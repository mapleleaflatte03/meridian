use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

use crate::provider_router::{load_provider_profiles, provider_auth_status};
use crate::{io_err, LoomResult};

pub const DEFAULT_PROVIDER_AUTH_STORE_PATH: &str = "state/providers/auth-profiles.json";
const PROVIDER_AUTH_STORE_VERSION: u32 = 1;
const DEFAULT_FAILURE_REASON: &str = "unknown";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProviderAuthProfileRecord {
    pub profile_name: String,
    pub provider_kind: String,
    pub auth_mode: String,
    pub env_var: Option<String>,
    pub header_name: Option<String>,
    pub credential_path: Option<String>,
    pub ready: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Default)]
pub struct ProviderAuthProfileUsageStats {
    pub last_used_at_ms: Option<u64>,
    pub last_failure_at_ms: Option<u64>,
    pub error_count: u64,
    pub cooldown_until_ms: Option<u64>,
    pub cooldown_reason: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProviderAuthStore {
    pub version: u32,
    pub profiles: BTreeMap<String, ProviderAuthProfileRecord>,
    pub last_good: BTreeMap<String, String>,
    pub usage_stats: BTreeMap<String, ProviderAuthProfileUsageStats>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProviderAuthStoreOverview {
    pub store_path: PathBuf,
    pub profile_count: usize,
    pub ready_count: usize,
    pub last_good_count: usize,
    pub usage_stats_count: usize,
    pub profile_names: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProviderAuthProfileSnapshot {
    pub profile_name: String,
    pub provider_kind: String,
    pub auth_mode: String,
    pub ready: bool,
    pub env_var: Option<String>,
    pub header_name: Option<String>,
    pub credential_path: Option<String>,
    pub last_used_at_ms: Option<u64>,
    pub last_failure_at_ms: Option<u64>,
    pub error_count: u64,
    pub cooldown_until_ms: Option<u64>,
    pub cooldown_reason: Option<String>,
    pub last_good_for: Vec<String>,
}

pub fn provider_auth_store_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_PROVIDER_AUTH_STORE_PATH)
}

pub fn ensure_provider_auth_store_scaffold(root: &Path) -> LoomResult<PathBuf> {
    let path = provider_auth_store_path(root);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    if !path.exists() {
        sync_provider_auth_store(root)?;
    }
    Ok(path)
}

pub fn sync_provider_auth_store(root: &Path) -> LoomResult<ProviderAuthStoreOverview> {
    let path = provider_auth_store_path(root);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }

    let existing = read_existing_store(&path)?;
    let provider_profiles = load_provider_profiles(Some(root))?;
    let mut profiles = BTreeMap::new();
    for profile in &provider_profiles.profiles {
        let status = provider_auth_status(Some(root), Some(&profile.name))?;
        profiles.insert(
            profile.name.clone(),
            ProviderAuthProfileRecord {
                profile_name: profile.name.clone(),
                provider_kind: status.profile_kind.label().to_string(),
                auth_mode: status.auth_mode,
                env_var: status.env_var,
                header_name: status.header_name,
                credential_path: status.credential_path,
                ready: status.ready,
            },
        );
    }

    let last_good = existing
        .as_ref()
        .map(|store| {
            store
                .last_good
                .iter()
                .filter(|(_, profile_name)| profiles.contains_key(*profile_name))
                .map(|(provider_kind, profile_name)| (provider_kind.clone(), profile_name.clone()))
                .collect::<BTreeMap<_, _>>()
        })
        .unwrap_or_default();
    let usage_stats = existing
        .as_ref()
        .map(|store| {
            store
                .usage_stats
                .iter()
                .filter(|(profile_name, _)| profiles.contains_key(*profile_name))
                .map(|(profile_name, stats)| (profile_name.clone(), stats.clone()))
                .collect::<BTreeMap<_, _>>()
        })
        .unwrap_or_default();

    let store = ProviderAuthStore {
        version: PROVIDER_AUTH_STORE_VERSION,
        profiles,
        last_good,
        usage_stats,
    };
    persist_provider_auth_store(&path, &store)?;
    Ok(provider_auth_store_overview_from_store(path, &store))
}

pub fn load_provider_auth_store(root: &Path) -> LoomResult<ProviderAuthStore> {
    ensure_provider_auth_store_scaffold(root)?;
    parse_provider_auth_store(&fs::read_to_string(provider_auth_store_path(root)).map_err(io_err)?)
}

pub fn provider_auth_store_overview(root: &Path) -> LoomResult<ProviderAuthStoreOverview> {
    let path = provider_auth_store_path(root);
    let store = load_provider_auth_store(root)?;
    Ok(provider_auth_store_overview_from_store(path, &store))
}

pub fn list_provider_auth_profiles(root: &Path) -> LoomResult<Vec<ProviderAuthProfileSnapshot>> {
    let store = load_provider_auth_store(root)?;
    let mut snapshots = store
        .profiles
        .values()
        .map(|record| snapshot_from_store(&store, record))
        .collect::<Vec<_>>();
    snapshots.sort_by(|left, right| left.profile_name.cmp(&right.profile_name));
    Ok(snapshots)
}

pub fn mark_provider_auth_profile_used(
    root: &Path,
    profile_name: &str,
) -> LoomResult<ProviderAuthProfileSnapshot> {
    let path = provider_auth_store_path(root);
    let mut store = load_provider_auth_store(root)?;
    let profile_name = required_profile_name(&store, profile_name)?.to_string();
    let provider_kind = store
        .profiles
        .get(&profile_name)
        .map(|record| record.provider_kind.clone())
        .ok_or_else(|| format!("provider auth profile '{}' was not found", profile_name))?;
    let stats = store
        .usage_stats
        .entry(profile_name.clone())
        .or_insert_with(ProviderAuthProfileUsageStats::default);
    stats.last_used_at_ms = Some(now_unix_ms());
    stats.cooldown_until_ms = None;
    stats.cooldown_reason = None;
    store.last_good.insert(provider_kind, profile_name.clone());
    persist_provider_auth_store(&path, &store)?;
    Ok(snapshot_from_store(
        &store,
        store.profiles.get(&profile_name).expect("profile exists"),
    ))
}

pub fn mark_provider_auth_profile_failure(
    root: &Path,
    profile_name: &str,
    reason: Option<&str>,
    cooldown_ms: Option<u64>,
) -> LoomResult<ProviderAuthProfileSnapshot> {
    let path = provider_auth_store_path(root);
    let mut store = load_provider_auth_store(root)?;
    let profile_name = required_profile_name(&store, profile_name)?.to_string();
    let now = now_unix_ms();
    let stats = store
        .usage_stats
        .entry(profile_name.clone())
        .or_insert_with(ProviderAuthProfileUsageStats::default);
    stats.last_failure_at_ms = Some(now);
    stats.error_count = stats.error_count.saturating_add(1);
    let normalized_reason = reason
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or(DEFAULT_FAILURE_REASON)
        .to_string();
    stats.cooldown_reason = Some(normalized_reason);
    stats.cooldown_until_ms = cooldown_ms
        .filter(|value| *value > 0)
        .map(|value| now.saturating_add(value));
    persist_provider_auth_store(&path, &store)?;
    Ok(snapshot_from_store(
        &store,
        store.profiles.get(&profile_name).expect("profile exists"),
    ))
}

pub fn render_provider_auth_store_human(summary: &ProviderAuthStoreOverview) -> String {
    format!(
        "store_path:         {}\nprofile_count:      {}\nready_count:        {}\nlast_good_count:    {}\nusage_stats_count:  {}\nprofiles:           {}\n",
        summary.store_path.display(),
        summary.profile_count,
        summary.ready_count,
        summary.last_good_count,
        summary.usage_stats_count,
        if summary.profile_names.is_empty() {
            "(none)".to_string()
        } else {
            summary.profile_names.join(",")
        }
    )
}

pub fn render_provider_auth_store_json(summary: &ProviderAuthStoreOverview) -> String {
    serde_json::to_string_pretty(&json!({
        "store_path": summary.store_path.display().to_string(),
        "profile_count": summary.profile_count,
        "ready_count": summary.ready_count,
        "last_good_count": summary.last_good_count,
        "usage_stats_count": summary.usage_stats_count,
        "profile_names": summary.profile_names,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_provider_auth_profiles_human(records: &[ProviderAuthProfileSnapshot]) -> String {
    if records.is_empty() {
        return "auth_profile_count: 0\n".to_string();
    }
    let mut rendered = format!("auth_profile_count: {}\n", records.len());
    for record in records {
        rendered.push_str(&format!(
            "\n- {} provider={} mode={} ready={} errors={} cooldown_until={} last_good_for={}\n",
            record.profile_name,
            record.provider_kind,
            record.auth_mode,
            record.ready,
            record.error_count,
            record
                .cooldown_until_ms
                .map(|value| value.to_string())
                .unwrap_or_else(|| "(none)".to_string()),
            if record.last_good_for.is_empty() {
                "(none)".to_string()
            } else {
                record.last_good_for.join(",")
            }
        ));
    }
    rendered
}

pub fn render_provider_auth_profiles_json(records: &[ProviderAuthProfileSnapshot]) -> String {
    serde_json::to_string_pretty(&records.iter().map(snapshot_json).collect::<Vec<_>>())
        .unwrap_or_else(|_| "[]".to_string())
        + "\n"
}

pub fn render_provider_auth_profile_human(record: &ProviderAuthProfileSnapshot) -> String {
    format!(
        "profile:            {}\nprovider_kind:      {}\nauth_mode:          {}\nready:              {}\nenv_var:            {}\nheader_name:        {}\ncredential_path:    {}\nlast_used_at_ms:    {}\nlast_failure_at_ms: {}\nerror_count:        {}\ncooldown_until_ms:  {}\ncooldown_reason:    {}\nlast_good_for:      {}\n",
        record.profile_name,
        record.provider_kind,
        record.auth_mode,
        record.ready,
        record.env_var.as_deref().unwrap_or("(none)"),
        record.header_name.as_deref().unwrap_or("(none)"),
        record.credential_path.as_deref().unwrap_or("(none)"),
        record
            .last_used_at_ms
            .map(|value| value.to_string())
            .unwrap_or_else(|| "(none)".to_string()),
        record
            .last_failure_at_ms
            .map(|value| value.to_string())
            .unwrap_or_else(|| "(none)".to_string()),
        record.error_count,
        record
            .cooldown_until_ms
            .map(|value| value.to_string())
            .unwrap_or_else(|| "(none)".to_string()),
        record.cooldown_reason.as_deref().unwrap_or("(none)"),
        if record.last_good_for.is_empty() {
            "(none)".to_string()
        } else {
            record.last_good_for.join(",")
        }
    )
}

pub fn render_provider_auth_profile_json(record: &ProviderAuthProfileSnapshot) -> String {
    serde_json::to_string_pretty(&snapshot_json(record)).unwrap_or_else(|_| "{}".to_string()) + "\n"
}

fn read_existing_store(path: &Path) -> LoomResult<Option<ProviderAuthStore>> {
    if !path.exists() {
        return Ok(None);
    }
    parse_provider_auth_store(&fs::read_to_string(path).map_err(io_err)?).map(Some)
}

fn persist_provider_auth_store(path: &Path, store: &ProviderAuthStore) -> LoomResult<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    let mut rendered =
        serde_json::to_string_pretty(&store_json(store)).map_err(|error| error.to_string())?;
    rendered.push('\n');
    fs::write(path, rendered).map_err(io_err)
}

fn parse_provider_auth_store(raw: &str) -> LoomResult<ProviderAuthStore> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid provider auth store json: {error}"))?;
    let version = value
        .get("version")
        .and_then(Value::as_u64)
        .unwrap_or(PROVIDER_AUTH_STORE_VERSION as u64) as u32;
    let profiles = value
        .get("profiles")
        .and_then(Value::as_object)
        .map(parse_profiles_map)
        .transpose()?
        .unwrap_or_default();
    let last_good = value
        .get("last_good")
        .and_then(Value::as_object)
        .map(|entries| {
            entries
                .iter()
                .filter_map(|(key, value)| {
                    value
                        .as_str()
                        .map(|profile_name| (key.clone(), profile_name.trim().to_string()))
                })
                .filter(|(_, profile_name)| !profile_name.is_empty())
                .collect::<BTreeMap<_, _>>()
        })
        .unwrap_or_default();
    let usage_stats = value
        .get("usage_stats")
        .and_then(Value::as_object)
        .map(parse_usage_stats_map)
        .transpose()?
        .unwrap_or_default();
    Ok(ProviderAuthStore {
        version,
        profiles,
        last_good,
        usage_stats,
    })
}

fn parse_profiles_map(
    entries: &serde_json::Map<String, Value>,
) -> LoomResult<BTreeMap<String, ProviderAuthProfileRecord>> {
    let mut profiles = BTreeMap::new();
    for (profile_name, value) in entries {
        profiles.insert(
            profile_name.clone(),
            parse_profile_record(profile_name, value)?,
        );
    }
    Ok(profiles)
}

fn parse_profile_record(
    profile_name: &str,
    value: &Value,
) -> LoomResult<ProviderAuthProfileRecord> {
    Ok(ProviderAuthProfileRecord {
        profile_name: required_string(value.get("profile_name"), "profile_name")
            .unwrap_or_else(|_| profile_name.to_string()),
        provider_kind: required_string(value.get("provider_kind"), "provider_kind")?,
        auth_mode: required_string(value.get("auth_mode"), "auth_mode")?,
        env_var: optional_string(value.get("env_var")),
        header_name: optional_string(value.get("header_name")),
        credential_path: optional_string(value.get("credential_path")),
        ready: value.get("ready").and_then(Value::as_bool).unwrap_or(false),
    })
}

fn parse_usage_stats_map(
    entries: &serde_json::Map<String, Value>,
) -> LoomResult<BTreeMap<String, ProviderAuthProfileUsageStats>> {
    let mut usage_stats = BTreeMap::new();
    for (profile_name, value) in entries {
        usage_stats.insert(profile_name.clone(), parse_usage_stats(value));
    }
    Ok(usage_stats)
}

fn parse_usage_stats(value: &Value) -> ProviderAuthProfileUsageStats {
    ProviderAuthProfileUsageStats {
        last_used_at_ms: value.get("last_used_at_ms").and_then(Value::as_u64),
        last_failure_at_ms: value.get("last_failure_at_ms").and_then(Value::as_u64),
        error_count: value
            .get("error_count")
            .and_then(Value::as_u64)
            .unwrap_or(0),
        cooldown_until_ms: value.get("cooldown_until_ms").and_then(Value::as_u64),
        cooldown_reason: optional_string(value.get("cooldown_reason")),
    }
}

fn store_json(store: &ProviderAuthStore) -> Value {
    json!({
        "version": store.version,
        "profiles": store
            .profiles
            .iter()
            .map(|(profile_name, record)| (profile_name.clone(), profile_record_json(record)))
            .collect::<serde_json::Map<_, _>>(),
        "last_good": store
            .last_good
            .iter()
            .map(|(provider_kind, profile_name)| (provider_kind.clone(), Value::String(profile_name.clone())))
            .collect::<serde_json::Map<_, _>>(),
        "usage_stats": store
            .usage_stats
            .iter()
            .map(|(profile_name, stats)| (profile_name.clone(), usage_stats_json(stats)))
            .collect::<serde_json::Map<_, _>>(),
    })
}

fn profile_record_json(record: &ProviderAuthProfileRecord) -> Value {
    json!({
        "profile_name": record.profile_name,
        "provider_kind": record.provider_kind,
        "auth_mode": record.auth_mode,
        "env_var": record.env_var,
        "header_name": record.header_name,
        "credential_path": record.credential_path,
        "ready": record.ready,
    })
}

fn usage_stats_json(stats: &ProviderAuthProfileUsageStats) -> Value {
    json!({
        "last_used_at_ms": stats.last_used_at_ms,
        "last_failure_at_ms": stats.last_failure_at_ms,
        "error_count": stats.error_count,
        "cooldown_until_ms": stats.cooldown_until_ms,
        "cooldown_reason": stats.cooldown_reason,
    })
}

fn snapshot_from_store(
    store: &ProviderAuthStore,
    record: &ProviderAuthProfileRecord,
) -> ProviderAuthProfileSnapshot {
    let usage = store
        .usage_stats
        .get(&record.profile_name)
        .cloned()
        .unwrap_or_default();
    let last_good_for = store
        .last_good
        .iter()
        .filter_map(|(provider_kind, profile_name)| {
            if profile_name == &record.profile_name {
                Some(provider_kind.clone())
            } else {
                None
            }
        })
        .collect::<Vec<_>>();
    ProviderAuthProfileSnapshot {
        profile_name: record.profile_name.clone(),
        provider_kind: record.provider_kind.clone(),
        auth_mode: record.auth_mode.clone(),
        ready: record.ready,
        env_var: record.env_var.clone(),
        header_name: record.header_name.clone(),
        credential_path: record.credential_path.clone(),
        last_used_at_ms: usage.last_used_at_ms,
        last_failure_at_ms: usage.last_failure_at_ms,
        error_count: usage.error_count,
        cooldown_until_ms: usage.cooldown_until_ms,
        cooldown_reason: usage.cooldown_reason,
        last_good_for,
    }
}

fn snapshot_json(record: &ProviderAuthProfileSnapshot) -> Value {
    json!({
        "profile_name": record.profile_name,
        "provider_kind": record.provider_kind,
        "auth_mode": record.auth_mode,
        "ready": record.ready,
        "env_var": record.env_var,
        "header_name": record.header_name,
        "credential_path": record.credential_path,
        "last_used_at_ms": record.last_used_at_ms,
        "last_failure_at_ms": record.last_failure_at_ms,
        "error_count": record.error_count,
        "cooldown_until_ms": record.cooldown_until_ms,
        "cooldown_reason": record.cooldown_reason,
        "last_good_for": record.last_good_for,
    })
}

fn provider_auth_store_overview_from_store(
    store_path: PathBuf,
    store: &ProviderAuthStore,
) -> ProviderAuthStoreOverview {
    ProviderAuthStoreOverview {
        store_path,
        profile_count: store.profiles.len(),
        ready_count: store
            .profiles
            .values()
            .filter(|record| record.ready)
            .count(),
        last_good_count: store.last_good.len(),
        usage_stats_count: store.usage_stats.len(),
        profile_names: store.profiles.keys().cloned().collect(),
    }
}

fn required_profile_name<'a>(
    store: &'a ProviderAuthStore,
    profile_name: &'a str,
) -> LoomResult<&'a str> {
    let normalized = profile_name.trim();
    if normalized.is_empty() {
        return Err("profile is required".to_string());
    }
    if !store.profiles.contains_key(normalized) {
        let available = store
            .profiles
            .keys()
            .cloned()
            .collect::<Vec<_>>()
            .join(", ");
        return Err(format!(
            "provider auth profile '{}' was not found (available: {})",
            normalized, available
        ));
    }
    Ok(normalized)
}

fn optional_string(value: Option<&Value>) -> Option<String> {
    value
        .and_then(Value::as_str)
        .map(|raw| raw.trim().to_string())
        .filter(|raw| !raw.is_empty())
}

fn required_string(value: Option<&Value>, label: &str) -> LoomResult<String> {
    value
        .and_then(Value::as_str)
        .map(|raw| raw.trim().to_string())
        .filter(|raw| !raw.is_empty())
        .ok_or_else(|| format!("{} must not be empty", label))
}

fn now_unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::init_workspace;
    use crate::provider_router::configure_onboard_provider_routes;

    fn temp_path(label: &str) -> PathBuf {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        let path = std::env::temp_dir().join(format!("{}-{}", label, unique));
        let _ = fs::remove_dir_all(&path);
        fs::create_dir_all(&path).expect("create temp path");
        path
    }

    #[test]
    fn scaffold_syncs_profiles_and_preserves_store_shape() {
        let root = temp_path("loom-provider-auth-store");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        configure_onboard_provider_routes(
            &root,
            "frontier",
            Some("gpt-5.4"),
            Some("/tmp/does-not-exist/auth.json"),
        )
        .expect("configure routes");

        let overview = sync_provider_auth_store(&root).expect("sync auth store");
        assert!(overview.profile_count >= 1);
        let store = load_provider_auth_store(&root).expect("load auth store");
        assert!(store.profiles.contains_key("local_ollama"));
        assert!(store.profiles.contains_key("manager_frontier"));
    }

    #[test]
    fn mark_used_sets_last_good_and_clears_cooldown() {
        let root = temp_path("loom-provider-auth-used");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        sync_provider_auth_store(&root).expect("sync auth store");
        let failed = mark_provider_auth_profile_failure(
            &root,
            "local_ollama",
            Some("rate_limit"),
            Some(5_000),
        )
        .expect("mark failure");
        assert_eq!(failed.cooldown_reason.as_deref(), Some("rate_limit"));
        assert!(failed.cooldown_until_ms.is_some());

        let used = mark_provider_auth_profile_used(&root, "local_ollama").expect("mark used");
        assert!(used.last_used_at_ms.is_some());
        assert!(used.cooldown_until_ms.is_none());
        assert!(used
            .last_good_for
            .iter()
            .any(|value| value == "local_ollama"));
    }
}
