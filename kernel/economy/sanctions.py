#!/usr/bin/env python3
"""
Sanction enforcement engine.
Applies, lifts, and auto-checks sanctions. Writes to ledger + transactions.

Usage:
  python3 sanctions.py apply --agent <id> --type <probation|zero_authority|lead_ban|remediation_only> --note "reason"
  python3 sanctions.py lift  --agent <id> --type <probation|zero_authority|lead_ban|all> --note "reason"
  python3 sanctions.py restrictions --agent <id>
  python3 sanctions.py auto-check [--dry-run]
  python3 sanctions.py show
"""
import argparse
import datetime
import json
import os
import sys

ECONOMY_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(ECONOMY_DIR)
KERNEL_DIR = os.path.join(ROOT_DIR, 'kernel')

if KERNEL_DIR not in sys.path:
    sys.path.insert(0, KERNEL_DIR)

from io_atomic import append_jsonl, atomic_write_json

try:
    from capsule import capsule_path
except ImportError:
    def capsule_path(org_id, filename):
        return os.path.join(ECONOMY_DIR, filename)


def _ledger_path(org_id=None):
    return capsule_path(org_id, 'ledger.json')


def _tx_path(org_id=None):
    return capsule_path(org_id, 'transactions.jsonl')


def _missing_org_error(org_id):
    raise SystemExit(
        f"ERROR: institution '{org_id}' is not initialized. Run quickstart.py --init-only or bootstrap the capsule first."
    )


# Actions blocked per sanction flag
RESTRICTION_MAP = {
    'probation':       ['lead', 'assign'],
    'zero_authority':  ['lead', 'assign', 'execute'],
    'lead_ban':        ['lead'],
    'remediation_only': ['lead', 'assign', 'execute'],
}

# Auto-apply thresholds (evaluated in order — most severe last to override)
AUTO_RULES = [
    {
        'id':        'rep_low_probation',
        'condition': lambda a: a['reputation_units'] <= 20 and not a.get('probation') and not a.get('zero_authority'),
        'apply':     'probation',
        'level':     4,
        'note':      'REP ≤ 20 → auto-probation',
    },
    {
        'id':        'auth_zero',
        'condition': lambda a: a['authority_units'] == 0 and not a.get('zero_authority'),
        'apply':     'zero_authority',
        'level':     5,
        'note':      'AUTH reached 0 → zero_authority',
    },
    {
        'id':        'rep_critical',
        'condition': lambda a: a['reputation_units'] <= 5 and not a.get('zero_authority'),
        'apply':     'zero_authority',
        'level':     6,
        'note':      'REP ≤ 5 critical → zero_authority',
    },
]

# Auto-lift thresholds
AUTO_LIFT_RULES = [
    {
        'condition': lambda a: a.get('probation') and not a.get('zero_authority') and a['reputation_units'] > 30,
        'lift':      'probation',
        'note':      'REP recovered above 30 → auto-lift probation',
    },
    {
        'condition': lambda a: a.get('zero_authority') and a['authority_units'] > 15,
        'lift':      'zero_authority',
        'note':      'AUTH recovered above 15 → auto-lift zero_authority',
    },
]

def now_ts():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

def load_ledger(org_id=None):
    path = _ledger_path(org_id)
    if org_id and not os.path.exists(path):
        _missing_org_error(org_id)
    with open(path) as f:
        return json.load(f)

def save_ledger(data, org_id=None):
    data['updatedAt'] = now_ts()
    path = _ledger_path(org_id)
    if org_id and not os.path.isdir(os.path.dirname(path)):
        _missing_org_error(org_id)
    atomic_write_json(path, data)

def append_tx(entry, org_id=None):
    entry['ts'] = now_ts()
    path = _tx_path(org_id)
    if org_id and not os.path.isdir(os.path.dirname(path)):
        _missing_org_error(org_id)
    append_jsonl(path, entry)

def get_restrictions(data, agent_id):
    if agent_id not in data['agents']:
        return []
    agent = data['agents'][agent_id]
    r = set()
    for flag, actions in RESTRICTION_MAP.items():
        if agent.get(flag):
            r.update(actions)
    return sorted(r)

def apply_sanction(data, agent_id, stype, note, level='manual', org_id=None):
    if agent_id not in data['agents']:
        print(f"ERROR: unknown agent '{agent_id}'")
        return False
    agent = data['agents'][agent_id]

    if stype == 'probation':
        agent['probation'] = True
    elif stype == 'zero_authority':
        agent['zero_authority']   = True
        agent['authority_units']  = 0
    elif stype == 'lead_ban':
        agent['lead_ban'] = True
    elif stype == 'remediation_only':
        agent['zero_authority']    = True
        agent['probation']         = True
        agent['remediation_only']  = True
        agent['authority_units']   = 0

    agent['last_scored_at']    = now_ts()
    agent['last_score_reason'] = f"SANCTION:{stype} | {note}"

    append_tx({
        'type':         'sanction_applied',
        'agent':        agent_id,
        'sanction':     stype,
        'level':        level,
        'reason':       note,
        'restrictions': get_restrictions(data, agent_id),
    }, org_id)
    print(f"SANCTION APPLIED: {agent_id} → {stype} | restrictions: {get_restrictions(data, agent_id)}")
    return True

def lift_sanction(data, agent_id, stype, note, org_id=None):
    if agent_id not in data['agents']:
        print(f"ERROR: unknown agent '{agent_id}'")
        return False
    agent = data['agents'][agent_id]

    if stype in ('probation', 'all'):
        agent['probation'] = False
    if stype in ('zero_authority', 'all'):
        agent['zero_authority'] = False
        # Prevent auto-rule from immediately re-sanctioning: grant enough AUTH
        # to survive one epoch of inactivity (auth_decay_per_epoch + 1)
        if agent['authority_units'] == 0:
            floor = data.get('epoch', {}).get('auth_decay_per_epoch', 5) + 1
            agent['authority_units'] = floor
    if stype in ('lead_ban', 'all'):
        agent.pop('lead_ban', None)
    if stype in ('remediation_only', 'all'):
        agent.pop('remediation_only', None)

    append_tx({'type': 'sanction_lifted', 'agent': agent_id, 'sanction': stype, 'reason': note}, org_id)
    print(f"SANCTION LIFTED: {agent_id} → {stype} cleared")
    return True

# ── programmatic API ──────────────────────────────────────────────────────────

def check_auto_sanctions(data, dry_run=False, org_id=None):
    """Evaluate auto-apply and auto-lift rules against data (in-place). Returns list of changes."""
    changes = []
    for aid, agent in data['agents'].items():
        for rule in AUTO_RULES:
            try:
                if rule['condition'](agent):
                    changes.append(('apply', aid, rule['apply'], rule['note'], rule['level']))
            except Exception:
                pass
        for rule in AUTO_LIFT_RULES:
            try:
                if rule['condition'](agent):
                    changes.append(('lift', aid, rule['lift'], rule['note'], None))
            except Exception:
                pass
    if dry_run:
        return changes
    for kind, aid, stype, note, level in changes:
        if kind == 'apply':
            apply_sanction(data, aid, stype, note, level or 'auto', org_id=org_id)
        else:
            lift_sanction(data, aid, stype, note, org_id=org_id)
    return changes

# ── CLI commands ──────────────────────────────────────────────────────────────

def cmd_apply(args):
    org_id = getattr(args, 'org_id', None)
    data = load_ledger(org_id)
    if apply_sanction(data, args.agent, args.type, args.note, org_id=org_id):
        save_ledger(data, org_id)

def cmd_lift(args):
    org_id = getattr(args, 'org_id', None)
    data = load_ledger(org_id)
    if lift_sanction(data, args.agent, args.type, args.note, org_id=org_id):
        save_ledger(data, org_id)

def cmd_restrictions(args):
    data = load_ledger(getattr(args, 'org_id', None))
    r = get_restrictions(data, args.agent)
    if r:
        print(f"{args.agent} restricted from: {', '.join(r)}")
    else:
        print(f"{args.agent}: no active restrictions")

def cmd_auto_check(args):
    org_id = getattr(args, 'org_id', None)
    data = load_ledger(org_id)
    changes = check_auto_sanctions(data, dry_run=True, org_id=org_id)

    if args.dry_run:
        print(f"Auto-check: {len(changes)} change(s) would apply")
        for kind, aid, stype, note, level in changes:
            print(f"  {kind}: {aid} → {stype} ({note})")
        return

    for kind, aid, stype, note, level in changes:
        if kind == 'apply':
            apply_sanction(data, aid, stype, note, level or 'auto', org_id=org_id)
        else:
            lift_sanction(data, aid, stype, note, org_id=org_id)

    if not changes:
        print("Auto-check: no changes needed")
    save_ledger(data, org_id)

def cmd_show(args):
    data = load_ledger(getattr(args, 'org_id', None))
    print(f"\n{'Agent':<12} {'REP':>5} {'AUTH':>5} {'Prob':<5} {'0Auth':<6} {'Restrictions'}")
    print('-' * 60)
    for aid, agent in data['agents'].items():
        prob  = 'Y' if agent.get('probation')    else '-'
        zauth = 'Y' if agent.get('zero_authority') else '-'
        r     = get_restrictions(data, aid)
        print(f"{aid:<12} {agent['reputation_units']:>5} {agent['authority_units']:>5} "
              f"{prob:<5} {zauth:<6} {', '.join(r) or '-'}")

def main():
    p   = argparse.ArgumentParser(description='Sanction enforcement engine')
    sub = p.add_subparsers(dest='command')

    def add_org_arg(parser):
        parser.add_argument('--org_id', default=None,
                            help='Institution context. Defaults to the legacy founding institution.')

    ap = sub.add_parser('apply')
    add_org_arg(ap)
    ap.add_argument('--agent',  required=True)
    ap.add_argument('--type',   required=True,
                    choices=['probation','zero_authority','lead_ban','remediation_only'])
    ap.add_argument('--note',   default='manual sanction')

    lp = sub.add_parser('lift')
    add_org_arg(lp)
    lp.add_argument('--agent', required=True)
    lp.add_argument('--type',  required=True,
                    choices=['probation','zero_authority','lead_ban','all'])
    lp.add_argument('--note',  default='sanction lifted')

    rp = sub.add_parser('restrictions')
    add_org_arg(rp)
    rp.add_argument('--agent', required=True)

    ac = sub.add_parser('auto-check')
    add_org_arg(ac)
    ac.add_argument('--dry-run', action='store_true')

    show = sub.add_parser('show')
    add_org_arg(show)

    args = p.parse_args()
    if   args.command == 'apply':        cmd_apply(args)
    elif args.command == 'lift':         cmd_lift(args)
    elif args.command == 'restrictions': cmd_restrictions(args)
    elif args.command == 'auto-check':   cmd_auto_check(args)
    elif args.command == 'show':         cmd_show(args)
    else:                                p.print_help()

if __name__ == '__main__':
    main()
