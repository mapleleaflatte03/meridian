use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

use crate::skills::{sync_skill_registry, DEFAULT_SKILL_INSTALLS_DIR};

pub type LoomResult<T> = Result<T, String>;

const DEFAULT_SKILL_LOCKS_PATH: &str = "state/skills/locks.json";
const DEFAULT_SKILL_RECEIPTS_PATH: &str = "state/skills/receipts.jsonl";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SkillInstallRecord {
    pub skill_id: String,
    pub source_path: String,
    pub installed_at: String,
    pub enabled: bool,
    pub locked: bool,
    pub skill_type: String,
    pub display_name: Option<String>,
    pub description: Option<String>,
    pub capabilities: Vec<String>,
    pub version: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SkillLockEntry {
    pub skill_id: String,
    pub locked_at: String,
    pub locked_by: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SkillLifecycleReceipt {
    pub action: String,
    pub skill_id: String,
    pub timestamp: String,
    pub success: bool,
    pub message: String,
}

pub fn skill_installs_dir(root: &Path) -> PathBuf {
    root.join(DEFAULT_SKILL_INSTALLS_DIR)
}

pub fn skill_locks_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_SKILL_LOCKS_PATH)
}

pub fn skill_receipts_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_SKILL_RECEIPTS_PATH)
}

pub fn skill_install_record_path(root: &Path, skill_id: &str) -> PathBuf {
    skill_installs_dir(root).join(format!("{}.json", safe_filename(skill_id)))
}

pub fn ensure_skill_lifecycle_scaffold(root: &Path) -> LoomResult<PathBuf> {
    let installs_dir = skill_installs_dir(root);
    fs::create_dir_all(&installs_dir).map_err(io_err)?;
    let locks_path = skill_locks_path(root);
    if !locks_path.exists() {
        fs::write(&locks_path, "{\n  \"locks\": []\n}\n").map_err(io_err)?;
    }
    Ok(installs_dir)
}

pub fn install_skill(
    root: &Path,
    source_root: &Path,
    skill_id_override: Option<&str>,
) -> LoomResult<SkillLifecycleReceipt> {
    ensure_skill_lifecycle_scaffold(root)?;

    // Detect skill manifest
    let manifest_path = detect_skill_manifest(source_root);
    let (detected_id, display_name, description, capabilities, version) =
        read_skill_manifest(source_root, manifest_path.as_deref());

    let skill_id = skill_id_override
        .map(str::trim)
        .filter(|v| !v.is_empty())
        .map(str::to_string)
        .or(detected_id)
        .unwrap_or_else(|| {
            source_root
                .file_name()
                .and_then(|n| n.to_str())
                .map(safe_filename)
                .unwrap_or_else(|| "unknown-skill".to_string())
        });

    if skill_id.is_empty() {
        return receipt_err("install", &skill_id, "skill_id could not be determined");
    }

    // Check if already installed
    let install_path = skill_install_record_path(root, &skill_id);
    if install_path.exists() {
        // Update source path and metadata but keep enabled/locked state
        let mut existing = load_install_record(root, &skill_id)?;
        existing.source_path = source_root.to_string_lossy().to_string();
        if let Some(dn) = display_name {
            existing.display_name = Some(dn);
        }
        if let Some(desc) = description {
            existing.description = Some(desc);
        }
        persist_install_record(root, &existing)?;
        append_receipt(
            root,
            &make_receipt("install", &skill_id, true, "updated existing install"),
        )?;
        let _ = sync_skill_registry(root);
        return Ok(make_receipt(
            "install",
            &skill_id,
            true,
            "updated existing install",
        ));
    }

    let record = SkillInstallRecord {
        skill_id: skill_id.clone(),
        source_path: source_root.to_string_lossy().to_string(),
        installed_at: timestamp_now(),
        enabled: true,
        locked: false,
        skill_type: "imported".to_string(),
        display_name,
        description,
        capabilities,
        version,
    };

    persist_install_record(root, &record)?;
    append_receipt(
        root,
        &make_receipt("install", &skill_id, true, "installed from source"),
    )?;

    // Rebuild skill registry to include this install
    let _ = sync_skill_registry(root);

    Ok(make_receipt(
        "install",
        &skill_id,
        true,
        "installed from source",
    ))
}

pub fn remove_skill(root: &Path, skill_id: &str, force: bool) -> LoomResult<SkillLifecycleReceipt> {
    ensure_skill_lifecycle_scaffold(root)?;
    let skill_id = skill_id.trim();
    if skill_id.is_empty() {
        return receipt_err("remove", skill_id, "skill_id is required");
    }

    let install_path = skill_install_record_path(root, skill_id);
    if !install_path.exists() {
        return receipt_err("remove", skill_id, "skill not installed via lifecycle");
    }

    // Check lock
    let record = load_install_record(root, skill_id)?;
    if record.locked && !force {
        return receipt_err(
            "remove",
            skill_id,
            "skill is locked; use --force to override",
        );
    }

    fs::remove_file(&install_path).map_err(io_err)?;
    append_receipt(
        root,
        &make_receipt("remove", skill_id, true, "removed install record"),
    )?;
    let _ = sync_skill_registry(root);
    Ok(make_receipt(
        "remove",
        skill_id,
        true,
        "removed install record",
    ))
}

pub fn enable_skill(root: &Path, skill_id: &str) -> LoomResult<SkillLifecycleReceipt> {
    mutate_install_record(root, skill_id, "enable", |record| {
        record.enabled = true;
    })
}

pub fn disable_skill(root: &Path, skill_id: &str) -> LoomResult<SkillLifecycleReceipt> {
    mutate_install_record(root, skill_id, "disable", |record| {
        record.enabled = false;
    })
}

pub fn update_skill_metadata(
    root: &Path,
    skill_id: &str,
    display_name: Option<&str>,
    description: Option<&str>,
    version: Option<&str>,
) -> LoomResult<SkillLifecycleReceipt> {
    let skill_id = skill_id.trim();
    ensure_skill_lifecycle_scaffold(root)?;
    if !skill_install_record_path(root, skill_id).exists() {
        return receipt_err("update", skill_id, "skill not installed via lifecycle");
    }
    let mut record = load_install_record(root, skill_id)?;
    if let Some(dn) = display_name.map(str::trim).filter(|v| !v.is_empty()) {
        record.display_name = Some(dn.to_string());
    }
    if let Some(desc) = description.map(str::trim).filter(|v| !v.is_empty()) {
        record.description = Some(desc.to_string());
    }
    if let Some(ver) = version.map(str::trim).filter(|v| !v.is_empty()) {
        record.version = Some(ver.to_string());
    }
    persist_install_record(root, &record)?;
    append_receipt(
        root,
        &make_receipt("update", skill_id, true, "metadata updated"),
    )?;
    let _ = sync_skill_registry(root);
    Ok(make_receipt("update", skill_id, true, "metadata updated"))
}

pub fn lock_skill(root: &Path, skill_id: &str) -> LoomResult<SkillLifecycleReceipt> {
    let skill_id = skill_id.trim();
    ensure_skill_lifecycle_scaffold(root)?;
    if !skill_install_record_path(root, skill_id).exists() {
        return receipt_err("lock", skill_id, "skill not installed via lifecycle");
    }
    let mut record = load_install_record(root, skill_id)?;
    record.locked = true;
    persist_install_record(root, &record)?;

    // Add to locks.json
    let mut locks = load_skill_locks(root)?;
    locks.retain(|l| l.skill_id != skill_id);
    locks.push(SkillLockEntry {
        skill_id: skill_id.to_string(),
        locked_at: timestamp_now(),
        locked_by: "user".to_string(),
    });
    persist_skill_locks(root, &locks)?;
    append_receipt(root, &make_receipt("lock", skill_id, true, "skill locked"))?;
    Ok(make_receipt("lock", skill_id, true, "skill locked"))
}

pub fn unlock_skill(root: &Path, skill_id: &str) -> LoomResult<SkillLifecycleReceipt> {
    let skill_id = skill_id.trim();
    ensure_skill_lifecycle_scaffold(root)?;
    if !skill_install_record_path(root, skill_id).exists() {
        return receipt_err("unlock", skill_id, "skill not installed via lifecycle");
    }
    let mut record = load_install_record(root, skill_id)?;
    record.locked = false;
    persist_install_record(root, &record)?;

    let mut locks = load_skill_locks(root)?;
    locks.retain(|l| l.skill_id != skill_id);
    persist_skill_locks(root, &locks)?;
    append_receipt(
        root,
        &make_receipt("unlock", skill_id, true, "skill unlocked"),
    )?;
    Ok(make_receipt("unlock", skill_id, true, "skill unlocked"))
}

pub fn list_skill_locks(root: &Path) -> LoomResult<Vec<SkillLockEntry>> {
    ensure_skill_lifecycle_scaffold(root)?;
    load_skill_locks(root)
}

pub fn list_skill_installs(root: &Path) -> LoomResult<Vec<SkillInstallRecord>> {
    ensure_skill_lifecycle_scaffold(root)?;
    let installs_dir = skill_installs_dir(root);
    let entries = match fs::read_dir(&installs_dir) {
        Ok(entries) => entries,
        Err(_) => return Ok(Vec::new()),
    };
    let mut records = Vec::new();
    for entry in entries.filter_map(|e| e.ok()) {
        let path = entry.path();
        if path.extension().and_then(|ext| ext.to_str()) != Some("json") {
            continue;
        }
        let raw = match fs::read_to_string(&path) {
            Ok(raw) => raw,
            Err(_) => continue,
        };
        if let Ok(record) = parse_install_record(&raw) {
            records.push(record);
        }
    }
    records.sort_by(|a, b| a.skill_id.cmp(&b.skill_id));
    Ok(records)
}

pub fn load_install_record(root: &Path, skill_id: &str) -> LoomResult<SkillInstallRecord> {
    let path = skill_install_record_path(root, skill_id);
    if !path.exists() {
        return Err(format!("install record for '{}' not found", skill_id));
    }
    let raw = fs::read_to_string(&path).map_err(io_err)?;
    parse_install_record(&raw)
}

// --- render ---

pub fn render_skill_install_human(record: &SkillInstallRecord) -> String {
    format!(
        "skill_id:          {}\nskill_type:        {}\nenabled:           {}\nlocked:            {}\nsource_path:       {}\ninstalled_at:      {}\ndisplay_name:      {}\ndescription:       {}\nversion:           {}\ncapabilities:      {}\n",
        record.skill_id,
        record.skill_type,
        record.enabled,
        record.locked,
        record.source_path,
        record.installed_at,
        record.display_name.as_deref().unwrap_or("(none)"),
        record.description.as_deref().unwrap_or("(none)"),
        record.version.as_deref().unwrap_or("(none)"),
        if record.capabilities.is_empty() {
            "(none)".to_string()
        } else {
            record.capabilities.join(",")
        }
    )
}

pub fn render_skill_install_json(record: &SkillInstallRecord) -> String {
    serde_json::to_string_pretty(&install_record_json(record)).unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_skill_installs_list_human(records: &[SkillInstallRecord]) -> String {
    if records.is_empty() {
        return "install_count:     0\n".to_string();
    }
    let mut out = format!("install_count:     {}\n", records.len());
    for r in records {
        out.push_str(&format!(
            "\n- {} type={} enabled={} locked={}\n",
            r.skill_id, r.skill_type, r.enabled, r.locked
        ));
    }
    out
}

pub fn render_skill_lifecycle_receipt_human(receipt: &SkillLifecycleReceipt) -> String {
    format!(
        "action:            {}\nskill_id:          {}\ntimestamp:         {}\nsuccess:           {}\nmessage:           {}\n",
        receipt.action,
        receipt.skill_id,
        receipt.timestamp,
        receipt.success,
        receipt.message,
    )
}

pub fn render_skill_lifecycle_receipt_json(receipt: &SkillLifecycleReceipt) -> String {
    serde_json::to_string_pretty(&json!({
        "action": receipt.action,
        "skill_id": receipt.skill_id,
        "timestamp": receipt.timestamp,
        "success": receipt.success,
        "message": receipt.message,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_skill_locks_human(locks: &[SkillLockEntry]) -> String {
    if locks.is_empty() {
        return "lock_count:        0\n".to_string();
    }
    let mut out = format!("lock_count:        {}\n", locks.len());
    for l in locks {
        out.push_str(&format!(
            "\n- {} locked_by={} locked_at={}\n",
            l.skill_id, l.locked_by, l.locked_at
        ));
    }
    out
}

// --- internal ---

fn mutate_install_record<F>(
    root: &Path,
    skill_id: &str,
    action: &str,
    mutate: F,
) -> LoomResult<SkillLifecycleReceipt>
where
    F: FnOnce(&mut SkillInstallRecord),
{
    let skill_id = skill_id.trim();
    ensure_skill_lifecycle_scaffold(root)?;
    if !skill_install_record_path(root, skill_id).exists() {
        return receipt_err(action, skill_id, "skill not installed via lifecycle");
    }
    let mut record = load_install_record(root, skill_id)?;
    mutate(&mut record);
    persist_install_record(root, &record)?;
    let msg = format!("skill {} applied", action);
    append_receipt(root, &make_receipt(action, skill_id, true, &msg))?;
    let _ = sync_skill_registry(root);
    Ok(make_receipt(action, skill_id, true, &msg))
}

fn persist_install_record(root: &Path, record: &SkillInstallRecord) -> LoomResult<()> {
    ensure_skill_lifecycle_scaffold(root)?;
    let path = skill_install_record_path(root, &record.skill_id);
    let mut rendered =
        serde_json::to_string_pretty(&install_record_json(record)).map_err(|e| e.to_string())?;
    rendered.push('\n');
    fs::write(path, rendered).map_err(io_err)
}

fn load_skill_locks(root: &Path) -> LoomResult<Vec<SkillLockEntry>> {
    let locks_path = skill_locks_path(root);
    if !locks_path.exists() {
        return Ok(Vec::new());
    }
    let raw = fs::read_to_string(&locks_path).map_err(io_err)?;
    let value: Value =
        serde_json::from_str(&raw).map_err(|e| format!("invalid locks json: {e}"))?;
    let items = value
        .get("locks")
        .and_then(Value::as_array)
        .ok_or_else(|| "locks.json must define a locks array".to_string())?;
    let mut locks = Vec::new();
    for item in items {
        let skill_id = item
            .get("skill_id")
            .and_then(Value::as_str)
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty());
        if let Some(skill_id) = skill_id {
            locks.push(SkillLockEntry {
                skill_id,
                locked_at: item
                    .get("locked_at")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string(),
                locked_by: item
                    .get("locked_by")
                    .and_then(Value::as_str)
                    .unwrap_or("user")
                    .to_string(),
            });
        }
    }
    Ok(locks)
}

fn persist_skill_locks(root: &Path, locks: &[SkillLockEntry]) -> LoomResult<()> {
    let locks_path = skill_locks_path(root);
    let value = json!({
        "locks": locks.iter().map(|l| json!({
            "skill_id": l.skill_id,
            "locked_at": l.locked_at,
            "locked_by": l.locked_by,
        })).collect::<Vec<_>>()
    });
    let mut rendered = serde_json::to_string_pretty(&value).map_err(|e| e.to_string())?;
    rendered.push('\n');
    fs::write(locks_path, rendered).map_err(io_err)
}

fn append_receipt(root: &Path, receipt: &SkillLifecycleReceipt) -> LoomResult<()> {
    let receipts_path = skill_receipts_path(root);
    let line = serde_json::to_string(&json!({
        "action": receipt.action,
        "skill_id": receipt.skill_id,
        "timestamp": receipt.timestamp,
        "success": receipt.success,
        "message": receipt.message,
    }))
    .unwrap_or_default();
    let content = if receipts_path.exists() {
        format!(
            "{}\n{}\n",
            fs::read_to_string(&receipts_path)
                .unwrap_or_default()
                .trim_end(),
            line
        )
    } else {
        format!("{}\n", line)
    };
    fs::write(receipts_path, content).map_err(io_err)
}

fn detect_skill_manifest(source_root: &Path) -> Option<PathBuf> {
    for name in &["skill.json", "loomskill.json", "clawskill.json"] {
        let path = source_root.join(name);
        if path.exists() {
            return Some(path);
        }
    }
    None
}

fn read_skill_manifest(
    source_root: &Path,
    manifest_path: Option<&Path>,
) -> (
    Option<String>,
    Option<String>,
    Option<String>,
    Vec<String>,
    Option<String>,
) {
    let Some(path) = manifest_path else {
        return (None, None, None, Vec::new(), None);
    };
    let raw = match fs::read_to_string(path) {
        Ok(raw) => raw,
        Err(_) => return (None, None, None, Vec::new(), None),
    };
    let value: Value = match serde_json::from_str(&raw) {
        Ok(v) => v,
        Err(_) => return (None, None, None, Vec::new(), None),
    };
    let detect_id = value
        .get("name")
        .and_then(Value::as_str)
        .map(safe_filename)
        .filter(|s| !s.is_empty())
        .or_else(|| {
            source_root
                .file_name()
                .and_then(|n| n.to_str())
                .map(safe_filename)
        });
    let display_name = value
        .get("name")
        .and_then(Value::as_str)
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty());
    let description = value
        .get("description")
        .and_then(Value::as_str)
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty());
    let version = value
        .get("version")
        .and_then(Value::as_str)
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty());
    let capabilities = value
        .get("capabilities")
        .and_then(Value::as_array)
        .map(|arr| {
            arr.iter()
                .filter_map(Value::as_str)
                .map(|s| s.to_string())
                .collect()
        })
        .unwrap_or_default();
    (detect_id, display_name, description, capabilities, version)
}

fn parse_install_record(raw: &str) -> LoomResult<SkillInstallRecord> {
    let value: Value =
        serde_json::from_str(raw).map_err(|e| format!("invalid install record json: {e}"))?;
    Ok(SkillInstallRecord {
        skill_id: value_string(value.get("skill_id"), "skill_id")?,
        source_path: value_string_or(value.get("source_path"), ""),
        installed_at: value_string_or(value.get("installed_at"), ""),
        enabled: value
            .get("enabled")
            .and_then(Value::as_bool)
            .unwrap_or(true),
        locked: value
            .get("locked")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        skill_type: value_string_or(value.get("skill_type"), "imported"),
        display_name: value_opt_string(value.get("display_name")),
        description: value_opt_string(value.get("description")),
        capabilities: value
            .get("capabilities")
            .and_then(Value::as_array)
            .map(|arr| {
                arr.iter()
                    .filter_map(Value::as_str)
                    .map(|s| s.to_string())
                    .collect()
            })
            .unwrap_or_default(),
        version: value_opt_string(value.get("version")),
    })
}

fn install_record_json(record: &SkillInstallRecord) -> Value {
    json!({
        "skill_id": record.skill_id,
        "source_path": record.source_path,
        "installed_at": record.installed_at,
        "enabled": record.enabled,
        "locked": record.locked,
        "skill_type": record.skill_type,
        "display_name": record.display_name,
        "description": record.description,
        "capabilities": record.capabilities,
        "version": record.version,
    })
}

fn make_receipt(
    action: &str,
    skill_id: &str,
    success: bool,
    message: &str,
) -> SkillLifecycleReceipt {
    SkillLifecycleReceipt {
        action: action.to_string(),
        skill_id: skill_id.to_string(),
        timestamp: timestamp_now(),
        success,
        message: message.to_string(),
    }
}

fn receipt_err(action: &str, skill_id: &str, message: &str) -> LoomResult<SkillLifecycleReceipt> {
    Err(format!(
        "skill lifecycle {} '{}': {}",
        action, skill_id, message
    ))
}

fn safe_filename(input: &str) -> String {
    input
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || ch == '-' || ch == '_' {
                ch.to_ascii_lowercase()
            } else {
                '-'
            }
        })
        .collect()
}

fn timestamp_now() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    format!("{}", secs)
}

fn io_err(error: std::io::Error) -> String {
    error.to_string()
}

fn value_string(value: Option<&Value>, label: &str) -> LoomResult<String> {
    value
        .and_then(Value::as_str)
        .map(|raw| raw.trim().to_string())
        .filter(|raw| !raw.is_empty())
        .ok_or_else(|| format!("{label} must not be empty"))
}

fn value_string_or(value: Option<&Value>, fallback: &str) -> String {
    value
        .and_then(Value::as_str)
        .map(|raw| raw.trim().to_string())
        .unwrap_or_else(|| fallback.to_string())
}

fn value_opt_string(value: Option<&Value>) -> Option<String> {
    value
        .and_then(Value::as_str)
        .map(|raw| raw.trim().to_string())
        .filter(|raw| !raw.is_empty())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::init_workspace;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_path(label: &str) -> PathBuf {
        let ts = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        std::env::temp_dir().join(format!("{}-{}", label, ts))
    }

    fn make_skill_root(label: &str) -> PathBuf {
        let skill_root = temp_path(label);
        fs::create_dir_all(&skill_root).expect("create skill dir");
        fs::write(
            skill_root.join("skill.json"),
            r#"{"name": "test-skill", "description": "A test skill"}"#,
        )
        .expect("write skill manifest");
        skill_root
    }

    #[test]
    fn install_skill_creates_install_record() {
        let root = temp_path("loom-skill-lifecycle-install");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        let skill_root = make_skill_root("loom-skill-src-install");
        let receipt = install_skill(&root, &skill_root, None).expect("install");
        assert!(receipt.success);

        let installs = list_skill_installs(&root).expect("list installs");
        assert!(!installs.is_empty());
        assert!(installs.iter().any(|r| r.enabled));
    }

    #[test]
    fn disable_then_enable_skill() {
        let root = temp_path("loom-skill-lifecycle-toggle");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        let skill_root = make_skill_root("loom-skill-src-toggle");
        let receipt = install_skill(&root, &skill_root, Some("toggle-skill")).expect("install");
        assert!(receipt.success);

        let receipt = disable_skill(&root, "toggle-skill").expect("disable");
        assert!(receipt.success);
        let record = load_install_record(&root, "toggle-skill").expect("load");
        assert!(!record.enabled);

        let receipt = enable_skill(&root, "toggle-skill").expect("enable");
        assert!(receipt.success);
        let record = load_install_record(&root, "toggle-skill").expect("load");
        assert!(record.enabled);
    }

    #[test]
    fn remove_skill_deletes_record() {
        let root = temp_path("loom-skill-lifecycle-remove");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        let skill_root = make_skill_root("loom-skill-src-remove");
        install_skill(&root, &skill_root, Some("removable-skill")).expect("install");

        let receipt = remove_skill(&root, "removable-skill", false).expect("remove");
        assert!(receipt.success);

        let path = skill_install_record_path(&root, "removable-skill");
        assert!(!path.exists());
    }

    #[test]
    fn lock_prevents_remove_without_force() {
        let root = temp_path("loom-skill-lifecycle-lock");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        let skill_root = make_skill_root("loom-skill-src-lock");
        install_skill(&root, &skill_root, Some("locked-skill")).expect("install");
        lock_skill(&root, "locked-skill").expect("lock");

        let result = remove_skill(&root, "locked-skill", false);
        assert!(result.is_err());

        let locks = list_skill_locks(&root).expect("list locks");
        assert!(locks.iter().any(|l| l.skill_id == "locked-skill"));
    }
}
