#!/usr/bin/env python3
"""
Institution onboarding API.

Handles creation of new institutions with isolated capsule, treasury, court, and PoGE context.
"""
import json
import os

from organizations import create_org, get_org
from capsule import ensure_capsule, ensure_treasury_aliases, _normalize_ledger_payload
import institution_brain_policy


def provision_institution(
    name,
    owner_id,
    plan='free',
    *,
    brain_route_type='',
    brain_provider_profile='',
    brain_model='',
    brain_auth_profile='',
    brain_cli_bin='',
    brain_cli_home='',
    brain_endpoint='',
    brain_auth_env='',
    brain_key_env_pool=None,
    brain_provider_entry_id='',
    brain_model_entry_id='',
):
    """
    Create a new institution with full isolated bootstrap.

    Returns:
        dict: {
            'org_id': str,
            'org': dict,
            'capsule_path': str,
            'treasury': dict,
        }
    """
    # Create organization record
    org_id = create_org(name, owner_id, plan)
    org = get_org(org_id)

    # Provision isolated capsule
    capsule_path = ensure_capsule(org_id)

    # Initialize treasury structure
    treasury_aliases = ensure_treasury_aliases(org_id)

    # Initialize or normalize ledger
    ledger_path = treasury_aliases['ledger']
    if not os.path.exists(ledger_path) or os.path.getsize(ledger_path) == 0:
        with open(ledger_path, 'w') as f:
            json.dump(_normalize_ledger_payload({}), f, indent=2)
    else:
        with open(ledger_path) as f:
            ledger_payload = json.load(f)
        normalized_ledger = _normalize_ledger_payload(ledger_payload)
        if normalized_ledger != ledger_payload:
            with open(ledger_path, 'w') as f:
                json.dump(normalized_ledger, f, indent=2)

    # Initialize empty revenue if not exists
    revenue_path = treasury_aliases['revenue']
    if not os.path.exists(revenue_path) or os.path.getsize(revenue_path) == 0:
        with open(revenue_path, 'w') as f:
            json.dump({
                'total_revenue_usd': 0.0,
                'clients': {},
                'orders': {},
                'receivables_usd': 0.0,
            }, f, indent=2)

    # Ensure transactions file exists
    transactions_path = treasury_aliases['transactions']
    if not os.path.exists(transactions_path):
        open(transactions_path, 'a').close()

    if not str(brain_route_type or '').strip():
        raise ValueError('brain_route_type is required')
    if not str(brain_provider_profile or '').strip():
        raise ValueError('brain_provider_profile is required')
    if not str(brain_auth_profile or '').strip():
        raise ValueError('brain_auth_profile is required')
    if brain_route_type == 'cli_session' and not str(brain_cli_bin or '').strip():
        raise ValueError('brain_cli_bin is required for cli_session')
    if brain_route_type == 'http_json' and not str(brain_endpoint or '').strip():
        raise ValueError('brain_endpoint is required for http_json')
    if brain_route_type == 'http_json' and not str(brain_auth_env or '').strip() and not list(brain_key_env_pool or []):
        raise ValueError('brain_auth_env or brain_key_env_pool is required for http_json')

    provider_entry_id = str(brain_provider_entry_id or brain_provider_profile or '').strip()
    if not provider_entry_id:
        raise ValueError('brain_provider_entry_id is required')

    model_entry_id = str(brain_model_entry_id or '').strip()

    institution_brain_policy_doc = institution_brain_policy.configure_policy(
        org_id,
        route_type=brain_route_type,
        provider_profile=brain_provider_profile,
        model=brain_model,
        updated_by=f'onboarding:{owner_id}',
        cli_bin=brain_cli_bin,
        cli_home=brain_cli_home,
        endpoint=brain_endpoint,
        auth_profile_name=brain_auth_profile,
        auth_env=brain_auth_env,
        key_env_pool=list(brain_key_env_pool or []),
        fallback_routes=[],
        provider_entry_id=provider_entry_id,
        model_entry_id=model_entry_id,
    )

    provider_registry = institution_brain_policy_doc.get('provider_registry') or {}
    model_registry = institution_brain_policy_doc.get('model_registry') or {}
    active_route = next(
        (
            route for route in (institution_brain_policy_doc.get('routes') or [])
            if str(route.get('route_id') or '') == str(institution_brain_policy_doc.get('primary_route_id') or '')
        ),
        (institution_brain_policy_doc.get('routes') or [{}])[0] if (institution_brain_policy_doc.get('routes') or []) else {},
    )
    active_provider_ref = str(active_route.get('provider_ref') or active_route.get('provider_profile') or '').strip()
    active_model_ref = str(active_route.get('model_ref') or '').strip() and str(active_route.get('model_ref') or '').strip() or ''

    institution_brain_policy_doc['active_provider'] = dict(provider_registry.get(active_provider_ref) or {})
    institution_brain_policy_doc['active_model'] = dict(model_registry.get(active_model_ref) or {}) if active_model_ref else {}
    institution_brain_policy_doc['provider_registry'] = dict(provider_registry)
    institution_brain_policy_doc['model_registry'] = dict(model_registry)

    return {
        'org_id': org_id,
        'org': org,
        'capsule_path': capsule_path,
        'treasury': {
            'ledger': ledger_path,
            'revenue': revenue_path,
            'transactions': transactions_path,
        },
        'institution_brain_policy': institution_brain_policy_doc,
    }
