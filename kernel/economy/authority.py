#!/usr/bin/env python3
"""
Authority enforcement engine.
AUTH score determines sprint lead eligibility and action rights.
Called by cron payloads and sanctions engine to gate routing decisions.

Usage:
  python3 authority.py sprint-lead
  python3 authority.py check --agent <id> --action <lead|assign|execute|review|remediate>
  python3 authority.py eligible --action <action>
  python3 authority.py show
"""
import argparse
import json
import os
import sys

ECONOMY_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(ECONOMY_DIR)
KERNEL_DIR = os.path.join(ROOT_DIR, 'kernel')

if KERNEL_DIR not in sys.path:
    sys.path.insert(0, KERNEL_DIR)

try:
    from capsule import capsule_path
except ImportError:
    def capsule_path(org_id, filename):
        return os.path.join(ECONOMY_DIR, filename)


def _ledger_path(org_id=None):
    return capsule_path(org_id, 'ledger.json')


def _missing_org_error(org_id):
    raise SystemExit(
        f"ERROR: institution '{org_id}' is not initialized. Run quickstart.py --init-only or bootstrap the capsule first."
    )

# Minimum AUTH to be eligible for lead (even without sanctions)
AUTH_LEAD_THRESHOLD = 30

# Actions and which sanction flags block them
BLOCK_MATRIX = {
    'lead':      ['zero_authority', 'probation', 'lead_ban', 'remediation_only'],
    'assign':    ['zero_authority', 'probation', 'remediation_only'],
    'execute':   ['zero_authority', 'probation', 'remediation_only'],
    'review':    [],
    'observe':   [],
    'remediate': [],  # always allowed — this IS the remediation action
}

def load_ledger(org_id=None):
    path = _ledger_path(org_id)
    if org_id and not os.path.exists(path):
        _missing_org_error(org_id)
    with open(path) as f:
        return json.load(f)

def get_sprint_lead(data):
    """Highest-AUTH active agent that can lead (excludes main -- manager is always manager)."""
    candidates = [
        (aid, agent['authority_units'])
        for aid, agent in data['agents'].items()
        if aid != 'main'
        and agent.get('status') == 'active'
        and not agent.get('zero_authority')
        and not agent.get('probation')
        and not agent.get('lead_ban')
        and not agent.get('remediation_only')
        and agent['authority_units'] >= AUTH_LEAD_THRESHOLD
    ]
    if not candidates:
        return None, 0
    return max(candidates, key=lambda x: x[1])

def check_rights(data, agent_id, action):
    """Returns (allowed: bool, reason: str)."""
    if agent_id not in data['agents']:
        return False, f"unknown agent: {agent_id}"
    agent   = data['agents'][agent_id]
    blockers = BLOCK_MATRIX.get(action, [])
    for flag in blockers:
        if agent.get(flag):
            return False, f"{agent_id} is {flag} — '{action}' blocked"
    # Low-AUTH lead restriction: must meet threshold even without sanctions
    if action == 'lead' and agent['authority_units'] < AUTH_LEAD_THRESHOLD:
        return False, f"{agent_id} AUTH={agent['authority_units']} below lead threshold {AUTH_LEAD_THRESHOLD}"
    return True, "ok"

def get_eligible(data, action):
    return [aid for aid in data['agents'] if check_rights(data, aid, action)[0]]

# ── CLI commands ──────────────────────────────────────────────────────────────

def cmd_sprint_lead(args):
    data = load_ledger(getattr(args, 'org_id', None))
    lead_id, auth = get_sprint_lead(data)
    if not lead_id:
        print("SPRINT_LEAD: NONE (no eligible agent)")
        sys.exit(1)
    agent = data['agents'][lead_id]
    print(f"SPRINT_LEAD: {lead_id} | {agent['name']} | AUTH={auth}")

def cmd_check(args):
    data = load_ledger(getattr(args, 'org_id', None))
    allowed, reason = check_rights(data, args.agent, args.action)
    if allowed:
        print(f"ALLOWED: {args.agent} may perform '{args.action}'")
        sys.exit(0)
    else:
        print(f"BLOCKED: {reason}")
        sys.exit(1)

def cmd_eligible(args):
    data = load_ledger(getattr(args, 'org_id', None))
    agents = get_eligible(data, args.action)
    print(f"ELIGIBLE for '{args.action}': {', '.join(agents) if agents else 'none'}")

def cmd_show(args):
    data = load_ledger(getattr(args, 'org_id', None))
    lead_id, _ = get_sprint_lead(data)
    print(f"\n{'Agent':<12} {'Name':<14} {'AUTH':>5} {'Lead?':<6} {'Flags'}")
    print('-' * 56)
    for aid, agent in data['agents'].items():
        flags = [f for f in ('zero_authority', 'probation', 'lead_ban') if agent.get(f)]
        allowed, _ = check_rights(data, aid, 'lead')
        lead_str   = 'LEAD*' if aid == lead_id else ('YES' if (allowed and aid != 'main') else 'no')
        print(f"{aid:<12} {agent['name']:<14} {agent['authority_units']:>5} {lead_str:<6} "
              f"{', '.join(flags) or '-'}")
    print(f"\nCurrent sprint lead: {lead_id or 'NONE'}")

def main():
    p   = argparse.ArgumentParser(description='Authority enforcement engine')
    sub = p.add_subparsers(dest='command')

    def add_org_arg(parser):
        parser.add_argument('--org_id', default=None,
                            help='Institution context. Defaults to the legacy founding institution.')

    sl = sub.add_parser('sprint-lead')
    add_org_arg(sl)

    chk = sub.add_parser('check')
    add_org_arg(chk)
    chk.add_argument('--agent',  required=True)
    chk.add_argument('--action', required=True, choices=list(BLOCK_MATRIX.keys()))

    eli = sub.add_parser('eligible')
    add_org_arg(eli)
    eli.add_argument('--action', required=True, choices=list(BLOCK_MATRIX.keys()))

    show = sub.add_parser('show')
    add_org_arg(show)

    args = p.parse_args()
    if   args.command == 'sprint-lead': cmd_sprint_lead(args)
    elif args.command == 'check':       cmd_check(args)
    elif args.command == 'eligible':    cmd_eligible(args)
    elif args.command == 'show':        cmd_show(args)
    else:                               p.print_help()

if __name__ == '__main__':
    main()
