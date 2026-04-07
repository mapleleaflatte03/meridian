#!/usr/bin/env python3
"""
Capsule-backed preview queue for payout-plan dry-runs.

This store is intentionally narrow:

- payout plan previews are institution-scoped and file-backed
- entries are keyed by preview_id for inspectable replay of a single dry-run
- records preserve the proposal snapshot, adapter contract, and draft
  execution plan that a future executor would need to inspect
- no external settlement is claimed here; the queue only records dry-run
  planning output that already passed the local governance gates
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


STORE_FILE = 'payout_plan_preview_queue.json'
LOCK_FILE = '.payout_plan_preview_queue.lock'
QUEUE_STATES = (
    'previewed',
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
        'payout_plan_previews': {},
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
        raise ValueError(f"Unknown payout-plan preview state {state!r}. Must be one of {QUEUE_STATES}")
    if state:
        return state
    return existing_state or 'previewed'


def _normalize_store(data, org_id):
    store = _empty_store(org_id)
    if not isinstance(data, dict):
        return store
    store.update({k: v for k, v in data.items() if k not in ('payout_plan_previews', '_meta')})
    meta = dict(store.get('_meta', {}))
    meta.update(data.get('_meta', {}) or {})
    meta['bound_org_id'] = (org_id or '').strip()
    store['_meta'] = meta

    raw_previews = data.get('payout_plan_previews', {})
    previews = {}
    if isinstance(raw_previews, list):
        for item in raw_previews:
            if isinstance(item, dict) and item.get('preview_id'):
                previews[item['preview_id']] = dict(item)
    elif isinstance(raw_previews, dict):
        for preview_id, item in raw_previews.items():
            if isinstance(item, dict):
                record = dict(item)
                record['preview_id'] = record.get('preview_id') or preview_id
                previews[record['preview_id']] = record
    for preview_id, record in list(previews.items()):
        record = dict(record or {})
        record['state'] = _normalize_state(record.get('state') or record.get('preview_state') or '')
        record['preview_state'] = record.get('preview_state') or record['state']
        record['previewed_at'] = (record.get('previewed_at') or record.get('generated_at') or '').strip()
        record['updated_at'] = (record.get('updated_at') or '').strip()
        previews[preview_id] = record
    store['payout_plan_previews'] = previews
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
        prefix='.payout_plan_preview_queue.',
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
def _preview_lock(org_id):
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


def _preview_digest(record):
    record = dict(record or {})
    digest_payload = {
        'preview_id': (record.get('preview_id') or '').strip(),
        'bound_org_id': (record.get('bound_org_id') or '').strip(),
        'proposal_id': (record.get('proposal_id') or '').strip(),
        'warrant_id': (record.get('warrant_id') or '').strip(),
        'settlement_adapter': (record.get('settlement_adapter') or '').strip(),
        'status_at_preview': (record.get('status_at_preview') or '').strip(),
        'preview_state': (record.get('preview_state') or '').strip(),
        'execution_ready': bool(record.get('execution_ready')),
        'settlement_claimed': bool(record.get('settlement_claimed')),
        'dry_run': bool(record.get('dry_run')),
        'execution_plan': dict(record.get('execution_plan') or {}),
    }
    return _canonical_hash(digest_payload)


def _preview_inspection_state(record):
    record = dict(record or {})
    state = (record.get('state') or record.get('preview_state') or '').strip() or 'previewed'
    if record.get('settlement_claimed'):
        return 'settlement_claimed'
    if record.get('external_settlement_observed'):
        return 'external_settlement_observed'
    if state == 'blocked':
        return 'blocked'
    if state == 'superseded':
        return 'superseded'
    if record.get('acknowledged'):
        return 'acknowledged'
    if record.get('execution_ready'):
        return 'ready_for_ack'
    return 'previewed'


def _inspected_preview_record(record):
    inspected = dict(record or {})
    inspection_state = _preview_inspection_state(inspected)
    inspected['inspection_state'] = inspection_state
    inspected['inspection_required'] = inspection_state == 'ready_for_ack'
    inspected['inspection_message'] = {
        'settlement_claimed': 'Preview has a claimed settlement reference but remains non-executable here.',
        'external_settlement_observed': 'Preview observed external settlement evidence; no settlement execution is claimed.',
        'blocked': 'Preview is blocked and needs operator review.',
        'superseded': 'Preview was superseded by a newer preview.',
        'acknowledged': 'Preview was acknowledged by an operator.',
        'ready_for_ack': 'Preview is execution-ready but still awaiting operator acknowledgment.',
        'previewed': 'Preview is recorded and still awaiting operator review.',
    }[inspection_state]
    return inspected


def _normalize_preview(preview, org_id, existing=None):
    preview = dict(preview or {})
    existing = dict(existing or {})
    preview_id = (preview.get('preview_id') or existing.get('preview_id') or '').strip()
    if not preview_id:
        preview_id = (preview.get('tx_ref') or existing.get('tx_ref') or '').strip()
    if not preview_id:
        raise ValueError('preview_id is required')

    record = dict(existing)
    record['preview_id'] = preview_id
    record['bound_org_id'] = (org_id or '').strip()
    record['proposal_id'] = (preview.get('proposal_id') or existing.get('proposal_id') or '').strip()
    record['status_at_preview'] = (
        preview.get('status_at_preview')
        or existing.get('status_at_preview')
        or preview.get('status')
        or ''
    ).strip()
    record['warrant_id'] = (preview.get('warrant_id') or existing.get('warrant_id') or '').strip()
    record['settlement_adapter'] = (
        preview.get('settlement_adapter')
        or existing.get('settlement_adapter')
        or ''
    ).strip()
    record['preview_state'] = _normalize_state(
        preview.get('preview_state') or preview.get('state') or existing.get('preview_state') or existing.get('state') or '',
        existing_state=existing.get('preview_state') or existing.get('state') or '',
    )
    record['state'] = record['preview_state']
    if 'dry_run' in preview or 'dry_run' not in record:
        record['dry_run'] = bool(preview.get('dry_run', existing.get('dry_run', True)))
    if 'execution_ready' in preview:
        record['execution_ready'] = bool(preview.get('execution_ready'))
    elif 'execution_ready' not in record:
        record['execution_ready'] = False
    if 'settlement_claimed' in preview:
        record['settlement_claimed'] = bool(preview.get('settlement_claimed'))
    elif 'settlement_claimed' not in record:
        record['settlement_claimed'] = False
    if 'acknowledged' in preview:
        record['acknowledged'] = bool(preview.get('acknowledged'))
    elif 'acknowledged' not in record:
        record['acknowledged'] = False
    if 'acknowledged_at' in preview or 'acknowledged_at' not in record:
        record['acknowledged_at'] = (
            preview.get('acknowledged_at')
            or existing.get('acknowledged_at')
            or ''
        ).strip()
    if 'acknowledged_by' in preview or 'acknowledged_by' not in record:
        record['acknowledged_by'] = (
            preview.get('acknowledged_by')
            or existing.get('acknowledged_by')
            or ''
        ).strip()
    if 'acknowledged_note' in preview or 'acknowledged_note' not in record:
        record['acknowledged_note'] = (
            preview.get('acknowledged_note')
            or existing.get('acknowledged_note')
            or ''
        ).strip()
    if 'external_settlement_observed' in preview or 'external_settlement_observed' not in record:
        record['external_settlement_observed'] = bool(
            preview.get(
                'external_settlement_observed',
                existing.get('external_settlement_observed', False),
            )
        )
    if 'preview_truth_source' in preview or 'preview_truth_source' not in record:
        record['preview_truth_source'] = (
            preview.get('preview_truth_source')
            or existing.get('preview_truth_source')
            or ''
        ).strip()
    if 'phase_gate' in preview:
        record['phase_gate'] = dict(preview.get('phase_gate') or {})
    elif 'phase_gate' not in record:
        record['phase_gate'] = {}
    if 'contract' in preview:
        record['contract'] = dict(preview.get('contract') or {})
    elif 'contract' not in record:
        record['contract'] = {}
    if 'normalized_proof' in preview:
        record['normalized_proof'] = dict(preview.get('normalized_proof') or {})
    elif 'normalized_proof' not in record:
        record['normalized_proof'] = {}
    if 'execution_plan' in preview:
        record['execution_plan'] = dict(preview.get('execution_plan') or {})
    elif 'execution_plan' not in record:
        record['execution_plan'] = {}
    if 'proposal_snapshot' in preview:
        record['proposal_snapshot'] = dict(preview.get('proposal_snapshot') or {})
    elif 'proposal_snapshot' not in record:
        record['proposal_snapshot'] = {}
    if 'plan_digest' in preview or 'plan_digest' not in record:
        record['plan_digest'] = (preview.get('plan_digest') or _preview_digest(record)).strip()
    record['generated_at'] = (preview.get('generated_at') or existing.get('generated_at') or _now()).strip()
    record['previewed_at'] = (preview.get('previewed_at') or existing.get('previewed_at') or record['generated_at']).strip()
    record['queued_at'] = (preview.get('queued_at') or existing.get('queued_at') or record['previewed_at']).strip()
    record['updated_at'] = _now()
    if 'note' in preview or 'note' not in record:
        record['note'] = (preview.get('note') or existing.get('note') or '').strip()
    if 'superseded_by' in preview or 'superseded_by' not in record:
        record['superseded_by'] = (preview.get('superseded_by') or existing.get('superseded_by') or '').strip()
    return record


def load_payout_plan_preview_queue(org_id):
    store = _load_store(org_id)
    if not os.path.exists(_store_path(org_id)):
        _save_store(store, org_id)
    return store


def get_payout_plan_preview(preview_id, org_id):
    preview_id = (preview_id or '').strip()
    if not preview_id:
        return None
    store = _load_store(org_id)
    return store.get('payout_plan_previews', {}).get(preview_id)


def list_payout_plan_previews(org_id, *, state=None):
    parent = os.path.dirname(_store_path(org_id))
    if org_id and not os.path.isdir(parent):
        return []
    store = _load_store(org_id)
    previews = list(store.get('payout_plan_previews', {}).values())
    if state:
        previews = [row for row in previews if row.get('state') == state or row.get('preview_state') == state]
    previews.sort(key=lambda row: row.get('previewed_at', '') or row.get('generated_at', ''), reverse=True)
    return previews


def acknowledge_payout_plan_preview(org_id, preview_id, *, by, note=''):
    preview_id = (preview_id or '').strip()
    by = (by or '').strip()
    if not preview_id:
        raise ValueError('preview_id is required')
    if not by:
        raise ValueError('by is required')
    with _preview_lock(org_id):
        store = _load_store(org_id)
        record = store.get('payout_plan_previews', {}).get(preview_id)
        if not record:
            raise LookupError(f'Payout-plan preview not found: {preview_id}')
        if not record.get('acknowledged'):
            timestamp = _now()
            record['acknowledged'] = True
            record['acknowledged_at'] = timestamp
            record['acknowledged_by'] = by
            record['acknowledged_note'] = (note or '').strip()
            record['updated_at'] = timestamp
            store['payout_plan_previews'][preview_id] = record
            _save_store(store, org_id)
        return record


def upsert_payout_plan_preview(org_id, preview=None, **preview_fields):
    payload = dict(preview or {})
    payload.update(preview_fields)
    with _preview_lock(org_id):
        store = _load_store(org_id)
        existing = None
        preview_id = (payload.get('preview_id') or payload.get('tx_ref') or '').strip()
        if preview_id:
            existing = store.get('payout_plan_previews', {}).get(preview_id)
        record = _normalize_preview(payload, org_id, existing=existing)
        store.setdefault('payout_plan_previews', {})[record['preview_id']] = record
        _save_store(store, org_id)
        return record


def payout_plan_preview_queue_summary(org_id):
    parent = os.path.dirname(_store_path(org_id))
    if org_id and not os.path.isdir(parent):
        return {
            'org_id': (org_id or '').strip(),
            'total': 0,
            'previewed': 0,
            'blocked': 0,
            'superseded': 0,
            'execution_ready': 0,
            'settlement_claimed': 0,
            'acknowledged': 0,
            'acknowledgement_pending': 0,
            'state_counts': {},
            'adapter_counts': {},
            'updatedAt': _now(),
        }
    store = _load_store(org_id)
    state_counts = {}
    adapter_counts = {}
    execution_ready = 0
    settlement_claimed = 0
    acknowledged = 0
    acknowledgement_pending = 0
    for record in store.get('payout_plan_previews', {}).values():
        state = (record.get('state') or record.get('preview_state') or '').strip() or 'previewed'
        record['state'] = state
        record['preview_state'] = record.get('preview_state') or state
        state_counts[state] = state_counts.get(state, 0) + 1
        adapter_id = (record.get('settlement_adapter') or '').strip() or 'unknown'
        adapter_counts[adapter_id] = adapter_counts.get(adapter_id, 0) + 1
        if record.get('execution_ready'):
            execution_ready += 1
        if record.get('settlement_claimed'):
            settlement_claimed += 1
        if record.get('acknowledged'):
            acknowledged += 1
        elif record.get('execution_ready') and state == 'previewed':
            acknowledgement_pending += 1
    return {
        'org_id': (org_id or '').strip(),
        'total': len(store.get('payout_plan_previews', {})),
        'previewed': state_counts.get('previewed', 0),
        'blocked': state_counts.get('blocked', 0),
        'superseded': state_counts.get('superseded', 0),
        'execution_ready': execution_ready,
        'settlement_claimed': settlement_claimed,
        'acknowledged': acknowledged,
        'acknowledgement_pending': acknowledgement_pending,
        'state_counts': state_counts,
        'adapter_counts': dict(sorted(adapter_counts.items())),
        'updatedAt': store.get('updatedAt', _now()),
    }


def payout_plan_preview_queue_snapshot(org_id, *, state=None, limit=50):
    summary = payout_plan_preview_queue_summary(org_id)
    records = list_payout_plan_previews(org_id, state=state)
    if limit is not None:
        records = records[:max(0, int(limit))]
    return {
        'summary': summary,
        'payout_plan_previews': records,
    }


def inspect_payout_plan_preview_queue(org_id, *, state=None, limit=50):
    snapshot = payout_plan_preview_queue_snapshot(org_id, state=state, limit=limit)
    inspected_records = [_inspected_preview_record(record) for record in snapshot['payout_plan_previews']]
    inspection_state_counts = {}
    for record in inspected_records:
        inspection_state = record.get('inspection_state', 'previewed')
        inspection_state_counts[inspection_state] = inspection_state_counts.get(inspection_state, 0) + 1
    inspection_summary = {
        'org_id': (org_id or '').strip(),
        'total': len(inspected_records),
        'acknowledged': inspection_state_counts.get('acknowledged', 0),
        'ready_for_ack': inspection_state_counts.get('ready_for_ack', 0),
        'blocked': inspection_state_counts.get('blocked', 0),
        'superseded': inspection_state_counts.get('superseded', 0),
        'settlement_claimed': inspection_state_counts.get('settlement_claimed', 0),
        'external_settlement_observed': inspection_state_counts.get('external_settlement_observed', 0),
        'requires_operator_ack': inspection_state_counts.get('ready_for_ack', 0),
        'inspection_state_counts': dict(sorted(inspection_state_counts.items())),
        'inspected_at': _now(),
    }
    return {
        'summary': snapshot['summary'],
        'inspection_summary': inspection_summary,
        'payout_plan_previews': inspected_records,
    }


def summarize_payout_plan_previews(org_id):
    return payout_plan_preview_queue_summary(org_id)


def summary(org_id):
    return payout_plan_preview_queue_summary(org_id)
