use loom_core::{
    build_action_envelope, build_action_envelope_with_options,
    capabilities::{
        capability_gap_replay_request, find_capability_by_name, forge_capability,
        import_legacy_v1_plugin_skill_subset, import_workspace_skill, load_capability_gap,
        load_capability_registry, promote_capability, record_capability_gap,
        render_capability_forge_human, render_capability_forge_json, render_capability_gap_human,
        render_capability_gap_json, render_capability_human, render_capability_import_human,
        render_capability_import_json, render_capability_json, render_capability_registry_human,
        render_capability_registry_json, render_capability_state_update_human,
        render_capability_state_update_json, render_legacy_v1_plugin_import_human,
        render_legacy_v1_plugin_import_json, scaffold_capability,
        timestamp_now as capability_timestamp_now, update_capability_gap_forge,
        update_capability_gap_promotion, update_capability_gap_verification,
        update_capability_verification, CapabilityForgeRequest, CapabilityGapRequest,
        CapabilityScaffoldRequest,
    },
    capability_shims::{
        generate_shim, render_shim_human, render_shim_json, validate_shim, LegacyToolSpec,
    },
    capsule_inspect, contract_show, contract_verify, doctor, evaluate_reference_gates, health,
    init_workspace, kernel_path_for, read_config, render_capsule_human, render_config_human,
    render_contract_human, render_contract_json, render_contract_verify_human,
    render_contract_verify_json, render_doctor_human, render_doctor_json, render_envelope_human,
    render_envelope_json, render_health_human, render_identity_human, render_identity_json,
    resolve_agent_identity, root_from, status_human,
    wasm_host::{
        render_host_config_human, render_host_config_json, run_wasm_guest, HostBackend,
        WasmExecutionRequest, WasmGuestSource, WasmHostBuilder,
    },
    wasm_limits::{
        default_limits, from_toml as parse_wasm_limits_toml, render_limits_human,
        render_limits_json, validate_limits,
    },
    wasm_profiles::{
        profile_defaults_map, render_pooling_config_human, render_pooling_config_json,
        PoolingProfile,
    },
    Config, LoomResult,
};
use loom_shadow::{
    ack_queue_job, approve_job, capture_decision, capture_preflight, capture_runtime_execution,
    compare_logs, consume_pending_queue, decision_exit_code, enqueue_action,
    import_commitment_execution_requests, inspect_job, inspect_pending_queue, list_jobs,
    queue_status, render_compare_human, render_compare_json, render_decision_human,
    render_decision_json, render_enqueued_action_human, render_enqueued_action_json,
    render_job_inspect_human, render_job_inspect_json, render_job_list_human, render_job_list_json,
    render_parity_report, render_preflight_human, render_preflight_json, render_queue_ack_human,
    render_queue_ack_json, render_queue_consume_human, render_queue_consume_json,
    render_queue_inspect_human, render_queue_inspect_json, render_queue_run_once_human,
    render_queue_run_once_json, render_queue_run_until_empty_human,
    render_queue_run_until_empty_json, render_queue_status_human, render_queue_status_json,
    render_runtime_execution_human, render_runtime_execution_json,
    render_runtime_service_cancel_human, render_runtime_service_cancel_json,
    render_runtime_service_human, render_runtime_service_import_human,
    render_runtime_service_import_json, render_runtime_service_json,
    render_runtime_service_submit_human, render_runtime_service_submit_json, render_shadow_report,
    render_supervisor_daemon_human, render_supervisor_daemon_json, render_supervisor_lanes_human,
    render_supervisor_lanes_json, render_supervisor_run_human, render_supervisor_run_json,
    render_supervisor_status_human, render_supervisor_status_json, render_supervisor_watch_human,
    render_supervisor_watch_json, request_runtime_service_cancel, request_runtime_service_stop,
    request_supervisor_daemon_stop, run_queue_once, run_queue_until_empty,
    run_runtime_service_loop, run_supervisor, run_supervisor_daemon_loop, runtime_service_status,
    submit_runtime_service_action, supervisor_daemon_status, supervisor_status, watch_supervisor,
};
use serde_json::Value;
use std::env;
use std::io::{self, IsTerminal};
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode, Stdio};

mod commands;

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("loom: {}", error);
            ExitCode::FAILURE
        }
    }
}

fn run() -> LoomResult<()> {
    let args = env::args().skip(1).collect::<Vec<_>>();
    if args.is_empty() {
        print_help();
        return Ok(());
    }

    match args[0].as_str() {
        "banner" => {
            print_startup_banner();
            Ok(())
        }
        "onboard" => commands::onboard::handle_onboard(&args[1..]),
        "quickstart" => commands::quickstart::handle_quickstart(&args[1..]),
        "version" | "-V" | "--version" => {
            print_startup_banner();
            print_human(&format!(
                "Meridian Loom // VERSION\n=========================\nversion:     {}\nboundary:    local-first runtime surface; hosted replacement not claimed\n",
                env!("CARGO_PKG_VERSION")
            ));
            Ok(())
        }
        "init" => commands::runtime::handle_init(&args[1..]),
        "doctor" => commands::runtime::handle_doctor(&args[1..]),
        "health" => commands::runtime::handle_health(&args[1..]),
        "status" => commands::runtime::handle_status(&args[1..]),
        "start" => commands::service::handle_start(&args[1..]),
        "stop" => commands::service::handle_stop(&args[1..]),
        "restart" => commands::service::handle_restart(&args[1..]),
        "logs" => commands::service::handle_logs(&args[1..]),
        "config" => commands::runtime::handle_config(&args[1..]),
        "provider" => commands::provider::handle_provider(&args[1..]),
        "context" => commands::context::handle_context(&args[1..]),
        "memory" => commands::memory::handle_memory(&args[1..]),
        "init-nation" => commands::nation::handle_nation(&args[1..]),
        "new-agent" => commands::personal_agent::handle_new_agent(&args[1..]),
        "run-agent" => commands::personal_agent::handle_run_agent(&args[1..]),
        "gateway" => commands::gateway::handle_gateway(&args[1..]),
        "auth" => commands::auth::handle_auth(&args[1..]),
        "binding" => commands::binding::handle_binding(&args[1..]),
        "breed" => commands::breed::handle_breed(&args[1..]),
        "channel" => commands::channel::handle_channel(&args[1..]),
        "connect" => commands::connect::handle_connect(&args[1..]),
        "deploy" => commands::deploy::handle_deploy(&args[1..]),
        "extension" => commands::extension::handle_extension(&args[1..]),
        "observe" => commands::observe::handle_observe(&args[1..]),
        "skill" => commands::skill::handle_skill(&args[1..]),
        "schedule" => commands::schedule::handle_schedule(&args[1..]),
        "heartbeat" => commands::heartbeat::handle_heartbeat(&args[1..]),
        "ingress" => commands::ingress::handle_ingress(&args[1..]),
        "contract" => commands::runtime::handle_contract(&args[1..]),
        "capsule" => commands::runtime::handle_capsule(&args[1..]),
        "capability" => commands::capability::handle_capability(&args[1..]),
        "job" => commands::job::handle_job(&args[1..]),
        "swarm" => commands::swarm::handle_swarm(&args[1..]),
        "output" => commands::output::handle_output(&args[1..]),
        "queue" => commands::queue::handle_queue(&args[1..]),
        "agent" => commands::runtime::handle_agent(&args[1..]),
        "envelope" => commands::runtime::handle_envelope(&args[1..]),
        "action" => commands::action::handle_action(&args[1..]),
        "supervisor" => commands::supervisor::handle_supervisor(&args[1..]),
        "service" => commands::service::handle_service(&args[1..]),
        "runtime-info" => commands::runtime::handle_runtime_info(&args[1..]),
        "shadow" => commands::runtime::handle_shadow(&args[1..]),
        "parity" => commands::runtime::handle_parity(&args[1..]),
        "wasm" => commands::wasm::handle_wasm(&args[1..]),
        "session" => commands::session::handle_session(&args[1..]),
        "recurring" => commands::recurring::handle_recurring(&args[1..]),
        "-h" | "--help" | "help" => {
            print_help();
            Ok(())
        }
        other => Err(format!(
            "unknown command '{}'; run `loom --help` to see available commands",
            other
        )),
    }
}

fn take_value(args: &[String], flag: &str) -> Option<String> {
    args.windows(2)
        .find(|pair| pair[0] == flag)
        .map(|pair| pair[1].clone())
}

fn take_values(args: &[String], flag: &str) -> Vec<String> {
    args.windows(2)
        .filter(|pair| pair[0] == flag)
        .map(|pair| pair[1].clone())
        .collect()
}

fn has_flag(args: &[String], flag: &str) -> bool {
    args.iter().any(|value| value == flag)
}

fn required_flag(args: &[String], flag: &str) -> LoomResult<String> {
    take_value(args, flag).ok_or_else(|| {
        format!(
            "missing required flag {}; run the command with --help for usage",
            flag
        )
    })
}

fn parse_f64_flag(args: &[String], flag: &str) -> Option<f64> {
    take_value(args, flag).and_then(|raw| raw.parse::<f64>().ok())
}

fn chrono_like_timestamp() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};

    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
        .to_string()
}

fn sanitize_token(input: &str) -> String {
    input
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() {
                ch.to_ascii_lowercase()
            } else {
                '-'
            }
        })
        .collect::<String>()
        .trim_matches('-')
        .to_string()
}

fn print_last_lines(path: &PathBuf, lines: usize) -> LoomResult<u64> {
    let contents = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let collected = contents.lines().collect::<Vec<_>>();
    let start = collected.len().saturating_sub(lines);
    for line in &collected[start..] {
        println!("{}", line);
    }
    Ok(contents.len() as u64)
}

fn print_new_bytes(path: &PathBuf, offset: u64) -> LoomResult<u64> {
    let contents = std::fs::read(path).map_err(|e| e.to_string())?;
    let start = offset.min(contents.len() as u64) as usize;
    if start < contents.len() {
        let new_bytes = &contents[start..];
        print!("{}", String::from_utf8_lossy(new_bytes));
    }
    Ok(contents.len() as u64)
}

fn rotate_log_file_if_needed(path: &PathBuf, max_bytes: usize, max_files: usize) -> LoomResult<()> {
    if max_bytes == 0 || max_files == 0 || !path.exists() {
        return Ok(());
    }
    let size = std::fs::metadata(path).map_err(|e| e.to_string())?.len() as usize;
    if size < max_bytes {
        return Ok(());
    }
    let base_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| format!("cannot rotate log path {}", path.display()))?
        .to_string();
    let parent = path
        .parent()
        .ok_or_else(|| format!("cannot rotate log path {}", path.display()))?;
    if max_files > 1 {
        for index in (1..max_files).rev() {
            let source = parent.join(format!("{}.{}", base_name, index));
            let target = parent.join(format!("{}.{}", base_name, index + 1));
            if source.exists() {
                if target.exists() {
                    let _ = std::fs::remove_file(&target);
                }
                std::fs::rename(&source, &target).map_err(|e| e.to_string())?;
            }
        }
        let first = parent.join(format!("{}.1", base_name));
        if first.exists() {
            let _ = std::fs::remove_file(&first);
        }
        std::fs::rename(path, &first).map_err(|e| e.to_string())?;
        set_private_permissions_if_supported(&first, 0o600)?;
    } else {
        std::fs::write(path, "").map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn json_string(input: &str) -> String {
    format!("{:?}", input)
}

#[cfg(unix)]
fn set_private_permissions_if_supported(path: &std::path::Path, mode: u32) -> LoomResult<()> {
    use std::os::unix::fs::PermissionsExt;

    let mut permissions = std::fs::metadata(path)
        .map_err(|e| e.to_string())?
        .permissions();
    permissions.set_mode(mode);
    match std::fs::set_permissions(path, permissions) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => Ok(()),
        Err(error) => Err(error.to_string()),
    }
}

#[cfg(not(unix))]
fn set_private_permissions_if_supported(_path: &std::path::Path, _mode: u32) -> LoomResult<()> {
    Ok(())
}

fn print_help() {
    print_startup_banner();
    print_human(
        "Meridian Loom // HELP\n\
======================\n\
phase:       production-oriented local runtime surface\n\
boundary:    local-first service is real; hosted replacement is not\n\
\n\
Bootstrap\n\
---------\n\
  loom banner\n\
  loom version\n\
  loom quickstart [--root PATH] [--kernel-path PATH] [--org-id ORG] [--charter TEXT] [--agent-name NAME] [--webhook-url URL] [--channel-test-text TEXT] [--interactive] [--non-interactive] [--format human|json]\n\
  loom onboard [--root PATH] [--mode MODE] [--org-id ID] [--kernel-path PATH] [--config-action setup|keep|modify|reset] [--manager-lane frontier|local] [--manager-model NAME] [--codex-auth-source loom|cli|path] [--codex-auth-path PATH] [--gateway-port N] [--gateway-bind loopback|all] [--gateway-auth-mode token|none] [--gateway-token-env ENV] [--telegram-enabled yes|no] [--telegram-token-env ENV] [--telegram-dm-policy TEXT] [--telegram-group-policy TEXT] [--telegram-streaming TEXT] [--daemon-enabled yes|no] [--daemon-manager supervisor] [--recurring-install-defaults yes|no] [--recurring-entry ID]... [--start-daemon] [--skip-health-check] [--format human|json]\n\
  loom init --mode <embedded|shadow|standalone> [--kernel-path PATH] [--root PATH] [--org-id ID]\n\
  loom doctor [--root PATH] [--format json|human]\n\
  loom health [--root PATH] [--format json|human]\n\
  loom status [--root PATH]\n\
  loom start [--root PATH] [--kernel-path PATH] [--http-address HOST:PORT] [--service-token TOKEN] [--foreground]\n\
  loom stop [--root PATH]\n\
  loom restart [--root PATH] [--kernel-path PATH] [--http-address HOST:PORT] [--service-token TOKEN] [--foreground]\n\
  loom logs [--root PATH] [--lines N] [--follow]\n\
  loom config show [--root PATH]\n\
  loom init-nation --charter TEXT [--org-id ORG] [--name NAME] [--root PATH] [--kernel-path PATH] [--format human|json]\n\
  loom new-agent --name NAME [--root PATH] [--kernel-path PATH] [--org-id ORG] [--telegram-chat-id ID] [--webhook-url URL] [--format human|json]\n\
  loom run-agent NAME [--foreground] [--poll-seconds N] [--once]\n\
  loom run-agent status NAME [--format human|json]\n\
  loom run-agent inspect NAME [--receipt-limit N] [--delivery-limit N] [--format human|json]\n\
  loom run-agent stop NAME [--format human|json]\n\
  loom run-agent reconcile NAME [--poll-seconds N] [--format human|json]\n\
  loom provider status [--root PATH] [--format human|json]\n\
  loom provider route [--root PATH] [--capability NAME] [--model NAME] [--agent-id ID] [--org-id ORG] [--profile NAME] [--format human|json]\n\
  loom provider auth [--root PATH] [--profile NAME] [--format human|json]\n\
  loom provider login [--root PATH] [--source loom|cli|path] [--auth-path PATH] [--device-auth|--with-api-key] [--format human|json]\n\
  loom provider profiles [--root PATH] [--profile NAME] [--format human|json]\n\
  loom provider mark-used --profile NAME [--root PATH] [--format human|json]\n\
  loom provider mark-failure --profile NAME [--reason TEXT] [--cooldown-ms N] [--root PATH] [--format human|json]\n\
  loom auth status [--root PATH] [--format human|json]\n\
  loom auth rotate --alias NAME --env-var NAME [--agent-id ID] [--org-id ORG] [--kernel-path PATH] [--root PATH] [--format human|json]\n\
  loom auth revoke --alias NAME [--agent-id ID] [--org-id ORG] [--kernel-path PATH] [--root PATH] [--format human|json]\n\
  loom auth audit [--root PATH] [--limit N] [--format human|json]\n\
  loom gateway status [--root PATH] [--format human|json]\n\
  loom gateway sync [--root PATH] [--format human|json]\n\
  loom binding status [--root PATH] [--format human|json]\n\
  loom binding sync [--root PATH] [--format human|json]\n\
  loom binding list [--root PATH] [--format human|json]\n\
  loom binding show --binding-id ID [--root PATH] [--format human|json]\n\
  loom binding resolve --channel ID --peer ID [--thread ID] [--agent-id ID] [--root PATH] [--format human|json]\n\
  loom breed <parent1> <parent2> --agent-id ID --kernel-path PATH [--org-id ORG] [--mutation-rate F] [--root PATH] [--format human|json]\n\
  loom channel status [--root PATH] [--format human|json]\n\
  loom channel sync [--root PATH] [--format human|json]\n\
  loom channel list [--root PATH] [--agent NAME] [--format human|json]\n\
  loom channel health [--root PATH] [--agent NAME] [--format human|json]\n\
  loom channel show --agent NAME [--format human|json]\n\
  loom channel connect telegram --agent NAME --chat-id ID [--token-env ENV]\n\
  loom channel connect webhook --agent NAME --url URL [--header TEXT]\n\
  loom channel disconnect telegram --agent NAME\n\
  loom channel disconnect webhook --agent NAME\n\
  loom channel test --agent NAME [--text TEXT] [--format human|json]\n\
  loom connect scaffold --name NAME --transport telegram|discord|whatsapp|slack|email|browser|shell|webhook|grpc|a2a|mcp|http|ros2 --action-schema SCHEMA [--root PATH] [--format human|json]\n\
  loom connect list [--root PATH] [--format human|json]\n\
  loom connect validate [--adapter-id ID] [--root PATH] [--format human|json]\n\
  loom connect enable --adapter-id ID [--root PATH] [--format human|json]\n\
  loom connect disable --adapter-id ID [--root PATH] [--format human|json]\n\
  loom connect test --adapter-id ID [--root PATH] [--format human|json]\n\
  loom connect health --adapter-id ID [--root PATH] [--format human|json]\n\
  loom connect diagnostics --adapter-id ID [--limit N] [--root PATH] [--format human|json]\n\
  loom connect metrics --adapter-id ID [--retention-days DAYS] [--root PATH] [--format human|json]\n\
  loom connect scorecard [--retention-days DAYS] [--fix] [--root PATH] [--format human|json]\n\
  loom connect prune --adapter-id ID [--retention-days DAYS] [--root PATH] [--format human|json]\n\
  loom extension validate --manifest PATH [--root PATH] [--format human|json]\n\
  loom extension install --manifest PATH [--root PATH] [--format human|json]\n\
  loom extension remove --extension-id ID [--root PATH] [--format human|json]\n\
  loom extension export --extension-id ID --out PATH [--root PATH] [--format human|json]\n\
  loom observe summary [--root PATH] [--fix-hints] [--format human|json]\n\
  loom observe alerts [--root PATH] [--fix-hints] [--format human|json]\n\
  loom observe watch [--root PATH] [--iterations N] [--interval-seconds N] [--follow] [--stream] [--fix-hints] [--format human|json]\n\
  loom channel send --channel ID --recipient ID [--text TEXT|--file PATH] [--allow-receipt-hashes] [--allow-operator-diagnostics] [--root PATH] [--format human|json]\n\
  loom channel deliveries [--root PATH] [--limit N] [--include-archived|--archived-only] [--format human|json]\n\
  loom ingress status [--root PATH] [--format human|json]\n\
  loom ingress list [--root PATH] [--limit N] [--format human|json]\n\
  loom ingress show --request-id ID [--root PATH] [--format human|json]\n\
  loom context status [--root PATH] [--format human|json]\n\
  loom context sync [--root PATH] [--format human|json]\n\
  loom context bundle --agent-id ID [--session-id ID] [--root PATH] [--format human|json]\n\
  loom context overlay --agent-id ID --session-id ID --section soul|user|tools|heartbeat|agents|memory [--text TEXT|--file PATH] [--root PATH] [--format human|json]\n\
  loom memory status [--root PATH] [--format human|json]\n\
  loom memory search --agent-id ID [--category NAME] [--key-prefix PREFIX] [--root PATH] [--format human|json]\n\
  loom memory receipts [--agent-id ID] [--limit N] [--root PATH] [--format human|json]\n\
  loom memory graph inspect <source-ref> [--node-id ID] [--direction ancestors|descendants|both] [--limit N] [--root PATH] [--format human|json]\n\
  loom memory fork <source-ref> --target-agent-id ID [--branch NAME] [--node-id ID] [--direction ancestors|descendants|both] [--limit N] [--root PATH] [--format human|json]\n\
  loom memory replay <source-ref> --target-agent-id ID --kernel-path PATH [--org-id ORG] [--node-id ID] [--direction ancestors|descendants|both] [--limit N] [--root PATH] [--format human|json]\n\
  loom memory write --agent-id ID --category NAME --key KEY --content TEXT [--source NAME] [--root PATH] [--format human|json]\n\
  loom memory remove --agent-id ID --category NAME --key KEY [--root PATH] [--format human|json]\n\
  loom memory prune [--root PATH] [--format human|json]\n\
  loom skill status [--root PATH] [--format human|json]\n\
  loom skill sync [--root PATH] [--format human|json]\n\
  loom skill list [--root PATH] [--format human|json]\n\
  loom skill show --skill-id ID [--root PATH] [--format human|json]\n\
  loom schedule status [--root PATH] [--now-unix-ms MS] [--format human|json]\n\
  loom schedule list [--root PATH] [--format human|json]\n\
  loom schedule show --job-id ID [--root PATH] [--format human|json]\n\
  loom schedule add --agent-id ID --job-kind KIND [--job-id ID] [--schedule daily|interval|once] [--expression HH:MM] [--every-seconds N] [--not-before-unix-ms MS] [--payload-json JSON] [--delivery-channel ID] [--delivery-recipient ID] [--delivery-allow-receipt-hashes] [--delivery-allow-operator-diagnostics] [--max-attempts N] [--source-kind default|manual] [--root PATH] [--format human|json]\n\
  loom schedule pause --job-id ID [--root PATH] [--format human|json]\n\
  loom schedule cancel --job-id ID [--root PATH] [--format human|json]\n\
  loom schedule run-due [--root PATH] [--now-unix-ms MS] [--limit N] [--format human|json]\n\
  loom heartbeat status [--root PATH] [--now-unix-ms MS] [--format human|json]\n\
  loom heartbeat list [--root PATH] [--format human|json]\n\
  loom heartbeat show --heartbeat-id ID [--root PATH] [--format human|json]\n\
  loom heartbeat schedule --agent-id ID --capability NAME [--heartbeat-id ID] [--schedule interval|once|cron] [--every-seconds N] [--jitter-seconds N] [--not-before-unix-ms MS] [--expression EXPR] [--timezone TZ] [--payload-json JSON] [--delivery-channel ID] [--delivery-recipient ID] [--delivery-allow-receipt-hashes] [--delivery-allow-operator-diagnostics] [--max-attempts N] [--root PATH] [--format human|json]\n\
  loom heartbeat pause --heartbeat-id ID [--root PATH] [--format human|json]\n\
  loom heartbeat cancel --heartbeat-id ID [--root PATH] [--format human|json]\n\
  loom heartbeat run-due [--root PATH] [--now-unix-ms MS] [--limit N] [--format human|json]\n\
  loom output inspect [--text TEXT|--file PATH] [--allow-receipt-hashes] [--allow-operator-diagnostics] [--format human|json]\n\
\n\
Governance surfaces\n\
-------------------\n\
  loom contract show [--root PATH] [--kernel-path PATH] [--format human|json]\n\
  loom contract verify [--root PATH] [--kernel-path PATH] [--agent-id ID] [--org-id ORG] [--format human|json]\n\
  loom capsule inspect [--root PATH]\n\
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
  loom job list [--root PATH] [--status STATUS] [--limit N] [--format human|json]\n\
  loom job inspect --job-id HASH [--root PATH] [--format human|json]\n\
  loom job approve --job-id HASH [--root PATH]\n\
  loom agent resolve --agent-id ID [--org-id ORG] [--kernel-path PATH] [--root PATH] [--format human|json]\n\
  loom agent runtime --agent-id ID [--root PATH] [--format human|json]\n\
  loom agent session --agent-id ID [--new] [--task-kind KIND] [--status STATUS] [--summary TEXT] [--root PATH] [--format human|json]\n\
  loom agent memory --agent-id ID [--set KEY=VALUE]... [--root PATH] [--format human|json]\n\
  loom agent context --agent-id ID [--session-id ID] [--root PATH] [--format human|json]\n\
  loom envelope build --agent-id ID --action-type TYPE --resource RESOURCE [--estimated-cost-usd USD] [--run-id ID] [--session-id ID] [--org-id ORG] [--kernel-path PATH] [--root PATH] [--format human|json]\n\
  loom wasm limits [--config-file loom.toml.example] [--format human|json]\n\
  loom wasm profile show [--profile minimal|standard|heavy] [--format human|json]\n\
  loom wasm host show [--profile minimal|standard|heavy|custom] [--backend preview_only|wasmtime_ready] [--config-file loom.toml.example] [--format human|json]\n\
  loom wasm run [--module builtin:minimal|PATH] [--entrypoint NAME] [--entrypoint-arg I32] [--fuel-budget N] [--profile minimal|standard|heavy|custom] [--backend wasmtime_ready] [--config-file loom.toml.example] [--format human|json]\n\
\n\
Runtime rehearsal\n\
-----------------\n\
  loom action enqueue --agent-id ID [--capability NAME] [--action-type TYPE] [--resource RESOURCE] [--payload-json JSON] [--estimated-cost-usd USD] [--run-id ID] [--session-id ID] [--org-id ORG] [--kernel-path PATH] [--root PATH] [--format human|json]\n\
  loom action execute --agent-id ID [--capability NAME] [--gap-class CLASS] [--goal TEXT] [--action-type TYPE] [--resource RESOURCE] [--payload-json JSON] [--estimated-cost-usd USD] [--run-id ID] [--session-id ID] [--org-id ORG] [--kernel-path PATH] [--root PATH] [--format human|json]\n\
  loom swarm run --agent-id ID --kernel-path PATH --warrant-file FILE --actual-cost-usd USD --settle-zk [--action-type TYPE] [--resource RESOURCE] [--module builtin:system.info|builtin:minimal|builtin:terminal.exec|wasm:PATH] [--estimated-cost-usd USD] [--zk-backend sp1] [--org-id ORG] [--root PATH] [--format human|json]\n\
  loom service start [--root PATH] [--kernel-path PATH] [--socket PATH] [--http-address HOST:PORT] [--service-token TOKEN] [--commitments-source PATH|URL] [--workspace-token TOKEN] [--max-jobs N] [--poll-seconds N] [--iterations N] [--foreground] [--format human|json]\n\
  loom service status [--root PATH] [--socket PATH] [--format human|json]\n\
  loom service submit --agent-id ID [--capability NAME] [--gap-class CLASS] [--goal TEXT] [--action-type TYPE] [--resource RESOURCE] [--payload-json JSON] [--estimated-cost-usd USD] [--run-id ID] [--session-id ID] [--org-id ORG] [--kernel-path PATH] [--root PATH] [--socket PATH] [--http-url URL] [--service-token TOKEN] [--format human|json]\n\
  loom service cancel --job-id ID [--root PATH] [--socket PATH] [--http-url URL] [--service-token TOKEN] [--format human|json]\n\
  loom service import-commitments --commitments-source PATH|URL [--workspace-token TOKEN] [--kernel-path PATH] [--root PATH] [--format human|json]\n\
  loom service stop [--root PATH] [--socket PATH] [--format human|json]\n\
  loom supervisor run [--root PATH] [--kernel-path PATH] [--max-jobs N] [--format human|json]\n\
  loom supervisor watch [--root PATH] [--kernel-path PATH] [--max-jobs N] [--iterations N] [--poll-seconds N] [--format human|json]\n\
  loom supervisor status [--root PATH] [--format human|json]\n\
  loom supervisor lanes [--root PATH] [--format human|json]\n\
  loom supervisor daemon start [--root PATH] [--kernel-path PATH] [--max-jobs N] [--poll-seconds N] [--iterations N] [--format human|json]\n\
  loom supervisor daemon status [--root PATH] [--format human|json]\n\
  loom supervisor daemon stop [--root PATH] [--format human|json]\n\
  loom shadow preflight --agent-id ID --action-type TYPE --resource RESOURCE [--estimated-cost-usd USD] [--run-id ID] [--session-id ID] [--org-id ORG] [--kernel-path PATH] [--root PATH] [--format human|json]\n\
  loom shadow decide --agent-id ID --action-type TYPE --resource RESOURCE [--estimated-cost-usd USD] [--run-id ID] [--session-id ID] [--org-id ORG] [--kernel-path PATH] [--root PATH] [--format human|json]\n\
  loom shadow enforce --agent-id ID --action-type TYPE --resource RESOURCE [--estimated-cost-usd USD] [--run-id ID] [--session-id ID] [--org-id ORG] [--kernel-path PATH] [--root PATH] [--format human|json]\n\
  loom shadow compare --primary FILE [--shadow FILE] [--root PATH] [--format human|json]\n\
  loom shadow report [--root PATH]\n\
  loom shadow grpc-diagnostics [--root PATH] [--limit N] [--format human|json]\n\
  loom parity report [--root PATH]\n\
\n\
\n\
Next\n\
----\n\
  1. loom init --mode embedded --root \"$HOME/.local/share/meridian-loom/runtime/default\" --kernel-path /opt/meridian-kernel\n\
  2. export LOOM_SERVICE_TOKEN=loom-local-token\n\
  3. loom start --root \"$HOME/.local/share/meridian-loom/runtime/default\" --kernel-path /opt/meridian-kernel --http-address 127.0.0.1:18910 --service-token \"$LOOM_SERVICE_TOKEN\"\n\
  4. curl -sS -H 'Authorization: Bearer loom-local-token' http://127.0.0.1:18910/status\n\
  5. loom logs --root \"$HOME/.local/share/meridian-loom/runtime/default\" --lines 50\n",
    );
}

fn render_startup_banner(color: bool) -> String {
    let icon = [
        r#"             /\             "#,
        r#"        /\  /  \  /\        "#,
        r#"       /  \/ /\ \/  \       "#,
        r#"      / /\  /  \  /\ \      "#,
        r#"     /_/ /_/ /\ \_\ \_\     "#,
        r#"     \ \ \ \/  \/ / / /     "#,
        r#"      \ \/  /\  \/ / /      "#,
        r#"       \___/  \___/ /       "#,
    ]
    .join("\n");
    let version_line = format!(
        "Loom v{} — official local runtime with proof-first receipts.",
        env!("CARGO_PKG_VERSION")
    );
    if color {
        format!(
            "\x1b[38;5;81m{}\x1b[0m\n\x1b[1;97mMERIDIAN\x1b[0m\n\x1b[38;5;245mGOVERNED LOCAL RUNTIME\x1b[0m\n\x1b[38;5;153m{}\x1b[0m\n\n",
            icon,
            version_line,
        )
    } else {
        format!(
            "{}\nMERIDIAN\nGOVERNED LOCAL RUNTIME\n{}\n\n",
            icon, version_line,
        )
    }
}

fn print_startup_banner() {
    print!("{}", render_startup_banner(stdout_supports_color()));
}

fn print_human(output: &str) {
    if stdout_supports_color() {
        print!("{}", style_human_output(output));
    } else {
        print!("{}", output);
    }
}

fn print_human_block(parts: &[String]) {
    let merged = parts.join("\n\n");
    print_human(&merged);
}

fn stdout_supports_color() -> bool {
    if env::var_os("FORCE_COLOR").is_some() {
        return true;
    }
    if env::var_os("NO_COLOR").is_some() {
        return false;
    }
    io::stdout().is_terminal()
}

fn style_human_output(output: &str) -> String {
    let mut styled = output
        .lines()
        .map(style_human_line)
        .collect::<Vec<_>>()
        .join("\n");
    if output.ends_with('\n') {
        styled.push('\n');
    }
    styled
}

fn style_human_line(line: &str) -> String {
    const RESET: &str = "\x1b[0m";
    const CYAN: &str = "\x1b[38;5;81m";
    const BLUE: &str = "\x1b[38;5;111m";
    const GREEN: &str = "\x1b[38;5;114m";
    const YELLOW: &str = "\x1b[38;5;221m";
    const RED: &str = "\x1b[38;5;203m";
    const DIM: &str = "\x1b[2m";
    const BOLD: &str = "\x1b[1m";

    if line.starts_with("Meridian Loom //") {
        return format!("{BOLD}{CYAN}{line}{RESET}");
    }
    if !line.is_empty() && line.chars().all(|c| c == '=' || c == '-') {
        return format!("{DIM}{line}{RESET}");
    }
    if line.starts_with("[OK") {
        return format!("{GREEN}{line}{RESET}");
    }
    let lower = line.to_ascii_lowercase();
    if lower.contains("deny") || lower.contains("blocked") || lower.contains("failed") {
        return format!("{RED}{line}{RESET}");
    }
    if lower.contains("warn") || lower.contains("degraded") || lower.contains("divergence") {
        return format!("{YELLOW}{line}{RESET}");
    }
    if line.starts_with("phase:")
        || line.starts_with("boundary:")
        || line.starts_with("Stage ")
        || line == "Decision"
        || line == "Checks"
        || line == "Current state"
        || line == "Next"
    {
        return format!("{BOLD}{BLUE}{line}{RESET}");
    }
    line.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use loom_core::capabilities::ensure_capability_registry_scaffold;
    use serde_json::json;
    use std::fs;
    use std::path::Path;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_path(label: &str) -> PathBuf {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        let path = std::env::temp_dir().join(format!("{}-{}", label, unique));
        let _ = fs::remove_dir_all(&path);
        fs::create_dir_all(&path).expect("create temp path");
        path
    }

    fn sample_config() -> loom_core::Config {
        loom_core::Config {
            mode: "embedded".to_string(),
            kernel_path: String::new(),
            org_id: "local_foundry".to_string(),
            state_dir: "state".to_string(),
            run_dir: "run".to_string(),
            log_dir: "logs".to_string(),
            artifact_dir: "artifacts".to_string(),
            capabilities_dir: "capabilities".to_string(),
            python_path: "workers/python".to_string(),
            typescript_path: "workers/typescript".to_string(),
            wasm_dir: "workers/wasm".to_string(),
            service_http_address: "127.0.0.1:18910".to_string(),
            service_token_env: "LOOM_SERVICE_TOKEN".to_string(),
            service_max_jobs: 8,
            service_poll_seconds: 1,
            service_max_iterations: 0,
            log_level: "info".to_string(),
            log_format: "jsonl".to_string(),
            log_max_bytes: 1024,
            log_max_files: 3,
            handoff_mode: "off".to_string(),
            delivery_queue: loom_core::DEFAULT_DELIVERY_QUEUE.to_string(),
        }
    }

    fn write_job_snapshot(root: &Path, job_id: &str, job_json: &str) {
        let job_dir = root.join("state/runtime/jobs").join(job_id);
        fs::create_dir_all(&job_dir).expect("create job dir");
        fs::write(job_dir.join("job.json"), job_json).expect("write job snapshot");
    }

    #[test]
    fn verify_expectations_accepts_matching_summary_and_fields() {
        let result = json!({
            "summary": "artifact suspicious.exe size=258",
            "artifact_exists": true,
            "artifact_name": "suspicious.exe",
            "meta": {"count": 1}
        });
        let failures = commands::capability::verify_capability_expectations(
            Some(&result),
            Some("suspicious.exe"),
            &[
                "artifact_exists=true".to_string(),
                "artifact_name=suspicious.exe".to_string(),
                "meta.count=1".to_string(),
            ],
        )
        .expect("verify expectations");
        assert!(failures.is_empty());
    }

    #[test]
    fn verify_expectations_reports_failures() {
        let result = json!({
            "summary": "artifact sample.bin size=99",
            "artifact_exists": false
        });
        let failures = commands::capability::verify_capability_expectations(
            Some(&result),
            Some("missing-fragment"),
            &["artifact_exists=true".to_string()],
        )
        .expect("verify expectations");
        assert_eq!(failures.len(), 2);
        assert!(failures
            .iter()
            .any(|item| item.contains("summary missing fragment")));
        assert!(failures.iter().any(|item| item.contains("artifact_exists")));
    }

    #[test]
    fn verify_expectations_supports_array_paths() {
        let result = json!({
            "skill_output": {
                "blocked": [
                    {"url": "http://127.0.0.1/", "reason": "host resolves to non-public address: 127.0.0.1"}
                ]
            }
        });
        let failures = commands::capability::verify_capability_expectations(
            Some(&result),
            None,
            &[
                "skill_output.blocked.0.url=http://127.0.0.1/".to_string(),
                "skill_output.blocked.0.reason=host resolves to non-public address: 127.0.0.1"
                    .to_string(),
            ],
        )
        .expect("verify expectations");
        assert!(failures.is_empty());
    }

    #[test]
    fn capability_show_exposes_verification_evidence_and_reject_reasons() {
        let root = temp_path("loom-cap-show-evidence");
        let config = sample_config();
        ensure_capability_registry_scaffold(&root, &config).expect("registry scaffold");
        scaffold_capability(
            &root,
            &config,
            &CapabilityScaffoldRequest {
                name: "local.custom.reject".to_string(),
                description: "custom reject".to_string(),
                action_type: "respond".to_string(),
                resource: "capability:local.custom.reject".to_string(),
                worker_kind: "python".to_string(),
                worker_entry: String::new(),
                wasm_module: String::new(),
                payload_mode: "json".to_string(),
            },
        )
        .expect("scaffold");

        let job_id = "job::reject";
        let execution_id = "execution::reject";
        let job_path = root
            .join("state/runtime/jobs")
            .join(job_id)
            .join("job.json");
        write_job_snapshot(
            &root,
            job_id,
            &json!({
                "job_id": job_id,
                "job_path": job_path.display().to_string(),
                "job_status": "failed",
                "job_stage": "rejected",
                "queue_bucket": "reject",
                "queued_at": "1234567890",
                "updated_at": "1234567891",
                "agent_id": "agent_tutorial",
                "org_id": "org_tutorial",
                "action_type": "respond",
                "resource": "capability:local.custom.reject",
                "estimated_cost_usd": "0.050000",
                "runtime_outcome": "worker_rejected",
                "budget_reservation_id": null,
                "budget_reservation_status": "denied",
                "budget_reservation_reason": "policy reject: missing fixture set",
                "worker_status": "rejected",
                "queue_path": null,
                "decision_path": null,
                "execution_path": null,
                "event_path": null,
                "event_stream_path": null,
                "audit_log_path": null,
                "parity_report_path": null,
                "reservation_id": null,
                "reservation_state": "denied",
                "attempt_count": 1,
                "note": "reject reason: missing fixture set"
            })
            .to_string(),
        );

        update_capability_verification(
            &root,
            &config,
            "local.custom.reject",
            "failed",
            "1234567892",
            job_id,
            execution_id,
            "runtime_outcome=worker_rejected | expectation_failures=summary missing fragment: suspicious.exe",
        )
        .expect("update verification");

        let capability = find_capability_by_name(&root, &config, "local.custom.reject")
            .expect("resolve capability")
            .expect("capability present");

        let json_output = commands::capability::render_capability_show_json(&root, &capability)
            .expect("render json");
        let value: Value = serde_json::from_str(&json_output).expect("parse show json");
        let evidence = value
            .get("verification_evidence")
            .and_then(Value::as_object)
            .expect("verification evidence");

        assert_eq!(
            evidence.get("job_status").and_then(Value::as_str),
            Some("failed")
        );
        assert_eq!(
            evidence.get("job_stage").and_then(Value::as_str),
            Some("rejected")
        );
        assert_eq!(
            evidence.get("expectation_summary").and_then(Value::as_str),
            Some("runtime_outcome=worker_rejected | expectation_failures=summary missing fragment: suspicious.exe")
        );
        assert_eq!(
            evidence.get("failure_reason").and_then(Value::as_str),
            Some("policy reject: missing fixture set")
        );
        assert_eq!(
            evidence.get("job_note").and_then(Value::as_str),
            Some("reject reason: missing fixture set")
        );

        let human = commands::capability::render_capability_evidence_human(&root, &capability);
        assert!(human.contains("expectation_summary: runtime_outcome=worker_rejected"));
        assert!(human.contains("failure_reason:    policy reject: missing fixture set"));
        assert!(human.contains("job_note:          reject reason: missing fixture set"));
    }

    #[test]
    fn startup_banner_uses_official_runtime_wording() {
        let banner = render_startup_banner(false);
        assert!(banner.contains("MERIDIAN"));
        assert!(banner.contains("GOVERNED LOCAL RUNTIME"));
        assert!(banner.contains("official local runtime with proof-first receipts"));
        assert!(!banner.contains("CONSTITUTIONAL OS"));
    }
}
