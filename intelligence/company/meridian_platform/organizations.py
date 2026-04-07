#!/usr/bin/env python3
"""
Organization / Tenant model for Meridian.

Every resource in Meridian belongs to an organization.
Organizations scope agents, subscriptions, usage, and billing.

Usage:
  python3 organizations.py create --name "Acme Corp" --owner_id "user_123"
  python3 organizations.py get --org_id <id>
  python3 organizations.py list
  python3 organizations.py add-member --org_id <id> --user_id <uid> --role member
  python3 organizations.py update --org_id <id> --plan pro
  python3 organizations.py suspend --org_id <id>
"""
import argparse
import datetime
import json
import os
import uuid

import organizations_store

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
ORGS_FILE = os.path.join(PLATFORM_DIR, 'organizations.json')

VALID_ROLES = ('owner', 'admin', 'member', 'viewer')
VALID_PLANS = ('free', 'trial', 'starter', 'pro', 'enterprise')
VALID_STATUSES = ('active', 'suspended', 'closed')
VALID_LIFECYCLE_STATES = ('founding', 'active', 'suspended', 'dissolved')

DEFAULT_POLICY_DEFAULTS = {
    'max_budget_per_agent_usd': 10.0,
    'require_approval_above_usd': 5.0,
    'auto_sanctions_enabled': True,
    'auth_decay_per_epoch': 5,
}


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _slug(name):
    return name.lower().replace(' ', '-').replace('_', '-')[:40]


def load_orgs():
    return organizations_store.load_orgs(ORGS_FILE)


def save_orgs(data):
    data = dict(data or {})
    data.setdefault('organizations', {})
    data['updatedAt'] = _now()
    organizations_store.save_orgs(ORGS_FILE, data)
    return data


def create_org(name, owner_id, plan='free'):
    data = load_orgs()
    org_id = f'org_{uuid.uuid4().hex[:8]}'
    slug = _slug(name)

    # Ensure slug uniqueness
    existing_slugs = {o['slug'] for o in data['organizations'].values()}
    if slug in existing_slugs:
        slug = f'{slug}-{uuid.uuid4().hex[:4]}'

    data['organizations'][org_id] = {
        'id': org_id,
        'name': name,
        'slug': slug,
        'owner_id': owner_id,
        'members': [
            {'user_id': owner_id, 'role': 'owner', 'added_at': _now()}
        ],
        'plan': plan,
        'status': 'active',
        'charter': '',
        'policy_defaults': dict(DEFAULT_POLICY_DEFAULTS),
        'treasury_id': None,
        'lifecycle_state': 'active',
        'settings': {},
        'created_at': _now(),
    }
    save_orgs(data)
    return org_id


def get_org(org_id):
    data = load_orgs()
    return data['organizations'].get(org_id)


def list_orgs(status_filter=None):
    data = load_orgs()
    orgs = list(data['organizations'].values())
    if status_filter:
        orgs = [o for o in orgs if o['status'] == status_filter]
    return orgs


def add_member(org_id, user_id, role='member'):
    if role not in VALID_ROLES:
        raise ValueError(f'Invalid role: {role}. Must be one of {VALID_ROLES}')
    data = load_orgs()
    org = data['organizations'].get(org_id)
    if not org:
        raise ValueError(f'Organization not found: {org_id}')

    # Check for existing membership
    for m in org['members']:
        if m['user_id'] == user_id:
            m['role'] = role
            save_orgs(data)
            return

    org['members'].append({
        'user_id': user_id,
        'role': role,
        'added_at': _now(),
    })
    save_orgs(data)


def update_org(org_id, **kwargs):
    data = load_orgs()
    org = data['organizations'].get(org_id)
    if not org:
        raise ValueError(f'Organization not found: {org_id}')

    if 'plan' in kwargs and kwargs['plan'] not in VALID_PLANS:
        raise ValueError(f'Invalid plan: {kwargs["plan"]}')
    if 'status' in kwargs and kwargs['status'] not in VALID_STATUSES:
        raise ValueError(f'Invalid status: {kwargs["status"]}')

    for key in ('name', 'plan', 'status'):
        if key in kwargs and kwargs[key] is not None:
            org[key] = kwargs[key]

    save_orgs(data)


def get_org_for_user(user_id):
    """Find the first active org where this user is a member."""
    data = load_orgs()
    for org in data['organizations'].values():
        if org['status'] != 'active':
            continue
        for m in org['members']:
            if m['user_id'] == user_id:
                return org
    return None


def set_charter(org_id, charter_text):
    """Set or update an institution's charter."""
    data = load_orgs()
    org = data['organizations'].get(org_id)
    if not org:
        raise ValueError(f'Organization not found: {org_id}')
    org['charter'] = charter_text
    save_orgs(data)


def set_policy_defaults(org_id, **policies):
    """Update policy defaults for an institution."""
    data = load_orgs()
    org = data['organizations'].get(org_id)
    if not org:
        raise ValueError(f'Organization not found: {org_id}')
    pd = org.get('policy_defaults', dict(DEFAULT_POLICY_DEFAULTS))
    for k, v in policies.items():
        if v is not None:
            pd[k] = v
    org['policy_defaults'] = pd
    save_orgs(data)


def transition_lifecycle(org_id, new_state):
    """Transition institution lifecycle state."""
    if new_state not in VALID_LIFECYCLE_STATES:
        raise ValueError(f'Invalid lifecycle state: {new_state}. Must be one of {VALID_LIFECYCLE_STATES}')
    data = load_orgs()
    org = data['organizations'].get(org_id)
    if not org:
        raise ValueError(f'Organization not found: {org_id}')
    current = org.get('lifecycle_state', 'active')
    # State machine: founding->active, active->suspended, suspended->dissolved, suspended->active
    valid_transitions = {
        'founding': ('active',),
        'active': ('suspended', 'dissolved'),
        'suspended': ('active', 'dissolved'),
        'dissolved': (),
    }
    allowed = valid_transitions.get(current, ())
    if new_state not in allowed:
        raise ValueError(f'Cannot transition from {current} to {new_state}. Allowed: {allowed}')
    org['lifecycle_state'] = new_state
    save_orgs(data)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description='Organization management')
    sub = p.add_subparsers(dest='command')

    c = sub.add_parser('create')
    c.add_argument('--name', required=True)
    c.add_argument('--owner_id', required=True)
    c.add_argument('--plan', default='free')

    g = sub.add_parser('get')
    g.add_argument('--org_id', required=True)

    sub.add_parser('list')

    am = sub.add_parser('add-member')
    am.add_argument('--org_id', required=True)
    am.add_argument('--user_id', required=True)
    am.add_argument('--role', default='member')

    u = sub.add_parser('update')
    u.add_argument('--org_id', required=True)
    u.add_argument('--name', default=None)
    u.add_argument('--plan', default=None)

    s = sub.add_parser('suspend')
    s.add_argument('--org_id', required=True)

    sc = sub.add_parser('set-charter')
    sc.add_argument('--org_id', required=True)
    sc.add_argument('--text', required=True)

    sp = sub.add_parser('set-policy')
    sp.add_argument('--org_id', required=True)
    sp.add_argument('--max_budget_per_agent_usd', type=float, default=None)
    sp.add_argument('--require_approval_above_usd', type=float, default=None)
    sp.add_argument('--auto_sanctions_enabled', type=lambda x: x.lower() == 'true', default=None)
    sp.add_argument('--auth_decay_per_epoch', type=int, default=None)

    lc = sub.add_parser('lifecycle')
    lc.add_argument('--org_id', required=True)
    lc.add_argument('--state', required=True)

    args = p.parse_args()

    if args.command == 'create':
        oid = create_org(args.name, args.owner_id, args.plan)
        print(f'Created organization: {oid}')
    elif args.command == 'get':
        org = get_org(args.org_id)
        print(json.dumps(org, indent=2) if org else f'Not found: {args.org_id}')
    elif args.command == 'list':
        for org in list_orgs():
            print(f"  {org['id']}  {org['name']:<30} plan={org['plan']:<12} status={org['status']}")
    elif args.command == 'add-member':
        add_member(args.org_id, args.user_id, args.role)
        print(f'Added {args.user_id} as {args.role} to {args.org_id}')
    elif args.command == 'update':
        update_org(args.org_id, name=args.name, plan=args.plan)
        print(f'Updated {args.org_id}')
    elif args.command == 'suspend':
        update_org(args.org_id, status='suspended')
        print(f'Suspended {args.org_id}')
    elif args.command == 'set-charter':
        set_charter(args.org_id, args.text)
        print(f'Charter set for {args.org_id}')
    elif args.command == 'set-policy':
        set_policy_defaults(args.org_id,
                            max_budget_per_agent_usd=args.max_budget_per_agent_usd,
                            require_approval_above_usd=args.require_approval_above_usd,
                            auto_sanctions_enabled=args.auto_sanctions_enabled,
                            auth_decay_per_epoch=args.auth_decay_per_epoch)
        print(f'Policy defaults updated for {args.org_id}')
    elif args.command == 'lifecycle':
        transition_lifecycle(args.org_id, args.state)
        print(f'Lifecycle transitioned to {args.state} for {args.org_id}')
    else:
        p.print_help()


if __name__ == '__main__':
    main()
