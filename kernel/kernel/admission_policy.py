#!/usr/bin/env python3
"""
Admission policy enforcement for Meridian Kernel.

Validates that runtime registrations meet the constitutional contract
requirements before they can be admitted to the governance plane.

Loom-first policy: the loom_native runtime is the primary admission
target. Other runtimes must declare transport_contract compliance
and meet minimum contract score thresholds.

Usage:
  python3 kernel/admission_policy.py check --runtime_id loom_native
  python3 kernel/admission_policy.py check --runtime_id mcp_generic
  python3 kernel/admission_policy.py list-policies
"""

import argparse
import json
import os
import sys

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
REGISTRY_FILE = os.path.join(PLATFORM_DIR, 'runtimes.json')


# ── Policy definitions ──────────────────────────────────────────────

ADMISSION_POLICIES = {
    "loom_first": {
        "label": "Loom-First Admission",
        "min_contract_score": 7,
        "require_transport_contract": True,
        "require_remote_audit": True,
        "require_external_cost_attribution": True,
        "allowed_protocols": [],  # empty = all
        "description": "Full constitutional compliance required. All transport policies enforced.",
    },
    "kernel_local": {
        "label": "Kernel Local Admission",
        "min_contract_score": 7,
        "require_transport_contract": False,
        "require_remote_audit": False,
        "require_external_cost_attribution": False,
        "allowed_protocols": ["custom"],
        "description": "Local kernel runtime. No transport policy enforcement needed.",
    },
    "adapter_bridge": {
        "label": "Adapter Bridge Admission",
        "min_contract_score": 7,
        "require_transport_contract": True,
        "require_remote_audit": True,
        "require_external_cost_attribution": True,
        "allowed_protocols": [],
        "description": "Partial compliance via adapter bridge. Transport policies enforced.",
    },
    "planned": {
        "label": "Planned Runtime (Not Admitted)",
        "min_contract_score": 0,
        "require_transport_contract": False,
        "require_remote_audit": False,
        "require_external_cost_attribution": False,
        "allowed_protocols": [],
        "description": "Runtime is planned but not yet admitted to the governance plane.",
        "force_not_admitted": True,
    },
}


# ── Registry helpers ────────────────────────────────────────────────

def load_runtimes():
    if not os.path.exists(REGISTRY_FILE):
        return {'runtimes': {}, 'contract_requirements': {}}
    with open(REGISTRY_FILE) as f:
        return json.load(f)


def get_runtime(runtime_id):
    return load_runtimes().get('runtimes', {}).get(runtime_id)


# ── Admission check ────────────────────────────────────────────────

def check_admission(runtime_id):
    """
    Check whether a runtime meets its declared admission policy.

    Returns:
        {
            'runtime_id': str,
            'admitted': bool,
            'policy': str,
            'contract_score': int,
            'violations': [str],
            'transport_compliant': bool,
        }
    """
    runtime = get_runtime(runtime_id)
    if not runtime:
        return {
            'runtime_id': runtime_id,
            'admitted': False,
            'policy': 'unknown',
            'contract_score': 0,
            'violations': [f'runtime {runtime_id!r} not found in registry'],
            'transport_compliant': False,
        }

    # Determine policy
    tc = runtime.get('transport_contract', {})
    policy_name = tc.get('admission_policy', 'planned')
    policy = ADMISSION_POLICIES.get(policy_name, ADMISSION_POLICIES['planned'])

    # Contract score uses the runtime adapter view so adapter-backed bridges are scored truthfully.
    from runtime_adapter import check_contract

    contract = check_contract(runtime_id)
    score = contract.get('score', 0)
    adapter_supplied = bool(contract.get('adapter_supplied'))

    violations = []

    # Planned runtimes never admit.
    if policy.get('force_not_admitted'):
        violations.append('runtime is marked planned and cannot be admitted yet')

    if runtime.get('status') != 'active' and not policy.get('force_not_admitted'):
        violations.append(f"runtime status {runtime.get('status', 'unknown')} is not active")

    # Check minimum score
    if score < policy['min_contract_score']:
        violations.append(
            f"contract score {score} below minimum {policy['min_contract_score']}"
        )

    if policy_name == 'adapter_bridge' and not adapter_supplied:
        violations.append('adapter bridge policy requires adapter-supplied constitutional hooks')

    # Transport contract checks
    if policy['require_transport_contract'] and not tc:
        violations.append("transport_contract section missing")

    if policy['require_remote_audit']:
        if tc and not tc.get('remote_audit_required', False):
            violations.append("remote_audit_required not set")

    if policy['require_external_cost_attribution']:
        if tc and not tc.get('external_cost_attribution_required', False):
            violations.append("external_cost_attribution_required not set")

    if policy['allowed_protocols']:
        supported = set(tc.get('supported_protocols', []))
        allowed = set(policy['allowed_protocols'])
        disallowed = supported - allowed
        if disallowed:
            violations.append(f"disallowed protocols: {', '.join(sorted(disallowed))}")

    transport_compliant = (
        not policy['require_transport_contract']
        or (bool(tc) and not any('transport' in v or 'protocol' in v or 'audit' in v or 'cost' in v for v in violations))
    )

    admitted = len(violations) == 0 and not policy.get('force_not_admitted', False)

    return {
        'runtime_id': runtime_id,
        'admitted': admitted,
        'policy': policy_name,
        'policy_label': policy['label'],
        'contract_score': score,
        'contract_status': contract.get('status', 'unknown'),
        'adapter_supplied': adapter_supplied,
        'violations': violations,
        'transport_compliant': transport_compliant,
        'status': runtime.get('status', 'unknown'),
    }


def check_all_runtimes():
    """Check admission for all registered runtimes."""
    data = load_runtimes()
    results = []
    for runtime_id in data.get('runtimes', {}):
        results.append(check_admission(runtime_id))
    return results


# ── CLI ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Meridian Kernel admission policy')
    sub = parser.add_subparsers(dest='command')

    check = sub.add_parser('check', help='Check admission for a runtime')
    check.add_argument('--runtime_id', required=True)

    sub.add_parser('check-all', help='Check admission for all runtimes')
    sub.add_parser('list-policies', help='List available admission policies')

    args = parser.parse_args()

    if args.command == 'check':
        result = check_admission(args.runtime_id)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result['admitted'] else 1)

    elif args.command == 'check-all':
        results = check_all_runtimes()
        print(json.dumps(results, indent=2))
        has_failures = any(not r['admitted'] and r['status'] == 'active' for r in results)
        sys.exit(1 if has_failures else 0)

    elif args.command == 'list-policies':
        print(json.dumps(ADMISSION_POLICIES, indent=2))

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
