#!/usr/bin/env python3
"""
Meridian Economy Scoring Tool
Usage:
  python3 score.py show
  python3 score.py record --agent <id> --event <type> --rep <+/-N> --auth <+/-N> --note "<reason>" [--randomize]
  python3 score.py treasury deposit --amount <USD> --type <owner_capital|customer_payment|reimbursement> --note "<reason>"
  python3 score.py treasury withdraw --amount <USD> --type <expense|owner_draw|owner_reimbursement|bonus> --note "<reason>"
  python3 score.py epoch --advance
"""
import argparse
import datetime
import json
import os
import random
import sys

RAND_CAP = {'rep': 3, 'auth': 4}

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_THIS_DIR)
_KERNEL_DIR = os.path.join(_ROOT_DIR, 'kernel')

if _KERNEL_DIR not in sys.path:
    sys.path.insert(0, _KERNEL_DIR)

# Capsule-aware path resolution: org_id=None -> economy/ (legacy default)
try:
    from capsule import capsule_path
except ImportError:
    def capsule_path(org_id, filename):
        return os.path.join(_THIS_DIR, filename)


def _ledger_path(org_id=None):
    return capsule_path(org_id, 'ledger.json')


def _tx_path(org_id=None):
    return capsule_path(org_id, 'transactions.jsonl')


def load_ledger(org_id=None):
    with open(_ledger_path(org_id)) as f:
        return json.load(f)

def save_ledger(data, org_id=None):
    data['updatedAt'] = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    with open(_ledger_path(org_id), 'w') as f:
        json.dump(data, f, indent=2)

def append_transaction(entry, org_id=None):
    entry['ts'] = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    with open(_tx_path(org_id), 'a') as f:
        f.write(json.dumps(entry) + '\n')

def clamp(val, lo=0, hi=100):
    return max(lo, min(hi, val))

def cmd_show(args):
    data = load_ledger(getattr(args, 'org_id', None))
    print(f"\n=== ECONOMY LEDGER (v{data.get('version', '?')}) ===")
    print(f"Updated: {data['updatedAt']}\n")
    print(f"{'Agent':<12} {'Name':<14} {'Role':<12} {'REP':>5} {'AUTH':>5} {'Status':<10}")
    print('-' * 65)
    for aid, a in data['agents'].items():
        status = 'PROBATION' if a.get('probation') else ('0-AUTH' if a.get('zero_authority') else a.get('status','?'))
        print(f"{aid:<12} {a.get('name','?'):<14} {a.get('role','?'):<12} {a['reputation_units']:>5} {a['authority_units']:>5} {status:<10}")
    t = data['treasury']
    print(f"\n=== TREASURY ===")
    print(f"  Cash (USD):         ${t['cash_usd']:.2f}")
    print(f"  Reserve floor:      ${t['reserve_floor_usd']:.2f}")
    print(f"  Owner capital in:   ${t['owner_capital_contributed_usd']:.2f}")
    print(f"  Revenue received:   ${t.get('total_revenue_usd', 0):.2f}")
    print(f"  Support received:   ${t.get('support_received_usd', 0):.2f}")
    print(f"  Expenses recorded:  ${t.get('expenses_recorded_usd', 0):.2f}")
    print(f"  Owner draws:        ${t.get('owner_draws_usd', 0):.2f}")
    bp = data.get('bonus_pool', {})
    print(f"\n=== BONUS POOL ===  ${bp.get('available_usd', 0):.2f} available\n")

def cmd_record(args):
    if not args.agent or not args.event:
        print("ERROR: --agent and --event are required")
        sys.exit(1)
    org_id = getattr(args, 'org_id', None)
    data = load_ledger(org_id)
    if args.agent not in data['agents']:
        print(f"ERROR: unknown agent '{args.agent}'. Known: {list(data['agents'].keys())}")
        sys.exit(1)
    agent = data['agents'][args.agent]
    old_rep = agent['reputation_units']
    old_auth = agent['authority_units']

    rep_delta  = int(args.rep)  if args.rep  else 0
    auth_delta = int(args.auth) if args.auth else 0

    # Bounded randomness: optional, positive outcomes only, never creates CASH
    if getattr(args, 'randomize', False):
        if rep_delta  > 0: rep_delta  += random.randint(0, RAND_CAP['rep'])
        if auth_delta > 0: auth_delta += random.randint(0, RAND_CAP['auth'])

    if agent.get('zero_authority') and auth_delta > 0:
        print(f"WARN: {args.agent} is zero_authority — AUTH gain blocked until sanction lifted")
        auth_delta = 0
    if agent.get('probation') and rep_delta > 0:
        print(f"WARN: {args.agent} is on probation — REP gain reduced by 50%")
        rep_delta = rep_delta // 2

    agent['reputation_units'] = clamp(old_rep + rep_delta)
    agent['authority_units'] = clamp(old_auth + auth_delta)
    agent['last_scored_at'] = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    agent['last_score_reason'] = args.note or args.event

    save_ledger(data, org_id)
    append_transaction({
        'type': 'agent_score',
        'agent': args.agent,
        'event': args.event,
        'rep_before': old_rep,
        'rep_after': agent['reputation_units'],
        'rep_delta': rep_delta,
        'auth_before': old_auth,
        'auth_after': agent['authority_units'],
        'auth_delta': auth_delta,
        'note': args.note or ''
    }, org_id)
    print(f"Recorded: {args.agent} | REP {old_rep} → {agent['reputation_units']} ({rep_delta:+}) | AUTH {old_auth} → {agent['authority_units']} ({auth_delta:+})")

def cmd_treasury(args):
    org_id = getattr(args, 'org_id', None)
    data = load_ledger(org_id)
    t = data['treasury']
    amount = float(args.amount)
    if args.subcommand == 'deposit':
        valid_types = ['owner_capital', 'customer_payment', 'reimbursement', 'support']
        if args.type not in valid_types:
            print(f"ERROR: type must be one of {valid_types}")
            sys.exit(1)
        t['cash_usd'] += amount
        if args.type == 'owner_capital':
            t['owner_capital_contributed_usd'] += amount
        elif args.type == 'customer_payment':
            t['total_revenue_usd'] = t.get('total_revenue_usd', 0) + amount
        elif args.type == 'support':
            t['support_received_usd'] = t.get('support_received_usd', 0) + amount
        save_ledger(data, org_id)
        append_transaction({
            'type': 'treasury_deposit',
            'deposit_type': args.type,
            'amount_usd': amount,
            'cash_after': t['cash_usd'],
            'note': args.note or ''
        }, org_id)
        print(f"Treasury deposit: +${amount:.2f} ({args.type}) → cash now ${t['cash_usd']:.2f}")
    elif args.subcommand == 'withdraw':
        valid_types = ['expense', 'owner_draw', 'owner_reimbursement', 'bonus']
        if args.type not in valid_types:
            print(f"ERROR: type must be one of {valid_types}")
            sys.exit(1)
        if args.type in ('owner_draw', 'bonus') and t['cash_usd'] - amount < t['reserve_floor_usd']:
            print(f"ERROR: withdrawal would breach reserve floor of ${t['reserve_floor_usd']:.2f}. Current cash: ${t['cash_usd']:.2f}")
            sys.exit(1)
        t['cash_usd'] -= amount
        if args.type in ('owner_draw', 'owner_reimbursement'):
            t['owner_draws_usd'] += amount
        elif args.type == 'expense':
            t['expenses_recorded_usd'] += amount
        save_ledger(data, org_id)
        append_transaction({
            'type': 'treasury_withdraw',
            'withdraw_type': args.type,
            'amount_usd': amount,
            'cash_after': t['cash_usd'],
            'note': args.note or ''
        }, org_id)
        print(f"Treasury withdraw: -${amount:.2f} ({args.type}) → cash now ${t['cash_usd']:.2f}")

def cmd_epoch(args):
    org_id = getattr(args, 'org_id', None)
    data = load_ledger(org_id)
    epoch = data['epoch']
    if args.advance:
        for aid, agent in data['agents'].items():
            if agent.get('zero_authority'):
                continue
            if agent.get('last_scored_at') and agent['last_scored_at'] < epoch['started_at']:
                old = agent['authority_units']
                agent['authority_units'] = clamp(old - epoch['auth_decay_per_epoch'])
                print(f"  AUTH decay: {aid} {old} → {agent['authority_units']}")
        epoch['number'] += 1
        epoch['started_at'] = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        save_ledger(data, org_id)
        append_transaction({
            'type': 'epoch_advance',
            'new_epoch': epoch['number'],
            'note': 'Auto decay applied to inactive agents'
        }, org_id)
        print(f"Advanced to epoch {epoch['number']}")


def add_org_arg(parser):
    parser.add_argument('--org_id', default=None,
                        help='Institution context. Defaults to the legacy founding institution.')

def main():
    parser = argparse.ArgumentParser(description='Meridian Economy Scoring Tool')
    sub = parser.add_subparsers(dest='command')

    show_p = sub.add_parser('show')
    add_org_arg(show_p)

    rec_p = sub.add_parser('record')
    add_org_arg(rec_p)
    rec_p.add_argument('--agent', required=True)
    rec_p.add_argument('--event', required=True)
    rec_p.add_argument('--rep',       default='0')
    rec_p.add_argument('--auth',      default='0')
    rec_p.add_argument('--note',      default='')
    rec_p.add_argument('--randomize', action='store_true',
                       help='Add bounded random bonus to positive deltas')

    tr_p = sub.add_parser('treasury')
    tr_sub = tr_p.add_subparsers(dest='subcommand')
    dep = tr_sub.add_parser('deposit')
    add_org_arg(dep)
    dep.add_argument('--amount', required=True)
    dep.add_argument('--type', required=True)
    dep.add_argument('--note', default='')
    wd = tr_sub.add_parser('withdraw')
    add_org_arg(wd)
    wd.add_argument('--amount', required=True)
    wd.add_argument('--type', required=True)
    wd.add_argument('--note', default='')

    ep_p = sub.add_parser('epoch')
    add_org_arg(ep_p)
    ep_p.add_argument('--advance', action='store_true')

    args = parser.parse_args()

    if args.command == 'show':
        cmd_show(args)
    elif args.command == 'record':
        cmd_record(args)
    elif args.command == 'treasury':
        if not args.subcommand:
            print("Usage: score.py treasury [deposit|withdraw] ...")
            sys.exit(1)
        cmd_treasury(args)
    elif args.command == 'epoch':
        cmd_epoch(args)
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
