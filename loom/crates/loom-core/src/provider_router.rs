use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};
use url::Url;

#[cfg(test)]
#[allow(clippy::duplicate_mod)]
#[path = "agent_runtime.rs"]
mod agent_runtime;

#[cfg(not(test))]
use crate::agent_runtime;

type LoomResult<T> = Result<T, String>;

pub const DEFAULT_PROVIDER_PROFILES_PATH: &str = "providers/profiles.json";
const DEFAULT_LOCAL_PROFILE_NAME: &str = "local_ollama";
const DEFAULT_OPENAI_PROFILE_NAME: &str = "openai_default";
const DEFAULT_CUSTOM_PROFILE_NAME: &str = "custom_endpoint";
const DEFAULT_CODEX_BASE_URL: &str = "https://chatgpt.com/backend-api";
const DEFAULT_CODEX_MODEL_ALIAS: &str = "gpt-5.4";
const DEFAULT_SHARED_CODEX_AUTH_PATH: &str = ".codex/auth.json";
const DEFAULT_LOOM_CODEX_AUTH_PATH: &str = ".meridian/auth/codex/auth.json";
const DEFAULT_LOCAL_OLLAMA_ENDPOINT: &str = "http://127.0.0.1:11434/v1/chat/completions";
const DEFAULT_OPENAI_ENDPOINT: &str = "https://api.openai.com/v1/chat/completions";
const DEFAULT_MODEL_ALIAS: &str = "qwen2.5:7b";
const DEFAULT_BEARER_ENV: &str = "OPENAI_API_KEY";
const ENV_PROVIDER_PROFILE: &str = "LLM_PROVIDER_PROFILE";
const ENV_PROVIDER_PROFILES_PATH: &str = "LLM_PROVIDER_PROFILES_PATH";
const ENV_PROVIDER_KIND: &str = "LLM_PROVIDER_KIND";
const ENV_AUTH_MODE: &str = "LLM_AUTH_MODE";
const ENV_AUTH_ENV_VAR: &str = "LLM_AUTH_ENV_VAR";
const ENV_AUTH_HEADER_NAME: &str = "LLM_AUTH_HEADER_NAME";
const ENV_AUTH_PATH: &str = "LLM_AUTH_PATH";
const ENV_LLM_BASE_URL: &str = "LLM_BASE_URL";
const ENV_LLM_MODEL: &str = "LLM_MODEL";

const FRONTIER_PROFILE_SPECS: &[(&str, &str)] = &[
    (
        "manager_frontier",
        "seeded Codex OAuth route for manager reasoning",
    ),
    (
        "research_frontier",
        "seeded Codex OAuth route for research reasoning",
    ),
    (
        "writer_general",
        "seeded Codex OAuth route for structured writing",
    ),
    ("qa_frontier", "seeded Codex OAuth route for QA evaluation"),
    (
        "verifier_frontier",
        "seeded Codex OAuth route for contradiction review",
    ),
    (
        "executor_tooling",
        "seeded Codex OAuth route for governed execution",
    ),
];

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ProviderKind {
    LocalOllama,
    OpenAiCompatible,
    OpenAiCodex,
    CustomEndpoint,
}

impl ProviderKind {
    pub fn label(&self) -> &'static str {
        match self {
            Self::LocalOllama => "local_ollama",
            Self::OpenAiCompatible => "openai_compatible",
            Self::OpenAiCodex => "openai_codex",
            Self::CustomEndpoint => "custom_endpoint",
        }
    }

    fn from_str(raw: &str) -> Option<Self> {
        match raw.trim().to_ascii_lowercase().as_str() {
            "local_ollama" | "ollama" => Some(Self::LocalOllama),
            "openai_compatible" | "openai-compatible" | "openai" => Some(Self::OpenAiCompatible),
            "openai_codex" | "openai-codex" | "codex" => Some(Self::OpenAiCodex),
            "custom_endpoint" | "custom-endpoint" | "custom" => Some(Self::CustomEndpoint),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ProviderAuthMode {
    None,
    BearerEnv {
        env_var: String,
    },
    StaticHeaderEnv {
        header_name: String,
        env_var: String,
    },
    CodexAuthJson {
        path: Option<String>,
    },
}

impl ProviderAuthMode {
    pub fn label(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::BearerEnv { .. } => "bearer_env",
            Self::StaticHeaderEnv { .. } => "static_header_env",
            Self::CodexAuthJson { .. } => "codex_auth_json",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProviderProfile {
    pub name: String,
    pub kind: ProviderKind,
    pub base_url: String,
    pub default_model: String,
    pub auth: ProviderAuthMode,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Default)]
pub struct ProviderRoutePolicy {
    pub profile_name: Option<String>,
    pub default_model: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Default)]
pub struct ProviderRoutingTable {
    pub capabilities: BTreeMap<String, ProviderRoutePolicy>,
    pub agents: BTreeMap<String, ProviderRoutePolicy>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProviderProfileSet {
    pub default_profile_name: String,
    pub profiles: Vec<ProviderProfile>,
    pub routing: ProviderRoutingTable,
    pub source: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProviderRouteIntent {
    pub capability_name: String,
    pub preferred_profile_name: Option<String>,
    pub requested_model: String,
    pub agent_id: Option<String>,
    pub org_id: Option<String>,
}

impl ProviderRouteIntent {
    pub fn for_capability(capability_name: &str, requested_model: &str) -> Self {
        Self {
            capability_name: if capability_name.trim().is_empty() {
                "loom.llm.inference.v1".to_string()
            } else {
                capability_name.trim().to_string()
            },
            preferred_profile_name: env_trimmed(ENV_PROVIDER_PROFILE),
            requested_model: requested_model.trim().to_string(),
            agent_id: None,
            org_id: None,
        }
    }

    pub fn llm_inference(requested_model: &str) -> Self {
        Self::for_capability("loom.llm.inference.v1", requested_model)
    }

    pub fn with_agent_id(mut self, agent_id: &str) -> Self {
        self.agent_id = trim_to_option(agent_id);
        self
    }

    pub fn with_org_id(mut self, org_id: &str) -> Self {
        self.org_id = trim_to_option(org_id);
        self
    }

    pub fn with_preferred_profile_name(mut self, profile_name: &str) -> Self {
        self.preferred_profile_name = trim_to_option(profile_name);
        self
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResolvedProviderRoute {
    pub capability_name: String,
    pub profile_name: String,
    pub profile_kind: ProviderKind,
    pub endpoint_url: Url,
    pub model: String,
    pub auth: ProviderAuthMode,
    pub source: String,
    pub note: String,
    pub matched_rule: String,
    pub agent_id: Option<String>,
    pub org_id: Option<String>,
}

impl ResolvedProviderRoute {
    pub fn transport_kind(&self) -> &'static str {
        match self.profile_kind {
            ProviderKind::LocalOllama => "ollama_local",
            ProviderKind::OpenAiCompatible => "openai_rest",
            ProviderKind::OpenAiCodex => "codex_session",
            ProviderKind::CustomEndpoint => "custom_http",
        }
    }

    pub fn execution_owner(&self) -> &'static str {
        "meridian"
    }

    pub fn resolve_auth_headers(&self) -> LoomResult<Vec<(String, String)>> {
        match &self.auth {
            ProviderAuthMode::None => Ok(vec![]),
            ProviderAuthMode::BearerEnv { env_var } => {
                let value = std::env::var(env_var)
                    .ok()
                    .map(|raw| raw.trim().to_string())
                    .filter(|raw| !raw.is_empty())
                    .ok_or_else(|| {
                        format!(
                            "provider profile '{}' requires bearer token env {}",
                            self.profile_name, env_var
                        )
                    })?;
                Ok(vec![(
                    "authorization".to_string(),
                    format!("Bearer {value}"),
                )])
            }
            ProviderAuthMode::StaticHeaderEnv {
                header_name,
                env_var,
            } => {
                let value = std::env::var(env_var)
                    .ok()
                    .map(|raw| raw.trim().to_string())
                    .filter(|raw| !raw.is_empty())
                    .ok_or_else(|| {
                        format!(
                            "provider profile '{}' requires header env {}",
                            self.profile_name, env_var
                        )
                    })?;
                Ok(vec![(header_name.clone(), value)])
            }
            ProviderAuthMode::CodexAuthJson { path } => {
                let material = read_codex_auth_material(path.as_deref())?;
                let mut headers = vec![(
                    "authorization".to_string(),
                    format!("Bearer {}", material.access_token),
                )];
                if let Some(account_id) = material.account_id.as_deref() {
                    headers.push(("ChatGPT-Account-Id".to_string(), account_id.to_string()));
                }
                Ok(headers)
            }
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct CodexAuthMaterial {
    auth_path: PathBuf,
    access_token: String,
    refresh_token: Option<String>,
    account_id: Option<String>,
    last_refresh: Option<String>,
    identity: CodexIdentityFingerprint,
}

#[derive(Clone, Debug, PartialEq, Eq, Default)]
pub struct CodexIdentityFingerprint {
    pub account_id: Option<String>,
    pub subject_id: Option<String>,
    pub email: Option<String>,
    pub name: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProviderPlaneSummary {
    pub profiles_path: PathBuf,
    pub source: String,
    pub default_profile_name: String,
    pub profile_count: usize,
    pub capability_route_count: usize,
    pub agent_route_count: usize,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnboardProviderRouteConfig {
    pub profile_name: String,
    pub kind: ProviderKind,
    pub base_url: String,
    pub default_model: String,
    pub auth: ProviderAuthMode,
    pub note: String,
    pub make_default: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProviderAuthStatus {
    pub profile_name: String,
    pub profile_kind: ProviderKind,
    pub auth_mode: String,
    pub env_var: Option<String>,
    pub header_name: Option<String>,
    pub credential_path: Option<String>,
    pub source: String,
    pub ready: bool,
    pub detail: String,
}

pub fn ensure_provider_profiles_scaffold(root: &Path) -> LoomResult<PathBuf> {
    let path = provider_profiles_path(root);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    if !path.exists() {
        fs::write(&path, render_default_provider_profiles()).map_err(io_err)?;
    }
    Ok(path)
}

pub fn default_codex_auth_path_hint() -> LoomResult<PathBuf> {
    resolve_loom_codex_auth_path(None)
}

pub fn shared_codex_auth_path_hint() -> LoomResult<PathBuf> {
    resolve_codex_auth_path(None)
}

pub fn configure_onboard_provider_routes(
    root: &Path,
    manager_lane: &str,
    manager_model: Option<&str>,
    codex_auth_path: Option<&str>,
) -> LoomResult<PathBuf> {
    ensure_provider_profiles_scaffold(root)?;
    let mut profiles = load_provider_profiles(Some(root))?;
    let resolved_manager_model = manager_model.and_then(trim_to_option).unwrap_or_else(|| {
        match manager_lane.trim().to_ascii_lowercase().as_str() {
            "local" => DEFAULT_MODEL_ALIAS.to_string(),
            _ => DEFAULT_CODEX_MODEL_ALIAS.to_string(),
        }
    });
    let resolved_frontier_auth_path = if matches!(
        manager_lane.trim().to_ascii_lowercase().as_str(),
        "" | "frontier" | "codex"
    ) {
        Some(codex_auth_path.and_then(trim_to_option).unwrap_or_else(|| {
            default_codex_auth_path_hint()
                .map(|path| path.display().to_string())
                .unwrap_or_else(|_| DEFAULT_LOOM_CODEX_AUTH_PATH.to_string())
        }))
    } else {
        codex_auth_path.and_then(trim_to_option)
    };
    apply_frontier_profile_defaults(
        &mut profiles,
        resolved_frontier_auth_path.as_deref(),
        Some(&resolved_manager_model),
    );

    let manager_policy = match manager_lane.trim().to_ascii_lowercase().as_str() {
        "" | "frontier" | "codex" => ProviderRoutePolicy {
            profile_name: Some("manager_frontier".to_string()),
            default_model: Some(resolved_manager_model.clone()),
        },
        "local" => ProviderRoutePolicy {
            profile_name: Some(DEFAULT_LOCAL_PROFILE_NAME.to_string()),
            default_model: Some(resolved_manager_model.clone()),
        },
        other => {
            return Err(format!(
                "unsupported manager lane '{}'; expected 'frontier' or 'local'",
                other
            ));
        }
    };

    profiles
        .routing
        .agents
        .insert("leviathann".to_string(), manager_policy);

    persist_provider_profiles(root, &profiles)
}

pub fn configure_onboard_provider_profile(
    root: &Path,
    config: &OnboardProviderRouteConfig,
) -> LoomResult<PathBuf> {
    ensure_provider_profiles_scaffold(root)?;
    let mut profiles = load_provider_profiles(Some(root))?;
    let route_model = trim_to_option(&config.default_model).unwrap_or_else(|| match config.kind {
        ProviderKind::OpenAiCodex => DEFAULT_CODEX_MODEL_ALIAS.to_string(),
        ProviderKind::LocalOllama => DEFAULT_MODEL_ALIAS.to_string(),
        _ => DEFAULT_CODEX_MODEL_ALIAS.to_string(),
    });

    upsert_provider_profile(
        &mut profiles,
        ProviderProfile {
            name: config.profile_name.clone(),
            kind: config.kind.clone(),
            base_url: config.base_url.trim().to_string(),
            default_model: route_model.clone(),
            auth: config.auth.clone(),
            note: config.note.trim().to_string(),
        },
    );

    if config.make_default {
        profiles.default_profile_name = config.profile_name.clone();
    }
    profiles.routing.capabilities.insert(
        "loom.llm.inference.v1".to_string(),
        ProviderRoutePolicy {
            profile_name: Some(config.profile_name.clone()),
            default_model: Some(route_model.clone()),
        },
    );
    profiles.routing.agents.insert(
        "leviathann".to_string(),
        ProviderRoutePolicy {
            profile_name: Some(config.profile_name.clone()),
            default_model: Some(route_model),
        },
    );

    persist_provider_profiles(root, &profiles)
}

pub fn provider_profiles_runtime_path(root: Option<&Path>) -> LoomResult<PathBuf> {
    let root = resolve_runtime_root(root)?;
    Ok(provider_profiles_path(&root))
}

pub fn provider_plane_summary(root: Option<&Path>) -> LoomResult<ProviderPlaneSummary> {
    let root = resolve_runtime_root(root)?;
    let profiles = load_provider_profiles(Some(&root))?;
    Ok(ProviderPlaneSummary {
        profiles_path: provider_profiles_path(&root),
        source: profiles.source,
        default_profile_name: profiles.default_profile_name,
        profile_count: profiles.profiles.len(),
        capability_route_count: profiles.routing.capabilities.len(),
        agent_route_count: profiles.routing.agents.len(),
    })
}

pub fn provider_auth_status(
    root: Option<&Path>,
    profile_name: Option<&str>,
) -> LoomResult<ProviderAuthStatus> {
    let profiles = load_provider_profiles(root)?;
    let selected_profile_name = profile_name
        .and_then(trim_to_option)
        .unwrap_or_else(|| profiles.default_profile_name.clone());
    let profile = profiles
        .profiles
        .iter()
        .find(|candidate| candidate.name == selected_profile_name)
        .ok_or_else(|| {
            let available = profiles
                .profiles
                .iter()
                .map(|profile| profile.name.clone())
                .collect::<Vec<_>>()
                .join(", ");
            format!(
                "provider profile '{}' was not found (available: {})",
                selected_profile_name, available
            )
        })?;
    let (env_var, header_name, credential_path, ready, detail) = match &profile.auth {
        ProviderAuthMode::None => (
            None,
            None,
            None,
            true,
            "profile does not require external credentials".to_string(),
        ),
        ProviderAuthMode::BearerEnv { env_var } => {
            let ready = env_trimmed(env_var).is_some();
            (
                Some(env_var.clone()),
                Some("authorization".to_string()),
                None,
                ready,
                if ready {
                    format!("bearer token env {} is present", env_var)
                } else {
                    format!("bearer token env {} is missing", env_var)
                },
            )
        }
        ProviderAuthMode::StaticHeaderEnv {
            header_name,
            env_var,
        } => {
            let ready = env_trimmed(env_var).is_some();
            (
                Some(env_var.clone()),
                Some(header_name.clone()),
                None,
                ready,
                if ready {
                    format!("header env {} is present for {}", env_var, header_name)
                } else {
                    format!("header env {} is missing for {}", env_var, header_name)
                },
            )
        }
        ProviderAuthMode::CodexAuthJson { path } => match read_codex_auth_material(path.as_deref())
        {
            Ok(material) => (
                None,
                Some("authorization".to_string()),
                Some(material.auth_path.display().to_string()),
                true,
                format!(
                    "Codex OAuth auth.json is ready (identity={}, refresh_token={})",
                    describe_codex_identity(&material.identity),
                    if material.refresh_token.as_deref().unwrap_or("").is_empty() {
                        "missing"
                    } else {
                        "present"
                    }
                ),
            ),
            Err(error) => {
                let auth_path = resolve_codex_auth_path(path.as_deref())?;
                (
                    None,
                    Some("authorization".to_string()),
                    Some(auth_path.display().to_string()),
                    false,
                    error,
                )
            }
        },
    };
    Ok(ProviderAuthStatus {
        profile_name: profile.name.clone(),
        profile_kind: profile.kind.clone(),
        auth_mode: profile.auth.label().to_string(),
        env_var,
        header_name,
        credential_path,
        source: profiles.source,
        ready,
        detail,
    })
}

pub fn load_provider_profiles(root: Option<&Path>) -> LoomResult<ProviderProfileSet> {
    let root = resolve_runtime_root(root)?;
    let path = provider_profiles_path(&root);
    if path.exists() {
        let raw = fs::read_to_string(&path).map_err(io_err)?;
        let mut profiles = parse_provider_profiles_json(&raw)?;
        profiles.source = path.display().to_string();
        return augment_provider_profiles(&root, profiles);
    }
    augment_provider_profiles(&root, env_default_provider_profiles())
}

pub fn resolve_provider_route(
    root: Option<&Path>,
    intent: &ProviderRouteIntent,
) -> LoomResult<ResolvedProviderRoute> {
    let root = resolve_runtime_root(root)?;
    let profiles = load_provider_profiles(Some(&root))?;
    let agent_policy = intent
        .agent_id
        .as_ref()
        .and_then(|agent_id| profiles.routing.agents.get(agent_id));
    let capability_policy = profiles.routing.capabilities.get(&intent.capability_name);
    let agent_runtime_profile = intent
        .agent_id
        .as_ref()
        .and_then(|agent_id| agent_runtime::agent_provider_profile(&root, agent_id).ok());
    let explicit_profile = intent.preferred_profile_name.clone();
    let agent_policy_profile = agent_policy.and_then(|policy| policy.profile_name.clone());
    let capability_policy_profile =
        capability_policy.and_then(|policy| policy.profile_name.clone());
    let profile_name = explicit_profile
        .clone()
        .or_else(|| agent_policy_profile.clone())
        .or_else(|| agent_runtime_profile.clone())
        .or_else(|| capability_policy_profile.clone())
        .unwrap_or_else(|| profiles.default_profile_name.clone());
    let matched_rule = if explicit_profile.is_some() {
        "explicit_profile".to_string()
    } else if let Some(agent_id) = &intent.agent_id {
        if agent_policy_profile.is_some() {
            format!("agent:{}", agent_id)
        } else if agent_runtime_profile.is_some() {
            format!("agent_runtime:{}", agent_id)
        } else if capability_policy_profile.is_some() {
            format!("capability:{}", intent.capability_name)
        } else {
            "default_profile".to_string()
        }
    } else if capability_policy_profile.is_some() {
        format!("capability:{}", intent.capability_name)
    } else {
        "default_profile".to_string()
    };
    let profile = profiles
        .profiles
        .iter()
        .find(|candidate| candidate.name == profile_name)
        .ok_or_else(|| {
            let available = profiles
                .profiles
                .iter()
                .map(|profile| profile.name.clone())
                .collect::<Vec<_>>()
                .join(", ");
            format!(
                "provider profile '{}' was not found (available: {})",
                profile_name, available
            )
        })?;
    let auth_status = provider_auth_status(Some(&root), Some(&profile.name))?;
    if !auth_status.ready {
        return Err(format!(
            "provider profile '{}' is not ready: {}",
            profile.name, auth_status.detail
        ));
    }
    let endpoint_url = normalize_endpoint_url(&profile.kind, &profile.base_url)?;
    let model = if !intent.requested_model.trim().is_empty() {
        intent.requested_model.trim().to_string()
    } else if explicit_profile.is_some() {
        profile.default_model.clone()
    } else if let Some(policy) = agent_policy {
        policy
            .default_model
            .clone()
            .or_else(|| capability_policy.and_then(|item| item.default_model.clone()))
            .unwrap_or_else(|| profile.default_model.clone())
    } else if agent_runtime_profile.is_some() {
        profile.default_model.clone()
    } else if let Some(policy) = capability_policy {
        policy
            .default_model
            .clone()
            .unwrap_or_else(|| profile.default_model.clone())
    } else {
        profile.default_model.clone()
    };
    let note = match matched_rule.as_str() {
        "explicit_profile" => "resolved from explicit provider profile override".to_string(),
        "default_profile" => "resolved from runtime default provider profile".to_string(),
        _ if matched_rule.starts_with("agent:") => {
            format!(
                "resolved from agent-scoped provider routing rule ({})",
                matched_rule
            )
        }
        _ if matched_rule.starts_with("agent_runtime:") => {
            format!(
                "resolved from agent runtime provider profile ({})",
                matched_rule
            )
        }
        _ if matched_rule.starts_with("capability:") => {
            format!(
                "resolved from capability-scoped provider routing rule ({})",
                matched_rule
            )
        }
        _ => profile.note.clone(),
    };
    Ok(ResolvedProviderRoute {
        capability_name: intent.capability_name.clone(),
        profile_name: profile.name.clone(),
        profile_kind: profile.kind.clone(),
        endpoint_url,
        model,
        auth: profile.auth.clone(),
        source: profiles.source,
        note,
        matched_rule,
        agent_id: intent.agent_id.clone(),
        org_id: intent.org_id.clone(),
    })
}

pub fn resolve_llm_route(
    root: Option<&Path>,
    intent: &ProviderRouteIntent,
) -> LoomResult<ResolvedProviderRoute> {
    resolve_provider_route(root, intent)
}

pub fn render_provider_plane_human(summary: &ProviderPlaneSummary) -> String {
    format!(
        "profiles_path:      {}
provider_source:    {}
default_profile:    {}
profile_count:      {}
capability_routes:  {}
agent_routes:       {}
",
        summary.profiles_path.display(),
        summary.source,
        summary.default_profile_name,
        summary.profile_count,
        summary.capability_route_count,
        summary.agent_route_count,
    )
}

pub fn render_provider_plane_json(summary: &ProviderPlaneSummary) -> String {
    format!(
        "{{\n  \"profiles_path\": {},\n  \"provider_source\": {},\n  \"default_profile\": {},\n  \"profile_count\": {},\n  \"capability_routes\": {},\n  \"agent_routes\": {}\n}}\n",
        json_string(&summary.profiles_path.display().to_string()),
        json_string(&summary.source),
        json_string(&summary.default_profile_name),
        summary.profile_count,
        summary.capability_route_count,
        summary.agent_route_count,
    )
}

pub fn render_provider_auth_human(status: &ProviderAuthStatus) -> String {
    format!(
        "profile:            {} ({})
auth_mode:          {}
header_name:        {}
env_var:            {}
credential_path:    {}
ready:              {}
source:             {}
detail:             {}
",
        status.profile_name,
        status.profile_kind.label(),
        status.auth_mode,
        status.header_name.as_deref().unwrap_or("(none)"),
        status.env_var.as_deref().unwrap_or("(none)"),
        status.credential_path.as_deref().unwrap_or("(none)"),
        if status.ready { "yes" } else { "no" },
        status.source,
        status.detail,
    )
}

pub fn render_provider_auth_json(status: &ProviderAuthStatus) -> String {
    format!(
        "{{
  \"profile\": {},
  \"profile_kind\": {},
  \"auth_mode\": {},
  \"header_name\": {},
  \"env_var\": {},
  \"credential_path\": {},
  \"ready\": {},
  \"source\": {},
  \"detail\": {}
}}
",
        json_string(&status.profile_name),
        json_string(status.profile_kind.label()),
        json_string(&status.auth_mode),
        json_option(status.header_name.as_deref()),
        json_option(status.env_var.as_deref()),
        json_option(status.credential_path.as_deref()),
        if status.ready { "true" } else { "false" },
        json_string(&status.source),
        json_string(&status.detail),
    )
}

pub fn render_provider_route_human(route: &ResolvedProviderRoute) -> String {
    format!(
        "capability:         {}
profile:            {} ({})
transport_kind:     {}
auth_mode:          {}
execution_owner:    {}
endpoint:           {}
model:              {}
matched_rule:       {}
source:             {}
note:               {}
",
        route.capability_name,
        route.profile_name,
        route.profile_kind.label(),
        route.transport_kind(),
        route.auth.label(),
        route.execution_owner(),
        route.endpoint_url,
        route.model,
        route.matched_rule,
        route.source,
        route.note,
    )
}

pub fn render_provider_route_json(route: &ResolvedProviderRoute) -> String {
    format!(
        "{{
  \"capability\": {},
  \"profile\": {},
  \"profile_kind\": {},
  \"transport_kind\": {},
  \"auth_mode\": {},
  \"execution_owner\": {},
  \"endpoint\": {},
  \"model\": {},
  \"matched_rule\": {},
  \"source\": {},
  \"note\": {},
  \"agent_id\": {},
  \"org_id\": {}
}}
",
        json_string(&route.capability_name),
        json_string(&route.profile_name),
        json_string(route.profile_kind.label()),
        json_string(route.transport_kind()),
        json_string(route.auth.label()),
        json_string(route.execution_owner()),
        json_string(route.endpoint_url.as_str()),
        json_string(&route.model),
        json_string(&route.matched_rule),
        json_string(&route.source),
        json_string(&route.note),
        json_option(route.agent_id.as_deref()),
        json_option(route.org_id.as_deref()),
    )
}

fn resolve_runtime_root(root: Option<&Path>) -> LoomResult<PathBuf> {
    match root {
        Some(path) => Ok(path.to_path_buf()),
        None => {
            let current_dir = std::env::current_dir().map_err(io_err)?;
            if current_dir.join("loom.toml").exists() {
                Ok(current_dir)
            } else {
                default_app_home()
            }
        }
    }
}

fn default_app_home() -> LoomResult<PathBuf> {
    if let Ok(value) = std::env::var("LOOM_ROOT") {
        let trimmed = value.trim();
        if !trimmed.is_empty() {
            return Ok(PathBuf::from(trimmed));
        }
    }
    if let Ok(value) = std::env::var("XDG_DATA_HOME") {
        let trimmed = value.trim();
        if !trimmed.is_empty() {
            return Ok(PathBuf::from(trimmed)
                .join("meridian-loom")
                .join("runtime")
                .join("default"));
        }
    }
    let home = std::env::var("HOME")
        .map_err(|_| "HOME is not set and no Loom runtime root was provided".to_string())?;
    Ok(PathBuf::from(home)
        .join(".local/share/meridian-loom")
        .join("runtime")
        .join("default"))
}

fn provider_profiles_path(root: &Path) -> PathBuf {
    match env_trimmed(ENV_PROVIDER_PROFILES_PATH) {
        Some(raw) => PathBuf::from(raw),
        None => root.join(DEFAULT_PROVIDER_PROFILES_PATH),
    }
}

fn render_default_provider_profiles() -> String {
    let mut profiles = ProviderProfileSet {
        default_profile_name: DEFAULT_LOCAL_PROFILE_NAME.to_string(),
        profiles: vec![ProviderProfile {
            name: DEFAULT_LOCAL_PROFILE_NAME.to_string(),
            kind: ProviderKind::LocalOllama,
            base_url: DEFAULT_LOCAL_OLLAMA_ENDPOINT.to_string(),
            default_model: DEFAULT_MODEL_ALIAS.to_string(),
            auth: ProviderAuthMode::None,
            note: "seeded Meridian local inference route for the bounded LLM host call".to_string(),
        }],
        routing: ProviderRoutingTable {
            capabilities: BTreeMap::from([(
                "loom.llm.inference.v1".to_string(),
                ProviderRoutePolicy {
                    profile_name: Some(DEFAULT_LOCAL_PROFILE_NAME.to_string()),
                    default_model: Some(DEFAULT_MODEL_ALIAS.to_string()),
                },
            )]),
            agents: BTreeMap::new(),
        },
        source: "runtime_provider_file".to_string(),
    };
    ensure_frontier_profiles(&mut profiles);
    render_provider_profiles(&profiles)
}

fn parse_provider_profiles_json(raw: &str) -> LoomResult<ProviderProfileSet> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| format!("invalid provider profiles json: {error}"))?;
    let default_profile_name =
        value_string_or(value.get("default_profile"), DEFAULT_LOCAL_PROFILE_NAME);
    let profiles = value
        .get("profiles")
        .and_then(Value::as_array)
        .ok_or_else(|| "provider profiles file must define a profiles array".to_string())?;
    if profiles.is_empty() {
        return Err("provider profiles file must define at least one profile".to_string());
    }
    let mut parsed_profiles = Vec::with_capacity(profiles.len());
    for raw_profile in profiles {
        parsed_profiles.push(parse_provider_profile(raw_profile)?);
    }
    Ok(ProviderProfileSet {
        default_profile_name,
        profiles: parsed_profiles,
        routing: parse_provider_routing(value.get("routing"))?,
        source: "runtime_provider_file".to_string(),
    })
}

fn parse_provider_profile(value: &Value) -> LoomResult<ProviderProfile> {
    let name = value_string(value.get("name"), "provider profile name")?;
    let kind = ProviderKind::from_str(&value_string_or(value.get("kind"), "openai_compatible"))
        .ok_or_else(|| format!("provider profile '{}' has unsupported kind", name))?;
    let base_url = value_string(value.get("base_url"), "provider profile base_url")?;
    let default_model = value_string_or(value.get("model"), DEFAULT_MODEL_ALIAS);
    let note = value_string_or(value.get("note"), "");
    let auth = parse_provider_auth(value.get("auth"))?;
    Ok(ProviderProfile {
        name,
        kind,
        base_url,
        default_model,
        auth,
        note,
    })
}

fn parse_provider_routing(value: Option<&Value>) -> LoomResult<ProviderRoutingTable> {
    let Some(value) = value else {
        return Ok(ProviderRoutingTable::default());
    };
    Ok(ProviderRoutingTable {
        capabilities: parse_policy_map(value.get("capabilities"))?,
        agents: parse_policy_map(value.get("agents"))?,
    })
}

fn parse_policy_map(value: Option<&Value>) -> LoomResult<BTreeMap<String, ProviderRoutePolicy>> {
    let Some(value) = value else {
        return Ok(BTreeMap::new());
    };
    let object = value
        .as_object()
        .ok_or_else(|| "provider routing entries must be objects".to_string())?;
    let mut policies = BTreeMap::new();
    for (key, raw_policy) in object {
        policies.insert(key.to_string(), parse_route_policy(raw_policy)?);
    }
    Ok(policies)
}

fn parse_route_policy(value: &Value) -> LoomResult<ProviderRoutePolicy> {
    if let Some(profile_name) = value.as_str() {
        return Ok(ProviderRoutePolicy {
            profile_name: trim_to_option(profile_name),
            default_model: None,
        });
    }
    let Some(object) = value.as_object() else {
        return Err("provider route policy must be a string or object".to_string());
    };
    let profile_name = object
        .get("profile")
        .and_then(Value::as_str)
        .or_else(|| object.get("default_profile").and_then(Value::as_str))
        .map(|raw| raw.trim().to_string())
        .filter(|raw| !raw.is_empty());
    let default_model = object
        .get("model")
        .and_then(Value::as_str)
        .or_else(|| object.get("default_model").and_then(Value::as_str))
        .map(|raw| raw.trim().to_string())
        .filter(|raw| !raw.is_empty());
    if profile_name.is_none() && default_model.is_none() {
        return Err("provider route policy object must define profile/default_profile or model/default_model".to_string());
    }
    Ok(ProviderRoutePolicy {
        profile_name,
        default_model,
    })
}

fn parse_provider_auth(value: Option<&Value>) -> LoomResult<ProviderAuthMode> {
    let Some(value) = value else {
        return Ok(ProviderAuthMode::None);
    };
    let mode = value_string_or(value.get("mode"), "none");
    match mode.trim().to_ascii_lowercase().as_str() {
        "none" => Ok(ProviderAuthMode::None),
        "bearer_env" | "bearer-env" => {
            let env_var = value_string_or(value.get("env_var"), DEFAULT_BEARER_ENV);
            Ok(ProviderAuthMode::BearerEnv { env_var })
        }
        "static_header_env" | "static-header-env" => {
            let header_name =
                value_string(value.get("header_name"), "static_header_env.header_name")?;
            let env_var = value_string(value.get("env_var"), "static_header_env.env_var")?;
            Ok(ProviderAuthMode::StaticHeaderEnv {
                header_name,
                env_var,
            })
        }
        "codex_auth_json" | "codex-auth-json" | "oauth" => Ok(ProviderAuthMode::CodexAuthJson {
            path: value
                .get("path")
                .and_then(Value::as_str)
                .map(|raw| raw.trim().to_string())
                .filter(|raw| !raw.is_empty()),
        }),
        _ => Err(format!("unsupported provider auth mode '{}'", mode)),
    }
}

fn env_default_provider_profiles() -> ProviderProfileSet {
    let explicit_base_url = env_trimmed(ENV_LLM_BASE_URL);
    let explicit_model =
        env_trimmed(ENV_LLM_MODEL).unwrap_or_else(|| DEFAULT_MODEL_ALIAS.to_string());
    if let Some(base_url) = explicit_base_url {
        let inferred_kind =
            ProviderKind::from_str(&env_trimmed(ENV_PROVIDER_KIND).unwrap_or_else(|| {
                infer_provider_kind_from_base_url(&base_url)
                    .label()
                    .to_string()
            }))
            .unwrap_or_else(|| infer_provider_kind_from_base_url(&base_url));
        let profile_name =
            env_trimmed(ENV_PROVIDER_PROFILE).unwrap_or_else(|| match inferred_kind {
                ProviderKind::LocalOllama => DEFAULT_LOCAL_PROFILE_NAME.to_string(),
                ProviderKind::OpenAiCompatible => DEFAULT_OPENAI_PROFILE_NAME.to_string(),
                ProviderKind::OpenAiCodex => "openai_codex_default".to_string(),
                ProviderKind::CustomEndpoint => DEFAULT_CUSTOM_PROFILE_NAME.to_string(),
            });
        let auth = env_default_auth_mode(&base_url, &inferred_kind);
        return ProviderProfileSet {
            default_profile_name: profile_name.clone(),
            profiles: vec![ProviderProfile {
                name: profile_name.clone(),
                kind: inferred_kind,
                base_url,
                default_model: explicit_model.clone(),
                auth,
                note: "resolved from environment-backed provider defaults".to_string(),
            }],
            routing: ProviderRoutingTable {
                capabilities: BTreeMap::from([(
                    "loom.llm.inference.v1".to_string(),
                    ProviderRoutePolicy {
                        profile_name: Some(profile_name),
                        default_model: Some(explicit_model),
                    },
                )]),
                agents: BTreeMap::new(),
            },
            source: "env_defaults".to_string(),
        };
    }
    if env_trimmed(DEFAULT_BEARER_ENV).is_some() {
        return ProviderProfileSet {
            default_profile_name: DEFAULT_OPENAI_PROFILE_NAME.to_string(),
            profiles: vec![ProviderProfile {
                name: DEFAULT_OPENAI_PROFILE_NAME.to_string(),
                kind: ProviderKind::OpenAiCompatible,
                base_url: DEFAULT_OPENAI_ENDPOINT.to_string(),
                default_model: explicit_model.clone(),
                auth: ProviderAuthMode::BearerEnv {
                    env_var: DEFAULT_BEARER_ENV.to_string(),
                },
                note: "resolved from OPENAI_API_KEY-backed defaults".to_string(),
            }],
            routing: ProviderRoutingTable {
                capabilities: BTreeMap::from([(
                    "loom.llm.inference.v1".to_string(),
                    ProviderRoutePolicy {
                        profile_name: Some(DEFAULT_OPENAI_PROFILE_NAME.to_string()),
                        default_model: Some(explicit_model),
                    },
                )]),
                agents: BTreeMap::new(),
            },
            source: "env_defaults".to_string(),
        };
    }
    ProviderProfileSet {
        default_profile_name: DEFAULT_LOCAL_PROFILE_NAME.to_string(),
        profiles: vec![ProviderProfile {
            name: DEFAULT_LOCAL_PROFILE_NAME.to_string(),
            kind: ProviderKind::LocalOllama,
            base_url: DEFAULT_LOCAL_OLLAMA_ENDPOINT.to_string(),
            default_model: explicit_model.clone(),
            auth: ProviderAuthMode::None,
            note: "resolved from Meridian local Ollama defaults".to_string(),
        }],
        routing: ProviderRoutingTable {
            capabilities: BTreeMap::from([(
                "loom.llm.inference.v1".to_string(),
                ProviderRoutePolicy {
                    profile_name: Some(DEFAULT_LOCAL_PROFILE_NAME.to_string()),
                    default_model: Some(explicit_model),
                },
            )]),
            agents: BTreeMap::new(),
        },
        source: "env_defaults".to_string(),
    }
}

fn env_default_auth_mode(base_url: &str, kind: &ProviderKind) -> ProviderAuthMode {
    let explicit_mode = env_trimmed(ENV_AUTH_MODE)
        .unwrap_or_else(|| {
            if matches!(kind, ProviderKind::OpenAiCodex) {
                "codex_auth_json".to_string()
            } else if endpoint_is_local(base_url) {
                "none".to_string()
            } else {
                "bearer_env".to_string()
            }
        })
        .to_ascii_lowercase();
    match explicit_mode.as_str() {
        "none" => ProviderAuthMode::None,
        "static_header_env" | "static-header-env" => ProviderAuthMode::StaticHeaderEnv {
            header_name: env_trimmed(ENV_AUTH_HEADER_NAME)
                .unwrap_or_else(|| "x-api-key".to_string()),
            env_var: env_trimmed(ENV_AUTH_ENV_VAR)
                .unwrap_or_else(|| DEFAULT_BEARER_ENV.to_string()),
        },
        "codex_auth_json" | "codex-auth-json" | "oauth" => ProviderAuthMode::CodexAuthJson {
            path: env_trimmed(ENV_AUTH_PATH),
        },
        _ => ProviderAuthMode::BearerEnv {
            env_var: env_trimmed(ENV_AUTH_ENV_VAR)
                .unwrap_or_else(|| DEFAULT_BEARER_ENV.to_string()),
        },
    }
}

fn normalize_endpoint_url(kind: &ProviderKind, raw: &str) -> LoomResult<Url> {
    let mut url =
        Url::parse(raw.trim()).map_err(|error| format!("provider base_url is invalid: {error}"))?;
    let normalized_path = match kind {
        ProviderKind::OpenAiCodex => normalize_path(url.path(), "/responses"),
        _ => normalize_path(url.path(), "/v1/chat/completions"),
    };
    url.set_path(&normalized_path);
    Ok(url)
}

fn endpoint_is_local(raw: &str) -> bool {
    Url::parse(raw)
        .ok()
        .and_then(|url| url.host_str().map(|value| value.to_string()))
        .map(|host| matches!(host.as_str(), "localhost" | "127.0.0.1" | "::1"))
        .unwrap_or(false)
}

fn infer_provider_kind_from_base_url(base_url: &str) -> ProviderKind {
    if endpoint_is_local(base_url) {
        ProviderKind::LocalOllama
    } else if base_url.contains("chatgpt.com") {
        ProviderKind::OpenAiCodex
    } else if base_url.contains("openai.com") {
        ProviderKind::OpenAiCompatible
    } else {
        ProviderKind::CustomEndpoint
    }
}

fn build_frontier_profile(name: &str, note: &str) -> ProviderProfile {
    ProviderProfile {
        name: name.to_string(),
        kind: ProviderKind::OpenAiCodex,
        base_url: DEFAULT_CODEX_BASE_URL.to_string(),
        default_model: DEFAULT_CODEX_MODEL_ALIAS.to_string(),
        auth: ProviderAuthMode::CodexAuthJson { path: None },
        note: note.to_string(),
    }
}

fn augment_provider_profiles(
    _root: &Path,
    mut profiles: ProviderProfileSet,
) -> LoomResult<ProviderProfileSet> {
    ensure_frontier_profiles(&mut profiles);
    Ok(profiles)
}

fn ensure_frontier_profiles(profiles: &mut ProviderProfileSet) {
    for (name, note) in FRONTIER_PROFILE_SPECS {
        if !profiles
            .profiles
            .iter()
            .any(|profile| profile.name == *name)
        {
            profiles.profiles.push(build_frontier_profile(name, note));
        }
    }
}

fn upsert_provider_profile(profiles: &mut ProviderProfileSet, candidate: ProviderProfile) {
    if let Some(existing) = profiles
        .profiles
        .iter_mut()
        .find(|profile| profile.name == candidate.name)
    {
        *existing = candidate;
    } else {
        profiles.profiles.push(candidate);
    }
}

fn apply_frontier_profile_defaults(
    profiles: &mut ProviderProfileSet,
    explicit_path: Option<&str>,
    explicit_model: Option<&str>,
) {
    let path = explicit_path
        .and_then(trim_to_option)
        .map(|value| value.to_string());
    let model = explicit_model
        .and_then(trim_to_option)
        .map(|value| value.to_string());
    for profile in profiles.profiles.iter_mut() {
        if matches!(profile.kind, ProviderKind::OpenAiCodex) {
            profile.auth = ProviderAuthMode::CodexAuthJson { path: path.clone() };
            if let Some(model) = model.as_ref() {
                profile.default_model = model.clone();
            }
        }
    }
}

fn persist_provider_profiles(root: &Path, profiles: &ProviderProfileSet) -> LoomResult<PathBuf> {
    let path = provider_profiles_path(root);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    fs::write(&path, render_provider_profiles(profiles)).map_err(io_err)?;
    Ok(path)
}

fn render_provider_profiles(profiles: &ProviderProfileSet) -> String {
    let rendered = json!({
        "default_profile": profiles.default_profile_name,
        "profiles": profiles
            .profiles
            .iter()
            .map(render_provider_profile_json)
            .collect::<Vec<_>>(),
        "routing": {
            "capabilities": profiles
                .routing
                .capabilities
                .iter()
                .map(|(name, policy)| (name.clone(), render_route_policy_json(policy)))
                .collect::<serde_json::Map<String, Value>>(),
            "agents": profiles
                .routing
                .agents
                .iter()
                .map(|(name, policy)| (name.clone(), render_route_policy_json(policy)))
                .collect::<serde_json::Map<String, Value>>(),
        }
    });
    let mut raw = serde_json::to_string_pretty(&rendered).unwrap_or_else(|_| "{}".to_string());
    raw.push('\n');
    raw
}

fn render_provider_profile_json(profile: &ProviderProfile) -> Value {
    json!({
        "name": profile.name,
        "kind": profile.kind.label(),
        "base_url": profile.base_url,
        "model": profile.default_model,
        "auth": render_provider_auth_json_value(&profile.auth),
        "note": profile.note,
    })
}

fn render_route_policy_json(policy: &ProviderRoutePolicy) -> Value {
    let mut value = serde_json::Map::new();
    if let Some(profile_name) = policy.profile_name.as_ref() {
        value.insert("profile".to_string(), Value::String(profile_name.clone()));
    }
    if let Some(default_model) = policy.default_model.as_ref() {
        value.insert(
            "default_model".to_string(),
            Value::String(default_model.clone()),
        );
    }
    Value::Object(value)
}

fn render_provider_auth_json_value(auth: &ProviderAuthMode) -> Value {
    match auth {
        ProviderAuthMode::None => json!({ "mode": "none" }),
        ProviderAuthMode::BearerEnv { env_var } => json!({
            "mode": "bearer_env",
            "env_var": env_var,
        }),
        ProviderAuthMode::StaticHeaderEnv {
            header_name,
            env_var,
        } => json!({
            "mode": "static_header_env",
            "header_name": header_name,
            "env_var": env_var,
        }),
        ProviderAuthMode::CodexAuthJson { path } => {
            let mut value = serde_json::Map::from_iter([(
                "mode".to_string(),
                Value::String("codex_auth_json".to_string()),
            )]);
            if let Some(path) = path.as_ref() {
                value.insert("path".to_string(), Value::String(path.clone()));
            }
            Value::Object(value)
        }
    }
}

fn resolve_codex_auth_path(explicit_path: Option<&str>) -> LoomResult<PathBuf> {
    let home = std::env::var("HOME")
        .map_err(|_| "HOME is not set and Codex auth.json could not be resolved".to_string())?;
    let path = explicit_path
        .map(str::trim)
        .filter(|raw| !raw.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(DEFAULT_SHARED_CODEX_AUTH_PATH));
    if path.is_absolute() {
        Ok(path)
    } else {
        Ok(PathBuf::from(home).join(path))
    }
}

fn resolve_loom_codex_auth_path(explicit_path: Option<&str>) -> LoomResult<PathBuf> {
    let home = std::env::var("HOME").map_err(|_| {
        "HOME is not set and Loom Codex auth.json could not be resolved".to_string()
    })?;
    let path = explicit_path
        .map(str::trim)
        .filter(|raw| !raw.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(DEFAULT_LOOM_CODEX_AUTH_PATH));
    if path.is_absolute() {
        Ok(path)
    } else {
        Ok(PathBuf::from(home).join(path))
    }
}

fn read_codex_auth_material(explicit_path: Option<&str>) -> LoomResult<CodexAuthMaterial> {
    let auth_path = resolve_codex_auth_path(explicit_path)?;
    let raw = fs::read_to_string(&auth_path).map_err(|error| {
        format!(
            "failed to read Codex auth.json at {}: {}",
            auth_path.display(),
            error
        )
    })?;
    let value: Value = serde_json::from_str(&raw).map_err(|error| {
        format!(
            "invalid Codex auth.json at {}: {}",
            auth_path.display(),
            error
        )
    })?;
    let access_token = value
        .pointer("/tokens/access_token")
        .and_then(Value::as_str)
        .map(|raw| raw.trim().to_string())
        .filter(|raw| !raw.is_empty())
        .ok_or_else(|| {
            format!(
                "Codex auth.json at {} does not contain tokens.access_token",
                auth_path.display()
            )
        })?;
    let refresh_token = value
        .pointer("/tokens/refresh_token")
        .and_then(Value::as_str)
        .map(|raw| raw.trim().to_string())
        .filter(|raw| !raw.is_empty());
    let identity = codex_identity_from_value(&value);
    let account_id = identity.account_id.clone();
    let last_refresh = value
        .get("last_refresh")
        .and_then(Value::as_str)
        .map(|raw| raw.trim().to_string())
        .filter(|raw| !raw.is_empty());
    enforce_dedicated_loom_codex_identity(&auth_path, &identity)?;
    Ok(CodexAuthMaterial {
        auth_path,
        access_token,
        refresh_token,
        account_id,
        last_refresh,
        identity,
    })
}

fn enforce_dedicated_loom_codex_identity(
    auth_path: &Path,
    identity: &CodexIdentityFingerprint,
) -> LoomResult<()> {
    if !is_loom_managed_codex_auth_path(auth_path) {
        return Ok(());
    }
    let shared_path = resolve_codex_auth_path(None)?;
    if auth_path == shared_path {
        return Err(format!(
            "Loom-managed Codex auth at {} resolves to the shared CLI auth path {}; use a dedicated Loom login or switch the provider source to cli if shared auth is intentional",
            auth_path.display(),
            shared_path.display()
        ));
    }
    let Some(shared_identity) = read_codex_identity_fingerprint(&shared_path) else {
        return Ok(());
    };
    if codex_principal_matches(identity, &shared_identity) {
        return Err(format!(
            "Loom-managed Codex auth at {} is using the shared CLI identity {}; sign in with a dedicated Loom account or switch the provider source to cli if shared auth is intentional",
            auth_path.display(),
            describe_codex_identity(&shared_identity)
        ));
    }
    Ok(())
}

fn is_loom_managed_codex_auth_path(path: &Path) -> bool {
    let normalized = path.to_string_lossy().replace('\\', "/");
    normalized.ends_with("/.meridian/auth/codex/auth.json")
        || normalized == ".meridian/auth/codex/auth.json"
}

pub fn read_codex_identity_fingerprint(path: &Path) -> Option<CodexIdentityFingerprint> {
    let raw = fs::read_to_string(path).ok()?;
    let value: Value = serde_json::from_str(&raw).ok()?;
    Some(codex_identity_from_value(&value))
}

fn codex_identity_from_value(value: &Value) -> CodexIdentityFingerprint {
    let account_id = value
        .pointer("/tokens/account_id")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|raw| !raw.is_empty())
        .map(ToOwned::to_owned);
    let id_token = value
        .pointer("/tokens/id_token")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|raw| !raw.is_empty());
    let claims = id_token
        .and_then(decode_jwt_payload_json)
        .unwrap_or(Value::Null);
    let subject_id = claims
        .get("sub")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|raw| !raw.is_empty())
        .map(ToOwned::to_owned);
    let email = claims
        .get("email")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|raw| !raw.is_empty())
        .map(ToOwned::to_owned);
    let name = claims
        .get("name")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|raw| !raw.is_empty())
        .map(ToOwned::to_owned);
    CodexIdentityFingerprint {
        account_id,
        subject_id,
        email,
        name,
    }
}

fn decode_jwt_payload_json(token: &str) -> Option<Value> {
    let mut parts = token.split('.');
    let _header = parts.next()?;
    let payload = parts.next()?;
    let decoded = decode_base64_url(payload)?;
    serde_json::from_slice(&decoded).ok()
}

fn decode_base64_url(raw: &str) -> Option<Vec<u8>> {
    let mut bits: u32 = 0;
    let mut bit_count: u8 = 0;
    let mut out = Vec::with_capacity(raw.len() * 3 / 4);
    for ch in raw.bytes() {
        let value = match ch {
            b'A'..=b'Z' => ch - b'A',
            b'a'..=b'z' => ch - b'a' + 26,
            b'0'..=b'9' => ch - b'0' + 52,
            b'-' => 62,
            b'_' => 63,
            b'=' => continue,
            _ => return None,
        } as u32;
        bits = (bits << 6) | value;
        bit_count += 6;
        while bit_count >= 8 {
            bit_count -= 8;
            out.push(((bits >> bit_count) & 0xFF) as u8);
            if bit_count > 0 {
                bits &= (1u32 << bit_count) - 1;
            } else {
                bits = 0;
            }
        }
    }
    Some(out)
}

fn codex_principal_matches(
    left: &CodexIdentityFingerprint,
    right: &CodexIdentityFingerprint,
) -> bool {
    if let (Some(left), Some(right)) = (left.subject_id.as_deref(), right.subject_id.as_deref()) {
        return left == right;
    }
    if let (Some(left), Some(right)) = (left.email.as_deref(), right.email.as_deref()) {
        return left.eq_ignore_ascii_case(right);
    }
    if let (Some(left), Some(right)) = (left.account_id.as_deref(), right.account_id.as_deref()) {
        return left == right;
    }
    false
}

fn describe_codex_identity(identity: &CodexIdentityFingerprint) -> String {
    match (
        identity.name.as_deref().filter(|value| !value.is_empty()),
        identity.email.as_deref().filter(|value| !value.is_empty()),
        identity
            .subject_id
            .as_deref()
            .filter(|value| !value.is_empty()),
        identity
            .account_id
            .as_deref()
            .filter(|value| !value.is_empty()),
    ) {
        (Some(name), Some(email), _, _) => format!("{} <{}>", name, email),
        (Some(name), None, Some(subject), _) => format!("{} [{}]", name, subject),
        (Some(name), None, None, Some(account_id)) => format!("{} [{}]", name, account_id),
        (None, Some(email), _, _) => email.to_string(),
        (None, None, Some(subject), _) => subject.to_string(),
        (None, None, None, Some(account_id)) => account_id.to_string(),
        _ => "unknown".to_string(),
    }
}

fn normalize_path(current: &str, required_suffix: &str) -> String {
    let trimmed = current.trim();
    if trimmed.is_empty() || trimmed == "/" {
        return required_suffix.to_string();
    }
    if trimmed.ends_with(required_suffix) {
        return trimmed.to_string();
    }
    format!(
        "{}/{}",
        trimmed.trim_end_matches('/'),
        required_suffix.trim_start_matches('/')
    )
}

fn env_trimmed(name: &str) -> Option<String> {
    std::env::var(name)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn trim_to_option(raw: &str) -> Option<String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

fn value_string(value: Option<&Value>, label: &str) -> LoomResult<String> {
    value
        .and_then(Value::as_str)
        .map(|raw| raw.trim().to_string())
        .filter(|raw| !raw.is_empty())
        .ok_or_else(|| format!("{label} must not be empty"))
}

fn value_string_or(value: Option<&Value>, fallback: &str) -> String {
    value
        .and_then(Value::as_str)
        .map(|raw| raw.trim().to_string())
        .filter(|raw| !raw.is_empty())
        .unwrap_or_else(|| fallback.to_string())
}

fn io_err(error: std::io::Error) -> String {
    error.to_string()
}

fn json_string(value: &str) -> String {
    serde_json::to_string(value).unwrap_or_else(|_| "\"\"".to_string())
}

fn json_option(value: Option<&str>) -> String {
    value.map(json_string).unwrap_or_else(|| "null".to_string())
}

#[cfg(test)]
mod tests {
    use std::sync::{Mutex, MutexGuard, OnceLock};
    use std::time::{SystemTime, UNIX_EPOCH};

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

    fn home_env_guard() -> MutexGuard<'static, ()> {
        static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        LOCK.get_or_init(|| Mutex::new(()))
            .lock()
            .expect("lock HOME env")
    }

    #[test]
    fn scaffold_writes_local_ollama_default_profile() {
        let root = temp_path("loom-provider-scaffold");
        let fake_home = root.join("fake-home");
        fs::create_dir_all(&fake_home).expect("create fake home");
        let _home_guard = home_env_guard();
        let previous_home = std::env::var("HOME").ok();
        std::env::set_var("HOME", &fake_home);
        let path = ensure_provider_profiles_scaffold(&root).expect("scaffold provider profiles");
        assert!(path.exists());
        let profiles = load_provider_profiles(Some(&root)).expect("load profiles");
        if let Some(home) = previous_home {
            std::env::set_var("HOME", home);
        } else {
            std::env::remove_var("HOME");
        }
        assert_eq!(profiles.default_profile_name, DEFAULT_LOCAL_PROFILE_NAME);
        assert_eq!(profiles.profiles.len(), 7);
        assert_eq!(profiles.profiles[0].kind, ProviderKind::LocalOllama);
        assert!(profiles
            .profiles
            .iter()
            .any(|profile| profile.name == "manager_frontier"
                && profile.kind == ProviderKind::OpenAiCodex));
        assert_eq!(profiles.routing.capabilities.len(), 1);
    }

    #[test]
    fn parser_supports_bearer_and_static_header_auth_modes() {
        let raw = r#"{
  "default_profile": "custom",
  "profiles": [
    {
      "name": "custom",
      "kind": "custom_endpoint",
      "base_url": "https://gateway.example.test",
      "model": "route-model",
      "auth": {
        "mode": "static_header_env",
        "header_name": "x-runtime-key",
        "env_var": "RUNTIME_KEY"
      }
    },
    {
      "name": "openai",
      "kind": "openai_compatible",
      "base_url": "https://api.openai.com/v1/chat/completions",
      "model": "gpt-5.4",
      "auth": {
        "mode": "bearer_env",
        "env_var": "OPENAI_API_KEY"
      }
    }
  ],
  "routing": {
    "capabilities": {
      "loom.llm.inference.v1": { "profile": "openai", "default_model": "gpt-5.4" }
    },
    "agents": {
      "agent_atlas": "custom"
    }
  }
}"#;
        let profiles = parse_provider_profiles_json(raw).expect("parse provider profiles");
        assert_eq!(profiles.profiles.len(), 2);
        assert_eq!(profiles.routing.capabilities.len(), 1);
        assert_eq!(profiles.routing.agents.len(), 1);
        assert_eq!(
            profiles.profiles[0].auth,
            ProviderAuthMode::StaticHeaderEnv {
                header_name: "x-runtime-key".to_string(),
                env_var: "RUNTIME_KEY".to_string(),
            }
        );
        assert_eq!(
            profiles.profiles[1].auth,
            ProviderAuthMode::BearerEnv {
                env_var: "OPENAI_API_KEY".to_string(),
            }
        );
    }

    #[test]
    fn resolved_route_uses_requested_model_override() {
        let root = temp_path("loom-provider-override");
        ensure_provider_profiles_scaffold(&root).expect("scaffold provider profiles");
        let route = resolve_llm_route(
            Some(&root),
            &ProviderRouteIntent::llm_inference("custom-alias"),
        )
        .expect("resolve route");
        assert_eq!(route.profile_name, DEFAULT_LOCAL_PROFILE_NAME);
        assert_eq!(route.model, "custom-alias");
        assert_eq!(route.endpoint_url.as_str(), DEFAULT_LOCAL_OLLAMA_ENDPOINT);
        assert_eq!(route.matched_rule, "capability:loom.llm.inference.v1");
    }

    #[test]
    fn explicit_profile_uses_profile_default_model_even_when_capability_has_default_model() {
        let root = temp_path("loom-provider-explicit-profile-model");
        let auth_path = root.join("codex-auth.json");
        fs::write(
            &auth_path,
            serde_json::to_string_pretty(&json!({
                "auth_mode": "chatgpt",
                "last_refresh": "2026-03-28T00:00:00Z",
                "tokens": {
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "account_id": "acct_test"
                }
            }))
            .expect("encode auth json"),
        )
        .expect("write auth json");
        let path = ensure_provider_profiles_scaffold(&root).expect("scaffold provider profiles");
        fs::write(
            &path,
            serde_json::to_string_pretty(&json!({
                "default_profile": "local_ollama",
                "profiles": [
                    {
                        "name": "local_ollama",
                        "kind": "local_ollama",
                        "base_url": DEFAULT_LOCAL_OLLAMA_ENDPOINT,
                        "model": DEFAULT_MODEL_ALIAS,
                        "auth": { "mode": "none" }
                    },
                    {
                        "name": "manager_frontier",
                        "kind": "openai_codex",
                        "base_url": DEFAULT_CODEX_BASE_URL,
                        "model": "gpt-5.4",
                        "auth": { "mode": "codex_auth_json", "path": auth_path.display().to_string() }
                    }
                ],
                "routing": {
                    "capabilities": {
                        "loom.llm.inference.v1": { "profile": "local_ollama", "default_model": "qwen2.5:7b" }
                    },
                    "agents": {}
                }
            }))
            .expect("encode provider routing"),
        )
        .expect("write provider profiles");
        let route = resolve_provider_route(
            Some(&root),
            &ProviderRouteIntent::for_capability("loom.llm.inference.v1", "")
                .with_preferred_profile_name("manager_frontier"),
        )
        .expect("resolve provider route");
        assert_eq!(route.profile_name, "manager_frontier");
        assert_eq!(route.model, "gpt-5.4");
        assert_eq!(route.matched_rule, "explicit_profile");
    }

    #[test]
    fn agent_route_overrides_capability_route_when_no_explicit_profile_is_set() {
        let root = temp_path("loom-provider-agent-route");
        let path = ensure_provider_profiles_scaffold(&root).expect("scaffold provider profiles");
        fs::write(
            &path,
            serde_json::to_string_pretty(&json!({
                "default_profile": "local_ollama",
                "profiles": [
                    {
                        "name": "local_ollama",
                        "kind": "local_ollama",
                        "base_url": DEFAULT_LOCAL_OLLAMA_ENDPOINT,
                        "model": DEFAULT_MODEL_ALIAS,
                        "auth": { "mode": "none" }
                    },
                    {
                        "name": "atlas_local",
                        "kind": "local_ollama",
                        "base_url": DEFAULT_LOCAL_OLLAMA_ENDPOINT,
                        "model": "atlas-special",
                        "auth": { "mode": "none" }
                    }
                ],
                "routing": {
                    "capabilities": {
                        "loom.llm.inference.v1": { "profile": "local_ollama", "default_model": "cap-default" }
                    },
                    "agents": {
                        "agent_atlas": { "profile": "atlas_local", "default_model": "atlas-route-model" }
                    }
                }
            }))
            .expect("encode provider routing"),
        )
        .expect("write provider profiles");
        let route = resolve_provider_route(
            Some(&root),
            &ProviderRouteIntent::for_capability("loom.llm.inference.v1", "")
                .with_agent_id("agent_atlas")
                .with_org_id("org_demo"),
        )
        .expect("resolve provider route");
        assert_eq!(route.profile_name, "atlas_local");
        assert_eq!(route.model, "atlas-route-model");
        assert_eq!(route.matched_rule, "agent:agent_atlas");
        assert_eq!(route.agent_id.as_deref(), Some("agent_atlas"));
        assert_eq!(route.org_id.as_deref(), Some("org_demo"));
    }

    #[test]
    fn parser_supports_codex_auth_json_mode() {
        let auth = parse_provider_auth(Some(&json!({
            "mode": "codex_auth_json",
            "path": "/tmp/codex-auth.json"
        })))
        .expect("parse codex auth mode");
        assert_eq!(
            auth,
            ProviderAuthMode::CodexAuthJson {
                path: Some("/tmp/codex-auth.json".to_string()),
            }
        );
    }

    #[test]
    fn auth_status_reports_codex_auth_json_ready() {
        let root = temp_path("loom-provider-auth-codex");
        let fake_home = root.join("fake-home");
        fs::create_dir_all(fake_home.join(".codex")).expect("create codex dir");
        fs::write(
            fake_home.join(".codex/auth.json"),
            serde_json::to_string_pretty(&json!({
                "auth_mode": "chatgpt",
                "last_refresh": "2026-03-28T00:00:00Z",
                "tokens": {
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "account_id": "acct_test"
                }
            }))
            .expect("encode auth json"),
        )
        .expect("write auth json");
        let _home_guard = home_env_guard();
        let previous_home = std::env::var("HOME").ok();
        std::env::set_var("HOME", &fake_home);
        let path = root.join(DEFAULT_PROVIDER_PROFILES_PATH);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).expect("create provider dir");
        }
        fs::write(
            &path,
            serde_json::to_string_pretty(&json!({
                "default_profile": "manager_frontier",
                "profiles": [
                    {
                        "name": "manager_frontier",
                        "kind": "openai_codex",
                        "base_url": DEFAULT_CODEX_BASE_URL,
                        "model": DEFAULT_CODEX_MODEL_ALIAS,
                        "auth": { "mode": "codex_auth_json" }
                    }
                ]
            }))
            .expect("encode provider json"),
        )
        .expect("write provider profiles");
        let status = provider_auth_status(Some(&root), Some("manager_frontier"))
            .expect("provider auth status");
        if let Some(home) = previous_home {
            std::env::set_var("HOME", home);
        } else {
            std::env::remove_var("HOME");
        }
        assert!(status.ready);
        assert_eq!(status.auth_mode, "codex_auth_json");
        assert!(status
            .credential_path
            .as_deref()
            .unwrap_or("")
            .ends_with(".codex/auth.json"));
    }

    #[test]
    fn agent_runtime_profile_fallback_resolves_frontier_profile() {
        let root = temp_path("loom-provider-agent-runtime-fallback");
        let fake_home = root.join("fake-home");
        fs::create_dir_all(fake_home.join(".codex")).expect("create codex dir");
        fs::write(
            fake_home.join(".codex/auth.json"),
            serde_json::to_string_pretty(&json!({
                "auth_mode": "chatgpt",
                "last_refresh": "2026-03-28T00:00:00Z",
                "tokens": {
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "account_id": "acct_test"
                }
            }))
            .expect("encode auth json"),
        )
        .expect("write auth json");
        let _home_guard = home_env_guard();
        let previous_home = std::env::var("HOME").ok();
        std::env::set_var("HOME", &fake_home);
        agent_runtime::ensure_agent_runtime_scaffold(&root).expect("scaffold agent runtime");
        ensure_provider_profiles_scaffold(&root).expect("scaffold provider profiles");
        let route = resolve_provider_route(
            Some(&root),
            &ProviderRouteIntent::llm_inference("")
                .with_agent_id("leviathann")
                .with_org_id("org_demo"),
        )
        .expect("resolve provider route");
        if let Some(home) = previous_home {
            std::env::set_var("HOME", home);
        } else {
            std::env::remove_var("HOME");
        }
        assert_eq!(route.profile_name, "manager_frontier");
        assert_eq!(route.profile_kind, ProviderKind::OpenAiCodex);
        assert_eq!(route.model, DEFAULT_CODEX_MODEL_ALIAS);
        assert_eq!(
            route.endpoint_url.as_str(),
            "https://chatgpt.com/backend-api/responses"
        );
        assert_eq!(route.matched_rule, "agent_runtime:leviathann");
    }

    #[test]
    fn configure_onboard_routes_prefers_dedicated_loom_auth_and_selected_model() {
        let root = temp_path("loom-provider-onboard-frontier");
        let fake_home = root.join("fake-home");
        fs::create_dir_all(fake_home.join(".meridian/auth/codex")).expect("create loom auth dir");
        fs::write(
            fake_home.join(".meridian/auth/codex/auth.json"),
            serde_json::to_string_pretty(&json!({
                "auth_mode": "chatgpt",
                "last_refresh": "2026-03-28T00:00:00Z",
                "tokens": {
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "account_id": "acct_loom"
                }
            }))
            .expect("encode auth json"),
        )
        .expect("write auth json");
        let _home_guard = home_env_guard();
        let previous_home = std::env::var("HOME").ok();
        std::env::set_var("HOME", &fake_home);
        ensure_provider_profiles_scaffold(&root).expect("scaffold provider profiles");
        let path =
            configure_onboard_provider_routes(&root, "frontier", Some("gpt-5.3-codex"), None)
                .expect("configure routes");
        assert!(path.exists());
        let profiles = load_provider_profiles(Some(&root)).expect("load provider profiles");
        let manager = profiles
            .profiles
            .iter()
            .find(|profile| profile.name == "manager_frontier")
            .expect("manager frontier profile");
        match &manager.auth {
            ProviderAuthMode::CodexAuthJson { path } => {
                assert!(path
                    .as_deref()
                    .unwrap_or("")
                    .ends_with(".meridian/auth/codex/auth.json"));
            }
            other => panic!("unexpected auth mode: {:?}", other),
        }
        assert_eq!(manager.default_model, "gpt-5.3-codex");
        let route = resolve_provider_route(
            Some(&root),
            &ProviderRouteIntent::llm_inference("").with_agent_id("leviathann"),
        )
        .expect("resolve provider route");
        if let Some(home) = previous_home {
            std::env::set_var("HOME", home);
        } else {
            std::env::remove_var("HOME");
        }
        assert_eq!(route.model, "gpt-5.3-codex");
    }

    #[test]
    fn configure_onboard_provider_profile_materializes_openai_compatible_route() {
        let root = temp_path("loom-provider-onboard-openai-compatible");
        ensure_provider_profiles_scaffold(&root).expect("scaffold provider profiles");
        let path = configure_onboard_provider_profile(
            &root,
            &OnboardProviderRouteConfig {
                profile_name: DEFAULT_OPENAI_PROFILE_NAME.to_string(),
                kind: ProviderKind::OpenAiCompatible,
                base_url: DEFAULT_OPENAI_ENDPOINT.to_string(),
                default_model: "gpt-5.4".to_string(),
                auth: ProviderAuthMode::BearerEnv {
                    env_var: "OPENAI_API_KEY".to_string(),
                },
                note: "seeded openai-compatible route".to_string(),
                make_default: true,
            },
        )
        .expect("configure provider profile");
        assert!(path.exists());
        let profiles = load_provider_profiles(Some(&root)).expect("load provider profiles");
        assert_eq!(profiles.default_profile_name, DEFAULT_OPENAI_PROFILE_NAME);
        let route = resolve_provider_route(
            Some(&root),
            &ProviderRouteIntent::llm_inference("").with_agent_id("leviathann"),
        )
        .expect_err("route should require OPENAI_API_KEY");
        assert!(route.contains("provider profile 'openai_default' is not ready"));
        assert!(route.contains("OPENAI_API_KEY"));
        let manager = profiles
            .profiles
            .iter()
            .find(|profile| profile.name == DEFAULT_OPENAI_PROFILE_NAME)
            .expect("openai profile");
        assert_eq!(manager.kind, ProviderKind::OpenAiCompatible);
        assert_eq!(manager.default_model, "gpt-5.4");
    }

    #[test]
    fn auth_status_blocks_loom_managed_auth_when_it_matches_shared_cli_account() {
        let root = temp_path("loom-provider-auth-dedicated-required");
        let fake_home = root.join("fake-home");
        fs::create_dir_all(fake_home.join(".codex")).expect("create shared codex dir");
        fs::create_dir_all(fake_home.join(".meridian/auth/codex")).expect("create loom codex dir");
        let auth_payload = serde_json::to_string_pretty(&json!({
            "auth_mode": "chatgpt",
            "last_refresh": "2026-03-28T00:00:00Z",
            "tokens": {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "account_id": "acct_shared"
            }
        }))
        .expect("encode auth json");
        fs::write(fake_home.join(".codex/auth.json"), &auth_payload)
            .expect("write shared auth json");
        fs::write(
            fake_home.join(".meridian/auth/codex/auth.json"),
            &auth_payload,
        )
        .expect("write loom auth json");
        let _home_guard = home_env_guard();
        let previous_home = std::env::var("HOME").ok();
        std::env::set_var("HOME", &fake_home);
        let path = root.join(DEFAULT_PROVIDER_PROFILES_PATH);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).expect("create provider dir");
        }
        fs::write(
            &path,
            serde_json::to_string_pretty(&json!({
                "default_profile": "manager_frontier",
                "profiles": [
                    {
                        "name": "manager_frontier",
                        "kind": "openai_codex",
                        "base_url": DEFAULT_CODEX_BASE_URL,
                        "model": DEFAULT_CODEX_MODEL_ALIAS,
                        "auth": { "mode": "codex_auth_json", "path": ".meridian/auth/codex/auth.json" }
                    }
                ]
            }))
            .expect("encode provider json"),
        )
        .expect("write provider profiles");
        let status = provider_auth_status(Some(&root), Some("manager_frontier"))
            .expect("provider auth status");
        let route_error = resolve_provider_route(
            Some(&root),
            &ProviderRouteIntent::llm_inference("").with_agent_id("leviathann"),
        )
        .expect_err("route should be blocked");
        if let Some(home) = previous_home {
            std::env::set_var("HOME", home);
        } else {
            std::env::remove_var("HOME");
        }
        assert!(!status.ready);
        assert!(status.detail.contains("shared CLI identity"));
        assert!(route_error.contains("provider profile 'manager_frontier' is not ready"));
    }

    #[test]
    fn auth_status_allows_dedicated_identity_when_account_id_matches_shared_cli_account() {
        let root = temp_path("loom-provider-auth-dedicated-identity");
        let fake_home = root.join("fake-home");
        fs::create_dir_all(fake_home.join(".codex")).expect("create shared codex dir");
        fs::create_dir_all(fake_home.join(".meridian/auth/codex")).expect("create loom codex dir");
        let shared_payload = serde_json::to_string_pretty(&json!({
            "auth_mode": "chatgpt",
            "last_refresh": "2026-03-28T00:00:00Z",
            "tokens": {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "account_id": "acct_shared",
                "id_token": "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiJ1c2VyX3NoYXJlZCIsImVtYWlsIjoic2hhcmVkQGV4YW1wbGUuY29tIiwibmFtZSI6IlNoYXJlZCBVc2VyIn0.signature"
            }
        }))
        .expect("encode shared auth json");
        let loom_payload = serde_json::to_string_pretty(&json!({
            "auth_mode": "chatgpt",
            "last_refresh": "2026-03-28T00:00:00Z",
            "tokens": {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "account_id": "acct_shared",
                "id_token": "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiJ1c2VyX2xvb20iLCJlbWFpbCI6Imxvb21AZXhhbXBsZS5jb20iLCJuYW1lIjoiTG9vbSBVc2VyIn0.signature"
            }
        }))
        .expect("encode loom auth json");
        fs::write(fake_home.join(".codex/auth.json"), &shared_payload)
            .expect("write shared auth json");
        fs::write(
            fake_home.join(".meridian/auth/codex/auth.json"),
            &loom_payload,
        )
        .expect("write loom auth json");
        let _home_guard = home_env_guard();
        let previous_home = std::env::var("HOME").ok();
        std::env::set_var("HOME", &fake_home);
        let path = root.join(DEFAULT_PROVIDER_PROFILES_PATH);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).expect("create provider dir");
        }
        fs::write(
            &path,
            serde_json::to_string_pretty(&json!({
                "default_profile": "manager_frontier",
                "profiles": [
                    {
                        "name": "manager_frontier",
                        "kind": "openai_codex",
                        "base_url": DEFAULT_CODEX_BASE_URL,
                        "model": DEFAULT_CODEX_MODEL_ALIAS,
                        "auth": { "mode": "codex_auth_json", "path": ".meridian/auth/codex/auth.json" }
                    }
                ]
            }))
            .expect("encode provider json"),
        )
        .expect("write provider profiles");
        let status = provider_auth_status(Some(&root), Some("manager_frontier"))
            .expect("provider auth status");
        let route = resolve_provider_route(
            Some(&root),
            &ProviderRouteIntent::llm_inference("").with_agent_id("leviathann"),
        )
        .expect("route should resolve");
        if let Some(home) = previous_home {
            std::env::set_var("HOME", home);
        } else {
            std::env::remove_var("HOME");
        }
        assert!(status.ready);
        assert_eq!(route.profile_name, "manager_frontier");
    }

    #[test]
    fn auth_status_reports_local_profile_ready_without_env() {
        let root = temp_path("loom-provider-auth-local");
        ensure_provider_profiles_scaffold(&root).expect("scaffold provider profiles");
        let status = provider_auth_status(Some(&root), None).expect("provider auth status");
        assert_eq!(status.profile_name, DEFAULT_LOCAL_PROFILE_NAME);
        assert!(status.ready);
        assert_eq!(status.auth_mode, "none");
    }

    #[test]
    fn auth_status_reports_missing_bearer_env() {
        let root = temp_path("loom-provider-auth-bearer");
        let env_var = "MERIDIAN_PROVIDER_TEST_TOKEN";
        std::env::remove_var(env_var);
        let path = root.join(DEFAULT_PROVIDER_PROFILES_PATH);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).expect("create provider profiles dir");
        }
        fs::write(
            &path,
            serde_json::to_string_pretty(&json!({
                "default_profile": "remote",
                "profiles": [
                    {
                        "name": "remote",
                        "kind": "openai_compatible",
                        "base_url": "https://api.example.test/v1/chat/completions",
                        "model": "gpt-test",
                        "auth": {
                            "mode": "bearer_env",
                            "env_var": env_var
                        }
                    }
                ]
            }))
            .expect("render provider json"),
        )
        .expect("write provider profiles");
        let status =
            provider_auth_status(Some(&root), Some("remote")).expect("provider auth status");
        assert_eq!(status.profile_name, "remote");
        assert!(!status.ready);
        assert_eq!(status.env_var.as_deref(), Some(env_var));
        assert_eq!(status.auth_mode, "bearer_env");
    }
}
