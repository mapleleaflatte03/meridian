#!/usr/bin/env python3
"""
Treasury primitive for Meridian Kernel.

Governance facade over the institution's capsule ledger, revenue state, and
metering data.  Reads resolve through capsule_path(org_id, ...) which
defaults to economy/ for the founding institution.  Write operations
(contribute, set-reserve-floor) delegate to the accounting layer when
available and fall back to direct capsule-path writes otherwise.

Usage:
  python3 treasury.py balance
  python3 treasury.py runway
  python3 treasury.py spend [--org_id <org>] [--days 30]
  python3 treasury.py snapshot
  python3 treasury.py check-budget --agent_id <id> --cost 2.00
  python3 treasury.py contribute --amount 50.00 --note "owner top-up"
  python3 treasury.py set-reserve-floor --amount 20.00 --note "policy change"
  python3 treasury.py wallets
  python3 treasury.py accounts
  python3 treasury.py maintainers
  python3 treasury.py contributors
  python3 treasury.py proposals
  python3 treasury.py funding-sources
  python3 treasury.py check-payout-wallet --wallet_id <id>
  python3 treasury.py sign-x402-transfer --proposal_id <id> --actor_id <id> --rpc_url <url> --token_contract_address <addr>
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
from decimal import Decimal
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(PLATFORM_DIR)
ECONOMY_DIR = os.path.join(WORKSPACE, 'economy')
LEGACY_TREASURY_DIR = os.path.join(WORKSPACE, 'treasury')

_BASE_MAINNET_CHAIN_ID = 8453
_BASE_SEPOLIA_CHAIN_ID = 84532
_ERC20_TRANSFER_SELECTOR = 'a9059cbb'
_ERC20_DECIMALS_SELECTOR = '313ce567'
_ERC20_BALANCE_OF_SELECTOR = '70a08231'

if PLATFORM_DIR not in sys.path:
    sys.path.insert(0, PLATFORM_DIR)

try:
    from capsule import capsule_path
except ImportError:
    def capsule_path(org_id, filename):
        return os.path.join(ECONOMY_DIR, filename)

# Import economy modules (avoid name collision)
import importlib.util
_spec = importlib.util.spec_from_file_location('econ_revenue', os.path.join(ECONOMY_DIR, 'revenue.py'))
_econ_revenue_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_econ_revenue_mod)
load_revenue = _econ_revenue_mod.load_revenue
load_ledger = _econ_revenue_mod.load_ledger
save_ledger = _econ_revenue_mod.save_ledger

# Optional accounting import -- accounting.py is a private company module.
# When not present, contribute/reserve-floor operations degrade gracefully.
_owner_contribute_capital = None
_update_reserve_floor = None
try:
    _accounting_path = os.path.join(WORKSPACE, 'accounting.py')
    if os.path.exists(_accounting_path):
        _accounting_spec = importlib.util.spec_from_file_location(
            'company_accounting', _accounting_path
        )
        _accounting_mod = importlib.util.module_from_spec(_accounting_spec)
        _accounting_spec.loader.exec_module(_accounting_mod)
        _owner_contribute_capital = _accounting_mod.contribute_capital
        _update_reserve_floor = _accounting_mod.update_reserve_floor
except Exception:
    pass

# Import platform metering
from metering import get_spend, summary as metering_summary
from agent_registry import check_budget as _agent_check_budget
import commitments
from payout_plan_preview_queue import (
    acknowledge_payout_plan_preview as _acknowledge_payout_plan_preview,
    inspect_payout_plan_preview_queue as _inspect_payout_plan_preview_queue,
    load_payout_plan_preview_queue,
    payout_plan_preview_queue_snapshot,
    payout_plan_preview_queue_summary,
    upsert_payout_plan_preview,
)
from payout_plan_approval_candidate_queue import (
    get_payout_plan_approval_candidate as _get_payout_plan_approval_candidate,
    inspect_payout_plan_approval_candidate_queue as _inspect_payout_plan_approval_candidate_queue,
    list_payout_plan_approval_candidates as _list_payout_plan_approval_candidates,
    load_payout_plan_approval_candidate_queue as _load_payout_plan_approval_candidate_queue,
    payout_plan_approval_candidate_queue_snapshot,
    payout_plan_approval_candidate_queue_summary,
    promote_payout_plan_preview_to_approval_candidate as _promote_payout_plan_preview_to_approval_candidate,
    upsert_payout_plan_approval_candidate,
)
from payout_execution_queue import (
    load_payout_execution_queue as _load_payout_execution_queue,
    payout_execution_queue_snapshot as _payout_execution_queue_snapshot,
    payout_execution_queue_summary as _payout_execution_queue_summary,
    upsert_payout_execution_record,
)

try:
    from phase_machine import current_phase as _current_phase
except Exception:
    _current_phase = None


_RUNTIME_BUDGET_RESERVATIONS_FILE = 'runtime_budget_reservations.json'


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _parse_ts(value):
    return datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')


def _budget_reservations_path(org_id=None):
    return capsule_path(org_id, _RUNTIME_BUDGET_RESERVATIONS_FILE)


def _empty_budget_reservation_store():
    return {
        'version': 1,
        'schema': 'meridian-runtime-budget-reservations-v1',
        'updatedAt': _now(),
        'reservations': {},
    }


def _normalize_budget_reservation_store(store):
    payload = dict(store or {})
    payload.setdefault('version', 1)
    payload.setdefault('schema', 'meridian-runtime-budget-reservations-v1')
    payload.setdefault('reservations', {})
    payload.setdefault('updatedAt', _now())
    return payload


def _load_budget_reservation_store(org_id=None):
    path = _budget_reservations_path(org_id)
    if org_id and not os.path.isdir(os.path.dirname(path)):
        _missing_org_error(org_id)
    if os.path.exists(path):
        with open(path) as f:
            return _normalize_budget_reservation_store(json.load(f))
    return _empty_budget_reservation_store()


def _save_budget_reservation_store(store, org_id=None):
    path = _budget_reservations_path(org_id)
    if org_id and not os.path.isdir(os.path.dirname(path)):
        _missing_org_error(org_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = _normalize_budget_reservation_store(store)
    payload['updatedAt'] = _now()
    fd, tmp_path = tempfile.mkstemp(
        prefix='.runtime-budget-reservations.',
        suffix='.tmp',
        dir=os.path.dirname(path),
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


def _ensure_runtime_budget_fields(ledger):
    treasury = ledger.setdefault('treasury', {})
    treasury.setdefault('runtime_budget_reserved_usd', 0.0)
    treasury.setdefault('runtime_budget_committed_usd', 0.0)
    treasury.setdefault('runtime_budget_released_usd', 0.0)
    treasury.setdefault('runtime_budget_expired_usd', 0.0)
    treasury.setdefault('runtime_budget_active_reservations', 0)
    return treasury


def _resolve_budget_agent(agent_id, org_id=None):
    agent = _registry_get_agent_by_economy_key(agent_id, org_id=org_id)
    if agent:
        return agent
    return _registry_resolve_agent(agent_id, org_id=org_id)


def _registry_get_agent_by_economy_key(agent_id, org_id=None):
    from agent_registry import get_agent_by_economy_key

    if org_id is None:
        return get_agent_by_economy_key(agent_id)
    try:
        return get_agent_by_economy_key(agent_id, org_id=org_id)
    except TypeError:
        # Compatibility path for legacy registries that do not accept org_id.
        return get_agent_by_economy_key(agent_id)


def _registry_resolve_agent(agent_ref, org_id=None):
    try:
        from agent_registry import resolve_agent as _resolve_agent
    except Exception:
        _resolve_agent = None

    if _resolve_agent is not None:
        if org_id is None:
            return _resolve_agent(agent_ref)
        try:
            return _resolve_agent(agent_ref, org_id=org_id)
        except TypeError:
            return _resolve_agent(agent_ref)

    try:
        from agent_registry import get_agent
    except Exception:
        get_agent = None

    if get_agent is not None:
        if org_id is None:
            agent = get_agent(agent_ref)
        else:
            try:
                agent = get_agent(agent_ref, org_id=org_id)
            except TypeError:
                agent = get_agent(agent_ref)
        if agent:
            return agent

    return _registry_get_agent_by_economy_key(agent_ref, org_id=org_id)


def _reservation_datetime(value):
    if not value:
        return None
    try:
        return _parse_ts(value)
    except Exception:
        return None


def _active_budget_reservations(store, *, org_id=None, agent_id=None, status='reserved'):
    rows = list((store or {}).get('reservations', {}).values())
    if status:
        rows = [row for row in rows if row.get('status') == status]
    if agent_id:
        rows = [row for row in rows if row.get('agent_id') == agent_id]
    if org_id is not None:
        rows = [row for row in rows if row.get('org_id') == org_id]
    rows.sort(key=lambda row: (row.get('created_at', ''), row.get('reservation_id', '')))
    return rows


def budget_reservation_summary(org_id=None, *, agent_id=None):
    """Summarize runtime budget reservations for the current institution."""
    store = expire_runtime_budget_reservations(org_id, _now())
    ledger = load_ledger(org_id)
    treasury = _ensure_runtime_budget_fields(ledger)
    rows = _active_budget_reservations(store, org_id=org_id, agent_id=agent_id, status=None)
    status_counts = {}
    active_reserved_usd = 0.0
    committed_usd = 0.0
    released_usd = 0.0
    expired_usd = 0.0
    denied_usd = 0.0
    for row in rows:
        status = row.get('status', 'unknown')
        status_counts[status] = status_counts.get(status, 0) + 1
        amount = float(row.get('estimated_cost_usd', 0.0) or 0.0)
        if status == 'reserved':
            active_reserved_usd += amount
        elif status == 'committed':
            committed_usd += float(row.get('actual_cost_usd', amount) or amount)
        elif status == 'released':
            released_usd += amount
        elif status == 'expired':
            expired_usd += amount
        elif status == 'denied':
            denied_usd += amount
    runway = get_runway(org_id)
    available = max(0.0, runway - active_reserved_usd)
    return {
        'org_id': org_id,
        'agent_id': agent_id,
        'reservation_count': len(rows),
        'status_counts': status_counts,
        'active_reservation_count': status_counts.get('reserved', 0),
        'committed_reservation_count': status_counts.get('committed', 0),
        'released_reservation_count': status_counts.get('released', 0),
        'expired_reservation_count': status_counts.get('expired', 0),
        'denied_reservation_count': status_counts.get('denied', 0),
        'active_reserved_usd': round(active_reserved_usd, 4),
        'committed_usd': round(committed_usd, 4),
        'released_usd': round(released_usd, 4),
        'expired_usd': round(expired_usd, 4),
        'denied_usd': round(denied_usd, 4),
        'runway_usd': round(runway, 4),
        'available_for_reservation_usd': round(available, 4),
        'ledger_runtime_budget_reserved_usd': round(float(treasury.get('runtime_budget_reserved_usd', 0.0) or 0.0), 4),
        'ledger_runtime_budget_committed_usd': round(float(treasury.get('runtime_budget_committed_usd', 0.0) or 0.0), 4),
        'ledger_runtime_budget_released_usd': round(float(treasury.get('runtime_budget_released_usd', 0.0) or 0.0), 4),
        'ledger_runtime_budget_expired_usd': round(float(treasury.get('runtime_budget_expired_usd', 0.0) or 0.0), 4),
        'ledger_runtime_budget_active_reservations': int(treasury.get('runtime_budget_active_reservations', 0) or 0),
        'updatedAt': store.get('updatedAt', _now()),
    }


def list_runtime_budget_reservations(org_id=None, *, agent_id=None, status=None):
    store = expire_runtime_budget_reservations(org_id, _now())
    return _active_budget_reservations(store, org_id=org_id, agent_id=agent_id, status=status)


def get_runtime_budget_reservation(reservation_id, org_id=None):
    if not reservation_id:
        return None
    store = expire_runtime_budget_reservations(org_id, _now())
    return store.get('reservations', {}).get(reservation_id)


def _append_runtime_budget_audit_event(org_id, agent_id, action, reservation, outcome='success', reason=''):
    try:
        from audit import log_event
        log_event(
            org_id,
            agent_id,
            action,
            resource=reservation.get('reservation_id', ''),
            outcome=outcome,
            details={
                'reservation_id': reservation.get('reservation_id', ''),
                'estimated_cost_usd': reservation.get('estimated_cost_usd', 0.0),
                'actual_cost_usd': reservation.get('actual_cost_usd', 0.0),
                'status': reservation.get('status', ''),
                'reason': reason,
                'action': reservation.get('action', ''),
                'resource': reservation.get('resource', ''),
                'context': reservation.get('context', {}),
            },
            policy_ref=reservation.get('policy_ref', ''),
        )
    except Exception:
        pass


def _update_runtime_budget_ledger(org_id, *, reserved_delta=0.0, committed_delta=0.0,
                                  released_delta=0.0, expired_delta=0.0,
                                  active_delta=0):
    ledger = load_ledger(org_id)
    treasury = _ensure_runtime_budget_fields(ledger)
    treasury['runtime_budget_reserved_usd'] = round(
        float(treasury.get('runtime_budget_reserved_usd', 0.0) or 0.0) + float(reserved_delta or 0.0),
        4,
    )
    treasury['runtime_budget_committed_usd'] = round(
        float(treasury.get('runtime_budget_committed_usd', 0.0) or 0.0) + float(committed_delta or 0.0),
        4,
    )
    treasury['runtime_budget_released_usd'] = round(
        float(treasury.get('runtime_budget_released_usd', 0.0) or 0.0) + float(released_delta or 0.0),
        4,
    )
    treasury['runtime_budget_expired_usd'] = round(
        float(treasury.get('runtime_budget_expired_usd', 0.0) or 0.0) + float(expired_delta or 0.0),
        4,
    )
    treasury['runtime_budget_active_reservations'] = max(
        0,
        int(treasury.get('runtime_budget_active_reservations', 0) or 0) + int(active_delta or 0),
    )
    save_ledger(ledger, org_id)


_PROTOCOL_DEFAULTS = {
    'wallets.json': {
        'wallets': {},
        'verification_levels': {
            '0': {'label': 'observed_only', 'description': 'Seen on-chain, no ownership proof', 'payout_eligible': False},
            '1': {'label': 'linked', 'description': 'Owner claims ownership, no crypto proof', 'payout_eligible': False},
            '2': {'label': 'exchange_linked', 'description': 'Exchange deposit screen, NOT self-custody', 'payout_eligible': False},
            '3': {'label': 'self_custody_verified', 'description': 'SIWE signature or equivalent', 'payout_eligible': True},
            '4': {'label': 'multisig_controlled', 'description': 'Safe or similar multisig', 'payout_eligible': True},
        },
    },
    'treasury_accounts.json': {
        'accounts': {},
        'transfer_policy': {
            'requires_owner_approval': True,
            'must_maintain_reserve': True,
            'audit_required': True,
        },
    },
    'maintainers.json': {
        'maintainers': {},
        'roles': {
            'bdfl': 'Benevolent Dictator For Life -- final authority on project direction and treasury',
            'core': 'Core maintainer with merge rights and payout eligibility',
            'maintainer': 'Active maintainer with review and triage rights',
        },
    },
    'contributors.json': {
        'contributors': {},
        'contribution_types': [
            'code',
            'documentation',
            'security_report',
            'bug_report',
            'design',
            'vertical_example',
            'test_coverage',
            'review',
            'community',
        ],
        'registration_requirements': {
            'github_account': True,
            'signed_commits': False,
            'payout_wallet_level': 3,
            'notes': 'Contributors register by submitting accepted PRs. Payout eligibility requires a Level 3+ verified wallet.',
        },
    },
    'payout_proposals.json': {
        'proposals': {},
        'state_machine': {
            'states': ['draft', 'submitted', 'under_review', 'approved', 'dispute_window', 'executed', 'rejected', 'cancelled'],
            'transitions': {
                'draft': ['submitted', 'cancelled'],
                'submitted': ['under_review', 'rejected', 'cancelled'],
                'under_review': ['approved', 'rejected'],
                'approved': ['dispute_window'],
                'dispute_window': ['executed', 'rejected'],
                'executed': [],
                'rejected': [],
                'cancelled': [],
            },
            'dispute_window_hours': 72,
            'notes': 'Proposals require evidence of contribution, a reviewer, and owner approval. 72-hour dispute window between approval and execution.',
        },
        'proposal_schema': {
            'id': 'string -- unique proposal ID',
            'contributor_id': 'string -- references contributors.json',
            'amount_usd': 'number -- payout amount',
            'currency': 'string -- USDC or other',
            'contribution_type': 'string -- from contribution_types list',
            'evidence': {
                'pr_urls': ['list of PR URLs'],
                'commit_hashes': ['list of commit hashes'],
                'issue_refs': ['list of issue references'],
                'description': 'string -- summary of contribution',
            },
            'recipient_wallet_id': 'string -- references wallets.json, must be Level 3+',
            'proposed_by': 'string -- who created the proposal',
            'reviewed_by': 'string -- who reviewed',
            'approved_by': 'string -- who approved (must be owner or delegated authority)',
            'status': 'string -- from state_machine.states',
            'settlement_adapter': 'string -- adapter_id from settlement_adapters.json',
            'warrant_id': 'string or null -- executable warrant bound to payout execution',
            'created_at': 'ISO 8601 timestamp',
            'updated_at': 'ISO 8601 timestamp',
            'dispute_window_ends_at': 'ISO 8601 timestamp or null',
            'executed_at': 'ISO 8601 timestamp or null',
            'tx_hash': 'string or null -- on-chain transaction hash',
            'execution_refs': 'object -- normalized settlement proof, tx_ref, and verification/finality states',
        },
    },
    'settlement_adapters.json': {
        'default_payout_adapter': 'internal_ledger',
        'adapters': {
            'internal_ledger': {
                'label': 'Internal Ledger',
                'status': 'active',
                'payout_execution_enabled': True,
                'execution_mode': 'host_ledger',
                'settlement_path': 'journal_append',
                'supported_currencies': ['USDC', 'USD'],
                'requires_tx_hash': False,
                'requires_settlement_proof': False,
                'proof_type': 'ledger_transaction',
                'verification_mode': 'host_ledger',
                'verification_ready': True,
                'requires_verifier_attestation': False,
                'accepted_attestation_types': [],
                'verification_state': 'host_ledger_final',
                'finality_state': 'host_local_final',
                'reversal_or_dispute_capability': 'court_case',
                'dispute_model': 'court_case',
                'finality_model': 'host_local_final',
                'notes': 'Reference payout adapter. Execution settles by appending an auditable institution-ledger transaction.',
            },
            'base_usdc_x402': {
                'label': 'Base USDC via x402',
                'status': 'active',
                'payout_execution_enabled': True,
                'execution_mode': 'external_chain',
                'settlement_path': 'x402_onchain',
                'supported_currencies': ['USDC'],
                'requires_tx_hash': True,
                'requires_settlement_proof': True,
                'proof_type': 'onchain_receipt',
                'verification_mode': 'external_attestation',
                'verification_ready': True,
                'requires_verifier_attestation': True,
                'accepted_attestation_types': ['x402_settlement_verifier'],
                'verification_state': 'external_verification_required',
                'finality_state': 'external_chain_finality',
                'reversal_or_dispute_capability': 'court_case_plus_chain_review',
                'dispute_model': 'court_case_plus_chain_review',
                'finality_model': 'external_chain_finality',
                'notes': 'Enabled only as an evidence-gated x402 execution candidate. External chain finality is still required and never assumed locally.',
            },
            'manual_bank_wire': {
                'label': 'Manual Bank Wire',
                'status': 'active',
                'payout_execution_enabled': True,
                'execution_mode': 'manual_offchain',
                'settlement_path': 'manual_bank_review',
                'supported_currencies': ['USD'],
                'requires_tx_hash': False,
                'requires_settlement_proof': True,
                'proof_type': 'manual_wire_receipt',
                'verification_mode': 'manual_attestation',
                'verification_ready': True,
                'requires_verifier_attestation': True,
                'accepted_attestation_types': ['manual_wire_verifier'],
                'verification_state': 'manual_review_required',
                'finality_state': 'manual_settlement_pending',
                'reversal_or_dispute_capability': 'manual_reversal_and_court_case',
                'dispute_model': 'manual_reversal_and_court_case',
                'finality_model': 'manual_settlement_pending',
                'notes': 'Executable on the internal reference path when manual wire evidence is supplied; the wire itself remains offchain/manual.',
            },
        },
    },
    'funding_sources.json': {
        'sources': {},
        'source_types': {
            'owner_capital': 'Direct capital contribution from project owner',
            'github_sponsors': 'Recurring or one-time sponsorship via GitHub Sponsors',
            'direct_crypto': 'Direct stablecoin transfer from identified sponsor',
            'customer_payment': 'Payment for a product or service',
            'grant': 'Grant from a foundation or organization',
            'reimbursement': 'Reimbursement of expenses previously paid out-of-pocket',
        },
    },
}


def _default_org_id():
    try:
        from organizations import load_orgs
        return next(iter(load_orgs().get('organizations', {})), None)
    except Exception:
        pass
    return None


def _protocol_path(filename, org_id=None):
    return capsule_path(org_id, filename)


def _is_economy_capsule(path):
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(ECONOMY_DIR)]) == os.path.abspath(ECONOMY_DIR)
    except ValueError:
        return False


def _missing_org_error(org_id):
    raise SystemExit(
        f"ERROR: institution '{org_id}' is not initialized. Run quickstart.py --init-only or bootstrap the capsule first."
    )


def _ensure_protocol_registry(filename, org_id=None):
    path = _protocol_path(filename, org_id)
    parent = os.path.dirname(path)
    if org_id and not os.path.isdir(parent):
        _missing_org_error(org_id)
    if os.path.exists(path):
        return path

    legacy_path = os.path.join(LEGACY_TREASURY_DIR, filename)
    if _is_economy_capsule(path) and os.path.exists(legacy_path):
        os.makedirs(parent, exist_ok=True)
        with open(legacy_path) as f:
            data = json.load(f)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        return path

    os.makedirs(parent, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(_PROTOCOL_DEFAULTS[filename], f, indent=2)
    return path


# -- Core functions -----------------------------------------------------------

def get_balance(org_id=None):
    """Read treasury.cash_usd from ledger.json."""
    ledger = load_ledger(org_id)
    return ledger['treasury']['cash_usd']


def get_reserve_floor(org_id=None):
    """Read treasury.reserve_floor_usd from ledger.json."""
    ledger = load_ledger(org_id)
    return ledger['treasury'].get('reserve_floor_usd', 50.0)


def get_runway(org_id=None):
    """Balance minus reserve floor. Negative means below reserve."""
    return get_balance(org_id) - get_reserve_floor(org_id)


def get_revenue_summary(org_id=None):
    """Read revenue state from economy/revenue.py."""
    rev = load_revenue(org_id)
    ledger = load_ledger(org_id)
    t = ledger['treasury']
    orders = rev.get('orders', {})
    paid = [o for o in orders.values() if o['status'] == 'paid']
    open_orders = [o for o in orders.values() if o['status'] not in ('paid', 'rejected')]
    return {
        'total_revenue_usd': t.get('total_revenue_usd', 0.0),
        'owner_capital_contributed_usd': t.get('owner_capital_contributed_usd', 0.0),
        'receivables_usd': rev.get('receivables_usd', 0.0),
        'clients': len(rev.get('clients', {})),
        'paid_orders': len(paid),
        'open_orders': len(open_orders),
    }


def get_spend_summary(org_id, period_days=30):
    """Aggregate spend from metering.jsonl."""
    since = (datetime.datetime.utcnow() -
             datetime.timedelta(days=period_days)).strftime('%Y-%m-%dT%H:%M:%SZ')
    total = get_spend(org_id, since=since)
    return {
        'org_id': org_id,
        'period_days': period_days,
        'total_spend_usd': round(total, 4),
    }


def contribute_owner_capital(amount_usd, note='', by='owner', org_id=None):
    """Record owner capital contribution via the accounting layer.
    Falls back to direct ledger write if accounting module is not available."""
    # Accounting module is founding-service-only (single-institution).
    # Route through it only for the founding org (org_id=None).
    # Non-founding orgs use the direct capsule-path fallback below.
    if _owner_contribute_capital and org_id is None:
        return _owner_contribute_capital(amount_usd, note, actor=by)
    # Graceful fallback: write directly to ledger
    ledger = load_ledger(org_id)
    ledger['treasury']['cash_usd'] += amount_usd
    ledger['treasury']['owner_capital_contributed_usd'] = (
        ledger['treasury'].get('owner_capital_contributed_usd', 0.0) + amount_usd
    )
    ledger['updatedAt'] = _now()
    ledger_path = capsule_path(org_id, 'ledger.json')
    if org_id and not os.path.isdir(os.path.dirname(ledger_path)):
        _missing_org_error(org_id)
    with open(ledger_path, 'w') as f:
        json.dump(ledger, f, indent=2)
    # Append transaction for auditability
    tx_path = capsule_path(org_id, 'transactions.jsonl')
    if org_id and not os.path.isdir(os.path.dirname(tx_path)):
        _missing_org_error(org_id)
    tx_entry = json.dumps({
        'type': 'treasury_deposit',
        'deposit_type': 'owner_capital',
        'amount_usd': amount_usd,
        'cash_after': ledger['treasury']['cash_usd'],
        'note': note,
        'ts': _now(),
    })
    with open(tx_path, 'a') as f:
        f.write(tx_entry + '\n')
    return {
        'amount_usd': amount_usd,
        'cash_after_usd': ledger['treasury']['cash_usd'],
        'note': note,
    }


def set_reserve_floor_policy(amount_usd, note='', by='owner', org_id=None):
    """Update reserve floor policy via the accounting layer.
    Falls back to direct ledger write if accounting module is not available."""
    if _update_reserve_floor and org_id is None:
        return _update_reserve_floor(amount_usd, note, actor=by)
    # Graceful fallback: write directly to ledger
    ledger = load_ledger(org_id)
    old_floor = ledger['treasury'].get('reserve_floor_usd', 50.0)
    ledger['treasury']['reserve_floor_usd'] = amount_usd
    ledger['updatedAt'] = _now()
    ledger_path = capsule_path(org_id, 'ledger.json')
    if org_id and not os.path.isdir(os.path.dirname(ledger_path)):
        _missing_org_error(org_id)
    with open(ledger_path, 'w') as f:
        json.dump(ledger, f, indent=2)
    return {
        'old_reserve_floor_usd': old_floor,
        'new_reserve_floor_usd': amount_usd,
        'note': note,
    }


def check_budget(agent_id, cost_usd, org_id=None):
    """Check agent budget + treasury runway. Returns (allowed, reason)."""
    # Try economy_key -> registry ID mapping first
    reg_agent = _registry_get_agent_by_economy_key(agent_id, org_id=org_id)
    lookup_id = reg_agent['id'] if reg_agent else agent_id

    # Check agent-level budget
    allowed, reason = _agent_check_budget(lookup_id, cost_usd)
    if not allowed:
        return False, reason
    summary = budget_reservation_summary(org_id, agent_id=lookup_id)
    runway = summary['runway_usd']
    available = summary['available_for_reservation_usd']
    if runway < 0:
        return False, f'Treasury below reserve floor (runway ${runway:.2f}). Recapitalize before spending.'
    if available < cost_usd:
        return False, f'Treasury runway insufficient (${available:.2f} available after reservations, ${cost_usd:.2f} requested)'
    return True, 'ok'


def reserve_runtime_budget(agent_id, estimated_cost_usd, *, org_id=None, action='',
                           resource='', context=None, lease_seconds=900, policy_ref=''):
    """Reserve runtime budget before execution.

    Returns a structured decision dict with reservation metadata when allowed.
    """
    from authority import check_authority

    estimated_cost_usd = round(float(estimated_cost_usd), 4)
    if estimated_cost_usd < 0:
        raise ValueError('estimated_cost_usd must be non-negative')

    resolved_agent = _resolve_budget_agent(agent_id, org_id=org_id)
    if not resolved_agent:
        return {
            'allowed': False,
            'stage': 'approval_hook',
            'reason': 'Agent not found',
            'reservation': None,
            'budget': budget_reservation_summary(org_id),
        }

    lookup_id = resolved_agent['id']
    authority_ref = resolved_agent.get('economy_key') or lookup_id
    auth_allowed, auth_reason = check_authority(
        authority_ref,
        action or 'runtime_budget_reservation',
        org_id=org_id,
    )
    if not auth_allowed:
        stage = 'sanction_controls'
        if 'kill switch' in auth_reason.lower() or 'delegat' in auth_reason.lower():
            stage = 'approval_hook'
        return {
            'allowed': False,
            'stage': stage,
            'reason': auth_reason,
            'reservation': None,
            'budget': budget_reservation_summary(org_id, agent_id=lookup_id),
            'sanction': {
                'source': 'authority',
                'restrictions': [],
            },
        }

    budget_allowed, budget_reason = check_budget(lookup_id, estimated_cost_usd, org_id=org_id)
    if not budget_allowed:
        return {
            'allowed': False,
            'stage': 'budget_gate',
            'reason': budget_reason,
            'reservation': None,
            'budget': budget_reservation_summary(org_id, agent_id=lookup_id),
        }

    store = _load_budget_reservation_store(org_id)
    reservation_id = f'bud_{uuid.uuid4().hex[:12]}'
    now = _now()
    expires_at = (
        datetime.datetime.utcnow() + datetime.timedelta(seconds=max(1, int(lease_seconds or 0)))
    ).strftime('%Y-%m-%dT%H:%M:%SZ')
    reservation = {
        'reservation_id': reservation_id,
        'org_id': org_id,
        'agent_id': lookup_id,
        'economy_key': resolved_agent.get('economy_key') or '',
        'requested_agent_ref': agent_id,
        'status': 'reserved',
        'estimated_cost_usd': estimated_cost_usd,
        'actual_cost_usd': 0.0,
        'action': action,
        'resource': resource,
        'context': dict(context or {}),
        'policy_ref': policy_ref,
        'lease_seconds': int(lease_seconds or 0),
        'created_at': now,
        'expires_at': expires_at,
        'committed_at': None,
        'released_at': None,
        'release_reason': '',
        'commit_reason': '',
        'overage_usd': 0.0,
    }
    store['reservations'][reservation_id] = reservation
    _save_budget_reservation_store(store, org_id)
    _update_runtime_budget_ledger(
        org_id,
        reserved_delta=estimated_cost_usd,
        active_delta=1,
    )
    _append_runtime_budget_audit_event(
        org_id,
        lookup_id,
        'runtime_budget_reserved',
        reservation,
        reason='ok',
    )
    return {
        'allowed': True,
        'stage': 'budget_gate',
        'reason': 'ok',
        'reservation': reservation,
        'budget': budget_reservation_summary(org_id, agent_id=lookup_id),
    }


def commit_runtime_budget(reservation_id, actual_cost_usd=None, *, org_id=None, note=''):
    """Finalize a runtime budget reservation."""
    reservation_id = (reservation_id or '').strip()
    if not reservation_id:
        raise ValueError('reservation_id is required')
    store = _load_budget_reservation_store(org_id)
    reservation = store.get('reservations', {}).get(reservation_id)
    if not reservation:
        raise LookupError(f'Budget reservation not found: {reservation_id}')
    if reservation.get('status') not in ('reserved',):
        raise ValueError(f"Reservation {reservation_id} is already {reservation.get('status')}")
    effective_org_id = org_id or reservation.get('org_id')

    expires_at = _reservation_datetime(reservation.get('expires_at'))
    if expires_at and datetime.datetime.utcnow() > expires_at:
        raise PermissionError(f'Reservation {reservation_id} expired at {reservation.get("expires_at")}')

    estimated = float(reservation.get('estimated_cost_usd', 0.0) or 0.0)
    actual = estimated if actual_cost_usd is None else round(float(actual_cost_usd), 4)
    if actual < 0:
        raise ValueError('actual_cost_usd must be non-negative')
    overage = round(max(0.0, actual - estimated), 4)
    reservation['status'] = 'committed'
    reservation['actual_cost_usd'] = actual
    reservation['overage_usd'] = overage
    reservation['commit_reason'] = note or 'runtime budget committed'
    reservation['committed_at'] = _now()
    store['reservations'][reservation_id] = reservation
    _save_budget_reservation_store(store, effective_org_id)
    _update_runtime_budget_ledger(
        effective_org_id,
        reserved_delta=-estimated,
        committed_delta=actual,
        active_delta=-1,
    )
    _append_runtime_budget_audit_event(
        effective_org_id,
        reservation.get('agent_id'),
        'runtime_budget_committed',
        reservation,
        reason=note or 'committed',
    )
    return {
        'allowed': True,
        'reservation': reservation,
        'status': 'committed',
        'overage_usd': overage,
        'budget': budget_reservation_summary(effective_org_id, agent_id=reservation.get('agent_id')),
    }


def release_runtime_budget(reservation_id, *, org_id=None, reason=''):
    """Release a runtime budget reservation without execution."""
    reservation_id = (reservation_id or '').strip()
    if not reservation_id:
        raise ValueError('reservation_id is required')
    store = _load_budget_reservation_store(org_id)
    reservation = store.get('reservations', {}).get(reservation_id)
    if not reservation:
        raise LookupError(f'Budget reservation not found: {reservation_id}')
    if reservation.get('status') not in ('reserved',):
        raise ValueError(f"Reservation {reservation_id} is already {reservation.get('status')}")
    effective_org_id = org_id or reservation.get('org_id')
    estimated = float(reservation.get('estimated_cost_usd', 0.0) or 0.0)
    reservation['status'] = 'released'
    reservation['released_at'] = _now()
    reservation['release_reason'] = reason or 'released'
    store['reservations'][reservation_id] = reservation
    _save_budget_reservation_store(store, effective_org_id)
    _update_runtime_budget_ledger(
        effective_org_id,
        reserved_delta=-estimated,
        released_delta=estimated,
        active_delta=-1,
    )
    _append_runtime_budget_audit_event(
        effective_org_id,
        reservation.get('agent_id'),
        'runtime_budget_released',
        reservation,
        outcome='success',
        reason=reason or 'released',
    )
    return {
        'allowed': True,
        'reservation': reservation,
        'status': 'released',
        'budget': budget_reservation_summary(effective_org_id, agent_id=reservation.get('agent_id')),
    }


def expire_runtime_budget_reservations(org_id=None, now=None):
    """Expire any reservations whose lease has ended."""
    now_dt = None
    if now is None:
        now_dt = datetime.datetime.utcnow()
    elif isinstance(now, str):
        now_dt = _parse_ts(now)
    else:
        now_dt = now

    store = _load_budget_reservation_store(org_id)
    changed = False
    expired = []
    for reservation in store.get('reservations', {}).values():
        if reservation.get('status') != 'reserved':
            continue
        expires_at = _reservation_datetime(reservation.get('expires_at'))
        if expires_at and now_dt > expires_at:
            estimated = float(reservation.get('estimated_cost_usd', 0.0) or 0.0)
            reservation['status'] = 'expired'
            reservation['expired_at'] = _now()
            reservation['expired_reason'] = 'lease_expired'
            expired.append(reservation)
            changed = True
            _update_runtime_budget_ledger(
                org_id,
                reserved_delta=-estimated,
                expired_delta=estimated,
                active_delta=-1,
            )
            _append_runtime_budget_audit_event(
                org_id,
                reservation.get('agent_id'),
                'runtime_budget_expired',
                reservation,
                outcome='expired',
                reason='lease_expired',
            )
    if changed:
        _save_budget_reservation_store(store, org_id)
    return store


def record_expense(org_id, agent_id, amount_usd, category, description):
    """Record expense via metering + audit."""
    from metering import record as meter_record
    try:
        from audit import log_event
        log_event(org_id, agent_id, 'expense_recorded',
                  resource=category, outcome='success',
                  details={'amount_usd': amount_usd, 'description': description})
    except Exception:
        pass
    meter_record(org_id, agent_id, f'expense:{category}',
                 quantity=1, unit='transactions', cost_usd=amount_usd,
                 details={'description': description})


def can_payout(amount_usd, org_id=None):
    """Check if a payout is possible (balance > reserve_floor + amount)."""
    balance = get_balance(org_id)
    floor = get_reserve_floor(org_id)
    return balance >= floor + amount_usd


# -- Protocol registry readers ------------------------------------------------


def _load_registry_file(filename, org_id=None):
    """Load a JSON registry file from the institution capsule."""
    path = _ensure_protocol_registry(filename, org_id)
    with open(path, 'r') as f:
        return json.load(f)


def _write_json_file(path, payload):
    with open(path, 'w') as f:
        json.dump(payload, f, indent=2, sort_keys=True)


def _save_legacy_registry_mirror(filename, payload, canonical_path):
    if not _is_economy_capsule(canonical_path):
        return
    legacy_path = os.path.join(LEGACY_TREASURY_DIR, filename)
    if os.path.abspath(legacy_path) == os.path.abspath(canonical_path):
        return
    os.makedirs(os.path.dirname(legacy_path), exist_ok=True)
    _write_json_file(legacy_path, payload)


def _save_registry_file(filename, payload, org_id=None):
    """Persist a JSON registry file inside the institution capsule."""
    path = _ensure_protocol_registry(filename, org_id)
    parent = os.path.dirname(path)
    if org_id and not os.path.isdir(parent):
        _missing_org_error(org_id)
    os.makedirs(parent, exist_ok=True)
    _write_json_file(path, payload)
    _save_legacy_registry_mirror(filename, payload, path)


def load_wallets(org_id=None):
    """Load wallet registry from the institution capsule."""
    return _load_registry_file('wallets.json', org_id)


def load_treasury_accounts(org_id=None):
    """Load treasury accounts from the institution capsule."""
    return _load_registry_file('treasury_accounts.json', org_id)


def _wallet_store(org_id=None):
    store = dict(load_wallets(org_id))
    store.setdefault('wallets', {})
    store.setdefault('verification_levels', _PROTOCOL_DEFAULTS['wallets.json']['verification_levels'])
    return store


def _save_wallet_store(store, org_id=None):
    payload = dict(store or {})
    payload['updatedAt'] = _now()
    payload.setdefault('wallets', {})
    payload.setdefault('verification_levels', _PROTOCOL_DEFAULTS['wallets.json']['verification_levels'])
    _save_registry_file('wallets.json', payload, org_id)


def _treasury_account_store(org_id=None):
    store = dict(load_treasury_accounts(org_id))
    store.setdefault('accounts', {})
    store.setdefault('transfer_policy', _PROTOCOL_DEFAULTS['treasury_accounts.json']['transfer_policy'])
    return store


def _save_treasury_account_store(store, org_id=None):
    payload = dict(store or {})
    payload['updatedAt'] = _now()
    payload.setdefault('accounts', {})
    payload.setdefault('transfer_policy', _PROTOCOL_DEFAULTS['treasury_accounts.json']['transfer_policy'])
    _save_registry_file('treasury_accounts.json', payload, org_id)


def get_treasury_account(account_id, org_id=None):
    account_id = str(account_id or '').strip()
    if not account_id:
        raise ValueError('account_id is required')
    return _treasury_account_store(org_id).get('accounts', {}).get(account_id)


def register_wallet(wallet_id, address, *, actor_id='', org_id=None, label='', chain='base',
                    asset='USDC', verification_level=3, verification_label='',
                    verification_details='', payout_eligible=None, status='active',
                    notes=''):
    wallet_id = str(wallet_id or '').strip()
    if not wallet_id:
        raise ValueError('wallet_id is required')
    address = _normalize_chain_wallet_address(address, field_name='wallet address')
    chain = str(chain or '').strip().lower()
    if not chain:
        raise ValueError('chain is required')
    asset = str(asset or '').strip().upper()
    if not asset:
        raise ValueError('asset is required')
    level = int(verification_level)
    store = _wallet_store(org_id)
    wallets = dict(store.get('wallets', {}))
    if wallet_id in wallets:
        raise ValueError(f'Wallet already exists: {wallet_id}')
    level_contract = dict(store.get('verification_levels', {}).get(str(level), {}))
    resolved_label = str(verification_label or level_contract.get('label') or '').strip()
    if not resolved_label:
        raise ValueError('verification_label is required when verification_level is not registered')
    if payout_eligible is None:
        payout_eligible = bool(level_contract.get('payout_eligible', level >= 3))
    timestamp = _now()
    wallet = {
        'id': wallet_id,
        'label': str(label or wallet_id).strip(),
        'address': address,
        'chain': chain,
        'asset': asset,
        'verification_level': level,
        'verification_label': resolved_label,
        'verification_details': str(verification_details or '').strip(),
        'payout_eligible': bool(payout_eligible),
        'status': str(status or 'active').strip() or 'active',
        'added_at': timestamp,
        'verified_at': timestamp if level >= 3 else None,
        'notes': str(notes or '').strip(),
    }
    actor_id = str(actor_id or '').strip()
    if actor_id:
        wallet['registered_by'] = actor_id
    wallets[wallet_id] = wallet
    store['wallets'] = wallets
    _save_wallet_store(store, org_id)
    return wallet


def register_treasury_account(account_id, *, wallet_id='', actor_id='', org_id=None, label='',
                              purpose='', balance_usd=0.0, reserve_floor_usd=0.0,
                              status='active', notes=''):
    account_id = str(account_id or '').strip()
    if not account_id:
        raise ValueError('account_id is required')
    wallet_id = str(wallet_id or '').strip()
    if wallet_id and not get_wallet(wallet_id, org_id):
        raise LookupError(f'Wallet not found for treasury account: {wallet_id}')
    store = _treasury_account_store(org_id)
    accounts = dict(store.get('accounts', {}))
    if account_id in accounts:
        raise ValueError(f'Treasury account already exists: {account_id}')
    account = {
        'id': account_id,
        'label': str(label or account_id).strip(),
        'purpose': str(purpose or '').strip(),
        'balance_usd': round(float(balance_usd or 0.0), 4),
        'reserve_floor_usd': round(float(reserve_floor_usd or 0.0), 4),
        'wallet_id': wallet_id or None,
        'status': str(status or 'active').strip() or 'active',
        'notes': str(notes or '').strip(),
    }
    actor_id = str(actor_id or '').strip()
    if actor_id:
        account['registered_by'] = actor_id
    accounts[account_id] = account
    store['accounts'] = accounts
    _save_treasury_account_store(store, org_id)
    return account


def load_maintainers(org_id=None):
    """Load maintainer registry from the institution capsule."""
    return _load_registry_file('maintainers.json', org_id)


def load_contributors(org_id=None):
    """Load contributor registry from the institution capsule."""
    return _load_registry_file('contributors.json', org_id)


def load_payout_proposals(org_id=None):
    """Load payout proposals from the institution capsule."""
    return _load_registry_file('payout_proposals.json', org_id)


def load_settlement_adapters(org_id=None):
    """Load settlement adapter policy from the institution capsule."""
    return _load_registry_file('settlement_adapters.json', org_id)


def load_funding_sources(org_id=None):
    """Load funding sources from the institution capsule."""
    return _sync_funding_sources(org_id)


def _save_funding_source_store(store, org_id=None):
    payload = dict(store or {})
    payload['updatedAt'] = _now()
    payload.setdefault('sources', {})
    payload.setdefault('source_types', _PROTOCOL_DEFAULTS['funding_sources.json']['source_types'])
    _save_registry_file('funding_sources.json', payload, org_id)


def _sync_funding_sources(org_id=None):
    store = dict(_load_registry_file('funding_sources.json', org_id))
    original_sources = dict(store.get('sources', {}))
    sources = dict(original_sources)
    source_types = dict(
        store.get('source_types') or _PROTOCOL_DEFAULTS['funding_sources.json']['source_types']
    )
    store['source_types'] = source_types

    treasury = load_ledger(org_id).get('treasury', {})
    owner_capital_total = round(
        float(treasury.get('owner_capital_contributed_usd', 0.0) or 0.0),
        4,
    )
    explicit_owner_capital = round(sum(
        float(item.get('amount_usd') or 0.0)
        for item in sources.values()
        if item.get('type') == 'owner_capital'
        and not dict(item.get('metadata') or {}).get('derived_from_ledger')
    ), 4)
    derived_owner_capital = round(max(0.0, owner_capital_total - explicit_owner_capital), 4)
    derived_id = 'src_derived_owner_capital'
    if derived_owner_capital > 0:
        existing = dict(sources.get(derived_id, {}))
        metadata = dict(existing.get('metadata') or {})
        metadata.update({
            'derived_from_ledger': True,
            'source_metric': 'owner_capital_contributed_usd',
        })
        sources[derived_id] = {
            'source_id': derived_id,
            'type': 'owner_capital',
            'amount_usd': derived_owner_capital,
            'currency': 'USD',
            'actor_id': 'system',
            'note': 'Backfilled from canonical ledger owner capital total.',
            'source_ref': 'ledger_total:owner_capital',
            'metadata': metadata,
            'recorded_at': existing.get('recorded_at') or _now(),
        }
    else:
        sources.pop(derived_id, None)

    store['sources'] = sources
    if store.get('source_types') != source_types or original_sources != sources:
        _save_funding_source_store(store, org_id)
    return store


def _proposal_store(org_id=None):
    store = dict(load_payout_proposals(org_id))
    store.setdefault('proposals', {})
    store.setdefault('state_machine', _PROTOCOL_DEFAULTS['payout_proposals.json']['state_machine'])
    store.setdefault('proposal_schema', _PROTOCOL_DEFAULTS['payout_proposals.json']['proposal_schema'])
    return store


def _save_proposal_store(store, org_id=None):
    store = dict(store or {})
    store['updatedAt'] = _now()
    store.setdefault('proposals', {})
    store.setdefault('state_machine', _PROTOCOL_DEFAULTS['payout_proposals.json']['state_machine'])
    store.setdefault('proposal_schema', _PROTOCOL_DEFAULTS['payout_proposals.json']['proposal_schema'])
    _save_registry_file('payout_proposals.json', store, org_id)


def _settlement_store(org_id=None):
    store = dict(load_settlement_adapters(org_id))
    store.setdefault(
        'default_payout_adapter',
        _PROTOCOL_DEFAULTS['settlement_adapters.json']['default_payout_adapter'],
    )
    adapters = {}
    raw_adapters = store.get('adapters', {})
    for adapter_id, raw in _PROTOCOL_DEFAULTS['settlement_adapters.json']['adapters'].items():
        merged = dict(raw)
        merged.update(dict(raw_adapters.get(adapter_id, {})))
        merged['adapter_id'] = adapter_id
        merged.setdefault('label', adapter_id)
        merged.setdefault('status', 'registered')
        merged.setdefault('payout_execution_enabled', False)
        merged.setdefault('supported_currencies', ['USDC'])
        merged.setdefault('requires_tx_hash', False)
        merged.setdefault('requires_settlement_proof', False)
        merged.setdefault('proof_type', 'external_reference')
        merged.setdefault(
            'verification_mode',
            'host_ledger' if adapter_id == 'internal_ledger' else 'external_attestation',
        )
        merged.setdefault('verification_ready', adapter_id == 'internal_ledger')
        merged.setdefault(
            'requires_verifier_attestation',
            adapter_id != 'internal_ledger',
        )
        merged.setdefault('accepted_attestation_types', [])
        merged.setdefault('verification_state', 'unknown')
        merged.setdefault('finality_state', 'unknown')
        merged.setdefault('reversal_or_dispute_capability', 'court_case')
        merged.setdefault('execution_mode', 'external_reference')
        merged.setdefault('settlement_path', 'external_reference')
        merged.setdefault('dispute_model', merged.get('reversal_or_dispute_capability', 'court_case'))
        merged.setdefault('finality_model', merged.get('finality_state', 'unknown'))
        adapters[adapter_id] = merged
    for adapter_id, raw in raw_adapters.items():
        if adapter_id in adapters:
            continue
        merged = dict(raw or {})
        merged['adapter_id'] = adapter_id
        merged.setdefault('label', adapter_id)
        merged.setdefault('status', 'registered')
        merged.setdefault('payout_execution_enabled', False)
        merged.setdefault('supported_currencies', ['USDC'])
        merged.setdefault('requires_tx_hash', False)
        merged.setdefault('requires_settlement_proof', False)
        merged.setdefault('proof_type', 'external_reference')
        merged.setdefault('verification_state', 'unknown')
        merged.setdefault('finality_state', 'unknown')
        merged.setdefault('reversal_or_dispute_capability', 'court_case')
        merged.setdefault('execution_mode', 'external_reference')
        merged.setdefault('settlement_path', 'external_reference')
        merged.setdefault('dispute_model', merged.get('reversal_or_dispute_capability', 'court_case'))
        merged.setdefault('finality_model', merged.get('finality_state', 'unknown'))
        adapters[adapter_id] = merged
    store['adapters'] = adapters
    return store


def get_settlement_adapter(adapter_id, org_id=None):
    adapter_id = (adapter_id or '').strip()
    if not adapter_id:
        adapter_id = _settlement_store(org_id).get('default_payout_adapter', 'internal_ledger')
    return _settlement_store(org_id).get('adapters', {}).get(adapter_id)


def list_settlement_adapters(org_id=None, *, payout_enabled_only=False):
    rows = list(_settlement_store(org_id).get('adapters', {}).values())
    if payout_enabled_only:
        rows = [row for row in rows if row.get('payout_execution_enabled')]
    rows.sort(key=lambda row: row.get('adapter_id', ''))
    return rows


def settlement_adapter_summary(org_id=None, *, host_supported_adapters=None):
    store = _settlement_store(org_id)
    rows = list(store.get('adapters', {}).values())
    host_supported = [item for item in (host_supported_adapters or []) if item]
    payout_enabled = [row for row in rows if row.get('payout_execution_enabled')]
    return {
        'default_payout_adapter': store.get('default_payout_adapter', 'internal_ledger'),
        'total': len(rows),
        'active': len([row for row in rows if row.get('status') == 'active']),
        'payout_enabled': len(payout_enabled),
        'host_supported_adapters': host_supported,
        'host_supported_payout_adapters': [
            row.get('adapter_id', '')
            for row in payout_enabled
            if row.get('adapter_id', '') in host_supported
        ],
    }


def _settlement_adapter_readiness_messages(contract):
    messages = {
        'payout_execution_disabled': 'Payout execution is disabled for this adapter.',
        'host_not_supported': 'The current host does not advertise this adapter.',
        'verification_not_ready': 'The verification path is not ready on this host.',
    }
    blockers = list((contract or {}).get('execution_blockers', []))
    if not blockers:
        return ['Adapter is ready for execution on this host.']
    return [messages.get(blocker, f'Blocked by {blocker}.') for blocker in blockers]


def settlement_adapter_readiness_snapshot(org_id=None, *, host_supported_adapters=None):
    store = _settlement_store(org_id)
    host_supported = [item for item in (host_supported_adapters or []) if item]
    adapters = []
    for adapter in list_settlement_adapters(org_id):
        contract = _settlement_adapter_contract(
            adapter,
            host_supported_adapters=host_supported,
        )
        adapters.append({
            'adapter_id': contract['adapter_id'],
            'label': contract['label'],
            'status': contract['status'],
            'payout_execution_enabled': contract['payout_execution_enabled'],
            'execution_mode': contract['execution_mode'],
            'settlement_path': contract['settlement_path'],
            'host_supported': contract['host_supported'],
            'execution_readiness': contract['execution_readiness'],
            'execution_ready': contract['execution_ready'],
            'execution_blockers': list(contract['execution_blockers']),
            'execution_blocker_messages': _settlement_adapter_readiness_messages(contract),
            'contract_snapshot': contract['contract_snapshot'],
            'contract_digest': contract['contract_digest'],
        })
    return {
        'default_payout_adapter': store.get('default_payout_adapter', 'internal_ledger'),
        'host_supported_adapters': host_supported,
        'summary': settlement_adapter_summary(
            org_id,
            host_supported_adapters=host_supported,
        ),
        'ready_adapter_ids': [
            item['adapter_id']
            for item in adapters
            if item['execution_ready']
        ],
        'blocked_adapter_ids': [
            item['adapter_id']
            for item in adapters
            if not item['execution_ready']
        ],
        'adapters': adapters,
    }


def settlement_adapter_contract_snapshot(contract_or_adapter):
    contract = dict(contract_or_adapter or {})
    requires_verifier_attestation = bool(
        contract.get(
            'requires_verifier_attestation',
            contract.get('execution_mode', 'external_reference') != 'host_ledger'
            or contract.get('settlement_path', 'external_reference') != 'journal_append',
        )
    )
    return {
        'contract_version': 2,
        'adapter_id': (contract.get('adapter_id') or '').strip(),
        'status': contract.get('status', 'registered'),
        'payout_execution_enabled': bool(contract.get('payout_execution_enabled')),
        'execution_mode': contract.get('execution_mode', 'external_reference'),
        'settlement_path': contract.get('settlement_path', 'external_reference'),
        'supported_currencies': sorted(
            {
                str(item).upper()
                for item in contract.get('supported_currencies', [])
                if str(item).strip()
            }
        ),
        'requires_tx_hash': bool(contract.get('requires_tx_hash')),
        'requires_settlement_proof': bool(contract.get('requires_settlement_proof')),
        'requires_verifier_attestation': requires_verifier_attestation,
        'verification_mode': contract.get('verification_mode', 'unknown'),
        'verification_ready': bool(contract.get('verification_ready')),
        'accepted_attestation_types': sorted(
            {
                str(item).strip()
                for item in contract.get('accepted_attestation_types', [])
                if str(item).strip()
            }
        ),
        'proof_type': contract.get('proof_type', 'external_reference'),
        'verification_state': contract.get('verification_state', 'unknown'),
        'finality_state': contract.get('finality_state', 'unknown'),
        'finality_model': contract.get(
            'finality_model',
            contract.get('finality_state', 'unknown'),
        ),
        'reversal_or_dispute_capability': contract.get(
            'reversal_or_dispute_capability',
            'court_case',
        ),
        'dispute_model': contract.get(
            'dispute_model',
            contract.get('reversal_or_dispute_capability', 'court_case'),
        ),
    }


def settlement_adapter_contract_digest(contract_or_adapter):
    snapshot = settlement_adapter_contract_snapshot(contract_or_adapter)
    raw = json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _verification_attestation_types(normalized_proof):
    proof = (normalized_proof or {}).get('proof') or {}
    if not isinstance(proof, dict):
        return []
    candidates = []
    for key in ('verification_attestation', 'verification_attestations'):
        value = proof.get(key)
        if value in ('', None, [], {}):
            continue
        if isinstance(value, list):
            candidates.extend(value)
        else:
            candidates.append(value)
    attestation_types = set()
    for item in candidates:
        if isinstance(item, str):
            item_type = item.strip()
        elif isinstance(item, dict):
            item_type = str(
                item.get('type')
                or item.get('attestation_type')
                or ''
            ).strip()
        else:
            item_type = ''
        if item_type:
            attestation_types.add(item_type)
    return sorted(attestation_types)


def _settlement_adapter_contract(adapter, *, host_supported_adapters=None):
    adapter = dict(adapter or {})
    adapter_id = (adapter.get('adapter_id') or '').strip()
    host_supported = [item for item in (host_supported_adapters or []) if item]
    host_supported_set = set(host_supported)
    host_supported_known = host_supported_adapters is not None
    host_supported_effective = adapter_id in host_supported_set
    verification_ready = bool(
        adapter.get('verification_ready', adapter_id == 'internal_ledger')
    )
    # The reference host always has a local ledger path even when the host
    # identity does not explicitly enumerate settlement adapters.
    if host_supported_known and not host_supported_effective and adapter_id == 'internal_ledger':
        host_supported_effective = True
    blockers = []
    if not adapter.get('payout_execution_enabled'):
        blockers.append('payout_execution_disabled')
    if host_supported_known and adapter_id and not host_supported_effective:
        blockers.append('host_not_supported')
    if not verification_ready:
        blockers.append('verification_not_ready')
    contract = {
        'adapter_id': adapter_id,
        'label': adapter.get('label', adapter_id),
        'status': adapter.get('status', 'registered'),
        'payout_execution_enabled': bool(adapter.get('payout_execution_enabled')),
        'execution_mode': adapter.get('execution_mode', 'external_reference'),
        'settlement_path': adapter.get('settlement_path', 'external_reference'),
        'supported_currencies': list(adapter.get('supported_currencies', [])),
        'requires_tx_hash': bool(adapter.get('requires_tx_hash')),
        'requires_settlement_proof': bool(adapter.get('requires_settlement_proof')),
        'requires_verifier_attestation': bool(
            adapter.get(
                'requires_verifier_attestation',
                adapter.get('execution_mode', 'external_reference') != 'host_ledger'
                or adapter.get('settlement_path', 'external_reference') != 'journal_append',
            )
        ),
        'verification_mode': adapter.get('verification_mode', 'unknown'),
        'verification_ready': verification_ready,
        'accepted_attestation_types': [
            str(item).strip()
            for item in adapter.get('accepted_attestation_types', [])
            if str(item).strip()
        ],
        'proof_type': adapter.get('proof_type', 'external_reference'),
        'verification_state': adapter.get('verification_state', 'unknown'),
        'finality_state': adapter.get('finality_state', 'unknown'),
        'finality_model': adapter.get('finality_model', adapter.get('finality_state', 'unknown')),
        'reversal_or_dispute_capability': adapter.get(
            'reversal_or_dispute_capability',
            'court_case',
        ),
        'dispute_model': adapter.get(
            'dispute_model',
            adapter.get('reversal_or_dispute_capability', 'court_case'),
        ),
        'host_supported': None if not host_supported_known else host_supported_effective,
        'host_supported_adapters': host_supported,
        'execution_readiness': 'ready' if not blockers else 'blocked',
        'execution_blockers': list(blockers),
        'execution_ready': not blockers,
    }
    contract['contract_snapshot'] = settlement_adapter_contract_snapshot(contract)
    contract['contract_digest'] = settlement_adapter_contract_digest(contract)
    return contract


def _append_transaction(org_id, entry):
    tx_path = capsule_path(org_id, 'transactions.jsonl')
    if org_id and not os.path.isdir(os.path.dirname(tx_path)):
        _missing_org_error(org_id)
    os.makedirs(os.path.dirname(tx_path), exist_ok=True)
    row = dict(entry or {})
    row.setdefault('ts', _now())
    with open(tx_path, 'a') as f:
        f.write(json.dumps(row, sort_keys=True) + '\n')
    return row


def _payout_contribution_types(org_id=None):
    registry = load_contributors(org_id)
    return registry.get('contribution_types') or _PROTOCOL_DEFAULTS['contributors.json']['contribution_types']


def get_contributor(contributor_id, org_id=None):
    contributor_id = (contributor_id or '').strip()
    if not contributor_id:
        return None
    return load_contributors(org_id).get('contributors', {}).get(contributor_id)


def get_payout_proposal(proposal_id, org_id=None):
    proposal_id = (proposal_id or '').strip()
    if not proposal_id:
        return None
    return _proposal_store(org_id).get('proposals', {}).get(proposal_id)


def list_payout_proposals(org_id=None, *, status=None):
    proposals = list(_proposal_store(org_id).get('proposals', {}).values())
    if status:
        proposals = [row for row in proposals if row.get('status') == status]
    proposals.sort(
        key=lambda row: (
            row.get('updated_at', ''),
            row.get('created_at', ''),
            row.get('proposal_id', ''),
        ),
        reverse=True,
    )
    return proposals


def payout_proposal_summary(org_id=None):
    rows = list_payout_proposals(org_id)
    summary = {
        'total': len(rows),
        'draft': 0,
        'submitted': 0,
        'under_review': 0,
        'approved': 0,
        'dispute_window': 0,
        'executed': 0,
        'rejected': 0,
        'cancelled': 0,
        'requested_usd': 0.0,
        'executed_usd': 0.0,
    }
    for row in rows:
        status = row.get('status', '')
        if status in summary:
            summary[status] += 1
        amount = float(row.get('amount_usd') or 0.0)
        summary['requested_usd'] += amount
        if status == 'executed':
            summary['executed_usd'] += amount
    summary['requested_usd'] = round(summary['requested_usd'], 4)
    summary['executed_usd'] = round(summary['executed_usd'], 4)
    return summary


def _normalize_payout_evidence(evidence):
    payload = dict(evidence or {})
    payload['pr_urls'] = [str(item).strip() for item in payload.get('pr_urls', []) if str(item).strip()]
    payload['commit_hashes'] = [str(item).strip() for item in payload.get('commit_hashes', []) if str(item).strip()]
    payload['issue_refs'] = [str(item).strip() for item in payload.get('issue_refs', []) if str(item).strip()]
    payload['description'] = str(payload.get('description', '') or '').strip()
    if not (
        payload['pr_urls']
        or payload['commit_hashes']
        or payload['issue_refs']
        or payload['description']
    ):
        raise ValueError('evidence must include at least one PR URL, commit hash, issue ref, or description')
    return payload


def _normalize_settlement_proof(adapter, *, tx_hash='', settlement_proof=None):
    payload = settlement_proof
    if payload is None:
        payload = {}
    elif isinstance(payload, str):
        payload = {'reference': payload.strip()}
    else:
        payload = dict(payload)

    normalized = {
        'proof_type': adapter.get('proof_type', 'external_reference'),
        'verification_state': adapter.get('verification_state', 'unknown'),
        'finality_state': adapter.get('finality_state', 'unknown'),
        'reversal_or_dispute_capability': adapter.get(
            'reversal_or_dispute_capability',
            'court_case',
        ),
        'execution_mode': adapter.get('execution_mode', 'external_reference'),
        'settlement_path': adapter.get('settlement_path', 'external_reference'),
        'dispute_model': adapter.get(
            'dispute_model',
            adapter.get('reversal_or_dispute_capability', 'court_case'),
        ),
        'finality_model': adapter.get('finality_model', adapter.get('finality_state', 'unknown')),
    }
    tx_hash = (tx_hash or '').strip()
    if tx_hash:
        normalized['tx_hash'] = tx_hash
    if adapter.get('adapter_id') == 'internal_ledger':
        normalized['reference'] = ''
        normalized['proof'] = {'mode': 'institution_transactions_journal'}
        return normalized

    cleaned = {}
    for key, value in payload.items():
        if isinstance(value, str):
            value = value.strip()
        if value in ('', None, [], {}):
            continue
        cleaned[key] = value
    if cleaned:
        normalized['proof'] = cleaned
        if 'reference' in cleaned:
            normalized['reference'] = cleaned['reference']
    return normalized


def _require_known_settlement_adapter(adapter_id, *, org_id=None):
    adapter = get_settlement_adapter(adapter_id, org_id)
    if not adapter:
        raise ValueError(f'Unknown settlement_adapter {adapter_id!r}')
    return adapter


def _validate_payout_execution_adapter(adapter_id, *, org_id=None, currency='USDC',
                                       tx_hash='', settlement_proof=None,
                                       host_supported_adapters=None):
    adapter = _require_known_settlement_adapter(adapter_id, org_id=org_id)
    contract = _settlement_adapter_contract(
        adapter,
        host_supported_adapters=host_supported_adapters,
    )
    supported_currencies = {str(item).upper() for item in adapter.get('supported_currencies', [])}
    currency = str(currency or '').upper()
    if supported_currencies and currency not in supported_currencies:
        raise PermissionError(
            f"Settlement adapter '{adapter_id}' does not support currency {currency!r}"
        )
    if contract['payout_execution_enabled'] is False:
        raise PermissionError(
            f"Settlement adapter '{adapter_id}' is registered but not enabled for payout execution"
        )
    if contract['host_supported'] is False:
        raise PermissionError(
            f"Settlement adapter '{adapter_id}' is not supported on this host"
        )
    if contract['verification_ready'] is False:
        raise PermissionError(
            f"Settlement adapter '{adapter_id}' verification path is not ready on this host"
        )
    if adapter.get('requires_tx_hash') and not (tx_hash or '').strip():
        raise ValueError(f"Settlement adapter '{adapter_id}' requires tx_hash")
    normalized = _normalize_settlement_proof(
        adapter,
        tx_hash=tx_hash,
        settlement_proof=settlement_proof,
    )
    if adapter.get('requires_settlement_proof') and not normalized.get('proof'):
        raise ValueError(f"Settlement adapter '{adapter_id}' requires settlement_proof")
    attestation_types = _verification_attestation_types(normalized)
    if attestation_types:
        normalized['verification_attestation_types'] = attestation_types
    if contract.get('requires_verifier_attestation'):
        accepted_types = set(contract.get('accepted_attestation_types') or [])
        if not attestation_types:
            raise ValueError(
                f"Settlement adapter '{adapter_id}' requires verifier attestation"
            )
        if accepted_types and not accepted_types.intersection(attestation_types):
            raise ValueError(
                f"Settlement adapter '{adapter_id}' requires verifier attestation "
                f"matching {sorted(accepted_types)!r}"
            )
    return adapter, normalized, contract


def preflight_settlement_adapter(adapter_id='', *, org_id=None, currency='USDC',
                                 tx_hash='', settlement_proof=None,
                                 host_supported_adapters=None):
    store = _settlement_store(org_id)
    requested_adapter_id = (
        (adapter_id or '').strip()
        or store.get('default_payout_adapter', 'internal_ledger')
    )
    result = {
        'default_payout_adapter': store.get('default_payout_adapter', 'internal_ledger'),
        'requested_adapter_id': requested_adapter_id,
        'currency': (currency or 'USDC').strip().upper(),
        'host_supported_adapters': list(host_supported_adapters or []),
        'known': False,
        'preflight_ok': False,
        'can_execute_now': False,
        'error_type': '',
        'error': '',
        'execution_blockers': [],
        'execution_blocker_messages': [],
    }
    adapter = get_settlement_adapter(requested_adapter_id, org_id)
    if not adapter:
        result['error_type'] = 'unknown_adapter'
        result['error'] = f'Unknown settlement_adapter {requested_adapter_id!r}'
        return result

    contract = _settlement_adapter_contract(
        adapter,
        host_supported_adapters=host_supported_adapters,
    )
    normalized = _normalize_settlement_proof(adapter, tx_hash=tx_hash, settlement_proof=settlement_proof)
    result.update({
        'known': True,
        'adapter': adapter,
        'execution_enabled': contract['payout_execution_enabled'],
        'host_supported': contract['host_supported'],
        'requirements': {
            'supported_currencies': list(adapter.get('supported_currencies', [])),
            'requires_tx_hash': bool(adapter.get('requires_tx_hash')),
            'requires_settlement_proof': bool(adapter.get('requires_settlement_proof')),
            'requires_verifier_attestation': bool(contract.get('requires_verifier_attestation')),
            'verification_mode': adapter.get('verification_mode', 'unknown'),
            'verification_ready': bool(
                adapter.get('verification_ready', requested_adapter_id == 'internal_ledger')
            ),
            'accepted_attestation_types': [
                str(item).strip()
                for item in adapter.get('accepted_attestation_types', [])
                if str(item).strip()
            ],
            'proof_type': adapter.get('proof_type', 'external_reference'),
            'verification_state': adapter.get('verification_state', 'unknown'),
            'finality_state': adapter.get('finality_state', 'unknown'),
            'reversal_or_dispute_capability': adapter.get(
                'reversal_or_dispute_capability',
                'court_case',
            ),
            'execution_mode': adapter.get('execution_mode', 'external_reference'),
            'settlement_path': adapter.get('settlement_path', 'external_reference'),
            'finality_model': adapter.get('finality_model', adapter.get('finality_state', 'unknown')),
            'dispute_model': adapter.get(
                'dispute_model',
                adapter.get('reversal_or_dispute_capability', 'court_case'),
            ),
        },
        'contract': contract,
        'normalized_proof': normalized,
        'execution_blockers': list(contract['execution_blockers']),
        'execution_ready': contract['execution_ready'],
    })
    try:
        _validated_adapter, normalized, contract = _validate_payout_execution_adapter(
            requested_adapter_id,
            org_id=org_id,
            currency=result['currency'],
            tx_hash=tx_hash,
            settlement_proof=settlement_proof,
            host_supported_adapters=host_supported_adapters,
        )
        result['preflight_ok'] = True
        result['can_execute_now'] = True
        result['normalized_proof'] = normalized
        result['contract'] = contract
        result['execution_blockers'] = []
        result['execution_ready'] = True
    except PermissionError as exc:
        result['error_type'] = 'permission_error'
        result['error'] = str(exc)
        result['execution_blockers'] = list(contract['execution_blockers'])
        result['execution_blocker_messages'] = [str(exc)]
    except ValueError as exc:
        result['error_type'] = 'validation_error'
        result['error'] = str(exc)
        result['execution_blockers'] = list(contract['execution_blockers'])
        result['execution_blocker_messages'] = [str(exc)]
    return result


def _resolve_recipient_wallet(contributor_id, recipient_wallet_id='', org_id=None):
    contributor = get_contributor(contributor_id, org_id)
    if not contributor:
        raise LookupError(f'Contributor not found: {contributor_id}')
    wallet_id = (
        (recipient_wallet_id or '').strip()
        or (contributor.get('payout_wallet_id') or '').strip()
    )
    if not wallet_id:
        raise ValueError(
            'recipient_wallet_id is required unless the contributor record defines payout_wallet_id'
        )
    eligible, reason = can_receive_payout(wallet_id, org_id)
    if not eligible:
        raise PermissionError(reason)
    return contributor, wallet_id


def _require_transition(record, target_state, *, org_id=None):
    current_state = (record.get('status') or '').strip()
    transitions = _proposal_store(org_id).get('state_machine', {}).get('transitions', {})
    allowed = list(transitions.get(current_state, []))
    if target_state not in allowed:
        raise ValueError(
            f"Proposal '{record.get('proposal_id', '')}' cannot transition from "
            f"{current_state!r} to {target_state!r}"
        )


def _payout_phase_gate(org_id=None):
    if _current_phase is None:
        return True, 'Phase machine unavailable; payout gate deferred to treasury reserve checks'
    phase_num, phase_info = _current_phase(org_id)
    if phase_num < 5:
        return False, (
            f"Phase {phase_num} ({phase_info.get('name', '')}) does not allow contributor payouts yet"
        )
    return True, f"Phase {phase_num} ({phase_info.get('name', '')}) permits contributor payouts"


def create_payout_proposal(contributor_id, amount_usd, contribution_type, *,
                           proposed_by, org_id=None, evidence=None,
                           recipient_wallet_id='', currency='USDC',
                           settlement_adapter='internal_ledger', note='',
                           metadata=None, linked_commitment_id=''):
    contributor_id = (contributor_id or '').strip()
    proposed_by = (proposed_by or '').strip()
    contribution_type = (contribution_type or '').strip()
    currency = (currency or 'USDC').strip().upper()
    settlement_adapter = (settlement_adapter or 'internal_ledger').strip()
    linked_commitment_id = (linked_commitment_id or '').strip()
    if not contributor_id:
        raise ValueError('contributor_id is required')
    if not proposed_by:
        raise ValueError('proposed_by is required')
    amount = round(float(amount_usd), 4)
    if amount <= 0:
        raise ValueError('amount_usd must be greater than 0')
    if contribution_type not in _payout_contribution_types(org_id):
        raise ValueError(f'Unknown contribution_type {contribution_type!r}')
    _require_known_settlement_adapter(settlement_adapter, org_id=org_id)
    if linked_commitment_id and not commitments.get_commitment(linked_commitment_id, org_id=org_id):
        raise LookupError(f'Commitment not found: {linked_commitment_id}')
    normalized_evidence = _normalize_payout_evidence(evidence)
    contributor, wallet_id = _resolve_recipient_wallet(
        contributor_id,
        recipient_wallet_id=recipient_wallet_id,
        org_id=org_id,
    )
    timestamp = _now()
    proposal_id = f'ppo_{uuid.uuid4().hex[:12]}'
    record = {
        'proposal_id': proposal_id,
        'id': proposal_id,
        'institution_id': org_id or _default_org_id(),
        'contributor_id': contributor_id,
        'contributor_name': contributor.get('name', ''),
        'amount_usd': amount,
        'currency': currency,
        'contribution_type': contribution_type,
        'evidence': normalized_evidence,
        'recipient_wallet_id': wallet_id,
        'proposed_by': proposed_by,
        'reviewed_by': '',
        'approved_by': '',
        'status': 'draft',
        'created_at': timestamp,
        'updated_at': timestamp,
        'submitted_at': '',
        'reviewed_at': '',
        'approved_at': '',
        'dispute_window_started_at': '',
        'dispute_window_ends_at': '',
        'executed_at': '',
        'executed_by': '',
        'tx_hash': '',
        'warrant_id': '',
        'settlement_adapter': settlement_adapter,
        'linked_commitment_id': linked_commitment_id,
        'execution_refs': {},
        'note': note or '',
        'metadata': dict(metadata or {}),
    }
    store = _proposal_store(org_id)
    store['proposals'][proposal_id] = record
    _save_proposal_store(store, org_id)
    return record


def submit_payout_proposal(proposal_id, actor_id, *, org_id=None, note='', owner_override=False):
    actor_id = (actor_id or '').strip()
    store = _proposal_store(org_id)
    record = store['proposals'].get((proposal_id or '').strip())
    if not record:
        raise LookupError(f'Payout proposal not found: {proposal_id}')
    _require_transition(record, 'submitted', org_id=org_id)
    if not owner_override and actor_id and actor_id != record.get('proposed_by'):
        raise PermissionError('Only the proposer or owner may submit this payout proposal')
    timestamp = _now()
    record['status'] = 'submitted'
    record['submitted_at'] = timestamp
    record['updated_at'] = timestamp
    if note:
        record['note'] = note
    _save_proposal_store(store, org_id)
    return record


def review_payout_proposal(proposal_id, reviewer_id, *, org_id=None, note=''):
    reviewer_id = (reviewer_id or '').strip()
    if not reviewer_id:
        raise ValueError('reviewer_id is required')
    store = _proposal_store(org_id)
    record = store['proposals'].get((proposal_id or '').strip())
    if not record:
        raise LookupError(f'Payout proposal not found: {proposal_id}')
    _require_transition(record, 'under_review', org_id=org_id)
    if reviewer_id in {
        record.get('contributor_id', ''),
        record.get('proposed_by', ''),
    }:
        raise PermissionError('Reviewer must not be the contributor or proposer')
    timestamp = _now()
    record['status'] = 'under_review'
    record['reviewed_by'] = reviewer_id
    record['reviewed_at'] = timestamp
    record['updated_at'] = timestamp
    if note:
        record['review_note'] = note
    _save_proposal_store(store, org_id)
    return record


def approve_payout_proposal(proposal_id, approver_id, *, org_id=None, note=''):
    approver_id = (approver_id or '').strip()
    if not approver_id:
        raise ValueError('approver_id is required')
    store = _proposal_store(org_id)
    record = store['proposals'].get((proposal_id or '').strip())
    if not record:
        raise LookupError(f'Payout proposal not found: {proposal_id}')
    _require_transition(record, 'approved', org_id=org_id)
    timestamp = _now()
    record['status'] = 'approved'
    record['approved_by'] = approver_id
    record['approved_at'] = timestamp
    record['updated_at'] = timestamp
    if note:
        record['approval_note'] = note
    _save_proposal_store(store, org_id)
    return record


def open_payout_dispute_window(proposal_id, actor_id, *, org_id=None, note='', dispute_window_hours=None):
    actor_id = (actor_id or '').strip()
    if not actor_id:
        raise ValueError('actor_id is required')
    store = _proposal_store(org_id)
    record = store['proposals'].get((proposal_id or '').strip())
    if not record:
        raise LookupError(f'Payout proposal not found: {proposal_id}')
    _require_transition(record, 'dispute_window', org_id=org_id)
    state_machine = store.get('state_machine', {})
    hours = state_machine.get('dispute_window_hours', 72) if dispute_window_hours is None else float(dispute_window_hours)
    if hours < 0:
        raise ValueError('dispute_window_hours must be >= 0')
    started_at = _parse_ts(_now())
    ends_at = started_at + datetime.timedelta(hours=hours)
    record['status'] = 'dispute_window'
    record['updated_at'] = started_at.strftime('%Y-%m-%dT%H:%M:%SZ')
    record['dispute_window_started_at'] = started_at.strftime('%Y-%m-%dT%H:%M:%SZ')
    record['dispute_window_ends_at'] = ends_at.strftime('%Y-%m-%dT%H:%M:%SZ')
    if note:
        record['approval_note'] = note
    _save_proposal_store(store, org_id)
    return record


def reject_payout_proposal(proposal_id, actor_id, *, org_id=None, note=''):
    actor_id = (actor_id or '').strip()
    if not actor_id:
        raise ValueError('actor_id is required')
    store = _proposal_store(org_id)
    record = store['proposals'].get((proposal_id or '').strip())
    if not record:
        raise LookupError(f'Payout proposal not found: {proposal_id}')
    current = record.get('status', '')
    allowed = current in ('submitted', 'under_review', 'dispute_window')
    if not allowed:
        raise ValueError(f"Proposal '{proposal_id}' cannot be rejected from status {current!r}")
    timestamp = _now()
    record['status'] = 'rejected'
    record['updated_at'] = timestamp
    record['reviewed_by'] = actor_id
    record['reviewed_at'] = timestamp
    if note:
        record['review_note'] = note
    _save_proposal_store(store, org_id)
    return record


def cancel_payout_proposal(proposal_id, actor_id, *, org_id=None, note='', owner_override=False):
    actor_id = (actor_id or '').strip()
    if not actor_id:
        raise ValueError('actor_id is required')
    store = _proposal_store(org_id)
    record = store['proposals'].get((proposal_id or '').strip())
    if not record:
        raise LookupError(f'Payout proposal not found: {proposal_id}')
    current = record.get('status', '')
    allowed = current in ('draft', 'submitted')
    if not allowed:
        raise ValueError(f"Proposal '{proposal_id}' cannot be cancelled from status {current!r}")
    if not owner_override and actor_id != record.get('proposed_by'):
        raise PermissionError('Only the proposer or owner may cancel this payout proposal')
    record['status'] = 'cancelled'
    record['updated_at'] = _now()
    if note:
        record['note'] = note
    _save_proposal_store(store, org_id)
    return record


def execute_payout_proposal(proposal_id, actor_id, *, org_id=None, warrant_id='',
                            settlement_adapter='', tx_hash='', note='',
                            allow_early=False, settlement_proof=None,
                            host_supported_adapters=None, dry_run=False):
    actor_id = (actor_id or '').strip()
    if not actor_id:
        raise ValueError('actor_id is required')
    store = _proposal_store(org_id)
    record = store['proposals'].get((proposal_id or '').strip())
    if not record:
        raise LookupError(f'Payout proposal not found: {proposal_id}')
    _require_transition(record, 'executed', org_id=org_id)
    allowed, reason = _payout_phase_gate(org_id)
    if not allowed:
        raise PermissionError(reason)
    ends_at = record.get('dispute_window_ends_at', '')
    if not allow_early and ends_at:
        if _parse_ts(ends_at) > _parse_ts(_now()):
            raise PermissionError(
                f"Payout proposal '{proposal_id}' is still inside dispute window until {ends_at}"
            )
    eligible, reason = can_receive_payout(record.get('recipient_wallet_id', ''), org_id)
    if not eligible:
        raise PermissionError(reason)
    if not can_payout(float(record.get('amount_usd') or 0.0), org_id=org_id):
        raise PermissionError(
            f"Payout proposal '{proposal_id}' would breach treasury reserve floor"
        )
    linked_commitment_id = (record.get('linked_commitment_id') or '').strip()
    if linked_commitment_id:
        commitments.validate_commitment_for_settlement(
            linked_commitment_id,
            org_id=org_id,
        )

    settlement_adapter = (settlement_adapter or record.get('settlement_adapter') or 'internal_ledger').strip()
    adapter, normalized_proof, contract = _validate_payout_execution_adapter(
        settlement_adapter,
        org_id=org_id,
        currency=record.get('currency', 'USDC'),
        tx_hash=tx_hash,
        settlement_proof=settlement_proof,
        host_supported_adapters=host_supported_adapters,
    )
    ledger = load_ledger(org_id)
    treasury = ledger.setdefault('treasury', {})
    amount = round(float(record.get('amount_usd') or 0.0), 4)
    cash_before = round(float(treasury.get('cash_usd', 0.0)) or 0.0, 4)
    expenses_before = round(float(treasury.get('expenses_recorded_usd', 0.0)) or 0.0, 4)
    projected_cash = round(cash_before - amount, 4)
    projected_expenses = round(expenses_before + amount, 4)
    tx_ref = f'ptx_preview_{uuid.uuid4().hex[:12]}' if dry_run else f'ptx_{uuid.uuid4().hex[:12]}'
    execution_refs = {
        'tx_ref': tx_ref,
        'settlement_adapter': settlement_adapter,
        'settlement_adapter_contract': contract,
        'settlement_adapter_contract_snapshot': contract.get('contract_snapshot', {}),
        'settlement_adapter_contract_digest': contract.get('contract_digest', ''),
        'tx_hash': normalized_proof.get('tx_hash', ''),
        'currency': record.get('currency', 'USDC'),
        'proof_type': adapter.get('proof_type', ''),
        'verification_state': normalized_proof.get('verification_state', ''),
        'finality_state': normalized_proof.get('finality_state', ''),
        'reversal_or_dispute_capability': normalized_proof.get(
            'reversal_or_dispute_capability',
            '',
        ),
        'proof': normalized_proof.get('proof', {}),
        'linked_commitment_id': linked_commitment_id,
    }
    execution_plan = {
        'tx_ref': tx_ref,
        'proposal_id': proposal_id,
        'warrant_id': (warrant_id or '').strip(),
        'linked_commitment_id': linked_commitment_id,
        'settlement_adapter': settlement_adapter,
        'amount_usd': amount,
        'currency': record.get('currency', 'USDC'),
        'cash_before': cash_before,
        'cash_after': projected_cash,
        'expenses_before': expenses_before,
        'expenses_after': projected_expenses,
        'recipient_wallet_id': record.get('recipient_wallet_id', ''),
        'settlement_adapter_contract': contract,
        'settlement_adapter_contract_snapshot': contract.get('contract_snapshot', {}),
        'settlement_adapter_contract_digest': contract.get('contract_digest', ''),
        'execution_refs': execution_refs,
    }
    execution_queue_base = {
        'execution_id': tx_ref,
        'proposal_id': proposal_id,
        'warrant_id': (warrant_id or '').strip(),
        'settlement_adapter': settlement_adapter,
        'dispatch_ready': bool(contract.get('execution_ready')),
        'dispatch_blockers': list(contract.get('execution_blockers') or []),
        'execution_ready': bool(contract.get('execution_ready')),
        'settlement_claimed': False,
        'external_settlement_observed': False,
        'proof_type': adapter.get('proof_type', ''),
        'tx_hash': normalized_proof.get('tx_hash', ''),
        'execution_refs': execution_refs,
        'execution_plan': execution_plan,
        'proposal_snapshot': {
            'proposal_id': proposal_id,
            'status': record.get('status', ''),
            'amount_usd': amount,
            'currency': record.get('currency', 'USDC'),
            'contributor_id': record.get('contributor_id', ''),
            'recipient_wallet_id': record.get('recipient_wallet_id', ''),
            'linked_commitment_id': linked_commitment_id,
        },
        'adapter_contract_snapshot': contract.get('contract_snapshot', {}),
        'adapter_contract_digest': contract.get('contract_digest', ''),
        'generated_at': record.get('updated_at', '') or _now(),
        'queued_at': record.get('updated_at', '') or _now(),
        'note': note or '',
    }
    if dry_run:
        preview_timestamp = _now()
        preview_record = {
            'preview_id': tx_ref,
            'proposal_id': proposal_id,
            'status_at_preview': record.get('status', ''),
            'warrant_id': (warrant_id or '').strip(),
            'settlement_adapter': settlement_adapter,
            'preview_state': 'previewed',
            'dry_run': True,
            'execution_ready': True,
            'settlement_claimed': False,
            'external_settlement_observed': False,
            'preview_truth_source': 'payout_dry_run_and_adapter_contract_only',
            'contract': contract,
            'normalized_proof': normalized_proof,
            'execution_plan': execution_plan,
            'proposal_snapshot': {
                'proposal_id': proposal_id,
                'status': record.get('status', ''),
                'amount_usd': amount,
                'currency': record.get('currency', 'USDC'),
                'contributor_id': record.get('contributor_id', ''),
                'recipient_wallet_id': record.get('recipient_wallet_id', ''),
                'linked_commitment_id': linked_commitment_id,
            },
            'tx_hash': normalized_proof.get('tx_hash', ''),
            'generated_at': preview_timestamp,
            'previewed_at': preview_timestamp,
            'queued_at': preview_timestamp,
            'note': note or '',
        }
        preview_queue_record = None
        preview_queue_error = ''
        try:
            preview_queue_record = upsert_payout_plan_preview(org_id, preview_record)
        except (SystemExit, ValueError, FileNotFoundError, OSError) as exc:
            preview_queue_error = str(exc)
        execution_queue_record = None
        execution_queue_error = ''
        try:
            execution_queue_record = upsert_payout_execution_record(
                org_id,
                dict(execution_queue_base),
                state='previewed',
                generated_at=preview_timestamp,
                queued_at=preview_timestamp,
                dispatched_at='',
                executed_at='',
                execution_refs=execution_refs,
            )
        except (SystemExit, ValueError, FileNotFoundError, OSError) as exc:
            execution_queue_error = str(exc)
        return {
            'dry_run': True,
            'proposal_id': proposal_id,
            'status': record.get('status', ''),
            'warrant_id': (warrant_id or '').strip(),
            'settlement_adapter': settlement_adapter,
            'tx_hash': normalized_proof.get('tx_hash', ''),
            'amount_usd': amount,
            'recipient_wallet_id': record.get('recipient_wallet_id', ''),
            'contract': contract,
            'normalized_proof': normalized_proof,
            'execution_plan': execution_plan,
            'plan_preview_queue_record': preview_queue_record,
            'plan_preview_queue_persisted': preview_queue_record is not None,
            'plan_preview_queue_error': preview_queue_error,
            'execution_queue_record': execution_queue_record,
            'execution_queue_persisted': execution_queue_record is not None,
            'execution_queue_error': execution_queue_error,
        }
    treasury['cash_usd'] = projected_cash
    treasury['expenses_recorded_usd'] = projected_expenses
    ledger['updatedAt'] = _now()
    ledger_path = capsule_path(org_id, 'ledger.json')
    if org_id and not os.path.isdir(os.path.dirname(ledger_path)):
        _missing_org_error(org_id)
    os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
    with open(ledger_path, 'w') as f:
        json.dump(ledger, f, indent=2)

    tx_row = _append_transaction(org_id, {
        'tx_ref': tx_ref,
        'type': 'payout_execution',
        'proposal_id': proposal_id,
        'contributor_id': record.get('contributor_id', ''),
        'recipient_wallet_id': record.get('recipient_wallet_id', ''),
        'amount_usd': amount,
        'currency': record.get('currency', 'USDC'),
        'settlement_adapter': settlement_adapter,
        'tx_hash': normalized_proof.get('tx_hash', ''),
        'verification_state': normalized_proof.get('verification_state', ''),
        'finality_state': normalized_proof.get('finality_state', ''),
        'warrant_id': (warrant_id or '').strip(),
        'cash_after': treasury['cash_usd'],
        'by': actor_id,
        'note': note or '',
        'settlement_proof': normalized_proof.get('proof', {}),
        'settlement_adapter_contract': contract,
        'settlement_adapter_contract_snapshot': contract.get('contract_snapshot', {}),
        'settlement_adapter_contract_digest': contract.get('contract_digest', ''),
    })
    timestamp = _now()
    record['status'] = 'executed'
    record['updated_at'] = timestamp
    record['executed_at'] = timestamp
    record['executed_by'] = actor_id
    record['warrant_id'] = (warrant_id or '').strip()
    record['settlement_adapter'] = settlement_adapter
    record['settlement_adapter_contract'] = contract
    record['settlement_adapter_contract_snapshot'] = contract.get('contract_snapshot', {})
    record['settlement_adapter_contract_digest'] = contract.get('contract_digest', '')
    record['tx_hash'] = normalized_proof.get('tx_hash', '')
    record['execution_refs'] = dict(execution_refs)
    execution_queue_record = None
    execution_queue_error = ''
    try:
        execution_queue_record = upsert_payout_execution_record(
            org_id,
            dict(execution_queue_base),
            state='dispatchable',
            dispatched_at=timestamp,
            execution_refs=dict(execution_refs),
        )
    except (SystemExit, ValueError, FileNotFoundError, OSError) as exc:
        execution_queue_error = str(exc)
    record['execution_queue_record'] = execution_queue_record
    record['execution_queue_persisted'] = execution_queue_record is not None
    record['execution_queue_error'] = execution_queue_error
    if note:
        record['execution_note'] = note
    linked_commitment = None
    if linked_commitment_id:
        linked_commitment = commitments.record_settlement_ref(
            linked_commitment_id,
            {
                'proposal_id': proposal_id,
                'tx_ref': tx_row['tx_ref'],
                'settlement_adapter': settlement_adapter,
                'settlement_adapter_contract': contract,
                'settlement_adapter_contract_snapshot': contract.get('contract_snapshot', {}),
                'settlement_adapter_contract_digest': contract.get('contract_digest', ''),
                'tx_hash': normalized_proof.get('tx_hash', ''),
                'currency': record.get('currency', 'USDC'),
                'proof_type': adapter.get('proof_type', ''),
                'verification_state': normalized_proof.get('verification_state', ''),
                'finality_state': normalized_proof.get('finality_state', ''),
                'warrant_id': (warrant_id or '').strip(),
                'recorded_by': actor_id,
                'proof': normalized_proof.get('proof', {}),
            },
            org_id=org_id,
        )
    _save_proposal_store(store, org_id)
    try:
        execution_queue_record = upsert_payout_execution_record(
            org_id,
            dict(execution_queue_base),
            state='executed',
            dispatched_at=timestamp,
            executed_at=timestamp,
            execution_refs=dict(execution_refs),
        )
    except (SystemExit, ValueError, FileNotFoundError, OSError) as exc:
        execution_queue_error = str(exc)
    record['execution_queue_record'] = execution_queue_record
    record['execution_queue_persisted'] = execution_queue_record is not None
    record['execution_queue_error'] = execution_queue_error
    if linked_commitment is not None:
        record['linked_commitment'] = linked_commitment
    return record


def get_wallet(wallet_id, org_id=None):
    """Get a single wallet by ID. Returns None if not found."""
    wallets = load_wallets(org_id)
    return wallets.get('wallets', {}).get(wallet_id)


def get_payout_eligible_wallets(org_id=None):
    """Return dict of wallets with verification Level 3+."""
    wallets = load_wallets(org_id)
    return {wid: w for wid, w in wallets.get('wallets', {}).items()
            if (w.get('verification_level') or 0) >= 3 and w.get('payout_eligible')}


def can_receive_payout(wallet_id, org_id=None):
    """Check if a wallet can receive payouts. Returns (bool, reason)."""
    wallet = get_wallet(wallet_id, org_id)
    if not wallet:
        return False, f'Wallet {wallet_id} not found in registry'
    level = wallet.get('verification_level')
    if level is None:
        return False, f'Wallet {wallet_id} has no verification level (status: {wallet.get("status")})'
    if level < 3:
        label = wallet.get('verification_label', 'unknown')
        return False, f'Wallet {wallet_id} is Level {level} ({label}). Minimum Level 3 (self_custody_verified) required.'
    if not wallet.get('payout_eligible'):
        return False, f'Wallet {wallet_id} is Level {level} but payout_eligible is false'
    if wallet.get('status') != 'active':
        return False, f'Wallet {wallet_id} status is {wallet.get("status")}, must be active'
    return True, f'Wallet {wallet_id} is Level {level} ({wallet.get("verification_label")}), payout eligible'


def _normalize_chain_wallet_address(address, *, field_name):
    text = str(address or '').strip()
    if not re.fullmatch(r'0x[0-9a-fA-F]{40}', text):
        raise ValueError(f'{field_name} must be a 20-byte hex address')
    return '0x' + text[2:].lower()


def _parse_rpc_quantity(value, *, field_name):
    text = str(value or '').strip()
    if not text.startswith('0x'):
        raise ValueError(f'{field_name} must be a 0x-prefixed RPC quantity')
    return int(text, 16)


def _format_rpc_quantity(value, *, field_name):
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f'{field_name} is required')
        if text.startswith('0x'):
            return '0x0' if text.lower() == '0x' else '0x' + (text[2:].lstrip('0') or '0')
        value = int(text, 10)
    elif isinstance(value, Decimal):
        value = int(value)
    elif value is None:
        raise ValueError(f'{field_name} is required')
    value = int(value)
    if value < 0:
        raise ValueError(f'{field_name} must be >= 0')
    return hex(value)


def _format_uint256(value, *, field_name):
    value = int(value)
    if value < 0:
        raise ValueError(f'{field_name} must be >= 0')
    if value >= 2 ** 256:
        raise ValueError(f'{field_name} exceeds uint256')
    return format(value, '064x')


def _encode_erc20_transfer_calldata(recipient_address, amount_base_units):
    recipient = _normalize_chain_wallet_address(
        recipient_address,
        field_name='recipient_address',
    )
    return '0x' + _ERC20_TRANSFER_SELECTOR + recipient[2:].rjust(64, '0') + _format_uint256(
        amount_base_units,
        field_name='amount_base_units',
    )


def _encode_erc20_balance_of_calldata(address):
    normalized = _normalize_chain_wallet_address(address, field_name='wallet_address')
    return '0x' + _ERC20_BALANCE_OF_SELECTOR + normalized[2:].rjust(64, '0')


def _json_rpc_request(rpc_url, method, params=None, *, timeout_seconds=10):
    rpc_url = str(rpc_url or '').strip()
    if not rpc_url:
        raise ValueError('rpc_url is required')
    if not (rpc_url.lower().startswith('http://') or rpc_url.lower().startswith('https://')):
        raise RuntimeError(f'Invalid RPC URL scheme in {rpc_url!r}')
    payload = {
        'jsonrpc': '2.0',
        'id': f'rpc_{uuid.uuid4().hex[:12]}',
        'method': method,
        'params': list(params or []),
    }
    req = urllib_request.Request(
        rpc_url,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'MeridianKernel/1.0',
        },
        method='POST',
    )
    try:
        with urllib_request.urlopen(req, timeout=timeout_seconds) as response:
            body = response.read().decode('utf-8')
    except urllib_error.HTTPError as exc:
        body = exc.read().decode('utf-8')
        raise RuntimeError(
            f'RPC {method} failed with HTTP {exc.code}: {body or exc.reason}'
        ) from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f'RPC {method} failed: {exc.reason}') from exc
    try:
        decoded = json.loads(body or '{}')
    except json.JSONDecodeError as exc:
        raise RuntimeError(f'RPC {method} returned invalid JSON') from exc
    if decoded.get('error'):
        error_payload = decoded.get('error') or {}
        raise RuntimeError(
            f"RPC {method} error {error_payload.get('code', 'unknown')}: "
            f"{error_payload.get('message', 'unknown error')}"
        )
    return decoded.get('result')


def _redact_rpc_url(rpc_url):
    parsed = urllib_parse.urlsplit(str(rpc_url or '').strip())
    if not parsed.scheme or not parsed.netloc:
        return ''
    path = parsed.path or ''
    return urllib_parse.urlunsplit((parsed.scheme, parsed.netloc, path, '', ''))


def _wallet_chain_asset_guard(wallet, wallet_id, *, expected_chain, expected_asset, role_label):
    chain = str(wallet.get('chain') or '').strip().lower()
    asset = str(wallet.get('asset') or '').strip().upper()
    if chain != expected_chain:
        raise ValueError(
            f"{role_label} wallet {wallet_id!r} is registered for chain {chain!r}, "
            f'expected {expected_chain!r}'
        )
    if asset != expected_asset:
        raise ValueError(
            f"{role_label} wallet {wallet_id!r} is registered for asset {asset!r}, "
            f'expected {expected_asset!r}'
        )
    return chain, asset


def _resolve_x402_sender_wallet(*, org_id=None, sender_wallet_id='', source_account_id='company_treasury'):
    accounts = load_treasury_accounts(org_id).get('accounts', {})
    resolved_wallet_id = (sender_wallet_id or '').strip()
    account = {}
    if resolved_wallet_id:
        account = dict(accounts.get((source_account_id or '').strip(), {}))
    else:
        source_account_id = (source_account_id or 'company_treasury').strip()
        account = dict(accounts.get(source_account_id, {}))
        if not account:
            raise LookupError(f'Treasury account not found: {source_account_id}')
        resolved_wallet_id = str(account.get('wallet_id') or '').strip()
        if not resolved_wallet_id:
            raise ValueError(
                f"Treasury account '{source_account_id}' does not define a wallet_id"
            )
    wallet = get_wallet(resolved_wallet_id, org_id)
    if not wallet:
        raise LookupError(f'Sender wallet not found: {resolved_wallet_id}')
    return account, resolved_wallet_id, wallet


def _append_structured_blocker(target, code, message):
    existing = {item.get('code') for item in target if isinstance(item, dict)}
    if code in existing:
        return
    target.append({'code': code, 'message': message})


def _prepare_x402_execution_gate_blockers(record, *, org_id=None):
    blockers = []
    try:
        _require_transition(record, 'executed', org_id=org_id)
    except ValueError as exc:
        _append_structured_blocker(blockers, 'proposal_not_executable', str(exc))
    phase_allowed, phase_reason = _payout_phase_gate(org_id)
    if not phase_allowed:
        _append_structured_blocker(blockers, 'payout_phase_blocked', phase_reason)
    ends_at = str(record.get('dispute_window_ends_at') or '').strip()
    if ends_at and _parse_ts(ends_at) > _parse_ts(_now()):
        _append_structured_blocker(
            blockers,
            'dispute_window_open',
            (
                f"Payout proposal '{record.get('proposal_id', '')}' remains inside "
                f'the dispute window until {ends_at}'
            ),
        )
    eligible, reason = can_receive_payout(record.get('recipient_wallet_id', ''), org_id)
    if not eligible:
        _append_structured_blocker(blockers, 'recipient_wallet_ineligible', reason)
    amount = round(float(record.get('amount_usd') or 0.0), 4)
    if not can_payout(amount, org_id=org_id):
        _append_structured_blocker(
            blockers,
            'reserve_floor_breach',
            f"Payout proposal '{record.get('proposal_id', '')}' would breach treasury reserve floor",
        )
    linked_commitment_id = str(record.get('linked_commitment_id') or '').strip()
    if linked_commitment_id:
        try:
            commitments.validate_commitment_for_settlement(
                linked_commitment_id,
                org_id=org_id,
            )
        except Exception as exc:
            _append_structured_blocker(
                blockers,
                'linked_commitment_not_ready',
                str(exc),
            )
    return blockers


def _signer_backend_status():
    try:
        from eth_account import Account  # noqa: F401
    except Exception as exc:
        return {
            'available': False,
            'backend': 'eth_account',
            'error': f'{exc.__class__.__name__}: {exc}',
        }
    return {
        'available': True,
        'backend': 'eth_account',
        'error': '',
    }


def _load_eth_account_backend():
    try:
        from eth_account import Account
    except Exception as exc:
        raise RuntimeError(
            'eth_account is required for x402 signing. Install eth-account to enable this path.'
        ) from exc
    return Account


def _parse_int_like(value, *, field_name):
    if value in ('', None):
        raise ValueError(f'{field_name} is required')
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f'{field_name} is required')
        return int(text, 16) if text.startswith('0x') else int(text, 10)
    if isinstance(value, Decimal):
        value = int(value)
    return int(value)


def _x402_network_classification(chain_id):
    if int(chain_id) == _BASE_MAINNET_CHAIN_ID:
        return 'base_mainnet'
    if int(chain_id) == _BASE_SEPOLIA_CHAIN_ID:
        return 'base_sepolia'
    return 'dev_or_nonmainnet'


def _checksum_signing_address(address):
    normalized = _normalize_chain_wallet_address(address, field_name='transaction address')
    try:
        from eth_utils import to_checksum_address
    except Exception:
        return normalized
    return to_checksum_address(normalized)


def prepare_x402_unsigned_transfer_for_payout(proposal_id, actor_id, *, org_id=None,
                                              rpc_url='', token_contract_address='',
                                              sender_wallet_id='',
                                              source_account_id='company_treasury',
                                              nonce=None, gas_limit=None,
                                              gas_price_wei=None,
                                              host_supported_adapters=None,
                                              timeout_seconds=10):
    actor_id = str(actor_id or '').strip()
    if not actor_id:
        raise ValueError('actor_id is required')
    proposal_id = str(proposal_id or '').strip()
    if not proposal_id:
        raise ValueError('proposal_id is required')
    record = get_payout_proposal(proposal_id, org_id)
    if not record:
        raise LookupError(f'Payout proposal not found: {proposal_id}')

    settlement_adapter = str(record.get('settlement_adapter') or '').strip()
    if settlement_adapter != 'base_usdc_x402':
        raise ValueError(
            f"Proposal '{proposal_id}' is not configured for base_usdc_x402"
        )

    adapter = _require_known_settlement_adapter('base_usdc_x402', org_id=org_id)
    contract = _settlement_adapter_contract(
        adapter,
        host_supported_adapters=host_supported_adapters,
    )
    token_contract = _normalize_chain_wallet_address(
        token_contract_address,
        field_name='token_contract_address',
    )

    account, resolved_sender_wallet_id, sender_wallet = _resolve_x402_sender_wallet(
        org_id=org_id,
        sender_wallet_id=sender_wallet_id,
        source_account_id=source_account_id,
    )
    recipient_wallet_id = str(record.get('recipient_wallet_id') or '').strip()
    recipient_wallet = get_wallet(recipient_wallet_id, org_id)
    if not recipient_wallet:
        raise LookupError(f'Recipient wallet not found: {recipient_wallet_id}')

    _wallet_chain_asset_guard(
        sender_wallet,
        resolved_sender_wallet_id,
        expected_chain='base',
        expected_asset='USDC',
        role_label='Sender',
    )
    _wallet_chain_asset_guard(
        recipient_wallet,
        recipient_wallet_id,
        expected_chain='base',
        expected_asset='USDC',
        role_label='Recipient',
    )

    sender_address = _normalize_chain_wallet_address(
        sender_wallet.get('address'),
        field_name=f'sender wallet {resolved_sender_wallet_id} address',
    )
    recipient_address = _normalize_chain_wallet_address(
        recipient_wallet.get('address'),
        field_name=f'recipient wallet {recipient_wallet_id} address',
    )

    rpc_calls = []

    def _rpc(method, params=None):
        result = _json_rpc_request(
            rpc_url,
            method,
            params=params,
            timeout_seconds=timeout_seconds,
        )
        rpc_calls.append({'method': method, 'params': list(params or []), 'result': result})
        return result

    chain_id = _parse_rpc_quantity(_rpc('eth_chainId', []), field_name='eth_chainId')
    network_classification = 'base_mainnet' if chain_id == _BASE_MAINNET_CHAIN_ID else 'dev_or_nonmainnet'

    decimals_hex = _rpc(
        'eth_call',
        [
            {
                'to': token_contract,
                'data': '0x' + _ERC20_DECIMALS_SELECTOR,
            },
            'latest',
        ],
    )
    token_decimals = _parse_rpc_quantity(decimals_hex, field_name='erc20 decimals')
    nominal_amount = Decimal(str(record.get('amount_usd') or 0.0))
    base_unit_multiplier = Decimal(10) ** token_decimals
    amount_base_units_decimal = nominal_amount * base_unit_multiplier
    if amount_base_units_decimal != amount_base_units_decimal.to_integral_value():
        raise ValueError(
            'Payout amount cannot be represented exactly at the token decimal precision'
        )
    amount_base_units = int(amount_base_units_decimal)
    calldata = _encode_erc20_transfer_calldata(recipient_address, amount_base_units)

    resolved_nonce = (
        _parse_rpc_quantity(str(nonce), field_name='nonce')
        if nonce not in ('', None)
        else _parse_rpc_quantity(
            _rpc('eth_getTransactionCount', [sender_address, 'pending']),
            field_name='eth_getTransactionCount',
        )
    )
    resolved_gas_price = (
        _parse_rpc_quantity(str(gas_price_wei), field_name='gas_price_wei')
        if gas_price_wei not in ('', None)
        else _parse_rpc_quantity(_rpc('eth_gasPrice', []), field_name='eth_gasPrice')
    )
    resolved_gas_limit = (
        _parse_rpc_quantity(str(gas_limit), field_name='gas_limit')
        if gas_limit not in ('', None)
        else _parse_rpc_quantity(
            _rpc(
                'eth_estimateGas',
                [
                    {
                        'from': sender_address,
                        'to': token_contract,
                        'value': '0x0',
                        'data': calldata,
                    }
                ],
            ),
            field_name='eth_estimateGas',
        )
    )
    sender_native_balance = _parse_rpc_quantity(
        _rpc('eth_getBalance', [sender_address, 'latest']),
        field_name='eth_getBalance',
    )
    sender_token_balance = _parse_rpc_quantity(
        _rpc(
            'eth_call',
            [
                {
                    'to': token_contract,
                    'data': _encode_erc20_balance_of_calldata(sender_address),
                },
                'latest',
            ],
        ),
        field_name='sender balanceOf',
    )
    recipient_token_balance = _parse_rpc_quantity(
        _rpc(
            'eth_call',
            [
                {
                    'to': token_contract,
                    'data': _encode_erc20_balance_of_calldata(recipient_address),
                },
                'latest',
            ],
        ),
        field_name='recipient balanceOf',
    )

    unsigned_transaction = {
        'chainId': chain_id,
        'from': sender_address,
        'to': token_contract,
        'nonce': _format_rpc_quantity(resolved_nonce, field_name='nonce'),
        'gas': _format_rpc_quantity(resolved_gas_limit, field_name='gas'),
        'gasPrice': _format_rpc_quantity(resolved_gas_price, field_name='gasPrice'),
        'value': '0x0',
        'data': calldata,
    }

    actual_transfer_blockers = _prepare_x402_execution_gate_blockers(record, org_id=org_id)
    if not contract.get('payout_execution_enabled'):
        _append_structured_blocker(
            actual_transfer_blockers,
            'adapter_execution_disabled',
            "Settlement adapter 'base_usdc_x402' is not enabled for payout execution",
        )
    if contract.get('host_supported') is False:
        _append_structured_blocker(
            actual_transfer_blockers,
            'host_not_supported',
            "Settlement adapter 'base_usdc_x402' is not supported on this host",
        )
    if not contract.get('verification_ready'):
        _append_structured_blocker(
            actual_transfer_blockers,
            'verification_not_ready',
            "Settlement adapter 'base_usdc_x402' verification path is not ready on this host",
        )
    sender_level = sender_wallet.get('verification_level')
    if sender_level is None or int(sender_level) < 3:
        _append_structured_blocker(
            actual_transfer_blockers,
            'sender_wallet_not_self_custody_verified',
            (
                f"Sender wallet '{resolved_sender_wallet_id}' is Level "
                f"{sender_level if sender_level is not None else 'unknown'} "
                f"({sender_wallet.get('verification_label') or 'unknown'}); "
                'actual broadcast requires Level 3+ custody verification or a multisig-controlled source wallet.'
            ),
        )
    estimated_fee_wei = resolved_gas_limit * resolved_gas_price
    if sender_native_balance < estimated_fee_wei:
        _append_structured_blocker(
            actual_transfer_blockers,
            'insufficient_native_balance_for_gas',
            (
                f'Sender native balance {sender_native_balance} wei is below the '
                f'estimated gas requirement {estimated_fee_wei} wei.'
            ),
        )
    if sender_token_balance < amount_base_units:
        _append_structured_blocker(
            actual_transfer_blockers,
            'insufficient_usdc_balance',
            (
                f'Sender token balance {sender_token_balance} base units is below the '
                f'required amount {amount_base_units}.'
            ),
        )
    _append_structured_blocker(
        actual_transfer_blockers,
        'post_broadcast_evidence_required',
        'execute_payout_proposal still requires tx_hash, settlement_proof, and x402_settlement_verifier attestation after operator broadcast.',
    )

    return {
        'prepared_at': _now(),
        'prepared_by': actor_id,
        'org_id': org_id or _default_org_id(),
        'proposal_id': proposal_id,
        'proposal_status': record.get('status', ''),
        'proposal_currency': record.get('currency', 'USDC'),
        'settlement_adapter': 'base_usdc_x402',
        'rpc_transport': 'json_rpc_http',
        'rpc_url_redacted': _redact_rpc_url(rpc_url),
        'source_account_id': str(account.get('id') or source_account_id or '').strip(),
        'sender_wallet_id': resolved_sender_wallet_id,
        'sender_wallet': {
            'id': resolved_sender_wallet_id,
            'address': sender_address,
            'chain': sender_wallet.get('chain'),
            'asset': sender_wallet.get('asset'),
            'verification_level': sender_wallet.get('verification_level'),
            'verification_label': sender_wallet.get('verification_label'),
            'status': sender_wallet.get('status'),
        },
        'recipient_wallet_id': recipient_wallet_id,
        'recipient_wallet': {
            'id': recipient_wallet_id,
            'address': recipient_address,
            'chain': recipient_wallet.get('chain'),
            'asset': recipient_wallet.get('asset'),
            'verification_level': recipient_wallet.get('verification_level'),
            'verification_label': recipient_wallet.get('verification_label'),
            'status': recipient_wallet.get('status'),
        },
        'adapter_contract': contract,
        'adapter_contract_snapshot': contract.get('contract_snapshot', {}),
        'adapter_contract_digest': contract.get('contract_digest', ''),
        'token': {
            'symbol': 'USDC',
            'chain': 'base',
            'chain_id': chain_id,
            'network_classification': network_classification,
            'contract_address': token_contract,
            'decimals': token_decimals,
        },
        'amount': {
            'proposal_amount_usd': str(nominal_amount),
            'nominal_token_amount': str(nominal_amount),
            'token_decimals': token_decimals,
            'base_units': str(amount_base_units),
            'accounting_assumption': 'Kernel models USDC payouts at nominal USD parity; transaction amount is derived from proposal.amount_usd.',
        },
        'rpc_observations': {
            'chain_id': chain_id,
            'nonce': resolved_nonce,
            'gas_price_wei': str(resolved_gas_price),
            'gas_limit': resolved_gas_limit,
            'estimated_fee_wei': str(estimated_fee_wei),
            'sender_native_balance_wei': str(sender_native_balance),
            'sender_token_balance_base_units': str(sender_token_balance),
            'recipient_token_balance_base_units': str(recipient_token_balance),
            'calls': rpc_calls,
        },
        'unsigned_transaction_prepared': True,
        'unsigned_transaction': unsigned_transaction,
        'actual_transfer_blockers': actual_transfer_blockers,
        'operator_actions_remaining': [
            'Review the unsigned transaction fields against the intended recipient and token contract.',
            'Sign with a matching self-custody or multisig-controlled sender key.',
            'Broadcast with eth_sendRawTransaction only on the intended network.',
            'Capture tx hash, settlement proof, and x402_settlement_verifier attestation before execute_payout_proposal.',
        ],
    }


def sign_x402_transfer_for_payout(proposal_id, actor_id, *, org_id=None,
                                  rpc_url='', token_contract_address='',
                                  private_key_env='MERIDIAN_X402_DEV_PRIVATE_KEY',
                                  sender_wallet_id='',
                                  source_account_id='company_treasury',
                                  nonce=None, gas_limit=None,
                                  gas_price_wei=None,
                                  host_supported_adapters=None,
                                  timeout_seconds=10,
                                  allow_mainnet_signing=False,
                                  broadcast=False,
                                  allow_mainnet_broadcast=False):
    result = prepare_x402_unsigned_transfer_for_payout(
        proposal_id,
        actor_id,
        org_id=org_id,
        rpc_url=rpc_url,
        token_contract_address=token_contract_address,
        sender_wallet_id=sender_wallet_id,
        source_account_id=source_account_id,
        nonce=nonce,
        gas_limit=gas_limit,
        gas_price_wei=gas_price_wei,
        host_supported_adapters=host_supported_adapters,
        timeout_seconds=timeout_seconds,
    )
    signer_status = _signer_backend_status()
    result['signer_backend'] = signer_status
    result['signing_private_key_env'] = private_key_env
    result['signing_performed'] = False
    result['signing_blockers'] = []
    result['signed_transaction'] = None
    result['broadcast'] = {
        'requested': bool(broadcast),
        'attempted': False,
        'allowed': False,
        'rpc_tx_hash': '',
        'error': '',
    }
    artifact_payload = {
        'proposal_id': result['proposal_id'],
        'org_id': result['org_id'],
        'unsigned_transaction': result['unsigned_transaction'],
        'token': result['token'],
        'sender_wallet_id': result['sender_wallet_id'],
        'recipient_wallet_id': result['recipient_wallet_id'],
    }
    raw_artifact = json.dumps(
        artifact_payload,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    result['dry_run_artifact'] = {
        'artifact_digest': hashlib.sha256(raw_artifact).hexdigest(),
        'payload': artifact_payload,
    }

    if not signer_status.get('available'):
        _append_structured_blocker(
            result['signing_blockers'],
            'signer_backend_missing',
            signer_status.get('error') or 'eth_account backend is not available',
        )
    private_key = str(os.environ.get(private_key_env, '') or '').strip()
    if not private_key:
        _append_structured_blocker(
            result['signing_blockers'],
            'private_key_env_missing',
            f'Environment variable {private_key_env!r} is required for signing',
        )
    sender_level = result['sender_wallet'].get('verification_level')
    if sender_level is None or int(sender_level) < 3:
        _append_structured_blocker(
            result['signing_blockers'],
            'sender_wallet_not_self_custody_verified',
            (
                f"Sender wallet '{result['sender_wallet_id']}' is Level "
                f"{sender_level if sender_level is not None else 'unknown'}; signing is blocked until custody is verified at Level 3+ or multisig-controlled."
            ),
        )
    if result['token']['chain_id'] == _BASE_MAINNET_CHAIN_ID and not allow_mainnet_signing:
        _append_structured_blocker(
            result['signing_blockers'],
            'mainnet_signing_disabled',
            'Base mainnet signing is disabled by default in this slice. Set allow_mainnet_signing explicitly if an operator wants to assume that risk.',
        )

    if not result['signing_blockers']:
        Account = _load_eth_account_backend()
        signer = Account.from_key(private_key)
        derived_address = signer.address.lower()
        sender_address = result['sender_wallet']['address'].lower()
        if derived_address != sender_address:
            _append_structured_blocker(
                result['signing_blockers'],
                'signing_key_does_not_match_sender_wallet',
                (
                    f'Signing key resolves to {derived_address}, but sender wallet '
                    f'is {sender_address}.'
                ),
            )
        else:
            tx_to_sign = {
                'nonce': int(result['rpc_observations']['nonce']),
                'gasPrice': int(result['rpc_observations']['gas_price_wei']),
                'gas': int(result['rpc_observations']['gas_limit']),
                'to': _checksum_signing_address(result['unsigned_transaction']['to']),
                'value': 0,
                'data': result['unsigned_transaction']['data'],
                'chainId': int(result['token']['chain_id']),
            }
            signed = Account.sign_transaction(tx_to_sign, private_key)
            result['signing_performed'] = True
            result['signed_transaction'] = {
                'tx_for_signing': tx_to_sign,
                'raw_transaction_hex': '0x' + signed.raw_transaction.hex(),
                'signed_tx_hash': '0x' + signed.hash.hex(),
                'sender_address': derived_address,
            }

    if broadcast:
        if not result['signing_performed']:
            _append_structured_blocker(
                result['broadcast'].setdefault('blockers', []),
                'cannot_broadcast_without_signed_transaction',
                'Broadcast requested but no signed transaction is available.',
            )
        elif result['token']['chain_id'] == _BASE_MAINNET_CHAIN_ID and not allow_mainnet_broadcast:
            _append_structured_blocker(
                result['broadcast'].setdefault('blockers', []),
                'mainnet_broadcast_disabled',
                'Base mainnet broadcast is disabled by default in this slice. No real Base transaction will be submitted without explicit override.',
            )
        else:
            result['broadcast']['allowed'] = True
            try:
                rpc_tx_hash = _json_rpc_request(
                    rpc_url,
                    'eth_sendRawTransaction',
                    [result['signed_transaction']['raw_transaction_hex']],
                    timeout_seconds=timeout_seconds,
                )
                result['broadcast']['attempted'] = True
                result['broadcast']['rpc_tx_hash'] = str(rpc_tx_hash or '')
            except Exception as exc:
                result['broadcast']['attempted'] = True
                result['broadcast']['error'] = str(exc)

    if result['token']['chain_id'] == _BASE_MAINNET_CHAIN_ID:
        result['truth_boundary'] = (
            'No Base mainnet transfer or tx hash was executed in this slice. Mainnet signing and broadcast remain explicitly config-gated.'
        )
    elif result['broadcast']['attempted']:
        result['truth_boundary'] = (
            'Broadcast was attempted only against a non-mainnet or local RPC endpoint. No Base mainnet settlement is implied.'
        )
    else:
        result['truth_boundary'] = (
            'Produced a deterministic dry-run artifact and, when allowed, a signed raw transaction for a non-mainnet path. No Base mainnet transfer was executed.'
        )
    return result


def prepare_x402_unsigned_transfer_from_wallet(actor_id, *, org_id=None,
                                               rpc_url='', token_contract_address='',
                                               recipient_address='', amount_usdc=None,
                                               sender_wallet_id='', source_account_id='',
                                               nonce=None, gas_limit=None,
                                               gas_price_wei=None, chain_id=None,
                                               token_decimals=6,
                                               host_supported_adapters=None,
                                               timeout_seconds=10):
    actor_id = str(actor_id or '').strip()
    if not actor_id:
        raise ValueError('actor_id is required')
    if not str(sender_wallet_id or '').strip() and not str(source_account_id or '').strip():
        raise ValueError('sender_wallet_id or source_account_id is required')
    token_contract = _normalize_chain_wallet_address(
        token_contract_address,
        field_name='token_contract_address',
    )
    recipient_address = _normalize_chain_wallet_address(
        recipient_address,
        field_name='recipient_address',
    )
    nominal_amount = Decimal(str(amount_usdc or 0))
    if nominal_amount <= 0:
        raise ValueError('amount_usdc must be greater than 0')

    adapter = _require_known_settlement_adapter('base_usdc_x402', org_id=org_id)
    contract = _settlement_adapter_contract(
        adapter,
        host_supported_adapters=host_supported_adapters,
    )
    account, resolved_sender_wallet_id, sender_wallet = _resolve_x402_sender_wallet(
        org_id=org_id,
        sender_wallet_id=sender_wallet_id,
        source_account_id=source_account_id or 'company_treasury',
    )
    _wallet_chain_asset_guard(
        sender_wallet,
        resolved_sender_wallet_id,
        expected_chain='base',
        expected_asset='USDC',
        role_label='Sender',
    )
    sender_address = _normalize_chain_wallet_address(
        sender_wallet.get('address'),
        field_name=f'sender wallet {resolved_sender_wallet_id} address',
    )
    blockers = []
    if not contract.get('payout_execution_enabled'):
        _append_structured_blocker(
            blockers,
            'adapter_execution_disabled',
            "Settlement adapter 'base_usdc_x402' is not enabled for payout execution",
        )
    if contract.get('host_supported') is False:
        _append_structured_blocker(
            blockers,
            'host_not_supported',
            "Settlement adapter 'base_usdc_x402' is not supported on this host",
        )
    if not contract.get('verification_ready'):
        _append_structured_blocker(
            blockers,
            'verification_not_ready',
            "Settlement adapter 'base_usdc_x402' verification path is not ready on this host",
        )
    sender_level = sender_wallet.get('verification_level')
    if sender_level is None or int(sender_level) < 3:
        _append_structured_blocker(
            blockers,
            'sender_wallet_not_self_custody_verified',
            (
                f"Sender wallet '{resolved_sender_wallet_id}' is Level "
                f"{sender_level if sender_level is not None else 'unknown'} "
                f"({sender_wallet.get('verification_label') or 'unknown'}); "
                'actual broadcast requires Level 3+ custody verification or a multisig-controlled source wallet.'
            ),
        )

    rpc_calls = []

    def _rpc(method, params=None):
        result = _json_rpc_request(
            rpc_url,
            method,
            params=params,
            timeout_seconds=timeout_seconds,
        )
        rpc_calls.append({'method': method, 'params': list(params or []), 'result': result})
        return result

    if rpc_url:
        resolved_chain_id = _parse_rpc_quantity(_rpc('eth_chainId', []), field_name='eth_chainId')
        decimals_hex = _rpc(
            'eth_call',
            [
                {
                    'to': token_contract,
                    'data': '0x' + _ERC20_DECIMALS_SELECTOR,
                },
                'latest',
            ],
        )
        resolved_token_decimals = _parse_rpc_quantity(decimals_hex, field_name='erc20 decimals')
    else:
        resolved_chain_id = _parse_int_like(chain_id, field_name='chain_id')
        resolved_token_decimals = _parse_int_like(
            6 if token_decimals in ('', None) else token_decimals,
            field_name='token_decimals',
        )
        _append_structured_blocker(
            blockers,
            'live_chain_state_unverified',
            'No live RPC state was queried; nonce, balances, and broadcast readiness remain operator-supplied and unverified.',
        )

    base_unit_multiplier = Decimal(10) ** resolved_token_decimals
    amount_base_units_decimal = nominal_amount * base_unit_multiplier
    if amount_base_units_decimal != amount_base_units_decimal.to_integral_value():
        raise ValueError(
            'Transfer amount cannot be represented exactly at the token decimal precision'
        )
    amount_base_units = int(amount_base_units_decimal)
    calldata = _encode_erc20_transfer_calldata(recipient_address, amount_base_units)

    if rpc_url:
        resolved_nonce = (
            _parse_rpc_quantity(str(nonce), field_name='nonce')
            if nonce not in ('', None)
            else _parse_rpc_quantity(
                _rpc('eth_getTransactionCount', [sender_address, 'pending']),
                field_name='eth_getTransactionCount',
            )
        )
        resolved_gas_price = (
            _parse_rpc_quantity(str(gas_price_wei), field_name='gas_price_wei')
            if gas_price_wei not in ('', None)
            else _parse_rpc_quantity(_rpc('eth_gasPrice', []), field_name='eth_gasPrice')
        )
        resolved_gas_limit = (
            _parse_rpc_quantity(str(gas_limit), field_name='gas_limit')
            if gas_limit not in ('', None)
            else _parse_rpc_quantity(
                _rpc(
                    'eth_estimateGas',
                    [
                        {
                            'from': sender_address,
                            'to': token_contract,
                            'value': '0x0',
                            'data': calldata,
                        }
                    ],
                ),
                field_name='eth_estimateGas',
            )
        )
        sender_native_balance = _parse_rpc_quantity(
            _rpc('eth_getBalance', [sender_address, 'latest']),
            field_name='eth_getBalance',
        )
        sender_token_balance = _parse_rpc_quantity(
            _rpc(
                'eth_call',
                [
                    {
                        'to': token_contract,
                        'data': _encode_erc20_balance_of_calldata(sender_address),
                    },
                    'latest',
                ],
            ),
            field_name='sender balanceOf',
        )
        recipient_token_balance = _parse_rpc_quantity(
            _rpc(
                'eth_call',
                [
                    {
                        'to': token_contract,
                        'data': _encode_erc20_balance_of_calldata(recipient_address),
                    },
                    'latest',
                ],
            ),
            field_name='recipient balanceOf',
        )
        rpc_transport = 'json_rpc_http'
        rpc_url_redacted = _redact_rpc_url(rpc_url)
    else:
        resolved_nonce = _parse_int_like(nonce, field_name='nonce')
        resolved_gas_limit = _parse_int_like(gas_limit, field_name='gas_limit')
        resolved_gas_price = _parse_int_like(gas_price_wei, field_name='gas_price_wei')
        sender_native_balance = None
        sender_token_balance = None
        recipient_token_balance = None
        rpc_transport = 'offline_operator_supplied'
        rpc_url_redacted = ''

    estimated_fee_wei = resolved_gas_limit * resolved_gas_price
    if sender_native_balance is not None and sender_native_balance < estimated_fee_wei:
        _append_structured_blocker(
            blockers,
            'insufficient_native_balance_for_gas',
            (
                f'Sender native balance {sender_native_balance} wei is below the '
                f'estimated gas requirement {estimated_fee_wei} wei.'
            ),
        )
    if sender_token_balance is not None and sender_token_balance < amount_base_units:
        _append_structured_blocker(
            blockers,
            'insufficient_usdc_balance',
            (
                f'Sender token balance {sender_token_balance} base units is below the '
                f'required amount {amount_base_units}.'
            ),
        )
    _append_structured_blocker(
        blockers,
        'post_broadcast_evidence_required',
        'Any later payout settlement claim still requires tx_hash, settlement proof, and x402_settlement_verifier attestation.',
    )

    return {
        'prepared_at': _now(),
        'prepared_by': actor_id,
        'org_id': org_id or _default_org_id(),
        'settlement_adapter': 'base_usdc_x402',
        'rpc_transport': rpc_transport,
        'rpc_url_redacted': rpc_url_redacted,
        'source_account_id': str(account.get('id') or source_account_id or '').strip(),
        'source_account': {
            'id': str(account.get('id') or source_account_id or '').strip(),
            'label': account.get('label', ''),
            'wallet_id': account.get('wallet_id'),
            'status': account.get('status', ''),
            'purpose': account.get('purpose', ''),
        },
        'sender_wallet_id': resolved_sender_wallet_id,
        'sender_wallet': {
            'id': resolved_sender_wallet_id,
            'address': sender_address,
            'chain': sender_wallet.get('chain'),
            'asset': sender_wallet.get('asset'),
            'verification_level': sender_wallet.get('verification_level'),
            'verification_label': sender_wallet.get('verification_label'),
            'status': sender_wallet.get('status'),
        },
        'recipient_wallet_id': '',
        'recipient_wallet': {
            'id': '',
            'address': recipient_address,
            'chain': 'base',
            'asset': 'USDC',
            'verification_level': None,
            'verification_label': '',
            'status': 'external_unverified',
        },
        'adapter_contract': contract,
        'adapter_contract_snapshot': contract.get('contract_snapshot', {}),
        'adapter_contract_digest': contract.get('contract_digest', ''),
        'token': {
            'symbol': 'USDC',
            'chain': 'base',
            'chain_id': resolved_chain_id,
            'network_classification': _x402_network_classification(resolved_chain_id),
            'contract_address': token_contract,
            'decimals': resolved_token_decimals,
        },
        'amount': {
            'nominal_token_amount': str(nominal_amount.normalize()),
            'token_decimals': resolved_token_decimals,
            'base_units': str(amount_base_units),
            'accounting_assumption': 'Kernel treats this hot-wallet x402 demo as an explicit USDC token amount supplied by the operator.',
        },
        'transfer_request': {
            'recipient_address': recipient_address,
            'amount_usdc': str(nominal_amount.normalize()),
        },
        'rpc_observations': {
            'chain_id': resolved_chain_id,
            'nonce': resolved_nonce,
            'gas_price_wei': str(resolved_gas_price),
            'gas_limit': resolved_gas_limit,
            'estimated_fee_wei': str(estimated_fee_wei),
            'sender_native_balance_wei': None if sender_native_balance is None else str(sender_native_balance),
            'sender_token_balance_base_units': None if sender_token_balance is None else str(sender_token_balance),
            'recipient_token_balance_base_units': None if recipient_token_balance is None else str(recipient_token_balance),
            'calls': rpc_calls,
            'live_state_verified': bool(rpc_url),
        },
        'unsigned_transaction_prepared': True,
        'unsigned_transaction': {
            'chainId': resolved_chain_id,
            'from': sender_address,
            'to': token_contract,
            'nonce': _format_rpc_quantity(resolved_nonce, field_name='nonce'),
            'gas': _format_rpc_quantity(resolved_gas_limit, field_name='gas'),
            'gasPrice': _format_rpc_quantity(resolved_gas_price, field_name='gasPrice'),
            'value': '0x0',
            'data': calldata,
        },
        'actual_transfer_blockers': blockers,
        'operator_actions_remaining': [
            'Review the unsigned transaction fields against the intended recipient and token contract.',
            'Confirm the segregated sender wallet remains the intended execution source.',
            'Sign with the matching hot-wallet or other self-custody sender key.',
            'Broadcast with eth_sendRawTransaction only on the intended network.',
            'Capture tx hash and verifier evidence before attaching this transfer to any settlement claim.',
        ],
    }


def sign_x402_transfer_from_wallet(actor_id, *, org_id=None,
                                   rpc_url='', token_contract_address='',
                                   recipient_address='', amount_usdc=None,
                                   private_key_env='MERIDIAN_X402_DEV_PRIVATE_KEY',
                                   private_key='', sender_wallet_id='',
                                   source_account_id='', nonce=None,
                                   gas_limit=None, gas_price_wei=None,
                                   chain_id=None, token_decimals=6,
                                   host_supported_adapters=None,
                                   timeout_seconds=10,
                                   allow_mainnet_signing=False,
                                   broadcast=False,
                                   allow_mainnet_broadcast=False):
    result = prepare_x402_unsigned_transfer_from_wallet(
        actor_id,
        org_id=org_id,
        rpc_url=rpc_url,
        token_contract_address=token_contract_address,
        recipient_address=recipient_address,
        amount_usdc=amount_usdc,
        sender_wallet_id=sender_wallet_id,
        source_account_id=source_account_id,
        nonce=nonce,
        gas_limit=gas_limit,
        gas_price_wei=gas_price_wei,
        chain_id=chain_id,
        token_decimals=token_decimals,
        host_supported_adapters=host_supported_adapters,
        timeout_seconds=timeout_seconds,
    )
    signer_status = _signer_backend_status()
    result['signer_backend'] = signer_status
    result['signing_private_key_env'] = private_key_env
    result['signing_private_key_source'] = 'direct_argument' if str(private_key or '').strip() else 'environment'
    result['signing_performed'] = False
    result['signing_blockers'] = []
    result['signed_transaction'] = None
    result['broadcast'] = {
        'requested': bool(broadcast),
        'attempted': False,
        'allowed': False,
        'rpc_tx_hash': '',
        'error': '',
        'blockers': [],
    }
    artifact_payload = {
        'org_id': result['org_id'],
        'source_account_id': result['source_account_id'],
        'unsigned_transaction': result['unsigned_transaction'],
        'token': result['token'],
        'sender_wallet_id': result['sender_wallet_id'],
        'transfer_request': result['transfer_request'],
    }
    raw_artifact = json.dumps(
        artifact_payload,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    result['dry_run_artifact'] = {
        'artifact_digest': hashlib.sha256(raw_artifact).hexdigest(),
        'payload': artifact_payload,
    }

    if not signer_status.get('available'):
        _append_structured_blocker(
            result['signing_blockers'],
            'signer_backend_missing',
            signer_status.get('error') or 'eth_account backend is not available',
        )
    resolved_private_key = str(private_key or '').strip()
    if not resolved_private_key:
        resolved_private_key = str(os.environ.get(private_key_env, '') or '').strip()
    if not resolved_private_key:
        _append_structured_blocker(
            result['signing_blockers'],
            'private_key_missing',
            f'A private key argument or environment variable {private_key_env!r} is required for signing',
        )
    sender_level = result['sender_wallet'].get('verification_level')
    if sender_level is None or int(sender_level) < 3:
        _append_structured_blocker(
            result['signing_blockers'],
            'sender_wallet_not_self_custody_verified',
            (
                f"Sender wallet '{result['sender_wallet_id']}' is Level "
                f"{sender_level if sender_level is not None else 'unknown'}; signing is blocked until custody is verified at Level 3+ or multisig-controlled."
            ),
        )
    if result['token']['chain_id'] == _BASE_MAINNET_CHAIN_ID and not allow_mainnet_signing:
        _append_structured_blocker(
            result['signing_blockers'],
            'mainnet_signing_disabled',
            'Base mainnet signing is disabled by default in this slice. Set allow_mainnet_signing explicitly if an operator wants to assume that risk.',
        )

    if not result['signing_blockers']:
        Account = _load_eth_account_backend()
        signer = Account.from_key(resolved_private_key)
        derived_address = signer.address.lower()
        sender_address = result['sender_wallet']['address'].lower()
        if derived_address != sender_address:
            _append_structured_blocker(
                result['signing_blockers'],
                'signing_key_does_not_match_sender_wallet',
                (
                    f'Signing key resolves to {derived_address}, but sender wallet '
                    f'is {sender_address}.'
                ),
            )
        else:
            tx_to_sign = {
                'nonce': int(result['rpc_observations']['nonce']),
                'gasPrice': int(result['rpc_observations']['gas_price_wei']),
                'gas': int(result['rpc_observations']['gas_limit']),
                'to': _checksum_signing_address(result['unsigned_transaction']['to']),
                'value': 0,
                'data': result['unsigned_transaction']['data'],
                'chainId': int(result['token']['chain_id']),
            }
            signed = Account.sign_transaction(tx_to_sign, resolved_private_key)
            result['signing_performed'] = True
            result['signed_transaction'] = {
                'tx_for_signing': tx_to_sign,
                'raw_transaction_hex': '0x' + signed.raw_transaction.hex(),
                'signed_tx_hash': '0x' + signed.hash.hex(),
                'sender_address': derived_address,
            }

    if broadcast:
        if not result['signing_performed']:
            _append_structured_blocker(
                result['broadcast']['blockers'],
                'cannot_broadcast_without_signed_transaction',
                'Broadcast requested but no signed transaction is available.',
            )
        elif not str(rpc_url or '').strip():
            _append_structured_blocker(
                result['broadcast']['blockers'],
                'rpc_url_required_for_broadcast',
                'Broadcast requested but no rpc_url was provided.',
            )
        elif result['token']['chain_id'] == _BASE_MAINNET_CHAIN_ID and not allow_mainnet_broadcast:
            _append_structured_blocker(
                result['broadcast']['blockers'],
                'mainnet_broadcast_disabled',
                'Base mainnet broadcast is disabled by default in this slice. No real Base transaction will be submitted without explicit override.',
            )
        else:
            result['broadcast']['allowed'] = True
            try:
                rpc_tx_hash = _json_rpc_request(
                    rpc_url,
                    'eth_sendRawTransaction',
                    [result['signed_transaction']['raw_transaction_hex']],
                    timeout_seconds=timeout_seconds,
                )
                result['broadcast']['attempted'] = True
                result['broadcast']['rpc_tx_hash'] = str(rpc_tx_hash or '')
            except Exception as exc:
                result['broadcast']['attempted'] = True
                result['broadcast']['error'] = str(exc)

    if result['token']['chain_id'] == _BASE_MAINNET_CHAIN_ID:
        result['truth_boundary'] = (
            'No Base mainnet transfer or tx hash was executed in this slice. Mainnet signing and broadcast remain explicitly config-gated.'
        )
    elif result['broadcast']['attempted']:
        result['truth_boundary'] = (
            'Broadcast was attempted only against Base Sepolia or another non-mainnet/local RPC endpoint. No Base mainnet settlement is implied.'
        )
    else:
        result['truth_boundary'] = (
            'Produced a deterministic dry-run artifact and, when allowed, a signed raw transaction for a non-mainnet or operator-supplied path. No Base mainnet transfer was executed.'
        )
    return result


def acknowledge_payout_plan_preview(preview_id, by, *, org_id=None, note=''):
    return _acknowledge_payout_plan_preview(org_id, preview_id, by=by, note=note)


def inspect_payout_plan_preview_queue(org_id=None, *, state=None, limit=50):
    return _inspect_payout_plan_preview_queue(org_id, state=state, limit=limit)


def promote_payout_plan_preview_to_approval_candidate(preview_id, promoted_by, *, org_id=None, promotion_note=''):
    return _promote_payout_plan_preview_to_approval_candidate(
        org_id,
        preview_id,
        promoted_by=promoted_by,
        promotion_note=promotion_note,
    )


def load_payout_plan_approval_candidate_queue(org_id=None):
    return _load_payout_plan_approval_candidate_queue(org_id)


def get_payout_plan_approval_candidate(candidate_id, org_id=None):
    return _get_payout_plan_approval_candidate(candidate_id, org_id)


def list_payout_plan_approval_candidates(org_id=None, *, state=None):
    return _list_payout_plan_approval_candidates(org_id, state=state)


def inspect_payout_plan_approval_candidate_queue(org_id=None, *, state=None, limit=50):
    return _inspect_payout_plan_approval_candidate_queue(org_id, state=state, limit=limit)


def load_payout_execution_queue(org_id=None):
    return _load_payout_execution_queue(org_id)


def payout_execution_queue_summary(org_id=None):
    return _payout_execution_queue_summary(org_id)


def payout_execution_queue_snapshot(org_id=None, *, state=None, limit=50):
    return _payout_execution_queue_snapshot(org_id, state=state, limit=limit)


def treasury_snapshot(org_id=None, *, host_supported_adapters=None):
    """Combined view: balance, revenue, spend, runway, reserve status."""
    ledger = load_ledger(org_id)
    t = ledger['treasury']
    rev_summary = get_revenue_summary(org_id)

    scoped_org_id = org_id or _default_org_id()
    spend_usd = 0.0
    if scoped_org_id:
        try:
            spend_usd = get_spend_summary(scoped_org_id, 30)['total_spend_usd']
        except Exception:
            pass

    balance = t['cash_usd']
    floor = t.get('reserve_floor_usd', 50.0)
    runway = balance - floor
    shortfall = max(0.0, floor - balance)
    remediation = {
        'blocked': runway < 0,
        'shortfall_usd': shortfall,
        'recommended_owner_capital_usd': shortfall,
        'recommended_reserve_floor_usd': max(0.0, balance),
        'next_steps': [],
    }
    if shortfall > 0:
        remediation['next_steps'].append(
            f"Record at least ${shortfall:.2f} of real owner capital or customer cash before running budget-gated phases."
        )
        remediation['next_steps'].append(
            f"If policy truly changed, explicitly lower reserve floor from ${floor:.2f} with an auditable note."
        )

    # Protocol summary
    protocol = {
        'wallet_count': len(load_wallets(org_id).get('wallets', {})),
        'payout_eligible_wallets': len(get_payout_eligible_wallets(org_id)),
        'maintainer_count': len(load_maintainers(org_id).get('maintainers', {})),
        'contributor_count': len(load_contributors(org_id).get('contributors', {})),
        'pending_proposals': len([p for p in load_payout_proposals(org_id).get('proposals', {}).values()
                                  if p.get('status') in ('submitted', 'under_review')]),
        'settlement_adapter_count': len(list_settlement_adapters(org_id)),
        'payout_enabled_settlement_adapters': len(
            list_settlement_adapters(org_id, payout_enabled_only=True)
        ),
        'funding_sources': len(load_funding_sources(org_id).get('sources', {})),
    }

    host_supported = [item for item in (host_supported_adapters or []) if item]

    return {
        'balance_usd': balance,
        'reserve_floor_usd': floor,
        'runway_usd': runway,
        'shortfall_usd': shortfall,
        'above_reserve': runway >= 0,
        'total_revenue_usd': t.get('total_revenue_usd', 0.0),
        'owner_capital_usd': t.get('owner_capital_contributed_usd', 0.0),
        'owner_draws_usd': t.get('owner_draws_usd', 0.0),
        'receivables_usd': rev_summary['receivables_usd'],
        'spend_30d_usd': spend_usd,
        'clients': rev_summary['clients'],
        'paid_orders': rev_summary['paid_orders'],
        'protocol': protocol,
        'settlement_adapter_summary': settlement_adapter_summary(
            org_id,
            host_supported_adapters=host_supported,
        ),
        'settlement_adapters': list_settlement_adapters(org_id),
        'plan_preview_queue_summary': payout_plan_preview_queue_summary(org_id),
        'plan_approval_candidate_queue_summary': payout_plan_approval_candidate_queue_summary(org_id),
        'execution_queue_summary': payout_execution_queue_summary(org_id),
        'runtime_budget': budget_reservation_summary(org_id),
        'remediation': remediation,
        'snapshot_at': _now(),
    }


# -- CLI ----------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description='Treasury primitive -- governance facade')
    sub = p.add_subparsers(dest='command')

    bal = sub.add_parser('balance')
    bal.add_argument('--org_id', default=None)
    run = sub.add_parser('runway')
    run.add_argument('--org_id', default=None)

    sp = sub.add_parser('spend')
    sp.add_argument('--org_id', default=None)
    sp.add_argument('--days', type=int, default=30)

    sn = sub.add_parser('snapshot')
    sn.add_argument('--org_id', default=None)

    cb = sub.add_parser('check-budget')
    cb.add_argument('--org_id', default=None)
    cb.add_argument('--agent_id', required=True)
    cb.add_argument('--cost', type=float, required=True)

    cc = sub.add_parser('contribute')
    cc.add_argument('--org_id', default=None)
    cc.add_argument('--amount', type=float, required=True)
    cc.add_argument('--note', default='owner top-up')
    cc.add_argument('--by', default='owner')

    rf = sub.add_parser('set-reserve-floor')
    rf.add_argument('--org_id', default=None)
    rf.add_argument('--amount', type=float, required=True)
    rf.add_argument('--note', default='reserve policy update')
    rf.add_argument('--by', default='owner')

    for name in ('wallets', 'accounts', 'maintainers', 'contributors', 'proposals', 'funding-sources'):
        parser = sub.add_parser(name)
        parser.add_argument('--org_id', default=None)

    cpw = sub.add_parser('check-payout-wallet')
    cpw.add_argument('--org_id', default=None)
    cpw.add_argument('--wallet_id', required=True)

    sxt = sub.add_parser('sign-x402-transfer')
    sxt.add_argument('--org_id', default=None)
    sxt.add_argument('--proposal_id', required=True)
    sxt.add_argument('--actor_id', required=True)
    sxt.add_argument('--rpc_url', required=True)
    sxt.add_argument('--token_contract_address', required=True)
    sxt.add_argument('--private_key_env', default='MERIDIAN_X402_DEV_PRIVATE_KEY')
    sxt.add_argument('--sender_wallet_id', default='')
    sxt.add_argument('--source_account_id', default='company_treasury')
    sxt.add_argument('--nonce', default='')
    sxt.add_argument('--gas_limit', default='')
    sxt.add_argument('--gas_price_wei', default='')
    sxt.add_argument('--timeout_seconds', type=int, default=10)
    sxt.add_argument('--host_supported_adapter', action='append', default=[])
    sxt.add_argument('--allow_mainnet_signing', action='store_true')
    sxt.add_argument('--broadcast', action='store_true')
    sxt.add_argument('--allow_mainnet_broadcast', action='store_true')

    args = p.parse_args()

    if args.command == 'balance':
        print(f'Treasury balance: ${get_balance(args.org_id):.2f}')
    elif args.command == 'runway':
        runway = get_runway(args.org_id)
        floor = get_reserve_floor(args.org_id)
        status = 'ABOVE reserve' if runway >= 0 else 'BELOW reserve'
        print(f'Runway: ${runway:.2f} ({status}, floor=${floor:.2f})')
    elif args.command == 'spend':
        org_id = args.org_id
        if not org_id:
            org_id = _default_org_id()
        if org_id:
            s = get_spend_summary(org_id, args.days)
            print(f'Spend ({s["period_days"]}d): ${s["total_spend_usd"]:.4f}')
        else:
            print('No org found for spend query')
    elif args.command == 'snapshot':
        snap = treasury_snapshot(args.org_id)
        print(f"\n=== Treasury Snapshot ({snap['snapshot_at']}) ===")
        print(f"Balance:         ${snap['balance_usd']:.2f}")
        print(f"Reserve floor:   ${snap['reserve_floor_usd']:.2f}")
        print(f"Runway:          ${snap['runway_usd']:.2f} {'(OK)' if snap['above_reserve'] else '(BELOW RESERVE)'}")
        print(f"Revenue:         ${snap['total_revenue_usd']:.2f}")
        print(f"Owner capital:   ${snap['owner_capital_usd']:.2f}")
        print(f"Owner draws:     ${snap['owner_draws_usd']:.2f}")
        print(f"Receivables:     ${snap['receivables_usd']:.2f}")
        print(f"Spend (30d):     ${snap['spend_30d_usd']:.4f}")
        print(f"Clients:         {snap['clients']}")
        print(f"Paid orders:     {snap['paid_orders']}")
        proto = snap.get('protocol', {})
        if proto:
            print(f"\n--- Protocol ---")
            print(f"Wallets:         {proto.get('wallet_count', 0)} ({proto.get('payout_eligible_wallets', 0)} payout-eligible)")
            print(f"Maintainers:     {proto.get('maintainer_count', 0)}")
            print(f"Contributors:    {proto.get('contributor_count', 0)}")
            print(f"Pending proposals: {proto.get('pending_proposals', 0)}")
            print(f"Funding sources: {proto.get('funding_sources', 0)}")
    elif args.command == 'check-budget':
        allowed, reason = check_budget(args.agent_id, args.cost, org_id=args.org_id)
        status = 'ALLOWED' if allowed else 'BLOCKED'
        print(f'{status}: {reason}')
        sys.exit(0 if allowed else 1)
    elif args.command == 'contribute':
        result = contribute_owner_capital(args.amount, args.note, args.by, org_id=args.org_id)
        print(f"Capital contribution recorded: +${result['amount_usd']:.2f} | cash now ${result['cash_after_usd']:.2f}")
    elif args.command == 'set-reserve-floor':
        result = set_reserve_floor_policy(args.amount, args.note, args.by, org_id=args.org_id)
        print(f"Reserve floor updated: ${result['old_reserve_floor_usd']:.2f} -> ${result['new_reserve_floor_usd']:.2f}")
    elif args.command == 'wallets':
        data = load_wallets(args.org_id)
        wallets = data.get('wallets', {})
        if not wallets:
            print('No wallets registered.')
        else:
            print(f'\n=== Wallet Registry ({len(wallets)} entries) ===')
            for wid, w in wallets.items():
                level = w.get('verification_level')
                level_str = f"L{level}" if level is not None else "L?"
                label = w.get('verification_label', '?')
                addr = w.get('address') or '(not deployed)'
                eligible = 'ELIGIBLE' if w.get('payout_eligible') else 'NOT ELIGIBLE'
                print(f"  {wid}: {addr} | {level_str} ({label}) | {eligible} | {w.get('status')}")
    elif args.command == 'accounts':
        data = load_treasury_accounts(args.org_id)
        accounts = data.get('accounts', {})
        if not accounts:
            print('No treasury accounts defined.')
        else:
            print(f'\n=== Treasury Accounts ({len(accounts)}) ===')
            for aid, a in accounts.items():
                print(f"  {aid}: ${a.get('balance_usd', 0):.2f} (reserve ${a.get('reserve_floor_usd', 0):.2f}) | {a.get('status')}")
    elif args.command == 'maintainers':
        data = load_maintainers(args.org_id)
        maintainers = data.get('maintainers', {})
        if not maintainers:
            print('No maintainers registered.')
        else:
            print(f'\n=== Maintainers ({len(maintainers)}) ===')
            for mid, m in maintainers.items():
                wallet = m.get('payout_wallet_id') or 'none'
                print(f"  {m.get('name')} ({m.get('github')}) | role={m.get('role')} | wallet={wallet} | {m.get('status')}")
    elif args.command == 'contributors':
        data = load_contributors(args.org_id)
        contributors = data.get('contributors', {})
        if not contributors:
            print('No contributors registered.')
        else:
            print(f'\n=== Contributors ({len(contributors)}) ===')
            for cid, c in contributors.items():
                print(f"  {c.get('name', cid)} ({c.get('github', '?')}) | {c.get('status', '?')}")
    elif args.command == 'proposals':
        data = load_payout_proposals(args.org_id)
        proposals = data.get('proposals', {})
        if not proposals:
            print('No payout proposals.')
        else:
            print(f'\n=== Payout Proposals ({len(proposals)}) ===')
            for pid, p_ in proposals.items():
                print(f"  {pid}: ${p_.get('amount_usd', 0):.2f} | {p_.get('status')} | {p_.get('contributor_id')}")
    elif args.command == 'funding-sources':
        data = load_funding_sources(args.org_id)
        sources = data.get('sources', {})
        if not sources:
            print('No funding sources recorded.')
        else:
            print(f'\n=== Funding Sources ({len(sources)}) ===')
            for sid, s in sources.items():
                print(f"  {sid}: ${s.get('amount_usd', 0):.2f} {s.get('currency', '')} | {s.get('type')} | {s.get('recorded_at')}")
    elif args.command == 'check-payout-wallet':
        eligible, reason = can_receive_payout(args.wallet_id, org_id=args.org_id)
        status = 'ELIGIBLE' if eligible else 'BLOCKED'
        print(f'{status}: {reason}')
        sys.exit(0 if eligible else 1)
    elif args.command == 'sign-x402-transfer':
        result = sign_x402_transfer_for_payout(
            args.proposal_id,
            args.actor_id,
            org_id=args.org_id,
            rpc_url=args.rpc_url,
            token_contract_address=args.token_contract_address,
            private_key_env=args.private_key_env,
            sender_wallet_id=args.sender_wallet_id,
            source_account_id=args.source_account_id,
            nonce=args.nonce or None,
            gas_limit=args.gas_limit or None,
            gas_price_wei=args.gas_price_wei or None,
            host_supported_adapters=args.host_supported_adapter or None,
            timeout_seconds=args.timeout_seconds,
            allow_mainnet_signing=args.allow_mainnet_signing,
            broadcast=args.broadcast,
            allow_mainnet_broadcast=args.allow_mainnet_broadcast,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        p.print_help()


if __name__ == '__main__':
    main()
