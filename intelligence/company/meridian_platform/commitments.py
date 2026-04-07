#!/usr/bin/env python3
"""
Founding-service commitment primitives for live Meridian.

This mirrors the kernel-side first-class commitment object, but does not claim
that live already supports broad multi-institution execution. It does ensure
that when live code references `commitment_id`, it resolves to a real
capsule-backed record rather than an inert field.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import uuid

from capsule import capsule_path


COMMITMENT_STATES = (
    'proposed',
    'accepted',
    'rejected',
    'breached',
    'settled',
)

FEDERATED_COMMITMENT_MESSAGE_STATES = {
    'commitment_proposal': 'proposed',
    'commitment_acceptance': 'accepted',
    'commitment_breach_notice': 'breached',
}

COMMITMENT_STATE_RANK = {
    'proposed': 0,
    'accepted': 1,
    'rejected': 2,
    'breached': 3,
    'settled': 4,
}


def _default_org_id():
    return 'org_48b05c21'


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


def _normalize_target_institution_id(*, target_org_id='', target_institution_id=''):
    return (target_institution_id or target_org_id or '').strip()


def _canonical_state(record):
    return (record.get('status') or record.get('state') or '').strip()


def _settlement_ref_keys(ref):
    return [
        (field, value)
        for field in ('envelope_id', 'receipt_id', 'proposal_id', 'tx_ref', 'tx_hash')
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


def _federation_ref_keys(ref):
    return [
        (field, value)
        for field in (
            'envelope_id',
            'receipt_id',
            'proposal_id',
            'tx_ref',
            'tx_hash',
        )
        for value in [str((ref or {}).get(field) or '').strip()]
        if value
    ]


def _federation_ref_matches(existing_ref, candidate_ref):
    existing_keys = _federation_ref_keys(existing_ref)
    candidate_keys = _federation_ref_keys(candidate_ref)
    for candidate_field, candidate_value in candidate_keys:
        for existing_field, existing_value in existing_keys:
            if candidate_field == existing_field and candidate_value == existing_value:
                return True
    return False


def _commitment_state_rank(state):
    return COMMITMENT_STATE_RANK.get((state or '').strip(), -1)


def _store_path(org_id=None):
    return capsule_path(org_id or _default_org_id(), 'commitments.json')


def _empty_store():
    return {
        'commitments': {},
        'updatedAt': _now(),
        'states': list(COMMITMENT_STATES),
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


def _propose_commitment_record(org_id, target_host_id, target_org_id, commitment_type,
                               actor_id, *, commitment_id=None, terms_payload=None,
                               warrant_id='', note='', metadata=None):
    target_host_id = (target_host_id or '').strip()
    target_org_id = _normalize_target_institution_id(target_org_id=target_org_id)
    commitment_type = (commitment_type or '').strip()
    actor_id = (actor_id or '').strip()
    if not target_host_id:
        raise ValueError('target_host_id is required')
    if not target_org_id:
        raise ValueError('target_org_id is required')
    if not commitment_type:
        raise ValueError('commitment_type is required')
    if not actor_id:
        raise ValueError('actor_id is required')

    timestamp = _now()
    commitment_id = (commitment_id or '').strip() or f'cmt_{uuid.uuid4().hex[:12]}'
    record = {
        'commitment_id': commitment_id,
        'institution_id': org_id,
        'source_institution_id': org_id,
        'target_host_id': target_host_id,
        'target_institution_id': target_org_id,
        'commitment_type': commitment_type,
        'summary': commitment_type,
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
        'federation_refs': [],
        'last_delivery_at': '',
        'last_settlement_at': '',
        'last_federation_at': '',
        'mirror_origin': '',
        'federation_message_type': '',
        'mirrored_from_envelope_id': '',
        'mirrored_from_receipt_id': '',
        'mirrored_from_host_id': '',
        'mirrored_from_institution_id': '',
        'mirrored_to_host_id': '',
        'mirrored_to_institution_id': '',
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
        org_id, target_host_id, target_org_id, commitment_type, actor_id = args[:5]
        return _propose_commitment_record(
            org_id or _default_org_id(),
            target_host_id,
            _normalize_target_institution_id(
                target_org_id=target_org_id,
                target_institution_id=kwargs.get('target_institution_id', ''),
            ),
            commitment_type,
            actor_id,
            terms_payload=kwargs.get('terms_payload'),
            warrant_id=kwargs.get('warrant_id', ''),
            note=kwargs.get('note', ''),
            commitment_id=kwargs.get('commitment_id'),
            metadata=kwargs.get('metadata'),
        )
    if len(args) >= 3:
        target_host_id, target_org_id, summary = args[:3]
        return _propose_commitment_record(
            kwargs.get('org_id') or _default_org_id(),
            target_host_id,
            _normalize_target_institution_id(
                target_org_id=target_org_id,
                target_institution_id=kwargs.get('target_institution_id', ''),
            ),
            summary,
            kwargs.get('proposed_by') or kwargs.get('actor_id') or 'owner',
            terms_payload=kwargs.get('terms_payload'),
            warrant_id=kwargs.get('warrant_id', ''),
            note=kwargs.get('note', ''),
            commitment_id=kwargs.get('commitment_id'),
            metadata=kwargs.get('metadata'),
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
    record['state'] = state
    record['status'] = state
    timestamp = _now()
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


def mirror_federated_commitment(commitment_id, *, org_id=None, message_type='',
                                source_host_id='', source_institution_id='',
                                target_host_id='', target_institution_id='',
                                actor_id='', warrant_id='', envelope_id='',
                                receipt_id='', payload=None, note='',
                                metadata=None):
    message_type = (message_type or '').strip()
    if message_type not in FEDERATED_COMMITMENT_MESSAGE_STATES:
        raise ValueError(
            f'Unsupported federated commitment message_type: {message_type}'
        )
    commitment_id = (commitment_id or '').strip()
    if not commitment_id:
        raise ValueError('commitment_id is required')
    source_host_id = (source_host_id or '').strip()
    source_institution_id = (source_institution_id or '').strip()
    target_host_id = (target_host_id or '').strip()
    target_institution_id = _normalize_target_institution_id(
        target_org_id=target_institution_id,
    )
    actor_id = (actor_id or '').strip() or f'peer:{source_host_id}'
    warrant_id = (warrant_id or '').strip()
    envelope_id = (envelope_id or '').strip()
    receipt_id = (receipt_id or '').strip()
    payload = dict(payload or {})
    commitment_type = (
        (payload.get('commitment_type') or '').strip()
        or (payload.get('summary') or '').strip()
        or message_type
    )
    summary = (
        (payload.get('summary') or '').strip()
        or commitment_type
    )
    timestamp = _now()
    metadata = dict(metadata or {})
    if source_host_id:
        metadata.setdefault('source_host_id', source_host_id)
    if source_institution_id:
        metadata.setdefault('source_institution_id', source_institution_id)
    if target_host_id:
        metadata.setdefault('target_host_id', target_host_id)
    if target_institution_id:
        metadata.setdefault('target_institution_id', target_institution_id)
    metadata.setdefault('federation_message_type', message_type)
    metadata.setdefault('mirror_origin', 'federation')
    store = _load_store(org_id)
    record = store.setdefault('commitments', {}).get(commitment_id)
    if not record:
        record = _propose_commitment_record(
            org_id or _default_org_id(),
            target_host_id or source_host_id or '',
            target_institution_id or source_institution_id or (org_id or _default_org_id()),
            commitment_type,
            actor_id,
            commitment_id=commitment_id,
            terms_payload=payload.get('terms_payload') or payload.get('terms') or payload,
            warrant_id=warrant_id,
            note=note or f'Federated {message_type}',
            metadata=metadata,
        )
        store = _load_store(org_id)
        record = store.setdefault('commitments', {}).get(commitment_id)
    if not record:
        raise ValueError(f'Commitment not found: {commitment_id}')

    record['mirror_origin'] = 'federation'
    record['federation_message_type'] = message_type
    record['mirrored_from_envelope_id'] = envelope_id
    record['mirrored_from_receipt_id'] = receipt_id
    record['mirrored_from_host_id'] = source_host_id
    record['mirrored_from_institution_id'] = source_institution_id
    record['mirrored_to_host_id'] = target_host_id
    record['mirrored_to_institution_id'] = target_institution_id
    record['commitment_type'] = commitment_type
    record['summary'] = summary
    if source_institution_id:
        record['source_institution_id'] = source_institution_id
    if target_host_id:
        record['target_host_id'] = target_host_id
    if target_institution_id:
        record['target_institution_id'] = target_institution_id
    if warrant_id:
        record['warrant_id'] = warrant_id
    record['metadata'] = dict(record.get('metadata') or {})
    record['metadata'].update(metadata)

    federation_ref = {
        'commitment_id': commitment_id,
        'message_type': message_type,
        'envelope_id': envelope_id,
        'receipt_id': receipt_id,
        'source_host_id': source_host_id,
        'source_institution_id': source_institution_id,
        'target_host_id': target_host_id,
        'target_institution_id': target_institution_id,
        'warrant_id': warrant_id,
        'recorded_by': actor_id,
        'recorded_at': timestamp,
        'payload_hash': _payload_hash(payload),
    }
    refs = list(record.get('federation_refs', []))
    replaced = False
    if _federation_ref_keys(federation_ref):
        for index, existing in enumerate(refs):
            if _federation_ref_matches(existing, federation_ref):
                refs[index] = federation_ref
                replaced = True
                break
    if not replaced:
        refs.append(federation_ref)
    record['federation_refs'] = refs
    record['last_federation_at'] = timestamp
    record['updated_at'] = timestamp

    state = FEDERATED_COMMITMENT_MESSAGE_STATES[message_type]
    current_state = _canonical_state(record)
    if _commitment_state_rank(state) >= _commitment_state_rank(current_state):
        record['state'] = state
        record['status'] = state
        if state == 'proposed':
            record['proposed_by'] = actor_id
            record['proposed_at'] = timestamp
        elif state == 'accepted':
            record['reviewed_by'] = actor_id
            record['reviewed_at'] = timestamp
            record['accepted_by'] = actor_id
            record['accepted_at'] = timestamp
        elif state == 'breached':
            record['reviewed_by'] = actor_id
            record['reviewed_at'] = timestamp
            record['breached_by'] = actor_id
            record['breached_at'] = timestamp

    _save_store(store, org_id)
    return record


def validate_commitment_for_federation(commitment_id, *, org_id=None,
                                       target_host_id='', target_org_id='',
                                       warrant_id=''):
    record = next(
        (item for item in list_commitments(org_id) if item.get('commitment_id') == commitment_id),
        None,
    )
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


def validate_commitment_for_breach_notice(commitment_id, *, org_id=None,
                                          target_host_id='',
                                          target_institution_id='',
                                          warrant_id=''):
    del warrant_id  # breach notices carry a fresh warrant; do not couple to proposal warrant
    record = get_commitment(commitment_id, org_id=org_id)
    if not record:
        raise PermissionError(f"Commitment '{commitment_id}' does not exist")
    if _canonical_state(record) != 'breached':
        raise PermissionError(
            f"Commitment '{commitment_id}' is not ready for breach notice "
            f"(state={_canonical_state(record)})"
        )
    if target_host_id and record.get('source_host_id') != target_host_id:
        raise PermissionError(
            f"Commitment '{commitment_id}' source_host_id "
            f"{record.get('source_host_id', '')!r} does not match {target_host_id!r}"
        )
    if target_institution_id and record.get('source_institution_id') != target_institution_id:
        raise PermissionError(
            f"Commitment '{commitment_id}' source_institution_id "
            f"{record.get('source_institution_id', '')!r} does not match {target_institution_id!r}"
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
    records = list_commitments(org_id)
    summary = {
        'total': len(records),
        'proposed': 0,
        'accepted': 0,
        'rejected': 0,
        'breached': 0,
        'settled': 0,
        'delivery_refs_total': 0,
        'settlement_refs_total': 0,
    }
    for record in records:
        state = _canonical_state(record)
        if state in summary:
            summary[state] += 1
        summary['delivery_refs_total'] += len(record.get('delivery_refs', []))
        summary['settlement_refs_total'] += len(record.get('settlement_refs', []))
    return summary
