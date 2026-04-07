use std::io::IsTerminal;

use crate::*;
use loom_core::recurring_executor::{
    dispatch_schedule_run, render_recurring_run_human, render_recurring_run_json,
};
use loom_core::schedules::{
    add_schedule, cancel_schedule, load_schedules, pause_schedule, render_schedule_overview_human,
    render_schedule_overview_json, render_schedule_record_human, render_schedule_record_json,
    render_schedule_run_summary_human, render_schedule_run_summary_json, run_due_schedules,
    schedule_overview, schedule_summary, ScheduleDeliveryTarget, ScheduleRequest,
    ScheduledJobRecord,
};

pub(crate) fn handle_schedule(args: &[String]) -> LoomResult<()> {
    if args.is_empty()
        || matches!(
            args.first().map(String::as_str),
            Some("help" | "--help" | "-h")
        )
    {
        print_schedule_help();
        return Ok(());
    }
    match args.first().map(String::as_str) {
        Some("status") => handle_schedule_status(&args[1..]),
        Some("list") => handle_schedule_list(&args[1..]),
        Some("show") => handle_schedule_show(&args[1..]),
        Some("add") => handle_schedule_add(&args[1..]),
        Some("pause") => handle_schedule_pause(&args[1..]),
        Some("cancel") => handle_schedule_cancel(&args[1..]),
        Some("run-due") => handle_schedule_run_due(&args[1..]),
        Some("run") => handle_schedule_run(&args[1..]),
        _ => Err(
            "schedule supports: status, list, show, add, pause, cancel, run-due, run".to_string(),
        ),
    }
}

fn print_schedule_help() {
    println!(
        "Meridian Loom // SCHEDULE

Manage scheduled recurring jobs.

USAGE: loom schedule <COMMAND> [OPTIONS]

COMMANDS:
  status                              Schedule runtime overview
  list                                List all scheduled jobs
  show --job-id ID                    Show schedule details
  add --agent-id AGENT                Create a new schedule
        --job-kind KIND
        [--schedule daily|interval]
        [--expression EXPR]
        [--every-seconds SEC]
        [--timezone TZ]
  pause --job-id ID                   Pause a scheduled job
  cancel --job-id ID                  Cancel a scheduled job
  run-due                             Execute all due schedules now
  run --job-id ID                     Execute a specific schedule now

GLOBAL OPTIONS:
  --root ROOT                         Workspace root path
  --format human|json                 Output format (default: human)"
    );
}

fn handle_schedule_status(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_schedule_help();
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
    let summary = schedule_overview(&root, now_unix_ms)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_schedule_overview_human(&summary));
        }
        _ => print!("{}", render_schedule_overview_json(&summary)),
    }
    Ok(())
}

fn handle_schedule_list(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_schedule_help();
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
    let records = load_schedules(&root)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_schedule_list_human(&records));
        }
        _ => print!("{}", render_schedule_list_json(&records)),
    }
    Ok(())
}

fn handle_schedule_show(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_schedule_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let job_id = required_flag(args, "--job-id")?;
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let record = schedule_summary(&root, &job_id)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_schedule_record_human(&record));
        }
        _ => print!("{}", render_schedule_record_json(&record)),
    }
    Ok(())
}

fn handle_schedule_add(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_schedule_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let request = ScheduleRequest {
        job_id: take_value(args, "--job-id"),
        agent_id: required_flag(args, "--agent-id")?,
        job_kind: required_flag(args, "--job-kind")?,
        schedule_kind: take_value(args, "--schedule").unwrap_or_else(|| "daily".to_string()),
        schedule_expression: take_value(args, "--expression").unwrap_or_default(),
        timezone: take_value(args, "--timezone").unwrap_or_else(|| "UTC".to_string()),
        every_seconds: take_value(args, "--every-seconds")
            .and_then(|raw| raw.parse::<u64>().ok())
            .unwrap_or(0),
        not_before_unix_ms: take_value(args, "--not-before-unix-ms")
            .and_then(|raw| raw.parse::<u64>().ok()),
        payload_json: take_value(args, "--payload-json").unwrap_or_else(|| "{}".to_string()),
        delivery_target: take_value(args, "--delivery-channel").map(|channel_id| {
            ScheduleDeliveryTarget {
                channel_id,
                recipient: required_flag(args, "--delivery-recipient")
                    .unwrap_or_else(|_| "".to_string()),
                allow_receipt_hashes: has_flag(args, "--delivery-allow-receipt-hashes"),
                allow_operator_diagnostics: has_flag(args, "--delivery-allow-operator-diagnostics"),
            }
        }),
        max_attempts: take_value(args, "--max-attempts")
            .and_then(|raw| raw.parse::<u32>().ok())
            .unwrap_or(1),
        source_kind: take_value(args, "--source-kind").unwrap_or_else(|| "manual".to_string()),
    };
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let result = add_schedule(&root, &request)?;
    if format == "json" {
        print!("{}", render_schedule_record_json(&result.record));
    } else {
        print_startup_banner();
        print_human(&render_schedule_record_human(&result.record));
    }
    Ok(())
}

fn handle_schedule_pause(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_schedule_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let job_id = required_flag(args, "--job-id")?;
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let result = pause_schedule(&root, &job_id)?;
    if format == "json" {
        print!("{}", render_schedule_record_json(&result.record));
    } else {
        print_startup_banner();
        print_human(&render_schedule_record_human(&result.record));
    }
    Ok(())
}

fn handle_schedule_cancel(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_schedule_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let job_id = required_flag(args, "--job-id")?;
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let result = cancel_schedule(&root, &job_id)?;
    if format == "json" {
        print!("{}", render_schedule_record_json(&result.record));
    } else {
        print_startup_banner();
        print_human(&render_schedule_record_human(&result.record));
    }
    Ok(())
}

fn handle_schedule_run_due(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_schedule_help();
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
    let summary = run_due_schedules(&root, now_unix_ms, limit)?;
    if format == "json" {
        print!("{}", render_schedule_run_summary_json(&summary));
    } else {
        print_startup_banner();
        print_human(&render_schedule_run_summary_human(&summary));
    }
    Ok(())
}

fn render_schedule_list_human(records: &[ScheduledJobRecord]) -> String {
    if records.is_empty() {
        return "schedule_count:     0\n".to_string();
    }
    let mut rendered = format!("schedule_count:     {}\n", records.len());
    for record in records {
        rendered.push_str(&format!(
            "\n- {} agent={} job_kind={} schedule={} enabled={} next_fire={}\n",
            record.job_id,
            record.agent_id,
            record.job_kind,
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

fn render_schedule_list_json(records: &[ScheduledJobRecord]) -> String {
    let rendered = serde_json::to_string_pretty(
        &records
            .iter()
            .map(|record| {
                serde_json::json!({
                    "job_id": record.job_id,
                    "agent_id": record.agent_id,
                    "job_kind": record.job_kind,
                    "schedule_kind": record.schedule_kind,
                    "enabled": record.enabled,
                    "status": record.status,
                    "next_fire_at_unix_ms": record.next_fire_at_unix_ms,
                })
            })
            .collect::<Vec<_>>(),
    )
    .unwrap_or_else(|_| "[]".to_string());
    rendered + "\n"
}

fn handle_schedule_run(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_schedule_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let job_id = required_flag(args, "--job-id")?;
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let record = schedule_summary(&root, &job_id)?;
    let run = dispatch_schedule_run(&root, &record)?;
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
