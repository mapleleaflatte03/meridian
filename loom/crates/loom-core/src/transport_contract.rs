//! Frontier transport contract — formalizes how Loom reaches external inference providers.
//!
//! This module owns the transport-level truth: which protocols Loom speaks,
//! what authentication shapes it supports, and how transport decisions map to
//! the constitutional contract's cost_attribution and audit_emission requirements.

use std::fmt;

type LoomResult<T> = Result<T, String>;

/// Transport protocol families that Loom recognizes.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TransportProtocol {
    /// OpenAI-compatible REST (chat/completions)
    OpenAiRest,
    /// Codex OAuth session (chatgpt.com backend-api)
    CodexSession,
    /// Local Ollama REST
    OllamaLocal,
    /// MCP tool-use protocol
    Mcp,
    /// Agent-to-Agent protocol (A2A)
    A2a,
    /// Custom HTTP endpoint
    CustomHttp,
}

impl TransportProtocol {
    pub fn label(&self) -> &'static str {
        match self {
            Self::OpenAiRest => "openai_rest",
            Self::CodexSession => "codex_session",
            Self::OllamaLocal => "ollama_local",
            Self::Mcp => "mcp",
            Self::A2a => "a2a",
            Self::CustomHttp => "custom_http",
        }
    }

    pub fn from_label(s: &str) -> Option<Self> {
        match s.trim().to_ascii_lowercase().as_str() {
            "openai_rest" | "openai" => Some(Self::OpenAiRest),
            "codex_session" | "codex" => Some(Self::CodexSession),
            "ollama_local" | "ollama" => Some(Self::OllamaLocal),
            "mcp" => Some(Self::Mcp),
            "a2a" => Some(Self::A2a),
            "custom_http" | "custom" => Some(Self::CustomHttp),
            _ => None,
        }
    }

    /// Whether this protocol transits data outside the local host boundary.
    pub fn is_remote(&self) -> bool {
        match self {
            Self::OllamaLocal => false,
            Self::Mcp => false, // MCP can be local stdio
            _ => true,
        }
    }

    /// Whether this protocol requires credential material.
    pub fn requires_auth(&self) -> bool {
        match self {
            Self::OllamaLocal => false,
            Self::Mcp => false,
            _ => true,
        }
    }
}

impl fmt::Display for TransportProtocol {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.label())
    }
}

/// Authentication shape for a transport connection.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TransportAuth {
    None,
    BearerToken { source: String },
    OAuthSession { credential_path: String },
    StaticHeader { header: String, source: String },
    ApiKey { source: String },
}

impl TransportAuth {
    pub fn label(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::BearerToken { .. } => "bearer_token",
            Self::OAuthSession { .. } => "oauth_session",
            Self::StaticHeader { .. } => "static_header",
            Self::ApiKey { .. } => "api_key",
        }
    }

    pub fn has_credential(&self) -> bool {
        !matches!(self, Self::None)
    }
}

/// A fully resolved transport binding for a single provider route.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TransportBinding {
    pub protocol: TransportProtocol,
    pub endpoint_url: String,
    pub auth: TransportAuth,
    pub model: String,
    pub profile_name: String,
    pub cost_attribution_class: &'static str,
    pub audit_required: bool,
}

impl TransportBinding {
    /// Derive a transport binding from a provider route's characteristics.
    pub fn from_provider_route(
        profile_name: &str,
        kind_label: &str,
        endpoint_url: &str,
        model: &str,
        auth_mode_label: &str,
        auth_detail: &str,
    ) -> LoomResult<Self> {
        let protocol = match kind_label {
            "local_ollama" => TransportProtocol::OllamaLocal,
            "openai_compatible" => TransportProtocol::OpenAiRest,
            "openai_codex" => TransportProtocol::CodexSession,
            "custom_endpoint" => TransportProtocol::CustomHttp,
            other => return Err(format!("unknown provider kind for transport: {}", other)),
        };

        let auth = match auth_mode_label {
            "none" => TransportAuth::None,
            "bearer_env" => TransportAuth::BearerToken {
                source: auth_detail.to_string(),
            },
            "codex_auth_json" => TransportAuth::OAuthSession {
                credential_path: auth_detail.to_string(),
            },
            "static_header_env" => TransportAuth::StaticHeader {
                header: "Authorization".to_string(),
                source: auth_detail.to_string(),
            },
            _ => TransportAuth::None,
        };

        let cost_attribution_class = if protocol.is_remote() {
            "external_inference"
        } else {
            "local_compute"
        };
        let audit_required = protocol.is_remote();

        Ok(Self {
            protocol,
            endpoint_url: endpoint_url.to_string(),
            auth,
            model: model.to_string(),
            profile_name: profile_name.to_string(),
            cost_attribution_class,
            audit_required,
        })
    }

    /// Summary for doctor/diagnostic output.
    pub fn diagnostic_summary(&self) -> String {
        format!(
            "protocol={} endpoint={} auth={} model={} cost_class={} audit={}",
            self.protocol.label(),
            self.endpoint_url,
            self.auth.label(),
            self.model,
            self.cost_attribution_class,
            self.audit_required,
        )
    }
}

/// Contract-level transport constraints that the constitutional contract can enforce.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TransportPolicy {
    /// Maximum allowed protocols (empty = allow all)
    pub allowed_protocols: Vec<TransportProtocol>,
    /// Whether remote transports require audit emission
    pub remote_audit_required: bool,
    /// Whether cost attribution must be present for external transports
    pub external_cost_attribution_required: bool,
}

impl Default for TransportPolicy {
    fn default() -> Self {
        Self {
            allowed_protocols: Vec::new(),
            remote_audit_required: true,
            external_cost_attribution_required: true,
        }
    }
}

impl TransportPolicy {
    /// Check a binding against this policy.
    pub fn check_binding(&self, binding: &TransportBinding) -> LoomResult<()> {
        if !self.allowed_protocols.is_empty() && !self.allowed_protocols.contains(&binding.protocol)
        {
            return Err(format!(
                "transport protocol {} not in allowed list",
                binding.protocol.label()
            ));
        }
        if self.remote_audit_required && binding.protocol.is_remote() && !binding.audit_required {
            return Err("remote transport requires audit emission".to_string());
        }
        if self.external_cost_attribution_required
            && binding.cost_attribution_class == "external_inference"
            && binding.model.is_empty()
        {
            return Err("external inference requires model for cost attribution".to_string());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_protocol_labels() {
        assert_eq!(TransportProtocol::OpenAiRest.label(), "openai_rest");
        assert_eq!(TransportProtocol::OllamaLocal.label(), "ollama_local");
        assert!(TransportProtocol::OpenAiRest.is_remote());
        assert!(!TransportProtocol::OllamaLocal.is_remote());
    }

    #[test]
    fn test_protocol_from_label() {
        assert_eq!(
            TransportProtocol::from_label("codex"),
            Some(TransportProtocol::CodexSession)
        );
        assert_eq!(TransportProtocol::from_label("unknown"), None);
    }

    #[test]
    fn test_transport_binding_from_provider() {
        let binding = TransportBinding::from_provider_route(
            "local_ollama",
            "local_ollama",
            "http://127.0.0.1:11434/v1/chat/completions",
            "qwen2.5:7b",
            "none",
            "",
        )
        .unwrap();
        assert_eq!(binding.protocol, TransportProtocol::OllamaLocal);
        assert_eq!(binding.cost_attribution_class, "local_compute");
        assert!(!binding.audit_required);
    }

    #[test]
    fn test_transport_binding_frontier() {
        let binding = TransportBinding::from_provider_route(
            "manager_frontier",
            "openai_codex",
            "https://chatgpt.com/backend-api",
            "gpt-5.4",
            "codex_auth_json",
            "~/.meridian/auth/codex/auth.json",
        )
        .unwrap();
        assert_eq!(binding.protocol, TransportProtocol::CodexSession);
        assert_eq!(binding.cost_attribution_class, "external_inference");
        assert!(binding.audit_required);
    }

    #[test]
    fn test_policy_check_allowed() {
        let policy = TransportPolicy {
            allowed_protocols: vec![TransportProtocol::OllamaLocal],
            remote_audit_required: true,
            external_cost_attribution_required: true,
        };
        let binding = TransportBinding::from_provider_route(
            "local_ollama",
            "local_ollama",
            "http://127.0.0.1:11434/v1/chat/completions",
            "qwen2.5:7b",
            "none",
            "",
        )
        .unwrap();
        assert!(policy.check_binding(&binding).is_ok());
    }

    #[test]
    fn test_policy_check_disallowed() {
        let policy = TransportPolicy {
            allowed_protocols: vec![TransportProtocol::OllamaLocal],
            remote_audit_required: true,
            external_cost_attribution_required: true,
        };
        let binding = TransportBinding::from_provider_route(
            "manager_frontier",
            "openai_codex",
            "https://chatgpt.com/backend-api",
            "gpt-5.4",
            "codex_auth_json",
            "",
        )
        .unwrap();
        assert!(policy.check_binding(&binding).is_err());
    }
}
