use std::io::IsTerminal;

use super::personal_agent::{
    configured_delivery_target, load_personal_agent_config, personal_agent_config_path,
    sync_personal_agent_delivery_channels, webhook_channel_id, write_personal_agent_config,
};
use crate::*;
use loom_core::channels::{
    channel_overview, enqueue_channel_delivery, ingest_channel_message, list_channel_deliveries,
    list_channel_deliveries_with_options, list_channel_health, list_channel_health_history,
    list_channel_ingress, list_channel_test_diagnostics, load_channels,
    record_channel_test_diagnostic, render_channel_delivery_human, render_channel_delivery_json,
    render_channel_delivery_list_human, render_channel_delivery_list_json,
    render_channel_ingress_human, render_channel_ingress_json, render_channel_ingress_list_human,
    render_channel_ingress_list_json, render_channel_list_human, render_channel_list_json,
    render_channel_overview_human, render_channel_overview_json, render_channel_sync_human,
    render_channel_sync_json, sync_channel_registry, update_channel_delivery,
    upsert_channel_record, ChannelDeliveryRequest, ChannelHealthHistoryRecord, ChannelHealthRecord,
    ChannelIngressRequest, ChannelRecord, ChannelTestDiagnosticRecord,
};

pub(crate) fn handle_channel(args: &[String]) -> LoomResult<()> {
    if args.is_empty()
        || matches!(
            args.first().map(String::as_str),
            Some("help" | "--help" | "-h")
        )
    {
        print_channel_help();
        return Ok(());
    }
    match args.first().map(String::as_str) {
        Some("status") => handle_channel_status(&args[1..]),
        Some("sync") => handle_channel_sync(&args[1..]),
        Some("list") => handle_channel_list(&args[1..]),
        Some("health") => handle_channel_health(&args[1..]),
        Some("show") => handle_channel_show(&args[1..]),
        Some("connect") => handle_channel_connect(&args[1..]),
        Some("disconnect") => handle_channel_disconnect(&args[1..]),
        Some("test") => handle_channel_test(&args[1..]),
        Some("send") => handle_channel_send(&args[1..]),
        Some("deliveries") => handle_channel_deliveries(&args[1..]),
        Some("update") => handle_channel_update(&args[1..]),
        Some("ingest") => handle_channel_ingest(&args[1..]),
        Some("inbox") => handle_channel_inbox(&args[1..]),
        _ => Err("channel supports 'status', 'sync', 'list', 'health', 'show', 'connect', 'disconnect', 'test', 'send', 'deliveries', 'update', 'ingest', and 'inbox'".to_string()),
    }
}

fn print_channel_help() {
    println!(
        "Meridian Loom // CHANNEL

Manage live channel ingress and delivery ledgers.

USAGE: loom channel <COMMAND> [OPTIONS]

COMMANDS:
  status                              Show channel runtime overview
  sync                                Sync channel registry from onboarding state
  list [--agent NAME]                 List known channel records
  health [--agent NAME]               Show operator-facing channel health
         [--history-limit N]          Include recent health transitions (default: 5)
         [--diagnostic-limit N]       Include recent test diagnostics (default: 3)
  show --agent NAME                   Show configured personal-agent delivery channels
  connect telegram --agent NAME       Connect Telegram delivery for a personal agent
          --chat-id ID [--token-env ENV]
  connect webhook --agent NAME        Connect webhook delivery for a personal agent
          --url URL [--header TEXT]
  disconnect telegram --agent NAME    Disable Telegram delivery for a personal agent
  disconnect webhook --agent NAME     Disable webhook delivery for a personal agent
  test --agent NAME [--text TEXT]     Queue a delivery on the agent's primary channel
  send --channel ID --recipient ID    Queue outbound delivery
       [--text TEXT|--file PATH]
       [--allow-receipt-hashes]
       [--allow-operator-diagnostics]
  deliveries [--limit N]              List active channel deliveries
             [--include-archived]     Include active + archived historical records
             [--archived-only]        Show only archived historical records
  update --delivery-id ID --status STATUS
         [--external-ref REF]
         [--detail TEXT]
  ingest --channel ID --peer ID       Materialize inbound channel message
         [--thread ID]
         [--agent-id ID]
         [--text TEXT|--file PATH]
  inbox [--limit N]                   List inbound channel records

GLOBAL OPTIONS:
  --root ROOT                         Workspace root path
  --format human|json                 Output format (default: human)"
    );
}

fn handle_channel_status(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_channel_help();
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
    let summary = channel_overview(&root)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_channel_overview_human(&summary));
        }
        _ => print!("{}", render_channel_overview_json(&summary)),
    }
    Ok(())
}

fn handle_channel_sync(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_channel_help();
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
    let summary = sync_channel_registry(&root)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_channel_sync_human(&summary));
        }
        _ => print!("{}", render_channel_sync_json(&summary)),
    }
    Ok(())
}

fn handle_channel_list(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_channel_help();
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
    let mut records = load_channels(&root)?;
    if let Some(agent) = take_value(args, "--agent") {
        let config = load_personal_agent_config(&agent)?;
        records = filter_channel_records_for_agent(records, &config);
    }
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_channel_list_human(&records));
        }
        _ => print!("{}", render_channel_list_json(&records)),
    }
    Ok(())
}

fn handle_channel_health(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_channel_help();
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
    let history_limit = take_value(args, "--history-limit")
        .and_then(|raw| raw.parse::<usize>().ok())
        .unwrap_or(5);
    let diagnostic_limit = take_value(args, "--diagnostic-limit")
        .and_then(|raw| raw.parse::<usize>().ok())
        .unwrap_or(3);
    let mut records = list_channel_health(&root)?;
    if let Some(agent) = take_value(args, "--agent") {
        let config = load_personal_agent_config(&agent)?;
        records = filter_channel_health_for_agent(records, &config);
    }
    let enriched = records
        .iter()
        .map(|record| {
            let history = list_channel_health_history(&root, &record.channel_id, history_limit)?;
            let diagnostics =
                list_channel_test_diagnostics(&root, &record.channel_id, diagnostic_limit)?;
            Ok((record.clone(), history, diagnostics))
        })
        .collect::<LoomResult<Vec<_>>>()?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_channel_health_surface_human(&enriched));
        }
        _ => print!("{}", render_channel_health_surface_json(&enriched)?),
    }
    Ok(())
}

fn handle_channel_show(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_channel_help();
        return Ok(());
    }
    let agent = required_flag(args, "--agent")?;
    let config = load_personal_agent_config(&agent)?;
    let root = root_from(Some(&config.loom_root))?;
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let payload = serde_json::json!({
        "name": config.display_name,
        "slug": config.slug,
        "agent_id": config.agent_id,
        "loom_root": config.loom_root,
        "config_path": personal_agent_config_path(&config.slug)?.display().to_string(),
        "telegram": {
            "enabled": config.telegram_enabled,
            "chat_id": config.telegram_chat_id,
            "token_env": config.telegram_token_env,
        },
        "webhook": {
            "enabled": config.webhook_enabled,
            "channel_id": webhook_channel_id(&config.slug),
            "url": config.webhook_url,
            "header": config.webhook_header,
        },
        "primary_delivery_target": configured_delivery_target(&config).map(|target| serde_json::json!({
            "channel_id": target.channel_id,
            "recipient": target.recipient,
            "allow_receipt_hashes": target.allow_receipt_hashes,
            "allow_operator_diagnostics": target.allow_operator_diagnostics,
        })),
        "channel_registry_path": loom_core::channels::channel_registry_path(&root).display().to_string(),
    });
    match format.as_str() {
        "json" => print!(
            "{}\n",
            serde_json::to_string_pretty(&payload).map_err(|error| error.to_string())?
        ),
        _ => {
            print_startup_banner();
            print_human(&format!(
                "Meridian Loom // CHANNEL SHOW\n=============================\nname:              {}\nslug:              {}\nagent_id:          {}\nconfig_path:       {}\ntelegram_enabled:  {}\ntelegram_chat_id:  {}\ntelegram_token_env:{}\nwebhook_enabled:   {}\nwebhook_channel_id:{}\nwebhook_url:       {}\nprimary_target:    {}\nregistry_path:     {}\n",
                payload["name"].as_str().unwrap_or(""),
                payload["slug"].as_str().unwrap_or(""),
                payload["agent_id"].as_str().unwrap_or(""),
                payload["config_path"].as_str().unwrap_or(""),
                payload["telegram"]["enabled"].as_bool().unwrap_or(false),
                payload["telegram"]["chat_id"].as_str().unwrap_or(""),
                payload["telegram"]["token_env"].as_str().unwrap_or(""),
                payload["webhook"]["enabled"].as_bool().unwrap_or(false),
                payload["webhook"]["channel_id"].as_str().unwrap_or(""),
                payload["webhook"]["url"].as_str().unwrap_or(""),
                payload.get("primary_delivery_target")
                    .and_then(|value| value.get("channel_id"))
                    .and_then(serde_json::Value::as_str)
                    .unwrap_or("none"),
                payload["channel_registry_path"].as_str().unwrap_or(""),
            ));
        }
    }
    Ok(())
}

fn handle_channel_connect(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_channel_help();
        return Ok(());
    }
    let Some(kind) = args.first().map(String::as_str) else {
        return Err("channel connect requires 'telegram' or 'webhook'".to_string());
    };
    let agent = required_flag(&args[1..], "--agent")?;
    let mut config = load_personal_agent_config(&agent)?;
    let root = root_from(Some(&config.loom_root))?;
    let format = take_value(&args[1..], "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    match kind {
        "telegram" => {
            config.telegram_enabled = true;
            config.telegram_chat_id = required_flag(&args[1..], "--chat-id")?;
            if let Some(token_env) = take_value(&args[1..], "--token-env") {
                config.telegram_token_env = token_env;
            }
        }
        "webhook" => {
            config.webhook_enabled = true;
            config.webhook_url = required_flag(&args[1..], "--url")?;
            config.webhook_header = take_value(&args[1..], "--header").unwrap_or_default();
        }
        other => return Err(format!("unsupported channel connect target '{}'", other)),
    }
    write_personal_agent_config(&personal_agent_config_path(&config.slug)?, &config)?;
    sync_personal_agent_delivery_channels(&root, &config)?;
    render_channel_connect_result("connect", kind, &config, &format)
}

fn handle_channel_disconnect(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_channel_help();
        return Ok(());
    }
    let Some(kind) = args.first().map(String::as_str) else {
        return Err("channel disconnect requires 'telegram' or 'webhook'".to_string());
    };
    let agent = required_flag(&args[1..], "--agent")?;
    let mut config = load_personal_agent_config(&agent)?;
    let root = root_from(Some(&config.loom_root))?;
    let format = take_value(&args[1..], "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    match kind {
        "telegram" => {
            config.telegram_enabled = false;
            config.telegram_chat_id.clear();
        }
        "webhook" => {
            config.webhook_enabled = false;
            config.webhook_url.clear();
            config.webhook_header.clear();
            upsert_channel_record(
                &root,
                &ChannelRecord {
                    channel_id: webhook_channel_id(&config.slug),
                    kind: "webhook".to_string(),
                    enabled: false,
                    endpoint: String::new(),
                    auth_mode: "none".to_string(),
                    credential_ref: String::new(),
                    dm_policy: "per-agent".to_string(),
                    group_policy: String::new(),
                    streaming: "async".to_string(),
                    note: format!("personal_agent={} status=disabled", config.slug),
                },
            )?;
        }
        other => return Err(format!("unsupported channel disconnect target '{}'", other)),
    }
    write_personal_agent_config(&personal_agent_config_path(&config.slug)?, &config)?;
    sync_personal_agent_delivery_channels(&root, &config)?;
    render_channel_connect_result("disconnect", kind, &config, &format)
}

fn handle_channel_test(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_channel_help();
        return Ok(());
    }
    let agent = required_flag(args, "--agent")?;
    let config = load_personal_agent_config(&agent)?;
    let root = root_from(Some(&config.loom_root))?;
    let Some(target) = configured_delivery_target(&config) else {
        return Err("personal agent has no configured delivery channel".to_string());
    };
    let text = take_value(args, "--text").unwrap_or_else(|| {
        format!(
            "Loom channel test for {}. Governed delivery path is wired.",
            config.display_name
        )
    });
    let record = enqueue_channel_delivery(
        &root,
        &ChannelDeliveryRequest {
            channel_id: target.channel_id,
            recipient: target.recipient,
            raw_text: text,
            allow_receipt_hashes: true,
            allow_operator_diagnostics: false,
        },
    )?;
    let diagnostic = record_channel_test_diagnostic(
        &root,
        &record,
        "queued from loom channel test; downstream channel acknowledgement may still be pending",
    )?;
    let diagnostic_path =
        loom_core::channels::channel_test_diagnostic_path(&root, &record.delivery_id)
            .display()
            .to_string();
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let payload = serde_json::json!({
        "delivery": serde_json::from_str::<serde_json::Value>(&render_channel_delivery_json(&record))
            .unwrap_or_else(|_| serde_json::json!({})),
        "diagnostic": {
            "diagnostic_id": diagnostic.diagnostic_id,
            "status": diagnostic.status,
            "health": diagnostic.health,
            "ready": diagnostic.ready,
            "status_detail": diagnostic.status_detail,
            "note": diagnostic.note,
            "path": diagnostic_path,
        }
    });
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&format!(
                "{}\ndiagnostic_id:     {}\ndiagnostic_status: {}\ndiagnostic_health: {}\ndiagnostic_ready:  {}\ndiagnostic_detail: {}\ndiagnostic_note:   {}\ndiagnostic_path:   {}\n",
                render_channel_delivery_human(&record).trim_end(),
                payload["diagnostic"]["diagnostic_id"].as_str().unwrap_or(""),
                payload["diagnostic"]["status"].as_str().unwrap_or(""),
                payload["diagnostic"]["health"].as_str().unwrap_or(""),
                payload["diagnostic"]["ready"].as_bool().unwrap_or(false),
                payload["diagnostic"]["status_detail"].as_str().unwrap_or(""),
                payload["diagnostic"]["note"].as_str().unwrap_or(""),
                payload["diagnostic"]["path"].as_str().unwrap_or(""),
            ));
        }
        _ => print!(
            "{}\n",
            serde_json::to_string_pretty(&payload).map_err(|error| error.to_string())?
        ),
    }
    Ok(())
}

fn render_channel_connect_result(
    action: &str,
    kind: &str,
    config: &super::personal_agent::PersonalAgentConfig,
    format: &str,
) -> LoomResult<()> {
    let payload = serde_json::json!({
        "status": "ok",
        "action": action,
        "channel_kind": kind,
        "name": config.display_name,
        "slug": config.slug,
        "agent_id": config.agent_id,
        "primary_delivery_target": configured_delivery_target(config).map(|target| serde_json::json!({
            "channel_id": target.channel_id,
            "recipient": target.recipient,
        })),
        "config_path": personal_agent_config_path(&config.slug)?.display().to_string(),
    });
    match format {
        "json" => print!(
            "{}\n",
            serde_json::to_string_pretty(&payload).map_err(|error| error.to_string())?
        ),
        _ => {
            print_startup_banner();
            print_human(&format!(
                "Meridian Loom // CHANNEL {}\n=============================\nname:              {}\nslug:              {}\nagent_id:          {}\nchannel_kind:      {}\nprimary_target:    {}\nconfig_path:       {}\n",
                action.to_ascii_uppercase(),
                payload["name"].as_str().unwrap_or(""),
                payload["slug"].as_str().unwrap_or(""),
                payload["agent_id"].as_str().unwrap_or(""),
                payload["channel_kind"].as_str().unwrap_or(""),
                payload.get("primary_delivery_target")
                    .and_then(|value| value.get("channel_id"))
                    .and_then(serde_json::Value::as_str)
                    .unwrap_or("none"),
                payload["config_path"].as_str().unwrap_or(""),
            ));
        }
    }
    Ok(())
}

fn filter_channel_records_for_agent(
    records: Vec<ChannelRecord>,
    config: &super::personal_agent::PersonalAgentConfig,
) -> Vec<ChannelRecord> {
    let channel_ids = agent_channel_ids(config);
    records
        .into_iter()
        .filter(|record| channel_ids.iter().any(|id| id == &record.channel_id))
        .collect()
}

fn filter_channel_health_for_agent(
    records: Vec<ChannelHealthRecord>,
    config: &super::personal_agent::PersonalAgentConfig,
) -> Vec<ChannelHealthRecord> {
    let channel_ids = agent_channel_ids(config);
    records
        .into_iter()
        .filter(|record| channel_ids.iter().any(|id| id == &record.channel_id))
        .collect()
}

fn agent_channel_ids(config: &super::personal_agent::PersonalAgentConfig) -> Vec<String> {
    let mut channel_ids = Vec::new();
    if config.telegram_enabled {
        channel_ids.push("telegram".to_string());
    }
    if config.webhook_enabled {
        channel_ids.push(webhook_channel_id(&config.slug));
    }
    if let Some(target) = configured_delivery_target(config) {
        if !channel_ids.iter().any(|id| id == &target.channel_id) {
            channel_ids.push(target.channel_id);
        }
    }
    channel_ids
}

fn render_channel_health_surface_human(
    records: &[(
        ChannelHealthRecord,
        Vec<ChannelHealthHistoryRecord>,
        Vec<ChannelTestDiagnosticRecord>,
    )],
) -> String {
    if records.is_empty() {
        return "channel_health_count: 0\n".to_string();
    }
    let mut rendered = format!("channel_health_count: {}\n", records.len());
    for (record, history, diagnostics) in records {
        rendered.push_str(&format!(
            "\n- {} kind={} health={} ready={} latest={} queued={} delivered={} failed={} blocked={} archived={} detail={}\n",
            record.channel_id,
            record.kind,
            record.health,
            record.ready,
            record.latest_delivery_status,
            record.queued_count,
            record.delivered_count,
            record.failed_count,
            record.blocked_count,
            record.archived_delivery_count,
            record.status_detail.replace('\n', "\\n"),
        ));
        rendered.push_str("  history:\n");
        if history.is_empty() {
            rendered.push_str("    (none)\n");
        } else {
            for item in history {
                rendered.push_str(&format!(
                    "    - at={} trigger={} health={} ready={} latest={} detail={}\n",
                    item.captured_at_unix_ms,
                    item.trigger,
                    item.health,
                    item.ready,
                    item.latest_delivery_status,
                    item.status_detail.replace('\n', "\\n"),
                ));
            }
        }
        rendered.push_str("  diagnostics:\n");
        if diagnostics.is_empty() {
            rendered.push_str("    (none)\n");
        } else {
            for item in diagnostics {
                rendered.push_str(&format!(
                    "    - {} status={} health={} ready={} updated_at={} note={} detail={}\n",
                    item.diagnostic_id,
                    item.status,
                    item.health,
                    item.ready,
                    item.updated_at_unix_ms,
                    item.note.replace('\n', "\\n"),
                    item.status_detail.replace('\n', "\\n"),
                ));
            }
        }
    }
    rendered
}

fn render_channel_health_surface_json(
    records: &[(
        ChannelHealthRecord,
        Vec<ChannelHealthHistoryRecord>,
        Vec<ChannelTestDiagnosticRecord>,
    )],
) -> LoomResult<String> {
    let payload = records
        .iter()
        .map(|(record, history, diagnostics)| {
            serde_json::json!({
                "channel_id": record.channel_id,
                "kind": record.kind,
                "enabled": record.enabled,
                "ready": record.ready,
                "health": record.health,
                "status_detail": record.status_detail,
                "endpoint": record.endpoint,
                "latest_delivery_status": record.latest_delivery_status,
                "latest_delivery_at_unix_ms": record.latest_delivery_at_unix_ms,
                "queued_count": record.queued_count,
                "delivered_count": record.delivered_count,
                "failed_count": record.failed_count,
                "blocked_count": record.blocked_count,
                "archived_delivery_count": record.archived_delivery_count,
                "history": history.iter().map(|item| serde_json::json!({
                    "captured_at_unix_ms": item.captured_at_unix_ms,
                    "trigger": item.trigger,
                    "health": item.health,
                    "ready": item.ready,
                    "status_detail": item.status_detail,
                    "latest_delivery_status": item.latest_delivery_status,
                    "latest_delivery_at_unix_ms": item.latest_delivery_at_unix_ms,
                    "queued_count": item.queued_count,
                    "delivered_count": item.delivered_count,
                    "failed_count": item.failed_count,
                    "blocked_count": item.blocked_count,
                    "archived_delivery_count": item.archived_delivery_count,
                })).collect::<Vec<_>>(),
                "diagnostics": diagnostics.iter().map(|item| serde_json::json!({
                    "diagnostic_id": item.diagnostic_id,
                    "delivery_id": item.delivery_id,
                    "recipient": item.recipient,
                    "submitted_at_unix_ms": item.submitted_at_unix_ms,
                    "updated_at_unix_ms": item.updated_at_unix_ms,
                    "status": item.status,
                    "ready": item.ready,
                    "health": item.health,
                    "status_detail": item.status_detail,
                    "note": item.note,
                })).collect::<Vec<_>>(),
            })
        })
        .collect::<Vec<_>>();
    Ok(format!(
        "{}\n",
        serde_json::to_string_pretty(&payload).map_err(|error| error.to_string())?
    ))
}

fn handle_channel_send(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_channel_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let channel_id = required_flag(args, "--channel")?;
    let recipient = required_flag(args, "--recipient")?;
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
    let record = enqueue_channel_delivery(
        &root,
        &ChannelDeliveryRequest {
            channel_id,
            recipient,
            raw_text: text,
            allow_receipt_hashes: has_flag(args, "--allow-receipt-hashes"),
            allow_operator_diagnostics: has_flag(args, "--allow-operator-diagnostics"),
        },
    )?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_channel_delivery_human(&record));
        }
        _ => print!("{}", render_channel_delivery_json(&record)),
    }
    Ok(())
}

fn handle_channel_deliveries(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_channel_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let limit = take_value(args, "--limit")
        .and_then(|raw| raw.parse::<usize>().ok())
        .unwrap_or(20);
    let archived_only = has_flag(args, "--archived-only");
    let include_archived = has_flag(args, "--include-archived");
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let records = if include_archived || archived_only {
        list_channel_deliveries_with_options(&root, limit, true, archived_only)?
    } else {
        list_channel_deliveries(&root, limit)?
    };
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_channel_delivery_list_human(&records));
        }
        _ => print!("{}", render_channel_delivery_list_json(&records)),
    }
    Ok(())
}

fn handle_channel_update(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_channel_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let delivery_id = required_flag(args, "--delivery-id")?;
    let status = required_flag(args, "--status")?;
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let record = update_channel_delivery(
        &root,
        &delivery_id,
        &status,
        take_value(args, "--external-ref").as_deref(),
        take_value(args, "--detail").as_deref(),
    )?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_channel_delivery_human(&record));
        }
        _ => print!("{}", render_channel_delivery_json(&record)),
    }
    Ok(())
}

fn handle_channel_ingest(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_channel_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let channel_id = required_flag(args, "--channel")?;
    let peer_id = required_flag(args, "--peer")?;
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
    let record = ingest_channel_message(
        &root,
        &ChannelIngressRequest {
            channel_id,
            peer_id,
            thread_id: take_value(args, "--thread"),
            text,
            agent_override: take_value(args, "--agent-id"),
        },
    )?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_channel_ingress_human(&record));
        }
        _ => print!("{}", render_channel_ingress_json(&record)),
    }
    Ok(())
}

fn handle_channel_inbox(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_channel_help();
        return Ok(());
    }
    let root = root_from(take_value(args, "--root").as_deref())?;
    let limit = take_value(args, "--limit")
        .and_then(|raw| raw.parse::<usize>().ok())
        .unwrap_or(20);
    let format = take_value(args, "--format").unwrap_or_else(|| {
        if std::io::stdout().is_terminal() {
            "human".to_string()
        } else {
            "json".to_string()
        }
    });
    let records = list_channel_ingress(&root, limit)?;
    match format.as_str() {
        "human" => {
            print_startup_banner();
            print_human(&render_channel_ingress_list_human(&records));
        }
        _ => print!("{}", render_channel_ingress_list_json(&records)),
    }
    Ok(())
}
