use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

pub type LoomResult<T> = Result<T, String>;

const DEFAULT_SESSION_OVERRIDES_PATH: &str = "state/session-policy/overrides.json";
const DEFAULT_SESSION_SEND_POLICIES_PATH: &str = "state/session-policy/send-policies.json";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SessionOverrideRecord {
    pub session_key: String,
    pub provider_profile: Option<String>,
    pub model: Option<String>,
    pub override_at: String,
    pub override_source: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SessionSendPolicyRecord {
    pub session_key: String,
    pub mode: String,
    pub channel_target: Option<String>,
    pub updated_at: String,
}

pub fn session_overrides_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_SESSION_OVERRIDES_PATH)
}

pub fn session_send_policies_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_SESSION_SEND_POLICIES_PATH)
}

pub fn ensure_session_policy_scaffold(root: &Path) -> LoomResult<PathBuf> {
    let overrides_path = session_overrides_path(root);
    if let Some(parent) = overrides_path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    if !overrides_path.exists() {
        fs::write(&overrides_path, "{\n  \"overrides\": []\n}\n").map_err(io_err)?;
    }
    let send_policies_path = session_send_policies_path(root);
    if !send_policies_path.exists() {
        fs::write(&send_policies_path, "{\n  \"send_policies\": []\n}\n").map_err(io_err)?;
    }
    Ok(overrides_path)
}

pub fn set_session_override(
    root: &Path,
    session_key: &str,
    provider_profile: Option<&str>,
    model: Option<&str>,
) -> LoomResult<SessionOverrideRecord> {
    let session_key = session_key.trim();
    if session_key.is_empty() {
        return Err("session_key is required".to_string());
    }
    let ts = timestamp_now();
    let mut overrides = load_session_overrides(root)?;
    let record = SessionOverrideRecord {
        session_key: session_key.to_string(),
        provider_profile: provider_profile
            .map(str::trim)
            .filter(|v| !v.is_empty())
            .map(str::to_string),
        model: model
            .map(str::trim)
            .filter(|v| !v.is_empty())
            .map(str::to_string),
        override_at: ts,
        override_source: "manual".to_string(),
    };
    overrides.retain(|r| r.session_key != session_key);
    overrides.push(record.clone());
    persist_session_overrides(root, &overrides)?;
    Ok(record)
}

pub fn get_session_override(
    root: &Path,
    session_key: &str,
) -> LoomResult<Option<SessionOverrideRecord>> {
    let session_key = session_key.trim();
    if session_key.is_empty() {
        return Ok(None);
    }
    let overrides = load_session_overrides(root)?;
    Ok(overrides.into_iter().find(|r| r.session_key == session_key))
}

pub fn clear_session_override(root: &Path, session_key: &str) -> LoomResult<()> {
    let session_key = session_key.trim();
    if session_key.is_empty() {
        return Err("session_key is required".to_string());
    }
    let mut overrides = load_session_overrides(root)?;
    let before = overrides.len();
    overrides.retain(|r| r.session_key != session_key);
    if overrides.len() < before {
        persist_session_overrides(root, &overrides)?;
    }
    Ok(())
}

pub fn set_session_send_policy(
    root: &Path,
    session_key: &str,
    mode: &str,
    channel_target: Option<&str>,
) -> LoomResult<SessionSendPolicyRecord> {
    let session_key = session_key.trim();
    if session_key.is_empty() {
        return Err("session_key is required".to_string());
    }
    let mode = normalize_send_mode(mode);
    let ts = timestamp_now();
    let mut policies = load_session_send_policies(root)?;
    let record = SessionSendPolicyRecord {
        session_key: session_key.to_string(),
        mode,
        channel_target: channel_target
            .map(str::trim)
            .filter(|v| !v.is_empty())
            .map(str::to_string),
        updated_at: ts,
    };
    policies.retain(|r| r.session_key != session_key);
    policies.push(record.clone());
    persist_session_send_policies(root, &policies)?;
    Ok(record)
}

pub fn get_session_send_policy(
    root: &Path,
    session_key: &str,
) -> LoomResult<Option<SessionSendPolicyRecord>> {
    let session_key = session_key.trim();
    if session_key.is_empty() {
        return Ok(None);
    }
    let policies = load_session_send_policies(root)?;
    Ok(policies.into_iter().find(|r| r.session_key == session_key))
}

/// Apply session-level overrides to a provider route intent.
/// Returns (preferred_profile, requested_model, override_source) tuple.
/// Callers should apply these fields to their ProviderRouteIntent before calling resolve_provider_route.
pub fn apply_session_overrides(
    root: &Path,
    session_key: &str,
) -> LoomResult<(Option<String>, Option<String>, String)> {
    match get_session_override(root, session_key)? {
        Some(ov) => Ok((ov.provider_profile, ov.model, "manual".to_string())),
        None => Ok((None, None, "default".to_string())),
    }
}

pub fn list_session_overrides(root: &Path) -> LoomResult<Vec<SessionOverrideRecord>> {
    load_session_overrides(root)
}

pub fn list_session_send_policies(root: &Path) -> LoomResult<Vec<SessionSendPolicyRecord>> {
    load_session_send_policies(root)
}

// --- render ---

pub fn render_session_override_human(record: &SessionOverrideRecord) -> String {
    format!(
        "session_key:       {}\nprovider_profile:  {}\nmodel:             {}\noverride_at:       {}\noverride_source:   {}\n",
        record.session_key,
        record.provider_profile.as_deref().unwrap_or("(none)"),
        record.model.as_deref().unwrap_or("(none)"),
        record.override_at,
        record.override_source,
    )
}

pub fn render_session_override_json(record: &SessionOverrideRecord) -> String {
    serde_json::to_string_pretty(&session_override_record_json(record))
        .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_session_send_policy_human(record: &SessionSendPolicyRecord) -> String {
    format!(
        "session_key:       {}\nmode:              {}\nchannel_target:    {}\nupdated_at:        {}\n",
        record.session_key,
        record.mode,
        record.channel_target.as_deref().unwrap_or("(none)"),
        record.updated_at,
    )
}

pub fn render_session_send_policy_json(record: &SessionSendPolicyRecord) -> String {
    serde_json::to_string_pretty(&send_policy_record_json(record))
        .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_session_overrides_list_human(records: &[SessionOverrideRecord]) -> String {
    if records.is_empty() {
        return "override_count:    0\n".to_string();
    }
    let mut out = format!("override_count:    {}\n", records.len());
    for r in records {
        out.push_str(&format!(
            "\n- {} profile={} model={}\n",
            r.session_key,
            r.provider_profile.as_deref().unwrap_or("(none)"),
            r.model.as_deref().unwrap_or("(none)"),
        ));
    }
    out
}

pub fn render_session_send_policies_list_human(records: &[SessionSendPolicyRecord]) -> String {
    if records.is_empty() {
        return "policy_count:      0\n".to_string();
    }
    let mut out = format!("policy_count:      {}\n", records.len());
    for r in records {
        out.push_str(&format!(
            "\n- {} mode={} target={}\n",
            r.session_key,
            r.mode,
            r.channel_target.as_deref().unwrap_or("(none)"),
        ));
    }
    out
}

// --- internal ---

fn load_session_overrides(root: &Path) -> LoomResult<Vec<SessionOverrideRecord>> {
    ensure_session_policy_scaffold(root)?;
    let raw = fs::read_to_string(session_overrides_path(root)).map_err(io_err)?;
    parse_session_overrides(&raw)
}

fn load_session_send_policies(root: &Path) -> LoomResult<Vec<SessionSendPolicyRecord>> {
    ensure_session_policy_scaffold(root)?;
    let raw = fs::read_to_string(session_send_policies_path(root)).map_err(io_err)?;
    parse_session_send_policies(&raw)
}

fn persist_session_overrides(root: &Path, records: &[SessionOverrideRecord]) -> LoomResult<()> {
    let path = session_overrides_path(root);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    let value = json!({
        "overrides": records.iter().map(session_override_record_json).collect::<Vec<_>>()
    });
    let mut rendered = serde_json::to_string_pretty(&value).map_err(|e| e.to_string())?;
    rendered.push('\n');
    fs::write(path, rendered).map_err(io_err)
}

fn persist_session_send_policies(
    root: &Path,
    records: &[SessionSendPolicyRecord],
) -> LoomResult<()> {
    let path = session_send_policies_path(root);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    let value = json!({
        "send_policies": records.iter().map(send_policy_record_json).collect::<Vec<_>>()
    });
    let mut rendered = serde_json::to_string_pretty(&value).map_err(|e| e.to_string())?;
    rendered.push('\n');
    fs::write(path, rendered).map_err(io_err)
}

fn parse_session_overrides(raw: &str) -> LoomResult<Vec<SessionOverrideRecord>> {
    let value: Value =
        serde_json::from_str(raw).map_err(|e| format!("invalid session overrides json: {e}"))?;
    let items = value
        .get("overrides")
        .and_then(Value::as_array)
        .ok_or_else(|| "session overrides must define an overrides array".to_string())?;
    let mut records = Vec::with_capacity(items.len());
    for item in items {
        records.push(parse_session_override_record(item)?);
    }
    Ok(records)
}

fn parse_session_send_policies(raw: &str) -> LoomResult<Vec<SessionSendPolicyRecord>> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|e| format!("invalid session send policies json: {e}"))?;
    let items = value
        .get("send_policies")
        .and_then(Value::as_array)
        .ok_or_else(|| "session send policies must define a send_policies array".to_string())?;
    let mut records = Vec::with_capacity(items.len());
    for item in items {
        records.push(parse_session_send_policy_record(item)?);
    }
    Ok(records)
}

fn parse_session_override_record(value: &Value) -> LoomResult<SessionOverrideRecord> {
    Ok(SessionOverrideRecord {
        session_key: value_string(value.get("session_key"), "session_key")?,
        provider_profile: value_opt_string(value.get("provider_profile")),
        model: value_opt_string(value.get("model")),
        override_at: value_string_or(value.get("override_at"), ""),
        override_source: value_string_or(value.get("override_source"), "manual"),
    })
}

fn parse_session_send_policy_record(value: &Value) -> LoomResult<SessionSendPolicyRecord> {
    Ok(SessionSendPolicyRecord {
        session_key: value_string(value.get("session_key"), "session_key")?,
        mode: value_string_or(value.get("mode"), "deliver"),
        channel_target: value_opt_string(value.get("channel_target")),
        updated_at: value_string_or(value.get("updated_at"), ""),
    })
}

fn session_override_record_json(record: &SessionOverrideRecord) -> Value {
    json!({
        "session_key": record.session_key,
        "provider_profile": record.provider_profile,
        "model": record.model,
        "override_at": record.override_at,
        "override_source": record.override_source,
    })
}

fn send_policy_record_json(record: &SessionSendPolicyRecord) -> Value {
    json!({
        "session_key": record.session_key,
        "mode": record.mode,
        "channel_target": record.channel_target,
        "updated_at": record.updated_at,
    })
}

fn normalize_send_mode(raw: &str) -> String {
    match raw.trim().to_ascii_lowercase().as_str() {
        "echo" => "echo".to_string(),
        "deliver" => "deliver".to_string(),
        "silent" => "silent".to_string(),
        "annotate" => "annotate".to_string(),
        other => other.to_string(),
    }
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

    fn temp_path(label: &str) -> std::path::PathBuf {
        let ts = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        std::env::temp_dir().join(format!("{}-{}", label, ts))
    }

    #[test]
    fn set_and_get_session_override() {
        let root = temp_path("loom-session-policy-override");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        let record = set_session_override(
            &root,
            "telegram:founder",
            Some("local_ollama"),
            Some("llama3"),
        )
        .expect("set override");
        assert_eq!(record.session_key, "telegram:founder");
        assert_eq!(record.provider_profile.as_deref(), Some("local_ollama"));
        assert_eq!(record.model.as_deref(), Some("llama3"));

        let loaded = get_session_override(&root, "telegram:founder")
            .expect("get override")
            .expect("must exist");
        assert_eq!(loaded.model.as_deref(), Some("llama3"));
    }

    #[test]
    fn set_and_get_send_policy() {
        let root = temp_path("loom-session-policy-send");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        let record = set_session_send_policy(&root, "telegram:founder", "echo", Some("telegram"))
            .expect("set policy");
        assert_eq!(record.mode, "echo");

        let loaded = get_session_send_policy(&root, "telegram:founder")
            .expect("get policy")
            .expect("must exist");
        assert_eq!(loaded.mode, "echo");
    }

    #[test]
    fn clear_session_override_removes_record() {
        let root = temp_path("loom-session-policy-clear");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        set_session_override(&root, "key:1", Some("local_ollama"), None).expect("set");
        clear_session_override(&root, "key:1").expect("clear");
        let result = get_session_override(&root, "key:1").expect("get");
        assert!(result.is_none());
    }

    #[test]
    fn apply_session_overrides_returns_none_when_no_override() {
        let root = temp_path("loom-session-policy-apply-none");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        let (profile, model, source) =
            apply_session_overrides(&root, "telegram:nobody").expect("apply");
        assert!(profile.is_none());
        assert!(model.is_none());
        assert_eq!(source, "default");
    }
}
