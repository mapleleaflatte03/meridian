#!/usr/bin/env python3
"""
Bootstrap Meridian platform state.

Creates the founding organization and registers all existing agents
into the agent registry. Safe to re-run — skips if data already exists.

Usage:
  python3 bootstrap.py
"""
import json
import os
import sys

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PLATFORM_DIR)

from organizations import load_orgs, save_orgs, create_org, _now, DEFAULT_POLICY_DEFAULTS
from agent_registry import (
    load_registry,
    save_registry,
    _now as _reg_now,
    runtime_binding_for_org,
)
from audit import log_event
from capsule import (
    ensure_capsule,
    capsule_path,
    ensure_treasury_aliases,
    ensure_subscription_aliases,
    ensure_accounting_aliases,
    ensure_payment_monitor_aliases,
    ensure_revenue_integrity_aliases,
    ledger_path as capsule_ledger_path,
)
from treasury import load_treasury_accounts, load_funding_sources

WORKSPACE = os.path.dirname(os.path.dirname(PLATFORM_DIR))
LEGACY_LEDGER_FILE = os.path.join(WORKSPACE, 'economy', 'ledger.json')


def bootstrap():
    # ── 1. Create founding organization ──────────────────────────────────
    orgs = load_orgs()
    founding_org_id = None

    for oid, org in orgs['organizations'].items():
        if org.get('slug') == 'meridian':
            founding_org_id = oid
            print(f'Founding org already exists: {oid}')
            break

    if not founding_org_id:
        founding_org_id = create_org(
            name='Meridian',
            owner_id='user_meridian_5322393870',
            plan='enterprise',
        )
        # Override slug to canonical value
        orgs = load_orgs()
        orgs['organizations'][founding_org_id]['slug'] = 'meridian'
        save_orgs(orgs)
        print(f'Created founding org: {founding_org_id}')

    # ── 1b. Backfill institution fields on founding org ─────────────────
    orgs = load_orgs()
    org = orgs['organizations'].get(founding_org_id, {})
    backfilled_org = False
    if 'charter' not in org:
        org['charter'] = ''
        backfilled_org = True
    if 'policy_defaults' not in org:
        org['policy_defaults'] = dict(DEFAULT_POLICY_DEFAULTS)
        backfilled_org = True
    expected_treasury_pointer = f'capsule://{founding_org_id}/treasury'
    if org.get('treasury_id') != expected_treasury_pointer:
        org['treasury_id'] = expected_treasury_pointer
        backfilled_org = True
    if 'lifecycle_state' not in org:
        org['lifecycle_state'] = 'active'
        backfilled_org = True
    if 'settings' not in org:
        org['settings'] = {}
        backfilled_org = True
    if backfilled_org:
        save_orgs(orgs)
        print('  Backfilled institution fields on founding org')

    # ── 2. Prepare founding capsule aliases before reading ledger ─────────
    ensure_capsule(founding_org_id)
    try:
        aliases = ensure_treasury_aliases(founding_org_id)
        service_aliases = ensure_subscription_aliases(founding_org_id)
        accounting_aliases = ensure_accounting_aliases(founding_org_id)
        payment_monitor_aliases = ensure_payment_monitor_aliases(founding_org_id)
        revenue_integrity_aliases = ensure_revenue_integrity_aliases(founding_org_id)
        print(
            f"  Treasury aliases ready: {os.path.relpath(aliases['ledger'], WORKSPACE)}, "
            f"{os.path.relpath(aliases['revenue'], WORKSPACE)}, "
            f"{os.path.relpath(aliases['transactions'], WORKSPACE)}"
        )
        print(
            f"  Service aliases ready: {os.path.relpath(service_aliases['subscriptions'], WORKSPACE)}, "
            f"{os.path.relpath(service_aliases['subscriptions_backup'], WORKSPACE)}, "
            f"{os.path.relpath(service_aliases['subscriptions_lock'], WORKSPACE)}, "
            f"{os.path.relpath(accounting_aliases['owner_ledger'], WORKSPACE)}, "
            f"{os.path.relpath(payment_monitor_aliases['payment_monitor_state'], WORKSPACE)}, "
            f"{os.path.relpath(payment_monitor_aliases['payment_events_log'], WORKSPACE)}, "
            f"{os.path.relpath(revenue_integrity_aliases['payment_integrity_lock'], WORKSPACE)}"
        )
    except FileNotFoundError:
        print(f'No ledger at {LEGACY_LEDGER_FILE}, skipping agent registration')
        return

    ledger_file = capsule_ledger_path(founding_org_id)

    with open(ledger_file) as f:
        ledger = json.load(f)

    registry = load_registry()

    # Map ledger keys to agent definitions
    agent_defs = {
        'main': {
            'name': 'Leviathann',
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
    for ledger_key, agent_def in agent_defs.items():
        # Check if already registered (by name match)
        already_exists = False
        for existing in registry['agents'].values():
            if existing['name'] == agent_def['name'] and existing['org_id'] == founding_org_id:
                already_exists = True
                # Sync scores from ledger
                ledger_agent = ledger['agents'].get(ledger_key, {})
                existing['reputation_units'] = ledger_agent.get('reputation_units', existing['reputation_units'])
                existing['authority_units'] = ledger_agent.get('authority_units', existing['authority_units'])
                existing['last_active_at'] = ledger_agent.get('last_scored_at', existing['last_active_at'])
                print(f'  Agent {agent_def["name"]} already registered, synced scores')
                break

        if not already_exists:
            agent_id = f'agent_{agent_def["name"].lower()}'
            ledger_agent = ledger['agents'].get(ledger_key, {})

            registry['agents'][agent_id] = {
                'id': agent_id,
                'org_id': founding_org_id,
                'name': agent_def['name'],
                'role': agent_def['role'],
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
                'runtime_binding': runtime_binding_for_org(founding_org_id),
            }
            registered += 1
            print(f'  Registered: {agent_id} ({agent_def["name"]})')

    save_registry(registry)
    print(f'\nRegistered {registered} new agents, org={founding_org_id}')

    # ── 2b. Backfill new agent fields ────────────────────────────────────
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
        if 'runtime_binding' not in agent:
            agent['runtime_binding'] = runtime_binding_for_org(founding_org_id)
            changed = True
        if changed:
            backfilled_agents += 1

    # Map economy_key for each agent
    economy_key_map = {
        'Leviathann': 'main', 'Atlas': 'atlas', 'Sentinel': 'sentinel',
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

    # ── 2c. Initialize capsule-backed authority/court state ───────────────

    authority_queue_file = capsule_path(founding_org_id, 'authority_queue.json')
    legacy_authority_queue_file = os.path.join(PLATFORM_DIR, 'authority_queue.json')
    if os.path.exists(legacy_authority_queue_file):
        should_copy_legacy = True
        if os.path.exists(authority_queue_file):
            with open(authority_queue_file) as f:
                current = json.load(f)
            should_copy_legacy = bool(
                current.get('pending_approvals')
                or current.get('delegations')
                or current.get('kill_switch', {}).get('engaged')
            ) is False
        if should_copy_legacy:
            with open(legacy_authority_queue_file) as f:
                legacy = json.load(f)
            with open(authority_queue_file, 'w') as f:
                json.dump(legacy, f, indent=2)
            print('  Migrated legacy authority_queue.json into capsule state')
    elif not os.path.exists(authority_queue_file):
        now = _reg_now()
        with open(authority_queue_file, 'w') as f:
            json.dump({
                'pending_approvals': {},
                'delegations': {},
                'kill_switch': {
                    'engaged': False,
                    'engaged_by': None,
                    'engaged_at': None,
                    'reason': '',
                },
                'updatedAt': now,
            }, f, indent=2)
        print('  Initialized capsule authority_queue.json')

    # ── 2d. Initialize court_records.json ─────────────────────────────────
    court_records_file = capsule_path(founding_org_id, 'court_records.json')
    legacy_court_records_file = os.path.join(PLATFORM_DIR, 'court_records.json')
    if os.path.exists(legacy_court_records_file):
        should_copy_legacy = True
        if os.path.exists(court_records_file):
            with open(court_records_file) as f:
                current = json.load(f)
            should_copy_legacy = not (current.get('violations') or current.get('appeals'))
        if should_copy_legacy:
            with open(legacy_court_records_file) as f:
                legacy = json.load(f)
            with open(court_records_file, 'w') as f:
                json.dump(legacy, f, indent=2)
            print('  Migrated legacy court_records.json into capsule state')
    elif not os.path.exists(court_records_file):
        now = _reg_now()
        with open(court_records_file, 'w') as f:
            json.dump({
                'violations': {},
                'appeals': {},
                'updatedAt': now,
            }, f, indent=2)
        print('  Initialized capsule court_records.json')

    # ── 2e. Initialize treasury protocol registries ───────────────────────
    protocol_loaders = [
        ('treasury_accounts.json', load_treasury_accounts),
        ('funding_sources.json', load_funding_sources),
    ]
    for filename, loader in protocol_loaders:
        protocol_path = capsule_path(founding_org_id, filename)
        if not os.path.exists(protocol_path):
            loader(founding_org_id)
            print(f'  Initialized capsule {filename}')

    # ── 3. Log bootstrap event ───────────────────────────────────────────
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
