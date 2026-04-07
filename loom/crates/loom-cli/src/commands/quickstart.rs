use crate::*;
use ed25519_dalek::{Signature, Signer, SigningKey};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::io::{self, IsTerminal, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::time::{SystemTime, UNIX_EPOCH};

const DEFAULT_ORG_ID: &str = "local_foundry";
const DEFAULT_CHARTER: &str = "Meridian Loom Quickstart Charter";
const DEFAULT_AGENT_NAME: &str = "My First Agent";
const DEFAULT_WEBHOOK_URL: &str = "https://example.com/loom-quickstart-webhook";
const DEFAULT_CHANNEL_TEST_TEXT: &str = "quickstart lane ping";
const QUICKSTART_PROOF_ACTION_TYPE: &str = "quickstart_first_proof";
const QUICKSTART_PROOF_RESOURCE: &str = "quickstart_runtime_lane";

pub(crate) fn handle_quickstart(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_quickstart_help();
        return Ok(());
    }

    let format = output_format(args);
    let mut org_id = take_value(args, "--org-id").unwrap_or_else(|| DEFAULT_ORG_ID.to_string());
    let mut charter = take_value(args, "--charter").unwrap_or_else(|| DEFAULT_CHARTER.to_string());
    let mut agent_name =
        take_value(args, "--agent-name").unwrap_or_else(|| DEFAULT_AGENT_NAME.to_string());
    let mut webhook_url =
        take_value(args, "--webhook-url").unwrap_or_else(|| DEFAULT_WEBHOOK_URL.to_string());
    let mut channel_test_text = take_value(args, "--channel-test-text")
        .unwrap_or_else(|| DEFAULT_CHANNEL_TEST_TEXT.to_string());
    let root = root_from(take_value(args, "--root").as_deref())?;
    let kernel_path = take_value(args, "--kernel-path")
        .or_else(default_kernel_path)
        .ok_or_else(|| {
            "quickstart requires --kernel-path or MERIDIAN_KERNEL_PATH or /opt/meridian-kernel"
                .to_string()
        })?;
    let interactive = should_run_interactive(args, &format);
    if interactive {
        print_startup_banner();
        print_human("Meridian Loom // QUICKSTART\n===========================\n");
        org_id = prompt_with_default("Organization ID", &org_id)?;
        charter = prompt_with_default("Nation charter", &charter)?;
        agent_name = prompt_with_default("Agent name", &agent_name)?;
        webhook_url = prompt_with_default("Webhook URL", &webhook_url)?;
        channel_test_text = prompt_with_default("Channel test text", &channel_test_text)?;
    }

    let runner = LoomRunner::new()?;
    let root_text = root.display().to_string();
    let quickstart_root = root.join("state/quickstart");
    std::fs::create_dir_all(&quickstart_root).map_err(|error| error.to_string())?;

    let total_steps = 7usize;

    print_progress_if_human(&format, 1, total_steps, "initialize runtime root");
    let had_runtime_config = root.join("loom.toml").exists();
    runner.run_checked(&[
        "init",
        "--mode",
        "embedded",
        "--root",
        &root_text,
        "--kernel-path",
        &kernel_path,
        "--org-id",
        &org_id,
    ])?;
    let init_payload = json!({
        "status": if had_runtime_config { "reused" } else { "initialized" },
        "root": root_text.clone(),
        "kernel_path": kernel_path.clone(),
        "org_id": org_id.clone(),
        "config_path": root.join("loom.toml").display().to_string(),
    });

    print_progress_if_human(&format, 2, total_steps, "bootstrap nation surface");
    let nation_payload = runner.run_json(&[
        "init-nation",
        "--charter",
        &charter,
        "--root",
        &root_text,
        "--kernel-path",
        &kernel_path,
        "--org-id",
        &org_id,
        "--format",
        "json",
    ])?;

    print_progress_if_human(&format, 3, total_steps, "provision first agent");
    let new_agent_payload = runner.run_json(&[
        "new-agent",
        "--name",
        &agent_name,
        "--root",
        &root_text,
        "--kernel-path",
        &kernel_path,
        "--org-id",
        &org_id,
        "--webhook-url",
        &webhook_url,
        "--format",
        "json",
    ])?;
    let agent_slug = required_json_string(&new_agent_payload, "slug")?;
    let agent_id = required_json_string(&new_agent_payload, "agent_id")?;

    print_progress_if_human(&format, 4, total_steps, "run agent once");
    runner.run_checked(&[
        "run-agent",
        &agent_slug,
        "--foreground",
        "--once",
        "--poll-seconds",
        "1",
    ])?;
    let run_agent_inspect_payload =
        runner.run_json(&["run-agent", "inspect", &agent_slug, "--format", "json"])?;

    print_progress_if_human(&format, 5, total_steps, "verify channel delivery");
    let channel_payload = runner.run_json(&[
        "channel",
        "test",
        "--agent",
        &agent_slug,
        "--text",
        &channel_test_text,
        "--format",
        "json",
    ])?;

    print_progress_if_human(&format, 6, total_steps, "capture first governed proof");
    let warrant_path = quickstart_root.join("quickstart_shadow_warrant.json");
    write_signed_warrant(&warrant_path)?;
    let shadow_payload = runner.run_json(&[
        "shadow",
        "run",
        "--backend",
        "wasmtime",
        "--root",
        &root_text,
        "--kernel-path",
        &kernel_path,
        "--agent-id",
        &agent_id,
        "--org-id",
        &org_id,
        "--action-type",
        QUICKSTART_PROOF_ACTION_TYPE,
        "--resource",
        QUICKSTART_PROOF_RESOURCE,
        "--module",
        "builtin:system.info",
        "--warrant-file",
        warrant_path.to_str().unwrap_or(""),
        "--format",
        "json",
    ])?;

    print_progress_if_human(&format, 7, total_steps, "render first proof reports");
    let parity_report = runner.run_stdout_text(&["parity", "report", "--root", &root_text])?;
    let shadow_report = runner.run_stdout_text(&["shadow", "report", "--root", &root_text])?;
    let proof_dir = quickstart_root.join("first_proof");
    std::fs::create_dir_all(&proof_dir).map_err(|error| error.to_string())?;
    let parity_report_path = proof_dir.join("parity_report.txt");
    let shadow_report_path = proof_dir.join("shadow_report.txt");
    std::fs::write(&parity_report_path, parity_report).map_err(|error| error.to_string())?;
    std::fs::write(&shadow_report_path, shadow_report).map_err(|error| error.to_string())?;

    let execution_path = required_json_string(&shadow_payload, "execution_path")?;
    let shadow_latest_path = required_json_string(&shadow_payload, "shadow_latest_path")?;
    let parity_latest_path = required_json_string(&shadow_payload, "parity_latest_path")?;
    let proof_summary_path = proof_dir.join("summary.json");
    let payload = json!({
        "status": "quickstart_completed",
        "org_id": org_id,
        "charter": charter,
        "root": root_text,
        "kernel_path": kernel_path,
        "agent": {
            "name": agent_name,
            "slug": agent_slug,
            "id": agent_id,
        },
        "steps": {
            "init": init_payload,
            "nation": nation_payload,
            "new_agent": new_agent_payload,
            "run_agent_inspect": run_agent_inspect_payload,
            "channel_test": channel_payload,
            "first_proof": {
                "status": shadow_payload.get("status").and_then(Value::as_str).unwrap_or("unknown"),
                "backend": shadow_payload.get("backend").and_then(Value::as_str).unwrap_or("unknown"),
                "warrant_binding_status": shadow_payload.get("warrant_binding_status").and_then(Value::as_str).unwrap_or("unknown"),
                "warrant_id_hex": shadow_payload.get("warrant_id_hex").and_then(Value::as_str).unwrap_or(""),
                "poge_merkle_root_hex": shadow_payload.get("poge_merkle_root_hex").and_then(Value::as_str).unwrap_or(""),
                "poge_witness_digest_hex": shadow_payload.get("poge_witness_digest_hex").and_then(Value::as_str).unwrap_or(""),
            }
        },
        "artifacts": {
            "execution_path": execution_path,
            "shadow_latest_path": shadow_latest_path,
            "parity_latest_path": parity_latest_path,
            "parity_report_path": parity_report_path.display().to_string(),
            "shadow_report_path": shadow_report_path.display().to_string(),
            "warrant_file_path": warrant_path.display().to_string(),
            "proof_summary_path": proof_summary_path.display().to_string(),
        },
        "migration_note": "quickstart is additive; existing 'loom init' and 'loom init-nation' remain unchanged",
        "rollback_note": "to rollback, continue using 'loom init' + 'loom init-nation' + 'loom new-agent' directly",
    });
    std::fs::write(
        &proof_summary_path,
        serde_json::to_string_pretty(&payload).map_err(|error| error.to_string())? + "\n",
    )
    .map_err(|error| error.to_string())?;

    match format.as_str() {
        "json" => {
            println!(
                "{}",
                serde_json::to_string_pretty(&payload).map_err(|error| error.to_string())?
            );
        }
        _ => {
            if !interactive {
                print_startup_banner();
            }
            print_human(&format!(
                "Meridian Loom // QUICKSTART\n===========================\nstatus:               quickstart_completed\nroot:                 {}\nkernel_path:          {}\norg_id:               {}\nagent_name:           {}\nagent_slug:           {}\nagent_id:             {}\nwarrant_binding:      {}\nexecution_path:       {}\nshadow_latest_path:   {}\nparity_report_path:   {}\nshadow_report_path:   {}\nproof_summary_path:   {}\n\nNext\n----\n1. loom run-agent watch {} --once\n2. loom channel health --root \"{}\" --agent {}\n3. loom parity report --root \"{}\"\n4. loom shadow report --root \"{}\"\n",
                payload["root"].as_str().unwrap_or(""),
                payload["kernel_path"].as_str().unwrap_or(""),
                payload["org_id"].as_str().unwrap_or(""),
                payload["agent"]["name"].as_str().unwrap_or(""),
                payload["agent"]["slug"].as_str().unwrap_or(""),
                payload["agent"]["id"].as_str().unwrap_or(""),
                payload
                    .pointer("/steps/first_proof/warrant_binding_status")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown"),
                payload
                    .pointer("/artifacts/execution_path")
                    .and_then(Value::as_str)
                    .unwrap_or(""),
                payload
                    .pointer("/artifacts/shadow_latest_path")
                    .and_then(Value::as_str)
                    .unwrap_or(""),
                payload
                    .pointer("/artifacts/parity_report_path")
                    .and_then(Value::as_str)
                    .unwrap_or(""),
                payload
                    .pointer("/artifacts/shadow_report_path")
                    .and_then(Value::as_str)
                    .unwrap_or(""),
                payload
                    .pointer("/artifacts/proof_summary_path")
                    .and_then(Value::as_str)
                    .unwrap_or(""),
                payload["agent"]["slug"].as_str().unwrap_or(""),
                payload["root"].as_str().unwrap_or(""),
                payload["agent"]["slug"].as_str().unwrap_or(""),
                payload["root"].as_str().unwrap_or(""),
                payload["root"].as_str().unwrap_or(""),
            ));
        }
    }

    Ok(())
}

fn print_quickstart_help() {
    print_human(
        "Meridian Loom // QUICKSTART HELP
===================================
USAGE:
  loom quickstart [--root PATH] [--kernel-path PATH] [--org-id ORG] [--charter TEXT] [--agent-name NAME] [--webhook-url URL] [--channel-test-text TEXT] [--interactive] [--non-interactive] [--format human|json]

PURPOSE:
  One-command first proof lane:
  init -> init-nation -> new-agent -> run-agent --once -> channel test -> shadow run proof -> parity/shadow report artifacts.
",
    );
}

fn output_format(args: &[String]) -> String {
    take_value(args, "--format").unwrap_or_else(|| {
        if io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    })
}

fn should_run_interactive(args: &[String], format: &str) -> bool {
    if has_flag(args, "--interactive") {
        return true;
    }
    if has_flag(args, "--non-interactive") {
        return false;
    }
    format == "human" && io::stdin().is_terminal() && io::stdout().is_terminal()
}

fn prompt_with_default(label: &str, default_value: &str) -> LoomResult<String> {
    print!("{} [{}]: ", label, default_value);
    io::stdout().flush().map_err(|error| error.to_string())?;
    let mut line = String::new();
    io::stdin()
        .read_line(&mut line)
        .map_err(|error| error.to_string())?;
    let trimmed = line.trim();
    if trimmed.is_empty() {
        Ok(default_value.to_string())
    } else {
        Ok(trimmed.to_string())
    }
}

fn print_progress_if_human(format: &str, step: usize, total: usize, label: &str) {
    if format != "human" {
        return;
    }
    let width = 18usize;
    let filled = (step.saturating_mul(width) / total.max(1)).min(width);
    let bar = format!("{}{}", "#".repeat(filled), "-".repeat(width - filled));
    print_human(&format!("[step {}/{}] [{}] {}\n", step, total, bar, label));
}

fn default_kernel_path() -> Option<String> {
    for candidate in ["/opt/meridian-kernel", "/tmp/meridian-kernel"] {
        if Path::new(candidate).exists() {
            return Some(candidate.to_string());
        }
    }
    std::env::var("MERIDIAN_KERNEL_PATH")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

struct LoomRunner {
    exe: PathBuf,
}

impl LoomRunner {
    fn new() -> LoomResult<Self> {
        let exe = std::env::current_exe().map_err(|error| error.to_string())?;
        Ok(Self { exe })
    }

    fn run_output(&self, args: &[&str]) -> LoomResult<Output> {
        let mut command = Command::new(&self.exe);
        command.args(args);
        command.output().map_err(|error| error.to_string())
    }

    fn run_checked(&self, args: &[&str]) -> LoomResult<()> {
        let output = self.run_output(args)?;
        ensure_success(args, &output)
    }

    fn run_json(&self, args: &[&str]) -> LoomResult<Value> {
        let output = self.run_output(args)?;
        ensure_success(args, &output)?;
        parse_json_from_output(&output.stdout).map_err(|error| {
            format!(
                "failed parsing JSON for {:?}: {} | stdout={}",
                args,
                error,
                String::from_utf8_lossy(&output.stdout).trim()
            )
        })
    }

    fn run_stdout_text(&self, args: &[&str]) -> LoomResult<String> {
        let output = self.run_output(args)?;
        ensure_success(args, &output)?;
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    }
}

fn ensure_success(args: &[&str], output: &Output) -> LoomResult<()> {
    if output.status.success() {
        return Ok(());
    }
    Err(format!(
        "quickstart subcommand {:?} failed (code={:?})\nstdout:\n{}\nstderr:\n{}",
        args,
        output.status.code(),
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    ))
}

fn parse_json_from_output(stdout: &[u8]) -> LoomResult<Value> {
    if let Ok(value) = serde_json::from_slice(stdout) {
        return Ok(value);
    }
    let text = String::from_utf8_lossy(stdout);
    let lines = text.lines().collect::<Vec<_>>();
    for index in (0..lines.len()).rev() {
        let candidate = lines[index..].join("\n");
        let trimmed = candidate.trim();
        if trimmed.starts_with('{') || trimmed.starts_with('[') {
            if let Ok(value) = serde_json::from_str::<Value>(trimmed) {
                return Ok(value);
            }
        }
    }
    Err("no JSON payload found in command output".to_string())
}

fn required_json_string(value: &Value, key: &str) -> LoomResult<String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(|item| item.to_string())
        .ok_or_else(|| format!("missing JSON string field '{}'", key))
}

fn write_signed_warrant(path: &Path) -> LoomResult<()> {
    let signer = SigningKey::from_bytes(&[11u8; 32]);
    let mut id = [0u8; 32];
    let seed = now_unix_ms() as u8;
    for (index, slot) in id.iter_mut().enumerate() {
        *slot = seed
            .wrapping_add((index as u8).wrapping_mul(9))
            .wrapping_add(7);
    }
    let scope_cbor = vec![
        0xA1, 0x69, b'q', b'u', b'i', b'c', b'k', b's', b't', b'a', b'r', b't', 0xF5,
    ];
    let expiry_epoch_ms = now_unix_ms().saturating_add(120_000);
    let signature: Signature = signer.sign(&warrant_message(id, &scope_cbor, expiry_epoch_ms));
    let payload = json!({
        "id_hex": hex::encode(id),
        "scope_cbor_hex": hex::encode(scope_cbor),
        "expiry_epoch_ms": expiry_epoch_ms,
        "kernel_sig_hex": hex::encode(signature.to_bytes()),
        "kernel_pub_hex": hex::encode(signer.verifying_key().to_bytes()),
    });
    std::fs::write(
        path,
        serde_json::to_string_pretty(&payload).map_err(|error| error.to_string())? + "\n",
    )
    .map_err(|error| error.to_string())
}

fn warrant_message(id: [u8; 32], scope_cbor: &[u8], expiry_epoch_ms: u64) -> Vec<u8> {
    let scope_hash: [u8; 32] = Sha256::digest(scope_cbor).into();
    let mut message = Vec::with_capacity(72);
    message.extend_from_slice(&id);
    message.extend_from_slice(&scope_hash);
    message.extend_from_slice(&expiry_epoch_ms.to_be_bytes());
    message
}

fn now_unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_json_from_output_handles_prefixed_logs() {
        let raw = b"log line\n{\"status\":\"ok\",\"value\":1}\n";
        let value = parse_json_from_output(raw).expect("parse mixed output");
        assert_eq!(value["status"], "ok");
        assert_eq!(value["value"], 1);
    }
}
