use crate::*;

pub(crate) fn handle_start(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_start_help();
        return Ok(());
    }
    start_service_with_mode(args)
}

pub(crate) fn handle_stop(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_stop_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let socket_path = take_value(args, "--socket");
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let snapshot = request_runtime_service_stop(&root, socket_path.as_deref())?;
    if format == "json" {
        print!("{}", render_runtime_service_json(&snapshot));
    } else {
        print_human(&render_runtime_service_human(&snapshot));
    }
    Ok(())
}

pub(crate) fn handle_restart(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_restart_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let socket_path = take_value(args, "--socket");
    let status = runtime_service_status(&root, socket_path.as_deref())?;
    if status.running {
        let _ = request_runtime_service_stop(&root, socket_path.as_deref())?;
        for _ in 0..40 {
            let snapshot = runtime_service_status(&root, socket_path.as_deref())?;
            if !snapshot.running {
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(100));
        }
    }
    start_service_with_mode(args)
}

pub(crate) fn handle_logs(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_logs_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let lines = take_value(args, "--lines")
        .and_then(|raw| raw.parse::<usize>().ok())
        .unwrap_or(100);
    let follow = has_flag(args, "--follow");
    let config = read_config(&root)?;
    let log_path = root.join(&config.log_dir).join("service.log");
    if !log_path.exists() {
        return Err(format!(
            "service log not found at {}; start the runtime service first",
            log_path.display()
        ));
    }
    print_human(&format!(
        "Meridian Loom // LOGS\n=====================\npath:        {}\nmode:        {}\nlines:       {}\n\n",
        log_path.display(),
        if follow { "follow" } else { "tail" },
        lines,
    ));
    let mut offset = print_last_lines(&log_path, lines)?;
    if follow {
        loop {
            std::thread::sleep(std::time::Duration::from_millis(500));
            offset = print_new_bytes(&log_path, offset)?;
        }
    }
    Ok(())
}

pub(crate) fn handle_service(args: &[String]) -> LoomResult<()> {
    if args.is_empty()
        || matches!(
            args.first().map(String::as_str),
            Some("help" | "--help" | "-h")
        )
    {
        print_service_help();
        return Ok(());
    }
    match args.first().map(String::as_str) {
        Some("start") => start_service_with_mode(&args[1..]),
        Some("loop") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let kernel_path = take_value(args, "--kernel-path");
            let socket_path = take_value(args, "--socket");
            let http_address = take_value(args, "--http-address");
            let service_token = take_value(args, "--service-token");
            let commitments_source = take_value(args, "--commitments-source");
            let workspace_token = take_value(args, "--workspace-token");
            let max_jobs = take_value(args, "--max-jobs")
                .and_then(|raw| raw.parse::<usize>().ok())
                .unwrap_or(1);
            let poll_seconds = take_value(args, "--poll-seconds")
                .and_then(|raw| raw.parse::<u64>().ok())
                .unwrap_or(1);
            let iterations = take_value(args, "--iterations")
                .and_then(|raw| raw.parse::<usize>().ok())
                .unwrap_or(120);
            let session_id =
                take_value(args, "--session-id").unwrap_or_else(|| format!("service-{}", chrono_like_timestamp()));
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let snapshot = run_runtime_service_loop(
                &root,
                kernel_path.as_deref(),
                socket_path.as_deref(),
                http_address.as_deref(),
                service_token.as_deref(),
                commitments_source.as_deref(),
                workspace_token.as_deref(),
                max_jobs,
                poll_seconds,
                iterations,
                &session_id,
            )?;
            if format == "json" {
                print!("{}", render_runtime_service_json(&snapshot));
            } else {
                print_human(&render_runtime_service_human(&snapshot));
            }
            Ok(())
        }
        Some("status") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let socket_path = take_value(args, "--socket");
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let snapshot = runtime_service_status(&root, socket_path.as_deref())?;
            if format == "json" {
                print!("{}", render_runtime_service_json(&snapshot));
            } else {
                print_human(&render_runtime_service_human(&snapshot));
            }
            Ok(())
        }
        Some("stop") => handle_stop(&args[1..]),
        Some("cancel") => handle_service_cancel(&args[1..]),
        Some("submit") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let config = read_config(&root)?;
            let agent_id = required_flag(args, "--agent-id")?;
            let capability_name = take_value(args, "--capability");
            let gap_class = take_value(args, "--gap-class").unwrap_or_default();
            let gap_goal = take_value(args, "--goal").unwrap_or_default();
            let mut action_type = take_value(args, "--action-type").unwrap_or_default();
            let mut resource = take_value(args, "--resource").unwrap_or_default();
            let payload_json = take_value(args, "--payload-json");
            let estimated_cost_usd = parse_f64_flag(args, "--estimated-cost-usd").unwrap_or(0.0);
            let kernel_path = take_value(args, "--kernel-path");
            let org_id = take_value(args, "--org-id");
            let run_id = take_value(args, "--run-id");
            let session_id = take_value(args, "--session-id");
            let socket_path = take_value(args, "--socket");
            let http_url = take_value(args, "--http-url");
            let service_token = effective_service_token(&config, take_value(args, "--service-token"))?;
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            if let Some(name) = capability_name.as_deref() {
                match find_capability_by_name(&root, &config, name)? {
                    Some(capability) => {
                        if action_type.is_empty() {
                            action_type = capability.action_type;
                        }
                        if resource.is_empty() {
                            resource = capability.resource;
                        }
                    }
                    None if !gap_class.is_empty() => {
                        let gap = record_capability_gap(
                            &root,
                            &config,
                            &CapabilityGapRequest {
                                requested_via: "service_submit".to_string(),
                                capability_name: name.to_string(),
                                gap_class,
                                goal: gap_goal,
                                proposed_capability_name: name.to_string(),
                                agent_id: agent_id.clone(),
                                org_id: org_id.clone().unwrap_or_else(|| config.org_id.clone()),
                                request_id: String::new(),
                                kernel_path: kernel_path.clone().unwrap_or_default(),
                                action_type: action_type.clone(),
                                resource: resource.clone(),
                                payload_json: payload_json.clone().unwrap_or_default(),
                                run_id: run_id.clone().unwrap_or_default(),
                                session_id: session_id.clone().unwrap_or_default(),
                                original_request_json: String::new(),
                            },
                        )?;
                        if format == "json" {
                            print!("{}", render_capability_gap_json(&gap));
                        } else {
                            print_human(&render_capability_gap_human(&gap));
                        }
                        return Ok(());
                    }
                    None => return Err(format!("capability '{}' not found", name)),
                }
            }
            if action_type.trim().is_empty() || resource.trim().is_empty() {
                return Err("service submit requires --action-type and --resource, or a resolvable --capability".to_string());
            }

            let envelope = build_action_envelope_with_options(
                &root,
                kernel_path.as_deref(),
                &agent_id,
                org_id.as_deref(),
                &action_type,
                &resource,
                estimated_cost_usd,
                run_id.as_deref(),
                session_id.as_deref(),
                capability_name.as_deref(),
                payload_json.as_deref(),
            )?;
            let effective_kernel_path = kernel_path_for(&root, kernel_path.as_deref())?;
            let capture = submit_runtime_service_action(
                &root,
                socket_path.as_deref(),
                http_url.as_deref(),
                service_token.as_deref(),
                &effective_kernel_path,
                &envelope,
            )?;
            if format == "json" {
                print!("{}", render_runtime_service_submit_json(&capture));
            } else {
                print_human_block(&[
                    render_envelope_human(&envelope),
                    render_runtime_service_submit_human(&capture),
                ]);
            }
            Ok(())
        }
        Some("pipeline") => handle_service_pipeline(&args[1..]),
        Some("import-commitments") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let kernel_path = take_value(args, "--kernel-path");
            let commitments_source = required_flag(args, "--commitments-source")?;
            let workspace_token = take_value(args, "--workspace-token");
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let capture = import_commitment_execution_requests(
                &root,
                kernel_path.as_deref(),
                &commitments_source,
                workspace_token.as_deref(),
            )?;
            if format == "json" {
                print!("{}", render_runtime_service_import_json(&capture));
            } else {
                print_human(&render_runtime_service_import_human(&capture));
            }
            Ok(())
        }
        _ => Err("service supports 'start', 'loop', 'status', 'submit', 'cancel', 'pipeline', 'import-commitments', and 'stop'".to_string()),
    }
}

fn handle_service_cancel(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_service_cancel_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let config = read_config(&root)?;
    let socket_path = take_value(args, "--socket");
    let http_url = take_value(args, "--http-url");
    let service_token = effective_service_token(&config, take_value(args, "--service-token"))?;
    let job_id = required_flag(args, "--job-id")?;
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let capture = request_runtime_service_cancel(
        &root,
        socket_path.as_deref(),
        http_url.as_deref(),
        service_token.as_deref(),
        &job_id,
    )?;
    if format == "json" {
        print!("{}", render_runtime_service_cancel_json(&capture));
    } else {
        print_human(&render_runtime_service_cancel_human(&capture));
    }
    Ok(())
}

fn handle_service_pipeline(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::IsTerminal::is_terminal(&std::io::stdout()) {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    if let Some(pipeline_id) = take_value(args, "--pipeline-id") {
        let run = loom_core::pipeline::show_pipeline_run(&root, &pipeline_id)?
            .ok_or_else(|| format!("pipeline run '{}' was not found", pipeline_id))?;
        match format.as_str() {
            "human" => {
                print_startup_banner();
                print_human(&loom_core::pipeline::render_pipeline_run_human(&run));
            }
            _ => print!("{}", loom_core::pipeline::render_pipeline_run_json(&run)),
        }
        return Ok(());
    }
    let limit = take_value(args, "--limit")
        .and_then(|v| v.parse::<usize>().ok())
        .unwrap_or(20);
    let runs = loom_core::pipeline::list_pipeline_runs(&root, limit)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&loom_core::pipeline::render_pipeline_runs_list_human(&runs));
        }
        _ => print!(
            "{}",
            loom_core::pipeline::render_pipeline_runs_list_json(&runs)
        ),
    }
    Ok(())
}

pub(crate) fn start_service_with_mode(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let config = read_config(&root)?;
    let kernel_path = take_value(args, "--kernel-path");
    let socket_path = take_value(args, "--socket");
    let http_address = if has_flag(args, "--no-http") {
        None
    } else {
        take_value(args, "--http-address").or_else(|| {
            let value = config.service_http_address.trim();
            if value.is_empty() {
                None
            } else {
                Some(value.to_string())
            }
        })
    };
    let service_token = effective_service_token(&config, take_value(args, "--service-token"))?;
    if http_address.is_some()
        && service_token
            .as_deref()
            .map(|value| value.trim().is_empty())
            .unwrap_or(true)
    {
        return Err(
            "service-token is required when the local HTTP control plane is enabled".to_string(),
        );
    }
    let commitments_source = take_value(args, "--commitments-source");
    let workspace_token = take_value(args, "--workspace-token");
    let max_jobs = take_value(args, "--max-jobs")
        .and_then(|raw| raw.parse::<usize>().ok())
        .unwrap_or(config.service_max_jobs);
    let poll_seconds = take_value(args, "--poll-seconds")
        .and_then(|raw| raw.parse::<u64>().ok())
        .unwrap_or(config.service_poll_seconds);
    let iterations = take_value(args, "--iterations")
        .and_then(|raw| raw.parse::<usize>().ok())
        .unwrap_or(config.service_max_iterations);
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let foreground = has_flag(args, "--foreground");
    let current = runtime_service_status(&root, socket_path.as_deref())?;
    if current.running {
        if format == "json" {
            print!("{}", render_runtime_service_json(&current));
        } else {
            print_human(&render_runtime_service_human(&current));
        }
        return Ok(());
    }

    if foreground {
        let session_id = format!("service-{}", chrono_like_timestamp());
        let snapshot = run_runtime_service_loop(
            &root,
            kernel_path.as_deref(),
            socket_path.as_deref(),
            http_address.as_deref(),
            service_token.as_deref(),
            commitments_source.as_deref(),
            workspace_token.as_deref(),
            max_jobs,
            poll_seconds,
            if iterations == 0 {
                usize::MAX
            } else {
                iterations
            },
            &session_id,
        )?;
        if format == "json" {
            print!("{}", render_runtime_service_json(&snapshot));
        } else {
            print_human(&render_runtime_service_human(&snapshot));
        }
        return Ok(());
    }

    let service_dir = root.join(&config.run_dir).join("service");
    std::fs::create_dir_all(&service_dir).map_err(|e| e.to_string())?;
    let log_dir = root.join(&config.log_dir);
    std::fs::create_dir_all(&log_dir).map_err(|e| e.to_string())?;
    let stdout_log_path = log_dir.join("service.log");
    rotate_log_file_if_needed(&stdout_log_path, config.log_max_bytes, config.log_max_files)?;
    let stdout = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&stdout_log_path)
        .map_err(|e| e.to_string())?;
    set_private_permissions_if_supported(&stdout_log_path, 0o600)?;
    let stderr = stdout.try_clone().map_err(|e| e.to_string())?;
    let session_id = format!("service-{}", chrono_like_timestamp());
    let exe = env::current_exe().map_err(|e| e.to_string())?;
    let mut command = Command::new(exe);
    command
        .arg("service")
        .arg("loop")
        .arg("--root")
        .arg(&root)
        .arg("--max-jobs")
        .arg(max_jobs.to_string())
        .arg("--poll-seconds")
        .arg(poll_seconds.to_string())
        .arg("--iterations")
        .arg(if iterations == 0 {
            usize::MAX.to_string()
        } else {
            iterations.to_string()
        })
        .arg("--session-id")
        .arg(&session_id)
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr));
    if let Some(kernel_path) = kernel_path.as_deref() {
        command.arg("--kernel-path").arg(kernel_path);
    }
    if let Some(socket_path) = socket_path.as_deref() {
        command.arg("--socket").arg(socket_path);
    }
    if let Some(http_address) = http_address.as_deref() {
        command.arg("--http-address").arg(http_address);
    }
    if let Some(service_token) = service_token.as_deref() {
        command.arg("--service-token").arg(service_token);
    }
    if let Some(commitments_source) = commitments_source.as_deref() {
        command.arg("--commitments-source").arg(commitments_source);
    }
    if let Some(workspace_token) = workspace_token.as_deref() {
        command.arg("--workspace-token").arg(workspace_token);
    }
    let mut child = command.spawn().map_err(|e| e.to_string())?;
    let note = format!(
        "runtime service start requested; pid={} session_id={} log={}",
        child.id(),
        session_id,
        stdout_log_path.display()
    );
    let mut snapshot_result = runtime_service_status(&root, socket_path.as_deref());
    let mut early_exit = None;
    for _ in 0..30 {
        if let Ok(snapshot) = &snapshot_result {
            if snapshot.available && snapshot.running && snapshot.session_id == session_id {
                break;
            }
        }
        if let Some(status) = child.try_wait().map_err(|e| e.to_string())? {
            early_exit = Some(status);
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(100));
        snapshot_result = runtime_service_status(&root, socket_path.as_deref());
    }
    if let Some(status) = early_exit {
        return Err(format!(
            "runtime service exited before becoming healthy (session_id={} status={})",
            session_id, status
        ));
    }
    let mut snapshot = snapshot_result.unwrap_or_else(|_| current);
    if snapshot.note.is_empty() {
        snapshot.note = note;
    }
    if format == "json" {
        print!("{}", render_runtime_service_json(&snapshot));
    } else {
        print_human(&render_runtime_service_human(&snapshot));
    }
    Ok(())
}

pub(crate) fn effective_service_token(
    config: &loom_core::Config,
    explicit: Option<String>,
) -> LoomResult<Option<String>> {
    if let Some(explicit) = explicit {
        return Ok(Some(explicit));
    }
    if config.service_token_env.trim().is_empty() {
        return Ok(None);
    }
    Ok(env::var(&config.service_token_env)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty()))
}

pub(crate) fn print_start_help() {
    print_human(
        "Meridian Loom // START HELP\n\
=============================\n\
usage: loom start [--root PATH] [--kernel-path PATH] [--http-address HOST:PORT] [--service-token TOKEN] [--max-jobs N] [--poll-seconds N] [--iterations N] [--foreground] [--format human|json]\n\
\n\
notes:\n\
  - starts the local-first runtime service for a single host\n\
  - background mode writes logs to <root>/logs/service.log\n\
  - foreground mode keeps the service attached to the current terminal\n\
  - --service-token is required whenever the HTTP control plane is enabled\n",
    );
}

pub(crate) fn print_stop_help() {
    print_human(
        "Meridian Loom // STOP HELP\n\
============================\n\
usage: loom stop [--root PATH] [--socket PATH] [--format human|json]\n\
\n\
notes:\n\
  - requests a clean local service shutdown\n\
  - safe to run repeatedly; duplicate stop requests are treated as idempotent local lifecycle operations\n",
    );
}

pub(crate) fn print_restart_help() {
    print_human(
        "Meridian Loom // RESTART HELP\n\
===============================\n\
usage: loom restart [--root PATH] [--kernel-path PATH] [--http-address HOST:PORT] [--service-token TOKEN] [--max-jobs N] [--poll-seconds N] [--iterations N] [--foreground] [--format human|json]\n\
\n\
notes:\n\
  - stops the current local service if it is running\n\
  - starts a new local service session for the same runtime root\n",
    );
}

pub(crate) fn print_service_cancel_help() {
    print_human(
        "Meridian Loom // SERVICE CANCEL HELP\n\
======================================\n\
usage: loom service cancel --job-id ID [--root PATH] [--socket PATH] [--http-url URL] [--service-token TOKEN] [--format human|json]\n\
\n\
notes:\n\
  - requests cancellation for a queued or in-flight runtime job\n\
  - returns truthful state: cancelled, not_cancelable, or not_found\n\
  - safe cancellation depends on the runtime service queue state\n",
    );
}

pub(crate) fn print_logs_help() {
    print_human(
        "Meridian Loom // LOGS HELP\n\
============================\n\
usage: loom logs [--root PATH] [--lines N] [--follow]\n\
\n\
notes:\n\
  - tails <root>/logs/service.log\n\
  - use --follow for a streaming local operator view\n",
    );
}

pub(crate) fn print_service_help() {
    print_human(
        "Meridian Loom // SERVICE HELP\n\
===============================\n\
usage:\n\
  loom service start [--root PATH] [--kernel-path PATH] [--socket PATH] [--http-address HOST:PORT] [--service-token TOKEN] [--commitments-source PATH|URL] [--workspace-token TOKEN] [--max-jobs N] [--poll-seconds N] [--iterations N] [--foreground] [--format human|json]\n\
  loom service status [--root PATH] [--socket PATH] [--format human|json]\n\
  loom service submit --agent-id ID [--capability NAME] [--action-type TYPE] [--resource RESOURCE] [--payload-json JSON] [--estimated-cost-usd USD] [--run-id ID] [--session-id ID] [--org-id ORG] [--kernel-path PATH] [--root PATH] [--socket PATH] [--http-url URL] [--service-token TOKEN] [--format human|json]\n\
  loom service cancel --job-id ID [--root PATH] [--socket PATH] [--http-url URL] [--service-token TOKEN] [--format human|json]\n\
  loom service import-commitments --root PATH --commitments-source PATH|URL [--kernel-path PATH] [--workspace-token TOKEN] [--format human|json]\n\
  loom service stop [--root PATH] [--socket PATH] [--format human|json]\n\
\n\
http surface:\n\
  GET  /status\n\
  GET  /health\n\
  GET  /metrics\n\
  GET  /config\n\
  GET  /jobs/<id>\n\
  POST /submit\n\
  POST /cancel\n\
  POST /import-commitments\n\
  POST /stop\n\
  POST /mcp/tools/list\n\
  POST /mcp/tools/call\n\
  GET  /.well-known/agent.json\n",
    );
}
