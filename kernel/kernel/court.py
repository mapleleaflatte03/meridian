#!/usr/bin/env python3
"""
Court primitive for Meridian Kernel.

Composes over economy/sanctions.py -- adds violation records, appeals,
and structured policy enforcement.

Usage:
  python3 court.py file --agent <id> --org_id <org> --type <type> --severity <1-6> --evidence "..."
  python3 court.py violations [--agent <id>] [--status open] [--org_id <org>]
  python3 court.py resolve --violation_id <id> --note "..." [--org_id <org>]
  python3 court.py appeal --violation_id <id> --agent <id> --grounds "..." [--org_id <org>]
  python3 court.py decide-appeal --appeal_id <id> --decision upheld|overturned|dismissed --by <who> [--org_id <org>]
  python3 court.py record --agent <id> [--org_id <org>]
  python3 court.py remediate --agent <id> --by <who> [--org_id <org>]
  python3 court.py auto-review [--org_id <org>]
  python3 court.py show [--org_id <org>]
"""
import argparse
import datetime
import json
import os
import sys
import uuid

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(PLATFORM_DIR)
ECONOMY_DIR = os.path.join(WORKSPACE, 'economy')
LEGACY_RECORDS_FILE = os.path.join(PLATFORM_DIR, 'court_records.json')

if PLATFORM_DIR not in sys.path:
    sys.path.insert(0, PLATFORM_DIR)

from io_atomic import atomic_write_json

try:
    from capsule import capsule_path
except ImportError:
    def capsule_path(org_id, filename):
        return os.path.join(ECONOMY_DIR, filename)

# Import economy sanctions module (avoid name collision)
import importlib.util
_spec = importlib.util.spec_from_file_location('econ_sanctions', os.path.join(ECONOMY_DIR, 'sanctions.py'))
_econ_sanctions_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_econ_sanctions_mod)
_econ_apply_sanction = _econ_sanctions_mod.apply_sanction
_econ_lift_sanction = _econ_sanctions_mod.lift_sanction
_econ_check_auto_sanctions = _econ_sanctions_mod.check_auto_sanctions
_econ_get_restrictions = _econ_sanctions_mod.get_restrictions
_econ_load_ledger = _econ_sanctions_mod.load_ledger
_econ_save_ledger = _econ_sanctions_mod.save_ledger

# Violation types (sanctions ladder levels 1-6)
VIOLATION_TYPES = (
    'weak_output',        # light failure
    'rejected_output',    # rejected output
    'rework',             # rework creation
    'token_waste',        # token/meta-work waste
    'false_confidence',   # false confidence / unverifiable claim
    'critical_failure',   # critical failure / repeat violation
)

# Severity-to-sanction mapping
SEVERITY_SANCTIONS = {
    1: None,                # light failure -- no sanction, just no reward
    2: None,                # light failure
    3: 'probation',         # rejected output
    4: 'lead_ban',          # rework creation
    5: 'zero_authority',    # false confidence
    6: 'remediation_only',  # critical failure
}


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _empty_records():
    return {'violations': {}, 'appeals': {}, 'updatedAt': _now()}


def _missing_org_error(org_id):
    raise SystemExit(
        f"ERROR: institution '{org_id}' is not initialized. Run quickstart.py --init-only or bootstrap the capsule first."
    )


def _records_path(org_id=None):
    return capsule_path(org_id, 'court_records.json')


def _is_economy_capsule(path):
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(ECONOMY_DIR)]) == os.path.abspath(ECONOMY_DIR)
    except ValueError:
        return False


def _migrate_legacy_records_if_needed(org_id=None):
    path = _records_path(org_id)
    if os.path.exists(path):
        return path
    if _is_economy_capsule(path) and os.path.exists(LEGACY_RECORDS_FILE):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(LEGACY_RECORDS_FILE) as f:
            data = json.load(f)
        atomic_write_json(path, data)
        return path
    return path


def _load_records(org_id=None):
    path = _migrate_legacy_records_if_needed(org_id)
    if org_id and not os.path.isdir(os.path.dirname(path)):
        _missing_org_error(org_id)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return _empty_records()


def _save_records(data, org_id=None):
    data['updatedAt'] = _now()
    path = _migrate_legacy_records_if_needed(org_id)
    if org_id and not os.path.isdir(os.path.dirname(path)):
        _missing_org_error(org_id)
    atomic_write_json(path, data)


# -- Core functions -----------------------------------------------------------

def file_violation(agent_id, org_id, violation_type, severity, evidence, policy_ref=''):
    """Create a violation record. Auto-applies sanction if severity >= 3."""
    if violation_type not in VIOLATION_TYPES:
        raise ValueError(f'Invalid violation type: {violation_type}. Must be one of {VIOLATION_TYPES}')
    if severity < 1 or severity > 6:
        raise ValueError(f'Severity must be 1-6, got {severity}')

    records = _load_records(org_id)
    violation_id = f'vio_{uuid.uuid4().hex[:8]}'

    sanction_type = SEVERITY_SANCTIONS.get(severity)
    sanction_applied = None

    # Auto-apply sanction if severity >= 3
    if sanction_type:
        try:
            ledger = _econ_load_ledger(org_id)
            result = _econ_apply_sanction(
                ledger, agent_id, sanction_type,
                f'Court violation {violation_id}: {violation_type} (severity {severity})',
                level=severity,
                org_id=org_id,
            )
            if result:
                _econ_save_ledger(ledger, org_id)
                sanction_applied = sanction_type
        except Exception as e:
            print(f'WARN: could not apply sanction: {e}')

    # Record incident in agent registry
    try:
        from agent_registry import record_incident, get_agent_by_economy_key, load_registry
        reg_agent = get_agent_by_economy_key(agent_id, org_id=org_id)
        if reg_agent:
            record_incident(reg_agent['id'])
        else:
            reg = load_registry()
            if agent_id in reg['agents']:
                record_incident(agent_id)
    except Exception:
        pass

    records['violations'][violation_id] = {
        'id': violation_id,
        'agent_id': agent_id,
        'org_id': org_id,
        'type': violation_type,
        'severity': severity,
        'evidence': evidence,
        'policy_ref': policy_ref,
        'sanction_applied': sanction_applied,
        'status': 'sanctioned' if sanction_applied else 'open',
        'created_at': _now(),
        'resolved_at': None,
    }
    _save_records(records, org_id)

    # Audit log
    try:
        from audit import log_event
        log_event(org_id, agent_id, 'court_violation_filed',
                  resource=violation_id, outcome='success',
                  details={'type': violation_type, 'severity': severity,
                           'sanction_applied': sanction_applied},
                  policy_ref=policy_ref)
    except Exception:
        pass

    return violation_id


def get_violations(agent_id=None, status=None, org_id=None):
    """Query violations, optionally filtered by agent and/or status."""
    records = _load_records(org_id)
    violations = list(records['violations'].values())
    if agent_id:
        violations = [v for v in violations if v['agent_id'] == agent_id]
    if org_id:
        violations = [v for v in violations if v.get('org_id') == org_id]
    if status:
        violations = [v for v in violations if v['status'] == status]
    return violations


def resolve_violation(violation_id, resolution_note, org_id=None):
    """Close a violation."""
    records = _load_records(org_id)
    v = records['violations'].get(violation_id)
    if not v:
        raise ValueError(f'Violation not found: {violation_id}')
    v['status'] = 'resolved'
    v['resolved_at'] = _now()
    v['resolution_note'] = resolution_note
    _save_records(records, org_id)


def file_appeal(violation_id, agent_id, grounds, org_id=None):
    """Create an appeal for a violation."""
    records = _load_records(org_id)
    v = records['violations'].get(violation_id)
    if not v:
        raise ValueError(f'Violation not found: {violation_id}')

    appeal_id = f'apl_{uuid.uuid4().hex[:8]}'
    records['appeals'][appeal_id] = {
        'id': appeal_id,
        'violation_id': violation_id,
        'agent_id': agent_id,
        'grounds': grounds,
        'status': 'pending',
        'decided_by': None,
        'decided_at': None,
        'created_at': _now(),
    }
    v['status'] = 'appealed'
    _save_records(records, org_id)
    return appeal_id


def decide_appeal(appeal_id, decision, decided_by, org_id=None):
    """Decide an appeal. If overturned, lift the associated sanction."""
    if decision not in ('upheld', 'overturned', 'dismissed'):
        raise ValueError(f'Invalid decision: {decision}')
    records = _load_records(org_id)
    appeal = records['appeals'].get(appeal_id)
    if not appeal:
        raise ValueError(f'Appeal not found: {appeal_id}')
    if appeal['status'] != 'pending':
        raise ValueError(f'Appeal {appeal_id} is already {appeal["status"]}')

    appeal['status'] = decision
    appeal['decided_by'] = decided_by
    appeal['decided_at'] = _now()

    # If overturned, lift the sanction and resolve the violation
    violation = records['violations'].get(appeal['violation_id'])
    if decision == 'overturned' and violation:
        violation['status'] = 'dismissed'
        violation['resolved_at'] = _now()
        violation['resolution_note'] = f'Appeal {appeal_id} overturned by {decided_by}'
        if violation.get('sanction_applied'):
            try:
                ledger = _econ_load_ledger(org_id or violation.get('org_id'))
                _econ_lift_sanction(
                    ledger, violation['agent_id'], violation['sanction_applied'],
                    f'Appeal {appeal_id} overturned',
                    org_id=org_id or violation.get('org_id'))
                _econ_save_ledger(ledger, org_id or violation.get('org_id'))
            except Exception as e:
                print(f'WARN: could not lift sanction: {e}')
    elif decision == 'upheld' and violation:
        violation['status'] = 'sanctioned'

    _save_records(records, org_id)


def get_agent_record(agent_id, org_id=None):
    """Get full court record for an agent: violations, sanctions, appeals."""
    records = _load_records(org_id)
    violations = [v for v in records['violations'].values() if v['agent_id'] == agent_id]
    appeals = [a for a in records['appeals'].values() if a['agent_id'] == agent_id]

    # Current restrictions from economy
    try:
        ledger = _econ_load_ledger(org_id)
        restrictions = _econ_get_restrictions(ledger, agent_id)
    except Exception:
        restrictions = []

    return {
        'agent_id': agent_id,
        'violations': violations,
        'appeals': appeals,
        'active_restrictions': restrictions,
        'open_violations': len([v for v in violations if v['status'] in ('open', 'sanctioned')]),
        'total_violations': len(violations),
    }


def auto_review(ledger_data=None, org_id=None):
    """Wrap economy auto-sanctions and create violation records for any auto-applied sanctions."""
    if ledger_data is None:
        ledger_data = _econ_load_ledger(org_id)

    changes = _econ_check_auto_sanctions(ledger_data, dry_run=True, org_id=org_id)
    violations_created = []

    for kind, agent_id, stype, note, level in changes:
        if kind == 'apply':
            try:
                violation_org_id = org_id
                if violation_org_id is None:
                    try:
                        from agent_registry import get_agent_by_economy_key
                        reg_agent = get_agent_by_economy_key(agent_id)
                        if reg_agent:
                            violation_org_id = reg_agent.get('org_id')
                    except Exception:
                        pass

                severity = level if isinstance(level, int) else 3
                vid = file_violation(
                    agent_id=agent_id,
                    org_id=violation_org_id,
                    violation_type='weak_output' if severity <= 2 else 'rejected_output',
                    severity=min(severity, 6),
                    evidence=note,
                    policy_ref='sanctions ladder (auto-sanction)',
                )
                violations_created.append(vid)
            except Exception as e:
                print(f'WARN: auto_review could not file violation for {agent_id}: {e}')

    # Now actually apply the sanctions
    _econ_check_auto_sanctions(ledger_data, dry_run=False, org_id=org_id)

    return violations_created


def get_restrictions(agent_id, org_id=None):
    """Pass-through to economy sanctions."""
    ledger = _econ_load_ledger(org_id)
    return _econ_get_restrictions(ledger, agent_id)


def remediate(agent_id, approved_by, note='', org_id=None):
    """Remediation path: lift lingering sanctions after violation is resolved.

    Requires all violations for the agent to be resolved/dismissed.
    Lifts economy sanctions, resets risk_state to nominal, resets incident_count.
    """
    records = _load_records(org_id)

    # Check that no open/sanctioned violations remain
    open_violations = [
        v for v in records['violations'].values()
        if v['agent_id'] == agent_id and v['status'] in ('open', 'sanctioned', 'appealed')
    ]
    if open_violations:
        raise ValueError(
            f'Cannot remediate: {len(open_violations)} open violation(s) remain. '
            f'Resolve or dismiss them first: {[v["id"] for v in open_violations]}'
        )

    # Lift all economy sanctions for this agent
    ledger = _econ_load_ledger(org_id)
    lifted = []
    for stype in ('probation', 'zero_authority', 'lead_ban', 'remediation_only'):
        agent_data = ledger.get('agents', {}).get(agent_id, {})
        if agent_data.get(stype):
            _econ_lift_sanction(ledger, agent_id, stype,
                                f'Remediation approved by {approved_by}: {note}',
                                org_id=org_id)
            lifted.append(stype)
    if lifted:
        _econ_save_ledger(ledger, org_id)

    # Reset risk_state and incident_count in agent registry
    try:
        from agent_registry import load_registry, save_registry, get_agent_by_economy_key
        reg = load_registry()
        reg_agent = get_agent_by_economy_key(agent_id, org_id=org_id)
        if reg_agent and reg_agent['id'] in reg['agents']:
            reg['agents'][reg_agent['id']]['risk_state'] = 'nominal'
            reg['agents'][reg_agent['id']]['incident_count'] = 0
            save_registry(reg)
    except Exception:
        pass

    # Audit
    try:
        from audit import log_event
        log_event(org_id or '', agent_id, 'court_remediation',
                  outcome='success',
                  details={'lifted': lifted, 'approved_by': approved_by, 'note': note})
    except Exception:
        pass

    return lifted


# -- CLI ----------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description='Court primitive -- violations, sanctions, appeals')
    sub = p.add_subparsers(dest='command')

    def add_org_arg(parser, required=False):
        parser.add_argument('--org_id', default=None, required=required,
                            help='Institution context. Defaults to the legacy founding institution.')
        parser.add_argument('--org', dest='org_id', help=argparse.SUPPRESS)

    fl = sub.add_parser('file')
    add_org_arg(fl, required=True)
    fl.add_argument('--agent', required=True)
    fl.add_argument('--type', required=True, choices=list(VIOLATION_TYPES))
    fl.add_argument('--severity', type=int, required=True, choices=range(1, 7))
    fl.add_argument('--evidence', required=True)
    fl.add_argument('--policy_ref', default='')

    vl = sub.add_parser('violations')
    add_org_arg(vl)
    vl.add_argument('--agent', default=None)
    vl.add_argument('--status', default=None)

    rs = sub.add_parser('resolve')
    add_org_arg(rs)
    rs.add_argument('--violation_id', required=True)
    rs.add_argument('--note', required=True)

    ap = sub.add_parser('appeal')
    add_org_arg(ap)
    ap.add_argument('--violation_id', required=True)
    ap.add_argument('--agent', required=True)
    ap.add_argument('--grounds', required=True)

    da = sub.add_parser('decide-appeal')
    add_org_arg(da)
    da.add_argument('--appeal_id', required=True)
    da.add_argument('--decision', required=True, choices=['upheld', 'overturned', 'dismissed'])
    da.add_argument('--by', required=True)

    rec = sub.add_parser('record')
    add_org_arg(rec)
    rec.add_argument('--agent', required=True)

    rem = sub.add_parser('remediate')
    add_org_arg(rem)
    rem.add_argument('--agent', required=True)
    rem.add_argument('--by', required=True, help='Who approved remediation')
    rem.add_argument('--note', default='', help='Remediation note')

    arv = sub.add_parser('auto-review')
    add_org_arg(arv)
    shw = sub.add_parser('show')
    add_org_arg(shw)

    args = p.parse_args()

    if args.command == 'file':
        vid = file_violation(args.agent, args.org_id, args.type, args.severity,
                             args.evidence, args.policy_ref)
        print(f'Violation filed: {vid}')
    elif args.command == 'violations':
        violations = get_violations(args.agent, args.status, org_id=args.org_id)
        if not violations:
            print('No violations found.')
        else:
            for v in violations:
                print(f"  {v['id']}  agent={v['agent_id']}  type={v['type']}  "
                      f"sev={v['severity']}  status={v['status']}  sanction={v.get('sanction_applied', '-')}")
    elif args.command == 'resolve':
        resolve_violation(args.violation_id, args.note, org_id=args.org_id)
        print(f'Violation {args.violation_id} resolved')
    elif args.command == 'appeal':
        aid = file_appeal(args.violation_id, args.agent, args.grounds, org_id=args.org_id)
        print(f'Appeal filed: {aid}')
    elif args.command == 'decide-appeal':
        decide_appeal(args.appeal_id, args.decision, args.by, org_id=args.org_id)
        print(f'Appeal {args.appeal_id}: {args.decision}')
    elif args.command == 'record':
        rec = get_agent_record(args.agent, org_id=args.org_id)
        print(f"\n=== Court Record: {args.agent} ===")
        print(f"Total violations: {rec['total_violations']}")
        print(f"Open violations:  {rec['open_violations']}")
        print(f"Active restrictions: {', '.join(rec['active_restrictions']) or 'none'}")
        for v in rec['violations']:
            print(f"  {v['id']}  {v['type']}  sev={v['severity']}  status={v['status']}  {v['created_at']}")
    elif args.command == 'remediate':
        try:
            lifted = remediate(args.agent, args.by, args.note, org_id=args.org_id)
            if lifted:
                print(f'Remediation complete for {args.agent}: lifted {lifted}')
            else:
                print(f'Remediation complete for {args.agent}: no active sanctions to lift')
        except ValueError as e:
            print(f'Remediation denied: {e}')
            raise SystemExit(1)
    elif args.command == 'auto-review':
        vids = auto_review(org_id=args.org_id)
        if vids:
            print(f'Auto-review created {len(vids)} violation(s): {vids}')
        else:
            print('Auto-review: no new violations')
    elif args.command == 'show':
        records = _load_records(args.org_id)
        violations = list(records['violations'].values())
        appeals = list(records['appeals'].values())
        open_v = [v for v in violations if v['status'] in ('open', 'sanctioned', 'appealed')]
        pending_a = [a for a in appeals if a['status'] == 'pending']

        print(f"\n=== Court Records ===")
        print(f"Total violations: {len(violations)}")
        print(f"Open violations:  {len(open_v)}")
        print(f"Total appeals:    {len(appeals)}")
        print(f"Pending appeals:  {len(pending_a)}")

        if open_v:
            print(f"\nOpen violations:")
            for v in open_v:
                print(f"  {v['id']}  agent={v['agent_id']}  type={v['type']}  "
                      f"sev={v['severity']}  status={v['status']}")
        if pending_a:
            print(f"\nPending appeals:")
            for a in pending_a:
                print(f"  {a['id']}  violation={a['violation_id']}  agent={a['agent_id']}")
    else:
        p.print_help()


if __name__ == '__main__':
    main()
