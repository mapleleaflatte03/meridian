#!/usr/bin/env python3
"""Capsule-backed intake queue for the founder-led pilot boundary."""
from __future__ import annotations

import contextlib
import datetime
import fcntl
import json
import os
import tempfile
import uuid


PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(PLATFORM_DIR))
CAPSULES_DIR = os.path.join(WORKSPACE, 'economy', 'capsules')

try:
    from capsule import capsule_path, resolve_org_id
except ImportError:
    def resolve_org_id(org_id=None):
        return org_id

    def capsule_path(org_id, filename):
        resolved_org_id = resolve_org_id(org_id)
        if not resolved_org_id:
            raise ValueError('org_id is required')
        return os.path.join(CAPSULES_DIR, resolved_org_id, filename)


STORE_FILE = 'pilot_intake.json'
LOCK_FILE = '.pilot_intake.lock'
REQUEST_STATES = ('requested', 'reviewed', 'contacted', 'closed')


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _store_path(org_id):
    resolved_org_id = resolve_org_id(org_id)
    if not resolved_org_id:
        raise ValueError('org_id is required')
    return capsule_path(resolved_org_id, STORE_FILE)


def _lock_path(org_id):
    resolved_org_id = resolve_org_id(org_id)
    if not resolved_org_id:
        raise ValueError('org_id is required')
    return capsule_path(resolved_org_id, LOCK_FILE)


def _empty_store(org_id):
    return {
        'version': 1,
        'updatedAt': _now(),
        'requests': {},
        'states': list(REQUEST_STATES),
        '_meta': {
            'service_scope': 'pilot_intake',
            'bound_org_id': resolve_org_id(org_id) or '',
            'boundary_name': 'pilot_intake',
            'identity_model': 'public_submission',
            'storage_model': 'capsule_canonical',
            'offer_scope': 'founder_led_pilot_with_public_paid_checkout',
        },
    }


def _normalize_csv(values):
    if values in (None, ''):
        return []
    if isinstance(values, list):
        raw_items = values
    else:
        raw_items = str(values).split(',')
    return [str(item).strip() for item in raw_items if str(item).strip()]


def _normalize_state(state, *, existing_state=''):
    state = (state or '').strip().lower()
    existing_state = (existing_state or '').strip().lower()
    if state and state not in REQUEST_STATES:
        raise ValueError(f"Unknown pilot intake state {state!r}. Must be one of {REQUEST_STATES}")
    if state:
        return state
    return existing_state or 'requested'


def _normalize_request(request, org_id, existing=None):
    request = dict(request or {})
    existing = dict(existing or {})
    resolved_org_id = resolve_org_id(org_id) or ''
    request_id = (request.get('request_id') or existing.get('request_id') or '').strip()
    if not request_id:
        request_id = 'pir_' + uuid.uuid4().hex[:12]

    record = dict(existing)
    record['request_id'] = request_id
    record['org_id'] = resolved_org_id

    for field in ('name', 'company'):
        if field in request:
            value = str(request.get(field) or '').strip()
            if not value:
                raise ValueError(f'{field} is required')
            record[field] = value
        elif not str(record.get(field) or '').strip():
            raise ValueError(f'{field} is required')

    if 'email' in request:
        record['email'] = str(request.get('email') or '').strip()
    elif 'email' not in record:
        record['email'] = ''

    if 'telegram_handle' in request:
        record['telegram_handle'] = str(request.get('telegram_handle') or '').strip()
    elif 'telegram_handle' not in record:
        record['telegram_handle'] = ''

    if not record.get('email') and not record.get('telegram_handle'):
        raise ValueError('email or telegram_handle is required')

    optional_text_fields = (
        'requested_cadence',
        'notes',
        'source_page',
        'requested_offer',
        'contact_channel',
        'reviewed_by',
        'review_note',
        'submitted_by',
    )
    for field in optional_text_fields:
        if field in request:
            record[field] = str(request.get(field) or '').strip()
        elif field not in record:
            record[field] = ''

    if 'competitors' in request:
        record['competitors'] = _normalize_csv(request.get('competitors'))
    elif 'competitors' not in record:
        record['competitors'] = []

    if 'topics' in request:
        record['topics'] = _normalize_csv(request.get('topics'))
    elif 'topics' not in record:
        record['topics'] = []

    if 'status' in request:
        record['status'] = _normalize_state(request.get('status'), existing_state=record.get('status', ''))
    else:
        record['status'] = _normalize_state(record.get('status', ''), existing_state=record.get('status', ''))

    if not record.get('created_at'):
        record['created_at'] = _now()
    record['updated_at'] = _now()
    if not record.get('source_page'):
        record['source_page'] = 'pilot.html'
    if not record.get('requested_offer'):
        record['requested_offer'] = 'manual_pilot'
    if not record.get('contact_channel'):
        record['contact_channel'] = 'email' if record.get('email') else 'telegram'
    if record['status'] in ('reviewed', 'contacted', 'closed') and not record.get('reviewed_at'):
        record['reviewed_at'] = record['updated_at']
    elif 'reviewed_at' not in record:
        record['reviewed_at'] = ''

    record['preview'] = {
        'requested_offer': record['requested_offer'],
        'contact_channel': record['contact_channel'],
        'competitor_count': len(record.get('competitors', [])),
        'topic_count': len(record.get('topics', [])),
        'has_notes': bool(record.get('notes')),
    }
    return record


def _request_view(request):
    request = dict(request or {})
    review_state = 'acknowledged' if request.get('reviewed_at') else 'pending_review'
    request['review_state'] = review_state
    request['review_metadata'] = {
        'review_state': review_state,
        'reviewed_by': request.get('reviewed_by', ''),
        'reviewed_at': request.get('reviewed_at', ''),
        'review_note': request.get('review_note', ''),
    }
    request['operator_acknowledged'] = review_state == 'acknowledged'
    return request


def _normalize_store(data, org_id):
    store = _empty_store(org_id)
    if not isinstance(data, dict):
        return store
    store.update({k: v for k, v in data.items() if k not in ('requests', '_meta')})
    meta = dict(store.get('_meta', {}))
    meta.update(data.get('_meta', {}) or {})
    meta['bound_org_id'] = resolve_org_id(org_id) or meta.get('bound_org_id', '')
    store['_meta'] = meta

    raw_requests = data.get('requests', {})
    requests = {}
    if isinstance(raw_requests, list):
        for item in raw_requests:
            if isinstance(item, dict):
                request_id = (item.get('request_id') or '').strip()
                if request_id:
                    requests[request_id] = dict(item)
    elif isinstance(raw_requests, dict):
        for request_id, item in raw_requests.items():
            if isinstance(item, dict):
                record = dict(item)
                record['request_id'] = record.get('request_id') or request_id
                requests[record['request_id']] = record
    store['requests'] = requests
    if 'states' not in store or not store['states']:
        store['states'] = list(REQUEST_STATES)
    return store


def _load_store(org_id):
    path = _store_path(org_id)
    if os.path.exists(path):
        with open(path) as f:
            return _normalize_store(json.load(f), org_id)
    return _empty_store(org_id)


def _save_store(store, org_id):
    path = _store_path(org_id)
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    payload = _normalize_store(store, org_id)
    payload['updatedAt'] = _now()
    fd, tmp_path = tempfile.mkstemp(
        prefix='.pilot_intake.',
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
def _store_lock(org_id):
    path = _lock_path(org_id)
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    with open(path, 'a+') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _sorted_requests(requests):
    return sorted(
        requests,
        key=lambda request: (
            request.get('created_at', ''),
            request.get('updated_at', ''),
            request.get('request_id', ''),
        ),
        reverse=True,
    )


def _queue_summary(requests, org_id):
    status_counts = {state: 0 for state in REQUEST_STATES}
    acknowledged_count = 0
    for request in requests:
        status = request.get('status', 'requested')
        status_counts[status] = status_counts.get(status, 0) + 1
        if request.get('reviewed_at'):
            acknowledged_count += 1
    return {
        'bound_org_id': resolve_org_id(org_id) or '',
        'total_requests': len(requests),
        'requested_count': status_counts.get('requested', 0),
        'reviewed_count': status_counts.get('reviewed', 0),
        'contacted_count': status_counts.get('contacted', 0),
        'closed_count': status_counts.get('closed', 0),
        'reviewable_count': status_counts.get('requested', 0),
        'acknowledged_count': acknowledged_count,
        'contactable_count': len([
            request for request in requests
            if request.get('email') or request.get('telegram_handle')
        ]),
        'latest_request_at': requests[0].get('created_at', '') if requests else '',
        'status_counts': status_counts,
    }


def load_pilot_requests(org_id=None):
    store = _load_store(org_id)
    requests = [
        _normalize_request(request, org_id, existing=request)
        for request in store.get('requests', {}).values()
    ]
    return _sorted_requests(requests)


def submit_pilot_request(
    name,
    company,
    *,
    email='',
    telegram_handle='',
    requested_cadence='',
    competitors=None,
    topics=None,
    notes='',
    source_page='pilot.html',
    requested_offer='manual_pilot',
    org_id=None,
    submitted_by='public:intake',
):
    request = {
        'name': name,
        'company': company,
        'email': email,
        'telegram_handle': telegram_handle,
        'requested_cadence': requested_cadence,
        'competitors': competitors or [],
        'topics': topics or [],
        'notes': notes,
        'source_page': source_page,
        'requested_offer': requested_offer,
        'submitted_by': submitted_by,
        'status': 'requested',
    }
    with _store_lock(org_id):
        store = _load_store(org_id)
        record = _normalize_request(request, org_id)
        store['requests'][record['request_id']] = record
        payload = _save_store(store, org_id)
    requests = _sorted_requests([
        _normalize_request(item, org_id, existing=item)
        for item in payload.get('requests', {}).values()
    ])
    return {
        'request': record,
        'summary': _queue_summary(requests, org_id),
    }


def queue_snapshot(org_id=None, *, limit=50):
    requests = [_request_view(request) for request in load_pilot_requests(org_id)]
    try:
        limit = max(int(limit), 0)
    except (TypeError, ValueError):
        limit = 50
    limited_requests = requests[:limit] if limit else []
    return {
        'bound_org_id': resolve_org_id(org_id) or '',
        'management_mode': 'pilot_intake_with_public_checkout_preview',
        'mutation_enabled': True,
        'mutation_disabled_reason': '',
        'service_scope': 'pilot_intake',
        'boundary_name': 'pilot_intake',
        'identity_model': 'public_submission',
        'storage_model': 'capsule_canonical',
        'checkout_preview_publication_enabled': True,
        'request_paths': {
            'submit': '/api/pilot/intake',
            'inspect': '/api/pilot/intake',
            'operator_inspect': '/api/pilot/intake/operator',
            'operator_review': '/api/pilot/intake/operator/review',
        },
        'summary': _queue_summary(requests, org_id),
        'requests': limited_requests,
        'meta': _empty_store(org_id)['_meta'],
    }


def operator_review_snapshot(org_id=None, *, limit=50):
    snapshot = queue_snapshot(org_id, limit=limit)
    snapshot['management_mode'] = 'manual_operator_review'
    snapshot['operator_review'] = {
        'review_mode': 'manual_ack_only',
        'inspect_path': '/api/pilot/intake/operator',
        'review_path': '/api/pilot/intake/operator/review',
        'fulfillment_claimed': False,
        'fulfillment_note': 'operator review only; public paid checkout can publish a preview without claiming manual fulfillment',
        'acknowledged_count': snapshot['summary'].get('acknowledged_count', 0),
        'reviewed_count': snapshot['summary'].get('reviewed_count', 0),
        'reviewable_count': snapshot['summary'].get('reviewable_count', 0),
    }
    return snapshot


def acknowledge_pilot_request(request_id, by, *, org_id=None, note=''):
    request_id = (request_id or '').strip()
    by = (by or '').strip()
    if not request_id:
        raise ValueError('request_id is required')
    if not by:
        raise ValueError('by is required')
    with _store_lock(org_id):
        store = _load_store(org_id)
        record = store.get('requests', {}).get(request_id)
        if not record:
            raise ValueError(f'Pilot intake request not found: {request_id}')
        updated = dict(record)
        if (updated.get('status') or '').strip() == 'requested':
            updated['status'] = 'reviewed'
        timestamp = _now()
        updated['reviewed_by'] = by
        updated['review_note'] = (note or '').strip()
        updated['reviewed_at'] = timestamp
        updated['updated_at'] = timestamp
        store['requests'][request_id] = _normalize_request(updated, org_id, existing=updated)
        payload = _save_store(store, org_id)
    requests = _sorted_requests([
        _normalize_request(item, org_id, existing=item)
        for item in payload.get('requests', {}).values()
    ])
    return {
        'request': _request_view(store['requests'][request_id]),
        'summary': _queue_summary(requests, org_id),
    }
