//! Local verifiable agent marketplace.
//!
//! Provides a governed bid/assignment/settle lifecycle for agent work,
//! bound to treasury accounting and PoGE proof receipts.
//!
//! Flow: Bid -> Assign -> Execute -> Settle (with proof)
//!
//! All transitions emit governance events and require treasury commitment.

use sha2::{Digest, Sha256};
use serde_json::{json, Value};

use crate::LoomResult;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/// A bid from an agent for a task.
#[derive(Clone, Debug, PartialEq)]
pub struct Bid {
    pub bid_id: String,
    pub agent_id: String,
    pub task_id: String,
    pub price_cents: u64,
    pub capability: String,
    pub timestamp_ms: u64,
}

/// Assignment of a bid to execute.
#[derive(Clone, Debug, PartialEq)]
pub struct Assignment {
    pub assignment_id: String,
    pub bid: Bid,
    pub treasury_commitment_cents: u64,
    pub assigned_at_ms: u64,
}

/// Settlement after execution with proof.
#[derive(Clone, Debug, PartialEq)]
pub struct Settlement {
    pub settlement_id: String,
    pub assignment_id: String,
    pub agent_id: String,
    pub settled_cents: u64,
    pub proof_hash: String,
    pub settled_at_ms: u64,
    pub status: SettlementStatus,
}

#[derive(Clone, Debug, PartialEq)]
pub enum SettlementStatus {
    Completed,
    Disputed,
    Refunded,
}

/// The marketplace state.
#[derive(Clone, Debug)]
pub struct Marketplace {
    pub open_bids: Vec<Bid>,
    pub assignments: Vec<Assignment>,
    pub settlements: Vec<Settlement>,
    pub treasury_committed_cents: u64,
    pub treasury_settled_cents: u64,
}

impl Marketplace {
    pub fn new() -> Self {
        Self {
            open_bids: Vec::new(),
            assignments: Vec::new(),
            settlements: Vec::new(),
            treasury_committed_cents: 0,
            treasury_settled_cents: 0,
        }
    }

    /// Submit a bid for a task. Returns the bid.
    pub fn submit_bid(
        &mut self,
        agent_id: &str,
        task_id: &str,
        price_cents: u64,
        capability: &str,
        timestamp_ms: u64,
    ) -> LoomResult<Bid> {
        if price_cents == 0 {
            return Err("bid price must be greater than zero".to_string());
        }
        let bid = Bid {
            bid_id: format!("bid_{:016x}", self.open_bids.len()),
            agent_id: agent_id.to_string(),
            task_id: task_id.to_string(),
            price_cents,
            capability: capability.to_string(),
            timestamp_ms,
        };
        self.open_bids.push(bid.clone());
        Ok(bid)
    }

    /// Assign a bid for execution, committing treasury funds.
    pub fn assign_bid(
        &mut self,
        bid_id: &str,
        treasury_balance_cents: u64,
        treasury_floor_cents: u64,
        timestamp_ms: u64,
    ) -> LoomResult<Assignment> {
        let bid_idx = self.open_bids.iter().position(|b| b.bid_id == bid_id)
            .ok_or_else(|| format!("bid '{}' not found", bid_id))?;
        let bid = self.open_bids[bid_idx].clone();
        // Treasury gate: ensure funds available above floor
        let available = treasury_balance_cents.saturating_sub(treasury_floor_cents);
        let total_committed = self.treasury_committed_cents.saturating_add(bid.price_cents);
        if total_committed > available {
            return Err(format!(
                "treasury insufficient: need {} cents but only {} available (committed: {})",
                bid.price_cents, available, self.treasury_committed_cents
            ));
        }
        let assignment = Assignment {
            assignment_id: format!("asgn_{:016x}", self.assignments.len()),
            bid: bid.clone(),
            treasury_commitment_cents: bid.price_cents,
            assigned_at_ms: timestamp_ms,
        };
        self.open_bids.remove(bid_idx);
        self.treasury_committed_cents = total_committed;
        self.assignments.push(assignment.clone());
        Ok(assignment)
    }

    /// Settle an assignment after execution, with a PoGE proof hash.
    pub fn settle(
        &mut self,
        assignment_id: &str,
        proof_hash: &str,
        timestamp_ms: u64,
    ) -> LoomResult<Settlement> {
        let asgn_idx = self.assignments.iter().position(|a| a.assignment_id == assignment_id)
            .ok_or_else(|| format!("assignment '{}' not found", assignment_id))?;
        let asgn = self.assignments[asgn_idx].clone();
        if proof_hash.is_empty() {
            return Err("settlement requires a non-empty proof hash".to_string());
        }
        let settlement = Settlement {
            settlement_id: format!("settle_{:016x}", self.settlements.len()),
            assignment_id: asgn.assignment_id.clone(),
            agent_id: asgn.bid.agent_id.clone(),
            settled_cents: asgn.treasury_commitment_cents,
            proof_hash: proof_hash.to_string(),
            settled_at_ms: timestamp_ms,
            status: SettlementStatus::Completed,
        };
        self.treasury_committed_cents = self.treasury_committed_cents
            .saturating_sub(asgn.treasury_commitment_cents);
        self.treasury_settled_cents = self.treasury_settled_cents
            .saturating_add(asgn.treasury_commitment_cents);
        self.assignments.remove(asgn_idx);
        self.settlements.push(settlement.clone());
        Ok(settlement)
    }

    /// Get a summary of marketplace state.
    pub fn summary(&self) -> Value {
        json!({
            "open_bids": self.open_bids.len(),
            "active_assignments": self.assignments.len(),
            "completed_settlements": self.settlements.len(),
            "treasury_committed_cents": self.treasury_committed_cents,
            "treasury_settled_cents": self.treasury_settled_cents,
        })
    }
}

impl Default for Marketplace {
    fn default() -> Self {
        Self::new()
    }
}

/// Compute a settlement proof hash from execution artifacts.
pub fn compute_settlement_proof(
    agent_id: &str,
    task_id: &str,
    amount_cents: u64,
    execution_receipt: &str,
) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"MERIDIAN_SETTLE_v1\x00");
    hasher.update(agent_id.as_bytes());
    hasher.update(b"|");
    hasher.update(task_id.as_bytes());
    hasher.update(b"|");
    hasher.update(amount_cents.to_le_bytes());
    hasher.update(b"|");
    hasher.update(execution_receipt.as_bytes());
    let result = hasher.finalize();
    format!("0x{}", result.iter().map(|b| format!("{:02x}", b)).collect::<String>())
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn submit_bid_creates_entry() {
        let mut market = Marketplace::new();
        let bid = market.submit_bid("agent_a", "task_1", 100, "exec", 1000).unwrap();
        assert_eq!(bid.agent_id, "agent_a");
        assert_eq!(bid.price_cents, 100);
        assert_eq!(market.open_bids.len(), 1);
    }

    #[test]
    fn submit_bid_rejects_zero_price() {
        let mut market = Marketplace::new();
        let result = market.submit_bid("a", "t", 0, "exec", 1000);
        assert!(result.is_err());
    }

    #[test]
    fn assign_bid_commits_treasury() {
        let mut market = Marketplace::new();
        let bid = market.submit_bid("agent_a", "task_1", 100, "exec", 1000).unwrap();
        let asgn = market.assign_bid(&bid.bid_id, 500, 100, 2000).unwrap();
        assert_eq!(asgn.treasury_commitment_cents, 100);
        assert_eq!(market.treasury_committed_cents, 100);
        assert_eq!(market.open_bids.len(), 0);
        assert_eq!(market.assignments.len(), 1);
    }

    #[test]
    fn assign_bid_rejects_insufficient_treasury() {
        let mut market = Marketplace::new();
        let bid = market.submit_bid("agent_a", "task_1", 500, "exec", 1000).unwrap();
        let result = market.assign_bid(&bid.bid_id, 400, 100, 2000);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("treasury insufficient"));
    }

    #[test]
    fn assign_bid_rejects_unknown_bid() {
        let mut market = Marketplace::new();
        let result = market.assign_bid("nonexistent", 500, 100, 2000);
        assert!(result.is_err());
    }

    #[test]
    fn settle_completes_lifecycle() {
        let mut market = Marketplace::new();
        let bid = market.submit_bid("agent_a", "task_1", 100, "exec", 1000).unwrap();
        let asgn = market.assign_bid(&bid.bid_id, 500, 100, 2000).unwrap();
        let proof = compute_settlement_proof("agent_a", "task_1", 100, "receipt_abc");
        let settlement = market.settle(&asgn.assignment_id, &proof, 3000).unwrap();
        assert_eq!(settlement.status, SettlementStatus::Completed);
        assert_eq!(settlement.settled_cents, 100);
        assert!(!settlement.proof_hash.is_empty());
        assert_eq!(market.treasury_committed_cents, 0);
        assert_eq!(market.treasury_settled_cents, 100);
        assert_eq!(market.assignments.len(), 0);
        assert_eq!(market.settlements.len(), 1);
    }

    #[test]
    fn settle_rejects_empty_proof() {
        let mut market = Marketplace::new();
        let bid = market.submit_bid("a", "t", 50, "exec", 1000).unwrap();
        let asgn = market.assign_bid(&bid.bid_id, 500, 100, 2000).unwrap();
        let result = market.settle(&asgn.assignment_id, "", 3000);
        assert!(result.is_err());
    }

    #[test]
    fn settle_rejects_unknown_assignment() {
        let mut market = Marketplace::new();
        let result = market.settle("nonexistent", "0xproof", 3000);
        assert!(result.is_err());
    }

    #[test]
    fn settlement_proof_is_deterministic() {
        let p1 = compute_settlement_proof("a", "t", 100, "receipt");
        let p2 = compute_settlement_proof("a", "t", 100, "receipt");
        assert_eq!(p1, p2);
        assert!(p1.starts_with("0x"));
        assert_eq!(p1.len(), 66);
    }

    #[test]
    fn settlement_proof_changes_with_input() {
        let p1 = compute_settlement_proof("a", "t", 100, "receipt_1");
        let p2 = compute_settlement_proof("a", "t", 100, "receipt_2");
        assert_ne!(p1, p2);
    }

    #[test]
    fn full_lifecycle_bid_assign_settle() {
        let mut market = Marketplace::new();
        // Multiple bids
        let bid1 = market.submit_bid("agent_a", "task_1", 80, "fast_exec", 1000).unwrap();
        let _bid2 = market.submit_bid("agent_b", "task_1", 120, "quality_exec", 1000).unwrap();
        assert_eq!(market.open_bids.len(), 2);

        // Assign cheapest
        let asgn = market.assign_bid(&bid1.bid_id, 500, 100, 2000).unwrap();
        assert_eq!(market.open_bids.len(), 1); // other bid still open
        assert_eq!(market.treasury_committed_cents, 80);

        // Settle
        let proof = compute_settlement_proof("agent_a", "task_1", 80, "execution_trace_hash");
        let settlement = market.settle(&asgn.assignment_id, &proof, 3000).unwrap();
        assert_eq!(settlement.settled_cents, 80);
        assert_eq!(market.treasury_settled_cents, 80);
        assert_eq!(market.treasury_committed_cents, 0);

        let summary = market.summary();
        assert_eq!(summary["open_bids"], 1);
        assert_eq!(summary["completed_settlements"], 1);
    }
}
