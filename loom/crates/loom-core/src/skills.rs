use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use crate::capabilities::load_capability_registry;
use crate::onboarding::{load_onboard_manifest, OnboardManifest};
use crate::{io_err, read_config};

pub type LoomResult<T> = Result<T, String>;

pub const DEFAULT_SKILL_REGISTRY_PATH: &str = "state/skills/registry.json";
pub const DEFAULT_SKILL_INSTALLS_DIR: &str = "state/skills/installs";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SkillRecord {
    pub skill_id: String,
    pub kind: String,
    pub enabled: bool,
    pub install_state: String,
    pub node_manager: String,
    pub source_kind: String,
    pub source_ref: String,
    pub runtime_refs: Vec<String>,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SkillRuntimeOverview {
    pub registry_path: PathBuf,
    pub installs_path: PathBuf,
    pub total_count: usize,
    pub enabled_count: usize,
    pub default_count: usize,
    pub imported_count: usize,
    pub skill_ids: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SkillSyncResult {
    pub registry_path: PathBuf,
    pub total_count: usize,
    pub enabled_count: usize,
    pub default_count: usize,
    pub imported_count: usize,
    pub skill_ids: Vec<String>,
}

pub fn skill_registry_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_SKILL_REGISTRY_PATH)
}

pub fn skill_installs_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_SKILL_INSTALLS_DIR)
}

pub fn ensure_skill_runtime_scaffold(root: &Path) -> LoomResult<PathBuf> {
    let registry_path = skill_registry_path(root);
    if let Some(parent) = registry_path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    fs::create_dir_all(skill_installs_path(root)).map_err(io_err)?;
    if !registry_path.exists() {
        sync_skill_registry(root)?;
    }
    Ok(registry_path)
}

pub fn sync_skill_registry(root: &Path) -> LoomResult<SkillSyncResult> {
    let manifest = load_onboard_manifest(root)?;
    let mut records = skill_records_from_manifest(&manifest);
    let imported_records = imported_skill_records(root)?;
    records.extend(imported_records);
    let lifecycle_records = lifecycle_install_records(root);
    for rec in lifecycle_records {
        if !records.iter().any(|r| r.skill_id == rec.skill_id) {
            records.push(rec);
        }
    }
    records.sort_by(|left, right| left.skill_id.cmp(&right.skill_id));
    records.dedup_by(|left, right| left.skill_id == right.skill_id);
    persist_skill_registry(root, &records)?;
    Ok(SkillSyncResult {
        registry_path: skill_registry_path(root),
        total_count: records.len(),
        enabled_count: records.iter().filter(|record| record.enabled).count(),
        default_count: records
            .iter()
            .filter(|record| record.install_state == "default")
            .count(),
        imported_count: records
            .iter()
            .filter(|record| record.install_state == "imported")
            .count(),
        skill_ids: records
            .iter()
            .map(|record| record.skill_id.clone())
            .collect(),
    })
}

pub fn load_skills(root: &Path) -> LoomResult<Vec<SkillRecord>> {
    ensure_skill_runtime_scaffold(root)?;
    let raw = fs::read_to_string(skill_registry_path(root)).map_err(io_err)?;
    parse_skill_registry(&raw)
}

pub fn find_skill(root: &Path, skill_id: &str) -> LoomResult<SkillRecord> {
    let skill_id = skill_id.trim();
    if skill_id.is_empty() {
        return Err("skill_id is required".to_string());
    }
    load_skills(root)?
        .into_iter()
        .find(|record| record.skill_id == skill_id)
        .ok_or_else(|| format!("skill '{}' was not found", skill_id))
}

pub fn skill_overview(root: &Path) -> LoomResult<SkillRuntimeOverview> {
    let records = load_skills(root)?;
    Ok(SkillRuntimeOverview {
        registry_path: skill_registry_path(root),
        installs_path: skill_installs_path(root),
        total_count: records.len(),
        enabled_count: records.iter().filter(|record| record.enabled).count(),
        default_count: records
            .iter()
            .filter(|record| record.install_state == "default")
            .count(),
        imported_count: records
            .iter()
            .filter(|record| record.install_state == "imported")
            .count(),
        skill_ids: records
            .iter()
            .map(|record| record.skill_id.clone())
            .collect(),
    })
}

pub fn render_skill_overview_human(summary: &SkillRuntimeOverview) -> String {
    format!(
        "registry_path:   {}\ninstalls_path:   {}\ntotal_count:     {}\nenabled_count:   {}\ndefault_count:   {}\nimported_count:  {}\nskills:          {}\n",
        summary.registry_path.display(),
        summary.installs_path.display(),
        summary.total_count,
        summary.enabled_count,
        summary.default_count,
        summary.imported_count,
        if summary.skill_ids.is_empty() {
            "(none)".to_string()
        } else {
            summary.skill_ids.join(",")
        }
    )
}

pub fn render_skill_overview_json(summary: &SkillRuntimeOverview) -> String {
    serde_json::to_string_pretty(&json!({
        "registry_path": summary.registry_path.display().to_string(),
        "installs_path": summary.installs_path.display().to_string(),
        "total_count": summary.total_count,
        "enabled_count": summary.enabled_count,
        "default_count": summary.default_count,
        "imported_count": summary.imported_count,
        "skill_ids": summary.skill_ids,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_skill_sync_human(result: &SkillSyncResult) -> String {
    format!(
        "registry_path:   {}\ntotal_count:     {}\nenabled_count:   {}\ndefault_count:   {}\nimported_count:  {}\nskills:          {}\n",
        result.registry_path.display(),
        result.total_count,
        result.enabled_count,
        result.default_count,
        result.imported_count,
        if result.skill_ids.is_empty() {
            "(none)".to_string()
        } else {
            result.skill_ids.join(",")
        }
    )
}

pub fn render_skill_sync_json(result: &SkillSyncResult) -> String {
    serde_json::to_string_pretty(&json!({
        "registry_path": result.registry_path.display().to_string(),
        "total_count": result.total_count,
        "enabled_count": result.enabled_count,
        "default_count": result.default_count,
        "imported_count": result.imported_count,
        "skill_ids": result.skill_ids,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_skill_human(record: &SkillRecord) -> String {
    format!(
        "skill_id:          {}\nkind:              {}\nenabled:           {}\ninstall_state:     {}\nnode_manager:      {}\nsource_kind:       {}\nsource_ref:        {}\nruntime_refs:      {}\nnote:              {}\n",
        record.skill_id,
        record.kind,
        record.enabled,
        record.install_state,
        record.node_manager,
        record.source_kind,
        if record.source_ref.is_empty() { "(none)" } else { &record.source_ref },
        if record.runtime_refs.is_empty() {
            "(none)".to_string()
        } else {
            record.runtime_refs.join(",")
        },
        if record.note.is_empty() { "(none)" } else { &record.note },
    )
}

pub fn render_skill_json(record: &SkillRecord) -> String {
    serde_json::to_string_pretty(&skill_record_json(record)).unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_skill_list_human(records: &[SkillRecord]) -> String {
    if records.is_empty() {
        return "skill_count:       0\n".to_string();
    }
    let mut rendered = format!("skill_count:       {}\n", records.len());
    for record in records {
        rendered.push_str(&format!(
            "\n- {} kind={} state={} enabled={} refs={}\n",
            record.skill_id,
            record.kind,
            record.install_state,
            record.enabled,
            if record.runtime_refs.is_empty() {
                "(none)".to_string()
            } else {
                record.runtime_refs.join("|")
            }
        ));
    }
    rendered
}

pub fn render_skill_list_json(records: &[SkillRecord]) -> String {
    serde_json::to_string_pretty(&records.iter().map(skill_record_json).collect::<Vec<_>>())
        .unwrap_or_else(|_| "[]".to_string())
        + "\n"
}

fn skill_records_from_manifest(manifest: &OnboardManifest) -> Vec<SkillRecord> {
    let mut records = Vec::new();
    if !manifest.skills_install_defaults {
        return records;
    }
    for entry in &manifest.skills_entries {
        let skill_id = entry.trim();
        if skill_id.is_empty() {
            continue;
        }
        let (runtime_refs, note) = default_skill_runtime_refs(skill_id);
        records.push(SkillRecord {
            skill_id: skill_id.to_string(),
            kind: "runtime_default".to_string(),
            enabled: true,
            install_state: "default".to_string(),
            node_manager: manifest.skills_node_manager.clone(),
            source_kind: "onboard_manifest".to_string(),
            source_ref: "state/onboard.json".to_string(),
            runtime_refs,
            note,
        });
    }
    records
}

fn default_skill_runtime_refs(skill_id: &str) -> (Vec<String>, String) {
    match skill_id {
        "browser" => (
            vec!["capability:loom.browser.navigate.v1".to_string()],
            "bounded browser acquisition lane".to_string(),
        ),
        "telegram_bridge" => (
            vec!["channel:telegram".to_string()],
            "native Telegram edge wiring".to_string(),
        ),
        "web_bridge" => (
            vec!["channel:web_api".to_string()],
            "native web adapter edge wiring".to_string(),
        ),
        "governed_memory" => (
            vec![
                "capability:loom.fs.read.v1".to_string(),
                "capability:loom.fs.write.v1".to_string(),
            ],
            "bounded filesystem memory substrate".to_string(),
        ),
        other => (
            Vec::new(),
            format!("declared by onboarding manifest entry '{}'", other),
        ),
    }
}

fn imported_skill_records(root: &Path) -> LoomResult<Vec<SkillRecord>> {
    let config = match read_config(root) {
        Ok(config) => config,
        Err(_) => return Ok(Vec::new()),
    };
    let registry = match load_capability_registry(root, &config) {
        Ok(registry) => registry,
        Err(_) => return Ok(Vec::new()),
    };
    let mut records = Vec::new();
    for capability in registry.capabilities {
        if !capability.enabled {
            continue;
        }
        let is_skill = capability.action_type == "skill_exec"
            || capability.source_kind.contains("skill")
            || capability.adapter_kind.contains("skill");
        if !is_skill {
            continue;
        }
        records.push(SkillRecord {
            skill_id: capability.name.clone(),
            kind: "capability_import".to_string(),
            enabled: capability.enabled,
            install_state: "imported".to_string(),
            node_manager: "runtime".to_string(),
            source_kind: capability.source_kind.clone(),
            source_ref: if capability.source_path.is_empty() {
                capability.source_manifest.clone()
            } else {
                capability.source_path.clone()
            },
            runtime_refs: vec![capability.resource.clone()],
            note: capability.description.clone(),
        });
    }
    Ok(records)
}

fn lifecycle_install_records(root: &Path) -> Vec<SkillRecord> {
    let installs_dir = root.join(DEFAULT_SKILL_INSTALLS_DIR);
    let entries = match fs::read_dir(&installs_dir) {
        Ok(entries) => entries,
        Err(_) => return Vec::new(),
    };
    let mut records = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) != Some("json") {
            continue;
        }
        let raw = match fs::read_to_string(&path) {
            Ok(raw) => raw,
            Err(_) => continue,
        };
        let value: Value = match serde_json::from_str(&raw) {
            Ok(v) => v,
            Err(_) => continue,
        };
        let skill_id = match value.get("skill_id").and_then(Value::as_str) {
            Some(id) if !id.is_empty() => id.to_string(),
            _ => continue,
        };
        let enabled = value
            .get("enabled")
            .and_then(Value::as_bool)
            .unwrap_or(true);
        let source_ref = value
            .get("source_path")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        let note = value
            .get("description")
            .and_then(Value::as_str)
            .unwrap_or("lifecycle install")
            .to_string();
        records.push(SkillRecord {
            skill_id,
            kind: "lifecycle_install".to_string(),
            enabled,
            install_state: "installed".to_string(),
            node_manager: "runtime".to_string(),
            source_kind: "lifecycle".to_string(),
            source_ref,
            runtime_refs: Vec::new(),
            note,
        });
    }
    records
}

fn parse_skill_registry(raw: &str) -> LoomResult<Vec<SkillRecord>> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid skill registry json: {error}"))?;
    let skills = value
        .get("skills")
        .and_then(Value::as_array)
        .ok_or_else(|| "skill registry must define a skills array".to_string())?;
    let mut records = Vec::with_capacity(skills.len());
    for skill in skills {
        records.push(parse_skill_record(skill)?);
    }
    Ok(records)
}

fn parse_skill_record(value: &Value) -> LoomResult<SkillRecord> {
    Ok(SkillRecord {
        skill_id: value_string(value.get("skill_id"), "skill_id")?,
        kind: value_string_or(value.get("kind"), "runtime_default"),
        enabled: value
            .get("enabled")
            .and_then(Value::as_bool)
            .unwrap_or(true),
        install_state: value_string_or(value.get("install_state"), "default"),
        node_manager: value_string_or(value.get("node_manager"), "npm"),
        source_kind: value_string_or(value.get("source_kind"), "onboard_manifest"),
        source_ref: value_string_or(value.get("source_ref"), ""),
        runtime_refs: value_array_strings(value.get("runtime_refs")),
        note: value_string_or(value.get("note"), ""),
    })
}

fn persist_skill_registry(root: &Path, records: &[SkillRecord]) -> LoomResult<()> {
    let registry_path = skill_registry_path(root);
    if let Some(parent) = registry_path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    fs::create_dir_all(skill_installs_path(root)).map_err(io_err)?;
    let value = json!({
        "skills": records.iter().map(skill_record_json).collect::<Vec<_>>()
    });
    let mut rendered = serde_json::to_string_pretty(&value).map_err(|error| error.to_string())?;
    rendered.push('\n');
    fs::write(registry_path, rendered).map_err(io_err)
}

fn skill_record_json(record: &SkillRecord) -> Value {
    json!({
        "skill_id": record.skill_id,
        "kind": record.kind,
        "enabled": record.enabled,
        "install_state": record.install_state,
        "node_manager": record.node_manager,
        "source_kind": record.source_kind,
        "source_ref": record.source_ref,
        "runtime_refs": record.runtime_refs,
        "note": record.note,
    })
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

fn value_array_strings(value: Option<&Value>) -> Vec<String> {
    value
        .and_then(Value::as_array)
        .map(|entries| {
            entries
                .iter()
                .filter_map(Value::as_str)
                .map(|entry| entry.to_string())
                .collect::<Vec<_>>()
        })
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::capabilities::import_workspace_skill;
    use crate::{init_workspace, read_config};
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn sync_skill_registry_materializes_default_entries() {
        let root = temp_path("loom-skills-defaults");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        let summary = sync_skill_registry(&root).expect("sync skills");
        assert_eq!(summary.default_count, 4);
        assert_eq!(summary.imported_count, 0);
        let records = load_skills(&root).expect("load skills");
        assert!(records.iter().any(|record| {
            record.skill_id == "browser"
                && record.runtime_refs == vec!["capability:loom.browser.navigate.v1".to_string()]
        }));
    }

    #[test]
    fn sync_skill_registry_includes_imported_workspace_skills() {
        let root = temp_path("loom-skills-imported");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        let config = read_config(&root).expect("config");
        let skill_root = temp_path("loom-skills-import-root");
        fs::create_dir_all(skill_root.join("scripts")).expect("create scripts dir");
        fs::write(
            skill_root.join("clawskill.json"),
            r#"{
  "version": "clawfamily_skill_contract_v0",
  "name": "Sample triage",
  "description": "Imported sample triage skill",
  "entrypoint": "scripts/triage.py",
  "adapter_kind": "artifact_report_v0",
  "action_type": "skill_exec",
  "payload_mode": "json"
}
"#,
        )
        .expect("write skill manifest");
        fs::write(
            skill_root.join("scripts/triage.py"),
            r#"#!/usr/bin/env python3
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--artifact")
parser.add_argument("--out")
"#,
        )
        .expect("write skill script");
        import_workspace_skill(&root, &config, &skill_root, None, None)
            .expect("import workspace skill");

        let summary = sync_skill_registry(&root).expect("sync skills");
        assert!(summary.imported_count >= 1);
        let records = load_skills(&root).expect("load skills");
        assert!(records.iter().any(|record| {
            record.install_state == "imported"
                && record
                    .runtime_refs
                    .iter()
                    .any(|item| item.contains("capability:loomskill.sample-triage.v0"))
        }));
    }

    fn temp_path(label: &str) -> PathBuf {
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        std::env::temp_dir().join(format!("{}-{}", label, timestamp))
    }
}
