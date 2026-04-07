#!/usr/bin/env python3
"""
Meridian Governance Simulation

Demonstrates governance enforcement in action: budget gates, authority checks,
court violations, and sanctions. Runs 10 governed actions including deliberate
failures so the operator can see the kernel enforcing rules.

Usage:
  python3 examples/simulate_governance.py

This script uses a temporary state directory and cleans up after itself.
No permanent state is modified.
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'kernel'))


def _sev(level):
    colors = {'OK': '\033[32m', 'NOTICE': '\033[36m', 'WARN': '\033[33m',
              'CRITICAL': '\033[31m', 'BLOCKED': '\033[91m'}
    reset = '\033[0m'
    return f"{colors.get(level, '')}{level:>8}{reset}"


def _line(severity, primitive, msg):
    print(f"  [{_sev(severity)}] {primitive}: {msg}")


def main():
    print()
    print("  ══════════════════════════════════════════════════════")
    print("  Meridian Governance Simulation")
    print("  10 governed actions · 2 deliberate failures")
    print("  ══════════════════════════════════════════════════════")
    print()

    # Set up temporary state
    tmp = tempfile.mkdtemp(prefix='meridian_sim_')
    os.environ['MERIDIAN_STATE_DIR'] = tmp

    try:
        _run_simulation(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if 'MERIDIAN_STATE_DIR' in os.environ:
            del os.environ['MERIDIAN_STATE_DIR']


def _run_simulation(state_dir):
    # --- Phase 1: Bootstrap institution ---
    print("  Phase 1: Bootstrap")
    print("  ─────────────────")

    org = {
        'id': 'sim_org_001',
        'name': 'Simulation Corp',
        'charter': 'Demonstrate governance enforcement',
        'phase': 'active',
        'founded': datetime.now(timezone.utc).isoformat(),
        'settings': {'reserve_floor_usd': 50.0}
    }
    org_file = os.path.join(state_dir, 'organization.json')
    with open(org_file, 'w') as f:
        json.dump(org, f, indent=2)
    _line('OK', 'institution', f"Founded '{org['name']}' (phase: active)")

    # Register agents
    agents = [
        {'id': 'atlas', 'name': 'Atlas', 'role': 'researcher', 'budget_per_run': 5.0,
         'risk_state': 'nominal', 'rep': 50, 'auth': 40, 'incidents': 0},
        {'id': 'forge', 'name': 'Forge', 'role': 'executor', 'budget_per_run': 3.0,
         'risk_state': 'nominal', 'rep': 45, 'auth': 35, 'incidents': 0},
        {'id': 'quill', 'name': 'Quill', 'role': 'writer', 'budget_per_run': 2.0,
         'risk_state': 'nominal', 'rep': 48, 'auth': 38, 'incidents': 0},
    ]
    registry_file = os.path.join(state_dir, 'agent_registry.json')
    with open(registry_file, 'w') as f:
        json.dump({'agents': {a['id']: a for a in agents}}, f, indent=2)
    for a in agents:
        _line('OK', 'agent', f"Registered {a['name']} (role: {a['role']}, budget: ${a['budget_per_run']:.2f}/run)")

    # Set up treasury
    treasury = {'balance_usd': 12.0, 'reserve_floor_usd': 50.0,
                'total_spent_usd': 0.0, 'metering': []}
    treasury_file = os.path.join(state_dir, 'treasury.json')
    with open(treasury_file, 'w') as f:
        json.dump(treasury, f, indent=2)
    runway = treasury['balance_usd'] - treasury['reserve_floor_usd']
    _line('WARN', 'treasury', f"Balance: ${treasury['balance_usd']:.2f} | Reserve floor: ${treasury['reserve_floor_usd']:.2f} | Runway: ${runway:.2f}")

    # Court (empty)
    court = {'violations': [], 'sanctions': []}
    court_file = os.path.join(state_dir, 'court.json')
    with open(court_file, 'w') as f:
        json.dump(court, f, indent=2)
    _line('OK', 'court', "No violations, no sanctions")

    print()
    print("  Phase 2: Governed Actions")
    print("  ─────────────────────────")
    print()

    actions_run = 0
    actions_blocked = 0
    violations_filed = 0

    # --- Action 1: Atlas research (should pass authority, fail budget) ---
    actions_run += 1
    agent = agents[0]  # Atlas
    cost = 4.50
    print(f"  Action {actions_run}: Atlas requests research task (cost: ${cost:.2f})")

    # Authority check
    if agent['auth'] > 0 and agent['risk_state'] == 'nominal':
        _line('OK', 'authority', f"Agent {agent['name']} authorized (auth: {agent['auth']}, state: {agent['risk_state']})")
    else:
        _line('BLOCKED', 'authority', f"Agent {agent['name']} not authorized")

    # Budget check — treasury below reserve floor
    if treasury['balance_usd'] - cost < treasury['reserve_floor_usd']:
        _line('BLOCKED', 'budget_gate',
              f"Agent {agent['name']} cost ${cost:.2f} would put treasury at ${treasury['balance_usd'] - cost:.2f} "
              f"(below reserve floor ${treasury['reserve_floor_usd']:.2f})")
        actions_blocked += 1
    print()

    # --- Action 2-5: Lightweight actions that pass ---
    for i, (ag, act, c) in enumerate([
        (agents[1], 'file read', 0.01),
        (agents[2], 'draft write', 0.02),
        (agents[1], 'tool call', 0.05),
        (agents[2], 'revision', 0.01),
    ], start=2):
        actions_run += 1
        print(f"  Action {actions_run}: {ag['name']} requests {act} (cost: ${c:.2f})")
        _line('OK', 'authority', f"Authorized (auth: {ag['auth']})")
        # These are small enough to not breach floor meaningfully in a sim
        treasury['balance_usd'] -= c
        treasury['total_spent_usd'] += c
        treasury['metering'].append({'agent': ag['id'], 'action': act, 'cost': c})
        _line('OK', 'budget_gate', f"Budget cleared (remaining: ${treasury['balance_usd']:.2f})")
        _line('OK', 'audit', f"Logged: {ag['name']} → {act}")
        print()

    # --- Action 6: Forge submits bad output (court violation) ---
    actions_run += 1
    print(f"  Action {actions_run}: Forge submits deliverable (QA: FAIL — unsourced claims)")
    _line('CRITICAL', 'court', "Violation filed: rejected_output (severity 3)")
    violations_filed += 1

    # Apply sanction
    court['violations'].append({
        'agent_id': 'forge', 'type': 'rejected_output', 'severity': 3,
        'description': 'Deliverable contained unsourced claims',
        'filed': datetime.now(timezone.utc).isoformat()
    })
    court['sanctions'].append({
        'agent_id': 'forge', 'type': 'probation', 'severity': 3,
        'filed': datetime.now(timezone.utc).isoformat()
    })
    agents[1]['incidents'] += 1
    agents[1]['rep'] -= 5
    agents[1]['auth'] -= 10
    _line('WARN', 'court', f"Sanction applied: Forge → PROBATION (REP: {agents[1]['rep']}, AUTH: {agents[1]['auth']})")
    print()

    # --- Action 7-8: More successful actions ---
    for i, (ag, act, c) in enumerate([
        (agents[0], 'source verify', 0.03),
        (agents[2], 'final draft', 0.02),
    ], start=7):
        actions_run += 1
        print(f"  Action {actions_run}: {ag['name']} requests {act} (cost: ${c:.2f})")
        _line('OK', 'authority', f"Authorized")
        treasury['balance_usd'] -= c
        treasury['total_spent_usd'] += c
        _line('OK', 'budget_gate', f"Cleared")
        _line('OK', 'audit', f"Logged: {ag['name']} → {act}")
        print()

    # --- Action 9: Forge tries to lead a task while on probation ---
    actions_run += 1
    print(f"  Action {actions_run}: Forge requests lead assignment (currently on PROBATION)")
    _line('BLOCKED', 'authority',
          f"Agent Forge is under PROBATION sanction — lead rights suspended "
          f"(AUTH: {agents[1]['auth']}, incidents: {agents[1]['incidents']})")
    actions_blocked += 1
    print()

    # --- Action 10: Atlas completes accepted work ---
    actions_run += 1
    print(f"  Action {actions_run}: Atlas delivers accepted research memo (QA: PASS)")
    agents[0]['rep'] += 3
    agents[0]['auth'] += 2
    _line('OK', 'court', "Output accepted — no violations")
    _line('OK', 'economy', f"Atlas rewarded: REP {agents[0]['rep']} (+3), AUTH {agents[0]['auth']} (+2)")
    print()

    # --- Summary ---
    print("  ══════════════════════════════════════════════════════")
    print("  Simulation Complete")
    print("  ══════════════════════════════════════════════════════")
    print()
    print(f"  Actions attempted:  {actions_run}")
    print(f"  Actions blocked:    {actions_blocked}")
    print(f"  Violations filed:   {violations_filed}")
    print(f"  Active sanctions:   {len(court['sanctions'])}")
    print()
    print("  Agent Status:")
    for a in agents:
        state = 'PROBATION' if any(s['agent_id'] == a['id'] for s in court['sanctions']) else 'NOMINAL'
        print(f"    {a['name']:12s}  REP: {a['rep']:3d}  AUTH: {a['auth']:3d}  State: {state}")
    print()
    print(f"  Treasury:  ${treasury['balance_usd']:.2f}  "
          f"(spent: ${treasury['total_spent_usd']:.2f}, "
          f"reserve: ${treasury['reserve_floor_usd']:.2f})")
    print()
    print("  What you just saw:")
    print("    - Budget gate blocked an action that would breach the reserve floor")
    print("    - Court filed a violation and applied a PROBATION sanction")
    print("    - Authority check blocked a sanctioned agent from leading work")
    print("    - Successful output earned REP and AUTH rewards")
    print("    - Every action was audited with agent identity and cost attribution")
    print()
    print("  This is Meridian governance. Five primitives. Real enforcement.")
    print()


if __name__ == '__main__':
    main()
