#!/usr/bin/env python3
"""Institution-owned accounting service layer for the live founding deployment.

This module mirrors the kernel accounting service semantics, but the live
deployment remains founding-locked. The service layer is still capsule-backed
and org-aware, so tests can prove isolation/backfill/journal behavior without
pretending the live host is multi-institution.
"""

from __future__ import annotations

import contextlib
import datetime
import fcntl
import json
import os
import sys
import tempfile


PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(PLATFORM_DIR))

if PLATFORM_DIR not in sys.path:
    sys.path.insert(0, PLATFORM_DIR)

from capsule import capsule_path

import accounting_store


BOUNDARY_NAME = 'accounting'
IDENTITY_MODEL = 'session'
MANAGEMENT_MODE = 'institution_owned_service'
MUTATION_PATHS = [
    '/api/accounting/expense',
    '/api/accounting/reimburse',
    '/api/accounting/draw',
]


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def _write_json_atomic(path, payload):
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=os.path.basename(path) + '.',
        suffix='.tmp',
        dir=directory,
    )
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _owner_ledger_path(org_id=None):
    return capsule_path(org_id, 'owner_ledger.json')


def _ledger_path(org_id=None):
    return capsule_path(org_id, 'ledger.json')


def _transactions_path(org_id=None):
    return capsule_path(org_id, 'transactions.jsonl')


def _lock_path(org_id=None):
    return capsule_path(org_id, '.accounting.lock')


@contextlib.contextmanager
def _accounting_lock(org_id=None):
    path = _lock_path(org_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a+') as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _append_transaction(org_id, entry):
    entry = dict(entry)
    entry['ts'] = _now()
    path = _transactions_path(org_id)
    return accounting_store.append_transaction(path, entry, org_id=org_id)


def _default_owner_ledger(org_id=None):
    return {
        'version': 1,
        'owner': 'Son Nguyen The',
        'created_at': _now(),
        'capital_contributed_usd': 0.0,
        'expenses_paid_usd': 0.0,
        'reimbursements_received_usd': 0.0,
        'draws_taken_usd': 0.0,
        'entries': [],
        '_meta': {
            'service_scope': 'institution_owned_service',
            'bound_org_id': org_id or '',
            'boundary_name': BOUNDARY_NAME,
            'identity_model': IDENTITY_MODEL,
            'storage_model': 'capsule_owned_owner_ledger',
        },
    }


def _normalize_owner_ledger(payload, org_id=None):
    if not isinstance(payload, dict):
        payload = {}
    normalized = dict(_default_owner_ledger(org_id))
    normalized.update(payload)
    normalized.setdefault('entries', [])
    if not isinstance(normalized['entries'], list):
        normalized['entries'] = list(normalized['entries'])
    normalized.setdefault('_meta', {})
    normalized['_meta']['service_scope'] = 'institution_owned_service'
    normalized['_meta']['bound_org_id'] = org_id or normalized['_meta'].get('bound_org_id', '')
    normalized['_meta']['boundary_name'] = BOUNDARY_NAME
    normalized['_meta']['identity_model'] = IDENTITY_MODEL
    normalized['_meta']['storage_model'] = 'capsule_owned_owner_ledger'
    return normalized


def _load_owner_ledger_state_unlocked(org_id=None):
    payload = accounting_store.load_owner_ledger_state(_owner_ledger_path(org_id), org_id)
    treasury = _load_json(_ledger_path(org_id), {'treasury': {}}).get('treasury', {})
    treasury_owner_capital = round(float(treasury.get('owner_capital_contributed_usd', 0.0) or 0.0), 4)
    owner_capital = round(float(payload.get('capital_contributed_usd', 0.0) or 0.0), 4)
    if treasury_owner_capital > owner_capital:
        payload['capital_contributed_usd'] = treasury_owner_capital
        payload['_meta']['capital_sync_source'] = 'treasury_ledger'
        payload['_meta']['capital_sync_backfilled'] = True
        backfill_exists = any(
            entry.get('type') == 'capital_contribution_backfill'
            and round(float(entry.get('metadata', {}).get('target_owner_capital_usd', -1.0) or -1.0), 4) == treasury_owner_capital
            for entry in payload['entries']
        )
        if not backfill_exists:
            payload['entries'].append({
                'type': 'capital_contribution_backfill',
                'amount_usd': round(treasury_owner_capital - owner_capital, 4),
                'note': 'Backfilled from treasury owner_capital_contributed_usd',
                'by': 'system:accounting_service',
                'at': _now(),
                'metadata': {
                    'derived_from_treasury_ledger': True,
                    'target_owner_capital_usd': treasury_owner_capital,
                },
            })
        accounting_store.save_owner_ledger_state(_owner_ledger_path(org_id), payload, org_id=org_id)
    else:
        payload['_meta'].setdefault('capital_sync_backfilled', False)
        payload['_meta'].setdefault('capital_sync_source', 'owner_ledger')
    return payload


def load_owner_ledger_state(org_id=None):
    with _accounting_lock(org_id):
        return _load_owner_ledger_state_unlocked(org_id)


def accounting_snapshot(org_id=None):
    payload = load_owner_ledger_state(org_id)
    expenses_paid = float(payload.get('expenses_paid_usd', 0.0) or 0.0)
    reimbursements = float(payload.get('reimbursements_received_usd', 0.0) or 0.0)
    draws_taken = float(payload.get('draws_taken_usd', 0.0) or 0.0)
    capital = float(payload.get('capital_contributed_usd', 0.0) or 0.0)

    return {
        'bound_org_id': payload.get('_meta', {}).get('bound_org_id', org_id or ''),
        'management_mode': MANAGEMENT_MODE,
        'mutation_enabled': True,
        'mutation_disabled_reason': '',
        'storage_model': 'capsule_owned_owner_ledger',
        'db': accounting_store.db_status_for_owner_ledger(_owner_ledger_path(org_id), org_id),
        'boundary_name': BOUNDARY_NAME,
        'identity_model': IDENTITY_MODEL,
        'canonical_path': os.path.relpath(_owner_ledger_path(org_id), WORKSPACE),
        'treasury_path': os.path.relpath(_ledger_path(org_id), WORKSPACE),
        'mutation_paths': list(MUTATION_PATHS),
        'summary': {
            'capital_contributed_usd': capital,
            'expenses_paid_usd': expenses_paid,
            'reimbursements_received_usd': reimbursements,
            'draws_taken_usd': draws_taken,
            'unreimbursed_expenses_usd': round(expenses_paid - reimbursements, 2),
            'entry_count': len(payload.get('entries', [])),
        },
        'meta': payload.get('_meta', {}),
        'owner': payload.get('owner', ''),
        'entries_tail': payload.get('entries', [])[-20:],
    }


def contribute_capital(amount_usd, note='', by='owner', org_id=None):
    amount = float(amount_usd)
    if amount <= 0:
        raise ValueError('Capital contribution must be greater than 0')

    with _accounting_lock(org_id):
        owner = _load_owner_ledger_state_unlocked(org_id)
        ledger = _load_json(_ledger_path(org_id), {'treasury': {}})
        treasury = ledger.setdefault('treasury', {})

        owner['capital_contributed_usd'] = round(float(owner.get('capital_contributed_usd', 0.0)) + amount, 4)
        owner['entries'].append({
            'type': 'capital_contribution',
            'amount_usd': amount,
            'note': note,
            'by': by,
            'at': _now(),
        })
        accounting_store.save_owner_ledger_state(_owner_ledger_path(org_id), owner, org_id=org_id)

        treasury['cash_usd'] = round(float(treasury.get('cash_usd', 0.0)) + amount, 4)
        treasury['owner_capital_contributed_usd'] = round(float(treasury.get('owner_capital_contributed_usd', 0.0)) + amount, 4)
        ledger['updatedAt'] = _now()
        _write_json_atomic(_ledger_path(org_id), ledger)

        _append_transaction(org_id, {
            'type': 'treasury_deposit',
            'deposit_type': 'owner_capital',
            'amount_usd': amount,
            'cash_after': treasury['cash_usd'],
            'note': note,
            'by': by,
        })
    return {
        'amount_usd': amount,
        'cash_after_usd': treasury['cash_usd'],
        'reserve_floor_usd': treasury.get('reserve_floor_usd', 50.0),
        'entry_count': len(owner['entries']),
    }


def record_owner_expense(amount_usd, note='', by='owner', org_id=None):
    amount = float(amount_usd)
    if amount <= 0:
        raise ValueError('Expense amount must be greater than 0')

    with _accounting_lock(org_id):
        owner = _load_owner_ledger_state_unlocked(org_id)
        owner['expenses_paid_usd'] = round(float(owner.get('expenses_paid_usd', 0.0)) + amount, 4)
        owner['entries'].append({
            'type': 'owner_expense',
            'amount_usd': amount,
            'note': note,
            'by': by,
            'at': _now(),
        })
        accounting_store.save_owner_ledger_state(_owner_ledger_path(org_id), owner, org_id=org_id)
        _append_transaction(org_id, {
            'type': 'owner_expense_recorded',
            'amount_usd': amount,
            'note': note,
            'by': by,
        })
    return {
        'amount_usd': amount,
        'unreimbursed_expenses_usd': round(
            float(owner.get('expenses_paid_usd', 0.0)) - float(owner.get('reimbursements_received_usd', 0.0)),
            2,
        ),
        'entry_count': len(owner['entries']),
    }


def reimburse_owner(amount_usd, note='', by='owner', org_id=None):
    amount = float(amount_usd)
    if amount <= 0:
        raise ValueError('Reimbursement amount must be greater than 0')

    with _accounting_lock(org_id):
        owner = _load_owner_ledger_state_unlocked(org_id)
        ledger = _load_json(_ledger_path(org_id), {'treasury': {}})
        treasury = ledger.setdefault('treasury', {})

        unreimbursed = float(owner.get('expenses_paid_usd', 0.0)) - float(owner.get('reimbursements_received_usd', 0.0))
        if amount > unreimbursed:
            raise ValueError(
                f'Reimbursement ${amount:.2f} exceeds unreimbursed expenses ${unreimbursed:.2f}'
            )
        reserve_floor = float(treasury.get('reserve_floor_usd', 50.0))
        if float(treasury.get('cash_usd', 0.0)) - amount < reserve_floor:
            raise PermissionError(
                f"Reimbursement ${amount:.2f} would breach reserve floor ${reserve_floor:.2f}"
            )

        treasury['cash_usd'] = round(float(treasury.get('cash_usd', 0.0)) - amount, 4)
        treasury['owner_draws_usd'] = round(float(treasury.get('owner_draws_usd', 0.0)) + amount, 4)
        owner['reimbursements_received_usd'] = round(float(owner.get('reimbursements_received_usd', 0.0)) + amount, 4)
        owner['entries'].append({
            'type': 'reimbursement',
            'amount_usd': amount,
            'note': note,
            'by': by,
            'at': _now(),
        })
        accounting_store.save_owner_ledger_state(_owner_ledger_path(org_id), owner, org_id=org_id)
        ledger['updatedAt'] = _now()
        _write_json_atomic(_ledger_path(org_id), ledger)
        _append_transaction(org_id, {
            'type': 'treasury_withdraw',
            'withdraw_type': 'owner_reimbursement',
            'amount_usd': amount,
            'cash_after': treasury['cash_usd'],
            'note': note,
            'by': by,
        })
    return {
        'amount_usd': amount,
        'cash_after_usd': treasury['cash_usd'],
        'unreimbursed_expenses_usd': round(
            float(owner.get('expenses_paid_usd', 0.0)) - float(owner.get('reimbursements_received_usd', 0.0)),
            2,
        ),
        'entry_count': len(owner['entries']),
    }


def take_owner_draw(amount_usd, note='', by='owner', org_id=None):
    amount = float(amount_usd)
    if amount <= 0:
        raise ValueError('Draw amount must be greater than 0')

    with _accounting_lock(org_id):
        owner = _load_owner_ledger_state_unlocked(org_id)
        ledger = _load_json(_ledger_path(org_id), {'treasury': {}})
        treasury = ledger.setdefault('treasury', {})

        reserve_floor = float(treasury.get('reserve_floor_usd', 50.0))
        available = max(0.0, float(treasury.get('cash_usd', 0.0)) - reserve_floor)
        if amount > available:
            raise ValueError(
                f'Draw ${amount:.2f} exceeds available above floor ${available:.2f}'
            )

        treasury['cash_usd'] = round(float(treasury.get('cash_usd', 0.0)) - amount, 4)
        treasury['owner_draws_usd'] = round(float(treasury.get('owner_draws_usd', 0.0)) + amount, 4)
        owner['draws_taken_usd'] = round(float(owner.get('draws_taken_usd', 0.0)) + amount, 4)
        owner['entries'].append({
            'type': 'owner_draw',
            'amount_usd': amount,
            'note': note,
            'by': by,
            'at': _now(),
        })
        accounting_store.save_owner_ledger_state(_owner_ledger_path(org_id), owner, org_id=org_id)
        ledger['updatedAt'] = _now()
        _write_json_atomic(_ledger_path(org_id), ledger)
        _append_transaction(org_id, {
            'type': 'treasury_withdraw',
            'withdraw_type': 'owner_draw',
            'amount_usd': amount,
            'cash_after': treasury['cash_usd'],
            'note': note,
            'by': by,
        })
    return {
        'amount_usd': amount,
        'cash_after_usd': treasury['cash_usd'],
        'available_for_draw_usd': round(max(0.0, float(treasury.get('cash_usd', 0.0)) - reserve_floor), 2),
        'entry_count': len(owner['entries']),
    }
