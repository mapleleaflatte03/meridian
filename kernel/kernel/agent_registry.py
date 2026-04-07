#!/usr/bin/env python3
"""
Agent Registry for Meridian Kernel.

Agents are first-class managed entities with identity, owner, permissions,
budget, model policy, rollout state, and audit trail.

Usage:
  python3 agent_registry.py register --org_id <org> --name Atlas --role analyst --purpose "Research and analysis"
  python3 agent_registry.py get --agent_id <id>
  python3 agent_registry.py list [--org_id <org>]
  python3 agent_registry.py update --agent_id <id> --rollout_state quarantined
  python3 agent_registry.py set-budget --agent_id <id> --max_per_day_usd 5.0
  python3 agent_registry.py set-scopes --agent_id <id> --scopes "read,research,write_brief"
  python3 agent_registry.py disable --agent_id <id>
  python3 agent_registry.py sync-economy  # sync REP/AUTH from economy/ledger.json
"""
import argparse
import datetime
import json
import os
import sys
import uuid
try:
    from io_atomic import atomic_write_json
except ModuleNotFoundError:
    PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
    if PLATFORM_DIR not in sys.path:
        sys.path.insert(0, PLATFORM_DIR)
    from io_atomic import atomic_write_json

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
REGISTRY_FILE = os.path.join(PLATFORM_DIR, 'agent_registry.json')
WORKSPACE = os.path.dirname(PLATFORM_DIR)
LEDGER_FILE = os.path.join(WORKSPACE, 'economy', 'ledger.json')

try:
    from capsule import capsule_path
except ImportError:
    def capsule_path(org_id, filename):
        return os.path.join(WORKSPACE, 'economy', filename)

VALID_ROLLOUT_STATES = ('active', 'staged', 'quarantined', 'disabled')
VALID_ROLES = ('manager', 'analyst', 'verifier', 'executor', 'writer', 'qa_gate', 'compressor')
VALID_RISK_STATES = ('nominal', 'elevated', 'critical', 'suspended')
VALID_LIFECYCLE_STATES = ('provisioned', 'active', 'quarantined', 'decommissioned')
DEFAULT_RUNTIME_ID = 'local_kernel'
DEFAULT_RUNTIME_LABEL = 'Local Kernel Runtime'
RUNTIME_BINDING_BOUNDARY_NAME = 'workspace'
RUNTIME_BINDING_IDENTITY_MODEL = 'session'
RUNTIME_BINDING_BOUNDARY_SCOPE = 'institution_bound'

# Risk auto-escalation thresholds
INCIDENT_ELEVATED_THRESHOLD = 3
INCIDENT_CRITICAL_THRESHOLD = 5


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _runtime_binding_runtime(runtime_id):
    try:
        from runtime_adapter import get_runtime
    except ImportError:
        get_runtime = None
    if get_runtime is None:
        return ({
            'id': runtime_id,
            'label': DEFAULT_RUNTIME_LABEL if runtime_id == DEFAULT_RUNTIME_ID else runtime_id,
        }, runtime_id == DEFAULT_RUNTIME_ID)
    runtime = get_runtime(runtime_id)
    if runtime:
        return runtime, True
    return ({
        'id': runtime_id,
        'label': DEFAULT_RUNTIME_LABEL if runtime_id == DEFAULT_RUNTIME_ID else runtime_id,
    }, False)


def _normalize_runtime_binding(runtime_binding, org_id=None, context_source='agent_registry'):
    if isinstance(runtime_binding, str):
        binding = {'runtime_id': runtime_binding}
    else:
        binding = dict(runtime_binding or {})
    runtime_id = (binding.get('runtime_id') or '').strip() or DEFAULT_RUNTIME_ID
    runtime, runtime_registered = _runtime_binding_runtime(runtime_id)
    binding['runtime_id'] = runtime.get('id', runtime_id)
    binding['runtime_label'] = binding.get('runtime_label') or runtime.get('label', DEFAULT_RUNTIME_LABEL)
    binding['runtime_registered'] = runtime_registered
    binding['registration_status'] = 'registered' if runtime_registered else 'missing_runtime'
    binding['bound_org_id'] = org_id
    binding['context_source'] = context_source
    binding['boundary_name'] = RUNTIME_BINDING_BOUNDARY_NAME
    binding['identity_model'] = RUNTIME_BINDING_IDENTITY_MODEL
    binding['boundary_scope'] = RUNTIME_BINDING_BOUNDARY_SCOPE
    return binding


def _validate_runtime_binding(runtime_binding):
    binding = _normalize_runtime_binding(runtime_binding)
    if not binding.get('runtime_registered'):
        raise ValueError(
            f"Runtime {binding.get('runtime_id')!r} is not declared in kernel/runtimes.json"
        )
    return binding


def _normalize_agent_record(agent):
    if not agent:
        return agent
    normalized = dict(agent)
    normalized['runtime_binding'] = _normalize_runtime_binding(
        normalized.get('runtime_binding'),
        org_id=normalized.get('org_id'),
    )
    return normalized


def normalize_agent_record(agent):
    return _normalize_agent_record(agent)


def _normalize_registry(data):
    data = dict(data or {})
    agents = data.get('agents', {})
    data['agents'] = {
        agent_id: _normalize_agent_record(agent)
        for agent_id, agent in agents.items()
    }
    return data


def load_registry():
    if os.path.exists(REGISTRY_FILE):
        with open(REGISTRY_FILE) as f:
            return _normalize_registry(json.load(f))
    return _normalize_registry({'agents': {}, 'updatedAt': _now()})


def save_registry(data):
    data = _normalize_registry(data)
    data['updatedAt'] = _now()
    atomic_write_json(REGISTRY_FILE, data)


def _org_matches(agent, org_id=None):
    return org_id is None or agent.get('org_id') == org_id


def _ledger_path(org_id=None):
    if org_id is None:
        return LEDGER_FILE
    return capsule_path(org_id, 'ledger.json')


def register_agent(org_id, name, role, purpose, scopes=None, model_policy=None,
                    budget=None, approval_required=False, runtime_binding=None):
    data = load_registry()
    agent_id = f'agent_{name.lower()}_{uuid.uuid4().hex[:6]}'
    normalized_runtime_binding = _validate_runtime_binding(runtime_binding)

    data['agents'][agent_id] = {
        'id': agent_id,
        'org_id': org_id,
        'name': name,
        'role': role,
        'purpose': purpose,
        'model_policy': model_policy or {
            'allowed_models': [],
            'max_context_tokens': 200000,
            'max_output_tokens': 16000,
        },
        'scopes': scopes or [],
        'budget': budget or {
            'max_per_run_usd': 0.50,
            'max_per_day_usd': 5.00,
            'max_per_month_usd': 100.00,
        },
        'approval_required': approval_required,
        'rollout_state': 'active',
        'runtime_binding': _normalize_runtime_binding(normalized_runtime_binding, org_id=org_id),
        'sla': {
            'max_latency_seconds': 120,
            'availability_target': 0.95,
        },
        'reputation_units': 100,
        'authority_units': 100,
        'sponsor_id': None,
        'risk_state': 'nominal',
        'lifecycle_state': 'active',
        'economy_key': None,
        'incident_count': 0,
        'escalation_path': [],
        'status': 'active',
        'created_at': _now(),
        'last_active_at': _now(),
    }
    save_registry(data)
    return agent_id


def get_agent(agent_id, org_id=None):
    data = load_registry()
    agent = data['agents'].get(agent_id)
    if agent and _org_matches(agent, org_id):
        return _normalize_agent_record(agent)
    return None


def list_agents(org_id=None, include_disabled=False):
    data = load_registry()
    agents = list(data['agents'].values())
    if org_id:
        agents = [a for a in agents if a['org_id'] == org_id]
    if not include_disabled:
        agents = [a for a in agents if a['rollout_state'] != 'disabled']
    return [_normalize_agent_record(agent) for agent in agents]


def update_agent(agent_id, **kwargs):
    data = load_registry()
    agent = data['agents'].get(agent_id)
    if not agent:
        raise ValueError(f'Agent not found: {agent_id}')

    if 'rollout_state' in kwargs and kwargs['rollout_state'] not in VALID_ROLLOUT_STATES:
        raise ValueError(f'Invalid rollout state: {kwargs["rollout_state"]}')

    for key in ('name', 'purpose', 'rollout_state', 'approval_required', 'status', 'runtime_binding'):
        if key in kwargs and kwargs[key] is not None:
            if key == 'runtime_binding':
                validated = _validate_runtime_binding(kwargs[key])
                agent[key] = _normalize_runtime_binding(validated, org_id=agent.get('org_id'))
                continue
            agent[key] = kwargs[key]

    agent['last_active_at'] = _now()
    save_registry(data)


def set_budget(agent_id, max_per_run_usd=None, max_per_day_usd=None, max_per_month_usd=None):
    data = load_registry()
    agent = data['agents'].get(agent_id)
    if not agent:
        raise ValueError(f'Agent not found: {agent_id}')

    if max_per_run_usd is not None:
        agent['budget']['max_per_run_usd'] = max_per_run_usd
    if max_per_day_usd is not None:
        agent['budget']['max_per_day_usd'] = max_per_day_usd
    if max_per_month_usd is not None:
        agent['budget']['max_per_month_usd'] = max_per_month_usd
    save_registry(data)


def set_scopes(agent_id, scopes):
    data = load_registry()
    agent = data['agents'].get(agent_id)
    if not agent:
        raise ValueError(f'Agent not found: {agent_id}')
    agent['scopes'] = scopes
    save_registry(data)


def check_budget(agent_id, cost_usd):
    """Check if an agent can spend the given amount. Returns (allowed, reason)."""
    agent = resolve_agent(agent_id)
    if not agent:
        return False, 'Agent not found'
    if agent['rollout_state'] in ('quarantined', 'disabled'):
        return False, f'Agent is {agent["rollout_state"]}'
    if cost_usd > agent['budget']['max_per_run_usd']:
        return False, f'Exceeds per-run budget (${agent["budget"]["max_per_run_usd"]})'
    return True, 'ok'


def check_scope(agent_id, required_scope):
    """Check if an agent has the required scope. Returns (allowed, reason)."""
    agent = resolve_agent(agent_id)
    if not agent:
        return False, 'Agent not found'
    if not agent['scopes']:
        return True, 'No scope restrictions (open)'
    if required_scope in agent['scopes']:
        return True, 'ok'
    return False, f'Missing scope: {required_scope}'


def set_risk_state(agent_id, state):
    """Update an agent's risk state with validation."""
    if state not in VALID_RISK_STATES:
        raise ValueError(f'Invalid risk state: {state}. Must be one of {VALID_RISK_STATES}')
    data = load_registry()
    agent = data['agents'].get(agent_id)
    if not agent:
        raise ValueError(f'Agent not found: {agent_id}')
    agent['risk_state'] = state
    save_registry(data)


def transition_lifecycle(agent_id, new_state):
    """Transition agent lifecycle state."""
    if new_state not in VALID_LIFECYCLE_STATES:
        raise ValueError(f'Invalid lifecycle state: {new_state}. Must be one of {VALID_LIFECYCLE_STATES}')
    data = load_registry()
    agent = data['agents'].get(agent_id)
    if not agent:
        raise ValueError(f'Agent not found: {agent_id}')
    current = agent.get('lifecycle_state', 'active')
    valid_transitions = {
        'provisioned': ('active',),
        'active': ('quarantined', 'decommissioned'),
        'quarantined': ('active', 'decommissioned'),
        'decommissioned': (),
    }
    allowed = valid_transitions.get(current, ())
    if new_state not in allowed:
        raise ValueError(f'Cannot transition from {current} to {new_state}. Allowed: {allowed}')
    agent['lifecycle_state'] = new_state
    save_registry(data)


def record_incident(agent_id):
    """Increment incident count, auto-escalate risk if threshold hit."""
    data = load_registry()
    agent = data['agents'].get(agent_id)
    if not agent:
        raise ValueError(f'Agent not found: {agent_id}')
    agent['incident_count'] = agent.get('incident_count', 0) + 1
    count = agent['incident_count']
    if count >= INCIDENT_CRITICAL_THRESHOLD:
        agent['risk_state'] = 'critical'
    elif count >= INCIDENT_ELEVATED_THRESHOLD:
        agent['risk_state'] = 'elevated'
    save_registry(data)
    return count


def get_agents_by_economy_key(economy_key, org_id=None):
    """Lookup all agents matching an economy ledger key, optionally scoped to an institution."""
    data = load_registry()
    matches = []
    for agent in data['agents'].values():
        if agent.get('economy_key') == economy_key and _org_matches(agent, org_id):
            matches.append(_normalize_agent_record(agent))
    return matches


def get_agent_by_economy_key(economy_key, org_id=None):
    """Lookup a single agent by economy ledger key.

    Returns None when the lookup is ambiguous and no org_id is provided.
    """
    matches = get_agents_by_economy_key(economy_key, org_id=org_id)
    if not matches:
        return None
    if org_id is None and len(matches) != 1:
        return None
    return matches[0]


def resolve_agent(agent_ref, org_id=None):
    """Resolve an agent by registry id first, then by economy_key with org scoping."""
    agent = get_agent(agent_ref, org_id=org_id)
    if agent:
        return agent
    return get_agent_by_economy_key(agent_ref, org_id=org_id)


def sync_from_economy(org_id=None):
    """Sync REP/AUTH and sanction flags from the relevant ledger into the agent registry."""
    ledger_path = _ledger_path(org_id)
    if not os.path.exists(ledger_path):
        print('No ledger found at', ledger_path)
        return

    with open(ledger_path) as f:
        ledger = json.load(f)

    data = load_registry()
    synced = 0

    for agent in data['agents'].values():
        if org_id is not None and agent.get('org_id') != org_id:
            continue
        # Match by economy_key first, then by name
        ledger_agent = None
        ekey = agent.get('economy_key')
        if ekey and ekey in ledger.get('agents', {}):
            ledger_agent = ledger['agents'][ekey]
        else:
            agent_name = agent['name'].lower()
            for lk, la in ledger.get('agents', {}).items():
                if la.get('name', '').lower() == agent_name:
                    ledger_agent = la
                    break

        if ledger_agent:
            agent['reputation_units'] = ledger_agent.get('reputation_units', agent['reputation_units'])
            agent['authority_units'] = ledger_agent.get('authority_units', agent['authority_units'])
            agent['last_active_at'] = ledger_agent.get('last_scored_at', agent['last_active_at'])
            # Sync sanction flags to risk_state
            if ledger_agent.get('zero_authority') or ledger_agent.get('remediation_only'):
                agent['risk_state'] = 'critical'
            elif ledger_agent.get('probation'):
                agent['risk_state'] = 'elevated'
            else:
                agent['risk_state'] = 'nominal'
            synced += 1

    save_registry(data)
    print(f'Synced {synced} agents from economy ledger')


# -- CLI ----------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description='Agent Registry')
    sub = p.add_subparsers(dest='command')

    r = sub.add_parser('register')
    r.add_argument('--org_id', required=True)
    r.add_argument('--name', required=True)
    r.add_argument('--role', required=True)
    r.add_argument('--purpose', required=True)
    r.add_argument('--scopes', default='')
    r.add_argument('--approval_required', action='store_true')
    r.add_argument('--runtime_binding', default=None)

    g = sub.add_parser('get')
    g.add_argument('--agent_id', required=True)
    g.add_argument('--org_id', default=None)

    ls = sub.add_parser('list')
    ls.add_argument('--org_id', default=None)
    ls.add_argument('--include_disabled', action='store_true')

    u = sub.add_parser('update')
    u.add_argument('--agent_id', required=True)
    u.add_argument('--rollout_state', default=None)
    u.add_argument('--purpose', default=None)
    u.add_argument('--runtime_binding', default=None)

    sb = sub.add_parser('set-budget')
    sb.add_argument('--agent_id', required=True)
    sb.add_argument('--max_per_run_usd', type=float, default=None)
    sb.add_argument('--max_per_day_usd', type=float, default=None)
    sb.add_argument('--max_per_month_usd', type=float, default=None)

    ss = sub.add_parser('set-scopes')
    ss.add_argument('--agent_id', required=True)
    ss.add_argument('--scopes', required=True, help='Comma-separated scopes')

    d = sub.add_parser('disable')
    d.add_argument('--agent_id', required=True)

    sync = sub.add_parser('sync-economy')
    sync.add_argument('--org_id', default=None)

    rs = sub.add_parser('set-risk')
    rs.add_argument('--agent_id', required=True)
    rs.add_argument('--state', required=True, choices=list(VALID_RISK_STATES))

    tl = sub.add_parser('lifecycle')
    tl.add_argument('--agent_id', required=True)
    tl.add_argument('--state', required=True, choices=list(VALID_LIFECYCLE_STATES))

    inc = sub.add_parser('record-incident')
    inc.add_argument('--agent_id', required=True)

    args = p.parse_args()

    if args.command == 'register':
        scopes = [s.strip() for s in args.scopes.split(',') if s.strip()] if args.scopes else []
        aid = register_agent(args.org_id, args.name, args.role, args.purpose,
                             scopes=scopes, approval_required=args.approval_required,
                             runtime_binding=args.runtime_binding)
        print(f'Registered agent: {aid}')
    elif args.command == 'get':
        agent = resolve_agent(args.agent_id, org_id=getattr(args, 'org_id', None))
        print(json.dumps(agent, indent=2) if agent else f'Not found: {args.agent_id}')
    elif args.command == 'list':
        for a in list_agents(args.org_id, getattr(args, 'include_disabled', False)):
            print(f"  {a['id']:<30} {a['name']:<12} role={a['role']:<10} "
                  f"state={a['rollout_state']:<12} REP={a['reputation_units']} AUTH={a['authority_units']}")
    elif args.command == 'update':
        update_agent(
            args.agent_id,
            rollout_state=args.rollout_state,
            purpose=args.purpose,
            runtime_binding=args.runtime_binding,
        )
        print(f'Updated {args.agent_id}')
    elif args.command == 'set-budget':
        set_budget(args.agent_id, args.max_per_run_usd, args.max_per_day_usd, args.max_per_month_usd)
        print(f'Budget updated for {args.agent_id}')
    elif args.command == 'set-scopes':
        scopes = [s.strip() for s in args.scopes.split(',')]
        set_scopes(args.agent_id, scopes)
        print(f'Scopes updated for {args.agent_id}')
    elif args.command == 'disable':
        update_agent(args.agent_id, rollout_state='disabled')
        print(f'Disabled {args.agent_id}')
    elif args.command == 'sync-economy':
        sync_from_economy(getattr(args, 'org_id', None))
    elif args.command == 'set-risk':
        set_risk_state(args.agent_id, args.state)
        print(f'Risk state set to {args.state} for {args.agent_id}')
    elif args.command == 'lifecycle':
        transition_lifecycle(args.agent_id, args.state)
        print(f'Lifecycle transitioned to {args.state} for {args.agent_id}')
    elif args.command == 'record-incident':
        count = record_incident(args.agent_id)
        print(f'Incident recorded for {args.agent_id} (total: {count})')
    else:
        p.print_help()


if __name__ == '__main__':
    main()
