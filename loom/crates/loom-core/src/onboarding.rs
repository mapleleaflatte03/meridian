use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use crate::{io_err, unix_now, Config, LoomResult};

pub const DEFAULT_ONBOARD_MANIFEST_PATH: &str = "state/onboard.json";
const DEFAULT_GATEWAY_BIND: &str = "loopback";
const DEFAULT_GATEWAY_AUTH_MODE: &str = "token";
const DEFAULT_GATEWAY_TAILSCALE_MODE: &str = "off";
const DEFAULT_TELEGRAM_TOKEN_ENV: &str = "MERIDIAN_TELEGRAM_BOT_TOKEN";
const DEFAULT_TELEGRAM_DM_POLICY: &str = "open";
const DEFAULT_TELEGRAM_GROUP_POLICY: &str = "allowlist";
const DEFAULT_TELEGRAM_STREAMING: &str = "partial";
const DEFAULT_SESSION_DM_SCOPE: &str = "per-channel-peer";
const DEFAULT_DAEMON_MANAGER: &str = "supervisor";
const DEFAULT_DAEMON_STATE: &str = "configured";
const DEFAULT_SKILLS_NODE_MANAGER: &str = "npm";
const DEFAULT_REMOTE_MODE: &str = "local";
const DEFAULT_WIZARD_VERSION: &str = "meridian-onboard-v1";
const DEFAULT_MANAGER_LANE: &str = "frontier";
const DEFAULT_FRONTIER_MANAGER_MODEL: &str = "gpt-5.4";
const DEFAULT_CODEX_AUTH_SOURCE: &str = "loom";
const DEFAULT_LOOM_CODEX_AUTH_PATH: &str = ".meridian/auth/codex/auth.json";
const DEFAULT_SKILL_ENTRIES: [&str; 4] = [
    "browser",
    "telegram_bridge",
    "web_bridge",
    "governed_memory",
];
const DEFAULT_RECURRING_ENTRIES: [&str; 4] = [
    "night_shift_kickoff",
    "night_shift_research",
    "night_shift_write",
    "morning_brief",
];

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnboardManifest {
    pub wizard_version: String,
    pub last_action: String,
    pub last_run_at: u64,
    pub last_run_mode: String,
    pub remote_mode: String,
    pub manager_lane: String,
    pub manager_model: String,
    pub codex_auth_source: String,
    pub codex_auth_path: String,
    pub gateway_port: u16,
    pub gateway_bind: String,
    pub gateway_auth_mode: String,
    pub gateway_token_env: String,
    pub gateway_tailscale_mode: String,
    pub telegram_enabled: bool,
    pub telegram_token_env: String,
    pub telegram_dm_policy: String,
    pub telegram_group_policy: String,
    pub telegram_streaming: String,
    pub session_dm_scope: String,
    pub daemon_enabled: bool,
    pub daemon_manager: String,
    pub daemon_state: String,
    pub skills_node_manager: String,
    pub skills_install_defaults: bool,
    pub skills_entries: Vec<String>,
    pub recurring_install_defaults: bool,
    pub recurring_entries: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnboardOverview {
    pub manifest_path: PathBuf,
    pub wizard_version: String,
    pub last_action: String,
    pub brain_summary: String,
    pub gateway_summary: String,
    pub telegram_summary: String,
    pub daemon_summary: String,
    pub skills_summary: String,
    pub recurring_summary: String,
    pub remote_mode: String,
}

pub fn onboard_manifest_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_ONBOARD_MANIFEST_PATH)
}

pub fn ensure_onboard_manifest(root: &Path, config: &Config) -> LoomResult<PathBuf> {
    let manifest_path = onboard_manifest_path(root);
    if let Some(parent) = manifest_path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    if !manifest_path.exists() {
        let manifest = OnboardManifest::from_config(config, "initialized");
        write_onboard_manifest(root, &manifest)?;
    }
    Ok(manifest_path)
}

pub fn load_onboard_manifest(root: &Path) -> LoomResult<OnboardManifest> {
    let raw = fs::read_to_string(onboard_manifest_path(root)).map_err(io_err)?;
    parse_onboard_manifest(&raw)
}

pub fn write_onboard_manifest(root: &Path, manifest: &OnboardManifest) -> LoomResult<PathBuf> {
    let path = onboard_manifest_path(root);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    fs::write(&path, render_onboard_manifest(manifest)).map_err(io_err)?;
    Ok(path)
}

pub fn onboard_overview(root: &Path) -> LoomResult<OnboardOverview> {
    let manifest = load_onboard_manifest(root)?;
    Ok(OnboardOverview {
        manifest_path: onboard_manifest_path(root),
        wizard_version: manifest.wizard_version.clone(),
        last_action: manifest.last_action.clone(),
        brain_summary: format!(
            "lane={} model={} codex_auth={} path={}",
            manifest.manager_lane,
            manifest.manager_model,
            manifest.codex_auth_source,
            if manifest.codex_auth_path.trim().is_empty() {
                "(none)".to_string()
            } else {
                manifest.codex_auth_path.clone()
            }
        ),
        gateway_summary: format!(
            "{}:{} auth={} tailscale={}",
            bind_host_for(&manifest.gateway_bind),
            manifest.gateway_port,
            manifest.gateway_auth_mode,
            manifest.gateway_tailscale_mode
        ),
        telegram_summary: if manifest.telegram_enabled {
            format!(
                "enabled env={} dm={} group={} streaming={}",
                manifest.telegram_token_env,
                manifest.telegram_dm_policy,
                manifest.telegram_group_policy,
                manifest.telegram_streaming
            )
        } else {
            "disabled".to_string()
        },
        daemon_summary: format!(
            "{} {}",
            manifest.daemon_manager,
            if manifest.daemon_enabled {
                manifest.daemon_state.as_str()
            } else {
                "disabled"
            }
        ),
        skills_summary: format!(
            "node_manager={} defaults={} entries={}",
            manifest.skills_node_manager,
            if manifest.skills_install_defaults {
                "yes"
            } else {
                "no"
            },
            manifest.skills_entries.join(",")
        ),
        recurring_summary: format!(
            "defaults={} entries={}",
            if manifest.recurring_install_defaults {
                "yes"
            } else {
                "no"
            },
            manifest.recurring_entries.join(",")
        ),
        remote_mode: manifest.remote_mode,
    })
}

/// Describes the user's setup state for user-first onboarding paths.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SetupState {
    /// No loom.toml yet — completely fresh workspace.
    FreshWorkspace,
    /// Workspace initialized but no provider credentials detected.
    FreshNoAuth { provider_count: usize },
    /// Provider profiles exist, but the selected frontier path still needs credentials.
    ProviderConfiguredAuthPending {
        profiles: Vec<String>,
        provider_count: usize,
    },
    /// Credentials are local-only (Ollama), no frontier auth.
    LocalOnly {
        ollama_available: bool,
        agent_count: usize,
    },
    /// At least one frontier provider credential found.
    FrontierAvailable {
        profiles: Vec<String>,
        agent_count: usize,
    },
    /// Workspace is fully configured with agents, providers, and credentials.
    FullyConfigured {
        agent_count: usize,
        provider_count: usize,
    },
}

/// Detect the current setup state to guide the user-first onboarding path.
pub fn detect_setup_state(root: &Path) -> SetupState {
    if !root.join("loom.toml").exists() {
        return SetupState::FreshWorkspace;
    }
    let manifest = load_onboard_manifest(root).ok();
    let profiles = match crate::provider_router::load_provider_profiles(Some(root)) {
        Ok(ps) => ps,
        Err(_) => return SetupState::FreshNoAuth { provider_count: 0 },
    };
    let agent_count = crate::agent_runtime::agent_runtime_overview(root)
        .map(|o| o.profile_count)
        .unwrap_or(0);
    let provider_count = profiles.profiles.len();
    let manager_lane = manifest
        .as_ref()
        .map(|value| value.manager_lane.trim().to_ascii_lowercase())
        .unwrap_or_else(|| DEFAULT_MANAGER_LANE.to_string());
    let onboard_complete = manifest
        .as_ref()
        .map(|value| value.last_action.trim() == "setup")
        .unwrap_or(false);
    if provider_count == 0 {
        return SetupState::FreshNoAuth { provider_count: 0 };
    }
    let has_ollama = profiles
        .profiles
        .iter()
        .any(|p| p.kind.label() == "local_ollama");
    let ollama_available = has_ollama
        && crate::provider_router::provider_auth_status(Some(root), Some("local_ollama"))
            .map(|s| s.ready)
            .unwrap_or(false);
    if manager_lane == "local" {
        return SetupState::LocalOnly {
            ollama_available,
            agent_count,
        };
    }
    let configured_manager_profile = profiles
        .routing
        .agents
        .get("leviathann")
        .and_then(|policy| policy.profile_name.as_ref())
        .and_then(|name| {
            profiles
                .profiles
                .iter()
                .find(|profile| profile.name == *name)
        });
    if let Some(manager_profile) = configured_manager_profile {
        let label = manager_profile.kind.label();
        if label != "local_ollama" && label != "unknown" {
            let manager_ready = crate::provider_router::provider_auth_status(
                Some(root),
                Some(&manager_profile.name),
            )
            .map(|status| status.ready)
            .unwrap_or(false);
            if !manager_ready {
                return if onboard_complete {
                    SetupState::ProviderConfiguredAuthPending {
                        profiles: vec![manager_profile.name.clone()],
                        provider_count,
                    }
                } else {
                    SetupState::FreshNoAuth { provider_count }
                };
            }
            let manager_route_ready = crate::provider_router::resolve_provider_route(
                Some(root),
                &crate::provider_router::ProviderRouteIntent::llm_inference("")
                    .with_agent_id("leviathann"),
            )
            .is_ok();
            if !manager_route_ready || !onboard_complete || agent_count == 0 {
                return SetupState::FrontierAvailable {
                    profiles: vec![manager_profile.name.clone()],
                    agent_count,
                };
            }
            return SetupState::FullyConfigured {
                agent_count,
                provider_count,
            };
        }
    }
    let configured_frontier_profiles: Vec<String> = profiles
        .profiles
        .iter()
        .filter(|p| {
            let label = p.kind.label();
            label != "local_ollama" && label != "unknown"
        })
        .map(|p| p.name.clone())
        .collect();
    let ready_profiles: Vec<String> = profiles
        .profiles
        .iter()
        .filter(|p| {
            let label = p.kind.label();
            label != "local_ollama" && label != "unknown"
        })
        .filter(|p| {
            crate::provider_router::provider_auth_status(Some(root), Some(&p.name))
                .map(|status| status.ready)
                .unwrap_or(false)
        })
        .map(|p| p.name.clone())
        .collect();
    if ready_profiles.is_empty() {
        if !configured_frontier_profiles.is_empty() {
            return if onboard_complete {
                SetupState::ProviderConfiguredAuthPending {
                    profiles: configured_frontier_profiles,
                    provider_count,
                }
            } else {
                SetupState::FreshNoAuth { provider_count }
            };
        }
        return SetupState::FreshNoAuth { provider_count };
    }
    let manager_route_ready = crate::provider_router::resolve_provider_route(
        Some(root),
        &crate::provider_router::ProviderRouteIntent::llm_inference("").with_agent_id("leviathann"),
    )
    .is_ok();
    if !manager_route_ready || !onboard_complete || agent_count == 0 {
        return SetupState::FrontierAvailable {
            profiles: ready_profiles,
            agent_count,
        };
    }
    SetupState::FullyConfigured {
        agent_count,
        provider_count,
    }
}

/// Returns a human-readable action hint appropriate for the given setup state.
pub fn onboard_path_hint(state: &SetupState) -> String {
    match state {
        SetupState::FreshWorkspace => {
            "No workspace found. Run: loom init --root <path>".to_string()
        }
        SetupState::FreshNoAuth { .. } => {
            "No provider credentials configured.\n  Option 1 (local):    install Ollama and run loom onboard --manager-lane local\n  Option 2 (frontier): sign in a dedicated Loom account and run loom onboard --manager-lane frontier --codex-auth-source loom\n  Convenience:        reuse an existing Codex CLI login with --codex-auth-source cli".to_string()
        }
        SetupState::ProviderConfiguredAuthPending { profiles, .. } => {
            format!(
                "Provider route configured (profiles: {}), but credentials are still missing.\n  Export the required auth env var or complete Loom-managed sign-in, then run loom doctor.",
                profiles.join(", ")
            )
        }
        SetupState::LocalOnly { ollama_available, .. } => {
            if *ollama_available {
                "Local Ollama provider is ready. To add a frontier provider run loom provider login --source loom --device-auth, then loom onboard --manager-lane frontier --codex-auth-source loom, or reuse the shared CLI login with --codex-auth-source cli.".to_string()
            } else {
                "Local Ollama profile found but credentials not detected. Start Ollama and ensure the endpoint is reachable.".to_string()
            }
        }
        SetupState::FrontierAvailable { profiles, agent_count } => {
            if *agent_count == 0 {
                format!("Frontier provider ready (profiles: {}). No agents configured yet — run loom agent to add one.", profiles.join(", "))
            } else {
                format!("Frontier provider ready (profiles: {}). Run loom doctor to verify the full stack.", profiles.join(", "))
            }
        }
        SetupState::FullyConfigured { agent_count, provider_count } => {
            format!("Runtime fully configured: {} agent(s), {} provider(s). Run loom doctor to inspect health.", agent_count, provider_count)
        }
    }
}

pub fn bind_host_for(bind: &str) -> &'static str {
    match bind.trim().to_ascii_lowercase().as_str() {
        "all" | "any" | "public" => "0.0.0.0",
        _ => "127.0.0.1",
    }
}

pub fn derive_service_http_address(bind: &str, port: u16) -> String {
    format!("{}:{}", bind_host_for(bind), port)
}

impl OnboardManifest {
    pub fn from_config(config: &Config, last_action: &str) -> Self {
        let (gateway_bind, gateway_port) = parse_service_address(&config.service_http_address);
        Self {
            wizard_version: DEFAULT_WIZARD_VERSION.to_string(),
            last_action: normalized_or(last_action, "initialized"),
            last_run_at: unix_now(),
            last_run_mode: config.mode.clone(),
            remote_mode: DEFAULT_REMOTE_MODE.to_string(),
            manager_lane: DEFAULT_MANAGER_LANE.to_string(),
            manager_model: DEFAULT_FRONTIER_MANAGER_MODEL.to_string(),
            codex_auth_source: DEFAULT_CODEX_AUTH_SOURCE.to_string(),
            codex_auth_path: default_loom_codex_auth_path_string(),
            gateway_port,
            gateway_bind,
            gateway_auth_mode: DEFAULT_GATEWAY_AUTH_MODE.to_string(),
            gateway_token_env: config.service_token_env.clone(),
            gateway_tailscale_mode: DEFAULT_GATEWAY_TAILSCALE_MODE.to_string(),
            telegram_enabled: false,
            telegram_token_env: DEFAULT_TELEGRAM_TOKEN_ENV.to_string(),
            telegram_dm_policy: DEFAULT_TELEGRAM_DM_POLICY.to_string(),
            telegram_group_policy: DEFAULT_TELEGRAM_GROUP_POLICY.to_string(),
            telegram_streaming: DEFAULT_TELEGRAM_STREAMING.to_string(),
            session_dm_scope: DEFAULT_SESSION_DM_SCOPE.to_string(),
            daemon_enabled: false,
            daemon_manager: DEFAULT_DAEMON_MANAGER.to_string(),
            daemon_state: DEFAULT_DAEMON_STATE.to_string(),
            skills_node_manager: DEFAULT_SKILLS_NODE_MANAGER.to_string(),
            skills_install_defaults: true,
            skills_entries: DEFAULT_SKILL_ENTRIES
                .iter()
                .map(|entry| entry.to_string())
                .collect(),
            recurring_install_defaults: true,
            recurring_entries: DEFAULT_RECURRING_ENTRIES
                .iter()
                .map(|entry| entry.to_string())
                .collect(),
        }
    }

    pub fn as_json(&self) -> Value {
        json!({
            "wizard": {
                "version": self.wizard_version,
                "lastAction": self.last_action,
                "lastRunAt": self.last_run_at,
                "lastRunMode": self.last_run_mode,
                "remoteMode": self.remote_mode
            },
            "brain": {
                "managerLane": self.manager_lane,
                "managerModel": self.manager_model,
                "codexAuth": {
                    "source": self.codex_auth_source,
                    "path": self.codex_auth_path
                }
            },
            "gateway": {
                "port": self.gateway_port,
                "bind": self.gateway_bind,
                "auth": {
                    "mode": self.gateway_auth_mode,
                    "tokenEnv": self.gateway_token_env
                },
                "tailscale": {
                    "mode": self.gateway_tailscale_mode
                }
            },
            "channels": {
                "telegram": {
                    "enabled": self.telegram_enabled,
                    "tokenEnv": self.telegram_token_env,
                    "dmPolicy": self.telegram_dm_policy,
                    "groupPolicy": self.telegram_group_policy,
                    "streaming": self.telegram_streaming
                }
            },
            "session": {
                "dmScope": self.session_dm_scope
            },
            "daemon": {
                "enabled": self.daemon_enabled,
                "manager": self.daemon_manager,
                "state": self.daemon_state
            },
            "skills": {
                "nodeManager": self.skills_node_manager,
                "installDefaults": self.skills_install_defaults,
                "entries": self.skills_entries
            },
            "recurring": {
                "installDefaults": self.recurring_install_defaults,
                "entries": self.recurring_entries
            }
        })
    }
}

fn render_onboard_manifest(manifest: &OnboardManifest) -> String {
    let mut rendered =
        serde_json::to_string_pretty(&manifest.as_json()).unwrap_or_else(|_| "{}".to_string());
    rendered.push('\n');
    rendered
}

fn parse_onboard_manifest(raw: &str) -> LoomResult<OnboardManifest> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid onboard manifest json: {error}"))?;
    let wizard = value
        .get("wizard")
        .and_then(Value::as_object)
        .ok_or_else(|| "onboard manifest missing wizard object".to_string())?;
    let brain = value.get("brain").and_then(Value::as_object);
    let brain_codex_auth = brain
        .and_then(|section| section.get("codexAuth"))
        .and_then(Value::as_object);
    let gateway = value
        .get("gateway")
        .and_then(Value::as_object)
        .ok_or_else(|| "onboard manifest missing gateway object".to_string())?;
    let gateway_auth = gateway
        .get("auth")
        .and_then(Value::as_object)
        .ok_or_else(|| "onboard manifest missing gateway.auth object".to_string())?;
    let gateway_tailscale = gateway
        .get("tailscale")
        .and_then(Value::as_object)
        .ok_or_else(|| "onboard manifest missing gateway.tailscale object".to_string())?;
    let channels = value
        .get("channels")
        .and_then(Value::as_object)
        .ok_or_else(|| "onboard manifest missing channels object".to_string())?;
    let telegram = channels
        .get("telegram")
        .and_then(Value::as_object)
        .ok_or_else(|| "onboard manifest missing channels.telegram object".to_string())?;
    let session = value
        .get("session")
        .and_then(Value::as_object)
        .ok_or_else(|| "onboard manifest missing session object".to_string())?;
    let daemon = value
        .get("daemon")
        .and_then(Value::as_object)
        .ok_or_else(|| "onboard manifest missing daemon object".to_string())?;
    let skills = value
        .get("skills")
        .and_then(Value::as_object)
        .ok_or_else(|| "onboard manifest missing skills object".to_string())?;
    let recurring = value.get("recurring").and_then(Value::as_object);
    let skill_entries = skills
        .get("entries")
        .and_then(Value::as_array)
        .map(|entries| {
            entries
                .iter()
                .filter_map(Value::as_str)
                .map(|entry| entry.trim().to_string())
                .filter(|entry| !entry.is_empty())
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let recurring_entries = recurring
        .and_then(|section| section.get("entries"))
        .and_then(Value::as_array)
        .map(|entries| {
            entries
                .iter()
                .filter_map(Value::as_str)
                .map(|entry| entry.trim().to_string())
                .filter(|entry| !entry.is_empty())
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    Ok(OnboardManifest {
        wizard_version: value_string(wizard.get("version"), DEFAULT_WIZARD_VERSION),
        last_action: value_string(wizard.get("lastAction"), "initialized"),
        last_run_at: wizard
            .get("lastRunAt")
            .and_then(Value::as_u64)
            .unwrap_or_else(unix_now),
        last_run_mode: value_string(wizard.get("lastRunMode"), "embedded"),
        remote_mode: value_string(wizard.get("remoteMode"), DEFAULT_REMOTE_MODE),
        manager_lane: value_string(
            brain.and_then(|section| section.get("managerLane")),
            DEFAULT_MANAGER_LANE,
        ),
        manager_model: value_string(
            brain.and_then(|section| section.get("managerModel")),
            DEFAULT_FRONTIER_MANAGER_MODEL,
        ),
        codex_auth_source: value_string(
            brain_codex_auth.and_then(|section| section.get("source")),
            DEFAULT_CODEX_AUTH_SOURCE,
        ),
        codex_auth_path: value_string_preserve_empty(
            brain_codex_auth.and_then(|section| section.get("path")),
            DEFAULT_LOOM_CODEX_AUTH_PATH,
        ),
        gateway_port: gateway.get("port").and_then(Value::as_u64).unwrap_or(18910) as u16,
        gateway_bind: value_string(gateway.get("bind"), DEFAULT_GATEWAY_BIND),
        gateway_auth_mode: value_string(gateway_auth.get("mode"), DEFAULT_GATEWAY_AUTH_MODE),
        gateway_token_env: value_string(gateway_auth.get("tokenEnv"), "LOOM_SERVICE_TOKEN"),
        gateway_tailscale_mode: value_string(
            gateway_tailscale.get("mode"),
            DEFAULT_GATEWAY_TAILSCALE_MODE,
        ),
        telegram_enabled: telegram
            .get("enabled")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        telegram_token_env: value_string(telegram.get("tokenEnv"), DEFAULT_TELEGRAM_TOKEN_ENV),
        telegram_dm_policy: value_string(telegram.get("dmPolicy"), DEFAULT_TELEGRAM_DM_POLICY),
        telegram_group_policy: value_string(
            telegram.get("groupPolicy"),
            DEFAULT_TELEGRAM_GROUP_POLICY,
        ),
        telegram_streaming: value_string(telegram.get("streaming"), DEFAULT_TELEGRAM_STREAMING),
        session_dm_scope: value_string(session.get("dmScope"), DEFAULT_SESSION_DM_SCOPE),
        daemon_enabled: daemon
            .get("enabled")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        daemon_manager: value_string(daemon.get("manager"), DEFAULT_DAEMON_MANAGER),
        daemon_state: value_string(daemon.get("state"), DEFAULT_DAEMON_STATE),
        skills_node_manager: value_string(skills.get("nodeManager"), DEFAULT_SKILLS_NODE_MANAGER),
        skills_install_defaults: skills
            .get("installDefaults")
            .and_then(Value::as_bool)
            .unwrap_or(true),
        skills_entries: if skill_entries.is_empty() {
            DEFAULT_SKILL_ENTRIES
                .iter()
                .map(|entry| entry.to_string())
                .collect()
        } else {
            skill_entries
        },
        recurring_install_defaults: recurring
            .and_then(|section| section.get("installDefaults"))
            .and_then(Value::as_bool)
            .unwrap_or(true),
        recurring_entries: if recurring_entries.is_empty() {
            DEFAULT_RECURRING_ENTRIES
                .iter()
                .map(|entry| entry.to_string())
                .collect()
        } else {
            recurring_entries
        },
    })
}

fn parse_service_address(raw: &str) -> (String, u16) {
    let trimmed = raw.trim();
    let Some((host, port)) = trimmed.rsplit_once(':') else {
        return (DEFAULT_GATEWAY_BIND.to_string(), 18910);
    };
    let bind = match host.trim() {
        "0.0.0.0" => "all",
        _ => DEFAULT_GATEWAY_BIND,
    };
    let port = port.trim().parse::<u16>().unwrap_or(18910);
    (bind.to_string(), port)
}

fn normalized_or(raw: &str, default: &str) -> String {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        default.to_string()
    } else {
        trimmed.to_string()
    }
}

fn value_string(value: Option<&Value>, default: &str) -> String {
    value
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or(default)
        .to_string()
}

fn value_string_preserve_empty(value: Option<&Value>, default: &str) -> String {
    match value.and_then(Value::as_str) {
        Some(raw) => raw.trim().to_string(),
        None => default.to_string(),
    }
}

fn default_loom_codex_auth_path_string() -> String {
    crate::provider_router::default_codex_auth_path_hint()
        .ok()
        .map(|path| path.display().to_string())
        .unwrap_or_else(|| DEFAULT_LOOM_CODEX_AUTH_PATH.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::provider_router::{
        configure_onboard_provider_profile, OnboardProviderRouteConfig, ProviderAuthMode,
        ProviderKind,
    };
    use crate::{init_workspace, read_config};
    use std::fs;
    use std::sync::{Mutex, MutexGuard, OnceLock};
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn ensure_manifest_scaffold_uses_runtime_defaults() {
        let root = temp_path("loom-onboard-defaults");
        let config = init_workspace(&root, "embedded", None, "org_demo").expect("init");
        let path = ensure_onboard_manifest(&root, &config).expect("manifest");
        assert!(path.exists());
        let manifest = load_onboard_manifest(&root).expect("load");
        assert_eq!(manifest.gateway_auth_mode, "token");
        assert_eq!(manifest.gateway_bind, "loopback");
        assert_eq!(manifest.gateway_port, 18910);
        assert_eq!(manifest.manager_lane, "frontier");
        assert_eq!(manifest.manager_model, "gpt-5.4");
        assert_eq!(manifest.codex_auth_source, "loom");
        assert!(manifest
            .codex_auth_path
            .ends_with(".meridian/auth/codex/auth.json"));
        assert!(!manifest.telegram_enabled);
        assert_eq!(
            manifest.gateway_token_env,
            read_config(&root).expect("config").service_token_env
        );
    }

    #[test]
    fn derive_service_http_address_tracks_bind_and_port() {
        assert_eq!(
            derive_service_http_address("loopback", 18789),
            "127.0.0.1:18789"
        );
        assert_eq!(derive_service_http_address("all", 18789), "0.0.0.0:18789");
    }

    #[test]
    fn detect_setup_state_marks_configured_provider_without_auth_as_pending() {
        let root = temp_path("loom-onboard-provider-pending");
        let fake_home = root.join("fake-home");
        fs::create_dir_all(&fake_home).expect("create fake home");
        let _home_guard = home_env_guard();
        let previous_home = std::env::var("HOME").ok();
        std::env::set_var("HOME", &fake_home);
        let config = init_workspace(&root, "embedded", None, "org_demo").expect("init");
        ensure_onboard_manifest(&root, &config).expect("manifest");
        let mut manifest = load_onboard_manifest(&root).expect("manifest");
        manifest.last_action = "setup".to_string();
        write_onboard_manifest(&root, &manifest).expect("write manifest");
        configure_onboard_provider_profile(
            &root,
            &OnboardProviderRouteConfig {
                profile_name: "openai_default".to_string(),
                kind: ProviderKind::OpenAiCompatible,
                base_url: "https://api.openai.com/v1/chat/completions".to_string(),
                default_model: "gpt-5.4-mini".to_string(),
                auth: ProviderAuthMode::BearerEnv {
                    env_var: "OPENAI_API_KEY".to_string(),
                },
                note: "test profile".to_string(),
                make_default: true,
            },
        )
        .expect("provider profile");

        let state = detect_setup_state(&root);
        restore_home(previous_home);
        match state {
            SetupState::ProviderConfiguredAuthPending {
                profiles,
                provider_count,
            } => {
                assert_eq!(profiles, vec!["openai_default".to_string()]);
                assert!(provider_count >= 2);
            }
            other => panic!("expected provider-configured-auth-pending, got {:?}", other),
        }
    }

    #[test]
    fn detect_setup_state_keeps_fresh_runtime_at_no_auth_before_setup() {
        let root = temp_path("loom-onboard-fresh-no-auth");
        let fake_home = root.join("fake-home");
        fs::create_dir_all(&fake_home).expect("create fake home");
        let _home_guard = home_env_guard();
        let previous_home = std::env::var("HOME").ok();
        std::env::set_var("HOME", &fake_home);
        let config = init_workspace(&root, "embedded", None, "org_demo").expect("init");
        ensure_onboard_manifest(&root, &config).expect("manifest");

        let state = detect_setup_state(&root);
        restore_home(previous_home);
        match state {
            SetupState::FreshNoAuth { provider_count } => {
                assert!(provider_count >= 1);
            }
            other => panic!("expected fresh_no_auth, got {:?}", other),
        }
    }

    fn home_env_guard() -> MutexGuard<'static, ()> {
        static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        LOCK.get_or_init(|| Mutex::new(()))
            .lock()
            .expect("lock HOME env")
    }

    fn restore_home(previous_home: Option<String>) {
        if let Some(home) = previous_home {
            std::env::set_var("HOME", home);
        } else {
            std::env::remove_var("HOME");
        }
    }

    fn temp_path(label: &str) -> PathBuf {
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        std::env::temp_dir().join(format!("{}-{}", label, timestamp))
    }
}
