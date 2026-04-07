use crate::*;

pub(crate) fn run_action_execute_request(
    root: &Path,
    config: &Config,
    agent_id: &str,
    capability_name: Option<&str>,
    mut action_type: String,
    mut resource: String,
    estimated_cost_usd: f64,
    kernel_path: Option<&str>,
    org_id: Option<&str>,
    run_id: Option<&str>,
    session_id: Option<&str>,
    payload_json: Option<&str>,
    format: &str,
) -> LoomResult<()> {
    let identity = resolve_agent_identity(&root, kernel_path, agent_id, org_id)?;
    if let Some(name) = capability_name {
        match find_capability_by_name(&root, config, name)? {
            Some(capability) => {
                if action_type.is_empty() {
                    action_type = capability.action_type;
                }
                if resource.is_empty() {
                    resource = capability.resource;
                }
            }
            None => return Err(format!("capability '{}' not found", name)),
        }
    }
    if action_type.trim().is_empty() || resource.trim().is_empty() {
        return Err(
            "action execute requires --action-type and --resource, or a resolvable --capability"
                .to_string(),
        );
    }

    let envelope = build_action_envelope_with_options(
        &root,
        kernel_path,
        agent_id,
        org_id,
        &action_type,
        &resource,
        estimated_cost_usd,
        run_id,
        session_id,
        capability_name,
        payload_json,
    )?;
    let reference = evaluate_reference_gates(&root, kernel_path, &identity, &envelope)?;
    let decision = capture_decision(&root, &identity, &envelope, &reference)?;
    let effective_kernel_path = kernel_path_for(&root, kernel_path)?;
    let capture = capture_runtime_execution(
        &root,
        &effective_kernel_path,
        &envelope,
        &reference,
        &decision,
    )?;
    if format == "json" {
        print!("{}", render_runtime_execution_json(&capture));
    } else {
        print_human_block(&[
            render_identity_human(&identity),
            render_envelope_human(&envelope),
            render_decision_human(&decision),
            render_runtime_execution_human(&capture),
        ]);
    }
    std::process::exit(decision_exit_code(&decision, 0, 2));
}

pub(crate) fn handle_action(args: &[String]) -> LoomResult<()> {
    match args.first().map(String::as_str) {
        Some("enqueue") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let agent_id = required_flag(args, "--agent-id")?;
            let config = read_config(&root)?;
            let capability_name = take_value(args, "--capability");
            let mut action_type = take_value(args, "--action-type").unwrap_or_default();
            let mut resource = take_value(args, "--resource").unwrap_or_default();
            let payload_json = take_value(args, "--payload-json");
            let estimated_cost_usd = parse_f64_flag(args, "--estimated-cost-usd").unwrap_or(0.0);
            let kernel_path = take_value(args, "--kernel-path");
            let org_id = take_value(args, "--org-id");
            let run_id = take_value(args, "--run-id");
            let session_id = take_value(args, "--session-id");
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            if let Some(name) = capability_name.as_deref() {
                let capability = find_capability_by_name(&root, &config, name)?
                    .ok_or_else(|| format!("capability '{}' not found", name))?;
                if action_type.is_empty() {
                    action_type = capability.action_type;
                }
                if resource.is_empty() {
                    resource = capability.resource;
                }
            }
            if action_type.trim().is_empty() || resource.trim().is_empty() {
                return Err("action enqueue requires --action-type and --resource, or a resolvable --capability".to_string());
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
            let capture = enqueue_action(&root, &effective_kernel_path, &envelope)?;
            if format == "json" {
                print!("{}", render_enqueued_action_json(&capture));
            } else {
                print_human_block(&[
                    render_envelope_human(&envelope),
                    render_enqueued_action_human(&capture),
                ]);
            }
            Ok(())
        }
        Some("execute") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let agent_id = required_flag(args, "--agent-id")?;
            let config = read_config(&root)?;
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
                                requested_via: "action_execute".to_string(),
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
                return Err("action execute requires --action-type and --resource, or a resolvable --capability".to_string());
            }

            let identity = resolve_agent_identity(
                &root,
                kernel_path.as_deref(),
                &agent_id,
                org_id.as_deref(),
            )?;
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
            let reference =
                evaluate_reference_gates(&root, kernel_path.as_deref(), &identity, &envelope)?;
            let decision = capture_decision(&root, &identity, &envelope, &reference)?;
            let effective_kernel_path = kernel_path_for(&root, kernel_path.as_deref())?;
            let capture = capture_runtime_execution(
                &root,
                &effective_kernel_path,
                &envelope,
                &reference,
                &decision,
            )?;
            if format == "json" {
                print!("{}", render_runtime_execution_json(&capture));
            } else {
                print_human_block(&[
                    render_identity_human(&identity),
                    render_envelope_human(&envelope),
                    render_decision_human(&decision),
                    render_runtime_execution_human(&capture),
                ]);
            }
            std::process::exit(decision_exit_code(&decision, 0, 2));
        }
        _ => Err("action supports 'enqueue' and 'execute'".to_string()),
    }
}
