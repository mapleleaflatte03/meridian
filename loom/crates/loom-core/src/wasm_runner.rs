use std::collections::BTreeMap;
use std::fs;
use std::io::Write;
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use loom_poge::{HostCallKind, KernelWarrant, PoGEInterceptor};

use serde_json::{json, Value};
use ureq::ResponseExt;
use url::Url;
use wasmtime::{
    Caller, Config, Engine, Instance, InstanceAllocationStrategy, Linker, Module,
    PoolingAllocationConfig, Store, StoreLimitsBuilder, Val,
};

#[cfg(test)]
use super::provider_router::{
    resolve_llm_route, ProviderKind, ProviderRouteIntent, ResolvedProviderRoute,
};
#[cfg(not(test))]
use crate::provider_router::{
    resolve_llm_route, ProviderKind, ProviderRouteIntent, ResolvedProviderRoute,
};

use super::{
    host_config_hints, parse_wasm_browser_navigate_request, parse_wasm_fs_read_request,
    parse_wasm_fs_write_request, parse_wasm_heartbeat_schedule_request, parse_wasm_kv_get_request,
    parse_wasm_kv_set_request, parse_wasm_llm_inference_request, parse_wasm_system_info_request,
    parse_wasm_terminal_exec_request, render_wasm_browser_navigate_response_json,
    render_wasm_fs_read_response_json, render_wasm_fs_write_response_json,
    render_wasm_heartbeat_schedule_response_json, render_wasm_kv_get_response_json,
    render_wasm_kv_set_response_json, render_wasm_llm_inference_response_json,
    render_wasm_system_info_response_json, render_wasm_terminal_exec_response_json,
    WasmBrowserNavigateResponse, WasmFsReadResponse, WasmFsWriteResponse,
    WasmHeartbeatScheduleResponse, WasmHostCallDecision, WasmHostCallStatusCode, WasmHostConfig,
    WasmKvGetResponse, WasmKvSetResponse, WasmLlmInferenceResponse, WasmSystemInfoResponse,
    WasmTerminalExecResponse, HOST_BROWSER_NAVIGATE, HOST_FS_READ, HOST_FS_WRITE, HOST_KV_GET,
    HOST_KV_SET, HOST_LLM_INFERENCE, HOST_SCHEDULE_HEARTBEAT, HOST_SYSTEM_INFO, HOST_TERMINAL_EXEC,
    WASM_HOST_CALL_NAMESPACE, WASM_HOST_RESULT_LEN_EXPORT, WASM_HOST_RESULT_PTR_EXPORT,
};

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum WasmGuestSource {
    WasmBytes { name: String, bytes: Vec<u8> },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WasmMemoryProbe {
    pub export_name: String,
    pub pages_to_grow: u32,
}

#[derive(Clone, Debug)]
pub struct WasmExecutionRequest {
    pub host: WasmHostConfig,
    pub source: WasmGuestSource,
    pub entrypoint: String,
    pub entrypoint_args: Vec<i32>,
    pub memory_probe: Option<WasmMemoryProbe>,
    pub fuel_budget: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WasmExecutionResult {
    pub host_backend: String,
    pub host_profile_name: String,
    pub runtime_path: String,
    pub module_name: String,
    pub entrypoint: String,
    pub entrypoint_result: Option<i32>,
    pub memory_probe_export: Option<String>,
    pub memory_probe_result: Option<i32>,
    pub memory_pages_after: Option<u32>,
    pub store_memory_limit_bytes: u64,
    pub pooling_profile: String,
    pub host_hints: BTreeMap<String, String>,
    pub host_response_json: Option<String>,
    pub host_calls: Vec<String>,
    pub notes: Vec<String>,
}

struct RunnerState {
    limits: wasmtime::StoreLimits,
    host_calls: Vec<String>,
    /// PoGE interceptor for this execution session. Wrapped in Option so we
    /// can take ownership via `.take()` at finalization time without cloning.
    poge: Option<PoGEInterceptor>,
}

pub fn build_wasmtime_config(host: &WasmHostConfig) -> Result<Config, Vec<String>> {
    let mut config = Config::new();

    config.consume_fuel(host.fuel_metering_enabled);

    let mut pooling = PoolingAllocationConfig::default();
    pooling
        .total_core_instances(host.pooling.max_instances)
        .total_memories(
            host.pooling
                .max_instances
                .saturating_mul(host.pooling.max_memories_per_instance),
        )
        .total_tables(
            host.pooling
                .max_instances
                .saturating_mul(host.pooling.max_tables_per_instance),
        )
        .max_core_instances_per_component(host.pooling.max_instances)
        .max_core_instance_size(host.pooling.max_memory_pages as usize * 65_536)
        .max_memories_per_component(host.pooling.max_memories_per_instance)
        .max_memories_per_module(host.pooling.max_memories_per_instance)
        .max_tables_per_component(host.pooling.max_tables_per_instance)
        .max_tables_per_module(host.pooling.max_tables_per_instance)
        .table_elements(host.pooling.max_table_elements);

    config.allocation_strategy(InstanceAllocationStrategy::Pooling(pooling));

    Ok(config)
}

pub fn run_wasm_guest(request: &WasmExecutionRequest) -> Result<WasmExecutionResult, String> {
    let config = build_wasmtime_config(&request.host).map_err(|errors| errors.join("; "))?;
    let engine =
        Engine::new(&config).map_err(|error| format!("failed to build engine: {error}"))?;
    let wasm_bytes = match &request.source {
        WasmGuestSource::WasmBytes { bytes, .. } => bytes.clone(),
    };
    let module_name = match &request.source {
        WasmGuestSource::WasmBytes { name, .. } => name.clone(),
    };
    let module = Module::new(&engine, &wasm_bytes)
        .map_err(|error| format!("failed to compile module: {error}"))?;

    let store_limits = StoreLimitsBuilder::new()
        .memory_size(request.host.store_limits.max_memory_bytes as usize)
        .table_elements(request.host.store_limits.max_table_elements)
        .instances(request.host.store_limits.max_instances as usize)
        .tables(request.host.store_limits.max_tables as usize)
        .memories(request.host.store_limits.max_memories as usize)
        .trap_on_grow_failure(false)
        .build();
    let poge = PoGEInterceptor::new(poge_dummy_warrant(), [0u8; 32], "airgapped-researcher");
    let mut store = Store::new(
        &engine,
        RunnerState {
            limits: store_limits,
            host_calls: Vec::new(),
            poge: Some(poge),
        },
    );
    store.limiter(|state| &mut state.limits);
    if request.host.fuel_metering_enabled {
        store
            .add_fuel(request.fuel_budget)
            .map_err(|error| format!("failed to set fuel: {error}"))?;
    }

    let mut linker = Linker::new(&engine);
    linker
        .func_wrap(
            WASM_HOST_CALL_NAMESPACE,
            HOST_BROWSER_NAVIGATE,
            |caller: Caller<'_, RunnerState>,
             request_ptr: i32,
             request_len: i32,
             response_ptr: i32,
             response_capacity: i32| {
                host_browser_navigate(
                    caller,
                    request_ptr,
                    request_len,
                    response_ptr,
                    response_capacity,
                )
            },
        )
        .map_err(|error| format!("failed to define {HOST_BROWSER_NAVIGATE}: {error}"))?;
    linker
        .func_wrap(
            WASM_HOST_CALL_NAMESPACE,
            HOST_SCHEDULE_HEARTBEAT,
            |caller: Caller<'_, RunnerState>,
             request_ptr: i32,
             request_len: i32,
             response_ptr: i32,
             response_capacity: i32| {
                host_schedule_heartbeat(
                    caller,
                    request_ptr,
                    request_len,
                    response_ptr,
                    response_capacity,
                )
            },
        )
        .map_err(|error| format!("failed to define {HOST_SCHEDULE_HEARTBEAT}: {error}"))?;
    linker
        .func_wrap(
            WASM_HOST_CALL_NAMESPACE,
            HOST_TERMINAL_EXEC,
            |caller: Caller<'_, RunnerState>,
             request_ptr: i32,
             request_len: i32,
             response_ptr: i32,
             response_capacity: i32| {
                host_terminal_exec(
                    caller,
                    request_ptr,
                    request_len,
                    response_ptr,
                    response_capacity,
                )
            },
        )
        .map_err(|error| format!("failed to define {HOST_TERMINAL_EXEC}: {error}"))?;
    linker
        .func_wrap(
            WASM_HOST_CALL_NAMESPACE,
            HOST_SYSTEM_INFO,
            |caller: Caller<'_, RunnerState>,
             request_ptr: i32,
             request_len: i32,
             response_ptr: i32,
             response_capacity: i32| {
                host_system_info(
                    caller,
                    request_ptr,
                    request_len,
                    response_ptr,
                    response_capacity,
                )
            },
        )
        .map_err(|error| format!("failed to define {HOST_SYSTEM_INFO}: {error}"))?;
    linker
        .func_wrap(
            WASM_HOST_CALL_NAMESPACE,
            HOST_FS_READ,
            |caller: Caller<'_, RunnerState>,
             request_ptr: i32,
             request_len: i32,
             response_ptr: i32,
             response_capacity: i32| {
                host_fs_read(
                    caller,
                    request_ptr,
                    request_len,
                    response_ptr,
                    response_capacity,
                )
            },
        )
        .map_err(|error| format!("failed to define {HOST_FS_READ}: {error}"))?;
    linker
        .func_wrap(
            WASM_HOST_CALL_NAMESPACE,
            HOST_FS_WRITE,
            |caller: Caller<'_, RunnerState>,
             request_ptr: i32,
             request_len: i32,
             response_ptr: i32,
             response_capacity: i32| {
                host_fs_write(
                    caller,
                    request_ptr,
                    request_len,
                    response_ptr,
                    response_capacity,
                )
            },
        )
        .map_err(|error| format!("failed to define {HOST_FS_WRITE}: {error}"))?;
    linker
        .func_wrap(
            WASM_HOST_CALL_NAMESPACE,
            HOST_LLM_INFERENCE,
            |caller: Caller<'_, RunnerState>,
             request_ptr: i32,
             request_len: i32,
             response_ptr: i32,
             response_capacity: i32| {
                host_llm_inference(
                    caller,
                    request_ptr,
                    request_len,
                    response_ptr,
                    response_capacity,
                )
            },
        )
        .map_err(|error| format!("failed to define {HOST_LLM_INFERENCE}: {error}"))?;
    linker
        .func_wrap(
            WASM_HOST_CALL_NAMESPACE,
            HOST_KV_GET,
            |caller: Caller<'_, RunnerState>,
             request_ptr: i32,
             request_len: i32,
             response_ptr: i32,
             response_capacity: i32| {
                host_kv_get(
                    caller,
                    request_ptr,
                    request_len,
                    response_ptr,
                    response_capacity,
                )
            },
        )
        .map_err(|error| format!("failed to define {HOST_KV_GET}: {error}"))?;
    linker
        .func_wrap(
            WASM_HOST_CALL_NAMESPACE,
            HOST_KV_SET,
            |caller: Caller<'_, RunnerState>,
             request_ptr: i32,
             request_len: i32,
             response_ptr: i32,
             response_capacity: i32| {
                host_kv_set(
                    caller,
                    request_ptr,
                    request_len,
                    response_ptr,
                    response_capacity,
                )
            },
        )
        .map_err(|error| format!("failed to define {HOST_KV_SET}: {error}"))?;

    let instance = linker
        .instantiate(&mut store, &module)
        .map_err(|error| format!("failed to instantiate module: {error}"))?;
    let func = instance
        .get_func(&mut store, &request.entrypoint)
        .ok_or_else(|| format!("missing export '{}'", request.entrypoint))?;
    let entrypoint_result = call_i32_function(&mut store, &func, &request.entrypoint_args)?;

    let (memory_probe_export, memory_probe_result, memory_pages_after) =
        if let Some(probe) = &request.memory_probe {
            let probe_func = instance
                .get_func(&mut store, &probe.export_name)
                .ok_or_else(|| format!("missing memory probe export '{}'", probe.export_name))?;
            let result = call_i32_function(&mut store, &probe_func, &[probe.pages_to_grow as i32])?;
            let pages_after = instance
                .get_export(&mut store, "memory")
                .and_then(|export| export.into_memory())
                .map(|memory| memory.size(&store) as u32);
            (Some(probe.export_name.clone()), result, pages_after)
        } else {
            (None, None, None)
        };

    let host_response_json = capture_host_response_json(&mut store, &instance)?;
    let host_calls = store.data().host_calls.clone();

    // --- PoGE Finalization ---
    // Extract the interceptor from state (taking ownership) and finalize the
    // Merkle tree over all recorded host-call receipts.
    if let Some(interceptor) = store.data_mut().poge.take() {
        match interceptor.finalize() {
            Ok(audit_root) => {
                let root_hex = audit_root.merkle_root_hex();
                let trace_len = audit_root.trace_len;
                eprintln!(
                    "\n\x1b[1;32m[🛡️ PoGE PROTOCOL] Cryptographic Audit Root Settled:\x1b[0m \x1b[1;36m{}\x1b[0m",
                    root_hex
                );
                eprintln!(
                    "\x1b[1;32m[🛡️ PoGE PROTOCOL] Trace Length:\x1b[0m \x1b[1;36m{} events securely hashed.\x1b[0m\n",
                    trace_len
                );
            }
            // EmptyTrace is expected when the guest made no PoGE-instrumented calls.
            Err(_) => {}
        }
    }

    let mut notes = vec![
        "experimental local Wasmtime guest execution".to_string(),
        "truth boundary: local-only execution path, not hosted runtime replacement".to_string(),
    ];
    if !host_calls.is_empty() {
        notes.push(format!("host calls dispatched: {}", host_calls.join(", ")));
    }
    if host_response_json.is_some() {
        notes.push("host-call response captured from guest memory".to_string());
    }

    Ok(WasmExecutionResult {
        host_backend: request.host.backend.label().to_string(),
        host_profile_name: request.host.profile_name.clone(),
        runtime_path: if host_calls.is_empty() {
            "wasmtime_local_guest".to_string()
        } else {
            "wasmtime_local_guest_with_host_calls".to_string()
        },
        module_name,
        entrypoint: request.entrypoint.clone(),
        entrypoint_result,
        memory_probe_export,
        memory_probe_result,
        memory_pages_after,
        store_memory_limit_bytes: request.host.store_limits.max_memory_bytes,
        pooling_profile: request.host.pooling.profile.label().to_string(),
        host_hints: host_config_hints(&request.host),
        host_response_json,
        host_calls,
        notes,
    })
}

fn host_browser_navigate(
    mut caller: Caller<'_, RunnerState>,
    request_ptr: i32,
    request_len: i32,
    response_ptr: i32,
    response_capacity: i32,
) -> i32 {
    caller
        .data_mut()
        .host_calls
        .push("browser.navigate".to_string());
    let input = read_guest_bytes_for_poge(&mut caller, request_ptr, request_len);
    let result = dispatch_browser_navigate(
        &mut caller,
        request_ptr,
        request_len,
        response_ptr,
        response_capacity,
    );
    let (return_val, is_error, out_len) = match result {
        Ok(n) => (n, false, n.max(0) as usize),
        Err(status) => (status.code(), true, 0usize),
    };
    let output = if out_len > 0 {
        read_guest_bytes_for_poge(&mut caller, response_ptr, out_len as i32)
    } else {
        Vec::new()
    };
    let epoch_ms = epoch_ms_now();
    let data = caller.data_mut();
    if let Some(poge) = data.poge.as_mut() {
        let _ = poge.record_event(HostCallKind::WebFetch, epoch_ms, &input, &output, is_error);
    }
    return_val
}

fn host_schedule_heartbeat(
    mut caller: Caller<'_, RunnerState>,
    request_ptr: i32,
    request_len: i32,
    response_ptr: i32,
    response_capacity: i32,
) -> i32 {
    caller
        .data_mut()
        .host_calls
        .push("heartbeat.schedule".to_string());
    match dispatch_schedule_heartbeat(
        &mut caller,
        request_ptr,
        request_len,
        response_ptr,
        response_capacity,
    ) {
        Ok(bytes_written) => bytes_written,
        Err(status) => status.code(),
    }
}

fn host_terminal_exec(
    mut caller: Caller<'_, RunnerState>,
    request_ptr: i32,
    request_len: i32,
    response_ptr: i32,
    response_capacity: i32,
) -> i32 {
    caller
        .data_mut()
        .host_calls
        .push("terminal.exec".to_string());
    match dispatch_terminal_exec(
        &mut caller,
        request_ptr,
        request_len,
        response_ptr,
        response_capacity,
    ) {
        Ok(bytes_written) => bytes_written,
        Err(status) => status.code(),
    }
}

fn host_system_info(
    mut caller: Caller<'_, RunnerState>,
    request_ptr: i32,
    request_len: i32,
    response_ptr: i32,
    response_capacity: i32,
) -> i32 {
    caller.data_mut().host_calls.push("system.info".to_string());
    let input = read_guest_bytes_for_poge(&mut caller, request_ptr, request_len);
    let result = dispatch_system_info(
        &mut caller,
        request_ptr,
        request_len,
        response_ptr,
        response_capacity,
    );
    let (return_val, is_error, out_len) = match result {
        Ok(n) => (n, false, n.max(0) as usize),
        Err(status) => (status.code(), true, 0usize),
    };
    let output = if out_len > 0 {
        read_guest_bytes_for_poge(&mut caller, response_ptr, out_len as i32)
    } else {
        Vec::new()
    };
    let epoch_ms = epoch_ms_now();
    let data = caller.data_mut();
    if let Some(poge) = data.poge.as_mut() {
        let _ = poge.record_event(
            HostCallKind::SystemInfo,
            epoch_ms,
            &input,
            &output,
            is_error,
        );
    }
    return_val
}

fn host_fs_read(
    mut caller: Caller<'_, RunnerState>,
    request_ptr: i32,
    request_len: i32,
    response_ptr: i32,
    response_capacity: i32,
) -> i32 {
    caller.data_mut().host_calls.push("fs.read".to_string());
    let input = read_guest_bytes_for_poge(&mut caller, request_ptr, request_len);
    let result = dispatch_fs_read(
        &mut caller,
        request_ptr,
        request_len,
        response_ptr,
        response_capacity,
    );
    let (return_val, is_error, out_len) = match result {
        Ok(n) => (n, false, n.max(0) as usize),
        Err(status) => (status.code(), true, 0usize),
    };
    let output = if out_len > 0 {
        read_guest_bytes_for_poge(&mut caller, response_ptr, out_len as i32)
    } else {
        Vec::new()
    };
    let epoch_ms = epoch_ms_now();
    let data = caller.data_mut();
    if let Some(poge) = data.poge.as_mut() {
        let _ = poge.record_event(HostCallKind::FsRead, epoch_ms, &input, &output, is_error);
    }
    return_val
}

fn host_fs_write(
    mut caller: Caller<'_, RunnerState>,
    request_ptr: i32,
    request_len: i32,
    response_ptr: i32,
    response_capacity: i32,
) -> i32 {
    caller.data_mut().host_calls.push("fs.write".to_string());
    let input = read_guest_bytes_for_poge(&mut caller, request_ptr, request_len);
    let result = dispatch_fs_write(
        &mut caller,
        request_ptr,
        request_len,
        response_ptr,
        response_capacity,
    );
    let (return_val, is_error, out_len) = match result {
        Ok(n) => (n, false, n.max(0) as usize),
        Err(status) => (status.code(), true, 0usize),
    };
    let output = if out_len > 0 {
        read_guest_bytes_for_poge(&mut caller, response_ptr, out_len as i32)
    } else {
        Vec::new()
    };
    let epoch_ms = epoch_ms_now();
    let data = caller.data_mut();
    if let Some(poge) = data.poge.as_mut() {
        let _ = poge.record_event(HostCallKind::FsWrite, epoch_ms, &input, &output, is_error);
    }
    return_val
}

fn host_llm_inference(
    mut caller: Caller<'_, RunnerState>,
    request_ptr: i32,
    request_len: i32,
    response_ptr: i32,
    response_capacity: i32,
) -> i32 {
    caller
        .data_mut()
        .host_calls
        .push("llm.inference".to_string());
    let input = read_guest_bytes_for_poge(&mut caller, request_ptr, request_len);
    let result = dispatch_llm_inference(
        &mut caller,
        request_ptr,
        request_len,
        response_ptr,
        response_capacity,
    );
    let (return_val, is_error, out_len) = match result {
        Ok(n) => (n, false, n.max(0) as usize),
        Err(status) => (status.code(), true, 0usize),
    };
    let output = if out_len > 0 {
        read_guest_bytes_for_poge(&mut caller, response_ptr, out_len as i32)
    } else {
        Vec::new()
    };
    let epoch_ms = epoch_ms_now();
    let data = caller.data_mut();
    if let Some(poge) = data.poge.as_mut() {
        let _ = poge.record_event(
            HostCallKind::LlmInference,
            epoch_ms,
            &input,
            &output,
            is_error,
        );
    }
    return_val
}

fn host_kv_get(
    mut caller: Caller<'_, RunnerState>,
    request_ptr: i32,
    request_len: i32,
    response_ptr: i32,
    response_capacity: i32,
) -> i32 {
    caller.data_mut().host_calls.push("kv.get".to_string());
    match dispatch_kv_get(
        &mut caller,
        request_ptr,
        request_len,
        response_ptr,
        response_capacity,
    ) {
        Ok(bytes_written) => bytes_written,
        Err(status) => status.code(),
    }
}

fn host_kv_set(
    mut caller: Caller<'_, RunnerState>,
    request_ptr: i32,
    request_len: i32,
    response_ptr: i32,
    response_capacity: i32,
) -> i32 {
    caller.data_mut().host_calls.push("kv.set".to_string());
    match dispatch_kv_set(
        &mut caller,
        request_ptr,
        request_len,
        response_ptr,
        response_capacity,
    ) {
        Ok(bytes_written) => bytes_written,
        Err(status) => status.code(),
    }
}

fn dispatch_browser_navigate(
    caller: &mut Caller<'_, RunnerState>,
    request_ptr: i32,
    request_len: i32,
    response_ptr: i32,
    response_capacity: i32,
) -> Result<i32, WasmHostCallStatusCode> {
    let memory = guest_memory(caller)?;
    let request_json = read_guest_utf8(&memory, caller, request_ptr, request_len)?;
    let request = parse_wasm_browser_navigate_request(&request_json)
        .map_err(|_| WasmHostCallStatusCode::InvalidRequest)?;

    let url = Url::parse(&request.url).map_err(|_| WasmHostCallStatusCode::InvalidRequest)?;
    if !matches!(url.scheme(), "http" | "https") {
        let response = WasmBrowserNavigateResponse {
            decision: WasmHostCallDecision::Denied,
            navigation_id: request.security.operation_id.clone(),
            final_url: request.url.clone(),
            http_status: None,
            content_type: String::new(),
            title: String::new(),
            body_excerpt_utf8: String::new(),
            semantic_snapshot_ref: String::new(),
            note: format!("unsupported scheme '{}'", url.scheme()),
        };
        return write_guest_json_response(
            &memory,
            caller,
            response_ptr,
            response_capacity,
            &render_wasm_browser_navigate_response_json(&response),
        );
    }

    let host = url.host_str().unwrap_or_default().to_string();
    let allowed_hosts = if request.allowed_hosts.is_empty() {
        request.security.allowed_hosts.clone()
    } else {
        request.allowed_hosts.clone()
    };
    if !allowed_hosts.is_empty() && !allowed_hosts.iter().any(|value| value == &host) {
        let response = WasmBrowserNavigateResponse {
            decision: WasmHostCallDecision::Denied,
            navigation_id: request.security.operation_id.clone(),
            final_url: request.url.clone(),
            http_status: None,
            content_type: String::new(),
            title: String::new(),
            body_excerpt_utf8: String::new(),
            semantic_snapshot_ref: String::new(),
            note: format!("host '{}' is outside the allowed host set", host),
        };
        return write_guest_json_response(
            &memory,
            caller,
            response_ptr,
            response_capacity,
            &render_wasm_browser_navigate_response_json(&response),
        );
    }

    let timeout_ms = bounded_timeout_ms(request.timeout_ms, request.security.max_timeout_ms);
    let max_response_bytes =
        bounded_response_bytes(request.security.max_response_bytes, response_capacity);
    let mut response = match ureq::get(request.url.as_str())
        .config()
        .timeout_global(Some(Duration::from_millis(timeout_ms)))
        .http_status_as_error(false)
        .build()
        .call()
    {
        Ok(response) => response,
        Err(error) => {
            let response = WasmBrowserNavigateResponse {
                decision: WasmHostCallDecision::Denied,
                navigation_id: request.security.operation_id.clone(),
                final_url: request.url.clone(),
                http_status: None,
                content_type: String::new(),
                title: String::new(),
                body_excerpt_utf8: String::new(),
                semantic_snapshot_ref: String::new(),
                note: format!("http navigate failed: {error}"),
            };
            return write_guest_json_response(
                &memory,
                caller,
                response_ptr,
                response_capacity,
                &render_wasm_browser_navigate_response_json(&response),
            );
        }
    };

    let final_url = response.get_uri().to_string();
    let http_status = Some(response.status().as_u16());
    let content_type = response
        .headers()
        .get("content-type")
        .and_then(|value| value.to_str().ok())
        .unwrap_or_default()
        .to_string();
    let body_excerpt_utf8 = response
        .body_mut()
        .with_config()
        .limit(max_response_bytes as u64)
        .lossy_utf8(true)
        .read_to_string()
        .unwrap_or_else(|error| format!("[body read failed: {error}]"));
    let title = extract_html_title(&body_excerpt_utf8);
    let response = WasmBrowserNavigateResponse {
        decision: WasmHostCallDecision::Allowed,
        navigation_id: if request.security.operation_id.trim().is_empty() {
            request.session_id.clone()
        } else {
            request.security.operation_id.clone()
        },
        final_url,
        http_status,
        content_type,
        title,
        body_excerpt_utf8: body_excerpt_utf8.clone(),
        semantic_snapshot_ref: if request.capture_semantic_snapshot {
            format!("inline:body_excerpt:{}", body_excerpt_utf8.len())
        } else {
            String::new()
        },
        note: format!(
            "bounded synchronous browser host call completed within {}ms",
            timeout_ms
        ),
    };
    write_guest_json_response(
        &memory,
        caller,
        response_ptr,
        response_capacity,
        &render_wasm_browser_navigate_response_json(&response),
    )
}

fn dispatch_schedule_heartbeat(
    caller: &mut Caller<'_, RunnerState>,
    request_ptr: i32,
    request_len: i32,
    response_ptr: i32,
    response_capacity: i32,
) -> Result<i32, WasmHostCallStatusCode> {
    let memory = guest_memory(caller)?;
    let request_json = read_guest_utf8(&memory, caller, request_ptr, request_len)?;
    let request = parse_wasm_heartbeat_schedule_request(&request_json)
        .map_err(|_| WasmHostCallStatusCode::InvalidRequest)?;
    let response = WasmHeartbeatScheduleResponse {
        decision: WasmHostCallDecision::Denied,
        heartbeat_id: request.heartbeat_id,
        next_fire_at_unix_ms: None,
        accepted_run_id: String::new(),
        note: "heartbeat scheduling remains a declared surface until a runtime service owns leases and acknowledgements".to_string(),
    };
    write_guest_json_response(
        &memory,
        caller,
        response_ptr,
        response_capacity,
        &render_wasm_heartbeat_schedule_response_json(&response),
    )
}

fn dispatch_terminal_exec(
    caller: &mut Caller<'_, RunnerState>,
    request_ptr: i32,
    request_len: i32,
    response_ptr: i32,
    response_capacity: i32,
) -> Result<i32, WasmHostCallStatusCode> {
    let memory = guest_memory(caller)?;
    let request_json = read_guest_utf8(&memory, caller, request_ptr, request_len)?;
    let request = parse_wasm_terminal_exec_request(&request_json)
        .map_err(|_| WasmHostCallStatusCode::InvalidRequest)?;

    if request.argv.is_empty() {
        let response = WasmTerminalExecResponse {
            decision: WasmHostCallDecision::Denied,
            exit_code: None,
            stdout_utf8: String::new(),
            stderr_utf8: String::new(),
            timed_out: false,
            truncated: false,
            note: "argv must contain at least one executable".to_string(),
        };
        return write_guest_json_response(
            &memory,
            caller,
            response_ptr,
            response_capacity,
            &render_wasm_terminal_exec_response_json(&response),
        );
    }

    let workdir = match resolve_allowed_workdir(
        &request.working_dir,
        &request.security.allowed_workdir_roots,
    ) {
        Ok(path) => path,
        Err(error) => {
            let response = WasmTerminalExecResponse {
                decision: WasmHostCallDecision::Denied,
                exit_code: None,
                stdout_utf8: String::new(),
                stderr_utf8: String::new(),
                timed_out: false,
                truncated: false,
                note: error,
            };
            return write_guest_json_response(
                &memory,
                caller,
                response_ptr,
                response_capacity,
                &render_wasm_terminal_exec_response_json(&response),
            );
        }
    };

    let timeout_ms = bounded_timeout_ms(request.timeout_ms, request.security.max_timeout_ms);
    let max_output_bytes = bounded_response_bytes(
        request
            .max_output_bytes
            .min(request.security.max_response_bytes),
        response_capacity,
    );
    let mut command = Command::new(&request.argv[0]);
    command.args(&request.argv[1..]);
    command.current_dir(&workdir);
    command.stdin(Stdio::piped());
    command.stdout(Stdio::piped());
    command.stderr(Stdio::piped());
    if request.require_clean_environment {
        command.env_clear();
    }
    for name in &request.env_allowlist {
        if let Ok(value) = std::env::var(name) {
            command.env(name, value);
        }
    }

    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(error) => {
            let response = WasmTerminalExecResponse {
                decision: WasmHostCallDecision::Denied,
                exit_code: None,
                stdout_utf8: String::new(),
                stderr_utf8: String::new(),
                timed_out: false,
                truncated: false,
                note: format!("failed to spawn '{}': {error}", request.argv[0]),
            };
            return write_guest_json_response(
                &memory,
                caller,
                response_ptr,
                response_capacity,
                &render_wasm_terminal_exec_response_json(&response),
            );
        }
    };

    if let Some(mut stdin) = child.stdin.take() {
        let _ = stdin.write_all(request.stdin_utf8.as_bytes());
    }

    let started_at = Instant::now();
    let timed_out = loop {
        match child.try_wait() {
            Ok(Some(_)) => break false,
            Ok(None) => {
                if started_at.elapsed() >= Duration::from_millis(timeout_ms) {
                    let _ = child.kill();
                    break true;
                }
                thread::sleep(Duration::from_millis(10));
            }
            Err(_) => break false,
        }
    };

    let output = child
        .wait_with_output()
        .map_err(|_| WasmHostCallStatusCode::InternalError)?;
    let (stdout_utf8, stdout_truncated) = truncate_lossy_utf8(&output.stdout, max_output_bytes);
    let (stderr_utf8, stderr_truncated) = truncate_lossy_utf8(&output.stderr, max_output_bytes);
    let response = WasmTerminalExecResponse {
        decision: WasmHostCallDecision::Allowed,
        exit_code: output.status.code(),
        stdout_utf8,
        stderr_utf8,
        timed_out,
        truncated: stdout_truncated || stderr_truncated,
        note: format!(
            "bounded terminal host call completed in {:?} inside {}",
            started_at.elapsed(),
            workdir.display()
        ),
    };
    write_guest_json_response(
        &memory,
        caller,
        response_ptr,
        response_capacity,
        &render_wasm_terminal_exec_response_json(&response),
    )
}

fn dispatch_system_info(
    caller: &mut Caller<'_, RunnerState>,
    request_ptr: i32,
    request_len: i32,
    response_ptr: i32,
    response_capacity: i32,
) -> Result<i32, WasmHostCallStatusCode> {
    let memory = guest_memory(caller)?;
    let request_json = read_guest_utf8(&memory, caller, request_ptr, request_len)?;
    let request = parse_wasm_system_info_request(&request_json)
        .map_err(|_| WasmHostCallStatusCode::InvalidRequest)?;
    let max_response_bytes =
        bounded_response_bytes(request.security.max_response_bytes, response_capacity);
    let field_bytes = (max_response_bytes / 3).max(256);
    let (uname_utf8, uname_truncated, uname_note) = read_uname_excerpt(field_bytes);
    let (os_release_utf8, os_release_truncated, os_release_note) =
        read_allowlisted_text_file(Path::new("/etc/os-release"), field_bytes);
    let (hostname_utf8, hostname_truncated, hostname_note) =
        read_allowlisted_text_file(Path::new("/etc/hostname"), field_bytes);
    let truncated = uname_truncated || os_release_truncated || hostname_truncated;
    let mut notes = Vec::new();
    if let Some(note) = uname_note {
        notes.push(note);
    }
    if let Some(note) = os_release_note {
        notes.push(note);
    }
    if let Some(note) = hostname_note {
        notes.push(note);
    }
    let response = WasmSystemInfoResponse {
        decision: WasmHostCallDecision::Allowed,
        uname_utf8,
        os_release_utf8,
        hostname_utf8,
        truncated,
        note: if notes.is_empty() {
            "bounded system diagnostics collected from allowlisted host probes".to_string()
        } else {
            notes.join("; ")
        },
    };
    write_guest_json_response(
        &memory,
        caller,
        response_ptr,
        response_capacity,
        &render_wasm_system_info_response_json(&response),
    )
}

fn dispatch_fs_read(
    caller: &mut Caller<'_, RunnerState>,
    request_ptr: i32,
    request_len: i32,
    response_ptr: i32,
    response_capacity: i32,
) -> Result<i32, WasmHostCallStatusCode> {
    let memory = guest_memory(caller)?;
    let request_json = read_guest_utf8(&memory, caller, request_ptr, request_len)?;
    let request = parse_wasm_fs_read_request(&request_json)
        .map_err(|_| WasmHostCallStatusCode::InvalidRequest)?;
    if request.path.trim().is_empty() {
        let response = WasmFsReadResponse {
            decision: WasmHostCallDecision::Denied,
            path: request.path,
            content_utf8: String::new(),
            bytes_read: 0,
            truncated: false,
            note: "path must not be empty".to_string(),
        };
        return write_guest_json_response(
            &memory,
            caller,
            response_ptr,
            response_capacity,
            &render_wasm_fs_read_response_json(&response),
        );
    }
    let sandbox_path = match resolve_runtime_read_path(&request.path) {
        Ok(path) => path,
        Err(error) => {
            let response = WasmFsReadResponse {
                decision: WasmHostCallDecision::Denied,
                path: request.path,
                content_utf8: String::new(),
                bytes_read: 0,
                truncated: false,
                note: error,
            };
            return write_guest_json_response(
                &memory,
                caller,
                response_ptr,
                response_capacity,
                &render_wasm_fs_read_response_json(&response),
            );
        }
    };
    let bytes = match fs::read(&sandbox_path) {
        Ok(bytes) => bytes,
        Err(error) => {
            let response = WasmFsReadResponse {
                decision: WasmHostCallDecision::Denied,
                path: request.path,
                content_utf8: String::new(),
                bytes_read: 0,
                truncated: false,
                note: format!("failed to read '{}': {error}", sandbox_path.display()),
            };
            return write_guest_json_response(
                &memory,
                caller,
                response_ptr,
                response_capacity,
                &render_wasm_fs_read_response_json(&response),
            );
        }
    };
    let max_bytes = bounded_response_bytes(
        request.max_bytes.min(request.security.max_response_bytes),
        response_capacity,
    );
    let (content_utf8, truncated) = truncate_lossy_utf8(&bytes, max_bytes);
    let response = WasmFsReadResponse {
        decision: WasmHostCallDecision::Allowed,
        path: request.path,
        bytes_read: content_utf8.len(),
        content_utf8,
        truncated,
        note: format!(
            "bounded fs read completed inside {}",
            runtime_workspace_root().display()
        ),
    };
    write_guest_json_response(
        &memory,
        caller,
        response_ptr,
        response_capacity,
        &render_wasm_fs_read_response_json(&response),
    )
}

fn dispatch_fs_write(
    caller: &mut Caller<'_, RunnerState>,
    request_ptr: i32,
    request_len: i32,
    response_ptr: i32,
    response_capacity: i32,
) -> Result<i32, WasmHostCallStatusCode> {
    let memory = guest_memory(caller)?;
    let request_json = read_guest_utf8(&memory, caller, request_ptr, request_len)?;
    let request = parse_wasm_fs_write_request(&request_json)
        .map_err(|_| WasmHostCallStatusCode::InvalidRequest)?;
    if request.path.trim().is_empty() {
        let response = WasmFsWriteResponse {
            decision: WasmHostCallDecision::Denied,
            path: request.path,
            bytes_written: 0,
            created_dirs: false,
            note: "path must not be empty".to_string(),
        };
        return write_guest_json_response(
            &memory,
            caller,
            response_ptr,
            response_capacity,
            &render_wasm_fs_write_response_json(&response),
        );
    }
    let sandbox_path = match resolve_runtime_workspace_path(&request.path) {
        Ok(path) => path,
        Err(error) => {
            let response = WasmFsWriteResponse {
                decision: WasmHostCallDecision::Denied,
                path: request.path,
                bytes_written: 0,
                created_dirs: false,
                note: error,
            };
            return write_guest_json_response(
                &memory,
                caller,
                response_ptr,
                response_capacity,
                &render_wasm_fs_write_response_json(&response),
            );
        }
    };
    let mut created_dirs = false;
    if let Some(parent) = sandbox_path.parent() {
        if request.create_dirs {
            fs::create_dir_all(parent).map_err(|_| WasmHostCallStatusCode::InternalError)?;
            created_dirs = true;
        } else if !parent.exists() {
            let response = WasmFsWriteResponse {
                decision: WasmHostCallDecision::Denied,
                path: request.path,
                bytes_written: 0,
                created_dirs: false,
                note: format!("parent directory '{}' is missing", parent.display()),
            };
            return write_guest_json_response(
                &memory,
                caller,
                response_ptr,
                response_capacity,
                &render_wasm_fs_write_response_json(&response),
            );
        }
    }
    let content = request.content_utf8.as_bytes();
    let write_result = if request.append {
        fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&sandbox_path)
            .and_then(|mut stream| stream.write_all(content))
    } else {
        fs::write(&sandbox_path, content)
    };
    if let Err(error) = write_result {
        let response = WasmFsWriteResponse {
            decision: WasmHostCallDecision::Denied,
            path: request.path,
            bytes_written: 0,
            created_dirs,
            note: format!("failed to write '{}': {error}", sandbox_path.display()),
        };
        return write_guest_json_response(
            &memory,
            caller,
            response_ptr,
            response_capacity,
            &render_wasm_fs_write_response_json(&response),
        );
    }
    let response = WasmFsWriteResponse {
        decision: WasmHostCallDecision::Allowed,
        path: request.path,
        bytes_written: content.len(),
        created_dirs,
        note: format!(
            "bounded fs write completed inside {}",
            runtime_workspace_root().display()
        ),
    };
    write_guest_json_response(
        &memory,
        caller,
        response_ptr,
        response_capacity,
        &render_wasm_fs_write_response_json(&response),
    )
}

fn dispatch_llm_inference(
    caller: &mut Caller<'_, RunnerState>,
    request_ptr: i32,
    request_len: i32,
    response_ptr: i32,
    response_capacity: i32,
) -> Result<i32, WasmHostCallStatusCode> {
    let memory = guest_memory(caller)?;
    let request_json = read_guest_utf8(&memory, caller, request_ptr, request_len)?;
    let request = parse_wasm_llm_inference_request(&request_json)
        .map_err(|_| WasmHostCallStatusCode::InvalidRequest)?;
    let route_intent = ProviderRouteIntent::llm_inference(&request.model)
        .with_agent_id(&request.security.agent_id)
        .with_org_id(&request.security.org_id)
        .with_preferred_profile_name(&request.provider_profile);
    let requested_model = if route_intent.requested_model.is_empty() {
        "qwen2.5:7b".to_string()
    } else {
        route_intent.requested_model.clone()
    };
    if request.user_prompt.trim().is_empty() {
        let response = WasmLlmInferenceResponse {
            decision: WasmHostCallDecision::Denied,
            model: requested_model,
            output_text: String::new(),
            finish_reason: String::new(),
            prompt_tokens: None,
            completion_tokens: None,
            total_tokens: None,
            note: "user_prompt must not be empty".to_string(),
        };
        return write_guest_json_response(
            &memory,
            caller,
            response_ptr,
            response_capacity,
            &render_wasm_llm_inference_response_json(&response),
        );
    }
    let route = match resolve_llm_route(None, &route_intent) {
        Ok(route) => route,
        Err(error) => {
            let response = WasmLlmInferenceResponse {
                decision: WasmHostCallDecision::Denied,
                model: requested_model,
                output_text: String::new(),
                finish_reason: String::new(),
                prompt_tokens: None,
                completion_tokens: None,
                total_tokens: None,
                note: error,
            };
            return write_guest_json_response(
                &memory,
                caller,
                response_ptr,
                response_capacity,
                &render_wasm_llm_inference_response_json(&response),
            );
        }
    };
    let endpoint_url = route.endpoint_url.clone();
    let auth_headers = match route.resolve_auth_headers() {
        Ok(auth_headers) => auth_headers,
        Err(error) => {
            let response = WasmLlmInferenceResponse {
                decision: WasmHostCallDecision::Denied,
                model: route.model.clone(),
                output_text: String::new(),
                finish_reason: String::new(),
                prompt_tokens: None,
                completion_tokens: None,
                total_tokens: None,
                note: error,
            };
            return write_guest_json_response(
                &memory,
                caller,
                response_ptr,
                response_capacity,
                &render_wasm_llm_inference_response_json(&response),
            );
        }
    };
    if route.model.trim().is_empty() {
        let response = WasmLlmInferenceResponse {
            decision: WasmHostCallDecision::Denied,
            model: requested_model,
            output_text: String::new(),
            finish_reason: String::new(),
            prompt_tokens: None,
            completion_tokens: None,
            total_tokens: None,
            note: "resolved provider route did not provide a model".to_string(),
        };
        return write_guest_json_response(
            &memory,
            caller,
            response_ptr,
            response_capacity,
            &render_wasm_llm_inference_response_json(&response),
        );
    }
    let timeout_ms = request.security.max_timeout_ms.max(1);
    let response_limit = request.security.max_response_bytes.max(1_024).min(65_536);
    let payload = build_llm_request_payload(&route, &request);
    let mut request_builder = ureq::post(endpoint_url.as_str())
        .config()
        .timeout_global(Some(Duration::from_millis(timeout_ms)))
        .http_status_as_error(false)
        .build()
        .header("content-type", "application/json");
    for (header_name, header_value) in auth_headers {
        request_builder = request_builder.header(&header_name, &header_value);
    }
    let mut response = match request_builder.send(payload.to_string()) {
        Ok(response) => response,
        Err(error) => {
            let response = WasmLlmInferenceResponse {
                decision: WasmHostCallDecision::Denied,
                model: payload
                    .get("model")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string(),
                output_text: String::new(),
                finish_reason: String::new(),
                prompt_tokens: None,
                completion_tokens: None,
                total_tokens: None,
                note: format!("LLM request failed: {error}"),
            };
            return write_guest_json_response(
                &memory,
                caller,
                response_ptr,
                response_capacity,
                &render_wasm_llm_inference_response_json(&response),
            );
        }
    };
    let status = response.status().as_u16();
    let response_body = response
        .body_mut()
        .with_config()
        .limit(response_limit as u64)
        .read_to_string()
        .unwrap_or_else(|error| {
            json!({"error": {"message": format!("failed to read body: {error}")}}).to_string()
        });
    let payload: Value =
        serde_json::from_str(&response_body).unwrap_or_else(|_| json!({"raw_body": response_body}));
    let error_message = payload
        .get("error")
        .and_then(|value| value.get("message"))
        .and_then(Value::as_str)
        .map(|value| value.to_string())
        .unwrap_or_else(|| value_string_from_json(payload.get("raw_body")));
    let response_model = payload
        .get("model")
        .and_then(Value::as_str)
        .map(|value| value.to_string())
        .unwrap_or_else(|| requested_model.clone());
    if !(200..300).contains(&status) {
        let response = WasmLlmInferenceResponse {
            decision: WasmHostCallDecision::Denied,
            model: response_model,
            output_text: String::new(),
            finish_reason: String::new(),
            prompt_tokens: payload
                .pointer("/usage/prompt_tokens")
                .and_then(Value::as_u64),
            completion_tokens: payload
                .pointer("/usage/completion_tokens")
                .and_then(Value::as_u64),
            total_tokens: payload
                .pointer("/usage/total_tokens")
                .and_then(Value::as_u64),
            note: format!("LLM endpoint returned HTTP {status}: {error_message}"),
        };
        return write_guest_json_response(
            &memory,
            caller,
            response_ptr,
            response_capacity,
            &render_wasm_llm_inference_response_json(&response),
        );
    }
    let response = WasmLlmInferenceResponse {
        decision: WasmHostCallDecision::Allowed,
        model: response_model,
        output_text: extract_openai_output_text(&payload),
        finish_reason: extract_openai_finish_reason(&payload),
        prompt_tokens: payload
            .pointer("/usage/input_tokens")
            .and_then(Value::as_u64)
            .or_else(|| {
                payload
                    .pointer("/usage/prompt_tokens")
                    .and_then(Value::as_u64)
            }),
        completion_tokens: payload
            .pointer("/usage/output_tokens")
            .and_then(Value::as_u64)
            .or_else(|| {
                payload
                    .pointer("/usage/completion_tokens")
                    .and_then(Value::as_u64)
            }),
        total_tokens: payload
            .pointer("/usage/total_tokens")
            .and_then(Value::as_u64),
        note: format!(
            "bounded llm host call completed against {} via provider profile {} ({})",
            endpoint_url,
            route.profile_name,
            route.profile_kind.label()
        ),
    };
    write_guest_json_response(
        &memory,
        caller,
        response_ptr,
        response_capacity,
        &render_wasm_llm_inference_response_json(&response),
    )
}

fn dispatch_kv_get(
    caller: &mut Caller<'_, RunnerState>,
    request_ptr: i32,
    request_len: i32,
    response_ptr: i32,
    response_capacity: i32,
) -> Result<i32, WasmHostCallStatusCode> {
    let memory = guest_memory(caller)?;
    let request_json = read_guest_utf8(&memory, caller, request_ptr, request_len)?;
    let request = parse_wasm_kv_get_request(&request_json)
        .map_err(|_| WasmHostCallStatusCode::InvalidRequest)?;
    if request.key.trim().is_empty() {
        let response = WasmKvGetResponse {
            decision: WasmHostCallDecision::Denied,
            namespace: request.namespace,
            key: request.key,
            found: false,
            value_json: "null".to_string(),
            note: "key must not be empty".to_string(),
        };
        return write_guest_json_response(
            &memory,
            caller,
            response_ptr,
            response_capacity,
            &render_wasm_kv_get_response_json(&response),
        );
    }
    let store = load_runtime_kv_store().map_err(|_| WasmHostCallStatusCode::InternalError)?;
    let value = store
        .get(&request.namespace)
        .and_then(|entries| entries.get(&request.key));
    let response = WasmKvGetResponse {
        decision: WasmHostCallDecision::Allowed,
        namespace: request.namespace,
        key: request.key,
        found: value.is_some(),
        value_json: value
            .map(|value| value.to_string())
            .unwrap_or_else(|| "null".to_string()),
        note: "local runtime KV lookup completed".to_string(),
    };
    write_guest_json_response(
        &memory,
        caller,
        response_ptr,
        response_capacity,
        &render_wasm_kv_get_response_json(&response),
    )
}

fn dispatch_kv_set(
    caller: &mut Caller<'_, RunnerState>,
    request_ptr: i32,
    request_len: i32,
    response_ptr: i32,
    response_capacity: i32,
) -> Result<i32, WasmHostCallStatusCode> {
    let memory = guest_memory(caller)?;
    let request_json = read_guest_utf8(&memory, caller, request_ptr, request_len)?;
    let request = parse_wasm_kv_set_request(&request_json)
        .map_err(|_| WasmHostCallStatusCode::InvalidRequest)?;
    if request.key.trim().is_empty() {
        let response = WasmKvSetResponse {
            decision: WasmHostCallDecision::Denied,
            namespace: request.namespace,
            key: request.key,
            stored: false,
            note: "key must not be empty".to_string(),
        };
        return write_guest_json_response(
            &memory,
            caller,
            response_ptr,
            response_capacity,
            &render_wasm_kv_set_response_json(&response),
        );
    }
    let value: Value = match serde_json::from_str(&request.value_json) {
        Ok(value) => value,
        Err(error) => {
            let response = WasmKvSetResponse {
                decision: WasmHostCallDecision::Denied,
                namespace: request.namespace,
                key: request.key,
                stored: false,
                note: format!("value_json must be valid JSON: {error}"),
            };
            return write_guest_json_response(
                &memory,
                caller,
                response_ptr,
                response_capacity,
                &render_wasm_kv_set_response_json(&response),
            );
        }
    };
    let mut store = load_runtime_kv_store().map_err(|_| WasmHostCallStatusCode::InternalError)?;
    store
        .entry(request.namespace.clone())
        .or_default()
        .insert(request.key.clone(), value);
    save_runtime_kv_store(&store).map_err(|_| WasmHostCallStatusCode::InternalError)?;
    let response = WasmKvSetResponse {
        decision: WasmHostCallDecision::Allowed,
        namespace: request.namespace,
        key: request.key,
        stored: true,
        note: "local runtime KV write completed".to_string(),
    };
    write_guest_json_response(
        &memory,
        caller,
        response_ptr,
        response_capacity,
        &render_wasm_kv_set_response_json(&response),
    )
}

fn capture_host_response_json(
    store: &mut Store<RunnerState>,
    instance: &Instance,
) -> Result<Option<String>, String> {
    let result_len = read_exported_i32(store, instance, WASM_HOST_RESULT_LEN_EXPORT);
    let result_ptr = read_exported_i32(store, instance, WASM_HOST_RESULT_PTR_EXPORT);
    let (Some(result_len), Some(result_ptr)) = (result_len, result_ptr) else {
        return Ok(None);
    };
    if result_len <= 0 || result_ptr < 0 {
        return Ok(None);
    }
    let memory = match instance
        .get_export(&mut *store, "memory")
        .and_then(|export| export.into_memory())
    {
        Some(memory) => memory,
        None => return Ok(None),
    };
    let mut bytes = vec![0_u8; result_len as usize];
    memory
        .read(&*store, result_ptr as usize, &mut bytes)
        .map_err(|error| format!("failed to read guest host response memory: {error}"))?;
    Ok(String::from_utf8(bytes).ok())
}

fn read_exported_i32(
    store: &mut Store<RunnerState>,
    instance: &Instance,
    export_name: &str,
) -> Option<i32> {
    let global = instance
        .get_export(&mut *store, export_name)?
        .into_global()?;
    match global.get(&mut *store) {
        Val::I32(value) => Some(value),
        _ => None,
    }
}

fn guest_memory(
    caller: &mut Caller<'_, RunnerState>,
) -> Result<wasmtime::Memory, WasmHostCallStatusCode> {
    caller
        .get_export("memory")
        .and_then(|export| export.into_memory())
        .ok_or(WasmHostCallStatusCode::InternalError)
}

fn read_guest_utf8(
    memory: &wasmtime::Memory,
    caller: &Caller<'_, RunnerState>,
    ptr: i32,
    len: i32,
) -> Result<String, WasmHostCallStatusCode> {
    if ptr < 0 || len < 0 {
        return Err(WasmHostCallStatusCode::InvalidRequest);
    }
    let mut bytes = vec![0_u8; len as usize];
    memory
        .read(caller, ptr as usize, &mut bytes)
        .map_err(|_| WasmHostCallStatusCode::InvalidRequest)?;
    String::from_utf8(bytes).map_err(|_| WasmHostCallStatusCode::InvalidRequest)
}

fn write_guest_json_response(
    memory: &wasmtime::Memory,
    caller: &mut Caller<'_, RunnerState>,
    response_ptr: i32,
    response_capacity: i32,
    response_json: &str,
) -> Result<i32, WasmHostCallStatusCode> {
    if response_ptr < 0 || response_capacity < 0 {
        return Err(WasmHostCallStatusCode::InvalidRequest);
    }
    let bytes = response_json.as_bytes();
    if bytes.len() > response_capacity as usize {
        return Err(WasmHostCallStatusCode::ResponseTooLarge);
    }
    memory
        .write(caller, response_ptr as usize, bytes)
        .map_err(|_| WasmHostCallStatusCode::InternalError)?;
    Ok(bytes.len() as i32)
}

fn bounded_timeout_ms(request_timeout_ms: u64, security_timeout_ms: u64) -> u64 {
    let bounded = request_timeout_ms.min(security_timeout_ms.max(1));
    bounded.max(1)
}

fn bounded_response_bytes(request_bytes: usize, response_capacity: i32) -> usize {
    let capacity = response_capacity.max(256) as usize;
    request_bytes.min(capacity).max(256)
}

fn extract_html_title(body: &str) -> String {
    let lower = body.to_lowercase();
    let Some(start_idx) = lower.find("<title>") else {
        return String::new();
    };
    let remainder = &body[start_idx + 7..];
    let lower_remainder = &lower[start_idx + 7..];
    let Some(end_idx) = lower_remainder.find("</title>") else {
        return String::new();
    };
    remainder[..end_idx].trim().to_string()
}

fn resolve_allowed_workdir(working_dir: &str, allowed_roots: &[String]) -> Result<PathBuf, String> {
    let current_dir = std::env::current_dir()
        .map_err(|error| format!("failed to resolve current dir: {error}"))?;
    let requested = if Path::new(working_dir).is_absolute() {
        PathBuf::from(working_dir)
    } else {
        current_dir.join(working_dir)
    };
    let requested = requested
        .canonicalize()
        .map_err(|error| format!("working_dir '{}' is not accessible: {error}", working_dir))?;
    let roots = if allowed_roots.is_empty() {
        vec![".".to_string()]
    } else {
        allowed_roots.to_vec()
    };
    for root in roots {
        let root_path = if Path::new(&root).is_absolute() {
            PathBuf::from(&root)
        } else {
            current_dir.join(&root)
        };
        if let Ok(canonical_root) = root_path.canonicalize() {
            if requested.starts_with(&canonical_root) {
                return Ok(requested);
            }
        }
    }
    Err(format!(
        "working_dir '{}' is outside the allowed roots {:?}",
        requested.display(),
        allowed_roots
    ))
}

fn truncate_lossy_utf8(bytes: &[u8], max_bytes: usize) -> (String, bool) {
    let limit = max_bytes.max(1);
    let truncated = bytes.len() > limit;
    let slice = if truncated { &bytes[..limit] } else { bytes };
    (String::from_utf8_lossy(slice).into_owned(), truncated)
}

fn runtime_workspace_root() -> PathBuf {
    if let Some(root) = std::env::var_os("LOOM_RUNTIME_ROOT")
        .or_else(|| std::env::var_os("MERIDIAN_LOOM_RUNTIME_ROOT"))
    {
        return PathBuf::from(root).join("workspace");
    }
    if let Some(home) = std::env::var_os("HOME") {
        return PathBuf::from(home).join(".local/share/meridian-loom/runtime/default/workspace");
    }
    std::env::temp_dir()
        .join("meridian-loom")
        .join("runtime")
        .join("default")
        .join("workspace")
}

fn normalize_guest_requested_path(raw: &str) -> Result<PathBuf, String> {
    if raw.trim().is_empty() {
        return Err("path must not be empty".to_string());
    }
    let absolute = Path::new(raw).is_absolute();
    let mut normalized = if absolute {
        PathBuf::from("/")
    } else {
        PathBuf::new()
    };
    for component in Path::new(raw).components() {
        match component {
            Component::Normal(segment) => normalized.push(segment),
            Component::CurDir | Component::RootDir => {}
            Component::ParentDir => {
                return Err(format!("path '{}' escapes the allowed read roots", raw))
            }
            Component::Prefix(_) => {
                return Err(format!("path '{}' contains an unsupported prefix", raw))
            }
        }
    }
    let is_root_only = absolute && normalized == Path::new("/");
    if normalized.as_os_str().is_empty() || is_root_only {
        return Err("path must not be empty".to_string());
    }
    Ok(normalized)
}

fn is_allowlisted_diagnostic_path(path: &Path) -> bool {
    matches!(path.to_str(), Some("/etc/os-release" | "/etc/hostname"))
}

fn resolve_runtime_read_path(raw: &str) -> Result<PathBuf, String> {
    let normalized = normalize_guest_requested_path(raw)?;
    if normalized.is_absolute() {
        if is_allowlisted_diagnostic_path(&normalized) {
            return Ok(normalized);
        }
        let workspace_root = runtime_workspace_root();
        if normalized.starts_with(&workspace_root) {
            return Ok(normalized);
        }
        return Err(format!(
            "absolute path '{}' is outside the workspace sandbox and diagnostic allowlist",
            raw
        ));
    }
    let root = runtime_workspace_root();
    fs::create_dir_all(&root).map_err(|error| {
        format!(
            "failed to create runtime workspace root '{}': {error}",
            root.display()
        )
    })?;
    Ok(root.join(normalized))
}

fn resolve_runtime_workspace_path(raw: &str) -> Result<PathBuf, String> {
    let normalized = normalize_guest_requested_path(raw)?;
    if normalized.is_absolute() {
        return Err(format!("absolute path '{}' is not allowed", raw));
    }
    let root = runtime_workspace_root();
    fs::create_dir_all(&root).map_err(|error| {
        format!(
            "failed to create runtime workspace root '{}': {error}",
            root.display()
        )
    })?;
    Ok(root.join(normalized))
}

fn read_allowlisted_text_file(path: &Path, max_bytes: usize) -> (String, bool, Option<String>) {
    match fs::read(path) {
        Ok(bytes) => {
            let (content_utf8, truncated) = truncate_lossy_utf8(&bytes, max_bytes);
            (content_utf8, truncated, None)
        }
        Err(error) => (
            String::new(),
            false,
            Some(format!("failed to read '{}': {error}", path.display())),
        ),
    }
}

fn read_uname_excerpt(max_bytes: usize) -> (String, bool, Option<String>) {
    match Command::new("uname").arg("-a").output() {
        Ok(output) => {
            let (stdout_utf8, truncated) = truncate_lossy_utf8(&output.stdout, max_bytes);
            if output.status.success() {
                (stdout_utf8.trim().to_string(), truncated, None)
            } else {
                let stderr_utf8 = truncate_lossy_utf8(&output.stderr, max_bytes).0;
                let note = if stderr_utf8.trim().is_empty() {
                    format!("uname -a exited with status {:?}", output.status.code())
                } else {
                    format!("uname -a failed: {}", stderr_utf8.trim())
                };
                (stdout_utf8.trim().to_string(), truncated, Some(note))
            }
        }
        Err(error) => (
            String::new(),
            false,
            Some(format!("failed to execute 'uname -a': {error}")),
        ),
    }
}

type RuntimeKvStore = BTreeMap<String, BTreeMap<String, Value>>;

fn runtime_kv_store_path() -> PathBuf {
    PathBuf::from(
        "/home/ubuntu/.local/share/meridian-loom/runtime/default/state/runtime/kv_memory.json",
    )
}

fn load_runtime_kv_store() -> Result<RuntimeKvStore, String> {
    let path = runtime_kv_store_path();
    if !path.exists() {
        return Ok(BTreeMap::new());
    }
    let raw = fs::read_to_string(&path)
        .map_err(|error| format!("failed to read kv store '{}': {error}", path.display()))?;
    if raw.trim().is_empty() {
        return Ok(BTreeMap::new());
    }
    serde_json::from_str(&raw)
        .map_err(|error| format!("failed to parse kv store '{}': {error}", path.display()))
}

fn save_runtime_kv_store(store: &RuntimeKvStore) -> Result<(), String> {
    let path = runtime_kv_store_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| {
            format!(
                "failed to create kv store directory '{}': {error}",
                parent.display()
            )
        })?;
    }
    let raw = serde_json::to_string_pretty(store)
        .map_err(|error| format!("failed to serialize kv store: {error}"))?;
    fs::write(&path, raw)
        .map_err(|error| format!("failed to write kv store '{}': {error}", path.display()))
}

// ---------------------------------------------------------------------------
// PoGE helpers
// ---------------------------------------------------------------------------

/// Returns a dummy KernelWarrant suitable for airgapped / development sessions.
/// All credential fields are zeroed; expiry is set to u64::MAX so the
/// interceptor never rejects a call due to expiry.
fn poge_dummy_warrant() -> KernelWarrant {
    KernelWarrant {
        id: [0u8; 32],
        scope_cbor: vec![],
        expiry_epoch_ms: u64::MAX,
        kernel_sig: [0u8; 64],
        kernel_pub: [0u8; 32],
    }
}

/// Returns the current wall-clock time as UTC milliseconds since the Unix epoch.
fn epoch_ms_now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

/// Read up to 4 KiB from guest memory at `(ptr, len)` for PoGE receipt hashing.
///
/// Returns an empty Vec on any error (invalid pointer, OOB, no memory export).
/// The 4 KiB cap keeps per-call overhead constant regardless of payload size.
fn read_guest_bytes_for_poge(caller: &mut Caller<'_, RunnerState>, ptr: i32, len: i32) -> Vec<u8> {
    const MAX_POGE_BYTES: usize = 4096;
    if ptr < 0 || len <= 0 {
        return Vec::new();
    }
    let clamped = (len as usize).min(MAX_POGE_BYTES);
    // guest_memory needs &mut caller to call get_export; the borrow is released
    // when the function returns and memory is just a lightweight handle.
    let Ok(memory) = guest_memory(caller) else {
        return Vec::new();
    };
    let mut buf = vec![0u8; clamped];
    // &*caller coerces &mut Caller<T> → &Caller<T>, satisfying AsContext.
    if memory.read(&*caller, ptr as usize, &mut buf).is_err() {
        return Vec::new();
    }
    buf
}

fn build_llm_request_payload(
    route: &ResolvedProviderRoute,
    request: &super::WasmLlmInferenceRequest,
) -> Value {
    match route.profile_kind {
        ProviderKind::OpenAiCodex => {
            let mut input = Vec::new();
            input.push(json!({
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": request.user_prompt,
                    }
                ]
            }));
            let mut payload = json!({
                "model": route.model,
                "store": false,
                "input": input,
            });
            if let Some(max_tokens) = request.max_tokens {
                payload["max_output_tokens"] = json!(max_tokens);
            }
            if !request.system_prompt.trim().is_empty() {
                payload["instructions"] = json!(request.system_prompt);
            }
            payload
        }
        _ => {
            let mut messages = vec![];
            if !request.system_prompt.trim().is_empty() {
                messages.push(json!({"role": "system", "content": request.system_prompt}));
            }
            messages.push(json!({"role": "user", "content": request.user_prompt}));
            json!({
                "model": route.model,
                "messages": messages,
                "max_tokens": request.max_tokens,
            })
        }
    }
}

fn extract_openai_finish_reason(payload: &Value) -> String {
    payload
        .pointer("/choices/0/finish_reason")
        .and_then(Value::as_str)
        .or_else(|| payload.get("status").and_then(Value::as_str))
        .unwrap_or_default()
        .to_string()
}

fn extract_openai_output_text(payload: &Value) -> String {
    if let Some(text) = payload.get("output_text").and_then(Value::as_str) {
        return text.to_string();
    }
    if let Some(items) = payload.get("output").and_then(Value::as_array) {
        let collected = items
            .iter()
            .flat_map(|item| {
                item.get("content")
                    .and_then(Value::as_array)
                    .into_iter()
                    .flatten()
            })
            .filter_map(|part| {
                part.get("text")
                    .and_then(Value::as_str)
                    .or_else(|| part.get("content").and_then(Value::as_str))
            })
            .collect::<Vec<_>>()
            .join("");
        if !collected.is_empty() {
            return collected;
        }
    }
    let Some(content) = payload.pointer("/choices/0/message/content") else {
        return String::new();
    };
    match content {
        Value::String(text) => text.clone(),
        Value::Array(parts) => parts
            .iter()
            .filter_map(|part| {
                part.get("text")
                    .and_then(Value::as_str)
                    .or_else(|| part.get("content").and_then(Value::as_str))
            })
            .collect::<Vec<_>>()
            .join(""),
        _ => String::new(),
    }
}

fn value_string_from_json(value: Option<&Value>) -> String {
    match value {
        Some(Value::String(text)) => text.clone(),
        Some(other) => other.to_string(),
        None => String::new(),
    }
}

fn call_i32_function(
    store: &mut Store<RunnerState>,
    func: &wasmtime::Func,
    args: &[i32],
) -> Result<Option<i32>, String> {
    if args.len() > 1 {
        return Err(
            "experimental local Wasm lane supports at most one i32 argument for now".to_string(),
        );
    }
    let mut results = vec![Val::I32(0); func.ty(&*store).results().len()];
    match args.len() {
        0 => func
            .call(store, &[], &mut results)
            .map_err(|error| format!("wasm call failed: {error}"))?,
        1 => func
            .call(store, &[Val::I32(args[0])], &mut results)
            .map_err(|error| format!("wasm call failed: {error}"))?,
        _ => unreachable!(),
    }
    Ok(match results.first() {
        Some(Val::I32(value)) => Some(*value),
        _ => None,
    })
}

#[cfg(test)]
mod tests {
    use super::resolve_runtime_read_path;
    use std::path::{Path, PathBuf};

    #[test]
    fn runtime_read_path_allows_workspace_relative_inputs() {
        let resolved =
            resolve_runtime_read_path("notes/summary.txt").expect("workspace relative path");
        assert!(resolved.is_absolute());
        assert!(resolved.ends_with(Path::new("workspace/notes/summary.txt")));
    }

    #[test]
    fn runtime_read_path_allows_explicit_diagnostic_allowlist() {
        assert_eq!(
            resolve_runtime_read_path("/etc/os-release").expect("allowlisted diagnostic"),
            PathBuf::from("/etc/os-release")
        );
        assert_eq!(
            resolve_runtime_read_path("/etc/hostname").expect("allowlisted diagnostic"),
            PathBuf::from("/etc/hostname")
        );
    }

    #[test]
    fn runtime_read_path_rejects_parent_segments_and_non_allowlisted_absolutes() {
        assert!(resolve_runtime_read_path("../secrets.txt").is_err());
        assert!(resolve_runtime_read_path("/etc/shadow").is_err());
    }
}
