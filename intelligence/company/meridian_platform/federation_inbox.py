#!/usr/bin/env python3
"""
Capsule-backed inbox for received federation messages on live.

The live host is still founding-only by default, but any accepted federation
message should still have an institution-scoped persistence path instead of
existing only in audit logs.
"""
from __future__ import annotations

import collections
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import sys
import tempfile


PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(PLATFORM_DIR))
ECONOMY_DIR = os.path.join(WORKSPACE, 'economy')

if PLATFORM_DIR not in sys.path:
    sys.path.insert(0, PLATFORM_DIR)

try:
    from capsule import capsule_path
except ImportError:
    def capsule_path(org_id, filename):
        return os.path.join(ECONOMY_DIR, filename)


INBOX_FILE = 'federation_inbox.json'
LOCK_FILE = '.federation_inbox.lock'
ENTRY_STATES = (
    'received',
    'processed',
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
        f"ERROR: institution '{org_id}' is not initialized. Bootstrap the founding capsule first."
    )


def _store_path(org_id):
    if not (org_id or '').strip():
        raise ValueError('org_id is required')
    return capsule_path(org_id, INBOX_FILE)


def _lock_path(org_id):
    if not (org_id or '').strip():
        raise ValueError('org_id is required')
    return capsule_path(org_id, LOCK_FILE)


def _empty_store(org_id):
    return {
        'version': 1,
        'updatedAt': _now(),
        'entries': {},
        'states': list(ENTRY_STATES),
        '_meta': {
            'service_scope': 'founding_meridian_service',
            'bound_org_id': (org_id or '').strip(),
        },
    }


def _normalize_state(state, *, existing_state=''):
    state = (state or '').strip().lower()
    existing_state = (existing_state or '').strip().lower()
    if state and state not in ENTRY_STATES:
        raise ValueError(f"Unknown inbox state {state!r}. Must be one of {ENTRY_STATES}")
    if existing_state == 'processed' or state == 'processed':
        return 'processed'
    if state:
        return state
    return existing_state or 'received'


def _normalize_store(data, org_id):
    store = _empty_store(org_id)
    if not isinstance(data, dict):
        return store
    store.update({k: v for k, v in data.items() if k not in ('entries', '_meta')})
    meta = dict(store.get('_meta', {}))
    meta.update(data.get('_meta', {}) or {})
    meta['bound_org_id'] = (org_id or '').strip()
    store['_meta'] = meta

    raw_entries = data.get('entries', {})
    entries = {}
    if isinstance(raw_entries, list):
        for item in raw_entries:
            if isinstance(item, dict) and item.get('envelope_id'):
                entries[item['envelope_id']] = dict(item)
    elif isinstance(raw_entries, dict):
        for envelope_id, item in raw_entries.items():
            if isinstance(item, dict):
                record = dict(item)
                record['envelope_id'] = record.get('envelope_id') or envelope_id
                entries[record['envelope_id']] = record
    store['entries'] = entries
    if 'states' not in store or not store['states']:
        store['states'] = list(ENTRY_STATES)
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
        prefix='.federation_inbox.',
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
def _inbox_lock(org_id):
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


def _normalize_entry(entry, existing=None):
    entry = dict(entry or {})
    existing = dict(existing or {})
    envelope_id = (entry.get('envelope_id') or existing.get('envelope_id') or '').strip()
    if not envelope_id:
        raise ValueError('envelope_id is required')

    record = dict(existing)
    record['envelope_id'] = envelope_id

    required_fields = (
        'source_host_id',
        'source_institution_id',
        'target_host_id',
        'target_institution_id',
        'message_type',
    )
    for field in required_fields:
        if field in entry:
            value = (entry.get(field) or '').strip()
            if not value:
                raise ValueError(f'{field} is required')
            record[field] = value
        elif field not in record or not record.get(field):
            raise ValueError(f'{field} is required')

    optional_text_fields = (
        'warrant_id',
        'commitment_id',
        'receipt_id',
        'accepted_at',
        'received_at',
        'processed_at',
    )
    for field in optional_text_fields:
        if field in entry:
            record[field] = (entry.get(field) or '').strip()
        elif field not in record:
            record[field] = ''

    if 'state' in entry:
        record['state'] = _normalize_state(entry.get('state'), existing_state=record.get('state', ''))
    else:
        record['state'] = _normalize_state(record.get('state', ''), existing_state=record.get('state', ''))

    if 'payload' in entry:
        record['payload'] = entry.get('payload')
    elif 'payload' not in record:
        record['payload'] = None

    if 'payload_hash' in entry:
        supplied = entry.get('payload_hash')
        record['payload_hash'] = supplied.strip() if supplied else _payload_hash(record.get('payload'))
    elif 'payload_hash' not in record:
        record['payload_hash'] = _payload_hash(record.get('payload'))

    if not record.get('accepted_at'):
        record['accepted_at'] = _now()
    if not record.get('received_at'):
        record['received_at'] = record['accepted_at']
    if record['state'] == 'processed' and not record.get('processed_at'):
        record['processed_at'] = record['accepted_at']
    if record['state'] != 'processed':
        record.setdefault('processed_at', '')

    return record


def load_inbox_entries(org_id):
    try:
        parent = os.path.dirname(_store_path(org_id))
    except ValueError:
        store = _empty_store(org_id)
        parent = ''
    else:
        if org_id and not os.path.isdir(parent):
            store = _empty_store(org_id)
        else:
            with _inbox_lock(org_id):
                store = _load_store(org_id)
    entries = list(store.get('entries', {}).values())
    entries.sort(
        key=lambda row: (
            row.get('accepted_at', ''),
            row.get('received_at', ''),
            row.get('envelope_id', ''),
        ),
        reverse=True,
    )
    return entries


def upsert_inbox_entry(org_id, entry=None, **fields):
    if entry is None:
        entry = fields
    elif fields:
        merged = dict(entry)
        merged.update(fields)
        entry = merged
    else:
        entry = dict(entry)

    if not (org_id or '').strip():
        raise ValueError('org_id is required')

    with _inbox_lock(org_id):
        store = _load_store(org_id)
        envelope_id = (entry.get('envelope_id') or '').strip()
        existing = store.get('entries', {}).get(envelope_id)
        record = _normalize_entry(entry, existing=existing)
        if existing and existing.get('state') == 'processed' and record.get('state') != 'processed':
            record['state'] = 'processed'
            record['processed_at'] = (
                existing.get('processed_at')
                or record.get('processed_at')
                or record['accepted_at']
            )
        if record['state'] == 'processed' and not record.get('processed_at'):
            record['processed_at'] = record['accepted_at']
        store.setdefault('entries', {})[record['envelope_id']] = record
        _save_store(store, org_id)
    return record


append_inbox_entry = upsert_inbox_entry


def summarize_inbox_entries(org_id):
    try:
        parent = os.path.dirname(_store_path(org_id))
    except ValueError:
        store = _empty_store(org_id)
    else:
        if org_id and not os.path.isdir(parent):
            store = _empty_store(org_id)
        else:
            with _inbox_lock(org_id):
                store = _load_store(org_id)
    entries = list(store.get('entries', {}).values())
    message_type_counts = collections.Counter()
    state_counts = collections.Counter()
    for entry in entries:
        message_type_counts[entry.get('message_type', '')] += 1
        state_counts[entry.get('state', 'received')] += 1
    message_type_counts.pop('', None)
    state_counts.pop('', None)
    return {
        'org_id': (org_id or '').strip(),
        'total': len(entries),
        'received': state_counts.get('received', 0),
        'processed': state_counts.get('processed', 0),
        'state_counts': dict(state_counts),
        'message_type_counts': dict(message_type_counts),
        'updatedAt': store.get('updatedAt', ''),
    }


def load_inbox(org_id):
    return load_inbox_entries(org_id)


def summarize_inbox(org_id):
    return summarize_inbox_entries(org_id)
