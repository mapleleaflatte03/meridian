#!/usr/bin/env python3
"""
Capsule-backed execution queue for payout settlement attempts.

This store is intentionally narrow:

- execution records are institution-scoped and file-backed
- entries are keyed by execution_id for idempotent upsert
- records preserve the proposal snapshot, adapter contract, and execution
  plan that the actual settlement path used
- no external settlement is claimed here; the queue only records whether the
  payout was previewed, dispatchable, blocked, or executed locally
"""
from __future__ import annotations

import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import sys
import tempfile


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


STORE_FILE = 'payout_execution_queue.json'
LOCK_FILE = '.payout_execution_queue.lock'
QUEUE_STATES = (
    'previewed',
    'dispatchable',
    'executed',
    'blocked',
    'superseded',
)


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _canonical_hash(payload):
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


def _store_path(org_id):
    if not (org_id or '').strip():
        raise ValueError('org_id is required')
    return capsule_path(org_id, STORE_FILE)


def _lock_path(org_id):
    if not (org_id or '').strip():
        raise ValueError('org_id is required')
    return capsule_path(org_id, LOCK_FILE)


def _empty_store(org_id):
    return {
        'version': 1,
        'updatedAt': _now(),
        'payout_execution_records': {},
        'states': list(QUEUE_STATES),
        '_meta': {
            'service_scope': 'institution_owned_service',
            'bound_org_id': (org_id or '').strip(),
        },
    }


def _normalize_state(state, *, existing_state=''):
    state = (state or '').strip().lower()
    existing_state = (existing_state or '').strip().lower()
    if state and state not in QUEUE_STATES:
        raise ValueError(
            f"Unknown payout execution state {state!r}. Must be one of {QUEUE_STATES}"
        )
    if state:
        return state
    return existing_state or 'previewed'


def _normalize_store(data, org_id):
    store = _empty_store(org_id)
    if not isinstance(data, dict):
        return store
    store.update({k: v for k, v in data.items() if k not in ('payout_execution_records', '_meta')})
    meta = dict(store.get('_meta', {}))
    meta.update(data.get('_meta', {}) or {})
    meta['bound_org_id'] = (org_id or '').strip()
    store['_meta'] = meta

    raw_records = data.get('payout_execution_records', {})
    records = {}
    if isinstance(raw_records, list):
        for item in raw_records:
            if isinstance(item, dict) and item.get('execution_id'):
                records[item['execution_id']] = dict(item)
    elif isinstance(raw_records, dict):
        for execution_id, item in raw_records.items():
            if isinstance(item, dict):
                record = dict(item)
                record['execution_id'] = record.get('execution_id') or execution_id
                records[record['execution_id']] = record
    for execution_id, record in list(records.items()):
        record = dict(record or {})
        record['state'] = _normalize_state(record.get('state') or record.get('execution_state') or '')
        record['execution_state'] = record.get('execution_state') or record['state']
        record['generated_at'] = (record.get('generated_at') or record.get('previewed_at') or '').strip()
        record['queued_at'] = (record.get('queued_at') or record['generated_at'] or '').strip()
        record['dispatched_at'] = (record.get('dispatched_at') or '').strip()
        record['executed_at'] = (record.get('executed_at') or '').strip()
        record['updated_at'] = (record.get('updated_at') or '').strip()
        records[execution_id] = record
    store['payout_execution_records'] = records
    if 'states' not in store or not store['states']:
        store['states'] = list(QUEUE_STATES)
    return store


def _load_store(org_id):
    path = _store_path(org_id)
    parent = os.path.dirname(path)
    if org_id and not os.path.isdir(parent):
        _missing_org_error(org_id)
    if os.path.exists(path):
        with open(path) as f:
            return _normalize_store(json.load(f), org_id)
    return _empty_store(org_id)


def _save_store(store, org_id):
    path = _store_path(org_id)
    parent = os.path.dirname(path)
    if org_id and not os.path.isdir(parent):
        _missing_org_error(org_id)
    os.makedirs(parent, exist_ok=True)
    payload = _normalize_store(store, org_id)
    payload['updatedAt'] = _now()
    fd, tmp_path = tempfile.mkstemp(
        prefix='.payout_execution_queue.',
        suffix='.tmp',
        dir=parent,
    )
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return payload


@contextlib.contextmanager
def _execution_lock(org_id):
    path = _lock_path(org_id)
    parent = os.path.dirname(path)
    if org_id and not os.path.isdir(parent):
        _missing_org_error(org_id)
    os.makedirs(parent, exist_ok=True)
    with open(path, 'a+') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _execution_digest(record):
    record = dict(record or {})
    digest_payload = {
        'execution_id': (record.get('execution_id') or '').strip(),
        'bound_org_id': (record.get('bound_org_id') or '').strip(),
        'proposal_id': (record.get('proposal_id') or '').strip(),
        'warrant_id': (record.get('warrant_id') or '').strip(),
        'settlement_adapter': (record.get('settlement_adapter') or '').strip(),
        'state': (record.get('state') or '').strip(),
        'dispatch_ready': bool(record.get('dispatch_ready')),
        'execution_ready': bool(record.get('execution_ready')),
        'settlement_claimed': bool(record.get('settlement_claimed')),
        'external_settlement_observed': bool(record.get('external_settlement_observed')),
        'execution_plan': dict(record.get('execution_plan') or {}),
    }
    return _canonical_hash(digest_payload)


def _normalize_execution(execution, org_id, existing=None):
    execution = dict(execution or {})
    existing = dict(existing or {})
    execution_id = (execution.get('execution_id') or existing.get('execution_id') or '').strip()
    if not execution_id:
        execution_id = (
            execution.get('tx_ref')
            or (execution.get('execution_plan') or {}).get('tx_ref')
            or existing.get('tx_ref')
            or existing.get('proposal_id')
            or ''
        ).strip()
    if not execution_id:
        raise ValueError('execution_id is required')

    record = dict(existing)
    record['execution_id'] = execution_id
    record['bound_org_id'] = (org_id or '').strip()
    record['proposal_id'] = (execution.get('proposal_id') or existing.get('proposal_id') or '').strip()
    record['warrant_id'] = (execution.get('warrant_id') or existing.get('warrant_id') or '').strip()
    record['settlement_adapter'] = (
        execution.get('settlement_adapter')
        or existing.get('settlement_adapter')
        or ''
    ).strip()
    record['state'] = _normalize_state(
        execution.get('state') or execution.get('execution_state') or existing.get('state') or existing.get('execution_state') or '',
        existing_state=existing.get('state') or existing.get('execution_state') or '',
    )
    record['execution_state'] = record['state']
    if 'dispatch_ready' in execution:
        record['dispatch_ready'] = bool(execution.get('dispatch_ready'))
    elif 'dispatch_ready' not in record:
        record['dispatch_ready'] = False
    if 'dispatch_blockers' in execution:
        record['dispatch_blockers'] = list(execution.get('dispatch_blockers') or [])
    elif 'dispatch_blockers' not in record:
        record['dispatch_blockers'] = []
    if 'execution_ready' in execution:
        record['execution_ready'] = bool(execution.get('execution_ready'))
    elif 'execution_ready' not in record:
        record['execution_ready'] = False
    if 'settlement_claimed' in execution:
        record['settlement_claimed'] = bool(execution.get('settlement_claimed'))
    elif 'settlement_claimed' not in record:
        record['settlement_claimed'] = False
    if 'external_settlement_observed' in execution:
        record['external_settlement_observed'] = bool(execution.get('external_settlement_observed'))
    elif 'external_settlement_observed' not in record:
        record['external_settlement_observed'] = False
    if 'proof_type' in execution or 'proof_type' not in record:
        record['proof_type'] = (execution.get('proof_type') or existing.get('proof_type') or '').strip()
    if 'tx_hash' in execution or 'tx_hash' not in record:
        record['tx_hash'] = (execution.get('tx_hash') or existing.get('tx_hash') or '').strip()
    if 'execution_refs' in execution:
        record['execution_refs'] = dict(execution.get('execution_refs') or {})
    elif 'execution_refs' not in record:
        record['execution_refs'] = {}
    if 'execution_plan' in execution:
        record['execution_plan'] = dict(execution.get('execution_plan') or {})
    elif 'execution_plan' not in record:
        record['execution_plan'] = {}
    if 'proposal_snapshot' in execution:
        record['proposal_snapshot'] = dict(execution.get('proposal_snapshot') or {})
    elif 'proposal_snapshot' not in record:
        record['proposal_snapshot'] = {}
    if 'adapter_contract_snapshot' in execution:
        record['adapter_contract_snapshot'] = dict(execution.get('adapter_contract_snapshot') or {})
    elif 'adapter_contract_snapshot' not in record:
        record['adapter_contract_snapshot'] = {}
    if 'adapter_contract_digest' in execution or 'adapter_contract_digest' not in record:
        record['adapter_contract_digest'] = (
            execution.get('adapter_contract_digest')
            or existing.get('adapter_contract_digest')
            or ''
        ).strip()
    record['generated_at'] = (execution.get('generated_at') or existing.get('generated_at') or _now()).strip()
    record['queued_at'] = (execution.get('queued_at') or existing.get('queued_at') or record['generated_at']).strip()
    record['dispatched_at'] = (execution.get('dispatched_at') or existing.get('dispatched_at') or '').strip()
    record['executed_at'] = (execution.get('executed_at') or existing.get('executed_at') or '').strip()
    record['updated_at'] = _now()
    if 'note' in execution or 'note' not in record:
        record['note'] = (execution.get('note') or existing.get('note') or '').strip()
    if 'execution_digest' in execution or 'execution_digest' not in record:
        record['execution_digest'] = (execution.get('execution_digest') or _execution_digest(record)).strip()
    return record


def load_payout_execution_queue(org_id):
    store = _load_store(org_id)
    if not os.path.exists(_store_path(org_id)):
        _save_store(store, org_id)
    return store


def get_payout_execution_record(execution_id, org_id):
    execution_id = (execution_id or '').strip()
    if not execution_id:
        return None
    store = _load_store(org_id)
    return store.get('payout_execution_records', {}).get(execution_id)


def list_payout_execution_records(org_id, *, state=None):
    parent = os.path.dirname(_store_path(org_id))
    if org_id and not os.path.isdir(parent):
        return []
    store = _load_store(org_id)
    records = list(store.get('payout_execution_records', {}).values())
    if state:
        records = [row for row in records if row.get('state') == state or row.get('execution_state') == state]
    records.sort(
        key=lambda row: row.get('executed_at', '') or row.get('dispatched_at', '') or row.get('queued_at', '') or row.get('generated_at', ''),
        reverse=True,
    )
    return records


def upsert_payout_execution_record(org_id, execution=None, **execution_fields):
    payload = dict(execution or {})
    payload.update(execution_fields)
    with _execution_lock(org_id):
        store = _load_store(org_id)
        existing = None
        execution_id = (payload.get('execution_id') or payload.get('tx_ref') or payload.get('proposal_id') or '').strip()
        if execution_id:
            existing = store.get('payout_execution_records', {}).get(execution_id)
        record = _normalize_execution(payload, org_id, existing=existing)
        store.setdefault('payout_execution_records', {})[record['execution_id']] = record
        _save_store(store, org_id)
        return record


def payout_execution_queue_summary(org_id):
    parent = os.path.dirname(_store_path(org_id))
    if org_id and not os.path.isdir(parent):
        return {
            'org_id': (org_id or '').strip(),
            'total': 0,
            'previewed': 0,
            'dispatchable': 0,
            'executed': 0,
            'blocked': 0,
            'superseded': 0,
            'state_counts': {},
            'adapter_counts': {},
            'updatedAt': _now(),
        }
    store = _load_store(org_id)
    state_counts = {}
    adapter_counts = {}
    for record in store.get('payout_execution_records', {}).values():
        state = (record.get('state') or record.get('execution_state') or '').strip() or 'previewed'
        record['state'] = state
        record['execution_state'] = record.get('execution_state') or state
        state_counts[state] = state_counts.get(state, 0) + 1
        adapter_id = (record.get('settlement_adapter') or '').strip() or 'unknown'
        adapter_counts[adapter_id] = adapter_counts.get(adapter_id, 0) + 1
    return {
        'org_id': (org_id or '').strip(),
        'total': len(store.get('payout_execution_records', {})),
        'previewed': state_counts.get('previewed', 0),
        'dispatchable': state_counts.get('dispatchable', 0),
        'executed': state_counts.get('executed', 0),
        'blocked': state_counts.get('blocked', 0),
        'superseded': state_counts.get('superseded', 0),
        'state_counts': state_counts,
        'adapter_counts': dict(sorted(adapter_counts.items())),
        'updatedAt': store.get('updatedAt', _now()),
    }


def payout_execution_queue_snapshot(org_id, *, state=None, limit=50):
    summary = payout_execution_queue_summary(org_id)
    records = list_payout_execution_records(org_id, state=state)
    if limit is not None:
        records = records[:max(0, int(limit))]
    return {
        'summary': summary,
        'payout_execution_records': records,
    }


def summarize_payout_execution_records(org_id):
    return payout_execution_queue_summary(org_id)


def summary(org_id):
    return payout_execution_queue_summary(org_id)
