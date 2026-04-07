use std::io::IsTerminal;

use crate::*;
use loom_core::recurring::{
    cancel_heartbeat, heartbeat_overview, heartbeat_summary, load_heartbeats, pause_heartbeat,
    render_heartbeat_overview_human, render_heartbeat_overview_json, render_heartbeat_record_human,
    render_heartbeat_record_json, render_heartbeat_run_summary_human,
    render_heartbeat_run_summary_json, run_due_heartbeats, schedule_heartbeat,
    HeartbeatDeliveryTarget, HeartbeatRecord, HeartbeatScheduleRequest,
};
use loom_core::recurring_executor::{
    dispatch_heartbeat_run, render_recurring_run_human, render_recurring_run_json,
};

pub(crate) fn handle_heartbeat(args: &[String]) -> LoomResult<()> {
    if args.is_empty()
        || matches!(
            args.first().map(String::as_str),
            Some("help" | "--help" | "-h")
        )
    {
        print_heartbeat_help();
        return Ok(());
    }
    match args.first().map(String::as_str) {
        Some("status") => handle_heartbeat_status(&args[1..]),
        Some("list") => handle_heartbeat_list(&args[1..]),
        Some("show") => handle_heartbeat_show(&args[1..]),
        Some("schedule") => handle_heartbeat_schedule(&args[1..]),
        Some("pause") => handle_heartbeat_pause(&args[1..]),
        Some("cancel") => handle_heartbeat_cancel(&args[1..]),
        Some("run-due") => handle_heartbeat_run_due(&args[1..]),
        Some("run") => handle_heartbeat_run(&args[1..]),
        _ => Err(
            "heartbeat supports: status, list, show, schedule, pause, cancel, run-due, run"
                .to_string(),
        ),
    }
}

fn print_heartbeat_help() {
    println!(
        "Meridian Loom // HEARTBEAT

Manage recurring heartbeat checks for background agent autonomy.

USAGE: loom heartbeat <COMMAND> [OPTIONS]

COMMANDS:
  status [--now-unix-ms MS]           Heartbeat runtime overview
  list                                List all registered heartbeats
  show --heartbeat-id ID              Show heartbeat details
  schedule --agent-id AGENT           Register a new heartbeat
        --capability CAP
        [--schedule interval]
        [--every-seconds SEC]
  pause --heartbeat-id ID             Pause a heartbeat
  cancel --heartbeat-id ID            Cancel a heartbeat
  run-due [--now-unix-ms MS]          Execute all due heartbeats now
  run --heartbeat-id ID               Execute a specific heartbeat now

GLOBAL OPTIONS:
  --root ROOT                         Workspace root path
  --format human|json                 Output format (default: human)"
    );
}

fn handle_heartbeat_status(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_heartbeat_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let now_unix_ms = take_value(args, "--now-unix-ms")
        .and_then(|raw| raw.parse::<u64>().ok())
        .unwrap_or_else(now_unix_ms);
    let summary = heartbeat_overview(&root, now_unix_ms)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_heartbeat_overview_human(&summary));
        }
        _ => print!("{}", render_heartbeat_overview_json(&summary)),
    }
    Ok(())
}

fn handle_heartbeat_list(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_heartbeat_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let records = load_heartbeats(&root)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_heartbeat_list_human(&records));
        }
        _ => print!("{}", render_heartbeat_list_json(&records)),
    }
    Ok(())
}

fn handle_heartbeat_show(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_heartbeat_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let heartbeat_id = required_flag(args, "--heartbeat-id")?;
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let record = heartbeat_summary(&root, &heartbeat_id)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_heartbeat_record_human(&record));
        }
        _ => print!("{}", render_heartbeat_record_json(&record)),
    }
    Ok(())
}

fn handle_heartbeat_schedule(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_heartbeat_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let agent_id = required_flag(args, "--agent-id")?;
    let capability_name = required_flag(args, "--capability")?;
    let schedule_kind = take_value(args, "--schedule").unwrap_or_else(|| "interval".to_string());
    let every_seconds = take_value(args, "--every-seconds")
        .and_then(|raw| raw.parse::<u64>().ok())
        .unwrap_or(60);
    let jitter_seconds = take_value(args, "--jitter-seconds")
        .and_then(|raw| raw.parse::<u64>().ok())
        .unwrap_or(0);
    let not_before_unix_ms =
        take_value(args, "--not-before-unix-ms").and_then(|raw| raw.parse::<u64>().ok());
    let max_attempts = take_value(args, "--max-attempts")
        .and_then(|raw| raw.parse::<u32>().ok())
        .unwrap_or(1);
    let delivery_target =
        take_value(args, "--delivery-channel").map(|channel_id| HeartbeatDeliveryTarget {
            channel_id,
            recipient: required_flag(args, "--delivery-recipient")
                .unwrap_or_else(|_| "".to_string()),
            allow_receipt_hashes: has_flag(args, "--delivery-allow-receipt-hashes"),
            allow_operator_diagnostics: has_flag(args, "--delivery-allow-operator-diagnostics"),
        });
    let request = HeartbeatScheduleRequest {
        heartbeat_id: take_value(args, "--heartbeat-id"),
        agent_id,
        capability_name,
        schedule_kind,
        schedule_expression: take_value(args, "--expression").unwrap_or_default(),
        timezone: take_value(args, "--timezone").unwrap_or_else(|| "UTC".to_string()),
        every_seconds,
        jitter_seconds,
        not_before_unix_ms,
        payload_json: take_value(args, "--payload-json").unwrap_or_else(|| "{}".to_string()),
        delivery_target,
        max_attempts,
    };
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let result = schedule_heartbeat(&root, &request)?;
    if format == "json" {
        print!("{}", render_heartbeat_record_json(&result.record));
    } else {
        print_startup_banner();
        print_human(&render_heartbeat_record_human(&result.record));
    }
    Ok(())
}

fn handle_heartbeat_pause(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_heartbeat_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let heartbeat_id = required_flag(args, "--heartbeat-id")?;
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let result = pause_heartbeat(&root, &heartbeat_id)?;
    if format == "json" {
        print!("{}", render_heartbeat_record_json(&result.record));
    } else {
        print_startup_banner();
        print_human(&render_heartbeat_record_human(&result.record));
    }
    Ok(())
}

fn handle_heartbeat_cancel(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_heartbeat_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let heartbeat_id = required_flag(args, "--heartbeat-id")?;
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let result = cancel_heartbeat(&root, &heartbeat_id)?;
    if format == "json" {
        print!("{}", render_heartbeat_record_json(&result.record));
    } else {
        print_startup_banner();
        print_human(&render_heartbeat_record_human(&result.record));
    }
    Ok(())
}

fn handle_heartbeat_run_due(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_heartbeat_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let now_unix_ms = take_value(args, "--now-unix-ms")
        .and_then(|raw| raw.parse::<u64>().ok())
        .unwrap_or_else(now_unix_ms);
    let limit = take_value(args, "--limit")
        .and_then(|raw| raw.parse::<usize>().ok())
        .unwrap_or(20);
    let summary = run_due_heartbeats(&root, now_unix_ms, limit)?;
    if format == "json" {
        print!("{}", render_heartbeat_run_summary_json(&summary));
    } else {
        print_startup_banner();
        print_human(&render_heartbeat_run_summary_human(&summary));
    }
    Ok(())
}

fn render_heartbeat_list_human(records: &[HeartbeatRecord]) -> String {
    if records.is_empty() {
        return "heartbeat_count:    0\n".to_string();
    }
    let mut rendered = format!("heartbeat_count:    {}\n", records.len());
    for record in records {
        rendered.push_str(&format!(
            "\n- {} agent={} capability={} schedule={} enabled={} next_fire={}\n",
            record.heartbeat_id,
            record.agent_id,
            record.capability_name,
            record.schedule_kind,
            record.enabled,
            record
                .next_fire_at_unix_ms
                .map(|value| value.to_string())
                .unwrap_or_else(|| "(none)".to_string())
        ));
    }
    rendered
}

fn render_heartbeat_list_json(records: &[HeartbeatRecord]) -> String {
    let rendered = serde_json::to_string_pretty(
        &records
            .iter()
            .map(heartbeat_record_json)
            .collect::<Vec<_>>(),
    )
    .unwrap_or_else(|_| "[]".to_string());
    rendered + "\n"
}

fn heartbeat_record_json(record: &HeartbeatRecord) -> serde_json::Value {
    serde_json::json!({
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
        "delivery_target": record.delivery_target.as_ref().map(|target| serde_json::json!({
            "channel_id": target.channel_id,
            "recipient": target.recipient,
            "allow_receipt_hashes": target.allow_receipt_hashes,
            "allow_operator_diagnostics": target.allow_operator_diagnostics,
        })),
        "enabled": record.enabled,
        "status": record.status,
        "max_attempts": record.max_attempts,
        "run_count": record.run_count,
        "last_fire_at_unix_ms": record.last_fire_at_unix_ms,
        "next_fire_at_unix_ms": record.next_fire_at_unix_ms,
    })
}

fn handle_heartbeat_run(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_heartbeat_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let heartbeat_id = required_flag(args, "--heartbeat-id")?;
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let record = heartbeat_summary(&root, &heartbeat_id)?;
    let run = dispatch_heartbeat_run(&root, &record)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_recurring_run_human(&run));
        }
        _ => print!("{}", render_recurring_run_json(&run)),
    }
    Ok(())
}

fn now_unix_ms() -> u64 {
    use std::time::{SystemTime, UNIX_EPOCH};

    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}
