use std::collections::BTreeMap;
use std::fs;
use std::io::IsTerminal;

use crate::*;
use loom_core::agent_runtime::{
    agent_memory_summary, agent_runtime_summary, agent_session_summary, commit_agent_session,
    open_agent_session, render_agent_memory_human, render_agent_memory_json,
    render_agent_runtime_human, render_agent_runtime_json, render_agent_session_human,
    render_agent_session_json, write_agent_memory_snapshot,
};
use loom_core::context_engine::{
    context_bundle, render_context_bundle_human, render_context_bundle_json,
};
use loom_core::{
    bindings, channels, gateway_runtime, onboarding, pipeline, provider_auth_store,
    provider_router, recurring, recurring_executor, schedules, service_ingress_runtime,
    service_runtime, session_provenance, skill_lifecycle, skills,
};
use loom_shadow::{
    render_shadow_grpc_action_diagnostics_json, render_shadow_grpc_action_diagnostics_report,
};

pub(crate) fn handle_init(args: &[String]) -> LoomResult<()> {
    let mode = take_value(args, "--mode").unwrap_or_else(|| "standalone".to_string());
    let kernel_path = take_value(args, "--kernel-path");
    let root = root_from(take_value(args, "--root").as_deref())?;
    let org_id = take_value(args, "--org-id").unwrap_or_else(|| "local_foundry".to_string());
    let config = init_workspace(&root, &mode, kernel_path.as_deref(), &org_id)?;
    print_human(&format!(
        "Meridian Loom // INIT\n====================\nroot:        {}\nmode:        {}\norg_id:      {}\nkernel_path: {}\nstatus:      local runtime root ready\n\nQuick start\n-----------\n1. loom onboard --root {} --format human\n2. loom provider login --source loom --device-auth\n3. loom doctor --root {} --format human\n",
        root.display(),
        config.mode,
        config.org_id,
        if config.kernel_path.is_empty() { "(not set)" } else { &config.kernel_path },
        root.display(),
        root.display()
    ));
    Ok(())
}

pub(crate) fn handle_doctor(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_doctor_help();
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
    let fix = args.iter().any(|a| a == "--fix");

    let mut checks = doctor(&root)?;

    let mut fix_results: Vec<String> = Vec::new();
    if fix {
        fix_results.extend(apply_safe_doctor_fixes(&root)?);
        if fix_results.is_empty() {
            fix_results.push("fix: no safe remediations to apply".to_string());
        }
        checks = doctor(&root)?;
    }

    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_doctor_human(&checks));
            for msg in &fix_results {
                println!("{}", msg);
            }
        }
        _ => {
            let checks_json = render_doctor_json(&checks);
            if fix_results.is_empty() {
                print!("{}", checks_json);
            } else {
                let fix_json: Vec<String> = fix_results
                    .iter()
                    .map(|s| format!("\"{}\"", s.replace('\\', "\\\\").replace('"', "\\\"")))
                    .collect();
                println!(
                    "{{\"checks\":{},\"fix_results\":[{}]}}",
                    checks_json.trim_end(),
                    fix_json.join(",")
                );
            }
        }
    }
    Ok(())
}

fn print_doctor_help() {
    print_human(
        "Meridian Loom // DOCTOR HELP
===============================
USAGE: loom doctor [OPTIONS]

PURPOSE:
  Inspect the local runtime for configuration gaps, provider readiness,
  service health, session/pipeline state, memory/context health, and proof surfaces.

OPTIONS:
  --root PATH            Runtime root to inspect.
  --format human|json    Output format.
  --fix                  Apply only safe scaffold and registry repairs.

NOTES:
  - --fix does not perform destructive changes.
  - --fix does not claim a service is running unless it can verify it.
  - JSON output is stable for automation and external probe tooling.
",
    );
}

fn apply_safe_doctor_fixes(root: &std::path::Path) -> LoomResult<Vec<String>> {
    let mut results = Vec::new();
    let config = read_config(root)?;
    fs::create_dir_all(root.join(&config.state_dir)).map_err(|error| error.to_string())?;
    fs::create_dir_all(root.join(&config.run_dir)).map_err(|error| error.to_string())?;
    fs::create_dir_all(root.join(&config.log_dir)).map_err(|error| error.to_string())?;
    fs::create_dir_all(root.join(&config.artifact_dir)).map_err(|error| error.to_string())?;
    fs::create_dir_all(root.join(&config.capabilities_dir)).map_err(|error| error.to_string())?;
    fs::create_dir_all(root.join("state/memory")).map_err(|error| error.to_string())?;
    results.push("fix: ensured runtime directories exist".to_string());

    onboarding::ensure_onboard_manifest(root, &config)?;
    provider_router::ensure_provider_profiles_scaffold(root)?;
    provider_auth_store::ensure_provider_auth_store_scaffold(root)?;
    provider_auth_store::sync_provider_auth_store(root)?;
    gateway_runtime::ensure_gateway_runtime_scaffold(root)?;
    service_runtime::ensure_service_runtime_scaffold(root)?;
    service_ingress_runtime::ensure_service_ingress_runtime_scaffold(root)?;
    loom_core::agent_runtime::ensure_agent_runtime_scaffold(root)?;
    loom_core::context_engine::ensure_context_engine_scaffold(root)?;
    recurring::ensure_heartbeat_runtime_scaffold(root)?;
    schedules::ensure_schedule_runtime_scaffold(root)?;
    channels::ensure_channel_runtime_scaffold(root)?;
    bindings::ensure_binding_runtime_scaffold(root)?;
    skills::ensure_skill_runtime_scaffold(root)?;
    session_provenance::ensure_session_provenance_scaffold(root)?;
    skill_lifecycle::ensure_skill_lifecycle_scaffold(root)?;
    recurring_executor::ensure_recurring_executor_scaffold(root)?;
    pipeline::ensure_pipeline_scaffold(root)?;
    results.push("fix: refreshed safe scaffold files and runtime registries".to_string());

    Ok(results)
}

pub(crate) fn handle_runtime_info(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let config = read_config(&root)?;
    let binary_path = std::env::current_exe()
        .map(|p| p.display().to_string())
        .unwrap_or_else(|_| "(unknown)".to_string());
    let info = serde_json::json!({
        "version": env!("CARGO_PKG_VERSION"),
        "binary_path": binary_path,
        "runtime_root": root.display().to_string(),
        "mode": config.mode,
        "org_id": config.org_id,
        "service_http_address": config.service_http_address,
        "service_token_env": config.service_token_env,
        "python_path": config.python_path,
        "kernel_path": config.kernel_path,
        "state_dir": root.join(&config.state_dir).display().to_string(),
        "log_dir": root.join(&config.log_dir).display().to_string(),
    });
    print!(
        "{}",
        serde_json::to_string_pretty(&info).map_err(|e| e.to_string())?
    );
    println!();
    Ok(())
}

pub(crate) fn handle_health(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = take_value(args, "--format").unwrap_or_else(|| "json".to_string());
    let (healthy, json) = health(&root)?;
    if format == "human" {
        print_human(&render_health_human(healthy, &json));
    } else {
        print!("{}", json);
    }
    Ok(())
}

pub(crate) fn handle_status(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let base = status_human(&root)?;
    let service = runtime_service_status(&root, take_value(args, "--socket").as_deref())?;
    let queue = queue_status(&root).ok();
    print_startup_banner();
    let mut blocks = vec![base, render_runtime_service_human(&service)];
    if let Some(snapshot) = queue {
        blocks.push(render_queue_status_human(&snapshot));
    }
    print_human_block(&blocks);
    Ok(())
}

pub(crate) fn handle_config(args: &[String]) -> LoomResult<()> {
    if args.first().map(String::as_str) != Some("show") {
        return Err("config only supports 'show' in this scaffold".to_string());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let config = read_config(&root)?;
    print_human(&render_config_human(&config, &root));
    Ok(())
}

pub(crate) fn handle_contract(args: &[String]) -> LoomResult<()> {
    match args.first().map(String::as_str) {
        Some("show") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let kernel_path = take_value(args, "--kernel-path");
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let snapshot = contract_show(&root, kernel_path.as_deref())?;
            if format == "json" {
                print!("{}", render_contract_json(&snapshot));
            } else {
                print_human(&render_contract_human(&snapshot));
            }
            Ok(())
        }
        Some("verify") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let kernel_path = take_value(args, "--kernel-path");
            let agent_id =
                take_value(args, "--agent-id").unwrap_or_else(|| "agent_tutorial".to_string());
            let org_id = take_value(args, "--org-id");
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let result =
                contract_verify(&root, kernel_path.as_deref(), &agent_id, org_id.as_deref())?;
            if format == "json" {
                print!("{}", render_contract_verify_json(&result));
            } else {
                print_human(&render_contract_verify_human(&result));
            }
            if result.passed < result.total {
                std::process::exit(1);
            }
            Ok(())
        }
        _ => Err("contract supports 'show' and 'verify'".to_string()),
    }
}

pub(crate) fn handle_capsule(args: &[String]) -> LoomResult<()> {
    if args.first().map(String::as_str) != Some("inspect") {
        return Err("capsule only supports 'inspect' in this scaffold".to_string());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let inspection = capsule_inspect(&root)?;
    print_human(&render_capsule_human(&inspection));
    Ok(())
}

pub(crate) fn handle_agent(args: &[String]) -> LoomResult<()> {
    match args.first().map(String::as_str) {
        Some("resolve") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let agent_id = required_flag(args, "--agent-id")?;
            let kernel_path = take_value(args, "--kernel-path");
            let org_id = take_value(args, "--org-id");
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let identity = resolve_agent_identity(
                &root,
                kernel_path.as_deref(),
                &agent_id,
                org_id.as_deref(),
            )?;
            if format == "json" {
                print!("{}", render_identity_json(&identity));
            } else {
                print_human(&render_identity_human(&identity));
            }
            Ok(())
        }
        Some("runtime") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let agent_id = required_flag(args, "--agent-id")?;
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let summary = agent_runtime_summary(&root, &agent_id)?;
            if format == "json" {
                print!("{}", render_agent_runtime_json(&summary));
            } else {
                print_human(&render_agent_runtime_human(&summary));
            }
            Ok(())
        }
        Some("session") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let agent_id = required_flag(args, "--agent-id")?;
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let task_kind = take_value(args, "--task-kind");
            let status = take_value(args, "--status");
            let summary_text = take_value(args, "--summary");
            let summary = if has_flag(args, "--new") {
                open_agent_session(&root, &agent_id, task_kind.as_deref())?
            } else if status.is_some() || summary_text.is_some() || task_kind.is_some() {
                commit_agent_session(
                    &root,
                    &agent_id,
                    status.as_deref(),
                    summary_text.as_deref(),
                    task_kind.as_deref(),
                )?
            } else {
                agent_session_summary(&root, &agent_id)?
            };
            if format == "json" {
                print!("{}", render_agent_session_json(&summary));
            } else {
                print_human(&render_agent_session_human(&summary));
            }
            Ok(())
        }
        Some("memory") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let agent_id = required_flag(args, "--agent-id")?;
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let mut updates = BTreeMap::new();
            for entry in take_values(args, "--set") {
                let Some((key, value)) = entry.split_once('=') else {
                    return Err(format!("invalid --set '{}': expected key=value", entry));
                };
                let key = key.trim();
                let value = value.trim();
                if key.is_empty() || value.is_empty() {
                    return Err(format!("invalid --set '{}': expected key=value", entry));
                }
                updates.insert(key.to_string(), value.to_string());
            }
            let summary = if updates.is_empty() {
                agent_memory_summary(&root, &agent_id)?
            } else {
                write_agent_memory_snapshot(&root, &agent_id, &updates)?
            };
            if format == "json" {
                print!("{}", render_agent_memory_json(&summary));
            } else {
                print_human(&render_agent_memory_human(&summary));
            }
            Ok(())
        }
        Some("context") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let agent_id = required_flag(args, "--agent-id")?;
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let session_id = take_value(args, "--session-id");
            let bundle = context_bundle(&root, &agent_id, session_id.as_deref())?;
            if format == "json" {
                print!("{}", render_context_bundle_json(&bundle));
            } else {
                print_human(&render_context_bundle_human(&bundle));
            }
            Ok(())
        }
        _ => Err(
            "agent supports 'resolve', 'runtime', 'session', 'memory', and 'context'".to_string(),
        ),
    }
}

pub(crate) fn handle_envelope(args: &[String]) -> LoomResult<()> {
    if args.first().map(String::as_str) != Some("build") {
        return Err("envelope only supports 'build' in this scaffold".to_string());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let agent_id = required_flag(args, "--agent-id")?;
    let action_type = required_flag(args, "--action-type")?;
    let resource = required_flag(args, "--resource")?;
    let estimated_cost_usd = parse_f64_flag(args, "--estimated-cost-usd").unwrap_or(0.0);
    let kernel_path = take_value(args, "--kernel-path");
    let org_id = take_value(args, "--org-id");
    let run_id = take_value(args, "--run-id");
    let session_id = take_value(args, "--session-id");
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());

    let envelope = build_action_envelope(
        &root,
        kernel_path.as_deref(),
        &agent_id,
        org_id.as_deref(),
        &action_type,
        &resource,
        estimated_cost_usd,
        run_id.as_deref(),
        session_id.as_deref(),
    )?;
    if format == "json" {
        print!("{}", render_envelope_json(&envelope));
    } else {
        print_human(&render_envelope_human(&envelope));
    }
    Ok(())
}

pub(crate) fn handle_shadow(args: &[String]) -> LoomResult<()> {
    match args.first().map(String::as_str) {
        Some("run") => handle_shadow_run(&args[1..]),
        Some("grpc-diagnostics") | Some("grpc_diagnostics") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let limit = take_value(args, "--limit")
                .map(|raw| {
                    raw.parse::<usize>()
                        .map_err(|error| format!("invalid --limit '{}': {}", raw, error))
                })
                .transpose()?
                .unwrap_or(10);
            if limit == 0 {
                return Err("shadow grpc-diagnostics requires --limit >= 1".to_string());
            }
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            if format == "json" {
                print!(
                    "{}",
                    render_shadow_grpc_action_diagnostics_json(&root, limit)?
                );
            } else {
                print_human(&render_shadow_grpc_action_diagnostics_report(&root, limit)?);
            }
            Ok(())
        }
        Some("report") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            print_human(&render_shadow_report(&root)?);
            Ok(())
        }
        Some("preflight") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let agent_id = required_flag(args, "--agent-id")?;
            let action_type = required_flag(args, "--action-type")?;
            let resource = required_flag(args, "--resource")?;
            let estimated_cost_usd = parse_f64_flag(args, "--estimated-cost-usd").unwrap_or(0.0);
            let kernel_path = take_value(args, "--kernel-path");
            let org_id = take_value(args, "--org-id");
            let run_id = take_value(args, "--run-id");
            let session_id = take_value(args, "--session-id");
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());

            let identity = resolve_agent_identity(
                &root,
                kernel_path.as_deref(),
                &agent_id,
                org_id.as_deref(),
            )?;
            let envelope = build_action_envelope(
                &root,
                kernel_path.as_deref(),
                &agent_id,
                org_id.as_deref(),
                &action_type,
                &resource,
                estimated_cost_usd,
                run_id.as_deref(),
                session_id.as_deref(),
            )?;
            let reference =
                evaluate_reference_gates(&root, kernel_path.as_deref(), &identity, &envelope)?;
            let effective_kernel_path = kernel_path_for(&root, kernel_path.as_deref())?;
            let capture = capture_preflight(
                &root,
                &effective_kernel_path,
                &identity,
                &envelope,
                &reference,
            )?;
            if format == "json" {
                print!("{}", render_preflight_json(&capture));
            } else {
                print_human_block(&[
                    render_identity_human(&identity),
                    render_envelope_human(&envelope),
                    render_preflight_human(&capture),
                ]);
            }
            Ok(())
        }
        Some("decide") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let agent_id = required_flag(args, "--agent-id")?;
            let action_type = required_flag(args, "--action-type")?;
            let resource = required_flag(args, "--resource")?;
            let estimated_cost_usd = parse_f64_flag(args, "--estimated-cost-usd").unwrap_or(0.0);
            let kernel_path = take_value(args, "--kernel-path");
            let org_id = take_value(args, "--org-id");
            let run_id = take_value(args, "--run-id");
            let session_id = take_value(args, "--session-id");
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());

            let identity = resolve_agent_identity(
                &root,
                kernel_path.as_deref(),
                &agent_id,
                org_id.as_deref(),
            )?;
            let envelope = build_action_envelope(
                &root,
                kernel_path.as_deref(),
                &agent_id,
                org_id.as_deref(),
                &action_type,
                &resource,
                estimated_cost_usd,
                run_id.as_deref(),
                session_id.as_deref(),
            )?;
            let reference =
                evaluate_reference_gates(&root, kernel_path.as_deref(), &identity, &envelope)?;
            let capture = capture_decision(&root, &identity, &envelope, &reference)?;
            if format == "json" {
                print!("{}", render_decision_json(&capture));
            } else {
                print_human(&render_decision_human(&capture));
            }
            Ok(())
        }
        Some("enforce") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let agent_id = required_flag(args, "--agent-id")?;
            let action_type = required_flag(args, "--action-type")?;
            let resource = required_flag(args, "--resource")?;
            let estimated_cost_usd = parse_f64_flag(args, "--estimated-cost-usd").unwrap_or(0.0);
            let kernel_path = take_value(args, "--kernel-path");
            let org_id = take_value(args, "--org-id");
            let run_id = take_value(args, "--run-id");
            let session_id = take_value(args, "--session-id");
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());

            let identity = resolve_agent_identity(
                &root,
                kernel_path.as_deref(),
                &agent_id,
                org_id.as_deref(),
            )?;
            let envelope = build_action_envelope(
                &root,
                kernel_path.as_deref(),
                &agent_id,
                org_id.as_deref(),
                &action_type,
                &resource,
                estimated_cost_usd,
                run_id.as_deref(),
                session_id.as_deref(),
            )?;
            let reference =
                evaluate_reference_gates(&root, kernel_path.as_deref(), &identity, &envelope)?;
            let capture = capture_decision(&root, &identity, &envelope, &reference)?;
            if format == "json" {
                print!("{}", render_decision_json(&capture));
            } else {
                print_human(&render_decision_human(&capture));
            }
            std::process::exit(decision_exit_code(&capture, 0, 2));
        }
        Some("compare") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let config = read_config(&root)?;
            let primary = PathBuf::from(required_flag(args, "--primary")?);
            let shadow = take_value(args, "--shadow")
                .map(PathBuf::from)
                .unwrap_or_else(|| root.join(&config.artifact_dir).join("shadow/events.jsonl"));
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let summary = compare_logs(Some(&root), &primary, &shadow)?;
            if format == "json" {
                print!("{}", render_compare_json(&summary));
            } else {
                print_human(&render_compare_human(&summary));
            }
            Ok(())
        }
        _ => Err(
            "shadow supports 'run', 'grpc-diagnostics', 'preflight', 'decide', 'enforce', 'compare', and 'report'".to_string(),
        ),
    }
}

pub(crate) fn handle_parity(args: &[String]) -> LoomResult<()> {
    match args.first().map(String::as_str) {
        Some("report") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            print_human(&render_parity_report(&root)?);
            Ok(())
        }
        _ => Err("parity supports 'report'".to_string()),
    }
}

fn handle_shadow_run(args: &[String]) -> LoomResult<()> {
    let backend = take_value(args, "--backend").unwrap_or_else(|| "wasmtime".to_string());
    let root = root_from(take_value(args, "--root").as_deref())?;
    let config = read_config(&root)?;
    let kernel_path = take_value(args, "--kernel-path")
        .ok_or_else(|| "shadow run requires --kernel-path".to_string())?;
    let agent_id = required_flag(args, "--agent-id")?;
    let org_id = take_value(args, "--org-id").unwrap_or_else(|| config.org_id.clone());
    let action_type =
        take_value(args, "--action-type").unwrap_or_else(|| "wasm_shadow".to_string());
    let resource = take_value(args, "--resource").unwrap_or_else(|| "wasm_run".to_string());
    let module_source =
        take_value(args, "--module").unwrap_or_else(|| "builtin:minimal".to_string());
    let entrypoint = take_value(args, "--entrypoint").unwrap_or_else(|| "run".to_string());
    let fuel_budget = take_value(args, "--fuel-budget")
        .map(|raw| {
            raw.parse::<u64>()
                .map_err(|e| format!("invalid --fuel-budget '{}': {}", raw, e))
        })
        .transpose()?
        .unwrap_or(100_000);
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let warrant_file = take_value(args, "--warrant-file")
        .ok_or_else(|| "shadow run requires --warrant-file".to_string())?;
    let warrant = read_kernel_warrant(Path::new(&warrant_file))?;
    let backend_kind = match backend.as_str() {
        "wasmtime" => loom_shadow::ShadowBackendKind::Wasmtime,
        "command" => loom_shadow::ShadowBackendKind::Command,
        "http" => loom_shadow::ShadowBackendKind::Http,
        "mcp" => loom_shadow::ShadowBackendKind::Mcp,
        "a2a" => loom_shadow::ShadowBackendKind::A2a,
        "a2a_action" | "a2a-action" => loom_shadow::ShadowBackendKind::A2aAction,
        "grpc_action" | "grpc-action" => loom_shadow::ShadowBackendKind::GrpcAction,
        "grpc_physical" | "grpc-physical" => loom_shadow::ShadowBackendKind::GrpcPhysical,
        other => {
            return Err(format!(
                "shadow run currently supports --backend wasmtime|command|http|mcp|a2a|a2a_action|grpc_action|grpc_physical, got '{}'",
                other
            ))
        }
    };
    let is_grpc_action = matches!(backend_kind, loom_shadow::ShadowBackendKind::GrpcAction);
    let is_grpc_physical = matches!(backend_kind, loom_shadow::ShadowBackendKind::GrpcPhysical);
    let is_grpc_semantic = is_grpc_action || is_grpc_physical;
    let command_program = if matches!(backend_kind, loom_shadow::ShadowBackendKind::Command) {
        Some(required_flag(args, "--command")?)
    } else {
        None
    };
    let command_args = if matches!(backend_kind, loom_shadow::ShadowBackendKind::Command) {
        take_values(args, "--arg")
    } else {
        Vec::new()
    };
    let http_url = if matches!(
        backend_kind,
        loom_shadow::ShadowBackendKind::Http
            | loom_shadow::ShadowBackendKind::Mcp
            | loom_shadow::ShadowBackendKind::A2a
            | loom_shadow::ShadowBackendKind::A2aAction
            | loom_shadow::ShadowBackendKind::GrpcAction
            | loom_shadow::ShadowBackendKind::GrpcPhysical
    ) {
        Some(required_flag(args, "--url")?)
    } else {
        None
    };
    let http_method = if matches!(backend_kind, loom_shadow::ShadowBackendKind::Http) {
        Some(take_value(args, "--method").unwrap_or_else(|| "GET".to_string()))
    } else if is_grpc_action {
        let grpc_service = take_value(args, "--grpc-service")
            .unwrap_or_else(|| "meridian.runtime.v1.ActionService".to_string());
        let grpc_method =
            take_value(args, "--grpc-method").unwrap_or_else(|| "SubmitAction".to_string());
        let grpc_service = grpc_service.trim();
        let grpc_method = grpc_method.trim();
        if grpc_service.is_empty() || grpc_method.is_empty() {
            return Err(
                "shadow run --backend grpc_action requires non-empty --grpc-service and --grpc-method"
                    .to_string(),
            );
        }
        Some(format!("{}/{}", grpc_service, grpc_method))
    } else if is_grpc_physical {
        let grpc_service = take_value(args, "--grpc-service")
            .unwrap_or_else(|| "meridian.embodied.action.v1.PhysicalActionService".to_string());
        let grpc_method =
            take_value(args, "--grpc-method").unwrap_or_else(|| "Execute".to_string());
        let grpc_service = grpc_service.trim();
        let grpc_method = grpc_method.trim();
        if grpc_service.is_empty() || grpc_method.is_empty() {
            return Err(
                "shadow run --backend grpc_physical requires non-empty --grpc-service and --grpc-method"
                    .to_string(),
            );
        }
        Some(format!("{}/{}", grpc_service, grpc_method))
    } else if matches!(
        backend_kind,
        loom_shadow::ShadowBackendKind::Mcp
            | loom_shadow::ShadowBackendKind::A2a
            | loom_shadow::ShadowBackendKind::A2aAction
    ) {
        Some("POST".to_string())
    } else {
        None
    };
    let mut http_headers = if matches!(
        backend_kind,
        loom_shadow::ShadowBackendKind::Http
            | loom_shadow::ShadowBackendKind::Mcp
            | loom_shadow::ShadowBackendKind::A2a
            | loom_shadow::ShadowBackendKind::A2aAction
            | loom_shadow::ShadowBackendKind::GrpcAction
            | loom_shadow::ShadowBackendKind::GrpcPhysical
    ) {
        parse_shadow_http_headers(&take_values(args, "--header"))?
    } else {
        Vec::new()
    };
    if is_grpc_semantic {
        let force_plaintext = has_flag(args, "--grpc-plaintext");
        let force_tls = has_flag(args, "--grpc-tls");
        if force_plaintext && force_tls {
            return Err(format!(
                "shadow run --backend {} does not allow both --grpc-plaintext and --grpc-tls",
                if is_grpc_physical {
                    "grpc_physical"
                } else {
                    "grpc_action"
                }
            ));
        }
        if force_plaintext {
            http_headers.push(("x-loom-grpc-plaintext".to_string(), "true".to_string()));
        } else if force_tls {
            http_headers.push(("x-loom-grpc-plaintext".to_string(), "false".to_string()));
        }
        if has_flag(args, "--grpc-allow-unknown-fields") {
            http_headers.push((
                "x-loom-grpc-allow-unknown-fields".to_string(),
                "true".to_string(),
            ));
        }
        if let Some(timeout_raw) = take_value(args, "--grpc-timeout-seconds") {
            let timeout_seconds = timeout_raw.parse::<u64>().map_err(|error| {
                format!(
                    "invalid --grpc-timeout-seconds '{}': {}",
                    timeout_raw, error
                )
            })?;
            if !(1..=120).contains(&timeout_seconds) {
                return Err(format!(
                    "shadow run --backend {} requires --grpc-timeout-seconds between 1 and 120",
                    if is_grpc_physical {
                        "grpc_physical"
                    } else {
                        "grpc_action"
                    }
                ));
            }
            http_headers.push((
                "x-loom-grpc-max-time-seconds".to_string(),
                timeout_seconds.to_string(),
            ));
        }
        if let Some(authority) = take_value(args, "--grpc-authority") {
            let authority = authority.trim();
            if authority.is_empty() {
                return Err(format!(
                    "shadow run --backend {} received empty --grpc-authority",
                    if is_grpc_physical {
                        "grpc_physical"
                    } else {
                        "grpc_action"
                    }
                ));
            }
            http_headers.push(("x-loom-grpc-authority".to_string(), authority.to_string()));
        }
        for import_path in take_values(args, "--grpc-import-path") {
            let import_path = import_path.trim();
            if import_path.is_empty() {
                return Err(format!(
                    "shadow run --backend {} received empty --grpc-import-path",
                    if is_grpc_physical {
                        "grpc_physical"
                    } else {
                        "grpc_action"
                    }
                ));
            }
            http_headers.push((
                "x-loom-grpc-import-path".to_string(),
                import_path.to_string(),
            ));
        }
        for proto in take_values(args, "--grpc-proto") {
            let proto = proto.trim();
            if proto.is_empty() {
                return Err(format!(
                    "shadow run --backend {} received empty --grpc-proto",
                    if is_grpc_physical {
                        "grpc_physical"
                    } else {
                        "grpc_action"
                    }
                ));
            }
            http_headers.push(("x-loom-grpc-proto".to_string(), proto.to_string()));
        }
        for protoset in take_values(args, "--grpc-protoset") {
            let protoset = protoset.trim();
            if protoset.is_empty() {
                return Err(format!(
                    "shadow run --backend {} received empty --grpc-protoset",
                    if is_grpc_physical {
                        "grpc_physical"
                    } else {
                        "grpc_action"
                    }
                ));
            }
            http_headers.push(("x-loom-grpc-protoset".to_string(), protoset.to_string()));
        }
    }
    let physical_robot_id = take_value(args, "--physical-robot-id");
    let physical_target = take_value(args, "--physical-target");
    let physical_command = take_value(args, "--physical-command");
    let physical_safety_class = take_value(args, "--physical-safety-class");
    let physical_dry_run = has_flag(args, "--physical-dry-run");
    let grpc_physical_lifecycle_mode =
        take_value(args, "--grpc-physical-lifecycle").unwrap_or_else(|| "unary".to_string());
    let grpc_physical_lifecycle_mode = grpc_physical_lifecycle_mode.trim().to_string();
    if is_grpc_physical
        && grpc_physical_lifecycle_mode != "unary"
        && grpc_physical_lifecycle_mode != "stream"
    {
        return Err(format!(
            "shadow run --backend grpc_physical expects --grpc-physical-lifecycle unary|stream, got '{}'",
            grpc_physical_lifecycle_mode
        ));
    }
    let grpc_physical_ack_required = has_flag(args, "--grpc-physical-ack-required");
    let grpc_physical_ack_timeout_seconds = take_value(args, "--grpc-physical-ack-timeout-seconds")
        .map(|raw| {
            raw.parse::<u64>().map_err(|error| {
                format!(
                    "invalid --grpc-physical-ack-timeout-seconds '{}': {}",
                    raw, error
                )
            })
        })
        .transpose()?;
    if is_grpc_physical {
        if grpc_physical_ack_required && grpc_physical_lifecycle_mode != "stream" {
            return Err(
                "shadow run --backend grpc_physical requires --grpc-physical-lifecycle stream when --grpc-physical-ack-required is set".to_string(),
            );
        }
        if let Some(timeout) = grpc_physical_ack_timeout_seconds {
            if !(1..=300).contains(&timeout) {
                return Err(
                    "shadow run --backend grpc_physical requires --grpc-physical-ack-timeout-seconds between 1 and 300".to_string(),
                );
            }
        }
    }
    let grpc_physical_cancel_on_ack_timeout =
        has_flag(args, "--grpc-physical-cancel-on-ack-timeout");
    let grpc_physical_cancel_after_seconds =
        take_value(args, "--grpc-physical-cancel-after-seconds")
            .map(|raw| {
                raw.parse::<u64>().map_err(|error| {
                    format!(
                        "invalid --grpc-physical-cancel-after-seconds '{}': {}",
                        raw, error
                    )
                })
            })
            .transpose()?;
    if is_grpc_physical {
        if let Some(cancel_after) = grpc_physical_cancel_after_seconds {
            if !(1..=600).contains(&cancel_after) {
                return Err(
                    "shadow run --backend grpc_physical requires --grpc-physical-cancel-after-seconds between 1 and 600".to_string(),
                );
            }
        }
    }
    let grpc_physical_remediation_profile = take_value(args, "--grpc-physical-remediation-profile")
        .unwrap_or_else(|| "standard".to_string());
    if is_grpc_physical && grpc_physical_remediation_profile.trim().is_empty() {
        return Err(
            "shadow run --backend grpc_physical requires non-empty --grpc-physical-remediation-profile".to_string(),
        );
    }
    if is_grpc_physical {
        if physical_robot_id
            .as_deref()
            .map(str::trim)
            .unwrap_or_default()
            .is_empty()
        {
            return Err(
                "shadow run --backend grpc_physical requires --physical-robot-id".to_string(),
            );
        }
        if physical_target
            .as_deref()
            .map(str::trim)
            .unwrap_or_default()
            .is_empty()
        {
            return Err(
                "shadow run --backend grpc_physical requires --physical-target".to_string(),
            );
        }
        if physical_command
            .as_deref()
            .map(str::trim)
            .unwrap_or_default()
            .is_empty()
        {
            return Err(
                "shadow run --backend grpc_physical requires --physical-command".to_string(),
            );
        }
        if physical_safety_class
            .as_deref()
            .map(str::trim)
            .unwrap_or_default()
            .is_empty()
        {
            return Err(
                "shadow run --backend grpc_physical requires --physical-safety-class".to_string(),
            );
        }
        http_headers.push((
            "x-loom-grpc-physical-lifecycle-mode".to_string(),
            grpc_physical_lifecycle_mode.clone(),
        ));
        http_headers.push((
            "x-loom-grpc-physical-ack-required".to_string(),
            if grpc_physical_ack_required {
                "true".to_string()
            } else {
                "false".to_string()
            },
        ));
        if let Some(timeout) = grpc_physical_ack_timeout_seconds {
            http_headers.push((
                "x-loom-grpc-physical-ack-timeout-seconds".to_string(),
                timeout.to_string(),
            ));
        }
        http_headers.push((
            "x-loom-grpc-physical-cancel-on-ack-timeout".to_string(),
            if grpc_physical_cancel_on_ack_timeout {
                "true".to_string()
            } else {
                "false".to_string()
            },
        ));
        if let Some(cancel_after) = grpc_physical_cancel_after_seconds {
            http_headers.push((
                "x-loom-grpc-physical-cancel-after-seconds".to_string(),
                cancel_after.to_string(),
            ));
        }
        http_headers.push((
            "x-loom-grpc-physical-remediation-profile".to_string(),
            grpc_physical_remediation_profile.trim().to_string(),
        ));
    }
    let http_body_json = if matches!(backend_kind, loom_shadow::ShadowBackendKind::Http) {
        take_value(args, "--body-json")
    } else if matches!(backend_kind, loom_shadow::ShadowBackendKind::Mcp) {
        let mcp_method =
            take_value(args, "--mcp-method").unwrap_or_else(|| "tools/list".to_string());
        let mcp_request_id = take_value(args, "--mcp-request-id")
            .unwrap_or_else(|| format!("loom-shadow-mcp-{}", chrono_like_timestamp()));
        let mcp_params_json =
            take_value(args, "--mcp-params-json").unwrap_or_else(|| "{}".to_string());
        let mcp_tool = take_value(args, "--mcp-tool");
        Some(build_shadow_mcp_request_json(
            &mcp_method,
            &mcp_request_id,
            &mcp_params_json,
            mcp_tool.as_deref(),
        )?)
    } else if matches!(backend_kind, loom_shadow::ShadowBackendKind::A2a) {
        let a2a_method =
            take_value(args, "--a2a-method").unwrap_or_else(|| "message/send".to_string());
        let a2a_request_id = take_value(args, "--a2a-request-id")
            .unwrap_or_else(|| format!("loom-shadow-a2a-{}", chrono_like_timestamp()));
        let a2a_params_json =
            take_value(args, "--a2a-params-json").unwrap_or_else(|| "{}".to_string());
        let a2a_skill = take_value(args, "--a2a-skill");
        Some(build_shadow_a2a_request_json(
            &a2a_method,
            &a2a_request_id,
            &a2a_params_json,
            a2a_skill.as_deref(),
        )?)
    } else if matches!(backend_kind, loom_shadow::ShadowBackendKind::A2aAction) {
        let a2a_action_request_id = take_value(args, "--a2a-action-request-id")
            .unwrap_or_else(|| format!("loom-shadow-a2a-action-{}", chrono_like_timestamp()));
        let a2a_action_kind =
            take_value(args, "--a2a-action-kind").unwrap_or_else(|| action_type.clone());
        let a2a_action_objective = take_value(args, "--a2a-action-objective")
            .unwrap_or_else(|| format!("execute {} on {}", action_type, resource));
        let a2a_context_json =
            take_value(args, "--a2a-context-json").unwrap_or_else(|| "{}".to_string());
        let a2a_constraints_json =
            take_value(args, "--a2a-constraints-json").unwrap_or_else(|| "{}".to_string());
        let a2a_memory_json =
            take_value(args, "--a2a-memory-json").unwrap_or_else(|| "[]".to_string());
        let a2a_skill = take_value(args, "--a2a-skill");
        Some(build_shadow_semantic_action_request_json(
            "a2a_action",
            &agent_id,
            &org_id,
            &warrant.id,
            &a2a_action_request_id,
            &a2a_action_kind,
            &a2a_action_objective,
            &a2a_context_json,
            &a2a_constraints_json,
            &a2a_memory_json,
            a2a_skill.as_deref(),
        )?)
    } else if is_grpc_action {
        let grpc_action_request_id = take_value(args, "--grpc-action-request-id")
            .unwrap_or_else(|| format!("loom-shadow-grpc-action-{}", chrono_like_timestamp()));
        let grpc_action_kind =
            take_value(args, "--grpc-action-kind").unwrap_or_else(|| action_type.clone());
        let grpc_action_objective = take_value(args, "--grpc-action-objective")
            .unwrap_or_else(|| format!("execute {} on {}", action_type, resource));
        let grpc_context_json =
            take_value(args, "--grpc-context-json").unwrap_or_else(|| "{}".to_string());
        let grpc_constraints_json =
            take_value(args, "--grpc-constraints-json").unwrap_or_else(|| "{}".to_string());
        let grpc_memory_json =
            take_value(args, "--grpc-memory-json").unwrap_or_else(|| "[]".to_string());
        let grpc_skill = take_value(args, "--grpc-skill");
        Some(build_shadow_semantic_action_request_json(
            "grpc_action",
            &agent_id,
            &org_id,
            &warrant.id,
            &grpc_action_request_id,
            &grpc_action_kind,
            &grpc_action_objective,
            &grpc_context_json,
            &grpc_constraints_json,
            &grpc_memory_json,
            grpc_skill.as_deref(),
        )?)
    } else if is_grpc_physical {
        let grpc_action_request_id = take_value(args, "--grpc-action-request-id")
            .unwrap_or_else(|| format!("loom-shadow-grpc-physical-{}", chrono_like_timestamp()));
        let grpc_action_kind =
            take_value(args, "--grpc-action-kind").unwrap_or_else(|| action_type.clone());
        let grpc_action_objective = take_value(args, "--grpc-action-objective")
            .unwrap_or_else(|| format!("execute {} on {}", action_type, resource));
        let grpc_context_json =
            take_value(args, "--grpc-context-json").unwrap_or_else(|| "{}".to_string());
        let grpc_constraints_json =
            take_value(args, "--grpc-constraints-json").unwrap_or_else(|| "{}".to_string());
        let grpc_memory_json =
            take_value(args, "--grpc-memory-json").unwrap_or_else(|| "[]".to_string());
        let grpc_skill = take_value(args, "--grpc-skill");
        Some(build_shadow_embodied_physical_request_json(
            "grpc_physical",
            &agent_id,
            &org_id,
            &warrant.id,
            &grpc_action_request_id,
            &grpc_action_kind,
            &grpc_action_objective,
            &grpc_context_json,
            &grpc_constraints_json,
            &grpc_memory_json,
            grpc_skill.as_deref(),
            physical_robot_id.as_deref().unwrap_or_default(),
            physical_target.as_deref().unwrap_or_default(),
            physical_command.as_deref().unwrap_or_default(),
            physical_safety_class.as_deref().unwrap_or_default(),
            physical_dry_run,
            &grpc_physical_lifecycle_mode,
            grpc_physical_ack_required,
            grpc_physical_ack_timeout_seconds,
            grpc_physical_cancel_on_ack_timeout,
            grpc_physical_cancel_after_seconds,
            grpc_physical_remediation_profile.trim(),
        )?)
    } else {
        None
    };
    let wasm_bytes = if matches!(backend_kind, loom_shadow::ShadowBackendKind::Wasmtime) {
        resolve_shadow_module_bytes(&module_source)?
    } else {
        Vec::new()
    };
    let effective_module_name = if let Some(program) = command_program.as_ref() {
        format!("command:{}", program)
    } else if matches!(backend_kind, loom_shadow::ShadowBackendKind::Mcp) {
        let method = take_value(args, "--mcp-method").unwrap_or_else(|| "tools/list".to_string());
        if let Some(url) = http_url.as_ref() {
            format!("mcp:{}:{}", method, url)
        } else {
            module_source
        }
    } else if matches!(backend_kind, loom_shadow::ShadowBackendKind::A2a) {
        let method = take_value(args, "--a2a-method").unwrap_or_else(|| "message/send".to_string());
        if let Some(url) = http_url.as_ref() {
            format!("a2a:{}:{}", method, url)
        } else {
            module_source
        }
    } else if matches!(backend_kind, loom_shadow::ShadowBackendKind::A2aAction) {
        let action_kind =
            take_value(args, "--a2a-action-kind").unwrap_or_else(|| action_type.clone());
        if let Some(url) = http_url.as_ref() {
            format!("a2a_action:{}:{}", action_kind, url)
        } else {
            module_source
        }
    } else if is_grpc_action {
        let action_kind =
            take_value(args, "--grpc-action-kind").unwrap_or_else(|| action_type.clone());
        if let Some(url) = http_url.as_ref() {
            format!(
                "grpc_action:{}:{}:{}",
                http_method
                    .as_deref()
                    .unwrap_or("meridian.runtime.v1.ActionService/SubmitAction"),
                action_kind,
                url
            )
        } else {
            module_source
        }
    } else if is_grpc_physical {
        let action_kind =
            take_value(args, "--grpc-action-kind").unwrap_or_else(|| action_type.clone());
        if let Some(url) = http_url.as_ref() {
            format!(
                "grpc_physical:{}:{}:{}",
                http_method
                    .as_deref()
                    .unwrap_or("meridian.embodied.action.v1.PhysicalActionService/Execute"),
                action_kind,
                url
            )
        } else {
            module_source
        }
    } else if let Some(url) = http_url.as_ref() {
        format!(
            "http:{}:{}",
            http_method.as_deref().unwrap_or("GET").to_uppercase(),
            url
        )
    } else {
        module_source
    };
    let capture = loom_shadow::run_shadow_backend(&loom_shadow::ShadowRunRequest {
        root: root.clone(),
        kernel_path: PathBuf::from(&kernel_path),
        backend: backend_kind,
        agent_id,
        org_id,
        action_type,
        resource,
        module_name: effective_module_name,
        entrypoint,
        fuel_budget,
        warrant,
        wasm_bytes,
        command_program,
        command_args,
        http_url,
        http_method,
        http_headers,
        http_body_json,
    })?;

    if format == "json" {
        println!("{}", loom_shadow::render_shadow_run_capture_json(&capture));
    } else {
        print_human(&loom_shadow::render_shadow_run_capture_human(
            &capture,
            &root,
            Path::new(&kernel_path),
        ));
    }
    Ok(())
}

fn resolve_shadow_module_bytes(module_source: &str) -> LoomResult<Vec<u8>> {
    match module_source {
        "builtin:minimal" => Ok(crate::commands::wasm::builtin_minimal_wasm_module()),
        "builtin:system.info" => loom_core::wasm_host::builtin_system_info_guest_bytes(
            &loom_core::wasm_host::render_wasm_system_info_request_json(
                &loom_core::wasm_host::WasmSystemInfoRequest::default(),
            ),
        ),
        "builtin:terminal.exec" => {
            let request = loom_core::wasm_host::WasmTerminalExecRequest {
                argv: vec!["echo".to_string(), "loom-shadow".to_string()],
                ..loom_core::wasm_host::WasmTerminalExecRequest::default()
            };
            loom_core::wasm_host::builtin_terminal_exec_guest_bytes(
                &loom_core::wasm_host::render_wasm_terminal_exec_request_json(&request),
            )
        }
        value if value.starts_with("wasm:") => {
            fs::read(value.trim_start_matches("wasm:")).map_err(|e| e.to_string())
        }
        other => Err(format!("unsupported shadow module '{}'", other)),
    }
}

fn read_kernel_warrant(path: &Path) -> LoomResult<loom_poge::KernelWarrant> {
    let raw = fs::read_to_string(path)
        .map_err(|e| format!("failed to read warrant file {}: {}", path.display(), e))?;
    let value: Value = serde_json::from_str(&raw)
        .map_err(|e| format!("invalid warrant json {}: {}", path.display(), e))?;
    Ok(loom_poge::KernelWarrant {
        id: decode_hex_fixed::<32>(
            value
                .get("id_hex")
                .and_then(Value::as_str)
                .ok_or_else(|| "warrant file missing id_hex".to_string())?,
            "id_hex",
        )?,
        scope_cbor: hex::decode(
            value
                .get("scope_cbor_hex")
                .and_then(Value::as_str)
                .ok_or_else(|| "warrant file missing scope_cbor_hex".to_string())?,
        )
        .map_err(|e| format!("invalid scope_cbor_hex: {}", e))?,
        expiry_epoch_ms: value
            .get("expiry_epoch_ms")
            .and_then(Value::as_u64)
            .ok_or_else(|| "warrant file missing expiry_epoch_ms".to_string())?,
        kernel_sig: decode_hex_fixed::<64>(
            value
                .get("kernel_sig_hex")
                .and_then(Value::as_str)
                .ok_or_else(|| "warrant file missing kernel_sig_hex".to_string())?,
            "kernel_sig_hex",
        )?,
        kernel_pub: decode_hex_fixed::<32>(
            value
                .get("kernel_pub_hex")
                .and_then(Value::as_str)
                .ok_or_else(|| "warrant file missing kernel_pub_hex".to_string())?,
            "kernel_pub_hex",
        )?,
    })
}

fn decode_hex_fixed<const N: usize>(value: &str, label: &str) -> LoomResult<[u8; N]> {
    let trimmed = value.trim().trim_start_matches("0x");
    let bytes = hex::decode(trimmed).map_err(|e| format!("invalid {}: {}", label, e))?;
    if bytes.len() != N {
        return Err(format!(
            "{} expected {} bytes, got {}",
            label,
            N,
            bytes.len()
        ));
    }
    let mut out = [0u8; N];
    out.copy_from_slice(&bytes);
    Ok(out)
}

fn parse_shadow_http_headers(values: &[String]) -> LoomResult<Vec<(String, String)>> {
    values
        .iter()
        .map(|value| {
            let (name, raw_value) = value
                .split_once(':')
                .ok_or_else(|| format!("invalid --header '{}': expected Name: Value", value))?;
            let name = name.trim();
            let header_value = raw_value.trim();
            if name.is_empty() {
                return Err(format!(
                    "invalid --header '{}': header name is empty",
                    value
                ));
            }
            Ok((name.to_string(), header_value.to_string()))
        })
        .collect()
}

fn build_shadow_mcp_request_json(
    method: &str,
    request_id: &str,
    params_json: &str,
    tool_name: Option<&str>,
) -> LoomResult<String> {
    let mut params: Value = serde_json::from_str(params_json)
        .map_err(|error| format!("invalid --mcp-params-json: {error}"))?;
    if method == "tools/call" {
        match &mut params {
            Value::Object(map) => {
                if let Some(tool) = tool_name.filter(|value| !value.trim().is_empty()) {
                    map.entry("name".to_string())
                        .or_insert_with(|| Value::String(tool.trim().to_string()));
                }
                if map
                    .get("name")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .trim()
                    .is_empty()
                {
                    return Err(
                        "shadow run --backend mcp with --mcp-method tools/call requires --mcp-tool or params.name"
                            .to_string(),
                    );
                }
            }
            _ => {
                return Err(
                    "shadow run --backend mcp expects --mcp-params-json to be a JSON object"
                        .to_string(),
                )
            }
        }
    }
    let payload = serde_json::json!({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    });
    serde_json::to_string(&payload)
        .map_err(|error| format!("failed to serialize mcp request json: {error}"))
}

fn build_shadow_a2a_request_json(
    method: &str,
    request_id: &str,
    params_json: &str,
    skill_name: Option<&str>,
) -> LoomResult<String> {
    let mut params: Value = serde_json::from_str(params_json)
        .map_err(|error| format!("invalid --a2a-params-json: {error}"))?;
    let params_map = params.as_object_mut().ok_or_else(|| {
        "shadow run --backend a2a expects --a2a-params-json to be a JSON object".to_string()
    })?;
    if let Some(skill) = skill_name.map(str::trim).filter(|value| !value.is_empty()) {
        params_map
            .entry("skill".to_string())
            .or_insert_with(|| Value::String(skill.to_string()));
    }
    let payload = serde_json::json!({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    });
    serde_json::to_string(&payload)
        .map_err(|error| format!("failed to serialize a2a request json: {error}"))
}

fn build_shadow_semantic_action_request_json(
    backend_label: &str,
    agent_id: &str,
    org_id: &str,
    warrant_id: &[u8; 32],
    request_id: &str,
    action_kind: &str,
    action_objective: &str,
    context_json: &str,
    constraints_json: &str,
    memory_json: &str,
    skill_name: Option<&str>,
) -> LoomResult<String> {
    let context: Value = serde_json::from_str(context_json)
        .map_err(|error| format!("invalid context JSON: {error}"))?;
    if !context.is_object() {
        return Err(format!(
            "shadow run --backend {} expects context JSON to be a JSON object",
            backend_label
        ));
    }
    let constraints: Value = serde_json::from_str(constraints_json)
        .map_err(|error| format!("invalid constraints JSON: {error}"))?;
    if !constraints.is_object() {
        return Err(format!(
            "shadow run --backend {} expects constraints JSON to be a JSON object",
            backend_label
        ));
    }
    let recall_refs: Value = serde_json::from_str(memory_json)
        .map_err(|error| format!("invalid memory JSON: {error}"))?;
    if !recall_refs.is_array() {
        return Err(format!(
            "shadow run --backend {} expects memory JSON to be a JSON array",
            backend_label
        ));
    }
    let action_kind = action_kind.trim();
    if action_kind.is_empty() {
        return Err(format!(
            "shadow run --backend {} requires non-empty action kind",
            backend_label
        ));
    }
    let action_objective = action_objective.trim();
    if action_objective.is_empty() {
        return Err(format!(
            "shadow run --backend {} requires non-empty action objective",
            backend_label
        ));
    }
    let mut action = serde_json::Map::new();
    action.insert("kind".to_string(), Value::String(action_kind.to_string()));
    action.insert(
        "objective".to_string(),
        Value::String(action_objective.to_string()),
    );
    if let Some(skill) = skill_name.map(str::trim).filter(|value| !value.is_empty()) {
        action.insert("skill".to_string(), Value::String(skill.to_string()));
    }
    let payload = serde_json::json!({
        "schema": "meridian.a2a.action.v1",
        "request_id": request_id,
        "actor": {
            "agent_id": agent_id,
            "org_id": org_id,
        },
        "action": action,
        "context": context,
        "memory": {
            "recall_refs": recall_refs,
        },
        "constraints": constraints,
        "governance": {
            "warrant_id_hex": format!("0x{}", hex::encode(warrant_id)),
            "proof_required": true,
            "settlement_mode": "treasury_gated",
        }
    });
    serde_json::to_string(&payload)
        .map_err(|error| format!("failed to serialize semantic action request json: {error}"))
}

#[allow(clippy::too_many_arguments)]
fn build_shadow_embodied_physical_request_json(
    backend_label: &str,
    agent_id: &str,
    org_id: &str,
    warrant_id: &[u8; 32],
    request_id: &str,
    action_kind: &str,
    action_objective: &str,
    context_json: &str,
    constraints_json: &str,
    memory_json: &str,
    skill_name: Option<&str>,
    physical_robot_id: &str,
    physical_target: &str,
    physical_command: &str,
    physical_safety_class: &str,
    physical_dry_run: bool,
    lifecycle_mode: &str,
    lifecycle_ack_required: bool,
    lifecycle_ack_timeout_seconds: Option<u64>,
    lifecycle_cancel_on_ack_timeout: bool,
    lifecycle_cancel_after_seconds: Option<u64>,
    remediation_profile: &str,
) -> LoomResult<String> {
    let context: Value = serde_json::from_str(context_json)
        .map_err(|error| format!("invalid context JSON: {error}"))?;
    if !context.is_object() {
        return Err(format!(
            "shadow run --backend {} expects context JSON to be a JSON object",
            backend_label
        ));
    }
    let constraints: Value = serde_json::from_str(constraints_json)
        .map_err(|error| format!("invalid constraints JSON: {error}"))?;
    if !constraints.is_object() {
        return Err(format!(
            "shadow run --backend {} expects constraints JSON to be a JSON object",
            backend_label
        ));
    }
    let recall_refs: Value = serde_json::from_str(memory_json)
        .map_err(|error| format!("invalid memory JSON: {error}"))?;
    if !recall_refs.is_array() {
        return Err(format!(
            "shadow run --backend {} expects memory JSON to be a JSON array",
            backend_label
        ));
    }
    let action_kind = action_kind.trim();
    if action_kind.is_empty() {
        return Err(format!(
            "shadow run --backend {} requires non-empty action kind",
            backend_label
        ));
    }
    let action_objective = action_objective.trim();
    if action_objective.is_empty() {
        return Err(format!(
            "shadow run --backend {} requires non-empty action objective",
            backend_label
        ));
    }
    let physical_robot_id = physical_robot_id.trim();
    let physical_target = physical_target.trim();
    let physical_command = physical_command.trim();
    let physical_safety_class = physical_safety_class.trim();
    if physical_robot_id.is_empty()
        || physical_target.is_empty()
        || physical_command.is_empty()
        || physical_safety_class.is_empty()
    {
        return Err(format!(
            "shadow run --backend {} requires non-empty physical robot/target/command/safety fields",
            backend_label
        ));
    }
    let lifecycle_mode = lifecycle_mode.trim();
    if lifecycle_mode.is_empty() {
        return Err(format!(
            "shadow run --backend {} requires non-empty lifecycle mode",
            backend_label
        ));
    }
    let remediation_profile = remediation_profile.trim();
    if remediation_profile.is_empty() {
        return Err(format!(
            "shadow run --backend {} requires non-empty remediation profile",
            backend_label
        ));
    }

    let mut action = serde_json::Map::new();
    action.insert("kind".to_string(), Value::String(action_kind.to_string()));
    action.insert(
        "objective".to_string(),
        Value::String(action_objective.to_string()),
    );
    if let Some(skill) = skill_name.map(str::trim).filter(|value| !value.is_empty()) {
        action.insert("skill".to_string(), Value::String(skill.to_string()));
    }
    let payload = serde_json::json!({
        "schema": "meridian.embodied.action.v1",
        "request_id": request_id,
        "actor": {
            "agent_id": agent_id,
            "org_id": org_id,
        },
        "action": action,
        "physical": {
            "robot_id": physical_robot_id,
            "target": physical_target,
            "command": physical_command,
            "safety_class": physical_safety_class,
            "dry_run": physical_dry_run,
        },
        "lifecycle": {
            "mode": lifecycle_mode,
            "ack_required": lifecycle_ack_required,
            "ack_timeout_seconds": lifecycle_ack_timeout_seconds,
            "cancel_on_ack_timeout": lifecycle_cancel_on_ack_timeout,
            "cancel_after_seconds": lifecycle_cancel_after_seconds,
        },
        "remediation": {
            "profile": remediation_profile,
        },
        "context": context,
        "memory": {
            "recall_refs": recall_refs,
        },
        "constraints": constraints,
        "governance": {
            "warrant_id_hex": format!("0x{}", hex::encode(warrant_id)),
            "proof_required": true,
            "settlement_mode": "treasury_gated",
        }
    });
    serde_json::to_string(&payload)
        .map_err(|error| format!("failed to serialize embodied physical request json: {error}"))
}
