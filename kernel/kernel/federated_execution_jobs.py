#!/usr/bin/env python3
"""
Capsule-backed receiver-side execution jobs for incoming federation requests.

This store is intentionally narrow:

- jobs are institution-scoped and file-backed
- jobs are keyed idempotently by envelope_id
- receiver-side review materializes local warrant state first, and the
  workspace can later mark a ready job executed and persist settlement refs
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


STORE_FILE = 'federated_execution_jobs.json'
LOCK_FILE = '.federated_execution_jobs.lock'
JOB_STATES = (
    'pending_local_warrant',
    'ready',
    'executed',
    'blocked',
    'rejected',
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


def _store_path(org_id):
    if not (org_id or '').strip():
        raise ValueError('org_id is required')
    return capsule_path(org_id, STORE_FILE)


def _lock_path(org_id):
    if not (org_id or '').strip():
        raise ValueError('org_id is required')
    return capsule_path(org_id, LOCK_FILE)


def _job_id_for_envelope(envelope_id):
    envelope_id = (envelope_id or '').strip()
    if not envelope_id:
        raise ValueError('envelope_id is required')
    return 'fej_' + hashlib.sha256(envelope_id.encode('utf-8')).hexdigest()[:12]


def _empty_store(org_id):
    return {
        'version': 1,
        'updatedAt': _now(),
        'jobs': {},
        'states': list(JOB_STATES),
        '_meta': {
            'service_scope': 'institution_owned_service',
            'bound_org_id': (org_id or '').strip(),
        },
    }


def _normalize_state(state, *, existing_state=''):
    state = (state or '').strip().lower()
    existing_state = (existing_state or '').strip().lower()
    if state and state not in JOB_STATES:
        raise ValueError(f"Unknown execution job state {state!r}. Must be one of {JOB_STATES}")
    if state:
        return state
    return existing_state or 'pending_local_warrant'


def _execution_request_evidence_refs(record):
    record = dict(record or {})
    refs = []
    envelope_id = (record.get('envelope_id') or '').strip()
    if envelope_id:
        refs.append(f'federation_envelope:{envelope_id}')
    receipt_id = (record.get('receipt_id') or '').strip()
    if receipt_id:
        refs.append(f'federation_receipt:{receipt_id}')
    payload_hash = (record.get('payload_hash') or '').strip()
    if payload_hash:
        refs.append(f'payload_hash:{payload_hash}')
    return refs


def _execution_request_snapshot(record):
    record = dict(record or {})
    persisted_request = record.get('request')
    has_persisted_request = isinstance(persisted_request, dict) and bool(persisted_request)
    request = dict(persisted_request or {})
    claims = dict(request.get('claims') or {})
    receipt = dict(request.get('receipt') or {})
    request.setdefault('request_id', (record.get('envelope_id') or record.get('job_id') or '').strip())
    request.setdefault('request_type', (record.get('message_type') or 'execution_request').strip())
    claim_defaults = (
        ('envelope_id', (record.get('envelope_id') or '').strip()),
        ('source_host_id', (record.get('source_host_id') or '').strip()),
        ('source_institution_id', (record.get('source_institution_id') or '').strip()),
        ('target_host_id', (record.get('target_host_id') or '').strip()),
        ('target_institution_id', (record.get('target_institution_id') or '').strip()),
        ('actor_type', (record.get('actor_type') or '').strip()),
        ('actor_id', (record.get('actor_id') or '').strip()),
        ('session_id', (record.get('session_id') or '').strip()),
        ('boundary_name', (record.get('boundary_name') or '').strip()),
        ('identity_model', (record.get('identity_model') or '').strip()),
        ('message_type', (record.get('message_type') or '').strip()),
        ('sender_warrant_id', (record.get('sender_warrant_id') or '').strip()),
        ('commitment_id', (record.get('commitment_id') or '').strip()),
        ('payload_hash', (record.get('payload_hash') or '').strip()),
    )
    if not has_persisted_request:
        claim_defaults += (
            ('local_warrant_id', (record.get('local_warrant_id') or '').strip()),
            ('received_at', (record.get('received_at') or '').strip()),
        )
    for key, value in claim_defaults:
        if value:
            claims.setdefault(key, value)
    receipt_defaults = (
        ('receipt_id', (record.get('receipt_id') or '').strip()),
        ('accepted_at', (record.get('received_at') or '').strip()),
        ('receiver_host_id', (record.get('target_host_id') or '').strip()),
        ('receiver_institution_id', (record.get('target_institution_id') or '').strip()),
    )
    if not has_persisted_request:
        receipt_defaults += (
            ('message_type', (record.get('message_type') or '').strip()),
            ('boundary_name', (record.get('boundary_name') or '').strip()),
            ('identity_model', (record.get('identity_model') or '').strip()),
        )
    for key, value in receipt_defaults:
        if value:
            receipt.setdefault(key, value)
    request['claims'] = claims
    request['receipt'] = receipt
    if 'payload' not in request and 'payload' in record:
        request['payload'] = record.get('payload')
    if not (request.get('payload_hash') or '').strip():
        request['payload_hash'] = (record.get('payload_hash') or '').strip()
    if not request.get('evidence_refs'):
        request['evidence_refs'] = list(_execution_request_evidence_refs(record))
    return request


def _execution_gap_snapshot(record, request=None):
    record = dict(record or {})
    request = dict(request or record.get('request') or {})
    gap = dict(record.get('gap') or {})
    gap['request_id'] = (gap.get('request_id') or request.get('request_id') or record.get('envelope_id') or '').strip()
    gap['request_type'] = (gap.get('request_type') or request.get('request_type') or record.get('message_type') or 'execution_request').strip()
    gap['status'] = (record.get('state') or gap.get('status') or '').strip()
    gap['metadata'] = dict(record.get('metadata') or gap.get('metadata') or {})
    gap['evidence_refs'] = list(gap.get('evidence_refs') or request.get('evidence_refs') or _execution_request_evidence_refs(record))
    return gap


def _normalize_store(data, org_id):
    store = _empty_store(org_id)
    if not isinstance(data, dict):
        return store
    store.update({k: v for k, v in data.items() if k not in ('jobs', '_meta')})
    meta = dict(store.get('_meta', {}))
    meta.update(data.get('_meta', {}) or {})
    meta['bound_org_id'] = (org_id or '').strip()
    store['_meta'] = meta

    raw_jobs = data.get('jobs', {})
    jobs = {}
    if isinstance(raw_jobs, list):
        for item in raw_jobs:
            if isinstance(item, dict) and item.get('job_id'):
                jobs[item['job_id']] = dict(item)
    elif isinstance(raw_jobs, dict):
        for job_id, item in raw_jobs.items():
            if isinstance(item, dict):
                record = dict(item)
                record['job_id'] = record.get('job_id') or job_id
                jobs[record['job_id']] = record
    for job_id, record in list(jobs.items()):
        record = dict(record or {})
        record['request'] = _execution_request_snapshot(record)
        record['gap'] = _execution_gap_snapshot(record, record['request'])
        jobs[job_id] = record
    store['jobs'] = jobs
    if 'states' not in store or not store['states']:
        store['states'] = list(JOB_STATES)
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
        prefix='.federated_execution_jobs.',
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
def _jobs_lock(org_id):
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


def _normalize_job(job, org_id, existing=None):
    job = dict(job or {})
    existing = dict(existing or {})
    envelope_id = (job.get('envelope_id') or existing.get('envelope_id') or '').strip()
    if not envelope_id:
        raise ValueError('envelope_id is required')

    record = dict(existing)
    record['job_id'] = (job.get('job_id') or existing.get('job_id') or _job_id_for_envelope(envelope_id)).strip()
    record['institution_id'] = (org_id or '').strip()
    record['envelope_id'] = envelope_id

    required_fields = (
        'source_host_id',
        'source_institution_id',
        'target_host_id',
        'target_institution_id',
        'boundary_name',
        'identity_model',
        'message_type',
    )
    for field in required_fields:
        if field in job:
            value = str(job.get(field) or '').strip()
            if not value:
                raise ValueError(f'{field} is required')
            record[field] = value
        elif not str(record.get(field) or '').strip():
            raise ValueError(f'{field} is required')

    optional_text_fields = (
        'receipt_id',
        'actor_type',
        'actor_id',
        'session_id',
        'sender_warrant_id',
        'local_warrant_id',
        'commitment_id',
        'payload_hash',
        'received_at',
        'updated_at',
        'executed_at',
        'note',
    )
    for field in optional_text_fields:
        if field in job:
            record[field] = str(job.get(field) or '').strip()
        elif field not in record:
            record[field] = ''

    if 'payload' in job:
        record['payload'] = job.get('payload')
    elif 'payload' not in record:
        record['payload'] = None

    if 'execution_refs' in job:
        record['execution_refs'] = dict(job.get('execution_refs') or {})
    elif 'execution_refs' not in record:
        record['execution_refs'] = {}

    if 'metadata' in job:
        record['metadata'] = dict(job.get('metadata') or {})
    elif 'metadata' not in record:
        record['metadata'] = {}

    if 'request' in job:
        record['request'] = dict(job.get('request') or {})
    elif 'request' not in record:
        record['request'] = {}

    if 'gap' in job:
        record['gap'] = dict(job.get('gap') or {})
    elif 'gap' not in record:
        record['gap'] = {}

    if job.get('payload_hash') in (None, ''):
        record['payload_hash'] = record.get('payload_hash') or _payload_hash(record.get('payload'))

    record['state'] = _normalize_state(job.get('state', ''), existing_state=record.get('state', ''))
    if not record.get('received_at'):
        record['received_at'] = _now()
    record['updated_at'] = _now()
    if record['state'] == 'executed' and not record.get('executed_at'):
        record['executed_at'] = record['updated_at']
    if record['state'] != 'executed' and 'executed_at' not in job:
        record['executed_at'] = record.get('executed_at', '')
    record['request'] = _execution_request_snapshot(record)
    record['gap'] = _execution_gap_snapshot(record, record['request'])
    return record


def get_execution_job(job_or_envelope_id, org_id):
    job_or_envelope_id = (job_or_envelope_id or '').strip()
    if not job_or_envelope_id:
        return None
    store = _load_store(org_id)
    record = store.get('jobs', {}).get(job_or_envelope_id)
    if record:
        return record
    for record in store.get('jobs', {}).values():
        if (record.get('envelope_id') or '').strip() == job_or_envelope_id:
            return record
    return None


def get_execution_job_by_envelope(envelope_id, org_id):
    envelope_id = (envelope_id or '').strip()
    if not envelope_id:
        return None
    store = _load_store(org_id)
    for record in store.get('jobs', {}).values():
        if (record.get('envelope_id') or '').strip() == envelope_id:
            return record
    return None


def get_execution_job_by_local_warrant(local_warrant_id, org_id):
    local_warrant_id = (local_warrant_id or '').strip()
    if not local_warrant_id:
        return None
    store = _load_store(org_id)
    for record in store.get('jobs', {}).values():
        if (record.get('local_warrant_id') or '').strip() == local_warrant_id:
            return record
    return None


def list_execution_jobs(org_id, *, state=None):
    parent = os.path.dirname(_store_path(org_id))
    if org_id and not os.path.isdir(parent):
        return []
    store = _load_store(org_id)
    jobs = list(store.get('jobs', {}).values())
    if state:
        jobs = [row for row in jobs if row.get('state') == state]
    jobs.sort(key=lambda row: row.get('received_at', ''), reverse=True)
    return jobs


def upsert_execution_job(org_id, job=None, **job_fields):
    payload = dict(job or {})
    payload.update(job_fields)
    with _jobs_lock(org_id):
        store = _load_store(org_id)
        existing = None
        if payload.get('job_id'):
            existing = store.get('jobs', {}).get(payload['job_id'])
        if existing is None and payload.get('envelope_id'):
            existing = get_execution_job_by_envelope(payload['envelope_id'], org_id)
        record = _normalize_job(payload, org_id, existing=existing)
        store.setdefault('jobs', {})[record['job_id']] = record
        _save_store(store, org_id)
        return record


def sync_execution_job_for_local_warrant(org_id, local_warrant_id, *, state, note='', metadata=None):
    existing = get_execution_job_by_local_warrant(local_warrant_id, org_id)
    if not existing:
        return None
    merged_metadata = dict(existing.get('metadata') or {})
    merged_metadata.update(metadata or {})
    return upsert_execution_job(
        org_id,
        job_id=existing.get('job_id', ''),
        state=state,
        note=note or existing.get('note', ''),
        metadata=merged_metadata,
    )


def execution_job_summary(org_id):
    parent = os.path.dirname(_store_path(org_id))
    if org_id and not os.path.isdir(parent):
        return {
            'org_id': (org_id or '').strip(),
            'total': 0,
            'pending_local_warrant': 0,
            'ready': 0,
            'executed': 0,
            'blocked': 0,
            'rejected': 0,
            'state_counts': {},
            'message_type_counts': {},
            'updatedAt': _now(),
        }
    store = _load_store(org_id)
    counts = {}
    message_type_counts = {}
    for record in store.get('jobs', {}).values():
        state = (record.get('state') or '').strip()
        if state:
            counts[state] = counts.get(state, 0) + 1
        message_type = (record.get('message_type') or '').strip() or 'unknown'
        message_type_counts[message_type] = message_type_counts.get(message_type, 0) + 1
    summary = {
        'org_id': (org_id or '').strip(),
        'total': len(store.get('jobs', {})),
        'pending_local_warrant': counts.get('pending_local_warrant', 0),
        'ready': counts.get('ready', 0),
        'executed': counts.get('executed', 0),
        'blocked': counts.get('blocked', 0),
        'rejected': counts.get('rejected', 0),
        'state_counts': counts,
        'message_type_counts': dict(sorted(message_type_counts.items())),
        'updatedAt': store.get('updatedAt', _now()),
    }
    return summary


def summarize_execution_jobs(org_id):
    return execution_job_summary(org_id)


def summary(org_id):
    return execution_job_summary(org_id)
