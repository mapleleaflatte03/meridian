use std::io::IsTerminal;

use crate::*;
use loom_core::recurring_executor::{
    list_recurring_runs, render_recurring_run_human, render_recurring_run_json,
    render_recurring_runs_list_human, render_recurring_runs_list_json, show_recurring_run,
};

pub(crate) fn handle_recurring(args: &[String]) -> LoomResult<()> {
    if args.is_empty()
        || matches!(
            args.first().map(String::as_str),
            Some("help" | "--help" | "-h")
        )
    {
        print_recurring_help();
        return Ok(());
    }
    match args.first().map(String::as_str) {
        Some("runs") => handle_recurring_runs(&args[1..]),
        Some("show") => handle_recurring_show(&args[1..]),
        _ => Err("recurring supports: runs, show".to_string()),
    }
}

fn print_recurring_help() {
    println!(
        "Meridian Loom // RECURRING

Inspect recurring job execution runs (schedules and heartbeats).

USAGE: loom recurring <COMMAND> [OPTIONS]

COMMANDS:
  runs [--limit N] [--job-type TYPE]  List recurring run records
  show --run-id ID                    Show details of a specific run

GLOBAL OPTIONS:
  --root ROOT                         Workspace root path
  --format human|json                 Output format (default: human)"
    );
}

fn handle_recurring_runs(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_recurring_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = format_flag(args);
    let limit = take_value(args, "--limit")
        .and_then(|v| v.parse::<usize>().ok())
        .unwrap_or(20);
    let job_type = take_value(args, "--job-type");
    let runs = list_recurring_runs(&root, limit, job_type.as_deref())?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_recurring_runs_list_human(&runs));
        }
        _ => print!("{}", render_recurring_runs_list_json(&runs)),
    }
    Ok(())
}

fn handle_recurring_show(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_recurring_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let run_id = required_flag(args, "--run-id")?;
    let format = format_flag(args);
    let run = show_recurring_run(&root, &run_id)?
        .ok_or_else(|| format!("recurring run '{}' was not found", run_id))?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_recurring_run_human(&run));
        }
        _ => print!("{}", render_recurring_run_json(&run)),
    }
    Ok(())
}

fn format_flag(args: &[String]) -> String {
    take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    })
}
