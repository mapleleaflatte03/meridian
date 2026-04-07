use std::io::IsTerminal;

use crate::*;
use loom_core::context_engine::{
    context_bundle, context_engine_overview, render_context_bundle_human,
    render_context_bundle_json, render_context_engine_overview_human,
    render_context_engine_overview_json, render_context_overlay_write_human,
    render_context_overlay_write_json, sync_context_registry, write_context_overlay,
};

pub(crate) fn handle_context(args: &[String]) -> LoomResult<()> {
    match args.first().map(String::as_str) {
        Some("status") => handle_context_status(&args[1..]),
        Some("sync") => handle_context_sync(&args[1..]),
        Some("bundle") => handle_context_bundle(&args[1..]),
        Some("overlay") => handle_context_overlay(&args[1..]),
        _ => Err("context supports 'status', 'sync', 'bundle', and 'overlay'".to_string()),
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

fn handle_context_status(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let summary = context_engine_overview(&root)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_context_engine_overview_human(&summary));
        }
        _ => print!("{}", render_context_engine_overview_json(&summary)),
    }
    Ok(())
}

fn handle_context_sync(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let summary = sync_context_registry(&root)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_context_engine_overview_human(&summary));
        }
        _ => print!("{}", render_context_engine_overview_json(&summary)),
    }
    Ok(())
}

fn handle_context_bundle(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let agent_id = required_flag(args, "--agent-id")?;
    let session_id = take_value(args, "--session-id");
    let format = output_format(args);
    let bundle = context_bundle(&root, &agent_id, session_id.as_deref())?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_context_bundle_human(&bundle));
        }
        _ => print!("{}", render_context_bundle_json(&bundle)),
    }
    Ok(())
}

fn handle_context_overlay(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let agent_id = required_flag(args, "--agent-id")?;
    let session_id = required_flag(args, "--session-id")?;
    let section = required_flag(args, "--section")?;
    let format = output_format(args);
    let text = if let Some(path) = take_value(args, "--file") {
        std::fs::read_to_string(&path)
            .map_err(|error| format!("failed to read {}: {}", path, error))?
    } else {
        required_flag(args, "--text")?
    };
    let result = write_context_overlay(&root, &agent_id, &session_id, &section, &text)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_context_overlay_write_human(&result));
        }
        _ => print!("{}", render_context_overlay_write_json(&result)),
    }
    Ok(())
}
