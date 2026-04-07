#!/usr/bin/env python3
"""Tracked subscription service helpers for the founding live workspace."""
import contextlib
import datetime
import fcntl
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from urllib import request as urllib_request
from urllib.parse import quote_plus

from capsule import (
    ensure_subscription_aliases,
    subscriptions_path,
    subscriptions_backup_path,
    subscriptions_lock_path,
)
from loom_runtime_client import LoomRuntimeContext
from loom_runtime_client import capability_preflight as shared_loom_capability_preflight
from loom_runtime_client import run_capability as shared_run_loom_capability


TRIAL_DAYS = 7
PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(PLATFORM_DIR))
ECONOMY_DIR = os.path.join(WORKSPACE, 'economy')
REVENUE_PY = os.path.join(ECONOMY_DIR, 'revenue.py')

_revenue_spec = importlib.util.spec_from_file_location('subscription_service_revenue', REVENUE_PY)
_revenue_mod = importlib.util.module_from_spec(_revenue_spec)
_revenue_spec.loader.exec_module(_revenue_mod)

MERIDIAN_HOME = os.environ.get('MERIDIAN_HOME', os.path.expanduser('~/.meridian'))
BASE_WALLET_FILE = os.environ.get(
    'MERIDIAN_BASE_WALLET_FILE',
    os.path.join(MERIDIAN_HOME, 'credentials', 'base_wallet.json'),
)
BASE_CHAIN_ID = 8453
BASE_USDC_ASSET = '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'
BASE_USDC_DECIMALS = 6
BASE_USDC_TRANSFER_TOPIC = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
BASE_RPC_URLS = tuple(
    url.strip()
    for url in (
        os.environ.get('MERIDIAN_BASE_RPC_URL', ''),
        os.environ.get('MERIDIAN_BASE_RPC_URL_BACKUP', ''),
        'https://base-rpc.publicnode.com',
        'https://base-mainnet.public.blastapi.io',
    )
    if str(url or '').strip()
)
PUBLIC_CHECKOUT_PLAN = 'founder-pilot-week'
PUBLIC_CHECKOUT_PAYMENT_METHOD = 'base_usdc'
INSTITUTION_LICENSE_CHECKOUT_PAYMENT_METHOD = 'base_usdc'
INSTITUTION_LICENSE_DEFAULT_PLAN = 'institution-license-foundation'
INSTITUTION_LICENSE_MAINTENANCE_PLAN = 'institution-license-maintenance-monthly'

PLANS = {
    PUBLIC_CHECKOUT_PLAN:         {'price_usd': 49.00, 'duration_days': 7,  'type': 'one-time'},
    'premium-brief-monthly': {'price_usd': 9.99, 'duration_days': 30, 'type': 'recurring'},
    'premium-brief-weekly':  {'price_usd': 2.99, 'duration_days': 7,  'type': 'recurring'},
    'deep-dive-single':      {'price_usd': 9.99, 'duration_days': 0,  'type': 'one-time'},
    'trial':                 {'price_usd': 0.00, 'duration_days': TRIAL_DAYS,  'type': 'trial'},
    INSTITUTION_LICENSE_DEFAULT_PLAN: {
        'price_usd': 299.00,
        'duration_days': 365,
        'type': 'one-time',
        'product_category': 'constitutional_institution_license',
        'recurring_plan': INSTITUTION_LICENSE_MAINTENANCE_PLAN,
        'revenue_share_pct': 0.10,
    },
    INSTITUTION_LICENSE_MAINTENANCE_PLAN: {
        'price_usd': 79.00,
        'duration_days': 30,
        'type': 'recurring',
        'product_category': 'constitutional_institution_maintenance',
        'renewal_of': INSTITUTION_LICENSE_DEFAULT_PLAN,
        'revenue_share_pct': 0.10,
    },
}

LOOM_DELIVERY_CAPABILITY_ENV_VARS = (
    'MERIDIAN_LOOM_SUBSCRIPTION_DELIVERY_CAPABILITY',
    'MERIDIAN_LOOM_DELIVERY_CAPABILITY',
)
LOOM_DELIVERY_CAPABILITY_FALLBACK_ENV_VARS = (
    'MERIDIAN_LOOM_RESEARCH_CAPABILITY',
)
SEND_EMAIL_PY = os.path.join(WORKSPACE, 'company', 'send_email.py')
DEFAULT_LOOM_DELIVERY_TIMEOUT = 30
BRIEF_PREVIEW_LIMIT = 280


def now_ts():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def now_dt():
    return datetime.datetime.utcnow()


def _load_base_wallet_address():
    if os.path.exists(BASE_WALLET_FILE):
        with open(BASE_WALLET_FILE) as f:
            payload = json.load(f)
        address = str(payload.get('address') or '').strip()
        if address:
            return address
    raise RuntimeError(f'Base wallet not found at {BASE_WALLET_FILE}')


def public_checkout_offer():
    plan = dict(PLANS[PUBLIC_CHECKOUT_PLAN])
    return {
        'requested_offer': PUBLIC_CHECKOUT_PLAN,
        'plan': PUBLIC_CHECKOUT_PLAN,
        'price_usd': float(plan['price_usd']),
        'duration_days': int(plan['duration_days']),
        'billing_type': plan['type'],
        'payment_method': PUBLIC_CHECKOUT_PAYMENT_METHOD,
        'payment_instructions': {
            'method': PUBLIC_CHECKOUT_PAYMENT_METHOD,
            'network': 'Base L2',
            'chain_id': BASE_CHAIN_ID,
            'asset': 'USDC',
            'asset_address': BASE_USDC_ASSET,
            'amount_usd': float(plan['price_usd']),
            'recipient_wallet': _load_base_wallet_address(),
            'payment_ref_mode': 'tx_hash',
            'checkout_capture_path': '/api/subscriptions/checkout-capture',
            'note': 'Pay the exact USDC amount on Base, then submit the transaction hash as payment_ref.',
        },
    }


def institution_license_catalog():
    foundation = dict(PLANS[INSTITUTION_LICENSE_DEFAULT_PLAN])
    maintenance = dict(PLANS[INSTITUTION_LICENSE_MAINTENANCE_PLAN])
    return {
        'schema_version': 'meridian.institution_license_catalog.v1',
        'default_plan': INSTITUTION_LICENSE_DEFAULT_PLAN,
        'checkout_capture_path': '/api/institution/license/checkout-capture',
        'payment_method': INSTITUTION_LICENSE_CHECKOUT_PAYMENT_METHOD,
        'maintenance_plan': INSTITUTION_LICENSE_MAINTENANCE_PLAN,
        'plans': [
            {
                'plan': INSTITUTION_LICENSE_DEFAULT_PLAN,
                'price_usd': float(foundation['price_usd']),
                'duration_days': int(foundation['duration_days']),
                'billing_type': foundation['type'],
                'revenue_share_pct': float(foundation.get('revenue_share_pct') or 0.0),
                'recurring_plan': str(foundation.get('recurring_plan') or '').strip(),
                'positioning': 'One-time constitutional institution license setup.',
            },
            {
                'plan': INSTITUTION_LICENSE_MAINTENANCE_PLAN,
                'price_usd': float(maintenance['price_usd']),
                'duration_days': int(maintenance['duration_days']),
                'billing_type': maintenance['type'],
                'revenue_share_pct': float(maintenance.get('revenue_share_pct') or 0.0),
                'renewal_of': str(maintenance.get('renewal_of') or '').strip(),
                'positioning': 'Monthly maintenance for policy updates and managed support.',
            },
        ],
        'boundary': {
            'institution_scope': 'founding_service_only',
            'customer_settlement': 'base_usdc_checkout_capture',
            'note': 'Founding-host implementation: verifiable payment evidence and ledger capture are live; multi-institution external settlement remains intentionally bounded.',
        },
    }


def institution_license_checkout_offer(plan_name=''):
    catalog = institution_license_catalog()
    selected = str(plan_name or catalog['default_plan']).strip() or catalog['default_plan']
    if selected not in PLANS:
        raise ValueError(f"unknown plan '{selected}'. Available: {', '.join(sorted(PLANS.keys()))}")
    if selected not in {INSTITUTION_LICENSE_DEFAULT_PLAN, INSTITUTION_LICENSE_MAINTENANCE_PLAN}:
        raise ValueError(f"plan '{selected}' is not an institution-license plan")
    plan = dict(PLANS[selected])
    return {
        'requested_offer': selected,
        'plan': selected,
        'price_usd': float(plan['price_usd']),
        'duration_days': int(plan['duration_days']),
        'billing_type': str(plan.get('type') or '').strip(),
        'revenue_share_pct': float(plan.get('revenue_share_pct') or 0.0),
        'payment_method': INSTITUTION_LICENSE_CHECKOUT_PAYMENT_METHOD,
        'payment_instructions': {
            'method': INSTITUTION_LICENSE_CHECKOUT_PAYMENT_METHOD,
            'network': 'Base L2',
            'chain_id': BASE_CHAIN_ID,
            'asset': 'USDC',
            'asset_address': BASE_USDC_ASSET,
            'amount_usd': float(plan['price_usd']),
            'recipient_wallet': _load_base_wallet_address(),
            'payment_ref_mode': 'tx_hash',
            'checkout_capture_path': '/api/institution/license/checkout-capture',
            'note': 'Pay exact USDC on Base, then submit transaction hash for institution-license capture.',
        },
        'maintenance_plan': str(plan.get('recurring_plan') or '').strip(),
    }


def capture_institution_license_checkout(*, plan_name='', payment_ref='', tx_hash='',
                                         institution_name='', buyer_name='', buyer_contact='',
                                         org_id=None):
    offer = institution_license_checkout_offer(plan_name)
    resolved_plan = offer['plan']
    payment_ref = str(payment_ref or tx_hash).strip()
    tx_hash = str(tx_hash or payment_ref).strip()
    if not payment_ref:
        raise ValueError('payment_ref is required')
    if not tx_hash:
        raise ValueError('tx_hash is required')

    preview = {
        'preview_id': f'inst_license_{payment_ref}',
        'company': str(institution_name or buyer_name or '').strip(),
        'name': str(buyer_name or institution_name or '').strip(),
        'email': str(buyer_contact or '').strip(),
    }
    settlement = ensure_base_usdc_customer_payment(
        preview,
        plan_name=resolved_plan,
        payment_ref=payment_ref,
        tx_hash=tx_hash,
        org_id=org_id,
    )

    existing_events = _revenue_mod.load_transactions()
    binding_exists = False
    for entry in existing_events:
        if str(entry.get('type') or '').strip() != 'institution_license_binding':
            continue
        if str(entry.get('payment_ref') or '').strip() == payment_ref:
            binding_exists = True
            break
    if not binding_exists:
        _revenue_mod.append_tx({
            'type': 'institution_license_binding',
            'plan': resolved_plan,
            'payment_ref': payment_ref,
            'tx_hash': tx_hash,
            'institution_name': str(institution_name or '').strip(),
            'buyer_name': str(buyer_name or '').strip(),
            'buyer_contact': str(buyer_contact or '').strip(),
            'maintenance_plan': offer.get('maintenance_plan', ''),
            'revenue_share_pct': float(offer.get('revenue_share_pct') or 0.0),
            'evidence_mode': str(settlement.get('mode') or '').strip(),
            'boundary_scope': 'founding_service_only',
        })

    evidence = dict(settlement.get('evidence') or {})
    order_id = str(evidence.get('order_id') or f'order_{payment_ref}')
    license_id = _revenue_mod.stable_short_id(f'institution-license:{resolved_plan}:{payment_ref}')
    return {
        'license_id': license_id,
        'plan': resolved_plan,
        'maintenance_plan': offer.get('maintenance_plan', ''),
        'price_usd': float(offer.get('price_usd') or 0.0),
        'revenue_share_pct': float(offer.get('revenue_share_pct') or 0.0),
        'payment_ref': payment_ref,
        'tx_hash': tx_hash,
        'order_id': order_id,
        'settlement': settlement,
        'boundary': {
            'institution_scope': 'founding_service_only',
            'ledger_binding_event': 'institution_license_binding',
        },
    }


def _rpc_json(url, method, params):
    payload = json.dumps({
        'jsonrpc': '2.0',
        'id': 1,
        'method': method,
        'params': params,
    }).encode('utf-8')
    req = urllib_request.Request(
        url,
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'Meridian/1.0',
        },
    )
    with urllib_request.urlopen(req, timeout=10) as response:
        body = json.loads(response.read().decode('utf-8'))
    if body.get('error'):
        raise RuntimeError(str(body['error']))
    return body.get('result')


def _rpc_json_any(method, params):
    last_error = 'no Base RPC URL configured'
    for url in BASE_RPC_URLS:
        try:
            result = _rpc_json(url, method, params)
            return result, url
        except Exception as exc:
            last_error = f'{url}: {exc}'
    raise RuntimeError(f'Base RPC request failed for {method}: {last_error}')


def _topic_address(topic):
    value = str(topic or '').strip().lower()
    if value.startswith('0x'):
        value = value[2:]
    if len(value) != 64:
        return ''
    return '0x' + value[-40:]


def _usd_to_base_usdc_units(amount_usd):
    return int(round(float(amount_usd or 0.0) * (10 ** BASE_USDC_DECIMALS)))


def _verify_base_usdc_payment(tx_hash, *, amount_usd):
    tx_hash = str(tx_hash or '').strip()
    if not tx_hash:
        raise ValueError('tx_hash is required for Base USDC verification')
    if not tx_hash.startswith('0x') or len(tx_hash) != 66:
        raise ValueError('tx_hash must be a 0x-prefixed 32-byte hash')

    chain_id_hex, chain_rpc_url = _rpc_json_any('eth_chainId', [])
    if int(chain_id_hex, 16) != BASE_CHAIN_ID:
        raise RuntimeError(f'Unexpected Base RPC chain id: {chain_id_hex}')

    receipt, receipt_rpc_url = _rpc_json_any('eth_getTransactionReceipt', [tx_hash])
    if not receipt:
        raise LookupError(f'Base transaction receipt not found for {tx_hash}')
    if int(receipt.get('status') or '0x0', 16) != 1:
        raise ValueError(f'Base transaction {tx_hash} did not execute successfully')

    receiving_wallet = _load_base_wallet_address().lower()
    expected_units = _usd_to_base_usdc_units(amount_usd)
    total_units = 0
    payer_wallet = ''
    matched_logs = []
    for entry in receipt.get('logs') or []:
        if str(entry.get('address') or '').lower() != BASE_USDC_ASSET.lower():
            continue
        topics = entry.get('topics') or []
        if len(topics) < 3:
            continue
        if str(topics[0] or '').lower() != BASE_USDC_TRANSFER_TOPIC:
            continue
        recipient = _topic_address(topics[2]).lower()
        if recipient != receiving_wallet:
            continue
        units = int(str(entry.get('data') or '0x0'), 16)
        total_units += units
        payer_wallet = payer_wallet or _topic_address(topics[1]).lower()
        matched_logs.append({
            'log_index': entry.get('logIndex', ''),
            'from': _topic_address(topics[1]),
            'to': recipient,
            'amount_units': units,
        })

    if total_units < expected_units:
        raise ValueError(
            f'Base USDC receipt {tx_hash} transferred {total_units / (10 ** BASE_USDC_DECIMALS):.6f} USDC '
            f'to {receiving_wallet}, below required {float(amount_usd):.2f} USDC'
        )

    return {
        'network': 'Base L2',
        'chain_id': BASE_CHAIN_ID,
        'tx_hash': tx_hash,
        'asset': 'USDC',
        'asset_address': BASE_USDC_ASSET,
        'recipient_wallet': receiving_wallet,
        'payer_wallet': payer_wallet,
        'received_units': total_units,
        'received_amount_usdc': round(total_units / (10 ** BASE_USDC_DECIMALS), 6),
        'required_amount_usdc': float(amount_usd),
        'receipt_rpc_url': receipt_rpc_url,
        'chain_rpc_url': chain_rpc_url,
        'matched_logs': matched_logs,
    }


def ensure_base_usdc_customer_payment(preview, *, plan_name='', payment_ref='', tx_hash='', org_id=None):
    preview = dict(preview or {})
    plan_name = (plan_name or '').strip()
    if plan_name not in PLANS:
        raise ValueError(f"unknown plan '{plan_name}'. Available: {', '.join(sorted(PLANS.keys()))}")
    tx_hash = str(tx_hash or '').strip()
    payment_ref = str(payment_ref or tx_hash).strip()
    if not tx_hash:
        raise ValueError('tx_hash is required for Base USDC checkout capture')
    if not payment_ref:
        raise ValueError('payment_ref is required for Base USDC checkout capture')

    amount_usd = float(PLANS[plan_name]['price_usd'])
    existing = _revenue_mod.find_customer_payment_evidence(
        payment_ref=payment_ref,
        tx_hash=tx_hash,
        min_amount_usd=amount_usd,
    )
    if existing:
        return {
            'mode': 'existing_customer_payment',
            'payment_ref': payment_ref,
            'tx_hash': tx_hash,
            'evidence': dict(existing),
            'verification': {
                'network': 'Base L2',
                'chain_id': BASE_CHAIN_ID,
                'status': 'already_recorded',
            },
        }

    verification = _verify_base_usdc_payment(tx_hash, amount_usd=amount_usd)
    client_name = (preview.get('company') or preview.get('name') or preview.get('preview_id') or 'meridian-customer').strip()
    client_contact = (
        preview.get('email')
        or preview.get('telegram_handle')
        or preview.get('preview_id')
        or payment_ref
    )
    record = _revenue_mod.record_external_customer_payment(
        plan_name,
        amount_usd,
        payment_key=f'ref:{payment_ref}',
        client_name=client_name,
        client_contact=client_contact,
        note=f'Base USDC checkout capture for {preview.get("preview_id") or "preview"}',
        tx_hash=tx_hash,
        payment_ref=payment_ref,
        payment_source='base_usdc_checkout',
    )
    evidence = _revenue_mod.find_customer_payment_evidence(
        payment_ref=payment_ref,
        tx_hash=tx_hash,
        min_amount_usd=amount_usd,
    ) or {}
    return {
        'mode': 'verified_base_usdc_recorded',
        'payment_ref': payment_ref,
        'tx_hash': tx_hash,
        'record': dict(record),
        'verification': verification,
        'evidence': dict(evidence),
    }


def _default_plan_from_preview(preview):
    preview = dict(preview or {})
    options = []
    for entry in preview.get('plan_options') or []:
        if not isinstance(entry, dict):
            continue
        plan_name = str(entry.get('plan') or '').strip()
        if plan_name:
            options.append(plan_name)
    unique = sorted(set(options))
    if len(unique) == 1:
        return unique[0]
    return ''


def _delivery_telegram_target(preview, explicit_telegram_id=''):
    explicit = str(explicit_telegram_id or '').strip()
    if explicit and not explicit.lower().startswith('email:'):
        return explicit
    preview_telegram_id = str(dict(preview or {}).get('telegram_id') or '').strip()
    if preview_telegram_id and not preview_telegram_id.lower().startswith('email:'):
        return preview_telegram_id
    handle = str(dict(preview or {}).get('telegram_handle') or '').strip()
    if handle and not handle.lower().startswith('email:'):
        return handle
    return ''


def _default_subscriptions(org_id=None):
    return {
        'subscribers': {},
        'draft_subscriptions': {},
        'loom_delivery_jobs': {},
        'loom_delivery_runs': [],
        'delivery_log': [],
        'updatedAt': now_ts(),
        '_meta': {
            'service_scope': 'institution_owned_subscription_service',
            'boundary_name': 'subscriptions',
            'identity_model': 'session',
            'storage_model': 'capsule_canonical_with_compatibility_alias',
            'bound_org_id': org_id or '',
            'internal_test_ids': [],
        },
    }


def _normalize_draft_subscription(draft, org_id=None, existing=None):
    draft = dict(draft or {})
    existing = dict(existing or {})
    draft_id = (draft.get('draft_id') or existing.get('draft_id') or '').strip()
    if not draft_id:
        draft_id = f"draft_{uuid.uuid4().hex[:12]}"

    record = dict(existing)
    record['draft_id'] = draft_id
    record['preview_id'] = (draft.get('preview_id') or existing.get('preview_id') or '').strip()
    record['pilot_request_id'] = (draft.get('pilot_request_id') or existing.get('pilot_request_id') or '').strip()
    record['source_preview_state'] = (
        draft.get('source_preview_state')
        or existing.get('source_preview_state')
        or ''
    ).strip()
    record['source_preview_truth_source'] = (
        draft.get('source_preview_truth_source')
        or existing.get('source_preview_truth_source')
        or ''
    ).strip()
    record['requested_offer'] = (draft.get('requested_offer') or existing.get('requested_offer') or '').strip()
    record['requested_cadence'] = (draft.get('requested_cadence') or existing.get('requested_cadence') or '').strip()
    record['name'] = (draft.get('name') or existing.get('name') or '').strip()
    record['company'] = (draft.get('company') or existing.get('company') or '').strip()
    record['email'] = (draft.get('email') or existing.get('email') or '').strip()
    record['telegram_handle'] = (draft.get('telegram_handle') or existing.get('telegram_handle') or '').strip()
    record['plan_options'] = list(draft.get('plan_options') or existing.get('plan_options') or [])
    record['plan'] = (draft.get('plan') or existing.get('plan') or '').strip()
    record['price_usd'] = float(draft.get('price_usd', existing.get('price_usd', 0.0)) or 0.0)
    record['status'] = (draft.get('status') or existing.get('status') or 'draft').strip() or 'draft'
    record['drafted_at'] = (draft.get('drafted_at') or existing.get('drafted_at') or '').strip()
    record['drafted_by'] = (draft.get('drafted_by') or existing.get('drafted_by') or '').strip()
    record['draft_note'] = (draft.get('draft_note') or existing.get('draft_note') or '').strip()
    record['subscription_id'] = (draft.get('subscription_id') or existing.get('subscription_id') or '').strip()
    record['subscription_source'] = (
        draft.get('subscription_source')
        or existing.get('subscription_source')
        or 'subscription_preview_queue'
    ).strip()
    record['subscription_status'] = (draft.get('subscription_status') or existing.get('subscription_status') or 'draft').strip() or 'draft'
    record['payment_method'] = (draft.get('payment_method') or existing.get('payment_method') or 'draft').strip()
    record['payment_ref'] = (draft.get('payment_ref') or existing.get('payment_ref') or '').strip()
    record['payment_verified'] = bool(draft.get('payment_verified', existing.get('payment_verified', False)))
    record['payment_verified_at'] = (draft.get('payment_verified_at') or existing.get('payment_verified_at') or '').strip()
    record['payment_evidence'] = dict(draft.get('payment_evidence') or existing.get('payment_evidence') or {})
    record['created_at'] = (draft.get('created_at') or existing.get('created_at') or now_ts()).strip()
    record['updated_at'] = now_ts()
    return record


def _normalize_subscriptions(data, org_id=None):
    if not isinstance(data, dict):
        return _default_subscriptions(org_id)
    payload = dict(data)
    payload.setdefault('subscribers', {})
    payload.setdefault('draft_subscriptions', {})
    payload.setdefault('loom_delivery_jobs', {})
    payload.setdefault('loom_delivery_runs', [])
    payload.setdefault('delivery_log', [])
    payload.setdefault('updatedAt', now_ts())
    payload.setdefault('_meta', {})
    payload['_meta']['service_scope'] = 'institution_owned_subscription_service'
    payload['_meta']['boundary_name'] = 'subscriptions'
    payload['_meta']['identity_model'] = 'session'
    payload['_meta']['storage_model'] = 'capsule_canonical_with_compatibility_alias'
    payload['_meta']['bound_org_id'] = org_id or payload['_meta'].get('bound_org_id', '')
    payload['_meta'].setdefault('internal_test_ids', [])
    raw_drafts = payload.get('draft_subscriptions', {})
    drafts = {}
    if isinstance(raw_drafts, list):
        for item in raw_drafts:
            if isinstance(item, dict):
                draft_id = (item.get('draft_id') or '').strip()
                if draft_id:
                    drafts[draft_id] = dict(item)
    elif isinstance(raw_drafts, dict):
        for draft_id, item in raw_drafts.items():
            if isinstance(item, dict):
                record = dict(item)
                record['draft_id'] = record.get('draft_id') or draft_id
                drafts[record['draft_id']] = record
    for draft_id, record in list(drafts.items()):
        drafts[draft_id] = _normalize_draft_subscription(record, org_id, existing=record)
    payload['draft_subscriptions'] = drafts

    raw_jobs = payload.get('loom_delivery_jobs', {})
    jobs = {}
    if isinstance(raw_jobs, list):
        for item in raw_jobs:
            if isinstance(item, dict):
                job_id = (item.get('job_id') or '').strip()
                if job_id:
                    jobs[job_id] = dict(item)
    elif isinstance(raw_jobs, dict):
        for job_id, item in raw_jobs.items():
            if isinstance(item, dict):
                record = dict(item)
                record['job_id'] = record.get('job_id') or job_id
                jobs[record['job_id']] = record
    payload['loom_delivery_jobs'] = {
        job_id: _normalize_loom_delivery_job(record, org_id, existing=record)
        for job_id, record in jobs.items()
    }

    raw_runs = payload.get('loom_delivery_runs', [])
    runs = []
    if isinstance(raw_runs, list):
        for item in raw_runs:
            if isinstance(item, dict):
                runs.append(dict(item))
    elif isinstance(raw_runs, dict):
        for run_id, item in raw_runs.items():
            if isinstance(item, dict):
                record = dict(item)
                record['run_id'] = record.get('run_id') or run_id
                runs.append(record)
    payload['loom_delivery_runs'] = [
        _normalize_loom_delivery_run(run, org_id, existing=run)
        for run in runs
    ]
    return payload


def _storage_paths(org_id=None):
    ensure_subscription_aliases(org_id)
    return subscriptions_path(org_id), subscriptions_backup_path(org_id)


def _write_json_atomic(path, data):
    directory = os.path.dirname(path) or '.'
    fd, tmp_path = tempfile.mkstemp(
        prefix=os.path.basename(path) + '.',
        suffix='.tmp',
        dir=directory,
    )
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@contextlib.contextmanager
def _subscriptions_lock(org_id=None):
    ensure_subscription_aliases(org_id)
    with open(subscriptions_lock_path(org_id), 'a+') as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def load_subscriptions(org_id=None):
    primary_path, backup_path = _storage_paths(org_id)
    for path in (primary_path, backup_path):
        if os.path.exists(path) and os.path.getsize(path) > 0:
            with open(path) as f:
                return _normalize_subscriptions(json.load(f), org_id)
    return _default_subscriptions(org_id)


def save_subscriptions(data, org_id=None):
    payload = _normalize_subscriptions(data, org_id)
    payload['updatedAt'] = now_ts()
    primary_path, backup_path = _storage_paths(org_id)
    with _subscriptions_lock(org_id):
        _write_json_atomic(primary_path, payload)
        _write_json_atomic(backup_path, payload)


def _subscription_delivery_eligible(sub, *, org_id=None, now=None):
    now = now or now_dt()
    if sub.get('status') != 'active':
        return False
    if sub.get('plan') not in (PUBLIC_CHECKOUT_PLAN, 'premium-brief-monthly', 'premium-brief-weekly', 'trial'):
        return False
    expires_at = (sub.get('expires_at') or '').strip()
    if expires_at:
        expires = datetime.datetime.strptime(expires_at, '%Y-%m-%dT%H:%M:%SZ')
        if expires < now:
            return False
    if sub.get('plan') != 'trial' and (
        not sub.get('payment_verified', False) or not _payment_evidence_ok(sub, org_id=org_id)
    ):
        return False
    return True


def _payment_evidence(sub, *, org_id=None):
    if sub.get('plan') == 'trial':
        return {'type': 'trial', 'payment_ref': ''}
    payment_ref = (sub.get('payment_ref') or '').strip()
    if not payment_ref:
        return None
    return _revenue_mod.find_customer_payment_evidence(
        payment_ref=payment_ref,
        min_amount_usd=float(sub.get('price_usd', 0.0) or 0.0),
    )


def _payment_evidence_ok(sub, *, org_id=None):
    if sub.get('plan') == 'trial':
        return True
    evidence = _payment_evidence(sub, org_id=org_id)
    if not evidence:
        return False
    bound = sub.get('payment_evidence', {})
    if bound:
        if bound.get('order_id') and evidence.get('order_id') != bound.get('order_id'):
            return False
        if bound.get('payment_key') and evidence.get('payment_key') != bound.get('payment_key'):
            return False
        if bound.get('tx_hash') and evidence.get('tx_hash') != bound.get('tx_hash'):
            return False
    return True


def _require_payment_evidence(payment_ref, amount_usd, *, payment_evidence=None, org_id=None):
    payment_ref = (payment_ref or '').strip()
    if not payment_ref:
        raise ValueError('payment_ref is required for paid subscription verification')
    evidence_hint = _coerce_payment_evidence(payment_evidence)
    evidence = _revenue_mod.find_customer_payment_evidence(
        payment_ref=payment_ref,
        tx_hash=(evidence_hint.get('tx_hash') or '').strip(),
        min_amount_usd=float(amount_usd or 0.0),
    )
    if not evidence:
        raise ValueError(
            f'no customer_payment evidence found for payment_ref={payment_ref} amount>={float(amount_usd or 0.0):.2f}'
        )
    if evidence_hint:
        for field in ('order_id', 'payment_key', 'payment_ref', 'tx_hash'):
            expected = (evidence_hint.get(field) or '').strip()
            if expected and (evidence.get(field) or '') != expected:
                raise ValueError(f'payment_evidence {field} mismatch for payment_ref={payment_ref}')
        expected_amount = evidence_hint.get('amount_usd')
        if expected_amount not in (None, ''):
            if abs(float(evidence.get('amount', 0.0) or 0.0) - float(expected_amount)) > 1e-9:
                raise ValueError(f'payment_evidence amount mismatch for payment_ref={payment_ref}')
    return evidence


def _bind_payment_evidence(subscription, payment_ref=None, *, payment_evidence=None, org_id=None):
    ref = (payment_ref if payment_ref is not None else subscription.get('payment_ref', '')) or ''
    evidence = _require_payment_evidence(
        ref,
        subscription.get('price_usd', 0.0),
        payment_evidence=payment_evidence,
        org_id=org_id,
    )
    subscription['payment_ref'] = ref
    subscription['payment_verified'] = True
    subscription['payment_verified_at'] = now_ts()
    subscription['payment_evidence'] = {
        'order_id': evidence.get('order_id', ''),
        'payment_key': evidence.get('payment_key', ''),
        'payment_ref': evidence.get('payment_ref', ref),
        'tx_hash': evidence.get('tx_hash', ''),
        'amount_usd': float(evidence.get('amount', 0.0) or 0.0),
    }
    return evidence


def _loom_bin():
    return (
        os.environ.get('MERIDIAN_LOOM_BIN')
        or '/home/ubuntu/.local/share/meridian-loom/current/bin/loom'
    ).strip()


def _loom_root():
    return (os.environ.get('MERIDIAN_LOOM_ROOT') or '/home/ubuntu/.local/share/meridian-loom/runtime/default').strip()


def _loom_org_id():
    for key in ('MERIDIAN_LOOM_ORG_ID', 'MERIDIAN_MCP_ORG_ID', 'MERIDIAN_WORKSPACE_ORG_ID'):
        value = (os.environ.get(key) or '').strip()
        if value:
            return value
    return 'org_48b05c21'


def _loom_service_token():
    return (
        os.environ.get('MERIDIAN_LOOM_SERVICE_TOKEN')
        or os.environ.get('LOOM_SERVICE_TOKEN')
        or ''
    ).strip()


def _loom_delivery_capability():
    for name in LOOM_DELIVERY_CAPABILITY_ENV_VARS + LOOM_DELIVERY_CAPABILITY_FALLBACK_ENV_VARS:
        capability = (os.environ.get(name) or '').strip()
        if capability:
            return capability
    return ''


def _loom_runtime_context():
    return LoomRuntimeContext(
        loom_bin=_loom_bin(),
        loom_root=_loom_root(),
        org_id=_loom_org_id(),
        agent_id=(os.environ.get('MERIDIAN_LOOM_AGENT_ID') or 'leviathann').strip(),
        service_token=_loom_service_token(),
        cwd=WORKSPACE,
        runtime_env=os.environ,
    )


def _load_json_file(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def _coerce_payment_evidence(payment_evidence):
    if not isinstance(payment_evidence, dict):
        return {}
    return {
        key: value
        for key, value in payment_evidence.items()
        if value not in (None, '')
    }


def _normalize_text_list(values):
    if values in (None, ''):
        return []
    if isinstance(values, list):
        raw_items = values
    else:
        raw_items = str(values).split(',')
    return [str(item).strip() for item in raw_items if str(item).strip()]


def _trim_text(value, limit=BRIEF_PREVIEW_LIMIT):
    text = str(value or '').strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 0)].rstrip() + '...'


def _looks_like_http_url(value):
    raw = (value or '').strip().lower()
    return raw.startswith('http://') or raw.startswith('https://')


def _loom_research_url(topic):
    topic = (topic or '').strip()
    if _looks_like_http_url(topic):
        return topic
    if not topic:
        return ''
    return f"https://duckduckgo.com/html/?q={quote_plus(topic)}"


def _subscription_delivery_title(job, subscription=None):
    subscription = dict(subscription or {})
    company = (job.get('company') or subscription.get('company') or job.get('name') or '').strip()
    if company:
        return f"Meridian Intelligence brief for {company}"
    return 'Meridian Intelligence subscription brief'


def _subscription_delivery_topic(job):
    parts = []
    company = (job.get('company') or job.get('name') or '').strip()
    if company:
        parts.append(company)
    parts.extend(_normalize_text_list(job.get('topics'))[:3])
    parts.extend(_normalize_text_list(job.get('competitors'))[:2])
    parts.append('AI market intelligence')
    topic = ' '.join(part for part in parts if part).strip()
    return topic or f"{(job.get('plan') or 'subscription').strip()} intelligence brief"


def _subscription_delivery_prompt(job, subscription=None):
    subscription = dict(subscription or {})
    company = (job.get('company') or subscription.get('company') or job.get('name') or '').strip() or 'the subscriber'
    cadence = (job.get('requested_cadence') or '').strip() or 'recurring intelligence brief'
    plan = (job.get('plan') or subscription.get('plan') or '').strip() or 'subscription'
    offer = (job.get('requested_offer') or '').strip() or 'subscription_delivery'
    topics = ', '.join(_normalize_text_list(job.get('topics'))) or 'not specified'
    competitors = ', '.join(_normalize_text_list(job.get('competitors'))) or 'not specified'
    return (
        f"Create the Meridian subscriber intelligence brief for {company}. "
        f"Requested cadence: {cadence}. Subscription plan: {plan}. Offer context: {offer}. "
        f"Focus topics: {topics}. Competitors: {competitors}. "
        "Return a concise, publication-ready brief in plain text with short headings, specific current signals, and concrete follow-up actions. "
        "Do not mention internal tooling or implementation details."
    )


def _subscription_delivery_payload(job, *, subscription=None, actor=''):
    topic = _subscription_delivery_topic(job)
    payload = {
        'job_id': job.get('job_id', ''),
        'subscription_id': job.get('subscription_id', ''),
        'preview_id': job.get('preview_id', ''),
        'telegram_id': job.get('telegram_id', ''),
        'email': job.get('email', ''),
        'plan': job.get('plan', ''),
        'queued_at': job.get('queued_at', ''),
        'actor': actor or '',
        'job_type': job.get('job_type', 'subscription_loom_delivery'),
        'delivery_kind': 'subscription_activation_brief',
        'delivery_title': _subscription_delivery_title(job, subscription=subscription),
        'requested_cadence': job.get('requested_cadence', ''),
        'requested_offer': job.get('requested_offer', ''),
        'topics': _normalize_text_list(job.get('topics')),
        'competitors': _normalize_text_list(job.get('competitors')),
        'topic': topic,
        'depth': 'standard',
        'prompt': _subscription_delivery_prompt(job, subscription=subscription),
    }
    loom_url = _loom_research_url(topic)
    if loom_url:
        payload['url'] = loom_url
        payload['urls'] = [loom_url]
    return payload


def _extract_loom_delivery_artifact(worker_result, *, job, execution=None):
    execution = dict(execution or {})
    payload = worker_result.get('skill_output')
    brief_text = ''
    source_key = ''
    if isinstance(payload, dict):
        for key in ('research', 'response', 'message', 'text'):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                brief_text = value.strip()
                source_key = key
                break
        if not brief_text:
            results = payload.get('results')
            if isinstance(results, list):
                normalized = []
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    text = item.get('normalized_text')
                    if isinstance(text, str) and text.strip():
                        normalized.append(text.strip())
                if normalized:
                    brief_text = '\n\n'.join(normalized)
                    source_key = 'results.normalized_text'
    if not brief_text:
        summary = worker_result.get('summary')
        if isinstance(summary, str) and summary.strip():
            brief_text = summary.strip()
            source_key = 'summary'

    artifact = {
        'artifact_type': 'subscription_brief_v1',
        'content_type': 'text/plain',
        'subscription_id': job.get('subscription_id', ''),
        'preview_id': job.get('preview_id', ''),
        'job_id': job.get('job_id', ''),
        'delivery_title': _subscription_delivery_title(job),
        'brief_date': now_dt().date().isoformat(),
        'topic': _subscription_delivery_topic(job),
        'result_path': execution.get('result_path', ''),
        'source_key': source_key,
    }
    if brief_text:
        artifact['brief_text'] = brief_text
        artifact['brief_preview'] = _trim_text(brief_text)
        return {
            'ok': True,
            'artifact': artifact,
        }

    artifact['raw_worker_result'] = dict(worker_result or {})
    artifact['brief_preview'] = ''
    return {
        'ok': False,
        'error': 'Loom execution completed without a deliverable brief body',
        'artifact': artifact,
    }


def _dispatch_telegram_delivery(telegram_id, message, *, timeout):
    target = str(telegram_id or '').strip()
    if not target:
        return None
    sent_at = now_ts()
    try:
        result = subprocess.run(
            [
                _loom_bin(),
                'channel',
                'send',
                '--root',
                _loom_root(),
                '--channel',
                'telegram',
                '--recipient',
                target,
                '--text',
                message,
                '--format',
                'json',
            ],
            capture_output=True,
            text=True,
            timeout=min(int(timeout or DEFAULT_LOOM_DELIVERY_TIMEOUT), DEFAULT_LOOM_DELIVERY_TIMEOUT),
            cwd=WORKSPACE,
        )
    except subprocess.TimeoutExpired:
        return {
            'channel': 'telegram',
            'target': target,
            'ok': False,
            'sent_at': sent_at,
            'error': 'telegram delivery timed out',
        }
    except Exception as exc:
        return {
            'channel': 'telegram',
            'target': target,
            'ok': False,
            'sent_at': sent_at,
            'error': str(exc),
        }
    if result.returncode == 0:
        return {
            'channel': 'telegram',
            'target': target,
            'ok': True,
            'sent_at': sent_at,
            'receipt': (result.stdout or '').strip(),
        }
    return {
        'channel': 'telegram',
        'target': target,
        'ok': False,
        'sent_at': sent_at,
        'error': ((result.stderr or result.stdout or '').strip()[:500] or 'telegram delivery failed'),
    }


def _dispatch_email_delivery(email, subject, body, *, timeout):
    target = str(email or '').strip()
    if not target:
        return None
    sent_at = now_ts()
    if not os.path.exists(SEND_EMAIL_PY):
        return {
            'channel': 'email',
            'target': target,
            'ok': False,
            'sent_at': sent_at,
            'error': f'missing email sender at {SEND_EMAIL_PY}',
        }
    try:
        result = subprocess.run(
            [sys.executable, SEND_EMAIL_PY, '--to', target, '--subject', subject, '--body', body],
            capture_output=True,
            text=True,
            timeout=min(int(timeout or DEFAULT_LOOM_DELIVERY_TIMEOUT), DEFAULT_LOOM_DELIVERY_TIMEOUT),
            cwd=WORKSPACE,
        )
    except subprocess.TimeoutExpired:
        return {
            'channel': 'email',
            'target': target,
            'ok': False,
            'sent_at': sent_at,
            'error': 'email delivery timed out',
        }
    except Exception as exc:
        return {
            'channel': 'email',
            'target': target,
            'ok': False,
            'sent_at': sent_at,
            'error': str(exc),
        }
    if result.returncode == 0:
        return {
            'channel': 'email',
            'target': target,
            'ok': True,
            'sent_at': sent_at,
            'receipt': (result.stdout or '').strip(),
        }
    return {
        'channel': 'email',
        'target': target,
        'ok': False,
        'sent_at': sent_at,
        'error': ((result.stderr or result.stdout or '').strip()[:500] or 'email delivery failed'),
    }


def _deliver_subscription_artifact(job, artifact, *, timeout):
    body = f"{artifact.get('delivery_title', 'Meridian Intelligence brief')}\n\n{artifact.get('brief_text', '').strip()}".strip()
    subject = artifact.get('delivery_title', 'Meridian Intelligence brief')
    dispatches = []
    telegram_dispatch = _dispatch_telegram_delivery(job.get('telegram_id', ''), body, timeout=timeout)
    if telegram_dispatch is not None:
        dispatches.append(telegram_dispatch)
    email_dispatch = _dispatch_email_delivery(job.get('email', ''), subject, body, timeout=timeout)
    if email_dispatch is not None:
        dispatches.append(email_dispatch)
    successful = [dispatch for dispatch in dispatches if dispatch.get('ok')]
    if successful:
        primary = successful[0]
        return {
            'ok': True,
            'delivery_status': 'delivered',
            'dispatches': dispatches,
            'delivery_channel': primary.get('channel', ''),
            'delivery_target': primary.get('target', ''),
            'delivered_at': primary.get('sent_at', ''),
            'error': '',
        }
    if dispatches:
        errors = '; '.join(
            dispatch.get('error', '')
            for dispatch in dispatches
            if dispatch.get('error')
        )
        return {
            'ok': False,
            'delivery_status': 'dispatch_failed',
            'dispatches': dispatches,
            'delivery_channel': '',
            'delivery_target': '',
            'delivered_at': '',
            'error': errors or 'No delivery channel succeeded',
        }
    return {
        'ok': False,
        'delivery_status': 'artifact_ready',
        'dispatches': [],
        'delivery_channel': '',
        'delivery_target': '',
        'delivered_at': '',
        'error': 'No delivery channel is configured for this subscription',
    }


def _find_subscription_record(payload, subscription_id):
    subscription_id = (subscription_id or '').strip()
    if not subscription_id:
        return '', -1, None
    for telegram_id, records in payload.get('subscribers', {}).items():
        for index, record in enumerate(records):
            if (record.get('id') or '').strip() == subscription_id:
                return telegram_id, index, record
    return '', -1, None


def _persist_subscription_delivery_state(payload, job, artifact, dispatch, *, run_id='', finished_at=''):
    telegram_id, index, record = _find_subscription_record(payload, job.get('subscription_id', ''))
    if record is None:
        return None
    updated = dict(record)
    attempted_at = (finished_at or now_ts()).strip()
    updated['latest_delivery_ref'] = (job.get('delivery_ref') or '').strip()
    updated['latest_delivery_run_id'] = (run_id or '').strip()
    updated['latest_delivery_job_id'] = (job.get('job_id') or '').strip()
    updated['latest_delivery_status'] = (dispatch.get('delivery_status') or '').strip()
    updated['latest_delivery_runtime'] = 'loom'
    updated['latest_delivery_channel'] = (dispatch.get('delivery_channel') or '').strip()
    updated['latest_delivery_target'] = (dispatch.get('delivery_target') or '').strip()
    updated['latest_delivery_attempted_at'] = attempted_at
    updated['latest_delivery_date'] = (artifact.get('brief_date') or '').strip()
    updated['latest_delivery_preview'] = (artifact.get('brief_preview') or '').strip()
    updated['latest_delivery_result_path'] = (artifact.get('result_path') or '').strip()
    updated['latest_delivery_artifact'] = {
        'artifact_type': artifact.get('artifact_type', ''),
        'delivery_title': artifact.get('delivery_title', ''),
        'brief_date': artifact.get('brief_date', ''),
        'brief_preview': artifact.get('brief_preview', ''),
        'result_path': artifact.get('result_path', ''),
    }
    if dispatch.get('ok'):
        updated['last_delivered_at'] = attempted_at
    payload['subscribers'][telegram_id][index] = updated
    return updated


def _normalize_loom_delivery_run(run, org_id=None, existing=None):
    run = dict(run or {})
    existing = dict(existing or {})
    job_id = (run.get('job_id') or existing.get('job_id') or '').strip()
    if not job_id:
        job_id = (run.get('job_id') or existing.get('job_id') or f'loom_{uuid.uuid4().hex[:12]}').strip()
    run_id = (run.get('run_id') or existing.get('run_id') or '').strip()
    if not run_id:
        run_id = f'ldr_{uuid.uuid4().hex[:12]}'

    record = dict(existing)
    record['run_id'] = run_id
    record['job_id'] = job_id
    record['subscription_id'] = (run.get('subscription_id') or existing.get('subscription_id') or '').strip()
    record['preview_id'] = (run.get('preview_id') or existing.get('preview_id') or '').strip()
    record['telegram_id'] = (run.get('telegram_id') or existing.get('telegram_id') or '').strip()
    record['email'] = (run.get('email') or existing.get('email') or '').strip()
    record['plan'] = (run.get('plan') or existing.get('plan') or '').strip()
    record['capability_name'] = (run.get('capability_name') or existing.get('capability_name') or '').strip()
    record['state'] = (run.get('state') or existing.get('state') or 'queued').strip() or 'queued'
    record['delivery_status'] = (run.get('delivery_status') or existing.get('delivery_status') or record['state']).strip() or record['state']
    record['delivered'] = bool(run.get('delivered', existing.get('delivered', False)))
    record['attempts'] = int(run.get('attempts', existing.get('attempts', 0)) or 0)
    record['queued_at'] = (run.get('queued_at') or existing.get('queued_at') or '').strip()
    record['started_at'] = (run.get('started_at') or existing.get('started_at') or '').strip()
    record['finished_at'] = (run.get('finished_at') or existing.get('finished_at') or '').strip()
    record['executed_at'] = (run.get('executed_at') or existing.get('executed_at') or '').strip()
    record['error'] = (run.get('error') or existing.get('error') or '').strip()
    record['result_path'] = (run.get('result_path') or existing.get('result_path') or '').strip()
    record['delivery_ref'] = (run.get('delivery_ref') or existing.get('delivery_ref') or '').strip()
    record['recorded_by'] = (run.get('recorded_by') or existing.get('recorded_by') or '').strip()
    record['dispatch_channel'] = (run.get('dispatch_channel') or existing.get('dispatch_channel') or '').strip()
    record['dispatch_target'] = (run.get('dispatch_target') or existing.get('dispatch_target') or '').strip()
    record['brief_preview'] = (run.get('brief_preview') or existing.get('brief_preview') or '').strip()
    record['brief_date'] = (run.get('brief_date') or existing.get('brief_date') or '').strip()
    record['submit'] = dict(run.get('submit') or existing.get('submit') or {})
    record['snapshot'] = dict(run.get('snapshot') or existing.get('snapshot') or {})
    record['worker_result'] = dict(run.get('worker_result') or existing.get('worker_result') or {})
    record['execution_refs'] = dict(run.get('execution_refs') or existing.get('execution_refs') or {})
    record['delivery_artifact'] = dict(run.get('delivery_artifact') or existing.get('delivery_artifact') or {})
    record['dispatches'] = [
        dict(item)
        for item in (run.get('dispatches') or existing.get('dispatches') or [])
        if isinstance(item, dict)
    ]
    record['created_at'] = (run.get('created_at') or existing.get('created_at') or now_ts()).strip()
    record['updated_at'] = now_ts()
    return record


def _loom_delivery_preflight(capability_name):
    preflight = shared_loom_capability_preflight(
        _loom_runtime_context(),
        capability_name,
        route='subscription_delivery',
        runner=subprocess.run,
        transport_allowlist=('http', 'socket+http', ''),
    )
    if not capability_name:
        preflight['errors'] = ['Loom subscription delivery capability is not configured']
        preflight['ok'] = False
    return preflight


def _run_loom_delivery_capability(capability_name, payload, timeout):
    result = shared_run_loom_capability(
        _loom_runtime_context(),
        capability_name,
        payload,
        timeout,
        runner=subprocess.run,
        sleeper=time.sleep,
        result_loader=_load_json_file,
    )
    if result.get('ok') and result.get('job_id'):
        result['result_path'] = os.path.join(_loom_root(), 'state', 'runtime', 'jobs', result['job_id'], 'result.json')
    if not capability_name:
        result['error'] = 'Loom subscription delivery capability is not configured'
    return result


def _normalize_loom_delivery_job(job, org_id=None, existing=None):
    job = dict(job or {})
    existing = dict(existing or {})
    subscription_id = (job.get('subscription_id') or existing.get('subscription_id') or '').strip()
    preview_id = (job.get('preview_id') or existing.get('preview_id') or '').strip()
    telegram_id = (job.get('telegram_id') or existing.get('telegram_id') or '').strip()
    job_id = (job.get('job_id') or existing.get('job_id') or '').strip()
    if not job_id:
        if subscription_id:
            job_id = f'loom_{subscription_id}'
        elif preview_id:
            job_id = f'loom_{preview_id}'
        else:
            job_id = f'loom_{uuid.uuid4().hex[:12]}'

    record = dict(existing)
    record['job_id'] = job_id
    record['subscription_id'] = subscription_id
    record['preview_id'] = preview_id
    record['telegram_id'] = telegram_id
    record['email'] = (job.get('email') or existing.get('email') or '').strip()
    record['name'] = (job.get('name') or existing.get('name') or '').strip()
    record['company'] = (job.get('company') or existing.get('company') or '').strip()
    record['requested_cadence'] = (job.get('requested_cadence') or existing.get('requested_cadence') or '').strip()
    record['requested_offer'] = (job.get('requested_offer') or existing.get('requested_offer') or '').strip()
    record['topics'] = _normalize_text_list(job.get('topics') or existing.get('topics'))
    record['competitors'] = _normalize_text_list(job.get('competitors') or existing.get('competitors'))
    record['plan'] = (job.get('plan') or existing.get('plan') or '').strip()
    record['delivery_runtime'] = (job.get('delivery_runtime') or existing.get('delivery_runtime') or 'loom').strip() or 'loom'
    record['delivery_channel'] = (job.get('delivery_channel') or existing.get('delivery_channel') or 'loom').strip() or 'loom'
    record['job_type'] = (job.get('job_type') or existing.get('job_type') or 'subscription_loom_delivery').strip() or 'subscription_loom_delivery'
    record['state'] = (job.get('state') or existing.get('state') or 'queued').strip() or 'queued'
    record['delivery_status'] = (job.get('delivery_status') or existing.get('delivery_status') or record['state']).strip() or record['state']
    record['attempts'] = int(job.get('attempts', existing.get('attempts', 0)) or 0)
    record['queued_at'] = (job.get('queued_at') or existing.get('queued_at') or now_ts()).strip()
    record['queued_by'] = (job.get('queued_by') or existing.get('queued_by') or '').strip()
    record['claimed_at'] = (job.get('claimed_at') or existing.get('claimed_at') or '').strip()
    record['claimed_by'] = (job.get('claimed_by') or existing.get('claimed_by') or '').strip()
    record['running_at'] = (job.get('running_at') or existing.get('running_at') or '').strip()
    record['blocked_at'] = (job.get('blocked_at') or existing.get('blocked_at') or '').strip()
    record['executed_at'] = (job.get('executed_at') or existing.get('executed_at') or '').strip()
    record['completed_at'] = (job.get('completed_at') or existing.get('completed_at') or '').strip()
    record['completed_by'] = (job.get('completed_by') or existing.get('completed_by') or '').strip()
    record['delivery_ref'] = (job.get('delivery_ref') or existing.get('delivery_ref') or '').strip()
    record['dispatch_channel'] = (job.get('dispatch_channel') or existing.get('dispatch_channel') or '').strip()
    record['dispatch_target'] = (job.get('dispatch_target') or existing.get('dispatch_target') or '').strip()
    record['brief_preview'] = (job.get('brief_preview') or existing.get('brief_preview') or '').strip()
    record['brief_date'] = (job.get('brief_date') or existing.get('brief_date') or '').strip()
    record['result_path'] = (job.get('result_path') or existing.get('result_path') or '').strip()
    record['notes'] = (job.get('notes') or existing.get('notes') or '').strip()
    record['subscription_status'] = (job.get('subscription_status') or existing.get('subscription_status') or '').strip()
    record['payment_verified'] = bool(job.get('payment_verified', existing.get('payment_verified', False)))
    record['payment_ref'] = (job.get('payment_ref') or existing.get('payment_ref') or '').strip()
    record['blocked_reason'] = (job.get('blocked_reason') or existing.get('blocked_reason') or '').strip()
    record['error'] = (job.get('error') or existing.get('error') or '').strip()
    record['execution_refs'] = dict(job.get('execution_refs') or existing.get('execution_refs') or {})
    record['delivery_artifact'] = dict(job.get('delivery_artifact') or existing.get('delivery_artifact') or {})
    record['dispatches'] = [
        dict(item)
        for item in (job.get('dispatches') or existing.get('dispatches') or [])
        if isinstance(item, dict)
    ]
    record['created_at'] = (job.get('created_at') or existing.get('created_at') or now_ts()).strip()
    record['updated_at'] = now_ts()
    return record


def queue_loom_delivery(subscription, *, preview=None, org_id=None, actor=''):
    subscription = dict(subscription or {})
    preview = dict(preview or {})
    subscription_id = (subscription.get('id') or '').strip()
    if not subscription_id:
        raise ValueError('subscription_id is required')

    payload = load_subscriptions(org_id)
    jobs = payload.setdefault('loom_delivery_jobs', {})
    job_id = f'loom_{subscription_id}'
    existing = jobs.get(job_id)
    job = _normalize_loom_delivery_job({
        'job_id': job_id,
        'subscription_id': subscription_id,
        'preview_id': (preview.get('preview_id') or subscription.get('activated_from_preview_id') or '').strip(),
        'telegram_id': (subscription.get('telegram_id') or '').strip(),
        'email': (subscription.get('email') or preview.get('email') or '').strip(),
        'name': (preview.get('name') or '').strip(),
        'company': (preview.get('company') or '').strip(),
        'requested_cadence': (preview.get('requested_cadence') or '').strip(),
        'requested_offer': (preview.get('requested_offer') or '').strip(),
        'topics': _normalize_text_list(preview.get('topics')),
        'competitors': _normalize_text_list(preview.get('competitors')),
        'plan': subscription.get('plan', ''),
        'delivery_runtime': 'loom',
        'delivery_channel': 'loom',
        'job_type': 'subscription_loom_delivery',
        'state': 'queued',
        'delivery_status': 'queued',
        'queued_at': now_ts(),
        'queued_by': actor or '',
        'payment_verified': bool(subscription.get('payment_verified', False)),
        'payment_ref': subscription.get('payment_ref', ''),
        'subscription_status': subscription.get('status', ''),
        'notes': 'Queued for Loom delivery after subscription activation',
    }, org_id, existing=existing)
    jobs[job_id] = job
    save_subscriptions(payload, org_id)
    return {
        'job_id': job_id,
        'delivery_job': job,
    }


def run_loom_delivery_job(job_id, *, org_id=None, actor='', timeout=120, capability_name=None):
    job_id = (job_id or '').strip()
    if not job_id:
        raise ValueError('job_id is required')

    payload = load_subscriptions(org_id)
    jobs = payload.setdefault('loom_delivery_jobs', {})
    job = jobs.get(job_id)
    if not job:
        raise LookupError(f'Loom delivery job not found: {job_id}')

    job = _normalize_loom_delivery_job(job, org_id, existing=job)
    capability_name = (capability_name or _loom_delivery_capability()).strip()
    now = now_ts()
    run_record = {
        'run_id': f'ldr_{uuid.uuid4().hex[:12]}',
        'job_id': job_id,
        'subscription_id': job.get('subscription_id', ''),
        'preview_id': job.get('preview_id', ''),
        'telegram_id': job.get('telegram_id', ''),
        'email': job.get('email', ''),
        'plan': job.get('plan', ''),
        'capability_name': capability_name,
        'queued_at': job.get('queued_at', now),
        'started_at': now,
        'attempts': int(job.get('attempts', 0) or 0) + 1,
        'recorded_by': actor or '',
        'state': 'running',
        'delivery_status': 'running',
        'delivered': False,
    }

    _telegram_id, _sub_index, subscription_record = _find_subscription_record(payload, job.get('subscription_id', ''))
    if subscription_record:
        job['telegram_id'] = (job.get('telegram_id') or subscription_record.get('telegram_id') or _telegram_id or '').strip()
        job['email'] = (job.get('email') or subscription_record.get('email') or '').strip()

    if not capability_name:
        run_record.update({
            'state': 'blocked',
            'delivery_status': 'blocked',
            'error': 'Loom subscription delivery capability is not configured',
            'finished_at': now,
        })
        job.update({
            'state': 'ready',
            'delivery_status': 'blocked',
            'attempts': run_record['attempts'],
            'blocked_reason': run_record['error'],
            'updated_at': now_ts(),
            'execution_refs': dict(job.get('execution_refs') or {}),
        })
        payload['loom_delivery_runs'] = list(payload.get('loom_delivery_runs', [])) + [_normalize_loom_delivery_run(run_record, org_id)]
        jobs[job_id] = job
        save_subscriptions(payload, org_id)
        return {
            'job_id': job_id,
            'delivery_job': job,
            'run': _normalize_loom_delivery_run(run_record, org_id),
        }

    preflight = _loom_delivery_preflight(capability_name)
    if not preflight.get('ok'):
        run_record.update({
            'state': 'blocked',
            'delivery_status': 'blocked',
            'error': '; '.join(preflight.get('errors') or ['loom delivery preflight failed']),
            'finished_at': now,
            'execution_refs': {'preflight': preflight},
        })
        job.update({
            'state': 'blocked',
            'delivery_status': 'blocked',
            'blocked_reason': run_record['error'],
            'blocked_at': now,
            'attempts': run_record['attempts'],
            'execution_refs': {'preflight': preflight},
            'updated_at': now_ts(),
        })
        payload['loom_delivery_runs'] = list(payload.get('loom_delivery_runs', [])) + [_normalize_loom_delivery_run(run_record, org_id)]
        jobs[job_id] = job
        save_subscriptions(payload, org_id)
        return {
            'job_id': job_id,
            'delivery_job': job,
            'run': _normalize_loom_delivery_run(run_record, org_id),
            'preflight': preflight,
        }

    job.update({
        'state': 'executing',
        'delivery_status': 'running',
        'running_at': now,
        'attempts': run_record['attempts'],
        'executing_by': actor or '',
        'updated_at': now_ts(),
        'execution_refs': dict(job.get('execution_refs') or {}),
    })
    jobs[job_id] = job
    save_subscriptions(payload, org_id)

    run_payload = _subscription_delivery_payload(job, subscription=subscription_record, actor=actor)
    execution = _run_loom_delivery_capability(capability_name, run_payload, timeout=timeout)
    finished_at = now_ts()
    artifact = {}
    dispatch = {
        'ok': False,
        'delivery_status': 'blocked',
        'dispatches': [],
        'delivery_channel': '',
        'delivery_target': '',
        'delivered_at': '',
        'error': execution.get('error', ''),
    }

    if execution.get('ok'):
        artifact_result = _extract_loom_delivery_artifact(execution.get('worker_result', {}) or {}, job=job, execution=execution)
        artifact = dict(artifact_result.get('artifact') or {})
        if artifact_result.get('ok'):
            dispatch = _deliver_subscription_artifact(job, artifact, timeout=timeout)
        else:
            dispatch = {
                'ok': False,
                'delivery_status': 'artifact_missing',
                'dispatches': [],
                'delivery_channel': '',
                'delivery_target': '',
                'delivered_at': '',
                'error': artifact_result.get('error', 'Loom execution completed without a deliverable brief body'),
            }

        execution_refs = {
            'capability_name': capability_name,
            'submit': execution.get('submit', {}),
            'snapshot': execution.get('snapshot', {}),
            'worker_result': execution.get('worker_result', {}),
            'result_path': execution.get('result_path', ''),
            'dispatches': list(dispatch.get('dispatches') or []),
        }
        job.update({
            'state': 'executed' if dispatch.get('ok') else 'blocked',
            'delivery_status': dispatch.get('delivery_status', 'blocked'),
            'delivered_at': dispatch.get('delivered_at', ''),
            'executed_at': finished_at,
            'delivery_ref': execution.get('job_id', job_id),
            'completed_at': finished_at if dispatch.get('ok') else '',
            'completed_by': (actor or '') if dispatch.get('ok') else '',
            'dispatch_channel': dispatch.get('delivery_channel', ''),
            'dispatch_target': dispatch.get('delivery_target', ''),
            'brief_preview': artifact.get('brief_preview', ''),
            'brief_date': artifact.get('brief_date', ''),
            'result_path': execution.get('result_path', ''),
            'delivery_artifact': artifact,
            'dispatches': list(dispatch.get('dispatches') or []),
            'updated_at': now_ts(),
            'error': dispatch.get('error', ''),
            'blocked_reason': dispatch.get('error', '') if not dispatch.get('ok') else '',
            'blocked_at': finished_at if not dispatch.get('ok') else '',
            'execution_refs': execution_refs,
        })
        run_record.update({
            'state': 'executed' if dispatch.get('ok') else 'blocked',
            'delivery_status': dispatch.get('delivery_status', 'blocked'),
            'delivered': bool(dispatch.get('ok')),
            'finished_at': finished_at,
            'executed_at': finished_at,
            'delivery_ref': job.get('delivery_ref', execution.get('job_id', job_id)),
            'error': dispatch.get('error', ''),
            'submit': execution.get('submit', {}),
            'snapshot': execution.get('snapshot', {}),
            'worker_result': execution.get('worker_result', {}),
            'result_path': execution.get('result_path', ''),
            'execution_refs': execution_refs,
            'dispatch_channel': dispatch.get('delivery_channel', ''),
            'dispatch_target': dispatch.get('delivery_target', ''),
            'brief_preview': artifact.get('brief_preview', ''),
            'brief_date': artifact.get('brief_date', ''),
            'delivery_artifact': artifact,
            'dispatches': list(dispatch.get('dispatches') or []),
        })
        _persist_subscription_delivery_state(
            payload,
            job,
            artifact,
            dispatch,
            run_id=run_record['run_id'],
            finished_at=finished_at,
        )
        if dispatch.get('ok'):
            payload.setdefault('delivery_log', []).append({
                'telegram_id': job.get('telegram_id', ''),
                'email': job.get('email', ''),
                'product': f"subscription:{job.get('plan', '') or 'delivery'}",
                'delivered_at': finished_at,
                'recorded_by': actor or '',
                'delivery_ref': job['delivery_ref'],
                'subscription_id': job.get('subscription_id', ''),
                'preview_id': job.get('preview_id', ''),
                'job_id': job_id,
                'run_id': run_record['run_id'],
                'delivery_status': 'delivered',
                'delivery_runtime': 'loom',
                'capability_name': capability_name,
                'brief_date': artifact.get('brief_date', ''),
                'brief_preview': artifact.get('brief_preview', ''),
                'dispatch_channel': dispatch.get('delivery_channel', ''),
                'dispatch_target': dispatch.get('delivery_target', ''),
                'result_path': execution.get('result_path', ''),
            })
            if len(payload['delivery_log']) > 500:
                payload['delivery_log'] = payload['delivery_log'][-500:]
    else:
        execution_refs = {
            'capability_name': capability_name,
            'submit': execution.get('submit', {}),
            'snapshot': execution.get('snapshot', {}),
        }
        job.update({
            'state': 'blocked',
            'delivery_status': 'blocked',
            'blocked_reason': execution.get('error', 'loom delivery failed'),
            'finished_at': finished_at,
            'error': execution.get('error', ''),
            'updated_at': now_ts(),
            'execution_refs': execution_refs,
        })
        run_record.update({
            'state': 'blocked',
            'delivery_status': 'blocked',
            'finished_at': finished_at,
            'error': execution.get('error', 'loom delivery failed'),
            'submit': execution.get('submit', {}),
            'snapshot': execution.get('snapshot', {}),
            'execution_refs': execution_refs,
        })

    normalized_run = _normalize_loom_delivery_run(run_record, org_id)
    payload['loom_delivery_runs'] = list(payload.get('loom_delivery_runs', [])) + [normalized_run]
    jobs[job_id] = _normalize_loom_delivery_job(job, org_id, existing=job)
    save_subscriptions(payload, org_id)
    return {
        'job_id': job_id,
        'delivery_job': jobs[job_id],
        'run': normalized_run,
        'execution': execution,
    }


def run_pending_loom_delivery_jobs(org_id=None, *, actor='', timeout=120, limit=50, capability_name=None):
    payload = load_subscriptions(org_id)
    jobs = list(payload.get('loom_delivery_jobs', {}).keys())
    queued_job_ids = [
        job_id for job_id in jobs
        if (payload.get('loom_delivery_jobs', {}).get(job_id, {}).get('state') or 'queued') in {'queued', 'ready'}
    ]
    try:
        limit = max(int(limit), 0)
    except (TypeError, ValueError):
        limit = 50
    results = []
    for job_id in queued_job_ids[:limit] if limit else []:
        results.append(
            run_loom_delivery_job(
                job_id,
                org_id=org_id,
                actor=actor,
                timeout=timeout,
                capability_name=capability_name,
            )
        )
    return {
        'bound_org_id': (org_id or '').strip(),
        'attempted_count': len(results),
        'results': results,
    }


def activate_subscription_from_preview(preview, *, telegram_id=None, plan=None,
                                       payment_method='captured', payment_ref=None,
                                       payment_evidence=None, org_id=None, actor='', timeout=120):
    preview = dict(preview or {})
    preview_id = (preview.get('preview_id') or '').strip()
    if not preview_id:
        raise ValueError('preview_id is required')
    plan_name = (plan or '').strip() or _default_plan_from_preview(preview)
    if not plan_name:
        raise ValueError('plan is required to activate a subscription from preview')
    if plan_name not in PLANS:
        raise ValueError(f"unknown plan '{plan_name}'. Available: {', '.join(sorted(PLANS.keys()))}")

    email = str(preview.get('email') or '').strip().lower()
    delivery_telegram_id = _delivery_telegram_target(preview, explicit_telegram_id=telegram_id)
    subscriber_key = delivery_telegram_id or (f'email:{email}' if email else '')
    if not subscriber_key:
        raise ValueError('telegram_id or email is required to activate a subscription from preview')

    payment_ref = (payment_ref or '').strip()
    confirm_payment = plan_name != 'trial'
    if confirm_payment and not payment_ref:
        raise ValueError('payment_ref is required to activate a paid subscription from preview')

    result = create_subscription(
        subscriber_key,
        plan=plan_name,
        payment_method=payment_method or ('trial' if plan_name == 'trial' else 'captured'),
        payment_ref=payment_ref,
        payment_evidence=payment_evidence,
        confirm_payment=confirm_payment,
        trial=(plan_name == 'trial'),
        email=email or None,
        org_id=org_id,
        actor=actor,
    )

    payload = load_subscriptions(org_id)
    subscription = result['subscription']
    records = payload.get('subscribers', {}).get(subscriber_key, [])
    for index, record in enumerate(records):
        if record.get('id') == subscription['id']:
            record['activated_from_preview_id'] = preview_id
            record['activation_state'] = 'captured'
            record['activation_source'] = 'subscription_preview_queue'
            record['subscription_source'] = 'subscription_preview_queue'
            record['telegram_id'] = delivery_telegram_id
            record['telegram_handle'] = str(preview.get('telegram_handle') or '').strip()
            record['subscriber_id'] = subscriber_key
            record['created_for'] = subscriber_key
            record['preview_id'] = preview_id
            record['created_from_preview'] = True
            record['activated_at'] = now_ts()
            record['activated_by'] = actor or ''
            record['contact_channel'] = 'telegram' if delivery_telegram_id else 'email'
            if email:
                record['email'] = email
            records[index] = record
            subscription = record
            result['subscription'] = record
            break
    payload['subscribers'][subscriber_key] = records
    save_subscriptions(payload, org_id)

    delivery_job = queue_loom_delivery(subscription, preview=preview, org_id=org_id, actor=actor)
    delivery_run = run_loom_delivery_job(
        delivery_job['job_id'],
        org_id=org_id,
        actor=actor,
        timeout=timeout,
    )
    payload = load_subscriptions(org_id)
    delivery_job = payload.get('loom_delivery_jobs', {}).get(delivery_job['job_id'], delivery_job)
    return {
        'preview_id': preview_id,
        'subscriber_id': subscriber_key,
        'telegram_id': delivery_telegram_id,
        'email': email,
        'subscription': subscription,
        'delivery_job': delivery_job,
        'delivery_run': delivery_run['run'],
        'delivery_execution': delivery_run.get('execution', {}),
        'delivery_artifact': dict(delivery_run['run'].get('delivery_artifact') or {}),
        'delivery_dispatches': list(delivery_run['run'].get('dispatches') or []),
    }


def capture_subscription_from_preview(preview, *, telegram_id=None, plan=None,
                                      payment_method='captured', payment_ref=None,
                                      payment_evidence=None, org_id=None, actor='', timeout=120):
    payment_evidence = _coerce_payment_evidence(payment_evidence)
    if not payment_evidence:
        raise ValueError('payment_evidence is required for customer-initiated checkout capture')
    payment_ref = (payment_ref or '').strip()
    if not payment_ref:
        raise ValueError('payment_ref is required for customer-initiated checkout capture')
    return activate_subscription_from_preview(
        preview,
        telegram_id=telegram_id,
        plan=plan,
        payment_method=payment_method,
        payment_ref=payment_ref,
        payment_evidence=payment_evidence,
        org_id=org_id,
        actor=actor,
        timeout=timeout,
    )


def create_draft_subscription_from_preview(preview, *, org_id=None, actor=''):
    preview = dict(preview or {})
    preview_id = (preview.get('preview_id') or '').strip()
    if not preview_id:
        raise ValueError('preview_id is required')

    subscription = {
        'draft_id': f"draft_{preview_id}",
        'preview_id': preview_id,
        'pilot_request_id': (preview.get('pilot_request_id') or '').strip(),
        'source_preview_state': (preview.get('state') or preview.get('preview_state') or '').strip(),
        'source_preview_truth_source': (preview.get('preview_truth_source') or '').strip(),
        'requested_offer': (preview.get('requested_offer') or '').strip(),
        'requested_cadence': (preview.get('requested_cadence') or '').strip(),
        'name': (preview.get('name') or '').strip(),
        'company': (preview.get('company') or '').strip(),
        'email': (preview.get('email') or '').strip(),
        'telegram_handle': (preview.get('telegram_handle') or '').strip(),
        'plan_options': list(preview.get('plan_options') or []),
        'plan': '',
        'price_usd': 0.0,
        'status': 'draft',
        'drafted_at': now_ts(),
        'drafted_by': actor or '',
        'draft_note': (preview.get('review_note') or '').strip(),
        'subscription_source': 'subscription_preview_queue',
        'subscription_status': 'draft',
        'payment_method': 'draft',
        'payment_ref': '',
        'payment_verified': False,
        'payment_verified_at': '',
        'payment_evidence': {},
        'created_at': now_ts(),
        'updated_at': now_ts(),
    }

    payload = load_subscriptions(org_id)
    drafts = payload.setdefault('draft_subscriptions', {})
    drafts[subscription['draft_id']] = _normalize_draft_subscription(
        subscription,
        org_id,
        existing=drafts.get(subscription['draft_id'], {}),
    )
    save_subscriptions(payload, org_id)
    return {
        'preview_id': preview_id,
        'draft_subscription': drafts[subscription['draft_id']],
    }


def active_delivery_targets(org_id=None, *, external_only=False):
    payload = load_subscriptions(org_id)
    internal_ids = {
        str(value) for value in payload.get('_meta', {}).get('internal_test_ids', [])
    }
    targets = set()
    for telegram_id, records in payload.get('subscribers', {}).items():
        tid = str(telegram_id)
        if external_only and tid in internal_ids:
            continue
        for record in records:
            if _subscription_delivery_eligible(record, org_id=org_id):
                targets.add(tid)
                break
    return sorted(targets)


def start_trial(telegram_id, *, email='', org_id=None, actor=''):
    return create_subscription(
        telegram_id,
        plan='trial',
        trial=True,
        email=email,
        org_id=org_id,
        actor=actor,
    )['subscription']


def add_subscription(telegram_id, plan='trial', *, duration_days=None,
                     payment_method=None, payment_ref=None,
                     payment_evidence=None,
                     confirm_payment=False, trial=False, email=None,
                     org_id=None, actor=''):
    payload = load_subscriptions(org_id)
    tid = str(telegram_id or '').strip()
    if not tid:
        raise ValueError('telegram_id is required')
    plan_name = 'trial' if trial else (plan or 'trial')
    if plan_name not in PLANS:
        raise ValueError(
            f"unknown plan '{plan_name}'. Available: {', '.join(sorted(PLANS.keys()))}"
        )

    if plan_name == 'trial':
        existing = payload.get('subscribers', {}).get(tid, [])
        for record in existing:
            if record.get('plan') == 'trial':
                raise ValueError(f'telegram:{tid} already used a trial subscription')

    plan_info = PLANS[plan_name]
    duration = duration_days if duration_days is not None else plan_info['duration_days']
    expires = None
    if duration > 0:
        expires = (now_dt() + datetime.timedelta(days=duration)).strftime('%Y-%m-%dT%H:%M:%SZ')

    payment_ref = (payment_ref or '').strip()
    payment_verified = plan_name == 'trial'
    payment_verified_at = now_ts() if plan_name == 'trial' else ''
    payment_evidence = {'type': 'trial'} if plan_name == 'trial' else {}
    if plan_name != 'trial' and bool(confirm_payment):
        evidence = _require_payment_evidence(
            payment_ref,
            plan_info['price_usd'],
            payment_evidence=payment_evidence,
            org_id=org_id,
        )
        payment_verified = True
        payment_verified_at = now_ts()
        payment_evidence = {
            'order_id': evidence.get('order_id', ''),
            'payment_key': evidence.get('payment_key', ''),
            'payment_ref': evidence.get('payment_ref', payment_ref),
            'tx_hash': evidence.get('tx_hash', ''),
            'amount_usd': float(evidence.get('amount', 0.0) or 0.0),
        }

    subscription = {
        'id': str(uuid.uuid4())[:8],
        'plan': plan_name,
        'price_usd': plan_info['price_usd'],
        'started_at': now_ts(),
        'expires_at': expires,
        'status': 'active',
        'payment_method': payment_method or ('trial' if plan_name == 'trial' else 'manual'),
        'payment_ref': payment_ref,
        'payment_verified': payment_verified,
        'payment_verified_at': payment_verified_at,
        'payment_evidence': payment_evidence,
        'email': email or '',
        'created_by': actor or '',
    }
    payload.setdefault('subscribers', {}).setdefault(tid, []).append(subscription)
    save_subscriptions(payload, org_id)
    return {
        'telegram_id': tid,
        'subscription': subscription,
    }


def create_subscription(telegram_id, plan='trial', *, duration_days=None,
                        payment_method=None, payment_ref=None, payment_evidence=None,
                        confirm_payment=False, trial=False, email=None,
                        org_id=None, actor=''):
    return add_subscription(
        telegram_id,
        plan=plan,
        duration_days=duration_days,
        payment_method=payment_method,
        payment_ref=payment_ref,
        payment_evidence=payment_evidence,
        confirm_payment=confirm_payment,
        trial=trial,
        email=email,
        org_id=org_id,
        actor=actor,
    )


def convert_trial_subscription(telegram_id, plan, *, payment_method=None,
                               payment_ref=None, payment_evidence=None, confirm_payment=False,
                               email=None, org_id=None, actor=''):
    tid = str(telegram_id or '').strip()
    if not tid:
        raise ValueError('telegram_id is required')
    if plan not in PLANS or plan == 'trial':
        raise ValueError(f"invalid conversion plan '{plan}'. Use a paid plan.")

    payload = load_subscriptions(org_id)
    if tid not in payload.get('subscribers', {}):
        raise LookupError(f'No subscriptions for telegram:{tid}')

    had_trial = False
    for sub in payload['subscribers'][tid]:
        if sub.get('plan') == 'trial' and sub.get('status') == 'active':
            had_trial = True
            sub['status'] = 'converted'
            sub['converted_at'] = now_ts()
            sub['converted_by'] = actor or ''
            break
    if not had_trial:
        raise LookupError(f'No active trial found for telegram:{tid}')

    save_subscriptions(payload, org_id)
    result = add_subscription(
        tid,
        plan=plan,
        payment_method=payment_method,
        payment_ref=payment_ref,
        payment_evidence=payment_evidence,
        confirm_payment=confirm_payment,
        email=email,
        org_id=org_id,
        actor=actor,
    )
    payload = load_subscriptions(org_id)
    for idx, record in enumerate(payload.get('subscribers', {}).get(tid, [])):
        if record.get('id') == result['subscription']['id']:
            record['converted_from_trial'] = True
            result['subscription'] = record
            payload['subscribers'][tid][idx] = record
            break
    save_subscriptions(payload, org_id)
    return {
        'telegram_id': tid,
        'subscription': result['subscription'],
    }


def check_subscription(telegram_id, *, org_id=None):
    tid = str(telegram_id or '').strip()
    if not tid:
        raise ValueError('telegram_id is required')
    payload = load_subscriptions(org_id)
    records = list(payload.get('subscribers', {}).get(tid, []))
    active = [record for record in records if record.get('status') == 'active']
    latest = records[-1] if records else None
    return {
        'telegram_id': tid,
        'found': bool(records),
        'active': bool(active),
        'eligible_for_delivery': any(
            _subscription_delivery_eligible(record, org_id=org_id)
            for record in active
        ),
        'subscription_count': len(records),
        'active_count': len(active),
        'latest_subscription': latest,
    }


def verify_subscription_payment(telegram_id, *, subscription_id=None,
                                payment_ref=None, payment_evidence=None, org_id=None, actor=''):
    payload = load_subscriptions(org_id)
    tid = str(telegram_id or '').strip()
    if not tid:
        raise ValueError('telegram_id is required')
    if tid not in payload.get('subscribers', {}) or not payload['subscribers'][tid]:
        raise LookupError(f'No subscriptions for telegram:{tid}')

    candidates = [
        sub for sub in payload['subscribers'][tid]
        if sub.get('status') == 'active' and sub.get('plan') != 'trial'
    ]
    if subscription_id:
        candidates = [sub for sub in candidates if sub.get('id') == subscription_id]
    if not candidates:
        raise LookupError(f'No active paid subscription found for telegram:{tid}')

    target = candidates[-1]
    if payment_ref:
        target['payment_ref'] = payment_ref
    _bind_payment_evidence(
        target,
        payment_ref=target.get('payment_ref'),
        payment_evidence=payment_evidence,
        org_id=org_id,
    )
    target['payment_verified_by'] = actor or ''
    save_subscriptions(payload, org_id)
    return {
        'telegram_id': tid,
        'subscription': target,
    }


def set_email(telegram_id, email, *, org_id=None, actor=''):
    payload = load_subscriptions(org_id)
    tid = str(telegram_id).strip()
    if tid not in payload.get('subscribers', {}) or not payload['subscribers'][tid]:
        raise LookupError(f'No subscriptions for telegram:{tid}')
    candidates = [sub for sub in payload['subscribers'][tid] if sub.get('status') == 'active']
    target = candidates[-1] if candidates else payload['subscribers'][tid][-1]
    target['email'] = email
    target['email_updated_at'] = now_ts()
    target['email_updated_by'] = actor or ''
    save_subscriptions(payload, org_id)
    return target


def cancel_active(telegram_id, *, org_id=None, actor=''):
    payload = load_subscriptions(org_id)
    tid = str(telegram_id).strip()
    if tid not in payload.get('subscribers', {}):
        raise LookupError(f'No subscriptions for telegram:{tid}')
    cancelled = 0
    for sub in payload['subscribers'][tid]:
        if sub.get('status') == 'active':
            sub['status'] = 'cancelled'
            sub['cancelled_at'] = now_ts()
            sub['cancelled_by'] = actor or ''
            cancelled += 1
    if cancelled == 0:
        raise ValueError(f'No active subscriptions for telegram:{tid}')
    save_subscriptions(payload, org_id)
    return {'telegram_id': tid, 'cancelled_count': cancelled}


def record_delivery(telegram_id, product, *, brief_date='', org_id=None, actor=''):
    payload = load_subscriptions(org_id)
    entry = {
        'telegram_id': str(telegram_id).strip(),
        'product': (product or '').strip(),
        'delivered_at': now_ts(),
        'recorded_by': actor or '',
    }
    if not entry['telegram_id']:
        raise ValueError('telegram_id is required')
    if not entry['product']:
        raise ValueError('product is required')
    if brief_date:
        entry['brief_date'] = brief_date
    payload.setdefault('delivery_log', []).append(entry)
    if len(payload['delivery_log']) > 500:
        payload['delivery_log'] = payload['delivery_log'][-500:]
    save_subscriptions(payload, org_id)
    return entry


def loom_delivery_queue_snapshot(org_id=None, *, limit=50):
    payload = load_subscriptions(org_id)
    jobs = list(payload.get('loom_delivery_jobs', {}).values())
    jobs = sorted(
        [
            _normalize_loom_delivery_job(job, org_id, existing=job)
            for job in jobs
        ],
        key=lambda job: (
            job.get('queued_at', ''),
            job.get('updated_at', ''),
            job.get('job_id', ''),
        ),
        reverse=True,
    )
    try:
        limit = max(int(limit), 0)
    except (TypeError, ValueError):
        limit = 50
    limited_jobs = jobs[:limit] if limit else []
    state_counts = {
        'queued': 0,
        'claimed': 0,
        'completed': 0,
        'blocked': 0,
    }
    for job in jobs:
        state = job.get('state', 'queued')
        state_counts[state] = state_counts.get(state, 0) + 1
    return {
        'bound_org_id': (org_id or '').strip(),
        'management_mode': 'institution_owned_service',
        'service_scope': 'institution_owned_subscription_service',
        'boundary_name': 'subscriptions',
        'queue_paths': {
            'inspect': '/api/subscriptions/loom-delivery-jobs',
            'activation': '/api/subscriptions/activate-from-preview',
        },
        'summary': {
            'total_jobs': len(jobs),
            'queued_count': state_counts.get('queued', 0),
            'claimed_count': state_counts.get('claimed', 0),
            'completed_count': state_counts.get('completed', 0),
            'blocked_count': state_counts.get('blocked', 0),
        },
        'delivery_jobs': limited_jobs,
        'meta': payload.get('_meta', {}),
    }


def loom_delivery_run_snapshot(org_id=None, *, limit=50):
    payload = load_subscriptions(org_id)
    runs = [
        _normalize_loom_delivery_run(run, org_id, existing=run)
        for run in payload.get('loom_delivery_runs', [])
    ]
    runs = sorted(
        runs,
        key=lambda run: (
            run.get('started_at', ''),
            run.get('finished_at', ''),
            run.get('run_id', ''),
        ),
        reverse=True,
    )
    try:
        limit = max(int(limit), 0)
    except (TypeError, ValueError):
        limit = 50
    limited_runs = runs[:limit] if limit else []
    state_counts = {
        'running': 0,
        'executed': 0,
        'blocked': 0,
        'queued': 0,
    }
    delivered_count = 0
    for run in runs:
        state = run.get('state', 'queued')
        state_counts[state] = state_counts.get(state, 0) + 1
        if run.get('delivered'):
            delivered_count += 1
    return {
        'bound_org_id': (org_id or '').strip(),
        'management_mode': 'institution_owned_service',
        'service_scope': 'institution_owned_subscription_service',
        'boundary_name': 'subscriptions',
        'summary': {
            'total_runs': len(runs),
            'delivered_count': delivered_count,
            'running_count': state_counts.get('running', 0),
            'executed_count': state_counts.get('executed', 0),
            'blocked_count': state_counts.get('blocked', 0),
            'queued_count': state_counts.get('queued', 0),
        },
        'delivery_runs': limited_runs,
        'meta': payload.get('_meta', {}),
    }


def subscription_summary(org_id=None):
    payload = load_subscriptions(org_id)
    rows = list(payload.get('subscribers', {}).values())
    all_subs = [sub for records in rows for sub in records]
    active = [sub for sub in all_subs if sub.get('status') == 'active']
    draft_subscriptions = list(payload.get('draft_subscriptions', {}).values())
    loom_delivery_jobs = list(payload.get('loom_delivery_jobs', {}).values())
    loom_delivery_runs = list(payload.get('loom_delivery_runs', []))
    verified = [
        sub for sub in active
        if sub.get('plan') != 'trial' and sub.get('payment_verified')
    ]
    return {
        'subscriber_count': len(payload.get('subscribers', {})),
        'subscription_count': len(all_subs),
        'active_subscription_count': len(active),
        'draft_subscription_count': len(draft_subscriptions),
        'verified_paid_subscription_count': len(verified),
        'delivery_log_count': len(payload.get('delivery_log', [])),
        'loom_delivery_job_count': len(loom_delivery_jobs),
        'loom_delivery_run_count': len(loom_delivery_runs),
        'executed_loom_delivery_run_count': sum(
            1 for run in loom_delivery_runs if (run.get('state') or '') == 'executed'
        ),
        'queued_loom_delivery_job_count': sum(
            1 for job in loom_delivery_jobs if (job.get('state') or 'queued') == 'queued'
        ),
        'internal_test_id_count': len(payload.get('_meta', {}).get('internal_test_ids', [])),
        'external_target_count': len(active_delivery_targets(org_id, external_only=True)),
    }
