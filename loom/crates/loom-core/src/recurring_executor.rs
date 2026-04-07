use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

use crate::channels::{enqueue_channel_delivery, ChannelDeliveryRequest};
use crate::recurring::HeartbeatRecord;
use crate::schedules::{schedule_runs_path, ScheduledJobRecord};

pub type LoomResult<T> = Result<T, String>;

pub const DEFAULT_RECURRING_RUNS_DIR: &str = "state/recurring/runs";
pub const DEFAULT_RECURRING_RUN_INDEX_PATH: &str = "state/recurring/run-index.json";

struct ExecutionAttempt {
    exit_code: i32,
    stdout: Option<String>,
    stderr: Option<String>,
    status: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RecurringRunRecord {
    pub run_id: String,
    pub job_type: String,
    pub job_id: String,
    pub triggered_at: String,
    pub started_at: Option<String>,
    pub completed_at: Option<String>,
    pub status: String,
    pub exit_code: Option<i32>,
    pub stdout_summary: Option<String>,
    pub stderr_summary: Option<String>,
    pub delivery_intent_id: Option<String>,
    pub session_key: Option<String>,
    pub retry_count: u32,
    pub last_error: Option<String>,
    pub payload_json: String,
    pub agent_id: String,
    pub capability_name: String,
}

pub fn recurring_runs_dir(root: &Path) -> PathBuf {
    root.join(DEFAULT_RECURRING_RUNS_DIR)
}

pub fn recurring_run_index_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_RECURRING_RUN_INDEX_PATH)
}

pub fn ensure_recurring_executor_scaffold(root: &Path) -> LoomResult<PathBuf> {
    let runs_dir = recurring_runs_dir(root);
    fs::create_dir_all(&runs_dir).map_err(io_err)?;
    let index_path = recurring_run_index_path(root);
    if !index_path.exists() {
        fs::write(&index_path, "{\n  \"index\": {}\n}\n").map_err(io_err)?;
    }
    Ok(runs_dir)
}

pub fn dispatch_schedule_run(
    root: &Path,
    record: &ScheduledJobRecord,
) -> LoomResult<RecurringRunRecord> {
    ensure_recurring_executor_scaffold(root)?;
    let run_id = format!("sched-run-{}", unique_token());
    let now = timestamp_now();
    let capability_name = record
        .job_kind
        .trim()
        .to_string()
        .or_empty_fallback("loom.llm.inference.v1");

    let mut run = RecurringRunRecord {
        run_id: run_id.clone(),
        job_type: "schedule".to_string(),
        job_id: record.job_id.clone(),
        triggered_at: now.clone(),
        started_at: Some(now.clone()),
        completed_at: None,
        status: "running".to_string(),
        exit_code: None,
        stdout_summary: None,
        stderr_summary: None,
        delivery_intent_id: None,
        session_key: None,
        retry_count: 0,
        last_error: None,
        payload_json: record.payload_json.clone(),
        agent_id: record.agent_id.clone(),
        capability_name: capability_name.clone(),
    };

    persist_run_record(root, &run)?;
    index_run_record(root, &run)?;

    // Attempt execution via loom binary if available
    let execution_result = attempt_schedule_execution(
        root,
        &run_id,
        &capability_name,
        &record.agent_id,
        &record.payload_json,
    );

    match execution_result {
        Ok(attempt) => {
            run.exit_code = Some(attempt.exit_code);
            run.stdout_summary = truncate_output(attempt.stdout, 2000);
            run.stderr_summary = truncate_output(attempt.stderr, 500);
            run.status = attempt.status;
            if attempt.exit_code != 0 {
                run.last_error = run
                    .stderr_summary
                    .clone()
                    .or_else(|| run.stdout_summary.clone());
            }
        }
        Err(err) => {
            run.status = "dispatched".to_string();
            run.last_error = Some(err);
        }
    }

    // Attempt delivery if target exists
    if let Some(target) = record.delivery_target.as_ref() {
        let text = extract_delivery_text(&record.payload_json, &run);
        if let Ok(delivery) = enqueue_channel_delivery(
            root,
            &ChannelDeliveryRequest {
                channel_id: target.channel_id.clone(),
                recipient: target.recipient.clone(),
                raw_text: text,
                allow_receipt_hashes: target.allow_receipt_hashes,
                allow_operator_diagnostics: target.allow_operator_diagnostics,
            },
        ) {
            run.delivery_intent_id = Some(delivery.delivery_id.clone());
            if run.status == "dispatched" {
                run.status = if delivery.allowed {
                    "delivery_queued".to_string()
                } else {
                    "delivery_blocked".to_string()
                };
            }
        }
    }

    run.completed_at = Some(timestamp_now());
    persist_run_record(root, &run)?;
    index_run_record(root, &run)?;
    Ok(run)
}

pub fn dispatch_heartbeat_run(
    root: &Path,
    record: &HeartbeatRecord,
) -> LoomResult<RecurringRunRecord> {
    ensure_recurring_executor_scaffold(root)?;
    let run_id = format!("hb-run-{}", unique_token());
    let now = timestamp_now();
    let capability_name = record
        .capability_name
        .trim()
        .to_string()
        .or_empty_fallback("loom.llm.inference.v1");

    let mut run = RecurringRunRecord {
        run_id: run_id.clone(),
        job_type: "heartbeat".to_string(),
        job_id: record.heartbeat_id.clone(),
        triggered_at: now.clone(),
        started_at: Some(now.clone()),
        completed_at: None,
        status: "running".to_string(),
        exit_code: None,
        stdout_summary: None,
        stderr_summary: None,
        delivery_intent_id: None,
        session_key: None,
        retry_count: 0,
        last_error: None,
        payload_json: record.payload_json.clone(),
        agent_id: record.agent_id.clone(),
        capability_name: capability_name.clone(),
    };

    persist_run_record(root, &run)?;
    index_run_record(root, &run)?;

    // Attempt execution
    let execution_result = attempt_schedule_execution(
        root,
        &run_id,
        &capability_name,
        &record.agent_id,
        &record.payload_json,
    );

    match execution_result {
        Ok(attempt) => {
            run.exit_code = Some(attempt.exit_code);
            run.stdout_summary = truncate_output(attempt.stdout, 2000);
            run.stderr_summary = truncate_output(attempt.stderr, 500);
            run.status = attempt.status;
            if attempt.exit_code != 0 {
                run.last_error = run
                    .stderr_summary
                    .clone()
                    .or_else(|| run.stdout_summary.clone());
            }
        }
        Err(err) => {
            run.status = "dispatched".to_string();
            run.last_error = Some(err);
        }
    }

    // Attempt delivery if target exists
    if let Some(target) = record.delivery_target.as_ref() {
        let text = extract_delivery_text(&record.payload_json, &run);
        if let Ok(delivery) = enqueue_channel_delivery(
            root,
            &ChannelDeliveryRequest {
                channel_id: target.channel_id.clone(),
                recipient: target.recipient.clone(),
                raw_text: text,
                allow_receipt_hashes: target.allow_receipt_hashes,
                allow_operator_diagnostics: target.allow_operator_diagnostics,
            },
        ) {
            run.delivery_intent_id = Some(delivery.delivery_id.clone());
            if run.status == "dispatched" {
                run.status = if delivery.allowed {
                    "delivery_queued".to_string()
                } else {
                    "delivery_blocked".to_string()
                };
            }
        }
    }

    run.completed_at = Some(timestamp_now());
    persist_run_record(root, &run)?;
    index_run_record(root, &run)?;
    Ok(run)
}

pub fn list_recurring_runs(
    root: &Path,
    limit: usize,
    job_type_filter: Option<&str>,
) -> LoomResult<Vec<RecurringRunRecord>> {
    ensure_recurring_executor_scaffold(root)?;
    let mut records = Vec::new();
    let mut paths: Vec<PathBuf> = collect_run_paths(&recurring_runs_dir(root));
    paths.extend(collect_run_paths(&schedule_runs_path(root)));
    paths.sort_by(|a, b| b.file_name().cmp(&a.file_name()));
    for path in paths {
        let raw = match fs::read_to_string(&path) {
            Ok(raw) => raw,
            Err(_) => continue,
        };
        match parse_any_run_record(&raw) {
            Ok(run) => {
                if let Some(filter) = job_type_filter {
                    if !filter.is_empty() && run.job_type != filter {
                        continue;
                    }
                }
                records.push(run);
                if limit > 0 && records.len() >= limit {
                    break;
                }
            }
            Err(_) => continue,
        }
    }
    Ok(records)
}

pub fn show_recurring_run(root: &Path, run_id: &str) -> LoomResult<Option<RecurringRunRecord>> {
    let run_id = run_id.trim();
    if run_id.is_empty() {
        return Err("run_id is required".to_string());
    }
    ensure_recurring_executor_scaffold(root)?;
    let path = recurring_runs_dir(root).join(format!("{}.json", safe_filename(run_id)));
    if path.exists() {
        let raw = fs::read_to_string(&path).map_err(io_err)?;
        return Ok(Some(parse_run_record(&raw)?));
    }
    let schedule_path = schedule_runs_path(root).join(format!("{}.json", safe_filename(run_id)));
    if schedule_path.exists() {
        let raw = fs::read_to_string(&schedule_path).map_err(io_err)?;
        return Ok(Some(parse_schedule_run_record(&raw)?));
    }
    Ok(None)
}

// --- render ---

pub fn render_recurring_run_human(run: &RecurringRunRecord) -> String {
    format!(
        "run_id:            {}\njob_type:          {}\njob_id:            {}\nagent_id:          {}\ncapability_name:   {}\ntriggered_at:      {}\nstarted_at:        {}\ncompleted_at:      {}\nstatus:            {}\nexit_code:         {}\ndelivery_intent_id:{}\nretry_count:       {}\nlast_error:        {}\nstdout_summary:\n{}\n",
        run.run_id,
        run.job_type,
        run.job_id,
        run.agent_id,
        run.capability_name,
        run.triggered_at,
        run.started_at.as_deref().unwrap_or("(none)"),
        run.completed_at.as_deref().unwrap_or("(none)"),
        run.status,
        run.exit_code.map(|c| c.to_string()).unwrap_or_else(|| "(none)".to_string()),
        run.delivery_intent_id.as_deref().unwrap_or("(none)"),
        run.retry_count,
        run.last_error.as_deref().unwrap_or("(none)"),
        run.stdout_summary.as_deref().unwrap_or("(none)"),
    )
}

pub fn render_recurring_run_json(run: &RecurringRunRecord) -> String {
    serde_json::to_string_pretty(&run_record_json(run)).unwrap_or_else(|_| "{}".to_string()) + "\n"
}

pub fn render_recurring_runs_list_human(runs: &[RecurringRunRecord]) -> String {
    if runs.is_empty() {
        return "run_count:         0\n".to_string();
    }
    let mut out = format!("run_count:         {}\n", runs.len());
    for run in runs {
        out.push_str(&format!(
            "\n- {} job_type={} job_id={} status={} exit_code={}\n",
            run.run_id,
            run.job_type,
            run.job_id,
            run.status,
            run.exit_code
                .map(|c| c.to_string())
                .unwrap_or_else(|| "(none)".to_string()),
        ));
    }
    out
}

pub fn render_recurring_runs_list_json(runs: &[RecurringRunRecord]) -> String {
    serde_json::to_string_pretty(&runs.iter().map(run_record_json).collect::<Vec<_>>())
        .unwrap_or_else(|_| "[]".to_string())
        + "\n"
}

// --- internal ---

fn persist_run_record(root: &Path, run: &RecurringRunRecord) -> LoomResult<()> {
    let path = recurring_runs_dir(root).join(format!("{}.json", safe_filename(&run.run_id)));
    let mut rendered =
        serde_json::to_string_pretty(&run_record_json(run)).map_err(|e| e.to_string())?;
    rendered.push('\n');
    fs::write(path, rendered).map_err(io_err)
}

fn collect_run_paths(dir: &Path) -> Vec<PathBuf> {
    let entries = match fs::read_dir(dir) {
        Ok(entries) => entries,
        Err(_) => return Vec::new(),
    };
    entries
        .filter_map(|entry| entry.ok().map(|e| e.path()))
        .filter(|path| path.extension().and_then(|ext| ext.to_str()) == Some("json"))
        .collect()
}

fn index_run_record(root: &Path, run: &RecurringRunRecord) -> LoomResult<()> {
    let index_path = recurring_run_index_path(root);
    let raw = if index_path.exists() {
        fs::read_to_string(&index_path).unwrap_or_else(|_| "{\"index\":{}}".to_string())
    } else {
        "{\"index\":{}}".to_string()
    };
    let mut value: Value = serde_json::from_str(&raw).unwrap_or_else(|_| json!({"index": {}}));
    let index = value.as_object_mut().and_then(|obj| {
        obj.entry("index")
            .or_insert_with(|| json!({}))
            .as_object_mut()
    });
    if let Some(index) = index {
        let entry = index.entry(&run.job_id).or_insert_with(|| json!([]));
        if let Some(arr) = entry.as_array_mut() {
            let run_id_val = Value::String(run.run_id.clone());
            if !arr.contains(&run_id_val) {
                arr.push(run_id_val);
                // Keep last 50 per job
                if arr.len() > 50 {
                    arr.remove(0);
                }
            }
        }
    }
    let mut rendered =
        serde_json::to_string_pretty(&value).unwrap_or_else(|_| "{\"index\":{}}".to_string());
    rendered.push('\n');
    let _ = fs::write(index_path, rendered);
    Ok(())
}

fn attempt_capability_execution(
    root: &Path,
    capability_name: &str,
    agent_id: &str,
    payload_json: &str,
) -> Result<(i32, Option<String>, Option<String>), String> {
    // Check if the service runtime socket exists (service is running and accepting work).
    // We do NOT invoke a subprocess — that would create recursive dispatch.
    // Instead we record truthful state: if the service is up, the supervisor loop
    // will pick up queued work; if not, we report that honestly.
    let sock = root.join("run/service/runtime.sock");
    if !sock.exists() {
        return Err(format!(
            "service socket not available; recurring dispatch for capability '{}' agent '{}' recorded but not executed",
            capability_name, agent_id
        ));
    }
    Ok((
        0,
        Some(format!(
            "capability dispatch accepted: capability={} agent={} payload_bytes={}",
            capability_name,
            agent_id,
            payload_json.len()
        )),
        None,
    ))
}

fn attempt_schedule_execution(
    root: &Path,
    run_id: &str,
    capability_name: &str,
    agent_id: &str,
    payload_json: &str,
) -> Result<ExecutionAttempt, String> {
    if let Some(exec_argv) = extract_exec_argv(payload_json) {
        return run_exec_argv(root, run_id, agent_id, capability_name, &exec_argv);
    }
    let (exit_code, stdout, stderr) =
        attempt_capability_execution(root, capability_name, agent_id, payload_json)?;
    Ok(ExecutionAttempt {
        exit_code,
        stdout,
        stderr,
        status: if exit_code == 0 {
            "dispatched".to_string()
        } else {
            "failed".to_string()
        },
    })
}

fn extract_exec_argv(payload_json: &str) -> Option<Vec<String>> {
    let value = serde_json::from_str::<Value>(payload_json).ok()?;
    let argv = value.get("exec_argv")?.as_array()?;
    let collected = argv
        .iter()
        .map(|item| {
            item.as_str()
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(str::to_string)
        })
        .collect::<Option<Vec<_>>>()?;
    if collected.is_empty() {
        None
    } else {
        Some(collected)
    }
}

fn run_exec_argv(
    root: &Path,
    run_id: &str,
    agent_id: &str,
    capability_name: &str,
    exec_argv: &[String],
) -> Result<ExecutionAttempt, String> {
    if exec_argv.is_empty() {
        return Err("exec_argv requires at least one command token".to_string());
    }
    let mut command = Command::new(&exec_argv[0]);
    if exec_argv.len() > 1 {
        command.args(&exec_argv[1..]);
    }
    command
        .current_dir(root)
        .env("MERIDIAN_LOOM_ROOT", root.display().to_string())
        .env("MERIDIAN_RECURRING_RUN_ID", run_id)
        .env("MERIDIAN_RECURRING_AGENT_ID", agent_id)
        .env("MERIDIAN_RECURRING_CAPABILITY", capability_name);
    let output = command.output().map_err(io_err)?;
    let exit_code = output.status.code().unwrap_or(1);
    Ok(ExecutionAttempt {
        exit_code,
        stdout: string_from_bytes(output.stdout),
        stderr: string_from_bytes(output.stderr),
        status: if exit_code == 0 {
            "completed".to_string()
        } else {
            "failed".to_string()
        },
    })
}

fn string_from_bytes(raw: Vec<u8>) -> Option<String> {
    let text = String::from_utf8_lossy(&raw).trim().to_string();
    if text.is_empty() {
        None
    } else {
        Some(text)
    }
}

fn extract_delivery_text(payload_json: &str, run: &RecurringRunRecord) -> String {
    // Try to extract a message from payload, fall back to stdout, then status
    if let Ok(value) = serde_json::from_str::<Value>(payload_json) {
        if let Some(msg) = value.get("message").and_then(Value::as_str) {
            if !msg.is_empty() {
                return msg.to_string();
            }
        }
        if let Some(text) = value.get("text").and_then(Value::as_str) {
            if !text.is_empty() {
                return text.to_string();
            }
        }
    }
    if let Some(ref stdout) = run.stdout_summary {
        if !stdout.is_empty() {
            return stdout.clone();
        }
    }
    format!("recurring run {} status={}", run.run_id, run.status)
}

fn parse_run_record(raw: &str) -> LoomResult<RecurringRunRecord> {
    let value: Value =
        serde_json::from_str(raw).map_err(|e| format!("invalid run record json: {e}"))?;
    Ok(RecurringRunRecord {
        run_id: value_string(value.get("run_id"), "run_id")?,
        job_type: value_string_or(value.get("job_type"), "schedule"),
        job_id: value_string_or(value.get("job_id"), ""),
        triggered_at: value_string_or(value.get("triggered_at"), ""),
        started_at: value_opt_string(value.get("started_at")),
        completed_at: value_opt_string(value.get("completed_at")),
        status: value_string_or(value.get("status"), "unknown"),
        exit_code: value
            .get("exit_code")
            .and_then(Value::as_i64)
            .map(|v| v as i32),
        stdout_summary: value_opt_string(value.get("stdout_summary")),
        stderr_summary: value_opt_string(value.get("stderr_summary")),
        delivery_intent_id: value_opt_string(value.get("delivery_intent_id")),
        session_key: value_opt_string(value.get("session_key")),
        retry_count: value
            .get("retry_count")
            .and_then(Value::as_u64)
            .map(|v| v as u32)
            .unwrap_or(0),
        last_error: value_opt_string(value.get("last_error")),
        payload_json: value_string_or(value.get("payload_json"), "{}"),
        agent_id: value_string_or(value.get("agent_id"), ""),
        capability_name: value_string_or(value.get("capability_name"), ""),
    })
}

fn parse_any_run_record(raw: &str) -> LoomResult<RecurringRunRecord> {
    let value: Value =
        serde_json::from_str(raw).map_err(|e| format!("invalid run record json: {e}"))?;
    if value.get("job_type").is_some() || value.get("triggered_at").is_some() {
        parse_run_record(raw)
    } else {
        parse_schedule_run_record(raw)
    }
}

fn parse_schedule_run_record(raw: &str) -> LoomResult<RecurringRunRecord> {
    let value: Value =
        serde_json::from_str(raw).map_err(|e| format!("invalid schedule run record json: {e}"))?;
    let fired_at = value
        .get("fired_at_unix_ms")
        .and_then(Value::as_u64)
        .map(|v| v.to_string())
        .unwrap_or_default();
    let delivery_id = value_opt_string(value.get("delivery_id"));
    let session_key = match (
        value_opt_string(value.get("delivery_channel_id")),
        value_opt_string(value.get("delivery_recipient")),
    ) {
        (Some(channel), Some(recipient)) if !channel.is_empty() && !recipient.is_empty() => {
            Some(format!("{channel}:{recipient}"))
        }
        _ => None,
    };
    Ok(RecurringRunRecord {
        run_id: value_string(value.get("run_id"), "run_id")?,
        job_type: "schedule".to_string(),
        job_id: value_string_or(value.get("job_id"), ""),
        triggered_at: fired_at.clone(),
        started_at: if fired_at.is_empty() {
            None
        } else {
            Some(fired_at.clone())
        },
        completed_at: if fired_at.is_empty() {
            None
        } else {
            Some(fired_at)
        },
        status: value_string_or(value.get("status"), "unknown"),
        exit_code: None,
        stdout_summary: None,
        stderr_summary: None,
        delivery_intent_id: delivery_id,
        session_key,
        retry_count: 0,
        last_error: None,
        payload_json: value_string_or(value.get("payload_json"), "{}"),
        agent_id: value_string_or(value.get("agent_id"), ""),
        capability_name: value_string_or(value.get("job_kind"), ""),
    })
}

fn run_record_json(run: &RecurringRunRecord) -> Value {
    json!({
        "run_id": run.run_id,
        "job_type": run.job_type,
        "job_id": run.job_id,
        "triggered_at": run.triggered_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "status": run.status,
        "exit_code": run.exit_code,
        "stdout_summary": run.stdout_summary,
        "stderr_summary": run.stderr_summary,
        "delivery_intent_id": run.delivery_intent_id,
        "session_key": run.session_key,
        "retry_count": run.retry_count,
        "last_error": run.last_error,
        "payload_json": run.payload_json,
        "agent_id": run.agent_id,
        "capability_name": run.capability_name,
    })
}

fn truncate_output(text: Option<String>, max_len: usize) -> Option<String> {
    text.map(|s| {
        let trimmed = s.trim().to_string();
        if trimmed.len() > max_len {
            format!("{}...", &trimmed[..max_len])
        } else {
            trimmed
        }
    })
    .filter(|s| !s.is_empty())
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

trait OrEmptyFallback {
    fn or_empty_fallback(self, fallback: &str) -> String;
}

impl OrEmptyFallback for String {
    fn or_empty_fallback(self, fallback: &str) -> String {
        if self.is_empty() {
            fallback.to_string()
        } else {
            self
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::init_workspace;
    use crate::schedules::{add_schedule, run_due_schedules, ScheduleRequest};
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_path(label: &str) -> PathBuf {
        let ts = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        std::env::temp_dir().join(format!("{}-{}", label, ts))
    }

    #[test]
    fn ensure_recurring_executor_scaffold_creates_dirs() {
        let root = temp_path("loom-recurring-exec-scaffold");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        let runs_dir = ensure_recurring_executor_scaffold(&root).expect("scaffold");
        assert!(runs_dir.exists());
        assert!(recurring_run_index_path(&root).exists());
    }

    #[test]
    fn list_recurring_runs_empty_on_fresh_root() {
        let root = temp_path("loom-recurring-exec-list");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        let runs = list_recurring_runs(&root, 10, None).expect("list");
        assert!(runs.is_empty());
    }

    #[test]
    fn show_recurring_run_returns_none_for_unknown_id() {
        let root = temp_path("loom-recurring-exec-show");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        let result = show_recurring_run(&root, "run-does-not-exist").expect("show");
        assert!(result.is_none());
    }

    #[test]
    fn list_recurring_runs_includes_schedule_run_records() {
        let root = temp_path("loom-recurring-exec-schedule-runs");
        init_workspace(&root, "embedded", None, "org_demo").expect("init");
        add_schedule(
            &root,
            &ScheduleRequest {
                job_id: Some("recurring-visible-schedule".to_string()),
                agent_id: "atlas".to_string(),
                job_kind: "research".to_string(),
                schedule_kind: "once".to_string(),
                schedule_expression: String::new(),
                timezone: "UTC".to_string(),
                every_seconds: 0,
                not_before_unix_ms: Some(10),
                payload_json: "{\"message\":\"recurring schedule visible\"}".to_string(),
                delivery_target: None,
                max_attempts: 1,
                source_kind: "manual".to_string(),
            },
        )
        .expect("add schedule");
        let summary = run_due_schedules(&root, 10, 10).expect("run due");
        assert_eq!(summary.dispatched_count, 1);
        let run_id = summary.run_records[0].run_id.clone();

        let runs = list_recurring_runs(&root, 10, Some("schedule")).expect("list recurring runs");
        assert!(runs.iter().any(|run| run.run_id == run_id));

        let shown = show_recurring_run(&root, &run_id)
            .expect("show run")
            .expect("schedule run visible");
        assert_eq!(shown.job_type, "schedule");
        assert_eq!(shown.run_id, run_id);
    }
}
