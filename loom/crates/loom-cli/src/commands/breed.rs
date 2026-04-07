use std::collections::BTreeSet;
use std::io::IsTerminal;
use std::path::Path;
use std::process::Command;

use crate::*;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

pub(crate) fn handle_breed(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_breed_help();
        return Ok(());
    }
    let parent1 = positional_arg(args, 0).ok_or_else(|| "breed requires <parent1>".to_string())?;
    let parent2 = positional_arg(args, 1).ok_or_else(|| "breed requires <parent2>".to_string())?;
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let agent_ref = required_flag(args, "--agent-id")?;
    let kernel_path = kernel_path_for(&root, take_value(args, "--kernel-path").as_deref())?;
    let config = read_config(&root)?;
    let org_id = take_value(args, "--org-id").unwrap_or(config.org_id.clone());
    let mutation_rate = take_value(args, "--mutation-rate")
        .and_then(|value| value.parse::<f64>().ok())
        .unwrap_or(0.1)
        .clamp(0.0, 1.0);

    let court = query_breed_court_status(&kernel_path, &agent_ref, &org_id)?;
    let authority = query_breed_authority_status(&kernel_path, &agent_ref, &org_id)?;
    if court.status == "blocked" || authority.status == "denied" {
        let payload = json!({
            "status": "breed_blocked",
            "agent_ref": agent_ref,
            "parent1": parent1,
            "parent2": parent2,
            "org_id": org_id,
            "court_status": court.status,
            "court_reason": court.reason,
            "court_restrictions": court.restrictions,
            "authority_status": authority.status,
            "authority_reason": authority.reason,
            "note": "breed blocked by governance gate",
        });
        return print_breed_payload(payload, &format);
    }

    let parent_one = query_agent_record(&kernel_path, &parent1, &org_id)?;
    let parent_two = query_agent_record(&kernel_path, &parent2, &org_id)?;
    let dna = build_dna_record(&agent_ref, &parent_one, &parent_two, mutation_rate)?;
    let artifacts_dir = root.join("artifacts/evolution");
    std::fs::create_dir_all(&artifacts_dir).map_err(|error| error.to_string())?;
    let dna_path = artifacts_dir.join(format!("{}.json", dna.dna_id));
    let latest_path = artifacts_dir.join("latest.json");
    let payload = json!({
        "status": "breed_created",
        "agent_ref": agent_ref,
        "org_id": org_id,
        "parent1": parent1,
        "parent2": parent2,
        "court_status": court.status,
        "authority_status": authority.status,
        "dna_id": dna.dna_id,
        "dna_hash": dna.dna_hash,
        "mutation_rate": mutation_rate,
        "crossover_signature": dna.crossover_signature,
        "mutation_signature": dna.mutation_signature,
        "dna_artifact_path": dna_path.display().to_string(),
        "latest_artifact_path": latest_path.display().to_string(),
        "note": "governed dna artifact persisted",
    });
    let rendered = serde_json::to_string_pretty(&payload).map_err(|error| error.to_string())?;
    std::fs::write(&dna_path, rendered.clone() + "\n").map_err(|error| error.to_string())?;
    std::fs::write(&latest_path, rendered + "\n").map_err(|error| error.to_string())?;
    print_breed_payload(payload, &format)
}

fn print_breed_help() {
    print_human(
        "Meridian Loom // BREED HELP
============================
USAGE:
  loom breed <parent1> <parent2> --agent-id ID --kernel-path PATH [--org-id ORG] [--mutation-rate 0.10] [--root PATH] [--format human|json]

PURPOSE:
  Deterministic crossover + mutation, Court/Authority gated, DNA artifact persisted.
",
    );
}

fn positional_arg(args: &[String], index: usize) -> Option<String> {
    args.iter()
        .filter(|value| !value.starts_with('-'))
        .nth(index)
        .cloned()
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
struct DnaRecord {
    dna_id: String,
    dna_hash: String,
    crossover_signature: String,
    mutation_signature: String,
}

fn print_breed_payload(payload: Value, format: &str) -> LoomResult<()> {
    match format {
        "human" => {
            print_startup_banner();
            print_human(&format!(
                "status:              {}\nagent_ref:           {}\nparent1:             {}\nparent2:             {}\ncourt_status:        {}\nauthority_status:    {}\ndna_id:              {}\ndna_hash:            {}\nmutation_rate:       {}\nnote:                {}\n",
                payload.get("status").and_then(Value::as_str).unwrap_or("unknown"),
                payload.get("agent_ref").and_then(Value::as_str).unwrap_or(""),
                payload.get("parent1").and_then(Value::as_str).unwrap_or(""),
                payload.get("parent2").and_then(Value::as_str).unwrap_or(""),
                payload.get("court_status").and_then(Value::as_str).unwrap_or("unknown"),
                payload.get("authority_status").and_then(Value::as_str).unwrap_or("unknown"),
                payload.get("dna_id").and_then(Value::as_str).unwrap_or("(none)"),
                payload.get("dna_hash").and_then(Value::as_str).unwrap_or("(none)"),
                payload.get("mutation_rate").and_then(Value::as_f64).unwrap_or(0.0),
                payload.get("note").and_then(Value::as_str).unwrap_or(""),
            ));
        }
        _ => println!(
            "{}",
            serde_json::to_string_pretty(&payload).map_err(|error| error.to_string())?
        ),
    }
    Ok(())
}

fn query_breed_court_status(
    kernel_path: &Path,
    agent_id: &str,
    org_id: &str,
) -> LoomResult<CourtStatus> {
    let script = r#"
import json, pathlib, sys
kernel_path, agent_id, org_id = sys.argv[1], sys.argv[2], sys.argv[3]
root = pathlib.Path(kernel_path)
sys.path.insert(0, str(root / "kernel"))
import court
restrictions = court.get_restrictions(agent_id, org_id)
blocked = "breed" in restrictions or "evolution" in restrictions
print(json.dumps({
    "status": "blocked" if blocked else "clear",
    "reason": "court restriction: breed" if blocked else "clear",
    "restrictions": restrictions,
}))
"#;
    let value = run_python_json(
        script,
        &[kernel_path.to_str().unwrap_or(""), agent_id, org_id],
    )?;
    let restrictions = value
        .get("restrictions")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(|item| item.to_string())
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    Ok(CourtStatus {
        status: value
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("clear")
            .to_string(),
        reason: value
            .get("reason")
            .and_then(Value::as_str)
            .unwrap_or("clear")
            .to_string(),
        restrictions,
    })
}

fn query_breed_authority_status(
    kernel_path: &Path,
    agent_id: &str,
    org_id: &str,
) -> LoomResult<AuthorityStatus> {
    let script = r#"
import json, pathlib, sys
kernel_path, agent_id, org_id = sys.argv[1], sys.argv[2], sys.argv[3]
root = pathlib.Path(kernel_path)
sys.path.insert(0, str(root / "kernel"))
import authority
allowed, reason = authority.check_authority(agent_id, "breed", org_id)
print(json.dumps({
    "status": "allowed" if allowed else "denied",
    "reason": reason,
}))
"#;
    let value = run_python_json(
        script,
        &[kernel_path.to_str().unwrap_or(""), agent_id, org_id],
    )?;
    Ok(AuthorityStatus {
        status: value
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("allowed")
            .to_string(),
        reason: value
            .get("reason")
            .and_then(Value::as_str)
            .unwrap_or("ok")
            .to_string(),
    })
}

fn query_agent_record(kernel_path: &Path, agent_id: &str, org_id: &str) -> LoomResult<Value> {
    let script = r#"
import json, pathlib, sys
kernel_path, agent_id, org_id = sys.argv[1], sys.argv[2], sys.argv[3]
root = pathlib.Path(kernel_path)
sys.path.insert(0, str(root / "kernel"))
import agent_registry
agent = agent_registry.get_agent(agent_id, org_id=org_id)
if agent is None:
    raise SystemExit(f"agent not found: {agent_id}")
print(json.dumps(agent))
"#;
    run_python_json(
        script,
        &[kernel_path.to_str().unwrap_or(""), agent_id, org_id],
    )
}

fn build_dna_record(
    breeder_agent_id: &str,
    parent_one: &Value,
    parent_two: &Value,
    mutation_rate: f64,
) -> LoomResult<DnaRecord> {
    let parent_one_id = parent_one
        .get("id")
        .and_then(Value::as_str)
        .ok_or_else(|| "parent1 missing id".to_string())?;
    let parent_two_id = parent_two
        .get("id")
        .and_then(Value::as_str)
        .ok_or_else(|| "parent2 missing id".to_string())?;
    let parent_one_role = parent_one
        .get("role")
        .and_then(Value::as_str)
        .unwrap_or("unknown");
    let parent_two_role = parent_two
        .get("role")
        .and_then(Value::as_str)
        .unwrap_or("unknown");
    let mut scope_set = BTreeSet::new();
    for parent in [parent_one, parent_two] {
        if let Some(scopes) = parent.get("scopes").and_then(Value::as_array) {
            for scope in scopes.iter().filter_map(Value::as_str) {
                scope_set.insert(scope.trim().to_string());
            }
        }
    }
    let mut scopes = scope_set.into_iter().collect::<Vec<_>>();
    scopes.sort();
    let crossover_signature = format!(
        "{}+{}:{}+{}",
        parent_one_id, parent_two_id, parent_one_role, parent_two_role
    );
    let mutation_seed = format!("{:.4}", mutation_rate);
    let mutation_signature = format!("deterministic_mutation:{}", mutation_seed);
    let dna_material = format!(
        "v1|breeder={}|p1={}|p2={}|roles={}:{}|scopes={}|mutation={}",
        breeder_agent_id,
        parent_one_id,
        parent_two_id,
        parent_one_role,
        parent_two_role,
        scopes.join(","),
        mutation_seed
    );
    let mut hasher = Sha256::new();
    hasher.update(dna_material.as_bytes());
    let dna_hash = hex::encode(hasher.finalize());
    let dna_id = format!("dna_{}", &dna_hash[..16]);
    Ok(DnaRecord {
        dna_id,
        dna_hash,
        crossover_signature,
        mutation_signature,
    })
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
    serde_json::from_slice(&output.stdout).map_err(|error| {
        format!(
            "python helper returned invalid json: {} | stdout={}",
            error,
            String::from_utf8_lossy(&output.stdout).trim()
        )
    })
}
