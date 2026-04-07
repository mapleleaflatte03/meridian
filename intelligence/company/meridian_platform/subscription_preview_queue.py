#!/usr/bin/env python3
"""Capsule-backed preview queue for subscription continuation offers.

This queue is intentionally narrow:

- it records review-time continuation previews for the founding workspace
- it exposes published plan pricing and durations only
- it does not create subscriptions, capture payment, or claim checkout
- it preserves a durable inspection trail that can follow pilot intake review
"""
from __future__ import annotations

import contextlib
import datetime
import fcntl
import json
import os
import tempfile
import uuid

import subscription_service


PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(PLATFORM_DIR))

STORE_FILE = 'subscription_preview_queue.json'
LOCK_FILE = '.subscription_preview_queue.lock'
QUEUE_STATES = (
    'previewed',
    'reviewed',
    'dismissed',
    'superseded',
)


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _store_path(org_id):
    if not (org_id or '').strip():
        raise ValueError('org_id is required')
    from capsule import capsule_path
    return capsule_path(org_id, STORE_FILE)


def _lock_path(org_id):
    if not (org_id or '').strip():
        raise ValueError('org_id is required')
    from capsule import capsule_path
    return capsule_path(org_id, LOCK_FILE)


def _empty_store(org_id):
    return {
        'version': 1,
        'updatedAt': _now(),
        'subscription_previews': {},
        'states': list(QUEUE_STATES),
        '_meta': {
            'service_scope': 'institution_owned_subscription_preview_queue',
            'bound_org_id': (org_id or '').strip(),
            'boundary_name': 'subscription_preview_queue',
            'identity_model': 'public_submission_or_operator_review',
            'storage_model': 'capsule_canonical',
            'truth_boundary': 'published_plan_table_only',
        },
    }


def _normalize_state(state, *, existing_state=''):
    state = (state or '').strip().lower()
    existing_state = (existing_state or '').strip().lower()
    if state and state not in QUEUE_STATES:
        raise ValueError(f"Unknown subscription preview state {state!r}. Must be one of {QUEUE_STATES}")
    return state or existing_state or 'previewed'


def _plan_options(requested_offer=''):
    requested_offer = (requested_offer or '').strip()
    restricted_plan = ''
    if requested_offer == subscription_service.PUBLIC_CHECKOUT_PLAN:
        restricted_plan = subscription_service.PUBLIC_CHECKOUT_PLAN
    options = []
    for plan_name in sorted(subscription_service.PLANS.keys()):
        if plan_name == 'trial':
            continue
        if restricted_plan and plan_name != restricted_plan:
            continue
        plan = subscription_service.PLANS[plan_name]
        options.append({
            'plan': plan_name,
            'price_usd': float(plan['price_usd']),
            'duration_days': int(plan['duration_days']),
            'billing_type': plan['type'],
        })
    return options


def _normalize_preview(preview, org_id, existing=None):
    preview = dict(preview or {})
    existing = dict(existing or {})
    preview_id = (preview.get('preview_id') or existing.get('preview_id') or '').strip()
    if not preview_id:
        preview_id = f"spv_{uuid.uuid4().hex[:12]}"

    record = dict(existing)
    record['preview_id'] = preview_id
    record['org_id'] = (org_id or '').strip()
    record['pilot_request_id'] = (
        preview.get('pilot_request_id')
        or preview.get('request_id')
        or existing.get('pilot_request_id')
        or ''
    ).strip()
    record['name'] = (preview.get('name') or existing.get('name') or '').strip()
    record['company'] = (preview.get('company') or existing.get('company') or '').strip()
    record['email'] = (preview.get('email') or existing.get('email') or '').strip()
    record['telegram_handle'] = (preview.get('telegram_handle') or existing.get('telegram_handle') or '').strip()
    record['requested_cadence'] = (preview.get('requested_cadence') or existing.get('requested_cadence') or '').strip()
    record['requested_offer'] = (preview.get('requested_offer') or existing.get('requested_offer') or 'manual_pilot').strip()
    record['reviewed_by'] = (preview.get('reviewed_by') or existing.get('reviewed_by') or '').strip()
    record['review_note'] = (preview.get('review_note') or existing.get('review_note') or '').strip()
    record['reviewed_at'] = (preview.get('reviewed_at') or existing.get('reviewed_at') or '').strip()
    record['created_by'] = (preview.get('created_by') or existing.get('created_by') or '').strip()
    record['billing_model'] = (preview.get('billing_model') or existing.get('billing_model') or 'manual_continuation_only').strip()
    record['preview_truth_source'] = (
        preview.get('preview_truth_source')
        or existing.get('preview_truth_source')
        or 'pilot_intake_review_and_published_plan_table_only'
    ).strip()
    record['draft_subscription_id'] = (preview.get('draft_subscription_id') or existing.get('draft_subscription_id') or '').strip()
    record['drafted_at'] = (preview.get('drafted_at') or existing.get('drafted_at') or '').strip()
    record['drafted_by'] = (preview.get('drafted_by') or existing.get('drafted_by') or '').strip()
    record['draft_state'] = (preview.get('draft_state') or existing.get('draft_state') or '').strip()
    record['activated_subscription_id'] = (preview.get('activated_subscription_id') or existing.get('activated_subscription_id') or '').strip()
    record['activated_at'] = (preview.get('activated_at') or existing.get('activated_at') or '').strip()
    record['activated_by'] = (preview.get('activated_by') or existing.get('activated_by') or '').strip()
    record['activation_state'] = (preview.get('activation_state') or existing.get('activation_state') or '').strip()
    record['delivery_run_id'] = (preview.get('delivery_run_id') or existing.get('delivery_run_id') or '').strip()
    record['delivery_ref'] = (preview.get('delivery_ref') or existing.get('delivery_ref') or '').strip()
    record['delivered_at'] = (preview.get('delivered_at') or existing.get('delivered_at') or '').strip()
    record['delivered_by'] = (preview.get('delivered_by') or existing.get('delivered_by') or '').strip()
    record['delivery_state'] = (preview.get('delivery_state') or existing.get('delivery_state') or '').strip()
    record['state'] = _normalize_state(
        preview.get('state') or preview.get('preview_state') or '',
        existing_state=existing.get('state') or existing.get('preview_state') or '',
    )
    record['preview_state'] = record['state']
    record['checkout_claimed'] = bool(preview.get('checkout_claimed', existing.get('checkout_claimed', False)))
    record['payment_capture_claimed'] = bool(preview.get('payment_capture_claimed', existing.get('payment_capture_claimed', False)))
    record['fulfillment_claimed'] = bool(preview.get('fulfillment_claimed', existing.get('fulfillment_claimed', False)))
    record['plan_options'] = list(preview.get('plan_options') or existing.get('plan_options') or _plan_options())
    record['created_at'] = (preview.get('created_at') or existing.get('created_at') or _now()).strip()
    record['updated_at'] = _now()
    return record


def _normalize_store(data, org_id):
    store = _empty_store(org_id)
    if not isinstance(data, dict):
        return store
    store.update({k: v for k, v in data.items() if k not in ('subscription_previews', '_meta')})
    meta = dict(store.get('_meta', {}))
    meta.update(data.get('_meta', {}) or {})
    meta['bound_org_id'] = (org_id or '').strip()
    store['_meta'] = meta

    raw_previews = data.get('subscription_previews', {})
    previews = {}
    if isinstance(raw_previews, list):
        for item in raw_previews:
            if isinstance(item, dict):
                preview_id = (item.get('preview_id') or '').strip()
                if preview_id:
                    previews[preview_id] = dict(item)
    elif isinstance(raw_previews, dict):
        for preview_id, item in raw_previews.items():
            if isinstance(item, dict):
                record = dict(item)
                record['preview_id'] = record.get('preview_id') or preview_id
                previews[record['preview_id']] = record

    for preview_id, record in list(previews.items()):
        previews[preview_id] = _normalize_preview(record, org_id, existing=record)
    store['subscription_previews'] = previews
    if 'states' not in store or not store['states']:
        store['states'] = list(QUEUE_STATES)
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
        prefix='.subscription_preview_queue.',
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
def _preview_lock(org_id):
    path = _lock_path(org_id)
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    with open(path, 'a+') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _sorted_previews(previews):
    return sorted(
        previews,
        key=lambda preview: (
            preview.get('created_at', ''),
            preview.get('updated_at', ''),
            preview.get('preview_id', ''),
        ),
        reverse=True,
    )


def _queue_summary(previews, org_id):
    state_counts = {state: 0 for state in QUEUE_STATES}
    checkout_claimed_count = 0
    drafted_count = 0
    activated_count = 0
    delivered_count = 0
    for preview in previews:
        state = preview.get('state', 'previewed')
        state_counts[state] = state_counts.get(state, 0) + 1
        if preview.get('checkout_claimed'):
            checkout_claimed_count += 1
        if preview.get('draft_subscription_id'):
            drafted_count += 1
        if preview.get('activated_subscription_id'):
            activated_count += 1
        if preview.get('delivery_ref'):
            delivered_count += 1
    return {
        'bound_org_id': (org_id or '').strip(),
        'total_previews': len(previews),
        'previewed_count': state_counts.get('previewed', 0),
        'reviewed_count': state_counts.get('reviewed', 0),
        'dismissed_count': state_counts.get('dismissed', 0),
        'superseded_count': state_counts.get('superseded', 0),
        'drafted_count': drafted_count,
        'activated_count': activated_count,
        'delivered_count': delivered_count,
        'checkout_claimed_count': checkout_claimed_count,
        'latest_preview_at': previews[0].get('created_at', '') if previews else '',
        'state_counts': state_counts,
    }


def load_subscription_previews(org_id=None):
    store = _load_store(org_id)
    previews = [
        _normalize_preview(preview, org_id, existing=preview)
        for preview in store.get('subscription_previews', {}).values()
    ]
    return _sorted_previews(previews)


def get_subscription_preview(preview_id, org_id=None):
    preview_id = (preview_id or '').strip()
    if not preview_id:
        raise ValueError('preview_id is required')
    store = _load_store(org_id)
    preview = store.get('subscription_previews', {}).get(preview_id)
    if not preview:
        raise LookupError(f'Subscription preview not found: {preview_id}')
    return _normalize_preview(preview, org_id, existing=preview)


def preview_from_pilot_request(request, *, org_id=None, by='', note='', billing_model='', preview_truth_source=''):
    request = dict(request or {})
    request_id = (request.get('request_id') or '').strip()
    if not request_id:
        raise ValueError('request_id is required')
    requested_offer = (request.get('requested_offer') or 'manual_pilot').strip()
    is_public_checkout_offer = requested_offer == subscription_service.PUBLIC_CHECKOUT_PLAN
    default_billing_model = 'customer_initiated_checkout_capture' if is_public_checkout_offer else 'manual_continuation_only'
    default_truth_source = (
        'public_intake_and_published_plan_table_only'
        if is_public_checkout_offer
        else 'pilot_intake_review_and_published_plan_table_only'
    )
    review_state = 'reviewed' if (request.get('reviewed_at') or request.get('reviewed_by')) else 'previewed'

    preview = {
        'preview_id': f'quote_{request_id}',
        'pilot_request_id': request_id,
        'name': request.get('name', ''),
        'company': request.get('company', ''),
        'email': request.get('email', ''),
        'telegram_handle': request.get('telegram_handle', ''),
        'requested_cadence': request.get('requested_cadence', ''),
        'requested_offer': requested_offer,
        'reviewed_by': (request.get('reviewed_by') or by or '').strip(),
        'review_note': (request.get('review_note') or note or '').strip(),
        'reviewed_at': request.get('reviewed_at', ''),
        'created_by': (by or request.get('submitted_by') or '').strip(),
        'billing_model': (billing_model or default_billing_model).strip(),
        'preview_truth_source': (preview_truth_source or default_truth_source).strip(),
        'state': review_state,
        'checkout_claimed': False,
        'payment_capture_claimed': False,
        'fulfillment_claimed': False,
        'plan_options': _plan_options(requested_offer),
    }
    if request.get('competitors') is not None:
        preview['competitors'] = list(request.get('competitors') or [])
    if request.get('topics') is not None:
        preview['topics'] = list(request.get('topics') or [])
    return preview


def queue_subscription_preview(request, *, org_id=None, by='', note='', billing_model='', preview_truth_source=''):
    preview = preview_from_pilot_request(
        request,
        org_id=org_id,
        by=by,
        note=note,
        billing_model=billing_model,
        preview_truth_source=preview_truth_source,
    )
    with _preview_lock(org_id):
        store = _load_store(org_id)
        existing = store.get('subscription_previews', {}).get(preview['preview_id'])
        if existing:
            preview['created_at'] = existing.get('created_at', preview.get('created_at', _now()))
        store.setdefault('subscription_previews', {})[preview['preview_id']] = _normalize_preview(
            preview,
            org_id,
            existing=existing or {},
        )
        payload = _save_store(store, org_id)
    previews = _sorted_previews([
        _normalize_preview(item, org_id, existing=item)
        for item in payload.get('subscription_previews', {}).values()
    ])
    return {
        'preview': previews[0] if previews and previews[0]['preview_id'] == preview['preview_id'] else store['subscription_previews'][preview['preview_id']],
        'summary': _queue_summary(previews, org_id),
    }


def mark_preview_drafted(preview_id, draft_subscription_id, *, org_id=None, by=''):
    preview_id = (preview_id or '').strip()
    draft_subscription_id = (draft_subscription_id or '').strip()
    if not preview_id:
        raise ValueError('preview_id is required')
    if not draft_subscription_id:
        raise ValueError('draft_subscription_id is required')

    with _preview_lock(org_id):
        store = _load_store(org_id)
        existing = store.get('subscription_previews', {}).get(preview_id)
        if not existing:
            raise LookupError(f'Subscription preview not found: {preview_id}')
        updated = dict(existing)
        timestamp = _now()
        updated['draft_subscription_id'] = draft_subscription_id
        updated['drafted_at'] = timestamp
        updated['drafted_by'] = (by or '').strip()
        updated['draft_state'] = 'draft_created'
        updated['updated_at'] = timestamp
        store.setdefault('subscription_previews', {})[preview_id] = _normalize_preview(
            updated,
            org_id,
            existing=updated,
        )
        payload = _save_store(store, org_id)
    previews = _sorted_previews([
        _normalize_preview(item, org_id, existing=item)
        for item in payload.get('subscription_previews', {}).values()
    ])
    return {
        'preview': store['subscription_previews'][preview_id],
        'summary': _queue_summary(previews, org_id),
    }


def mark_preview_activated(
    preview_id,
    subscription_id,
    *,
    org_id=None,
    by='',
    state='captured',
    checkout_claimed=False,
    payment_capture_claimed=False,
):
    preview_id = (preview_id or '').strip()
    subscription_id = (subscription_id or '').strip()
    if not preview_id:
        raise ValueError('preview_id is required')
    if not subscription_id:
        raise ValueError('subscription_id is required')

    with _preview_lock(org_id):
        store = _load_store(org_id)
        existing = store.get('subscription_previews', {}).get(preview_id)
        if not existing:
            raise LookupError(f'Subscription preview not found: {preview_id}')
        updated = dict(existing)
        timestamp = _now()
        updated['activated_subscription_id'] = subscription_id
        updated['activated_at'] = timestamp
        updated['activated_by'] = (by or '').strip()
        updated['activation_state'] = (state or 'captured').strip() or 'captured'
        updated['payment_capture_claimed'] = bool(payment_capture_claimed)
        updated['checkout_claimed'] = bool(checkout_claimed)
        updated['updated_at'] = timestamp
        store.setdefault('subscription_previews', {})[preview_id] = _normalize_preview(
            updated,
            org_id,
            existing=updated,
        )
        payload = _save_store(store, org_id)
    previews = _sorted_previews([
        _normalize_preview(item, org_id, existing=item)
        for item in payload.get('subscription_previews', {}).values()
    ])
    return {
        'preview': store['subscription_previews'][preview_id],
        'summary': _queue_summary(previews, org_id),
    }


def mark_preview_delivered(preview_id, delivery_ref, *, org_id=None, by='', delivery_run_id=''):
    preview_id = (preview_id or '').strip()
    delivery_ref = (delivery_ref or '').strip()
    if not preview_id:
        raise ValueError('preview_id is required')
    if not delivery_ref:
        raise ValueError('delivery_ref is required')

    with _preview_lock(org_id):
        store = _load_store(org_id)
        existing = store.get('subscription_previews', {}).get(preview_id)
        if not existing:
            raise LookupError(f'Subscription preview not found: {preview_id}')
        updated = dict(existing)
        timestamp = _now()
        updated['delivery_ref'] = delivery_ref
        updated['delivery_run_id'] = (delivery_run_id or '').strip()
        updated['delivered_at'] = timestamp
        updated['delivered_by'] = (by or '').strip()
        updated['delivery_state'] = 'delivered'
        updated['fulfillment_claimed'] = True
        updated['updated_at'] = timestamp
        store.setdefault('subscription_previews', {})[preview_id] = _normalize_preview(
            updated,
            org_id,
            existing=updated,
        )
        payload = _save_store(store, org_id)
    previews = _sorted_previews([
        _normalize_preview(item, org_id, existing=item)
        for item in payload.get('subscription_previews', {}).values()
    ])
    return {
        'preview': store['subscription_previews'][preview_id],
        'summary': _queue_summary(previews, org_id),
    }


def subscription_preview_queue_snapshot(org_id=None, *, limit=50):
    previews = load_subscription_previews(org_id)
    try:
        limit = max(int(limit), 0)
    except (TypeError, ValueError):
        limit = 50
    limited_previews = previews[:limit] if limit else []
    return {
        'bound_org_id': (org_id or '').strip(),
        'management_mode': 'subscription_preview_queue',
        'mutation_enabled': True,
        'mutation_disabled_reason': '',
        'service_scope': 'institution_owned_subscription_preview_queue',
        'boundary_name': 'subscription_preview_queue',
        'identity_model': 'public_submission_or_operator_review',
        'storage_model': 'capsule_canonical',
        'queue_paths': {
            'public_intake': '/api/pilot/intake',
            'inspect': '/api/subscriptions/preview-queue',
            'source_review': '/api/pilot/intake/operator/review',
            'checkout_capture': '/api/subscriptions/checkout-capture',
        },
        'summary': _queue_summary(previews, org_id),
        'subscription_previews': limited_previews,
        'meta': _empty_store(org_id)['_meta'],
    }
