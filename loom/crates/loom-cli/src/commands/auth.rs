use std::collections::BTreeMap;
use std::io::IsTerminal;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::*;
use loom_core::provider_auth_store;
use serde_json::{json, Map, Value};

const AUTH_CONTRACT_VERSION: &str = "auth_contract_v1";
const AUTH_ALIASES_SCHEMA: &str = "meridian.auth.aliases.v1";
const AUTH_AUDIT_EVENT_SCHEMA: &str = "meridian.auth.audit_event.v1";
const AUTH_ALIASES_PATH: &str = "state/auth/token_aliases.json";
const AUTH_AUDIT_PATH: &str = "state/auth/audit.jsonl";
const AUTH_CONTRACT_PATH: &str = "state/auth/auth_contract_v1.json";
const AUTH_LATEST_ARTIFACT_PATH: &str = "artifacts/auth/latest.json";

pub(crate) fn handle_auth(args: &[String]) -> LoomResult<()> {
    if args.is_empty()
        || matches!(
            args.first().map(String::as_str),
            Some("help" | "--help" | "-h")
        )
    {
        print_auth_help();
        return Ok(());
    }
    match args.first().map(String::as_str) {
        Some("status") => handle_auth_status(&args[1..]),
        Some("rotate") => handle_auth_rotate(&args[1..]),
        Some("revoke") => handle_auth_revoke(&args[1..]),
        Some("audit") => handle_auth_audit(&args[1..]),
        _ => Err("auth supports 'status', 'rotate', 'revoke', and 'audit'".to_string()),
    }
}

fn print_auth_help() {
    println!(
        "Meridian Loom // AUTH

Governed token alias lifecycle with audit receipts.

USAGE: loom auth <COMMAND> [OPTIONS]

COMMANDS:
  status [--root ROOT] [--format human|json]
  rotate --alias NAME --env-var NAME [--agent-id ID] [--org-id ORG] [--kernel-path PATH] [--root ROOT] [--format human|json]
  revoke --alias NAME [--agent-id ID] [--org-id ORG] [--kernel-path PATH] [--root ROOT] [--format human|json]
  audit [--root ROOT] [--limit N] [--format human|json]"
    );
}

fn handle_auth_status(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);

    let _ = provider_auth_store::sync_provider_auth_store(&root)?;
    let profiles = provider_auth_store::list_provider_auth_profiles(&root)?;
    let mut aliases = load_aliases(&root)?;
    let migrated = migrate_aliases_from_profiles(&mut aliases, &profiles);
    persist_aliases(&root, &aliases)?;

    let alias_records = alias_summaries(&aliases);
    let active_aliases = alias_records
        .iter()
        .filter(|entry| entry.get("status").and_then(Value::as_str) == Some("active"))
        .count();
    let revoked_aliases = alias_records
        .iter()
        .filter(|entry| entry.get("status").and_then(Value::as_str) == Some("revoked"))
        .count();

    let payload = json!({
        "status": "auth_status",
        "contract_version": AUTH_CONTRACT_VERSION,
        "generated_at": chrono_like_timestamp(),
        "profile_count": profiles.len(),
        "ready_profile_count": profiles.iter().filter(|profile| profile.ready).count(),
        "alias_count": alias_records.len(),
        "active_alias_count": active_aliases,
        "revoked_alias_count": revoked_aliases,
        "migration_inserted": migrated,
        "profiles": profiles.iter().map(profile_summary).collect::<Vec<_>>(),
        "aliases": alias_records,
        "paths": {
            "aliases": auth_aliases_path(&root).display().to_string(),
            "audit": auth_audit_path(&root).display().to_string(),
            "contract": auth_contract_path(&root).display().to_string(),
            "latest_artifact": auth_latest_artifact_path(&root).display().to_string(),
        },
        "note": "auth_contract_v1 uses alias references only; secret values are never persisted",
    });
    persist_auth_contract(&root, &payload)?;
    write_latest_auth_artifact(&root, &payload)?;
    append_auth_audit_event(
        &root,
        &json!({
            "action_type": "auth.status",
            "result": "ok",
            "migration_inserted": migrated,
            "alias_count": alias_records.len(),
        }),
    )?;
    print_auth_payload(&payload, &format)
}

fn handle_auth_rotate(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let alias = required_flag(args, "--alias")?;
    let env_var = required_flag(args, "--env-var")?;
    if alias.trim().is_empty() || env_var.trim().is_empty() {
        return Err("auth rotate requires non-empty --alias and --env-var".to_string());
    }

    let governance = capture_auth_governance(
        &root,
        args,
        "auth.rotate",
        &format!("token_alias:{}", sanitize_token(&alias)),
    )?;
    if !governance
        .get("allowed")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        let reason = governance
            .get("reason")
            .and_then(Value::as_str)
            .unwrap_or("governance denied auth.rotate");
        append_auth_audit_event(
            &root,
            &json!({
                "action_type": "auth.rotate",
                "alias": alias,
                "result": "denied",
                "reason": reason,
                "governance": governance,
            }),
        )?;
        return Err(reason.to_string());
    }

    let now_ms = now_unix_ms();
    let alias_key = sanitize_token(&alias);
    let mut aliases = load_aliases(&root)?;
    let mut record = aliases
        .remove(&alias_key)
        .unwrap_or_else(|| default_alias_record(&alias_key, now_ms));
    record["alias"] = Value::String(alias_key.clone());
    record["env_var"] = Value::String(env_var);
    record["credential_path"] = Value::Null;
    record["status"] = Value::String("active".to_string());
    record["updated_at_ms"] = json!(now_ms);
    record["last_rotated_at_ms"] = json!(now_ms);
    record["revoked_at_ms"] = Value::Null;
    record["source"] = Value::String("manual_rotate".to_string());
    aliases.insert(alias_key.clone(), record.clone());
    persist_aliases(&root, &aliases)?;

    let payload = json!({
        "status": "auth_rotated",
        "contract_version": AUTH_CONTRACT_VERSION,
        "alias": alias_record_summary(&record),
        "governance": governance,
        "paths": {
            "aliases": auth_aliases_path(&root).display().to_string(),
            "audit": auth_audit_path(&root).display().to_string(),
            "latest_artifact": auth_latest_artifact_path(&root).display().to_string(),
        },
    });
    write_latest_auth_artifact(&root, &payload)?;
    append_auth_audit_event(
        &root,
        &json!({
            "action_type": "auth.rotate",
            "alias": alias_key,
            "result": "ok",
            "governance": payload.get("governance").cloned().unwrap_or(Value::Null),
        }),
    )?;
    print_auth_payload(&payload, &format)
}

fn handle_auth_revoke(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let alias = required_flag(args, "--alias")?;
    if alias.trim().is_empty() {
        return Err("auth revoke requires non-empty --alias".to_string());
    }
    let governance = capture_auth_governance(
        &root,
        args,
        "auth.revoke",
        &format!("token_alias:{}", sanitize_token(&alias)),
    )?;
    if !governance
        .get("allowed")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        let reason = governance
            .get("reason")
            .and_then(Value::as_str)
            .unwrap_or("governance denied auth.revoke");
        append_auth_audit_event(
            &root,
            &json!({
                "action_type": "auth.revoke",
                "alias": alias,
                "result": "denied",
                "reason": reason,
                "governance": governance,
            }),
        )?;
        return Err(reason.to_string());
    }

    let now_ms = now_unix_ms();
    let alias_key = sanitize_token(&alias);
    let mut aliases = load_aliases(&root)?;
    let mut record = aliases
        .remove(&alias_key)
        .ok_or_else(|| format!("token alias '{}' was not found", alias_key))?;
    record["alias"] = Value::String(alias_key.clone());
    record["status"] = Value::String("revoked".to_string());
    record["updated_at_ms"] = json!(now_ms);
    record["revoked_at_ms"] = json!(now_ms);
    record["source"] = Value::String("manual_revoke".to_string());
    aliases.insert(alias_key.clone(), record.clone());
    persist_aliases(&root, &aliases)?;

    let payload = json!({
        "status": "auth_revoked",
        "contract_version": AUTH_CONTRACT_VERSION,
        "alias": alias_record_summary(&record),
        "governance": governance,
        "paths": {
            "aliases": auth_aliases_path(&root).display().to_string(),
            "audit": auth_audit_path(&root).display().to_string(),
            "latest_artifact": auth_latest_artifact_path(&root).display().to_string(),
        },
    });
    write_latest_auth_artifact(&root, &payload)?;
    append_auth_audit_event(
        &root,
        &json!({
            "action_type": "auth.revoke",
            "alias": alias_key,
            "result": "ok",
            "governance": payload.get("governance").cloned().unwrap_or(Value::Null),
        }),
    )?;
    print_auth_payload(&payload, &format)
}

fn handle_auth_audit(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let limit = take_value(args, "--limit")
        .and_then(|raw| raw.parse::<usize>().ok())
        .unwrap_or(20);
    let events = read_audit_events(&root, limit)?;
    let payload = json!({
        "status": "auth_audit",
        "contract_version": AUTH_CONTRACT_VERSION,
        "event_count": events.len(),
        "events": events,
        "paths": {
            "audit": auth_audit_path(&root).display().to_string(),
            "aliases": auth_aliases_path(&root).display().to_string(),
        },
    });
    print_auth_payload(&payload, &format)
}

fn capture_auth_governance(
    root: &Path,
    args: &[String],
    action_type: &str,
    resource: &str,
) -> LoomResult<Value> {
    let config = read_config(root)?;
    let kernel_path = take_value(args, "--kernel-path")
        .or_else(|| trim_to_option(&config.kernel_path))
        .ok_or_else(|| {
            "auth governance checks require --kernel-path or configured kernel_path".to_string()
        })?;
    let org_id = take_value(args, "--org-id").unwrap_or_else(|| config.org_id.clone());
    let agent_id = take_value(args, "--agent-id").unwrap_or_else(|| "agent_main".to_string());
    let identity = resolve_agent_identity(root, Some(&kernel_path), &agent_id, Some(&org_id))?;
    let envelope = build_action_envelope_with_options(
        root,
        Some(&kernel_path),
        &agent_id,
        Some(&org_id),
        action_type,
        resource,
        0.01,
        None,
        None,
        None,
        None,
    )?;
    let reference = evaluate_reference_gates(root, Some(&kernel_path), &identity, &envelope)?;
    let decision = capture_decision(root, &identity, &envelope, &reference)?;
    let effective_kernel_path = kernel_path_for(root, Some(&kernel_path))?;
    let execution = capture_runtime_execution(
        root,
        &effective_kernel_path,
        &envelope,
        &reference,
        &decision,
    )?;
    Ok(json!({
        "allowed": reference.allowed,
        "stage": reference.stage,
        "reason": reference.reason,
        "sanction_gate_decision": reference.sanction_gate_decision,
        "approval_gate_decision": reference.approval_gate_decision,
        "budget_gate_decision": reference.budget_gate_decision,
        "decision_path": decision.decision_path.display().to_string(),
        "execution_path": execution.execution_path.display().to_string(),
        "runtime_outcome": execution.runtime_outcome,
        "budget_reservation_status": execution.budget_reservation_status,
        "budget_reservation_reason": execution.budget_reservation_reason,
    }))
}

fn print_auth_payload(payload: &Value, format: &str) -> LoomResult<()> {
    match format {
        "human" => {
            print_startup_banner();
            let mut lines = vec![format!(
                "status:              {}",
                payload
                    .get("status")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown")
            )];
            if let Some(version) = payload.get("contract_version").and_then(Value::as_str) {
                lines.push(format!("contract_version:    {}", version));
            }
            if let Some(alias) = payload
                .pointer("/alias/alias")
                .and_then(Value::as_str)
                .or_else(|| payload.get("alias").and_then(Value::as_str))
            {
                lines.push(format!("alias:               {}", alias));
            }
            if let Some(governance_allowed) = payload
                .pointer("/governance/allowed")
                .and_then(Value::as_bool)
            {
                lines.push(format!("governance_allowed:  {}", governance_allowed));
            }
            if let Some(alias_count) = payload.get("alias_count").and_then(Value::as_u64) {
                lines.push(format!("alias_count:         {}", alias_count));
            }
            if let Some(event_count) = payload.get("event_count").and_then(Value::as_u64) {
                lines.push(format!("event_count:         {}", event_count));
            }
            lines.push(String::new());
            print_human(&(lines.join("\n") + "\n"));
            Ok(())
        }
        _ => {
            print!(
                "{}",
                serde_json::to_string_pretty(payload).map_err(|error| error.to_string())?
            );
            println!();
            Ok(())
        }
    }
}

fn output_format(args: &[String]) -> String {
    take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    })
}

fn profile_summary(profile: &provider_auth_store::ProviderAuthProfileSnapshot) -> Value {
    json!({
        "profile_name": profile.profile_name,
        "provider_kind": profile.provider_kind,
        "auth_mode": profile.auth_mode,
        "ready": profile.ready,
        "env_var": profile.env_var,
        "credential_path": profile.credential_path,
        "error_count": profile.error_count,
        "cooldown_reason": profile.cooldown_reason,
    })
}

fn load_aliases(root: &Path) -> LoomResult<BTreeMap<String, Value>> {
    let path = auth_aliases_path(root);
    if !path.exists() {
        return Ok(BTreeMap::new());
    }
    let raw = std::fs::read_to_string(path).map_err(|error| error.to_string())?;
    let value: Value = serde_json::from_str(&raw)
        .map_err(|error| format!("invalid auth aliases json: {error}"))?;
    let mut out = BTreeMap::new();
    if let Some(aliases) = value.get("aliases").and_then(Value::as_object) {
        for (alias, record) in aliases {
            out.insert(alias.to_string(), record.clone());
        }
    }
    Ok(out)
}

fn persist_aliases(root: &Path, aliases: &BTreeMap<String, Value>) -> LoomResult<()> {
    let path = auth_aliases_path(root);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let alias_map = aliases
        .iter()
        .map(|(alias, record)| (alias.clone(), record.clone()))
        .collect::<Map<String, Value>>();
    let payload = json!({
        "schema_version": AUTH_ALIASES_SCHEMA,
        "version": 1,
        "updated_at": chrono_like_timestamp(),
        "aliases": alias_map,
    });
    std::fs::write(
        &path,
        serde_json::to_string_pretty(&payload).map_err(|error| error.to_string())? + "\n",
    )
    .map_err(|error| error.to_string())?;
    set_private_permissions_if_supported(&path, 0o600)?;
    Ok(())
}

fn migrate_aliases_from_profiles(
    aliases: &mut BTreeMap<String, Value>,
    profiles: &[provider_auth_store::ProviderAuthProfileSnapshot],
) -> usize {
    let now_ms = now_unix_ms();
    let mut inserted = 0usize;
    for profile in profiles {
        let alias = format!("profile.{}", sanitize_token(&profile.profile_name));
        if aliases.contains_key(&alias) {
            continue;
        }
        let mut record = default_alias_record(&alias, now_ms);
        record["env_var"] = profile
            .env_var
            .as_ref()
            .map(|value| Value::String(value.clone()))
            .unwrap_or(Value::Null);
        record["credential_path"] = profile
            .credential_path
            .as_ref()
            .map(|value| Value::String(value.clone()))
            .unwrap_or(Value::Null);
        record["status"] = Value::String(if profile.ready {
            "active".to_string()
        } else {
            "attention".to_string()
        });
        record["source"] = Value::String("provider_auth_store_sync".to_string());
        aliases.insert(alias, record);
        inserted += 1;
    }
    inserted
}

fn default_alias_record(alias: &str, now_ms: u64) -> Value {
    json!({
        "alias": alias,
        "env_var": Value::Null,
        "credential_path": Value::Null,
        "status": "active",
        "source": "manual",
        "created_at_ms": now_ms,
        "updated_at_ms": now_ms,
        "last_rotated_at_ms": Value::Null,
        "revoked_at_ms": Value::Null,
    })
}

fn alias_summaries(aliases: &BTreeMap<String, Value>) -> Vec<Value> {
    let mut out = aliases
        .values()
        .map(alias_record_summary)
        .collect::<Vec<_>>();
    out.sort_by(|left, right| {
        left.get("alias")
            .and_then(Value::as_str)
            .unwrap_or("")
            .cmp(right.get("alias").and_then(Value::as_str).unwrap_or(""))
    });
    out
}

fn alias_record_summary(record: &Value) -> Value {
    json!({
        "alias": value_string(record.get("alias")),
        "env_var": optional_value_string(record.get("env_var")),
        "credential_path": optional_value_string(record.get("credential_path")),
        "status": value_string(record.get("status")),
        "source": value_string(record.get("source")),
        "updated_at_ms": record.get("updated_at_ms").and_then(Value::as_u64),
        "last_rotated_at_ms": record.get("last_rotated_at_ms").and_then(Value::as_u64),
        "revoked_at_ms": record.get("revoked_at_ms").and_then(Value::as_u64),
    })
}

fn persist_auth_contract(root: &Path, payload: &Value) -> LoomResult<()> {
    let path = auth_contract_path(root);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    std::fs::write(
        &path,
        serde_json::to_string_pretty(payload).map_err(|error| error.to_string())? + "\n",
    )
    .map_err(|error| error.to_string())
}

fn write_latest_auth_artifact(root: &Path, payload: &Value) -> LoomResult<()> {
    let path = auth_latest_artifact_path(root);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    std::fs::write(
        &path,
        serde_json::to_string_pretty(payload).map_err(|error| error.to_string())? + "\n",
    )
    .map_err(|error| error.to_string())
}

fn append_auth_audit_event(root: &Path, event: &Value) -> LoomResult<()> {
    let path = auth_audit_path(root);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let payload = json!({
        "schema_version": AUTH_AUDIT_EVENT_SCHEMA,
        "timestamp": chrono_like_timestamp(),
        "event": event,
    });
    let mut line = serde_json::to_string(&payload).map_err(|error| error.to_string())?;
    line.push('\n');
    std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .and_then(|mut file| {
            use std::io::Write;
            file.write_all(line.as_bytes())
        })
        .map_err(|error| error.to_string())?;
    Ok(())
}

fn read_audit_events(root: &Path, limit: usize) -> LoomResult<Vec<Value>> {
    let path = auth_audit_path(root);
    if !path.exists() {
        return Ok(Vec::new());
    }
    let raw = std::fs::read_to_string(path).map_err(|error| error.to_string())?;
    let mut events = raw
        .lines()
        .filter_map(|line| serde_json::from_str::<Value>(line).ok())
        .map(|value| {
            let mut merged = value
                .get("event")
                .cloned()
                .unwrap_or_else(|| json!({"raw": value}));
            if merged.get("timestamp").is_none() {
                if let Some(ts) = value.get("timestamp") {
                    merged["timestamp"] = ts.clone();
                }
            }
            merged
        })
        .collect::<Vec<_>>();
    if limit > 0 && events.len() > limit {
        events = events.split_off(events.len() - limit);
    }
    Ok(events)
}

fn auth_aliases_path(root: &Path) -> PathBuf {
    root.join(AUTH_ALIASES_PATH)
}

fn auth_audit_path(root: &Path) -> PathBuf {
    root.join(AUTH_AUDIT_PATH)
}

fn auth_contract_path(root: &Path) -> PathBuf {
    root.join(AUTH_CONTRACT_PATH)
}

fn auth_latest_artifact_path(root: &Path) -> PathBuf {
    root.join(AUTH_LATEST_ARTIFACT_PATH)
}

fn trim_to_option(value: &str) -> Option<String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

fn value_string(value: Option<&Value>) -> String {
    value
        .and_then(Value::as_str)
        .map(|raw| raw.trim().to_string())
        .filter(|raw| !raw.is_empty())
        .unwrap_or_default()
}

fn optional_value_string(value: Option<&Value>) -> Option<String> {
    value
        .and_then(Value::as_str)
        .map(|raw| raw.trim().to_string())
        .filter(|raw| !raw.is_empty())
}

fn now_unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}
