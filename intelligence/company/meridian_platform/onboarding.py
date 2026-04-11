#!/usr/bin/env python3
"""
Institution onboarding API.

Handles creation of new institutions with isolated capsule, treasury, court, and PoGE context.
"""
import json
import os

from organizations import create_org, get_org
from capsule import ensure_capsule, ensure_treasury_aliases


def provision_institution(name, owner_id, plan='free'):
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

    # Initialize empty ledger if not exists
    ledger_path = treasury_aliases['ledger']
    if not os.path.exists(ledger_path) or os.path.getsize(ledger_path) == 0:
        with open(ledger_path, 'w') as f:
            json.dump({
                'balance_usd': 0.0,
                'reserved_usd': 0.0,
                'transactions': [],
            }, f, indent=2)

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

    return {
        'org_id': org_id,
        'org': org,
        'capsule_path': capsule_path,
        'treasury': {
            'ledger': ledger_path,
            'revenue': revenue_path,
            'transactions': transactions_path,
        },
    }
