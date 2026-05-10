#!/usr/bin/env python3
"""Constitutional execution traces for Meridian.

Every /api/run response carries a machine-readable constitutional_trace that
proves what governed the execution: authority posture, treasury gate, court
posture, route decision, and execution proof hash.

This is the visible proof that Meridian governs execution — not just claims
governance exists, but demonstrates it in every response.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import secrets
import sys
import time
from typing import Any

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
if PLATFORM_DIR not in sys.path:
    sys.path.insert(0, PLATFORM_DIR)

from authority import _load_queue, get_pending_approvals, get_sprint_lead, is_kill_switch_engaged
from court import get_restrictions as court_get_restrictions
from treasury import treasury_snapshot as _treasury_snapshot

SCHEMA_VERSION = 'constitutional_trace.v1'
TRACE_FILE_ENV = 'MERIDIAN_CONSTITUTIONAL_TRACE_FILE'


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _proof_hash(output: str) -> str:
    if not output:
        return ''
    return hashlib.sha256(output.encode('utf-8')).hexdigest()


def _authority_posture(org_id: str) -> dict[str, Any]:
    """Snapshot the authority posture at execution time."""
    kill_engaged = is_kill_switch_engaged(org_id)
    lead_id, lead_auth = get_sprint_lead(org_id)
    pending = list(get_pending_approvals(org_id=org_id))
    queue = _load_queue(org_id)
    delegations = [
        d for d in (queue.get('delegations') or {}).values()
        if d.get('org_id') in (None, '', org_id)
    ]
    return {
        'kill_switch_engaged': bool(kill_engaged),
        'sprint_lead_agent_id': str(lead_id or ''),
        'sprint_lead_auth': int(lead_auth or 0),
        'delegation_count': len(delegations),
        'pending_approvals': len(pending),
    }


def _treasury_posture(org_id: str) -> dict[str, Any]:
    """Snapshot the treasury posture at execution time."""
    snap = _treasury_snapshot(org_id)
    return {
        'balance_usd': float(snap.get('balance_usd', 0.0) or 0.0),
        'reserve_floor_usd': float(snap.get('reserve_floor_usd', 0.0) or 0.0),
        'runway_usd': float(snap.get('runway_usd', 0.0) or 0.0),
        'above_reserve': bool(snap.get('above_reserve', False)),
        'budget_gate': 'passed' if snap.get('above_reserve', False) else 'blocked',
    }


def _court_posture(org_id: str, agent_id: str = '') -> dict[str, Any]:
    """Snapshot the court posture at execution time."""
    restrictions = court_get_restrictions(agent_id, org_id=org_id) if agent_id else []
    blocking = [r for r in (restrictions or []) if r.get('severity', 0) >= 3]
    posture = 'clean'
    if blocking:
        posture = 'blocked'
    elif restrictions:
        posture = 'restricted'
    return {
        'active_sanctions': len(restrictions or []),
        'blocking_violations': len(blocking),
        'posture': posture,
    }


def _route_summary(plan: dict[str, Any]) -> dict[str, Any]:
    """Extract the route decision summary from the plan."""
    routing_score = dict(plan.get('routing_score') or {})
    workers = [str(w) for w in (plan.get('workers') or [])]
    skill_names = [
        str(item.get('name') or '').strip()
        for item in (plan.get('skills') or [])
        if isinstance(item, dict) and str(item.get('name') or '').strip()
    ]
    return {
        'mode': str(plan.get('mode') or '').strip(),
        'reason': str(plan.get('reason') or '').strip(),
        'decision': str(routing_score.get('decision') or '').strip(),
        'confidence': routing_score.get('confidence'),
        'workers': workers,
        'skills_used': skill_names,
    }


def _execution_summary(
    steps: list[dict[str, Any]],
    output: str,
    *,
    mode: str = '',
) -> dict[str, Any]:
    """Summarize execution results with proof hash."""
    completed_statuses = {'ok', 'success', 'completed'}
    completed = [
        s for s in steps
        if s.get('ok') or str(s.get('status') or '').strip().lower() in completed_statuses
    ]
    failed = [
        s for s in steps
        if not (s.get('ok') or str(s.get('status') or '').strip().lower() in completed_statuses)
    ]
    return {
        'steps_total': len(steps),
        'steps_completed': len(completed),
        'steps_failed': len(failed),
        'manager_synthesized': mode != 'direct' and len(steps) > 0,
        'proof_hash': f'sha256:{_proof_hash(output)}' if output else '',
    }


def build_constitutional_trace(
    *,
    org_id: str,
    session_key: str = '',
    agent_id: str = '',
    plan: dict[str, Any] | None = None,
    steps: list[dict[str, Any]] | None = None,
    output: str = '',
    mode: str = '',
) -> dict[str, Any]:
    """Build a complete constitutional execution trace.

    This is the machine-readable proof that governance was active during
    execution. Every field is sourced from live kernel state, not fabricated.
    """
    plan = plan or {}
    steps = steps or []
    mode = mode or str(plan.get('mode') or '').strip()
    trace_id = f'ctrace_{int(time.time() * 1000)}_{secrets.token_hex(4)}'

    return {
        'schema_version': SCHEMA_VERSION,
        'trace_id': trace_id,
        'timestamp': _now(),
        'institution_id': org_id,
        'session_key': session_key,
        'authority': _authority_posture(org_id),
        'treasury': _treasury_posture(org_id),
        'court': _court_posture(org_id, agent_id),
        'route': _route_summary(plan),
        'execution': _execution_summary(steps, output, mode=mode),
    }


def trace_file_path() -> str:
    """Resolve the constitutional trace JSONL file path."""
    default = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(PLATFORM_DIR))),
        'state',
        'constitutional_traces.jsonl',
    )
    return os.environ.get(TRACE_FILE_ENV, default)


def persist_trace(trace: dict[str, Any]) -> str:
    """Append a constitutional trace to the JSONL file. Returns the file path."""
    path = trace_file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(trace, ensure_ascii=False, sort_keys=True) + '\n')
    return path


def load_recent_traces(*, limit: int = 50) -> list[dict[str, Any]]:
    """Load the most recent constitutional traces from the JSONL file."""
    path = trace_file_path()
    if not os.path.exists(path):
        return []
    traces: list[dict[str, Any]] = []
    with open(path, 'r', encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                traces.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
    traces.sort(key=lambda t: t.get('timestamp', ''), reverse=True)
    return traces[:limit]
