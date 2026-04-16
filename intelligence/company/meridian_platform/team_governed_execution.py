#!/usr/bin/env python3
"""Team-governed execution wrapper for Meridian Team depth."""

from __future__ import annotations

import importlib.util
import json
import os
from typing import Any

from audit import log_event, query_events, stats
from authority import _load_queue, get_pending_approvals, get_sprint_lead
from treasury import treasury_snapshot
import side_hustle
from agent_registry import check_budget

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MERIDIAN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PLATFORM_DIR))))

_court_spec = importlib.util.spec_from_file_location(
    'meridian_team_governed_execution_court',
    os.path.join(PLATFORM_DIR, 'court.py'),
)
_court_mod = importlib.util.module_from_spec(_court_spec)
_court_spec.loader.exec_module(_court_mod)
get_violations = _court_mod.get_violations
get_agent_record = _court_mod.get_agent_record


def onboard_state_path(*, meridian_root: str = '') -> str:
    root = str(meridian_root or os.environ.get('MERIDIAN_ROOT') or DEFAULT_MERIDIAN_ROOT).strip()
    return os.path.join(root, 'runtime', 'onboard_state.json')


def load_onboard_state(*, meridian_root: str = '') -> dict[str, Any]:
    path = onboard_state_path(meridian_root=meridian_root)
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as fh:
        payload = json.load(fh)
    return payload if isinstance(payload, dict) else {}


def require_team_mode(onboard_state: dict[str, Any]) -> tuple[bool, str]:
    mode = str((onboard_state or {}).get('mode') or '').strip().lower()
    if mode != 'team':
        return False, 'Team governed execution requires Meridian Team mode.'
    return True, 'ok'


def _public_sprint_lead_snapshot(org_id: str) -> dict[str, Any]:
    lead_id, lead_auth = get_sprint_lead(org_id)
    if not lead_id:
        return {
            'agent_id': '',
            'economy_key': '',
            'agent_name': '',
            'auth': lead_auth,
            'auth_source': 'economy_sprint_lead',
            'authority_alignment': 'no_agent',
        }
    return {
        'agent_id': lead_id,
        'economy_key': lead_id,
        'agent_name': '',
        'auth': lead_auth,
        'auth_source': 'economy_sprint_lead',
        'authority_alignment': 'unknown_agent',
    }


def _authority_snapshot(org_id: str) -> dict[str, Any]:
    queue = _load_queue(org_id)
    return {
        'kill_switch': dict(queue.get('kill_switch') or {}),
        'pending_approvals': list(get_pending_approvals(org_id=org_id)),
        'delegations': [
            dict(item)
            for item in (queue.get('delegations') or {}).values()
            if item.get('org_id') in (None, '', org_id)
        ],
        'sprint_lead': _public_sprint_lead_snapshot(org_id),
    }


def _governance_checks(agent_id: str, org_id: str, estimated_cost_usd: float) -> dict[str, Any]:
    blocking_violations = []
    for status in ('sanctioned', 'open'):
        for violation in get_violations(agent_id=agent_id, status=status, org_id=org_id):
            if int(violation.get('severity') or 0) >= 3:
                blocking_violations.append(dict(violation))
    court_allowed = not blocking_violations
    budget_allowed, budget_reason = check_budget(agent_id, estimated_cost_usd) if estimated_cost_usd > 0 else (True, 'ok')
    court_reason = 'ok'
    if blocking_violations:
        first = blocking_violations[0]
        court_reason = (
            f"Court violation block: {first.get('type', 'unknown')} "
            f"(severity {first.get('severity', 0)})"
        )
    return {
        'court': {
            'allowed': court_allowed,
            'reason': court_reason,
            'blocking_violations': blocking_violations,
        },
        'budget': {
            'allowed': bool(budget_allowed),
            'reason': budget_reason,
            'estimated_cost_usd': estimated_cost_usd,
        },
    }


def build_audit_export(*,
                       org_id: str,
                       actor_id: str,
                       team_mode: str,
                       request_payload: dict[str, Any],
                       execution_result: dict[str, Any],
                       authority_snapshot: dict[str, Any],
                       treasury_snapshot: dict[str, Any],
                       court_record: dict[str, Any],
                       audit_events: list[dict[str, Any]],
                       audit_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        'artifact_type': 'meridian.team.governed_execution.audit_export.v1',
        'org_id': org_id,
        'actor_id': actor_id,
        'team_mode': team_mode,
        'request': {
            'agent_id': request_payload.get('agent_id', ''),
            'task_description': request_payload.get('task_description', ''),
            'amount_usd': float(request_payload.get('amount_usd', 0.0) or 0.0),
            'estimated_cost_usd': float(request_payload.get('estimated_cost_usd', 0.0) or 0.0),
        },
        'execution': {
            'status': execution_result.get('status', ''),
            'bid_id': execution_result.get('bid_id', ''),
            'assignment_id': execution_result.get('assignment_id', ''),
            'settlement_id': execution_result.get('settlement_id', ''),
            'settlement_receipt': execution_result.get('settlement_receipt', ''),
            'reason': execution_result.get('reason', ''),
            'governance_checks': dict(execution_result.get('governance_checks') or {}),
        },
        'authority': {
            'kill_switch': dict(authority_snapshot.get('kill_switch') or {}),
            'pending_approval_count': len(authority_snapshot.get('pending_approvals') or []),
            'pending_approvals': list(authority_snapshot.get('pending_approvals') or []),
            'delegation_count': len(authority_snapshot.get('delegations') or []),
            'delegations': list(authority_snapshot.get('delegations') or []),
            'sprint_lead': dict(authority_snapshot.get('sprint_lead') or {}),
        },
        'treasury': {
            'balance_usd': float(treasury_snapshot.get('balance_usd', 0.0) or 0.0),
            'reserve_floor_usd': float(treasury_snapshot.get('reserve_floor_usd', 0.0) or 0.0),
            'runway_usd': float(treasury_snapshot.get('runway_usd', 0.0) or 0.0),
            'snapshot': dict(treasury_snapshot),
        },
        'court': {
            'agent_id': court_record.get('agent_id', ''),
            'active_restrictions': list(court_record.get('active_restrictions') or []),
            'open_violations': int(court_record.get('open_violations', 0) or 0),
            'total_violations': int(court_record.get('total_violations', 0) or 0),
            'record': dict(court_record),
        },
        'audit': {
            'event_count': len(audit_events),
            'events': list(audit_events),
            'summary': dict(audit_summary),
        },
        'proof_chain': dict(execution_result.get('proof_chain') or {}),
    }


def run_team_governed_execution(*,
                                org_id: str,
                                actor_id: str,
                                request_payload: dict[str, Any],
                                meridian_root: str = '') -> dict[str, Any]:
    onboard_state = load_onboard_state(meridian_root=meridian_root)
    team_allowed, team_reason = require_team_mode(onboard_state)
    if not team_allowed:
        return {
            'status': 'blocked',
            'reason': team_reason,
            'team_mode': str((onboard_state or {}).get('mode') or ''),
        }

    agent_id = str(request_payload.get('agent_id') or '').strip()
    estimated_cost_usd = float(request_payload.get('estimated_cost_usd', 0.0) or 0.0)
    execution_result = side_hustle.run_side_hustle(
        agent_id=agent_id,
        org_id=org_id,
        task_description=str(request_payload.get('task_description') or ''),
        amount_usd=float(request_payload.get('amount_usd', 0.0) or 0.0),
        proof_receipt=str(request_payload.get('proof_receipt') or ''),
        assigned_by=str(request_payload.get('assigned_by') or ''),
        settled_by=str(request_payload.get('settled_by') or ''),
        estimated_cost_usd=estimated_cost_usd,
    )
    governance_checks = _governance_checks(agent_id, org_id, estimated_cost_usd)
    execution_result = {
        **dict(execution_result or {}),
        'governance_checks': governance_checks,
    }

    authority_snapshot = _authority_snapshot(org_id)
    treasury_view = treasury_snapshot(org_id)
    court_record = get_agent_record(agent_id, org_id=org_id)
    audit_events = list(query_events(org_id=org_id, limit=50))
    audit_summary = dict(stats(org_id))
    artifact = build_audit_export(
        org_id=org_id,
        actor_id=actor_id,
        team_mode='team',
        request_payload=request_payload,
        execution_result=execution_result,
        authority_snapshot=authority_snapshot,
        treasury_snapshot=treasury_view,
        court_record=court_record,
        audit_events=audit_events,
        audit_summary=audit_summary,
    )
    log_event(
        org_id,
        actor_id,
        'team_governed_execution_exported',
        resource=agent_id,
        outcome='success' if execution_result.get('status') == 'settled' else 'blocked',
        details={
            'status': execution_result.get('status', ''),
            'reason': execution_result.get('reason', ''),
            'audit_event_count': len(audit_events),
            'proof_chain': dict(execution_result.get('proof_chain') or {}),
        },
    )
    return {
        **execution_result,
        'team_mode': 'team',
        'authority': authority_snapshot,
        'treasury': treasury_view,
        'court': court_record,
        'audit_export': artifact,
    }
