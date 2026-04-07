use std::io::IsTerminal;
use std::path::Path;
use std::process::Command;

use crate::*;
use loom_core::memory_service::{
    render_memory_entries_human, render_memory_entries_json, render_memory_graph_inspect_human,
    render_memory_graph_inspect_json, render_memory_receipts_human, render_memory_receipts_json,
    render_memory_service_overview_human, render_memory_service_overview_json,
    MemoryLineageDirection, MemoryService,
};
use serde_json::{json, Value};

pub(crate) fn handle_memory(args: &[String]) -> LoomResult<()> {
    match args.first().map(String::as_str) {
        Some("status") | Some("overview") => handle_memory_overview(&args[1..]),
        Some("graph") => handle_memory_graph(&args[1..]),
        Some("fork") => handle_memory_fork(&args[1..]),
        Some("replay") => handle_memory_replay(&args[1..]),
        Some("search") => handle_memory_search(&args[1..]),
        Some("receipts") => handle_memory_receipts(&args[1..]),
        Some("write") => handle_memory_write(&args[1..]),
        Some("remove") => handle_memory_remove(&args[1..]),
        Some("prune") => handle_memory_prune(&args[1..]),
        _ => Err(
            "memory supports 'status', 'overview', 'graph', 'fork', 'replay', 'search', 'receipts', 'write', 'remove', and 'prune'"
                .to_string(),
        ),
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

fn handle_memory_overview(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let summary = MemoryService::with_defaults(&root).overview()?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_memory_service_overview_human(&summary));
        }
        _ => print!("{}", render_memory_service_overview_json(&summary)),
    }
    Ok(())
}

fn handle_memory_graph(args: &[String]) -> LoomResult<()> {
    match args.first().map(String::as_str) {
        Some("inspect") | Some("lineage") => handle_memory_graph_inspect(&args[1..]),
        _ => Err("memory graph supports 'inspect' and 'lineage'".to_string()),
    }
}

fn handle_memory_graph_inspect(args: &[String]) -> LoomResult<()> {
    let source_ref = args
        .first()
        .cloned()
        .ok_or_else(|| "memory graph inspect requires <source-ref>".to_string())?;
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let direction = MemoryLineageDirection::parse(
        take_value(args, "--direction")
            .unwrap_or_else(|| "both".to_string())
            .as_str(),
    )?;
    let limit = take_value(args, "--limit")
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(10);
    let focus_node_id = take_value(args, "--node-id");
    let view = MemoryService::with_defaults(&root).graph_inspect(
        &source_ref,
        focus_node_id.as_deref(),
        direction,
        limit,
    )?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_memory_graph_inspect_human(&view));
        }
        _ => print!("{}", render_memory_graph_inspect_json(&view)),
    }
    Ok(())
}

fn handle_memory_fork(args: &[String]) -> LoomResult<()> {
    let source_ref = args
        .first()
        .cloned()
        .ok_or_else(|| "memory fork requires <source-ref>".to_string())?;
    let target_agent_id = required_flag(args, "--target-agent-id")?;
    let branch = take_value(args, "--branch").unwrap_or_else(|| "main".to_string());
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let focus_node_id = take_value(args, "--node-id");
    let direction = MemoryLineageDirection::parse(
        take_value(args, "--direction")
            .unwrap_or_else(|| "both".to_string())
            .as_str(),
    )?;
    let limit = take_value(args, "--limit")
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(25);

    let service = MemoryService::with_defaults(&root);
    let selection = service.select_replay_entries(
        &source_ref,
        focus_node_id.as_deref(),
        direction.clone(),
        limit,
    )?;

    let fork_source = format!("memory_fork:{}:{}", selection.source_ref, branch);
    let mut forked_entries = 0usize;
    for entry in &selection.selected_entries {
        service.write(
            &target_agent_id,
            &entry.category,
            &entry.key,
            &entry.content,
            &fork_source,
        )?;
        forked_entries += 1;
    }

    let artifact_dir = root.join("artifacts/memory/forks");
    std::fs::create_dir_all(&artifact_dir).map_err(|error| error.to_string())?;
    let fork_artifact_path = artifact_dir.join(format!(
        "{}_to_{}_{}.json",
        sanitize_token(&selection.source_ref),
        sanitize_token(&target_agent_id),
        chrono_like_timestamp(),
    ));
    let latest_artifact_path = artifact_dir.join("latest.json");
    let payload = json!({
        "status": "memory_fork_created",
        "source_ref": selection.source_ref,
        "target_agent_id": target_agent_id,
        "branch": branch,
        "direction": direction.as_str(),
        "focus_node_id": selection.focus_node_id,
        "mode": selection.mode,
        "selected_node_ids": selection.selected_node_ids,
        "selected_category_keys": selection.selected_category_keys.iter().map(|(category, key)| {
            json!({"category": category, "key": key})
        }).collect::<Vec<_>>(),
        "selected_entries": selection.selected_entries.len(),
        "forked_entries": forked_entries,
        "total_graph_nodes": selection.total_graph_nodes,
        "artifact_path": fork_artifact_path.display().to_string(),
        "latest_artifact_path": latest_artifact_path.display().to_string(),
        "note": "native memory fork lane created from governed replay selection",
    });
    let rendered = serde_json::to_string_pretty(&payload).map_err(|error| error.to_string())?;
    std::fs::write(&fork_artifact_path, rendered.clone() + "\n")
        .map_err(|error| error.to_string())?;
    std::fs::write(&latest_artifact_path, rendered + "\n").map_err(|error| error.to_string())?;
    print_memory_fork_payload(payload, &format)
}

fn print_memory_fork_payload(payload: Value, format: &str) -> LoomResult<()> {
    match format {
        "human" => {
            print_startup_banner();
            print_human(&format!(
                "status:            {}\nsource_ref:        {}\ntarget_agent_id:   {}\nbranch:            {}\ndirection:         {}\nmode:              {}\nselected_entries:  {}\nforked_entries:    {}\nartifact_path:     {}\nlatest_artifact:   {}\nnote:              {}\n",
                payload.get("status").and_then(Value::as_str).unwrap_or("unknown"),
                payload.get("source_ref").and_then(Value::as_str).unwrap_or(""),
                payload.get("target_agent_id").and_then(Value::as_str).unwrap_or(""),
                payload.get("branch").and_then(Value::as_str).unwrap_or(""),
                payload.get("direction").and_then(Value::as_str).unwrap_or("both"),
                payload.get("mode").and_then(Value::as_str).unwrap_or("(n/a)"),
                payload.get("selected_entries").and_then(Value::as_u64).unwrap_or(0),
                payload.get("forked_entries").and_then(Value::as_u64).unwrap_or(0),
                payload.get("artifact_path").and_then(Value::as_str).unwrap_or(""),
                payload
                    .get("latest_artifact_path")
                    .and_then(Value::as_str)
                    .unwrap_or(""),
                payload.get("note").and_then(Value::as_str).unwrap_or(""),
            ));
        }
        _ => print!(
            "{}\n",
            serde_json::to_string_pretty(&payload).map_err(|error| error.to_string())?
        ),
    }
    Ok(())
}

#[derive(Clone, Debug)]
struct ReplayCourtStatus {
    status: String,
    reason: String,
    restrictions: Vec<String>,
}

#[derive(Clone, Debug)]
struct ReplayAuthorityStatus {
    status: String,
    reason: String,
}

fn handle_memory_replay(args: &[String]) -> LoomResult<()> {
    let source_ref = args
        .first()
        .cloned()
        .ok_or_else(|| "memory replay requires <source-ref>".to_string())?;
    let target_agent_id = required_flag(args, "--target-agent-id")?;
    let kernel_path = required_flag(args, "--kernel-path")?;
    let root = root_from(take_value(args, "--root").as_deref())?;
    let config = read_config(&root)?;
    let org_id = take_value(args, "--org-id").unwrap_or_else(|| config.org_id.clone());
    let format = output_format(args);
    let focus_node_id = take_value(args, "--node-id");
    let direction = MemoryLineageDirection::parse(
        take_value(args, "--direction")
            .unwrap_or_else(|| "both".to_string())
            .as_str(),
    )?;
    let limit = take_value(args, "--limit")
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(25);

    let target_identity = resolve_agent_identity(
        &root,
        Some(kernel_path.as_str()),
        &target_agent_id,
        Some(org_id.as_str()),
    )?;
    let court = query_replay_court_status(
        Path::new(kernel_path.as_str()),
        &target_identity.agent_id,
        org_id.as_str(),
    )?;
    let authority = query_replay_authority_status(
        Path::new(kernel_path.as_str()),
        &target_identity.agent_id,
        org_id.as_str(),
    )?;
    if court.status == "blocked" || authority.status == "denied" {
        let payload = json!({
            "status": "memory_replay_blocked",
            "source_ref": source_ref,
            "target_agent_id": target_identity.agent_id,
            "org_id": org_id,
            "court_status": court.status,
            "court_reason": court.reason,
            "court_restrictions": court.restrictions,
            "authority_status": authority.status,
            "authority_reason": authority.reason,
            "direction": direction.as_str(),
            "focus_node_id": focus_node_id,
            "selected_node_ids": Vec::<String>::new(),
            "replayed_entries": 0usize,
            "note": "replay blocked by governance gate before memory write",
        });
        return print_memory_replay_payload(payload, &format);
    }

    let service = MemoryService::with_defaults(&root);
    let selection = service.select_replay_entries(
        &source_ref,
        focus_node_id.as_deref(),
        direction.clone(),
        limit,
    )?;
    let mut replayed_entries = 0usize;
    for entry in &selection.selected_entries {
        service.write(
            &target_identity.agent_id,
            &entry.category,
            &entry.key,
            &entry.content,
            &format!("memory_replay:{}", selection.source_ref),
        )?;
        replayed_entries += 1;
    }

    let payload = json!({
        "status": "memory_replay_applied",
        "source_ref": selection.source_ref,
        "target_agent_id": target_identity.agent_id,
        "org_id": org_id,
        "court_status": court.status,
        "court_reason": court.reason,
        "court_restrictions": court.restrictions,
        "authority_status": authority.status,
        "authority_reason": authority.reason,
        "direction": direction.as_str(),
        "focus_node_id": selection.focus_node_id,
        "mode": selection.mode,
        "selected_node_ids": selection.selected_node_ids,
        "selected_category_keys": selection.selected_category_keys.iter().map(|(category, key)| {
            json!({"category": category, "key": key})
        }).collect::<Vec<_>>(),
        "total_graph_nodes": selection.total_graph_nodes,
        "selected_entries": selection.selected_entries.len(),
        "replayed_entries": replayed_entries,
        "note": selection.note,
    });
    print_memory_replay_payload(payload, &format)
}

fn print_memory_replay_payload(payload: Value, format: &str) -> LoomResult<()> {
    match format {
        "human" => {
            print_startup_banner();
            print_human(&format!(
                "status:            {}\nsource_ref:        {}\ntarget_agent_id:   {}\ncourt_status:      {}\nauthority_status:  {}\nmode:              {}\ndirection:         {}\nfocus_node_id:     {}\nselected_nodes:    {}\nreplayed_entries:  {}\nnote:              {}\n",
                payload.get("status").and_then(Value::as_str).unwrap_or("unknown"),
                payload.get("source_ref").and_then(Value::as_str).unwrap_or(""),
                payload.get("target_agent_id").and_then(Value::as_str).unwrap_or(""),
                payload.get("court_status").and_then(Value::as_str).unwrap_or("unknown"),
                payload.get("authority_status").and_then(Value::as_str).unwrap_or("unknown"),
                payload.get("mode").and_then(Value::as_str).unwrap_or("(n/a)"),
                payload.get("direction").and_then(Value::as_str).unwrap_or("both"),
                payload
                    .get("focus_node_id")
                    .and_then(Value::as_str)
                    .unwrap_or("(none)"),
                payload
                    .get("selected_node_ids")
                    .and_then(Value::as_array)
                    .map(|items| items.len())
                    .unwrap_or(0),
                payload
                    .get("replayed_entries")
                    .and_then(Value::as_u64)
                    .unwrap_or(0),
                payload.get("note").and_then(Value::as_str).unwrap_or(""),
            ));
        }
        _ => print!(
            "{}\n",
            serde_json::to_string_pretty(&payload).map_err(|error| error.to_string())?
        ),
    }
    Ok(())
}

fn query_replay_court_status(
    kernel_path: &Path,
    agent_id: &str,
    org_id: &str,
) -> LoomResult<ReplayCourtStatus> {
    let script = r#"
import json, sys
kernel_path, agent_id, org_id = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, kernel_path)
from kernel import court
restrictions = court.get_restrictions(agent_id, org_id)
blocked = "memory_replay" in restrictions or "replay" in restrictions
print(json.dumps({
    "status": "blocked" if blocked else "clear",
    "reason": "court restriction: memory_replay" if blocked else "clear",
    "restrictions": restrictions,
}))
"#;
    let output = Command::new("python3")
        .arg("-c")
        .arg(script)
        .arg(kernel_path)
        .arg(agent_id)
        .arg(org_id)
        .output()
        .map_err(|error| format!("failed to query Court for replay: {}", error))?;
    if !output.status.success() {
        return Err(format!(
            "Court replay query failed: {}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }
    let value: Value = serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("invalid Court replay response: {}", error))?;
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
    Ok(ReplayCourtStatus {
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

fn query_replay_authority_status(
    kernel_path: &Path,
    agent_id: &str,
    org_id: &str,
) -> LoomResult<ReplayAuthorityStatus> {
    let script = r#"
import json, sys
kernel_path, agent_id, org_id = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, kernel_path)
from kernel import authority
allowed, reason = authority.check_authority(agent_id, "memory_replay", org_id)
print(json.dumps({
    "status": "allowed" if allowed else "denied",
    "reason": reason,
}))
"#;
    let output = Command::new("python3")
        .arg("-c")
        .arg(script)
        .arg(kernel_path)
        .arg(agent_id)
        .arg(org_id)
        .output()
        .map_err(|error| format!("failed to query Authority for replay: {}", error))?;
    if !output.status.success() {
        return Err(format!(
            "Authority replay query failed: {}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }
    let value: Value = serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("invalid Authority replay response: {}", error))?;
    Ok(ReplayAuthorityStatus {
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

fn handle_memory_search(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let agent_id = required_flag(args, "--agent-id")?;
    let category = take_value(args, "--category");
    let key_prefix = take_value(args, "--key-prefix");
    let entries = MemoryService::with_defaults(&root).search(
        &agent_id,
        category.as_deref(),
        key_prefix.as_deref(),
    )?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_memory_entries_human(&entries));
        }
        _ => print!("{}", render_memory_entries_json(&entries)),
    }
    Ok(())
}

fn handle_memory_receipts(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let agent_id = take_value(args, "--agent-id");
    let limit = take_value(args, "--limit")
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(20);
    let receipts = MemoryService::with_defaults(&root).list_receipts(limit, agent_id.as_deref())?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_memory_receipts_human(&receipts));
        }
        _ => print!("{}", render_memory_receipts_json(&receipts)),
    }
    Ok(())
}

fn handle_memory_write(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let agent_id = required_flag(args, "--agent-id")?;
    let category = required_flag(args, "--category")?;
    let key = required_flag(args, "--key")?;
    let content = required_flag(args, "--content")?;
    let source = take_value(args, "--source").unwrap_or_else(|| "operator".to_string());
    let entry =
        MemoryService::with_defaults(&root).write(&agent_id, &category, &key, &content, &source)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_memory_entries_human(&[entry]));
        }
        _ => print!("{}", render_memory_entries_json(&[entry])),
    }
    Ok(())
}

fn handle_memory_remove(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let agent_id = required_flag(args, "--agent-id")?;
    let category = required_flag(args, "--category")?;
    let key = required_flag(args, "--key")?;
    let removed = MemoryService::with_defaults(&root).remove(&agent_id, &category, &key)?;
    let payload = serde_json::json!({
        "agent_id": agent_id,
        "category": category,
        "key": key,
        "removed": removed,
    });
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&format!(
                "agent_id:         {}\ncategory:         {}\nkey:              {}\nremoved:          {}\n",
                payload["agent_id"].as_str().unwrap_or(""),
                payload["category"].as_str().unwrap_or(""),
                payload["key"].as_str().unwrap_or(""),
                payload["removed"].as_bool().unwrap_or(false),
            ));
        }
        _ => print!(
            "{}\n",
            serde_json::to_string_pretty(&payload).map_err(|e| e.to_string())?
        ),
    }
    Ok(())
}

fn handle_memory_prune(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let pruned = MemoryService::with_defaults(&root).prune()?;
    let payload = serde_json::json!({ "pruned_entries": pruned });
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&format!("pruned_entries:   {}\n", pruned));
        }
        _ => print!(
            "{}\n",
            serde_json::to_string_pretty(&payload).map_err(|e| e.to_string())?
        ),
    }
    Ok(())
}
