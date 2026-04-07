//! Capability shims for legacy tools.
//!
//! Wraps legacy tool specifications into governance-compatible capability
//! shims that carry cost class, isolation tier, and capability-world metadata.

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/// Specification of a legacy tool that needs to be wrapped.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LegacyToolSpec {
    pub name: String,
    pub version: Option<String>,
    pub input_schema: String,
    pub output_schema: String,
}

/// A governance-compatible capability shim wrapping a legacy tool.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapabilityShim {
    pub tool_name: String,
    pub shim_version: String,
    pub capability_world: String,
    pub cost_class: String,
    pub isolation_tier: String,
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/// Generate a governance-compatible capability shim from a legacy tool spec.
///
/// The shim inherits the tool name, derives a version string, and assigns
/// default governance metadata (capability world, cost class, isolation tier)
/// based on the tool's characteristics.
pub fn generate_shim(spec: &LegacyToolSpec) -> CapabilityShim {
    let tool_version = spec.version.as_deref().unwrap_or("0.0.0");

    let shim_version = format!("shim-{}", tool_version);

    // Derive cost class from output schema heuristics
    let cost_class =
        if spec.output_schema.contains("stream") || spec.output_schema.contains("continuous") {
            "metered".to_string()
        } else if spec.input_schema.contains("large") || spec.input_schema.contains("batch") {
            "batch".to_string()
        } else {
            "per_call".to_string()
        };

    // Derive isolation tier from input schema heuristics
    let isolation_tier = if spec.input_schema.contains("exec")
        || spec.input_schema.contains("shell")
        || spec.input_schema.contains("command")
    {
        "sandboxed".to_string()
    } else if spec.input_schema.contains("network") || spec.input_schema.contains("http") {
        "network_isolated".to_string()
    } else {
        "shared".to_string()
    };

    CapabilityShim {
        tool_name: spec.name.clone(),
        shim_version,
        capability_world: "legacy_v0".to_string(),
        cost_class,
        isolation_tier,
    }
}

/// Render the capability shim as a human-readable terminal string.
pub fn render_shim_human(shim: &CapabilityShim) -> String {
    format!(
        "Meridian Loom // CAPABILITY SHIM\n\
         =================================\n\
         tool_name:         {}\n\
         shim_version:      {}\n\
         capability_world:  {}\n\
         cost_class:        {}\n\
         isolation_tier:    {}\n",
        shim.tool_name,
        shim.shim_version,
        shim.capability_world,
        shim.cost_class,
        shim.isolation_tier,
    )
}

/// Render the capability shim as a JSON string.
pub fn render_shim_json(shim: &CapabilityShim) -> String {
    format!(
        "{{\n  \"tool_name\": {:?},\n  \"shim_version\": {:?},\n  \"capability_world\": {:?},\n  \"cost_class\": {:?},\n  \"isolation_tier\": {:?}\n}}\n",
        shim.tool_name,
        shim.shim_version,
        shim.capability_world,
        shim.cost_class,
        shim.isolation_tier,
    )
}

/// Validate a capability shim.  Returns Ok(()) if valid, or Err with a list
/// of validation errors.
pub fn validate_shim(shim: &CapabilityShim) -> Result<(), Vec<String>> {
    let mut errors = Vec::new();

    if shim.tool_name.is_empty() {
        errors.push("tool_name is empty".to_string());
    }

    if shim.shim_version.is_empty() {
        errors.push("shim_version is empty".to_string());
    }

    if shim.capability_world.is_empty() {
        errors.push("capability_world is empty".to_string());
    }

    let valid_cost_classes = ["per_call", "metered", "batch", "free"];
    if !valid_cost_classes.contains(&shim.cost_class.as_str()) {
        errors.push(format!(
            "invalid cost_class '{}' (expected one of: {})",
            shim.cost_class,
            valid_cost_classes.join(", ")
        ));
    }

    let valid_isolation_tiers = ["shared", "network_isolated", "sandboxed", "air_gapped"];
    if !valid_isolation_tiers.contains(&shim.isolation_tier.as_str()) {
        errors.push(format!(
            "invalid isolation_tier '{}' (expected one of: {})",
            shim.isolation_tier,
            valid_isolation_tiers.join(", ")
        ));
    }

    if errors.is_empty() {
        Ok(())
    } else {
        Err(errors)
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn basic_spec() -> LegacyToolSpec {
        LegacyToolSpec {
            name: "web_search".to_string(),
            version: Some("1.2.0".to_string()),
            input_schema: r#"{"query": "string"}"#.to_string(),
            output_schema: r#"{"results": "array"}"#.to_string(),
        }
    }

    #[test]
    fn generate_shim_basic_tool() {
        let spec = basic_spec();
        let shim = generate_shim(&spec);
        assert_eq!(shim.tool_name, "web_search");
        assert_eq!(shim.shim_version, "shim-1.2.0");
        assert_eq!(shim.capability_world, "legacy_v0");
        assert_eq!(shim.cost_class, "per_call");
        assert_eq!(shim.isolation_tier, "shared");
    }

    #[test]
    fn generate_shim_no_version() {
        let spec = LegacyToolSpec {
            name: "calculator".to_string(),
            version: None,
            input_schema: r#"{"expression": "string"}"#.to_string(),
            output_schema: r#"{"result": "number"}"#.to_string(),
        };
        let shim = generate_shim(&spec);
        assert_eq!(shim.shim_version, "shim-0.0.0");
    }

    #[test]
    fn generate_shim_streaming_output() {
        let spec = LegacyToolSpec {
            name: "log_tail".to_string(),
            version: Some("2.0.0".to_string()),
            input_schema: r#"{"path": "string"}"#.to_string(),
            output_schema: r#"{"stream": "lines"}"#.to_string(),
        };
        let shim = generate_shim(&spec);
        assert_eq!(shim.cost_class, "metered");
    }

    #[test]
    fn generate_shim_exec_input_gets_sandboxed() {
        let spec = LegacyToolSpec {
            name: "shell_runner".to_string(),
            version: Some("0.1.0".to_string()),
            input_schema: r#"{"command": "string", "exec": true}"#.to_string(),
            output_schema: r#"{"stdout": "string"}"#.to_string(),
        };
        let shim = generate_shim(&spec);
        assert_eq!(shim.isolation_tier, "sandboxed");
    }

    #[test]
    fn generate_shim_network_input_gets_network_isolated() {
        let spec = LegacyToolSpec {
            name: "http_fetch".to_string(),
            version: Some("1.0.0".to_string()),
            input_schema: r#"{"url": "string", "network": true}"#.to_string(),
            output_schema: r#"{"body": "string"}"#.to_string(),
        };
        let shim = generate_shim(&spec);
        assert_eq!(shim.isolation_tier, "network_isolated");
    }

    #[test]
    fn generate_shim_batch_input() {
        let spec = LegacyToolSpec {
            name: "bulk_processor".to_string(),
            version: Some("3.0.0".to_string()),
            input_schema: r#"{"batch": "array", "large": true}"#.to_string(),
            output_schema: r#"{"results": "array"}"#.to_string(),
        };
        let shim = generate_shim(&spec);
        assert_eq!(shim.cost_class, "batch");
    }

    #[test]
    fn validate_shim_accepts_valid() {
        let shim = generate_shim(&basic_spec());
        assert!(validate_shim(&shim).is_ok());
    }

    #[test]
    fn validate_shim_accepts_all_valid_cost_classes() {
        let mut shim = generate_shim(&basic_spec());
        let valid_cost_classes = ["per_call", "metered", "batch", "free"];
        for cost_class in valid_cost_classes {
            shim.cost_class = cost_class.to_string();
            assert!(
                validate_shim(&shim).is_ok(),
                "failed on valid cost_class: {}",
                cost_class
            );
        }
    }

    #[test]
    fn validate_shim_rejects_empty_tool_name() {
        let shim = CapabilityShim {
            tool_name: "".to_string(),
            shim_version: "shim-1.0.0".to_string(),
            capability_world: "legacy_v0".to_string(),
            cost_class: "per_call".to_string(),
            isolation_tier: "shared".to_string(),
        };
        let errors = validate_shim(&shim).expect_err("should fail");
        assert!(errors.iter().any(|e| e.contains("tool_name")));
    }

    #[test]
    fn validate_shim_rejects_invalid_cost_class() {
        let shim = CapabilityShim {
            tool_name: "test_tool".to_string(),
            shim_version: "shim-1.0.0".to_string(),
            capability_world: "legacy_v0".to_string(),
            cost_class: "unlimited".to_string(),
            isolation_tier: "shared".to_string(),
        };
        let errors = validate_shim(&shim).expect_err("should fail");
        assert!(errors.iter().any(|e| e.contains("cost_class")));
    }

    #[test]
    fn validate_shim_rejects_invalid_isolation_tier() {
        let shim = CapabilityShim {
            tool_name: "test_tool".to_string(),
            shim_version: "shim-1.0.0".to_string(),
            capability_world: "legacy_v0".to_string(),
            cost_class: "per_call".to_string(),
            isolation_tier: "open_access".to_string(),
        };
        let errors = validate_shim(&shim).expect_err("should fail");
        assert!(errors.iter().any(|e| e.contains("isolation_tier")));
    }

    #[test]
    fn validate_shim_collects_multiple_errors() {
        let shim = CapabilityShim {
            tool_name: "".to_string(),
            shim_version: "".to_string(),
            capability_world: "".to_string(),
            cost_class: "invalid".to_string(),
            isolation_tier: "invalid".to_string(),
        };
        let errors = validate_shim(&shim).expect_err("should fail");
        assert!(errors.len() >= 4);
    }

    #[test]
    fn render_human_contains_tool_name() {
        let shim = generate_shim(&basic_spec());
        let output = render_shim_human(&shim);
        assert!(output.contains("web_search"));
        assert!(output.contains("CAPABILITY SHIM"));
        assert!(output.contains("legacy_v0"));
    }

    #[test]
    fn render_json_contains_all_fields() {
        let shim = generate_shim(&basic_spec());
        let output = render_shim_json(&shim);
        assert!(output.contains("\"web_search\""));
        assert!(output.contains("\"shim-1.2.0\""));
        assert!(output.contains("\"legacy_v0\""));
        assert!(output.contains("\"per_call\""));
        assert!(output.contains("\"shared\""));
    }
}
