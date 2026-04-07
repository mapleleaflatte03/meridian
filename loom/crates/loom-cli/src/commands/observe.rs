use std::io::{IsTerminal, Write};
use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;

use crate::*;
use serde_json::{json, Value};

const OBSERVABILITY_CONTRACT_VERSION: &str = "observability_contract_v1";
const OBSERVABILITY_CONTRACT_PATH: &str = "state/observability/observability_contract_v1.json";
const OBSERVABILITY_LATEST_ARTIFACT_PATH: &str = "artifacts/observability/latest.json";
const OBSERVABILITY_ALERT_STREAM_PATH: &str = "state/observability/alerts_stream.jsonl";
const ROUTE_TRACE_PATH: &str = "state/gateway/route_decision_trace.jsonl";
const CONNECT_REGISTRY_PATH: &str = "state/connect/registry.json";
const CONNECT_HEALTH_DIR: &str = "state/connect/health";

pub(crate) fn handle_observe(args: &[String]) -> LoomResult<()> {
    if args.is_empty()
        || matches!(
            args.first().map(String::as_str),
            Some("help" | "--help" | "-h")
        )
    {
        print_observe_help();
        return Ok(());
    }
    match args.first().map(String::as_str) {
        Some("summary") => handle_observe_summary(&args[1..]),
        Some("alerts") => handle_observe_alerts(&args[1..]),
        Some("watch") => handle_observe_watch(&args[1..]),
        _ => Err("observe supports 'summary', 'alerts', and 'watch'".to_string()),
    }
}

fn print_observe_help() {
    println!(
        "Meridian Loom // OBSERVE

Operator-grade observability summary for queue, service, proof chain, and route drift.

USAGE: loom observe <COMMAND> [OPTIONS]

COMMANDS:
  summary [--root ROOT] [--fix-hints] [--format human|json]
  alerts  [--root ROOT] [--fix-hints] [--format human|json]
  watch   [--root ROOT] [--iterations N] [--interval-seconds N] [--follow] [--stream] [--fix-hints] [--format human|json]"
    );
}

fn handle_observe_summary(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let include_fix_hints = has_flag(args, "--fix-hints");
    let payload = build_observability_payload(&root, include_fix_hints)?;
    persist_observability_payload(&root, &payload)?;
    print_observe_payload(&payload, &format)
}

fn handle_observe_alerts(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let include_fix_hints = has_flag(args, "--fix-hints");
    let payload = build_observability_payload(&root, include_fix_hints)?;
    let alerts_payload = json!({
        "status": "observe_alerts",
        "contract_version": OBSERVABILITY_CONTRACT_VERSION,
        "overall_status": payload.get("overall_status").cloned().unwrap_or(Value::String("unknown".to_string())),
        "alert_count": payload.get("alerts").and_then(Value::as_array).map(|items| items.len()).unwrap_or(0),
        "alerts": payload.get("alerts").cloned().unwrap_or_else(|| Value::Array(vec![])),
        "fix_hints": payload.get("fix_hints").cloned().unwrap_or_else(|| Value::Array(vec![])),
        "paths": payload.get("paths").cloned().unwrap_or(Value::Null),
    });
    print_observe_payload(&alerts_payload, &format)
}

fn handle_observe_watch(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let include_fix_hints = has_flag(args, "--fix-hints");
    let stream_mode = has_flag(args, "--stream");
    let follow_mode = has_flag(args, "--follow");
    let iterations = if follow_mode {
        take_value(args, "--iterations")
            .and_then(|raw| raw.parse::<usize>().ok())
            .unwrap_or(usize::MAX)
    } else {
        take_value(args, "--iterations")
            .and_then(|raw| raw.parse::<usize>().ok())
            .unwrap_or(5)
            .max(1)
    };
    let interval_seconds = take_value(args, "--interval-seconds")
        .and_then(|raw| raw.parse::<u64>().ok())
        .unwrap_or(1);

    let mut frames = Vec::new();
    let mut emitted_frames = 0_u64;
    for index in 0..iterations {
        let payload = build_observability_payload(&root, include_fix_hints)?;
        persist_observability_payload(&root, &payload)?;
        let frame = json!({
            "status": "observe_watch_frame",
            "contract_version": OBSERVABILITY_CONTRACT_VERSION,
            "iteration": index + 1,
            "observed_at": chrono_like_timestamp(),
            "overall_status": payload.get("overall_status").cloned().unwrap_or(Value::String("unknown".to_string())),
            "alert_count": payload.get("alerts").and_then(Value::as_array).map(|items| items.len()).unwrap_or(0),
            "alerts": payload.get("alerts").cloned().unwrap_or_else(|| Value::Array(vec![])),
            "fix_hints": payload.get("fix_hints").cloned().unwrap_or_else(|| Value::Array(vec![])),
            "components": payload.get("components").cloned().unwrap_or(Value::Null),
            "operator_view": {
                "runtime_service_status": payload.pointer("/components/runtime_service/status").and_then(Value::as_str).unwrap_or("unknown"),
                "queue_total_pending": payload.pointer("/components/queue/total_pending").and_then(Value::as_u64).unwrap_or(0),
                "proof_chain_status": payload.pointer("/components/proof_chain/status").and_then(Value::as_str).unwrap_or("unknown"),
                "connect_status": payload.pointer("/components/connect/status").and_then(Value::as_str).unwrap_or("unknown"),
                "connect_summary": payload.pointer("/components/connect/operators_summary").and_then(Value::as_str).unwrap_or(""),
            },
            "stream_path": observability_alert_stream_path(&root).display().to_string(),
        });
        append_jsonl_event(&observability_alert_stream_path(&root), &frame)?;
        emitted_frames = emitted_frames.saturating_add(1);

        if stream_mode {
            emit_observe_watch_frame(&frame, &format)?;
        } else {
            if format == "human" {
                print_observe_payload(&payload, "human")?;
            }
            frames.push(frame);
        }
        if index + 1 < iterations {
            thread::sleep(Duration::from_secs(interval_seconds));
        }
    }

    if stream_mode {
        let completion = json!({
            "status": "observe_watch_complete",
            "contract_version": OBSERVABILITY_CONTRACT_VERSION,
            "iterations": if follow_mode { Value::Null } else { Value::Number((iterations as u64).into()) },
            "interval_seconds": interval_seconds,
            "emitted_frames": emitted_frames,
            "stream_path": observability_alert_stream_path(&root).display().to_string(),
        });
        if format == "json" {
            println!(
                "{}",
                serde_json::to_string(&completion).map_err(|error| error.to_string())?
            );
            std::io::stdout()
                .flush()
                .map_err(|error| error.to_string())?;
        } else {
            print_human(&format!(
                "observe stream complete: frames={} path={}\n",
                emitted_frames,
                observability_alert_stream_path(&root).display()
            ));
        }
        return Ok(());
    }

    let payload = json!({
        "status": "observe_watch",
        "contract_version": OBSERVABILITY_CONTRACT_VERSION,
        "iterations": iterations,
        "interval_seconds": interval_seconds,
        "frames": frames,
    });
    if format == "human" {
        Ok(())
    } else {
        print_observe_payload(&payload, "json")
    }
}

fn emit_observe_watch_frame(frame: &Value, format: &str) -> LoomResult<()> {
    match format {
        "json" => {
            println!(
                "{}",
                serde_json::to_string(frame).map_err(|error| error.to_string())?
            );
            std::io::stdout()
                .flush()
                .map_err(|error| error.to_string())?;
        }
        _ => {
            print_human(&render_observe_watch_frame_human(frame));
        }
    }
    Ok(())
}

fn render_observe_watch_frame_human(frame: &Value) -> String {
    let mut lines = vec![
        "Meridian Loom // OBSERVE STREAM".to_string(),
        "==============================".to_string(),
        format!(
            "frame:               {}",
            frame.get("iteration").and_then(Value::as_u64).unwrap_or(0)
        ),
        format!(
            "observed_at:         {}",
            frame
                .get("observed_at")
                .and_then(Value::as_str)
                .unwrap_or("")
        ),
        format!(
            "overall_status:      {}",
            frame
                .get("overall_status")
                .and_then(Value::as_str)
                .unwrap_or("unknown")
        ),
        format!(
            "alert_count:         {}",
            frame
                .get("alert_count")
                .and_then(Value::as_u64)
                .unwrap_or(0)
        ),
        format!(
            "service:             {}",
            frame
                .pointer("/operator_view/runtime_service_status")
                .and_then(Value::as_str)
                .unwrap_or("unknown")
        ),
        format!(
            "queue_pending:       {}",
            frame
                .pointer("/operator_view/queue_total_pending")
                .and_then(Value::as_u64)
                .unwrap_or(0)
        ),
        format!(
            "proof_chain:         {}",
            frame
                .pointer("/operator_view/proof_chain_status")
                .and_then(Value::as_str)
                .unwrap_or("unknown")
        ),
        format!(
            "connect:             {} ({})",
            frame
                .pointer("/operator_view/connect_status")
                .and_then(Value::as_str)
                .unwrap_or("unknown"),
            frame
                .pointer("/operator_view/connect_summary")
                .and_then(Value::as_str)
                .unwrap_or("")
        ),
        String::new(),
        "alerts".to_string(),
        "------".to_string(),
    ];
    let alerts = frame
        .get("alerts")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if alerts.is_empty() {
        lines.push("- none".to_string());
    } else {
        for item in alerts.iter().take(3) {
            lines.push(format!(
                "- [{}] {}: {}",
                item.get("severity")
                    .and_then(Value::as_str)
                    .unwrap_or("info"),
                item.get("code")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown"),
                item.get("message").and_then(Value::as_str).unwrap_or("")
            ));
        }
    }
    lines.push(String::new());
    lines.push("hint: use Ctrl+C to stop realtime stream".to_string());
    lines.push(String::new());
    lines.join("\n")
}

fn build_observability_payload(root: &Path, include_fix_hints: bool) -> LoomResult<Value> {
    let service = runtime_service_status(root, None).map_err(|error| error.to_string())?;
    let queue = queue_status(root).map_err(|error| error.to_string())?;
    let proof_chain = proof_chain_snapshot(root)?;
    let route_trace = route_trace_snapshot(root)?;
    let connect = connect_snapshot(root)?;

    let mut alerts = Vec::new();
    if !service.running {
        alerts.push(alert(
            "service_not_running",
            "warning",
            "runtime service is not currently running",
        ));
    }
    if queue.total_pending > 0 {
        alerts.push(alert(
            "queue_backlog",
            "warning",
            &format!("queue has {} pending jobs", queue.total_pending),
        ));
    }
    if proof_chain
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("missing")
        != "ready"
    {
        alerts.push(alert(
            "proof_chain_missing",
            "critical",
            "zk + settlement latest artifacts are not both available",
        ));
    }
    if route_trace
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("missing")
        == "missing"
    {
        alerts.push(alert(
            "route_trace_missing",
            "warning",
            "route decision trace is not yet available",
        ));
    }
    if route_trace
        .get("drift_count")
        .and_then(Value::as_u64)
        .unwrap_or(0)
        > 0
    {
        alerts.push(alert(
            "route_drift_detected",
            "warning",
            "detected drift markers in route decision trace",
        ));
    }
    match connect
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("missing")
    {
        "missing" => alerts.push(alert(
            "connect_registry_missing",
            "warning",
            "connect registry is not available; adapter fleet cannot be observed",
        )),
        "degraded" => alerts.push(alert(
            "connect_degraded",
            "warning",
            "one or more connect adapters are degraded",
        )),
        _ => {}
    }
    if connect
        .get("fallback_active_count")
        .and_then(Value::as_u64)
        .unwrap_or(0)
        > 0
    {
        alerts.push(alert(
            "connect_fallback_active",
            "warning",
            "connect fallback is active for one or more adapters",
        ));
    }

    let overall_status = if alerts
        .iter()
        .any(|item| item.get("severity").and_then(Value::as_str) == Some("critical"))
    {
        "degraded"
    } else if alerts.is_empty() {
        "healthy"
    } else {
        "warning"
    };

    let mut payload = json!({
        "status": "observe_summary",
        "contract_version": OBSERVABILITY_CONTRACT_VERSION,
        "generated_at": chrono_like_timestamp(),
        "overall_status": overall_status,
        "components": {
            "runtime_service": {
                "status": if service.running { "running" } else { "stopped" },
                "runtime_state_status": service.status,
                "running": service.running,
                "pending_jobs": service.pending_jobs,
                "processed_jobs": service.processed_jobs,
                "failed_jobs": service.failed_jobs,
                "requests_received": service.requests_received,
                "note": service.note,
                "state_path": service.runtime_state_path.display().to_string(),
                "metrics_path": service.metrics_path.display().to_string(),
            },
            "queue": {
                "pending_records": queue.pending_records,
                "acked_records": queue.acked_records,
                "total_pending": queue.total_pending,
                "standard_depth": queue.standard_depth,
                "privileged_depth": queue.privileged_depth,
                "budget_heavy_depth": queue.budget_heavy_depth,
                "sanction_sensitive_depth": queue.sanction_sensitive_depth,
                "queue_dir": queue.queue_dir.display().to_string(),
            },
            "proof_chain": proof_chain,
            "route_decision": route_trace,
            "connect": connect,
        },
        "alerts": alerts,
        "fix_hints": Value::Array(Vec::new()),
        "paths": {
            "contract": observability_contract_path(root).display().to_string(),
            "latest_artifact": observability_latest_artifact_path(root).display().to_string(),
        }
    });

    if include_fix_hints {
        payload["fix_hints"] = Value::Array(fix_hints_from_alerts(
            payload
                .get("alerts")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default(),
        ));
    }
    Ok(payload)
}

fn proof_chain_snapshot(root: &Path) -> LoomResult<Value> {
    let zk_path = root.join("artifacts/zk/latest.json");
    let settlement_path = root.join("artifacts/settlement/latest.json");
    let zk_value = read_optional_json(&zk_path)?;
    let settlement_value = read_optional_json(&settlement_path)?;
    let zk_status = zk_value
        .as_ref()
        .and_then(|value| value.get("status"))
        .and_then(Value::as_str)
        .unwrap_or("");
    let settlement_status = settlement_value
        .as_ref()
        .and_then(|value| value.get("status"))
        .and_then(Value::as_str)
        .unwrap_or("");
    let status = if !zk_status.is_empty() && !settlement_status.is_empty() {
        "ready"
    } else {
        "missing"
    };
    Ok(json!({
        "status": status,
        "zk_status": zk_status,
        "settlement_status": settlement_status,
        "zk_path": zk_path.display().to_string(),
        "settlement_path": settlement_path.display().to_string(),
    }))
}

fn route_trace_snapshot(root: &Path) -> LoomResult<Value> {
    let path = root.join(ROUTE_TRACE_PATH);
    if !path.exists() {
        return Ok(json!({
            "status": "missing",
            "trace_path": path.display().to_string(),
            "trace_count": 0,
            "drift_count": 0,
            "last_trace_id": "",
        }));
    }
    let raw = std::fs::read_to_string(&path).map_err(|error| error.to_string())?;
    let mut trace_count = 0usize;
    let mut drift_count = 0usize;
    let mut last_trace_id = String::new();
    for line in raw.lines() {
        let Ok(value) = serde_json::from_str::<Value>(line) else {
            continue;
        };
        trace_count += 1;
        if value
            .get("drift_flag")
            .and_then(Value::as_bool)
            .unwrap_or(false)
        {
            drift_count += 1;
        }
        if let Some(trace_id) = value.get("trace_id").and_then(Value::as_str) {
            if !trace_id.trim().is_empty() {
                last_trace_id = trace_id.to_string();
            }
        }
    }
    Ok(json!({
        "status": if trace_count > 0 { "ready" } else { "empty" },
        "trace_path": path.display().to_string(),
        "trace_count": trace_count,
        "drift_count": drift_count,
        "last_trace_id": last_trace_id,
    }))
}

fn connect_snapshot(root: &Path) -> LoomResult<Value> {
    let registry_path = root.join(CONNECT_REGISTRY_PATH);
    if !registry_path.exists() {
        return Ok(json!({
            "status": "missing",
            "registry_path": registry_path.display().to_string(),
            "total_adapters": 0,
            "enabled_adapters": 0,
            "degraded_adapters": 0,
            "reconnecting_count": 0,
            "fallback_active_count": 0,
            "health_dir": root.join(CONNECT_HEALTH_DIR).display().to_string(),
            "operators_summary": "connect registry missing",
        }));
    }

    let registry = read_optional_json(&registry_path)?
        .and_then(|value| value.as_object().cloned().map(Value::Object))
        .unwrap_or_else(|| json!({}));
    let adapters = registry
        .get("adapters")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if adapters.is_empty() {
        return Ok(json!({
            "status": "empty",
            "registry_path": registry_path.display().to_string(),
            "total_adapters": 0,
            "enabled_adapters": 0,
            "degraded_adapters": 0,
            "reconnecting_count": 0,
            "fallback_active_count": 0,
            "health_dir": root.join(CONNECT_HEALTH_DIR).display().to_string(),
            "operators_summary": "no adapters in connect registry",
        }));
    }

    let mut enabled_count = 0_u64;
    let mut degraded_count = 0_u64;
    let mut reconnecting_count = 0_u64;
    let mut fallback_count = 0_u64;

    for adapter in &adapters {
        let enabled = adapter
            .pointer("/lifecycle/enabled")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        if enabled {
            enabled_count = enabled_count.saturating_add(1);
        }
        let adapter_id = adapter
            .get("adapter_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim()
            .to_string();
        if adapter_id.is_empty() {
            continue;
        }
        let health_path = root
            .join(CONNECT_HEALTH_DIR)
            .join(format!("{}.json", adapter_id.as_str()));
        let health = read_optional_json(&health_path)?;

        let health_status = health
            .as_ref()
            .and_then(|value| value.get("health_status"))
            .and_then(Value::as_str)
            .unwrap_or("unknown");
        let lifecycle_state = health
            .as_ref()
            .and_then(|value| value.get("lifecycle_state"))
            .and_then(Value::as_str)
            .or_else(|| {
                adapter
                    .pointer("/lifecycle/state")
                    .and_then(Value::as_str)
                    .or_else(|| adapter.get("status").and_then(Value::as_str))
            })
            .unwrap_or("unknown");
        let fallback_active = health
            .as_ref()
            .and_then(|value| value.pointer("/lifecycle_metrics/fallback_active"))
            .and_then(Value::as_bool)
            .or_else(|| adapter.pointer("/fallback/active").and_then(Value::as_bool))
            .unwrap_or(false);

        if lifecycle_state == "reconnecting" {
            reconnecting_count = reconnecting_count.saturating_add(1);
        }
        if fallback_active {
            fallback_count = fallback_count.saturating_add(1);
        }
        let degraded = enabled
            && (health_status == "degraded"
                || matches!(lifecycle_state, "error" | "reconnecting" | "fallback"));
        if degraded {
            degraded_count = degraded_count.saturating_add(1);
        }
    }

    let status = if degraded_count > 0 || fallback_count > 0 {
        "degraded"
    } else {
        "ready"
    };
    Ok(json!({
        "status": status,
        "registry_path": registry_path.display().to_string(),
        "total_adapters": adapters.len() as u64,
        "enabled_adapters": enabled_count,
        "degraded_adapters": degraded_count,
        "reconnecting_count": reconnecting_count,
        "fallback_active_count": fallback_count,
        "health_dir": root.join(CONNECT_HEALTH_DIR).display().to_string(),
        "operators_summary": if status == "degraded" {
            format!("{} degraded / {} fallback", degraded_count, fallback_count)
        } else {
            "connect fleet healthy".to_string()
        },
    }))
}

fn fix_hints_from_alerts(alerts: Vec<Value>) -> Vec<Value> {
    let mut hints = Vec::new();
    for item in alerts {
        let Some(code) = item.get("code").and_then(Value::as_str) else {
            continue;
        };
        let hint = match code {
            "service_not_running" => {
                "run `loom service start --root \"$ROOT\" --kernel-path \"$KERNEL\" --service-token \"$TOKEN\"`"
            }
            "queue_backlog" => {
                "run `loom queue run-until-empty --root \"$ROOT\"` or `loom swarm run --settle-zk --root \"$ROOT\"`"
            }
            "proof_chain_missing" => {
                "run `loom shadow run ... --root \"$ROOT\"` then `loom job settle --zk --root \"$ROOT\" --kernel-path \"$KERNEL\"`"
            }
            "route_trace_missing" => {
                "run one managed gateway request and verify `state/gateway/route_decision_trace.jsonl` is written"
            }
            "route_drift_detected" => {
                "review route thresholds and rerun `loom observe summary --root \"$ROOT\" --fix-hints`"
            }
            "connect_registry_missing" => {
                "run `loom connect scaffold --name telegram_adapter --transport telegram --action-schema meridian.runtime.v1 --root \"$ROOT\"`"
            }
            "connect_degraded" => {
                "run `loom connect list --root \"$ROOT\"`, then `loom connect diagnostics --adapter-id \"$ADAPTER_ID\" --limit 10 --root \"$ROOT\"`"
            }
            "connect_fallback_active" => {
                "run `loom connect health --adapter-id \"$ADAPTER_ID\" --root \"$ROOT\"` until state returns `ready`"
            }
            _ => continue,
        };
        hints.push(json!({
            "code": code,
            "hint": hint,
        }));
    }
    hints
}

fn alert(code: &str, severity: &str, message: &str) -> Value {
    json!({
        "code": code,
        "severity": severity,
        "message": message,
    })
}

fn read_optional_json(path: &Path) -> LoomResult<Option<Value>> {
    if !path.exists() {
        return Ok(None);
    }
    let raw = std::fs::read_to_string(path).map_err(|error| error.to_string())?;
    let value = serde_json::from_str::<Value>(&raw)
        .map_err(|error| format!("failed to parse json at {}: {}", path.display(), error))?;
    Ok(Some(value))
}

fn print_observe_payload(payload: &Value, format: &str) -> LoomResult<()> {
    match format {
        "human" => {
            print_startup_banner();
            let mut lines = vec![
                format!(
                    "status:              {}",
                    payload
                        .get("status")
                        .and_then(Value::as_str)
                        .unwrap_or("unknown")
                ),
                format!(
                    "contract_version:    {}",
                    payload
                        .get("contract_version")
                        .and_then(Value::as_str)
                        .unwrap_or(OBSERVABILITY_CONTRACT_VERSION)
                ),
                format!(
                    "overall_status:      {}",
                    payload
                        .get("overall_status")
                        .and_then(Value::as_str)
                        .unwrap_or("unknown")
                ),
            ];
            if let Some(alerts) = payload.get("alerts").and_then(Value::as_array) {
                lines.push(format!("alert_count:         {}", alerts.len()));
            }
            lines.push(String::new());
            print_human(&(lines.join("\n") + "\n"));
            Ok(())
        }
        _ => {
            print!(
                "{}",
                serde_json::to_string_pretty(payload).map_err(|error| error.to_string())?
            );
            println!();
            Ok(())
        }
    }
}

fn output_format(args: &[String]) -> String {
    take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    })
}

fn persist_observability_payload(root: &Path, payload: &Value) -> LoomResult<()> {
    let contract_path = observability_contract_path(root);
    if let Some(parent) = contract_path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    std::fs::write(
        &contract_path,
        serde_json::to_string_pretty(payload).map_err(|error| error.to_string())? + "\n",
    )
    .map_err(|error| error.to_string())?;

    let latest_path = observability_latest_artifact_path(root);
    if let Some(parent) = latest_path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    std::fs::write(
        &latest_path,
        serde_json::to_string_pretty(payload).map_err(|error| error.to_string())? + "\n",
    )
    .map_err(|error| error.to_string())
}

fn append_jsonl_event(path: &Path, payload: &Value) -> LoomResult<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let mut file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|error| error.to_string())?;
    file.write_all(
        serde_json::to_string(payload)
            .map_err(|error| error.to_string())?
            .as_bytes(),
    )
    .map_err(|error| error.to_string())?;
    file.write_all(b"\n").map_err(|error| error.to_string())
}

fn observability_contract_path(root: &Path) -> PathBuf {
    root.join(OBSERVABILITY_CONTRACT_PATH)
}

fn observability_latest_artifact_path(root: &Path) -> PathBuf {
    root.join(OBSERVABILITY_LATEST_ARTIFACT_PATH)
}

fn observability_alert_stream_path(root: &Path) -> PathBuf {
    root.join(OBSERVABILITY_ALERT_STREAM_PATH)
}
