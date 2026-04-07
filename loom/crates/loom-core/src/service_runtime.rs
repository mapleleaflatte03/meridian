use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use crate::{read_config, LoomResult};

pub const DEFAULT_SERVICE_RUNTIME_REGISTRY_PATH: &str = "state/service-runtime/registry.json";
const SERVICE_RUNTIME_VERSION: u32 = 1;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ServiceRuntimeRecord {
    pub service_state_path: PathBuf,
    pub service_log_path: PathBuf,
    pub service_socket_path: PathBuf,
    pub service_http_address: String,
    pub service_token_required: bool,
    pub service_available: bool,
    pub service_running: bool,
    pub service_status: String,
    pub service_session_id: String,
    pub service_pid: u32,
    pub service_pending_jobs: usize,
    pub service_processed_jobs: usize,
    pub supervisor_state_path: PathBuf,
    pub supervisor_log_path: PathBuf,
    pub supervisor_available: bool,
    pub supervisor_running: bool,
    pub supervisor_status: String,
    pub supervisor_session_id: String,
    pub supervisor_pid: u32,
    pub supervisor_pending_jobs: usize,
    pub supervisor_processed_jobs: usize,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ServiceRuntimeOverview {
    pub registry_path: PathBuf,
    pub service_state_path: PathBuf,
    pub service_socket_path: PathBuf,
    pub service_http_address: String,
    pub service_health: String,
    pub service_session_id: String,
    pub service_pid: u32,
    pub service_pending_jobs: usize,
    pub service_processed_jobs: usize,
    pub supervisor_state_path: PathBuf,
    pub supervisor_health: String,
    pub supervisor_session_id: String,
    pub supervisor_pid: u32,
    pub supervisor_pending_jobs: usize,
    pub supervisor_processed_jobs: usize,
    pub note: String,
}

pub fn service_runtime_registry_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_SERVICE_RUNTIME_REGISTRY_PATH)
}

pub fn ensure_service_runtime_scaffold(root: &Path) -> LoomResult<PathBuf> {
    let path = service_runtime_registry_path(root);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    if !path.exists() {
        sync_service_runtime(root)?;
    }
    Ok(path)
}

pub fn sync_service_runtime(root: &Path) -> LoomResult<ServiceRuntimeOverview> {
    let config = read_config(root)?;
    let service_dir = root.join(&config.run_dir).join("service");
    let state_runtime_dir = root.join(&config.state_dir).join("runtime");
    let supervisor_dir = state_runtime_dir.join("supervisor");

    fs::create_dir_all(&service_dir).map_err(io_err)?;
    fs::create_dir_all(&supervisor_dir).map_err(io_err)?;
    fs::create_dir_all(root.join(&config.log_dir)).map_err(io_err)?;

    let service_state_path = service_dir.join("runtime_state.json");
    let service_socket_path = service_dir.join("runtime.sock");
    let service_log_path = root.join(&config.log_dir).join("service.log");
    let supervisor_state_path = supervisor_dir.join("runtime_state.json");
    let supervisor_log_path = supervisor_dir.join("daemon.log");

    let service_state = if service_state_path.exists() {
        let raw = fs::read_to_string(&service_state_path).map_err(io_err)?;
        Some(
            serde_json::from_str::<Value>(&raw)
                .map_err(|error| format!("invalid runtime service state json: {error}"))?,
        )
    } else {
        None
    };
    let supervisor_state = if supervisor_state_path.exists() {
        let raw = fs::read_to_string(&supervisor_state_path).map_err(io_err)?;
        Some(
            serde_json::from_str::<Value>(&raw)
                .map_err(|error| format!("invalid supervisor daemon state json: {error}"))?,
        )
    } else {
        None
    };

    let service_pid = value_u32(service_state.as_ref(), "pid");
    let service_running_flag = value_bool(service_state.as_ref(), "running");
    let service_alive = pid_is_alive(service_pid);
    let service_status = if service_running_flag && !service_alive && service_pid > 0 {
        "crashed".to_string()
    } else {
        value_string(service_state.as_ref(), "status", "not_started")
    };
    let service_running = service_running_flag && service_alive;

    let supervisor_pid = value_u32(supervisor_state.as_ref(), "pid");
    let supervisor_running_flag = value_bool(supervisor_state.as_ref(), "running");
    let supervisor_alive = pid_is_alive(supervisor_pid);
    let supervisor_status = if supervisor_running_flag && !supervisor_alive && supervisor_pid > 0 {
        "crashed".to_string()
    } else {
        value_string(supervisor_state.as_ref(), "status", "not_started")
    };
    let supervisor_running = supervisor_running_flag && supervisor_alive;

    let service_available = service_state.is_some();
    let supervisor_available = supervisor_state.is_some();

    let service_http_address = value_string(
        service_state.as_ref(),
        "http_address",
        config.service_http_address.trim(),
    );
    let service_socket_path = PathBuf::from(value_string(
        service_state.as_ref(),
        "socket_path",
        &service_socket_path.display().to_string(),
    ));

    let record = ServiceRuntimeRecord {
        service_state_path: service_state_path.clone(),
        service_log_path,
        service_socket_path: service_socket_path.clone(),
        service_http_address: service_http_address.clone(),
        service_token_required: value_bool(service_state.as_ref(), "http_token_required"),
        service_available,
        service_running,
        service_status,
        service_session_id: value_string(service_state.as_ref(), "session_id", ""),
        service_pid,
        service_pending_jobs: value_usize(service_state.as_ref(), "pending_jobs"),
        service_processed_jobs: value_usize(service_state.as_ref(), "processed_jobs"),
        supervisor_state_path: supervisor_state_path.clone(),
        supervisor_log_path,
        supervisor_available,
        supervisor_running,
        supervisor_status,
        supervisor_session_id: value_string(supervisor_state.as_ref(), "session_id", ""),
        supervisor_pid,
        supervisor_pending_jobs: value_usize(supervisor_state.as_ref(), "pending_jobs"),
        supervisor_processed_jobs: value_usize(supervisor_state.as_ref(), "processed_jobs"),
        note: format!(
            "service={} supervisor={}",
            health_label(service_available, service_running),
            health_label(supervisor_available, supervisor_running)
        ),
    };

    persist_service_runtime(root, &record)?;
    service_runtime_overview(root)
}

pub fn service_runtime_overview(root: &Path) -> LoomResult<ServiceRuntimeOverview> {
    let record = load_service_runtime(root)?;
    Ok(ServiceRuntimeOverview {
        registry_path: service_runtime_registry_path(root),
        service_state_path: record.service_state_path,
        service_socket_path: record.service_socket_path,
        service_http_address: record.service_http_address,
        service_health: format!(
            "{} {}",
            record.service_status,
            if record.service_running {
                "running"
            } else {
                "idle"
            }
        ),
        service_session_id: record.service_session_id,
        service_pid: record.service_pid,
        service_pending_jobs: record.service_pending_jobs,
        service_processed_jobs: record.service_processed_jobs,
        supervisor_state_path: record.supervisor_state_path,
        supervisor_health: format!(
            "{} {}",
            record.supervisor_status,
            if record.supervisor_running {
                "running"
            } else {
                "idle"
            }
        ),
        supervisor_session_id: record.supervisor_session_id,
        supervisor_pid: record.supervisor_pid,
        supervisor_pending_jobs: record.supervisor_pending_jobs,
        supervisor_processed_jobs: record.supervisor_processed_jobs,
        note: record.note,
    })
}

pub fn render_service_runtime_human(summary: &ServiceRuntimeOverview) -> String {
    format!(
        "registry_path:      {}\nservice_state:      {}\nservice_socket:     {}\nservice_http:       {}\nservice_health:     {}\nservice_session:    {}\nservice_pid:        {}\nservice_jobs:       pending={} processed={}\nsupervisor_state:   {}\nsupervisor_health:  {}\nsupervisor_session: {}\nsupervisor_pid:     {}\nsupervisor_jobs:    pending={} processed={}\nnote:               {}\n",
        summary.registry_path.display(),
        summary.service_state_path.display(),
        summary.service_socket_path.display(),
        summary.service_http_address,
        summary.service_health,
        if summary.service_session_id.trim().is_empty() { "(none)" } else { summary.service_session_id.as_str() },
        summary.service_pid,
        summary.service_pending_jobs,
        summary.service_processed_jobs,
        summary.supervisor_state_path.display(),
        summary.supervisor_health,
        if summary.supervisor_session_id.trim().is_empty() { "(none)" } else { summary.supervisor_session_id.as_str() },
        summary.supervisor_pid,
        summary.supervisor_pending_jobs,
        summary.supervisor_processed_jobs,
        summary.note,
    )
}

pub fn render_service_runtime_json(summary: &ServiceRuntimeOverview) -> String {
    serde_json::to_string_pretty(&json!({
        "registry_path": summary.registry_path.display().to_string(),
        "service_state_path": summary.service_state_path.display().to_string(),
        "service_socket_path": summary.service_socket_path.display().to_string(),
        "service_http_address": summary.service_http_address,
        "service_health": summary.service_health,
        "service_session_id": summary.service_session_id,
        "service_pid": summary.service_pid,
        "service_pending_jobs": summary.service_pending_jobs,
        "service_processed_jobs": summary.service_processed_jobs,
        "supervisor_state_path": summary.supervisor_state_path.display().to_string(),
        "supervisor_health": summary.supervisor_health,
        "supervisor_session_id": summary.supervisor_session_id,
        "supervisor_pid": summary.supervisor_pid,
        "supervisor_pending_jobs": summary.supervisor_pending_jobs,
        "supervisor_processed_jobs": summary.supervisor_processed_jobs,
        "note": summary.note,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

fn load_service_runtime(root: &Path) -> LoomResult<ServiceRuntimeRecord> {
    ensure_service_runtime_scaffold(root)?;
    let raw = fs::read_to_string(service_runtime_registry_path(root)).map_err(io_err)?;
    parse_service_runtime(&raw)
}

fn persist_service_runtime(root: &Path, record: &ServiceRuntimeRecord) -> LoomResult<()> {
    let path = service_runtime_registry_path(root);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    let mut rendered = serde_json::to_string_pretty(&service_runtime_json(record))
        .map_err(|error| error.to_string())?;
    rendered.push('\n');
    fs::write(path, rendered).map_err(io_err)
}

fn parse_service_runtime(raw: &str) -> LoomResult<ServiceRuntimeRecord> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid service runtime json: {error}"))?;
    let runtime = value
        .get("runtime")
        .and_then(Value::as_object)
        .ok_or_else(|| "service runtime missing runtime object".to_string())?;
    Ok(ServiceRuntimeRecord {
        service_state_path: PathBuf::from(value_string_object(
            runtime,
            "service_state_path",
            "state/service-runtime/missing-service-state",
        )),
        service_log_path: PathBuf::from(value_string_object(
            runtime,
            "service_log_path",
            "logs/service.log",
        )),
        service_socket_path: PathBuf::from(value_string_object(
            runtime,
            "service_socket_path",
            "run/service/runtime.sock",
        )),
        service_http_address: value_string_object(
            runtime,
            "service_http_address",
            "127.0.0.1:18910",
        ),
        service_token_required: value_bool_object(runtime, "service_token_required"),
        service_available: value_bool_object(runtime, "service_available"),
        service_running: value_bool_object(runtime, "service_running"),
        service_status: value_string_object(runtime, "service_status", "not_started"),
        service_session_id: value_string_object(runtime, "service_session_id", ""),
        service_pid: value_u32_object(runtime, "service_pid"),
        service_pending_jobs: value_usize_object(runtime, "service_pending_jobs"),
        service_processed_jobs: value_usize_object(runtime, "service_processed_jobs"),
        supervisor_state_path: PathBuf::from(value_string_object(
            runtime,
            "supervisor_state_path",
            "state/runtime/supervisor/runtime_state.json",
        )),
        supervisor_log_path: PathBuf::from(value_string_object(
            runtime,
            "supervisor_log_path",
            "state/runtime/supervisor/daemon.log",
        )),
        supervisor_available: value_bool_object(runtime, "supervisor_available"),
        supervisor_running: value_bool_object(runtime, "supervisor_running"),
        supervisor_status: value_string_object(runtime, "supervisor_status", "not_started"),
        supervisor_session_id: value_string_object(runtime, "supervisor_session_id", ""),
        supervisor_pid: value_u32_object(runtime, "supervisor_pid"),
        supervisor_pending_jobs: value_usize_object(runtime, "supervisor_pending_jobs"),
        supervisor_processed_jobs: value_usize_object(runtime, "supervisor_processed_jobs"),
        note: value_string_object(runtime, "note", ""),
    })
}

fn service_runtime_json(record: &ServiceRuntimeRecord) -> Value {
    json!({
        "version": SERVICE_RUNTIME_VERSION,
        "runtime": {
            "service_state_path": record.service_state_path.display().to_string(),
            "service_log_path": record.service_log_path.display().to_string(),
            "service_socket_path": record.service_socket_path.display().to_string(),
            "service_http_address": record.service_http_address,
            "service_token_required": record.service_token_required,
            "service_available": record.service_available,
            "service_running": record.service_running,
            "service_status": record.service_status,
            "service_session_id": record.service_session_id,
            "service_pid": record.service_pid,
            "service_pending_jobs": record.service_pending_jobs,
            "service_processed_jobs": record.service_processed_jobs,
            "supervisor_state_path": record.supervisor_state_path.display().to_string(),
            "supervisor_log_path": record.supervisor_log_path.display().to_string(),
            "supervisor_available": record.supervisor_available,
            "supervisor_running": record.supervisor_running,
            "supervisor_status": record.supervisor_status,
            "supervisor_session_id": record.supervisor_session_id,
            "supervisor_pid": record.supervisor_pid,
            "supervisor_pending_jobs": record.supervisor_pending_jobs,
            "supervisor_processed_jobs": record.supervisor_processed_jobs,
            "note": record.note,
        }
    })
}

fn value_string(value: Option<&Value>, key: &str, default: &str) -> String {
    value
        .and_then(|object| object.get(key))
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or(default)
        .to_string()
}

fn value_bool(value: Option<&Value>, key: &str) -> bool {
    value
        .and_then(|object| object.get(key))
        .and_then(Value::as_bool)
        .unwrap_or(false)
}

fn value_usize(value: Option<&Value>, key: &str) -> usize {
    value
        .and_then(|object| object.get(key))
        .and_then(Value::as_u64)
        .unwrap_or(0) as usize
}

fn value_u32(value: Option<&Value>, key: &str) -> u32 {
    value
        .and_then(|object| object.get(key))
        .and_then(Value::as_u64)
        .unwrap_or(0) as u32
}

fn value_string_object(
    object: &serde_json::Map<String, Value>,
    key: &str,
    default: &str,
) -> String {
    object
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or(default)
        .to_string()
}

fn value_bool_object(object: &serde_json::Map<String, Value>, key: &str) -> bool {
    object.get(key).and_then(Value::as_bool).unwrap_or(false)
}

fn value_usize_object(object: &serde_json::Map<String, Value>, key: &str) -> usize {
    object.get(key).and_then(Value::as_u64).unwrap_or(0) as usize
}

fn value_u32_object(object: &serde_json::Map<String, Value>, key: &str) -> u32 {
    object.get(key).and_then(Value::as_u64).unwrap_or(0) as u32
}

fn pid_is_alive(pid: u32) -> bool {
    pid > 0 && PathBuf::from(format!("/proc/{}", pid)).exists()
}

fn health_label(available: bool, running: bool) -> &'static str {
    if running {
        "running"
    } else if available {
        "available"
    } else {
        "not_started"
    }
}

fn io_err(error: std::io::Error) -> String {
    error.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::init_workspace;
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
    fn sync_service_runtime_materializes_registry_with_defaults() {
        let root = temp_path("loom-service-runtime");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        let summary = sync_service_runtime(&root).expect("sync service runtime");
        assert_eq!(summary.service_health, "not_started idle");
        assert_eq!(summary.supervisor_health, "not_started idle");
        assert!(service_runtime_registry_path(&root).exists());
    }

    #[test]
    fn sync_service_runtime_reads_runtime_state_files() {
        let root = temp_path("loom-service-runtime-state");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        let service_state = root.join("run/service/runtime_state.json");
        let supervisor_state = root.join("state/runtime/supervisor/runtime_state.json");
        fs::create_dir_all(service_state.parent().expect("service parent")).expect("service dir");
        fs::create_dir_all(supervisor_state.parent().expect("supervisor parent"))
            .expect("supervisor dir");
        fs::write(
            &service_state,
            serde_json::to_string_pretty(&json!({
                "status": "running",
                "session_id": "service-demo",
                "pid": std::process::id(),
                "running": true,
                "socket_path": root.join("run/service/runtime.sock").display().to_string(),
                "http_address": "127.0.0.1:18910",
                "pending_jobs": 2,
                "processed_jobs": 5
            }))
            .expect("render service state"),
        )
        .expect("write service state");
        fs::write(
            &supervisor_state,
            serde_json::to_string_pretty(&json!({
                "status": "running",
                "session_id": "daemon-demo",
                "pid": std::process::id(),
                "running": true,
                "pending_jobs": 1,
                "processed_jobs": 3
            }))
            .expect("render supervisor state"),
        )
        .expect("write supervisor state");

        let summary = sync_service_runtime(&root).expect("sync service runtime");
        assert_eq!(summary.service_session_id, "service-demo");
        assert_eq!(summary.service_pending_jobs, 2);
        assert_eq!(summary.supervisor_session_id, "daemon-demo");
        assert_eq!(summary.supervisor_processed_jobs, 3);
    }
}
