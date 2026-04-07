use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use crate::agent_runtime::{
    ensure_agent_runtime_scaffold, load_agent_runtime_registry, AgentRuntimeProfile,
};
use crate::LoomResult;

pub const DEFAULT_CONTEXT_ENGINE_REGISTRY_PATH: &str = "state/context-engine/registry.json";
pub const DEFAULT_CONTEXT_OVERLAYS_DIR: &str = "state/context-engine/overlays";

const GLOBAL_CONTEXT_DIR: &str = "context/global";
const GLOBAL_PRECEDENCE: u32 = 100;
const AGENT_PRECEDENCE: u32 = 200;
const SESSION_OVERLAY_PRECEDENCE: u32 = 300;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ContextLayerRecord {
    pub layer_id: String,
    pub section: String,
    pub scope_kind: String,
    pub agent_id: Option<String>,
    pub path: String,
    pub precedence: u32,
    pub mutable: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ContextEngineOverview {
    pub registry_path: PathBuf,
    pub overlay_root: PathBuf,
    pub layer_count: usize,
    pub section_count: usize,
    pub mutable_count: usize,
    pub sections: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ContextBundle {
    pub agent_id: String,
    pub role: String,
    pub session_id: Option<String>,
    pub sections: BTreeMap<String, String>,
    pub section_sources: BTreeMap<String, Vec<String>>,
    pub merged_layer_count: usize,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ContextOverlayWriteResult {
    pub overlay_path: PathBuf,
    pub agent_id: String,
    pub session_id: String,
    pub section: String,
    pub byte_count: usize,
}

pub fn context_engine_registry_path(root: &Path) -> PathBuf {
    root.join(DEFAULT_CONTEXT_ENGINE_REGISTRY_PATH)
}

pub fn context_engine_overlay_root(root: &Path) -> PathBuf {
    root.join(DEFAULT_CONTEXT_OVERLAYS_DIR)
}

pub fn ensure_context_engine_scaffold(root: &Path) -> LoomResult<PathBuf> {
    ensure_agent_runtime_scaffold(root)?;
    let registry_path = context_engine_registry_path(root);
    if let Some(parent) = registry_path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    fs::create_dir_all(context_engine_overlay_root(root)).map_err(io_err)?;
    if !registry_path.exists() {
        sync_context_registry(root)?;
    }
    Ok(registry_path)
}

pub fn sync_context_registry(root: &Path) -> LoomResult<ContextEngineOverview> {
    ensure_agent_runtime_scaffold(root)?;
    let registry_path = context_engine_registry_path(root);
    if let Some(parent) = registry_path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    fs::create_dir_all(context_engine_overlay_root(root)).map_err(io_err)?;

    let profiles = load_agent_runtime_registry(root)?;
    let mut layers = vec![
        global_layer("soul", "SOUL.md", false),
        global_layer("user", "USER.md", false),
        global_layer("tools", "TOOLS.md", false),
        global_layer("heartbeat", "HEARTBEAT.md", false),
        global_layer("agents", "AGENTS.md", false),
    ];
    for profile in &profiles {
        layers.extend(agent_layers(profile));
    }

    let rendered = serde_json::to_string_pretty(&json!({
        "version": 1,
        "layers": layers.iter().map(layer_json).collect::<Vec<_>>(),
    }))
    .map_err(|error| error.to_string())?
        + "\n";
    fs::write(&registry_path, rendered).map_err(io_err)?;

    context_engine_overview(root)
}

pub fn context_engine_overview(root: &Path) -> LoomResult<ContextEngineOverview> {
    let registry_path = context_engine_registry_path(root);
    let layers = load_context_layers(root)?;
    let mut sections = BTreeSet::new();
    for layer in &layers {
        sections.insert(layer.section.clone());
    }
    Ok(ContextEngineOverview {
        registry_path,
        overlay_root: context_engine_overlay_root(root),
        layer_count: layers.len(),
        section_count: sections.len(),
        mutable_count: layers.iter().filter(|layer| layer.mutable).count(),
        sections: sections.into_iter().collect(),
    })
}

pub fn context_bundle(
    root: &Path,
    agent_id: &str,
    session_id: Option<&str>,
) -> LoomResult<ContextBundle> {
    ensure_context_engine_scaffold(root)?;
    let profile = resolve_agent_profile(root, agent_id)?;
    let layers = load_context_layers(root)?;
    let mut grouped: BTreeMap<String, Vec<ContextLayerRecord>> = BTreeMap::new();
    for layer in layers {
        if layer.scope_kind == "global"
            || layer.agent_id.as_deref() == Some(profile.agent_id.as_str())
        {
            grouped
                .entry(layer.section.clone())
                .or_default()
                .push(layer);
        }
    }

    let mut sections = BTreeMap::new();
    let mut section_sources = BTreeMap::new();
    let mut merged_layer_count = 0usize;
    let session_id = trim_to_option(session_id);

    for (section, mut section_layers) in grouped {
        section_layers.sort_by(|left, right| left.precedence.cmp(&right.precedence));
        let mut rendered = String::new();
        let mut sources = Vec::new();
        for layer in section_layers {
            let path = root.join(&layer.path);
            if !path.exists() {
                continue;
            }
            let raw = fs::read_to_string(&path).map_err(io_err)?;
            if raw.trim().is_empty() {
                continue;
            }
            if !rendered.is_empty() {
                rendered.push_str("\n\n");
            }
            rendered.push_str(raw.trim());
            sources.push(path.display().to_string());
            merged_layer_count += 1;
        }
        if let Some(session_id) = session_id.as_deref() {
            let overlay_path = context_overlay_path(root, &profile.agent_id, session_id, &section);
            if overlay_path.exists() {
                let raw = fs::read_to_string(&overlay_path).map_err(io_err)?;
                if !raw.trim().is_empty() {
                    if !rendered.is_empty() {
                        rendered.push_str("\n\n");
                    }
                    rendered.push_str(raw.trim());
                    sources.push(format!(
                        "{}#precedence={}",
                        overlay_path.display(),
                        SESSION_OVERLAY_PRECEDENCE
                    ));
                    merged_layer_count += 1;
                }
            }
        }
        if !rendered.is_empty() {
            sections.insert(section.clone(), rendered);
            section_sources.insert(section, sources);
        }
    }

    Ok(ContextBundle {
        agent_id: profile.agent_id,
        role: profile.role,
        session_id,
        sections,
        section_sources,
        merged_layer_count,
    })
}

pub fn write_context_overlay(
    root: &Path,
    agent_id: &str,
    session_id: &str,
    section: &str,
    content: &str,
) -> LoomResult<ContextOverlayWriteResult> {
    let profile = resolve_agent_profile(root, agent_id)?;
    let session_id =
        trim_to_option(Some(session_id)).ok_or_else(|| "session_id is required".to_string())?;
    let section = normalize_section(section)?;
    let overlay_path = context_overlay_path(root, &profile.agent_id, &session_id, &section);
    if let Some(parent) = overlay_path.parent() {
        fs::create_dir_all(parent).map_err(io_err)?;
    }
    let normalized = content.trim();
    if normalized.is_empty() {
        return Err("overlay content must not be empty".to_string());
    }
    fs::write(&overlay_path, format!("{}\n", normalized)).map_err(io_err)?;
    Ok(ContextOverlayWriteResult {
        overlay_path,
        agent_id: profile.agent_id,
        session_id,
        section,
        byte_count: normalized.len(),
    })
}

pub fn render_context_engine_overview_human(summary: &ContextEngineOverview) -> String {
    format!(
        "registry_path:     {}\noverlay_root:      {}\nlayer_count:       {}\nsection_count:     {}\nmutable_count:     {}\nsections:          {}\n",
        summary.registry_path.display(),
        summary.overlay_root.display(),
        summary.layer_count,
        summary.section_count,
        summary.mutable_count,
        if summary.sections.is_empty() {
            "(none)".to_string()
        } else {
            summary.sections.join(",")
        }
    )
}

pub fn render_context_engine_overview_json(summary: &ContextEngineOverview) -> String {
    serde_json::to_string_pretty(&json!({
        "registry_path": summary.registry_path.display().to_string(),
        "overlay_root": summary.overlay_root.display().to_string(),
        "layer_count": summary.layer_count,
        "section_count": summary.section_count,
        "mutable_count": summary.mutable_count,
        "sections": summary.sections,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_context_bundle_human(bundle: &ContextBundle) -> String {
    let mut rendered = format!(
        "agent_id:          {}\nrole:              {}\nsession_id:        {}\nsection_count:     {}\nmerged_layers:     {}\n",
        bundle.agent_id,
        bundle.role,
        bundle.session_id.as_deref().unwrap_or("(none)"),
        bundle.sections.len(),
        bundle.merged_layer_count,
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

pub fn render_context_bundle_json(bundle: &ContextBundle) -> String {
    serde_json::to_string_pretty(&json!({
        "agent_id": bundle.agent_id,
        "role": bundle.role,
        "session_id": bundle.session_id,
        "section_count": bundle.sections.len(),
        "merged_layer_count": bundle.merged_layer_count,
        "sections": bundle.sections,
        "section_sources": bundle.section_sources,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

pub fn render_context_overlay_write_human(result: &ContextOverlayWriteResult) -> String {
    format!(
        "overlay_path:      {}\nagent_id:          {}\nsession_id:        {}\nsection:           {}\nbyte_count:        {}\n",
        result.overlay_path.display(),
        result.agent_id,
        result.session_id,
        result.section,
        result.byte_count,
    )
}

pub fn render_context_overlay_write_json(result: &ContextOverlayWriteResult) -> String {
    serde_json::to_string_pretty(&json!({
        "overlay_path": result.overlay_path.display().to_string(),
        "agent_id": result.agent_id,
        "session_id": result.session_id,
        "section": result.section,
        "byte_count": result.byte_count,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

fn load_context_layers(root: &Path) -> LoomResult<Vec<ContextLayerRecord>> {
    ensure_context_engine_scaffold(root)?;
    let raw = fs::read_to_string(context_engine_registry_path(root)).map_err(io_err)?;
    let value: Value = serde_json::from_str(&raw)
        .map_err(|error| format!("invalid context engine registry json: {error}"))?;
    let layers = value
        .get("layers")
        .and_then(Value::as_array)
        .ok_or_else(|| "context engine registry missing layers array".to_string())?;
    let mut records = Vec::new();
    for layer in layers {
        records.push(parse_layer(layer)?);
    }
    Ok(records)
}

fn parse_layer(value: &Value) -> LoomResult<ContextLayerRecord> {
    Ok(ContextLayerRecord {
        layer_id: required_string(value.get("layer_id"), "layer_id")?,
        section: required_string(value.get("section"), "section")?,
        scope_kind: required_string(value.get("scope_kind"), "scope_kind")?,
        agent_id: optional_string(value.get("agent_id")),
        path: required_string(value.get("path"), "path")?,
        precedence: value.get("precedence").and_then(Value::as_u64).unwrap_or(0) as u32,
        mutable: value
            .get("mutable")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    })
}

fn layer_json(layer: &ContextLayerRecord) -> Value {
    json!({
        "layer_id": layer.layer_id,
        "section": layer.section,
        "scope_kind": layer.scope_kind,
        "agent_id": layer.agent_id,
        "path": layer.path,
        "precedence": layer.precedence,
        "mutable": layer.mutable,
    })
}

fn global_layer(section: &str, filename: &str, mutable: bool) -> ContextLayerRecord {
    ContextLayerRecord {
        layer_id: format!("global:{}", section),
        section: section.to_string(),
        scope_kind: "global".to_string(),
        agent_id: None,
        path: format!("{}/{}", GLOBAL_CONTEXT_DIR, filename),
        precedence: GLOBAL_PRECEDENCE,
        mutable,
    }
}

fn agent_layers(profile: &AgentRuntimeProfile) -> Vec<ContextLayerRecord> {
    vec![
        ContextLayerRecord {
            layer_id: format!("agent:{}:soul", profile.agent_id),
            section: "soul".to_string(),
            scope_kind: "agent".to_string(),
            agent_id: Some(profile.agent_id.clone()),
            path: format!("{}/SOUL.md", profile.workspace_root),
            precedence: AGENT_PRECEDENCE,
            mutable: true,
        },
        ContextLayerRecord {
            layer_id: format!("agent:{}:memory", profile.agent_id),
            section: "memory".to_string(),
            scope_kind: "agent".to_string(),
            agent_id: Some(profile.agent_id.clone()),
            path: format!("{}/MEMORY.md", profile.workspace_root),
            precedence: AGENT_PRECEDENCE,
            mutable: true,
        },
        ContextLayerRecord {
            layer_id: format!("agent:{}:tools", profile.agent_id),
            section: "tools".to_string(),
            scope_kind: "agent".to_string(),
            agent_id: Some(profile.agent_id.clone()),
            path: format!("{}/TOOLS.md", profile.workspace_root),
            precedence: AGENT_PRECEDENCE,
            mutable: true,
        },
        ContextLayerRecord {
            layer_id: format!("agent:{}:heartbeat", profile.agent_id),
            section: "heartbeat".to_string(),
            scope_kind: "agent".to_string(),
            agent_id: Some(profile.agent_id.clone()),
            path: format!("{}/HEARTBEAT.md", profile.workspace_root),
            precedence: AGENT_PRECEDENCE,
            mutable: true,
        },
    ]
}

fn resolve_agent_profile(root: &Path, agent_id: &str) -> LoomResult<AgentRuntimeProfile> {
    ensure_agent_runtime_scaffold(root)?;
    let normalized =
        trim_to_option(Some(agent_id)).ok_or_else(|| "agent_id is required".to_string())?;
    load_agent_runtime_registry(root)?
        .into_iter()
        .find(|profile| profile.agent_id == normalized)
        .ok_or_else(|| format!("unknown agent_id '{}'", normalized))
}

fn context_overlay_path(root: &Path, agent_id: &str, session_id: &str, section: &str) -> PathBuf {
    context_engine_overlay_root(root)
        .join(agent_id)
        .join(session_id)
        .join(format!("{}.md", section))
}

fn normalize_section(section: &str) -> LoomResult<String> {
    let value = section.trim().to_ascii_lowercase();
    if value.is_empty() {
        return Err("section is required".to_string());
    }
    match value.as_str() {
        "soul" | "user" | "tools" | "heartbeat" | "agents" | "memory" => Ok(value),
        _ => Err(format!("unsupported context section '{}'", section)),
    }
}

fn trim_to_option(value: Option<&str>) -> Option<String> {
    value
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(|value| value.to_string())
}

fn optional_string(value: Option<&Value>) -> Option<String> {
    value
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(|value| value.to_string())
}

fn required_string(value: Option<&Value>, label: &str) -> LoomResult<String> {
    optional_string(value).ok_or_else(|| format!("{} must not be empty", label))
}

fn io_err(error: std::io::Error) -> String {
    error.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

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
    fn sync_context_registry_materializes_layers() {
        let root = temp_path("loom-context-engine-sync");
        let overview = sync_context_registry(&root).expect("sync context registry");
        assert!(overview.layer_count >= 5);
        assert!(overview.sections.iter().any(|section| section == "soul"));
        assert!(context_engine_registry_path(&root).exists());
    }

    #[test]
    fn context_bundle_merges_global_agent_and_overlay_layers() {
        let root = temp_path("loom-context-engine-bundle");
        sync_context_registry(&root).expect("sync context registry");
        let overlay = write_context_overlay(
            &root,
            "atlas",
            "session-demo",
            "memory",
            "- Session override: prioritize pricing deltas",
        )
        .expect("write overlay");
        assert!(overlay.overlay_path.exists());
        let bundle = context_bundle(&root, "atlas", Some("session-demo")).expect("context bundle");
        assert_eq!(bundle.agent_id, "atlas");
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
            .contains("Session override"));
        assert!(bundle
            .section_sources
            .get("memory")
            .map(|sources| sources
                .iter()
                .any(|source| source.contains("session-demo/memory.md")))
            .unwrap_or(false));
    }
}
