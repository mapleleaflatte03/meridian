use std::io::IsTerminal;

use crate::*;
use loom_core::bindings::{
    binding_overview, find_binding, load_bindings, render_binding_human, render_binding_json,
    render_binding_list_human, render_binding_list_json, render_binding_overview_human,
    render_binding_overview_json, render_binding_resolution_human, render_binding_resolution_json,
    render_binding_sync_human, render_binding_sync_json, resolve_binding, sync_binding_registry,
};

pub(crate) fn handle_binding(args: &[String]) -> LoomResult<()> {
    match args.first().map(String::as_str) {
        Some("status") => handle_binding_status(&args[1..]),
        Some("sync") => handle_binding_sync(&args[1..]),
        Some("list") => handle_binding_list(&args[1..]),
        Some("show") => handle_binding_show(&args[1..]),
        Some("resolve") => handle_binding_resolve(&args[1..]),
        _ => Err("binding supports 'status', 'sync', 'list', 'show', and 'resolve'".to_string()),
    }
}

fn handle_binding_status(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let summary = binding_overview(&root)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_binding_overview_human(&summary));
        }
        _ => print!("{}", render_binding_overview_json(&summary)),
    }
    Ok(())
}

fn handle_binding_sync(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let summary = sync_binding_registry(&root)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_binding_sync_human(&summary));
        }
        _ => print!("{}", render_binding_sync_json(&summary)),
    }
    Ok(())
}

fn handle_binding_list(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let records = load_bindings(&root)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_binding_list_human(&records));
        }
        _ => print!("{}", render_binding_list_json(&records)),
    }
    Ok(())
}

fn handle_binding_show(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let binding_id = required_flag(args, "--binding-id")?;
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let record = find_binding(&root, &binding_id)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_binding_human(&record));
        }
        _ => print!("{}", render_binding_json(&record)),
    }
    Ok(())
}

fn handle_binding_resolve(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let channel_id = required_flag(args, "--channel")?;
    let peer_id = required_flag(args, "--peer")?;
    let thread_id = take_value(args, "--thread");
    let agent_id = take_value(args, "--agent-id");
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let resolution = resolve_binding(
        &root,
        &channel_id,
        &peer_id,
        thread_id.as_deref(),
        agent_id.as_deref(),
    )?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_binding_resolution_human(&resolution));
        }
        _ => print!("{}", render_binding_resolution_json(&resolution)),
    }
    Ok(())
}
