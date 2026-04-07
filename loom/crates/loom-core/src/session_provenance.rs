use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

pub type LoomResult<T> = Result<T, String>;

pub const DEFAULT_SESSION_PROVENANCE_REGISTRY_PATH: &str = "state/session-provenance/registry.json";
pub const LEGACY_SESSION_ARCHIVE_AFTER_SECS: u64 = 6 * 60 * 60;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SessionProvenanceRecord {
    pub session_key: String,
    pub channel_id: String,
    pub peer_id: String,
    pub org_id: String,
    pub agent_id: String,
    pub binding_id: String,
    pub provider_profile: String,
    pub model: String,
    pub transport_kind: String,
    pub auth_mode: String,
    pub execution_owner: String,
    pub ingress_request_id: Option<String>,
    pub job_id: Option<String>,
    pub delivery_id: Option<String>,
    pub override_source: String,
    pub send_policy: String,
    pub opened_at: String,
    pub last_active_at: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SessionProvenanceOverview {
    pub registry_path: PathBuf,
    pub total_count: usize,
    pub active_count: usize,
    pub archived_count: usize,
    pub session_keys: Vec<String>,
    pub archived_session_keys: Vec<String>,
}

fn session_provenance_state_with_now(
    record: &SessionProvenanceRecord,
    now_secs: u64,
) -> &'static str {
    if !record.provider_profile.is_empty()
        && !record.model.is_empty()
        && !record.transport_kind.is_empty()
        && !record.auth_mode.is_empty()
        && !record.execution_owner.is_empty()
    {
        "complete"
    } else if record.ingress_request_id.is_some()
        || record.job_id.is_some()
        || record.delivery_id.is_some()
    {
        "partial"
    } else if last_activity_unix_secs(record)
        .map(|last| now_secs.saturating_sub(last) >= LEGACY_SESSION_ARCHIVE_AFTER_SECS)
        .unwrap_or(false)
    {
        "legacy_archived"
    } else {
        "legacy_incomplete"
    }
}

fn session_provenance_state(record: &SessionProvenanceRecord) -> &'static str {
    session_provenance_state_with_now(record, now_unix_secs())
}

pub fn session_provenance_registry_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_SESSION_PROVENANCE_REGISTRY_PATH)
}

pub fn ensure_session_provenance_scaffold(root: &Path) -> LoomResult<PathBuf> {
    let registry_path = session_provenance_registry_path(root);
    if let Some(parent) = registry_path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    if !registry_path.exists() {
        fs::write(&registry_path, "{\n  \"sessions\": []\n}\n").map_err(io_err)?;
    }
    Ok(registry_path)
}

/// Open or refresh a provenance record for a session.
/// If the session_key already exists, updates last_active_at.
/// If it does not exist, creates a new record.
pub fn open_session_provenance(
    root: &Path,
    session_key: &str,
    channel_id: &str,
    peer_id: &str,
    agent_id: &str,
    binding_id: &str,
) -> LoomResult<SessionProvenanceRecord> {
    let ts = timestamp_now();
    let mut records = load_session_provenance_records(root)?;
    if let Some(existing) = records.iter_mut().find(|r| r.session_key == session_key) {
        existing.last_active_at = ts.clone();
        existing.agent_id = agent_id.to_string();
        let updated = existing.clone();
        persist_session_provenance_registry(root, &records)?;
        return Ok(updated);
    }
    let record = SessionProvenanceRecord {
        session_key: session_key.to_string(),
        channel_id: channel_id.to_string(),
        peer_id: peer_id.to_string(),
        org_id: infer_session_org_id(session_key, peer_id, ""),
        agent_id: agent_id.to_string(),
        binding_id: binding_id.to_string(),
        provider_profile: String::new(),
        model: String::new(),
        transport_kind: String::new(),
        auth_mode: String::new(),
        execution_owner: String::new(),
        ingress_request_id: None,
        job_id: None,
        delivery_id: None,
        override_source: "default".to_string(),
        send_policy: "deliver".to_string(),
        opened_at: ts.clone(),
        last_active_at: ts,
    };
    records.push(record.clone());
    persist_session_provenance_registry(root, &records)?;
    Ok(record)
}

/// Update the resolved provider route info on a provenance record.
pub fn update_session_provenance_route(
    root: &Path,
    session_key: &str,
    provider_profile: &str,
    model: &str,
    override_source: &str,
) -> LoomResult<()> {
    update_session_provenance_route_full(
        root,
        session_key,
        provider_profile,
        model,
        override_source,
        "",
        "",
        "",
        "",
    )
}

pub fn update_session_provenance_route_full(
    root: &Path,
    session_key: &str,
    provider_profile: &str,
    model: &str,
    override_source: &str,
    transport_kind: &str,
    auth_mode: &str,
    execution_owner: &str,
    org_id: &str,
) -> LoomResult<()> {
    let ts = timestamp_now();
    let mut records = load_session_provenance_records(root)?;
    if let Some(record) = records.iter_mut().find(|r| r.session_key == session_key) {
        let resolved_org_id = infer_session_org_id(session_key, &record.peer_id, org_id);
        if !resolved_org_id.is_empty() {
            record.org_id = resolved_org_id;
        }
        if !provider_profile.is_empty() {
            record.provider_profile = provider_profile.to_string();
        }
        if !model.is_empty() {
            record.model = model.to_string();
        }
        if !override_source.is_empty() {
            record.override_source = override_source.to_string();
        }
        if !transport_kind.is_empty() {
            record.transport_kind = transport_kind.to_string();
        }
        if !auth_mode.is_empty() {
            record.auth_mode = auth_mode.to_string();
        }
        if !execution_owner.is_empty() {
            record.execution_owner = execution_owner.to_string();
        }
        record.last_active_at = ts;
        persist_session_provenance_registry(root, &records)?;
    }
    Ok(())
}

/// Link a job_id and/or delivery_id and/or ingress_request_id to a provenance record.
pub fn update_session_provenance_job(
    root: &Path,
    session_key: &str,
    job_id: Option<&str>,
    delivery_id: Option<&str>,
    ingress_request_id: Option<&str>,
) -> LoomResult<()> {
    let ts = timestamp_now();
    let mut records = load_session_provenance_records(root)?;
    if let Some(record) = records.iter_mut().find(|r| r.session_key == session_key) {
        if let Some(j) = job_id {
            if !j.is_empty() {
                record.job_id = Some(j.to_string());
            }
        }
        if let Some(d) = delivery_id {
            if !d.is_empty() {
                record.delivery_id = Some(d.to_string());
            }
        }
        if let Some(i) = ingress_request_id {
            if !i.is_empty() {
                record.ingress_request_id = Some(i.to_string());
            }
        }
        record.last_active_at = ts;
        persist_session_provenance_registry(root, &records)?;
    }
    Ok(())
}

pub fn find_session_provenance(
    root: &Path,
    session_key: &str,
) -> LoomResult<Option<SessionProvenanceRecord>> {
    let session_key = session_key.trim();
    if session_key.is_empty() {
        return Err("session_key is required".to_string());
    }
    let records = load_session_provenance_records(root)?;
    Ok(records.into_iter().find(|r| r.session_key == session_key))
}

pub fn list_session_provenance(
    root: &Path,
    limit: usize,
) -> LoomResult<Vec<SessionProvenanceRecord>> {
    list_session_provenance_with_options(root, limit, false, false)
}

pub fn list_session_provenance_with_options(
    root: &Path,
    limit: usize,
    include_archived: bool,
    archived_only: bool,
) -> LoomResult<Vec<SessionProvenanceRecord>> {
    let mut records = load_session_provenance_records(root)?;
    records.sort_by(|a, b| b.last_active_at.cmp(&a.last_active_at));
    if archived_only {
        records.retain(|record| session_provenance_state(record) == "legacy_archived");
    } else if !include_archived {
        records.retain(|record| session_provenance_state(record) != "legacy_archived");
    }
    if limit > 0 && records.len() > limit {
        records.truncate(limit);
    }
    Ok(records)
}

pub fn session_provenance_overview(root: &Path) -> LoomResult<SessionProvenanceOverview> {
    let records = load_session_provenance_records(root)?;
    let mut session_keys = Vec::new();
    let mut archived_session_keys = Vec::new();
    for record in &records {
        if session_provenance_state(record) == "legacy_archived" {
            archived_session_keys.push(record.session_key.clone());
        } else {
            session_keys.push(record.session_key.clone());
        }
    }
    Ok(SessionProvenanceOverview {
        registry_path: session_provenance_registry_path(root),
        total_count: records.len(),
        active_count: session_keys.len(),
        archived_count: archived_session_keys.len(),
        session_keys,
        archived_session_keys,
    })
}

pub fn sync_session_provenance_registry(root: &Path) -> LoomResult<()> {
    ensure_session_provenance_scaffold(root)?;
    Ok(())
}

// --- render ---

pub fn render_session_provenance_overview_human(overview: &SessionProvenanceOverview) -> String {
    format!(
        "registry_path:   {}\ntotal_count:     {}\nactive_count:    {}\narchived_count:  {}\nsessions:        {}\n",
        overview.registry_path.display(),
        overview.total_count,
        overview.active_count,
        overview.archived_count,
        if overview.session_keys.is_empty() {
            "(none)".to_string()
        } else {
            overview.session_keys.join(",")
        }
    )
}

pub fn render_session_provenance_overview_json(overview: &SessionProvenanceOverview) -> String {
    serde_json::to_string_pretty(&json!({
        "registry_path": overview.registry_path.display().to_string(),
        "total_count": overview.total_count,
        "active_count": overview.active_count,
        "archived_count": overview.archived_count,
        "session_keys": overview.session_keys,
        "archived_session_keys": overview.archived_session_keys,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_session_provenance_human(record: &SessionProvenanceRecord) -> String {
    format!(
        "session_key:          {}\nprovenance_state:     {}\nchannel_id:           {}\npeer_id:              {}\norg_id:               {}\nagent_id:             {}\nbinding_id:           {}\nprovider_profile:     {}\nmodel:                {}\ntransport_kind:       {}\nauth_mode:            {}\nexecution_owner:      {}\ningress_request_id:   {}\njob_id:               {}\ndelivery_id:          {}\noverride_source:      {}\nsend_policy:          {}\nopened_at:            {}\nlast_active_at:       {}\n",
        record.session_key,
        session_provenance_state(record),
        record.channel_id,
        record.peer_id,
        if record.org_id.is_empty() { "(none)" } else { &record.org_id },
        record.agent_id,
        record.binding_id,
        if record.provider_profile.is_empty() { "(none)" } else { &record.provider_profile },
        if record.model.is_empty() { "(none)" } else { &record.model },
        if record.transport_kind.is_empty() { "(none)" } else { &record.transport_kind },
        if record.auth_mode.is_empty() { "(none)" } else { &record.auth_mode },
        if record.execution_owner.is_empty() { "(none)" } else { &record.execution_owner },
        record.ingress_request_id.as_deref().unwrap_or("(none)"),
        record.job_id.as_deref().unwrap_or("(none)"),
        record.delivery_id.as_deref().unwrap_or("(none)"),
        record.override_source,
        record.send_policy,
        record.opened_at,
        record.last_active_at,
    )
}

pub fn render_session_provenance_json(record: &SessionProvenanceRecord) -> String {
    serde_json::to_string_pretty(&session_provenance_record_json(record))
        .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_session_provenance_list_human(records: &[SessionProvenanceRecord]) -> String {
    if records.is_empty() {
        return "session_count:     0\n".to_string();
    }
    let mut out = format!("session_count:     {}\n", records.len());
    for r in records {
        out.push_str(&format!(
            "\n- {} channel={} peer={} agent={} policy={}\n",
            r.session_key, r.channel_id, r.peer_id, r.agent_id, r.send_policy
        ));
    }
    out
}

pub fn render_session_provenance_list_json(records: &[SessionProvenanceRecord]) -> String {
    serde_json::to_string_pretty(
        &records
            .iter()
            .map(session_provenance_record_json)
            .collect::<Vec<_>>(),
    )
    .unwrap_or_else(|_| "[]".to_string())
        + "\n"
}

// --- internal ---

fn load_session_provenance_records(root: &Path) -> LoomResult<Vec<SessionProvenanceRecord>> {
    ensure_session_provenance_scaffold(root)?;
    let raw = fs::read_to_string(session_provenance_registry_path(root)).map_err(io_err)?;
    parse_session_provenance_registry(&raw)
}

fn persist_session_provenance_registry(
    root: &Path,
    records: &[SessionProvenanceRecord],
) -> LoomResult<()> {
    let registry_path = session_provenance_registry_path(root);
    if let Some(parent) = registry_path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    let value = json!({
        "sessions": records.iter().map(session_provenance_record_json).collect::<Vec<_>>()
    });
    let mut rendered = serde_json::to_string_pretty(&value).map_err(|e| e.to_string())?;
    rendered.push('\n');
    fs::write(registry_path, rendered).map_err(io_err)
}

fn parse_session_provenance_registry(raw: &str) -> LoomResult<Vec<SessionProvenanceRecord>> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|e| format!("invalid session provenance registry json: {e}"))?;
    let sessions = value
        .get("sessions")
        .and_then(Value::as_array)
        .ok_or_else(|| "session provenance registry must define a sessions array".to_string())?;
    let mut records = Vec::with_capacity(sessions.len());
    for s in sessions {
        records.push(parse_session_provenance_record(s)?);
    }
    Ok(records)
}

fn parse_session_provenance_record(value: &Value) -> LoomResult<SessionProvenanceRecord> {
    Ok(SessionProvenanceRecord {
        session_key: value_string(value.get("session_key"), "session_key")?,
        channel_id: value_string_or(value.get("channel_id"), ""),
        peer_id: value_string_or(value.get("peer_id"), ""),
        org_id: infer_session_org_id(
            &value_string_or(value.get("session_key"), ""),
            &value_string_or(value.get("peer_id"), ""),
            &value_string_or(value.get("org_id"), ""),
        ),
        agent_id: value_string_or(value.get("agent_id"), ""),
        binding_id: value_string_or(value.get("binding_id"), ""),
        provider_profile: value_string_or(value.get("provider_profile"), ""),
        model: value_string_or(value.get("model"), ""),
        transport_kind: value_string_or(value.get("transport_kind"), ""),
        auth_mode: value_string_or(value.get("auth_mode"), ""),
        execution_owner: value_string_or(value.get("execution_owner"), ""),
        ingress_request_id: value_opt_string(value.get("ingress_request_id")),
        job_id: value_opt_string(value.get("job_id")),
        delivery_id: value_opt_string(value.get("delivery_id")),
        override_source: value_string_or(value.get("override_source"), "default"),
        send_policy: value_string_or(value.get("send_policy"), "deliver"),
        opened_at: value_string_or(value.get("opened_at"), ""),
        last_active_at: value_string_or(value.get("last_active_at"), ""),
    })
}

fn session_provenance_record_json(record: &SessionProvenanceRecord) -> Value {
    json!({
        "session_key": record.session_key,
        "provenance_state": session_provenance_state(record),
        "channel_id": record.channel_id,
        "peer_id": record.peer_id,
        "org_id": record.org_id,
        "agent_id": record.agent_id,
        "binding_id": record.binding_id,
        "provider_profile": record.provider_profile,
        "model": record.model,
        "transport_kind": record.transport_kind,
        "auth_mode": record.auth_mode,
        "execution_owner": record.execution_owner,
        "ingress_request_id": record.ingress_request_id,
        "job_id": record.job_id,
        "delivery_id": record.delivery_id,
        "override_source": record.override_source,
        "send_policy": record.send_policy,
        "opened_at": record.opened_at,
        "last_active_at": record.last_active_at,
    })
}

fn timestamp_now() -> String {
    format!("{}", now_unix_secs())
}

fn now_unix_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

fn last_activity_unix_secs(record: &SessionProvenanceRecord) -> Option<u64> {
    parse_unix_secs(&record.last_active_at).or_else(|| parse_unix_secs(&record.opened_at))
}

fn parse_unix_secs(value: &str) -> Option<u64> {
    value.trim().parse::<u64>().ok()
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

fn infer_session_org_id(session_key: &str, peer_id: &str, org_id: &str) -> String {
    let explicit = org_id.trim();
    if !explicit.is_empty() {
        return explicit.to_string();
    }
    let peer = peer_id.trim();
    if peer.starts_with("org_") {
        return peer.to_string();
    }
    if let Some((_, suffix)) = session_key.split_once(':') {
        let trimmed = suffix.trim();
        if trimmed.starts_with("org_") {
            return trimmed.to_string();
        }
    }
    String::new()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::init_workspace;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_path(label: &str) -> std::path::PathBuf {
        let ts = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        std::env::temp_dir().join(format!("{}-{}", label, ts))
    }

    #[test]
    fn open_session_provenance_creates_record() {
        let root = temp_path("loom-session-prov-create");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        let record = open_session_provenance(
            &root,
            "telegram:founder",
            "telegram",
            "founder",
            "leviathann",
            "binding-telegram",
        )
        .expect("open provenance");
        assert_eq!(record.session_key, "telegram:founder");
        assert_eq!(record.channel_id, "telegram");
        assert_eq!(record.agent_id, "leviathann");
        assert_eq!(record.send_policy, "deliver");

        let records = list_session_provenance(&root, 10).expect("list");
        assert_eq!(records.len(), 1);
    }

    #[test]
    fn open_session_provenance_updates_existing() {
        let root = temp_path("loom-session-prov-update");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        open_session_provenance(
            &root,
            "telegram:founder",
            "telegram",
            "founder",
            "leviathann",
            "binding-telegram",
        )
        .expect("open first");
        open_session_provenance(
            &root,
            "telegram:founder",
            "telegram",
            "founder",
            "atlas",
            "binding-telegram",
        )
        .expect("open second");

        let records = list_session_provenance(&root, 10).expect("list");
        assert_eq!(records.len(), 1, "must not duplicate");
        assert_eq!(records[0].agent_id, "atlas");
    }

    #[test]
    fn find_session_provenance_returns_none_for_unknown() {
        let root = temp_path("loom-session-prov-find");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        let result = find_session_provenance(&root, "nope:nope").expect("find");
        assert!(result.is_none());
    }

    #[test]
    fn update_session_provenance_job_links_ids() {
        let root = temp_path("loom-session-prov-job");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        open_session_provenance(
            &root,
            "web_api:user42",
            "web_api",
            "user42",
            "leviathann",
            "binding-web_api",
        )
        .expect("open");
        update_session_provenance_job(
            &root,
            "web_api:user42",
            Some("job-abc"),
            Some("delivery-xyz"),
            Some("req-123"),
        )
        .expect("update job");
        let record = find_session_provenance(&root, "web_api:user42")
            .expect("find")
            .expect("record must exist");
        assert_eq!(record.job_id.as_deref(), Some("job-abc"));
        assert_eq!(record.delivery_id.as_deref(), Some("delivery-xyz"));
        assert_eq!(record.ingress_request_id.as_deref(), Some("req-123"));
    }

    #[test]
    fn render_session_provenance_marks_legacy_incomplete_records() {
        let now = now_unix_secs().to_string();
        let record = SessionProvenanceRecord {
            session_key: "telegram:legacy".to_string(),
            channel_id: "telegram".to_string(),
            peer_id: "legacy".to_string(),
            org_id: String::new(),
            agent_id: "leviathann".to_string(),
            binding_id: "binding-telegram".to_string(),
            provider_profile: String::new(),
            model: String::new(),
            transport_kind: String::new(),
            auth_mode: String::new(),
            execution_owner: String::new(),
            ingress_request_id: None,
            job_id: None,
            delivery_id: None,
            override_source: "default".to_string(),
            send_policy: "deliver".to_string(),
            opened_at: now.clone(),
            last_active_at: now,
        };
        let rendered = render_session_provenance_json(&record);
        assert!(rendered.contains("\"provenance_state\": \"legacy_incomplete\""));
    }

    #[test]
    fn render_session_provenance_marks_legacy_archived_records() {
        let old = (now_unix_secs() - LEGACY_SESSION_ARCHIVE_AFTER_SECS - 1).to_string();
        let record = SessionProvenanceRecord {
            session_key: "telegram:archived".to_string(),
            channel_id: "telegram".to_string(),
            peer_id: "archived".to_string(),
            org_id: String::new(),
            agent_id: "leviathann".to_string(),
            binding_id: "binding-telegram".to_string(),
            provider_profile: String::new(),
            model: String::new(),
            transport_kind: String::new(),
            auth_mode: String::new(),
            execution_owner: String::new(),
            ingress_request_id: None,
            job_id: None,
            delivery_id: None,
            override_source: "default".to_string(),
            send_policy: "deliver".to_string(),
            opened_at: old.clone(),
            last_active_at: old,
        };
        let rendered = render_session_provenance_json(&record);
        assert!(rendered.contains("\"provenance_state\": \"legacy_archived\""));
    }

    #[test]
    fn session_overview_separates_archived_sessions_from_active_sessions() {
        let root = temp_path("loom-session-prov-overview");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        open_session_provenance(
            &root,
            "telegram:active",
            "telegram",
            "active",
            "leviathann",
            "binding-telegram",
        )
        .expect("open active");
        let mut records = load_session_provenance_records(&root).expect("load records");
        records.push(SessionProvenanceRecord {
            session_key: "telegram:archived".to_string(),
            channel_id: "telegram".to_string(),
            peer_id: "archived".to_string(),
            org_id: String::new(),
            agent_id: "leviathann".to_string(),
            binding_id: "binding-telegram".to_string(),
            provider_profile: String::new(),
            model: String::new(),
            transport_kind: String::new(),
            auth_mode: String::new(),
            execution_owner: String::new(),
            ingress_request_id: None,
            job_id: None,
            delivery_id: None,
            override_source: "default".to_string(),
            send_policy: "deliver".to_string(),
            opened_at: (now_unix_secs() - LEGACY_SESSION_ARCHIVE_AFTER_SECS - 10).to_string(),
            last_active_at: (now_unix_secs() - LEGACY_SESSION_ARCHIVE_AFTER_SECS - 10).to_string(),
        });
        persist_session_provenance_registry(&root, &records).expect("persist");

        let visible = list_session_provenance(&root, 10).expect("visible");
        assert_eq!(visible.len(), 1);
        assert_eq!(visible[0].session_key, "telegram:active");

        let archived =
            list_session_provenance_with_options(&root, 10, true, true).expect("archived");
        assert_eq!(archived.len(), 1);
        assert_eq!(archived[0].session_key, "telegram:archived");

        let overview = session_provenance_overview(&root).expect("overview");
        assert_eq!(overview.total_count, 2);
        assert_eq!(overview.active_count, 1);
        assert_eq!(overview.archived_count, 1);
        assert_eq!(overview.session_keys, vec!["telegram:active".to_string()]);
        assert_eq!(
            overview.archived_session_keys,
            vec!["telegram:archived".to_string()]
        );
    }

    #[test]
    fn render_session_provenance_marks_complete_records() {
        let record = SessionProvenanceRecord {
            session_key: "web_api:org_demo".to_string(),
            channel_id: "web_api".to_string(),
            peer_id: "org_demo".to_string(),
            org_id: "org_demo".to_string(),
            agent_id: "leviathann".to_string(),
            binding_id: "binding-web_api".to_string(),
            provider_profile: "manager_frontier".to_string(),
            model: "gpt-5.4".to_string(),
            transport_kind: "codex_session".to_string(),
            auth_mode: "codex_auth_json".to_string(),
            execution_owner: "meridian".to_string(),
            ingress_request_id: Some("ingress-1".to_string()),
            job_id: Some("job-1".to_string()),
            delivery_id: Some("delivery-1".to_string()),
            override_source: "default".to_string(),
            send_policy: "deliver".to_string(),
            opened_at: "1".to_string(),
            last_active_at: "2".to_string(),
        };
        let rendered = render_session_provenance_json(&record);
        assert!(rendered.contains("\"provenance_state\": \"complete\""));
    }
}
