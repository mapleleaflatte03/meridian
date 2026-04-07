#!/usr/bin/env python3
"""
Audit logging for Meridian.

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

import observability_store

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIT_FILE = os.path.join(PLATFORM_DIR, 'audit_log.jsonl')

# Max audit log size before rotation (10MB)
MAX_LOG_SIZE = 10 * 1024 * 1024


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def log_event(org_id, agent_id, action, resource='', outcome='success',
              actor_type='agent', details=None, policy_ref='',
              session_id=None):
    """Append an audit event to the log.

    When session_id is provided, it is recorded as a top-level field
    so that the audit trail traces which session authorized the action.
    """
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
    if os.path.exists(AUDIT_FILE) and os.path.getsize(AUDIT_FILE) > MAX_LOG_SIZE:
        archive = AUDIT_FILE + f'.{datetime.date.today().isoformat()}'
        os.rename(AUDIT_FILE, archive)

    with open(AUDIT_FILE, 'a') as f:
        f.write(json.dumps(event) + '\n')

    observability_store.write_audit_event(AUDIT_FILE, event)

    return event['id']


def query_events(org_id=None, agent_id=None, action=None, since=None,
                 outcome=None, limit=50):
    """Query audit events with filters."""
    return observability_store.query_audit_events(
        AUDIT_FILE,
        org_id=org_id,
        agent_id=agent_id,
        action=action,
        since=since,
        outcome=outcome,
        limit=limit,
    )


def tail_events(limit=20, org_id=None):
    """Return the most recent N events, optionally filtered by org_id."""
    events = observability_store.query_audit_events(AUDIT_FILE, org_id=org_id, limit=limit)
    events.reverse()
    return events[-limit:]


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


# ── CLI ──────────────────────────────────────────────────────────────────────

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

    s = sub.add_parser('stats')
    s.add_argument('--org_id', required=True)

    args = p.parse_args()

    if args.command == 'log':
        eid = log_event(args.org_id, args.agent_id, args.action,
                        args.resource, args.outcome, args.actor_type,
                        policy_ref=args.policy_ref)
        print(f'Logged: {eid}')
    elif args.command == 'query':
        events = query_events(args.org_id, args.agent_id, args.action,
                              args.since, args.outcome, args.limit)
        for e in events:
            print(f"  {e['timestamp']}  {e['action']:<25} {e['outcome']:<10} agent={e.get('agent_id',''):<15} {e.get('resource','')}")
    elif args.command == 'tail':
        for e in tail_events(args.limit, org_id=args.org_id):
            print(f"  {e['timestamp']}  {e['action']:<25} {e['outcome']:<10} org={e.get('org_id','')}")
    elif args.command == 'stats':
        print(json.dumps(stats(args.org_id), indent=2))
    else:
        p.print_help()


if __name__ == '__main__':
    main()
