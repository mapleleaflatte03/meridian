#!/usr/bin/env python3
"""
Capsule-backed preview queue for remote federation handoff candidates.

This store is intentionally narrow:

- handoff previews are institution-scoped and file-backed
- entries are keyed by handoff_id for idempotent upsert
- records preserve the routing planner decision, the draft execution request,
  and the dispatch paths that a future runtime would need to inspect
- no remote execution is claimed here; the queue only records planner output
  that is already previewed as dispatch-ready
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


STORE_FILE = 'federation_handoff_queue.json'
LOCK_FILE = '.federation_handoff_queue.lock'
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
        'handoff_previews': {},
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
        raise ValueError(f"Unknown handoff preview state {state!r}. Must be one of {QUEUE_STATES}")
    if state:
        return state
    return existing_state or 'previewed'


def _normalize_store(data, org_id):
    store = _empty_store(org_id)
    if not isinstance(data, dict):
        return store
    store.update({k: v for k, v in data.items() if k not in ('handoff_previews', '_meta')})
    meta = dict(store.get('_meta', {}))
    meta.update(data.get('_meta', {}) or {})
    meta['bound_org_id'] = (org_id or '').strip()
    store['_meta'] = meta

    raw_previews = data.get('handoff_previews', {})
    previews = {}
    if isinstance(raw_previews, list):
        for item in raw_previews:
            if isinstance(item, dict) and item.get('handoff_id'):
                previews[item['handoff_id']] = dict(item)
    elif isinstance(raw_previews, dict):
        for handoff_id, item in raw_previews.items():
            if isinstance(item, dict):
                record = dict(item)
                record['handoff_id'] = record.get('handoff_id') or handoff_id
                previews[record['handoff_id']] = record
    for handoff_id, record in list(previews.items()):
        record = dict(record or {})
        record['state'] = _normalize_state(record.get('state') or record.get('handoff_state') or '')
        record['handoff_state'] = record.get('handoff_state') or record['state']
        record['previewed_at'] = (record.get('previewed_at') or record.get('generated_at') or '').strip()
        record['updated_at'] = (record.get('updated_at') or '').strip()
        previews[handoff_id] = record
    store['handoff_previews'] = previews
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
        prefix='.federation_handoff_queue.',
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
def _handoff_lock(org_id):
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
        'handoff_id': (record.get('handoff_id') or '').strip(),
        'bound_org_id': (record.get('bound_org_id') or '').strip(),
        'requested_org_id': (record.get('requested_org_id') or '').strip(),
        'route_kind': (record.get('route_kind') or '').strip(),
        'route_state': (record.get('route_state') or '').strip(),
        'route_reason': (record.get('route_reason') or '').strip(),
        'handoff_state': (record.get('handoff_state') or '').strip(),
        'dispatch_ready': bool(record.get('dispatch_ready')),
        'dispatch_blockers': list(record.get('dispatch_blockers') or []),
        'draft_execution_request': dict(record.get('draft_execution_request') or {}),
        'acknowledged': bool(record.get('acknowledged')),
        'acknowledged_by': (record.get('acknowledged_by') or '').strip(),
        'acknowledged_at': (record.get('acknowledged_at') or '').strip(),
        'acknowledged_note': (record.get('acknowledged_note') or '').strip(),
        'settlement_claimed': bool(record.get('settlement_claimed')),
        'external_settlement_observed': bool(record.get('external_settlement_observed')),
    }
    return _canonical_hash(digest_payload)


def _normalize_preview(preview, org_id, existing=None):
    preview = dict(preview or {})
    existing = dict(existing or {})
    handoff_id = (preview.get('handoff_id') or existing.get('handoff_id') or '').strip()
    if not handoff_id:
        raise ValueError('handoff_id is required')

    record = dict(existing)
    record['handoff_id'] = handoff_id
    record['bound_org_id'] = (org_id or '').strip()
    record['requested_org_id'] = (preview.get('requested_org_id') or existing.get('requested_org_id') or '').strip()
    record['route_kind'] = (preview.get('route_kind') or existing.get('route_kind') or '').strip()
    record['route_state'] = (preview.get('route_state') or existing.get('route_state') or '').strip()
    record['route_reason'] = (preview.get('route_reason') or existing.get('route_reason') or '').strip()
    record['handoff_state'] = _normalize_state(
        preview.get('handoff_state') or preview.get('state') or existing.get('handoff_state') or existing.get('state') or '',
        existing_state=existing.get('handoff_state') or existing.get('state') or '',
    )
    record['state'] = record['handoff_state']
    if 'dispatch_ready' in preview:
        record['dispatch_ready'] = bool(preview.get('dispatch_ready'))
    elif 'dispatch_ready' not in record:
        record['dispatch_ready'] = False
    if 'dispatch_blockers' in preview:
        record['dispatch_blockers'] = list(preview.get('dispatch_blockers') or [])
    elif 'dispatch_blockers' not in record:
        record['dispatch_blockers'] = []
    if 'acknowledged' in preview:
        record['acknowledged'] = bool(preview.get('acknowledged'))
    elif 'acknowledged' not in record:
        record['acknowledged'] = False
    if 'acknowledged_by' in preview or 'acknowledged_by' not in record:
        record['acknowledged_by'] = (preview.get('acknowledged_by') or existing.get('acknowledged_by') or '').strip()
    if 'acknowledged_at' in preview or 'acknowledged_at' not in record:
        record['acknowledged_at'] = (preview.get('acknowledged_at') or existing.get('acknowledged_at') or '').strip()
    if 'acknowledged_note' in preview or 'acknowledged_note' not in record:
        record['acknowledged_note'] = (preview.get('acknowledged_note') or existing.get('acknowledged_note') or '').strip()
    if 'preview_truth_source' in preview or 'preview_truth_source' not in record:
        record['preview_truth_source'] = (preview.get('preview_truth_source') or existing.get('preview_truth_source') or '').strip()
    if 'dispatch_paths' in preview:
        record['dispatch_paths'] = dict(preview.get('dispatch_paths') or {})
    elif 'dispatch_paths' not in record:
        record['dispatch_paths'] = {}
    if 'draft_execution_request' in preview:
        record['draft_execution_request'] = dict(preview.get('draft_execution_request') or {})
    elif 'draft_execution_request' not in record:
        record['draft_execution_request'] = {}
    if 'remote_execution_claimed' in preview:
        record['remote_execution_claimed'] = bool(preview.get('remote_execution_claimed'))
    elif 'remote_execution_claimed' not in record:
        record['remote_execution_claimed'] = False
    if 'settlement_claimed' in preview:
        record['settlement_claimed'] = bool(preview.get('settlement_claimed'))
    elif 'settlement_claimed' not in record:
        record['settlement_claimed'] = False
    if 'external_settlement_observed' in preview:
        record['external_settlement_observed'] = bool(preview.get('external_settlement_observed'))
    elif 'external_settlement_observed' not in record:
        record['external_settlement_observed'] = False

    draft = dict(record.get('draft_execution_request') or {})
    record['source_host_id'] = (preview.get('source_host_id') or draft.get('source_host_id') or existing.get('source_host_id') or '').strip()
    record['source_institution_id'] = (preview.get('source_institution_id') or draft.get('source_institution_id') or existing.get('source_institution_id') or '').strip()
    record['target_host_id'] = (preview.get('target_host_id') or draft.get('target_host_id') or existing.get('target_host_id') or '').strip()
    record['target_institution_id'] = (preview.get('target_institution_id') or draft.get('target_institution_id') or existing.get('target_institution_id') or '').strip()
    record['target_endpoint_url'] = (preview.get('target_endpoint_url') or existing.get('target_endpoint_url') or '').strip()
    record['peer_host_id'] = (preview.get('peer_host_id') or existing.get('peer_host_id') or '').strip()
    record['peer_label'] = (preview.get('peer_label') or existing.get('peer_label') or '').strip()
    record['peer_trust_state'] = (preview.get('peer_trust_state') or existing.get('peer_trust_state') or '').strip()
    record['generated_at'] = (preview.get('generated_at') or existing.get('generated_at') or _now()).strip()
    record['previewed_at'] = (preview.get('previewed_at') or existing.get('previewed_at') or record['generated_at']).strip()
    record['queued_at'] = (preview.get('queued_at') or existing.get('queued_at') or record['previewed_at']).strip()
    record['updated_at'] = _now()
    if 'note' in preview or 'note' not in record:
        record['note'] = (preview.get('note') or existing.get('note') or '').strip()
    if 'superseded_by' in preview or 'superseded_by' not in record:
        record['superseded_by'] = (preview.get('superseded_by') or existing.get('superseded_by') or '').strip()
    if 'preview_digest' in preview or 'preview_digest' not in record:
        record['preview_digest'] = (preview.get('preview_digest') or _preview_digest(record)).strip()
    return record


def get_handoff_preview(handoff_id, org_id):
    handoff_id = (handoff_id or '').strip()
    if not handoff_id:
        return None
    store = _load_store(org_id)
    return store.get('handoff_previews', {}).get(handoff_id)


def acknowledge_handoff_preview(org_id, handoff_id, *, by, note=''):
    handoff_id = (handoff_id or '').strip()
    by = (by or '').strip()
    if not handoff_id:
        raise ValueError('handoff_id is required')
    if not by:
        raise ValueError('by is required')
    with _handoff_lock(org_id):
        store = _load_store(org_id)
        record = store.get('handoff_previews', {}).get(handoff_id)
        if not record:
            raise LookupError(f'Federation handoff preview not found: {handoff_id}')
        if not record.get('acknowledged'):
            timestamp = _now()
            record['acknowledged'] = True
            record['acknowledged_at'] = timestamp
            record['acknowledged_by'] = by
            record['acknowledged_note'] = (note or '').strip()
            record['updated_at'] = timestamp
            store['handoff_previews'][handoff_id] = record
            _save_store(store, org_id)
        return record


def list_handoff_previews(org_id, *, state=None):
    parent = os.path.dirname(_store_path(org_id))
    if org_id and not os.path.isdir(parent):
        return []
    store = _load_store(org_id)
    previews = list(store.get('handoff_previews', {}).values())
    if state:
        previews = [row for row in previews if row.get('state') == state or row.get('handoff_state') == state]
    previews.sort(key=lambda row: row.get('previewed_at', '') or row.get('generated_at', ''), reverse=True)
    return previews


def upsert_handoff_preview(org_id, preview=None, **preview_fields):
    payload = dict(preview or {})
    payload.update(preview_fields)
    with _handoff_lock(org_id):
        store = _load_store(org_id)
        existing = None
        if payload.get('handoff_id'):
            existing = store.get('handoff_previews', {}).get(payload['handoff_id'])
        record = _normalize_preview(payload, org_id, existing=existing)
        store.setdefault('handoff_previews', {})[record['handoff_id']] = record
        _save_store(store, org_id)
        return record


def handoff_preview_queue_summary(org_id):
    parent = os.path.dirname(_store_path(org_id))
    if org_id and not os.path.isdir(parent):
        return {
            'org_id': (org_id or '').strip(),
            'total': 0,
            'previewed': 0,
            'blocked': 0,
            'superseded': 0,
            'dispatch_ready': 0,
            'remote_execution_claimed': 0,
            'state_counts': {},
            'route_kind_counts': {},
            'updatedAt': _now(),
        }
    store = _load_store(org_id)
    state_counts = {}
    route_kind_counts = {}
    dispatch_ready = 0
    acknowledged = 0
    acknowledgement_pending = 0
    remote_execution_claimed = 0
    for record in store.get('handoff_previews', {}).values():
        state = (record.get('state') or record.get('handoff_state') or '').strip() or 'previewed'
        record['state'] = state
        record['handoff_state'] = record.get('handoff_state') or state
        state_counts[state] = state_counts.get(state, 0) + 1
        route_kind = (record.get('route_kind') or '').strip() or 'unknown'
        route_kind_counts[route_kind] = route_kind_counts.get(route_kind, 0) + 1
        if record.get('dispatch_ready'):
            dispatch_ready += 1
        if record.get('acknowledged'):
            acknowledged += 1
        elif record.get('dispatch_ready') and state == 'previewed':
            acknowledgement_pending += 1
        if record.get('remote_execution_claimed'):
            remote_execution_claimed += 1
    return {
        'org_id': (org_id or '').strip(),
        'total': len(store.get('handoff_previews', {})),
        'previewed': state_counts.get('previewed', 0),
        'blocked': state_counts.get('blocked', 0),
        'superseded': state_counts.get('superseded', 0),
        'dispatch_ready': dispatch_ready,
        'acknowledged': acknowledged,
        'acknowledgement_pending': acknowledgement_pending,
        'remote_execution_claimed': remote_execution_claimed,
        'state_counts': state_counts,
        'route_kind_counts': dict(sorted(route_kind_counts.items())),
        'updatedAt': store.get('updatedAt', _now()),
    }


def handoff_preview_queue_snapshot(org_id, *, state=None, limit=50):
    summary = handoff_preview_queue_summary(org_id)
    records = list_handoff_previews(org_id, state=state)
    if limit is not None:
        records = records[:max(0, int(limit))]
    return {
        'summary': summary,
        'handoff_previews': records,
    }


def summarize_handoff_previews(org_id):
    return handoff_preview_queue_summary(org_id)


def summary(org_id):
    return handoff_preview_queue_summary(org_id)
