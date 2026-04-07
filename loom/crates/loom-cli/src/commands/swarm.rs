use crate::*;
use loom_poge::ZkProofBackend;
use serde_json::{json, Value};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::Path;

pub(crate) fn handle_swarm(args: &[String]) -> LoomResult<()> {
    match args.first().map(String::as_str) {
        Some("run") => handle_swarm_run(&args[1..]),
        _ => Err("swarm supports 'run'".to_string()),
    }
}

fn handle_swarm_run(args: &[String]) -> LoomResult<()> {
    if !has_flag(args, "--settle-zk") {
        return Err("swarm run currently requires --settle-zk".to_string());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let config = read_config(&root)?;
    let kernel_path = required_flag(args, "--kernel-path")?;
    let agent_id = required_flag(args, "--agent-id")?;
    let org_id = take_value(args, "--org-id").unwrap_or_else(|| config.org_id.clone());
    let action_type = take_value(args, "--action-type").unwrap_or_else(|| "research".to_string());
    let resource = take_value(args, "--resource").unwrap_or_else(|| "system_info".to_string());
    let module_source =
        take_value(args, "--module").unwrap_or_else(|| "builtin:system.info".to_string());
    let entrypoint = take_value(args, "--entrypoint").unwrap_or_else(|| "run".to_string());
    let fuel_budget = take_value(args, "--fuel-budget")
        .map(|raw| {
            raw.parse::<u64>()
                .map_err(|error| format!("invalid --fuel-budget '{}': {}", raw, error))
        })
        .transpose()?
        .unwrap_or(100_000);
    let estimated_cost_usd = parse_f64_flag(args, "--estimated-cost-usd").unwrap_or(0.0);
    let actual_cost_usd = required_flag(args, "--actual-cost-usd")?
        .parse::<f64>()
        .map_err(|error| format!("invalid --actual-cost-usd: {}", error))?;
    let zk_backend = take_value(args, "--zk-backend")
        .unwrap_or_else(|| "sp1".to_string())
        .parse::<ZkProofBackend>()
        .map_err(|error| format!("invalid --zk-backend: {}", error))?;
    let run_id = take_value(args, "--run-id");
    let session_id = take_value(args, "--session-id");
    let payload_json = take_value(args, "--payload-json");
    let warrant_file = required_flag(args, "--warrant-file")?;
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());

    let effective_kernel_path = kernel_path_for(&root, Some(&kernel_path))?;
    let envelope = build_action_envelope_with_options(
        &root,
        Some(&kernel_path),
        &agent_id,
        Some(&org_id),
        &action_type,
        &resource,
        estimated_cost_usd,
        run_id.as_deref(),
        session_id.as_deref(),
        None,
        payload_json.as_deref(),
    )?;

    let enqueued = enqueue_action(&root, &effective_kernel_path, &envelope)?;
    let queue_summary = run_queue_once(&root, Some(&kernel_path))?;

    let warrant = read_kernel_warrant(Path::new(&warrant_file))?;
    let wasm_bytes = resolve_shadow_module_bytes(&module_source)?;
    let shadow_capture = loom_shadow::run_shadow_backend(&loom_shadow::ShadowRunRequest {
        root: root.clone(),
        kernel_path: effective_kernel_path.clone(),
        backend: loom_shadow::ShadowBackendKind::Wasmtime,
        agent_id: agent_id.clone(),
        org_id: org_id.clone(),
        action_type: action_type.clone(),
        resource: resource.clone(),
        module_name: module_source.clone(),
        entrypoint,
        fuel_budget,
        warrant,
        wasm_bytes,
        command_program: None,
        command_args: Vec::new(),
        http_url: None,
        http_method: None,
        http_headers: Vec::new(),
        http_body_json: None,
    })?;

    let settlement = crate::commands::job::settle_latest_execution_with_zk(
        &root,
        &kernel_path,
        actual_cost_usd,
        zk_backend,
    )?;

    let settlement_status = settlement
        .settlement_payload
        .get("settlement_status")
        .and_then(Value::as_str)
        .unwrap_or("unknown")
        .to_string();
    let treasury_status = settlement
        .settlement_payload
        .get("treasury_status")
        .and_then(Value::as_str)
        .unwrap_or("unknown")
        .to_string();
    let proof_backend = settlement
        .settlement_payload
        .get("proof_backend")
        .and_then(Value::as_str)
        .unwrap_or(zk_backend.as_str())
        .to_string();
    let proof_id = settlement
        .settlement_payload
        .get("proof_id")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let reservation_id = settlement
        .settlement_payload
        .get("reservation_id")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let witness_digest_hex = settlement
        .settlement_payload
        .get("witness_digest_hex")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let poge_merkle_root_hex = settlement
        .settlement_payload
        .get("poge_merkle_root_hex")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();

    let artifacts_root = root.join(&config.artifact_dir);
    let swarm_dir = artifacts_root.join("swarm");
    fs::create_dir_all(&swarm_dir).map_err(|error| error.to_string())?;
    let swarm_latest_path = swarm_dir.join("latest.json");
    let swarm_stream_path = swarm_dir.join("stream.jsonl");

    let payload = json!({
        "status": "swarm_run_settled",
        "captured_at": chrono_like_timestamp(),
        "agent_id": agent_id,
        "org_id": org_id,
        "action_type": action_type,
        "resource": resource,
        "estimated_cost_usd": estimated_cost_usd,
        "actual_cost_usd": actual_cost_usd,
        "proof_backend": proof_backend,
        "proof_id": proof_id,
        "settlement_status": settlement_status,
        "treasury_status": treasury_status,
        "reservation_id": reservation_id,
        "witness_digest_hex": witness_digest_hex,
        "poge_merkle_root_hex": poge_merkle_root_hex,
        "queue_status": "queue_run_once_complete",
        "queue": {
            "requested": queue_summary.requested,
            "pending_before": queue_summary.pending_before,
            "pending_after": queue_summary.pending_after,
            "processed_jobs": queue_summary.processed_jobs,
            "failed_jobs": queue_summary.failed_jobs,
            "acked_jobs": queue_summary.acked_jobs,
            "progress_path": queue_summary.progress_path.display().to_string(),
        },
        "shadow": {
            "status": shadow_capture.status,
            "backend": shadow_capture.backend,
            "warrant_binding_status": shadow_capture.warrant_binding_status,
            "warrant_id_hex": shadow_capture.warrant_id_hex,
            "poge_merkle_root_hex": shadow_capture.poge_merkle_root_hex,
            "execution_path": shadow_capture.execution_path.display().to_string(),
            "shadow_latest_path": shadow_capture.shadow_latest_path.display().to_string(),
            "parity_latest_path": shadow_capture.parity_latest_path.display().to_string(),
        },
        "enqueued_action": {
            "job_id": enqueued.input_hash,
            "policy_class": enqueued.policy_class,
            "queue_path": enqueued.queue_path.display().to_string(),
            "job_path": enqueued.job_path.display().to_string(),
        },
        "paths": {
            "swarm_latest_path": swarm_latest_path.display().to_string(),
            "swarm_stream_path": swarm_stream_path.display().to_string(),
            "zk_latest_path": settlement.zk_latest_path.display().to_string(),
            "settlement_latest_path": settlement.settlement_latest_path.display().to_string(),
        },
        "note": "one-command swarm flow: enqueue -> run queue -> shadow proof -> settle --zk",
    });
    write_pretty_json(&swarm_latest_path, &payload)?;
    append_jsonl(&swarm_stream_path, &payload)?;

    if format == "json" {
        println!(
            "{}",
            serde_json::to_string_pretty(&payload).map_err(|error| error.to_string())?
        );
    } else {
        print_human(&format!(
            "Meridian Loom // SWARM RUN\n===========================\nstatus:             {}\nproof_backend:      {}\nsettlement_status:  {}\ntreasury_status:    {}\nreservation_id:     {}\nqueue_before:       {}\nqueue_after:        {}\nprocessed_jobs:     {}\nfailed_jobs:        {}\nshadow_warrant:     {}\nwitness_digest:     {}\nswarm_latest_path:  {}\n\nNext\n====\n- loom shadow report --root {}\n- loom parity report --root {}\n- inspect {}\n",
            payload.get("status").and_then(Value::as_str).unwrap_or("unknown"),
            payload.get("proof_backend").and_then(Value::as_str).unwrap_or("unknown"),
            payload.get("settlement_status").and_then(Value::as_str).unwrap_or("unknown"),
            payload.get("treasury_status").and_then(Value::as_str).unwrap_or("unknown"),
            payload.get("reservation_id").and_then(Value::as_str).unwrap_or("(none)"),
            payload.get("queue").and_then(|v| v.get("pending_before")).and_then(Value::as_u64).unwrap_or(0),
            payload.get("queue").and_then(|v| v.get("pending_after")).and_then(Value::as_u64).unwrap_or(0),
            payload.get("queue").and_then(|v| v.get("processed_jobs")).and_then(Value::as_u64).unwrap_or(0),
            payload.get("queue").and_then(|v| v.get("failed_jobs")).and_then(Value::as_u64).unwrap_or(0),
            payload.get("shadow").and_then(|v| v.get("warrant_binding_status")).and_then(Value::as_str).unwrap_or("unknown"),
            payload.get("witness_digest_hex").and_then(Value::as_str).unwrap_or("(missing)"),
            swarm_latest_path.display(),
            root.display(),
            root.display(),
            swarm_latest_path.display(),
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
                argv: vec!["echo".to_string(), "loom-swarm".to_string()],
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
        .map_err(|error| format!("failed to read warrant file {}: {}", path.display(), error))?;
    let value: Value = serde_json::from_str(&raw)
        .map_err(|error| format!("invalid warrant json {}: {}", path.display(), error))?;
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
        .map_err(|error| format!("invalid scope_cbor_hex: {}", error))?,
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
    let bytes = hex::decode(trimmed).map_err(|error| format!("invalid {}: {}", label, error))?;
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

fn write_pretty_json(path: &Path, value: &Value) -> LoomResult<()> {
    let body = serde_json::to_string_pretty(value).map_err(|error| error.to_string())?;
    fs::write(path, format!("{}\n", body)).map_err(|error| error.to_string())
}

fn append_jsonl(path: &Path, value: &Value) -> LoomResult<()> {
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|error| error.to_string())?;
    let line = serde_json::to_string(value).map_err(|error| error.to_string())?;
    writeln!(file, "{}", line).map_err(|error| error.to_string())
}
