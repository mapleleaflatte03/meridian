#!/usr/bin/env python3
"""
Capsule-backed dispatch queue for acknowledged federation handoff previews.

This store is intentionally narrow:

- dispatch records are institution-scoped and file-backed
- entries are keyed by dispatch_id for idempotent upsert
- records preserve the acknowledged preview, draft execution request, and the
  dispatch metadata a future runtime needs to send a federation envelope
- successful dispatches can persist delivery evidence and receiver-side
  execution metadata without claiming external settlement beyond that receipt
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


STORE_FILE = 'federation_handoff_dispatch_queue.json'
LOCK_FILE = '.federation_handoff_dispatch_queue.lock'
QUEUE_STATES = (
    'dispatchable',
    'dispatched',
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
        'handoff_dispatch_records': {},
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
        raise ValueError(f"Unknown handoff dispatch state {state!r}. Must be one of {QUEUE_STATES}")
    if state:
        return state
    return existing_state or 'dispatchable'


def _normalize_store(data, org_id):
    store = _empty_store(org_id)
    if not isinstance(data, dict):
        return store
    store.update({k: v for k, v in data.items() if k not in ('handoff_dispatch_records', '_meta')})
    meta = dict(store.get('_meta', {}))
    meta.update(data.get('_meta', {}) or {})
    meta['bound_org_id'] = (org_id or '').strip()
    store['_meta'] = meta

    raw_records = data.get('handoff_dispatch_records', {})
    records = {}
    if isinstance(raw_records, list):
        for item in raw_records:
            if isinstance(item, dict) and item.get('dispatch_id'):
                records[item['dispatch_id']] = dict(item)
    elif isinstance(raw_records, dict):
        for dispatch_id, item in raw_records.items():
            if isinstance(item, dict):
                record = dict(item)
                record['dispatch_id'] = record.get('dispatch_id') or dispatch_id
                records[record['dispatch_id']] = record
    for dispatch_id, record in list(records.items()):
        record = dict(record or {})
        record['state'] = _normalize_state(record.get('state') or record.get('dispatch_state') or '')
        record['dispatch_state'] = record.get('dispatch_state') or record['state']
        record['generated_at'] = (record.get('generated_at') or record.get('previewed_at') or '').strip()
        record['queued_at'] = (record.get('queued_at') or record['generated_at'] or '').strip()
        record['dispatched_at'] = (record.get('dispatched_at') or '').strip()
        record['updated_at'] = (record.get('updated_at') or '').strip()
        records[dispatch_id] = record
    store['handoff_dispatch_records'] = records
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
        prefix='.federation_handoff_dispatch_queue.',
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
def _dispatch_lock(org_id):
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


def _dispatch_digest(record):
    record = dict(record or {})
    digest_payload = {
        'dispatch_id': (record.get('dispatch_id') or '').strip(),
        'bound_org_id': (record.get('bound_org_id') or '').strip(),
        'handoff_id': (record.get('handoff_id') or '').strip(),
        'requested_org_id': (record.get('requested_org_id') or '').strip(),
        'route_kind': (record.get('route_kind') or '').strip(),
        'route_state': (record.get('route_state') or '').strip(),
        'route_reason': (record.get('route_reason') or '').strip(),
        'state': (record.get('state') or '').strip(),
        'dispatch_ready': bool(record.get('dispatch_ready')),
        'dispatch_blockers': list(record.get('dispatch_blockers') or []),
        'draft_execution_request': dict(record.get('draft_execution_request') or {}),
        'preview_snapshot': dict(record.get('preview_snapshot') or {}),
        'dispatch_paths': dict(record.get('dispatch_paths') or {}),
        'acknowledged_by': (record.get('acknowledged_by') or '').strip(),
        'acknowledged_at': (record.get('acknowledged_at') or '').strip(),
        'acknowledged_note': (record.get('acknowledged_note') or '').strip(),
        'dispatch_runner': (record.get('dispatch_runner') or '').strip(),
        'dispatched_by': (record.get('dispatched_by') or '').strip(),
        'dispatched_at': (record.get('dispatched_at') or '').strip(),
        'dispatched_note': (record.get('dispatched_note') or '').strip(),
        'execution_job_id': (record.get('execution_job_id') or '').strip(),
        'execution_job_state': (record.get('execution_job_state') or '').strip(),
        'delivery_snapshot': dict(record.get('delivery_snapshot') or {}),
    }
    return _canonical_hash(digest_payload)


def _normalize_dispatch(dispatch, org_id, existing=None):
    dispatch = dict(dispatch or {})
    existing = dict(existing or {})
    dispatch_id = (dispatch.get('dispatch_id') or existing.get('dispatch_id') or '').strip()
    if not dispatch_id:
        dispatch_id = (dispatch.get('handoff_id') or existing.get('handoff_id') or '').strip()
    if not dispatch_id:
        raise ValueError('dispatch_id is required')

    record = dict(existing)
    record['dispatch_id'] = dispatch_id
    record['bound_org_id'] = (org_id or '').strip()
    record['handoff_id'] = (dispatch.get('handoff_id') or existing.get('handoff_id') or dispatch_id).strip()
    record['requested_org_id'] = (dispatch.get('requested_org_id') or existing.get('requested_org_id') or '').strip()
    record['route_kind'] = (dispatch.get('route_kind') or existing.get('route_kind') or '').strip()
    record['route_state'] = (dispatch.get('route_state') or existing.get('route_state') or '').strip()
    record['route_reason'] = (dispatch.get('route_reason') or existing.get('route_reason') or '').strip()
    if 'acknowledged_by' in dispatch or 'acknowledged_by' not in record:
        record['acknowledged_by'] = (dispatch.get('acknowledged_by') or existing.get('acknowledged_by') or '').strip()
    if 'acknowledged_at' in dispatch or 'acknowledged_at' not in record:
        record['acknowledged_at'] = (dispatch.get('acknowledged_at') or existing.get('acknowledged_at') or '').strip()
    if 'acknowledged_note' in dispatch or 'acknowledged_note' not in record:
        record['acknowledged_note'] = (dispatch.get('acknowledged_note') or existing.get('acknowledged_note') or '').strip()
    record['state'] = _normalize_state(
        dispatch.get('state') or dispatch.get('dispatch_state') or existing.get('state') or existing.get('dispatch_state') or '',
        existing_state=existing.get('state') or existing.get('dispatch_state') or '',
    )
    record['dispatch_state'] = record['state']
    if 'dispatch_ready' in dispatch:
        record['dispatch_ready'] = bool(dispatch.get('dispatch_ready'))
    elif 'dispatch_ready' not in record:
        record['dispatch_ready'] = False
    if 'dispatch_blockers' in dispatch:
        record['dispatch_blockers'] = list(dispatch.get('dispatch_blockers') or [])
    elif 'dispatch_blockers' not in record:
        record['dispatch_blockers'] = []
    if 'dispatch_truth_source' in dispatch or 'dispatch_truth_source' not in record:
        record['dispatch_truth_source'] = (dispatch.get('dispatch_truth_source') or existing.get('dispatch_truth_source') or '').strip()
    if 'dispatch_paths' in dispatch:
        record['dispatch_paths'] = dict(dispatch.get('dispatch_paths') or {})
    elif 'dispatch_paths' not in record:
        record['dispatch_paths'] = {}
    if 'draft_execution_request' in dispatch:
        record['draft_execution_request'] = dict(dispatch.get('draft_execution_request') or {})
    elif 'draft_execution_request' not in record:
        record['draft_execution_request'] = {}
    if 'preview_snapshot' in dispatch:
        record['preview_snapshot'] = dict(dispatch.get('preview_snapshot') or {})
    elif 'preview_snapshot' not in record:
        record['preview_snapshot'] = {}
    if 'dispatch_runner' in dispatch or 'dispatch_runner' not in record:
        record['dispatch_runner'] = (dispatch.get('dispatch_runner') or existing.get('dispatch_runner') or '').strip()
    if 'acknowledged_by' in dispatch or 'acknowledged_by' not in record:
        record['acknowledged_by'] = (dispatch.get('acknowledged_by') or existing.get('acknowledged_by') or '').strip()
    if 'acknowledged_at' in dispatch or 'acknowledged_at' not in record:
        record['acknowledged_at'] = (dispatch.get('acknowledged_at') or existing.get('acknowledged_at') or '').strip()
    if 'acknowledged_note' in dispatch or 'acknowledged_note' not in record:
        record['acknowledged_note'] = (dispatch.get('acknowledged_note') or existing.get('acknowledged_note') or '').strip()
    if 'dispatched_by' in dispatch or 'dispatched_by' not in record:
        record['dispatched_by'] = (dispatch.get('dispatched_by') or existing.get('dispatched_by') or '').strip()
    if 'dispatched_at' in dispatch or 'dispatched_at' not in record:
        record['dispatched_at'] = (dispatch.get('dispatched_at') or existing.get('dispatched_at') or '').strip()
    if 'dispatched_note' in dispatch or 'dispatched_note' not in record:
        record['dispatched_note'] = (dispatch.get('dispatched_note') or existing.get('dispatched_note') or '').strip()
    if 'execution_job_id' in dispatch or 'execution_job_id' not in record:
        record['execution_job_id'] = (dispatch.get('execution_job_id') or existing.get('execution_job_id') or '').strip()
    if 'execution_job_state' in dispatch or 'execution_job_state' not in record:
        record['execution_job_state'] = (dispatch.get('execution_job_state') or existing.get('execution_job_state') or '').strip()
    if 'delivery_snapshot' in dispatch:
        record['delivery_snapshot'] = dict(dispatch.get('delivery_snapshot') or {})
    elif 'delivery_snapshot' not in record:
        record['delivery_snapshot'] = {}
    record['generated_at'] = (dispatch.get('generated_at') or existing.get('generated_at') or _now()).strip()
    record['queued_at'] = (dispatch.get('queued_at') or existing.get('queued_at') or record['generated_at']).strip()
    record['dispatched_at'] = (dispatch.get('dispatched_at') or existing.get('dispatched_at') or '').strip()
    record['updated_at'] = _now()
    if 'note' in dispatch or 'note' not in record:
        record['note'] = (dispatch.get('note') or existing.get('note') or '').strip()
    if 'dispatch_digest' in dispatch or 'dispatch_digest' not in record:
        record['dispatch_digest'] = (dispatch.get('dispatch_digest') or _dispatch_digest(record)).strip()
    return record


def load_handoff_dispatch_queue(org_id):
    store = _load_store(org_id)
    if not os.path.exists(_store_path(org_id)):
        _save_store(store, org_id)
    return store


def get_handoff_dispatch_record(dispatch_id, org_id):
    dispatch_id = (dispatch_id or '').strip()
    if not dispatch_id:
        return None
    store = _load_store(org_id)
    return store.get('handoff_dispatch_records', {}).get(dispatch_id)


def list_handoff_dispatch_records(org_id, *, state=None):
    parent = os.path.dirname(_store_path(org_id))
    if org_id and not os.path.isdir(parent):
        return []
    store = _load_store(org_id)
    records = list(store.get('handoff_dispatch_records', {}).values())
    if state:
        records = [row for row in records if row.get('state') == state or row.get('dispatch_state') == state]
    records.sort(
        key=lambda row: row.get('dispatched_at', '') or row.get('queued_at', '') or row.get('generated_at', ''),
        reverse=True,
    )
    return records


def upsert_handoff_dispatch_record(org_id, dispatch=None, **dispatch_fields):
    payload = dict(dispatch or {})
    payload.update(dispatch_fields)
    with _dispatch_lock(org_id):
        store = _load_store(org_id)
        existing = None
        dispatch_id = (payload.get('dispatch_id') or payload.get('handoff_id') or '').strip()
        if dispatch_id:
            existing = store.get('handoff_dispatch_records', {}).get(dispatch_id)
        record = _normalize_dispatch(payload, org_id, existing=existing)
        store.setdefault('handoff_dispatch_records', {})[record['dispatch_id']] = record
        _save_store(store, org_id)
        return record


def promote_acknowledged_handoff_preview_to_dispatch_record(org_id, handoff_id, *, promoted_by, promotion_note=''):
    from federation_handoff_queue import get_handoff_preview

    handoff_id = (handoff_id or '').strip()
    if not handoff_id:
        raise ValueError('handoff_id is required')
    promoted_by = (promoted_by or '').strip()
    if not promoted_by:
        raise ValueError('promoted_by is required')

    preview_record = get_handoff_preview(handoff_id, org_id)
    if not preview_record:
        raise LookupError(f'Federation handoff preview not found: {handoff_id}')
    if preview_record.get('settlement_claimed'):
        raise PermissionError(
            f"Federation handoff preview '{handoff_id}' already records a settlement claim and cannot be dispatched"
        )
    if preview_record.get('external_settlement_observed'):
        raise PermissionError(
            f"Federation handoff preview '{handoff_id}' observed external settlement evidence and cannot be dispatched"
        )
    if not preview_record.get('acknowledged'):
        raise PermissionError(
            f"Federation handoff preview '{handoff_id}' must be acknowledged before it can be dispatched"
        )
    if not preview_record.get('dispatch_ready'):
        raise PermissionError(
            f"Federation handoff preview '{handoff_id}' is not dispatch-ready"
        )

    with _dispatch_lock(org_id):
        store = _load_store(org_id)
        existing = store.get('handoff_dispatch_records', {}).get(handoff_id)
        timestamp = _now()
        dispatch_record = _normalize_dispatch({
            'dispatch_id': handoff_id,
            'handoff_id': handoff_id,
            'requested_org_id': preview_record.get('requested_org_id', ''),
            'route_kind': preview_record.get('route_kind', ''),
            'route_state': preview_record.get('route_state', ''),
            'route_reason': preview_record.get('route_reason', ''),
            'state': 'dispatchable',
            'dispatch_ready': True,
            'dispatch_blockers': [],
            'dispatch_truth_source': 'acknowledged_handoff_preview_and_local_policy_only',
            'dispatch_paths': dict(preview_record.get('dispatch_paths') or {}),
            'draft_execution_request': dict(preview_record.get('draft_execution_request') or {}),
            'preview_snapshot': dict(preview_record),
            'acknowledged_by': preview_record.get('acknowledged_by', ''),
            'acknowledged_at': preview_record.get('acknowledged_at', ''),
            'acknowledged_note': preview_record.get('acknowledged_note', ''),
            'generated_at': preview_record.get('generated_at', timestamp),
            'queued_at': preview_record.get('queued_at', timestamp),
            'note': (promotion_note or '').strip() or (preview_record.get('note') or '').strip(),
        }, org_id, existing=existing)
        store.setdefault('handoff_dispatch_records', {})[dispatch_record['dispatch_id']] = dispatch_record
        _save_store(store, org_id)
        return dispatch_record


def mark_handoff_dispatch_record_dispatched(
    org_id,
    dispatch_id,
    *,
    dispatched_by,
    note='',
    dispatch_runner='',
    execution_job_id='',
    execution_job_state='',
    execution_job_snapshot=None,
    delivery_snapshot=None,
    dispatch_truth_source='',
):
    dispatch_id = (dispatch_id or '').strip()
    dispatched_by = (dispatched_by or '').strip()
    if not dispatch_id:
        raise ValueError('dispatch_id is required')
    if not dispatched_by:
        raise ValueError('dispatched_by is required')
    with _dispatch_lock(org_id):
        store = _load_store(org_id)
        record = store.get('handoff_dispatch_records', {}).get(dispatch_id)
        if not record:
            raise LookupError(f'Federation handoff dispatch record not found: {dispatch_id}')
        timestamp = _now()
        record['state'] = 'dispatched'
        record['dispatch_state'] = 'dispatched'
        record['dispatched_at'] = timestamp
        record['dispatched_by'] = dispatched_by
        record['dispatched_note'] = (note or '').strip()
        record['dispatch_runner'] = (dispatch_runner or record.get('dispatch_runner') or '').strip()
        record['execution_job_id'] = (execution_job_id or record.get('execution_job_id') or '').strip()
        record['execution_job_state'] = (execution_job_state or record.get('execution_job_state') or '').strip()
        if execution_job_snapshot is not None:
            record['execution_job_snapshot'] = dict(execution_job_snapshot or {})
        if delivery_snapshot is not None:
            record['delivery_snapshot'] = dict(delivery_snapshot or {})
        if dispatch_truth_source:
            record['dispatch_truth_source'] = (dispatch_truth_source or '').strip()
        record['updated_at'] = timestamp
        record['dispatch_digest'] = _dispatch_digest(record)
        store['handoff_dispatch_records'][dispatch_id] = record
        _save_store(store, org_id)
        return record


def handoff_dispatch_queue_summary(org_id):
    parent = os.path.dirname(_store_path(org_id))
    if org_id and not os.path.isdir(parent):
        return {
            'org_id': (org_id or '').strip(),
            'total': 0,
            'dispatchable': 0,
            'dispatched': 0,
            'blocked': 0,
            'superseded': 0,
            'state_counts': {},
            'route_kind_counts': {},
            'updatedAt': _now(),
        }
    store = _load_store(org_id)
    state_counts = {}
    route_kind_counts = {}
    for record in store.get('handoff_dispatch_records', {}).values():
        state = (record.get('state') or record.get('dispatch_state') or '').strip() or 'dispatchable'
        record['state'] = state
        record['dispatch_state'] = record.get('dispatch_state') or state
        state_counts[state] = state_counts.get(state, 0) + 1
        route_kind = (record.get('route_kind') or '').strip() or 'unknown'
        route_kind_counts[route_kind] = route_kind_counts.get(route_kind, 0) + 1
    return {
        'org_id': (org_id or '').strip(),
        'total': len(store.get('handoff_dispatch_records', {})),
        'dispatchable': state_counts.get('dispatchable', 0),
        'dispatched': state_counts.get('dispatched', 0),
        'blocked': state_counts.get('blocked', 0),
        'superseded': state_counts.get('superseded', 0),
        'state_counts': state_counts,
        'route_kind_counts': dict(sorted(route_kind_counts.items())),
        'updatedAt': store.get('updatedAt', _now()),
    }


def handoff_dispatch_queue_snapshot(org_id, *, state=None, limit=50):
    summary = handoff_dispatch_queue_summary(org_id)
    records = list_handoff_dispatch_records(org_id, state=state)
    if limit is not None:
        records = records[:max(0, int(limit))]
    return {
        'summary': summary,
        'handoff_dispatch_records': records,
    }


def summarize_handoff_dispatch_records(org_id):
    return handoff_dispatch_queue_summary(org_id)


def summary(org_id):
    return handoff_dispatch_queue_summary(org_id)
