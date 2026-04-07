#!/usr/bin/env python3
"""
Authority primitive for Meridian Constitutional OS.

Institution scope:
  Founding-institution-only.  All functions accept org_id but
  _resolve_org_id() enforces that only the founding org (slug='meridian')
  is valid.  Authority queue state resolves through capsule_path() to the
  founding org's capsule directory.

Composes over economy/authority.py — adds approval queues, delegations,
and a kill switch. Economy module handles the scoring math; this module
handles governance workflow.

Usage:
  python3 authority.py check --agent <id> --action <action>
  python3 authority.py request --agent <id> --action <action> --resource <res> [--cost 0.0]
  python3 authority.py decide --approval_id <id> --decision approve|deny --by <who> [--reason "..."]
  python3 authority.py delegate --from <agent> --to <agent> --scopes "lead,assign" [--hours 24]
  python3 authority.py revoke --delegation_id <id>
  python3 authority.py kill-switch on --by <who> --reason "..."
  python3 authority.py kill-switch off --by <who>
  python3 authority.py show
"""
import argparse
import datetime
import json
import os
import sys
import uuid

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(PLATFORM_DIR))
ECONOMY_DIR = os.path.join(WORKSPACE, 'economy')
QUEUE_FILE = os.path.join(PLATFORM_DIR, 'authority_queue.json')

if PLATFORM_DIR not in sys.path:
    sys.path.insert(0, PLATFORM_DIR)

from capsule import capsule_path, ensure_capsule, ensure_treasury_aliases, ledger_path as capsule_ledger_path

# Import economy authority module (avoid name collision with this file)
import importlib.util
_spec = importlib.util.spec_from_file_location('econ_authority', os.path.join(ECONOMY_DIR, 'authority.py'))
_econ_auth_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_econ_auth_mod)
_econ_check_rights = _econ_auth_mod.check_rights
_econ_sprint_lead = _econ_auth_mod.get_sprint_lead
BLOCK_MATRIX = _econ_auth_mod.BLOCK_MATRIX


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _default_org_id():
    try:
        from organizations import load_orgs
        for oid, org in load_orgs().get('organizations', {}).items():
            if org.get('slug') == 'meridian':
                return oid
    except Exception:
        pass
    return None


def _resolve_org_id(org_id=None):
    founding_org_id = _default_org_id()
    if org_id and founding_org_id and org_id != founding_org_id:
        raise ValueError(
            f'Live authority only supports founding org {founding_org_id}, got {org_id}'
        )
    return org_id or founding_org_id


def _matches_org(entry_org_id, org_id):
    return not org_id or entry_org_id in (None, '', org_id)


def _queue_path(org_id=None):
    return capsule_path(org_id, 'authority_queue.json')


def _queue_has_state(data):
    return (
        bool(data.get('pending_approvals'))
        or bool(data.get('delegations'))
        or bool(data.get('kill_switch', {}).get('engaged'))
    )


def _migrate_legacy_queue_if_needed(org_id=None):
    path = _queue_path(org_id)
    legacy_data = None
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE) as f:
            legacy_data = json.load(f)
    if os.path.exists(path):
        if legacy_data and _queue_has_state(legacy_data):
            with open(path) as f:
                current = json.load(f)
            if not _queue_has_state(current):
                with open(path, 'w') as f:
                    json.dump(legacy_data, f, indent=2)
        return path
    if legacy_data is not None:
        ensure_capsule(org_id)
        with open(path, 'w') as f:
            json.dump(legacy_data, f, indent=2)
        return path
    return path


def _load_queue(org_id=None):
    org_id = _resolve_org_id(org_id)
    path = _migrate_legacy_queue_if_needed(org_id)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {
        'pending_approvals': {},
        'delegations': {},
        'kill_switch': {
            'engaged': False,
            'engaged_by': None,
            'engaged_at': None,
            'reason': '',
        },
        'updatedAt': _now(),
    }


def _save_queue(data, org_id=None):
    data['updatedAt'] = _now()
    org_id = _resolve_org_id(org_id)
    path = _migrate_legacy_queue_if_needed(org_id)
    if not os.path.exists(os.path.dirname(path)):
        ensure_capsule(org_id)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def _load_ledger(org_id=None):
    _resolve_org_id(org_id)
    ensure_treasury_aliases(org_id)
    with open(capsule_ledger_path(org_id)) as f:
        return json.load(f)


# ── Core functions ───────────────────────────────────────────────────────────

def check_authority(agent_id, action, org_id=None):
    """Check if agent can perform action. Returns (allowed, reason).
    Checks kill switch, delegations, then economy authority."""
    org_id = _resolve_org_id(org_id)
    queue = _load_queue(org_id)

    # Kill switch overrides everything except owner
    if queue['kill_switch']['engaged']:
        return False, f"Kill switch engaged: {queue['kill_switch']['reason']}"

    # Check delegations — if someone delegated this scope to the agent
    for d in queue['delegations'].values():
        if not _matches_org(d.get('org_id'), org_id):
            continue
        if d['to_agent_id'] == agent_id and action in d.get('scopes', []):
            if d['expires_at'] > _now():
                return True, f"Delegated by {d['from_agent_id']} (expires {d['expires_at']})"

    # Fall through to economy authority check
    ledger = _load_ledger(org_id)
    return _econ_check_rights(ledger, agent_id, action)


def request_approval(agent_id, action, resource, cost_usd=0.0, org_id=None):
    """Create a pending approval request. Returns approval_id."""
    org_id = _resolve_org_id(org_id)
    queue = _load_queue(org_id)
    approval_id = f'apr_{uuid.uuid4().hex[:8]}'
    queue['pending_approvals'][approval_id] = {
        'id': approval_id,
        'org_id': org_id,
        'requester_agent_id': agent_id,
        'action': action,
        'resource': resource,
        'cost_usd': cost_usd,
        'status': 'pending',
        'created_at': _now(),
        'decided_by': None,
        'decided_at': None,
        'reason': '',
    }
    _save_queue(queue, org_id)
    return approval_id


def decide_approval(approval_id, decision, decided_by, reason='', org_id=None):
    """Approve or deny a pending approval. Returns True on success."""
    if decision not in ('approved', 'denied'):
        raise ValueError(f'Invalid decision: {decision}. Must be approved or denied')
    org_id = _resolve_org_id(org_id)
    queue = _load_queue(org_id)
    approval = queue['pending_approvals'].get(approval_id)
    if not approval:
        raise ValueError(f'Approval not found: {approval_id}')
    if not _matches_org(approval.get('org_id'), org_id):
        raise ValueError(f'Approval {approval_id} does not belong to {org_id}')
    if approval['status'] != 'pending':
        raise ValueError(f'Approval {approval_id} is already {approval["status"]}')
    approval['status'] = decision
    approval['decided_by'] = decided_by
    approval['decided_at'] = _now()
    approval['reason'] = reason
    _save_queue(queue, org_id)
    return True


def delegate(from_agent_id, to_agent_id, scopes, duration_hours=24, org_id=None):
    """Create a time-boxed delegation. Returns delegation_id."""
    org_id = _resolve_org_id(org_id)
    queue = _load_queue(org_id)
    delegation_id = f'dlg_{uuid.uuid4().hex[:8]}'
    expires = (datetime.datetime.utcnow() +
               datetime.timedelta(hours=duration_hours)).strftime('%Y-%m-%dT%H:%M:%SZ')
    queue['delegations'][delegation_id] = {
        'id': delegation_id,
        'org_id': org_id,
        'from_agent_id': from_agent_id,
        'to_agent_id': to_agent_id,
        'scopes': scopes,
        'expires_at': expires,
        'created_at': _now(),
    }
    _save_queue(queue, org_id)
    return delegation_id


def revoke_delegation(delegation_id, org_id=None):
    """Remove a delegation."""
    org_id = _resolve_org_id(org_id)
    queue = _load_queue(org_id)
    if delegation_id not in queue['delegations']:
        raise ValueError(f'Delegation not found: {delegation_id}')
    if not _matches_org(queue['delegations'][delegation_id].get('org_id'), org_id):
        raise ValueError(f'Delegation {delegation_id} does not belong to {org_id}')
    del queue['delegations'][delegation_id]
    _save_queue(queue, org_id)


def engage_kill_switch(engaged_by, reason, org_id=None):
    """Halt all non-owner actions."""
    org_id = _resolve_org_id(org_id)
    queue = _load_queue(org_id)
    queue['kill_switch'] = {
        'engaged': True,
        'org_id': org_id,
        'engaged_by': engaged_by,
        'engaged_at': _now(),
        'reason': reason,
    }
    _save_queue(queue, org_id)


def disengage_kill_switch(engaged_by, org_id=None):
    """Resume operations."""
    org_id = _resolve_org_id(org_id)
    queue = _load_queue(org_id)
    queue['kill_switch'] = {
        'engaged': False,
        'org_id': org_id,
        'engaged_by': None,
        'engaged_at': None,
        'reason': '',
    }
    _save_queue(queue, org_id)


def get_sprint_lead(org_id=None):
    """Pass-through to economy authority."""
    _resolve_org_id(org_id)
    ledger = _load_ledger(org_id)
    return _econ_sprint_lead(ledger)


def get_pending_approvals(agent_id=None, org_id=None):
    """List pending approvals, optionally filtered by agent."""
    org_id = _resolve_org_id(org_id)
    queue = _load_queue(org_id)
    approvals = [a for a in queue['pending_approvals'].values() if _matches_org(a.get('org_id'), org_id)]
    if agent_id:
        approvals = [a for a in approvals if a['requester_agent_id'] == agent_id]
    return [a for a in approvals if a['status'] == 'pending']


def is_kill_switch_engaged(org_id=None):
    """Check if kill switch is active."""
    queue = _load_queue(org_id)
    return queue['kill_switch']['engaged']


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description='Authority primitive — approval, delegation, kill switch')
    sub = p.add_subparsers(dest='command')

    chk = sub.add_parser('check')
    chk.add_argument('--agent', required=True)
    chk.add_argument('--action', required=True)
    chk.add_argument('--org_id', default=None)

    req = sub.add_parser('request')
    req.add_argument('--agent', required=True)
    req.add_argument('--action', required=True)
    req.add_argument('--resource', required=True)
    req.add_argument('--cost', type=float, default=0.0)
    req.add_argument('--org_id', default=None)

    dec = sub.add_parser('decide')
    dec.add_argument('--approval_id', required=True)
    dec.add_argument('--decision', required=True, choices=['approve', 'deny'])
    dec.add_argument('--by', required=True)
    dec.add_argument('--reason', default='')
    dec.add_argument('--org_id', default=None)

    dlg = sub.add_parser('delegate')
    dlg.add_argument('--from', dest='from_agent', required=True)
    dlg.add_argument('--to', dest='to_agent', required=True)
    dlg.add_argument('--scopes', required=True)
    dlg.add_argument('--hours', type=int, default=24)
    dlg.add_argument('--org_id', default=None)

    rev = sub.add_parser('revoke')
    rev.add_argument('--delegation_id', required=True)
    rev.add_argument('--org_id', default=None)

    ks = sub.add_parser('kill-switch')
    ks.add_argument('mode', choices=['on', 'off'])
    ks.add_argument('--by', required=True)
    ks.add_argument('--reason', default='')
    ks.add_argument('--org_id', default=None)

    sh = sub.add_parser('show')
    sh.add_argument('--org_id', default=None)

    args = p.parse_args()

    if args.command == 'check':
        allowed, reason = check_authority(args.agent, args.action, org_id=args.org_id)
        status = 'ALLOWED' if allowed else 'BLOCKED'
        print(f'{status}: {reason}')
        sys.exit(0 if allowed else 1)
    elif args.command == 'request':
        aid = request_approval(args.agent, args.action, args.resource, args.cost, org_id=args.org_id)
        print(f'Approval requested: {aid}')
    elif args.command == 'decide':
        decision = 'approved' if args.decision == 'approve' else 'denied'
        decide_approval(args.approval_id, decision, args.by, args.reason, org_id=args.org_id)
        print(f'Approval {args.approval_id}: {decision}')
    elif args.command == 'delegate':
        scopes = [s.strip() for s in args.scopes.split(',')]
        did = delegate(args.from_agent, args.to_agent, scopes, args.hours, org_id=args.org_id)
        print(f'Delegation created: {did}')
    elif args.command == 'revoke':
        revoke_delegation(args.delegation_id, org_id=args.org_id)
        print(f'Delegation revoked: {args.delegation_id}')
    elif args.command == 'kill-switch':
        if args.mode == 'on':
            engage_kill_switch(args.by, args.reason, org_id=args.org_id)
            print('Kill switch ENGAGED')
        else:
            disengage_kill_switch(args.by, org_id=args.org_id)
            print('Kill switch DISENGAGED')
    elif args.command == 'show':
        resolved_org_id = _resolve_org_id(args.org_id)
        queue = _load_queue(resolved_org_id)
        ks = queue['kill_switch']
        print(f"\n=== Authority State ===")
        print(f"Kill switch: {'ENGAGED' if ks['engaged'] else 'off'}", end='')
        if ks['engaged']:
            print(f" (by {ks['engaged_by']} at {ks['engaged_at']}: {ks['reason']})")
        else:
            print()

        pending = get_pending_approvals(org_id=resolved_org_id)
        print(f"\nPending approvals: {len(pending)}")
        for a in pending:
            print(f"  {a['id']}  agent={a['requester_agent_id']}  action={a['action']}  resource={a['resource']}  cost=${a['cost_usd']}")

        active_delegations = [
            d for d in queue['delegations'].values()
            if d['expires_at'] > _now() and _matches_org(d.get('org_id'), resolved_org_id)
        ]
        print(f"\nActive delegations: {len(active_delegations)}")
        for d in active_delegations:
            print(f"  {d['id']}  {d['from_agent_id']} -> {d['to_agent_id']}  scopes={d['scopes']}  expires={d['expires_at']}")

        lead_id, lead_auth = get_sprint_lead(resolved_org_id)
        print(f"\nSprint lead: {lead_id or 'NONE'} (AUTH={lead_auth})")
    else:
        p.print_help()


if __name__ == '__main__':
    main()
