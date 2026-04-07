use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

use crate::bindings::resolve_binding;
use crate::channels::{enqueue_channel_delivery, ChannelDeliveryRequest};
use crate::output_guard::{guard_user_visible_output, OutputGuardPolicy};
use crate::provider_router::{resolve_provider_route, ProviderRouteIntent};
use crate::service_ingress_runtime::ServiceIngressRecord;
use crate::session_policy::{apply_session_overrides, get_session_send_policy};
use crate::session_provenance::update_session_provenance_job;

pub type LoomResult<T> = Result<T, String>;

const DEFAULT_PIPELINE_RUNS_DIR: &str = "state/pipeline/runs";
const DEFAULT_PIPELINE_INDEX_PATH: &str = "state/pipeline/index.json";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PipelineRunRecord {
    pub pipeline_id: String,
    pub ingress_request_id: String,
    pub channel_id: String,
    pub peer_id: String,
    pub session_key: String,
    pub binding_id: String,
    pub agent_id: String,
    pub provider_profile: String,
    pub model: String,
    pub transport_kind: String,
    pub auth_mode: String,
    pub execution_owner: String,
    pub job_id: Option<String>,
    pub delivery_id: Option<String>,
    pub status: String,
    pub started_at: String,
    pub completed_at: Option<String>,
    pub override_applied: bool,
    pub send_policy: String,
    pub output_guard_class: Option<String>,
    pub last_error: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PipelineOverview {
    pub runs_dir: PathBuf,
    pub total_count: usize,
    pub completed_count: usize,
    pub failed_count: usize,
    pub pipeline_ids: Vec<String>,
}

pub fn pipeline_runs_dir(root: &Path) -> PathBuf {
    root.join(DEFAULT_PIPELINE_RUNS_DIR)
}

pub fn pipeline_index_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_PIPELINE_INDEX_PATH)
}

pub fn ensure_pipeline_scaffold(root: &Path) -> LoomResult<PathBuf> {
    let runs_dir = pipeline_runs_dir(root);
    fs::create_dir_all(&runs_dir).map_err(io_err)?;
    let index_path = pipeline_index_path(root);
    if !index_path.exists() {
        fs::write(&index_path, "{\n  \"index\": {}\n}\n").map_err(io_err)?;
    }
    Ok(runs_dir)
}

/// Execute the full pipeline for an ingress request:
/// ingress -> binding -> session provenance -> provider route (+ overrides) -> dispatch -> guard -> deliver
pub fn execute_pipeline_step(
    root: &Path,
    ingress: &ServiceIngressRecord,
) -> LoomResult<PipelineRunRecord> {
    ensure_pipeline_scaffold(root)?;
    let pipeline_id = format!("pipeline-{}", unique_token());
    let now = timestamp_now();

    // Step 1: Resolve binding from ingress metadata
    // Normalize transport targets to Loom-native channel edges
    let channel_id = normalize_ingress_channel(&ingress.ingress_target, &ingress.transport);
    let peer_id = infer_peer_from_ingress(ingress);

    let (binding_id, agent_id, session_key) =
        match resolve_binding(root, &channel_id, &peer_id, None, None) {
            Ok(resolution) => (
                resolution.binding_id,
                resolution.agent_id,
                resolution.session_key,
            ),
            Err(err) => {
                // Cannot resolve binding; record failed pipeline step
                let run = PipelineRunRecord {
                    pipeline_id: pipeline_id.clone(),
                    ingress_request_id: ingress.request_id.clone(),
                    channel_id: channel_id.clone(),
                    peer_id: peer_id.clone(),
                    session_key: String::new(),
                    binding_id: String::new(),
                    agent_id: ingress.agent_id.clone(),
                    provider_profile: String::new(),
                    model: String::new(),
                    transport_kind: String::new(),
                    auth_mode: String::new(),
                    execution_owner: String::new(),
                    job_id: None,
                    delivery_id: None,
                    status: "failed".to_string(),
                    started_at: now.clone(),
                    completed_at: Some(timestamp_now()),
                    override_applied: false,
                    send_policy: "deliver".to_string(),
                    output_guard_class: None,
                    last_error: Some(format!("binding resolution failed: {}", err)),
                };
                persist_pipeline_run(root, &run)?;
                return Ok(run);
            }
        };

    // Step 2: Session provenance is already opened by resolve_binding -> open_session_provenance
    // Step 3: Apply session-level overrides
    let (override_profile, override_model, override_source) =
        apply_session_overrides(root, &session_key).unwrap_or((None, None, "default".to_string()));
    let override_applied = override_profile.is_some() || override_model.is_some();

    // Step 4: Resolve provider route with overrides applied
    let capability = if !ingress.capability_name.is_empty() {
        ingress.capability_name.clone()
    } else {
        "loom.llm.inference.v1".to_string()
    };
    let mut intent = ProviderRouteIntent::for_capability(&capability, "");
    intent.agent_id = Some(agent_id.clone());
    if let Some(ref profile) = override_profile {
        intent.preferred_profile_name = Some(profile.clone());
    }
    if let Some(ref model) = override_model {
        intent.requested_model = model.clone();
    }
    let (provider_profile, model, transport_kind, auth_mode, execution_owner) =
        match resolve_provider_route(Some(root), &intent) {
            Ok(route) => {
                let transport_kind = route.transport_kind().to_string();
                let auth_mode = route.auth.label().to_string();
                let execution_owner = route.execution_owner().to_string();
                (
                    route.profile_name,
                    route.model,
                    transport_kind,
                    auth_mode,
                    execution_owner,
                )
            }
            Err(_) => (
                String::new(),
                String::new(),
                String::new(),
                String::new(),
                String::new(),
            ),
        };

    // Update session provenance with route info
    let _ = crate::session_provenance::update_session_provenance_route_full(
        root,
        &session_key,
        &provider_profile,
        &model,
        &override_source,
        &transport_kind,
        &auth_mode,
        &execution_owner,
        "",
    );

    // Step 5: Determine send policy
    let send_policy = get_session_send_policy(root, &session_key)
        .ok()
        .flatten()
        .map(|p| p.mode)
        .unwrap_or_else(|| "deliver".to_string());

    let mut run = PipelineRunRecord {
        pipeline_id: pipeline_id.clone(),
        ingress_request_id: ingress.request_id.clone(),
        channel_id: channel_id.clone(),
        peer_id: peer_id.clone(),
        session_key: session_key.clone(),
        binding_id: binding_id.clone(),
        agent_id: agent_id.clone(),
        provider_profile: provider_profile.clone(),
        model: model.clone(),
        transport_kind: transport_kind.clone(),
        auth_mode: auth_mode.clone(),
        execution_owner: execution_owner.clone(),
        job_id: ingress.job_id.clone().if_not_empty(),
        delivery_id: None,
        status: "dispatched".to_string(),
        started_at: now.clone(),
        completed_at: None,
        override_applied,
        send_policy: send_policy.clone(),
        output_guard_class: None,
        last_error: None,
    };

    persist_pipeline_run(root, &run)?;
    index_pipeline_run(root, &ingress.request_id, &pipeline_id)?;

    // Step 6: Dispatch the job if service is running
    let output_text =
        attempt_pipeline_dispatch(root, ingress, &agent_id, &provider_profile, &model);

    // Step 7: Guard output
    let guard_class = if let Some(ref text) = output_text {
        let policy = OutputGuardPolicy {
            allow_receipt_hashes: false,
            allow_operator_diagnostics: false,
        };
        match guard_user_visible_output(text, &policy) {
            Ok(guard_result) => Some(guard_result.final_class.to_string()),
            Err(_) => Some("guard_error".to_string()),
        }
    } else {
        None
    };
    run.output_guard_class = guard_class;

    // Step 8: Deliver if send policy says so and we have output
    if send_policy == "deliver" || send_policy == "echo" {
        if let Some(text) = output_text.as_ref() {
            if !text.is_empty() && !channel_id.is_empty() {
                if let Ok(delivery) = enqueue_channel_delivery(
                    root,
                    &ChannelDeliveryRequest {
                        channel_id: channel_id.clone(),
                        recipient: peer_id.clone(),
                        raw_text: text.clone(),
                        allow_receipt_hashes: false,
                        allow_operator_diagnostics: false,
                    },
                ) {
                    run.delivery_id = Some(delivery.delivery_id.clone());
                    // Step 9: Update session provenance with job and delivery
                    let _ = update_session_provenance_job(
                        root,
                        &session_key,
                        run.job_id.as_deref(),
                        Some(&delivery.delivery_id),
                        Some(&ingress.request_id),
                    );
                }
            }
        }
    }

    run.status = "completed".to_string();
    run.completed_at = Some(timestamp_now());
    persist_pipeline_run(root, &run)?;
    Ok(run)
}

/// Record a pipeline entry from the live service ingress path.
/// Called after the service runtime accepts a request and queues a job.
/// Records truth about what is known at acceptance time — does not claim completion.
pub fn record_pipeline_from_ingress(
    root: &Path,
    request_id: &str,
    ingress_target: &str,
    transport: &str,
    agent_id: &str,
    org_id: &str,
    capability_name: &str,
    job_id: &str,
) -> LoomResult<PipelineRunRecord> {
    ensure_pipeline_scaffold(root)?;
    let pipeline_id = format!("pipeline-{}", unique_token());
    let now = timestamp_now();

    let channel_id = normalize_ingress_channel(ingress_target, transport);
    let peer_id = if !org_id.is_empty() {
        org_id.to_string()
    } else if !agent_id.is_empty() {
        format!("agent:{}", agent_id)
    } else {
        "unknown".to_string()
    };

    // Best-effort binding resolution for session provenance
    let (binding_id, resolved_agent, session_key) =
        match resolve_binding(root, &channel_id, &peer_id, None, None) {
            Ok(r) => (r.binding_id, r.agent_id, r.session_key),
            Err(_) => (
                String::new(),
                agent_id.to_string(),
                format!("{}:{}", channel_id, peer_id),
            ),
        };

    // Apply session overrides
    let (override_profile, override_model, override_source) =
        apply_session_overrides(root, &session_key).unwrap_or((None, None, "default".to_string()));
    let override_applied = override_profile.is_some() || override_model.is_some();

    // Resolve provider route with overrides
    let cap = if capability_name.is_empty() {
        "loom.llm.inference.v1"
    } else {
        capability_name
    };
    let mut intent = ProviderRouteIntent::for_capability(cap, "");
    intent.agent_id = Some(resolved_agent.clone());
    if let Some(ref profile) = override_profile {
        intent.preferred_profile_name = Some(profile.clone());
    }
    if let Some(ref model) = override_model {
        intent.requested_model = model.clone();
    }
    let (provider_profile, model, transport_kind, auth_mode, execution_owner) =
        match resolve_provider_route(Some(root), &intent) {
            Ok(route) => {
                let transport_kind = route.transport_kind().to_string();
                let auth_mode = route.auth.label().to_string();
                let execution_owner = route.execution_owner().to_string();
                (
                    route.profile_name,
                    route.model,
                    transport_kind,
                    auth_mode,
                    execution_owner,
                )
            }
            Err(_) => (
                String::new(),
                String::new(),
                String::new(),
                String::new(),
                String::new(),
            ),
        };

    // Update session provenance with route info
    let _ = crate::session_provenance::update_session_provenance_route_full(
        root,
        &session_key,
        &provider_profile,
        &model,
        &override_source,
        &transport_kind,
        &auth_mode,
        &execution_owner,
        "",
    );

    // Get send policy
    let send_policy = get_session_send_policy(root, &session_key)
        .ok()
        .flatten()
        .map(|p| p.mode)
        .unwrap_or_else(|| "deliver".to_string());

    // Update session provenance with job linkage
    let _ = update_session_provenance_job(
        root,
        &session_key,
        if job_id.is_empty() {
            None
        } else {
            Some(job_id)
        },
        None,
        Some(request_id),
    );

    let run = PipelineRunRecord {
        pipeline_id: pipeline_id.clone(),
        ingress_request_id: request_id.to_string(),
        channel_id,
        peer_id,
        session_key,
        binding_id,
        agent_id: resolved_agent,
        provider_profile,
        model,
        transport_kind,
        auth_mode,
        execution_owner,
        job_id: if job_id.is_empty() {
            None
        } else {
            Some(job_id.to_string())
        },
        delivery_id: None,
        status: "accepted".to_string(),
        started_at: now,
        completed_at: None,
        override_applied,
        send_policy,
        output_guard_class: None,
        last_error: None,
    };

    persist_pipeline_run(root, &run)?;
    index_pipeline_run(root, request_id, &pipeline_id)?;
    Ok(run)
}

pub fn list_pipeline_runs(root: &Path, limit: usize) -> LoomResult<Vec<PipelineRunRecord>> {
    ensure_pipeline_scaffold(root)?;
    let runs_dir = pipeline_runs_dir(root);
    let entries = match fs::read_dir(&runs_dir) {
        Ok(entries) => entries,
        Err(_) => return Ok(Vec::new()),
    };
    let mut paths: Vec<PathBuf> = entries
        .filter_map(|entry| entry.ok().map(|e| e.path()))
        .filter(|path| path.extension().and_then(|ext| ext.to_str()) == Some("json"))
        .collect();
    paths.sort_by(|a, b| b.file_name().cmp(&a.file_name()));
    let mut records = Vec::new();
    for path in paths {
        let raw = match fs::read_to_string(&path) {
            Ok(raw) => raw,
            Err(_) => continue,
        };
        if let Ok(run) = parse_pipeline_run(&raw) {
            records.push(run);
            if limit > 0 && records.len() >= limit {
                break;
            }
        }
    }
    Ok(records)
}

pub fn show_pipeline_run(root: &Path, pipeline_id: &str) -> LoomResult<Option<PipelineRunRecord>> {
    let pipeline_id = pipeline_id.trim();
    if pipeline_id.is_empty() {
        return Err("pipeline_id is required".to_string());
    }
    ensure_pipeline_scaffold(root)?;
    let path = pipeline_runs_dir(root).join(format!("{}.json", safe_filename(pipeline_id)));
    if !path.exists() {
        return Ok(None);
    }
    let raw = fs::read_to_string(&path).map_err(io_err)?;
    Ok(Some(parse_pipeline_run(&raw)?))
}

pub fn pipeline_overview(root: &Path) -> LoomResult<PipelineOverview> {
    ensure_pipeline_scaffold(root)?;
    let runs = list_pipeline_runs(root, 0)?;
    let completed = runs.iter().filter(|r| r.status == "completed").count();
    let failed = runs.iter().filter(|r| r.status == "failed").count();
    let ids = runs.iter().map(|r| r.pipeline_id.clone()).collect();
    Ok(PipelineOverview {
        runs_dir: pipeline_runs_dir(root),
        total_count: runs.len(),
        completed_count: completed,
        failed_count: failed,
        pipeline_ids: ids,
    })
}

// --- render ---

pub fn render_pipeline_run_human(run: &PipelineRunRecord) -> String {
    format!(
        "pipeline_id:       {}\ningress_id:        {}\nchannel_id:        {}\npeer_id:           {}\nsession_key:       {}\nbinding_id:        {}\nagent_id:          {}\nprovider_profile:  {}\nmodel:             {}\ntransport_kind:    {}\nauth_mode:         {}\nexecution_owner:   {}\njob_id:            {}\ndelivery_id:       {}\nstatus:            {}\nstarted_at:        {}\ncompleted_at:      {}\noverride_applied:  {}\nsend_policy:       {}\noutput_guard_class:{}\nlast_error:        {}\n",
        run.pipeline_id,
        run.ingress_request_id,
        run.channel_id,
        run.peer_id,
        run.session_key,
        run.binding_id,
        run.agent_id,
        if run.provider_profile.is_empty() { "(none)" } else { &run.provider_profile },
        if run.model.is_empty() { "(none)" } else { &run.model },
        if run.transport_kind.is_empty() { "(none)" } else { &run.transport_kind },
        if run.auth_mode.is_empty() { "(none)" } else { &run.auth_mode },
        if run.execution_owner.is_empty() { "(none)" } else { &run.execution_owner },
        run.job_id.as_deref().unwrap_or("(none)"),
        run.delivery_id.as_deref().unwrap_or("(none)"),
        run.status,
        run.started_at,
        run.completed_at.as_deref().unwrap_or("(none)"),
        run.override_applied,
        run.send_policy,
        run.output_guard_class.as_deref().unwrap_or("(none)"),
        run.last_error.as_deref().unwrap_or("(none)"),
    )
}

pub fn render_pipeline_run_json(run: &PipelineRunRecord) -> String {
    serde_json::to_string_pretty(&pipeline_run_json(run)).unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_pipeline_runs_list_human(runs: &[PipelineRunRecord]) -> String {
    if runs.is_empty() {
        return "pipeline_count:    0\n".to_string();
    }
    let mut out = format!("pipeline_count:    {}\n", runs.len());
    for run in runs {
        out.push_str(&format!(
            "\n- {} channel={} agent={} status={} policy={}\n",
            run.pipeline_id, run.channel_id, run.agent_id, run.status, run.send_policy
        ));
    }
    out
}

pub fn render_pipeline_runs_list_json(runs: &[PipelineRunRecord]) -> String {
    serde_json::to_string_pretty(&runs.iter().map(pipeline_run_json).collect::<Vec<_>>())
        .unwrap_or_else(|_| "[]".to_string())
        + "\n"
}

pub fn render_pipeline_overview_human(overview: &PipelineOverview) -> String {
    format!(
        "runs_dir:          {}\ntotal_count:       {}\ncompleted_count:   {}\nfailed_count:      {}\n",
        overview.runs_dir.display(),
        overview.total_count,
        overview.completed_count,
        overview.failed_count,
    )
}

pub fn render_pipeline_overview_json(overview: &PipelineOverview) -> String {
    serde_json::to_string_pretty(&json!({
        "runs_dir": overview.runs_dir.display().to_string(),
        "total_count": overview.total_count,
        "completed_count": overview.completed_count,
        "failed_count": overview.failed_count,
        "pipeline_ids": overview.pipeline_ids,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

// --- internal ---

fn persist_pipeline_run(root: &Path, run: &PipelineRunRecord) -> LoomResult<()> {
    let path = pipeline_runs_dir(root).join(format!("{}.json", safe_filename(&run.pipeline_id)));
    let mut rendered =
        serde_json::to_string_pretty(&pipeline_run_json(run)).map_err(|e| e.to_string())?;
    rendered.push('\n');
    fs::write(path, rendered).map_err(io_err)
}

fn index_pipeline_run(root: &Path, ingress_id: &str, pipeline_id: &str) -> LoomResult<()> {
    let index_path = pipeline_index_path(root);
    let raw = if index_path.exists() {
        fs::read_to_string(&index_path).unwrap_or_else(|_| "{\"index\":{}}".to_string())
    } else {
        "{\"index\":{}}".to_string()
    };
    let mut value: Value = serde_json::from_str(&raw).unwrap_or_else(|_| json!({"index": {}}));
    if let Some(obj) = value.as_object_mut() {
        let index = obj.entry("index").or_insert_with(|| json!({}));
        if let Some(map) = index.as_object_mut() {
            map.insert(
                ingress_id.to_string(),
                Value::String(pipeline_id.to_string()),
            );
        }
    }
    let mut rendered = serde_json::to_string_pretty(&value).unwrap_or_default();
    rendered.push('\n');
    let _ = fs::write(index_path, rendered);
    Ok(())
}

fn attempt_pipeline_dispatch(
    _root: &Path,
    ingress: &ServiceIngressRecord,
    _agent_id: &str,
    _provider_profile: &str,
    _model: &str,
) -> Option<String> {
    // The pipeline records truth about dispatch state.
    // Actual job execution happens in the service supervisor loop (loom-shadow).
    // If the ingress request has been accepted and has a job_id, the job is queued.
    // We do not invoke a subprocess from here — that would create recursive dispatch.
    if !ingress.job_id.is_empty() {
        // Job was queued by the service runtime — report that truthfully
        Some(format!("job queued: {}", ingress.job_id))
    } else if !ingress.payload_json.is_empty() {
        // Payload present but no job_id yet — request accepted but not yet queued
        Some(format!("request accepted: {}", ingress.request_id))
    } else {
        None
    }
}

/// Normalize a transport-level ingress target to a Loom-native channel edge.
/// Service/HTTP/socket/file ingress maps to `web_api`.
/// Telegram-related targets map to `telegram`.
/// Recognized channel IDs pass through unchanged.
fn normalize_ingress_channel(ingress_target: &str, transport: &str) -> String {
    let target = ingress_target.trim();
    let transport_lower = transport.trim().to_ascii_lowercase();

    // Recognized Loom channel IDs pass through unchanged
    if matches!(
        target,
        "web_api" | "telegram" | "discord" | "slack" | "email" | "matrix"
    ) {
        return target.to_string();
    }

    // Telegram transport or target heuristic
    if target.contains("telegram") || transport_lower.contains("telegram") {
        return "telegram".to_string();
    }

    // Transport-level targets (socket paths, HTTP addresses, file paths) -> web_api
    if target.contains('/')
        || target.contains(':')
        || target.contains(".sock")
        || target.is_empty()
        || transport_lower == "socket"
        || transport_lower == "http"
        || transport_lower == "file_ingress"
    {
        return "web_api".to_string();
    }

    // Unknown target — default to web_api
    "web_api".to_string()
}

fn infer_peer_from_ingress(ingress: &ServiceIngressRecord) -> String {
    // Try to infer peer from org_id, falling back to a synthetic peer
    if !ingress.org_id.is_empty() {
        ingress.org_id.clone()
    } else if !ingress.agent_id.is_empty() {
        format!("agent:{}", ingress.agent_id)
    } else {
        "unknown".to_string()
    }
}

fn parse_pipeline_run(raw: &str) -> LoomResult<PipelineRunRecord> {
    let v: Value =
        serde_json::from_str(raw).map_err(|e| format!("invalid pipeline run json: {e}"))?;
    Ok(PipelineRunRecord {
        pipeline_id: value_string(v.get("pipeline_id"), "pipeline_id")?,
        ingress_request_id: value_string_or(v.get("ingress_request_id"), ""),
        channel_id: value_string_or(v.get("channel_id"), ""),
        peer_id: value_string_or(v.get("peer_id"), ""),
        session_key: value_string_or(v.get("session_key"), ""),
        binding_id: value_string_or(v.get("binding_id"), ""),
        agent_id: value_string_or(v.get("agent_id"), ""),
        provider_profile: value_string_or(v.get("provider_profile"), ""),
        model: value_string_or(v.get("model"), ""),
        transport_kind: value_string_or(v.get("transport_kind"), ""),
        auth_mode: value_string_or(v.get("auth_mode"), ""),
        execution_owner: value_string_or(v.get("execution_owner"), ""),
        job_id: value_opt_string(v.get("job_id")),
        delivery_id: value_opt_string(v.get("delivery_id")),
        status: value_string_or(v.get("status"), "unknown"),
        started_at: value_string_or(v.get("started_at"), ""),
        completed_at: value_opt_string(v.get("completed_at")),
        override_applied: v
            .get("override_applied")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        send_policy: value_string_or(v.get("send_policy"), "deliver"),
        output_guard_class: value_opt_string(v.get("output_guard_class")),
        last_error: value_opt_string(v.get("last_error")),
    })
}

fn pipeline_run_json(run: &PipelineRunRecord) -> Value {
    json!({
        "pipeline_id": run.pipeline_id,
        "ingress_request_id": run.ingress_request_id,
        "channel_id": run.channel_id,
        "peer_id": run.peer_id,
        "session_key": run.session_key,
        "binding_id": run.binding_id,
        "agent_id": run.agent_id,
        "provider_profile": run.provider_profile,
        "model": run.model,
        "transport_kind": run.transport_kind,
        "auth_mode": run.auth_mode,
        "execution_owner": run.execution_owner,
        "job_id": run.job_id,
        "delivery_id": run.delivery_id,
        "status": run.status,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "override_applied": run.override_applied,
        "send_policy": run.send_policy,
        "output_guard_class": run.output_guard_class,
        "last_error": run.last_error,
    })
}

fn safe_filename(input: &str) -> String {
    input
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || ch == '-' || ch == '_' {
                ch.to_ascii_lowercase()
            } else {
                '-'
            }
        })
        .collect()
}

fn timestamp_now() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    format!("{}", secs)
}

fn unique_token() -> String {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos()
        .to_string()
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

trait IntoOption {
    fn if_not_empty(self) -> Option<String>;
}

impl IntoOption for String {
    fn if_not_empty(self) -> Option<String> {
        if self.is_empty() {
            None
        } else {
            Some(self)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::init_workspace;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_path(label: &str) -> PathBuf {
        let ts = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        std::env::temp_dir().join(format!("{}-{}", label, ts))
    }

    #[test]
    fn ensure_pipeline_scaffold_creates_dirs() {
        let root = temp_path("loom-pipeline-scaffold");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        let runs_dir = ensure_pipeline_scaffold(&root).expect("scaffold");
        assert!(runs_dir.exists());
        assert!(pipeline_index_path(&root).exists());
    }

    #[test]
    fn list_pipeline_runs_empty_on_fresh_root() {
        let root = temp_path("loom-pipeline-list");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        let runs = list_pipeline_runs(&root, 10).expect("list");
        assert!(runs.is_empty());
    }

    #[test]
    fn show_pipeline_run_returns_none_for_unknown() {
        let root = temp_path("loom-pipeline-show");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        let result = show_pipeline_run(&root, "pipeline-does-not-exist").expect("show");
        assert!(result.is_none());
    }
}
