use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

pub type LoomResult<T> = Result<T, String>;

pub const DEFAULT_AGENT_RUNTIME_REGISTRY_PATH: &str = "agents/registry.json";
const DEFAULT_AGENT_MEMORY_FILE: &str = "core.json";
const DEFAULT_AGENT_SESSION_CURRENT_FILE: &str = "current.json";
const DEFAULT_AGENT_SESSION_HISTORY_DIR: &str = "history";
const DEFAULT_GLOBAL_CONTEXT_DIR: &str = "context/global";
const DEFAULT_SOUL_FILE: &str = "SOUL.md";
const DEFAULT_MARKDOWN_MEMORY_FILE: &str = "MEMORY.md";
const DEFAULT_USER_FILE: &str = "USER.md";
const DEFAULT_TOOLS_FILE: &str = "TOOLS.md";
const DEFAULT_HEARTBEAT_FILE: &str = "HEARTBEAT.md";
const DEFAULT_AGENTS_FILE: &str = "AGENTS.md";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AgentRuntimeProfile {
    pub agent_id: String,
    pub display_name: String,
    pub role: String,
    pub workspace_root: String,
    pub memory_root: String,
    pub session_root: String,
    pub provider_profile: String,
    pub tool_scope: String,
    pub heartbeat_policy: String,
}

impl AgentRuntimeProfile {
    pub fn as_json(&self) -> Value {
        json!({
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "role": self.role,
            "workspace_root": self.workspace_root,
            "memory_root": self.memory_root,
            "session_root": self.session_root,
            "provider_profile": self.provider_profile,
            "tool_scope": self.tool_scope,
            "heartbeat_policy": self.heartbeat_policy,
        })
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AgentRuntimeOverview {
    pub registry_path: PathBuf,
    pub profile_count: usize,
    pub agent_ids: Vec<String>,
    pub memory_ready_count: usize,
    pub session_ready_count: usize,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AgentSessionRecord {
    pub session_id: String,
    pub agent_id: String,
    pub status: String,
    pub task_kind: String,
    pub summary: String,
    pub opened_at: String,
    pub updated_at: String,
    pub commit_count: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AgentMemorySnapshot {
    pub agent_id: String,
    pub updated_at: String,
    pub facts: BTreeMap<String, String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AgentSessionSummary {
    pub current_session_path: PathBuf,
    pub history_path: PathBuf,
    pub history_entry_count: usize,
    pub record: AgentSessionRecord,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AgentMemorySummary {
    pub memory_file_path: PathBuf,
    pub snapshot: AgentMemorySnapshot,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AgentRuntimeSummary {
    pub registry_path: PathBuf,
    pub profile_count: usize,
    pub profile: AgentRuntimeProfile,
    pub workspace_path: PathBuf,
    pub memory_path: PathBuf,
    pub session_path: PathBuf,
    pub memory_file_path: PathBuf,
    pub current_session_path: PathBuf,
    pub session_history_path: PathBuf,
    pub current_session: AgentSessionRecord,
    pub memory_snapshot: AgentMemorySnapshot,
    pub history_entry_count: usize,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AgentContextBundle {
    pub agent_id: String,
    pub role: String,
    pub sections: BTreeMap<String, String>,
    pub section_sources: BTreeMap<String, Vec<String>>,
}

pub fn agent_runtime_registry_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_AGENT_RUNTIME_REGISTRY_PATH)
}

pub fn ensure_agent_runtime_scaffold(root: &Path) -> LoomResult<PathBuf> {
    let registry_path = agent_runtime_registry_path(root);
    if let Some(parent) = registry_path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    if !registry_path.exists() {
        fs::write(&registry_path, render_default_agent_runtime_registry()).map_err(io_err)?;
    }
    let profiles = load_agent_runtime_registry(root)?;
    ensure_global_context_scaffold(root, &profiles)?;
    for profile in &profiles {
        let workspace_path = root.join(&profile.workspace_root);
        let memory_path = root.join(&profile.memory_root);
        let session_path = root.join(&profile.session_root);
        fs::create_dir_all(&workspace_path).map_err(io_err)?;
        fs::create_dir_all(&memory_path).map_err(io_err)?;
        fs::create_dir_all(&session_path).map_err(io_err)?;
        fs::create_dir_all(session_history_path_for_profile(root, profile)).map_err(io_err)?;
        ensure_agent_operating_files(root, profile)?;

        let memory_file_path = agent_memory_file_path_for_profile(root, profile);
        if !memory_file_path.exists() {
            write_json_pretty(
                &memory_file_path,
                &default_memory_snapshot(profile).as_json(),
            )?;
        }
        let current_session_path = agent_session_current_path_for_profile(root, profile);
        if !current_session_path.exists() {
            write_json_pretty(
                &current_session_path,
                &default_session_record(profile).as_json(),
            )?;
        }
    }
    Ok(registry_path)
}

pub fn load_agent_runtime_registry(root: &Path) -> LoomResult<Vec<AgentRuntimeProfile>> {
    let registry_path = agent_runtime_registry_path(root);
    let raw = fs::read_to_string(&registry_path).map_err(io_err)?;
    parse_agent_runtime_registry(&raw)
}

pub fn upsert_agent_runtime_profile(
    root: &Path,
    profile: &AgentRuntimeProfile,
) -> LoomResult<AgentRuntimeSummary> {
    ensure_agent_runtime_scaffold(root)?;
    let mut profiles = load_agent_runtime_registry(root)?;
    if let Some(existing) = profiles
        .iter_mut()
        .find(|existing| existing.agent_id == profile.agent_id)
    {
        *existing = profile.clone();
    } else {
        profiles.push(profile.clone());
        profiles.sort_by(|left, right| left.agent_id.cmp(&right.agent_id));
    }

    write_json_pretty(
        &agent_runtime_registry_path(root),
        &json!({
            "agents": profiles
                .iter()
                .map(AgentRuntimeProfile::as_json)
                .collect::<Vec<_>>(),
        }),
    )?;
    ensure_global_context_scaffold(root, &profiles)?;
    ensure_profile_runtime_state(root, profile)?;
    agent_runtime_summary(root, &profile.agent_id)
}

pub fn agent_runtime_overview(root: &Path) -> LoomResult<AgentRuntimeOverview> {
    ensure_agent_runtime_scaffold(root)?;
    let profiles = load_agent_runtime_registry(root)?;
    let mut memory_ready_count = 0usize;
    let mut session_ready_count = 0usize;
    for profile in &profiles {
        if agent_memory_file_path_for_profile(root, profile).exists() {
            memory_ready_count += 1;
        }
        if agent_session_current_path_for_profile(root, profile).exists() {
            session_ready_count += 1;
        }
    }
    Ok(AgentRuntimeOverview {
        registry_path: agent_runtime_registry_path(root),
        profile_count: profiles.len(),
        agent_ids: profiles
            .into_iter()
            .map(|profile| profile.agent_id)
            .collect(),
        memory_ready_count,
        session_ready_count,
    })
}

pub fn agent_runtime_summary(root: &Path, agent_id: &str) -> LoomResult<AgentRuntimeSummary> {
    let profile = resolve_agent_runtime_profile(root, agent_id)?;
    let profiles = load_agent_runtime_registry(root)?;
    let memory = agent_memory_summary(root, agent_id)?;
    let session = agent_session_summary(root, agent_id)?;
    Ok(AgentRuntimeSummary {
        registry_path: agent_runtime_registry_path(root),
        profile_count: profiles.len(),
        workspace_path: root.join(&profile.workspace_root),
        memory_path: root.join(&profile.memory_root),
        session_path: root.join(&profile.session_root),
        memory_file_path: memory.memory_file_path,
        current_session_path: session.current_session_path,
        session_history_path: session.history_path,
        current_session: session.record,
        memory_snapshot: memory.snapshot,
        history_entry_count: session.history_entry_count,
        profile,
    })
}

pub fn agent_session_summary(root: &Path, agent_id: &str) -> LoomResult<AgentSessionSummary> {
    let profile = resolve_agent_runtime_profile(root, agent_id)?;
    let current_session_path = agent_session_current_path_for_profile(root, &profile);
    let history_path = session_history_path_for_profile(root, &profile);
    let raw = fs::read_to_string(&current_session_path).map_err(io_err)?;
    let record = parse_agent_session_record(&raw)?;
    Ok(AgentSessionSummary {
        history_entry_count: count_history_entries(&history_path)?,
        current_session_path,
        history_path,
        record,
    })
}

pub fn open_agent_session(
    root: &Path,
    agent_id: &str,
    task_kind: Option<&str>,
) -> LoomResult<AgentSessionSummary> {
    let profile = resolve_agent_runtime_profile(root, agent_id)?;
    let now = timestamp_now();
    let task_kind = normalized_or(task_kind, "general");
    let record = AgentSessionRecord {
        session_id: format!("{}-{}", profile.agent_id, unique_token()),
        agent_id: profile.agent_id.clone(),
        status: "open".to_string(),
        task_kind,
        summary: "session opened".to_string(),
        opened_at: now.clone(),
        updated_at: now,
        commit_count: 0,
    };
    persist_session_record(root, &profile, &record, true)?;
    agent_session_summary(root, agent_id)
}

pub fn commit_agent_session(
    root: &Path,
    agent_id: &str,
    status: Option<&str>,
    summary: Option<&str>,
    task_kind: Option<&str>,
) -> LoomResult<AgentSessionSummary> {
    let profile = resolve_agent_runtime_profile(root, agent_id)?;
    let mut record = agent_session_summary(root, agent_id)?.record;
    if let Some(value) = status {
        record.status = normalized_or(Some(value), &record.status);
    }
    if let Some(value) = task_kind {
        record.task_kind = normalized_or(Some(value), &record.task_kind);
    }
    if let Some(value) = summary {
        record.summary = normalized_or(Some(value), &record.summary);
    }
    record.updated_at = timestamp_now();
    record.commit_count = record.commit_count.saturating_add(1);
    persist_session_record(root, &profile, &record, true)?;
    agent_session_summary(root, agent_id)
}

pub fn agent_memory_summary(root: &Path, agent_id: &str) -> LoomResult<AgentMemorySummary> {
    let profile = resolve_agent_runtime_profile(root, agent_id)?;
    let memory_file_path = agent_memory_file_path_for_profile(root, &profile);
    let raw = fs::read_to_string(&memory_file_path).map_err(io_err)?;
    let snapshot = parse_agent_memory_snapshot(&raw)?;
    Ok(AgentMemorySummary {
        memory_file_path,
        snapshot,
    })
}

pub fn write_agent_memory_snapshot(
    root: &Path,
    agent_id: &str,
    updates: &BTreeMap<String, String>,
) -> LoomResult<AgentMemorySummary> {
    let profile = resolve_agent_runtime_profile(root, agent_id)?;
    let mut snapshot = agent_memory_summary(root, agent_id)?.snapshot;
    for (key, value) in updates {
        let normalized_key = key.trim();
        let normalized_value = value.trim();
        if normalized_key.is_empty() || normalized_value.is_empty() {
            continue;
        }
        snapshot
            .facts
            .insert(normalized_key.to_string(), normalized_value.to_string());
    }
    snapshot.updated_at = timestamp_now();
    write_json_pretty(
        &agent_memory_file_path_for_profile(root, &profile),
        &snapshot.as_json(),
    )?;
    agent_memory_summary(root, agent_id)
}

pub fn agent_provider_profile(root: &Path, agent_id: &str) -> LoomResult<String> {
    Ok(resolve_agent_runtime_profile(root, agent_id)?.provider_profile)
}

pub fn agent_context_bundle(root: &Path, agent_id: &str) -> LoomResult<AgentContextBundle> {
    let profile = resolve_agent_runtime_profile(root, agent_id)?;
    let global_context_path = root.join(DEFAULT_GLOBAL_CONTEXT_DIR);
    let workspace_path = root.join(&profile.workspace_root);
    let mut sections = BTreeMap::new();
    let mut section_sources = BTreeMap::new();

    let soul = merge_markdown_sources(&[
        global_context_path.join(DEFAULT_SOUL_FILE),
        workspace_path.join(DEFAULT_SOUL_FILE),
    ])?;
    if !soul.0.is_empty() {
        sections.insert("soul".to_string(), soul.0);
        section_sources.insert("soul".to_string(), soul.1);
    }

    let user = merge_markdown_sources(&[global_context_path.join(DEFAULT_USER_FILE)])?;
    if !user.0.is_empty() {
        sections.insert("user".to_string(), user.0);
        section_sources.insert("user".to_string(), user.1);
    }

    let tools = merge_markdown_sources(&[
        global_context_path.join(DEFAULT_TOOLS_FILE),
        workspace_path.join(DEFAULT_TOOLS_FILE),
    ])?;
    if !tools.0.is_empty() {
        sections.insert("tools".to_string(), tools.0);
        section_sources.insert("tools".to_string(), tools.1);
    }

    let heartbeat = merge_markdown_sources(&[
        global_context_path.join(DEFAULT_HEARTBEAT_FILE),
        workspace_path.join(DEFAULT_HEARTBEAT_FILE),
    ])?;
    if !heartbeat.0.is_empty() {
        sections.insert("heartbeat".to_string(), heartbeat.0);
        section_sources.insert("heartbeat".to_string(), heartbeat.1);
    }

    let agents = merge_markdown_sources(&[global_context_path.join(DEFAULT_AGENTS_FILE)])?;
    if !agents.0.is_empty() {
        sections.insert("agents".to_string(), agents.0);
        section_sources.insert("agents".to_string(), agents.1);
    }

    let memory = merge_markdown_sources(&[workspace_path.join(DEFAULT_MARKDOWN_MEMORY_FILE)])?;
    if !memory.0.is_empty() {
        sections.insert("memory".to_string(), memory.0);
        section_sources.insert("memory".to_string(), memory.1);
    }

    Ok(AgentContextBundle {
        agent_id: profile.agent_id,
        role: profile.role,
        sections,
        section_sources,
    })
}

pub fn render_agent_context_human(bundle: &AgentContextBundle) -> String {
    let mut rendered = format!(
        "agent_id:          {}\nrole:              {}\nsection_count:     {}\n",
        bundle.agent_id,
        bundle.role,
        bundle.sections.len()
    );
    for (section, content) in &bundle.sections {
        rendered.push_str(&format!("\n[{}]\n", section));
        if let Some(sources) = bundle.section_sources.get(section) {
            rendered.push_str(&format!("sources: {}\n", sources.join(", ")));
        }
        rendered.push_str(content.trim_end());
        rendered.push('\n');
    }
    rendered
}

pub fn render_agent_context_json(bundle: &AgentContextBundle) -> String {
    serde_json::to_string_pretty(&json!({
        "agent_id": bundle.agent_id,
        "role": bundle.role,
        "sections": bundle.sections,
        "section_sources": bundle.section_sources,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_agent_runtime_human(summary: &AgentRuntimeSummary) -> String {
    format!(
        "registry_path:      {}\nprofile_count:      {}\nagent_id:           {}\ndisplay_name:       {}\nrole:               {}\nworkspace_root:     {}\nmemory_root:        {}\nsession_root:       {}\nmemory_file:        {}\ncurrent_session:    {}\nsession_history:    {}\ncurrent_status:     {}\ncurrent_task:       {}\ncurrent_summary:    {}\nhistory_entries:    {}\nmemory_fact_count:  {}\nprovider_profile:   {}\ntool_scope:         {}\nheartbeat_policy:   {}\n",
        summary.registry_path.display(),
        summary.profile_count,
        summary.profile.agent_id,
        summary.profile.display_name,
        summary.profile.role,
        summary.workspace_path.display(),
        summary.memory_path.display(),
        summary.session_path.display(),
        summary.memory_file_path.display(),
        summary.current_session_path.display(),
        summary.session_history_path.display(),
        summary.current_session.status,
        summary.current_session.task_kind,
        summary.current_session.summary,
        summary.history_entry_count,
        summary.memory_snapshot.facts.len(),
        summary.profile.provider_profile,
        summary.profile.tool_scope,
        summary.profile.heartbeat_policy,
    )
}

pub fn render_agent_runtime_json(summary: &AgentRuntimeSummary) -> String {
    serde_json::to_string_pretty(&json!({
        "registry_path": summary.registry_path.display().to_string(),
        "profile_count": summary.profile_count,
        "agent_id": summary.profile.agent_id,
        "display_name": summary.profile.display_name,
        "role": summary.profile.role,
        "workspace_root": summary.workspace_path.display().to_string(),
        "memory_root": summary.memory_path.display().to_string(),
        "session_root": summary.session_path.display().to_string(),
        "memory_file": summary.memory_file_path.display().to_string(),
        "current_session_path": summary.current_session_path.display().to_string(),
        "session_history_path": summary.session_history_path.display().to_string(),
        "current_session": summary.current_session.as_json(),
        "history_entry_count": summary.history_entry_count,
        "memory_snapshot": summary.memory_snapshot.as_json(),
        "provider_profile": summary.profile.provider_profile,
        "tool_scope": summary.profile.tool_scope,
        "heartbeat_policy": summary.profile.heartbeat_policy,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_agent_session_human(summary: &AgentSessionSummary) -> String {
    format!(
        "current_session_path: {}\nsession_history:      {}\nhistory_entries:      {}\nsession_id:           {}\nagent_id:             {}\nstatus:               {}\ntask_kind:            {}\nsummary:              {}\nopened_at:            {}\nupdated_at:           {}\ncommit_count:         {}\n",
        summary.current_session_path.display(),
        summary.history_path.display(),
        summary.history_entry_count,
        summary.record.session_id,
        summary.record.agent_id,
        summary.record.status,
        summary.record.task_kind,
        summary.record.summary,
        summary.record.opened_at,
        summary.record.updated_at,
        summary.record.commit_count,
    )
}

pub fn render_agent_session_json(summary: &AgentSessionSummary) -> String {
    serde_json::to_string_pretty(&json!({
        "current_session_path": summary.current_session_path.display().to_string(),
        "session_history_path": summary.history_path.display().to_string(),
        "history_entry_count": summary.history_entry_count,
        "session": summary.record.as_json(),
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_agent_memory_human(summary: &AgentMemorySummary) -> String {
    let facts = if summary.snapshot.facts.is_empty() {
        "(none)".to_string()
    } else {
        summary
            .snapshot
            .facts
            .iter()
            .map(|(key, value)| format!("{}={}", key, value))
            .collect::<Vec<_>>()
            .join(", ")
    };
    format!(
        "memory_file:     {}\nagent_id:        {}\nupdated_at:      {}\nfact_count:      {}\nfacts:           {}\n",
        summary.memory_file_path.display(),
        summary.snapshot.agent_id,
        summary.snapshot.updated_at,
        summary.snapshot.facts.len(),
        facts,
    )
}

pub fn render_agent_memory_json(summary: &AgentMemorySummary) -> String {
    serde_json::to_string_pretty(&json!({
        "memory_file": summary.memory_file_path.display().to_string(),
        "snapshot": summary.snapshot.as_json(),
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

fn merge_markdown_sources(paths: &[PathBuf]) -> LoomResult<(String, Vec<String>)> {
    let mut rendered = String::new();
    let mut sources = Vec::new();
    for path in paths {
        if !path.exists() {
            continue;
        }
        let raw = fs::read_to_string(path).map_err(io_err)?;
        if raw.trim().is_empty() {
            continue;
        }
        if !rendered.is_empty() {
            rendered.push_str("\n\n");
        }
        rendered.push_str(raw.trim());
        sources.push(path.display().to_string());
    }
    Ok((rendered, sources))
}

fn ensure_global_context_scaffold(root: &Path, profiles: &[AgentRuntimeProfile]) -> LoomResult<()> {
    let global_context_path = root.join(DEFAULT_GLOBAL_CONTEXT_DIR);
    fs::create_dir_all(&global_context_path).map_err(io_err)?;
    write_text_if_missing(
        &global_context_path.join(DEFAULT_SOUL_FILE),
        "You are Meridian Loom, a governed local runtime for bounded autonomous work.\n",
    )?;
    write_text_if_missing(
        &global_context_path.join(DEFAULT_USER_FILE),
        "# User\n- Founder preferences arrive through governed overlays.\n",
    )?;
    write_text_if_missing(
        &global_context_path.join(DEFAULT_TOOLS_FILE),
        "# Tool Doctrine\n- Use only governed Loom capabilities.\n",
    )?;
    write_text_if_missing(
        &global_context_path.join(DEFAULT_HEARTBEAT_FILE),
        "# Heartbeat Doctrine\n- Stay silent unless recurring policy permits outreach.\n",
    )?;
    let mut roster = String::from("# Agent Roster\n");
    for profile in profiles {
        roster.push_str(&format!(
            "- {} ({}) -> provider={}, scope={}, heartbeat={}\n",
            profile.display_name,
            profile.role,
            profile.provider_profile,
            profile.tool_scope,
            profile.heartbeat_policy
        ));
    }
    write_text_if_missing(&global_context_path.join(DEFAULT_AGENTS_FILE), &roster)?;
    Ok(())
}

fn ensure_agent_operating_files(root: &Path, profile: &AgentRuntimeProfile) -> LoomResult<()> {
    let workspace_path = root.join(&profile.workspace_root);
    write_text_if_missing(
        &workspace_path.join(DEFAULT_SOUL_FILE),
        &format!(
            "You are {}, Meridian's {} agent.\n",
            profile.display_name, profile.role
        ),
    )?;
    write_text_if_missing(
        &workspace_path.join(DEFAULT_MARKDOWN_MEMORY_FILE),
        &format!(
            "# Core Memory\n- Display name: {}\n- Role: {}\n- Provider profile: {}\n- Tool scope: {}\n- Heartbeat policy: {}\n",
            profile.display_name,
            profile.role,
            profile.provider_profile,
            profile.tool_scope,
            profile.heartbeat_policy
        ),
    )?;
    write_text_if_missing(
        &workspace_path.join(DEFAULT_TOOLS_FILE),
        &format!("# Tool Scope\n- Bound tool scope: {}\n", profile.tool_scope),
    )?;
    write_text_if_missing(
        &workspace_path.join(DEFAULT_HEARTBEAT_FILE),
        &format!(
            "# Heartbeat Policy\n- Policy: {}\n",
            profile.heartbeat_policy
        ),
    )?;
    Ok(())
}

fn ensure_profile_runtime_state(root: &Path, profile: &AgentRuntimeProfile) -> LoomResult<()> {
    let workspace_path = root.join(&profile.workspace_root);
    let memory_path = root.join(&profile.memory_root);
    let session_path = root.join(&profile.session_root);
    fs::create_dir_all(&workspace_path).map_err(io_err)?;
    fs::create_dir_all(&memory_path).map_err(io_err)?;
    fs::create_dir_all(&session_path).map_err(io_err)?;
    fs::create_dir_all(session_history_path_for_profile(root, profile)).map_err(io_err)?;
    ensure_agent_operating_files(root, profile)?;

    let memory_file_path = agent_memory_file_path_for_profile(root, profile);
    if !memory_file_path.exists() {
        write_json_pretty(
            &memory_file_path,
            &default_memory_snapshot(profile).as_json(),
        )?;
    }
    let current_session_path = agent_session_current_path_for_profile(root, profile);
    if !current_session_path.exists() {
        write_json_pretty(
            &current_session_path,
            &default_session_record(profile).as_json(),
        )?;
    }
    Ok(())
}

fn write_text_if_missing(path: &Path, value: &str) -> LoomResult<()> {
    if path.exists() {
        return Ok(());
    }
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    fs::write(path, value).map_err(io_err)
}

fn render_default_agent_runtime_registry() -> String {
    serde_json::to_string_pretty(&json!({
        "agents": [
            default_profile("leviathann", "Leviathann", "manager", "manager_frontier", "manager_scope", "managed"),
            default_profile("atlas", "Atlas", "research", "research_frontier", "research_scope", "managed"),
            default_profile("quill", "Quill", "writer", "writer_general", "writer_scope", "managed"),
            default_profile("aegis", "Aegis", "qa_gate", "qa_frontier", "qa_scope", "managed"),
            default_profile("sentinel", "Sentinel", "verifier", "verifier_frontier", "verifier_scope", "managed"),
            default_profile("forge", "Forge", "executor", "executor_tooling", "executor_scope", "managed"),
            default_profile("pulse", "Pulse", "compressor", "local_ollama", "compression_scope", "cheap_background"),
        ]
    }))
    .unwrap_or_else(|_| "{}".to_string())
}

fn default_profile(
    agent_id: &str,
    display_name: &str,
    role: &str,
    provider_profile: &str,
    tool_scope: &str,
    heartbeat_policy: &str,
) -> Value {
    json!({
        "agent_id": agent_id,
        "display_name": display_name,
        "role": role,
        "workspace_root": format!("agents/{}/workspace", agent_id),
        "memory_root": format!("agents/{}/memory", agent_id),
        "session_root": format!("agents/{}/sessions", agent_id),
        "provider_profile": provider_profile,
        "tool_scope": tool_scope,
        "heartbeat_policy": heartbeat_policy,
    })
}

fn resolve_agent_runtime_profile(root: &Path, agent_id: &str) -> LoomResult<AgentRuntimeProfile> {
    ensure_agent_runtime_scaffold(root)?;
    let profiles = load_agent_runtime_registry(root)?;
    let normalized_agent_id = agent_id.trim();
    if normalized_agent_id.is_empty() {
        return Err("agent_id is required".to_string());
    }
    if let Some(profile) = profiles
        .iter()
        .find(|profile| profile.agent_id == normalized_agent_id)
        .cloned()
    {
        return Ok(profile);
    }
    let available = profiles
        .iter()
        .map(|profile| profile.agent_id.clone())
        .collect::<Vec<_>>()
        .join(", ");
    Err(format!(
        "agent runtime profile '{}' was not found (available: {})",
        normalized_agent_id, available
    ))
}

fn agent_memory_file_path_for_profile(root: &Path, profile: &AgentRuntimeProfile) -> PathBuf {
    root.join(&profile.memory_root)
        .join(DEFAULT_AGENT_MEMORY_FILE)
}

fn agent_session_current_path_for_profile(root: &Path, profile: &AgentRuntimeProfile) -> PathBuf {
    root.join(&profile.session_root)
        .join(DEFAULT_AGENT_SESSION_CURRENT_FILE)
}

fn session_history_path_for_profile(root: &Path, profile: &AgentRuntimeProfile) -> PathBuf {
    root.join(&profile.session_root)
        .join(DEFAULT_AGENT_SESSION_HISTORY_DIR)
}

fn default_memory_snapshot(profile: &AgentRuntimeProfile) -> AgentMemorySnapshot {
    let mut facts = BTreeMap::new();
    facts.insert("display_name".to_string(), profile.display_name.clone());
    facts.insert("role".to_string(), profile.role.clone());
    facts.insert(
        "provider_profile".to_string(),
        profile.provider_profile.clone(),
    );
    facts.insert("tool_scope".to_string(), profile.tool_scope.clone());
    facts.insert(
        "heartbeat_policy".to_string(),
        profile.heartbeat_policy.clone(),
    );
    AgentMemorySnapshot {
        agent_id: profile.agent_id.clone(),
        updated_at: timestamp_now(),
        facts,
    }
}

fn default_session_record(profile: &AgentRuntimeProfile) -> AgentSessionRecord {
    let now = timestamp_now();
    AgentSessionRecord {
        session_id: format!("{}-bootstrap", profile.agent_id),
        agent_id: profile.agent_id.clone(),
        status: "idle".to_string(),
        task_kind: "standby".to_string(),
        summary: "agent runtime provisioned".to_string(),
        opened_at: now.clone(),
        updated_at: now,
        commit_count: 0,
    }
}

fn persist_session_record(
    root: &Path,
    profile: &AgentRuntimeProfile,
    record: &AgentSessionRecord,
    archive_history: bool,
) -> LoomResult<()> {
    let current_path = agent_session_current_path_for_profile(root, profile);
    write_json_pretty(&current_path, &record.as_json())?;
    if archive_history {
        let history_path = session_history_path_for_profile(root, profile).join(format!(
            "{}-{}-{}.json",
            safe_file_token(&record.session_id),
            record.commit_count,
            unique_token()
        ));
        write_json_pretty(&history_path, &record.as_json())?;
    }
    Ok(())
}

fn count_history_entries(path: &Path) -> LoomResult<usize> {
    if !path.exists() {
        return Ok(0);
    }
    let mut count = 0usize;
    for entry in fs::read_dir(path).map_err(io_err)? {
        let entry = entry.map_err(io_err)?;
        let entry_path = entry.path();
        if entry_path.is_file()
            && entry_path
                .extension()
                .and_then(|value| value.to_str())
                .map(|value| value.eq_ignore_ascii_case("json"))
                .unwrap_or(false)
        {
            count += 1;
        }
    }
    Ok(count)
}

fn parse_agent_runtime_registry(raw: &str) -> LoomResult<Vec<AgentRuntimeProfile>> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid agent runtime registry json: {error}"))?;
    let agents = value
        .get("agents")
        .and_then(Value::as_array)
        .ok_or_else(|| "agent runtime registry must define an agents array".to_string())?;
    if agents.is_empty() {
        return Err("agent runtime registry must define at least one agent".to_string());
    }
    let mut profiles = Vec::with_capacity(agents.len());
    for agent in agents {
        profiles.push(parse_agent_runtime_profile(agent)?);
    }
    Ok(profiles)
}

fn parse_agent_runtime_profile(value: &Value) -> LoomResult<AgentRuntimeProfile> {
    Ok(AgentRuntimeProfile {
        agent_id: value_string(value.get("agent_id"), "agent_id")?,
        display_name: value_string(value.get("display_name"), "display_name")?,
        role: value_string(value.get("role"), "role")?,
        workspace_root: value_string(value.get("workspace_root"), "workspace_root")?,
        memory_root: value_string(value.get("memory_root"), "memory_root")?,
        session_root: value_string(value.get("session_root"), "session_root")?,
        provider_profile: value_string(value.get("provider_profile"), "provider_profile")?,
        tool_scope: value_string(value.get("tool_scope"), "tool_scope")?,
        heartbeat_policy: value_string(value.get("heartbeat_policy"), "heartbeat_policy")?,
    })
}

fn parse_agent_session_record(raw: &str) -> LoomResult<AgentSessionRecord> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid agent session json: {error}"))?;
    Ok(AgentSessionRecord {
        session_id: value_string(value.get("session_id"), "session_id")?,
        agent_id: value_string(value.get("agent_id"), "agent_id")?,
        status: value_string(value.get("status"), "status")?,
        task_kind: value_string(value.get("task_kind"), "task_kind")?,
        summary: value_string(value.get("summary"), "summary")?,
        opened_at: value_string(value.get("opened_at"), "opened_at")?,
        updated_at: value_string(value.get("updated_at"), "updated_at")?,
        commit_count: value
            .get("commit_count")
            .and_then(Value::as_u64)
            .unwrap_or(0),
    })
}

fn parse_agent_memory_snapshot(raw: &str) -> LoomResult<AgentMemorySnapshot> {
    let value: Value =
        serde_json::from_str(raw).map_err(|error| format!("invalid agent memory json: {error}"))?;
    let facts_value = value
        .get("facts")
        .and_then(Value::as_object)
        .ok_or_else(|| "agent memory snapshot must define a facts object".to_string())?;
    let mut facts = BTreeMap::new();
    for (key, value) in facts_value {
        let Some(raw_value) = value.as_str() else {
            return Err(format!("memory fact '{}' must be a string", key));
        };
        if raw_value.trim().is_empty() {
            continue;
        }
        facts.insert(key.trim().to_string(), raw_value.trim().to_string());
    }
    Ok(AgentMemorySnapshot {
        agent_id: value_string(value.get("agent_id"), "agent_id")?,
        updated_at: value_string(value.get("updated_at"), "updated_at")?,
        facts,
    })
}

fn value_string(value: Option<&Value>, label: &str) -> LoomResult<String> {
    value
        .and_then(Value::as_str)
        .map(|raw| raw.trim().to_string())
        .filter(|raw| !raw.is_empty())
        .ok_or_else(|| format!("{label} must not be empty"))
}

fn write_json_pretty(path: &Path, value: &Value) -> LoomResult<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    let mut rendered = serde_json::to_string_pretty(value).map_err(|error| error.to_string())?;
    rendered.push('\n');
    fs::write(path, rendered).map_err(io_err)
}

fn normalized_or(value: Option<&str>, fallback: &str) -> String {
    value
        .map(|raw| raw.trim())
        .filter(|raw| !raw.is_empty())
        .unwrap_or(fallback)
        .to_string()
}

fn timestamp_now() -> String {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
        .to_string()
}

fn unique_token() -> String {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos()
        .to_string()
}

fn safe_file_token(input: &str) -> String {
    input
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() {
                ch.to_ascii_lowercase()
            } else {
                '-'
            }
        })
        .collect::<String>()
        .trim_matches('-')
        .to_string()
}

fn io_err(error: std::io::Error) -> String {
    error.to_string()
}

impl AgentSessionRecord {
    fn as_json(&self) -> Value {
        json!({
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "status": self.status,
            "task_kind": self.task_kind,
            "summary": self.summary,
            "opened_at": self.opened_at,
            "updated_at": self.updated_at,
            "commit_count": self.commit_count,
        })
    }
}

impl AgentMemorySnapshot {
    fn as_json(&self) -> Value {
        json!({
            "agent_id": self.agent_id,
            "updated_at": self.updated_at,
            "facts": self.facts,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_path(label: &str) -> PathBuf {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        let path = std::env::temp_dir().join(format!("{}-{}", label, unique));
        let _ = fs::remove_dir_all(&path);
        fs::create_dir_all(&path).expect("create temp path");
        path
    }

    #[test]
    fn scaffold_writes_default_agent_registry_and_state_files() {
        let root = temp_path("loom-agent-runtime-scaffold");
        let registry =
            ensure_agent_runtime_scaffold(&root).expect("scaffold agent runtime registry");
        assert!(registry.exists());
        let overview = agent_runtime_overview(&root).expect("agent runtime overview");
        assert_eq!(overview.profile_count, 7);
        assert_eq!(overview.memory_ready_count, 7);
        assert_eq!(overview.session_ready_count, 7);
        assert!(root.join("agents/atlas/workspace").exists());
        assert!(root.join("agents/pulse/memory/core.json").exists());
        assert!(root.join("agents/pulse/sessions/current.json").exists());
        assert!(root.join("context/global/SOUL.md").exists());
        assert!(root.join("agents/pulse/workspace/MEMORY.md").exists());
    }

    #[test]
    fn summary_resolves_expected_agent_profile_and_state() {
        let root = temp_path("loom-agent-runtime-summary");
        ensure_agent_runtime_scaffold(&root).expect("scaffold agent runtime registry");
        let summary = agent_runtime_summary(&root, "pulse").expect("agent runtime summary");
        assert_eq!(summary.profile.display_name, "Pulse");
        assert_eq!(summary.profile.provider_profile, "local_ollama");
        assert_eq!(
            summary.memory_snapshot.facts.get("role"),
            Some(&"compressor".to_string())
        );
        assert_eq!(summary.current_session.status, "idle");
        assert!(summary
            .workspace_path
            .ends_with(Path::new("agents/pulse/workspace")));
    }

    #[test]
    fn open_and_commit_agent_session_updates_history() {
        let root = temp_path("loom-agent-runtime-session");
        ensure_agent_runtime_scaffold(&root).expect("scaffold agent runtime registry");
        let opened = open_agent_session(&root, "atlas", Some("research")).expect("open session");
        assert_eq!(opened.record.status, "open");
        assert_eq!(opened.record.task_kind, "research");

        let committed = commit_agent_session(
            &root,
            "atlas",
            Some("completed"),
            Some("research brief drafted"),
            None,
        )
        .expect("commit session");
        assert_eq!(committed.record.status, "completed");
        assert_eq!(committed.record.summary, "research brief drafted");
        assert!(committed.history_entry_count >= 2);
        assert_eq!(committed.record.commit_count, 1);
    }

    #[test]
    fn write_agent_memory_snapshot_persists_fact_updates() {
        let root = temp_path("loom-agent-runtime-memory");
        ensure_agent_runtime_scaffold(&root).expect("scaffold agent runtime registry");
        let mut updates = BTreeMap::new();
        updates.insert("mission".to_string(), "governed execution".to_string());
        let summary = write_agent_memory_snapshot(&root, "forge", &updates).expect("write memory");
        assert_eq!(
            summary.snapshot.facts.get("mission"),
            Some(&"governed execution".to_string())
        );
        assert_eq!(
            summary.snapshot.facts.get("role"),
            Some(&"executor".to_string())
        );
    }

    #[test]
    fn context_bundle_merges_global_and_agent_operating_files() {
        let root = temp_path("loom-agent-runtime-context");
        ensure_agent_runtime_scaffold(&root).expect("scaffold agent runtime registry");
        let bundle = agent_context_bundle(&root, "atlas").expect("agent context bundle");
        assert!(bundle
            .sections
            .get("soul")
            .unwrap_or(&String::new())
            .contains("Meridian Loom"));
        assert!(bundle
            .sections
            .get("soul")
            .unwrap_or(&String::new())
            .contains("Atlas"));
        assert!(bundle
            .sections
            .get("memory")
            .unwrap_or(&String::new())
            .contains("Provider profile"));
        assert!(bundle
            .section_sources
            .get("agents")
            .map(|items| !items.is_empty())
            .unwrap_or(false));
    }
}
