use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use crate::{Config, LoomResult};

const CAPABILITY_REGISTRY_VERSION: &str = "loom.capabilities.v0";
const DEFAULT_CAPABILITY_DIR: &str = "capabilities";
const CUSTOM_PYTHON_WORKER_TEMPLATE: &str = r#"#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone


def main():
    parser = argparse.ArgumentParser(description="Meridian Loom capability worker")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    capability = payload.get("capability", {})
    envelope = payload.get("envelope", {})
    raw_payload = payload.get("payload_json", "")
    parsed_payload = {}
    if raw_payload:
        try:
            parsed_payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            parsed_payload = {"raw_payload": raw_payload}

    result = {
        "status": "completed",
        "worker_kind": capability.get("worker_kind", "python_capability_worker"),
        "capability_name": capability.get("name", "unknown"),
        "completed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "agent_id": envelope.get("agent_id", ""),
        "org_id": envelope.get("org_id", ""),
        "action_type": envelope.get("action_type", ""),
        "resource": envelope.get("resource", ""),
        "summary": parsed_payload.get("message", f"capability {capability.get('name', 'unknown')} executed"),
        "payload": parsed_payload,
    }

    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")

    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
"#;
const FORGE_TEMPLATE_ECHO_JSON: &str = "echo_json_v0";
const FORGE_TEMPLATE_ARTIFACT_INSPECT: &str = "artifact_inspect_v0";
const FORGE_TEMPLATE_URL_BUNDLE: &str = "url_bundle_v0";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapabilityDescriptor {
    pub name: String,
    pub description: String,
    pub action_type: String,
    pub resource: String,
    pub worker_kind: String,
    pub worker_entry: String,
    pub wasm_module: String,
    pub payload_mode: String,
    pub source_kind: String,
    pub source_path: String,
    pub source_manifest: String,
    pub adapter_kind: String,
    pub import_provenance: String,
    pub verification_status: String,
    pub last_verified_at: String,
    pub last_verification_job_id: String,
    pub last_verification_execution_id: String,
    pub verification_note: String,
    pub promotion_state: String,
    pub promoted_at: String,
    pub enabled: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapabilityRegistry {
    pub version: String,
    pub capabilities: Vec<CapabilityDescriptor>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapabilityScaffoldRequest {
    pub name: String,
    pub description: String,
    pub action_type: String,
    pub resource: String,
    pub worker_kind: String,
    pub worker_entry: String,
    pub wasm_module: String,
    pub payload_mode: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapabilityScaffoldResult {
    pub manifest_path: PathBuf,
    pub worker_path: Option<PathBuf>,
    pub capability: CapabilityDescriptor,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapabilityForgeRequest {
    pub name: String,
    pub description: String,
    pub template: String,
    pub gap_class: String,
    pub goal: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapabilityForgeResult {
    pub manifest_path: PathBuf,
    pub worker_path: PathBuf,
    pub capability: CapabilityDescriptor,
    pub template: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapabilityImportResult {
    pub manifest_path: PathBuf,
    pub worker_path: PathBuf,
    pub capability: CapabilityDescriptor,
    pub detected_signature: String,
    pub source_manifest: PathBuf,
    pub skill_shape: String,
    pub skill_root: PathBuf,
    pub skill_script: PathBuf,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LegacyV1PluginImportResult {
    pub manifest_path: PathBuf,
    pub plugin_root: PathBuf,
    pub plugin_id: String,
    pub config_schema_json: String,
    pub skills_roots: Vec<PathBuf>,
    pub imported_skills: Vec<LegacyV1PluginSkillImportResult>,
    pub unsupported_items: Vec<LegacyV1PluginUnsupportedItem>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LegacyV1PluginSkillImportResult {
    pub manifest_path: PathBuf,
    pub worker_path: PathBuf,
    pub capability: CapabilityDescriptor,
    pub skill_root: PathBuf,
    pub skill_doc: PathBuf,
    pub normalized_metadata: LegacyV1PluginNormalizedMetadata,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LegacyV1PluginNormalizedMetadata {
    pub plugin_id: String,
    pub plugin_root: String,
    pub skills_root: String,
    pub skill_root: String,
    pub skill_name: String,
    pub skill_description: String,
    pub capability_name: String,
    pub source_kind: String,
    pub source_manifest: String,
    pub import_provenance: String,
    pub import_scope: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LegacyV1PluginUnsupportedItem {
    pub path: String,
    pub reason: String,
    pub detail: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapabilityStateUpdateResult {
    pub manifest_path: PathBuf,
    pub capability: CapabilityDescriptor,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapabilityGapRequest {
    pub request_id: String,
    pub requested_via: String,
    pub capability_name: String,
    pub gap_class: String,
    pub goal: String,
    pub proposed_capability_name: String,
    pub agent_id: String,
    pub org_id: String,
    pub kernel_path: String,
    pub action_type: String,
    pub resource: String,
    pub payload_json: String,
    pub run_id: String,
    pub session_id: String,
    pub original_request_json: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapabilityGapRecord {
    pub gap_id: String,
    pub request_id: String,
    pub requested_at: String,
    pub updated_at: String,
    pub requested_via: String,
    pub capability_name: String,
    pub gap_class: String,
    pub goal: String,
    pub proposed_capability_name: String,
    pub agent_id: String,
    pub org_id: String,
    pub kernel_path: String,
    pub action_type: String,
    pub resource: String,
    pub payload_json: String,
    pub run_id: String,
    pub session_id: String,
    pub original_request_json: String,
    pub forge_status: String,
    pub verification_status: String,
    pub promotion_status: String,
    pub verified_at: String,
    pub verification_note: String,
    pub promoted_at: String,
    pub promotion_note: String,
    pub candidate_manifest_path: String,
    pub verification_job_id: String,
    pub verification_execution_id: String,
    pub last_note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapabilityGapUpdateResult {
    pub gap_path: PathBuf,
    pub gap: CapabilityGapRecord,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct ClawfamilyImportSpec {
    skill_shape: String,
    skill_name: String,
    skill_description: String,
    source_manifest: PathBuf,
    skill_script: PathBuf,
    adapter_kind: String,
    action_type: String,
    payload_mode: String,
    source_kind: String,
    import_provenance: String,
}

#[derive(Clone, Debug)]
struct LegacyV1PluginManifestSpec {
    manifest_path: PathBuf,
    plugin_id: String,
    config_schema_json: String,
    skill_roots: Vec<LegacyV1PluginSkillRootSpec>,
    unsupported_items: Vec<LegacyV1PluginUnsupportedItem>,
}

#[derive(Clone, Debug)]
struct LegacyV1PluginSkillRootSpec {
    raw_path: String,
    config_gated: bool,
    gate_detail: String,
}

pub fn default_capabilities(config: &Config) -> Vec<CapabilityDescriptor> {
    vec![
        CapabilityDescriptor {
            name: "loom.echo.v1".to_string(),
            description: "Echo a small JSON payload through the default Python capability worker.".to_string(),
            action_type: "respond".to_string(),
            resource: "capability:loom.echo.v1".to_string(),
            worker_kind: "python".to_string(),
            worker_entry: format!("{}/loom_runtime_worker.py", config.python_path),
            wasm_module: String::new(),
            payload_mode: "json".to_string(),
            source_kind: "loom_builtin".to_string(),
            source_path: "builtin:loom.echo.v1".to_string(),
            source_manifest: String::new(),
            adapter_kind: "loom_worker_contract_v0".to_string(),
            import_provenance: "loom_builtin_contract_v0".to_string(),
            verification_status: "builtin".to_string(),
            last_verified_at: String::new(),
            last_verification_job_id: String::new(),
            last_verification_execution_id: String::new(),
            verification_note: "built-in capability".to_string(),
            promotion_state: "builtin".to_string(),
            promoted_at: String::new(),
            enabled: true,
        },
        CapabilityDescriptor {
            name: "loom.wasm.minimal.v1".to_string(),
            description: "Run the built-in minimal Wasm guest through the local Wasmtime lane.".to_string(),
            action_type: "compute".to_string(),
            resource: "capability:loom.wasm.minimal.v1".to_string(),
            worker_kind: "wasm".to_string(),
            worker_entry: String::new(),
            wasm_module: "builtin:minimal".to_string(),
            payload_mode: "none".to_string(),
            source_kind: "loom_builtin".to_string(),
            source_path: "builtin:loom.wasm.minimal.v1".to_string(),
            source_manifest: String::new(),
            adapter_kind: "loom_wasm_guest_v0".to_string(),
            import_provenance: "loom_builtin_contract_v0".to_string(),
            verification_status: "builtin".to_string(),
            last_verified_at: String::new(),
            last_verification_job_id: String::new(),
            last_verification_execution_id: String::new(),
            verification_note: "built-in capability".to_string(),
            promotion_state: "builtin".to_string(),
            promoted_at: String::new(),
            enabled: true,
        },
        CapabilityDescriptor {
            name: "loom.browser.navigate.v1".to_string(),
            description: "Run the built-in bounded browser navigation Wasm guest through the local Wasmtime lane.".to_string(),
            action_type: "browse".to_string(),
            resource: "capability:loom.browser.navigate.v1".to_string(),
            worker_kind: "wasm".to_string(),
            worker_entry: String::new(),
            wasm_module: "builtin:browser.navigate".to_string(),
            payload_mode: "json".to_string(),
            source_kind: "loom_builtin".to_string(),
            source_path: "builtin:loom.browser.navigate.v1".to_string(),
            source_manifest: String::new(),
            adapter_kind: "loom_wasm_browser_guest_v0".to_string(),
            import_provenance: "loom_builtin_contract_v0".to_string(),
            verification_status: "builtin".to_string(),
            last_verified_at: String::new(),
            last_verification_job_id: String::new(),
            last_verification_execution_id: String::new(),
            verification_note: "built-in bounded web/Wasm capability".to_string(),
            promotion_state: "builtin".to_string(),
            promoted_at: String::new(),
            enabled: true,
        },
        CapabilityDescriptor {
            name: "loom.terminal.exec.v1".to_string(),
            description: "Run the built-in bounded terminal execution Wasm guest through the local Wasmtime lane.".to_string(),
            action_type: "execute".to_string(),
            resource: "capability:loom.terminal.exec.v1".to_string(),
            worker_kind: "wasm".to_string(),
            worker_entry: String::new(),
            wasm_module: "builtin:terminal.exec".to_string(),
            payload_mode: "json".to_string(),
            source_kind: "loom_builtin".to_string(),
            source_path: "builtin:loom.terminal.exec.v1".to_string(),
            source_manifest: String::new(),
            adapter_kind: "loom_wasm_terminal_guest_v0".to_string(),
            import_provenance: "loom_builtin_contract_v0".to_string(),
            verification_status: "builtin".to_string(),
            last_verified_at: String::new(),
            last_verification_job_id: String::new(),
            last_verification_execution_id: String::new(),
            verification_note: "built-in bounded terminal/Wasm capability".to_string(),
            promotion_state: "builtin".to_string(),
            promoted_at: String::new(),
            enabled: true,
        },
        CapabilityDescriptor {
            name: "loom.heartbeat.schedule.v1".to_string(),
            description: "Run the built-in heartbeat scheduling Wasm guest through the local Wasmtime lane and persist a bounded receipt.".to_string(),
            action_type: "schedule".to_string(),
            resource: "capability:loom.heartbeat.schedule.v1".to_string(),
            worker_kind: "wasm".to_string(),
            worker_entry: String::new(),
            wasm_module: "builtin:heartbeat.schedule".to_string(),
            payload_mode: "json".to_string(),
            source_kind: "loom_builtin".to_string(),
            source_path: "builtin:loom.heartbeat.schedule.v1".to_string(),
            source_manifest: String::new(),
            adapter_kind: "loom_wasm_heartbeat_guest_v0".to_string(),
            import_provenance: "loom_builtin_contract_v0".to_string(),
            verification_status: "builtin".to_string(),
            last_verified_at: String::new(),
            last_verification_job_id: String::new(),
            last_verification_execution_id: String::new(),
            verification_note: "built-in heartbeat/Wasm capability with local receipt logging".to_string(),
            promotion_state: "builtin".to_string(),
            promoted_at: String::new(),
            enabled: true,
        },
        CapabilityDescriptor {
            name: "loom.system.info.v1".to_string(),
            description: "Run the built-in bounded system diagnostics Wasm guest through the local Wasmtime lane.".to_string(),
            action_type: "inspect".to_string(),
            resource: "capability:loom.system.info.v1".to_string(),
            worker_kind: "wasm".to_string(),
            worker_entry: String::new(),
            wasm_module: "builtin:system.info".to_string(),
            payload_mode: "json".to_string(),
            source_kind: "loom_builtin".to_string(),
            source_path: "builtin:loom.system.info.v1".to_string(),
            source_manifest: String::new(),
            adapter_kind: "loom_wasm_system_info_guest_v0".to_string(),
            import_provenance: "loom_builtin_contract_v0".to_string(),
            verification_status: "builtin".to_string(),
            last_verified_at: String::new(),
            last_verification_job_id: String::new(),
            last_verification_execution_id: String::new(),
            verification_note: "built-in bounded host diagnostics/Wasm capability with PoGE-audited host calls".to_string(),
            promotion_state: "builtin".to_string(),
            promoted_at: String::new(),
            enabled: true,
        },
        CapabilityDescriptor {
            name: "loom.fs.read.v1".to_string(),
            description: "Run the built-in sandboxed filesystem read Wasm guest through the local Wasmtime lane.".to_string(),
            action_type: "read".to_string(),
            resource: "capability:loom.fs.read.v1".to_string(),
            worker_kind: "wasm".to_string(),
            worker_entry: String::new(),
            wasm_module: "builtin:fs.read".to_string(),
            payload_mode: "json".to_string(),
            source_kind: "loom_builtin".to_string(),
            source_path: "builtin:loom.fs.read.v1".to_string(),
            source_manifest: String::new(),
            adapter_kind: "loom_wasm_fs_read_guest_v0".to_string(),
            import_provenance: "loom_builtin_contract_v0".to_string(),
            verification_status: "builtin".to_string(),
            last_verified_at: String::new(),
            last_verification_job_id: String::new(),
            last_verification_execution_id: String::new(),
            verification_note: "built-in sandboxed fs read/Wasm capability".to_string(),
            promotion_state: "builtin".to_string(),
            promoted_at: String::new(),
            enabled: true,
        },
        CapabilityDescriptor {
            name: "loom.fs.write.v1".to_string(),
            description: "Run the built-in sandboxed filesystem write Wasm guest through the local Wasmtime lane.".to_string(),
            action_type: "write".to_string(),
            resource: "capability:loom.fs.write.v1".to_string(),
            worker_kind: "wasm".to_string(),
            worker_entry: String::new(),
            wasm_module: "builtin:fs.write".to_string(),
            payload_mode: "json".to_string(),
            source_kind: "loom_builtin".to_string(),
            source_path: "builtin:loom.fs.write.v1".to_string(),
            source_manifest: String::new(),
            adapter_kind: "loom_wasm_fs_write_guest_v0".to_string(),
            import_provenance: "loom_builtin_contract_v0".to_string(),
            verification_status: "builtin".to_string(),
            last_verified_at: String::new(),
            last_verification_job_id: String::new(),
            last_verification_execution_id: String::new(),
            verification_note: "built-in sandboxed fs write/Wasm capability".to_string(),
            promotion_state: "builtin".to_string(),
            promoted_at: String::new(),
            enabled: true,
        },
        CapabilityDescriptor {
            name: "loom.llm.inference.v1".to_string(),
            description: "Run the built-in native LLM inference Wasm guest through the local Wasmtime lane.".to_string(),
            action_type: "infer".to_string(),
            resource: "capability:loom.llm.inference.v1".to_string(),
            worker_kind: "wasm".to_string(),
            worker_entry: String::new(),
            wasm_module: "builtin:llm.inference".to_string(),
            payload_mode: "json".to_string(),
            source_kind: "loom_builtin".to_string(),
            source_path: "builtin:loom.llm.inference.v1".to_string(),
            source_manifest: String::new(),
            adapter_kind: "loom_wasm_llm_guest_v0".to_string(),
            import_provenance: "loom_builtin_contract_v0".to_string(),
            verification_status: "builtin".to_string(),
            last_verified_at: String::new(),
            last_verification_job_id: String::new(),
            last_verification_execution_id: String::new(),
            verification_note: "built-in native LLM inference/Wasm capability".to_string(),
            promotion_state: "builtin".to_string(),
            promoted_at: String::new(),
            enabled: true,
        },
        CapabilityDescriptor {
            name: "loom.kv.get.v1".to_string(),
            description: "Run the built-in local KV memory read Wasm guest through the local Wasmtime lane.".to_string(),
            action_type: "memory_get".to_string(),
            resource: "capability:loom.kv.get.v1".to_string(),
            worker_kind: "wasm".to_string(),
            worker_entry: String::new(),
            wasm_module: "builtin:kv.get".to_string(),
            payload_mode: "json".to_string(),
            source_kind: "loom_builtin".to_string(),
            source_path: "builtin:loom.kv.get.v1".to_string(),
            source_manifest: String::new(),
            adapter_kind: "loom_wasm_kv_get_guest_v0".to_string(),
            import_provenance: "loom_builtin_contract_v0".to_string(),
            verification_status: "builtin".to_string(),
            last_verified_at: String::new(),
            last_verification_job_id: String::new(),
            last_verification_execution_id: String::new(),
            verification_note: "built-in local KV get/Wasm capability".to_string(),
            promotion_state: "builtin".to_string(),
            promoted_at: String::new(),
            enabled: true,
        },
        CapabilityDescriptor {
            name: "loom.kv.set.v1".to_string(),
            description: "Run the built-in local KV memory write Wasm guest through the local Wasmtime lane.".to_string(),
            action_type: "memory_set".to_string(),
            resource: "capability:loom.kv.set.v1".to_string(),
            worker_kind: "wasm".to_string(),
            worker_entry: String::new(),
            wasm_module: "builtin:kv.set".to_string(),
            payload_mode: "json".to_string(),
            source_kind: "loom_builtin".to_string(),
            source_path: "builtin:loom.kv.set.v1".to_string(),
            source_manifest: String::new(),
            adapter_kind: "loom_wasm_kv_set_guest_v0".to_string(),
            import_provenance: "loom_builtin_contract_v0".to_string(),
            verification_status: "builtin".to_string(),
            last_verified_at: String::new(),
            last_verification_job_id: String::new(),
            last_verification_execution_id: String::new(),
            verification_note: "built-in local KV set/Wasm capability".to_string(),
            promotion_state: "builtin".to_string(),
            promoted_at: String::new(),
            enabled: true,
        },
    ]
}

pub fn capability_registry_dir(root: &Path, config: &Config) -> PathBuf {
    root.join(&config.capabilities_dir)
}

pub fn capability_registry_path(root: &Path, config: &Config) -> PathBuf {
    capability_registry_dir(root, config).join("registry.json")
}

pub fn capability_custom_dir(root: &Path, config: &Config) -> PathBuf {
    capability_registry_dir(root, config).join("custom")
}

pub fn capability_gap_dir(root: &Path, config: &Config) -> PathBuf {
    capability_registry_dir(root, config).join("gaps")
}

pub fn ensure_capability_registry_scaffold(root: &Path, config: &Config) -> LoomResult<PathBuf> {
    let registry_dir = capability_registry_dir(root, config);
    let custom_dir = capability_custom_dir(root, config);
    let gap_dir = capability_gap_dir(root, config);
    fs::create_dir_all(&registry_dir).map_err(io_err)?;
    fs::create_dir_all(&custom_dir).map_err(io_err)?;
    fs::create_dir_all(&gap_dir).map_err(io_err)?;
    let registry_path = capability_registry_path(root, config);
    if !registry_path.exists() {
        let registry = CapabilityRegistry {
            version: CAPABILITY_REGISTRY_VERSION.to_string(),
            capabilities: default_capabilities(config),
        };
        save_capability_registry(&registry, &registry_path)?;
    }
    Ok(registry_path)
}

pub fn load_capability_registry(root: &Path, config: &Config) -> LoomResult<CapabilityRegistry> {
    let registry_path = ensure_capability_registry_scaffold(root, config)?;
    let raw = fs::read_to_string(&registry_path).map_err(io_err)?;
    let mut registry = parse_capability_registry(&raw)?;
    let custom_dir = capability_custom_dir(root, config);
    if custom_dir.exists() {
        let mut custom_paths = fs::read_dir(&custom_dir)
            .map_err(io_err)?
            .filter_map(|entry| entry.ok().map(|item| item.path()))
            .filter(|path| path.extension().map(|ext| ext == "json").unwrap_or(false))
            .collect::<Vec<_>>();
        custom_paths.sort();
        for manifest in custom_paths {
            let raw = fs::read_to_string(&manifest).map_err(io_err)?;
            let descriptor = parse_capability_descriptor_json(&raw)?;
            upsert_capability(&mut registry.capabilities, descriptor);
        }
    }
    registry
        .capabilities
        .sort_by(|left, right| left.name.cmp(&right.name));
    Ok(registry)
}

pub fn find_capability_by_name(
    root: &Path,
    config: &Config,
    name: &str,
) -> LoomResult<Option<CapabilityDescriptor>> {
    let registry = load_capability_registry(root, config)?;
    Ok(registry
        .capabilities
        .into_iter()
        .find(|item| item.enabled && item.name == name))
}

pub fn resolve_capability_for_request(
    root: &Path,
    config: &Config,
    capability_name: Option<&str>,
    action_type: &str,
    resource: &str,
) -> LoomResult<Option<CapabilityDescriptor>> {
    let registry = load_capability_registry(root, config)?;
    if let Some(name) = capability_name.filter(|value| !value.trim().is_empty()) {
        return Ok(registry
            .capabilities
            .into_iter()
            .find(|item| item.enabled && item.name == name));
    }
    Ok(registry
        .capabilities
        .into_iter()
        .find(|item| item.enabled && item.action_type == action_type && item.resource == resource))
}

pub fn scaffold_capability(
    root: &Path,
    config: &Config,
    request: &CapabilityScaffoldRequest,
) -> LoomResult<CapabilityScaffoldResult> {
    if request.name.trim().is_empty() {
        return Err("capability name is required".to_string());
    }
    if request.action_type.trim().is_empty() {
        return Err("capability action_type is required".to_string());
    }
    if request.resource.trim().is_empty() {
        return Err("capability resource is required".to_string());
    }
    if !matches!(request.worker_kind.as_str(), "python" | "wasm") {
        return Err("worker_kind must be 'python' or 'wasm'".to_string());
    }

    ensure_capability_registry_scaffold(root, config)?;
    let manifest_path =
        capability_custom_dir(root, config).join(format!("{}.json", sanitize_name(&request.name)));
    let mut worker_path = None;
    let worker_entry = if request.worker_kind == "python" {
        let relative = if request.worker_entry.trim().is_empty() {
            format!("{}/{}.py", config.python_path, sanitize_name(&request.name))
        } else {
            request.worker_entry.clone()
        };
        let full_path = root.join(&relative);
        if !full_path.exists() {
            if let Some(parent) = full_path.parent() {
                fs::create_dir_all(parent).map_err(io_err)?;
            }
            fs::write(&full_path, CUSTOM_PYTHON_WORKER_TEMPLATE).map_err(io_err)?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                let mut permissions = fs::metadata(&full_path).map_err(io_err)?.permissions();
                permissions.set_mode(0o755);
                fs::set_permissions(&full_path, permissions).map_err(io_err)?;
            }
        }
        worker_path = Some(full_path);
        relative
    } else {
        String::new()
    };

    let capability = CapabilityDescriptor {
        name: request.name.trim().to_string(),
        description: request.description.trim().to_string(),
        action_type: request.action_type.trim().to_string(),
        resource: request.resource.trim().to_string(),
        worker_kind: request.worker_kind.trim().to_string(),
        worker_entry,
        wasm_module: request.wasm_module.trim().to_string(),
        payload_mode: if request.payload_mode.trim().is_empty() {
            "json".to_string()
        } else {
            request.payload_mode.trim().to_string()
        },
        source_kind: "loom_scaffold".to_string(),
        source_path: root.display().to_string(),
        source_manifest: String::new(),
        adapter_kind: if request.worker_kind == "wasm" {
            "loom_wasm_guest_v0".to_string()
        } else {
            "loom_worker_contract_v0".to_string()
        },
        import_provenance: "loom_scaffold_contract_v0".to_string(),
        verification_status: "unverified".to_string(),
        last_verified_at: String::new(),
        last_verification_job_id: String::new(),
        last_verification_execution_id: String::new(),
        verification_note: "candidate capability has not been verified yet".to_string(),
        promotion_state: "candidate".to_string(),
        promoted_at: String::new(),
        enabled: true,
    };
    fs::write(&manifest_path, descriptor_json(&capability)).map_err(io_err)?;
    Ok(CapabilityScaffoldResult {
        manifest_path,
        worker_path,
        capability,
    })
}

pub fn import_workspace_skill(
    root: &Path,
    config: &Config,
    skill_root: &Path,
    explicit_entrypoint: Option<&str>,
    capability_name_override: Option<&str>,
) -> LoomResult<CapabilityImportResult> {
    let skill_root = skill_root.canonicalize().map_err(io_err)?;
    let import_spec = load_clawfamily_import_spec(&skill_root, explicit_entrypoint)?;

    ensure_capability_registry_scaffold(root, config)?;
    let capability_name = capability_name_override
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| format!("loomskill.{}.v0", sanitize_name(&import_spec.skill_name)));
    let relative_worker_entry = format!(
        "{}/imported-{}.py",
        config.python_path,
        sanitize_name(&capability_name)
    );
    let worker_path = root.join(&relative_worker_entry);
    if let Some(parent) = worker_path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    fs::write(
        &worker_path,
        render_workspace_skill_wrapper(
            &capability_name,
            &import_spec.skill_name,
            &skill_root,
            &import_spec.skill_script,
            &import_spec.adapter_kind,
            &import_spec.source_kind,
        )?,
    )
    .map_err(io_err)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut permissions = fs::metadata(&worker_path).map_err(io_err)?.permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(&worker_path, permissions).map_err(io_err)?;
    }

    let capability = CapabilityDescriptor {
        name: capability_name.clone(),
        description: if import_spec.skill_description.is_empty() {
            format!("Imported from clawfamily skill {}", import_spec.skill_name)
        } else {
            import_spec.skill_description
        },
        action_type: import_spec.action_type,
        resource: format!("capability:{}", capability_name),
        worker_kind: "python".to_string(),
        worker_entry: relative_worker_entry,
        wasm_module: String::new(),
        payload_mode: import_spec.payload_mode,
        source_kind: import_spec.source_kind,
        source_path: skill_root.display().to_string(),
        source_manifest: import_spec.source_manifest.display().to_string(),
        adapter_kind: import_spec.adapter_kind.clone(),
        import_provenance: import_spec.import_provenance,
        verification_status: "unverified".to_string(),
        last_verified_at: String::new(),
        last_verification_job_id: String::new(),
        last_verification_execution_id: String::new(),
        verification_note: "imported clawfamily skill has not been verified by Loom yet"
            .to_string(),
        promotion_state: "candidate".to_string(),
        promoted_at: String::new(),
        enabled: true,
    };
    let manifest_path = capability_custom_dir(root, config)
        .join(format!("{}.json", sanitize_name(&capability_name)));
    fs::write(&manifest_path, descriptor_json(&capability)).map_err(io_err)?;
    Ok(CapabilityImportResult {
        manifest_path,
        worker_path,
        capability,
        detected_signature: import_spec.adapter_kind,
        source_manifest: import_spec.source_manifest,
        skill_shape: import_spec.skill_shape,
        skill_root,
        skill_script: import_spec.skill_script,
    })
}

pub fn import_legacy_v1_plugin_skill_subset(
    root: &Path,
    config: &Config,
    plugin_root: &Path,
) -> LoomResult<LegacyV1PluginImportResult> {
    let plugin_root = plugin_root.canonicalize().map_err(io_err)?;
    let plugin_spec = load_legacy_v1_plugin_manifest_spec(&plugin_root)?;
    ensure_capability_registry_scaffold(root, config)?;

    let mut unsupported_items = collect_legacy_v1_plugin_surface_unsupported_items(&plugin_root);
    unsupported_items.extend(plugin_spec.unsupported_items);

    let mut skills_roots = Vec::new();
    let mut imported_skills = Vec::new();

    if plugin_spec.skill_roots.is_empty() {
        unsupported_items.push(LegacyV1PluginUnsupportedItem {
            path: plugin_spec.manifest_path.display().to_string(),
            reason: "missing_skills_root".to_string(),
            detail: "legacy_v1.plugin.json does not declare any skills roots".to_string(),
        });
        return Ok(LegacyV1PluginImportResult {
            manifest_path: plugin_spec.manifest_path,
            plugin_root,
            plugin_id: plugin_spec.plugin_id,
            config_schema_json: plugin_spec.config_schema_json,
            skills_roots,
            imported_skills,
            unsupported_items,
        });
    }

    if plugin_spec.skill_roots.len() > 1 {
        unsupported_items.push(LegacyV1PluginUnsupportedItem {
            path: plugin_spec.manifest_path.display().to_string(),
            reason: "multiple_skill_roots".to_string(),
            detail: format!(
                "legacy_v1.plugin.json declares {} skills roots; this import mode supports only one",
                plugin_spec.skill_roots.len()
            ),
        });
        return Ok(LegacyV1PluginImportResult {
            manifest_path: plugin_spec.manifest_path,
            plugin_root,
            plugin_id: plugin_spec.plugin_id,
            config_schema_json: plugin_spec.config_schema_json,
            skills_roots,
            imported_skills,
            unsupported_items,
        });
    }

    let skill_root_spec = &plugin_spec.skill_roots[0];
    if skill_root_spec.config_gated {
        unsupported_items.push(LegacyV1PluginUnsupportedItem {
            path: plugin_spec.manifest_path.display().to_string(),
            reason: "config_gated_skills_not_supported".to_string(),
            detail: if skill_root_spec.gate_detail.is_empty() {
                format!(
                    "skills root {} is config-gated and this import mode does not support config-gated skills",
                    skill_root_spec.raw_path
                )
            } else {
                skill_root_spec.gate_detail.clone()
            },
        });
        return Ok(LegacyV1PluginImportResult {
            manifest_path: plugin_spec.manifest_path,
            plugin_root,
            plugin_id: plugin_spec.plugin_id,
            config_schema_json: plugin_spec.config_schema_json,
            skills_roots,
            imported_skills,
            unsupported_items,
        });
    }

    let resolved_skill_root =
        match resolve_legacy_v1_plugin_skill_root(&plugin_root, &skill_root_spec.raw_path) {
            Ok(path) => path,
            Err(item) => {
                unsupported_items.push(item);
                return Ok(LegacyV1PluginImportResult {
                    manifest_path: plugin_spec.manifest_path,
                    plugin_root,
                    plugin_id: plugin_spec.plugin_id,
                    config_schema_json: plugin_spec.config_schema_json,
                    skills_roots,
                    imported_skills,
                    unsupported_items,
                });
            }
        };
    if !resolved_skill_root.exists() {
        unsupported_items.push(LegacyV1PluginUnsupportedItem {
            path: resolved_skill_root.display().to_string(),
            reason: "missing_skills_root_path".to_string(),
            detail: format!(
                "declared skills root {} does not exist under {}",
                skill_root_spec.raw_path,
                plugin_root.display()
            ),
        });
        return Ok(LegacyV1PluginImportResult {
            manifest_path: plugin_spec.manifest_path,
            plugin_root,
            plugin_id: plugin_spec.plugin_id,
            config_schema_json: plugin_spec.config_schema_json,
            skills_roots,
            imported_skills,
            unsupported_items,
        });
    }
    if !resolved_skill_root.is_dir() {
        unsupported_items.push(LegacyV1PluginUnsupportedItem {
            path: resolved_skill_root.display().to_string(),
            reason: "skills_root_not_directory".to_string(),
            detail: format!(
                "declared skills root {} must resolve to a directory",
                skill_root_spec.raw_path
            ),
        });
        return Ok(LegacyV1PluginImportResult {
            manifest_path: plugin_spec.manifest_path,
            plugin_root,
            plugin_id: plugin_spec.plugin_id,
            config_schema_json: plugin_spec.config_schema_json,
            skills_roots,
            imported_skills,
            unsupported_items,
        });
    }

    skills_roots.push(resolved_skill_root.clone());
    let child_dirs = fs::read_dir(&resolved_skill_root).map_err(io_err)?;
    let mut discovered_skill_names = std::collections::BTreeSet::new();
    for entry in child_dirs {
        let entry = entry.map_err(io_err)?;
        let child_path = entry.path();
        if !child_path.is_dir() {
            continue;
        }
        let skill_doc = child_path.join("SKILL.md");
        if !skill_doc.exists() {
            continue;
        }
        let (skill_name, skill_description, _) =
            match parse_workspace_skill_front_matter(&skill_doc) {
                Ok(values) => values,
                Err(error) => {
                    unsupported_items.push(LegacyV1PluginUnsupportedItem {
                        path: skill_doc.display().to_string(),
                        reason: "invalid_skill_front_matter".to_string(),
                        detail: error,
                    });
                    continue;
                }
            };
        if skill_description.trim().is_empty() {
            unsupported_items.push(LegacyV1PluginUnsupportedItem {
                path: skill_doc.display().to_string(),
                reason: "missing_skill_description".to_string(),
                detail: "Legacy v1 plugin skills need SKILL.md front matter with both name and description".to_string(),
            });
            continue;
        }
        let capability_name =
            legacy_v1_plugin_skill_capability_name(&plugin_spec.plugin_id, &skill_name);
        if !discovered_skill_names.insert(capability_name.clone()) {
            unsupported_items.push(LegacyV1PluginUnsupportedItem {
                path: skill_doc.display().to_string(),
                reason: "duplicate_skill_name".to_string(),
                detail: format!(
                    "skill {} would materialize more than once under plugin {}",
                    skill_name, plugin_spec.plugin_id
                ),
            });
            continue;
        }

        let relative_worker_entry = format!(
            "{}/imported-{}.py",
            config.python_path,
            sanitize_name(&capability_name)
        );
        let worker_path = root.join(&relative_worker_entry);
        if let Some(parent) = worker_path.parent() {
            fs::create_dir_all(parent).map_err(io_err)?;
        }
        fs::write(&worker_path, CUSTOM_PYTHON_WORKER_TEMPLATE).map_err(io_err)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mut permissions = fs::metadata(&worker_path).map_err(io_err)?.permissions();
            permissions.set_mode(0o755);
            fs::set_permissions(&worker_path, permissions).map_err(io_err)?;
        }

        let manifest_path = capability_custom_dir(root, config)
            .join(format!("{}.json", sanitize_name(&capability_name)));
        let capability = CapabilityDescriptor {
            name: capability_name.clone(),
            description: skill_description.clone(),
            action_type: "skill_exec".to_string(),
            resource: format!("capability:{}", capability_name),
            worker_kind: "python".to_string(),
            worker_entry: relative_worker_entry,
            wasm_module: String::new(),
            payload_mode: "json".to_string(),
            source_kind: "legacy_v1_plugin_skill".to_string(),
            source_path: child_path.display().to_string(),
            source_manifest: plugin_spec.manifest_path.display().to_string(),
            adapter_kind: "legacy_v1_plugin_skill_contract_v0".to_string(),
            import_provenance: "legacy_v1_plugin_contract_v0/immediate_child_skill_dir".to_string(),
            verification_status: "unverified".to_string(),
            last_verified_at: String::new(),
            last_verification_job_id: String::new(),
            last_verification_execution_id: String::new(),
            verification_note:
                "imported legacy v1 plugin skill subset has not been verified by Loom yet"
                    .to_string(),
            promotion_state: "candidate".to_string(),
            promoted_at: String::new(),
            enabled: true,
        };
        fs::write(&manifest_path, descriptor_json(&capability)).map_err(io_err)?;
        imported_skills.push(LegacyV1PluginSkillImportResult {
            manifest_path,
            worker_path,
            capability: capability.clone(),
            skill_root: child_path.clone(),
            skill_doc: skill_doc.clone(),
            normalized_metadata: LegacyV1PluginNormalizedMetadata {
                plugin_id: plugin_spec.plugin_id.clone(),
                plugin_root: plugin_root.display().to_string(),
                skills_root: resolved_skill_root.display().to_string(),
                skill_root: child_path.display().to_string(),
                skill_name,
                skill_description,
                capability_name,
                source_kind: "legacy_v1_plugin_skill".to_string(),
                source_manifest: plugin_spec.manifest_path.display().to_string(),
                import_provenance: "legacy_v1_plugin_contract_v0/immediate_child_skill_dir"
                    .to_string(),
                import_scope: "immediate_child_skill_dir".to_string(),
            },
        });
    }

    Ok(LegacyV1PluginImportResult {
        manifest_path: plugin_spec.manifest_path,
        plugin_root,
        plugin_id: plugin_spec.plugin_id,
        config_schema_json: plugin_spec.config_schema_json,
        skills_roots,
        imported_skills,
        unsupported_items,
    })
}

pub fn forge_capability(
    root: &Path,
    config: &Config,
    request: &CapabilityForgeRequest,
) -> LoomResult<CapabilityForgeResult> {
    if request.name.trim().is_empty() {
        return Err("capability name is required".to_string());
    }
    let template = if request.template.trim().is_empty() {
        template_for_gap_class(&request.gap_class)?
    } else {
        normalize_forge_template(&request.template)?
    };
    ensure_capability_registry_scaffold(root, config)?;

    let worker_relative = format!(
        "{}/forged-{}.py",
        config.python_path,
        sanitize_name(&request.name)
    );
    let worker_path = root.join(&worker_relative);
    if let Some(parent) = worker_path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    fs::write(
        &worker_path,
        render_forged_capability_worker(&request.name, template)?,
    )
    .map_err(io_err)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut permissions = fs::metadata(&worker_path).map_err(io_err)?.permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(&worker_path, permissions).map_err(io_err)?;
    }

    let (action_type, description, adapter_kind) = match template {
        FORGE_TEMPLATE_ECHO_JSON => (
            "respond".to_string(),
            if request.description.trim().is_empty() {
                default_forge_description(template, &request.goal)
            } else {
                request.description.trim().to_string()
            },
            "loom_forge_template/echo_json_v0".to_string(),
        ),
        FORGE_TEMPLATE_ARTIFACT_INSPECT => (
            "artifact_inspect".to_string(),
            if request.description.trim().is_empty() {
                default_forge_description(template, &request.goal)
            } else {
                request.description.trim().to_string()
            },
            "loom_forge_template/artifact_inspect_v0".to_string(),
        ),
        FORGE_TEMPLATE_URL_BUNDLE => (
            "url_bundle".to_string(),
            if request.description.trim().is_empty() {
                default_forge_description(template, &request.goal)
            } else {
                request.description.trim().to_string()
            },
            "loom_forge_template/url_bundle_v0".to_string(),
        ),
        _ => unreachable!(),
    };

    let capability = CapabilityDescriptor {
        name: request.name.trim().to_string(),
        description,
        action_type,
        resource: format!("capability:{}", request.name.trim()),
        worker_kind: "python".to_string(),
        worker_entry: worker_relative,
        wasm_module: String::new(),
        payload_mode: "json".to_string(),
        source_kind: "loom_forge_candidate".to_string(),
        source_path: format!("forge:{}", template),
        source_manifest: String::new(),
        adapter_kind,
        import_provenance: "loom_forge_contract_v0".to_string(),
        verification_status: "unverified".to_string(),
        last_verified_at: String::new(),
        last_verification_job_id: String::new(),
        last_verification_execution_id: String::new(),
        verification_note: format!(
            "forged candidate from template {} has not been verified yet",
            template
        ),
        promotion_state: "candidate".to_string(),
        promoted_at: String::new(),
        enabled: true,
    };
    let manifest_path =
        capability_custom_dir(root, config).join(format!("{}.json", sanitize_name(&request.name)));
    fs::write(&manifest_path, descriptor_json(&capability)).map_err(io_err)?;
    Ok(CapabilityForgeResult {
        manifest_path,
        worker_path,
        capability,
        template: template.to_string(),
    })
}

pub fn capability_interpreter(capability: &CapabilityDescriptor) -> &'static str {
    match capability.worker_kind.as_str() {
        "python" => "python3",
        "wasm" => "wasmtime",
        _ => "runtime-managed",
    }
}

pub fn capability_binary_surface(capability: &CapabilityDescriptor) -> String {
    if !capability.worker_entry.is_empty() {
        capability.worker_entry.clone()
    } else if !capability.wasm_module.is_empty() {
        capability.wasm_module.clone()
    } else {
        "(none)".to_string()
    }
}

pub fn capability_isolation_expectation(capability: &CapabilityDescriptor) -> &'static str {
    match capability.worker_kind.as_str() {
        "wasm" => "local Wasmtime guest sandbox",
        "python" if capability.source_kind == "legacy_v1_workspace_skill" => {
            "host python process, workspace-skill wrapper"
        }
        "python" if capability.source_kind == "clawfamily_skill_bundle" => {
            "host python process, bundle wrapper"
        }
        "python" if capability.source_kind == "loom_forge_candidate" => {
            "host python process, forged wrapper"
        }
        "python" => "host python process",
        _ => "runtime-managed",
    }
}

pub fn render_capability_readiness_human(
    request_action: &str,
    request_resource: &str,
    capability: Option<&CapabilityDescriptor>,
    resolution_note: Option<&str>,
) -> String {
    let note = resolution_note.unwrap_or_else(|| {
        if capability.is_some() {
            "matched enabled capability registry entry"
        } else {
            "no enabled capability matched the request"
        }
    });
    let capability_block = match capability {
        Some(capability) => render_capability_human(capability),
        None => String::from(
            "Meridian Loom // CAPABILITY\n============================\nname:              (none)\n",
        ),
    };
    format!(
        "Meridian Loom // CAPABILITY READINESS\n=====================================\nrequest:             {} / {}\nresolution:          {}\nresolution_note:     {}\n{}\n",
        request_action,
        request_resource,
        if capability.is_some() { "resolved" } else { "unresolved" },
        note,
        capability_block
    )
}

pub fn render_capability_readiness_json(
    request_action: &str,
    request_resource: &str,
    capability: Option<&CapabilityDescriptor>,
    resolution_note: Option<&str>,
) -> String {
    let note = resolution_note.unwrap_or_else(|| {
        if capability.is_some() {
            "matched enabled capability registry entry"
        } else {
            "no enabled capability matched the request"
        }
    });
    format!(
        "{}\n",
        json!({
            "request_action": request_action,
            "request_resource": request_resource,
            "resolution_status": if capability.is_some() { "resolved" } else { "unresolved" },
            "resolution_note": note,
            "capability": capability.map(descriptor_value),
        })
    )
}

pub fn render_capability_human(capability: &CapabilityDescriptor) -> String {
    format!(
        "Meridian Loom // CAPABILITY\n============================\nname:              {}\ndescription:       {}\naction_type:       {}\nresource:          {}\nworker_kind:       {}\ninterpreter:       {}\nworker_entry:      {}\nwasm_module:       {}\nbinary_surface:    {}\npayload_mode:      {}\nsource_kind:       {}\nsource_path:       {}\nsource_manifest:   {}\nadapter_kind:      {}\nimport_provenance: {}\nruntime_lane:      {}\ndependency:        {}\nenv_contract:      {}\nisolation:         {}\nverification:      {}\nverified_at:       {}\nverify_job:        {}\nverify_exec:       {}\nverify_note:       {}\npromotion:         {}\npromoted_at:       {}\nenabled:           {}\n",
        capability.name,
        if capability.description.is_empty() {
            "(none)"
        } else {
            &capability.description
        },
        capability.action_type,
        capability.resource,
        capability.worker_kind,
        capability_interpreter(capability),
        if capability.worker_entry.is_empty() {
            "(none)"
        } else {
            &capability.worker_entry
        },
        if capability.wasm_module.is_empty() {
            "(none)"
        } else {
            &capability.wasm_module
        },
        capability_binary_surface(capability),
        capability.payload_mode,
        if capability.source_kind.is_empty() {
            "(none)"
        } else {
            &capability.source_kind
        },
        if capability.source_path.is_empty() {
            "(none)"
        } else {
            &capability.source_path
        },
        if capability.source_manifest.is_empty() {
            "(none)"
        } else {
            &capability.source_manifest
        },
        if capability.adapter_kind.is_empty() {
            "(none)"
        } else {
            &capability.adapter_kind
        },
        if capability.import_provenance.is_empty() {
            "(none)"
        } else {
            &capability.import_provenance
        },
        capability_runtime_lane(capability),
        capability_dependency_mode(capability),
        capability_env_contract(capability),
        capability_isolation_expectation(capability),
        if capability.verification_status.is_empty() {
            "(none)"
        } else {
            &capability.verification_status
        },
        if capability.last_verified_at.is_empty() {
            "(never)"
        } else {
            &capability.last_verified_at
        },
        if capability.last_verification_job_id.is_empty() {
            "(none)"
        } else {
            &capability.last_verification_job_id
        },
        if capability.last_verification_execution_id.is_empty() {
            "(none)"
        } else {
            &capability.last_verification_execution_id
        },
        if capability.verification_note.is_empty() {
            "(none)"
        } else {
            &capability.verification_note
        },
        if capability.promotion_state.is_empty() {
            "(none)"
        } else {
            &capability.promotion_state
        },
        if capability.promoted_at.is_empty() {
            "(never)"
        } else {
            &capability.promoted_at
        },
        capability.enabled,
    )
}

pub fn render_capability_import_human(result: &CapabilityImportResult) -> String {
    format!(
        "Meridian Loom // CAPABILITY IMPORT\n==================================\nname:              {}\nmanifest:          {}\nworker_path:       {}\nskill_shape:       {}\nworker_kind:       {}\nworker_entry:      {}\npayload_mode:      {}\nsource_kind:       {}\nsource_path:       {}\nsource_manifest:   {}\nadapter_kind:      {}\nimport_provenance: {}\nruntime_lane:      {}\ndependency:        {}\nenv_contract:      {}\nskill_root:        {}\nskill_script:      {}\naction_type:       {}\nresource:          {}\nnote:              bounded clawfamily skill imported into Loom capability runtime\n",
        result.capability.name,
        result.manifest_path.display(),
        result.worker_path.display(),
        result.skill_shape,
        result.capability.worker_kind,
        if result.capability.worker_entry.is_empty() {
            "(none)"
        } else {
            &result.capability.worker_entry
        },
        result.capability.payload_mode,
        result.capability.source_kind,
        result.capability.source_path,
        result.source_manifest.display(),
        result.detected_signature,
        result.capability.import_provenance,
        capability_runtime_lane(&result.capability),
        capability_dependency_mode(&result.capability),
        capability_env_contract(&result.capability),
        result.skill_root.display(),
        result.skill_script.display(),
        result.capability.action_type,
        result.capability.resource,
    )
}
pub fn render_capability_import_json(result: &CapabilityImportResult) -> String {
    format!(
        "{}\n",
        json!({
            "manifest_path": result.manifest_path.display().to_string(),
            "worker_path": result.worker_path.display().to_string(),
            "skill_shape": result.skill_shape,
            "skill_root": result.skill_root.display().to_string(),
            "skill_script": result.skill_script.display().to_string(),
            "source_manifest": result.source_manifest.display().to_string(),
            "detected_signature": result.detected_signature,
            "capability": descriptor_value(&result.capability),
        })
    )
}

pub fn render_legacy_v1_plugin_import_human(result: &LegacyV1PluginImportResult) -> String {
    let mut out = String::new();
    out.push_str(
        r#"Meridian Loom // LEGACY V1 PLUGIN IMPORT
"#,
    );
    out.push_str(
        r#"======================================
"#,
    );
    out.push_str(&format!(
        r#"plugin_root:      {}
plugin_id:        {}
config_schema:     {}
skills_roots:      {}
imported_skills:   {}
unsupported_items:  {}
"#,
        result.plugin_root.display(),
        result.plugin_id,
        if result.config_schema_json.is_empty() {
            "(none)"
        } else {
            &result.config_schema_json
        },
        if result.skills_roots.is_empty() {
            "(none)".to_string()
        } else {
            result
                .skills_roots
                .iter()
                .map(|path| path.display().to_string())
                .collect::<Vec<_>>()
                .join(", ")
        },
        result.imported_skills.len(),
        result.unsupported_items.len(),
    ));
    for imported in &result.imported_skills {
        out.push_str(&format!(
            r#"- {}
  manifest: {}
  worker_path: {}
  skill_root: {}
  skill_doc: {}
  worker_kind: {}
  worker_entry: {}
  payload_mode: {}
  source_kind: {}
  source_manifest: {}
  import_provenance: {}
  runtime_lane: {}
  dependency: {}
  env_contract: {}
  import_scope: {}
"#,
            imported.capability.name,
            imported.manifest_path.display(),
            imported.worker_path.display(),
            imported.skill_root.display(),
            imported.skill_doc.display(),
            imported.capability.worker_kind,
            if imported.capability.worker_entry.is_empty() {
                "(none)"
            } else {
                &imported.capability.worker_entry
            },
            imported.capability.payload_mode,
            imported.normalized_metadata.source_kind,
            imported.normalized_metadata.source_manifest,
            imported.normalized_metadata.import_provenance,
            capability_runtime_lane(&imported.capability),
            capability_dependency_mode(&imported.capability),
            capability_env_contract(&imported.capability),
            imported.normalized_metadata.import_scope,
        ));
    }
    if !result.unsupported_items.is_empty() {
        out.push_str(
            r#"unsupported:
"#,
        );
        for item in &result.unsupported_items {
            out.push_str(&format!(
                r#"- {} | {} | {}
"#,
                item.path, item.reason, item.detail
            ));
        }
    }
    out
}
pub fn render_legacy_v1_plugin_import_json(result: &LegacyV1PluginImportResult) -> String {
    let imported_skills = result
        .imported_skills
        .iter()
        .map(|imported| {
            json!({
                "manifest_path": imported.manifest_path.display().to_string(),
                "worker_path": imported.worker_path.display().to_string(),
                "skill_root": imported.skill_root.display().to_string(),
                "skill_doc": imported.skill_doc.display().to_string(),
                "normalized_metadata": {
                    "plugin_id": imported.normalized_metadata.plugin_id,
                    "plugin_root": imported.normalized_metadata.plugin_root,
                    "skills_root": imported.normalized_metadata.skills_root,
                    "skill_root": imported.normalized_metadata.skill_root,
                    "skill_name": imported.normalized_metadata.skill_name,
                    "skill_description": imported.normalized_metadata.skill_description,
                    "capability_name": imported.normalized_metadata.capability_name,
                    "source_kind": imported.normalized_metadata.source_kind,
                    "source_manifest": imported.normalized_metadata.source_manifest,
                    "import_provenance": imported.normalized_metadata.import_provenance,
                    "import_scope": imported.normalized_metadata.import_scope,
                },
                "capability": descriptor_value(&imported.capability),
            })
        })
        .collect::<Vec<_>>();
    let unsupported_items = result
        .unsupported_items
        .iter()
        .map(|item| {
            json!({
                "path": item.path,
                "reason": item.reason,
                "detail": item.detail,
            })
        })
        .collect::<Vec<_>>();
    format!(
        r#"{}
"#,
        json!({
            "manifest_path": result.manifest_path.display().to_string(),
            "plugin_root": result.plugin_root.display().to_string(),
            "plugin_id": result.plugin_id,
            "config_schema_json": result.config_schema_json,
            "skills_roots": result.skills_roots.iter().map(|path| path.display().to_string()).collect::<Vec<_>>(),
            "imported_skills": imported_skills,
            "unsupported_items": unsupported_items,
        })
    )
}

pub fn render_capability_forge_human(result: &CapabilityForgeResult) -> String {
    format!(
        "Meridian Loom // CAPABILITY FORGE\n=================================\nname:              {}\nmanifest:          {}\nworker_path:       {}\ntemplate:          {}\nsource_kind:       {}\nadapter_kind:      {}\naction_type:       {}\nresource:          {}\nnote:              candidate capability forged into Loom runtime and ready for verify/promote\n",
        result.capability.name,
        result.manifest_path.display(),
        result.worker_path.display(),
        result.template,
        result.capability.source_kind,
        result.capability.adapter_kind,
        result.capability.action_type,
        result.capability.resource,
    )
}

pub fn render_capability_forge_json(result: &CapabilityForgeResult) -> String {
    format!(
        "{}\n",
        json!({
            "manifest_path": result.manifest_path.display().to_string(),
            "worker_path": result.worker_path.display().to_string(),
            "template": result.template,
            "capability": descriptor_value(&result.capability),
        })
    )
}

pub fn render_capability_json(capability: &CapabilityDescriptor) -> String {
    format!("{}\n", descriptor_value(capability))
}

pub fn render_capability_registry_human(
    root: &Path,
    config: &Config,
    registry: &CapabilityRegistry,
) -> String {
    let mut body = String::new();
    body.push_str("Meridian Loom // CAPABILITY REGISTRY\n");
    body.push_str("====================================\n");
    body.push_str(&format!(
        "root:         {}\nregistry:      {}\ncapabilities:  {}\n\n",
        root.display(),
        capability_registry_path(root, config).display(),
        registry.capabilities.len()
    ));
    for capability in &registry.capabilities {
        body.push_str(&format!(
            "- {} [{}] {} {} -> {}\n",
            capability.name,
            capability.worker_kind,
            capability.verification_status,
            capability.action_type,
            capability.resource
        ));
    }
    body
}

pub fn render_capability_registry_json(registry: &CapabilityRegistry) -> String {
    format!(
        "{}\n",
        json!({
            "version": registry.version,
            "capabilities": registry.capabilities.iter().map(descriptor_value).collect::<Vec<_>>(),
        })
    )
}

fn descriptor_value(capability: &CapabilityDescriptor) -> Value {
    json!({
        "name": capability.name,
        "description": capability.description,
        "action_type": capability.action_type,
        "resource": capability.resource,
        "worker_kind": capability.worker_kind,
        "interpreter": capability_interpreter(capability),
        "worker_entry": capability.worker_entry,
        "wasm_module": capability.wasm_module,
        "binary_surface": capability_binary_surface(capability),
        "payload_mode": capability.payload_mode,
        "source_kind": capability.source_kind,
        "source_path": capability.source_path,
        "source_manifest": capability.source_manifest,
        "adapter_kind": capability.adapter_kind,
        "import_provenance": capability.import_provenance,
        "runtime_lane": capability_runtime_lane(capability),
        "dependency_mode": capability_dependency_mode(capability),
        "env_contract": capability_env_contract(capability),
        "isolation_expectation": capability_isolation_expectation(capability),
        "verification_status": capability.verification_status,
        "last_verified_at": capability.last_verified_at,
        "last_verification_job_id": capability.last_verification_job_id,
        "last_verification_execution_id": capability.last_verification_execution_id,
        "verification_note": capability.verification_note,
        "promotion_state": capability.promotion_state,
        "promoted_at": capability.promoted_at,
        "enabled": capability.enabled,
    })
}

fn descriptor_json(capability: &CapabilityDescriptor) -> String {
    format!("{}\n", descriptor_value(capability))
}

fn gap_value(gap: &CapabilityGapRecord) -> Value {
    json!({
        "gap_id": gap.gap_id,
        "request_id": gap.request_id,
        "requested_at": gap.requested_at,
        "updated_at": gap.updated_at,
        "requested_via": gap.requested_via,
        "capability_name": gap.capability_name,
        "gap_class": gap.gap_class,
        "goal": gap.goal,
        "proposed_capability_name": gap.proposed_capability_name,
        "agent_id": gap.agent_id,
        "org_id": gap.org_id,
        "kernel_path": gap.kernel_path,
        "action_type": gap.action_type,
        "resource": gap.resource,
        "payload_json": gap.payload_json,
        "run_id": gap.run_id,
        "session_id": gap.session_id,
        "original_request_json": gap.original_request_json,
        "forge_status": gap.forge_status,
        "verification_status": gap.verification_status,
        "promotion_status": gap.promotion_status,
        "verified_at": gap.verified_at,
        "verification_note": gap.verification_note,
        "promoted_at": gap.promoted_at,
        "promotion_note": gap.promotion_note,
        "candidate_manifest_path": gap.candidate_manifest_path,
        "verification_job_id": gap.verification_job_id,
        "verification_execution_id": gap.verification_execution_id,
        "last_note": gap.last_note,
    })
}

fn parse_capability_registry(raw: &str) -> LoomResult<CapabilityRegistry> {
    let value: Value = serde_json::from_str(raw).map_err(io_err)?;
    let version = value
        .get("version")
        .and_then(Value::as_str)
        .unwrap_or(CAPABILITY_REGISTRY_VERSION)
        .to_string();
    let capabilities = value
        .get("capabilities")
        .and_then(Value::as_array)
        .ok_or_else(|| "capability registry missing capabilities array".to_string())?
        .iter()
        .map(parse_capability_descriptor_value)
        .collect::<LoomResult<Vec<_>>>()?;
    Ok(CapabilityRegistry {
        version,
        capabilities,
    })
}

fn parse_capability_descriptor_json(raw: &str) -> LoomResult<CapabilityDescriptor> {
    let value: Value = serde_json::from_str(raw).map_err(io_err)?;
    parse_capability_descriptor_value(&value)
}

fn parse_capability_gap_json(raw: &str) -> LoomResult<CapabilityGapRecord> {
    let value: Value = serde_json::from_str(raw).map_err(io_err)?;
    Ok(CapabilityGapRecord {
        gap_id: required_string(&value, "gap_id")?,
        request_id: value
            .get("request_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        requested_at: value
            .get("requested_at")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        updated_at: value
            .get("updated_at")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        requested_via: required_string(&value, "requested_via")?,
        capability_name: required_string(&value, "capability_name")?,
        gap_class: required_string(&value, "gap_class")?,
        goal: value
            .get("goal")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        proposed_capability_name: required_string(&value, "proposed_capability_name")?,
        agent_id: value
            .get("agent_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        org_id: value
            .get("org_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        kernel_path: value
            .get("kernel_path")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        action_type: value
            .get("action_type")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        resource: value
            .get("resource")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        payload_json: value
            .get("payload_json")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        run_id: value
            .get("run_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        session_id: value
            .get("session_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        original_request_json: value
            .get("original_request_json")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        forge_status: value
            .get("forge_status")
            .and_then(Value::as_str)
            .unwrap_or("missing_request_recorded")
            .to_string(),
        verification_status: value
            .get("verification_status")
            .and_then(Value::as_str)
            .unwrap_or("unverified")
            .to_string(),
        promotion_status: value
            .get("promotion_status")
            .and_then(Value::as_str)
            .unwrap_or("candidate")
            .to_string(),
        verified_at: value
            .get("verified_at")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        verification_note: value
            .get("verification_note")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        promoted_at: value
            .get("promoted_at")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        promotion_note: value
            .get("promotion_note")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        candidate_manifest_path: value
            .get("candidate_manifest_path")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        verification_job_id: value
            .get("verification_job_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        verification_execution_id: value
            .get("verification_execution_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        last_note: value
            .get("last_note")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
    })
}

fn parse_capability_descriptor_value(value: &Value) -> LoomResult<CapabilityDescriptor> {
    Ok(CapabilityDescriptor {
        name: required_string(value, "name")?,
        description: value
            .get("description")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        action_type: required_string(value, "action_type")?,
        resource: required_string(value, "resource")?,
        worker_kind: required_string(value, "worker_kind")?,
        worker_entry: value
            .get("worker_entry")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        wasm_module: value
            .get("wasm_module")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        payload_mode: value
            .get("payload_mode")
            .and_then(Value::as_str)
            .unwrap_or("json")
            .to_string(),
        source_kind: value
            .get("source_kind")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        source_path: value
            .get("source_path")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        source_manifest: value
            .get("source_manifest")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        adapter_kind: value
            .get("adapter_kind")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        import_provenance: value
            .get("import_provenance")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        verification_status: value
            .get("verification_status")
            .and_then(Value::as_str)
            .unwrap_or("unverified")
            .to_string(),
        last_verified_at: value
            .get("last_verified_at")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        last_verification_job_id: value
            .get("last_verification_job_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        last_verification_execution_id: value
            .get("last_verification_execution_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        verification_note: value
            .get("verification_note")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        promotion_state: value
            .get("promotion_state")
            .and_then(Value::as_str)
            .unwrap_or("candidate")
            .to_string(),
        promoted_at: value
            .get("promoted_at")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        enabled: value
            .get("enabled")
            .and_then(Value::as_bool)
            .unwrap_or(true),
    })
}

fn parse_workspace_skill_front_matter(
    skill_doc: &Path,
) -> LoomResult<(String, String, Option<String>)> {
    let raw = fs::read_to_string(skill_doc).map_err(io_err)?;
    let mut lines = raw.lines();
    if lines.next().map(str::trim) != Some("---") {
        return Err(format!(
            "workspace skill {} missing front matter",
            skill_doc.display()
        ));
    }
    let mut name = String::new();
    let mut description = String::new();
    let mut entrypoint = None;
    for line in lines {
        let trimmed = line.trim();
        if trimmed == "---" {
            break;
        }
        if let Some((key, value)) = trimmed.split_once(':') {
            let parsed = value.trim().trim_matches('"').trim_matches('\'');
            match key.trim() {
                "name" => name = parsed.to_string(),
                "description" => description = parsed.to_string(),
                "entrypoint" | "entry" => {
                    if !parsed.is_empty() {
                        entrypoint = Some(parsed.to_string());
                    }
                }
                _ => {}
            }
        }
    }
    if name.is_empty() {
        return Err(format!(
            "workspace skill {} front matter missing name",
            skill_doc.display()
        ));
    }
    Ok((name, description, entrypoint))
}

fn load_clawfamily_import_spec(
    skill_root: &Path,
    explicit_entrypoint: Option<&str>,
) -> LoomResult<ClawfamilyImportSpec> {
    let bundle_manifest = skill_root.join("clawskill.json");
    if bundle_manifest.exists() {
        return load_bundle_skill_spec(skill_root, &bundle_manifest);
    }
    load_workspace_skill_spec(skill_root, explicit_entrypoint)
}

fn load_workspace_skill_spec(
    skill_root: &Path,
    explicit_entrypoint: Option<&str>,
) -> LoomResult<ClawfamilyImportSpec> {
    let skill_doc = skill_root.join("SKILL.md");
    if !skill_doc.exists() {
        return Err(format!(
            "clawfamily skill import requires either {} or {}",
            skill_doc.display(),
            skill_root.join("clawskill.json").display()
        ));
    }
    let (skill_name, skill_description, front_matter_entrypoint) =
        parse_workspace_skill_front_matter(&skill_doc)?;
    let selected_entrypoint = explicit_entrypoint
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToString::to_string)
        .or(front_matter_entrypoint);
    let skill_script = if let Some(entrypoint) = selected_entrypoint {
        resolve_workspace_skill_entrypoint(skill_root, &entrypoint)?
    } else {
        let scripts_dir = skill_root.join("scripts");
        let mut scripts = if scripts_dir.exists() {
            fs::read_dir(&scripts_dir)
                .map_err(io_err)?
                .filter_map(|entry| entry.ok().map(|item| item.path()))
                .filter(|path| path.extension().map(|ext| ext == "py").unwrap_or(false))
                .collect::<Vec<_>>()
        } else {
            Vec::new()
        };
        scripts.sort();
        if scripts.len() != 1 {
            return Err(format!(
                "workspace skill import found {} python scripts in {}; pass --entrypoint PATH or add entrypoint: PATH to {}",
                scripts.len(),
                scripts_dir.display(),
                skill_doc.display()
            ));
        }
        scripts.remove(0)
    };
    let script_text = fs::read_to_string(&skill_script).map_err(io_err)?;
    let detected_signature = detect_workspace_skill_signature(&script_text)?;
    Ok(ClawfamilyImportSpec {
        skill_shape: "workspace_python_entrypoint".to_string(),
        skill_name,
        skill_description,
        source_manifest: skill_doc,
        skill_script,
        adapter_kind: detected_signature,
        action_type: "skill_exec".to_string(),
        payload_mode: "json".to_string(),
        source_kind: "legacy_v1_workspace_skill".to_string(),
        import_provenance: "clawfamily_skill_contract_v0/workspace_python_entrypoint".to_string(),
    })
}

fn resolve_workspace_skill_entrypoint(skill_root: &Path, entrypoint: &str) -> LoomResult<PathBuf> {
    let candidate = PathBuf::from(entrypoint.trim());
    let full_path = if candidate.is_absolute() {
        candidate
    } else {
        skill_root.join(candidate)
    };
    if !full_path.exists() {
        return Err(format!(
            "workspace skill entrypoint {} not found under {}",
            entrypoint,
            skill_root.display()
        ));
    }
    if !full_path.is_file() {
        return Err(format!(
            "workspace skill entrypoint {} must be a file",
            full_path.display()
        ));
    }
    Ok(full_path)
}

fn load_bundle_skill_spec(
    skill_root: &Path,
    bundle_manifest: &Path,
) -> LoomResult<ClawfamilyImportSpec> {
    let raw = fs::read_to_string(bundle_manifest).map_err(io_err)?;
    let value: Value = serde_json::from_str(&raw).map_err(io_err)?;
    let version = value.get("version").and_then(Value::as_str).unwrap_or("");
    if version != "clawfamily_skill_contract_v0" {
        return Err(format!(
            "unsupported clawskill bundle version '{}' in {}",
            version,
            bundle_manifest.display()
        ));
    }
    let worker_kind = value
        .get("worker_kind")
        .and_then(Value::as_str)
        .unwrap_or("python");
    if worker_kind != "python" {
        return Err(format!(
            "clawskill bundle {} currently supports only worker_kind=python",
            bundle_manifest.display()
        ));
    }
    let entry = value
        .get("entrypoint")
        .and_then(Value::as_str)
        .or_else(|| value.get("entry").and_then(Value::as_str))
        .ok_or_else(|| {
            format!(
                "clawskill bundle {} requires entrypoint or entry",
                bundle_manifest.display()
            )
        })?;
    let skill_script = skill_root.join(entry);
    if !skill_script.exists() {
        return Err(format!(
            "clawskill bundle entry {} not found under {}",
            entry,
            skill_root.display()
        ));
    }
    let adapter_kind = value
        .get("adapter_kind")
        .and_then(Value::as_str)
        .map(ToString::to_string)
        .unwrap_or_else(|| {
            let script_text = fs::read_to_string(&skill_script).unwrap_or_default();
            detect_workspace_skill_signature(&script_text)
                .unwrap_or_else(|_| "custom_bundle_v0".to_string())
        });
    if !matches!(
        adapter_kind.as_str(),
        "artifact_report_v0" | "url_report_v0" | "download_quarantine_v0"
    ) {
        return Err(format!(
            "clawskill bundle {} uses unsupported adapter_kind '{}'; supported: artifact_report_v0, url_report_v0, download_quarantine_v0",
            bundle_manifest.display(),
            adapter_kind
        ));
    }
    Ok(ClawfamilyImportSpec {
        skill_shape: "bundle_manifest".to_string(),
        skill_name: required_string(&value, "name")?,
        skill_description: value
            .get("description")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        source_manifest: bundle_manifest.to_path_buf(),
        skill_script,
        adapter_kind,
        action_type: value
            .get("action_type")
            .and_then(Value::as_str)
            .unwrap_or("skill_exec")
            .to_string(),
        payload_mode: value
            .get("payload_mode")
            .and_then(Value::as_str)
            .unwrap_or("json")
            .to_string(),
        source_kind: "clawfamily_skill_bundle".to_string(),
        import_provenance: "clawfamily_skill_contract_v0/bundle_manifest".to_string(),
    })
}

fn load_legacy_v1_plugin_manifest_spec(
    plugin_root: &Path,
) -> LoomResult<LegacyV1PluginManifestSpec> {
    let manifest_path = plugin_root.join("legacy_v1.plugin.json");
    if !manifest_path.exists() {
        return Err(format!(
            "legacy_v1 plugin root {} is missing {}",
            plugin_root.display(),
            manifest_path.display()
        ));
    }
    let raw = fs::read_to_string(&manifest_path).map_err(io_err)?;
    let value: Value = serde_json::from_str(&raw).map_err(io_err)?;
    let plugin_id = required_string(&value, "id")?;
    let config_schema_json = value
        .get("configSchema")
        .map(|schema| serde_json::to_string(schema).unwrap_or_else(|_| schema.to_string()))
        .unwrap_or_default();
    let (skill_roots, unsupported_items) =
        parse_legacy_v1_plugin_skill_roots(&value, &manifest_path);
    Ok(LegacyV1PluginManifestSpec {
        manifest_path,
        plugin_id,
        config_schema_json,
        skill_roots,
        unsupported_items,
    })
}

fn parse_legacy_v1_plugin_skill_roots(
    value: &Value,
    manifest_path: &Path,
) -> (
    Vec<LegacyV1PluginSkillRootSpec>,
    Vec<LegacyV1PluginUnsupportedItem>,
) {
    let mut unsupported_items = Vec::new();
    let Some(raw_skills) = value.get("skills") else {
        unsupported_items.push(LegacyV1PluginUnsupportedItem {
            path: manifest_path.display().to_string(),
            reason: "missing_skills_field".to_string(),
            detail: "legacy_v1.plugin.json does not declare a skills field".to_string(),
        });
        return (Vec::new(), unsupported_items);
    };

    let skill_entries: Vec<&Value> = match raw_skills {
        Value::String(_) | Value::Object(_) => vec![raw_skills],
        Value::Array(entries) => entries.iter().collect(),
        _ => {
            unsupported_items.push(LegacyV1PluginUnsupportedItem {
                path: manifest_path.display().to_string(),
                reason: "invalid_skills_field_shape".to_string(),
                detail:
                    "legacy_v1.plugin.json skills must be a string path or an array of path entries"
                        .to_string(),
            });
            return (Vec::new(), unsupported_items);
        }
    };

    let mut skill_roots = Vec::new();
    for entry in skill_entries {
        match parse_legacy_v1_plugin_skill_root_entry(entry, manifest_path) {
            Ok(skill_root) => skill_roots.push(skill_root),
            Err(item) => unsupported_items.push(item),
        }
    }
    (skill_roots, unsupported_items)
}

fn parse_legacy_v1_plugin_skill_root_entry(
    entry: &Value,
    manifest_path: &Path,
) -> Result<LegacyV1PluginSkillRootSpec, LegacyV1PluginUnsupportedItem> {
    match entry {
        Value::String(path) => {
            let trimmed = path.trim();
            if trimmed.is_empty() {
                return Err(LegacyV1PluginUnsupportedItem {
                    path: manifest_path.display().to_string(),
                    reason: "empty_skills_root_path".to_string(),
                    detail: "legacy_v1.plugin.json skills entries must not be empty".to_string(),
                });
            }
            Ok(LegacyV1PluginSkillRootSpec {
                raw_path: trimmed.to_string(),
                config_gated: false,
                gate_detail: String::new(),
            })
        }
        Value::Object(map) => {
            let raw_path = map
                .get("path")
                .or_else(|| map.get("root"))
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(ToString::to_string)
                .ok_or_else(|| LegacyV1PluginUnsupportedItem {
                    path: manifest_path.display().to_string(),
                    reason: "invalid_skills_root_entry".to_string(),
                    detail: "skills root objects need a path or root string".to_string(),
                })?;
            let config_gated = map.contains_key("config")
                || map.contains_key("when")
                || map.contains_key("enabledIf")
                || map.contains_key("condition")
                || map.contains_key("gated");
            let gate_detail = if config_gated {
                format!(
                    "skills root {} is config-gated and this import mode does not support config-gated skills",
                    raw_path
                )
            } else {
                String::new()
            };
            Ok(LegacyV1PluginSkillRootSpec {
                raw_path,
                config_gated,
                gate_detail,
            })
        }
        _ => Err(LegacyV1PluginUnsupportedItem {
            path: manifest_path.display().to_string(),
            reason: "invalid_skills_root_entry_shape".to_string(),
            detail: "skills entries must be string paths or objects with a path".to_string(),
        }),
    }
}

fn collect_legacy_v1_plugin_surface_unsupported_items(
    plugin_root: &Path,
) -> Vec<LegacyV1PluginUnsupportedItem> {
    let mut unsupported_items = Vec::new();
    let checks = [
        (
            "package.json",
            "package_json_not_supported",
            "package.json is not supported for this bounded plugin skill import",
        ),
        (
            "providers",
            "providers_not_supported",
            "providers are not supported for this bounded plugin skill import",
        ),
        (
            "channels",
            "channels_not_supported",
            "channels are not supported for this bounded plugin skill import",
        ),
        (
            "hooks",
            "hooks_not_supported",
            "hooks are not supported for this bounded plugin skill import",
        ),
        (
            "commands",
            "commands_not_supported",
            "commands are not supported for this bounded plugin skill import",
        ),
        (
            "src",
            "runtime_modules_not_supported",
            "runtime modules are not supported for this bounded plugin skill import",
        ),
        (
            "lib",
            "runtime_modules_not_supported",
            "runtime modules are not supported for this bounded plugin skill import",
        ),
        (
            "dist",
            "runtime_modules_not_supported",
            "runtime modules are not supported for this bounded plugin skill import",
        ),
    ];
    for (relative, reason, detail) in checks {
        let path = plugin_root.join(relative);
        if path.exists() {
            unsupported_items.push(LegacyV1PluginUnsupportedItem {
                path: path.display().to_string(),
                reason: reason.to_string(),
                detail: detail.to_string(),
            });
        }
    }
    unsupported_items
}

fn resolve_legacy_v1_plugin_skill_root(
    plugin_root: &Path,
    raw_path: &str,
) -> Result<PathBuf, LegacyV1PluginUnsupportedItem> {
    let trimmed = raw_path.trim();
    if trimmed.is_empty() {
        return Err(LegacyV1PluginUnsupportedItem {
            path: plugin_root.display().to_string(),
            reason: "empty_skills_root_path".to_string(),
            detail: "skills roots must not be empty".to_string(),
        });
    }
    let candidate = Path::new(trimmed);
    if candidate.is_absolute() {
        return Err(LegacyV1PluginUnsupportedItem {
            path: candidate.display().to_string(),
            reason: "absolute_skills_root_path_not_supported".to_string(),
            detail: "legacy_v1.plugin.json skills roots must be relative to the plugin root"
                .to_string(),
        });
    }
    if candidate
        .components()
        .any(|component| matches!(component, std::path::Component::ParentDir))
    {
        return Err(LegacyV1PluginUnsupportedItem {
            path: candidate.display().to_string(),
            reason: "escaping_skills_root_path_not_supported".to_string(),
            detail: "legacy_v1.plugin.json skills roots must stay under the plugin root"
                .to_string(),
        });
    }
    Ok(plugin_root.join(candidate))
}

fn legacy_v1_plugin_skill_capability_name(plugin_id: &str, skill_name: &str) -> String {
    format!(
        "loomskill.{}.{}.v0",
        sanitize_name(plugin_id),
        sanitize_name(skill_name)
    )
}

pub fn update_capability_verification(
    root: &Path,
    config: &Config,
    name: &str,
    verification_status: &str,
    verified_at: &str,
    verification_job_id: &str,
    verification_execution_id: &str,
    verification_note: &str,
) -> LoomResult<CapabilityStateUpdateResult> {
    let manifest_path = custom_capability_manifest_path(root, config, name)?;
    let raw = fs::read_to_string(&manifest_path).map_err(io_err)?;
    let mut capability = parse_capability_descriptor_json(&raw)?;
    capability.verification_status = verification_status.trim().to_string();
    capability.last_verified_at = verified_at.trim().to_string();
    capability.last_verification_job_id = verification_job_id.trim().to_string();
    capability.last_verification_execution_id = verification_execution_id.trim().to_string();
    capability.verification_note = verification_note.trim().to_string();
    fs::write(&manifest_path, descriptor_json(&capability)).map_err(io_err)?;
    Ok(CapabilityStateUpdateResult {
        manifest_path,
        capability,
    })
}

pub fn promote_capability(
    root: &Path,
    config: &Config,
    name: &str,
    promoted_at: &str,
) -> LoomResult<CapabilityStateUpdateResult> {
    let manifest_path = custom_capability_manifest_path(root, config, name)?;
    let raw = fs::read_to_string(&manifest_path).map_err(io_err)?;
    let mut capability = parse_capability_descriptor_json(&raw)?;
    if capability.verification_status != "verified" {
        return Err(format!(
            "capability '{}' must be verified before promotion (current status: {})",
            name, capability.verification_status
        ));
    }
    capability.promotion_state = "promoted".to_string();
    capability.promoted_at = promoted_at.trim().to_string();
    fs::write(&manifest_path, descriptor_json(&capability)).map_err(io_err)?;
    Ok(CapabilityStateUpdateResult {
        manifest_path,
        capability,
    })
}

pub fn render_capability_state_update_human(
    heading: &str,
    result: &CapabilityStateUpdateResult,
) -> String {
    format!(
        "{heading}\n{underline}\nname:              {}\nmanifest:          {}\nverification:      {}\nverified_at:       {}\nverify_job:        {}\nverify_exec:       {}\nverification_note: {}\npromotion:         {}\npromoted_at:       {}\n",
        result.capability.name,
        result.manifest_path.display(),
        if result.capability.verification_status.is_empty() {
            "(none)"
        } else {
            &result.capability.verification_status
        },
        if result.capability.last_verified_at.is_empty() {
            "(never)"
        } else {
            &result.capability.last_verified_at
        },
        if result.capability.last_verification_job_id.is_empty() {
            "(none)"
        } else {
            &result.capability.last_verification_job_id
        },
        if result.capability.last_verification_execution_id.is_empty() {
            "(none)"
        } else {
            &result.capability.last_verification_execution_id
        },
        if result.capability.verification_note.is_empty() {
            "(none)"
        } else {
            &result.capability.verification_note
        },
        if result.capability.promotion_state.is_empty() {
            "(none)"
        } else {
            &result.capability.promotion_state
        },
        if result.capability.promoted_at.is_empty() {
            "(never)"
        } else {
            &result.capability.promoted_at
        },
        underline = "=".repeat(heading.len()),
    )
}

pub fn render_capability_state_update_json(result: &CapabilityStateUpdateResult) -> String {
    format!(
        "{}\n",
        json!({
            "manifest_path": result.manifest_path.display().to_string(),
            "capability": descriptor_value(&result.capability),
        })
    )
}

pub fn record_capability_gap(
    root: &Path,
    config: &Config,
    request: &CapabilityGapRequest,
) -> LoomResult<CapabilityGapUpdateResult> {
    if request.capability_name.trim().is_empty() {
        return Err("capability gap requires capability_name".to_string());
    }
    if request.gap_class.trim().is_empty() {
        return Err("capability gap requires gap_class".to_string());
    }
    if request.proposed_capability_name.trim().is_empty() {
        return Err("capability gap requires proposed_capability_name".to_string());
    }
    ensure_capability_registry_scaffold(root, config)?;
    let gap_id = format!(
        "gap-{}-{}",
        precise_timestamp_now(),
        sanitize_name(&request.proposed_capability_name)
    );
    let request_id = if request.request_id.trim().is_empty() {
        format!(
            "request-{}-{}",
            precise_timestamp_now(),
            sanitize_name(&request.proposed_capability_name)
        )
    } else {
        request.request_id.trim().to_string()
    };
    let original_request_json = if request.original_request_json.trim().is_empty() {
        gap_request_value(request, &request_id).to_string()
    } else {
        request.original_request_json.trim().to_string()
    };
    let gap = CapabilityGapRecord {
        gap_id: gap_id.clone(),
        request_id,
        requested_at: timestamp_now(),
        updated_at: timestamp_now(),
        requested_via: request.requested_via.trim().to_string(),
        capability_name: request.capability_name.trim().to_string(),
        gap_class: request.gap_class.trim().to_string(),
        goal: request.goal.trim().to_string(),
        proposed_capability_name: request.proposed_capability_name.trim().to_string(),
        agent_id: request.agent_id.trim().to_string(),
        org_id: request.org_id.trim().to_string(),
        kernel_path: request.kernel_path.trim().to_string(),
        action_type: request.action_type.trim().to_string(),
        resource: request.resource.trim().to_string(),
        payload_json: request.payload_json.trim().to_string(),
        run_id: request.run_id.trim().to_string(),
        session_id: request.session_id.trim().to_string(),
        original_request_json,
        forge_status: "missing_request_recorded".to_string(),
        verification_status: "unverified".to_string(),
        promotion_status: "candidate".to_string(),
        verified_at: String::new(),
        verification_note: String::new(),
        promoted_at: String::new(),
        promotion_note: String::new(),
        candidate_manifest_path: String::new(),
        verification_job_id: String::new(),
        verification_execution_id: String::new(),
        last_note: "missing capability recorded for bounded forge follow-up".to_string(),
    };
    let gap_path = capability_gap_dir(root, config).join(format!("{}.json", gap_id));
    fs::write(&gap_path, format!("{}\n", gap_value(&gap))).map_err(io_err)?;
    Ok(CapabilityGapUpdateResult { gap_path, gap })
}

fn gap_request_value(request: &CapabilityGapRequest, request_id: &str) -> Value {
    json!({
        "request_id": request_id,
        "requested_via": request.requested_via,
        "capability_name": request.capability_name,
        "gap_class": request.gap_class,
        "goal": request.goal,
        "proposed_capability_name": request.proposed_capability_name,
        "agent_id": request.agent_id,
        "org_id": request.org_id,
        "kernel_path": request.kernel_path,
        "action_type": request.action_type,
        "resource": request.resource,
        "payload_json": request.payload_json,
        "run_id": request.run_id,
        "session_id": request.session_id,
    })
}

fn gap_replay_request_value(gap: &CapabilityGapRecord) -> Value {
    let request = CapabilityGapRequest {
        request_id: gap.request_id.clone(),
        requested_via: gap.requested_via.clone(),
        capability_name: gap.capability_name.clone(),
        gap_class: gap.gap_class.clone(),
        goal: gap.goal.clone(),
        proposed_capability_name: gap.proposed_capability_name.clone(),
        agent_id: gap.agent_id.clone(),
        org_id: gap.org_id.clone(),
        kernel_path: gap.kernel_path.clone(),
        action_type: gap.action_type.clone(),
        resource: gap.resource.clone(),
        payload_json: gap.payload_json.clone(),
        run_id: gap.run_id.clone(),
        session_id: gap.session_id.clone(),
        original_request_json: gap.original_request_json.clone(),
    };
    gap_request_value(&request, &gap.request_id)
}

fn gap_render_value(gap: &CapabilityGapRecord) -> Value {
    let mut value = gap_value(gap);
    if let Some(object) = value.as_object_mut() {
        object.insert("replay_request".to_string(), gap_replay_request_value(gap));
    }
    value
}

pub fn load_capability_gap(
    root: &Path,
    config: &Config,
    gap_id: &str,
) -> LoomResult<CapabilityGapRecord> {
    let gap_path = capability_gap_manifest_path(root, config, gap_id)?;
    let raw = fs::read_to_string(&gap_path).map_err(io_err)?;
    parse_capability_gap_json(&raw)
}

pub fn capability_gap_replay_request(
    gap: &CapabilityGapRecord,
) -> LoomResult<CapabilityGapRequest> {
    match gap.requested_via.trim() {
        "action_execute" => Ok(CapabilityGapRequest {
            request_id: gap.request_id.clone(),
            requested_via: gap.requested_via.clone(),
            capability_name: gap.capability_name.clone(),
            gap_class: gap.gap_class.clone(),
            goal: gap.goal.clone(),
            proposed_capability_name: gap.proposed_capability_name.clone(),
            agent_id: gap.agent_id.clone(),
            org_id: gap.org_id.clone(),
            kernel_path: gap.kernel_path.clone(),
            action_type: gap.action_type.clone(),
            resource: gap.resource.clone(),
            payload_json: gap.payload_json.clone(),
            run_id: gap.run_id.clone(),
            session_id: gap.session_id.clone(),
            original_request_json: gap.original_request_json.clone(),
        }),
        other => Err(format!(
            "capability gap replay only supports requested_via=action_execute; got {}",
            if other.is_empty() { "(none)" } else { other }
        )),
    }
}

pub fn update_capability_gap_forge(
    root: &Path,
    config: &Config,
    gap_id: &str,
    candidate_manifest_path: &Path,
    note: &str,
) -> LoomResult<CapabilityGapUpdateResult> {
    let gap_path = capability_gap_manifest_path(root, config, gap_id)?;
    let raw = fs::read_to_string(&gap_path).map_err(io_err)?;
    let mut gap = parse_capability_gap_json(&raw)?;
    gap.updated_at = timestamp_now();
    gap.forge_status = "candidate_forged".to_string();
    gap.candidate_manifest_path = candidate_manifest_path.display().to_string();
    gap.last_note = note.trim().to_string();
    fs::write(&gap_path, format!("{}\n", gap_value(&gap))).map_err(io_err)?;
    Ok(CapabilityGapUpdateResult { gap_path, gap })
}

pub fn update_capability_gap_verification(
    root: &Path,
    config: &Config,
    gap_id: &str,
    verification_status: &str,
    verification_job_id: &str,
    verification_execution_id: &str,
    note: &str,
) -> LoomResult<CapabilityGapUpdateResult> {
    let gap_path = capability_gap_manifest_path(root, config, gap_id)?;
    let raw = fs::read_to_string(&gap_path).map_err(io_err)?;
    let mut gap = parse_capability_gap_json(&raw)?;
    let now = timestamp_now();
    gap.updated_at = now.clone();
    gap.verification_status = verification_status.trim().to_string();
    gap.verified_at = now;
    gap.verification_job_id = verification_job_id.trim().to_string();
    gap.verification_execution_id = verification_execution_id.trim().to_string();
    gap.verification_note = note.trim().to_string();
    gap.last_note = note.trim().to_string();
    fs::write(&gap_path, format!("{}\n", gap_value(&gap))).map_err(io_err)?;
    Ok(CapabilityGapUpdateResult { gap_path, gap })
}

pub fn update_capability_gap_promotion(
    root: &Path,
    config: &Config,
    gap_id: &str,
    promotion_status: &str,
    note: &str,
) -> LoomResult<CapabilityGapUpdateResult> {
    let gap_path = capability_gap_manifest_path(root, config, gap_id)?;
    let raw = fs::read_to_string(&gap_path).map_err(io_err)?;
    let mut gap = parse_capability_gap_json(&raw)?;
    let now = timestamp_now();
    gap.updated_at = now.clone();
    gap.promotion_status = promotion_status.trim().to_string();
    gap.promoted_at = now;
    gap.promotion_note = note.trim().to_string();
    gap.last_note = note.trim().to_string();
    fs::write(&gap_path, format!("{}\n", gap_value(&gap))).map_err(io_err)?;
    Ok(CapabilityGapUpdateResult { gap_path, gap })
}

pub fn render_capability_gap_human(result: &CapabilityGapUpdateResult) -> String {
    let replay_request_status = match capability_gap_replay_request(&result.gap) {
        Ok(_) => "supported (requested_via=action_execute)".to_string(),
        Err(error) => format!("unavailable ({})", error),
    };
    format!(
        "Meridian Loom // CAPABILITY GAP
================================
gap_id:              {}
request_id:          {}
gap_path:            {}
requested_via:       {}
capability_name:     {}
gap_class:           {}
goal:                {}
proposed_capability: {}
agent_id:            {}
org_id:              {}
kernel_path:         {}
action_type:         {}
resource:            {}
original_request:    {}
forge_status:        {}
verification_status: {}
promotion_status:    {}
verified_at:         {}
verification_note:   {}
promoted_at:         {}
promotion_note:      {}
candidate_manifest:  {}
verification_job:    {}
verification_exec:   {}
replay_request:      {}
last_note:           {}
",
        result.gap.gap_id,
        if result.gap.request_id.is_empty() {
            "(none)"
        } else {
            &result.gap.request_id
        },
        result.gap_path.display(),
        result.gap.requested_via,
        result.gap.capability_name,
        result.gap.gap_class,
        if result.gap.goal.is_empty() {
            "(none)"
        } else {
            &result.gap.goal
        },
        result.gap.proposed_capability_name,
        if result.gap.agent_id.is_empty() {
            "(none)"
        } else {
            &result.gap.agent_id
        },
        if result.gap.org_id.is_empty() {
            "(none)"
        } else {
            &result.gap.org_id
        },
        if result.gap.kernel_path.is_empty() {
            "(none)"
        } else {
            &result.gap.kernel_path
        },
        if result.gap.action_type.is_empty() {
            "(none)"
        } else {
            &result.gap.action_type
        },
        if result.gap.resource.is_empty() {
            "(none)"
        } else {
            &result.gap.resource
        },
        if result.gap.original_request_json.is_empty() {
            "(none)"
        } else {
            &result.gap.original_request_json
        },
        result.gap.forge_status,
        result.gap.verification_status,
        result.gap.promotion_status,
        if result.gap.verified_at.is_empty() {
            "(never)"
        } else {
            &result.gap.verified_at
        },
        if result.gap.verification_note.is_empty() {
            "(none)"
        } else {
            &result.gap.verification_note
        },
        if result.gap.promoted_at.is_empty() {
            "(never)"
        } else {
            &result.gap.promoted_at
        },
        if result.gap.promotion_note.is_empty() {
            "(none)"
        } else {
            &result.gap.promotion_note
        },
        if result.gap.candidate_manifest_path.is_empty() {
            "(none)"
        } else {
            &result.gap.candidate_manifest_path
        },
        if result.gap.verification_job_id.is_empty() {
            "(none)"
        } else {
            &result.gap.verification_job_id
        },
        if result.gap.verification_execution_id.is_empty() {
            "(none)"
        } else {
            &result.gap.verification_execution_id
        },
        replay_request_status,
        if result.gap.last_note.is_empty() {
            "(none)"
        } else {
            &result.gap.last_note
        },
    )
}

pub fn render_capability_gap_json(result: &CapabilityGapUpdateResult) -> String {
    format!(
        "{}\n",
        json!({
            "gap_path": result.gap_path.display().to_string(),
            "gap": gap_render_value(&result.gap),
        })
    )
}

fn detect_workspace_skill_signature(script_text: &str) -> LoomResult<String> {
    let has = |needle: &str| script_text.contains(needle);
    if has("--artifact") && has("--out") {
        return Ok("artifact_report_v0".to_string());
    }
    if has("--url") && has("--quarantine-root") && has("--out") {
        return Ok("download_quarantine_v0".to_string());
    }
    if has("--url") && has("--out") {
        return Ok("url_report_v0".to_string());
    }
    Err("workspace skill import supports only script signatures with --artifact/--out or --url/--out today".to_string())
}

fn normalize_forge_template(template: &str) -> LoomResult<&'static str> {
    match template.trim() {
        FORGE_TEMPLATE_ECHO_JSON => Ok(FORGE_TEMPLATE_ECHO_JSON),
        FORGE_TEMPLATE_ARTIFACT_INSPECT => Ok(FORGE_TEMPLATE_ARTIFACT_INSPECT),
        FORGE_TEMPLATE_URL_BUNDLE => Ok(FORGE_TEMPLATE_URL_BUNDLE),
        other => Err(format!(
            "unsupported forge template '{}'; supported: {}, {}, {}",
            other,
            FORGE_TEMPLATE_ECHO_JSON,
            FORGE_TEMPLATE_ARTIFACT_INSPECT,
            FORGE_TEMPLATE_URL_BUNDLE
        )),
    }
}

fn template_for_gap_class(gap_class: &str) -> LoomResult<&'static str> {
    match gap_class.trim() {
        "artifact_triage" | "artifact_inspect" => Ok(FORGE_TEMPLATE_ARTIFACT_INSPECT),
        "url_collection" | "url_bundle" => Ok(FORGE_TEMPLATE_URL_BUNDLE),
        "response_echo" | "echo" => Ok(FORGE_TEMPLATE_ECHO_JSON),
        other => Err(format!(
            "unsupported gap class '{}'; supported: artifact_triage, url_collection, response_echo",
            other
        )),
    }
}

fn default_forge_description(template: &str, goal: &str) -> String {
    let suffix = if goal.trim().is_empty() {
        String::new()
    } else {
        format!(" for goal: {}", goal.trim())
    };
    match template {
        FORGE_TEMPLATE_ECHO_JSON => format!("Forged echo capability candidate{}", suffix),
        FORGE_TEMPLATE_ARTIFACT_INSPECT => {
            format!("Forged artifact inspection capability candidate{}", suffix)
        }
        FORGE_TEMPLATE_URL_BUNDLE => format!("Forged URL bundle capability candidate{}", suffix),
        _ => format!("Forged capability candidate{}", suffix),
    }
}

pub fn capability_runtime_lane(capability: &CapabilityDescriptor) -> &'static str {
    match capability.worker_kind.as_str() {
        "wasm" => "wasmtime_local_guest",
        "python" if capability.source_kind == "legacy_v1_workspace_skill" => {
            "python_host_process/imported_workspace_skill"
        }
        "python" if capability.source_kind == "clawfamily_skill_bundle" => {
            "python_host_process/imported_skill_bundle"
        }
        "python" if capability.source_kind == "legacy_v1_plugin_skill" => {
            "python_host_process/imported_legacy_v1_plugin_skill"
        }
        "python" if capability.source_kind == "loom_forge_candidate" => {
            "python_host_process/forged_candidate"
        }
        "python" => "python_host_process",
        _ => "unknown",
    }
}

pub fn capability_dependency_mode(capability: &CapabilityDescriptor) -> &'static str {
    match capability.source_kind.as_str() {
        "legacy_v1_workspace_skill" => "workspace_host_python",
        "clawfamily_skill_bundle" => "bundle_host_python",
        "legacy_v1_plugin_skill" => "plugin_host_python",
        "loom_forge_candidate" => "loom_generated_python",
        "loom_builtin" if capability.worker_kind == "wasm" => "builtin_wasm_guest",
        "loom_builtin" => "builtin_runtime_worker",
        "loom_scaffold" => "scaffolded_runtime_worker",
        _ => "unspecified",
    }
}

pub fn capability_env_contract(capability: &CapabilityDescriptor) -> String {
    match capability.source_kind.as_str() {
        "legacy_v1_workspace_skill" => format!(
            "host python3 + source skill root {} + wrapper {}",
            if capability.source_path.is_empty() {
                "(unknown)"
            } else {
                &capability.source_path
            },
            if capability.worker_entry.is_empty() {
                "(none)"
            } else {
                &capability.worker_entry
            }
        ),
        "clawfamily_skill_bundle" => format!(
            "host python3 + bundle manifest {} + wrapper {}",
            if capability.source_manifest.is_empty() {
                "(none)"
            } else {
                &capability.source_manifest
            },
            if capability.worker_entry.is_empty() {
                "(none)"
            } else {
                &capability.worker_entry
            }
        ),
        "legacy_v1_plugin_skill" => format!(
            "host python3 + plugin skill root {} + wrapper {}",
            if capability.source_path.is_empty() {
                "(unknown)"
            } else {
                &capability.source_path
            },
            if capability.worker_entry.is_empty() {
                "(none)"
            } else {
                &capability.worker_entry
            }
        ),
        "loom_forge_candidate" => format!(
            "host python3 + forged worker {}",
            if capability.worker_entry.is_empty() {
                "(none)"
            } else {
                &capability.worker_entry
            }
        ),
        "loom_builtin" if capability.worker_kind == "wasm" => format!(
            "local wasmtime guest {}",
            if capability.wasm_module.is_empty() {
                "(none)"
            } else {
                &capability.wasm_module
            }
        ),
        _ => format!(
            "runtime-managed worker {}",
            if capability.worker_entry.is_empty() {
                "(none)"
            } else {
                &capability.worker_entry
            }
        ),
    }
}

fn render_forged_capability_worker(capability_name: &str, template: &str) -> LoomResult<String> {
    let capability_name = serde_json::to_string(capability_name).map_err(io_err)?;
    let template_name = serde_json::to_string(template).map_err(io_err)?;
    let handler = match template {
        FORGE_TEMPLATE_ECHO_JSON => {
            r#"
    summary = parsed_payload.get("message") or f"forged echo {CAPABILITY_NAME} executed"
    result = {
        "status": "completed",
        "worker_kind": "python_forge_candidate",
        "template_kind": TEMPLATE_NAME,
        "capability_name": CAPABILITY_NAME,
        "completed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "agent_id": envelope.get("agent_id", ""),
        "org_id": envelope.get("org_id", ""),
        "action_type": envelope.get("action_type", ""),
        "resource": envelope.get("resource", ""),
        "summary": summary,
        "echo_message": parsed_payload.get("message", ""),
        "payload": parsed_payload,
    }
"#
        }
        FORGE_TEMPLATE_ARTIFACT_INSPECT => {
            r#"
    artifact_path = pathlib.Path(_required(parsed_payload, "artifact_path"))
    if not artifact_path.exists():
        raise FileNotFoundError(f"artifact not found: {artifact_path}")
    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    result = {
        "status": "completed",
        "worker_kind": "python_forge_candidate",
        "template_kind": TEMPLATE_NAME,
        "capability_name": CAPABILITY_NAME,
        "completed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "agent_id": envelope.get("agent_id", ""),
        "org_id": envelope.get("org_id", ""),
        "action_type": envelope.get("action_type", ""),
        "resource": envelope.get("resource", ""),
        "summary": f"artifact {artifact_path.name} size={artifact_path.stat().st_size} sha256={digest[:12]}",
        "artifact_path": str(artifact_path),
        "artifact_name": artifact_path.name,
        "artifact_exists": True,
        "artifact_size_bytes": artifact_path.stat().st_size,
        "artifact_sha256": digest,
        "payload": parsed_payload,
    }
"#
        }
        FORGE_TEMPLATE_URL_BUNDLE => {
            r#"
    urls = parsed_payload.get("urls") or []
    if parsed_payload.get("url"):
        urls = [parsed_payload["url"], *urls]
    if not urls:
        raise ValueError("payload missing url or urls")
    domains = []
    for raw_url in urls:
        parsed = urllib.parse.urlparse(str(raw_url))
        domains.append(parsed.netloc or "(unknown)")
    unique_domains = sorted(set(domains))
    result = {
        "status": "completed",
        "worker_kind": "python_forge_candidate",
        "template_kind": TEMPLATE_NAME,
        "capability_name": CAPABILITY_NAME,
        "completed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "agent_id": envelope.get("agent_id", ""),
        "org_id": envelope.get("org_id", ""),
        "action_type": envelope.get("action_type", ""),
        "resource": envelope.get("resource", ""),
        "summary": f"url bundle domains={','.join(unique_domains)} count={len(urls)}",
        "url_count": len(urls),
        "domains": unique_domains,
        "urls": [str(item) for item in urls],
        "payload": parsed_payload,
    }
"#
        }
        _ => {
            return Err(format!(
                "unsupported forge template '{}'; expected {}, {}, or {}",
                template,
                FORGE_TEMPLATE_ECHO_JSON,
                FORGE_TEMPLATE_ARTIFACT_INSPECT,
                FORGE_TEMPLATE_URL_BUNDLE
            ))
        }
    };
    Ok(format!(
        r#"#!/usr/bin/env python3
import argparse
import hashlib
import json
import pathlib
import urllib.parse
from datetime import datetime, timezone

CAPABILITY_NAME = {capability_name}
TEMPLATE_NAME = {template_name}


def _load_payload(raw):
    if not raw:
        return {{}}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {{"raw_payload": raw}}


def _required(payload, key):
    value = payload.get(key)
    if value is None or value == "":
        raise ValueError(f"payload missing {{key}}")
    return value


def main():
    parser = argparse.ArgumentParser(description="Meridian Loom forged capability worker")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    request = json.loads(pathlib.Path(args.input).read_text(encoding="utf-8"))
    envelope = request.get("envelope", {{}})
    parsed_payload = _load_payload(request.get("payload_json", "") or envelope.get("payload_json", ""))

{handler}

    pathlib.Path(args.output).write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"#
    ))
}

fn render_workspace_skill_wrapper(
    capability_name: &str,
    skill_name: &str,
    skill_root: &Path,
    skill_script: &Path,
    detected_signature: &str,
    source_kind: &str,
) -> LoomResult<String> {
    let capability_name = serde_json::to_string(capability_name).map_err(io_err)?;
    let skill_name = serde_json::to_string(skill_name).map_err(io_err)?;
    let skill_root = serde_json::to_string(&skill_root.display().to_string()).map_err(io_err)?;
    let skill_script =
        serde_json::to_string(&skill_script.display().to_string()).map_err(io_err)?;
    let detected_signature = serde_json::to_string(detected_signature).map_err(io_err)?;
    let source_kind = serde_json::to_string(source_kind).map_err(io_err)?;
    Ok(format!(
        r#"#!/usr/bin/env python3
import argparse
import json
import pathlib
import subprocess
from datetime import datetime, timezone

CAPABILITY_NAME = {capability_name}
SKILL_NAME = {skill_name}
SKILL_ROOT = pathlib.Path({skill_root})
SKILL_SCRIPT = pathlib.Path({skill_script})
ADAPTER_KIND = {detected_signature}
SOURCE_KIND = {source_kind}


def _load_payload(raw):
    if not raw:
        return {{}}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {{"raw_payload": raw}}


def _required(payload, key):
    value = payload.get(key)
    if value is None or value == "":
        raise ValueError(f"payload missing {{key}}")
    return value


def _command(payload, skill_output_path):
    if ADAPTER_KIND == "artifact_report_v0":
        command = ["python3", str(SKILL_SCRIPT), "--artifact", _required(payload, "artifact_path"), "--out", str(skill_output_path)]
        if payload.get("skip_container", True):
            command.append("--skip-container")
        if payload.get("image"):
            command.extend(["--image", str(payload["image"])])
        return command
    if ADAPTER_KIND == "url_report_v0":
        urls = payload.get("urls") or []
        if payload.get("url"):
            urls = [payload["url"], *urls]
        if not urls:
            raise ValueError("payload missing url or urls")
        command = ["python3", str(SKILL_SCRIPT)]
        for url in urls:
            command.extend(["--url", str(url)])
        command.extend(["--out", str(skill_output_path)])
        if payload.get("timeout") is not None:
            command.extend(["--timeout", str(payload["timeout"])])
        if payload.get("max_bytes") is not None:
            command.extend(["--max-bytes", str(payload["max_bytes"])])
        return command
    if ADAPTER_KIND == "download_quarantine_v0":
        command = [
            "python3",
            str(SKILL_SCRIPT),
            "--url",
            _required(payload, "url"),
            "--out",
            str(skill_output_path),
            "--quarantine-root",
            str(payload.get("quarantine_root") or (skill_output_path.parent / "quarantine")),
        ]
        if payload.get("timeout") is not None:
            command.extend(["--timeout", str(payload["timeout"])])
        if payload.get("max_bytes") is not None:
            command.extend(["--max-bytes", str(payload["max_bytes"])])
        return command
    raise ValueError(f"unsupported adapter kind {{ADAPTER_KIND}}")


def main():
    parser = argparse.ArgumentParser(description="Meridian Loom imported workspace-skill adapter")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    request = json.loads(pathlib.Path(args.input).read_text(encoding="utf-8"))
    envelope = request.get("envelope", {{}})
    payload = _load_payload(request.get("payload_json", "") or envelope.get("payload_json", ""))
    skill_output_path = pathlib.Path(args.output).with_name("imported-skill-output.json")
    skill_output_path.parent.mkdir(parents=True, exist_ok=True)
    command = _command(payload, skill_output_path)
    proc = subprocess.run(command, capture_output=True, text=True)

    skill_output = None
    if skill_output_path.exists():
        try:
            skill_output = json.loads(skill_output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            skill_output = {{"raw_output": skill_output_path.read_text(encoding="utf-8")}}

    status = "completed" if proc.returncode == 0 else "failed"
    summary = f"imported skill {{SKILL_NAME}} {{status}}"
    if isinstance(skill_output, dict):
        summary = (
            skill_output.get("summary")
            or (skill_output.get("verdict") or {{}}).get("risk")
            or skill_output.get("risk")
            or skill_output.get("mode")
            or summary
        )

    result = {{
        "status": status,
        "worker_contract_version": "loom.worker.v0",
        "worker_kind": f"imported_clawfamily_skill/{{SKILL_NAME}}",
        "capability_name": CAPABILITY_NAME,
        "imported_skill_name": SKILL_NAME,
        "source_kind": SOURCE_KIND,
        "source_path": str(SKILL_ROOT),
        "adapter_kind": ADAPTER_KIND,
        "completed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "agent_id": envelope.get("agent_id", ""),
        "org_id": envelope.get("org_id", ""),
        "action_type": envelope.get("action_type", ""),
        "resource": envelope.get("resource", ""),
        "payload": payload,
        "command": command,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "skill_output_path": str(skill_output_path),
        "skill_output": skill_output,
        "summary": summary,
    }}
    pathlib.Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if proc.returncode == 0 else proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
"#
    ))
}

fn required_string(value: &Value, key: &str) -> LoomResult<String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(ToString::to_string)
        .filter(|raw| !raw.trim().is_empty())
        .ok_or_else(|| format!("capability manifest missing {}", key))
}

fn upsert_capability(
    capabilities: &mut Vec<CapabilityDescriptor>,
    capability: CapabilityDescriptor,
) {
    if let Some(existing) = capabilities
        .iter_mut()
        .find(|item| item.name == capability.name)
    {
        *existing = capability;
    } else {
        capabilities.push(capability);
    }
}

fn custom_capability_manifest_path(
    root: &Path,
    config: &Config,
    name: &str,
) -> LoomResult<PathBuf> {
    let manifest_path =
        capability_custom_dir(root, config).join(format!("{}.json", sanitize_name(name)));
    if !manifest_path.exists() {
        return Err(format!(
            "capability '{}' does not have a writable custom manifest at {}",
            name,
            manifest_path.display()
        ));
    }
    Ok(manifest_path)
}

fn capability_gap_manifest_path(root: &Path, config: &Config, gap_id: &str) -> LoomResult<PathBuf> {
    let gap_path = capability_gap_dir(root, config).join(format!("{}.json", sanitize_name(gap_id)));
    if !gap_path.exists() {
        return Err(format!(
            "capability gap '{}' does not exist at {}",
            gap_id,
            gap_path.display()
        ));
    }
    Ok(gap_path)
}

fn save_capability_registry(registry: &CapabilityRegistry, path: &Path) -> LoomResult<()> {
    let payload = json!({
        "version": registry.version,
        "capabilities": registry.capabilities.iter().map(descriptor_value).collect::<Vec<_>>(),
    });
    fs::write(path, format!("{}\n", payload)).map_err(io_err)
}

fn sanitize_name(input: &str) -> String {
    input
        .chars()
        .map(|ch| if ch.is_ascii_alphanumeric() { ch } else { '-' })
        .collect::<String>()
        .trim_matches('-')
        .to_ascii_lowercase()
}

fn io_err(error: impl std::fmt::Display) -> String {
    error.to_string()
}

pub fn default_capabilities_dir() -> &'static str {
    DEFAULT_CAPABILITY_DIR
}

pub fn timestamp_now() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    format!("{}", secs)
}

fn precise_timestamp_now() -> String {
    let millis = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    millis.to_string()
}

#[cfg(test)]
mod tests {
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

    fn sample_config() -> Config {
        Config {
            mode: "embedded".to_string(),
            kernel_path: String::new(),
            org_id: "local_foundry".to_string(),
            state_dir: "state".to_string(),
            run_dir: "run".to_string(),
            log_dir: "logs".to_string(),
            artifact_dir: "artifacts".to_string(),
            capabilities_dir: "capabilities".to_string(),
            python_path: "workers/python".to_string(),
            typescript_path: "workers/typescript".to_string(),
            wasm_dir: "workers/wasm".to_string(),
            service_http_address: "127.0.0.1:18910".to_string(),
            service_token_env: "LOOM_SERVICE_TOKEN".to_string(),
            service_max_jobs: 8,
            service_poll_seconds: 1,
            service_max_iterations: 0,
            log_level: "info".to_string(),
            log_format: "jsonl".to_string(),
            log_max_bytes: 1024,
            log_max_files: 3,
            handoff_mode: "off".to_string(),
            delivery_queue: "/tmp/delivery-queue".to_string(),
        }
    }

    fn write_legacy_v1_plugin_manifest(plugin_root: &Path, skills_json: &str) {
        fs::write(
            plugin_root.join("legacy_v1.plugin.json"),
            format!(
                r#"{{
  "id": "acme-plugin",
  "configSchema": {{
    "type": "object",
    "title": "Plugin config"
  }},
  "skills": {}
}}
"#,
                skills_json
            ),
        )
        .expect("write plugin manifest");
    }

    fn write_skill_doc(skill_dir: &Path, name: &str, description: &str) {
        fs::create_dir_all(skill_dir).expect("create skill dir");
        fs::write(
            skill_dir.join("SKILL.md"),
            format!(
                r#"---
name: {}
description: {}
---

# {}
"#,
                name, description, name
            ),
        )
        .expect("write skill doc");
    }

    #[test]
    fn scaffold_writes_registry_and_defaults() {
        let root = temp_path("loom-cap-registry");
        let config = sample_config();
        let path = ensure_capability_registry_scaffold(&root, &config).expect("registry scaffold");
        assert!(path.exists());
        let registry = load_capability_registry(&root, &config).expect("registry load");
        assert!(registry
            .capabilities
            .iter()
            .any(|item| item.name == "loom.echo.v1"));
        assert!(registry
            .capabilities
            .iter()
            .any(|item| item.name == "loom.wasm.minimal.v1"));
        assert!(registry
            .capabilities
            .iter()
            .any(|item| item.name == "loom.browser.navigate.v1"));
        assert!(registry
            .capabilities
            .iter()
            .any(|item| item.name == "loom.fs.read.v1"));
        assert!(registry
            .capabilities
            .iter()
            .any(|item| item.name == "loom.fs.write.v1"));
        assert!(registry
            .capabilities
            .iter()
            .any(|item| item.name == "loom.llm.inference.v1"));
        assert!(registry
            .capabilities
            .iter()
            .any(|item| item.name == "loom.kv.get.v1"));
        assert!(registry
            .capabilities
            .iter()
            .any(|item| item.name == "loom.kv.set.v1"));
    }

    #[test]
    fn scaffold_custom_python_capability_creates_manifest_and_worker() {
        let root = temp_path("loom-cap-custom");
        let config = sample_config();
        ensure_capability_registry_scaffold(&root, &config).expect("registry scaffold");
        let result = scaffold_capability(
            &root,
            &config,
            &CapabilityScaffoldRequest {
                name: "local.custom.echo".to_string(),
                description: "custom echo".to_string(),
                action_type: "respond".to_string(),
                resource: "capability:local.custom.echo".to_string(),
                worker_kind: "python".to_string(),
                worker_entry: String::new(),
                wasm_module: String::new(),
                payload_mode: "json".to_string(),
            },
        )
        .expect("scaffold custom capability");
        assert!(result.manifest_path.exists());
        assert!(result.worker_path.expect("worker path").exists());
        let resolved = find_capability_by_name(&root, &config, "local.custom.echo")
            .expect("resolve capability")
            .expect("capability present");
        assert_eq!(resolved.worker_kind, "python");
    }

    #[test]
    fn resolve_capability_matches_by_name_or_action_resource() {
        let root = temp_path("loom-cap-resolve");
        let config = sample_config();
        ensure_capability_registry_scaffold(&root, &config).expect("registry scaffold");
        let by_name = resolve_capability_for_request(
            &root,
            &config,
            Some("loom.echo.v1"),
            "ignored",
            "ignored",
        )
        .expect("resolve by name")
        .expect("capability by name");
        assert_eq!(by_name.resource, "capability:loom.echo.v1");
        let by_request = resolve_capability_for_request(
            &root,
            &config,
            None,
            "compute",
            "capability:loom.wasm.minimal.v1",
        )
        .expect("resolve by request")
        .expect("capability by request");
        assert_eq!(by_request.worker_kind, "wasm");
        let browser = resolve_capability_for_request(
            &root,
            &config,
            None,
            "browse",
            "capability:loom.browser.navigate.v1",
        )
        .expect("resolve browser capability")
        .expect("browser capability by request");
        assert_eq!(browser.wasm_module, "builtin:browser.navigate");
    }

    #[test]
    fn import_legacy_v1_plugin_skill_subset_imports_immediate_child_skills_and_tracks_unsupported_items(
    ) {
        let root = temp_path("loom-legacy_v1-import-root");
        let config = sample_config();
        ensure_capability_registry_scaffold(&root, &config).expect("registry scaffold");

        let plugin_root = temp_path("loom-legacy_v1-plugin");
        fs::create_dir_all(plugin_root.join("skills/alpha/nested"))
            .expect("create plugin skill dirs");
        fs::write(plugin_root.join("package.json"), "{\"name\":\"acme\"}\n")
            .expect("write package manifest");
        write_legacy_v1_plugin_manifest(&plugin_root, r#""skills""#);
        write_skill_doc(
            &plugin_root.join("skills/alpha"),
            "alpha-review",
            "Alpha review skill",
        );
        fs::create_dir_all(plugin_root.join("skills/beta")).expect("create beta dir");
        fs::write(
            plugin_root.join("skills/beta/SKILL.md"),
            r#"---
name: beta-review
---

# Beta Review
"#,
        )
        .expect("write invalid skill doc");
        write_skill_doc(
            &plugin_root.join("skills/alpha/nested"),
            "nested-review",
            "Nested review skill",
        );

        let result = import_legacy_v1_plugin_skill_subset(&root, &config, &plugin_root)
            .expect("import plugin skills");
        assert_eq!(result.plugin_id, "acme-plugin");
        assert_eq!(result.skills_roots.len(), 1);
        assert_eq!(result.imported_skills.len(), 1);
        assert!(result
            .unsupported_items
            .iter()
            .any(|item| item.reason == "package_json_not_supported"));
        assert!(result
            .unsupported_items
            .iter()
            .any(|item| item.reason == "missing_skill_description"));
        assert!(result
            .unsupported_items
            .iter()
            .all(|item| !item.path.contains("nested")));

        let imported = &result.imported_skills[0];
        assert_eq!(
            imported.capability.name,
            "loomskill.acme-plugin.alpha-review.v0"
        );
        assert_eq!(imported.capability.description, "Alpha review skill");
        assert_eq!(imported.normalized_metadata.plugin_id, "acme-plugin");
        assert_eq!(imported.normalized_metadata.skill_name, "alpha-review");
        assert_eq!(
            imported.normalized_metadata.skill_description,
            "Alpha review skill"
        );
        assert_eq!(
            imported.normalized_metadata.import_scope,
            "immediate_child_skill_dir"
        );
        assert_eq!(
            imported.normalized_metadata.capability_name,
            "loomskill.acme-plugin.alpha-review.v0"
        );
        assert!(imported.manifest_path.exists());
        assert!(imported.worker_path.exists());
        let human = render_legacy_v1_plugin_import_human(&result);
        assert!(human.contains("worker_kind: python"));
        assert!(human.contains(
            "worker_entry: workers/python/imported-loomskill-acme-plugin-alpha-review-v0.py"
        ));
        assert!(human.contains("payload_mode: json"));
        assert!(human.contains("runtime_lane: python_host_process/imported_legacy_v1_plugin_skill"));
        assert!(human.contains("dependency: plugin_host_python"));
        assert!(human.contains("env_contract: host python3 + plugin skill root"));
    }

    #[test]
    fn import_legacy_v1_plugin_skill_subset_rejects_multiple_skill_roots() {
        let root = temp_path("loom-legacy_v1-multi-root");
        let config = sample_config();
        ensure_capability_registry_scaffold(&root, &config).expect("registry scaffold");

        let plugin_root = temp_path("loom-legacy_v1-plugin-multi-root");
        fs::create_dir_all(plugin_root.join("skills-one/alpha")).expect("create skills one");
        fs::create_dir_all(plugin_root.join("skills-two/beta")).expect("create skills two");
        write_legacy_v1_plugin_manifest(&plugin_root, r#"["skills-one", "skills-two"]"#);
        write_skill_doc(
            &plugin_root.join("skills-one/alpha"),
            "alpha",
            "Alpha skill",
        );
        write_skill_doc(&plugin_root.join("skills-two/beta"), "beta", "Beta skill");

        let result = import_legacy_v1_plugin_skill_subset(&root, &config, &plugin_root)
            .expect("import plugin skills");
        assert!(result.imported_skills.is_empty());
        assert!(result
            .unsupported_items
            .iter()
            .any(|item| item.reason == "multiple_skill_roots"));
    }

    #[test]
    fn import_legacy_v1_plugin_skill_subset_rejects_config_gated_skill_root() {
        let root = temp_path("loom-legacy_v1-config-gated");
        let config = sample_config();
        ensure_capability_registry_scaffold(&root, &config).expect("registry scaffold");

        let plugin_root = temp_path("loom-legacy_v1-plugin-config-gated");
        fs::create_dir_all(plugin_root.join("skills/alpha")).expect("create skills");
        write_legacy_v1_plugin_manifest(&plugin_root, r#"[{"path": "skills", "when": "beta"}]"#);
        write_skill_doc(&plugin_root.join("skills/alpha"), "alpha", "Alpha skill");

        let result = import_legacy_v1_plugin_skill_subset(&root, &config, &plugin_root)
            .expect("import plugin skills");
        assert!(result.imported_skills.is_empty());
        assert!(result
            .unsupported_items
            .iter()
            .any(|item| item.reason == "config_gated_skills_not_supported"));
    }

    #[test]
    fn import_workspace_skill_creates_manifest_and_wrapper() {
        let root = temp_path("loom-cap-import-root");
        let config = sample_config();
        ensure_capability_registry_scaffold(&root, &config).expect("registry scaffold");

        let skill_root = temp_path("loom-cap-import-skill");
        fs::create_dir_all(skill_root.join("scripts")).expect("create scripts dir");
        fs::write(
            skill_root.join("SKILL.md"),
            r#"---
name: malware-triage
description: Imported malware triage skill
---

# Malware Triage
"#,
        )
        .expect("write skill doc");
        fs::write(
            skill_root.join("scripts/triage_artifact.py"),
            r#"#!/usr/bin/env python3
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--artifact", required=True)
parser.add_argument("--out", required=True)
parser.add_argument("--skip-container", action="store_true")
"#,
        )
        .expect("write skill script");

        let result = import_workspace_skill(&root, &config, &skill_root, None, None)
            .expect("import workspace skill");
        assert!(result.manifest_path.exists());
        assert!(result.worker_path.exists());
        assert_eq!(result.detected_signature, "artifact_report_v0");
        assert_eq!(result.capability.source_kind, "legacy_v1_workspace_skill");
        assert_eq!(result.skill_shape, "workspace_python_entrypoint");
        assert_eq!(result.capability.adapter_kind, "artifact_report_v0");
        assert!(result
            .capability
            .import_provenance
            .contains("workspace_python_entrypoint"));
        assert_eq!(result.capability.action_type, "skill_exec");
        assert_eq!(
            result.capability.resource,
            "capability:loomskill.malware-triage.v0"
        );

        let registry = load_capability_registry(&root, &config).expect("load capability registry");
        let imported = registry
            .capabilities
            .into_iter()
            .find(|item| item.name == "loomskill.malware-triage.v0")
            .expect("imported capability present");
        assert_eq!(imported.source_kind, "legacy_v1_workspace_skill");
        assert!(imported.source_path.contains("loom-cap-import-skill"));
        let human = render_capability_import_human(&result);
        assert!(human.contains("worker_kind:       python"));
        assert!(human
            .contains("worker_entry:      workers/python/imported-loomskill-malware-triage-v0.py"));
        assert!(human.contains("payload_mode:      json"));
        assert!(human.contains("runtime_lane:      python_host_process/imported_workspace_skill"));
        assert!(human.contains("dependency:        workspace_host_python"));
        assert!(human.contains("env_contract:      host python3 + source skill root"));
    }

    #[test]
    fn import_workspace_skill_uses_explicit_entrypoint_for_multi_script_skills() {
        let root = temp_path("loom-cap-import-root-explicit");
        let config = sample_config();
        ensure_capability_registry_scaffold(&root, &config).expect("registry scaffold");

        let skill_root = temp_path("loom-cap-import-skill-explicit");
        fs::create_dir_all(skill_root.join("scripts")).expect("create scripts dir");
        fs::write(
            skill_root.join("SKILL.md"),
            r#"---
name: malware-triage
description: Imported malware triage skill
---

# Malware Triage
"#,
        )
        .expect("write skill doc");
        fs::write(skill_root.join("scripts/helper.py"), "import pathlib\n")
            .expect("write helper script");
        fs::write(
            skill_root.join("scripts/triage_artifact.py"),
            r#"import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--artifact", required=True)
parser.add_argument("--out", required=True)
parser.add_argument("--skip-container", action="store_true")
"#,
        )
        .expect("write skill script");

        let result = import_workspace_skill(
            &root,
            &config,
            &skill_root,
            Some("scripts/triage_artifact.py"),
            None,
        )
        .expect("import workspace skill");
        assert!(result.manifest_path.exists());
        assert!(result.worker_path.exists());
        assert_eq!(
            result.skill_script,
            skill_root.join("scripts/triage_artifact.py")
        );
        assert_eq!(result.detected_signature, "artifact_report_v0");
        assert_eq!(result.capability.source_kind, "legacy_v1_workspace_skill");
        assert_eq!(result.skill_shape, "workspace_python_entrypoint");
        assert_eq!(result.capability.adapter_kind, "artifact_report_v0");
        assert!(result
            .capability
            .import_provenance
            .contains("workspace_python_entrypoint"));
        assert_eq!(result.capability.action_type, "skill_exec");
        assert_eq!(
            result.capability.resource,
            "capability:loomskill.malware-triage.v0"
        );
    }

    #[test]
    fn import_bundle_skill_creates_manifest_and_wrapper() {
        let root = temp_path("loom-cap-import-bundle-root");
        let config = sample_config();
        ensure_capability_registry_scaffold(&root, &config).expect("registry scaffold");

        let skill_root = temp_path("loom-cap-import-bundle");
        fs::create_dir_all(skill_root.join("scripts")).expect("create scripts dir");
        fs::write(
            skill_root.join("clawskill.json"),
            r#"{
  "version": "clawfamily_skill_contract_v0",
  "name": "safe-web-research-bundle",
  "description": "Bundle manifest import",
  "entrypoint": "scripts/fetch_safe.py",
  "adapter_kind": "url_report_v0",
  "action_type": "skill_exec",
  "payload_mode": "json"
}
"#,
        )
        .expect("write bundle manifest");
        fs::write(
            skill_root.join("scripts/fetch_safe.py"),
            r#"#!/usr/bin/env python3
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--url", action="append")
parser.add_argument("--url-file")
parser.add_argument("--out")
"#,
        )
        .expect("write bundle script");

        let result = import_workspace_skill(&root, &config, &skill_root, None, None)
            .expect("import bundle skill");
        assert!(result.manifest_path.exists());
        assert!(result.worker_path.exists());
        assert_eq!(result.detected_signature, "url_report_v0");
        assert_eq!(result.skill_shape, "bundle_manifest");
        assert_eq!(result.capability.source_kind, "clawfamily_skill_bundle");
        assert_eq!(
            result.capability.source_manifest,
            skill_root.join("clawskill.json").display().to_string()
        );
        assert!(result
            .capability
            .import_provenance
            .contains("bundle_manifest"));
    }

    #[test]
    fn forge_capability_creates_candidate_manifest_and_worker() {
        let root = temp_path("loom-cap-forge");
        let config = sample_config();
        ensure_capability_registry_scaffold(&root, &config).expect("registry scaffold");

        let result = forge_capability(
            &root,
            &config,
            &CapabilityForgeRequest {
                name: "loomforge.artifact.inspect.v0".to_string(),
                description: "forged artifact inspector".to_string(),
                template: FORGE_TEMPLATE_ARTIFACT_INSPECT.to_string(),
                gap_class: String::new(),
                goal: String::new(),
            },
        )
        .expect("forge capability");
        assert!(result.manifest_path.exists());
        assert!(result.worker_path.exists());
        assert_eq!(result.capability.source_kind, "loom_forge_candidate");
        assert_eq!(
            result.capability.adapter_kind,
            "loom_forge_template/artifact_inspect_v0"
        );

        let resolved = find_capability_by_name(&root, &config, "loomforge.artifact.inspect.v0")
            .expect("resolve capability")
            .expect("capability present");
        assert_eq!(resolved.promotion_state, "candidate");
        assert_eq!(resolved.verification_status, "unverified");
    }

    #[test]
    fn forge_capability_can_resolve_from_gap_class() {
        let root = temp_path("loom-cap-forge-gap");
        let config = sample_config();
        ensure_capability_registry_scaffold(&root, &config).expect("registry scaffold");
        let result = forge_capability(
            &root,
            &config,
            &CapabilityForgeRequest {
                name: "loomforge.url.collect.v0".to_string(),
                description: String::new(),
                template: String::new(),
                gap_class: "url_collection".to_string(),
                goal: "collect domains from urls".to_string(),
            },
        )
        .expect("forge from gap class");
        assert_eq!(result.template, FORGE_TEMPLATE_URL_BUNDLE);
        assert!(result
            .capability
            .description
            .contains("goal: collect domains from urls"));
    }

    #[test]
    fn verification_and_promotion_update_custom_manifest() {
        let root = temp_path("loom-cap-verify-promote");
        let config = sample_config();
        ensure_capability_registry_scaffold(&root, &config).expect("registry scaffold");
        scaffold_capability(
            &root,
            &config,
            &CapabilityScaffoldRequest {
                name: "local.custom.verify".to_string(),
                description: "custom verify".to_string(),
                action_type: "respond".to_string(),
                resource: "capability:local.custom.verify".to_string(),
                worker_kind: "python".to_string(),
                worker_entry: String::new(),
                wasm_module: String::new(),
                payload_mode: "json".to_string(),
            },
        )
        .expect("scaffold");

        let verified = update_capability_verification(
            &root,
            &config,
            "local.custom.verify",
            "verified",
            "1234567890",
            "job::verify",
            "execution::verify",
            "runtime execution completed",
        )
        .expect("update verification");
        assert_eq!(verified.capability.verification_status, "verified");

        let promoted = promote_capability(&root, &config, "local.custom.verify", "1234567891")
            .expect("promote capability");
        assert_eq!(promoted.capability.promotion_state, "promoted");
        assert_eq!(promoted.capability.promoted_at, "1234567891");
    }

    #[test]
    fn capability_gap_record_tracks_forge_verify_promote_states() {
        let root = temp_path("loom-cap-gap");
        let config = sample_config();
        ensure_capability_registry_scaffold(&root, &config).expect("registry scaffold");

        let gap = record_capability_gap(
            &root,
            &config,
            &CapabilityGapRequest {
                request_id: String::new(),
                requested_via: "action_execute".to_string(),
                capability_name: "loomforge.artifact-triage.demo.v0".to_string(),
                gap_class: "artifact_triage".to_string(),
                goal: "suspicious artifact triage".to_string(),
                proposed_capability_name: "loomforge.artifact-triage.demo.v0".to_string(),
                agent_id: "agent_tutorial".to_string(),
                org_id: "org_tutorial".to_string(),
                kernel_path: "/tmp/kernel".to_string(),
                action_type: String::new(),
                resource: String::new(),
                payload_json: r#"{"artifact_path":"/tmp/sample.bin"}"#.to_string(),
                run_id: String::new(),
                session_id: String::new(),
                original_request_json: String::new(),
            },
        )
        .expect("record gap");
        assert_eq!(gap.gap.forge_status, "missing_request_recorded");

        let forged = update_capability_gap_forge(
            &root,
            &config,
            &gap.gap.gap_id,
            &root.join("capabilities/custom/demo.json"),
            "candidate forged",
        )
        .expect("update forge");
        assert_eq!(forged.gap.forge_status, "candidate_forged");

        let verified = update_capability_gap_verification(
            &root,
            &config,
            &gap.gap.gap_id,
            "verified",
            "job::verify",
            "execution::verify",
            "verification matched expectations",
        )
        .expect("update verify");
        assert_eq!(verified.gap.verification_status, "verified");
        assert_eq!(
            verified.gap.verification_note,
            "verification matched expectations"
        );
        assert!(!verified.gap.verified_at.is_empty());

        let promoted = update_capability_gap_promotion(
            &root,
            &config,
            &gap.gap.gap_id,
            "promoted",
            "promotion succeeded",
        )
        .expect("update promote");
        assert_eq!(promoted.gap.promotion_status, "promoted");
        assert_eq!(promoted.gap.promotion_note, "promotion succeeded");
        assert!(!promoted.gap.promoted_at.is_empty());

        let persisted = load_capability_gap(&root, &config, &gap.gap.gap_id).expect("reload gap");
        assert_eq!(persisted.verification_note, verified.gap.verification_note);
        assert_eq!(persisted.verified_at, verified.gap.verified_at);
        assert_eq!(persisted.promotion_note, promoted.gap.promotion_note);
        assert_eq!(persisted.promoted_at, promoted.gap.promoted_at);
    }

    #[test]
    fn capability_gap_record_persists_verification_and_promotion_evidence() {
        let root = temp_path("loom-cap-gap-evidence");
        let config = sample_config();
        ensure_capability_registry_scaffold(&root, &config).expect("registry scaffold");

        let gap = record_capability_gap(
            &root,
            &config,
            &CapabilityGapRequest {
                request_id: String::new(),
                requested_via: "action_execute".to_string(),
                capability_name: "loomforge.artifact-triage.demo.v0".to_string(),
                gap_class: "artifact_triage".to_string(),
                goal: "suspicious artifact triage".to_string(),
                proposed_capability_name: "loomforge.artifact-triage.demo.v0".to_string(),
                agent_id: "agent_tutorial".to_string(),
                org_id: "org_tutorial".to_string(),
                kernel_path: "/tmp/kernel".to_string(),
                action_type: String::new(),
                resource: String::new(),
                payload_json: r#"{"artifact_path":"/tmp/sample.bin"}"#.to_string(),
                run_id: String::new(),
                session_id: String::new(),
                original_request_json: String::new(),
            },
        )
        .expect("record gap");

        let verified = update_capability_gap_verification(
            &root,
            &config,
            &gap.gap.gap_id,
            "verified",
            "job::verify",
            "execution::verify",
            "verification matched expectations",
        )
        .expect("update verify");
        let promoted = update_capability_gap_promotion(
            &root,
            &config,
            &gap.gap.gap_id,
            "promoted",
            "promotion succeeded",
        )
        .expect("update promote");

        let persisted = load_capability_gap(&root, &config, &gap.gap.gap_id).expect("reload gap");
        assert_eq!(persisted.verification_status, "verified");
        assert_eq!(
            persisted.verification_note,
            "verification matched expectations"
        );
        assert_eq!(persisted.verified_at, verified.gap.verified_at);
        assert_eq!(persisted.promotion_status, "promoted");
        assert_eq!(persisted.promotion_note, "promotion succeeded");
        assert_eq!(persisted.promoted_at, promoted.gap.promoted_at);
    }

    #[test]
    fn capability_gap_show_json_includes_replay_request_fixture() {
        let root = temp_path("loom-cap-gap-replay");
        let config = sample_config();
        ensure_capability_registry_scaffold(&root, &config).expect("registry scaffold");

        let gap = record_capability_gap(
            &root,
            &config,
            &CapabilityGapRequest {
                request_id: "request::replay::demo".to_string(),
                requested_via: "action_execute".to_string(),
                capability_name: "loomforge.artifact-triage.demo.v0".to_string(),
                gap_class: "artifact_triage".to_string(),
                goal: "suspicious artifact triage".to_string(),
                proposed_capability_name: "loomforge.artifact-triage.demo.v0".to_string(),
                agent_id: "agent_tutorial".to_string(),
                org_id: "org_tutorial".to_string(),
                kernel_path: "/tmp/kernel".to_string(),
                action_type: "artifact_inspect".to_string(),
                resource: "capability:loomforge.artifact-triage.demo.v0".to_string(),
                payload_json: r#"{"artifact_path":"/tmp/sample.bin"}"#.to_string(),
                run_id: "run::replay::demo".to_string(),
                session_id: "session::replay::demo".to_string(),
                original_request_json: String::new(),
            },
        )
        .expect("record gap");

        let json_output = render_capability_gap_json(&gap);
        let value: Value = serde_json::from_str(&json_output).expect("parse gap json");
        let replay = value
            .get("gap")
            .and_then(Value::as_object)
            .and_then(|gap| gap.get("replay_request"))
            .and_then(Value::as_object)
            .expect("replay request");

        assert_eq!(
            replay.get("request_id").and_then(Value::as_str),
            Some("request::replay::demo")
        );
        assert_eq!(
            replay.get("requested_via").and_then(Value::as_str),
            Some("action_execute")
        );
        assert_eq!(
            replay.get("capability_name").and_then(Value::as_str),
            Some("loomforge.artifact-triage.demo.v0")
        );
        assert_eq!(
            replay.get("gap_class").and_then(Value::as_str),
            Some("artifact_triage")
        );
        assert_eq!(
            replay.get("goal").and_then(Value::as_str),
            Some("suspicious artifact triage")
        );
        assert_eq!(
            replay.get("payload_json").and_then(Value::as_str),
            Some(r#"{"artifact_path":"/tmp/sample.bin"}"#)
        );
        assert_eq!(
            replay.get("run_id").and_then(Value::as_str),
            Some("run::replay::demo")
        );
        assert_eq!(
            replay.get("session_id").and_then(Value::as_str),
            Some("session::replay::demo")
        );
        assert!(value
            .get("gap")
            .and_then(Value::as_object)
            .and_then(|gap| gap.get("original_request_json"))
            .and_then(Value::as_str)
            .map(|raw| raw.contains("request::replay::demo"))
            .unwrap_or(false));

        let human = render_capability_gap_human(&gap);
        assert!(human.contains("replay_request:      supported (requested_via=action_execute)"));
    }

    #[test]
    fn capability_gap_replay_request_reconstructs_action_execute_fixture() {
        let root = temp_path("loom-cap-gap-replay-request");
        let config = sample_config();
        ensure_capability_registry_scaffold(&root, &config).expect("registry scaffold");

        let gap = record_capability_gap(
            &root,
            &config,
            &CapabilityGapRequest {
                request_id: "request::replay::roundtrip::demo".to_string(),
                requested_via: "action_execute".to_string(),
                capability_name: "loomforge.artifact-triage.demo.v0".to_string(),
                gap_class: "artifact_triage".to_string(),
                goal: "suspicious artifact triage".to_string(),
                proposed_capability_name: "loomforge.artifact-triage.demo.v0".to_string(),
                agent_id: "agent_tutorial".to_string(),
                org_id: "org_tutorial".to_string(),
                kernel_path: "/tmp/kernel".to_string(),
                action_type: "artifact_inspect".to_string(),
                resource: "capability:loomforge.artifact-triage.demo.v0".to_string(),
                payload_json: r#"{"artifact_path":"/tmp/sample.bin"}"#.to_string(),
                run_id: "run::replay::demo".to_string(),
                session_id: "session::replay::demo".to_string(),
                original_request_json: String::new(),
            },
        )
        .expect("record gap");

        let replay = capability_gap_replay_request(&gap.gap).expect("replay request");
        assert_eq!(replay.requested_via, "action_execute");
        assert_eq!(replay.capability_name, "loomforge.artifact-triage.demo.v0");
        assert_eq!(replay.action_type, "artifact_inspect");
        assert_eq!(
            replay.resource,
            "capability:loomforge.artifact-triage.demo.v0"
        );
        assert_eq!(
            replay.payload_json,
            r#"{"artifact_path":"/tmp/sample.bin"}"#
        );
        assert_eq!(replay.original_request_json, gap.gap.original_request_json);
    }

    #[test]
    fn capability_gap_replay_request_rejects_service_submit_fixture() {
        let root = temp_path("loom-cap-gap-replay-service");
        let config = sample_config();
        ensure_capability_registry_scaffold(&root, &config).expect("registry scaffold");

        let gap = record_capability_gap(
            &root,
            &config,
            &CapabilityGapRequest {
                request_id: "request::replay::service::demo".to_string(),
                requested_via: "service_submit".to_string(),
                capability_name: "loomforge.artifact-triage.demo.v0".to_string(),
                gap_class: "artifact_triage".to_string(),
                goal: "suspicious artifact triage".to_string(),
                proposed_capability_name: "loomforge.artifact-triage.demo.v0".to_string(),
                agent_id: "agent_tutorial".to_string(),
                org_id: "org_tutorial".to_string(),
                kernel_path: "/tmp/kernel".to_string(),
                action_type: "artifact_inspect".to_string(),
                resource: "capability:loomforge.artifact-triage.demo.v0".to_string(),
                payload_json: r#"{"artifact_path":"/tmp/sample.bin"}"#.to_string(),
                run_id: "run::replay::demo".to_string(),
                session_id: "session::replay::demo".to_string(),
                original_request_json: String::new(),
            },
        )
        .expect("record gap");

        let error = capability_gap_replay_request(&gap.gap).expect_err("unsupported replay");
        assert!(error.contains("requested_via=action_execute"));
    }
}
