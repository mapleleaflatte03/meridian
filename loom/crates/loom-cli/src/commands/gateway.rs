use std::io::IsTerminal;

use crate::*;
use loom_core::gateway_runtime::{
    gateway_runtime_overview, render_gateway_runtime_human, render_gateway_runtime_json,
    sync_gateway_runtime,
};

pub(crate) fn handle_gateway(args: &[String]) -> LoomResult<()> {
    match args.first().map(String::as_str) {
        Some("status") => handle_gateway_status(&args[1..]),
        Some("sync") => handle_gateway_sync(&args[1..]),
        _ => Err("gateway supports 'status' and 'sync'".to_string()),
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

fn handle_gateway_status(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let summary = gateway_runtime_overview(&root)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_gateway_runtime_human(&summary));
        }
        _ => print!("{}", render_gateway_runtime_json(&summary)),
    }
    Ok(())
}

fn handle_gateway_sync(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let summary = sync_gateway_runtime(&root)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_gateway_runtime_human(&summary));
        }
        _ => print!("{}", render_gateway_runtime_json(&summary)),
    }
    Ok(())
}
