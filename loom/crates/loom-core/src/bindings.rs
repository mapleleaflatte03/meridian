use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use crate::agent_runtime::load_agent_runtime_registry;
use crate::channels::load_channels;
use crate::io_err;
use crate::onboarding::load_onboard_manifest;
use crate::session_provenance::open_session_provenance;

pub type LoomResult<T> = Result<T, String>;

pub const DEFAULT_BINDING_REGISTRY_PATH: &str = "state/bindings/registry.json";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BindingRecord {
    pub binding_id: String,
    pub channel_id: String,
    pub agent_id: String,
    pub session_scope: String,
    pub route_kind: String,
    pub enabled: bool,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BindingRuntimeOverview {
    pub registry_path: PathBuf,
    pub total_count: usize,
    pub enabled_count: usize,
    pub binding_ids: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BindingSyncResult {
    pub registry_path: PathBuf,
    pub total_count: usize,
    pub enabled_count: usize,
    pub binding_ids: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BindingResolution {
    pub binding_id: String,
    pub channel_id: String,
    pub peer_id: String,
    pub thread_id: Option<String>,
    pub agent_id: String,
    pub session_scope: String,
    pub session_key: String,
    pub route_kind: String,
}

pub fn binding_registry_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_BINDING_REGISTRY_PATH)
}

pub fn ensure_binding_runtime_scaffold(root: &Path) -> LoomResult<PathBuf> {
    let registry_path = binding_registry_path(root);
    if let Some(parent) = registry_path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    if !registry_path.exists() {
        sync_binding_registry(root)?;
    }
    Ok(registry_path)
}

pub fn sync_binding_registry(root: &Path) -> LoomResult<BindingSyncResult> {
    let manifest = load_onboard_manifest(root)?;
    let channels = load_channels(root)?;
    let agents = load_agent_runtime_registry(root)?;
    let default_agent_id = agents
        .iter()
        .find(|profile| profile.agent_id == "leviathann")
        .map(|profile| profile.agent_id.clone())
        .or_else(|| agents.first().map(|profile| profile.agent_id.clone()))
        .unwrap_or_else(|| "leviathann".to_string());
    let records = channels
        .iter()
        .map(|channel| {
            default_binding_record(channel, &manifest.session_dm_scope, &default_agent_id)
        })
        .collect::<Vec<_>>();
    persist_binding_registry(root, &records)?;
    Ok(BindingSyncResult {
        registry_path: binding_registry_path(root),
        total_count: records.len(),
        enabled_count: records.iter().filter(|record| record.enabled).count(),
        binding_ids: records
            .iter()
            .map(|record| record.binding_id.clone())
            .collect(),
    })
}

pub fn load_bindings(root: &Path) -> LoomResult<Vec<BindingRecord>> {
    ensure_binding_runtime_scaffold(root)?;
    let raw = fs::read_to_string(binding_registry_path(root)).map_err(io_err)?;
    parse_binding_registry(&raw)
}

pub fn binding_overview(root: &Path) -> LoomResult<BindingRuntimeOverview> {
    let records = load_bindings(root)?;
    Ok(BindingRuntimeOverview {
        registry_path: binding_registry_path(root),
        total_count: records.len(),
        enabled_count: records.iter().filter(|record| record.enabled).count(),
        binding_ids: records
            .iter()
            .map(|record| record.binding_id.clone())
            .collect(),
    })
}

pub fn find_binding(root: &Path, binding_id: &str) -> LoomResult<BindingRecord> {
    let binding_id = binding_id.trim();
    if binding_id.is_empty() {
        return Err("binding_id is required".to_string());
    }
    load_bindings(root)?
        .into_iter()
        .find(|record| record.binding_id == binding_id)
        .ok_or_else(|| format!("binding '{}' was not found", binding_id))
}

pub fn resolve_binding(
    root: &Path,
    channel_id: &str,
    peer_id: &str,
    thread_id: Option<&str>,
    agent_override: Option<&str>,
) -> LoomResult<BindingResolution> {
    let channel_id = channel_id.trim();
    if channel_id.is_empty() {
        return Err("channel_id is required".to_string());
    }
    let peer_id = peer_id.trim();
    if peer_id.is_empty() {
        return Err("peer_id is required".to_string());
    }
    let record = load_bindings(root)?
        .into_iter()
        .find(|candidate| candidate.channel_id == channel_id)
        .ok_or_else(|| format!("no binding registered for channel '{}'", channel_id))?;
    if !record.enabled {
        return Err(format!("binding '{}' is disabled", record.binding_id));
    }
    let agent_id = agent_override
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or(&record.agent_id)
        .to_string();
    let normalized_thread = thread_id
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(|value| value.to_string());
    let session_key = match record.session_scope.as_str() {
        "global" => "global".to_string(),
        "agent" | "per-agent" => format!("agent:{}", agent_id),
        "per-channel-thread" => format!(
            "{}:{}",
            channel_id,
            normalized_thread.as_deref().unwrap_or(peer_id)
        ),
        _ => format!("{}:{}", channel_id, peer_id),
    };
    let resolution = BindingResolution {
        binding_id: record.binding_id.clone(),
        channel_id: channel_id.to_string(),
        peer_id: peer_id.to_string(),
        thread_id: normalized_thread,
        agent_id: agent_id.clone(),
        session_scope: record.session_scope,
        session_key: session_key.clone(),
        route_kind: record.route_kind,
    };
    // Open (or refresh) session provenance — best effort, do not fail the binding resolution
    let _ = open_session_provenance(
        root,
        &session_key,
        channel_id,
        peer_id,
        &agent_id,
        &record.binding_id,
    );
    Ok(resolution)
}

pub fn render_binding_overview_human(summary: &BindingRuntimeOverview) -> String {
    format!(
        "registry_path:   {}\ntotal_count:     {}\nenabled_count:   {}\nbindings:        {}\n",
        summary.registry_path.display(),
        summary.total_count,
        summary.enabled_count,
        if summary.binding_ids.is_empty() {
            "(none)".to_string()
        } else {
            summary.binding_ids.join(",")
        }
    )
}

pub fn render_binding_overview_json(summary: &BindingRuntimeOverview) -> String {
    serde_json::to_string_pretty(&json!({
        "registry_path": summary.registry_path.display().to_string(),
        "total_count": summary.total_count,
        "enabled_count": summary.enabled_count,
        "binding_ids": summary.binding_ids,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_binding_sync_human(result: &BindingSyncResult) -> String {
    format!(
        "registry_path:   {}\ntotal_count:     {}\nenabled_count:   {}\nbindings:        {}\n",
        result.registry_path.display(),
        result.total_count,
        result.enabled_count,
        if result.binding_ids.is_empty() {
            "(none)".to_string()
        } else {
            result.binding_ids.join(",")
        }
    )
}

pub fn render_binding_sync_json(result: &BindingSyncResult) -> String {
    serde_json::to_string_pretty(&json!({
        "registry_path": result.registry_path.display().to_string(),
        "total_count": result.total_count,
        "enabled_count": result.enabled_count,
        "binding_ids": result.binding_ids,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_binding_human(record: &BindingRecord) -> String {
    format!(
        "binding_id:        {}\nchannel_id:        {}\nagent_id:          {}\nsession_scope:     {}\nroute_kind:        {}\nenabled:           {}\nnote:              {}\n",
        record.binding_id,
        record.channel_id,
        record.agent_id,
        record.session_scope,
        record.route_kind,
        record.enabled,
        if record.note.is_empty() { "(none)" } else { &record.note },
    )
}

pub fn render_binding_json(record: &BindingRecord) -> String {
    serde_json::to_string_pretty(&binding_record_json(record)).unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_binding_list_human(records: &[BindingRecord]) -> String {
    if records.is_empty() {
        return "binding_count:     0\n".to_string();
    }
    let mut rendered = format!("binding_count:     {}\n", records.len());
    for record in records {
        rendered.push_str(&format!(
            "\n- {} channel={} agent={} scope={} enabled={}\n",
            record.binding_id,
            record.channel_id,
            record.agent_id,
            record.session_scope,
            record.enabled,
        ));
    }
    rendered
}

pub fn render_binding_list_json(records: &[BindingRecord]) -> String {
    serde_json::to_string_pretty(&records.iter().map(binding_record_json).collect::<Vec<_>>())
        .unwrap_or_else(|_| "[]".to_string())
        + "\n"
}

pub fn render_binding_resolution_human(resolution: &BindingResolution) -> String {
    format!(
        "binding_id:        {}\nchannel_id:        {}\npeer_id:           {}\nthread_id:         {}\nagent_id:          {}\nsession_scope:     {}\nsession_key:       {}\nroute_kind:        {}\n",
        resolution.binding_id,
        resolution.channel_id,
        resolution.peer_id,
        resolution.thread_id.as_deref().unwrap_or("(none)"),
        resolution.agent_id,
        resolution.session_scope,
        resolution.session_key,
        resolution.route_kind,
    )
}

pub fn render_binding_resolution_json(resolution: &BindingResolution) -> String {
    serde_json::to_string_pretty(&json!({
        "binding_id": resolution.binding_id,
        "channel_id": resolution.channel_id,
        "peer_id": resolution.peer_id,
        "thread_id": resolution.thread_id,
        "agent_id": resolution.agent_id,
        "session_scope": resolution.session_scope,
        "session_key": resolution.session_key,
        "route_kind": resolution.route_kind,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

fn default_binding_record(
    channel: &crate::channels::ChannelRecord,
    session_scope: &str,
    default_agent_id: &str,
) -> BindingRecord {
    BindingRecord {
        binding_id: format!("binding-{}", channel.channel_id),
        channel_id: channel.channel_id.clone(),
        agent_id: default_agent_id.to_string(),
        session_scope: normalized_scope(session_scope),
        route_kind: "default_manager".to_string(),
        enabled: channel.enabled,
        note: format!("channel={} dm_policy={}", channel.kind, channel.dm_policy),
    }
}

fn normalized_scope(raw: &str) -> String {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        "per-channel-peer".to_string()
    } else {
        trimmed.to_string()
    }
}

fn parse_binding_registry(raw: &str) -> LoomResult<Vec<BindingRecord>> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid binding registry json: {error}"))?;
    let bindings = value
        .get("bindings")
        .and_then(Value::as_array)
        .ok_or_else(|| "binding registry must define a bindings array".to_string())?;
    let mut records = Vec::with_capacity(bindings.len());
    for binding in bindings {
        records.push(parse_binding_record(binding)?);
    }
    Ok(records)
}

fn parse_binding_record(value: &Value) -> LoomResult<BindingRecord> {
    Ok(BindingRecord {
        binding_id: value_string(value.get("binding_id"), "binding_id")?,
        channel_id: value_string(value.get("channel_id"), "channel_id")?,
        agent_id: value_string(value.get("agent_id"), "agent_id")?,
        session_scope: value_string_or(value.get("session_scope"), "per-channel-peer"),
        route_kind: value_string_or(value.get("route_kind"), "default_manager"),
        enabled: value
            .get("enabled")
            .and_then(Value::as_bool)
            .unwrap_or(true),
        note: value_string_or(value.get("note"), ""),
    })
}

fn persist_binding_registry(root: &Path, records: &[BindingRecord]) -> LoomResult<()> {
    let registry_path = binding_registry_path(root);
    if let Some(parent) = registry_path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    let value = json!({
        "bindings": records.iter().map(binding_record_json).collect::<Vec<_>>()
    });
    let mut rendered = serde_json::to_string_pretty(&value).map_err(|error| error.to_string())?;
    rendered.push('\n');
    fs::write(registry_path, rendered).map_err(io_err)
}

fn binding_record_json(record: &BindingRecord) -> Value {
    json!({
        "binding_id": record.binding_id,
        "channel_id": record.channel_id,
        "agent_id": record.agent_id,
        "session_scope": record.session_scope,
        "route_kind": record.route_kind,
        "enabled": record.enabled,
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::channels::sync_channel_registry;
    use crate::init_workspace;
    use crate::onboarding::{load_onboard_manifest, write_onboard_manifest};
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn sync_binding_registry_materializes_channel_defaults() {
        let root = temp_path("loom-binding-defaults");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        let mut manifest = load_onboard_manifest(&root).expect("load manifest");
        manifest.telegram_enabled = true;
        write_onboard_manifest(&root, &manifest).expect("write manifest");
        sync_channel_registry(&root).expect("sync channels");

        let summary = sync_binding_registry(&root).expect("sync bindings");
        assert_eq!(summary.total_count, 2);
        assert_eq!(summary.enabled_count, 2);
        let records = load_bindings(&root).expect("load bindings");
        assert!(records.iter().any(|record| {
            record.channel_id == "telegram"
                && record.agent_id == "leviathann"
                && record.session_scope == "per-channel-peer"
        }));
    }

    #[test]
    fn resolve_binding_uses_channel_peer_scope() {
        let root = temp_path("loom-binding-resolve");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        let mut manifest = load_onboard_manifest(&root).expect("load manifest");
        manifest.telegram_enabled = true;
        write_onboard_manifest(&root, &manifest).expect("write manifest");
        sync_channel_registry(&root).expect("sync channels");
        sync_binding_registry(&root).expect("sync bindings");

        let resolution =
            resolve_binding(&root, "telegram", "founder", None, None).expect("resolve binding");
        assert_eq!(resolution.agent_id, "leviathann");
        assert_eq!(resolution.session_key, "telegram:founder");
    }

    #[test]
    fn resolve_binding_allows_agent_override() {
        let root = temp_path("loom-binding-override");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        let mut manifest = load_onboard_manifest(&root).expect("load manifest");
        manifest.telegram_enabled = true;
        manifest.session_dm_scope = "agent".to_string();
        write_onboard_manifest(&root, &manifest).expect("write manifest");
        sync_channel_registry(&root).expect("sync channels");
        sync_binding_registry(&root).expect("sync bindings");

        let resolution = resolve_binding(&root, "telegram", "founder", None, Some("atlas"))
            .expect("resolve binding");
        assert_eq!(resolution.agent_id, "atlas");
        assert_eq!(resolution.session_key, "agent:atlas");
    }

    fn temp_path(label: &str) -> PathBuf {
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        std::env::temp_dir().join(format!("{}-{}", label, timestamp))
    }
}
