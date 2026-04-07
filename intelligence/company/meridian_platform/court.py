#!/usr/bin/env python3
"""
Court primitive for Meridian Constitutional OS.

Institution scope:
  Founding-institution-only.  All functions accept org_id but
  _resolve_org_id() enforces that only the founding org (slug='meridian')
  is valid.  Court records resolve through capsule_path() to the founding
  org's capsule directory.

Composes over economy/sanctions.py — adds violation records, appeals,
and structured policy enforcement per CLAUDE.md sections 9-10.

Usage:
  python3 court.py file --agent <id> --org <org> --type <type> --severity <1-6> --evidence "..."
  python3 court.py violations [--agent <id>] [--status open]
  python3 court.py resolve --violation_id <id> --note "..."
  python3 court.py appeal --violation_id <id> --agent <id> --grounds "..."
  python3 court.py decide-appeal --appeal_id <id> --decision upheld|overturned|dismissed --by <who>
  python3 court.py record --agent <id>
  python3 court.py auto-review
  python3 court.py show
"""
import argparse
import datetime
import json
import os
import sys
import uuid

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(PLATFORM_DIR))
ECONOMY_DIR = os.path.join(WORKSPACE, 'economy')
RECORDS_FILE = os.path.join(PLATFORM_DIR, 'court_records.json')

if PLATFORM_DIR not in sys.path:
    sys.path.insert(0, PLATFORM_DIR)

from capsule import (
    capsule_path,
    ensure_capsule,
    ensure_treasury_aliases,
    ledger_path as capsule_ledger_path,
)

# Import economy sanctions module (avoid name collision)
import importlib.util
_spec = importlib.util.spec_from_file_location('econ_sanctions', os.path.join(ECONOMY_DIR, 'sanctions.py'))
_econ_sanctions_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_econ_sanctions_mod)
_econ_apply_sanction = _econ_sanctions_mod.apply_sanction
_econ_lift_sanction = _econ_sanctions_mod.lift_sanction
_econ_check_auto_sanctions = _econ_sanctions_mod.check_auto_sanctions
_econ_get_restrictions = _econ_sanctions_mod.get_restrictions

# Violation types per CLAUDE.md section 9
VIOLATION_TYPES = (
    'weak_output',        # 9.1 light failure
    'rejected_output',    # 9.2 rejected output
    'rework',             # 9.3 rework creation
    'token_waste',        # 9.4 token/meta-work waste
    'false_confidence',   # 9.5 false confidence / unverifiable claim
    'critical_failure',   # 9.6 critical failure / repeat violation
)

# Severity-to-sanction mapping (CLAUDE.md section 9)
SEVERITY_SANCTIONS = {
    1: None,                # light failure — no sanction, just no reward
    2: None,                # light failure
    3: 'probation',         # rejected output
    4: 'lead_ban',          # rework creation
    5: 'zero_authority',    # false confidence
    6: 'remediation_only',  # critical failure
}


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _default_org_id():
    try:
        from organizations import load_orgs
        for oid, org in load_orgs().get('organizations', {}).items():
            if org.get('slug') == 'meridian':
                return oid
    except Exception:
        pass
    return None


def _resolve_org_id(org_id=None):
    founding_org_id = _default_org_id()
    if org_id and founding_org_id and org_id != founding_org_id:
        raise ValueError(
            f'Live court only supports founding org {founding_org_id}, got {org_id}'
        )
    return org_id or founding_org_id


def _matches_org(entry_org_id, org_id):
    return not org_id or entry_org_id in (None, '', org_id)


def _records_path(org_id=None):
    return capsule_path(org_id, 'court_records.json')


def _records_have_state(data):
    return bool(data.get('violations')) or bool(data.get('appeals'))


def _migrate_legacy_records_if_needed(org_id=None):
    path = _records_path(org_id)
    legacy_data = None
    if os.path.exists(RECORDS_FILE):
        with open(RECORDS_FILE) as f:
            legacy_data = json.load(f)
    if os.path.exists(path):
        if legacy_data and _records_have_state(legacy_data):
            with open(path) as f:
                current = json.load(f)
            if not _records_have_state(current):
                with open(path, 'w') as f:
                    json.dump(legacy_data, f, indent=2)
        return path
    if legacy_data is not None:
        ensure_capsule(org_id)
        with open(path, 'w') as f:
            json.dump(legacy_data, f, indent=2)
        return path
    return path


def _load_records(org_id=None):
    _resolve_org_id(org_id)
    path = _migrate_legacy_records_if_needed(org_id)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {'violations': {}, 'appeals': {}, 'updatedAt': _now()}


def _save_records(data, org_id=None):
    data['updatedAt'] = _now()
    org_id = _resolve_org_id(org_id)
    path = _migrate_legacy_records_if_needed(org_id)
    if not os.path.exists(os.path.dirname(path)):
        ensure_capsule(org_id)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def _econ_load_ledger(org_id=None):
    _resolve_org_id(org_id)
    ensure_treasury_aliases(org_id)
    with open(capsule_ledger_path(org_id)) as f:
        return json.load(f)


def _econ_save_ledger(data, org_id=None):
    data['updatedAt'] = _now()
    _resolve_org_id(org_id)
    ensure_treasury_aliases(org_id)
    with open(capsule_ledger_path(org_id), 'w') as f:
        json.dump(data, f, indent=2)


# ── Core functions ───────────────────────────────────────────────────────────

def file_violation(agent_id, org_id, violation_type, severity, evidence, policy_ref=''):
    """Create a violation record. Auto-applies sanction if severity >= 3."""
    org_id = _resolve_org_id(org_id)
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
                level=severity
            )
            if result:
                _econ_save_ledger(ledger, org_id)
                sanction_applied = sanction_type
        except Exception as e:
            print(f'WARN: could not apply sanction: {e}')

    # Record incident in agent registry (try economy_key-based ID then registry ID)
    try:
        sys.path.insert(0, PLATFORM_DIR)
        from agent_registry import record_incident, get_agent_by_economy_key, load_registry
        # agent_id might be an economy key (e.g. 'pulse') — map to registry ID
        reg_agent = get_agent_by_economy_key(agent_id)
        if reg_agent:
            record_incident(reg_agent['id'])
        else:
            # Try direct registry ID
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
    org_id = _resolve_org_id(org_id)
    records = _load_records(org_id)
    violations = [v for v in records['violations'].values() if _matches_org(v.get('org_id'), org_id)]
    if agent_id:
        violations = [v for v in violations if v['agent_id'] == agent_id]
    if status:
        violations = [v for v in violations if v['status'] == status]
    return violations


def resolve_violation(violation_id, resolution_note, org_id=None):
    """Close a violation."""
    org_id = _resolve_org_id(org_id)
    records = _load_records(org_id)
    v = records['violations'].get(violation_id)
    if not v:
        raise ValueError(f'Violation not found: {violation_id}')
    if not _matches_org(v.get('org_id'), org_id):
        raise ValueError(f'Violation {violation_id} does not belong to {org_id}')
    v['status'] = 'resolved'
    v['resolved_at'] = _now()
    v['resolution_note'] = resolution_note
    _save_records(records, org_id)


def file_appeal(violation_id, agent_id, grounds, org_id=None):
    """Create an appeal for a violation."""
    org_id = _resolve_org_id(org_id)
    records = _load_records(org_id)
    v = records['violations'].get(violation_id)
    if not v:
        raise ValueError(f'Violation not found: {violation_id}')
    if not _matches_org(v.get('org_id'), org_id):
        raise ValueError(f'Violation {violation_id} does not belong to {org_id}')

    appeal_id = f'apl_{uuid.uuid4().hex[:8]}'
    records['appeals'][appeal_id] = {
        'id': appeal_id,
        'org_id': org_id,
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
    org_id = _resolve_org_id(org_id)
    records = _load_records(org_id)
    appeal = records['appeals'].get(appeal_id)
    if not appeal:
        raise ValueError(f'Appeal not found: {appeal_id}')
    if not _matches_org(appeal.get('org_id'), org_id):
        raise ValueError(f'Appeal {appeal_id} does not belong to {org_id}')
    if appeal['status'] != 'pending':
        raise ValueError(f'Appeal {appeal_id} is already {appeal["status"]}')

    appeal['status'] = decision
    appeal['decided_by'] = decided_by
    appeal['decided_at'] = _now()

    # If overturned, lift the sanction and resolve the violation
    violation = records['violations'].get(appeal['violation_id'])
    if violation and not _matches_org(violation.get('org_id'), org_id):
        raise ValueError(f'Violation {appeal["violation_id"]} does not belong to {org_id}')
    if decision == 'overturned' and violation:
        violation['status'] = 'dismissed'
        violation['resolved_at'] = _now()
        violation['resolution_note'] = f'Appeal {appeal_id} overturned by {decided_by}'
        if violation.get('sanction_applied'):
            try:
                ledger = _econ_load_ledger(org_id)
                _econ_lift_sanction(
                    ledger, violation['agent_id'], violation['sanction_applied'],
                    f'Appeal {appeal_id} overturned')
                _econ_save_ledger(ledger, org_id)
            except Exception as e:
                print(f'WARN: could not lift sanction: {e}')
    elif decision == 'upheld' and violation:
        violation['status'] = 'sanctioned'

    _save_records(records, org_id)


def get_agent_record(agent_id, org_id=None):
    """Get full court record for an agent: violations, sanctions, appeals."""
    org_id = _resolve_org_id(org_id)
    records = _load_records(org_id)
    violations = [
        v for v in records['violations'].values()
        if v['agent_id'] == agent_id and _matches_org(v.get('org_id'), org_id)
    ]
    appeals = [
        a for a in records['appeals'].values()
        if a['agent_id'] == agent_id and _matches_org(a.get('org_id'), org_id)
    ]

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
    requested_org_id = _resolve_org_id(org_id)
    if ledger_data is None:
        ledger_data = _econ_load_ledger(requested_org_id)

    changes = _econ_check_auto_sanctions(ledger_data, dry_run=True)
    violations_created = []

    for kind, agent_id, stype, note, level in changes:
        if kind == 'apply':
            # Create a violation record for the auto-sanction
            try:
                # Determine org_id from agent registry
                violation_org_id = requested_org_id or ''
                try:
                    sys.path.insert(0, PLATFORM_DIR)
                    from agent_registry import load_registry
                    reg = load_registry()
                    for a in reg['agents'].values():
                        ekey = a.get('economy_key', '')
                        if ekey == agent_id or a['name'].lower() == agent_id:
                            violation_org_id = a.get('org_id', violation_org_id)
                            break
                except Exception:
                    pass
                if requested_org_id and violation_org_id not in ('', requested_org_id):
                    continue

                severity = level if isinstance(level, int) else 3
                vid = file_violation(
                    agent_id=agent_id,
                    org_id=violation_org_id or requested_org_id,
                    violation_type='weak_output' if severity <= 2 else 'rejected_output',
                    severity=min(severity, 6),
                    evidence=note,
                    policy_ref='CLAUDE.md section 9 (auto-sanction)',
                )
                violations_created.append(vid)
            except Exception as e:
                print(f'WARN: auto_review could not file violation for {agent_id}: {e}')

    # Now actually apply the sanctions
    _econ_check_auto_sanctions(ledger_data, dry_run=False)

    return violations_created


def get_restrictions(agent_id, org_id=None):
    """Pass-through to economy sanctions."""
    resolved_org_id = _resolve_org_id(org_id)
    ledger = _econ_load_ledger(resolved_org_id)
    return _econ_get_restrictions(ledger, agent_id)


def remediate(agent_id, approved_by, note='', org_id=None):
    """Remediation path: lift lingering sanctions after violation is resolved.

    Requires all violations for the agent to be resolved/dismissed.
    Lifts economy sanctions, resets risk_state to nominal, resets incident_count.
    """
    org_id = _resolve_org_id(org_id)
    records = _load_records(org_id)

    # Check that no open/sanctioned violations remain
    open_violations = [
        v for v in records['violations'].values()
        if (
            v['agent_id'] == agent_id
            and v['status'] in ('open', 'sanctioned', 'appealed')
            and _matches_org(v.get('org_id'), org_id)
        )
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
                                f'Remediation approved by {approved_by}: {note}')
            lifted.append(stype)
    if lifted:
        _econ_save_ledger(ledger, org_id)

    # Reset risk_state and incident_count in agent registry
    try:
        sys.path.insert(0, PLATFORM_DIR)
        from agent_registry import load_registry, save_registry, get_agent_by_economy_key
        reg = load_registry()
        reg_agent = get_agent_by_economy_key(agent_id)
        if reg_agent and reg_agent['id'] in reg['agents']:
            reg['agents'][reg_agent['id']]['risk_state'] = 'nominal'
            reg['agents'][reg_agent['id']]['incident_count'] = 0
            save_registry(reg)
    except Exception:
        pass

    # Audit
    try:
        from audit import log_event
        log_event(org_id, agent_id, 'court_remediation',
                  outcome='success',
                  details={'lifted': lifted, 'approved_by': approved_by, 'note': note})
    except Exception:
        pass

    return lifted


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description='Court primitive — violations, sanctions, appeals')
    sub = p.add_subparsers(dest='command')

    fl = sub.add_parser('file')
    fl.add_argument('--agent', required=True)
    fl.add_argument('--org', required=True)
    fl.add_argument('--type', required=True, choices=list(VIOLATION_TYPES))
    fl.add_argument('--severity', type=int, required=True, choices=range(1, 7))
    fl.add_argument('--evidence', required=True)
    fl.add_argument('--policy_ref', default='')

    vl = sub.add_parser('violations')
    vl.add_argument('--agent', default=None)
    vl.add_argument('--status', default=None)
    vl.add_argument('--org', default=None)

    rs = sub.add_parser('resolve')
    rs.add_argument('--violation_id', required=True)
    rs.add_argument('--note', required=True)
    rs.add_argument('--org', default=None)

    ap = sub.add_parser('appeal')
    ap.add_argument('--violation_id', required=True)
    ap.add_argument('--agent', required=True)
    ap.add_argument('--grounds', required=True)
    ap.add_argument('--org', default=None)

    da = sub.add_parser('decide-appeal')
    da.add_argument('--appeal_id', required=True)
    da.add_argument('--decision', required=True, choices=['upheld', 'overturned', 'dismissed'])
    da.add_argument('--by', required=True)
    da.add_argument('--org', default=None)

    rec = sub.add_parser('record')
    rec.add_argument('--agent', required=True)
    rec.add_argument('--org', default=None)

    rem = sub.add_parser('remediate')
    rem.add_argument('--agent', required=True)
    rem.add_argument('--by', required=True, help='Who approved remediation')
    rem.add_argument('--note', default='', help='Remediation note')
    rem.add_argument('--org', default=None)

    arv = sub.add_parser('auto-review')
    arv.add_argument('--org', default=None)
    sh = sub.add_parser('show')
    sh.add_argument('--org', default=None)

    args = p.parse_args()

    if args.command == 'file':
        vid = file_violation(args.agent, args.org, args.type, args.severity,
                             args.evidence, args.policy_ref)
        print(f'Violation filed: {vid}')
    elif args.command == 'violations':
        violations = get_violations(args.agent, args.status, org_id=args.org)
        if not violations:
            print('No violations found.')
        else:
            for v in violations:
                print(f"  {v['id']}  agent={v['agent_id']}  type={v['type']}  "
                      f"sev={v['severity']}  status={v['status']}  sanction={v.get('sanction_applied', '-')}")
    elif args.command == 'resolve':
        resolve_violation(args.violation_id, args.note, org_id=args.org)
        print(f'Violation {args.violation_id} resolved')
    elif args.command == 'appeal':
        aid = file_appeal(args.violation_id, args.agent, args.grounds, org_id=args.org)
        print(f'Appeal filed: {aid}')
    elif args.command == 'decide-appeal':
        decide_appeal(args.appeal_id, args.decision, args.by, org_id=args.org)
        print(f'Appeal {args.appeal_id}: {args.decision}')
    elif args.command == 'record':
        rec = get_agent_record(args.agent, org_id=args.org)
        print(f"\n=== Court Record: {args.agent} ===")
        print(f"Total violations: {rec['total_violations']}")
        print(f"Open violations:  {rec['open_violations']}")
        print(f"Active restrictions: {', '.join(rec['active_restrictions']) or 'none'}")
        for v in rec['violations']:
            print(f"  {v['id']}  {v['type']}  sev={v['severity']}  status={v['status']}  {v['created_at']}")
    elif args.command == 'remediate':
        try:
            lifted = remediate(args.agent, args.by, args.note, org_id=args.org)
            if lifted:
                print(f'Remediation complete for {args.agent}: lifted {lifted}')
            else:
                print(f'Remediation complete for {args.agent}: no active sanctions to lift')
        except ValueError as e:
            print(f'Remediation denied: {e}')
            raise SystemExit(1)
    elif args.command == 'auto-review':
        vids = auto_review(org_id=args.org)
        if vids:
            print(f'Auto-review created {len(vids)} violation(s): {vids}')
        else:
            print('Auto-review: no new violations')
    elif args.command == 'show':
        resolved_org_id = _resolve_org_id(args.org)
        records = _load_records(args.org)
        violations = [v for v in records['violations'].values() if _matches_org(v.get('org_id'), resolved_org_id)]
        appeals = [a for a in records['appeals'].values() if _matches_org(a.get('org_id'), resolved_org_id)]
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
