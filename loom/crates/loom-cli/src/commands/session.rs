use std::io::IsTerminal;

use crate::*;
use loom_core::session_policy::{
    clear_session_override, get_session_override, get_session_send_policy, list_session_overrides,
    list_session_send_policies, render_session_override_human, render_session_override_json,
    render_session_overrides_list_human, render_session_send_policies_list_human,
    render_session_send_policy_human, render_session_send_policy_json, set_session_override,
    set_session_send_policy,
};
use loom_core::session_provenance::{
    find_session_provenance, list_session_provenance, list_session_provenance_with_options,
    open_session_provenance, render_session_provenance_human, render_session_provenance_json,
    render_session_provenance_list_human, render_session_provenance_list_json,
    render_session_provenance_overview_human, render_session_provenance_overview_json,
    session_provenance_overview, update_session_provenance_job,
    update_session_provenance_route_full,
};

pub(crate) fn handle_session(args: &[String]) -> LoomResult<()> {
    if args.is_empty()
        || matches!(
            args.first().map(String::as_str),
            Some("help" | "--help" | "-h")
        )
    {
        print_session_help();
        return Ok(());
    }
    match args.first().map(String::as_str) {
        Some("status") => handle_session_status(&args[1..]),
        Some("list") => handle_session_list(&args[1..]),
        Some("show") => handle_session_show(&args[1..]),
        Some("route") => handle_session_route(&args[1..]),
        Some("override") => handle_session_override(&args[1..]),
        Some("clear-override") => handle_session_clear_override(&args[1..]),
        Some("send-policy") => handle_session_send_policy(&args[1..]),
        Some("overrides") => handle_session_overrides_list(&args[1..]),
        Some("policies") => handle_session_policies_list(&args[1..]),
        _ => Err(
            "session supports: status, list, show, route, override, clear-override, send-policy, overrides, policies"
                .to_string(),
        ),
    }
}

fn print_session_help() {
    println!(
        "Meridian Loom // SESSION

Manage session provenance, overrides, and send policies.

USAGE: loom session <COMMAND> [OPTIONS]

COMMANDS:
  status                              Show session provenance overview
  list [--limit N] [--include-archived] [--archived-only]
                                      List active sessions, optionally including archived legacy sessions
  show --session-key KEY              Show session details + override + send policy
  route --session-key KEY             Update route/provenance facts for a session
        [--channel-id CHANNEL]
        [--peer-id PEER]
        [--org-id ORG]
        [--binding-id BINDING]
        [--agent-id AGENT]
        [--provider-profile PROFILE]
        [--model MODEL]
        [--override-source SOURCE]
        [--transport-kind KIND]
        [--auth-mode MODE]
        [--execution-owner OWNER]
        [--ingress-request-id ID]
        [--job-id ID]
        [--delivery-id ID]
  override --session-key KEY          Set provider override for a session
        [--provider-profile PROFILE]
        [--model MODEL]
  clear-override --session-key KEY    Remove provider override
  send-policy --session-key KEY       Set delivery mode for a session
        --mode MODE
        [--channel-target TARGET]
  overrides                           List all active overrides
  policies                            List all active send policies

GLOBAL OPTIONS:
  --root ROOT                         Workspace root path
  --format human|json                 Output format (default: human)"
    );
}

fn handle_session_status(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_session_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = format_flag(args);
    let overview = session_provenance_overview(&root)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_session_provenance_overview_human(&overview));
        }
        _ => print!("{}", render_session_provenance_overview_json(&overview)),
    }
    Ok(())
}

fn handle_session_list(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_session_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = format_flag(args);
    let limit = take_value(args, "--limit")
        .and_then(|v| v.parse::<usize>().ok())
        .unwrap_or(20);
    let archived_only = has_flag(args, "--archived-only");
    let include_archived = has_flag(args, "--include-archived");
    let records = if include_archived || archived_only {
        list_session_provenance_with_options(&root, limit, true, archived_only)?
    } else {
        list_session_provenance(&root, limit)?
    };
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_session_provenance_list_human(&records));
        }
        _ => print!("{}", render_session_provenance_list_json(&records)),
    }
    Ok(())
}

fn handle_session_show(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_session_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let session_key = required_flag(args, "--session-key")?;
    let format = format_flag(args);
    let record = find_session_provenance(&root, &session_key)?
        .ok_or_else(|| format!("session '{}' was not found", session_key))?;
    let override_rec = get_session_override(&root, &session_key).ok().flatten();
    let send_policy_rec = get_session_send_policy(&root, &session_key).ok().flatten();
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_session_provenance_human(&record));
            if let Some(ov) = &override_rec {
                print_human("\n[session override]\n");
                print_human(&render_session_override_human(ov));
            }
            if let Some(sp) = &send_policy_rec {
                print_human("\n[send policy]\n");
                print_human(&render_session_send_policy_human(sp));
            }
        }
        _ => {
            use serde_json::json;
            let output = json!({
                "provenance": serde_json::from_str::<serde_json::Value>(&render_session_provenance_json(&record)).unwrap_or_default(),
                "override": override_rec.as_ref().map(|ov| serde_json::from_str::<serde_json::Value>(&render_session_override_json(ov)).unwrap_or_default()),
                "send_policy": send_policy_rec.as_ref().map(|sp| serde_json::from_str::<serde_json::Value>(&render_session_send_policy_json(sp)).unwrap_or_default()),
            });
            print!(
                "{}\n",
                serde_json::to_string_pretty(&output).unwrap_or_default()
            );
        }
    }
    Ok(())
}

fn handle_session_route(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_session_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let session_key = required_flag(args, "--session-key")?;
    let channel_id = take_value(args, "--channel-id").unwrap_or_else(|| {
        session_key
            .split_once(':')
            .map(|(channel, _)| channel.to_string())
            .unwrap_or_default()
    });
    let peer_id = take_value(args, "--peer-id").unwrap_or_else(|| {
        session_key
            .split_once(':')
            .map(|(_, peer)| peer.to_string())
            .unwrap_or_default()
    });
    let binding_id = take_value(args, "--binding-id").unwrap_or_else(|| {
        if channel_id.is_empty() {
            String::new()
        } else {
            format!("binding-{}", channel_id)
        }
    });
    let org_id = take_value(args, "--org-id").unwrap_or_default();
    let agent_id = take_value(args, "--agent-id").unwrap_or_default();
    let provider_profile = take_value(args, "--provider-profile").unwrap_or_default();
    let model = take_value(args, "--model").unwrap_or_default();
    let override_source =
        take_value(args, "--override-source").unwrap_or_else(|| "default".to_string());
    let transport_kind = take_value(args, "--transport-kind").unwrap_or_default();
    let auth_mode = take_value(args, "--auth-mode").unwrap_or_default();
    let execution_owner = take_value(args, "--execution-owner").unwrap_or_default();
    let ingress_request_id = take_value(args, "--ingress-request-id");
    let job_id = take_value(args, "--job-id");
    let delivery_id = take_value(args, "--delivery-id");
    let format = format_flag(args);

    if find_session_provenance(&root, &session_key)?.is_none()
        && !channel_id.is_empty()
        && !peer_id.is_empty()
        && !agent_id.is_empty()
        && !binding_id.is_empty()
    {
        open_session_provenance(
            &root,
            &session_key,
            &channel_id,
            &peer_id,
            &agent_id,
            &binding_id,
        )?;
    }

    update_session_provenance_route_full(
        &root,
        &session_key,
        &provider_profile,
        &model,
        &override_source,
        &transport_kind,
        &auth_mode,
        &execution_owner,
        &org_id,
    )?;
    if ingress_request_id.is_some() || job_id.is_some() || delivery_id.is_some() {
        update_session_provenance_job(
            &root,
            &session_key,
            job_id.as_deref(),
            delivery_id.as_deref(),
            ingress_request_id.as_deref(),
        )?;
    }

    let record = find_session_provenance(&root, &session_key)?
        .ok_or_else(|| format!("session '{}' was not found", session_key))?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_session_provenance_human(&record));
        }
        _ => print!("{}", render_session_provenance_json(&record)),
    }
    Ok(())
}

fn handle_session_override(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_session_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let session_key = required_flag(args, "--session-key")?;
    let provider_profile = take_value(args, "--provider-profile");
    let model = take_value(args, "--model");
    if provider_profile.is_none() && model.is_none() {
        return Err(
            "at least one of --provider-profile or --model is required for session override"
                .to_string(),
        );
    }
    let format = format_flag(args);
    let record = set_session_override(
        &root,
        &session_key,
        provider_profile.as_deref(),
        model.as_deref(),
    )?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_session_override_human(&record));
        }
        _ => print!("{}", render_session_override_json(&record)),
    }
    Ok(())
}

fn handle_session_clear_override(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_session_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let session_key = required_flag(args, "--session-key")?;
    clear_session_override(&root, &session_key)?;
    if std::io::stdout().is_terminal() {
        print_startup_banner();
        print_human(&format!("override cleared for session '{}'\n", session_key));
    } else {
        print!(
            "{{\"status\":\"cleared\",\"session_key\":{:?}}}\n",
            session_key
        );
    }
    Ok(())
}

fn handle_session_send_policy(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_session_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let session_key = required_flag(args, "--session-key")?;
    let mode = required_flag(args, "--mode")?;
    let channel_target = take_value(args, "--channel-target");
    let format = format_flag(args);
    let record = set_session_send_policy(&root, &session_key, &mode, channel_target.as_deref())?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_session_send_policy_human(&record));
        }
        _ => print!("{}", render_session_send_policy_json(&record)),
    }
    Ok(())
}

fn handle_session_overrides_list(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_session_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = format_flag(args);
    let records = list_session_overrides(&root)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_session_overrides_list_human(&records));
        }
        _ => {
            use serde_json::json;
            let out = json!(records
                .iter()
                .map(
                    |r| serde_json::from_str::<serde_json::Value>(&render_session_override_json(r))
                        .unwrap_or_default()
                )
                .collect::<Vec<_>>());
            print!(
                "{}\n",
                serde_json::to_string_pretty(&out).unwrap_or_default()
            );
        }
    }
    Ok(())
}

fn handle_session_policies_list(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_session_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let format = format_flag(args);
    let records = list_session_send_policies(&root)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_session_send_policies_list_human(&records));
        }
        _ => {
            use serde_json::json;
            let out = json!(records
                .iter()
                .map(|r| serde_json::from_str::<serde_json::Value>(
                    &render_session_send_policy_json(r)
                )
                .unwrap_or_default())
                .collect::<Vec<_>>());
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
