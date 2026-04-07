use crate::*;

pub(crate) fn handle_capability(args: &[String]) -> LoomResult<()> {
    if args.is_empty() || has_flag(args, "--help") || has_flag(args, "-h") {
        print_capability_help();
        return Ok(());
    }
    match args.first().map(String::as_str) {
        Some("list") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let config = read_config(&root)?;
            let registry = load_capability_registry(&root, &config)?;
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            if format == "json" {
                print!("{}", render_capability_registry_json(&registry));
            } else {
                print_human(&render_capability_registry_human(&root, &config, &registry));
            }
            Ok(())
        }
        Some("show") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let config = read_config(&root)?;
            let name = required_flag(args, "--name")?;
            let capability = find_capability_by_name(&root, &config, &name)?
                .ok_or_else(|| format!("capability '{}' not found", name))?;
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            if format == "json" {
                print!("{}", render_capability_show_json(&root, &capability)?);
            } else {
                print_human_block(&[
                    render_capability_human(&capability),
                    render_capability_evidence_human(&root, &capability),
                ]);
            }
            Ok(())
        }
        Some("scaffold") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let config = read_config(&root)?;
            let request = CapabilityScaffoldRequest {
                name: required_flag(args, "--name")?,
                description: take_value(args, "--description").unwrap_or_default(),
                action_type: required_flag(args, "--action-type")?,
                resource: required_flag(args, "--resource")?,
                worker_kind: take_value(args, "--worker-kind")
                    .unwrap_or_else(|| "python".to_string()),
                worker_entry: take_value(args, "--worker-entry").unwrap_or_default(),
                wasm_module: take_value(args, "--wasm-module").unwrap_or_default(),
                payload_mode: take_value(args, "--payload-mode")
                    .unwrap_or_else(|| "json".to_string()),
            };
            let result = scaffold_capability(&root, &config, &request)?;
            print_human(&format!(
                "Meridian Loom // CAPABILITY SCAFFOLD\n====================================\nmanifest:     {}\nworker_path:  {}\nname:         {}\nworker_kind:  {}\naction_type:  {}\nresource:     {}\nnote:         capability scaffolded into the local runtime root\n",
                result.manifest_path.display(),
                result.worker_path
                    .as_ref()
                    .map(|path| path.display().to_string())
                    .unwrap_or_else(|| "(none)".to_string()),
                result.capability.name,
                result.capability.worker_kind,
                result.capability.action_type,
                result.capability.resource,
            ));
            Ok(())
        }
        Some("forge") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let config = read_config(&root)?;
            let gap_id = take_value(args, "--gap-id");
            let (gap_class, goal, name) = if let Some(ref gap_id) = gap_id {
                let gap = load_capability_gap(&root, &config, gap_id)?;
                (
                    gap.gap_class.clone(),
                    gap.goal.clone(),
                    gap.proposed_capability_name.clone(),
                )
            } else {
                let gap_class = take_value(args, "--gap-class").unwrap_or_default();
                let goal = take_value(args, "--goal").unwrap_or_default();
                let name = forge_name_from_args(args, &gap_class, &goal)?;
                (gap_class, goal, name)
            };
            let request = CapabilityForgeRequest {
                name,
                description: take_value(args, "--description").unwrap_or_default(),
                template: take_value(args, "--template").unwrap_or_default(),
                gap_class,
                goal,
            };
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let result = forge_capability(&root, &config, &request)?;
            let gap_update = if let Some(gap_id) = gap_id.as_deref() {
                Some(update_capability_gap_forge(
                    &root,
                    &config,
                    gap_id,
                    &result.manifest_path,
                    "gap candidate forged into Loom capability runtime",
                )?)
            } else {
                None
            };
            if format == "json" {
                if let Some(gap_update) = gap_update {
                    print!(
                        "{{\"forge\":{},\"gap\":{}}}\n",
                        render_capability_forge_json(&result).trim(),
                        render_capability_gap_json(&gap_update).trim()
                    );
                } else {
                    print!("{}", render_capability_forge_json(&result));
                }
            } else {
                if let Some(gap_update) = gap_update {
                    print_human_block(&[
                        render_capability_forge_human(&result),
                        render_capability_gap_human(&gap_update),
                    ]);
                } else {
                    print_human(&render_capability_forge_human(&result));
                }
            }
            Ok(())
        }
        Some("import-workspace-skill") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let config = read_config(&root)?;
            let skill_root = PathBuf::from(required_flag(args, "--skill-root")?);
            let capability_name = take_value(args, "--name");
            let entrypoint = take_value(args, "--entrypoint");
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let result = import_workspace_skill(
                &root,
                &config,
                &skill_root,
                entrypoint.as_deref(),
                capability_name.as_deref(),
            )?;
            if format == "json" {
                print!("{}", render_capability_import_json(&result));
            } else {
                print_human(&render_capability_import_human(&result));
            }
            Ok(())
        }
        Some("import-legacy-v1-plugin-skill-subset") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let config = read_config(&root)?;
            let plugin_root = PathBuf::from(required_flag(args, "--plugin-root")?);
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let result = import_legacy_v1_plugin_skill_subset(&root, &config, &plugin_root)?;
            if format == "json" {
                print!("{}", render_legacy_v1_plugin_import_json(&result));
            } else {
                print_human(&render_legacy_v1_plugin_import_human(&result));
            }
            Ok(())
        }
        Some("verify") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let config = read_config(&root)?;
            let name = required_flag(args, "--name")?;
            let agent_id = required_flag(args, "--agent-id")?;
            let kernel_path = take_value(args, "--kernel-path");
            let org_id = take_value(args, "--org-id");
            let payload_json = take_value(args, "--payload-json");
            let estimated_cost_usd = parse_f64_flag(args, "--estimated-cost-usd").unwrap_or(0.0);
            let expect_summary_contains = take_value(args, "--expect-summary-contains");
            let expect_result_fields = take_values(args, "--expect-result-field");
            let gap_id = take_value(args, "--gap-id");
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let capability = find_capability_by_name(&root, &config, &name)?
                .ok_or_else(|| format!("capability '{}' not found", name))?;
            let identity =
                resolve_agent_identity(&root, kernel_path.as_deref(), &agent_id, org_id.as_deref())?;
            let envelope = build_action_envelope_with_options(
                &root,
                kernel_path.as_deref(),
                &agent_id,
                org_id.as_deref(),
                &capability.action_type,
                &capability.resource,
                estimated_cost_usd,
                None,
                None,
                Some(&name),
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
            let verification_execution_id = read_runtime_event_execution_id(&capture.runtime_event_path)?;
            let worker_result = if capture.worker_result_path.exists() {
                Some(read_json_file(&capture.worker_result_path)?)
            } else {
                None
            };
            let expectation_failures = verify_capability_expectations(
                worker_result.as_ref(),
                expect_summary_contains.as_deref(),
                &expect_result_fields,
            )?;
            let base_verified =
                capture.runtime_outcome == "worker_executed" && capture.worker_status == "completed";
            let verification_status = if base_verified && expectation_failures.is_empty() {
                "verified"
            } else {
                "failed"
            };
            let mut verification_notes = vec![format!(
                "runtime_outcome={} worker_status={} effective_stage={}",
                capture.runtime_outcome, capture.worker_status, capture.effective_stage
            )];
            if !expectation_failures.is_empty() {
                verification_notes.push(format!(
                    "expectation_failures={}",
                    expectation_failures.join("; ")
                ));
            } else if expect_summary_contains.is_some() || !expect_result_fields.is_empty() {
                verification_notes.push("expectations=matched".to_string());
            }
            let verification_note = verification_notes.join(" | ");
            let updated = update_capability_verification(
                &root,
                &config,
                &name,
                verification_status,
                &capability_timestamp_now(),
                &capture.input_hash,
                &verification_execution_id,
                &verification_note,
            )?;
            let gap_update = if let Some(gap_id) = gap_id.as_deref() {
                Some(update_capability_gap_verification(
                    &root,
                    &config,
                    gap_id,
                    verification_status,
                    &capture.input_hash,
                    &verification_execution_id,
                    &verification_note,
                )?)
            } else {
                None
            };
            if format == "json" {
                if let Some(gap_update) = gap_update {
                    print!(
                        "{{\"verification\":{},\"gap\":{}}}\n",
                        render_capability_state_update_json(&updated).trim(),
                        render_capability_gap_json(&gap_update).trim()
                    );
                } else {
                    print!("{}", render_capability_state_update_json(&updated));
                }
            } else {
                let mut blocks = vec![
                    render_runtime_execution_human(&capture),
                    render_capability_state_update_human("Meridian Loom // CAPABILITY VERIFY", &updated),
                ];
                if let Some(gap_update) = gap_update {
                    blocks.push(render_capability_gap_human(&gap_update));
                }
                print_human_block(&blocks);
            }
            Ok(())
        }
        Some("promote") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let config = read_config(&root)?;
            let name = required_flag(args, "--name")?;
            let gap_id = take_value(args, "--gap-id");
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let updated = promote_capability(&root, &config, &name, &capability_timestamp_now())?;
            let gap_update = if let Some(gap_id) = gap_id.as_deref() {
                Some(update_capability_gap_promotion(
                    &root,
                    &config,
                    gap_id,
                    "promoted",
                    "gap candidate promoted after verification",
                )?)
            } else {
                None
            };
            if format == "json" {
                if let Some(gap_update) = gap_update {
                    print!(
                        "{{\"promotion\":{},\"gap\":{}}}\n",
                        render_capability_state_update_json(&updated).trim(),
                        render_capability_gap_json(&gap_update).trim()
                    );
                } else {
                    print!("{}", render_capability_state_update_json(&updated));
                }
            } else {
                if let Some(gap_update) = gap_update {
                    print_human_block(&[
                        render_capability_state_update_human(
                            "Meridian Loom // CAPABILITY PROMOTE",
                            &updated,
                        ),
                        render_capability_gap_human(&gap_update),
                    ]);
                } else {
                    print_human(&render_capability_state_update_human(
                        "Meridian Loom // CAPABILITY PROMOTE",
                        &updated,
                    ));
                }
            }
            Ok(())
        }

        Some("gap") => {
            match args.get(1).map(String::as_str) {
                Some("show") => {
                    let root = root_from(take_value(args, "--root").as_deref())?;
                    let config = read_config(&root)?;
                    let gap_id = required_flag(args, "--gap-id")?;
                    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
                    let gap = load_capability_gap(&root, &config, &gap_id)?;
                    let gap_path = root
                        .join(&config.capabilities_dir)
                        .join("gaps")
                        .join(format!("{}.json", sanitize_token(&gap_id)));
                    let update = loom_core::capabilities::CapabilityGapUpdateResult { gap_path, gap };
                    if format == "json" {
                        print!("{}", render_capability_gap_json(&update));
                    } else {
                        print_human(&render_capability_gap_human(&update));
                    }
                    Ok(())
                }
                Some("replay") => {
                    let root = root_from(take_value(args, "--root").as_deref())?;
                    let config = read_config(&root)?;
                    let gap_id = required_flag(args, "--gap-id")?;
                    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
                    let gap = load_capability_gap(&root, &config, &gap_id)?;
                    let replay_request = capability_gap_replay_request(&gap)?;
                    crate::commands::action::run_action_execute_request(
                        &root,
                        &config,
                        &replay_request.agent_id,
                        Some(replay_request.capability_name.as_str()),
                        replay_request.action_type,
                        replay_request.resource,
                        0.0,
                        if replay_request.kernel_path.trim().is_empty() {
                            None
                        } else {
                            Some(replay_request.kernel_path.as_str())
                        },
                        if replay_request.org_id.trim().is_empty() {
                            None
                        } else {
                            Some(replay_request.org_id.as_str())
                        },
                        if replay_request.run_id.trim().is_empty() {
                            None
                        } else {
                            Some(replay_request.run_id.as_str())
                        },
                        if replay_request.session_id.trim().is_empty() {
                            None
                        } else {
                            Some(replay_request.session_id.as_str())
                        },
                        if replay_request.payload_json.trim().is_empty() {
                            None
                        } else {
                            Some(replay_request.payload_json.as_str())
                        },
                        &format,
                    )
                }
                _ => Err("capability gap supports 'show' and 'replay'".to_string()),
            }
        }
        Some("shim") => {
            let tool_name = required_flag(args, "--tool-name")?;
            let input_schema = required_flag(args, "--input-schema")?;
            let output_schema = required_flag(args, "--output-schema")?;
            let version = take_value(args, "--version");
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let spec = LegacyToolSpec {
                name: tool_name,
                version,
                input_schema,
                output_schema,
            };
            let shim = generate_shim(&spec);
            if let Err(errors) = validate_shim(&shim) {
                return Err(format!("generated invalid shim: {}", errors.join("; ")));
            }
            if format == "json" {
                print!("{}", render_shim_json(&shim));
            } else {
                print_human(&render_shim_human(&shim));
            }
            Ok(())
        }
        _ => Err("capability supports 'list', 'show', 'scaffold', 'forge', 'import-workspace-skill', 'import-legacy-v1-plugin-skill-subset', 'verify', 'promote', and 'shim'".to_string()),
    }
}

pub(crate) fn forge_name_from_args(
    args: &[String],
    gap_class: &str,
    goal: &str,
) -> LoomResult<String> {
    if let Some(name) = take_value(args, "--name") {
        return Ok(name);
    }
    if gap_class.trim().is_empty() {
        return Err("capability forge requires --name or --gap-class".to_string());
    }
    let goal_token = if goal.trim().is_empty() {
        "candidate".to_string()
    } else {
        sanitize_token(goal)
    };
    Ok(format!(
        "loomforge.{}.{}.v0",
        sanitize_token(gap_class),
        goal_token
    ))
}

pub(crate) fn read_runtime_event_execution_id(path: &PathBuf) -> LoomResult<String> {
    let raw = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let value: Value = serde_json::from_str(&raw).map_err(|e| e.to_string())?;
    let job_id = value
        .get("job_id")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let execution_id = value
        .get("execution_id")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    if job_id.is_empty() || execution_id.is_empty() {
        return Err(format!(
            "runtime event at {} missing job_id or execution_id",
            path.display()
        ));
    }
    Ok(execution_id)
}

pub(crate) fn read_json_file(path: &PathBuf) -> LoomResult<Value> {
    let raw = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    serde_json::from_str(&raw).map_err(|e| format!("failed to parse {}: {}", path.display(), e))
}

pub(crate) fn render_capability_evidence_human(
    root: &std::path::Path,
    capability: &loom_core::capabilities::CapabilityDescriptor,
) -> String {
    let manifest_path = root
        .join("capabilities")
        .join("custom")
        .join(format!("{}.json", sanitize_token(&capability.name)));
    if capability.last_verification_job_id.is_empty() {
        return format!(
            "Verification evidence\n=====================\nmanifest:          {}\nverification_job:  (none)\nexpectation_summary: capability has not been verified through Loom yet\n",
            manifest_path.display(),
        );
    }
    match inspect_job(root, &capability.last_verification_job_id) {
        Ok(job) => {
            let worker_result_path = job
                .job_path
                .parent()
                .map(|parent| parent.join("result.json"))
                .unwrap_or_else(|| root.join("state/runtime/jobs/result.json"));
            format!(
                "Verification evidence\n=====================\nmanifest:          {}\nverification_job:  {}\nverification_exec: {}\nexpectation_summary: {}\njob_path:          {}\njob_status:        {}\njob_stage:         {}\nruntime_outcome:   {}\nworker_status:     {}\nbudget_status:     {}\nfailure_reason:    {}\njob_note:          {}\nworker_result:     {}\nevent_path:        {}\naudit_log:         {}\nparity_report:     {}\n",
                manifest_path.display(),
                capability.last_verification_job_id,
                if capability.last_verification_execution_id.is_empty() {
                    "(none)"
                } else {
                    &capability.last_verification_execution_id
                },
                if capability.verification_note.is_empty() {
                    "(none)"
                } else {
                    &capability.verification_note
                },
                job.job_path.display(),
                job.status,
                job.stage,
                job.runtime_outcome,
                job.worker_status,
                job.budget_reservation_status,
                if job.budget_reservation_reason.is_empty() {
                    if job.note.is_empty() {
                        "(none)"
                    } else {
                        &job.note
                    }
                } else {
                    &job.budget_reservation_reason
                },
                if job.note.is_empty() { "(none)" } else { &job.note },
                worker_result_path.display(),
                job.event_path
                    .as_ref()
                    .map(|path| path.display().to_string())
                    .unwrap_or_else(|| "(none)".to_string()),
                job.audit_log_path
                    .as_ref()
                    .map(|path| path.display().to_string())
                    .unwrap_or_else(|| "(none)".to_string()),
                job.parity_report_path
                    .as_ref()
                    .map(|path| path.display().to_string())
                    .unwrap_or_else(|| "(none)".to_string()),
            )
        }
        Err(error) => format!(
            "Verification evidence\n=====================\nmanifest:          {}\nverification_job:  {}\nverification_exec: {}\nexpectation_summary: {}\nlookup_error:      {}\n",
            manifest_path.display(),
            capability.last_verification_job_id,
            if capability.last_verification_execution_id.is_empty() {
                "(none)"
            } else {
                &capability.last_verification_execution_id
            },
            if capability.verification_note.is_empty() {
                "(none)"
            } else {
                &capability.verification_note
            },
            error
        ),
    }
}

pub(crate) fn capability_verification_evidence_value(
    root: &std::path::Path,
    capability: &loom_core::capabilities::CapabilityDescriptor,
) -> LoomResult<Value> {
    let manifest_path = root
        .join("capabilities")
        .join("custom")
        .join(format!("{}.json", sanitize_token(&capability.name)));
    if capability.last_verification_job_id.is_empty() {
        return Ok(serde_json::json!({
            "manifest": manifest_path.display().to_string(),
            "verification_job": Value::Null,
            "expectation_summary": if capability.verification_note.is_empty() {
                "capability has not been verified through Loom yet"
            } else {
                capability.verification_note.as_str()
            },
        }));
    }

    match inspect_job(root, &capability.last_verification_job_id) {
        Ok(job) => {
            let worker_result_path = job
                .job_path
                .parent()
                .map(|parent| parent.join("result.json"))
                .unwrap_or_else(|| root.join("state/runtime/jobs/result.json"));
            Ok(serde_json::json!({
                "manifest": manifest_path.display().to_string(),
                "verification_job": capability.last_verification_job_id,
                "verification_exec": if capability.last_verification_execution_id.is_empty() {
                    Value::Null
                } else {
                    Value::String(capability.last_verification_execution_id.clone())
                },
                "expectation_summary": if capability.verification_note.is_empty() {
                    Value::Null
                } else {
                    Value::String(capability.verification_note.clone())
                },
                "job_path": job.job_path.display().to_string(),
                "job_status": job.status,
                "job_stage": job.stage,
                "runtime_outcome": job.runtime_outcome,
                "worker_status": job.worker_status,
                "budget_status": job.budget_reservation_status,
                "failure_reason": if job.budget_reservation_reason.is_empty() {
                    if job.note.is_empty() {
                        Value::Null
                    } else {
                        Value::String(job.note.clone())
                    }
                } else {
                    Value::String(job.budget_reservation_reason)
                },
                "job_note": if job.note.is_empty() {
                    Value::Null
                } else {
                    Value::String(job.note)
                },
                "worker_result": worker_result_path.display().to_string(),
                "event_path": job.event_path.map(|path| path.display().to_string()),
                "audit_log": job.audit_log_path.map(|path| path.display().to_string()),
                "parity_report": job.parity_report_path.map(|path| path.display().to_string()),
            }))
        }
        Err(error) => Ok(serde_json::json!({
            "manifest": manifest_path.display().to_string(),
            "verification_job": capability.last_verification_job_id,
            "verification_exec": if capability.last_verification_execution_id.is_empty() {
                Value::Null
            } else {
                Value::String(capability.last_verification_execution_id.clone())
            },
            "expectation_summary": if capability.verification_note.is_empty() {
                Value::Null
            } else {
                Value::String(capability.verification_note.clone())
            },
            "lookup_error": error,
        })),
    }
}

pub(crate) fn render_capability_show_json(
    root: &std::path::Path,
    capability: &loom_core::capabilities::CapabilityDescriptor,
) -> LoomResult<String> {
    let mut value: Value = serde_json::from_str(&render_capability_json(capability))
        .map_err(|error| format!("failed to parse capability json: {}", error))?;
    let evidence = capability_verification_evidence_value(root, capability)?;
    if let Some(object) = value.as_object_mut() {
        object.insert("verification_evidence".to_string(), evidence);
    }
    Ok(format!("{}\n", value))
}

pub(crate) fn verify_capability_expectations(
    worker_result: Option<&Value>,
    expect_summary_contains: Option<&str>,
    expect_result_fields: &[String],
) -> LoomResult<Vec<String>> {
    if expect_summary_contains.is_none() && expect_result_fields.is_empty() {
        return Ok(Vec::new());
    }
    let Some(worker_result) = worker_result else {
        return Ok(vec![
            "worker result missing while expectations were requested".to_string(),
        ]);
    };
    let mut failures = Vec::new();
    if let Some(fragment) = expect_summary_contains {
        let summary = worker_result
            .get("summary")
            .and_then(Value::as_str)
            .unwrap_or("");
        if !summary.contains(fragment) {
            failures.push(format!(
                "summary missing fragment {:?} (actual: {:?})",
                fragment, summary
            ));
        }
    }
    for expectation in expect_result_fields {
        let Some((path, expected_raw)) = expectation.split_once('=') else {
            failures.push(format!(
                "invalid --expect-result-field {:?}; expected PATH=VALUE",
                expectation
            ));
            continue;
        };
        let Some(actual) = lookup_json_path(worker_result, path) else {
            failures.push(format!("result field {:?} not found", path));
            continue;
        };
        if !json_value_matches(actual, expected_raw) {
            failures.push(format!(
                "result field {:?} expected {:?} but was {}",
                path,
                expected_raw,
                json_value_to_string(actual)
            ));
        }
    }
    Ok(failures)
}

pub(crate) fn lookup_json_path<'a>(value: &'a Value, path: &str) -> Option<&'a Value> {
    let mut current = value;
    for segment in path.split('.') {
        let trimmed = segment.trim();
        if trimmed.is_empty() {
            return None;
        }
        current = match current {
            Value::Object(_) => current.get(trimmed)?,
            Value::Array(items) => {
                let index = trimmed.parse::<usize>().ok()?;
                items.get(index)?
            }
            _ => return None,
        };
    }
    Some(current)
}

pub(crate) fn json_value_matches(actual: &Value, expected_raw: &str) -> bool {
    if let Ok(expected_json) = serde_json::from_str::<Value>(expected_raw) {
        return actual == &expected_json;
    }
    json_value_to_string(actual) == expected_raw
}

pub(crate) fn json_value_to_string(value: &Value) -> String {
    match value {
        Value::String(raw) => raw.clone(),
        _ => value.to_string(),
    }
}

pub(crate) fn print_capability_help() {
    print_human(
        "Meridian Loom // CAPABILITY HELP\n\
=================================\n\
Commands\n\
--------\n\
  loom capability list [--root PATH] [--format human|json]\n\
  loom capability show --name NAME [--root PATH] [--format human|json]\n\
  loom capability gap show --gap-id ID [--root PATH] [--format human|json]\n\
  loom capability gap replay --gap-id ID [--root PATH] [--format human|json]\n\
  loom capability scaffold --name NAME --action-type TYPE --resource RESOURCE [--description TEXT] [--worker-kind python|wasm] [--worker-entry PATH] [--wasm-module builtin:minimal|wasm:PATH] [--payload-mode json|none] [--root PATH]\n\
  loom capability forge [--name NAME] [--gap-id ID] [--template echo_json_v0|artifact_inspect_v0|url_bundle_v0] [--gap-class artifact_triage|url_collection|response_echo] [--goal TEXT] [--description TEXT] [--root PATH] [--format human|json]\n\
  loom capability import-workspace-skill --skill-root PATH [--entrypoint PATH] [--name NAME] [--root PATH] [--format human|json]\n  loom capability import-legacy-v1-plugin-skill-subset --plugin-root PATH [--root PATH] [--format human|json]\n\
  loom capability verify --name NAME --agent-id ID --kernel-path PATH [--gap-id ID] [--org-id ORG] [--payload-json JSON] [--estimated-cost-usd USD] [--expect-summary-contains TEXT] [--expect-result-field PATH=VALUE]... [--root PATH] [--format human|json]\n\
  loom capability promote --name NAME [--gap-id ID] [--root PATH] [--format human|json]\n\
  loom capability shim --tool-name NAME --input-schema JSON --output-schema JSON [--version SEMVER] [--format human|json]\n\
\n\
Notes\n\
-----\n\
  - forge creates a candidate Loom-native capability from either a bounded template, a bounded gap-class, or a recorded capability gap.\n\
  - import-workspace-skill supports a bounded clawfamily contract v0 subset: workspace python entrypoint skills and bundle-manifest python skills. Workspace imports can disambiguate multi-script trees with --entrypoint or entrypoint: front matter.\n  - import-legacy-v1-plugin-skill-subset imports only immediate child skill dirs under the declared plugin skills roots and reports every unsupported source surface explicitly.\n\
  - verify executes the capability through Loom's runtime path, can assert expectations over the worker result, and writes verification state back into the custom manifest.\n\
  - promote is only for custom/imported capabilities that have already been verified.\n\
  - action execute / service submit with --capability plus --gap-class records a bounded gap object instead of pretending the capability exists.\n\
  - gap replay currently reissues only recorded action_execute gaps; service_submit gaps fail explicitly until their transport-side replay fields are persisted.\n\
  - imported workspace skills still run through Loom queue, job, worker, audit, and artifact paths.\n\
  - this is a local-first compatibility surface; hosted runtime dependency is not claimed.\n",
    );
}
