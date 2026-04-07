//! Hybrid memory architecture: temporal relations, vector retrieval, Merkle provenance.
//!
//! This module extends the memory service with three layers:
//! - **Temporal**: entries have valid_from/valid_until, enabling point-in-time queries
//! - **Vector**: entries carry an optional embedding vector for cosine similarity search
//! - **Merkle provenance**: each entry hash chains into a root, enabling integrity proofs

use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use crate::LoomResult;

// ---------------------------------------------------------------------------
// Temporal relation layer
// ---------------------------------------------------------------------------

/// A memory entry with temporal bounds.
#[derive(Clone, Debug, PartialEq)]
pub struct TemporalEntry {
    pub entry_id: String,
    pub agent_id: String,
    pub category: String,
    pub key: String,
    pub content: String,
    pub valid_from: u64,
    pub valid_until: Option<u64>,
    pub source: String,
}

impl TemporalEntry {
    pub fn is_valid_at(&self, timestamp: u64) -> bool {
        if timestamp < self.valid_from {
            return false;
        }
        match self.valid_until {
            Some(until) => timestamp < until,
            None => true,
        }
    }

    pub fn to_json(&self) -> Value {
        json!({
            "entry_id": self.entry_id,
            "agent_id": self.agent_id,
            "category": self.category,
            "key": self.key,
            "content": self.content,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "source": self.source,
        })
    }
}

/// Query entries valid at a specific point in time.
pub fn query_at_time(entries: &[TemporalEntry], timestamp: u64) -> Vec<&TemporalEntry> {
    entries.iter().filter(|e| e.is_valid_at(timestamp)).collect()
}

/// Query entries valid within a time range [from, until).
pub fn query_range(entries: &[TemporalEntry], from: u64, until: u64) -> Vec<&TemporalEntry> {
    entries
        .iter()
        .filter(|e| {
            let entry_end = e.valid_until.unwrap_or(u64::MAX);
            e.valid_from < until && entry_end > from
        })
        .collect()
}

// ---------------------------------------------------------------------------
// Vector retrieval layer
// ---------------------------------------------------------------------------

/// A memory entry with an optional embedding vector.
#[derive(Clone, Debug)]
pub struct VectorEntry {
    pub entry_id: String,
    pub content: String,
    pub embedding: Vec<f32>,
}

/// Compute cosine similarity between two vectors.
pub fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 {
    if a.len() != b.len() || a.is_empty() {
        return 0.0;
    }
    let dot: f32 = a.iter().zip(b.iter()).map(|(x, y)| x * y).sum();
    let norm_a: f32 = a.iter().map(|x| x * x).sum::<f32>().sqrt();
    let norm_b: f32 = b.iter().map(|x| x * x).sum::<f32>().sqrt();
    if norm_a == 0.0 || norm_b == 0.0 {
        return 0.0;
    }
    dot / (norm_a * norm_b)
}

/// Search entries by vector similarity, returning (entry, score) pairs sorted descending.
pub fn vector_search<'a>(
    entries: &'a [VectorEntry],
    query: &[f32],
    top_k: usize,
) -> Vec<(&'a VectorEntry, f32)> {
    let mut scored: Vec<(&VectorEntry, f32)> = entries
        .iter()
        .map(|e| (e, cosine_similarity(&e.embedding, query)))
        .collect();
    scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    scored.truncate(top_k);
    scored
}

// ---------------------------------------------------------------------------
// Merkle provenance layer
// ---------------------------------------------------------------------------

/// Hash a single entry's content for Merkle tree inclusion.
pub fn hash_entry(entry_id: &str, content: &str) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(entry_id.as_bytes());
    hasher.update(b"|");
    hasher.update(content.as_bytes());
    hasher.finalize().into()
}

/// Combine two hashes into a parent hash (Merkle internal node).
pub fn hash_pair(left: &[u8; 32], right: &[u8; 32]) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(left);
    hasher.update(right);
    hasher.finalize().into()
}

/// Compute a Merkle root over a list of (entry_id, content) pairs.
///
/// Returns the root hash and the full list of leaf hashes for verification.
pub fn compute_provenance_root(entries: &[(String, String)]) -> LoomResult<ProvenanceRoot> {
    if entries.is_empty() {
        return Ok(ProvenanceRoot {
            root: [0u8; 32],
            leaf_count: 0,
            leaves: Vec::new(),
        });
    }
    let leaves: Vec<[u8; 32]> = entries
        .iter()
        .map(|(id, content)| hash_entry(id, content))
        .collect();

    let root = merkle_root_from_leaves(&leaves);
    Ok(ProvenanceRoot {
        root,
        leaf_count: leaves.len(),
        leaves,
    })
}

/// Verify that a specific entry is included in the provenance root.
pub fn verify_entry_inclusion(
    provenance: &ProvenanceRoot,
    entry_id: &str,
    content: &str,
) -> bool {
    let leaf_hash = hash_entry(entry_id, content);
    provenance.leaves.contains(&leaf_hash)
}

fn merkle_root_from_leaves(leaves: &[[u8; 32]]) -> [u8; 32] {
    if leaves.is_empty() {
        return [0u8; 32];
    }
    if leaves.len() == 1 {
        return leaves[0];
    }
    let mut current = leaves.to_vec();
    while current.len() > 1 {
        let mut next = Vec::new();
        for chunk in current.chunks(2) {
            if chunk.len() == 2 {
                next.push(hash_pair(&chunk[0], &chunk[1]));
            } else {
                next.push(chunk[0]);
            }
        }
        current = next;
    }
    current[0]
}

/// The result of computing a Merkle provenance root.
#[derive(Clone, Debug)]
pub struct ProvenanceRoot {
    pub root: [u8; 32],
    pub leaf_count: usize,
    pub leaves: Vec<[u8; 32]>,
}

impl ProvenanceRoot {
    pub fn root_hex(&self) -> String {
        hex_encode(&self.root)
    }

    pub fn to_json(&self) -> Value {
        json!({
            "root": self.root_hex(),
            "leaf_count": self.leaf_count,
        })
    }
}

fn hex_encode(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{:02x}", b)).collect()
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    // -- Temporal tests --

    #[test]
    fn temporal_entry_valid_at_checks_bounds() {
        let entry = TemporalEntry {
            entry_id: "t1".into(),
            agent_id: "atlas".into(),
            category: "facts".into(),
            key: "k1".into(),
            content: "v1".into(),
            valid_from: 1000,
            valid_until: Some(2000),
            source: "test".into(),
        };
        assert!(!entry.is_valid_at(999));
        assert!(entry.is_valid_at(1000));
        assert!(entry.is_valid_at(1500));
        assert!(!entry.is_valid_at(2000));
    }

    #[test]
    fn temporal_entry_open_ended_valid_indefinitely() {
        let entry = TemporalEntry {
            entry_id: "t2".into(),
            agent_id: "atlas".into(),
            category: "facts".into(),
            key: "k1".into(),
            content: "v1".into(),
            valid_from: 1000,
            valid_until: None,
            source: "test".into(),
        };
        assert!(entry.is_valid_at(1000));
        assert!(entry.is_valid_at(u64::MAX - 1));
    }

    #[test]
    fn query_at_time_filters_correctly() {
        let entries = vec![
            TemporalEntry {
                entry_id: "t1".into(), agent_id: "a".into(),
                category: "f".into(), key: "k1".into(), content: "v1".into(),
                valid_from: 1000, valid_until: Some(2000), source: "t".into(),
            },
            TemporalEntry {
                entry_id: "t2".into(), agent_id: "a".into(),
                category: "f".into(), key: "k1".into(), content: "v2".into(),
                valid_from: 2000, valid_until: None, source: "t".into(),
            },
        ];
        let at_1500 = query_at_time(&entries, 1500);
        assert_eq!(at_1500.len(), 1);
        assert_eq!(at_1500[0].content, "v1");

        let at_2500 = query_at_time(&entries, 2500);
        assert_eq!(at_2500.len(), 1);
        assert_eq!(at_2500[0].content, "v2");
    }

    #[test]
    fn query_range_finds_overlapping_entries() {
        let entries = vec![
            TemporalEntry {
                entry_id: "t1".into(), agent_id: "a".into(),
                category: "f".into(), key: "k1".into(), content: "early".into(),
                valid_from: 100, valid_until: Some(500), source: "t".into(),
            },
            TemporalEntry {
                entry_id: "t2".into(), agent_id: "a".into(),
                category: "f".into(), key: "k2".into(), content: "middle".into(),
                valid_from: 400, valid_until: Some(800), source: "t".into(),
            },
            TemporalEntry {
                entry_id: "t3".into(), agent_id: "a".into(),
                category: "f".into(), key: "k3".into(), content: "late".into(),
                valid_from: 900, valid_until: None, source: "t".into(),
            },
        ];
        let range = query_range(&entries, 300, 600);
        assert_eq!(range.len(), 2);
    }

    // -- Vector tests --

    #[test]
    fn cosine_similarity_identical_vectors_is_one() {
        let v = vec![1.0, 0.0, 0.0];
        let sim = cosine_similarity(&v, &v);
        assert!((sim - 1.0).abs() < 1e-6);
    }

    #[test]
    fn cosine_similarity_orthogonal_vectors_is_zero() {
        let a = vec![1.0, 0.0, 0.0];
        let b = vec![0.0, 1.0, 0.0];
        let sim = cosine_similarity(&a, &b);
        assert!(sim.abs() < 1e-6);
    }

    #[test]
    fn cosine_similarity_empty_is_zero() {
        assert_eq!(cosine_similarity(&[], &[]), 0.0);
    }

    #[test]
    fn vector_search_returns_top_k_sorted() {
        let entries = vec![
            VectorEntry { entry_id: "e1".into(), content: "far".into(), embedding: vec![0.0, 1.0, 0.0] },
            VectorEntry { entry_id: "e2".into(), content: "close".into(), embedding: vec![0.9, 0.1, 0.0] },
            VectorEntry { entry_id: "e3".into(), content: "closest".into(), embedding: vec![1.0, 0.0, 0.0] },
        ];
        let query = vec![1.0, 0.0, 0.0];
        let results = vector_search(&entries, &query, 2);
        assert_eq!(results.len(), 2);
        assert_eq!(results[0].0.entry_id, "e3");
        assert_eq!(results[1].0.entry_id, "e2");
        assert!((results[0].1 - 1.0).abs() < 1e-6);
    }

    // -- Merkle provenance tests --

    #[test]
    fn provenance_root_deterministic() {
        let entries = vec![
            ("e1".to_string(), "content1".to_string()),
            ("e2".to_string(), "content2".to_string()),
        ];
        let r1 = compute_provenance_root(&entries).unwrap();
        let r2 = compute_provenance_root(&entries).unwrap();
        assert_eq!(r1.root, r2.root);
        assert_eq!(r1.leaf_count, 2);
    }

    #[test]
    fn provenance_root_changes_with_content() {
        let e1 = vec![("e1".to_string(), "v1".to_string())];
        let e2 = vec![("e1".to_string(), "v2".to_string())];
        let r1 = compute_provenance_root(&e1).unwrap();
        let r2 = compute_provenance_root(&e2).unwrap();
        assert_ne!(r1.root, r2.root);
    }

    #[test]
    fn verify_entry_inclusion_works() {
        let entries = vec![
            ("e1".to_string(), "c1".to_string()),
            ("e2".to_string(), "c2".to_string()),
        ];
        let prov = compute_provenance_root(&entries).unwrap();
        assert!(verify_entry_inclusion(&prov, "e1", "c1"));
        assert!(verify_entry_inclusion(&prov, "e2", "c2"));
        assert!(!verify_entry_inclusion(&prov, "e1", "wrong"));
        assert!(!verify_entry_inclusion(&prov, "e3", "c3"));
    }

    #[test]
    fn empty_provenance_root_is_zero() {
        let prov = compute_provenance_root(&[]).unwrap();
        assert_eq!(prov.root, [0u8; 32]);
        assert_eq!(prov.leaf_count, 0);
    }

    #[test]
    fn provenance_root_odd_leaf_count() {
        let entries = vec![
            ("e1".to_string(), "c1".to_string()),
            ("e2".to_string(), "c2".to_string()),
            ("e3".to_string(), "c3".to_string()),
        ];
        let prov = compute_provenance_root(&entries).unwrap();
        assert_ne!(prov.root, [0u8; 32]);
        assert_eq!(prov.leaf_count, 3);
    }

    #[test]
    fn provenance_root_hex_format() {
        let entries = vec![("e1".to_string(), "c1".to_string())];
        let prov = compute_provenance_root(&entries).unwrap();
        let hex = prov.root_hex();
        assert_eq!(hex.len(), 64);
        assert!(hex.chars().all(|c| c.is_ascii_hexdigit()));
    }
}
