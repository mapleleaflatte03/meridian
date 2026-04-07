use crate::*;
use serde_json::{json, Value};
use std::io::IsTerminal;
use std::path::{Path, PathBuf};

const DEPLOY_STATE_SCHEMA: &str = "meridian.deploy.host.state.v1";
const DEPLOY_RECEIPT_SCHEMA: &str = "meridian.deploy.host.receipt.v1";

pub(crate) fn handle_deploy(args: &[String]) -> LoomResult<()> {
    if args.is_empty()
        || matches!(
            args.first().map(String::as_str),
            Some("help" | "--help" | "-h")
        )
    {
        print_deploy_help();
        return Ok(());
    }
    match args.first().map(String::as_str) {
        Some("host") => handle_deploy_host(&args[1..]),
        Some("verify") => handle_deploy_verify(&args[1..]),
        Some("rollback") => handle_deploy_rollback(&args[1..]),
        _ => Err("deploy supports 'host', 'verify', and 'rollback'".to_string()),
    }
}

fn print_deploy_help() {
    println!(
        "Meridian Loom // DEPLOY

Operator-grade deploy lane for host apply, verify, and rollback.

USAGE: loom deploy <COMMAND> [OPTIONS]

COMMANDS:
  host     --root ROOT [--target-version VERSION] [--format human|json]
  verify   --root ROOT [--format human|json]
  rollback --root ROOT [--to-version VERSION] [--format human|json]"
    );
}

fn handle_deploy_host(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_deploy_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let _ = read_config(&root)?;
    let format = output_format(args);
    let target_version = take_value(args, "--target-version")
        .unwrap_or_else(chrono_like_timestamp)
        .trim()
        .to_string();
    if target_version.is_empty() {
        return Err("deploy host requires a non-empty target version".to_string());
    }

    let now = chrono_like_timestamp();
    let mut state = load_deploy_state(&root)?;
    let current_version = state_current_version(&state);
    let idempotent = !current_version.is_empty() && current_version == target_version;
    let deploy_id = format!("dep_{}_{}", now, sanitize_token(target_version.as_str()));
    let status = if idempotent {
        "deploy_host_idempotent"
    } else {
        "deploy_host_applied"
    };

    if !idempotent {
        state["current"] = json!({
            "version": target_version,
            "deployed_at": now,
            "deploy_id": deploy_id,
            "status": "deployed",
        });
    }
    push_history_entry(
        &mut state,
        json!({
            "entry_id": deploy_id,
            "operation": "host",
            "recorded_at": now,
            "from_version": current_version,
            "to_version": target_version,
            "idempotent": idempotent,
            "status": status,
        }),
    )?;
    state["updated_at"] = Value::String(now.clone());
    persist_deploy_state(&root, &state)?;

    let receipt_payload = json!({
        "schema_version": DEPLOY_RECEIPT_SCHEMA,
        "receipt_id": deploy_id,
        "recorded_at": now,
        "operation": "host",
        "status": status,
        "idempotent": idempotent,
        "from_version": current_version,
        "to_version": target_version,
        "rollback_suggestion": if idempotent { "" } else { "loom deploy rollback --root <root> --to-version <previous-version> --format json" },
    });
    let receipt_path = write_deploy_receipt(&root, deploy_id.as_str(), &receipt_payload)?;
    write_deploy_latest_artifact(&root, &receipt_payload)?;

    let payload = json!({
        "status": status,
        "idempotent": idempotent,
        "root": root.display().to_string(),
        "target_version": target_version,
        "current_version": state_current_version(&state),
        "previous_version": current_version,
        "deploy_id": deploy_id,
        "state_path": deploy_state_path(&root).display().to_string(),
        "receipt_path": receipt_path.display().to_string(),
        "verify_hint": format!("loom deploy verify --root \"{}\" --format json", root.display()),
        "rollback_hint": format!("loom deploy rollback --root \"{}\" --to-version \"{}\" --format json", root.display(), current_version),
    });
    print_deploy_payload(&payload, &format)
}

fn handle_deploy_verify(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_deploy_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let state_path = deploy_state_path(&root);
    let state = load_deploy_state(&root)?;
    let current_version = state_current_version(&state);
    let checks = json!({
        "runtime_config_present": root.join("loom.toml").exists(),
        "deploy_state_present": state_path.exists(),
        "current_version_present": !current_version.is_empty(),
        "rollback_ready": state_history_len(&state) > 0,
    });
    let ok = checks
        .as_object()
        .map(|item| item.values().all(|value| value.as_bool().unwrap_or(false)))
        .unwrap_or(false);
    let payload = json!({
        "status": if ok { "deploy_verify_ok" } else { "deploy_verify_failed" },
        "root": root.display().to_string(),
        "current_version": current_version,
        "state_path": state_path.display().to_string(),
        "checks": checks,
    });
    print_deploy_payload(&payload, &format)
}

fn handle_deploy_rollback(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_deploy_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let _ = read_config(&root)?;
    let format = output_format(args);
    let now = chrono_like_timestamp();
    let mut state = load_deploy_state(&root)?;
    let current_version = state_current_version(&state);
    if current_version.is_empty() {
        return Err("deploy rollback requires an existing host deployment record".to_string());
    }
    let requested_target = take_value(args, "--to-version").unwrap_or_default();
    let target_version = if requested_target.trim().is_empty() {
        resolve_previous_version(&state, current_version.as_str())
            .ok_or_else(|| "deploy rollback could not resolve a previous version".to_string())?
    } else {
        requested_target.trim().to_string()
    };
    let idempotent = target_version == current_version;
    let rollback_id = format!("rlb_{}_{}", now, sanitize_token(target_version.as_str()));
    let status = if idempotent {
        "deploy_rollback_idempotent"
    } else {
        "deploy_rollback_applied"
    };
    if !idempotent {
        state["current"] = json!({
            "version": target_version,
            "deployed_at": now,
            "deploy_id": rollback_id,
            "status": "rolled_back",
        });
    }
    push_history_entry(
        &mut state,
        json!({
            "entry_id": rollback_id,
            "operation": "rollback",
            "recorded_at": now,
            "from_version": current_version,
            "to_version": target_version,
            "idempotent": idempotent,
            "status": status,
        }),
    )?;
    state["updated_at"] = Value::String(now.clone());
    persist_deploy_state(&root, &state)?;

    let receipt_payload = json!({
        "schema_version": DEPLOY_RECEIPT_SCHEMA,
        "receipt_id": rollback_id,
        "recorded_at": now,
        "operation": "rollback",
        "status": status,
        "idempotent": idempotent,
        "from_version": current_version,
        "to_version": target_version,
    });
    let receipt_path = write_deploy_receipt(&root, rollback_id.as_str(), &receipt_payload)?;
    write_deploy_latest_artifact(&root, &receipt_payload)?;

    let payload = json!({
        "status": status,
        "idempotent": idempotent,
        "root": root.display().to_string(),
        "current_version": state_current_version(&state),
        "rollback_from_version": current_version,
        "rollback_to_version": target_version,
        "rollback_id": rollback_id,
        "state_path": deploy_state_path(&root).display().to_string(),
        "receipt_path": receipt_path.display().to_string(),
        "verify_hint": format!("loom deploy verify --root \"{}\" --format json", root.display()),
    });
    print_deploy_payload(&payload, &format)
}

fn deploy_state_path(root: &Path) -> PathBuf {
    root.join("state/deploy/host_state.json")
}

fn deploy_receipts_dir(root: &Path) -> PathBuf {
    root.join("state/deploy/receipts")
}

fn deploy_latest_artifact_path(root: &Path) -> PathBuf {
    root.join("artifacts/deploy/latest.json")
}

fn load_deploy_state(root: &Path) -> LoomResult<Value> {
    let path = deploy_state_path(root);
    if !path.exists() {
        return Ok(json!({
            "schema_version": DEPLOY_STATE_SCHEMA,
            "updated_at": "",
            "current": {},
            "history": [],
        }));
    }
    let raw = std::fs::read_to_string(&path).map_err(|error| error.to_string())?;
    let mut payload: Value = serde_json::from_str(&raw).map_err(|error| error.to_string())?;
    if !payload.is_object() {
        payload = json!({});
    }
    if payload
        .get("schema_version")
        .and_then(Value::as_str)
        .unwrap_or("")
        .is_empty()
    {
        payload["schema_version"] = Value::String(DEPLOY_STATE_SCHEMA.to_string());
    }
    if !payload
        .get("current")
        .map(Value::is_object)
        .unwrap_or(false)
    {
        payload["current"] = json!({});
    }
    if !payload.get("history").map(Value::is_array).unwrap_or(false) {
        payload["history"] = json!([]);
    }
    Ok(payload)
}

fn persist_deploy_state(root: &Path, state: &Value) -> LoomResult<()> {
    let path = deploy_state_path(root);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    std::fs::write(
        &path,
        serde_json::to_string_pretty(state).map_err(|error| error.to_string())? + "\n",
    )
    .map_err(|error| error.to_string())
}

fn push_history_entry(state: &mut Value, entry: Value) -> LoomResult<()> {
    let history = state
        .get_mut("history")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| "deploy state history must be an array".to_string())?;
    history.push(entry);
    Ok(())
}

fn state_current_version(state: &Value) -> String {
    state
        .get("current")
        .and_then(Value::as_object)
        .and_then(|current| current.get("version"))
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim()
        .to_string()
}

fn state_history_len(state: &Value) -> usize {
    state
        .get("history")
        .and_then(Value::as_array)
        .map(|items| items.len())
        .unwrap_or(0)
}

fn resolve_previous_version(state: &Value, current_version: &str) -> Option<String> {
    let history = state.get("history").and_then(Value::as_array)?;
    for entry in history.iter().rev() {
        let from_version = entry
            .get("from_version")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim();
        if !from_version.is_empty() && from_version != current_version {
            return Some(from_version.to_string());
        }
    }
    None
}

fn write_deploy_receipt(root: &Path, receipt_id: &str, payload: &Value) -> LoomResult<PathBuf> {
    let path = deploy_receipts_dir(root).join(format!("{}.json", receipt_id));
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    std::fs::write(
        &path,
        serde_json::to_string_pretty(payload).map_err(|error| error.to_string())? + "\n",
    )
    .map_err(|error| error.to_string())?;
    Ok(path)
}

fn write_deploy_latest_artifact(root: &Path, payload: &Value) -> LoomResult<()> {
    let path = deploy_latest_artifact_path(root);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    std::fs::write(
        &path,
        serde_json::to_string_pretty(payload).map_err(|error| error.to_string())? + "\n",
    )
    .map_err(|error| error.to_string())
}

fn print_deploy_payload(payload: &Value, format: &str) -> LoomResult<()> {
    match format {
        "json" => {
            println!(
                "{}",
                serde_json::to_string_pretty(payload).map_err(|error| error.to_string())?
            );
            Ok(())
        }
        _ => {
            print_startup_banner();
            print_human(&format!(
                "Meridian Loom // DEPLOY\n========================\nstatus:           {}\nroot:             {}\ncurrent_version:  {}\nidempotent:       {}\nstate_path:       {}\nreceipt_path:     {}\n",
                payload.get("status").and_then(Value::as_str).unwrap_or("unknown"),
                payload.get("root").and_then(Value::as_str).unwrap_or(""),
                payload.get("current_version").and_then(Value::as_str).unwrap_or(""),
                payload.get("idempotent").and_then(Value::as_bool).unwrap_or(false),
                payload.get("state_path").and_then(Value::as_str).unwrap_or(""),
                payload.get("receipt_path").and_then(Value::as_str).unwrap_or(""),
            ));
            Ok(())
        }
    }
}

fn output_format(args: &[String]) -> String {
    let requested = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    match requested.as_str() {
        "human" => "human".to_string(),
        "json" => "json".to_string(),
        _ => "human".to_string(),
    }
}
