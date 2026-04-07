use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

pub mod advanced_primitives;
pub mod agent_marketplace;
pub mod agent_runtime;
pub mod bindings;
pub mod capabilities;
pub mod capability_shims;
pub mod channels;
pub mod context_engine;
pub mod event_sourcing;
pub mod gateway_runtime;
pub mod memory_hybrid;
pub mod memory_service;
pub mod onboarding;
pub mod output_guard;
pub mod pipeline;
pub mod provider_auth_store;
pub mod provider_router;
pub mod recurring;
pub mod recurring_executor;
pub mod schedules;
pub mod service_ingress_runtime;
pub mod service_runtime;
pub mod session_policy;
pub mod session_provenance;
pub mod skill_lifecycle;
pub mod skills;
pub mod transport_contract;
pub mod wasm_host;
pub mod wasm_limits;
pub mod wasm_profiles;

pub type LoomResult<T> = Result<T, String>;

const DEFAULT_STATE_DIR: &str = "state";
const DEFAULT_RUN_DIR: &str = "run";
const DEFAULT_LOG_DIR: &str = "logs";
const DEFAULT_ARTIFACT_DIR: &str = "artifacts";
const DEFAULT_CAPABILITIES_DIR: &str = "capabilities";
const DEFAULT_SERVICE_HTTP_ADDRESS: &str = "127.0.0.1:18910";
const DEFAULT_SERVICE_TOKEN_ENV: &str = "LOOM_SERVICE_TOKEN";
const DEFAULT_LOG_LEVEL: &str = "info";
const DEFAULT_LOG_FORMAT: &str = "jsonl";
const DEFAULT_LOG_MAX_BYTES: usize = 5 * 1024 * 1024;
const DEFAULT_LOG_MAX_FILES: usize = 5;
pub const DEFAULT_DELIVERY_QUEUE: &str = "state/delivery-queue";
const DEFAULT_PYTHON_WORKER_FILE: &str = "loom_runtime_worker.py";
const DEFAULT_PYTHON_WORKER_SOURCE: &str = r#"#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone


def main():
    parser = argparse.ArgumentParser(description="Meridian Loom experimental worker")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    envelope = payload.get("envelope", {})
    capability = payload.get("capability") or {}
    decision = payload.get("decision", {})
    raw_payload = envelope.get("payload_json", "") or payload.get("payload_json", "")
    parsed_payload = {}
    if raw_payload:
        try:
            parsed_payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            parsed_payload = {"raw_payload": raw_payload}
    summary = parsed_payload.get(
        "message",
        f"capability {capability.get('name', 'default')} handled {envelope.get('action_type', 'unknown')}::{envelope.get('resource', 'unknown')}",
    )
    result = {
        "status": "completed",
        "worker_kind": capability.get("worker_kind", "python_reference_worker"),
        "worker_contract_version": payload.get("worker_contract_version", "loom.worker.v0"),
        "capability_name": capability.get("name", ""),
        "completed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "agent_id": envelope.get("agent_id", ""),
        "org_id": envelope.get("org_id", ""),
        "action_type": envelope.get("action_type", ""),
        "resource": envelope.get("resource", ""),
        "input_hash": payload.get("input_hash", ""),
        "decision": decision.get("overall_decision", ""),
        "effective_stage": decision.get("effective_stage", ""),
        "summary": summary,
        "payload": parsed_payload,
    }

    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")

    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
"#;
const EXPERIMENTAL_PRELIGHT_HOOKS: [&str; 7] = [
    "agent_identity",
    "action_envelope",
    "cost_attribution",
    "approval_hook",
    "audit_emission",
    "sanction_controls",
    "budget_gate",
];

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Config {
    pub mode: String,
    pub kernel_path: String,
    pub org_id: String,
    pub state_dir: String,
    pub run_dir: String,
    pub log_dir: String,
    pub artifact_dir: String,
    pub capabilities_dir: String,
    pub python_path: String,
    pub typescript_path: String,
    pub wasm_dir: String,
    pub service_http_address: String,
    pub service_token_env: String,
    pub service_max_jobs: usize,
    pub service_poll_seconds: u64,
    pub service_max_iterations: usize,
    pub log_level: String,
    pub log_format: String,
    pub log_max_bytes: usize,
    pub log_max_files: usize,
    pub handoff_mode: String,
    pub delivery_queue: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Check {
    pub level: &'static str,
    pub label: &'static str,
    pub detail: String,
    pub category: &'static str,
    pub remediation: &'static str,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ContractSnapshot {
    pub kernel_path: PathBuf,
    pub runtime_status: String,
    pub local_scaffold: String,
    pub notes: String,
    pub hooks: Vec<(String, String)>,
    pub experimental_hooks: Vec<(String, String)>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapsuleInspection {
    pub org_id: String,
    pub manifest_path: PathBuf,
    pub state_dir: PathBuf,
    pub files: Vec<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct AgentIdentityResolution {
    pub agent_id: String,
    pub agent_name: String,
    pub org_id: String,
    pub role: String,
    pub economy_key: String,
    pub approval_required: bool,
    pub max_per_run_usd: Option<f64>,
    pub restrictions: Vec<String>,
    pub sanction_decision: String,
    pub runtime_id: String,
    pub runtime_label: String,
    pub bound_org_id: String,
    pub boundary_name: String,
    pub identity_model: String,
    pub runtime_registered: bool,
    pub registration_status: String,
    pub source: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct ActionEnvelope {
    pub agent_id: String,
    pub agent_name: String,
    pub org_id: String,
    pub runtime_id: String,
    pub runtime_label: String,
    pub action_type: String,
    pub resource: String,
    pub capability_name: String,
    pub payload_json: String,
    pub estimated_cost_usd: f64,
    pub run_id: String,
    pub session_id: String,
    pub source: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct ReferenceGateCheck {
    pub allowed: bool,
    pub stage: String,
    pub reason: String,
    pub restrictions: Vec<String>,
    pub sanction_gate_decision: String,
    pub approval_gate_decision: String,
    pub budget_gate_decision: String,
    pub source: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LocalSanctionPreview {
    pub allowed: bool,
    pub decision: String,
    pub reason: String,
}

/// Hard enforcement result for sanction controls.
/// Unlike preview, this produces `hard_deny` when an agent is restricted.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SanctionEnforcement {
    pub allowed: bool,
    pub decision: String,
    pub reason: String,
}

#[derive(Clone, Debug)]
pub struct HookVerification {
    pub hook_name: String,
    pub passed: bool,
    pub detail: String,
    pub artifact_path: Option<PathBuf>,
}

#[derive(Clone, Debug)]
pub struct ContractVerifyResult {
    pub kernel_path: PathBuf,
    pub hooks: Vec<HookVerification>,
    pub passed: usize,
    pub total: usize,
}

pub fn init_workspace(
    root: &Path,
    mode: &str,
    kernel_path: Option<&str>,
    org_id: &str,
) -> LoomResult<Config> {
    let mode = normalize_mode(mode)?;
    let root = ensure_root(root)?;
    let config_path = root.join("loom.toml");
    if config_path.exists() {
        return Err(format!(
            "refusing to overwrite existing config at {}",
            config_path.display()
        ));
    }

    let state_dir = root.join(DEFAULT_STATE_DIR);
    let run_dir = root.join(DEFAULT_RUN_DIR);
    let log_dir = root.join(DEFAULT_LOG_DIR);
    let artifact_dir = root.join(DEFAULT_ARTIFACT_DIR);
    let capabilities_dir = root.join(DEFAULT_CAPABILITIES_DIR);
    let capsule_dir = state_dir.join("capsules").join(org_id);
    let shadow_dir = artifact_dir.join("shadow");
    let workers_python = root.join("workers/python");
    let workers_typescript = root.join("workers/typescript");
    let workers_wasm = root.join("workers/wasm");
    let delivery_queue = state_dir.join("delivery-queue");

    fs::create_dir_all(&capsule_dir).map_err(io_err)?;
    fs::create_dir_all(&shadow_dir).map_err(io_err)?;
    fs::create_dir_all(run_dir.join("service")).map_err(io_err)?;
    fs::create_dir_all(run_dir.join("ingress")).map_err(io_err)?;
    fs::create_dir_all(&log_dir).map_err(io_err)?;
    fs::create_dir_all(artifact_dir.join("audit")).map_err(io_err)?;
    fs::create_dir_all(artifact_dir.join("parity")).map_err(io_err)?;
    fs::create_dir_all(&capabilities_dir).map_err(io_err)?;
    fs::create_dir_all(&workers_python).map_err(io_err)?;
    fs::create_dir_all(&workers_typescript).map_err(io_err)?;
    fs::create_dir_all(&workers_wasm).map_err(io_err)?;
    fs::create_dir_all(&delivery_queue).map_err(io_err)?;

    let kernel_path = kernel_path.unwrap_or_default().to_string();
    let config = Config {
        mode,
        kernel_path,
        org_id: org_id.to_string(),
        state_dir: DEFAULT_STATE_DIR.to_string(),
        run_dir: DEFAULT_RUN_DIR.to_string(),
        log_dir: DEFAULT_LOG_DIR.to_string(),
        artifact_dir: DEFAULT_ARTIFACT_DIR.to_string(),
        capabilities_dir: DEFAULT_CAPABILITIES_DIR.to_string(),
        python_path: "workers/python".to_string(),
        typescript_path: "workers/typescript".to_string(),
        wasm_dir: "workers/wasm".to_string(),
        service_http_address: DEFAULT_SERVICE_HTTP_ADDRESS.to_string(),
        service_token_env: DEFAULT_SERVICE_TOKEN_ENV.to_string(),
        service_max_jobs: 8,
        service_poll_seconds: 1,
        service_max_iterations: 0,
        log_level: DEFAULT_LOG_LEVEL.to_string(),
        log_format: DEFAULT_LOG_FORMAT.to_string(),
        log_max_bytes: DEFAULT_LOG_MAX_BYTES,
        log_max_files: DEFAULT_LOG_MAX_FILES,
        handoff_mode: "off".to_string(),
        delivery_queue: DEFAULT_DELIVERY_QUEUE.to_string(),
    };
    ensure_runtime_worker_scaffold(&root, &config)?;
    capabilities::ensure_capability_registry_scaffold(&root, &config)?;
    agent_runtime::ensure_agent_runtime_scaffold(&root)?;
    context_engine::ensure_context_engine_scaffold(&root)?;
    recurring::ensure_heartbeat_runtime_scaffold(&root)?;
    schedules::ensure_schedule_runtime_scaffold(&root)?;
    provider_router::ensure_provider_profiles_scaffold(&root)?;
    provider_auth_store::ensure_provider_auth_store_scaffold(&root)?;
    onboarding::ensure_onboard_manifest(&root, &config)?;
    channels::ensure_channel_runtime_scaffold(&root)?;
    gateway_runtime::ensure_gateway_runtime_scaffold(&root)?;

    fs::write(&config_path, render_config(&config)).map_err(io_err)?;
    service_runtime::ensure_service_runtime_scaffold(&root)?;
    service_ingress_runtime::ensure_service_ingress_runtime_scaffold(&root)?;
    bindings::ensure_binding_runtime_scaffold(&root)?;
    skills::ensure_skill_runtime_scaffold(&root)?;
    fs::write(
        state_dir.join("state.json"),
        format!(
            "{{\n  \"org_id\": {},\n  \"mode\": {},\n  \"created_at\": {},\n  \"status\": \"initialized\"\n}}\n",
            json_string(&config.org_id),
            json_string(&config.mode),
            unix_now()
        ),
    )
    .map_err(io_err)?;
    fs::write(
        log_dir.join("bootstrap.log"),
        format!(
            "{} init mode={} org_id={}\n",
            unix_now(),
            config.mode,
            config.org_id
        ),
    )
    .map_err(io_err)?;
    fs::write(
        capsule_dir.join("manifest.json"),
        format!(
            "{{\n  \"org_id\": {},\n  \"state\": \"local_embedded_capsule\",\n  \"provenance\": \"experimental_scaffold\",\n  \"created_at\": {},\n  \"files\": [\"state/state.json\", \"logs/bootstrap.log\"]\n}}\n",
            json_string(&config.org_id),
            unix_now()
        ),
    )
    .map_err(io_err)?;
    fs::write(
        shadow_dir.join("latest.json"),
        "{\n  \"status\": \"not_started\",\n  \"events_compared\": 0,\n  \"divergences\": 0,\n  \"note\": \"shadow mode is not implemented in this scaffold\"\n}\n",
    )
    .map_err(io_err)?;
    fs::write(shadow_dir.join("events.jsonl"), "").map_err(io_err)?;

    Ok(config)
}

pub fn write_config(root: &Path, config: &Config) -> LoomResult<PathBuf> {
    let root = ensure_root(root)?;
    let config_path = root.join("loom.toml");
    fs::write(&config_path, render_config(config)).map_err(io_err)?;
    Ok(config_path)
}

pub fn read_config(root: &Path) -> LoomResult<Config> {
    let root = ensure_root(root)?;
    let contents = fs::read_to_string(root.join("loom.toml")).map_err(io_err)?;
    let mut values = BTreeMap::new();
    for raw in contents.lines() {
        let line = raw.trim();
        if line.is_empty() || line.starts_with('#') || line.starts_with('[') {
            continue;
        }
        let Some((key, value)) = line.split_once('=') else {
            continue;
        };
        values.insert(
            key.trim().to_string(),
            value.trim().trim_matches('"').to_string(),
        );
    }

    let legacy_layout = root.join(".loom").exists() && !values.contains_key("state_dir");

    let config = Config {
        mode: values
            .get("mode")
            .cloned()
            .ok_or_else(|| "loom.toml missing runtime.mode".to_string())?,
        kernel_path: values.get("kernel_path").cloned().unwrap_or_default(),
        org_id: values
            .get("org_id")
            .cloned()
            .unwrap_or_else(|| "local_foundry".to_string()),
        state_dir: values.get("state_dir").cloned().unwrap_or_else(|| {
            if legacy_layout {
                ".loom".to_string()
            } else {
                DEFAULT_STATE_DIR.to_string()
            }
        }),
        run_dir: values.get("run_dir").cloned().unwrap_or_else(|| {
            if legacy_layout {
                ".loom/runtime".to_string()
            } else {
                DEFAULT_RUN_DIR.to_string()
            }
        }),
        log_dir: values.get("log_dir").cloned().unwrap_or_else(|| {
            if legacy_layout {
                ".loom/runtime/service".to_string()
            } else {
                DEFAULT_LOG_DIR.to_string()
            }
        }),
        artifact_dir: values.get("artifact_dir").cloned().unwrap_or_else(|| {
            if legacy_layout {
                ".loom".to_string()
            } else {
                DEFAULT_ARTIFACT_DIR.to_string()
            }
        }),
        capabilities_dir: values
            .get("capabilities_dir")
            .cloned()
            .unwrap_or_else(|| DEFAULT_CAPABILITIES_DIR.to_string()),
        python_path: values
            .get("python_path")
            .cloned()
            .unwrap_or_else(|| "workers/python".to_string()),
        typescript_path: values
            .get("typescript_path")
            .cloned()
            .unwrap_or_else(|| "workers/typescript".to_string()),
        wasm_dir: values
            .get("wasm_dir")
            .cloned()
            .unwrap_or_else(|| "workers/wasm".to_string()),
        service_http_address: values
            .get("service_http_address")
            .cloned()
            .unwrap_or_else(|| DEFAULT_SERVICE_HTTP_ADDRESS.to_string()),
        service_token_env: values
            .get("service_token_env")
            .cloned()
            .unwrap_or_else(|| DEFAULT_SERVICE_TOKEN_ENV.to_string()),
        service_max_jobs: values
            .get("service_max_jobs")
            .and_then(|value| value.parse::<usize>().ok())
            .unwrap_or(8),
        service_poll_seconds: values
            .get("service_poll_seconds")
            .and_then(|value| value.parse::<u64>().ok())
            .unwrap_or(1),
        service_max_iterations: values
            .get("service_max_iterations")
            .and_then(|value| value.parse::<usize>().ok())
            .unwrap_or(0),
        log_level: values
            .get("log_level")
            .cloned()
            .unwrap_or_else(|| DEFAULT_LOG_LEVEL.to_string()),
        log_format: values
            .get("log_format")
            .cloned()
            .unwrap_or_else(|| DEFAULT_LOG_FORMAT.to_string()),
        log_max_bytes: values
            .get("log_max_bytes")
            .and_then(|value| value.parse::<usize>().ok())
            .unwrap_or(DEFAULT_LOG_MAX_BYTES),
        log_max_files: values
            .get("log_max_files")
            .and_then(|value| value.parse::<usize>().ok())
            .unwrap_or(DEFAULT_LOG_MAX_FILES),
        handoff_mode: values
            .get("handoff_mode")
            .or_else(|| values.get("legacy_v1_integration"))
            .cloned()
            .unwrap_or_else(|| "off".to_string()),
        delivery_queue: values
            .get("delivery_queue")
            .or_else(|| values.get("legacy_v1_delivery_queue"))
            .cloned()
            .unwrap_or_else(|| DEFAULT_DELIVERY_QUEUE.to_string()),
    };

    normalize_mode(&config.mode)?;
    Ok(config)
}

pub fn ensure_runtime_worker_scaffold(root: &Path, config: &Config) -> LoomResult<PathBuf> {
    let worker_path = root
        .join(&config.python_path)
        .join(DEFAULT_PYTHON_WORKER_FILE);
    if let Some(parent) = worker_path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    if !worker_path.exists() {
        fs::write(&worker_path, DEFAULT_PYTHON_WORKER_SOURCE).map_err(io_err)?;
    }
    Ok(worker_path)
}

pub fn runtime_worker_entry(root: &Path, config: &Config) -> PathBuf {
    root.join(&config.python_path)
        .join(DEFAULT_PYTHON_WORKER_FILE)
}

pub fn doctor(root: &Path) -> LoomResult<Vec<Check>> {
    let root = ensure_root(root)?;
    let config = read_config(&root)?;
    let mut checks = Vec::new();

    checks.push(Check {
        level: "OK",
        label: "config",
        detail: format!("loaded {}", root.join("loom.toml").display()),
        category: "config",
        remediation: "",
    });

    let state_dir = root.join(&config.state_dir);
    let run_dir = root.join(&config.run_dir);
    let log_dir = root.join(&config.log_dir);
    let artifact_dir = root.join(&config.artifact_dir);
    let capabilities_dir = root.join(&config.capabilities_dir);
    push_path_check(
        &mut checks,
        "state_dir",
        &state_dir,
        true,
        "state directory present",
        "config",
        "loom onboard",
    );
    push_path_check(
        &mut checks,
        "run_dir",
        &run_dir,
        true,
        "runtime run directory present",
        "config",
        "loom onboard",
    );
    push_path_check(
        &mut checks,
        "log_dir",
        &log_dir,
        true,
        "log directory present",
        "config",
        "loom onboard",
    );
    push_path_check(
        &mut checks,
        "artifact_dir",
        &artifact_dir,
        true,
        "artifact directory present",
        "config",
        "loom onboard",
    );
    push_path_check(
        &mut checks,
        "capabilities_dir",
        &capabilities_dir,
        true,
        "capability registry directory present",
        "config",
        "loom onboard",
    );
    push_path_check(
        &mut checks,
        "capability_registry",
        &capabilities::capability_registry_path(&root, &config),
        true,
        "capability registry manifest present",
        "config",
        "loom onboard",
    );
    let provider_profiles_path = provider_router::provider_profiles_runtime_path(Some(&root))?;
    push_path_check(
        &mut checks,
        "provider_profiles",
        &provider_profiles_path,
        false,
        "provider profiles manifest present",
        "provider",
        "loom onboard",
    );
    match provider_router::provider_plane_summary(Some(&root)) {
        Ok(summary) => checks.push(Check {
            level: "OK",
            label: "provider_plane",
            detail: format!(
                "default_profile={} profiles={} capability_routes={} agent_routes={}",
                summary.default_profile_name,
                summary.profile_count,
                summary.capability_route_count,
                summary.agent_route_count
            ),
            category: "provider",
            remediation: "",
        }),
        Err(error) => checks.push(Check {
            level: "WARN",
            label: "provider_plane",
            detail: format!("provider plane unavailable: {}", error),
            category: "provider",
            remediation: "loom provider login --source loom",
        }),
    }

    match provider_router::provider_auth_status(Some(&root), None) {
        Ok(status) => checks.push(Check {
            level: if status.ready { "OK" } else { "WARN" },
            label: "provider_auth",
            detail: format!(
                "profile={} mode={} ready={} detail={}",
                status.profile_name, status.auth_mode, status.ready, status.detail
            ),
            category: "provider",
            remediation: if status.ready {
                ""
            } else {
                "loom provider login --source loom"
            },
        }),
        Err(error) => checks.push(Check {
            level: "WARN",
            label: "provider_auth",
            detail: format!("provider auth unavailable: {}", error),
            category: "provider",
            remediation: "loom provider login --source loom",
        }),
    }
    match provider_auth_store::ensure_provider_auth_store_scaffold(&root) {
        Ok(store_path) => {
            push_path_check(
                &mut checks,
                "provider_auth_store",
                &store_path,
                false,
                "provider auth store present",
                "provider",
                "loom onboard",
            );
            match provider_auth_store::sync_provider_auth_store(&root) {
                Ok(summary) => checks.push(Check {
                    level: if summary.ready_count > 0 {
                        "OK"
                    } else {
                        "WARN"
                    },
                    label: "provider_auth_runtime",
                    detail: format!(
                        "profiles={} ready={} last_good={} usage_stats={}",
                        summary.profile_count,
                        summary.ready_count,
                        summary.last_good_count,
                        summary.usage_stats_count
                    ),
                    category: "provider",
                    remediation: if summary.ready_count > 0 {
                        ""
                    } else {
                        "loom provider login --source loom"
                    },
                }),
                Err(error) => checks.push(Check {
                    level: "WARN",
                    label: "provider_auth_runtime",
                    detail: format!("provider auth store unavailable: {}", error),
                    category: "provider",
                    remediation: "loom provider login --source loom",
                }),
            }
        }
        Err(error) => checks.push(Check {
            level: "WARN",
            label: "provider_auth_store",
            detail: format!("provider auth store unavailable: {}", error),
            category: "provider",
            remediation: "loom onboard",
        }),
    }
    match gateway_runtime::ensure_gateway_runtime_scaffold(&root) {
        Ok(gateway_registry) => {
            push_path_check(
                &mut checks,
                "gateway_registry",
                &gateway_registry,
                false,
                "gateway runtime registry present",
                "gateway",
                "loom onboard",
            );
            match gateway_runtime::gateway_runtime_overview(&root) {
                Ok(summary) => checks.push(Check {
                    level: if summary.enabled_channel_count > 0 {
                        "OK"
                    } else {
                        "WARN"
                    },
                    label: "gateway_runtime",
                    detail: format!(
                        "gateway={} endpoint={} auth={} remote={} channels={}/{} daemon={}",
                        summary.gateway_id,
                        summary.endpoint,
                        summary.auth_mode,
                        summary.remote_mode,
                        summary.enabled_channel_count,
                        summary.total_channel_count,
                        summary.daemon_summary
                    ),
                    category: "gateway",
                    remediation: if summary.enabled_channel_count > 0 {
                        ""
                    } else {
                        "loom onboard --gateway-port 18910"
                    },
                }),
                Err(error) => checks.push(Check {
                    level: "WARN",
                    label: "gateway_runtime",
                    detail: format!("gateway runtime unavailable: {}", error),
                    category: "gateway",
                    remediation: "loom onboard --gateway-port 18910",
                }),
            }
        }
        Err(error) => checks.push(Check {
            level: "WARN",
            label: "gateway_registry",
            detail: format!("gateway runtime unavailable: {}", error),
            category: "gateway",
            remediation: "loom onboard --gateway-port 18910",
        }),
    }
    match service_runtime::ensure_service_runtime_scaffold(&root) {
        Ok(service_registry) => {
            push_path_check(
                &mut checks,
                "service_runtime_registry",
                &service_registry,
                false,
                "service runtime registry present",
                "service",
                "loom onboard",
            );
            match service_runtime::sync_service_runtime(&root) {
                Ok(summary) => checks.push(Check {
                    level: if summary.service_health.starts_with("crashed")
                        || summary.supervisor_health.starts_with("crashed")
                    {
                        "WARN"
                    } else {
                        "OK"
                    },
                    label: "service_runtime",
                    detail: format!(
                        "service={} pending={} processed={} supervisor={} pending={} processed={}",
                        summary.service_health,
                        summary.service_pending_jobs,
                        summary.service_processed_jobs,
                        summary.supervisor_health,
                        summary.supervisor_pending_jobs,
                        summary.supervisor_processed_jobs,
                    ),
                    category: "service",
                    remediation: if summary.service_health.starts_with("crashed")
                        || summary.supervisor_health.starts_with("crashed")
                    {
                        "loom service start"
                    } else {
                        ""
                    },
                }),
                Err(error) => checks.push(Check {
                    level: "WARN",
                    label: "service_runtime",
                    detail: format!("service runtime unavailable: {}", error),
                    category: "service",
                    remediation: "loom service start",
                }),
            }
        }
        Err(error) => checks.push(Check {
            level: "WARN",
            label: "service_runtime_registry",
            detail: format!("service runtime unavailable: {}", error),
            category: "service",
            remediation: "loom service start",
        }),
    }
    match service_ingress_runtime::ensure_service_ingress_runtime_scaffold(&root) {
        Ok(ingress_registry) => {
            push_path_check(
                &mut checks,
                "service_ingress_registry",
                &ingress_registry,
                false,
                "service ingress registry present",
                "service",
                "loom onboard",
            );
            match service_ingress_runtime::sync_service_ingress_runtime(&root) {
                Ok(summary) => checks.push(Check {
                    level: "OK",
                    label: "service_ingress_runtime",
                    detail: format!(
                        "requests={} accepted={} pending={} last_request={} last_job={}",
                        summary.total_requests,
                        summary.accepted_count,
                        summary.pending_count,
                        if summary.last_request_id.is_empty() {
                            "(none)"
                        } else {
                            summary.last_request_id.as_str()
                        },
                        if summary.last_job_id.is_empty() {
                            "(none)"
                        } else {
                            summary.last_job_id.as_str()
                        },
                    ),
                    category: "service",
                    remediation: "",
                }),
                Err(error) => checks.push(Check {
                    level: "WARN",
                    label: "service_ingress_runtime",
                    detail: format!("service ingress runtime unavailable: {}", error),
                    category: "service",
                    remediation: "loom service start",
                }),
            }
        }
        Err(error) => checks.push(Check {
            level: "WARN",
            label: "service_ingress_registry",
            detail: format!("service ingress runtime unavailable: {}", error),
            category: "service",
            remediation: "loom service start",
        }),
    }
    match onboarding::ensure_onboard_manifest(&root, &config) {
        Ok(onboard_manifest) => {
            push_path_check(
                &mut checks,
                "onboard_manifest",
                &onboard_manifest,
                true,
                "onboard manifest present",
                "config",
                "loom onboard",
            );
            match onboarding::onboard_overview(&root) {
                Ok(overview) => checks.push(Check {
                    level: "OK",
                    label: "onboard_runtime",
                    detail: format!(
                        "action={} gateway={} telegram={} daemon={} remote={}",
                        overview.last_action,
                        overview.gateway_summary,
                        overview.telegram_summary,
                        overview.daemon_summary,
                        overview.remote_mode
                    ),
                    category: "config",
                    remediation: "",
                }),
                Err(error) => checks.push(Check {
                    level: "WARN",
                    label: "onboard_runtime",
                    detail: format!("onboard overview unavailable: {}", error),
                    category: "config",
                    remediation: "loom onboard",
                }),
            }
        }
        Err(error) => checks.push(Check {
            level: "WARN",
            label: "onboard_manifest",
            detail: format!("onboard manifest unavailable: {}", error),
            category: "config",
            remediation: "loom onboard",
        }),
    }
    match agent_runtime::ensure_agent_runtime_scaffold(&root) {
        Ok(agent_runtime_registry) => {
            push_path_check(
                &mut checks,
                "agent_runtime_registry",
                &agent_runtime_registry,
                true,
                "agent runtime registry present",
                "agent",
                "loom onboard",
            );
            match agent_runtime::agent_runtime_overview(&root) {
                Ok(overview) => checks.push(Check {
                    level: if overview.memory_ready_count == overview.profile_count
                        && overview.session_ready_count == overview.profile_count
                    {
                        "OK"
                    } else {
                        "WARN"
                    },
                    label: "agent_runtime",
                    detail: format!(
                        "profiles={} agents={} memory_ready={}/{} session_ready={}/{}",
                        overview.profile_count,
                        overview.agent_ids.join(","),
                        overview.memory_ready_count,
                        overview.profile_count,
                        overview.session_ready_count,
                        overview.profile_count
                    ),
                    category: "agent",
                    remediation: if overview.memory_ready_count == overview.profile_count
                        && overview.session_ready_count == overview.profile_count
                    {
                        ""
                    } else {
                        "loom onboard"
                    },
                }),
                Err(error) => checks.push(Check {
                    level: "WARN",
                    label: "agent_runtime",
                    detail: format!("agent runtime unavailable: {}", error),
                    category: "agent",
                    remediation: "loom onboard",
                }),
            }
        }
        Err(error) => checks.push(Check {
            level: "WARN",
            label: "agent_runtime_registry",
            detail: format!("agent runtime scaffold unavailable: {}", error),
            category: "agent",
            remediation: "loom onboard",
        }),
    }
    match context_engine::ensure_context_engine_scaffold(&root) {
        Ok(context_registry) => {
            push_path_check(
                &mut checks,
                "context_registry",
                &context_registry,
                false,
                "context engine registry present",
                "context",
                "loom onboard",
            );
            match context_engine::context_engine_overview(&root) {
                Ok(summary) => checks.push(Check {
                    level: if summary.layer_count > 0 {
                        "OK"
                    } else {
                        "WARN"
                    },
                    label: "context_engine",
                    detail: format!(
                        "layers={} sections={} mutable={} overlay_root={}",
                        summary.layer_count,
                        summary.section_count,
                        summary.mutable_count,
                        summary.overlay_root.display()
                    ),
                    category: "context",
                    remediation: if summary.layer_count > 0 {
                        ""
                    } else {
                        "loom onboard"
                    },
                }),
                Err(error) => checks.push(Check {
                    level: "WARN",
                    label: "context_engine",
                    detail: format!("context engine unavailable: {}", error),
                    category: "context",
                    remediation: "loom onboard",
                }),
            }
        }
        Err(error) => checks.push(Check {
            level: "WARN",
            label: "context_registry",
            detail: format!("context engine scaffold unavailable: {}", error),
            category: "context",
            remediation: "loom onboard",
        }),
    }
    match recurring::ensure_heartbeat_runtime_scaffold(&root) {
        Ok(heartbeat_registry) => {
            push_path_check(
                &mut checks,
                "heartbeat_registry",
                &heartbeat_registry,
                true,
                "heartbeat runtime registry present",
                "lifecycle",
                "loom onboard",
            );
            match recurring::heartbeat_overview(
                &root,
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_millis() as u64,
            ) {
                Ok(overview) => checks.push(Check {
                    level: "OK",
                    label: "heartbeat_runtime",
                    detail: format!(
                        "total={} enabled={} due={} runs_path={}",
                        overview.total_count,
                        overview.enabled_count,
                        overview.due_count,
                        overview.runs_path.display()
                    ),
                    category: "lifecycle",
                    remediation: "",
                }),
                Err(error) => checks.push(Check {
                    level: "WARN",
                    label: "heartbeat_runtime",
                    detail: format!("heartbeat runtime unavailable: {}", error),
                    category: "lifecycle",
                    remediation: "loom doctor",
                }),
            }
        }
        Err(error) => checks.push(Check {
            level: "WARN",
            label: "heartbeat_registry",
            detail: format!("heartbeat runtime scaffold unavailable: {}", error),
            category: "lifecycle",
            remediation: "loom onboard",
        }),
    }
    match schedules::ensure_schedule_runtime_scaffold(&root) {
        Ok(schedule_registry) => {
            push_path_check(
                &mut checks,
                "schedule_registry",
                &schedule_registry,
                true,
                "schedule runtime registry present",
                "lifecycle",
                "loom onboard",
            );
            match schedules::schedule_overview(
                &root,
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_millis() as u64,
            ) {
                Ok(overview) => checks.push(Check {
                    level: if overview.enabled_count > 0 || overview.total_count == 0 {
                        "OK"
                    } else {
                        "WARN"
                    },
                    label: "schedule_runtime",
                    detail: format!(
                        "total={} enabled={} due={} runs_path={} schedules={}",
                        overview.total_count,
                        overview.enabled_count,
                        overview.due_count,
                        overview.runs_path.display(),
                        if overview.job_ids.is_empty() {
                            "(none)".to_string()
                        } else {
                            overview.job_ids.join(",")
                        }
                    ),
                    category: "lifecycle",
                    remediation: if overview.enabled_count > 0 || overview.total_count == 0 {
                        ""
                    } else {
                        "loom doctor"
                    },
                }),
                Err(error) => checks.push(Check {
                    level: "WARN",
                    label: "schedule_runtime",
                    detail: format!("schedule runtime unavailable: {}", error),
                    category: "lifecycle",
                    remediation: "loom doctor",
                }),
            }
        }
        Err(error) => checks.push(Check {
            level: "WARN",
            label: "schedule_registry",
            detail: format!("schedule runtime scaffold unavailable: {}", error),
            category: "lifecycle",
            remediation: "loom onboard",
        }),
    }
    match channels::ensure_channel_runtime_scaffold(&root) {
        Ok(channel_registry) => {
            push_path_check(
                &mut checks,
                "channel_registry",
                &channel_registry,
                true,
                "channel runtime registry present",
                "channel",
                "loom onboard",
            );
            match channels::channel_overview(&root) {
                Ok(overview) => checks.push(Check {
                    level: if overview.enabled_count > 0 || overview.total_count == 0 { "OK" } else { "WARN" },
                    label: "channel_runtime",
                    detail: format!(
                        "total={} enabled={} ingress={} active_deliveries={} archived_deliveries={} delivery_path={} inbox_path={} channels={}",
                        overview.total_count,
                        overview.enabled_count,
                        overview.ingress_count,
                        overview.active_delivery_count,
                        overview.archived_delivery_count,
                        overview.delivery_path.display(),
                        overview.inbox_path.display(),
                        if overview.channel_ids.is_empty() {
                            "(none)".to_string()
                        } else {
                            overview.channel_ids.join(",")
                        }
                    ),
                    category: "channel",
                    remediation: if overview.enabled_count > 0 || overview.total_count == 0 { "" } else { "loom onboard" },
                }),
                Err(error) => checks.push(Check {
                    level: "WARN",
                    label: "channel_runtime",
                    detail: format!("channel runtime unavailable: {}", error),
                    category: "channel",
                    remediation: "loom onboard",
                }),
            }
        }
        Err(error) => checks.push(Check {
            level: "WARN",
            label: "channel_registry",
            detail: format!("channel runtime scaffold unavailable: {}", error),
            category: "channel",
            remediation: "loom onboard",
        }),
    }
    match bindings::ensure_binding_runtime_scaffold(&root) {
        Ok(binding_registry) => {
            push_path_check(
                &mut checks,
                "binding_registry",
                &binding_registry,
                true,
                "binding runtime registry present",
                "channel",
                "loom onboard",
            );
            match bindings::binding_overview(&root) {
                Ok(overview) => checks.push(Check {
                    level: if overview.enabled_count > 0 || overview.total_count == 0 {
                        "OK"
                    } else {
                        "WARN"
                    },
                    label: "binding_runtime",
                    detail: format!(
                        "total={} enabled={} bindings={}",
                        overview.total_count,
                        overview.enabled_count,
                        if overview.binding_ids.is_empty() {
                            "(none)".to_string()
                        } else {
                            overview.binding_ids.join(",")
                        }
                    ),
                    category: "channel",
                    remediation: if overview.enabled_count > 0 || overview.total_count == 0 {
                        ""
                    } else {
                        "loom onboard"
                    },
                }),
                Err(error) => checks.push(Check {
                    level: "WARN",
                    label: "binding_runtime",
                    detail: format!("binding runtime unavailable: {}", error),
                    category: "channel",
                    remediation: "loom onboard",
                }),
            }
        }
        Err(error) => checks.push(Check {
            level: "WARN",
            label: "binding_registry",
            detail: format!("binding runtime scaffold unavailable: {}", error),
            category: "channel",
            remediation: "loom onboard",
        }),
    }
    match skills::ensure_skill_runtime_scaffold(&root) {
        Ok(skill_registry) => {
            push_path_check(
                &mut checks,
                "skill_registry",
                &skill_registry,
                true,
                "skill runtime registry present",
                "skills",
                "loom onboard",
            );
            match skills::skill_overview(&root) {
                Ok(overview) => checks.push(Check {
                    level: if overview.enabled_count > 0 || overview.total_count == 0 {
                        "OK"
                    } else {
                        "WARN"
                    },
                    label: "skill_runtime",
                    detail: format!(
                        "total={} enabled={} defaults={} imported={} installs_path={} skills={}",
                        overview.total_count,
                        overview.enabled_count,
                        overview.default_count,
                        overview.imported_count,
                        overview.installs_path.display(),
                        if overview.skill_ids.is_empty() {
                            "(none)".to_string()
                        } else {
                            overview.skill_ids.join(",")
                        }
                    ),
                    category: "skills",
                    remediation: if overview.enabled_count > 0 || overview.total_count == 0 {
                        ""
                    } else {
                        "loom onboard"
                    },
                }),
                Err(error) => checks.push(Check {
                    level: "WARN",
                    label: "skill_runtime",
                    detail: format!("skill runtime unavailable: {}", error),
                    category: "skills",
                    remediation: "loom onboard",
                }),
            }
        }
        Err(error) => checks.push(Check {
            level: "WARN",
            label: "skill_registry",
            detail: format!("skill runtime scaffold unavailable: {}", error),
            category: "skills",
            remediation: "loom onboard",
        }),
    }
    match session_provenance::ensure_session_provenance_scaffold(&root) {
        Ok(prov_registry) => {
            push_path_check(
                &mut checks,
                "session_provenance_registry",
                &prov_registry,
                false,
                "session provenance registry present",
                "session",
                "loom onboard",
            );
            match session_provenance::session_provenance_overview(&root) {
                Ok(overview) => checks.push(Check {
                    level: "OK",
                    label: "session_provenance",
                    detail: format!(
                        "total={} active={} archived={} sessions={}",
                        overview.total_count,
                        overview.active_count,
                        overview.archived_count,
                        if overview.session_keys.is_empty() {
                            "(none)".to_string()
                        } else {
                            overview.session_keys.join(",")
                        }
                    ),
                    category: "session",
                    remediation: "",
                }),
                Err(error) => checks.push(Check {
                    level: "WARN",
                    label: "session_provenance",
                    detail: format!("session provenance unavailable: {}", error),
                    category: "session",
                    remediation: "loom onboard",
                }),
            }
        }
        Err(error) => checks.push(Check {
            level: "WARN",
            label: "session_provenance_registry",
            detail: format!("session provenance scaffold unavailable: {}", error),
            category: "session",
            remediation: "loom onboard",
        }),
    }
    match skill_lifecycle::ensure_skill_lifecycle_scaffold(&root) {
        Ok(installs_dir) => {
            push_path_check(
                &mut checks,
                "skill_installs_dir",
                &installs_dir,
                false,
                "skill installs directory present",
                "skills",
                "loom onboard",
            );
            match skill_lifecycle::list_skill_installs(&root) {
                Ok(installs) => {
                    let enabled = installs.iter().filter(|r| r.enabled).count();
                    let locked = installs.iter().filter(|r| r.locked).count();
                    checks.push(Check {
                        level: "OK",
                        label: "skill_lifecycle",
                        detail: format!(
                            "installed={} enabled={} locked={}",
                            installs.len(),
                            enabled,
                            locked
                        ),
                        category: "skills",
                        remediation: "",
                    });
                }
                Err(error) => checks.push(Check {
                    level: "WARN",
                    label: "skill_lifecycle",
                    detail: format!("skill installs unavailable: {}", error),
                    category: "skills",
                    remediation: "loom onboard",
                }),
            }
        }
        Err(error) => checks.push(Check {
            level: "WARN",
            label: "skill_installs_dir",
            detail: format!("skill lifecycle scaffold unavailable: {}", error),
            category: "skills",
            remediation: "loom onboard",
        }),
    }
    match recurring_executor::ensure_recurring_executor_scaffold(&root) {
        Ok(runs_dir) => {
            push_path_check(
                &mut checks,
                "recurring_runs_dir",
                &runs_dir,
                false,
                "recurring runs directory present",
                "pipeline",
                "loom onboard",
            );
            match recurring_executor::list_recurring_runs(&root, 50, None) {
                Ok(runs) => {
                    let completed = runs.iter().filter(|r| r.status == "completed").count();
                    let failed = runs.iter().filter(|r| r.status == "failed").count();
                    checks.push(Check {
                        level: "OK",
                        label: "recurring_executor",
                        detail: format!(
                            "runs={} completed={} failed={}",
                            runs.len(),
                            completed,
                            failed
                        ),
                        category: "pipeline",
                        remediation: "",
                    });
                }
                Err(error) => checks.push(Check {
                    level: "WARN",
                    label: "recurring_executor",
                    detail: format!("recurring runs unavailable: {}", error),
                    category: "pipeline",
                    remediation: "loom doctor",
                }),
            }
        }
        Err(error) => checks.push(Check {
            level: "WARN",
            label: "recurring_runs_dir",
            detail: format!("recurring executor scaffold unavailable: {}", error),
            category: "pipeline",
            remediation: "loom onboard",
        }),
    }
    match pipeline::ensure_pipeline_scaffold(&root) {
        Ok(runs_dir) => {
            push_path_check(
                &mut checks,
                "pipeline_runs_dir",
                &runs_dir,
                false,
                "pipeline runs directory present",
                "pipeline",
                "loom onboard",
            );
            match pipeline::pipeline_overview(&root) {
                Ok(overview) => checks.push(Check {
                    level: "OK",
                    label: "pipeline",
                    detail: format!(
                        "total={} completed={} failed={}",
                        overview.total_count, overview.completed_count, overview.failed_count
                    ),
                    category: "pipeline",
                    remediation: "",
                }),
                Err(error) => checks.push(Check {
                    level: "WARN",
                    label: "pipeline",
                    detail: format!("pipeline overview unavailable: {}", error),
                    category: "pipeline",
                    remediation: "loom doctor",
                }),
            }
        }
        Err(error) => checks.push(Check {
            level: "WARN",
            label: "pipeline_runs_dir",
            detail: format!("pipeline scaffold unavailable: {}", error),
            category: "pipeline",
            remediation: "loom onboard",
        }),
    }
    let delivery_queue = delivery_queue_path(&root, &config);
    let delivery_required = config.handoff_mode != "off";
    push_path_check(
        &mut checks,
        "delivery_queue",
        &delivery_queue,
        delivery_required,
        if delivery_required {
            "delivery queue present"
        } else {
            "delivery queue configured"
        },
        "runtime",
        "loom onboard",
    );
    push_path_check(
        &mut checks,
        "python_workers",
        &root.join(&config.python_path),
        true,
        "python worker path present",
        "runtime",
        "loom onboard",
    );
    push_path_check(
        &mut checks,
        "typescript_workers",
        &root.join(&config.typescript_path),
        true,
        "typescript worker path present",
        "runtime",
        "loom onboard",
    );
    push_path_check(
        &mut checks,
        "wasm_modules",
        &root.join(&config.wasm_dir),
        true,
        "wasm module path present",
        "runtime",
        "loom onboard",
    );
    push_path_check(
        &mut checks,
        "capsule_manifest",
        &state_dir
            .join("capsules")
            .join(&config.org_id)
            .join("manifest.json"),
        true,
        "capsule manifest present",
        "runtime",
        "loom onboard",
    );
    let kernel_required = config.mode == "shadow" || config.mode == "standalone";
    let kernel_path = if config.kernel_path.is_empty() {
        None
    } else {
        Some(PathBuf::from(&config.kernel_path))
    };
    match (kernel_required, kernel_path) {
        (true, None) => checks.push(Check {
            level: "CRITICAL",
            label: "kernel_path",
            detail: "standalone/shadow mode requires --kernel-path".to_string(),
            category: "kernel",
            remediation: "loom onboard",
        }),
        (_, Some(path)) => {
            push_path_check(
                &mut checks,
                "kernel_path",
                &path,
                true,
                "kernel path present",
                "kernel",
                "loom onboard",
            );
            let registry = path.join("kernel/runtimes.json");
            push_path_check(
                &mut checks,
                "runtime_registry",
                &registry,
                true,
                "Meridian runtime registry available",
                "kernel",
                "loom onboard",
            );
            let agent_registry = path.join("kernel/agent_registry.py");
            push_path_check(
                &mut checks,
                "agent_registry",
                &agent_registry,
                true,
                "Meridian agent registry CLI available",
                "kernel",
                "loom onboard",
            );
        }
        (false, None) => checks.push(Check {
            level: "WARN",
            label: "kernel_path",
            detail: "embedded mode can run without kernel_path; contract inspection needs it"
                .to_string(),
            category: "kernel",
            remediation: "loom onboard",
        }),
    }

    let memory_root = state_dir.join("memory");
    push_path_check(
        &mut checks,
        "memory_repo",
        &memory_root,
        false,
        "memory repository present",
        "memory",
        "loom doctor --fix",
    );

    // Memory service check
    let memory_svc = memory_service::MemoryService::with_defaults(&root);
    match memory_svc.overview() {
        Ok(overview) => checks.push(Check {
            level: "OK",
            label: "memory_service",
            detail: format!(
                "agents={} entries={} bytes={} max_entries={} max_entry_bytes={} retention_days={}",
                overview.agent_count,
                overview.total_entries,
                overview.total_bytes,
                overview.policy.max_entries_per_agent,
                overview.policy.max_entry_bytes,
                overview.policy.retention_days,
            ),
            category: "memory",
            remediation: "",
        }),
        Err(_) => checks.push(Check {
            level: "OK",
            label: "memory_service",
            detail: "agents=0 entries=0 bytes=0".to_string(),
            category: "memory",
            remediation: "",
        }),
    }

    Ok(checks)
}

pub fn render_doctor_human(checks: &[Check]) -> String {
    let ok_count = checks.iter().filter(|c| c.level == "OK").count();
    let warn_count = checks.iter().filter(|c| c.level == "WARN").count();
    let crit_count = checks.iter().filter(|c| c.level == "CRITICAL").count();
    let overall = if crit_count > 0 {
        "blocked"
    } else if warn_count > 0 {
        "attention_needed"
    } else {
        "ready"
    };
    let next_step = if crit_count > 0 || warn_count > 0 {
        "loom doctor --root <path> --format human --fix"
    } else {
        "loom status --root <path>"
    };
    let mut out = format!(
        "Meridian Loom // DOCTOR\n=======================\nrelease:     official v0.1 local runtime\nboundary:    local-first service and proof surfaces are real; hosted replacement is not\n\nSummary\n=======\noverall:     {}\nchecks:      {} total · {} ok · {} warn · {} critical\nnext_step:   {}\n\n",
        overall,
        checks.len(),
        ok_count,
        warn_count,
        crit_count,
        next_step,
    );
    let mut categories: Vec<&str> = Vec::new();
    for check in checks {
        if !categories.contains(&check.category) {
            categories.push(check.category);
        }
    }
    for cat in &categories {
        let cat_checks: Vec<&Check> = checks.iter().filter(|c| c.category == *cat).collect();
        if cat_checks.is_empty() {
            continue;
        }
        out.push_str(&format!("[{}]\n", cat));
        for check in &cat_checks {
            out.push_str(&format!(
                "  [{:<8}] {:<30} {}\n",
                check.level, check.label, check.detail
            ));
            if !check.remediation.is_empty() && check.level != "OK" {
                out.push_str(&format!(
                    "             remediation: {}\n",
                    check.remediation
                ));
            }
        }
        out.push('\n');
    }
    out
}

pub fn render_doctor_json(checks: &[Check]) -> String {
    let parts: Vec<String> = checks
        .iter()
        .map(|check| {
            let mut s = format!(
                "{{\"level\":{},\"label\":{},\"detail\":{},\"category\":{}",
                json_string(check.level),
                json_string(check.label),
                json_string(&check.detail),
                json_string(check.category)
            );
            if !check.remediation.is_empty() {
                s.push_str(&format!(
                    ",\"remediation\":{}",
                    json_string(check.remediation)
                ));
            }
            s.push('}');
            s
        })
        .collect();
    format!("[{}]\n", parts.join(","))
}

pub fn health(root: &Path) -> LoomResult<(bool, String)> {
    let checks = doctor(root)?;
    let degraded = checks
        .iter()
        .any(|check| check.level == "CRITICAL" || check.level == "WARN");
    let config = read_config(root)?;
    let status = if degraded { "degraded" } else { "healthy" };
    let json = format!(
        "{{\n  \"status\": {},\n  \"mode\": {},\n  \"org_id\": {},\n  \"checks\": {},\n  \"experimental_hooks\": {}\n}}\n",
        json_string(status),
        json_string(&config.mode),
        json_string(&config.org_id),
        render_doctor_json(&checks).trim(),
        render_json_string_array(&EXPERIMENTAL_PRELIGHT_HOOKS)
    );
    Ok((!degraded, json))
}

pub fn render_health_human(healthy: bool, json: &str) -> String {
    let status = if healthy { "healthy" } else { "degraded" };
    let mode = extract_json_string(json, "\"mode\"").unwrap_or_else(|| "unknown".to_string());
    let org_id = extract_json_string(json, "\"org_id\"").unwrap_or_else(|| "unknown".to_string());
    let check_count = json.matches("\"label\"").count();
    let next_step = if healthy {
        "loom status --root <path>"
    } else {
        "loom doctor --root <path> --format human --fix"
    };
    format!(
        "Meridian Loom // HEALTH\n=======================\nrelease:     official v0.1 local runtime\nstatus:      {}\nmode:        {}\norg_id:      {}\nchecks:      {}\nsource:      doctor-derived health summary\nnext_step:   {}\n",
        status,
        mode,
        org_id,
        check_count,
        next_step,
    )
}

pub fn status_human(root: &Path) -> LoomResult<String> {
    let root = ensure_root(root)?;
    let config = read_config(&root)?;
    let state_dir = root.join(&config.state_dir);
    let delivery_queue = delivery_queue_path(&root, &config);
    let manifest = state_dir
        .join("capsules")
        .join(&config.org_id)
        .join("manifest.json");
    let provider_summary = provider_router::provider_plane_summary(Some(&root)).ok();
    let provider_block = provider_summary
        .map(|summary| {
            format!(
                "provider_cfg: {}\nprovider_src: {}\ndefault_prof: {}\nprofile_cnt: {}\ncap_routes:  {}\nagent_routes: {}\n",
                summary.profiles_path.display(),
                summary.source,
                summary.default_profile_name,
                summary.profile_count,
                summary.capability_route_count,
                summary.agent_route_count,
            )
        })
        .unwrap_or_else(|| {
            "provider_cfg: (unavailable)\nprovider_src: (unavailable)\ndefault_prof: (unavailable)\nprofile_cnt: 0\ncap_routes:  0\nagent_routes: 0\n".to_string()
        });
    Ok(format!(
        "Meridian Loom // STATUS\n=======================\nrelease:     official v0.1 local runtime\nboundary:    local root, queue, service, and proof artifacts are inspectable here\nmode:        {}\norg_id:      {}\nroot:        {}\nstate_dir:   {}\nrun_dir:     {}\nlog_dir:     {}\nartifact_dir:{}\nkernel_path: {}\ncapsule:     {}\nshadow:      {}\nqueue:       {}\n{}runtime:     local queue supervisor + service shell\ngovernance_surfaces: {}\n",
        config.mode,
        config.org_id,
        root.display(),
        state_dir.display(),
        root.join(&config.run_dir).display(),
        root.join(&config.log_dir).display(),
        root.join(&config.artifact_dir).display(),
        if config.kernel_path.is_empty() { "(not set)" } else { &config.kernel_path },
        manifest.display(),
        root.join(&config.artifact_dir).join("shadow/latest.json").display(),
        delivery_queue.display(),
        provider_block,
        EXPERIMENTAL_PRELIGHT_HOOKS.join(", ")
    ))
}

pub fn render_config_human(config: &Config, root: &Path) -> String {
    let delivery_queue = delivery_queue_path(root, config);
    let provider_summary = provider_router::provider_plane_summary(Some(root)).ok();
    let provider_block = provider_summary
        .map(|summary| format!(
            "provider_cfg: {}\nprovider_src: {}\ndefault_prof: {}\nprofile_cnt: {}\ncap_routes:  {}\nagent_routes:{}\n",
            summary.profiles_path.display(),
            summary.source,
            summary.default_profile_name,
            summary.profile_count,
            summary.capability_route_count,
            summary.agent_route_count,
        ))
        .unwrap_or_else(|| "provider_cfg: (unavailable)\nprovider_src: (unavailable)\ndefault_prof: (unavailable)\nprofile_cnt: 0\ncap_routes:  0\nagent_routes:0\n".to_string());
    format!(
        "Meridian Loom // CONFIG
=======================
root:         {}
mode:         {}
org_id:       {}
state_dir:    {}
run_dir:      {}
log_dir:      {}
artifact_dir: {}
capability_dir:{}
kernel_path:  {}
python_path:  {}
typescript:   {}
wasm_dir:     {}
service_http: {}
service_env:  {}
service_jobs: {}
service_poll: {}
service_iters:{}
log_level:    {}
log_format:   {}
log_max_b:    {}
log_max_f:    {}
handoff:      {}
delivery_q:   {} (resolved: {})
{}boundary:     local-first config; hosted runtime remains future work
",
        root.display(),
        config.mode,
        config.org_id,
        config.state_dir,
        config.run_dir,
        config.log_dir,
        config.artifact_dir,
        config.capabilities_dir,
        if config.kernel_path.is_empty() {
            "(not set)"
        } else {
            &config.kernel_path
        },
        config.python_path,
        config.typescript_path,
        config.wasm_dir,
        config.service_http_address,
        config.service_token_env,
        config.service_max_jobs,
        config.service_poll_seconds,
        if config.service_max_iterations == 0 {
            "unbounded".to_string()
        } else {
            config.service_max_iterations.to_string()
        },
        config.log_level,
        config.log_format,
        config.log_max_bytes,
        config.log_max_files,
        config.handoff_mode,
        config.delivery_queue,
        delivery_queue.display(),
        provider_block,
    )
}

pub fn contract_show(
    root: &Path,
    override_kernel_path: Option<&str>,
) -> LoomResult<ContractSnapshot> {
    let config = read_config(root)?;
    let kernel_path = resolve_kernel_path(root, override_kernel_path, Some(&config))?;
    let registry_path = kernel_path.join("kernel/runtimes.json");
    let contents = fs::read_to_string(&registry_path).map_err(io_err)?;
    let start = contents
        .find("\"loom_native\"")
        .ok_or_else(|| format!("loom_native not found in {}", registry_path.display()))?;
    let section = &contents[start..];

    let runtime_status = extract_json_string(section, "\"status\"")
        .ok_or_else(|| "runtime status not found".to_string())?;
    let notes = extract_json_string(section, "\"notes\"").unwrap_or_default();
    let hook_names = [
        "agent_identity",
        "action_envelope",
        "cost_attribution",
        "approval_hook",
        "audit_emission",
        "sanction_controls",
        "budget_gate",
    ];
    let hooks = hook_names
        .iter()
        .map(|hook| {
            let key = format!("\"{}\"", hook);
            let value =
                extract_json_literal(section, &key).unwrap_or_else(|| "unknown".to_string());
            ((*hook).to_string(), value)
        })
        .collect();

    let experimental_hooks = EXPERIMENTAL_PRELIGHT_HOOKS
        .iter()
        .map(|hook| {
            (
                (*hook).to_string(),
                "experimental_preflight_path".to_string(),
            )
        })
        .collect();

    Ok(ContractSnapshot {
        kernel_path,
        runtime_status,
        local_scaffold: "experimental_scaffold_present".to_string(),
        notes,
        hooks,
        experimental_hooks,
    })
}

pub fn render_contract_human(snapshot: &ContractSnapshot) -> String {
    let mut out = format!(
        "Meridian Loom // CONTRACT\n=========================\nkernel: {}\nstatus: {}\nlocal_scaffold: {}\n\nregistry_declared_hooks\n----------------------\n",
        snapshot.kernel_path.display(),
        snapshot.runtime_status,
        snapshot.local_scaffold,
    );
    for (hook, value) in &snapshot.hooks {
        out.push_str(&format!("{:<18} {}\n", hook, value));
    }
    out.push_str("\ngovernance_hook_paths\n---------------------\n");
    for (hook, value) in &snapshot.experimental_hooks {
        out.push_str(&format!("{:<18} {}\n", hook, value));
    }
    out.push_str(&format!("\nnotes: {}\n", snapshot.notes));
    out
}

pub fn render_contract_json(snapshot: &ContractSnapshot) -> String {
    let hooks = snapshot
        .hooks
        .iter()
        .map(|(hook, value)| format!("    {}: {}", json_string(hook), json_string(value)))
        .collect::<Vec<_>>()
        .join(",\n");
    let experimental = snapshot
        .experimental_hooks
        .iter()
        .map(|(hook, value)| format!("    {}: {}", json_string(hook), json_string(value)))
        .collect::<Vec<_>>()
        .join(",\n");
    format!(
        "{{\n  \"kernel_path\": {},\n  \"status\": {},\n  \"local_scaffold\": {},\n  \"hooks\": {{\n{}\n  }},\n  \"experimental_hooks\": {{\n{}\n  }},\n  \"notes\": {}\n}}\n",
        json_string(&snapshot.kernel_path.display().to_string()),
        json_string(&snapshot.runtime_status),
        json_string(&snapshot.local_scaffold),
        hooks,
        experimental,
        json_string(&snapshot.notes)
    )
}

pub fn contract_verify(
    root: &Path,
    override_kernel_path: Option<&str>,
    agent_ref: &str,
    org_hint: Option<&str>,
) -> LoomResult<ContractVerifyResult> {
    let config = read_config(root)?;
    let kernel_path = resolve_kernel_path(root, override_kernel_path, Some(&config))?;
    let evidence_dir = root.join("artifacts").join("contract");
    fs::create_dir_all(&evidence_dir).map_err(io_err)?;

    let org_id = org_hint.unwrap_or(&config.org_id);
    let mut hooks: Vec<HookVerification> = Vec::new();

    // Hook 1: agent_identity
    let identity_result =
        resolve_agent_identity(root, override_kernel_path, agent_ref, Some(org_id));
    let identity = match &identity_result {
        Ok(id) => {
            let artifact = evidence_dir.join("agent_identity.json");
            let body = format!(
                "{{\n  \"agent_id\": {},\n  \"agent_name\": {},\n  \"org_id\": {},\n  \"role\": {},\n  \"restrictions\": [{}],\n  \"sanction_decision\": {},\n  \"runtime_id\": {},\n  \"source\": {}\n}}\n",
                json_string(&id.agent_id), json_string(&id.agent_name),
                json_string(&id.org_id), json_string(&id.role),
                id.restrictions.iter().map(|r| json_string(r)).collect::<Vec<_>>().join(", "),
                json_string(&id.sanction_decision), json_string(&id.runtime_id),
                json_string(&id.source),
            );
            fs::write(&artifact, &body).map_err(io_err)?;
            hooks.push(HookVerification {
                hook_name: "agent_identity".to_string(),
                passed: true,
                detail: format!("resolved {}", id.agent_id),
                artifact_path: Some(artifact),
            });
            Some(id.clone())
        }
        Err(err) => {
            hooks.push(HookVerification {
                hook_name: "agent_identity".to_string(),
                passed: false,
                detail: err.clone(),
                artifact_path: None,
            });
            None
        }
    };

    // Hook 2: action_envelope
    let envelope = if let Some(ref id) = identity {
        let envelope = ActionEnvelope {
            agent_id: id.agent_id.clone(),
            agent_name: id.agent_name.clone(),
            org_id: id.org_id.clone(),
            runtime_id: id.runtime_id.clone(),
            runtime_label: id.runtime_label.clone(),
            action_type: "contract_verify".to_string(),
            resource: "self_test".to_string(),
            capability_name: String::new(),
            payload_json: String::new(),
            estimated_cost_usd: 0.01,
            run_id: String::new(),
            session_id: String::new(),
            source: "loom_contract_verify".to_string(),
        };
        let hash = envelope_input_hash(&envelope);
        let artifact = evidence_dir.join("action_envelope.json");
        let body = format!(
            "{{\n  \"agent_id\": {},\n  \"org_id\": {},\n  \"action_type\": {},\n  \"resource\": {},\n  \"estimated_cost_usd\": {:.6},\n  \"input_hash\": {},\n  \"source\": {}\n}}\n",
            json_string(&envelope.agent_id), json_string(&envelope.org_id),
            json_string(&envelope.action_type), json_string(&envelope.resource),
            envelope.estimated_cost_usd, json_string(&hash),
            json_string(&envelope.source),
        );
        fs::write(&artifact, &body).map_err(io_err)?;
        hooks.push(HookVerification {
            hook_name: "action_envelope".to_string(),
            passed: true,
            detail: format!("hash={}", hash),
            artifact_path: Some(artifact),
        });
        Some(envelope)
    } else {
        hooks.push(HookVerification {
            hook_name: "action_envelope".to_string(),
            passed: false,
            detail: "skipped: no identity".to_string(),
            artifact_path: None,
        });
        None
    };

    // Hook 3: cost_attribution
    if let Some(ref env) = envelope {
        let artifact = evidence_dir.join("cost_attribution.json");
        let has_budget = identity
            .as_ref()
            .and_then(|id| id.max_per_run_usd)
            .unwrap_or(0.0);
        let body = format!(
            "{{\n  \"estimated_cost_usd\": {:.6},\n  \"agent_budget_limit_usd\": {:.6},\n  \"within_limit\": {},\n  \"source\": \"loom_contract_verify\"\n}}\n",
            env.estimated_cost_usd, has_budget,
            if has_budget <= 0.0 || env.estimated_cost_usd <= has_budget { "true" } else { "false" },
        );
        fs::write(&artifact, &body).map_err(io_err)?;
        hooks.push(HookVerification {
            hook_name: "cost_attribution".to_string(),
            passed: true,
            detail: format!("cost={:.4} limit={:.2}", env.estimated_cost_usd, has_budget),
            artifact_path: Some(artifact),
        });
    } else {
        hooks.push(HookVerification {
            hook_name: "cost_attribution".to_string(),
            passed: false,
            detail: "skipped: no envelope".to_string(),
            artifact_path: None,
        });
    }

    // Hook 4: approval_hook (via reference gates)
    let reference = if let (Some(ref id), Some(ref env)) = (&identity, &envelope) {
        match evaluate_reference_gates(root, override_kernel_path, id, env) {
            Ok(gate) => {
                let artifact = evidence_dir.join("approval_hook.json");
                let body = format!(
                    "{{\n  \"allowed\": {},\n  \"stage\": {},\n  \"reason\": {},\n  \"approval_gate_decision\": {},\n  \"source\": {}\n}}\n",
                    gate.allowed, json_string(&gate.stage), json_string(&gate.reason),
                    json_string(&gate.approval_gate_decision), json_string(&gate.source),
                );
                fs::write(&artifact, &body).map_err(io_err)?;
                hooks.push(HookVerification {
                    hook_name: "approval_hook".to_string(),
                    passed: true,
                    detail: format!("decision={}", gate.approval_gate_decision),
                    artifact_path: Some(artifact),
                });
                Some(gate)
            }
            Err(err) => {
                hooks.push(HookVerification {
                    hook_name: "approval_hook".to_string(),
                    passed: false,
                    detail: err,
                    artifact_path: None,
                });
                None
            }
        }
    } else {
        hooks.push(HookVerification {
            hook_name: "approval_hook".to_string(),
            passed: false,
            detail: "skipped: no identity or envelope".to_string(),
            artifact_path: None,
        });
        None
    };

    // Hook 5: audit_emission
    if let Some(ref env) = envelope {
        let audit_dir = root.join("artifacts").join("audit");
        fs::create_dir_all(&audit_dir).map_err(io_err)?;
        let audit_verify_log = audit_dir.join("contract_verify.jsonl");
        let input_hash = envelope_input_hash(env);
        let ts = timestamp_now();
        let entry = format!(
            "{{\"id\":{},\"timestamp\":{},\"org_id\":{},\"agent_id\":{},\"actor_type\":\"agent\",\"action\":{},\"resource\":{},\"outcome\":\"contract_verify\",\"details\":{{\"source\":\"loom_contract_verify\",\"input_hash\":{},\"estimated_cost_usd\":{:.6}}},\"policy_ref\":\"contract_verify\"}}\n",
            json_string(&format!("cv_{}", &input_hash[..8.min(input_hash.len())])),
            json_string(&ts), json_string(&env.org_id), json_string(&env.agent_id),
            json_string(&env.action_type), json_string(&env.resource),
            json_string(&input_hash), env.estimated_cost_usd,
        );
        fs::write(&audit_verify_log, &entry).map_err(io_err)?;
        // Verify the file was written and is readable
        let readback = fs::read_to_string(&audit_verify_log).map_err(io_err)?;
        if readback.contains("contract_verify") {
            let artifact = evidence_dir.join("audit_emission.json");
            fs::write(&artifact, format!(
                "{{\n  \"audit_log_path\": {},\n  \"entry_written\": true,\n  \"readback_verified\": true,\n  \"source\": \"loom_contract_verify\"\n}}\n",
                json_string(&audit_verify_log.display().to_string()),
            )).map_err(io_err)?;
            hooks.push(HookVerification {
                hook_name: "audit_emission".to_string(),
                passed: true,
                detail: format!("log={}", audit_verify_log.display()),
                artifact_path: Some(artifact),
            });
        } else {
            hooks.push(HookVerification {
                hook_name: "audit_emission".to_string(),
                passed: false,
                detail: "audit entry not readable after write".to_string(),
                artifact_path: None,
            });
        }
    } else {
        hooks.push(HookVerification {
            hook_name: "audit_emission".to_string(),
            passed: false,
            detail: "skipped: no envelope".to_string(),
            artifact_path: None,
        });
    }

    // Hook 6: sanction_controls
    if let Some(ref id) = identity {
        let preview = preview_local_sanction_controls(id);
        let ref_sanction = reference
            .as_ref()
            .map(|r| r.sanction_gate_decision.as_str())
            .unwrap_or("not_evaluated");
        let artifact = evidence_dir.join("sanction_controls.json");
        let body = format!(
            "{{\n  \"local_allowed\": {},\n  \"local_decision\": {},\n  \"local_reason\": {},\n  \"reference_sanction_decision\": {},\n  \"source\": \"loom_contract_verify\"\n}}\n",
            preview.allowed, json_string(&preview.decision),
            json_string(&preview.reason), json_string(ref_sanction),
        );
        fs::write(&artifact, &body).map_err(io_err)?;
        hooks.push(HookVerification {
            hook_name: "sanction_controls".to_string(),
            passed: true,
            detail: format!("local={} ref={}", preview.decision, ref_sanction),
            artifact_path: Some(artifact),
        });
    } else {
        hooks.push(HookVerification {
            hook_name: "sanction_controls".to_string(),
            passed: false,
            detail: "skipped: no identity".to_string(),
            artifact_path: None,
        });
    }

    // Hook 7: budget_gate
    if let Some(ref gate) = reference {
        let artifact = evidence_dir.join("budget_gate.json");
        let body = format!(
            "{{\n  \"budget_gate_decision\": {},\n  \"overall_allowed\": {},\n  \"stage\": {},\n  \"source\": \"loom_contract_verify\"\n}}\n",
            json_string(&gate.budget_gate_decision), gate.allowed,
            json_string(&gate.stage),
        );
        fs::write(&artifact, &body).map_err(io_err)?;
        hooks.push(HookVerification {
            hook_name: "budget_gate".to_string(),
            passed: true,
            detail: format!("decision={}", gate.budget_gate_decision),
            artifact_path: Some(artifact),
        });
    } else {
        hooks.push(HookVerification {
            hook_name: "budget_gate".to_string(),
            passed: false,
            detail: "skipped: reference gates not reached".to_string(),
            artifact_path: None,
        });
    }

    let passed = hooks.iter().filter(|h| h.passed).count();
    let total = hooks.len();

    Ok(ContractVerifyResult {
        kernel_path,
        hooks,
        passed,
        total,
    })
}

pub fn render_contract_verify_human(result: &ContractVerifyResult) -> String {
    let mut out = format!(
        "Meridian Loom // CONTRACT VERIFY\n================================\nkernel:  {}\nresult:  {}/{} hooks proven\n\n",
        result.kernel_path.display(), result.passed, result.total,
    );
    out.push_str(&format!(
        "{:<20} {:<6} {:<40} {}\n",
        "hook", "status", "detail", "artifact"
    ));
    out.push_str(&format!("{}\n", "-".repeat(100)));
    for hook in &result.hooks {
        let status = if hook.passed { "pass" } else { "FAIL" };
        let artifact = hook
            .artifact_path
            .as_ref()
            .map(|p| p.display().to_string())
            .unwrap_or_else(|| "-".to_string());
        out.push_str(&format!(
            "{:<20} {:<6} {:<40} {}\n",
            hook.hook_name, status, hook.detail, artifact
        ));
    }
    if result.passed == result.total {
        out.push_str(&format!("\nall {} hooks proven\n", result.total));
    } else {
        out.push_str(&format!(
            "\n{} of {} hooks failed\n",
            result.total - result.passed,
            result.total
        ));
    }
    out
}

pub fn render_contract_verify_json(result: &ContractVerifyResult) -> String {
    let hooks_json = result
        .hooks
        .iter()
        .map(|h| {
            let artifact = h
                .artifact_path
                .as_ref()
                .map(|p| json_string(&p.display().to_string()))
                .unwrap_or_else(|| "null".to_string());
            format!(
                "    {{\n      \"hook\": {},\n      \"passed\": {},\n      \"detail\": {},\n      \"artifact\": {}\n    }}",
                json_string(&h.hook_name), h.passed,
                json_string(&h.detail), artifact,
            )
        })
        .collect::<Vec<_>>()
        .join(",\n");
    format!(
        "{{\n  \"kernel_path\": {},\n  \"passed\": {},\n  \"total\": {},\n  \"hooks\": [\n{}\n  ]\n}}\n",
        json_string(&result.kernel_path.display().to_string()),
        result.passed, result.total, hooks_json,
    )
}

fn timestamp_now() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    format!("{}", secs)
}

pub fn resolve_agent_identity(
    root: &Path,
    override_kernel_path: Option<&str>,
    agent_ref: &str,
    org_hint: Option<&str>,
) -> LoomResult<AgentIdentityResolution> {
    let config = read_config(root)?;
    let kernel_path = resolve_kernel_path(root, override_kernel_path, Some(&config))?;
    let script = kernel_path.join("kernel/agent_registry.py");
    if !script.exists() {
        return Err(format!("missing {}", script.display()));
    }

    let normalized_agent = agent_ref.trim();
    if normalized_agent.is_empty() {
        return Err("agent_ref is required".to_string());
    }

    let explicit_org_hint = org_hint
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty());
    let stdout =
        run_agent_registry_lookup(&script, normalized_agent, explicit_org_hint.as_deref())?;

    let runtime_binding = find_named_object(&stdout, "\"runtime_binding\"")
        .ok_or_else(|| "runtime_binding missing from agent record".to_string())?;
    let agent_id =
        extract_json_string(&stdout, "\"id\"").ok_or_else(|| "agent id missing".to_string())?;
    let agent_name =
        extract_json_string(&stdout, "\"name\"").ok_or_else(|| "agent name missing".to_string())?;
    let org_id =
        extract_json_string(&stdout, "\"org_id\"").ok_or_else(|| "org_id missing".to_string())?;
    let role = extract_json_string(&stdout, "\"role\"").unwrap_or_default();
    let economy_key = extract_json_string(&stdout, "\"economy_key\"").unwrap_or_default();
    let approval_required = extract_json_bool(&stdout, "\"approval_required\"").unwrap_or(false);
    let max_per_run_usd = find_named_object(&stdout, "\"budget\"")
        .and_then(|budget| extract_json_f64(&budget, "\"max_per_run_usd\""));
    let snapshot_restrictions = extract_json_string_array(&stdout, "\"restrictions\"");
    let snapshot_sanction_decision = extract_json_string(&stdout, "\"sanction_decision\"");
    let restriction_lookup = if economy_key.is_empty() {
        agent_id.as_str()
    } else {
        economy_key.as_str()
    };
    let (restrictions, sanction_decision) = if snapshot_restrictions.is_empty() {
        query_agent_restrictions(&kernel_path, restriction_lookup, Some(&org_id))
    } else {
        let decision = snapshot_sanction_decision
            .unwrap_or_else(|| derive_sanction_decision(&snapshot_restrictions).to_string());
        (snapshot_restrictions, decision)
    };

    Ok(AgentIdentityResolution {
        agent_id,
        agent_name,
        org_id,
        role,
        economy_key,
        approval_required,
        max_per_run_usd,
        restrictions,
        sanction_decision,
        runtime_id: extract_json_string(&runtime_binding, "\"runtime_id\"")
            .ok_or_else(|| "runtime_id missing".to_string())?,
        runtime_label: extract_json_string(&runtime_binding, "\"runtime_label\"")
            .unwrap_or_default(),
        bound_org_id: extract_json_string(&runtime_binding, "\"bound_org_id\"").unwrap_or_default(),
        boundary_name: extract_json_string(&runtime_binding, "\"boundary_name\"")
            .unwrap_or_default(),
        identity_model: extract_json_string(&runtime_binding, "\"identity_model\"")
            .unwrap_or_default(),
        runtime_registered: extract_json_bool(&runtime_binding, "\"runtime_registered\"")
            .unwrap_or(true),
        registration_status: extract_json_string(&runtime_binding, "\"registration_status\"")
            .unwrap_or_else(|| "registered".to_string()),
        source: "kernel_agent_registry".to_string(),
    })
}

fn run_agent_registry_lookup(
    script: &Path,
    agent_ref: &str,
    org_hint: Option<&str>,
) -> LoomResult<String> {
    let mut cmd = Command::new("python3");
    cmd.arg(script).arg("get").arg("--agent_id").arg(agent_ref);
    if let Some(org_id) = org_hint {
        cmd.arg("--org_id").arg(org_id);
    }

    let output = cmd.output().map_err(io_err)?;
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    if !output.status.success() {
        return Err(format!(
            "agent_registry lookup failed: {}",
            if stderr.is_empty() { stdout } else { stderr }
        ));
    }
    if stdout.starts_with("Not found:") {
        return Err(stdout);
    }
    if !stdout.starts_with('{') {
        return Err(format!(
            "agent_registry returned non-JSON output: {}",
            stdout.lines().next().unwrap_or_default()
        ));
    }
    Ok(stdout)
}

fn query_agent_restrictions(
    kernel_path: &Path,
    agent_lookup: &str,
    org_hint: Option<&str>,
) -> (Vec<String>, String) {
    let kernel_dir = kernel_path.join("kernel");
    let script = r#"import sys
kernel_dir = sys.argv[1]
agent_id = sys.argv[2]
org_id = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None
sys.path.insert(0, kernel_dir)
from court import get_restrictions
for item in get_restrictions(agent_id, org_id=org_id) or []:
    print(item)
"#;

    let mut cmd = Command::new("python3");
    cmd.arg("-c").arg(script).arg(&kernel_dir).arg(agent_lookup);
    if let Some(org_id) = org_hint {
        cmd.arg(org_id);
    }

    match cmd.output() {
        Ok(output) if output.status.success() => {
            let stdout = String::from_utf8_lossy(&output.stdout);
            let restrictions = stdout
                .lines()
                .map(str::trim)
                .filter(|line| !line.is_empty())
                .map(|line| line.to_string())
                .collect::<Vec<_>>();
            let decision = derive_sanction_decision(&restrictions);
            (restrictions, decision.to_string())
        }
        _ => (Vec::new(), "unknown".to_string()),
    }
}

fn derive_sanction_decision(restrictions: &[String]) -> &'static str {
    if restrictions.is_empty() {
        "clear"
    } else if restrictions
        .iter()
        .any(|value| value == "execute" || value == "remediation_only")
    {
        "restricted_execute"
    } else {
        "restricted"
    }
}

pub fn render_identity_human(identity: &AgentIdentityResolution) -> String {
    format!(
        "Meridian Loom // AGENT IDENTITY\n================================\nagent_id:            {}\nagent_name:          {}\norg_id:              {}\nrole:                {}\neconomy_key:         {}\napproval_required:   {}\nmax_per_run_usd:     {}\nrestrictions:        {}\nsanction_decision:   {}\nruntime_id:          {}\nruntime_label:       {}\nbound_org_id:        {}\nboundary_name:       {}\nidentity_model:      {}\nruntime_registered:  {}\nregistration_status: {}\nsource:              {}\n",
        identity.agent_id,
        identity.agent_name,
        identity.org_id,
        identity.role,
        if identity.economy_key.is_empty() { "(none)" } else { &identity.economy_key },
        identity.approval_required,
        identity
            .max_per_run_usd
            .map(|value| format!("{:.4}", value))
            .unwrap_or_else(|| "(unknown)".to_string()),
        if identity.restrictions.is_empty() {
            "(none)".to_string()
        } else {
            identity.restrictions.join(", ")
        },
        identity.sanction_decision,
        identity.runtime_id,
        identity.runtime_label,
        identity.bound_org_id,
        identity.boundary_name,
        identity.identity_model,
        identity.runtime_registered,
        identity.registration_status,
        identity.source,
    )
}

pub fn render_identity_json(identity: &AgentIdentityResolution) -> String {
    format!(
        "{{\n  \"agent_id\": {},\n  \"agent_name\": {},\n  \"org_id\": {},\n  \"role\": {},\n  \"economy_key\": {},\n  \"approval_required\": {},\n  \"max_per_run_usd\": {},\n  \"restrictions\": {},\n  \"sanction_decision\": {},\n  \"runtime_id\": {},\n  \"runtime_label\": {},\n  \"bound_org_id\": {},\n  \"boundary_name\": {},\n  \"identity_model\": {},\n  \"runtime_registered\": {},\n  \"registration_status\": {},\n  \"source\": {}\n}}\n",
        json_string(&identity.agent_id),
        json_string(&identity.agent_name),
        json_string(&identity.org_id),
        json_string(&identity.role),
        json_string(&identity.economy_key),
        if identity.approval_required { "true" } else { "false" },
        identity
            .max_per_run_usd
            .map(|value| format!("{:.6}", value))
            .unwrap_or_else(|| "null".to_string()),
        render_json_string_array(&identity.restrictions),
        json_string(&identity.sanction_decision),
        json_string(&identity.runtime_id),
        json_string(&identity.runtime_label),
        json_string(&identity.bound_org_id),
        json_string(&identity.boundary_name),
        json_string(&identity.identity_model),
        if identity.runtime_registered { "true" } else { "false" },
        json_string(&identity.registration_status),
        json_string(&identity.source),
    )
}

pub fn build_action_envelope(
    root: &Path,
    override_kernel_path: Option<&str>,
    agent_ref: &str,
    org_hint: Option<&str>,
    action_type: &str,
    resource: &str,
    estimated_cost_usd: f64,
    run_id: Option<&str>,
    session_id: Option<&str>,
) -> LoomResult<ActionEnvelope> {
    build_action_envelope_with_options(
        root,
        override_kernel_path,
        agent_ref,
        org_hint,
        action_type,
        resource,
        estimated_cost_usd,
        run_id,
        session_id,
        None,
        None,
    )
}

pub fn build_action_envelope_with_options(
    root: &Path,
    override_kernel_path: Option<&str>,
    agent_ref: &str,
    org_hint: Option<&str>,
    action_type: &str,
    resource: &str,
    estimated_cost_usd: f64,
    run_id: Option<&str>,
    session_id: Option<&str>,
    capability_name: Option<&str>,
    payload_json: Option<&str>,
) -> LoomResult<ActionEnvelope> {
    let action_type = action_type.trim();
    let resource = resource.trim();
    if action_type.is_empty() {
        return Err("action_type is required".to_string());
    }
    if resource.is_empty() {
        return Err("resource is required".to_string());
    }
    if estimated_cost_usd < 0.0 {
        return Err("estimated_cost_usd must be non-negative".to_string());
    }

    let identity = resolve_agent_identity(root, override_kernel_path, agent_ref, org_hint)?;
    Ok(ActionEnvelope {
        agent_id: identity.agent_id,
        agent_name: identity.agent_name,
        org_id: identity.org_id,
        runtime_id: identity.runtime_id,
        runtime_label: identity.runtime_label,
        action_type: action_type.to_string(),
        resource: resource.to_string(),
        capability_name: capability_name.unwrap_or("").trim().to_string(),
        payload_json: payload_json.unwrap_or("").trim().to_string(),
        estimated_cost_usd,
        run_id: run_id.unwrap_or("").trim().to_string(),
        session_id: session_id.unwrap_or("").trim().to_string(),
        source: "loom_experimental_preflight".to_string(),
    })
}

pub fn preview_local_sanction_controls(identity: &AgentIdentityResolution) -> LocalSanctionPreview {
    if identity
        .restrictions
        .iter()
        .any(|value| value == "execute" || value == "remediation_only")
    {
        return LocalSanctionPreview {
            allowed: false,
            decision: "deny".to_string(),
            reason: format!("Agent {} is restricted from execute", identity.agent_id),
        };
    }

    LocalSanctionPreview {
        allowed: true,
        decision: "allow".to_string(),
        reason: "no execute restriction".to_string(),
    }
}

/// Hard enforcement of sanction controls. Returns `hard_deny` for restricted agents.
/// This is the production enforcement path — no preview, no soft-fail.
pub fn enforce_sanction_controls(identity: &AgentIdentityResolution) -> SanctionEnforcement {
    if identity
        .restrictions
        .iter()
        .any(|value| value == "execute" || value == "remediation_only")
    {
        return SanctionEnforcement {
            allowed: false,
            decision: "hard_deny".to_string(),
            reason: format!(
                "sanction enforcement: agent {} is restricted (restrictions: {:?})",
                identity.agent_id, identity.restrictions
            ),
        };
    }

    SanctionEnforcement {
        allowed: true,
        decision: "allow".to_string(),
        reason: "no execute restriction".to_string(),
    }
}

pub fn evaluate_reference_gates(
    root: &Path,
    override_kernel_path: Option<&str>,
    identity: &AgentIdentityResolution,
    envelope: &ActionEnvelope,
) -> LoomResult<ReferenceGateCheck> {
    let config = read_config(root)?;
    let kernel_path = resolve_kernel_path(root, override_kernel_path, Some(&config))?;
    let kernel_dir = kernel_path.join("kernel");
    // Legacy Execution Parity Adapter: Used by Meridian to benchmark and audit legacy un-governed runtimes against the Meridian constitutional ledger.
    let script = r#"import importlib, json, os, sys
kernel_dir = sys.argv[1]
org_id = sys.argv[2]
envelope = json.loads(sys.argv[3])
sys.path.insert(0, kernel_dir)
module = None
for module_name, module_path in (
    ("adapters.meridian_compatible", os.path.join(kernel_dir, "adapters", "meridian_compatible.py")),
    ("adapters.legacy_v1_compatible", os.path.join(kernel_dir, "adapters", "legacy_v1_compatible.py")),
):
    if os.path.exists(module_path):
        module = importlib.import_module(module_name)
        break
if module is None:
    raise FileNotFoundError(
        "no reference adapter found in kernel/adapters (tried meridian_compatible.py, legacy_v1_compatible.py)"
    )
print(json.dumps(module.pre_action_check(org_id, envelope)))
"#;

    let reference_agent = if identity.economy_key.trim().is_empty() {
        envelope.agent_id.clone()
    } else {
        identity.economy_key.clone()
    };
    let reference_envelope = ActionEnvelope {
        agent_id: reference_agent,
        agent_name: envelope.agent_name.clone(),
        org_id: envelope.org_id.clone(),
        runtime_id: envelope.runtime_id.clone(),
        runtime_label: envelope.runtime_label.clone(),
        action_type: envelope.action_type.clone(),
        resource: envelope.resource.clone(),
        capability_name: envelope.capability_name.clone(),
        payload_json: envelope.payload_json.clone(),
        estimated_cost_usd: envelope.estimated_cost_usd,
        run_id: envelope.run_id.clone(),
        session_id: envelope.session_id.clone(),
        source: envelope.source.clone(),
    };
    let envelope_json = render_envelope_json(&reference_envelope);
    let output = Command::new("python3")
        .arg("-c")
        .arg(script)
        .arg(&kernel_dir)
        .arg(&envelope.org_id)
        .arg(envelope_json)
        .output()
        .map_err(io_err)?;
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    if !output.status.success() {
        return Err(format!(
            "reference adapter pre_action_check failed: {}",
            if stderr.is_empty() { stdout } else { stderr }
        ));
    }
    if !stdout.starts_with('{') {
        return Err(format!(
            "reference adapter returned non-JSON output: {}",
            stdout.lines().next().unwrap_or_default()
        ));
    }

    let allowed = extract_json_bool(&stdout, "\"allowed\"")
        .ok_or_else(|| "reference adapter response missing allowed".to_string())?;
    let stage = extract_json_string(&stdout, "\"stage\"").unwrap_or_else(|| {
        if allowed {
            "ok".to_string()
        } else {
            "unknown".to_string()
        }
    });
    let reason = extract_json_string(&stdout, "\"reason\"").unwrap_or_default();
    let restrictions = extract_json_string_array(&stdout, "\"restrictions\"");
    let sanction_gate_decision = if stage == "sanction_controls" {
        "deny".to_string()
    } else {
        "allow".to_string()
    };
    let approval_gate_decision = match stage.as_str() {
        "sanction_controls" => "not_reached".to_string(),
        "approval_hook" => "deny".to_string(),
        _ => "allow".to_string(),
    };
    let budget_gate_decision = match stage.as_str() {
        "sanction_controls" | "approval_hook" => "not_reached".to_string(),
        "budget_gate" => "deny".to_string(),
        _ if envelope.estimated_cost_usd <= 0.0 => "skipped_zero_cost".to_string(),
        _ => "allow".to_string(),
    };

    Ok(ReferenceGateCheck {
        allowed,
        stage,
        reason,
        restrictions,
        sanction_gate_decision,
        approval_gate_decision,
        budget_gate_decision,
        source: "kernel_reference_adapter_read_only".to_string(),
    })
}

pub fn envelope_input_hash(envelope: &ActionEnvelope) -> String {
    let raw = format!(
        "{}|{}|{}|{}|{}|{}|{:.6}|{}|{}",
        envelope.agent_id,
        envelope.org_id,
        envelope.runtime_id,
        envelope.action_type,
        envelope.capability_name,
        envelope.payload_json,
        envelope.estimated_cost_usd,
        envelope.resource,
        envelope.source,
    );
    format!("{:016x}", fnv1a64(raw.as_bytes()))
}

pub fn render_envelope_human(envelope: &ActionEnvelope) -> String {
    format!(
        "Meridian Loom // ACTION ENVELOPE\n=================================\nagent_id:            {}\nagent_name:          {}\norg_id:              {}\nruntime_id:          {}\nruntime_label:       {}\naction_type:         {}\nresource:            {}\ncapability_name:     {}\npayload_json:        {}\nestimated_cost_usd:  {:.4}\nrun_id:              {}\nsession_id:          {}\nsource:              {}\ninput_hash:          {}\n",
        envelope.agent_id,
        envelope.agent_name,
        envelope.org_id,
        envelope.runtime_id,
        envelope.runtime_label,
        envelope.action_type,
        envelope.resource,
        if envelope.capability_name.is_empty() { "(none)" } else { &envelope.capability_name },
        if envelope.payload_json.is_empty() { "(none)" } else { &envelope.payload_json },
        envelope.estimated_cost_usd,
        if envelope.run_id.is_empty() { "(none)" } else { &envelope.run_id },
        if envelope.session_id.is_empty() { "(none)" } else { &envelope.session_id },
        envelope.source,
        envelope_input_hash(envelope),
    )
}

pub fn render_envelope_json(envelope: &ActionEnvelope) -> String {
    format!(
        "{{\n  \"agent_id\": {},\n  \"agent_name\": {},\n  \"org_id\": {},\n  \"runtime_id\": {},\n  \"runtime_label\": {},\n  \"action_type\": {},\n  \"resource\": {},\n  \"capability_name\": {},\n  \"payload_json\": {},\n  \"estimated_cost_usd\": {:.6},\n  \"run_id\": {},\n  \"session_id\": {},\n  \"source\": {},\n  \"input_hash\": {}\n}}\n",
        json_string(&envelope.agent_id),
        json_string(&envelope.agent_name),
        json_string(&envelope.org_id),
        json_string(&envelope.runtime_id),
        json_string(&envelope.runtime_label),
        json_string(&envelope.action_type),
        json_string(&envelope.resource),
        json_string(&envelope.capability_name),
        json_string(&envelope.payload_json),
        envelope.estimated_cost_usd,
        json_string(&envelope.run_id),
        json_string(&envelope.session_id),
        json_string(&envelope.source),
        json_string(&envelope_input_hash(envelope)),
    )
}

pub fn capsule_inspect(root: &Path) -> LoomResult<CapsuleInspection> {
    let config = read_config(root)?;
    let state_dir = root.join(&config.state_dir);
    let capsule_dir = state_dir.join("capsules").join(&config.org_id);
    let manifest_path = capsule_dir.join("manifest.json");
    let mut files: Vec<String> = fs::read_dir(&capsule_dir)
        .map_err(io_err)?
        .map(|entry| {
            let entry = entry.map_err(io_err)?;
            Ok(entry
                .file_name()
                .into_string()
                .unwrap_or_else(|os_str| os_str.to_string_lossy().into_owned()))
        })
        .collect::<LoomResult<Vec<String>>>()?;
    files.sort();
    Ok(CapsuleInspection {
        org_id: config.org_id,
        manifest_path,
        state_dir,
        files,
    })
}

pub fn render_capsule_human(inspection: &CapsuleInspection) -> String {
    format!(
        "Meridian Loom // CAPSULE INSPECT\n=================================\norg_id:       {}\nstate_dir:    {}\nmanifest:     {}\nfiles:        {}\n",
        inspection.org_id,
        inspection.state_dir.display(),
        inspection.manifest_path.display(),
        inspection.files.join(", ")
    )
}

pub fn root_from(opt: Option<&str>) -> LoomResult<PathBuf> {
    let root = if let Some(raw) = opt {
        PathBuf::from(raw)
    } else {
        let current_dir = std::env::current_dir().map_err(io_err)?;
        if current_dir.join("loom.toml").exists() {
            current_dir
        } else {
            default_app_home()?
        }
    };
    ensure_root(&root)
}

pub fn kernel_path_for(root: &Path, override_kernel_path: Option<&str>) -> LoomResult<PathBuf> {
    let config = read_config(root)?;
    resolve_kernel_path(root, override_kernel_path, Some(&config))
}

fn resolve_kernel_path(
    root: &Path,
    override_kernel_path: Option<&str>,
    config: Option<&Config>,
) -> LoomResult<PathBuf> {
    let from_override = override_kernel_path
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty());
    let from_config = config
        .map(|cfg| cfg.kernel_path.trim().to_string())
        .filter(|value| !value.is_empty());
    let kernel_path = from_override
        .or(from_config)
        .ok_or_else(|| format!("kernel path is required for {}", root.display()))?;
    Ok(PathBuf::from(kernel_path))
}

pub fn resolve_workspace_path(root: &Path, configured_path: &str) -> PathBuf {
    let path = Path::new(configured_path.trim());
    if path.is_absolute() {
        path.to_path_buf()
    } else {
        root.join(path)
    }
}

pub fn delivery_queue_path(root: &Path, config: &Config) -> PathBuf {
    resolve_workspace_path(root, &config.delivery_queue)
}

fn ensure_root(root: &Path) -> LoomResult<PathBuf> {
    fs::create_dir_all(root).map_err(io_err)?;
    Ok(root.to_path_buf())
}

fn render_config(config: &Config) -> String {
    format!(
        "[runtime]\nmode = {}\nkernel_path = {}\norg_id = {}\nstate_dir = {}\nrun_dir = {}\nlog_dir = {}\nartifact_dir = {}\n\n[capabilities]\ncapabilities_dir = {}\n\n[workers]\npython_path = {}\ntypescript_path = {}\nwasm_dir = {}\n\n[service]\nservice_http_address = {}\nservice_token_env = {}\nservice_max_jobs = {}\nservice_poll_seconds = {}\nservice_max_iterations = {}\n\n[logging]\nlog_level = {}\nlog_format = {}\nlog_max_bytes = {}\nlog_max_files = {}\n\n[handoff]\nhandoff_mode = {}\ndelivery_queue = {}\n",
        json_string(&config.mode),
        json_string(&config.kernel_path),
        json_string(&config.org_id),
        json_string(&config.state_dir),
        json_string(&config.run_dir),
        json_string(&config.log_dir),
        json_string(&config.artifact_dir),
        json_string(&config.capabilities_dir),
        json_string(&config.python_path),
        json_string(&config.typescript_path),
        json_string(&config.wasm_dir),
        json_string(&config.service_http_address),
        json_string(&config.service_token_env),
        config.service_max_jobs,
        config.service_poll_seconds,
        config.service_max_iterations,
        json_string(&config.log_level),
        json_string(&config.log_format),
        config.log_max_bytes,
        config.log_max_files,
        json_string(&config.handoff_mode),
        json_string(&config.delivery_queue),
    )
}

fn default_app_home() -> LoomResult<PathBuf> {
    if let Ok(value) = std::env::var("LOOM_ROOT") {
        let trimmed = value.trim();
        if !trimmed.is_empty() {
            return Ok(PathBuf::from(trimmed));
        }
    }
    if let Ok(value) = std::env::var("XDG_DATA_HOME") {
        let trimmed = value.trim();
        if !trimmed.is_empty() {
            return Ok(PathBuf::from(trimmed)
                .join("meridian-loom")
                .join("runtime")
                .join("default"));
        }
    }
    let home = std::env::var("HOME")
        .map_err(|_| "HOME is not set and --root was not provided".to_string())?;
    Ok(PathBuf::from(home)
        .join(".local/share/meridian-loom")
        .join("runtime")
        .join("default"))
}

fn normalize_mode(mode: &str) -> LoomResult<String> {
    match mode {
        "embedded" | "shadow" | "standalone" => Ok(mode.to_string()),
        other => Err(format!("unsupported mode '{}'", other)),
    }
}

fn push_path_check(
    checks: &mut Vec<Check>,
    label: &'static str,
    path: &Path,
    required: bool,
    success: &'static str,
    category: &'static str,
    remediation: &'static str,
) {
    if path.exists() {
        checks.push(Check {
            level: "OK",
            label,
            detail: format!("{} ({})", success, path.display()),
            category,
            remediation: "",
        });
    } else if required {
        checks.push(Check {
            level: "CRITICAL",
            label,
            detail: format!("missing {}", path.display()),
            category,
            remediation,
        });
    } else {
        checks.push(Check {
            level: "WARN",
            label,
            detail: format!("optional path missing {}", path.display()),
            category,
            remediation,
        });
    }
}

fn find_named_object(section: &str, key: &str) -> Option<String> {
    let idx = section.find(key)?;
    let after = &section[idx + key.len()..];
    let brace_idx = after.find('{')?;
    let start = idx + key.len() + brace_idx;
    let end = find_matching_brace(section, start)?;
    Some(section[start..=end].to_string())
}

fn find_matching_brace(section: &str, start: usize) -> Option<usize> {
    let bytes = section.as_bytes();
    let mut depth = 0usize;
    let mut in_string = false;
    let mut escaped = false;
    for (idx, byte) in bytes.iter().enumerate().skip(start) {
        let ch = *byte as char;
        if in_string {
            if escaped {
                escaped = false;
                continue;
            }
            if ch == '\\' {
                escaped = true;
            } else if ch == '"' {
                in_string = false;
            }
            continue;
        }
        match ch {
            '"' => in_string = true,
            '{' => depth += 1,
            '}' => {
                depth = depth.saturating_sub(1);
                if depth == 0 {
                    return Some(idx);
                }
            }
            _ => {}
        }
    }
    None
}

fn extract_json_string(section: &str, key: &str) -> Option<String> {
    let idx = section.find(key)?;
    let after = &section[idx + key.len()..];
    let first_quote = after.find('"')?;
    let rest = &after[first_quote + 1..];
    let end_quote = rest.find('"')?;
    Some(rest[..end_quote].to_string())
}

fn extract_json_bool(section: &str, key: &str) -> Option<bool> {
    match extract_json_literal(section, key)?.as_str() {
        "true" => Some(true),
        "false" => Some(false),
        _ => None,
    }
}

fn extract_json_string_array(section: &str, key: &str) -> Vec<String> {
    let Some(idx) = section.find(key) else {
        return Vec::new();
    };
    let after = &section[idx + key.len()..];
    let Some(bracket_start) = after.find('[') else {
        return Vec::new();
    };
    let rest = &after[bracket_start + 1..];
    let Some(bracket_end) = rest.find(']') else {
        return Vec::new();
    };
    let body = &rest[..bracket_end];
    body.split(',')
        .map(str::trim)
        .filter(|item| !item.is_empty())
        .map(|item| item.trim_matches('"').to_string())
        .collect()
}

fn extract_json_f64(section: &str, key: &str) -> Option<f64> {
    extract_json_literal(section, key)?.parse::<f64>().ok()
}

fn extract_json_literal(section: &str, key: &str) -> Option<String> {
    let idx = section.find(key)?;
    let after = &section[idx + key.len()..];
    let colon = after.find(':')?;
    let rest = after[colon + 1..].trim_start();
    let end = rest.find([',', '\n', '}']).unwrap_or(rest.len());
    Some(rest[..end].trim().trim_matches('"').to_string())
}

fn render_json_string_array<T: AsRef<str>>(values: &[T]) -> String {
    format!(
        "[{}]",
        values
            .iter()
            .map(|value| json_string(value.as_ref()))
            .collect::<Vec<_>>()
            .join(", ")
    )
}

fn json_string(input: &str) -> String {
    format!("{:?}", input)
}

fn io_err(error: impl std::fmt::Display) -> String {
    error.to_string()
}

fn unix_now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

fn fnv1a64(bytes: &[u8]) -> u64 {
    let mut hash = 0xcbf29ce484222325u64;
    for byte in bytes {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    hash
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn init_refuses_overwrite() {
        let root = temp_path("loom-core-init-refuse");
        fs::create_dir_all(&root).expect("root");
        fs::write(root.join("loom.toml"), "existing").expect("existing config");
        let error = init_workspace(&root, "embedded", None, "org_demo").expect_err("should fail");
        assert!(error.contains("refusing to overwrite"));
    }

    #[test]
    fn init_and_read_config_round_trip() {
        let root = temp_path("loom-core-init");
        let config = init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        assert_eq!(config.mode, "embedded");
        let loaded = read_config(&root).expect("read config");
        assert_eq!(loaded.org_id, "org_demo");
        assert_eq!(loaded.kernel_path, "/tmp/meridian-kernel");
        assert!(root.join("artifacts/shadow/events.jsonl").exists());
        assert!(root
            .join(provider_router::DEFAULT_PROVIDER_PROFILES_PATH)
            .exists());
    }

    #[test]
    fn resolve_workspace_path_handles_relative_and_absolute_paths() {
        let root = temp_path("loom-core-storage-paths");
        let relative = resolve_workspace_path(&root, "state/delivery-queue");
        assert_eq!(relative, root.join("state/delivery-queue"));

        let absolute = resolve_workspace_path(&root, "/var/lib/delivery-queue");
        assert_eq!(absolute, PathBuf::from("/var/lib/delivery-queue"));
    }

    #[test]
    fn doctor_reports_resolved_delivery_queue() {
        let root = temp_path("loom-core-delivery-doctor");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        let config_path = root.join("loom.toml");
        let updated = fs::read_to_string(&config_path)
            .expect("read config")
            .replace("handoff_mode = \"off\"", "handoff_mode = \"dry_run\"")
            .replace(DEFAULT_DELIVERY_QUEUE, "state/delivery-queue");
        fs::write(&config_path, updated).expect("rewrite config");
        fs::create_dir_all(root.join("state/delivery-queue")).expect("queue dir");

        let checks = doctor(&root).expect("doctor");
        let queue_check = checks
            .iter()
            .find(|check| check.label == "delivery_queue")
            .expect("queue check present");
        assert_eq!(queue_check.level, "OK");
        assert!(queue_check
            .detail
            .contains(&root.join("state/delivery-queue").display().to_string()));
    }

    #[test]
    fn doctor_human_render_includes_overall_summary() {
        let human = render_doctor_human(&[
            Check {
                level: "OK",
                label: "config",
                detail: "loaded /tmp/loom.toml".to_string(),
                category: "config",
                remediation: "",
            },
            Check {
                level: "WARN",
                label: "provider",
                detail: "provider auth missing".to_string(),
                category: "provider",
                remediation: "loom onboard",
            },
        ]);
        assert!(human.contains("release:     official v0.1 local runtime"));
        assert!(human.contains("overall:     attention_needed"));
        assert!(human.contains("next_step:   loom doctor --root <path> --format human --fix"));
    }

    #[test]
    fn status_human_render_uses_official_runtime_wording() {
        let root = temp_path("loom-core-status");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        let human = status_human(&root).expect("status");
        assert!(human.contains("release:     official v0.1 local runtime"));
        assert!(human.contains("runtime:     local queue supervisor + service shell"));
    }

    #[test]
    fn resolve_identity_and_build_envelope_against_fake_kernel() {
        let kernel = fake_kernel_root("atlas");
        let root = temp_path("loom-core-envelope");
        init_workspace(
            &root,
            "shadow",
            Some(&kernel.display().to_string()),
            "org_demo",
        )
        .expect("init workspace");

        let identity =
            resolve_agent_identity(&root, None, "atlas", None).expect("resolve identity");
        assert_eq!(identity.agent_id, "agent_atlas");
        assert_eq!(identity.max_per_run_usd, Some(0.5));
        assert!(!identity.approval_required);
        assert_eq!(identity.restrictions, vec!["lead".to_string()]);
        assert_eq!(identity.sanction_decision, "restricted");
        assert_eq!(identity.runtime_id, "local_kernel");
        assert!(identity.runtime_registered);

        let envelope = build_action_envelope(
            &root,
            None,
            "atlas",
            None,
            "research",
            "web_search",
            0.25,
            Some("run_1"),
            Some("session_1"),
        )
        .expect("build envelope");
        assert_eq!(envelope.agent_id, "agent_atlas");
        assert_eq!(envelope.org_id, "org_demo");
        assert_eq!(envelope.estimated_cost_usd, 0.25);
        assert!(!envelope_input_hash(&envelope).is_empty());
    }

    #[test]
    fn resolve_identity_prefers_snapshot_restrictions_when_present() {
        let kernel = fake_kernel_root_with_snapshot(
            "sanction",
            &["execute"],
            Some("restricted_execute"),
            &[],
        );
        let root = temp_path("loom-core-snapshot");
        init_workspace(
            &root,
            "shadow",
            Some(&kernel.display().to_string()),
            "org_demo",
        )
        .expect("init workspace");

        let identity =
            resolve_agent_identity(&root, None, "sanction", None).expect("resolve identity");
        assert_eq!(identity.agent_id, "agent_atlas");
        assert_eq!(identity.restrictions, vec!["execute".to_string()]);
        assert_eq!(identity.sanction_decision, "restricted_execute");
        let preview = preview_local_sanction_controls(&identity);
        assert!(!preview.allowed);
        assert_eq!(preview.decision, "deny");
    }

    #[test]
    fn evaluate_reference_gates_uses_kernel_reference_adapter() {
        let kernel = fake_kernel_root("atlas");
        let root = temp_path("loom-core-reference");
        init_workspace(
            &root,
            "shadow",
            Some(&kernel.display().to_string()),
            "org_demo",
        )
        .expect("init workspace");

        let allowed = build_action_envelope(
            &root,
            None,
            "atlas",
            None,
            "research",
            "web_search",
            0.25,
            Some("run_1"),
            Some("session_1"),
        )
        .expect("allowed envelope");
        let identity = resolve_agent_identity(&root, None, "atlas", None).expect("identity");
        let allowed_check =
            evaluate_reference_gates(&root, None, &identity, &allowed).expect("allowed gates");
        assert!(allowed_check.allowed);
        assert_eq!(allowed_check.stage, "ok");
        assert_eq!(allowed_check.sanction_gate_decision, "allow");
        assert_eq!(allowed_check.approval_gate_decision, "allow");
        assert_eq!(allowed_check.budget_gate_decision, "allow");

        let denied = build_action_envelope(
            &root,
            None,
            "atlas",
            None,
            "research",
            "web_search",
            1.25,
            None,
            None,
        )
        .expect("denied envelope");
        let denied_check =
            evaluate_reference_gates(&root, None, &identity, &denied).expect("denied gates");
        assert!(!denied_check.allowed);
        assert_eq!(denied_check.stage, "budget_gate");
        assert_eq!(denied_check.budget_gate_decision, "deny");
    }

    #[test]
    fn build_envelope_rejects_negative_cost() {
        let kernel = fake_kernel_root("atlas");
        let root = temp_path("loom-core-envelope-negative");
        init_workspace(
            &root,
            "shadow",
            Some(&kernel.display().to_string()),
            "org_demo",
        )
        .expect("init workspace");
        let error = build_action_envelope(
            &root,
            None,
            "atlas",
            None,
            "research",
            "web_search",
            -0.1,
            None,
            None,
        )
        .expect_err("negative cost should fail");
        assert!(error.contains("non-negative"));
    }

    #[test]
    fn build_envelope_with_options_preserves_capability_and_payload() {
        let kernel = fake_kernel_root("atlas");
        let root = temp_path("loom-core-envelope-capability");
        init_workspace(
            &root,
            "shadow",
            Some(&kernel.display().to_string()),
            "org_demo",
        )
        .expect("init workspace");
        let envelope = build_action_envelope_with_options(
            &root,
            None,
            "atlas",
            None,
            "respond",
            "capability:loom.echo.v1",
            0.1,
            Some("run_cap"),
            Some("session_cap"),
            Some("loom.echo.v1"),
            Some("{\"message\":\"hello\"}"),
        )
        .expect("build capability envelope");
        assert_eq!(envelope.capability_name, "loom.echo.v1");
        assert_eq!(envelope.payload_json, "{\"message\":\"hello\"}");
        assert_eq!(envelope.action_type, "respond");
        assert_eq!(envelope.resource, "capability:loom.echo.v1");
        assert!(!envelope_input_hash(&envelope).is_empty());
    }

    #[test]
    fn resolve_identity_does_not_force_workspace_org_hint() {
        let kernel = fake_kernel_root("atlas");
        let root = temp_path("loom-core-org-fallback");
        init_workspace(
            &root,
            "embedded",
            Some(&kernel.display().to_string()),
            "org_local",
        )
        .expect("init workspace");

        let identity =
            resolve_agent_identity(&root, None, "atlas", None).expect("resolve identity");
        assert_eq!(identity.agent_id, "agent_atlas");
        assert_eq!(identity.org_id, "org_demo");
        assert_eq!(identity.max_per_run_usd, Some(0.5));
        assert_eq!(identity.restrictions, vec!["lead".to_string()]);
    }

    #[test]
    fn local_sanction_preview_allows_non_execute_restrictions() {
        let identity = AgentIdentityResolution {
            agent_id: "agent_atlas".to_string(),
            agent_name: "Atlas".to_string(),
            org_id: "org_demo".to_string(),
            role: "analyst".to_string(),
            economy_key: "atlas".to_string(),
            approval_required: false,
            max_per_run_usd: Some(0.5),
            restrictions: vec!["lead".to_string()],
            sanction_decision: "restricted".to_string(),
            runtime_id: "local_kernel".to_string(),
            runtime_label: "Local Kernel Runtime".to_string(),
            bound_org_id: "org_demo".to_string(),
            boundary_name: "workspace".to_string(),
            identity_model: "session".to_string(),
            runtime_registered: true,
            registration_status: "registered".to_string(),
            source: "kernel_agent_registry".to_string(),
        };
        let preview = preview_local_sanction_controls(&identity);
        assert!(preview.allowed);
        assert_eq!(preview.decision, "allow");
        assert_eq!(preview.reason, "no execute restriction");
    }

    #[test]
    fn local_sanction_preview_denies_execute_and_remediation_only() {
        let mut identity = AgentIdentityResolution {
            agent_id: "agent_atlas".to_string(),
            agent_name: "Atlas".to_string(),
            org_id: "org_demo".to_string(),
            role: "analyst".to_string(),
            economy_key: "atlas".to_string(),
            approval_required: false,
            max_per_run_usd: Some(0.5),
            restrictions: vec!["execute".to_string()],
            sanction_decision: "restricted_execute".to_string(),
            runtime_id: "local_kernel".to_string(),
            runtime_label: "Local Kernel Runtime".to_string(),
            bound_org_id: "org_demo".to_string(),
            boundary_name: "workspace".to_string(),
            identity_model: "session".to_string(),
            runtime_registered: true,
            registration_status: "registered".to_string(),
            source: "kernel_agent_registry".to_string(),
        };
        let preview = preview_local_sanction_controls(&identity);
        assert!(!preview.allowed);
        assert_eq!(preview.decision, "deny");
        assert!(preview.reason.contains("restricted from execute"));

        identity.restrictions = vec!["remediation_only".to_string()];
        let remediation = preview_local_sanction_controls(&identity);
        assert!(!remediation.allowed);
        assert_eq!(remediation.decision, "deny");
    }

    fn temp_path(prefix: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "{}-{}",
            prefix,
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        ))
    }

    fn fake_kernel_root(agent_lookup: &str) -> PathBuf {
        fake_kernel_root_with_snapshot(agent_lookup, &[], None, &["lead"])
    }

    fn fake_kernel_root_with_snapshot(
        agent_lookup: &str,
        snapshot_restrictions: &[&str],
        snapshot_sanction_decision: Option<&str>,
        court_restrictions: &[&str],
    ) -> PathBuf {
        let root = temp_path("loom-core-kernel");
        let kernel_dir = root.join("kernel");
        fs::create_dir_all(&kernel_dir).expect("kernel dir");
        let snapshot_restrictions_literal = format!(
            "[{}]",
            snapshot_restrictions
                .iter()
                .map(|value| format!("{:?}", value))
                .collect::<Vec<_>>()
                .join(", ")
        );
        let snapshot_fields = if snapshot_restrictions.is_empty() {
            String::new()
        } else if let Some(decision) = snapshot_sanction_decision {
            format!(
                "'restrictions': {restrictions}, 'sanction_decision': {decision:?}, ",
                restrictions = snapshot_restrictions_literal,
                decision = decision
            )
        } else {
            format!(
                "'restrictions': {restrictions}, ",
                restrictions = snapshot_restrictions_literal
            )
        };
        let court_restrictions_literal = format!(
            "[{}]",
            court_restrictions
                .iter()
                .map(|value| format!("{:?}", value))
                .collect::<Vec<_>>()
                .join(", ")
        );
        fs::write(
            kernel_dir.join("runtimes.json"),
            format!(
                "{{\n  \"runtimes\": {{\n    \"local_kernel\": {{\"id\": \"local_kernel\", \"label\": \"Local Kernel Runtime\"}},\n    \"loom_native\": {{\"status\": \"planned\", \"notes\": \"test note\", \"contract_compliance\": {{\"agent_identity\": null, \"action_envelope\": null, \"cost_attribution\": null, \"approval_hook\": null, \"audit_emission\": null, \"sanction_controls\": null, \"budget_gate\": null}}}}\n  }}\n}}\n"
            ),
        )
        .expect("write runtimes");
        fs::write(
            kernel_dir.join("agent_registry.py"),
            format!(
                "import json, sys\nagent_id = sys.argv[sys.argv.index('--agent_id') + 1]\norg_id = 'org_demo'\nif '--org_id' in sys.argv:\n    org_id = sys.argv[sys.argv.index('--org_id') + 1]\nif agent_id in ('{lookup}', 'agent_atlas', 'Atlas'):\n    print(json.dumps({{'id': 'agent_atlas', 'name': 'Atlas', 'org_id': org_id, 'role': 'analyst', 'economy_key': '{lookup}', 'approval_required': False, {snapshot_fields}'budget': {{'max_per_run_usd': 0.5}}, 'runtime_binding': {{'runtime_id': 'local_kernel', 'runtime_label': 'Local Kernel Runtime', 'bound_org_id': org_id, 'boundary_name': 'workspace', 'identity_model': 'session', 'runtime_registered': True, 'registration_status': 'registered'}}}}, indent=2))\nelse:\n    print(f'Not found: {{agent_id}}')\n",
                lookup = agent_lookup,
                snapshot_fields = snapshot_fields
            ),
        )
        .expect("write agent_registry");
        fs::write(
            kernel_dir.join("court.py"),
            format!(
                "def get_restrictions(agent_id, org_id=None):\n    if agent_id in ('atlas', 'agent_atlas'):\n        return {restrictions}\n    return []\n",
                restrictions = court_restrictions_literal
            ),
        )
        .expect("write court");
        let adapters_dir = kernel_dir.join("adapters");
        fs::create_dir_all(&adapters_dir).expect("adapters dir");
        fs::write(adapters_dir.join("__init__.py"), "").expect("write adapters init");
        fs::write(
            kernel_dir.join("authority.py"),
            "def check_authority(agent_id, action, org_id=None):\n    return True, 'ok'\n",
        )
        .expect("write authority");
        fs::write(
            kernel_dir.join("treasury.py"),
            "def check_budget(agent_id, cost_usd, org_id=None):\n    if cost_usd > 0.5:\n        return False, 'below reserve'\n    return True, 'ok'\n",
        )
        .expect("write treasury");
        fs::write(
            kernel_dir.join("audit.py"),
            "def log_event(*args, **kwargs):\n    return 'evt_fake'\n",
        )
        .expect("write audit");
        fs::write(
            kernel_dir.join("metering.py"),
            "def record(*args, **kwargs):\n    return 'meter_fake'\n",
        )
        .expect("write metering");
        fs::write(
            adapters_dir.join("meridian_compatible.py"),
            "from audit import log_event\nfrom authority import check_authority\nfrom court import get_restrictions\nfrom metering import record as meter_record\nfrom treasury import check_budget\n\n\
def pre_session_check(org_id, agent_id):\n    restrictions = list(get_restrictions(agent_id, org_id=org_id) or [])\n    if 'execute' in restrictions or 'remediation_only' in restrictions:\n        return {'allowed': False, 'reason': f'Agent {agent_id} is restricted from execute', 'restrictions': restrictions}\n    return {'allowed': True, 'reason': 'ok', 'restrictions': restrictions}\n\n\
def pre_action_check(org_id, envelope):\n    session_gate = pre_session_check(org_id, envelope['agent_id'])\n    if not session_gate['allowed']:\n        return {'allowed': False, 'reason': session_gate['reason'], 'stage': 'sanction_controls', 'envelope': envelope, 'restrictions': session_gate['restrictions']}\n    allowed, reason = check_authority(envelope['agent_id'], envelope['action_type'], org_id=org_id)\n    if not allowed:\n        return {'allowed': False, 'reason': reason, 'stage': 'approval_hook', 'envelope': envelope, 'restrictions': session_gate['restrictions']}\n    estimated_cost = envelope.get('estimated_cost_usd', 0.0)\n    if estimated_cost > 0:\n        allowed, reason = check_budget(envelope['agent_id'], estimated_cost, org_id=org_id)\n        if not allowed:\n            return {'allowed': False, 'reason': reason, 'stage': 'budget_gate', 'envelope': envelope, 'restrictions': session_gate['restrictions']}\n    return {'allowed': True, 'reason': 'ok', 'stage': 'ok', 'envelope': envelope, 'restrictions': session_gate['restrictions']}\n",
        )
        .expect("write adapter");
        root
    }
}
