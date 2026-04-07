use std::io::IsTerminal;
use std::path::PathBuf;

use crate::*;
use loom_core::skill_lifecycle::{
    disable_skill, enable_skill, install_skill, list_skill_installs, list_skill_locks,
    remove_skill, render_skill_installs_list_human, render_skill_lifecycle_receipt_human,
    render_skill_lifecycle_receipt_json, render_skill_locks_human, update_skill_metadata,
};
use loom_core::skills::{
    find_skill, load_skills, render_skill_human, render_skill_json, render_skill_list_human,
    render_skill_list_json, render_skill_overview_human, render_skill_overview_json,
    render_skill_sync_human, render_skill_sync_json, skill_overview, sync_skill_registry,
};

pub(crate) fn handle_skill(args: &[String]) -> LoomResult<()> {
    if args.is_empty()
        || matches!(
            args.first().map(String::as_str),
            Some("help" | "--help" | "-h")
        )
    {
        print_skill_help();
        return Ok(());
    }
    match args.first().map(String::as_str) {
        Some("status") => handle_skill_status(&args[1..]),
        Some("sync") => handle_skill_sync(&args[1..]),
        Some("list") => handle_skill_list(&args[1..]),
        Some("show") => handle_skill_show(&args[1..]),
        Some("install") => handle_skill_install(&args[1..]),
        Some("remove") => handle_skill_remove(&args[1..]),
        Some("enable") => handle_skill_enable(&args[1..]),
        Some("disable") => handle_skill_disable(&args[1..]),
        Some("update") => handle_skill_update(&args[1..]),
        Some("locks") => handle_skill_locks(&args[1..]),
        Some("installs") => handle_skill_installs(&args[1..]),
        _ => Err("skill supports: status, sync, list, show, install, remove, enable, disable, update, locks, installs".to_string()),
    }
}

fn print_skill_help() {
    println!(
        "Meridian Loom // SKILL

Manage skill registry and lifecycle (install, enable, lock, remove).

USAGE: loom skill <COMMAND> [OPTIONS]

COMMANDS:
  status                              Skill registry overview
  sync                                Rebuild skill registry from manifests
  list                                List all registered skills
  show --skill-id ID                  Show skill details
  install --skill-root PATH           Install a skill from a local directory
        [--skill-id ID]
  remove --skill-id ID [--force]      Remove an installed skill
  enable --skill-id ID                Enable a disabled skill
  disable --skill-id ID               Disable a skill
  update --skill-id ID                Update skill metadata
        [--name NAME] [--desc DESC]
  locks                               List skill dependency locks
  installs                            List skill installation records

GLOBAL OPTIONS:
  --root ROOT                         Workspace root path
  --format human|json                 Output format (default: human)"
    );
}

fn handle_skill_status(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_skill_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let summary = skill_overview(&root)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_skill_overview_human(&summary));
        }
        _ => print!("{}", render_skill_overview_json(&summary)),
    }
    Ok(())
}

fn handle_skill_sync(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_skill_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let summary = sync_skill_registry(&root)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_skill_sync_human(&summary));
        }
        _ => print!("{}", render_skill_sync_json(&summary)),
    }
    Ok(())
}

fn handle_skill_list(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_skill_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let records = load_skills(&root)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_skill_list_human(&records));
        }
        _ => print!("{}", render_skill_list_json(&records)),
    }
    Ok(())
}

fn handle_skill_show(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_skill_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let skill_id = required_flag(args, "--skill-id")?;
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let record = find_skill(&root, &skill_id)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_skill_human(&record));
        }
        _ => print!("{}", render_skill_json(&record)),
    }
    Ok(())
}

fn handle_skill_install(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_skill_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let skill_root_str = required_flag(args, "--skill-root")?;
    let skill_id_override = take_value(args, "--skill-id");
    let format = format_flag(args);
    let skill_root = PathBuf::from(&skill_root_str);
    if !skill_root.exists() {
        return Err(format!("skill-root '{}' does not exist", skill_root_str));
    }
    let receipt = install_skill(&root, &skill_root, skill_id_override.as_deref())?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_skill_lifecycle_receipt_human(&receipt));
        }
        _ => print!("{}", render_skill_lifecycle_receipt_json(&receipt)),
    }
    Ok(())
}

fn handle_skill_remove(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_skill_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let skill_id = required_flag(args, "--skill-id")?;
    let force = has_flag(args, "--force");
    let format = format_flag(args);
    let receipt = remove_skill(&root, &skill_id, force)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_skill_lifecycle_receipt_human(&receipt));
        }
        _ => print!("{}", render_skill_lifecycle_receipt_json(&receipt)),
    }
    Ok(())
}

fn handle_skill_enable(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_skill_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let skill_id = required_flag(args, "--skill-id")?;
    let format = format_flag(args);
    let receipt = enable_skill(&root, &skill_id)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_skill_lifecycle_receipt_human(&receipt));
        }
        _ => print!("{}", render_skill_lifecycle_receipt_json(&receipt)),
    }
    Ok(())
}

fn handle_skill_disable(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_skill_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let skill_id = required_flag(args, "--skill-id")?;
    let format = format_flag(args);
    let receipt = disable_skill(&root, &skill_id)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_skill_lifecycle_receipt_human(&receipt));
        }
        _ => print!("{}", render_skill_lifecycle_receipt_json(&receipt)),
    }
    Ok(())
}

fn handle_skill_update(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_skill_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let skill_id = required_flag(args, "--skill-id")?;
    let display_name = take_value(args, "--name");
    let description = take_value(args, "--desc");
    let version = take_value(args, "--version");
    let format = format_flag(args);
    let receipt = update_skill_metadata(
        &root,
        &skill_id,
        display_name.as_deref(),
        description.as_deref(),
        version.as_deref(),
    )?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_skill_lifecycle_receipt_human(&receipt));
        }
        _ => print!("{}", render_skill_lifecycle_receipt_json(&receipt)),
    }
    Ok(())
}

fn handle_skill_locks(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_skill_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = format_flag(args);
    let locks = list_skill_locks(&root)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_skill_locks_human(&locks));
        }
        _ => {
            use serde_json::json;
            let out = json!(locks.iter().map(|l| json!({"skill_id": l.skill_id, "locked_by": l.locked_by, "locked_at": l.locked_at})).collect::<Vec<_>>());
            print!(
                "{}\n",
                serde_json::to_string_pretty(&out).unwrap_or_default()
            );
        }
    }
    Ok(())
}

fn handle_skill_installs(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_skill_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = format_flag(args);
    let installs = list_skill_installs(&root)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_skill_installs_list_human(&installs));
        }
        _ => {
            use serde_json::json;
            let out = json!(installs.iter().map(|r| json!({"skill_id": r.skill_id, "enabled": r.enabled, "locked": r.locked, "skill_type": r.skill_type})).collect::<Vec<_>>());
            print!(
                "{}\n",
                serde_json::to_string_pretty(&out).unwrap_or_default()
            );
        }
    }
    Ok(())
}

fn format_flag(args: &[String]) -> String {
    take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    })
}
