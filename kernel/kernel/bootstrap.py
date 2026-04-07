#!/usr/bin/env python3
"""
Bootstrap Meridian Kernel platform state.

Creates the founding organization and registers all existing agents
into the agent registry. Safe to re-run -- skips if data already exists.

Reference behavior:
  This bootstrap path seeds the founding institution from the checked-in
  economy/ledger.json sample state, then materializes capsule-backed
  governance files around it.  It is the supported local reference path,
  not a generic production multi-institution provisioning service.

Usage:
  python3 bootstrap.py
"""
import json
import os
import sys

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PLATFORM_DIR)

from organizations import load_orgs, save_orgs, create_org, _now, DEFAULT_POLICY_DEFAULTS
from agent_registry import load_registry, save_registry, _now as _reg_now
from audit import log_event
from capsule import capsule_path, init_capsule
from authority import _load_queue, _save_queue
from court import _load_records, _save_records
from treasury import (load_wallets, load_treasury_accounts, load_maintainers,
                      load_contributors, load_payout_proposals, load_funding_sources)
from payout_plan_preview_queue import load_payout_plan_preview_queue

WORKSPACE = os.path.dirname(PLATFORM_DIR)
LEDGER_FILE = os.path.join(WORKSPACE, 'economy', 'ledger.json')

# Defaults for the demo institution -- override via bootstrap() parameters
_DEFAULT_ORG_NAME = 'Demo Org'
_DEFAULT_ORG_OWNER = 'user_owner'
_DEFAULT_ORG_SLUG = 'demo-org'
_DEFAULT_ORG_CHARTER = (
    'Reference demo institution for exercising Meridian governance locally '
    'across institution, agent, authority, treasury, and court.'
)


def bootstrap(name=None, owner_id=None, slug=None, charter=None, plan='enterprise'):
    """Bootstrap an institution with agents.

    All parameters are optional -- defaults create a demo institution suitable
    for local experimentation.  Re-running is safe (idempotent).
    """
    org_name = name or _DEFAULT_ORG_NAME
    org_owner = owner_id or _DEFAULT_ORG_OWNER
    org_slug = slug or _DEFAULT_ORG_SLUG
    org_charter = charter or _DEFAULT_ORG_CHARTER

    # -- 1. Create founding organization --------------------------------------
    orgs = load_orgs()
    founding_org_id = None
    reuse_meridian = (
        not name and not owner_id and not slug and not charter and org_slug == _DEFAULT_ORG_SLUG
    )

    if reuse_meridian:
        for oid, org in orgs['organizations'].items():
            if org.get('slug') == 'meridian':
                founding_org_id = oid
                org_name = org.get('name') or 'Meridian'
                org_owner = org.get('owner_id') or org_owner
                org_slug = org.get('slug') or 'meridian'
                org_charter = org.get('charter') or org_charter
                print(f'Reusing existing Meridian org: {oid}')
                break

    if not founding_org_id:
        for oid, org in orgs['organizations'].items():
            if org.get('slug') == org_slug:
                founding_org_id = oid
                print(f'Founding org already exists: {oid}')
                break

    if not founding_org_id:
        founding_org_id = create_org(
            name=org_name,
            owner_id=org_owner,
            plan=plan,
        )
        # Override slug to canonical value
        orgs = load_orgs()
        orgs['organizations'][founding_org_id]['slug'] = org_slug
        save_orgs(orgs)
        print(f'Created founding org: {founding_org_id}')

    # -- 1b. Backfill institution fields on founding org ----------------------
    orgs = load_orgs()
    org = orgs['organizations'].get(founding_org_id, {})
    backfilled_org = False
    if org.get('name') != org_name:
        org['name'] = org_name
        backfilled_org = True
    if org.get('owner_id') != org_owner:
        org['owner_id'] = org_owner
        backfilled_org = True
    if org.get('slug') != org_slug:
        org['slug'] = org_slug
        backfilled_org = True
    if not org.get('charter'):
        org['charter'] = org_charter
        backfilled_org = True
    if 'policy_defaults' not in org:
        org['policy_defaults'] = dict(DEFAULT_POLICY_DEFAULTS)
        backfilled_org = True
    canonical_treasury_id = f'capsule://{founding_org_id}/treasury'
    if org.get('treasury_id') != canonical_treasury_id:
        org['treasury_id'] = canonical_treasury_id
        backfilled_org = True
    if 'lifecycle_state' not in org:
        org['lifecycle_state'] = 'active'
        backfilled_org = True
    if 'settings' not in org:
        org['settings'] = {}
        backfilled_org = True
    members = org.get('members', [])
    if members and isinstance(members[0], str):
        org['members'] = [
            {
                'user_id': member_id,
                'role': 'owner' if member_id == org.get('owner_id') else 'member',
                'added_at': _now(),
            }
            for member_id in members
        ]
        backfilled_org = True
    if backfilled_org:
        save_orgs(orgs)
        print('  Backfilled institution fields on founding org')

    # -- 2. Register agents from the reference founding ledger ----------------
    if not os.path.exists(LEDGER_FILE):
        print(f'No ledger at {LEDGER_FILE}, skipping agent registration')
        return

    with open(LEDGER_FILE) as f:
        ledger = json.load(f)

    founding_ledger_path = capsule_path(founding_org_id, 'ledger.json')
    if not os.path.exists(founding_ledger_path):
        init_capsule(founding_org_id, ledger_template=ledger)
        print(f'  Initialized capsule for {founding_org_id}')

    registry = load_registry()

    # Map ledger keys to agent definitions
    agent_defs = {
        'main': {
            'name': 'Manager',
            'role': 'manager',
            'purpose': 'Manager and orchestrator. Routes work, sequences pipeline, verifies evidence, closes loops.',
            'scopes': ['manage', 'delegate', 'deliver', 'score', 'research', 'write'],
            'budget': {'max_per_run_usd': 1.00, 'max_per_day_usd': 10.00, 'max_per_month_usd': 200.00},
        },
        'atlas': {
            'name': 'Atlas',
            'role': 'analyst',
            'purpose': 'Research, analysis, exploration, synthesis, and option framing.',
            'scopes': ['research', 'read', 'analyze'],
            'budget': {'max_per_run_usd': 0.50, 'max_per_day_usd': 5.00, 'max_per_month_usd': 100.00},
        },
        'sentinel': {
            'name': 'Sentinel',
            'role': 'verifier',
            'purpose': 'Verification, risk review, contradiction checking, narrow QA.',
            'scopes': ['verify', 'read', 'audit'],
            'budget': {'max_per_run_usd': 0.30, 'max_per_day_usd': 3.00, 'max_per_month_usd': 50.00},
        },
        'forge': {
            'name': 'Forge',
            'role': 'executor',
            'purpose': 'Implementation, file edits, operational steps, execution handoff.',
            'scopes': ['execute', 'write', 'deploy'],
            'budget': {'max_per_run_usd': 0.50, 'max_per_day_usd': 5.00, 'max_per_month_usd': 100.00},
        },
        'quill': {
            'name': 'Quill',
            'role': 'writer',
            'purpose': 'Product writing, release notes, structured deliverables, briefs.',
            'scopes': ['write', 'read', 'deliver'],
            'budget': {'max_per_run_usd': 0.40, 'max_per_day_usd': 4.00, 'max_per_month_usd': 80.00},
        },
        'aegis': {
            'name': 'Aegis',
            'role': 'qa_gate',
            'purpose': 'QA gate, acceptance testing, standards checking, output validation.',
            'scopes': ['verify', 'read', 'qa'],
            'budget': {'max_per_run_usd': 0.30, 'max_per_day_usd': 3.00, 'max_per_month_usd': 50.00},
        },
        'pulse': {
            'name': 'Pulse',
            'role': 'compressor',
            'purpose': 'Context compression, session triage, summarization, support ops.',
            'scopes': ['read', 'compress', 'triage'],
            'budget': {'max_per_run_usd': 0.20, 'max_per_day_usd': 2.00, 'max_per_month_usd': 40.00},
        },
    }

    registered = 0

    # Precompute existing agents for the founding org to allow O(1) lookups.
    # We match by economy_key+org_id or name+org_id.
    existing_by_economy_key = {}
    existing_by_name = {}
    for existing in registry['agents'].values():
        if existing.get('org_id') == founding_org_id:
            ekey = existing.get('economy_key')
            if ekey:
                existing_by_economy_key[ekey] = existing
            name = existing.get('name')
            if name:
                existing_by_name[name] = existing

    for ledger_key, agent_def in agent_defs.items():
        # Check if already registered — match by economy_key+org_id (stable),
        # fall back to name+org_id for agents created before economy_key existed.
        already_exists = False
        existing = existing_by_economy_key.get(ledger_key) or existing_by_name.get(agent_def['name'])

        if existing:
            already_exists = True
            # Ensure economy_key is set (backfill for pre-economy_key agents)
            if existing.get('economy_key') != ledger_key:
                existing['economy_key'] = ledger_key
            # Sync scores from ledger
            ledger_agent = ledger['agents'].get(ledger_key, {})
            existing['reputation_units'] = ledger_agent.get('reputation_units', existing['reputation_units'])
            existing['authority_units'] = ledger_agent.get('authority_units', existing['authority_units'])
            existing['last_active_at'] = ledger_agent.get('last_scored_at', existing['last_active_at'])
            print(f'  Agent {existing["name"]} already registered (economy_key={ledger_key}), synced scores')

        if not already_exists:
            agent_id = f'agent_{agent_def["name"].lower()}'
            ledger_agent = ledger['agents'].get(ledger_key, {})

            registry['agents'][agent_id] = {
                'id': agent_id,
                'org_id': founding_org_id,
                'name': agent_def['name'],
                'role': agent_def['role'],
                'economy_key': ledger_key,
                'purpose': agent_def['purpose'],
                'model_policy': {
                    'allowed_models': [],
                    'max_context_tokens': 200000,
                    'max_output_tokens': 16000,
                },
                'scopes': agent_def['scopes'],
                'budget': agent_def['budget'],
                'approval_required': False,
                'rollout_state': 'active',
                'sla': {
                    'max_latency_seconds': 120,
                    'availability_target': 0.95,
                },
                'reputation_units': ledger_agent.get('reputation_units', 100),
                'authority_units': ledger_agent.get('authority_units', 100),
                'status': ledger_agent.get('status', 'active'),
                'created_at': _reg_now(),
                'last_active_at': ledger_agent.get('last_scored_at', _reg_now()),
            }
            registered += 1
            print(f'  Registered: {agent_id} ({agent_def["name"]})')

    save_registry(registry)
    print(f'\nRegistered {registered} new agents, org={founding_org_id}')

    # -- 2b. Backfill new agent fields ----------------------------------------
    registry = load_registry()
    backfilled_agents = 0
    for agent_id, agent in registry['agents'].items():
        changed = False
        if 'sponsor_id' not in agent:
            agent['sponsor_id'] = None
            changed = True
        if 'risk_state' not in agent:
            agent['risk_state'] = 'nominal'
            changed = True
        if 'lifecycle_state' not in agent:
            agent['lifecycle_state'] = 'active'
            changed = True
        if 'economy_key' not in agent:
            agent['economy_key'] = None
            changed = True
        if 'incident_count' not in agent:
            agent['incident_count'] = 0
            changed = True
        if 'escalation_path' not in agent:
            agent['escalation_path'] = []
            changed = True
        if changed:
            backfilled_agents += 1

    # Map economy_key for each agent
    economy_key_map = {
        'Manager': 'main', 'Leviathann': 'main',
        'Atlas': 'atlas', 'Sentinel': 'sentinel',
        'Forge': 'forge', 'Quill': 'quill', 'Aegis': 'aegis', 'Pulse': 'pulse',
    }
    for agent in registry['agents'].values():
        mapped_key = economy_key_map.get(agent['name'])
        if mapped_key and agent.get('economy_key') != mapped_key:
            agent['economy_key'] = mapped_key
            backfilled_agents += 1

    # Derive risk_state from ledger sanction flags
    for agent in registry['agents'].values():
        ekey = agent.get('economy_key')
        if ekey and ekey in ledger.get('agents', {}):
            la = ledger['agents'][ekey]
            if la.get('zero_authority') or la.get('remediation_only'):
                agent['risk_state'] = 'critical'
            elif la.get('probation'):
                agent['risk_state'] = 'elevated'
            else:
                agent['risk_state'] = 'nominal'

    save_registry(registry)
    if backfilled_agents:
        print(f'  Backfilled fields on {backfilled_agents} agent(s)')

    # -- 2c. Initialize capsule-owned governance files ------------------------
    authority_queue_file = capsule_path(founding_org_id, 'authority_queue.json')
    if not os.path.exists(authority_queue_file):
        _save_queue(_load_queue(founding_org_id), founding_org_id)
        print('  Initialized capsule authority queue')

    court_records_file = capsule_path(founding_org_id, 'court_records.json')
    if not os.path.exists(court_records_file):
        _save_records(_load_records(founding_org_id), founding_org_id)
        print('  Initialized capsule court records')

    protocol_loaders = [
        ('wallets.json', load_wallets),
        ('treasury_accounts.json', load_treasury_accounts),
        ('maintainers.json', load_maintainers),
        ('contributors.json', load_contributors),
        ('payout_proposals.json', load_payout_proposals),
        ('funding_sources.json', load_funding_sources),
        ('payout_plan_preview_queue.json', load_payout_plan_preview_queue),
    ]
    for filename, loader in protocol_loaders:
        protocol_path = capsule_path(founding_org_id, filename)
        if not os.path.exists(protocol_path):
            loader(founding_org_id)
            print(f'  Initialized capsule {filename}')

    # -- 3. Log bootstrap event -----------------------------------------------
    log_event(
        org_id=founding_org_id,
        agent_id='system',
        action='platform_bootstrap',
        resource='agent_registry',
        outcome='success',
        actor_type='system',
        details={
            'agents_registered': registered,
            'org_id': founding_org_id,
            'source': 'bootstrap.py',
        },
    )
    print('\nBootstrap complete.')


if __name__ == '__main__':
    bootstrap()
