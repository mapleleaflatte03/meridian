/// Store-level Wasm resource limits.
///
/// Defines the configuration layer that will be consumed by the wasmtime
/// `StoreLimitsBuilder` once the runtime wiring is connected. These structures
/// are pure configuration — no wasmtime dependency required.
/// Hard ceiling for max_memory_bytes validation (4 GiB).
const MAX_MEMORY_CEILING: u64 = 4 * 1024 * 1024 * 1024;

/// Hard ceiling for max_table_elements validation.
const MAX_TABLE_ELEMENTS_CEILING: u32 = 10_000_000;

/// Hard ceiling for max_instances validation.
const MAX_INSTANCES_CEILING: u32 = 1_000;

/// Hard ceiling for max_tables validation.
const MAX_TABLES_CEILING: u32 = 1_000;

/// Hard ceiling for max_memories validation.
const MAX_MEMORIES_CEILING: u32 = 1_000;

/// Hard ceiling for fuel_limit validation.
const MAX_FUEL_CEILING: u64 = 1_000_000_000;

/// Resource limits for a single Wasm store.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WasmStoreLimits {
    /// Maximum linear memory in bytes.
    pub max_memory_bytes: u64,
    /// Maximum number of table elements.
    pub max_table_elements: u32,
    /// Maximum number of instances.
    pub max_instances: u32,
    /// Maximum number of tables.
    pub max_tables: u32,
    /// Maximum number of memories.
    pub max_memories: u32,
    /// Optional fuel limit for metered execution.
    pub fuel_limit: Option<u64>,
}

/// Returns sensible default limits: 64 MB memory, 10 000 table elements,
/// 10 instances, 10 tables, 10 memories, 1 000 000 fuel.
pub fn default_limits() -> WasmStoreLimits {
    WasmStoreLimits {
        max_memory_bytes: 64 * 1024 * 1024, // 64 MB
        max_table_elements: 10_000,
        max_instances: 10,
        max_tables: 10,
        max_memories: 10,
        fuel_limit: Some(1_000_000),
    }
}

/// Parse `WasmStoreLimits` from a minimal TOML-style string.
///
/// Expected keys (one per line, order-independent):
///   max_memory_bytes = <u64>
///   max_table_elements = <u32>
///   max_instances = <u32>
///   max_tables = <u32>
///   max_memories = <u32>
///   fuel_limit = <u64>         (omit or set to "none" for None)
///
/// Lines starting with `#` or `[` are ignored.
/// Missing keys fall back to the default value.
pub fn from_toml(value: &str) -> Result<WasmStoreLimits, String> {
    let mut limits = default_limits();

    for (line_no, raw_line) in value.lines().enumerate() {
        let line = raw_line.trim();
        if line.is_empty() || line.starts_with('#') || line.starts_with('[') {
            continue;
        }
        let parts: Vec<&str> = line.splitn(2, '=').collect();
        if parts.len() != 2 {
            return Err(format!(
                "line {}: expected key = value, got: {}",
                line_no + 1,
                line
            ));
        }
        let key = parts[0].trim();
        let val = parts[1].trim().trim_matches('"');

        match key {
            "max_memory_bytes" => {
                limits.max_memory_bytes = val
                    .parse::<u64>()
                    .map_err(|e| format!("line {}: bad max_memory_bytes: {}", line_no + 1, e))?;
            }
            "max_table_elements" => {
                limits.max_table_elements = val
                    .parse::<u32>()
                    .map_err(|e| format!("line {}: bad max_table_elements: {}", line_no + 1, e))?;
            }
            "max_instances" => {
                limits.max_instances = val
                    .parse::<u32>()
                    .map_err(|e| format!("line {}: bad max_instances: {}", line_no + 1, e))?;
            }
            "max_tables" => {
                limits.max_tables = val
                    .parse::<u32>()
                    .map_err(|e| format!("line {}: bad max_tables: {}", line_no + 1, e))?;
            }
            "max_memories" => {
                limits.max_memories = val
                    .parse::<u32>()
                    .map_err(|e| format!("line {}: bad max_memories: {}", line_no + 1, e))?;
            }
            "fuel_limit" => {
                if val == "none" || val.is_empty() {
                    limits.fuel_limit = None;
                } else {
                    limits.fuel_limit = Some(
                        val.parse::<u64>()
                            .map_err(|e| format!("line {}: bad fuel_limit: {}", line_no + 1, e))?,
                    );
                }
            }
            _ => {
                // Silently skip unknown keys to allow forward compatibility.
            }
        }
    }

    Ok(limits)
}

/// Render limits as a human-readable terminal string.
pub fn render_limits_human(limits: &WasmStoreLimits) -> String {
    let mem_mb = limits.max_memory_bytes as f64 / (1024.0 * 1024.0);
    let fuel_display = match limits.fuel_limit {
        Some(f) => format!("{}", f),
        None => "unlimited".to_string(),
    };
    format!(
        "Wasm Store Limits\n\
         -----------------\n\
         Memory        : {:.1} MB ({} bytes)\n\
         Table elements: {}\n\
         Instances     : {}\n\
         Tables        : {}\n\
         Memories      : {}\n\
         Fuel          : {}",
        mem_mb,
        limits.max_memory_bytes,
        limits.max_table_elements,
        limits.max_instances,
        limits.max_tables,
        limits.max_memories,
        fuel_display,
    )
}

/// Render limits as a JSON string (no external crate).
pub fn render_limits_json(limits: &WasmStoreLimits) -> String {
    let fuel_json = match limits.fuel_limit {
        Some(f) => format!("{}", f),
        None => "null".to_string(),
    };
    format!(
        "{{\
\"max_memory_bytes\":{},\
\"max_table_elements\":{},\
\"max_instances\":{},\
\"max_tables\":{},\
\"max_memories\":{},\
\"fuel_limit\":{}\
}}",
        limits.max_memory_bytes,
        limits.max_table_elements,
        limits.max_instances,
        limits.max_tables,
        limits.max_memories,
        fuel_json,
    )
}

/// Validate limits against sanity bounds.
///
/// Returns `Ok(())` when all limits are sane, or `Err(reasons)` listing every
/// violation found.
pub fn validate_limits(limits: &WasmStoreLimits) -> Result<(), Vec<String>> {
    let mut errors: Vec<String> = Vec::new();

    if limits.max_memory_bytes == 0 {
        errors.push("max_memory_bytes must be > 0".to_string());
    }
    if limits.max_memory_bytes > MAX_MEMORY_CEILING {
        errors.push(format!(
            "max_memory_bytes {} exceeds ceiling {}",
            limits.max_memory_bytes, MAX_MEMORY_CEILING
        ));
    }

    if limits.max_table_elements == 0 {
        errors.push("max_table_elements must be > 0".to_string());
    }
    if limits.max_table_elements > MAX_TABLE_ELEMENTS_CEILING {
        errors.push(format!(
            "max_table_elements {} exceeds ceiling {}",
            limits.max_table_elements, MAX_TABLE_ELEMENTS_CEILING
        ));
    }

    if limits.max_instances == 0 {
        errors.push("max_instances must be > 0".to_string());
    }
    if limits.max_instances > MAX_INSTANCES_CEILING {
        errors.push(format!(
            "max_instances {} exceeds ceiling {}",
            limits.max_instances, MAX_INSTANCES_CEILING
        ));
    }

    if limits.max_tables == 0 {
        errors.push("max_tables must be > 0".to_string());
    }
    if limits.max_tables > MAX_TABLES_CEILING {
        errors.push(format!(
            "max_tables {} exceeds ceiling {}",
            limits.max_tables, MAX_TABLES_CEILING
        ));
    }

    if limits.max_memories == 0 {
        errors.push("max_memories must be > 0".to_string());
    }
    if limits.max_memories > MAX_MEMORIES_CEILING {
        errors.push(format!(
            "max_memories {} exceeds ceiling {}",
            limits.max_memories, MAX_MEMORIES_CEILING
        ));
    }

    if let Some(fuel) = limits.fuel_limit {
        if fuel == 0 {
            errors.push("fuel_limit when set must be > 0".to_string());
        }
        if fuel > MAX_FUEL_CEILING {
            errors.push(format!(
                "fuel_limit {} exceeds ceiling {}",
                fuel, MAX_FUEL_CEILING
            ));
        }
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

    #[test]
    fn test_default_limits_are_valid() {
        let limits = default_limits();
        assert!(validate_limits(&limits).is_ok());
    }

    #[test]
    fn test_default_limits_values() {
        let limits = default_limits();
        assert_eq!(limits.max_memory_bytes, 64 * 1024 * 1024);
        assert_eq!(limits.max_table_elements, 10_000);
        assert_eq!(limits.max_instances, 10);
        assert_eq!(limits.max_tables, 10);
        assert_eq!(limits.max_memories, 10);
        assert_eq!(limits.fuel_limit, Some(1_000_000));
    }

    #[test]
    fn test_from_toml_full() {
        let toml = "\
max_memory_bytes = 134217728\n\
max_table_elements = 20000\n\
max_instances = 5\n\
max_tables = 8\n\
max_memories = 4\n\
fuel_limit = 5000000\n";
        let limits = from_toml(toml).unwrap();
        assert_eq!(limits.max_memory_bytes, 134_217_728);
        assert_eq!(limits.max_table_elements, 20_000);
        assert_eq!(limits.max_instances, 5);
        assert_eq!(limits.max_tables, 8);
        assert_eq!(limits.max_memories, 4);
        assert_eq!(limits.fuel_limit, Some(5_000_000));
    }

    #[test]
    fn test_from_toml_partial_defaults() {
        let toml = "max_memory_bytes = 33554432\n";
        let limits = from_toml(toml).unwrap();
        assert_eq!(limits.max_memory_bytes, 33_554_432);
        // Everything else should be default.
        assert_eq!(limits.max_table_elements, 10_000);
        assert_eq!(limits.fuel_limit, Some(1_000_000));
    }

    #[test]
    fn test_from_toml_fuel_none() {
        let toml = "fuel_limit = none\n";
        let limits = from_toml(toml).unwrap();
        assert_eq!(limits.fuel_limit, None);
    }

    #[test]
    fn test_from_toml_comments_and_sections_ignored() {
        let toml = "\
# This is a comment\n\
[wasm]\n\
max_memory_bytes = 16777216\n";
        let limits = from_toml(toml).unwrap();
        assert_eq!(limits.max_memory_bytes, 16_777_216);
    }

    #[test]
    fn test_from_toml_bad_value() {
        let toml = "max_memory_bytes = not_a_number\n";
        assert!(from_toml(toml).is_err());
    }

    #[test]
    fn test_validate_zero_memory() {
        let mut limits = default_limits();
        limits.max_memory_bytes = 0;
        let errs = validate_limits(&limits).unwrap_err();
        assert!(errs
            .iter()
            .any(|e| e.contains("max_memory_bytes must be > 0")));
    }

    #[test]
    fn test_validate_excessive_memory() {
        let mut limits = default_limits();
        limits.max_memory_bytes = MAX_MEMORY_CEILING + 1;
        let errs = validate_limits(&limits).unwrap_err();
        assert!(errs.iter().any(|e| e.contains("exceeds ceiling")));
    }

    #[test]
    fn test_validate_zero_fuel() {
        let mut limits = default_limits();
        limits.fuel_limit = Some(0);
        let errs = validate_limits(&limits).unwrap_err();
        assert!(errs
            .iter()
            .any(|e| e.contains("fuel_limit when set must be > 0")));
    }

    #[test]
    fn test_validate_none_fuel_ok() {
        let mut limits = default_limits();
        limits.fuel_limit = None;
        assert!(validate_limits(&limits).is_ok());
    }

    #[test]
    fn test_validate_multiple_errors() {
        let limits = WasmStoreLimits {
            max_memory_bytes: 0,
            max_table_elements: 0,
            max_instances: 0,
            max_tables: 0,
            max_memories: 0,
            fuel_limit: Some(0),
        };
        let errs = validate_limits(&limits).unwrap_err();
        assert!(errs.len() >= 6);
    }

    #[test]
    fn test_render_human() {
        let limits = default_limits();
        let out = render_limits_human(&limits);
        assert!(out.contains("64.0 MB"));
        assert!(out.contains("10000"));
        assert!(out.contains("1000000"));
    }

    #[test]
    fn test_render_human_unlimited_fuel() {
        let mut limits = default_limits();
        limits.fuel_limit = None;
        let out = render_limits_human(&limits);
        assert!(out.contains("unlimited"));
    }

    #[test]
    fn test_render_json() {
        let limits = default_limits();
        let json = render_limits_json(&limits);
        assert!(json.contains("\"max_memory_bytes\":67108864"));
        assert!(json.contains("\"fuel_limit\":1000000"));
    }

    #[test]
    fn test_render_json_null_fuel() {
        let mut limits = default_limits();
        limits.fuel_limit = None;
        let json = render_limits_json(&limits);
        assert!(json.contains("\"fuel_limit\":null"));
    }

    #[test]
    fn test_from_toml_unknown_keys_ignored() {
        let toml = "\
max_memory_bytes = 67108864\n\
unknown_future_key = 42\n";
        let limits = from_toml(toml).unwrap();
        assert_eq!(limits.max_memory_bytes, 67_108_864);
    }

    #[test]
    fn test_roundtrip_json_contains_all_fields() {
        let limits = WasmStoreLimits {
            max_memory_bytes: 128 * 1024 * 1024,
            max_table_elements: 50_000,
            max_instances: 20,
            max_tables: 15,
            max_memories: 8,
            fuel_limit: Some(2_000_000),
        };
        let json = render_limits_json(&limits);
        assert!(json.contains("\"max_memory_bytes\":134217728"));
        assert!(json.contains("\"max_table_elements\":50000"));
        assert!(json.contains("\"max_instances\":20"));
        assert!(json.contains("\"max_tables\":15"));
        assert!(json.contains("\"max_memories\":8"));
        assert!(json.contains("\"fuel_limit\":2000000"));
    }

    #[test]
    fn test_validate_excessive_instances() {
        let mut limits = default_limits();
        limits.max_instances = MAX_INSTANCES_CEILING + 1;
        let errs = validate_limits(&limits).unwrap_err();
        assert!(errs
            .iter()
            .any(|e| e.contains("max_instances") && e.contains("exceeds ceiling")));
    }
}
