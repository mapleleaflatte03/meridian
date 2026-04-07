use std::io::IsTerminal;

use crate::*;
use loom_core::service_ingress_runtime::{
    list_service_ingress, render_service_ingress_human, render_service_ingress_json,
    render_service_ingress_list_human, render_service_ingress_list_json,
    render_service_ingress_overview_human, render_service_ingress_overview_json,
    show_service_ingress, sync_service_ingress_runtime,
};

pub(crate) fn handle_ingress(args: &[String]) -> LoomResult<()> {
    match args.first().map(String::as_str) {
        Some("status") => handle_ingress_status(&args[1..]),
        Some("list") => handle_ingress_list(&args[1..]),
        Some("show") => handle_ingress_show(&args[1..]),
        _ => Err("ingress supports 'status', 'list', and 'show'".to_string()),
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

fn handle_ingress_status(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let summary = sync_service_ingress_runtime(&root)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_service_ingress_overview_human(&summary));
        }
        _ => print!("{}", render_service_ingress_overview_json(&summary)),
    }
    Ok(())
}

fn handle_ingress_list(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let limit = take_value(args, "--limit")
        .and_then(|raw| raw.parse::<usize>().ok())
        .unwrap_or(20);
    let records = list_service_ingress(&root, limit)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_service_ingress_list_human(&records));
        }
        _ => print!("{}", render_service_ingress_list_json(&records)),
    }
    Ok(())
}

fn handle_ingress_show(args: &[String]) -> LoomResult<()> {
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = output_format(args);
    let request_id = required_flag(args, "--request-id")?;
    let record = show_service_ingress(&root, &request_id)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_service_ingress_human(&record));
        }
        _ => print!("{}", render_service_ingress_json(&record)),
    }
    Ok(())
}
