use crate::*;
use loom_poge::{PoGEAuditRoot, ZkPoGEProof, ZkProofBackend};
use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

#[derive(Clone, Debug)]
pub(crate) struct JobSettleZkCapture {
    pub settlement_payload: Value,
    pub zk_latest_path: PathBuf,
    pub settlement_latest_path: PathBuf,
}

pub(crate) fn handle_job(args: &[String]) -> LoomResult<()> {
    match args.first().map(String::as_str) {
        Some("list") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let status_filter = take_value(args, "--status");
            let limit = take_value(args, "--limit")
                .and_then(|raw| raw.parse::<usize>().ok())
                .unwrap_or(20);
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let jobs = list_jobs(&root, status_filter.as_deref(), limit)?;
            if format == "json" {
                print!("{}", render_job_list_json(&jobs));
            } else {
                print_human(&render_job_list_human(
                    &root,
                    &jobs,
                    status_filter.as_deref(),
                ));
            }
            Ok(())
        }
        Some("inspect") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let job_id = required_flag(args, "--job-id")?;
            let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
            let snapshot = inspect_job(&root, &job_id)?;
            if format == "json" {
                print!("{}", render_job_inspect_json(&snapshot));
            } else {
                print_human(&render_job_inspect_human(&snapshot));
            }
            Ok(())
        }
        Some("approve") => {
            let root = root_from(take_value(args, "--root").as_deref())?;
            let job_id = required_flag(args, "--job-id")?;
            let result = approve_job(&root, &job_id)?;
            println!("{}", result);
            Ok(())
        }
        Some("settle") => handle_job_settle(&args[1..]),
        _ => Err("job supports 'list', 'inspect', 'approve', and 'settle'".to_string()),
    }
}

fn handle_job_settle(args: &[String]) -> LoomResult<()> {
    if !has_flag(args, "--zk") {
        return Err("job settle currently requires --zk".to_string());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let kernel_path = required_flag(args, "--kernel-path")?;
    let actual_cost_usd = required_flag(args, "--actual-cost-usd")?
        .parse::<f64>()
        .map_err(|error| format!("invalid --actual-cost-usd: {}", error))?;
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let zk_backend = take_value(args, "--zk-backend")
        .unwrap_or_else(|| "sp1".to_string())
        .parse::<ZkProofBackend>()
        .map_err(|error| format!("invalid --zk-backend: {}", error))?;
    let capture =
        settle_latest_execution_with_zk(&root, &kernel_path, actual_cost_usd, zk_backend)?;

    if format == "json" {
        println!(
            "{}",
            serde_json::to_string_pretty(&capture.settlement_payload)
                .map_err(|error| error.to_string())?
        );
    } else {
        print_human(&render_job_settle_zk_human(
            &capture.settlement_payload,
            &capture.zk_latest_path,
            &capture.settlement_latest_path,
            &root,
        ));
    }

    Ok(())
}

pub(crate) fn settle_latest_execution_with_zk(
    root: &Path,
    kernel_path: &str,
    actual_cost_usd: f64,
    zk_backend: ZkProofBackend,
) -> LoomResult<JobSettleZkCapture> {
    let config = read_config(root)?;
    let runtime_execution_path = root
        .join(&config.state_dir)
        .join("runtime")
        .join("last_execution.json");
    let execution = read_json_file(&runtime_execution_path)?;
    let requested_agent_ref = required_json_string(&execution, "agent_id")?;
    let org_id = execution
        .get("org_id")
        .and_then(Value::as_str)
        .unwrap_or(&config.org_id)
        .to_string();
    let action_type = execution
        .get("action_type")
        .and_then(Value::as_str)
        .unwrap_or("unknown")
        .to_string();
    let resource = execution
        .get("resource")
        .and_then(Value::as_str)
        .unwrap_or("unknown")
        .to_string();
    let warrant_binding_status = execution
        .get("warrant_binding_status")
        .and_then(Value::as_str)
        .unwrap_or("missing")
        .to_string();
    if warrant_binding_status != "verified" {
        return Err(format!(
            "job settle --zk requires a verified warrant-bound execution, got '{}'",
            warrant_binding_status
        ));
    }

    let agent_refs =
        resolve_settlement_agent_refs(root, kernel_path, &requested_agent_ref, &org_id)?;
    let audit_root = audit_root_from_execution(&execution)?;
    let proof = ZkPoGEProof::prepare(&audit_root, &warrant_binding_status, zk_backend);
    let captured_at = chrono_like_timestamp();
    let kernel_path_buf = PathBuf::from(kernel_path);
    let court = query_court_status(&kernel_path_buf, &agent_refs.authority_agent_ref, &org_id)?;
    let authority =
        query_authority_status(&kernel_path_buf, &agent_refs.authority_agent_ref, &org_id)?;

    let artifacts_root = root.join(&config.artifact_dir);
    let zk_dir = artifacts_root.join("zk");
    let settlement_dir = artifacts_root.join("settlement");
    fs::create_dir_all(&zk_dir).map_err(|error| error.to_string())?;
    fs::create_dir_all(&settlement_dir).map_err(|error| error.to_string())?;

    let zk_latest_path = zk_dir.join("latest.json");
    let zk_stream_path = zk_dir.join("stream.jsonl");
    let settlement_latest_path = settlement_dir.join("latest.json");
    let settlement_stream_path = settlement_dir.join("stream.jsonl");

    let proof_payload = json!({
        "status": "zk_proof_prepared",
        "proof_backend": proof.proof_backend.as_str(),
        "proof_mode": proof.proof_mode,
        "proof_id": proof.proof_id,
        "captured_at": captured_at,
        "verification_status": proof.verification_status,
        "agent_id": agent_refs.canonical_agent_id,
        "requested_agent_ref": requested_agent_ref,
        "authority_agent_ref": agent_refs.authority_agent_ref,
        "treasury_agent_ref": agent_refs.treasury_agent_ref,
        "economy_key": agent_refs.economy_key,
        "agent_resolution_source": agent_refs.resolution_source,
        "org_id": org_id,
        "action_type": action_type,
        "resource": resource,
        "warrant_binding_status": proof.warrant_binding_status,
        "warrant_id_hex": proof.warrant_id_hex,
        "poge_merkle_root_hex": proof.merkle_root_hex,
        "witness_digest_hex": proof.witness_digest_hex,
        "poge_trace_len": proof.trace_len,
        "poge_epoch_start_ms": proof.epoch_start_ms,
        "poge_epoch_end_ms": proof.epoch_end_ms,
        "poge_session_label": proof.session_label,
        "runtime_execution_path": runtime_execution_path.display().to_string(),
        "kernel_path": kernel_path,
        "note": "The selected zk backend prepares a bounded proof artifact that binds and verifies the PoGE witness before settlement without claiming on-chain finality."
    });
    write_pretty_json(&zk_latest_path, &proof_payload)?;
    append_jsonl(&zk_stream_path, &proof_payload)?;

    let (treasury_status, treasury_reason, reservation_id, settlement_status) =
        if court.status == "blocked" || authority.status == "denied" {
            (
                "skipped".to_string(),
                if court.status == "blocked" {
                    "court restriction prevents settlement".to_string()
                } else {
                    authority.reason.clone()
                },
                None,
                if court.status == "blocked" {
                    "blocked_by_court".to_string()
                } else {
                    "blocked_by_authority".to_string()
                },
            )
        } else {
            let reserve = reserve_treasury_budget(
                &kernel_path_buf,
                &agent_refs.treasury_agent_ref,
                &org_id,
                &action_type,
                &resource,
                actual_cost_usd,
            )?;
            let allowed = reserve
                .get("allowed")
                .and_then(Value::as_bool)
                .unwrap_or(true);
            let reservation_id = extract_treasury_reservation_id(&reserve);
            if !allowed {
                (
                    "blocked".to_string(),
                    reserve
                        .get("reason")
                        .and_then(Value::as_str)
                        .unwrap_or("treasury reserve rejected")
                        .to_string(),
                    reservation_id,
                    "blocked_by_treasury".to_string(),
                )
            } else {
                let reservation_id_value = reservation_id
                    .clone()
                    .ok_or_else(|| "treasury reserve did not return reservation_id".to_string())?;
                let commit = commit_treasury_budget(
                    &kernel_path_buf,
                    &reservation_id_value,
                    actual_cost_usd,
                    "loom.job.settle --zk",
                )?;
                (
                    commit
                        .get("status")
                        .and_then(Value::as_str)
                        .unwrap_or("unknown")
                        .to_string(),
                    commit
                        .get("commit_reason")
                        .and_then(Value::as_str)
                        .unwrap_or("committed")
                        .to_string(),
                    Some(reservation_id_value),
                    "prepared".to_string(),
                )
            }
        };

    let settlement_payload = json!({
        "status": "zk_settlement_captured",
        "captured_at": captured_at,
        "proof_backend": proof.proof_backend.as_str(),
        "proof_status": "prepared",
        "proof_id": proof_payload.get("proof_id").and_then(Value::as_str).unwrap_or_default(),
        "court_status": court.status,
        "court_reason": court.reason,
        "court_restrictions": court.restrictions,
        "authority_status": authority.status,
        "authority_reason": authority.reason,
        "treasury_status": treasury_status,
        "treasury_reason": treasury_reason,
        "reservation_id": reservation_id,
        "settlement_status": settlement_status,
        "agent_id": agent_refs.canonical_agent_id,
        "requested_agent_ref": requested_agent_ref,
        "authority_agent_ref": agent_refs.authority_agent_ref,
        "treasury_agent_ref": agent_refs.treasury_agent_ref,
        "economy_key": agent_refs.economy_key,
        "agent_resolution_source": agent_refs.resolution_source,
        "org_id": org_id,
        "action_type": action_type,
        "resource": resource,
        "actual_cost_usd": actual_cost_usd,
        "warrant_id_hex": proof.warrant_id_hex,
        "witness_digest_hex": proof.witness_digest_hex,
        "poge_merkle_root_hex": proof.merkle_root_hex,
        "runtime_execution_path": runtime_execution_path.display().to_string(),
        "zk_proof_path": zk_latest_path.display().to_string(),
        "kernel_path": kernel_path,
        "note": "Court and Treasury were evaluated in-process for this settlement slice. Final chain submission is not claimed until a chain adapter confirms it."
    });
    write_pretty_json(&settlement_latest_path, &settlement_payload)?;
    append_jsonl(&settlement_stream_path, &settlement_payload)?;

    Ok(JobSettleZkCapture {
        settlement_payload,
        zk_latest_path,
        settlement_latest_path,
    })
}

fn render_job_settle_zk_human(
    settlement_payload: &Value,
    zk_latest_path: &Path,
    settlement_latest_path: &Path,
    root: &Path,
) -> String {
    format!(
        "Meridian Loom // JOB SETTLE ZK\n===============================\nstatus:             {}\nproof_backend:      {}\ncourt_status:       {}\nauthority_status:   {}\ntreasury_status:    {}\nsettlement_status:  {}\nreservation_id:     {}\nwitness_digest:     {}\nzk_proof_path:      {}\nsettlement_path:    {}\n\nNext\n====\n1. loom shadow report --root {}\n2. loom parity report --root {}\n",
        settlement_payload
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("unknown"),
        settlement_payload
            .get("proof_backend")
            .and_then(Value::as_str)
            .unwrap_or("unknown"),
        settlement_payload
            .get("court_status")
            .and_then(Value::as_str)
            .unwrap_or("unknown"),
        settlement_payload
            .get("authority_status")
            .and_then(Value::as_str)
            .unwrap_or("unknown"),
        settlement_payload
            .get("treasury_status")
            .and_then(Value::as_str)
            .unwrap_or("unknown"),
        settlement_payload
            .get("settlement_status")
            .and_then(Value::as_str)
            .unwrap_or("unknown"),
        settlement_payload
            .get("reservation_id")
            .and_then(Value::as_str)
            .unwrap_or("(none)"),
        settlement_payload
            .get("witness_digest_hex")
            .and_then(Value::as_str)
            .unwrap_or("(missing)"),
        zk_latest_path.display(),
        settlement_latest_path.display(),
        root.display(),
        root.display(),
    )
}

#[derive(Clone, Debug)]
struct CourtStatus {
    status: String,
    reason: String,
    restrictions: Vec<String>,
}

#[derive(Clone, Debug)]
struct AuthorityStatus {
    status: String,
    reason: String,
}

#[derive(Clone, Debug)]
struct SettlementAgentRefs {
    canonical_agent_id: String,
    authority_agent_ref: String,
    treasury_agent_ref: String,
    economy_key: Option<String>,
    resolution_source: String,
}

fn resolve_settlement_agent_refs(
    root: &Path,
    kernel_path: &str,
    requested_agent_ref: &str,
    org_id: &str,
) -> LoomResult<SettlementAgentRefs> {
    let requested = requested_agent_ref.trim();
    if requested.is_empty() {
        return Err("execution artifact missing agent_id".to_string());
    }
    let mut candidates = vec![requested.to_string()];
    if let Some(stripped) = requested.strip_prefix("agent_") {
        if !stripped.is_empty() {
            candidates.push(stripped.to_string());
        }
    } else {
        candidates.push(format!("agent_{}", requested));
    }
    match requested {
        "main" => candidates.push("agent_leviathann".to_string()),
        "leviathann" | "agent_leviathann" => {
            candidates.push("main".to_string());
            candidates.push("agent_leviathann".to_string());
        }
        _ => {}
    }
    candidates.dedup();

    for candidate in &candidates {
        if let Ok(identity) =
            resolve_agent_identity(root, Some(kernel_path), candidate, Some(org_id))
        {
            let canonical_agent_id = identity.agent_id.trim().to_string();
            if canonical_agent_id.is_empty() {
                continue;
            }
            let economy_key = identity.economy_key.trim().to_string();
            let authority_agent_ref = if economy_key.is_empty() {
                canonical_agent_id.clone()
            } else {
                economy_key.clone()
            };
            return Ok(SettlementAgentRefs {
                canonical_agent_id: canonical_agent_id.clone(),
                authority_agent_ref,
                treasury_agent_ref: canonical_agent_id,
                economy_key: if economy_key.is_empty() {
                    None
                } else {
                    Some(economy_key)
                },
                resolution_source: "kernel_agent_registry".to_string(),
            });
        }
    }

    let canonical_agent_id = if requested.starts_with("agent_") {
        requested.to_string()
    } else {
        format!("agent_{}", requested)
    };
    let authority_agent_ref = canonical_economy_key_for_agent(requested)
        .map(str::to_string)
        .unwrap_or_else(|| canonical_agent_id.clone());

    Ok(SettlementAgentRefs {
        canonical_agent_id: canonical_agent_id.clone(),
        authority_agent_ref: authority_agent_ref.clone(),
        treasury_agent_ref: canonical_agent_id,
        economy_key: canonical_economy_key_for_agent(requested).map(str::to_string),
        resolution_source: "fallback_alias_map".to_string(),
    })
}

fn canonical_economy_key_for_agent(agent_ref: &str) -> Option<&'static str> {
    let trimmed = agent_ref.trim();
    let normalized = trimmed.strip_prefix("agent_").unwrap_or(trimmed);
    match normalized {
        "main" | "manager" | "leviathann" => Some("main"),
        "atlas" => Some("atlas"),
        "sentinel" => Some("sentinel"),
        "forge" => Some("forge"),
        "quill" => Some("quill"),
        "aegis" => Some("aegis"),
        "pulse" => Some("pulse"),
        _ => None,
    }
}

fn query_court_status(kernel_path: &Path, agent_id: &str, org_id: &str) -> LoomResult<CourtStatus> {
    let payload = run_kernel_python_json(
        kernel_path,
        r#"
import json
import sys
import court

agent_id = sys.argv[1]
org_id = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
restrictions = court.get_restrictions(agent_id, org_id)
blocked = "settle" in restrictions
print(json.dumps({
    "status": "blocked" if blocked else "clear",
    "reason": "court restriction: settle" if blocked else "clear",
    "restrictions": restrictions,
}))
"#,
        &[agent_id, org_id],
    )?;
    Ok(CourtStatus {
        status: payload
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("unknown")
            .to_string(),
        reason: payload
            .get("reason")
            .and_then(Value::as_str)
            .unwrap_or("unknown")
            .to_string(),
        restrictions: payload
            .get("restrictions")
            .and_then(Value::as_array)
            .map(|values| {
                values
                    .iter()
                    .filter_map(Value::as_str)
                    .map(str::to_string)
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default(),
    })
}

fn query_authority_status(
    kernel_path: &Path,
    agent_id: &str,
    org_id: &str,
) -> LoomResult<AuthorityStatus> {
    let payload = run_kernel_python_json(
        kernel_path,
        r#"
import json
import sys
import authority

agent_id = sys.argv[1]
org_id = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
allowed, reason = authority.check_authority(agent_id, "settle", org_id)
print(json.dumps({
    "status": "allowed" if allowed else "denied",
    "reason": reason,
}))
"#,
        &[agent_id, org_id],
    )?;
    Ok(AuthorityStatus {
        status: payload
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("unknown")
            .to_string(),
        reason: payload
            .get("reason")
            .and_then(Value::as_str)
            .unwrap_or("unknown")
            .to_string(),
    })
}

fn reserve_treasury_budget(
    kernel_path: &Path,
    agent_id: &str,
    org_id: &str,
    action_type: &str,
    resource: &str,
    actual_cost_usd: f64,
) -> LoomResult<Value> {
    run_kernel_python_json(
        kernel_path,
        r#"
import json
import sys
import treasury

agent_id = sys.argv[1]
estimated_cost = float(sys.argv[2])
org_id = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None
action_type = sys.argv[4]
resource = sys.argv[5]
result = treasury.reserve_runtime_budget(
    agent_id,
    estimated_cost,
    org_id=org_id,
    action=action_type,
    resource=resource,
    context={"settlement_mode": "zk"},
    policy_ref="loom.job.settle.zk",
)
print(json.dumps(result))
"#,
        &[
            agent_id,
            &format!("{:.6}", actual_cost_usd),
            org_id,
            action_type,
            resource,
        ],
    )
}

fn commit_treasury_budget(
    kernel_path: &Path,
    reservation_id: &str,
    actual_cost_usd: f64,
    note: &str,
) -> LoomResult<Value> {
    run_kernel_python_json(
        kernel_path,
        r#"
import json
import sys
import treasury

reservation_id = sys.argv[1]
actual_cost_usd = float(sys.argv[2])
note = sys.argv[3]
print(json.dumps(treasury.commit_runtime_budget(reservation_id, actual_cost_usd, note=note)))
"#,
        &[reservation_id, &format!("{:.6}", actual_cost_usd), note],
    )
}

fn run_kernel_python_json(kernel_path: &Path, script: &str, args: &[&str]) -> LoomResult<Value> {
    let kernel_module_dir = kernel_path.join("kernel");
    let output = Command::new("python3")
        .arg("-c")
        .arg(script)
        .args(args)
        .current_dir(&kernel_module_dir)
        .output()
        .map_err(|error| {
            format!(
                "failed to execute python helper in {}: {}",
                kernel_module_dir.display(),
                error
            )
        })?;
    if !output.status.success() {
        return Err(format!(
            "python helper failed in {}\nstdout:\n{}\nstderr:\n{}",
            kernel_module_dir.display(),
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr),
        ));
    }
    serde_json::from_slice(&output.stdout).map_err(|error| {
        format!(
            "python helper returned invalid json in {}\nstdout:\n{}\nerror: {}",
            kernel_module_dir.display(),
            String::from_utf8_lossy(&output.stdout),
            error
        )
    })
}

fn audit_root_from_execution(execution: &Value) -> LoomResult<PoGEAuditRoot> {
    Ok(PoGEAuditRoot {
        merkle_root: decode_hex_fixed::<32>(
            &required_json_string(execution, "poge_merkle_root_hex")?,
            "poge_merkle_root_hex",
        )?,
        warrant_id: decode_hex_fixed::<32>(
            &required_json_string(execution, "warrant_id_hex")?,
            "warrant_id_hex",
        )?,
        trace_len: execution
            .get("poge_trace_len")
            .and_then(Value::as_u64)
            .ok_or_else(|| "execution artifact missing poge_trace_len".to_string())?
            as u32,
        epoch_start_ms: execution
            .get("poge_epoch_start_ms")
            .and_then(Value::as_u64)
            .unwrap_or_default(),
        epoch_end_ms: execution
            .get("poge_epoch_end_ms")
            .and_then(Value::as_u64)
            .unwrap_or_default(),
        module_digest: decode_hex_fixed::<32>(
            execution
                .get("poge_module_digest_hex")
                .and_then(Value::as_str)
                .unwrap_or("0x0000000000000000000000000000000000000000000000000000000000000000"),
            "poge_module_digest_hex",
        )?,
        session_label: execution
            .get("poge_session_label")
            .and_then(Value::as_str)
            .unwrap_or("shadow:unknown")
            .to_string(),
    })
}

fn read_json_file(path: &Path) -> LoomResult<Value> {
    let raw = fs::read_to_string(path)
        .map_err(|error| format!("failed to read {}: {}", path.display(), error))?;
    serde_json::from_str(&raw)
        .map_err(|error| format!("invalid json in {}: {}", path.display(), error))
}

fn write_pretty_json(path: &Path, value: &Value) -> LoomResult<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    fs::write(
        path,
        serde_json::to_string_pretty(value).map_err(|error| error.to_string())?,
    )
    .map_err(|error| format!("failed to write {}: {}", path.display(), error))
}

fn append_jsonl(path: &Path, value: &Value) -> LoomResult<()> {
    use std::io::Write;

    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let mut file = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|error| format!("failed to open {}: {}", path.display(), error))?;
    writeln!(
        file,
        "{}",
        serde_json::to_string(value).map_err(|error| error.to_string())?
    )
    .map_err(|error| format!("failed to append {}: {}", path.display(), error))
}

fn required_json_string(value: &Value, key: &str) -> LoomResult<String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(str::to_string)
        .ok_or_else(|| format!("execution artifact missing {}", key))
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

fn extract_treasury_reservation_id(payload: &Value) -> Option<String> {
    payload
        .get("reservation_id")
        .and_then(Value::as_str)
        .map(str::to_string)
        .or_else(|| {
            payload
                .get("reservation")
                .and_then(|reservation| reservation.get("reservation_id"))
                .and_then(Value::as_str)
                .map(str::to_string)
        })
}
