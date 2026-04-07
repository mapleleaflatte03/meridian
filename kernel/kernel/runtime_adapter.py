#!/usr/bin/env python3
"""
Runtime Adapter primitive for Meridian Kernel.

Meridian is runtime-neutral. This module provides:
  - A machine-readable registry of governed runtimes (kernel/runtimes.json)
  - A registry-based constitutional contract assessment for each runtime
  - CLI for listing and inspecting runtimes

Meridian does not execute agents. It governs them. Any runtime that satisfies
the seven constitutional contract requirements can, in principle, have its
agents governed by Meridian's five primitives once a real adapter exists.

Constitutional contract requirements are defined in kernel/runtimes.json
and documented in docs/RUNTIME_CONTRACT.md.

Usage:
  python3 runtime_adapter.py list
  python3 runtime_adapter.py show --runtime_id mcp_generic
  python3 runtime_adapter.py check-contract --runtime_id loom_native
  python3 runtime_adapter.py check-proof --runtime_id legacy_v1_compatible
  python3 runtime_adapter.py register --id my_runtime --label "My Runtime" \
      --type hosted --protocols "MCP,A2A" --identity_mode api_key
"""
import argparse
import datetime
import importlib
import json
import os
import sys
try:
    from io_atomic import atomic_write_json
except ModuleNotFoundError:
    PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
    if PLATFORM_DIR not in sys.path:
        sys.path.insert(0, PLATFORM_DIR)
    from io_atomic import atomic_write_json

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
REGISTRY_FILE = os.path.join(PLATFORM_DIR, 'runtimes.json')


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


# -- Registry I/O -------------------------------------------------------------

def load_runtimes():
    """Load runtime registry from kernel/runtimes.json."""
    if not os.path.exists(REGISTRY_FILE):
        return {'runtimes': {}, 'contract_requirements': {}, 'updatedAt': _now()}
    with open(REGISTRY_FILE) as f:
        return json.load(f)


def save_runtimes(data):
    """Save runtime registry."""
    data['updatedAt'] = _now()
    atomic_write_json(REGISTRY_FILE, data)


def get_runtime(runtime_id):
    """Get a single runtime by ID. Returns None if not found."""
    return load_runtimes().get('runtimes', {}).get(runtime_id)


def _load_adapter_module(runtime):
    proof = runtime.get('adapter_proof', {})
    module_name = proof.get('module')
    if not module_name:
        return None
    return importlib.import_module(module_name)


def get_adapter_proof(runtime_id):
    runtime = get_runtime(runtime_id)
    if not runtime:
        return {'runtime_id': runtime_id, 'status': 'missing_runtime'}

    proof = runtime.get('adapter_proof', {})
    module_name = proof.get('module')
    if not module_name:
        return {
            'runtime_id': runtime_id,
            'status': 'no_adapter',
            'available': False,
            'implemented_hooks': [],
            'assessment_basis': 'registry_metadata',
        }

    try:
        module = _load_adapter_module(runtime)
    except Exception as e:
        return {
            'runtime_id': runtime_id,
            'status': 'import_error',
            'available': False,
            'implemented_hooks': [],
            'assessment_basis': 'registry_metadata',
            'error': str(e),
        }

    if hasattr(module, 'adapter_proof'):
        data = module.adapter_proof()
    else:
        data = {
            'type': proof.get('type', 'reference_library'),
            'runtime_id': runtime_id,
            'implemented_hooks': list(getattr(module, 'SUPPORTED_HOOKS', [])),
            'notes': proof.get('notes', ''),
        }
    return {
        'runtime_id': runtime_id,
        'status': 'available',
        'available': True,
        'assessment_basis': 'reference_adapter_library',
        'module': module_name,
        **data,
    }


# -- Contract checking --------------------------------------------------------

def check_contract(runtime_id):
    """
    Assess a runtime's declared Meridian constitutional contract compliance.

    This is a registry-backed assessment, not an active conformance probe.
    It reports what the runtime entry declares in kernel/runtimes.json.

    Returns a dict:
      {
        'runtime_id': str,
        'satisfied': [list of satisfied requirement IDs],
        'gaps': [list of unsatisfied requirement IDs],
        'unknown': [list of requirement IDs with null compliance],
        'score': int (0-7),
        'status': 'compliant' | 'partial' | 'non_compliant' | 'unknown',
        'verdict': str,
      }
    """
    data = load_runtimes()
    runtime = data.get('runtimes', {}).get(runtime_id)
    if not runtime:
        return {
            'runtime_id': runtime_id,
            'error': f'Runtime {runtime_id!r} not found in registry',
        }

    requirements = list(data.get('contract_requirements', {}).keys())
    thresholds = data.get('compliance_thresholds', {'compliant': 7, 'partial': 4})
    compliance = runtime.get('contract_compliance', {})

    native_satisfied = [r for r in requirements if compliance.get(r) is True]
    adapter_support = set()
    adapter_meta = get_adapter_proof(runtime_id)
    if adapter_meta.get('available'):
        adapter_support = set(adapter_meta.get('implemented_hooks', []))

    effective = {}
    for requirement in requirements:
        native = compliance.get(requirement)
        if native is True:
            effective[requirement] = True
        elif requirement in adapter_support:
            effective[requirement] = True
        else:
            effective[requirement] = native

    satisfied = [r for r in requirements if effective.get(r) is True]
    gaps = [r for r in requirements if effective.get(r) is False]
    unknown = [r for r in requirements if effective.get(r) is None]
    adapter_supplied = [r for r in requirements if r in adapter_support and compliance.get(r) is not True]

    score = len(satisfied)
    if score >= thresholds.get('compliant', 7) and adapter_supplied:
        status = 'reference_adapter'
    elif score >= thresholds.get('compliant', 7):
        status = 'compliant'
    elif score >= thresholds.get('partial', 4):
        status = 'partial'
    elif unknown and score == 0 and not gaps:
        status = 'unknown'
    else:
        status = 'non_compliant'

    if status == 'reference_adapter':
        verdict = (
            f"Runtime {runtime_id!r} now has a tested kernel-side reference adapter "
            f"covering {score}/{len(requirements)} constitutional requirements. "
            'A real deployment still has to route runtime events through that adapter.'
        )
    elif status == 'compliant':
        verdict = (
            f"Registry metadata says runtime {runtime_id!r} satisfies all "
            f"{score} constitutional contract requirements."
        )
    elif status == 'partial':
        verdict = (
            f"Registry metadata says runtime {runtime_id!r} satisfies "
            f"{score}/{len(requirements)} requirements. "
            f'Gaps: {", ".join(gaps + unknown)}. Active adapter verification is still required.'
        )
    elif status == 'unknown':
        verdict = (
            f"Runtime {runtime_id!r} has no declared compliance data. "
            'Runtime API review is required before an adapter can be built.'
        )
    else:
        unmet = gaps + unknown
        verdict = (
            f"Registry metadata says runtime {runtime_id!r} satisfies only "
            f"{score}/{len(requirements)} requirements. "
            f'Not governable without significant adapter work. '
            f'Unmet/unknown: {", ".join(unmet)}.'
        )

    return {
        'runtime_id': runtime_id,
        'label': runtime.get('label', runtime_id),
        'assessment_basis': (
            'declared_runtime_plus_reference_adapter'
            if adapter_supplied else
            'registry_metadata'
        ),
        'native_satisfied': native_satisfied,
        'adapter_supplied': adapter_supplied,
        'satisfied': satisfied,
        'gaps': gaps,
        'unknown': unknown,
        'score': score,
        'total': len(requirements),
        'status': status,
        'verdict': verdict,
        'adapter_proof': adapter_meta,
    }


def check_all_contracts():
    """Run contract check for every registered runtime."""
    data = load_runtimes()
    results = {}
    for rid in data.get('runtimes', {}):
        results[rid] = check_contract(rid)
    return results


# -- Runtime registration -----------------------------------------------------

def register_runtime(runtime_id, label, runtime_type, protocols, identity_mode,
                     execution_ownership='runtime', notes=''):
    """Register a new runtime in the registry."""
    data = load_runtimes()
    if runtime_id in data.get('runtimes', {}):
        raise ValueError(f'Runtime {runtime_id!r} already exists. Use update instead.')
    requirements = list(data.get('contract_requirements', {}).keys())
    entry = {
        'id': runtime_id,
        'label': label,
        'description': label,
        'type': runtime_type,
        'protocol_support': [p.strip() for p in protocols.split(',') if p.strip()],
        'identity_mode': identity_mode,
        'execution_ownership': execution_ownership,
        'capability_exposure': [],
        'contract_compliance': {r: None for r in requirements},
        'integration': {'treasury': 'none', 'audit': 'none', 'court': 'none'},
        'adapter_available': False,
        'status': 'planned',
        'transport_contract': {
            'supported_protocols': [p.strip().lower() for p in protocols.split(',') if p.strip()],
            'auth_shapes': [],
            'remote_audit_required': False,
            'external_cost_attribution_required': False,
            'admission_policy': 'planned',
        },
        'notes': notes,
        'registered_at': _now(),
    }
    if 'runtimes' not in data:
        data['runtimes'] = {}
    data['runtimes'][runtime_id] = entry
    save_runtimes(data)
    return entry


# -- Adapter integration helpers (callable by runtime implementations) --------

def get_contract_requirements():
    """Return the seven constitutional contract requirements as a dict."""
    return load_runtimes().get('contract_requirements', {})


def get_compliant_runtimes():
    """Return list of runtime IDs that are fully contract-compliant."""
    data = load_runtimes()
    thresholds = data.get('compliance_thresholds', {'compliant': 7})
    results = []
    for rid, rt in data.get('runtimes', {}).items():
        compliance = rt.get('contract_compliance', {})
        score = sum(1 for v in compliance.values() if v is True)
        if score >= thresholds.get('compliant', 7):
            results.append(rid)
    return results


# -- Admission helpers --------------------------------------------------------

def get_admission(runtime_id):
    from admission_policy import check_admission

    return check_admission(runtime_id)


def check_all_admissions():
    data = load_runtimes()
    return {rid: get_admission(rid) for rid in data.get('runtimes', {})}


# -- CLI ----------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description='Runtime Adapter primitive -- registry and contract checker')
    sub = p.add_subparsers(dest='command')

    sub.add_parser('list')

    sh = sub.add_parser('show')
    sh.add_argument('--runtime_id', required=True)

    cc = sub.add_parser('check-contract')
    cc.add_argument('--runtime_id', required=True)

    cp = sub.add_parser('check-proof')
    cp.add_argument('--runtime_id', required=True)

    sub.add_parser('check-all')

    ca = sub.add_parser('check-admission')
    ca.add_argument('--runtime_id', required=True)

    sub.add_parser('check-all-admission')

    reg = sub.add_parser('register')
    reg.add_argument('--id', required=True, dest='runtime_id')
    reg.add_argument('--label', required=True)
    reg.add_argument('--type', required=True, dest='runtime_type')
    reg.add_argument('--protocols', required=True,
                     help='Comma-separated: MCP,A2A,custom,etc.')
    reg.add_argument('--identity_mode', required=True)
    reg.add_argument('--execution_ownership', default='runtime')
    reg.add_argument('--notes', default='')

    args = p.parse_args()

    if args.command == 'list':
        data = load_runtimes()
        runtimes = data.get('runtimes', {})
        if not runtimes:
            print('No runtimes registered.')
            return
        print(f'\n=== Runtime Registry ({len(runtimes)} runtimes) ===')
        for rid, rt in runtimes.items():
            contract = check_contract(rid)
            admission = get_admission(rid)
            print(f"  {rid}: {rt.get('label')} | type={rt.get('type')} | "
                  f"contract={contract.get('score', 0)}/{contract.get('total', 0)} | "
                  f"admission={admission.get('policy', 'unknown')}:{'yes' if admission.get('admitted') else 'no'} | "
                  f"status={rt.get('status')} | adapter={'YES' if rt.get('adapter_available') else 'no'}")

    elif args.command == 'show':
        rt = get_runtime(args.runtime_id)
        if not rt:
            print(f'Runtime {args.runtime_id!r} not found.')
            sys.exit(1)
        payload = dict(rt)
        payload['admission'] = get_admission(args.runtime_id)
        print(json.dumps(payload, indent=2))

    elif args.command == 'check-contract':
        result = check_contract(args.runtime_id)
        if 'error' in result:
            print(f'ERROR: {result["error"]}')
            sys.exit(1)
        status = result['status'].upper()
        print(f'\n=== Contract Check: {args.runtime_id} ===')
        print(f'Status:    {status}')
        print(f'Score:     {result["score"]}/{result["total"]}')
        if result['native_satisfied']:
            print(f'Native:    {", ".join(result["native_satisfied"])}')
        if result['adapter_supplied']:
            print(f'Adapter:   {", ".join(result["adapter_supplied"])}')
        if result['satisfied']:
            print(f'Satisfied: {", ".join(result["satisfied"])}')
        if result['gaps']:
            print(f'Gaps:      {", ".join(result["gaps"])}')
        if result['unknown']:
            print(f'Unknown:   {", ".join(result["unknown"])}')
        print(f'Verdict:   {result["verdict"]}')
        sys.exit(0 if result['status'] in ('compliant', 'reference_adapter') else 1)

    elif args.command == 'check-proof':
        result = get_adapter_proof(args.runtime_id)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result.get('available') else 1)

    elif args.command == 'check-admission':
        result = get_admission(args.runtime_id)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result.get('admitted') else 1)

    elif args.command == 'check-all-admission':
        results = check_all_admissions()
        print(json.dumps(results, indent=2))
        has_failures = any(not result.get('admitted') and result.get('status') == 'active' for result in results.values())
        sys.exit(1 if has_failures else 0)

    elif args.command == 'check-all':
        results = check_all_contracts()
        print(f'\n=== Contract Check: All Runtimes (registry metadata) ===')
        for rid, result in results.items():
            if 'error' in result:
                print(f'  {rid}: ERROR -- {result["error"]}')
            else:
                print(f'  {rid}: {result["status"].upper()} ({result["score"]}/{result["total"]})')

    elif args.command == 'register':
        entry = register_runtime(
            args.runtime_id, args.label, args.runtime_type,
            args.protocols, args.identity_mode,
            args.execution_ownership, args.notes)
        print(f'Runtime registered: {entry["id"]} (status: {entry["status"]})')

    else:
        p.print_help()


if __name__ == '__main__':
    main()
