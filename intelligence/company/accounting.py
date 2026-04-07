#!/usr/bin/env python3
"""
Legacy compatibility shim for owner money-flow accounting.
Separates owner capital from company treasury cash.

Institution scope:
  Founding-service-only compatibility shim.  Ledger reads/writes go through capsule
  aliases (ensure_treasury_aliases, capsule_ledger_path) which resolve to
  economy/ledger.json for the founding institution.  Transaction appends
  also resolve through the founding institution's capsule alias, which
  points at the canonical economy/transactions.jsonl file.  Owner-ledger
  state is now canonical in the founding institution capsule, while the
  legacy `company/owner_ledger.json` path is retained only as a compatibility
  symlink.  This module accepts explicit org_id plumbing, but the live capsule
  still resolves only the founding institution and fails closed for any other
  org.  This module does not support multi-institution operation and is not
  part of the OSS kernel.

Usage:
  python3 accounting.py contribute --amount <USD> --note "..."
  python3 accounting.py expense    --amount <USD> --note "..."   # records owner-paid expense
  python3 accounting.py reimburse  --amount <USD> --note "..."   # draws from treasury to owner
  python3 accounting.py draw       --amount <USD> --note "..."   # profit draw (respects reserve floor)
  python3 accounting.py show
"""
import argparse, contextlib, datetime, fcntl, json, os, sys, tempfile

COMPANY_DIR      = os.path.dirname(os.path.abspath(__file__))
ECONOMY_DIR      = os.path.join(COMPANY_DIR, '..', 'economy')
MERIDIAN_PLATFORM_DIR = os.path.join(COMPANY_DIR, 'meridian_platform')
OWNER_LEDGER     = os.path.join(COMPANY_DIR, 'owner_ledger.json')
DEFAULT_OWNER_LEDGER = OWNER_LEDGER
if MERIDIAN_PLATFORM_DIR not in sys.path:
    sys.path.insert(0, MERIDIAN_PLATFORM_DIR)

import capsule
from capsule import ensure_treasury_aliases, ledger_path as capsule_ledger_path
from capsule import transactions_path as capsule_transactions_path
from capsule import ensure_accounting_aliases, owner_ledger_path as capsule_owner_ledger_path

import accounting_store

def now_ts():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

def load_json(path, default=None):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default if default is not None else {}

def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def _write_json_atomic(path, data):
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
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
def _accounting_lock(org_id=None):
    lock_path = owner_ledger_path(org_id) + '.lock'
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    with open(lock_path, 'a+') as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _default_owner(org_id=None):
    return {
        'version': 1,
        'owner': 'Son Nguyen The',
        'created_at': now_ts(),
        'capital_contributed_usd': 0.0,
        'expenses_paid_usd': 0.0,
        'reimbursements_received_usd': 0.0,
        'draws_taken_usd': 0.0,
        'entries': [],
        '_meta': {
            'service_scope': 'institution_owned_service',
            'bound_org_id': capsule.default_org_id() if org_id is None else org_id or '',
            'boundary_name': 'accounting',
            'identity_model': 'session',
            'storage_model': 'capsule_owned_owner_ledger',
        },
    }


def _normalize_owner(data, org_id=None):
    if not isinstance(data, dict):
        return _default_owner(org_id)

    payload = dict(data)
    defaults = _default_owner(org_id)
    for key, value in defaults.items():
        if key == '_meta':
            continue
        payload.setdefault(key, value)

    payload.setdefault('_meta', {})
    payload['_meta']['service_scope'] = 'institution_owned_service'
    payload['_meta']['bound_org_id'] = capsule.default_org_id() if org_id is None else org_id or ''
    payload['_meta']['boundary_name'] = 'accounting'
    payload['_meta']['identity_model'] = 'session'
    payload['_meta']['storage_model'] = 'capsule_owned_owner_ledger'
    return payload


def owner_ledger_path(org_id=None):
    if org_id is None and OWNER_LEDGER != DEFAULT_OWNER_LEDGER:
        return OWNER_LEDGER
    ensure_accounting_aliases(org_id)
    return capsule_owner_ledger_path(org_id)

def load_ledger(org_id=None):
    path = os.path.realpath(capsule_ledger_path(org_id))
    with open(path) as f:
        return json.load(f)

def save_ledger(data, org_id=None):
    data['updatedAt'] = now_ts()
    _write_json_atomic(os.path.realpath(capsule_ledger_path(org_id)), data)

def append_tx(entry, org_id=None):
    entry = dict(entry)
    entry['ts'] = now_ts()
    tx_path = os.path.realpath(capsule_transactions_path(org_id))
    accounting_store.append_transaction(tx_path, entry, org_id=org_id)

def load_owner(org_id=None):
    path = owner_ledger_path(org_id)
    return accounting_store.load_owner_ledger_state(path, org_id)

# ── reusable helpers ─────────────────────────────────────────────────────────

def contribute_capital(amount_usd, note='', actor='owner', org_id=None):
    """Record an owner capital contribution and deposit it into treasury."""
    amount = float(amount_usd)
    if amount <= 0:
        raise ValueError('Capital contribution must be greater than 0')

    with _accounting_lock(org_id):
        owner = load_owner(org_id)
        ledger = load_ledger(org_id)

        owner['capital_contributed_usd'] += amount
        owner['entries'].append({
            'type': 'capital_contribution',
            'amount_usd': amount,
            'note': note,
            'by': actor,
            'at': now_ts(),
        })
        accounting_store.save_owner_ledger_state(owner_ledger_path(org_id), owner, org_id=org_id)

        t = ledger['treasury']
        t['cash_usd'] += amount
        t['owner_capital_contributed_usd'] += amount
        save_ledger(ledger, org_id)

        append_tx({
            'type': 'treasury_deposit',
            'deposit_type': 'owner_capital',
            'amount_usd': amount,
            'cash_after': t['cash_usd'],
            'note': note,
            'by': actor,
        }, org_id)
    return {
        'amount_usd': amount,
        'cash_after_usd': t['cash_usd'],
        'reserve_floor_usd': t['reserve_floor_usd'],
    }


def record_owner_expense(amount_usd, note='', actor='owner', org_id=None):
    """Record an owner-paid expense without mutating treasury cash."""
    amount = float(amount_usd)
    if amount <= 0:
        raise ValueError('Expense amount must be greater than 0')

    with _accounting_lock(org_id):
        owner = load_owner(org_id)
        owner['expenses_paid_usd'] += amount
        owner['entries'].append({
            'type': 'owner_expense',
            'amount_usd': amount,
            'note': note,
            'by': actor,
            'at': now_ts(),
        })
        accounting_store.save_owner_ledger_state(owner_ledger_path(org_id), owner, org_id=org_id)
        append_tx({
            'type': 'owner_expense_recorded',
            'amount_usd': amount,
            'note': note,
            'by': actor,
        }, org_id)
    unreimbursed = owner['expenses_paid_usd'] - owner['reimbursements_received_usd']
    return {
        'amount_usd': amount,
        'unreimbursed_expenses_usd': round(unreimbursed, 2),
    }


def update_reserve_floor(new_floor_usd, note='', actor='owner', org_id=None):
    """Update the treasury reserve floor as an explicit policy action."""
    amount = float(new_floor_usd)
    if amount < 0:
        raise ValueError('Reserve floor cannot be negative')

    with _accounting_lock(org_id):
        ledger = load_ledger(org_id)
        t = ledger['treasury']
        old = float(t.get('reserve_floor_usd', 50.0))
        t['reserve_floor_usd'] = amount
        save_ledger(ledger, org_id)

        append_tx({
            'type': 'treasury_policy_update',
            'policy': 'reserve_floor_usd',
            'old_value': old,
            'new_value': amount,
            'cash_after': t['cash_usd'],
            'note': note,
            'by': actor,
        }, org_id)
    return {
        'old_reserve_floor_usd': old,
        'new_reserve_floor_usd': amount,
        'cash_usd': t['cash_usd'],
    }


def reimburse_owner(amount_usd, note='', actor='owner', org_id=None):
    """Draw from treasury to reimburse a previously recorded owner expense."""
    amount = float(amount_usd)
    if amount <= 0:
        raise ValueError('Reimbursement amount must be greater than 0')

    with _accounting_lock(org_id):
        owner = load_owner(org_id)
        ledger = load_ledger(org_id)
        t = ledger['treasury']

        unreimbursed = owner['expenses_paid_usd'] - owner['reimbursements_received_usd']
        if amount > unreimbursed:
            raise ValueError(
                f'Reimbursement ${amount:.2f} exceeds unreimbursed expenses ${unreimbursed:.2f}'
            )
        if t['cash_usd'] - amount < t['reserve_floor_usd']:
            raise PermissionError(
                f"Reimbursement ${amount:.2f} would breach reserve floor ${t['reserve_floor_usd']:.2f}"
            )

        t['cash_usd'] -= amount
        t['owner_draws_usd'] += amount
        owner['reimbursements_received_usd'] += amount
        owner['entries'].append({
            'type': 'reimbursement',
            'amount_usd': amount,
            'note': note,
            'by': actor,
            'at': now_ts(),
        })
        accounting_store.save_owner_ledger_state(owner_ledger_path(org_id), owner, org_id=org_id)
        save_ledger(ledger, org_id)
        append_tx({
            'type': 'treasury_withdraw',
            'withdraw_type': 'owner_reimbursement',
            'amount_usd': amount,
            'cash_after': t['cash_usd'],
            'note': note,
            'by': actor,
        }, org_id)
    return {
        'amount_usd': amount,
        'cash_after_usd': t['cash_usd'],
        'unreimbursed_expenses_usd': round(
            owner['expenses_paid_usd'] - owner['reimbursements_received_usd'],
            2,
        ),
    }


def take_owner_draw(amount_usd, note='', actor='owner', org_id=None):
    """Take a profit draw from treasury cash while respecting the reserve floor."""
    amount = float(amount_usd)
    if amount <= 0:
        raise ValueError('Draw amount must be greater than 0')

    with _accounting_lock(org_id):
        ledger = load_ledger(org_id)
        t = ledger['treasury']
        floor = t['reserve_floor_usd']
        available = max(0.0, t['cash_usd'] - floor)
        if amount > available:
            raise ValueError(
                f'Draw ${amount:.2f} exceeds available above floor ${available:.2f}'
            )

        owner = load_owner(org_id)
        t['cash_usd'] -= amount
        t['owner_draws_usd'] += amount
        owner['draws_taken_usd'] += amount
        owner['entries'].append({
            'type': 'owner_draw',
            'amount_usd': amount,
            'note': note,
            'by': actor,
            'at': now_ts(),
        })
        accounting_store.save_owner_ledger_state(owner_ledger_path(org_id), owner, org_id=org_id)
        save_ledger(ledger, org_id)
        append_tx({
            'type': 'treasury_withdraw',
            'withdraw_type': 'owner_draw',
            'amount_usd': amount,
            'cash_after': t['cash_usd'],
            'note': note,
            'by': actor,
        }, org_id)
    return {
        'amount_usd': amount,
        'cash_after_usd': t['cash_usd'],
        'available_for_draw_usd': round(max(0.0, t['cash_usd'] - floor), 2),
    }

# ── commands ──────────────────────────────────────────────────────────────────

def cmd_contribute(args):
    """Owner contributes capital → deposits into company treasury."""
    result = contribute_capital(args.amount, args.note, actor='owner')
    print(f"Capital contribution: +${result['amount_usd']:.2f} | Treasury cash: ${result['cash_after_usd']:.2f}")

def cmd_expense(args):
    """Record owner-paid expense. Does NOT touch treasury (owner paid out-of-pocket)."""
    result = record_owner_expense(args.amount, args.note, actor='owner')
    print(
        f"Expense recorded: ${result['amount_usd']:.2f} | "
        f"Unreimbursed total: ${result['unreimbursed_expenses_usd']:.2f}"
    )

def cmd_reimburse(args):
    """Owner draws from treasury to reimburse a previous expense."""
    try:
        result = reimburse_owner(args.amount, args.note, actor='owner')
    except (ValueError, PermissionError) as exc:
        print(f'ERROR: {exc}')
        sys.exit(1)
    print(
        f"Reimbursement: -${result['amount_usd']:.2f} | "
        f"Treasury cash: ${result['cash_after_usd']:.2f}"
    )

def cmd_draw(args):
    """Owner takes a profit draw. Respects reserve floor."""
    try:
        result = take_owner_draw(args.amount, args.note, actor='owner')
    except ValueError as exc:
        print(f'ERROR: {exc}')
        sys.exit(1)
    print(
        f"Owner draw: -${result['amount_usd']:.2f} | "
        f"Treasury cash: ${result['cash_after_usd']:.2f}"
    )

def cmd_show(args):
    owner  = load_owner()
    ledger = load_ledger()
    t      = ledger['treasury']

    unreimbursed   = owner['expenses_paid_usd'] - owner['reimbursements_received_usd']
    avail_for_draw = max(0.0, t['cash_usd'] - t['reserve_floor_usd'])

    print("\n=== OWNER LEDGER (separated from company treasury) ===")
    print(f"  Capital contributed:         ${owner['capital_contributed_usd']:.2f}")
    print(f"  Expenses paid out-of-pocket: ${owner['expenses_paid_usd']:.2f}")
    print(f"  Reimbursements received:     ${owner['reimbursements_received_usd']:.2f}")
    print(f"  Draws taken:                 ${owner['draws_taken_usd']:.2f}")
    print(f"  Unreimbursed expenses:       ${unreimbursed:.2f}")
    print(f"\n=== COMPANY TREASURY ===")
    print(f"  Cash (USD):                  ${t['cash_usd']:.2f}")
    print(f"  Reserve floor:               ${t['reserve_floor_usd']:.2f}")
    print(f"  Available for draw:          ${avail_for_draw:.2f}")
    print(f"  Revenue from customers:      ${t.get('total_revenue_usd', 0):.2f}")
    print(f"  Owner capital deposited:     ${t['owner_capital_contributed_usd']:.2f}")

def main():
    p   = argparse.ArgumentParser(description='Owner money flow accounting')
    sub = p.add_subparsers(dest='command')

    for cmd, hlp in [('contribute', 'Deposit owner capital into treasury'),
                     ('expense',    'Record owner-paid expense (no treasury change)'),
                     ('reimburse',  'Draw from treasury to reimburse owner expense'),
                     ('draw',       'Take profit draw from treasury')]:
        sp = sub.add_parser(cmd, help=hlp)
        sp.add_argument('--amount', required=True)
        sp.add_argument('--note',   default=cmd)

    sub.add_parser('show')

    args = p.parse_args()
    if   args.command == 'contribute': cmd_contribute(args)
    elif args.command == 'expense':    cmd_expense(args)
    elif args.command == 'reimburse':  cmd_reimburse(args)
    elif args.command == 'draw':       cmd_draw(args)
    elif args.command == 'show':       cmd_show(args)
    else:                              p.print_help()

if __name__ == '__main__':
    main()
