use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use crate::channels::{channel_overview, ensure_channel_runtime_scaffold};
use crate::onboarding::{bind_host_for, load_onboard_manifest};
use crate::LoomResult;

pub const DEFAULT_GATEWAY_RUNTIME_REGISTRY_PATH: &str = "state/gateway/registry.json";
const GATEWAY_RUNTIME_VERSION: u32 = 1;
const DEFAULT_GATEWAY_ID: &str = "meridian_gateway";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GatewayRuntimeRecord {
    pub gateway_id: String,
    pub endpoint: String,
    pub bind_host: String,
    pub port: u16,
    pub auth_mode: String,
    pub credential_ref: String,
    pub tailscale_mode: String,
    pub remote_mode: String,
    pub daemon_enabled: bool,
    pub daemon_manager: String,
    pub daemon_state: String,
    pub channel_ids: Vec<String>,
    pub total_channel_count: usize,
    pub enabled_channel_count: usize,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GatewayRuntimeOverview {
    pub registry_path: PathBuf,
    pub gateway_id: String,
    pub endpoint: String,
    pub auth_mode: String,
    pub remote_mode: String,
    pub daemon_summary: String,
    pub total_channel_count: usize,
    pub enabled_channel_count: usize,
    pub channel_ids: Vec<String>,
}

pub fn gateway_runtime_registry_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_GATEWAY_RUNTIME_REGISTRY_PATH)
}

pub fn ensure_gateway_runtime_scaffold(root: &Path) -> LoomResult<PathBuf> {
    ensure_channel_runtime_scaffold(root)?;
    let path = gateway_runtime_registry_path(root);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    if !path.exists() {
        sync_gateway_runtime(root)?;
    }
    Ok(path)
}

pub fn sync_gateway_runtime(root: &Path) -> LoomResult<GatewayRuntimeOverview> {
    ensure_channel_runtime_scaffold(root)?;
    crate::channels::sync_channel_registry(root)?;
    let manifest = load_onboard_manifest(root)?;
    let channels = channel_overview(root)?;
    let bind_host = bind_host_for(&manifest.gateway_bind).to_string();
    let endpoint = format!("http://{}:{}", bind_host, manifest.gateway_port);
    let record = GatewayRuntimeRecord {
        gateway_id: DEFAULT_GATEWAY_ID.to_string(),
        endpoint: endpoint.clone(),
        bind_host,
        port: manifest.gateway_port,
        auth_mode: manifest.gateway_auth_mode.clone(),
        credential_ref: manifest.gateway_token_env.clone(),
        tailscale_mode: manifest.gateway_tailscale_mode.clone(),
        remote_mode: manifest.remote_mode.clone(),
        daemon_enabled: manifest.daemon_enabled,
        daemon_manager: manifest.daemon_manager.clone(),
        daemon_state: manifest.daemon_state.clone(),
        channel_ids: channels.channel_ids.clone(),
        total_channel_count: channels.total_count,
        enabled_channel_count: channels.enabled_count,
        note: format!(
            "gateway={} remote={} channels={}/{}",
            manifest.gateway_bind,
            manifest.remote_mode,
            channels.enabled_count,
            channels.total_count
        ),
    };
    persist_gateway_runtime(root, &record)?;
    gateway_runtime_overview(root)
}

pub fn gateway_runtime_overview(root: &Path) -> LoomResult<GatewayRuntimeOverview> {
    let record = load_gateway_runtime(root)?;
    Ok(GatewayRuntimeOverview {
        registry_path: gateway_runtime_registry_path(root),
        gateway_id: record.gateway_id,
        endpoint: record.endpoint,
        auth_mode: record.auth_mode,
        remote_mode: record.remote_mode,
        daemon_summary: format!(
            "{} {}",
            record.daemon_manager,
            if record.daemon_enabled {
                record.daemon_state.as_str()
            } else {
                "disabled"
            }
        ),
        total_channel_count: record.total_channel_count,
        enabled_channel_count: record.enabled_channel_count,
        channel_ids: record.channel_ids,
    })
}

pub fn render_gateway_runtime_human(summary: &GatewayRuntimeOverview) -> String {
    format!(
        "registry_path:     {}
gateway_id:        {}
endpoint:          {}
auth_mode:         {}
remote_mode:       {}
daemon:            {}
channels:          total={} enabled={} ids={}
",
        summary.registry_path.display(),
        summary.gateway_id,
        summary.endpoint,
        summary.auth_mode,
        summary.remote_mode,
        summary.daemon_summary,
        summary.total_channel_count,
        summary.enabled_channel_count,
        if summary.channel_ids.is_empty() {
            "(none)".to_string()
        } else {
            summary.channel_ids.join(",")
        }
    )
}

pub fn render_gateway_runtime_json(summary: &GatewayRuntimeOverview) -> String {
    serde_json::to_string_pretty(&json!({
        "registry_path": summary.registry_path.display().to_string(),
        "gateway_id": summary.gateway_id,
        "endpoint": summary.endpoint,
        "auth_mode": summary.auth_mode,
        "remote_mode": summary.remote_mode,
        "daemon_summary": summary.daemon_summary,
        "total_channel_count": summary.total_channel_count,
        "enabled_channel_count": summary.enabled_channel_count,
        "channel_ids": summary.channel_ids,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

fn load_gateway_runtime(root: &Path) -> LoomResult<GatewayRuntimeRecord> {
    ensure_gateway_runtime_scaffold(root)?;
    let raw = fs::read_to_string(gateway_runtime_registry_path(root)).map_err(io_err)?;
    parse_gateway_runtime(&raw)
}

fn persist_gateway_runtime(root: &Path, record: &GatewayRuntimeRecord) -> LoomResult<()> {
    let path = gateway_runtime_registry_path(root);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    let mut rendered = serde_json::to_string_pretty(&gateway_runtime_json(record))
        .map_err(|error| error.to_string())?;
    rendered.push('\n');
    fs::write(path, rendered).map_err(io_err)
}

fn parse_gateway_runtime(raw: &str) -> LoomResult<GatewayRuntimeRecord> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid gateway runtime json: {error}"))?;
    let gateway = value
        .get("gateway")
        .and_then(Value::as_object)
        .ok_or_else(|| "gateway runtime missing gateway object".to_string())?;
    Ok(GatewayRuntimeRecord {
        gateway_id: value_string(gateway.get("gateway_id"), DEFAULT_GATEWAY_ID),
        endpoint: value_string(gateway.get("endpoint"), "http://127.0.0.1:18910"),
        bind_host: value_string(gateway.get("bind_host"), "127.0.0.1"),
        port: gateway.get("port").and_then(Value::as_u64).unwrap_or(18910) as u16,
        auth_mode: value_string(gateway.get("auth_mode"), "token"),
        credential_ref: value_string(gateway.get("credential_ref"), "LOOM_SERVICE_TOKEN"),
        tailscale_mode: value_string(gateway.get("tailscale_mode"), "off"),
        remote_mode: value_string(gateway.get("remote_mode"), "local"),
        daemon_enabled: gateway
            .get("daemon_enabled")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        daemon_manager: value_string(gateway.get("daemon_manager"), "supervisor"),
        daemon_state: value_string(gateway.get("daemon_state"), "configured"),
        channel_ids: gateway
            .get("channel_ids")
            .and_then(Value::as_array)
            .map(|items| {
                items
                    .iter()
                    .filter_map(Value::as_str)
                    .map(|value| value.trim().to_string())
                    .filter(|value| !value.is_empty())
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default(),
        total_channel_count: gateway
            .get("total_channel_count")
            .and_then(Value::as_u64)
            .unwrap_or(0) as usize,
        enabled_channel_count: gateway
            .get("enabled_channel_count")
            .and_then(Value::as_u64)
            .unwrap_or(0) as usize,
        note: value_string(gateway.get("note"), ""),
    })
}

fn gateway_runtime_json(record: &GatewayRuntimeRecord) -> Value {
    json!({
        "version": GATEWAY_RUNTIME_VERSION,
        "gateway": {
            "gateway_id": record.gateway_id,
            "endpoint": record.endpoint,
            "bind_host": record.bind_host,
            "port": record.port,
            "auth_mode": record.auth_mode,
            "credential_ref": record.credential_ref,
            "tailscale_mode": record.tailscale_mode,
            "remote_mode": record.remote_mode,
            "daemon_enabled": record.daemon_enabled,
            "daemon_manager": record.daemon_manager,
            "daemon_state": record.daemon_state,
            "channel_ids": record.channel_ids,
            "total_channel_count": record.total_channel_count,
            "enabled_channel_count": record.enabled_channel_count,
            "note": record.note,
        }
    })
}

fn value_string(value: Option<&Value>, default: &str) -> String {
    value
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or(default)
        .to_string()
}

fn io_err(error: std::io::Error) -> String {
    error.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::init_workspace;
    use crate::onboarding::{load_onboard_manifest, write_onboard_manifest};
    use std::time::{SystemTime, UNIX_EPOCH};

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
    fn sync_gateway_runtime_materializes_registry() {
        let root = temp_path("loom-gateway-runtime");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        let summary = sync_gateway_runtime(&root).expect("sync gateway runtime");
        assert_eq!(summary.gateway_id, DEFAULT_GATEWAY_ID);
        assert!(summary.endpoint.contains(":18910"));
        assert!(gateway_runtime_registry_path(&root).exists());
    }

    #[test]
    fn sync_gateway_runtime_tracks_enabled_channels_from_onboard_manifest() {
        let root = temp_path("loom-gateway-runtime-channels");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        let mut manifest = load_onboard_manifest(&root).expect("load manifest");
        manifest.telegram_enabled = true;
        write_onboard_manifest(&root, &manifest).expect("write manifest");
        let summary = sync_gateway_runtime(&root).expect("sync gateway runtime");
        assert_eq!(summary.enabled_channel_count, 2);
        assert!(summary.channel_ids.iter().any(|value| value == "telegram"));
    }
}
