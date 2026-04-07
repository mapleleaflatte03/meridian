use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

use crate::channels::{enqueue_channel_delivery, ChannelDeliveryRequest};
use crate::io_err;
use crate::onboarding::load_onboard_manifest;

pub type LoomResult<T> = Result<T, String>;

pub const DEFAULT_SCHEDULE_REGISTRY_PATH: &str = "state/schedules/registry.json";
pub const DEFAULT_SCHEDULE_RUNS_DIR: &str = "state/schedules/runs";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ScheduleDeliveryTarget {
    pub channel_id: String,
    pub recipient: String,
    pub allow_receipt_hashes: bool,
    pub allow_operator_diagnostics: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ScheduledJobRecord {
    pub job_id: String,
    pub agent_id: String,
    pub job_kind: String,
    pub schedule_kind: String,
    pub schedule_expression: String,
    pub timezone: String,
    pub every_seconds: u64,
    pub not_before_unix_ms: Option<u64>,
    pub payload_json: String,
    pub delivery_target: Option<ScheduleDeliveryTarget>,
    pub source_kind: String,
    pub enabled: bool,
    pub status: String,
    pub max_attempts: u32,
    pub run_count: u32,
    pub last_fire_at_unix_ms: Option<u64>,
    pub next_fire_at_unix_ms: Option<u64>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ScheduleRequest {
    pub job_id: Option<String>,
    pub agent_id: String,
    pub job_kind: String,
    pub schedule_kind: String,
    pub schedule_expression: String,
    pub timezone: String,
    pub every_seconds: u64,
    pub not_before_unix_ms: Option<u64>,
    pub payload_json: String,
    pub delivery_target: Option<ScheduleDeliveryTarget>,
    pub max_attempts: u32,
    pub source_kind: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ScheduleRuntimeOverview {
    pub registry_path: PathBuf,
    pub runs_path: PathBuf,
    pub total_count: usize,
    pub enabled_count: usize,
    pub due_count: usize,
    pub job_ids: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ScheduleSyncResult {
    pub registry_path: PathBuf,
    pub total_count: usize,
    pub enabled_count: usize,
    pub job_ids: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ScheduleMutationResult {
    pub registry_path: PathBuf,
    pub record: ScheduledJobRecord,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ScheduledJobRunRecord {
    pub run_id: String,
    pub job_id: String,
    pub agent_id: String,
    pub job_kind: String,
    pub fired_at_unix_ms: u64,
    pub payload_json: String,
    pub status: String,
    pub delivery_channel_id: Option<String>,
    pub delivery_recipient: Option<String>,
    pub delivery_id: Option<String>,
    pub delivery_status: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ScheduleRunSummary {
    pub registry_path: PathBuf,
    pub runs_path: PathBuf,
    pub dispatched_count: usize,
    pub delivery_attempted_count: usize,
    pub delivery_queued_count: usize,
    pub delivery_blocked_count: usize,
    pub run_records: Vec<ScheduledJobRunRecord>,
}

pub fn schedule_registry_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_SCHEDULE_REGISTRY_PATH)
}

pub fn schedule_runs_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_SCHEDULE_RUNS_DIR)
}

pub fn ensure_schedule_runtime_scaffold(root: &Path) -> LoomResult<PathBuf> {
    let registry_path = schedule_registry_path(root);
    if let Some(parent) = registry_path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    fs::create_dir_all(schedule_runs_path(root)).map_err(io_err)?;
    if !registry_path.exists() {
        fs::write(&registry_path, "{\n  \"schedules\": []\n}\n").map_err(io_err)?;
    }
    Ok(registry_path)
}

pub fn sync_schedule_registry(root: &Path) -> LoomResult<ScheduleSyncResult> {
    ensure_schedule_runtime_scaffold(root)?;
    let manifest = load_onboard_manifest(root)?;
    let mut records = if manifest.recurring_install_defaults {
        manifest
            .recurring_entries
            .iter()
            .filter_map(|entry| default_schedule_record(entry))
            .collect::<Vec<_>>()
    } else {
        Vec::new()
    };
    records.sort_by(|left, right| left.job_id.cmp(&right.job_id));
    records.dedup_by(|left, right| left.job_id == right.job_id);
    for record in records.iter_mut() {
        if record.next_fire_at_unix_ms.is_none() {
            record.next_fire_at_unix_ms = initial_next_fire_at(record, now_unix_ms());
        }
    }
    persist_schedule_registry(root, &records)?;
    Ok(ScheduleSyncResult {
        registry_path: schedule_registry_path(root),
        total_count: records.len(),
        enabled_count: records.iter().filter(|record| record.enabled).count(),
        job_ids: records.iter().map(|record| record.job_id.clone()).collect(),
    })
}

pub fn load_schedules(root: &Path) -> LoomResult<Vec<ScheduledJobRecord>> {
    ensure_schedule_runtime_scaffold(root)?;
    let raw = fs::read_to_string(schedule_registry_path(root)).map_err(io_err)?;
    parse_schedule_registry(&raw)
}

pub fn schedule_overview(root: &Path, now_unix_ms: u64) -> LoomResult<ScheduleRuntimeOverview> {
    let records = load_schedules(root)?;
    Ok(ScheduleRuntimeOverview {
        registry_path: schedule_registry_path(root),
        runs_path: schedule_runs_path(root),
        total_count: records.len(),
        enabled_count: records.iter().filter(|record| record.enabled).count(),
        due_count: records
            .iter()
            .filter(|record| schedule_is_due(record, now_unix_ms))
            .count(),
        job_ids: records.iter().map(|record| record.job_id.clone()).collect(),
    })
}

pub fn schedule_summary(root: &Path, job_id: &str) -> LoomResult<ScheduledJobRecord> {
    let job_id = job_id.trim();
    if job_id.is_empty() {
        return Err("job_id is required".to_string());
    }
    load_schedules(root)?
        .into_iter()
        .find(|record| record.job_id == job_id)
        .ok_or_else(|| format!("schedule '{}' was not found", job_id))
}

pub fn add_schedule(root: &Path, request: &ScheduleRequest) -> LoomResult<ScheduleMutationResult> {
    validate_schedule_request(request)?;
    let mut records = load_schedules(root)?;
    let job_id = request
        .job_id
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .unwrap_or_else(|| format!("job-{}", unique_token()));
    if records.iter().any(|record| record.job_id == job_id) {
        return Err(format!("schedule '{}' already exists", job_id));
    }
    let record = ScheduledJobRecord {
        job_id,
        agent_id: request.agent_id.trim().to_string(),
        job_kind: request.job_kind.trim().to_string(),
        schedule_kind: request.schedule_kind.trim().to_string(),
        schedule_expression: normalized_or(Some(&request.schedule_expression), ""),
        timezone: normalized_or(Some(&request.timezone), "UTC"),
        every_seconds: request.every_seconds,
        not_before_unix_ms: request.not_before_unix_ms,
        payload_json: normalized_or(Some(&request.payload_json), "{}"),
        delivery_target: request.delivery_target.clone(),
        source_kind: normalized_or(Some(&request.source_kind), "manual"),
        enabled: true,
        status: "scheduled".to_string(),
        max_attempts: request.max_attempts.max(1),
        run_count: 0,
        last_fire_at_unix_ms: None,
        next_fire_at_unix_ms: initial_next_fire_at_request(request, now_unix_ms()),
    };
    records.push(record.clone());
    persist_schedule_registry(root, &records)?;
    Ok(ScheduleMutationResult {
        registry_path: schedule_registry_path(root),
        record,
    })
}

pub fn pause_schedule(root: &Path, job_id: &str) -> LoomResult<ScheduleMutationResult> {
    mutate_schedule(root, job_id, |record| {
        record.enabled = false;
        record.status = "paused".to_string();
    })
}

pub fn cancel_schedule(root: &Path, job_id: &str) -> LoomResult<ScheduleMutationResult> {
    mutate_schedule(root, job_id, |record| {
        record.enabled = false;
        record.status = "cancelled".to_string();
        record.next_fire_at_unix_ms = None;
    })
}

pub fn run_due_schedules(
    root: &Path,
    now_unix_ms: u64,
    limit: usize,
) -> LoomResult<ScheduleRunSummary> {
    let mut records = load_schedules(root)?;
    let effective_limit = if limit == 0 { usize::MAX } else { limit };
    let mut run_records = Vec::new();
    let mut delivery_attempted_count = 0usize;
    let mut delivery_queued_count = 0usize;
    let mut delivery_blocked_count = 0usize;

    for record in records.iter_mut() {
        if run_records.len() >= effective_limit {
            break;
        }
        if !schedule_is_due(record, now_unix_ms) {
            continue;
        }
        let mut run_record = ScheduledJobRunRecord {
            run_id: format!("run-{}", unique_token()),
            job_id: record.job_id.clone(),
            agent_id: record.agent_id.clone(),
            job_kind: record.job_kind.clone(),
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
            "daily" => {
                record.status = "scheduled".to_string();
                record.next_fire_at_unix_ms =
                    next_daily_fire_at(&record.schedule_expression, now_unix_ms);
            }
            _ => {}
        }
        run_records.push(run_record);
    }

    persist_schedule_registry(root, &records)?;
    Ok(ScheduleRunSummary {
        registry_path: schedule_registry_path(root),
        runs_path: schedule_runs_path(root),
        dispatched_count: run_records.len(),
        delivery_attempted_count,
        delivery_queued_count,
        delivery_blocked_count,
        run_records,
    })
}

pub fn render_schedule_overview_human(summary: &ScheduleRuntimeOverview) -> String {
    format!(
        "registry_path:   {}\nruns_path:       {}\ntotal_count:     {}\nenabled_count:   {}\ndue_count:       {}\njob_ids:         {}\n",
        summary.registry_path.display(),
        summary.runs_path.display(),
        summary.total_count,
        summary.enabled_count,
        summary.due_count,
        if summary.job_ids.is_empty() { "(none)".to_string() } else { summary.job_ids.join(",") },
    )
}

pub fn render_schedule_overview_json(summary: &ScheduleRuntimeOverview) -> String {
    serde_json::to_string_pretty(&json!({
        "registry_path": summary.registry_path.display().to_string(),
        "runs_path": summary.runs_path.display().to_string(),
        "total_count": summary.total_count,
        "enabled_count": summary.enabled_count,
        "due_count": summary.due_count,
        "job_ids": summary.job_ids,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_schedule_record_human(record: &ScheduledJobRecord) -> String {
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
        "job_id:            {}\nagent_id:          {}\njob_kind:          {}\nschedule_kind:     {}\nschedule_expr:     {}\ntimezone:          {}\nevery_seconds:     {}\nnot_before:        {}\ndelivery:          {}\nsource_kind:       {}\nenabled:           {}\nstatus:            {}\nmax_attempts:      {}\nrun_count:         {}\nlast_fire_at:      {}\nnext_fire_at:      {}\n",
        record.job_id,
        record.agent_id,
        record.job_kind,
        record.schedule_kind,
        if record.schedule_expression.is_empty() { "(none)" } else { &record.schedule_expression },
        record.timezone,
        record.every_seconds,
        record.not_before_unix_ms.map(|value| value.to_string()).unwrap_or_else(|| "(none)".to_string()),
        delivery.unwrap_or_else(|| "(none)".to_string()),
        record.source_kind,
        record.enabled,
        record.status,
        record.max_attempts,
        record.run_count,
        record.last_fire_at_unix_ms.map(|value| value.to_string()).unwrap_or_else(|| "(none)".to_string()),
        record.next_fire_at_unix_ms.map(|value| value.to_string()).unwrap_or_else(|| "(none)".to_string()),
    )
}

pub fn render_schedule_record_json(record: &ScheduledJobRecord) -> String {
    serde_json::to_string_pretty(&schedule_record_json(record)).unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_schedule_run_summary_human(summary: &ScheduleRunSummary) -> String {
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
            "\n- {} agent={} job_kind={} fired_at={} status={} delivery={} recipient={} delivery_status={}\n",
            run.job_id,
            run.agent_id,
            run.job_kind,
            run.fired_at_unix_ms,
            run.status,
            run.delivery_channel_id.as_deref().unwrap_or("(none)"),
            run.delivery_recipient.as_deref().unwrap_or("(none)"),
            run.delivery_status.as_deref().unwrap_or("(none)"),
        ));
    }
    rendered
}

pub fn render_schedule_run_summary_json(summary: &ScheduleRunSummary) -> String {
    serde_json::to_string_pretty(&json!({
        "registry_path": summary.registry_path.display().to_string(),
        "runs_path": summary.runs_path.display().to_string(),
        "dispatched_count": summary.dispatched_count,
        "delivery_attempted_count": summary.delivery_attempted_count,
        "delivery_queued_count": summary.delivery_queued_count,
        "delivery_blocked_count": summary.delivery_blocked_count,
        "run_records": summary.run_records.iter().map(schedule_run_json).collect::<Vec<_>>(),
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

fn mutate_schedule<F>(root: &Path, job_id: &str, mutator: F) -> LoomResult<ScheduleMutationResult>
where
    F: FnOnce(&mut ScheduledJobRecord),
{
    let mut records = load_schedules(root)?;
    let job_id = job_id.trim();
    if job_id.is_empty() {
        return Err("job_id is required".to_string());
    }
    let Some(record) = records.iter_mut().find(|record| record.job_id == job_id) else {
        return Err(format!("schedule '{}' was not found", job_id));
    };
    mutator(record);
    let result = record.clone();
    persist_schedule_registry(root, &records)?;
    Ok(ScheduleMutationResult {
        registry_path: schedule_registry_path(root),
        record: result,
    })
}

fn parse_schedule_registry(raw: &str) -> LoomResult<Vec<ScheduledJobRecord>> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid schedule registry json: {error}"))?;
    let schedules = value
        .get("schedules")
        .and_then(Value::as_array)
        .ok_or_else(|| "schedule registry must define a schedules array".to_string())?;
    let mut records = Vec::with_capacity(schedules.len());
    for schedule in schedules {
        records.push(parse_schedule_record(schedule)?);
    }
    Ok(records)
}

fn parse_schedule_record(value: &Value) -> LoomResult<ScheduledJobRecord> {
    Ok(ScheduledJobRecord {
        job_id: value_string(value.get("job_id"), "job_id")?,
        agent_id: value_string(value.get("agent_id"), "agent_id")?,
        job_kind: value_string(value.get("job_kind"), "job_kind")?,
        schedule_kind: value_string(value.get("schedule_kind"), "schedule_kind")?,
        schedule_expression: value_string_or(value.get("schedule_expression"), ""),
        timezone: value_string_or(value.get("timezone"), "UTC"),
        every_seconds: value_u64(value.get("every_seconds")).unwrap_or(0),
        not_before_unix_ms: value_u64(value.get("not_before_unix_ms")),
        payload_json: value_string_or(value.get("payload_json"), "{}"),
        delivery_target: value
            .get("delivery_target")
            .and_then(|entry| if entry.is_null() { None } else { Some(entry) })
            .map(parse_delivery_target)
            .transpose()?,
        source_kind: value_string_or(value.get("source_kind"), "manual"),
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

fn parse_delivery_target(value: &Value) -> LoomResult<ScheduleDeliveryTarget> {
    Ok(ScheduleDeliveryTarget {
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

fn persist_schedule_registry(root: &Path, records: &[ScheduledJobRecord]) -> LoomResult<()> {
    let registry_path = schedule_registry_path(root);
    if let Some(parent) = registry_path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    let value = json!({
        "schedules": records.iter().map(schedule_record_json).collect::<Vec<_>>(),
    });
    let mut rendered = serde_json::to_string_pretty(&value).map_err(|error| error.to_string())?;
    rendered.push('\n');
    fs::write(&registry_path, rendered).map_err(io_err)
}

fn persist_run_record(root: &Path, run_record: &ScheduledJobRunRecord) -> LoomResult<()> {
    let path =
        schedule_runs_path(root).join(format!("{}.json", safe_file_token(&run_record.run_id)));
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    let mut rendered = serde_json::to_string_pretty(&schedule_run_json(run_record))
        .map_err(|error| error.to_string())?;
    rendered.push('\n');
    fs::write(path, rendered).map_err(io_err)
}

fn schedule_record_json(record: &ScheduledJobRecord) -> Value {
    json!({
        "job_id": record.job_id,
        "agent_id": record.agent_id,
        "job_kind": record.job_kind,
        "schedule_kind": record.schedule_kind,
        "schedule_expression": record.schedule_expression,
        "timezone": record.timezone,
        "every_seconds": record.every_seconds,
        "not_before_unix_ms": record.not_before_unix_ms,
        "payload_json": record.payload_json,
        "delivery_target": record.delivery_target.as_ref().map(delivery_target_json),
        "source_kind": record.source_kind,
        "enabled": record.enabled,
        "status": record.status,
        "max_attempts": record.max_attempts,
        "run_count": record.run_count,
        "last_fire_at_unix_ms": record.last_fire_at_unix_ms,
        "next_fire_at_unix_ms": record.next_fire_at_unix_ms,
    })
}

fn delivery_target_json(target: &ScheduleDeliveryTarget) -> Value {
    json!({
        "channel_id": target.channel_id,
        "recipient": target.recipient,
        "allow_receipt_hashes": target.allow_receipt_hashes,
        "allow_operator_diagnostics": target.allow_operator_diagnostics,
    })
}

fn schedule_run_json(run: &ScheduledJobRunRecord) -> Value {
    json!({
        "run_id": run.run_id,
        "job_id": run.job_id,
        "agent_id": run.agent_id,
        "job_kind": run.job_kind,
        "fired_at_unix_ms": run.fired_at_unix_ms,
        "payload_json": run.payload_json,
        "status": run.status,
        "delivery_channel_id": run.delivery_channel_id,
        "delivery_recipient": run.delivery_recipient,
        "delivery_id": run.delivery_id,
        "delivery_status": run.delivery_status,
    })
}

fn validate_schedule_request(request: &ScheduleRequest) -> LoomResult<()> {
    if request.agent_id.trim().is_empty() {
        return Err("agent_id is required".to_string());
    }
    if request.job_kind.trim().is_empty() {
        return Err("job_kind is required".to_string());
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
        "daily" => {
            parse_daily_expression(&request.schedule_expression)?;
        }
        other => return Err(format!("unsupported schedule kind '{}'", other)),
    }
    Ok(())
}

fn initial_next_fire_at_request(request: &ScheduleRequest, now_unix_ms: u64) -> Option<u64> {
    match request.schedule_kind.trim() {
        "interval" => Some(now_unix_ms + (request.every_seconds * 1_000)),
        "once" => request.not_before_unix_ms,
        "daily" => next_daily_fire_at(&request.schedule_expression, now_unix_ms),
        _ => None,
    }
}

fn initial_next_fire_at(record: &ScheduledJobRecord, now_unix_ms: u64) -> Option<u64> {
    match record.schedule_kind.as_str() {
        "interval" => Some(now_unix_ms + (record.every_seconds * 1_000)),
        "once" => record.not_before_unix_ms,
        "daily" => next_daily_fire_at(&record.schedule_expression, now_unix_ms),
        _ => None,
    }
}

fn schedule_is_due(record: &ScheduledJobRecord, now_unix_ms: u64) -> bool {
    if !record.enabled {
        return false;
    }
    record
        .next_fire_at_unix_ms
        .map(|value| value <= now_unix_ms)
        .unwrap_or(false)
}

fn default_schedule_record(entry: &str) -> Option<ScheduledJobRecord> {
    let now = now_unix_ms();
    let (job_id, agent_id, job_kind, schedule_expression, payload_json) = match entry.trim() {
        "night_shift_kickoff" => (
            "night_shift_kickoff",
            "leviathann",
            "night_shift_kickoff",
            "00:05",
            json!({"message": "Night shift kickoff scaffold is ready."}).to_string(),
        ),
        "night_shift_research" => (
            "night_shift_research",
            "atlas",
            "night_shift_research",
            "00:15",
            json!({"message": "Night shift research queue is staged."}).to_string(),
        ),
        "night_shift_write" => (
            "night_shift_write",
            "quill",
            "night_shift_write",
            "06:15",
            json!({"message": "Night shift writing lane is staged."}).to_string(),
        ),
        "morning_brief" => (
            "morning_brief",
            "leviathann",
            "morning_brief",
            "07:00",
            json!({"message": "Morning brief slot is reserved."}).to_string(),
        ),
        _ => return None,
    };
    Some(ScheduledJobRecord {
        job_id: job_id.to_string(),
        agent_id: agent_id.to_string(),
        job_kind: job_kind.to_string(),
        schedule_kind: "daily".to_string(),
        schedule_expression: schedule_expression.to_string(),
        timezone: "UTC".to_string(),
        every_seconds: 0,
        not_before_unix_ms: None,
        payload_json,
        delivery_target: None,
        source_kind: "default".to_string(),
        enabled: true,
        status: "scheduled".to_string(),
        max_attempts: 1,
        run_count: 0,
        last_fire_at_unix_ms: None,
        next_fire_at_unix_ms: next_daily_fire_at(schedule_expression, now),
    })
}

fn next_daily_fire_at(expression: &str, now_unix_ms: u64) -> Option<u64> {
    let (hour, minute) = parse_daily_expression(expression).ok()?;
    let day_ms = 86_400_000u64;
    let target_ms = ((hour as u64) * 3_600_000) + ((minute as u64) * 60_000);
    let day_start = now_unix_ms - (now_unix_ms % day_ms);
    let mut candidate = day_start + target_ms;
    if candidate <= now_unix_ms {
        candidate = candidate.saturating_add(day_ms);
    }
    Some(candidate)
}

fn parse_daily_expression(expression: &str) -> LoomResult<(u32, u32)> {
    let trimmed = expression.trim();
    let (hour, minute) = trimmed
        .split_once(':')
        .ok_or_else(|| "daily schedules require HH:MM expression".to_string())?;
    let hour = hour
        .trim()
        .parse::<u32>()
        .map_err(|error| format!("invalid daily hour: {}", error))?;
    let minute = minute
        .trim()
        .parse::<u32>()
        .map_err(|error| format!("invalid daily minute: {}", error))?;
    if hour > 23 || minute > 59 {
        return Err("daily schedules require hour 0-23 and minute 0-59".to_string());
    }
    Ok((hour, minute))
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::channels::list_channel_deliveries;
    use crate::init_workspace;
    use crate::onboarding::{load_onboard_manifest, write_onboard_manifest};

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
    fn scaffold_creates_schedule_registry() {
        let root = temp_path("loom-schedule-scaffold");
        let registry_path = ensure_schedule_runtime_scaffold(&root).expect("schedule scaffold");
        assert!(registry_path.exists());
        assert!(schedule_runs_path(&root).exists());
        let overview = schedule_overview(&root, 0).expect("schedule overview");
        assert_eq!(overview.total_count, 0);
    }

    #[test]
    fn sync_registry_materializes_default_entries_from_onboard_manifest() {
        let root = temp_path("loom-schedule-sync");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        let mut manifest = load_onboard_manifest(&root).expect("load onboard manifest");
        manifest.recurring_install_defaults = true;
        manifest.recurring_entries = vec![
            "night_shift_kickoff".to_string(),
            "night_shift_research".to_string(),
            "morning_brief".to_string(),
        ];
        write_onboard_manifest(&root, &manifest).expect("write onboard manifest");
        let summary = sync_schedule_registry(&root).expect("sync schedules");
        assert_eq!(summary.total_count, 3);
        assert!(summary.job_ids.contains(&"night_shift_kickoff".to_string()));
    }

    #[test]
    fn add_and_run_due_schedule_queues_guarded_delivery() {
        let root = temp_path("loom-schedule-run");
        init_workspace(&root, "embedded", Some("/tmp/meridian-kernel"), "org_demo")
            .expect("init workspace");
        let mut manifest = load_onboard_manifest(&root).expect("load onboard manifest");
        manifest.telegram_enabled = true;
        write_onboard_manifest(&root, &manifest).expect("write onboard manifest");
        crate::channels::sync_channel_registry(&root).expect("sync channel registry");

        add_schedule(
            &root,
            &ScheduleRequest {
                job_id: Some("brief-delivery".to_string()),
                agent_id: "leviathann".to_string(),
                job_kind: "brief_delivery".to_string(),
                schedule_kind: "once".to_string(),
                schedule_expression: String::new(),
                timezone: "UTC".to_string(),
                every_seconds: 0,
                not_before_unix_ms: Some(10),
                payload_json: json!({
                    "message": "[✅ FINAL ANSWER]\nMeridian morning brief ready\n[🛡️ PoGE PROTOCOL] Cryptographic Audit Root Settled: 0xbeef"
                }).to_string(),
                delivery_target: Some(ScheduleDeliveryTarget {
                    channel_id: "telegram".to_string(),
                    recipient: "founder".to_string(),
                    allow_receipt_hashes: true,
                    allow_operator_diagnostics: false,
                }),
                max_attempts: 1,
                source_kind: "manual".to_string(),
            },
        )
        .expect("add schedule");

        let summary = run_due_schedules(&root, 10, 5).expect("run due schedules");
        assert_eq!(summary.dispatched_count, 1);
        assert_eq!(summary.delivery_queued_count, 1);
        let deliveries = list_channel_deliveries(&root, 10).expect("list deliveries");
        assert_eq!(deliveries.len(), 1);
        assert!(deliveries[0]
            .display_text
            .contains("Meridian morning brief ready"));
        assert!(deliveries[0].display_text.contains("[PoGE Receipt] 0xbeef"));
    }

    #[test]
    fn pause_and_cancel_schedule_update_status() {
        let root = temp_path("loom-schedule-mutate");
        ensure_schedule_runtime_scaffold(&root).expect("schedule scaffold");
        add_schedule(
            &root,
            &ScheduleRequest {
                job_id: Some("night-run".to_string()),
                agent_id: "atlas".to_string(),
                job_kind: "night_run".to_string(),
                schedule_kind: "daily".to_string(),
                schedule_expression: "00:30".to_string(),
                timezone: "UTC".to_string(),
                every_seconds: 0,
                not_before_unix_ms: None,
                payload_json: "{}".to_string(),
                delivery_target: None,
                max_attempts: 1,
                source_kind: "manual".to_string(),
            },
        )
        .expect("add schedule");
        let paused = pause_schedule(&root, "night-run").expect("pause schedule");
        assert_eq!(paused.record.status, "paused");
        assert!(!paused.record.enabled);
        let cancelled = cancel_schedule(&root, "night-run").expect("cancel schedule");
        assert_eq!(cancelled.record.status, "cancelled");
        assert!(cancelled.record.next_fire_at_unix_ms.is_none());
    }
}
