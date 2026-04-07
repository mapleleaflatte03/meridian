//! Memory service and repository seam.
//!
//! This module formalizes the boundary between memory storage (the repo — a
//! per-agent directory of governed memory files) and memory operations (the
//! service — search, write, prune, and governance checks).
//!
//! The repo is the truth. The service is the access pattern. Context engine
//! layers can read from the repo, but all writes go through the service to
//! enforce governance (retention policy, size limits, agent isolation).

use std::collections::{HashMap, HashSet, VecDeque};
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use loom_poge::{HostCallEvent, HostCallKind, PoGEInterceptor};
use rayon::prelude::*;
use serde_json::{json, Value};

use crate::LoomResult;

const MEMORY_ROOT_DIR: &str = "state/memory";
const MEMORY_INDEX_FILE: &str = "index.json";
const MEMORY_RECEIPTS_FILE: &str = "receipts.jsonl";
const DEFAULT_MAX_ENTRIES_PER_AGENT: usize = 500;
const DEFAULT_MAX_ENTRY_BYTES: usize = 16_384;
const DEFAULT_RETENTION_DAYS: u64 = 365;

// ───── Repo types ─────

/// A single memory entry in the repo.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MemoryEntry {
    pub entry_id: String,
    pub agent_id: String,
    pub category: String,
    pub key: String,
    pub content: String,
    pub created_at: u64,
    pub updated_at: u64,
    pub source: String,
    pub governed: bool,
}

impl MemoryEntry {
    pub fn to_json(&self) -> Value {
        json!({
            "entry_id": self.entry_id,
            "agent_id": self.agent_id,
            "category": self.category,
            "key": self.key,
            "content": self.content,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source": self.source,
            "governed": self.governed,
        })
    }

    pub fn from_json(value: &Value) -> LoomResult<Self> {
        Ok(Self {
            entry_id: value["entry_id"].as_str().unwrap_or("").to_string(),
            agent_id: value["agent_id"].as_str().unwrap_or("").to_string(),
            category: value["category"].as_str().unwrap_or("general").to_string(),
            key: value["key"].as_str().unwrap_or("").to_string(),
            content: value["content"].as_str().unwrap_or("").to_string(),
            created_at: value["created_at"].as_u64().unwrap_or(0),
            updated_at: value["updated_at"].as_u64().unwrap_or(0),
            source: value["source"].as_str().unwrap_or("unknown").to_string(),
            governed: value["governed"].as_bool().unwrap_or(true),
        })
    }

    pub fn byte_size(&self) -> usize {
        self.content.len() + self.key.len() + self.category.len()
    }
}

/// Index of all memory entries for one agent.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MemoryIndex {
    pub agent_id: String,
    pub entry_count: usize,
    pub categories: Vec<String>,
    pub total_bytes: usize,
    pub oldest_entry: u64,
    pub newest_entry: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MemoryReceiptRecord {
    pub timestamp_unix_ms: u64,
    pub operation: String,
    pub agent_id: String,
    pub kind: String,
    pub receipt_hash: String,
    pub input_summary: String,
    pub output_summary: String,
    pub is_error: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum MemoryLineageDirection {
    Ancestors,
    Descendants,
    Both,
}

impl MemoryLineageDirection {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Ancestors => "ancestors",
            Self::Descendants => "descendants",
            Self::Both => "both",
        }
    }

    pub fn parse(raw: &str) -> LoomResult<Self> {
        match raw.trim().to_ascii_lowercase().as_str() {
            "ancestors" => Ok(Self::Ancestors),
            "descendants" => Ok(Self::Descendants),
            "both" => Ok(Self::Both),
            other => Err(format!(
                "invalid direction '{}': expected ancestors|descendants|both",
                other
            )),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MemoryGraphNode {
    pub node_id: String,
    pub timestamp_unix_ms: u64,
    pub operation: String,
    pub category: String,
    pub key: String,
    pub source: String,
    pub output_summary: String,
    pub parent_node_id: Option<String>,
}

impl MemoryGraphNode {
    pub fn to_json(&self) -> Value {
        json!({
            "node_id": self.node_id,
            "timestamp_unix_ms": self.timestamp_unix_ms,
            "operation": self.operation,
            "category": self.category,
            "key": self.key,
            "source": self.source,
            "output_summary": self.output_summary,
            "parent_node_id": self.parent_node_id,
        })
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MemoryGraphInspectView {
    pub source_ref: String,
    pub total_nodes: usize,
    pub focus_node: Option<MemoryGraphNode>,
    pub ancestor_nodes: Vec<MemoryGraphNode>,
    pub descendant_nodes: Vec<MemoryGraphNode>,
    pub direction: MemoryLineageDirection,
    pub limit: usize,
    pub note: String,
}

impl MemoryGraphInspectView {
    pub fn to_json(&self) -> Value {
        json!({
            "status": "memory_graph_inspect",
            "source_ref": self.source_ref,
            "total_nodes": self.total_nodes,
            "focus_node": self.focus_node.as_ref().map(MemoryGraphNode::to_json),
            "ancestor_nodes": self.ancestor_nodes.iter().map(MemoryGraphNode::to_json).collect::<Vec<_>>(),
            "descendant_nodes": self.descendant_nodes.iter().map(MemoryGraphNode::to_json).collect::<Vec<_>>(),
            "direction": self.direction.as_str(),
            "limit": self.limit,
            "note": self.note,
        })
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MemoryReplaySelection {
    pub source_ref: String,
    pub focus_node_id: Option<String>,
    pub mode: String,
    pub selected_node_ids: Vec<String>,
    pub selected_category_keys: Vec<(String, String)>,
    pub selected_entries: Vec<MemoryEntry>,
    pub total_graph_nodes: usize,
    pub note: String,
}
impl MemoryReceiptRecord {
    pub fn from_json(value: &Value) -> LoomResult<Self> {
        Ok(Self {
            timestamp_unix_ms: value
                .get("timestamp_unix_ms")
                .and_then(Value::as_u64)
                .unwrap_or_default(),
            operation: value
                .get("operation")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            agent_id: value
                .get("agent_id")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            kind: value
                .get("kind")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            receipt_hash: value
                .get("receipt_hash")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            input_summary: value
                .get("input_summary")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            output_summary: value
                .get("output_summary")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            is_error: value
                .get("is_error")
                .and_then(Value::as_bool)
                .unwrap_or(false),
        })
    }

    pub fn to_json(&self) -> Value {
        json!({
            "timestamp_unix_ms": self.timestamp_unix_ms,
            "operation": self.operation,
            "agent_id": self.agent_id,
            "kind": self.kind,
            "receipt_hash": self.receipt_hash,
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "is_error": self.is_error,
        })
    }
}

// ───── Repo operations ─────

/// Memory repo — per-agent directory of governed memory files.
pub struct MemoryRepo {
    root: PathBuf,
}

impl MemoryRepo {
    pub fn new(root: &Path) -> Self {
        Self {
            root: root.join(MEMORY_ROOT_DIR),
        }
    }

    pub fn agent_dir(&self, agent_id: &str) -> PathBuf {
        self.root.join(agent_id)
    }

    pub fn agent_index_path(&self, agent_id: &str) -> PathBuf {
        self.agent_dir(agent_id).join(MEMORY_INDEX_FILE)
    }

    pub fn ensure_scaffold(&self, agent_id: &str) -> LoomResult<PathBuf> {
        let dir = self.agent_dir(agent_id);
        fs::create_dir_all(&dir).map_err(|e| format!("memory scaffold: {}", e))?;
        Ok(dir)
    }

    pub fn list_agents(&self) -> LoomResult<Vec<String>> {
        if !self.root.exists() {
            return Ok(Vec::new());
        }
        let mut agents = Vec::new();
        for entry in fs::read_dir(&self.root).map_err(|e| format!("memory root: {}", e))? {
            let entry = entry.map_err(|e| format!("memory readdir: {}", e))?;
            if entry.file_type().map(|ft| ft.is_dir()).unwrap_or(false) {
                if let Some(name) = entry.file_name().to_str() {
                    agents.push(name.to_string());
                }
            }
        }
        agents.sort();
        Ok(agents)
    }

    pub fn read_entries(&self, agent_id: &str) -> LoomResult<Vec<MemoryEntry>> {
        let index_path = self.agent_index_path(agent_id);
        if !index_path.exists() {
            return Ok(Vec::new());
        }
        let raw = fs::read_to_string(&index_path).map_err(|e| format!("memory read: {}", e))?;
        let raw = raw.trim();
        if raw.is_empty() {
            return Ok(Vec::new());
        }
        let value: Value = serde_json::from_str(raw).map_err(|e| format!("memory parse: {}", e))?;
        let entries_val = value.get("entries").and_then(|v| v.as_array());
        match entries_val {
            Some(arr) => arr.iter().map(MemoryEntry::from_json).collect(),
            None => Ok(Vec::new()),
        }
    }

    pub fn write_entries(&self, agent_id: &str, entries: &[MemoryEntry]) -> LoomResult<PathBuf> {
        self.ensure_scaffold(agent_id)?;
        let index_path = self.agent_index_path(agent_id);
        let now = current_unix();
        let entries_json: Vec<Value> = entries.iter().map(|e| e.to_json()).collect();
        let doc = json!({
            "agent_id": agent_id,
            "updated_at": now,
            "entry_count": entries.len(),
            "entries": entries_json,
        });
        let text =
            serde_json::to_string_pretty(&doc).map_err(|e| format!("memory serialize: {}", e))?;
        fs::write(&index_path, text).map_err(|e| format!("memory write: {}", e))?;
        Ok(index_path)
    }

    pub fn build_index(&self, agent_id: &str) -> LoomResult<MemoryIndex> {
        let entries = self.read_entries(agent_id)?;
        let mut categories: Vec<String> = entries.iter().map(|e| e.category.clone()).collect();
        categories.sort();
        categories.dedup();
        let total_bytes: usize = entries.iter().map(|e| e.byte_size()).sum();
        let oldest = entries.iter().map(|e| e.created_at).min().unwrap_or(0);
        let newest = entries.iter().map(|e| e.updated_at).max().unwrap_or(0);
        Ok(MemoryIndex {
            agent_id: agent_id.to_string(),
            entry_count: entries.len(),
            categories,
            total_bytes,
            oldest_entry: oldest,
            newest_entry: newest,
        })
    }
}

// ───── Service operations ─────

/// Memory service policy.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MemoryPolicy {
    pub max_entries_per_agent: usize,
    pub max_entry_bytes: usize,
    pub retention_days: u64,
    pub agent_isolation: bool,
}

impl Default for MemoryPolicy {
    fn default() -> Self {
        Self {
            max_entries_per_agent: DEFAULT_MAX_ENTRIES_PER_AGENT,
            max_entry_bytes: DEFAULT_MAX_ENTRY_BYTES,
            retention_days: DEFAULT_RETENTION_DAYS,
            agent_isolation: true,
        }
    }
}

/// Memory service — governs all access to the memory repo.
pub struct MemoryService {
    repo: MemoryRepo,
    policy: MemoryPolicy,
}

impl MemoryService {
    pub fn new(root: &Path, policy: MemoryPolicy) -> Self {
        Self {
            repo: MemoryRepo::new(root),
            policy,
        }
    }

    pub fn with_defaults(root: &Path) -> Self {
        Self::new(root, MemoryPolicy::default())
    }

    /// Write a memory entry, enforcing policy.
    pub fn write(
        &self,
        agent_id: &str,
        category: &str,
        key: &str,
        content: &str,
        source: &str,
    ) -> LoomResult<MemoryEntry> {
        let now = current_unix();
        let entry = MemoryEntry {
            entry_id: format!("mem_{}_{}", agent_id, now),
            agent_id: agent_id.to_string(),
            category: category.to_string(),
            key: key.to_string(),
            content: content.to_string(),
            created_at: now,
            updated_at: now,
            source: source.to_string(),
            governed: true,
        };

        // Policy: entry size
        if entry.byte_size() > self.policy.max_entry_bytes {
            return Err(format!(
                "memory entry exceeds size limit: {} > {}",
                entry.byte_size(),
                self.policy.max_entry_bytes
            ));
        }

        let mut entries = self.repo.read_entries(agent_id)?;

        // Policy: max entries (evict oldest if at limit)
        if entries.len() >= self.policy.max_entries_per_agent {
            entries.sort_by_key(|e| e.updated_at);
            entries.remove(0);
        }

        // Upsert by key
        let persisted_entry = if let Some(existing) = entries
            .iter_mut()
            .find(|e| e.key == key && e.category == category)
        {
            existing.content = entry.content.clone();
            existing.updated_at = now;
            existing.source = entry.source.clone();
            existing.clone()
        } else {
            entries.push(entry.clone());
            entry.clone()
        };

        self.repo.write_entries(agent_id, &entries)?;
        self.append_receipt(
            "write",
            agent_id,
            &format!("category={} key={} source={}", category, key, source),
            &format!(
                "entry_id={} bytes={} governed={}",
                persisted_entry.entry_id,
                persisted_entry.byte_size(),
                persisted_entry.governed
            ),
            false,
        )?;
        Ok(persisted_entry)
    }

    /// Search memory entries for an agent by category and/or key prefix.
    pub fn search(
        &self,
        agent_id: &str,
        category: Option<&str>,
        key_prefix: Option<&str>,
    ) -> LoomResult<Vec<MemoryEntry>> {
        let entries = self.repo.read_entries(agent_id)?;
        let filtered: Vec<MemoryEntry> = entries
            .into_iter()
            .filter(|e| {
                if let Some(cat) = category {
                    if e.category != cat {
                        return false;
                    }
                }
                if let Some(prefix) = key_prefix {
                    if !e.key.starts_with(prefix) {
                        return false;
                    }
                }
                true
            })
            .collect();
        self.append_receipt(
            "read",
            agent_id,
            &format!(
                "category={} key_prefix={}",
                category.unwrap_or("*"),
                key_prefix.unwrap_or("*")
            ),
            &format!("result_count={}", filtered.len()),
            false,
        )?;
        Ok(filtered)
    }

    /// Remove a specific entry by key.
    pub fn remove(&self, agent_id: &str, category: &str, key: &str) -> LoomResult<bool> {
        let mut entries = self.repo.read_entries(agent_id)?;
        let before = entries.len();
        entries.retain(|e| !(e.key == key && e.category == category));
        if entries.len() < before {
            self.repo.write_entries(agent_id, &entries)?;
            self.append_receipt(
                "remove",
                agent_id,
                &format!("category={} key={}", category, key),
                "removed=true",
                false,
            )?;
            Ok(true)
        } else {
            self.append_receipt(
                "remove",
                agent_id,
                &format!("category={} key={}", category, key),
                "removed=false",
                false,
            )?;
            Ok(false)
        }
    }

    /// Prune expired entries across all agents.
    pub fn prune(&self) -> LoomResult<usize> {
        let now = current_unix();
        let cutoff = now.saturating_sub(self.policy.retention_days * 86400);
        let agents = self.repo.list_agents()?;
        let mut total_pruned = 0;
        for agent_id in &agents {
            let mut entries = self.repo.read_entries(agent_id)?;
            let before = entries.len();
            entries.retain(|e| e.updated_at >= cutoff);
            if entries.len() < before {
                total_pruned += before - entries.len();
                self.repo.write_entries(agent_id, &entries)?;
            }
        }
        self.append_receipt(
            "prune",
            "memory-service",
            &format!(
                "retention_days={} cutoff={}",
                self.policy.retention_days, cutoff
            ),
            &format!("pruned_entries={}", total_pruned),
            false,
        )?;
        Ok(total_pruned)
    }

    /// Prune expired entries across all agents using parallel execution.
    ///
    /// Semantically identical to `prune()` but processes agents in parallel
    /// via rayon, reducing wall-clock time for large agent populations.
    pub fn prune_parallel(&self) -> LoomResult<usize> {
        let now = current_unix();
        let cutoff = now.saturating_sub(self.policy.retention_days * 86400);
        let agents = self.repo.list_agents()?;
        let total_pruned = AtomicUsize::new(0);
        let errors: std::sync::Mutex<Vec<String>> = std::sync::Mutex::new(Vec::new());

        agents.par_iter().for_each(|agent_id| {
            match self.repo.read_entries(agent_id) {
                Ok(mut entries) => {
                    let before = entries.len();
                    entries.retain(|e| e.updated_at >= cutoff);
                    if entries.len() < before {
                        let pruned = before - entries.len();
                        total_pruned.fetch_add(pruned, Ordering::Relaxed);
                        if let Err(e) = self.repo.write_entries(agent_id, &entries) {
                            errors.lock().unwrap().push(e);
                        }
                    }
                }
                Err(e) => {
                    errors.lock().unwrap().push(e);
                }
            }
        });

        let errs = errors.into_inner().unwrap();
        if !errs.is_empty() {
            return Err(format!("parallel prune errors: {}", errs.join("; ")));
        }
        let pruned = total_pruned.load(Ordering::Relaxed);
        self.append_receipt(
            "prune",
            "memory-service",
            &format!(
                "retention_days={} cutoff={} mode=parallel agents={}",
                self.policy.retention_days, cutoff, agents.len()
            ),
            &format!("pruned_entries={}", pruned),
            false,
        )?;
        Ok(pruned)
    }

    /// Compact an agent's memory by deduplicating entries with the same
    /// (category, key) pair, keeping only the entry with the latest `updated_at`.
    ///
    /// Returns the number of entries removed. Emits a governance receipt.
    pub fn compact(&self, agent_id: &str) -> LoomResult<usize> {
        let entries = self.repo.read_entries(agent_id)?;
        if entries.is_empty() {
            return Ok(0);
        }
        let mut best: HashMap<(String, String), MemoryEntry> = HashMap::new();
        for entry in &entries {
            let key = (entry.category.clone(), entry.key.clone());
            let existing = best.get(&key);
            if existing.is_none() || existing.unwrap().updated_at < entry.updated_at {
                best.insert(key, entry.clone());
            }
        }
        let compacted_count = entries.len().saturating_sub(best.len());
        if compacted_count == 0 {
            return Ok(0);
        }
        let mut deduplicated: Vec<MemoryEntry> = best.into_values().collect();
        deduplicated.sort_by_key(|e| (e.category.clone(), e.key.clone()));
        self.repo.write_entries(agent_id, &deduplicated)?;
        self.append_receipt(
            "compact",
            agent_id,
            &format!("before={} after={}", entries.len(), deduplicated.len()),
            &format!("removed_duplicates={}", compacted_count),
            false,
        )?;
        Ok(compacted_count)
    }

    /// Build overview for diagnostics.
    pub fn overview(&self) -> LoomResult<MemoryServiceOverview> {
        let agents = self.repo.list_agents()?;
        let mut indices = Vec::new();
        let mut total_entries = 0;
        let mut total_bytes = 0;
        for agent_id in &agents {
            let index = self.repo.build_index(agent_id)?;
            total_entries += index.entry_count;
            total_bytes += index.total_bytes;
            indices.push(index);
        }
        Ok(MemoryServiceOverview {
            agent_count: agents.len(),
            total_entries,
            total_bytes,
            indices,
            policy: self.policy.clone(),
        })
    }

    pub fn list_receipts(
        &self,
        limit: usize,
        agent_id: Option<&str>,
    ) -> LoomResult<Vec<MemoryReceiptRecord>> {
        let path = self.repo.root.join(MEMORY_RECEIPTS_FILE);
        if !path.exists() {
            return Ok(Vec::new());
        }
        let raw = fs::read_to_string(&path).map_err(|e| format!("memory receipt read: {}", e))?;
        let mut records = Vec::new();
        for line in raw.lines() {
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }
            let value: Value = serde_json::from_str(trimmed)
                .map_err(|e| format!("memory receipt parse: {}", e))?;
            let record = MemoryReceiptRecord::from_json(&value)?;
            if let Some(filter) = agent_id {
                if record.agent_id != filter {
                    continue;
                }
            }
            records.push(record);
        }
        records.sort_by_key(|record| std::cmp::Reverse(record.timestamp_unix_ms));
        if limit == 0 || records.len() <= limit {
            return Ok(records);
        }
        Ok(records.into_iter().take(limit).collect())
    }

    pub fn graph_inspect(
        &self,
        source_ref: &str,
        focus_node_id: Option<&str>,
        direction: MemoryLineageDirection,
        limit: usize,
    ) -> LoomResult<MemoryGraphInspectView> {
        let effective_limit = limit.max(1);
        let nodes = self.graph_nodes(source_ref)?;
        let total_nodes = nodes.len();
        if total_nodes == 0 {
            return Ok(MemoryGraphInspectView {
                source_ref: source_ref.to_string(),
                total_nodes,
                focus_node: None,
                ancestor_nodes: Vec::new(),
                descendant_nodes: Vec::new(),
                direction,
                limit: effective_limit,
                note: "no graph nodes available for source".to_string(),
            });
        }
        let graph_index = build_graph_index(&nodes);
        let fallback_focus = nodes
            .iter()
            .max_by_key(|node| node.timestamp_unix_ms)
            .map(|node| node.node_id.clone())
            .unwrap_or_default();
        let focus_id = focus_node_id
            .filter(|value| !value.trim().is_empty())
            .map(|value| value.to_string())
            .unwrap_or(fallback_focus);
        let focus_node = graph_index.nodes.get(&focus_id).cloned().ok_or_else(|| {
            format!(
                "focus node '{}' not found for source {}",
                focus_id, source_ref
            )
        })?;
        let ancestor_ids = if matches!(
            direction,
            MemoryLineageDirection::Ancestors | MemoryLineageDirection::Both
        ) {
            collect_ancestor_ids(&graph_index.parents, &focus_id, effective_limit)
        } else {
            Vec::new()
        };
        let descendant_ids = if matches!(
            direction,
            MemoryLineageDirection::Descendants | MemoryLineageDirection::Both
        ) {
            collect_descendant_ids(
                &graph_index.children,
                &graph_index.nodes,
                &focus_id,
                effective_limit,
            )
        } else {
            Vec::new()
        };
        let ancestor_nodes = ancestor_ids
            .iter()
            .filter_map(|node_id| graph_index.nodes.get(node_id).cloned())
            .collect::<Vec<_>>();
        let descendant_nodes = descendant_ids
            .iter()
            .filter_map(|node_id| graph_index.nodes.get(node_id).cloned())
            .collect::<Vec<_>>();
        Ok(MemoryGraphInspectView {
            source_ref: source_ref.to_string(),
            total_nodes,
            focus_node: Some(focus_node),
            ancestor_nodes,
            descendant_nodes,
            direction,
            limit: effective_limit,
            note: "compact lineage view over governed memory write/remove receipts".to_string(),
        })
    }

    pub fn select_replay_entries(
        &self,
        source_ref: &str,
        focus_node_id: Option<&str>,
        direction: MemoryLineageDirection,
        limit: usize,
    ) -> LoomResult<MemoryReplaySelection> {
        let entries = self.search(source_ref, None, None)?;
        if focus_node_id.is_none() {
            return Ok(MemoryReplaySelection {
                source_ref: source_ref.to_string(),
                focus_node_id: None,
                mode: "full_snapshot".to_string(),
                selected_node_ids: Vec::new(),
                selected_category_keys: entries
                    .iter()
                    .map(|entry| (entry.category.clone(), entry.key.clone()))
                    .collect(),
                selected_entries: entries,
                total_graph_nodes: self.graph_nodes(source_ref)?.len(),
                note: "full snapshot replay selected from source memory entries".to_string(),
            });
        }

        let graph = self.graph_inspect(source_ref, focus_node_id, direction.clone(), limit)?;
        let focus = graph
            .focus_node
            .as_ref()
            .ok_or_else(|| format!("focus node missing for source {}", source_ref))?;
        let mut selected_node_ids = vec![focus.node_id.clone()];
        if matches!(
            direction,
            MemoryLineageDirection::Ancestors | MemoryLineageDirection::Both
        ) {
            selected_node_ids.extend(graph.ancestor_nodes.iter().map(|node| node.node_id.clone()));
        }
        if matches!(
            direction,
            MemoryLineageDirection::Descendants | MemoryLineageDirection::Both
        ) {
            selected_node_ids.extend(
                graph
                    .descendant_nodes
                    .iter()
                    .map(|node| node.node_id.clone()),
            );
        }
        selected_node_ids.sort();
        selected_node_ids.dedup();

        let mut selected_key_set = HashSet::new();
        for node in std::iter::once(focus)
            .chain(graph.ancestor_nodes.iter())
            .chain(graph.descendant_nodes.iter())
        {
            selected_key_set.insert((node.category.clone(), node.key.clone()));
        }
        let selected_category_keys = selected_key_set.iter().cloned().collect::<Vec<_>>();
        let selected_entries = entries
            .into_iter()
            .filter(|entry| selected_key_set.contains(&(entry.category.clone(), entry.key.clone())))
            .collect::<Vec<_>>();

        Ok(MemoryReplaySelection {
            source_ref: source_ref.to_string(),
            focus_node_id: Some(focus.node_id.clone()),
            mode: "node_subgraph".to_string(),
            selected_node_ids,
            selected_category_keys,
            selected_entries,
            total_graph_nodes: graph.total_nodes,
            note: "selected replay set generated from focused lineage subgraph".to_string(),
        })
    }

    fn graph_nodes(&self, source_ref: &str) -> LoomResult<Vec<MemoryGraphNode>> {
        let records = self.list_receipts(0, Some(source_ref))?;
        build_graph_nodes_from_receipts(&records)
    }

    fn append_receipt(
        &self,
        operation: &str,
        agent_id: &str,
        input_summary: &str,
        output_summary: &str,
        is_error: bool,
    ) -> LoomResult<()> {
        fs::create_dir_all(&self.repo.root)
            .map_err(|e| format!("memory receipt scaffold: {}", e))?;
        let timestamp_ms = current_unix_ms();
        let event = HostCallEvent {
            kind: match operation {
                "write" | "remove" | "prune" => HostCallKind::KvPut,
                _ => HostCallKind::KvGet,
            },
            sequence: (timestamp_ms & u32::MAX as u64) as u32,
            warrant_id: synthetic_warrant_id(agent_id),
            dispatch_epoch_ms: timestamp_ms,
            input_bytes: input_summary.as_bytes(),
            output_bytes: output_summary.as_bytes(),
            is_error,
        };
        let receipt = PoGEInterceptor::receipt_for(&event).to_hex();
        let line = serde_json::to_string(&json!({
            "timestamp_unix_ms": timestamp_ms,
            "operation": operation,
            "agent_id": agent_id,
            "kind": match event.kind {
                HostCallKind::KvPut => "KvPut",
                _ => "KvGet",
            },
            "receipt_hash": receipt,
            "input_summary": input_summary,
            "output_summary": output_summary,
            "is_error": is_error,
        }))
        .map_err(|e| format!("memory receipt serialize: {}", e))?;
        let path = self.repo.root.join(MEMORY_RECEIPTS_FILE);
        let mut file = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
            .map_err(|e| format!("memory receipt open: {}", e))?;
        writeln!(file, "{}", line).map_err(|e| format!("memory receipt append: {}", e))
    }
}

/// Overview of the memory service state.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MemoryServiceOverview {
    pub agent_count: usize,
    pub total_entries: usize,
    pub total_bytes: usize,
    pub indices: Vec<MemoryIndex>,
    pub policy: MemoryPolicy,
}

impl MemoryServiceOverview {
    pub fn to_json(&self) -> Value {
        json!({
            "agent_count": self.agent_count,
            "total_entries": self.total_entries,
            "total_bytes": self.total_bytes,
            "policy": {
                "max_entries_per_agent": self.policy.max_entries_per_agent,
                "max_entry_bytes": self.policy.max_entry_bytes,
                "retention_days": self.policy.retention_days,
                "agent_isolation": self.policy.agent_isolation,
            },
            "agents": self.indices.iter().map(|idx| json!({
                "agent_id": idx.agent_id,
                "entry_count": idx.entry_count,
                "categories": idx.categories,
                "total_bytes": idx.total_bytes,
            })).collect::<Vec<_>>(),
        })
    }
}

pub fn render_memory_service_overview_human(overview: &MemoryServiceOverview) -> String {
    let mut rendered = format!(
        "agent_count:       {}\ntotal_entries:     {}\ntotal_bytes:       {}\nmax_entries:       {}\nmax_entry_bytes:   {}\nretention_days:    {}\nagent_isolation:   {}\n",
        overview.agent_count,
        overview.total_entries,
        overview.total_bytes,
        overview.policy.max_entries_per_agent,
        overview.policy.max_entry_bytes,
        overview.policy.retention_days,
        overview.policy.agent_isolation,
    );
    for index in &overview.indices {
        rendered.push_str(&format!(
            "\n[agent:{}]\nentries:          {}\nbytes:            {}\ncategories:       {}\noldest_entry:     {}\nnewest_entry:     {}\n",
            index.agent_id,
            index.entry_count,
            index.total_bytes,
            if index.categories.is_empty() {
                "(none)".to_string()
            } else {
                index.categories.join(",")
            },
            index.oldest_entry,
            index.newest_entry,
        ));
    }
    rendered
}

pub fn render_memory_service_overview_json(overview: &MemoryServiceOverview) -> String {
    serde_json::to_string_pretty(&overview.to_json()).unwrap_or_else(|_| "{}".to_string()) + "\n"
}

pub fn render_memory_entries_human(entries: &[MemoryEntry]) -> String {
    if entries.is_empty() {
        return "entry_count:       0\n".to_string();
    }
    let mut rendered = format!("entry_count:       {}\n", entries.len());
    for entry in entries {
        rendered.push_str(&format!(
            "\n[entry:{}]\nagent_id:         {}\ncategory:         {}\nkey:              {}\nsource:           {}\nupdated_at:       {}\ncontent:          {}\n",
            entry.entry_id,
            entry.agent_id,
            entry.category,
            entry.key,
            entry.source,
            entry.updated_at,
            entry.content.replace('\n', "\\n"),
        ));
    }
    rendered
}

pub fn render_memory_entries_json(entries: &[MemoryEntry]) -> String {
    serde_json::to_string_pretty(&entries.iter().map(MemoryEntry::to_json).collect::<Vec<_>>())
        .unwrap_or_else(|_| "[]".to_string())
        + "\n"
}

pub fn render_memory_receipts_human(receipts: &[MemoryReceiptRecord]) -> String {
    if receipts.is_empty() {
        return "receipt_count:     0\n".to_string();
    }
    let mut rendered = format!("receipt_count:     {}\n", receipts.len());
    for receipt in receipts {
        rendered.push_str(&format!(
            "\n[receipt:{}]\nagent_id:         {}\noperation:        {}\nkind:             {}\ntimestamp_ms:     {}\nerror:            {}\ninput:            {}\noutput:           {}\n",
            receipt.receipt_hash,
            receipt.agent_id,
            receipt.operation,
            receipt.kind,
            receipt.timestamp_unix_ms,
            receipt.is_error,
            receipt.input_summary.replace('\n', "\\n"),
            receipt.output_summary.replace('\n', "\\n"),
        ));
    }
    rendered
}

pub fn render_memory_receipts_json(receipts: &[MemoryReceiptRecord]) -> String {
    serde_json::to_string_pretty(
        &receipts
            .iter()
            .map(MemoryReceiptRecord::to_json)
            .collect::<Vec<_>>(),
    )
    .unwrap_or_else(|_| "[]".to_string())
        + "\n"
}

fn current_unix() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

fn current_unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

fn synthetic_warrant_id(agent_id: &str) -> [u8; 32] {
    let mut warrant = [0u8; 32];
    for (index, byte) in agent_id.as_bytes().iter().enumerate() {
        let slot = index % 32;
        warrant[slot] = warrant[slot]
            .wrapping_add(*byte)
            .rotate_left((slot % 7) as u32);
    }
    warrant
}

struct MemoryGraphIndex {
    nodes: HashMap<String, MemoryGraphNode>,
    parents: HashMap<String, Option<String>>,
    children: HashMap<String, Vec<String>>,
}

fn build_graph_nodes_from_receipts(
    records: &[MemoryReceiptRecord],
) -> LoomResult<Vec<MemoryGraphNode>> {
    let mut relevant = records
        .iter()
        .filter(|record| matches!(record.operation.as_str(), "write" | "remove"))
        .cloned()
        .collect::<Vec<_>>();
    relevant.sort_by_key(|record| (record.timestamp_unix_ms, record.receipt_hash.clone()));

    let mut nodes = Vec::new();
    let mut last_node_by_key: HashMap<(String, String), String> = HashMap::new();

    for record in relevant {
        let summary = parse_summary_tokens(&record.input_summary);
        let category = summary.get("category").cloned().unwrap_or_default();
        let key = summary.get("key").cloned().unwrap_or_default();
        if category.is_empty() || key.is_empty() {
            continue;
        }
        let source = summary
            .get("source")
            .cloned()
            .unwrap_or_else(|| "unknown".to_string());
        let parent_node_id = last_node_by_key
            .get(&(category.clone(), key.clone()))
            .cloned();
        let node = MemoryGraphNode {
            node_id: record.receipt_hash.clone(),
            timestamp_unix_ms: record.timestamp_unix_ms,
            operation: record.operation.clone(),
            category: category.clone(),
            key: key.clone(),
            source,
            output_summary: record.output_summary.clone(),
            parent_node_id: parent_node_id.clone(),
        };
        nodes.push(node);
        last_node_by_key.insert((category, key), record.receipt_hash);
    }
    Ok(nodes)
}

fn build_graph_index(nodes: &[MemoryGraphNode]) -> MemoryGraphIndex {
    let mut node_map = HashMap::new();
    let mut parents = HashMap::new();
    let mut children: HashMap<String, Vec<String>> = HashMap::new();
    for node in nodes {
        node_map.insert(node.node_id.clone(), node.clone());
        parents.insert(node.node_id.clone(), node.parent_node_id.clone());
        if let Some(parent_id) = node.parent_node_id.as_ref() {
            children
                .entry(parent_id.clone())
                .or_default()
                .push(node.node_id.clone());
        }
    }
    for list in children.values_mut() {
        list.sort();
        list.dedup();
    }
    MemoryGraphIndex {
        nodes: node_map,
        parents,
        children,
    }
}

fn collect_ancestor_ids(
    parents: &HashMap<String, Option<String>>,
    node_id: &str,
    limit: usize,
) -> Vec<String> {
    let mut out = Vec::new();
    let mut cursor = parents.get(node_id).and_then(|value| value.clone());
    while let Some(current) = cursor {
        if out.len() >= limit {
            break;
        }
        out.push(current.clone());
        cursor = parents.get(&current).and_then(|value| value.clone());
    }
    out
}

fn collect_descendant_ids(
    children: &HashMap<String, Vec<String>>,
    nodes: &HashMap<String, MemoryGraphNode>,
    node_id: &str,
    limit: usize,
) -> Vec<String> {
    let mut out = Vec::new();
    let mut queue = VecDeque::new();
    if let Some(initial) = children.get(node_id) {
        for child in initial {
            queue.push_back(child.clone());
        }
    }
    let mut visited = HashSet::new();
    while let Some(current) = queue.pop_front() {
        if !visited.insert(current.clone()) {
            continue;
        }
        if !nodes.contains_key(&current) {
            continue;
        }
        out.push(current.clone());
        if out.len() >= limit {
            break;
        }
        if let Some(next) = children.get(&current) {
            for child in next {
                queue.push_back(child.clone());
            }
        }
    }
    out
}

fn parse_summary_tokens(summary: &str) -> HashMap<String, String> {
    let mut out = HashMap::new();
    for token in summary.split_whitespace() {
        if let Some((key, value)) = token.split_once('=') {
            if key.trim().is_empty() {
                continue;
            }
            out.insert(key.trim().to_string(), value.trim().to_string());
        }
    }
    out
}

pub fn render_memory_graph_inspect_human(view: &MemoryGraphInspectView) -> String {
    let focus = match view.focus_node.as_ref() {
        Some(node) => format!(
            "node_id:          {}\noperation:        {}\ncategory:         {}\nkey:              {}\nparent_node_id:   {}\ntimestamp_ms:     {}\n",
            node.node_id,
            node.operation,
            node.category,
            node.key,
            node.parent_node_id.as_deref().unwrap_or("(none)"),
            node.timestamp_unix_ms
        ),
        None => "(none)\n".to_string(),
    };
    let ancestors = if view.ancestor_nodes.is_empty() {
        "  (none)\n".to_string()
    } else {
        view.ancestor_nodes
            .iter()
            .map(|node| {
                format!(
                    "  {} [{}:{}] parent={}\n",
                    node.node_id,
                    node.category,
                    node.key,
                    node.parent_node_id.as_deref().unwrap_or("(none)")
                )
            })
            .collect::<String>()
    };
    let descendants = if view.descendant_nodes.is_empty() {
        "  (none)\n".to_string()
    } else {
        view.descendant_nodes
            .iter()
            .map(|node| {
                format!(
                    "  {} [{}:{}] parent={}\n",
                    node.node_id,
                    node.category,
                    node.key,
                    node.parent_node_id.as_deref().unwrap_or("(none)")
                )
            })
            .collect::<String>()
    };
    format!(
        "source_ref:        {}\ntotal_nodes:       {}\ndirection:         {}\nlimit:             {}\nnote:              {}\n\nfocus_node\n----------\n{}\nancestor_nodes\n--------------\n{}\ndescendant_nodes\n----------------\n{}",
        view.source_ref,
        view.total_nodes,
        view.direction.as_str(),
        view.limit,
        view.note,
        focus,
        ancestors,
        descendants,
    )
}

pub fn render_memory_graph_inspect_json(view: &MemoryGraphInspectView) -> String {
    serde_json::to_string_pretty(&view.to_json()).unwrap_or_else(|_| "{}".to_string()) + "\n"
}

pub fn render_memory_replay_selection_human(selection: &MemoryReplaySelection) -> String {
    format!(
        "source_ref:         {}\nmode:               {}\nfocus_node_id:      {}\nselected_nodes:     {}\nselected_keys:      {}\nselected_entries:   {}\ntotal_graph_nodes:  {}\nnote:               {}\n",
        selection.source_ref,
        selection.mode,
        selection.focus_node_id.as_deref().unwrap_or("(none)"),
        selection.selected_node_ids.len(),
        selection.selected_category_keys.len(),
        selection.selected_entries.len(),
        selection.total_graph_nodes,
        selection.note,
    )
}

pub fn render_memory_replay_selection_json(selection: &MemoryReplaySelection) -> String {
    serde_json::to_string_pretty(&json!({
        "source_ref": selection.source_ref,
        "mode": selection.mode,
        "focus_node_id": selection.focus_node_id,
        "selected_node_ids": selection.selected_node_ids,
        "selected_category_keys": selection.selected_category_keys.iter().map(|(category, key)| json!({
            "category": category,
            "key": key,
        })).collect::<Vec<_>>(),
        "selected_entries": selection.selected_entries.iter().map(MemoryEntry::to_json).collect::<Vec<_>>(),
        "total_graph_nodes": selection.total_graph_nodes,
        "note": selection.note,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    use std::sync::atomic::{AtomicU64, Ordering};
    static TEST_COUNTER: AtomicU64 = AtomicU64::new(0);

    fn temp_root() -> PathBuf {
        let n = TEST_COUNTER.fetch_add(1, Ordering::SeqCst);
        let dir =
            std::env::temp_dir().join(format!("loom_memory_test_{}_{}", std::process::id(), n));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn cleanup(root: &Path) {
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn test_memory_entry_roundtrip() {
        let entry = MemoryEntry {
            entry_id: "mem_1".to_string(),
            agent_id: "atlas".to_string(),
            category: "knowledge".to_string(),
            key: "test_key".to_string(),
            content: "test content".to_string(),
            created_at: 1000,
            updated_at: 2000,
            source: "user".to_string(),
            governed: true,
        };
        let json = entry.to_json();
        let parsed = MemoryEntry::from_json(&json).unwrap();
        assert_eq!(parsed.agent_id, "atlas");
        assert_eq!(parsed.content, "test content");
    }

    #[test]
    fn test_repo_write_and_read() {
        let root = temp_root();
        let repo = MemoryRepo::new(&root);
        let entries = vec![MemoryEntry {
            entry_id: "mem_1".to_string(),
            agent_id: "atlas".to_string(),
            category: "facts".to_string(),
            key: "k1".to_string(),
            content: "v1".to_string(),
            created_at: 1000,
            updated_at: 1000,
            source: "test".to_string(),
            governed: true,
        }];
        repo.write_entries("atlas", &entries).unwrap();
        let read = repo.read_entries("atlas").unwrap();
        assert_eq!(read.len(), 1);
        assert_eq!(read[0].key, "k1");
        cleanup(&root);
    }

    #[test]
    fn test_service_write_and_search() {
        let root = temp_root();
        let svc = MemoryService::with_defaults(&root);
        svc.write("atlas", "knowledge", "weather", "sunny", "user")
            .unwrap();
        svc.write("atlas", "knowledge", "location", "home", "user")
            .unwrap();
        svc.write("atlas", "preferences", "lang", "en", "user")
            .unwrap();

        let all = svc.search("atlas", None, None).unwrap();
        assert_eq!(all.len(), 3);

        let knowledge = svc.search("atlas", Some("knowledge"), None).unwrap();
        assert_eq!(knowledge.len(), 2);

        let weather = svc
            .search("atlas", Some("knowledge"), Some("weather"))
            .unwrap();
        assert_eq!(weather.len(), 1);
        assert_eq!(weather[0].content, "sunny");
        cleanup(&root);
    }

    #[test]
    fn test_service_upsert() {
        let root = temp_root();
        let svc = MemoryService::with_defaults(&root);
        svc.write("atlas", "facts", "k1", "v1", "test").unwrap();
        svc.write("atlas", "facts", "k1", "v2", "test").unwrap();

        let entries = svc.search("atlas", None, None).unwrap();
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].content, "v2");
        cleanup(&root);
    }

    #[test]
    fn test_service_remove() {
        let root = temp_root();
        let svc = MemoryService::with_defaults(&root);
        svc.write("atlas", "facts", "k1", "v1", "test").unwrap();
        assert!(svc.remove("atlas", "facts", "k1").unwrap());
        assert!(!svc.remove("atlas", "facts", "k1").unwrap());
        let entries = svc.search("atlas", None, None).unwrap();
        assert!(entries.is_empty());
        cleanup(&root);
    }

    #[test]
    fn test_service_size_limit() {
        let root = temp_root();
        let policy = MemoryPolicy {
            max_entry_bytes: 10,
            ..Default::default()
        };
        let svc = MemoryService::new(&root, policy);
        let result = svc.write(
            "atlas",
            "facts",
            "k1",
            "this is way too long content",
            "test",
        );
        assert!(result.is_err());
        cleanup(&root);
    }

    #[test]
    fn test_service_overview() {
        let root = temp_root();
        let svc = MemoryService::with_defaults(&root);
        svc.write("atlas", "facts", "k1", "v1", "test").unwrap();
        svc.write("sentinel", "rules", "r1", "no", "test").unwrap();

        let overview = svc.overview().unwrap();
        assert_eq!(overview.agent_count, 2);
        assert_eq!(overview.total_entries, 2);
        cleanup(&root);
    }

    #[test]
    fn test_agent_isolation() {
        let root = temp_root();
        let svc = MemoryService::with_defaults(&root);
        svc.write("atlas", "facts", "shared_key", "atlas_data", "test")
            .unwrap();
        svc.write("sentinel", "facts", "shared_key", "sentinel_data", "test")
            .unwrap();

        let atlas_entries = svc.search("atlas", None, None).unwrap();
        assert_eq!(atlas_entries.len(), 1);
        assert_eq!(atlas_entries[0].content, "atlas_data");

        let sentinel_entries = svc.search("sentinel", None, None).unwrap();
        assert_eq!(sentinel_entries.len(), 1);
        assert_eq!(sentinel_entries[0].content, "sentinel_data");
        cleanup(&root);
    }

    #[test]
    fn test_list_receipts_filters_by_agent_and_limit() {
        let root = temp_root();
        let svc = MemoryService::with_defaults(&root);
        svc.write("atlas", "facts", "k1", "v1", "test").unwrap();
        svc.search("atlas", Some("facts"), None).unwrap();
        svc.write("quill", "notes", "k2", "v2", "test").unwrap();

        let atlas = svc.list_receipts(10, Some("atlas")).unwrap();
        assert!(!atlas.is_empty());
        assert!(atlas.iter().all(|record| record.agent_id == "atlas"));

        let limited = svc.list_receipts(1, None).unwrap();
        assert_eq!(limited.len(), 1);
        cleanup(&root);
    }

    #[test]
    fn test_graph_inspect_compact_lineage_for_focus_node() {
        let root = temp_root();
        let svc = MemoryService::with_defaults(&root);
        svc.write("atlas", "research", "strategy", "v1", "test")
            .unwrap();
        svc.write("atlas", "research", "strategy", "v2", "test")
            .unwrap();
        svc.write("atlas", "research", "strategy", "v3", "test")
            .unwrap();

        let receipts = svc.list_receipts(20, Some("atlas")).unwrap();
        let write_nodes = receipts
            .iter()
            .filter(|record| record.operation == "write")
            .map(|record| record.receipt_hash.clone())
            .collect::<Vec<_>>();
        assert!(write_nodes.len() >= 3);
        let focus = write_nodes[1].clone();

        let graph = svc
            .graph_inspect("atlas", Some(&focus), MemoryLineageDirection::Both, 10)
            .unwrap();
        assert_eq!(graph.source_ref, "atlas");
        assert_eq!(graph.total_nodes >= 3, true);
        assert_eq!(
            graph.focus_node.as_ref().map(|node| node.node_id.as_str()),
            Some(focus.as_str())
        );
        assert!(!graph.ancestor_nodes.is_empty());
        assert!(!graph.descendant_nodes.is_empty());
        cleanup(&root);
    }

    #[test]
    fn test_select_replay_entries_for_node_subgraph() {
        let root = temp_root();
        let svc = MemoryService::with_defaults(&root);
        svc.write("atlas", "research", "strategy", "v1", "test")
            .unwrap();
        svc.write("atlas", "research", "strategy", "v2", "test")
            .unwrap();
        svc.write("atlas", "research", "strategy", "v3", "test")
            .unwrap();
        svc.write("atlas", "research", "risk", "low", "test")
            .unwrap();

        let receipts = svc.list_receipts(20, Some("atlas")).unwrap();
        let focus = receipts
            .iter()
            .find(|record| {
                record.operation == "write"
                    && record
                        .input_summary
                        .contains("category=research key=strategy")
            })
            .map(|record| record.receipt_hash.clone())
            .expect("strategy write receipt should exist");
        let selection = svc
            .select_replay_entries("atlas", Some(&focus), MemoryLineageDirection::Ancestors, 10)
            .unwrap();
        assert_eq!(selection.mode, "node_subgraph");
        assert_eq!(selection.focus_node_id.as_deref(), Some(focus.as_str()));
        assert!(!selection.selected_node_ids.is_empty());
        assert!(!selection.selected_entries.is_empty());
        assert!(selection
            .selected_category_keys
            .iter()
            .any(|(category, key)| category == "research" && key == "strategy"));
        cleanup(&root);
    }

    #[test]
    fn test_graph_inspect_respects_direction_mode() {
        let root = temp_root();
        let svc = MemoryService::with_defaults(&root);
        svc.write("atlas", "research", "strategy", "v1", "test")
            .unwrap();
        svc.write("atlas", "research", "strategy", "v2", "test")
            .unwrap();
        svc.write("atlas", "research", "strategy", "v3", "test")
            .unwrap();

        let receipts = svc.list_receipts(20, Some("atlas")).unwrap();
        let write_nodes = receipts
            .iter()
            .filter(|record| record.operation == "write")
            .map(|record| record.receipt_hash.clone())
            .collect::<Vec<_>>();
        assert!(write_nodes.len() >= 3);
        let focus = write_nodes[1].clone();

        let only_ancestors = svc
            .graph_inspect("atlas", Some(&focus), MemoryLineageDirection::Ancestors, 10)
            .unwrap();
        assert!(!only_ancestors.ancestor_nodes.is_empty());
        assert!(only_ancestors.descendant_nodes.is_empty());

        let only_descendants = svc
            .graph_inspect(
                "atlas",
                Some(&focus),
                MemoryLineageDirection::Descendants,
                10,
            )
            .unwrap();
        assert!(only_descendants.ancestor_nodes.is_empty());
        assert!(!only_descendants.descendant_nodes.is_empty());
        cleanup(&root);
    }

    #[test]
    fn test_parallel_prune_produces_same_result_as_sequential() {
        let root = temp_root();
        let svc = MemoryService::new(
            &root,
            MemoryPolicy {
                max_entries_per_agent: 100,
                max_entry_bytes: 65536,
                retention_days: 1,
                agent_isolation: true,
            },
        );
        // Write entries with a past timestamp by going through the repo directly
        for agent in &["atlas", "sentinel", "oracle"] {
            let old_entries: Vec<MemoryEntry> = (0..5)
                .map(|i| MemoryEntry {
                    entry_id: format!("mem_{agent}_{i}"),
                    agent_id: agent.to_string(),
                    category: "facts".to_string(),
                    key: format!("k{i}"),
                    content: format!("v{i}"),
                    created_at: 1000,  // far in the past
                    updated_at: 1000,
                    source: "test".to_string(),
                    governed: true,
                })
                .collect();
            svc.repo.write_entries(agent, &old_entries).unwrap();
        }
        let pruned = svc.prune_parallel().unwrap();
        assert_eq!(pruned, 15);
        for agent in &["atlas", "sentinel", "oracle"] {
            let entries = svc.repo.read_entries(agent).unwrap();
            assert_eq!(entries.len(), 0, "agent {agent} should have 0 entries after prune");
        }
        cleanup(&root);
    }

    #[test]
    fn test_compact_deduplicates_same_key_entries() {
        let root = temp_root();
        let svc = MemoryService::with_defaults(&root);
        // Write duplicates directly via repo (service upserts, so we bypass it)
        let entries = vec![
            MemoryEntry {
                entry_id: "m1".into(), agent_id: "atlas".into(),
                category: "facts".into(), key: "k1".into(),
                content: "v1".into(), created_at: 1000, updated_at: 1000,
                source: "test".into(), governed: true,
            },
            MemoryEntry {
                entry_id: "m2".into(), agent_id: "atlas".into(),
                category: "facts".into(), key: "k1".into(),
                content: "v2".into(), created_at: 1000, updated_at: 2000,
                source: "test".into(), governed: true,
            },
            MemoryEntry {
                entry_id: "m3".into(), agent_id: "atlas".into(),
                category: "facts".into(), key: "k1".into(),
                content: "v3".into(), created_at: 1000, updated_at: 3000,
                source: "test".into(), governed: true,
            },
            MemoryEntry {
                entry_id: "m4".into(), agent_id: "atlas".into(),
                category: "facts".into(), key: "k2".into(),
                content: "other".into(), created_at: 1000, updated_at: 1000,
                source: "test".into(), governed: true,
            },
        ];
        svc.repo.write_entries("atlas", &entries).unwrap();
        let entries_before = svc.repo.read_entries("atlas").unwrap();
        assert_eq!(entries_before.len(), 4);
        let compacted = svc.compact("atlas").unwrap();
        assert_eq!(compacted, 2, "should compact 2 duplicate entries");
        let entries_after = svc.repo.read_entries("atlas").unwrap();
        assert_eq!(entries_after.len(), 2, "should keep 2 unique keys");
        let k1 = entries_after.iter().find(|e| e.key == "k1").unwrap();
        assert_eq!(k1.content, "v3", "should keep latest value");
        cleanup(&root);
    }

    #[test]
    fn test_compact_preserves_lineage_proof() {
        let root = temp_root();
        let svc = MemoryService::with_defaults(&root);
        // Create duplicates via repo
        let entries = vec![
            MemoryEntry {
                entry_id: "m1".into(), agent_id: "atlas".into(),
                category: "facts".into(), key: "k1".into(),
                content: "v1".into(), created_at: 1000, updated_at: 1000,
                source: "test".into(), governed: true,
            },
            MemoryEntry {
                entry_id: "m2".into(), agent_id: "atlas".into(),
                category: "facts".into(), key: "k1".into(),
                content: "v2".into(), created_at: 1000, updated_at: 2000,
                source: "test".into(), governed: true,
            },
        ];
        svc.repo.write_entries("atlas", &entries).unwrap();
        svc.compact("atlas").unwrap();
        let receipts = svc.list_receipts(20, Some("atlas")).unwrap();
        let compact_receipts: Vec<_> = receipts
            .iter()
            .filter(|r| r.operation == "compact")
            .collect();
        assert!(!compact_receipts.is_empty(), "compact receipt should be emitted");
        cleanup(&root);
    }

    #[test]
    fn test_compact_noop_when_no_duplicates() {
        let root = temp_root();
        let svc = MemoryService::with_defaults(&root);
        svc.write("atlas", "facts", "k1", "v1", "test").unwrap();
        svc.write("atlas", "facts", "k2", "v2", "test").unwrap();
        let compacted = svc.compact("atlas").unwrap();
        assert_eq!(compacted, 0, "no duplicates should mean no compaction");
        cleanup(&root);
    }
}
