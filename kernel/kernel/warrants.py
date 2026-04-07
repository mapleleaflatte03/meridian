#!/usr/bin/env python3
"""
Court-first warrant primitives for Meridian Kernel.

Warrants are reviewable proof objects for sensitive actions. This module does
not pretend to complete the whole constitutional autonomy program. It does
establish the first real object and execution gate:

- warrants are institution-scoped and file-backed
- warrants carry action class, boundary, actor/session, request hash, and TTL
- sensitive sender-side federation execution can require an executable warrant
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
import uuid
try:
    from io_atomic import atomic_write_json
except ModuleNotFoundError:
    PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
    if PLATFORM_DIR not in sys.path:
        sys.path.insert(0, PLATFORM_DIR)
    from io_atomic import atomic_write_json


PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(PLATFORM_DIR)
ECONOMY_DIR = os.path.join(WORKSPACE, 'economy')

if PLATFORM_DIR not in sys.path:
    sys.path.insert(0, PLATFORM_DIR)

try:
    from capsule import capsule_path
except ImportError:
    def capsule_path(org_id, filename):
        return os.path.join(ECONOMY_DIR, filename)


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


def _missing_org_error(org_id):
    raise SystemExit(
        f"ERROR: institution '{org_id}' is not initialized. Run quickstart.py --init-only or bootstrap the capsule first."
    )


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
    parent = os.path.dirname(path)
    if org_id and not os.path.isdir(parent):
        _missing_org_error(org_id)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return _empty_store()


def _save_store(data, org_id=None):
    data['updatedAt'] = _now()
    path = _store_path(org_id)
    parent = os.path.dirname(path)
    if org_id and not os.path.isdir(parent):
        _missing_org_error(org_id)
    os.makedirs(parent, exist_ok=True)
    atomic_write_json(path, data)


def warrant_action_for_message(message_type):
    return FEDERATION_WARRANT_ACTIONS.get((message_type or '').strip(), '')


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


def list_warrants(org_id=None, *, action_class=None, review_state=None, execution_state=None):
    store = _load_store(org_id)
    warrants = list(store.get('warrants', {}).values())
    if action_class:
        warrants = [w for w in warrants if w.get('action_class') == action_class]
    if review_state:
        warrants = [w for w in warrants if w.get('court_review_state') == review_state]
    if execution_state:
        warrants = [w for w in warrants if w.get('execution_state') == execution_state]
    warrants.sort(key=lambda row: row.get('issued_at', ''), reverse=True)
    return warrants


def get_warrant(warrant_id, org_id=None):
    if not warrant_id:
        return None
    store = _load_store(org_id)
    return store.get('warrants', {}).get(warrant_id)


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


def main():
    parser = argparse.ArgumentParser(description='Warrant management')
    sub = parser.add_subparsers(dest='command')

    issue = sub.add_parser('issue')
    issue.add_argument('--org_id', required=True)
    issue.add_argument('--action_class', required=True)
    issue.add_argument('--boundary_name', required=True)
    issue.add_argument('--actor_id', required=True)
    issue.add_argument('--session_id', default='')
    issue.add_argument('--risk_class', default='moderate')
    issue.add_argument('--ttl_seconds', type=int, default=DEFAULT_TTL_SECONDS)
    issue.add_argument('--auto_issue', action='store_true')

    show = sub.add_parser('show')
    show.add_argument('--org_id', required=True)

    review = sub.add_parser('review')
    review.add_argument('--org_id', required=True)
    review.add_argument('--warrant_id', required=True)
    review.add_argument('--decision', required=True)
    review.add_argument('--by', required=True)

    args = parser.parse_args()
    if args.command == 'issue':
        print(json.dumps(issue_warrant(
            args.org_id,
            args.action_class,
            args.boundary_name,
            args.actor_id,
            session_id=args.session_id,
            risk_class=args.risk_class,
            ttl_seconds=args.ttl_seconds,
            auto_issue=args.auto_issue,
        ), indent=2))
    elif args.command == 'show':
        print(json.dumps({'warrants': list_warrants(args.org_id)}, indent=2))
    elif args.command == 'review':
        print(json.dumps(review_warrant(
            args.warrant_id,
            args.decision,
            args.by,
            org_id=args.org_id,
        ), indent=2))
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
