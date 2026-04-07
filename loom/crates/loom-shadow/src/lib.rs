use loom_core::{
    build_action_envelope, build_action_envelope_with_options,
    capabilities::{
        render_capability_json, render_capability_readiness_human,
        render_capability_readiness_json, resolve_capability_for_request, CapabilityDescriptor,
    },
    enforce_sanction_controls, ensure_runtime_worker_scaffold, envelope_input_hash,
    evaluate_reference_gates, kernel_path_for,
    pipeline::record_pipeline_from_ingress,
    preview_local_sanction_controls, read_config, resolve_agent_identity, runtime_worker_entry,
    wasm_host::{
        builtin_browser_navigate_guest_bytes, builtin_fs_read_guest_bytes,
        builtin_fs_write_guest_bytes, builtin_heartbeat_schedule_guest_bytes,
        builtin_kv_get_guest_bytes, builtin_kv_set_guest_bytes, builtin_llm_inference_guest_bytes,
        builtin_system_info_guest_bytes, builtin_terminal_exec_guest_bytes,
        render_wasm_browser_navigate_request_json, render_wasm_fs_read_request_json,
        render_wasm_fs_write_request_json, render_wasm_heartbeat_schedule_request_json,
        render_wasm_kv_get_request_json, render_wasm_kv_set_request_json,
        render_wasm_llm_inference_request_json, render_wasm_system_info_request_json,
        render_wasm_terminal_exec_request_json, run_wasm_guest, HostBackend,
        WasmBrowserNavigateRequest, WasmExecutionRequest, WasmExecutionResult, WasmFsReadRequest,
        WasmFsWriteRequest, WasmGuestSource, WasmHeartbeatScheduleKind,
        WasmHeartbeatScheduleRequest, WasmHostBuilder, WasmHostSecurityContext, WasmKvGetRequest,
        WasmKvSetRequest, WasmLlmInferenceRequest, WasmSystemInfoRequest, WasmTerminalExecRequest,
    },
    ActionEnvelope, AgentIdentityResolution, Config, ReferenceGateCheck,
};
mod event_schema;
mod policy_queue;
mod proof_views;
mod reservations;
mod scheduler_state;

use event_schema::{
    canonical_audit_id, canonical_decision_id, canonical_envelope_id, canonical_event_id,
    canonical_execution_id, canonical_job_id, canonical_parity_id, render_artifact_refs_human,
    render_artifact_refs_json, ArtifactRefSpec, RuntimeEventSpec, RuntimeEventV1,
};
use loom_poge::{HostCallKind, KernelWarrant, PoGEInterceptor};
use policy_queue::{classify_action, PolicyClass};
use proof_views::render_proof_first_status_human;
use reservations::{
    ack_job, expire_stale, load_ledger, nack_job, reserve_job, save_ledger, ReservationLedger,
};
use scheduler_state::{
    append_job_with_id, load_state as load_scheduler_state, save_state as save_scheduler_state,
    transition_job, update_job_metadata, JobStatus, SchedulerState,
};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs;
use std::io::{self, ErrorKind, Read, Write};
use std::net::{Shutdown, TcpListener, TcpStream, ToSocketAddrs};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use ureq::ResponseExt;

pub type ShadowResult<T> = Result<T, String>;

#[derive(Clone, Debug, PartialEq)]
pub struct PreflightCapture {
    pub event_log: PathBuf,
    pub audit_preview_log: PathBuf,
    pub reference_report: PathBuf,
    pub reference_event_log: PathBuf,
    pub latest_report: PathBuf,
    pub input_hash: String,
    pub hooks: Vec<String>,
    pub estimated_cost_usd: f64,
    pub identity_restrictions: Vec<String>,
    pub reference_restrictions: Vec<String>,
    pub sanction_decision: String,
    pub sanction_gate_decision: String,
    pub budget_limit_usd: Option<f64>,
    pub budget_gate_decision: String,
    pub approval_decision: String,
    pub approval_gate_decision: String,
    pub audit_emission_decision: String,
    pub overall_decision: String,
    pub reference_stage: String,
    pub reference_reason: String,
    pub capability_readiness_human: String,
    pub capability_readiness_json: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct ComparisonSummary {
    pub primary_log: PathBuf,
    pub shadow_log: PathBuf,
    pub primary_events: usize,
    pub shadow_events: usize,
    pub pairs_compared: usize,
    pub matches: usize,
    pub divergences: usize,
    pub divergence_rate: f64,
    pub hook_results: Vec<HookComparison>,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct DecisionCapture {
    pub decision_path: PathBuf,
    pub input_hash: String,
    pub agent_id: String,
    pub org_id: String,
    pub action_type: String,
    pub resource: String,
    pub estimated_cost_usd: f64,
    pub identity_restrictions: Vec<String>,
    pub reference_restrictions: Vec<String>,
    pub local_sanction_allowed: bool,
    pub local_sanction_decision: String,
    pub local_sanction_reason: String,
    pub sanction_gate_decision: String,
    pub approval_gate_decision: String,
    pub budget_limit_usd: Option<f64>,
    pub budget_gate_decision: String,
    pub overall_decision: String,
    pub effective_source: String,
    pub effective_stage: String,
    pub effective_reason: String,
    pub reference_stage: String,
    pub reference_reason: String,
    pub source: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct RuntimeExecutionCapture {
    pub execution_path: PathBuf,
    pub runtime_event_path: PathBuf,
    pub runtime_event_stream_path: PathBuf,
    pub worker_request_path: PathBuf,
    pub worker_result_path: PathBuf,
    pub worker_log_path: PathBuf,
    pub audit_log_path: PathBuf,
    pub parity_stream_path: PathBuf,
    pub parity_report_path: PathBuf,
    pub reference_probe_path: Option<PathBuf>,
    pub reference_probe_stream_path: Option<PathBuf>,
    pub decision_path: PathBuf,
    pub input_hash: String,
    pub agent_id: String,
    pub org_id: String,
    pub action_type: String,
    pub resource: String,
    pub estimated_cost_usd: f64,
    pub runtime_outcome: String,
    pub budget_reservation_id: String,
    pub budget_reservation_status: String,
    pub budget_reservation_reason: String,
    pub worker_status: String,
    pub worker_kind: String,
    pub worker_note: String,
    pub overall_decision: String,
    pub effective_source: String,
    pub effective_stage: String,
    pub reference_decision: String,
    pub reference_stage: String,
    pub audit_emission_status: String,
    pub economy_hook_status: String,
    pub reference_probe_status: String,
    pub reference_probe_note: String,
    pub parity_status: String,
    pub parity_reason: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ShadowBackendKind {
    Wasmtime,
    Command,
    Http,
    Mcp,
    A2a,
    A2aAction,
    GrpcAction,
    GrpcPhysical,
}

impl ShadowBackendKind {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Wasmtime => "wasmtime",
            Self::Command => "command",
            Self::Http => "http",
            Self::Mcp => "mcp",
            Self::A2a => "a2a",
            Self::A2aAction => "a2a_action",
            Self::GrpcAction => "grpc_action",
            Self::GrpcPhysical => "grpc_physical",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ShadowRunRequest {
    pub root: PathBuf,
    pub kernel_path: PathBuf,
    pub backend: ShadowBackendKind,
    pub agent_id: String,
    pub org_id: String,
    pub action_type: String,
    pub resource: String,
    pub module_name: String,
    pub entrypoint: String,
    pub fuel_budget: u64,
    pub warrant: KernelWarrant,
    pub wasm_bytes: Vec<u8>,
    pub command_program: Option<String>,
    pub command_args: Vec<String>,
    pub http_url: Option<String>,
    pub http_method: Option<String>,
    pub http_headers: Vec<(String, String)>,
    pub http_body_json: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ShadowRunCapture {
    pub execution_path: PathBuf,
    pub shadow_latest_path: PathBuf,
    pub parity_latest_path: PathBuf,
    pub parity_stream_path: PathBuf,
    pub status: String,
    pub captured_at: String,
    pub backend: String,
    pub agent_id: String,
    pub org_id: String,
    pub action_type: String,
    pub resource: String,
    pub module_name: String,
    pub entrypoint: String,
    pub entrypoint_result: Option<i32>,
    pub host_backend: String,
    pub warrant_binding_status: String,
    pub warrant_id_hex: Option<String>,
    pub poge_merkle_root_hex: Option<String>,
    pub poge_trace_len: Option<u32>,
    pub poge_witness_digest_hex: Option<String>,
    pub poge_session_label: Option<String>,
    pub poge_epoch_start_ms: Option<u64>,
    pub poge_epoch_end_ms: Option<u64>,
    pub poge_module_digest_hex: Option<String>,
    pub host_calls: Vec<String>,
    pub host_response_json: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EnqueuedAction {
    pub queue_path: PathBuf,
    pub job_path: PathBuf,
    pub input_hash: String,
    pub policy_class: String,
    pub agent_id: String,
    pub org_id: String,
    pub action_type: String,
    pub resource: String,
    pub estimated_cost_usd: String,
    pub kernel_path: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QueueRecordSnapshot {
    pub root: PathBuf,
    pub queue_path: PathBuf,
    pub ack_path: PathBuf,
    pub job_path: PathBuf,
    pub job_id: String,
    pub queue_bucket: String,
    pub policy_class: String,
    pub status: String,
    pub queued_at: String,
    pub agent_id: String,
    pub org_id: String,
    pub action_type: String,
    pub resource: String,
    pub estimated_cost_usd: String,
    pub run_id: String,
    pub session_id: String,
    pub kernel_path: String,
    pub job_status: String,
    pub job_stage: String,
    pub acknowledged: bool,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QueueConsumeSummary {
    pub root: PathBuf,
    pub queue_dir: PathBuf,
    pub requested: usize,
    pub pending_before: usize,
    pub pending_after: usize,
    pub processed_jobs: usize,
    pub failed_jobs: usize,
    pub acked_jobs: usize,
    pub last_input_hash: String,
    pub last_execution_path: PathBuf,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QueueRunOnceSummary {
    pub root: PathBuf,
    pub queue_dir: PathBuf,
    pub progress_path: PathBuf,
    pub requested: usize,
    pub pending_before: usize,
    pub pending_after: usize,
    pub processed_jobs: usize,
    pub failed_jobs: usize,
    pub acked_jobs: usize,
    pub last_input_hash: String,
    pub last_execution_path: PathBuf,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QueueRunUntilEmptySummary {
    pub root: PathBuf,
    pub queue_dir: PathBuf,
    pub progress_path: PathBuf,
    pub journal_path: PathBuf,
    pub requested: usize,
    pub max_passes: usize,
    pub passes_completed: usize,
    pub initial_pending: usize,
    pub final_pending: usize,
    pub processed_jobs: usize,
    pub failed_jobs: usize,
    pub acked_jobs: usize,
    pub last_input_hash: String,
    pub last_execution_path: PathBuf,
    pub drained: bool,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QueueStatusSnapshot {
    pub root: PathBuf,
    pub queue_dir: PathBuf,
    pub pending_records: usize,
    pub acked_records: usize,
    pub total_pending: usize,
    pub standard_depth: usize,
    pub privileged_depth: usize,
    pub budget_heavy_depth: usize,
    pub sanction_sensitive_depth: usize,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QueueAckCapture {
    pub root: PathBuf,
    pub job_id: String,
    pub job_path: PathBuf,
    pub queue_path: Option<PathBuf>,
    pub ack_path: PathBuf,
    pub queue_bucket: String,
    pub job_status: String,
    pub acknowledged_at: String,
    pub acknowledged_by: String,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct JobSnapshot {
    pub root: PathBuf,
    pub job_id: String,
    pub job_path: PathBuf,
    pub status: String,
    pub stage: String,
    pub queue_bucket: String,
    pub queued_at: String,
    pub updated_at: String,
    pub agent_id: String,
    pub org_id: String,
    pub action_type: String,
    pub resource: String,
    pub estimated_cost_usd: String,
    pub runtime_outcome: String,
    pub budget_reservation_id: String,
    pub budget_reservation_status: String,
    pub budget_reservation_reason: String,
    pub worker_status: String,
    pub queue_path: Option<PathBuf>,
    pub decision_path: Option<PathBuf>,
    pub execution_path: Option<PathBuf>,
    pub event_path: Option<PathBuf>,
    pub event_stream_path: Option<PathBuf>,
    pub audit_log_path: Option<PathBuf>,
    pub parity_report_path: Option<PathBuf>,
    pub reservation_id: String,
    pub reservation_state: String,
    pub attempt_count: u32,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SupervisorRunSummary {
    pub root: PathBuf,
    pub queue_dir: PathBuf,
    pub processed: usize,
    pub allowed: usize,
    pub denied: usize,
    pub failed: usize,
    pub last_input_hash: String,
    pub last_execution_path: PathBuf,
    pub audit_log_path: PathBuf,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SupervisorWatchSummary {
    pub root: PathBuf,
    pub supervisor_dir: PathBuf,
    pub iterations: usize,
    pub poll_seconds: u64,
    pub processed: usize,
    pub allowed: usize,
    pub denied: usize,
    pub failed: usize,
    pub heartbeat_log_path: PathBuf,
    pub status_path: PathBuf,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SupervisorStatusSnapshot {
    pub root: PathBuf,
    pub supervisor_dir: PathBuf,
    pub status_path: PathBuf,
    pub heartbeat_log_path: PathBuf,
    pub available: bool,
    pub updated_at: String,
    pub iterations: usize,
    pub poll_seconds: u64,
    pub processed: usize,
    pub allowed: usize,
    pub denied: usize,
    pub failed: usize,
    pub pending_jobs: usize,
    pub processed_jobs: usize,
    pub failed_jobs: usize,
    pub heartbeat_entries: usize,
    pub last_heartbeat_timestamp: String,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SupervisorDaemonSnapshot {
    pub root: PathBuf,
    pub supervisor_dir: PathBuf,
    pub runtime_state_path: PathBuf,
    pub stop_request_path: PathBuf,
    pub stdout_log_path: PathBuf,
    pub available: bool,
    pub session_id: String,
    pub pid: u32,
    pub running: bool,
    pub status: String,
    pub updated_at: String,
    pub booted_at: String,
    pub stopped_at: String,
    pub poll_seconds: u64,
    pub max_jobs: usize,
    pub max_iterations: usize,
    pub iterations_completed: usize,
    pub processed: usize,
    pub allowed: usize,
    pub denied: usize,
    pub failed: usize,
    pub pending_jobs: usize,
    pub processed_jobs: usize,
    pub failed_jobs: usize,
    pub heartbeat_entries: usize,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RuntimeServiceSnapshot {
    pub root: PathBuf,
    pub service_dir: PathBuf,
    pub service_lock_path: PathBuf,
    pub metrics_path: PathBuf,
    pub config_path: PathBuf,
    pub socket_path: PathBuf,
    pub http_address: String,
    pub http_token_required: bool,
    pub runtime_state_path: PathBuf,
    pub stop_request_path: PathBuf,
    pub stdout_log_path: PathBuf,
    pub event_log_path: PathBuf,
    pub ingress_stream_path: PathBuf,
    pub available: bool,
    pub session_id: String,
    pub pid: u32,
    pub running: bool,
    pub status: String,
    pub updated_at: String,
    pub booted_at: String,
    pub stopped_at: String,
    pub poll_seconds: u64,
    pub max_jobs: usize,
    pub max_iterations: usize,
    pub iterations_completed: usize,
    pub requests_received: usize,
    pub submitted: usize,
    pub processed: usize,
    pub allowed: usize,
    pub denied: usize,
    pub failed: usize,
    pub pending_jobs: usize,
    pub processed_jobs: usize,
    pub failed_jobs: usize,
    pub last_request_id: String,
    pub last_job_id: String,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RuntimeServiceSubmitCapture {
    pub request_id: String,
    pub transport: String,
    pub service_target: String,
    pub socket_path: PathBuf,
    pub ingress_request_path: PathBuf,
    pub ingress_receipt_path: PathBuf,
    pub job_id: String,
    pub policy_class: String,
    pub queue_path: PathBuf,
    pub accepted_at: String,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RuntimeServiceCancelCapture {
    pub request_id: String,
    pub transport: String,
    pub service_target: String,
    pub socket_path: PathBuf,
    pub job_id: String,
    pub status: String,
    pub current_status: String,
    pub previous_status: String,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RuntimeServiceImportCapture {
    pub commitments_source: String,
    pub imports_dir: PathBuf,
    pub imported: usize,
    pub skipped: usize,
    pub last_import_id: String,
    pub last_job_id: String,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq)]
struct WorkerExecutionCapture {
    worker_request_path: PathBuf,
    worker_result_path: PathBuf,
    worker_log_path: PathBuf,
    worker_status: String,
    worker_kind: String,
    worker_note: String,
    runtime_outcome: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct BudgetReservationCapture {
    reservation_id: String,
    status: String,
    reason: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HookComparison {
    pub pair_index: usize,
    pub hook_name: String,
    pub input_hash: String,
    pub primary_decision: String,
    pub shadow_decision: String,
    pub matched: bool,
    pub primary_agent_id: String,
    pub shadow_agent_id: String,
    pub primary_org_id: String,
    pub shadow_org_id: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct ShadowEvent {
    hook_name: String,
    input_hash: String,
    decision: String,
    agent_id: String,
    org_id: String,
}

pub fn capture_preflight(
    root: &Path,
    kernel_path: &Path,
    identity: &AgentIdentityResolution,
    envelope: &ActionEnvelope,
    reference: &ReferenceGateCheck,
) -> ShadowResult<PreflightCapture> {
    let shadow_dir = ensure_shadow_dir(root)?;
    let audit_dir = ensure_audit_dir(root)?;
    let event_log = shadow_dir.join("events.jsonl");
    let audit_preview_log = audit_dir.join("preview.jsonl");
    let reference_report = shadow_dir.join("reference.json");
    let reference_event_log = shadow_dir.join("reference_events.jsonl");
    let latest_report = shadow_dir.join("latest.json");
    let input_hash = envelope_input_hash(envelope);
    let sanction_decision = if identity.sanction_decision.is_empty() {
        "unknown"
    } else {
        identity.sanction_decision.as_str()
    };
    let effective_restrictions = if !reference.restrictions.is_empty() {
        reference.restrictions.clone()
    } else {
        identity.restrictions.clone()
    };
    let budget_limit_usd = identity.max_per_run_usd;
    let approval_decision = if identity.approval_required {
        "requires_approval"
    } else {
        "not_required"
    };
    let overall_decision = if reference.allowed { "allow" } else { "deny" };
    let (resolved_capability, capability_resolution_note) = match read_config(root) {
        Ok(config) => match resolve_capability_for_request(
            root,
            &config,
            if envelope.capability_name.is_empty() {
                None
            } else {
                Some(envelope.capability_name.as_str())
            },
            &envelope.action_type,
            &envelope.resource,
        ) {
            Ok(capability) => (capability, None),
            Err(error) => (None, Some(error)),
        },
        Err(error) => (
            None,
            Some(format!("capability readiness skipped: {}", error)),
        ),
    };
    let capability_readiness_human = render_capability_readiness_human(
        &envelope.action_type,
        &envelope.resource,
        resolved_capability.as_ref(),
        capability_resolution_note.as_deref(),
    );
    let capability_readiness_json = render_capability_readiness_json(
        &envelope.action_type,
        &envelope.resource,
        resolved_capability.as_ref(),
        capability_resolution_note.as_deref(),
    );

    append_line(
        &event_log,
        &format!(
            "{{\"timestamp\":{},\"source\":\"loom_shadow_preflight\",\"hook_name\":\"agent_identity\",\"decision\":\"resolved\",\"agent_id\":{},\"org_id\":{},\"runtime_id\":{},\"input_hash\":{},\"note\":\"experimental preflight capture\"}}\n",
            json_string(&timestamp_now()),
            json_string(&identity.agent_id),
            json_string(&identity.org_id),
            json_string(&identity.runtime_id),
            json_string(&input_hash),
        ),
    )?;
    append_line(
        &event_log,
        &format!(
            "{{\"timestamp\":{},\"source\":\"loom_shadow_preflight\",\"hook_name\":\"action_envelope\",\"decision\":\"constructed\",\"agent_id\":{},\"org_id\":{},\"runtime_id\":{},\"action_type\":{},\"resource\":{},\"estimated_cost_usd\":{:.6},\"input_hash\":{},\"note\":\"experimental preflight capture\"}}\n",
            json_string(&timestamp_now()),
            json_string(&envelope.agent_id),
            json_string(&envelope.org_id),
            json_string(&envelope.runtime_id),
            json_string(&envelope.action_type),
            json_string(&envelope.resource),
            envelope.estimated_cost_usd,
            json_string(&input_hash),
        ),
    )?;
    append_line(
        &event_log,
        &format!(
            "{{\"timestamp\":{},\"source\":\"loom_shadow_preflight\",\"hook_name\":\"sanction_controls\",\"decision\":{},\"agent_id\":{},\"org_id\":{},\"runtime_id\":{},\"restrictions\":{},\"input_hash\":{},\"note\":\"experimental restriction snapshot\"}}\n",
            json_string(&timestamp_now()),
            json_string(&reference.sanction_gate_decision),
            json_string(&identity.agent_id),
            json_string(&identity.org_id),
            json_string(&identity.runtime_id),
            render_json_string_array(&effective_restrictions),
            json_string(&input_hash),
        ),
    )?;
    append_line(
        &event_log,
        &format!(
            "{{\"timestamp\":{},\"source\":\"loom_shadow_preflight\",\"hook_name\":\"cost_attribution\",\"decision\":\"estimated\",\"agent_id\":{},\"org_id\":{},\"runtime_id\":{},\"estimated_cost_usd\":{:.6},\"input_hash\":{},\"note\":\"experimental preflight estimate\"}}\n",
            json_string(&timestamp_now()),
            json_string(&envelope.agent_id),
            json_string(&envelope.org_id),
            json_string(&envelope.runtime_id),
            envelope.estimated_cost_usd,
            json_string(&input_hash),
        ),
    )?;
    append_line(
        &event_log,
        &format!(
            "{{\"timestamp\":{},\"source\":\"loom_shadow_preflight\",\"hook_name\":\"approval_hook\",\"decision\":{},\"agent_id\":{},\"org_id\":{},\"runtime_id\":{},\"input_hash\":{},\"note\":\"experimental preflight policy read\"}}\n",
            json_string(&timestamp_now()),
            json_string(&reference.approval_gate_decision),
            json_string(&identity.agent_id),
            json_string(&identity.org_id),
            json_string(&identity.runtime_id),
            json_string(&input_hash),
        ),
    )?;
    append_line(
        &event_log,
        &format!(
            "{{\"timestamp\":{},\"source\":\"loom_shadow_preflight\",\"hook_name\":\"budget_gate\",\"decision\":{},\"agent_id\":{},\"org_id\":{},\"runtime_id\":{},\"estimated_cost_usd\":{:.6},\"budget_limit_usd\":{},\"input_hash\":{},\"note\":\"experimental preflight budget check\"}}\n",
            json_string(&timestamp_now()),
            json_string(&reference.budget_gate_decision),
            json_string(&identity.agent_id),
            json_string(&identity.org_id),
            json_string(&identity.runtime_id),
            envelope.estimated_cost_usd,
            budget_limit_usd
                .map(|value| format!("{:.6}", value))
                .unwrap_or_else(|| "null".to_string()),
            json_string(&input_hash),
        ),
    )?;
    let audit_emission_decision =
        emit_kernel_audit_preview(kernel_path, &audit_preview_log, envelope, &input_hash)?;
    fs::write(
        &reference_report,
        format!(
            "{{\n  \"source\": {},\n  \"allowed\": {},\n  \"stage\": {},\n  \"reason\": {},\n  \"restrictions\": {},\n  \"sanction_gate_decision\": {},\n  \"approval_gate_decision\": {},\n  \"budget_gate_decision\": {}\n}}\n",
            json_string(&reference.source),
            if reference.allowed { "true" } else { "false" },
            json_string(&reference.stage),
            json_string(&reference.reason),
            render_json_string_array(&reference.restrictions),
            json_string(&reference.sanction_gate_decision),
            json_string(&reference.approval_gate_decision),
            json_string(&reference.budget_gate_decision),
        ),
    )
    .map_err(io_err)?;
    fs::write(
        &reference_event_log,
        format!(
            "{{\"timestamp\":{},\"source\":\"kernel_reference_adapter\",\"hook_name\":\"agent_identity\",\"decision\":\"resolved\",\"agent_id\":{},\"org_id\":{},\"input_hash\":{}}}\n\
{{\"timestamp\":{},\"source\":\"kernel_reference_adapter\",\"hook_name\":\"action_envelope\",\"decision\":\"constructed\",\"agent_id\":{},\"org_id\":{},\"input_hash\":{}}}\n\
{{\"timestamp\":{},\"source\":\"kernel_reference_adapter\",\"hook_name\":\"sanction_controls\",\"decision\":{},\"agent_id\":{},\"org_id\":{},\"input_hash\":{}}}\n\
{{\"timestamp\":{},\"source\":\"kernel_reference_adapter\",\"hook_name\":\"cost_attribution\",\"decision\":\"estimated\",\"agent_id\":{},\"org_id\":{},\"input_hash\":{}}}\n\
{{\"timestamp\":{},\"source\":\"kernel_reference_adapter\",\"hook_name\":\"approval_hook\",\"decision\":{},\"agent_id\":{},\"org_id\":{},\"input_hash\":{}}}\n\
{{\"timestamp\":{},\"source\":\"kernel_reference_adapter\",\"hook_name\":\"budget_gate\",\"decision\":{},\"agent_id\":{},\"org_id\":{},\"input_hash\":{}}}\n\
{{\"timestamp\":{},\"source\":\"kernel_reference_adapter\",\"hook_name\":\"audit_emission\",\"decision\":\"not_exercised\",\"agent_id\":{},\"org_id\":{},\"input_hash\":{}}}\n",
            json_string(&timestamp_now()),
            json_string(&identity.agent_id),
            json_string(&identity.org_id),
            json_string(&input_hash),
            json_string(&timestamp_now()),
            json_string(&identity.agent_id),
            json_string(&identity.org_id),
            json_string(&input_hash),
            json_string(&timestamp_now()),
            json_string(&reference.sanction_gate_decision),
            json_string(&identity.agent_id),
            json_string(&identity.org_id),
            json_string(&input_hash),
            json_string(&timestamp_now()),
            json_string(&identity.agent_id),
            json_string(&identity.org_id),
            json_string(&input_hash),
            json_string(&timestamp_now()),
            json_string(&reference.approval_gate_decision),
            json_string(&identity.agent_id),
            json_string(&identity.org_id),
            json_string(&input_hash),
            json_string(&timestamp_now()),
            json_string(&reference.budget_gate_decision),
            json_string(&identity.agent_id),
            json_string(&identity.org_id),
            json_string(&input_hash),
            json_string(&timestamp_now()),
            json_string(&identity.agent_id),
            json_string(&identity.org_id),
            json_string(&input_hash),
        ),
    )
    .map_err(io_err)?;
    append_line(
        &event_log,
        &format!(
            "{{\"timestamp\":{},\"source\":\"loom_shadow_preflight\",\"hook_name\":\"audit_emission\",\"decision\":{},\"agent_id\":{},\"org_id\":{},\"runtime_id\":{},\"input_hash\":{},\"preview_log\":{},\"note\":\"experimental audit preview written via kernel serializer\"}}\n",
            json_string(&timestamp_now()),
            json_string(&audit_emission_decision),
            json_string(&envelope.agent_id),
            json_string(&envelope.org_id),
            json_string(&envelope.runtime_id),
            json_string(&input_hash),
            json_string(&audit_preview_log.display().to_string()),
        ),
    )?;

    fs::write(
        &latest_report,
        format!(
            "{{\n  \"status\": \"preflight_captured\",\n  \"events_compared\": 0,\n  \"divergences\": 0,\n  \"captured_hooks\": [\"agent_identity\", \"action_envelope\", \"cost_attribution\", \"approval_hook\", \"audit_emission\", \"sanction_controls\", \"budget_gate\"],\n  \"input_hash\": {},\n  \"estimated_cost_usd\": {:.6},\n  \"restrictions\": {},\n  \"sanction_decision\": {},\n  \"sanction_gate_decision\": {},\n  \"budget_limit_usd\": {},\n  \"budget_gate_decision\": {},\n  \"approval_decision\": {},\n  \"approval_gate_decision\": {},\n  \"audit_emission_decision\": {},\n  \"overall_decision\": {},\n  \"reference_stage\": {},\n  \"reference_reason\": {},\n  \"event_log\": {},\n  \"audit_preview_log\": {},\n  \"reference_report\": {},\n  \"reference_event_log\": {},\n  \"note\": \"experimental preflight captured with read-only kernel reference gates; no governed runtime yet\"\n}}\n",
            json_string(&input_hash),
            envelope.estimated_cost_usd,
            render_json_string_array(&effective_restrictions),
            json_string(sanction_decision),
            json_string(&reference.sanction_gate_decision),
            budget_limit_usd
                .map(|value| format!("{:.6}", value))
                .unwrap_or_else(|| "null".to_string()),
            json_string(&reference.budget_gate_decision),
            json_string(approval_decision),
            json_string(&reference.approval_gate_decision),
            json_string(&audit_emission_decision),
            json_string(overall_decision),
            json_string(&reference.stage),
            json_string(&reference.reason),
            json_string(&event_log.display().to_string()),
            json_string(&audit_preview_log.display().to_string()),
            json_string(&reference_report.display().to_string()),
            json_string(&reference_event_log.display().to_string()),
        ),
    )
    .map_err(io_err)?;

    Ok(PreflightCapture {
        event_log,
        audit_preview_log,
        reference_report,
        reference_event_log,
        latest_report,
        input_hash,
        hooks: vec![
            "agent_identity".to_string(),
            "action_envelope".to_string(),
            "cost_attribution".to_string(),
            "approval_hook".to_string(),
            "audit_emission".to_string(),
            "sanction_controls".to_string(),
            "budget_gate".to_string(),
        ],
        estimated_cost_usd: envelope.estimated_cost_usd,
        identity_restrictions: identity.restrictions.clone(),
        reference_restrictions: effective_restrictions,
        sanction_decision: sanction_decision.to_string(),
        sanction_gate_decision: reference.sanction_gate_decision.clone(),
        budget_limit_usd,
        budget_gate_decision: reference.budget_gate_decision.clone(),
        approval_decision: approval_decision.to_string(),
        approval_gate_decision: reference.approval_gate_decision.clone(),
        audit_emission_decision: audit_emission_decision.to_string(),
        overall_decision: overall_decision.to_string(),
        reference_stage: reference.stage.clone(),
        reference_reason: reference.reason.clone(),
        capability_readiness_human,
        capability_readiness_json,
    })
}

pub fn compare_logs(
    root: Option<&Path>,
    primary: &Path,
    shadow: &Path,
) -> ShadowResult<ComparisonSummary> {
    let primary_events = load_events(primary)?;
    let shadow_events = load_events(shadow)?;
    let pairs_compared = primary_events.len().min(shadow_events.len());
    let mut matches = 0usize;
    let mut divergences = 0usize;
    let mut hook_results = Vec::new();

    for idx in 0..pairs_compared {
        let left = &primary_events[idx];
        let right = &shadow_events[idx];
        let matched = left.hook_name == right.hook_name
            && left.input_hash == right.input_hash
            && left.decision == right.decision
            && left.agent_id == right.agent_id
            && left.org_id == right.org_id;
        if matched {
            matches += 1;
        } else {
            divergences += 1;
        }
        hook_results.push(HookComparison {
            pair_index: idx,
            hook_name: if left.hook_name == right.hook_name {
                left.hook_name.clone()
            } else {
                format!("{} -> {}", left.hook_name, right.hook_name)
            },
            input_hash: if left.input_hash == right.input_hash {
                left.input_hash.clone()
            } else {
                format!("{} -> {}", left.input_hash, right.input_hash)
            },
            primary_decision: left.decision.clone(),
            shadow_decision: right.decision.clone(),
            matched,
            primary_agent_id: left.agent_id.clone(),
            shadow_agent_id: right.agent_id.clone(),
            primary_org_id: left.org_id.clone(),
            shadow_org_id: right.org_id.clone(),
        });
    }

    divergences += primary_events.len().max(shadow_events.len()) - pairs_compared;
    let divergence_rate = if pairs_compared == 0 {
        0.0
    } else {
        divergences as f64 / pairs_compared as f64
    };

    let summary = ComparisonSummary {
        primary_log: primary.to_path_buf(),
        shadow_log: shadow.to_path_buf(),
        primary_events: primary_events.len(),
        shadow_events: shadow_events.len(),
        pairs_compared,
        matches,
        divergences,
        divergence_rate,
        hook_results,
        note: "offline event-log diff only; use `loom action execute` plus `loom parity report` for runtime-side rehearsal and optional live reference probe".to_string(),
    };

    if let Some(root) = root {
        let latest_report = ensure_shadow_dir(root)?.join("latest.json");
        fs::write(&latest_report, render_compare_json(&summary)).map_err(io_err)?;
    }

    Ok(summary)
}

pub fn capture_decision(
    root: &Path,
    identity: &AgentIdentityResolution,
    envelope: &ActionEnvelope,
    reference: &ReferenceGateCheck,
) -> ShadowResult<DecisionCapture> {
    let decision_path = ensure_shadow_dir(root)?.join("decision.json");
    let sanction = enforce_sanction_controls(identity);
    let local_preview = preview_local_sanction_controls(identity);
    let (overall_decision, effective_source, effective_stage, effective_reason) =
        if !sanction.allowed {
            (
                sanction.decision.clone(),
                "sanction_enforcement".to_string(),
                "sanction_controls".to_string(),
                sanction.reason.clone(),
            )
        } else if reference.allowed {
            (
                "allow".to_string(),
                "reference_gate".to_string(),
                reference.stage.clone(),
                reference.reason.clone(),
            )
        } else {
            (
                "deny".to_string(),
                "reference_gate".to_string(),
                reference.stage.clone(),
                reference.reason.clone(),
            )
        };
    let capture = DecisionCapture {
        decision_path: decision_path.clone(),
        input_hash: envelope_input_hash(envelope),
        agent_id: identity.agent_id.clone(),
        org_id: identity.org_id.clone(),
        action_type: envelope.action_type.clone(),
        resource: envelope.resource.clone(),
        estimated_cost_usd: envelope.estimated_cost_usd,
        identity_restrictions: identity.restrictions.clone(),
        reference_restrictions: reference.restrictions.clone(),
        local_sanction_allowed: local_preview.allowed,
        local_sanction_decision: local_preview.decision,
        local_sanction_reason: local_preview.reason,
        sanction_gate_decision: reference.sanction_gate_decision.clone(),
        approval_gate_decision: reference.approval_gate_decision.clone(),
        budget_limit_usd: identity.max_per_run_usd,
        budget_gate_decision: reference.budget_gate_decision.clone(),
        overall_decision,
        effective_source,
        effective_stage,
        effective_reason,
        reference_stage: reference.stage.clone(),
        reference_reason: reference.reason.clone(),
        source: "experimental_preflight_gate".to_string(),
    };
    fs::write(&decision_path, render_decision_json(&capture)).map_err(io_err)?;
    Ok(capture)
}

pub fn capture_runtime_execution(
    root: &Path,
    kernel_path: &Path,
    envelope: &ActionEnvelope,
    reference: &ReferenceGateCheck,
    decision: &DecisionCapture,
) -> ShadowResult<RuntimeExecutionCapture> {
    let runtime_dir = ensure_runtime_dir(root)?;
    let parity_dir = ensure_parity_dir(root)?;
    let jobs_dir = runtime_dir.join("jobs").join(&decision.input_hash);
    fs::create_dir_all(&jobs_dir).map_err(io_err)?;
    let audit_log_path = runtime_audit_log_path(root, Some(kernel_path.to_string_lossy().as_ref()));
    let execution_path = runtime_dir.join("last_execution.json");
    let runtime_event_path = runtime_event_path(root, &decision.input_hash)?;
    let runtime_event_stream_path = runtime_event_stream_path(root)?;
    let parity_stream_path = parity_dir.join("stream.jsonl");
    let parity_report_path = parity_dir.join("latest.json");
    let mut budget_capture = if decision.overall_decision == "allow" {
        reserve_runtime_budget(kernel_path, envelope, decision)?
    } else {
        BudgetReservationCapture {
            reservation_id: String::new(),
            status: "decision_denied".to_string(),
            reason: format!(
                "effective decision denied before runtime reservation via {} ({})",
                decision.effective_stage, decision.effective_reason
            ),
        }
    };
    let worker_capture = if decision.overall_decision != "allow" {
        run_worker_supervisor(root, envelope, decision)?
    } else if budget_capture.status == "reservation_denied" {
        let worker_log_path = jobs_dir.join("worker.log");
        fs::write(
            &worker_log_path,
            format!(
                "worker_not_dispatched budget_reservation_denied reason={}\n",
                budget_capture.reason
            ),
        )
        .map_err(io_err)?;
        WorkerExecutionCapture {
            worker_request_path: jobs_dir.join("request.json"),
            worker_result_path: jobs_dir.join("result.json"),
            worker_log_path,
            worker_status: "not_dispatched".to_string(),
            worker_kind: "python_reference_worker".to_string(),
            worker_note: format!(
                "runtime budget reservation denied before dispatch: {}",
                budget_capture.reason
            ),
            runtime_outcome: "budget_reservation_denied".to_string(),
        }
    } else {
        run_worker_supervisor(root, envelope, decision)?
    };
    let (
        reference_probe_path,
        reference_probe_stream_path,
        reference_probe_status,
        reference_probe_note,
    ) = capture_reference_probe(root, &decision.input_hash)?;
    write_reference_parity_artifacts(root, envelope, decision, reference)?;
    if budget_capture.status == "reserved" {
        budget_capture = if worker_capture.runtime_outcome == "worker_executed" {
            finalize_runtime_budget(
                kernel_path,
                &budget_capture.reservation_id,
                envelope.estimated_cost_usd,
                true,
                "runtime worker completed",
            )?
        } else {
            finalize_runtime_budget(
                kernel_path,
                &budget_capture.reservation_id,
                envelope.estimated_cost_usd,
                false,
                &worker_capture.runtime_outcome,
            )?
        };
    }
    let runtime_outcome = worker_capture.runtime_outcome.clone();
    let audit_emission_status = emit_runtime_audit(
        kernel_path,
        &audit_log_path,
        envelope,
        decision,
        &runtime_outcome,
        &worker_capture,
        &budget_capture,
    )?;
    let economy_hook_status = emit_economy_hook(
        kernel_path,
        envelope,
        decision,
        &runtime_outcome,
        &budget_capture,
    );
    let reference_decision = if reference.allowed { "allow" } else { "deny" }.to_string();
    let effective_runtime_decision =
        if worker_capture.runtime_outcome == "budget_reservation_denied" {
            "deny".to_string()
        } else {
            decision.overall_decision.clone()
        };
    let parity_status = if reference_decision == effective_runtime_decision {
        "match".to_string()
    } else {
        "divergence".to_string()
    };
    let parity_reason = if parity_status == "match" {
        format!(
            "reference and loom agreed on {} at stage {}",
            decision.overall_decision, decision.reference_stage
        )
    } else {
        format!(
            "reference returned {} at stage {} while loom enforced {} via {}",
            reference_decision,
            decision.reference_stage,
            decision.overall_decision,
            decision.effective_stage
        )
    };

    let stream_timestamp = timestamp_now();
    append_line(
        &parity_stream_path,
        &format!(
            "{{\"timestamp\":{},\"source\":\"reference_stream\",\"phase\":\"reference_gate\",\"hook_name\":{},\"decision\":{},\"stage\":{},\"agent_id\":{},\"org_id\":{},\"input_hash\":{},\"reason\":{}}}\n",
            json_string(&stream_timestamp),
            json_string(&decision.reference_stage),
            json_string(&reference_decision),
            json_string(&decision.reference_stage),
            json_string(&decision.agent_id),
            json_string(&decision.org_id),
            json_string(&decision.input_hash),
            json_string(&decision.reference_reason),
        ),
    )?;
    append_line(
        &parity_stream_path,
        &format!(
            "{{\"timestamp\":{},\"source\":\"loom_runtime_stream\",\"phase\":\"worker_supervisor\",\"hook_name\":{},\"decision\":{},\"stage\":{},\"agent_id\":{},\"org_id\":{},\"input_hash\":{},\"reason\":{},\"worker_status\":{},\"worker_kind\":{},\"worker_result_path\":{}}}\n",
            json_string(&stream_timestamp),
            json_string(&decision.effective_stage),
            json_string(&decision.overall_decision),
            json_string(&decision.effective_stage),
            json_string(&decision.agent_id),
            json_string(&decision.org_id),
            json_string(&decision.input_hash),
            json_string(&decision.effective_reason),
            json_string(&worker_capture.worker_status),
            json_string(&worker_capture.worker_kind),
            json_string(&worker_capture.worker_result_path.display().to_string()),
        ),
    )?;
    append_line(
        &parity_stream_path,
        &format!(
            "{{\"timestamp\":{},\"source\":\"loom_runtime_stream\",\"phase\":\"audit_emission\",\"hook_name\":\"audit_emission\",\"decision\":{},\"stage\":\"runtime_audit\",\"agent_id\":{},\"org_id\":{},\"input_hash\":{},\"reason\":{},\"audit_log\":{}}}\n",
            json_string(&stream_timestamp),
            json_string(&audit_emission_status),
            json_string(&decision.agent_id),
            json_string(&decision.org_id),
            json_string(&decision.input_hash),
            json_string(&runtime_outcome),
            json_string(&audit_log_path.display().to_string()),
        ),
    )?;
    append_line(
        &parity_stream_path,
        &format!(
            "{{\"timestamp\":{},\"source\":\"reference_probe\",\"phase\":\"live_runtime_probe\",\"hook_name\":\"runtime_health\",\"decision\":{},\"stage\":\"live_single_host_reference\",\"agent_id\":{},\"org_id\":{},\"input_hash\":{},\"reason\":{},\"probe_path\":{},\"probe_stream_path\":{}}}\n",
            json_string(&stream_timestamp),
            json_string(&reference_probe_status),
            json_string(&decision.agent_id),
            json_string(&decision.org_id),
            json_string(&decision.input_hash),
            json_string(&reference_probe_note),
            json_string(
                &reference_probe_path
                    .as_ref()
                    .map(|path| path.display().to_string())
                    .unwrap_or_default()
            ),
            json_string(
                &reference_probe_stream_path
                    .as_ref()
                    .map(|path| path.display().to_string())
                    .unwrap_or_default()
            ),
        ),
    )?;

    let capture = RuntimeExecutionCapture {
        execution_path: execution_path.clone(),
        runtime_event_path: runtime_event_path.clone(),
        runtime_event_stream_path: runtime_event_stream_path.clone(),
        worker_request_path: worker_capture.worker_request_path.clone(),
        worker_result_path: worker_capture.worker_result_path.clone(),
        worker_log_path: worker_capture.worker_log_path.clone(),
        audit_log_path: audit_log_path.clone(),
        parity_stream_path: parity_stream_path.clone(),
        parity_report_path: parity_report_path.clone(),
        reference_probe_path,
        reference_probe_stream_path,
        decision_path: decision.decision_path.clone(),
        input_hash: decision.input_hash.clone(),
        agent_id: decision.agent_id.clone(),
        org_id: decision.org_id.clone(),
        action_type: decision.action_type.clone(),
        resource: decision.resource.clone(),
        estimated_cost_usd: decision.estimated_cost_usd,
        runtime_outcome,
        budget_reservation_id: budget_capture.reservation_id.clone(),
        budget_reservation_status: budget_capture.status.clone(),
        budget_reservation_reason: budget_capture.reason.clone(),
        worker_status: worker_capture.worker_status,
        worker_kind: worker_capture.worker_kind,
        worker_note: worker_capture.worker_note,
        overall_decision: decision.overall_decision.clone(),
        effective_source: decision.effective_source.clone(),
        effective_stage: decision.effective_stage.clone(),
        reference_decision,
        reference_stage: decision.reference_stage.clone(),
        audit_emission_status,
        economy_hook_status: economy_hook_status.unwrap_or_else(|e| format!("error: {}", e)),
        reference_probe_status,
        reference_probe_note,
        parity_status,
        parity_reason,
    };
    let runtime_event = runtime_event_for_capture(&capture);
    write_runtime_event_artifacts(root, &decision.input_hash, &runtime_event)?;
    write_parity_comparison_artifacts(root, &capture, &runtime_event)?;
    fs::write(&execution_path, render_runtime_execution_json(&capture)).map_err(io_err)?;
    fs::write(&parity_report_path, render_parity_report_json(&capture)).map_err(io_err)?;
    let existing_job = read_job_snapshot(root, &decision.input_hash).ok();
    let queue_path = existing_job
        .as_ref()
        .and_then(|snapshot| snapshot.queue_path.clone());
    let queue_bucket = existing_job
        .as_ref()
        .map(|snapshot| snapshot.queue_bucket.clone())
        .unwrap_or_else(|| "(none)".to_string());
    let queued_at = existing_job
        .as_ref()
        .map(|snapshot| snapshot.queued_at.clone())
        .unwrap_or_else(timestamp_now);
    let status = if capture.overall_decision == "allow"
        && capture.worker_status == "completed"
        && capture.runtime_outcome == "worker_executed"
    {
        "completed".to_string()
    } else if capture.overall_decision == "deny" {
        "denied".to_string()
    } else if capture.worker_status == "failed" {
        "failed".to_string()
    } else {
        "runtime_rehearsed".to_string()
    };
    let stage = if queue_bucket.starts_with("processed") || queue_bucket.starts_with("failed") {
        "local_queue_supervisor".to_string()
    } else {
        "runtime_execute".to_string()
    };
    write_job_snapshot(
        root,
        JobSnapshot {
            root: root.to_path_buf(),
            job_id: decision.input_hash.clone(),
            job_path: job_snapshot_path(root, &decision.input_hash),
            status,
            stage,
            queue_bucket,
            queued_at,
            updated_at: timestamp_now(),
            agent_id: decision.agent_id.clone(),
            org_id: decision.org_id.clone(),
            action_type: decision.action_type.clone(),
            resource: decision.resource.clone(),
            estimated_cost_usd: format!("{:.6}", decision.estimated_cost_usd),
            runtime_outcome: capture.runtime_outcome.clone(),
            budget_reservation_id: capture.budget_reservation_id.clone(),
            budget_reservation_status: capture.budget_reservation_status.clone(),
            budget_reservation_reason: capture.budget_reservation_reason.clone(),
            worker_status: capture.worker_status.clone(),
            queue_path,
            decision_path: Some(capture.decision_path.clone()),
            execution_path: Some(capture.execution_path.clone()),
            event_path: Some(capture.runtime_event_path.clone()),
            event_stream_path: Some(capture.runtime_event_stream_path.clone()),
            audit_log_path: Some(capture.audit_log_path.clone()),
            parity_report_path: Some(capture.parity_report_path.clone()),
            reservation_id: String::new(),
            reservation_state: String::new(),
            attempt_count: 0,
            note: if capture.worker_note.is_empty() {
                format!(
                    "runtime execution {} via {}",
                    capture.runtime_outcome, capture.effective_stage
                )
            } else {
                capture.worker_note.clone()
            },
        },
    )?;
    Ok(capture)
}

trait ShadowBackendPlugin {
    fn id(&self) -> &'static str;
    fn run(&self, request: &ShadowRunRequest) -> ShadowResult<ShadowRunCapture>;
}

struct WasmtimeShadowBackendPlugin;
struct CommandShadowBackendPlugin;
struct HttpShadowBackendPlugin;
struct McpShadowBackendPlugin;
struct A2aShadowBackendPlugin;
struct A2aActionShadowBackendPlugin;
struct GrpcActionShadowBackendPlugin;
struct GrpcPhysicalShadowBackendPlugin;

impl ShadowBackendPlugin for WasmtimeShadowBackendPlugin {
    fn id(&self) -> &'static str {
        ShadowBackendKind::Wasmtime.as_str()
    }

    fn run(&self, request: &ShadowRunRequest) -> ShadowResult<ShadowRunCapture> {
        run_shadow_backend_wasmtime(request)
    }
}

impl ShadowBackendPlugin for CommandShadowBackendPlugin {
    fn id(&self) -> &'static str {
        ShadowBackendKind::Command.as_str()
    }

    fn run(&self, request: &ShadowRunRequest) -> ShadowResult<ShadowRunCapture> {
        run_shadow_backend_command(request)
    }
}

impl ShadowBackendPlugin for HttpShadowBackendPlugin {
    fn id(&self) -> &'static str {
        ShadowBackendKind::Http.as_str()
    }

    fn run(&self, request: &ShadowRunRequest) -> ShadowResult<ShadowRunCapture> {
        run_shadow_backend_http(request)
    }
}

impl ShadowBackendPlugin for McpShadowBackendPlugin {
    fn id(&self) -> &'static str {
        ShadowBackendKind::Mcp.as_str()
    }

    fn run(&self, request: &ShadowRunRequest) -> ShadowResult<ShadowRunCapture> {
        run_shadow_backend_mcp(request)
    }
}

impl ShadowBackendPlugin for A2aShadowBackendPlugin {
    fn id(&self) -> &'static str {
        ShadowBackendKind::A2a.as_str()
    }

    fn run(&self, request: &ShadowRunRequest) -> ShadowResult<ShadowRunCapture> {
        run_shadow_backend_a2a(request)
    }
}

impl ShadowBackendPlugin for A2aActionShadowBackendPlugin {
    fn id(&self) -> &'static str {
        ShadowBackendKind::A2aAction.as_str()
    }

    fn run(&self, request: &ShadowRunRequest) -> ShadowResult<ShadowRunCapture> {
        run_shadow_backend_a2a_action(request)
    }
}

impl ShadowBackendPlugin for GrpcActionShadowBackendPlugin {
    fn id(&self) -> &'static str {
        ShadowBackendKind::GrpcAction.as_str()
    }

    fn run(&self, request: &ShadowRunRequest) -> ShadowResult<ShadowRunCapture> {
        run_shadow_backend_grpc_action(request)
    }
}

impl ShadowBackendPlugin for GrpcPhysicalShadowBackendPlugin {
    fn id(&self) -> &'static str {
        ShadowBackendKind::GrpcPhysical.as_str()
    }

    fn run(&self, request: &ShadowRunRequest) -> ShadowResult<ShadowRunCapture> {
        run_shadow_backend_grpc_physical(request)
    }
}

static WASMTIME_SHADOW_BACKEND_PLUGIN: WasmtimeShadowBackendPlugin = WasmtimeShadowBackendPlugin;
static COMMAND_SHADOW_BACKEND_PLUGIN: CommandShadowBackendPlugin = CommandShadowBackendPlugin;
static HTTP_SHADOW_BACKEND_PLUGIN: HttpShadowBackendPlugin = HttpShadowBackendPlugin;
static MCP_SHADOW_BACKEND_PLUGIN: McpShadowBackendPlugin = McpShadowBackendPlugin;
static A2A_SHADOW_BACKEND_PLUGIN: A2aShadowBackendPlugin = A2aShadowBackendPlugin;
static A2A_ACTION_SHADOW_BACKEND_PLUGIN: A2aActionShadowBackendPlugin =
    A2aActionShadowBackendPlugin;
static GRPC_ACTION_SHADOW_BACKEND_PLUGIN: GrpcActionShadowBackendPlugin =
    GrpcActionShadowBackendPlugin;
static GRPC_PHYSICAL_SHADOW_BACKEND_PLUGIN: GrpcPhysicalShadowBackendPlugin =
    GrpcPhysicalShadowBackendPlugin;

fn resolve_shadow_backend_plugin(kind: &ShadowBackendKind) -> &'static dyn ShadowBackendPlugin {
    match kind {
        ShadowBackendKind::Wasmtime => &WASMTIME_SHADOW_BACKEND_PLUGIN,
        ShadowBackendKind::Command => &COMMAND_SHADOW_BACKEND_PLUGIN,
        ShadowBackendKind::Http => &HTTP_SHADOW_BACKEND_PLUGIN,
        ShadowBackendKind::Mcp => &MCP_SHADOW_BACKEND_PLUGIN,
        ShadowBackendKind::A2a => &A2A_SHADOW_BACKEND_PLUGIN,
        ShadowBackendKind::A2aAction => &A2A_ACTION_SHADOW_BACKEND_PLUGIN,
        ShadowBackendKind::GrpcAction => &GRPC_ACTION_SHADOW_BACKEND_PLUGIN,
        ShadowBackendKind::GrpcPhysical => &GRPC_PHYSICAL_SHADOW_BACKEND_PLUGIN,
    }
}

pub fn run_shadow_backend(request: &ShadowRunRequest) -> ShadowResult<ShadowRunCapture> {
    let plugin = resolve_shadow_backend_plugin(&request.backend);
    debug_assert_eq!(plugin.id(), request.backend.as_str());
    plugin.run(request)
}

pub fn render_shadow_run_capture_human(
    capture: &ShadowRunCapture,
    root: &Path,
    kernel_path: &Path,
) -> String {
    format!(
        "Meridian Loom // SHADOW RUN\n===========================\nbackend:              {}\nagent_id:             {}\norg_id:               {}\naction_type:          {}\nresource:             {}\nmodule_name:          {}\nentrypoint:           {}\nentrypoint_result:    {}\nwarrant_binding:      {}\nwarrant_id:           {}\npoge_merkle_root:     {}\npoge_trace_len:       {}\npoge_witness_digest:  {}\nexecution_path:       {}\nshadow_latest_path:   {}\nparity_latest_path:   {}\n\nNext\n====\n1. loom parity report --root {}\n2. loom shadow report --root {}\n3. loom job settle --zk --root {} --kernel-path {}\n",
        capture.backend,
        capture.agent_id,
        capture.org_id,
        capture.action_type,
        capture.resource,
        capture.module_name,
        capture.entrypoint,
        capture
            .entrypoint_result
            .map(|value| value.to_string())
            .unwrap_or_else(|| "null".to_string()),
        capture.warrant_binding_status,
        capture.warrant_id_hex.as_deref().unwrap_or("(none)"),
        capture
            .poge_merkle_root_hex
            .as_deref()
            .unwrap_or("(none)"),
        capture
            .poge_trace_len
            .map(|value| value.to_string())
            .unwrap_or_else(|| "0".to_string()),
        capture
            .poge_witness_digest_hex
            .as_deref()
            .unwrap_or("(none)"),
        capture.execution_path.display(),
        capture.shadow_latest_path.display(),
        capture.parity_latest_path.display(),
        root.display(),
        root.display(),
        root.display(),
        kernel_path.display(),
    )
}

pub fn render_shadow_run_capture_json(capture: &ShadowRunCapture) -> String {
    serde_json::to_string_pretty(&shadow_run_capture_value(capture))
        .unwrap_or_else(|_| "{}".to_string())
}

fn run_shadow_backend_wasmtime(request: &ShadowRunRequest) -> ShadowResult<ShadowRunCapture> {
    let host = WasmHostBuilder::new()
        .with_profile_name("shadow/wasmtime".to_string())
        .with_backend(HostBackend::WasmtimeReady)
        .build()
        .map_err(|errors| format!("invalid wasm host config: {}", errors.join("; ")))?;
    let session_label = format!(
        "shadow:{}:{}:{}",
        request.org_id, request.agent_id, request.action_type
    );
    let start_ms = current_epoch_ms();
    let mut interceptor = PoGEInterceptor::new_validated(
        request.warrant.clone(),
        shadow_wasmtime_module_digest(&request.module_name, &request.wasm_bytes),
        session_label.clone(),
        start_ms,
    )
    .map_err(|error| format!("invalid kernel warrant: {}", error))?;
    let result = run_wasm_guest(&WasmExecutionRequest {
        host,
        source: WasmGuestSource::WasmBytes {
            name: request.module_name.clone(),
            bytes: request.wasm_bytes.clone(),
        },
        entrypoint: request.entrypoint.clone(),
        entrypoint_args: vec![],
        memory_probe: None,
        fuel_budget: request.fuel_budget,
    })?;
    let end_ms = current_epoch_ms();
    let response_json = result
        .host_response_json
        .clone()
        .unwrap_or_else(|| "null".to_string());
    let host_calls = if result.host_calls.is_empty() {
        vec!["loom.wasm.execute".to_string()]
    } else {
        result.host_calls.clone()
    };
    for host_call in &host_calls {
        interceptor
            .record_event(
                HostCallKind::Extension,
                end_ms,
                host_call.as_bytes(),
                response_json.as_bytes(),
                result.entrypoint_result.unwrap_or(0) != 0,
            )
            .map_err(|error| error.to_string())?;
    }
    let audit_root = interceptor.finalize().map_err(|error| error.to_string())?;

    let runtime_dir = ensure_runtime_dir(&request.root)?;
    let shadow_dir = ensure_shadow_dir(&request.root)?;
    let parity_dir = ensure_parity_dir(&request.root)?;
    let execution_path = runtime_dir.join("last_execution.json");
    let shadow_latest_path = shadow_dir.join("latest.json");
    let parity_latest_path = parity_dir.join("latest.json");
    let parity_stream_path = parity_dir.join("stream.jsonl");

    let capture = ShadowRunCapture {
        execution_path: execution_path.clone(),
        shadow_latest_path: shadow_latest_path.clone(),
        parity_latest_path: parity_latest_path.clone(),
        parity_stream_path: parity_stream_path.clone(),
        status: "shadow_run_captured".to_string(),
        captured_at: timestamp_now(),
        backend: request.backend.as_str().to_string(),
        agent_id: request.agent_id.clone(),
        org_id: request.org_id.clone(),
        action_type: request.action_type.clone(),
        resource: request.resource.clone(),
        module_name: result.module_name,
        entrypoint: result.entrypoint,
        entrypoint_result: result.entrypoint_result,
        host_backend: result.host_backend,
        warrant_binding_status: "verified".to_string(),
        warrant_id_hex: Some(format!("0x{}", hex::encode(audit_root.warrant_id))),
        poge_merkle_root_hex: Some(audit_root.merkle_root_hex()),
        poge_trace_len: Some(audit_root.trace_len),
        poge_witness_digest_hex: Some(audit_root.witness_digest_hex()),
        poge_session_label: Some(audit_root.session_label.clone()),
        poge_epoch_start_ms: Some(audit_root.epoch_start_ms),
        poge_epoch_end_ms: Some(audit_root.epoch_end_ms),
        poge_module_digest_hex: Some(format!("0x{}", hex::encode(audit_root.module_digest))),
        host_calls,
        host_response_json: Some(response_json),
    };

    persist_shadow_run_capture(&capture)?;
    Ok(capture)
}

fn run_shadow_backend_command(request: &ShadowRunRequest) -> ShadowResult<ShadowRunCapture> {
    let program = request
        .command_program
        .as_ref()
        .ok_or_else(|| "shadow command backend requires command_program".to_string())?;
    let session_label = format!(
        "shadow:{}:{}:{}",
        request.org_id, request.agent_id, request.action_type
    );
    let start_ms = current_epoch_ms();
    let mut interceptor = PoGEInterceptor::new_validated(
        request.warrant.clone(),
        shadow_command_module_digest(program, &request.command_args),
        session_label.clone(),
        start_ms,
    )
    .map_err(|error| format!("invalid kernel warrant: {}", error))?;
    let command_request_json = serde_json::json!({
        "program": program,
        "args": request.command_args,
    });
    let command_input_bytes = serde_json::to_vec(&command_request_json).map_err(io_err)?;
    let output = Command::new(program)
        .args(&request.command_args)
        .output()
        .map_err(|error| format!("failed to execute external command {}: {}", program, error))?;
    let exit_code = output.status.code();
    let response_payload = serde_json::json!({
        "status": if output.status.success() { "ok" } else { "error" },
        "exit_code": exit_code,
        "stdout": String::from_utf8_lossy(&output.stdout),
        "stderr": String::from_utf8_lossy(&output.stderr),
    });
    let response_json = serde_json::to_string_pretty(&response_payload).map_err(io_err)?;
    interceptor
        .record_event(
            HostCallKind::Extension,
            start_ms,
            &command_input_bytes,
            response_json.as_bytes(),
            !output.status.success(),
        )
        .map_err(|error| error.to_string())?;
    let audit_root = interceptor.finalize().map_err(|error| error.to_string())?;
    let capture = ShadowRunCapture {
        execution_path: ensure_runtime_dir(&request.root)?.join("last_execution.json"),
        shadow_latest_path: ensure_shadow_dir(&request.root)?.join("latest.json"),
        parity_latest_path: ensure_parity_dir(&request.root)?.join("latest.json"),
        parity_stream_path: ensure_parity_dir(&request.root)?.join("stream.jsonl"),
        status: "shadow_run_captured".to_string(),
        captured_at: timestamp_now(),
        backend: request.backend.as_str().to_string(),
        agent_id: request.agent_id.clone(),
        org_id: request.org_id.clone(),
        action_type: request.action_type.clone(),
        resource: request.resource.clone(),
        module_name: request.module_name.clone(),
        entrypoint: request.entrypoint.clone(),
        entrypoint_result: exit_code,
        host_backend: "external_command".to_string(),
        warrant_binding_status: "verified".to_string(),
        warrant_id_hex: Some(format!("0x{}", hex::encode(audit_root.warrant_id))),
        poge_merkle_root_hex: Some(audit_root.merkle_root_hex()),
        poge_trace_len: Some(audit_root.trace_len),
        poge_witness_digest_hex: Some(audit_root.witness_digest_hex()),
        poge_session_label: Some(audit_root.session_label.clone()),
        poge_epoch_start_ms: Some(audit_root.epoch_start_ms),
        poge_epoch_end_ms: Some(audit_root.epoch_end_ms),
        poge_module_digest_hex: Some(format!("0x{}", hex::encode(audit_root.module_digest))),
        host_calls: vec!["command.exec".to_string()],
        host_response_json: Some(response_json),
    };

    persist_shadow_run_capture(&capture)?;
    Ok(capture)
}

fn run_shadow_backend_http(request: &ShadowRunRequest) -> ShadowResult<ShadowRunCapture> {
    let url = request
        .http_url
        .as_ref()
        .ok_or_else(|| "shadow http backend requires http_url".to_string())?;
    let method = request
        .http_method
        .as_deref()
        .unwrap_or("GET")
        .trim()
        .to_uppercase();
    let session_label = format!(
        "shadow:{}:{}:{}",
        request.org_id, request.agent_id, request.action_type
    );
    let start_ms = current_epoch_ms();
    let mut interceptor = PoGEInterceptor::new_validated(
        request.warrant.clone(),
        shadow_http_module_digest(
            &method,
            url,
            &request.http_headers,
            request.http_body_json.as_deref(),
        ),
        session_label.clone(),
        start_ms,
    )
    .map_err(|error| format!("invalid kernel warrant: {}", error))?;
    let request_payload = serde_json::json!({
        "method": method,
        "url": url,
        "headers": request.http_headers,
        "body_json": request.http_body_json,
    });
    let request_bytes = serde_json::to_vec(&request_payload).map_err(io_err)?;

    let timeout_ms = 5_000_u64;
    let response_limit = 65_536_u64;
    let mut response = match method.as_str() {
        "GET" => {
            let mut builder = ureq::get(url)
                .config()
                .timeout_global(Some(Duration::from_millis(timeout_ms)))
                .http_status_as_error(false)
                .build();
            for (header_name, header_value) in &request.http_headers {
                builder = builder.header(header_name, header_value);
            }
            builder.call()
        }
        "POST" => {
            let mut builder = ureq::post(url)
                .config()
                .timeout_global(Some(Duration::from_millis(timeout_ms)))
                .http_status_as_error(false)
                .build();
            for (header_name, header_value) in &request.http_headers {
                builder = builder.header(header_name, header_value);
            }
            if request.http_body_json.is_some() {
                builder = builder.header("content-type", "application/json");
            }
            builder.send(request.http_body_json.clone().unwrap_or_default())
        }
        other => {
            return Err(format!(
                "shadow http backend currently supports GET|POST, got '{}'",
                other
            ));
        }
    }
    .map_err(|error| {
        format!(
            "failed to execute external http request {} {}: {}",
            method, url, error
        )
    })?;

    let http_status = response.status().as_u16();
    let final_url = response.get_uri().to_string();
    let content_type = response
        .headers()
        .get("content-type")
        .map(|value| String::from_utf8_lossy(value.as_bytes()).into_owned())
        .unwrap_or_default();
    let body_excerpt = response
        .body_mut()
        .with_config()
        .limit(response_limit)
        .lossy_utf8(true)
        .read_to_string()
        .unwrap_or_else(|error| format!("[body read failed: {error}]"));
    let response_payload = serde_json::json!({
        "status": if (200..400).contains(&http_status) { "ok" } else { "error" },
        "method": method,
        "url": url,
        "final_url": final_url,
        "http_status": http_status,
        "content_type": content_type,
        "body_excerpt_utf8": body_excerpt,
    });
    let response_json = serde_json::to_string_pretty(&response_payload).map_err(io_err)?;
    interceptor
        .record_event(
            HostCallKind::WebFetch,
            start_ms,
            &request_bytes,
            response_json.as_bytes(),
            !(200..400).contains(&http_status),
        )
        .map_err(|error| error.to_string())?;
    let audit_root = interceptor.finalize().map_err(|error| error.to_string())?;
    let capture = ShadowRunCapture {
        execution_path: ensure_runtime_dir(&request.root)?.join("last_execution.json"),
        shadow_latest_path: ensure_shadow_dir(&request.root)?.join("latest.json"),
        parity_latest_path: ensure_parity_dir(&request.root)?.join("latest.json"),
        parity_stream_path: ensure_parity_dir(&request.root)?.join("stream.jsonl"),
        status: "shadow_run_captured".to_string(),
        captured_at: timestamp_now(),
        backend: request.backend.as_str().to_string(),
        agent_id: request.agent_id.clone(),
        org_id: request.org_id.clone(),
        action_type: request.action_type.clone(),
        resource: request.resource.clone(),
        module_name: request.module_name.clone(),
        entrypoint: request.entrypoint.clone(),
        entrypoint_result: Some(http_status as i32),
        host_backend: "external_http".to_string(),
        warrant_binding_status: "verified".to_string(),
        warrant_id_hex: Some(format!("0x{}", hex::encode(audit_root.warrant_id))),
        poge_merkle_root_hex: Some(audit_root.merkle_root_hex()),
        poge_trace_len: Some(audit_root.trace_len),
        poge_witness_digest_hex: Some(audit_root.witness_digest_hex()),
        poge_session_label: Some(audit_root.session_label.clone()),
        poge_epoch_start_ms: Some(audit_root.epoch_start_ms),
        poge_epoch_end_ms: Some(audit_root.epoch_end_ms),
        poge_module_digest_hex: Some(format!("0x{}", hex::encode(audit_root.module_digest))),
        host_calls: vec!["http.fetch".to_string()],
        host_response_json: Some(response_json),
    };

    persist_shadow_run_capture(&capture)?;
    Ok(capture)
}

fn run_shadow_backend_mcp(request: &ShadowRunRequest) -> ShadowResult<ShadowRunCapture> {
    let url = request
        .http_url
        .as_deref()
        .ok_or_else(|| "shadow mcp backend requires http_url".to_string())?;
    let request_json = request
        .http_body_json
        .as_deref()
        .ok_or_else(|| "shadow mcp backend requires mcp request body".to_string())?;
    let request_payload: Value = serde_json::from_str(request_json)
        .map_err(|error| format!("invalid mcp request json: {error}"))?;
    let mcp_method = request_payload
        .get("method")
        .and_then(Value::as_str)
        .unwrap_or("unknown")
        .to_string();
    let mcp_request_id = request_payload
        .get("id")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let timeout_ms = 5_000_u64;
    let response_limit = 32 * 1024;

    let mut interceptor = PoGEInterceptor::new(
        request.warrant.clone(),
        shadow_mcp_module_digest(url, &request.http_headers, request_json),
        format!(
            "shadow:{}:{}:{}:{}",
            request.org_id, request.agent_id, request.action_type, request.resource
        ),
    );

    let request_bytes = request_json.as_bytes().to_vec();
    let start_ms = current_epoch_ms();
    let mut builder = ureq::post(url)
        .config()
        .timeout_global(Some(Duration::from_millis(timeout_ms)))
        .http_status_as_error(false)
        .build();
    let mut has_content_type = false;
    for (header_name, header_value) in &request.http_headers {
        if header_name.eq_ignore_ascii_case("content-type") {
            has_content_type = true;
        }
        builder = builder.header(header_name, header_value);
    }
    if !has_content_type {
        builder = builder.header("content-type", "application/json");
    }
    let mut response = builder.send(request_json.to_string()).map_err(|error| {
        format!(
            "failed to execute external mcp request POST {}: {}",
            url, error
        )
    })?;

    let http_status = response.status().as_u16();
    let final_url = response.get_uri().to_string();
    let content_type = response
        .headers()
        .get("content-type")
        .map(|value| String::from_utf8_lossy(value.as_bytes()).into_owned())
        .unwrap_or_default();
    let body_excerpt = response
        .body_mut()
        .with_config()
        .limit(response_limit)
        .lossy_utf8(true)
        .read_to_string()
        .unwrap_or_else(|error| format!("[body read failed: {error}]"));
    let response_payload = serde_json::json!({
        "status": if (200..400).contains(&http_status) { "ok" } else { "error" },
        "url": url,
        "final_url": final_url,
        "http_status": http_status,
        "content_type": content_type,
        "mcp_method": mcp_method,
        "mcp_request_id": mcp_request_id,
        "body_excerpt_utf8": body_excerpt,
    });
    let response_json = serde_json::to_string_pretty(&response_payload).map_err(io_err)?;
    interceptor
        .record_event(
            HostCallKind::WebFetch,
            start_ms,
            &request_bytes,
            response_json.as_bytes(),
            !(200..400).contains(&http_status),
        )
        .map_err(|error| error.to_string())?;
    let audit_root = interceptor.finalize().map_err(|error| error.to_string())?;
    let capture = ShadowRunCapture {
        execution_path: ensure_runtime_dir(&request.root)?.join("last_execution.json"),
        shadow_latest_path: ensure_shadow_dir(&request.root)?.join("latest.json"),
        parity_latest_path: ensure_parity_dir(&request.root)?.join("latest.json"),
        parity_stream_path: ensure_parity_dir(&request.root)?.join("stream.jsonl"),
        status: "shadow_run_captured".to_string(),
        captured_at: timestamp_now(),
        backend: request.backend.as_str().to_string(),
        agent_id: request.agent_id.clone(),
        org_id: request.org_id.clone(),
        action_type: request.action_type.clone(),
        resource: request.resource.clone(),
        module_name: request.module_name.clone(),
        entrypoint: request.entrypoint.clone(),
        entrypoint_result: Some(http_status as i32),
        host_backend: "external_mcp".to_string(),
        warrant_binding_status: "verified".to_string(),
        warrant_id_hex: Some(format!("0x{}", hex::encode(audit_root.warrant_id))),
        poge_merkle_root_hex: Some(audit_root.merkle_root_hex()),
        poge_trace_len: Some(audit_root.trace_len),
        poge_witness_digest_hex: Some(audit_root.witness_digest_hex()),
        poge_session_label: Some(audit_root.session_label.clone()),
        poge_epoch_start_ms: Some(audit_root.epoch_start_ms),
        poge_epoch_end_ms: Some(audit_root.epoch_end_ms),
        poge_module_digest_hex: Some(format!("0x{}", hex::encode(audit_root.module_digest))),
        host_calls: vec!["mcp.call".to_string()],
        host_response_json: Some(response_json),
    };

    persist_shadow_run_capture(&capture)?;
    Ok(capture)
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct A2aSemanticActionRequest {
    request_id: String,
    action_kind: String,
    action_objective: String,
    action_skill: String,
    actor_agent_id: String,
    actor_org_id: String,
    governance_warrant_id_hex: String,
}

fn parse_semantic_a2a_action_request(request_json: &str) -> ShadowResult<A2aSemanticActionRequest> {
    let request_payload: Value = serde_json::from_str(request_json)
        .map_err(|error| format!("invalid a2a action request json: {error}"))?;
    let schema = value_string(request_payload.get("schema"));
    if schema != "meridian.a2a.action.v1" {
        return Err(format!(
            "invalid a2a action schema '{}': expected meridian.a2a.action.v1",
            schema
        ));
    }
    let request_id = value_string(request_payload.get("request_id"));
    if request_id.is_empty() {
        return Err("a2a action request missing request_id".to_string());
    }
    let actor = request_payload
        .get("actor")
        .and_then(Value::as_object)
        .ok_or_else(|| "a2a action request missing actor object".to_string())?;
    let actor_agent_id = value_string(actor.get("agent_id"));
    let actor_org_id = value_string(actor.get("org_id"));
    if actor_agent_id.is_empty() || actor_org_id.is_empty() {
        return Err("a2a action actor requires non-empty agent_id and org_id".to_string());
    }
    let action = request_payload
        .get("action")
        .and_then(Value::as_object)
        .ok_or_else(|| "a2a action request missing action object".to_string())?;
    let action_kind = value_string(action.get("kind"));
    let action_objective = value_string(action.get("objective"));
    if action_kind.is_empty() || action_objective.is_empty() {
        return Err("a2a action requires non-empty action.kind and action.objective".to_string());
    }
    let action_skill = value_string(action.get("skill"));
    let governance = request_payload
        .get("governance")
        .and_then(Value::as_object)
        .ok_or_else(|| "a2a action request missing governance object".to_string())?;
    let governance_warrant_id_hex = value_string(governance.get("warrant_id_hex"));
    if governance_warrant_id_hex.is_empty() {
        return Err("a2a action governance requires warrant_id_hex".to_string());
    }
    Ok(A2aSemanticActionRequest {
        request_id,
        action_kind,
        action_objective,
        action_skill,
        actor_agent_id,
        actor_org_id,
        governance_warrant_id_hex,
    })
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct EmbodiedPhysicalActionRequest {
    request_id: String,
    action_kind: String,
    action_objective: String,
    action_skill: String,
    actor_agent_id: String,
    actor_org_id: String,
    governance_warrant_id_hex: String,
    physical_robot_id: String,
    physical_target: String,
    physical_command: String,
    physical_safety_class: String,
    physical_dry_run: bool,
    lifecycle_mode: String,
    lifecycle_ack_required: bool,
    lifecycle_ack_timeout_seconds: Option<u64>,
    lifecycle_cancel_on_ack_timeout: bool,
    lifecycle_cancel_after_seconds: Option<u64>,
    remediation_profile: String,
}

fn parse_semantic_embodied_physical_request(
    request_json: &str,
) -> ShadowResult<EmbodiedPhysicalActionRequest> {
    let request_payload: Value = serde_json::from_str(request_json)
        .map_err(|error| format!("invalid embodied physical request json: {error}"))?;
    let schema = value_string(request_payload.get("schema"));
    if schema != "meridian.embodied.action.v1" {
        return Err(format!(
            "invalid embodied physical schema '{}': expected meridian.embodied.action.v1",
            schema
        ));
    }
    let request_id = value_string(request_payload.get("request_id"));
    if request_id.is_empty() {
        return Err("embodied physical request missing request_id".to_string());
    }
    let actor = request_payload
        .get("actor")
        .and_then(Value::as_object)
        .ok_or_else(|| "embodied physical request missing actor object".to_string())?;
    let actor_agent_id = value_string(actor.get("agent_id"));
    let actor_org_id = value_string(actor.get("org_id"));
    if actor_agent_id.is_empty() || actor_org_id.is_empty() {
        return Err("embodied physical actor requires non-empty agent_id and org_id".to_string());
    }
    let action = request_payload
        .get("action")
        .and_then(Value::as_object)
        .ok_or_else(|| "embodied physical request missing action object".to_string())?;
    let action_kind = value_string(action.get("kind"));
    let action_objective = value_string(action.get("objective"));
    if action_kind.is_empty() || action_objective.is_empty() {
        return Err(
            "embodied physical request requires non-empty action.kind and action.objective"
                .to_string(),
        );
    }
    let action_skill = value_string(action.get("skill"));
    let physical = request_payload
        .get("physical")
        .and_then(Value::as_object)
        .ok_or_else(|| "embodied physical request missing physical object".to_string())?;
    let physical_robot_id = value_string(physical.get("robot_id"));
    let physical_target = value_string(physical.get("target"));
    let physical_command = value_string(physical.get("command"));
    let physical_safety_class = value_string(physical.get("safety_class"));
    let physical_dry_run = physical
        .get("dry_run")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if physical_robot_id.is_empty()
        || physical_target.is_empty()
        || physical_command.is_empty()
        || physical_safety_class.is_empty()
    {
        return Err(
            "embodied physical request requires non-empty robot_id/target/command/safety_class"
                .to_string(),
        );
    }
    let lifecycle = request_payload
        .get("lifecycle")
        .and_then(Value::as_object)
        .ok_or_else(|| "embodied physical request missing lifecycle object".to_string())?;
    let lifecycle_mode = value_string(lifecycle.get("mode"));
    if lifecycle_mode != "unary" && lifecycle_mode != "stream" {
        return Err(format!(
            "embodied physical lifecycle mode must be unary|stream, got '{}'",
            lifecycle_mode
        ));
    }
    let lifecycle_ack_required = lifecycle
        .get("ack_required")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let lifecycle_ack_timeout_seconds =
        lifecycle.get("ack_timeout_seconds").and_then(Value::as_u64);
    let lifecycle_cancel_on_ack_timeout = lifecycle
        .get("cancel_on_ack_timeout")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let lifecycle_cancel_after_seconds = lifecycle
        .get("cancel_after_seconds")
        .and_then(Value::as_u64);
    let remediation_profile = request_payload
        .get("remediation")
        .and_then(Value::as_object)
        .map(|value| value_string(value.get("profile")))
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "standard".to_string());
    let governance = request_payload
        .get("governance")
        .and_then(Value::as_object)
        .ok_or_else(|| "embodied physical request missing governance object".to_string())?;
    let governance_warrant_id_hex = value_string(governance.get("warrant_id_hex"));
    if governance_warrant_id_hex.is_empty() {
        return Err("embodied physical governance requires warrant_id_hex".to_string());
    }
    Ok(EmbodiedPhysicalActionRequest {
        request_id,
        action_kind,
        action_objective,
        action_skill,
        actor_agent_id,
        actor_org_id,
        governance_warrant_id_hex,
        physical_robot_id,
        physical_target,
        physical_command,
        physical_safety_class,
        physical_dry_run,
        lifecycle_mode,
        lifecycle_ack_required,
        lifecycle_ack_timeout_seconds,
        lifecycle_cancel_on_ack_timeout,
        lifecycle_cancel_after_seconds,
        remediation_profile,
    })
}

fn run_shadow_backend_a2a(request: &ShadowRunRequest) -> ShadowResult<ShadowRunCapture> {
    let url = request
        .http_url
        .as_deref()
        .ok_or_else(|| "shadow a2a backend requires http_url".to_string())?;
    let request_json = request
        .http_body_json
        .as_deref()
        .ok_or_else(|| "shadow a2a backend requires a2a request body".to_string())?;
    let request_payload: Value = serde_json::from_str(request_json)
        .map_err(|error| format!("invalid a2a request json: {error}"))?;
    let a2a_method = request_payload
        .get("method")
        .and_then(Value::as_str)
        .unwrap_or("unknown")
        .to_string();
    let a2a_request_id = request_payload
        .get("id")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let a2a_skill = request_payload
        .get("params")
        .and_then(|value| value.get("skill"))
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let timeout_ms = 5_000_u64;
    let response_limit = 32 * 1024;

    let mut interceptor = PoGEInterceptor::new(
        request.warrant.clone(),
        shadow_a2a_module_digest(url, &request.http_headers, request_json),
        format!(
            "shadow:{}:{}:{}:{}",
            request.org_id, request.agent_id, request.action_type, request.resource
        ),
    );

    let request_bytes = request_json.as_bytes().to_vec();
    let start_ms = current_epoch_ms();
    let mut builder = ureq::post(url)
        .config()
        .timeout_global(Some(Duration::from_millis(timeout_ms)))
        .http_status_as_error(false)
        .build();
    let mut has_content_type = false;
    for (header_name, header_value) in &request.http_headers {
        if header_name.eq_ignore_ascii_case("content-type") {
            has_content_type = true;
        }
        builder = builder.header(header_name, header_value);
    }
    if !has_content_type {
        builder = builder.header("content-type", "application/json");
    }
    let mut response = builder.send(request_json.to_string()).map_err(|error| {
        format!(
            "failed to execute external a2a request POST {}: {}",
            url, error
        )
    })?;

    let http_status = response.status().as_u16();
    let final_url = response.get_uri().to_string();
    let content_type = response
        .headers()
        .get("content-type")
        .map(|value| String::from_utf8_lossy(value.as_bytes()).into_owned())
        .unwrap_or_default();
    let body_excerpt = response
        .body_mut()
        .with_config()
        .limit(response_limit)
        .lossy_utf8(true)
        .read_to_string()
        .unwrap_or_else(|error| format!("[body read failed: {error}]"));
    let response_payload = serde_json::json!({
        "status": if (200..400).contains(&http_status) { "ok" } else { "error" },
        "url": url,
        "final_url": final_url,
        "http_status": http_status,
        "content_type": content_type,
        "a2a_method": a2a_method,
        "a2a_request_id": a2a_request_id,
        "a2a_skill": a2a_skill,
        "body_excerpt_utf8": body_excerpt,
    });
    let response_json = serde_json::to_string_pretty(&response_payload).map_err(io_err)?;
    interceptor
        .record_event(
            HostCallKind::WebFetch,
            start_ms,
            &request_bytes,
            response_json.as_bytes(),
            !(200..400).contains(&http_status),
        )
        .map_err(|error| error.to_string())?;
    let audit_root = interceptor.finalize().map_err(|error| error.to_string())?;
    let host_call = if a2a_method.starts_with("message/") {
        "a2a.message"
    } else {
        "a2a.call"
    };
    let capture = ShadowRunCapture {
        execution_path: ensure_runtime_dir(&request.root)?.join("last_execution.json"),
        shadow_latest_path: ensure_shadow_dir(&request.root)?.join("latest.json"),
        parity_latest_path: ensure_parity_dir(&request.root)?.join("latest.json"),
        parity_stream_path: ensure_parity_dir(&request.root)?.join("stream.jsonl"),
        status: "shadow_run_captured".to_string(),
        captured_at: timestamp_now(),
        backend: request.backend.as_str().to_string(),
        agent_id: request.agent_id.clone(),
        org_id: request.org_id.clone(),
        action_type: request.action_type.clone(),
        resource: request.resource.clone(),
        module_name: request.module_name.clone(),
        entrypoint: request.entrypoint.clone(),
        entrypoint_result: Some(http_status as i32),
        host_backend: "external_a2a".to_string(),
        warrant_binding_status: "verified".to_string(),
        warrant_id_hex: Some(format!("0x{}", hex::encode(audit_root.warrant_id))),
        poge_merkle_root_hex: Some(audit_root.merkle_root_hex()),
        poge_trace_len: Some(audit_root.trace_len),
        poge_witness_digest_hex: Some(audit_root.witness_digest_hex()),
        poge_session_label: Some(audit_root.session_label.clone()),
        poge_epoch_start_ms: Some(audit_root.epoch_start_ms),
        poge_epoch_end_ms: Some(audit_root.epoch_end_ms),
        poge_module_digest_hex: Some(format!("0x{}", hex::encode(audit_root.module_digest))),
        host_calls: vec![host_call.to_string()],
        host_response_json: Some(response_json),
    };

    persist_shadow_run_capture(&capture)?;
    Ok(capture)
}

fn run_shadow_backend_a2a_action(request: &ShadowRunRequest) -> ShadowResult<ShadowRunCapture> {
    let url = request
        .http_url
        .as_deref()
        .ok_or_else(|| "shadow a2a_action backend requires http_url".to_string())?;
    let request_json = request.http_body_json.as_deref().ok_or_else(|| {
        "shadow a2a_action backend requires semantic action request body".to_string()
    })?;
    let action_request = parse_semantic_a2a_action_request(request_json)?;
    if action_request.actor_agent_id != request.agent_id
        || action_request.actor_org_id != request.org_id
    {
        return Err(format!(
            "a2a action actor mismatch: payload actor={}/{} but run requested {}/{}",
            action_request.actor_agent_id,
            action_request.actor_org_id,
            request.agent_id,
            request.org_id
        ));
    }
    let expected_warrant = format!("0x{}", hex::encode(request.warrant.id));
    if !action_request
        .governance_warrant_id_hex
        .trim()
        .eq_ignore_ascii_case(&expected_warrant)
    {
        return Err(format!(
            "a2a action warrant mismatch: payload={} expected={}",
            action_request.governance_warrant_id_hex, expected_warrant
        ));
    }

    let timeout_ms = 5_000_u64;
    let response_limit = 32 * 1024;
    let mut interceptor = PoGEInterceptor::new(
        request.warrant.clone(),
        shadow_a2a_action_module_digest(url, &request.http_headers, request_json),
        format!(
            "shadow:{}:{}:{}:{}",
            request.org_id, request.agent_id, request.action_type, request.resource
        ),
    );

    let request_bytes = request_json.as_bytes().to_vec();
    let start_ms = current_epoch_ms();
    let mut builder = ureq::post(url)
        .config()
        .timeout_global(Some(Duration::from_millis(timeout_ms)))
        .http_status_as_error(false)
        .build();
    let mut has_content_type = false;
    for (header_name, header_value) in &request.http_headers {
        if header_name.eq_ignore_ascii_case("content-type") {
            has_content_type = true;
        }
        builder = builder.header(header_name, header_value);
    }
    if !has_content_type {
        builder = builder.header("content-type", "application/json");
    }
    let mut response = builder.send(request_json.to_string()).map_err(|error| {
        format!(
            "failed to execute external a2a semantic action POST {}: {}",
            url, error
        )
    })?;

    let http_status = response.status().as_u16();
    let final_url = response.get_uri().to_string();
    let content_type = response
        .headers()
        .get("content-type")
        .map(|value| String::from_utf8_lossy(value.as_bytes()).into_owned())
        .unwrap_or_default();
    let body_excerpt = response
        .body_mut()
        .with_config()
        .limit(response_limit)
        .lossy_utf8(true)
        .read_to_string()
        .unwrap_or_else(|error| format!("[body read failed: {error}]"));
    let response_payload = serde_json::json!({
        "status": if (200..400).contains(&http_status) { "ok" } else { "error" },
        "url": url,
        "final_url": final_url,
        "http_status": http_status,
        "content_type": content_type,
        "a2a_schema": "meridian.a2a.action.v1",
        "a2a_request_id": action_request.request_id,
        "a2a_action_kind": action_request.action_kind,
        "a2a_action_objective": action_request.action_objective,
        "a2a_action_skill": action_request.action_skill,
        "body_excerpt_utf8": body_excerpt,
    });
    let response_json = serde_json::to_string_pretty(&response_payload).map_err(io_err)?;
    interceptor
        .record_event(
            HostCallKind::WebFetch,
            start_ms,
            &request_bytes,
            response_json.as_bytes(),
            !(200..400).contains(&http_status),
        )
        .map_err(|error| error.to_string())?;
    let audit_root = interceptor.finalize().map_err(|error| error.to_string())?;
    let capture = ShadowRunCapture {
        execution_path: ensure_runtime_dir(&request.root)?.join("last_execution.json"),
        shadow_latest_path: ensure_shadow_dir(&request.root)?.join("latest.json"),
        parity_latest_path: ensure_parity_dir(&request.root)?.join("latest.json"),
        parity_stream_path: ensure_parity_dir(&request.root)?.join("stream.jsonl"),
        status: "shadow_run_captured".to_string(),
        captured_at: timestamp_now(),
        backend: request.backend.as_str().to_string(),
        agent_id: request.agent_id.clone(),
        org_id: request.org_id.clone(),
        action_type: request.action_type.clone(),
        resource: request.resource.clone(),
        module_name: request.module_name.clone(),
        entrypoint: request.entrypoint.clone(),
        entrypoint_result: Some(http_status as i32),
        host_backend: "external_a2a_action".to_string(),
        warrant_binding_status: "verified".to_string(),
        warrant_id_hex: Some(format!("0x{}", hex::encode(audit_root.warrant_id))),
        poge_merkle_root_hex: Some(audit_root.merkle_root_hex()),
        poge_trace_len: Some(audit_root.trace_len),
        poge_witness_digest_hex: Some(audit_root.witness_digest_hex()),
        poge_session_label: Some(audit_root.session_label.clone()),
        poge_epoch_start_ms: Some(audit_root.epoch_start_ms),
        poge_epoch_end_ms: Some(audit_root.epoch_end_ms),
        poge_module_digest_hex: Some(format!("0x{}", hex::encode(audit_root.module_digest))),
        host_calls: vec!["a2a.action.submit".to_string()],
        host_response_json: Some(response_json),
    };

    persist_shadow_run_capture(&capture)?;
    Ok(capture)
}

fn parse_grpc_target_from_url(raw: &str) -> ShadowResult<(String, bool)> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Err("grpc_action target is empty".to_string());
    }
    let (without_scheme, plaintext) = if let Some(rest) = trimmed.strip_prefix("https://") {
        (rest, false)
    } else if let Some(rest) = trimmed.strip_prefix("http://") {
        (rest, true)
    } else if let Some(rest) = trimmed.strip_prefix("grpcs://") {
        (rest, false)
    } else if let Some(rest) = trimmed.strip_prefix("grpc://") {
        (rest, true)
    } else {
        (trimmed, true)
    };
    let target = without_scheme
        .split('/')
        .next()
        .unwrap_or_default()
        .trim()
        .to_string();
    if target.is_empty() {
        return Err(format!(
            "invalid grpc_action target '{}': expected host:port or scheme://host:port",
            raw
        ));
    }
    Ok((target, plaintext))
}

fn run_shadow_backend_grpc_action(request: &ShadowRunRequest) -> ShadowResult<ShadowRunCapture> {
    let target_url = request
        .http_url
        .as_deref()
        .ok_or_else(|| "shadow grpc_action backend requires http_url target".to_string())?;
    let request_json = request.http_body_json.as_deref().ok_or_else(|| {
        "shadow grpc_action backend requires semantic action request body".to_string()
    })?;
    let action_request = parse_semantic_a2a_action_request(request_json)?;
    if action_request.actor_agent_id != request.agent_id
        || action_request.actor_org_id != request.org_id
    {
        return Err(format!(
            "grpc_action actor mismatch: payload actor={}/{} but run requested {}/{}",
            action_request.actor_agent_id,
            action_request.actor_org_id,
            request.agent_id,
            request.org_id
        ));
    }
    let expected_warrant = format!("0x{}", hex::encode(request.warrant.id));
    if !action_request
        .governance_warrant_id_hex
        .trim()
        .eq_ignore_ascii_case(&expected_warrant)
    {
        return Err(format!(
            "grpc_action warrant mismatch: payload={} expected={}",
            action_request.governance_warrant_id_hex, expected_warrant
        ));
    }

    let grpc_rpc = request
        .http_method
        .as_deref()
        .unwrap_or("meridian.runtime.v1.ActionService/SubmitAction")
        .trim()
        .to_string();
    let Some((grpc_service, grpc_method)) = grpc_rpc.split_once('/') else {
        return Err(format!(
            "invalid grpc_action rpc '{}': expected <Service>/<Method>",
            grpc_rpc
        ));
    };
    if grpc_service.trim().is_empty()
        || grpc_method.trim().is_empty()
        || grpc_method.contains('/')
        || grpc_service.contains(' ')
        || grpc_method.contains(' ')
    {
        return Err(format!(
            "invalid grpc_action rpc '{}': expected <Service>/<Method> without spaces",
            grpc_rpc
        ));
    }
    let (grpc_target, inferred_plaintext) = parse_grpc_target_from_url(target_url)?;

    let mut grpc_headers = Vec::new();
    let mut grpc_proto_files = Vec::new();
    let mut grpc_protosets = Vec::new();
    let mut grpc_import_paths = Vec::new();
    let mut grpc_authority = String::new();
    let mut grpc_plaintext_override: Option<bool> = None;
    let mut grpc_allow_unknown_fields = false;
    let mut grpc_max_time_seconds = 5_u64;
    for (name, value) in &request.http_headers {
        let lower = name.to_ascii_lowercase();
        match lower.as_str() {
            "x-loom-grpc-proto" => grpc_proto_files.push(value.clone()),
            "x-loom-grpc-protoset" => grpc_protosets.push(value.clone()),
            "x-loom-grpc-import-path" => grpc_import_paths.push(value.clone()),
            "x-loom-grpc-authority" => {
                grpc_authority = value.trim().to_string();
            }
            "x-loom-grpc-plaintext" => {
                let normalized = value.trim().to_ascii_lowercase();
                if normalized == "true" || normalized == "1" || normalized == "yes" {
                    grpc_plaintext_override = Some(true);
                } else if normalized == "false" || normalized == "0" || normalized == "no" {
                    grpc_plaintext_override = Some(false);
                } else {
                    return Err(format!(
                        "invalid x-loom-grpc-plaintext value '{}': expected true/false",
                        value
                    ));
                }
            }
            "x-loom-grpc-allow-unknown-fields" => {
                let normalized = value.trim().to_ascii_lowercase();
                if normalized == "true" || normalized == "1" || normalized == "yes" {
                    grpc_allow_unknown_fields = true;
                } else if normalized == "false" || normalized == "0" || normalized == "no" {
                    grpc_allow_unknown_fields = false;
                } else {
                    return Err(format!(
                        "invalid x-loom-grpc-allow-unknown-fields value '{}': expected true/false",
                        value
                    ));
                }
            }
            "x-loom-grpc-max-time-seconds" => {
                let parsed = value.trim().parse::<u64>().map_err(|error| {
                    format!(
                        "invalid x-loom-grpc-max-time-seconds value '{}': {}",
                        value, error
                    )
                })?;
                if !(1..=120).contains(&parsed) {
                    return Err(format!(
                        "invalid x-loom-grpc-max-time-seconds value '{}': expected 1..120",
                        value
                    ));
                }
                grpc_max_time_seconds = parsed;
            }
            _ => grpc_headers.push((name.clone(), value.clone())),
        }
    }
    let plaintext = grpc_plaintext_override.unwrap_or(inferred_plaintext);

    let start_ms = current_epoch_ms();
    let mut interceptor = PoGEInterceptor::new_validated(
        request.warrant.clone(),
        shadow_grpc_action_module_digest(
            &grpc_target,
            &grpc_rpc,
            &request.http_headers,
            request_json,
        ),
        format!(
            "shadow:{}:{}:{}:{}",
            request.org_id, request.agent_id, request.action_type, request.resource
        ),
        start_ms,
    )
    .map_err(|error| format!("invalid kernel warrant: {}", error))?;
    let request_bytes = request_json.as_bytes().to_vec();

    let grpcurl_bin =
        std::env::var("LOOM_SHADOW_GRPCURL_BIN").unwrap_or_else(|_| "grpcurl".to_string());
    let mut command = Command::new(&grpcurl_bin);
    command
        .arg("-max-time")
        .arg(grpc_max_time_seconds.to_string());
    if plaintext {
        command.arg("-plaintext");
    }
    if grpc_allow_unknown_fields {
        command.arg("-allow-unknown-fields");
    }
    for (name, value) in &grpc_headers {
        command.arg("-H").arg(format!("{}: {}", name, value));
    }
    if !grpc_authority.is_empty() {
        command.arg("-authority").arg(&grpc_authority);
    }
    for import_path in &grpc_import_paths {
        command.arg("-import-path").arg(import_path);
    }
    for proto in &grpc_proto_files {
        command.arg("-proto").arg(proto);
    }
    for protoset in &grpc_protosets {
        command.arg("-protoset").arg(protoset);
    }
    command.arg("-d").arg(request_json);
    command.arg(&grpc_target).arg(&grpc_rpc);
    let output = command.output().map_err(|error| match error.kind() {
        ErrorKind::NotFound => format!(
            "failed to execute grpc_action: '{}' not found. Install grpcurl or set LOOM_SHADOW_GRPCURL_BIN to a grpcurl-compatible binary",
            grpcurl_bin
        ),
        _ => format!(
            "failed to execute grpc_action via {} for {} {}: {}",
            grpcurl_bin, grpc_target, grpc_rpc, error
        ),
    })?;
    let exit_code = output.status.code();
    let stdout_text = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr_text = String::from_utf8_lossy(&output.stderr).to_string();
    let response_payload = serde_json::json!({
        "status": if output.status.success() { "ok" } else { "error" },
        "grpc_target": grpc_target,
        "grpc_rpc": grpc_rpc,
        "grpc_transport": if plaintext { "plaintext" } else { "tls" },
        "grpc_allow_unknown_fields": grpc_allow_unknown_fields,
        "grpc_max_time_seconds": grpc_max_time_seconds,
        "grpc_schema": "meridian.a2a.action.v1",
        "grpc_request_id": action_request.request_id,
        "grpc_action_kind": action_request.action_kind,
        "grpc_action_objective": action_request.action_objective,
        "grpc_action_skill": action_request.action_skill,
        "grpc_proto_count": grpc_proto_files.len(),
        "grpc_protoset_count": grpc_protosets.len(),
        "grpc_import_path_count": grpc_import_paths.len(),
        "grpc_authority": grpc_authority,
        "exit_code": exit_code,
        "stdout_excerpt_utf8": stdout_text,
        "stderr_excerpt_utf8": stderr_text,
    });
    let response_json = serde_json::to_string_pretty(&response_payload).map_err(io_err)?;
    interceptor
        .record_event(
            HostCallKind::Extension,
            start_ms,
            &request_bytes,
            response_json.as_bytes(),
            !output.status.success(),
        )
        .map_err(|error| error.to_string())?;
    let audit_root = interceptor.finalize().map_err(|error| error.to_string())?;
    let capture = ShadowRunCapture {
        execution_path: ensure_runtime_dir(&request.root)?.join("last_execution.json"),
        shadow_latest_path: ensure_shadow_dir(&request.root)?.join("latest.json"),
        parity_latest_path: ensure_parity_dir(&request.root)?.join("latest.json"),
        parity_stream_path: ensure_parity_dir(&request.root)?.join("stream.jsonl"),
        status: "shadow_run_captured".to_string(),
        captured_at: timestamp_now(),
        backend: request.backend.as_str().to_string(),
        agent_id: request.agent_id.clone(),
        org_id: request.org_id.clone(),
        action_type: request.action_type.clone(),
        resource: request.resource.clone(),
        module_name: request.module_name.clone(),
        entrypoint: request.entrypoint.clone(),
        entrypoint_result: exit_code,
        host_backend: "external_grpc_action".to_string(),
        warrant_binding_status: "verified".to_string(),
        warrant_id_hex: Some(format!("0x{}", hex::encode(audit_root.warrant_id))),
        poge_merkle_root_hex: Some(audit_root.merkle_root_hex()),
        poge_trace_len: Some(audit_root.trace_len),
        poge_witness_digest_hex: Some(audit_root.witness_digest_hex()),
        poge_session_label: Some(audit_root.session_label.clone()),
        poge_epoch_start_ms: Some(audit_root.epoch_start_ms),
        poge_epoch_end_ms: Some(audit_root.epoch_end_ms),
        poge_module_digest_hex: Some(format!("0x{}", hex::encode(audit_root.module_digest))),
        host_calls: vec!["grpc.action.submit".to_string()],
        host_response_json: Some(response_json),
    };

    persist_shadow_run_capture(&capture)?;
    persist_shadow_grpc_action_diagnostics(&request.root, &capture, &response_payload)?;
    Ok(capture)
}

fn run_shadow_backend_grpc_physical(request: &ShadowRunRequest) -> ShadowResult<ShadowRunCapture> {
    let target_url = request
        .http_url
        .as_deref()
        .ok_or_else(|| "shadow grpc_physical backend requires http_url target".to_string())?;
    let request_json = request.http_body_json.as_deref().ok_or_else(|| {
        "shadow grpc_physical backend requires semantic physical request body".to_string()
    })?;
    let action_request = parse_semantic_embodied_physical_request(request_json)?;
    if action_request.actor_agent_id != request.agent_id
        || action_request.actor_org_id != request.org_id
    {
        return Err(format!(
            "grpc_physical actor mismatch: payload actor={}/{} but run requested {}/{}",
            action_request.actor_agent_id,
            action_request.actor_org_id,
            request.agent_id,
            request.org_id
        ));
    }
    let expected_warrant = format!("0x{}", hex::encode(request.warrant.id));
    if !action_request
        .governance_warrant_id_hex
        .trim()
        .eq_ignore_ascii_case(&expected_warrant)
    {
        return Err(format!(
            "grpc_physical warrant mismatch: payload={} expected={}",
            action_request.governance_warrant_id_hex, expected_warrant
        ));
    }

    let grpc_rpc = request
        .http_method
        .as_deref()
        .unwrap_or("meridian.embodied.action.v1.PhysicalActionService/Execute")
        .trim()
        .to_string();
    let Some((grpc_service, grpc_method)) = grpc_rpc.split_once('/') else {
        return Err(format!(
            "invalid grpc_physical rpc '{}': expected <Service>/<Method>",
            grpc_rpc
        ));
    };
    if grpc_service.trim().is_empty()
        || grpc_method.trim().is_empty()
        || grpc_method.contains('/')
        || grpc_service.contains(' ')
        || grpc_method.contains(' ')
    {
        return Err(format!(
            "invalid grpc_physical rpc '{}': expected <Service>/<Method> without spaces",
            grpc_rpc
        ));
    }
    let (grpc_target, inferred_plaintext) = parse_grpc_target_from_url(target_url)?;

    let mut grpc_headers = Vec::new();
    let mut grpc_proto_files = Vec::new();
    let mut grpc_protosets = Vec::new();
    let mut grpc_import_paths = Vec::new();
    let mut grpc_authority = String::new();
    let mut grpc_plaintext_override: Option<bool> = None;
    let mut grpc_allow_unknown_fields = false;
    let mut grpc_max_time_seconds = 5_u64;
    let mut lifecycle_mode = action_request.lifecycle_mode.clone();
    let mut lifecycle_ack_required = action_request.lifecycle_ack_required;
    let mut lifecycle_ack_timeout_seconds = action_request.lifecycle_ack_timeout_seconds;
    let mut lifecycle_cancel_on_ack_timeout = action_request.lifecycle_cancel_on_ack_timeout;
    let mut lifecycle_cancel_after_seconds = action_request.lifecycle_cancel_after_seconds;
    let mut remediation_profile = action_request.remediation_profile.clone();
    for (name, value) in &request.http_headers {
        let lower = name.to_ascii_lowercase();
        match lower.as_str() {
            "x-loom-grpc-proto" => grpc_proto_files.push(value.clone()),
            "x-loom-grpc-protoset" => grpc_protosets.push(value.clone()),
            "x-loom-grpc-import-path" => grpc_import_paths.push(value.clone()),
            "x-loom-grpc-authority" => {
                grpc_authority = value.trim().to_string();
            }
            "x-loom-grpc-plaintext" => {
                let normalized = value.trim().to_ascii_lowercase();
                if normalized == "true" || normalized == "1" || normalized == "yes" {
                    grpc_plaintext_override = Some(true);
                } else if normalized == "false" || normalized == "0" || normalized == "no" {
                    grpc_plaintext_override = Some(false);
                } else {
                    return Err(format!(
                        "invalid x-loom-grpc-plaintext value '{}': expected true/false",
                        value
                    ));
                }
            }
            "x-loom-grpc-allow-unknown-fields" => {
                let normalized = value.trim().to_ascii_lowercase();
                if normalized == "true" || normalized == "1" || normalized == "yes" {
                    grpc_allow_unknown_fields = true;
                } else if normalized == "false" || normalized == "0" || normalized == "no" {
                    grpc_allow_unknown_fields = false;
                } else {
                    return Err(format!(
                        "invalid x-loom-grpc-allow-unknown-fields value '{}': expected true/false",
                        value
                    ));
                }
            }
            "x-loom-grpc-max-time-seconds" => {
                let parsed = value.trim().parse::<u64>().map_err(|error| {
                    format!(
                        "invalid x-loom-grpc-max-time-seconds value '{}': {}",
                        value, error
                    )
                })?;
                if !(1..=120).contains(&parsed) {
                    return Err(format!(
                        "invalid x-loom-grpc-max-time-seconds value '{}': expected 1..120",
                        value
                    ));
                }
                grpc_max_time_seconds = parsed;
            }
            "x-loom-grpc-physical-lifecycle-mode" => {
                lifecycle_mode = value.trim().to_string();
            }
            "x-loom-grpc-physical-ack-required" => {
                let normalized = value.trim().to_ascii_lowercase();
                if normalized == "true" || normalized == "1" || normalized == "yes" {
                    lifecycle_ack_required = true;
                } else if normalized == "false" || normalized == "0" || normalized == "no" {
                    lifecycle_ack_required = false;
                } else {
                    return Err(format!(
                        "invalid x-loom-grpc-physical-ack-required value '{}': expected true/false",
                        value
                    ));
                }
            }
            "x-loom-grpc-physical-ack-timeout-seconds" => {
                let parsed = value.trim().parse::<u64>().map_err(|error| {
                    format!(
                        "invalid x-loom-grpc-physical-ack-timeout-seconds value '{}': {}",
                        value, error
                    )
                })?;
                lifecycle_ack_timeout_seconds = Some(parsed);
            }
            "x-loom-grpc-physical-cancel-on-ack-timeout" => {
                let normalized = value.trim().to_ascii_lowercase();
                if normalized == "true" || normalized == "1" || normalized == "yes" {
                    lifecycle_cancel_on_ack_timeout = true;
                } else if normalized == "false" || normalized == "0" || normalized == "no" {
                    lifecycle_cancel_on_ack_timeout = false;
                } else {
                    return Err(format!(
                        "invalid x-loom-grpc-physical-cancel-on-ack-timeout value '{}': expected true/false",
                        value
                    ));
                }
            }
            "x-loom-grpc-physical-cancel-after-seconds" => {
                let parsed = value.trim().parse::<u64>().map_err(|error| {
                    format!(
                        "invalid x-loom-grpc-physical-cancel-after-seconds value '{}': {}",
                        value, error
                    )
                })?;
                lifecycle_cancel_after_seconds = Some(parsed);
            }
            "x-loom-grpc-physical-remediation-profile" => {
                remediation_profile = value.trim().to_string();
            }
            _ => grpc_headers.push((name.clone(), value.clone())),
        }
    }
    if lifecycle_mode != "unary" && lifecycle_mode != "stream" {
        return Err(format!(
            "grpc_physical lifecycle mode must be unary|stream, got '{}'",
            lifecycle_mode
        ));
    }
    if lifecycle_ack_required && lifecycle_mode != "stream" {
        return Err(
            "grpc_physical lifecycle requires stream mode when ack_required=true".to_string(),
        );
    }
    if let Some(timeout) = lifecycle_ack_timeout_seconds {
        if !(1..=300).contains(&timeout) {
            return Err(format!(
                "grpc_physical ack timeout out of range: {} (expected 1..300)",
                timeout
            ));
        }
    }
    if let Some(cancel_after) = lifecycle_cancel_after_seconds {
        if !(1..=600).contains(&cancel_after) {
            return Err(format!(
                "grpc_physical cancel-after out of range: {} (expected 1..600)",
                cancel_after
            ));
        }
    }
    if remediation_profile.trim().is_empty() {
        remediation_profile = "standard".to_string();
    }
    let plaintext = grpc_plaintext_override.unwrap_or(inferred_plaintext);

    let start_ms = current_epoch_ms();
    let mut interceptor = PoGEInterceptor::new_validated(
        request.warrant.clone(),
        shadow_grpc_physical_module_digest(
            &grpc_target,
            &grpc_rpc,
            &request.http_headers,
            request_json,
        ),
        format!(
            "shadow:{}:{}:{}:{}",
            request.org_id, request.agent_id, request.action_type, request.resource
        ),
        start_ms,
    )
    .map_err(|error| format!("invalid kernel warrant: {}", error))?;
    let request_bytes = request_json.as_bytes().to_vec();

    let grpcurl_bin =
        std::env::var("LOOM_SHADOW_GRPCURL_BIN").unwrap_or_else(|_| "grpcurl".to_string());
    let mut command = Command::new(&grpcurl_bin);
    command
        .arg("-max-time")
        .arg(grpc_max_time_seconds.to_string());
    if plaintext {
        command.arg("-plaintext");
    }
    if grpc_allow_unknown_fields {
        command.arg("-allow-unknown-fields");
    }
    for (name, value) in &grpc_headers {
        command.arg("-H").arg(format!("{}: {}", name, value));
    }
    if !grpc_authority.is_empty() {
        command.arg("-authority").arg(&grpc_authority);
    }
    for import_path in &grpc_import_paths {
        command.arg("-import-path").arg(import_path);
    }
    for proto in &grpc_proto_files {
        command.arg("-proto").arg(proto);
    }
    for protoset in &grpc_protosets {
        command.arg("-protoset").arg(protoset);
    }
    command.arg("-d").arg(request_json);
    command.arg(&grpc_target).arg(&grpc_rpc);
    let (command_success, exit_code, stdout_text, stderr_text, stdout_json, transport_fallback) =
        match command.output() {
            Ok(output) => {
                let stdout_text = String::from_utf8_lossy(&output.stdout).to_string();
                let stderr_text = String::from_utf8_lossy(&output.stderr).to_string();
                let stdout_json: Value = serde_json::from_str(&stdout_text).unwrap_or_else(|_| {
                    serde_json::json!({
                        "status": if output.status.success() { "ok" } else { "error" },
                        "stdout_excerpt_utf8": stdout_text,
                    })
                });
                (
                    output.status.success(),
                    output.status.code(),
                    stdout_text,
                    stderr_text,
                    stdout_json,
                    None::<String>,
                )
            }
            Err(error) if error.kind() == ErrorKind::NotFound => {
                let fallback_reason = "grpcurl_not_found".to_string();
                let stderr_text = format!(
                    "grpc_physical fallback: '{}' not found; run degraded capture without transport execution",
                    grpcurl_bin
                );
                let stdout_json = serde_json::json!({
                    "status": "grpc_physical_transport_unavailable",
                    "reason": fallback_reason,
                    "ack_received": !lifecycle_ack_required,
                    "lifecycle_status": "transport_unavailable",
                    "stream_event_count": 0,
                    "transport_backend": "missing_grpcurl",
                });
                (
                    false,
                    Some(127),
                    String::new(),
                    stderr_text,
                    stdout_json,
                    Some(fallback_reason),
                )
            }
            Err(error) => {
                return Err(format!(
                    "failed to execute grpc_physical via {} for {} {}: {}",
                    grpcurl_bin, grpc_target, grpc_rpc, error
                ));
            }
        };
    let ack_received = stdout_json
        .get("ack_received")
        .and_then(Value::as_bool)
        .unwrap_or(!lifecycle_ack_required);
    let mut lifecycle_cancelled = stdout_json
        .get("cancelled")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let mut lifecycle_cancel_reason = value_string(stdout_json.get("cancel_reason"));
    if lifecycle_ack_required && !ack_received && lifecycle_cancel_on_ack_timeout {
        lifecycle_cancelled = true;
        if lifecycle_cancel_reason.is_empty() {
            lifecycle_cancel_reason = "ack_timeout".to_string();
        }
    }
    let lifecycle_status = value_string(stdout_json.get("lifecycle_status"));
    let lifecycle_stream_event_count = stdout_json
        .get("stream_event_count")
        .and_then(Value::as_u64);
    let lifecycle_ack_latency_ms = stdout_json.get("ack_latency_ms").and_then(Value::as_u64);
    let remediation_action = if let Some(reason) = transport_fallback.as_deref() {
        format!("transport_unavailable:{}:{}", reason, remediation_profile)
    } else if lifecycle_cancelled {
        format!(
            "cancelled:{}:{}",
            if lifecycle_cancel_reason.is_empty() {
                "unspecified"
            } else {
                lifecycle_cancel_reason.as_str()
            },
            remediation_profile
        )
    } else if lifecycle_ack_required && !ack_received {
        format!("escalate_ack_missing:{}", remediation_profile)
    } else {
        "none".to_string()
    };
    let response_payload = serde_json::json!({
        "status": if command_success {
            "grpc_physical_executed"
        } else if transport_fallback.is_some() {
            "grpc_physical_transport_unavailable"
        } else {
            "grpc_physical_error"
        },
        "grpc_target": grpc_target,
        "grpc_rpc": grpc_rpc,
        "grpc_transport": if plaintext { "plaintext" } else { "tls" },
        "grpc_transport_fallback": transport_fallback,
        "grpc_allow_unknown_fields": grpc_allow_unknown_fields,
        "grpc_max_time_seconds": grpc_max_time_seconds,
        "grpc_schema": "meridian.embodied.action.v1",
        "grpc_request_id": action_request.request_id,
        "grpc_action_kind": action_request.action_kind,
        "grpc_action_objective": action_request.action_objective,
        "grpc_action_skill": action_request.action_skill,
        "grpc_proto_count": grpc_proto_files.len(),
        "grpc_protoset_count": grpc_protosets.len(),
        "grpc_import_path_count": grpc_import_paths.len(),
        "grpc_authority": grpc_authority,
        "exit_code": exit_code,
        "stdout_excerpt_utf8": stdout_text,
        "stderr_excerpt_utf8": stderr_text,
        "grpc_physical_robot_id": action_request.physical_robot_id,
        "grpc_physical_target": action_request.physical_target,
        "grpc_physical_command": action_request.physical_command,
        "grpc_physical_safety_class": action_request.physical_safety_class,
        "grpc_physical_dry_run": action_request.physical_dry_run,
        "grpc_lifecycle_mode": lifecycle_mode,
        "grpc_lifecycle_ack_required": lifecycle_ack_required,
        "grpc_lifecycle_ack_timeout_seconds": lifecycle_ack_timeout_seconds,
        "grpc_lifecycle_ack_received": ack_received,
        "grpc_lifecycle_ack_latency_ms": lifecycle_ack_latency_ms,
        "grpc_lifecycle_cancel_on_ack_timeout": lifecycle_cancel_on_ack_timeout,
        "grpc_lifecycle_cancel_after_seconds": lifecycle_cancel_after_seconds,
        "grpc_lifecycle_cancelled": lifecycle_cancelled,
        "grpc_lifecycle_cancel_reason": lifecycle_cancel_reason,
        "grpc_lifecycle_status": lifecycle_status,
        "grpc_lifecycle_stream_event_count": lifecycle_stream_event_count,
        "grpc_remediation_profile": remediation_profile,
        "grpc_remediation_action": remediation_action,
    });
    let response_json = serde_json::to_string_pretty(&response_payload).map_err(io_err)?;
    interceptor
        .record_event(
            HostCallKind::Extension,
            start_ms,
            &request_bytes,
            response_json.as_bytes(),
            !command_success,
        )
        .map_err(|error| error.to_string())?;
    let audit_root = interceptor.finalize().map_err(|error| error.to_string())?;
    let capture = ShadowRunCapture {
        execution_path: ensure_runtime_dir(&request.root)?.join("last_execution.json"),
        shadow_latest_path: ensure_shadow_dir(&request.root)?.join("latest.json"),
        parity_latest_path: ensure_parity_dir(&request.root)?.join("latest.json"),
        parity_stream_path: ensure_parity_dir(&request.root)?.join("stream.jsonl"),
        status: "shadow_run_captured".to_string(),
        captured_at: timestamp_now(),
        backend: request.backend.as_str().to_string(),
        agent_id: request.agent_id.clone(),
        org_id: request.org_id.clone(),
        action_type: request.action_type.clone(),
        resource: request.resource.clone(),
        module_name: request.module_name.clone(),
        entrypoint: request.entrypoint.clone(),
        entrypoint_result: exit_code,
        host_backend: "external_grpc_physical".to_string(),
        warrant_binding_status: "verified".to_string(),
        warrant_id_hex: Some(format!("0x{}", hex::encode(audit_root.warrant_id))),
        poge_merkle_root_hex: Some(audit_root.merkle_root_hex()),
        poge_trace_len: Some(audit_root.trace_len),
        poge_witness_digest_hex: Some(audit_root.witness_digest_hex()),
        poge_session_label: Some(audit_root.session_label.clone()),
        poge_epoch_start_ms: Some(audit_root.epoch_start_ms),
        poge_epoch_end_ms: Some(audit_root.epoch_end_ms),
        poge_module_digest_hex: Some(format!("0x{}", hex::encode(audit_root.module_digest))),
        host_calls: vec![
            "grpc.physical.execute".to_string(),
            "grpc.physical.lifecycle".to_string(),
        ],
        host_response_json: Some(response_json),
    };

    persist_shadow_run_capture(&capture)?;
    persist_shadow_grpc_action_diagnostics(&request.root, &capture, &response_payload)?;
    Ok(capture)
}

fn persist_shadow_run_capture(capture: &ShadowRunCapture) -> ShadowResult<()> {
    let rendered = render_shadow_run_capture_json(capture);
    fs::write(&capture.execution_path, &rendered).map_err(io_err)?;
    fs::write(&capture.shadow_latest_path, &rendered).map_err(io_err)?;
    fs::write(&capture.parity_latest_path, &rendered).map_err(io_err)?;
    ensure_private_file(&capture.execution_path)?;
    ensure_private_file(&capture.shadow_latest_path)?;
    ensure_private_file(&capture.parity_latest_path)?;

    let stream_entry = serde_json::to_string(&serde_json::json!({
        "timestamp": &capture.captured_at,
        "source": "shadow_run",
        "backend": &capture.backend,
        "agent_id": &capture.agent_id,
        "org_id": &capture.org_id,
        "action_type": &capture.action_type,
        "resource": &capture.resource,
        "warrant_binding_status": &capture.warrant_binding_status,
        "poge_merkle_root_hex": &capture.poge_merkle_root_hex,
        "artifact_path": capture.parity_latest_path.display().to_string(),
    }))
    .map_err(io_err)?;
    append_line(&capture.parity_stream_path, &format!("{}\n", stream_entry))
}

fn shadow_run_capture_value(capture: &ShadowRunCapture) -> Value {
    let backend_note = match capture.backend.as_str() {
        "wasmtime" => {
            "shadow run executed through the governed wasmtime backend with warrant-bound PoGE receipts"
        }
        "command" => {
            "shadow run executed through the governed command backend with warrant-bound PoGE receipts"
        }
        "http" => {
            "shadow run executed through the governed http backend with warrant-bound PoGE receipts"
        }
        "mcp" => {
            "shadow run executed through the governed mcp backend with warrant-bound PoGE receipts"
        }
        "a2a" => {
            "shadow run executed through the governed a2a backend with warrant-bound PoGE receipts"
        }
        "a2a_action" => {
            "shadow run executed through the governed a2a semantic action backend with warrant-bound PoGE receipts"
        }
        "grpc_action" => {
            "shadow run executed through the governed grpc semantic action backend with warrant-bound PoGE receipts"
        }
        "grpc_physical" => {
            "shadow run executed through the governed grpc embodied physical backend with warrant-bound PoGE receipts"
        }
        _ => "shadow run executed through a governed backend with warrant-bound PoGE receipts",
    };
    serde_json::json!({
        "status": &capture.status,
        "backend": &capture.backend,
        "captured_at": &capture.captured_at,
        "agent_id": &capture.agent_id,
        "org_id": &capture.org_id,
        "action_type": &capture.action_type,
        "resource": &capture.resource,
        "module_name": &capture.module_name,
        "entrypoint": &capture.entrypoint,
        "entrypoint_result": capture.entrypoint_result,
        "host_backend": &capture.host_backend,
        "warrant_binding_status": &capture.warrant_binding_status,
        "warrant_id_hex": &capture.warrant_id_hex,
        "poge_merkle_root_hex": &capture.poge_merkle_root_hex,
        "poge_trace_len": capture.poge_trace_len,
        "poge_witness_digest_hex": &capture.poge_witness_digest_hex,
        "poge_session_label": &capture.poge_session_label,
        "poge_epoch_start_ms": capture.poge_epoch_start_ms,
        "poge_epoch_end_ms": capture.poge_epoch_end_ms,
        "poge_module_digest_hex": &capture.poge_module_digest_hex,
        "host_calls": &capture.host_calls,
        "host_response_json": &capture.host_response_json,
        "execution_path": capture.execution_path.display().to_string(),
        "shadow_latest_path": capture.shadow_latest_path.display().to_string(),
        "parity_latest_path": capture.parity_latest_path.display().to_string(),
        "note": backend_note,
    })
}

fn shadow_wasmtime_module_digest(module_name: &str, wasm_bytes: &[u8]) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(b"MERIDIAN_SHADOW_WASMTIME_BACKEND_V1\x00");
    hasher.update((module_name.len() as u32).to_be_bytes());
    hasher.update(module_name.as_bytes());
    hasher.update((wasm_bytes.len() as u64).to_be_bytes());
    hasher.update(wasm_bytes);
    hasher.finalize().into()
}

fn shadow_command_module_digest(program: &str, args: &[String]) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(b"MERIDIAN_SHADOW_COMMAND_BACKEND_V1\x00");
    hasher.update((program.len() as u32).to_be_bytes());
    hasher.update(program.as_bytes());
    hasher.update((args.len() as u32).to_be_bytes());
    for arg in args {
        hasher.update((arg.len() as u32).to_be_bytes());
        hasher.update(arg.as_bytes());
    }
    hasher.finalize().into()
}

fn shadow_http_module_digest(
    method: &str,
    url: &str,
    headers: &[(String, String)],
    body_json: Option<&str>,
) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(b"MERIDIAN_SHADOW_HTTP_BACKEND_V1\x00");
    hasher.update((method.len() as u32).to_be_bytes());
    hasher.update(method.as_bytes());
    hasher.update((url.len() as u32).to_be_bytes());
    hasher.update(url.as_bytes());
    hasher.update((headers.len() as u32).to_be_bytes());
    for (name, value) in headers {
        hasher.update((name.len() as u32).to_be_bytes());
        hasher.update(name.as_bytes());
        hasher.update((value.len() as u32).to_be_bytes());
        hasher.update(value.as_bytes());
    }
    let body = body_json.unwrap_or_default();
    hasher.update((body.len() as u32).to_be_bytes());
    hasher.update(body.as_bytes());
    hasher.finalize().into()
}

fn shadow_mcp_module_digest(url: &str, headers: &[(String, String)], body_json: &str) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(b"MERIDIAN_SHADOW_MCP_BACKEND_V1\x00");
    hasher.update((url.len() as u32).to_be_bytes());
    hasher.update(url.as_bytes());
    hasher.update((headers.len() as u32).to_be_bytes());
    for (name, value) in headers {
        hasher.update((name.len() as u32).to_be_bytes());
        hasher.update(name.as_bytes());
        hasher.update((value.len() as u32).to_be_bytes());
        hasher.update(value.as_bytes());
    }
    hasher.update((body_json.len() as u32).to_be_bytes());
    hasher.update(body_json.as_bytes());
    hasher.finalize().into()
}

fn shadow_a2a_module_digest(url: &str, headers: &[(String, String)], body_json: &str) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(b"MERIDIAN_SHADOW_A2A_BACKEND_V1\x00");
    hasher.update((url.len() as u32).to_be_bytes());
    hasher.update(url.as_bytes());
    hasher.update((headers.len() as u32).to_be_bytes());
    for (name, value) in headers {
        hasher.update((name.len() as u32).to_be_bytes());
        hasher.update(name.as_bytes());
        hasher.update((value.len() as u32).to_be_bytes());
        hasher.update(value.as_bytes());
    }
    hasher.update((body_json.len() as u32).to_be_bytes());
    hasher.update(body_json.as_bytes());
    hasher.finalize().into()
}

fn shadow_a2a_action_module_digest(
    url: &str,
    headers: &[(String, String)],
    body_json: &str,
) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(b"MERIDIAN_SHADOW_A2A_ACTION_BACKEND_V1\x00");
    hasher.update((url.len() as u32).to_be_bytes());
    hasher.update(url.as_bytes());
    hasher.update((headers.len() as u32).to_be_bytes());
    for (name, value) in headers {
        hasher.update((name.len() as u32).to_be_bytes());
        hasher.update(name.as_bytes());
        hasher.update((value.len() as u32).to_be_bytes());
        hasher.update(value.as_bytes());
    }
    hasher.update((body_json.len() as u32).to_be_bytes());
    hasher.update(body_json.as_bytes());
    hasher.finalize().into()
}

fn shadow_grpc_action_module_digest(
    grpc_target: &str,
    grpc_rpc: &str,
    headers: &[(String, String)],
    body_json: &str,
) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(b"MERIDIAN_SHADOW_GRPC_ACTION_BACKEND_V1\x00");
    hasher.update((grpc_target.len() as u32).to_be_bytes());
    hasher.update(grpc_target.as_bytes());
    hasher.update((grpc_rpc.len() as u32).to_be_bytes());
    hasher.update(grpc_rpc.as_bytes());
    hasher.update((headers.len() as u32).to_be_bytes());
    for (name, value) in headers {
        hasher.update((name.len() as u32).to_be_bytes());
        hasher.update(name.as_bytes());
        hasher.update((value.len() as u32).to_be_bytes());
        hasher.update(value.as_bytes());
    }
    hasher.update((body_json.len() as u32).to_be_bytes());
    hasher.update(body_json.as_bytes());
    hasher.finalize().into()
}

fn shadow_grpc_physical_module_digest(
    grpc_target: &str,
    grpc_rpc: &str,
    headers: &[(String, String)],
    body_json: &str,
) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(b"MERIDIAN_SHADOW_GRPC_PHYSICAL_BACKEND_V1\x00");
    hasher.update((grpc_target.len() as u32).to_be_bytes());
    hasher.update(grpc_target.as_bytes());
    hasher.update((grpc_rpc.len() as u32).to_be_bytes());
    hasher.update(grpc_rpc.as_bytes());
    hasher.update((headers.len() as u32).to_be_bytes());
    for (name, value) in headers {
        hasher.update((name.len() as u32).to_be_bytes());
        hasher.update(name.as_bytes());
        hasher.update((value.len() as u32).to_be_bytes());
        hasher.update(value.as_bytes());
    }
    hasher.update((body_json.len() as u32).to_be_bytes());
    hasher.update(body_json.as_bytes());
    hasher.finalize().into()
}

fn persist_shadow_grpc_action_diagnostics(
    root: &Path,
    capture: &ShadowRunCapture,
    response_payload: &Value,
) -> ShadowResult<()> {
    let diagnostics_dir = ensure_shadow_grpc_action_dir(root)?;
    let latest_path = diagnostics_dir.join("latest.json");
    let stream_path = diagnostics_dir.join("stream.jsonl");
    let mut diagnostics_value = response_payload.clone();
    if let Some(map) = diagnostics_value.as_object_mut() {
        map.insert(
            "captured_at".to_string(),
            Value::String(capture.captured_at.clone()),
        );
        map.insert(
            "backend".to_string(),
            Value::String(capture.backend.clone()),
        );
        map.insert(
            "host_backend".to_string(),
            Value::String(capture.host_backend.clone()),
        );
        map.insert(
            "agent_id".to_string(),
            Value::String(capture.agent_id.clone()),
        );
        map.insert("org_id".to_string(), Value::String(capture.org_id.clone()));
        map.insert(
            "action_type".to_string(),
            Value::String(capture.action_type.clone()),
        );
        map.insert(
            "resource".to_string(),
            Value::String(capture.resource.clone()),
        );
        map.insert(
            "warrant_binding_status".to_string(),
            Value::String(capture.warrant_binding_status.clone()),
        );
        if let Some(warrant_id) = capture.warrant_id_hex.as_ref() {
            map.insert(
                "warrant_id_hex".to_string(),
                Value::String(warrant_id.clone()),
            );
        }
        if let Some(merkle_root) = capture.poge_merkle_root_hex.as_ref() {
            map.insert(
                "poge_merkle_root_hex".to_string(),
                Value::String(merkle_root.clone()),
            );
        }
        if let Some(witness_digest) = capture.poge_witness_digest_hex.as_ref() {
            map.insert(
                "poge_witness_digest_hex".to_string(),
                Value::String(witness_digest.clone()),
            );
        }
        map.insert(
            "execution_path".to_string(),
            Value::String(capture.execution_path.display().to_string()),
        );
    }
    let rendered = serde_json::to_string_pretty(&diagnostics_value).map_err(io_err)?;
    fs::write(&latest_path, rendered).map_err(io_err)?;
    ensure_private_file(&latest_path)?;
    let stream_entry = serde_json::to_string(&diagnostics_value).map_err(io_err)?;
    append_line(&stream_path, &format!("{}\n", stream_entry))?;
    ensure_private_file(&stream_path)?;
    Ok(())
}

struct EventIds {
    job_id: String,
    execution_id: String,
    decision_id: String,
    parity_id: String,
    audit_id: String,
    subject_id: String,
    source_event_id: String,
}

fn artifact_spec(
    artifact_kind: &str,
    label: &str,
    path: &Path,
    source_event_id: &str,
    job_id: &str,
    execution_id: &str,
    note: &str,
) -> ArtifactRefSpec {
    ArtifactRefSpec {
        artifact_kind: artifact_kind.to_string(),
        label: label.to_string(),
        path: path.display().to_string(),
        source_event_id: source_event_id.to_string(),
        job_id: job_id.to_string(),
        execution_id: execution_id.to_string(),
        content_sha256: "unverified_local".to_string(),
        note: note.to_string(),
    }
}

fn generate_capture_ids(capture: &RuntimeExecutionCapture) -> EventIds {
    let job_id = canonical_job_id(
        &capture.org_id,
        &capture.agent_id,
        &capture.action_type,
        &capture.input_hash,
    );
    let execution_id =
        canonical_execution_id(&job_id, &capture.effective_stage, &capture.runtime_outcome);
    let decision_id =
        canonical_decision_id(&job_id, &capture.effective_stage, &capture.overall_decision);
    let parity_id = canonical_parity_id(&job_id, &execution_id, &capture.parity_status);
    let audit_id = canonical_audit_id(&job_id, &execution_id, &capture.action_type);
    let subject_id = canonical_envelope_id(
        &capture.org_id,
        &capture.agent_id,
        &capture.action_type,
        &capture.input_hash,
    );
    let source_event_id = canonical_event_id(
        &capture.org_id,
        &capture.agent_id,
        &capture.action_type,
        &capture.resource,
        &capture.runtime_outcome,
        &capture.effective_stage,
        &job_id,
        &execution_id,
    );

    EventIds {
        job_id,
        execution_id,
        decision_id,
        parity_id,
        audit_id,
        subject_id,
        source_event_id,
    }
}

fn runtime_event_for_capture(capture: &RuntimeExecutionCapture) -> RuntimeEventV1 {
    let ids = generate_capture_ids(capture);
    let mut artifact_refs = vec![
        artifact_spec(
            "execution_receipt",
            "runtime_execution",
            &capture.execution_path,
            &ids.source_event_id,
            &ids.job_id,
            &ids.execution_id,
            "runtime execution receipt",
        ),
        artifact_spec(
            "decision_receipt",
            "runtime_decision",
            &capture.decision_path,
            &ids.source_event_id,
            &ids.job_id,
            &ids.execution_id,
            "pre-execution decision artifact",
        ),
        artifact_spec(
            "audit_log",
            "runtime_audit",
            &capture.audit_log_path,
            &ids.source_event_id,
            &ids.job_id,
            &ids.execution_id,
            &format!(
                "kernel-owned runtime audit status={}",
                capture.audit_emission_status
            ),
        ),
        artifact_spec(
            "parity_stream",
            "runtime_parity_stream",
            &capture.parity_stream_path,
            &ids.source_event_id,
            &ids.job_id,
            &ids.execution_id,
            &format!("parity_status={}", capture.parity_status),
        ),
        artifact_spec(
            "parity_report",
            "runtime_parity_report",
            &capture.parity_report_path,
            &ids.source_event_id,
            &ids.job_id,
            &ids.execution_id,
            &capture.parity_reason,
        ),
        artifact_spec(
            "runtime_event",
            "runtime_event",
            &capture.runtime_event_path,
            &ids.source_event_id,
            &ids.job_id,
            &ids.execution_id,
            "canonical runtime event receipt",
        ),
        artifact_spec(
            "runtime_event_stream",
            "runtime_event_stream",
            &capture.runtime_event_stream_path,
            &ids.source_event_id,
            &ids.job_id,
            &ids.execution_id,
            "runtime event stream entry appended",
        ),
        artifact_spec(
            "worker_request",
            "worker_request",
            &capture.worker_request_path,
            &ids.source_event_id,
            &ids.job_id,
            &ids.execution_id,
            "worker dispatch envelope",
        ),
        artifact_spec(
            "worker_result",
            "worker_result",
            &capture.worker_result_path,
            &ids.source_event_id,
            &ids.job_id,
            &ids.execution_id,
            &format!("worker_status={}", capture.worker_status),
        ),
        artifact_spec(
            "worker_log",
            "worker_log",
            &capture.worker_log_path,
            &ids.source_event_id,
            &ids.job_id,
            &ids.execution_id,
            &capture.worker_note,
        ),
    ];
    if let Some(path) = capture.reference_probe_path.as_ref() {
        artifact_refs.push(artifact_spec(
            "reference_probe",
            "reference_probe",
            path,
            &ids.source_event_id,
            &ids.job_id,
            &ids.execution_id,
            &capture.reference_probe_note,
        ));
    }
    if let Some(path) = capture.reference_probe_stream_path.as_ref() {
        artifact_refs.push(artifact_spec(
            "reference_probe_stream",
            "reference_probe_stream",
            path,
            &ids.source_event_id,
            &ids.job_id,
            &ids.execution_id,
            "reference probe stream entries",
        ));
    }
    RuntimeEventSpec {
        truth_class: "experimental_runtime_local".to_string(),
        org_id: capture.org_id.clone(),
        agent_id: capture.agent_id.clone(),
        action_type: capture.action_type.clone(),
        resource: capture.resource.clone(),
        outcome: capture.runtime_outcome.clone(),
        stage: capture.effective_stage.clone(),
        source: "loom_runtime_execute".to_string(),
        subject_kind: "action_envelope".to_string(),
        subject_id: ids.subject_id,
        job_id: ids.job_id,
        execution_id: ids.execution_id,
        decision_id: ids.decision_id,
        parity_id: ids.parity_id,
        audit_id: ids.audit_id,
        note: "runtime execution receipt with canonical proof identifiers".to_string(),
        artifact_refs,
    }
    .into_event()
}

fn generate_job_ids(job: &JobSnapshot) -> EventIds {
    let job_id = canonical_job_id(&job.org_id, &job.agent_id, &job.action_type, &job.job_id);
    let execution_id = canonical_execution_id(&job_id, &job.stage, &job.runtime_outcome);
    let decision_id = canonical_decision_id(&job_id, &job.stage, &job.status);
    let parity_id = canonical_parity_id(
        &job_id,
        &execution_id,
        if job.parity_report_path.is_some() {
            "linked"
        } else {
            "missing"
        },
    );
    let audit_id = canonical_audit_id(&job_id, &execution_id, &job.action_type);
    let subject_id =
        canonical_envelope_id(&job.org_id, &job.agent_id, &job.action_type, &job.job_id);
    let source_event_id = canonical_event_id(
        &job.org_id,
        &job.agent_id,
        &job.action_type,
        &job.resource,
        &job.runtime_outcome,
        &job.stage,
        &job_id,
        &execution_id,
    );

    EventIds {
        job_id,
        execution_id,
        decision_id,
        parity_id,
        audit_id,
        subject_id,
        source_event_id,
    }
}

fn runtime_event_for_job(job: &JobSnapshot) -> RuntimeEventV1 {
    let ids = generate_job_ids(job);
    let mut artifact_refs = vec![artifact_spec(
        "job_snapshot",
        "job_snapshot",
        &job.job_path,
        &ids.source_event_id,
        &ids.job_id,
        &ids.execution_id,
        &job.note,
    )];
    if let Some(path) = job.queue_path.as_ref() {
        artifact_refs.push(artifact_spec(
            "queue_entry",
            "queue_entry",
            path,
            &ids.source_event_id,
            &ids.job_id,
            &ids.execution_id,
            "queue artifact for this job",
        ));
    }
    if let Some(path) = job.decision_path.as_ref() {
        artifact_refs.push(artifact_spec(
            "decision_receipt",
            "job_decision",
            path,
            &ids.source_event_id,
            &ids.job_id,
            &ids.execution_id,
            "decision artifact linked from job ledger",
        ));
    }
    if let Some(path) = job.execution_path.as_ref() {
        artifact_refs.push(artifact_spec(
            "execution_receipt",
            "job_execution",
            path,
            &ids.source_event_id,
            &ids.job_id,
            &ids.execution_id,
            "execution artifact linked from job ledger",
        ));
    }
    if let Some(path) = job.event_path.as_ref() {
        artifact_refs.push(artifact_spec(
            "runtime_event",
            "job_runtime_event",
            path,
            &ids.source_event_id,
            &ids.job_id,
            &ids.execution_id,
            "canonical runtime event linked from job ledger",
        ));
    }
    if let Some(path) = job.event_stream_path.as_ref() {
        artifact_refs.push(artifact_spec(
            "runtime_event_stream",
            "job_runtime_event_stream",
            path,
            &ids.source_event_id,
            &ids.job_id,
            &ids.execution_id,
            "runtime event stream linked from job ledger",
        ));
    }
    if let Some(path) = job.audit_log_path.as_ref() {
        artifact_refs.push(artifact_spec(
            "audit_log",
            "job_audit",
            path,
            &ids.source_event_id,
            &ids.job_id,
            &ids.execution_id,
            "kernel-owned runtime audit linked from job ledger",
        ));
    }
    if let Some(path) = job.parity_report_path.as_ref() {
        artifact_refs.push(artifact_spec(
            "parity_report",
            "job_parity",
            path,
            &ids.source_event_id,
            &ids.job_id,
            &ids.execution_id,
            "parity report linked from job ledger",
        ));
    }
    RuntimeEventSpec {
        truth_class: "experimental_runtime_job_ledger".to_string(),
        org_id: job.org_id.clone(),
        agent_id: job.agent_id.clone(),
        action_type: job.action_type.clone(),
        resource: job.resource.clone(),
        outcome: job.status.clone(),
        stage: job.stage.clone(),
        source: "loom_runtime_job_ledger".to_string(),
        subject_kind: "job_snapshot".to_string(),
        subject_id: ids.subject_id,
        job_id: ids.job_id,
        execution_id: ids.execution_id,
        decision_id: ids.decision_id,
        parity_id: ids.parity_id,
        audit_id: ids.audit_id,
        note: if job.budget_reservation_status.is_empty() {
            "job ledger view with canonical proof identifiers".to_string()
        } else {
            format!(
                "job ledger view with canonical proof identifiers; budget reservation {}",
                job.budget_reservation_status
            )
        },
        artifact_refs,
    }
    .into_event()
}

pub fn enqueue_action(
    root: &Path,
    kernel_path: &Path,
    envelope: &ActionEnvelope,
) -> ShadowResult<EnqueuedAction> {
    let input_hash = envelope_input_hash(envelope);
    let has_sanctions = resolve_agent_identity(
        root,
        Some(kernel_path.to_string_lossy().as_ref()),
        &envelope.agent_id,
        Some(&envelope.org_id),
    )
    .map(|identity| {
        let preview = preview_local_sanction_controls(&identity);
        !preview.allowed || !identity.restrictions.is_empty()
    })
    .unwrap_or(false);
    let policy_class = classify_action(
        &envelope.action_type,
        envelope.estimated_cost_usd,
        has_sanctions,
    );
    let queue_bucket = format!("pending:{}", policy_class.label());
    let mut scheduler_state = load_scheduler_state_or_default(root)?;
    if let Some(existing) = scheduler_state.jobs.get(&input_hash) {
        if matches!(
            existing.status,
            JobStatus::Queued | JobStatus::Reserved | JobStatus::Running | JobStatus::Suspended
        ) {
            let existing_snapshot = read_job_snapshot(root, &input_hash).ok();
            let existing_queue_path = existing_snapshot
                .as_ref()
                .and_then(|snapshot| snapshot.queue_path.clone())
                .filter(|path| path.exists())
                .or_else(|| {
                    find_pending_queue_path_for_job(root, &input_hash)
                        .ok()
                        .flatten()
                });
            if let Some(queue_path) = existing_queue_path {
                return Ok(EnqueuedAction {
                    queue_path,
                    job_path: job_snapshot_path(root, &input_hash),
                    input_hash,
                    policy_class: existing.policy_class.clone(),
                    agent_id: existing.agent_id.clone(),
                    org_id: existing.org_id.clone(),
                    action_type: existing.action_type.clone(),
                    resource: existing.resource.clone(),
                    estimated_cost_usd: envelope.estimated_cost_usd.to_string(),
                    kernel_path: kernel_path.display().to_string(),
                });
            }
        }
    }
    let pending_dir = pending_queue_dir(root, policy_class)?;
    let queue_path = pending_dir.join(format!(
        "{}-{}-{}.json",
        timestamp_now(),
        sanitize_filename(&envelope.agent_id),
        &input_hash[..8]
    ));
    fs::write(
        &queue_path,
        format!(
            "{{\n  \"status\": \"queued\",\n  \"queued_at\": {},\n  \"input_hash\": {},\n  \"policy_class\": {},\n  \"agent_id\": {},\n  \"org_id\": {},\n  \"action_type\": {},\n  \"resource\": {},\n  \"capability_name\": {},\n  \"payload_json\": {},\n  \"estimated_cost_usd\": {:.6},\n  \"run_id\": {},\n  \"session_id\": {},\n  \"kernel_path\": {}\n}}\n",
            json_string(&timestamp_now()),
            json_string(&input_hash),
            json_string(policy_class.label()),
            json_string(&envelope.agent_id),
            json_string(&envelope.org_id),
            json_string(&envelope.action_type),
            json_string(&envelope.resource),
            json_string(&envelope.capability_name),
            json_string(&envelope.payload_json),
            envelope.estimated_cost_usd,
            json_string(&envelope.run_id),
            json_string(&envelope.session_id),
            json_string(&kernel_path.display().to_string()),
        ),
    )
    .map_err(io_err)?;
    let job_path = job_snapshot_path(root, &input_hash);
    append_job_with_id(
        &mut scheduler_state,
        &input_hash,
        &envelope.agent_id,
        &envelope.org_id,
        &envelope.action_type,
        &envelope.resource,
        policy_class.label(),
        &queue_bucket,
    );
    save_scheduler_state_checked(root, &scheduler_state)?;
    write_job_snapshot(
        root,
        JobSnapshot {
            root: root.to_path_buf(),
            job_id: input_hash.clone(),
            job_path: job_path.clone(),
            status: "queued".to_string(),
            stage: "queue_pending".to_string(),
            queue_bucket: queue_bucket.clone(),
            queued_at: timestamp_now(),
            updated_at: timestamp_now(),
            agent_id: envelope.agent_id.clone(),
            org_id: envelope.org_id.clone(),
            action_type: envelope.action_type.clone(),
            resource: envelope.resource.clone(),
            estimated_cost_usd: format!("{:.6}", envelope.estimated_cost_usd),
            runtime_outcome: "not_started".to_string(),
            budget_reservation_id: String::new(),
            budget_reservation_status: "not_requested".to_string(),
            budget_reservation_reason: "queue pending; runtime reservation not attempted yet"
                .to_string(),
            worker_status: "queued".to_string(),
            queue_path: Some(queue_path.clone()),
            decision_path: None,
            execution_path: None,
            event_path: None,
            event_stream_path: None,
            audit_log_path: None,
            parity_report_path: None,
            reservation_id: String::new(),
            reservation_state: "none".to_string(),
            attempt_count: 0,
            note: format!(
                "queued for local supervisor rehearsal in {} lane",
                policy_class.label()
            ),
        },
    )?;
    Ok(EnqueuedAction {
        queue_path,
        job_path,
        input_hash,
        policy_class: policy_class.label().to_string(),
        agent_id: envelope.agent_id.clone(),
        org_id: envelope.org_id.clone(),
        action_type: envelope.action_type.clone(),
        resource: envelope.resource.clone(),
        estimated_cost_usd: format!("{:.6}", envelope.estimated_cost_usd),
        kernel_path: kernel_path.display().to_string(),
    })
}

fn find_pending_queue_path_for_job(root: &Path, job_id: &str) -> ShadowResult<Option<PathBuf>> {
    for (_class, path) in collect_pending_queue_paths(root)? {
        let contents = match fs::read_to_string(&path) {
            Ok(contents) => contents,
            Err(_) => continue,
        };
        let candidate = extract_json_string(&contents, "\"input_hash\"").or_else(|| {
            serde_json::from_str::<Value>(&contents).ok().and_then(|v| {
                v.get("input_hash")
                    .and_then(Value::as_str)
                    .map(|s| s.to_string())
            })
        });
        if candidate.as_deref() == Some(job_id) {
            return Ok(Some(path));
        }
    }
    Ok(None)
}

pub fn run_supervisor(
    root: &Path,
    override_kernel_path: Option<&str>,
    max_jobs: usize,
) -> ShadowResult<SupervisorRunSummary> {
    let runtime_dir = ensure_runtime_dir(root)?;
    let queue_dir = runtime_dir.join("queue");
    let processed_dir = queue_dir.join("processed");
    let failed_dir = queue_dir.join("failed");
    fs::create_dir_all(&processed_dir).map_err(io_err)?;
    fs::create_dir_all(&failed_dir).map_err(io_err)?;
    let mut pending = collect_pending_queue_paths(root)?;
    let mut scheduler_state = load_scheduler_state_or_default(root)?;
    let mut reservation_ledger = load_reservation_ledger_or_default(root)?;
    let expired_reservations = expire_stale(
        &mut reservation_ledger,
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs(),
    );
    for job_id in expired_reservations {
        let _ = transition_job(&mut scheduler_state, &job_id, JobStatus::Queued);
        let _ = update_job_metadata(
            &mut scheduler_state,
            &job_id,
            Some("pending:expired_recovered"),
            Some(None),
            Some(Some("expired reservation recovered for local supervisor")),
        );
    }
    save_scheduler_state_checked(root, &scheduler_state)?;
    save_reservation_ledger_checked(root, &reservation_ledger)?;

    let mut summary = SupervisorRunSummary {
        root: root.to_path_buf(),
        queue_dir: queue_dir.clone(),
        processed: 0,
        allowed: 0,
        denied: 0,
        failed: 0,
        last_input_hash: String::new(),
        last_execution_path: runtime_dir.join("last_execution.json"),
        audit_log_path: runtime_audit_log_path(root, override_kernel_path),
        note: "no queued actions were present".to_string(),
    };

    for (policy_class, path) in pending.drain(..).take(max_jobs.max(1)) {
        let contents = fs::read_to_string(&path).map_err(io_err)?;
        let queue_body = serde_json::from_str::<Value>(&contents).unwrap_or(Value::Null);
        let kernel_path_string = value_string(queue_body.get("kernel_path"))
            .trim()
            .to_string()
            .split_once('\0')
            .map(|(head, _)| head.to_string())
            .unwrap_or_else(|| value_string(queue_body.get("kernel_path")))
            .trim()
            .to_string();
        let kernel_path_string = (!kernel_path_string.is_empty())
            .then_some(kernel_path_string)
            .or_else(|| extract_json_string(&contents, "\"kernel_path\""))
            .or_else(|| override_kernel_path.map(|value| value.to_string()))
            .unwrap_or_else(|| {
                kernel_path_for(root, override_kernel_path)
                    .map(|p| p.display().to_string())
                    .unwrap_or_default()
            });
        if kernel_path_string.is_empty() {
            return Err(format!(
                "queued action {} has no kernel_path and no override was provided",
                path.display()
            ));
        }
        let input_hash = {
            let value = value_string(queue_body.get("input_hash"));
            if value.is_empty() {
                extract_json_string(&contents, "\"input_hash\"")
                    .ok_or_else(|| format!("input_hash missing in {}", path.display()))?
            } else {
                value
            }
        };
        let agent_id = {
            let value = value_string(queue_body.get("agent_id"));
            if value.is_empty() {
                extract_json_string(&contents, "\"agent_id\"")
                    .ok_or_else(|| format!("agent_id missing in {}", path.display()))?
            } else {
                value
            }
        };
        let org_id = {
            let value = value_string(queue_body.get("org_id"));
            if value.is_empty() {
                extract_json_string(&contents, "\"org_id\"")
                    .ok_or_else(|| format!("org_id missing in {}", path.display()))?
            } else {
                value
            }
        };
        let action_type = {
            let value = value_string(queue_body.get("action_type"));
            if value.is_empty() {
                extract_json_string(&contents, "\"action_type\"")
                    .ok_or_else(|| format!("action_type missing in {}", path.display()))?
            } else {
                value
            }
        };
        let resource = {
            let value = value_string(queue_body.get("resource"));
            if value.is_empty() {
                extract_json_string(&contents, "\"resource\"")
                    .ok_or_else(|| format!("resource missing in {}", path.display()))?
            } else {
                value
            }
        };
        let estimated_cost_usd = queue_body
            .get("estimated_cost_usd")
            .and_then(Value::as_f64)
            .or_else(|| extract_json_number(&contents, "\"estimated_cost_usd\""))
            .ok_or_else(|| format!("estimated_cost_usd missing in {}", path.display()))?;
        let run_id = {
            let value = value_string(queue_body.get("run_id"));
            if value.is_empty() {
                extract_json_string(&contents, "\"run_id\"").unwrap_or_default()
            } else {
                value
            }
        };
        let session_id = {
            let value = value_string(queue_body.get("session_id"));
            if value.is_empty() {
                extract_json_string(&contents, "\"session_id\"").unwrap_or_default()
            } else {
                value
            }
        };
        let capability_name = {
            let value = value_string(queue_body.get("capability_name"));
            if value.is_empty() {
                extract_json_string(&contents, "\"capability_name\"").unwrap_or_default()
            } else {
                value
            }
        };
        let payload_json = {
            let value = value_json_string(queue_body.get("payload_json"));
            if value.is_empty() {
                extract_json_string(&contents, "\"payload_json\"").unwrap_or_default()
            } else {
                value
            }
        };
        let policy_label = value_string(queue_body.get("policy_class"))
            .trim()
            .to_string();
        let policy_label = (!policy_label.is_empty())
            .then_some(policy_label)
            .or_else(|| extract_json_string(&contents, "\"policy_class\""))
            .unwrap_or_else(|| policy_class.label().to_string());

        if reconcile_terminal_pending_queue_record(
            root,
            &path,
            &processed_dir,
            &failed_dir,
            &mut scheduler_state,
            &input_hash,
            &policy_label,
        )? {
            continue;
        }

        if !scheduler_state.jobs.contains_key(&input_hash) {
            append_job_with_id(
                &mut scheduler_state,
                &input_hash,
                &agent_id,
                &org_id,
                &action_type,
                &resource,
                &policy_label,
                &format!("pending:{}", policy_label),
            );
        }
        let reservation =
            match reserve_job(&mut reservation_ledger, &input_hash, "local_supervisor", 60) {
                Ok(reservation) => reservation,
                Err(error) => {
                    let _ = update_job_metadata(
                        &mut scheduler_state,
                        &input_hash,
                        Some(&format!("reserved:{}", policy_label)),
                        Some(Some("local_supervisor")),
                        Some(Some(&format!("reservation skipped: {}", error))),
                    );
                    save_scheduler_state_checked(root, &scheduler_state)?;
                    save_reservation_ledger_checked(root, &reservation_ledger)?;
                    continue;
                }
            };
        transition_job(&mut scheduler_state, &input_hash, JobStatus::Reserved).map_err(
            |error| format!("failed to reserve scheduler job {}: {}", input_hash, error),
        )?;
        update_job_metadata(
            &mut scheduler_state,
            &input_hash,
            Some(&format!("reserved:{}", policy_label)),
            Some(Some("local_supervisor")),
            Some(Some(&format!(
                "reserved by local_supervisor via {} lane ({})",
                policy_label, reservation.reservation_id
            ))),
        )
        .map_err(|error| {
            format!(
                "failed to update reserved scheduler job {}: {}",
                input_hash, error
            )
        })?;
        save_scheduler_state_checked(root, &scheduler_state)?;
        save_reservation_ledger_checked(root, &reservation_ledger)?;

        let process_result = (|| -> ShadowResult<RuntimeExecutionCapture> {
            let identity =
                resolve_agent_identity(root, Some(&kernel_path_string), &agent_id, Some(&org_id))?;
            let envelope = build_action_envelope(
                root,
                Some(&kernel_path_string),
                &agent_id,
                Some(&org_id),
                &action_type,
                &resource,
                estimated_cost_usd,
                if run_id.is_empty() {
                    None
                } else {
                    Some(run_id.as_str())
                },
                if session_id.is_empty() {
                    None
                } else {
                    Some(session_id.as_str())
                },
            )?;
            let envelope = if capability_name.is_empty() && payload_json.is_empty() {
                envelope
            } else {
                build_action_envelope_with_options(
                    root,
                    Some(&kernel_path_string),
                    &agent_id,
                    Some(&org_id),
                    &action_type,
                    &resource,
                    estimated_cost_usd,
                    if run_id.is_empty() {
                        None
                    } else {
                        Some(run_id.as_str())
                    },
                    if session_id.is_empty() {
                        None
                    } else {
                        Some(session_id.as_str())
                    },
                    if capability_name.is_empty() {
                        None
                    } else {
                        Some(capability_name.as_str())
                    },
                    if payload_json.is_empty() {
                        None
                    } else {
                        Some(payload_json.as_str())
                    },
                )?
            };
            transition_job(&mut scheduler_state, &input_hash, JobStatus::Running)
                .map_err(|error| format!("failed to mark running for {}: {}", input_hash, error))?;
            update_job_metadata(
                &mut scheduler_state,
                &input_hash,
                Some(&format!("running:{}", policy_label)),
                Some(Some("local_supervisor")),
                None,
            )
            .map_err(|error| {
                format!(
                    "failed to update running scheduler job {}: {}",
                    input_hash, error
                )
            })?;
            save_scheduler_state_checked(root, &scheduler_state)?;
            let reference =
                evaluate_reference_gates(root, Some(&kernel_path_string), &identity, &envelope)?;
            let decision = capture_decision(root, &identity, &envelope, &reference)?;
            capture_runtime_execution(
                root,
                Path::new(&kernel_path_string),
                &envelope,
                &reference,
                &decision,
            )
        })();

        match process_result {
            Ok(capture) => {
                summary.processed += 1;
                summary.last_input_hash = capture.input_hash.clone();
                summary.last_execution_path = capture.execution_path.clone();
                summary.audit_log_path = capture.audit_log_path.clone();
                if capture.overall_decision == "allow" {
                    summary.allowed += 1;
                } else {
                    summary.denied += 1;
                }
                ack_job(
                    &mut reservation_ledger,
                    &capture.input_hash,
                    "local_supervisor",
                )
                .map_err(|error| {
                    format!(
                        "failed to ack reservation for {}: {}",
                        capture.input_hash, error
                    )
                })?;
                let terminal_status = if capture.overall_decision == "allow" {
                    if capture.worker_status == "completed" {
                        JobStatus::Completed
                    } else {
                        JobStatus::Failed
                    }
                } else {
                    JobStatus::Cancelled
                };
                transition_job(
                    &mut scheduler_state,
                    &capture.input_hash,
                    terminal_status.clone(),
                )
                .map_err(|error| {
                    format!(
                        "failed to update terminal state for {}: {}",
                        capture.input_hash, error
                    )
                })?;
                update_job_metadata(
                    &mut scheduler_state,
                    &capture.input_hash,
                    Some(&format!("processed:{}", policy_label)),
                    Some(None),
                    Some(Some(&format!(
                        "{} via {} (reference={})",
                        capture.runtime_outcome, capture.effective_stage, capture.reference_stage
                    ))),
                )
                .map_err(|error| {
                    format!(
                        "failed to update scheduler metadata for {}: {}",
                        capture.input_hash, error
                    )
                })?;
                save_scheduler_state_checked(root, &scheduler_state)?;
                save_reservation_ledger_checked(root, &reservation_ledger)?;
                let destination = processed_dir.join(
                    path.file_name()
                        .ok_or_else(|| format!("invalid queue file {}", path.display()))?,
                );
                fs::rename(&path, destination.clone()).map_err(io_err)?;
                let mut snapshot =
                    read_job_snapshot(root, &capture.input_hash).unwrap_or_else(|_| JobSnapshot {
                        root: root.to_path_buf(),
                        job_id: capture.input_hash.clone(),
                        job_path: job_snapshot_path(root, &capture.input_hash),
                        status: "runtime_rehearsed".to_string(),
                        stage: "local_queue_supervisor".to_string(),
                        queue_bucket: format!("processed:{}", policy_label),
                        queued_at: timestamp_now(),
                        updated_at: timestamp_now(),
                        agent_id: capture.agent_id.clone(),
                        org_id: capture.org_id.clone(),
                        action_type: capture.action_type.clone(),
                        resource: capture.resource.clone(),
                        estimated_cost_usd: format!("{:.6}", capture.estimated_cost_usd),
                        runtime_outcome: capture.runtime_outcome.clone(),
                        budget_reservation_id: capture.budget_reservation_id.clone(),
                        budget_reservation_status: capture.budget_reservation_status.clone(),
                        budget_reservation_reason: capture.budget_reservation_reason.clone(),
                        worker_status: capture.worker_status.clone(),
                        queue_path: None,
                        decision_path: Some(capture.decision_path.clone()),
                        execution_path: Some(capture.execution_path.clone()),
                        event_path: Some(capture.runtime_event_path.clone()),
                        event_stream_path: Some(capture.runtime_event_stream_path.clone()),
                        audit_log_path: Some(capture.audit_log_path.clone()),
                        parity_report_path: Some(capture.parity_report_path.clone()),
                        reservation_id: reservation.reservation_id.clone(),
                        reservation_state: "acked".to_string(),
                        attempt_count: scheduler_state
                            .jobs
                            .get(&capture.input_hash)
                            .map(|j| j.attempt_count)
                            .unwrap_or(1),
                        note: capture.worker_note.clone(),
                    });
                snapshot.queue_bucket = format!("processed:{}", policy_label);
                snapshot.stage = "local_queue_supervisor".to_string();
                snapshot.updated_at = timestamp_now();
                snapshot.queue_path = Some(destination.clone());
                snapshot.decision_path = Some(capture.decision_path.clone());
                snapshot.execution_path = Some(capture.execution_path.clone());
                snapshot.event_path = Some(capture.runtime_event_path.clone());
                snapshot.event_stream_path = Some(capture.runtime_event_stream_path.clone());
                snapshot.audit_log_path = Some(capture.audit_log_path.clone());
                snapshot.parity_report_path = Some(capture.parity_report_path.clone());
                snapshot.runtime_outcome = capture.runtime_outcome.clone();
                snapshot.budget_reservation_id = capture.budget_reservation_id.clone();
                snapshot.budget_reservation_status = capture.budget_reservation_status.clone();
                snapshot.budget_reservation_reason = capture.budget_reservation_reason.clone();
                snapshot.worker_status = capture.worker_status.clone();
                snapshot.reservation_id = reservation.reservation_id.clone();
                snapshot.reservation_state = "acked".to_string();
                snapshot.attempt_count = scheduler_state
                    .jobs
                    .get(&capture.input_hash)
                    .map(|j| j.attempt_count)
                    .unwrap_or(1);
                snapshot.status = if capture.overall_decision == "allow" {
                    if capture.worker_status == "completed" {
                        "completed".to_string()
                    } else {
                        "failed".to_string()
                    }
                } else {
                    capture.overall_decision.clone()
                };
                snapshot.note = if capture.worker_note.is_empty() {
                    format!(
                        "processed in {} lane via {}",
                        policy_label, capture.effective_stage
                    )
                } else {
                    format!("{} [{} lane]", capture.worker_note, policy_label)
                };
                write_job_snapshot(root, snapshot.clone())?;
                let _ =
                    write_queue_ack_record(root, &snapshot, "local_supervisor", Some(&destination));
            }
            Err(error) => {
                summary.failed += 1;
                let _ = nack_job(&mut reservation_ledger, &input_hash, "local_supervisor");
                let _ = transition_job(&mut scheduler_state, &input_hash, JobStatus::Failed);
                let _ = update_job_metadata(
                    &mut scheduler_state,
                    &input_hash,
                    Some(&format!("failed:{}", policy_label)),
                    Some(None),
                    Some(Some(&error)),
                );
                save_scheduler_state_checked(root, &scheduler_state)?;
                save_reservation_ledger_checked(root, &reservation_ledger)?;
                let destination = failed_dir.join(
                    path.file_name()
                        .ok_or_else(|| format!("invalid queue file {}", path.display()))?,
                );
                let failure_payload = format!(
                    "{{\n  \"status\": \"failed\",\n  \"failed_at\": {},\n  \"source_path\": {},\n  \"error\": {},\n  \"queued_action\": {}\n}}\n",
                    json_string(&timestamp_now()),
                    json_string(&path.display().to_string()),
                    json_string(&error),
                    contents.trim(),
                );
                fs::write(&destination, failure_payload).map_err(io_err)?;
                fs::remove_file(&path).map_err(io_err)?;
                if let Some(input_hash) = extract_json_string(&contents, "\"input_hash\"") {
                    write_job_snapshot(
                        root,
                        JobSnapshot {
                            root: root.to_path_buf(),
                            job_id: input_hash.clone(),
                            job_path: job_snapshot_path(root, &input_hash),
                            status: "failed".to_string(),
                            stage: "local_queue_supervisor".to_string(),
                            queue_bucket: format!("failed:{}", policy_label),
                            queued_at: extract_json_string(&contents, "\"queued_at\"")
                                .unwrap_or_else(timestamp_now),
                            updated_at: timestamp_now(),
                            agent_id: extract_json_string(&contents, "\"agent_id\"")
                                .unwrap_or_default(),
                            org_id: extract_json_string(&contents, "\"org_id\"")
                                .unwrap_or_default(),
                            action_type: extract_json_string(&contents, "\"action_type\"")
                                .unwrap_or_default(),
                            resource: extract_json_string(&contents, "\"resource\"")
                                .unwrap_or_default(),
                            estimated_cost_usd: extract_json_number(
                                &contents,
                                "\"estimated_cost_usd\"",
                            )
                            .map(|value| format!("{:.6}", value))
                            .unwrap_or_else(|| "0.000000".to_string()),
                            runtime_outcome: "supervisor_failed".to_string(),
                            budget_reservation_id: String::new(),
                            budget_reservation_status: "reservation_failed".to_string(),
                            budget_reservation_reason:
                                "queue supervisor failed before runtime capture".to_string(),
                            worker_status: "failed_before_dispatch".to_string(),
                            queue_path: Some(destination.clone()),
                            decision_path: None,
                            execution_path: None,
                            event_path: None,
                            event_stream_path: None,
                            audit_log_path: None,
                            parity_report_path: None,
                            reservation_id: reservation.reservation_id.clone(),
                            reservation_state: "nacked".to_string(),
                            attempt_count: scheduler_state
                                .jobs
                                .get(&input_hash)
                                .map(|j| j.attempt_count)
                                .unwrap_or(1),
                            note: error,
                        },
                    )?;
                    if let Ok(snapshot) = read_job_snapshot(root, &input_hash) {
                        let _ = write_queue_ack_record(
                            root,
                            &snapshot,
                            "local_supervisor",
                            Some(&destination),
                        );
                    }
                }
            }
        }
    }

    if summary.processed > 0 || summary.failed > 0 {
        summary.note = format!(
            "processed={} allowed={} denied={} failed={}",
            summary.processed, summary.allowed, summary.denied, summary.failed
        );
    }
    Ok(summary)
}

fn reconcile_terminal_pending_queue_record(
    root: &Path,
    pending_path: &Path,
    processed_dir: &Path,
    failed_dir: &Path,
    scheduler_state: &mut SchedulerState,
    job_id: &str,
    policy_label: &str,
) -> ShadowResult<bool> {
    let Some(job) = scheduler_state.jobs.get(job_id).cloned() else {
        return Ok(false);
    };
    if !matches!(
        job.status,
        JobStatus::Completed | JobStatus::Failed | JobStatus::Cancelled
    ) {
        return Ok(false);
    }

    let terminal_bucket =
        if job.queue_bucket.starts_with("failed:") || job.status == JobStatus::Failed {
            failed_dir
        } else {
            processed_dir
        };
    let destination = terminal_bucket.join(
        pending_path
            .file_name()
            .ok_or_else(|| format!("invalid queue file {}", pending_path.display()))?,
    );
    if !destination.exists() {
        fs::rename(pending_path, &destination).map_err(io_err)?;
    } else if pending_path.exists() {
        fs::remove_file(pending_path).map_err(io_err)?;
    }

    let note = format!(
        "stale pending queue record reconciled against terminal scheduler state ({}) [{} lane]",
        job.status.as_str(),
        policy_label
    );
    let _ = update_job_metadata(
        scheduler_state,
        job_id,
        Some(&job.queue_bucket),
        Some(None),
        Some(Some(&note)),
    );
    save_scheduler_state_checked(root, scheduler_state)?;

    let mut snapshot = read_job_snapshot(root, job_id).unwrap_or_else(|_| JobSnapshot {
        root: root.to_path_buf(),
        job_id: job_id.to_string(),
        job_path: job_snapshot_path(root, job_id),
        status: job.status.as_str().to_string(),
        stage: "local_queue_supervisor".to_string(),
        queue_bucket: job.queue_bucket.clone(),
        queued_at: job.enqueued_at.to_string(),
        updated_at: timestamp_now(),
        agent_id: job.agent_id.clone(),
        org_id: job.org_id.clone(),
        action_type: job.action_type.clone(),
        resource: job.resource.clone(),
        estimated_cost_usd: "0.000000".to_string(),
        runtime_outcome: "stale_pending_reconciled".to_string(),
        budget_reservation_id: String::new(),
        budget_reservation_status: String::new(),
        budget_reservation_reason: String::new(),
        worker_status: job.status.as_str().to_string(),
        queue_path: None,
        decision_path: None,
        execution_path: None,
        event_path: None,
        event_stream_path: None,
        audit_log_path: None,
        parity_report_path: None,
        reservation_id: String::new(),
        reservation_state: String::new(),
        attempt_count: job.attempt_count,
        note: note.clone(),
    });
    snapshot.status = job.status.as_str().to_string();
    snapshot.stage = "local_queue_supervisor".to_string();
    snapshot.queue_bucket = job.queue_bucket.clone();
    snapshot.updated_at = timestamp_now();
    snapshot.queue_path = Some(destination.clone());
    snapshot.worker_status = job.status.as_str().to_string();
    snapshot.attempt_count = job.attempt_count;
    snapshot.note = note.clone();
    write_job_snapshot(root, snapshot.clone())?;
    let _ = write_queue_ack_record(root, &snapshot, "local_supervisor", Some(&destination));

    Ok(true)
}

pub fn list_jobs(
    root: &Path,
    status_filter: Option<&str>,
    limit: usize,
) -> ShadowResult<Vec<JobSnapshot>> {
    let jobs_dir = ensure_runtime_jobs_dir(root)?;
    let mut jobs = fs::read_dir(&jobs_dir)
        .map_err(io_err)?
        .filter_map(|entry| entry.ok().map(|item| item.path()))
        .filter(|path| path.is_dir())
        .filter_map(|path| {
            let job_id = path.file_name()?.to_string_lossy().to_string();
            read_job_snapshot(root, &job_id).ok()
        })
        .collect::<Vec<_>>();
    jobs.sort_by(|left, right| {
        right
            .updated_at
            .cmp(&left.updated_at)
            .then_with(|| right.job_id.cmp(&left.job_id))
    });
    if let Some(filter) = status_filter {
        jobs.retain(|job| job.status == filter);
    }
    if limit > 0 {
        jobs.truncate(limit);
    }
    Ok(jobs)
}

pub fn inspect_job(root: &Path, job_id: &str) -> ShadowResult<JobSnapshot> {
    read_job_snapshot(root, job_id)
}

pub fn inspect_pending_queue(root: &Path, limit: usize) -> ShadowResult<Vec<QueueRecordSnapshot>> {
    let mut records = collect_pending_queue_paths(root)?
        .into_iter()
        .map(|(policy_class, path)| load_queue_record_snapshot(root, policy_class, &path))
        .collect::<ShadowResult<Vec<_>>>()?;
    records.sort_by(|left, right| {
        left.queued_at
            .cmp(&right.queued_at)
            .then_with(|| left.job_id.cmp(&right.job_id))
    });
    if limit > 0 {
        records.truncate(limit);
    }
    Ok(records)
}

pub fn queue_status(root: &Path) -> ShadowResult<QueueStatusSnapshot> {
    let queue_dir = ensure_runtime_dir(root)?.join("queue");
    let records = inspect_pending_queue(root, 0)?;
    let mut standard_depth = 0usize;
    let mut privileged_depth = 0usize;
    let mut budget_heavy_depth = 0usize;
    let mut sanction_sensitive_depth = 0usize;

    for record in &records {
        match record.policy_class.as_str() {
            "standard" => standard_depth += 1,
            "privileged" => privileged_depth += 1,
            "budget_heavy" => budget_heavy_depth += 1,
            "sanction_sensitive" => sanction_sensitive_depth += 1,
            _ => {}
        }
    }

    Ok(QueueStatusSnapshot {
        root: root.to_path_buf(),
        queue_dir,
        pending_records: records.len(),
        acked_records: records.iter().filter(|record| record.acknowledged).count(),
        total_pending: records.iter().filter(|record| !record.acknowledged).count(),
        standard_depth,
        privileged_depth,
        budget_heavy_depth,
        sanction_sensitive_depth,
        note: "local queue depth is inspectable; hosted queue orchestration remains future work"
            .to_string(),
    })
}

pub fn consume_pending_queue(
    root: &Path,
    override_kernel_path: Option<&str>,
    max_jobs: usize,
) -> ShadowResult<QueueConsumeSummary> {
    let queue_dir = ensure_runtime_dir(root)?.join("queue");
    let pending_before = count_runtime_queue_entries(root, "pending")?;
    let run = run_supervisor(root, override_kernel_path, max_jobs)?;
    let pending_after = count_runtime_queue_entries(root, "pending")?;
    let acked_jobs = count_queue_ack_entries(root)?;
    let note = if run.note.is_empty() {
        format!(
            "consumed {} local queue records with filesystem acks",
            run.processed
        )
    } else {
        format!("{}; local queue acks recorded", run.note)
    };
    Ok(QueueConsumeSummary {
        root: root.to_path_buf(),
        queue_dir,
        requested: max_jobs,
        pending_before,
        pending_after,
        processed_jobs: run.processed,
        failed_jobs: run.failed,
        acked_jobs,
        last_input_hash: run.last_input_hash,
        last_execution_path: run.last_execution_path,
        note,
    })
}

pub fn run_queue_once(
    root: &Path,
    override_kernel_path: Option<&str>,
) -> ShadowResult<QueueRunOnceSummary> {
    let consume = consume_pending_queue(root, override_kernel_path, 1)?;
    let progress_dir = queue_runs_dir(root)?;
    let progress_path = progress_dir.join(format!("run_once_{}.json", timestamp_now()));
    let summary = QueueRunOnceSummary {
        root: consume.root,
        queue_dir: consume.queue_dir,
        progress_path: progress_path.clone(),
        requested: consume.requested,
        pending_before: consume.pending_before,
        pending_after: consume.pending_after,
        processed_jobs: consume.processed_jobs,
        failed_jobs: consume.failed_jobs,
        acked_jobs: consume.acked_jobs,
        last_input_hash: consume.last_input_hash,
        last_execution_path: consume.last_execution_path,
        note: if consume.note.is_empty() {
            "bounded local queue pipeline pass; no live delivery attempted".to_string()
        } else {
            format!("bounded local queue pipeline pass; {}", consume.note)
        },
    };
    fs::write(&progress_path, render_queue_run_once_json(&summary)).map_err(io_err)?;
    ensure_private_file(&progress_path)?;
    Ok(summary)
}

pub fn run_queue_until_empty(
    root: &Path,
    override_kernel_path: Option<&str>,
    max_jobs_per_pass: usize,
    max_passes: usize,
) -> ShadowResult<QueueRunUntilEmptySummary> {
    let queue_dir = ensure_runtime_dir(root)?.join("queue");
    let progress_dir = queue_runs_dir(root)?.join(format!("run_until_empty_{}", timestamp_now()));
    ensure_private_dir(&progress_dir)?;
    let journal_path = progress_dir.join("journal.jsonl");
    let progress_path = progress_dir.join("summary.json");
    let initial_pending = count_runtime_queue_entries(root, "pending")?;
    let mut passes_completed = 0usize;
    let mut processed_jobs = 0usize;
    let mut failed_jobs = 0usize;
    let mut acked_jobs = 0usize;
    let mut last_input_hash = String::new();
    let mut last_execution_path = queue_dir.join("last_execution.json");
    let mut final_pending = initial_pending;
    let effective_max_passes = max_passes.max(1);
    let effective_max_jobs = max_jobs_per_pass.max(1);
    let mut journal_entries: Vec<String> = Vec::new();

    if initial_pending == 0 {
        journal_entries.push(format!(
            r#"{{"status":"queue_run_until_empty_pass","pass":0,"pending_before":0,"pending_after":0,"processed_jobs":0,"failed_jobs":0,"acked_jobs":0,"drained":true,"note":{}}}
"#,
            json_string("queue already empty; no consume pass executed"),
        ));
    } else {
        for pass in 0..effective_max_passes {
            let pending_before = count_runtime_queue_entries(root, "pending")?;
            if pending_before == 0 {
                break;
            }

            let acked_before = count_queue_ack_entries(root)?;
            let consume = consume_pending_queue(root, override_kernel_path, effective_max_jobs)?;
            let acked_after = count_queue_ack_entries(root)?;
            let pass_acked_jobs = acked_after.saturating_sub(acked_before);
            passes_completed += 1;
            processed_jobs += consume.processed_jobs;
            failed_jobs += consume.failed_jobs;
            acked_jobs += pass_acked_jobs;
            last_input_hash = consume.last_input_hash.clone();
            last_execution_path = consume.last_execution_path.clone();
            final_pending = consume.pending_after;
            let drained = final_pending == 0;
            journal_entries.push(format!(
                r#"{{"status":"queue_run_until_empty_pass","pass":{},"pending_before":{},"pending_after":{},"processed_jobs":{},"failed_jobs":{},"acked_jobs":{},"last_input_hash":{},"last_execution_path":{},"drained":{},"note":{}}}
"#,
                pass + 1,
                consume.pending_before,
                consume.pending_after,
                consume.processed_jobs,
                consume.failed_jobs,
                pass_acked_jobs,
                json_string(&consume.last_input_hash),
                json_string(&consume.last_execution_path.display().to_string()),
                if drained { "true" } else { "false" },
                json_string(&consume.note),
            ));
            if drained {
                break;
            }
        }
    }

    for entry in &journal_entries {
        append_line(&journal_path, entry)?;
    }

    let drained = final_pending == 0;
    let note = if initial_pending == 0 {
        "queue already empty; no consume pass executed".to_string()
    } else if drained {
        format!(
            "drained {} pending records in {} pass(es)",
            initial_pending, passes_completed
        )
    } else {
        format!(
            "stopped after {} pass(es) with {} pending record(s) remaining",
            passes_completed, final_pending
        )
    };
    let summary = QueueRunUntilEmptySummary {
        root: root.to_path_buf(),
        queue_dir,
        progress_path: progress_path.clone(),
        journal_path: journal_path.clone(),
        requested: effective_max_jobs,
        max_passes: effective_max_passes,
        passes_completed,
        initial_pending,
        final_pending,
        processed_jobs,
        failed_jobs,
        acked_jobs,
        last_input_hash,
        last_execution_path,
        drained,
        note,
    };
    fs::write(&progress_path, render_queue_run_until_empty_json(&summary)).map_err(io_err)?;
    ensure_private_file(&progress_path)?;
    ensure_private_file(&journal_path)?;
    Ok(summary)
}

pub fn ack_queue_job(root: &Path, job_id: &str) -> ShadowResult<QueueAckCapture> {
    let snapshot = inspect_job(root, job_id)?;
    if !matches!(
        snapshot.status.as_str(),
        "completed" | "failed" | "denied" | "cancelled"
    ) {
        return Err(format!(
            "job {} is in state {}, not a terminal state that can be acknowledged",
            job_id, snapshot.status
        ));
    }
    write_queue_ack_record(root, &snapshot, "queue_ack", snapshot.queue_path.as_deref())
}

/// Approve a suspended job, moving it back to Queued so the supervisor can re-process it.
pub fn approve_job(root: &Path, job_id: &str) -> ShadowResult<String> {
    let mut scheduler_state = load_scheduler_state_or_default(root)?;
    let job = scheduler_state
        .jobs
        .get(job_id)
        .ok_or_else(|| format!("job {} not found in scheduler state", job_id))?;
    if job.status != JobStatus::Suspended {
        return Err(format!(
            "job {} is in state {:?}, not suspended — only suspended jobs can be approved",
            job_id, job.status
        ));
    }
    transition_job(&mut scheduler_state, job_id, JobStatus::Queued)
        .map_err(|e| format!("failed to transition job {} to queued: {}", job_id, e))?;
    update_job_metadata(
        &mut scheduler_state,
        job_id,
        Some("pending:approved"),
        Some(None),
        Some(Some(
            "job approved via loom job approve, re-queued for processing",
        )),
    )
    .map_err(|e| format!("failed to update job metadata: {}", e))?;
    save_scheduler_state_checked(root, &scheduler_state)?;
    // Also update job snapshot if it exists
    if let Ok(mut snapshot) = read_job_snapshot(root, job_id) {
        snapshot.status = "queued".to_string();
        snapshot.queue_bucket = "pending:approved".to_string();
        snapshot.updated_at = timestamp_now();
        snapshot.note = "approved and re-queued for supervisor processing".to_string();
        write_job_snapshot(root, snapshot)?;
    }
    Ok(format!("job {} approved and re-queued", job_id))
}

pub fn watch_supervisor(
    root: &Path,
    override_kernel_path: Option<&str>,
    max_jobs: usize,
    iterations: usize,
    poll_seconds: u64,
) -> ShadowResult<SupervisorWatchSummary> {
    let runtime_dir = ensure_runtime_dir(root)?;
    let supervisor_dir = runtime_dir.join("supervisor");
    fs::create_dir_all(&supervisor_dir).map_err(io_err)?;
    let heartbeat_log_path = supervisor_dir.join("heartbeat.jsonl");
    let status_path = supervisor_dir.join("status.json");

    let mut summary = SupervisorWatchSummary {
        root: root.to_path_buf(),
        supervisor_dir,
        iterations,
        poll_seconds,
        processed: 0,
        allowed: 0,
        denied: 0,
        failed: 0,
        heartbeat_log_path: heartbeat_log_path.clone(),
        status_path: status_path.clone(),
        note: "no iterations executed".to_string(),
    };

    for iteration in 0..iterations.max(1) {
        let run = run_supervisor(root, override_kernel_path, max_jobs)?;
        summary.processed += run.processed;
        summary.allowed += run.allowed;
        summary.denied += run.denied;
        summary.failed += run.failed;
        summary.note = format!(
            "iterations={} processed={} allowed={} denied={} failed={}",
            iteration + 1,
            summary.processed,
            summary.allowed,
            summary.denied,
            summary.failed,
        );

        let pending_jobs = count_runtime_queue_entries(root, "pending")?;
        let processed_jobs = count_runtime_queue_entries(root, "processed")?;
        let failed_jobs = count_runtime_queue_entries(root, "failed")?;
        append_line(
            &heartbeat_log_path,
            &format!(
                "{{\"timestamp\":{},\"iteration\":{},\"processed\":{},\"allowed\":{},\"denied\":{},\"failed\":{},\"pending_jobs\":{},\"processed_jobs\":{},\"failed_jobs\":{},\"note\":{}}}\n",
                json_string(&timestamp_now()),
                iteration + 1,
                run.processed,
                run.allowed,
                run.denied,
                run.failed,
                pending_jobs,
                processed_jobs,
                failed_jobs,
                json_string(&run.note),
            ),
        )?;
        fs::write(
            &status_path,
            format!(
                "{{\n  \"status\": \"watch_complete\",\n  \"updated_at\": {},\n  \"iterations\": {},\n  \"poll_seconds\": {},\n  \"processed\": {},\n  \"allowed\": {},\n  \"denied\": {},\n  \"failed\": {},\n  \"pending_jobs\": {},\n  \"processed_jobs\": {},\n  \"failed_jobs\": {},\n  \"note\": {}\n}}\n",
                json_string(&timestamp_now()),
                iteration + 1,
                poll_seconds,
                summary.processed,
                summary.allowed,
                summary.denied,
                summary.failed,
                pending_jobs,
                processed_jobs,
                failed_jobs,
                json_string(&summary.note),
            ),
        )
        .map_err(io_err)?;

        if iteration + 1 < iterations.max(1) {
            thread::sleep(Duration::from_secs(poll_seconds));
        }
    }

    Ok(summary)
}

pub fn supervisor_status(root: &Path) -> ShadowResult<SupervisorStatusSnapshot> {
    let runtime_dir = ensure_runtime_dir(root)?;
    let supervisor_dir = runtime_dir.join("supervisor");
    fs::create_dir_all(&supervisor_dir).map_err(io_err)?;
    let status_path = supervisor_dir.join("status.json");
    let heartbeat_log_path = supervisor_dir.join("heartbeat.jsonl");

    if !status_path.exists() {
        return Ok(SupervisorStatusSnapshot {
            root: root.to_path_buf(),
            supervisor_dir,
            status_path,
            heartbeat_log_path,
            available: false,
            updated_at: "not_started".to_string(),
            iterations: 0,
            poll_seconds: 0,
            processed: 0,
            allowed: 0,
            denied: 0,
            failed: 0,
            pending_jobs: count_runtime_queue_entries(root, "pending")?,
            processed_jobs: count_runtime_queue_entries(root, "processed")?,
            failed_jobs: count_runtime_queue_entries(root, "failed")?,
            heartbeat_entries: 0,
            last_heartbeat_timestamp: "not_started".to_string(),
            note: "no supervisor status captured yet; run `loom supervisor watch` or `loom supervisor run` first".to_string(),
        });
    }

    let status_contents = fs::read_to_string(&status_path).map_err(io_err)?;
    let (heartbeat_entries, last_heartbeat_timestamp) = if heartbeat_log_path.exists() {
        let contents = fs::read_to_string(&heartbeat_log_path).map_err(io_err)?;
        let entries = contents
            .lines()
            .filter(|line| !line.trim().is_empty())
            .collect::<Vec<_>>();
        let last_timestamp = entries
            .last()
            .and_then(|line| extract_json_string(line, "\"timestamp\""))
            .unwrap_or_else(|| "unknown".to_string());
        (entries.len(), last_timestamp)
    } else {
        (0, "not_started".to_string())
    };

    Ok(SupervisorStatusSnapshot {
        root: root.to_path_buf(),
        supervisor_dir,
        status_path,
        heartbeat_log_path,
        available: true,
        updated_at: extract_json_string(&status_contents, "\"updated_at\"")
            .unwrap_or_else(|| "unknown".to_string()),
        iterations: extract_json_number(&status_contents, "\"iterations\"")
            .or_else(|| extract_json_number(&status_contents, "\"iteration\""))
            .map(|value| value as usize)
            .unwrap_or(0),
        poll_seconds: extract_json_number(&status_contents, "\"poll_seconds\"")
            .map(|value| value as u64)
            .unwrap_or(0),
        processed: extract_json_number(&status_contents, "\"processed\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        allowed: extract_json_number(&status_contents, "\"allowed\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        denied: extract_json_number(&status_contents, "\"denied\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        failed: extract_json_number(&status_contents, "\"failed\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        pending_jobs: extract_json_number(&status_contents, "\"pending_jobs\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        processed_jobs: extract_json_number(&status_contents, "\"processed_jobs\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        failed_jobs: extract_json_number(&status_contents, "\"failed_jobs\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        heartbeat_entries,
        last_heartbeat_timestamp,
        note: extract_json_string(&status_contents, "\"note\"").unwrap_or_default(),
    })
}

pub fn run_supervisor_daemon_loop(
    root: &Path,
    override_kernel_path: Option<&str>,
    max_jobs: usize,
    poll_seconds: u64,
    max_iterations: usize,
    session_id: &str,
) -> ShadowResult<SupervisorDaemonSnapshot> {
    let runtime_dir = ensure_runtime_dir(root)?;
    let supervisor_dir = runtime_dir.join("supervisor");
    fs::create_dir_all(&supervisor_dir).map_err(io_err)?;
    let runtime_state_path = supervisor_dir.join("runtime_state.json");
    let stop_request_path = supervisor_dir.join("stop.requested");
    let heartbeat_log_path = supervisor_dir.join("heartbeat.jsonl");
    let status_path = supervisor_dir.join("status.json");
    let booted_at = timestamp_now();
    let pid = std::process::id();

    if stop_request_path.exists() {
        fs::remove_file(&stop_request_path).map_err(io_err)?;
    }

    let mut total_processed = 0usize;
    let mut total_allowed = 0usize;
    let mut total_denied = 0usize;
    let mut total_failed = 0usize;
    let mut iterations_completed = 0usize;
    let mut stop_reason = "max_iterations_completed".to_string();

    write_supervisor_runtime_state(
        &runtime_state_path,
        session_id,
        pid,
        true,
        "running",
        &booted_at,
        "",
        poll_seconds,
        max_jobs,
        max_iterations,
        iterations_completed,
        total_processed,
        total_allowed,
        total_denied,
        total_failed,
        count_runtime_queue_entries(root, "pending")?,
        count_runtime_queue_entries(root, "processed")?,
        count_runtime_queue_entries(root, "failed")?,
        format!("daemon session {} booted", session_id),
    )?;

    for iteration in 0..max_iterations.max(1) {
        if stop_request_path.exists() {
            stop_reason = "stop_requested".to_string();
            break;
        }

        let run = run_supervisor(root, override_kernel_path, max_jobs)?;
        iterations_completed = iteration + 1;
        total_processed += run.processed;
        total_allowed += run.allowed;
        total_denied += run.denied;
        total_failed += run.failed;

        let pending_jobs = count_runtime_queue_entries(root, "pending")?;
        let processed_jobs = count_runtime_queue_entries(root, "processed")?;
        let failed_jobs = count_runtime_queue_entries(root, "failed")?;

        append_line(
            &heartbeat_log_path,
            &format!(
                "{{\"timestamp\":{},\"mode\":\"daemon\",\"session_id\":{},\"iteration\":{},\"processed\":{},\"allowed\":{},\"denied\":{},\"failed\":{},\"pending_jobs\":{},\"processed_jobs\":{},\"failed_jobs\":{},\"note\":{}}}\n",
                json_string(&timestamp_now()),
                json_string(session_id),
                iterations_completed,
                run.processed,
                run.allowed,
                run.denied,
                run.failed,
                pending_jobs,
                processed_jobs,
                failed_jobs,
                json_string(&run.note),
            ),
        )?;

        fs::write(
            &status_path,
            format!(
                "{{\n  \"status\": \"daemon_iteration_complete\",\n  \"updated_at\": {},\n  \"session_id\": {},\n  \"pid\": {},\n  \"iteration\": {},\n  \"poll_seconds\": {},\n  \"processed\": {},\n  \"allowed\": {},\n  \"denied\": {},\n  \"failed\": {},\n  \"pending_jobs\": {},\n  \"processed_jobs\": {},\n  \"failed_jobs\": {},\n  \"note\": {}\n}}\n",
                json_string(&timestamp_now()),
                json_string(session_id),
                pid,
                iterations_completed,
                poll_seconds,
                total_processed,
                total_allowed,
                total_denied,
                total_failed,
                pending_jobs,
                processed_jobs,
                failed_jobs,
                json_string(&run.note),
            ),
        )
        .map_err(io_err)?;

        write_supervisor_runtime_state(
            &runtime_state_path,
            session_id,
            pid,
            true,
            "running",
            &booted_at,
            "",
            poll_seconds,
            max_jobs,
            max_iterations,
            iterations_completed,
            total_processed,
            total_allowed,
            total_denied,
            total_failed,
            pending_jobs,
            processed_jobs,
            failed_jobs,
            format!(
                "daemon iteration {} complete; processed={} allowed={} denied={} failed={}",
                iterations_completed, total_processed, total_allowed, total_denied, total_failed
            ),
        )?;

        if iterations_completed >= max_iterations {
            break;
        }
        if poll_seconds > 0 {
            thread::sleep(Duration::from_secs(poll_seconds));
        } else {
            thread::sleep(Duration::from_millis(25));
        }
    }

    let stopped_at = timestamp_now();
    let pending_jobs = count_runtime_queue_entries(root, "pending")?;
    let processed_jobs = count_runtime_queue_entries(root, "processed")?;
    let failed_jobs = count_runtime_queue_entries(root, "failed")?;
    write_supervisor_runtime_state(
        &runtime_state_path,
        session_id,
        pid,
        false,
        if stop_reason == "stop_requested" {
            "stop_requested"
        } else {
            "completed"
        },
        &booted_at,
        &stopped_at,
        poll_seconds,
        max_jobs,
        max_iterations,
        iterations_completed,
        total_processed,
        total_allowed,
        total_denied,
        total_failed,
        pending_jobs,
        processed_jobs,
        failed_jobs,
        format!(
            "daemon session stopped via {} after {} iterations",
            stop_reason, iterations_completed
        ),
    )?;

    if stop_request_path.exists() {
        fs::remove_file(&stop_request_path).map_err(io_err)?;
    }

    supervisor_daemon_status(root)
}

pub fn supervisor_daemon_status(root: &Path) -> ShadowResult<SupervisorDaemonSnapshot> {
    let runtime_dir = ensure_runtime_dir(root)?;
    let supervisor_dir = runtime_dir.join("supervisor");
    fs::create_dir_all(&supervisor_dir).map_err(io_err)?;
    let runtime_state_path = supervisor_dir.join("runtime_state.json");
    let stop_request_path = supervisor_dir.join("stop.requested");
    let stdout_log_path = supervisor_dir.join("daemon.log");
    let heartbeat_log_path = supervisor_dir.join("heartbeat.jsonl");

    if !runtime_state_path.exists() {
        return Ok(SupervisorDaemonSnapshot {
            root: root.to_path_buf(),
            supervisor_dir,
            runtime_state_path,
            stop_request_path,
            stdout_log_path,
            available: false,
            session_id: String::new(),
            pid: 0,
            running: false,
            status: "not_started".to_string(),
            updated_at: "not_started".to_string(),
            booted_at: String::new(),
            stopped_at: String::new(),
            poll_seconds: 0,
            max_jobs: 0,
            max_iterations: 0,
            iterations_completed: 0,
            processed: 0,
            allowed: 0,
            denied: 0,
            failed: 0,
            pending_jobs: count_runtime_queue_entries(root, "pending")?,
            processed_jobs: count_runtime_queue_entries(root, "processed")?,
            failed_jobs: count_runtime_queue_entries(root, "failed")?,
            heartbeat_entries: 0,
            note: "no daemon state captured yet; run `loom supervisor daemon start` first"
                .to_string(),
        });
    }

    let contents = fs::read_to_string(&runtime_state_path).map_err(io_err)?;
    let pid = extract_json_number(&contents, "\"pid\"")
        .map(|value| value as u32)
        .unwrap_or(0);
    let running_flag = extract_json_bool(&contents, "\"running\"").unwrap_or(false);
    let alive = if pid > 0 {
        PathBuf::from(format!("/proc/{}", pid)).exists()
    } else {
        false
    };
    let status =
        extract_json_string(&contents, "\"status\"").unwrap_or_else(|| "unknown".to_string());
    let (heartbeat_entries, _) = if heartbeat_log_path.exists() {
        let heartbeat = fs::read_to_string(&heartbeat_log_path).map_err(io_err)?;
        let entries = heartbeat
            .lines()
            .filter(|line| !line.trim().is_empty())
            .count();
        (entries, ())
    } else {
        (0, ())
    };

    Ok(SupervisorDaemonSnapshot {
        root: root.to_path_buf(),
        supervisor_dir,
        runtime_state_path,
        stop_request_path,
        stdout_log_path,
        available: true,
        session_id: extract_json_string(&contents, "\"session_id\"").unwrap_or_default(),
        pid,
        running: running_flag && alive,
        status,
        updated_at: extract_json_string(&contents, "\"updated_at\"").unwrap_or_default(),
        booted_at: extract_json_string(&contents, "\"booted_at\"").unwrap_or_default(),
        stopped_at: extract_json_string(&contents, "\"stopped_at\"").unwrap_or_default(),
        poll_seconds: extract_json_number(&contents, "\"poll_seconds\"")
            .map(|value| value as u64)
            .unwrap_or(0),
        max_jobs: extract_json_number(&contents, "\"max_jobs\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        max_iterations: extract_json_number(&contents, "\"max_iterations\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        iterations_completed: extract_json_number(&contents, "\"iterations_completed\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        processed: extract_json_number(&contents, "\"processed\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        allowed: extract_json_number(&contents, "\"allowed\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        denied: extract_json_number(&contents, "\"denied\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        failed: extract_json_number(&contents, "\"failed\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        pending_jobs: extract_json_number(&contents, "\"pending_jobs\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        processed_jobs: extract_json_number(&contents, "\"processed_jobs\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        failed_jobs: extract_json_number(&contents, "\"failed_jobs\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        heartbeat_entries,
        note: extract_json_string(&contents, "\"note\"").unwrap_or_default(),
    })
}

pub fn request_supervisor_daemon_stop(root: &Path) -> ShadowResult<SupervisorDaemonSnapshot> {
    let runtime_dir = ensure_runtime_dir(root)?;
    let supervisor_dir = runtime_dir.join("supervisor");
    fs::create_dir_all(&supervisor_dir).map_err(io_err)?;
    let stop_request_path = supervisor_dir.join("stop.requested");
    fs::write(
        &stop_request_path,
        format!(
            "{{\n  \"status\": \"stop_requested\",\n  \"requested_at\": {}\n}}\n",
            json_string(&timestamp_now())
        ),
    )
    .map_err(io_err)?;
    let mut snapshot = supervisor_daemon_status(root)?;
    snapshot.note = format!(
        "{}; stop request recorded at {}",
        if snapshot.note.is_empty() {
            "stop requested".to_string()
        } else {
            snapshot.note.clone()
        },
        stop_request_path.display()
    );
    Ok(snapshot)
}

pub fn run_runtime_service_loop(
    root: &Path,
    override_kernel_path: Option<&str>,
    socket_override: Option<&str>,
    http_address: Option<&str>,
    service_token: Option<&str>,
    commitments_source: Option<&str>,
    workspace_token: Option<&str>,
    max_jobs: usize,
    poll_seconds: u64,
    max_iterations: usize,
    session_id: &str,
) -> ShadowResult<RuntimeServiceSnapshot> {
    ensure_runtime_service_dir(root)?;
    let socket_path = service_socket_path(root, socket_override)?;
    let runtime_state_path = runtime_service_state_path(root)?;
    let service_lock_path = service_lock_path(root)?;
    let metrics_path = service_metrics_path(root)?;
    let stop_request_path = service_stop_request_path(root)?;
    let event_log_path = runtime_service_event_log_path(root)?;
    let _ingress_stream_path = runtime_ingress_stream_path(root)?;
    let booted_at = timestamp_now();
    let pid = std::process::id();

    if stop_request_path.exists() {
        fs::remove_file(&stop_request_path).map_err(io_err)?;
    }
    if service_lock_path.exists() {
        let existing = fs::read_to_string(&service_lock_path).unwrap_or_default();
        let existing_pid = extract_json_number(&existing, "\"pid\"")
            .map(|value| value as u32)
            .unwrap_or(0);
        if existing_pid > 0 && PathBuf::from(format!("/proc/{}", existing_pid)).exists() {
            return Err(format!(
                "runtime service already appears to be running with pid {}",
                existing_pid
            ));
        }
        let _ = fs::remove_file(&service_lock_path);
    }
    if socket_path.exists() && !socket_path.is_dir() {
        fs::remove_file(&socket_path).map_err(io_err)?;
    }
    if let Some(parent) = socket_path.parent() {
        if parent.starts_with(root) {
            ensure_private_dir(parent)?;
        } else {
            fs::create_dir_all(parent).map_err(io_err)?;
        }
    }

    let listener = match UnixListener::bind(&socket_path) {
        Ok(listener) => match listener.set_nonblocking(true) {
            Ok(()) => Some(listener),
            Err(error) if error.kind() == ErrorKind::PermissionDenied => {
                append_line(
                        &event_log_path,
                        &format!(
                            "{{\"timestamp\":{},\"session_id\":{},\"status\":\"socket_nonblocking_unavailable\",\"socket_path\":{},\"note\":{}}}\n",
                            json_string(&timestamp_now()),
                            json_string(session_id),
                            json_string(&socket_path.display().to_string()),
                            json_string(&format!(
                                "socket ingress disabled because nonblocking mode is unavailable: {}",
                                error
                            )),
                        ),
                    )?;
                let _ = fs::remove_file(&socket_path);
                None
            }
            Err(error) => return Err(io_err(error)),
        },
        Err(error) => {
            append_line(
                &event_log_path,
                &format!(
                    "{{\"timestamp\":{},\"session_id\":{},\"status\":\"socket_bind_failed\",\"socket_path\":{},\"note\":{}}}\n",
                    json_string(&timestamp_now()),
                    json_string(session_id),
                    json_string(&socket_path.display().to_string()),
                    json_string(&format!(
                        "socket ingress unavailable; using file-backed ingress only: {}",
                        error
                    )),
                ),
            )?;
            None
        }
    };
    let http_listener = match http_address {
        Some(raw) if !raw.trim().is_empty() => match TcpListener::bind(raw) {
            Ok(listener) => {
                listener.set_nonblocking(true).map_err(io_err)?;
                Some(listener)
            }
            Err(error) => {
                append_line(
                    &event_log_path,
                    &format!(
                        "{{\"timestamp\":{},\"session_id\":{},\"status\":\"http_bind_failed\",\"http_address\":{},\"note\":{}}}\n",
                        json_string(&timestamp_now()),
                        json_string(session_id),
                        json_string(raw),
                        json_string(&format!(
                            "http control plane unavailable; continuing without HTTP ingress: {}",
                            error
                        )),
                    ),
                )?;
                None
            }
        },
        _ => None,
    };
    let resolved_http_address = http_listener
        .as_ref()
        .and_then(|listener| listener.local_addr().ok())
        .map(|addr| addr.to_string())
        .unwrap_or_default();
    let http_token_required = service_token
        .map(|token| !token.trim().is_empty())
        .unwrap_or(false);

    let mut iterations_completed = 0usize;
    let mut requests_received = 0usize;
    let mut submitted = 0usize;
    let mut processed = 0usize;
    let mut allowed = 0usize;
    let mut denied = 0usize;
    let mut failed = 0usize;
    let mut last_request_id = String::new();
    let mut last_job_id = String::new();
    let mut stop_reason = "max_iterations_completed".to_string();

    fs::write(
        &service_lock_path,
        format!(
            "{{\n  \"status\": \"locked\",\n  \"session_id\": {},\n  \"pid\": {},\n  \"created_at\": {},\n  \"socket_path\": {},\n  \"http_address\": {}\n}}\n",
            json_string(session_id),
            pid,
            json_string(&booted_at),
            json_string(&socket_path.display().to_string()),
            if resolved_http_address.is_empty() {
                "null".to_string()
            } else {
                json_string(&resolved_http_address)
            },
        ),
    )
    .map_err(io_err)?;
    ensure_private_file(&service_lock_path)?;

    write_runtime_service_state(
        &runtime_state_path,
        &metrics_path,
        &socket_path,
        if resolved_http_address.is_empty() {
            None
        } else {
            Some(resolved_http_address.as_str())
        },
        http_token_required,
        session_id,
        pid,
        true,
        "running",
        &booted_at,
        "",
        poll_seconds,
        max_jobs,
        max_iterations,
        iterations_completed,
        requests_received,
        submitted,
        processed,
        allowed,
        denied,
        failed,
        count_runtime_queue_entries(root, "pending")?,
        count_runtime_queue_entries(root, "processed")?,
        count_runtime_queue_entries(root, "failed")?,
        "",
        "",
        if listener.is_some() {
            if resolved_http_address.is_empty() {
                format!("runtime service {} booted with socket ingress", session_id)
            } else {
                format!(
                    "runtime service {} booted with socket ingress + http control plane at {}",
                    session_id, resolved_http_address
                )
            }
        } else {
            if resolved_http_address.is_empty() {
                format!(
                    "runtime service {} booted with file-backed ingress only",
                    session_id
                )
            } else {
                format!(
                    "runtime service {} booted with file-backed ingress + http control plane at {}",
                    session_id, resolved_http_address
                )
            }
        },
    )?;

    for iteration in 0..max_iterations.max(1) {
        if stop_request_path.exists() {
            stop_reason = "stop_requested".to_string();
            break;
        }

        if let Some(listener) = listener.as_ref() {
            loop {
                match listener.accept() {
                    Ok((mut stream, _addr)) => {
                        let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
                        let _ = stream.set_write_timeout(Some(Duration::from_secs(5)));
                        let request_contents = read_stream_string(&mut stream)?;
                        let reply = match handle_runtime_service_request(
                            root,
                            override_kernel_path,
                            &socket_path.display().to_string(),
                            "socket",
                            &request_contents,
                        ) {
                            Ok(reply) => reply,
                            Err(error) => RuntimeServiceReply::bad_request(
                                "socket",
                                format!("rejected malformed socket request: {}", error),
                            ),
                        };
                        requests_received += 1;
                        if reply.status == "accepted" {
                            submitted += 1;
                            last_request_id = reply.request_id.clone();
                            last_job_id = reply.job_id.clone();
                        } else if reply.status == "stop_requested" {
                            last_request_id = reply.request_id.clone();
                        }
                        append_line(
                            &event_log_path,
                            &format!(
                                "{{\"timestamp\":{},\"session_id\":{},\"request_id\":{},\"status\":{},\"transport\":{},\"job_id\":{},\"note\":{}}}\n",
                                json_string(&timestamp_now()),
                                json_string(session_id),
                                json_string(&reply.request_id),
                                json_string(&reply.status),
                                json_string(&reply.transport),
                                json_string(&reply.job_id),
                                json_string(&reply.note),
                            ),
                        )?;
                        if let Err(error) = stream.write_all(reply.payload.as_bytes()) {
                            if is_client_disconnect_error(&error) {
                                continue;
                            }
                            return Err(io_err(error));
                        }
                        if let Err(error) = stream.flush() {
                            if is_client_disconnect_error(&error) {
                                continue;
                            }
                            return Err(io_err(error));
                        }
                        if reply.status == "stop_requested" {
                            stop_reason = "stop_requested".to_string();
                        }
                    }
                    Err(error) if error.kind() == ErrorKind::WouldBlock => break,
                    Err(error) => return Err(io_err(error)),
                }
            }
        }

        if let Some(http_listener) = http_listener.as_ref() {
            loop {
                match http_listener.accept() {
                    Ok((mut stream, _addr)) => {
                        let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
                        let _ = stream.set_write_timeout(Some(Duration::from_secs(5)));
                        let request_contents = read_http_request_stream(&mut stream)?;
                        let reply = handle_runtime_service_http_request(
                            root,
                            override_kernel_path,
                            &resolved_http_address,
                            service_token,
                            &request_contents,
                        )?;
                        requests_received += 1;
                        if reply.status == "accepted" || reply.status == "commitment_imported" {
                            submitted += 1;
                            last_request_id = reply.request_id.clone();
                            if !reply.job_id.is_empty() {
                                last_job_id = reply.job_id.clone();
                            }
                        } else if reply.status == "stop_requested" {
                            last_request_id = reply.request_id.clone();
                            stop_reason = "stop_requested".to_string();
                        }
                        append_line(
                            &event_log_path,
                            &format!(
                                "{{\"timestamp\":{},\"session_id\":{},\"request_id\":{},\"status\":{},\"transport\":{},\"job_id\":{},\"note\":{}}}\n",
                                json_string(&timestamp_now()),
                                json_string(session_id),
                                json_string(&reply.request_id),
                                json_string(&reply.status),
                                json_string(&reply.transport),
                                json_string(&reply.job_id),
                                json_string(&reply.note),
                            ),
                        )?;
                        let http_response =
                            build_http_response(reply.http_status_code, &reply.payload);
                        if let Err(error) = stream.write_all(http_response.as_bytes()) {
                            if is_client_disconnect_error(&error) {
                                continue;
                            }
                            return Err(io_err(error));
                        }
                        if let Err(error) = stream.flush() {
                            if is_client_disconnect_error(&error) {
                                continue;
                            }
                            return Err(io_err(error));
                        }
                    }
                    Err(error) if error.kind() == ErrorKind::WouldBlock => break,
                    Err(error) => return Err(io_err(error)),
                }
            }
        }

        for request_path in collect_pending_runtime_ingress_requests(root)? {
            let request_contents = fs::read_to_string(&request_path).map_err(io_err)?;
            let reply = match handle_runtime_service_request(
                root,
                override_kernel_path,
                &socket_path.display().to_string(),
                "file_ingress",
                &request_contents,
            ) {
                Ok(reply) => reply,
                Err(error) => RuntimeServiceReply::bad_request(
                    "file_ingress",
                    format!(
                        "rejected malformed file ingress request {}: {}",
                        request_path.display(),
                        error
                    ),
                ),
            };
            requests_received += 1;
            if reply.status == "accepted" {
                submitted += 1;
                last_request_id = reply.request_id.clone();
                last_job_id = reply.job_id.clone();
            } else if reply.status == "stop_requested" {
                last_request_id = reply.request_id.clone();
                stop_reason = "stop_requested".to_string();
            }
            append_line(
                &event_log_path,
                &format!(
                    "{{\"timestamp\":{},\"session_id\":{},\"request_id\":{},\"status\":{},\"job_id\":{},\"note\":{},\"transport\":\"file_ingress\"}}\n",
                    json_string(&timestamp_now()),
                    json_string(session_id),
                    json_string(&reply.request_id),
                    json_string(&reply.status),
                    json_string(&reply.job_id),
                    json_string(&reply.note),
                ),
            )?;
        }

        if let Some(commitments_source) = commitments_source {
            let import = import_commitment_execution_requests(
                root,
                override_kernel_path,
                commitments_source,
                workspace_token,
            )?;
            if import.imported > 0 {
                submitted += import.imported;
                last_request_id = import.last_import_id.clone();
                last_job_id = import.last_job_id.clone();
                append_line(
                    &event_log_path,
                    &format!(
                        "{{\"timestamp\":{},\"session_id\":{},\"status\":\"commitment_imported\",\"imported\":{},\"skipped\":{},\"last_import_id\":{},\"last_job_id\":{},\"source\":{},\"note\":{}}}\n",
                        json_string(&timestamp_now()),
                        json_string(session_id),
                        import.imported,
                        import.skipped,
                        json_string(&import.last_import_id),
                        json_string(&import.last_job_id),
                        json_string(&import.commitments_source),
                        json_string(&import.note),
                    ),
                )?;
            }
        }

        let run = run_supervisor(root, override_kernel_path, max_jobs)?;
        iterations_completed = iteration + 1;
        processed += run.processed;
        allowed += run.allowed;
        denied += run.denied;
        failed += run.failed;

        let pending_jobs = count_runtime_queue_entries(root, "pending")?;
        let processed_jobs = count_runtime_queue_entries(root, "processed")?;
        let failed_jobs = count_runtime_queue_entries(root, "failed")?;
        write_runtime_service_state(
            &runtime_state_path,
            &metrics_path,
            &socket_path,
            if resolved_http_address.is_empty() {
                None
            } else {
                Some(resolved_http_address.as_str())
            },
            http_token_required,
            session_id,
            pid,
            true,
            "running",
            &booted_at,
            "",
            poll_seconds,
            max_jobs,
            max_iterations,
            iterations_completed,
            requests_received,
            submitted,
            processed,
            allowed,
            denied,
            failed,
            pending_jobs,
            processed_jobs,
            failed_jobs,
            &last_request_id,
            &last_job_id,
            format!(
                "service iteration {} complete; submitted={} processed={} allowed={} denied={} failed={}",
                iterations_completed, submitted, processed, allowed, denied, failed
            ),
        )?;

        append_line(
            &event_log_path,
            &format!(
                "{{\"timestamp\":{},\"session_id\":{},\"status\":\"iteration_complete\",\"iteration\":{},\"submitted\":{},\"processed\":{},\"allowed\":{},\"denied\":{},\"failed\":{},\"pending_jobs\":{},\"processed_jobs\":{},\"failed_jobs\":{},\"last_request_id\":{},\"last_job_id\":{}}}\n",
                json_string(&timestamp_now()),
                json_string(session_id),
                iterations_completed,
                submitted,
                processed,
                allowed,
                denied,
                failed,
                pending_jobs,
                processed_jobs,
                failed_jobs,
                json_string(&last_request_id),
                json_string(&last_job_id),
            ),
        )?;

        if stop_reason == "stop_requested" {
            break;
        }
        if iterations_completed >= max_iterations {
            break;
        }
        if poll_seconds > 0 {
            thread::sleep(Duration::from_secs(poll_seconds));
        }
    }

    drop(listener);
    drop(http_listener);
    if socket_path.exists() && !socket_path.is_dir() {
        fs::remove_file(&socket_path).map_err(io_err)?;
    }

    let stopped_at = timestamp_now();
    write_runtime_service_state(
        &runtime_state_path,
        &metrics_path,
        &socket_path,
        if resolved_http_address.is_empty() {
            None
        } else {
            Some(resolved_http_address.as_str())
        },
        http_token_required,
        session_id,
        pid,
        false,
        if stop_reason == "stop_requested" {
            "stop_requested"
        } else {
            "completed"
        },
        &booted_at,
        &stopped_at,
        poll_seconds,
        max_jobs,
        max_iterations,
        iterations_completed,
        requests_received,
        submitted,
        processed,
        allowed,
        denied,
        failed,
        count_runtime_queue_entries(root, "pending")?,
        count_runtime_queue_entries(root, "processed")?,
        count_runtime_queue_entries(root, "failed")?,
        &last_request_id,
        &last_job_id,
        format!(
            "runtime service stopped via {} after {} iterations",
            stop_reason, iterations_completed
        ),
    )?;

    if stop_request_path.exists() {
        fs::remove_file(&stop_request_path).map_err(io_err)?;
    }
    if service_lock_path.exists() {
        let _ = fs::remove_file(&service_lock_path);
    }

    runtime_service_status(root, socket_override)
}

pub fn runtime_service_status(
    root: &Path,
    socket_override: Option<&str>,
) -> ShadowResult<RuntimeServiceSnapshot> {
    let service_dir = ensure_runtime_service_dir(root)?;
    let socket_path = service_socket_path(root, socket_override)?;
    let runtime_state_path = runtime_service_state_path(root)?;
    let service_lock_path = service_lock_path(root)?;
    let metrics_path = service_metrics_path(root)?;
    let stop_request_path = service_stop_request_path(root)?;
    let stdout_log_path = service_stdout_log_path(root)?;
    let event_log_path = runtime_service_event_log_path(root)?;
    let ingress_stream_path = runtime_ingress_stream_path(root)?;
    let config_path = root.join("loom.toml");

    if !runtime_state_path.exists() {
        return Ok(RuntimeServiceSnapshot {
            root: root.to_path_buf(),
            service_dir,
            service_lock_path,
            metrics_path,
            config_path,
            socket_path,
            http_address: String::new(),
            http_token_required: false,
            runtime_state_path,
            stop_request_path,
            stdout_log_path,
            event_log_path,
            ingress_stream_path,
            available: false,
            session_id: String::new(),
            pid: 0,
            running: false,
            status: "not_started".to_string(),
            updated_at: "not_started".to_string(),
            booted_at: String::new(),
            stopped_at: String::new(),
            poll_seconds: 0,
            max_jobs: 0,
            max_iterations: 0,
            iterations_completed: 0,
            requests_received: 0,
            submitted: 0,
            processed: 0,
            allowed: 0,
            denied: 0,
            failed: 0,
            pending_jobs: count_runtime_queue_entries(root, "pending")?,
            processed_jobs: count_runtime_queue_entries(root, "processed")?,
            failed_jobs: count_runtime_queue_entries(root, "failed")?,
            last_request_id: String::new(),
            last_job_id: String::new(),
            note: "no runtime service state captured yet; run `loom service start` first"
                .to_string(),
        });
    }

    let contents = fs::read_to_string(&runtime_state_path).map_err(io_err)?;
    let pid = extract_json_number(&contents, "\"pid\"")
        .map(|value| value as u32)
        .unwrap_or(0);
    let running_flag = extract_json_bool(&contents, "\"running\"").unwrap_or(false);
    let http_address = extract_optional_string(&contents, "\"http_address\"").unwrap_or_default();
    let http_token_required =
        extract_json_bool(&contents, "\"http_token_required\"").unwrap_or(false);
    let proc_visible = if pid > 0 {
        PathBuf::from(format!("/proc/{}", pid)).exists()
    } else {
        false
    };
    let alive = runtime_service_control_plane_alive(pid, proc_visible, &socket_path, &http_address);
    let recorded_status =
        extract_json_string(&contents, "\"status\"").unwrap_or_else(|| "unknown".to_string());
    let derived_status = if running_flag && !alive {
        "crashed".to_string()
    } else {
        recorded_status
    };
    let recorded_note = extract_json_string(&contents, "\"note\"").unwrap_or_default();
    let derived_note = if running_flag && !alive && pid > 0 {
        format!(
            "runtime service state claims pid {} is running, but the process is gone; clean stale state before reusing the root",
            pid
        )
    } else if running_flag && alive && pid > 0 && !proc_visible {
        format!(
            "runtime service control plane is reachable, but pid {} is not visible from this context; using socket/http liveness",
            pid
        )
    } else {
        recorded_note
    };

    Ok(RuntimeServiceSnapshot {
        root: root.to_path_buf(),
        service_dir,
        service_lock_path,
        metrics_path,
        config_path,
        socket_path,
        http_address,
        http_token_required,
        runtime_state_path,
        stop_request_path,
        stdout_log_path,
        event_log_path,
        ingress_stream_path,
        available: true,
        session_id: extract_json_string(&contents, "\"session_id\"").unwrap_or_default(),
        pid,
        running: running_flag && alive,
        status: derived_status,
        updated_at: extract_json_string(&contents, "\"updated_at\"").unwrap_or_default(),
        booted_at: extract_json_string(&contents, "\"booted_at\"").unwrap_or_default(),
        stopped_at: extract_json_string(&contents, "\"stopped_at\"").unwrap_or_default(),
        poll_seconds: extract_json_number(&contents, "\"poll_seconds\"")
            .map(|value| value as u64)
            .unwrap_or(0),
        max_jobs: extract_json_number(&contents, "\"max_jobs\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        max_iterations: extract_json_number(&contents, "\"max_iterations\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        iterations_completed: extract_json_number(&contents, "\"iterations_completed\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        requests_received: extract_json_number(&contents, "\"requests_received\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        submitted: extract_json_number(&contents, "\"submitted\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        processed: extract_json_number(&contents, "\"processed\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        allowed: extract_json_number(&contents, "\"allowed\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        denied: extract_json_number(&contents, "\"denied\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        failed: extract_json_number(&contents, "\"failed\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        pending_jobs: extract_json_number(&contents, "\"pending_jobs\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        processed_jobs: extract_json_number(&contents, "\"processed_jobs\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        failed_jobs: extract_json_number(&contents, "\"failed_jobs\"")
            .map(|value| value as usize)
            .unwrap_or(0),
        last_request_id: extract_json_string(&contents, "\"last_request_id\"").unwrap_or_default(),
        last_job_id: extract_json_string(&contents, "\"last_job_id\"").unwrap_or_default(),
        note: derived_note,
    })
}

fn runtime_service_control_plane_alive(
    pid: u32,
    proc_visible: bool,
    socket_path: &Path,
    http_address: &str,
) -> bool {
    if pid > 0 && proc_visible {
        return true;
    }
    if runtime_service_tcp_reachable(http_address) {
        return true;
    }
    runtime_service_socket_reachable(socket_path)
}

fn runtime_service_tcp_reachable(http_address: &str) -> bool {
    let target = http_address.trim();
    if target.is_empty() {
        return false;
    }
    let timeout = Duration::from_millis(250);
    match target.to_socket_addrs() {
        Ok(addrs) => {
            for addr in addrs {
                if let Ok(stream) = TcpStream::connect_timeout(&addr, timeout) {
                    let _ = stream.shutdown(Shutdown::Both);
                    return true;
                }
            }
            false
        }
        Err(_) => false,
    }
}

fn runtime_service_socket_reachable(socket_path: &Path) -> bool {
    if !socket_path.exists() || socket_path.is_dir() {
        return false;
    }
    match UnixStream::connect(socket_path) {
        Ok(stream) => {
            let _ = stream.shutdown(Shutdown::Both);
            true
        }
        Err(_) => false,
    }
}

pub fn request_runtime_service_stop(
    root: &Path,
    socket_override: Option<&str>,
) -> ShadowResult<RuntimeServiceSnapshot> {
    let stop_request_path = service_stop_request_path(root)?;
    fs::write(
        &stop_request_path,
        format!(
            "{{\n  \"status\": \"stop_requested\",\n  \"requested_at\": {}\n}}\n",
            json_string(&timestamp_now())
        ),
    )
    .map_err(io_err)?;
    ensure_private_file(&stop_request_path)?;
    let mut snapshot = runtime_service_status(root, socket_override)?;
    snapshot.note = format!(
        "{}; stop request recorded at {}",
        if snapshot.note.is_empty() {
            "stop requested".to_string()
        } else {
            snapshot.note.clone()
        },
        stop_request_path.display()
    );
    Ok(snapshot)
}

pub fn submit_runtime_service_action(
    root: &Path,
    socket_override: Option<&str>,
    http_url: Option<&str>,
    service_token: Option<&str>,
    kernel_path: &Path,
    envelope: &ActionEnvelope,
) -> ShadowResult<RuntimeServiceSubmitCapture> {
    let socket_path = service_socket_path(root, socket_override)?;
    let request_id = canonical_join_runtime(&[
        "ingress",
        &envelope.org_id,
        &envelope.agent_id,
        &envelope.action_type,
        &envelope_input_hash(envelope),
        &timestamp_now(),
    ]);
    let request = format!(
        "{{\"request_type\":{},\"request_id\":{},\"agent_id\":{},\"org_id\":{},\"action_type\":{},\"resource\":{},\"capability_name\":{},\"payload_json\":{},\"estimated_cost_usd\":{:.6},\"run_id\":{},\"session_id\":{},\"kernel_path\":{}}}\n",
        json_string("submit_action"),
        json_string(&request_id),
        json_string(&envelope.agent_id),
        json_string(&envelope.org_id),
        json_string(&envelope.action_type),
        json_string(&envelope.resource),
        json_string(&envelope.capability_name),
        json_string(&envelope.payload_json),
        envelope.estimated_cost_usd,
        json_string(&envelope.run_id),
        json_string(&envelope.session_id),
        json_string(&kernel_path.display().to_string()),
    );

    let service_snapshot = runtime_service_status(root, socket_override)?;
    let service_running = service_snapshot.available && service_snapshot.running;
    let explicit_http_url = http_url
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty());
    if let Some(http_url) = explicit_http_url.as_deref() {
        if !service_running {
            return Err(
                "runtime service is not running; start it with `loom service start` first"
                    .to_string(),
            );
        }
        let reply = send_runtime_service_http_request(
            http_url,
            "POST",
            "/submit",
            Some(&request),
            service_token,
        )?;
        let body = extract_http_body(&reply);
        let status =
            extract_json_string(&body, "\"status\"").unwrap_or_else(|| "unknown".to_string());
        if status != "accepted" {
            return Err(format!(
                "runtime service submission failed: {}",
                extract_json_string(&body, "\"note\"").unwrap_or(body)
            ));
        }
        return Ok(RuntimeServiceSubmitCapture {
            request_id: extract_json_string(&body, "\"request_id\"").unwrap_or(request_id),
            transport: extract_json_string(&body, "\"transport\"")
                .unwrap_or_else(|| "http".to_string()),
            service_target: extract_json_string(&body, "\"service_target\"")
                .unwrap_or_else(|| http_url.to_string()),
            socket_path,
            ingress_request_path: PathBuf::from(
                extract_json_string(&body, "\"ingress_request_path\"").unwrap_or_default(),
            ),
            ingress_receipt_path: PathBuf::from(
                extract_json_string(&body, "\"ingress_receipt_path\"").unwrap_or_default(),
            ),
            job_id: extract_json_string(&body, "\"job_id\"").unwrap_or_default(),
            policy_class: extract_json_string(&body, "\"policy_class\"").unwrap_or_default(),
            queue_path: PathBuf::from(
                extract_json_string(&body, "\"queue_path\"").unwrap_or_default(),
            ),
            accepted_at: extract_json_string(&body, "\"accepted_at\"").unwrap_or_default(),
            note: extract_json_string(&body, "\"note\"").unwrap_or_default(),
        });
    } else if service_running && socket_path.exists() && !socket_path.is_dir() {
        if let Ok(reply) = send_runtime_service_request(&socket_path, &request) {
            let status =
                extract_json_string(&reply, "\"status\"").unwrap_or_else(|| "unknown".to_string());
            if status != "accepted" {
                return Err(format!(
                    "runtime service submission failed: {}",
                    extract_json_string(&reply, "\"note\"").unwrap_or(reply)
                ));
            }
            return Ok(RuntimeServiceSubmitCapture {
                request_id: extract_json_string(&reply, "\"request_id\"").unwrap_or(request_id),
                transport: extract_json_string(&reply, "\"transport\"")
                    .unwrap_or_else(|| "socket".to_string()),
                service_target: extract_json_string(&reply, "\"service_target\"")
                    .unwrap_or_else(|| socket_path.display().to_string()),
                socket_path,
                ingress_request_path: PathBuf::from(
                    extract_json_string(&reply, "\"ingress_request_path\"").unwrap_or_default(),
                ),
                ingress_receipt_path: PathBuf::from(
                    extract_json_string(&reply, "\"ingress_receipt_path\"").unwrap_or_default(),
                ),
                job_id: extract_json_string(&reply, "\"job_id\"").unwrap_or_default(),
                policy_class: extract_json_string(&reply, "\"policy_class\"").unwrap_or_default(),
                queue_path: PathBuf::from(
                    extract_json_string(&reply, "\"queue_path\"").unwrap_or_default(),
                ),
                accepted_at: extract_json_string(&reply, "\"accepted_at\"").unwrap_or_default(),
                note: extract_json_string(&reply, "\"note\"").unwrap_or_default(),
            });
        }
    }

    let ingress_request_path = runtime_ingress_request_path(root, &request_id)?;
    let ingress_receipt_path = runtime_ingress_receipt_path(root, &request_id)?;
    fs::write(
        &ingress_request_path,
        format!(
            "{{\n  \"status\": \"staged\",\n  \"request_id\": {},\n  \"request_type\": {},\n  \"received_at\": {},\n  \"transport\": \"file_ingress\",\n  \"socket_path\": {},\n  \"agent_id\": {},\n  \"org_id\": {},\n  \"action_type\": {},\n  \"resource\": {},\n  \"capability_name\": {},\n  \"payload_json\": {},\n  \"estimated_cost_usd\": {:.6},\n  \"run_id\": {},\n  \"session_id\": {},\n  \"kernel_path\": {}\n}}\n",
            json_string(&request_id),
            json_string("submit_action"),
            json_string(&timestamp_now()),
            json_string(&socket_path.display().to_string()),
            json_string(&envelope.agent_id),
            json_string(&envelope.org_id),
            json_string(&envelope.action_type),
            json_string(&envelope.resource),
            json_string(&envelope.capability_name),
            json_string(&envelope.payload_json),
            envelope.estimated_cost_usd,
            json_string(&envelope.run_id),
            json_string(&envelope.session_id),
            json_string(&kernel_path.display().to_string()),
        ),
    )
    .map_err(io_err)?;
    append_line(
        &runtime_ingress_stream_path(root)?,
        &format!(
            "{{\"timestamp\":{},\"request_id\":{},\"status\":\"staged\",\"transport\":\"file_ingress\",\"socket_path\":{},\"job_id\":{},\"note\":\"service submit staged request for file-backed ingress\"}}\n",
            json_string(&timestamp_now()),
            json_string(&request_id),
            json_string(&socket_path.display().to_string()),
            json_string(&envelope_input_hash(envelope)),
        ),
    )?;

    for _ in 0..25 {
        if ingress_receipt_path.exists() {
            let reply = fs::read_to_string(&ingress_receipt_path).map_err(io_err)?;
            return Ok(RuntimeServiceSubmitCapture {
                request_id: extract_json_string(&reply, "\"request_id\"").unwrap_or(request_id),
                transport: extract_json_string(&reply, "\"transport\"")
                    .unwrap_or_else(|| "file_ingress".to_string()),
                service_target: extract_json_string(&reply, "\"service_target\"")
                    .unwrap_or_else(|| socket_path.display().to_string()),
                socket_path,
                ingress_request_path,
                ingress_receipt_path,
                job_id: extract_json_string(&reply, "\"job_id\"")
                    .unwrap_or_else(|| envelope_input_hash(envelope)),
                policy_class: extract_json_string(&reply, "\"policy_class\"").unwrap_or_default(),
                queue_path: PathBuf::from(
                    extract_json_string(&reply, "\"queue_path\"").unwrap_or_default(),
                ),
                accepted_at: extract_json_string(&reply, "\"accepted_at\"").unwrap_or_default(),
                note: format!(
                    "{} via file-backed transport",
                    extract_json_string(&reply, "\"note\"")
                        .unwrap_or_else(|| "service ingress accepted".to_string())
                ),
            });
        }
        thread::sleep(Duration::from_millis(100));
    }

    let fallback_policy_class =
        classify_action(&envelope.action_type, envelope.estimated_cost_usd, false)
            .label()
            .to_string();
    Ok(RuntimeServiceSubmitCapture {
        request_id,
        transport: "file_ingress".to_string(),
        service_target: socket_path.display().to_string(),
        socket_path,
        ingress_request_path,
        ingress_receipt_path,
        job_id: envelope_input_hash(envelope),
        policy_class: fallback_policy_class.clone(),
        queue_path: pending_queue_dir(
            root,
            PolicyClass::from_label(&fallback_policy_class).unwrap_or(PolicyClass::Standard),
        )?
        .join(format!(
            "{}.json",
            sanitize_filename(&envelope_input_hash(envelope))
        )),
        accepted_at: timestamp_now(),
        note: "service request staged for file-backed ingress; awaiting acceptance receipt"
            .to_string(),
    })
}

pub fn request_runtime_service_cancel(
    root: &Path,
    socket_override: Option<&str>,
    http_url: Option<&str>,
    service_token: Option<&str>,
    job_id: &str,
) -> ShadowResult<RuntimeServiceCancelCapture> {
    let socket_path = service_socket_path(root, socket_override)?;
    let request_id = canonical_join_runtime(&["cancel", job_id, &timestamp_now()]);
    let request = format!(
        "{{\"request_type\":{},\"request_id\":{},\"job_id\":{}}}\n",
        json_string("cancel_job"),
        json_string(&request_id),
        json_string(job_id),
    );

    let service_snapshot = runtime_service_status(root, socket_override)?;
    if !service_snapshot.available || !service_snapshot.running {
        return Err(
            "runtime service is not running; start it with `loom service start` first".to_string(),
        );
    }

    let explicit_http_url = http_url
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty());
    let fallback_http_url = if service_snapshot.http_address.trim().is_empty() {
        None
    } else {
        Some(format!("http://{}", service_snapshot.http_address))
    };

    if let Some(http_url) = explicit_http_url.as_deref() {
        let reply = send_runtime_service_http_request(
            http_url,
            "POST",
            "/cancel",
            Some(&format!(
                "{{\"request_id\":{},\"job_id\":{}}}\n",
                json_string(&request_id),
                json_string(job_id),
            )),
            service_token,
        )?;
        let body = extract_http_body(&reply);
        return parse_runtime_service_cancel_capture(
            &body,
            &request_id,
            http_url,
            &socket_path,
            "http",
            job_id,
        );
    }

    if socket_path.exists() && !socket_path.is_dir() {
        if let Ok(reply) = send_runtime_service_request(&socket_path, &request) {
            return parse_runtime_service_cancel_capture(
                &reply,
                &request_id,
                &socket_path.display().to_string(),
                &socket_path,
                "socket",
                job_id,
            );
        }
    }

    if let Some(http_url) = fallback_http_url.as_deref() {
        let reply = send_runtime_service_http_request(
            http_url,
            "POST",
            "/cancel",
            Some(&format!(
                "{{\"request_id\":{},\"job_id\":{}}}\n",
                json_string(&request_id),
                json_string(job_id),
            )),
            service_token,
        )?;
        let body = extract_http_body(&reply);
        return parse_runtime_service_cancel_capture(
            &body,
            &request_id,
            http_url,
            &socket_path,
            "http",
            job_id,
        );
    }

    Err("runtime service cancel requires the local HTTP or socket control plane".to_string())
}

fn parse_runtime_service_cancel_capture(
    reply: &str,
    fallback_request_id: &str,
    service_target: &str,
    socket_path: &Path,
    fallback_transport: &str,
    fallback_job_id: &str,
) -> ShadowResult<RuntimeServiceCancelCapture> {
    let status = extract_json_string(reply, "\"status\"").unwrap_or_else(|| "unknown".to_string());
    let note = extract_json_string(reply, "\"note\"").unwrap_or_else(|| reply.trim().to_string());
    let lowered_note = note.to_ascii_lowercase();
    if lowered_note.contains("unsupported route") || lowered_note.contains("unknown request_type") {
        return Err(format!("runtime service cancel failed: {}", note));
    }

    let capture = RuntimeServiceCancelCapture {
        request_id: extract_json_string(reply, "\"request_id\"")
            .unwrap_or_else(|| fallback_request_id.to_string()),
        transport: extract_json_string(reply, "\"transport\"")
            .unwrap_or_else(|| fallback_transport.to_string()),
        service_target: service_target.to_string(),
        socket_path: socket_path.to_path_buf(),
        job_id: extract_json_string(reply, "\"job_id\"")
            .unwrap_or_else(|| fallback_job_id.to_string()),
        status: status.clone(),
        current_status: extract_json_string(reply, "\"current_status\"").unwrap_or_default(),
        previous_status: extract_json_string(reply, "\"previous_status\"").unwrap_or_default(),
        note,
    };

    match status.as_str() {
        "cancelled" | "not_cancelable" | "not_found" => Ok(capture),
        _ => Err(format!(
            "runtime service cancel failed: {}",
            if capture.note.trim().is_empty() {
                reply.trim().to_string()
            } else {
                capture.note.clone()
            }
        )),
    }
}

struct RuntimeServiceReply {
    status: String,
    transport: String,
    request_id: String,
    job_id: String,
    note: String,
    http_status_code: u16,
    payload: String,
}

impl RuntimeServiceReply {
    fn bad_request(transport: &str, note: String) -> Self {
        let request_id = canonical_join_runtime(&[transport, "bad-request", &timestamp_now()]);
        let payload = format!(
            "{{\"status\":\"bad_request\",\"request_id\":{},\"note\":{}}}\n",
            json_string(&request_id),
            json_string(&note),
        );
        Self {
            status: "bad_request".to_string(),
            transport: transport.to_string(),
            request_id,
            job_id: String::new(),
            note,
            http_status_code: 400,
            payload,
        }
    }

    fn unsupported_media_type(transport: &str, note: String) -> Self {
        let request_id =
            canonical_join_runtime(&[transport, "unsupported-media-type", &timestamp_now()]);
        let payload = format!(
            "{{\"status\":\"unsupported_media_type\",\"request_id\":{},\"note\":{}}}\n",
            json_string(&request_id),
            json_string(&note),
        );
        Self {
            status: "unsupported_media_type".to_string(),
            transport: transport.to_string(),
            request_id,
            job_id: String::new(),
            note,
            http_status_code: 415,
            payload,
        }
    }
}

fn handle_runtime_service_request(
    root: &Path,
    override_kernel_path: Option<&str>,
    ingress_target: &str,
    transport: &str,
    request_contents: &str,
) -> ShadowResult<RuntimeServiceReply> {
    let request_body = serde_json::from_str::<Value>(request_contents).unwrap_or(Value::Null);
    let request_type = {
        let parsed = value_string(request_body.get("request_type"));
        if parsed.is_empty() {
            extract_json_string(request_contents, "\"request_type\"")
                .unwrap_or_else(|| "unknown".to_string())
        } else {
            parsed
        }
    };
    let request_id = {
        let parsed = value_string(request_body.get("request_id"));
        if parsed.is_empty() {
            extract_json_string(request_contents, "\"request_id\"")
                .unwrap_or_else(|| canonical_join_runtime(&["ingress", &timestamp_now()]))
        } else {
            parsed
        }
    };

    match request_type.as_str() {
        "submit_action" => {
            let agent_id = {
                let value = value_string(request_body.get("agent_id"));
                if value.is_empty() {
                    extract_json_string(request_contents, "\"agent_id\"")
                        .ok_or_else(|| "service request missing agent_id".to_string())?
                } else {
                    value
                }
            };
            let org_id = {
                let value = value_string(request_body.get("org_id"));
                if value.is_empty() {
                    extract_json_string(request_contents, "\"org_id\"")
                        .unwrap_or_else(|| "local_foundry".to_string())
                } else {
                    value
                }
            };
            let action_type = {
                let value = value_string(request_body.get("action_type"));
                if value.is_empty() {
                    extract_json_string(request_contents, "\"action_type\"")
                        .ok_or_else(|| "service request missing action_type".to_string())?
                } else {
                    value
                }
            };
            let resource = {
                let value = value_string(request_body.get("resource"));
                if value.is_empty() {
                    extract_json_string(request_contents, "\"resource\"")
                        .ok_or_else(|| "service request missing resource".to_string())?
                } else {
                    value
                }
            };
            let estimated_cost_usd = request_body
                .get("estimated_cost_usd")
                .and_then(Value::as_f64)
                .or_else(|| extract_json_number(request_contents, "\"estimated_cost_usd\""))
                .unwrap_or(0.0);
            let run_id = {
                let value = value_string(request_body.get("run_id"));
                if value.is_empty() {
                    extract_json_string(request_contents, "\"run_id\"")
                } else {
                    Some(value)
                }
            };
            let session_id = {
                let value = value_string(request_body.get("session_id"));
                if value.is_empty() {
                    extract_json_string(request_contents, "\"session_id\"")
                } else {
                    Some(value)
                }
            };
            let capability_name = {
                let value = value_string(request_body.get("capability_name"));
                if value.is_empty() {
                    extract_json_string(request_contents, "\"capability_name\"")
                } else {
                    Some(value)
                }
            };
            let payload_json = {
                let value = value_json_string(
                    request_body
                        .get("payload_json")
                        .or_else(|| request_body.get("payload")),
                );
                if value.is_empty() {
                    extract_json_string(request_contents, "\"payload_json\"")
                } else {
                    Some(value)
                }
            };
            let kernel_path_raw = {
                let value = value_string(request_body.get("kernel_path"));
                if value.is_empty() {
                    extract_json_string(request_contents, "\"kernel_path\"")
                        .or_else(|| override_kernel_path.map(|value| value.to_string()))
                        .unwrap_or_default()
                } else {
                    value
                }
            };
            let effective_kernel_path = kernel_path_for(root, Some(kernel_path_raw.as_str()))?;
            let envelope = build_action_envelope_with_options(
                root,
                Some(effective_kernel_path.to_string_lossy().as_ref()),
                &agent_id,
                Some(&org_id),
                &action_type,
                &resource,
                estimated_cost_usd,
                run_id.as_deref(),
                session_id.as_deref(),
                capability_name.as_deref(),
                payload_json.as_deref(),
            )?;
            let ingress_request_path = runtime_ingress_request_path(root, &request_id)?;
            fs::write(
                &ingress_request_path,
                format!(
                    "{{\n  \"status\": \"received\",\n  \"request_id\": {},\n  \"request_type\": {},\n  \"received_at\": {},\n  \"transport\": {},\n  \"ingress_target\": {},\n  \"agent_id\": {},\n  \"org_id\": {},\n  \"action_type\": {},\n  \"resource\": {},\n  \"capability_name\": {},\n  \"payload_json\": {},\n  \"estimated_cost_usd\": {:.6}\n}}\n",
                    json_string(&request_id),
                    json_string(&request_type),
                    json_string(&timestamp_now()),
                    json_string(transport),
                    json_string(ingress_target),
                    json_string(&agent_id),
                    json_string(&org_id),
                    json_string(&action_type),
                    json_string(&resource),
                    json_string(&envelope.capability_name),
                    json_string(&envelope.payload_json),
                    estimated_cost_usd,
                ),
            )
            .map_err(io_err)?;
            let enqueue = enqueue_action(root, &effective_kernel_path, &envelope)?;
            let ingress_receipt_path = runtime_ingress_receipt_path(root, &request_id)?;
            fs::write(
                &ingress_receipt_path,
                format!(
                    "{{\n  \"status\": \"accepted\",\n  \"request_id\": {},\n  \"accepted_at\": {},\n  \"transport\": {},\n  \"service_target\": {},\n  \"job_id\": {},\n  \"policy_class\": {},\n  \"queue_path\": {},\n  \"kernel_path\": {},\n  \"note\": \"service ingress accepted and queued action for local runtime supervision\"\n}}\n",
                    json_string(&request_id),
                    json_string(&timestamp_now()),
                    json_string(transport),
                    json_string(ingress_target),
                    json_string(&enqueue.input_hash),
                    json_string(&enqueue.policy_class),
                    json_string(&enqueue.queue_path.display().to_string()),
                    json_string(&enqueue.kernel_path),
                ),
            )
            .map_err(io_err)?;
            append_line(
                &runtime_ingress_stream_path(root)?,
                &format!(
                    "{{\"timestamp\":{},\"request_id\":{},\"status\":\"accepted\",\"transport\":{},\"job_id\":{},\"policy_class\":{},\"queue_path\":{},\"ingress_target\":{}}}\n",
                    json_string(&timestamp_now()),
                    json_string(&request_id),
                    json_string(transport),
                    json_string(&enqueue.input_hash),
                    json_string(&enqueue.policy_class),
                    json_string(&enqueue.queue_path.display().to_string()),
                    json_string(ingress_target),
                ),
            )?;
            // Record pipeline entry from live ingress path
            let _ = record_pipeline_from_ingress(
                root,
                &request_id,
                ingress_target,
                transport,
                &agent_id,
                &org_id,
                capability_name.as_deref().unwrap_or(""),
                &enqueue.input_hash,
            );
            let payload = format!(
                "{{\"status\":\"accepted\",\"transport\":{},\"service_target\":{},\"request_id\":{},\"accepted_at\":{},\"job_id\":{},\"policy_class\":{},\"queue_path\":{},\"ingress_request_path\":{},\"ingress_receipt_path\":{},\"note\":\"service ingress accepted and queued action\"}}\n",
                json_string(transport),
                json_string(ingress_target),
                json_string(&request_id),
                json_string(&timestamp_now()),
                json_string(&enqueue.input_hash),
                json_string(&enqueue.policy_class),
                json_string(&enqueue.queue_path.display().to_string()),
                json_string(&ingress_request_path.display().to_string()),
                json_string(&ingress_receipt_path.display().to_string()),
            );
            Ok(RuntimeServiceReply {
                status: "accepted".to_string(),
                transport: transport.to_string(),
                request_id,
                job_id: enqueue.input_hash,
                note: "service ingress accepted and queued action".to_string(),
                http_status_code: 202,
                payload,
            })
        }
        "cancel_job" => {
            let job_id = {
                let value = value_string(request_body.get("job_id"));
                if value.is_empty() {
                    extract_json_string(request_contents, "\"job_id\"").unwrap_or_default()
                } else {
                    value
                }
            };
            if job_id.is_empty() {
                let payload = format!(
                    "{{\"status\":\"rejected\",\"request_id\":{},\"note\":\"cancel_job requires job_id\"}}\n",
                    json_string(&request_id),
                );
                return Ok(RuntimeServiceReply {
                    status: "rejected".to_string(),
                    transport: transport.to_string(),
                    request_id,
                    job_id: String::new(),
                    note: "cancel_job requires job_id".to_string(),
                    http_status_code: 400,
                    payload,
                });
            }
            let mut state = load_scheduler_state_or_default(root)?;
            let cancel_result = match state.jobs.get(&job_id) {
                None => {
                    let payload = format!(
                        "{{\"status\":\"not_found\",\"job_id\":{},\"request_id\":{},\"note\":\"job not found in scheduler\"}}\n",
                        json_string(&job_id),
                        json_string(&request_id),
                    );
                    return Ok(RuntimeServiceReply {
                        status: "not_found".to_string(),
                        transport: transport.to_string(),
                        request_id,
                        job_id: job_id.clone(),
                        note: "job not found in scheduler".to_string(),
                        http_status_code: 404,
                        payload,
                    });
                }
                Some(job) => {
                    let current = job.status.as_str().to_string();
                    let allowed = job.status.valid_transitions();
                    if allowed.contains(&JobStatus::Cancelled) {
                        Ok(current)
                    } else {
                        Err(current)
                    }
                }
            };
            match cancel_result {
                Ok(previous_status) => {
                    transition_job(&mut state, &job_id, JobStatus::Cancelled)
                        .map_err(|e| format!("cancel transition failed: {}", e))?;
                    update_job_metadata(
                        &mut state,
                        &job_id,
                        None,
                        None,
                        Some(Some("cancelled via service cancel request")),
                    )
                    .ok();
                    save_scheduler_state_checked(root, &state)?;
                    let payload = format!(
                        "{{\"status\":\"cancelled\",\"job_id\":{},\"request_id\":{},\"previous_status\":{},\"note\":\"job cancelled successfully\"}}\n",
                        json_string(&job_id),
                        json_string(&request_id),
                        json_string(&previous_status),
                    );
                    Ok(RuntimeServiceReply {
                        status: "cancelled".to_string(),
                        transport: transport.to_string(),
                        request_id,
                        job_id: job_id.clone(),
                        note: "job cancelled successfully".to_string(),
                        http_status_code: 200,
                        payload,
                    })
                }
                Err(current_status) => {
                    let note = format!(
                        "job {} cannot be cancelled from status '{}'",
                        job_id, current_status
                    );
                    let payload = format!(
                        "{{\"status\":\"not_cancelable\",\"job_id\":{},\"request_id\":{},\"current_status\":{},\"note\":{}}}\n",
                        json_string(&job_id),
                        json_string(&request_id),
                        json_string(&current_status),
                        json_string(&note),
                    );
                    Ok(RuntimeServiceReply {
                        status: "not_cancelable".to_string(),
                        transport: transport.to_string(),
                        request_id,
                        job_id: job_id.clone(),
                        note,
                        http_status_code: 409,
                        payload,
                    })
                }
            }
        }
        "stop" => {
            let stop_request_path = service_stop_request_path(root)?;
            fs::write(
                &stop_request_path,
                format!(
                    "{{\n  \"status\": \"stop_requested\",\n  \"request_id\": {},\n  \"requested_at\": {}\n}}\n",
                    json_string(&request_id),
                    json_string(&timestamp_now())
                ),
            )
            .map_err(io_err)?;
            let payload = format!(
                "{{\"status\":\"stop_requested\",\"request_id\":{},\"note\":\"runtime service stop has been requested\"}}\n",
                json_string(&request_id),
            );
            Ok(RuntimeServiceReply {
                status: "stop_requested".to_string(),
                transport: transport.to_string(),
                request_id,
                job_id: String::new(),
                note: "runtime service stop has been requested".to_string(),
                http_status_code: 202,
                payload,
            })
        }
        _ => {
            let payload = format!(
                "{{\"status\":\"rejected\",\"request_id\":{},\"note\":{}}}\n",
                json_string(&request_id),
                json_string(&format!("unknown request_type '{}'", request_type)),
            );
            Ok(RuntimeServiceReply {
                status: "rejected".to_string(),
                transport: transport.to_string(),
                request_id,
                job_id: String::new(),
                note: format!("unknown request_type '{}'", request_type),
                http_status_code: 400,
                payload,
            })
        }
    }
}

fn send_runtime_service_request(socket_path: &Path, request: &str) -> ShadowResult<String> {
    let mut last_error = None;
    for _ in 0..20 {
        match UnixStream::connect(socket_path) {
            Ok(mut stream) => {
                stream.write_all(request.as_bytes()).map_err(io_err)?;
                stream.shutdown(Shutdown::Write).map_err(io_err)?;
                return read_stream_string(&mut stream);
            }
            Err(error) => {
                last_error = Some(error);
                thread::sleep(Duration::from_millis(50));
            }
        }
    }
    Err(io_err(last_error.unwrap_or_else(|| {
        io::Error::other("runtime service socket connection failed")
    })))
}

fn send_runtime_service_http_request(
    http_url: &str,
    method: &str,
    path: &str,
    body: Option<&str>,
    service_token: Option<&str>,
) -> ShadowResult<String> {
    let target = http_url
        .trim()
        .strip_prefix("http://")
        .ok_or_else(|| "http_url must start with http://".to_string())?;
    let (host_port, base_path) = if let Some((host_port, suffix)) = target.split_once('/') {
        (host_port, format!("/{}", suffix.trim_start_matches('/')))
    } else {
        (target, String::new())
    };
    let resolved_path = format!("{}{}", base_path, path);
    let mut stream = TcpStream::connect(host_port).map_err(io_err)?;
    stream
        .set_read_timeout(Some(Duration::from_secs(5)))
        .map_err(io_err)?;
    stream
        .set_write_timeout(Some(Duration::from_secs(5)))
        .map_err(io_err)?;
    let payload = body.unwrap_or("");
    let mut request = format!(
        "{} {} HTTP/1.1\r\nHost: {}\r\nConnection: close\r\n",
        method, resolved_path, host_port
    );
    if let Some(token) = service_token {
        request.push_str(&format!("Authorization: Bearer {}\r\n", token));
    }
    if !payload.is_empty() {
        request.push_str("Content-Type: application/json\r\n");
        request.push_str(&format!("Content-Length: {}\r\n", payload.len()));
    } else {
        request.push_str("Content-Length: 0\r\n");
    }
    request.push_str("\r\n");
    request.push_str(payload);
    stream.write_all(request.as_bytes()).map_err(io_err)?;
    stream.shutdown(Shutdown::Write).map_err(io_err)?;
    read_tcp_stream_string(&mut stream)
}

/// Constant-time string comparison to prevent timing attacks.
fn constant_time_eq(a: &str, b: &str) -> bool {
    let a_bytes = a.as_bytes();
    let b_bytes = b.as_bytes();
    if a_bytes.len() != b_bytes.len() {
        return false;
    }
    let mut result = 0;
    for (x, y) in a_bytes.iter().zip(b_bytes.iter()) {
        result |= x ^ y;
    }
    std::hint::black_box(result) == 0
}

fn handle_runtime_service_http_request(
    root: &Path,
    override_kernel_path: Option<&str>,
    http_address: &str,
    service_token: Option<&str>,
    raw_request: &str,
) -> ShadowResult<RuntimeServiceReply> {
    let request = match parse_http_request(raw_request) {
        Ok(request) => request,
        Err(error) => return Ok(RuntimeServiceReply::bad_request("http", error)),
    };
    if let Some(expected) = service_token {
        let presented = request
            .authorization
            .unwrap_or_default()
            .trim()
            .strip_prefix("Bearer ")
            .unwrap_or_default()
            .to_string();
        if !constant_time_eq(&presented, expected) {
            let payload = "{\"status\":\"unauthorized\",\"note\":\"service token required for this HTTP surface\"}\n".to_string();
            return Ok(RuntimeServiceReply {
                status: "unauthorized".to_string(),
                transport: "http".to_string(),
                request_id: canonical_join_runtime(&["http", "unauthorized", &timestamp_now()]),
                job_id: String::new(),
                note: "service token required for this HTTP surface".to_string(),
                http_status_code: 401,
                payload,
            });
        }
    }

    match (request.method.as_str(), request.path.as_str()) {
        ("GET", "/status") => {
            let snapshot = runtime_service_status(root, None)?;
            Ok(RuntimeServiceReply {
                status: "status".to_string(),
                transport: "http".to_string(),
                request_id: canonical_join_runtime(&["http", "status", &timestamp_now()]),
                job_id: snapshot.last_job_id.clone(),
                note: "service status rendered over local http control plane".to_string(),
                http_status_code: 200,
                payload: render_runtime_service_json(&snapshot),
            })
        }
        ("GET", "/health") => {
            let snapshot = runtime_service_status(root, None)?;
            let health = runtime_service_health(&snapshot);
            Ok(RuntimeServiceReply {
                status: "health".to_string(),
                transport: "http".to_string(),
                request_id: canonical_join_runtime(&["http", "health", &timestamp_now()]),
                job_id: snapshot.last_job_id.clone(),
                note: "service health rendered over local http control plane".to_string(),
                http_status_code: if health == "healthy" { 200 } else { 503 },
                payload: render_runtime_service_health_json(&snapshot),
            })
        }
        ("GET", "/metrics") => {
            let snapshot = runtime_service_status(root, None)?;
            Ok(RuntimeServiceReply {
                status: "metrics".to_string(),
                transport: "http".to_string(),
                request_id: canonical_join_runtime(&["http", "metrics", &timestamp_now()]),
                job_id: snapshot.last_job_id.clone(),
                note: "service metrics rendered over local http control plane".to_string(),
                http_status_code: 200,
                payload: render_runtime_service_metrics_json(&snapshot),
            })
        }
        ("GET", "/config") => {
            let snapshot = runtime_service_status(root, None)?;
            Ok(RuntimeServiceReply {
                status: "config".to_string(),
                transport: "http".to_string(),
                request_id: canonical_join_runtime(&["http", "config", &timestamp_now()]),
                job_id: snapshot.last_job_id.clone(),
                note: "service config rendered over local http control plane".to_string(),
                http_status_code: 200,
                payload: render_runtime_service_config_json(root, &snapshot),
            })
        }
        ("GET", path) if path.starts_with("/jobs/") => {
            let job_id = path.trim_start_matches("/jobs/").trim();
            if job_id.is_empty() {
                return Ok(RuntimeServiceReply::bad_request(
                    "http",
                    "job id is required for /jobs/<id>".to_string(),
                ));
            }
            match inspect_job(root, job_id) {
                Ok(job) => Ok(RuntimeServiceReply {
                    status: "job".to_string(),
                    transport: "http".to_string(),
                    request_id: canonical_join_runtime(&["http", "job", job_id, &timestamp_now()]),
                    job_id: job.job_id.clone(),
                    note: "runtime job snapshot rendered over local http control plane".to_string(),
                    http_status_code: 200,
                    payload: render_job_inspect_json(&job),
                }),
                Err(error) => Ok(RuntimeServiceReply {
                    status: "not_found".to_string(),
                    transport: "http".to_string(),
                    request_id: canonical_join_runtime(&[
                        "http",
                        "job-not-found",
                        job_id,
                        &timestamp_now(),
                    ]),
                    job_id: job_id.to_string(),
                    note: error.clone(),
                    http_status_code: 404,
                    payload: format!(
                        "{{\"status\":\"not_found\",\"job_id\":{},\"note\":{}}}\n",
                        json_string(job_id),
                        json_string(&error),
                    ),
                }),
            }
        }
        ("POST", "/submit") => {
            let content_type = request
                .content_type
                .as_deref()
                .unwrap_or("")
                .split(';')
                .next()
                .unwrap_or("")
                .trim()
                .to_ascii_lowercase();
            if content_type != "application/json" {
                return Ok(RuntimeServiceReply::unsupported_media_type(
                    "http",
                    "POST /submit requires Content-Type: application/json".to_string(),
                ));
            }
            let body = match serde_json::from_str::<Value>(&request.body) {
                Ok(body) => body,
                Err(error) => {
                    return Ok(RuntimeServiceReply::bad_request("http", error.to_string()))
                }
            };
            let payload = format!(
                "{{\"request_type\":{},\"request_id\":{},\"agent_id\":{},\"org_id\":{},\"action_type\":{},\"resource\":{},\"capability_name\":{},\"payload_json\":{},\"estimated_cost_usd\":{:.6},\"run_id\":{},\"session_id\":{},\"kernel_path\":{}}}\n",
                json_string("submit_action"),
                json_string(&value_string(body.get("request_id"))),
                json_string(&value_string(body.get("agent_id"))),
                json_string(&value_string(body.get("org_id"))),
                json_string(&value_string(body.get("action_type"))),
                json_string(&value_string(body.get("resource"))),
                json_string(&value_string(body.get("capability_name"))),
                json_string(&value_json_string(body.get("payload_json").or_else(|| body.get("payload")))),
                body.get("estimated_cost_usd").and_then(Value::as_f64).unwrap_or(0.0),
                json_string(&value_string(body.get("run_id"))),
                json_string(&value_string(body.get("session_id"))),
                json_string(&value_string(body.get("kernel_path"))),
            );
            handle_runtime_service_request(
                root,
                override_kernel_path,
                http_address,
                "http",
                &payload,
            )
        }
        ("POST", "/import-commitments") => {
            let content_type = request
                .content_type
                .as_deref()
                .unwrap_or("")
                .split(';')
                .next()
                .unwrap_or("")
                .trim()
                .to_ascii_lowercase();
            if content_type != "application/json" {
                return Ok(RuntimeServiceReply::unsupported_media_type(
                    "http",
                    "POST /import-commitments requires Content-Type: application/json".to_string(),
                ));
            }
            let body = match serde_json::from_str::<Value>(&request.body) {
                Ok(body) => body,
                Err(error) => {
                    return Ok(RuntimeServiceReply::bad_request("http", error.to_string()))
                }
            };
            let commitments_source = value_string(body.get("commitments_source"));
            let kernel_path = value_string(body.get("kernel_path"));
            if commitments_source.is_empty() {
                let payload =
                    "{\"status\":\"rejected\",\"note\":\"commitments_source is required\"}\n"
                        .to_string();
                return Ok(RuntimeServiceReply {
                    status: "rejected".to_string(),
                    transport: "http".to_string(),
                    request_id: canonical_join_runtime(&["http", "import", &timestamp_now()]),
                    job_id: String::new(),
                    note: "commitments_source is required".to_string(),
                    http_status_code: 400,
                    payload,
                });
            }
            let effective_kernel_path = if kernel_path.trim().is_empty() {
                override_kernel_path
            } else {
                Some(kernel_path.as_str())
            };
            let import = import_commitment_execution_requests(
                root,
                effective_kernel_path,
                &commitments_source,
                body.get("workspace_token").and_then(Value::as_str),
            )?;
            Ok(RuntimeServiceReply {
                status: "commitment_imported".to_string(),
                transport: "http".to_string(),
                request_id: canonical_join_runtime(&["http", "import", &timestamp_now()]),
                job_id: import.last_job_id.clone(),
                note: import.note.clone(),
                http_status_code: 202,
                payload: render_runtime_service_import_json(&import),
            })
        }
        ("POST", "/cancel") => {
            let content_type = request
                .content_type
                .as_deref()
                .unwrap_or("")
                .split(';')
                .next()
                .unwrap_or("")
                .trim()
                .to_ascii_lowercase();
            if content_type != "application/json" {
                return Ok(RuntimeServiceReply::unsupported_media_type(
                    "http",
                    "POST /cancel requires Content-Type: application/json".to_string(),
                ));
            }
            let body = match serde_json::from_str::<Value>(&request.body) {
                Ok(body) => body,
                Err(error) => {
                    return Ok(RuntimeServiceReply::bad_request("http", error.to_string()))
                }
            };
            let payload = format!(
                "{{\"request_type\":{},\"request_id\":{},\"job_id\":{}}}\n",
                json_string("cancel_job"),
                json_string(&value_string(body.get("request_id"))),
                json_string(&value_string(body.get("job_id"))),
            );
            handle_runtime_service_request(
                root,
                override_kernel_path,
                http_address,
                "http",
                &payload,
            )
        }
        ("POST", "/stop") => handle_runtime_service_request(
            root,
            override_kernel_path,
            http_address,
            "http",
            &format!(
                "{{\"request_type\":{},\"request_id\":{}}}\n",
                json_string("stop"),
                json_string(&canonical_join_runtime(&["http", "stop", &timestamp_now()])),
            ),
        ),
        // S3: MCP server adapter — tools/list returns kernel capabilities as MCP tool objects
        ("POST", "/mcp/tools/list") => {
            let effective_kernel = kernel_path_for(root, override_kernel_path).ok();
            let tools = mcp_tools_list(root, effective_kernel.as_deref());
            let payload = format!(
                "{{\"jsonrpc\":\"2.0\",\"result\":{{\"tools\":{}}}}}\n",
                tools,
            );
            Ok(RuntimeServiceReply {
                status: "mcp_tools_list".to_string(),
                transport: "http".to_string(),
                request_id: canonical_join_runtime(&["http", "mcp-tools-list", &timestamp_now()]),
                job_id: String::new(),
                note: "MCP tools/list response".to_string(),
                http_status_code: 200,
                payload,
            })
        }
        // S3: MCP server adapter — tools/call routes to /submit
        ("POST", "/mcp/tools/call") => {
            let content_type = request
                .content_type
                .as_deref()
                .unwrap_or("")
                .split(';')
                .next()
                .unwrap_or("")
                .trim()
                .to_ascii_lowercase();
            if content_type != "application/json" {
                return Ok(RuntimeServiceReply::unsupported_media_type(
                    "http",
                    "POST /mcp/tools/call requires Content-Type: application/json".to_string(),
                ));
            }
            let body = match serde_json::from_str::<Value>(&request.body) {
                Ok(body) => body,
                Err(error) => {
                    return Ok(RuntimeServiceReply::bad_request("http", error.to_string()))
                }
            };
            // MCP tools/call expects: {"name": "tool_name", "arguments": {...}}
            // or {"params": {"name": "tool_name", "arguments": {...}}}
            let tool_name = body
                .get("params")
                .and_then(|p| p.get("name"))
                .or_else(|| body.get("name"))
                .and_then(Value::as_str)
                .unwrap_or("unknown");
            let arguments = body
                .get("params")
                .and_then(|p| p.get("arguments"))
                .or_else(|| body.get("arguments"))
                .cloned()
                .unwrap_or(Value::Object(Default::default()));
            match tool_name {
                "loom_submit" => {
                    let payload = format!(
                        "{{\"request_type\":{},\"request_id\":{},\"agent_id\":{},\"org_id\":{},\"action_type\":{},\"resource\":{},\"capability_name\":{},\"payload_json\":{},\"estimated_cost_usd\":{:.6},\"run_id\":{},\"session_id\":{},\"kernel_path\":{}}}\n",
                        json_string("submit_action"),
                        json_string(&canonical_join_runtime(&["mcp", "tools-call", &timestamp_now()])),
                        json_string(&value_string(arguments.get("agent_id"))),
                        json_string(&value_string(arguments.get("org_id"))),
                        json_string(&value_string(arguments.get("action_type"))),
                        json_string(&value_string(arguments.get("resource"))),
                        json_string(&value_string(arguments.get("capability_name"))),
                        json_string(&value_json_string(arguments.get("payload_json").or_else(|| arguments.get("payload")))),
                        arguments.get("estimated_cost_usd").and_then(Value::as_f64).unwrap_or(0.0),
                        json_string(&value_string(arguments.get("run_id"))),
                        json_string(&value_string(arguments.get("session_id"))),
                        json_string(&value_string(arguments.get("kernel_path"))),
                    );
                    handle_runtime_service_request(
                        root,
                        override_kernel_path,
                        http_address,
                        "http",
                        &payload,
                    )
                }
                "loom_status" => {
                    let snapshot = runtime_service_status(root, None)?;
                    let payload = render_runtime_service_json(&snapshot);
                    Ok(RuntimeServiceReply {
                        status: "mcp_tool_result".to_string(),
                        transport: "http".to_string(),
                        request_id: canonical_join_runtime(&[
                            "mcp",
                            "tools-call",
                            "status",
                            &timestamp_now(),
                        ]),
                        job_id: String::new(),
                        note: "loom_status tool result".to_string(),
                        http_status_code: 200,
                        payload,
                    })
                }
                "loom_job_inspect" => {
                    let job_id = value_string(arguments.get("job_id"));
                    if job_id.is_empty() {
                        return Ok(RuntimeServiceReply::bad_request(
                            "http",
                            "loom_job_inspect requires job_id argument".to_string(),
                        ));
                    }
                    match inspect_job(root, &job_id) {
                        Ok(snapshot) => {
                            let payload = render_job_inspect_json(&snapshot);
                            Ok(RuntimeServiceReply {
                                status: "mcp_tool_result".to_string(),
                                transport: "http".to_string(),
                                request_id: canonical_join_runtime(&[
                                    "mcp",
                                    "tools-call",
                                    "job-inspect",
                                    &timestamp_now(),
                                ]),
                                job_id: job_id.to_string(),
                                note: "loom_job_inspect tool result".to_string(),
                                http_status_code: 200,
                                payload,
                            })
                        }
                        Err(e) => Ok(RuntimeServiceReply::bad_request(
                            "http",
                            format!("job inspect failed: {}", e),
                        )),
                    }
                }
                _ => {
                    let payload = format!(
                        "{{\"error\":\"unknown_tool\",\"tool_name\":{},\"note\":\"available tools: loom_submit, loom_status, loom_job_inspect\"}}\n",
                        json_string(tool_name),
                    );
                    Ok(RuntimeServiceReply {
                        status: "unknown_tool".to_string(),
                        transport: "http".to_string(),
                        request_id: canonical_join_runtime(&[
                            "mcp",
                            "tools-call",
                            "error",
                            &timestamp_now(),
                        ]),
                        job_id: String::new(),
                        note: format!("unknown MCP tool: {}", tool_name),
                        http_status_code: 400,
                        payload,
                    })
                }
            }
        }
        // S4: A2A agent cards
        ("GET", "/.well-known/agent.json") => {
            let agent_card = a2a_agent_card(root, override_kernel_path);
            Ok(RuntimeServiceReply {
                status: "agent_card".to_string(),
                transport: "http".to_string(),
                request_id: canonical_join_runtime(&["http", "a2a-agent-card", &timestamp_now()]),
                job_id: String::new(),
                note: "A2A agent card".to_string(),
                http_status_code: 200,
                payload: agent_card,
            })
        }
        _ => {
            let payload = format!(
                "{{\"status\":\"not_found\",\"note\":{}}}\n",
                json_string(&format!(
                    "unsupported route {} {}",
                    request.method, request.path
                )),
            );
            Ok(RuntimeServiceReply {
                status: "not_found".to_string(),
                transport: "http".to_string(),
                request_id: canonical_join_runtime(&["http", "not-found", &timestamp_now()]),
                job_id: String::new(),
                note: format!("unsupported route {} {}", request.method, request.path),
                http_status_code: 404,
                payload,
            })
        }
    }
}

/// S3: Generate MCP tools/list response from kernel capabilities.
fn mcp_tools_list(root: &Path, _kernel_path: Option<&Path>) -> String {
    let config = read_config(root).ok();
    let org_id = config
        .as_ref()
        .map(|c| c.org_id.clone())
        .unwrap_or_else(|| "unknown".to_string());
    let mut tools = Vec::new();
    // Core tool: submit an action through the governed pipeline
    tools.push(format!(
        concat!(
            "{{\"name\":\"loom_submit\",\"description\":\"Submit an action through the Meridian Loom governed pipeline. ",
            "All actions pass through identity resolution, sanction enforcement, budget gate, and audit emission.\",",
            "\"inputSchema\":{{\"type\":\"object\",\"properties\":{{",
            "\"agent_id\":{{\"type\":\"string\",\"description\":\"Agent identifier\"}},",
            "\"org_id\":{{\"type\":\"string\",\"description\":\"Organization identifier\",\"default\":{}}},",
            "\"action_type\":{{\"type\":\"string\",\"description\":\"Type of action (e.g. research, execute)\"}},",
            "\"resource\":{{\"type\":\"string\",\"description\":\"Target resource\"}},",
            "\"estimated_cost_usd\":{{\"type\":\"number\",\"description\":\"Estimated cost in USD\"}}",
            "}},\"required\":[\"agent_id\",\"action_type\",\"resource\"]}}}}"
        ),
        json_string(&org_id),
    ));
    // Status tool
    tools.push(
        "{\"name\":\"loom_status\",\"description\":\"Get the current status of the Meridian Loom runtime service.\",\"inputSchema\":{\"type\":\"object\",\"properties\":{}}}".to_string()
    );
    // Job inspect tool
    tools.push(
        "{\"name\":\"loom_job_inspect\",\"description\":\"Inspect a job by ID, showing status, reservation state, and audit trail.\",\"inputSchema\":{\"type\":\"object\",\"properties\":{\"job_id\":{\"type\":\"string\",\"description\":\"Job identifier\"}},\"required\":[\"job_id\"]}}".to_string()
    );
    format!("[{}]", tools.join(","))
}

/// S4: Generate A2A agent card JSON.
fn a2a_agent_card(root: &Path, _override_kernel_path: Option<&str>) -> String {
    let config = read_config(root).ok();
    let org_id = config
        .as_ref()
        .map(|c| c.org_id.clone())
        .unwrap_or_else(|| "unknown".to_string());
    format!(
        concat!(
            "{{\n",
            "  \"name\": \"Meridian Loom\",\n",
            "  \"description\": \"Governance-first execution runtime for operator-scale AI. ",
            "Policy, economy, and isolation are in the execution loop.\",\n",
            "  \"url\": \"http://localhost:3120\",\n",
            "  \"version\": \"0.1.0\",\n",
            "  \"capabilities\": [\"governed_execution\", \"budget_gate\", \"sanction_enforcement\", \"audit_emission\", \"economy_hook\"],\n",
            "  \"defaultInputModes\": [\"application/json\"],\n",
            "  \"defaultOutputModes\": [\"application/json\"],\n",
            "  \"skills\": [\n",
            "    {{\"id\": \"submit_action\", \"name\": \"Submit Governed Action\", \"description\": \"Submit an action through the governed pipeline with identity, sanctions, budget, and audit.\"}},\n",
            "    {{\"id\": \"job_inspect\", \"name\": \"Inspect Job\", \"description\": \"Query the lifecycle state of a job.\"}}\n",
            "  ],\n",
            "  \"org_id\": {}\n",
            "}}\n"
        ),
        json_string(&org_id),
    )
}

fn collect_pending_runtime_ingress_requests(root: &Path) -> ShadowResult<Vec<PathBuf>> {
    let request_dir = ensure_runtime_ingress_dir(root)?.join("requests");
    let mut paths = Vec::new();
    for entry in fs::read_dir(&request_dir).map_err(io_err)? {
        let path = entry.map_err(io_err)?.path();
        if path.extension().and_then(|ext| ext.to_str()) != Some("json") {
            continue;
        }
        let Some(stem) = path.file_stem().and_then(|value| value.to_str()) else {
            continue;
        };
        if runtime_ingress_receipt_path(root, stem)?.exists() {
            continue;
        }
        paths.push(path);
    }
    paths.sort();
    Ok(paths)
}

pub fn import_commitment_execution_requests(
    root: &Path,
    override_kernel_path: Option<&str>,
    commitments_source: &str,
    workspace_token: Option<&str>,
) -> ShadowResult<RuntimeServiceImportCapture> {
    let imports_dir = ensure_runtime_imports_dir(root)?.join("commitment_execution");
    fs::create_dir_all(&imports_dir).map_err(io_err)?;
    let effective_kernel_path = kernel_path_for(root, override_kernel_path)?;
    let snapshot = load_commitments_snapshot(commitments_source, workspace_token)?;
    let commitments = snapshot
        .get("commitments")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();

    let mut imported = 0usize;
    let mut skipped = 0usize;
    let mut last_import_id = String::new();
    let mut last_job_id = String::new();

    for commitment in commitments {
        let commitment_id = value_string(commitment.get("commitment_id"));
        let source_org_id = value_string(commitment.get("source_institution_id"));
        let delivery_refs = commitment
            .get("delivery_refs")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        for delivery in delivery_refs {
            if value_string(delivery.get("message_type")) != "execution_request" {
                continue;
            }
            let adapter_envelope = delivery
                .get("adapter_envelope")
                .and_then(Value::as_object)
                .cloned()
                .unwrap_or_default();
            if adapter_envelope.is_empty() {
                skipped += 1;
                continue;
            }
            let import_id = canonical_join_runtime(&[
                "commitment",
                &commitment_id,
                &value_string(delivery.get("envelope_id")),
                &value_string(delivery.get("receipt_id")),
            ]);
            let marker_path = imports_dir.join(format!("{}.json", sanitize_filename(&import_id)));
            if marker_path.exists() {
                skipped += 1;
                continue;
            }

            let envelope = build_commitment_import_envelope(
                root,
                &effective_kernel_path,
                &source_org_id,
                &adapter_envelope,
            )?;
            let enqueue = enqueue_action(root, &effective_kernel_path, &envelope)?;
            fs::write(
                &marker_path,
                format!(
                    "{{\n  \"status\": \"imported\",\n  \"imported_at\": {},\n  \"import_id\": {},\n  \"commitment_id\": {},\n  \"delivery_envelope_id\": {},\n  \"delivery_receipt_id\": {},\n  \"job_id\": {},\n  \"queue_path\": {},\n  \"commitments_source\": {},\n  \"note\": \"sender-side execution_request imported from commitment delivery ref\"\n}}\n",
                    json_string(&timestamp_now()),
                    json_string(&import_id),
                    json_string(&commitment_id),
                    json_string(&value_string(delivery.get("envelope_id"))),
                    json_string(&value_string(delivery.get("receipt_id"))),
                    json_string(&enqueue.input_hash),
                    json_string(&enqueue.queue_path.display().to_string()),
                    json_string(commitments_source),
                ),
            )
            .map_err(io_err)?;
            imported += 1;
            last_import_id = import_id;
            last_job_id = enqueue.input_hash;
        }
    }

    Ok(RuntimeServiceImportCapture {
        commitments_source: commitments_source.to_string(),
        imports_dir,
        imported,
        skipped,
        last_import_id,
        last_job_id,
        note: if imported > 0 {
            format!(
                "imported {} sender-side execution_request deliveries from commitment outbox truth",
                imported
            )
        } else {
            "no new sender-side execution_request deliveries were imported".to_string()
        },
    })
}

fn load_commitments_snapshot(
    commitments_source: &str,
    workspace_token: Option<&str>,
) -> ShadowResult<Value> {
    let raw = if commitments_source.starts_with("http://")
        || commitments_source.starts_with("https://")
    {
        let mut command = Command::new("curl");
        command.arg("-sS");
        if let Some(token) = workspace_token {
            command
                .arg("-H")
                .arg(format!("Authorization: Bearer {}", token));
        }
        command.arg(commitments_source);
        let output = command.output().map_err(io_err)?;
        if !output.status.success() {
            return Err(format!(
                "failed to load commitments snapshot from {}: {}",
                commitments_source,
                String::from_utf8_lossy(&output.stderr).trim()
            ));
        }
        String::from_utf8(output.stdout).map_err(|error| error.to_string())?
    } else {
        fs::read_to_string(commitments_source).map_err(io_err)?
    };
    serde_json::from_str(&raw).map_err(|error| error.to_string())
}

fn build_commitment_import_envelope(
    root: &Path,
    kernel_path: &Path,
    source_org_id: &str,
    adapter_envelope: &serde_json::Map<String, Value>,
) -> ShadowResult<ActionEnvelope> {
    let agent_id = value_string(adapter_envelope.get("agent_id"));
    let action_type = value_string(adapter_envelope.get("action_type"));
    let resource = value_string(adapter_envelope.get("resource"));
    if agent_id.is_empty() || action_type.is_empty() || resource.is_empty() {
        return Err(
            "commitment import is missing adapter_envelope agent_id/action_type/resource"
                .to_string(),
        );
    }
    let estimated_cost_usd = adapter_envelope
        .get("estimated_cost_usd")
        .and_then(Value::as_f64)
        .unwrap_or(0.0);
    let run_id = value_string(adapter_envelope.get("run_id"));
    let session_id = value_string(adapter_envelope.get("session_id"));
    let envelope = build_action_envelope(
        root,
        Some(kernel_path.to_string_lossy().as_ref()),
        &agent_id,
        if source_org_id.is_empty() {
            None
        } else {
            Some(source_org_id)
        },
        &action_type,
        &resource,
        estimated_cost_usd,
        if run_id.is_empty() {
            None
        } else {
            Some(run_id.as_str())
        },
        if session_id.is_empty() {
            None
        } else {
            Some(session_id.as_str())
        },
    )?;
    Ok(envelope)
}

fn value_string(value: Option<&Value>) -> String {
    value
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_string()
}

fn value_json_string(value: Option<&Value>) -> String {
    match value {
        Some(Value::String(raw)) => raw.trim().to_string(),
        Some(other) => other.to_string(),
        None => String::new(),
    }
}

fn read_stream_string(stream: &mut UnixStream) -> ShadowResult<String> {
    let mut buffer = String::new();
    let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(5)));
    stream.read_to_string(&mut buffer).map_err(io_err)?;
    Ok(buffer)
}

fn read_tcp_stream_string(stream: &mut TcpStream) -> ShadowResult<String> {
    let mut buffer = String::new();
    let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(5)));
    stream.read_to_string(&mut buffer).map_err(io_err)?;
    Ok(buffer)
}

fn read_http_request_stream(stream: &mut TcpStream) -> ShadowResult<String> {
    let mut buffer = Vec::new();
    let mut chunk = [0u8; 4096];
    let mut header_end = None;
    let mut expected_total_len = None;

    loop {
        let bytes_read = stream.read(&mut chunk).map_err(io_err)?;
        if bytes_read == 0 {
            break;
        }
        buffer.extend_from_slice(&chunk[..bytes_read]);

        if header_end.is_none() {
            if let Some(idx) = buffer.windows(4).position(|window| window == b"\r\n\r\n") {
                let end = idx + 4;
                header_end = Some(end);
                let headers = String::from_utf8_lossy(&buffer[..end]);
                let content_length = headers
                    .lines()
                    .find_map(|line| {
                        let lower = line.to_ascii_lowercase();
                        if let Some(rest) = lower.strip_prefix("content-length:") {
                            rest.trim().parse::<usize>().ok()
                        } else {
                            None
                        }
                    })
                    .unwrap_or(0);
                expected_total_len = Some(end + content_length);
            } else if let Some(idx) = buffer.windows(2).position(|window| window == b"\n\n") {
                let end = idx + 2;
                header_end = Some(end);
                let headers = String::from_utf8_lossy(&buffer[..end]);
                let content_length = headers
                    .lines()
                    .find_map(|line| {
                        let lower = line.to_ascii_lowercase();
                        if let Some(rest) = lower.strip_prefix("content-length:") {
                            rest.trim().parse::<usize>().ok()
                        } else {
                            None
                        }
                    })
                    .unwrap_or(0);
                expected_total_len = Some(end + content_length);
            }
        }

        if let Some(expected_total_len) = expected_total_len {
            if buffer.len() >= expected_total_len {
                break;
            }
        }
    }

    String::from_utf8(buffer).map_err(|error| error.to_string())
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct HttpRequest {
    method: String,
    path: String,
    body: String,
    authorization: Option<String>,
    content_type: Option<String>,
}

fn parse_http_request(raw: &str) -> ShadowResult<HttpRequest> {
    let (head, body) = if let Some((head, body)) = raw.split_once("\r\n\r\n") {
        (head, body)
    } else if let Some((head, body)) = raw.split_once("\n\n") {
        (head, body)
    } else {
        (raw, "")
    };
    let mut lines = head.lines();
    let request_line = lines
        .next()
        .ok_or_else(|| "http request missing request line".to_string())?;
    let mut parts = request_line.split_whitespace();
    let method = parts
        .next()
        .ok_or_else(|| "http request missing method".to_string())?
        .to_string();
    let path = parts
        .next()
        .ok_or_else(|| "http request missing path".to_string())?
        .to_string();
    let version = parts
        .next()
        .ok_or_else(|| "http request missing version".to_string())?;
    if parts.next().is_some() {
        return Err("http request request line contains unexpected fields".to_string());
    }
    if !matches!(method.as_str(), "GET" | "POST") {
        return Err(format!("unsupported http method '{}'", method));
    }
    if !path.starts_with('/') {
        return Err("http request path must start with '/'".to_string());
    }
    if !version.starts_with("HTTP/1.") {
        return Err(format!("unsupported http version '{}'", version));
    }
    let mut authorization = None;
    let mut content_type = None;
    let mut content_length = None;
    for line in lines {
        if line.trim().is_empty() {
            continue;
        }
        if let Some((name, value)) = line.split_once(':') {
            if name.trim().eq_ignore_ascii_case("authorization") {
                authorization = Some(value.trim().to_string());
            } else if name.trim().eq_ignore_ascii_case("content-type") {
                content_type = Some(value.trim().to_string());
            } else if name.trim().eq_ignore_ascii_case("content-length") {
                let parsed = value.trim().parse::<usize>().map_err(|_| {
                    "http request content-length must be an unsigned integer".to_string()
                })?;
                content_length = Some(parsed);
            }
        } else {
            return Err(format!("malformed http header '{}'", line.trim()));
        }
    }
    if let Some(expected) = content_length {
        let actual = body.len();
        if actual != expected {
            return Err(format!(
                "http request content-length mismatch: declared {} bytes but received {}",
                expected, actual
            ));
        }
    }
    Ok(HttpRequest {
        method,
        path,
        body: body.to_string(),
        authorization,
        content_type,
    })
}

fn build_http_response(status_code: u16, body: &str) -> String {
    let status_text = match status_code {
        200 => "OK",
        202 => "Accepted",
        400 => "Bad Request",
        401 => "Unauthorized",
        404 => "Not Found",
        405 => "Method Not Allowed",
        415 => "Unsupported Media Type",
        500 => "Internal Server Error",
        _ => "OK",
    };
    format!(
        "HTTP/1.1 {} {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        status_code,
        status_text,
        body.len(),
        body
    )
}

fn extract_http_body(response: &str) -> String {
    if let Some((_, body)) = response.split_once("\r\n\r\n") {
        body.to_string()
    } else if let Some((_, body)) = response.split_once("\n\n") {
        body.to_string()
    } else {
        response.to_string()
    }
}

pub fn decision_exit_code(capture: &DecisionCapture, allow_code: i32, deny_code: i32) -> i32 {
    if capture.overall_decision == "allow" {
        allow_code
    } else {
        deny_code
    }
}

pub fn render_preflight_human(capture: &PreflightCapture) -> String {
    format!(
        "Meridian Loom // SHADOW PREFLIGHT\n===================================\nevent_log:              {}\naudit_preview_log:      {}\nreference_report:       {}\nreference_event_log:    {}\nlatest_report:          {}\ninput_hash:             {}\nestimated_cost_usd:     {:.4}\nidentity_restrictions:  {}\nreference_restrictions: {}\nsanction_controls:      {} (snapshot: {})\nbudget_limit_usd:       {}\nbudget_gate:            {}\napproval_hook:          {} (policy: {})\naudit_emission:         {}\noverall_decision:       {}\nreference_stage:        {}\nreference_reason:       {}\ncaptured_hooks:         {}\n\n{}\n",
        capture.event_log.display(),
        capture.audit_preview_log.display(),
        capture.reference_report.display(),
        capture.reference_event_log.display(),
        capture.latest_report.display(),
        capture.input_hash,
        capture.estimated_cost_usd,
        if capture.identity_restrictions.is_empty() {
            "(none)".to_string()
        } else {
            capture.identity_restrictions.join(", ")
        },
        if capture.reference_restrictions.is_empty() {
            "(none)".to_string()
        } else {
            capture.reference_restrictions.join(", ")
        },
        capture.sanction_gate_decision,
        capture.sanction_decision,
        capture
            .budget_limit_usd
            .map(|value| format!("{:.4}", value))
            .unwrap_or_else(|| "(unknown)".to_string()),
        capture.budget_gate_decision,
        capture.approval_gate_decision,
        capture.approval_decision,
        capture.audit_emission_decision,
        capture.overall_decision,
        capture.reference_stage,
        if capture.reference_reason.is_empty() {
            "(none)"
        } else {
            &capture.reference_reason
        },
        capture.hooks.join(", "),
        capture.capability_readiness_human,
    )
}

pub fn render_preflight_json(capture: &PreflightCapture) -> String {
    format!(
        "{{\n  \"event_log\": {},\n  \"audit_preview_log\": {},\n  \"reference_report\": {},\n  \"reference_event_log\": {},\n  \"latest_report\": {},\n  \"input_hash\": {},\n  \"estimated_cost_usd\": {:.6},\n  \"identity_restrictions\": {},\n  \"reference_restrictions\": {},\n  \"sanction_decision\": {},\n  \"sanction_gate_decision\": {},\n  \"budget_limit_usd\": {},\n  \"budget_gate_decision\": {},\n  \"approval_decision\": {},\n  \"approval_gate_decision\": {},\n  \"audit_emission_decision\": {},\n  \"overall_decision\": {},\n  \"reference_stage\": {},\n  \"reference_reason\": {},\n  \"capability_readiness\": {},\n  \"captured_hooks\": [\"agent_identity\", \"action_envelope\", \"cost_attribution\", \"approval_hook\", \"audit_emission\", \"sanction_controls\", \"budget_gate\"]\n}}\n",
        json_string(&capture.event_log.display().to_string()),
        json_string(&capture.audit_preview_log.display().to_string()),
        json_string(&capture.reference_report.display().to_string()),
        json_string(&capture.reference_event_log.display().to_string()),
        json_string(&capture.latest_report.display().to_string()),
        json_string(&capture.input_hash),
        capture.estimated_cost_usd,
        render_json_string_array(&capture.identity_restrictions),
        render_json_string_array(&capture.reference_restrictions),
        json_string(&capture.sanction_decision),
        json_string(&capture.sanction_gate_decision),
        capture
            .budget_limit_usd
            .map(|value| format!("{:.6}", value))
            .unwrap_or_else(|| "null".to_string()),
        json_string(&capture.budget_gate_decision),
        json_string(&capture.approval_decision),
        json_string(&capture.approval_gate_decision),
        json_string(&capture.audit_emission_decision),
        json_string(&capture.overall_decision),
        json_string(&capture.reference_stage),
        json_string(&capture.reference_reason),
        capture.capability_readiness_json,
    )
}

pub fn render_decision_human(capture: &DecisionCapture) -> String {
    format!(
        "Meridian Loom // SHADOW DECISION\n==================================\ndecision_path:          {}\nsource:                 {}\nagent_id:               {}\norg_id:                 {}\naction_type:            {}\nresource:               {}\ninput_hash:             {}\nestimated_cost_usd:{:>12.4}\nidentity_restrictions:  {}\nreference_restrictions: {}\nlocal_sanction:         {} ({})\nsanction_gate:          {}\napproval_gate:          {}\nbudget_limit_usd:       {}\nbudget_gate:            {}\noverall_decision:       {}\neffective_source:       {}\neffective_stage:        {}\neffective_reason:       {}\nreference_stage:        {}\nreference_reason:       {}\n",
        capture.decision_path.display(),
        capture.source,
        capture.agent_id,
        capture.org_id,
        capture.action_type,
        capture.resource,
        capture.input_hash,
        capture.estimated_cost_usd,
        if capture.identity_restrictions.is_empty() {
            "(none)".to_string()
        } else {
            capture.identity_restrictions.join(", ")
        },
        if capture.reference_restrictions.is_empty() {
            "(none)".to_string()
        } else {
            capture.reference_restrictions.join(", ")
        },
        capture.local_sanction_decision,
        capture.local_sanction_reason,
        capture.sanction_gate_decision,
        capture.approval_gate_decision,
        capture
            .budget_limit_usd
            .map(|value| format!("{:.4}", value))
            .unwrap_or_else(|| "(unknown)".to_string()),
        capture.budget_gate_decision,
        capture.overall_decision,
        capture.effective_source,
        capture.effective_stage,
        if capture.effective_reason.is_empty() {
            "(none)"
        } else {
            &capture.effective_reason
        },
        capture.reference_stage,
        if capture.reference_reason.is_empty() {
            "(none)"
        } else {
            &capture.reference_reason
        },
    )
}

pub fn render_decision_json(capture: &DecisionCapture) -> String {
    format!(
        "{{\n  \"status\": \"decision_captured\",\n  \"decision_path\": {},\n  \"source\": {},\n  \"agent_id\": {},\n  \"org_id\": {},\n  \"action_type\": {},\n  \"resource\": {},\n  \"input_hash\": {},\n  \"estimated_cost_usd\": {:.6},\n  \"identity_restrictions\": {},\n  \"reference_restrictions\": {},\n  \"local_sanction_allowed\": {},\n  \"local_sanction_decision\": {},\n  \"local_sanction_reason\": {},\n  \"sanction_gate_decision\": {},\n  \"approval_gate_decision\": {},\n  \"budget_limit_usd\": {},\n  \"budget_gate_decision\": {},\n  \"overall_decision\": {},\n  \"effective_source\": {},\n  \"effective_stage\": {},\n  \"effective_reason\": {},\n  \"reference_stage\": {},\n  \"reference_reason\": {},\n  \"note\": \"experimental preflight decision only; not governed runtime enforcement\"\n}}\n",
        json_string(&capture.decision_path.display().to_string()),
        json_string(&capture.source),
        json_string(&capture.agent_id),
        json_string(&capture.org_id),
        json_string(&capture.action_type),
        json_string(&capture.resource),
        json_string(&capture.input_hash),
        capture.estimated_cost_usd,
        render_json_string_array(&capture.identity_restrictions),
        render_json_string_array(&capture.reference_restrictions),
        if capture.local_sanction_allowed { "true" } else { "false" },
        json_string(&capture.local_sanction_decision),
        json_string(&capture.local_sanction_reason),
        json_string(&capture.sanction_gate_decision),
        json_string(&capture.approval_gate_decision),
        capture
            .budget_limit_usd
            .map(|value| format!("{:.6}", value))
            .unwrap_or_else(|| "null".to_string()),
        json_string(&capture.budget_gate_decision),
        json_string(&capture.overall_decision),
        json_string(&capture.effective_source),
        json_string(&capture.effective_stage),
        json_string(&capture.effective_reason),
        json_string(&capture.reference_stage),
        json_string(&capture.reference_reason),
    )
}

pub fn render_runtime_execution_human(capture: &RuntimeExecutionCapture) -> String {
    let root = capture
        .execution_path
        .parent()
        .and_then(Path::parent)
        .and_then(Path::parent)
        .map(|path| path.display().to_string())
        .unwrap_or_else(|| "(unknown)".to_string());
    let event = runtime_event_for_capture(capture);
    format!(
        "Meridian Loom // RUNTIME EXECUTE\n=================================\nphase:       experimental runtime rehearsal\nboundary:    local governed supervisor path is real; hosted runtime replacement is not\n\nDecision\n========\nagent_id:            {}\norg_id:              {}\naction_type:         {}\nresource:            {}\ninput_hash:          {}\nestimated_cost_usd:  {:.4}\noverall_decision:    {}\neffective_source:    {}\neffective_stage:     {}\nreference_decision:  {}\nreference_stage:     {}\nruntime_outcome:     {}\nbudget_reservation:  {} {}\nworker_status:       {}\nworker_kind:         {}\nworker_note:         {}\nparity_status:       {}\nparity_reason:       {}\n\n{}\nArtifacts\n=========\n{}\nworker supervisor artifacts\n===========================\nworker_request:      {}\nworker_result:       {}\nworker_log:          {}\n\nproof / audit / parity artifacts\n================================\nexecution_path:      {}\nruntime_event:       {}\nruntime_event_stream:{}\ndecision_path:       {}\naudit_log:           {} ({})\nparity_stream:       {}\nparity_report:       {}\nreference_probe: {} ({})\nreference_probe_log:  {}\n\nNext\n====\n1. loom job inspect --job-id {} --root {}\n2. loom parity report --root {}\n3. loom shadow report --root {}\n4. Inspect {} for worker execution details.\n5. Inspect {} for runtime-side audit details.\n",
        capture.agent_id,
        capture.org_id,
        capture.action_type,
        capture.resource,
        capture.input_hash,
        capture.estimated_cost_usd,
        capture.overall_decision,
        capture.effective_source,
        capture.effective_stage,
        capture.reference_decision,
        capture.reference_stage,
        capture.runtime_outcome,
        capture.budget_reservation_status,
        if capture.budget_reservation_reason.is_empty() {
            String::new()
        } else {
            format!("({})", capture.budget_reservation_reason)
        },
        capture.worker_status,
        capture.worker_kind,
        capture.worker_note,
        capture.parity_status,
        capture.parity_reason,
        render_proof_first_status_human("Proof-first status", &event),
        render_artifact_refs_human(&event.artifact_refs),
        capture.worker_request_path.display(),
        capture.worker_result_path.display(),
        capture.worker_log_path.display(),
        capture.execution_path.display(),
        capture.runtime_event_path.display(),
        capture.runtime_event_stream_path.display(),
        capture.decision_path.display(),
        capture.audit_log_path.display(),
        capture.audit_emission_status,
        capture.parity_stream_path.display(),
        capture.parity_report_path.display(),
        capture
            .reference_probe_path
            .as_ref()
            .map(|path| path.display().to_string())
            .unwrap_or_else(|| "(not captured)".to_string()),
        capture.reference_probe_status,
        capture
            .reference_probe_stream_path
            .as_ref()
            .map(|path| path.display().to_string())
            .unwrap_or_else(|| "(not captured)".to_string()),
        capture.input_hash,
        root,
        root,
        root,
        capture.worker_log_path.display(),
        capture.audit_log_path.display(),
    )
}

pub fn render_runtime_execution_json(capture: &RuntimeExecutionCapture) -> String {
    let event = runtime_event_for_capture(capture);
    format!(
        "{{\n  \"status\": \"runtime_execution_captured\",\n  \"execution_path\": {},\n  \"runtime_event_path\": {},\n  \"runtime_event_stream_path\": {},\n  \"worker_request_path\": {},\n  \"worker_result_path\": {},\n  \"worker_log_path\": {},\n  \"decision_path\": {},\n  \"audit_log_path\": {},\n  \"parity_stream_path\": {},\n  \"parity_report_path\": {},\n  \"reference_probe_path\": {},\n  \"reference_probe_stream_path\": {},\n  \"agent_id\": {},\n  \"org_id\": {},\n  \"action_type\": {},\n  \"resource\": {},\n  \"input_hash\": {},\n  \"estimated_cost_usd\": {:.6},\n  \"runtime_outcome\": {},\n  \"budget_reservation_id\": {},\n  \"budget_reservation_status\": {},\n  \"budget_reservation_reason\": {},\n  \"worker_status\": {},\n  \"worker_kind\": {},\n  \"worker_note\": {},\n  \"overall_decision\": {},\n  \"effective_source\": {},\n  \"effective_stage\": {},\n  \"reference_decision\": {},\n  \"reference_stage\": {},\n  \"audit_emission_status\": {},\n  \"reference_probe_status\": {},\n  \"reference_probe_note\": {},\n  \"parity_status\": {},\n  \"parity_reason\": {},\n  \"event_schema_version\": {},\n  \"event_id\": {},\n  \"job_id\": {},\n  \"execution_id\": {},\n  \"decision_id\": {},\n  \"parity_id\": {},\n  \"audit_id\": {},\n  \"artifact_refs\": {},\n  \"note\": \"experimental local supervisor path exists for allow decisions; governed hosted supervisor remains future work\"\n}}\n",
        json_string(&capture.execution_path.display().to_string()),
        json_string(&capture.runtime_event_path.display().to_string()),
        json_string(&capture.runtime_event_stream_path.display().to_string()),
        json_string(&capture.worker_request_path.display().to_string()),
        json_string(&capture.worker_result_path.display().to_string()),
        json_string(&capture.worker_log_path.display().to_string()),
        json_string(&capture.decision_path.display().to_string()),
        json_string(&capture.audit_log_path.display().to_string()),
        json_string(&capture.parity_stream_path.display().to_string()),
        json_string(&capture.parity_report_path.display().to_string()),
        capture
            .reference_probe_path
            .as_ref()
            .map(|path| json_string(&path.display().to_string()))
            .unwrap_or_else(|| "null".to_string()),
        capture
            .reference_probe_stream_path
            .as_ref()
            .map(|path| json_string(&path.display().to_string()))
            .unwrap_or_else(|| "null".to_string()),
        json_string(&capture.agent_id),
        json_string(&capture.org_id),
        json_string(&capture.action_type),
        json_string(&capture.resource),
        json_string(&capture.input_hash),
        capture.estimated_cost_usd,
        json_string(&capture.runtime_outcome),
        if capture.budget_reservation_id.is_empty() {
            "null".to_string()
        } else {
            json_string(&capture.budget_reservation_id)
        },
        json_string(&capture.budget_reservation_status),
        json_string(&capture.budget_reservation_reason),
        json_string(&capture.worker_status),
        json_string(&capture.worker_kind),
        json_string(&capture.worker_note),
        json_string(&capture.overall_decision),
        json_string(&capture.effective_source),
        json_string(&capture.effective_stage),
        json_string(&capture.reference_decision),
        json_string(&capture.reference_stage),
        json_string(&capture.audit_emission_status),
        json_string(&capture.reference_probe_status),
        json_string(&capture.reference_probe_note),
        json_string(&capture.parity_status),
        json_string(&capture.parity_reason),
        json_string(&event.schema_version),
        json_string(&event.event_id),
        json_string(&event.job_id),
        json_string(&event.execution_id),
        json_string(&event.decision_id),
        json_string(&event.parity_id),
        json_string(&event.audit_id),
        render_artifact_refs_json(&event.artifact_refs),
    )
}

pub fn render_enqueued_action_human(capture: &EnqueuedAction) -> String {
    format!(
        "Meridian Loom // ACTION ENQUEUED\n=================================\nqueue_path:           {}\njob_path:             {}\ninput_hash:           {}\npolicy_class:         {}\nagent_id:             {}\norg_id:               {}\naction_type:          {}\nresource:             {}\nestimated_cost_usd:   {}\nkernel_path:          {}\nnext_step:            loom job inspect --job-id {} --root <path>\nthen:                 loom supervisor run --root <path> --max-jobs 1\n",
        capture.queue_path.display(),
        capture.job_path.display(),
        capture.input_hash,
        capture.policy_class,
        capture.agent_id,
        capture.org_id,
        capture.action_type,
        capture.resource,
        capture.estimated_cost_usd,
        capture.kernel_path,
        capture.input_hash,
    )
}

pub fn render_enqueued_action_json(capture: &EnqueuedAction) -> String {
    format!(
        r#"{{
  "status": "queued",
  "queue_path": {},
  "job_path": {},
  "input_hash": {},
  "policy_class": {},
  "agent_id": {},
  "org_id": {},
  "action_type": {},
  "resource": {},
  "estimated_cost_usd": {},
  "kernel_path": {}
}}"#,
        json_string(&capture.queue_path.display().to_string()),
        json_string(&capture.job_path.display().to_string()),
        json_string(&capture.input_hash),
        json_string(&capture.policy_class),
        json_string(&capture.agent_id),
        json_string(&capture.org_id),
        json_string(&capture.action_type),
        json_string(&capture.resource),
        capture.estimated_cost_usd,
        json_string(&capture.kernel_path),
    )
}

fn render_queue_record_human(record: &QueueRecordSnapshot) -> String {
    format!(
        r"  {} | policy={} | status={} | job_status={} | stage={} | acked={} | queue_path={}
",
        record.job_id,
        record.policy_class,
        record.status,
        record.job_status,
        record.job_stage,
        if record.acknowledged { "yes" } else { "no" },
        record.queue_path.display(),
    )
}

fn render_queue_record_json(record: &QueueRecordSnapshot) -> String {
    format!(
        r#"    {{
      "job_id": {},
      "queue_bucket": {},
      "policy_class": {},
      "status": {},
      "queued_at": {},
      "agent_id": {},
      "org_id": {},
      "action_type": {},
      "resource": {},
      "estimated_cost_usd": {},
      "run_id": {},
      "session_id": {},
      "kernel_path": {},
      "job_status": {},
      "job_stage": {},
      "acknowledged": {},
      "queue_path": {},
      "job_path": {},
      "ack_path": {},
      "note": {}
    }}"#,
        json_string(&record.job_id),
        json_string(&record.queue_bucket),
        json_string(&record.policy_class),
        json_string(&record.status),
        json_string(&record.queued_at),
        json_string(&record.agent_id),
        json_string(&record.org_id),
        json_string(&record.action_type),
        json_string(&record.resource),
        json_string(&record.estimated_cost_usd),
        json_string(&record.run_id),
        json_string(&record.session_id),
        json_string(&record.kernel_path),
        json_string(&record.job_status),
        json_string(&record.job_stage),
        if record.acknowledged { "true" } else { "false" },
        json_string(&record.queue_path.display().to_string()),
        json_string(&record.job_path.display().to_string()),
        json_string(&record.ack_path.display().to_string()),
        json_string(&record.note),
    )
}

pub fn render_queue_inspect_human(
    root: &Path,
    records: &[QueueRecordSnapshot],
    limit: usize,
) -> String {
    let entries = if records.is_empty() {
        "  (none)
"
        .to_string()
    } else {
        records
            .iter()
            .map(render_queue_record_human)
            .collect::<String>()
    };
    let acked = records.iter().filter(|record| record.acknowledged).count();
    format!(
        r#"Meridian Loom // QUEUE INSPECT
==============================
phase:       experimental local queue staging
boundary:    submitted queue records are locally inspectable; hosted delivery is not

Current state
=============
root:                {}
pending_records:     {}
acked_records:       {}
limit:               {}

Entries
-------
{}
Next
====
1. loom queue consume --root {} --max-jobs 1
2. loom queue ack --root {} --job-id <job_id>
3. loom job inspect --job-id <job_id> --root {}
"#,
        root.display(),
        records.len(),
        acked,
        if limit == 0 {
            "(all)".to_string()
        } else {
            limit.to_string()
        },
        entries,
        root.display(),
        root.display(),
        root.display(),
    )
}

pub fn render_queue_inspect_json(
    root: &Path,
    records: &[QueueRecordSnapshot],
    limit: usize,
) -> String {
    let rendered = records
        .iter()
        .map(render_queue_record_json)
        .collect::<Vec<_>>()
        .join(",\n");
    format!(
        r#"{{
  "status": "queue_inspect",
  "root": {},
  "limit": {},
  "pending_records": {},
  "acked_records": {},
  "records": [
{}
  ]
}}"#,
        json_string(&root.display().to_string()),
        limit,
        records.len(),
        records.iter().filter(|record| record.acknowledged).count(),
        rendered
    )
}

pub fn render_queue_consume_human(summary: &QueueConsumeSummary) -> String {
    format!(
        r#"Meridian Loom // QUEUE CONSUME
==============================
phase:       experimental local queue consumer
boundary:    queued records are consumed locally and acked on the filesystem; hosted delivery is not

Current state
=============
root:                {}
queue_dir:            {}
requested:            {}
pending_before:       {}
pending_after:        {}
processed_jobs:       {}
failed_jobs:          {}
acked_jobs:           {}
last_input_hash:      {}
last_execution_path:  {}
note:                 {}

Next
====
1. loom queue inspect --root {}
2. loom queue ack --root {} --job-id {}
3. loom parity report --root {}
"#,
        summary.root.display(),
        summary.queue_dir.display(),
        summary.requested,
        summary.pending_before,
        summary.pending_after,
        summary.processed_jobs,
        summary.failed_jobs,
        summary.acked_jobs,
        summary.last_input_hash,
        summary.last_execution_path.display(),
        summary.note,
        summary.root.display(),
        summary.root.display(),
        if summary.last_input_hash.is_empty() {
            "<job_id>".to_string()
        } else {
            summary.last_input_hash.clone()
        },
        summary.root.display(),
    )
}

pub fn render_queue_consume_json(summary: &QueueConsumeSummary) -> String {
    format!(
        r#"{{
  "status": "queue_consume_complete",
  "root": {},
  "queue_dir": {},
  "requested": {},
  "pending_before": {},
  "pending_after": {},
  "processed_jobs": {},
  "failed_jobs": {},
  "acked_jobs": {},
  "last_input_hash": {},
  "last_execution_path": {},
  "note": {}
}}"#,
        json_string(&summary.root.display().to_string()),
        json_string(&summary.queue_dir.display().to_string()),
        summary.requested,
        summary.pending_before,
        summary.pending_after,
        summary.processed_jobs,
        summary.failed_jobs,
        summary.acked_jobs,
        json_string(&summary.last_input_hash),
        json_string(&summary.last_execution_path.display().to_string()),
        json_string(&summary.note),
    )
}

pub fn render_queue_run_once_human(summary: &QueueRunOnceSummary) -> String {
    format!(
        r#"Meridian Loom // QUEUE RUN-ONCE
===============================
phase:       bounded local queue pipeline step
boundary:    staged records are consumed locally and progress is recorded on disk; live delivery is not attempted

Current state
=============
root:                {}
queue_dir:            {}
progress_path:        {}
requested:            {}
pending_before:       {}
pending_after:        {}
processed_jobs:       {}
failed_jobs:          {}
acked_jobs:           {}
last_input_hash:      {}
last_execution_path:  {}
note:                 {}
"#,
        summary.root.display(),
        summary.queue_dir.display(),
        summary.progress_path.display(),
        summary.requested,
        summary.pending_before,
        summary.pending_after,
        summary.processed_jobs,
        summary.failed_jobs,
        summary.acked_jobs,
        summary.last_input_hash,
        summary.last_execution_path.display(),
        summary.note,
    )
}

pub fn render_queue_run_once_json(summary: &QueueRunOnceSummary) -> String {
    format!(
        r#"{{
  "status": "queue_run_once_complete",
  "root": {},
  "queue_dir": {},
  "progress_path": {},
  "requested": {},
  "pending_before": {},
  "pending_after": {},
  "processed_jobs": {},
  "failed_jobs": {},
  "acked_jobs": {},
  "last_input_hash": {},
  "last_execution_path": {},
  "note": {}
}}"#,
        json_string(&summary.root.display().to_string()),
        json_string(&summary.queue_dir.display().to_string()),
        json_string(&summary.progress_path.display().to_string()),
        summary.requested,
        summary.pending_before,
        summary.pending_after,
        summary.processed_jobs,
        summary.failed_jobs,
        summary.acked_jobs,
        json_string(&summary.last_input_hash),
        json_string(&summary.last_execution_path.display().to_string()),
        json_string(&summary.note),
    )
}

pub fn render_queue_run_until_empty_human(summary: &QueueRunUntilEmptySummary) -> String {
    format!(
        r#"Meridian Loom // QUEUE RUN-UNTIL-EMPTY
======================================
phase:       bounded local queue drain loop
boundary:    queued records are consumed locally until empty or until the pass cap is reached; live delivery is not attempted

Current state
=============
root:                {}
queue_dir:            {}
progress_path:        {}
journal_path:         {}
requested:            {}
max_passes:           {}
passes_completed:     {}
initial_pending:      {}
final_pending:        {}
processed_jobs:       {}
failed_jobs:          {}
acked_jobs:           {}
drained:              {}
last_input_hash:      {}
last_execution_path:  {}
note:                 {}
"#,
        summary.root.display(),
        summary.queue_dir.display(),
        summary.progress_path.display(),
        summary.journal_path.display(),
        summary.requested,
        summary.max_passes,
        summary.passes_completed,
        summary.initial_pending,
        summary.final_pending,
        summary.processed_jobs,
        summary.failed_jobs,
        summary.acked_jobs,
        if summary.drained { "true" } else { "false" },
        if summary.last_input_hash.is_empty() {
            "(none)".to_string()
        } else {
            summary.last_input_hash.clone()
        },
        summary.last_execution_path.display(),
        summary.note,
    )
}

pub fn render_queue_run_until_empty_json(summary: &QueueRunUntilEmptySummary) -> String {
    format!(
        r#"{{
  "status": "queue_run_until_empty_complete",
  "root": {},
  "queue_dir": {},
  "progress_path": {},
  "journal_path": {},
  "requested": {},
  "max_passes": {},
  "passes_completed": {},
  "initial_pending": {},
  "final_pending": {},
  "processed_jobs": {},
  "failed_jobs": {},
  "acked_jobs": {},
  "drained": {},
  "last_input_hash": {},
  "last_execution_path": {},
  "note": {}
}}"#,
        json_string(&summary.root.display().to_string()),
        json_string(&summary.queue_dir.display().to_string()),
        json_string(&summary.progress_path.display().to_string()),
        json_string(&summary.journal_path.display().to_string()),
        summary.requested,
        summary.max_passes,
        summary.passes_completed,
        summary.initial_pending,
        summary.final_pending,
        summary.processed_jobs,
        summary.failed_jobs,
        summary.acked_jobs,
        if summary.drained { "true" } else { "false" },
        json_string(&summary.last_input_hash),
        json_string(&summary.last_execution_path.display().to_string()),
        json_string(&summary.note),
    )
}

pub fn render_queue_status_human(snapshot: &QueueStatusSnapshot) -> String {
    format!(
        r#"Meridian Loom // QUEUE STATUS
=============================
phase:       official v0.1 local queue surface
boundary:    queue depth is locally inspectable; hosted queue orchestration is not claimed

Current state
=============
root:                {}
queue_dir:            {}
pending_records:      {}
acked_records:        {}
total_pending:        {}
standard_depth:       {}
privileged_depth:     {}
budget_heavy_depth:   {}
sanction_sensitive:   {}
note:                 {}
"#,
        snapshot.root.display(),
        snapshot.queue_dir.display(),
        snapshot.pending_records,
        snapshot.acked_records,
        snapshot.total_pending,
        snapshot.standard_depth,
        snapshot.privileged_depth,
        snapshot.budget_heavy_depth,
        snapshot.sanction_sensitive_depth,
        snapshot.note,
    )
}

pub fn render_queue_status_json(snapshot: &QueueStatusSnapshot) -> String {
    format!(
        r#"{{
  "status": "queue_status",
  "root": {},
  "queue_dir": {},
  "pending_records": {},
  "acked_records": {},
  "total_pending": {},
  "queue_depths": {{
    "standard": {},
    "privileged": {},
    "budget_heavy": {},
    "sanction_sensitive": {}
  }},
  "note": {}
}}"#,
        json_string(&snapshot.root.display().to_string()),
        json_string(&snapshot.queue_dir.display().to_string()),
        snapshot.pending_records,
        snapshot.acked_records,
        snapshot.total_pending,
        snapshot.standard_depth,
        snapshot.privileged_depth,
        snapshot.budget_heavy_depth,
        snapshot.sanction_sensitive_depth,
        json_string(&snapshot.note),
    )
}

pub fn render_queue_ack_human(capture: &QueueAckCapture) -> String {
    format!(
        r#"Meridian Loom // QUEUE ACK
=========================
phase:       experimental local queue acknowledgment
boundary:    queue acknowledgement is a local filesystem receipt, not live delivery

Current state
=============
job_id:              {}
job_status:          {}
queue_bucket:        {}
ack_path:            {}
acknowledged_at:     {}
acknowledged_by:     {}
queue_path:          {}
job_path:            {}
note:                {}
"#,
        capture.job_id,
        capture.job_status,
        capture.queue_bucket,
        capture.ack_path.display(),
        capture.acknowledged_at,
        capture.acknowledged_by,
        capture
            .queue_path
            .as_ref()
            .map(|path| path.display().to_string())
            .unwrap_or_else(|| "(none)".to_string()),
        capture.job_path.display(),
        capture.note,
    )
}

pub fn render_queue_ack_json(capture: &QueueAckCapture) -> String {
    format!(
        r#"{{
  "status": "queue_ack_recorded",
  "root": {},
  "job_id": {},
  "job_path": {},
  "queue_path": {},
  "ack_path": {},
  "queue_bucket": {},
  "job_status": {},
  "acknowledged_at": {},
  "acknowledged_by": {},
  "note": {}
}}"#,
        json_string(&capture.root.display().to_string()),
        json_string(&capture.job_id),
        json_string(&capture.job_path.display().to_string()),
        capture
            .queue_path
            .as_ref()
            .map(|path| json_string(&path.display().to_string()))
            .unwrap_or_else(|| "null".to_string()),
        json_string(&capture.ack_path.display().to_string()),
        json_string(&capture.queue_bucket),
        json_string(&capture.job_status),
        json_string(&capture.acknowledged_at),
        json_string(&capture.acknowledged_by),
        json_string(&capture.note),
    )
}

pub fn render_job_list_human(
    root: &Path,
    jobs: &[JobSnapshot],
    status_filter: Option<&str>,
) -> String {
    let entries = if jobs.is_empty() {
        "  (none)\n".to_string()
    } else {
        jobs.iter()
            .map(|job| {
                format!(
                    "  {} | status={} | stage={} | bucket={} | agent={} | action={}::{} | updated_at={}\n",
                    job.job_id,
                    job.status,
                    job.stage,
                    job.queue_bucket,
                    job.agent_id,
                    job.action_type,
                    job.resource,
                    job.updated_at
                )
            })
            .collect::<String>()
    };
    format!(
        "Meridian Loom // JOB LIST\n==========================\nphase:       experimental runtime-owned job ledger\nboundary:    local job state is real; hosted scheduler remains future work\n\nCurrent state\n=============\nroot:                {}\nstatus_filter:       {}\njobs_found:          {}\n\nEntries\n-------\n{}\
\nNext\n====\n1. loom job inspect --job-id <input_hash> --root {}\n2. loom supervisor daemon status --root {}\n3. loom parity report --root {}\n",
        root.display(),
        status_filter.unwrap_or("(none)"),
        jobs.len(),
        entries,
        root.display(),
        root.display(),
        root.display(),
    )
}

pub fn render_job_list_json(jobs: &[JobSnapshot]) -> String {
    let rendered = jobs
        .iter()
        .map(render_job_snapshot_json)
        .collect::<Vec<_>>()
        .join(",\n");
    format!(
        "{{\n  \"status\": \"job_list\",\n  \"jobs\": [\n{}\n  ]\n}}\n",
        rendered
    )
}

pub fn render_job_inspect_human(job: &JobSnapshot) -> String {
    let event = runtime_event_for_job(job);
    format!(
        "Meridian Loom // JOB INSPECT\n=============================\nphase:       experimental runtime-owned job ledger\nboundary:    job lifecycle is locally inspectable; hosted scheduler remains future work\n\nCurrent state\n=============\njob_id:              {}\nstatus:              {}\nstage:               {}\nqueue_bucket:        {}\nqueued_at:           {}\nupdated_at:          {}\nagent_id:            {}\norg_id:              {}\naction_type:         {}\nresource:            {}\nestimated_cost_usd:  {}\nruntime_outcome:     {}\nbudget_reservation:  {} {}\nworker_status:       {}\nreservation_id:      {}\nreservation_state:   {}\nattempt_count:       {}\nnote:                {}\n\n{}\nArtifacts\n=========\n{}\njob_path:            {}\nqueue_path:          {}\ndecision_path:       {}\nexecution_path:      {}\nevent_path:          {}\nevent_stream_path:   {}\naudit_log_path:      {}\nparity_report_path:  {}\n\nNext\n====\n1. loom parity report --root {}\n2. loom shadow report --root {}\n3. Inspect {} for the latest persisted job state.\n",
        job.job_id,
        job.status,
        job.stage,
        job.queue_bucket,
        job.queued_at,
        job.updated_at,
        job.agent_id,
        job.org_id,
        job.action_type,
        job.resource,
        job.estimated_cost_usd,
        job.runtime_outcome,
        job.budget_reservation_status,
        if job.budget_reservation_reason.is_empty() {
            String::new()
        } else {
            format!("({})", job.budget_reservation_reason)
        },
        job.worker_status,
        if job.reservation_id.is_empty() { "(none)" } else { &job.reservation_id },
        job.reservation_state,
        job.attempt_count,
        job.note,
        render_proof_first_status_human("Proof-first status", &event),
        render_artifact_refs_human(&event.artifact_refs),
        job.job_path.display(),
        display_optional_path(job.queue_path.as_ref()),
        display_optional_path(job.decision_path.as_ref()),
        display_optional_path(job.execution_path.as_ref()),
        display_optional_path(job.event_path.as_ref()),
        display_optional_path(job.event_stream_path.as_ref()),
        display_optional_path(job.audit_log_path.as_ref()),
        display_optional_path(job.parity_report_path.as_ref()),
        job.root.display(),
        job.root.display(),
        job.job_path.display(),
    )
}

pub fn render_job_inspect_json(job: &JobSnapshot) -> String {
    let event = runtime_event_for_job(job);
    format!(
        "{{\n  \"status\": \"job_snapshot\",\n  \"event_schema_version\": {},\n  \"event_id\": {},\n  \"proof_job_id\": {},\n  \"execution_id\": {},\n  \"decision_id\": {},\n  \"parity_id\": {},\n  \"audit_id\": {},\n  \"artifact_refs\": {},\n  {}\n}}\n",
        json_string(&event.schema_version),
        json_string(&event.event_id),
        json_string(&event.job_id),
        json_string(&event.execution_id),
        json_string(&event.decision_id),
        json_string(&event.parity_id),
        json_string(&event.audit_id),
        render_artifact_refs_json(&event.artifact_refs),
        render_job_snapshot_json(job)
            .trim()
            .trim_start_matches('{')
            .trim_end_matches('}')
    )
}

pub fn render_supervisor_run_human(summary: &SupervisorRunSummary) -> String {
    format!(
        "Meridian Loom // SUPERVISOR RUN\n================================\nphase:       experimental local queue supervisor\nboundary:    queued worker dispatch is real; hosted governed supervisor is not\n\nCurrent state\n=============\nroot:                {}\nqueue_dir:           {}\nprocessed:           {}\nallowed:             {}\ndenied:              {}\nfailed:              {}\nlast_input_hash:     {}\nlast_execution:      {}\naudit_log:           {}\nnote:                {}\n\nNext\n====\n1. loom parity report --root {}\n2. loom shadow report --root {}\n3. Inspect {} for canonical runtime audit entries.\n",
        summary.root.display(),
        summary.queue_dir.display(),
        summary.processed,
        summary.allowed,
        summary.denied,
        summary.failed,
        if summary.last_input_hash.is_empty() {
            "(none)".to_string()
        } else {
            summary.last_input_hash.clone()
        },
        summary.last_execution_path.display(),
        summary.audit_log_path.display(),
        summary.note,
        summary.root.display(),
        summary.root.display(),
        summary.audit_log_path.display(),
    )
}

pub fn render_supervisor_run_json(summary: &SupervisorRunSummary) -> String {
    format!(
        "{{\n  \"status\": \"supervisor_run_complete\",\n  \"root\": {},\n  \"queue_dir\": {},\n  \"processed\": {},\n  \"allowed\": {},\n  \"denied\": {},\n  \"failed\": {},\n  \"last_input_hash\": {},\n  \"last_execution_path\": {},\n  \"audit_log_path\": {},\n  \"note\": {}\n}}\n",
        json_string(&summary.root.display().to_string()),
        json_string(&summary.queue_dir.display().to_string()),
        summary.processed,
        summary.allowed,
        summary.denied,
        summary.failed,
        json_string(&summary.last_input_hash),
        json_string(&summary.last_execution_path.display().to_string()),
        json_string(&summary.audit_log_path.display().to_string()),
        json_string(&summary.note),
    )
}

pub fn render_supervisor_watch_human(summary: &SupervisorWatchSummary) -> String {
    format!(
        "Meridian Loom // SUPERVISOR WATCH\n==================================\nphase:       experimental local queue supervisor loop\nboundary:    heartbeat and queue watch are real; hosted scheduler remains future work\n\nCurrent state\n=============\nroot:                {}\nsupervisor_dir:      {}\niterations:          {}\npoll_seconds:        {}\nprocessed:           {}\nallowed:             {}\ndenied:              {}\nfailed:              {}\nheartbeat_log:       {}\nstatus_path:         {}\nnote:                {}\n\nNext\n====\n1. loom supervisor run --root {} --max-jobs 1\n2. loom parity report --root {}\n3. inspect {} for supervisor heartbeat history.\n",
        summary.root.display(),
        summary.supervisor_dir.display(),
        summary.iterations,
        summary.poll_seconds,
        summary.processed,
        summary.allowed,
        summary.denied,
        summary.failed,
        summary.heartbeat_log_path.display(),
        summary.status_path.display(),
        summary.note,
        summary.root.display(),
        summary.root.display(),
        summary.heartbeat_log_path.display(),
    )
}

pub fn render_supervisor_watch_json(summary: &SupervisorWatchSummary) -> String {
    format!(
        "{{\n  \"status\": \"supervisor_watch_complete\",\n  \"root\": {},\n  \"supervisor_dir\": {},\n  \"iterations\": {},\n  \"poll_seconds\": {},\n  \"processed\": {},\n  \"allowed\": {},\n  \"denied\": {},\n  \"failed\": {},\n  \"heartbeat_log_path\": {},\n  \"status_path\": {},\n  \"note\": {}\n}}\n",
        json_string(&summary.root.display().to_string()),
        json_string(&summary.supervisor_dir.display().to_string()),
        summary.iterations,
        summary.poll_seconds,
        summary.processed,
        summary.allowed,
        summary.denied,
        summary.failed,
        json_string(&summary.heartbeat_log_path.display().to_string()),
        json_string(&summary.status_path.display().to_string()),
        json_string(&summary.note),
    )
}

pub fn render_supervisor_status_human(snapshot: &SupervisorStatusSnapshot) -> String {
    if !snapshot.available {
        return format!(
            "Meridian Loom // SUPERVISOR STATUS\n===================================\nphase:       experimental local queue supervisor loop\nboundary:    no watch status captured yet; hosted scheduler remains future work\n\nCurrent state\n=============\nroot:                {}\nsupervisor_dir:      {}\nstatus_path:         {}\nheartbeat_log:       {}\npending_jobs:        {}\nprocessed_jobs:      {}\nfailed_jobs:         {}\nheartbeat_entries:   {}\nnote:                {}\n\nNext\n====\n1. loom supervisor watch --root {} --max-jobs 1 --iterations 2 --poll-seconds 0\n2. loom supervisor run --root {} --max-jobs 1\n3. inspect {} after a watch loop has executed.\n",
            snapshot.root.display(),
            snapshot.supervisor_dir.display(),
            snapshot.status_path.display(),
            snapshot.heartbeat_log_path.display(),
            snapshot.pending_jobs,
            snapshot.processed_jobs,
            snapshot.failed_jobs,
            snapshot.heartbeat_entries,
            snapshot.note,
            snapshot.root.display(),
            snapshot.root.display(),
            snapshot.status_path.display(),
        );
    }

    format!(
        "Meridian Loom // SUPERVISOR STATUS\n===================================\nphase:       experimental local queue supervisor loop\nboundary:    bounded local loop state is real; hosted scheduler remains future work\n\nCurrent state\n=============\nroot:                {}\nsupervisor_dir:      {}\nupdated_at:          {}\niterations:          {}\npoll_seconds:        {}\nprocessed:           {}\nallowed:             {}\ndenied:              {}\nfailed:              {}\npending_jobs:        {}\nprocessed_jobs:      {}\nfailed_jobs:         {}\nheartbeat_entries:   {}\nlast_heartbeat:      {}\nstatus_path:         {}\nheartbeat_log:       {}\nnote:                {}\n\nNext\n====\n1. loom parity report --root {}\n2. loom shadow report --root {}\n3. inspect {} for the latest heartbeat history.\n",
        snapshot.root.display(),
        snapshot.supervisor_dir.display(),
        snapshot.updated_at,
        snapshot.iterations,
        snapshot.poll_seconds,
        snapshot.processed,
        snapshot.allowed,
        snapshot.denied,
        snapshot.failed,
        snapshot.pending_jobs,
        snapshot.processed_jobs,
        snapshot.failed_jobs,
        snapshot.heartbeat_entries,
        snapshot.last_heartbeat_timestamp,
        snapshot.status_path.display(),
        snapshot.heartbeat_log_path.display(),
        snapshot.note,
        snapshot.root.display(),
        snapshot.root.display(),
        snapshot.heartbeat_log_path.display(),
    )
}

pub fn render_supervisor_status_json(snapshot: &SupervisorStatusSnapshot) -> String {
    format!(
        "{{\n  \"status\": {},\n  \"root\": {},\n  \"supervisor_dir\": {},\n  \"status_path\": {},\n  \"heartbeat_log_path\": {},\n  \"available\": {},\n  \"updated_at\": {},\n  \"iterations\": {},\n  \"poll_seconds\": {},\n  \"processed\": {},\n  \"allowed\": {},\n  \"denied\": {},\n  \"failed\": {},\n  \"pending_jobs\": {},\n  \"processed_jobs\": {},\n  \"failed_jobs\": {},\n  \"heartbeat_entries\": {},\n  \"last_heartbeat_timestamp\": {},\n  \"note\": {}\n}}\n",
        json_string(if snapshot.available {
            "supervisor_status_available"
        } else {
            "supervisor_status_not_started"
        }),
        json_string(&snapshot.root.display().to_string()),
        json_string(&snapshot.supervisor_dir.display().to_string()),
        json_string(&snapshot.status_path.display().to_string()),
        json_string(&snapshot.heartbeat_log_path.display().to_string()),
        if snapshot.available { "true" } else { "false" },
        json_string(&snapshot.updated_at),
        snapshot.iterations,
        snapshot.poll_seconds,
        snapshot.processed,
        snapshot.allowed,
        snapshot.denied,
        snapshot.failed,
        snapshot.pending_jobs,
        snapshot.processed_jobs,
        snapshot.failed_jobs,
        snapshot.heartbeat_entries,
        json_string(&snapshot.last_heartbeat_timestamp),
        json_string(&snapshot.note),
    )
}

pub fn render_supervisor_lanes_human(root: &Path) -> ShadowResult<String> {
    let queue_root = ensure_runtime_dir(root)?.join("queue").join("pending");
    fs::create_dir_all(&queue_root).map_err(io_err)?;
    let mut queue = policy_queue::PolicyQueue::new();
    for class in PolicyClass::all() {
        let class_dir = queue_root.join(class.label());
        if !class_dir.exists() {
            continue;
        }
        for entry in fs::read_dir(&class_dir).map_err(io_err)? {
            let path = entry.map_err(io_err)?.path();
            if !path.is_file() || !path.extension().map(|ext| ext == "json").unwrap_or(false) {
                continue;
            }
            let job_id = path
                .file_stem()
                .map(|stem| stem.to_string_lossy().to_string())
                .unwrap_or_else(|| "unknown".to_string());
            queue.enqueue(*class, job_id);
        }
    }
    Ok(policy_queue::render_queue_depths_human(&queue))
}

pub fn render_supervisor_lanes_json(root: &Path) -> ShadowResult<String> {
    let queue_root = ensure_runtime_dir(root)?.join("queue").join("pending");
    fs::create_dir_all(&queue_root).map_err(io_err)?;
    let mut queue = policy_queue::PolicyQueue::new();
    for entry in fs::read_dir(&queue_root).map_err(io_err)? {
        let path = entry.map_err(io_err)?.path();
        if path.is_dir() {
            if let Some(class_name) = path
                .file_name()
                .map(|name| name.to_string_lossy().to_string())
            {
                if let Some(class) = PolicyClass::from_label(&class_name) {
                    for inner in fs::read_dir(&path).map_err(io_err)? {
                        let inner_path = inner.map_err(io_err)?.path();
                        if inner_path
                            .extension()
                            .map(|ext| ext == "json")
                            .unwrap_or(false)
                        {
                            let job_id = inner_path
                                .file_stem()
                                .map(|stem| stem.to_string_lossy().to_string())
                                .unwrap_or_else(|| "unknown".to_string());
                            queue.enqueue(class, job_id);
                        }
                    }
                }
            }
        } else if path.extension().map(|ext| ext == "json").unwrap_or(false) {
            let job_id = path
                .file_stem()
                .map(|stem| stem.to_string_lossy().to_string())
                .unwrap_or_else(|| "unknown".to_string());
            queue.enqueue(PolicyClass::Standard, job_id);
        }
    }
    Ok(policy_queue::render_queue_depths_json(&queue))
}

pub fn render_supervisor_daemon_human(snapshot: &SupervisorDaemonSnapshot) -> String {
    if !snapshot.available {
        return format!(
            "Meridian Loom // SUPERVISOR DAEMON\n===================================\nphase:       experimental local queue supervisor daemon rehearsal\nboundary:    no daemon state captured yet; hosted scheduler remains future work\n\nCurrent state\n=============\nroot:                {}\nsupervisor_dir:      {}\nruntime_state:       {}\nstdout_log:          {}\npending_jobs:        {}\nprocessed_jobs:      {}\nfailed_jobs:         {}\nheartbeat_entries:   {}\nnote:                {}\n\nNext\n====\n1. loom supervisor daemon start --root {} --max-jobs 1 --poll-seconds 1 --iterations 10\n2. loom supervisor status --root {}\n3. inspect {} once the daemon has started.\n",
            snapshot.root.display(),
            snapshot.supervisor_dir.display(),
            snapshot.runtime_state_path.display(),
            snapshot.stdout_log_path.display(),
            snapshot.pending_jobs,
            snapshot.processed_jobs,
            snapshot.failed_jobs,
            snapshot.heartbeat_entries,
            snapshot.note,
            snapshot.root.display(),
            snapshot.root.display(),
            snapshot.runtime_state_path.display(),
        );
    }

    format!(
        "Meridian Loom // SUPERVISOR DAEMON\n===================================\nphase:       experimental local queue supervisor daemon rehearsal\nboundary:    daemon lifecycle is locally real; hosted scheduler remains future work\n\nCurrent state\n=============\nroot:                {}\nsupervisor_dir:      {}\nsession_id:          {}\npid:                 {}\nrunning:             {}\nstatus:              {}\nbooted_at:           {}\nupdated_at:          {}\nstopped_at:          {}\npoll_seconds:        {}\nmax_jobs:            {}\nmax_iterations:      {}\niterations_completed:{}\nprocessed:           {}\nallowed:             {}\ndenied:              {}\nfailed:              {}\npending_jobs:        {}\nprocessed_jobs:      {}\nfailed_jobs:         {}\nheartbeat_entries:   {}\nruntime_state:       {}\nstdout_log:          {}\nstop_request:        {}\nnote:                {}\n\nNext\n====\n1. loom supervisor daemon stop --root {}\n2. loom supervisor status --root {}\n3. inspect {} for background daemon output.\n",
        snapshot.root.display(),
        snapshot.supervisor_dir.display(),
        if snapshot.session_id.is_empty() { "(none)".to_string() } else { snapshot.session_id.clone() },
        snapshot.pid,
        if snapshot.running { "true" } else { "false" },
        snapshot.status,
        if snapshot.booted_at.is_empty() { "(none)".to_string() } else { snapshot.booted_at.clone() },
        if snapshot.updated_at.is_empty() { "(none)".to_string() } else { snapshot.updated_at.clone() },
        if snapshot.stopped_at.is_empty() { "(none)".to_string() } else { snapshot.stopped_at.clone() },
        snapshot.poll_seconds,
        snapshot.max_jobs,
        snapshot.max_iterations,
        snapshot.iterations_completed,
        snapshot.processed,
        snapshot.allowed,
        snapshot.denied,
        snapshot.failed,
        snapshot.pending_jobs,
        snapshot.processed_jobs,
        snapshot.failed_jobs,
        snapshot.heartbeat_entries,
        snapshot.runtime_state_path.display(),
        snapshot.stdout_log_path.display(),
        snapshot.stop_request_path.display(),
        snapshot.note,
        snapshot.root.display(),
        snapshot.root.display(),
        snapshot.stdout_log_path.display(),
    )
}

pub fn render_supervisor_daemon_json(snapshot: &SupervisorDaemonSnapshot) -> String {
    format!(
        "{{\n  \"status\": {},\n  \"root\": {},\n  \"supervisor_dir\": {},\n  \"runtime_state_path\": {},\n  \"stop_request_path\": {},\n  \"stdout_log_path\": {},\n  \"available\": {},\n  \"session_id\": {},\n  \"pid\": {},\n  \"running\": {},\n  \"daemon_status\": {},\n  \"updated_at\": {},\n  \"booted_at\": {},\n  \"stopped_at\": {},\n  \"poll_seconds\": {},\n  \"max_jobs\": {},\n  \"max_iterations\": {},\n  \"iterations_completed\": {},\n  \"processed\": {},\n  \"allowed\": {},\n  \"denied\": {},\n  \"failed\": {},\n  \"pending_jobs\": {},\n  \"processed_jobs\": {},\n  \"failed_jobs\": {},\n  \"heartbeat_entries\": {},\n  \"note\": {}\n}}\n",
        json_string(if snapshot.available {
            "supervisor_daemon_status_available"
        } else {
            "supervisor_daemon_not_started"
        }),
        json_string(&snapshot.root.display().to_string()),
        json_string(&snapshot.supervisor_dir.display().to_string()),
        json_string(&snapshot.runtime_state_path.display().to_string()),
        json_string(&snapshot.stop_request_path.display().to_string()),
        json_string(&snapshot.stdout_log_path.display().to_string()),
        if snapshot.available { "true" } else { "false" },
        json_string(&snapshot.session_id),
        snapshot.pid,
        if snapshot.running { "true" } else { "false" },
        json_string(&snapshot.status),
        json_string(&snapshot.updated_at),
        json_string(&snapshot.booted_at),
        json_string(&snapshot.stopped_at),
        snapshot.poll_seconds,
        snapshot.max_jobs,
        snapshot.max_iterations,
        snapshot.iterations_completed,
        snapshot.processed,
        snapshot.allowed,
        snapshot.denied,
        snapshot.failed,
        snapshot.pending_jobs,
        snapshot.processed_jobs,
        snapshot.failed_jobs,
        snapshot.heartbeat_entries,
        json_string(&snapshot.note),
    )
}

pub fn render_runtime_service_human(snapshot: &RuntimeServiceSnapshot) -> String {
    let transport = runtime_service_transport(snapshot);
    let health = runtime_service_health(snapshot);
    if !snapshot.available {
        return format!(
            "Meridian Loom // RUNTIME SERVICE\n=================================\nphase:       official v0.1 local runtime service\nboundary:    no service state captured yet; transport replacement remains future work\n\nCurrent state\n=============\nroot:                {}\nconfig:              {}\nservice_dir:         {}\nservice_lock:        {}\nmetrics:             {}\nsocket_path:         {}\nhttp_address:        {}\nhttp_token_required: {}\nruntime_state:       {}\nstdout_log:          {}\nevent_log:           {}\ningress_stream:      {}\nhealth:              {}\ntransport:           {}\npending_jobs:        {}\nprocessed_jobs:      {}\nfailed_jobs:         {}\nnote:                {}\n\nNext\n====\n1. loom service start --root {} --http-address 127.0.0.1:0 --max-jobs 1 --poll-seconds 1\n2. loom service submit --root {} --agent-id agent_atlas --action-type research --resource web_search --estimated-cost-usd 0.05\n3. loom service status --root {}\n",
            snapshot.root.display(),
            snapshot.config_path.display(),
            snapshot.service_dir.display(),
            snapshot.service_lock_path.display(),
            snapshot.metrics_path.display(),
            snapshot.socket_path.display(),
            "(none)",
            "false",
            snapshot.runtime_state_path.display(),
            snapshot.stdout_log_path.display(),
            snapshot.event_log_path.display(),
            snapshot.ingress_stream_path.display(),
            health,
            transport,
            snapshot.pending_jobs,
            snapshot.processed_jobs,
            snapshot.failed_jobs,
            snapshot.note,
            snapshot.root.display(),
            snapshot.root.display(),
            snapshot.root.display(),
        );
    }

    format!(
        "Meridian Loom // RUNTIME SERVICE\n=================================\nphase:       official v0.1 local runtime service\nboundary:    service-owned ingress is locally real; live replacement is not claimed\n\nCurrent state\n=============\nroot:                {}\nconfig:              {}\nservice_dir:         {}\nservice_lock:        {}\nmetrics:             {}\nsocket_path:         {}\nhttp_address:        {}\nhttp_token_required: {}\ntransport:           {}\nhealth:              {}\nsession_id:          {}\npid:                 {}\nrunning:             {}\nstatus:              {}\nbooted_at:           {}\nupdated_at:          {}\nstopped_at:          {}\npoll_seconds:        {}\nmax_jobs:            {}\nmax_iterations:      {}\niterations_completed:{}\nrequests_received:   {}\nsubmitted:           {}\nprocessed:           {}\nallowed:             {}\ndenied:              {}\nfailed:              {}\npending_jobs:        {}\nprocessed_jobs:      {}\nfailed_jobs:         {}\nlast_request_id:     {}\nlast_job_id:         {}\nruntime_state:       {}\nstdout_log:          {}\nevent_log:           {}\ningress_stream:      {}\nstop_request:        {}\nnote:                {}\n\nNext\n====\n1. loom service submit --root {} --agent-id agent_atlas --action-type research --resource web_search --estimated-cost-usd 0.05\n2. loom service status --root {}\n3. loom parity report --root {}\n4. loom job inspect --job-id {} --root {}\n",
        snapshot.root.display(),
        snapshot.config_path.display(),
        snapshot.service_dir.display(),
        snapshot.service_lock_path.display(),
        snapshot.metrics_path.display(),
        snapshot.socket_path.display(),
        if snapshot.http_address.is_empty() { "(none)".to_string() } else { snapshot.http_address.clone() },
        if snapshot.http_token_required { "true" } else { "false" },
        transport,
        health,
        if snapshot.session_id.is_empty() { "(none)".to_string() } else { snapshot.session_id.clone() },
        snapshot.pid,
        if snapshot.running { "true" } else { "false" },
        snapshot.status,
        if snapshot.booted_at.is_empty() { "(none)".to_string() } else { snapshot.booted_at.clone() },
        if snapshot.updated_at.is_empty() { "(none)".to_string() } else { snapshot.updated_at.clone() },
        if snapshot.stopped_at.is_empty() { "(none)".to_string() } else { snapshot.stopped_at.clone() },
        snapshot.poll_seconds,
        snapshot.max_jobs,
        snapshot.max_iterations,
        snapshot.iterations_completed,
        snapshot.requests_received,
        snapshot.submitted,
        snapshot.processed,
        snapshot.allowed,
        snapshot.denied,
        snapshot.failed,
        snapshot.pending_jobs,
        snapshot.processed_jobs,
        snapshot.failed_jobs,
        if snapshot.last_request_id.is_empty() { "(none)".to_string() } else { snapshot.last_request_id.clone() },
        if snapshot.last_job_id.is_empty() { "(none)".to_string() } else { snapshot.last_job_id.clone() },
        snapshot.runtime_state_path.display(),
        snapshot.stdout_log_path.display(),
        snapshot.event_log_path.display(),
        snapshot.ingress_stream_path.display(),
        snapshot.stop_request_path.display(),
        snapshot.note,
        snapshot.root.display(),
        snapshot.root.display(),
        snapshot.root.display(),
        if snapshot.last_job_id.is_empty() { "<job_id>".to_string() } else { snapshot.last_job_id.clone() },
        snapshot.root.display(),
    )
}

pub fn render_runtime_service_json(snapshot: &RuntimeServiceSnapshot) -> String {
    format!(
        "{{\n  \"status\": {},\n  \"root\": {},\n  \"config_path\": {},\n  \"service_dir\": {},\n  \"service_lock_path\": {},\n  \"metrics_path\": {},\n  \"socket_path\": {},\n  \"http_address\": {},\n  \"http_token_required\": {},\n  \"transport\": {},\n  \"health\": {},\n  \"runtime_state_path\": {},\n  \"stop_request_path\": {},\n  \"stdout_log_path\": {},\n  \"event_log_path\": {},\n  \"ingress_stream_path\": {},\n  \"available\": {},\n  \"session_id\": {},\n  \"pid\": {},\n  \"running\": {},\n  \"service_status\": {},\n  \"updated_at\": {},\n  \"booted_at\": {},\n  \"stopped_at\": {},\n  \"poll_seconds\": {},\n  \"max_jobs\": {},\n  \"max_iterations\": {},\n  \"iterations_completed\": {},\n  \"requests_received\": {},\n  \"submitted\": {},\n  \"processed\": {},\n  \"allowed\": {},\n  \"denied\": {},\n  \"failed\": {},\n  \"pending_jobs\": {},\n  \"processed_jobs\": {},\n  \"failed_jobs\": {},\n  \"last_request_id\": {},\n  \"last_job_id\": {},\n  \"note\": {}\n}}\n",
        json_string(if snapshot.available { "runtime_service_status_available" } else { "runtime_service_not_started" }),
        json_string(&snapshot.root.display().to_string()),
        json_string(&snapshot.config_path.display().to_string()),
        json_string(&snapshot.service_dir.display().to_string()),
        json_string(&snapshot.service_lock_path.display().to_string()),
        json_string(&snapshot.metrics_path.display().to_string()),
        json_string(&snapshot.socket_path.display().to_string()),
        if snapshot.http_address.is_empty() {
            "null".to_string()
        } else {
            json_string(&snapshot.http_address)
        },
        if snapshot.http_token_required { "true" } else { "false" },
        json_string(&runtime_service_transport(snapshot)),
        json_string(&runtime_service_health(snapshot)),
        json_string(&snapshot.runtime_state_path.display().to_string()),
        json_string(&snapshot.stop_request_path.display().to_string()),
        json_string(&snapshot.stdout_log_path.display().to_string()),
        json_string(&snapshot.event_log_path.display().to_string()),
        json_string(&snapshot.ingress_stream_path.display().to_string()),
        if snapshot.available { "true" } else { "false" },
        json_string(&snapshot.session_id),
        snapshot.pid,
        if snapshot.running { "true" } else { "false" },
        json_string(&snapshot.status),
        json_string(&snapshot.updated_at),
        json_string(&snapshot.booted_at),
        json_string(&snapshot.stopped_at),
        snapshot.poll_seconds,
        snapshot.max_jobs,
        snapshot.max_iterations,
        snapshot.iterations_completed,
        snapshot.requests_received,
        snapshot.submitted,
        snapshot.processed,
        snapshot.allowed,
        snapshot.denied,
        snapshot.failed,
        snapshot.pending_jobs,
        snapshot.processed_jobs,
        snapshot.failed_jobs,
        json_string(&snapshot.last_request_id),
        json_string(&snapshot.last_job_id),
        json_string(&snapshot.note),
    )
}

fn runtime_service_transport(snapshot: &RuntimeServiceSnapshot) -> String {
    if !snapshot.http_address.trim().is_empty() && snapshot.socket_path.exists() {
        "socket+http".to_string()
    } else if !snapshot.http_address.trim().is_empty() {
        "http".to_string()
    } else if snapshot.socket_path.exists() {
        "socket".to_string()
    } else {
        "file_ingress".to_string()
    }
}

fn runtime_service_health(snapshot: &RuntimeServiceSnapshot) -> String {
    if !snapshot.available {
        "not_started".to_string()
    } else if snapshot.status == "crashed" {
        "crashed".to_string()
    } else if snapshot.running && runtime_service_transport(snapshot) == "file_ingress" {
        "degraded".to_string()
    } else if snapshot.running {
        "healthy".to_string()
    } else if snapshot.status == "stop_requested" || !snapshot.stopped_at.is_empty() {
        "stopped".to_string()
    } else {
        "degraded".to_string()
    }
}

fn render_runtime_service_health_json(snapshot: &RuntimeServiceSnapshot) -> String {
    format!(
        "{{\n  \"status\": {},\n  \"running\": {},\n  \"service_status\": {},\n  \"transport\": {},\n  \"pid\": {},\n  \"updated_at\": {},\n  \"pending_jobs\": {},\n  \"processed_jobs\": {},\n  \"failed_jobs\": {},\n  \"note\": {}\n}}\n",
        json_string(&runtime_service_health(snapshot)),
        if snapshot.running { "true" } else { "false" },
        json_string(&snapshot.status),
        json_string(&runtime_service_transport(snapshot)),
        snapshot.pid,
        json_string(&snapshot.updated_at),
        snapshot.pending_jobs,
        snapshot.processed_jobs,
        snapshot.failed_jobs,
        json_string(&snapshot.note),
    )
}

fn render_runtime_service_metrics_json(snapshot: &RuntimeServiceSnapshot) -> String {
    format!(
        "{{\n  \"uptime_seconds\": {},\n  \"requests_received\": {},\n  \"jobs_submitted\": {},\n  \"jobs_processed\": {},\n  \"jobs_allowed\": {},\n  \"jobs_denied\": {},\n  \"jobs_failed\": {},\n  \"queue_depth\": {},\n  \"processed_jobs\": {},\n  \"failed_jobs\": {},\n  \"last_request_id\": {},\n  \"last_job_id\": {}\n}}\n",
        runtime_uptime_seconds(&snapshot.booted_at, &snapshot.updated_at),
        snapshot.requests_received,
        snapshot.submitted,
        snapshot.processed,
        snapshot.allowed,
        snapshot.denied,
        snapshot.failed,
        snapshot.pending_jobs,
        snapshot.processed_jobs,
        snapshot.failed_jobs,
        json_string(&snapshot.last_request_id),
        json_string(&snapshot.last_job_id),
    )
}

fn render_runtime_service_config_json(root: &Path, snapshot: &RuntimeServiceSnapshot) -> String {
    let config = read_config(root).ok();
    let config_mode = config
        .as_ref()
        .map(|value| value.mode.clone())
        .unwrap_or_default();
    let org_id = config
        .as_ref()
        .map(|value| value.org_id.clone())
        .unwrap_or_default();
    let kernel_path = config
        .as_ref()
        .map(|value| value.kernel_path.clone())
        .unwrap_or_default();
    let service_token_env = config
        .as_ref()
        .map(|value| value.service_token_env.clone())
        .unwrap_or_else(|| "LOOM_SERVICE_TOKEN".to_string());
    let token_present = std::env::var(&service_token_env)
        .ok()
        .map(|value| !value.trim().is_empty())
        .unwrap_or(false);
    format!(
        "{{\n  \"config_path\": {},\n  \"mode\": {},\n  \"org_id\": {},\n  \"kernel_path\": {},\n  \"service_http_address\": {},\n  \"service_token_env\": {},\n  \"service_token_present\": {},\n  \"state_dir\": {},\n  \"run_dir\": {},\n  \"log_dir\": {},\n  \"artifact_dir\": {},\n  \"runtime_state_path\": {},\n  \"log_path\": {}\n}}\n",
        json_string(&snapshot.config_path.display().to_string()),
        json_string(&config_mode),
        json_string(&org_id),
        json_string(&kernel_path),
        if snapshot.http_address.is_empty() {
            "null".to_string()
        } else {
            json_string(&snapshot.http_address)
        },
        json_string(&service_token_env),
        if token_present { "true" } else { "false" },
        json_string(&state_root(root).unwrap_or_else(|_| root.join("state")).display().to_string()),
        json_string(&run_root(root).unwrap_or_else(|_| root.join("run")).display().to_string()),
        json_string(&log_root(root).unwrap_or_else(|_| root.join("logs")).display().to_string()),
        json_string(&artifact_root(root).unwrap_or_else(|_| root.join("artifacts")).display().to_string()),
        json_string(&snapshot.runtime_state_path.display().to_string()),
        json_string(&snapshot.stdout_log_path.display().to_string()),
    )
}

fn runtime_uptime_seconds(booted_at: &str, updated_at: &str) -> u64 {
    unix_seconds(updated_at).saturating_sub(unix_seconds(booted_at))
}

fn unix_seconds(value: &str) -> u64 {
    value.parse::<u64>().unwrap_or(0)
}

pub fn render_runtime_service_submit_human(capture: &RuntimeServiceSubmitCapture) -> String {
    format!(
        "Meridian Loom // SERVICE SUBMIT\n================================\nphase:       experimental runtime ingress\nboundary:    service-owned local ingress is real; live transport replacement is not\n\nCurrent state\n=============\nrequest_id:          {}\naccepted_at:         {}\ntransport:           {}\nservice_target:      {}\nsocket_path:         {}\njob_id:              {}\npolicy_class:        {}\nqueue_path:          {}\ningress_request:     {}\ningress_receipt:     {}\nnote:                {}\n\nNext\n====\n1. loom service status --root <path>\n2. loom job inspect --job-id {} --root <path>\n3. loom parity report --root <path>\n",
        capture.request_id,
        capture.accepted_at,
        capture.transport,
        capture.service_target,
        capture.socket_path.display(),
        capture.job_id,
        capture.policy_class,
        capture.queue_path.display(),
        capture.ingress_request_path.display(),
        capture.ingress_receipt_path.display(),
        capture.note,
        capture.job_id,
    )
}

pub fn render_runtime_service_submit_json(capture: &RuntimeServiceSubmitCapture) -> String {
    format!(
        "{{\n  \"status\": \"service_submit_accepted\",\n  \"request_id\": {},\n  \"accepted_at\": {},\n  \"transport\": {},\n  \"service_target\": {},\n  \"socket_path\": {},\n  \"ingress_request_path\": {},\n  \"ingress_receipt_path\": {},\n  \"job_id\": {},\n  \"policy_class\": {},\n  \"queue_path\": {},\n  \"note\": {}\n}}\n",
        json_string(&capture.request_id),
        json_string(&capture.accepted_at),
        json_string(&capture.transport),
        json_string(&capture.service_target),
        json_string(&capture.socket_path.display().to_string()),
        json_string(&capture.ingress_request_path.display().to_string()),
        json_string(&capture.ingress_receipt_path.display().to_string()),
        json_string(&capture.job_id),
        json_string(&capture.policy_class),
        json_string(&capture.queue_path.display().to_string()),
        json_string(&capture.note),
    )
}

pub fn render_runtime_service_cancel_human(capture: &RuntimeServiceCancelCapture) -> String {
    format!(
        "Meridian Loom // SERVICE CANCEL\n================================\nrequest_id:      {}\ntransport:       {}\nservice_target:  {}\nsocket_path:     {}\njob_id:          {}\nstatus:          {}\nprevious_status: {}\ncurrent_status:  {}\nnote:            {}\n",
        capture.request_id,
        capture.transport,
        capture.service_target,
        capture.socket_path.display(),
        capture.job_id,
        capture.status,
        if capture.previous_status.trim().is_empty() { "(none)" } else { capture.previous_status.as_str() },
        if capture.current_status.trim().is_empty() { "(none)" } else { capture.current_status.as_str() },
        capture.note,
    )
}

pub fn render_runtime_service_cancel_json(capture: &RuntimeServiceCancelCapture) -> String {
    format!(
        "{{\n  \"request_id\": {},\n  \"transport\": {},\n  \"service_target\": {},\n  \"socket_path\": {},\n  \"job_id\": {},\n  \"status\": {},\n  \"previous_status\": {},\n  \"current_status\": {},\n  \"note\": {}\n}}\n",
        json_string(&capture.request_id),
        json_string(&capture.transport),
        json_string(&capture.service_target),
        json_string(&capture.socket_path.display().to_string()),
        json_string(&capture.job_id),
        json_string(&capture.status),
        json_string(&capture.previous_status),
        json_string(&capture.current_status),
        json_string(&capture.note),
    )
}

pub fn render_runtime_service_import_human(capture: &RuntimeServiceImportCapture) -> String {
    format!(
        "Meridian Loom // SERVICE IMPORT\n================================\nphase:       experimental sender-side execution_request import\nboundary:    commitment outbox import is locally real; hosted runtime replacement is not\n\nCurrent state\n=============\ncommitments_source:   {}\nimports_dir:          {}\nimported:             {}\nskipped:              {}\nlast_import_id:       {}\nlast_job_id:          {}\nnote:                 {}\n\nNext\n====\n1. loom job inspect --job-id {} --root <path>\n2. loom service status --root <path>\n3. loom parity report --root <path>\n",
        capture.commitments_source,
        capture.imports_dir.display(),
        capture.imported,
        capture.skipped,
        if capture.last_import_id.is_empty() { "(none)".to_string() } else { capture.last_import_id.clone() },
        if capture.last_job_id.is_empty() { "(none)".to_string() } else { capture.last_job_id.clone() },
        capture.note,
        if capture.last_job_id.is_empty() { "<job_id>".to_string() } else { capture.last_job_id.clone() },
    )
}

pub fn render_runtime_service_import_json(capture: &RuntimeServiceImportCapture) -> String {
    format!(
        "{{\n  \"status\": \"service_import_completed\",\n  \"commitments_source\": {},\n  \"imports_dir\": {},\n  \"imported\": {},\n  \"skipped\": {},\n  \"last_import_id\": {},\n  \"last_job_id\": {},\n  \"note\": {}\n}}\n",
        json_string(&capture.commitments_source),
        json_string(&capture.imports_dir.display().to_string()),
        capture.imported,
        capture.skipped,
        json_string(&capture.last_import_id),
        json_string(&capture.last_job_id),
        json_string(&capture.note),
    )
}

pub fn render_compare_human(summary: &ComparisonSummary) -> String {
    let divergence_lines = {
        let rendered = summary
            .hook_results
            .iter()
            .filter(|item| !item.matched)
            .map(|item| {
                format!(
                    "  [{}] {} | primary={} | shadow={} | input={}\n",
                    item.pair_index,
                    item.hook_name,
                    item.primary_decision,
                    item.shadow_decision,
                    item.input_hash
                )
            })
            .collect::<Vec<_>>()
            .join("");
        if rendered.is_empty() {
            "  (none)\n".to_string()
        } else {
            rendered
        }
    };
    format!(
        "Meridian Loom // SHADOW COMPARE\n================================\nprimary_log:     {}\nshadow_log:      {}\nprimary_events:  {}\nshadow_events:   {}\npairs_compared:  {}\nmatches:         {}\ndivergences:     {}\ndivergence_rate: {:.4}\n\nDivergence details\n------------------\n{}note:            {}\n",
        summary.primary_log.display(),
        summary.shadow_log.display(),
        summary.primary_events,
        summary.shadow_events,
        summary.pairs_compared,
        summary.matches,
        summary.divergences,
        summary.divergence_rate,
        divergence_lines,
        summary.note,
    )
}

pub fn render_compare_json(summary: &ComparisonSummary) -> String {
    let hook_results = summary
        .hook_results
        .iter()
        .map(|item| {
            format!(
                "    {{\"pair_index\":{},\"hook_name\":{},\"input_hash\":{},\"primary_decision\":{},\"shadow_decision\":{},\"matched\":{},\"primary_agent_id\":{},\"shadow_agent_id\":{},\"primary_org_id\":{},\"shadow_org_id\":{}}}",
                item.pair_index,
                json_string(&item.hook_name),
                json_string(&item.input_hash),
                json_string(&item.primary_decision),
                json_string(&item.shadow_decision),
                if item.matched { "true" } else { "false" },
                json_string(&item.primary_agent_id),
                json_string(&item.shadow_agent_id),
                json_string(&item.primary_org_id),
                json_string(&item.shadow_org_id),
            )
        })
        .collect::<Vec<_>>()
        .join(",\n");
    format!(
        "{{\n  \"status\": \"comparison_complete\",\n  \"primary_log\": {},\n  \"shadow_log\": {},\n  \"primary_events\": {},\n  \"shadow_events\": {},\n  \"pairs_compared\": {},\n  \"matches\": {},\n  \"divergences\": {},\n  \"divergence_rate\": {:.6},\n  \"hook_results\": [\n{}\n  ],\n  \"note\": {}\n}}\n",
        json_string(&summary.primary_log.display().to_string()),
        json_string(&summary.shadow_log.display().to_string()),
        summary.primary_events,
        summary.shadow_events,
        summary.pairs_compared,
        summary.matches,
        summary.divergences,
        summary.divergence_rate,
        hook_results,
        json_string(&summary.note),
    )
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct ShadowZkProofArtifact {
    status: String,
    proof_backend: String,
    proof_mode: String,
    proof_id: String,
    verification_status: String,
    warrant_binding_status: String,
    warrant_id_hex: String,
    merkle_root_hex: String,
    witness_digest_hex: String,
    trace_len: u32,
    epoch_start_ms: u64,
    epoch_end_ms: u64,
    session_label: String,
    captured_at: String,
}

#[derive(Clone, Debug, PartialEq)]
struct ShadowSettlementArtifact {
    status: String,
    captured_at: String,
    proof_backend: String,
    proof_status: String,
    proof_id: String,
    court_status: String,
    authority_status: String,
    treasury_status: String,
    settlement_status: String,
    reservation_id: Option<String>,
    actual_cost_usd: Option<f64>,
    witness_digest_hex: Option<String>,
    merkle_root_hex: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct ShadowGrpcActionDiagnostics {
    status: String,
    captured_at: String,
    grpc_target: String,
    grpc_rpc: String,
    grpc_transport: String,
    grpc_allow_unknown_fields: bool,
    grpc_max_time_seconds: Option<u64>,
    grpc_schema: String,
    grpc_request_id: String,
    grpc_action_kind: String,
    grpc_action_objective: String,
    grpc_action_skill: String,
    grpc_proto_count: Option<u64>,
    grpc_protoset_count: Option<u64>,
    grpc_import_path_count: Option<u64>,
    grpc_authority: String,
    exit_code: Option<i32>,
    grpc_physical_robot_id: String,
    grpc_physical_target: String,
    grpc_physical_command: String,
    grpc_physical_safety_class: String,
    grpc_physical_dry_run: Option<bool>,
    grpc_lifecycle_mode: String,
    grpc_lifecycle_ack_required: Option<bool>,
    grpc_lifecycle_ack_timeout_seconds: Option<u64>,
    grpc_lifecycle_ack_received: Option<bool>,
    grpc_lifecycle_ack_latency_ms: Option<u64>,
    grpc_lifecycle_cancel_on_ack_timeout: Option<bool>,
    grpc_lifecycle_cancel_after_seconds: Option<u64>,
    grpc_lifecycle_cancelled: Option<bool>,
    grpc_lifecycle_cancel_reason: String,
    grpc_lifecycle_status: String,
    grpc_lifecycle_stream_event_count: Option<u64>,
    grpc_remediation_profile: String,
    grpc_remediation_action: String,
}

pub fn render_shadow_report(root: &Path) -> ShadowResult<String> {
    let report_path = ensure_shadow_dir(root)?.join("latest.json");
    let contents = fs::read_to_string(&report_path).ok();
    let shadow_latest = load_shadow_run_capture(&report_path);
    let reference_path = ensure_shadow_dir(root)?.join("reference.json");
    let reference = fs::read_to_string(&reference_path).ok();
    let decision_path = ensure_shadow_dir(root)?.join("decision.json");
    let decision = fs::read_to_string(&decision_path).ok();
    let runtime_path = ensure_runtime_dir(root)?.join("last_execution.json");
    let runtime = fs::read_to_string(&runtime_path).ok();
    let runtime_capture = load_shadow_run_capture(&runtime_path);
    let runtime_event_path = runtime_event_latest_path(root)?;
    let runtime_event = fs::read_to_string(&runtime_event_path).ok();
    let parity_path = ensure_parity_dir(root)?.join("latest.json");
    let parity = fs::read_to_string(&parity_path).ok();
    let parity_capture = load_shadow_run_capture(&parity_path);
    let zk_path = artifact_root(root)?.join("zk").join("latest.json");
    let zk = fs::read_to_string(&zk_path).ok();
    let zk_latest = load_zk_proof_artifact(&zk_path);
    let settlement_path = artifact_root(root)?.join("settlement").join("latest.json");
    let settlement = fs::read_to_string(&settlement_path).ok();
    let settlement_latest = load_settlement_artifact(&settlement_path);
    let grpc_diagnostics_path = ensure_shadow_grpc_action_dir(root)?.join("latest.json");
    let grpc_diagnostics = fs::read_to_string(&grpc_diagnostics_path).ok();
    let grpc_diagnostics_latest = load_grpc_action_diagnostics_artifact(&grpc_diagnostics_path);
    if contents.is_none()
        && reference.is_none()
        && decision.is_none()
        && runtime.is_none()
        && runtime_event.is_none()
        && parity.is_none()
        && zk.is_none()
        && settlement.is_none()
        && grpc_diagnostics.is_none()
    {
        return Err(format!(
            "could not read any shadow artifacts under {}",
            ensure_shadow_dir(root)?.display()
        ));
    }
    let mut out = String::from(
        "Meridian Loom // SHADOW REPORT\n==============================\nphase:       experimental shadow + parity surface\nboundary:    report artifacts are real; governed runtime is not\n",
    );
    let stale_latest = shadow_latest
        .as_ref()
        .map(|value| value.status == "not_started")
        .or_else(|| {
            contents
                .as_ref()
                .map(|value| value.contains("\"status\": \"not_started\""))
        })
        .unwrap_or(false);
    let no_newer_artifacts =
        runtime.is_none() && parity.is_none() && decision.is_none() && reference.is_none();

    if stale_latest && no_newer_artifacts {
        out.push_str(&format!(
            "\nCurrent state\n=============\nsource: {}\nstatus:      not_started\nmeaning:     no shadow or runtime rehearsal artifacts have been captured yet\n\nRecommended next step\n=====================\n  loom shadow preflight --agent-id agent_atlas --action-type research --resource web_search --kernel-path /opt/meridian-kernel --root {}\n  loom shadow decide --agent-id agent_atlas --action-type research --resource web_search --kernel-path /opt/meridian-kernel --root {}\n  loom action execute --agent-id agent_atlas --action-type research --resource web_search --kernel-path /opt/meridian-kernel --root {}\n",
            report_path.display(),
            root.display(),
            root.display(),
            root.display(),
        ));
        return Ok(out);
    }

    if let Some(runtime_capture) = runtime_capture.as_ref() {
        out.push_str(&render_shadow_run_summary(
            "Runtime execution",
            &runtime_path,
            runtime_capture,
        ));
    } else if let Some(runtime) = runtime.as_ref() {
        out.push_str(&format!(
            "Runtime execution\n=================\nsource: {}\n\n{}\n",
            runtime_path.display(),
            runtime
        ));
    }
    if let Some(runtime_event) = runtime_event.as_ref() {
        out.push_str(&format!(
            "\nRuntime event latest\n====================\nsource: {}\n\n{}\n",
            runtime_event_path.display(),
            runtime_event
        ));
    }
    if let Some(parity_capture) = parity_capture.as_ref() {
        out.push_str(&render_shadow_run_summary(
            "Parity latest",
            &parity_path,
            parity_capture,
        ));
    } else if let Some(parity) = parity.as_ref() {
        out.push_str(&format!(
            "\nParity latest\n=============\nsource: {}\n\n{}\n",
            parity_path.display(),
            parity
        ));
    }
    if let Some(zk_latest) = zk_latest.as_ref() {
        out.push_str(&render_zk_proof_summary(&zk_path, zk_latest));
    } else if let Some(zk) = zk.as_ref() {
        out.push_str(&format!(
            "\nZK proof latest\n===============\nsource: {}\n\n{}\n",
            zk_path.display(),
            zk
        ));
    }
    if let Some(settlement_latest) = settlement_latest.as_ref() {
        out.push_str(&render_settlement_summary(
            &settlement_path,
            settlement_latest,
        ));
    } else if let Some(settlement) = settlement.as_ref() {
        out.push_str(&format!(
            "\nSettlement latest\n=================\nsource: {}\n\n{}\n",
            settlement_path.display(),
            settlement
        ));
    }
    if let Some(grpc_diagnostics_latest) = grpc_diagnostics_latest.as_ref() {
        out.push_str(&render_grpc_action_diagnostics_summary(
            &grpc_diagnostics_path,
            grpc_diagnostics_latest,
        ));
    } else if let Some(runtime_capture) = runtime_capture
        .as_ref()
        .and_then(load_grpc_action_diagnostics)
    {
        out.push_str(&render_grpc_action_diagnostics_summary(
            &runtime_path,
            &runtime_capture,
        ));
    } else if let Some(shadow_capture) = shadow_latest
        .as_ref()
        .and_then(load_grpc_action_diagnostics)
    {
        out.push_str(&render_grpc_action_diagnostics_summary(
            &report_path,
            &shadow_capture,
        ));
    }
    if let Some(decision) = decision.as_ref() {
        out.push_str(&format!(
            "\nDecision artifact\n=================\nsource: {}\n\n{}\n",
            decision_path.display(),
            decision
        ));
    }
    if let Some(reference) = reference.as_ref() {
        out.push_str(&format!(
            "\nReference gates\n===============\nsource: {}\n\n{}\n",
            reference_path.display(),
            reference
        ));
    }
    if let Some(shadow_latest) = shadow_latest.as_ref() {
        out.push_str(&render_shadow_run_summary(
            "Shadow latest",
            &report_path,
            shadow_latest,
        ));
    } else if let Some(contents) = contents.as_ref() {
        let label = if stale_latest && (runtime.is_some() || parity.is_some()) {
            "Legacy shadow marker"
        } else {
            "Shadow latest"
        };
        out.push_str(&format!(
            "\n{}\n{}\nsource: {}\n\n{}\n",
            label,
            "=".repeat(label.len()),
            report_path.display(),
            contents
        ));
    } else {
        out.push_str("\nShadow latest\n=============\nsource: (latest report not present)\n\n");
    }
    if stale_latest && runtime.is_some() {
        out.push_str(
            "Note\n----\nlatest shadow marker still says `not_started`; the runtime execution and parity sections above are the newer operator surfaces for this flow.\n",
        );
    }
    Ok(out)
}

fn load_shadow_run_capture(path: &Path) -> Option<ShadowRunCapture> {
    let value = load_artifact_json(path)?;
    if value.get("status").and_then(Value::as_str) != Some("shadow_run_captured") {
        return None;
    }
    Some(ShadowRunCapture {
        execution_path: PathBuf::from(value_string(value.get("execution_path"))),
        shadow_latest_path: PathBuf::from(value_string(value.get("shadow_latest_path"))),
        parity_latest_path: PathBuf::from(value_string(value.get("parity_latest_path"))),
        parity_stream_path: path
            .parent()
            .map(|parent| parent.join("stream.jsonl"))
            .unwrap_or_else(|| PathBuf::from("stream.jsonl")),
        status: value_string(value.get("status")),
        captured_at: value_string(value.get("captured_at")),
        backend: value_string(value.get("backend")),
        agent_id: value_string(value.get("agent_id")),
        org_id: value_string(value.get("org_id")),
        action_type: value_string(value.get("action_type")),
        resource: value_string(value.get("resource")),
        module_name: value_string(value.get("module_name")),
        entrypoint: value_string(value.get("entrypoint")),
        entrypoint_result: value
            .get("entrypoint_result")
            .and_then(Value::as_i64)
            .map(|value| value as i32),
        host_backend: value_string(value.get("host_backend")),
        warrant_binding_status: value_string(value.get("warrant_binding_status")),
        warrant_id_hex: optional_value_string(value.get("warrant_id_hex")),
        poge_merkle_root_hex: optional_value_string(value.get("poge_merkle_root_hex")),
        poge_trace_len: value
            .get("poge_trace_len")
            .and_then(Value::as_u64)
            .map(|value| value as u32),
        poge_witness_digest_hex: optional_value_string(value.get("poge_witness_digest_hex")),
        poge_session_label: optional_value_string(value.get("poge_session_label")),
        poge_epoch_start_ms: value.get("poge_epoch_start_ms").and_then(Value::as_u64),
        poge_epoch_end_ms: value.get("poge_epoch_end_ms").and_then(Value::as_u64),
        poge_module_digest_hex: optional_value_string(value.get("poge_module_digest_hex")),
        host_calls: value_string_vec(value.get("host_calls")),
        host_response_json: optional_value_string(value.get("host_response_json")),
    })
}

fn load_zk_proof_artifact(path: &Path) -> Option<ShadowZkProofArtifact> {
    let value = load_artifact_json(path)?;
    Some(ShadowZkProofArtifact {
        status: value_string(value.get("status")),
        proof_backend: value_string(value.get("proof_backend")),
        proof_mode: value_string(value.get("proof_mode")),
        proof_id: value_string(value.get("proof_id")),
        verification_status: value_string(value.get("verification_status")),
        warrant_binding_status: value_string(value.get("warrant_binding_status")),
        warrant_id_hex: value_string(value.get("warrant_id_hex")),
        merkle_root_hex: value_string(value.get("poge_merkle_root_hex")),
        witness_digest_hex: value_string(value.get("witness_digest_hex")),
        trace_len: value
            .get("poge_trace_len")
            .and_then(Value::as_u64)
            .unwrap_or_default() as u32,
        epoch_start_ms: value
            .get("poge_epoch_start_ms")
            .and_then(Value::as_u64)
            .unwrap_or_default(),
        epoch_end_ms: value
            .get("poge_epoch_end_ms")
            .and_then(Value::as_u64)
            .unwrap_or_default(),
        session_label: value_string(value.get("poge_session_label")),
        captured_at: value_string(value.get("captured_at")),
    })
}

fn load_settlement_artifact(path: &Path) -> Option<ShadowSettlementArtifact> {
    let value = load_artifact_json(path)?;
    Some(ShadowSettlementArtifact {
        status: value_string(value.get("status")),
        captured_at: value_string(value.get("captured_at")),
        proof_backend: value_string(value.get("proof_backend")),
        proof_status: value_string(value.get("proof_status")),
        proof_id: value_string(value.get("proof_id")),
        court_status: value_string(value.get("court_status")),
        authority_status: value_string(value.get("authority_status")),
        treasury_status: value_string(value.get("treasury_status")),
        settlement_status: value_string(value.get("settlement_status")),
        reservation_id: optional_value_string(value.get("reservation_id")),
        actual_cost_usd: value.get("actual_cost_usd").and_then(Value::as_f64),
        witness_digest_hex: optional_value_string(value.get("witness_digest_hex")),
        merkle_root_hex: optional_value_string(value.get("poge_merkle_root_hex")),
    })
}

fn load_artifact_json(path: &Path) -> Option<Value> {
    let raw = fs::read_to_string(path).ok()?;
    serde_json::from_str(&raw).ok()
}

fn optional_value_string(value: Option<&Value>) -> Option<String> {
    let rendered = value_string(value);
    if rendered.is_empty() || rendered == "null" {
        None
    } else {
        Some(rendered)
    }
}

fn load_grpc_action_diagnostics(capture: &ShadowRunCapture) -> Option<ShadowGrpcActionDiagnostics> {
    if capture.backend != "grpc_action"
        && capture.backend != "grpc_physical"
        && capture.host_backend != "external_grpc_action"
        && capture.host_backend != "external_grpc_physical"
    {
        return None;
    }
    let raw = capture.host_response_json.as_deref()?;
    let value: Value = serde_json::from_str(raw).ok()?;
    let mut diagnostics = grpc_action_diagnostics_from_value(&value);
    if diagnostics.captured_at.is_empty() {
        diagnostics.captured_at = capture.captured_at.clone();
    }
    Some(diagnostics)
}

fn load_grpc_action_diagnostics_artifact(path: &Path) -> Option<ShadowGrpcActionDiagnostics> {
    let value = load_artifact_json(path)?;
    Some(grpc_action_diagnostics_from_value(&value))
}

fn grpc_action_diagnostics_from_value(value: &Value) -> ShadowGrpcActionDiagnostics {
    ShadowGrpcActionDiagnostics {
        status: value_string(value.get("status")),
        captured_at: value_string(value.get("captured_at")),
        grpc_target: value_string(value.get("grpc_target")),
        grpc_rpc: value_string(value.get("grpc_rpc")),
        grpc_transport: value_string(value.get("grpc_transport")),
        grpc_allow_unknown_fields: value
            .get("grpc_allow_unknown_fields")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        grpc_max_time_seconds: value.get("grpc_max_time_seconds").and_then(Value::as_u64),
        grpc_schema: value_string(value.get("grpc_schema")),
        grpc_request_id: value_string(value.get("grpc_request_id")),
        grpc_action_kind: value_string(value.get("grpc_action_kind")),
        grpc_action_objective: value_string(value.get("grpc_action_objective")),
        grpc_action_skill: value_string(value.get("grpc_action_skill")),
        grpc_proto_count: value.get("grpc_proto_count").and_then(Value::as_u64),
        grpc_protoset_count: value.get("grpc_protoset_count").and_then(Value::as_u64),
        grpc_import_path_count: value.get("grpc_import_path_count").and_then(Value::as_u64),
        grpc_authority: value_string(value.get("grpc_authority")),
        exit_code: value
            .get("exit_code")
            .and_then(Value::as_i64)
            .map(|code| code as i32),
        grpc_physical_robot_id: value_string(value.get("grpc_physical_robot_id")),
        grpc_physical_target: value_string(value.get("grpc_physical_target")),
        grpc_physical_command: value_string(value.get("grpc_physical_command")),
        grpc_physical_safety_class: value_string(value.get("grpc_physical_safety_class")),
        grpc_physical_dry_run: value.get("grpc_physical_dry_run").and_then(Value::as_bool),
        grpc_lifecycle_mode: value_string(value.get("grpc_lifecycle_mode")),
        grpc_lifecycle_ack_required: value
            .get("grpc_lifecycle_ack_required")
            .and_then(Value::as_bool),
        grpc_lifecycle_ack_timeout_seconds: value
            .get("grpc_lifecycle_ack_timeout_seconds")
            .and_then(Value::as_u64),
        grpc_lifecycle_ack_received: value
            .get("grpc_lifecycle_ack_received")
            .and_then(Value::as_bool),
        grpc_lifecycle_ack_latency_ms: value
            .get("grpc_lifecycle_ack_latency_ms")
            .and_then(Value::as_u64),
        grpc_lifecycle_cancel_on_ack_timeout: value
            .get("grpc_lifecycle_cancel_on_ack_timeout")
            .and_then(Value::as_bool),
        grpc_lifecycle_cancel_after_seconds: value
            .get("grpc_lifecycle_cancel_after_seconds")
            .and_then(Value::as_u64),
        grpc_lifecycle_cancelled: value
            .get("grpc_lifecycle_cancelled")
            .and_then(Value::as_bool),
        grpc_lifecycle_cancel_reason: value_string(value.get("grpc_lifecycle_cancel_reason")),
        grpc_lifecycle_status: value_string(value.get("grpc_lifecycle_status")),
        grpc_lifecycle_stream_event_count: value
            .get("grpc_lifecycle_stream_event_count")
            .and_then(Value::as_u64),
        grpc_remediation_profile: value_string(value.get("grpc_remediation_profile")),
        grpc_remediation_action: value_string(value.get("grpc_remediation_action")),
    }
}

fn grpc_action_diagnostics_to_value(diagnostics: &ShadowGrpcActionDiagnostics) -> Value {
    serde_json::json!({
        "status": diagnostics.status,
        "captured_at": diagnostics.captured_at,
        "grpc_target": diagnostics.grpc_target,
        "grpc_rpc": diagnostics.grpc_rpc,
        "grpc_transport": diagnostics.grpc_transport,
        "grpc_allow_unknown_fields": diagnostics.grpc_allow_unknown_fields,
        "grpc_max_time_seconds": diagnostics.grpc_max_time_seconds,
        "grpc_schema": diagnostics.grpc_schema,
        "grpc_request_id": diagnostics.grpc_request_id,
        "grpc_action_kind": diagnostics.grpc_action_kind,
        "grpc_action_objective": diagnostics.grpc_action_objective,
        "grpc_action_skill": diagnostics.grpc_action_skill,
        "grpc_proto_count": diagnostics.grpc_proto_count,
        "grpc_protoset_count": diagnostics.grpc_protoset_count,
        "grpc_import_path_count": diagnostics.grpc_import_path_count,
        "grpc_authority": diagnostics.grpc_authority,
        "exit_code": diagnostics.exit_code,
        "grpc_physical_robot_id": diagnostics.grpc_physical_robot_id,
        "grpc_physical_target": diagnostics.grpc_physical_target,
        "grpc_physical_command": diagnostics.grpc_physical_command,
        "grpc_physical_safety_class": diagnostics.grpc_physical_safety_class,
        "grpc_physical_dry_run": diagnostics.grpc_physical_dry_run,
        "grpc_lifecycle_mode": diagnostics.grpc_lifecycle_mode,
        "grpc_lifecycle_ack_required": diagnostics.grpc_lifecycle_ack_required,
        "grpc_lifecycle_ack_timeout_seconds": diagnostics.grpc_lifecycle_ack_timeout_seconds,
        "grpc_lifecycle_ack_received": diagnostics.grpc_lifecycle_ack_received,
        "grpc_lifecycle_ack_latency_ms": diagnostics.grpc_lifecycle_ack_latency_ms,
        "grpc_lifecycle_cancel_on_ack_timeout": diagnostics.grpc_lifecycle_cancel_on_ack_timeout,
        "grpc_lifecycle_cancel_after_seconds": diagnostics.grpc_lifecycle_cancel_after_seconds,
        "grpc_lifecycle_cancelled": diagnostics.grpc_lifecycle_cancelled,
        "grpc_lifecycle_cancel_reason": diagnostics.grpc_lifecycle_cancel_reason,
        "grpc_lifecycle_status": diagnostics.grpc_lifecycle_status,
        "grpc_lifecycle_stream_event_count": diagnostics.grpc_lifecycle_stream_event_count,
        "grpc_remediation_profile": diagnostics.grpc_remediation_profile,
        "grpc_remediation_action": diagnostics.grpc_remediation_action,
    })
}

fn render_shadow_run_summary(title: &str, source: &Path, capture: &ShadowRunCapture) -> String {
    let host_calls = if capture.host_calls.is_empty() {
        "(none)".to_string()
    } else {
        capture.host_calls.join(", ")
    };
    let source_label = match title {
        "Runtime execution" => "typed runtime execution",
        "Shadow latest" => "typed shadow capture",
        "Parity latest" => "typed parity capture",
        _ => "typed shadow artifact",
    };
    let mut output = format!(
        "\n{}\n{}\nsource: {} @ {}\nstatus:      {}\nbackend:     {}\nagent_id:    {}\norg_id:      {}\naction_type: {}\nresource:    {}\nmodule_name: {}\nentrypoint:  {}\nresult:      {}\nhost_backend:{}\nwarrant:     {}\npoge_root:   {}\nwitness:     {}\nhost_calls:  {}\n",
        title,
        "=".repeat(title.len()),
        source_label,
        source.display(),
        capture.status,
        capture.backend,
        capture.agent_id,
        capture.org_id,
        capture.action_type,
        capture.resource,
        capture.module_name,
        capture.entrypoint,
        capture
            .entrypoint_result
            .map(|value| value.to_string())
            .unwrap_or_else(|| "null".to_string()),
        capture.host_backend,
        capture.warrant_binding_status,
        capture
            .poge_merkle_root_hex
            .as_deref()
            .unwrap_or("(none)"),
        capture
            .poge_witness_digest_hex
            .as_deref()
            .unwrap_or("(none)"),
        host_calls,
    );
    if let Some(diag) = load_grpc_action_diagnostics(capture) {
        output.push_str(&format!(
            "grpc_target: {}\ngrpc_rpc:    {}\ngrpc_status: {}\ngrpc_transport: {}\ngrpc_allow_unknown_fields: {}\ngrpc_max_time_seconds: {}\ngrpc_proto_count: {}\ngrpc_protoset_count: {}\ngrpc_import_path_count: {}\ngrpc_authority: {}\ngrpc_schema: {}\ngrpc_request_id: {}\ngrpc_action_kind: {}\ngrpc_action_objective: {}\ngrpc_action_skill: {}\ngrpc_exit_code: {}\n",
            if diag.grpc_target.is_empty() { "(none)" } else { diag.grpc_target.as_str() },
            if diag.grpc_rpc.is_empty() { "(none)" } else { diag.grpc_rpc.as_str() },
            if diag.status.is_empty() { "(none)" } else { diag.status.as_str() },
            if diag.grpc_transport.is_empty() { "(none)" } else { diag.grpc_transport.as_str() },
            if diag.grpc_allow_unknown_fields { "true" } else { "false" },
            diag.grpc_max_time_seconds
                .map(|value| value.to_string())
                .unwrap_or_else(|| "(none)".to_string()),
            diag.grpc_proto_count
                .map(|value| value.to_string())
                .unwrap_or_else(|| "(none)".to_string()),
            diag.grpc_protoset_count
                .map(|value| value.to_string())
                .unwrap_or_else(|| "(none)".to_string()),
            diag.grpc_import_path_count
                .map(|value| value.to_string())
                .unwrap_or_else(|| "(none)".to_string()),
            if diag.grpc_authority.is_empty() { "(none)" } else { diag.grpc_authority.as_str() },
            if diag.grpc_schema.is_empty() { "(none)" } else { diag.grpc_schema.as_str() },
            if diag.grpc_request_id.is_empty() { "(none)" } else { diag.grpc_request_id.as_str() },
            if diag.grpc_action_kind.is_empty() { "(none)" } else { diag.grpc_action_kind.as_str() },
            if diag.grpc_action_objective.is_empty() { "(none)" } else { diag.grpc_action_objective.as_str() },
            if diag.grpc_action_skill.is_empty() { "(none)" } else { diag.grpc_action_skill.as_str() },
            diag.exit_code
                .map(|value| value.to_string())
                .unwrap_or_else(|| "(none)".to_string()),
        ));
        if !diag.grpc_physical_robot_id.is_empty()
            || !diag.grpc_physical_target.is_empty()
            || !diag.grpc_physical_command.is_empty()
            || !diag.grpc_physical_safety_class.is_empty()
            || diag.grpc_physical_dry_run.is_some()
        {
            output.push_str(&format!(
                "grpc_physical_robot_id: {}\ngrpc_physical_target: {}\ngrpc_physical_command: {}\ngrpc_physical_safety_class: {}\ngrpc_physical_dry_run: {}\n",
                if diag.grpc_physical_robot_id.is_empty() {
                    "(none)"
                } else {
                    diag.grpc_physical_robot_id.as_str()
                },
                if diag.grpc_physical_target.is_empty() {
                    "(none)"
                } else {
                    diag.grpc_physical_target.as_str()
                },
                if diag.grpc_physical_command.is_empty() {
                    "(none)"
                } else {
                    diag.grpc_physical_command.as_str()
                },
                if diag.grpc_physical_safety_class.is_empty() {
                    "(none)"
                } else {
                    diag.grpc_physical_safety_class.as_str()
                },
                diag.grpc_physical_dry_run
                    .map(|value| if value { "true" } else { "false" })
                    .unwrap_or("(none)")
            ));
        }
        if !diag.grpc_lifecycle_mode.is_empty()
            || diag.grpc_lifecycle_ack_required.is_some()
            || diag.grpc_lifecycle_ack_received.is_some()
            || diag.grpc_lifecycle_cancelled.is_some()
            || !diag.grpc_lifecycle_cancel_reason.is_empty()
            || !diag.grpc_remediation_profile.is_empty()
            || !diag.grpc_remediation_action.is_empty()
        {
            output.push_str(&format!(
                "grpc_lifecycle_mode: {}\ngrpc_lifecycle_ack_required: {}\ngrpc_lifecycle_ack_timeout_seconds: {}\ngrpc_lifecycle_ack_received: {}\ngrpc_lifecycle_ack_latency_ms: {}\ngrpc_lifecycle_cancel_on_ack_timeout: {}\ngrpc_lifecycle_cancel_after_seconds: {}\ngrpc_lifecycle_cancelled: {}\ngrpc_lifecycle_cancel_reason: {}\ngrpc_lifecycle_status: {}\ngrpc_lifecycle_stream_event_count: {}\ngrpc_remediation_profile: {}\ngrpc_remediation_action: {}\n",
                if diag.grpc_lifecycle_mode.is_empty() {
                    "(none)"
                } else {
                    diag.grpc_lifecycle_mode.as_str()
                },
                diag.grpc_lifecycle_ack_required
                    .map(|value| if value { "true" } else { "false" })
                    .unwrap_or("(none)"),
                diag.grpc_lifecycle_ack_timeout_seconds
                    .map(|value| value.to_string())
                    .unwrap_or_else(|| "(none)".to_string()),
                diag.grpc_lifecycle_ack_received
                    .map(|value| if value { "true" } else { "false" })
                    .unwrap_or("(none)"),
                diag.grpc_lifecycle_ack_latency_ms
                    .map(|value| value.to_string())
                    .unwrap_or_else(|| "(none)".to_string()),
                diag.grpc_lifecycle_cancel_on_ack_timeout
                    .map(|value| if value { "true" } else { "false" })
                    .unwrap_or("(none)"),
                diag.grpc_lifecycle_cancel_after_seconds
                    .map(|value| value.to_string())
                    .unwrap_or_else(|| "(none)".to_string()),
                diag.grpc_lifecycle_cancelled
                    .map(|value| if value { "true" } else { "false" })
                    .unwrap_or("(none)"),
                if diag.grpc_lifecycle_cancel_reason.is_empty() {
                    "(none)"
                } else {
                    diag.grpc_lifecycle_cancel_reason.as_str()
                },
                if diag.grpc_lifecycle_status.is_empty() {
                    "(none)"
                } else {
                    diag.grpc_lifecycle_status.as_str()
                },
                diag.grpc_lifecycle_stream_event_count
                    .map(|value| value.to_string())
                    .unwrap_or_else(|| "(none)".to_string()),
                if diag.grpc_remediation_profile.is_empty() {
                    "(none)"
                } else {
                    diag.grpc_remediation_profile.as_str()
                },
                if diag.grpc_remediation_action.is_empty() {
                    "(none)"
                } else {
                    diag.grpc_remediation_action.as_str()
                },
            ));
        }
    }
    output
}

fn render_zk_proof_summary(path: &Path, artifact: &ShadowZkProofArtifact) -> String {
    format!(
        "\nZK proof latest\n===============\nsource: typed zk proof @ {}\nstatus:             {}\nproof_backend:      {}\nproof_mode:         {}\nproof_id:           {}\nverification:       {}\nwarrant_binding:    {}\nwarrant_id:         {}\npoge_merkle_root:   {}\nwitness_digest:     {}\ntrace_len:          {}\nsession_label:      {}\ncaptured_at:        {}\n",
        path.display(),
        artifact.status,
        artifact.proof_backend,
        artifact.proof_mode,
        artifact.proof_id,
        artifact.verification_status,
        artifact.warrant_binding_status,
        artifact.warrant_id_hex,
        artifact.merkle_root_hex,
        artifact.witness_digest_hex,
        artifact.trace_len,
        artifact.session_label,
        artifact.captured_at,
    )
}

fn render_settlement_summary(path: &Path, artifact: &ShadowSettlementArtifact) -> String {
    format!(
        "\nSettlement latest\n=================\nsource: typed settlement artifact @ {}\nstatus:             {}\nproof_backend:      {}\nproof_status:       {}\nproof_id:           {}\ncourt_status:       {}\nauthority_status:   {}\ntreasury_status:    {}\nsettlement_status:  {}\nreservation_id:     {}\nactual_cost_usd:    {}\nwitness_digest:     {}\npoge_merkle_root:   {}\ncaptured_at:        {}\n",
        path.display(),
        artifact.status,
        artifact.proof_backend,
        artifact.proof_status,
        artifact.proof_id,
        artifact.court_status,
        artifact.authority_status,
        artifact.treasury_status,
        artifact.settlement_status,
        artifact
            .reservation_id
            .as_deref()
            .unwrap_or("(none)"),
        artifact
            .actual_cost_usd
            .map(|value| format!("{:.6}", value))
            .unwrap_or_else(|| "(none)".to_string()),
        artifact
            .witness_digest_hex
            .as_deref()
            .unwrap_or("(none)"),
        artifact
            .merkle_root_hex
            .as_deref()
            .unwrap_or("(none)"),
        artifact.captured_at,
    )
}

fn render_grpc_action_diagnostics_summary(
    path: &Path,
    artifact: &ShadowGrpcActionDiagnostics,
) -> String {
    let mut output = format!(
        "\nGrpc action diagnostics latest\n==============================\nsource: typed grpc diagnostics @ {}\nstatus:                  {}\ncaptured_at:             {}\ngrpc_target:             {}\ngrpc_rpc:                {}\ngrpc_transport:          {}\ngrpc_allow_unknown:      {}\ngrpc_max_time_seconds:   {}\ngrpc_proto_count:        {}\ngrpc_protoset_count:     {}\ngrpc_import_path_count:  {}\ngrpc_authority:          {}\ngrpc_schema:             {}\ngrpc_request_id:         {}\ngrpc_action_kind:        {}\ngrpc_action_objective:   {}\ngrpc_action_skill:       {}\ngrpc_exit_code:          {}\n",
        path.display(),
        if artifact.status.is_empty() {
            "(none)"
        } else {
            artifact.status.as_str()
        },
        if artifact.captured_at.is_empty() {
            "(none)"
        } else {
            artifact.captured_at.as_str()
        },
        if artifact.grpc_target.is_empty() {
            "(none)"
        } else {
            artifact.grpc_target.as_str()
        },
        if artifact.grpc_rpc.is_empty() {
            "(none)"
        } else {
            artifact.grpc_rpc.as_str()
        },
        if artifact.grpc_transport.is_empty() {
            "(none)"
        } else {
            artifact.grpc_transport.as_str()
        },
        if artifact.grpc_allow_unknown_fields {
            "true"
        } else {
            "false"
        },
        artifact
            .grpc_max_time_seconds
            .map(|value| value.to_string())
            .unwrap_or_else(|| "(none)".to_string()),
        artifact
            .grpc_proto_count
            .map(|value| value.to_string())
            .unwrap_or_else(|| "(none)".to_string()),
        artifact
            .grpc_protoset_count
            .map(|value| value.to_string())
            .unwrap_or_else(|| "(none)".to_string()),
        artifact
            .grpc_import_path_count
            .map(|value| value.to_string())
            .unwrap_or_else(|| "(none)".to_string()),
        if artifact.grpc_authority.is_empty() {
            "(none)"
        } else {
            artifact.grpc_authority.as_str()
        },
        if artifact.grpc_schema.is_empty() {
            "(none)"
        } else {
            artifact.grpc_schema.as_str()
        },
        if artifact.grpc_request_id.is_empty() {
            "(none)"
        } else {
            artifact.grpc_request_id.as_str()
        },
        if artifact.grpc_action_kind.is_empty() {
            "(none)"
        } else {
            artifact.grpc_action_kind.as_str()
        },
        if artifact.grpc_action_objective.is_empty() {
            "(none)"
        } else {
            artifact.grpc_action_objective.as_str()
        },
        if artifact.grpc_action_skill.is_empty() {
            "(none)"
        } else {
            artifact.grpc_action_skill.as_str()
        },
        artifact
            .exit_code
            .map(|value| value.to_string())
            .unwrap_or_else(|| "(none)".to_string()),
    );
    if !artifact.grpc_physical_robot_id.is_empty()
        || !artifact.grpc_physical_target.is_empty()
        || !artifact.grpc_physical_command.is_empty()
        || !artifact.grpc_physical_safety_class.is_empty()
        || artifact.grpc_physical_dry_run.is_some()
    {
        output.push_str(&format!(
            "grpc_physical_robot_id: {}\ngrpc_physical_target: {}\ngrpc_physical_command: {}\ngrpc_physical_safety_class: {}\ngrpc_physical_dry_run: {}\n",
            if artifact.grpc_physical_robot_id.is_empty() {
                "(none)"
            } else {
                artifact.grpc_physical_robot_id.as_str()
            },
            if artifact.grpc_physical_target.is_empty() {
                "(none)"
            } else {
                artifact.grpc_physical_target.as_str()
            },
            if artifact.grpc_physical_command.is_empty() {
                "(none)"
            } else {
                artifact.grpc_physical_command.as_str()
            },
            if artifact.grpc_physical_safety_class.is_empty() {
                "(none)"
            } else {
                artifact.grpc_physical_safety_class.as_str()
            },
            artifact
                .grpc_physical_dry_run
                .map(|value| if value { "true" } else { "false" })
                .unwrap_or("(none)")
        ));
    }
    if !artifact.grpc_lifecycle_mode.is_empty()
        || artifact.grpc_lifecycle_ack_required.is_some()
        || artifact.grpc_lifecycle_ack_received.is_some()
        || artifact.grpc_lifecycle_cancelled.is_some()
        || !artifact.grpc_lifecycle_cancel_reason.is_empty()
        || !artifact.grpc_lifecycle_status.is_empty()
        || !artifact.grpc_remediation_profile.is_empty()
        || !artifact.grpc_remediation_action.is_empty()
    {
        output.push_str(&format!(
            "grpc_lifecycle_mode:         {}\ngrpc_lifecycle_ack_required: {}\ngrpc_lifecycle_ack_timeout_seconds: {}\ngrpc_lifecycle_ack_received: {}\ngrpc_lifecycle_ack_latency_ms: {}\ngrpc_lifecycle_cancel_on_ack_timeout: {}\ngrpc_lifecycle_cancel_after_seconds: {}\ngrpc_lifecycle_cancelled: {}\ngrpc_lifecycle_cancel_reason: {}\ngrpc_lifecycle_status: {}\ngrpc_lifecycle_stream_event_count: {}\ngrpc_remediation_profile: {}\ngrpc_remediation_action: {}\n",
            if artifact.grpc_lifecycle_mode.is_empty() {
                "(none)"
            } else {
                artifact.grpc_lifecycle_mode.as_str()
            },
            artifact
                .grpc_lifecycle_ack_required
                .map(|value| if value { "true" } else { "false" })
                .unwrap_or("(none)"),
            artifact
                .grpc_lifecycle_ack_timeout_seconds
                .map(|value| value.to_string())
                .unwrap_or_else(|| "(none)".to_string()),
            artifact
                .grpc_lifecycle_ack_received
                .map(|value| if value { "true" } else { "false" })
                .unwrap_or("(none)"),
            artifact
                .grpc_lifecycle_ack_latency_ms
                .map(|value| value.to_string())
                .unwrap_or_else(|| "(none)".to_string()),
            artifact
                .grpc_lifecycle_cancel_on_ack_timeout
                .map(|value| if value { "true" } else { "false" })
                .unwrap_or("(none)"),
            artifact
                .grpc_lifecycle_cancel_after_seconds
                .map(|value| value.to_string())
                .unwrap_or_else(|| "(none)".to_string()),
            artifact
                .grpc_lifecycle_cancelled
                .map(|value| if value { "true" } else { "false" })
                .unwrap_or("(none)"),
            if artifact.grpc_lifecycle_cancel_reason.is_empty() {
                "(none)"
            } else {
                artifact.grpc_lifecycle_cancel_reason.as_str()
            },
            if artifact.grpc_lifecycle_status.is_empty() {
                "(none)"
            } else {
                artifact.grpc_lifecycle_status.as_str()
            },
            artifact
                .grpc_lifecycle_stream_event_count
                .map(|value| value.to_string())
                .unwrap_or_else(|| "(none)".to_string()),
            if artifact.grpc_remediation_profile.is_empty() {
                "(none)"
            } else {
                artifact.grpc_remediation_profile.as_str()
            },
            if artifact.grpc_remediation_action.is_empty() {
                "(none)"
            } else {
                artifact.grpc_remediation_action.as_str()
            },
        ));
    }
    output
}

pub fn render_shadow_grpc_action_diagnostics_report(
    root: &Path,
    limit: usize,
) -> ShadowResult<String> {
    if limit == 0 {
        return Err("shadow grpc diagnostics report requires limit >= 1".to_string());
    }
    let latest_path = ensure_shadow_grpc_action_dir(root)?.join("latest.json");
    let stream_path = ensure_shadow_grpc_action_dir(root)?.join("stream.jsonl");
    let latest = load_grpc_action_diagnostics_artifact(&latest_path);
    let stream_contents = fs::read_to_string(&stream_path).ok();
    let mut recent = stream_contents
        .as_deref()
        .map(|contents| {
            contents
                .lines()
                .filter_map(|line| {
                    let trimmed = line.trim();
                    if trimmed.is_empty() {
                        return None;
                    }
                    let value: Value = serde_json::from_str(trimmed).ok()?;
                    Some(grpc_action_diagnostics_from_value(&value))
                })
                .filter(|entry| {
                    !entry.status.is_empty()
                        || !entry.grpc_target.is_empty()
                        || !entry.grpc_rpc.is_empty()
                })
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    if recent.len() > limit {
        recent = recent.split_off(recent.len() - limit);
    }
    let mut out = String::from(
        "Meridian Loom // SHADOW GRPC DIAGNOSTICS\n========================================\nphase:       typed grpc diagnostics operator surface\nboundary:    shows persisted grpc_action transport diagnostics only\n",
    );
    if latest.is_none() && recent.is_empty() {
        out.push_str(&format!(
            "\nCurrent state\n=============\nstatus:      not_started\nmeaning:     no grpc_action diagnostics artifacts captured yet\nsource:      {}\n\nRecommended next step\n=====================\n1. loom shadow run --backend grpc_action --root {} --kernel-path /opt/meridian-kernel --agent-id agent_atlas --warrant-file ./shadow-warrant.json --url grpc://grpcb.in:9000 --grpc-service grpcbin.GRPCBin --grpc-method DummyUnary --format human\n2. loom shadow grpc-diagnostics --root {} --limit {}\n",
            latest_path.display(),
            root.display(),
            root.display(),
            limit,
        ));
        return Ok(out);
    }
    if let Some(latest) = latest.as_ref() {
        out.push_str(&render_grpc_action_diagnostics_summary(
            &latest_path,
            latest,
        ));
    } else {
        out.push_str(&format!(
            "\nGrpc action diagnostics latest\n==============================\nsource: {}\nstatus:                  missing\n",
            latest_path.display(),
        ));
    }
    out.push_str(&format!(
        "\nGrpc action diagnostics recent\n==============================\nsource: typed grpc diagnostics stream @ {}\nlimit: {}\ncount: {}\n",
        stream_path.display(),
        limit,
        recent.len(),
    ));
    if recent.is_empty() {
        out.push_str("status:                  no_stream_entries\n");
    } else {
        for (index, entry) in recent.iter().enumerate() {
            out.push_str(&format!(
                "entry[{index}]: captured_at={} status={} rpc={} target={} transport={} exit={}\n",
                if entry.captured_at.is_empty() {
                    "(none)"
                } else {
                    entry.captured_at.as_str()
                },
                if entry.status.is_empty() {
                    "(none)"
                } else {
                    entry.status.as_str()
                },
                if entry.grpc_rpc.is_empty() {
                    "(none)"
                } else {
                    entry.grpc_rpc.as_str()
                },
                if entry.grpc_target.is_empty() {
                    "(none)"
                } else {
                    entry.grpc_target.as_str()
                },
                if entry.grpc_transport.is_empty() {
                    "(none)"
                } else {
                    entry.grpc_transport.as_str()
                },
                entry
                    .exit_code
                    .map(|value| value.to_string())
                    .unwrap_or_else(|| "(none)".to_string()),
            ));
        }
    }
    Ok(out)
}

pub fn render_shadow_grpc_action_diagnostics_json(
    root: &Path,
    limit: usize,
) -> ShadowResult<String> {
    if limit == 0 {
        return Err("shadow grpc diagnostics json requires limit >= 1".to_string());
    }
    let latest_path = ensure_shadow_grpc_action_dir(root)?.join("latest.json");
    let stream_path = ensure_shadow_grpc_action_dir(root)?.join("stream.jsonl");
    let latest = load_grpc_action_diagnostics_artifact(&latest_path);
    let stream_contents = fs::read_to_string(&stream_path).ok();
    let mut recent = stream_contents
        .as_deref()
        .map(|contents| {
            contents
                .lines()
                .filter_map(|line| {
                    let trimmed = line.trim();
                    if trimmed.is_empty() {
                        return None;
                    }
                    let value = serde_json::from_str::<Value>(trimmed).ok()?;
                    Some(grpc_action_diagnostics_from_value(&value))
                })
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    if recent.len() > limit {
        recent = recent.split_off(recent.len() - limit);
    }
    let payload = serde_json::json!({
        "status": if latest.is_some() || !recent.is_empty() { "ok" } else { "not_started" },
        "latest_path": latest_path.display().to_string(),
        "stream_path": stream_path.display().to_string(),
        "limit": limit,
        "latest": latest.as_ref().map(grpc_action_diagnostics_to_value),
        "recent": recent
            .iter()
            .map(grpc_action_diagnostics_to_value)
            .collect::<Vec<_>>(),
    });
    serde_json::to_string_pretty(&payload).map_err(io_err)
}

pub fn render_parity_report(root: &Path) -> ShadowResult<String> {
    let parity_dir = ensure_parity_dir(root)?;
    let report_path = parity_dir.join("latest.json");
    let contents = fs::read_to_string(&report_path).ok();
    let parity_capture = load_shadow_run_capture(&report_path);
    let stream_path = parity_dir.join("stream.jsonl");
    let stream = fs::read_to_string(&stream_path).ok();
    let reference_latest_path = parity_dir.join("reference_latest.json");
    let reference_latest = fs::read_to_string(&reference_latest_path).ok();
    let reference_stream_path = parity_dir.join("reference_stream.jsonl");
    let reference_stream = fs::read_to_string(&reference_stream_path).ok();
    let comparison_latest_path = parity_dir.join("comparison_latest.json");
    let comparison_latest = fs::read_to_string(&comparison_latest_path).ok();
    let comparison_stream_path = parity_dir.join("comparison_stream.jsonl");
    let comparison_stream = fs::read_to_string(&comparison_stream_path).ok();
    let event_latest_path = runtime_event_latest_path(root)?;
    let event_latest = fs::read_to_string(&event_latest_path).ok();
    let event_stream_path = runtime_event_stream_path(root)?;
    let event_stream = fs::read_to_string(&event_stream_path).ok();
    let reference_probe_path = parity_dir.join("reference_probe.json");
    let reference_probe = fs::read_to_string(&reference_probe_path).ok();
    let reference_probe_stream_path = parity_dir.join("reference_probe_stream.jsonl");
    let reference_probe_stream = fs::read_to_string(&reference_probe_stream_path).ok();
    let zk_latest_path = artifact_root(root)?.join("zk").join("latest.json");
    let zk_latest = fs::read_to_string(&zk_latest_path).ok();
    let zk_artifact = load_zk_proof_artifact(&zk_latest_path);
    let settlement_latest_path = artifact_root(root)?.join("settlement").join("latest.json");
    let settlement_latest = fs::read_to_string(&settlement_latest_path).ok();
    let settlement_artifact = load_settlement_artifact(&settlement_latest_path);
    let grpc_diagnostics_latest_path = ensure_shadow_grpc_action_dir(root)?.join("latest.json");
    let grpc_diagnostics_latest = fs::read_to_string(&grpc_diagnostics_latest_path).ok();
    let grpc_diagnostics_artifact =
        load_grpc_action_diagnostics_artifact(&grpc_diagnostics_latest_path);
    if contents.is_none()
        && stream.is_none()
        && reference_latest.is_none()
        && reference_stream.is_none()
        && comparison_latest.is_none()
        && comparison_stream.is_none()
        && event_latest.is_none()
        && event_stream.is_none()
        && reference_probe.is_none()
        && reference_probe_stream.is_none()
        && zk_latest.is_none()
        && settlement_latest.is_none()
        && grpc_diagnostics_latest.is_none()
    {
        return Ok(format!(
            "Meridian Loom // PARITY REPORT\n===============================\nphase:       runtime-side parity surface\nboundary:    parity artifacts appear only after runtime rehearsal\n\nCurrent state\n=============\nstatus:      not_started\nmeaning:     no parity stream, parity report, or live reference probe has been captured yet\n\nRecommended next step\n=====================\n1. loom action execute --agent-id agent_atlas --action-type research --resource web_search --kernel-path /opt/meridian-kernel --root {}\n2. loom shadow report --root {}\n3. Re-run loom parity report after runtime rehearsal artifacts exist.\n",
            root.display(),
            root.display(),
        ));
    }
    let parity_latest_section = parity_capture
        .as_ref()
        .map(|capture| render_shadow_run_summary("Parity latest", &report_path, capture))
        .unwrap_or_else(|| {
            format!(
                "Parity latest\n=============\nsource: {}\n\n{}\n",
                report_path.display(),
                contents.unwrap_or_else(|| {
                    "{\n  \"status\": \"missing\",\n  \"note\": \"latest parity report has not been captured yet\"\n}\n"
                        .to_string()
                })
            )
        });
    let mut out = format!(
        "Meridian Loom // PARITY REPORT\n===============================\nphase:       runtime-side parity surface\nboundary:    action-level parity now compares Loom runtime events to the reference adapter; live host probe remains supplementary\n{}\nParity stream\n=============\nsource: {}\n\n{}\n",
        parity_latest_section,
        stream_path.display(),
        stream.unwrap_or_else(|| "# parity stream not captured yet\n".to_string()),
    );

    out.push_str(
        &reference_latest
            .as_ref()
            .map(|contents| {
                format!(
                    "Reference action latest\n=======================\nsource: {}\n\n{}\n",
                    reference_latest_path.display(),
                    contents
                )
            })
            .unwrap_or_else(|| {
                "Reference action latest\n=======================\nsource: (not captured)\n\n"
                    .to_string()
            }),
    );
    out.push_str(
        &reference_stream
            .as_ref()
            .map(|contents| {
                format!(
                    "Reference action stream\n=======================\nsource: {}\n\n{}\n",
                    reference_stream_path.display(),
                    contents
                )
            })
            .unwrap_or_else(|| {
                "Reference action stream\n=======================\nsource: (not captured)\n\n"
                    .to_string()
            }),
    );
    out.push_str(
        &comparison_latest
            .as_ref()
            .map(|contents| {
                format!(
                    "Action parity latest\n====================\nsource: {}\n\n{}\n",
                    comparison_latest_path.display(),
                    contents
                )
            })
            .unwrap_or_else(|| {
                "Action parity latest\n====================\nsource: (not captured)\n\n".to_string()
            }),
    );
    out.push_str(
        &comparison_stream
            .as_ref()
            .map(|contents| {
                format!(
                    "Action parity stream\n====================\nsource: {}\n\n{}\n",
                    comparison_stream_path.display(),
                    contents
                )
            })
            .unwrap_or_else(|| {
                "Action parity stream\n====================\nsource: (not captured)\n\n".to_string()
            }),
    );
    out.push_str(&render_action_parity_summary(
        event_latest.as_deref(),
        reference_latest.as_deref(),
        reference_probe.as_deref(),
    ));
    out.push('\n');
    out.push_str(
        &event_latest
            .as_ref()
            .map(|contents| {
                format!(
                    "Runtime event latest\n====================\nsource: {}\n\n{}\n",
                    event_latest_path.display(),
                    contents
                )
            })
            .unwrap_or_else(|| {
                "Runtime event latest\n====================\nsource: (not captured)\n\n".to_string()
            }),
    );
    out.push_str(
        &event_stream
            .as_ref()
            .map(|contents| {
                format!(
                    "Runtime event stream\n====================\nsource: {}\n\n{}\n",
                    event_stream_path.display(),
                    contents
                )
            })
            .unwrap_or_else(|| {
                "Runtime event stream\n====================\nsource: (not captured)\n\n".to_string()
            }),
    );
    out.push_str(
        &reference_probe
            .as_ref()
            .map(|contents| {
                format!(
                    "Reference probe\n===================\nsource: {}\n\n{}\n",
                    reference_probe_path.display(),
                    contents
                )
            })
            .unwrap_or_else(|| {
                "Reference probe\n===================\nsource: (not captured)\n\n".to_string()
            }),
    );
    out.push_str(
        &reference_probe_stream
            .as_ref()
            .map(|contents| {
                format!(
                    "Reference probe stream\n==========================\nsource: {}\n\n{}\n",
                    reference_probe_stream_path.display(),
                    contents
                )
            })
            .unwrap_or_else(|| {
                "Reference probe stream\n==========================\nsource: (not captured)\n\n"
                    .to_string()
            }),
    );
    out.push_str(
        &zk_artifact
            .as_ref()
            .map(|artifact| render_zk_proof_summary(&zk_latest_path, artifact))
            .or_else(|| {
                zk_latest.as_ref().map(|contents| {
                    format!(
                        "ZK proof latest\n===============\nsource: {}\n\n{}\n",
                        zk_latest_path.display(),
                        contents
                    )
                })
            })
            .unwrap_or_else(|| {
                "ZK proof latest\n===============\nsource: (not captured)\n\n".to_string()
            }),
    );
    out.push_str(
        &settlement_artifact
            .as_ref()
            .map(|artifact| render_settlement_summary(&settlement_latest_path, artifact))
            .or_else(|| {
                settlement_latest.as_ref().map(|contents| {
                    format!(
                        "Settlement latest\n=================\nsource: {}\n\n{}\n",
                        settlement_latest_path.display(),
                        contents
                    )
                })
            })
            .unwrap_or_else(|| {
                "Settlement latest\n=================\nsource: (not captured)\n\n".to_string()
            }),
    );
    out.push_str(
        &grpc_diagnostics_artifact
            .as_ref()
            .map(|artifact| {
                render_grpc_action_diagnostics_summary(&grpc_diagnostics_latest_path, artifact)
            })
            .or_else(|| {
                parity_capture
                    .as_ref()
                    .and_then(load_grpc_action_diagnostics)
                    .map(|artifact| render_grpc_action_diagnostics_summary(&report_path, &artifact))
            })
            .or_else(|| {
                grpc_diagnostics_latest.as_ref().map(|contents| {
                    format!(
                        "Grpc action diagnostics latest\n==============================\nsource: {}\n\n{}\n",
                        grpc_diagnostics_latest_path.display(),
                        contents
                    )
                })
            })
            .unwrap_or_else(|| {
                "Grpc action diagnostics latest\n==============================\nsource: (not captured)\n\n"
                    .to_string()
            }),
    );

    Ok(out)
}

fn render_action_parity_summary(
    runtime_event: Option<&str>,
    reference_latest: Option<&str>,
    reference_probe: Option<&str>,
) -> String {
    let mut out = String::from("Action parity summary\n=====================\n");
    let Some(reference_latest) = reference_latest else {
        out.push_str("status:      not_started\nmeaning:     no action-level reference artifact has been captured yet\n\n");
        return out;
    };

    let reference_decision = extract_json_bool(reference_latest, "\"reference_allowed\"")
        .map(|allowed| if allowed { "allow" } else { "deny" }.to_string())
        .or_else(|| extract_json_string(reference_latest, "\"reference_decision\""))
        .unwrap_or_else(|| "unknown".to_string());
    let reference_stage = extract_json_string(reference_latest, "\"reference_stage\"")
        .unwrap_or_else(|| "unknown".to_string());
    let action_type = extract_json_string(reference_latest, "\"action_type\"")
        .unwrap_or_else(|| "unknown".to_string());
    let resource = extract_json_string(reference_latest, "\"resource\"")
        .unwrap_or_else(|| "unknown".to_string());

    let runtime_status = if let Some(runtime_event) = runtime_event {
        let runtime_outcome = extract_json_string(runtime_event, "\"outcome\"")
            .unwrap_or_else(|| "unknown".to_string());
        let runtime_stage = extract_json_string(runtime_event, "\"stage\"")
            .unwrap_or_else(|| "unknown".to_string());
        let runtime_decision = if runtime_outcome == "worker_executed" {
            "allow".to_string()
        } else {
            "deny".to_string()
        };
        let status = if runtime_decision == reference_decision {
            "match"
        } else {
            "divergence"
        };
        out.push_str(&format!(
            "status:      {}\nexpected:    {} via {}\nactual:      {} via {}\naction_type: {}\nresource:    {}\n",
            status, reference_decision, reference_stage, runtime_decision, runtime_stage, action_type, resource
        ));
        status.to_string()
    } else {
        out.push_str(&format!(
            "status:      pending_runtime_event\nexpected:    {} via {}\naction_type: {}\nresource:    {}\n",
            reference_decision, reference_stage, action_type, resource
        ));
        "pending_runtime_event".to_string()
    };

    if let Some(reference_probe) = reference_probe {
        let proof_level = extract_json_string(reference_probe, "\"proof_level\"")
            .unwrap_or_else(|| "unknown".to_string());
        let deployment_mode = extract_json_string(reference_probe, "\"deployment_mode\"")
            .unwrap_or_else(|| "unknown".to_string());
        let health_ok = extract_json_bool(reference_probe, "\"health_ok\"").unwrap_or(false);
        out.push_str(&format!(
            "live_probe:  {} (proof_level={} deployment_mode={})\n",
            if health_ok { "healthy" } else { "degraded" },
            proof_level,
            deployment_mode
        ));
    } else {
        out.push_str("live_probe:  not_captured\n");
    }
    out.push_str(&format!(
        "note:        action-level parity is {} against the reference adapter; live reference probe remains supplementary\n\n",
        runtime_status
    ));
    out
}

fn render_parity_report_json(capture: &RuntimeExecutionCapture) -> String {
    format!(
        "{{\n  \"status\": \"parity_report_captured\",\n  \"execution_path\": {},\n  \"runtime_event_path\": {},\n  \"runtime_event_stream_path\": {},\n  \"decision_path\": {},\n  \"audit_log_path\": {},\n  \"parity_stream_path\": {},\n  \"comparison_latest_path\": {},\n  \"comparison_stream_path\": {},\n  \"reference_probe_path\": {},\n  \"reference_probe_stream_path\": {},\n  \"reference_decision\": {},\n  \"reference_stage\": {},\n  \"overall_decision\": {},\n  \"effective_stage\": {},\n  \"reference_probe_status\": {},\n  \"reference_probe_note\": {},\n  \"parity_status\": {},\n  \"parity_reason\": {},\n  \"note\": \"runtime-side parity stream now captures Loom execution plus a per-action Reference probe artifact when available; hosted per-action parity remains future work\"\n}}\n",
        json_string(&capture.execution_path.display().to_string()),
        json_string(&capture.runtime_event_path.display().to_string()),
        json_string(&capture.runtime_event_stream_path.display().to_string()),
        json_string(&capture.decision_path.display().to_string()),
        json_string(&capture.audit_log_path.display().to_string()),
        json_string(&capture.parity_stream_path.display().to_string()),
        json_string("artifacts/parity/comparison_latest.json"),
        json_string("artifacts/parity/comparison_stream.jsonl"),
        capture
            .reference_probe_path
            .as_ref()
            .map(|path| json_string(&path.display().to_string()))
            .unwrap_or_else(|| "null".to_string()),
        capture
            .reference_probe_stream_path
            .as_ref()
            .map(|path| json_string(&path.display().to_string()))
            .unwrap_or_else(|| "null".to_string()),
        json_string(&capture.reference_decision),
        json_string(&capture.reference_stage),
        json_string(&capture.overall_decision),
        json_string(&capture.effective_stage),
        json_string(&capture.reference_probe_status),
        json_string(&capture.reference_probe_note),
        json_string(&capture.parity_status),
        json_string(&capture.parity_reason),
    )
}

fn ensure_shadow_dir(root: &Path) -> ShadowResult<PathBuf> {
    let shadow_dir = artifact_root(root)?.join("shadow");
    ensure_private_dir(&shadow_dir)?;
    Ok(shadow_dir)
}

fn ensure_shadow_grpc_action_dir(root: &Path) -> ShadowResult<PathBuf> {
    let diagnostics_dir = ensure_shadow_dir(root)?.join("grpc_action");
    ensure_private_dir(&diagnostics_dir)?;
    Ok(diagnostics_dir)
}

fn ensure_runtime_dir(root: &Path) -> ShadowResult<PathBuf> {
    let runtime_dir = state_root(root)?.join("runtime");
    ensure_private_dir(&runtime_dir)?;
    Ok(runtime_dir)
}

fn ensure_runtime_jobs_dir(root: &Path) -> ShadowResult<PathBuf> {
    let jobs_dir = ensure_runtime_dir(root)?.join("jobs");
    ensure_private_dir(&jobs_dir)?;
    Ok(jobs_dir)
}

fn ensure_runtime_events_dir(root: &Path) -> ShadowResult<PathBuf> {
    let events_dir = artifact_root(root)?.join("runtime").join("events");
    ensure_private_dir(&events_dir)?;
    Ok(events_dir)
}

fn ensure_runtime_scheduler_dir(root: &Path) -> ShadowResult<PathBuf> {
    let scheduler_dir = ensure_runtime_dir(root)?.join("scheduler");
    ensure_private_dir(&scheduler_dir)?;
    Ok(scheduler_dir)
}

fn ensure_runtime_service_dir(root: &Path) -> ShadowResult<PathBuf> {
    let service_dir = run_root(root)?.join("service");
    ensure_private_dir(&service_dir)?;
    Ok(service_dir)
}

fn ensure_runtime_ingress_dir(root: &Path) -> ShadowResult<PathBuf> {
    let ingress_dir = run_root(root)?.join("ingress");
    ensure_private_dir(&ingress_dir)?;
    ensure_private_dir(&ingress_dir.join("requests"))?;
    ensure_private_dir(&ingress_dir.join("receipts"))?;
    Ok(ingress_dir)
}

fn ensure_runtime_imports_dir(root: &Path) -> ShadowResult<PathBuf> {
    let imports_dir = ensure_runtime_dir(root)?.join("imports");
    ensure_private_dir(&imports_dir)?;
    Ok(imports_dir)
}

fn ensure_audit_dir(root: &Path) -> ShadowResult<PathBuf> {
    let audit_dir = artifact_root(root)?.join("audit");
    ensure_private_dir(&audit_dir)?;
    Ok(audit_dir)
}

fn runtime_event_path(root: &Path, input_hash: &str) -> ShadowResult<PathBuf> {
    Ok(ensure_runtime_events_dir(root)?.join(format!("{}.json", input_hash)))
}

fn runtime_event_latest_path(root: &Path) -> ShadowResult<PathBuf> {
    Ok(ensure_runtime_events_dir(root)?.join("latest.json"))
}

fn runtime_event_stream_path(root: &Path) -> ShadowResult<PathBuf> {
    Ok(ensure_runtime_events_dir(root)?.join("stream.jsonl"))
}

fn runtime_audit_log_path(root: &Path, override_kernel_path: Option<&str>) -> PathBuf {
    if let Ok(override_path) = std::env::var("MERIDIAN_RUNTIME_AUDIT_FILE") {
        let trimmed = override_path.trim();
        if !trimmed.is_empty() {
            return PathBuf::from(trimmed);
        }
    }
    match kernel_path_for(root, override_kernel_path) {
        Ok(kernel_path) => kernel_path
            .join("kernel")
            .join("runtime_audit")
            .join("loom_runtime_events.jsonl"),
        Err(_) => ensure_audit_dir(root)
            .unwrap_or_else(|_| root.join("artifacts").join("audit"))
            .join("loom_runtime_events.jsonl"),
    }
}

fn service_socket_path(root: &Path, socket_override: Option<&str>) -> ShadowResult<PathBuf> {
    if let Some(raw) = socket_override {
        let path = PathBuf::from(raw);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(io_err)?;
        }
        return Ok(path);
    }
    let preferred = ensure_runtime_service_dir(root)?.join("runtime.sock");
    if preferred.as_os_str().len() < 96 {
        return Ok(preferred);
    }
    let root_token = sanitize_filename(&root.display().to_string());
    let suffix = if root_token.len() > 32 {
        &root_token[root_token.len() - 32..]
    } else {
        root_token.as_str()
    };
    Ok(std::env::temp_dir().join(format!("meridian-loom-{}.sock", suffix)))
}

fn runtime_service_state_path(root: &Path) -> ShadowResult<PathBuf> {
    Ok(ensure_runtime_service_dir(root)?.join("runtime_state.json"))
}

fn service_lock_path(root: &Path) -> ShadowResult<PathBuf> {
    Ok(ensure_runtime_service_dir(root)?.join("service.lock"))
}

fn service_metrics_path(root: &Path) -> ShadowResult<PathBuf> {
    Ok(ensure_runtime_service_dir(root)?.join("metrics.json"))
}

fn service_stop_request_path(root: &Path) -> ShadowResult<PathBuf> {
    Ok(ensure_runtime_service_dir(root)?.join("stop.requested"))
}

fn service_stdout_log_path(root: &Path) -> ShadowResult<PathBuf> {
    let log_dir = log_root(root)?;
    fs::create_dir_all(&log_dir).map_err(io_err)?;
    Ok(log_dir.join("service.log"))
}

fn runtime_service_event_log_path(root: &Path) -> ShadowResult<PathBuf> {
    let log_dir = log_root(root)?;
    fs::create_dir_all(&log_dir).map_err(io_err)?;
    Ok(log_dir.join("service_events.jsonl"))
}

fn runtime_ingress_stream_path(root: &Path) -> ShadowResult<PathBuf> {
    Ok(ensure_runtime_ingress_dir(root)?.join("stream.jsonl"))
}

fn runtime_ingress_request_path(root: &Path, request_id: &str) -> ShadowResult<PathBuf> {
    Ok(ensure_runtime_ingress_dir(root)?
        .join("requests")
        .join(format!("{}.json", sanitize_filename(request_id))))
}

fn runtime_ingress_receipt_path(root: &Path, request_id: &str) -> ShadowResult<PathBuf> {
    Ok(ensure_runtime_ingress_dir(root)?
        .join("receipts")
        .join(format!("{}.json", sanitize_filename(request_id))))
}

fn write_supervisor_runtime_state(
    runtime_state_path: &Path,
    session_id: &str,
    pid: u32,
    running: bool,
    status: &str,
    booted_at: &str,
    stopped_at: &str,
    poll_seconds: u64,
    max_jobs: usize,
    max_iterations: usize,
    iterations_completed: usize,
    processed: usize,
    allowed: usize,
    denied: usize,
    failed: usize,
    pending_jobs: usize,
    processed_jobs: usize,
    failed_jobs: usize,
    note: String,
) -> ShadowResult<()> {
    fs::write(
        runtime_state_path,
        format!(
            "{{\n  \"status\": {},\n  \"updated_at\": {},\n  \"session_id\": {},\n  \"pid\": {},\n  \"running\": {},\n  \"booted_at\": {},\n  \"stopped_at\": {},\n  \"poll_seconds\": {},\n  \"max_jobs\": {},\n  \"max_iterations\": {},\n  \"iterations_completed\": {},\n  \"processed\": {},\n  \"allowed\": {},\n  \"denied\": {},\n  \"failed\": {},\n  \"pending_jobs\": {},\n  \"processed_jobs\": {},\n  \"failed_jobs\": {},\n  \"note\": {}\n}}\n",
            json_string(status),
            json_string(&timestamp_now()),
            json_string(session_id),
            pid,
            if running { "true" } else { "false" },
            json_string(booted_at),
            json_string(stopped_at),
            poll_seconds,
            max_jobs,
            max_iterations,
            iterations_completed,
            processed,
            allowed,
            denied,
            failed,
            pending_jobs,
            processed_jobs,
            failed_jobs,
            json_string(&note),
        ),
    )
    .map_err(io_err)?;
    ensure_private_file(runtime_state_path)?;
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn write_runtime_service_state(
    runtime_state_path: &Path,
    metrics_path: &Path,
    socket_path: &Path,
    http_address: Option<&str>,
    http_token_required: bool,
    session_id: &str,
    pid: u32,
    running: bool,
    status: &str,
    booted_at: &str,
    stopped_at: &str,
    poll_seconds: u64,
    max_jobs: usize,
    max_iterations: usize,
    iterations_completed: usize,
    requests_received: usize,
    submitted: usize,
    processed: usize,
    allowed: usize,
    denied: usize,
    failed: usize,
    pending_jobs: usize,
    processed_jobs: usize,
    failed_jobs: usize,
    last_request_id: &str,
    last_job_id: &str,
    note: String,
) -> ShadowResult<()> {
    let updated_at = timestamp_now();
    let http_address_json = http_address
        .map(json_string)
        .unwrap_or_else(|| "null".to_string());
    let state_json = format!(
        "{{\n  \"status\": {},\n  \"updated_at\": {},\n  \"session_id\": {},\n  \"pid\": {},\n  \"running\": {},\n  \"socket_path\": {},\n  \"http_address\": {},\n  \"http_token_required\": {},\n  \"booted_at\": {},\n  \"stopped_at\": {},\n  \"poll_seconds\": {},\n  \"max_jobs\": {},\n  \"max_iterations\": {},\n  \"iterations_completed\": {},\n  \"requests_received\": {},\n  \"submitted\": {},\n  \"processed\": {},\n  \"allowed\": {},\n  \"denied\": {},\n  \"failed\": {},\n  \"pending_jobs\": {},\n  \"processed_jobs\": {},\n  \"failed_jobs\": {},\n  \"last_request_id\": {},\n  \"last_job_id\": {},\n  \"note\": {}\n}}\n",
        json_string(status),
        json_string(&updated_at),
        json_string(session_id),
        pid,
        if running { "true" } else { "false" },
        json_string(&socket_path.display().to_string()),
        http_address_json,
        if http_token_required { "true" } else { "false" },
        json_string(booted_at),
        json_string(stopped_at),
        poll_seconds,
        max_jobs,
        max_iterations,
        iterations_completed,
        requests_received,
        submitted,
        processed,
        allowed,
        denied,
        failed,
        pending_jobs,
        processed_jobs,
        failed_jobs,
        json_string(last_request_id),
        json_string(last_job_id),
        json_string(&note),
    );
    fs::write(runtime_state_path, &state_json).map_err(io_err)?;
    fs::write(
        metrics_path,
        format!(
            "{{\n  \"status\": {},\n  \"updated_at\": {},\n  \"uptime_seconds\": {},\n  \"requests_received\": {},\n  \"jobs_submitted\": {},\n  \"jobs_processed\": {},\n  \"jobs_allowed\": {},\n  \"jobs_denied\": {},\n  \"jobs_failed\": {},\n  \"queue_depth\": {},\n  \"processed_jobs\": {},\n  \"failed_jobs\": {},\n  \"last_request_id\": {},\n  \"last_job_id\": {}\n}}\n",
            json_string(status),
            json_string(&updated_at),
            runtime_uptime_seconds(booted_at, &updated_at),
            requests_received,
            submitted,
            processed,
            allowed,
            denied,
            failed,
            pending_jobs,
            processed_jobs,
            failed_jobs,
            json_string(last_request_id),
            json_string(last_job_id),
        ),
    )
    .map_err(io_err)
}

fn count_runtime_queue_entries(root: &Path, bucket: &str) -> ShadowResult<usize> {
    let path = ensure_runtime_dir(root)?.join("queue").join(bucket);
    if !path.exists() {
        return Ok(0);
    }
    count_json_files_recursive(&path)
}

fn count_json_files_recursive(path: &Path) -> ShadowResult<usize> {
    let mut count = 0usize;
    for entry in fs::read_dir(path).map_err(io_err)? {
        let entry = entry.map_err(io_err)?;
        let entry_path = entry.path();
        if entry_path.is_dir() {
            count += count_json_files_recursive(&entry_path)?;
        } else if entry_path
            .extension()
            .map(|ext| ext == "json")
            .unwrap_or(false)
        {
            count += 1;
        }
    }
    Ok(count)
}

fn scheduler_state_path(root: &Path) -> ShadowResult<PathBuf> {
    Ok(ensure_runtime_scheduler_dir(root)?.join("state.json"))
}

fn reservation_ledger_path(root: &Path) -> ShadowResult<PathBuf> {
    Ok(ensure_runtime_scheduler_dir(root)?.join("reservations.json"))
}

fn load_scheduler_state_or_default(root: &Path) -> ShadowResult<SchedulerState> {
    let path = scheduler_state_path(root)?;
    if path.exists() {
        load_scheduler_state(&path)
            .map_err(|error| format!("failed to load scheduler state: {}", error))
    } else {
        Ok(SchedulerState::new())
    }
}

fn save_scheduler_state_checked(root: &Path, state: &SchedulerState) -> ShadowResult<()> {
    let path = scheduler_state_path(root)?;
    save_scheduler_state(state, &path)
        .map_err(|error| format!("failed to save scheduler state: {}", error))
}

fn load_reservation_ledger_or_default(root: &Path) -> ShadowResult<ReservationLedger> {
    let path = reservation_ledger_path(root)?;
    if path.exists() {
        load_ledger(&path).map_err(|error| format!("failed to load reservation ledger: {}", error))
    } else {
        Ok(ReservationLedger::new())
    }
}

fn save_reservation_ledger_checked(root: &Path, ledger: &ReservationLedger) -> ShadowResult<()> {
    let path = reservation_ledger_path(root)?;
    save_ledger(ledger, &path)
        .map_err(|error| format!("failed to save reservation ledger: {}", error))
}

fn pending_queue_dir(root: &Path, class: PolicyClass) -> ShadowResult<PathBuf> {
    let path = ensure_runtime_dir(root)?
        .join("queue")
        .join("pending")
        .join(class.label());
    fs::create_dir_all(&path).map_err(io_err)?;
    Ok(path)
}

fn collect_pending_queue_paths(root: &Path) -> ShadowResult<Vec<(PolicyClass, PathBuf)>> {
    let queue_root = ensure_runtime_dir(root)?.join("queue").join("pending");
    fs::create_dir_all(&queue_root).map_err(io_err)?;
    let mut pending = Vec::new();
    for class in PolicyClass::all() {
        let class_dir = queue_root.join(class.label());
        if class_dir.exists() {
            let mut class_entries = fs::read_dir(&class_dir)
                .map_err(io_err)?
                .filter_map(|entry| entry.ok().map(|item| item.path()))
                .filter(|path| path.extension().map(|ext| ext == "json").unwrap_or(false))
                .collect::<Vec<_>>();
            class_entries.sort();
            pending.extend(class_entries.into_iter().map(|path| (*class, path)));
        }
    }
    let mut legacy_entries = fs::read_dir(&queue_root)
        .map_err(io_err)?
        .filter_map(|entry| entry.ok().map(|item| item.path()))
        .filter(|path| path.is_file() && path.extension().map(|ext| ext == "json").unwrap_or(false))
        .collect::<Vec<_>>();
    legacy_entries.sort();
    pending.extend(
        legacy_entries
            .into_iter()
            .map(|path| (PolicyClass::Standard, path)),
    );
    Ok(pending)
}

fn queue_acks_dir(root: &Path) -> ShadowResult<PathBuf> {
    let path = ensure_runtime_dir(root)?.join("queue").join("acks");
    fs::create_dir_all(&path).map_err(io_err)?;
    Ok(path)
}

fn queue_runs_dir(root: &Path) -> ShadowResult<PathBuf> {
    let path = ensure_runtime_dir(root)?.join("queue").join("runs");
    fs::create_dir_all(&path).map_err(io_err)?;
    Ok(path)
}

fn queue_ack_path(root: &Path, job_id: &str) -> ShadowResult<PathBuf> {
    Ok(queue_acks_dir(root)?.join(format!("{}.json", sanitize_filename(job_id))))
}

fn count_queue_ack_entries(root: &Path) -> ShadowResult<usize> {
    let path = queue_acks_dir(root)?;
    if !path.exists() {
        return Ok(0);
    }
    count_json_files_recursive(&path)
}

fn load_queue_record_snapshot(
    root: &Path,
    policy_class: PolicyClass,
    queue_path: &Path,
) -> ShadowResult<QueueRecordSnapshot> {
    let contents = fs::read_to_string(queue_path).map_err(io_err)?;
    let queue_body = serde_json::from_str::<Value>(&contents).unwrap_or(Value::Null);
    let job_id = value_string(queue_body.get("input_hash"));
    let job_id = if job_id.is_empty() {
        extract_json_string(&contents, "\"input_hash\"")
            .ok_or_else(|| format!("input_hash missing in {}", queue_path.display()))?
    } else {
        job_id
    };
    let job_path = job_snapshot_path(root, &job_id);
    let ack_path = queue_ack_path(root, &job_id)?;
    let job_snapshot = read_job_snapshot(root, &job_id).ok();
    let acknowledged = ack_path.exists();
    let (job_status, job_stage, note) = match job_snapshot {
        Some(snapshot) => (
            snapshot.status,
            snapshot.stage,
            if ack_path.exists() {
                format!("{}; local queue ack present", snapshot.note)
            } else {
                snapshot.note
            },
        ),
        None => (
            "(not captured)".to_string(),
            "(not captured)".to_string(),
            if ack_path.exists() {
                "local queue ack present, but no job snapshot was captured".to_string()
            } else {
                "pending local supervisor consume".to_string()
            },
        ),
    };
    Ok(QueueRecordSnapshot {
        root: root.to_path_buf(),
        queue_path: queue_path.to_path_buf(),
        ack_path,
        job_path,
        job_id,
        queue_bucket: format!("pending:{}", policy_class.label()),
        policy_class: policy_class.label().to_string(),
        status: value_string(queue_body.get("status")),
        queued_at: value_string(queue_body.get("queued_at")),
        agent_id: value_string(queue_body.get("agent_id")),
        org_id: value_string(queue_body.get("org_id")),
        action_type: value_string(queue_body.get("action_type")),
        resource: value_string(queue_body.get("resource")),
        estimated_cost_usd: if let Some(value) =
            queue_body.get("estimated_cost_usd").and_then(Value::as_f64)
        {
            format!("{:.6}", value)
        } else {
            extract_json_number(&contents, "\"estimated_cost_usd\"")
                .map(|value| format!("{:.6}", value))
                .unwrap_or_else(|| "0.000000".to_string())
        },
        run_id: value_string(queue_body.get("run_id")),
        session_id: value_string(queue_body.get("session_id")),
        kernel_path: value_string(queue_body.get("kernel_path")),
        job_status,
        job_stage,
        acknowledged,
        note,
    })
}

fn write_queue_ack_record(
    root: &Path,
    snapshot: &JobSnapshot,
    acknowledged_by: &str,
    queue_path: Option<&Path>,
) -> ShadowResult<QueueAckCapture> {
    let ack_path = queue_ack_path(root, &snapshot.job_id)?;
    let acknowledged_at = timestamp_now();
    let rendered = format!(
        r#"{{
  "status": "acked",
  "job_id": {},
  "job_path": {},
  "queue_path": {},
  "ack_path": {},
  "queue_bucket": {},
  "job_status": {},
  "job_stage": {},
  "acknowledged_at": {},
  "acknowledged_by": {},
  "note": {}
}}"#,
        json_string(&snapshot.job_id),
        json_string(&snapshot.job_path.display().to_string()),
        queue_path
            .map(|path| json_string(&path.display().to_string()))
            .unwrap_or_else(|| "null".to_string()),
        json_string(&ack_path.display().to_string()),
        json_string(&snapshot.queue_bucket),
        json_string(&snapshot.status),
        json_string(&snapshot.stage),
        json_string(&acknowledged_at),
        json_string(acknowledged_by),
        json_string(&snapshot.note),
    );
    fs::write(&ack_path, rendered).map_err(io_err)?;
    ensure_private_file(&ack_path)?;
    Ok(QueueAckCapture {
        root: root.to_path_buf(),
        job_id: snapshot.job_id.clone(),
        job_path: snapshot.job_path.clone(),
        queue_path: queue_path.map(Path::to_path_buf),
        ack_path: ack_path.clone(),
        queue_bucket: snapshot.queue_bucket.clone(),
        job_status: snapshot.status.clone(),
        acknowledged_at,
        acknowledged_by: acknowledged_by.to_string(),
        note: snapshot.note.clone(),
    })
}

fn ensure_parity_dir(root: &Path) -> ShadowResult<PathBuf> {
    let parity_dir = artifact_root(root)?.join("parity");
    fs::create_dir_all(&parity_dir).map_err(io_err)?;
    Ok(parity_dir)
}

fn runtime_layout_config(root: &Path) -> Config {
    read_config(root).unwrap_or_else(|_| Config {
        mode: "embedded".to_string(),
        kernel_path: String::new(),
        org_id: "local_foundry".to_string(),
        state_dir: "state".to_string(),
        run_dir: "run".to_string(),
        log_dir: "logs".to_string(),
        artifact_dir: "artifacts".to_string(),
        capabilities_dir: "capabilities".to_string(),
        python_path: "workers/python".to_string(),
        typescript_path: "workers/typescript".to_string(),
        wasm_dir: "workers/wasm".to_string(),
        service_http_address: "127.0.0.1:18910".to_string(),
        service_token_env: "LOOM_SERVICE_TOKEN".to_string(),
        service_max_jobs: 8,
        service_poll_seconds: 1,
        service_max_iterations: 0,
        log_level: "info".to_string(),
        log_format: "jsonl".to_string(),
        log_max_bytes: 5 * 1024 * 1024,
        log_max_files: 5,
        handoff_mode: "off".to_string(),
        delivery_queue: loom_core::DEFAULT_DELIVERY_QUEUE.to_string(),
    })
}

fn state_root(root: &Path) -> ShadowResult<PathBuf> {
    let path = root.join(&runtime_layout_config(root).state_dir);
    ensure_private_dir(&path)?;
    Ok(path)
}

fn run_root(root: &Path) -> ShadowResult<PathBuf> {
    let path = root.join(&runtime_layout_config(root).run_dir);
    ensure_private_dir(&path)?;
    Ok(path)
}

fn log_root(root: &Path) -> ShadowResult<PathBuf> {
    let path = root.join(&runtime_layout_config(root).log_dir);
    ensure_private_dir(&path)?;
    Ok(path)
}

fn artifact_root(root: &Path) -> ShadowResult<PathBuf> {
    let path = root.join(&runtime_layout_config(root).artifact_dir);
    ensure_private_dir(&path)?;
    Ok(path)
}

fn ensure_parity_reference_dir(root: &Path) -> ShadowResult<PathBuf> {
    let path = ensure_parity_dir(root)?.join("reference");
    ensure_private_dir(&path)?;
    Ok(path)
}

fn render_capability_descriptor_json(capability: Option<&CapabilityDescriptor>) -> String {
    match capability {
        Some(capability) => render_capability_json(capability).trim_end().to_string(),
        None => "null".to_string(),
    }
}

fn ensure_parity_comparison_dir(root: &Path) -> ShadowResult<PathBuf> {
    let path = ensure_parity_dir(root)?.join("comparisons");
    ensure_private_dir(&path)?;
    Ok(path)
}

fn ensure_private_dir(path: &Path) -> ShadowResult<()> {
    fs::create_dir_all(path).map_err(io_err)?;
    set_mode_if_supported(path, 0o700)
}

fn ensure_private_file(path: &Path) -> ShadowResult<()> {
    if path.exists() {
        set_mode_if_supported(path, 0o600)?;
    }
    Ok(())
}

#[cfg(unix)]
fn set_mode_if_supported(path: &Path, mode: u32) -> ShadowResult<()> {
    use std::os::unix::fs::PermissionsExt;

    let mut permissions = fs::metadata(path).map_err(io_err)?.permissions();
    permissions.set_mode(mode);
    match fs::set_permissions(path, permissions) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == io::ErrorKind::PermissionDenied => Ok(()),
        Err(error) => Err(io_err(error)),
    }
}

#[cfg(not(unix))]
fn set_mode_if_supported(_path: &Path, _mode: u32) -> ShadowResult<()> {
    Ok(())
}

fn parity_reference_action_path(root: &Path, input_hash: &str) -> ShadowResult<PathBuf> {
    Ok(ensure_parity_reference_dir(root)?.join(format!("{}.json", input_hash)))
}

fn parity_reference_latest_path(root: &Path) -> ShadowResult<PathBuf> {
    Ok(ensure_parity_dir(root)?.join("reference_latest.json"))
}

fn parity_reference_stream_path(root: &Path) -> ShadowResult<PathBuf> {
    Ok(ensure_parity_dir(root)?.join("reference_stream.jsonl"))
}

fn parity_comparison_action_path(root: &Path, input_hash: &str) -> ShadowResult<PathBuf> {
    Ok(ensure_parity_comparison_dir(root)?.join(format!("{}.json", input_hash)))
}

fn parity_comparison_latest_path(root: &Path) -> ShadowResult<PathBuf> {
    Ok(ensure_parity_dir(root)?.join("comparison_latest.json"))
}

fn parity_comparison_stream_path(root: &Path) -> ShadowResult<PathBuf> {
    Ok(ensure_parity_dir(root)?.join("comparison_stream.jsonl"))
}

fn write_reference_parity_artifacts(
    root: &Path,
    envelope: &ActionEnvelope,
    decision: &DecisionCapture,
    reference: &ReferenceGateCheck,
) -> ShadowResult<()> {
    let action_path = parity_reference_action_path(root, &decision.input_hash)?;
    let latest_path = parity_reference_latest_path(root)?;
    let stream_path = parity_reference_stream_path(root)?;
    let decision_status = if reference.allowed { "allow" } else { "deny" };
    let rendered = format!(
        "{{\n  \"status\": \"reference_action_captured\",\n  \"source\": \"reference_adapter\",\n  \"input_hash\": {},\n  \"agent_id\": {},\n  \"org_id\": {},\n  \"action_type\": {},\n  \"resource\": {},\n  \"estimated_cost_usd\": {:.6},\n  \"reference_allowed\": {},\n  \"reference_decision\": {},\n  \"reference_stage\": {},\n  \"reference_reason\": {},\n  \"effective_source\": {},\n  \"effective_stage\": {},\n  \"overall_decision\": {},\n  \"note\": \"action-level reference snapshot for parity comparison\"\n}}\n",
        json_string(&decision.input_hash),
        json_string(&envelope.agent_id),
        json_string(&envelope.org_id),
        json_string(&envelope.action_type),
        json_string(&envelope.resource),
        envelope.estimated_cost_usd,
        if reference.allowed { "true".to_string() } else { "false".to_string() },
        json_string(decision_status),
        json_string(&reference.stage),
        json_string(&reference.reason),
        json_string(&decision.effective_source),
        json_string(&decision.effective_stage),
        json_string(&decision.overall_decision),
    );
    fs::write(&action_path, &rendered).map_err(io_err)?;
    fs::write(&latest_path, &rendered).map_err(io_err)?;
    append_line(
        &stream_path,
        &format!(
            "{{\"timestamp\":{},\"input_hash\":{},\"status\":\"reference_action_captured\",\"reference_decision\":{},\"reference_stage\":{},\"action_type\":{},\"resource\":{},\"artifact_path\":{}}}\n",
            json_string(&timestamp_now()),
            json_string(&decision.input_hash),
            json_string(decision_status),
            json_string(&reference.stage),
            json_string(&envelope.action_type),
            json_string(&envelope.resource),
            json_string(&action_path.display().to_string()),
        ),
    )?;
    Ok(())
}

fn write_parity_comparison_artifacts(
    root: &Path,
    capture: &RuntimeExecutionCapture,
    runtime_event: &RuntimeEventV1,
) -> ShadowResult<()> {
    let action_path = parity_comparison_action_path(root, &capture.input_hash)?;
    let latest_path = parity_comparison_latest_path(root)?;
    let stream_path = parity_comparison_stream_path(root)?;
    let rendered = format!(
        "{{\n  \"status\": \"action_parity_compared\",\n  \"comparison_id\": {},\n  \"event_schema_version\": {},\n  \"input_hash\": {},\n  \"job_id\": {},\n  \"execution_id\": {},\n  \"decision_id\": {},\n  \"parity_id\": {},\n  \"audit_id\": {},\n  \"runtime_event_id\": {},\n  \"action_type\": {},\n  \"resource\": {},\n  \"reference_decision\": {},\n  \"reference_stage\": {},\n  \"runtime_decision\": {},\n  \"runtime_stage\": {},\n  \"runtime_outcome\": {},\n  \"comparison_status\": {},\n  \"reference_probe_status\": {},\n  \"execution_path\": {},\n  \"runtime_event_path\": {},\n  \"audit_log_path\": {},\n  \"note\": \"action-level parity comparison between Loom runtime execution and the reference adapter; live probe remains supplementary\"\n}}\n",
        json_string(&runtime_event.parity_id),
        json_string(runtime_event.schema_version.as_str()),
        json_string(&capture.input_hash),
        json_string(&runtime_event.job_id),
        json_string(&runtime_event.execution_id),
        json_string(&runtime_event.decision_id),
        json_string(&runtime_event.parity_id),
        json_string(&runtime_event.audit_id),
        json_string(&runtime_event.event_id),
        json_string(&capture.action_type),
        json_string(&capture.resource),
        json_string(&capture.reference_decision),
        json_string(&capture.reference_stage),
        json_string(&capture.overall_decision),
        json_string(&capture.effective_stage),
        json_string(&capture.runtime_outcome),
        json_string(&capture.parity_status),
        json_string(&capture.reference_probe_status),
        json_string(&capture.execution_path.display().to_string()),
        json_string(&capture.runtime_event_path.display().to_string()),
        json_string(&capture.audit_log_path.display().to_string()),
    );
    fs::write(&action_path, &rendered).map_err(io_err)?;
    fs::write(&latest_path, &rendered).map_err(io_err)?;
    append_line(
        &stream_path,
        &format!(
            "{{\"timestamp\":{},\"comparison_id\":{},\"input_hash\":{},\"job_id\":{},\"execution_id\":{},\"runtime_event_id\":{},\"reference_decision\":{},\"runtime_decision\":{},\"comparison_status\":{},\"reference_probe_status\":{},\"artifact_path\":{}}}\n",
            json_string(&timestamp_now()),
            json_string(&runtime_event.parity_id),
            json_string(&capture.input_hash),
            json_string(&runtime_event.job_id),
            json_string(&runtime_event.execution_id),
            json_string(&runtime_event.event_id),
            json_string(&capture.reference_decision),
            json_string(&capture.overall_decision),
            json_string(&capture.parity_status),
            json_string(&capture.reference_probe_status),
            json_string(&action_path.display().to_string()),
        ),
    )?;
    Ok(())
}

fn supervisor_config(root: &Path) -> ShadowResult<Config> {
    Ok(runtime_layout_config(root))
}

fn run_worker_supervisor(
    root: &Path,
    envelope: &ActionEnvelope,
    decision: &DecisionCapture,
) -> ShadowResult<WorkerExecutionCapture> {
    let config = supervisor_config(root)?;
    let _ = ensure_runtime_worker_scaffold(root, &config)?;
    let capability = resolve_capability_for_request(
        root,
        &config,
        if envelope.capability_name.is_empty() {
            None
        } else {
            Some(envelope.capability_name.as_str())
        },
        &envelope.action_type,
        &envelope.resource,
    )?;
    let jobs_dir = ensure_runtime_dir(root)?
        .join("jobs")
        .join(&decision.input_hash);
    fs::create_dir_all(&jobs_dir).map_err(io_err)?;
    let worker_request_path = jobs_dir.join("request.json");
    let worker_result_path = jobs_dir.join("result.json");
    let worker_log_path = jobs_dir.join("worker.log");

    fs::write(
        &worker_request_path,
        format!(
            "{{\n  \"worker_contract_version\": \"loom.worker.v0\",\n  \"input_hash\": {},\n  \"envelope\": {{\n    \"agent_id\": {},\n    \"org_id\": {},\n    \"runtime_id\": {},\n    \"action_type\": {},\n    \"resource\": {},\n    \"capability_name\": {},\n    \"payload_json\": {},\n    \"estimated_cost_usd\": {:.6}\n  }},\n  \"capability\": {},\n  \"decision\": {{\n    \"overall_decision\": {},\n    \"effective_source\": {},\n    \"effective_stage\": {},\n    \"reference_stage\": {}\n  }}\n}}\n",
            json_string(&decision.input_hash),
            json_string(&envelope.agent_id),
            json_string(&envelope.org_id),
            json_string(&envelope.runtime_id),
            json_string(&envelope.action_type),
            json_string(&envelope.resource),
            json_string(&envelope.capability_name),
            json_string(&envelope.payload_json),
            envelope.estimated_cost_usd,
            render_capability_descriptor_json(capability.as_ref()),
            json_string(&decision.overall_decision),
            json_string(&decision.effective_source),
            json_string(&decision.effective_stage),
            json_string(&decision.reference_stage),
        ),
    )
    .map_err(io_err)?;

    if decision.overall_decision != "allow" {
        fs::write(
            &worker_log_path,
            format!(
                "worker_not_dispatched decision={} stage={} reason={}\n",
                decision.overall_decision, decision.effective_stage, decision.effective_reason
            ),
        )
        .map_err(io_err)?;
        return Ok(WorkerExecutionCapture {
            worker_request_path,
            worker_result_path,
            worker_log_path,
            worker_status: "not_dispatched".to_string(),
            worker_kind: capability
                .as_ref()
                .map(|item| format!("{}:not_dispatched", item.name))
                .unwrap_or_else(|| "python_reference_worker".to_string()),
            worker_note: "effective decision denied; supervisor did not dispatch worker"
                .to_string(),
            runtime_outcome: "denied".to_string(),
        });
    }

    if let Some(capability) = capability.as_ref() {
        if capability.worker_kind == "wasm" {
            return dispatch_wasm_worker(
                capability,
                &envelope.resource,
                &jobs_dir,
                &worker_request_path,
                &worker_result_path,
                &worker_log_path,
            );
        }
        if capability.worker_kind == "python" {
            return dispatch_python_worker(
                root,
                &config,
                Some(capability),
                &worker_request_path,
                &worker_result_path,
                &worker_log_path,
            );
        }
    }

    // Wasm dispatch remains available for direct resource-based execution too.
    if envelope.resource.starts_with("wasm:") || envelope.resource.starts_with("builtin:") {
        return dispatch_wasm_worker(
            &CapabilityDescriptor {
                name: "resource_direct_wasm".to_string(),
                description: "resource-directed wasm execution".to_string(),
                action_type: envelope.action_type.clone(),
                resource: envelope.resource.clone(),
                worker_kind: "wasm".to_string(),
                worker_entry: String::new(),
                wasm_module: envelope.resource.clone(),
                payload_mode: "none".to_string(),
                source_kind: "loom_runtime_direct".to_string(),
                source_path: envelope.resource.clone(),
                source_manifest: String::new(),
                adapter_kind: "loom_wasm_guest_v0".to_string(),
                import_provenance: "loom_runtime_direct_contract_v0".to_string(),
                verification_status: "runtime_direct".to_string(),
                last_verified_at: String::new(),
                last_verification_job_id: String::new(),
                last_verification_execution_id: String::new(),
                verification_note: "resource-directed wasm execution".to_string(),
                promotion_state: "runtime_direct".to_string(),
                promoted_at: String::new(),
                enabled: true,
            },
            &envelope.resource,
            &jobs_dir,
            &worker_request_path,
            &worker_result_path,
            &worker_log_path,
        );
    }

    dispatch_python_worker(
        root,
        &config,
        capability.as_ref(),
        &worker_request_path,
        &worker_result_path,
        &worker_log_path,
    )
}

fn dispatch_python_worker(
    root: &Path,
    config: &Config,
    capability: Option<&CapabilityDescriptor>,
    worker_request_path: &Path,
    worker_result_path: &Path,
    worker_log_path: &Path,
) -> ShadowResult<WorkerExecutionCapture> {
    let worker_entry = capability
        .and_then(|item| {
            if item.worker_entry.trim().is_empty() {
                None
            } else {
                Some(root.join(&item.worker_entry))
            }
        })
        .unwrap_or_else(|| runtime_worker_entry(root, config));
    let output = Command::new("python3")
        .arg(&worker_entry)
        .arg("--input")
        .arg(worker_request_path)
        .arg("--output")
        .arg(worker_result_path)
        .output()
        .map_err(io_err)?;

    let mut log_contents = String::new();
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    if !stdout.trim().is_empty() {
        log_contents.push_str("stdout:\n");
        log_contents.push_str(stdout.trim());
        log_contents.push('\n');
    }
    if !stderr.trim().is_empty() {
        log_contents.push_str("stderr:\n");
        log_contents.push_str(stderr.trim());
        log_contents.push('\n');
    }
    fs::write(worker_log_path, log_contents).map_err(io_err)?;

    if output.status.success() && worker_result_path.exists() {
        Ok(WorkerExecutionCapture {
            worker_request_path: worker_request_path.to_path_buf(),
            worker_result_path: worker_result_path.to_path_buf(),
            worker_log_path: worker_log_path.to_path_buf(),
            worker_status: "completed".to_string(),
            worker_kind: capability
                .map(|item| format!("python_capability/{}", item.name))
                .unwrap_or_else(|| "python_reference_worker".to_string()),
            worker_note: capability
                .map(|item| {
                    format!(
                        "capability {} dispatched via {}",
                        item.name,
                        worker_entry.display()
                    )
                })
                .unwrap_or_else(|| {
                    format!(
                        "experimental supervisor dispatched {}",
                        worker_entry.display()
                    )
                }),
            runtime_outcome: "worker_executed".to_string(),
        })
    } else {
        Ok(WorkerExecutionCapture {
            worker_request_path: worker_request_path.to_path_buf(),
            worker_result_path: worker_result_path.to_path_buf(),
            worker_log_path: worker_log_path.to_path_buf(),
            worker_status: "failed".to_string(),
            worker_kind: capability
                .map(|item| format!("python_capability/{}", item.name))
                .unwrap_or_else(|| "python_reference_worker".to_string()),
            worker_note: if stderr.trim().is_empty() {
                "worker supervisor command failed".to_string()
            } else {
                stderr.trim().to_string()
            },
            runtime_outcome: "worker_failed".to_string(),
        })
    }
}

/// Dispatch a job to a WASM worker via Wasmtime. Used when resource is "wasm:*" or "builtin:*".
fn dispatch_wasm_worker(
    capability: &CapabilityDescriptor,
    resource: &str,
    jobs_dir: &Path,
    worker_request_path: &Path,
    worker_result_path: &Path,
    worker_log_path: &Path,
) -> ShadowResult<WorkerExecutionCapture> {
    let module_source = if !capability.wasm_module.trim().is_empty() {
        capability.wasm_module.as_str()
    } else {
        resource
    };
    let wasm_bytes = if module_source == "builtin:minimal" {
        // Inline minimal WASM module: exports "run" -> i32 (returns 7)
        vec![
            0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00, 0x01, 0x05, 0x01, 0x60, 0x00, 0x01,
            0x7f, 0x03, 0x02, 0x01, 0x00, 0x07, 0x07, 0x01, 0x03, 0x72, 0x75, 0x6e, 0x00, 0x00,
            0x0a, 0x06, 0x01, 0x04, 0x00, 0x41, 0x07, 0x0b,
        ]
    } else if module_source == "builtin:browser.navigate" {
        build_builtin_browser_navigate_guest(capability, worker_request_path)?
    } else if module_source == "builtin:terminal.exec" {
        build_builtin_terminal_exec_guest(capability, worker_request_path)?
    } else if module_source == "builtin:heartbeat.schedule" {
        build_builtin_heartbeat_schedule_guest(capability, worker_request_path)?
    } else if module_source == "builtin:system.info" {
        build_builtin_system_info_guest(capability, worker_request_path)?
    } else if module_source == "builtin:fs.read" {
        build_builtin_fs_read_guest(capability, worker_request_path)?
    } else if module_source == "builtin:fs.write" {
        build_builtin_fs_write_guest(capability, worker_request_path)?
    } else if module_source == "builtin:llm.inference" {
        build_builtin_llm_inference_guest(capability, worker_request_path)?
    } else if module_source == "builtin:kv.get" {
        build_builtin_kv_get_guest(capability, worker_request_path)?
    } else if module_source == "builtin:kv.set" {
        build_builtin_kv_set_guest(capability, worker_request_path)?
    } else if let Some(module_path) = module_source.strip_prefix("wasm:") {
        fs::read(module_path)
            .map_err(|error| format!("failed to read wasm module {}: {}", module_path, error))?
    } else {
        return Err(format!("unsupported wasm resource: {}", module_source));
    };

    let fuel_budget: u64 = 100_000;
    let host_config = WasmHostBuilder::default()
        .with_backend(HostBackend::WasmtimeReady)
        .with_profile_name(format!("runtime/{}", capability.name))
        .build()
        .map_err(|errors| format!("wasm host config: {}", errors.join("; ")))?;

    let request = WasmExecutionRequest {
        host: host_config,
        source: WasmGuestSource::WasmBytes {
            name: capability.name.clone(),
            bytes: wasm_bytes,
        },
        entrypoint: "run".to_string(),
        entrypoint_args: vec![],
        memory_probe: None,
        fuel_budget,
    };

    match run_wasm_guest(&request) {
        Ok(result) => {
            let heartbeat_receipt_path = if module_source == "builtin:heartbeat.schedule" {
                Some(append_builtin_heartbeat_receipt(
                    jobs_dir,
                    capability,
                    worker_request_path,
                    &result,
                )?)
            } else {
                None
            };
            let host_response_json = result
                .host_response_json
                .clone()
                .unwrap_or_else(|| "null".to_string());
            let host_calls_json =
                serde_json::to_string(&result.host_calls).unwrap_or_else(|_| "[]".to_string());
            let result_json = format!(
                "{{
  \"status\": \"completed\",
  \"worker_type\": \"wasm\",
  \"module\": {},
  \"entrypoint\": \"run\",
  \"entrypoint_result\": {},
  \"fuel_budget\": {},
  \"host_backend\": {},
  \"pooling_profile\": {},
  \"host_calls\": {},
  \"host_response_json\": {}
}}
",
                json_string(&result.module_name),
                result
                    .entrypoint_result
                    .map(|value| value.to_string())
                    .unwrap_or_else(|| "null".to_string()),
                fuel_budget,
                json_string(&result.host_backend),
                json_string(&result.pooling_profile),
                host_calls_json,
                host_response_json,
            );
            fs::write(worker_result_path, &result_json).map_err(io_err)?;
            let host_calls_label = if result.host_calls.is_empty() {
                "none".to_string()
            } else {
                result.host_calls.join(",")
            };
            let log_msg = format!(
                "wasm worker completed: module={} entrypoint=run result={} backend={} host_calls={} jobs_dir={} heartbeat_receipt={}
",
                result.module_name,
                result.entrypoint_result.map(|value| value.to_string()).unwrap_or_else(|| "null".to_string()),
                result.host_backend,
                host_calls_label,
                jobs_dir.display(),
                heartbeat_receipt_path
                    .as_ref()
                    .map(|path| path.display().to_string())
                    .unwrap_or_else(|| "<none>".to_string()),
            );
            fs::write(worker_log_path, &log_msg).map_err(io_err)?;
            Ok(WorkerExecutionCapture {
                worker_request_path: worker_request_path.to_path_buf(),
                worker_result_path: worker_result_path.to_path_buf(),
                worker_log_path: worker_log_path.to_path_buf(),
                worker_status: "completed".to_string(),
                worker_kind: format!("wasm_wasmtime/{}", capability.name),
                worker_note: format!(
                    "wasm capability {} executed: module={} entrypoint_result={} host_calls={} fuel_budget={} heartbeat_receipt={}",
                    capability.name,
                    result.module_name,
                    result.entrypoint_result.map(|value| value.to_string()).unwrap_or_else(|| "null".to_string()),
                    if result.host_calls.is_empty() { "none".to_string() } else { result.host_calls.join(",") },
                    fuel_budget,
                    heartbeat_receipt_path
                        .as_ref()
                        .map(|path| path.display().to_string())
                        .unwrap_or_else(|| "<none>".to_string()),
                ),
                runtime_outcome: "worker_executed".to_string(),
            })
        }
        Err(error) => {
            let is_fuel_exhaustion = error.contains("fuel") || error.contains("out of fuel");
            let result_json = format!(
                "{{
  \"status\": \"failed\",
  \"worker_type\": \"wasm\",
  \"module\": {},
  \"error\": {},
  \"fuel_exhaustion\": {}
}}
",
                json_string(module_source),
                json_string(&error),
                if is_fuel_exhaustion { "true" } else { "false" },
            );
            fs::write(worker_result_path, &result_json).map_err(io_err)?;
            fs::write(
                worker_log_path,
                format!(
                    "wasm worker failed: {}
",
                    error
                ),
            )
            .map_err(io_err)?;
            Ok(WorkerExecutionCapture {
                worker_request_path: worker_request_path.to_path_buf(),
                worker_result_path: worker_result_path.to_path_buf(),
                worker_log_path: worker_log_path.to_path_buf(),
                worker_status: "failed".to_string(),
                worker_kind: format!("wasm_wasmtime/{}", capability.name),
                worker_note: if is_fuel_exhaustion {
                    format!("wasm fuel exhaustion: {}", error)
                } else {
                    format!("wasm worker failed: {}", error)
                },
                runtime_outcome: if is_fuel_exhaustion {
                    "fuel_exhausted".to_string()
                } else {
                    "worker_failed".to_string()
                },
            })
        }
    }
}

fn build_builtin_browser_navigate_guest(
    capability: &CapabilityDescriptor,
    worker_request_path: &Path,
) -> ShadowResult<Vec<u8>> {
    let raw = fs::read_to_string(worker_request_path).map_err(io_err)?;
    let body: Value = serde_json::from_str(&raw).map_err(io_err)?;
    let envelope = body.get("envelope");
    let payload_json = value_json_string(envelope.and_then(|value| value.get("payload_json")));
    let payload = if payload_json.is_empty() {
        Value::Object(serde_json::Map::new())
    } else {
        serde_json::from_str(&payload_json).map_err(|error| {
            format!(
                "invalid browser payload_json for {}: {}",
                capability.name, error
            )
        })?
    };
    let url = value_string(payload.get("url"));
    if url.is_empty() {
        return Err(format!(
            "capability '{}' requires payload_json.url",
            capability.name
        ));
    }
    let allowed_hosts = value_string_vec(payload.get("allowed_hosts"));
    let timeout_ms = payload
        .get("timeout_ms")
        .and_then(Value::as_u64)
        .unwrap_or(3_000);
    let runtime_id = value_string(envelope.and_then(|value| value.get("runtime_id")));
    let input_hash = value_string(body.get("input_hash"));
    let wait_for = value_string(payload.get("wait_for"));
    let request = WasmBrowserNavigateRequest {
        security: WasmHostSecurityContext {
            capability_name: capability.name.clone(),
            agent_id: value_string(envelope.and_then(|value| value.get("agent_id"))),
            org_id: value_string(envelope.and_then(|value| value.get("org_id"))),
            session_id: runtime_id.clone(),
            operation_id: input_hash.clone(),
            max_timeout_ms: timeout_ms.max(1),
            max_response_bytes: 16_384,
            allowed_hosts: allowed_hosts.clone(),
            allowed_workdir_roots: vec![".".to_string()],
            require_user_present: false,
        },
        session_id: if runtime_id.is_empty() {
            input_hash
        } else {
            runtime_id
        },
        url,
        allowed_hosts,
        wait_for: if wait_for.is_empty() {
            "dom_content_loaded".to_string()
        } else {
            wait_for
        },
        timeout_ms,
        capture_semantic_snapshot: payload
            .get("capture_semantic_snapshot")
            .and_then(Value::as_bool)
            .unwrap_or(true),
    };
    let request_json = render_wasm_browser_navigate_request_json(&request);
    builtin_browser_navigate_guest_bytes(&request_json)
}

fn build_builtin_terminal_exec_guest(
    capability: &CapabilityDescriptor,
    worker_request_path: &Path,
) -> ShadowResult<Vec<u8>> {
    let raw = fs::read_to_string(worker_request_path).map_err(io_err)?;
    let body: Value = serde_json::from_str(&raw).map_err(io_err)?;
    let envelope = body.get("envelope");
    let payload_json = value_json_string(envelope.and_then(|value| value.get("payload_json")));
    let payload = if payload_json.is_empty() {
        Value::Object(serde_json::Map::new())
    } else {
        serde_json::from_str(&payload_json).map_err(|error| {
            format!(
                "invalid terminal payload_json for {}: {}",
                capability.name, error
            )
        })?
    };
    let argv = value_string_vec(payload.get("argv"));
    if argv.is_empty() {
        return Err(format!(
            "capability '{}' requires payload_json.argv",
            capability.name
        ));
    }
    let timeout_ms = payload
        .get("timeout_ms")
        .and_then(Value::as_u64)
        .unwrap_or(2_000);
    let max_output_bytes = payload
        .get("max_output_bytes")
        .and_then(Value::as_u64)
        .unwrap_or(16_384) as usize;
    let allowed_workdir_roots = value_string_vec(payload.get("allowed_workdir_roots"));
    let request = WasmTerminalExecRequest {
        security: WasmHostSecurityContext {
            capability_name: capability.name.clone(),
            agent_id: value_string(envelope.and_then(|value| value.get("agent_id"))),
            org_id: value_string(envelope.and_then(|value| value.get("org_id"))),
            session_id: value_string(envelope.and_then(|value| value.get("runtime_id"))),
            operation_id: value_string(body.get("input_hash")),
            max_timeout_ms: timeout_ms.max(1),
            max_response_bytes: max_output_bytes.max(256),
            allowed_hosts: Vec::new(),
            allowed_workdir_roots: if allowed_workdir_roots.is_empty() {
                vec![".".to_string()]
            } else {
                allowed_workdir_roots
            },
            require_user_present: false,
        },
        argv,
        working_dir: {
            let working_dir = value_string(payload.get("working_dir"));
            if working_dir.is_empty() {
                ".".to_string()
            } else {
                working_dir
            }
        },
        env_allowlist: value_string_vec(payload.get("env_allowlist")),
        stdin_utf8: value_string(payload.get("stdin_utf8")),
        timeout_ms,
        max_output_bytes,
        require_clean_environment: payload
            .get("require_clean_environment")
            .and_then(Value::as_bool)
            .unwrap_or(true),
    };
    let request_json = render_wasm_terminal_exec_request_json(&request);
    builtin_terminal_exec_guest_bytes(&request_json)
}

fn build_builtin_heartbeat_schedule_guest(
    capability: &CapabilityDescriptor,
    worker_request_path: &Path,
) -> ShadowResult<Vec<u8>> {
    let raw = fs::read_to_string(worker_request_path).map_err(io_err)?;
    let body: Value = serde_json::from_str(&raw).map_err(io_err)?;
    let envelope = body.get("envelope");
    let payload_json = value_json_string(envelope.and_then(|value| value.get("payload_json")));
    let payload = if payload_json.is_empty() {
        Value::Object(serde_json::Map::new())
    } else {
        serde_json::from_str(&payload_json).map_err(|error| {
            format!(
                "invalid heartbeat payload_json for {}: {}",
                capability.name, error
            )
        })?
    };
    let schedule_kind = match value_string(payload.get("schedule_kind")).as_str() {
        "once" => WasmHeartbeatScheduleKind::Once,
        "cron" => WasmHeartbeatScheduleKind::Cron,
        _ => WasmHeartbeatScheduleKind::Interval,
    };
    let timeout_ms = payload
        .get("timeout_ms")
        .and_then(Value::as_u64)
        .unwrap_or(1_000);
    let heartbeat_id = {
        let explicit = value_string(payload.get("heartbeat_id"));
        if explicit.is_empty() {
            value_string(body.get("input_hash"))
        } else {
            explicit
        }
    };
    let nested_payload_json = {
        let raw = value_json_string(payload.get("payload_json"));
        if !raw.is_empty() {
            raw
        } else {
            value_json_string(payload.get("payload"))
        }
    };
    let request = WasmHeartbeatScheduleRequest {
        security: WasmHostSecurityContext {
            capability_name: capability.name.clone(),
            agent_id: value_string(envelope.and_then(|value| value.get("agent_id"))),
            org_id: value_string(envelope.and_then(|value| value.get("org_id"))),
            session_id: value_string(envelope.and_then(|value| value.get("runtime_id"))),
            operation_id: value_string(body.get("input_hash")),
            max_timeout_ms: timeout_ms.max(1),
            max_response_bytes: 4_096,
            allowed_hosts: Vec::new(),
            allowed_workdir_roots: vec![".".to_string()],
            require_user_present: false,
        },
        heartbeat_id,
        capability_name: {
            let requested = value_string(payload.get("capability_name"));
            if requested.is_empty() {
                capability.name.clone()
            } else {
                requested
            }
        },
        schedule_kind,
        schedule_expression: value_string(payload.get("schedule_expression")),
        not_before_unix_ms: payload.get("not_before_unix_ms").and_then(Value::as_u64),
        interval_seconds: payload
            .get("interval_seconds")
            .and_then(Value::as_u64)
            .or(Some(300)),
        jitter_seconds: payload
            .get("jitter_seconds")
            .and_then(Value::as_u64)
            .unwrap_or(15),
        payload_json: nested_payload_json,
        max_runs: payload
            .get("max_runs")
            .and_then(Value::as_u64)
            .map(|value| value as u32),
    };
    let request_json = render_wasm_heartbeat_schedule_request_json(&request);
    builtin_heartbeat_schedule_guest_bytes(&request_json)
}

fn build_builtin_system_info_guest(
    capability: &CapabilityDescriptor,
    worker_request_path: &Path,
) -> ShadowResult<Vec<u8>> {
    let raw = fs::read_to_string(worker_request_path).map_err(io_err)?;
    let body: Value = serde_json::from_str(&raw).map_err(io_err)?;
    let envelope = body.get("envelope");
    let request = WasmSystemInfoRequest {
        security: WasmHostSecurityContext {
            capability_name: capability.name.clone(),
            agent_id: value_string(envelope.and_then(|value| value.get("agent_id"))),
            org_id: value_string(envelope.and_then(|value| value.get("org_id"))),
            session_id: value_string(envelope.and_then(|value| value.get("runtime_id"))),
            operation_id: value_string(body.get("input_hash")),
            max_timeout_ms: 500,
            max_response_bytes: 4_096,
            allowed_hosts: Vec::new(),
            allowed_workdir_roots: vec![
                "/home/ubuntu/.local/share/meridian-loom/runtime/default/workspace".to_string(),
            ],
            require_user_present: false,
        },
    };
    let request_json = render_wasm_system_info_request_json(&request);
    builtin_system_info_guest_bytes(&request_json)
}

fn build_builtin_fs_read_guest(
    capability: &CapabilityDescriptor,
    worker_request_path: &Path,
) -> ShadowResult<Vec<u8>> {
    let raw = fs::read_to_string(worker_request_path).map_err(io_err)?;
    let body: Value = serde_json::from_str(&raw).map_err(io_err)?;
    let envelope = body.get("envelope");
    let payload_json = value_json_string(envelope.and_then(|value| value.get("payload_json")));
    let payload = if payload_json.is_empty() {
        Value::Object(serde_json::Map::new())
    } else {
        serde_json::from_str(&payload_json).map_err(|error| {
            format!(
                "invalid fs read payload_json for {}: {}",
                capability.name, error
            )
        })?
    };
    let path = value_string(payload.get("path"));
    if path.is_empty() {
        return Err(format!(
            "capability '{}' requires payload_json.path",
            capability.name
        ));
    }
    let max_bytes = payload
        .get("max_bytes")
        .and_then(Value::as_u64)
        .unwrap_or(8_192) as usize;
    let request = WasmFsReadRequest {
        security: WasmHostSecurityContext {
            capability_name: capability.name.clone(),
            agent_id: value_string(envelope.and_then(|value| value.get("agent_id"))),
            org_id: value_string(envelope.and_then(|value| value.get("org_id"))),
            session_id: value_string(envelope.and_then(|value| value.get("runtime_id"))),
            operation_id: value_string(body.get("input_hash")),
            max_timeout_ms: 1_000,
            max_response_bytes: max_bytes.max(256),
            allowed_hosts: Vec::new(),
            allowed_workdir_roots: vec![
                "/home/ubuntu/.local/share/meridian-loom/runtime/default/workspace".to_string(),
            ],
            require_user_present: false,
        },
        path,
        max_bytes,
    };
    let request_json = render_wasm_fs_read_request_json(&request);
    builtin_fs_read_guest_bytes(&request_json)
}

fn build_builtin_fs_write_guest(
    capability: &CapabilityDescriptor,
    worker_request_path: &Path,
) -> ShadowResult<Vec<u8>> {
    let raw = fs::read_to_string(worker_request_path).map_err(io_err)?;
    let body: Value = serde_json::from_str(&raw).map_err(io_err)?;
    let envelope = body.get("envelope");
    let payload_json = value_json_string(envelope.and_then(|value| value.get("payload_json")));
    let payload = if payload_json.is_empty() {
        Value::Object(serde_json::Map::new())
    } else {
        serde_json::from_str(&payload_json).map_err(|error| {
            format!(
                "invalid fs write payload_json for {}: {}",
                capability.name, error
            )
        })?
    };
    let path = value_string(payload.get("path"));
    if path.is_empty() {
        return Err(format!(
            "capability '{}' requires payload_json.path",
            capability.name
        ));
    }
    let content_utf8 = {
        let direct = value_string(payload.get("content_utf8"));
        if direct.is_empty() {
            value_string(payload.get("content"))
        } else {
            direct
        }
    };
    let request = WasmFsWriteRequest {
        security: WasmHostSecurityContext {
            capability_name: capability.name.clone(),
            agent_id: value_string(envelope.and_then(|value| value.get("agent_id"))),
            org_id: value_string(envelope.and_then(|value| value.get("org_id"))),
            session_id: value_string(envelope.and_then(|value| value.get("runtime_id"))),
            operation_id: value_string(body.get("input_hash")),
            max_timeout_ms: 1_000,
            max_response_bytes: 8_192,
            allowed_hosts: Vec::new(),
            allowed_workdir_roots: vec![
                "/home/ubuntu/.local/share/meridian-loom/runtime/default/workspace".to_string(),
            ],
            require_user_present: false,
        },
        path,
        content_utf8,
        create_dirs: payload
            .get("create_dirs")
            .and_then(Value::as_bool)
            .unwrap_or(true),
        append: payload
            .get("append")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    };
    let request_json = render_wasm_fs_write_request_json(&request);
    builtin_fs_write_guest_bytes(&request_json)
}

fn build_builtin_llm_inference_guest(
    capability: &CapabilityDescriptor,
    worker_request_path: &Path,
) -> ShadowResult<Vec<u8>> {
    let raw = fs::read_to_string(worker_request_path).map_err(io_err)?;
    let body: Value = serde_json::from_str(&raw).map_err(io_err)?;
    let envelope = body.get("envelope");
    let payload_json = value_json_string(envelope.and_then(|value| value.get("payload_json")));
    let payload = if payload_json.is_empty() {
        Value::Object(serde_json::Map::new())
    } else {
        serde_json::from_str(&payload_json).map_err(|error| {
            format!(
                "invalid llm payload_json for {}: {}",
                capability.name, error
            )
        })?
    };
    let user_prompt = {
        let prompt = value_string(payload.get("user_prompt"));
        if prompt.is_empty() {
            value_string(payload.get("prompt"))
        } else {
            prompt
        }
    };
    if user_prompt.is_empty() {
        return Err(format!(
            "capability '{}' requires payload_json.user_prompt",
            capability.name
        ));
    }
    let timeout_ms = payload
        .get("timeout_ms")
        .and_then(Value::as_u64)
        .unwrap_or(15_000);
    let request = WasmLlmInferenceRequest {
        security: WasmHostSecurityContext {
            capability_name: capability.name.clone(),
            agent_id: value_string(envelope.and_then(|value| value.get("agent_id"))),
            org_id: value_string(envelope.and_then(|value| value.get("org_id"))),
            session_id: value_string(envelope.and_then(|value| value.get("runtime_id"))),
            operation_id: value_string(body.get("input_hash")),
            max_timeout_ms: timeout_ms.max(1),
            max_response_bytes: 16_384,
            allowed_hosts: vec!["api.openai.com".to_string()],
            allowed_workdir_roots: vec![
                "/home/ubuntu/.local/share/meridian-loom/runtime/default/workspace".to_string(),
            ],
            require_user_present: false,
        },
        provider_profile: {
            let profile = value_string(payload.get("provider_profile"));
            profile
        },
        model: {
            let model = value_string(payload.get("model"));
            if model.is_empty() {
                "qwen2.5:7b".to_string()
            } else {
                model
            }
        },
        system_prompt: value_string(payload.get("system_prompt")),
        user_prompt,
        max_tokens: payload
            .get("max_tokens")
            .and_then(Value::as_u64)
            .map(|value| value as u32),
    };
    let request_json = render_wasm_llm_inference_request_json(&request);
    builtin_llm_inference_guest_bytes(&request_json)
}

fn build_builtin_kv_get_guest(
    capability: &CapabilityDescriptor,
    worker_request_path: &Path,
) -> ShadowResult<Vec<u8>> {
    let raw = fs::read_to_string(worker_request_path).map_err(io_err)?;
    let body: Value = serde_json::from_str(&raw).map_err(io_err)?;
    let envelope = body.get("envelope");
    let payload_json = value_json_string(envelope.and_then(|value| value.get("payload_json")));
    let payload = if payload_json.is_empty() {
        Value::Object(serde_json::Map::new())
    } else {
        serde_json::from_str(&payload_json).map_err(|error| {
            format!(
                "invalid kv get payload_json for {}: {}",
                capability.name, error
            )
        })?
    };
    let key = value_string(payload.get("key"));
    if key.is_empty() {
        return Err(format!(
            "capability '{}' requires payload_json.key",
            capability.name
        ));
    }
    let request = WasmKvGetRequest {
        security: WasmHostSecurityContext {
            capability_name: capability.name.clone(),
            agent_id: value_string(envelope.and_then(|value| value.get("agent_id"))),
            org_id: value_string(envelope.and_then(|value| value.get("org_id"))),
            session_id: value_string(envelope.and_then(|value| value.get("runtime_id"))),
            operation_id: value_string(body.get("input_hash")),
            max_timeout_ms: 1_000,
            max_response_bytes: 4_096,
            allowed_hosts: Vec::new(),
            allowed_workdir_roots: vec![
                "/home/ubuntu/.local/share/meridian-loom/runtime/default/workspace".to_string(),
            ],
            require_user_present: false,
        },
        namespace: {
            let namespace = value_string(payload.get("namespace"));
            if namespace.is_empty() {
                "default".to_string()
            } else {
                namespace
            }
        },
        key,
    };
    let request_json = render_wasm_kv_get_request_json(&request);
    builtin_kv_get_guest_bytes(&request_json)
}

fn build_builtin_kv_set_guest(
    capability: &CapabilityDescriptor,
    worker_request_path: &Path,
) -> ShadowResult<Vec<u8>> {
    let raw = fs::read_to_string(worker_request_path).map_err(io_err)?;
    let body: Value = serde_json::from_str(&raw).map_err(io_err)?;
    let envelope = body.get("envelope");
    let payload_json = value_json_string(envelope.and_then(|value| value.get("payload_json")));
    let payload = if payload_json.is_empty() {
        Value::Object(serde_json::Map::new())
    } else {
        serde_json::from_str(&payload_json).map_err(|error| {
            format!(
                "invalid kv set payload_json for {}: {}",
                capability.name, error
            )
        })?
    };
    let key = value_string(payload.get("key"));
    if key.is_empty() {
        return Err(format!(
            "capability '{}' requires payload_json.key",
            capability.name
        ));
    }
    let value_json = {
        let raw = value_json_string(payload.get("value_json"));
        if !raw.is_empty() {
            raw
        } else {
            value_json_string(payload.get("value"))
        }
    };
    let request = WasmKvSetRequest {
        security: WasmHostSecurityContext {
            capability_name: capability.name.clone(),
            agent_id: value_string(envelope.and_then(|value| value.get("agent_id"))),
            org_id: value_string(envelope.and_then(|value| value.get("org_id"))),
            session_id: value_string(envelope.and_then(|value| value.get("runtime_id"))),
            operation_id: value_string(body.get("input_hash")),
            max_timeout_ms: 1_000,
            max_response_bytes: 4_096,
            allowed_hosts: Vec::new(),
            allowed_workdir_roots: vec![
                "/home/ubuntu/.local/share/meridian-loom/runtime/default/workspace".to_string(),
            ],
            require_user_present: false,
        },
        namespace: {
            let namespace = value_string(payload.get("namespace"));
            if namespace.is_empty() {
                "default".to_string()
            } else {
                namespace
            }
        },
        key,
        value_json: if value_json.is_empty() {
            "null".to_string()
        } else {
            value_json
        },
    };
    let request_json = render_wasm_kv_set_request_json(&request);
    builtin_kv_set_guest_bytes(&request_json)
}

fn append_builtin_heartbeat_receipt(
    jobs_dir: &Path,
    capability: &CapabilityDescriptor,
    worker_request_path: &Path,
    result: &WasmExecutionResult,
) -> ShadowResult<PathBuf> {
    let raw = fs::read_to_string(worker_request_path).map_err(io_err)?;
    let body: Value = serde_json::from_str(&raw).map_err(io_err)?;
    let envelope = body.get("envelope");
    let payload_json = value_json_string(envelope.and_then(|value| value.get("payload_json")));
    let payload = if payload_json.is_empty() {
        Value::Object(serde_json::Map::new())
    } else {
        serde_json::from_str(&payload_json).map_err(|error| {
            format!(
                "invalid heartbeat payload_json for {}: {}",
                capability.name, error
            )
        })?
    };
    let receipt_path = jobs_dir.join("heartbeat_schedule.jsonl");
    let host_response = result
        .host_response_json
        .as_ref()
        .and_then(|raw| serde_json::from_str::<Value>(raw).ok())
        .unwrap_or(Value::Null);
    let schedule_kind = {
        let schedule_kind = value_string(payload.get("schedule_kind"));
        if schedule_kind.is_empty() {
            "interval".to_string()
        } else {
            schedule_kind
        }
    };
    let receipt = serde_json::json!({
        "timestamp": timestamp_now(),
        "capability_name": capability.name,
        "module": result.module_name,
        "runtime_path": result.runtime_path,
        "input_hash": value_string(body.get("input_hash")),
        "heartbeat_id": value_string(payload.get("heartbeat_id")),
        "requested_capability": value_string(payload.get("capability_name")),
        "schedule_kind": schedule_kind,
        "schedule_expression": value_string(payload.get("schedule_expression")),
        "interval_seconds": payload.get("interval_seconds").and_then(Value::as_u64),
        "host_calls": result.host_calls,
        "host_response": host_response,
    });
    let mut stream = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&receipt_path)
        .map_err(io_err)?;
    writeln!(stream, "{}", receipt).map_err(io_err)?;
    Ok(receipt_path)
}

fn value_string_vec(value: Option<&Value>) -> Vec<String> {
    value
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(Value::as_str)
                .map(|value| value.trim().to_string())
                .filter(|value| !value.is_empty())
                .collect::<Vec<_>>()
        })
        .unwrap_or_default()
}

/// Legacy Execution Parity Adapter: Used by Meridian to benchmark and audit legacy un-governed runtimes against the Meridian constitutional ledger.
fn capture_reference_probe(
    root: &Path,
    input_hash: &str,
) -> ShadowResult<(Option<PathBuf>, Option<PathBuf>, String, String)> {
    let parity_dir = ensure_parity_dir(root)?;
    let live_dir = parity_dir.join("reference");
    fs::create_dir_all(&live_dir).map_err(io_err)?;
    let probe_path = live_dir.join(format!("{}.json", input_hash));
    let latest_probe_path = parity_dir.join("reference_probe.json");
    let probe_stream_path = parity_dir.join("reference_probe_stream.jsonl");
    let proof_script = std::env::var("MERIDIAN_REFERENCE_PROOF_SCRIPT")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .or_else(|| {
            std::env::var("MERIDIAN_LEGACY_V1_PROOF_SCRIPT")
                .ok()
                .filter(|value| !value.trim().is_empty())
        })
        .or_else(|| {
            std::env::var("MERIDIAN_RUNTIME_PROOF_SCRIPT")
                .ok()
                .filter(|value| !value.trim().is_empty())
        })
        .map(PathBuf::from)
        .or_else(|| {
            [
                "/home/ubuntu/.meridian/workspace/company/meridian_platform/meridian_compatible_runtime_proof.py",
                "/home/ubuntu/.meridian/workspace/company/meridian_platform/meridian_runtime_proof.py",
                "/root/.meridian/workspace/company/meridian_platform/meridian_compatible_runtime_proof.py",
                "/root/.meridian/workspace/company/meridian_platform/meridian_runtime_proof.py",
            ]
            .iter()
            .map(PathBuf::from)
            .find(|candidate| candidate.exists())
        })
        .unwrap_or_else(|| {
            PathBuf::from("/home/ubuntu/.meridian/workspace/company/meridian_platform/meridian_runtime_proof.py")
        });
    if !proof_script.exists() {
        append_line(
            &probe_stream_path,
            &format!(
                "{{\"timestamp\":{},\"input_hash\":{},\"status\":\"not_available\",\"reason\":{},\"probe_path\":null}}\n",
                json_string(&timestamp_now()),
                json_string(input_hash),
                json_string(&format!("reference probe script not found at {}", proof_script.display())),
            ),
        )?;
        return Ok((
            None,
            Some(probe_stream_path),
            "not_available".to_string(),
            format!(
                "reference probe script not found at {}",
                proof_script.display()
            ),
        ));
    }

    let output = Command::new("python3")
        .arg(&proof_script)
        .arg("--json")
        .output()
        .map_err(io_err)?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        append_line(
            &probe_stream_path,
            &format!(
                "{{\"timestamp\":{},\"input_hash\":{},\"status\":\"probe_failed\",\"reason\":{},\"probe_path\":null}}\n",
                json_string(&timestamp_now()),
                json_string(input_hash),
                json_string(if stderr.is_empty() {
                    "reference probe command failed"
                } else {
                    &stderr
                }),
            ),
        )?;
        return Ok((
            None,
            Some(probe_stream_path),
            "probe_failed".to_string(),
            if stderr.is_empty() {
                "reference probe command failed".to_string()
            } else {
                stderr
            },
        ));
    }

    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    fs::write(&probe_path, format!("{}\n", stdout)).map_err(io_err)?;
    fs::write(&latest_probe_path, format!("{}\n", stdout)).map_err(io_err)?;
    let health_ok = extract_json_bool(&stdout, "\"health_ok\"").unwrap_or(false);
    let proof_level =
        extract_json_string(&stdout, "\"proof_level\"").unwrap_or_else(|| "unknown".to_string());
    let deployment_mode = extract_json_string(&stdout, "\"deployment_mode\"")
        .unwrap_or_else(|| "unknown".to_string());
    let note = format!(
        "reference probe {} with proof_level={} deployment_mode={}",
        if health_ok { "healthy" } else { "degraded" },
        proof_level,
        deployment_mode,
    );
    append_line(
        &probe_stream_path,
        &format!(
            "{{\"timestamp\":{},\"input_hash\":{},\"status\":{},\"proof_level\":{},\"deployment_mode\":{},\"probe_path\":{}}}\n",
            json_string(&timestamp_now()),
            json_string(input_hash),
            json_string(if health_ok { "ok" } else { "degraded" }),
            json_string(&proof_level),
            json_string(&deployment_mode),
            json_string(&probe_path.display().to_string()),
        ),
    )?;
    Ok((
        Some(probe_path),
        Some(probe_stream_path),
        if health_ok { "ok" } else { "degraded" }.to_string(),
        note,
    ))
}

fn reserve_runtime_budget(
    kernel_path: &Path,
    envelope: &ActionEnvelope,
    decision: &DecisionCapture,
) -> ShadowResult<BudgetReservationCapture> {
    if envelope.estimated_cost_usd <= 0.0 {
        return Ok(BudgetReservationCapture {
            reservation_id: String::new(),
            status: "skipped_zero_cost".to_string(),
            reason: "no reservation required for zero-cost action".to_string(),
        });
    }
    let kernel_dir = kernel_path.join("kernel");
    if !kernel_dir.join("treasury.py").exists() {
        return Ok(BudgetReservationCapture {
            reservation_id: String::new(),
            status: "not_available".to_string(),
            reason: format!("treasury.py not found under {}", kernel_dir.display()),
        });
    }
    let script = r#"import json, sys
kernel_dir = sys.argv[1]
org_id = sys.argv[2]
agent_id = sys.argv[3]
estimated_cost = float(sys.argv[4])
action = sys.argv[5]
resource = sys.argv[6]
input_hash = sys.argv[7]
session_id = sys.argv[8]
sys.path.insert(0, kernel_dir)
import treasury
result = treasury.reserve_runtime_budget(
    agent_id,
    estimated_cost,
    org_id=org_id,
    action=action,
    resource=resource,
    context={"input_hash": input_hash, "session_id": session_id},
    policy_ref="experimental_runtime_rehearsal",
)
print(json.dumps(result))
"#;
    let output = Command::new("python3")
        .arg("-c")
        .arg(script)
        .arg(&kernel_dir)
        .arg(&envelope.org_id)
        .arg(&envelope.agent_id)
        .arg(format!("{:.6}", envelope.estimated_cost_usd))
        .arg(&envelope.action_type)
        .arg(&envelope.resource)
        .arg(&decision.input_hash)
        .arg(&envelope.session_id)
        .output()
        .map_err(io_err)?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Ok(BudgetReservationCapture {
            reservation_id: String::new(),
            status: "reservation_failed".to_string(),
            reason: if stderr.is_empty() {
                "runtime budget reservation command failed".to_string()
            } else {
                stderr
            },
        });
    }
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let allowed = extract_json_bool(&stdout, "\"allowed\"").unwrap_or(false);
    let reservation_id = extract_json_string(&stdout, "\"reservation_id\"").unwrap_or_default();
    let reason = extract_json_string(&stdout, "\"reason\"").unwrap_or_else(|| {
        if allowed {
            "ok".to_string()
        } else {
            "runtime budget reservation denied".to_string()
        }
    });
    Ok(BudgetReservationCapture {
        reservation_id,
        status: if allowed {
            "reserved".to_string()
        } else {
            "reservation_denied".to_string()
        },
        reason,
    })
}

fn finalize_runtime_budget(
    kernel_path: &Path,
    reservation_id: &str,
    actual_cost_usd: f64,
    commit: bool,
    reason: &str,
) -> ShadowResult<BudgetReservationCapture> {
    if reservation_id.trim().is_empty() {
        return Ok(BudgetReservationCapture {
            reservation_id: String::new(),
            status: "not_requested".to_string(),
            reason: "no reservation to finalize".to_string(),
        });
    }
    let kernel_dir = kernel_path.join("kernel");
    if !kernel_dir.join("treasury.py").exists() {
        return Ok(BudgetReservationCapture {
            reservation_id: reservation_id.to_string(),
            status: "not_available".to_string(),
            reason: format!("treasury.py not found under {}", kernel_dir.display()),
        });
    }
    let script = if commit {
        r#"import json, sys
kernel_dir = sys.argv[1]
reservation_id = sys.argv[2]
actual_cost = float(sys.argv[3])
reason = sys.argv[4]
sys.path.insert(0, kernel_dir)
import treasury
print(json.dumps(treasury.commit_runtime_budget(reservation_id, actual_cost, note=reason)))"#
    } else {
        r#"import json, sys
kernel_dir = sys.argv[1]
reservation_id = sys.argv[2]
reason = sys.argv[3]
sys.path.insert(0, kernel_dir)
import treasury
print(json.dumps(treasury.release_runtime_budget(reservation_id, reason=reason)))"#
    };
    let mut command = Command::new("python3");
    command
        .arg("-c")
        .arg(script)
        .arg(&kernel_dir)
        .arg(reservation_id);
    if commit {
        command.arg(format!("{:.6}", actual_cost_usd)).arg(reason);
    } else {
        command.arg(reason);
    }
    let output = command.output().map_err(io_err)?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Ok(BudgetReservationCapture {
            reservation_id: reservation_id.to_string(),
            status: if commit {
                "commit_failed"
            } else {
                "release_failed"
            }
            .to_string(),
            reason: if stderr.is_empty() {
                "runtime budget finalization failed".to_string()
            } else {
                stderr
            },
        });
    }
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    Ok(BudgetReservationCapture {
        reservation_id: extract_json_string(&stdout, "\"reservation_id\"")
            .unwrap_or_else(|| reservation_id.to_string()),
        status: extract_json_string(&stdout, "\"status\"").unwrap_or_else(|| {
            if commit {
                "committed".to_string()
            } else {
                "released".to_string()
            }
        }),
        reason: extract_json_string(&stdout, "\"commit_reason\"")
            .or_else(|| extract_json_string(&stdout, "\"release_reason\""))
            .unwrap_or_else(|| reason.to_string()),
    })
}

/// Economy post-execution hook (S1). Calls kernel economy adapter with
/// {agent_id, outcome, cost_actual} after job completes. Writes REP/AUTH
/// delta to kernel state files via economy.py if present.
fn emit_economy_hook(
    kernel_path: &Path,
    envelope: &ActionEnvelope,
    decision: &DecisionCapture,
    runtime_outcome: &str,
    budget_capture: &BudgetReservationCapture,
) -> ShadowResult<String> {
    let kernel_dir = kernel_path.join("kernel");
    let economy_script = kernel_dir.join("economy.py");
    if !economy_script.exists() {
        return Ok("not_available".to_string());
    }
    let script = r#"import json, sys
kernel_dir = sys.argv[1]
agent_id = sys.argv[2]
org_id = sys.argv[3]
outcome = sys.argv[4]
cost_actual = float(sys.argv[5])
action_type = sys.argv[6]
decision = sys.argv[7]
input_hash = sys.argv[8]
sys.path.insert(0, kernel_dir)
import economy
result = economy.post_execution_hook(
    agent_id=agent_id,
    org_id=org_id,
    outcome=outcome,
    cost_actual_usd=cost_actual,
    action_type=action_type,
    decision=decision,
    input_hash=input_hash,
)
print(json.dumps(result))
"#;
    let actual_cost = if budget_capture.status == "committed" {
        envelope.estimated_cost_usd
    } else {
        0.0
    };
    let output = Command::new("python3")
        .arg("-c")
        .arg(script)
        .arg(&kernel_dir)
        .arg(&envelope.agent_id)
        .arg(&envelope.org_id)
        .arg(runtime_outcome)
        .arg(format!("{:.6}", actual_cost))
        .arg(&envelope.action_type)
        .arg(&decision.overall_decision)
        .arg(&decision.input_hash)
        .output()
        .map_err(io_err)?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Ok(format!(
            "economy_hook_failed: {}",
            if stderr.is_empty() {
                "unknown error"
            } else {
                &stderr
            }
        ));
    }
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let status = extract_json_string(&stdout, "\"status\"")
        .unwrap_or_else(|| "economy_hook_called".to_string());
    Ok(status)
}

fn emit_kernel_audit_preview(
    kernel_path: &Path,
    audit_preview_log: &Path,
    envelope: &ActionEnvelope,
    input_hash: &str,
) -> ShadowResult<String> {
    let kernel_dir = kernel_path.join("kernel");
    if kernel_dir.join("audit.py").exists() {
        let script = r#"import sys
kernel_dir = sys.argv[1]
org_id = sys.argv[2]
agent_id = sys.argv[3]
action = sys.argv[4]
resource = sys.argv[5]
input_hash = sys.argv[6]
estimated_cost = float(sys.argv[7])
session_id = sys.argv[8]
sys.path.insert(0, kernel_dir)
import audit
event_id = audit.log_event(
    org_id,
    agent_id,
    action,
    resource=resource,
    outcome='simulated_success',
    actor_type='agent',
    details={
        'source': 'loom_shadow_preflight',
        'input_hash': input_hash,
        'estimated_cost_usd': estimated_cost,
        'experimental': True,
    },
    policy_ref='experimental_preflight_preview',
    session_id=session_id or None,
)
print(event_id)
"#;
        let output = Command::new("python3")
            .arg("-c")
            .arg(script)
            .arg(&kernel_dir)
            .arg(&envelope.org_id)
            .arg(&envelope.agent_id)
            .arg(&envelope.action_type)
            .arg(&envelope.resource)
            .arg(input_hash)
            .arg(format!("{:.6}", envelope.estimated_cost_usd))
            .arg(&envelope.session_id)
            .env("MERIDIAN_AUDIT_FILE", audit_preview_log)
            .output()
            .map_err(io_err)?;
        if output.status.success() {
            return Ok("kernel_preview_written".to_string());
        }
    }

    append_line(
        audit_preview_log,
        &format!(
            "{{\"id\":{},\"timestamp\":{},\"org_id\":{},\"agent_id\":{},\"actor_type\":\"agent\",\"action\":{},\"resource\":{},\"outcome\":\"simulated_success\",\"details\":{{\"source\":\"loom_shadow_preflight\",\"input_hash\":{},\"estimated_cost_usd\":{:.6},\"experimental\":true}},\"policy_ref\":\"experimental_preflight_preview\"}}\n",
            json_string(&format!("preview_{}", &input_hash[..8])),
            json_string(&timestamp_now()),
            json_string(&envelope.org_id),
            json_string(&envelope.agent_id),
            json_string(&envelope.action_type),
            json_string(&envelope.resource),
            json_string(input_hash),
            envelope.estimated_cost_usd,
        ),
    )?;
    Ok("local_preview_written".to_string())
}

fn emit_runtime_audit(
    kernel_path: &Path,
    audit_log_path: &Path,
    envelope: &ActionEnvelope,
    decision: &DecisionCapture,
    outcome: &str,
    worker: &WorkerExecutionCapture,
    budget: &BudgetReservationCapture,
) -> ShadowResult<String> {
    let kernel_dir = kernel_path.join("kernel");
    let job_id = canonical_job_id(
        &envelope.org_id,
        &envelope.agent_id,
        &envelope.action_type,
        &decision.input_hash,
    );
    let execution_id = canonical_execution_id(&job_id, &decision.effective_stage, outcome);
    let decision_id = canonical_decision_id(
        &job_id,
        &decision.effective_stage,
        &decision.overall_decision,
    );
    let parity_id = canonical_parity_id(
        &job_id,
        &execution_id,
        if decision.effective_source == "reference_gate" {
            "match"
        } else {
            "divergence"
        },
    );
    let audit_id = canonical_audit_id(&job_id, &execution_id, &envelope.action_type);
    let runtime_event_id = canonical_event_id(
        &envelope.org_id,
        &envelope.agent_id,
        &envelope.action_type,
        &envelope.resource,
        outcome,
        &decision.effective_stage,
        &job_id,
        &execution_id,
    );
    if let Some(parent) = audit_log_path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    if kernel_dir.join("audit.py").exists() {
        let output = Command::new("python3")
            .arg(kernel_dir.join("audit.py"))
            .arg("log-runtime")
            .arg("--org_id")
            .arg(&envelope.org_id)
            .arg("--agent_id")
            .arg(&envelope.agent_id)
            .arg("--action")
            .arg(&envelope.action_type)
            .arg("--resource")
            .arg(&envelope.resource)
            .arg("--outcome")
            .arg(outcome)
            .arg("--input_hash")
            .arg(&decision.input_hash)
            .arg("--estimated_cost_usd")
            .arg(format!("{:.6}", envelope.estimated_cost_usd))
            .arg("--effective_source")
            .arg(&decision.effective_source)
            .arg("--effective_stage")
            .arg(&decision.effective_stage)
            .arg("--reference_stage")
            .arg(&decision.reference_stage)
            .arg("--runtime_outcome")
            .arg(outcome)
            .arg("--worker_status")
            .arg(&worker.worker_status)
            .arg("--worker_kind")
            .arg(&worker.worker_kind)
            .arg("--parity_status")
            .arg(
                if decision.overall_decision == "allow" || decision.overall_decision == "deny" {
                    if decision.effective_source == "reference_gate" {
                        "match"
                    } else {
                        "divergence"
                    }
                } else {
                    "unknown"
                },
            )
            .arg("--runtime_event_id")
            .arg(&runtime_event_id)
            .arg("--event_schema_version")
            .arg("loom.runtime.v1")
            .arg("--job_id")
            .arg(&job_id)
            .arg("--execution_id")
            .arg(&execution_id)
            .arg("--decision_id")
            .arg(&decision_id)
            .arg("--parity_id")
            .arg(&parity_id)
            .arg("--audit_id")
            .arg(&audit_id)
            .arg("--budget_reservation_id")
            .arg(&budget.reservation_id)
            .arg("--budget_reservation_status")
            .arg(&budget.status)
            .arg("--budget_reservation_reason")
            .arg(&budget.reason)
            .arg("--session_id")
            .arg(&envelope.session_id)
            .env("MERIDIAN_RUNTIME_AUDIT_FILE", audit_log_path)
            .output()
            .map_err(io_err)?;
        if output.status.success() {
            return Ok("kernel_cli_runtime_event_written".to_string());
        }
    }

    append_line(
        audit_log_path,
        &format!(
            "{{\"id\":{},\"timestamp\":{},\"org_id\":{},\"agent_id\":{},\"actor_type\":\"agent\",\"action\":{},\"resource\":{},\"outcome\":{},\"details\":{{\"source\":\"loom_runtime_execute\",\"runtime_event_id\":{},\"event_schema_version\":\"loom.runtime.v1\",\"job_id\":{},\"execution_id\":{},\"decision_id\":{},\"parity_id\":{},\"audit_id\":{},\"budget_reservation_id\":{},\"budget_reservation_status\":{},\"budget_reservation_reason\":{},\"input_hash\":{},\"estimated_cost_usd\":{:.6},\"effective_source\":{},\"effective_stage\":{},\"reference_stage\":{},\"runtime_outcome\":{},\"worker_status\":{},\"worker_kind\":{},\"experimental\":true}},\"policy_ref\":\"experimental_runtime_rehearsal\"}}\n",
            json_string(&audit_id),
            json_string(&timestamp_now()),
            json_string(&envelope.org_id),
            json_string(&envelope.agent_id),
            json_string(&envelope.action_type),
            json_string(&envelope.resource),
            json_string(outcome),
            json_string(&runtime_event_id),
            json_string(&job_id),
            json_string(&execution_id),
            json_string(&decision_id),
            json_string(&parity_id),
            json_string(&audit_id),
            if budget.reservation_id.is_empty() {
                "null".to_string()
            } else {
                json_string(&budget.reservation_id)
            },
            json_string(&budget.status),
            json_string(&budget.reason),
            json_string(&decision.input_hash),
            envelope.estimated_cost_usd,
            json_string(&decision.effective_source),
            json_string(&decision.effective_stage),
            json_string(&decision.reference_stage),
            json_string(outcome),
            json_string(&worker.worker_status),
            json_string(&worker.worker_kind),
        ),
    )?;
    Ok("runtime_event_written_local_fallback".to_string())
}

fn append_line(path: &Path, line: &str) -> ShadowResult<()> {
    let mut existing = if path.exists() {
        fs::read_to_string(path).map_err(io_err)?
    } else {
        String::new()
    };
    existing.push_str(line);
    fs::write(path, existing).map_err(io_err)?;
    ensure_private_file(path)?;
    Ok(())
}

fn write_runtime_event_artifacts(
    root: &Path,
    input_hash: &str,
    event: &RuntimeEventV1,
) -> ShadowResult<(PathBuf, PathBuf)> {
    let event_path = runtime_event_path(root, input_hash)?;
    let latest_path = runtime_event_latest_path(root)?;
    let stream_path = runtime_event_stream_path(root)?;
    let rendered = event.render_json();
    fs::write(&event_path, &rendered).map_err(io_err)?;
    fs::write(&latest_path, &rendered).map_err(io_err)?;
    append_line(&stream_path, &format!("{}\n", event.render_json_line()))?;
    Ok((event_path, stream_path))
}

fn job_snapshot_path(root: &Path, job_id: &str) -> PathBuf {
    root.join(&runtime_layout_config(root).state_dir)
        .join("runtime")
        .join("jobs")
        .join(job_id)
        .join("job.json")
}

fn write_job_snapshot(root: &Path, snapshot: JobSnapshot) -> ShadowResult<()> {
    let jobs_dir = ensure_runtime_jobs_dir(root)?;
    let job_dir = jobs_dir.join(&snapshot.job_id);
    fs::create_dir_all(&job_dir).map_err(io_err)?;
    let job_path = job_dir.join("job.json");
    fs::write(&job_path, render_job_snapshot_json(&snapshot)).map_err(io_err)?;
    let ledger_path = jobs_dir.join("ledger.jsonl");
    append_line(
        &ledger_path,
        &format!(
            "{{\"timestamp\":{},\"job_id\":{},\"status\":{},\"stage\":{},\"queue_bucket\":{},\"agent_id\":{},\"org_id\":{},\"action_type\":{},\"resource\":{},\"updated_at\":{},\"job_path\":{}}}\n",
            json_string(&snapshot.updated_at),
            json_string(&snapshot.job_id),
            json_string(&snapshot.status),
            json_string(&snapshot.stage),
            json_string(&snapshot.queue_bucket),
            json_string(&snapshot.agent_id),
            json_string(&snapshot.org_id),
            json_string(&snapshot.action_type),
            json_string(&snapshot.resource),
            json_string(&snapshot.updated_at),
            json_string(&job_path.display().to_string()),
        ),
    )?;
    Ok(())
}

fn read_job_snapshot(root: &Path, job_id: &str) -> ShadowResult<JobSnapshot> {
    let job_path = job_snapshot_path(root, job_id);
    let contents = fs::read_to_string(&job_path).map_err(io_err)?;
    Ok(JobSnapshot {
        root: root.to_path_buf(),
        job_id: extract_json_string(&contents, "\"job_id\"").unwrap_or_else(|| job_id.to_string()),
        job_path,
        status: extract_json_string(&contents, "\"job_status\"").unwrap_or_default(),
        stage: extract_json_string(&contents, "\"job_stage\"").unwrap_or_default(),
        queue_bucket: extract_json_string(&contents, "\"queue_bucket\"")
            .unwrap_or_else(|| "(none)".to_string()),
        queued_at: extract_json_string(&contents, "\"queued_at\"").unwrap_or_default(),
        updated_at: extract_json_string(&contents, "\"updated_at\"").unwrap_or_default(),
        agent_id: extract_json_string(&contents, "\"agent_id\"").unwrap_or_default(),
        org_id: extract_json_string(&contents, "\"org_id\"").unwrap_or_default(),
        action_type: extract_json_string(&contents, "\"action_type\"").unwrap_or_default(),
        resource: extract_json_string(&contents, "\"resource\"").unwrap_or_default(),
        estimated_cost_usd: extract_json_string(&contents, "\"estimated_cost_usd\"")
            .unwrap_or_else(|| "0.000000".to_string()),
        runtime_outcome: extract_json_string(&contents, "\"runtime_outcome\"")
            .unwrap_or_else(|| "not_started".to_string()),
        budget_reservation_id: extract_json_string(&contents, "\"budget_reservation_id\"")
            .unwrap_or_default(),
        budget_reservation_status: extract_json_string(&contents, "\"budget_reservation_status\"")
            .unwrap_or_else(|| "not_requested".to_string()),
        budget_reservation_reason: extract_json_string(&contents, "\"budget_reservation_reason\"")
            .unwrap_or_default(),
        worker_status: extract_json_string(&contents, "\"worker_status\"")
            .unwrap_or_else(|| "not_started".to_string()),
        queue_path: extract_optional_path(&contents, "\"queue_path\""),
        decision_path: extract_optional_path(&contents, "\"decision_path\""),
        execution_path: extract_optional_path(&contents, "\"execution_path\""),
        event_path: extract_optional_path(&contents, "\"event_path\""),
        event_stream_path: extract_optional_path(&contents, "\"event_stream_path\""),
        audit_log_path: extract_optional_path(&contents, "\"audit_log_path\""),
        parity_report_path: extract_optional_path(&contents, "\"parity_report_path\""),
        reservation_id: extract_json_string(&contents, "\"reservation_id\"").unwrap_or_default(),
        reservation_state: extract_json_string(&contents, "\"reservation_state\"")
            .unwrap_or_else(|| "unknown".to_string()),
        attempt_count: extract_json_string(&contents, "\"attempt_count\"")
            .and_then(|s| s.parse::<u32>().ok())
            .unwrap_or(0),
        note: extract_json_string(&contents, "\"note\"").unwrap_or_default(),
    })
}

fn sanitize_filename(input: &str) -> String {
    input
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || ch == '-' || ch == '_' {
                ch
            } else {
                '-'
            }
        })
        .collect()
}

fn canonical_join_runtime(parts: &[&str]) -> String {
    parts
        .iter()
        .map(|part| sanitize_filename(part))
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join("::")
}

fn load_events(path: &Path) -> ShadowResult<Vec<ShadowEvent>> {
    let contents = fs::read_to_string(path).map_err(io_err)?;
    let mut events = Vec::new();
    for line in contents.lines() {
        let raw = line.trim();
        if raw.is_empty() {
            continue;
        }
        events.push(ShadowEvent {
            hook_name: extract_json_string(raw, "\"hook_name\"")
                .ok_or_else(|| format!("hook_name missing in {}", path.display()))?,
            input_hash: extract_json_string(raw, "\"input_hash\"")
                .ok_or_else(|| format!("input_hash missing in {}", path.display()))?,
            decision: extract_json_string(raw, "\"decision\"")
                .ok_or_else(|| format!("decision missing in {}", path.display()))?,
            agent_id: extract_json_string(raw, "\"agent_id\"")
                .ok_or_else(|| format!("agent_id missing in {}", path.display()))?,
            org_id: extract_json_string(raw, "\"org_id\"")
                .ok_or_else(|| format!("org_id missing in {}", path.display()))?,
        });
    }
    Ok(events)
}

fn extract_json_string(section: &str, key: &str) -> Option<String> {
    let idx = section.find(key)?;
    let after = &section[idx + key.len()..];
    let first_quote = after.find('"')?;
    let rest = &after[first_quote + 1..];
    let end_quote = rest.find('"')?;
    Some(rest[..end_quote].to_string())
}

fn extract_optional_string(section: &str, key: &str) -> Option<String> {
    let idx = section.find(key)?;
    let after = &section[idx + key.len()..];
    let colon = after.find(':')?;
    let rest = after[colon + 1..].trim_start();
    if rest.starts_with("null") {
        return None;
    }
    if !rest.starts_with('"') {
        return None;
    }
    let remainder = &rest[1..];
    let end_quote = remainder.find('"')?;
    Some(remainder[..end_quote].to_string())
}

fn extract_json_bool(section: &str, key: &str) -> Option<bool> {
    let idx = section.find(key)?;
    let after = &section[idx + key.len()..];
    if after.contains("true") {
        Some(true)
    } else if after.contains("false") {
        Some(false)
    } else {
        None
    }
}

fn extract_json_number(section: &str, key: &str) -> Option<f64> {
    let idx = section.find(key)?;
    let after = &section[idx + key.len()..];
    let colon = after.find(':')?;
    let rest = after[colon + 1..].trim_start();
    let end = rest.find([',', '\n', '}']).unwrap_or(rest.len());
    rest[..end].trim().parse::<f64>().ok()
}

fn extract_optional_path(section: &str, key: &str) -> Option<PathBuf> {
    let idx = section.find(key)?;
    let after = &section[idx + key.len()..];
    let colon = after.find(':')?;
    let rest = after[colon + 1..].trim_start();
    if rest.starts_with("null") {
        return None;
    }
    if !rest.starts_with('"') {
        return None;
    }
    let remainder = &rest[1..];
    let end_quote = remainder.find('"')?;
    let value = remainder[..end_quote].trim();
    if value.is_empty() {
        None
    } else {
        Some(PathBuf::from(value))
    }
}

fn json_string(input: &str) -> String {
    format!("{:?}", input)
}

fn render_json_string_array(values: &[String]) -> String {
    let items = values
        .iter()
        .map(|value| json_string(value))
        .collect::<Vec<_>>()
        .join(", ");
    format!("[{}]", items)
}

fn io_err(error: impl std::fmt::Display) -> String {
    error.to_string()
}

fn is_client_disconnect_error(error: &io::Error) -> bool {
    matches!(
        error.kind(),
        ErrorKind::BrokenPipe
            | ErrorKind::ConnectionReset
            | ErrorKind::ConnectionAborted
            | ErrorKind::NotConnected
            | ErrorKind::UnexpectedEof
    )
}

fn display_optional_path(path: Option<&PathBuf>) -> String {
    path.map(|value| value.display().to_string())
        .unwrap_or_else(|| "(not captured)".to_string())
}

fn render_job_snapshot_json(snapshot: &JobSnapshot) -> String {
    format!(
        "    {{\n      \"job_id\": {},\n      \"job_path\": {},\n      \"job_status\": {},\n      \"job_stage\": {},\n      \"queue_bucket\": {},\n      \"queued_at\": {},\n      \"updated_at\": {},\n      \"agent_id\": {},\n      \"org_id\": {},\n      \"action_type\": {},\n      \"resource\": {},\n      \"estimated_cost_usd\": {},\n      \"runtime_outcome\": {},\n      \"budget_reservation_id\": {},\n      \"budget_reservation_status\": {},\n      \"budget_reservation_reason\": {},\n      \"worker_status\": {},\n      \"queue_path\": {},\n      \"decision_path\": {},\n      \"execution_path\": {},\n      \"event_path\": {},\n      \"event_stream_path\": {},\n      \"audit_log_path\": {},\n      \"parity_report_path\": {},\n      \"reservation_id\": {},\n      \"reservation_state\": {},\n      \"attempt_count\": {},\n      \"note\": {}\n    }}",
        json_string(&snapshot.job_id),
        json_string(&snapshot.job_path.display().to_string()),
        json_string(&snapshot.status),
        json_string(&snapshot.stage),
        json_string(&snapshot.queue_bucket),
        json_string(&snapshot.queued_at),
        json_string(&snapshot.updated_at),
        json_string(&snapshot.agent_id),
        json_string(&snapshot.org_id),
        json_string(&snapshot.action_type),
        json_string(&snapshot.resource),
        json_string(&snapshot.estimated_cost_usd),
        json_string(&snapshot.runtime_outcome),
        if snapshot.budget_reservation_id.is_empty() {
            "null".to_string()
        } else {
            json_string(&snapshot.budget_reservation_id)
        },
        json_string(&snapshot.budget_reservation_status),
        json_string(&snapshot.budget_reservation_reason),
        json_string(&snapshot.worker_status),
        snapshot
            .queue_path
            .as_ref()
            .map(|path| json_string(&path.display().to_string()))
            .unwrap_or_else(|| "null".to_string()),
        snapshot
            .decision_path
            .as_ref()
            .map(|path| json_string(&path.display().to_string()))
            .unwrap_or_else(|| "null".to_string()),
        snapshot
            .execution_path
            .as_ref()
            .map(|path| json_string(&path.display().to_string()))
            .unwrap_or_else(|| "null".to_string()),
        snapshot
            .event_path
            .as_ref()
            .map(|path| json_string(&path.display().to_string()))
            .unwrap_or_else(|| "null".to_string()),
        snapshot
            .event_stream_path
            .as_ref()
            .map(|path| json_string(&path.display().to_string()))
            .unwrap_or_else(|| "null".to_string()),
        snapshot
            .audit_log_path
            .as_ref()
            .map(|path| json_string(&path.display().to_string()))
            .unwrap_or_else(|| "null".to_string()),
        snapshot
            .parity_report_path
            .as_ref()
            .map(|path| json_string(&path.display().to_string()))
            .unwrap_or_else(|| "null".to_string()),
        if snapshot.reservation_id.is_empty() {
            "null".to_string()
        } else {
            json_string(&snapshot.reservation_id)
        },
        json_string(&snapshot.reservation_state),
        snapshot.attempt_count,
        json_string(&snapshot.note),
    )
}

fn timestamp_now() -> String {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
        .to_string()
}

fn current_epoch_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::{Signature, Signer, SigningKey};
    use loom_core::wasm_host::{
        builtin_system_info_guest_bytes, render_wasm_system_info_request_json,
        WasmSystemInfoRequest,
    };
    use loom_core::{init_workspace, ActionEnvelope, AgentIdentityResolution};
    use loom_poge::KernelWarrant;
    use sha2::{Digest, Sha256};

    #[test]
    fn records_preflight_and_renders_report() {
        let root = temp_path("loom-shadow-capture");
        ensure_shadow_dir(&root).expect("shadow dir");
        let identity = sample_identity();
        let envelope = sample_envelope();
        let reference = ReferenceGateCheck {
            allowed: true,
            stage: "ok".to_string(),
            reason: "ok".to_string(),
            restrictions: vec![],
            sanction_gate_decision: "allow".to_string(),
            approval_gate_decision: "allow".to_string(),
            budget_gate_decision: "allow".to_string(),
            source: "kernel_reference_adapter_read_only".to_string(),
        };

        let capture =
            capture_preflight(&root, &root, &identity, &envelope, &reference).expect("capture");
        assert!(capture.event_log.exists());
        assert!(capture.audit_preview_log.exists());
        assert!(capture.reference_report.exists());
        assert!(capture.reference_event_log.exists());
        assert_eq!(capture.sanction_decision, "clear");
        assert_eq!(capture.sanction_gate_decision, "allow");
        assert_eq!(capture.identity_restrictions, Vec::<String>::new());
        assert_eq!(capture.reference_restrictions, Vec::<String>::new());
        assert_eq!(capture.budget_gate_decision, "allow");
        assert_eq!(capture.approval_decision, "not_required");
        assert_eq!(capture.approval_gate_decision, "allow");
        assert_eq!(capture.audit_emission_decision, "local_preview_written");
        assert_eq!(capture.overall_decision, "allow");
        let human = render_preflight_human(&capture);
        assert!(human.contains("CAPABILITY READINESS"));
        assert!(human.contains("capability readiness skipped"));
        let report = render_shadow_report(&root).expect("report");
        assert!(report.contains("preflight_captured"));
        assert!(report.contains("budget_gate"));
        assert!(report.contains("audit_preview_log"));
        assert!(report.contains("reference_report"));
    }

    #[test]
    fn decision_capture_surfaces_gate_outcome() {
        let root = temp_path("loom-shadow-decision");
        ensure_shadow_dir(&root).expect("shadow dir");
        let identity = sample_identity();
        let envelope = sample_envelope();
        let reference = ReferenceGateCheck {
            allowed: false,
            stage: "budget_gate".to_string(),
            reason: "runway below reserve floor".to_string(),
            restrictions: vec!["execute".to_string()],
            sanction_gate_decision: "allow".to_string(),
            approval_gate_decision: "allow".to_string(),
            budget_gate_decision: "deny".to_string(),
            source: "kernel_reference_adapter_read_only".to_string(),
        };

        let capture = capture_decision(&root, &identity, &envelope, &reference).expect("decision");
        assert!(capture.decision_path.exists());
        assert_eq!(capture.overall_decision, "deny");
        assert!(capture.identity_restrictions.is_empty());
        assert_eq!(capture.reference_restrictions, vec!["execute".to_string()]);
        assert!(capture.local_sanction_allowed);
        assert_eq!(capture.local_sanction_decision, "allow");
        assert_eq!(capture.effective_source, "reference_gate");
        assert_eq!(capture.effective_stage, "budget_gate");
        assert_eq!(capture.reference_stage, "budget_gate");
        let human = render_decision_human(&capture);
        assert!(human.contains("overall_decision:       deny"));
        assert!(human.contains("identity_restrictions:  (none)"));
        assert!(human.contains("reference_restrictions: execute"));
        assert!(human.contains("effective_source:       reference_gate"));
        assert!(human.contains("reference_stage:        budget_gate"));
        let json = render_decision_json(&capture);
        assert!(json.contains("\"status\": \"decision_captured\""));
        assert!(json.contains("\"identity_restrictions\": []"));
        assert!(json.contains("\"reference_restrictions\": [\"execute\"]"));
        assert!(json.contains("\"overall_decision\": \"deny\""));
        assert!(json.contains(
            "\"note\": \"experimental preflight decision only; not governed runtime enforcement\""
        ));
        assert_eq!(decision_exit_code(&capture, 0, 2), 2);
        let report = render_shadow_report(&root).expect("render report");
        assert!(report.contains("Decision artifact"));
        assert!(report.contains("\"overall_decision\": \"deny\""));
    }

    #[test]
    fn decision_capture_prefers_local_sanction_preview_when_execute_is_restricted() {
        let root = temp_path("loom-shadow-decision-sanction");
        ensure_shadow_dir(&root).expect("shadow dir");
        let mut identity = sample_identity();
        identity.restrictions = vec!["execute".to_string()];
        identity.sanction_decision = "restricted_execute".to_string();
        let envelope = sample_envelope();
        let reference = ReferenceGateCheck {
            allowed: true,
            stage: "ok".to_string(),
            reason: "ok".to_string(),
            restrictions: vec!["execute".to_string()],
            sanction_gate_decision: "allow".to_string(),
            approval_gate_decision: "allow".to_string(),
            budget_gate_decision: "allow".to_string(),
            source: "kernel_reference_adapter_read_only".to_string(),
        };

        let capture = capture_decision(&root, &identity, &envelope, &reference).expect("decision");
        assert_eq!(capture.overall_decision, "hard_deny");
        assert_eq!(capture.identity_restrictions, vec!["execute".to_string()]);
        assert_eq!(capture.reference_restrictions, vec!["execute".to_string()]);
        assert!(!capture.local_sanction_allowed);
        assert_eq!(capture.local_sanction_decision, "deny");
        assert_eq!(capture.effective_source, "sanction_enforcement");
        assert_eq!(capture.effective_stage, "sanction_controls");
        assert!(capture.effective_reason.contains("restricted"));
        assert_eq!(decision_exit_code(&capture, 0, 2), 2);
    }

    #[test]
    fn compares_identical_logs_without_divergence() {
        let root = temp_path("loom-shadow-compare");
        let shadow_dir = ensure_shadow_dir(&root).expect("shadow dir");
        fs::create_dir_all(&shadow_dir).expect("shadow dir");
        let log_a = shadow_dir.join("primary.jsonl");
        let log_b = shadow_dir.join("shadow.jsonl");
        let line = "{\"hook_name\":\"agent_identity\",\"input_hash\":\"abc\",\"decision\":\"resolved\",\"agent_id\":\"agent_atlas\",\"org_id\":\"org_demo\"}\n";
        fs::write(&log_a, line).expect("write primary");
        fs::write(&log_b, line).expect("write shadow");

        let summary = compare_logs(Some(&root), &log_a, &log_b).expect("compare");
        assert_eq!(summary.matches, 1);
        assert_eq!(summary.divergences, 0);
        assert_eq!(summary.hook_results.len(), 1);
        assert!(summary.hook_results[0].matched);
        let report = render_shadow_report(&root).expect("render report");
        assert!(report.contains("comparison_complete"));
        assert!(report.contains("\"hook_results\""));
    }

    #[test]
    fn compare_report_surfaces_hook_level_divergence_details() {
        let root = temp_path("loom-shadow-divergence");
        let shadow_dir = ensure_shadow_dir(&root).expect("shadow dir");
        fs::create_dir_all(&shadow_dir).expect("shadow dir");
        let primary = shadow_dir.join("primary.jsonl");
        let shadow = shadow_dir.join("shadow.jsonl");
        fs::write(
            &primary,
            "{\"hook_name\":\"audit_emission\",\"input_hash\":\"abc\",\"decision\":\"not_exercised\",\"agent_id\":\"agent_atlas\",\"org_id\":\"org_demo\"}\n",
        )
        .expect("write primary");
        fs::write(
            &shadow,
            "{\"hook_name\":\"audit_emission\",\"input_hash\":\"abc\",\"decision\":\"kernel_preview_written\",\"agent_id\":\"agent_atlas\",\"org_id\":\"org_demo\"}\n",
        )
        .expect("write shadow");

        let summary = compare_logs(Some(&root), &primary, &shadow).expect("compare");
        assert_eq!(summary.matches, 0);
        assert_eq!(summary.divergences, 1);
        assert_eq!(summary.hook_results.len(), 1);
        assert_eq!(summary.hook_results[0].hook_name, "audit_emission");
        assert!(!summary.hook_results[0].matched);
        let human = render_compare_human(&summary);
        assert!(human.contains("Divergence details"));
        assert!(human.contains("[0] audit_emission | primary=not_exercised | shadow=kernel_preview_written | input=abc"));
        let json = render_compare_json(&summary);
        assert!(json.contains("\"hook_results\""));
        assert!(json.contains("\"shadow_decision\":\"kernel_preview_written\""));
    }

    #[test]
    fn runtime_execution_capture_writes_runtime_and_parity_artifacts() {
        let root = temp_path("loom-shadow-runtime");
        ensure_shadow_dir(&root).expect("shadow dir");
        let identity = sample_identity();
        let envelope = sample_envelope();
        let reference = ReferenceGateCheck {
            allowed: true,
            stage: "ok".to_string(),
            reason: "ok".to_string(),
            restrictions: vec![],
            sanction_gate_decision: "allow".to_string(),
            approval_gate_decision: "allow".to_string(),
            budget_gate_decision: "allow".to_string(),
            source: "kernel_reference_adapter_read_only".to_string(),
        };

        let decision = capture_decision(&root, &identity, &envelope, &reference).expect("decision");
        let capture = capture_runtime_execution(&root, &root, &envelope, &reference, &decision)
            .expect("runtime capture");

        assert!(capture.execution_path.exists());
        assert!(capture.worker_request_path.exists());
        assert!(capture.worker_result_path.exists());
        assert!(capture.worker_log_path.exists());
        assert!(capture.audit_log_path.exists());
        assert!(capture.runtime_event_path.exists());
        assert!(capture.runtime_event_stream_path.exists());
        assert!(capture.parity_stream_path.exists());
        assert!(capture.parity_report_path.exists());
        assert_eq!(capture.runtime_outcome, "worker_executed");
        assert_eq!(capture.worker_status, "completed");
        assert_eq!(capture.reference_decision, "allow");
        assert_eq!(capture.parity_status, "match");

        let human = render_runtime_execution_human(&capture);
        assert!(human.contains("Meridian Loom // RUNTIME EXECUTE"));
        assert!(human.contains("phase:       experimental runtime rehearsal"));
        assert!(human.contains("worker supervisor artifacts"));
        assert!(human.contains("proof / audit / parity artifacts"));
        assert!(human.contains("runtime_event:"));
        assert!(human.contains("loom parity report --root"));
        let json = render_runtime_execution_json(&capture);
        assert!(json.contains("\"status\": \"runtime_execution_captured\""));
        assert!(json.contains("\"runtime_event_path\":"));
        assert!(json.contains("\"worker_status\": \"completed\""));
        assert!(json.contains("\"reference_probe_status\":"));
        let parity = render_parity_report(&root).expect("parity report");
        assert!(parity.contains("Meridian Loom // PARITY REPORT"));
        assert!(parity.contains("Reference action latest"));
        assert!(parity.contains("Action parity latest"));
        assert!(parity.contains("Action parity stream"));
        assert!(parity.contains("Action parity summary"));
        assert!(parity.contains("Runtime event latest"));
        assert!(parity.contains("Reference probe stream"));
        assert!(parity.contains("\"parity_status\": \"match\""));
    }

    #[test]
    fn test_generate_capture_ids() {
        let capture = RuntimeExecutionCapture {
            execution_path: PathBuf::new(),
            runtime_event_path: PathBuf::new(),
            runtime_event_stream_path: PathBuf::new(),
            worker_request_path: PathBuf::new(),
            worker_result_path: PathBuf::new(),
            worker_log_path: PathBuf::new(),
            audit_log_path: PathBuf::new(),
            parity_stream_path: PathBuf::new(),
            parity_report_path: PathBuf::new(),
            reference_probe_path: None,
            reference_probe_stream_path: None,
            decision_path: PathBuf::new(),
            input_hash: "test_hash".to_string(),
            agent_id: "agent_test".to_string(),
            org_id: "org_test".to_string(),
            action_type: "action_test".to_string(),
            resource: "resource_test".to_string(),
            estimated_cost_usd: 0.0,
            runtime_outcome: "outcome_test".to_string(),
            budget_reservation_id: "".to_string(),
            budget_reservation_status: "".to_string(),
            budget_reservation_reason: "".to_string(),
            worker_status: "".to_string(),
            worker_kind: "".to_string(),
            worker_note: "".to_string(),
            overall_decision: "decision_test".to_string(),
            effective_source: "".to_string(),
            effective_stage: "stage_test".to_string(),
            reference_decision: "".to_string(),
            reference_stage: "".to_string(),
            audit_emission_status: "".to_string(),
            economy_hook_status: "".to_string(),
            reference_probe_status: "".to_string(),
            reference_probe_note: "".to_string(),
            parity_status: "parity_test".to_string(),
            parity_reason: "".to_string(),
        };

        let ids = generate_capture_ids(&capture);
        assert!(ids.job_id.starts_with("job::"));
        assert!(ids.execution_id.starts_with("execution::"));
        assert!(ids.decision_id.starts_with("decision::"));
        assert!(ids.parity_id.starts_with("parity::"));
        assert!(ids.audit_id.starts_with("audit::"));
        assert!(ids.subject_id.starts_with("envelope::"));
        assert!(
            ids.source_event_id.starts_with("loom_runtime_v1::")
                || ids.source_event_id.starts_with("loom.runtime.v1::")
        );
    }

    #[test]
    fn runtime_execution_respects_sanction_deny_without_dispatch() {
        let root = temp_path("loom-shadow-runtime-sanction-deny");
        ensure_shadow_dir(&root).expect("shadow dir");
        let mut identity = sample_identity();
        identity.restrictions = vec!["execute".to_string()];
        identity.sanction_decision = "restricted_execute".to_string();
        let envelope = sample_envelope();
        let reference = ReferenceGateCheck {
            allowed: true,
            stage: "ok".to_string(),
            reason: "ok".to_string(),
            restrictions: vec!["execute".to_string()],
            sanction_gate_decision: "allow".to_string(),
            approval_gate_decision: "allow".to_string(),
            budget_gate_decision: "allow".to_string(),
            source: "kernel_reference_adapter_read_only".to_string(),
        };

        let decision = capture_decision(&root, &identity, &envelope, &reference).expect("decision");
        let capture = capture_runtime_execution(&root, &root, &envelope, &reference, &decision)
            .expect("runtime capture");

        assert_eq!(capture.runtime_outcome, "denied");
        assert_eq!(capture.worker_status, "not_dispatched");
        assert_eq!(capture.effective_stage, "sanction_controls");
        assert_eq!(capture.budget_reservation_status, "decision_denied");
        let human = render_runtime_execution_human(&capture);
        assert!(human.contains("runtime_outcome:     denied"));
        assert!(human.contains("budget_reservation:  decision_denied"));
        assert!(human.contains("effective_stage:     sanction_controls"));
    }

    #[test]
    fn shadow_report_deprioritizes_stale_not_started_marker_when_runtime_exists() {
        let root = temp_path("loom-shadow-stale-latest");
        let shadow_dir = ensure_shadow_dir(&root).expect("shadow dir");
        let runtime_dir = ensure_runtime_dir(&root).expect("runtime dir");
        let parity_dir = ensure_parity_dir(&root).expect("parity dir");
        fs::write(
            shadow_dir.join("latest.json"),
            "{\n  \"status\": \"not_started\",\n  \"note\": \"shadow mode is not implemented in this scaffold\"\n}\n",
        )
        .expect("write latest");
        fs::write(
            runtime_dir.join("last_execution.json"),
            "{\n  \"status\": \"runtime_execution_captured\"\n}\n",
        )
        .expect("write runtime");
        fs::write(
            parity_dir.join("latest.json"),
            "{\n  \"status\": \"parity_report_captured\"\n}\n",
        )
        .expect("write parity");

        let report = render_shadow_report(&root).expect("render report");
        let runtime_index = report.find("Runtime execution").expect("runtime section");
        let legacy_index = report.find("Legacy shadow marker").expect("legacy section");
        assert!(runtime_index < legacy_index);
        assert!(report.contains(
            "the runtime execution and parity sections above are the newer operator surfaces"
        ));
    }

    #[test]
    fn shadow_report_guides_next_steps_when_only_legacy_marker_exists() {
        let root = temp_path("loom-shadow-guidance");
        let shadow_dir = ensure_shadow_dir(&root).expect("shadow dir");
        fs::write(
            shadow_dir.join("latest.json"),
            "{\n  \"status\": \"not_started\",\n  \"note\": \"shadow mode is not implemented in this scaffold\"\n}\n",
        )
        .expect("write latest");

        let report = render_shadow_report(&root).expect("render report");
        assert!(report.contains("Current state"));
        assert!(report.contains("Recommended next step"));
        assert!(report.contains("loom shadow preflight"));
        assert!(report.contains(
            "meaning:     no shadow or runtime rehearsal artifacts have been captured yet"
        ));
    }

    #[test]
    fn parity_report_guides_next_steps_when_no_artifacts_exist() {
        let root = temp_path("loom-parity-guidance");
        ensure_parity_dir(&root).expect("parity dir");

        let report = render_parity_report(&root).expect("render parity");
        assert!(report.contains("Current state"));
        assert!(report.contains("status:      not_started"));
        assert!(report.contains("loom action execute"));
        assert!(report.contains("loom shadow report"));
    }

    #[test]
    fn shadow_backend_plugin_registry_covers_all_backends() {
        let cases = [
            ShadowBackendKind::Wasmtime,
            ShadowBackendKind::Command,
            ShadowBackendKind::Http,
            ShadowBackendKind::Mcp,
            ShadowBackendKind::A2a,
            ShadowBackendKind::A2aAction,
            ShadowBackendKind::GrpcAction,
            ShadowBackendKind::GrpcPhysical,
        ];
        for case in cases.iter() {
            let plugin = resolve_shadow_backend_plugin(case);
            assert_eq!(plugin.id(), case.as_str());
        }
    }

    #[test]
    fn enqueue_action_writes_pending_queue_artifact() {
        let root = temp_path("loom-shadow-enqueue");
        fs::create_dir_all(&root).expect("root");
        let envelope = sample_envelope();

        let capture =
            enqueue_action(&root, Path::new("/tmp/meridian-kernel"), &envelope).expect("enqueue");
        assert!(capture.queue_path.exists());
        assert!(capture.job_path.exists());
        let queued = fs::read_to_string(&capture.queue_path).expect("queued file");
        assert!(queued.contains("\"status\": \"queued\""));
        assert!(queued.contains("\"agent_id\": \"agent_atlas\""));
        assert!(queued.contains("\"kernel_path\": \"/tmp/meridian-kernel\""));
        let job = fs::read_to_string(&capture.job_path).expect("job file");
        assert!(job.contains("\"job_status\": \"queued\""));
        assert!(job.contains("\"queue_bucket\": \"pending:standard\""));
    }

    #[test]
    fn job_list_and_inspect_surface_runtime_owned_state() {
        let root = temp_path("loom-shadow-job-ledger");
        fs::create_dir_all(&root).expect("root");
        let kernel_root = temp_path("loom-shadow-job-ledger-kernel");
        let kernel_dir = kernel_root.join("kernel");
        fs::create_dir_all(kernel_dir.join("adapters")).expect("kernel dirs");
        fs::write(
            kernel_dir.join("runtimes.json"),
            "{\n  \"runtimes\": {\n    \"local_kernel\": {\"id\": \"local_kernel\", \"label\": \"Local Kernel Runtime\"},\n    \"loom_native\": {\"status\": \"experimental\", \"notes\": \"job fixture\", \"contract_compliance\": {\"agent_identity\": null, \"action_envelope\": null, \"cost_attribution\": null, \"approval_hook\": null, \"audit_emission\": null, \"sanction_controls\": null, \"budget_gate\": null}}\n  }\n}\n",
        )
        .expect("write runtimes");
        fs::write(
            kernel_dir.join("agent_registry.py"),
            "import json, sys\nagent_id = sys.argv[sys.argv.index('--agent_id') + 1]\norg_id = sys.argv[sys.argv.index('--org_id') + 1] if '--org_id' in sys.argv else 'org_demo'\nprint(json.dumps({'id': agent_id, 'name': 'Atlas', 'org_id': org_id, 'role': 'analyst', 'economy_key': 'atlas', 'approval_required': False, 'budget': {'max_per_run_usd': 0.5}, 'runtime_binding': {'runtime_id': 'local_kernel', 'runtime_label': 'Local Kernel Runtime', 'bound_org_id': org_id, 'boundary_name': 'workspace', 'identity_model': 'session', 'runtime_registered': True, 'registration_status': 'registered'}}, indent=2))\n",
        )
        .expect("write registry");
        fs::write(
            kernel_dir.join("court.py"),
            "def get_restrictions(agent_id, org_id=None):\n    return []\n",
        )
        .expect("write court");
        fs::write(
            kernel_dir.join("authority.py"),
            "def check_authority(agent_id, action, org_id=None):\n    return True, 'ok'\n",
        )
        .expect("write authority");
        fs::write(
            kernel_dir.join("treasury.py"),
            "def check_budget(agent_id, cost_usd, org_id=None):\n    return True, 'ok'\n",
        )
        .expect("write treasury");
        fs::write(
            kernel_dir.join("audit.py"),
            "def log_event(*args, **kwargs):\n    return 'evt_jobs'\n",
        )
        .expect("write audit");
        fs::write(kernel_dir.join("adapters/__init__.py"), "").expect("write adapter init");
        fs::write(
            kernel_dir.join("adapters/meridian_compatible.py"),
            "def pre_action_check(org_id, envelope):\n    return {'allowed': True, 'stage': 'ok', 'reason': 'ok', 'restrictions': []}\n",
        )
        .expect("write adapter");
        init_workspace(
            &root,
            "embedded",
            Some(kernel_root.to_string_lossy().as_ref()),
            "org_demo",
        )
        .expect("init workspace");
        let envelope = sample_envelope();
        let capture = enqueue_action(&root, &kernel_root, &envelope).expect("enqueue");
        let queued = inspect_job(&root, &capture.input_hash).expect("queued job");
        assert_eq!(queued.status, "queued");
        assert_eq!(queued.queue_bucket, "pending:standard");
        let queued_human = render_job_inspect_human(&queued);
        assert!(queued_human.contains("JOB INSPECT"));

        run_supervisor(&root, Some(kernel_root.to_string_lossy().as_ref()), 1).expect("supervisor");
        let jobs = list_jobs(&root, None, 10).expect("job list");
        assert_eq!(jobs.len(), 1);
        assert_eq!(jobs[0].status, "completed");
        assert_eq!(jobs[0].queue_bucket, "processed:standard");
        assert!(jobs[0].execution_path.is_some());
        let list_human = render_job_list_human(&root, &jobs, None);
        assert!(list_human.contains("experimental runtime-owned job ledger"));
        assert!(list_human.contains("status=completed"));
    }

    #[test]
    fn supervisor_run_processes_pending_queue_and_uses_kernel_runtime_audit_path() {
        let root = temp_path("loom-shadow-supervisor");
        fs::create_dir_all(&root).expect("root");
        let kernel_root = temp_path("loom-shadow-supervisor-kernel");
        let kernel_dir = kernel_root.join("kernel");
        fs::create_dir_all(&kernel_dir).expect("kernel dir");
        fs::write(
            kernel_dir.join("runtimes.json"),
            "{\n  \"runtimes\": {\n    \"local_kernel\": {\"id\": \"local_kernel\", \"label\": \"Local Kernel Runtime\"},\n    \"loom_native\": {\"status\": \"experimental\", \"notes\": \"test note\", \"contract_compliance\": {\"agent_identity\": null, \"action_envelope\": null, \"cost_attribution\": null, \"approval_hook\": null, \"audit_emission\": null, \"sanction_controls\": null, \"budget_gate\": null}}\n  }\n}\n",
        )
        .expect("write runtimes");
        fs::write(
            kernel_dir.join("agent_registry.py"),
            "import json, sys\nagent_id = sys.argv[sys.argv.index('--agent_id') + 1]\norg_id = sys.argv[sys.argv.index('--org_id') + 1] if '--org_id' in sys.argv else 'org_demo'\nprint(json.dumps({'id': agent_id, 'name': 'Atlas', 'org_id': org_id, 'role': 'analyst', 'economy_key': 'atlas', 'approval_required': False, 'budget': {'max_per_run_usd': 0.5}, 'runtime_binding': {'runtime_id': 'local_kernel', 'runtime_label': 'Local Kernel Runtime', 'bound_org_id': org_id, 'boundary_name': 'workspace', 'identity_model': 'session', 'runtime_registered': True, 'registration_status': 'registered'}}, indent=2))\n",
        )
        .expect("write agent registry");
        fs::write(
            kernel_dir.join("court.py"),
            "def get_restrictions(agent_id, org_id=None):\n    return []\n",
        )
        .expect("write court");
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
        let adapters_dir = kernel_dir.join("adapters");
        fs::create_dir_all(&adapters_dir).expect("adapters dir");
        fs::write(adapters_dir.join("__init__.py"), "").expect("write adapters init");
        fs::write(
            adapters_dir.join("meridian_compatible.py"),
            "import treasury\n\ndef pre_action_check(org_id, envelope):\n    allowed, reason = treasury.check_budget(envelope.get('agent_id'), float(envelope.get('estimated_cost_usd', 0.0)), org_id)\n    if not allowed:\n        return {'allowed': False, 'stage': 'budget_gate', 'reason': reason, 'restrictions': []}\n    return {'allowed': True, 'stage': 'ok', 'reason': 'ok', 'restrictions': []}\n",
        )
        .expect("write adapter");
        fs::write(
            kernel_dir.join("audit.py"),
            r#"#!/usr/bin/env python3
import argparse
import datetime
import json
import os
import uuid

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
RUNTIME_AUDIT_FILE = os.path.join(PLATFORM_DIR, "runtime_audit", "loom_runtime_events.jsonl")

def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

def log_event(org_id, agent_id, action, resource='', outcome='success', details=None, policy_ref='', session_id=None, audit_file=None):
    audit_file = audit_file or RUNTIME_AUDIT_FILE
    os.makedirs(os.path.dirname(audit_file), exist_ok=True)
    event = {
        'id': f'evt_{uuid.uuid4().hex[:10]}',
        'timestamp': _now(),
        'org_id': org_id,
        'agent_id': agent_id,
        'action': action,
        'resource': resource,
        'outcome': outcome,
        'details': details or {},
        'policy_ref': policy_ref,
    }
    if session_id:
        event['session_id'] = session_id
    with open(audit_file, 'a', encoding='utf-8') as handle:
        handle.write(json.dumps(event) + '\n')

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command')
    runtime = sub.add_parser('log-runtime')
    runtime.add_argument('--org_id', required=True)
    runtime.add_argument('--agent_id', default='')
    runtime.add_argument('--action', required=True)
    runtime.add_argument('--resource', default='')
    runtime.add_argument('--outcome', required=True)
    runtime.add_argument('--input_hash', required=True)
    runtime.add_argument('--estimated_cost_usd', type=float, required=True)
    runtime.add_argument('--effective_source', required=True)
    runtime.add_argument('--effective_stage', required=True)
    runtime.add_argument('--reference_stage', required=True)
    runtime.add_argument('--runtime_outcome', required=True)
    runtime.add_argument('--worker_status', default='')
    runtime.add_argument('--worker_kind', default='')
    runtime.add_argument('--parity_status', default='')
    runtime.add_argument('--session_id', default=None)
    args = parser.parse_args()
    log_event(
        args.org_id,
        args.agent_id,
        args.action,
        resource=args.resource,
        outcome=args.outcome,
        details={
            'source': 'loom_runtime_execute',
            'input_hash': args.input_hash,
            'estimated_cost_usd': args.estimated_cost_usd,
            'effective_source': args.effective_source,
            'effective_stage': args.effective_stage,
            'reference_stage': args.reference_stage,
            'runtime_outcome': args.runtime_outcome,
            'worker_status': args.worker_status,
            'worker_kind': args.worker_kind,
            'parity_status': args.parity_status,
            'experimental': True,
        },
        policy_ref='experimental_runtime_rehearsal',
        session_id=args.session_id,
    )

if __name__ == '__main__':
    main()
"#,
        )
        .expect("write audit");
        init_workspace(
            &root,
            "embedded",
            Some(kernel_root.to_string_lossy().as_ref()),
            "org_demo",
        )
        .expect("init workspace");
        let envelope = sample_envelope();
        enqueue_action(&root, &kernel_root, &envelope).expect("enqueue");

        let summary = run_supervisor(&root, Some(kernel_root.to_string_lossy().as_ref()), 1)
            .expect("supervisor");
        assert_eq!(summary.processed, 1);
        assert_eq!(summary.allowed, 1);
        assert_eq!(
            summary.audit_log_path,
            kernel_root
                .join("kernel")
                .join("runtime_audit")
                .join("loom_runtime_events.jsonl")
        );
        assert!(summary.audit_log_path.exists());
        assert!(summary.last_execution_path.exists());
        let runtime_dir = ensure_runtime_dir(&root).expect("runtime dir");
        let pending_dir = runtime_dir.join("queue/pending");
        let processed_dir = runtime_dir.join("queue/processed");
        assert_eq!(
            count_json_files_recursive(&pending_dir).expect("pending dir"),
            0
        );
        assert_eq!(
            fs::read_dir(&processed_dir).expect("processed dir").count(),
            1
        );
        let human = render_supervisor_run_human(&summary);
        assert!(human.contains("experimental local queue supervisor"));
    }

    #[test]
    fn supervisor_watch_writes_heartbeat_and_status() {
        let root = temp_path("loom-shadow-watch");
        fs::create_dir_all(&root).expect("root");
        let kernel = temp_path("loom-shadow-watch-kernel");
        let kernel_dir = kernel.join("kernel");
        fs::create_dir_all(kernel_dir.join("adapters")).expect("kernel dirs");
        fs::write(
            kernel_dir.join("runtimes.json"),
            "{\n  \"runtimes\": {\n    \"local_kernel\": {\"id\": \"local_kernel\", \"label\": \"Local Kernel Runtime\"},\n    \"loom_native\": {\"status\": \"experimental\", \"notes\": \"watch fixture\", \"contract_compliance\": {\"agent_identity\": null, \"action_envelope\": null, \"cost_attribution\": null, \"approval_hook\": null, \"audit_emission\": null, \"sanction_controls\": null, \"budget_gate\": null}}\n  }\n}\n",
        )
        .expect("write runtimes");
        fs::write(
            kernel_dir.join("agent_registry.py"),
            "import json, sys\nagent_id = sys.argv[sys.argv.index('--agent_id') + 1]\norg_id = sys.argv[sys.argv.index('--org_id') + 1] if '--org_id' in sys.argv else 'org_demo'\nprint(json.dumps({'id': agent_id, 'name': 'Atlas', 'org_id': org_id, 'role': 'analyst', 'economy_key': 'atlas', 'approval_required': False, 'budget': {'max_per_run_usd': 0.5}, 'runtime_binding': {'runtime_id': 'local_kernel', 'runtime_label': 'Local Kernel Runtime', 'bound_org_id': org_id, 'boundary_name': 'workspace', 'identity_model': 'session', 'runtime_registered': True, 'registration_status': 'registered'}}, indent=2))\n",
        )
        .expect("write registry");
        fs::write(
            kernel_dir.join("court.py"),
            "def get_restrictions(agent_id, org_id=None):\n    return []\n",
        )
        .expect("write court");
        fs::write(
            kernel_dir.join("authority.py"),
            "def check_authority(agent_id, action, org_id=None):\n    return True, 'ok'\n",
        )
        .expect("write authority");
        fs::write(
            kernel_dir.join("treasury.py"),
            "def check_budget(agent_id, cost_usd, org_id=None):\n    return True, 'ok'\n",
        )
        .expect("write treasury");
        fs::write(
            kernel_dir.join("audit.py"),
            "def log_event(*args, **kwargs):\n    return 'evt_watch'\n",
        )
        .expect("write audit");
        fs::write(kernel_dir.join("adapters/__init__.py"), "").expect("write adapter init");
        fs::write(
            kernel_dir.join("adapters/meridian_compatible.py"),
            "def pre_action_check(org_id, envelope):\n    return {'allowed': True, 'stage': 'ok', 'reason': 'ok', 'restrictions': []}\n",
        )
        .expect("write adapter");
        init_workspace(
            &root,
            "embedded",
            Some(kernel.to_string_lossy().as_ref()),
            "org_demo",
        )
        .expect("init workspace");
        let envelope = sample_envelope();
        enqueue_action(&root, &kernel, &envelope).expect("enqueue");

        let summary = watch_supervisor(&root, Some(kernel.to_string_lossy().as_ref()), 1, 2, 0)
            .expect("watch supervisor");
        assert_eq!(summary.iterations, 2);
        assert_eq!(summary.processed, 1);
        assert!(summary.heartbeat_log_path.exists());
        assert!(summary.status_path.exists());
        let status = fs::read_to_string(&summary.status_path).expect("status");
        assert!(status.contains("\"status\": \"watch_complete\""));
        let heartbeat = fs::read_to_string(&summary.heartbeat_log_path).expect("heartbeat");
        assert!(heartbeat.contains("\"iteration\":1"));
        assert!(heartbeat.contains("\"iteration\":2"));
        let human = render_supervisor_watch_human(&summary);
        assert!(human.contains("experimental local queue supervisor loop"));
    }

    #[test]
    fn supervisor_status_reads_written_artifacts() {
        let root = temp_path("loom-shadow-supervisor-status");
        fs::create_dir_all(&root).expect("root");
        let kernel = temp_path("loom-shadow-supervisor-status-kernel");
        let kernel_dir = kernel.join("kernel");
        fs::create_dir_all(kernel_dir.join("adapters")).expect("kernel dirs");
        fs::write(
            kernel_dir.join("runtimes.json"),
            "{\n  \"runtimes\": {\n    \"local_kernel\": {\"id\": \"local_kernel\", \"label\": \"Local Kernel Runtime\"},\n    \"loom_native\": {\"status\": \"experimental\", \"notes\": \"status fixture\", \"contract_compliance\": {\"agent_identity\": null, \"action_envelope\": null, \"cost_attribution\": null, \"approval_hook\": null, \"audit_emission\": null, \"sanction_controls\": null, \"budget_gate\": null}}\n  }\n}\n",
        )
        .expect("write runtimes");
        fs::write(
            kernel_dir.join("agent_registry.py"),
            "import json, sys\nagent_id = sys.argv[sys.argv.index('--agent_id') + 1]\norg_id = sys.argv[sys.argv.index('--org_id') + 1] if '--org_id' in sys.argv else 'org_demo'\nprint(json.dumps({'id': agent_id, 'name': 'Atlas', 'org_id': org_id, 'role': 'analyst', 'economy_key': 'atlas', 'approval_required': False, 'budget': {'max_per_run_usd': 0.5}, 'runtime_binding': {'runtime_id': 'local_kernel', 'runtime_label': 'Local Kernel Runtime', 'bound_org_id': org_id, 'boundary_name': 'workspace', 'identity_model': 'session', 'runtime_registered': True, 'registration_status': 'registered'}}, indent=2))\n",
        )
        .expect("write registry");
        fs::write(
            kernel_dir.join("court.py"),
            "def get_restrictions(agent_id, org_id=None):\n    return []\n",
        )
        .expect("write court");
        fs::write(
            kernel_dir.join("authority.py"),
            "def check_authority(agent_id, action, org_id=None):\n    return True, 'ok'\n",
        )
        .expect("write authority");
        fs::write(
            kernel_dir.join("treasury.py"),
            "def check_budget(agent_id, cost_usd, org_id=None):\n    return True, 'ok'\n",
        )
        .expect("write treasury");
        fs::write(
            kernel_dir.join("audit.py"),
            "def log_event(*args, **kwargs):\n    return 'evt_status'\n",
        )
        .expect("write audit");
        fs::write(kernel_dir.join("adapters/__init__.py"), "").expect("write adapter init");
        fs::write(
            kernel_dir.join("adapters/meridian_compatible.py"),
            "def pre_action_check(org_id, envelope):\n    return {'allowed': True, 'stage': 'ok', 'reason': 'ok', 'restrictions': []}\n",
        )
        .expect("write adapter");
        init_workspace(
            &root,
            "embedded",
            Some(kernel.to_string_lossy().as_ref()),
            "org_demo",
        )
        .expect("init workspace");
        let envelope = sample_envelope();
        enqueue_action(&root, &kernel, &envelope).expect("enqueue");
        watch_supervisor(&root, Some(kernel.to_string_lossy().as_ref()), 1, 2, 0)
            .expect("watch supervisor");

        let snapshot = supervisor_status(&root).expect("status");
        assert!(snapshot.available);
        assert_eq!(snapshot.processed, 1);
        assert_eq!(snapshot.allowed, 1);
        assert_eq!(snapshot.heartbeat_entries, 2);
        assert_eq!(snapshot.pending_jobs, 0);
        let human = render_supervisor_status_human(&snapshot);
        assert!(human.contains("SUPERVISOR STATUS"));
        assert!(human.contains("bounded local loop state is real"));
    }

    #[test]
    fn daemon_loop_writes_runtime_state_and_status() {
        let root = temp_path("loom-shadow-daemon-loop");
        fs::create_dir_all(&root).expect("root");
        let kernel = temp_path("loom-shadow-daemon-kernel");
        let kernel_dir = kernel.join("kernel");
        fs::create_dir_all(kernel_dir.join("adapters")).expect("kernel dirs");
        fs::write(
            kernel_dir.join("runtimes.json"),
            "{\n  \"runtimes\": {\n    \"local_kernel\": {\"id\": \"local_kernel\", \"label\": \"Local Kernel Runtime\"},\n    \"loom_native\": {\"status\": \"experimental\", \"notes\": \"daemon fixture\", \"contract_compliance\": {\"agent_identity\": null, \"action_envelope\": null, \"cost_attribution\": null, \"approval_hook\": null, \"audit_emission\": null, \"sanction_controls\": null, \"budget_gate\": null}}\n  }\n}\n",
        )
        .expect("write runtimes");
        fs::write(
            kernel_dir.join("agent_registry.py"),
            "import json, sys\nagent_id = sys.argv[sys.argv.index('--agent_id') + 1]\norg_id = sys.argv[sys.argv.index('--org_id') + 1] if '--org_id' in sys.argv else 'org_demo'\nprint(json.dumps({'id': agent_id, 'name': 'Atlas', 'org_id': org_id, 'role': 'analyst', 'economy_key': 'atlas', 'approval_required': False, 'budget': {'max_per_run_usd': 0.5}, 'runtime_binding': {'runtime_id': 'local_kernel', 'runtime_label': 'Local Kernel Runtime', 'bound_org_id': org_id, 'boundary_name': 'workspace', 'identity_model': 'session', 'runtime_registered': True, 'registration_status': 'registered'}}, indent=2))\n",
        )
        .expect("write registry");
        fs::write(
            kernel_dir.join("court.py"),
            "def get_restrictions(agent_id, org_id=None):\n    return []\n",
        )
        .expect("write court");
        fs::write(
            kernel_dir.join("authority.py"),
            "def check_authority(agent_id, action, org_id=None):\n    return True, 'ok'\n",
        )
        .expect("write authority");
        fs::write(
            kernel_dir.join("treasury.py"),
            "def check_budget(agent_id, cost_usd, org_id=None):\n    return True, 'ok'\n",
        )
        .expect("write treasury");
        fs::write(
            kernel_dir.join("audit.py"),
            "def log_event(*args, **kwargs):\n    return 'evt_daemon'\n",
        )
        .expect("write audit");
        fs::write(kernel_dir.join("adapters/__init__.py"), "").expect("write adapter init");
        fs::write(
            kernel_dir.join("adapters/meridian_compatible.py"),
            "def pre_action_check(org_id, envelope):\n    return {'allowed': True, 'stage': 'ok', 'reason': 'ok', 'restrictions': []}\n",
        )
        .expect("write adapter");
        init_workspace(
            &root,
            "embedded",
            Some(kernel.to_string_lossy().as_ref()),
            "org_demo",
        )
        .expect("init workspace");
        let envelope = sample_envelope();
        enqueue_action(&root, &kernel, &envelope).expect("enqueue");

        let snapshot = run_supervisor_daemon_loop(
            &root,
            Some(kernel.to_string_lossy().as_ref()),
            1,
            0,
            2,
            "daemon-test",
        )
        .expect("daemon loop");
        assert!(snapshot.available);
        assert_eq!(snapshot.session_id, "daemon-test");
        assert_eq!(snapshot.processed, 1);
        assert_eq!(snapshot.status, "completed");
        assert!(snapshot.runtime_state_path.exists());
        let human = render_supervisor_daemon_human(&snapshot);
        assert!(human.contains("SUPERVISOR DAEMON"));
    }

    #[test]
    fn runtime_service_accepts_socket_submit_and_processes_queue() {
        let root = temp_path("loom-shadow-runtime-service");
        fs::create_dir_all(&root).expect("root");
        let kernel = temp_path("loom-shadow-runtime-service-kernel");
        let kernel_dir = kernel.join("kernel");
        fs::create_dir_all(kernel_dir.join("adapters")).expect("kernel dirs");
        fs::write(
            kernel_dir.join("runtimes.json"),
            "{\n  \"runtimes\": {\n    \"local_kernel\": {\"id\": \"local_kernel\", \"label\": \"Local Kernel Runtime\"},\n    \"loom_native\": {\"status\": \"experimental\", \"notes\": \"service fixture\", \"contract_compliance\": {\"agent_identity\": null, \"action_envelope\": null, \"cost_attribution\": null, \"approval_hook\": null, \"audit_emission\": null, \"sanction_controls\": null, \"budget_gate\": null}}\n  }\n}\n",
        )
        .expect("write runtimes");
        fs::write(
            kernel_dir.join("agent_registry.py"),
            "import json, sys\nagent_id = sys.argv[sys.argv.index('--agent_id') + 1]\norg_id = sys.argv[sys.argv.index('--org_id') + 1] if '--org_id' in sys.argv else 'org_demo'\nprint(json.dumps({'id': agent_id, 'name': 'Atlas', 'org_id': org_id, 'role': 'analyst', 'economy_key': 'atlas', 'approval_required': False, 'budget': {'max_per_run_usd': 0.5}, 'runtime_binding': {'runtime_id': 'local_kernel', 'runtime_label': 'Local Kernel Runtime', 'bound_org_id': org_id, 'boundary_name': 'workspace', 'identity_model': 'session', 'runtime_registered': True, 'registration_status': 'registered'}}, indent=2))\n",
        )
        .expect("write registry");
        fs::write(
            kernel_dir.join("court.py"),
            "def get_restrictions(agent_id, org_id=None):\n    return []\n",
        )
        .expect("write court");
        fs::write(
            kernel_dir.join("authority.py"),
            "def check_authority(agent_id, action, org_id=None):\n    return True, 'ok'\n",
        )
        .expect("write authority");
        fs::write(
            kernel_dir.join("treasury.py"),
            "def check_budget(agent_id, cost_usd, org_id=None):\n    return True, 'ok'\n\ndef reserve_runtime_budget(*args, **kwargs):\n    return {'allowed': True, 'reservation_id': 'bud_service', 'reservation': {'reservation_id': 'bud_service'}, 'reason': 'ok'}\n\ndef commit_runtime_budget(reservation_id, actual_cost_usd, note=''):\n    return {'reservation_id': reservation_id, 'status': 'committed', 'commit_reason': note}\n\ndef release_runtime_budget(reservation_id, reason=''):\n    return {'reservation_id': reservation_id, 'status': 'released', 'release_reason': reason}\n",
        )
        .expect("write treasury");
        fs::write(
            kernel_dir.join("audit.py"),
            "def log_event(*args, **kwargs):\n    return 'evt_service'\n",
        )
        .expect("write audit");
        fs::write(kernel_dir.join("adapters/__init__.py"), "").expect("write adapter init");
        fs::write(
            kernel_dir.join("adapters/meridian_compatible.py"),
            "def pre_action_check(org_id, envelope):\n    return {'allowed': True, 'stage': 'ok', 'reason': 'ok', 'restrictions': []}\n",
        )
        .expect("write adapter");
        init_workspace(
            &root,
            "embedded",
            Some(kernel.to_string_lossy().as_ref()),
            "org_demo",
        )
        .expect("init workspace");
        let root_for_service = root.clone();
        let kernel_for_service = kernel.clone();
        let handle = thread::spawn(move || {
            run_runtime_service_loop(
                &root_for_service,
                Some(kernel_for_service.to_string_lossy().as_ref()),
                None,
                None,
                None,
                None,
                None,
                1,
                1,
                3,
                "service-test",
            )
        });

        let socket_path = service_socket_path(&root, None).expect("socket path");
        for _ in 0..20 {
            if socket_path.exists() {
                break;
            }
            thread::sleep(Duration::from_millis(50));
        }
        assert!(
            socket_path.exists(),
            "runtime service socket did not appear"
        );

        let capture =
            submit_runtime_service_action(&root, None, None, None, &kernel, &sample_envelope())
                .expect("submit via service");
        assert_eq!(capture.job_id, envelope_input_hash(&sample_envelope()));
        request_runtime_service_stop(&root, None).expect("request stop");
        let snapshot = handle
            .join()
            .expect("join service thread")
            .expect("service loop");
        assert!(snapshot.available);
        assert_eq!(snapshot.session_id, "service-test");
        assert_eq!(snapshot.submitted, 1);
        assert!(snapshot.processed >= 1);
        let job = inspect_job(&root, &capture.job_id).expect("inspect job");
        assert_eq!(job.status, "completed");
        let human = render_runtime_service_human(&snapshot);
        assert!(human.contains("RUNTIME SERVICE"));
        assert!(human.contains("official v0.1 local runtime service"));
        assert!(human.contains("service-owned ingress is locally real"));
    }

    #[test]
    fn runtime_service_falls_back_to_file_ingress_when_socket_bind_is_unavailable() {
        let root = temp_path("loom-shadow-runtime-service-file");
        fs::create_dir_all(&root).expect("root");
        let kernel = temp_path("loom-shadow-runtime-service-file-kernel");
        let kernel_dir = kernel.join("kernel");
        fs::create_dir_all(kernel_dir.join("adapters")).expect("kernel dirs");
        fs::write(
            kernel_dir.join("runtimes.json"),
            "{\n  \"runtimes\": {\n    \"local_kernel\": {\"id\": \"local_kernel\", \"label\": \"Local Kernel Runtime\"},\n    \"loom_native\": {\"status\": \"experimental\", \"notes\": \"file ingress fixture\", \"contract_compliance\": {\"agent_identity\": null, \"action_envelope\": null, \"cost_attribution\": null, \"approval_hook\": null, \"audit_emission\": null, \"sanction_controls\": null, \"budget_gate\": null}}\n  }\n}\n",
        )
        .expect("write runtimes");
        fs::write(
            kernel_dir.join("agent_registry.py"),
            "import json, sys\nagent_id = sys.argv[sys.argv.index('--agent_id') + 1]\norg_id = sys.argv[sys.argv.index('--org_id') + 1] if '--org_id' in sys.argv else 'org_demo'\nprint(json.dumps({'id': agent_id, 'name': 'Atlas', 'org_id': org_id, 'role': 'analyst', 'economy_key': 'atlas', 'approval_required': False, 'budget': {'max_per_run_usd': 0.5}, 'runtime_binding': {'runtime_id': 'local_kernel', 'runtime_label': 'Local Kernel Runtime', 'bound_org_id': org_id, 'boundary_name': 'workspace', 'identity_model': 'session', 'runtime_registered': True, 'registration_status': 'registered'}}, indent=2))\n",
        )
        .expect("write registry");
        fs::write(
            kernel_dir.join("court.py"),
            "def get_restrictions(agent_id, org_id=None):\n    return []\n",
        )
        .expect("write court");
        fs::write(
            kernel_dir.join("authority.py"),
            "def check_authority(agent_id, action, org_id=None):\n    return True, 'ok'\n",
        )
        .expect("write authority");
        fs::write(
            kernel_dir.join("treasury.py"),
            "def check_budget(agent_id, cost_usd, org_id=None):\n    return True, 'ok'\n\ndef reserve_runtime_budget(*args, **kwargs):\n    return {'allowed': True, 'reservation_id': 'bud_service', 'reservation': {'reservation_id': 'bud_service'}, 'reason': 'ok'}\n\ndef commit_runtime_budget(reservation_id, actual_cost_usd, note=''):\n    return {'reservation_id': reservation_id, 'status': 'committed', 'commit_reason': note}\n\ndef release_runtime_budget(reservation_id, reason=''):\n    return {'reservation_id': reservation_id, 'status': 'released', 'release_reason': reason}\n",
        )
        .expect("write treasury");
        fs::write(
            kernel_dir.join("audit.py"),
            "def log_event(*args, **kwargs):\n    return 'evt_service'\n",
        )
        .expect("write audit");
        fs::write(kernel_dir.join("adapters/__init__.py"), "").expect("write adapter init");
        fs::write(
            kernel_dir.join("adapters/meridian_compatible.py"),
            "def pre_action_check(org_id, envelope):\n    return {'allowed': True, 'stage': 'ok', 'reason': 'ok', 'restrictions': []}\n",
        )
        .expect("write adapter");
        init_workspace(
            &root,
            "embedded",
            Some(kernel.to_string_lossy().as_ref()),
            "org_demo",
        )
        .expect("init workspace");

        let socket_override = ensure_runtime_service_dir(&root)
            .expect("service dir")
            .display()
            .to_string();
        let root_for_service = root.clone();
        let kernel_for_service = kernel.clone();
        let socket_override_for_service = socket_override.clone();
        let handle = thread::spawn(move || {
            run_runtime_service_loop(
                &root_for_service,
                Some(kernel_for_service.to_string_lossy().as_ref()),
                Some(&socket_override_for_service),
                None,
                None,
                None,
                None,
                1,
                0,
                1_000_000,
                "service-file-test",
            )
        });

        let mut running = false;
        for _ in 0..40 {
            if let Ok(snapshot) = runtime_service_status(&root, Some(&socket_override)) {
                if snapshot.available && snapshot.running {
                    running = true;
                    break;
                }
            }
            thread::sleep(Duration::from_millis(50));
        }
        assert!(
            running,
            "runtime service did not report running before submit"
        );

        let capture =
            submit_runtime_service_action(&root, None, None, None, &kernel, &sample_envelope())
                .expect("submit via file ingress fallback");
        request_runtime_service_stop(&root, None).expect("request stop");
        let snapshot = handle
            .join()
            .expect("join service thread")
            .expect("service loop");
        assert!(snapshot.available);
        assert_eq!(snapshot.session_id, "service-file-test");
        assert_eq!(capture.job_id, envelope_input_hash(&sample_envelope()));
        let job = inspect_job(&root, &capture.job_id).expect("inspect job");
        assert_eq!(job.status, "completed");
        assert!(capture.note.contains("file"));
        let service_events = fs::read_to_string(snapshot.event_log_path).expect("service events");
        assert!(service_events.contains("socket_bind_failed"));
    }

    #[test]
    fn runtime_service_file_ingress_preserves_capability_job_identity() {
        let root = temp_path("loom-shadow-runtime-service-capability-file");
        fs::create_dir_all(&root).expect("root");
        let kernel = temp_path("loom-shadow-runtime-service-capability-file-kernel");
        let kernel_dir = kernel.join("kernel");
        fs::create_dir_all(kernel_dir.join("adapters")).expect("kernel dirs");
        fs::write(
            kernel_dir.join("runtimes.json"),
            "{\n  \"runtimes\": {\n    \"local_kernel\": {\"id\": \"local_kernel\", \"label\": \"Local Kernel Runtime\"},\n    \"loom_native\": {\"status\": \"experimental\", \"notes\": \"capability file ingress fixture\", \"contract_compliance\": {\"agent_identity\": null, \"action_envelope\": null, \"cost_attribution\": null, \"approval_hook\": null, \"audit_emission\": null, \"sanction_controls\": null, \"budget_gate\": null}}\n  }\n}\n",
        )
        .expect("write runtimes");
        fs::write(
            kernel_dir.join("agent_registry.py"),
            "import json, sys\nagent_id = sys.argv[sys.argv.index('--agent_id') + 1]\norg_id = sys.argv[sys.argv.index('--org_id') + 1] if '--org_id' in sys.argv else 'org_demo'\nprint(json.dumps({'id': agent_id, 'name': 'Atlas', 'org_id': org_id, 'role': 'analyst', 'economy_key': 'atlas', 'approval_required': False, 'budget': {'max_per_run_usd': 0.5}, 'runtime_binding': {'runtime_id': 'local_kernel', 'runtime_label': 'Local Kernel Runtime', 'bound_org_id': org_id, 'boundary_name': 'workspace', 'identity_model': 'session', 'runtime_registered': True, 'registration_status': 'registered'}}, indent=2))\n",
        )
        .expect("write registry");
        fs::write(
            kernel_dir.join("court.py"),
            "def get_restrictions(agent_id, org_id=None):\n    return []\n",
        )
        .expect("write court");
        fs::write(
            kernel_dir.join("authority.py"),
            "def check_authority(agent_id, action, org_id=None):\n    return True, 'ok'\n",
        )
        .expect("write authority");
        fs::write(
            kernel_dir.join("treasury.py"),
            "def check_budget(agent_id, cost_usd, org_id=None):\n    return True, 'ok'\n\ndef reserve_runtime_budget(*args, **kwargs):\n    return {'allowed': True, 'reservation_id': 'bud_service', 'reservation': {'reservation_id': 'bud_service'}, 'reason': 'ok'}\n\ndef commit_runtime_budget(reservation_id, actual_cost_usd, note=''):\n    return {'reservation_id': reservation_id, 'status': 'committed', 'commit_reason': note}\n\ndef release_runtime_budget(reservation_id, reason=''):\n    return {'reservation_id': reservation_id, 'status': 'released', 'release_reason': reason}\n",
        )
        .expect("write treasury");
        fs::write(
            kernel_dir.join("audit.py"),
            "def log_event(*args, **kwargs):\n    return 'evt_service'\n",
        )
        .expect("write audit");
        fs::write(kernel_dir.join("adapters/__init__.py"), "").expect("write adapter init");
        fs::write(
            kernel_dir.join("adapters/meridian_compatible.py"),
            "def pre_action_check(org_id, envelope):\n    return {'allowed': True, 'stage': 'ok', 'reason': 'ok', 'restrictions': []}\n",
        )
        .expect("write adapter");
        init_workspace(
            &root,
            "embedded",
            Some(kernel.to_string_lossy().as_ref()),
            "org_demo",
        )
        .expect("init workspace");

        let socket_override = ensure_runtime_service_dir(&root)
            .expect("service dir")
            .display()
            .to_string();
        let root_for_service = root.clone();
        let kernel_for_service = kernel.clone();
        let socket_override_for_service = socket_override.clone();
        let handle = thread::spawn(move || {
            run_runtime_service_loop(
                &root_for_service,
                Some(kernel_for_service.to_string_lossy().as_ref()),
                Some(&socket_override_for_service),
                None,
                None,
                None,
                None,
                1,
                0,
                100,
                "service-capability-file-test",
            )
        });

        for _ in 0..20 {
            if let Ok(snapshot) = runtime_service_status(&root, Some(&socket_override)) {
                if snapshot.available && snapshot.running {
                    break;
                }
            }
            let state_path = runtime_service_state_path(&root).expect("service state path");
            if state_path.exists() {
                break;
            }
            thread::sleep(Duration::from_millis(50));
        }

        let envelope = sample_capability_envelope();
        let expected_job_id = envelope_input_hash(&envelope);
        let capture = submit_runtime_service_action(&root, None, None, None, &kernel, &envelope)
            .expect("submit via file ingress fallback");
        request_runtime_service_stop(&root, None).expect("request stop");
        let snapshot = handle
            .join()
            .expect("join service thread")
            .expect("service loop");
        assert!(snapshot.available);
        assert_eq!(capture.job_id, expected_job_id);
        let job = inspect_job(&root, &capture.job_id).expect("inspect job");
        assert_eq!(job.status, "completed");
        let result_path = job.job_path.parent().expect("job dir").join("result.json");
        let result_contents = fs::read_to_string(result_path).expect("result");
        assert!(result_contents.contains("\"capability_name\": \"loom.echo.v1\""));
        assert!(result_contents.contains("hello from capability lane"));
    }

    #[test]
    fn import_commitment_execution_requests_enqueues_sender_side_delivery_refs() {
        let root = temp_path("loom-shadow-commitment-import");
        fs::create_dir_all(&root).expect("root");
        let kernel = temp_path("loom-shadow-commitment-import-kernel");
        let kernel_dir = kernel.join("kernel");
        fs::create_dir_all(kernel_dir.join("adapters")).expect("kernel dirs");
        fs::write(
            kernel_dir.join("runtimes.json"),
            "{\n  \"runtimes\": {\n    \"local_kernel\": {\"id\": \"local_kernel\", \"label\": \"Local Kernel Runtime\"},\n    \"loom_native\": {\"status\": \"experimental\", \"notes\": \"commitment import fixture\", \"contract_compliance\": {\"agent_identity\": null, \"action_envelope\": null, \"cost_attribution\": null, \"approval_hook\": null, \"audit_emission\": null, \"sanction_controls\": null, \"budget_gate\": null}}\n  }\n}\n",
        )
        .expect("write runtimes");
        fs::write(
            kernel_dir.join("agent_registry.py"),
            "import json, sys\nagent_id = sys.argv[sys.argv.index('--agent_id') + 1]\norg_id = sys.argv[sys.argv.index('--org_id') + 1] if '--org_id' in sys.argv else 'org_alpha'\nprint(json.dumps({'id': agent_id, 'name': 'Atlas', 'org_id': org_id, 'role': 'analyst', 'economy_key': 'atlas', 'approval_required': False, 'budget': {'max_per_run_usd': 5.0}, 'runtime_binding': {'runtime_id': 'local_kernel', 'runtime_label': 'Local Kernel Runtime', 'bound_org_id': org_id, 'boundary_name': 'workspace', 'identity_model': 'session', 'runtime_registered': True, 'registration_status': 'registered'}}, indent=2))\n",
        )
        .expect("write registry");
        fs::write(
            kernel_dir.join("court.py"),
            "def get_restrictions(agent_id, org_id=None):\n    return []\n",
        )
        .expect("write court");
        fs::write(
            kernel_dir.join("authority.py"),
            "def check_authority(agent_id, action, org_id=None):\n    return True, 'ok'\n",
        )
        .expect("write authority");
        fs::write(
            kernel_dir.join("treasury.py"),
            "def check_budget(agent_id, cost_usd, org_id=None):\n    return True, 'ok'\n",
        )
        .expect("write treasury");
        fs::write(
            kernel_dir.join("audit.py"),
            "def log_event(*args, **kwargs):\n    return 'evt_import'\n",
        )
        .expect("write audit");
        init_workspace(
            &root,
            "embedded",
            Some(kernel.to_string_lossy().as_ref()),
            "org_alpha",
        )
        .expect("init workspace");

        let commitments_path = root.join("commitments_snapshot.json");
        fs::write(
            &commitments_path,
            "{\n  \"bound_org_id\": \"org_alpha\",\n  \"commitments\": [\n    {\n      \"commitment_id\": \"commit_demo\",\n      \"source_institution_id\": \"org_alpha\",\n      \"delivery_refs\": [\n        {\n          \"message_type\": \"execution_request\",\n          \"envelope_id\": \"fedenv_demo\",\n          \"receipt_id\": \"fedrcpt_demo\",\n          \"adapter_envelope\": {\n            \"agent_id\": \"atlas\",\n            \"action_type\": \"federated_execution\",\n            \"resource\": \"host_beta/shared_brief_review\",\n            \"estimated_cost_usd\": 0.10,\n            \"run_id\": \"run_import_demo\",\n            \"session_id\": \"sess_import_demo\",\n            \"details\": {\n              \"message_type\": \"execution_request\",\n              \"commitment_id\": \"commit_demo\"\n            }\n          }\n        }\n      ]\n    }\n  ]\n}\n",
        )
        .expect("write commitments snapshot");

        let capture = import_commitment_execution_requests(
            &root,
            Some(kernel.to_string_lossy().as_ref()),
            commitments_path.to_string_lossy().as_ref(),
            None,
        )
        .expect("import commitments");
        assert_eq!(capture.imported, 1);
        assert_eq!(capture.skipped, 0);
        assert!(!capture.last_job_id.is_empty());
        let job = inspect_job(&root, &capture.last_job_id).expect("inspect imported job");
        assert_eq!(job.status, "queued");
        assert_eq!(job.action_type, "federated_execution");
        assert_eq!(job.org_id, "org_alpha");
    }

    #[test]
    fn runtime_service_loop_imports_commitments_source_and_processes_job() {
        let root = temp_path("loom-shadow-commitment-service-import");
        fs::create_dir_all(&root).expect("root");
        let kernel = temp_path("loom-shadow-commitment-service-import-kernel");
        let kernel_dir = kernel.join("kernel");
        fs::create_dir_all(kernel_dir.join("adapters")).expect("kernel dirs");
        fs::write(
            kernel_dir.join("runtimes.json"),
            "{\n  \"runtimes\": {\n    \"local_kernel\": {\"id\": \"local_kernel\", \"label\": \"Local Kernel Runtime\"},\n    \"loom_native\": {\"status\": \"experimental\", \"notes\": \"service import fixture\", \"contract_compliance\": {\"agent_identity\": null, \"action_envelope\": null, \"cost_attribution\": null, \"approval_hook\": null, \"audit_emission\": null, \"sanction_controls\": null, \"budget_gate\": null}}\n  }\n}\n",
        )
        .expect("write runtimes");
        fs::write(
            kernel_dir.join("agent_registry.py"),
            "import json, sys\nagent_id = sys.argv[sys.argv.index('--agent_id') + 1]\norg_id = sys.argv[sys.argv.index('--org_id') + 1] if '--org_id' in sys.argv else 'org_alpha'\nprint(json.dumps({'id': agent_id, 'name': 'Atlas', 'org_id': org_id, 'role': 'analyst', 'economy_key': 'atlas', 'approval_required': False, 'budget': {'max_per_run_usd': 5.0}, 'runtime_binding': {'runtime_id': 'local_kernel', 'runtime_label': 'Local Kernel Runtime', 'bound_org_id': org_id, 'boundary_name': 'workspace', 'identity_model': 'session', 'runtime_registered': True, 'registration_status': 'registered'}}, indent=2))\n",
        )
        .expect("write registry");
        fs::write(
            kernel_dir.join("court.py"),
            "def get_restrictions(agent_id, org_id=None):\n    return []\n",
        )
        .expect("write court");
        fs::write(
            kernel_dir.join("authority.py"),
            "def check_authority(agent_id, action, org_id=None):\n    return True, 'ok'\n",
        )
        .expect("write authority");
        fs::write(
            kernel_dir.join("treasury.py"),
            "def check_budget(agent_id, cost_usd, org_id=None):\n    return True, 'ok'\n\ndef reserve_runtime_budget(*args, **kwargs):\n    return {'allowed': True, 'reservation_id': 'bud_service', 'reservation': {'reservation_id': 'bud_service'}, 'reason': 'ok'}\n\ndef commit_runtime_budget(reservation_id, actual_cost_usd, note=''):\n    return {'reservation_id': reservation_id, 'status': 'committed', 'commit_reason': note}\n\ndef release_runtime_budget(reservation_id, reason=''):\n    return {'reservation_id': reservation_id, 'status': 'released', 'release_reason': reason}\n",
        )
        .expect("write treasury");
        fs::write(
            kernel_dir.join("audit.py"),
            "def log_event(*args, **kwargs):\n    return 'evt_import'\n",
        )
        .expect("write audit");
        fs::write(kernel_dir.join("adapters/__init__.py"), "").expect("write adapter init");
        fs::write(
            kernel_dir.join("adapters/meridian_compatible.py"),
            "def pre_action_check(org_id, envelope):\n    return {'allowed': True, 'stage': 'ok', 'reason': 'ok', 'restrictions': []}\n",
        )
        .expect("write adapter");
        init_workspace(
            &root,
            "embedded",
            Some(kernel.to_string_lossy().as_ref()),
            "org_alpha",
        )
        .expect("init workspace");

        let commitments_path = root.join("commitments_snapshot.json");
        fs::write(
            &commitments_path,
            "{\n  \"bound_org_id\": \"org_alpha\",\n  \"commitments\": [\n    {\n      \"commitment_id\": \"commit_demo\",\n      \"source_institution_id\": \"org_alpha\",\n      \"delivery_refs\": [\n        {\n          \"message_type\": \"execution_request\",\n          \"envelope_id\": \"fedenv_demo\",\n          \"receipt_id\": \"fedrcpt_demo\",\n          \"adapter_envelope\": {\n            \"agent_id\": \"atlas\",\n            \"action_type\": \"federated_execution\",\n            \"resource\": \"host_beta/shared_brief_review\",\n            \"estimated_cost_usd\": 0.10,\n            \"run_id\": \"run_import_demo\",\n            \"session_id\": \"sess_import_demo\",\n            \"details\": {\"message_type\": \"execution_request\", \"commitment_id\": \"commit_demo\"}\n          }\n        }\n      ]\n    }\n  ]\n}\n",
        )
        .expect("write commitments snapshot");

        let snapshot = run_runtime_service_loop(
            &root,
            Some(kernel.to_string_lossy().as_ref()),
            None,
            None,
            None,
            Some(commitments_path.to_string_lossy().as_ref()),
            None,
            1,
            0,
            2,
            "service-import-test",
        )
        .expect("service loop");
        assert!(snapshot.available);
        assert_eq!(snapshot.submitted, 1);
        assert_eq!(snapshot.processed, 1);
        let marker_dir = ensure_runtime_imports_dir(&root)
            .expect("imports dir")
            .join("commitment_execution");
        assert!(marker_dir.exists());
    }

    #[test]
    fn runtime_service_http_rejects_missing_token_and_handles_bad_requests() {
        let root = temp_path("loom-shadow-http-auth");
        init_workspace(&root, "embedded", None, "org_demo").expect("init workspace");

        let unauthorized = handle_runtime_service_http_request(
            &root,
            None,
            "127.0.0.1:18910",
            Some("secret-token"),
            "GET /status HTTP/1.1\r\nHost: local\r\n\r\n",
        )
        .expect("unauthorized reply");
        assert_eq!(unauthorized.http_status_code, 401);
        assert_eq!(unauthorized.status, "unauthorized");

        let bad = handle_runtime_service_http_request(
            &root,
            None,
            "127.0.0.1:18910",
            Some("secret-token"),
            "BROKEN REQUEST\r\n\r\n",
        )
        .expect("bad request reply");
        assert_eq!(bad.http_status_code, 400);
        assert_eq!(bad.status, "bad_request");

        let malformed_header = handle_runtime_service_http_request(
            &root,
            None,
            "127.0.0.1:18910",
            Some("secret-token"),
            "GET /status HTTP/1.1\r\nHost local\r\nAuthorization: Bearer secret-token\r\n\r\n",
        )
        .expect("malformed header reply");
        assert_eq!(malformed_header.http_status_code, 400);
        assert_eq!(malformed_header.status, "bad_request");

        let bad_length = handle_runtime_service_http_request(
            &root,
            None,
            "127.0.0.1:18910",
            Some("secret-token"),
            "POST /submit HTTP/1.1\r\nHost: local\r\nAuthorization: Bearer secret-token\r\nContent-Type: application/json\r\nContent-Length: 25\r\n\r\n{}",
        )
        .expect("content-length reply");
        assert_eq!(bad_length.http_status_code, 400);
        assert_eq!(bad_length.status, "bad_request");

        let wrong_content_type = handle_runtime_service_http_request(
            &root,
            None,
            "127.0.0.1:18910",
            Some("secret-token"),
            "POST /submit HTTP/1.1\r\nHost: local\r\nAuthorization: Bearer secret-token\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\n{}",
        )
        .expect("wrong content-type reply");
        assert_eq!(wrong_content_type.http_status_code, 415);
        assert_eq!(wrong_content_type.status, "unsupported_media_type");

        let metrics = handle_runtime_service_http_request(
            &root,
            None,
            "127.0.0.1:18910",
            Some("secret-token"),
            "GET /metrics HTTP/1.1\r\nHost: local\r\nAuthorization: Bearer secret-token\r\n\r\n",
        )
        .expect("metrics reply");
        assert_eq!(metrics.http_status_code, 200);
        assert!(metrics.payload.contains("\"requests_received\""));

        let config = handle_runtime_service_http_request(
            &root,
            None,
            "127.0.0.1:18910",
            Some("secret-token"),
            "GET /config HTTP/1.1\r\nHost: local\r\nAuthorization: Bearer secret-token\r\n\r\n",
        )
        .expect("config reply");
        assert_eq!(config.http_status_code, 200);
        assert!(config.payload.contains("\"service_token_present\""));
    }

    #[test]
    fn runtime_service_status_marks_dead_pid_unhealthy() {
        let root = temp_path("loom-shadow-service-status-dead-pid");
        init_workspace(&root, "embedded", None, "org_demo").expect("init workspace");

        let runtime_state_path = runtime_service_state_path(&root).expect("runtime state path");
        let metrics_path = service_metrics_path(&root).expect("metrics path");
        let socket_path = service_socket_path(&root, None).expect("socket path");
        write_runtime_service_state(
            &runtime_state_path,
            &metrics_path,
            &socket_path,
            Some("127.0.0.1:1"),
            true,
            "service-dead",
            999_999,
            true,
            "running",
            "100",
            "",
            1,
            1,
            100,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            "",
            "",
            "simulated dead pid".to_string(),
        )
        .expect("write runtime state");

        let snapshot = runtime_service_status(&root, None).expect("status");
        assert!(snapshot.available);
        assert!(!snapshot.running);
        assert_eq!(snapshot.status, "crashed");
        let health = render_runtime_service_health_json(&snapshot);
        assert!(health.contains("\"status\": \"crashed\""));
    }

    #[test]
    fn runtime_service_status_accepts_live_http_control_plane_when_pid_is_hidden() {
        let root = temp_path("loom-shadow-service-status-http-live");
        init_workspace(&root, "embedded", None, "org_demo").expect("init workspace");

        let listener = TcpListener::bind("127.0.0.1:0").expect("bind http listener");
        let http_address = listener.local_addr().expect("listener addr").to_string();

        let runtime_state_path = runtime_service_state_path(&root).expect("runtime state path");
        let metrics_path = service_metrics_path(&root).expect("metrics path");
        let socket_path = service_socket_path(&root, None).expect("socket path");
        write_runtime_service_state(
            &runtime_state_path,
            &metrics_path,
            &socket_path,
            Some(&http_address),
            true,
            "service-http-live",
            999_999,
            true,
            "running",
            "100",
            "",
            1,
            1,
            100,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            "",
            "",
            "simulated hidden pid".to_string(),
        )
        .expect("write runtime state");

        let snapshot = runtime_service_status(&root, None).expect("status");
        assert!(snapshot.available);
        assert!(snapshot.running);
        assert_eq!(snapshot.status, "running");
        assert!(snapshot.note.contains("control plane is reachable"));

        drop(listener);
    }

    fn scaffold_queue_kernel(kernel_root: &Path, note: &str, treasury_limit: f64) {
        let kernel_dir = kernel_root.join("kernel");
        fs::create_dir_all(kernel_dir.join("adapters")).expect("kernel dirs");
        let runtimes = serde_json::json!({
            "runtimes": {
                "local_kernel": {"id": "local_kernel", "label": "Local Kernel Runtime"},
                "loom_native": {
                    "status": "experimental",
                    "notes": note,
                    "contract_compliance": {
                        "agent_identity": null,
                        "action_envelope": null,
                        "cost_attribution": null,
                        "approval_hook": null,
                        "audit_emission": null,
                        "sanction_controls": null,
                        "budget_gate": null,
                    },
                },
            }
        });
        fs::write(
            kernel_dir.join("runtimes.json"),
            format!(
                "{}\n",
                serde_json::to_string_pretty(&runtimes).expect("serialize runtimes")
            ),
        )
        .expect("write runtimes");
        fs::write(
            kernel_dir.join("agent_registry.py"),
            r#"import json, sys
agent_id = sys.argv[sys.argv.index('--agent_id') + 1]
org_id = sys.argv[sys.argv.index('--org_id') + 1] if '--org_id' in sys.argv else 'org_demo'
print(json.dumps({'id': agent_id, 'name': 'Atlas', 'org_id': org_id, 'role': 'analyst', 'economy_key': 'atlas', 'approval_required': False, 'budget': {'max_per_run_usd': 0.5}, 'runtime_binding': {'runtime_id': 'local_kernel', 'runtime_label': 'Local Kernel Runtime', 'bound_org_id': org_id, 'boundary_name': 'workspace', 'identity_model': 'session', 'runtime_registered': True, 'registration_status': 'registered'}}, indent=2))
"#,
        )
        .expect("write registry");
        fs::write(
            kernel_dir.join("court.py"),
            r#"def get_restrictions(agent_id, org_id=None):
    return []
"#,
        )
        .expect("write court");
        fs::write(
            kernel_dir.join("authority.py"),
            r#"def check_authority(agent_id, action, org_id=None):
    return True, 'ok'
"#,
        )
        .expect("write authority");
        fs::write(
            kernel_dir.join("treasury.py"),
            format!(
                r#"def check_budget(agent_id, cost_usd, org_id=None):
    if cost_usd > {}:
        return False, 'below reserve'
    return True, 'ok'
"#,
                treasury_limit,
            ),
        )
        .expect("write treasury");
        fs::write(
            kernel_dir.join("audit.py"),
            r#"def log_event(*args, **kwargs):
    return 'evt_jobs'
"#,
        )
        .expect("write audit");
        fs::write(kernel_dir.join("adapters/__init__.py"), "").expect("write adapter init");
        fs::write(
            kernel_dir.join("adapters/meridian_compatible.py"),
            r#"def pre_action_check(org_id, envelope):
    return {'allowed': True, 'stage': 'ok', 'reason': 'ok', 'restrictions': []}
"#,
        )
        .expect("write adapter");
    }

    #[test]
    fn queue_inspect_lists_pending_records_before_processing() {
        let root = temp_path("loom-shadow-queue-inspect");
        fs::create_dir_all(&root).expect("root");
        let envelope = sample_envelope();
        let capture =
            enqueue_action(&root, Path::new("/tmp/meridian-kernel"), &envelope).expect("enqueue");

        let records = inspect_pending_queue(&root, 10).expect("inspect queue");
        assert_eq!(records.len(), 1);
        assert_eq!(records[0].job_id, capture.input_hash);
        assert!(!records[0].acknowledged);
        let human = render_queue_inspect_human(&root, &records, 10);
        assert!(human.contains("QUEUE INSPECT"));
        assert!(human.contains(&capture.input_hash));
        let json = render_queue_inspect_json(&root, &records, 10);
        assert!(json.contains(r#""pending_records": 1"#));
    }

    #[test]
    fn queue_status_reports_policy_depths_for_pending_records() {
        let root = temp_path("loom-shadow-queue-status");
        fs::create_dir_all(&root).expect("root");
        let kernel_root = temp_path("loom-shadow-queue-status-kernel");
        scaffold_queue_kernel(&kernel_root, "queue status fixture", 0.5);
        init_workspace(
            &root,
            "embedded",
            Some(kernel_root.to_string_lossy().as_ref()),
            "org_demo",
        )
        .expect("init workspace");

        let mut envelope = sample_envelope();
        envelope.action_type = "research".to_string();
        envelope.estimated_cost_usd = 0.5;
        enqueue_action(&root, &kernel_root, &envelope).expect("enqueue standard");
        envelope.action_type = "admin".to_string();
        enqueue_action(&root, &kernel_root, &envelope).expect("enqueue privileged");
        envelope.action_type = "research".to_string();
        envelope.estimated_cost_usd = 2.5;
        enqueue_action(&root, &kernel_root, &envelope).expect("enqueue budget heavy");

        let snapshot = queue_status(&root).expect("queue status");
        assert_eq!(snapshot.pending_records, 3);
        assert_eq!(snapshot.total_pending, 3);
        assert_eq!(snapshot.standard_depth, 1);
        assert_eq!(snapshot.privileged_depth, 1);
        assert_eq!(snapshot.budget_heavy_depth, 1);
        assert_eq!(snapshot.sanction_sensitive_depth, 0);
        let human = render_queue_status_human(&snapshot);
        assert!(human.contains("QUEUE STATUS"));
        assert!(human.contains("official v0.1 local queue surface"));
        assert!(human.contains("standard_depth:"));
        let json = render_queue_status_json(&snapshot);
        assert!(json.contains(r#""status": "queue_status""#));
        assert!(json.contains(r#""standard": 1"#));
    }

    #[test]
    fn queue_consume_processes_and_records_ack_receipts() {
        let root = temp_path("loom-shadow-queue-consume");
        fs::create_dir_all(&root).expect("root");
        let kernel_root = temp_path("loom-shadow-queue-consume-kernel");
        scaffold_queue_kernel(&kernel_root, "queue consume fixture", 0.5);
        init_workspace(
            &root,
            "embedded",
            Some(kernel_root.to_string_lossy().as_ref()),
            "org_demo",
        )
        .expect("init workspace");
        let envelope = sample_envelope();
        let capture = enqueue_action(&root, &kernel_root, &envelope).expect("enqueue");

        let summary = consume_pending_queue(&root, Some(kernel_root.to_string_lossy().as_ref()), 1)
            .expect("consume queue");
        assert_eq!(summary.pending_before, 1);
        assert_eq!(summary.pending_after, 0);
        assert_eq!(summary.processed_jobs, 1);
        assert_eq!(summary.failed_jobs, 0);
        assert_eq!(summary.acked_jobs, 1);
        assert_eq!(summary.last_input_hash, capture.input_hash);
        let ack_path = root
            .join("state/runtime/queue/acks")
            .join(format!("{}.json", capture.input_hash));
        assert!(ack_path.exists());
        let human = render_queue_consume_human(&summary);
        assert!(human.contains("QUEUE CONSUME"));
        assert!(human.contains("acked_jobs:"));
        let json = render_queue_consume_json(&summary);
        assert!(json.contains(r#""status": "queue_consume_complete""#));
    }

    #[test]
    fn queue_ack_records_terminal_job_receipt() {
        let root = temp_path("loom-shadow-queue-ack");
        fs::create_dir_all(&root).expect("root");
        let kernel_root = temp_path("loom-shadow-queue-ack-kernel");
        scaffold_queue_kernel(&kernel_root, "queue ack fixture", 0.5);
        init_workspace(
            &root,
            "embedded",
            Some(kernel_root.to_string_lossy().as_ref()),
            "org_demo",
        )
        .expect("init workspace");
        let envelope = sample_envelope();
        let capture = enqueue_action(&root, &kernel_root, &envelope).expect("enqueue");
        run_supervisor(&root, Some(kernel_root.to_string_lossy().as_ref()), 1).expect("supervisor");

        let ack = ack_queue_job(&root, &capture.input_hash).expect("ack job");
        assert_eq!(ack.job_id, capture.input_hash);
        assert_eq!(ack.acknowledged_by, "queue_ack");
        assert_eq!(ack.job_status, "completed");
        assert!(ack.ack_path.exists());
        let human = render_queue_ack_human(&ack);
        assert!(human.contains("QUEUE ACK"));
        assert!(human.contains("acknowledged_by:     queue_ack"));
        let json = render_queue_ack_json(&ack);
        assert!(json.contains(r#""status": "queue_ack_recorded""#));
    }

    #[test]
    fn supervisor_reconciles_stale_pending_record_for_completed_job() {
        let root = temp_path("loom-shadow-stale-pending-terminal");
        fs::create_dir_all(&root).expect("root");
        let kernel_root = temp_path("loom-shadow-stale-pending-terminal-kernel");
        scaffold_queue_kernel(&kernel_root, "stale pending fixture", 0.5);
        init_workspace(
            &root,
            "embedded",
            Some(kernel_root.to_string_lossy().as_ref()),
            "org_demo",
        )
        .expect("init workspace");
        let envelope = sample_envelope();
        let capture = enqueue_action(&root, &kernel_root, &envelope).expect("enqueue");

        run_supervisor(&root, Some(kernel_root.to_string_lossy().as_ref()), 1)
            .expect("first supervisor");

        let processed_path = root
            .join("state/runtime/queue/processed")
            .join(capture.queue_path.file_name().expect("queue filename"));
        assert!(processed_path.exists());
        let stale_pending_path = root
            .join("state/runtime/queue/pending/standard")
            .join(capture.queue_path.file_name().expect("queue filename"));
        fs::copy(&processed_path, &stale_pending_path).expect("copy stale pending");
        assert!(stale_pending_path.exists());

        let summary = run_supervisor(&root, Some(kernel_root.to_string_lossy().as_ref()), 1)
            .expect("second supervisor");
        assert_eq!(summary.processed, 0);
        assert_eq!(summary.failed, 0);
        assert!(!stale_pending_path.exists());
        assert!(processed_path.exists());

        let state = load_scheduler_state_or_default(&root).expect("load scheduler");
        let job = state.jobs.get(&capture.input_hash).expect("job");
        assert_eq!(job.status, JobStatus::Completed);
        assert_eq!(job.queue_bucket, "processed:standard");
        assert!(job
            .result_summary
            .as_deref()
            .unwrap_or_default()
            .contains("stale pending queue record reconciled"));
    }

    #[test]
    fn enqueue_action_reuses_inflight_job_without_duplicate_pending_record() {
        let root = temp_path("loom-shadow-enqueue-dedupe");
        fs::create_dir_all(&root).expect("root");
        let kernel_root = temp_path("loom-shadow-enqueue-dedupe-kernel");
        scaffold_queue_kernel(&kernel_root, "dedupe fixture", 0.5);
        init_workspace(
            &root,
            "embedded",
            Some(kernel_root.to_string_lossy().as_ref()),
            "org_demo",
        )
        .expect("init workspace");
        let envelope = sample_envelope();

        let first = enqueue_action(&root, &kernel_root, &envelope).expect("first enqueue");
        let second = enqueue_action(&root, &kernel_root, &envelope).expect("second enqueue");

        assert_eq!(first.input_hash, second.input_hash);
        assert_eq!(first.queue_path, second.queue_path);
        let pending = collect_pending_queue_paths(&root).expect("pending");
        assert_eq!(pending.len(), 1);
    }

    #[test]
    fn client_disconnect_error_helper_flags_broken_pipe() {
        let error = io::Error::new(ErrorKind::BrokenPipe, "client left");
        assert!(is_client_disconnect_error(&error));
        let other = io::Error::new(ErrorKind::TimedOut, "timeout");
        assert!(!is_client_disconnect_error(&other));
    }

    #[test]
    fn runtime_service_cancel_marks_queued_job_cancelled() {
        let root = temp_path("loom-shadow-cancel-queued");
        fs::create_dir_all(&root).expect("root");
        let kernel_root = temp_path("loom-shadow-cancel-queued-kernel");
        scaffold_queue_kernel(&kernel_root, "cancel queued fixture", 0.5);
        init_workspace(
            &root,
            "embedded",
            Some(kernel_root.to_string_lossy().as_ref()),
            "org_demo",
        )
        .expect("init workspace");

        let envelope = sample_envelope();
        let capture = enqueue_action(&root, &kernel_root, &envelope).expect("enqueue");

        let request = format!(
            "{{\"request_type\":{},\"request_id\":{},\"job_id\":{}}}\n",
            json_string("cancel_job"),
            json_string("cancel-test"),
            json_string(&capture.input_hash),
        );
        let reply = handle_runtime_service_request(
            &root,
            Some(kernel_root.to_string_lossy().as_ref()),
            "test-socket",
            "socket",
            &request,
        )
        .expect("cancel request");

        assert_eq!(reply.status, "cancelled");
        assert!(reply.payload.contains(r#""status":"cancelled""#));
        assert!(reply.payload.contains(&capture.input_hash));

        let state = load_scheduler_state_or_default(&root).expect("load scheduler");
        let job = state.jobs.get(&capture.input_hash).expect("job");
        assert_eq!(job.status, JobStatus::Cancelled);
        assert_eq!(
            job.result_summary.as_deref(),
            Some("cancelled via service cancel request")
        );
    }

    #[test]
    fn queue_run_once_processes_a_single_batch_and_records_progress() {
        let root = temp_path("loom-shadow-queue-run-once");
        fs::create_dir_all(&root).expect("root");
        let kernel_root = temp_path("loom-shadow-queue-run-once-kernel");
        scaffold_queue_kernel(&kernel_root, "queue run-once fixture", 0.5);
        init_workspace(
            &root,
            "embedded",
            Some(kernel_root.to_string_lossy().as_ref()),
            "org_demo",
        )
        .expect("init workspace");
        let envelope = sample_envelope();
        let capture = enqueue_action(&root, &kernel_root, &envelope).expect("enqueue");

        let summary = run_queue_once(&root, Some(kernel_root.to_string_lossy().as_ref()))
            .expect("run queue once");
        assert_eq!(summary.pending_before, 1);
        assert_eq!(summary.pending_after, 0);
        assert_eq!(summary.processed_jobs, 1);
        assert_eq!(summary.failed_jobs, 0);
        assert_eq!(summary.acked_jobs, 1);
        assert_eq!(summary.last_input_hash, capture.input_hash);
        assert!(summary.progress_path.exists());
        let progress = fs::read_to_string(&summary.progress_path).expect("progress file");
        assert!(progress.contains(r#""status": "queue_run_once_complete""#));
        let human = render_queue_run_once_human(&summary);
        assert!(human.contains("QUEUE RUN-ONCE"));
        assert!(human.contains("progress_path:"));
        let json = render_queue_run_once_json(&summary);
        assert!(json.contains(r#""status": "queue_run_once_complete""#));
    }

    #[test]
    fn queue_run_until_empty_records_a_journal_and_drains_pending_records() {
        let root = temp_path("loom-shadow-queue-run-until-empty");
        fs::create_dir_all(&root).expect("root");
        let kernel_root = temp_path("loom-shadow-queue-run-until-empty-kernel");
        scaffold_queue_kernel(&kernel_root, "queue run-until-empty fixture", 0.5);
        init_workspace(
            &root,
            "embedded",
            Some(kernel_root.to_string_lossy().as_ref()),
            "org_demo",
        )
        .expect("init workspace");

        let mut first = sample_envelope();
        first.run_id = "run_a".to_string();
        let first_capture = enqueue_action(&root, &kernel_root, &first).expect("enqueue first");
        let mut second = sample_envelope();
        second.run_id = "run_b".to_string();
        second.action_type = "analysis".to_string();
        second.resource = "artifact_inspect".to_string();
        let second_capture = enqueue_action(&root, &kernel_root, &second).expect("enqueue second");

        let summary =
            run_queue_until_empty(&root, Some(kernel_root.to_string_lossy().as_ref()), 1, 5)
                .expect("run queue until empty");
        assert_eq!(summary.initial_pending, 2);
        assert_eq!(summary.passes_completed, 2);
        assert_eq!(summary.final_pending, 0);
        assert_eq!(summary.processed_jobs, 2);
        assert_eq!(summary.failed_jobs, 0);
        assert_eq!(summary.acked_jobs, 2);
        assert!(summary.drained);
        assert!(summary.progress_path.exists());
        assert!(summary.journal_path.exists());
        let progress = fs::read_to_string(&summary.progress_path).expect("progress file");
        assert!(progress.contains(r#""status": "queue_run_until_empty_complete""#));
        let journal = fs::read_to_string(&summary.journal_path).expect("journal file");
        assert!(journal.contains(r#""pass":1"#));
        assert!(journal.contains(r#""pass":2"#));
        assert!(journal.contains(&first_capture.input_hash));
        assert!(journal.contains(&second_capture.input_hash));
        let human = render_queue_run_until_empty_human(&summary);
        assert!(human.contains("QUEUE RUN-UNTIL-EMPTY"));
        assert!(human.contains("journal_path:"));
        let json = render_queue_run_until_empty_json(&summary);
        assert!(json.contains(r#""status": "queue_run_until_empty_complete""#));
    }

    #[test]
    fn shadow_backend_run_wasmtime_records_verified_warrant_artifacts() {
        let root = temp_path("loom-shadow-backend-run");
        fs::create_dir_all(&root).expect("root");
        let kernel_root = temp_path("loom-shadow-backend-run-kernel");
        scaffold_queue_kernel(&kernel_root, "shadow backend fixture", 0.5);
        init_workspace(
            &root,
            "embedded",
            Some(kernel_root.to_string_lossy().as_ref()),
            "org_demo",
        )
        .expect("init workspace");

        let capture = run_shadow_backend(&ShadowRunRequest {
            root: root.clone(),
            kernel_path: kernel_root.clone(),
            backend: ShadowBackendKind::Wasmtime,
            agent_id: "agent_atlas".to_string(),
            org_id: "org_demo".to_string(),
            action_type: "research".to_string(),
            resource: "system_info".to_string(),
            module_name: "builtin:system.info".to_string(),
            entrypoint: "run".to_string(),
            fuel_budget: 100_000,
            warrant: signed_shadow_warrant(u64::MAX - 10),
            wasm_bytes: builtin_system_info_guest_bytes(&render_wasm_system_info_request_json(
                &WasmSystemInfoRequest::default(),
            ))
            .expect("builtin system info guest"),
            command_program: None,
            command_args: Vec::new(),
            http_url: None,
            http_method: None,
            http_headers: Vec::new(),
            http_body_json: None,
        })
        .expect("shadow backend run");

        assert_eq!(capture.status, "shadow_run_captured");
        assert_eq!(capture.warrant_binding_status, "verified");
        assert!(capture.shadow_latest_path.exists());
        assert!(capture.parity_latest_path.exists());
        assert!(capture.execution_path.exists());
        assert!(capture
            .poge_merkle_root_hex
            .as_deref()
            .unwrap_or_default()
            .starts_with("0x"));

        let report = render_shadow_report(&root).expect("shadow report");
        assert!(report.contains("Runtime execution"));
        assert!(report.contains("verified"));
    }

    #[test]
    fn shadow_backend_run_rejects_invalid_warrant() {
        let root = temp_path("loom-shadow-backend-invalid-warrant");
        fs::create_dir_all(&root).expect("root");
        let kernel_root = temp_path("loom-shadow-backend-invalid-warrant-kernel");
        scaffold_queue_kernel(&kernel_root, "shadow backend invalid warrant", 0.5);
        init_workspace(
            &root,
            "embedded",
            Some(kernel_root.to_string_lossy().as_ref()),
            "org_demo",
        )
        .expect("init workspace");

        let mut warrant = signed_shadow_warrant(u64::MAX - 10);
        warrant.kernel_sig[0] ^= 0xFF;
        let error = run_shadow_backend(&ShadowRunRequest {
            root,
            kernel_path: kernel_root,
            backend: ShadowBackendKind::Wasmtime,
            agent_id: "agent_atlas".to_string(),
            org_id: "org_demo".to_string(),
            action_type: "research".to_string(),
            resource: "system_info".to_string(),
            module_name: "builtin:system.info".to_string(),
            entrypoint: "run".to_string(),
            fuel_budget: 100_000,
            warrant,
            wasm_bytes: builtin_system_info_guest_bytes(&render_wasm_system_info_request_json(
                &WasmSystemInfoRequest::default(),
            ))
            .expect("builtin system info guest"),
            command_program: None,
            command_args: Vec::new(),
            http_url: None,
            http_method: None,
            http_headers: Vec::new(),
            http_body_json: None,
        })
        .expect_err("invalid warrant should fail");

        assert!(
            error.contains("invalid") || error.contains("Warrant"),
            "{}",
            error
        );
    }

    #[test]
    fn shadow_backend_run_command_records_external_process_artifacts() {
        let root = temp_path("loom-shadow-backend-command");
        fs::create_dir_all(&root).expect("root");
        let kernel_root = temp_path("loom-shadow-backend-command-kernel");
        scaffold_queue_kernel(&kernel_root, "shadow backend command fixture", 0.5);
        init_workspace(
            &root,
            "embedded",
            Some(kernel_root.to_string_lossy().as_ref()),
            "org_demo",
        )
        .expect("init workspace");

        let capture = run_shadow_backend(&ShadowRunRequest {
            root,
            kernel_path: kernel_root,
            backend: ShadowBackendKind::Command,
            agent_id: "agent_atlas".to_string(),
            org_id: "org_demo".to_string(),
            action_type: "research".to_string(),
            resource: "command_exec".to_string(),
            module_name: "command:/bin/echo".to_string(),
            entrypoint: "command".to_string(),
            fuel_budget: 100_000,
            warrant: signed_shadow_warrant(u64::MAX - 10),
            wasm_bytes: Vec::new(),
            command_program: Some("/bin/echo".to_string()),
            command_args: vec!["shadow-command".to_string()],
            http_url: None,
            http_method: None,
            http_headers: Vec::new(),
            http_body_json: None,
        })
        .expect("shadow command backend run");

        assert_eq!(capture.status, "shadow_run_captured");
        assert_eq!(capture.backend, "command");
        assert_eq!(capture.host_backend, "external_command");
        assert_eq!(capture.warrant_binding_status, "verified");
        assert!(capture
            .host_response_json
            .as_deref()
            .unwrap_or_default()
            .contains("shadow-command"));
        assert!(capture
            .poge_merkle_root_hex
            .as_deref()
            .unwrap_or_default()
            .starts_with("0x"));
    }

    #[test]
    fn shadow_backend_run_http_records_external_fetch_artifacts() {
        let root = temp_path("loom-shadow-backend-http");
        fs::create_dir_all(&root).expect("root");
        let kernel_root = temp_path("loom-shadow-backend-http-kernel");
        scaffold_queue_kernel(&kernel_root, "shadow backend http fixture", 0.5);
        init_workspace(
            &root,
            "embedded",
            Some(kernel_root.to_string_lossy().as_ref()),
            "org_demo",
        )
        .expect("init workspace");

        let listener = TcpListener::bind("127.0.0.1:0").expect("bind http listener");
        let http_url = format!(
            "http://{}/shadow-http",
            listener.local_addr().expect("listener addr")
        );
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept http connection");
            let mut buf = [0_u8; 4096];
            let n = stream.read(&mut buf).expect("read request");
            let request = String::from_utf8_lossy(&buf[..n]).to_string();
            assert!(
                request.starts_with("GET /shadow-http HTTP/1.1"),
                "{}",
                request
            );
            assert!(request.contains("x-shadow-test: enabled"), "{}", request);
            let response =
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 17\r\nConnection: close\r\n\r\n{\"status\":\"ok\"}";
            stream
                .write_all(response.as_bytes())
                .expect("write response");
        });

        let capture = run_shadow_backend(&ShadowRunRequest {
            root,
            kernel_path: kernel_root,
            backend: ShadowBackendKind::Http,
            agent_id: "agent_atlas".to_string(),
            org_id: "org_demo".to_string(),
            action_type: "research".to_string(),
            resource: "http_fetch".to_string(),
            module_name: format!("http:GET:{}", http_url),
            entrypoint: "fetch".to_string(),
            fuel_budget: 100_000,
            warrant: signed_shadow_warrant(u64::MAX - 10),
            wasm_bytes: Vec::new(),
            command_program: None,
            command_args: Vec::new(),
            http_url: Some(http_url.clone()),
            http_method: Some("GET".to_string()),
            http_headers: vec![("x-shadow-test".to_string(), "enabled".to_string())],
            http_body_json: None,
        })
        .expect("shadow http backend run");

        server.join().expect("join http fixture");

        assert_eq!(capture.status, "shadow_run_captured");
        assert_eq!(capture.backend, "http");
        assert_eq!(capture.host_backend, "external_http");
        assert_eq!(capture.warrant_binding_status, "verified");
        assert_eq!(capture.entrypoint_result, Some(200));
        assert_eq!(capture.host_calls, vec!["http.fetch".to_string()]);
        assert!(capture
            .host_response_json
            .as_deref()
            .unwrap_or_default()
            .contains("\"http_status\": 200"));
        assert!(capture
            .poge_merkle_root_hex
            .as_deref()
            .unwrap_or_default()
            .starts_with("0x"));
    }

    #[test]
    fn shadow_report_prefers_typed_shadow_and_settlement_views() {
        let root = temp_path("loom-shadow-report-typed");
        fs::create_dir_all(&root).expect("root");
        let kernel_root = temp_path("loom-shadow-report-typed-kernel");
        scaffold_queue_kernel(&kernel_root, "shadow report typed fixture", 0.5);
        init_workspace(
            &root,
            "embedded",
            Some(kernel_root.to_string_lossy().as_ref()),
            "org_demo",
        )
        .expect("init workspace");

        let capture = run_shadow_backend(&ShadowRunRequest {
            root: root.clone(),
            kernel_path: kernel_root.clone(),
            backend: ShadowBackendKind::Wasmtime,
            agent_id: "agent_atlas".to_string(),
            org_id: "org_demo".to_string(),
            action_type: "research".to_string(),
            resource: "system_info".to_string(),
            module_name: "builtin:system.info".to_string(),
            entrypoint: "run".to_string(),
            fuel_budget: 100_000,
            warrant: signed_shadow_warrant(u64::MAX - 10),
            wasm_bytes: builtin_system_info_guest_bytes(&render_wasm_system_info_request_json(
                &WasmSystemInfoRequest::default(),
            ))
            .expect("builtin system info guest"),
            command_program: None,
            command_args: Vec::new(),
            http_url: None,
            http_method: None,
            http_headers: Vec::new(),
            http_body_json: None,
        })
        .expect("shadow backend run");

        let artifacts_root = artifact_root(&root).expect("artifact root");
        let zk_path = artifacts_root.join("zk").join("latest.json");
        let settlement_path = artifacts_root.join("settlement").join("latest.json");
        fs::create_dir_all(zk_path.parent().expect("zk dir")).expect("zk dir");
        fs::create_dir_all(settlement_path.parent().expect("settlement dir"))
            .expect("settlement dir");
        fs::write(
            &zk_path,
            serde_json::to_string_pretty(&serde_json::json!({
                "status": "zk_proof_prepared",
                "proof_backend": "sp1",
                "proof_mode": "bounded_adapter",
                "proof_id": "zkp_shadowtyped",
                "captured_at": "123456",
                "verification_status": "witness_bound",
                "agent_id": "agent_atlas",
                "org_id": "org_demo",
                "action_type": "research",
                "resource": "system_info",
                "warrant_binding_status": "verified",
                "warrant_id_hex": capture.warrant_id_hex,
                "poge_merkle_root_hex": capture.poge_merkle_root_hex,
                "witness_digest_hex": capture.poge_witness_digest_hex,
                "poge_trace_len": capture.poge_trace_len,
                "poge_epoch_start_ms": capture.poge_epoch_start_ms,
                "poge_epoch_end_ms": capture.poge_epoch_end_ms,
                "poge_session_label": capture.poge_session_label,
                "runtime_execution_path": capture.execution_path.display().to_string(),
                "kernel_path": kernel_root.display().to_string()
            }))
            .expect("zk json"),
        )
        .expect("write zk");
        fs::write(
            &settlement_path,
            serde_json::to_string_pretty(&serde_json::json!({
                "status": "zk_settlement_captured",
                "captured_at": "123457",
                "proof_backend": "sp1",
                "proof_status": "prepared",
                "proof_id": "zkp_shadowtyped",
                "court_status": "clear",
                "court_reason": "clear",
                "court_restrictions": [],
                "authority_status": "allowed",
                "authority_reason": "ok",
                "treasury_status": "committed",
                "treasury_reason": "committed",
                "reservation_id": "bud_shadow",
                "settlement_status": "prepared",
                "agent_id": "agent_atlas",
                "org_id": "org_demo",
                "action_type": "research",
                "resource": "system_info",
                "actual_cost_usd": 0.05,
                "warrant_id_hex": capture.warrant_id_hex,
                "witness_digest_hex": capture.poge_witness_digest_hex,
                "poge_merkle_root_hex": capture.poge_merkle_root_hex,
                "runtime_execution_path": capture.execution_path.display().to_string(),
                "zk_proof_path": zk_path.display().to_string(),
                "kernel_path": kernel_root.display().to_string()
            }))
            .expect("settlement json"),
        )
        .expect("write settlement");

        let report = render_shadow_report(&root).expect("shadow report");
        assert!(report.contains("backend:     wasmtime"), "{}", report);
        assert!(report.contains("proof_backend:      sp1"), "{}", report);
        assert!(
            report.contains("settlement_status:  prepared"),
            "{}",
            report
        );
        assert!(!report.contains("\"proof_backend\": \"sp1\""), "{}", report);
    }

    #[test]
    fn shadow_grpc_diagnostics_json_uses_typed_models() {
        let root = temp_path("loom-shadow-grpc-diag-typed");
        let diagnostics_dir = ensure_shadow_grpc_action_dir(&root).expect("grpc diag dir");
        let latest_path = diagnostics_dir.join("latest.json");
        let stream_path = diagnostics_dir.join("stream.jsonl");
        fs::write(
            &latest_path,
            serde_json::to_string_pretty(&serde_json::json!({
                "status": "grpc_action_executed",
                "captured_at": "2026-04-04T00:00:00Z",
                "grpc_target": "grpc://127.0.0.1:9000",
                "grpc_rpc": "meridian.a2a.action.v1.ActionService/ExecuteAction",
                "grpc_transport": "plaintext",
                "grpc_allow_unknown_fields": true,
                "grpc_max_time_seconds": 20,
                "grpc_schema": "proto_inline",
                "grpc_request_id": "req_typed_latest",
                "grpc_action_kind": "research",
                "grpc_action_objective": "typed parse",
                "grpc_action_skill": "atlas",
                "grpc_proto_count": 1,
                "grpc_protoset_count": 1,
                "grpc_import_path_count": 1,
                "grpc_authority": "localhost",
                "exit_code": 0
            }))
            .expect("latest json"),
        )
        .expect("write latest");
        fs::write(
            &stream_path,
            format!(
                "{}\n{}\n",
                serde_json::json!({
                    "status": "grpc_action_executed",
                    "captured_at": "2026-04-04T00:00:00Z",
                    "grpc_target": "grpc://127.0.0.1:9000",
                    "grpc_rpc": "meridian.a2a.action.v1.ActionService/ExecuteAction",
                    "grpc_transport": "plaintext",
                    "grpc_allow_unknown_fields": true,
                    "grpc_max_time_seconds": 20,
                    "grpc_schema": "proto_inline",
                    "grpc_request_id": "req_typed_stream_1",
                    "grpc_action_kind": "research",
                    "grpc_action_objective": "typed parse",
                    "grpc_action_skill": "atlas",
                    "grpc_proto_count": 1,
                    "grpc_protoset_count": 1,
                    "grpc_import_path_count": 1,
                    "grpc_authority": "localhost",
                    "exit_code": 0
                }),
                serde_json::json!({
                    "status": "grpc_action_executed",
                    "captured_at": "2026-04-04T00:00:01Z",
                    "grpc_target": "grpc://127.0.0.1:9000",
                    "grpc_rpc": "meridian.a2a.action.v1.ActionService/ExecuteAction",
                    "grpc_transport": "plaintext",
                    "grpc_allow_unknown_fields": false,
                    "grpc_max_time_seconds": 20,
                    "grpc_schema": "proto_inline",
                    "grpc_request_id": "req_typed_stream_2",
                    "grpc_action_kind": "research",
                    "grpc_action_objective": "typed parse",
                    "grpc_action_skill": "atlas",
                    "grpc_proto_count": 1,
                    "grpc_protoset_count": 1,
                    "grpc_import_path_count": 1,
                    "grpc_authority": "localhost",
                    "exit_code": 0
                })
            ),
        )
        .expect("write stream");

        let rendered = render_shadow_grpc_action_diagnostics_json(&root, 1).expect("render json");
        let value: Value = serde_json::from_str(&rendered).expect("parse json");
        assert_eq!(value.get("status").and_then(Value::as_str), Some("ok"));
        assert_eq!(
            value
                .pointer("/latest/grpc_request_id")
                .and_then(Value::as_str),
            Some("req_typed_latest")
        );
        assert_eq!(
            value
                .pointer("/recent/0/grpc_request_id")
                .and_then(Value::as_str),
            Some("req_typed_stream_2")
        );
    }

    #[test]
    fn shadow_report_loads_typed_settlement_alias_fields() {
        let root = temp_path("loom-shadow-settlement-alias");
        fs::create_dir_all(&root).expect("root");
        init_workspace(&root, "embedded", None, "org_demo").expect("init workspace");
        let shadow_dir = ensure_shadow_dir(&root).expect("shadow dir");
        fs::write(
            shadow_dir.join("decision.json"),
            serde_json::to_string_pretty(&serde_json::json!({
                "status": "decision_captured",
                "overall_decision": "allow",
                "agent_id": "agent_atlas",
                "org_id": "org_demo"
            }))
            .expect("decision json"),
        )
        .expect("write decision");

        let artifacts_root = artifact_root(&root).expect("artifact root");
        let settlement_path = artifacts_root.join("settlement").join("latest.json");
        fs::create_dir_all(settlement_path.parent().expect("settlement dir"))
            .expect("settlement dir");
        fs::write(
            &settlement_path,
            serde_json::to_string_pretty(&serde_json::json!({
                "status": "zk_settlement_captured",
                "captured_at": "2026-04-04T00:00:02Z",
                "proof_backend": "sp1",
                "proof_status": "prepared",
                "proof_id": "zkp_alias",
                "court_status": "clear",
                "authority_status": "allowed",
                "treasury_status": "committed",
                "settlement_status": "prepared",
                "reservation_id": "bud_alias",
                "actual_cost_usd": 0.025,
                "witness_digest_hex": "0xabc",
                "poge_merkle_root_hex": "0xdef"
            }))
            .expect("settlement json"),
        )
        .expect("write settlement");

        let report = render_shadow_report(&root).expect("shadow report");
        assert!(
            report.contains("proof_id:           zkp_alias"),
            "{}",
            report
        );
        assert!(
            report.contains("reservation_id:     bud_alias"),
            "{}",
            report
        );
        assert!(report.contains("poge_merkle_root:   0xdef"), "{}", report);
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

    fn signed_shadow_warrant(expiry_epoch_ms: u64) -> KernelWarrant {
        let signer = SigningKey::from_bytes(&[17u8; 32]);
        let mut id = [0u8; 32];
        for (index, slot) in id.iter_mut().enumerate() {
            *slot = (index as u8).wrapping_mul(5).wrapping_add(3);
        }
        let scope_cbor = vec![0xA1, 0x66, b's', b'h', b'a', b'd', b'o', b'w', 0xF5];
        let scope_hash: [u8; 32] = Sha256::digest(&scope_cbor).into();
        let mut message = Vec::with_capacity(32 + 32 + 8);
        message.extend_from_slice(&id);
        message.extend_from_slice(&scope_hash);
        message.extend_from_slice(&expiry_epoch_ms.to_be_bytes());
        let signature: Signature = signer.sign(&message);
        KernelWarrant {
            id,
            scope_cbor,
            expiry_epoch_ms,
            kernel_sig: signature.to_bytes(),
            kernel_pub: signer.verifying_key().to_bytes(),
        }
    }

    fn sample_identity() -> AgentIdentityResolution {
        AgentIdentityResolution {
            agent_id: "agent_atlas".to_string(),
            agent_name: "Atlas".to_string(),
            org_id: "org_demo".to_string(),
            role: "analyst".to_string(),
            economy_key: "atlas".to_string(),
            approval_required: false,
            max_per_run_usd: Some(0.5),
            restrictions: vec![],
            sanction_decision: "clear".to_string(),
            runtime_id: "local_kernel".to_string(),
            runtime_label: "Local Kernel Runtime".to_string(),
            bound_org_id: "org_demo".to_string(),
            boundary_name: "workspace".to_string(),
            identity_model: "session".to_string(),
            runtime_registered: true,
            registration_status: "registered".to_string(),
            source: "kernel_agent_registry".to_string(),
        }
    }

    fn sample_envelope() -> ActionEnvelope {
        ActionEnvelope {
            agent_id: "agent_atlas".to_string(),
            agent_name: "Atlas".to_string(),
            org_id: "org_demo".to_string(),
            runtime_id: "local_kernel".to_string(),
            runtime_label: "Local Kernel Runtime".to_string(),
            action_type: "research".to_string(),
            resource: "web_search".to_string(),
            capability_name: String::new(),
            payload_json: String::new(),
            estimated_cost_usd: 0.25,
            run_id: "run_1".to_string(),
            session_id: "session_1".to_string(),
            source: "loom_experimental_preflight".to_string(),
        }
    }

    fn sample_capability_envelope() -> ActionEnvelope {
        ActionEnvelope {
            capability_name: "loom.echo.v1".to_string(),
            payload_json: "{\"message\":\"hello from capability lane\"}".to_string(),
            ..sample_envelope()
        }
    }
}
