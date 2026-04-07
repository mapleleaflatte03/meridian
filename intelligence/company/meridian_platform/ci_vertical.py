#!/usr/bin/env python3
"""
Competitive Intelligence Vertical — mapped onto Constitutional Primitives.

This module makes the CI pipeline a first-class constitutional workflow:
- Runs within one Institution (Meridian)
- Uses specific Agents (Atlas, Quill, Aegis, Sentinel, Forge, Pulse, Leviathann)
- Checks Authority before executing each phase
- Constrains against Treasury budget
- Records Court violations on failures

Usage:
  python3 ci_vertical.py status         # Show CI vertical state mapped to primitives
  python3 ci_vertical.py preflight      # Check all constitutional gates before pipeline run
  python3 ci_vertical.py post-mortem    # Analyze last pipeline run and file court records
"""
import argparse
import datetime
import glob
import os
import sys

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(PLATFORM_DIR))
NS_DIR = os.path.join(WORKSPACE, 'night-shift')
ECONOMY_DIR = os.path.join(WORKSPACE, 'economy')

sys.path.insert(0, PLATFORM_DIR)

from organizations import load_orgs
from agent_registry import load_registry
from authority import check_authority, is_kill_switch_engaged, get_sprint_lead
from treasury import get_balance, get_runway, check_budget
from court import file_violation, get_violations, get_restrictions, get_agent_record
from audit import log_event


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _get_org():
    orgs = load_orgs()
    for oid, org in orgs['organizations'].items():
        if org.get('slug') == 'meridian':
            return oid, org
    return None, None


# ── Pipeline phase → Agent mapping ───────────────────────────────────────────

PIPELINE_PHASES = [
    {'phase': 'research',    'agent': 'atlas',     'action': 'execute', 'description': 'Fetch 30+ sources, extract findings'},
    {'phase': 'write',       'agent': 'quill',     'action': 'execute', 'description': 'Write cited intelligence brief'},
    {'phase': 'qa_sentinel', 'agent': 'sentinel',  'action': 'review',  'description': 'Verify sources and check contradictions'},
    {'phase': 'qa_aegis',    'agent': 'aegis',     'action': 'review',  'description': 'Run acceptance gate and PASS/FAIL decision'},
    {'phase': 'execute',     'agent': 'forge',     'action': 'execute', 'description': 'Execute bounded improvement task'},
    {'phase': 'compress',    'agent': 'pulse',     'action': 'execute', 'description': 'Compress context for delivery'},
    {'phase': 'deliver',     'agent': 'main',      'action': 'execute', 'description': 'Deliver brief through the current honest customer path'},
    {'phase': 'score',       'agent': 'main',      'action': 'execute', 'description': 'Auto-score agents, advance epoch'},
]


def _get_registry_agent(reg, economy_key, org_id=None):
    for agent in reg['agents'].values():
        if org_id and agent.get('org_id') not in (None, '', org_id):
            continue
        if agent.get('economy_key') == economy_key:
            return agent
    return None


def _phase_gate_snapshot(reg=None, org_id=None):
    """Return phase-by-phase gate status, combining authority + treasury truth."""
    reg = reg or load_registry()
    org_id = org_id or _get_org()[0]
    lead_id, _ = get_sprint_lead(org_id)
    phases = []
    blocked_phases = []

    for phase in PIPELINE_PHASES:
        economy_key = phase['agent']
        agent = _get_registry_agent(reg, economy_key, org_id)

        auth_allowed, auth_reason = check_authority(economy_key, phase['action'], org_id=org_id)
        budget_allowed = True
        budget_reason = 'n/a'
        budget_required = 0.0
        if agent:
            budget_required = float(agent.get('budget', {}).get('max_per_run_usd', 0.0) or 0.0)
            if budget_required > 0:
                try:
                    budget_allowed, budget_reason = check_budget(agent['id'], budget_required, org_id=org_id)
                except TypeError:
                    # Compatibility for kernels that still expose check_budget(agent_id, amount)
                    budget_allowed, budget_reason = check_budget(agent['id'], budget_required)

        blockers = []
        if not auth_allowed:
            blockers.append(f'authority: {auth_reason}')
        if budget_required > 0 and not budget_allowed:
            blockers.append(f'budget: {budget_reason}')
        if agent and agent.get('risk_state') == 'suspended':
            blockers.append(f"risk: {agent['name']} is suspended")

        is_clear = not blockers
        if not is_clear:
            blocked_phases.append(phase['phase'])

        phases.append({
            'phase': phase['phase'],
            'agent_key': economy_key,
            'agent_name': agent['name'] if agent else economy_key,
            'agent_id': agent['id'] if agent else None,
            'action': phase['action'],
            'description': phase['description'],
            'authority_allowed': auth_allowed,
            'authority_reason': auth_reason,
            'budget_allowed': budget_allowed,
            'budget_reason': budget_reason,
            'budget_required_usd': budget_required,
            'risk_state': agent.get('risk_state', '?') if agent else '?',
            'restrictions': get_restrictions(economy_key, org_id=org_id),
            'is_lead': economy_key == lead_id,
            'blockers': blockers,
            'clear': is_clear,
        })

    return phases, blocked_phases


def get_agent_remediation(agent_key, reg=None, org_id=None):
    """Expose an operator-readable remediation path for non-nominal agents."""
    reg = reg or load_registry()
    org_id = org_id or _get_org()[0]
    agent = _get_registry_agent(reg, agent_key, org_id)
    if not agent:
        return None

    restrictions = get_restrictions(agent_key, org_id=org_id)
    if agent.get('risk_state') == 'nominal' and not restrictions:
        return None

    actions = {}
    for action in ('lead', 'assign', 'execute', 'review', 'remediate'):
        allowed, reason = check_authority(agent_key, action, org_id=org_id)
        actions[action] = {'allowed': allowed, 'reason': reason}

    record = get_agent_record(agent_key, org_id=org_id)
    next_steps = []
    if actions['remediate']['allowed']:
        next_steps.append('Run a remediation-only task and record the evidence in court/audit.')
    if agent.get('authority_units', 0) <= 15 and 'execute' in restrictions:
        next_steps.append('Recover AUTH above 15 or manually lift zero_authority before execute rights return.')
    if restrictions:
        next_steps.append(f"Current restrictions to clear: {', '.join(restrictions)}.")
    if not next_steps:
        next_steps.append('Review current court record and decide whether to resolve or escalate.')

    return {
        'agent_key': agent_key,
        'agent_id': agent['id'],
        'agent_name': agent['name'],
        'risk_state': agent.get('risk_state', 'nominal'),
        'authority_units': agent.get('authority_units', 0),
        'restrictions': restrictions,
        'open_violations': record['open_violations'],
        'total_violations': record['total_violations'],
        'actions': actions,
        'next_steps': next_steps,
    }


def status():
    """Show CI vertical mapped to five constitutional primitives."""
    org_id, org = _get_org()
    reg = load_registry()
    lead_id, lead_auth = get_sprint_lead(org_id)

    print(f"\n{'='*60}")
    print(f"COMPETITIVE INTELLIGENCE VERTICAL — Constitutional Map")
    print(f"{'='*60}")

    # Institution
    print(f"\n--- INSTITUTION ---")
    print(f"  Name:      {org['name']}")
    print(f"  Charter:   {org.get('charter', '(not set)')[:80] or '(not set)'}")
    print(f"  Lifecycle: {org.get('lifecycle_state', '?')}")
    print(f"  Policies:  auto_sanctions={org.get('policy_defaults',{}).get('auto_sanctions_enabled', '?')}")

    # Agents in this vertical
    print(f"\n--- AGENTS (CI Vertical) ---")
    print(f"  {'Phase':<14} {'Agent':<12} {'Role':<12} {'REP':>4} {'AUTH':>4} {'Risk':<10} {'Restrictions'}")
    print(f"  {'-'*80}")
    phases, blocked_phases = _phase_gate_snapshot(reg, org_id)
    for phase in phases:
        agent = _get_registry_agent(reg, phase['agent_key'], org_id)
        if agent:
            lead_marker = ' *LEAD*' if phase['agent_key'] == lead_id else ''
            print(f"  {phase['phase']:<14} {agent['name']:<12} {agent['role']:<12} "
                  f"{agent['reputation_units']:>4} {agent['authority_units']:>4} "
                  f"{agent.get('risk_state','?'):<10} {', '.join(phase['restrictions']) or '-'}{lead_marker}")

    # Authority gates
    print(f"\n--- AUTHORITY (Pipeline Gates) ---")
    ks = is_kill_switch_engaged(org_id)
    print(f"  Kill switch: {'ENGAGED (pipeline blocked)' if ks else 'off'}")
    print(f"  Sprint lead: {lead_id or 'NONE'} (AUTH={lead_auth})")
    for phase in phases:
        status_str = 'PASS' if phase['authority_allowed'] else f"BLOCKED: {phase['authority_reason']}"
        print(f"  {phase['phase']:<14} {phase['agent_key']:<10} {phase['action']:<8} -> {status_str}")

    # Treasury
    print(f"\n--- TREASURY (Budget Constraints) ---")
    balance = get_balance(org_id)
    runway = get_runway(org_id)
    print(f"  Balance: ${balance:.2f} | Runway: ${runway:.2f}")
    for phase in phases:
        if phase['budget_required_usd'] > 0:
            status_str = 'OK' if phase['budget_allowed'] else f"BLOCKED: {phase['budget_reason']}"
            print(f"  {phase['agent_name']:<12} budget=${phase['budget_required_usd']:.2f}/run -> {status_str}")

    # Court
    print(f"\n--- COURT (Active Enforcement) ---")
    open_v = get_violations(status='open', org_id=org_id) + get_violations(status='sanctioned', org_id=org_id)
    if open_v:
        for v in open_v:
            print(f"  {v['id']} agent={v['agent_id']} type={v['type']} sev={v['severity']} "
                  f"sanction={v.get('sanction_applied', '-')}")
    else:
        print(f"  No active violations affecting pipeline")

    if blocked_phases:
        print(f"\n--- REMEDIATION PATHS ---")
        for phase in phases:
            remediation = get_agent_remediation(phase['agent_key'], reg, org_id=org_id)
            if remediation and (phase['phase'] in blocked_phases or remediation['risk_state'] != 'nominal'):
                print(f"  {remediation['agent_name']} ({remediation['risk_state']})")
                for step in remediation['next_steps']:
                    print(f"    - {step}")

    # Latest artifacts
    print(f"\n--- LATEST ARTIFACTS ---")
    briefs = sorted(glob.glob(os.path.join(NS_DIR, 'brief-*.md')))
    reports = sorted(glob.glob(os.path.join(NS_DIR, 'reports', '*.md')))
    findings = sorted(glob.glob(os.path.join(NS_DIR, 'findings-*.md')))
    print(f"  Briefs:   {len(briefs)} (latest: {os.path.basename(briefs[-1]) if briefs else 'none'})")
    print(f"  Reports:  {len(reports)} (latest: {os.path.basename(reports[-1]) if reports else 'none'})")
    print(f"  Findings: {len(findings)} (latest: {os.path.basename(findings[-1]) if findings else 'none'})")


def preflight():
    """Check all constitutional gates before pipeline run. Returns 0 if clear, 1 if blocked."""
    org_id, org = _get_org()
    blocked = False
    blockers = []
    reg = load_registry()
    phases, blocked_phases = _phase_gate_snapshot(reg, org_id)

    print(f"CI Vertical Preflight — {_now()}")

    # 1. Institution lifecycle
    lifecycle = org.get('lifecycle_state', 'active')
    if lifecycle != 'active':
        print(f"  BLOCKED: Institution lifecycle is '{lifecycle}', not 'active'")
        blocked = True
        blockers.append(f"institution lifecycle={lifecycle}")
    else:
        print(f"  OK: Institution active")

    # 2. Kill switch
    if is_kill_switch_engaged(org_id):
        print(f"  BLOCKED: Kill switch engaged")
        blocked = True
        blockers.append('kill switch engaged')
    else:
        print(f"  OK: Kill switch off")

    # 3. Combined phase gates
    for phase in phases:
        if phase['clear']:
            print(f"  OK: {phase['phase']} ({phase['agent_key']} cleared)")
        else:
            print(f"  BLOCKED: {phase['phase']} — {'; '.join(phase['blockers'])}")
            blocked = True
            blockers.append(f"{phase['phase']}: {'; '.join(phase['blockers'])}")

    # 4. Treasury summary
    runway = get_runway(org_id)
    if runway < -100:
        print(f"  WARN: Treasury runway severely negative (${runway:.2f})")
    elif runway < 0:
        print(f"  WARN: Treasury below reserve by ${abs(runway):.2f}")

    # 5. Court / remediation state
    for phase in phases:
        remediation = get_agent_remediation(phase['agent_key'], reg, org_id=org_id)
        if remediation and remediation['risk_state'] in ('critical', 'suspended'):
            print(f"  NOTE: {remediation['agent_name']} remediation path active")
            for step in remediation['next_steps']:
                print(f"    - {step}")

    if blocked:
        print(f"\nPREFLIGHT: BLOCKED — pipeline should not run")
        log_event(org_id, 'system', 'ci_preflight', outcome='blocked',
                  details={'reason': 'constitutional gates failed',
                           'blocked_phases': blocked_phases,
                           'blockers': blockers})
        return 1
    else:
        print(f"\nPREFLIGHT: CLEAR — pipeline may proceed")
        log_event(org_id, 'system', 'ci_preflight', outcome='success',
                  details={'blocked_phases': [], 'blockers': []})
        return 0


def post_mortem():
    """Analyze last pipeline run and file court records for failures."""
    org_id, _ = _get_org()

    # Read latest report
    reports = sorted(glob.glob(os.path.join(NS_DIR, 'reports', '*.md')),
                     key=os.path.getmtime)
    if not reports:
        print("No reports found for post-mortem.")
        return

    with open(reports[-1]) as f:
        report = f.read()
    lo = report.lower()
    report_name = os.path.basename(reports[-1])

    print(f"Post-mortem for: {report_name}")
    violations_filed = 0

    # Check for Sentinel failure
    if 'sentinel' in lo and any(kw in lo for kw in ['sentinel: fail', 'sentinel fail', 'fail-to-parse']):
        vid = file_violation('sentinel', org_id, 'weak_output', 2,
                             f'Sentinel QA failed in {report_name}',
                             'CLAUDE.md section 9.1')
        print(f"  Filed: {vid} (Sentinel QA failure, severity 2)")
        violations_filed += 1

    # Check for delivery failure
    if any(kw in lo for kw in ['deliver_fail', 'delivery failed', 'delivery error']):
        vid = file_violation('main', org_id, 'weak_output', 2,
                             f'Delivery failed in {report_name}',
                             'CLAUDE.md section 9.1')
        print(f"  Filed: {vid} (delivery failure, severity 2)")
        violations_filed += 1

    # Check for Aegis rejection
    if 'aegis' in lo and any(kw in lo for kw in ['aegis: reject', 'aegis reject']):
        vid = file_violation('quill', org_id, 'rejected_output', 3,
                             f'Brief rejected by Aegis in {report_name}',
                             'CLAUDE.md section 9.2')
        print(f"  Filed: {vid} (Quill output rejected, severity 3)")
        violations_filed += 1

    if violations_filed == 0:
        print("  No court-worthy failures detected.")

    log_event(org_id, 'system', 'ci_post_mortem', outcome='success',
              details={'report': report_name, 'violations_filed': violations_filed})


def main():
    p = argparse.ArgumentParser(description='CI Vertical — constitutional primitive mapping')
    sub = p.add_subparsers(dest='command')
    sub.add_parser('status')
    sub.add_parser('preflight')
    sub.add_parser('post-mortem')
    args = p.parse_args()

    if args.command == 'status':
        status()
    elif args.command == 'preflight':
        rc = preflight()
        sys.exit(rc)
    elif args.command == 'post-mortem':
        post_mortem()
    else:
        p.print_help()


if __name__ == '__main__':
    main()
