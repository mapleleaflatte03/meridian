use std::collections::BTreeSet;
use std::env;
use std::io::IsTerminal;
use std::path::Path;
use std::process::Command;

use crate::*;
use loom_core::gateway_runtime::sync_gateway_runtime;
use serde_json::{json, Value};

const DEFAULT_ACTOR_ID: &str = "loom:init_nation";
const SEED_AGENT_NAMES: [&str; 7] = [
    "manager", "atlas", "sentinel", "forge", "quill", "aegis", "pulse",
];

pub(crate) fn handle_nation(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_nation_help();
        return Ok(());
    }
    let charter = required_flag(args, "--charter")?;
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let requested_org_hint =
        take_value(args, "--org-id").unwrap_or_else(|| "local_foundry".to_string());
    let nation_name =
        take_value(args, "--name").unwrap_or_else(|| requested_org_hint.replace('_', " "));
    let kernel_override = take_value(args, "--kernel-path");
    let kernel_default = kernel_override.clone().or_else(default_kernel_path);

    let runtime_status = if root.join("loom.toml").exists() {
        "reused".to_string()
    } else {
        init_workspace(
            &root,
            "embedded",
            kernel_default.as_deref(),
            requested_org_hint.as_str(),
        )?;
        "created".to_string()
    };
    let config = read_config(&root)?;
    let kernel_path = kernel_path_for(
        &root,
        kernel_override.as_deref().or(kernel_default.as_deref()),
    )?;
    let org_slug = slugify(requested_org_hint.as_str());

    let institution = bootstrap_institution(
        &kernel_path,
        nation_name.as_str(),
        org_slug.as_str(),
        charter.as_str(),
    )?;
    let institution_id = institution
        .get("org_id")
        .and_then(Value::as_str)
        .ok_or_else(|| "bootstrap did not return org_id".to_string())?
        .to_string();
    let institution_name = institution
        .get("name")
        .and_then(Value::as_str)
        .unwrap_or(nation_name.as_str())
        .to_string();
    let institution_slug = institution
        .get("slug")
        .and_then(Value::as_str)
        .unwrap_or(org_slug.as_str())
        .to_string();

    let agent_listing = list_org_agents(&kernel_path, institution_id.as_str())?;
    let (seed_agents_count, seed_agent_ids) = count_seed_agents(&agent_listing)?;
    if seed_agents_count < SEED_AGENT_NAMES.len() {
        return Err(format!(
            "bootstrap produced {} seed agents, expected at least {}",
            seed_agents_count,
            SEED_AGENT_NAMES.len()
        ));
    }

    let wallet_id = format!("nation_hot_wallet_{}", institution_slug.replace('-', "_"));
    let account_id = format!("nation_hot_account_{}", institution_slug.replace('-', "_"));
    let wallet = ensure_hot_wallet(
        &kernel_path,
        &root,
        institution_id.as_str(),
        wallet_id.as_str(),
        account_id.as_str(),
    )?;
    let hot_wallet_status = wallet
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("unknown")
        .to_string();

    let gateway = sync_gateway_runtime(&root)?;
    let summary_path = root.join("state/nation/init_last.json");
    if let Some(parent) = summary_path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let summary = json!({
        "status": "init_nation_ready",
        "runtime_status": runtime_status,
        "runtime_root": root.display().to_string(),
        "kernel_path": kernel_path.display().to_string(),
        "runtime_org_id": config.org_id,
        "requested_org_hint": requested_org_hint,
        "institution_id": institution_id,
        "institution_name": institution_name,
        "institution_slug": institution_slug,
        "charter": charter,
        "seed_agents_count": seed_agents_count,
        "seed_agent_ids": seed_agent_ids,
        "hot_wallet_status": hot_wallet_status,
        "hot_wallet_id": wallet_id,
        "hot_account_id": account_id,
        "hot_wallet_address": wallet.pointer("/wallet/address").and_then(Value::as_str).unwrap_or(""),
        "gateway_endpoint": gateway.endpoint,
        "gateway_remote_mode": gateway.remote_mode,
        "gateway_total_channels": gateway.total_channel_count,
        "gateway_enabled_channels": gateway.enabled_channel_count,
        "artifact_path": summary_path.display().to_string(),
        "note": "one-command nation bootstrap: runtime + institution + hot wallet + seed agents + gateway",
    });
    std::fs::write(
        &summary_path,
        serde_json::to_string_pretty(&summary).map_err(|error| error.to_string())? + "\n",
    )
    .map_err(|error| error.to_string())?;

    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&format!(
                "status:              init_nation_ready\nruntime_status:      {}\nruntime_root:        {}\nkernel_path:         {}\ninstitution_id:      {}\ninstitution_name:    {}\ninstitution_slug:    {}\nseed_agents_count:   {}\nhot_wallet_status:   {}\nhot_wallet_id:       {}\nhot_account_id:      {}\ngateway_endpoint:    {}\nartifact_path:       {}\n",
                summary["runtime_status"].as_str().unwrap_or("unknown"),
                summary["runtime_root"].as_str().unwrap_or(""),
                summary["kernel_path"].as_str().unwrap_or(""),
                summary["institution_id"].as_str().unwrap_or(""),
                summary["institution_name"].as_str().unwrap_or(""),
                summary["institution_slug"].as_str().unwrap_or(""),
                summary["seed_agents_count"].as_u64().unwrap_or(0),
                summary["hot_wallet_status"].as_str().unwrap_or("unknown"),
                summary["hot_wallet_id"].as_str().unwrap_or(""),
                summary["hot_account_id"].as_str().unwrap_or(""),
                summary["gateway_endpoint"].as_str().unwrap_or(""),
                summary["artifact_path"].as_str().unwrap_or(""),
            ));
        }
        _ => println!(
            "{}",
            serde_json::to_string_pretty(&summary).map_err(|error| error.to_string())?
        ),
    }
    Ok(())
}

fn print_nation_help() {
    print_human(
        "Meridian Loom // INIT NATION HELP
=================================
USAGE:
  loom init-nation --charter \"My Company\" [--org-id ORG] [--name NAME] [--root PATH] [--kernel-path PATH] [--format human|json]

PURPOSE:
  One-command bootstrap:
  runtime + institution + treasury hot wallet + 7 seed agents + simple gateway sync.
",
    );
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

fn slugify(raw: &str) -> String {
    let mut out = String::new();
    let mut dash = false;
    for ch in raw.chars() {
        if ch.is_ascii_alphanumeric() {
            out.push(ch.to_ascii_lowercase());
            dash = false;
        } else if !dash {
            out.push('-');
            dash = true;
        }
    }
    out.trim_matches('-').to_string()
}

fn default_kernel_path() -> Option<String> {
    for candidate in ["/opt/meridian-kernel", "/tmp/meridian-kernel"] {
        if Path::new(candidate).exists() {
            return Some(candidate.to_string());
        }
    }
    env::var("MERIDIAN_KERNEL_PATH")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn bootstrap_institution(
    kernel_path: &Path,
    name: &str,
    slug: &str,
    charter: &str,
) -> LoomResult<Value> {
    let script = r#"
import json, pathlib, sys
kernel_path, name, slug, charter = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
root = pathlib.Path(kernel_path)
sys.path.insert(0, str(root / "kernel"))
import bootstrap
import organizations
bootstrap.bootstrap(name=name, slug=slug, charter=charter)
orgs = organizations.load_orgs().get("organizations", {})
target = None
for org_id, org in orgs.items():
    if org.get("slug") == slug:
        target = {
            "org_id": org_id,
            "name": org.get("name", ""),
            "slug": org.get("slug", ""),
            "charter": org.get("charter", ""),
        }
        break
if target is None:
    raise SystemExit(f"bootstrap did not materialize org for slug={slug}")
print(json.dumps(target))
"#;
    run_python_json(
        script,
        &[kernel_path.to_str().unwrap_or(""), name, slug, charter],
    )
}

fn list_org_agents(kernel_path: &Path, org_id: &str) -> LoomResult<Value> {
    let script = r#"
import json, pathlib, sys
kernel_path, org_id = sys.argv[1], sys.argv[2]
root = pathlib.Path(kernel_path)
sys.path.insert(0, str(root / "kernel"))
import agent_registry
agents = agent_registry.list_agents(org_id=org_id)
print(json.dumps({"agents": agents}))
"#;
    run_python_json(script, &[kernel_path.to_str().unwrap_or(""), org_id])
}

fn count_seed_agents(agent_listing: &Value) -> LoomResult<(usize, Vec<String>)> {
    let agents = agent_listing
        .get("agents")
        .and_then(Value::as_array)
        .ok_or_else(|| "agent listing missing agents array".to_string())?;
    let mut seen_names = BTreeSet::new();
    let mut ids = Vec::new();
    for agent in agents {
        let Some(name) = agent.get("name").and_then(Value::as_str) else {
            continue;
        };
        let lowered = name.trim().to_ascii_lowercase();
        if SEED_AGENT_NAMES.iter().any(|seed| seed == &lowered) {
            seen_names.insert(lowered);
            if let Some(agent_id) = agent.get("id").and_then(Value::as_str) {
                ids.push(agent_id.to_string());
            }
        }
    }
    ids.sort();
    ids.dedup();
    Ok((seen_names.len(), ids))
}

fn ensure_hot_wallet(
    kernel_path: &Path,
    root: &Path,
    org_id: &str,
    wallet_id: &str,
    account_id: &str,
) -> LoomResult<Value> {
    let script = r#"
import hashlib, json, pathlib, sys
kernel_path, org_id, wallet_id, account_id, actor_id = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
root = pathlib.Path(kernel_path)
sys.path.insert(0, str(root / "kernel"))
import treasury

wallet = treasury.get_wallet(wallet_id, org_id)
account = treasury.get_treasury_account(account_id, org_id)
status = "reused"
if wallet is None or account is None:
    status = "created"
    if wallet is None:
        address = "0x" + hashlib.sha256(wallet_id.encode("utf-8")).hexdigest()[:40]
        wallet = treasury.register_wallet(
            wallet_id,
            address,
            actor_id=actor_id,
            org_id=org_id,
            label="Loom Nation Hot Wallet",
            verification_level=3,
            verification_label="self_custody_verified",
            payout_eligible=True,
            status="active",
        )
    if account is None:
        account = treasury.register_treasury_account(
            account_id,
            wallet_id=wallet_id,
            actor_id=actor_id,
            org_id=org_id,
            label="Loom Nation Treasury Hot Account",
            purpose="init-nation settlement source",
            status="active",
        )
print(json.dumps({
    "status": status,
    "wallet": wallet,
    "account": account,
    "wallet_id": wallet_id,
    "account_id": account_id,
}))
"#;
    let actor_id = DEFAULT_ACTOR_ID;
    let mut value = run_python_json(
        script,
        &[
            kernel_path.to_str().unwrap_or(""),
            org_id,
            wallet_id,
            account_id,
            actor_id,
        ],
    )?;
    value["secret_dir"] = json!(root.join("state/nation/secrets").display().to_string());
    Ok(value)
}

fn run_python_json(script: &str, args: &[&str]) -> LoomResult<Value> {
    let mut command = Command::new("python3");
    command.arg("-c").arg(script);
    for value in args {
        command.arg(value);
    }
    let output = command.output().map_err(|error| error.to_string())?;
    if !output.status.success() {
        return Err(format!(
            "python helper failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    parse_json_from_mixed_stdout(&output.stdout).map_err(|error| {
        format!(
            "python helper returned invalid json: {} | stdout={}",
            error,
            String::from_utf8_lossy(&output.stdout).trim()
        )
    })
}

fn parse_json_from_mixed_stdout(stdout: &[u8]) -> LoomResult<Value> {
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
    Err("no JSON payload detected".to_string())
}
