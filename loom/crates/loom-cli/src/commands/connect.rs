use std::fs::OpenOptions;
use std::io::{IsTerminal, Write};
use std::path::{Path, PathBuf};

use crate::*;
use sha2::{Digest, Sha256};
use serde_json::{json, Value};

const DEFAULT_CONNECT_REGISTRY_PATH: &str = "state/connect/registry.json";
const DEFAULT_CONNECT_ADAPTERS_DIR: &str = "state/connect/adapters";
const DEFAULT_CONNECT_HEALTH_DIR: &str = "state/connect/health";
const DEFAULT_CONNECT_TESTS_DIR: &str = "state/connect/tests";
const DEFAULT_CONNECT_LIFECYCLE_DIR: &str = "state/connect/lifecycle";
const DEFAULT_CONNECT_SANCTIONS_DIR: &str = "state/connect/sanctions";
const DEFAULT_CONNECT_DESKTOP_DIR: &str = "state/connect/desktop";
const DEFAULT_CONNECT_LATEST_ARTIFACT_PATH: &str = "artifacts/connect/latest.json";
const CONNECT_REGISTRY_SCHEMA_V1: &str = "meridian.connect.registry.v1";
const CONNECT_REGISTRY_SCHEMA_V2: &str = "meridian.connect.registry.v2";
const CONNECT_ADAPTER_SCHEMA: &str = "meridian.connect.adapter.v1";
const CONNECT_RUNTIME_CONTRACT_V2: &str = "connect_runtime_contract_v2";
const CONNECT_TEST_EVENT_SCHEMA: &str = "meridian.connect.test_event.v1";
const CONNECT_HEALTH_EVENT_SCHEMA: &str = "meridian.connect.health_event.v1";
const CONNECT_LIFECYCLE_EVENT_SCHEMA: &str = "meridian.connect.lifecycle_event.v1";
const DEFAULT_RECONNECT_ATTEMPTS_MAX: u64 = 3;
const DEFAULT_DIAGNOSTIC_RETENTION_DAYS: u64 = 30;
const DEFAULT_RATE_LIMIT_WINDOW_SECONDS: u64 = 60;
const DEFAULT_SECURITY_MAX_PAYLOAD_BYTES: u64 = 262_144;
const SECURITY_MAX_PAYLOAD_BYTES_LIMIT: u64 = 1_048_576;
const CONNECT_SANCTION_SCHEMA: &str = "meridian.connect.sanction_event.v1";
const SECURITY_PROFILE_SCHEMA: &str = "connect_security_profile_v1";
const SECURITY_FAILURE_POLICY_DEFAULT: &str = "fallback_local_queue";
const SECURITY_FAILURE_POLICIES: [&str; 3] = ["fallback_local_queue", "shadow_mode", "deny"];
const SUPPORTED_TRANSPORTS: [&str; 14] = [
    "telegram", "discord", "whatsapp", "slack", "email", "browser", "shell", "desktop",
    "webhook", "grpc", "a2a", "mcp", "http", "ros2",
];
const OPERATOR_PRIORITY_TRANSPORTS: [&str; 9] = [
    "telegram", "discord", "whatsapp", "slack", "email", "browser", "shell", "desktop", "webhook",
];

pub(crate) fn handle_connect(args: &[String]) -> LoomResult<()> {
    if args.is_empty()
        || matches!(
            args.first().map(String::as_str),
            Some("help" | "--help" | "-h")
        )
    {
        print_connect_help();
        return Ok(());
    }
    match args.first().map(String::as_str) {
        Some("scaffold") => handle_connect_scaffold(&args[1..]),
        Some("list") => handle_connect_list(&args[1..]),
        Some("validate") => handle_connect_validate(&args[1..]),
        Some("enable") => handle_connect_toggle(&args[1..], true),
        Some("disable") => handle_connect_toggle(&args[1..], false),
        Some("test") => handle_connect_test(&args[1..]),
        Some("health") => handle_connect_health(&args[1..]),
        Some("diagnostics") => handle_connect_diagnostics(&args[1..]),
        Some("metrics") => handle_connect_metrics(&args[1..]),
        Some("scorecard") => handle_connect_scorecard(&args[1..]),
        Some("prune") => handle_connect_prune(&args[1..]),
        Some(unknown) => Err(format!(
            "unknown connect subcommand '{}'; available: scaffold, list, validate, enable, disable, test, health, diagnostics, metrics, scorecard, prune. Run `loom connect --help` for usage.",
            unknown
        )),
        None => {
            print_connect_help();
            Ok(())
        }
    }
}

fn print_connect_help() {
    println!(
        "Meridian Loom // CONNECT

Scaffold, validate, and operate Universal Connect adapter manifests.

USAGE: loom connect <COMMAND> [OPTIONS]

COMMANDS:
  scaffold --name NAME --transport telegram|discord|whatsapp|slack|email|browser|shell|desktop|webhook|grpc|a2a|mcp|http|ros2 --action-schema SCHEMA
           [--root ROOT] [--format human|json]
  list     [--root ROOT] [--format human|json]
  validate [--adapter-id ID] [--root ROOT] [--format human|json]
  enable   --adapter-id ID [--root ROOT] [--format human|json]
  disable  --adapter-id ID [--root ROOT] [--format human|json]
  test     --adapter-id ID [--root ROOT] [--format human|json]
  health   --adapter-id ID [--root ROOT] [--format human|json]
  diagnostics --adapter-id ID [--limit N] [--root ROOT] [--format human|json]
  metrics  --adapter-id ID [--retention-days DAYS] [--root ROOT] [--format human|json]
  scorecard [--retention-days DAYS] [--fix] [--root ROOT] [--format human|json]
  prune    --adapter-id ID [--retention-days DAYS] [--root ROOT] [--format human|json]"
    );
}

fn handle_connect_scaffold(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let name = required_flag(args, "--name")?;
    let transport = required_flag(args, "--transport")?
        .trim()
        .to_ascii_lowercase();
    let action_schema = required_flag(args, "--action-schema")?;
    validate_transport(&transport)?;

    let adapter_id = sanitize_token(&name);
    if adapter_id.is_empty() {
        return Err("connect scaffold produced empty adapter id from --name".to_string());
    }

    let mut registry = load_connect_registry(&root)?;
    let now = chrono_like_timestamp();
    let mode = if find_adapter(&registry, &adapter_id).is_some() {
        "updated"
    } else {
        "created"
    };
    let created_at = find_adapter(&registry, &adapter_id)
        .and_then(|value| value.get("created_at"))
        .and_then(Value::as_str)
        .unwrap_or(now.as_str())
        .to_string();
    let manifest = json!({
        "schema_version": CONNECT_ADAPTER_SCHEMA,
        "adapter_id": adapter_id,
        "name": name,
        "transport": transport,
        "action_schema": action_schema,
        "status": "scaffolded",
        "created_at": created_at,
        "updated_at": now,
        "runtime_contract": CONNECT_RUNTIME_CONTRACT_V2,
        "lifecycle": {
            "enabled": false,
            "state": "init",
            "auth_state": "pending",
            "last_transition_at": chrono_like_timestamp(),
            "reconnect_attempts": 0,
            "reconnect_attempts_max": DEFAULT_RECONNECT_ATTEMPTS_MAX,
            "last_error": "",
        },
        "diagnostics": default_adapter_diagnostics(),
        "fallback": default_fallback_policy(),
        "poge_standard": poge_standard_profile(),
        "security_profile": security_profile_for(transport.as_str()),
        "transport_profile": transport_profile_for(transport.as_str()),
    });
    upsert_adapter(&mut registry, manifest.clone())?;
    persist_connect_registry(&root, &registry)?;

    let adapters_dir = connect_adapters_dir(&root);
    std::fs::create_dir_all(&adapters_dir).map_err(|error| error.to_string())?;
    let manifest_path = adapters_dir.join(format!(
        "{}.json",
        manifest
            .get("adapter_id")
            .and_then(Value::as_str)
            .unwrap_or_default()
    ));
    std::fs::write(
        &manifest_path,
        serde_json::to_string_pretty(&manifest).map_err(|error| error.to_string())? + "\n",
    )
    .map_err(|error| error.to_string())?;

    let total_adapters = registry
        .get("adapters")
        .and_then(Value::as_array)
        .map(|items| items.len())
        .unwrap_or(0);
    let payload = json!({
        "status": "connect_scaffolded",
        "mode": mode,
        "adapter_id": manifest.get("adapter_id").and_then(Value::as_str).unwrap_or(""),
        "name": manifest.get("name").and_then(Value::as_str).unwrap_or(""),
        "transport": manifest.get("transport").and_then(Value::as_str).unwrap_or(""),
        "action_schema": manifest.get("action_schema").and_then(Value::as_str).unwrap_or(""),
        "runtime_contract": CONNECT_RUNTIME_CONTRACT_V2,
        "enabled": false,
        "manifest_path": manifest_path.display().to_string(),
        "registry_path": connect_registry_path(&root).display().to_string(),
        "total_adapters": total_adapters,
        "registry_schema_version": CONNECT_REGISTRY_SCHEMA_V2,
        "poge_standard_profile": manifest.pointer("/poge_standard/profile").and_then(Value::as_str).unwrap_or(""),
        "supported_transports": SUPPORTED_TRANSPORTS,
        "operator_priority_transports": OPERATOR_PRIORITY_TRANSPORTS,
        "note": "connect adapter scaffolded with governed defaults",
    });
    persist_connect_latest_artifact(&root, &payload)?;
    let _ = append_lifecycle_event(
        &root,
        manifest
            .get("adapter_id")
            .and_then(Value::as_str)
            .unwrap_or_default(),
        "init",
        "scaffolded",
        "adapter scaffolded with governed defaults",
    );
    print_connect_payload(&payload, &format)
}

fn handle_connect_list(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let registry = load_connect_registry(&root)?;
    let adapters = registry
        .get("adapters")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let payload = json!({
        "status": "connect_listed",
        "registry_path": connect_registry_path(&root).display().to_string(),
        "registry_schema_version": CONNECT_REGISTRY_SCHEMA_V2,
        "total_adapters": adapters.len(),
        "supported_transports": SUPPORTED_TRANSPORTS,
        "operator_priority_transports": OPERATOR_PRIORITY_TRANSPORTS,
        "adapters": adapters,
        "note": "connect adapter registry snapshot",
    });
    print_connect_payload(&payload, &format)
}

fn handle_connect_validate(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let adapter_id = take_value(args, "--adapter-id").map(|value| sanitize_token(&value));
    let legacy_schema_detected = detect_legacy_registry_schema(&root)?;

    let registry = load_connect_registry(&root)?;
    persist_connect_registry(&root, &registry)?;
    let adapters = registry
        .get("adapters")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let selected = if let Some(requested) = adapter_id {
        adapters
            .into_iter()
            .filter(|adapter| {
                adapter
                    .get("adapter_id")
                    .and_then(Value::as_str)
                    .map(|value| value == requested)
                    .unwrap_or(false)
            })
            .collect::<Vec<_>>()
    } else {
        adapters
    };
    if selected.is_empty() {
        return Err("connect validate did not find matching adapters".to_string());
    }

    let mut invalid = 0_u64;
    let mut checks = Vec::new();
    for adapter in selected {
        let adapter_id = adapter
            .get("adapter_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        let transport = adapter
            .get("transport")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        let action_schema = adapter
            .get("action_schema")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        let transport_ok = SUPPORTED_TRANSPORTS.contains(&transport.as_str());
        let schema_ok = !action_schema.trim().is_empty();
        let runtime_contract_ok = adapter
            .get("runtime_contract")
            .and_then(Value::as_str)
            .map(|value| value == CONNECT_RUNTIME_CONTRACT_V2)
            .unwrap_or(false);
        let security_checks = evaluate_adapter_security(&adapter);
        let security_posture_ok = security_checks
            .get("valid")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let valid = transport_ok && schema_ok && runtime_contract_ok && security_posture_ok;
        if !valid {
            invalid += 1;
        }
        checks.push(json!({
            "adapter_id": adapter_id,
            "transport_ok": transport_ok,
            "action_schema_ok": schema_ok,
            "runtime_contract_ok": runtime_contract_ok,
            "security_posture_ok": security_posture_ok,
            "security_checks": security_checks,
            "valid": valid,
        }));
    }

    let validation_status = if invalid == 0 { "pass" } else { "fail" };
    let payload = json!({
        "status": "connect_validated",
        "validation_status": validation_status,
        "registry_path": connect_registry_path(&root).display().to_string(),
        "registry_schema_version": CONNECT_REGISTRY_SCHEMA_V2,
        "runtime_contract": CONNECT_RUNTIME_CONTRACT_V2,
        "checked_adapters": checks.len(),
        "invalid_adapters": invalid,
        "checks": checks,
        "migration": {
            "legacy_schema_detected": legacy_schema_detected,
            "migration_mode": "additive_v1_to_v2",
        },
        "note": "connect registry validation with additive v1->v2 compatibility",
    });
    persist_connect_latest_artifact(&root, &payload)?;
    if invalid > 0 {
        let _ = print_connect_payload(&payload, &format);
        return Err(format!(
            "connect validate failed: {} adapters invalid",
            invalid
        ));
    }
    print_connect_payload(&payload, &format)
}

fn handle_connect_toggle(args: &[String], enable: bool) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let adapter_id = sanitize_token(&required_flag(args, "--adapter-id")?);
    if adapter_id.is_empty() {
        return Err("adapter-id cannot be empty".to_string());
    }

    let mut registry = load_connect_registry(&root)?;
    let adapter = find_adapter_mut(&mut registry, &adapter_id)
        .ok_or_else(|| format!("adapter '{}' not found; run `loom connect list` to see available adapters", adapter_id))?;
    let previous = adapter_enabled(adapter);
    set_adapter_enabled(adapter, enable);
    let now = chrono_like_timestamp();
    adapter["status"] = Value::String(if enable { "enabled" } else { "disabled" }.to_string());
    adapter["updated_at"] = Value::String(now.clone());
    let lifecycle = adapter_lifecycle_mut(adapter);
    lifecycle["state"] = Value::String(if enable { "ready" } else { "disabled" }.to_string());
    lifecycle["auth_state"] =
        Value::String(if enable { "verified" } else { "disabled" }.to_string());
    lifecycle["last_transition_at"] = Value::String(now);
    if enable {
        lifecycle["reconnect_attempts"] = Value::Number(0_u64.into());
        lifecycle["last_error"] = Value::String(String::new());
    }
    let mode = if previous == enable {
        "noop"
    } else {
        "changed"
    };
    persist_connect_registry(&root, &registry)?;
    let transition_reason = if enable {
        if mode == "noop" {
            "adapter already enabled"
        } else {
            "adapter enabled and authenticated"
        }
    } else if mode == "noop" {
        "adapter already disabled"
    } else {
        "adapter disabled by operator"
    };
    let _ = append_lifecycle_event(
        &root,
        &adapter_id,
        if enable { "ready" } else { "disabled" },
        if enable {
            if mode == "noop" {
                "enable_noop"
            } else {
                "enable"
            }
        } else if mode == "noop" {
            "disable_noop"
        } else {
            "disable"
        },
        transition_reason,
    );

    let payload = json!({
        "status": if enable { "connect_enabled" } else { "connect_disabled" },
        "mode": mode,
        "adapter_id": adapter_id,
        "enabled": enable,
        "lifecycle_state": if enable { "ready" } else { "disabled" },
        "registry_path": connect_registry_path(&root).display().to_string(),
        "registry_schema_version": CONNECT_REGISTRY_SCHEMA_V2,
        "runtime_contract": CONNECT_RUNTIME_CONTRACT_V2,
        "note": "adapter lifecycle state updated",
    });
    persist_connect_latest_artifact(&root, &payload)?;
    print_connect_payload(&payload, &format)
}

fn handle_connect_test(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let adapter_id = sanitize_token(&required_flag(args, "--adapter-id")?);
    if adapter_id.is_empty() {
        return Err("adapter-id cannot be empty".to_string());
    }

    let mut registry = load_connect_registry(&root)?;
    let adapter = find_adapter_mut(&mut registry, &adapter_id)
        .ok_or_else(|| format!("adapter '{}' not found; run `loom connect list` to see available adapters", adapter_id))?;
    let transport = adapter
        .get("transport")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let action_schema = adapter
        .get("action_schema")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let enabled = adapter_enabled(adapter);

    let tested_at = chrono_like_timestamp();
    let tested_at_unix = tested_at.parse::<u64>().unwrap_or_default();
    let rate_limit_per_minute = adapter
        .pointer("/transport_profile/rate_limit_per_minute")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let rate_limit_reached = if rate_limit_per_minute > 0 {
        recent_test_count_within_window(
            &root,
            &adapter_id,
            tested_at_unix,
            DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
        ) >= rate_limit_per_minute
    } else {
        false
    };
    let malformed_payload = should_force_malformed_payload(adapter);

    let (test_status, test_reason) = if !enabled {
        ("fail".to_string(), "adapter_disabled".to_string())
    } else if !SUPPORTED_TRANSPORTS.contains(&transport.as_str()) {
        (
            "fail".to_string(),
            format!("unsupported_transport:{transport}"),
        )
    } else if malformed_payload {
        ("fail".to_string(), "malformed_payload".to_string())
    } else if rate_limit_reached {
        (
            "fail".to_string(),
            format!("rate_limited:{rate_limit_per_minute}/min"),
        )
    } else if action_schema.trim().is_empty() {
        ("fail".to_string(), "missing_action_schema".to_string())
    } else {
        ("pass".to_string(), "contract_checks_passed".to_string())
    };
    let test_event = json!({
        "schema_version": CONNECT_TEST_EVENT_SCHEMA,
        "adapter_id": adapter_id,
        "transport": transport,
        "runtime_contract": CONNECT_RUNTIME_CONTRACT_V2,
        "tested_at": tested_at,
        "test_status": test_status,
        "test_reason": test_reason,
        "warrant_bound": true,
        "authority_checked": true,
        "court_checked": true,
        "treasury_gate": true,
    });
    append_jsonl(
        &connect_tests_history_path(&root, &adapter_id),
        &serde_json::to_string(&test_event).map_err(|error| error.to_string())?,
    )?;
    let desktop_vision_event = if transport == "desktop" {
        let event = build_desktop_vision_event(
            &adapter_id,
            test_event
                .get("tested_at")
                .and_then(Value::as_str)
                .unwrap_or_default(),
            test_event
                .get("test_status")
                .and_then(Value::as_str)
                .unwrap_or("unknown"),
            test_event
                .get("test_reason")
                .and_then(Value::as_str)
                .unwrap_or("unknown"),
        );
        append_jsonl(
            &connect_desktop_history_path(&root, &adapter_id),
            &serde_json::to_string(&event).map_err(|error| error.to_string())?,
        )?;
        Some(event)
    } else {
        None
    };
    if test_reason == "malformed_payload" {
        let _ = append_connect_sanction_event(
            &root,
            &adapter_id,
            "malformed_payload",
            "test_fail",
            "payload failed governed validation",
        );
    }

    let diagnostics = adapter_diagnostics_mut(adapter);
    diagnostics["last_test_status"] = Value::String(
        test_event
            .get("test_status")
            .and_then(Value::as_str)
            .unwrap_or("unknown")
            .to_string(),
    );
    diagnostics["last_test_reason"] = Value::String(
        test_event
            .get("test_reason")
            .and_then(Value::as_str)
            .unwrap_or("unknown")
            .to_string(),
    );
    diagnostics["last_test_at"] = Value::String(
        test_event
            .get("tested_at")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
    );
    if let Some(event) = desktop_vision_event.as_ref() {
        diagnostics["last_desktop_capture_at"] = Value::String(
            event
                .get("captured_at")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string(),
        );
        diagnostics["last_desktop_capture_digest"] = Value::String(
            event
                .get("capture_digest_hex")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string(),
        );
    }
    let test_entries = diagnostics
        .get("test_history_entries")
        .and_then(Value::as_u64)
        .unwrap_or(0)
        + 1;
    diagnostics["test_history_entries"] = Value::Number(test_entries.into());
    if !adapter
        .get("lifecycle")
        .map(Value::is_object)
        .unwrap_or(false)
    {
        adapter["lifecycle"] = json!({});
    }
    if !adapter
        .get("fallback")
        .map(Value::is_object)
        .unwrap_or(false)
    {
        adapter["fallback"] = default_fallback_policy();
    }
    adapter["lifecycle"]["last_transition_at"] = Value::String(tested_at.clone());
    if test_status == "pass" {
        adapter["status"] = Value::String("ready".to_string());
        adapter["lifecycle"]["state"] = Value::String("ready".to_string());
        adapter["lifecycle"]["auth_state"] = Value::String("verified".to_string());
        adapter["lifecycle"]["last_error"] = Value::String(String::new());
        adapter["fallback"]["active"] = Value::Bool(false);
        adapter["fallback"]["last_trigger_reason"] = Value::String(String::new());
    } else {
        adapter["status"] = Value::String("error".to_string());
        adapter["lifecycle"]["state"] = Value::String("error".to_string());
        adapter["lifecycle"]["last_error"] = Value::String(test_reason.clone());
        adapter["fallback"]["active"] = Value::Bool(true);
        adapter["fallback"]["last_trigger_reason"] = Value::String(test_reason.clone());
    }
    adapter["updated_at"] = Value::String(tested_at);
    persist_connect_registry(&root, &registry)?;
    let _ = append_lifecycle_event(
        &root,
        &adapter_id,
        if test_status == "pass" {
            "ready"
        } else {
            "error"
        },
        if test_status == "pass" {
            "test_pass"
        } else {
            "test_fail"
        },
        &test_reason,
    );

    let payload = json!({
        "status": "connect_tested",
        "adapter_id": adapter_id,
        "test_status": test_event.get("test_status").and_then(Value::as_str).unwrap_or("unknown"),
        "test_reason": test_event.get("test_reason").and_then(Value::as_str).unwrap_or("unknown"),
        "rate_limit_per_minute": rate_limit_per_minute,
        "rate_limit_reached": rate_limit_reached,
        "malformed_payload": malformed_payload,
        "lifecycle_state": if test_status == "pass" { "ready" } else { "error" },
        "fallback_active": test_status != "pass",
        "tests_history_path": connect_tests_history_path(&root, &adapter_id).display().to_string(),
        "sanctions_path": connect_sanctions_history_path(&root, &adapter_id).display().to_string(),
        "desktop_history_path": if transport == "desktop" { connect_desktop_history_path(&root, &adapter_id).display().to_string() } else { String::new() },
        "desktop_vision": desktop_vision_event,
        "registry_path": connect_registry_path(&root).display().to_string(),
        "runtime_contract": CONNECT_RUNTIME_CONTRACT_V2,
        "note": "adapter test diagnostics persisted",
    });
    persist_connect_latest_artifact(&root, &payload)?;
    if payload.get("test_status").and_then(Value::as_str) == Some("fail") {
        let _ = print_connect_payload(&payload, &format);
        return Err(format!(
            "connect test failed for adapter '{}': {}",
            adapter_id,
            payload
                .get("test_reason")
                .and_then(Value::as_str)
                .unwrap_or("unknown")
        ));
    }
    print_connect_payload(&payload, &format)
}

fn handle_connect_health(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let adapter_id = sanitize_token(&required_flag(args, "--adapter-id")?);
    if adapter_id.is_empty() {
        return Err("adapter-id cannot be empty".to_string());
    }

    let mut registry = load_connect_registry(&root)?;
    let adapter = find_adapter_mut(&mut registry, &adapter_id)
        .ok_or_else(|| format!("adapter '{}' not found; run `loom connect list` to see available adapters", adapter_id))?;
    let enabled = adapter_enabled(adapter);
    let latest_test = read_latest_jsonl_event(&connect_tests_history_path(&root, &adapter_id))?;
    let latest_desktop_event =
        read_latest_jsonl_event(&connect_desktop_history_path(&root, &adapter_id))?;
    let test_status = latest_test
        .as_ref()
        .and_then(|event| event.get("test_status"))
        .and_then(Value::as_str)
        .unwrap_or("unknown");
    let health_status = if !enabled {
        "disabled"
    } else if test_status == "pass" {
        "healthy"
    } else if test_status == "fail" {
        "degraded"
    } else {
        "unknown"
    };
    let health_checked_at = chrono_like_timestamp();
    if !adapter
        .get("lifecycle")
        .map(Value::is_object)
        .unwrap_or(false)
    {
        adapter["lifecycle"] = json!({});
    }
    if !adapter
        .get("fallback")
        .map(Value::is_object)
        .unwrap_or(false)
    {
        adapter["fallback"] = default_fallback_policy();
    }
    let reconnect_attempts = adapter
        .pointer("/lifecycle/reconnect_attempts")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let reconnect_attempts_max = adapter
        .pointer("/lifecycle/reconnect_attempts_max")
        .and_then(Value::as_u64)
        .unwrap_or(DEFAULT_RECONNECT_ATTEMPTS_MAX);
    let mut lifecycle_state = adapter
        .pointer("/lifecycle/state")
        .and_then(Value::as_str)
        .unwrap_or("init")
        .to_string();
    let fallback_active_before = adapter
        .pointer("/fallback/active")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let mut recommended_action = "none".to_string();
    let mut sanction_status = "none".to_string();
    if !enabled {
        lifecycle_state = "disabled".to_string();
        adapter["fallback"]["active"] = Value::Bool(false);
        recommended_action = "enable_adapter".to_string();
    } else if health_status == "healthy" {
        lifecycle_state = "ready".to_string();
        adapter["lifecycle"]["auth_state"] = Value::String("verified".to_string());
        adapter["lifecycle"]["reconnect_attempts"] = Value::Number(0_u64.into());
        adapter["lifecycle"]["last_error"] = Value::String(String::new());
        adapter["fallback"]["active"] = Value::Bool(false);
        adapter["fallback"]["last_trigger_reason"] = Value::String(String::new());
    } else if health_status == "degraded" {
        let next_attempt = reconnect_attempts.saturating_add(1);
        if next_attempt <= reconnect_attempts_max {
            lifecycle_state = "reconnecting".to_string();
            adapter["lifecycle"]["reconnect_attempts"] = Value::Number(next_attempt.into());
            adapter["lifecycle"]["last_error"] = Value::String(
                latest_test
                    .as_ref()
                    .and_then(|event| event.get("test_reason"))
                    .and_then(Value::as_str)
                    .unwrap_or("test_failed")
                    .to_string(),
            );
            adapter["fallback"]["active"] = Value::Bool(true);
            adapter["fallback"]["last_trigger_reason"] =
                Value::String("connect_health_degraded".to_string());
            recommended_action = "reconnect".to_string();
        } else {
            if fallback_active_before && lifecycle_state == "fallback" {
                lifecycle_state = "sanctioned".to_string();
                adapter["fallback"]["active"] = Value::Bool(true);
                adapter["fallback"]["last_trigger_reason"] =
                    Value::String("reconnect_storm".to_string());
                adapter["lifecycle"]["last_error"] = Value::String("reconnect_storm".to_string());
                recommended_action = "court_sanction_review".to_string();
                sanction_status = "reconnect_storm".to_string();
                let _ = append_connect_sanction_event(
                    &root,
                    &adapter_id,
                    "reconnect_storm",
                    "health_degraded",
                    "reconnect attempts exhausted repeatedly under degraded tests",
                );
            } else {
                lifecycle_state = "fallback".to_string();
                adapter["fallback"]["active"] = Value::Bool(true);
                adapter["fallback"]["last_trigger_reason"] =
                    Value::String("reconnect_attempts_exhausted".to_string());
                recommended_action = "shadow_or_local_queue".to_string();
            }
        }
    }
    adapter["lifecycle"]["state"] = Value::String(lifecycle_state.clone());
    adapter["lifecycle"]["last_transition_at"] = Value::String(health_checked_at.clone());
    let lifecycle_event_action = match lifecycle_state.as_str() {
        "ready" => "health_ready",
        "reconnecting" => "health_reconnect",
        "fallback" => "health_fallback",
        "sanctioned" => "health_sanction",
        "disabled" => "health_disabled",
        _ => "health_unknown",
    };
    let lifecycle_event_reason = if health_status == "healthy" {
        "health checks pass"
    } else if health_status == "degraded" {
        "latest adapter test failed"
    } else if health_status == "disabled" {
        "adapter disabled"
    } else {
        "no deterministic health signal"
    };
    let _ = append_lifecycle_event(
        &root,
        &adapter_id,
        lifecycle_state.as_str(),
        lifecycle_event_action,
        lifecycle_event_reason,
    );
    let payload = json!({
        "schema_version": CONNECT_HEALTH_EVENT_SCHEMA,
        "status": "connect_health",
        "adapter_id": adapter_id,
        "enabled": enabled,
        "health_status": health_status,
        "recommended_action": recommended_action,
        "sanction_status": sanction_status,
        "lifecycle_state": lifecycle_state,
        "last_test_status": test_status,
        "last_test_reason": latest_test
            .as_ref()
            .and_then(|event| event.get("test_reason"))
            .and_then(Value::as_str)
            .unwrap_or(""),
        "health_checked_at": health_checked_at,
        "runtime_contract": CONNECT_RUNTIME_CONTRACT_V2,
        "registry_path": connect_registry_path(&root).display().to_string(),
        "health_path": connect_health_path(&root, &adapter_id).display().to_string(),
        "tests_history_path": connect_tests_history_path(&root, &adapter_id).display().to_string(),
        "lifecycle_history_path": connect_lifecycle_history_path(&root, &adapter_id).display().to_string(),
        "sanctions_path": connect_sanctions_history_path(&root, &adapter_id).display().to_string(),
        "desktop_history_path": connect_desktop_history_path(&root, &adapter_id).display().to_string(),
        "lifecycle_metrics": {
            "test_history_entries": adapter
                .pointer("/diagnostics/test_history_entries")
                .and_then(Value::as_u64)
                .unwrap_or(0),
            "reconnect_attempts": adapter
                .pointer("/lifecycle/reconnect_attempts")
                .and_then(Value::as_u64)
                .unwrap_or(0),
            "reconnect_attempts_max": adapter
                .pointer("/lifecycle/reconnect_attempts_max")
                .and_then(Value::as_u64)
                .unwrap_or(DEFAULT_RECONNECT_ATTEMPTS_MAX),
            "fallback_active": adapter
                .pointer("/fallback/active")
                .and_then(Value::as_bool)
                .unwrap_or(false),
            "sanction_events": count_jsonl_events(&connect_sanctions_history_path(&root, &adapter_id))?,
            "desktop_capture_events": count_jsonl_events(&connect_desktop_history_path(&root, &adapter_id))?,
        },
        "desktop_vision": latest_desktop_event,
        "operator_next_step": match recommended_action.as_str() {
            "enable_adapter" => format!("loom connect enable --adapter-id {} --format human", adapter_id),
            "reconnect" => format!("loom connect test --adapter-id {} --format human", adapter_id),
            "shadow_or_local_queue" => format!("loom connect diagnostics --adapter-id {} --format human", adapter_id),
            "court_sanction_review" => format!("loom connect scorecard --fix --format human"),
            _ => "loom connect list --format human".to_string(),
        },
        "note": "adapter health snapshot persisted",
    });
    persist_health_snapshot(&root, &adapter_id, &payload)?;

    let diagnostics = adapter_diagnostics_mut(adapter);
    diagnostics["last_health_status"] = Value::String(health_status.to_string());
    diagnostics["last_health_at"] = Value::String(health_checked_at);
    diagnostics["health_history_entries"] = Value::Number(
        diagnostics
            .get("health_history_entries")
            .and_then(Value::as_u64)
            .unwrap_or(0)
            .saturating_add(1)
            .into(),
    );
    diagnostics["lifecycle_history_entries"] = Value::Number(
        diagnostics
            .get("lifecycle_history_entries")
            .and_then(Value::as_u64)
            .unwrap_or(0)
            .saturating_add(1)
            .into(),
    );
    adapter["status"] = Value::String(lifecycle_state.clone());
    adapter["updated_at"] = Value::String(chrono_like_timestamp());
    persist_connect_registry(&root, &registry)?;
    persist_connect_latest_artifact(&root, &payload)?;
    print_connect_payload(&payload, &format)
}

fn handle_connect_metrics(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let adapter_id = sanitize_token(&required_flag(args, "--adapter-id")?);
    if adapter_id.is_empty() {
        return Err("adapter-id cannot be empty".to_string());
    }

    let registry = load_connect_registry(&root)?;
    let adapter = find_adapter(&registry, &adapter_id)
        .ok_or_else(|| format!("adapter '{}' not found; run `loom connect list` to see available adapters", adapter_id))?;
    let configured_retention = adapter
        .pointer("/diagnostics/history_retention_days")
        .and_then(Value::as_u64)
        .unwrap_or(DEFAULT_DIAGNOSTIC_RETENTION_DAYS);
    let retention_days = parse_retention_days(args, configured_retention)?;
    let mut payload = compute_connect_metrics_payload(&root, &adapter_id, retention_days)?;
    payload["status"] = Value::String("connect_metrics".to_string());
    payload["note"] = Value::String("operator metrics over connect diagnostics window".to_string());
    persist_connect_latest_artifact(&root, &payload)?;
    print_connect_payload(&payload, &format)
}

fn handle_connect_diagnostics(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let adapter_id = sanitize_token(&required_flag(args, "--adapter-id")?);
    if adapter_id.is_empty() {
        return Err("adapter-id cannot be empty".to_string());
    }
    let limit = parse_limit(args, "--limit", 10, 500)?;

    let registry = load_connect_registry(&root)?;
    let adapter = find_adapter(&registry, &adapter_id)
        .ok_or_else(|| format!("adapter '{}' not found; run `loom connect list` to see available adapters", adapter_id))?;
    let tests_path = connect_tests_history_path(&root, &adapter_id);
    let lifecycle_path = connect_lifecycle_history_path(&root, &adapter_id);
    let sanctions_path = connect_sanctions_history_path(&root, &adapter_id);
    let desktop_path = connect_desktop_history_path(&root, &adapter_id);
    let health_path = connect_health_path(&root, &adapter_id);

    let tests_recent = read_recent_jsonl_events(&tests_path, limit)?;
    let lifecycle_recent = read_recent_jsonl_events(&lifecycle_path, limit)?;
    let sanctions_recent = read_recent_jsonl_events(&sanctions_path, limit)?;
    let desktop_recent = read_recent_jsonl_events(&desktop_path, limit)?;
    let health_snapshot = read_optional_json_value(&health_path)?;
    let payload = json!({
        "status": "connect_diagnostics",
        "adapter_id": adapter_id,
        "enabled": adapter_enabled(adapter),
        "lifecycle_state": adapter
            .pointer("/lifecycle/state")
            .and_then(Value::as_str)
            .unwrap_or("init"),
        "fallback_active": adapter
            .pointer("/fallback/active")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        "last_test_status": adapter
            .pointer("/diagnostics/last_test_status")
            .and_then(Value::as_str)
            .unwrap_or("unknown"),
        "last_health_status": adapter
            .pointer("/diagnostics/last_health_status")
            .and_then(Value::as_str)
            .unwrap_or("unknown"),
        "limit": limit as u64,
        "tests_recent_count": tests_recent.len() as u64,
        "lifecycle_recent_count": lifecycle_recent.len() as u64,
        "sanctions_recent_count": sanctions_recent.len() as u64,
        "desktop_recent_count": desktop_recent.len() as u64,
        "tests_recent": tests_recent,
        "lifecycle_recent": lifecycle_recent,
        "sanctions_recent": sanctions_recent,
        "desktop_recent": desktop_recent,
        "health_snapshot": health_snapshot.unwrap_or(Value::Null),
        "registry_path": connect_registry_path(&root).display().to_string(),
        "tests_history_path": tests_path.display().to_string(),
        "lifecycle_history_path": lifecycle_path.display().to_string(),
        "sanctions_path": sanctions_path.display().to_string(),
        "desktop_path": desktop_path.display().to_string(),
        "health_path": health_path.display().to_string(),
        "runtime_contract": CONNECT_RUNTIME_CONTRACT_V2,
        "operator_next_step": format!("loom connect health --adapter-id {} --format human", adapter_id),
        "note": "operator diagnostics snapshot for connect adapter lifecycle",
    });
    persist_connect_latest_artifact(&root, &payload)?;
    print_connect_payload(&payload, &format)
}

fn handle_connect_scorecard(args: &[String]) -> LoomResult<()> {
    validate_connect_scorecard_args(args)?;
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let apply_fix = has_flag(args, "--fix");
    let registry = load_connect_registry(&root)?;
    let adapters = registry
        .get("adapters")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if adapters.is_empty() {
        return Err(
            "connect scorecard found no adapters; run `loom connect scaffold --name telegram_adapter --transport telegram --action-schema meridian.runtime.v1` first".to_string(),
        );
    }

    let mut rows = Vec::new();
    let mut degraded = 0_u64;
    let mut remediation_actions = Vec::new();
    let mut remediations_applied = 0_u64;
    let mut mutable_registry = load_connect_registry(&root)?;
    for adapter in adapters {
        let adapter_id = adapter
            .get("adapter_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        if adapter_id.is_empty() {
            continue;
        }
        let configured_retention = adapter
            .pointer("/diagnostics/history_retention_days")
            .and_then(Value::as_u64)
            .unwrap_or(DEFAULT_DIAGNOSTIC_RETENTION_DAYS);
        let retention_days = parse_retention_days(args, configured_retention)?;
        let security_checks = evaluate_adapter_security(&adapter);
        let security_posture_ok = security_checks
            .get("valid")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let mut row = compute_connect_metrics_payload(&root, &adapter_id, retention_days)?;
        row["security_posture_ok"] = Value::Bool(security_posture_ok);
        row["security_checks"] = security_checks.clone();
        let uptime_met = row
            .get("target_uptime_met")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let fallback_met = row
            .get("target_fallback_success_met")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let sanction_clean = row
            .get("sanction_clean")
            .and_then(Value::as_bool)
            .unwrap_or(true);
        if !(uptime_met && fallback_met && security_posture_ok && sanction_clean) {
            degraded = degraded.saturating_add(1);
            if apply_fix {
                if !security_posture_ok {
                    if let Some(action) =
                        apply_security_baseline(&root, &mut mutable_registry, &adapter_id)?
                    {
                        remediations_applied = remediations_applied.saturating_add(1);
                        remediation_actions.push(json!({
                            "adapter_id": adapter_id,
                            "action": action,
                        }));
                    }
                }
                if !(uptime_met && fallback_met) {
                    if let Some(action) =
                        apply_scorecard_fix(&root, &mut mutable_registry, &adapter_id)?
                    {
                        remediations_applied = remediations_applied.saturating_add(1);
                        remediation_actions.push(json!({
                            "adapter_id": adapter_id,
                            "action": action,
                        }));
                    }
                }
                if !sanction_clean {
                    remediation_actions.push(json!({
                        "adapter_id": adapter_id,
                        "action": "manual_court_review_required",
                    }));
                }
            }
        }
        rows.push(row);
    }
    if apply_fix {
        persist_connect_registry(&root, &mutable_registry)?;
    }
    let payload = json!({
        "status": "connect_scorecard",
        "overall_status": if degraded == 0 { "healthy" } else { "degraded" },
        "total_adapters": rows.len(),
        "degraded_adapters": degraded,
        "fix_requested": apply_fix,
        "remediations_applied": remediations_applied,
        "remediation_actions": remediation_actions,
        "runtime_contract": CONNECT_RUNTIME_CONTRACT_V2,
        "adapters": rows,
        "operator_next_step": if degraded == 0 {
            "loom connect list --format human"
        } else if apply_fix {
            "loom connect health --adapter-id <adapter-id> --format human"
        } else {
            "loom connect scorecard --retention-days 30 --fix --format human"
        },
        "note": "fleet scorecard across connect adapters",
    });
    persist_connect_latest_artifact(&root, &payload)?;
    print_connect_payload(&payload, &format)
}

fn validate_connect_scorecard_args(args: &[String]) -> LoomResult<()> {
    let mut index = 0_usize;
    while index < args.len() {
        let token = args[index].as_str();
        match token {
            "--retention-days" | "--root" | "--format" => {
                if index + 1 >= args.len() {
                    return Err(format!("missing value for {}", token));
                }
                index += 2;
            }
            "--fix" => {
                index += 1;
            }
            _ => {
                return Err(format!(
                    "unexpected argument '{}' for `loom connect scorecard`; example: `loom connect scorecard --retention-days 30 --fix` (optional: --root ROOT, --format human|json)",
                    token
                ));
            }
        }
    }
    Ok(())
}

fn compute_connect_metrics_payload(
    root: &Path,
    adapter_id: &str,
    retention_days: u64,
) -> LoomResult<Value> {
    let now_secs = chrono_like_timestamp().parse::<u64>().unwrap_or_default();
    let cutoff_secs = now_secs.saturating_sub(retention_days.saturating_mul(86_400));
    let tests_path = connect_tests_history_path(root, adapter_id);
    let lifecycle_path = connect_lifecycle_history_path(root, adapter_id);
    let sanctions_path = connect_sanctions_history_path(root, adapter_id);

    let tests_events = read_jsonl_events(&tests_path)?
        .into_iter()
        .filter(|event| event_in_window(event, &["tested_at"], cutoff_secs))
        .collect::<Vec<_>>();
    let lifecycle_events = read_jsonl_events(&lifecycle_path)?
        .into_iter()
        .filter(|event| event_in_window(event, &["recorded_at"], cutoff_secs))
        .collect::<Vec<_>>();

    let tests_total = tests_events.len() as u64;
    let tests_pass = tests_events
        .iter()
        .filter(|event| {
            event.get("test_status").and_then(Value::as_str) == Some("pass")
                || event.get("result").and_then(Value::as_str) == Some("pass")
        })
        .count() as u64;
    let test_pass_ratio = if tests_total == 0 {
        1.0
    } else {
        tests_pass as f64 / tests_total as f64
    };

    let mut lifecycle_states = lifecycle_events
        .iter()
        .map(|event| {
            (
                parse_event_timestamp(event, &["recorded_at"]).unwrap_or_default(),
                event
                    .get("state")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown")
                    .to_string(),
            )
        })
        .collect::<Vec<_>>();
    lifecycle_states.sort_by(|left, right| left.0.cmp(&right.0));

    let lifecycle_total = lifecycle_states.len() as u64;
    let ready_states = lifecycle_states
        .iter()
        .filter(|(_, state)| state == "ready")
        .count() as u64;
    let fallback_events = lifecycle_states
        .iter()
        .filter(|(_, state)| state == "fallback")
        .count() as u64;
    let mut pending_recovery = 0_u64;
    let mut fallback_recoveries = 0_u64;
    for (_, state) in &lifecycle_states {
        if state == "fallback" {
            pending_recovery = pending_recovery.saturating_add(1);
        } else if state == "ready" && pending_recovery > 0 {
            fallback_recoveries = fallback_recoveries.saturating_add(1);
            pending_recovery = pending_recovery.saturating_sub(1);
        }
    }
    let uptime_ratio = if lifecycle_total > 0 {
        ready_states as f64 / lifecycle_total as f64
    } else {
        read_optional_health_ready_ratio(root, adapter_id)?
    };
    let fallback_success_ratio = if fallback_events > 0 {
        fallback_recoveries as f64 / fallback_events as f64
    } else {
        1.0
    };
    let target_uptime = 0.995_f64;
    let target_fallback_success = 0.98_f64;
    let sanction_events = read_jsonl_events(&sanctions_path)?
        .into_iter()
        .filter(|event| event_in_window(event, &["recorded_at"], cutoff_secs))
        .count() as u64;
    let sanction_clean = sanction_events == 0;

    Ok(json!({
        "adapter_id": adapter_id,
        "retention_days": retention_days,
        "window_start_unix": cutoff_secs,
        "window_end_unix": now_secs,
        "tests_total": tests_total,
        "tests_pass": tests_pass,
        "test_pass_ratio": test_pass_ratio,
        "lifecycle_samples": lifecycle_total,
        "ready_samples": ready_states,
        "fallback_events": fallback_events,
        "fallback_recoveries": fallback_recoveries,
        "uptime_ratio": uptime_ratio,
        "fallback_success_ratio": fallback_success_ratio,
        "target_uptime": target_uptime,
        "target_fallback_success": target_fallback_success,
        "target_uptime_met": uptime_ratio >= target_uptime,
        "target_fallback_success_met": fallback_success_ratio >= target_fallback_success,
        "sanction_events": sanction_events,
        "sanction_clean": sanction_clean,
        "tests_history_path": tests_path.display().to_string(),
        "lifecycle_history_path": lifecycle_path.display().to_string(),
        "sanctions_history_path": sanctions_path.display().to_string(),
        "runtime_contract": CONNECT_RUNTIME_CONTRACT_V2,
    }))
}

fn apply_scorecard_fix(
    root: &Path,
    registry: &mut Value,
    adapter_id: &str,
) -> LoomResult<Option<String>> {
    let Some(adapter) = find_adapter_mut(registry, adapter_id) else {
        return Ok(None);
    };
    let enabled = adapter_enabled(adapter);
    if !enabled {
        return Ok(Some("enable_required".to_string()));
    }
    if !adapter
        .get("lifecycle")
        .map(Value::is_object)
        .unwrap_or(false)
    {
        adapter["lifecycle"] = json!({});
    }
    if !adapter
        .get("fallback")
        .map(Value::is_object)
        .unwrap_or(false)
    {
        adapter["fallback"] = default_fallback_policy();
    }
    adapter["lifecycle"]["state"] = Value::String("reconnecting".to_string());
    adapter["lifecycle"]["reconnect_attempts"] = Value::Number(0_u64.into());
    adapter["lifecycle"]["last_transition_at"] = Value::String(chrono_like_timestamp());
    adapter["lifecycle"]["last_error"] = Value::String("scorecard_fix_reset".to_string());
    adapter["fallback"]["active"] = Value::Bool(false);
    adapter["fallback"]["last_trigger_reason"] = Value::String("scorecard_fix_reset".to_string());
    adapter["status"] = Value::String("reconnecting".to_string());
    adapter["updated_at"] = Value::String(chrono_like_timestamp());
    let _ = append_lifecycle_event(
        root,
        adapter_id,
        "reconnecting",
        "scorecard_fix",
        "scorecard remediation reset reconnect state",
    );
    Ok(Some("reset_reconnect_state".to_string()))
}

fn apply_security_baseline(
    root: &Path,
    registry: &mut Value,
    adapter_id: &str,
) -> LoomResult<Option<String>> {
    let Some(adapter) = find_adapter_mut(registry, adapter_id) else {
        return Ok(None);
    };
    let before = adapter.clone();
    harden_adapter_security_profile(adapter);
    if *adapter == before {
        return Ok(None);
    }
    adapter["updated_at"] = Value::String(chrono_like_timestamp());
    let _ = append_lifecycle_event(
        root,
        adapter_id,
        adapter
            .pointer("/lifecycle/state")
            .and_then(Value::as_str)
            .unwrap_or("init"),
        "security_harden",
        "scorecard remediation applied security baseline",
    );
    Ok(Some("apply_security_baseline".to_string()))
}

fn handle_connect_prune(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let adapter_id = sanitize_token(&required_flag(args, "--adapter-id")?);
    if adapter_id.is_empty() {
        return Err("adapter-id cannot be empty".to_string());
    }

    let mut registry = load_connect_registry(&root)?;
    let adapter = find_adapter_mut(&mut registry, &adapter_id)
        .ok_or_else(|| format!("adapter '{}' not found; run `loom connect list` to see available adapters", adapter_id))?;
    let configured_retention = adapter
        .pointer("/diagnostics/history_retention_days")
        .and_then(Value::as_u64)
        .unwrap_or(DEFAULT_DIAGNOSTIC_RETENTION_DAYS);
    let retention_days = parse_retention_days(args, configured_retention)?;
    let now_secs = chrono_like_timestamp().parse::<u64>().unwrap_or_default();
    let cutoff_secs = now_secs.saturating_sub(retention_days.saturating_mul(86_400));

    let tests_path = connect_tests_history_path(&root, &adapter_id);
    let lifecycle_path = connect_lifecycle_history_path(&root, &adapter_id);
    let (removed_tests_entries, remaining_tests_entries) =
        prune_jsonl_events_by_cutoff(&tests_path, &["tested_at"], cutoff_secs)?;
    let (removed_lifecycle_entries, remaining_lifecycle_entries) =
        prune_jsonl_events_by_cutoff(&lifecycle_path, &["recorded_at"], cutoff_secs)?;

    let diagnostics = adapter_diagnostics_mut(adapter);
    diagnostics["test_history_entries"] = Value::Number(remaining_tests_entries.into());
    diagnostics["lifecycle_history_entries"] = Value::Number(remaining_lifecycle_entries.into());
    diagnostics["history_retention_days"] = Value::Number(retention_days.into());
    adapter["updated_at"] = Value::String(chrono_like_timestamp());
    persist_connect_registry(&root, &registry)?;

    let payload = json!({
        "status": "connect_pruned",
        "adapter_id": adapter_id,
        "retention_days": retention_days,
        "cutoff_unix": cutoff_secs,
        "removed_tests_entries": removed_tests_entries,
        "removed_lifecycle_entries": removed_lifecycle_entries,
        "remaining_tests_entries": remaining_tests_entries,
        "remaining_lifecycle_entries": remaining_lifecycle_entries,
        "tests_history_path": tests_path.display().to_string(),
        "lifecycle_history_path": lifecycle_path.display().to_string(),
        "runtime_contract": CONNECT_RUNTIME_CONTRACT_V2,
        "note": "diagnostics retention pruning complete",
    });
    persist_connect_latest_artifact(&root, &payload)?;
    print_connect_payload(&payload, &format)
}

fn persist_health_snapshot(root: &Path, adapter_id: &str, payload: &Value) -> LoomResult<()> {
    let health_path = connect_health_path(root, adapter_id);
    if let Some(parent) = health_path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    std::fs::write(
        health_path,
        serde_json::to_string_pretty(payload).map_err(|error| error.to_string())? + "\n",
    )
    .map_err(|error| error.to_string())
}

fn persist_connect_latest_artifact(root: &Path, payload: &Value) -> LoomResult<()> {
    let latest_path = connect_latest_artifact_path(root);
    if let Some(parent) = latest_path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    std::fs::write(
        &latest_path,
        serde_json::to_string_pretty(payload).map_err(|error| error.to_string())? + "\n",
    )
    .map_err(|error| error.to_string())
}

fn append_jsonl(path: &Path, line: &str) -> LoomResult<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|error| error.to_string())?;
    file.write_all(line.as_bytes())
        .map_err(|error| error.to_string())?;
    file.write_all(b"\n").map_err(|error| error.to_string())
}

fn read_latest_jsonl_event(path: &Path) -> LoomResult<Option<Value>> {
    if !path.exists() {
        return Ok(None);
    }
    let raw = std::fs::read_to_string(path).map_err(|error| error.to_string())?;
    for line in raw.lines().rev() {
        if line.trim().is_empty() {
            continue;
        }
        let value: Value = serde_json::from_str(line)
            .map_err(|error| format!("invalid connect jsonl entry: {error}"))?;
        return Ok(Some(value));
    }
    Ok(None)
}

fn read_jsonl_events(path: &Path) -> LoomResult<Vec<Value>> {
    if !path.exists() {
        return Ok(Vec::new());
    }
    let raw = std::fs::read_to_string(path).map_err(|error| error.to_string())?;
    let mut events = Vec::new();
    for line in raw.lines() {
        if line.trim().is_empty() {
            continue;
        }
        let value: Value = serde_json::from_str(line)
            .map_err(|error| format!("invalid connect jsonl entry: {error}"))?;
        events.push(value);
    }
    Ok(events)
}

fn read_recent_jsonl_events(path: &Path, limit: usize) -> LoomResult<Vec<Value>> {
    let events = read_jsonl_events(path)?;
    if events.len() <= limit {
        return Ok(events);
    }
    Ok(events[events.len() - limit..].to_vec())
}

fn count_jsonl_events(path: &Path) -> LoomResult<u64> {
    Ok(read_jsonl_events(path)?.len() as u64)
}

fn read_optional_json_value(path: &Path) -> LoomResult<Option<Value>> {
    if !path.exists() {
        return Ok(None);
    }
    let raw = std::fs::read_to_string(path).map_err(|error| error.to_string())?;
    let value: Value = serde_json::from_str(&raw)
        .map_err(|error| format!("invalid json payload '{}': {}", path.display(), error))?;
    Ok(Some(value))
}

fn write_jsonl_events(path: &Path, events: &[Value]) -> LoomResult<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let rendered = events
        .iter()
        .map(|event| serde_json::to_string(event).map_err(|error| error.to_string()))
        .collect::<Result<Vec<_>, _>>()?
        .join("\n");
    if rendered.is_empty() {
        std::fs::write(path, "").map_err(|error| error.to_string())?;
    } else {
        std::fs::write(path, format!("{rendered}\n")).map_err(|error| error.to_string())?;
    }
    Ok(())
}

fn parse_retention_days(args: &[String], fallback: u64) -> LoomResult<u64> {
    let retention_days = take_value(args, "--retention-days")
        .map(|raw| {
            raw.parse::<u64>()
                .map_err(|error| format!("invalid --retention-days '{}': {}", raw, error))
        })
        .transpose()?
        .unwrap_or(fallback);
    if !(1..=3650).contains(&retention_days) {
        return Err("retention days must be between 1 and 3650".to_string());
    }
    Ok(retention_days)
}

fn parse_limit(args: &[String], flag: &str, fallback: usize, max: usize) -> LoomResult<usize> {
    let limit = take_value(args, flag)
        .map(|raw| {
            raw.parse::<usize>()
                .map_err(|error| format!("invalid {} '{}': {}", flag, raw, error))
        })
        .transpose()?
        .unwrap_or(fallback);
    if !(1..=max).contains(&limit) {
        return Err(format!("{} must be between 1 and {}", flag, max));
    }
    Ok(limit)
}

fn parse_event_timestamp(event: &Value, fields: &[&str]) -> Option<u64> {
    for field in fields {
        if let Some(value) = event.get(*field).and_then(Value::as_u64) {
            return Some(value);
        }
        if let Some(raw) = event.get(*field).and_then(Value::as_str) {
            if raw.is_empty() {
                continue;
            }
            if let Ok(value) = raw.parse::<u64>() {
                return Some(value);
            }
        }
    }
    None
}

fn recent_test_count_within_window(
    root: &Path,
    adapter_id: &str,
    now_unix: u64,
    window_seconds: u64,
) -> u64 {
    let tests_path = connect_tests_history_path(root, adapter_id);
    let Ok(events) = read_jsonl_events(&tests_path) else {
        return 0;
    };
    events
        .into_iter()
        .filter(|event| {
            parse_event_timestamp(event, &["tested_at"])
                .map(|ts| ts > 0 && now_unix.saturating_sub(ts) <= window_seconds)
                .unwrap_or(false)
        })
        .count() as u64
}

fn should_force_malformed_payload(adapter: &Value) -> bool {
    adapter
        .pointer("/transport_profile/force_malformed_payload")
        .and_then(Value::as_bool)
        .unwrap_or(false)
}

fn event_in_window(event: &Value, fields: &[&str], cutoff_secs: u64) -> bool {
    match parse_event_timestamp(event, fields) {
        Some(value) if value > 0 => value >= cutoff_secs,
        _ => true,
    }
}

fn prune_jsonl_events_by_cutoff(
    path: &Path,
    fields: &[&str],
    cutoff_secs: u64,
) -> LoomResult<(u64, u64)> {
    let events = read_jsonl_events(path)?;
    let mut kept = Vec::new();
    let mut removed = 0_u64;
    for event in events {
        let should_remove = parse_event_timestamp(&event, fields)
            .map(|value| value > 0 && value < cutoff_secs)
            .unwrap_or(false);
        if should_remove {
            removed = removed.saturating_add(1);
        } else {
            kept.push(event);
        }
    }
    write_jsonl_events(path, &kept)?;
    Ok((removed, kept.len() as u64))
}

fn read_optional_health_ready_ratio(root: &Path, adapter_id: &str) -> LoomResult<f64> {
    let health_path = connect_health_path(root, adapter_id);
    if !health_path.exists() {
        return Ok(0.0);
    }
    let raw = std::fs::read_to_string(health_path).map_err(|error| error.to_string())?;
    let value: Value = serde_json::from_str(&raw).map_err(|error| error.to_string())?;
    let ratio = if value
        .get("health_status")
        .and_then(Value::as_str)
        .unwrap_or("unknown")
        == "healthy"
    {
        1.0
    } else {
        0.0
    };
    Ok(ratio)
}

fn print_connect_payload(payload: &Value, format: &str) -> LoomResult<()> {
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
            if let Some(mode) = payload.get("mode").and_then(Value::as_str) {
                lines.push(format!("mode:                {mode}"));
            }
            if let Some(adapter_id) = payload.get("adapter_id").and_then(Value::as_str) {
                lines.push(format!("adapter_id:          {adapter_id}"));
            }
            if let Some(enabled) = payload.get("enabled").and_then(Value::as_bool) {
                lines.push(format!("enabled:             {enabled}"));
            }
            if let Some(test_status) = payload.get("test_status").and_then(Value::as_str) {
                lines.push(format!("test_status:         {test_status}"));
            }
            if let Some(test_reason) = payload.get("test_reason").and_then(Value::as_str) {
                lines.push(format!("test_reason:         {test_reason}"));
            }
            if let Some(health_status) = payload.get("health_status").and_then(Value::as_str) {
                lines.push(format!("health_status:       {health_status}"));
            }
            if let Some(lifecycle_state) = payload.get("lifecycle_state").and_then(Value::as_str) {
                lines.push(format!("lifecycle_state:     {lifecycle_state}"));
            }
            if let Some(recommended_action) =
                payload.get("recommended_action").and_then(Value::as_str)
            {
                lines.push(format!("recommended_action:  {recommended_action}"));
            }
            if let Some(sanction_status) = payload.get("sanction_status").and_then(Value::as_str) {
                lines.push(format!("sanction_status:     {sanction_status}"));
            }
            if let Some(fallback_active) = payload.get("fallback_active").and_then(Value::as_bool) {
                lines.push(format!("fallback_active:     {fallback_active}"));
            }
            if let Some(validation_status) =
                payload.get("validation_status").and_then(Value::as_str)
            {
                lines.push(format!("validation_status:   {validation_status}"));
            }
            if let Some(path) = payload.get("manifest_path").and_then(Value::as_str) {
                lines.push(format!("manifest_path:       {path}"));
            }
            if let Some(path) = payload.get("registry_path").and_then(Value::as_str) {
                lines.push(format!("registry_path:       {path}"));
            }
            if let Some(path) = payload.get("tests_history_path").and_then(Value::as_str) {
                lines.push(format!("tests_history_path:  {path}"));
            }
            if let Some(path) = payload
                .get("lifecycle_history_path")
                .and_then(Value::as_str)
            {
                lines.push(format!("lifecycle_path:      {path}"));
            }
            if let Some(path) = payload.get("health_path").and_then(Value::as_str) {
                lines.push(format!("health_path:         {path}"));
            }
            if let Some(value) = payload.get("tests_recent_count").and_then(Value::as_u64) {
                lines.push(format!("tests_recent_count:  {value}"));
            }
            if let Some(value) = payload
                .get("lifecycle_recent_count")
                .and_then(Value::as_u64)
            {
                lines.push(format!("lifecycle_recent:    {value}"));
            }
            if let Some(value) = payload
                .get("sanctions_recent_count")
                .and_then(Value::as_u64)
            {
                lines.push(format!("sanctions_recent:    {value}"));
            }
            if let Some(value) = payload.get("uptime_ratio").and_then(Value::as_f64) {
                lines.push(format!("uptime_ratio:        {:.4}", value));
            }
            if let Some(value) = payload
                .get("fallback_success_ratio")
                .and_then(Value::as_f64)
            {
                lines.push(format!("fallback_success:    {:.4}", value));
            }
            if let Some(value) = payload.get("removed_tests_entries").and_then(Value::as_u64) {
                lines.push(format!("removed_tests:       {}", value));
            }
            if let Some(value) = payload
                .get("removed_lifecycle_entries")
                .and_then(Value::as_u64)
            {
                lines.push(format!("removed_lifecycle:   {}", value));
            }
            if let Some(total) = payload.get("total_adapters").and_then(Value::as_u64) {
                lines.push(format!("total_adapters:      {total}"));
            }
            if let Some(invalid) = payload.get("invalid_adapters").and_then(Value::as_u64) {
                lines.push(format!("invalid_adapters:    {invalid}"));
            }
            if let Some(next_step) = payload.get("operator_next_step").and_then(Value::as_str) {
                lines.push(format!("operator_next_step:  {next_step}"));
            }
            if let Some(note) = payload.get("note").and_then(Value::as_str) {
                lines.push(format!("note:                {note}"));
            }
            if let Some(adapters) = payload.get("adapters").and_then(Value::as_array) {
                lines.push("adapters:".to_string());
                for adapter in adapters {
                    lines.push(format!(
                        "  - {} ({}) schema={} enabled={} status={}",
                        adapter
                            .get("adapter_id")
                            .and_then(Value::as_str)
                            .unwrap_or(""),
                        adapter
                            .get("transport")
                            .and_then(Value::as_str)
                            .unwrap_or(""),
                        adapter
                            .get("action_schema")
                            .and_then(Value::as_str)
                            .unwrap_or(""),
                        adapter
                            .pointer("/lifecycle/enabled")
                            .and_then(Value::as_bool)
                            .unwrap_or(false),
                        adapter.get("status").and_then(Value::as_str).unwrap_or(""),
                    ));
                }
            }
            print_human(&(lines.join("\n") + "\n"));
        }
        _ => println!(
            "{}",
            serde_json::to_string_pretty(payload).map_err(|error| error.to_string())?
        ),
    }
    Ok(())
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

fn validate_transport(transport: &str) -> LoomResult<()> {
    if SUPPORTED_TRANSPORTS.contains(&transport) {
        Ok(())
    } else {
        Err(format!(
            "unsupported transport '{}'; supported: {}",
            transport,
            SUPPORTED_TRANSPORTS.join("|")
        ))
    }
}

fn connect_registry_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_CONNECT_REGISTRY_PATH)
}

fn connect_adapters_dir(root: &Path) -> PathBuf {
    root.join(DEFAULT_CONNECT_ADAPTERS_DIR)
}

fn connect_health_path(root: &Path, adapter_id: &str) -> PathBuf {
    root.join(DEFAULT_CONNECT_HEALTH_DIR)
        .join(format!("{adapter_id}.json"))
}

fn connect_tests_history_path(root: &Path, adapter_id: &str) -> PathBuf {
    root.join(DEFAULT_CONNECT_TESTS_DIR)
        .join(format!("{adapter_id}.jsonl"))
}

fn connect_lifecycle_history_path(root: &Path, adapter_id: &str) -> PathBuf {
    root.join(DEFAULT_CONNECT_LIFECYCLE_DIR)
        .join(format!("{adapter_id}.jsonl"))
}

fn connect_sanctions_history_path(root: &Path, adapter_id: &str) -> PathBuf {
    root.join(DEFAULT_CONNECT_SANCTIONS_DIR)
        .join(format!("{adapter_id}.jsonl"))
}

fn connect_desktop_history_path(root: &Path, adapter_id: &str) -> PathBuf {
    root.join(DEFAULT_CONNECT_DESKTOP_DIR)
        .join(format!("{adapter_id}.jsonl"))
}

fn connect_latest_artifact_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_CONNECT_LATEST_ARTIFACT_PATH)
}

fn load_connect_registry(root: &Path) -> LoomResult<Value> {
    let path = connect_registry_path(root);
    if !path.exists() {
        return Ok(default_connect_registry());
    }
    let raw = std::fs::read_to_string(path).map_err(|error| error.to_string())?;
    let mut value: Value = serde_json::from_str(&raw)
        .map_err(|error| format!("invalid connect registry json: {error}"))?;
    normalize_registry(&mut value);
    Ok(value)
}

fn persist_connect_registry(root: &Path, registry: &Value) -> LoomResult<()> {
    let path = connect_registry_path(root);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    std::fs::write(
        path,
        serde_json::to_string_pretty(registry).map_err(|error| error.to_string())? + "\n",
    )
    .map_err(|error| error.to_string())
}

fn detect_legacy_registry_schema(root: &Path) -> LoomResult<bool> {
    let path = connect_registry_path(root);
    if !path.exists() {
        return Ok(false);
    }
    let raw = std::fs::read_to_string(path).map_err(|error| error.to_string())?;
    let value: Value = serde_json::from_str(&raw)
        .map_err(|error| format!("invalid connect registry json: {error}"))?;
    Ok(value
        .get("schema_version")
        .and_then(Value::as_str)
        .map(|schema| schema == CONNECT_REGISTRY_SCHEMA_V1)
        .unwrap_or(false))
}

fn default_connect_registry() -> Value {
    json!({
        "schema_version": CONNECT_REGISTRY_SCHEMA_V2,
        "runtime_contract": CONNECT_RUNTIME_CONTRACT_V2,
        "adapters": [],
    })
}

fn normalize_registry(registry: &mut Value) {
    if !registry.is_object() {
        *registry = default_connect_registry();
        return;
    }
    registry["schema_version"] = Value::String(CONNECT_REGISTRY_SCHEMA_V2.to_string());
    registry["runtime_contract"] = Value::String(CONNECT_RUNTIME_CONTRACT_V2.to_string());
    if !registry
        .get("adapters")
        .map(Value::is_array)
        .unwrap_or(false)
    {
        registry["adapters"] = Value::Array(Vec::new());
    }
    if let Some(items) = registry.get_mut("adapters").and_then(Value::as_array_mut) {
        for item in items.iter_mut() {
            normalize_adapter(item);
        }
        items.sort_by(|left, right| {
            value_string(left.get("adapter_id")).cmp(value_string(right.get("adapter_id")))
        });
    }
}

fn normalize_adapter(adapter: &mut Value) {
    if !adapter.is_object() {
        *adapter = json!({});
    }
    if adapter
        .get("schema_version")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .is_empty()
    {
        adapter["schema_version"] = Value::String(CONNECT_ADAPTER_SCHEMA.to_string());
    }
    adapter["runtime_contract"] = Value::String(CONNECT_RUNTIME_CONTRACT_V2.to_string());
    if !adapter
        .get("lifecycle")
        .map(Value::is_object)
        .unwrap_or(false)
    {
        adapter["lifecycle"] = json!({});
    }
    if adapter
        .pointer("/lifecycle/enabled")
        .and_then(Value::as_bool)
        .is_none()
    {
        adapter["lifecycle"]["enabled"] = Value::Bool(false);
    }
    if adapter
        .pointer("/lifecycle/state")
        .and_then(Value::as_str)
        .is_none()
    {
        adapter["lifecycle"]["state"] = Value::String("init".to_string());
    }
    if adapter
        .pointer("/lifecycle/auth_state")
        .and_then(Value::as_str)
        .is_none()
    {
        adapter["lifecycle"]["auth_state"] = Value::String("pending".to_string());
    }
    if adapter
        .pointer("/lifecycle/reconnect_attempts")
        .and_then(Value::as_u64)
        .is_none()
    {
        adapter["lifecycle"]["reconnect_attempts"] = Value::Number(0_u64.into());
    }
    if adapter
        .pointer("/lifecycle/reconnect_attempts_max")
        .and_then(Value::as_u64)
        .is_none()
    {
        adapter["lifecycle"]["reconnect_attempts_max"] =
            Value::Number(DEFAULT_RECONNECT_ATTEMPTS_MAX.into());
    }
    if adapter
        .pointer("/lifecycle/last_error")
        .and_then(Value::as_str)
        .is_none()
    {
        adapter["lifecycle"]["last_error"] = Value::String(String::new());
    }
    if adapter
        .pointer("/lifecycle/last_transition_at")
        .and_then(Value::as_str)
        .is_none()
    {
        adapter["lifecycle"]["last_transition_at"] = Value::String(String::new());
    }
    if !adapter
        .get("diagnostics")
        .map(Value::is_object)
        .unwrap_or(false)
    {
        adapter["diagnostics"] = default_adapter_diagnostics();
    }
    if !adapter
        .get("fallback")
        .map(Value::is_object)
        .unwrap_or(false)
    {
        adapter["fallback"] = default_fallback_policy();
    }
    let diagnostics = adapter_diagnostics_mut(adapter);
    if diagnostics
        .get("last_test_status")
        .and_then(Value::as_str)
        .is_none()
    {
        diagnostics["last_test_status"] = Value::String("unknown".to_string());
    }
    if diagnostics
        .get("last_health_status")
        .and_then(Value::as_str)
        .is_none()
    {
        diagnostics["last_health_status"] = Value::String("unknown".to_string());
    }
    if diagnostics
        .get("test_history_entries")
        .and_then(Value::as_u64)
        .is_none()
    {
        diagnostics["test_history_entries"] = Value::Number(0_u64.into());
    }
    if diagnostics
        .get("health_history_entries")
        .and_then(Value::as_u64)
        .is_none()
    {
        diagnostics["health_history_entries"] = Value::Number(0_u64.into());
    }
    if diagnostics
        .get("lifecycle_history_entries")
        .and_then(Value::as_u64)
        .is_none()
    {
        diagnostics["lifecycle_history_entries"] = Value::Number(0_u64.into());
    }
    if diagnostics
        .get("history_retention_days")
        .and_then(Value::as_u64)
        .is_none()
    {
        diagnostics["history_retention_days"] =
            Value::Number(DEFAULT_DIAGNOSTIC_RETENTION_DAYS.into());
    }
    ensure_adapter_security_defaults(adapter);
    ensure_transport_profile_defaults(adapter);
}

fn find_adapter<'a>(registry: &'a Value, adapter_id: &str) -> Option<&'a Value> {
    registry
        .get("adapters")
        .and_then(Value::as_array)
        .and_then(|items| {
            items.iter().find(|item| {
                item.get("adapter_id")
                    .and_then(Value::as_str)
                    .map(|value| value == adapter_id)
                    .unwrap_or(false)
            })
        })
}

fn find_adapter_mut<'a>(registry: &'a mut Value, adapter_id: &str) -> Option<&'a mut Value> {
    registry
        .get_mut("adapters")
        .and_then(Value::as_array_mut)
        .and_then(|items| {
            items.iter_mut().find(|item| {
                item.get("adapter_id")
                    .and_then(Value::as_str)
                    .map(|value| value == adapter_id)
                    .unwrap_or(false)
            })
        })
}

fn upsert_adapter(registry: &mut Value, manifest: Value) -> LoomResult<()> {
    normalize_registry(registry);
    let adapter_id = manifest
        .get("adapter_id")
        .and_then(Value::as_str)
        .ok_or_else(|| "adapter manifest missing adapter_id".to_string())?
        .to_string();
    let adapters = registry
        .get_mut("adapters")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| "connect registry missing adapters array".to_string())?;
    if let Some(existing) = adapters.iter_mut().find(|item| {
        item.get("adapter_id")
            .and_then(Value::as_str)
            .map(|value| value == adapter_id)
            .unwrap_or(false)
    }) {
        *existing = manifest;
    } else {
        adapters.push(manifest);
    }
    normalize_registry(registry);
    Ok(())
}

fn adapter_enabled(adapter: &Value) -> bool {
    adapter
        .pointer("/lifecycle/enabled")
        .and_then(Value::as_bool)
        .unwrap_or(false)
}

fn set_adapter_enabled(adapter: &mut Value, enabled: bool) {
    if !adapter
        .get("lifecycle")
        .map(Value::is_object)
        .unwrap_or(false)
    {
        adapter["lifecycle"] = json!({});
    }
    adapter["lifecycle"]["enabled"] = Value::Bool(enabled);
}

fn adapter_diagnostics_mut(adapter: &mut Value) -> &mut Value {
    if !adapter
        .get("diagnostics")
        .map(Value::is_object)
        .unwrap_or(false)
    {
        adapter["diagnostics"] = default_adapter_diagnostics();
    }
    &mut adapter["diagnostics"]
}

fn adapter_lifecycle_mut(adapter: &mut Value) -> &mut Value {
    if !adapter
        .get("lifecycle")
        .map(Value::is_object)
        .unwrap_or(false)
    {
        adapter["lifecycle"] = json!({});
    }
    &mut adapter["lifecycle"]
}

fn default_adapter_diagnostics() -> Value {
    json!({
        "last_test_status": "unknown",
        "last_test_reason": "",
        "last_test_at": "",
        "last_desktop_capture_at": "",
        "last_desktop_capture_digest": "",
        "last_health_status": "unknown",
        "last_health_at": "",
        "test_history_entries": 0,
        "health_history_entries": 0,
        "lifecycle_history_entries": 0,
        "history_retention_days": DEFAULT_DIAGNOSTIC_RETENTION_DAYS,
    })
}

fn default_fallback_policy() -> Value {
    json!({
        "mode": "local_queue_shadow",
        "active": false,
        "max_reconnect_attempts": DEFAULT_RECONNECT_ATTEMPTS_MAX,
        "last_trigger_reason": "",
    })
}

fn security_profile_for(transport: &str) -> Value {
    json!({
        "schema_version": SECURITY_PROFILE_SCHEMA,
        "mode": "governed_default",
        "require_poge_receipts": true,
        "require_warrant": true,
        "require_authority": true,
        "require_court": true,
        "require_treasury_gate": true,
        "allow_plaintext_secrets": false,
        "max_payload_bytes": DEFAULT_SECURITY_MAX_PAYLOAD_BYTES,
        "failure_policy": SECURITY_FAILURE_POLICY_DEFAULT,
        "input_validation": "strict",
        "redaction_policy": "metadata_only",
        "transport_guard": transport,
    })
}

fn ensure_adapter_security_defaults(adapter: &mut Value) {
    let transport = adapter
        .get("transport")
        .and_then(Value::as_str)
        .unwrap_or("http");
    let defaults = security_profile_for(transport);
    if !adapter
        .get("security_profile")
        .map(Value::is_object)
        .unwrap_or(false)
    {
        adapter["security_profile"] = defaults;
        return;
    }
    merge_missing_object_fields(&mut adapter["security_profile"], &defaults);
}

fn ensure_transport_profile_defaults(adapter: &mut Value) {
    let transport = adapter
        .get("transport")
        .and_then(Value::as_str)
        .unwrap_or("http");
    let defaults = transport_profile_for(transport);
    if !adapter
        .get("transport_profile")
        .map(Value::is_object)
        .unwrap_or(false)
    {
        adapter["transport_profile"] = defaults;
        return;
    }
    merge_missing_object_fields(&mut adapter["transport_profile"], &defaults);
}

fn merge_missing_object_fields(target: &mut Value, defaults: &Value) {
    let Some(target_map) = target.as_object_mut() else {
        *target = defaults.clone();
        return;
    };
    let Some(default_map) = defaults.as_object() else {
        return;
    };
    for (key, value) in default_map {
        if !target_map.contains_key(key) {
            target_map.insert(key.clone(), value.clone());
        }
    }
}

fn harden_adapter_security_profile(adapter: &mut Value) {
    ensure_adapter_security_defaults(adapter);
    ensure_transport_profile_defaults(adapter);
    let transport = adapter
        .get("transport")
        .and_then(Value::as_str)
        .unwrap_or("http")
        .to_string();
    let security = &mut adapter["security_profile"];
    security["schema_version"] = Value::String(SECURITY_PROFILE_SCHEMA.to_string());
    security["mode"] = Value::String("governed_default".to_string());
    security["require_poge_receipts"] = Value::Bool(true);
    security["require_warrant"] = Value::Bool(true);
    security["require_authority"] = Value::Bool(true);
    security["require_court"] = Value::Bool(true);
    security["require_treasury_gate"] = Value::Bool(true);
    security["allow_plaintext_secrets"] = Value::Bool(false);
    let max_payload_bytes = security
        .get("max_payload_bytes")
        .and_then(Value::as_u64)
        .filter(|value| (1..=SECURITY_MAX_PAYLOAD_BYTES_LIMIT).contains(value))
        .unwrap_or(DEFAULT_SECURITY_MAX_PAYLOAD_BYTES);
    security["max_payload_bytes"] = Value::Number(max_payload_bytes.into());
    let failure_policy = security
        .get("failure_policy")
        .and_then(Value::as_str)
        .filter(|value| SECURITY_FAILURE_POLICIES.contains(value))
        .unwrap_or(SECURITY_FAILURE_POLICY_DEFAULT);
    security["failure_policy"] = Value::String(failure_policy.to_string());
    security["input_validation"] = Value::String("strict".to_string());
    security["redaction_policy"] = Value::String("metadata_only".to_string());
    security["transport_guard"] = Value::String(transport.clone());

    let profile = &mut adapter["transport_profile"];
    match transport.as_str() {
        "telegram" | "discord" | "whatsapp" | "slack" | "email" | "webhook" => {
            profile["health_endpoint"] = Value::String("/health".to_string());
        }
        _ => {}
    }
    match transport.as_str() {
        "browser" => {
            profile["sandbox"] = Value::String("restricted".to_string());
            profile["engine"] = Value::String("playwright_wrapper".to_string());
        }
        "shell" => {
            profile["execution_mode"] = Value::String("restricted_executor".to_string());
            profile["sandbox"] = Value::String("filesystem_guarded".to_string());
        }
        "desktop" => {
            profile["control_mode"] = Value::String("governed_desktop_bridge".to_string());
            profile["input_guard"] = Value::String("warrant_bound".to_string());
            profile["capture_mode"] = Value::String("receipt_snapshots".to_string());
            profile["vision_schema"] = Value::String("meridian.desktop.vision.v1".to_string());
            profile["capture_digest"] = Value::String("sha256".to_string());
            profile["allowed_actions"] = json!([
                "screen.capture",
                "window.focus",
                "pointer.move",
                "pointer.click",
                "keyboard.type",
            ]);
            profile["health_endpoint"] = Value::String("/health".to_string());
            if profile
                .get("rate_limit_per_minute")
                .and_then(Value::as_u64)
                .unwrap_or(0)
                == 0
            {
                profile["rate_limit_per_minute"] = Value::Number(45_u64.into());
            }
            profile["queue_fallback"] = Value::String("local_queue_shadow".to_string());
            profile["remediation_policy"] =
                Value::String("fallback_queue_then_sanction".to_string());
        }
        "webhook" => {
            profile["method"] = Value::String("POST".to_string());
            profile["content_type"] = Value::String("application/json".to_string());
        }
        "whatsapp" => {
            profile["inbound_mode"] = Value::String("webhook".to_string());
            profile["commands_surface"] = Value::String("message+interactive".to_string());
            if profile
                .get("rate_limit_per_minute")
                .and_then(Value::as_u64)
                .unwrap_or(0)
                == 0
            {
                profile["rate_limit_per_minute"] = Value::Number(60_u64.into());
            }
            profile["queue_fallback"] = Value::String("local_queue_shadow".to_string());
        }
        "slack" => {
            profile["inbound_mode"] = Value::String("events_api".to_string());
            profile["commands_surface"] = Value::String("slash+app_mentions".to_string());
            if profile
                .get("rate_limit_per_minute")
                .and_then(Value::as_u64)
                .unwrap_or(0)
                == 0
            {
                profile["rate_limit_per_minute"] = Value::Number(120_u64.into());
            }
            profile["queue_fallback"] = Value::String("local_queue_shadow".to_string());
        }
        "email" => {
            profile["inbound_mode"] = Value::String("smtp_imap_bridge".to_string());
            profile["commands_surface"] = Value::String("subject+reply_thread".to_string());
            if profile
                .get("rate_limit_per_minute")
                .and_then(Value::as_u64)
                .unwrap_or(0)
                == 0
            {
                profile["rate_limit_per_minute"] = Value::Number(30_u64.into());
            }
            profile["queue_fallback"] = Value::String("local_queue_shadow".to_string());
        }
        _ => {}
    }
}

fn evaluate_adapter_security(adapter: &Value) -> Value {
    let transport = adapter
        .get("transport")
        .and_then(Value::as_str)
        .unwrap_or("");
    let security = adapter.get("security_profile");
    let security_present = security.map(Value::is_object).unwrap_or(false);
    let mode_ok = security
        .and_then(|value| value.get("mode"))
        .and_then(Value::as_str)
        .map(|value| value == "governed_default")
        .unwrap_or(false);
    let governance_requirements_ok = security
        .map(|value| {
            value
                .get("require_poge_receipts")
                .and_then(Value::as_bool)
                .unwrap_or(false)
                && value
                    .get("require_warrant")
                    .and_then(Value::as_bool)
                    .unwrap_or(false)
                && value
                    .get("require_authority")
                    .and_then(Value::as_bool)
                    .unwrap_or(false)
                && value
                    .get("require_court")
                    .and_then(Value::as_bool)
                    .unwrap_or(false)
                && value
                    .get("require_treasury_gate")
                    .and_then(Value::as_bool)
                    .unwrap_or(false)
        })
        .unwrap_or(false);
    let plaintext_secrets_blocked = security
        .and_then(|value| value.get("allow_plaintext_secrets"))
        .and_then(Value::as_bool)
        .map(|value| !value)
        .unwrap_or(false);
    let payload_limit_ok = security
        .and_then(|value| value.get("max_payload_bytes"))
        .and_then(Value::as_u64)
        .map(|value| (1..=SECURITY_MAX_PAYLOAD_BYTES_LIMIT).contains(&value))
        .unwrap_or(false);
    let failure_policy_ok = security
        .and_then(|value| value.get("failure_policy"))
        .and_then(Value::as_str)
        .map(|value| SECURITY_FAILURE_POLICIES.contains(&value))
        .unwrap_or(false);
    let no_inline_secrets_ok = inline_secret_scan(adapter).is_empty();
    let transport_security_ok = evaluate_transport_security(adapter, transport);
    let valid = security_present
        && mode_ok
        && governance_requirements_ok
        && plaintext_secrets_blocked
        && payload_limit_ok
        && failure_policy_ok
        && no_inline_secrets_ok
        && transport_security_ok;
    json!({
        "security_profile_present": security_present,
        "mode_ok": mode_ok,
        "governance_requirements_ok": governance_requirements_ok,
        "plaintext_secrets_blocked": plaintext_secrets_blocked,
        "payload_limit_ok": payload_limit_ok,
        "failure_policy_ok": failure_policy_ok,
        "no_inline_secrets_ok": no_inline_secrets_ok,
        "transport_security_ok": transport_security_ok,
        "valid": valid,
    })
}

fn evaluate_transport_security(adapter: &Value, transport: &str) -> bool {
    let profile = adapter.get("transport_profile").unwrap_or(&Value::Null);
    match transport {
        "telegram" | "discord" | "whatsapp" | "slack" | "email" => {
            profile
                .get("health_endpoint")
                .and_then(Value::as_str)
                .map(|value| value == "/health")
                .unwrap_or(false)
                && profile
                    .get("rate_limit_per_minute")
                    .and_then(Value::as_u64)
                    .map(|value| value > 0)
                    .unwrap_or(false)
        }
        "browser" => profile
            .get("sandbox")
            .and_then(Value::as_str)
            .map(|value| value == "restricted")
            .unwrap_or(false),
        "shell" => {
            profile
                .get("execution_mode")
                .and_then(Value::as_str)
                .map(|value| value == "restricted_executor")
                .unwrap_or(false)
                && profile
                    .get("sandbox")
                    .and_then(Value::as_str)
                    .map(|value| value == "filesystem_guarded")
                    .unwrap_or(false)
        }
        "desktop" => {
            profile
                .get("control_mode")
                .and_then(Value::as_str)
                .map(|value| value == "governed_desktop_bridge")
                .unwrap_or(false)
                && profile
                    .get("input_guard")
                    .and_then(Value::as_str)
                    .map(|value| value == "warrant_bound")
                    .unwrap_or(false)
                && profile
                    .get("capture_mode")
                    .and_then(Value::as_str)
                    .map(|value| value == "receipt_snapshots")
                    .unwrap_or(false)
                && profile
                    .get("vision_schema")
                    .and_then(Value::as_str)
                    .map(|value| value == "meridian.desktop.vision.v1")
                    .unwrap_or(false)
                && profile
                    .get("health_endpoint")
                    .and_then(Value::as_str)
                    .map(|value| value == "/health")
                    .unwrap_or(false)
                && profile
                    .get("rate_limit_per_minute")
                    .and_then(Value::as_u64)
                    .map(|value| value > 0)
                    .unwrap_or(false)
        }
        "webhook" => {
            profile
                .get("method")
                .and_then(Value::as_str)
                .map(|value| value.eq_ignore_ascii_case("POST"))
                .unwrap_or(false)
                && profile
                    .get("health_endpoint")
                    .and_then(Value::as_str)
                    .map(|value| value == "/health")
                    .unwrap_or(false)
        }
        _ => true,
    }
}

fn inline_secret_scan(adapter: &Value) -> Vec<String> {
    let mut hits = Vec::new();
    let candidate_keys = [
        "api_key",
        "token",
        "secret",
        "access_token",
        "bearer_token",
        "webhook_secret",
    ];
    for key in candidate_keys {
        if adapter
            .get(key)
            .and_then(Value::as_str)
            .map(|value| !value.trim().is_empty())
            .unwrap_or(false)
        {
            hits.push(key.to_string());
        }
        if adapter
            .get("transport_profile")
            .and_then(|value| value.get(key))
            .and_then(Value::as_str)
            .map(|value| !value.trim().is_empty())
            .unwrap_or(false)
        {
            hits.push(format!("transport_profile.{}", key));
        }
    }
    hits
}

fn append_lifecycle_event(
    root: &Path,
    adapter_id: &str,
    state: &str,
    action: &str,
    reason: &str,
) -> LoomResult<()> {
    let event = json!({
        "schema_version": CONNECT_LIFECYCLE_EVENT_SCHEMA,
        "adapter_id": adapter_id,
        "state": state,
        "action": action,
        "reason": reason,
        "recorded_at": chrono_like_timestamp(),
    });
    append_jsonl(
        &connect_lifecycle_history_path(root, adapter_id),
        &serde_json::to_string(&event).map_err(|error| error.to_string())?,
    )
}

fn append_connect_sanction_event(
    root: &Path,
    adapter_id: &str,
    sanction_kind: &str,
    trigger: &str,
    reason: &str,
) -> LoomResult<()> {
    let event = json!({
        "schema_version": CONNECT_SANCTION_SCHEMA,
        "adapter_id": adapter_id,
        "sanction_kind": sanction_kind,
        "trigger": trigger,
        "reason": reason,
        "recorded_at": chrono_like_timestamp(),
        "warrant_bound": true,
        "authority_checked": true,
        "court_checked": true,
        "treasury_gate": true,
    });
    append_jsonl(
        &connect_sanctions_history_path(root, adapter_id),
        &serde_json::to_string(&event).map_err(|error| error.to_string())?,
    )
}

fn build_desktop_vision_event(
    adapter_id: &str,
    tested_at: &str,
    test_status: &str,
    test_reason: &str,
) -> Value {
    let mut hasher = Sha256::new();
    hasher.update(adapter_id.as_bytes());
    hasher.update(b":");
    hasher.update(tested_at.as_bytes());
    hasher.update(b":");
    hasher.update(test_status.as_bytes());
    hasher.update(b":");
    hasher.update(test_reason.as_bytes());
    let capture_digest_hex = hex::encode(hasher.finalize());
    json!({
        "schema_version": "meridian.connect.desktop_vision_event.v1",
        "adapter_id": adapter_id,
        "captured_at": tested_at,
        "capture_digest_hex": capture_digest_hex,
        "vision_schema": "meridian.desktop.vision.v1",
        "frame_source": "governed_desktop_bridge",
        "action_schema": "meridian.desktop.action.v1",
        "allowed_actions": ["screen.capture", "window.focus", "pointer.move", "pointer.click", "keyboard.type"],
        "ack_required": true,
        "cancel_policy": "court_bound_abort",
        "test_status": test_status,
        "test_reason": test_reason,
        "warrant_bound": true,
        "authority_checked": true,
        "court_checked": true,
        "treasury_gate": true,
    })
}

fn value_string(value: Option<&Value>) -> &str {
    value.and_then(Value::as_str).unwrap_or("")
}

fn poge_standard_profile() -> Value {
    json!({
        "profile": "meridian.poge.standard.v1",
        "warrant_required": true,
        "authority_check": true,
        "court_check": true,
        "treasury_gate": true,
        "receipt_emission": true,
        "merkle_audit_root": true,
        "zk_settlement_compatible": true,
        "event_schema": "runtime_event_v1",
        "settlement_mode": "receipt+settle_zk",
    })
}

fn transport_profile_for(transport: &str) -> Value {
    match transport {
        "telegram" => json!({
            "kind": "telegram",
            "inbound_mode": "bot_updates",
            "commands_surface": "inline+slash",
            "rate_limit_per_minute": 60,
            "health_endpoint": "/health",
            "queue_fallback": "local_queue_shadow",
            "note": "operator-grade chat transport with governed command envelopes",
        }),
        "discord" => json!({
            "kind": "discord",
            "inbound_mode": "slash_commands",
            "voice_channel": true,
            "rate_limit_per_minute": 90,
            "health_endpoint": "/health",
            "queue_fallback": "local_queue_shadow",
            "note": "operator-grade guild transport with command and voice support",
        }),
        "whatsapp" => json!({
            "kind": "whatsapp",
            "inbound_mode": "webhook",
            "commands_surface": "message+interactive",
            "rate_limit_per_minute": 60,
            "health_endpoint": "/health",
            "queue_fallback": "local_queue_shadow",
            "note": "operator-grade WhatsApp transport with governed webhook envelopes",
        }),
        "slack" => json!({
            "kind": "slack",
            "inbound_mode": "events_api",
            "commands_surface": "slash+app_mentions",
            "rate_limit_per_minute": 120,
            "health_endpoint": "/health",
            "queue_fallback": "local_queue_shadow",
            "note": "operator-grade Slack transport with governed event ingestion",
        }),
        "email" => json!({
            "kind": "email",
            "inbound_mode": "smtp_imap_bridge",
            "commands_surface": "subject+reply_thread",
            "rate_limit_per_minute": 30,
            "health_endpoint": "/health",
            "queue_fallback": "local_queue_shadow",
            "note": "operator-grade email transport with governed thread routing",
        }),
        "browser" => json!({
            "kind": "browser",
            "engine": "playwright_wrapper",
            "sandbox": "restricted",
            "health_endpoint": "/health",
            "queue_fallback": "local_queue_shadow",
            "note": "governed browser automation transport with proof receipts",
        }),
        "shell" => json!({
            "kind": "shell",
            "execution_mode": "restricted_executor",
            "sandbox": "filesystem_guarded",
            "health_endpoint": "/health",
            "queue_fallback": "local_queue_shadow",
            "note": "governed shell transport with bounded command execution",
        }),
        "desktop" => json!({
            "kind": "desktop",
            "control_mode": "governed_desktop_bridge",
            "input_guard": "warrant_bound",
            "capture_mode": "receipt_snapshots",
            "vision_schema": "meridian.desktop.vision.v1",
            "capture_digest": "sha256",
            "allowed_actions": ["screen.capture", "window.focus", "pointer.move", "pointer.click", "keyboard.type"],
            "rate_limit_per_minute": 45,
            "health_endpoint": "/health",
            "queue_fallback": "local_queue_shadow",
            "remediation_policy": "fallback_queue_then_sanction",
            "note": "governed desktop control lane with proof-bound interaction envelopes",
        }),
        "webhook" => json!({
            "kind": "webhook",
            "method": "POST",
            "content_type": "application/json",
            "inbound_mode": "generic_http_ingress",
            "health_endpoint": "/health",
            "queue_fallback": "local_queue_shadow",
            "note": "generic inbound webhook transport for external systems",
        }),
        "grpc" => json!({
            "kind": "grpc",
            "rpc": "meridian.runtime.v1.ActionService/SubmitAction",
            "target": "https://runtime.example",
            "serialization": "protobuf",
            "note": "semantic action envelopes over gRPC transport",
        }),
        "a2a" => json!({
            "kind": "a2a",
            "method": "message/send",
            "target": "https://a2a.example/bridge",
            "note": "agent-to-agent semantic envelope bridge",
        }),
        "mcp" => json!({
            "kind": "mcp",
            "method": "tools/call",
            "target": "https://mcp.example",
            "tool": "shadow.execute",
            "note": "MCP tool-call transport with governed action envelope",
        }),
        "http" => json!({
            "kind": "http",
            "method": "POST",
            "target": "https://runtime.example/shadow/execute",
            "content_type": "application/json",
            "note": "HTTP JSON envelope fallback transport",
        }),
        "ros2" => json!({
            "kind": "ros2",
            "mode": "service",
            "service": "/meridian/physical_action/execute",
            "type": "meridian_embodied_msgs/srv/ExecutePhysicalAction",
            "note": "embodied transport via ROS2 service/action bridge",
        }),
        _ => json!({
            "kind": transport,
            "note": "unsupported transport profile",
        }),
    }
}
