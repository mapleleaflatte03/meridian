use std::collections::BTreeMap;
use std::env;
use std::fs;
#[cfg(unix)]
use std::os::unix::process::ExitStatusExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use crate::*;
use loom_core::agent_runtime::{
    open_agent_session, upsert_agent_runtime_profile, write_agent_memory_snapshot,
    AgentRuntimeProfile,
};
use loom_core::channels::{
    self, ChannelDeliveryRecord, ChannelHealthHistoryRecord, ChannelHealthRecord, ChannelRecord,
    ChannelTestDiagnosticRecord,
};
use loom_core::memory_service::MemoryService;
use loom_core::onboarding;
use loom_core::recurring::{self, HeartbeatDeliveryTarget, HeartbeatScheduleRequest};
use loom_core::recurring_executor::dispatch_heartbeat_run;
use loom_core::{init_workspace, read_config};

const DEFAULT_PERSONAL_PROVIDER_PROFILE: &str = "local_ollama";
const DEFAULT_PERSONAL_TOOL_SCOPE: &str = "personal_agent_scope";
const DEFAULT_PERSONAL_ROLE: &str = "manager";
const DEFAULT_PERSONAL_HEARTBEAT_CAPABILITY: &str = "loom.system.info.v1";
const DEFAULT_PERSONAL_HEARTBEAT_SECONDS: u64 = 300;
const DEFAULT_TELEGRAM_TOKEN_ENV: &str = "MERIDIAN_TELEGRAM_BOT_TOKEN";
const DEFAULT_PERSONAL_RESTART_POLICY: &str = "manual";
const DEFAULT_PERSONAL_RESTART_BACKOFF_SECONDS: u64 = 30;
const PERSONAL_AGENT_CHAOS_ENV: &str = "MERIDIAN_LOOM_AGENT_CHAOS";
const PERSONAL_AGENT_TEMPLATE_README: &str =
    include_str!("../../../../templates/personal-agent/README.md");
const PERSONAL_AGENT_TEMPLATE_MEMORY: &str =
    include_str!("../../../../templates/personal-agent/MEMORY.md");
const PERSONAL_AGENT_TEMPLATE_SOUL: &str =
    include_str!("../../../../templates/personal-agent/SOUL.md");

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct PersonalAgentConfig {
    pub(crate) name: String,
    pub(crate) slug: String,
    pub(crate) agent_id: String,
    pub(crate) display_name: String,
    pub(crate) role: String,
    pub(crate) purpose: String,
    pub(crate) provider_profile: String,
    pub(crate) tool_scope: String,
    pub(crate) org_id: String,
    pub(crate) loom_root: String,
    pub(crate) kernel_path: String,
    pub(crate) service_http_address: String,
    pub(crate) service_token: String,
    pub(crate) heartbeat_capability: String,
    pub(crate) heartbeat_every_seconds: u64,
    pub(crate) restart_policy: String,
    pub(crate) restart_backoff_seconds: u64,
    pub(crate) telegram_enabled: bool,
    pub(crate) telegram_chat_id: String,
    pub(crate) telegram_token_env: String,
    pub(crate) webhook_enabled: bool,
    pub(crate) webhook_url: String,
    pub(crate) webhook_header: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct PersonalAgentLoopState {
    slug: String,
    agent_id: String,
    pid: u32,
    status: String,
    launched_at_unix_ms: u64,
    updated_at_unix_ms: u64,
    last_run_status: String,
    last_tick_unix_ms: u64,
    heartbeat_id: String,
    log_path: String,
    last_memory_sync_unix_ms: u64,
    memory_entries_recalled: usize,
    memory_entries_updated: usize,
    primary_channel_id: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
struct PersonalAgentMemorySyncState {
    config_hash: String,
    soul_hash: String,
    memory_hash: String,
    last_sync_unix_ms: u64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
struct PersonalAgentMemorySyncResult {
    changed_count: usize,
    recalled_count: usize,
    sync_state: PersonalAgentMemorySyncState,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct PersonalAgentRunPolicy {
    desired_state: String,
    restart_policy: String,
    restart_backoff_seconds: u64,
    failure_count: u64,
    last_exit_unix_ms: u64,
    next_restart_after_unix_ms: u64,
    last_exit_status: String,
    supervisor_pid: u32,
    current_worker_pid: u32,
    last_crash_unix_ms: u64,
    last_crash_reason: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct PersonalAgentChaosDirective {
    phase: String,
    mode: String,
    exit_code: i32,
}

type PersonalAgentChannelSurface = (
    ChannelHealthRecord,
    Vec<ChannelHealthHistoryRecord>,
    Vec<ChannelTestDiagnosticRecord>,
);

pub(crate) fn handle_new_agent(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_new_agent_help();
        return Ok(());
    }

    let root = root_from(take_value(args, "--root").as_deref())?;
    let display_name = required_flag(args, "--name")?;
    let slug = sanitize_personal_slug(&display_name);
    if slug.is_empty() {
        return Err("agent name must produce a non-empty slug".to_string());
    }
    let config_path = personal_agent_config_path(&slug)?;
    if config_path.exists() {
        return Err(format!(
            "personal agent config already exists at {}",
            config_path.display()
        ));
    }

    let requested_kernel_path = take_value(args, "--kernel-path").or_else(default_kernel_path);
    let requested_org_id = take_value(args, "--org-id");
    let runtime_config = ensure_runtime_initialized(
        &root,
        requested_kernel_path.as_deref(),
        requested_org_id.as_deref(),
    )?;
    let kernel_path = kernel_path_for(&root, requested_kernel_path.as_deref())?;
    let org_id = requested_org_id.unwrap_or_else(|| runtime_config.org_id.clone());
    let role = take_value(args, "--role").unwrap_or_else(|| DEFAULT_PERSONAL_ROLE.to_string());
    let purpose = take_value(args, "--purpose")
        .unwrap_or_else(|| format!("Governed personal agent for {}", display_name.trim()));
    let provider_profile = take_value(args, "--provider-profile")
        .unwrap_or_else(|| DEFAULT_PERSONAL_PROVIDER_PROFILE.to_string());
    let tool_scope =
        take_value(args, "--tool-scope").unwrap_or_else(|| DEFAULT_PERSONAL_TOOL_SCOPE.to_string());
    let telegram_chat_id = take_value(args, "--telegram-chat-id").unwrap_or_default();
    let webhook_url = take_value(args, "--webhook-url").unwrap_or_default();
    let webhook_header = take_value(args, "--webhook-header").unwrap_or_default();
    let service_token = format!("loom-agent-{}-{}", slug, chrono_like_timestamp());

    let agent_id = register_kernel_agent(
        &kernel_path,
        &org_id,
        display_name.trim(),
        role.trim(),
        purpose.trim(),
        &provider_profile,
    )?;

    let profile = AgentRuntimeProfile {
        agent_id: agent_id.clone(),
        display_name: display_name.trim().to_string(),
        role: role.trim().to_string(),
        workspace_root: format!("agents/personal/{}/workspace", slug),
        memory_root: format!("agents/personal/{}/memory", slug),
        session_root: format!("agents/personal/{}/sessions", slug),
        provider_profile: provider_profile.clone(),
        tool_scope: tool_scope.clone(),
        heartbeat_policy: "persistent".to_string(),
    };
    let _ = upsert_agent_runtime_profile(&root, &profile)?;

    let config = PersonalAgentConfig {
        name: display_name.trim().to_string(),
        slug: slug.clone(),
        agent_id: agent_id.clone(),
        display_name: display_name.trim().to_string(),
        role: role.trim().to_string(),
        purpose: purpose.trim().to_string(),
        provider_profile,
        tool_scope,
        org_id,
        loom_root: root.display().to_string(),
        kernel_path: kernel_path.display().to_string(),
        service_http_address: runtime_config.service_http_address.clone(),
        service_token,
        heartbeat_capability: DEFAULT_PERSONAL_HEARTBEAT_CAPABILITY.to_string(),
        heartbeat_every_seconds: DEFAULT_PERSONAL_HEARTBEAT_SECONDS,
        restart_policy: DEFAULT_PERSONAL_RESTART_POLICY.to_string(),
        restart_backoff_seconds: DEFAULT_PERSONAL_RESTART_BACKOFF_SECONDS,
        telegram_enabled: !telegram_chat_id.trim().is_empty(),
        telegram_chat_id,
        telegram_token_env: DEFAULT_TELEGRAM_TOKEN_ENV.to_string(),
        webhook_enabled: !webhook_url.trim().is_empty(),
        webhook_url,
        webhook_header,
    };
    write_personal_agent_config(&config_path, &config)?;
    write_personal_agent_support_files(&config_path, &config)?;
    seed_personal_agent_memory(&root, &config)?;
    let _ = open_agent_session(&root, &agent_id, Some("personal_agent"))?;

    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    match format.as_str() {
        "json" => {
            print!(
                "{}",
                serde_json::to_string_pretty(&serde_json::json!({
                    "status": "created",
                    "name": config.name,
                    "slug": config.slug,
                    "agent_id": config.agent_id,
                    "runtime_root": config.loom_root,
                    "kernel_path": config.kernel_path,
                    "config_path": config_path.display().to_string(),
                    "agent_dir": config_path.parent().map(|path| path.display().to_string()).unwrap_or_default(),
                    "next_steps": [
                        format!("loom run-agent {}", config.slug),
                        format!("loom agent runtime --root {} --agent-id {}", config.loom_root, config.agent_id),
                        format!("cat {}/SOUL.md", config_path.parent().map(|path| path.display().to_string()).unwrap_or_default()),
                    ],
                }))
                .map_err(|error| error.to_string())?
            );
            println!();
        }
        _ => {
            print_startup_banner();
            print_human(&format!(
                "Meridian Loom // NEW AGENT\n==========================\nname:         {}\nslug:         {}\nagent_id:     {}\norg_id:       {}\nruntime_root: {}\nkernel_path:  {}\nconfig_path:  {}\nagent_dir:    {}\nstatus:       governed personal agent provisioned\n\nNext\n----\n1. loom run-agent {}\n2. loom agent runtime --root \"{}\" --agent-id {}\n3. loom memory search --root \"{}\" --agent-id {} --category profile\n4. edit \"{}/SOUL.md\" and \"{}/MEMORY.md\"\n",
                config.display_name,
                config.slug,
                config.agent_id,
                config.org_id,
                config.loom_root,
                config.kernel_path,
                config_path.display(),
                config_path.parent().map(|path| path.display().to_string()).unwrap_or_default(),
                config.slug,
                config.loom_root,
                config.agent_id,
                config.loom_root,
                config.agent_id,
                config_path.parent().map(|path| path.display().to_string()).unwrap_or_default(),
                config_path.parent().map(|path| path.display().to_string()).unwrap_or_default(),
            ));
        }
    }
    Ok(())
}

pub(crate) fn handle_run_agent(args: &[String]) -> LoomResult<()> {
    if has_flag(args, "--help") || has_flag(args, "-h") {
        print_run_agent_help();
        return Ok(());
    }

    match args.first().map(String::as_str) {
        Some("status") => return handle_run_agent_status(&args[1..]),
        Some("inspect") => return handle_run_agent_inspect(&args[1..]),
        Some("diagnose") => return handle_run_agent_diagnose(&args[1..]),
        Some("watch") => return handle_run_agent_watch(&args[1..]),
        Some("stop") => return handle_run_agent_stop(&args[1..]),
        Some("reconcile") => return handle_run_agent_reconcile(&args[1..]),
        Some("supervise") => return handle_run_agent_supervise(&args[1..]),
        _ => {}
    }

    let Some(name_or_slug) = positional_name(args) else {
        return Err("run-agent requires an agent name or slug".to_string());
    };
    let config = load_personal_agent_config(&name_or_slug)?;
    let root = root_from(Some(&config.loom_root))?;
    let loop_log_path = personal_agent_log_path(&root, &config.slug)?;
    let state_path = personal_agent_state_path(&root, &config.slug)?;
    let heartbeat_id = heartbeat_id_for_slug(&config.slug);
    let poll_seconds = take_value(args, "--poll-seconds")
        .and_then(|value| value.parse::<u64>().ok())
        .unwrap_or(15);
    let once = has_flag(args, "--once");
    let foreground = has_flag(args, "--foreground") || has_flag(args, "--loop");
    let supervisor_pid = take_value(args, "--supervisor-pid")
        .and_then(|value| value.parse::<u32>().ok())
        .filter(|pid| *pid > 0);
    let restart_policy = take_value(args, "--restart-policy")
        .map(|value| normalize_restart_policy(&value))
        .unwrap_or_else(|| normalize_restart_policy(&config.restart_policy));
    let restart_backoff_seconds = take_value(args, "--restart-backoff-seconds")
        .and_then(|value| value.parse::<u64>().ok())
        .unwrap_or(config.restart_backoff_seconds)
        .max(1);

    if !foreground {
        let summary = build_run_agent_summary(&root, &config)?;
        if summary["running"].as_bool().unwrap_or(false) {
            print_startup_banner();
            print_human(&format!(
                "Meridian Loom // RUN AGENT\n==========================\nname:         {}\nslug:         {}\nagent_id:     {}\nstatus:       already supervised\nworker_pid:   {}\nsupervisor_pid:{}\nheartbeat_id: {}\nlog_path:     {}\nstate_path:   {}\n",
                config.display_name,
                config.slug,
                config.agent_id,
                summary["worker_pid"].as_u64().unwrap_or_default(),
                summary["supervisor_pid"].as_u64().unwrap_or_default(),
                heartbeat_id,
                loop_log_path.display(),
                state_path.display(),
            ));
            return Ok(());
        }

        let child = spawn_run_agent_supervisor(
            &root,
            &config,
            poll_seconds,
            &restart_policy,
            restart_backoff_seconds,
        )?;
        print_startup_banner();
        print_human(&format!(
            "Meridian Loom // RUN AGENT\n==========================\nname:         {}\nslug:         {}\nagent_id:     {}\nstatus:       supervisor started\nsupervisor_pid:{}\nheartbeat_id: {}\nlog_path:     {}\nstate_path:   {}\nrestart_policy:{}\nrestart_backoff:{}s\n\nNext\n----\n1. tail -f \"{}\"\n2. loom run-agent watch {}\n3. loom run-agent inspect {}\n4. loom run-agent reconcile {}\n",
            config.display_name,
            config.slug,
            config.agent_id,
            child.id(),
            heartbeat_id,
            loop_log_path.display(),
            state_path.display(),
            restart_policy,
            restart_backoff_seconds,
            loop_log_path.display(),
            config.slug,
            config.slug,
            config.slug,
        ));
        return Ok(());
    }

    run_agent_loop(
        &root,
        &config,
        &state_path,
        &loop_log_path,
        &heartbeat_id,
        poll_seconds,
        once,
        supervisor_pid,
    )
}

fn run_agent_loop(
    root: &Path,
    config: &PersonalAgentConfig,
    state_path: &Path,
    log_path: &Path,
    heartbeat_id: &str,
    poll_seconds: u64,
    once: bool,
    _supervisor_pid: Option<u32>,
) -> LoomResult<()> {
    ensure_runtime_ready_for_personal_agent(root, config)?;
    sync_personal_agent_delivery_channels(root, config)?;
    let delivery_target = configured_delivery_target(config);
    ensure_personal_agent_heartbeat(root, config, heartbeat_id, delivery_target)?;
    clear_stop_request(root, &config.slug)?;
    let policy_path = personal_agent_policy_path(root, &config.slug)?;
    let mut run_policy = load_run_policy(&policy_path, config)?;
    let mut memory_sync = sync_personal_agent_memory(root, config)?;
    let _ = open_agent_session(root, &config.agent_id, Some("personal_agent"))?;
    run_policy.last_exit_status = "running".to_string();
    write_run_policy(&policy_path, &run_policy)?;

    loop {
        let now_ms = now_unix_ms();
        if stop_requested(root, &config.slug)? {
            run_policy.last_exit_unix_ms = now_ms;
            run_policy.next_restart_after_unix_ms = 0;
            run_policy.last_exit_status = "stop requested by operator".to_string();
            write_loop_state(
                state_path,
                &PersonalAgentLoopState {
                    slug: config.slug.clone(),
                    agent_id: config.agent_id.clone(),
                    pid: std::process::id(),
                    status: "stopped".to_string(),
                    launched_at_unix_ms: load_loop_state(state_path)?
                        .map(|state| state.launched_at_unix_ms)
                        .unwrap_or(now_ms),
                    updated_at_unix_ms: now_ms,
                    last_run_status: "stop requested by operator".to_string(),
                    last_tick_unix_ms: now_ms,
                    heartbeat_id: heartbeat_id.to_string(),
                    log_path: log_path.display().to_string(),
                    last_memory_sync_unix_ms: memory_sync.sync_state.last_sync_unix_ms,
                    memory_entries_recalled: memory_sync.recalled_count,
                    memory_entries_updated: memory_sync.changed_count,
                    primary_channel_id: configured_delivery_target(config)
                        .map(|target| target.channel_id)
                        .unwrap_or_default(),
                },
            )?;
            write_run_policy(&policy_path, &run_policy)?;
            clear_stop_request(root, &config.slug)?;
            return Ok(());
        }

        let latest_sync = sync_personal_agent_memory(root, config)?;
        if latest_sync.changed_count > 0 || latest_sync.recalled_count > 0 {
            memory_sync = latest_sync;
        }
        maybe_inject_personal_agent_chaos(root, config, log_path, "post_sync")?;
        let due = recurring::claim_due_heartbeats(root, now_ms, 8)?;
        let mut last_status = if due.is_empty() {
            format!(
                "idle; recall_entries={} updated_entries={}",
                memory_sync.recalled_count, memory_sync.changed_count
            )
        } else {
            format!("dispatching {} heartbeat(s)", due.len())
        };
        for record in due {
            let run = dispatch_heartbeat_run(root, &record)?;
            memory_sync = recall_personal_agent_memory(root, config)?;
            last_status = format!("{} => {}", record.heartbeat_id, run.status);
        }
        let _ = loom_core::agent_runtime::commit_agent_session(
            root,
            &config.agent_id,
            Some("active"),
            Some(&format!(
                "personal agent loop active; heartbeat_id={} status={}",
                heartbeat_id, last_status
            )),
            Some("personal_agent"),
        );
        write_loop_state(
            state_path,
            &PersonalAgentLoopState {
                slug: config.slug.clone(),
                agent_id: config.agent_id.clone(),
                pid: std::process::id(),
                status: "running".to_string(),
                launched_at_unix_ms: load_loop_state(state_path)?
                    .map(|state| state.launched_at_unix_ms)
                    .unwrap_or(now_ms),
                updated_at_unix_ms: now_ms,
                last_run_status: last_status.clone(),
                last_tick_unix_ms: now_ms,
                heartbeat_id: heartbeat_id.to_string(),
                log_path: log_path.display().to_string(),
                last_memory_sync_unix_ms: memory_sync.sync_state.last_sync_unix_ms,
                memory_entries_recalled: memory_sync.recalled_count,
                memory_entries_updated: memory_sync.changed_count,
                primary_channel_id: configured_delivery_target(config)
                    .map(|target| target.channel_id)
                    .unwrap_or_default(),
            },
        )?;
        maybe_inject_personal_agent_chaos(root, config, log_path, "after_tick")?;
        if once {
            run_policy.last_exit_unix_ms = now_ms;
            run_policy.last_exit_status = last_status.clone();
            run_policy.next_restart_after_unix_ms =
                if run_policy.restart_policy == "always" && run_policy.desired_state == "running" {
                    now_ms.saturating_add(run_policy.restart_backoff_seconds.saturating_mul(1000))
                } else {
                    0
                };
            write_loop_state(
                state_path,
                &PersonalAgentLoopState {
                    slug: config.slug.clone(),
                    agent_id: config.agent_id.clone(),
                    pid: 0,
                    status: "completed_once".to_string(),
                    launched_at_unix_ms: load_loop_state(state_path)?
                        .map(|state| state.launched_at_unix_ms)
                        .unwrap_or(now_ms),
                    updated_at_unix_ms: now_ms,
                    last_run_status: last_status.clone(),
                    last_tick_unix_ms: now_ms,
                    heartbeat_id: heartbeat_id.to_string(),
                    log_path: log_path.display().to_string(),
                    last_memory_sync_unix_ms: memory_sync.sync_state.last_sync_unix_ms,
                    memory_entries_recalled: memory_sync.recalled_count,
                    memory_entries_updated: memory_sync.changed_count,
                    primary_channel_id: configured_delivery_target(config)
                        .map(|target| target.channel_id)
                        .unwrap_or_default(),
                },
            )?;
            write_run_policy(&policy_path, &run_policy)?;
            return Ok(());
        }
        thread::sleep(Duration::from_secs(poll_seconds.max(5)));
    }
}

fn spawn_run_agent_worker(
    root: &Path,
    config: &PersonalAgentConfig,
    poll_seconds: u64,
) -> LoomResult<std::process::Child> {
    let loop_log_path = personal_agent_log_path(root, &config.slug)?;
    let state_path = personal_agent_state_path(root, &config.slug)?;
    let heartbeat_id = heartbeat_id_for_slug(&config.slug);

    if let Some(parent) = loop_log_path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let stdout = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&loop_log_path)
        .map_err(|error| error.to_string())?;
    let stderr = stdout.try_clone().map_err(|error| error.to_string())?;
    let exe = env::current_exe().map_err(|error| error.to_string())?;
    let mut command = Command::new(exe);
    command
        .arg("run-agent")
        .arg(&config.slug)
        .arg("--foreground")
        .arg("--loop")
        .arg("--poll-seconds")
        .arg(poll_seconds.to_string())
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr));
    let child = command.spawn().map_err(|error| error.to_string())?;
    write_loop_state(
        &state_path,
        &PersonalAgentLoopState {
            slug: config.slug.clone(),
            agent_id: config.agent_id.clone(),
            pid: child.id(),
            status: "starting".to_string(),
            launched_at_unix_ms: now_unix_ms(),
            updated_at_unix_ms: now_unix_ms(),
            last_run_status: "booting".to_string(),
            last_tick_unix_ms: 0,
            heartbeat_id,
            log_path: loop_log_path.display().to_string(),
            last_memory_sync_unix_ms: 0,
            memory_entries_recalled: 0,
            memory_entries_updated: 0,
            primary_channel_id: configured_delivery_target(config)
                .map(|target| target.channel_id)
                .unwrap_or_default(),
        },
    )?;
    Ok(child)
}

fn spawn_run_agent_supervisor(
    root: &Path,
    config: &PersonalAgentConfig,
    poll_seconds: u64,
    restart_policy: &str,
    restart_backoff_seconds: u64,
) -> LoomResult<std::process::Child> {
    let loop_log_path = personal_agent_log_path(root, &config.slug)?;
    let policy_path = personal_agent_policy_path(root, &config.slug)?;
    let mut policy = load_run_policy(&policy_path, config)?;
    policy.desired_state = "running".to_string();
    policy.restart_policy = normalize_restart_policy(restart_policy);
    policy.restart_backoff_seconds = restart_backoff_seconds.max(1);
    policy.next_restart_after_unix_ms = 0;
    policy.supervisor_pid = 0;
    policy.current_worker_pid = 0;
    write_run_policy(&policy_path, &policy)?;

    if let Some(parent) = loop_log_path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let stdout = fs::File::create(&loop_log_path).map_err(|error| error.to_string())?;
    let stderr = stdout.try_clone().map_err(|error| error.to_string())?;
    let exe = env::current_exe().map_err(|error| error.to_string())?;
    let mut command = Command::new(exe);
    command
        .arg("run-agent")
        .arg("supervise")
        .arg(&config.slug)
        .arg("--poll-seconds")
        .arg(poll_seconds.to_string())
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr));
    command.spawn().map_err(|error| error.to_string())
}

fn append_supervisor_log(log_path: &Path, line: &str) -> LoomResult<()> {
    if let Some(parent) = log_path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let mut file = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_path)
        .map_err(|error| error.to_string())?;
    use std::io::Write;
    writeln!(file, "{} :: {}", now_unix_ms(), line).map_err(|error| error.to_string())
}

fn describe_exit_status(status: std::process::ExitStatus) -> String {
    if let Some(code) = status.code() {
        if code == 0 {
            return "worker exited cleanly".to_string();
        }
        return format!("worker exited with code {}", code);
    }
    #[cfg(unix)]
    if let Some(signal) = status.signal() {
        return format!("worker terminated by signal {}", signal);
    }
    "worker exited without status code".to_string()
}

fn run_agent_supervisor_loop(
    root: &Path,
    config: &PersonalAgentConfig,
    poll_seconds: u64,
) -> LoomResult<()> {
    let policy_path = personal_agent_policy_path(root, &config.slug)?;
    let log_path = personal_agent_log_path(root, &config.slug)?;
    let supervisor_pid = std::process::id();
    let mut child: Option<std::process::Child> = None;
    append_supervisor_log(
        &log_path,
        &format!("supervisor starting pid={}", supervisor_pid),
    )?;

    loop {
        let mut policy = load_run_policy(&policy_path, config)?;
        policy.supervisor_pid = supervisor_pid;

        if policy.desired_state != "running" {
            if child.is_none() {
                policy.supervisor_pid = 0;
                policy.current_worker_pid = 0;
                policy.next_restart_after_unix_ms = 0;
                write_run_policy(&policy_path, &policy)?;
                clear_stop_request(root, &config.slug)?;
                append_supervisor_log(&log_path, "supervisor stopped by policy")?;
                return Ok(());
            }
            if !stop_requested(root, &config.slug)? {
                let _ = write_stop_request(root, &config.slug)?;
            }
        }

        if let Some(child_process) = child.as_mut() {
            match child_process
                .try_wait()
                .map_err(|error| error.to_string())?
            {
                Some(status) => {
                    let now_ms = now_unix_ms();
                    let exit_reason = describe_exit_status(status);
                    let unexpected_exit =
                        policy.desired_state == "running" && !stop_requested(root, &config.slug)?;
                    policy.current_worker_pid = 0;
                    policy.last_exit_unix_ms = now_ms;
                    policy.last_exit_status = exit_reason.clone();
                    if unexpected_exit {
                        policy.failure_count = policy.failure_count.saturating_add(1);
                        policy.last_crash_unix_ms = now_ms;
                        policy.last_crash_reason = exit_reason.clone();
                        if policy.restart_policy == "always" {
                            policy.next_restart_after_unix_ms = now_ms.saturating_add(
                                policy.restart_backoff_seconds.saturating_mul(1000),
                            );
                        } else {
                            policy.next_restart_after_unix_ms = 0;
                        }
                    } else {
                        policy.next_restart_after_unix_ms = 0;
                    }
                    write_run_policy(&policy_path, &policy)?;
                    append_supervisor_log(
                        &log_path,
                        &format!(
                            "worker exit unexpected={} reason={}",
                            unexpected_exit, exit_reason
                        ),
                    )?;
                    child = None;
                    if policy.desired_state != "running" {
                        continue;
                    }
                    if policy.restart_policy != "always" {
                        policy.supervisor_pid = 0;
                        write_run_policy(&policy_path, &policy)?;
                        append_supervisor_log(
                            &log_path,
                            "manual policy leaves crashed worker stopped",
                        )?;
                        return Ok(());
                    }
                }
                None => {
                    policy.current_worker_pid = child_process.id();
                    write_run_policy(&policy_path, &policy)?;
                    thread::sleep(Duration::from_secs(poll_seconds.min(5).max(1)));
                    continue;
                }
            }
        }

        let policy = load_run_policy(&policy_path, config)?;
        if policy.desired_state != "running" {
            continue;
        }
        let now_ms = now_unix_ms();
        if policy.next_restart_after_unix_ms > now_ms {
            thread::sleep(Duration::from_secs(1));
            continue;
        }

        clear_stop_request(root, &config.slug)?;
        let new_child = spawn_run_agent_worker(root, config, poll_seconds)?;
        let mut policy = load_run_policy(&policy_path, config)?;
        policy.supervisor_pid = supervisor_pid;
        policy.current_worker_pid = new_child.id();
        policy.last_exit_status = "worker running".to_string();
        write_run_policy(&policy_path, &policy)?;
        append_supervisor_log(&log_path, &format!("worker spawned pid={}", new_child.id()))?;
        child = Some(new_child);
        thread::sleep(Duration::from_secs(1));
    }
}

fn build_run_agent_summary(
    root: &Path,
    config: &PersonalAgentConfig,
) -> LoomResult<serde_json::Value> {
    let state_path = personal_agent_state_path(root, &config.slug)?;
    let stop_path = personal_agent_stop_request_path(root, &config.slug)?;
    let policy_path = personal_agent_policy_path(root, &config.slug)?;
    let state = load_loop_state(&state_path)?;
    let run_policy = load_run_policy(&policy_path, config)?;
    let now_ms = now_unix_ms();
    let supervisor_running = pid_is_running(run_policy.supervisor_pid);
    let state_worker_pid = state
        .as_ref()
        .map(|state| state.pid)
        .filter(|pid| pid_is_running(*pid))
        .unwrap_or_default();
    let policy_worker_pid =
        if state_worker_pid == 0 && pid_is_running(run_policy.current_worker_pid) {
            run_policy.current_worker_pid
        } else {
            0
        };
    let worker_pid = if state_worker_pid != 0 {
        state_worker_pid
    } else {
        policy_worker_pid
    };
    let worker_running = worker_pid != 0;
    let action = if worker_running {
        "healthy"
    } else {
        supervision_action(&run_policy, now_ms)
    };
    let normalized_status = derive_run_agent_status(
        state.as_ref(),
        worker_running,
        supervisor_running,
        &run_policy,
        action,
    );
    let primary_channel = configured_delivery_target(config)
        .map(|target| format!("{} -> {}", target.channel_id, target.recipient))
        .unwrap_or_else(|| "none".to_string());
    Ok(serde_json::json!({
        "name": config.display_name,
        "slug": config.slug,
        "agent_id": config.agent_id,
        "running": worker_running,
        "status": normalized_status,
        "pid": worker_pid,
        "worker_pid": worker_pid,
        "worker_running": worker_running,
        "supervisor_pid": run_policy.supervisor_pid,
        "supervisor_running": supervisor_running,
        "heartbeat_id": heartbeat_id_for_slug(&config.slug),
        "last_run_status": state.as_ref().map(|state| state.last_run_status.clone()).unwrap_or_else(|| run_policy.last_exit_status.clone()),
        "last_tick_unix_ms": state.as_ref().map(|state| state.last_tick_unix_ms).unwrap_or_default(),
        "last_memory_sync_unix_ms": state.as_ref().map(|state| state.last_memory_sync_unix_ms).unwrap_or_default(),
        "memory_entries_recalled": state.as_ref().map(|state| state.memory_entries_recalled).unwrap_or_default(),
        "memory_entries_updated": state.as_ref().map(|state| state.memory_entries_updated).unwrap_or_default(),
        "primary_channel": primary_channel,
        "config_path": personal_agent_config_path(&config.slug)?.display().to_string(),
        "state_path": state_path.display().to_string(),
        "policy_path": policy_path.display().to_string(),
        "stop_request_path": stop_path.display().to_string(),
        "stop_requested": stop_path.exists(),
        "desired_state": run_policy.desired_state,
        "restart_policy": run_policy.restart_policy,
        "restart_backoff_seconds": run_policy.restart_backoff_seconds,
        "failure_count": run_policy.failure_count,
        "last_exit_unix_ms": run_policy.last_exit_unix_ms,
        "next_restart_after_unix_ms": run_policy.next_restart_after_unix_ms,
        "last_exit_status": run_policy.last_exit_status,
        "last_crash_unix_ms": run_policy.last_crash_unix_ms,
        "last_crash_reason": run_policy.last_crash_reason,
        "crash_state": derive_crash_state(&run_policy, worker_running, supervisor_running, now_ms),
        "supervision_action": action,
    }))
}

fn derive_run_agent_status(
    state: Option<&PersonalAgentLoopState>,
    worker_running: bool,
    supervisor_running: bool,
    policy: &PersonalAgentRunPolicy,
    action: &str,
) -> String {
    if worker_running {
        return state
            .map(|item| item.status.as_str())
            .filter(|value| !value.trim().is_empty())
            .map(|value| match value {
                "starting" => "running".to_string(),
                other => other.to_string(),
            })
            .unwrap_or_else(|| "running".to_string());
    }
    match action {
        "waiting_backoff" => "waiting_backoff".to_string(),
        "supervisor_active" => {
            if policy.last_crash_unix_ms > 0 {
                "recovering".to_string()
            } else if supervisor_running {
                "supervising".to_string()
            } else {
                "starting".to_string()
            }
        }
        "manual_restart_required" => "crashed".to_string(),
        "stopped_by_policy" => "stopped".to_string(),
        _ => state
            .map(|item| item.status.clone())
            .filter(|value| !matches!(value.as_str(), "running" | "starting"))
            .unwrap_or_else(|| {
                if policy.last_crash_unix_ms > 0 {
                    "crashed".to_string()
                } else {
                    "not_started".to_string()
                }
            }),
    }
}

fn derive_crash_state(
    policy: &PersonalAgentRunPolicy,
    worker_running: bool,
    supervisor_running: bool,
    now_unix_ms: u64,
) -> &'static str {
    if policy.last_crash_unix_ms == 0 {
        return "none";
    }
    if worker_running {
        return "recovered";
    }
    if supervisor_running || policy.next_restart_after_unix_ms > now_unix_ms {
        return "awaiting_restart";
    }
    if policy.restart_policy == "always" {
        return "restart_due";
    }
    "manual_restart_required"
}

fn supervision_action(policy: &PersonalAgentRunPolicy, now_unix_ms: u64) -> &'static str {
    if policy.desired_state != "running" {
        return "stopped_by_policy";
    }
    if pid_is_running(policy.current_worker_pid) {
        return "healthy";
    }
    if pid_is_running(policy.supervisor_pid) {
        if policy.next_restart_after_unix_ms > now_unix_ms {
            return "waiting_backoff";
        }
        return "supervisor_active";
    }
    if policy.restart_policy != "always" {
        if policy.last_crash_unix_ms > 0 || policy.failure_count > 0 {
            return "manual_restart_required";
        }
        return "needs_restart";
    }
    if policy.next_restart_after_unix_ms > now_unix_ms {
        return "waiting_backoff";
    }
    "needs_restart"
}

fn personal_agent_channel_ids(config: &PersonalAgentConfig) -> Vec<String> {
    let mut channel_ids = Vec::new();
    if config.telegram_enabled {
        channel_ids.push("telegram".to_string());
    }
    if config.webhook_enabled {
        channel_ids.push(webhook_channel_id(&config.slug));
    }
    if let Some(target) = configured_delivery_target(config) {
        if !channel_ids.iter().any(|entry| entry == &target.channel_id) {
            channel_ids.push(target.channel_id);
        }
    }
    channel_ids
}

fn ensure_runtime_ready_for_personal_agent(
    root: &Path,
    config: &PersonalAgentConfig,
) -> LoomResult<()> {
    let runtime_config = read_config(root)?;
    let profile = AgentRuntimeProfile {
        agent_id: config.agent_id.clone(),
        display_name: config.display_name.clone(),
        role: config.role.clone(),
        workspace_root: format!("agents/personal/{}/workspace", config.slug),
        memory_root: format!("agents/personal/{}/memory", config.slug),
        session_root: format!("agents/personal/{}/sessions", config.slug),
        provider_profile: config.provider_profile.clone(),
        tool_scope: config.tool_scope.clone(),
        heartbeat_policy: "persistent".to_string(),
    };
    let _ = upsert_agent_runtime_profile(root, &profile)?;
    let _ = write_agent_memory_snapshot(
        root,
        &config.agent_id,
        &BTreeMap::from([
            ("personal_agent_slug".to_string(), config.slug.clone()),
            (
                "service_http_address".to_string(),
                runtime_config.service_http_address.clone(),
            ),
            (
                "heartbeat_capability".to_string(),
                config.heartbeat_capability.clone(),
            ),
        ]),
    )?;
    if !runtime_service_status(root, None)?.running {
        let start_args = vec![
            "--root".to_string(),
            root.display().to_string(),
            "--kernel-path".to_string(),
            config.kernel_path.clone(),
            "--http-address".to_string(),
            config.service_http_address.clone(),
            "--service-token".to_string(),
            config.service_token.clone(),
        ];
        crate::commands::service::start_service_with_mode(&start_args)?;
    }
    if !supervisor_daemon_status(root)?.running {
        let daemon_args = vec![
            "--root".to_string(),
            root.display().to_string(),
            "--kernel-path".to_string(),
            config.kernel_path.clone(),
            "--poll-seconds".to_string(),
            "5".to_string(),
        ];
        crate::commands::supervisor::handle_supervisor_daemon_start(&daemon_args)?;
    }
    Ok(())
}

pub(crate) fn sync_personal_agent_delivery_channels(
    root: &Path,
    config: &PersonalAgentConfig,
) -> LoomResult<()> {
    let runtime_config = read_config(root)?;
    let mut manifest = onboarding::load_onboard_manifest(root)?;
    if config.telegram_enabled {
        manifest.telegram_enabled = true;
        manifest.telegram_token_env = config.telegram_token_env.clone();
    }
    onboarding::write_onboard_manifest(root, &manifest)?;
    let _ = channels::sync_channel_registry(root)?;
    if config.webhook_enabled && !config.webhook_url.trim().is_empty() {
        let channel_id = webhook_channel_id(&config.slug);
        channels::upsert_channel_record(
            root,
            &ChannelRecord {
                channel_id,
                kind: "webhook".to_string(),
                enabled: true,
                endpoint: config.webhook_url.clone(),
                auth_mode: if config.webhook_header.trim().is_empty() {
                    "none".to_string()
                } else {
                    "inline_header".to_string()
                },
                credential_ref: config.webhook_header.clone(),
                dm_policy: "per-agent".to_string(),
                group_policy: String::new(),
                streaming: "async".to_string(),
                note: format!(
                    "personal_agent={} gateway={}",
                    config.slug, runtime_config.service_http_address
                ),
            },
        )?;
    } else {
        channels::upsert_channel_record(
            root,
            &ChannelRecord {
                channel_id: webhook_channel_id(&config.slug),
                kind: "webhook".to_string(),
                enabled: false,
                endpoint: config.webhook_url.clone(),
                auth_mode: if config.webhook_header.trim().is_empty() {
                    "none".to_string()
                } else {
                    "inline_header".to_string()
                },
                credential_ref: config.webhook_header.clone(),
                dm_policy: "per-agent".to_string(),
                group_policy: String::new(),
                streaming: "async".to_string(),
                note: format!(
                    "personal_agent={} gateway={} status=disabled",
                    config.slug, runtime_config.service_http_address
                ),
            },
        )?;
    }
    Ok(())
}

fn ensure_personal_agent_heartbeat(
    root: &Path,
    config: &PersonalAgentConfig,
    heartbeat_id: &str,
    delivery_target: Option<HeartbeatDeliveryTarget>,
) -> LoomResult<()> {
    if recurring::heartbeat_summary(root, heartbeat_id).is_ok() {
        return Ok(());
    }
    let request = HeartbeatScheduleRequest {
        heartbeat_id: Some(heartbeat_id.to_string()),
        agent_id: config.agent_id.clone(),
        capability_name: config.heartbeat_capability.clone(),
        schedule_kind: "interval".to_string(),
        schedule_expression: String::new(),
        timezone: "UTC".to_string(),
        every_seconds: config.heartbeat_every_seconds.max(30),
        jitter_seconds: 0,
        not_before_unix_ms: None,
        payload_json: serde_json::json!({
            "message": format!(
                "{} heartbeat on Loom. Emit a governed local status receipt.",
                config.display_name
            )
        })
        .to_string(),
        delivery_target,
        max_attempts: 1,
    };
    let _ = recurring::schedule_heartbeat(root, &request)?;
    Ok(())
}

fn seed_personal_agent_memory(root: &Path, config: &PersonalAgentConfig) -> LoomResult<usize> {
    let service = MemoryService::with_defaults(root);
    let profile_text = format!(
        "name={} role={} purpose={} provider_profile={} tool_scope={} telegram_enabled={} webhook_enabled={}",
        config.display_name,
        config.role,
        config.purpose,
        config.provider_profile,
        config.tool_scope,
        config.telegram_enabled,
        config.webhook_enabled
    );
    let _ = service.write(
        &config.agent_id,
        "profile",
        "personal-agent",
        &profile_text,
        "loom.new-agent",
    )?;
    let _ = service.write(
        &config.agent_id,
        "delivery",
        "channel-plan",
        &format!(
            "telegram_chat_id={} webhook_url={}",
            if config.telegram_chat_id.trim().is_empty() {
                "(none)"
            } else {
                &config.telegram_chat_id
            },
            if config.webhook_url.trim().is_empty() {
                "(none)"
            } else {
                &config.webhook_url
            }
        ),
        "loom.run-agent",
    )?;
    let recalled = service.search(&config.agent_id, Some("profile"), None)?;
    Ok(recalled.len())
}

fn sync_personal_agent_memory(
    root: &Path,
    config: &PersonalAgentConfig,
) -> LoomResult<PersonalAgentMemorySyncResult> {
    let service = MemoryService::with_defaults(root);
    let state_path = personal_agent_memory_sync_state_path(root, &config.slug)?;
    let previous = load_memory_sync_state(&state_path)?;
    let agent_dir = personal_agent_config_path(&config.slug)?
        .parent()
        .map(Path::to_path_buf)
        .ok_or_else(|| "personal agent directory was not found".to_string())?;

    let config_body = render_personal_agent_config(config);
    let soul_body = fs::read_to_string(agent_dir.join("SOUL.md")).unwrap_or_default();
    let memory_body = fs::read_to_string(agent_dir.join("MEMORY.md")).unwrap_or_default();

    let current = PersonalAgentMemorySyncState {
        config_hash: fingerprint_text(&config_body),
        soul_hash: fingerprint_text(&soul_body),
        memory_hash: fingerprint_text(&memory_body),
        last_sync_unix_ms: now_unix_ms(),
    };

    let mut changed_count = 0usize;
    if previous.config_hash != current.config_hash {
        let _ = service.write(
            &config.agent_id,
            "profile",
            "agent-config",
            &compact_memory_body(&config_body),
            "loom.personal-agent.sync",
        )?;
        changed_count += 1;
    }
    if previous.soul_hash != current.soul_hash {
        let _ = service.write(
            &config.agent_id,
            "soul",
            "operator-soul",
            &compact_memory_body(&soul_body),
            "loom.personal-agent.sync",
        )?;
        changed_count += 1;
    }
    if previous.memory_hash != current.memory_hash {
        let _ = service.write(
            &config.agent_id,
            "notes",
            "operator-memory",
            &compact_memory_body(&memory_body),
            "loom.personal-agent.sync",
        )?;
        changed_count += 1;
    }

    write_memory_sync_state(&state_path, &current)?;
    let recalled = recall_personal_agent_memory(root, config)?;
    Ok(PersonalAgentMemorySyncResult {
        changed_count,
        recalled_count: recalled.recalled_count,
        sync_state: current,
    })
}

fn recall_personal_agent_memory(
    root: &Path,
    config: &PersonalAgentConfig,
) -> LoomResult<PersonalAgentMemorySyncResult> {
    let service = MemoryService::with_defaults(root);
    let entries = service.search(&config.agent_id, None, None)?;
    let state =
        load_memory_sync_state(&personal_agent_memory_sync_state_path(root, &config.slug)?)?;
    Ok(PersonalAgentMemorySyncResult {
        changed_count: 0,
        recalled_count: entries.len(),
        sync_state: state,
    })
}

pub(crate) fn configured_delivery_target(
    config: &PersonalAgentConfig,
) -> Option<HeartbeatDeliveryTarget> {
    if config.telegram_enabled && !config.telegram_chat_id.trim().is_empty() {
        return Some(HeartbeatDeliveryTarget {
            channel_id: "telegram".to_string(),
            recipient: config.telegram_chat_id.clone(),
            allow_receipt_hashes: true,
            allow_operator_diagnostics: false,
        });
    }
    if config.webhook_enabled && !config.webhook_url.trim().is_empty() {
        return Some(HeartbeatDeliveryTarget {
            channel_id: webhook_channel_id(&config.slug),
            recipient: config.webhook_url.clone(),
            allow_receipt_hashes: true,
            allow_operator_diagnostics: false,
        });
    }
    None
}

fn ensure_runtime_initialized(
    root: &Path,
    requested_kernel_path: Option<&str>,
    requested_org_id: Option<&str>,
) -> LoomResult<loom_core::Config> {
    if root.join("loom.toml").exists() {
        let mut config = read_config(root)?;
        if config.kernel_path.trim().is_empty() {
            let fallback_kernel = default_kernel_path();
            let kernel_path = requested_kernel_path
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .or(fallback_kernel.as_deref())
                .ok_or_else(|| {
                    "kernel path is required to bootstrap a personal agent".to_string()
                })?;
            config.kernel_path = kernel_path.to_string();
            let _ = loom_core::write_config(root, &config)?;
        }
        return Ok(config);
    }

    let fallback_kernel = default_kernel_path();
    let kernel_path = requested_kernel_path
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .or(fallback_kernel.as_deref())
        .ok_or_else(|| "kernel path is required to initialize Loom".to_string())?;
    let org_id = requested_org_id
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or("local_foundry");
    init_workspace(root, "embedded", Some(kernel_path), org_id)
}

fn register_kernel_agent(
    kernel_path: &Path,
    org_id: &str,
    display_name: &str,
    role: &str,
    purpose: &str,
    provider_profile: &str,
) -> LoomResult<String> {
    let script = kernel_path.join("kernel/agent_registry.py");
    if !script.exists() {
        return Err(format!("missing {}", script.display()));
    }
    let scopes = format!(
        "governed_local,personal_agent,{},memory_receipts,channel_delivery",
        provider_profile
    );
    let output = Command::new("python3")
        .arg(&script)
        .arg("register")
        .arg("--org_id")
        .arg(org_id)
        .arg("--name")
        .arg(display_name)
        .arg("--role")
        .arg(role)
        .arg("--purpose")
        .arg(purpose)
        .arg("--scopes")
        .arg(scopes)
        .arg("--runtime_binding")
        .arg("loom_native")
        .output()
        .map_err(|error| error.to_string())?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    stdout
        .lines()
        .find_map(|line| line.strip_prefix("Registered agent: "))
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .ok_or_else(|| "kernel agent registration did not return an agent id".to_string())
}

pub(crate) fn load_personal_agent_config(name_or_slug: &str) -> LoomResult<PersonalAgentConfig> {
    let slug = sanitize_personal_slug(name_or_slug);
    let direct = personal_agent_config_path(&slug)?;
    if direct.exists() {
        return parse_personal_agent_config(&direct);
    }
    let root = personal_agents_config_root()?;
    if !root.exists() {
        return Err(format!(
            "personal agent config was not found for '{}'",
            name_or_slug
        ));
    }
    for entry in fs::read_dir(&root).map_err(|error| error.to_string())? {
        let entry = entry.map_err(|error| error.to_string())?;
        let path = entry.path().join("agent.toml");
        if !path.exists() {
            continue;
        }
        let config = parse_personal_agent_config(&path)?;
        if config.slug == slug
            || config.agent_id == name_or_slug.trim()
            || config.name.eq_ignore_ascii_case(name_or_slug.trim())
        {
            return Ok(config);
        }
    }
    Err(format!(
        "personal agent config was not found for '{}'",
        name_or_slug
    ))
}

fn parse_personal_agent_config(path: &Path) -> LoomResult<PersonalAgentConfig> {
    let raw = fs::read_to_string(path).map_err(|error| error.to_string())?;
    let mut values = BTreeMap::new();
    for raw_line in raw.lines() {
        let line = raw_line.trim();
        if line.is_empty() || line.starts_with('#') || line.starts_with('[') {
            continue;
        }
        let Some((key, value)) = line.split_once('=') else {
            continue;
        };
        values.insert(
            key.trim().to_string(),
            value.trim().trim_matches('"').to_string(),
        );
    }
    Ok(PersonalAgentConfig {
        name: required_config_value(&values, "name")?,
        slug: required_config_value(&values, "slug")?,
        agent_id: required_config_value(&values, "agent_id")?,
        display_name: required_config_value(&values, "display_name")?,
        role: required_config_value(&values, "role")?,
        purpose: required_config_value(&values, "purpose")?,
        provider_profile: required_config_value(&values, "provider_profile")?,
        tool_scope: required_config_value(&values, "tool_scope")?,
        org_id: required_config_value(&values, "org_id")?,
        loom_root: required_config_value(&values, "loom_root")?,
        kernel_path: required_config_value(&values, "kernel_path")?,
        service_http_address: required_config_value(&values, "service_http_address")?,
        service_token: required_config_value(&values, "service_token")?,
        heartbeat_capability: required_config_value(&values, "heartbeat_capability")?,
        heartbeat_every_seconds: values
            .get("heartbeat_every_seconds")
            .and_then(|value| value.parse::<u64>().ok())
            .unwrap_or(DEFAULT_PERSONAL_HEARTBEAT_SECONDS),
        restart_policy: values
            .get("restart_policy")
            .cloned()
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| DEFAULT_PERSONAL_RESTART_POLICY.to_string()),
        restart_backoff_seconds: values
            .get("restart_backoff_seconds")
            .and_then(|value| value.parse::<u64>().ok())
            .unwrap_or(DEFAULT_PERSONAL_RESTART_BACKOFF_SECONDS),
        telegram_enabled: values
            .get("telegram_enabled")
            .map(|value| value.eq_ignore_ascii_case("true"))
            .unwrap_or(false),
        telegram_chat_id: values.get("telegram_chat_id").cloned().unwrap_or_default(),
        telegram_token_env: values
            .get("telegram_token_env")
            .cloned()
            .unwrap_or_else(|| DEFAULT_TELEGRAM_TOKEN_ENV.to_string()),
        webhook_enabled: values
            .get("webhook_enabled")
            .map(|value| value.eq_ignore_ascii_case("true"))
            .unwrap_or(false),
        webhook_url: values.get("webhook_url").cloned().unwrap_or_default(),
        webhook_header: values.get("webhook_header").cloned().unwrap_or_default(),
    })
}

pub(crate) fn write_personal_agent_config(
    path: &Path,
    config: &PersonalAgentConfig,
) -> LoomResult<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    fs::write(path, render_personal_agent_config(config)).map_err(|error| error.to_string())
}

fn write_personal_agent_support_files(path: &Path, config: &PersonalAgentConfig) -> LoomResult<()> {
    let Some(agent_dir) = path.parent() else {
        return Ok(());
    };
    fs::create_dir_all(agent_dir).map_err(|error| error.to_string())?;
    write_template_if_missing(
        &agent_dir.join("README.md"),
        &render_personal_agent_template(PERSONAL_AGENT_TEMPLATE_README, config),
    )?;
    write_template_if_missing(
        &agent_dir.join("MEMORY.md"),
        &render_personal_agent_template(PERSONAL_AGENT_TEMPLATE_MEMORY, config),
    )?;
    write_template_if_missing(
        &agent_dir.join("SOUL.md"),
        &render_personal_agent_template(PERSONAL_AGENT_TEMPLATE_SOUL, config),
    )?;
    Ok(())
}

fn render_personal_agent_config(config: &PersonalAgentConfig) -> String {
    format!(
        "[agent]\nname = {}\nslug = {}\nagent_id = {}\ndisplay_name = {}\nrole = {}\npurpose = {}\nprovider_profile = {}\ntool_scope = {}\n\n[runtime]\norg_id = {}\nloom_root = {}\nkernel_path = {}\nservice_http_address = {}\nservice_token = {}\n\n[heartbeat]\nheartbeat_capability = {}\nheartbeat_every_seconds = {}\n\n[supervision]\nrestart_policy = {}\nrestart_backoff_seconds = {}\n\n[telegram]\ntelegram_enabled = {}\ntelegram_chat_id = {}\ntelegram_token_env = {}\n\n[webhook]\nwebhook_enabled = {}\nwebhook_url = {}\nwebhook_header = {}\n",
        json_string(&config.name),
        json_string(&config.slug),
        json_string(&config.agent_id),
        json_string(&config.display_name),
        json_string(&config.role),
        json_string(&config.purpose),
        json_string(&config.provider_profile),
        json_string(&config.tool_scope),
        json_string(&config.org_id),
        json_string(&config.loom_root),
        json_string(&config.kernel_path),
        json_string(&config.service_http_address),
        json_string(&config.service_token),
        json_string(&config.heartbeat_capability),
        config.heartbeat_every_seconds,
        json_string(&normalize_restart_policy(&config.restart_policy)),
        config.restart_backoff_seconds,
        if config.telegram_enabled { "true" } else { "false" },
        json_string(&config.telegram_chat_id),
        json_string(&config.telegram_token_env),
        if config.webhook_enabled { "true" } else { "false" },
        json_string(&config.webhook_url),
        json_string(&config.webhook_header),
    )
}

fn write_template_if_missing(path: &Path, contents: &str) -> LoomResult<()> {
    if path.exists() {
        return Ok(());
    }
    fs::write(path, contents).map_err(|error| error.to_string())
}

fn render_personal_agent_template(template: &str, config: &PersonalAgentConfig) -> String {
    template
        .replace("{{NAME}}", &config.display_name)
        .replace("{{SLUG}}", &config.slug)
        .replace("{{AGENT_ID}}", &config.agent_id)
        .replace("{{ROLE}}", &config.role)
        .replace("{{PURPOSE}}", &config.purpose)
        .replace("{{PROVIDER_PROFILE}}", &config.provider_profile)
        .replace("{{TOOL_SCOPE}}", &config.tool_scope)
        .replace("{{ORG_ID}}", &config.org_id)
        .replace("{{LOOM_ROOT}}", &config.loom_root)
        .replace("{{KERNEL_PATH}}", &config.kernel_path)
        .replace("{{SERVICE_HTTP_ADDRESS}}", &config.service_http_address)
        .replace("{{SERVICE_TOKEN}}", &config.service_token)
        .replace("{{HEARTBEAT_CAPABILITY}}", &config.heartbeat_capability)
        .replace(
            "{{HEARTBEAT_EVERY_SECONDS}}",
            &config.heartbeat_every_seconds.to_string(),
        )
        .replace(
            "{{TELEGRAM_ENABLED}}",
            if config.telegram_enabled {
                "true"
            } else {
                "false"
            },
        )
        .replace("{{TELEGRAM_CHAT_ID}}", &config.telegram_chat_id)
        .replace("{{TELEGRAM_TOKEN_ENV}}", &config.telegram_token_env)
        .replace(
            "{{WEBHOOK_ENABLED}}",
            if config.webhook_enabled {
                "true"
            } else {
                "false"
            },
        )
        .replace("{{WEBHOOK_URL}}", &config.webhook_url)
        .replace("{{WEBHOOK_HEADER}}", &config.webhook_header)
}

fn personal_agents_config_root() -> LoomResult<PathBuf> {
    Ok(config_home()?.join("meridian-loom").join("agents"))
}

pub(crate) fn personal_agent_config_path(slug: &str) -> LoomResult<PathBuf> {
    Ok(personal_agents_config_root()?.join(slug).join("agent.toml"))
}

fn personal_agent_log_path(root: &Path, slug: &str) -> LoomResult<PathBuf> {
    Ok(root
        .join("run")
        .join("personal-agents")
        .join(format!("{}.log", slug)))
}

fn personal_agent_state_path(root: &Path, slug: &str) -> LoomResult<PathBuf> {
    Ok(root
        .join("run")
        .join("personal-agents")
        .join(format!("{}.state.json", slug)))
}

fn personal_agent_policy_path(root: &Path, slug: &str) -> LoomResult<PathBuf> {
    Ok(root
        .join("run")
        .join("personal-agents")
        .join(format!("{}.policy.json", slug)))
}

fn personal_agent_stop_request_path(root: &Path, slug: &str) -> LoomResult<PathBuf> {
    Ok(root
        .join("run")
        .join("personal-agents")
        .join(format!("{}.stop", slug)))
}

fn personal_agent_memory_sync_state_path(root: &Path, slug: &str) -> LoomResult<PathBuf> {
    Ok(root
        .join("run")
        .join("personal-agents")
        .join(format!("{}.memory-sync.json", slug)))
}

fn personal_agent_chaos_marker_path(
    root: &Path,
    slug: &str,
    directive: &PersonalAgentChaosDirective,
) -> LoomResult<PathBuf> {
    Ok(root.join("run").join("personal-agents").join(format!(
        "{}.chaos.{}.{}.{}.marker",
        slug, directive.phase, directive.mode, directive.exit_code
    )))
}

fn heartbeat_id_for_slug(slug: &str) -> String {
    format!("personal-{}-heartbeat", slug)
}

pub(crate) fn webhook_channel_id(slug: &str) -> String {
    format!("webhook_{}", slug)
}

fn config_home() -> LoomResult<PathBuf> {
    if let Ok(value) = env::var("XDG_CONFIG_HOME") {
        let trimmed = value.trim();
        if !trimmed.is_empty() {
            return Ok(PathBuf::from(trimmed));
        }
    }
    let home = env::var("HOME").map_err(|_| "HOME is not set".to_string())?;
    Ok(PathBuf::from(home).join(".config"))
}

fn default_kernel_path() -> Option<String> {
    for candidate in ["/opt/meridian-kernel", "/tmp/meridian-kernel"] {
        if Path::new(candidate).exists() {
            return Some(candidate.to_string());
        }
    }
    env::var("MERIDIAN_KERNEL_PATH")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn required_config_value(values: &BTreeMap<String, String>, key: &str) -> LoomResult<String> {
    values
        .get(key)
        .cloned()
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| format!("agent config missing {}", key))
}

fn positional_name(args: &[String]) -> Option<String> {
    args.iter()
        .find(|value| !value.starts_with('-'))
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn sanitize_personal_slug(input: &str) -> String {
    sanitize_token(input)
}

fn now_unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

fn atomic_write_text(path: &Path, contents: &str) -> LoomResult<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        let temp_path = parent.join(format!(
            ".{}.{}.{}.tmp",
            path.file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("loom-state"),
            now_unix_ms(),
            std::process::id()
        ));
        fs::write(&temp_path, contents).map_err(|error| error.to_string())?;
        fs::rename(&temp_path, path).map_err(|error| error.to_string())?;
        return Ok(());
    }
    fs::write(path, contents).map_err(|error| error.to_string())
}

fn load_loop_state(path: &Path) -> LoomResult<Option<PersonalAgentLoopState>> {
    if !path.exists() {
        return Ok(None);
    }
    let raw = fs::read_to_string(path).map_err(|error| error.to_string())?;
    let value: serde_json::Value = serde_json::from_str(&raw).map_err(|error| error.to_string())?;
    Ok(Some(PersonalAgentLoopState {
        slug: value
            .get("slug")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default()
            .to_string(),
        agent_id: value
            .get("agent_id")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default()
            .to_string(),
        pid: value
            .get("pid")
            .and_then(serde_json::Value::as_u64)
            .unwrap_or_default() as u32,
        status: value
            .get("status")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default()
            .to_string(),
        launched_at_unix_ms: value
            .get("launched_at_unix_ms")
            .and_then(serde_json::Value::as_u64)
            .unwrap_or_default(),
        updated_at_unix_ms: value
            .get("updated_at_unix_ms")
            .and_then(serde_json::Value::as_u64)
            .unwrap_or_default(),
        last_run_status: value
            .get("last_run_status")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default()
            .to_string(),
        last_tick_unix_ms: value
            .get("last_tick_unix_ms")
            .and_then(serde_json::Value::as_u64)
            .unwrap_or_default(),
        heartbeat_id: value
            .get("heartbeat_id")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default()
            .to_string(),
        log_path: value
            .get("log_path")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default()
            .to_string(),
        last_memory_sync_unix_ms: value
            .get("last_memory_sync_unix_ms")
            .and_then(serde_json::Value::as_u64)
            .unwrap_or_default(),
        memory_entries_recalled: value
            .get("memory_entries_recalled")
            .and_then(serde_json::Value::as_u64)
            .unwrap_or_default() as usize,
        memory_entries_updated: value
            .get("memory_entries_updated")
            .and_then(serde_json::Value::as_u64)
            .unwrap_or_default() as usize,
        primary_channel_id: value
            .get("primary_channel_id")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default()
            .to_string(),
    }))
}

fn write_loop_state(path: &Path, state: &PersonalAgentLoopState) -> LoomResult<()> {
    let rendered = serde_json::to_string_pretty(&serde_json::json!({
        "slug": state.slug,
        "agent_id": state.agent_id,
        "pid": state.pid,
        "status": state.status,
        "launched_at_unix_ms": state.launched_at_unix_ms,
        "updated_at_unix_ms": state.updated_at_unix_ms,
        "last_run_status": state.last_run_status,
        "last_tick_unix_ms": state.last_tick_unix_ms,
        "heartbeat_id": state.heartbeat_id,
        "log_path": state.log_path,
        "last_memory_sync_unix_ms": state.last_memory_sync_unix_ms,
        "memory_entries_recalled": state.memory_entries_recalled,
        "memory_entries_updated": state.memory_entries_updated,
        "primary_channel_id": state.primary_channel_id,
    }))
    .map_err(|error| error.to_string())?;
    atomic_write_text(path, &format!("{}\n", rendered))
}

fn load_memory_sync_state(path: &Path) -> LoomResult<PersonalAgentMemorySyncState> {
    if !path.exists() {
        return Ok(PersonalAgentMemorySyncState::default());
    }
    let raw = fs::read_to_string(path).map_err(|error| error.to_string())?;
    let value: serde_json::Value = serde_json::from_str(&raw).map_err(|error| error.to_string())?;
    Ok(PersonalAgentMemorySyncState {
        config_hash: value
            .get("config_hash")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default()
            .to_string(),
        soul_hash: value
            .get("soul_hash")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default()
            .to_string(),
        memory_hash: value
            .get("memory_hash")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default()
            .to_string(),
        last_sync_unix_ms: value
            .get("last_sync_unix_ms")
            .and_then(serde_json::Value::as_u64)
            .unwrap_or_default(),
    })
}

fn write_memory_sync_state(path: &Path, state: &PersonalAgentMemorySyncState) -> LoomResult<()> {
    let rendered = serde_json::to_string_pretty(&serde_json::json!({
        "config_hash": state.config_hash,
        "soul_hash": state.soul_hash,
        "memory_hash": state.memory_hash,
        "last_sync_unix_ms": state.last_sync_unix_ms,
    }))
    .map_err(|error| error.to_string())?;
    atomic_write_text(path, &format!("{}\n", rendered))
}

fn default_run_policy(config: &PersonalAgentConfig) -> PersonalAgentRunPolicy {
    PersonalAgentRunPolicy {
        desired_state: "stopped".to_string(),
        restart_policy: normalize_restart_policy(&config.restart_policy),
        restart_backoff_seconds: config.restart_backoff_seconds.max(1),
        failure_count: 0,
        last_exit_unix_ms: 0,
        next_restart_after_unix_ms: 0,
        last_exit_status: "not_started".to_string(),
        supervisor_pid: 0,
        current_worker_pid: 0,
        last_crash_unix_ms: 0,
        last_crash_reason: String::new(),
    }
}

fn load_run_policy(
    path: &Path,
    config: &PersonalAgentConfig,
) -> LoomResult<PersonalAgentRunPolicy> {
    if !path.exists() {
        return Ok(default_run_policy(config));
    }
    let raw = fs::read_to_string(path).map_err(|error| error.to_string())?;
    let value: serde_json::Value = serde_json::from_str(&raw).map_err(|error| error.to_string())?;
    Ok(PersonalAgentRunPolicy {
        desired_state: value
            .get("desired_state")
            .and_then(serde_json::Value::as_str)
            .unwrap_or("stopped")
            .to_string(),
        restart_policy: normalize_restart_policy(
            value
                .get("restart_policy")
                .and_then(serde_json::Value::as_str)
                .unwrap_or(&config.restart_policy),
        ),
        restart_backoff_seconds: value
            .get("restart_backoff_seconds")
            .and_then(serde_json::Value::as_u64)
            .unwrap_or(config.restart_backoff_seconds)
            .max(1),
        failure_count: value
            .get("failure_count")
            .and_then(serde_json::Value::as_u64)
            .unwrap_or_default(),
        last_exit_unix_ms: value
            .get("last_exit_unix_ms")
            .and_then(serde_json::Value::as_u64)
            .unwrap_or_default(),
        next_restart_after_unix_ms: value
            .get("next_restart_after_unix_ms")
            .and_then(serde_json::Value::as_u64)
            .unwrap_or_default(),
        last_exit_status: value
            .get("last_exit_status")
            .and_then(serde_json::Value::as_str)
            .unwrap_or("not_started")
            .to_string(),
        supervisor_pid: value
            .get("supervisor_pid")
            .and_then(serde_json::Value::as_u64)
            .unwrap_or_default() as u32,
        current_worker_pid: value
            .get("current_worker_pid")
            .and_then(serde_json::Value::as_u64)
            .unwrap_or_default() as u32,
        last_crash_unix_ms: value
            .get("last_crash_unix_ms")
            .and_then(serde_json::Value::as_u64)
            .unwrap_or_default(),
        last_crash_reason: value
            .get("last_crash_reason")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default()
            .to_string(),
    })
}

fn write_run_policy(path: &Path, policy: &PersonalAgentRunPolicy) -> LoomResult<()> {
    let rendered = serde_json::to_string_pretty(&serde_json::json!({
        "desired_state": policy.desired_state,
        "restart_policy": normalize_restart_policy(&policy.restart_policy),
        "restart_backoff_seconds": policy.restart_backoff_seconds.max(1),
        "failure_count": policy.failure_count,
        "last_exit_unix_ms": policy.last_exit_unix_ms,
        "next_restart_after_unix_ms": policy.next_restart_after_unix_ms,
        "last_exit_status": policy.last_exit_status,
        "supervisor_pid": policy.supervisor_pid,
        "current_worker_pid": policy.current_worker_pid,
        "last_crash_unix_ms": policy.last_crash_unix_ms,
        "last_crash_reason": policy.last_crash_reason,
    }))
    .map_err(|error| error.to_string())?;
    atomic_write_text(path, &format!("{}\n", rendered))
}

fn normalize_restart_policy(input: &str) -> String {
    match input.trim() {
        "always" => "always".to_string(),
        _ => "manual".to_string(),
    }
}

fn parse_personal_agent_chaos_directive(raw: &str) -> Option<PersonalAgentChaosDirective> {
    let mut parts = raw
        .split(':')
        .map(str::trim)
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>();
    if parts.len() != 3 {
        return None;
    }
    let phase = parts.remove(0).to_string();
    let mode = match parts.remove(0) {
        "always" => "always".to_string(),
        "once" => "once".to_string(),
        _ => return None,
    };
    let exit_code = parts.remove(0).parse::<i32>().ok()?;
    if exit_code <= 0 {
        return None;
    }
    Some(PersonalAgentChaosDirective {
        phase,
        mode,
        exit_code,
    })
}

fn load_personal_agent_chaos_directive() -> Option<PersonalAgentChaosDirective> {
    env::var(PERSONAL_AGENT_CHAOS_ENV)
        .ok()
        .and_then(|raw| parse_personal_agent_chaos_directive(&raw))
}

fn maybe_inject_personal_agent_chaos(
    root: &Path,
    config: &PersonalAgentConfig,
    log_path: &Path,
    phase: &str,
) -> LoomResult<()> {
    let Some(directive) = load_personal_agent_chaos_directive() else {
        return Ok(());
    };
    if directive.phase != phase {
        return Ok(());
    }
    let marker_path = personal_agent_chaos_marker_path(root, &config.slug, &directive)?;
    if directive.mode == "once" {
        if marker_path.exists() {
            return Ok(());
        }
        if let Some(parent) = marker_path.parent() {
            fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        fs::write(
            &marker_path,
            format!(
                "phase={}\nmode={}\nexit_code={}\ntriggered_at_unix_ms={}\n",
                directive.phase,
                directive.mode,
                directive.exit_code,
                now_unix_ms()
            ),
        )
        .map_err(|error| error.to_string())?;
    }
    append_supervisor_log(
        log_path,
        &format!(
            "chaos injected phase={} mode={} exit_code={}",
            directive.phase, directive.mode, directive.exit_code
        ),
    )?;
    std::process::exit(directive.exit_code);
}

fn stop_requested(root: &Path, slug: &str) -> LoomResult<bool> {
    Ok(personal_agent_stop_request_path(root, slug)?.exists())
}

fn clear_stop_request(root: &Path, slug: &str) -> LoomResult<()> {
    let path = personal_agent_stop_request_path(root, slug)?;
    if path.exists() {
        fs::remove_file(path).map_err(|error| error.to_string())?;
    }
    Ok(())
}

fn write_stop_request(root: &Path, slug: &str) -> LoomResult<PathBuf> {
    let path = personal_agent_stop_request_path(root, slug)?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    fs::write(&path, b"stop\n").map_err(|error| error.to_string())?;
    Ok(path)
}

fn fingerprint_text(input: &str) -> String {
    use std::hash::{Hash, Hasher};
    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    input.hash(&mut hasher);
    format!("{:016x}", hasher.finish())
}

fn compact_memory_body(input: &str) -> String {
    const MAX_BYTES: usize = 12_000;
    let trimmed = input.trim();
    if trimmed.len() <= MAX_BYTES {
        return trimmed.to_string();
    }
    let mut end = MAX_BYTES;
    while !trimmed.is_char_boundary(end) {
        end = end.saturating_sub(1);
    }
    format!(
        "{}\n\n[loom.personal-agent.sync truncated {} bytes]",
        &trimmed[..end],
        trimmed.len().saturating_sub(end)
    )
}

fn pid_is_running(pid: u32) -> bool {
    if pid == 0 {
        return false;
    }
    Command::new("kill")
        .arg("-0")
        .arg(pid.to_string())
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

fn handle_run_agent_status(args: &[String]) -> LoomResult<()> {
    let Some(name_or_slug) = positional_name(args) else {
        return Err("run-agent status requires an agent name or slug".to_string());
    };
    let config = load_personal_agent_config(&name_or_slug)?;
    let root = root_from(Some(&config.loom_root))?;
    let summary = build_run_agent_summary(&root, &config)?;
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    match format.as_str() {
        "json" => {
            print!(
                "{}\n",
                serde_json::to_string_pretty(&summary).map_err(|error| error.to_string())?
            );
        }
        _ => {
            print_startup_banner();
            print_human(&format!(
                "Meridian Loom // RUN AGENT STATUS\n=================================\nname:                  {}\nslug:                  {}\nagent_id:              {}\nstatus:                {}\nrunning:               {}\nworker_pid:            {}\nworker_running:        {}\nsupervisor_pid:        {}\nsupervisor_running:    {}\ncrash_state:           {}\nlast_crash_unix_ms:    {}\nlast_crash_reason:     {}\nheartbeat_id:          {}\nlast_run_status:       {}\nlast_tick_unix_ms:     {}\nlast_memory_sync_ms:   {}\nmemory_entries_recalled:{}\nmemory_entries_updated:{}\nprimary_channel:       {}\ndesired_state:         {}\nrestart_policy:        {}\nrestart_backoff_sec:   {}\nsupervision_action:    {}\nconfig_path:           {}\nstate_path:            {}\npolicy_path:           {}\nstop_requested:        {}\n",
                summary["name"].as_str().unwrap_or(""),
                summary["slug"].as_str().unwrap_or(""),
                summary["agent_id"].as_str().unwrap_or(""),
                summary["status"].as_str().unwrap_or(""),
                summary["running"].as_bool().unwrap_or(false),
                summary["worker_pid"].as_u64().unwrap_or_default(),
                summary["worker_running"].as_bool().unwrap_or(false),
                summary["supervisor_pid"].as_u64().unwrap_or_default(),
                summary["supervisor_running"].as_bool().unwrap_or(false),
                summary["crash_state"].as_str().unwrap_or(""),
                summary["last_crash_unix_ms"].as_u64().unwrap_or_default(),
                summary["last_crash_reason"].as_str().unwrap_or(""),
                summary["heartbeat_id"].as_str().unwrap_or(""),
                summary["last_run_status"].as_str().unwrap_or(""),
                summary["last_tick_unix_ms"].as_u64().unwrap_or_default(),
                summary["last_memory_sync_unix_ms"].as_u64().unwrap_or_default(),
                summary["memory_entries_recalled"].as_u64().unwrap_or_default(),
                summary["memory_entries_updated"].as_u64().unwrap_or_default(),
                summary["primary_channel"].as_str().unwrap_or(""),
                summary["desired_state"].as_str().unwrap_or(""),
                summary["restart_policy"].as_str().unwrap_or(""),
                summary["restart_backoff_seconds"].as_u64().unwrap_or_default(),
                summary["supervision_action"].as_str().unwrap_or(""),
                summary["config_path"].as_str().unwrap_or(""),
                summary["state_path"].as_str().unwrap_or(""),
                summary["policy_path"].as_str().unwrap_or(""),
                summary["stop_requested"].as_bool().unwrap_or(false),
            ));
        }
    }
    Ok(())
}

fn collect_personal_agent_channel_surface(
    root: &Path,
    config: &PersonalAgentConfig,
    history_limit: usize,
    diagnostic_limit: usize,
) -> LoomResult<Vec<PersonalAgentChannelSurface>> {
    let channel_ids = personal_agent_channel_ids(config);
    loom_core::channels::list_channel_health(root)?
        .into_iter()
        .filter(|record| channel_ids.iter().any(|id| id == &record.channel_id))
        .map(|record| {
            let history = loom_core::channels::list_channel_health_history(
                root,
                &record.channel_id,
                history_limit,
            )?;
            let diagnostics = loom_core::channels::list_channel_test_diagnostics(
                root,
                &record.channel_id,
                diagnostic_limit,
            )?;
            Ok((record, history, diagnostics))
        })
        .collect()
}

fn collect_personal_agent_recent_deliveries(
    root: &Path,
    config: &PersonalAgentConfig,
    limit: usize,
) -> LoomResult<Vec<ChannelDeliveryRecord>> {
    let channel_ids = personal_agent_channel_ids(config);
    Ok(
        loom_core::channels::list_channel_deliveries_with_options(root, 0, true, false)?
            .into_iter()
            .filter(|record| channel_ids.iter().any(|id| id == &record.channel_id))
            .take(limit)
            .collect::<Vec<_>>(),
    )
}

fn build_run_agent_operator_payload(
    root: &Path,
    config: &PersonalAgentConfig,
    receipt_limit: usize,
    delivery_limit: usize,
    history_limit: usize,
    diagnostic_limit: usize,
) -> LoomResult<serde_json::Value> {
    let summary = build_run_agent_summary(root, config)?;
    let channel_health =
        collect_personal_agent_channel_surface(root, config, history_limit, diagnostic_limit)?;
    let recent_receipts =
        MemoryService::with_defaults(root).list_receipts(receipt_limit, Some(&config.agent_id))?;
    let recent_deliveries = collect_personal_agent_recent_deliveries(root, config, delivery_limit)?;
    let mut alerts = Vec::new();
    match summary["supervision_action"]
        .as_str()
        .unwrap_or("stopped_by_policy")
    {
        "manual_restart_required" => alerts
            .push("Worker crashed under manual policy; operator restart required.".to_string()),
        "waiting_backoff" => alerts.push(
            "Supervisor is waiting for restart backoff to expire before relaunching the worker."
                .to_string(),
        ),
        "needs_restart" => alerts.push("Agent is down and ready for restart.".to_string()),
        _ => {}
    }
    if summary["stop_requested"].as_bool().unwrap_or(false) {
        alerts.push(
            "Stop request is pending; supervisor will drain and stop the worker.".to_string(),
        );
    }
    for (record, _, diagnostics) in &channel_health {
        if !matches!(record.health.as_str(), "healthy" | "active") {
            alerts.push(format!(
                "Channel {} is {} ({})",
                record.channel_id, record.health, record.status_detail
            ));
        }
        if let Some(item) = diagnostics.first() {
            if !matches!(
                item.status.as_str(),
                "delivered" | "acknowledged" | "queued"
            ) {
                alerts.push(format!(
                    "Channel {} last diagnostic is {} ({})",
                    record.channel_id, item.status, item.status_detail
                ));
            }
        }
    }
    Ok(serde_json::json!({
        "captured_at_unix_ms": now_unix_ms(),
        "agent": summary,
        "alerts": alerts,
        "channel_health": channel_health.iter().map(|(record, history, diagnostics)| serde_json::json!({
            "channel_id": record.channel_id,
            "kind": record.kind,
            "health": record.health,
            "ready": record.ready,
            "status_detail": record.status_detail,
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
            })).collect::<Vec<_>>(),
            "diagnostics": diagnostics.iter().map(|item| serde_json::json!({
                "diagnostic_id": item.diagnostic_id,
                "delivery_id": item.delivery_id,
                "status": item.status,
                "health": item.health,
                "ready": item.ready,
                "updated_at_unix_ms": item.updated_at_unix_ms,
                "status_detail": item.status_detail,
                "note": item.note,
            })).collect::<Vec<_>>(),
        })).collect::<Vec<_>>(),
        "recent_memory_receipts": recent_receipts.iter().map(|receipt| serde_json::json!({
            "operation": receipt.operation,
            "kind": receipt.kind,
            "timestamp_unix_ms": receipt.timestamp_unix_ms,
            "input_summary": receipt.input_summary,
            "output_summary": receipt.output_summary,
            "receipt_hash": receipt.receipt_hash,
        })).collect::<Vec<_>>(),
        "recent_deliveries": recent_deliveries.iter().map(|record| serde_json::json!({
            "delivery_id": record.delivery_id,
            "channel_id": record.channel_id,
            "status": record.status,
            "submitted_at_unix_ms": record.submitted_at_unix_ms,
            "recipient": record.recipient,
            "status_detail": record.status_detail,
        })).collect::<Vec<_>>(),
    }))
}

fn render_run_agent_inspect_human(payload: &serde_json::Value) -> String {
    let mut rendered = String::new();
    rendered.push_str("Meridian Loom // RUN AGENT INSPECT\n==================================\n");
    rendered.push_str(&format!(
        "name:                  {}\nslug:                  {}\nagent_id:              {}\nstatus:                {}\nsupervision_action:    {}\ncrash_state:           {}\nworker_pid:            {}\nsupervisor_pid:        {}\nprimary_channel:       {}\nrestart_policy:        {}\nrestart_backoff_sec:   {}\n\n",
        payload["agent"]["name"].as_str().unwrap_or(""),
        payload["agent"]["slug"].as_str().unwrap_or(""),
        payload["agent"]["agent_id"].as_str().unwrap_or(""),
        payload["agent"]["status"].as_str().unwrap_or(""),
        payload["agent"]["supervision_action"].as_str().unwrap_or(""),
        payload["agent"]["crash_state"].as_str().unwrap_or(""),
        payload["agent"]["worker_pid"].as_u64().unwrap_or_default(),
        payload["agent"]["supervisor_pid"].as_u64().unwrap_or_default(),
        payload["agent"]["primary_channel"].as_str().unwrap_or(""),
        payload["agent"]["restart_policy"].as_str().unwrap_or(""),
        payload["agent"]["restart_backoff_seconds"].as_u64().unwrap_or_default(),
    ));
    rendered.push_str("Alerts\n------\n");
    if let Some(alerts) = payload["alerts"].as_array() {
        if alerts.is_empty() {
            rendered.push_str("(none)\n");
        } else {
            for alert in alerts {
                rendered.push_str(&format!("- {}\n", alert.as_str().unwrap_or("")));
            }
        }
    }
    rendered.push_str("\nChannel health\n--------------\n");
    if let Some(channels) = payload["channel_health"].as_array() {
        if channels.is_empty() {
            rendered.push_str("(no configured delivery channels)\n");
        } else {
            for entry in channels {
                rendered.push_str(&format!(
                    "- {} kind={} health={} ready={} latest={} detail={}\n",
                    entry["channel_id"].as_str().unwrap_or(""),
                    entry["kind"].as_str().unwrap_or(""),
                    entry["health"].as_str().unwrap_or(""),
                    entry["ready"].as_bool().unwrap_or(false),
                    entry["latest_delivery_status"].as_str().unwrap_or(""),
                    entry["status_detail"]
                        .as_str()
                        .unwrap_or("")
                        .replace('\n', "\\n"),
                ));
                rendered.push_str("  history:\n");
                if let Some(history) = entry["history"].as_array() {
                    if history.is_empty() {
                        rendered.push_str("    (none)\n");
                    } else {
                        for item in history {
                            rendered.push_str(&format!(
                                "    - at={} trigger={} health={} latest={}\n",
                                item["captured_at_unix_ms"].as_u64().unwrap_or_default(),
                                item["trigger"].as_str().unwrap_or(""),
                                item["health"].as_str().unwrap_or(""),
                                item["latest_delivery_status"].as_str().unwrap_or(""),
                            ));
                        }
                    }
                }
                rendered.push_str("  diagnostics:\n");
                if let Some(diagnostics) = entry["diagnostics"].as_array() {
                    if diagnostics.is_empty() {
                        rendered.push_str("    (none)\n");
                    } else {
                        for item in diagnostics {
                            rendered.push_str(&format!(
                                "    - {} status={} health={} ready={} updated_at={}\n",
                                item["diagnostic_id"].as_str().unwrap_or(""),
                                item["status"].as_str().unwrap_or(""),
                                item["health"].as_str().unwrap_or(""),
                                item["ready"].as_bool().unwrap_or(false),
                                item["updated_at_unix_ms"].as_u64().unwrap_or_default(),
                            ));
                        }
                    }
                }
            }
        }
    }
    rendered.push_str("\nRecent memory receipts\n----------------------\n");
    if let Some(receipts) = payload["recent_memory_receipts"].as_array() {
        if receipts.is_empty() {
            rendered.push_str("(no memory receipts)\n");
        } else {
            for receipt in receipts {
                rendered.push_str(&format!(
                    "- {} kind={} at={} output={}\n",
                    receipt["operation"].as_str().unwrap_or(""),
                    receipt["kind"].as_str().unwrap_or(""),
                    receipt["timestamp_unix_ms"].as_u64().unwrap_or_default(),
                    receipt["output_summary"]
                        .as_str()
                        .unwrap_or("")
                        .replace('\n', "\\n"),
                ));
            }
        }
    }
    rendered.push_str("\nRecent deliveries\n-----------------\n");
    if let Some(deliveries) = payload["recent_deliveries"].as_array() {
        if deliveries.is_empty() {
            rendered.push_str("(no recent deliveries)\n");
        } else {
            for record in deliveries {
                rendered.push_str(&format!(
                    "- {} channel={} status={} recipient={} submitted_at={}\n",
                    record["delivery_id"].as_str().unwrap_or(""),
                    record["channel_id"].as_str().unwrap_or(""),
                    record["status"].as_str().unwrap_or(""),
                    record["recipient"].as_str().unwrap_or(""),
                    record["submitted_at_unix_ms"].as_u64().unwrap_or_default(),
                ));
            }
        }
    }
    rendered
}

fn render_run_agent_watch_human(
    payload: &serde_json::Value,
    frame_index: usize,
    continuous: bool,
) -> String {
    let mut rendered = String::new();
    rendered.push_str("Meridian Loom // RUN AGENT WATCH\n================================\n");
    rendered.push_str(&format!(
        "frame:                 {}\ncaptured_at_unix_ms:    {}\nname:                  {}\nstatus:                {}\nworker:                pid={} running={}\nsupervisor:            pid={} running={}\naction:                {}\ncrash_state:           {}\nprimary_channel:       {}\n",
        frame_index,
        payload["captured_at_unix_ms"].as_u64().unwrap_or_default(),
        payload["agent"]["name"].as_str().unwrap_or(""),
        payload["agent"]["status"].as_str().unwrap_or(""),
        payload["agent"]["worker_pid"].as_u64().unwrap_or_default(),
        payload["agent"]["worker_running"].as_bool().unwrap_or(false),
        payload["agent"]["supervisor_pid"].as_u64().unwrap_or_default(),
        payload["agent"]["supervisor_running"].as_bool().unwrap_or(false),
        payload["agent"]["supervision_action"].as_str().unwrap_or(""),
        payload["agent"]["crash_state"].as_str().unwrap_or(""),
        payload["agent"]["primary_channel"].as_str().unwrap_or(""),
    ));
    if continuous {
        rendered.push_str("hint: press Ctrl+C to exit watch mode\n");
    }
    rendered.push_str("\nalerts\n------\n");
    if let Some(alerts) = payload["alerts"].as_array() {
        if alerts.is_empty() {
            rendered.push_str("(none)\n");
        } else {
            for alert in alerts.iter().take(3) {
                rendered.push_str(&format!("- {}\n", alert.as_str().unwrap_or("")));
            }
        }
    }
    rendered.push_str("\nchannels\n--------\n");
    if let Some(channels) = payload["channel_health"].as_array() {
        if channels.is_empty() {
            rendered.push_str("(no configured delivery channels)\n");
        } else {
            for entry in channels {
                let latest_diag = entry["diagnostics"]
                    .as_array()
                    .and_then(|items| items.first())
                    .map(|item| {
                        format!(
                            "diag={} / {}",
                            item["status"].as_str().unwrap_or(""),
                            item["health"].as_str().unwrap_or("")
                        )
                    })
                    .unwrap_or_else(|| "diag=none".to_string());
                rendered.push_str(&format!(
                    "- {} {} ready={} latest={} {}\n",
                    entry["channel_id"].as_str().unwrap_or(""),
                    entry["health"].as_str().unwrap_or(""),
                    entry["ready"].as_bool().unwrap_or(false),
                    entry["latest_delivery_status"].as_str().unwrap_or(""),
                    latest_diag,
                ));
            }
        }
    }
    rendered.push_str("\nrecent receipts\n---------------\n");
    if let Some(receipts) = payload["recent_memory_receipts"].as_array() {
        if receipts.is_empty() {
            rendered.push_str("(none)\n");
        } else {
            for receipt in receipts.iter().take(3) {
                rendered.push_str(&format!(
                    "- {} {} at={}\n",
                    receipt["operation"].as_str().unwrap_or(""),
                    receipt["kind"].as_str().unwrap_or(""),
                    receipt["timestamp_unix_ms"].as_u64().unwrap_or_default(),
                ));
            }
        }
    }
    rendered.push_str("\nrecent deliveries\n-----------------\n");
    if let Some(deliveries) = payload["recent_deliveries"].as_array() {
        if deliveries.is_empty() {
            rendered.push_str("(none)\n");
        } else {
            for record in deliveries.iter().take(3) {
                rendered.push_str(&format!(
                    "- {} {} {}\n",
                    record["channel_id"].as_str().unwrap_or(""),
                    record["status"].as_str().unwrap_or(""),
                    record["recipient"].as_str().unwrap_or(""),
                ));
            }
        }
    }
    rendered
}

fn recommended_action(command: String, reason: &str) -> serde_json::Value {
    serde_json::json!({
        "command": command,
        "reason": reason,
    })
}

fn build_run_agent_diagnose_payload(
    root: &Path,
    config: &PersonalAgentConfig,
    receipt_limit: usize,
    delivery_limit: usize,
    history_limit: usize,
    diagnostic_limit: usize,
) -> LoomResult<serde_json::Value> {
    let mut payload = build_run_agent_operator_payload(
        root,
        config,
        receipt_limit,
        delivery_limit,
        history_limit,
        diagnostic_limit,
    )?;
    let agent = &payload["agent"];
    let slug = agent["slug"].as_str().unwrap_or(&config.slug);
    let supervision_action = agent["supervision_action"]
        .as_str()
        .unwrap_or("stopped_by_policy");
    let stop_requested = agent["stop_requested"].as_bool().unwrap_or(false);
    let last_crash_reason = agent["last_crash_reason"].as_str().unwrap_or("");
    let next_restart_after_unix_ms = agent["next_restart_after_unix_ms"]
        .as_u64()
        .unwrap_or_default();
    let worker_running = agent["worker_running"].as_bool().unwrap_or(false);
    let channels = payload["channel_health"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    let no_channels = channels.is_empty();
    let degraded_channels = channels
        .iter()
        .filter(|entry| !matches!(entry["health"].as_str().unwrap_or(""), "healthy" | "active"))
        .map(|entry| entry["channel_id"].as_str().unwrap_or("").to_string())
        .filter(|value| !value.is_empty())
        .collect::<Vec<_>>();
    let failed_diagnostics = channels
        .iter()
        .filter_map(|entry| {
            let channel_id = entry["channel_id"].as_str().unwrap_or("").trim();
            let diagnostic = entry["diagnostics"]
                .as_array()
                .and_then(|items| items.first())?;
            let status = diagnostic["status"].as_str().unwrap_or("").trim();
            if matches!(status, "delivered" | "acknowledged" | "queued") {
                return None;
            }
            Some(format!(
                "{}:{}",
                channel_id,
                if status.is_empty() { "unknown" } else { status }
            ))
        })
        .collect::<Vec<_>>();
    let no_memory_receipts = payload["recent_memory_receipts"]
        .as_array()
        .map(|items| items.is_empty())
        .unwrap_or(true);

    let mut status = "healthy".to_string();
    let mut severity = "ok".to_string();
    let mut summary =
        "Agent is supervised, channel-ready, and emitting governed receipts.".to_string();
    if stop_requested {
        status = "stop_requested".to_string();
        severity = "attention".to_string();
        summary =
            "A stop request is pending. The supervisor should drain and stop the worker cleanly."
                .to_string();
    } else if supervision_action == "manual_restart_required" {
        status = "worker_crashed_manual_policy".to_string();
        severity = "action_required".to_string();
        summary = format!(
            "The worker crashed under manual restart policy. Operator action is required before the agent can resume{}.",
            if last_crash_reason.is_empty() {
                String::new()
            } else {
                format!(" ({})", last_crash_reason)
            }
        );
    } else if supervision_action == "waiting_backoff" {
        status = "restart_backoff_active".to_string();
        severity = "attention".to_string();
        summary = format!(
            "The supervisor is backing off before relaunching the worker. Next restart is scheduled at unix_ms={}.",
            next_restart_after_unix_ms
        );
    } else if supervision_action == "needs_restart" {
        status = "worker_down_restart_available".to_string();
        severity = "action_required".to_string();
        summary =
            "The worker is down and eligible for restart under the current supervision policy."
                .to_string();
    } else if no_channels {
        status = "no_delivery_channel".to_string();
        severity = "attention".to_string();
        summary =
            "The agent can run, but no delivery channel is configured, so no operator-visible output can leave Loom."
                .to_string();
    } else if !failed_diagnostics.is_empty() {
        status = "channel_diagnostic_failed".to_string();
        severity = "attention".to_string();
        summary = format!(
            "Recent channel diagnostics failed for {}.",
            failed_diagnostics.join(", ")
        );
    } else if !degraded_channels.is_empty() {
        status = "channel_degraded".to_string();
        severity = "attention".to_string();
        summary = format!(
            "One or more delivery channels are degraded: {}.",
            degraded_channels.join(", ")
        );
    } else if !worker_running {
        status = "supervisor_idle".to_string();
        severity = "attention".to_string();
        summary =
            "The worker is not currently running. Inspect the loop state and reconcile if this is unexpected."
                .to_string();
    } else if no_memory_receipts {
        status = "memory_receipts_missing".to_string();
        severity = "attention".to_string();
        summary =
            "The agent is running, but no recent memory receipts were found. The memory loop may not have warmed up yet."
                .to_string();
    }

    let mut actions = Vec::new();
    match status.as_str() {
        "worker_crashed_manual_policy" => {
            actions.push(recommended_action(
                format!("loom run-agent reconcile {}", slug),
                "Start a fresh supervised worker under the current policy.",
            ));
            actions.push(recommended_action(
                format!("loom run-agent inspect {}", slug),
                "Review recent receipts, deliveries, and crash context before restarting again.",
            ));
            actions.push(recommended_action(
                format!(
                    "loom doctor --root \"{}\" --format human --fix",
                    config.loom_root
                ),
                "Apply safe runtime scaffold repairs if the local state looks inconsistent after the crash.",
            ));
        }
        "restart_backoff_active" => {
            actions.push(recommended_action(
                format!("loom run-agent watch {}", slug),
                "Watch the next restart window and confirm the worker recovers cleanly after backoff.",
            ));
            actions.push(recommended_action(
                format!("loom run-agent inspect {}", slug),
                "Inspect crash details, recent memory receipts, and delivery health while the supervisor is waiting.",
            ));
            actions.push(recommended_action(
                format!(
                    "loom channel health --agent {} --history-limit 5 --diagnostic-limit 5",
                    slug
                ),
                "Confirm channel health is not contributing to repeated restart loops.",
            ));
        }
        "worker_down_restart_available" | "supervisor_idle" => {
            actions.push(recommended_action(
                format!("loom run-agent reconcile {}", slug),
                "Relaunch the supervised worker if the agent should still be serving.",
            ));
            actions.push(recommended_action(
                format!("loom run-agent inspect {}", slug),
                "Review the current loop state before and after reconcile.",
            ));
            actions.push(recommended_action(
                format!(
                    "loom doctor --root \"{}\" --format human --fix",
                    config.loom_root
                ),
                "Refresh safe runtime scaffolding if the agent should be running but state files drifted.",
            ));
        }
        "no_delivery_channel" => {
            actions.push(recommended_action(
                format!("loom channel show --agent {}", slug),
                "Inspect the current channel config for this agent.",
            ));
            actions.push(recommended_action(
                format!(
                    "loom channel connect webhook --agent {} --url https://example.com/hook",
                    slug
                ),
                "Attach a webhook so the agent can emit governed outbound deliveries immediately.",
            ));
            actions.push(recommended_action(
                format!(
                    "loom channel connect telegram --agent {} --chat-id <telegram-chat-id>",
                    slug
                ),
                "Attach Telegram if you want operator-visible delivery on chat instead of webhook.",
            ));
        }
        "channel_diagnostic_failed" | "channel_degraded" => {
            actions.push(recommended_action(
                format!(
                    "loom channel health --agent {} --history-limit 5 --diagnostic-limit 5",
                    slug
                ),
                "Inspect recent health transitions and failed diagnostics for the affected channels.",
            ));
            actions.push(recommended_action(
                format!(
                    "loom channel test --agent {} --text \"diagnostic ping\"",
                    slug
                ),
                "Queue a fresh diagnostic delivery on the agent's primary channel.",
            ));
            actions.push(recommended_action(
                format!("loom run-agent inspect {}", slug),
                "Cross-check channel issues against recent receipts and deliveries from the agent loop.",
            ));
        }
        "stop_requested" => {
            actions.push(recommended_action(
                format!("loom run-agent status {}", slug),
                "Confirm the loop drains and transitions to a stopped state cleanly.",
            ));
            actions.push(recommended_action(
                format!("loom run-agent watch {}", slug),
                "Follow the stop transition in real time instead of polling raw state files.",
            ));
        }
        "memory_receipts_missing" => {
            actions.push(recommended_action(
                format!("loom run-agent {} --foreground --once", slug),
                "Force a single governed loop tick so memory sync and recall can emit receipts.",
            ));
            actions.push(recommended_action(
                format!(
                    "loom memory receipts --root \"{}\" --agent-id {}",
                    config.loom_root, config.agent_id
                ),
                "Inspect read/write receipt history directly for this agent.",
            ));
            actions.push(recommended_action(
                format!("loom run-agent inspect {}", slug),
                "Confirm memory receipts appear in the operator view after the next tick.",
            ));
        }
        _ => {
            actions.push(recommended_action(
                format!("loom run-agent watch {}", slug),
                "Keep a live operator view on the agent, channels, and receipts.",
            ));
            actions.push(recommended_action(
                format!("loom run-agent inspect {}", slug),
                "Inspect deeper delivery and memory detail on demand.",
            ));
        }
    }

    if let Some(object) = payload.as_object_mut() {
        object.insert(
            "diagnosis".to_string(),
            serde_json::json!({
                "status": status,
                "severity": severity,
                "summary": summary,
            }),
        );
        object.insert(
            "recommended_actions".to_string(),
            serde_json::Value::Array(actions),
        );
    }
    Ok(payload)
}

fn render_run_agent_diagnose_human(payload: &serde_json::Value) -> String {
    let mut rendered = String::new();
    rendered.push_str("Meridian Loom // RUN AGENT DIAGNOSE\n===================================\n");
    rendered.push_str(&format!(
        "name:                  {}\nslug:                  {}\nagent_id:              {}\nstatus:                {}\ndiagnosis:             {}\nseverity:              {}\nsupervision_action:    {}\ncrash_state:           {}\nworker_pid:            {}\nsupervisor_pid:        {}\nprimary_channel:       {}\n\nsummary: {}\n",
        payload["agent"]["name"].as_str().unwrap_or(""),
        payload["agent"]["slug"].as_str().unwrap_or(""),
        payload["agent"]["agent_id"].as_str().unwrap_or(""),
        payload["agent"]["status"].as_str().unwrap_or(""),
        payload["diagnosis"]["status"].as_str().unwrap_or(""),
        payload["diagnosis"]["severity"].as_str().unwrap_or(""),
        payload["agent"]["supervision_action"].as_str().unwrap_or(""),
        payload["agent"]["crash_state"].as_str().unwrap_or(""),
        payload["agent"]["worker_pid"].as_u64().unwrap_or_default(),
        payload["agent"]["supervisor_pid"].as_u64().unwrap_or_default(),
        payload["agent"]["primary_channel"].as_str().unwrap_or(""),
        payload["diagnosis"]["summary"].as_str().unwrap_or(""),
    ));
    rendered.push_str("\nAlerts\n------\n");
    if let Some(alerts) = payload["alerts"].as_array() {
        if alerts.is_empty() {
            rendered.push_str("(none)\n");
        } else {
            for alert in alerts {
                rendered.push_str(&format!("- {}\n", alert.as_str().unwrap_or("")));
            }
        }
    }
    rendered.push_str("\nRecommended actions\n-------------------\n");
    if let Some(actions) = payload["recommended_actions"].as_array() {
        if actions.is_empty() {
            rendered.push_str("(none)\n");
        } else {
            for (index, action) in actions.iter().enumerate() {
                rendered.push_str(&format!(
                    "{}. {}\n   reason: {}\n",
                    index + 1,
                    action["command"].as_str().unwrap_or(""),
                    action["reason"].as_str().unwrap_or(""),
                ));
            }
        }
    }
    rendered
}

fn handle_run_agent_inspect(args: &[String]) -> LoomResult<()> {
    let Some(name_or_slug) = positional_name(args) else {
        return Err("run-agent inspect requires an agent name or slug".to_string());
    };
    let config = load_personal_agent_config(&name_or_slug)?;
    let root = root_from(Some(&config.loom_root))?;
    let receipt_limit = take_value(args, "--receipt-limit")
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(5);
    let delivery_limit = take_value(args, "--delivery-limit")
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(5);
    let history_limit = take_value(args, "--history-limit")
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(5);
    let diagnostic_limit = take_value(args, "--diagnostic-limit")
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(3);
    let payload = build_run_agent_operator_payload(
        &root,
        &config,
        receipt_limit,
        delivery_limit,
        history_limit,
        diagnostic_limit,
    )?;
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    match format.as_str() {
        "json" => print!(
            "{}\n",
            serde_json::to_string_pretty(&payload).map_err(|error| error.to_string())?
        ),
        _ => {
            print_startup_banner();
            print_human(&render_run_agent_inspect_human(&payload));
        }
    }
    Ok(())
}

fn handle_run_agent_diagnose(args: &[String]) -> LoomResult<()> {
    let Some(name_or_slug) = positional_name(args) else {
        return Err("run-agent diagnose requires an agent name or slug".to_string());
    };
    let config = load_personal_agent_config(&name_or_slug)?;
    let root = root_from(Some(&config.loom_root))?;
    let receipt_limit = take_value(args, "--receipt-limit")
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(5);
    let delivery_limit = take_value(args, "--delivery-limit")
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(5);
    let history_limit = take_value(args, "--history-limit")
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(5);
    let diagnostic_limit = take_value(args, "--diagnostic-limit")
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(3);
    let payload = build_run_agent_diagnose_payload(
        &root,
        &config,
        receipt_limit,
        delivery_limit,
        history_limit,
        diagnostic_limit,
    )?;
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    match format.as_str() {
        "json" => print!(
            "{}\n",
            serde_json::to_string_pretty(&payload).map_err(|error| error.to_string())?
        ),
        _ => {
            print_startup_banner();
            print_human(&render_run_agent_diagnose_human(&payload));
        }
    }
    Ok(())
}

fn handle_run_agent_watch(args: &[String]) -> LoomResult<()> {
    let Some(name_or_slug) = positional_name(args) else {
        return Err("run-agent watch requires an agent name or slug".to_string());
    };
    let config = load_personal_agent_config(&name_or_slug)?;
    let root = root_from(Some(&config.loom_root))?;
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let once = has_flag(args, "--once");
    let iterations = if once {
        1
    } else {
        take_value(args, "--iterations")
            .and_then(|value| value.parse::<usize>().ok())
            .unwrap_or(if format == "json" { 1 } else { 0 })
    };
    let poll_seconds = take_value(args, "--poll-seconds")
        .and_then(|value| value.parse::<u64>().ok())
        .unwrap_or(2)
        .max(1);
    let receipt_limit = take_value(args, "--receipt-limit")
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(3);
    let delivery_limit = take_value(args, "--delivery-limit")
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(3);
    let history_limit = take_value(args, "--history-limit")
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(3);
    let diagnostic_limit = take_value(args, "--diagnostic-limit")
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(2);
    let clear_each_frame =
        format == "human" && std::io::stdout().is_terminal() && !has_flag(args, "--no-clear");
    let mut frame = 0usize;
    let mut snapshots = Vec::new();
    loop {
        frame = frame.saturating_add(1);
        let payload = build_run_agent_operator_payload(
            &root,
            &config,
            receipt_limit,
            delivery_limit,
            history_limit,
            diagnostic_limit,
        )?;
        if format == "json" {
            snapshots.push(payload);
        } else {
            if clear_each_frame {
                print!("\x1b[2J\x1b[H");
                let _ = std::io::Write::flush(&mut std::io::stdout());
            }
            print_startup_banner();
            print_human(&render_run_agent_watch_human(
                &payload,
                frame,
                iterations == 0,
            ));
        }
        if iterations != 0 && frame >= iterations {
            break;
        }
        thread::sleep(Duration::from_secs(poll_seconds));
    }
    if format == "json" {
        if snapshots.len() == 1 {
            print!(
                "{}\n",
                serde_json::to_string_pretty(&snapshots.remove(0))
                    .map_err(|error| error.to_string())?
            );
        } else {
            print!(
                "{}\n",
                serde_json::to_string_pretty(&snapshots).map_err(|error| error.to_string())?
            );
        }
    }
    Ok(())
}

fn handle_run_agent_supervise(args: &[String]) -> LoomResult<()> {
    let Some(name_or_slug) = positional_name(args) else {
        return Err("run-agent supervise requires an agent name or slug".to_string());
    };
    let config = load_personal_agent_config(&name_or_slug)?;
    let root = root_from(Some(&config.loom_root))?;
    let poll_seconds = take_value(args, "--poll-seconds")
        .and_then(|value| value.parse::<u64>().ok())
        .unwrap_or(15)
        .max(1);
    run_agent_supervisor_loop(&root, &config, poll_seconds)
}

fn handle_run_agent_stop(args: &[String]) -> LoomResult<()> {
    let Some(name_or_slug) = positional_name(args) else {
        return Err("run-agent stop requires an agent name or slug".to_string());
    };
    let config = load_personal_agent_config(&name_or_slug)?;
    let root = root_from(Some(&config.loom_root))?;
    let state_path = personal_agent_state_path(&root, &config.slug)?;
    let policy_path = personal_agent_policy_path(&root, &config.slug)?;
    let state = load_loop_state(&state_path)?;
    let mut policy = load_run_policy(&policy_path, &config)?;
    policy.desired_state = "stopped".to_string();
    policy.next_restart_after_unix_ms = 0;
    policy.last_exit_status = "operator requested stop".to_string();
    write_run_policy(&policy_path, &policy)?;
    let stop_path = write_stop_request(&root, &config.slug)?;
    let running = state
        .as_ref()
        .map(|state| pid_is_running(state.pid))
        .unwrap_or(false);
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let payload = serde_json::json!({
        "status": if running { "stop_requested" } else { "stop_written_no_process" },
        "name": config.display_name,
        "slug": config.slug,
        "agent_id": config.agent_id,
        "pid": state.as_ref().map(|state| state.pid).unwrap_or_default(),
        "stop_request_path": stop_path.display().to_string(),
    });
    match format.as_str() {
        "json" => {
            print!(
                "{}\n",
                serde_json::to_string_pretty(&payload).map_err(|error| error.to_string())?
            );
        }
        _ => {
            print_startup_banner();
            print_human(&format!(
                "Meridian Loom // RUN AGENT STOP\n===============================\nname:              {}\nslug:              {}\nagent_id:          {}\nstatus:            {}\npid:               {}\nstop_request_path: {}\n",
                payload["name"].as_str().unwrap_or(""),
                payload["slug"].as_str().unwrap_or(""),
                payload["agent_id"].as_str().unwrap_or(""),
                payload["status"].as_str().unwrap_or(""),
                payload["pid"].as_u64().unwrap_or_default(),
                payload["stop_request_path"].as_str().unwrap_or(""),
            ));
        }
    }
    Ok(())
}

fn handle_run_agent_reconcile(args: &[String]) -> LoomResult<()> {
    let Some(name_or_slug) = positional_name(args) else {
        return Err("run-agent reconcile requires an agent name or slug".to_string());
    };
    let config = load_personal_agent_config(&name_or_slug)?;
    let root = root_from(Some(&config.loom_root))?;
    let summary = build_run_agent_summary(&root, &config)?;
    let poll_seconds = take_value(args, "--poll-seconds")
        .and_then(|value| value.parse::<u64>().ok())
        .unwrap_or(15);
    let format = take_value(args, "--format").unwrap_or_else(|| "human".to_string());
    let action = if summary["running"].as_bool().unwrap_or(false) {
        "already_running".to_string()
    } else {
        match summary["supervision_action"]
            .as_str()
            .unwrap_or("stopped_by_policy")
        {
            "needs_restart" | "manual_restart_required" => {
                let child = spawn_run_agent_supervisor(
                    &root,
                    &config,
                    poll_seconds,
                    summary["restart_policy"]
                        .as_str()
                        .unwrap_or(DEFAULT_PERSONAL_RESTART_POLICY),
                    summary["restart_backoff_seconds"]
                        .as_u64()
                        .unwrap_or(DEFAULT_PERSONAL_RESTART_BACKOFF_SECONDS),
                )?;
                format!("supervisor_started pid={}", child.id())
            }
            "waiting_backoff" => "waiting_backoff".to_string(),
            "supervisor_active" => "supervisor_active".to_string(),
            "stopped_by_policy" => "stopped_by_policy".to_string(),
            other => other.to_string(),
        }
    };
    let payload = serde_json::json!({
        "name": config.display_name,
        "slug": config.slug,
        "agent_id": config.agent_id,
        "action": action,
        "supervision_action": summary["supervision_action"],
        "desired_state": summary["desired_state"],
        "restart_policy": summary["restart_policy"],
        "restart_backoff_seconds": summary["restart_backoff_seconds"],
    });
    match format.as_str() {
        "json" => print!(
            "{}\n",
            serde_json::to_string_pretty(&payload).map_err(|error| error.to_string())?
        ),
        _ => {
            print_startup_banner();
            print_human(&format!(
                "Meridian Loom // RUN AGENT RECONCILE\n====================================\nname:              {}\nslug:              {}\nagent_id:          {}\naction:            {}\nsupervision_action:{}\ndesired_state:     {}\nrestart_policy:    {}\nrestart_backoff:   {}s\n",
                payload["name"].as_str().unwrap_or(""),
                payload["slug"].as_str().unwrap_or(""),
                payload["agent_id"].as_str().unwrap_or(""),
                payload["action"].as_str().unwrap_or(""),
                payload["supervision_action"].as_str().unwrap_or(""),
                payload["desired_state"].as_str().unwrap_or(""),
                payload["restart_policy"].as_str().unwrap_or(""),
                payload["restart_backoff_seconds"].as_u64().unwrap_or_default(),
            ));
        }
    }
    Ok(())
}

fn print_new_agent_help() {
    print_human(
        "Meridian Loom // NEW AGENT HELP
==================================
USAGE:
  loom new-agent --name \"My Assistant\" [OPTIONS]

PURPOSE:
  Provision a governed personal agent on Loom, register it in Kernel with
  runtime_binding=loom_native, create a local runtime profile, and write a
  personal agent folder under ~/.config/meridian-loom/agents/<slug>/ with
  agent.toml, README.md, MEMORY.md, and SOUL.md

OPTIONS:
  --name NAME              Required display name for the new agent
  --root PATH              Loom runtime root (defaults to the standard local root)
  --kernel-path PATH       Meridian Kernel path (defaults to /opt/meridian-kernel when present)
  --org-id ORG             Institution/org id to bind
  --role ROLE              Kernel role (default: manager)
  --purpose TEXT           Purpose statement stored in Kernel
  --provider-profile NAME  Loom provider profile (default: local_ollama)
  --tool-scope NAME        Loom tool scope (default: personal_agent_scope)
  --telegram-chat-id ID    Seed Telegram delivery target
  --webhook-url URL        Seed webhook delivery target
  --webhook-header TEXT    Optional inline header for the webhook channel
  --format human|json      Output format
",
    );
}

fn print_run_agent_help() {
    print_human(
        "Meridian Loom // RUN AGENT HELP
==================================
USAGE:
  loom run-agent <name-or-slug> [OPTIONS]

PURPOSE:
  Start a persistent governed personal agent loop. The loop keeps Loom service
  and supervisor ready, syncs SOUL/MEMORY/config into governed memory with
  receipts, claims due heartbeats, dispatches them through the governed
  runtime, and writes loop state under the runtime root.

SUBCOMMANDS:
  status <name-or-slug>     Show loop state, worker/supervisor pids, and crash semantics
  inspect <name-or-slug>    Show operator-facing state, channel health history, diagnostics, and receipts
  diagnose <name-or-slug>   Turn crash/channel state into a concrete remediation plan
  watch <name-or-slug>      Compact terminal dashboard that refreshes agent/operator state
  stop <name-or-slug>       Write a graceful stop request for the running loop
  reconcile <name-or-slug>  Restart a dead background loop when policy allows it
  supervise <name-or-slug>  Internal supervisor entrypoint (can also be run directly)

OPTIONS:
  --foreground             Run the loop in the current terminal
  --loop                   Internal flag used by the background daemon mode
  --poll-seconds N         Loop polling interval (default: 15)
  --once                   Run a single loop tick, then exit
  --restart-policy POLICY  Restart policy for background mode: manual|always
  --restart-backoff-seconds N
                           Backoff before reconcile can restart the loop
  --iterations N          Bound run-agent watch to N frames (default: infinite in human mode)
  --no-clear              Keep watch output appended instead of refreshing the terminal
",
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};

    static TEST_COUNTER: AtomicU64 = AtomicU64::new(0);

    fn temp_root(label: &str) -> PathBuf {
        let n = TEST_COUNTER.fetch_add(1, Ordering::SeqCst);
        let dir = std::env::temp_dir().join(format!(
            "loom_personal_agent_{}_{}_{}",
            label,
            std::process::id(),
            n
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).expect("create temp root");
        dir
    }

    #[test]
    fn personal_agent_slug_is_sanitized() {
        assert_eq!(sanitize_personal_slug("My Assistant"), "my-assistant");
        assert_eq!(sanitize_personal_slug("  Meridian+Bot  "), "meridian-bot");
    }

    #[test]
    fn personal_agent_config_roundtrip_keeps_core_fields() {
        let config = PersonalAgentConfig {
            name: "My Assistant".to_string(),
            slug: "my-assistant".to_string(),
            agent_id: "agent_my_123".to_string(),
            display_name: "My Assistant".to_string(),
            role: "manager".to_string(),
            purpose: "Governed personal agent".to_string(),
            provider_profile: "local_ollama".to_string(),
            tool_scope: "personal_agent_scope".to_string(),
            org_id: "local_foundry".to_string(),
            loom_root: "/tmp/loom".to_string(),
            kernel_path: "/opt/meridian-kernel".to_string(),
            service_http_address: "127.0.0.1:18910".to_string(),
            service_token: "token".to_string(),
            heartbeat_capability: "loom.system.info.v1".to_string(),
            heartbeat_every_seconds: 300,
            restart_policy: DEFAULT_PERSONAL_RESTART_POLICY.to_string(),
            restart_backoff_seconds: DEFAULT_PERSONAL_RESTART_BACKOFF_SECONDS,
            telegram_enabled: false,
            telegram_chat_id: String::new(),
            telegram_token_env: DEFAULT_TELEGRAM_TOKEN_ENV.to_string(),
            webhook_enabled: true,
            webhook_url: "https://example.com/hook".to_string(),
            webhook_header: "Authorization: Bearer test".to_string(),
        };
        let rendered = render_personal_agent_config(&config);
        let temp = std::env::temp_dir().join(format!(
            "loom_personal_agent_config_{}_{}.toml",
            std::process::id(),
            chrono_like_timestamp()
        ));
        fs::write(&temp, rendered).expect("write config");
        let parsed = parse_personal_agent_config(&temp).expect("parse config");
        fs::remove_file(&temp).ok();
        assert_eq!(parsed.agent_id, config.agent_id);
        assert_eq!(parsed.webhook_url, config.webhook_url);
        assert_eq!(parsed.provider_profile, config.provider_profile);
    }

    #[test]
    fn personal_agent_memory_sync_tracks_file_changes() {
        let root = temp_root("memory_sync");
        let slug = format!(
            "my-assistant-{}",
            TEST_COUNTER.fetch_add(1, Ordering::SeqCst)
        );
        let config = PersonalAgentConfig {
            name: "My Assistant".to_string(),
            slug: slug.clone(),
            agent_id: "agent_my_123".to_string(),
            display_name: "My Assistant".to_string(),
            role: "manager".to_string(),
            purpose: "Governed personal agent".to_string(),
            provider_profile: "local_ollama".to_string(),
            tool_scope: "personal_agent_scope".to_string(),
            org_id: "local_foundry".to_string(),
            loom_root: root.display().to_string(),
            kernel_path: "/opt/meridian-kernel".to_string(),
            service_http_address: "127.0.0.1:18910".to_string(),
            service_token: "token".to_string(),
            heartbeat_capability: "loom.system.info.v1".to_string(),
            heartbeat_every_seconds: 300,
            restart_policy: DEFAULT_PERSONAL_RESTART_POLICY.to_string(),
            restart_backoff_seconds: DEFAULT_PERSONAL_RESTART_BACKOFF_SECONDS,
            telegram_enabled: true,
            telegram_chat_id: "12345".to_string(),
            telegram_token_env: DEFAULT_TELEGRAM_TOKEN_ENV.to_string(),
            webhook_enabled: false,
            webhook_url: String::new(),
            webhook_header: String::new(),
        };
        let config_path = personal_agent_config_path(&slug).expect("config path");
        write_personal_agent_config(&config_path, &config).expect("write config");
        write_personal_agent_support_files(&config_path, &config).expect("support files");

        let first = sync_personal_agent_memory(&root, &config).expect("first sync");
        assert!(first.changed_count >= 3);
        assert!(first.recalled_count >= 3);

        let second = sync_personal_agent_memory(&root, &config).expect("second sync");
        assert_eq!(second.changed_count, 0);

        let memory_file = config_path.parent().expect("agent dir").join("MEMORY.md");
        fs::write(&memory_file, "# changed\nnew durable fact\n").expect("write memory");
        let third = sync_personal_agent_memory(&root, &config).expect("third sync");
        assert!(third.changed_count >= 1);

        fs::remove_dir_all(&root).ok();
        fs::remove_dir_all(config_path.parent().expect("agent dir").to_path_buf()).ok();
    }

    #[test]
    fn compact_memory_body_marks_truncation() {
        let body = "a".repeat(13_000);
        let compacted = compact_memory_body(&body);
        assert!(compacted.contains("truncated"));
        assert!(compacted.len() < body.len());
    }

    #[test]
    fn personal_agent_chaos_directive_parser_accepts_supported_shape() {
        let directive =
            parse_personal_agent_chaos_directive("after_tick:once:91").expect("directive");
        assert_eq!(directive.phase, "after_tick");
        assert_eq!(directive.mode, "once");
        assert_eq!(directive.exit_code, 91);
        assert!(parse_personal_agent_chaos_directive("after_tick:weird:91").is_none());
        assert!(parse_personal_agent_chaos_directive("after_tick:once:0").is_none());
    }

    #[test]
    fn run_policy_defaults_and_roundtrip_are_stable() {
        let config = PersonalAgentConfig {
            name: "My Assistant".to_string(),
            slug: "my-assistant".to_string(),
            agent_id: "agent_my_123".to_string(),
            display_name: "My Assistant".to_string(),
            role: "manager".to_string(),
            purpose: "Governed personal agent".to_string(),
            provider_profile: "local_ollama".to_string(),
            tool_scope: "personal_agent_scope".to_string(),
            org_id: "local_foundry".to_string(),
            loom_root: "/tmp/loom".to_string(),
            kernel_path: "/opt/meridian-kernel".to_string(),
            service_http_address: "127.0.0.1:18910".to_string(),
            service_token: "token".to_string(),
            heartbeat_capability: "loom.system.info.v1".to_string(),
            heartbeat_every_seconds: 300,
            restart_policy: "always".to_string(),
            restart_backoff_seconds: 45,
            telegram_enabled: false,
            telegram_chat_id: String::new(),
            telegram_token_env: DEFAULT_TELEGRAM_TOKEN_ENV.to_string(),
            webhook_enabled: false,
            webhook_url: String::new(),
            webhook_header: String::new(),
        };
        let root = temp_root("run_policy");
        let policy_path = personal_agent_policy_path(&root, &config.slug).expect("policy path");
        let mut policy = default_run_policy(&config);
        policy.desired_state = "running".to_string();
        policy.last_exit_status = "completed_once".to_string();
        write_run_policy(&policy_path, &policy).expect("write policy");
        let loaded = load_run_policy(&policy_path, &config).expect("load policy");
        assert_eq!(loaded.restart_policy, "always");
        assert_eq!(loaded.restart_backoff_seconds, 45);
        assert_eq!(loaded.desired_state, "running");
        assert_eq!(supervision_action(&loaded, 0), "needs_restart");
        fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn supervision_action_tracks_manual_and_backoff_states() {
        let config = PersonalAgentConfig {
            name: "My Assistant".to_string(),
            slug: "my-assistant".to_string(),
            agent_id: "agent_my_123".to_string(),
            display_name: "My Assistant".to_string(),
            role: "manager".to_string(),
            purpose: "Governed personal agent".to_string(),
            provider_profile: "local_ollama".to_string(),
            tool_scope: "personal_agent_scope".to_string(),
            org_id: "local_foundry".to_string(),
            loom_root: "/tmp/loom".to_string(),
            kernel_path: "/opt/meridian-kernel".to_string(),
            service_http_address: "127.0.0.1:18910".to_string(),
            service_token: "token".to_string(),
            heartbeat_capability: "loom.system.info.v1".to_string(),
            heartbeat_every_seconds: 300,
            restart_policy: "manual".to_string(),
            restart_backoff_seconds: 45,
            telegram_enabled: false,
            telegram_chat_id: String::new(),
            telegram_token_env: DEFAULT_TELEGRAM_TOKEN_ENV.to_string(),
            webhook_enabled: false,
            webhook_url: String::new(),
            webhook_header: String::new(),
        };
        let mut policy = default_run_policy(&config);
        policy.desired_state = "running".to_string();
        policy.last_crash_unix_ms = 42;
        policy.failure_count = 1;
        assert_eq!(supervision_action(&policy, 100), "manual_restart_required");
        assert_eq!(
            derive_crash_state(&policy, false, false, 100),
            "manual_restart_required"
        );

        policy.restart_policy = "always".to_string();
        policy.next_restart_after_unix_ms = 200;
        assert_eq!(supervision_action(&policy, 100), "waiting_backoff");
        assert_eq!(
            derive_crash_state(&policy, false, false, 100),
            "awaiting_restart"
        );
    }

    #[test]
    fn build_run_agent_summary_exposes_supervisor_and_worker_state() {
        let root = temp_root("summary_state");
        let config = PersonalAgentConfig {
            name: "My Assistant".to_string(),
            slug: "my-assistant-summary".to_string(),
            agent_id: "agent_summary_123".to_string(),
            display_name: "My Assistant".to_string(),
            role: "manager".to_string(),
            purpose: "Governed personal agent".to_string(),
            provider_profile: "local_ollama".to_string(),
            tool_scope: "personal_agent_scope".to_string(),
            org_id: "local_foundry".to_string(),
            loom_root: root.display().to_string(),
            kernel_path: "/opt/meridian-kernel".to_string(),
            service_http_address: "127.0.0.1:18910".to_string(),
            service_token: "token".to_string(),
            heartbeat_capability: "loom.system.info.v1".to_string(),
            heartbeat_every_seconds: 300,
            restart_policy: "always".to_string(),
            restart_backoff_seconds: 45,
            telegram_enabled: false,
            telegram_chat_id: String::new(),
            telegram_token_env: DEFAULT_TELEGRAM_TOKEN_ENV.to_string(),
            webhook_enabled: false,
            webhook_url: String::new(),
            webhook_header: String::new(),
        };
        let policy_path = personal_agent_policy_path(&root, &config.slug).expect("policy path");
        let mut policy = default_run_policy(&config);
        policy.desired_state = "running".to_string();
        policy.supervisor_pid = std::process::id();
        policy.current_worker_pid = std::process::id();
        policy.last_crash_unix_ms = 7;
        policy.last_crash_reason = "previous failure".to_string();
        write_run_policy(&policy_path, &policy).expect("write policy");
        let summary = build_run_agent_summary(&root, &config).expect("build summary");
        assert_eq!(
            summary["supervisor_pid"].as_u64().unwrap_or_default(),
            std::process::id() as u64
        );
        assert_eq!(
            summary["worker_pid"].as_u64().unwrap_or_default(),
            std::process::id() as u64
        );
        assert_eq!(
            summary["supervision_action"].as_str().unwrap_or(""),
            "healthy"
        );
        assert_eq!(summary["crash_state"].as_str().unwrap_or(""), "recovered");
        fs::remove_dir_all(&root).ok();
    }
}
