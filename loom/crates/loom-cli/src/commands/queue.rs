use crate::*;

pub(crate) fn handle_queue(args: &[String]) -> LoomResult<()> {
    match args.first().map(String::as_str) {
        Some("inspect") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let limit = take_value(args, "--limit")
                .and_then(|raw| raw.parse::<usize>().ok())
                .unwrap_or(0);
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let records = inspect_pending_queue(&root, limit)?;
            if format == "json" {
                print!("{}", render_queue_inspect_json(&root, &records, limit));
            } else {
                print_human(&render_queue_inspect_human(&root, &records, limit));
            }
            Ok(())
        }
        Some("consume") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let kernel_path = take_value(args, "--kernel-path");
            let max_jobs = take_value(args, "--max-jobs")
                .and_then(|raw| raw.parse::<usize>().ok())
                .unwrap_or(1);
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let summary = consume_pending_queue(&root, kernel_path.as_deref(), max_jobs)?;
            if format == "json" {
                print!("{}", render_queue_consume_json(&summary));
            } else {
                print_human(&render_queue_consume_human(&summary));
            }
            Ok(())
        }
        Some("run-once") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let kernel_path = take_value(args, "--kernel-path");
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let summary = run_queue_once(&root, kernel_path.as_deref())?;
            if format == "json" {
                print!("{}", render_queue_run_once_json(&summary));
            } else {
                print_human(&render_queue_run_once_human(&summary));
            }
            Ok(())
        }
        Some("run-until-empty") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let kernel_path = take_value(args, "--kernel-path");
            let max_jobs = take_value(args, "--max-jobs")
                .and_then(|raw| raw.parse::<usize>().ok())
                .unwrap_or(1);
            let max_passes = take_value(args, "--max-passes")
                .and_then(|raw| raw.parse::<usize>().ok())
                .unwrap_or(25);
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let summary = run_queue_until_empty(&root, kernel_path.as_deref(), max_jobs, max_passes)?;
            if format == "json" {
                print!("{}", render_queue_run_until_empty_json(&summary));
            } else {
                print_human(&render_queue_run_until_empty_human(&summary));
            }
            Ok(())
        }
        Some("status") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let snapshot = queue_status(&root)?;
            if format == "json" {
                print!("{}", render_queue_status_json(&snapshot));
            } else {
                print_human(&render_queue_status_human(&snapshot));
            }
            Ok(())
        }
        Some("ack") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let job_id = required_flag(args, "--job-id")?;
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let capture = ack_queue_job(&root, &job_id)?;
            if format == "json" {
                print!("{}", render_queue_ack_json(&capture));
            } else {
                print_human(&render_queue_ack_human(&capture));
            }
            Ok(())
        }
        _ => Err("queue supports 'inspect', 'consume', 'run-once', 'run-until-empty', 'status', and 'ack'".to_string()),
    }
}
