#!/usr/bin/env python3
"""
Witness-host archival store for independently re-validated federation evidence.

Live mirrors this contract so the workspace can surface the witness archive
shape honestly, even when the host itself is not configured as a witness host.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _empty_store(host_id=''):
    return {
        'host_id': (host_id or '').strip(),
        'records': {},
        'updated_at': _now(),
    }


def load_witness_archive(file_path, *, host_id=''):
    host_id = (host_id or '').strip()
    if not file_path or not os.path.exists(file_path):
        return _empty_store(host_id)
    with open(file_path) as f:
        data = json.load(f)
    if host_id and data.get('host_id') and data.get('host_id') != host_id:
        raise RuntimeError(
            f"Witness archive host_id '{data.get('host_id', '')}' does not match runtime host '{host_id}'"
        )
    data.setdefault('host_id', host_id)
    data.setdefault('records', {})
    data.setdefault('updated_at', _now())
    return data


def _save_witness_archive(file_path, data, *, host_id=''):
    payload = dict(data or {})
    payload['host_id'] = (host_id or payload.get('host_id') or '').strip()
    payload['updated_at'] = _now()
    payload.setdefault('records', {})
    parent = os.path.dirname(file_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(file_path, 'w') as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    return payload


def _archive_id(claims, receipt):
    material = ':'.join((
        str((claims or {}).get('envelope_id') or '').strip(),
        str((receipt or {}).get('receipt_id') or '').strip(),
        str((claims or {}).get('source_host_id') or '').strip(),
        str((claims or {}).get('target_host_id') or '').strip(),
    ))
    return 'witobs_' + hashlib.sha256(material.encode('utf-8')).hexdigest()[:12]


def list_witness_observations(file_path, *, host_id=''):
    store = load_witness_archive(file_path, host_id=host_id)
    rows = list(store.get('records', {}).values())
    rows.sort(
        key=lambda row: (
            row.get('observed_at', ''),
            row.get('archive_id', ''),
        ),
        reverse=True,
    )
    return rows


def witness_archive_summary(file_path, *, host_id=''):
    rows = list_witness_observations(file_path, host_id=host_id)
    message_type_counts = {}
    peer_host_ids = set()
    for row in rows:
        message_type = (row.get('message_type') or '').strip()
        if message_type:
            message_type_counts[message_type] = message_type_counts.get(message_type, 0) + 1
        for key in ('source_host_id', 'target_host_id'):
            value = (row.get(key) or '').strip()
            if value:
                peer_host_ids.add(value)
    return {
        'total': len(rows),
        'message_type_counts': message_type_counts,
        'peer_host_ids': sorted(peer_host_ids),
        'latest_observed_at': rows[0].get('observed_at', '') if rows else '',
    }


def archive_witness_observation(
    file_path,
    *,
    host_id,
    bound_org_id='',
    actor_id='',
    claims=None,
    receipt=None,
    payload=None,
    source_manifest=None,
    target_manifest=None,
):
    claims = dict(claims or {})
    receipt = dict(receipt or {})
    payload = payload if isinstance(payload, dict) else {}
    source_manifest = dict(source_manifest or {})
    target_manifest = dict(target_manifest or {})
    archive_id = _archive_id(claims, receipt)
    store = load_witness_archive(file_path, host_id=host_id)
    existing = store.get('records', {}).get(archive_id)
    if existing:
        return dict(existing), False
    record = {
        'archive_id': archive_id,
        'observer_host_id': (host_id or '').strip(),
        'observer_institution_id': (bound_org_id or '').strip(),
        'observed_by': (actor_id or '').strip(),
        'observed_at': _now(),
        'message_type': (claims.get('message_type') or '').strip(),
        'boundary_name': (claims.get('boundary_name') or '').strip(),
        'identity_model': (claims.get('identity_model') or '').strip(),
        'envelope_id': (claims.get('envelope_id') or '').strip(),
        'receipt_id': (receipt.get('receipt_id') or '').strip(),
        'payload_hash': (claims.get('payload_hash') or '').strip(),
        'warrant_id': (claims.get('warrant_id') or '').strip(),
        'commitment_id': (claims.get('commitment_id') or '').strip(),
        'source_host_id': (claims.get('source_host_id') or '').strip(),
        'source_institution_id': (claims.get('source_institution_id') or '').strip(),
        'target_host_id': (claims.get('target_host_id') or '').strip(),
        'target_institution_id': (claims.get('target_institution_id') or '').strip(),
        'claims': claims,
        'receipt': receipt,
        'payload': payload,
        'source_manifest': source_manifest,
        'target_manifest': target_manifest,
        'validation': {
            'source_manifest_validated': bool(source_manifest),
            'target_manifest_validated': bool(target_manifest),
            'receipt_validated': bool(receipt),
        },
    }
    store.setdefault('records', {})[archive_id] = record
    _save_witness_archive(file_path, store, host_id=host_id)
    return dict(record), True
