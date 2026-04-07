#!/usr/bin/env python3
"""Workspace-facing snapshots for institution-owned live services."""
import datetime
import importlib.util
import json
import os

from capsule import (
    ensure_accounting_aliases,
    ensure_subscription_aliases,
    ledger_path,
    owner_ledger_path,
    subscriptions_path,
)
import accounting_store
import pilot_intake
import subscription_preview_queue
import subscription_service


PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(PLATFORM_DIR))
LEGACY_SUBSCRIPTIONS_FILE = os.path.join(WORKSPACE, 'company', 'subscriptions.json')
LEGACY_OWNER_LEDGER_FILE = os.path.join(WORKSPACE, 'company', 'owner_ledger.json')
SUBSCRIPTIONS_MUTATION_PATHS = [
    '/api/subscriptions/add',
    '/api/subscriptions/draft-from-preview',
    '/api/subscriptions/activate-from-preview',
    '/api/subscriptions/loom-delivery-jobs/run',
    '/api/subscriptions/convert',
    '/api/subscriptions/verify-payment',
    '/api/subscriptions/set-email',
    '/api/subscriptions/remove',
    '/api/subscriptions/record-delivery',
]
ACCOUNTING_MUTATION_PATHS = [
    '/api/accounting/expense',
    '/api/accounting/reimburse',
    '/api/accounting/draw',
]


if not hasattr(subscription_service, 'loom_delivery_queue_snapshot'):
    _subscription_spec = importlib.util.spec_from_file_location(
        'meridian_workspace_subscription_service',
        os.path.join(PLATFORM_DIR, 'subscription_service.py'),
    )
    _subscription_mod = importlib.util.module_from_spec(_subscription_spec)
    _subscription_spec.loader.exec_module(_subscription_mod)
    subscription_service = _subscription_mod


def _normalize_storage_model(value):
    mapping = {
        'capsule_canonical_with_legacy_symlink': 'capsule_canonical_with_compatibility_alias',
    }
    normalized = mapping.get(str(value or '').strip(), str(value or '').strip())
    return normalized or 'capsule_canonical'


def _normalize_compatibility_mode(value):
    mapping = {
        'legacy_shim': 'compatibility_alias',
        'legacy_symlink': 'compatibility_alias',
    }
    normalized = mapping.get(str(value or '').strip(), str(value or '').strip())
    return normalized or 'compatibility_alias'


def _now():
    return datetime.datetime.utcnow()


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def _save_json(path, payload):
    with open(path, 'w') as f:
        json.dump(payload, f, indent=2)


def _default_subscriptions(org_id=None):
    return {
        'subscribers': {},
        'delivery_log': [],
        'updatedAt': '',
        '_meta': {
            'service_scope': 'institution_owned_subscription_service',
            'bound_org_id': org_id or '',
            'boundary_name': 'subscriptions',
            'identity_model': 'session',
            'storage_model': 'capsule_canonical_with_compatibility_alias',
            'internal_test_ids': [],
        },
    }


def _default_owner(org_id=None):
    return {
        'version': 1,
        'owner': 'Son Nguyen The',
        'created_at': '',
        'capital_contributed_usd': 0.0,
        'expenses_paid_usd': 0.0,
        'reimbursements_received_usd': 0.0,
        'draws_taken_usd': 0.0,
        'entries': [],
        '_meta': {
            'service_scope': 'institution_owned_service',
            'bound_org_id': org_id or '',
            'boundary_name': 'accounting',
            'identity_model': 'session',
            'storage_model': 'capsule_owned_owner_ledger',
        },
    }


def load_subscription_state(org_id=None):
    payload = dict(_default_subscriptions(org_id))
    payload.update(_load_json(subscriptions_path(org_id), payload))
    payload.setdefault('subscribers', {})
    payload.setdefault('delivery_log', [])
    payload.setdefault('_meta', {})
    payload['_meta']['service_scope'] = 'institution_owned_subscription_service'
    payload['_meta']['bound_org_id'] = org_id or payload['_meta'].get('bound_org_id', '')
    payload['_meta']['boundary_name'] = 'subscriptions'
    payload['_meta']['identity_model'] = 'session'
    payload['_meta']['storage_model'] = _normalize_storage_model('capsule_canonical_with_compatibility_alias')
    payload['_meta'].setdefault('internal_test_ids', [])
    return payload


def load_owner_ledger_state(org_id=None):
    payload = dict(_default_owner(org_id))
    payload.update(_load_json(owner_ledger_path(org_id), payload))
    payload.setdefault('entries', [])
    payload.setdefault('_meta', {})
    payload['_meta']['service_scope'] = 'institution_owned_service'
    payload['_meta']['bound_org_id'] = org_id or payload['_meta'].get('bound_org_id', '')
    payload['_meta']['boundary_name'] = 'accounting'
    payload['_meta']['identity_model'] = 'session'
    payload['_meta']['storage_model'] = 'capsule_owned_owner_ledger'
    treasury = _load_json(ledger_path(org_id), {'treasury': {}}).get('treasury', {})
    treasury_owner_capital = round(float(treasury.get('owner_capital_contributed_usd', 0.0) or 0.0), 4)
    owner_capital = round(float(payload.get('capital_contributed_usd', 0.0) or 0.0), 4)
    if treasury_owner_capital > owner_capital:
        payload['capital_contributed_usd'] = treasury_owner_capital
        payload['_meta']['capital_sync_source'] = 'treasury_ledger'
        payload['_meta']['capital_sync_backfilled'] = True
        backfill_exists = any(
            entry.get('type') == 'capital_contribution_backfill'
            and round(float(entry.get('metadata', {}).get('target_owner_capital_usd', -1.0) or -1.0), 4) == treasury_owner_capital
            for entry in payload['entries']
        )
        if not backfill_exists:
            payload['entries'].append({
                'type': 'capital_contribution_backfill',
                'amount_usd': round(treasury_owner_capital - owner_capital, 4),
                'note': 'Backfilled from treasury owner_capital_contributed_usd',
                'by': 'system:service_state',
                'at': _now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                'metadata': {
                    'derived_from_treasury_ledger': True,
                    'target_owner_capital_usd': treasury_owner_capital,
                },
            })
        accounting_store.save_owner_ledger_state(owner_ledger_path(org_id), payload, org_id=org_id)
    return payload


def subscription_snapshot(org_id=None):
    payload = load_subscription_state(org_id)
    meta = payload.get('_meta', {})
    summary = subscription_service.subscription_summary(org_id)
    loom_delivery_queue = subscription_service.loom_delivery_queue_snapshot(org_id)
    loom_delivery_runs = subscription_service.loom_delivery_run_snapshot(org_id)
    alias_registry = ensure_subscription_aliases(org_id)
    canonical_path = os.path.relpath(
        alias_registry['canonical_paths']['subscriptions'],
        WORKSPACE,
    )
    compatibility_paths = alias_registry.get('compatibility_paths') or alias_registry['legacy_paths']
    legacy_path = os.path.relpath(
        compatibility_paths['subscriptions'],
        WORKSPACE,
    )

    return {
        'bound_org_id': meta.get('bound_org_id', org_id or ''),
        'management_mode': 'institution_owned_service',
        'mutation_enabled': True,
        'mutation_disabled_reason': '',
        'storage_model': _normalize_storage_model(meta.get('storage_model', 'capsule_canonical_with_compatibility_alias')),
        'boundary_name': meta.get('boundary_name', 'subscriptions'),
        'identity_model': meta.get('identity_model', 'session'),
        'canonical_source': 'service_module',
        'canonical_service_module': alias_registry['canonical_service_module'],
        'canonical_path': canonical_path,
        'compatibility_path_role': 'compatibility_symlink',
        'compatibility_path': legacy_path,
        'compatibility_module': alias_registry['compatibility_module'],
        'compatibility_mode': _normalize_compatibility_mode('compatibility_alias'),
        'alias_registry': {
            'canonical_source': alias_registry['canonical_source'],
            'canonical_paths': {
                'subscriptions': canonical_path,
                'subscriptions_backup': os.path.relpath(
                    alias_registry['canonical_paths']['subscriptions_backup'],
                    WORKSPACE,
                ),
                'subscriptions_lock': os.path.relpath(
                    alias_registry['canonical_paths']['subscriptions_lock'],
                    WORKSPACE,
                ),
            },
            'compatibility_paths': {
                'subscriptions': legacy_path,
                'subscriptions_backup': os.path.relpath(
                    compatibility_paths['subscriptions_backup'],
                    WORKSPACE,
                ),
                'subscriptions_lock': os.path.relpath(
                    compatibility_paths['subscriptions_lock'],
                    WORKSPACE,
                ),
            },
            'compatibility_mode': _normalize_compatibility_mode(alias_registry['compatibility_mode']),
        },
        'mutation_paths': list(SUBSCRIPTIONS_MUTATION_PATHS),
        'public_checkout_paths': {
            'intake': '/api/pilot/intake',
            'capture': '/api/subscriptions/checkout-capture',
        },
        'summary': summary,
        'meta': meta,
        'subscribers': payload.get('subscribers', {}),
        'delivery_log_tail': payload.get('delivery_log', [])[-20:],
        'loom_delivery_queue_summary': loom_delivery_queue['summary'],
        'loom_delivery_queue_paths': loom_delivery_queue['queue_paths'],
        'loom_delivery_queue_tail': loom_delivery_queue['delivery_jobs'][-20:],
        'loom_delivery_run_summary': loom_delivery_runs['summary'],
        'loom_delivery_run_tail': loom_delivery_runs['delivery_runs'][-20:],
    }


def accounting_snapshot(org_id=None):
    payload = load_owner_ledger_state(org_id)
    meta = payload.get('_meta', {})
    alias_registry = ensure_accounting_aliases(org_id)
    expenses_paid = float(payload.get('expenses_paid_usd', 0.0) or 0.0)
    reimbursements = float(payload.get('reimbursements_received_usd', 0.0) or 0.0)
    draws_taken = float(payload.get('draws_taken_usd', 0.0) or 0.0)
    capital = float(payload.get('capital_contributed_usd', 0.0) or 0.0)
    canonical_path = os.path.relpath(
        alias_registry['canonical_paths']['owner_ledger'],
        WORKSPACE,
    )
    compatibility_paths = alias_registry.get('compatibility_paths') or alias_registry['legacy_paths']
    legacy_path = os.path.relpath(
        compatibility_paths['owner_ledger'],
        WORKSPACE,
    )

    return {
        'bound_org_id': meta.get('bound_org_id', org_id or ''),
        'management_mode': 'institution_owned_service',
        'mutation_enabled': True,
        'mutation_disabled_reason': '',
        'storage_model': _normalize_storage_model(meta.get('storage_model', 'capsule_owned_owner_ledger')),
        'db': accounting_store.db_status_for_owner_ledger(owner_ledger_path(org_id), org_id),
        'boundary_name': meta.get('boundary_name', 'accounting'),
        'identity_model': meta.get('identity_model', 'session'),
        'canonical_source': 'service_module',
        'canonical_service_module': alias_registry['canonical_service_module'],
        'canonical_path': canonical_path,
        'compatibility_path_role': 'compatibility_symlink',
        'compatibility_path': legacy_path,
        'compatibility_module': alias_registry['compatibility_module'],
        'compatibility_mode': _normalize_compatibility_mode('compatibility_alias'),
        'alias_registry': {
            'canonical_source': alias_registry['canonical_source'],
            'canonical_paths': {
                'owner_ledger': canonical_path,
            },
            'compatibility_paths': {
                'owner_ledger': legacy_path,
            },
            'compatibility_mode': _normalize_compatibility_mode(alias_registry['compatibility_mode']),
        },
        'mutation_paths': list(ACCOUNTING_MUTATION_PATHS),
        'summary': {
            'capital_contributed_usd': capital,
            'expenses_paid_usd': expenses_paid,
            'reimbursements_received_usd': reimbursements,
            'draws_taken_usd': draws_taken,
            'unreimbursed_expenses_usd': round(expenses_paid - reimbursements, 2),
            'entry_count': len(payload.get('entries', [])),
        },
        'meta': meta,
        'owner': payload.get('owner', ''),
        'entries_tail': payload.get('entries', [])[-20:],
    }





def subscription_preview_snapshot(org_id=None, *, limit=50):
    payload = subscription_preview_queue.subscription_preview_queue_snapshot(org_id, limit=limit)
    return {
        'bound_org_id': payload['bound_org_id'],
        'management_mode': payload['management_mode'],
        'mutation_enabled': payload['mutation_enabled'],
        'mutation_disabled_reason': payload['mutation_disabled_reason'],
        'service_scope': payload['service_scope'],
        'boundary_name': payload['boundary_name'],
        'identity_model': payload['identity_model'],
        'storage_model': payload['storage_model'],
        'queue_paths': payload['queue_paths'],
        'public_intake_path': payload['queue_paths'].get('public_intake', ''),
        'summary': payload['summary'],
        'preview_tail': payload['subscription_previews'][-20:],
        'meta': payload['meta'],
    }

def pilot_intake_snapshot(org_id=None):
    payload = pilot_intake.queue_snapshot(org_id)
    return {
        'bound_org_id': payload['bound_org_id'],
        'management_mode': payload['management_mode'],
        'mutation_enabled': payload['mutation_enabled'],
        'mutation_disabled_reason': payload['mutation_disabled_reason'],
        'service_scope': payload['service_scope'],
        'boundary_name': payload['boundary_name'],
        'identity_model': payload['identity_model'],
        'storage_model': payload['storage_model'],
        'checkout_preview_publication_enabled': bool(payload.get('checkout_preview_publication_enabled')),
        'request_paths': payload['request_paths'],
        'summary': payload['summary'],
        'requests_tail': payload['requests'][-20:],
        'meta': payload['meta'],
    }
