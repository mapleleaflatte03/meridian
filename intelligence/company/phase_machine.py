#!/usr/bin/env python3
"""
Phase machine for the live Meridian deployment.

Institution scope:
  Founding-institution-only evaluator.  Reads from capsule-aliased ledger
  and revenue files that resolve to economy/ledger.json and economy/revenue.json
  for the founding org.  The _resolve_org_id() guard rejects any non-founding
  org_id at runtime.  Multi-institution phase evaluation would require the
  OSS kernel's phase_machine.py which accepts org_id for capsule resolution.

Evaluates the institution's current maturity against the same phase model as
the public kernel, but against live economy state and deployment-specific
internal test identifiers.

Usage:
  python3 phase_machine.py              # Show current phase
  python3 phase_machine.py --json       # JSON output for pipeline integration
"""
import argparse
import json
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_WORKSPACE = os.path.dirname(_THIS_DIR)
ECONOMY_DIR = os.path.join(_WORKSPACE, 'economy')
_PLATFORM_DIR = os.path.join(_WORKSPACE, 'company', 'meridian_platform')
if _PLATFORM_DIR not in sys.path:
    sys.path.insert(0, _PLATFORM_DIR)

from capsule import ensure_treasury_aliases, ledger_path as capsule_ledger_path, revenue_path as capsule_revenue_path

# -- Known internal test Telegram IDs (must never count as external traction) --
INTERNAL_TEST_IDS = frozenset({
    '6114408283',
    '1053016694',
})

# -- Direct state readers (no kernel import dependency) -----------------------

def _load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def _load_ledger(org_id=None):
    ensure_treasury_aliases()
    return _load_json(capsule_ledger_path(org_id))


def _load_revenue(org_id=None):
    ensure_treasury_aliases()
    return _load_json(capsule_revenue_path(org_id))


def _default_org_id():
    try:
        orgs_path = os.path.join(_WORKSPACE, 'company', 'meridian_platform', 'organizations.json')
        with open(orgs_path) as f:
            orgs = json.load(f)
        for oid, org in orgs.get('organizations', {}).items():
            if org.get('slug') == 'meridian':
                return oid
    except Exception:
        pass
    return None


def _resolve_org_id(org_id=None):
    founding_org_id = _default_org_id()
    if org_id and founding_org_id and org_id != founding_org_id:
        raise ValueError(
            f'Live phase machine only supports founding org {founding_org_id}, got {org_id}'
        )
    return org_id or founding_org_id


# -- Phase checks (mirrors kernel/phase_machine.py with deployment context) ---

PHASES = {
    0: 'Founder-Backed Build',
    1: 'Support-Backed Build',
    2: 'Customer-Validated Pilot',
    3: 'Customer-Backed Treasury',
    4: 'Treasury-Cleared Automation',
    5: 'Surplus-Backed Contributor Payouts',
    6: 'Inter-Institution Commitments',
}


def _order_client_id(order):
    return order.get('client_id') or order.get('client') or ''


def evaluate(org_id=None):
    """Evaluate Meridian's current phase. Returns (phase_num, details)."""
    resolved = _resolve_org_id(org_id)
    ledger = _load_ledger(resolved)
    revenue = _load_revenue(resolved)
    t = ledger.get('treasury', {})
    checks = []

    # Phase 0: founder-backed build starts as soon as the ledger exists.
    epoch = ledger.get('epoch', {})
    epoch_num = epoch.get('number', epoch) if isinstance(epoch, dict) else epoch
    p0 = bool(ledger)
    checks.append({'phase': 0, 'met': p0,
                    'reason': f'Ledger exists (epoch {epoch_num})' if p0 else 'No ledger found'})

    # Phase 1: support_received_usd > 0 (optional milestone before customer validation)
    support = t.get('support_received_usd', 0)
    p1 = p0 and support > 0
    checks.append({'phase': 1, 'met': p1,
                    'reason': f'Support: ${support:.2f}' if p1 else 'No support recorded'})

    # Phase 2: at least 1 real customer order paid. Support is not required first.
    orders = revenue.get('orders', {})
    real_paid = []
    for oid, order in orders.items():
        if order.get('status') != 'paid':
            continue
        cid = _order_client_id(order)
        if cid in INTERNAL_TEST_IDS:
            continue
        if order.get('product') in ('owner-capital-contribution',):
            continue
        real_paid.append(order)
    p2 = p0 and len(real_paid) >= 1
    checks.append({'phase': 2, 'met': p2,
                    'reason': f'{len(real_paid)} real paid orders' if p2 else f'{len(real_paid)} real paid orders (need >= 1)'})

    # Phase 3: revenue > owner capital, >= 3 payments, >= 2 clients
    total_rev = t.get('total_revenue_usd', 0)
    owner_cap = t.get('owner_capital_contributed_usd', 0)
    client_ids = {_order_client_id(o) for o in real_paid if _order_client_id(o)} - INTERNAL_TEST_IDS
    p3 = p2 and total_rev > owner_cap and len(real_paid) >= 3 and len(client_ids) >= 2
    p3_reason = f'Rev ${total_rev:.2f} vs cap ${owner_cap:.2f}, {len(real_paid)} orders, {len(client_ids)} clients'
    checks.append({'phase': 3, 'met': p3, 'reason': p3_reason})

    # Phase 4: cash >= reserve floor
    cash = t.get('cash_usd', 0)
    floor = t.get('reserve_floor_usd', 50)
    p4 = p3 and cash >= floor
    checks.append({'phase': 4, 'met': p4,
                    'reason': f'Cash ${cash:.2f} vs floor ${floor:.2f}'})

    # Phase 5: surplus for payouts
    p5 = p4 and cash > floor
    checks.append({'phase': 5, 'met': p5,
                    'reason': f'Surplus ${cash - floor:.2f}' if p5 else 'No surplus'})

    # Phase 6: inter-institution (needs multi-capsule)
    checks.append({'phase': 6, 'met': False,
                    'reason': 'Requires another institution on same kernel'})

    # Find highest passing phase. Support-backed build is optional; customer-backed
    # validation can be reached directly from founder-backed build.
    highest = -1
    for c in checks:
        if c['met']:
            highest = max(highest, c['phase'])

    # Next unlock
    next_unlock = None
    if highest < 1 and not checks[1]['met'] and not checks[2]['met']:
        next_unlock = 'Record first external support contribution or first real customer payment'
    elif highest < 6:
        next_unlock = checks[highest + 1]['reason']

    return highest, {
        'phase': highest,
        'name': PHASES.get(highest, 'Pre-Foundation'),
        'next_phase': highest + 1 if highest < 6 else None,
        'next_phase_name': PHASES.get(highest + 1) if highest < 6 else None,
        'next_unlock': next_unlock,
        'treasury': {
            'cash_usd': round(t.get('cash_usd', 0.0), 2),
            'reserve_floor_usd': round(t.get('reserve_floor_usd', 50.0), 2),
            'total_revenue_usd': round(total_rev, 2),
            'support_received_usd': round(support, 2),
            'owner_capital_usd': round(owner_cap, 2),
        },
        'checks': checks,
    }


def main():
    parser = argparse.ArgumentParser(description='Meridian Phase Machine')
    parser.add_argument('--json', action='store_true', help='JSON output')
    args = parser.parse_args()

    phase_num, details = evaluate()

    if args.json:
        print(json.dumps(details, indent=2))
        return

    print(f"\n=== Meridian Phase Machine ===")
    print(f"Current Phase: {phase_num} — {details['name']}")
    if details['next_phase'] is not None:
        print(f"Next Phase:    {details['next_phase']} — {details['next_phase_name']}")
        print(f"Unlock needs:  {details['next_unlock']}")
    print()
    for c in details['checks']:
        status = 'PASS' if c['met'] else 'FAIL'
        print(f"  Phase {c['phase']} ({PHASES[c['phase']]}): {status} — {c['reason']}")
    print()
    t = details['treasury']
    print(f"  Treasury: ${t['cash_usd']:.2f} cash, ${t['reserve_floor_usd']:.2f} floor, ${t['total_revenue_usd']:.2f} revenue, ${t['support_received_usd']:.2f} support, ${t['owner_capital_usd']:.2f} capital")


if __name__ == '__main__':
    main()
