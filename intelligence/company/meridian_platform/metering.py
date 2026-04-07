#!/usr/bin/env python3
"""
Usage metering for Meridian.

Every billable action is metered: MCP tool calls, research runs, brief
deliveries, agent compute time. Meters are appended to a JSONL file and
can be aggregated per org, per agent, or per time period.

Usage:
  python3 metering.py record --org_id <org> --agent_id <agent> --metric mcp_tool_call --quantity 1 --cost_usd 0.50
  python3 metering.py usage --org_id <org> [--since <datetime>] [--agent_id <agent>]
  python3 metering.py budget-check --org_id <org> --cost_usd 2.00
  python3 metering.py summary --org_id <org> [--period day|week|month]
"""
import argparse
import datetime
import json
import os
import uuid

import observability_store

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
METERING_FILE = os.path.join(PLATFORM_DIR, 'metering.jsonl')
ORGS_FILE = os.path.join(PLATFORM_DIR, 'organizations.json')

# Max metering log size before rotation (10MB)
MAX_LOG_SIZE = 10 * 1024 * 1024


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _today():
    return datetime.date.today().isoformat()


def record(org_id, agent_id, metric, quantity=1.0, unit='calls',
           cost_usd=0.0, run_id='', details=None):
    """Record a usage meter event."""
    event = {
        'id': f'meter_{uuid.uuid4().hex[:10]}',
        'timestamp': _now(),
        'org_id': org_id,
        'agent_id': agent_id,
        'metric': metric,
        'quantity': quantity,
        'unit': unit,
        'cost_usd': cost_usd,
        'run_id': run_id,
        'details': details or {},
    }

    if os.path.exists(METERING_FILE) and os.path.getsize(METERING_FILE) > MAX_LOG_SIZE:
        archive = METERING_FILE + f'.{datetime.date.today().isoformat()}'
        os.rename(METERING_FILE, archive)

    with open(METERING_FILE, 'a') as f:
        f.write(json.dumps(event) + '\n')

    observability_store.write_metering_event(METERING_FILE, event)

    return event['id']


def get_usage(org_id, agent_id=None, since=None, metric=None):
    """Get usage events for an org, optionally filtered."""
    return observability_store.query_metering_events(
        METERING_FILE,
        org_id=org_id,
        agent_id=agent_id,
        since=since,
        metric=metric,
    )


def get_spend(org_id, since=None, agent_id=None):
    """Calculate total spend for an org in the given period."""
    events = get_usage(org_id, agent_id=agent_id, since=since)
    return sum(e.get('cost_usd', 0) for e in events)


def budget_check(org_id, cost_usd):
    """Check if an org can afford the given cost. Returns (allowed, reason, remaining)."""
    # Load org plan limits
    org_limits = _get_org_limits(org_id)
    if not org_limits:
        return True, 'No org limits configured', None

    monthly_limit = org_limits.get('monthly_budget_usd')
    if monthly_limit is None:
        return True, 'No monthly budget set', None

    # Calculate current month spend
    month_start = datetime.date.today().replace(day=1).isoformat() + 'T00:00:00Z'
    current_spend = get_spend(org_id, since=month_start)
    remaining = monthly_limit - current_spend

    if current_spend + cost_usd > monthly_limit:
        return False, f'Monthly budget exceeded (${current_spend:.2f} / ${monthly_limit:.2f})', remaining

    return True, 'ok', remaining


def summary(org_id, period='month'):
    """Return usage summary for an org."""
    now = datetime.datetime.utcnow()
    if period == 'day':
        since = now.replace(hour=0, minute=0, second=0).strftime('%Y-%m-%dT%H:%M:%SZ')
    elif period == 'week':
        since = (now - datetime.timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ')
    else:  # month
        since = now.replace(day=1, hour=0, minute=0, second=0).strftime('%Y-%m-%dT%H:%M:%SZ')

    events = get_usage(org_id, since=since)
    total_cost = sum(e.get('cost_usd', 0) for e in events)

    by_metric = {}
    by_agent = {}
    for e in events:
        m = e.get('metric', 'unknown')
        a = e.get('agent_id', 'unknown')
        by_metric[m] = by_metric.get(m, 0) + e.get('cost_usd', 0)
        by_agent[a] = by_agent.get(a, 0) + e.get('cost_usd', 0)

    return {
        'org_id': org_id,
        'period': period,
        'since': since,
        'total_events': len(events),
        'total_cost_usd': round(total_cost, 4),
        'by_metric': {k: round(v, 4) for k, v in sorted(by_metric.items(), key=lambda x: -x[1])},
        'by_agent': {k: round(v, 4) for k, v in sorted(by_agent.items(), key=lambda x: -x[1])},
    }


def _get_org_limits(org_id):
    """Load org budget limits from org data."""
    if not os.path.exists(ORGS_FILE):
        return None
    with open(ORGS_FILE) as f:
        orgs = json.load(f)
    org = orgs.get('organizations', {}).get(org_id)
    if not org:
        return None

    # Plan-based limits
    plan_limits = {
        'free': {'monthly_budget_usd': 10},
        'trial': {'monthly_budget_usd': 25},
        'starter': {'monthly_budget_usd': 100},
        'pro': {'monthly_budget_usd': 500},
        'enterprise': {'monthly_budget_usd': None},  # unlimited
    }
    return plan_limits.get(org.get('plan', 'free'), {'monthly_budget_usd': 10})


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description='Usage metering')
    sub = p.add_subparsers(dest='command')

    r = sub.add_parser('record')
    r.add_argument('--org_id', required=True)
    r.add_argument('--agent_id', default='')
    r.add_argument('--metric', required=True)
    r.add_argument('--quantity', type=float, default=1.0)
    r.add_argument('--unit', default='calls')
    r.add_argument('--cost_usd', type=float, default=0.0)
    r.add_argument('--run_id', default='')

    u = sub.add_parser('usage')
    u.add_argument('--org_id', required=True)
    u.add_argument('--agent_id', default=None)
    u.add_argument('--since', default=None)
    u.add_argument('--metric', default=None)

    b = sub.add_parser('budget-check')
    b.add_argument('--org_id', required=True)
    b.add_argument('--cost_usd', type=float, required=True)

    s = sub.add_parser('summary')
    s.add_argument('--org_id', required=True)
    s.add_argument('--period', default='month', choices=['day', 'week', 'month'])

    args = p.parse_args()

    if args.command == 'record':
        mid = record(args.org_id, args.agent_id, args.metric,
                     args.quantity, args.unit, args.cost_usd, args.run_id)
        print(f'Recorded: {mid}')
    elif args.command == 'usage':
        events = get_usage(args.org_id, args.agent_id, args.since, args.metric)
        total = sum(e.get('cost_usd', 0) for e in events)
        for e in events[-20:]:
            print(f"  {e['timestamp']}  {e['metric']:<20} qty={e['quantity']:<6} ${e['cost_usd']:.4f}  agent={e.get('agent_id','')}")
        print(f"\nTotal: {len(events)} events, ${total:.4f}")
    elif args.command == 'budget-check':
        allowed, reason, remaining = budget_check(args.org_id, args.cost_usd)
        print(json.dumps({'allowed': allowed, 'reason': reason, 'remaining_usd': remaining}))
    elif args.command == 'summary':
        print(json.dumps(summary(args.org_id, args.period), indent=2))
    else:
        p.print_help()


if __name__ == '__main__':
    main()
