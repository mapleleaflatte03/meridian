use crate::*;

pub(crate) fn handle_supervisor(args: &[String]) -> LoomResult<()> {
    match args.first().map(String::as_str) {
        Some("daemon") => handle_supervisor_daemon(&args[1..]),
        Some("run") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let kernel_path = take_value(args, "--kernel-path");
            let max_jobs = take_value(args, "--max-jobs")
                .and_then(|raw| raw.parse::<usize>().ok())
                .unwrap_or(1);
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let summary = run_supervisor(&root, kernel_path.as_deref(), max_jobs)?;
            if format == "json" {
                print!("{}", render_supervisor_run_json(&summary));
            } else {
                print_human(&render_supervisor_run_human(&summary));
            }
            Ok(())
        }
        Some("watch") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let kernel_path = take_value(args, "--kernel-path");
            let max_jobs = take_value(args, "--max-jobs")
                .and_then(|raw| raw.parse::<usize>().ok())
                .unwrap_or(1);
            let iterations = take_value(args, "--iterations")
                .and_then(|raw| raw.parse::<usize>().ok())
                .unwrap_or(2);
            let poll_seconds = take_value(args, "--poll-seconds")
                .and_then(|raw| raw.parse::<u64>().ok())
                .unwrap_or(1);
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let summary = watch_supervisor(
                &root,
                kernel_path.as_deref(),
                max_jobs,
                iterations,
                poll_seconds,
            )?;
            if format == "json" {
                print!("{}", render_supervisor_watch_json(&summary));
            } else {
                print_human(&render_supervisor_watch_human(&summary));
            }
            Ok(())
        }
        Some("status") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let snapshot = supervisor_status(&root)?;
            if format == "json" {
                print!("{}", render_supervisor_status_json(&snapshot));
            } else {
                print_human(&render_supervisor_status_human(&snapshot));
            }
            Ok(())
        }
        Some("lanes") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            if format == "json" {
                print!("{}", render_supervisor_lanes_json(&root)?);
            } else {
                print_human(&render_supervisor_lanes_human(&root)?);
            }
            Ok(())
        }
        _ => Err("supervisor supports 'run', 'watch', 'status', 'lanes', and 'daemon'".to_string()),
    }
}

pub(crate) fn handle_supervisor_daemon_start(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let kernel_path = take_value(args, "--kernel-path");
    let max_jobs = take_value(args, "--max-jobs")
        .and_then(|raw| raw.parse::<usize>().ok())
        .unwrap_or(1);
    let poll_seconds = take_value(args, "--poll-seconds")
        .and_then(|raw| raw.parse::<u64>().ok())
        .unwrap_or(1);
    let iterations = take_value(args, "--iterations")
        .and_then(|raw| raw.parse::<usize>().ok())
        .unwrap_or(60);
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let supervisor_dir = root.join(".loom/runtime/supervisor");
    std::fs::create_dir_all(&supervisor_dir).map_err(|e| e.to_string())?;
    let stdout_log_path = supervisor_dir.join("daemon.log");
    let stdout = std::fs::File::create(&stdout_log_path).map_err(|e| e.to_string())?;
    let stderr = stdout.try_clone().map_err(|e| e.to_string())?;
    let session_id = format!("daemon-{}", chrono_like_timestamp());
    let exe = env::current_exe().map_err(|e| e.to_string())?;
    let mut command = Command::new(exe);
    command
        .arg("supervisor")
        .arg("daemon")
        .arg("loop")
        .arg("--root")
        .arg(&root)
        .arg("--max-jobs")
        .arg(max_jobs.to_string())
        .arg("--poll-seconds")
        .arg(poll_seconds.to_string())
        .arg("--iterations")
        .arg(iterations.to_string())
        .arg("--session-id")
        .arg(&session_id)
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr));
    if let Some(kernel_path) = kernel_path.as_deref() {
        command.arg("--kernel-path").arg(kernel_path);
    }
    let child = command.spawn().map_err(|e| e.to_string())?;
    let note = format!(
        "daemon start requested; pid={} session_id={} log={}",
        child.id(),
        session_id,
        stdout_log_path.display()
    );
    let fallback_note = note.clone();
    let mut snapshot_result = supervisor_daemon_status(&root);
    for _ in 0..10 {
        if let Ok(snapshot) = &snapshot_result {
            if snapshot.available {
                break;
            }
        }
        std::thread::sleep(std::time::Duration::from_millis(100));
        snapshot_result = supervisor_daemon_status(&root);
    }
    let snapshot = snapshot_result.unwrap_or_else(|_| loom_shadow::SupervisorDaemonSnapshot {
        root: root.clone(),
        supervisor_dir,
        runtime_state_path: root.join(".loom/runtime/supervisor/runtime_state.json"),
        stop_request_path: root.join(".loom/runtime/supervisor/stop.requested"),
        stdout_log_path,
        available: true,
        session_id: session_id.clone(),
        pid: child.id(),
        running: true,
        status: "starting".to_string(),
        updated_at: String::new(),
        booted_at: String::new(),
        stopped_at: String::new(),
        poll_seconds,
        max_jobs,
        max_iterations: iterations,
        iterations_completed: 0,
        processed: 0,
        allowed: 0,
        denied: 0,
        failed: 0,
        pending_jobs: 0,
        processed_jobs: 0,
        failed_jobs: 0,
        heartbeat_entries: 0,
        note: fallback_note,
    });
    if format == "json" {
        print!("{}", render_supervisor_daemon_json(&snapshot));
    } else {
        let mut snapshot = snapshot;
        if snapshot.note.is_empty() {
            snapshot.note = note;
        }
        print_human(&render_supervisor_daemon_human(&snapshot));
    }
    Ok(())
}

pub(crate) fn handle_supervisor_daemon_loop(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let kernel_path = take_value(args, "--kernel-path");
    let max_jobs = take_value(args, "--max-jobs")
        .and_then(|raw| raw.parse::<usize>().ok())
        .unwrap_or(1);
    let poll_seconds = take_value(args, "--poll-seconds")
        .and_then(|raw| raw.parse::<u64>().ok())
        .unwrap_or(1);
    let iterations = take_value(args, "--iterations")
        .and_then(|raw| raw.parse::<usize>().ok())
        .unwrap_or(60);
    let session_id = take_value(args, "--session-id")
        .unwrap_or_else(|| format!("daemon-{}", chrono_like_timestamp()));
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let snapshot = run_supervisor_daemon_loop(
        &root,
        kernel_path.as_deref(),
        max_jobs,
        poll_seconds,
        iterations,
        &session_id,
    )?;
    if format == "json" {
        print!("{}", render_supervisor_daemon_json(&snapshot));
    } else {
        print_human(&render_supervisor_daemon_human(&snapshot));
    }
    Ok(())
}

pub(crate) fn handle_supervisor_daemon_status(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let snapshot = supervisor_daemon_status(&root)?;
    if format == "json" {
        print!("{}", render_supervisor_daemon_json(&snapshot));
    } else {
        print_human(&render_supervisor_daemon_human(&snapshot));
    }
    Ok(())
}

pub(crate) fn handle_supervisor_daemon_stop(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let snapshot = request_supervisor_daemon_stop(&root)?;
    if format == "json" {
        print!("{}", render_supervisor_daemon_json(&snapshot));
    } else {
        print_human(&render_supervisor_daemon_human(&snapshot));
    }
    Ok(())
}

pub(crate) fn handle_supervisor_daemon(args: &[String]) -> LoomResult<()> {
    match args.first().map(String::as_str) {
        Some("start") => handle_supervisor_daemon_start(args),
        Some("loop") => handle_supervisor_daemon_loop(args),
        Some("status") => handle_supervisor_daemon_status(args),
        Some("stop") => handle_supervisor_daemon_stop(args),
        _ => Err("supervisor daemon supports 'start', 'loop', 'status', and 'stop'".to_string()),
    }
}
