use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ActionRequest {
    pub org_id: String,
    pub agent_id: String,
    pub capability: String,
    pub estimated_cost_cents: u64,
    pub warrant_bound: bool,
    pub authority_ok: bool,
    pub court_ok: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TreasuryState {
    pub balance_cents: u64,
    pub reserve_floor_cents: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RuntimeProofEnvelope {
    pub schema_version: String,
    pub org_id: String,
    pub agent_id: String,
    pub capability: String,
    pub decision: DecisionStatus,
    pub reason: String,
    pub treasury_balance_cents: u64,
    pub treasury_reserve_floor_cents: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum DecisionStatus {
    Allow,
    Deny,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Decision {
    pub status: DecisionStatus,
    pub reason: String,
    pub proof: RuntimeProofEnvelope,
}

pub fn evaluate_action(request: &ActionRequest, treasury: &TreasuryState) -> Decision {
    let (status, reason) = if !request.warrant_bound {
        (DecisionStatus::Deny, "warrant_missing".to_string())
    } else if !request.authority_ok {
        (DecisionStatus::Deny, "authority_rejected".to_string())
    } else if !request.court_ok {
        (DecisionStatus::Deny, "court_restriction".to_string())
    } else if treasury.balance_cents < request.estimated_cost_cents {
        (DecisionStatus::Deny, "treasury_insufficient_balance".to_string())
    } else if treasury.balance_cents.saturating_sub(request.estimated_cost_cents)
        < treasury.reserve_floor_cents
    {
        (DecisionStatus::Deny, "treasury_reserve_floor_breach".to_string())
    } else {
        (DecisionStatus::Allow, "governance_checks_passed".to_string())
    };

    let proof = RuntimeProofEnvelope {
        schema_version: "meridian.kernel.rs.explore.proof.v1".to_string(),
        org_id: request.org_id.clone(),
        agent_id: request.agent_id.clone(),
        capability: request.capability.clone(),
        decision: status.clone(),
        reason: reason.clone(),
        treasury_balance_cents: treasury.balance_cents,
        treasury_reserve_floor_cents: treasury.reserve_floor_cents,
    };

    Decision {
        status,
        reason,
        proof,
    }
}

pub fn commit_spend(treasury: &TreasuryState, amount_cents: u64) -> TreasuryState {
    TreasuryState {
        balance_cents: treasury.balance_cents.saturating_sub(amount_cents),
        reserve_floor_cents: treasury.reserve_floor_cents,
    }
}

// ---------------------------------------------------------------------------
// Authority primitive
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuthorityPolicy {
    pub allowed_capabilities: Vec<String>,
    pub denied_agents: Vec<String>,
}

impl AuthorityPolicy {
    pub fn is_allowed(&self, agent_id: &str, capability: &str) -> bool {
        if self.denied_agents.iter().any(|a| a == agent_id) {
            return false;
        }
        self.allowed_capabilities.iter().any(|c| c == capability)
    }
}

// ---------------------------------------------------------------------------
// Court primitive
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CourtState {
    pub active_sanctions: Vec<String>,
}

impl CourtState {
    pub fn is_clear(&self, agent_id: &str) -> bool {
        !self.active_sanctions.iter().any(|a| a == agent_id)
    }
}

// ---------------------------------------------------------------------------
// Governance pipeline (Authority -> Court -> Treasury -> Proof)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct GovernancePipeline {
    pub authority: AuthorityPolicy,
    pub court: CourtState,
    pub treasury: TreasuryState,
}

#[derive(Debug, Clone)]
pub enum GovernanceResult {
    Allow {
        proof_hash: String,
        updated_treasury: TreasuryState,
    },
    Deny {
        reason: String,
        stage: String,
    },
}

impl GovernancePipeline {
    /// Execute the full governance pipeline for an action.
    ///
    /// Order: Authority -> Court -> Treasury -> PoGE proof hash.
    /// Returns Allow with a deterministic proof hash and updated treasury,
    /// or Deny with the stage and reason.
    pub fn execute(
        &self,
        agent_id: &str,
        capability: &str,
        cost_cents: u64,
    ) -> GovernanceResult {
        // 1. Authority check
        if !self.authority.is_allowed(agent_id, capability) {
            return GovernanceResult::Deny {
                reason: format!("authority_rejected:{capability}"),
                stage: "authority".to_string(),
            };
        }
        // 2. Court check
        if !self.court.is_clear(agent_id) {
            return GovernanceResult::Deny {
                reason: format!("court_sanction:{agent_id}"),
                stage: "court".to_string(),
            };
        }
        // 3. Treasury check
        if self.treasury.balance_cents < cost_cents {
            return GovernanceResult::Deny {
                reason: "treasury_insufficient_balance".to_string(),
                stage: "treasury".to_string(),
            };
        }
        if self.treasury.balance_cents.saturating_sub(cost_cents)
            < self.treasury.reserve_floor_cents
        {
            return GovernanceResult::Deny {
                reason: "treasury_reserve_floor_breach".to_string(),
                stage: "treasury".to_string(),
            };
        }
        // 4. Commit + proof
        let updated = commit_spend(&self.treasury, cost_cents);
        let proof_hash = compute_proof_hash(agent_id, capability, cost_cents, &updated);
        GovernanceResult::Allow {
            proof_hash,
            updated_treasury: updated,
        }
    }
}

fn compute_proof_hash(
    agent_id: &str,
    capability: &str,
    cost_cents: u64,
    treasury: &TreasuryState,
) -> String {
    let mut hasher = Sha256::new();
    hasher.update(agent_id.as_bytes());
    hasher.update(b"|");
    hasher.update(capability.as_bytes());
    hasher.update(b"|");
    hasher.update(cost_cents.to_le_bytes());
    hasher.update(b"|");
    hasher.update(treasury.balance_cents.to_le_bytes());
    hasher.update(b"|");
    hasher.update(treasury.reserve_floor_cents.to_le_bytes());
    let result = hasher.finalize();
    result.iter().map(|b| format!("{:02x}", b)).collect()
}
