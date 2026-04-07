#!/usr/bin/env python3
"""
Phase Machine -- read-only evaluator for institutional maturity.

The phase machine derives an institution's current phase from verifiable
accounting and governance state.  There is no "set phase" command; phase
is always computed, never stored.

Phases:
  0  Founder-Backed Build    -- owner capital only, building
  1  Support-Backed Build    -- external support received
  2  Customer-Validated Pilot -- at least one real customer payment
  3  Customer-Backed Treasury -- revenue exceeds owner capital
  4  Treasury-Cleared Auto   -- self-sustaining (above reserve, positive flow)
  5  Surplus Contributor Pay -- surplus allows contributor payouts
  6  Inter-Institution       -- treaties with other institutions

Usage:
  python3 phase_machine.py status [--org_id <id>]
  python3 phase_machine.py check  --action <action> [--org_id <id>]
"""
import argparse
import json
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_WORKSPACE = os.path.dirname(_THIS_DIR)

# Try to import capsule resolver; fall back to direct economy/ paths
try:
    from capsule import capsule_path, ECONOMY_DIR
except ImportError:
    ECONOMY_DIR = os.path.join(_WORKSPACE, 'economy')

    def capsule_path(org_id, filename):
        return os.path.join(ECONOMY_DIR, filename)


# -- Phase definitions --------------------------------------------------------

PHASES = {
    0: {
        'name': 'Founder-Backed Build',
        'description': 'Building with owner capital only.',
        'allowed_claims': ['We are building X'],
        'forbidden': ['Calling owner capital "revenue"', 'Claiming customers'],
    },
    1: {
        'name': 'Support-Backed Build',
        'description': 'External support/sponsorship received as an optional build milestone.',
        'allowed_claims': ['We accept support to fund development'],
        'forbidden': ['Calling support "revenue"', 'Calling supporters "customers"'],
    },
    2: {
        'name': 'Customer-Validated Pilot',
        'description': 'At least one real external customer payment received.',
        'allowed_claims': ['We have pilot customers'],
        'forbidden': ['Counting owner tests as customers'],
    },
    3: {
        'name': 'Customer-Backed Treasury',
        'description': 'Revenue exceeds owner capital with multiple clients.',
        'allowed_claims': ['Revenue-generating institution'],
        'forbidden': ['Counting support spikes as sustainable revenue'],
    },
    4: {
        'name': 'Treasury-Cleared Automation',
        'description': 'Self-sustaining: above reserve with positive cash flow.',
        'allowed_claims': ['Self-sustaining operations'],
        'forbidden': ['Claiming sustainability while below reserve'],
    },
    5: {
        'name': 'Surplus-Backed Contributor Payouts',
        'description': 'Surplus treasury enables contributor compensation.',
        'allowed_claims': ['We pay contributors'],
        'forbidden': ['Paying before reserve covered', 'Paying from earmarked support'],
    },
    6: {
        'name': 'Inter-Institution Commitments',
        'description': 'Active treaties with other Meridian institutions.',
        'allowed_claims': ['We partner with other Meridian institutions'],
        'forbidden': ['Calling internal tests "partners"'],
    },
}

# Actions gated by minimum phase
PHASE_GATES = {
    'claim_customers': 2,
    'claim_revenue': 3,
    'claim_self_sustaining': 4,
    'execute_payout': 5,
    'propose_treaty': 6,
}


# -- State readers ------------------------------------------------------------

def _load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def _load_ledger(org_id=None):
    return _load_json(capsule_path(org_id, 'ledger.json'))


def _load_revenue(org_id=None):
    return _load_json(capsule_path(org_id, 'revenue.json'))


# -- Known internal test identifiers (must never count as external) -----------

INTERNAL_TEST_IDS = frozenset()  # Populate per deployment; kernel has no defaults


# -- Phase evaluation ---------------------------------------------------------

def _check_phase_0(ledger, revenue):
    """Phase 0 begins as soon as the institution has a ledger.

    Founder-backed build is the starting operating phase after bootstrap.
    Requiring a completed epoch makes fresh institutions appear to be in a
    nonsensical pre-foundation state.
    """
    if not ledger:
        return False, 'No ledger found'
    epoch = ledger.get('epoch', {})
    epoch_num = epoch.get('number', epoch) if isinstance(epoch, dict) else epoch
    return True, f'Ledger exists (epoch {epoch_num})'


def _check_phase_1(ledger, revenue):
    """Phase 1: support_received_usd > 0."""
    t = ledger.get('treasury', {})
    support = t.get('support_received_usd', 0)
    if support > 0:
        return True, f'Support received: ${support:.2f}'
    return False, 'No external support contributions recorded'


def _check_phase_2(ledger, revenue):
    """Phase 2: at least 1 real customer order paid. Support is not required first."""
    orders = revenue.get('orders', {})
    for oid, order in orders.items():
        if order.get('status') == 'paid':
            # Filter internal tests
            client_id = order.get('client_id') or order.get('client', '')
            if client_id in INTERNAL_TEST_IDS:
                continue
            product = order.get('product', '')
            if product in ('owner-capital-contribution',):
                continue
            return True, f'Customer order {oid} is paid (product={product})'
    return False, 'No real customer payments in revenue.json'


def _check_phase_3(ledger, revenue):
    """Phase 3: revenue > owner capital, >= 3 payments, >= 2 clients."""
    t = ledger.get('treasury', {})
    total_rev = t.get('total_revenue_usd', 0)
    owner_cap = t.get('owner_capital_contributed_usd', 0)
    if total_rev <= owner_cap:
        return False, f'Revenue ${total_rev:.2f} <= owner capital ${owner_cap:.2f}'

    # Count distinct paid customer orders and clients
    orders = revenue.get('orders', {})
    paid_orders = []
    client_ids = set()
    for order in orders.values():
        if order.get('status') == 'paid':
            cid = order.get('client_id') or order.get('client', '')
            if cid in INTERNAL_TEST_IDS:
                continue
            if order.get('product') in ('owner-capital-contribution',):
                continue
            paid_orders.append(order)
            if cid:
                client_ids.add(cid)

    if len(paid_orders) < 3:
        return False, f'{len(paid_orders)} paid orders < 3 required'
    if len(client_ids) < 2:
        return False, f'{len(client_ids)} distinct clients < 2 required'

    return True, f'Revenue ${total_rev:.2f} > capital ${owner_cap:.2f}, {len(paid_orders)} orders, {len(client_ids)} clients'


def _check_phase_4(ledger, revenue):
    """Phase 4: cash >= reserve floor (simplified -- full check needs 3-month history)."""
    t = ledger.get('treasury', {})
    cash = t.get('cash_usd', 0)
    floor = t.get('reserve_floor_usd', 50)
    if cash < floor:
        return False, f'Cash ${cash:.2f} < reserve floor ${floor:.2f}'
    return True, f'Cash ${cash:.2f} >= reserve floor ${floor:.2f}'


def _check_phase_5(ledger, revenue):
    """Phase 5: surplus after reserve covers pending payouts."""
    t = ledger.get('treasury', {})
    cash = t.get('cash_usd', 0)
    floor = t.get('reserve_floor_usd', 50)
    # Would need payout_proposals.json to check pending -- simplified
    if cash <= floor:
        return False, f'No surplus: cash ${cash:.2f} <= floor ${floor:.2f}'
    return True, f'Surplus: ${cash - floor:.2f} available for payouts'


def _check_phase_6(ledger, revenue):
    """Phase 6: requires another institution on the same kernel (cannot evaluate from single capsule)."""
    return False, 'Inter-institution evaluation requires multi-capsule context'


_PHASE_CHECKS = [
    _check_phase_0,
    _check_phase_1,
    _check_phase_2,
    _check_phase_3,
    _check_phase_4,
    _check_phase_5,
    _check_phase_6,
]


def current_phase(org_id=None):
    """Evaluate the highest phase whose conditions are met.

    Returns (phase_number, phase_info_dict) where phase_info_dict contains:
      name, description, checks (list of {phase, met, reason}).
    """
    ledger = _load_ledger(org_id)
    revenue = _load_revenue(org_id)

    checks = []
    highest = -1

    for phase_num, check_fn in enumerate(_PHASE_CHECKS):
        met, reason = check_fn(ledger, revenue)
        checks.append({
            'phase': phase_num,
            'name': PHASES[phase_num]['name'],
            'met': met,
            'reason': reason,
        })
        if met:
            highest = max(highest, phase_num)

    phase_info = PHASES.get(highest, PHASES[0])
    next_phase = highest + 1 if highest < 6 else None
    next_unlock = None
    if highest < 1 and not checks[1]['met'] and not checks[2]['met']:
        next_unlock = 'Record first external support contribution or first real customer payment'
    elif next_phase is not None and next_phase <= 6:
        next_unlock = checks[next_phase]['reason']

    return highest, {
        'phase': highest,
        'name': phase_info['name'],
        'description': phase_info['description'],
        'allowed_claims': phase_info['allowed_claims'],
        'forbidden': phase_info['forbidden'],
        'next_phase': next_phase,
        'next_unlock': next_unlock,
        'checks': checks,
    }


def check_phase_gate(org_id, action):
    """Check if an action is allowed at the institution's current phase.

    Returns (allowed, reason).
    """
    required = PHASE_GATES.get(action)
    if required is None:
        return True, f'Action "{action}" has no phase gate'

    phase_num, info = current_phase(org_id)
    if phase_num >= required:
        return True, f'Phase {phase_num} ({info["name"]}) >= required {required}'
    return False, (
        f'Action "{action}" requires Phase {required} ({PHASES[required]["name"]}). '
        f'Current: Phase {phase_num} ({info["name"]}). '
        f'Next unlock: {info.get("next_unlock", "unknown")}'
    )


# -- CLI ----------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description='Phase machine -- institutional maturity evaluator')
    sub = p.add_subparsers(dest='command')

    st = sub.add_parser('status', help='Show current phase and all checks')
    st.add_argument('--org_id', default=None)

    chk = sub.add_parser('check', help='Check if an action is allowed at current phase')
    chk.add_argument('--action', required=True,
                     choices=list(PHASE_GATES.keys()))
    chk.add_argument('--org_id', default=None)

    args = p.parse_args()

    if args.command == 'status':
        phase_num, info = current_phase(args.org_id)
        print(f"\n=== Phase Machine ===")
        print(f"Current Phase: {phase_num} — {info['name']}")
        print(f"Description:   {info['description']}")
        print(f"Allowed claims: {', '.join(info['allowed_claims'])}")
        print(f"Forbidden:      {', '.join(info['forbidden'])}")
        if info['next_phase'] is not None:
            next_name = PHASES[info['next_phase']]['name']
            print(f"\nNext phase:    {info['next_phase']} — {next_name}")
            print(f"Unlock needs:  {info['next_unlock']}")
        else:
            print(f"\nMaximum phase reached.")

        print(f"\n--- Phase Checks ---")
        for c in info['checks']:
            status = 'PASS' if c['met'] else 'FAIL'
            print(f"  Phase {c['phase']} ({c['name']}): {status} — {c['reason']}")

    elif args.command == 'check':
        allowed, reason = check_phase_gate(args.org_id, args.action)
        status = 'ALLOWED' if allowed else 'BLOCKED'
        print(f'{status}: {reason}')
        sys.exit(0 if allowed else 1)

    else:
        p.print_help()


if __name__ == '__main__':
    main()
