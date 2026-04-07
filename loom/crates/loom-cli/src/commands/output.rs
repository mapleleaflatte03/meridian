use std::io::IsTerminal;

use crate::*;
use loom_core::output_guard::{
    guard_user_visible_output, render_output_guard_human, render_output_guard_json,
    OutputGuardPolicy,
};

pub(crate) fn handle_output(args: &[String]) -> LoomResult<()> {
    match args.first().map(String::as_str) {
        Some("inspect") => handle_output_inspect(&args[1..]),
        _ => Err("output supports 'inspect'".to_string()),
    }
}

fn handle_output_inspect(args: &[String]) -> LoomResult<()> {
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let text = if let Some(path) = take_value(args, "--file") {
        std::fs::read_to_string(&path)
            .map_err(|error| format!("failed to read {}: {}", path, error))?
    } else {
        required_flag(args, "--text")?
    };
    let result = guard_user_visible_output(
        &text,
        &OutputGuardPolicy {
            allow_receipt_hashes: has_flag(args, "--allow-receipt-hashes"),
            allow_operator_diagnostics: has_flag(args, "--allow-operator-diagnostics"),
        },
    )?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_output_guard_human(&result));
        }
        _ => print!("{}", render_output_guard_json(&result)),
    }
    Ok(())
}
