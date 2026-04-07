//! Host-side Wasm configuration plumbing.
//!
//! This module is intentionally honest: it prepares host configuration shapes
//! that can later be wired into Wasmtime or another engine, but it does not
//! pretend to execute components today.

use std::collections::BTreeMap;

use serde_json::{json, Value};

use crate::wasm_limits::{default_limits, render_limits_human, validate_limits, WasmStoreLimits};
use crate::wasm_profiles::{render_pooling_config_human, PoolingConfig, PoolingProfile};

#[cfg(test)]
#[allow(clippy::duplicate_mod)]
#[path = "provider_router.rs"]
mod provider_router;

#[path = "wasm_runner.rs"]
mod wasm_runner;

#[allow(unused_imports)]
pub use wasm_runner::{
    run_wasm_guest, WasmExecutionRequest, WasmExecutionResult, WasmGuestSource, WasmMemoryProbe,
};

pub const WASM_HOST_CALL_NAMESPACE: &str = "loom_host";
pub const HOST_BROWSER_NAVIGATE: &str = "host_browser_navigate";
pub const HOST_SCHEDULE_HEARTBEAT: &str = "host_schedule_heartbeat";
pub const HOST_TERMINAL_EXEC: &str = "host_terminal_exec";
pub const HOST_SYSTEM_INFO: &str = "host_system_info";
pub const HOST_FS_READ: &str = "host_fs_read";
pub const HOST_FS_WRITE: &str = "host_fs_write";
pub const HOST_LLM_INFERENCE: &str = "host_llm_inference";
pub const HOST_KV_GET: &str = "host_kv_get";
pub const HOST_KV_SET: &str = "host_kv_set";
pub const WASM_HOST_REQUEST_OFFSET: i32 = 1_024;
pub const WASM_HOST_RESPONSE_OFFSET: i32 = 8_192;
pub const WASM_HOST_RESPONSE_CAPACITY: i32 = 16_384;
pub const WASM_HOST_RESULT_PTR_EXPORT: &str = "loom_result_ptr";
pub const WASM_HOST_RESULT_LEN_EXPORT: &str = "loom_result_len";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WasmHostCallKind {
    BrowserNavigate,
    ScheduleHeartbeat,
    TerminalExec,
    SystemInfo,
    FsRead,
    FsWrite,
    LlmInference,
    KvGet,
    KvSet,
}

impl WasmHostCallKind {
    pub fn import_name(self) -> &'static str {
        match self {
            Self::BrowserNavigate => HOST_BROWSER_NAVIGATE,
            Self::ScheduleHeartbeat => HOST_SCHEDULE_HEARTBEAT,
            Self::TerminalExec => HOST_TERMINAL_EXEC,
            Self::SystemInfo => HOST_SYSTEM_INFO,
            Self::FsRead => HOST_FS_READ,
            Self::FsWrite => HOST_FS_WRITE,
            Self::LlmInference => HOST_LLM_INFERENCE,
            Self::KvGet => HOST_KV_GET,
            Self::KvSet => HOST_KV_SET,
        }
    }

    pub fn purpose(self) -> &'static str {
        match self {
            Self::BrowserNavigate => "bounded browser navigation and semantic snapshot capture",
            Self::ScheduleHeartbeat => "register or refresh proactive background work independent of user input",
            Self::TerminalExec => "execute a bounded local argv command inside a constrained workspace context",
            Self::SystemInfo => "collect bounded host diagnostics from a fixed allowlist without exposing arbitrary host access",
            Self::FsRead => "read a bounded UTF-8 excerpt from the runtime workspace sandbox or a fixed diagnostic allowlist",
            Self::FsWrite => "write bounded UTF-8 content into the runtime workspace sandbox",
            Self::LlmInference => "perform bounded native inference through the host-side OpenAI chat completions bridge",
            Self::KvGet => "read a namespaced value from the runtime-backed KV memory file",
            Self::KvSet => "persist a namespaced value into the runtime-backed KV memory file",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum WasmHostCallDecision {
    Pending,
    Allowed,
    Denied,
}

impl WasmHostCallDecision {
    pub fn label(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Allowed => "allowed",
            Self::Denied => "denied",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WasmHostCallStatusCode {
    Success,
    InvalidRequest,
    PermissionDenied,
    ResponseTooLarge,
    Unsupported,
    InternalError,
}

impl WasmHostCallStatusCode {
    pub fn code(self) -> i32 {
        match self {
            Self::Success => 0,
            Self::InvalidRequest => -1,
            Self::PermissionDenied => -2,
            Self::ResponseTooLarge => -3,
            Self::Unsupported => -4,
            Self::InternalError => -5,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WasmHostSecurityContext {
    pub capability_name: String,
    pub agent_id: String,
    pub org_id: String,
    pub session_id: String,
    pub operation_id: String,
    pub max_timeout_ms: u64,
    pub max_response_bytes: usize,
    pub allowed_hosts: Vec<String>,
    pub allowed_workdir_roots: Vec<String>,
    pub require_user_present: bool,
}

impl Default for WasmHostSecurityContext {
    fn default() -> Self {
        Self {
            capability_name: String::new(),
            agent_id: String::new(),
            org_id: String::new(),
            session_id: String::new(),
            operation_id: String::new(),
            max_timeout_ms: 3_000,
            max_response_bytes: 16_384,
            allowed_hosts: Vec::new(),
            allowed_workdir_roots: vec![".".to_string()],
            require_user_present: false,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WasmBrowserNavigateRequest {
    pub security: WasmHostSecurityContext,
    pub session_id: String,
    pub url: String,
    pub allowed_hosts: Vec<String>,
    pub wait_for: String,
    pub timeout_ms: u64,
    pub capture_semantic_snapshot: bool,
}

impl Default for WasmBrowserNavigateRequest {
    fn default() -> Self {
        Self {
            security: WasmHostSecurityContext::default(),
            session_id: String::new(),
            url: String::new(),
            allowed_hosts: Vec::new(),
            wait_for: "dom_content_loaded".to_string(),
            timeout_ms: 4_000,
            capture_semantic_snapshot: true,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WasmBrowserNavigateResponse {
    pub decision: WasmHostCallDecision,
    pub navigation_id: String,
    pub final_url: String,
    pub http_status: Option<u16>,
    pub content_type: String,
    pub title: String,
    pub body_excerpt_utf8: String,
    pub semantic_snapshot_ref: String,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum WasmHeartbeatScheduleKind {
    Once,
    Interval,
    Cron,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WasmHeartbeatScheduleRequest {
    pub security: WasmHostSecurityContext,
    pub heartbeat_id: String,
    pub capability_name: String,
    pub schedule_kind: WasmHeartbeatScheduleKind,
    pub schedule_expression: String,
    pub not_before_unix_ms: Option<u64>,
    pub interval_seconds: Option<u64>,
    pub jitter_seconds: u64,
    pub payload_json: String,
    pub max_runs: Option<u32>,
}

impl Default for WasmHeartbeatScheduleRequest {
    fn default() -> Self {
        Self {
            security: WasmHostSecurityContext::default(),
            heartbeat_id: String::new(),
            capability_name: String::new(),
            schedule_kind: WasmHeartbeatScheduleKind::Interval,
            schedule_expression: String::new(),
            not_before_unix_ms: None,
            interval_seconds: Some(300),
            jitter_seconds: 15,
            payload_json: String::new(),
            max_runs: None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WasmHeartbeatScheduleResponse {
    pub decision: WasmHostCallDecision,
    pub heartbeat_id: String,
    pub next_fire_at_unix_ms: Option<u64>,
    pub accepted_run_id: String,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WasmTerminalExecRequest {
    pub security: WasmHostSecurityContext,
    pub argv: Vec<String>,
    pub working_dir: String,
    pub env_allowlist: Vec<String>,
    pub stdin_utf8: String,
    pub timeout_ms: u64,
    pub max_output_bytes: usize,
    pub require_clean_environment: bool,
}

impl Default for WasmTerminalExecRequest {
    fn default() -> Self {
        Self {
            security: WasmHostSecurityContext::default(),
            argv: Vec::new(),
            working_dir: ".".to_string(),
            env_allowlist: Vec::new(),
            stdin_utf8: String::new(),
            timeout_ms: 2_000,
            max_output_bytes: 16_384,
            require_clean_environment: true,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WasmTerminalExecResponse {
    pub decision: WasmHostCallDecision,
    pub exit_code: Option<i32>,
    pub stdout_utf8: String,
    pub stderr_utf8: String,
    pub timed_out: bool,
    pub truncated: bool,
    pub note: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct WasmSystemInfoRequest {
    pub security: WasmHostSecurityContext,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WasmSystemInfoResponse {
    pub decision: WasmHostCallDecision,
    pub uname_utf8: String,
    pub os_release_utf8: String,
    pub hostname_utf8: String,
    pub truncated: bool,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WasmFsReadRequest {
    pub security: WasmHostSecurityContext,
    pub path: String,
    pub max_bytes: usize,
}

impl Default for WasmFsReadRequest {
    fn default() -> Self {
        Self {
            security: WasmHostSecurityContext::default(),
            path: String::new(),
            max_bytes: 8_192,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WasmFsReadResponse {
    pub decision: WasmHostCallDecision,
    pub path: String,
    pub content_utf8: String,
    pub bytes_read: usize,
    pub truncated: bool,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WasmFsWriteRequest {
    pub security: WasmHostSecurityContext,
    pub path: String,
    pub content_utf8: String,
    pub create_dirs: bool,
    pub append: bool,
}

impl Default for WasmFsWriteRequest {
    fn default() -> Self {
        Self {
            security: WasmHostSecurityContext::default(),
            path: String::new(),
            content_utf8: String::new(),
            create_dirs: true,
            append: false,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WasmFsWriteResponse {
    pub decision: WasmHostCallDecision,
    pub path: String,
    pub bytes_written: usize,
    pub created_dirs: bool,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WasmLlmInferenceRequest {
    pub security: WasmHostSecurityContext,
    pub provider_profile: String,
    pub model: String,
    pub system_prompt: String,
    pub user_prompt: String,
    pub max_tokens: Option<u32>,
}

impl Default for WasmLlmInferenceRequest {
    fn default() -> Self {
        Self {
            security: WasmHostSecurityContext::default(),
            provider_profile: String::new(),
            model: "qwen2.5:7b".to_string(),
            system_prompt: String::new(),
            user_prompt: String::new(),
            max_tokens: Some(256),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WasmLlmInferenceResponse {
    pub decision: WasmHostCallDecision,
    pub model: String,
    pub output_text: String,
    pub finish_reason: String,
    pub prompt_tokens: Option<u64>,
    pub completion_tokens: Option<u64>,
    pub total_tokens: Option<u64>,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WasmKvGetRequest {
    pub security: WasmHostSecurityContext,
    pub namespace: String,
    pub key: String,
}

impl Default for WasmKvGetRequest {
    fn default() -> Self {
        Self {
            security: WasmHostSecurityContext::default(),
            namespace: "default".to_string(),
            key: String::new(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WasmKvGetResponse {
    pub decision: WasmHostCallDecision,
    pub namespace: String,
    pub key: String,
    pub found: bool,
    pub value_json: String,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WasmKvSetRequest {
    pub security: WasmHostSecurityContext,
    pub namespace: String,
    pub key: String,
    pub value_json: String,
}

impl Default for WasmKvSetRequest {
    fn default() -> Self {
        Self {
            security: WasmHostSecurityContext::default(),
            namespace: "default".to_string(),
            key: String::new(),
            value_json: "null".to_string(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WasmKvSetResponse {
    pub decision: WasmHostCallDecision,
    pub namespace: String,
    pub key: String,
    pub stored: bool,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WasmHostCallSignature {
    pub kind: WasmHostCallKind,
    pub import_module: &'static str,
    pub request_type: &'static str,
    pub response_type: &'static str,
    pub purpose: &'static str,
    pub truth_boundary: &'static str,
}

impl WasmHostCallSignature {
    pub fn import_name(&self) -> &'static str {
        self.kind.import_name()
    }
}

pub fn wasm_host_call_signatures() -> Vec<WasmHostCallSignature> {
    vec![
        WasmHostCallSignature {
            kind: WasmHostCallKind::BrowserNavigate,
            import_module: WASM_HOST_CALL_NAMESPACE,
            request_type: "WasmBrowserNavigateRequest",
            response_type: "WasmBrowserNavigateResponse",
            purpose: WasmHostCallKind::BrowserNavigate.purpose(),
            truth_boundary: "bounded synchronous HTTP navigation is locally real; hosted browser automation remains out of scope here",
        },
        WasmHostCallSignature {
            kind: WasmHostCallKind::ScheduleHeartbeat,
            import_module: WASM_HOST_CALL_NAMESPACE,
            request_type: "WasmHeartbeatScheduleRequest",
            response_type: "WasmHeartbeatScheduleResponse",
            purpose: WasmHostCallKind::ScheduleHeartbeat.purpose(),
            truth_boundary: "foundation only; no autonomous scheduler is claimed active until a runtime service implements leases and acknowledgements",
        },
        WasmHostCallSignature {
            kind: WasmHostCallKind::TerminalExec,
            import_module: WASM_HOST_CALL_NAMESPACE,
            request_type: "WasmTerminalExecRequest",
            response_type: "WasmTerminalExecResponse",
            purpose: WasmHostCallKind::TerminalExec.purpose(),
            truth_boundary: "bounded local command execution is real only inside explicit timeout and path policy",
        },
        WasmHostCallSignature {
            kind: WasmHostCallKind::SystemInfo,
            import_module: WASM_HOST_CALL_NAMESPACE,
            request_type: "WasmSystemInfoRequest",
            response_type: "WasmSystemInfoResponse",
            purpose: WasmHostCallKind::SystemInfo.purpose(),
            truth_boundary: "system diagnostics are limited to a fixed allowlist of host metadata and never expose arbitrary shell access",
        },
        WasmHostCallSignature {
            kind: WasmHostCallKind::FsRead,
            import_module: WASM_HOST_CALL_NAMESPACE,
            request_type: "WasmFsReadRequest",
            response_type: "WasmFsReadResponse",
            purpose: WasmHostCallKind::FsRead.purpose(),
            truth_boundary: "file reads are limited to the local Loom runtime workspace sandbox plus a small diagnostic allowlist",
        },
        WasmHostCallSignature {
            kind: WasmHostCallKind::FsWrite,
            import_module: WASM_HOST_CALL_NAMESPACE,
            request_type: "WasmFsWriteRequest",
            response_type: "WasmFsWriteResponse",
            purpose: WasmHostCallKind::FsWrite.purpose(),
            truth_boundary: "file writes are limited to the local Loom runtime workspace sandbox",
        },
        WasmHostCallSignature {
            kind: WasmHostCallKind::LlmInference,
            import_module: WASM_HOST_CALL_NAMESPACE,
            request_type: "WasmLlmInferenceRequest",
            response_type: "WasmLlmInferenceResponse",
            purpose: WasmHostCallKind::LlmInference.purpose(),
            truth_boundary: "native inference is bounded by host-side API policy and never exposes credentials to Wasm",
        },
        WasmHostCallSignature {
            kind: WasmHostCallKind::KvGet,
            import_module: WASM_HOST_CALL_NAMESPACE,
            request_type: "WasmKvGetRequest",
            response_type: "WasmKvGetResponse",
            purpose: WasmHostCallKind::KvGet.purpose(),
            truth_boundary: "KV lookups are local runtime-state reads only",
        },
        WasmHostCallSignature {
            kind: WasmHostCallKind::KvSet,
            import_module: WASM_HOST_CALL_NAMESPACE,
            request_type: "WasmKvSetRequest",
            response_type: "WasmKvSetResponse",
            purpose: WasmHostCallKind::KvSet.purpose(),
            truth_boundary: "KV writes are local runtime-state mutations only",
        },
    ]
}

pub fn render_wasm_browser_navigate_request_json(request: &WasmBrowserNavigateRequest) -> String {
    json!({
        "security": render_security_context_value(&request.security),
        "session_id": request.session_id,
        "url": request.url,
        "allowed_hosts": request.allowed_hosts,
        "wait_for": request.wait_for,
        "timeout_ms": request.timeout_ms,
        "capture_semantic_snapshot": request.capture_semantic_snapshot,
    })
    .to_string()
}

pub fn render_wasm_terminal_exec_request_json(request: &WasmTerminalExecRequest) -> String {
    json!({
        "security": render_security_context_value(&request.security),
        "argv": request.argv,
        "working_dir": request.working_dir,
        "env_allowlist": request.env_allowlist,
        "stdin_utf8": request.stdin_utf8,
        "timeout_ms": request.timeout_ms,
        "max_output_bytes": request.max_output_bytes,
        "require_clean_environment": request.require_clean_environment,
    })
    .to_string()
}

pub fn render_wasm_heartbeat_schedule_request_json(
    request: &WasmHeartbeatScheduleRequest,
) -> String {
    json!({
        "security": render_security_context_value(&request.security),
        "heartbeat_id": request.heartbeat_id,
        "capability_name": request.capability_name,
        "schedule_kind": match request.schedule_kind {
            WasmHeartbeatScheduleKind::Once => "once",
            WasmHeartbeatScheduleKind::Interval => "interval",
            WasmHeartbeatScheduleKind::Cron => "cron",
        },
        "schedule_expression": request.schedule_expression,
        "not_before_unix_ms": request.not_before_unix_ms,
        "interval_seconds": request.interval_seconds,
        "jitter_seconds": request.jitter_seconds,
        "payload_json": request.payload_json,
        "max_runs": request.max_runs,
    })
    .to_string()
}

pub fn render_wasm_system_info_request_json(request: &WasmSystemInfoRequest) -> String {
    json!({
        "security": render_security_context_value(&request.security),
    })
    .to_string()
}

pub fn render_wasm_fs_read_request_json(request: &WasmFsReadRequest) -> String {
    json!({
        "security": render_security_context_value(&request.security),
        "path": request.path,
        "max_bytes": request.max_bytes,
    })
    .to_string()
}

pub fn render_wasm_fs_write_request_json(request: &WasmFsWriteRequest) -> String {
    json!({
        "security": render_security_context_value(&request.security),
        "path": request.path,
        "content_utf8": request.content_utf8,
        "create_dirs": request.create_dirs,
        "append": request.append,
    })
    .to_string()
}

pub fn render_wasm_llm_inference_request_json(request: &WasmLlmInferenceRequest) -> String {
    json!({
        "security": render_security_context_value(&request.security),
        "model": request.model,
        "system_prompt": request.system_prompt,
        "user_prompt": request.user_prompt,
        "max_tokens": request.max_tokens,
    })
    .to_string()
}

pub fn render_wasm_kv_get_request_json(request: &WasmKvGetRequest) -> String {
    json!({
        "security": render_security_context_value(&request.security),
        "namespace": request.namespace,
        "key": request.key,
    })
    .to_string()
}

pub fn render_wasm_kv_set_request_json(request: &WasmKvSetRequest) -> String {
    json!({
        "security": render_security_context_value(&request.security),
        "namespace": request.namespace,
        "key": request.key,
        "value_json": request.value_json,
    })
    .to_string()
}

pub fn builtin_browser_navigate_guest_bytes(request_json: &str) -> Result<Vec<u8>, String> {
    build_host_call_guest(HOST_BROWSER_NAVIGATE, request_json)
}

pub fn builtin_terminal_exec_guest_bytes(request_json: &str) -> Result<Vec<u8>, String> {
    build_host_call_guest(HOST_TERMINAL_EXEC, request_json)
}

pub fn builtin_heartbeat_schedule_guest_bytes(request_json: &str) -> Result<Vec<u8>, String> {
    build_host_call_guest(HOST_SCHEDULE_HEARTBEAT, request_json)
}

pub fn builtin_system_info_guest_bytes(request_json: &str) -> Result<Vec<u8>, String> {
    build_host_call_guest(HOST_SYSTEM_INFO, request_json)
}

pub fn builtin_fs_read_guest_bytes(request_json: &str) -> Result<Vec<u8>, String> {
    build_host_call_guest(HOST_FS_READ, request_json)
}

pub fn builtin_fs_write_guest_bytes(request_json: &str) -> Result<Vec<u8>, String> {
    build_host_call_guest(HOST_FS_WRITE, request_json)
}

pub fn builtin_llm_inference_guest_bytes(request_json: &str) -> Result<Vec<u8>, String> {
    build_host_call_guest(HOST_LLM_INFERENCE, request_json)
}

pub fn builtin_kv_get_guest_bytes(request_json: &str) -> Result<Vec<u8>, String> {
    build_host_call_guest(HOST_KV_GET, request_json)
}

pub fn builtin_kv_set_guest_bytes(request_json: &str) -> Result<Vec<u8>, String> {
    build_host_call_guest(HOST_KV_SET, request_json)
}

pub(crate) fn parse_wasm_browser_navigate_request(
    raw: &str,
) -> Result<WasmBrowserNavigateRequest, String> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid browser navigate request json: {error}"))?;
    Ok(WasmBrowserNavigateRequest {
        security: parse_security_context(value.get("security")),
        session_id: value_string(value.get("session_id")),
        url: value_string(value.get("url")),
        allowed_hosts: value_string_array(value.get("allowed_hosts")),
        wait_for: value_string_or(value.get("wait_for"), "dom_content_loaded"),
        timeout_ms: value_u64_or(value.get("timeout_ms"), 4_000),
        capture_semantic_snapshot: value_bool_or(value.get("capture_semantic_snapshot"), true),
    })
}

pub(crate) fn parse_wasm_terminal_exec_request(
    raw: &str,
) -> Result<WasmTerminalExecRequest, String> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid terminal exec request json: {error}"))?;
    Ok(WasmTerminalExecRequest {
        security: parse_security_context(value.get("security")),
        argv: value_string_array(value.get("argv")),
        working_dir: value_string_or(value.get("working_dir"), "."),
        env_allowlist: value_string_array(value.get("env_allowlist")),
        stdin_utf8: value_string(value.get("stdin_utf8")),
        timeout_ms: value_u64_or(value.get("timeout_ms"), 2_000),
        max_output_bytes: value_usize_or(value.get("max_output_bytes"), 16_384),
        require_clean_environment: value_bool_or(value.get("require_clean_environment"), true),
    })
}

pub(crate) fn parse_wasm_heartbeat_schedule_request(
    raw: &str,
) -> Result<WasmHeartbeatScheduleRequest, String> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid heartbeat request json: {error}"))?;
    let schedule_kind = match value_string_or(value.get("schedule_kind"), "interval").as_str() {
        "once" => WasmHeartbeatScheduleKind::Once,
        "cron" => WasmHeartbeatScheduleKind::Cron,
        _ => WasmHeartbeatScheduleKind::Interval,
    };
    Ok(WasmHeartbeatScheduleRequest {
        security: parse_security_context(value.get("security")),
        heartbeat_id: value_string(value.get("heartbeat_id")),
        capability_name: value_string(value.get("capability_name")),
        schedule_kind,
        schedule_expression: value_string(value.get("schedule_expression")),
        not_before_unix_ms: value.get("not_before_unix_ms").and_then(Value::as_u64),
        interval_seconds: value.get("interval_seconds").and_then(Value::as_u64),
        jitter_seconds: value_u64_or(value.get("jitter_seconds"), 15),
        payload_json: value_string(value.get("payload_json")),
        max_runs: value
            .get("max_runs")
            .and_then(Value::as_u64)
            .map(|value| value as u32),
    })
}

pub(crate) fn parse_wasm_system_info_request(raw: &str) -> Result<WasmSystemInfoRequest, String> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid system info request json: {error}"))?;
    Ok(WasmSystemInfoRequest {
        security: parse_security_context(value.get("security")),
    })
}

pub(crate) fn parse_wasm_fs_read_request(raw: &str) -> Result<WasmFsReadRequest, String> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid fs read request json: {error}"))?;
    Ok(WasmFsReadRequest {
        security: parse_security_context(value.get("security")),
        path: value_string(value.get("path")),
        max_bytes: value_usize_or(value.get("max_bytes"), 8_192),
    })
}

pub(crate) fn parse_wasm_fs_write_request(raw: &str) -> Result<WasmFsWriteRequest, String> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid fs write request json: {error}"))?;
    Ok(WasmFsWriteRequest {
        security: parse_security_context(value.get("security")),
        path: value_string(value.get("path")),
        content_utf8: value_string(value.get("content_utf8")),
        create_dirs: value_bool_or(value.get("create_dirs"), true),
        append: value_bool_or(value.get("append"), false),
    })
}

pub(crate) fn parse_wasm_llm_inference_request(
    raw: &str,
) -> Result<WasmLlmInferenceRequest, String> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid llm inference request json: {error}"))?;
    Ok(WasmLlmInferenceRequest {
        security: parse_security_context(value.get("security")),
        provider_profile: value_string_or(value.get("provider_profile"), ""),
        model: value_string_or(value.get("model"), "qwen2.5:7b"),
        system_prompt: value_string(value.get("system_prompt")),
        user_prompt: value_string(value.get("user_prompt")),
        max_tokens: value
            .get("max_tokens")
            .and_then(Value::as_u64)
            .map(|value| value as u32),
    })
}

pub(crate) fn parse_wasm_kv_get_request(raw: &str) -> Result<WasmKvGetRequest, String> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid kv get request json: {error}"))?;
    Ok(WasmKvGetRequest {
        security: parse_security_context(value.get("security")),
        namespace: value_string_or(value.get("namespace"), "default"),
        key: value_string(value.get("key")),
    })
}

pub(crate) fn parse_wasm_kv_set_request(raw: &str) -> Result<WasmKvSetRequest, String> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid kv set request json: {error}"))?;
    Ok(WasmKvSetRequest {
        security: parse_security_context(value.get("security")),
        namespace: value_string_or(value.get("namespace"), "default"),
        key: value_string(value.get("key")),
        value_json: value_string_or(value.get("value_json"), "null"),
    })
}

pub(crate) fn render_wasm_browser_navigate_response_json(
    response: &WasmBrowserNavigateResponse,
) -> String {
    json!({
        "decision": response.decision.label(),
        "navigation_id": response.navigation_id,
        "final_url": response.final_url,
        "http_status": response.http_status,
        "content_type": response.content_type,
        "title": response.title,
        "body_excerpt_utf8": response.body_excerpt_utf8,
        "semantic_snapshot_ref": response.semantic_snapshot_ref,
        "note": response.note,
    })
    .to_string()
}

pub(crate) fn render_wasm_terminal_exec_response_json(
    response: &WasmTerminalExecResponse,
) -> String {
    json!({
        "decision": response.decision.label(),
        "exit_code": response.exit_code,
        "stdout_utf8": response.stdout_utf8,
        "stderr_utf8": response.stderr_utf8,
        "timed_out": response.timed_out,
        "truncated": response.truncated,
        "note": response.note,
    })
    .to_string()
}

pub(crate) fn render_wasm_heartbeat_schedule_response_json(
    response: &WasmHeartbeatScheduleResponse,
) -> String {
    json!({
        "decision": response.decision.label(),
        "heartbeat_id": response.heartbeat_id,
        "next_fire_at_unix_ms": response.next_fire_at_unix_ms,
        "accepted_run_id": response.accepted_run_id,
        "note": response.note,
    })
    .to_string()
}

pub(crate) fn render_wasm_system_info_response_json(response: &WasmSystemInfoResponse) -> String {
    json!({
        "decision": response.decision.label(),
        "uname_utf8": response.uname_utf8,
        "os_release_utf8": response.os_release_utf8,
        "hostname_utf8": response.hostname_utf8,
        "truncated": response.truncated,
        "note": response.note,
    })
    .to_string()
}

pub(crate) fn render_wasm_fs_read_response_json(response: &WasmFsReadResponse) -> String {
    json!({
        "decision": response.decision.label(),
        "path": response.path,
        "content_utf8": response.content_utf8,
        "bytes_read": response.bytes_read,
        "truncated": response.truncated,
        "note": response.note,
    })
    .to_string()
}

pub(crate) fn render_wasm_fs_write_response_json(response: &WasmFsWriteResponse) -> String {
    json!({
        "decision": response.decision.label(),
        "path": response.path,
        "bytes_written": response.bytes_written,
        "created_dirs": response.created_dirs,
        "note": response.note,
    })
    .to_string()
}

pub(crate) fn render_wasm_llm_inference_response_json(
    response: &WasmLlmInferenceResponse,
) -> String {
    json!({
        "decision": response.decision.label(),
        "model": response.model,
        "output_text": response.output_text,
        "finish_reason": response.finish_reason,
        "prompt_tokens": response.prompt_tokens,
        "completion_tokens": response.completion_tokens,
        "total_tokens": response.total_tokens,
        "note": response.note,
    })
    .to_string()
}

pub(crate) fn render_wasm_kv_get_response_json(response: &WasmKvGetResponse) -> String {
    json!({
        "decision": response.decision.label(),
        "namespace": response.namespace,
        "key": response.key,
        "found": response.found,
        "value_json": response.value_json,
        "note": response.note,
    })
    .to_string()
}

pub(crate) fn render_wasm_kv_set_response_json(response: &WasmKvSetResponse) -> String {
    json!({
        "decision": response.decision.label(),
        "namespace": response.namespace,
        "key": response.key,
        "stored": response.stored,
        "note": response.note,
    })
    .to_string()
}

fn build_host_call_guest(import_name: &str, request_json: &str) -> Result<Vec<u8>, String> {
    let request_bytes = request_json.as_bytes();
    let request_data = wat_data_bytes(request_bytes);
    let wat = format!(
        r#"(module
  (import "{namespace}" "{import_name}" (func $host_call (param i32 i32 i32 i32) (result i32)))
  (memory (export "memory") 2)
  (global $loom_result_ptr (export "{result_ptr_export}") i32 (i32.const {response_offset}))
  (global $loom_result_len (export "{result_len_export}") (mut i32) (i32.const 0))
  (data (i32.const {request_offset}) "{request_data}")
  (func (export "run") (result i32)
    (local $written i32)
    i32.const {request_offset}
    i32.const {request_len}
    global.get $loom_result_ptr
    i32.const {response_capacity}
    call $host_call
    local.tee $written
    global.set $loom_result_len
    local.get $written))"#,
        namespace = WASM_HOST_CALL_NAMESPACE,
        import_name = import_name,
        request_offset = WASM_HOST_REQUEST_OFFSET,
        request_len = request_bytes.len(),
        request_data = request_data,
        response_offset = WASM_HOST_RESPONSE_OFFSET,
        response_capacity = WASM_HOST_RESPONSE_CAPACITY,
        result_ptr_export = WASM_HOST_RESULT_PTR_EXPORT,
        result_len_export = WASM_HOST_RESULT_LEN_EXPORT,
    );
    wat::parse_str(&wat).map_err(|error| format!("failed to compile builtin wasm guest: {error}"))
}

fn wat_data_bytes(bytes: &[u8]) -> String {
    bytes
        .iter()
        .map(|byte| format!("\\{:02x}", byte))
        .collect::<Vec<_>>()
        .join("")
}

fn render_security_context_value(security: &WasmHostSecurityContext) -> Value {
    json!({
        "capability_name": security.capability_name,
        "agent_id": security.agent_id,
        "org_id": security.org_id,
        "session_id": security.session_id,
        "operation_id": security.operation_id,
        "max_timeout_ms": security.max_timeout_ms,
        "max_response_bytes": security.max_response_bytes,
        "allowed_hosts": security.allowed_hosts,
        "allowed_workdir_roots": security.allowed_workdir_roots,
        "require_user_present": security.require_user_present,
    })
}

fn parse_security_context(value: Option<&Value>) -> WasmHostSecurityContext {
    let mut security = WasmHostSecurityContext::default();
    if let Some(value) = value {
        security.capability_name = value_string(value.get("capability_name"));
        security.agent_id = value_string(value.get("agent_id"));
        security.org_id = value_string(value.get("org_id"));
        security.session_id = value_string(value.get("session_id"));
        security.operation_id = value_string(value.get("operation_id"));
        security.max_timeout_ms =
            value_u64_or(value.get("max_timeout_ms"), security.max_timeout_ms);
        security.max_response_bytes =
            value_usize_or(value.get("max_response_bytes"), security.max_response_bytes);
        let allowed_hosts = value_string_array(value.get("allowed_hosts"));
        if !allowed_hosts.is_empty() {
            security.allowed_hosts = allowed_hosts;
        }
        let allowed_roots = value_string_array(value.get("allowed_workdir_roots"));
        if !allowed_roots.is_empty() {
            security.allowed_workdir_roots = allowed_roots;
        }
        security.require_user_present = value_bool_or(
            value.get("require_user_present"),
            security.require_user_present,
        );
    }
    security
}

fn value_string(value: Option<&Value>) -> String {
    value
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string()
}

fn value_string_or(value: Option<&Value>, default: &str) -> String {
    value.and_then(Value::as_str).unwrap_or(default).to_string()
}

fn value_string_array(value: Option<&Value>) -> Vec<String> {
    value
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(Value::as_str)
                .map(|value| value.to_string())
                .collect::<Vec<_>>()
        })
        .unwrap_or_default()
}

fn value_u64_or(value: Option<&Value>, default: u64) -> u64 {
    value.and_then(Value::as_u64).unwrap_or(default)
}

fn value_usize_or(value: Option<&Value>, default: usize) -> usize {
    value
        .and_then(Value::as_u64)
        .map(|value| value as usize)
        .unwrap_or(default)
}

fn value_bool_or(value: Option<&Value>, default: bool) -> bool {
    value.and_then(Value::as_bool).unwrap_or(default)
}

/// Host-side runtime backend selection.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HostBackend {
    /// Current truth: local preview / preparation path only.
    PreviewOnly,
    /// Prepared for a Wasmtime-backed runtime wiring.
    WasmtimeReady,
}

impl HostBackend {
    pub fn label(self) -> &'static str {
        match self {
            Self::PreviewOnly => "preview_only",
            Self::WasmtimeReady => "wasmtime_ready",
        }
    }
}

/// A host-side Wasm execution plan with store limits, pooling profile, and
/// engine-preparation metadata.
#[derive(Clone, Debug)]
pub struct WasmHostConfig {
    pub profile_name: String,
    pub backend: HostBackend,
    pub component_model_enabled: bool,
    pub store_limits: WasmStoreLimits,
    pub pooling: PoolingConfig,
    pub fuel_metering_enabled: bool,
    pub epoch_deadline_ms: Option<u64>,
    pub notes: Vec<String>,
}

impl WasmHostConfig {
    pub fn host_memory_budget_bytes(&self) -> u64 {
        self.store_limits.max_memory_bytes
    }

    pub fn per_instance_memory_budget_bytes(&self) -> u64 {
        self.pooling.max_memory_pages as u64 * 65_536
    }

    pub fn pool_memory_budget_bytes(&self) -> u64 {
        self.pooling.total_memory_bytes()
    }
}

/// Builder for a host-side Wasm configuration.
#[derive(Clone, Debug)]
pub struct WasmHostBuilder {
    profile_name: String,
    backend: HostBackend,
    component_model_enabled: bool,
    store_limits: WasmStoreLimits,
    pooling: PoolingConfig,
    fuel_metering_enabled: bool,
    epoch_deadline_ms: Option<u64>,
    notes: Vec<String>,
}

impl Default for WasmHostBuilder {
    fn default() -> Self {
        Self::new()
    }
}

impl WasmHostBuilder {
    pub fn new() -> Self {
        Self {
            profile_name: "standard".to_string(),
            backend: HostBackend::PreviewOnly,
            component_model_enabled: true,
            store_limits: default_limits(),
            pooling: PoolingConfig::from_profile(PoolingProfile::Standard),
            fuel_metering_enabled: true,
            epoch_deadline_ms: Some(1_000),
            notes: vec![
                "prepared host config; execution lives in the experimental guest lane".to_string(),
            ],
        }
    }

    pub fn with_profile_name(mut self, profile_name: impl Into<String>) -> Self {
        self.profile_name = profile_name.into();
        self
    }

    pub fn with_backend(mut self, backend: HostBackend) -> Self {
        self.backend = backend;
        self
    }

    pub fn with_component_model_enabled(mut self, enabled: bool) -> Self {
        self.component_model_enabled = enabled;
        self
    }

    pub fn with_store_limits(mut self, limits: WasmStoreLimits) -> Self {
        self.store_limits = limits;
        self
    }

    pub fn with_pooling_profile(mut self, profile: PoolingProfile) -> Self {
        self.pooling = PoolingConfig::from_profile(profile);
        self
    }

    pub fn with_pooling_config(mut self, pooling: PoolingConfig) -> Self {
        self.pooling = pooling;
        self
    }

    pub fn with_fuel_metering_enabled(mut self, enabled: bool) -> Self {
        self.fuel_metering_enabled = enabled;
        self
    }

    pub fn with_epoch_deadline_ms(mut self, deadline: Option<u64>) -> Self {
        self.epoch_deadline_ms = deadline;
        self
    }

    pub fn add_note(mut self, note: impl Into<String>) -> Self {
        self.notes.push(note.into());
        self
    }

    pub fn build(self) -> Result<WasmHostConfig, Vec<String>> {
        let mut errors = Vec::new();

        if let Err(mut reasons) = validate_limits(&self.store_limits) {
            errors.append(&mut reasons);
        }
        if let Err(reason) = self.pooling.validate() {
            errors.push(reason);
        }
        let per_instance_budget = self.pooling.max_memory_pages as u64 * 65_536;
        if per_instance_budget > self.store_limits.max_memory_bytes {
            errors.push(format!(
                "pooling profile can allocate {} bytes per instance, which exceeds store limit {} bytes",
                per_instance_budget,
                self.store_limits.max_memory_bytes
            ));
        }
        if self.profile_name.trim().is_empty() {
            errors.push("profile_name must not be empty".to_string());
        }

        if errors.is_empty() {
            Ok(WasmHostConfig {
                profile_name: self.profile_name,
                backend: self.backend,
                component_model_enabled: self.component_model_enabled,
                store_limits: self.store_limits,
                pooling: self.pooling,
                fuel_metering_enabled: self.fuel_metering_enabled,
                epoch_deadline_ms: self.epoch_deadline_ms,
                notes: self.notes,
            })
        } else {
            Err(errors)
        }
    }

    pub fn build_with_profile(
        profile_name: impl Into<String>,
        profile: PoolingProfile,
    ) -> Result<WasmHostConfig, Vec<String>> {
        Self::new()
            .with_profile_name(profile_name)
            .with_pooling_profile(profile)
            .build()
    }
}

/// Build a concise host configuration map for later Wasmtime wiring.
pub fn host_config_hints(config: &WasmHostConfig) -> BTreeMap<String, String> {
    let mut hints = BTreeMap::new();
    hints.insert("profile_name".to_string(), config.profile_name.clone());
    hints.insert("backend".to_string(), config.backend.label().to_string());
    hints.insert(
        "component_model_enabled".to_string(),
        config.component_model_enabled.to_string(),
    );
    hints.insert(
        "fuel_metering_enabled".to_string(),
        config.fuel_metering_enabled.to_string(),
    );
    hints.insert(
        "epoch_deadline_ms".to_string(),
        config
            .epoch_deadline_ms
            .map(|value| value.to_string())
            .unwrap_or_else(|| "none".to_string()),
    );
    hints.insert(
        "store_memory_budget_bytes".to_string(),
        config.host_memory_budget_bytes().to_string(),
    );
    hints.insert(
        "per_instance_memory_budget_bytes".to_string(),
        config.per_instance_memory_budget_bytes().to_string(),
    );
    hints.insert(
        "pool_memory_budget_bytes".to_string(),
        config.pool_memory_budget_bytes().to_string(),
    );
    hints.insert(
        "pool_profile".to_string(),
        config.pooling.profile.label().to_string(),
    );
    hints
}

pub fn render_host_config_human(config: &WasmHostConfig) -> String {
    let hints = host_config_hints(config);
    let mut text = String::from(
        "Meridian Loom // WASM HOST CONFIG\n\
         =================================\n",
    );
    text.push_str(&format!(
        "profile              {}\nbackend              {}\ncomponent_model      {}\nfuel_metering        {}\nepoch_deadline_ms    {}\n",
        config.profile_name,
        config.backend.label(),
        config.component_model_enabled,
        config.fuel_metering_enabled,
        config.epoch_deadline_ms
            .map(|v| v.to_string())
            .unwrap_or_else(|| "none".to_string()),
    ));
    text.push_str("store_limits\n");
    text.push_str(&render_limits_human(&config.store_limits));
    text.push('\n');
    text.push_str("pooling_profile\n");
    text.push_str(&render_pooling_config_human(&config.pooling));
    text.push_str("\nhost_hints\n");
    for (key, value) in hints {
        text.push_str(&format!("{} = {}\n", key, value));
    }
    if !config.notes.is_empty() {
        text.push_str("notes\n");
        for note in &config.notes {
            text.push_str(&format!("- {}\n", note));
        }
    }
    text
}

pub fn render_host_config_json(config: &WasmHostConfig) -> String {
    let epoch = config
        .epoch_deadline_ms
        .map(|value| value.to_string())
        .unwrap_or_else(|| "null".to_string());
    let notes_json = if config.notes.is_empty() {
        "[]".to_string()
    } else {
        let values = config
            .notes
            .iter()
            .map(|note| format!("{:?}", note))
            .collect::<Vec<_>>()
            .join(",");
        format!("[{}]", values)
    };
    format!(
        "{{\n  \"profile_name\": {:?},\n  \"backend\": {:?},\n  \"component_model_enabled\": {},\n  \"fuel_metering_enabled\": {},\n  \"epoch_deadline_ms\": {},\n  \"store_limits\": {},\n  \"pooling\": {},\n  \"notes\": {}\n}}",
        config.profile_name,
        config.backend.label(),
        config.component_model_enabled,
        config.fuel_metering_enabled,
        epoch,
        crate::wasm_limits::render_limits_json(&config.store_limits),
        crate::wasm_profiles::render_pooling_config_json(&config.pooling),
        notes_json,
    )
}

pub fn validate_host_config(config: &WasmHostConfig) -> Result<(), Vec<String>> {
    WasmHostBuilder {
        profile_name: config.profile_name.clone(),
        backend: config.backend,
        component_model_enabled: config.component_model_enabled,
        store_limits: config.store_limits.clone(),
        pooling: config.pooling.clone(),
        fuel_metering_enabled: config.fuel_metering_enabled,
        epoch_deadline_ms: config.epoch_deadline_ms,
        notes: config.notes.clone(),
    }
    .build()
    .map(|_| ())
}

pub fn build_wasmtime_config(config: &WasmHostConfig) -> Result<wasmtime::Config, Vec<String>> {
    wasm_runner::build_wasmtime_config(config)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_builder_is_truthful() {
        let config = WasmHostBuilder::new().build().expect("default config");
        assert_eq!(config.profile_name, "standard");
        assert_eq!(config.backend, HostBackend::PreviewOnly);
        assert!(config.component_model_enabled);
        assert!(config.fuel_metering_enabled);
        assert!(config
            .notes
            .iter()
            .any(|note| note.contains("experimental guest lane")));
        assert!(validate_host_config(&config).is_ok());
    }

    #[test]
    fn builder_can_be_marked_wasmtime_ready_without_faking_execution() {
        let config = WasmHostBuilder::new()
            .with_backend(HostBackend::WasmtimeReady)
            .with_profile_name("host/wasmtime-ready")
            .build()
            .expect("wasmtime-ready config");
        assert_eq!(config.backend, HostBackend::WasmtimeReady);
        assert_eq!(config.profile_name, "host/wasmtime-ready");
        let hints = host_config_hints(&config);
        assert_eq!(hints.get("backend"), Some(&"wasmtime_ready".to_string()));
    }

    #[test]
    fn builder_rejects_pooling_that_exceeds_store_memory() {
        let limits = WasmStoreLimits {
            max_memory_bytes: 1_048_576, // 1 MiB
            max_table_elements: 1_000,
            max_instances: 4,
            max_tables: 4,
            max_memories: 4,
            fuel_limit: Some(100_000),
        };
        let config = WasmHostBuilder::new()
            .with_store_limits(limits)
            .with_pooling_config(PoolingConfig::from_profile(PoolingProfile::Heavy))
            .build()
            .expect_err("should reject oversized pooling");
        assert!(config
            .iter()
            .any(|reason| reason.contains("exceeds store limit")));
    }

    #[test]
    fn render_human_includes_store_and_pooling_surfaces() {
        let config = WasmHostBuilder::new().build().expect("config");
        let rendered = render_host_config_human(&config);
        assert!(rendered.contains("WASM HOST CONFIG"));
        assert!(rendered.contains("store_limits"));
        assert!(rendered.contains("pooling_profile"));
    }

    #[test]
    fn json_render_is_structured_and_truthful() {
        let config = WasmHostBuilder::new()
            .with_epoch_deadline_ms(Some(2_500))
            .build()
            .expect("config");
        let rendered = render_host_config_json(&config);
        assert!(rendered.contains("\"profile_name\""));
        assert!(rendered.contains("\"epoch_deadline_ms\": 2500"));
        assert!(rendered.contains("\"notes\""));
    }

    #[test]
    fn host_call_signature_surface_covers_builtin_host_calls() {
        let signatures = wasm_host_call_signatures();
        assert_eq!(signatures.len(), 9);
        assert!(signatures
            .iter()
            .all(|signature| signature.import_module == WASM_HOST_CALL_NAMESPACE));
        assert!(signatures
            .iter()
            .any(|signature| signature.import_name() == HOST_BROWSER_NAVIGATE));
        assert!(signatures
            .iter()
            .any(|signature| signature.import_name() == HOST_SCHEDULE_HEARTBEAT));
        assert!(signatures
            .iter()
            .any(|signature| signature.import_name() == HOST_TERMINAL_EXEC));
        assert!(signatures
            .iter()
            .any(|signature| signature.import_name() == HOST_SYSTEM_INFO));
        assert!(signatures
            .iter()
            .any(|signature| signature.import_name() == HOST_FS_READ));
        assert!(signatures
            .iter()
            .any(|signature| signature.import_name() == HOST_FS_WRITE));
        assert!(signatures
            .iter()
            .any(|signature| signature.import_name() == HOST_LLM_INFERENCE));
        assert!(signatures
            .iter()
            .any(|signature| signature.import_name() == HOST_KV_GET));
        assert!(signatures
            .iter()
            .any(|signature| signature.import_name() == HOST_KV_SET));
    }

    #[test]
    fn host_security_context_defaults_remain_bounded() {
        let security = WasmHostSecurityContext::default();
        assert_eq!(security.max_timeout_ms, 3_000);
        assert_eq!(security.max_response_bytes, 16_384);
        assert_eq!(security.allowed_workdir_roots, vec![".".to_string()]);
        assert!(!security.require_user_present);

        let terminal = WasmTerminalExecRequest::default();
        assert!(terminal.require_clean_environment);
        assert_eq!(terminal.timeout_ms, 2_000);

        let browser = WasmBrowserNavigateRequest::default();
        assert!(browser.capture_semantic_snapshot);
        assert_eq!(browser.wait_for, "dom_content_loaded");

        let heartbeat = WasmHeartbeatScheduleRequest::default();
        assert_eq!(heartbeat.interval_seconds, Some(300));
        assert_eq!(heartbeat.jitter_seconds, 15);
    }
}
