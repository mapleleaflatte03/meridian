#!/usr/bin/env python3
"""
Live warrant primitives for Meridian.

The live runtime is still founding-only, but warrant objects should already
exist as first-class capsule-backed records instead of ad hoc fields on
delivery requests.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import uuid

from capsule import capsule_path


ACTION_CLASSES = (
    'routine_internal',
    'budget_spend',
    'payout_execution',
    'cross_institution_commitment',
    'sanction_execution',
    'federated_execution',
)

RISK_CLASSES = (
    'low',
    'moderate',
    'high',
    'critical',
)

COURT_REVIEW_STATES = (
    'auto_issued',
    'pending_review',
    'approved',
    'stayed',
    'revoked',
)

EXECUTION_STATES = (
    'ready',
    'executed',
)

FEDERATION_WARRANT_ACTIONS = {
    'execution_request': 'federated_execution',
    'commitment_proposal': 'cross_institution_commitment',
    'commitment_acceptance': 'cross_institution_commitment',
    'commitment_breach_notice': 'cross_institution_commitment',
}

DEFAULT_TTL_SECONDS = 1800
MAX_TTL_SECONDS = 24 * 3600


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _parse_ts(value):
    return datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')


def _payload_hash(payload):
    if payload is None:
        return ''
    if isinstance(payload, bytes):
        raw = payload
    elif isinstance(payload, str):
        raw = payload.encode('utf-8')
    else:
        raw = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _store_path(org_id=None):
    return capsule_path(org_id, 'warrants.json')


def _empty_store():
    return {
        'warrants': {},
        'updatedAt': _now(),
        'action_classes': list(ACTION_CLASSES),
        'risk_classes': list(RISK_CLASSES),
        'court_review_states': list(COURT_REVIEW_STATES),
        'execution_states': list(EXECUTION_STATES),
    }


def _load_store(org_id=None):
    path = _store_path(org_id)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return _empty_store()


def _save_store(data, org_id=None):
    data['updatedAt'] = _now()
    path = _store_path(org_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2, sort_keys=True)


def warrant_action_for_message(message_type):
    return FEDERATION_WARRANT_ACTIONS.get((message_type or '').strip(), '')


def _warrant_view(record):
    view = dict(record or {})
    expires_at = str(view.get('expires_at') or '').strip()
    try:
        expired = bool(expires_at) and _parse_ts(expires_at) <= _parse_ts(_now())
    except (TypeError, ValueError):
        expired = False
    view['expired'] = expired
    view['archived'] = expired or str(view.get('court_review_state') or '').strip() in {'revoked', 'stayed'}
    return view


def issue_warrant(org_id, action_class, boundary_name, actor_id, *,
                  session_id='', request_payload=None, risk_class='moderate',
                  evidence_refs=None, policy_refs=None, ttl_seconds=None,
                  auto_issue=False, note=''):
    action_class = (action_class or '').strip()
    if action_class not in ACTION_CLASSES:
        raise ValueError(f'Unknown action_class {action_class!r}. Must be one of {ACTION_CLASSES}')
    risk_class = (risk_class or '').strip()
    if risk_class not in RISK_CLASSES:
        raise ValueError(f'Unknown risk_class {risk_class!r}. Must be one of {RISK_CLASSES}')
    boundary_name = (boundary_name or '').strip()
    if not boundary_name:
        raise ValueError('boundary_name is required')
    actor_id = (actor_id or '').strip()
    if not actor_id:
        raise ValueError('actor_id is required')

    ttl = ttl_seconds if ttl_seconds is not None else DEFAULT_TTL_SECONDS
    if ttl <= 0:
        raise ValueError('ttl_seconds must be positive')
    ttl = min(int(ttl), MAX_TTL_SECONDS)
    issued_at = _parse_ts(_now())
    review_state = 'auto_issued' if auto_issue else 'pending_review'

    warrant_id = f'war_{uuid.uuid4().hex[:12]}'
    record = {
        'warrant_id': warrant_id,
        'institution_id': org_id,
        'boundary_name': boundary_name,
        'action_class': action_class,
        'risk_class': risk_class,
        'actor_id': actor_id,
        'session_id': (session_id or '').strip(),
        'request_hash': _payload_hash(request_payload),
        'evidence_refs': list(evidence_refs or []),
        'policy_refs': list(policy_refs or []),
        'court_review_state': review_state,
        'issued_at': issued_at.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'expires_at': (issued_at + datetime.timedelta(seconds=ttl)).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'execution_state': 'ready',
        'executed_at': '',
        'execution_refs': {},
        'reviewed_by': '',
        'reviewed_at': '',
        'review_note': '',
        'note': note or '',
    }
    store = _load_store(org_id)
    store.setdefault('warrants', {})[warrant_id] = record
    _save_store(store, org_id)
    return record


def list_warrants(org_id=None, *, action_class=None, review_state=None, execution_state=None,
                  include_archived=True, archived_only=False, expired_only=False):
    store = _load_store(org_id)
    warrants = [_warrant_view(item) for item in store.get('warrants', {}).values()]
    if action_class:
        warrants = [w for w in warrants if w.get('action_class') == action_class]
    if review_state:
        warrants = [w for w in warrants if w.get('court_review_state') == review_state]
    if execution_state:
        warrants = [w for w in warrants if w.get('execution_state') == execution_state]
    if expired_only:
        warrants = [w for w in warrants if bool(w.get('expired'))]
    elif archived_only:
        warrants = [w for w in warrants if bool(w.get('archived'))]
    elif not include_archived:
        warrants = [w for w in warrants if not bool(w.get('archived'))]
    warrants.sort(key=lambda row: row.get('issued_at', ''), reverse=True)
    return warrants


def get_warrant(warrant_id, org_id=None):
    if not warrant_id:
        return None
    store = _load_store(org_id)
    record = store.get('warrants', {}).get(warrant_id)
    return _warrant_view(record) if record else None


def review_warrant(warrant_id, decision, by, *, org_id=None, note=''):
    decision = (decision or '').strip()
    state_map = {
        'approve': 'approved',
        'stay': 'stayed',
        'revoke': 'revoked',
    }
    if decision not in state_map:
        raise ValueError(f'Unsupported warrant decision: {decision}')
    store = _load_store(org_id)
    record = store.get('warrants', {}).get(warrant_id)
    if not record:
        raise ValueError(f'Warrant not found: {warrant_id}')
    record['court_review_state'] = state_map[decision]
    record['reviewed_by'] = (by or '').strip()
    record['reviewed_at'] = _now()
    record['review_note'] = note or ''
    _save_store(store, org_id)
    return record


def validate_warrant_for_execution(warrant_id, *, org_id=None, action_class='',
                                   boundary_name='', actor_id='', session_id='',
                                   request_payload=None):
    record = get_warrant(warrant_id, org_id=org_id)
    if not record:
        raise PermissionError(f"Warrant '{warrant_id}' does not exist")
    if action_class and record.get('action_class') != action_class:
        raise PermissionError(
            f"Warrant '{warrant_id}' action_class {record.get('action_class', '')!r} "
            f"does not match {action_class!r}"
        )
    if boundary_name and record.get('boundary_name') != boundary_name:
        raise PermissionError(
            f"Warrant '{warrant_id}' boundary {record.get('boundary_name', '')!r} "
            f"does not match {boundary_name!r}"
        )
    if record.get('court_review_state') not in ('auto_issued', 'approved'):
        raise PermissionError(
            f"Warrant '{warrant_id}' is not executable "
            f"(court_review_state={record.get('court_review_state', '')})"
        )
    if record.get('execution_state') != 'ready':
        raise PermissionError(
            f"Warrant '{warrant_id}' is not ready for execution "
            f"(execution_state={record.get('execution_state', '')})"
        )
    if _parse_ts(record.get('expires_at', '1970-01-01T00:00:00Z')) <= _parse_ts(_now()):
        raise PermissionError(f"Warrant '{warrant_id}' is expired")
    if actor_id and record.get('actor_id') and record.get('actor_id') != actor_id:
        raise PermissionError(
            f"Warrant '{warrant_id}' actor {record.get('actor_id', '')!r} "
            f"does not match {actor_id!r}"
        )
    if session_id and record.get('session_id') and record.get('session_id') != session_id:
        raise PermissionError(
            f"Warrant '{warrant_id}' session {record.get('session_id', '')!r} "
            f"does not match {session_id!r}"
        )
    request_hash = _payload_hash(request_payload)
    if record.get('request_hash') and record.get('request_hash') != request_hash:
        raise PermissionError(f"Warrant '{warrant_id}' request hash does not match execution payload")
    return record


def mark_warrant_executed(warrant_id, *, org_id=None, execution_refs=None):
    store = _load_store(org_id)
    record = store.get('warrants', {}).get(warrant_id)
    if not record:
        raise ValueError(f'Warrant not found: {warrant_id}')
    if record.get('execution_state') != 'ready':
        raise ValueError(
            f"Warrant '{warrant_id}' execution_state is {record.get('execution_state', '')}, not 'ready'"
        )
    record['execution_state'] = 'executed'
    record['executed_at'] = _now()
    record['execution_refs'] = dict(execution_refs or {})
    _save_store(store, org_id)
    return record
