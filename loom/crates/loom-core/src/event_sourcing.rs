//! Event sourcing foundation for governance flows.
//!
//! Provides an append-only event store, deterministic replay, and a
//! CRDT-safe state merge for federation-compatible governance state.

use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use crate::LoomResult;

// ---------------------------------------------------------------------------
// Event types
// ---------------------------------------------------------------------------

/// A governance event that can be stored and replayed.
#[derive(Clone, Debug, PartialEq)]
pub struct GovernanceEvent {
    pub event_id: String,
    pub event_type: String,
    pub agent_id: String,
    pub payload: Value,
    pub timestamp_ms: u64,
    pub sequence: u64,
}

impl GovernanceEvent {
    pub fn to_json(&self) -> Value {
        json!({
            "event_id": self.event_id,
            "event_type": self.event_type,
            "agent_id": self.agent_id,
            "payload": self.payload,
            "timestamp_ms": self.timestamp_ms,
            "sequence": self.sequence,
        })
    }

    pub fn from_json(v: &Value) -> LoomResult<Self> {
        Ok(Self {
            event_id: v.get("event_id").and_then(Value::as_str).unwrap_or("").to_string(),
            event_type: v.get("event_type").and_then(Value::as_str).unwrap_or("").to_string(),
            agent_id: v.get("agent_id").and_then(Value::as_str).unwrap_or("").to_string(),
            payload: v.get("payload").cloned().unwrap_or(Value::Null),
            timestamp_ms: v.get("timestamp_ms").and_then(Value::as_u64).unwrap_or(0),
            sequence: v.get("sequence").and_then(Value::as_u64).unwrap_or(0),
        })
    }
}

// ---------------------------------------------------------------------------
// Event Store (append-only)
// ---------------------------------------------------------------------------

/// Append-only event store backed by a JSONL file.
pub struct EventStore {
    path: PathBuf,
    next_sequence: u64,
}

impl EventStore {
    pub fn open(path: &Path) -> LoomResult<Self> {
        let events = Self::read_all_from(path)?;
        let next_sequence = events.last().map(|e| e.sequence + 1).unwrap_or(0);
        Ok(Self {
            path: path.to_path_buf(),
            next_sequence,
        })
    }

    pub fn append(&mut self, event_type: &str, agent_id: &str, payload: Value, timestamp_ms: u64) -> LoomResult<GovernanceEvent> {
        let event = GovernanceEvent {
            event_id: format!("evt_{:016x}", self.next_sequence),
            event_type: event_type.to_string(),
            agent_id: agent_id.to_string(),
            payload,
            timestamp_ms,
            sequence: self.next_sequence,
        };
        if let Some(parent) = self.path.parent() {
            fs::create_dir_all(parent).map_err(|e| format!("event store mkdir: {e}"))?;
        }
        let mut file = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.path)
            .map_err(|e| format!("event store open: {e}"))?;
        let line = serde_json::to_string(&event.to_json())
            .map_err(|e| format!("event serialize: {e}"))?;
        writeln!(file, "{line}").map_err(|e| format!("event write: {e}"))?;
        self.next_sequence += 1;
        Ok(event)
    }

    pub fn read_all(&self) -> LoomResult<Vec<GovernanceEvent>> {
        Self::read_all_from(&self.path)
    }

    fn read_all_from(path: &Path) -> LoomResult<Vec<GovernanceEvent>> {
        if !path.exists() {
            return Ok(Vec::new());
        }
        let raw = fs::read_to_string(path).map_err(|e| format!("event read: {e}"))?;
        let mut events = Vec::new();
        for line in raw.lines() {
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }
            let v: Value = serde_json::from_str(trimmed)
                .map_err(|e| format!("event parse: {e}"))?;
            events.push(GovernanceEvent::from_json(&v)?);
        }
        events.sort_by_key(|e| e.sequence);
        Ok(events)
    }

    pub fn sequence(&self) -> u64 {
        self.next_sequence
    }
}

// ---------------------------------------------------------------------------
// Deterministic Replay
// ---------------------------------------------------------------------------

/// Treasury state derived from replaying events.
#[derive(Clone, Debug, PartialEq)]
pub struct ReplayedTreasuryState {
    pub balance_cents: u64,
    pub total_spent_cents: u64,
    pub total_deposited_cents: u64,
    pub event_count: u64,
}

/// Replay governance events to reconstruct treasury state.
pub fn replay_treasury(events: &[GovernanceEvent]) -> ReplayedTreasuryState {
    let mut state = ReplayedTreasuryState {
        balance_cents: 0,
        total_spent_cents: 0,
        total_deposited_cents: 0,
        event_count: 0,
    };
    for event in events {
        match event.event_type.as_str() {
            "treasury_deposit" => {
                let amount = event.payload.get("amount_cents")
                    .and_then(Value::as_u64)
                    .unwrap_or(0);
                state.balance_cents = state.balance_cents.saturating_add(amount);
                state.total_deposited_cents = state.total_deposited_cents.saturating_add(amount);
            }
            "treasury_spend" => {
                let amount = event.payload.get("amount_cents")
                    .and_then(Value::as_u64)
                    .unwrap_or(0);
                state.balance_cents = state.balance_cents.saturating_sub(amount);
                state.total_spent_cents = state.total_spent_cents.saturating_add(amount);
            }
            _ => {}
        }
        state.event_count += 1;
    }
    state
}

// ---------------------------------------------------------------------------
// CRDT-safe State Merge (G-Counter style)
// ---------------------------------------------------------------------------

/// A grow-only counter map for federation-safe state merging.
///
/// Each node independently increments its own counter. Merge takes the
/// max of each node's counter — guaranteeing convergence without coordination.
#[derive(Clone, Debug, PartialEq)]
pub struct GCounter {
    counters: HashMap<String, u64>,
}

impl GCounter {
    pub fn new() -> Self {
        Self { counters: HashMap::new() }
    }

    pub fn increment(&mut self, node_id: &str, amount: u64) {
        let entry = self.counters.entry(node_id.to_string()).or_insert(0);
        *entry = entry.saturating_add(amount);
    }

    pub fn value(&self) -> u64 {
        self.counters.values().sum()
    }

    pub fn merge(&self, other: &GCounter) -> GCounter {
        let mut merged = self.counters.clone();
        for (key, &value) in &other.counters {
            let entry = merged.entry(key.clone()).or_insert(0);
            *entry = (*entry).max(value);
        }
        GCounter { counters: merged }
    }

    pub fn node_value(&self, node_id: &str) -> u64 {
        self.counters.get(node_id).copied().unwrap_or(0)
    }
}

impl Default for GCounter {
    fn default() -> Self {
        Self::new()
    }
}

// ---------------------------------------------------------------------------
// Actor-style execution boundary
// ---------------------------------------------------------------------------

/// A message sent to an actor.
#[derive(Clone, Debug)]
pub struct ActorMessage {
    pub actor_id: String,
    pub action: String,
    pub payload: Value,
}

/// Result of processing a message.
#[derive(Clone, Debug)]
pub struct ActorResponse {
    pub actor_id: String,
    pub action: String,
    pub result: Value,
    pub events: Vec<GovernanceEvent>,
}

/// An actor that processes messages and emits governance events.
pub struct GovernanceActor {
    pub actor_id: String,
    sequence: u64,
}

impl GovernanceActor {
    pub fn new(actor_id: &str) -> Self {
        Self {
            actor_id: actor_id.to_string(),
            sequence: 0,
        }
    }

    /// Process a message and return a response with emitted events.
    pub fn process(&mut self, msg: &ActorMessage, timestamp_ms: u64) -> ActorResponse {
        let event = GovernanceEvent {
            event_id: format!("evt_{}_{:08x}", self.actor_id, self.sequence),
            event_type: format!("actor.{}", msg.action),
            agent_id: msg.actor_id.clone(),
            payload: msg.payload.clone(),
            timestamp_ms,
            sequence: self.sequence,
        };
        self.sequence += 1;
        ActorResponse {
            actor_id: self.actor_id.clone(),
            action: msg.action.clone(),
            result: json!({"status": "processed", "event_id": event.event_id}),
            events: vec![event],
        }
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn temp_event_path() -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "loom_event_test_{}_{}", std::process::id(), rand_u32()
        ));
        fs::create_dir_all(&dir).unwrap();
        dir.join("events.jsonl")
    }

    fn rand_u32() -> u32 {
        use std::time::{SystemTime, UNIX_EPOCH};
        SystemTime::now().duration_since(UNIX_EPOCH).unwrap().subsec_nanos()
    }

    // -- Event Store --

    #[test]
    fn event_store_append_and_read() {
        let path = temp_event_path();
        let mut store = EventStore::open(&path).unwrap();
        store.append("treasury_deposit", "agent_a", json!({"amount_cents": 100}), 1000).unwrap();
        store.append("treasury_spend", "agent_a", json!({"amount_cents": 30}), 2000).unwrap();
        let events = store.read_all().unwrap();
        assert_eq!(events.len(), 2);
        assert_eq!(events[0].sequence, 0);
        assert_eq!(events[1].sequence, 1);
        let _ = fs::remove_dir_all(path.parent().unwrap());
    }

    #[test]
    fn event_store_resumes_sequence() {
        let path = temp_event_path();
        {
            let mut store = EventStore::open(&path).unwrap();
            store.append("deposit", "a", json!({}), 1000).unwrap();
            store.append("deposit", "a", json!({}), 2000).unwrap();
        }
        let mut store2 = EventStore::open(&path).unwrap();
        assert_eq!(store2.sequence(), 2);
        store2.append("spend", "a", json!({}), 3000).unwrap();
        let events = store2.read_all().unwrap();
        assert_eq!(events.len(), 3);
        assert_eq!(events[2].sequence, 2);
        let _ = fs::remove_dir_all(path.parent().unwrap());
    }

    // -- Replay --

    #[test]
    fn replay_treasury_reconstructs_state() {
        let events = vec![
            GovernanceEvent {
                event_id: "e1".into(), event_type: "treasury_deposit".into(),
                agent_id: "a".into(), payload: json!({"amount_cents": 100}),
                timestamp_ms: 1000, sequence: 0,
            },
            GovernanceEvent {
                event_id: "e2".into(), event_type: "treasury_spend".into(),
                agent_id: "a".into(), payload: json!({"amount_cents": 30}),
                timestamp_ms: 2000, sequence: 1,
            },
        ];
        let state = replay_treasury(&events);
        assert_eq!(state.balance_cents, 70);
        assert_eq!(state.total_deposited_cents, 100);
        assert_eq!(state.total_spent_cents, 30);
        assert_eq!(state.event_count, 2);
    }

    #[test]
    fn replay_is_deterministic() {
        let events = vec![
            GovernanceEvent {
                event_id: "e1".into(), event_type: "treasury_deposit".into(),
                agent_id: "a".into(), payload: json!({"amount_cents": 50}),
                timestamp_ms: 1000, sequence: 0,
            },
        ];
        let s1 = replay_treasury(&events);
        let s2 = replay_treasury(&events);
        assert_eq!(s1, s2);
    }

    // -- GCounter CRDT --

    #[test]
    fn gcounter_increment_and_value() {
        let mut c = GCounter::new();
        c.increment("node_a", 5);
        c.increment("node_b", 3);
        assert_eq!(c.value(), 8);
    }

    #[test]
    fn gcounter_merge_takes_max() {
        let mut a = GCounter::new();
        a.increment("n1", 5);
        a.increment("n2", 3);

        let mut b = GCounter::new();
        b.increment("n1", 3);
        b.increment("n2", 7);
        b.increment("n3", 1);

        let merged = a.merge(&b);
        assert_eq!(merged.node_value("n1"), 5);
        assert_eq!(merged.node_value("n2"), 7);
        assert_eq!(merged.node_value("n3"), 1);
        assert_eq!(merged.value(), 13);
    }

    #[test]
    fn gcounter_merge_is_commutative() {
        let mut a = GCounter::new();
        a.increment("x", 10);
        let mut b = GCounter::new();
        b.increment("y", 20);
        assert_eq!(a.merge(&b), b.merge(&a));
    }

    #[test]
    fn gcounter_merge_is_idempotent() {
        let mut a = GCounter::new();
        a.increment("x", 5);
        let merged = a.merge(&a);
        assert_eq!(merged, a);
    }

    // -- Actor --

    #[test]
    fn actor_processes_message_and_emits_event() {
        let mut actor = GovernanceActor::new("treasury_actor");
        let msg = ActorMessage {
            actor_id: "agent_a".into(),
            action: "deposit".into(),
            payload: json!({"amount_cents": 100}),
        };
        let response = actor.process(&msg, 1000);
        assert_eq!(response.events.len(), 1);
        assert_eq!(response.events[0].event_type, "actor.deposit");
        assert_eq!(response.action, "deposit");
    }

    #[test]
    fn actor_increments_sequence() {
        let mut actor = GovernanceActor::new("test");
        let msg = ActorMessage {
            actor_id: "a".into(), action: "op".into(), payload: json!({}),
        };
        let r1 = actor.process(&msg, 1000);
        let r2 = actor.process(&msg, 2000);
        assert_eq!(r1.events[0].sequence, 0);
        assert_eq!(r2.events[0].sequence, 1);
    }
}
