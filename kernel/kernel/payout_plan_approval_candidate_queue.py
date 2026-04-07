#!/usr/bin/env python3
"""
Capsule-backed approval-candidate queue for payout-plan previews.

This store is intentionally narrow:

- approval candidates are institution-scoped and file-backed
- entries are keyed by candidate_id for idempotent upsert
- records preserve the preview snapshot, operator acknowledgement, and the
  local promotion context that would be needed for later approval review
- no settlement is claimed here; the queue only records the next local
  review bridge after a payout-plan preview has been acknowledged
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


STORE_FILE = 'payout_plan_approval_candidate_queue.json'
LOCK_FILE = '.payout_plan_approval_candidate_queue.lock'
QUEUE_STATES = (
    'candidate',
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
        'payout_plan_approval_candidates': {},
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
            f"Unknown payout-plan approval-candidate state {state!r}. Must be one of {QUEUE_STATES}"
        )
    if state:
        return state
    return existing_state or 'candidate'


def _normalize_store(data, org_id):
    store = _empty_store(org_id)
    if not isinstance(data, dict):
        return store
    store.update({k: v for k, v in data.items() if k not in ('payout_plan_approval_candidates', '_meta')})
    meta = dict(store.get('_meta', {}))
    meta.update(data.get('_meta', {}) or {})
    meta['bound_org_id'] = (org_id or '').strip()
    store['_meta'] = meta

    raw_candidates = data.get('payout_plan_approval_candidates', {})
    candidates = {}
    if isinstance(raw_candidates, list):
        for item in raw_candidates:
            if isinstance(item, dict) and item.get('candidate_id'):
                candidates[item['candidate_id']] = dict(item)
    elif isinstance(raw_candidates, dict):
        for candidate_id, item in raw_candidates.items():
            if isinstance(item, dict):
                record = dict(item)
                record['candidate_id'] = record.get('candidate_id') or candidate_id
                candidates[record['candidate_id']] = record
    for candidate_id, record in list(candidates.items()):
        record = dict(record or {})
        record['state'] = _normalize_state(record.get('state') or record.get('candidate_state') or '')
        record['candidate_state'] = record.get('candidate_state') or record['state']
        record['previewed_at'] = (record.get('previewed_at') or record.get('generated_at') or '').strip()
        record['promoted_at'] = (record.get('promoted_at') or '').strip()
        record['updated_at'] = (record.get('updated_at') or '').strip()
        candidates[candidate_id] = record
    store['payout_plan_approval_candidates'] = candidates
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
        prefix='.payout_plan_approval_candidate_queue.',
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
def _candidate_lock(org_id):
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


def _candidate_digest(record):
    record = dict(record or {})
    digest_payload = {
        'candidate_id': (record.get('candidate_id') or '').strip(),
        'bound_org_id': (record.get('bound_org_id') or '').strip(),
        'source_preview_id': (record.get('source_preview_id') or '').strip(),
        'proposal_id': (record.get('proposal_id') or '').strip(),
        'settlement_adapter': (record.get('settlement_adapter') or '').strip(),
        'preview_state': (record.get('preview_state') or '').strip(),
        'candidate_state': (record.get('candidate_state') or '').strip(),
        'candidate_ready_for_approval': bool(record.get('candidate_ready_for_approval')),
        'preview_acknowledged': bool(record.get('preview_acknowledged')),
        'settlement_claimed': bool(record.get('settlement_claimed')),
        'external_settlement_observed': bool(record.get('external_settlement_observed')),
        'execution_plan': dict(record.get('execution_plan') or {}),
    }
    return _canonical_hash(digest_payload)


def _candidate_inspection_state(record):
    record = dict(record or {})
    state = (record.get('state') or record.get('candidate_state') or '').strip() or 'candidate'
    if record.get('settlement_claimed'):
        return 'settlement_claimed'
    if record.get('external_settlement_observed'):
        return 'external_settlement_observed'
    if state == 'blocked':
        return 'blocked'
    if state == 'superseded':
        return 'superseded'
    if record.get('candidate_ready_for_approval'):
        return 'ready_for_approval'
    if record.get('preview_acknowledged'):
        return 'candidate_recorded'
    return 'needs_preview_acknowledgement'


def _inspected_candidate_record(record):
    inspected = dict(record or {})
    inspection_state = _candidate_inspection_state(inspected)
    inspected['inspection_state'] = inspection_state
    inspected['inspection_required'] = inspection_state == 'ready_for_approval'
    inspected['inspection_message'] = {
        'settlement_claimed': 'Candidate records a claimed settlement reference but remains non-executable here.',
        'external_settlement_observed': 'Candidate observed external settlement evidence; no settlement execution is claimed.',
        'blocked': 'Candidate is blocked and needs operator review.',
        'superseded': 'Candidate was superseded by a newer promotion record.',
        'ready_for_approval': 'Candidate is acknowledged and ready for approval review.',
        'candidate_recorded': 'Candidate is recorded but still awaiting local approval review.',
        'needs_preview_acknowledgement': 'Candidate promotion requires an acknowledged preview first.',
    }[inspection_state]
    return inspected


def _normalize_candidate(candidate, org_id, existing=None):
    candidate = dict(candidate or {})
    existing = dict(existing or {})
    candidate_id = (candidate.get('candidate_id') or existing.get('candidate_id') or '').strip()
    if not candidate_id:
        candidate_id = (candidate.get('source_preview_id') or existing.get('source_preview_id') or '').strip()
    if not candidate_id:
        raise ValueError('candidate_id is required')

    record = dict(existing)
    record['candidate_id'] = candidate_id
    record['bound_org_id'] = (org_id or '').strip()
    record['source_preview_id'] = (
        candidate.get('source_preview_id')
        or candidate.get('preview_id')
        or existing.get('source_preview_id')
        or existing.get('preview_id')
        or candidate_id
    ).strip()
    record['proposal_id'] = (candidate.get('proposal_id') or existing.get('proposal_id') or '').strip()
    record['warrant_id'] = (candidate.get('warrant_id') or existing.get('warrant_id') or '').strip()
    record['status_at_preview'] = (
        candidate.get('status_at_preview')
        or existing.get('status_at_preview')
        or candidate.get('preview_state')
        or ''
    ).strip()
    record['settlement_adapter'] = (
        candidate.get('settlement_adapter')
        or existing.get('settlement_adapter')
        or ''
    ).strip()
    record['preview_state'] = (
        candidate.get('preview_state')
        or candidate.get('source_preview_state')
        or existing.get('preview_state')
        or ''
    ).strip() or 'previewed'
    record['candidate_state'] = _normalize_state(
        candidate.get('candidate_state') or candidate.get('state') or existing.get('candidate_state') or existing.get('state') or '',
        existing_state=existing.get('candidate_state') or existing.get('state') or '',
    )
    record['state'] = record['candidate_state']
    if 'candidate_ready_for_approval' in candidate:
        record['candidate_ready_for_approval'] = bool(candidate.get('candidate_ready_for_approval'))
    elif 'candidate_ready_for_approval' not in record:
        record['candidate_ready_for_approval'] = False
    if 'preview_acknowledged' in candidate:
        record['preview_acknowledged'] = bool(candidate.get('preview_acknowledged'))
    elif 'preview_acknowledged' not in record:
        record['preview_acknowledged'] = False
    if 'preview_acknowledged_at' in candidate or 'preview_acknowledged_at' not in record:
        record['preview_acknowledged_at'] = (
            candidate.get('preview_acknowledged_at')
            or existing.get('preview_acknowledged_at')
            or ''
        ).strip()
    if 'preview_acknowledged_by' in candidate or 'preview_acknowledged_by' not in record:
        record['preview_acknowledged_by'] = (
            candidate.get('preview_acknowledged_by')
            or existing.get('preview_acknowledged_by')
            or ''
        ).strip()
    if 'preview_acknowledged_note' in candidate or 'preview_acknowledged_note' not in record:
        record['preview_acknowledged_note'] = (
            candidate.get('preview_acknowledged_note')
            or existing.get('preview_acknowledged_note')
            or ''
        ).strip()
    if 'settlement_claimed' in candidate or 'settlement_claimed' not in record:
        record['settlement_claimed'] = bool(candidate.get('settlement_claimed', existing.get('settlement_claimed', False)))
    if 'external_settlement_observed' in candidate or 'external_settlement_observed' not in record:
        record['external_settlement_observed'] = bool(
            candidate.get('external_settlement_observed', existing.get('external_settlement_observed', False))
        )
    if 'approval_candidate_truth_source' in candidate or 'approval_candidate_truth_source' not in record:
        record['approval_candidate_truth_source'] = (
            candidate.get('approval_candidate_truth_source')
            or existing.get('approval_candidate_truth_source')
            or ''
        ).strip()
    if 'promotion_context' in candidate:
        record['promotion_context'] = dict(candidate.get('promotion_context') or {})
    elif 'promotion_context' not in record:
        record['promotion_context'] = {}
    if 'execution_plan' in candidate:
        record['execution_plan'] = dict(candidate.get('execution_plan') or {})
    elif 'execution_plan' not in record:
        record['execution_plan'] = {}
    if 'proposal_snapshot' in candidate:
        record['proposal_snapshot'] = dict(candidate.get('proposal_snapshot') or {})
    elif 'proposal_snapshot' not in record:
        record['proposal_snapshot'] = {}
    if 'preview_snapshot' in candidate:
        record['preview_snapshot'] = dict(candidate.get('preview_snapshot') or {})
    elif 'preview_snapshot' not in record:
        record['preview_snapshot'] = {}
    if 'candidate_digest' in candidate or 'candidate_digest' not in record:
        record['candidate_digest'] = (candidate.get('candidate_digest') or _candidate_digest(record)).strip()
    record['generated_at'] = (candidate.get('generated_at') or existing.get('generated_at') or _now()).strip()
    record['previewed_at'] = (candidate.get('previewed_at') or existing.get('previewed_at') or record['generated_at']).strip()
    record['queued_at'] = (candidate.get('queued_at') or existing.get('queued_at') or record['previewed_at']).strip()
    record['promoted_at'] = (candidate.get('promoted_at') or existing.get('promoted_at') or '').strip()
    record['updated_at'] = _now()
    if 'note' in candidate or 'note' not in record:
        record['note'] = (candidate.get('note') or existing.get('note') or '').strip()
    if 'superseded_by' in candidate or 'superseded_by' not in record:
        record['superseded_by'] = (candidate.get('superseded_by') or existing.get('superseded_by') or '').strip()
    if 'promoted_by' in candidate or 'promoted_by' not in record:
        record['promoted_by'] = (candidate.get('promoted_by') or existing.get('promoted_by') or '').strip()
    if 'promotion_note' in candidate or 'promotion_note' not in record:
        record['promotion_note'] = (candidate.get('promotion_note') or existing.get('promotion_note') or '').strip()
    return record


def load_payout_plan_approval_candidate_queue(org_id):
    store = _load_store(org_id)
    if not os.path.exists(_store_path(org_id)):
        _save_store(store, org_id)
    return store


def get_payout_plan_approval_candidate(candidate_id, org_id):
    candidate_id = (candidate_id or '').strip()
    if not candidate_id:
        return None
    store = _load_store(org_id)
    return store.get('payout_plan_approval_candidates', {}).get(candidate_id)


def list_payout_plan_approval_candidates(org_id, *, state=None):
    parent = os.path.dirname(_store_path(org_id))
    if org_id and not os.path.isdir(parent):
        return []
    store = _load_store(org_id)
    candidates = list(store.get('payout_plan_approval_candidates', {}).values())
    if state:
        candidates = [row for row in candidates if row.get('state') == state or row.get('candidate_state') == state]
    candidates.sort(key=lambda row: row.get('promoted_at', '') or row.get('previewed_at', '') or row.get('generated_at', ''), reverse=True)
    return candidates


def promote_payout_plan_preview_to_approval_candidate(org_id, preview, *, promoted_by, promotion_note=''):
    from payout_plan_preview_queue import get_payout_plan_preview

    preview_id = ''
    if isinstance(preview, str):
        preview_id = preview.strip()
    elif isinstance(preview, dict):
        preview_id = (preview.get('preview_id') or preview.get('tx_ref') or preview.get('source_preview_id') or '').strip()
    if not preview_id:
        raise ValueError('preview_id is required')
    promoted_by = (promoted_by or '').strip()
    if not promoted_by:
        raise ValueError('promoted_by is required')

    preview_record = get_payout_plan_preview(preview_id, org_id)
    if not preview_record:
        raise LookupError(f'Payout-plan preview not found: {preview_id}')
    if preview_record.get('settlement_claimed'):
        raise PermissionError(
            f"Payout-plan preview '{preview_id}' already records a settlement claim and cannot be promoted"
        )
    if preview_record.get('external_settlement_observed'):
        raise PermissionError(
            f"Payout-plan preview '{preview_id}' observed external settlement evidence and cannot be promoted"
        )
    if not preview_record.get('acknowledged'):
        raise PermissionError(
            f"Payout-plan preview '{preview_id}' must be acknowledged before it can be promoted"
        )

    with _candidate_lock(org_id):
        store = _load_store(org_id)
        existing = store.get('payout_plan_approval_candidates', {}).get(preview_id)
        timestamp = _now()
        candidate_record = _normalize_candidate({
            'candidate_id': preview_id,
            'source_preview_id': preview_id,
            'proposal_id': preview_record.get('proposal_id', ''),
            'warrant_id': preview_record.get('warrant_id', ''),
            'status_at_preview': preview_record.get('status_at_preview', ''),
            'settlement_adapter': preview_record.get('settlement_adapter', ''),
            'preview_state': preview_record.get('preview_state', ''),
            'candidate_state': 'candidate',
            'candidate_ready_for_approval': True,
            'preview_acknowledged': True,
            'preview_acknowledged_at': preview_record.get('acknowledged_at', ''),
            'preview_acknowledged_by': preview_record.get('acknowledged_by', ''),
            'preview_acknowledged_note': preview_record.get('acknowledged_note', ''),
            'approval_candidate_truth_source': 'payout_preview_acknowledgement_and_local_policy_only',
            'preview_snapshot': dict(preview_record),
            'execution_plan': dict(preview_record.get('execution_plan') or {}),
            'proposal_snapshot': dict(preview_record.get('proposal_snapshot') or {}),
            'generated_at': preview_record.get('generated_at', timestamp),
            'previewed_at': preview_record.get('previewed_at', timestamp),
            'queued_at': preview_record.get('queued_at', timestamp),
            'promoted_at': timestamp,
            'promoted_by': promoted_by,
            'promotion_note': (promotion_note or '').strip(),
            'note': (preview_record.get('note') or '').strip(),
            'settlement_claimed': False,
            'external_settlement_observed': False,
            'promotion_context': {
                'source_preview_digest': (preview_record.get('plan_digest') or '').strip(),
                'preview_acknowledged_by': preview_record.get('acknowledged_by', ''),
                'preview_acknowledged_at': preview_record.get('acknowledged_at', ''),
            },
        }, org_id, existing=existing)
        store.setdefault('payout_plan_approval_candidates', {})[candidate_record['candidate_id']] = candidate_record
        _save_store(store, org_id)
        return candidate_record


def upsert_payout_plan_approval_candidate(org_id, candidate=None, **candidate_fields):
    payload = dict(candidate or {})
    payload.update(candidate_fields)
    with _candidate_lock(org_id):
        store = _load_store(org_id)
        existing = None
        candidate_id = (payload.get('candidate_id') or payload.get('source_preview_id') or '').strip()
        if candidate_id:
            existing = store.get('payout_plan_approval_candidates', {}).get(candidate_id)
        record = _normalize_candidate(payload, org_id, existing=existing)
        store.setdefault('payout_plan_approval_candidates', {})[record['candidate_id']] = record
        _save_store(store, org_id)
        return record


def payout_plan_approval_candidate_queue_summary(org_id):
    parent = os.path.dirname(_store_path(org_id))
    if org_id and not os.path.isdir(parent):
        return {
            'org_id': (org_id or '').strip(),
            'total': 0,
            'candidate': 0,
            'blocked': 0,
            'superseded': 0,
            'ready_for_approval': 0,
            'settlement_claimed': 0,
            'external_settlement_observed': 0,
            'candidate_recorded': 0,
            'state_counts': {},
            'adapter_counts': {},
            'updatedAt': _now(),
        }
    store = _load_store(org_id)
    state_counts = {}
    adapter_counts = {}
    ready_for_approval = 0
    settlement_claimed = 0
    external_settlement_observed = 0
    candidate_recorded = 0
    for record in store.get('payout_plan_approval_candidates', {}).values():
        state = (record.get('state') or record.get('candidate_state') or '').strip() or 'candidate'
        record['state'] = state
        record['candidate_state'] = record.get('candidate_state') or state
        state_counts[state] = state_counts.get(state, 0) + 1
        adapter_id = (record.get('settlement_adapter') or '').strip() or 'unknown'
        adapter_counts[adapter_id] = adapter_counts.get(adapter_id, 0) + 1
        if record.get('candidate_ready_for_approval'):
            ready_for_approval += 1
        if record.get('settlement_claimed'):
            settlement_claimed += 1
        if record.get('external_settlement_observed'):
            external_settlement_observed += 1
        if record.get('preview_acknowledged') and not record.get('candidate_ready_for_approval'):
            candidate_recorded += 1
    return {
        'org_id': (org_id or '').strip(),
        'total': len(store.get('payout_plan_approval_candidates', {})),
        'candidate': state_counts.get('candidate', 0),
        'blocked': state_counts.get('blocked', 0),
        'superseded': state_counts.get('superseded', 0),
        'ready_for_approval': ready_for_approval,
        'settlement_claimed': settlement_claimed,
        'external_settlement_observed': external_settlement_observed,
        'candidate_recorded': candidate_recorded,
        'state_counts': state_counts,
        'adapter_counts': dict(sorted(adapter_counts.items())),
        'updatedAt': store.get('updatedAt', _now()),
    }


def payout_plan_approval_candidate_queue_snapshot(org_id, *, state=None, limit=50):
    summary = payout_plan_approval_candidate_queue_summary(org_id)
    records = list_payout_plan_approval_candidates(org_id, state=state)
    if limit is not None:
        records = records[:max(0, int(limit))]
    return {
        'summary': summary,
        'payout_plan_approval_candidates': records,
    }


def inspect_payout_plan_approval_candidate_queue(org_id, *, state=None, limit=50):
    snapshot = payout_plan_approval_candidate_queue_snapshot(org_id, state=state, limit=limit)
    inspected_records = [_inspected_candidate_record(record) for record in snapshot['payout_plan_approval_candidates']]
    inspection_state_counts = {}
    for record in inspected_records:
        inspection_state = record.get('inspection_state', 'candidate')
        inspection_state_counts[inspection_state] = inspection_state_counts.get(inspection_state, 0) + 1
    inspection_summary = {
        'org_id': (org_id or '').strip(),
        'total': len(inspected_records),
        'ready_for_approval': inspection_state_counts.get('ready_for_approval', 0),
        'candidate_recorded': inspection_state_counts.get('candidate_recorded', 0),
        'blocked': inspection_state_counts.get('blocked', 0),
        'superseded': inspection_state_counts.get('superseded', 0),
        'settlement_claimed': inspection_state_counts.get('settlement_claimed', 0),
        'external_settlement_observed': inspection_state_counts.get('external_settlement_observed', 0),
        'requires_operator_review': inspection_state_counts.get('ready_for_approval', 0),
        'inspection_state_counts': dict(sorted(inspection_state_counts.items())),
        'inspected_at': _now(),
    }
    return {
        'summary': snapshot['summary'],
        'inspection_summary': inspection_summary,
        'payout_plan_approval_candidates': inspected_records,
    }


def summarize_payout_plan_approval_candidates(org_id):
    return payout_plan_approval_candidate_queue_summary(org_id)


def summary(org_id):
    return payout_plan_approval_candidate_queue_summary(org_id)
