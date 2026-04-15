#!/usr/bin/env python3
"""Side Hustle integration logic for Autonomous Agent Earning Loops.

Enforces governance rules (court checks) before executing autonomous spending
or earning actions.
"""
import agent_registry
from agent_registry import check_budget
import brain_router
from court import get_violations
import memory_graph
from marketplace import post_bid, assign_bid, settle_bid


def ensure_hustle_agent(agent_id: str, org_id: str) -> str:
    """Ensure the agent exists in the registry. Register if missing.

    Returns the verified agent_id (may be the same or a newly registered one).
    """
    registry = agent_registry.load_registry()
    if agent_id in registry.get('agents', {}):
        return agent_id
    # Agent not found — register it as a side-hustle executor
    new_id = agent_registry.register_agent(
        org_id=org_id,
        name=agent_id,
        role='executor',
        purpose='Autonomous side hustle agent',
    )
    return new_id


def can_hustle(agent_id: str, org_id: str, cost_usd: float = 0.0) -> tuple[bool, str]:
    """Check if an agent is allowed to execute a side hustle.

    Returns:
        (bool, str): (True, "ok") if allowed, (False, reason) if blocked.
    """
    # 1. Check Court Violations — severity >= 3 is blocking
    for status in ('sanctioned', 'open'):
        for v in get_violations(agent_id=agent_id, status=status, org_id=org_id):
            if v.get('severity', 0) >= 3:
                return False, f"Court violation block: {v.get('type')} (severity {v.get('severity')})"

    # 2. Check Budget
    if cost_usd > 0.0:
        allowed, reason = check_budget(agent_id, cost_usd)
        if not allowed:
            return False, f"Budget block: {reason}"

    return True, "ok"


def run_side_hustle(
    agent_id: str,
    org_id: str,
    task_description: str,
    amount_usd: float,
    proof_receipt: str,
    assigned_by: str,
    settled_by: str,
    estimated_cost_usd: float = 0.0,
) -> dict:
    """Orchestrate an autonomous side hustle from governance-check to settlement.

    Governance is always evaluated first. If blocked, returns status='blocked'.
    On success returns a full proof chain: bid_receipt -> settlement_receipt.

    Args:
        estimated_cost_usd: Optional per-run cost estimate for budget gate.
    """
    # Ensure agent exists in registry (auto-register if missing)
    agent_id = ensure_hustle_agent(agent_id, org_id)

    # Pre-flight governance check (Court + Budget)
    allowed, reason = can_hustle(agent_id, org_id, cost_usd=estimated_cost_usd)
    if not allowed:
        return {'status': 'blocked', 'reason': reason}

    # Execute earning loop
    bid_id, bid_receipt = post_bid(agent_id, task_description, amount_usd, org_id)
    assignment_id = assign_bid(bid_id, assigned_by, org_id)

    work_execution = brain_router.execute_manager(
        runtime_env={
            'MERIDIAN_ORG_ID': org_id,
            'MERIDIAN_WORKSPACE_ORG_ID': org_id,
        },
        system_prompt='You are Meridian Autonomous Side Hustle worker. Execute the task and return the completed output.',
        user_prompt=task_description,
        model='',
        timeout=90,
    )

    if not work_execution.get('ok'):
        return {
            'status': 'execution_failed',
            'reason': str(work_execution.get('stderr') or 'brain_router execution failed'),
            'execution_error_code': str(work_execution.get('error_code') or ''),
            'execution_error_metadata': work_execution.get('error_metadata') or {},
            'provider_profile': str(work_execution.get('provider_profile') or ''),
            'transport_kind': str(work_execution.get('transport_kind') or ''),
            'auth_mode': str(work_execution.get('auth_mode') or ''),
            'policy_source': str(work_execution.get('policy_source') or ''),
            'policy_route_id': str(work_execution.get('policy_route_id') or ''),
            'policy_auth_profile': str(work_execution.get('policy_auth_profile') or ''),
            'failover_trace': list(work_execution.get('failover_trace') or []),
            'bid_id': bid_id,
            'assignment_id': assignment_id,
        }

    work_output = str(work_execution.get('output_text') or '').strip()
    memory_payload = {
        'agent_id': agent_id,
        'org_id': org_id,
        'task_description': task_description,
        'work_output': work_output,
        'work_execution': work_execution,
    }
    memory_hash, memory_depth = memory_graph.append_node(
        key='side_hustle_execution',
        value=memory_payload,
        org_id=org_id,
        tags=['side_hustle_execution'],
        action_id=bid_id,
        agent_id=agent_id,
    )

    settlement_proof_receipt = f"{proof_receipt}|memory:{memory_hash}"
    settlement_id, settlement_receipt, split = settle_bid(
        bid_id,
        settlement_proof_receipt,
        settled_by,
        org_id,
    )

    return {
        'status': 'settled',
        'bid_id': bid_id,
        'assignment_id': assignment_id,
        'settlement_id': settlement_id,
        'settlement_receipt': settlement_receipt,
        'split': split,
        'work_output': work_output,
        'provider_profile': str(work_execution.get('provider_profile') or ''),
        'transport_kind': str(work_execution.get('transport_kind') or ''),
        'auth_mode': str(work_execution.get('auth_mode') or ''),
        'policy_source': str(work_execution.get('policy_source') or ''),
        'policy_route_id': str(work_execution.get('policy_route_id') or ''),
        'policy_auth_profile': str(work_execution.get('policy_auth_profile') or ''),
        'failover_trace': list(work_execution.get('failover_trace') or []),
        'memory_hash': memory_hash,
        'memory_depth': memory_depth,
        'proof_chain': {
            'proof_receipt': proof_receipt,
            'bid_receipt': bid_receipt,
            'memory_hash': memory_hash,
            'settlement_receipt': settlement_receipt,
        },
    }


def side_hustle_status(runs: list[dict]) -> dict:
    """Compute summary statistics for a list of side hustle run results.

    Args:
        runs: List of run_side_hustle result dicts.

    Returns:
        Summary with total_runs, settled_runs, blocked_runs, success_rate.
    """
    total = len(runs)
    settled = sum(1 for r in runs if r.get('status') == 'settled')
    blocked = sum(1 for r in runs if r.get('status') == 'blocked')
    success_rate = settled / total if total > 0 else 0.0

    return {
        'total_runs': total,
        'settled_runs': settled,
        'blocked_runs': blocked,
        'success_rate': success_rate,
    }
