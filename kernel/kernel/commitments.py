#!/usr/bin/env python3
"""
Cross-institution commitment primitives for Meridian Kernel.

This is the first first-class commitment object. It does not yet claim the
entire inter-institution commitments program. It does establish:

- institution-scoped, capsule-backed commitment records
- explicit target host / target institution binding
- workspace APIs to propose and review commitments
- optional sender-side federation validation when `commitment_id` is supplied
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


COMMITMENT_STATES = (
    'proposed',
    'accepted',
    'rejected',
    'breached',
    'settled',
)


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


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
    return capsule_path(org_id, 'commitments.json')


def _empty_store():
    return {
        'commitments': {},
        'updatedAt': _now(),
        'states': list(COMMITMENT_STATES),
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


def _normalize_target_institution_id(*, target_org_id='', target_institution_id=''):
    return (target_institution_id or target_org_id or '').strip()


def _canonical_state(record):
    return (record.get('status') or record.get('state') or '').strip()


def _settlement_ref_keys(ref):
    return [
        (field, value)
        for field in ('envelope_id', 'receipt_id', 'tx_hash', 'proposal_id', 'tx_ref')
        for value in [str((ref or {}).get(field) or '').strip()]
        if value
    ]


def _settlement_ref_matches(existing_ref, candidate_ref):
    existing_keys = _settlement_ref_keys(existing_ref)
    candidate_keys = _settlement_ref_keys(candidate_ref)
    for candidate_field, candidate_value in candidate_keys:
        for existing_field, existing_value in existing_keys:
            if candidate_field == existing_field and candidate_value == existing_value:
                return True
    return False


def _propose_commitment_record(org_id, target_host_id, target_institution_id, summary,
                               actor_id, *, commitment_id=None, terms_payload=None,
                               warrant_id='', note='', metadata=None,
                               source_host_id='', source_institution_id=''):
    target_host_id = (target_host_id or '').strip()
    target_institution_id = _normalize_target_institution_id(
        target_institution_id=target_institution_id,
    )
    summary = (summary or '').strip()
    actor_id = (actor_id or '').strip()
    if not target_host_id:
        raise ValueError('target_host_id is required')
    if not target_institution_id:
        raise ValueError('target_institution_id is required')
    if not summary:
        raise ValueError('summary is required')
    if not actor_id:
        raise ValueError('actor_id is required')

    timestamp = _now()
    commitment_id = (commitment_id or '').strip() or f'cmt_{uuid.uuid4().hex[:12]}'
    record = {
        'commitment_id': commitment_id,
        'institution_id': org_id,
        'source_institution_id': (source_institution_id or org_id or '').strip(),
        'source_host_id': (source_host_id or '').strip(),
        'target_host_id': target_host_id,
        'target_institution_id': target_institution_id,
        'commitment_type': summary,
        'summary': summary,
        'terms_hash': _payload_hash(terms_payload),
        'terms_payload': terms_payload if terms_payload is not None else {},
        'warrant_id': (warrant_id or '').strip(),
        'state': 'proposed',
        'status': 'proposed',
        'proposed_by': actor_id,
        'proposed_at': timestamp,
        'updated_at': timestamp,
        'reviewed_by': '',
        'reviewed_at': '',
        'review_note': '',
        'accepted_by': '',
        'accepted_at': '',
        'rejected_by': '',
        'rejected_at': '',
        'breached_by': '',
        'settled_by': '',
        'delivery_refs': [],
        'settlement_refs': [],
        'last_delivery_at': '',
        'last_settlement_at': '',
        'breached_at': '',
        'settled_at': '',
        'note': note or '',
        'metadata': dict(metadata or {}),
    }
    store = _load_store(org_id)
    store.setdefault('commitments', {})[commitment_id] = record
    _save_store(store, org_id)
    return record


def propose_commitment(*args, **kwargs):
    if len(args) >= 5:
        org_id, target_host_id, target_org_id, summary, actor_id = args[:5]
        return _propose_commitment_record(
            org_id,
            target_host_id,
            _normalize_target_institution_id(
                target_org_id=target_org_id,
                target_institution_id=kwargs.get('target_institution_id', ''),
            ),
            summary,
            actor_id,
            commitment_id=kwargs.get('commitment_id'),
            terms_payload=kwargs.get('terms_payload'),
            warrant_id=kwargs.get('warrant_id', ''),
            note=kwargs.get('note', ''),
            metadata=kwargs.get('metadata'),
            source_host_id=kwargs.get('source_host_id', ''),
            source_institution_id=kwargs.get('source_institution_id', ''),
        )
    if len(args) >= 3:
        target_host_id, target_org_id, summary = args[:3]
        org_id = kwargs.get('org_id')
        if not org_id:
            raise ValueError('org_id is required')
        return _propose_commitment_record(
            org_id,
            target_host_id,
            _normalize_target_institution_id(
                target_org_id=target_org_id,
                target_institution_id=kwargs.get('target_institution_id', ''),
            ),
            summary,
            kwargs.get('proposed_by') or kwargs.get('actor_id') or 'owner',
            commitment_id=kwargs.get('commitment_id'),
            terms_payload=kwargs.get('terms_payload'),
            warrant_id=kwargs.get('warrant_id', ''),
            note=kwargs.get('note', ''),
            metadata=kwargs.get('metadata'),
            source_host_id=kwargs.get('source_host_id', ''),
            source_institution_id=kwargs.get('source_institution_id', ''),
        )
    raise TypeError('Unsupported propose_commitment call signature')


def list_commitments(org_id=None, *, state=None):
    store = _load_store(org_id)
    commitments = list(store.get('commitments', {}).values())
    if state:
        commitments = [row for row in commitments if _canonical_state(row) == state]
    commitments.sort(key=lambda row: row.get('proposed_at', ''), reverse=True)
    return commitments


def get_commitment(commitment_id, org_id=None):
    if not commitment_id:
        return None
    store = _load_store(org_id)
    return store.get('commitments', {}).get(commitment_id)


def review_commitment(commitment_id, decision, by, *, org_id=None, note=''):
    decision = (decision or '').strip()
    state_map = {
        'accept': 'accepted',
        'reject': 'rejected',
        'breach': 'breached',
        'settle': 'settled',
    }
    if decision not in state_map:
        raise ValueError(f'Unsupported commitment decision: {decision}')
    store = _load_store(org_id)
    record = store.get('commitments', {}).get(commitment_id)
    if not record:
        raise ValueError(f'Commitment not found: {commitment_id}')
    state = state_map[decision]
    timestamp = _now()
    record['state'] = state
    record['status'] = state
    record['reviewed_by'] = (by or '').strip()
    record['reviewed_at'] = timestamp
    record['review_note'] = note or ''
    record['updated_at'] = timestamp
    if state == 'accepted':
        record['accepted_by'] = record['reviewed_by']
        record['accepted_at'] = timestamp
    if state == 'rejected':
        record['rejected_by'] = record['reviewed_by']
        record['rejected_at'] = timestamp
    if state == 'breached':
        record['breached_by'] = record['reviewed_by']
        record['breached_at'] = timestamp
    if state == 'settled':
        record['settled_by'] = record['reviewed_by']
        record['settled_at'] = timestamp
    _save_store(store, org_id)
    return record


def accept_commitment(commitment_id, by, *, org_id=None, note=''):
    return review_commitment(commitment_id, 'accept', by, org_id=org_id, note=note)


def reject_commitment(commitment_id, by, *, org_id=None, note=''):
    return review_commitment(commitment_id, 'reject', by, org_id=org_id, note=note)


def breach_commitment(commitment_id, by, *, org_id=None, note=''):
    return review_commitment(commitment_id, 'breach', by, org_id=org_id, note=note)


def settle_commitment(commitment_id, by, *, org_id=None, note=''):
    return review_commitment(commitment_id, 'settle', by, org_id=org_id, note=note)


def validate_commitment_for_federation(commitment_id, *, org_id=None,
                                       target_host_id='', target_org_id='',
                                       warrant_id=''):
    record = get_commitment(commitment_id, org_id=org_id)
    if not record:
        raise PermissionError(f"Commitment '{commitment_id}' does not exist")
    if _canonical_state(record) != 'accepted':
        raise PermissionError(
            f"Commitment '{commitment_id}' is not active for federation "
            f"(state={_canonical_state(record)})"
        )
    if target_host_id and record.get('target_host_id') != target_host_id:
        raise PermissionError(
            f"Commitment '{commitment_id}' target_host_id "
            f"{record.get('target_host_id', '')!r} does not match {target_host_id!r}"
        )
    if target_org_id and record.get('target_institution_id') != target_org_id:
        raise PermissionError(
            f"Commitment '{commitment_id}' target_institution_id "
            f"{record.get('target_institution_id', '')!r} does not match {target_org_id!r}"
        )
    if warrant_id and record.get('warrant_id') and record.get('warrant_id') != warrant_id:
        raise PermissionError(
            f"Commitment '{commitment_id}' warrant_id "
            f"{record.get('warrant_id', '')!r} does not match {warrant_id!r}"
        )
    return record


def validate_commitment_for_delivery(commitment_id, *, target_host_id='',
                                     target_institution_id='', org_id=None,
                                     warrant_id=''):
    try:
        return validate_commitment_for_federation(
            commitment_id,
            org_id=org_id,
            target_host_id=target_host_id,
            target_org_id=target_institution_id,
            warrant_id=warrant_id,
        )
    except PermissionError as exc:
        raise ValueError(str(exc))


def validate_commitment_for_proposal_dispatch(commitment_id, *, org_id=None,
                                              target_host_id='', target_institution_id='',
                                              warrant_id=''):
    record = get_commitment(commitment_id, org_id=org_id)
    if not record:
        raise PermissionError(f"Commitment '{commitment_id}' does not exist")
    if _canonical_state(record) != 'proposed':
        raise PermissionError(
            f"Commitment '{commitment_id}' is not ready for proposal dispatch "
            f"(state={_canonical_state(record)})"
        )
    if target_host_id and record.get('target_host_id') != target_host_id:
        raise PermissionError(
            f"Commitment '{commitment_id}' target_host_id "
            f"{record.get('target_host_id', '')!r} does not match {target_host_id!r}"
        )
    if target_institution_id and record.get('target_institution_id') != target_institution_id:
        raise PermissionError(
            f"Commitment '{commitment_id}' target_institution_id "
            f"{record.get('target_institution_id', '')!r} does not match {target_institution_id!r}"
        )
    if warrant_id and record.get('warrant_id') and record.get('warrant_id') != warrant_id:
        raise PermissionError(
            f"Commitment '{commitment_id}' warrant_id "
            f"{record.get('warrant_id', '')!r} does not match {warrant_id!r}"
        )
    return record


def validate_commitment_for_acceptance_dispatch(commitment_id, *, org_id=None,
                                                target_host_id='', target_institution_id='',
                                                warrant_id=''):
    record = get_commitment(commitment_id, org_id=org_id)
    if not record:
        raise PermissionError(f"Commitment '{commitment_id}' does not exist")
    if _canonical_state(record) != 'accepted':
        raise PermissionError(
            f"Commitment '{commitment_id}' is not ready for acceptance dispatch "
            f"(state={_canonical_state(record)})"
        )
    if target_host_id and (record.get('source_host_id') or '') != target_host_id:
        raise PermissionError(
            f"Commitment '{commitment_id}' source_host_id "
            f"{record.get('source_host_id', '')!r} does not match {target_host_id!r}"
        )
    if target_institution_id and (record.get('source_institution_id') or '') != target_institution_id:
        raise PermissionError(
            f"Commitment '{commitment_id}' source_institution_id "
            f"{record.get('source_institution_id', '')!r} does not match {target_institution_id!r}"
        )
    return record


def validate_commitment_for_breach_notice(commitment_id, *, org_id=None,
                                          target_host_id='', target_institution_id='',
                                          warrant_id=''):
    del warrant_id  # breach notices require their own warrant and do not reuse proposal warrant binding
    record = get_commitment(commitment_id, org_id=org_id)
    if not record:
        raise PermissionError(f"Commitment '{commitment_id}' does not exist")
    if _canonical_state(record) != 'breached':
        raise PermissionError(
            f"Commitment '{commitment_id}' is not ready for breach notice "
            f"(state={_canonical_state(record)})"
        )
    if target_host_id and (record.get('source_host_id') or '') != target_host_id:
        raise PermissionError(
            f"Commitment '{commitment_id}' source_host_id "
            f"{record.get('source_host_id', '')!r} does not match {target_host_id!r}"
        )
    if target_institution_id and (record.get('source_institution_id') or '') != target_institution_id:
        raise PermissionError(
            f"Commitment '{commitment_id}' source_institution_id "
            f"{record.get('source_institution_id', '')!r} does not match {target_institution_id!r}"
        )
    return record


def sync_federated_commitment_proposal(org_id, commitment_id, *, source_host_id='',
                                       source_institution_id='', target_host_id='',
                                       target_institution_id='', summary='',
                                       actor_id='', terms_payload=None,
                                       warrant_id='', note='', metadata=None):
    commitment_id = (commitment_id or '').strip()
    if not commitment_id:
        raise ValueError('commitment_id is required')
    existing = get_commitment(commitment_id, org_id=org_id)
    if existing:
        if (existing.get('source_host_id') or '').strip() != (source_host_id or '').strip():
            raise ValueError(
                f"Commitment '{commitment_id}' source_host_id "
                f"{existing.get('source_host_id', '')!r} does not match {(source_host_id or '').strip()!r}"
            )
        if (existing.get('source_institution_id') or '').strip() != (source_institution_id or '').strip():
            raise ValueError(
                f"Commitment '{commitment_id}' source_institution_id "
                f"{existing.get('source_institution_id', '')!r} does not match {(source_institution_id or '').strip()!r}"
            )
        if (existing.get('target_host_id') or '').strip() != (target_host_id or '').strip():
            raise ValueError(
                f"Commitment '{commitment_id}' target_host_id "
                f"{existing.get('target_host_id', '')!r} does not match {(target_host_id or '').strip()!r}"
            )
        if (existing.get('target_institution_id') or '').strip() != (target_institution_id or '').strip():
            raise ValueError(
                f"Commitment '{commitment_id}' target_institution_id "
                f"{existing.get('target_institution_id', '')!r} does not match {(target_institution_id or '').strip()!r}"
            )
        return existing, False
    return propose_commitment(
        org_id,
        target_host_id,
        target_institution_id,
        summary,
        actor_id,
        commitment_id=commitment_id,
        terms_payload=terms_payload,
        warrant_id=warrant_id,
        note=note,
        metadata=metadata,
        source_host_id=source_host_id,
        source_institution_id=source_institution_id,
    ), True


def validate_commitment_for_settlement(commitment_id, *, org_id=None, warrant_id=''):
    record = get_commitment(commitment_id, org_id=org_id)
    if not record:
        raise PermissionError(f"Commitment '{commitment_id}' does not exist")
    if _canonical_state(record) not in ('accepted', 'settled'):
        raise PermissionError(
            f"Commitment '{commitment_id}' is not ready for settlement "
            f"(state={_canonical_state(record)})"
        )
    if warrant_id and record.get('warrant_id') and record.get('warrant_id') != warrant_id:
        raise PermissionError(
            f"Commitment '{commitment_id}' warrant_id "
            f"{record.get('warrant_id', '')!r} does not match {warrant_id!r}"
        )
    return record


def mark_commitment_delivery(commitment_id, *, org_id=None, delivery_ref=None):
    store = _load_store(org_id)
    record = store.get('commitments', {}).get(commitment_id)
    if not record:
        raise ValueError(f'Commitment not found: {commitment_id}')
    ref = dict(delivery_ref or {})
    ref.setdefault('recorded_at', _now())
    refs = list(record.get('delivery_refs', []))
    refs.append(ref)
    record['delivery_refs'] = refs
    record['last_delivery_at'] = ref['recorded_at']
    record['updated_at'] = ref['recorded_at']
    _save_store(store, org_id)
    return record


def record_delivery_ref(commitment_id, delivery_ref, *, org_id=None):
    return mark_commitment_delivery(
        commitment_id,
        org_id=org_id,
        delivery_ref=delivery_ref,
    )


def mark_commitment_settlement(commitment_id, *, org_id=None, settlement_ref=None):
    store = _load_store(org_id)
    record = store.get('commitments', {}).get(commitment_id)
    if not record:
        raise ValueError(f'Commitment not found: {commitment_id}')
    ref = dict(settlement_ref or {})
    ref.setdefault('recorded_at', _now())
    refs = list(record.get('settlement_refs', []))
    replaced = False
    if _settlement_ref_keys(ref):
        for index, existing in enumerate(refs):
            if _settlement_ref_matches(existing, ref):
                refs[index] = ref
                replaced = True
                break
    if not replaced:
        refs.append(ref)
    record['settlement_refs'] = refs
    record['last_settlement_at'] = ref['recorded_at']
    record['updated_at'] = ref['recorded_at']
    _save_store(store, org_id)
    return record


def record_settlement_ref(commitment_id, settlement_ref, *, org_id=None):
    return mark_commitment_settlement(
        commitment_id,
        org_id=org_id,
        settlement_ref=settlement_ref,
    )


def commitment_summary(org_id=None):
    commitments = list_commitments(org_id)
    summary = {
        'total': len(commitments),
        'proposed': 0,
        'accepted': 0,
        'rejected': 0,
        'breached': 0,
        'settled': 0,
        'delivery_refs_total': 0,
        'settlement_refs_total': 0,
    }
    for record in commitments:
        state = _canonical_state(record)
        if state in summary:
            summary[state] += 1
        summary['delivery_refs_total'] += len(record.get('delivery_refs', []))
        summary['settlement_refs_total'] += len(record.get('settlement_refs', []))
    return summary


def main():
    parser = argparse.ArgumentParser(description='Commitment management')
    sub = parser.add_subparsers(dest='command')

    propose = sub.add_parser('propose')
    propose.add_argument('--org_id', required=True)
    propose.add_argument('--target_host_id', required=True)
    propose.add_argument('--target_org_id', required=True)
    propose.add_argument('--commitment_type', required=True)
    propose.add_argument('--actor_id', required=True)
    propose.add_argument('--warrant_id', default='')

    show = sub.add_parser('show')
    show.add_argument('--org_id', required=True)

    review = sub.add_parser('review')
    review.add_argument('--org_id', required=True)
    review.add_argument('--commitment_id', required=True)
    review.add_argument('--decision', required=True)
    review.add_argument('--by', required=True)

    args = parser.parse_args()
    if args.command == 'propose':
        print(json.dumps(propose_commitment(
            args.org_id,
            args.target_host_id,
            args.target_org_id,
            args.commitment_type,
            args.actor_id,
            warrant_id=args.warrant_id,
        ), indent=2))
    elif args.command == 'show':
        print(json.dumps({'commitments': list_commitments(args.org_id)}, indent=2))
    elif args.command == 'review':
        print(json.dumps(review_commitment(
            args.commitment_id,
            args.decision,
            args.by,
            org_id=args.org_id,
        ), indent=2))
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
