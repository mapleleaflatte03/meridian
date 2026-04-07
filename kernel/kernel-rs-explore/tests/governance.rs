use meridian_kernel_rs_explore::{
    commit_spend, evaluate_action,
    ActionRequest, DecisionStatus, TreasuryState,
    AuthorityPolicy, CourtState, GovernancePipeline, GovernanceResult,
};

fn base_request() -> ActionRequest {
    ActionRequest {
        org_id: "org_demo".to_string(),
        agent_id: "agent_atlas".to_string(),
        capability: "loom.terminal.exec.v1".to_string(),
        estimated_cost_cents: 75,
        warrant_bound: true,
        authority_ok: true,
        court_ok: true,
    }
}

#[test]
fn allows_action_when_governance_and_treasury_checks_pass() {
    let request = base_request();
    let treasury = TreasuryState {
        balance_cents: 400,
        reserve_floor_cents: 250,
    };
    let decision = evaluate_action(&request, &treasury);
    assert_eq!(decision.status, DecisionStatus::Allow);
    assert_eq!(decision.reason, "governance_checks_passed");
    assert_eq!(decision.proof.schema_version, "meridian.kernel.rs.explore.proof.v1");
}

#[test]
fn denies_action_when_reserve_floor_would_be_breached() {
    let request = base_request();
    let treasury = TreasuryState {
        balance_cents: 300,
        reserve_floor_cents: 260,
    };
    let decision = evaluate_action(&request, &treasury);
    assert_eq!(decision.status, DecisionStatus::Deny);
    assert_eq!(decision.reason, "treasury_reserve_floor_breach");
}

#[test]
fn denies_action_when_warrant_is_missing() {
    let mut request = base_request();
    request.warrant_bound = false;
    let treasury = TreasuryState {
        balance_cents: 500,
        reserve_floor_cents: 100,
    };
    let decision = evaluate_action(&request, &treasury);
    assert_eq!(decision.status, DecisionStatus::Deny);
    assert_eq!(decision.reason, "warrant_missing");
}

#[test]
fn commit_spend_reduces_balance_without_underflow() {
    let treasury = TreasuryState {
        balance_cents: 80,
        reserve_floor_cents: 40,
    };
    let updated = commit_spend(&treasury, 75);
    assert_eq!(updated.balance_cents, 5);
    let clamped = commit_spend(&updated, 200);
    assert_eq!(clamped.balance_cents, 0);
}

// -- Authority primitive tests --

#[test]
fn authority_allows_permitted_capability() {
    let policy = AuthorityPolicy {
        allowed_capabilities: vec!["loom.terminal.exec.v1".to_string()],
        denied_agents: vec![],
    };
    assert!(policy.is_allowed("agent_atlas", "loom.terminal.exec.v1"));
}

#[test]
fn authority_denies_unpermitted_capability() {
    let policy = AuthorityPolicy {
        allowed_capabilities: vec!["loom.terminal.exec.v1".to_string()],
        denied_agents: vec![],
    };
    assert!(!policy.is_allowed("agent_atlas", "loom.admin.destroy.v1"));
}

#[test]
fn authority_denies_blacklisted_agent() {
    let policy = AuthorityPolicy {
        allowed_capabilities: vec!["loom.terminal.exec.v1".to_string()],
        denied_agents: vec!["rogue_agent".to_string()],
    };
    assert!(!policy.is_allowed("rogue_agent", "loom.terminal.exec.v1"));
}

// -- Court primitive tests --

#[test]
fn court_clear_allows_action() {
    let court = CourtState { active_sanctions: vec![] };
    assert!(court.is_clear("agent_atlas"));
}

#[test]
fn court_sanction_blocks_agent() {
    let court = CourtState {
        active_sanctions: vec!["agent_rogue".to_string()],
    };
    assert!(!court.is_clear("agent_rogue"));
    assert!(court.is_clear("agent_atlas"));
}

// -- Full governance pipeline tests --

#[test]
fn pipeline_allows_fully_governed_action() {
    let pipeline = GovernancePipeline {
        authority: AuthorityPolicy {
            allowed_capabilities: vec!["exec".to_string()],
            denied_agents: vec![],
        },
        court: CourtState { active_sanctions: vec![] },
        treasury: TreasuryState { balance_cents: 500, reserve_floor_cents: 100 },
    };
    let result = pipeline.execute("agent_a", "exec", 50);
    assert!(matches!(result, GovernanceResult::Allow { .. }));
    if let GovernanceResult::Allow { proof_hash, updated_treasury } = result {
        assert!(!proof_hash.is_empty());
        assert_eq!(updated_treasury.balance_cents, 450);
    }
}

#[test]
fn pipeline_denies_when_court_sanctioned() {
    let pipeline = GovernancePipeline {
        authority: AuthorityPolicy {
            allowed_capabilities: vec!["exec".to_string()],
            denied_agents: vec![],
        },
        court: CourtState {
            active_sanctions: vec!["agent_bad".to_string()],
        },
        treasury: TreasuryState { balance_cents: 500, reserve_floor_cents: 100 },
    };
    let result = pipeline.execute("agent_bad", "exec", 50);
    assert!(matches!(result, GovernanceResult::Deny { .. }));
}

#[test]
fn pipeline_denies_when_authority_rejects() {
    let pipeline = GovernancePipeline {
        authority: AuthorityPolicy {
            allowed_capabilities: vec!["exec".to_string()],
            denied_agents: vec![],
        },
        court: CourtState { active_sanctions: vec![] },
        treasury: TreasuryState { balance_cents: 500, reserve_floor_cents: 100 },
    };
    let result = pipeline.execute("agent_a", "admin_destroy", 50);
    assert!(matches!(result, GovernanceResult::Deny { .. }));
}

#[test]
fn pipeline_denies_when_treasury_insufficient() {
    let pipeline = GovernancePipeline {
        authority: AuthorityPolicy {
            allowed_capabilities: vec!["exec".to_string()],
            denied_agents: vec![],
        },
        court: CourtState { active_sanctions: vec![] },
        treasury: TreasuryState { balance_cents: 50, reserve_floor_cents: 40 },
    };
    let result = pipeline.execute("agent_a", "exec", 50);
    assert!(matches!(result, GovernanceResult::Deny { .. }));
}

#[test]
fn pipeline_proof_hash_is_deterministic() {
    let pipeline = GovernancePipeline {
        authority: AuthorityPolicy {
            allowed_capabilities: vec!["exec".to_string()],
            denied_agents: vec![],
        },
        court: CourtState { active_sanctions: vec![] },
        treasury: TreasuryState { balance_cents: 500, reserve_floor_cents: 100 },
    };
    let r1 = pipeline.execute("agent_a", "exec", 50);
    let r2 = pipeline.execute("agent_a", "exec", 50);
    match (r1, r2) {
        (GovernanceResult::Allow { proof_hash: h1, .. }, GovernanceResult::Allow { proof_hash: h2, .. }) => {
            assert_eq!(h1, h2, "proof hash must be deterministic for same inputs");
        }
        _ => panic!("both should be Allow"),
    }
}

