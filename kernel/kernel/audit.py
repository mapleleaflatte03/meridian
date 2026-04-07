#!/usr/bin/env python3
"""
Audit logging for Meridian Kernel.

Every significant action produces an audit event: agent runs, payments,
policy decisions, approval gates, kills, and configuration changes.

Events are appended to a JSONL file (one JSON object per line).

Usage:
  python3 audit.py log --org_id <org> --agent_id <agent> --action "mcp_tool_call" --resource "latest-brief" --outcome success
  python3 audit.py query --org_id <org> [--agent_id <agent>] [--action <action>] [--since <datetime>] [--limit 50]
  python3 audit.py tail [--limit 20]
  python3 audit.py stats --org_id <org>
"""
import argparse
import datetime
import json
import os
import uuid

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIT_FILE = os.environ.get(
    'MERIDIAN_AUDIT_FILE',
    os.path.join(PLATFORM_DIR, 'audit_log.jsonl'),
)
RUNTIME_AUDIT_FILE = os.environ.get(
    'MERIDIAN_RUNTIME_AUDIT_FILE',
    os.environ.get(
        'MERIDIAN_AUDIT_FILE',
        os.path.join(PLATFORM_DIR, 'runtime_audit', 'loom_runtime_events.jsonl'),
    ),
)

# Max audit log size before rotation (10MB)
MAX_LOG_SIZE = 10 * 1024 * 1024


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def log_event(org_id, agent_id, action, resource='', outcome='success',
              actor_type='agent', details=None, policy_ref='',
              session_id=None, audit_file=None):
    """Append an audit event to the log.

    When session_id is provided, it is recorded as a top-level field
    so that the audit trail traces which session authorized the action.
    """
    audit_file = audit_file or AUDIT_FILE
    event = {
        'id': f'evt_{uuid.uuid4().hex[:10]}',
        'timestamp': _now(),
        'org_id': org_id,
        'agent_id': agent_id,
        'actor_type': actor_type,
        'action': action,
        'resource': resource,
        'outcome': outcome,
        'details': details or {},
        'policy_ref': policy_ref,
    }
    if session_id:
        event['session_id'] = session_id

    # Rotate if file is too large
    if os.path.exists(audit_file) and os.path.getsize(audit_file) > MAX_LOG_SIZE:
        archive = audit_file + f'.{datetime.date.today().isoformat()}'
        os.rename(audit_file, archive)

    parent_dir = os.path.dirname(audit_file)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    with open(audit_file, 'a') as f:
        f.write(json.dumps(event) + '\n')

    return event['id']


def query_events(org_id=None, agent_id=None, action=None, since=None,
                 outcome=None, limit=50):
    """Query audit events with filters."""
    if not os.path.exists(AUDIT_FILE):
        return []

    results = []
    with open(AUDIT_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if org_id and event.get('org_id') != org_id:
                continue
            if agent_id and event.get('agent_id') != agent_id:
                continue
            if action and event.get('action') != action:
                continue
            if outcome and event.get('outcome') != outcome:
                continue
            if since and event.get('timestamp', '') < since:
                continue

            results.append(event)

    # Return most recent first, limited
    results.reverse()
    return results[:limit]


def tail_events(limit=20, org_id=None):
    """Return the most recent N events, optionally filtered by org_id."""
    if not os.path.exists(AUDIT_FILE):
        return []

    events = []
    with open(AUDIT_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if org_id and event.get('org_id') != org_id:
                continue
            events.append(event)

    return events[-limit:]


def tail_runtime_events(limit=20, org_id=None):
    """Return the most recent N runtime audit events from the canonical runtime log."""
    if not os.path.exists(RUNTIME_AUDIT_FILE):
        return []

    events = []
    with open(RUNTIME_AUDIT_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if org_id and event.get('org_id') != org_id:
                continue
            events.append(event)

    return events[-limit:]


def _runtime_event_counts(events):
    """Build lightweight proof-oriented counts for runtime inspection output."""
    actions = {}
    outcomes = {}
    agents = set()
    orgs = set()
    for e in events:
        action = e.get('action', '')
        outcome = e.get('outcome', '')
        if action:
            actions[action] = actions.get(action, 0) + 1
        if outcome:
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
        if e.get('agent_id'):
            agents.add(e['agent_id'])
        if e.get('org_id'):
            orgs.add(e['org_id'])
    return {
        'actions': actions,
        'outcomes': outcomes,
        'distinct_agents': len(agents),
        'distinct_orgs': len(orgs),
    }


def summarize_runtime_events(limit=20, org_id=None):
    """Return a truthful runtime-audit summary and the newest events."""
    events = tail_runtime_events(limit=10**9, org_id=org_id)
    if not events:
        return {
            'runtime_audit_file': RUNTIME_AUDIT_FILE,
            'org_id': org_id,
            'total_events': 0,
            'events': [],
            'counts': {'actions': {}, 'outcomes': {}, 'distinct_agents': 0, 'distinct_orgs': 0},
            'earliest': None,
            'latest': None,
            'showing_last': 0,
        }

    counts = _runtime_event_counts(events)
    recent = events[-limit:] if limit else []
    return {
        'runtime_audit_file': RUNTIME_AUDIT_FILE,
        'org_id': org_id,
        'total_events': len(events),
        'events': recent,
        'counts': counts,
        'earliest': events[0].get('timestamp'),
        'latest': events[-1].get('timestamp'),
        'showing_last': len(recent),
    }


def _format_runtime_event(event):
    return (
        f"  {event.get('timestamp', '')}  "
        f"{event.get('id', ''):<16} "
        f"{event.get('action', ''):<25} "
        f"{event.get('outcome', ''):<12} "
        f"org={event.get('org_id', '')} "
        f"agent={event.get('agent_id', '')} "
        f"resource={event.get('resource', '')}"
    )


def print_runtime_summary(limit=20, org_id=None):
    """Print a proof-first human summary of the runtime audit trail."""
    summary = summarize_runtime_events(limit=limit, org_id=org_id)
    print('Runtime audit inspection')
    print(f"  file: {summary['runtime_audit_file']}")
    print(f"  org_id: {summary['org_id'] or '*'}")
    print(f"  total_events: {summary['total_events']}")
    print(f"  showing_last: {summary['showing_last']}")
    print(f"  earliest: {summary['earliest'] or 'n/a'}")
    print(f"  latest: {summary['latest'] or 'n/a'}")
    print(f"  distinct_orgs: {summary['counts']['distinct_orgs']}")
    print(f"  distinct_agents: {summary['counts']['distinct_agents']}")
    print(f"  actions: {json.dumps(summary['counts']['actions'], sort_keys=True)}")
    print(f"  outcomes: {json.dumps(summary['counts']['outcomes'], sort_keys=True)}")
    if summary['events']:
        latest = summary['events'][-1]
        print('Latest proof')
        print(_format_runtime_event(latest))
        print('Recent events')
        for event in summary['events']:
            print(_format_runtime_event(event))
    else:
        print('Latest proof')
        print('  no runtime audit events found')
        print('Recent events')
        print('  no runtime audit events found')
    return summary


def stats(org_id):
    """Return summary stats for an organization's audit events."""
    events = query_events(org_id=org_id, limit=10000)
    if not events:
        return {'org_id': org_id, 'total_events': 0}

    actions = {}
    outcomes = {}
    agents = set()
    for e in events:
        actions[e['action']] = actions.get(e['action'], 0) + 1
        outcomes[e['outcome']] = outcomes.get(e['outcome'], 0) + 1
        if e.get('agent_id'):
            agents.add(e['agent_id'])

    return {
        'org_id': org_id,
        'total_events': len(events),
        'actions': actions,
        'outcomes': outcomes,
        'distinct_agents': len(agents),
        'earliest': events[-1]['timestamp'] if events else None,
        'latest': events[0]['timestamp'] if events else None,
    }


# -- CLI ----------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description='Audit log')
    sub = p.add_subparsers(dest='command')

    l = sub.add_parser('log')
    l.add_argument('--org_id', required=True)
    l.add_argument('--agent_id', default='')
    l.add_argument('--action', required=True)
    l.add_argument('--resource', default='')
    l.add_argument('--outcome', default='success')
    l.add_argument('--actor_type', default='agent')
    l.add_argument('--policy_ref', default='')
    l.add_argument('--session_id', default=None)

    runtime = sub.add_parser('log-runtime')
    runtime.add_argument('--org_id', required=True)
    runtime.add_argument('--agent_id', default='')
    runtime.add_argument('--action', required=True)
    runtime.add_argument('--resource', default='')
    runtime.add_argument('--outcome', required=True)
    runtime.add_argument('--input_hash', required=True)
    runtime.add_argument('--estimated_cost_usd', type=float, required=True)
    runtime.add_argument('--effective_source', required=True)
    runtime.add_argument('--effective_stage', required=True)
    runtime.add_argument('--reference_stage', required=True)
    runtime.add_argument('--runtime_outcome', required=True)
    runtime.add_argument('--worker_status', default='')
    runtime.add_argument('--worker_kind', default='')
    runtime.add_argument('--parity_status', default='')
    runtime.add_argument('--runtime_event_id', default='')
    runtime.add_argument('--event_schema_version', default='')
    runtime.add_argument('--job_id', default='')
    runtime.add_argument('--execution_id', default='')
    runtime.add_argument('--decision_id', default='')
    runtime.add_argument('--parity_id', default='')
    runtime.add_argument('--audit_id', default='')
    runtime.add_argument('--budget_reservation_id', default='')
    runtime.add_argument('--budget_reservation_status', default='')
    runtime.add_argument('--budget_reservation_reason', default='')
    runtime.add_argument('--session_id', default=None)

    q = sub.add_parser('query')
    q.add_argument('--org_id', default=None)
    q.add_argument('--agent_id', default=None)
    q.add_argument('--action', default=None)
    q.add_argument('--since', default=None)
    q.add_argument('--outcome', default=None)
    q.add_argument('--limit', type=int, default=50)

    t = sub.add_parser('tail')
    t.add_argument('--org_id', default=None)
    t.add_argument('--limit', type=int, default=20)

    rt = sub.add_parser('tail-runtime')
    rt.add_argument('--org_id', default=None)
    rt.add_argument('--limit', type=int, default=20)

    rs = sub.add_parser('summarize-runtime')
    rs.add_argument('--org_id', default=None)
    rs.add_argument('--limit', type=int, default=20)

    s = sub.add_parser('stats')
    s.add_argument('--org_id', required=True)

    args = p.parse_args()

    if args.command == 'log':
        eid = log_event(args.org_id, args.agent_id, args.action,
                        args.resource, args.outcome, args.actor_type,
                        policy_ref=args.policy_ref,
                        session_id=args.session_id)
        print(f'Logged: {eid}')
    elif args.command == 'log-runtime':
        runtime_details = {
            'source': 'loom_runtime_execute',
            'runtime_event_id': args.runtime_event_id,
            'input_hash': args.input_hash,
            'estimated_cost_usd': args.estimated_cost_usd,
            'effective_source': args.effective_source,
            'effective_stage': args.effective_stage,
            'reference_stage': args.reference_stage,
            'runtime_outcome': args.runtime_outcome,
            'worker_status': args.worker_status,
            'worker_kind': args.worker_kind,
            'parity_status': args.parity_status,
            'event_schema_version': args.event_schema_version,
            'job_id': args.job_id,
            'execution_id': args.execution_id,
            'decision_id': args.decision_id,
            'parity_id': args.parity_id,
            'audit_id': args.audit_id,
            'budget_reservation_id': args.budget_reservation_id,
            'budget_reservation_status': args.budget_reservation_status,
            'budget_reservation_reason': args.budget_reservation_reason,
            'experimental': True,
        }
        eid = log_event(
            args.org_id,
            args.agent_id,
            args.action,
            resource=args.resource,
            outcome=args.outcome,
            actor_type='agent',
            details=runtime_details,
            policy_ref='experimental_runtime_rehearsal',
            session_id=args.session_id,
            audit_file=RUNTIME_AUDIT_FILE,
        )
        payload = {
            'audit_event_id': eid,
            'runtime_event_id': args.runtime_event_id,
            'event_schema_version': args.event_schema_version,
            'job_id': args.job_id,
            'execution_id': args.execution_id,
            'decision_id': args.decision_id,
            'parity_id': args.parity_id,
            'audit_id': args.audit_id,
            'budget_reservation_id': args.budget_reservation_id,
            'budget_reservation_status': args.budget_reservation_status,
            'budget_reservation_reason': args.budget_reservation_reason,
            'runtime_audit_file': RUNTIME_AUDIT_FILE,
        }
        print(json.dumps(payload, sort_keys=True))
    elif args.command == 'query':
        events = query_events(args.org_id, args.agent_id, args.action,
                              args.since, args.outcome, args.limit)
        for e in events:
            print(f"  {e['timestamp']}  {e['action']:<25} {e['outcome']:<10} agent={e.get('agent_id',''):<15} {e.get('resource','')}")
    elif args.command == 'tail':
        for e in tail_events(args.limit, org_id=args.org_id):
            print(f"  {e['timestamp']}  {e['action']:<25} {e['outcome']:<10} org={e.get('org_id','')}")
    elif args.command == 'tail-runtime':
        for e in tail_runtime_events(args.limit, org_id=args.org_id):
            print(_format_runtime_event(e))
    elif args.command == 'summarize-runtime':
        print_runtime_summary(limit=args.limit, org_id=args.org_id)
    elif args.command == 'stats':
        print(json.dumps(stats(args.org_id), indent=2))
    else:
        p.print_help()


if __name__ == '__main__':
    main()
