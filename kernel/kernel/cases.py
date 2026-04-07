#!/usr/bin/env python3
"""
Inter-institution case primitives for Meridian Kernel.

This is the first public case object for cross-institution dispute handling.
It does not claim the full network court program. It does establish:

- institution-scoped, capsule-backed case records
- explicit target host / target institution binding
- open / stay / resolve lifecycle transitions
- breach-to-case linkage for commitment failures
"""
from __future__ import annotations

import datetime
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


CASE_STATES = (
    'open',
    'stayed',
    'resolved',
)

BLOCKING_CASE_STATES = (
    'open',
    'stayed',
)

CLAIM_TYPES = (
    'non_delivery',
    'fraudulent_proof',
    'breach_of_commitment',
    'invalid_settlement_notice',
    'misrouted_execution',
)

PEER_SUSPENSION_CLAIM_TYPES = (
    'fraudulent_proof',
    'invalid_settlement_notice',
    'misrouted_execution',
    'breach_of_commitment',
)


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _missing_org_error(org_id):
    raise SystemExit(
        f"ERROR: institution '{org_id}' is not initialized. Run quickstart.py --init-only or bootstrap the capsule first."
    )


def _store_path(org_id=None):
    return capsule_path(org_id, 'cases.json')


def _empty_store():
    return {
        'cases': {},
        'updatedAt': _now(),
        'states': list(CASE_STATES),
        'claim_types': list(CLAIM_TYPES),
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


def _matching_active_case(
    org_id,
    *,
    claim_type,
    target_host_id='',
    target_institution_id='',
    linked_commitment_id='',
    linked_warrant_id='',
):
    for existing in blocking_cases(org_id):
        if (
            existing.get('claim_type') == claim_type
            and (existing.get('target_host_id') or '').strip() == target_host_id
            and (existing.get('target_institution_id') or '').strip() == target_institution_id
            and (existing.get('linked_commitment_id') or '').strip() == linked_commitment_id
            and (existing.get('linked_warrant_id') or '').strip() == linked_warrant_id
        ):
            return existing
    return None


def open_case(org_id, claim_type, actor_id, *, target_host_id='',
              target_institution_id='', linked_commitment_id='',
              linked_warrant_id='', evidence_refs=None, note='',
              metadata=None, dedupe_existing=False):
    claim_type = (claim_type or '').strip()
    actor_id = (actor_id or '').strip()
    target_host_id = (target_host_id or '').strip()
    target_institution_id = (target_institution_id or '').strip()
    if claim_type not in CLAIM_TYPES:
        raise ValueError(f'Unknown claim_type {claim_type!r}. Must be one of {CLAIM_TYPES}')
    if not actor_id:
        raise ValueError('actor_id is required')
    if dedupe_existing:
        existing = _matching_active_case(
            org_id,
            claim_type=claim_type,
            target_host_id=target_host_id,
            target_institution_id=target_institution_id,
            linked_commitment_id=(linked_commitment_id or '').strip(),
            linked_warrant_id=(linked_warrant_id or '').strip(),
        )
        if existing:
            return existing
    timestamp = _now()
    case_id = f'case_{uuid.uuid4().hex[:12]}'
    record = {
        'case_id': case_id,
        'institution_id': org_id,
        'source_institution_id': org_id,
        'target_host_id': target_host_id,
        'target_institution_id': target_institution_id,
        'claim_type': claim_type,
        'linked_commitment_id': (linked_commitment_id or '').strip(),
        'linked_warrant_id': (linked_warrant_id or '').strip(),
        'evidence_refs': list(evidence_refs or []),
        'status': 'open',
        'opened_by': actor_id,
        'opened_at': timestamp,
        'updated_at': timestamp,
        'reviewed_by': '',
        'reviewed_at': '',
        'review_note': '',
        'resolution': '',
        'note': note or '',
        'metadata': dict(metadata or {}),
    }
    store = _load_store(org_id)
    store.setdefault('cases', {})[case_id] = record
    _save_store(store, org_id)
    return record


def list_cases(org_id=None, *, status=None, claim_type=None):
    store = _load_store(org_id)
    rows = list(store.get('cases', {}).values())
    if status:
        rows = [row for row in rows if row.get('status') == status]
    if claim_type:
        rows = [row for row in rows if row.get('claim_type') == claim_type]
    rows.sort(key=lambda row: row.get('opened_at', ''), reverse=True)
    return rows


def get_case(case_id, org_id=None):
    if not case_id:
        return None
    store = _load_store(org_id)
    return store.get('cases', {}).get(case_id)


def review_case(case_id, decision, by, *, org_id=None, note=''):
    decision = (decision or '').strip()
    state_map = {
        'stay': 'stayed',
        'resolve': 'resolved',
    }
    if decision not in state_map:
        raise ValueError(f'Unsupported case decision: {decision}')
    store = _load_store(org_id)
    record = store.get('cases', {}).get(case_id)
    if not record:
        raise ValueError(f'Case not found: {case_id}')
    timestamp = _now()
    record['status'] = state_map[decision]
    record['reviewed_by'] = (by or '').strip()
    record['reviewed_at'] = timestamp
    record['review_note'] = note or ''
    record['updated_at'] = timestamp
    if decision == 'resolve':
        record['resolution'] = note or 'resolved'
    _save_store(store, org_id)
    return record


def stay_case(case_id, by, *, org_id=None, note=''):
    return review_case(case_id, 'stay', by, org_id=org_id, note=note)


def resolve_case(case_id, by, *, org_id=None, note=''):
    return review_case(case_id, 'resolve', by, org_id=org_id, note=note)


def case_summary(org_id=None):
    rows = list_cases(org_id)
    summary = {
        'total': len(rows),
        'open': 0,
        'stayed': 0,
        'resolved': 0,
    }
    for row in rows:
        status = row.get('status', '')
        if status in summary:
            summary[status] += 1
    return summary


def _safe_list_cases(org_id=None):
    try:
        return list_cases(org_id)
    except SystemExit:
        return []


def blocking_cases(org_id=None):
    return [
        row for row in _safe_list_cases(org_id)
        if row.get('status') in BLOCKING_CASE_STATES
    ]


def case_requires_peer_block(case_record):
    case_record = dict(case_record or {})
    return (
        case_record.get('status') in BLOCKING_CASE_STATES
        and case_targets_peer(case_record)
    )


def case_targets_peer(case_record):
    case_record = dict(case_record or {})
    return (
        case_record.get('claim_type') in PEER_SUSPENSION_CLAIM_TYPES
        and bool((case_record.get('target_host_id') or '').strip())
    )


def blocking_commitment_case(commitment_id, org_id=None):
    commitment_id = (commitment_id or '').strip()
    if not commitment_id:
        return None
    for row in blocking_cases(org_id):
        if row.get('linked_commitment_id') == commitment_id:
            return row
    return None


def blocking_peer_case(peer_host_id, org_id=None, *, claim_types=None):
    peer_host_id = (peer_host_id or '').strip()
    if not peer_host_id:
        return None
    allowed_claim_types = set(claim_types or PEER_SUSPENSION_CLAIM_TYPES)
    for row in blocking_cases(org_id):
        if (
            row.get('target_host_id') == peer_host_id
            and row.get('claim_type') in allowed_claim_types
            and case_requires_peer_block(row)
        ):
            return row
    return None


def blocking_commitment_ids(org_id=None):
    seen = []
    for row in blocking_cases(org_id):
        commitment_id = (row.get('linked_commitment_id') or '').strip()
        if commitment_id and commitment_id not in seen:
            seen.append(commitment_id)
    return sorted(seen)


def blocked_peer_host_ids(org_id=None):
    seen = []
    for row in blocking_cases(org_id):
        peer_host_id = (row.get('target_host_id') or '').strip()
        if peer_host_id and case_requires_peer_block(row) and peer_host_id not in seen:
            seen.append(peer_host_id)
    return sorted(seen)


def _commitment_counterparty_binding(commitment_record):
    commitment_record = dict(commitment_record or {})
    institution_id = (commitment_record.get('institution_id') or '').strip()
    source_host_id = (commitment_record.get('source_host_id') or '').strip()
    source_institution_id = (commitment_record.get('source_institution_id') or '').strip()
    target_host_id = (commitment_record.get('target_host_id') or '').strip()
    target_institution_id = (commitment_record.get('target_institution_id') or '').strip()
    if (
        institution_id
        and institution_id == target_institution_id
        and (source_host_id or source_institution_id)
    ):
        return source_host_id, source_institution_id
    return target_host_id, target_institution_id


def ensure_case_for_commitment_breach(commitment_record, actor_id, *, org_id=None, note=''):
    commitment_id = (commitment_record or {}).get('commitment_id', '')
    if not commitment_id:
        raise ValueError('commitment_record.commitment_id is required')
    target_host_id, target_institution_id = _commitment_counterparty_binding(commitment_record)
    for existing in list_cases(org_id):
        if (
            existing.get('claim_type') == 'breach_of_commitment'
            and existing.get('linked_commitment_id') == commitment_id
            and existing.get('status') in BLOCKING_CASE_STATES
        ):
            return existing, False
    return open_case(
        org_id,
        'breach_of_commitment',
        actor_id,
        target_host_id=target_host_id,
        target_institution_id=target_institution_id,
        linked_commitment_id=commitment_id,
        linked_warrant_id=(commitment_record or {}).get('warrant_id', ''),
        note=note,
        metadata={'source': 'commitment_breach'},
    ), True


def ensure_case_for_delivery_failure(claim_type, actor_id, *, org_id=None,
                                     target_host_id='', target_institution_id='',
                                     linked_commitment_id='', linked_warrant_id='',
                                     note='', metadata=None):
    claim_type = (claim_type or '').strip()
    target_host_id = (target_host_id or '').strip()
    target_institution_id = (target_institution_id or '').strip()
    linked_commitment_id = (linked_commitment_id or '').strip()
    linked_warrant_id = (linked_warrant_id or '').strip()
    for existing in blocking_cases(org_id):
        if (
            existing.get('claim_type') == claim_type
            and (existing.get('target_host_id') or '').strip() == target_host_id
            and (existing.get('target_institution_id') or '').strip() == target_institution_id
            and (existing.get('linked_commitment_id') or '').strip() == linked_commitment_id
            and (existing.get('linked_warrant_id') or '').strip() == linked_warrant_id
        ):
            return existing, False
    case_metadata = {'source': 'federation_delivery_failure'}
    case_metadata.update(dict(metadata or {}))
    return open_case(
        org_id,
        claim_type,
        actor_id,
        target_host_id=target_host_id,
        target_institution_id=target_institution_id,
        linked_commitment_id=linked_commitment_id,
        linked_warrant_id=linked_warrant_id,
        note=note,
        metadata=case_metadata,
    ), True
