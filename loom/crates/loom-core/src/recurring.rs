use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

use crate::channels::{enqueue_channel_delivery, ChannelDeliveryRequest};

pub type LoomResult<T> = Result<T, String>;

pub const DEFAULT_HEARTBEAT_REGISTRY_PATH: &str = "state/heartbeats/registry.json";
pub const DEFAULT_HEARTBEAT_RUNS_DIR: &str = "state/heartbeats/runs";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HeartbeatDeliveryTarget {
    pub channel_id: String,
    pub recipient: String,
    pub allow_receipt_hashes: bool,
    pub allow_operator_diagnostics: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HeartbeatRecord {
    pub heartbeat_id: String,
    pub agent_id: String,
    pub capability_name: String,
    pub schedule_kind: String,
    pub schedule_expression: String,
    pub timezone: String,
    pub every_seconds: u64,
    pub jitter_seconds: u64,
    pub not_before_unix_ms: Option<u64>,
    pub payload_json: String,
    pub delivery_target: Option<HeartbeatDeliveryTarget>,
    pub enabled: bool,
    pub status: String,
    pub max_attempts: u32,
    pub run_count: u32,
    pub last_fire_at_unix_ms: Option<u64>,
    pub next_fire_at_unix_ms: Option<u64>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HeartbeatScheduleRequest {
    pub heartbeat_id: Option<String>,
    pub agent_id: String,
    pub capability_name: String,
    pub schedule_kind: String,
    pub schedule_expression: String,
    pub timezone: String,
    pub every_seconds: u64,
    pub jitter_seconds: u64,
    pub not_before_unix_ms: Option<u64>,
    pub payload_json: String,
    pub delivery_target: Option<HeartbeatDeliveryTarget>,
    pub max_attempts: u32,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HeartbeatRuntimeOverview {
    pub registry_path: PathBuf,
    pub runs_path: PathBuf,
    pub total_count: usize,
    pub enabled_count: usize,
    pub due_count: usize,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HeartbeatMutationResult {
    pub registry_path: PathBuf,
    pub record: HeartbeatRecord,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HeartbeatRunRecord {
    pub run_id: String,
    pub heartbeat_id: String,
    pub agent_id: String,
    pub capability_name: String,
    pub fired_at_unix_ms: u64,
    pub payload_json: String,
    pub status: String,
    pub delivery_channel_id: Option<String>,
    pub delivery_recipient: Option<String>,
    pub delivery_id: Option<String>,
    pub delivery_status: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HeartbeatRunSummary {
    pub registry_path: PathBuf,
    pub runs_path: PathBuf,
    pub dispatched_count: usize,
    pub delivery_attempted_count: usize,
    pub delivery_queued_count: usize,
    pub delivery_blocked_count: usize,
    pub run_records: Vec<HeartbeatRunRecord>,
}

pub fn heartbeat_registry_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_HEARTBEAT_REGISTRY_PATH)
}

pub fn heartbeat_runs_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_HEARTBEAT_RUNS_DIR)
}

pub fn ensure_heartbeat_runtime_scaffold(root: &Path) -> LoomResult<PathBuf> {
    let registry_path = heartbeat_registry_path(root);
    if let Some(parent) = registry_path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    let runs_path = heartbeat_runs_path(root);
    fs::create_dir_all(&runs_path).map_err(io_err)?;
    if !registry_path.exists() {
        fs::write(&registry_path, "{\n  \"heartbeats\": []\n}\n").map_err(io_err)?;
    }
    Ok(registry_path)
}

pub fn load_heartbeats(root: &Path) -> LoomResult<Vec<HeartbeatRecord>> {
    ensure_heartbeat_runtime_scaffold(root)?;
    let raw = fs::read_to_string(heartbeat_registry_path(root)).map_err(io_err)?;
    parse_heartbeat_registry(&raw)
}

pub fn heartbeat_overview(root: &Path, now_unix_ms: u64) -> LoomResult<HeartbeatRuntimeOverview> {
    let records = load_heartbeats(root)?;
    let enabled_count = records.iter().filter(|record| record.enabled).count();
    let due_count = records
        .iter()
        .filter(|record| heartbeat_is_due(record, now_unix_ms))
        .count();
    Ok(HeartbeatRuntimeOverview {
        registry_path: heartbeat_registry_path(root),
        runs_path: heartbeat_runs_path(root),
        total_count: records.len(),
        enabled_count,
        due_count,
    })
}

pub fn heartbeat_summary(root: &Path, heartbeat_id: &str) -> LoomResult<HeartbeatRecord> {
    let heartbeat_id = heartbeat_id.trim();
    if heartbeat_id.is_empty() {
        return Err("heartbeat_id is required".to_string());
    }
    load_heartbeats(root)?
        .into_iter()
        .find(|record| record.heartbeat_id == heartbeat_id)
        .ok_or_else(|| format!("heartbeat '{}' was not found", heartbeat_id))
}

pub fn schedule_heartbeat(
    root: &Path,
    request: &HeartbeatScheduleRequest,
) -> LoomResult<HeartbeatMutationResult> {
    validate_schedule_request(request)?;
    let mut records = load_heartbeats(root)?;
    let heartbeat_id = request
        .heartbeat_id
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .unwrap_or_else(|| format!("heartbeat-{}", unique_token()));
    if records
        .iter()
        .any(|record| record.heartbeat_id == heartbeat_id)
    {
        return Err(format!("heartbeat '{}' already exists", heartbeat_id));
    }
    let next_fire_at_unix_ms = initial_next_fire_at(request, now_unix_ms());
    let record = HeartbeatRecord {
        heartbeat_id,
        agent_id: request.agent_id.trim().to_string(),
        capability_name: request.capability_name.trim().to_string(),
        schedule_kind: request.schedule_kind.trim().to_string(),
        schedule_expression: request.schedule_expression.trim().to_string(),
        timezone: normalized_or(Some(&request.timezone), "UTC"),
        every_seconds: request.every_seconds,
        jitter_seconds: request.jitter_seconds,
        not_before_unix_ms: request.not_before_unix_ms,
        payload_json: normalized_or(Some(&request.payload_json), "{}"),
        delivery_target: request.delivery_target.clone(),
        enabled: true,
        status: "scheduled".to_string(),
        max_attempts: request.max_attempts.max(1),
        run_count: 0,
        last_fire_at_unix_ms: None,
        next_fire_at_unix_ms,
    };
    records.push(record.clone());
    persist_heartbeat_registry(root, &records)?;
    Ok(HeartbeatMutationResult {
        registry_path: heartbeat_registry_path(root),
        record,
    })
}

pub fn pause_heartbeat(root: &Path, heartbeat_id: &str) -> LoomResult<HeartbeatMutationResult> {
    mutate_heartbeat(root, heartbeat_id, |record| {
        record.enabled = false;
        record.status = "paused".to_string();
    })
}

pub fn cancel_heartbeat(root: &Path, heartbeat_id: &str) -> LoomResult<HeartbeatMutationResult> {
    mutate_heartbeat(root, heartbeat_id, |record| {
        record.enabled = false;
        record.status = "cancelled".to_string();
        record.next_fire_at_unix_ms = None;
    })
}

pub fn run_due_heartbeats(
    root: &Path,
    now_unix_ms: u64,
    limit: usize,
) -> LoomResult<HeartbeatRunSummary> {
    let mut records = load_heartbeats(root)?;
    let effective_limit = if limit == 0 { usize::MAX } else { limit };
    let mut run_records = Vec::new();
    let mut delivery_attempted_count: usize = 0;
    let mut delivery_queued_count: usize = 0;
    let mut delivery_blocked_count: usize = 0;

    for record in records.iter_mut() {
        if run_records.len() >= effective_limit {
            break;
        }
        if !heartbeat_is_due(record, now_unix_ms) {
            continue;
        }

        let mut run_record = HeartbeatRunRecord {
            run_id: format!("run-{}", unique_token()),
            heartbeat_id: record.heartbeat_id.clone(),
            agent_id: record.agent_id.clone(),
            capability_name: record.capability_name.clone(),
            fired_at_unix_ms: now_unix_ms,
            payload_json: record.payload_json.clone(),
            status: "dispatched".to_string(),
            delivery_channel_id: None,
            delivery_recipient: None,
            delivery_id: None,
            delivery_status: None,
        };

        if let Some(target) = record.delivery_target.as_ref() {
            delivery_attempted_count = delivery_attempted_count.saturating_add(1);
            run_record.delivery_channel_id = Some(target.channel_id.clone());
            run_record.delivery_recipient = Some(target.recipient.clone());
            match delivery_text_from_payload(&record.payload_json) {
                Some(text) => {
                    let delivery = enqueue_channel_delivery(
                        root,
                        &ChannelDeliveryRequest {
                            channel_id: target.channel_id.clone(),
                            recipient: target.recipient.clone(),
                            raw_text: text,
                            allow_receipt_hashes: target.allow_receipt_hashes,
                            allow_operator_diagnostics: target.allow_operator_diagnostics,
                        },
                    )?;
                    run_record.delivery_id = Some(delivery.delivery_id.clone());
                    run_record.delivery_status = Some(delivery.status.clone());
                    run_record.status = if delivery.allowed {
                        delivery_queued_count = delivery_queued_count.saturating_add(1);
                        "delivery_queued".to_string()
                    } else {
                        delivery_blocked_count = delivery_blocked_count.saturating_add(1);
                        "delivery_blocked".to_string()
                    };
                }
                None => {
                    delivery_blocked_count = delivery_blocked_count.saturating_add(1);
                    run_record.delivery_status = Some("missing_text".to_string());
                    run_record.status = "delivery_missing_text".to_string();
                }
            }
        }

        persist_run_record(root, &run_record)?;
        record.run_count = record.run_count.saturating_add(1);
        record.last_fire_at_unix_ms = Some(now_unix_ms);
        match record.schedule_kind.as_str() {
            "once" => {
                record.enabled = false;
                record.status = "completed".to_string();
                record.next_fire_at_unix_ms = None;
            }
            "interval" => {
                record.status = "scheduled".to_string();
                record.next_fire_at_unix_ms = Some(now_unix_ms + (record.every_seconds * 1_000));
            }
            "cron" => {
                record.status = "scheduled".to_string();
                record.next_fire_at_unix_ms = None;
            }
            _ => {}
        }
        run_records.push(run_record);
    }

    persist_heartbeat_registry(root, &records)?;
    Ok(HeartbeatRunSummary {
        registry_path: heartbeat_registry_path(root),
        runs_path: heartbeat_runs_path(root),
        dispatched_count: run_records.len(),
        delivery_attempted_count,
        delivery_queued_count,
        delivery_blocked_count,
        run_records,
    })
}

pub fn claim_due_heartbeats(
    root: &Path,
    now_unix_ms: u64,
    limit: usize,
) -> LoomResult<Vec<HeartbeatRecord>> {
    let mut records = load_heartbeats(root)?;
    let effective_limit = if limit == 0 { usize::MAX } else { limit };
    let mut claimed = Vec::new();

    for record in records.iter_mut() {
        if claimed.len() >= effective_limit {
            break;
        }
        if !heartbeat_is_due(record, now_unix_ms) {
            continue;
        }

        let snapshot = record.clone();
        record.run_count = record.run_count.saturating_add(1);
        record.last_fire_at_unix_ms = Some(now_unix_ms);
        match record.schedule_kind.as_str() {
            "once" => {
                record.enabled = false;
                record.status = "completed".to_string();
                record.next_fire_at_unix_ms = None;
            }
            "interval" => {
                record.status = "scheduled".to_string();
                record.next_fire_at_unix_ms = Some(now_unix_ms + (record.every_seconds * 1_000));
            }
            "cron" => {
                record.status = "scheduled".to_string();
                record.next_fire_at_unix_ms = None;
            }
            _ => {}
        }
        claimed.push(snapshot);
    }

    if !claimed.is_empty() {
        persist_heartbeat_registry(root, &records)?;
    }
    Ok(claimed)
}

pub fn render_heartbeat_overview_human(summary: &HeartbeatRuntimeOverview) -> String {
    format!(
        "registry_path:   {}\nruns_path:       {}\ntotal_count:     {}\nenabled_count:   {}\ndue_count:       {}\n",
        summary.registry_path.display(),
        summary.runs_path.display(),
        summary.total_count,
        summary.enabled_count,
        summary.due_count,
    )
}

pub fn render_heartbeat_overview_json(summary: &HeartbeatRuntimeOverview) -> String {
    serde_json::to_string_pretty(&json!({
        "registry_path": summary.registry_path.display().to_string(),
        "runs_path": summary.runs_path.display().to_string(),
        "total_count": summary.total_count,
        "enabled_count": summary.enabled_count,
        "due_count": summary.due_count,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_heartbeat_record_human(record: &HeartbeatRecord) -> String {
    let delivery = record.delivery_target.as_ref().map(|target| {
        format!(
            "{} -> {} receipts={} diagnostics={}",
            target.channel_id,
            target.recipient,
            target.allow_receipt_hashes,
            target.allow_operator_diagnostics
        )
    });
    format!(
        "heartbeat_id:      {}\nagent_id:          {}\ncapability_name:   {}\nschedule_kind:     {}\nschedule_expr:     {}\ntimezone:          {}\nevery_seconds:     {}\njitter_seconds:    {}\nnot_before:        {}\ndelivery:          {}\nenabled:           {}\nstatus:            {}\nmax_attempts:      {}\nrun_count:         {}\nlast_fire_at:      {}\nnext_fire_at:      {}\n",
        record.heartbeat_id,
        record.agent_id,
        record.capability_name,
        record.schedule_kind,
        if record.schedule_expression.is_empty() { "(none)" } else { &record.schedule_expression },
        record.timezone,
        record.every_seconds,
        record.jitter_seconds,
        record.not_before_unix_ms.map(|value| value.to_string()).unwrap_or_else(|| "(none)".to_string()),
        delivery.unwrap_or_else(|| "(none)".to_string()),
        record.enabled,
        record.status,
        record.max_attempts,
        record.run_count,
        record.last_fire_at_unix_ms.map(|value| value.to_string()).unwrap_or_else(|| "(none)".to_string()),
        record.next_fire_at_unix_ms.map(|value| value.to_string()).unwrap_or_else(|| "(none)".to_string()),
    )
}

pub fn render_heartbeat_record_json(record: &HeartbeatRecord) -> String {
    serde_json::to_string_pretty(&heartbeat_record_json(record))
        .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_heartbeat_run_summary_human(summary: &HeartbeatRunSummary) -> String {
    let mut rendered = format!(
        "registry_path:       {}\nruns_path:           {}\ndispatched:          {}\ndelivery_attempted:  {}\ndelivery_queued:     {}\ndelivery_blocked:    {}\n",
        summary.registry_path.display(),
        summary.runs_path.display(),
        summary.dispatched_count,
        summary.delivery_attempted_count,
        summary.delivery_queued_count,
        summary.delivery_blocked_count,
    );
    for run in &summary.run_records {
        rendered.push_str(&format!(
            "\n- {} agent={} capability={} fired_at={} status={} delivery={} recipient={} delivery_status={}\n",
            run.heartbeat_id,
            run.agent_id,
            run.capability_name,
            run.fired_at_unix_ms,
            run.status,
            run.delivery_channel_id.as_deref().unwrap_or("(none)"),
            run.delivery_recipient.as_deref().unwrap_or("(none)"),
            run.delivery_status.as_deref().unwrap_or("(none)"),
        ));
    }
    rendered
}

pub fn render_heartbeat_run_summary_json(summary: &HeartbeatRunSummary) -> String {
    serde_json::to_string_pretty(&json!({
        "registry_path": summary.registry_path.display().to_string(),
        "runs_path": summary.runs_path.display().to_string(),
        "dispatched_count": summary.dispatched_count,
        "delivery_attempted_count": summary.delivery_attempted_count,
        "delivery_queued_count": summary.delivery_queued_count,
        "delivery_blocked_count": summary.delivery_blocked_count,
        "run_records": summary.run_records.iter().map(heartbeat_run_json).collect::<Vec<_>>(),
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

fn mutate_heartbeat<F>(
    root: &Path,
    heartbeat_id: &str,
    mutator: F,
) -> LoomResult<HeartbeatMutationResult>
where
    F: FnOnce(&mut HeartbeatRecord),
{
    let mut records = load_heartbeats(root)?;
    let heartbeat_id = heartbeat_id.trim();
    if heartbeat_id.is_empty() {
        return Err("heartbeat_id is required".to_string());
    }
    let Some(record) = records
        .iter_mut()
        .find(|record| record.heartbeat_id == heartbeat_id)
    else {
        return Err(format!("heartbeat '{}' was not found", heartbeat_id));
    };
    mutator(record);
    let result = record.clone();
    persist_heartbeat_registry(root, &records)?;
    Ok(HeartbeatMutationResult {
        registry_path: heartbeat_registry_path(root),
        record: result,
    })
}

fn parse_heartbeat_registry(raw: &str) -> LoomResult<Vec<HeartbeatRecord>> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid heartbeat registry json: {error}"))?;
    let heartbeats = value
        .get("heartbeats")
        .and_then(Value::as_array)
        .ok_or_else(|| "heartbeat registry must define a heartbeats array".to_string())?;
    let mut records = Vec::with_capacity(heartbeats.len());
    for heartbeat in heartbeats {
        records.push(parse_heartbeat_record(heartbeat)?);
    }
    Ok(records)
}

fn parse_heartbeat_record(value: &Value) -> LoomResult<HeartbeatRecord> {
    Ok(HeartbeatRecord {
        heartbeat_id: value_string(value.get("heartbeat_id"), "heartbeat_id")?,
        agent_id: value_string(value.get("agent_id"), "agent_id")?,
        capability_name: value_string(value.get("capability_name"), "capability_name")?,
        schedule_kind: value_string(value.get("schedule_kind"), "schedule_kind")?,
        schedule_expression: value_string_or(value.get("schedule_expression"), ""),
        timezone: value_string_or(value.get("timezone"), "UTC"),
        every_seconds: value_u64(value.get("every_seconds")).unwrap_or(0),
        jitter_seconds: value_u64(value.get("jitter_seconds")).unwrap_or(0),
        not_before_unix_ms: value_u64(value.get("not_before_unix_ms")),
        payload_json: value_string_or(value.get("payload_json"), "{}"),
        delivery_target: value
            .get("delivery_target")
            .and_then(|entry| if entry.is_null() { None } else { Some(entry) })
            .map(parse_delivery_target)
            .transpose()?,
        enabled: value
            .get("enabled")
            .and_then(Value::as_bool)
            .unwrap_or(true),
        status: value_string_or(value.get("status"), "scheduled"),
        max_attempts: value_u64(value.get("max_attempts")).unwrap_or(1) as u32,
        run_count: value_u64(value.get("run_count")).unwrap_or(0) as u32,
        last_fire_at_unix_ms: value_u64(value.get("last_fire_at_unix_ms")),
        next_fire_at_unix_ms: value_u64(value.get("next_fire_at_unix_ms")),
    })
}

fn parse_delivery_target(value: &Value) -> LoomResult<HeartbeatDeliveryTarget> {
    Ok(HeartbeatDeliveryTarget {
        channel_id: value_string(value.get("channel_id"), "delivery_target.channel_id")?,
        recipient: value_string(value.get("recipient"), "delivery_target.recipient")?,
        allow_receipt_hashes: value
            .get("allow_receipt_hashes")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        allow_operator_diagnostics: value
            .get("allow_operator_diagnostics")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    })
}

fn persist_heartbeat_registry(root: &Path, records: &[HeartbeatRecord]) -> LoomResult<()> {
    let registry_path = heartbeat_registry_path(root);
    if let Some(parent) = registry_path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    let value = json!({
        "heartbeats": records.iter().map(heartbeat_record_json).collect::<Vec<_>>(),
    });
    let mut rendered = serde_json::to_string_pretty(&value).map_err(|error| error.to_string())?;
    rendered.push('\n');
    fs::write(&registry_path, rendered).map_err(io_err)
}

fn persist_run_record(root: &Path, run_record: &HeartbeatRunRecord) -> LoomResult<()> {
    let path =
        heartbeat_runs_path(root).join(format!("{}.json", safe_file_token(&run_record.run_id)));
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    let mut rendered = serde_json::to_string_pretty(&heartbeat_run_json(run_record))
        .map_err(|error| error.to_string())?;
    rendered.push('\n');
    fs::write(path, rendered).map_err(io_err)
}

fn heartbeat_record_json(record: &HeartbeatRecord) -> Value {
    json!({
        "heartbeat_id": record.heartbeat_id,
        "agent_id": record.agent_id,
        "capability_name": record.capability_name,
        "schedule_kind": record.schedule_kind,
        "schedule_expression": record.schedule_expression,
        "timezone": record.timezone,
        "every_seconds": record.every_seconds,
        "jitter_seconds": record.jitter_seconds,
        "not_before_unix_ms": record.not_before_unix_ms,
        "payload_json": record.payload_json,
        "delivery_target": record.delivery_target.as_ref().map(delivery_target_json),
        "enabled": record.enabled,
        "status": record.status,
        "max_attempts": record.max_attempts,
        "run_count": record.run_count,
        "last_fire_at_unix_ms": record.last_fire_at_unix_ms,
        "next_fire_at_unix_ms": record.next_fire_at_unix_ms,
    })
}

fn delivery_target_json(target: &HeartbeatDeliveryTarget) -> Value {
    json!({
        "channel_id": target.channel_id,
        "recipient": target.recipient,
        "allow_receipt_hashes": target.allow_receipt_hashes,
        "allow_operator_diagnostics": target.allow_operator_diagnostics,
    })
}

fn heartbeat_run_json(run: &HeartbeatRunRecord) -> Value {
    json!({
        "run_id": run.run_id,
        "heartbeat_id": run.heartbeat_id,
        "agent_id": run.agent_id,
        "capability_name": run.capability_name,
        "fired_at_unix_ms": run.fired_at_unix_ms,
        "payload_json": run.payload_json,
        "status": run.status,
        "delivery_channel_id": run.delivery_channel_id,
        "delivery_recipient": run.delivery_recipient,
        "delivery_id": run.delivery_id,
        "delivery_status": run.delivery_status,
    })
}

fn validate_schedule_request(request: &HeartbeatScheduleRequest) -> LoomResult<()> {
    if request.agent_id.trim().is_empty() {
        return Err("agent_id is required".to_string());
    }
    if request.capability_name.trim().is_empty() {
        return Err("capability_name is required".to_string());
    }
    if let Some(target) = request.delivery_target.as_ref() {
        if target.channel_id.trim().is_empty() {
            return Err("delivery_target.channel_id is required".to_string());
        }
        if target.recipient.trim().is_empty() {
            return Err("delivery_target.recipient is required".to_string());
        }
    }
    match request.schedule_kind.trim() {
        "interval" => {
            if request.every_seconds == 0 {
                return Err("interval schedules require --every-seconds > 0".to_string());
            }
        }
        "once" => {
            if request.not_before_unix_ms.is_none() {
                return Err("once schedules require --not-before-unix-ms".to_string());
            }
        }
        "cron" => {
            if request.schedule_expression.trim().is_empty() {
                return Err("cron schedules require --expression".to_string());
            }
        }
        other => return Err(format!("unsupported schedule kind '{}'", other)),
    }
    Ok(())
}

fn initial_next_fire_at(request: &HeartbeatScheduleRequest, now_unix_ms: u64) -> Option<u64> {
    match request.schedule_kind.trim() {
        "interval" => Some(now_unix_ms + (request.every_seconds * 1_000)),
        "once" => request.not_before_unix_ms,
        "cron" => None,
        _ => None,
    }
}

fn heartbeat_is_due(record: &HeartbeatRecord, now_unix_ms: u64) -> bool {
    if !record.enabled {
        return false;
    }
    match record.schedule_kind.as_str() {
        "cron" => false,
        _ => record
            .next_fire_at_unix_ms
            .map(|value| value <= now_unix_ms)
            .unwrap_or(false),
    }
}

fn delivery_text_from_payload(payload_json: &str) -> Option<String> {
    let trimmed = payload_json.trim();
    if trimmed.is_empty() || trimmed == "{}" {
        return None;
    }
    match serde_json::from_str::<Value>(trimmed) {
        Ok(Value::String(value)) => {
            let value = value.trim().to_string();
            if value.is_empty() {
                None
            } else {
                Some(value)
            }
        }
        Ok(Value::Object(map)) => {
            for key in ["message", "text", "content", "final_answer"] {
                if let Some(value) = map.get(key).and_then(Value::as_str) {
                    let value = value.trim().to_string();
                    if !value.is_empty() {
                        return Some(value);
                    }
                }
            }
            None
        }
        Ok(_) => None,
        Err(_) => Some(trimmed.to_string()),
    }
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
        .filter(|raw| !raw.is_empty())
        .unwrap_or_else(|| fallback.to_string())
}

fn value_u64(value: Option<&Value>) -> Option<u64> {
    value.and_then(Value::as_u64)
}

fn normalized_or(value: Option<&str>, fallback: &str) -> String {
    value
        .map(|raw| raw.trim())
        .filter(|raw| !raw.is_empty())
        .unwrap_or(fallback)
        .to_string()
}

fn now_unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

fn unique_token() -> String {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos()
        .to_string()
}

fn safe_file_token(input: &str) -> String {
    input
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() {
                ch.to_ascii_lowercase()
            } else {
                '-'
            }
        })
        .collect::<String>()
        .trim_matches('-')
        .to_string()
}

fn io_err(error: std::io::Error) -> String {
    error.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::channels::list_channel_deliveries;
    use crate::{
        init_workspace,
        onboarding::{load_onboard_manifest, write_onboard_manifest},
    };

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
    fn scaffold_writes_empty_heartbeat_registry() {
        let root = temp_path("loom-heartbeat-scaffold");
        let registry_path = ensure_heartbeat_runtime_scaffold(&root).expect("heartbeat scaffold");
        assert!(registry_path.exists());
        assert!(heartbeat_runs_path(&root).exists());
        let overview = heartbeat_overview(&root, 0).expect("heartbeat overview");
        assert_eq!(overview.total_count, 0);
        assert_eq!(overview.enabled_count, 0);
    }

    #[test]
    fn schedule_interval_heartbeat_persists_record() {
        let root = temp_path("loom-heartbeat-schedule");
        ensure_heartbeat_runtime_scaffold(&root).expect("heartbeat scaffold");
        let result = schedule_heartbeat(
            &root,
            &HeartbeatScheduleRequest {
                heartbeat_id: Some("beat-atlas".to_string()),
                agent_id: "atlas".to_string(),
                capability_name: "loom.system.info.v1".to_string(),
                schedule_kind: "interval".to_string(),
                schedule_expression: String::new(),
                timezone: "UTC".to_string(),
                every_seconds: 60,
                jitter_seconds: 5,
                not_before_unix_ms: None,
                payload_json: "{}".to_string(),
                delivery_target: Some(HeartbeatDeliveryTarget {
                    channel_id: "web_api".to_string(),
                    recipient: "founder".to_string(),
                    allow_receipt_hashes: false,
                    allow_operator_diagnostics: false,
                }),
                max_attempts: 2,
            },
        )
        .expect("schedule heartbeat");
        assert_eq!(result.record.heartbeat_id, "beat-atlas");
        assert_eq!(result.record.status, "scheduled");
        assert!(result.record.next_fire_at_unix_ms.is_some());
        assert!(result.record.delivery_target.is_some());
    }

    #[test]
    fn run_due_heartbeats_creates_run_record_and_advances_interval() {
        let root = temp_path("loom-heartbeat-run");
        ensure_heartbeat_runtime_scaffold(&root).expect("heartbeat scaffold");
        schedule_heartbeat(
            &root,
            &HeartbeatScheduleRequest {
                heartbeat_id: Some("beat-pulse".to_string()),
                agent_id: "pulse".to_string(),
                capability_name: "loom.system.info.v1".to_string(),
                schedule_kind: "interval".to_string(),
                schedule_expression: String::new(),
                timezone: "UTC".to_string(),
                every_seconds: 30,
                jitter_seconds: 0,
                not_before_unix_ms: None,
                payload_json: "{}".to_string(),
                delivery_target: None,
                max_attempts: 1,
            },
        )
        .expect("schedule heartbeat");
        let before = heartbeat_summary(&root, "beat-pulse").expect("summary before");
        let now = before.next_fire_at_unix_ms.expect("next fire");
        let summary = run_due_heartbeats(&root, now, 1).expect("run due heartbeats");
        assert_eq!(summary.dispatched_count, 1);
        assert_eq!(summary.run_records[0].heartbeat_id, "beat-pulse");
        let after = heartbeat_summary(&root, "beat-pulse").expect("summary after");
        assert_eq!(after.run_count, 1);
        assert!(after.next_fire_at_unix_ms.expect("advanced next fire") > now);
    }

    #[test]
    fn run_due_heartbeats_queues_guarded_delivery() {
        let root = temp_path("loom-heartbeat-delivery");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        let mut manifest = load_onboard_manifest(&root).expect("load onboard manifest");
        manifest.telegram_enabled = true;
        write_onboard_manifest(&root, &manifest).expect("write onboard manifest");
        crate::channels::sync_channel_registry(&root).expect("sync channel registry");

        schedule_heartbeat(
            &root,
            &HeartbeatScheduleRequest {
                heartbeat_id: Some("beat-leviathann".to_string()),
                agent_id: "leviathann".to_string(),
                capability_name: "loom.llm.inference.v1".to_string(),
                schedule_kind: "once".to_string(),
                schedule_expression: String::new(),
                timezone: "UTC".to_string(),
                every_seconds: 0,
                jitter_seconds: 0,
                not_before_unix_ms: Some(10),
                payload_json: json!({
                    "message": "[✅ FINAL ANSWER]\nMeridian proactive brief ready\n[🛡️ PoGE PROTOCOL] Cryptographic Audit Root Settled: 0xabc123"
                })
                .to_string(),
                delivery_target: Some(HeartbeatDeliveryTarget {
                    channel_id: "telegram".to_string(),
                    recipient: "founder".to_string(),
                    allow_receipt_hashes: true,
                    allow_operator_diagnostics: false,
                }),
                max_attempts: 1,
            },
        )
        .expect("schedule heartbeat");

        let summary = run_due_heartbeats(&root, 10, 1).expect("run due heartbeats");
        assert_eq!(summary.dispatched_count, 1);
        assert_eq!(summary.delivery_attempted_count, 1);
        assert_eq!(summary.delivery_queued_count, 1);
        assert_eq!(summary.delivery_blocked_count, 0);
        assert_eq!(summary.run_records[0].status, "delivery_queued");
        assert_eq!(
            summary.run_records[0].delivery_channel_id.as_deref(),
            Some("telegram")
        );
        let deliveries = list_channel_deliveries(&root, 10).expect("list deliveries");
        assert_eq!(deliveries.len(), 1);
        assert!(deliveries[0]
            .display_text
            .contains("Meridian proactive brief ready"));
        assert!(deliveries[0]
            .display_text
            .contains("[PoGE Receipt] 0xabc123"));
    }

    #[test]
    fn run_due_heartbeats_blocks_internal_delivery_payloads() {
        let root = temp_path("loom-heartbeat-delivery-blocked");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        crate::channels::sync_channel_registry(&root).expect("sync channel registry");

        schedule_heartbeat(
            &root,
            &HeartbeatScheduleRequest {
                heartbeat_id: Some("beat-sentinel".to_string()),
                agent_id: "sentinel".to_string(),
                capability_name: "loom.llm.inference.v1".to_string(),
                schedule_kind: "once".to_string(),
                schedule_expression: String::new(),
                timezone: "UTC".to_string(),
                every_seconds: 0,
                jitter_seconds: 0,
                not_before_unix_ms: Some(25),
                payload_json: json!({"message": "SLEEP"}).to_string(),
                delivery_target: Some(HeartbeatDeliveryTarget {
                    channel_id: "web_api".to_string(),
                    recipient: "founder".to_string(),
                    allow_receipt_hashes: false,
                    allow_operator_diagnostics: false,
                }),
                max_attempts: 1,
            },
        )
        .expect("schedule heartbeat");

        let summary = run_due_heartbeats(&root, 25, 1).expect("run due heartbeats");
        assert_eq!(summary.delivery_attempted_count, 1);
        assert_eq!(summary.delivery_queued_count, 0);
        assert_eq!(summary.delivery_blocked_count, 1);
        assert_eq!(summary.run_records[0].status, "delivery_blocked");
        let deliveries = list_channel_deliveries(&root, 10).expect("list deliveries");
        assert_eq!(deliveries.len(), 1);
        assert!(!deliveries[0].allowed);
    }

    #[test]
    fn pause_and_cancel_update_status() {
        let root = temp_path("loom-heartbeat-mutate");
        ensure_heartbeat_runtime_scaffold(&root).expect("heartbeat scaffold");
        schedule_heartbeat(
            &root,
            &HeartbeatScheduleRequest {
                heartbeat_id: Some("beat-forge".to_string()),
                agent_id: "forge".to_string(),
                capability_name: "loom.fs.read.v1".to_string(),
                schedule_kind: "once".to_string(),
                schedule_expression: String::new(),
                timezone: "UTC".to_string(),
                every_seconds: 0,
                jitter_seconds: 0,
                not_before_unix_ms: Some(123),
                payload_json: "{}".to_string(),
                delivery_target: None,
                max_attempts: 1,
            },
        )
        .expect("schedule heartbeat");
        let paused = pause_heartbeat(&root, "beat-forge").expect("pause heartbeat");
        assert_eq!(paused.record.status, "paused");
        assert!(!paused.record.enabled);
        let cancelled = cancel_heartbeat(&root, "beat-forge").expect("cancel heartbeat");
        assert_eq!(cancelled.record.status, "cancelled");
        assert!(cancelled.record.next_fire_at_unix_ms.is_none());
    }
}
