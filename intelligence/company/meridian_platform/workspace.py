#!/usr/bin/env python3
"""
Governed Workspace — Owner-facing surface for the Constitutional OS.

Serves an HTML dashboard + JSON API for all six primitives:
  Institution, Agent, Authority, Treasury, Court, Commitment.

Endpoints:
  GET  /                          → Dashboard HTML
  GET  /api/status                → Full system snapshot (JSON)
  GET  /api/institution           → Institution state
  GET  /api/agents                → Agent registry
  POST /api/agents/update         → Update agent rollout/status metadata
  POST /api/agents/budget         → Update agent budget guardrails
  POST /api/agents/scopes         → Update agent scopes
  POST /api/agents/risk           → Update agent risk state
  POST /api/agents/lifecycle      → Transition agent lifecycle
  POST /api/agents/incident       → Record an agent incident
  POST /api/agents/sync-economy   → Sync REP/AUTH and sanctions from the economy ledger
  GET  /api/authority             → Authority state (kill switch, approvals, delegations)
  GET  /api/treasury              → Treasury snapshot
  GET  /api/treasury/wallets      → Treasury wallet registry
  GET  /api/treasury/accounts     → Treasury sub-accounts
  GET  /api/treasury/maintainers  → Treasury maintainer registry
  GET  /api/treasury/contributors → Treasury contributor registry
  GET  /api/treasury/proposals    → Treasury payout proposal registry
  GET  /api/treasury/funding-sources → Funding source records
  GET  /api/treasury/settlement-adapters → Settlement adapter registry
  GET  /api/treasury/settlement-adapters/readiness → Settlement adapter execution readiness
  GET  /api/treasury/payout-plan-preview-queue → Payout plan preview queue
  GET  /api/treasury/payout-plan-preview-queue/inspect → Payout plan preview queue inspection
  GET  /api/treasury/payout-plan-approval-candidate-queue → Approval-candidate queue
  GET  /api/treasury/payout-plan-approval-candidate-queue/inspect → Approval-candidate queue inspection
  GET  /api/treasury/payout-execution-queue → Payout execution queue
  GET  /api/runtimes              → Runtime registry with contract compliance and binding usage
  GET  /api/runtimes/<id>         → Single runtime registry entry with contract compliance and binding usage
  GET  /api/subscriptions         → Institution-owned subscription service state on the founding-locked host
  GET  /api/subscriptions/delivery-targets → Institution-owned delivery-target calculation on the founding-locked host
  GET  /api/subscriptions/loom-delivery-jobs → Inspect queued Loom delivery jobs on the founding-locked host
  GET  /api/subscriptions/loom-delivery-runs → Inspect persisted Loom delivery runs on the founding-locked host
  GET  /api/accounting            → Institution-owned accounting owner-ledger state on the founding-locked host
  GET  /api/pilot/intake          → Pilot intake queue snapshot on the founding-locked host
  GET  /api/payouts              → Payout proposals and summary
  GET  /api/court                 → Court records
  GET  /api/warrants              → Warrant records and summary
  GET  /api/commitments           → Commitment records and summary
  GET  /api/cases                 → Founding-workspace case records and summary
  GET  /api/admission             → Host admission state
  GET  /api/federation            → Federation gateway state
  GET  /api/federation/peers      → Federation peer registry state
  GET  /api/federation/inbox      → Founding federation inbox state
  GET  /api/federation/handoff-preview-queue → Federation handoff preview queue
  GET  /api/federation/handoff-dispatch-queue → Federation handoff dispatch queue
  GET  /api/federation/execution-jobs → Receiver-side federated execution jobs
  GET  /api/federation/manifest   → Public host federation manifest
  GET  /api/federation/witness/archive → Witness-host archival evidence state
  GET  /api/alerts               → Alert queue, delivery, and dispatch summary
  POST /api/alerts/dispatch      → Acknowledge queued alerts without claiming delivery
  GET  /api/runtime-proof         → Public live Loom runtime proof receipt
  GET  /api/runtime-proof-contract → Public bounded Loom surface-proof contract
  GET  /api/kernel-proof-bundle   → Public kernel reference proof bundle with live host receipts
  POST /api/authority/kill-switch → Engage/disengage kill switch
  POST /api/authority/approve     → Decide an approval
  POST /api/authority/request     → Request approval
  POST /api/authority/delegate    → Create delegation
  POST /api/authority/revoke      → Revoke delegation
  POST /api/court/file            → File a violation
  POST /api/court/resolve         → Resolve a violation
  POST /api/court/appeal          → File an appeal
  POST /api/court/decide-appeal   → Decide an appeal
  POST /api/court/remediate       → Lift lingering sanctions after review
  POST /api/warrants/issue        → Issue a warrant record
  POST /api/warrants/approve      → Approve a warrant for execution
  POST /api/warrants/stay         → Stay a warrant before execution
  POST /api/warrants/revoke       → Revoke a warrant before execution
  POST /api/commitments/propose   → Propose a founding-org commitment
  POST /api/commitments/accept    → Accept a commitment
  POST /api/commitments/reject    → Reject a commitment
  POST /api/commitments/breach    → Mark a commitment breached
  POST /api/commitments/settle    → Settle a commitment
  POST /api/cases/open            → Open a founding-workspace case
  POST /api/cases/stay            → Stay a founding-workspace case
  POST /api/cases/resolve         → Resolve a founding-workspace case
  POST /api/federation/execution-jobs/execute → Structurally reject live receiver-side execution completion
  POST /api/treasury/contribute   → Record owner capital contribution
  POST /api/treasury/reserve-floor → Update reserve floor policy
  POST /api/treasury/settlement-adapters/preflight → Validate settlement-adapter execution requirements
  POST /api/treasury/payout-plan-approval-candidate-queue/promote → Promote a preview into the approval-candidate queue
  POST /api/subscriptions/add     → Create an institution-owned subscription record on the founding-locked host
  POST /api/subscriptions/convert → Convert a trial into a paid subscription
  POST /api/subscriptions/checkout-capture → Customer-initiated preview checkout capture that validates payment evidence
  POST /api/subscriptions/activate-from-preview → Activate a captured subscription from preview truth and queue Loom delivery
  POST /api/subscriptions/loom-delivery-jobs/run → Run or advance queued Loom delivery jobs on the founding-locked host
  POST /api/subscriptions/verify-payment → Bind payment evidence to a subscription
  POST /api/subscriptions/remove  → Cancel active subscriptions for a Telegram user
  POST /api/subscriptions/set-email → Update subscription email metadata
  POST /api/subscriptions/record-delivery → Append a subscription delivery record
  POST /api/telegram/history/import → Import Telegram Desktop export into Leviathann session continuity
  POST /api/pilot/intake         → Persist a public pilot intake request and optionally publish a checkout preview
  POST /api/accounting/expense    → Record an owner-paid expense in the institution-owned ledger
  POST /api/accounting/reimburse  → Reimburse an owner-paid expense from treasury
  POST /api/accounting/draw       → Take an owner draw from treasury above reserve floor
  POST /api/payouts/propose       → Create a payout proposal draft
  POST /api/payouts/submit        → Submit a payout proposal for review
  POST /api/payouts/review        → Move a payout proposal into review
  POST /api/payouts/approve       → Owner-approve a payout proposal
  POST /api/payouts/open-dispute-window → Start the payout dispute window
  POST /api/payouts/reject        → Reject a payout proposal
  POST /api/payouts/cancel        → Cancel a payout proposal
  POST /api/payouts/execute       → Execute an approved payout
  POST /api/admission/admit       → Structurally reject non-founding admission changes
  POST /api/admission/suspend     → Structurally reject admission suspension changes
  POST /api/admission/revoke      → Structurally reject admission revocation changes
  POST /api/federation/peers/upsert → Structurally reject peer registry mutation on live
  POST /api/federation/peers/refresh → Structurally reject peer capability refresh on live
  POST /api/federation/peers/suspend → Structurally reject peer suspension changes on live
  POST /api/federation/peers/revoke → Structurally reject peer revocation changes on live
  POST /api/federation/send       → Attempt a federation delivery and fail closed when disabled
  POST /api/federation/handoff-preview-queue/acknowledge → Acknowledge a remote handoff preview and queue dispatch
  POST /api/federation/handoff-dispatch-queue/run → Run a queued federation handoff dispatch
  POST /api/federation/execution-jobs/execute → Fail closed; receiver-side execution jobs stay review-only
  POST /api/federation/receive    → Validate and consume a federation envelope
  POST /api/federation/witness/archive → Archive independently validated witness evidence
  POST /api/institution/charter   → Set charter
  POST /api/institution/lifecycle → Transition lifecycle

Run:
  python3 workspace.py                    # port 18901
  python3 workspace.py --port 18902
  python3 workspace.py --org-id <org>    # must still be the founding Meridian org on live

When workspace credentials are configured, the dashboard and JSON API are
owner-authenticated with HTTP Basic auth.

Route backbone: see app.py for the public intelligence surface, runtime
boundaries, and mutation-role map.
"""
import argparse
import base64
import concurrent.futures
import copy
import datetime
import hashlib
import hmac
import json
import os
import sys
import threading
import time
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib import error as urllib_error, request as urllib_request
from urllib.parse import urlparse, parse_qs

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(PLATFORM_DIR))
PHASE_MACHINE_FILE = os.path.join(WORKSPACE, 'company', 'phase_machine.py')
WORKSPACE_CREDENTIALS_FILE = os.environ.get(
    'MERIDIAN_WORKSPACE_CREDENTIALS_FILE',
    '/etc/caddy/.workspace_credentials',
)
RUNTIME_HOST_IDENTITY_FILE = os.environ.get(
    'MERIDIAN_RUNTIME_HOST_IDENTITY_FILE',
    os.path.join(PLATFORM_DIR, 'host_identity.json'),
)
RUNTIME_ADMISSION_FILE = os.environ.get(
    'MERIDIAN_RUNTIME_ADMISSION_FILE',
    os.path.join(PLATFORM_DIR, 'institution_admissions.json'),
)
FEDERATION_PEERS_FILE = os.environ.get(
    'MERIDIAN_FEDERATION_PEERS_FILE',
    os.path.join(PLATFORM_DIR, 'federation_peers.json'),
)
FEDERATION_REPLAY_FILE = os.environ.get(
    'MERIDIAN_FEDERATION_REPLAY_FILE',
    os.path.join(PLATFORM_DIR, '.federation_replay'),
)
WITNESS_ARCHIVE_FILE = os.environ.get(
    'MERIDIAN_WITNESS_ARCHIVE_FILE',
    os.path.join(PLATFORM_DIR, 'witness_archive.json'),
)
FEDERATION_SIGNING_SECRET = (
    os.environ.get('MERIDIAN_FEDERATION_SIGNING_SECRET', '').strip() or None
)
WORKSPACE_ORG_ID = (os.environ.get('MERIDIAN_WORKSPACE_ORG_ID') or '').strip() or None
WORKSPACE_AUTH_REQUIRED = os.environ.get('MERIDIAN_WORKSPACE_AUTH_REQUIRED', '').lower() in (
    '1', 'true', 'yes', 'on'
)
KERNEL_ROOT = os.environ.get('MERIDIAN_KERNEL_ROOT', '/opt/meridian-kernel')
KERNEL_MODULE_DIR = os.path.join(KERNEL_ROOT, 'kernel')
KERNEL_RUNTIME_ADAPTER_FILE = os.path.join(KERNEL_ROOT, 'kernel', 'runtime_adapter.py')
KERNEL_PUBLIC_PROOF_BUNDLE_FILE = os.path.join(KERNEL_ROOT, 'examples', 'generate_public_proof_bundle.py')
PUBLIC_BASE_URL = (os.environ.get('MERIDIAN_PUBLIC_BASE_URL') or 'https://app.welliam.codes').strip() or 'https://app.welliam.codes'
PUBLIC_PROOF_CACHE_TTL_SECONDS = max(0, int(os.environ.get('MERIDIAN_PUBLIC_PROOF_CACHE_TTL_SECONDS', '300') or '300'))
PUBLIC_PROOF_BUILD_SYNC_TIMEOUT_SECONDS = max(
    0.5,
    float(os.environ.get('MERIDIAN_PUBLIC_PROOF_BUILD_SYNC_TIMEOUT_SECONDS', '4') or '4'),
)
PUBLIC_PROOF_FALLBACK_MAX_AGE_SECONDS = max(
    PUBLIC_PROOF_CACHE_TTL_SECONDS,
    int(os.environ.get('MERIDIAN_PUBLIC_PROOF_FALLBACK_MAX_AGE_SECONDS', '3600') or '3600'),
)
sys.path.insert(0, PLATFORM_DIR)

from organizations import (load_orgs, set_charter, set_policy_defaults, DEFAULT_POLICY_DEFAULTS,
                           transition_lifecycle as org_transition_lifecycle)
from agent_registry import (
    load_registry,
    normalize_agent_record,
    sync_from_economy,
    get_agent,
    update_agent as update_registry_agent,
    set_budget as set_agent_budget,
    set_scopes as set_agent_scopes,
    set_risk_state as set_agent_risk_state,
    transition_lifecycle as transition_agent_lifecycle,
    record_incident as record_agent_incident,
)
from audit import log_event, query_events
import alerting

import importlib.util

_phase_spec = importlib.util.spec_from_file_location('company_phase_machine', PHASE_MACHINE_FILE)
_phase_mod = importlib.util.module_from_spec(_phase_spec)
_phase_spec.loader.exec_module(_phase_mod)

_runtime_adapter_spec = importlib.util.spec_from_file_location(
    'meridian_kernel_runtime_adapter',
    KERNEL_RUNTIME_ADAPTER_FILE,
)
_runtime_adapter_mod = importlib.util.module_from_spec(_runtime_adapter_spec)
_runtime_adapter_spec.loader.exec_module(_runtime_adapter_mod)
kernel_load_runtimes = _runtime_adapter_mod.load_runtimes
kernel_get_runtime = _runtime_adapter_mod.get_runtime
kernel_check_all_contracts = _runtime_adapter_mod.check_all_contracts
kernel_check_contract = _runtime_adapter_mod.check_contract
_kernel_public_proof_bundle_mod = None
_public_kernel_proof_cache = {}
_public_kernel_proof_cache_lock = threading.RLock()
_public_kernel_proof_build_futures = {}
_public_kernel_proof_last_error = {}
_public_kernel_proof_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix='meridian_public_proof_bundle',
)

if KERNEL_MODULE_DIR not in sys.path:
    sys.path.append(KERNEL_MODULE_DIR)
_kernel_treasury_spec = importlib.util.spec_from_file_location(
    'meridian_kernel_treasury',
    os.path.join(KERNEL_MODULE_DIR, 'treasury.py'),
)
_kernel_treasury_mod = importlib.util.module_from_spec(_kernel_treasury_spec)
_kernel_treasury_spec.loader.exec_module(_kernel_treasury_mod)
kernel_load_maintainers = _kernel_treasury_mod.load_maintainers
kernel_payout_plan_preview_queue_snapshot = _kernel_treasury_mod.payout_plan_preview_queue_snapshot
kernel_inspect_payout_plan_preview_queue = _kernel_treasury_mod.inspect_payout_plan_preview_queue
kernel_payout_plan_approval_candidate_queue_snapshot = _kernel_treasury_mod.payout_plan_approval_candidate_queue_snapshot
kernel_inspect_payout_plan_approval_candidate_queue = _kernel_treasury_mod.inspect_payout_plan_approval_candidate_queue
kernel_payout_execution_queue_snapshot = _kernel_treasury_mod.payout_execution_queue_snapshot
kernel_promote_payout_plan_preview_to_approval_candidate = _kernel_treasury_mod.promote_payout_plan_preview_to_approval_candidate

_kernel_handoff_queue_spec = importlib.util.spec_from_file_location(
    'meridian_kernel_federation_handoff_queue',
    os.path.join(KERNEL_MODULE_DIR, 'federation_handoff_queue.py'),
)
_kernel_handoff_queue_mod = importlib.util.module_from_spec(_kernel_handoff_queue_spec)
_kernel_handoff_queue_spec.loader.exec_module(_kernel_handoff_queue_mod)
kernel_handoff_preview_queue_snapshot = _kernel_handoff_queue_mod.handoff_preview_queue_snapshot
kernel_acknowledge_handoff_preview = _kernel_handoff_queue_mod.acknowledge_handoff_preview

_kernel_handoff_dispatch_spec = importlib.util.spec_from_file_location(
    'meridian_kernel_federation_handoff_dispatch_queue',
    os.path.join(KERNEL_MODULE_DIR, 'federation_handoff_dispatch_queue.py'),
)
_kernel_handoff_dispatch_mod = importlib.util.module_from_spec(_kernel_handoff_dispatch_spec)
_kernel_handoff_dispatch_spec.loader.exec_module(_kernel_handoff_dispatch_mod)
kernel_handoff_dispatch_queue_snapshot = _kernel_handoff_dispatch_mod.handoff_dispatch_queue_snapshot
kernel_get_handoff_dispatch_record = _kernel_handoff_dispatch_mod.get_handoff_dispatch_record
kernel_promote_acknowledged_handoff_preview_to_dispatch_record = _kernel_handoff_dispatch_mod.promote_acknowledged_handoff_preview_to_dispatch_record
kernel_mark_handoff_dispatch_record_dispatched = _kernel_handoff_dispatch_mod.mark_handoff_dispatch_record_dispatched

# Import authority, treasury, court via their public APIs
from authority import (check_authority, request_approval, decide_approval,
                       delegate, revoke_delegation, engage_kill_switch,
                       disengage_kill_switch, get_pending_approvals,
                       get_sprint_lead, is_kill_switch_engaged, _load_queue)
from treasury import (treasury_snapshot, get_balance,
                      contribute_owner_capital, set_reserve_floor_policy,
                      load_wallets, load_treasury_accounts, load_funding_sources,
                      load_contributors,
                      list_payout_proposals, payout_proposal_summary,
                      load_payout_proposals,
                      list_settlement_adapters, settlement_adapter_summary,
                      settlement_adapter_readiness_snapshot,
                      preflight_settlement_adapter,
                      settlement_adapter_contract_snapshot,
                      settlement_adapter_contract_digest,
                      get_payout_proposal,
                      create_payout_proposal, submit_payout_proposal,
                      review_payout_proposal, approve_payout_proposal,
                      open_payout_dispute_window, reject_payout_proposal,
                      cancel_payout_proposal, execute_payout_proposal,
                      load_payout_proposals)
from court import (file_violation, resolve_violation,
                   file_appeal, decide_appeal, auto_review,
                   get_restrictions, remediate, _load_records)
from session import SessionAuthority
from app import (
    PUBLIC_UNAUTHENTICATED_PATHS,
    SUPPORTED_RUNTIME_BOUNDARIES,
    WORKSPACE_MUTATION_ROLE_REQUIREMENTS,
    is_workspace_protected_path,
)
_warrants_spec = importlib.util.spec_from_file_location(
    'meridian_workspace_warrants',
    os.path.join(PLATFORM_DIR, 'warrants.py'),
)
_warrants_mod = importlib.util.module_from_spec(_warrants_spec)
_warrants_spec.loader.exec_module(_warrants_mod)
list_warrants = _warrants_mod.list_warrants
get_warrant = _warrants_mod.get_warrant
issue_warrant = _warrants_mod.issue_warrant
review_warrant = _warrants_mod.review_warrant
validate_warrant_for_execution = _warrants_mod.validate_warrant_for_execution
mark_warrant_executed = _warrants_mod.mark_warrant_executed
warrant_action_for_message = _warrants_mod.warrant_action_for_message
import commitments
import cases
import accounting_service
import loom_runtime_proof
import service_state
import status_surface
import pilot_intake
import subscription_preview_queue
import subscription_service
if not hasattr(subscription_service, 'institution_license_catalog'):
    _subscription_service_spec = importlib.util.spec_from_file_location(
        'meridian_workspace_subscription_service',
        os.path.join(PLATFORM_DIR, 'subscription_service.py'),
    )
    _subscription_service_mod = importlib.util.module_from_spec(_subscription_service_spec)
    _subscription_service_spec.loader.exec_module(_subscription_service_mod)
    subscription_service = _subscription_service_mod
from telegram_history import import_telegram_history
from constitutional_model import constitutional_model
from federation import (
    FederationAuthority,
    ReplayStore,
    load_peer_registry,
    FederationUnavailable,
    FederationDeliveryError,
    FederationValidationError,
    FederationReplayError,
)
from witness_archive import (
    archive_witness_observation,
    list_witness_observations,
    witness_archive_summary,
)
from federation_inbox import (
    load_inbox_entries,
    summarize_inbox_entries,
    upsert_inbox_entry,
)
from federated_execution_jobs import (
    get_execution_job,
    get_execution_job_by_local_warrant,
    list_execution_jobs,
    execution_job_summary,
    sync_execution_job_for_local_warrant,
    upsert_execution_job,
)
from capsule import capsule_dir
from ci_vertical import _phase_gate_snapshot, get_agent_remediation
from institution_context import InstitutionContext, WORKSPACE_BOUNDARY, runtime_core_snapshot
from runtime_host import (
    load_host_identity,
    load_admission_registry,
    ensure_org_admitted,
)

# Process-level session authority (tokens do not survive restarts unless
# MERIDIAN_SESSION_SECRET is set in the environment).
_session_revocation_file = (
    os.environ.get('MERIDIAN_SESSION_REVOCATIONS_FILE', '').strip() or None
)
if not _session_revocation_file and os.environ.get('MERIDIAN_SESSION_SECRET', '').strip():
    _session_revocation_file = os.path.join(PLATFORM_DIR, '.session_revocations')
_session_authority = SessionAuthority(revocation_file=_session_revocation_file)


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


ROLE_RANK = {
    'viewer': 0,
    'member': 1,
    'admin': 2,
    'owner': 3,
}

MUTATION_ROLE_REQUIREMENTS = WORKSPACE_MUTATION_ROLE_REQUIREMENTS


def _load_workspace_credentials():
    env_user = os.environ.get('MERIDIAN_WORKSPACE_USER')
    env_password = os.environ.get('MERIDIAN_WORKSPACE_PASS')
    env_org_id = (os.environ.get('MERIDIAN_WORKSPACE_AUTH_ORG_ID') or '').strip() or None
    env_user_id = (os.environ.get('MERIDIAN_WORKSPACE_USER_ID') or '').strip() or None
    if env_user and env_password:
        return env_user, env_password, env_org_id, env_user_id
    if not os.path.exists(WORKSPACE_CREDENTIALS_FILE):
        return None, None, None, None
    user = None
    password = None
    org_id = None
    user_id = None
    with open(WORKSPACE_CREDENTIALS_FILE) as f:
        for raw_line in f:
            line = raw_line.strip()
            if line.startswith('user:'):
                user = line.split(':', 1)[1].strip()
            elif line.startswith('pass:'):
                password = line.split(':', 1)[1].strip()
            elif line.startswith('org_id:'):
                org_id = line.split(':', 1)[1].strip() or None
            elif line.startswith('user_id:'):
                user_id = line.split(':', 1)[1].strip() or None
    return user, password, org_id, user_id


def _normalized_public_base_url(value):
    return (str(value or '').strip() or PUBLIC_BASE_URL).rstrip('/')


def _request_public_base_url(handler):
    forwarded_proto = (handler.headers.get('X-Forwarded-Proto') or '').strip()
    host = (handler.headers.get('X-Forwarded-Host') or handler.headers.get('Host') or '').strip()
    if forwarded_proto and host:
        return _normalized_public_base_url(f'{forwarded_proto}://{host}')
    return _normalized_public_base_url(PUBLIC_BASE_URL)


def _load_kernel_public_proof_builder():
    global _kernel_public_proof_bundle_mod
    if _kernel_public_proof_bundle_mod is not None:
        return getattr(_kernel_public_proof_bundle_mod, 'build_bundle', None)
    if not os.path.exists(KERNEL_PUBLIC_PROOF_BUNDLE_FILE):
        return None
    spec = importlib.util.spec_from_file_location(
        'meridian_kernel_public_proof_bundle',
        KERNEL_PUBLIC_PROOF_BUNDLE_FILE,
    )
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _kernel_public_proof_bundle_mod = module
    return getattr(module, 'build_bundle', None)


def _kernel_public_proof_bundle(*, base_url=None):
    builder = _load_kernel_public_proof_builder()
    if builder is None:
        raise RuntimeError(
            f'Kernel public proof bundle builder unavailable at {KERNEL_PUBLIC_PROOF_BUNDLE_FILE}'
        )
    normalized_base = _normalized_public_base_url(base_url)
    now = time.time()

    def _decorate_payload(payload, *, cache_state):
        enriched = copy.deepcopy(payload)
        generated_from = dict(enriched.get('generated_from') or {})
        generated_from.update({
            'kernel_root': KERNEL_ROOT,
            'bundle_builder': KERNEL_PUBLIC_PROOF_BUNDLE_FILE,
            'public_base_url': normalized_base,
        })
        enriched['generated_from'] = generated_from
        enriched['public_routes'] = {
            'kernel_proof_bundle': '/api/kernel-proof-bundle',
            'federation_manifest': '/api/federation/manifest',
            'runtime_proof': '/api/runtime-proof',
            'runtime_proof_contract': '/api/runtime-proof-contract',
        }
        enriched['cache'] = cache_state
        return enriched

    def _placeholder_payload(reason, *, cache_state='bootstrap'):
        return _decorate_payload({
            'proof_bundle_version': 4,
            'generated_at': datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
            'reference_scope': 'oss_kernel_reference',
            'status': 'degraded',
            'degraded_reason': reason,
            'live_host_receipt': {
                'included': False,
                'attempted': False,
                'route': f'{normalized_base}/api/federation/manifest',
                'reason': 'live_receipt_refresh_pending',
            },
            'live_runtime_receipt': {
                'included': False,
                'attempted': False,
                'route': f'{normalized_base}/api/runtime-proof',
                'reason': 'live_receipt_refresh_pending',
            },
            'local_loom_runtime_receipt': {
                'included': False,
                'attempted': False,
                'path': '',
                'reason': 'public_bundle_refresh_pending',
            },
            'not_live_proven': [
                'live multi-host federation between independent deployments',
                'live end-to-end hosted runtime wiring',
                'live non-internal settlement execution',
            ],
        }, cache_state={
            'state': cache_state,
            'reason': reason,
            'generated_at_epoch': now,
        })

    def _build_payload():
        raw_payload = builder(
            live_manifest_url=f'{normalized_base}/api/federation/manifest',
            live_runtime_proof_url=f'{normalized_base}/api/runtime-proof',
        )
        cached_payload = _decorate_payload(raw_payload, cache_state={
            'state': 'fresh',
            'generated_at_epoch': now,
            'ttl_seconds': PUBLIC_PROOF_CACHE_TTL_SECONDS,
        })
        with _public_kernel_proof_cache_lock:
            _public_kernel_proof_cache[normalized_base] = {
                'cached_at_epoch': time.time(),
                'payload': copy.deepcopy(cached_payload),
            }
            _public_kernel_proof_last_error.pop(normalized_base, None)
        return cached_payload

    def _future_done(base_key, future):
        with _public_kernel_proof_cache_lock:
            _public_kernel_proof_build_futures.pop(base_key, None)
            if future.cancelled():
                _public_kernel_proof_last_error[base_key] = 'public_bundle_refresh_cancelled'
                return
            exc = future.exception()
            if exc is not None:
                _public_kernel_proof_last_error[base_key] = f'{type(exc).__name__}: {exc}'

    def _ensure_refresh_in_flight():
        with _public_kernel_proof_cache_lock:
            existing = _public_kernel_proof_build_futures.get(normalized_base)
            if existing and not existing.done():
                return existing
            future = _public_kernel_proof_executor.submit(_build_payload)
            _public_kernel_proof_build_futures[normalized_base] = future
            future.add_done_callback(lambda done_future, base_key=normalized_base: _future_done(base_key, done_future))
            return future

    with _public_kernel_proof_cache_lock:
        cache_entry = copy.deepcopy(_public_kernel_proof_cache.get(normalized_base))
        last_error = _public_kernel_proof_last_error.get(normalized_base)

    if cache_entry:
        cache_age = max(0.0, now - float(cache_entry.get('cached_at_epoch', 0.0)))
        payload = dict(cache_entry.get('payload') or {})
        if PUBLIC_PROOF_CACHE_TTL_SECONDS > 0 and cache_age <= PUBLIC_PROOF_CACHE_TTL_SECONDS:
            payload['cache'] = {
                'state': 'fresh',
                'age_seconds': round(cache_age, 3),
                'ttl_seconds': PUBLIC_PROOF_CACHE_TTL_SECONDS,
                'last_error': last_error,
            }
            return payload

        _ensure_refresh_in_flight()
        payload['cache'] = {
            'state': 'stale_fallback',
            'age_seconds': round(cache_age, 3),
            'ttl_seconds': PUBLIC_PROOF_CACHE_TTL_SECONDS,
            'fallback_max_age_seconds': PUBLIC_PROOF_FALLBACK_MAX_AGE_SECONDS,
            'refresh': 'in_progress',
            'last_error': last_error,
        }
        if cache_age <= PUBLIC_PROOF_FALLBACK_MAX_AGE_SECONDS:
            return payload

    refresh_future = _ensure_refresh_in_flight()
    try:
        return refresh_future.result(timeout=PUBLIC_PROOF_BUILD_SYNC_TIMEOUT_SECONDS)
    except concurrent.futures.TimeoutError:
        return _placeholder_payload(
            'public_bundle_build_in_progress',
            cache_state='building',
        )
    except Exception as exc:
        with _public_kernel_proof_cache_lock:
            _public_kernel_proof_last_error[normalized_base] = f'{type(exc).__name__}: {exc}'
        return _placeholder_payload(
            f'public_bundle_build_failed: {type(exc).__name__}',
            cache_state='error_fallback',
        )


def _canonical_meridian_user_id(user_id):
    value = (str(user_id or '')).strip()
    if not value:
        return None
    if value.startswith('user_son_'):
        return f"user_meridian_{value[len('user_son_'):]}"
    return value


def _public_org_record(org):
    if not org:
        return {}
    record = dict(org)
    record['owner_id'] = _canonical_meridian_user_id(record.get('owner_id', ''))
    record['members'] = [
        {
            **dict(member or {}),
            'user_id': _canonical_meridian_user_id((member or {}).get('user_id', '')),
        }
        for member in (record.get('members') or [])
    ]
    return record


def _institution_template_snapshot(org_id, org=None):
    org_record = _public_org_record(org or load_orgs().get('organizations', {}).get(org_id) or {})
    policy_defaults = dict(DEFAULT_POLICY_DEFAULTS)
    policy_defaults.update(dict(org_record.get('policy_defaults') or {}))
    charter_text = str(org_record.get('charter') or '').strip()
    if not charter_text:
        charter_text = (
            "Operate a governed institution where every delegated action requires "
            "warranted authority, budget discipline, and verifiable receipts."
        )
    return {
        'schema_version': 'meridian.institution_template.v1',
        'org_id': org_id,
        'institution_name': org_record.get('name', 'Meridian Institution'),
        'charter_template': charter_text,
        'policy_defaults': policy_defaults,
        'court_rule_set': [
            {
                'rule_id': 'budget_overspend_guard',
                'trigger': 'runtime_budget_denied_or_unapproved_spend',
                'default_sanction': 'probation',
            },
            {
                'rule_id': 'proof_integrity_guard',
                'trigger': 'missing_or_invalid_poge_receipt',
                'default_sanction': 'remediation_only',
            },
            {
                'rule_id': 'authority_breach_guard',
                'trigger': 'executed_action_without_authority',
                'default_sanction': 'zero_authority',
            },
        ],
        'rollback_contract': {
            'strategy': 'capsule_snapshot_restore',
            'requires_owner_approval': True,
            'api_paths': [
                '/api/authority/kill-switch',
                '/api/court/remediate',
                '/api/treasury/reserve-floor',
            ],
        },
        'boundary': {
            'service_scope': 'founding_service_only',
            'note': 'Template is production-ready for the founding host path; multi-institution self-serve remains intentionally bounded.',
        },
    }


def _institution_license_catalog_snapshot(org_id, org=None):
    catalog = subscription_service.institution_license_catalog()
    try:
        offer = subscription_service.institution_license_checkout_offer(catalog.get('default_plan', ''))
    except Exception as exc:
        offer = {
            'requested_offer': catalog.get('default_plan', ''),
            'availability': 'degraded',
            'error': f'{exc.__class__.__name__}: {exc}',
        }
    return {
        'catalog': catalog,
        'default_offer': offer,
        'template': _institution_template_snapshot(org_id, org=org),
    }


def _public_sprint_lead(lead_id, lead_auth, reg=None):
    if not lead_id:
        return {
            'agent_id': '',
            'economy_key': '',
            'agent_name': '',
            'auth': lead_auth,
            'auth_source': 'economy_sprint_lead',
            'registry_authority_units': None,
            'registry_reputation_units': None,
            'authority_alignment': 'no_agent',
        }
    registry = reg or load_registry()
    for agent in (registry.get('agents') or {}).values():
        normalized = normalize_agent_record(agent)
        candidates = {
            (normalized.get('id') or '').strip(),
            (normalized.get('economy_key') or '').strip(),
            (normalized.get('name') or '').strip().lower(),
        }
        candidates.discard('')
        if lead_id in candidates:
            return {
                'agent_id': normalized.get('id') or lead_id,
                'economy_key': normalized.get('economy_key') or lead_id,
                'agent_name': normalized.get('name') or '',
                'auth': lead_auth,
                'auth_source': 'economy_sprint_lead',
                'registry_authority_units': normalized.get('authority_units'),
                'registry_reputation_units': normalized.get('reputation_units'),
                'authority_alignment': (
                    'match'
                    if normalized.get('authority_units') == lead_auth
                    else 'divergent'
                ),
            }
    return {
        'agent_id': lead_id,
        'economy_key': lead_id,
        'agent_name': '',
        'auth': lead_auth,
        'auth_source': 'economy_sprint_lead',
        'registry_authority_units': None,
        'registry_reputation_units': None,
        'authority_alignment': 'unknown_agent',
    }


def _get_founding_org():
    orgs = load_orgs()
    for oid, org in orgs['organizations'].items():
        if org.get('slug') == 'meridian':
            return oid, org
    return None, None


def _resolve_workspace_context(*, allow_inactive=False):
    """Bind this live workspace process to the founding Meridian institution."""
    founding_org_id, founding_org = _get_founding_org()
    configured_org_id = WORKSPACE_ORG_ID
    cred_user, cred_password, credential_org_id, _credential_user_id = _load_workspace_credentials()
    credential_scope_active = bool(cred_user and cred_password and credential_org_id)
    if configured_org_id and configured_org_id != founding_org_id:
        raise RuntimeError(
            f"Live workspace only supports founding org '{founding_org_id}', got '{configured_org_id}'"
        )
    if credential_scope_active and credential_org_id != founding_org_id:
        raise RuntimeError(
            f"Live workspace credentials must scope to founding org '{founding_org_id}', got '{credential_org_id}'"
        )
    context_source = 'configured_org' if configured_org_id else 'founding_default'
    if allow_inactive:
        ctx = InstitutionContext(
            founding_org_id,
            founding_org,
            context_source,
            WORKSPACE_BOUNDARY,
        )
        if not ctx.is_admitted:
            raise RuntimeError('No institution admitted to this context')
    else:
        ctx = InstitutionContext.bind(
            founding_org_id,
            founding_org,
            context_source,
            WORKSPACE_BOUNDARY,
        )
    _runtime_host_state(ctx.org_id)
    return ctx


def _runtime_host_state(bound_org_id):
    host_identity = load_host_identity(
        RUNTIME_HOST_IDENTITY_FILE,
        supported_boundaries=SUPPORTED_RUNTIME_BOUNDARIES,
        fallback_label='Meridian Live Host',
        fallback_federation=False,
    )
    admission_registry = load_admission_registry(
        RUNTIME_ADMISSION_FILE,
        bound_org_id=bound_org_id,
        host_identity=host_identity,
    )
    ensure_org_admitted(bound_org_id, admission_registry)
    return host_identity, admission_registry


def _federation_authority(host_identity, peer_registry=None):
    return FederationAuthority(
        host_identity,
        signing_secret=FEDERATION_SIGNING_SECRET,
        peer_registry=(
            peer_registry
            if peer_registry is not None else
            load_peer_registry(FEDERATION_PEERS_FILE, host_identity=host_identity)
        ),
        replay_store=ReplayStore(FEDERATION_REPLAY_FILE),
    )


def _witness_read_only_management_state():
    return {
        'management_mode': 'witness_read_only',
        'mutation_enabled': False,
        'mutation_disabled_reason': 'witness_host_read_only',
    }


def _federation_management_state(host_identity=None):
    if getattr(host_identity, 'role', '') == 'witness_host':
        return _witness_read_only_management_state()
    return {
        'management_mode': 'founding_locked',
        'mutation_enabled': False,
        'mutation_disabled_reason': 'single_institution_deployment',
    }


def _federation_snapshot(bound_org_id, host_identity=None, admission_registry=None, peer_registry=None):
    if host_identity is None or admission_registry is None:
        host_identity, admission_registry = _runtime_host_state(bound_org_id)
    snapshot = _federation_authority(host_identity, peer_registry=peer_registry).snapshot(
        bound_org_id=bound_org_id,
        admission_registry=admission_registry,
    )
    snapshot.update(_federation_management_state(host_identity))
    try:
        snapshot['inbox_summary'] = summarize_inbox_entries(bound_org_id)
    except Exception as exc:
        snapshot['inbox_summary'] = {
            'org_id': (bound_org_id or '').strip(),
            'total': 0,
            'received': 0,
            'processed': 0,
            'state_counts': {},
            'message_type_counts': {},
            'updatedAt': _now(),
            'unavailable_reason': f'{exc.__class__.__name__}: {exc}',
        }
    try:
        snapshot['execution_job_summary'] = execution_job_summary(bound_org_id)
    except Exception as exc:
        snapshot['execution_job_summary'] = {
            'org_id': (bound_org_id or '').strip(),
            'total': 0,
            'pending_local_warrant': 0,
            'ready': 0,
            'executed': 0,
            'blocked': 0,
            'rejected': 0,
            'state_counts': {},
            'message_type_counts': {},
            'updatedAt': _now(),
            'unavailable_reason': f'{exc.__class__.__name__}: {exc}',
        }
    snapshot['witness_archive'] = _witness_archive_snapshot(
        bound_org_id,
        host_identity=host_identity,
    )
    return snapshot


def _federation_manifest(context, host_identity=None, admission_registry=None):
    if host_identity is None or admission_registry is None:
        host_identity, admission_registry = _runtime_host_state(context.org_id)
    admission_management = _admission_management_state(host_identity)
    runtime_core = runtime_core_snapshot(
        context,
        additional_institutions_allowed=bool(
            admission_management['mutation_enabled']
            or len(admission_registry.get('admitted_org_ids', [])) > 1
        ),
        host_identity=host_identity,
        admission_registry=admission_registry,
        admission_management_mode=admission_management['management_mode'],
        admission_mutation_enabled=admission_management['mutation_enabled'],
        admission_mutation_disabled_reason=admission_management['mutation_disabled_reason'],
    )
    federation = _federation_snapshot(
        context.org_id,
        host_identity=host_identity,
        admission_registry=admission_registry,
    )
    return {
        'manifest_version': 1,
        'generated_at': _now(),
        'host_identity': runtime_core['host_identity'],
        'institution_context': runtime_core['institution_context'],
        'admission': runtime_core['admission'],
        'service_registry': runtime_core['service_registry'],
        'witness_archive': federation['witness_archive'],
        'federation': {
            key: value
            for key, value in federation.items()
            if key not in ('peers', 'trusted_peers', 'trusted_peer_ids')
        },
    }


def _witness_archive_snapshot(bound_org_id, host_identity=None):
    if host_identity is None:
        host_identity, _admission_registry = _runtime_host_state(bound_org_id)
    archive_enabled = getattr(host_identity, 'role', '') == 'witness_host'
    records = (
        list_witness_observations(WITNESS_ARCHIVE_FILE, host_id=host_identity.host_id)
        if archive_enabled else
        []
    )
    summary = (
        witness_archive_summary(WITNESS_ARCHIVE_FILE, host_id=host_identity.host_id)
        if archive_enabled else
        {
            'total': 0,
            'message_type_counts': {},
            'peer_host_ids': [],
            'latest_observed_at': '',
        }
    )
    return {
        'bound_org_id': bound_org_id,
        'host_id': host_identity.host_id,
        'host_role': host_identity.role,
        'boundary_name': 'federation_gateway',
        'archive_enabled': archive_enabled,
        'archive_disabled_reason': '' if archive_enabled else 'witness_host_only',
        'mutation_enabled': archive_enabled,
        'mutation_disabled_reason': '' if archive_enabled else 'witness_host_only',
        'management_mode': (
            'witness_local_archive'
            if archive_enabled else
            'host_role_unavailable'
        ),
        'records': records,
        'summary': summary,
    }


def _admission_management_state(host_identity=None):
    if getattr(host_identity, 'role', '') == 'witness_host':
        return _witness_read_only_management_state()
    return {
        'management_mode': 'founding_locked',
        'mutation_enabled': False,
        'mutation_disabled_reason': 'single_institution_deployment',
    }


def _admission_snapshot(bound_org_id, host_identity=None, admission_registry=None):
    if host_identity is None or admission_registry is None:
        host_identity, admission_registry = _runtime_host_state(bound_org_id)
    institutions = {}
    for org_id, entry in sorted(admission_registry.get('institutions', {}).items()):
        data = dict(entry or {})
        data['org_id'] = org_id
        institutions[org_id] = data
    return {
        'bound_org_id': bound_org_id,
        'host_id': host_identity.host_id,
        'host_role': host_identity.role,
        'source': admission_registry.get('source', 'none'),
        'admitted_org_ids': list(admission_registry.get('admitted_org_ids', [])),
        'institutions': institutions,
        **_admission_management_state(host_identity),
    }


def _mutate_admission(bound_org_id, action, target_org_id):
    raise PermissionError(
        f"Live runtime remains founding-only; admission mutation '{action}' is disabled "
        f"for institution '{bound_org_id}'"
    )


def _commitment_management_state():
    return {
        'management_mode': 'founding_workspace_local',
        'mutation_enabled': True,
        'mutation_disabled_reason': '',
    }


def _commitment_snapshot(bound_org_id):
    summary = commitments.commitment_summary(bound_org_id)
    return {
        'bound_org_id': bound_org_id,
        **_commitment_management_state(),
        **summary,
        'commitments': commitments.list_commitments(bound_org_id),
    }


def _payout_snapshot(bound_org_id, *, host_supported_adapters=None):
    phase_num, phase_details = _phase_mod.evaluate(bound_org_id)
    phase_gate_ok = phase_num >= 5
    return {
        'bound_org_id': bound_org_id,
        'management_mode': 'founding_workspace_local',
        'mutation_enabled': True,
        'mutation_disabled_reason': '',
        'phase_machine': {
            'number': phase_num,
            'name': phase_details.get('name', ''),
            'next_phase': phase_details.get('next_phase'),
            'next_phase_name': phase_details.get('next_phase_name'),
            'next_unlock': phase_details.get('next_unlock'),
        },
        'execution_gate': {
            'phase_ok': phase_gate_ok,
            'phase_required': 5,
            'reason': (
                f"Phase {phase_num} ({phase_details.get('name', '')}) permits contributor payouts"
                if phase_gate_ok
                else f"Phase {phase_num} ({phase_details.get('name', '')}) does not allow contributor payouts yet"
            ),
        },
        'summary': payout_proposal_summary(bound_org_id),
        'proposals': list_payout_proposals(bound_org_id),
        'policy': load_payout_proposals(bound_org_id).get('state_machine', {}),
        'settlement_adapter_summary': settlement_adapter_summary(
            bound_org_id,
            host_supported_adapters=host_supported_adapters,
        ),
        'settlement_adapters': list_settlement_adapters(bound_org_id),
    }


def _settlement_adapter_readiness_snapshot(bound_org_id, *, host_supported_adapters=None):
    return settlement_adapter_readiness_snapshot(
        bound_org_id,
        host_supported_adapters=host_supported_adapters,
    )


def _agent_runtime_usage_snapshot(org_id=None):
    usage = {}
    unregistered_bindings = []
    agents = [
        normalize_agent_record(agent)
        for agent in load_registry().get('agents', {}).values()
        if agent.get('org_id') in (None, '', org_id)
    ]
    for agent in agents:
        binding = dict(agent.get('runtime_binding') or {})
        runtime_id = (binding.get('runtime_id') or '').strip()
        if not runtime_id:
            continue
        entry = usage.setdefault(runtime_id, {
            'runtime_id': runtime_id,
            'bound_agent_ids': [],
            'bound_org_ids': [],
        })
        entry['bound_agent_ids'].append(agent.get('id'))
        bound_org_id = agent.get('org_id')
        if bound_org_id:
            entry['bound_org_ids'].append(bound_org_id)
        if not binding.get('runtime_registered', True):
            unregistered_bindings.append({
                'agent_id': agent.get('id'),
                'org_id': bound_org_id,
                'runtime_id': runtime_id,
                'registration_status': binding.get('registration_status', 'missing_runtime'),
            })

    for entry in usage.values():
        entry['bound_agent_ids'] = sorted({aid for aid in entry['bound_agent_ids'] if aid})
        entry['bound_org_ids'] = sorted({oid for oid in entry['bound_org_ids'] if oid})
        entry['bound_agent_count'] = len(entry['bound_agent_ids'])
        entry['runtime_binding_status'] = 'in_use' if entry['bound_agent_count'] else 'declared_unused'

    return {
        'runtimes': usage,
        'unregistered_bindings': unregistered_bindings,
    }


def _case_management_state():
    return {
        'management_mode': 'founding_workspace_local',
        'mutation_enabled': True,
        'mutation_disabled_reason': '',
    }


def _case_snapshot(bound_org_id):
    return {
        'bound_org_id': bound_org_id,
        **_case_management_state(),
        **cases.case_summary(bound_org_id),
        'blocking_commitment_ids': cases.blocking_commitment_ids(bound_org_id),
        'blocked_peer_host_ids': cases.blocked_peer_host_ids(bound_org_id),
        'cases': cases.list_cases(bound_org_id),
    }


def _maybe_open_case_for_commitment_breach(commitment_record, actor_id, *, org_id, note=''):
    return cases.ensure_case_for_commitment_breach(
        commitment_record,
        actor_id,
        org_id=org_id,
        note=note,
    )


def _maybe_stay_warrant_for_case(case_record, actor_id, *, org_id, session_id=None, note=''):
    warrant_id = (case_record or {}).get('linked_warrant_id', '').strip()
    if not warrant_id:
        return None
    record = next(
        (item for item in list_warrants(org_id) if item.get('warrant_id') == warrant_id),
        None,
    )
    if not record:
        return {
            'applied': False,
            'warrant_id': warrant_id,
            'reason': 'warrant_not_found',
            'court_review_state': '',
            'execution_state': '',
        }
    review_state = record.get('court_review_state', '')
    execution_state = record.get('execution_state', '')
    if execution_state != 'ready':
        return {
            'applied': False,
            'warrant_id': warrant_id,
            'reason': f'execution_state_{execution_state or "unknown"}',
            'court_review_state': review_state,
            'execution_state': execution_state,
            'warrant': record,
        }
    if review_state == 'stayed':
        return {
            'applied': False,
            'warrant_id': warrant_id,
            'reason': 'already_stayed',
            'court_review_state': review_state,
            'execution_state': execution_state,
            'warrant': record,
        }
    if review_state == 'revoked':
        return {
            'applied': False,
            'warrant_id': warrant_id,
            'reason': 'already_revoked',
            'court_review_state': review_state,
            'execution_state': execution_state,
            'warrant': record,
        }
    stayed = review_warrant(
        warrant_id,
        'stay',
        actor_id,
        org_id=org_id,
        note=note or f"Automatically stayed because case {case_record.get('case_id', '')} is active",
    )
    execution_job = _sync_execution_job_for_warrant_review(
        org_id,
        stayed,
        actor_id=actor_id,
        session_id=session_id,
        reason='case_hold_applied',
    )
    court_notice = None
    if execution_job:
        try:
            court_notice = _deliver_execution_job_court_notice(
                org_id,
                execution_job,
                stayed,
                'stay',
                actor_id=actor_id,
                session_id=session_id,
                note=note or f"Stayed because case {case_record.get('case_id', '')} is active",
            )
        except (FederationUnavailable, FederationDeliveryError, FederationValidationError, PermissionError, LookupError, RuntimeError, ValueError) as exc:
            log_event(
                org_id,
                actor_id,
                'federation_court_notice_delivery_failed',
                resource=(execution_job or {}).get('job_id', ''),
                outcome='failed',
                details={
                    'case_id': case_record.get('case_id', ''),
                    'local_warrant_id': warrant_id,
                    'error': str(exc),
                },
                session_id=session_id,
            )
    log_event(
        org_id,
        actor_id,
        'warrant_stayed_for_case',
        outcome='success',
        resource=warrant_id,
        details={
            'case_id': case_record.get('case_id', ''),
            'claim_type': case_record.get('claim_type', ''),
            'previous_court_review_state': review_state,
            'court_review_state': stayed.get('court_review_state', ''),
            'execution_job_id': (execution_job or {}).get('job_id', ''),
            'job_state': (execution_job or {}).get('state', ''),
        },
        session_id=session_id,
    )
    result = {
        'applied': True,
        'warrant_id': warrant_id,
        'reason': 'case_hold_applied',
        'court_review_state': stayed.get('court_review_state', ''),
        'execution_state': stayed.get('execution_state', ''),
        'warrant': stayed,
    }
    if execution_job:
        result['execution_job'] = execution_job
    if court_notice:
        result['court_notice'] = court_notice
    return result


def _maybe_block_commitment_settlement(commitment_id, actor_id, *, org_id, session_id=None, note=''):
    case_record = cases.blocking_commitment_case(commitment_id, org_id=org_id)
    if not case_record:
        return None, None
    warrant = _maybe_stay_warrant_for_case(
        case_record,
        actor_id,
        org_id=org_id,
        session_id=session_id,
        note=note or f"Settlement blocked while case {case_record.get('case_id', '')} remains active",
    )
    log_event(
        org_id,
        actor_id,
        'commitment_settlement_blocked',
        outcome='blocked',
        resource=commitment_id,
        details={
            'case_id': case_record.get('case_id', ''),
            'claim_type': case_record.get('claim_type', ''),
            'case_status': case_record.get('status', ''),
            'linked_warrant_id': case_record.get('linked_warrant_id', ''),
        },
        session_id=session_id,
    )
    return case_record, warrant


def _blocking_case_for_delivery(*, org_id, commitment_id='', target_host_id='', message_type=''):
    try:
        if message_type in ('commitment_breach_notice', 'case_notice'):
            return None
        if message_type != 'commitment_breach_notice':
            commitment_case = cases.blocking_commitment_case(commitment_id, org_id=org_id)
            if commitment_case:
                return commitment_case
        return cases.blocking_peer_case(target_host_id, org_id=org_id)
    except (SystemExit, ValueError):
        return None


def _maybe_suspend_peer_for_case(case_record, actor_id, *, org_id, session_id=None):
    if not cases.case_requires_peer_block(case_record):
        return None
    target_host_id = (case_record.get('target_host_id') or '').strip()
    if not target_host_id:
        return None
    management = _federation_management_state()
    return {
        'applied': False,
        'peer_host_id': target_host_id,
        'reason': management['mutation_disabled_reason'],
        'trust_state': '',
    }


def _maybe_restore_peer_for_case(case_record, actor_id, *, org_id, session_id=None):
    if not cases.case_targets_peer_block(case_record):
        return {
            'applied': False,
            'peer_host_id': (case_record.get('target_host_id') or '').strip(),
            'reason': 'case_not_peer_blocking',
            'trust_state': '',
        }
    target_host_id = (case_record.get('target_host_id') or '').strip()
    if not target_host_id:
        return None
    host_identity, admission_registry = _runtime_host_state(org_id)
    management = _federation_management_state(host_identity)
    if not management['mutation_enabled']:
        return {
            'applied': False,
            'peer_host_id': target_host_id,
            'reason': management['mutation_disabled_reason'],
            'trust_state': '',
        }
    if not cases.peer_can_be_thawed(target_host_id, org_id=org_id):
        return {
            'applied': False,
            'peer_host_id': target_host_id,
            'reason': 'peer_still_blocked',
            'trust_state': '',
        }
    try:
        peer_registry = set_peer_trust_state(
            FEDERATION_PEERS_FILE,
            target_host_id,
            'trusted',
            host_identity=host_identity,
        )
    except LookupError:
        return {
            'applied': False,
            'peer_host_id': target_host_id,
            'reason': 'peer_not_registered',
            'trust_state': '',
        }
    def _peer_value(peer, field, default=''):
        if isinstance(peer, dict):
            return peer.get(field, default)
        return getattr(peer, field, default)
    peer_record = next(
        (
            peer
            for peer in (peer_registry.get('peers', {}) or {}).values()
            if _peer_value(peer, 'host_id', '') == target_host_id
        ),
        None,
    )
    log_event(
        org_id,
        actor_id,
        'federation_peer_auto_reinstated',
        resource=target_host_id,
        outcome='success',
        details={
            'peer_host_id': target_host_id,
            'case_id': case_record.get('case_id', ''),
            'claim_type': case_record.get('claim_type', ''),
            'trust_state': _peer_value(peer_record, 'trust_state', ''),
        },
        session_id=session_id,
    )
    return {
        'applied': True,
        'peer_host_id': target_host_id,
        'reason': '',
        'trust_state': _peer_value(peer_record, 'trust_state', ''),
        'admitted_org_ids': list(_peer_value(peer_record, 'admitted_org_ids', []) or []),
        'label': _peer_value(peer_record, 'label', ''),
        'federation': {
            'host_id': host_identity.host_id,
            'peer_host_id': target_host_id,
            'peer_trust_state': _peer_value(peer_record, 'trust_state', ''),
        },
    }


def _sender_warrant_delivery_ref(commitment_record):
    for ref in reversed((commitment_record or {}).get('delivery_refs', []) or []):
        if (ref or {}).get('warrant_id'):
            return dict(ref or {})
    return None


def _maybe_finalize_sender_warrant_for_commitment(commitment_record, claims, receipt,
                                                  settlement_ref, *, org_id,
                                                  actor_id, session_id=None):
    claim_data = _federation_claims_dict(claims)
    delivery_ref = _sender_warrant_delivery_ref(commitment_record)
    if not delivery_ref:
        return None
    warrant_id = (delivery_ref.get('warrant_id') or '').strip()
    if not warrant_id:
        return None
    warrant = get_warrant(warrant_id, org_id=org_id)
    if not warrant:
        return None
    if warrant.get('execution_state') == 'executed':
        return warrant
    execution_refs = {
        'message_type': 'settlement_notice',
        'commitment_id': (commitment_record or {}).get('commitment_id', ''),
        'sender_warrant_id': warrant_id,
        'source_delivery_envelope_id': delivery_ref.get('envelope_id', ''),
        'source_delivery_receipt_id': delivery_ref.get('receipt_id', ''),
        'source_delivery_target_host_id': delivery_ref.get('target_host_id', ''),
        'source_delivery_target_institution_id': delivery_ref.get('target_institution_id', ''),
        'settlement_notice_envelope_id': claim_data.get('envelope_id', ''),
        'settlement_notice_receipt_id': (receipt or {}).get('receipt_id', ''),
        'settlement_notice_target_host_id': claim_data.get('target_host_id', ''),
        'settlement_notice_target_institution_id': claim_data.get('target_institution_id', ''),
        'settlement_notice_sent_at': (receipt or {}).get('accepted_at', '') or _now(),
        'proposal_id': (settlement_ref or {}).get('proposal_id', ''),
        'tx_ref': (settlement_ref or {}).get('tx_ref', ''),
        'tx_hash': (settlement_ref or {}).get('tx_hash', ''),
        'settlement_adapter': (settlement_ref or {}).get('settlement_adapter', ''),
        'proof_type': (settlement_ref or {}).get('proof_type', ''),
        'verification_state': (settlement_ref or {}).get('verification_state', ''),
        'finality_state': (settlement_ref or {}).get('finality_state', ''),
    }
    warrant = mark_warrant_executed(
        warrant_id,
        org_id=org_id,
        execution_refs=execution_refs,
    )
    log_event(
        org_id,
        actor_id,
        'federated_execution_warrant_finalized',
        resource=warrant_id,
        outcome='success',
        details={
            'commitment_id': execution_refs['commitment_id'],
            'settlement_notice_envelope_id': execution_refs['settlement_notice_envelope_id'],
            'settlement_notice_receipt_id': execution_refs['settlement_notice_receipt_id'],
        },
        session_id=session_id,
    )
    return warrant


def _delivery_failure_claim_type(error_message):
    message = (error_message or '').lower()
    if not message:
        return ''
    if 'signature verification failed' in message:
        return 'fraudulent_proof'
    if 'receiver_host_id' in message or 'receiver_institution_id' in message:
        return 'misrouted_execution'
    if 'receipt' in message:
        return 'invalid_settlement_notice'
    return ''


def _maybe_open_case_for_delivery_failure(exc, actor_id, *, org_id, target_host_id,
                                          target_institution_id, commitment_id='',
                                          warrant_id='', session_id=None):
    claim_type = _delivery_failure_claim_type(str(exc))
    if not claim_type:
        return None, None
    try:
        case_record, created = cases.ensure_case_for_delivery_failure(
            claim_type,
            actor_id,
            org_id=org_id,
            target_host_id=target_host_id,
            target_institution_id=target_institution_id,
            linked_commitment_id=commitment_id,
            linked_warrant_id=warrant_id,
            note=str(exc),
            metadata={
                'peer_host_id': exc.peer_host_id,
                'error': str(exc),
            },
        )
    except (SystemExit, ValueError):
        return None, None
    if created:
        log_event(
            org_id,
            actor_id,
            'case_opened',
            resource=case_record['case_id'],
            outcome='success',
            details={
                'claim_type': case_record.get('claim_type', ''),
                'linked_commitment_id': case_record.get('linked_commitment_id', ''),
                'source': 'federation_delivery_failure',
            },
            session_id=session_id,
        )
    return case_record, _maybe_suspend_peer_for_case(
        case_record,
        actor_id,
        org_id=org_id,
        session_id=session_id,
    )


def _accept_federation_request(bound_org_id, envelope, payload=None, *, peer_registry=None):
    host_identity, admission_registry = _runtime_host_state(bound_org_id)
    authority = _federation_authority(host_identity, peer_registry=peer_registry)
    claims = authority.accept(
        envelope,
        payload=payload,
        expected_target_host_id=host_identity.host_id,
        expected_target_org_id=bound_org_id,
        expected_boundary_name='federation_gateway',
    )
    return claims, authority.snapshot(
        bound_org_id=bound_org_id,
        admission_registry=admission_registry,
    )


def _control_plane_notice_validation_peer_registry(bound_org_id, envelope):
    envelope = (envelope or '').strip()
    if not envelope or '.' not in envelope:
        return None
    try:
        body_b64 = envelope.split('.', 1)[0]
        padding = '=' * ((4 - (len(body_b64) % 4)) % 4)
        body = json.loads(base64.urlsafe_b64decode(body_b64 + padding).decode('utf-8'))
    except Exception:
        return None
    if body.get('message_type') not in ('case_notice', 'court_notice'):
        return None
    source_host_id = (body.get('source_host_id') or '').strip()
    if not source_host_id:
        return None
    host_identity = load_host_identity(
        RUNTIME_HOST_IDENTITY_FILE,
        supported_boundaries=SUPPORTED_RUNTIME_BOUNDARIES,
    )
    registry = load_peer_registry(
        FEDERATION_PEERS_FILE,
        host_identity=host_identity,
    )
    source_peer = registry.get('peers', {}).get(source_host_id)
    if not source_peer or getattr(source_peer, 'trust_state', '') != 'suspended':
        return None
    registry = copy.deepcopy(registry)
    registry['peers'][source_host_id].trust_state = 'trusted'
    return registry


def _mutate_federation_peer(bound_org_id, action, payload):
    raise PermissionError(
        f"Live runtime remains founding-only; federation peer mutation '{action}' is disabled "
        f"for institution '{bound_org_id}'"
    )


def _federation_claims_dict(claims):
    if not claims:
        return {}
    if isinstance(claims, dict):
        return dict(claims)
    if hasattr(claims, 'to_dict'):
        return claims.to_dict()
    return {}


def _acknowledge_and_dispatch_remote_handoff_preview(bound_org_id, handoff_id, *, actor_id, note=''):
    preview = kernel_acknowledge_handoff_preview(
        bound_org_id,
        handoff_id,
        by=actor_id,
        note=note,
    )
    result = {
        'handoff_preview': preview,
        'dispatch_record': None,
        'dispatch_record_created': False,
        'dispatch_record_error': '',
    }
    if not preview.get('dispatch_ready'):
        return result
    try:
        dispatch_record = kernel_promote_acknowledged_handoff_preview_to_dispatch_record(
            bound_org_id,
            handoff_id,
            promoted_by=actor_id,
            promotion_note=note,
        )
    except (LookupError, PermissionError, ValueError) as exc:
        result['dispatch_record_error'] = str(exc)
        return result
    result['dispatch_record'] = dispatch_record
    result['dispatch_record_created'] = True
    return result


def _merged_dispatch_execution_request(dispatch_record):
    record = dict(dispatch_record or {})
    preview_snapshot = dict(record.get('preview_snapshot') or {})
    preview_draft = dict(preview_snapshot.get('draft_execution_request') or {})
    draft = dict(preview_draft)
    draft.update(dict(record.get('draft_execution_request') or {}))
    return preview_snapshot, draft


def _existing_remote_dispatch_result(dispatch_record):
    record = dict(dispatch_record or {})
    if record.get('state') != 'dispatched':
        return None
    if record.get('dispatch_runner') != 'remote_http_federation_runner':
        return None
    delivery_snapshot = dict(record.get('delivery_snapshot') or {})
    if not delivery_snapshot:
        return None
    response_processing = dict(delivery_snapshot.get('response_processing') or {})
    execution_job = dict(record.get('execution_job_snapshot') or response_processing.get('execution_job') or {})
    receiver_warrant = dict(response_processing.get('receiver_warrant') or {})
    blocking_case = dict(response_processing.get('case') or response_processing.get('blocking_case') or {})
    return {
        'dispatch_record': record,
        'delivery': delivery_snapshot,
        'execution_job': execution_job or None,
        'receiver_warrant': receiver_warrant or None,
        'blocking_case': blocking_case or None,
        'dispatch_runner': 'remote_http_federation_runner',
        'dispatch_state': 'dispatched',
        'dispatch_blockers': [],
        'execution_job_created': bool(execution_job),
        'delivery_received': True,
        'already_dispatched': True,
    }


def _run_federation_dispatch(bound_org_id, dispatch_id, *, actor_id, note='', session_id=None,
                             payload=None, warrant_id='', commitment_id='', ttl_seconds=None):
    dispatch_id = (dispatch_id or '').strip()
    actor_id = (actor_id or '').strip()
    if not dispatch_id:
        raise ValueError('dispatch_id is required')
    if not actor_id:
        raise ValueError('actor_id is required')

    dispatch_record = kernel_get_handoff_dispatch_record(dispatch_id, bound_org_id)
    if not dispatch_record:
        raise LookupError(f'Federation handoff dispatch record not found: {dispatch_id}')

    existing_result = _existing_remote_dispatch_result(dispatch_record)
    if existing_result is not None:
        return existing_result

    preview_snapshot, draft = _merged_dispatch_execution_request(dispatch_record)
    target_host_id = (
        draft.get('target_host_id')
        or dispatch_record.get('target_host_id')
        or ''
    ).strip()
    target_institution_id = (
        draft.get('target_institution_id')
        or dispatch_record.get('requested_org_id')
        or ''
    ).strip()
    if not target_host_id:
        raise ValueError('target_host_id is required for federation handoff dispatch')
    if not target_institution_id:
        raise ValueError('target_institution_id is required for federation handoff dispatch')

    request_payload = payload if payload is not None else draft.get('payload')
    if request_payload is None:
        request_payload = {}
    if not isinstance(request_payload, dict):
        raise ValueError('payload must be a JSON object for federation handoff dispatch')

    resolved_warrant_id = (warrant_id or draft.get('warrant_id') or '').strip()
    resolved_commitment_id = (commitment_id or draft.get('commitment_id') or '').strip()
    message_type = (draft.get('message_type') or 'execution_request').strip()

    delivery, federation_state = _deliver_federation_envelope(
        bound_org_id,
        target_host_id,
        target_institution_id,
        message_type,
        payload=request_payload,
        actor_type='user',
        actor_id=actor_id,
        session_id=session_id or '',
        warrant_id=resolved_warrant_id,
        commitment_id=resolved_commitment_id,
        ttl_seconds=ttl_seconds,
    )
    response_processing = dict((delivery.get('response') or {}).get('processing') or {})
    remote_execution_job = dict(response_processing.get('execution_job') or {})
    blocking_case = dict(response_processing.get('case') or response_processing.get('blocking_case') or {})
    receiver_warrant = dict(response_processing.get('receiver_warrant') or {})
    dispatch_note = note or (
        'Remote HTTP federation dispatch delivered envelope and receiver-side execution job was persisted'
        if remote_execution_job and not blocking_case else
        'Remote HTTP federation dispatch delivered envelope and receiver-side execution job was blocked by case'
        if blocking_case else
        'Remote HTTP federation dispatch delivered envelope'
    )
    delivery_snapshot = {
        'message_type': (delivery.get('claims') or {}).get('message_type', ''),
        'claims': copy.deepcopy(delivery.get('claims') or {}),
        'receipt': copy.deepcopy(delivery.get('receipt') or {}),
        'response_processing': copy.deepcopy(response_processing),
    }
    updated_dispatch = kernel_mark_handoff_dispatch_record_dispatched(
        bound_org_id,
        dispatch_id,
        dispatched_by=actor_id,
        note=dispatch_note,
        dispatch_runner='remote_http_federation_runner',
        execution_job_id=(remote_execution_job.get('job_id') or '').strip(),
        execution_job_state=(remote_execution_job.get('state') or '').strip(),
        execution_job_snapshot=remote_execution_job,
        delivery_snapshot=delivery_snapshot,
        dispatch_truth_source='remote_federation_receipt_and_receiver_processing',
    )
    return {
        'dispatch_record': updated_dispatch,
        'delivery': delivery,
        'execution_job': remote_execution_job or None,
        'receiver_warrant': receiver_warrant or None,
        'blocking_case': blocking_case or None,
        'federation_state': federation_state,
        'dispatch_runner': 'remote_http_federation_runner',
        'dispatch_state': 'dispatched',
        'dispatch_blockers': [],
        'execution_job_created': bool(remote_execution_job),
    }


def _federation_audit_details(claims, **extra):
    claim_data = _federation_claims_dict(claims)
    details = {
        'envelope_id': claim_data.get('envelope_id', ''),
        'source_host_id': claim_data.get('source_host_id', ''),
        'source_institution_id': claim_data.get('source_institution_id', ''),
        'target_host_id': claim_data.get('target_host_id', ''),
        'target_institution_id': claim_data.get('target_institution_id', ''),
        'nonce': claim_data.get('nonce', ''),
        'boundary_name': claim_data.get('boundary_name', ''),
        'warrant_id': claim_data.get('warrant_id', ''),
        'commitment_id': claim_data.get('commitment_id', ''),
    }
    for key, value in extra.items():
        if value not in (None, ''):
            details[key] = value
    return details


def _federation_receipt(bound_org_id, receiver_host_id, claims):
    claim_data = _federation_claims_dict(claims)
    envelope_id = claim_data.get('envelope_id', '')
    receipt_material = ':'.join((
        (receiver_host_id or '').strip(),
        (bound_org_id or '').strip(),
        envelope_id,
    ))
    receipt_id = 'fedrcpt_' + hashlib.sha256(receipt_material.encode('utf-8')).hexdigest()[:12]
    return {
        'receipt_id': receipt_id,
        'envelope_id': envelope_id,
        'accepted_at': _now(),
        'receiver_host_id': (receiver_host_id or '').strip(),
        'receiver_institution_id': (bound_org_id or '').strip(),
        'message_type': claim_data.get('message_type', ''),
        'boundary_name': claim_data.get('boundary_name', ''),
        'identity_model': 'signed_host_service',
    }


def _federation_inbox_entry(bound_org_id, claims, receipt, *, payload=None, state='received'):
    claim_data = _federation_claims_dict(claims)
    accepted_at = (receipt or {}).get('accepted_at', '') or _now()
    return upsert_inbox_entry(
        bound_org_id,
        envelope_id=claim_data.get('envelope_id', ''),
        source_host_id=claim_data.get('source_host_id', ''),
        source_institution_id=claim_data.get('source_institution_id', ''),
        target_host_id=claim_data.get('target_host_id', ''),
        target_institution_id=claim_data.get('target_institution_id', ''),
        message_type=claim_data.get('message_type', ''),
        warrant_id=claim_data.get('warrant_id', ''),
        commitment_id=claim_data.get('commitment_id', ''),
        payload=payload,
        payload_hash=claim_data.get('payload_hash', ''),
        receipt_id=(receipt or {}).get('receipt_id', ''),
        accepted_at=accepted_at,
        received_at=accepted_at,
        state=state,
    )


def _federation_inbox_snapshot(bound_org_id, *, limit=50):
    return {
        'management_mode': 'capsule_backed',
        'mutation_enabled': False,
        'mutation_disabled_reason': 'receive_only',
        'storage_model': 'capsule_canonical',
        'boundary_name': 'federation_gateway',
        'identity_model': 'signed_host_service',
        'summary': summarize_inbox_entries(bound_org_id),
        'entries': load_inbox_entries(bound_org_id)[:limit],
    }


def _receiver_execution_warrant_payload(claims, payload=None):
    claim_data = _federation_claims_dict(claims)
    return {
        'source_host_id': claim_data.get('source_host_id', ''),
        'source_institution_id': claim_data.get('source_institution_id', ''),
        'target_host_id': claim_data.get('target_host_id', ''),
        'target_institution_id': claim_data.get('target_institution_id', ''),
        'message_type': claim_data.get('message_type', ''),
        'boundary_name': claim_data.get('boundary_name', ''),
        'identity_model': claim_data.get('identity_model', ''),
        'sender_warrant_id': claim_data.get('warrant_id', ''),
        'commitment_id': claim_data.get('commitment_id', ''),
        'payload': payload if isinstance(payload, dict) else {},
    }


def _execution_job_view(bound_org_id, job):
    record = dict(job or {})
    local_warrant_id = (record.get('local_warrant_id') or '').strip()
    if local_warrant_id:
        warrant = get_warrant(local_warrant_id, org_id=bound_org_id)
        if warrant:
            record['local_warrant'] = {
                'warrant_id': warrant.get('warrant_id', ''),
                'court_review_state': warrant.get('court_review_state', ''),
                'execution_state': warrant.get('execution_state', ''),
                'expires_at': warrant.get('expires_at', ''),
            }
    return record


def _federation_execution_jobs_snapshot(bound_org_id, *, limit=50):
    jobs = [
        _execution_job_view(bound_org_id, job)
        for job in list_execution_jobs(bound_org_id)[:limit]
    ]
    return {
        'management_mode': 'capsule_backed',
        'mutation_enabled': False,
        'mutation_disabled_reason': 'review_via_warrants',
        'storage_model': 'capsule_canonical',
        'boundary_name': 'federation_gateway',
        'identity_model': 'signed_host_service',
        'summary': execution_job_summary(bound_org_id),
        'jobs': jobs,
    }


def _reject_live_execution_job_completion(bound_org_id):
    return {
        'error': (
            f"Live runtime remains founding-only; receiver-side execution jobs stay "
            f"review-only for institution '{bound_org_id}'"
        ),
        'management_mode': 'founding_locked',
        'mutation_enabled': False,
        'state_change': False,
        'boundary_name': 'federation_gateway',
        'identity_model': 'signed_host_service',
        'mutation_disabled_reason': 'single_institution_deployment',
        'execution_jobs': _federation_execution_jobs_snapshot(bound_org_id),
    }


def _queue_received_execution_request(bound_org_id, claims, receipt, *, payload=None):
    existing = get_execution_job(claims.envelope_id, org_id=bound_org_id)
    if existing:
        return _execution_job_view(bound_org_id, existing), (
            get_warrant(existing.get('local_warrant_id', ''), org_id=bound_org_id)
            if existing.get('local_warrant_id')
            else None
        ), None

    actor_id = claims.actor_id or f'peer:{claims.source_host_id}'
    blocking_case = _blocking_case_for_delivery(
        org_id=bound_org_id,
        commitment_id=claims.commitment_id,
        target_host_id=claims.source_host_id,
    )
    if blocking_case:
        blocked_job = upsert_execution_job(bound_org_id, {
            'envelope_id': claims.envelope_id,
            'source_host_id': claims.source_host_id,
            'source_institution_id': claims.source_institution_id,
            'target_host_id': claims.target_host_id,
            'target_institution_id': claims.target_institution_id,
            'message_type': claims.message_type,
            'receipt_id': (receipt or {}).get('receipt_id', ''),
            'actor_type': claims.actor_type or 'service',
            'actor_id': actor_id,
            'session_id': claims.session_id or '',
            'boundary_name': claims.boundary_name,
            'identity_model': claims.identity_model,
            'sender_warrant_id': claims.warrant_id,
            'local_warrant_id': '',
            'commitment_id': claims.commitment_id,
            'payload': payload,
            'payload_hash': claims.payload_hash,
            'state': 'blocked',
            'received_at': (receipt or {}).get('accepted_at', '') or _now(),
            'note': 'Receiver-side case blocks incoming execution request',
            'metadata': {
                'case_id': blocking_case.get('case_id', ''),
                'case_status': blocking_case.get('status', ''),
                'claim_type': blocking_case.get('claim_type', ''),
            },
        })
        return _execution_job_view(bound_org_id, blocked_job), None, blocking_case

    receiver_warrant = issue_warrant(
        bound_org_id,
        'federated_execution',
        'federation_gateway',
        actor_id,
        session_id='',
        request_payload=_receiver_execution_warrant_payload(claims, payload),
        risk_class='high',
        evidence_refs=[
            f"federation_envelope:{claims.envelope_id}",
            f"federation_receipt:{(receipt or {}).get('receipt_id', '')}",
        ],
        auto_issue=False,
        note='Receiver-side local review for incoming execution_request',
    )
    job = upsert_execution_job(bound_org_id, {
        'envelope_id': claims.envelope_id,
        'source_host_id': claims.source_host_id,
        'source_institution_id': claims.source_institution_id,
        'target_host_id': claims.target_host_id,
        'target_institution_id': claims.target_institution_id,
        'message_type': claims.message_type,
        'receipt_id': (receipt or {}).get('receipt_id', ''),
        'actor_type': claims.actor_type or 'service',
        'actor_id': actor_id,
        'session_id': claims.session_id or '',
        'boundary_name': claims.boundary_name,
        'identity_model': claims.identity_model,
        'sender_warrant_id': claims.warrant_id,
        'local_warrant_id': receiver_warrant['warrant_id'],
        'commitment_id': claims.commitment_id,
        'payload': payload,
        'payload_hash': claims.payload_hash,
        'state': 'pending_local_warrant',
        'received_at': (receipt or {}).get('accepted_at', '') or _now(),
        'note': 'Receiver-side execution request queued for local warrant review',
        'metadata': {
            'source_boundary_name': claims.boundary_name,
        },
    })
    return _execution_job_view(bound_org_id, job), receiver_warrant, None


def _execution_job_state_for_warrant(warrant):
    record = dict(warrant or {})
    execution_state = (record.get('execution_state') or '').strip()
    review_state = (record.get('court_review_state') or '').strip()
    if execution_state == 'executed':
        return 'executed'
    if review_state in ('auto_issued', 'approved') and execution_state == 'ready':
        return 'ready'
    if review_state == 'pending_review':
        return 'pending_local_warrant'
    if review_state == 'stayed':
        return 'blocked'
    if review_state == 'revoked':
        return 'rejected'
    return ''


def _sync_execution_job_for_warrant_review(bound_org_id, warrant, *, decision='', note='', actor_id='', session_id=None, reason=''):
    warrant = dict(warrant or {})
    if warrant.get('action_class') != 'federated_execution':
        return None
    if warrant.get('boundary_name') != 'federation_gateway':
        return None
    warrant_id = (warrant.get('warrant_id') or '').strip()
    if not warrant_id:
        return None
    desired_state = _execution_job_state_for_warrant(warrant)
    if not desired_state:
        return None

    existing = get_execution_job_by_local_warrant(warrant_id, bound_org_id)
    if not existing:
        return None

    review_decision = (decision or warrant.get('court_review_state') or '').strip()
    synced = sync_execution_job_for_local_warrant(
        bound_org_id,
        warrant_id,
        state=desired_state,
        note=note or reason or f"Local warrant {warrant.get('court_review_state', '')} via workspace review",
        metadata={
            'review_decision': review_decision,
            'reviewed_by': warrant.get('reviewed_by', ''),
            'reviewed_at': warrant.get('reviewed_at', ''),
            'court_review_state': warrant.get('court_review_state', ''),
            'execution_state': warrant.get('execution_state', ''),
        },
    )
    if not synced:
        return None
    job = _execution_job_view(bound_org_id, synced)
    if actor_id:
        log_event(
            bound_org_id,
            actor_id,
            'federation_execution_job_review_synced',
            resource=job.get('job_id', ''),
            outcome='success',
            details={
                'local_warrant_id': warrant_id,
                'court_review_state': warrant.get('court_review_state', ''),
                'job_state': job.get('state', ''),
                'reason': reason or 'workspace_warrant_review',
            },
            session_id=session_id,
        )
    return job


def _execution_job_court_notice_payload(job, warrant, decision, *, note=''):
    record = dict(job or {})
    warrant = dict(warrant or {})
    metadata = dict(record.get('metadata') or {})
    metadata.update({
        'source': 'receiver_local_warrant_review',
        'message_type': 'court_notice',
    })
    return {
        'court_decision': (decision or '').strip(),
        'sender_warrant_id': (record.get('sender_warrant_id') or '').strip(),
        'local_warrant_id': (record.get('local_warrant_id') or warrant.get('warrant_id') or '').strip(),
        'source_execution_envelope_id': (record.get('envelope_id') or '').strip(),
        'source_execution_job_id': (record.get('job_id') or '').strip(),
        'source_execution_receipt_id': (record.get('receipt_id') or '').strip(),
        'local_court_review_state': (warrant.get('court_review_state') or '').strip(),
        'local_execution_state': (warrant.get('execution_state') or '').strip(),
        'reviewed_by': (warrant.get('reviewed_by') or '').strip(),
        'reviewed_at': (warrant.get('reviewed_at') or '').strip(),
        'target_host_id': (record.get('source_host_id') or '').strip(),
        'target_institution_id': (record.get('source_institution_id') or '').strip(),
        'note': note or warrant.get('review_note', ''),
        'metadata': metadata,
    }


def _existing_execution_job_court_notice(job, *, decision=''):
    metadata = dict((job or {}).get('metadata') or {})
    notice = dict(metadata.get('court_notice') or {})
    if not notice:
        return None
    if decision and (notice.get('decision') or '').strip() != (decision or '').strip():
        return None
    if not (notice.get('envelope_id') or notice.get('receipt_id')):
        return None
    return {
        'message_type': 'court_notice',
        'decision': (notice.get('decision') or '').strip(),
        'envelope_id': (notice.get('envelope_id') or '').strip(),
        'receipt_id': (notice.get('receipt_id') or '').strip(),
        'target_host_id': (notice.get('target_host_id') or '').strip(),
        'target_institution_id': (notice.get('target_institution_id') or '').strip(),
        'sender_warrant_id': (notice.get('sender_warrant_id') or '').strip(),
        'local_warrant_id': (notice.get('local_warrant_id') or '').strip(),
        'sent_at': (notice.get('sent_at') or '').strip(),
        'court_review_state': (notice.get('court_review_state') or '').strip(),
        'response': dict(notice.get('response') or {}),
    }


def _deliver_execution_job_court_notice(bound_org_id, job, warrant, decision, *, actor_id, session_id=None, note=''):
    record = dict(job or {})
    warrant = dict(warrant or {})
    if (record.get('message_type') or '').strip() != 'execution_request':
        return None
    sender_warrant_id = (record.get('sender_warrant_id') or '').strip()
    target_host_id = (record.get('source_host_id') or '').strip()
    target_institution_id = (record.get('source_institution_id') or '').strip()
    if not sender_warrant_id or not target_host_id or not target_institution_id:
        return None

    existing_notice = _existing_execution_job_court_notice(record, decision=decision)
    if existing_notice:
        return {
            'applied': True,
            'reused': True,
            'reason': 'already_sent',
            'court_notice': existing_notice,
            'execution_job': _execution_job_view(bound_org_id, record),
        }

    federated_payload = _execution_job_court_notice_payload(
        record,
        warrant,
        decision,
        note=note,
    )
    delivery, federation_state = _deliver_federation_envelope(
        bound_org_id,
        target_host_id,
        target_institution_id,
        'court_notice',
        payload=federated_payload,
        actor_type='user',
        actor_id=actor_id,
        session_id=session_id or '',
        warrant_id=sender_warrant_id,
        commitment_id='',
    )
    court_notice = {
        'message_type': 'court_notice',
        'decision': (decision or '').strip(),
        'envelope_id': (delivery.get('claims') or {}).get('envelope_id', ''),
        'receipt_id': (delivery.get('receipt') or {}).get('receipt_id', ''),
        'target_host_id': (delivery.get('claims') or {}).get('target_host_id', ''),
        'target_institution_id': (delivery.get('claims') or {}).get('target_institution_id', ''),
        'sender_warrant_id': sender_warrant_id,
        'local_warrant_id': (record.get('local_warrant_id') or '').strip(),
        'court_review_state': (warrant.get('court_review_state') or '').strip(),
        'sent_at': (delivery.get('receipt') or {}).get('accepted_at', '') or _now(),
        'response': dict(delivery.get('response') or {}),
    }
    updated_job = upsert_execution_job(
        bound_org_id,
        job_id=record.get('job_id', ''),
        metadata={
            **dict(record.get('metadata') or {}),
            'court_notice': court_notice,
        },
    )
    log_event(
        bound_org_id,
        actor_id,
        'federation_court_notice_sent',
        resource=record.get('job_id', '') or sender_warrant_id,
        outcome='success',
        actor_type='user',
        details={
            **_federation_audit_details(delivery.get('claims') or {}),
            'local_warrant_id': (record.get('local_warrant_id') or '').strip(),
            'sender_warrant_id': sender_warrant_id,
            'decision': (decision or '').strip(),
        },
        session_id=session_id or None,
    )
    return {
        'applied': True,
        'reused': False,
        'delivery': delivery,
        'court_notice': court_notice,
        'execution_job': _execution_job_view(bound_org_id, updated_job),
        'runtime_core': {
            'federation': federation_state,
        },
    }


def _settlement_notice_ref(claims, receipt, payload=None):
    payload = payload if isinstance(payload, dict) else {}
    execution_refs = payload.get('execution_refs') or {}
    if not isinstance(execution_refs, dict):
        execution_refs = {}
    raw_contract = payload.get('settlement_adapter_contract') or execution_refs.get('settlement_adapter_contract') or {}
    if not isinstance(raw_contract, dict):
        raw_contract = {}
    contract_snapshot = (
        payload.get('settlement_adapter_contract_snapshot')
        or execution_refs.get('settlement_adapter_contract_snapshot')
        or raw_contract.get('contract_snapshot')
        or {}
    )
    if not isinstance(contract_snapshot, dict):
        contract_snapshot = {}
    contract_digest = (
        payload.get('settlement_adapter_contract_digest')
        or execution_refs.get('settlement_adapter_contract_digest')
        or raw_contract.get('contract_digest')
        or ''
    ).strip()
    if contract_snapshot and not contract_digest:
        contract_digest = settlement_adapter_contract_digest(contract_snapshot)
    claim_data = _federation_claims_dict(claims)
    return {
        'proposal_id': (payload.get('proposal_id') or '').strip(),
        'currency': (payload.get('currency') or execution_refs.get('currency') or 'USDC').strip().upper(),
        'tx_ref': (payload.get('tx_ref') or execution_refs.get('tx_ref') or '').strip(),
        'tx_hash': (payload.get('tx_hash') or execution_refs.get('tx_hash') or '').strip(),
        'settlement_adapter': (payload.get('settlement_adapter') or execution_refs.get('settlement_adapter') or '').strip(),
        'proof_type': (payload.get('proof_type') or execution_refs.get('proof_type') or '').strip(),
        'verification_state': (payload.get('verification_state') or execution_refs.get('verification_state') or '').strip(),
        'finality_state': (payload.get('finality_state') or execution_refs.get('finality_state') or '').strip(),
        'warrant_id': claim_data.get('warrant_id', ''),
        'envelope_id': claim_data.get('envelope_id', ''),
        'receipt_id': (receipt or {}).get('receipt_id', ''),
        'source_host_id': claim_data.get('source_host_id', ''),
        'source_institution_id': claim_data.get('source_institution_id', ''),
        'target_host_id': claim_data.get('target_host_id', ''),
        'target_institution_id': claim_data.get('target_institution_id', ''),
        'payload_hash': claim_data.get('payload_hash', ''),
        'proof': payload.get('proof') or execution_refs.get('proof') or {},
        'settlement_adapter_contract': raw_contract,
        'settlement_adapter_contract_snapshot': contract_snapshot,
        'settlement_adapter_contract_digest': contract_digest,
        'recorded_by': claim_data.get('actor_id') or f"peer:{claim_data.get('source_host_id', '')}",
        'recorded_at': (receipt or {}).get('accepted_at', '') or _now(),
    }


def _commitment_federation_ref(claims, receipt, payload=None):
    payload = payload if isinstance(payload, dict) else {}
    claim_data = _federation_claims_dict(claims)
    return {
        'commitment_id': claim_data.get('commitment_id', '') or (payload.get('commitment_id') or '').strip(),
        'message_type': claim_data.get('message_type', ''),
        'envelope_id': claim_data.get('envelope_id', ''),
        'receipt_id': (receipt or {}).get('receipt_id', ''),
        'source_host_id': claim_data.get('source_host_id', ''),
        'source_institution_id': claim_data.get('source_institution_id', ''),
        'target_host_id': claim_data.get('target_host_id', ''),
        'target_institution_id': claim_data.get('target_institution_id', ''),
        'warrant_id': claim_data.get('warrant_id', ''),
        'proposal_id': (payload.get('proposal_id') or '').strip(),
        'commitment_type': (payload.get('commitment_type') or '').strip(),
        'summary': (payload.get('summary') or '').strip(),
        'terms_hash': claim_data.get('payload_hash', ''),
        'recorded_by': claim_data.get('actor_id') or f"peer:{claim_data.get('source_host_id', '')}",
        'recorded_at': (receipt or {}).get('accepted_at', '') or _now(),
    }


def _preflight_received_settlement_notice(bound_org_id, claims, receipt, *, payload=None):
    settlement_ref = _settlement_notice_ref(claims, receipt, payload)
    adapter_id = (settlement_ref.get('settlement_adapter') or '').strip()
    if not adapter_id:
        return settlement_ref, {
            'preflight_ok': False,
            'requested_adapter_id': '',
            'error_type': 'validation_error',
            'error': 'Settlement notice is missing settlement_adapter',
            'currency': settlement_ref.get('currency', 'USDC'),
        }
    host_identity, _admission_registry = _runtime_host_state(bound_org_id)
    settlement_adapter_preflight = preflight_settlement_adapter(
        adapter_id,
        org_id=bound_org_id,
        currency=settlement_ref.get('currency', 'USDC'),
        tx_hash=settlement_ref.get('tx_hash', ''),
        settlement_proof=settlement_ref.get('proof'),
        host_supported_adapters=getattr(host_identity, 'settlement_adapters', []),
    )
    expected_snapshot = dict(settlement_ref.get('settlement_adapter_contract_snapshot') or {})
    expected_digest = (settlement_ref.get('settlement_adapter_contract_digest') or '').strip()
    current_contract = dict(settlement_adapter_preflight.get('contract') or {})
    current_snapshot = dict(
        current_contract.get('contract_snapshot')
        or settlement_adapter_contract_snapshot(current_contract)
    )
    current_digest = (
        current_contract.get('contract_digest')
        or settlement_adapter_contract_digest(current_snapshot)
    ).strip()
    if expected_snapshot and current_snapshot != expected_snapshot:
        settlement_adapter_preflight = dict(settlement_adapter_preflight)
        settlement_adapter_preflight['preflight_ok'] = False
        settlement_adapter_preflight['can_execute_now'] = False
        settlement_adapter_preflight['error_type'] = 'validation_error'
        settlement_adapter_preflight['error'] = (
            f"Settlement notice adapter contract drifted for "
            f"{settlement_ref.get('settlement_adapter', '')!r}"
        )
    elif expected_digest and current_digest and not hmac.compare_digest(expected_digest, current_digest):
        settlement_adapter_preflight = dict(settlement_adapter_preflight)
        settlement_adapter_preflight['preflight_ok'] = False
        settlement_adapter_preflight['can_execute_now'] = False
        settlement_adapter_preflight['error_type'] = 'validation_error'
        settlement_adapter_preflight['error'] = (
            f"Settlement notice adapter contract digest mismatch for "
            f"{settlement_ref.get('settlement_adapter', '')!r}"
        )
    settlement_ref['settlement_adapter_contract'] = current_contract
    settlement_ref['settlement_adapter_contract_snapshot'] = current_snapshot
    settlement_ref['settlement_adapter_contract_digest'] = current_digest
    return settlement_ref, settlement_adapter_preflight


def _validated_settlement_notice_ref(bound_org_id, claims, receipt, *, payload=None):
    settlement_ref, settlement_adapter_preflight = _preflight_received_settlement_notice(
        bound_org_id,
        claims,
        receipt,
        payload=payload,
    )
    adapter_id = (settlement_ref.get('settlement_adapter') or '').strip()
    if not settlement_adapter_preflight.get('preflight_ok'):
        raise ValueError(
            settlement_adapter_preflight.get('error')
            or f"Settlement notice failed adapter preflight for {adapter_id!r}"
        )
    normalized = dict(settlement_adapter_preflight.get('normalized_proof') or {})
    current_contract = dict(settlement_adapter_preflight.get('contract') or {})
    current_snapshot = dict(
        current_contract.get('contract_snapshot')
        or settlement_adapter_contract_snapshot(current_contract)
    )
    current_digest = (
        current_contract.get('contract_digest')
        or settlement_adapter_contract_digest(current_snapshot)
    ).strip()
    settlement_ref['settlement_adapter'] = adapter_id
    settlement_ref['tx_hash'] = normalized.get('tx_hash', settlement_ref.get('tx_hash', ''))
    settlement_ref['proof_type'] = normalized.get('proof_type', settlement_ref.get('proof_type', ''))
    settlement_ref['verification_state'] = normalized.get(
        'verification_state',
        settlement_ref.get('verification_state', ''),
    )
    settlement_ref['finality_state'] = normalized.get(
        'finality_state',
        settlement_ref.get('finality_state', ''),
    )
    settlement_ref['proof'] = normalized.get('proof') or settlement_ref.get('proof') or {}
    settlement_ref['currency'] = settlement_adapter_preflight.get(
        'currency',
        settlement_ref.get('currency', 'USDC'),
    )
    settlement_ref['reversal_or_dispute_capability'] = normalized.get(
        'reversal_or_dispute_capability',
        '',
    )
    settlement_ref['settlement_adapter_contract'] = current_contract
    settlement_ref['settlement_adapter_contract_snapshot'] = current_snapshot
    settlement_ref['settlement_adapter_contract_digest'] = current_digest
    return settlement_ref, settlement_adapter_preflight


def _court_notice_payload_dict(payload):
    payload = payload if isinstance(payload, dict) else {}
    return {
        'court_decision': (payload.get('court_decision') or '').strip(),
        'sender_warrant_id': (payload.get('sender_warrant_id') or payload.get('warrant_id') or '').strip(),
        'local_warrant_id': (payload.get('local_warrant_id') or '').strip(),
        'source_execution_envelope_id': (payload.get('source_execution_envelope_id') or payload.get('execution_envelope_id') or '').strip(),
        'source_execution_job_id': (payload.get('source_execution_job_id') or payload.get('job_id') or '').strip(),
        'source_execution_receipt_id': (payload.get('source_execution_receipt_id') or payload.get('receipt_id') or '').strip(),
        'local_court_review_state': (payload.get('local_court_review_state') or '').strip(),
        'local_execution_state': (payload.get('local_execution_state') or '').strip(),
        'reviewed_by': (payload.get('reviewed_by') or '').strip(),
        'reviewed_at': (payload.get('reviewed_at') or '').strip(),
        'target_host_id': (payload.get('target_host_id') or '').strip(),
        'target_institution_id': (
            payload.get('target_institution_id')
            or payload.get('target_org_id')
            or ''
        ).strip(),
        'note': payload.get('note', ''),
        'metadata': dict(payload.get('metadata') or {}),
    }


def _sender_execution_delivery_ref_for_court_notice(bound_org_id, sender_warrant_id, claims, payload):
    payload = _court_notice_payload_dict(payload)
    sender_warrant_id = (sender_warrant_id or '').strip()
    execution_envelope_id = payload.get('source_execution_envelope_id', '')
    commitment = None
    if claims.commitment_id:
        commitment = commitments.get_commitment(claims.commitment_id, org_id=bound_org_id)
        for ref in reversed(list((commitment or {}).get('delivery_refs') or [])):
            ref = dict(ref or {})
            if (ref.get('message_type') or '').strip() != 'execution_request':
                continue
            if sender_warrant_id and (ref.get('warrant_id') or '').strip() != sender_warrant_id:
                continue
            if execution_envelope_id and (ref.get('envelope_id') or '').strip() != execution_envelope_id:
                continue
            if (ref.get('target_host_id') or '').strip() != (claims.source_host_id or '').strip():
                continue
            if (ref.get('target_institution_id') or '').strip() != (claims.source_institution_id or '').strip():
                continue
            return ref, commitment
    for event in query_events(
        org_id=bound_org_id,
        action='federation_envelope_sent',
        limit=500,
    ):
        if event.get('resource') != 'execution_request':
            continue
        details = dict(event.get('details') or {})
        if sender_warrant_id and (details.get('warrant_id') or '').strip() != sender_warrant_id:
            continue
        if execution_envelope_id and (details.get('envelope_id') or '').strip() != execution_envelope_id:
            continue
        if (details.get('target_host_id') or '').strip() != (claims.source_host_id or '').strip():
            continue
        if (details.get('target_institution_id') or '').strip() != (claims.source_institution_id or '').strip():
            continue
        return {
            'message_type': 'execution_request',
            'envelope_id': details.get('envelope_id', ''),
            'target_host_id': details.get('target_host_id', ''),
            'target_institution_id': details.get('target_institution_id', ''),
            'receipt_id': details.get('receipt_id', ''),
            'receiver_host_id': details.get('receiver_host_id', ''),
            'receiver_institution_id': details.get('receiver_institution_id', ''),
            'warrant_id': details.get('warrant_id', ''),
        }, commitment
    return None, commitment


def _process_received_court_notice(bound_org_id, claims, receipt, *, payload=None):
    payload = _court_notice_payload_dict(payload)
    actor_id = claims.actor_id or f'peer:{claims.source_host_id}'
    decision = payload.get('court_decision', '')
    sender_warrant_id = payload.get('sender_warrant_id') or (claims.warrant_id or '').strip()
    local_warrant_id = payload.get('local_warrant_id', '')
    execution_envelope_id = payload.get('source_execution_envelope_id', '')
    target_host_id = payload.get('target_host_id', '')
    target_institution_id = payload.get('target_institution_id', '')
    note = payload.get('note', '')
    metadata = dict(payload.get('metadata') or {})

    errors = []
    if decision not in ('approve', 'stay', 'revoke'):
        errors.append('court_decision must be one of approve|stay|revoke')
    if not sender_warrant_id:
        errors.append('sender_warrant_id is required')
    if not local_warrant_id:
        errors.append('local_warrant_id is required')
    if not execution_envelope_id:
        errors.append('source_execution_envelope_id is required')
    if not target_host_id:
        errors.append('target_host_id is required')
    if not target_institution_id:
        errors.append('target_institution_id is required')
    if claims.warrant_id and sender_warrant_id != claims.warrant_id:
        errors.append(
            f"court_notice sender_warrant_id {sender_warrant_id!r} does not match envelope warrant_id {claims.warrant_id!r}"
        )
    if target_host_id != claims.target_host_id:
        errors.append(
            f"court_notice target_host_id {target_host_id!r} does not match envelope target_host_id {claims.target_host_id!r}"
        )
    if target_institution_id != claims.target_institution_id:
        errors.append(
            f"court_notice target_institution_id {target_institution_id!r} does not match envelope target_institution_id {claims.target_institution_id!r}"
        )

    warrant = get_warrant(sender_warrant_id, org_id=bound_org_id)
    if not warrant:
        errors.append(f"Sender warrant not found: {sender_warrant_id}")
    elif warrant.get('action_class') != 'federated_execution':
        errors.append(
            f"Sender warrant '{sender_warrant_id}' action_class must be 'federated_execution'"
        )
    elif warrant.get('boundary_name') != 'federation_gateway':
        errors.append(
            f"Sender warrant '{sender_warrant_id}' boundary_name must be 'federation_gateway'"
        )

    delivery_ref, commitment = _sender_execution_delivery_ref_for_court_notice(
        bound_org_id,
        sender_warrant_id,
        claims,
        payload,
    )
    if not delivery_ref:
        errors.append(
            f"No outbound execution_request proof matches sender_warrant_id '{sender_warrant_id}' "
            f"and envelope '{execution_envelope_id}'"
        )

    if errors:
        error = '; '.join(errors)
        log_event(
            bound_org_id,
            actor_id,
            'federation_court_notice_blocked',
            resource=sender_warrant_id or claims.envelope_id,
            outcome='blocked',
            actor_type=claims.actor_type or 'service',
            details=_federation_audit_details(
                claims,
                receipt_id=(receipt or {}).get('receipt_id', ''),
                court_decision=decision,
                sender_warrant_id=sender_warrant_id,
                local_warrant_id=local_warrant_id,
                source_execution_envelope_id=execution_envelope_id,
                error=error,
            ),
            session_id=claims.session_id or None,
        )
        return {
            'applied': False,
            'message_type': claims.message_type,
            'state': 'received',
            'reason': 'invalid_court_notice',
            'error': error,
        }

    if warrant.get('execution_state') == 'executed':
        inbox_entry = _federation_inbox_entry(
            bound_org_id,
            claims,
            receipt,
            payload=payload,
            state='processed',
        )
        return {
            'applied': False,
            'message_type': claims.message_type,
            'state': 'processed',
            'reason': 'warrant_already_executed',
            'warrant': warrant,
            'inbox_entry': inbox_entry,
        }

    reviewed = review_warrant(
        sender_warrant_id,
        decision,
        actor_id,
        org_id=bound_org_id,
        note=note or f"Receiver-side court_notice {decision} from {claims.source_host_id}",
    )
    delivery_record = None
    if claims.commitment_id and commitment:
        commitment = commitments.record_delivery_ref(
            claims.commitment_id,
            {
                'recorded_at': _now(),
                'message_type': 'court_notice',
                'envelope_id': claims.envelope_id,
                'receipt_id': (receipt or {}).get('receipt_id', ''),
                'source_host_id': claims.source_host_id,
                'source_institution_id': claims.source_institution_id,
                'target_host_id': claims.target_host_id,
                'target_institution_id': claims.target_institution_id,
                'warrant_id': sender_warrant_id,
                'local_warrant_id': local_warrant_id,
                'source_execution_envelope_id': execution_envelope_id,
                'source_execution_job_id': payload.get('source_execution_job_id', ''),
                'source_execution_receipt_id': payload.get('source_execution_receipt_id', ''),
                'court_decision': decision,
                'court_review_state': payload.get('local_court_review_state') or reviewed.get('court_review_state', ''),
                'local_execution_state': payload.get('local_execution_state', ''),
                'reviewed_by': payload.get('reviewed_by') or actor_id,
                'reviewed_at': payload.get('reviewed_at') or (receipt or {}).get('accepted_at', '') or _now(),
                'note': note or '',
                'metadata': metadata,
            },
            org_id=bound_org_id,
        )
        delivery_record = dict((commitment.get('delivery_refs') or [])[-1] or {})

    inbox_entry = _federation_inbox_entry(
        bound_org_id,
        claims,
        receipt,
        payload=payload,
        state='processed',
    )
    log_event(
        bound_org_id,
        actor_id,
        'federation_court_notice_applied',
        resource=sender_warrant_id,
        outcome='success',
        actor_type=claims.actor_type or 'service',
        details=_federation_audit_details(
            claims,
            receipt_id=(receipt or {}).get('receipt_id', ''),
            court_decision=decision,
            sender_warrant_id=sender_warrant_id,
            local_warrant_id=local_warrant_id,
            source_execution_envelope_id=execution_envelope_id,
            court_review_state=reviewed.get('court_review_state', ''),
        ),
        session_id=claims.session_id or None,
    )
    return {
        'applied': True,
        'message_type': claims.message_type,
        'state': 'processed',
        'reason': 'court_notice_applied',
        'warrant': reviewed,
        'commitment': commitment,
        'delivery_ref': delivery_record,
        'outbound_execution_ref': dict(delivery_ref or {}),
        'inbox_entry': inbox_entry,
    }


def _process_received_federation_message(bound_org_id, claims, receipt, *, payload=None):
    result = {
        'applied': False,
        'message_type': claims.message_type,
        'state': 'received',
        'reason': 'no_receiver_handler',
    }
    if claims.message_type in (
        'commitment_proposal',
        'commitment_acceptance',
        'commitment_breach_notice',
    ) and claims.commitment_id:
        actor_id = claims.actor_id or f'peer:{claims.source_host_id}'
        commitment_ref = _commitment_federation_ref(claims, receipt, payload)
        try:
            commitment = commitments.mirror_federated_commitment(
                bound_org_id,
                commitment_ref['commitment_id'],
                message_type=claims.message_type,
                source_host_id=claims.source_host_id,
                source_institution_id=claims.source_institution_id,
                target_host_id=claims.target_host_id,
                target_institution_id=claims.target_institution_id,
                actor_id=actor_id,
                warrant_id=claims.warrant_id,
                envelope_id=claims.envelope_id,
                receipt_id=commitment_ref['receipt_id'],
                payload=payload,
                note='Mirrored from received federation envelope',
                metadata={
                    'source_boundary_name': claims.boundary_name,
                    'source_message_type': claims.message_type,
                },
            )
        except (PermissionError, ValueError) as exc:
            error = str(exc)
            log_event(
                bound_org_id,
                actor_id,
                'federation_commitment_mirror_blocked',
                resource=claims.commitment_id,
                outcome='blocked',
                actor_type=claims.actor_type or 'service',
                details=_federation_audit_details(
                    claims,
                    receipt_id=commitment_ref['receipt_id'],
                    error=error,
                ),
                session_id=claims.session_id or None,
            )
            result.update({
                'reason': 'commitment_mirror_blocked',
                'error': error,
            })
            return result
        inbox_entry = _federation_inbox_entry(
            bound_org_id,
            claims,
            receipt,
            payload=payload,
            state='processed',
        )
        if claims.message_type == 'commitment_breach_notice':
            case_record, created = _maybe_open_case_for_commitment_breach(
                commitment,
                actor_id,
                org_id=bound_org_id,
                note='Mirrored from received federation envelope',
            )
            if created:
                log_event(
                    bound_org_id,
                    actor_id,
                    'case_opened',
                    resource=case_record['case_id'],
                    outcome='success',
                    details={
                        'claim_type': case_record.get('claim_type', ''),
                        'linked_commitment_id': case_record.get('linked_commitment_id', ''),
                        'linked_warrant_id': case_record.get('linked_warrant_id', ''),
                    },
                    session_id=claims.session_id or None,
                )
            warrant = _maybe_stay_warrant_for_case(
                case_record,
                actor_id,
                org_id=bound_org_id,
                session_id=claims.session_id or None,
                note='Mirrored from received federation breach notice',
            )
            event_name = 'federation_commitment_breach_notice_applied'
        else:
            case_record = None
            warrant = None
            event_name = (
                'federation_commitment_proposal_applied'
                if claims.message_type == 'commitment_proposal'
                else 'federation_commitment_acceptance_applied'
            )
        log_event(
            bound_org_id,
            actor_id,
            event_name,
            resource=claims.commitment_id,
            outcome='success',
            actor_type=claims.actor_type or 'service',
            details=_federation_audit_details(
                claims,
                receipt_id=commitment_ref['receipt_id'],
                commitment_state=commitment.get('status', ''),
            ),
            session_id=claims.session_id or None,
        )
        result.update({
            'applied': True,
            'state': 'processed',
            'reason': (
                'commitment_proposal_mirrored'
                if claims.message_type == 'commitment_proposal'
                else (
                    'commitment_acceptance_mirrored'
                    if claims.message_type == 'commitment_acceptance'
                    else 'commitment_breach_notice_mirrored'
                )
            ),
            'commitment': commitment,
            'commitment_ref': commitment_ref,
            'inbox_entry': inbox_entry,
        })
        if claims.message_type == 'commitment_breach_notice':
            result['case'] = case_record
            result['warrant'] = warrant
        return result

    if claims.message_type == 'case_notice':
        payload = payload if isinstance(payload, dict) else {}
        actor_id = claims.actor_id or f'peer:{claims.source_host_id}'
        decision = (payload.get('case_decision') or '').strip()
        source_case_id = (payload.get('source_case_id') or '').strip()
        claim_type = (payload.get('claim_type') or '').strip()
        linked_commitment_id = (payload.get('linked_commitment_id') or '').strip()
        linked_warrant_id = (payload.get('linked_warrant_id') or '').strip()
        target_host_id = (payload.get('target_host_id') or '').strip()
        target_institution_id = (
            payload.get('target_institution_id')
            or payload.get('target_org_id')
            or ''
        ).strip()
        note = payload.get('note', '')
        metadata = dict(payload.get('metadata') or {})

        errors = []
        if decision not in ('open', 'stay', 'resolve'):
            errors.append('case_decision must be one of open|stay|resolve')
        if not source_case_id:
            errors.append('source_case_id is required')
        if not claim_type:
            errors.append('claim_type is required')
        if not target_host_id:
            errors.append('target_host_id is required')
        if not target_institution_id:
            errors.append('target_institution_id is required')
        if target_host_id != claims.target_host_id:
            errors.append(
                f"case_notice target_host_id {target_host_id!r} does not match envelope target_host_id {claims.target_host_id!r}"
            )
        if target_institution_id != claims.target_institution_id:
            errors.append(
                f"case_notice target_institution_id {target_institution_id!r} does not match envelope target_institution_id {claims.target_institution_id!r}"
            )
        if errors:
            error = '; '.join(errors)
            log_event(
                bound_org_id,
                actor_id,
                'federation_case_notice_blocked',
                resource=source_case_id or claims.envelope_id,
                outcome='blocked',
                actor_type=claims.actor_type or 'service',
                details=_federation_audit_details(
                    claims,
                    receipt_id=(receipt or {}).get('receipt_id', ''),
                    case_decision=decision,
                    source_case_id=source_case_id,
                    claim_type=claim_type,
                    linked_commitment_id=linked_commitment_id,
                    linked_warrant_id=linked_warrant_id,
                    error=error,
                ),
                session_id=claims.session_id or None,
            )
            result.update({
                'reason': 'invalid_case_notice',
                'error': error,
            })
            return result

        mirrored_case = None
        for row in cases.list_cases(bound_org_id):
            row_metadata = dict(row.get('metadata') or {})
            if (
                row_metadata.get('federation_source_host_id') == claims.source_host_id
                and row_metadata.get('federation_source_institution_id') == claims.source_institution_id
                and row_metadata.get('federation_source_case_id') == source_case_id
            ):
                mirrored_case = dict(row)
                break

        mirrored_target_host_id = claims.source_host_id
        mirrored_target_institution_id = claims.source_institution_id
        mirror_metadata = dict(metadata)
        mirror_metadata.update({
            'source': 'federation_case_notice',
            'federation_message_type': 'case_notice',
            'federation_case_decision': decision,
            'federation_source_host_id': claims.source_host_id,
            'federation_source_institution_id': claims.source_institution_id,
            'federation_source_case_id': source_case_id,
            'federation_notice_target_host_id': target_host_id,
            'federation_notice_target_institution_id': target_institution_id,
            'federation_envelope_id': claims.envelope_id,
            'federation_receipt_id': (receipt or {}).get('receipt_id', ''),
        })

        created = False
        if decision == 'open':
            if mirrored_case:
                mirrored_case.update({
                    'claim_type': claim_type,
                    'target_host_id': mirrored_target_host_id,
                    'target_institution_id': mirrored_target_institution_id,
                    'linked_commitment_id': linked_commitment_id,
                    'linked_warrant_id': linked_warrant_id,
                    'status': 'open',
                    'opened_by': actor_id,
                    'reviewed_by': '',
                    'reviewed_at': '',
                    'review_note': '',
                    'resolution': '',
                    'note': note or mirrored_case.get('note', ''),
                    'metadata': mirror_metadata,
                    'updated_at': _now(),
                })
                store = cases._load_store(bound_org_id)
                store.setdefault('cases', {})[mirrored_case['case_id']] = mirrored_case
                cases._save_store(store, bound_org_id)
            else:
                mirrored_case = cases.open_case(
                    bound_org_id,
                    claim_type,
                    actor_id,
                    target_host_id=mirrored_target_host_id,
                    target_institution_id=mirrored_target_institution_id,
                    linked_commitment_id=linked_commitment_id,
                    linked_warrant_id=linked_warrant_id,
                    note=note,
                    metadata=mirror_metadata,
                )
                created = True
            federation_peer = _maybe_suspend_peer_for_case(
                mirrored_case,
                actor_id,
                org_id=bound_org_id,
                session_id=claims.session_id or None,
            )
            warrant = _maybe_stay_warrant_for_case(
                mirrored_case,
                actor_id,
                org_id=bound_org_id,
                session_id=claims.session_id or None,
                note=note or 'Stayed after received case_notice envelope',
            )
        else:
            if not mirrored_case:
                error = (
                    f"Mirrored case not found for source_case_id '{source_case_id}' "
                    f"(source_host_id={claims.source_host_id!r}, "
                    f"source_institution_id={claims.source_institution_id!r})"
                )
                log_event(
                    bound_org_id,
                    actor_id,
                    'federation_case_notice_blocked',
                    resource=source_case_id,
                    outcome='blocked',
                    actor_type=claims.actor_type or 'service',
                    details=_federation_audit_details(
                        claims,
                        receipt_id=(receipt or {}).get('receipt_id', ''),
                        case_decision=decision,
                        source_case_id=source_case_id,
                        claim_type=claim_type,
                        linked_commitment_id=linked_commitment_id,
                        linked_warrant_id=linked_warrant_id,
                        error=error,
                    ),
                    session_id=claims.session_id or None,
                )
                result.update({
                    'reason': 'case_not_found',
                    'error': error,
                })
                return result
            mirrored_case.update({
                'claim_type': claim_type,
                'target_host_id': mirrored_target_host_id,
                'target_institution_id': mirrored_target_institution_id,
                'linked_commitment_id': linked_commitment_id,
                'linked_warrant_id': linked_warrant_id,
                'status': 'stayed' if decision == 'stay' else 'resolved',
                'reviewed_by': actor_id,
                'reviewed_at': _now(),
                'review_note': note or '',
                'resolution': note or ('resolved' if decision == 'resolve' else ''),
                'note': note or mirrored_case.get('note', ''),
                'metadata': mirror_metadata,
                'updated_at': _now(),
            })
            store = cases._load_store(bound_org_id)
            store.setdefault('cases', {})[mirrored_case['case_id']] = mirrored_case
            cases._save_store(store, bound_org_id)
            if decision == 'stay':
                federation_peer = None
                warrant = _maybe_stay_warrant_for_case(
                    mirrored_case,
                    actor_id,
                    org_id=bound_org_id,
                    session_id=claims.session_id or None,
                    note=note or 'Stayed after received case_notice envelope',
                )
            else:
                federation_peer = _maybe_restore_peer_for_case(
                    mirrored_case,
                    actor_id,
                    org_id=bound_org_id,
                    session_id=claims.session_id or None,
                )
                warrant = None

        inbox_entry = _federation_inbox_entry(
            bound_org_id,
            claims,
            receipt,
            payload=payload,
            state='processed',
        )
        log_event(
            bound_org_id,
            actor_id,
            'federation_case_notice_applied',
            resource=source_case_id,
            outcome='success',
            actor_type=claims.actor_type or 'service',
            details=_federation_audit_details(
                claims,
                receipt_id=(receipt or {}).get('receipt_id', ''),
                case_decision=decision,
                source_case_id=source_case_id,
                claim_type=claim_type,
                linked_commitment_id=linked_commitment_id,
                linked_warrant_id=linked_warrant_id,
                case_id=mirrored_case.get('case_id', ''),
                case_created=created,
                case_status=mirrored_case.get('status', ''),
            ),
            session_id=claims.session_id or None,
        )
        result.update({
            'applied': True,
            'state': 'processed',
            'reason': 'case_notice_applied',
            'case': mirrored_case,
            'case_created': created,
            'federation_peer': federation_peer,
            'warrant': warrant,
            'inbox_entry': inbox_entry,
        })
        return result

    if claims.message_type == 'court_notice':
        return _process_received_court_notice(
            bound_org_id,
            claims,
            receipt,
            payload=payload,
        )

    if claims.message_type == 'execution_request':
        actor_id = claims.actor_id or f'peer:{claims.source_host_id}'
        execution_job, receiver_warrant, blocking_case = _queue_received_execution_request(
            bound_org_id,
            claims,
            receipt,
            payload=payload,
        )
        inbox_state = 'processed'
        note = 'queued_for_local_warrant_review'
        event_name = 'federation_execution_job_created'
        outcome = 'accepted'
        if execution_job.get('state') == 'blocked':
            inbox_state = 'processed'
            note = 'blocked_by_case'
            event_name = 'federation_execution_job_blocked'
            outcome = 'blocked'
        inbox_entry = _federation_inbox_entry(
            bound_org_id,
            claims,
            receipt,
            payload=payload,
            state=inbox_state,
        )
        log_event(
            bound_org_id,
            actor_id,
            event_name,
            resource=execution_job.get('job_id', claims.envelope_id),
            outcome=outcome,
            actor_type=claims.actor_type or 'service',
            details=_federation_audit_details(
                claims,
                receipt_id=(receipt or {}).get('receipt_id', ''),
                execution_job_id=execution_job.get('job_id', ''),
                local_warrant_id=execution_job.get('local_warrant_id', ''),
                job_state=execution_job.get('state', ''),
                reason=note,
            ),
            session_id=claims.session_id or None,
        )
        result.update({
            'applied': True,
            'state': inbox_state,
            'reason': 'execution_job_created' if execution_job.get('state') != 'blocked' else 'case_blocked',
            'execution_job': execution_job,
            'receiver_warrant': receiver_warrant,
            'inbox_entry': inbox_entry,
        })
        if blocking_case:
            result['case'] = blocking_case
        return result

    if claims.message_type != 'settlement_notice' or not claims.commitment_id:
        return result

    actor_id = claims.actor_id or f'peer:{claims.source_host_id}'
    try:
        commitments.validate_commitment_for_settlement(
            claims.commitment_id,
            org_id=bound_org_id,
            warrant_id=claims.warrant_id,
        )
    except PermissionError as exc:
        error = str(exc)
        log_event(
            bound_org_id,
            actor_id,
            'federation_settlement_notice_blocked',
            resource=claims.commitment_id,
            outcome='blocked',
            actor_type=claims.actor_type or 'service',
            details=_federation_audit_details(
                claims,
                receipt_id=(receipt or {}).get('receipt_id', ''),
                error=error,
            ),
            session_id=claims.session_id or None,
        )
        result.update({
            'reason': 'commitment_not_settlement_ready',
            'error': error,
        })
        return result

    case_record, warrant = _maybe_block_commitment_settlement(
        claims.commitment_id,
        actor_id,
        org_id=bound_org_id,
        session_id=claims.session_id or None,
        note='Settlement notice blocked by active case on receiver',
    )
    if case_record:
        log_event(
            bound_org_id,
            actor_id,
            'federation_settlement_notice_blocked',
            resource=claims.commitment_id,
            outcome='blocked',
            actor_type=claims.actor_type or 'service',
            details=_federation_audit_details(
                claims,
                receipt_id=(receipt or {}).get('receipt_id', ''),
                case_id=case_record.get('case_id', ''),
                case_status=case_record.get('status', ''),
                error='linked_case_blocked',
            ),
            session_id=claims.session_id or None,
        )
        result.update({
            'reason': 'case_blocked',
            'case': case_record,
            'warrant': warrant,
        })
        return result

    try:
        settlement_ref, settlement_adapter_preflight = _validated_settlement_notice_ref(
            bound_org_id,
            claims,
            receipt,
            payload=payload,
        )
    except ValueError as exc:
        error = str(exc)
        raw_settlement_ref = _settlement_notice_ref(claims, receipt, payload)
        case_record, created = cases.ensure_case_for_delivery_failure(
            'invalid_settlement_notice',
            actor_id,
            org_id=bound_org_id,
            target_host_id=claims.source_host_id,
            target_institution_id=claims.source_institution_id,
            linked_commitment_id=claims.commitment_id,
            linked_warrant_id=claims.warrant_id,
            note=error,
            metadata={
                'receipt_id': (receipt or {}).get('receipt_id', ''),
                'settlement_adapter': raw_settlement_ref.get('settlement_adapter', ''),
                'payload_hash': claims.payload_hash,
            },
        )
        federation_peer = None
        if case_record:
            federation_peer = _maybe_suspend_peer_for_case(
                case_record,
                actor_id,
                org_id=bound_org_id,
                session_id=claims.session_id or None,
            )
        log_event(
            bound_org_id,
            actor_id,
            'federation_settlement_notice_rejected',
            resource=claims.commitment_id,
            outcome='blocked',
            actor_type=claims.actor_type or 'service',
            details=_federation_audit_details(
                claims,
                receipt_id=(receipt or {}).get('receipt_id', ''),
                error=error,
                case_id=(case_record or {}).get('case_id', ''),
                settlement_adapter=raw_settlement_ref.get('settlement_adapter', ''),
            ),
            session_id=claims.session_id or None,
        )
        settlement_adapter_preflight = _preflight_received_settlement_notice(
            bound_org_id,
            claims,
            receipt,
            payload=payload,
        )[1]
        if not settlement_adapter_preflight.get('error_type'):
            settlement_adapter_preflight = dict(settlement_adapter_preflight)
            settlement_adapter_preflight['error_type'] = 'validation_error'
            settlement_adapter_preflight['error'] = error
        result.update({
            'reason': 'invalid_settlement_notice',
            'error': error,
            'settlement_preflight': None,
            'case': case_record,
            'case_created': created,
            'federation_peer': federation_peer,
            'settlement_adapter_preflight': settlement_adapter_preflight,
        })
        return result

    commitments.record_settlement_ref(
        claims.commitment_id,
        settlement_ref,
        org_id=bound_org_id,
    )
    commitment = commitments.settle_commitment(
        claims.commitment_id,
        actor_id,
        org_id=bound_org_id,
        note='Applied from received settlement_notice envelope',
    )
    sender_warrant = _maybe_finalize_sender_warrant_for_commitment(
        commitment,
        claims,
        receipt,
        settlement_ref,
        org_id=bound_org_id,
        actor_id=actor_id,
        session_id=claims.session_id or None,
    )
    inbox_entry = _federation_inbox_entry(
        bound_org_id,
        claims,
        receipt,
        payload=payload,
        state='processed',
    )
    log_event(
        bound_org_id,
        actor_id,
        'federation_settlement_notice_applied',
        resource=claims.commitment_id,
        outcome='success',
        actor_type=claims.actor_type or 'service',
        details=_federation_audit_details(
            claims,
            receipt_id=(receipt or {}).get('receipt_id', ''),
            proposal_id=settlement_ref.get('proposal_id', ''),
            tx_ref=settlement_ref.get('tx_ref', ''),
            settlement_adapter=settlement_ref.get('settlement_adapter', ''),
            currency=settlement_ref.get('currency', ''),
        ),
        session_id=claims.session_id or None,
    )
    result.update({
        'applied': True,
        'state': 'processed',
        'reason': 'settlement_notice_applied',
        'commitment': commitment,
        'settlement_ref': settlement_ref,
        'settlement_adapter_preflight': settlement_adapter_preflight,
        'inbox_entry': inbox_entry,
        'warrant': sender_warrant,
    })
    return result


def _federation_peer_state(peer_host_id, *, host_identity=None):
    peer_host_id = (peer_host_id or '').strip()
    if not peer_host_id:
        return None
    try:
        registry = load_peer_registry(
            FEDERATION_PEERS_FILE,
            host_identity=host_identity or load_host_identity(RUNTIME_HOST_IDENTITY_FILE),
        )
    except RuntimeError:
        return {
            'applied': False,
            'peer_host_id': peer_host_id,
            'reason': 'peer_registry_unavailable',
        }
    peer = registry.get('peers', {}).get(peer_host_id)
    if not peer:
        return {
            'applied': False,
            'peer_host_id': peer_host_id,
            'reason': 'peer_not_registered',
        }
    return {
        'applied': False,
        'peer_host_id': peer.host_id,
        'trust_state': peer.trust_state,
        'admitted_org_ids': list(peer.admitted_org_ids),
        'label': peer.label,
        'reason': 'case_blocked',
    }


def _validate_witness_peer_manifest(peer, manifest):
    if not isinstance(manifest, dict):
        raise FederationDeliveryError(
            f"Peer host '{peer.host_id}' returned a non-object witness manifest",
            peer_host_id=peer.host_id,
            response=manifest,
        )
    host_identity = manifest.get('host_identity', {}) or {}
    if host_identity.get('host_id') != peer.host_id:
        raise FederationDeliveryError(
            f"Peer manifest host_id '{host_identity.get('host_id', '')}' does not match "
            f"witness peer '{peer.host_id}'",
            peer_host_id=peer.host_id,
            response=manifest,
        )
    if host_identity.get('role') != 'witness_host':
        raise FederationDeliveryError(
            f"Peer host '{peer.host_id}' does not advertise witness_host role",
            peer_host_id=peer.host_id,
            response=manifest,
        )
    archive = manifest.get('witness_archive', {}) or {}
    if not archive.get('archive_enabled'):
        raise FederationDeliveryError(
            f"Peer host '{peer.host_id}' does not advertise enabled witness archive",
            peer_host_id=peer.host_id,
            response=manifest,
        )
    if archive.get('host_id') and archive.get('host_id') != peer.host_id:
        raise FederationDeliveryError(
            f"Peer host '{peer.host_id}' witness archive host_id "
            f"{archive.get('host_id', '')!r} does not match peer host",
            peer_host_id=peer.host_id,
            response=manifest,
        )
    return manifest


def _archive_delivery_with_witness_peers(bound_org_id, authority, delivery, payload, *,
                                         actor_id='', session_id=None,
                                         host_identity=None):
    host_identity = host_identity or authority.host_identity
    claims = dict(delivery.get('claims') or {})
    receipt = dict(delivery.get('receipt') or {})
    if not claims or not receipt:
        return {
            'attempted': 0,
            'created': 0,
            'existing': 0,
            'failed': 0,
            'records': [],
        }

    peer_registry = getattr(authority, 'peer_registry', {}) or {}
    peer_registry = peer_registry.get('peers', {}) or {}
    target_host_id = (claims.get('target_host_id') or '').strip()
    results = []
    for peer_host_id in sorted(peer_registry):
        peer = peer_registry.get(peer_host_id)
        if not isinstance(peer, FederationPeer):
            continue
        if peer.trust_state != 'trusted':
            continue
        if peer.host_id in (host_identity.host_id, target_host_id):
            continue
        if not peer.endpoint_url:
            continue

        try:
            witness_peer, witness_manifest = authority.fetch_peer_manifest(peer.host_id)
            witness_manifest = _validate_witness_peer_manifest(witness_peer, witness_manifest)
            request = urllib_request.Request(
                witness_peer.endpoint_url + '/api/federation/witness/archive',
                data=json.dumps({
                    'envelope': delivery.get('envelope', ''),
                    'payload': payload,
                    'receipt': receipt,
                }).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urllib_request.urlopen(request, timeout=10) as response:
                archive_response = json.loads(response.read().decode('utf-8') or '{}')
            archive_record = archive_response.get('archive') or {}
            if not isinstance(archive_record, dict) or not archive_record.get('archive_id'):
                raise FederationDeliveryError(
                    f"Peer host '{witness_peer.host_id}' returned an invalid witness archive response",
                    peer_host_id=witness_peer.host_id,
                    response=archive_response,
                )
            created = bool(archive_response.get('created'))
            result = {
                'peer_host_id': witness_peer.host_id,
                'peer_label': witness_peer.label,
                'archived': True,
                'created': created,
                'archive_id': archive_record.get('archive_id', ''),
                'message_type': archive_record.get('message_type', ''),
            }
            log_event(
                bound_org_id,
                actor_id or f'host:{host_identity.host_id}',
                'federation_witness_archive_sent',
                resource=claims.get('message_type', ''),
                outcome='success',
                actor_type=claims.get('actor_type') or 'service',
                details={
                    'witness_host_id': witness_peer.host_id,
                    'target_host_id': target_host_id,
                    'target_institution_id': claims.get('target_institution_id', ''),
                    'archive_id': archive_record.get('archive_id', ''),
                    'created': created,
                    'receipt_id': receipt.get('receipt_id', ''),
                },
                session_id=session_id or None,
            )
        except Exception as exc:
            result = {
                'peer_host_id': peer.host_id,
                'peer_label': peer.label,
                'archived': False,
                'created': False,
                'error': str(exc),
            }
            log_event(
                bound_org_id,
                actor_id or f'host:{host_identity.host_id}',
                'federation_witness_archive_failed',
                resource=claims.get('message_type', ''),
                outcome='blocked',
                actor_type=claims.get('actor_type') or 'service',
                details={
                    'witness_host_id': peer.host_id,
                    'target_host_id': target_host_id,
                    'target_institution_id': claims.get('target_institution_id', ''),
                    'error': str(exc),
                },
                session_id=session_id or None,
            )
        results.append(result)

    attempted = len(results)
    created = sum(1 for row in results if row.get('created'))
    failed = sum(1 for row in results if not row.get('archived'))
    existing = sum(
        1 for row in results
        if row.get('archived') and not row.get('created')
    )
    return {
        'attempted': attempted,
        'created': created,
        'existing': existing,
        'failed': failed,
        'records': results,
    }


def _case_record_by_id(bound_org_id, case_id):
    case_id = (case_id or '').strip()
    if not case_id:
        return None
    for row in cases.list_cases(bound_org_id):
        if (row.get('case_id') or '').strip() == case_id:
            return row
    return None


def _case_notice_delivery_context(case_record, body):
    body = body if isinstance(body, dict) else {}
    case_record = dict(case_record or {})
    target_host_id = (
        body.get('target_host_id')
        or case_record.get('target_host_id')
        or ''
    ).strip()
    target_institution_id = (
        body.get('target_institution_id')
        or body.get('target_org_id')
        or case_record.get('target_institution_id')
        or case_record.get('target_org_id')
        or ''
    ).strip()
    return target_host_id, target_institution_id


def _deliver_case_notice(bound_org_id, case_record, decision, *, actor_id, session_id=None,
                         body=None):
    body = body if isinstance(body, dict) else {}
    target_host_id, target_institution_id = _case_notice_delivery_context(case_record, body)
    if not target_host_id:
        raise ValueError(
            f"Case '{(case_record or {}).get('case_id', '')}' does not declare target_host_id for federated case_notice dispatch"
        )
    if not target_institution_id:
        raise ValueError(
            f"Case '{(case_record or {}).get('case_id', '')}' does not declare target_institution_id for federated case_notice dispatch"
        )
    federated_payload = {
        'case_decision': decision,
        'source_case_id': case_record.get('case_id', ''),
        'claim_type': case_record.get('claim_type', ''),
        'linked_commitment_id': case_record.get('linked_commitment_id', ''),
        'linked_warrant_id': case_record.get('linked_warrant_id', ''),
        'target_host_id': target_host_id,
        'target_institution_id': target_institution_id,
        'note': body.get('note', ''),
        'metadata': dict(case_record.get('metadata') or body.get('metadata') or {}),
    }
    delivery, federation_state = _deliver_federation_envelope(
        bound_org_id,
        target_host_id,
        target_institution_id,
        'case_notice',
        payload=federated_payload,
        actor_type='user',
        actor_id=actor_id,
        session_id=session_id or '',
    )
    return {
        'delivery': delivery,
        'runtime_core': {
            'federation': federation_state,
        },
    }


def _deliver_federation_envelope(bound_org_id, target_host_id, target_org_id,
                                 message_type, payload=None, *,
                                 actor_type='host_service', actor_id='',
                                 session_id='', warrant_id='',
                                 commitment_id='', ttl_seconds=None):
    host_identity, admission_registry = _runtime_host_state(bound_org_id)
    authority = _federation_authority(host_identity)
    authority.ensure_enabled()
    execution_warrant = None
    required_action = warrant_action_for_message(message_type)
    if required_action:
        if not warrant_id:
            message = (
                f"Federation message_type '{message_type}' requires warrant_id "
                f"for action_class '{required_action}'"
            )
            log_event(
                bound_org_id,
                actor_id or f'host:{host_identity.host_id}',
                'federation_warrant_blocked',
                resource=message_type,
                outcome='blocked',
                actor_type=actor_type or 'service',
                details={
                    'target_host_id': target_host_id,
                    'target_institution_id': target_org_id,
                    'required_action_class': required_action,
                    'error': message,
                },
                session_id=session_id or None,
            )
            raise PermissionError(message)
        try:
            execution_warrant = validate_warrant_for_execution(
                warrant_id,
                org_id=bound_org_id,
                action_class=required_action,
                boundary_name='federation_gateway',
                actor_id=actor_id,
                session_id=session_id,
                request_payload=payload,
            )
        except PermissionError as exc:
            log_event(
                bound_org_id,
                actor_id or f'host:{host_identity.host_id}',
                'federation_warrant_blocked',
                resource=message_type,
                outcome='blocked',
                actor_type=actor_type or 'service',
                details={
                    'target_host_id': target_host_id,
                    'target_institution_id': target_org_id,
                    'warrant_id': warrant_id,
                    'required_action_class': required_action,
                    'error': str(exc),
                },
                session_id=session_id or None,
            )
            raise
    commitment_record = None
    if message_type == 'commitment_breach_notice' and not commitment_id:
        message = "Federation message_type 'commitment_breach_notice' requires commitment_id"
        log_event(
            bound_org_id,
            actor_id or f'host:{host_identity.host_id}',
            'federation_commitment_blocked',
            resource=message_type,
            outcome='blocked',
            actor_type=actor_type or 'service',
            details={
                'target_host_id': target_host_id,
                'target_institution_id': target_org_id,
                'error': message,
            },
            session_id=session_id or None,
        )
        raise ValueError(message)
    if commitment_id:
        try:
            if message_type == 'commitment_breach_notice':
                commitment_record = commitments.validate_commitment_for_breach_notice(
                    commitment_id,
                    target_host_id=target_host_id,
                    target_institution_id=target_org_id,
                    org_id=bound_org_id,
                    warrant_id=warrant_id,
                )
            else:
                commitment_record = commitments.validate_commitment_for_delivery(
                    commitment_id,
                    target_host_id=target_host_id,
                    target_institution_id=target_org_id,
                    org_id=bound_org_id,
                    warrant_id=warrant_id,
                )
        except (PermissionError, ValueError) as exc:
            log_event(
                bound_org_id,
                actor_id or f'host:{host_identity.host_id}',
                'federation_commitment_blocked',
                resource=message_type,
                outcome='blocked',
                actor_type=actor_type or 'service',
                details={
                    'target_host_id': target_host_id,
                    'target_institution_id': target_org_id,
                    'commitment_id': commitment_id,
                    'error': str(exc),
                },
                session_id=session_id or None,
            )
            raise
    blocking_case = _blocking_case_for_delivery(
        org_id=bound_org_id,
        commitment_id=commitment_id,
        target_host_id=target_host_id,
        message_type=message_type,
    )
    if blocking_case:
        message = (
            f"Federation delivery is blocked by case '{blocking_case.get('case_id', '')}' "
            f"(claim_type={blocking_case.get('claim_type', '')}, "
            f"status={blocking_case.get('status', '')})"
        )
        log_event(
            bound_org_id,
            actor_id or f'host:{host_identity.host_id}',
            'federation_case_blocked',
            resource=message_type,
            outcome='blocked',
            actor_type=actor_type or 'service',
            details={
                'target_host_id': target_host_id,
                'target_institution_id': target_org_id,
                'commitment_id': commitment_id,
                'case_id': blocking_case.get('case_id', ''),
                'claim_type': blocking_case.get('claim_type', ''),
                'case_status': blocking_case.get('status', ''),
                'error': message,
            },
            session_id=session_id or None,
        )
        error = PermissionError(message)
        error.case_record = blocking_case
        error.federation_peer = _federation_peer_state(
            target_host_id,
            host_identity=host_identity,
        )
        error.warrant = _maybe_stay_warrant_for_case(
            blocking_case,
            actor_id or f'host:{host_identity.host_id}',
            org_id=bound_org_id,
            session_id=session_id or None,
            note=message,
        )
        raise error
    try:
        delivery = authority.deliver(
            target_host_id,
            bound_org_id,
            target_org_id,
            message_type,
            payload=payload,
            actor_type=actor_type,
            actor_id=actor_id,
            session_id=session_id,
            warrant_id=warrant_id,
            commitment_id=commitment_id,
            ttl_seconds=ttl_seconds,
        )
    except FederationDeliveryError as exc:
        case_record, federation_peer = _maybe_open_case_for_delivery_failure(
            exc,
            actor_id or f'host:{host_identity.host_id}',
            org_id=bound_org_id,
            target_host_id=target_host_id,
            target_institution_id=target_org_id,
            commitment_id=commitment_id,
            warrant_id=warrant_id,
            session_id=session_id or None,
        )
        warrant_hold = _maybe_stay_warrant_for_case(
            case_record,
            actor_id or f'host:{host_identity.host_id}',
            org_id=bound_org_id,
            session_id=session_id or None,
            note=str(exc),
        )
        log_event(
            bound_org_id,
            actor_id or f'host:{host_identity.host_id}',
            'federation_envelope_delivery_failed',
            resource=message_type,
            outcome='failed',
            actor_type=actor_type or 'service',
            details=_federation_audit_details(
                exc.claims,
                target_host_id=exc.peer_host_id or target_host_id,
                target_institution_id=target_org_id,
                error=str(exc),
            ),
            session_id=session_id or None,
        )
        exc.case_record = case_record
        exc.federation_peer = federation_peer
        exc.warrant = warrant_hold
        raise

    claims = delivery.get('claims')
    receipt = dict(delivery.get('receipt') or {})
    if not receipt and isinstance(delivery.get('response'), dict):
        receipt = dict(delivery['response'].get('receipt') or {})
    commitment_delivery_ref = None
    if commitment_record:
        commitment_delivery_ref = commitments.record_delivery_ref(
            commitment_record['commitment_id'],
            {
                'delivered_at': _now(),
                'target_host_id': target_host_id,
                'target_institution_id': target_org_id,
                'message_type': message_type,
                'peer_transport': (delivery.get('peer') or {}).get('transport', ''),
                'envelope_id': (claims or {}).get('envelope_id', ''),
                'receipt_id': receipt.get('receipt_id', ''),
                'receiver_host_id': receipt.get('receiver_host_id', ''),
                'receiver_institution_id': receipt.get('receiver_institution_id', ''),
                'actor_id': actor_id or f'host:{host_identity.host_id}',
                'session_id': session_id or '',
                'warrant_id': warrant_id or '',
            },
            org_id=bound_org_id,
        )
        log_event(
            bound_org_id,
            actor_id or f'host:{host_identity.host_id}',
            'commitment_delivery_recorded',
            resource=commitment_record['commitment_id'],
            outcome='success',
            actor_type=actor_type or 'service',
            details={
                'target_host_id': target_host_id,
                'target_institution_id': target_org_id,
                'message_type': message_type,
                'receipt_id': receipt.get('receipt_id', ''),
            },
            session_id=session_id or None,
        )
    if execution_warrant and not commitment_record:
        mark_warrant_executed(
            warrant_id,
            org_id=bound_org_id,
            execution_refs={
                'message_type': message_type,
                'envelope_id': (claims or {}).get('envelope_id', ''),
                'target_host_id': target_host_id,
                'target_institution_id': target_org_id,
                'receipt_id': receipt.get('receipt_id', ''),
                'receiver_host_id': receipt.get('receiver_host_id', ''),
                'receiver_institution_id': receipt.get('receiver_institution_id', ''),
            },
        )
    witness_archive = _archive_delivery_with_witness_peers(
        bound_org_id,
        authority,
        delivery,
        payload,
        actor_id=actor_id or f'host:{host_identity.host_id}',
        session_id=session_id,
        host_identity=host_identity,
    )
    delivery['witness_archive'] = witness_archive
    log_event(
        bound_org_id,
        actor_id or f'host:{host_identity.host_id}',
        'federation_envelope_sent',
        resource=message_type,
        outcome='accepted',
        actor_type=actor_type or 'service',
        details=_federation_audit_details(
            claims,
            peer_transport=(delivery.get('peer') or {}).get('transport', ''),
            receipt_id=receipt.get('receipt_id', ''),
            receiver_host_id=receipt.get('receiver_host_id', ''),
            receiver_institution_id=receipt.get('receiver_institution_id', ''),
            commitment_delivery_recorded=bool(commitment_delivery_ref),
            witness_archive_attempted=witness_archive.get('attempted', 0),
            witness_archive_created=witness_archive.get('created', 0),
            witness_archive_failed=witness_archive.get('failed', 0),
        ),
        session_id=session_id or None,
    )
    return delivery, authority.snapshot(
        bound_org_id=bound_org_id,
        admission_registry=admission_registry,
    )


def _requested_org_override(parsed_url, headers):
    query_org_ids = [value for value in parse_qs(parsed_url.query).get('org_id', []) if value]
    header_org_id = (headers.get('X-Meridian-Org-Id', '') or '').strip()
    requested = set(query_org_ids + ([header_org_id] if header_org_id else []))
    if not requested:
        return None
    if len(requested) > 1:
        raise ValueError('Conflicting institution context hints in request')
    return requested.pop()


def _enforce_request_context(parsed_url, headers, bound_org_id):
    requested_org_id = _requested_org_override(parsed_url, headers)
    if requested_org_id and requested_org_id != bound_org_id:
        raise ValueError(
            f"Workspace is bound to institution '{bound_org_id}'. "
            f"Request-level override '{requested_org_id}' is not allowed."
        )
    return {
        'mode': 'process_bound',
        'bound_org_id': bound_org_id,
        'request_override': 'exact-match-only',
        'requested_org_id': requested_org_id,
    }


def _resolve_auth_context(bound_org_id):
    user, password, credential_org_id, credential_user_id = _load_workspace_credentials()
    auth_enabled = bool(user and password)
    if credential_org_id and auth_enabled and credential_org_id != bound_org_id:
        raise RuntimeError(
            f"Live workspace credentials must scope to bound org '{bound_org_id}', got '{credential_org_id}'"
        )
    resolved_user_id = None
    actor_source = None
    if credential_user_id:
        resolved_user_id = _canonical_meridian_user_id(credential_user_id)
        actor_source = 'credentials'
    elif user and _member_role(bound_org_id, user):
        resolved_user_id = _canonical_meridian_user_id(user)
        actor_source = 'basic_user_id'
    elif user == 'owner':
        org = load_orgs().get('organizations', {}).get(bound_org_id)
        owner_id = _canonical_meridian_user_id((org or {}).get('owner_id'))
        if owner_id:
            resolved_user_id = owner_id
            actor_source = 'owner_alias'
    role = _member_role(bound_org_id, resolved_user_id)
    actor_id = resolved_user_id or (f'workspace_user:{user}' if user else None)
    if not auth_enabled:
        return {
            'enabled': False,
            'mode': 'required_missing' if WORKSPACE_AUTH_REQUIRED else 'disabled',
            'org_id': None,
            'user_id': None,
            'role': None,
            'actor_id': None,
            'actor_source': None,
        }
    if credential_org_id:
        return {
            'enabled': True,
            'mode': 'credential_bound',
            'org_id': credential_org_id,
            'user_id': resolved_user_id,
            'role': role,
            'actor_id': actor_id,
            'actor_source': actor_source or 'credentials',
        }
    return {
        'enabled': True,
        'mode': 'process_bound_basic',
        'org_id': bound_org_id,
        'user_id': resolved_user_id,
        'role': role,
        'actor_id': actor_id,
        'actor_source': actor_source or 'basic_user',
    }


def _resolve_auth_context_from_session(claims, bound_org_id):
    """Build auth context from validated session claims.

    The session records the role at issuance, but we re-check live membership
    so that removed or downgraded members lose access immediately.
    """
    if claims.org_id != bound_org_id:
        raise ValueError(
            f"Session is bound to institution '{claims.org_id}', "
            f"but workspace is bound to '{bound_org_id}'"
        )
    canonical_user_id = _canonical_meridian_user_id(claims.user_id)
    current_role = _member_role(bound_org_id, canonical_user_id)
    return {
        'enabled': True,
        'mode': 'session_bound',
        'org_id': bound_org_id,
        'user_id': canonical_user_id,
        'role': current_role,
        'actor_id': canonical_user_id,
        'actor_source': 'session',
        'session_id': claims.session_id,
    }


def _member_role(org_id, user_id):
    canonical_user_id = _canonical_meridian_user_id(user_id)
    if not org_id or not canonical_user_id:
        return None
    org = load_orgs().get('organizations', {}).get(org_id)
    if not org:
        return None
    for member in org.get('members', []):
        if _canonical_meridian_user_id(member.get('user_id')) == canonical_user_id:
            return member.get('role')
    return None


def _required_mutation_role(path):
    return MUTATION_ROLE_REQUIREMENTS.get(path, 'admin')


def _enforce_mutation_authorization(auth_context, org_id, path):
    if not auth_context.get('enabled'):
        raise PermissionError('Workspace auth is required for mutations')
    role = auth_context.get('role')
    if not role:
        raise PermissionError(
            f"Workspace credential actor is not a member of institution '{org_id}'"
        )
    required_role = _required_mutation_role(path)
    if ROLE_RANK.get(role, -1) < ROLE_RANK.get(required_role, 99):
        raise PermissionError(
            f"Workspace actor role '{role}' cannot mutate '{path}'; requires {required_role}"
        )
    return required_role


def _permission_snapshot(auth_context):
    role = auth_context.get('role')
    permissions = {}
    for path, required_role in MUTATION_ROLE_REQUIREMENTS.items():
        permissions[path] = {
            'required_role': required_role,
            'allowed': bool(
                auth_context.get('enabled')
                and role
                and ROLE_RANK.get(role, -1) >= ROLE_RANK.get(required_role, 99)
            ),
        }
    return {
        'read_allowed': bool(auth_context.get('enabled') or not WORKSPACE_AUTH_REQUIRED),
        'mutation_paths': permissions,
    }


def _list_warrants_compat(
    org_id,
    *,
    action_class=None,
    review_state=None,
    execution_state=None,
    include_archived=True,
    archived_only=False,
    expired_only=False,
):
    """Call list_warrants across old/new signatures and normalize filters."""
    try:
        return list_warrants(
            org_id,
            action_class=action_class,
            review_state=review_state,
            execution_state=execution_state,
            include_archived=include_archived,
            archived_only=archived_only,
            expired_only=expired_only,
        )
    except TypeError:
        try:
            warrants = list_warrants(
                org_id,
                action_class=action_class,
                review_state=review_state,
                execution_state=execution_state,
            )
        except TypeError:
            warrants = list_warrants(org_id)
        if action_class:
            warrants = [w for w in warrants if w.get('action_class') == action_class]
        if review_state:
            warrants = [w for w in warrants if w.get('court_review_state') == review_state]
        if execution_state:
            warrants = [w for w in warrants if w.get('execution_state') == execution_state]
        if expired_only:
            warrants = [w for w in warrants if bool(w.get('expired'))]
        elif archived_only:
            warrants = [w for w in warrants if bool(w.get('archived'))]
        elif not include_archived:
            warrants = [w for w in warrants if not bool(w.get('archived'))]
        warrants.sort(key=lambda row: row.get('issued_at', ''), reverse=True)
        return warrants


def _warrant_summary(org_id, *, include_archived=True, archived_only=False, expired_only=False):
    warrants = _list_warrants_compat(
        org_id,
        include_archived=include_archived,
        archived_only=archived_only,
        expired_only=expired_only,
    )
    all_warrants = _list_warrants_compat(org_id, include_archived=True)
    pending_review = 0
    executable = 0
    executed = 0
    expired_ready = 0
    for record in warrants:
        if record.get('court_review_state') == 'pending_review':
            pending_review += 1
        if (
            record.get('court_review_state') in ('auto_issued', 'approved')
            and record.get('execution_state') == 'ready'
            and not bool(record.get('expired'))
        ):
            executable += 1
        if record.get('execution_state') == 'ready' and bool(record.get('expired')):
            expired_ready += 1
        if record.get('execution_state') == 'executed':
            executed += 1
    return {
        'total': len(warrants),
        'pending_review': pending_review,
        'executable': executable,
        'executed': executed,
        'expired_ready': expired_ready,
        'archived_count': len([record for record in all_warrants if bool(record.get('archived'))]),
    }


# ── API data builders ────────────────────────────────────────────────────────

def api_status(context_source='founding_default', institution_context=None):
    if institution_context is not None:
        inst_ctx = institution_context
    else:
        inst_ctx = _resolve_workspace_context()
    org_id = inst_ctx.org_id
    org = inst_ctx.org
    context_source = inst_ctx.context_source
    host_identity, admission_registry = _runtime_host_state(org_id)
    auth_context = _resolve_auth_context(org_id)
    reg = load_registry()
    queue = _load_queue(org_id)
    snap = treasury_snapshot(
        org_id,
        host_supported_adapters=getattr(host_identity, 'settlement_adapters', []),
    )
    phase_num, phase_details = _phase_mod.evaluate(org_id)
    records = _load_records(org_id)
    lead_id, lead_auth = get_sprint_lead(org_id)

    agents = []
    agent_runtime_bindings = []
    remediations = []
    for a in reg['agents'].values():
        if a.get('org_id') not in (None, '', org_id):
            continue
        a = normalize_agent_record(a)
        restrictions = get_restrictions(a.get('economy_key', a['name'].lower()), org_id=org_id)
        remediation = get_agent_remediation(a.get('economy_key', a['name'].lower()), reg, org_id=org_id)
        if remediation:
            remediations.append(remediation)
        agents.append({
            'id': a['id'], 'name': a['name'], 'role': a['role'],
            'purpose': a['purpose'],
            'rep': a['reputation_units'], 'auth': a['authority_units'],
            'risk_state': a.get('risk_state', 'nominal'),
            'lifecycle_state': a.get('lifecycle_state', 'active'),
            'economy_key': a.get('economy_key'),
            'incident_count': a.get('incident_count', 0),
            'restrictions': restrictions,
            'is_sprint_lead': a.get('economy_key') == lead_id,
            'remediation': remediation,
            'runtime_binding': a.get('runtime_binding', {}),
        })
        agent_runtime_bindings.append({
            'agent_id': a['id'],
            'agent_name': a['name'],
            'role': a['role'],
            **dict(a.get('runtime_binding') or {}),
        })

    open_violations = [
        v for v in records['violations'].values()
        if v['status'] in ('open', 'sanctioned', 'appealed') and v.get('org_id') in (None, '', org_id)
    ]
    pending_appeals = [
        a for a in records['appeals'].values()
        if a['status'] == 'pending' and a.get('org_id') in (None, '', org_id)
    ]
    pending_approvals = get_pending_approvals(org_id=org_id)
    active_delegations = [
        d for d in queue['delegations'].values()
        if d.get('expires_at', '') > _now() and d.get('org_id') in (None, '', org_id)
    ]

    observability = status_surface.observability_snapshot(org_id)
    alert_queue = observability.get('alert_queue', {}) if isinstance(observability, dict) else {}
    slo = observability.get('slo', {}) if isinstance(observability, dict) else {}

    result = {
        'runtime_id': 'loom_native',
        'slo': slo,
        'queue_count': int(alert_queue.get('queue_count', 0) or 0),
        'pending_delivery_count': int(alert_queue.get('pending_delivery_count', 0) or 0),
        'delivered_count': int(alert_queue.get('delivered_count', 0) or 0),
        'proof_mode': 'live_host_runtime_probe',
        'constitutional_model': constitutional_model(),
        'context': {
            'mode': 'process_bound',
            'bound_org_id': org_id,
            'source': context_source,
            'request_override': 'exact-match-only',
            'auth': auth_context,
            'permissions': _permission_snapshot(auth_context),
        },
        'runtime_core': runtime_core_snapshot(
            inst_ctx,
            additional_institutions_allowed=False,
            second_institution_path=(
                'Live runtime remains founding-only. Admitting a second institution '
                'requires a new runtime program; this deployment does not expose '
                'shared multi-institution routing.'
            ),
            host_identity=host_identity,
            admission_registry=admission_registry,
            admission_management_mode=_admission_management_state(host_identity)['management_mode'],
            admission_mutation_enabled=_admission_management_state(host_identity)['mutation_enabled'],
            admission_mutation_disabled_reason=_admission_management_state(host_identity)['mutation_disabled_reason'],
        ),
        'institution': {
            'id': org_id,
            'name': org.get('name', ''),
            'slug': org.get('slug', ''),
            'charter': org.get('charter', ''),
            'lifecycle_state': org.get('lifecycle_state', 'active'),
            'policy_defaults': org.get('policy_defaults', {}),
            'plan': org.get('plan', ''),
            'owner_id': _canonical_meridian_user_id(org.get('owner_id', '')),
            'state_capsule': os.path.relpath(capsule_dir(org_id), WORKSPACE) if org_id else None,
            'treasury_id': org.get('treasury_id'),
        } if org else None,
        'agents': agents,
        'agent_runtime_bindings': agent_runtime_bindings,
        'authority': {
            'kill_switch': queue['kill_switch'],
            'pending_approvals': pending_approvals,
            'active_delegations': active_delegations,
            'sprint_lead': _public_sprint_lead(lead_id, lead_auth, reg=reg),
        },
        'treasury': snap,
        'phase_machine': {
            'number': phase_num,
            'name': phase_details['name'],
            'next_phase': phase_details.get('next_phase'),
            'next_phase_name': phase_details.get('next_phase_name'),
            'next_unlock': phase_details.get('next_unlock'),
        },
        'court': {
            'open_violations': open_violations,
            'pending_appeals': pending_appeals,
            'total_violations': len(records['violations']),
            'total_appeals': len(records['appeals']),
        },
        'warrants': _warrant_summary(org_id, include_archived=False),
        'commitments': _commitment_snapshot(org_id),
        'cases': _case_snapshot(org_id),
        'service_state': {
            'subscriptions': service_state.subscription_snapshot(org_id),
            'subscription_preview': service_state.subscription_preview_snapshot(org_id),
            'accounting': service_state.accounting_snapshot(org_id),
            'pilot_intake': service_state.pilot_intake_snapshot(org_id),
        },
        'persistence': status_surface.persistence_snapshot(org_id),
        'observability': observability,
        'runtime_proof': {
            'route': '/api/runtime-proof',
            'contract_route': '/api/runtime-proof-contract',
            'kernel_bundle_route': '/api/kernel-proof-bundle',
            'runtime_id': 'loom_native',
            'proof_mode': 'live_host_runtime_probe',
            'contract_version': 'runtime_proof_contract_v1',
            'runtime_proof_status': 'route_available',
            'channel_surface_status': 'bounded_live_host_surfaces',
            'trust_ops_status': 'governed_trust_ops_surface',
            'proof_path': '/api/status -> /api/runtime-proof -> /api/runtime-proof-contract -> /api/kernel-proof-bundle',
        },
        'ci_vertical': _ci_vertical_status(reg, lead_id, org_id),
        'remediations': remediations,
        'timestamp': _now(),
    }
    result['runtime_core']['federation'] = _federation_snapshot(
        org_id,
        host_identity=host_identity,
        admission_registry=admission_registry,
    )
    return result


def _ci_vertical_status(reg, lead_id, org_id):
    """Build CI vertical constitutional gate status."""
    phases, blocked_phases = _phase_gate_snapshot(reg, org_id)
    all_clear = all(p['clear'] for p in phases)

    return {
        'preflight': 'CLEAR' if (all_clear and not is_kill_switch_engaged(org_id)) else 'BLOCKED',
        'blocked_phases': blocked_phases,
        'phases': phases,
    }


# ── HTML Dashboard ───────────────────────────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Meridian — Governed Workspace</title>
<style>
:root { --bg: #0a0a0f; --fg: #e0e0e0; --accent: #4fc3f7; --card: #151520;
        --border: #2a2a3a; --green: #4caf50; --gold: #ffd54f; --dim: #888;
        --red: #ef5350; --orange: #ff9800; }
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Inter', system-ui, sans-serif; background: var(--bg);
       color: var(--fg); line-height: 1.5; padding: 1.5rem; max-width: 1100px; margin: 0 auto; }
h1 { font-size: 1.5rem; color: #fff; margin-bottom: 0.5rem; }
h2 { font-size: 1.15rem; color: var(--accent); margin: 1.5rem 0 0.75rem;
     border-bottom: 1px solid var(--border); padding-bottom: 0.4rem; }
.subtitle { color: var(--dim); font-size: 0.9rem; margin-bottom: 1.5rem; }
.card { background: var(--card); border: 1px solid var(--border);
        border-radius: 8px; padding: 1rem; margin-bottom: 0.75rem; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; }
.grid3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0.75rem; }
@media (max-width: 700px) { .grid2, .grid3 { grid-template-columns: 1fr; } }
.metric { text-align: center; }
.metric .val { font-size: 1.6rem; font-weight: 700; color: #fff; }
.metric .label { font-size: 0.8rem; color: var(--dim); }
table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
th { text-align: left; color: var(--dim); font-weight: 600; padding: 0.4rem 0.5rem;
     border-bottom: 1px solid var(--border); }
td { padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border); }
.tag { display: inline-block; padding: 2px 8px; border-radius: 4px;
       font-size: 0.75rem; font-weight: 700; }
.tag-live { background: #1a3a1a; color: var(--green); }
.tag-warn { background: #3a2a1a; color: var(--orange); }
.tag-crit { background: #3a1a1a; color: var(--red); }
.tag-off  { background: #1a2a1a; color: var(--green); }
.tag-on   { background: #3a1a1a; color: var(--red); }
.action-row { display: flex; gap: 0.5rem; flex-wrap: wrap; margin: 0.5rem 0; }
button { background: var(--accent); color: #000; border: none; padding: 6px 16px;
         border-radius: 4px; cursor: pointer; font-weight: 600; font-size: 0.85rem; }
button:hover { background: #81d4fa; }
button.danger { background: var(--red); color: #fff; }
button.danger:hover { background: #c62828; }
button.secondary { background: transparent; border: 1px solid var(--border);
                   color: var(--fg); }
button.secondary:hover { border-color: var(--accent); color: var(--accent); }
input, select, textarea { background: #1a1a2a; border: 1px solid var(--border);
  color: var(--fg); padding: 6px 10px; border-radius: 4px; font-size: 0.85rem; }
textarea { width: 100%; min-height: 60px; font-family: inherit; }
.form-row { display: flex; gap: 0.5rem; align-items: center; margin: 0.4rem 0; flex-wrap: wrap; }
.form-row label { color: var(--dim); font-size: 0.8rem; min-width: 80px; }
.status-bar { display: flex; gap: 1.5rem; flex-wrap: wrap; margin-bottom: 1rem;
              padding: 0.75rem 1rem; background: var(--card); border-radius: 8px;
              border: 1px solid var(--border); font-size: 0.85rem; }
.status-bar .item { display: flex; align-items: center; gap: 0.4rem; }
#toast { position: fixed; bottom: 1rem; right: 1rem; background: var(--card);
         border: 1px solid var(--accent); color: var(--fg); padding: 0.75rem 1.25rem;
         border-radius: 6px; display: none; z-index: 99; font-size: 0.9rem; }
.empty { color: var(--dim); font-style: italic; padding: 0.5rem 0; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
</style>
</head>
<body>

<h1>Meridian Governed Workspace</h1>
<p class="subtitle">Constitutional Operating System — Six Primitives</p>

<div class="status-bar" id="status-bar">Loading...</div>

<!-- INSTITUTION -->
<h2>Institution</h2>
<div class="card" id="inst-card">Loading...</div>

<!-- AGENTS -->
<h2>Agents</h2>
<div class="card" id="agents-card">Loading...</div>

<!-- AUTHORITY -->
<h2>Authority</h2>
<div id="authority-section">Loading...</div>

<!-- TREASURY -->
<h2>Treasury</h2>
<div class="card" id="treasury-card">Loading...</div>

<!-- COURT -->
<h2>Court</h2>
<div id="court-section">Loading...</div>

<!-- CI VERTICAL -->
<h2>CI Vertical — Constitutional Pipeline</h2>
<div class="card" id="ci-card">Loading...</div>

<!-- RECENT AUDIT -->
<h2>Recent Audit Trail</h2>
<div class="card" id="audit-card">Loading...</div>

<div id="toast"></div>

<script>
function toast(msg, ms) {
  var t = document.getElementById('toast');
  t.textContent = msg; t.style.display = 'block';
  setTimeout(function() { t.style.display = 'none'; }, ms || 3000);
}

function api(method, path, body) {
  var opts = { method: method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  return fetch(path, opts).then(function(r) { return r.json(); });
}

var currentContext = null;
function can(path) {
  var perms = currentContext && currentContext.permissions && currentContext.permissions.mutation_paths;
  return !!(perms && perms[path] && perms[path].allowed);
}
function requiredRole(path) {
  var perms = currentContext && currentContext.permissions && currentContext.permissions.mutation_paths;
  return perms && perms[path] ? perms[path].required_role : 'admin';
}
function requirePermission(path) {
  if (can(path)) return true;
  toast('This action requires ' + requiredRole(path) + ' role.');
  return false;
}

function riskTag(state) {
  if (state === 'critical') return '<span class="tag tag-crit">CRITICAL</span>';
  if (state === 'elevated') return '<span class="tag tag-warn">ELEVATED</span>';
  if (state === 'suspended') return '<span class="tag tag-crit">SUSPENDED</span>';
  return '<span class="tag tag-live">NOMINAL</span>';
}

function render(data) {
  currentContext = data.context || null;
  // Status bar
  var ks = data.authority.kill_switch;
  var sb = '';
  sb += '<span class="item">Kill switch: ' + (ks.engaged
    ? '<span class="tag tag-on">ENGAGED</span>' : '<span class="tag tag-off">OFF</span>') + '</span>';
  sb += '<span class="item">Balance: <strong>$' + data.treasury.balance_usd.toFixed(2) + '</strong></span>';
  sb += '<span class="item">Runway: <strong>$' + data.treasury.runway_usd.toFixed(2) + '</strong></span>';
  sb += '<span class="item">CI Gate: <strong>' + data.ci_vertical.preflight + '</strong></span>';
  sb += '<span class="item">Violations: <strong>' + data.court.open_violations.length + ' open</strong></span>';
  sb += '<span class="item">Approvals: <strong>' + data.authority.pending_approvals.length + ' pending</strong></span>';
  sb += '<span class="item">Lead: <strong>' + (data.authority.sprint_lead.agent_id || 'none') + '</strong></span>';
  var persistence = data.persistence || {};
  var observability = data.observability || {};
  var dbStatus = (persistence.db && persistence.db.status) || 'unknown';
  var auditTotal = observability.metrics && observability.metrics.audit ? observability.metrics.audit.total_events : 0;
  var monthCost = observability.metrics && observability.metrics.metering ? observability.metrics.metering.total_cost_usd : 0;
  var slo = observability.slo || {};
  sb += '<span class="item">DB: <strong>' + dbStatus + '</strong></span>';
  sb += '<span class="item">Obs: <strong>audit ' + auditTotal + ' / $' + monthCost.toFixed(2) + '</strong></span>';
  sb += '<span class="item">SLO: <strong>' + (slo.status || 'unknown') + '</strong></span>';
  if (data.context && data.context.auth && data.context.auth.actor_id) {
    sb += '<span class="item">Actor: <strong>' + data.context.auth.actor_id + '</strong> (' + (data.context.auth.role || 'unbound') + ')</span>';
  }
  document.getElementById('status-bar').innerHTML = sb;

  // Institution
  var inst = data.institution;
  if (inst) {
    var ic = '';
    ic += '<div class="grid2"><div>';
    ic += '<div class="form-row"><label>Name</label> <strong>' + inst.name + '</strong></div>';
    ic += '<div class="form-row"><label>Lifecycle</label> <span class="tag tag-live">' + inst.lifecycle_state.toUpperCase() + '</span></div>';
    ic += '<div class="form-row"><label>Plan</label> ' + inst.plan + '</div>';
    ic += '<div class="form-row"><label>Owner</label> ' + inst.owner_id + '</div>';
    ic += '<div class="form-row"><label>State Capsule</label> ' + (inst.state_capsule || 'none') + '</div>';
    ic += '<div class="form-row"><label>Treasury Pointer</label> ' + (inst.treasury_id || 'none') + '</div>';
    ic += '</div><div>';
    ic += '<div class="form-row"><label>Charter</label></div>';
    ic += '<textarea id="charter-text" placeholder="Set institution charter...">' + (inst.charter || '') + '</textarea>';
    ic += '<div class="action-row"><button onclick="setCharter()">Save Charter</button>';
    ic += ' <select id="lifecycle-select"><option value="active">active</option><option value="suspended">suspended</option><option value="dissolved">dissolved</option></select>';
    ic += ' <button class="secondary" onclick="setLifecycle()">Transition Lifecycle</button></div>';
    ic += '<div class="form-row"><label>Policies</label></div>';
    var pd = inst.policy_defaults || {};
    ic += '<div style="font-size:0.8rem;color:var(--dim)">';
    for (var k in pd) ic += k + ': ' + pd[k] + '<br>';
    ic += '</div>';
    ic += '</div></div>';
    document.getElementById('inst-card').innerHTML = ic;
  }

  // Agents
  var at = '<table><tr><th>Agent</th><th>Role</th><th>REP</th><th>AUTH</th><th>Risk</th><th>Lifecycle</th><th>Incidents</th><th>Restrictions</th><th>Lead</th></tr>';
  data.agents.forEach(function(a) {
    at += '<tr><td><strong>' + a.name + '</strong></td><td>' + a.role + '</td>';
    at += '<td>' + a.rep + '</td><td>' + a.auth + '</td>';
    at += '<td>' + riskTag(a.risk_state) + '</td>';
    at += '<td>' + a.lifecycle_state + '</td>';
    at += '<td>' + a.incident_count + '</td>';
    at += '<td>' + (a.restrictions.length ? a.restrictions.join(', ') : '-') + '</td>';
    at += '<td>' + (a.is_sprint_lead ? '<strong>LEAD</strong>' : '-') + '</td></tr>';
  });
  at += '</table>';
  document.getElementById('agents-card').innerHTML = at;

  // Authority
  var au = '';
  // Kill switch control
  au += '<div class="card">';
  au += '<strong>Kill Switch</strong>: ' + (ks.engaged
    ? '<span class="tag tag-on">ENGAGED</span> by ' + ks.engaged_by + ' — ' + ks.reason
      + ' <button onclick="killSwitch(false)">Disengage</button>'
    : '<span class="tag tag-off">OFF</span> <button class="danger" onclick="killSwitch(true)">Engage Kill Switch</button>');
  au += '</div>';

  // Pending approvals
  au += '<div class="card"><strong>Pending Approvals</strong> (' + data.authority.pending_approvals.length + ')';
  if (data.authority.pending_approvals.length === 0) {
    au += '<div class="empty">No pending approvals</div>';
  } else {
    au += '<table><tr><th>ID</th><th>Agent</th><th>Action</th><th>Resource</th><th>Cost</th><th>Actions</th></tr>';
    data.authority.pending_approvals.forEach(function(a) {
      au += '<tr><td>' + a.id + '</td><td>' + a.requester_agent_id + '</td>';
      au += '<td>' + a.action + '</td><td>' + a.resource + '</td>';
      au += '<td>$' + a.cost_usd.toFixed(2) + '</td>';
      au += '<td><button onclick="decideApproval(\'' + a.id + '\',\'approved\')">Approve</button> ';
      au += '<button class="danger" onclick="decideApproval(\'' + a.id + '\',\'denied\')">Deny</button></td></tr>';
    });
    au += '</table>';
  }
  au += '</div>';

  // Active delegations
  au += '<div class="card"><strong>Active Delegations</strong> (' + data.authority.active_delegations.length + ')';
  if (data.authority.active_delegations.length === 0) {
    au += '<div class="empty">No active delegations</div>';
  } else {
    au += '<table><tr><th>ID</th><th>From</th><th>To</th><th>Scopes</th><th>Expires</th><th>Actions</th></tr>';
    data.authority.active_delegations.forEach(function(d) {
      au += '<tr><td>' + d.id + '</td><td>' + d.from_agent_id + '</td>';
      au += '<td>' + d.to_agent_id + '</td><td>' + d.scopes.join(', ') + '</td>';
      au += '<td>' + d.expires_at + '</td>';
      au += '<td><button class="danger" onclick="revokeDelegation(\'' + d.id + '\')">Revoke</button></td></tr>';
    });
    au += '</table>';
  }
  au += '</div>';

  // Request approval form
  au += '<div class="card"><strong>Request Approval</strong>';
  au += '<div class="form-row"><label>Agent</label><select id="apr-agent">';
  data.agents.forEach(function(a) { au += '<option value="' + a.economy_key + '">' + a.name + '</option>'; });
  au += '</select></div>';
  au += '<div class="form-row"><label>Action</label><select id="apr-action"><option>execute</option><option>lead</option><option>assign</option><option>deploy</option></select></div>';
  au += '<div class="form-row"><label>Resource</label><input id="apr-resource" placeholder="what to act on"></div>';
  au += '<div class="form-row"><label>Cost</label><input id="apr-cost" type="number" step="0.01" value="0" style="width:80px"></div>';
  au += '<div class="action-row"><button onclick="requestApproval()">Submit Request</button></div>';
  au += '</div>';

  // Delegate form
  au += '<div class="card"><strong>Create Delegation</strong>';
  au += '<div class="form-row"><label>From</label><select id="dlg-from">';
  data.agents.forEach(function(a) { au += '<option value="' + a.economy_key + '">' + a.name + '</option>'; });
  au += '</select></div>';
  au += '<div class="form-row"><label>To</label><select id="dlg-to">';
  data.agents.forEach(function(a) { au += '<option value="' + a.economy_key + '">' + a.name + '</option>'; });
  au += '</select></div>';
  au += '<div class="form-row"><label>Scopes</label><input id="dlg-scopes" placeholder="lead,assign,execute"></div>';
  au += '<div class="form-row"><label>Hours</label><input id="dlg-hours" type="number" value="24" style="width:60px"></div>';
  au += '<div class="action-row"><button onclick="createDelegation()">Create Delegation</button></div>';
  au += '</div>';

  document.getElementById('authority-section').innerHTML = au;

  // Treasury
  var tr = data.treasury;
  var tc = '<div class="grid3">';
  tc += '<div class="metric"><div class="val">$' + tr.balance_usd.toFixed(2) + '</div><div class="label">Balance</div></div>';
  tc += '<div class="metric"><div class="val' + (tr.runway_usd < 0 ? '" style="color:var(--red)' : '') + '">$' + tr.runway_usd.toFixed(2) + '</div><div class="label">Runway</div></div>';
  tc += '<div class="metric"><div class="val">$' + tr.reserve_floor_usd.toFixed(2) + '</div><div class="label">Reserve Floor</div></div>';
  tc += '</div>';
  tc += '<div class="grid3" style="margin-top:0.75rem">';
  tc += '<div class="metric"><div class="val">$' + tr.total_revenue_usd.toFixed(2) + '</div><div class="label">Customer Revenue</div></div>';
  tc += '<div class="metric"><div class="val">$' + tr.support_received_usd.toFixed(2) + '</div><div class="label">Support</div></div>';
  tc += '<div class="metric"><div class="val">$' + tr.owner_capital_usd.toFixed(2) + '</div><div class="label">Owner Capital</div></div>';
  tc += '</div>';
  tc += '<div style="margin-top:0.75rem;font-size:0.85rem;color:var(--dim)">';
  tc += 'Receivables: $' + tr.receivables_usd.toFixed(2) + ' | Clients: ' + tr.clients;
  tc += ' | Paid orders: ' + tr.paid_orders + ' | Owner draws: $' + tr.owner_draws_usd.toFixed(2);
  tc += ' | Spend (30d): $' + tr.spend_30d_usd.toFixed(4);
  tc += ' | ' + (tr.above_reserve ? '<span style="color:var(--green)">Above reserve</span>' : '<span style="color:var(--red)">BELOW reserve</span>');
  tc += '</div>';
  if (data.phase_machine) {
    tc += '<div style="margin-top:0.75rem;font-size:0.85rem;color:var(--dim)">';
    tc += 'Institution phase: <strong style="color:#fff">' + data.phase_machine.number + ' — ' + data.phase_machine.name + '</strong>';
    if (data.phase_machine.next_phase_name) {
      tc += ' | Next: ' + data.phase_machine.next_phase + ' — ' + data.phase_machine.next_phase_name;
    }
    tc += '</div>';
    if (data.phase_machine.next_unlock) {
      tc += '<div style="margin-top:0.35rem;font-size:0.8rem;color:var(--dim)">Next unlock: ' + data.phase_machine.next_unlock + '</div>';
    }
  }
  if (!tr.above_reserve) {
    tc += '<div style="margin-top:0.75rem;padding:0.75rem;border:1px solid var(--red);border-radius:6px;background:#241414">';
    tc += '<strong style="color:var(--red)">Operating below reserve.</strong> Clear the reserve gate before any budget-gated phase can proceed, but do not treat that alone as automation-ready state.';
    tc += '</div>';
  }
  if (data.phase_machine && data.phase_machine.number < 4) {
    tc += '<div style="margin-top:0.75rem;padding:0.75rem;border:1px solid var(--orange);border-radius:6px;background:#2b2011">';
    tc += '<strong style="color:var(--orange)">Automation still phase-blocked.</strong> Support or owner cash can clear reserve pressure, but automated delivery still waits for customer-backed treasury, treasury-cleared automation, and constitutional preflight.';
    tc += '</div>';
  }
  if (tr.remediation && tr.remediation.blocked) {
    tc += '<div class="card" style="margin-top:0.75rem"><strong>Treasury Remediation</strong>';
    tc += '<div class="form-row"><label>Shortfall</label><strong>$' + tr.remediation.shortfall_usd.toFixed(2) + '</strong></div>';
    tc += '<div class="form-row"><label>Capital</label><input id="cap-amount" type="number" step="0.01" value="' + tr.remediation.recommended_owner_capital_usd.toFixed(2) + '" style="width:120px"> <input id="cap-note" placeholder="Real transfer note" style="flex:1"></div>';
    tc += '<div class="action-row"><button onclick="contributeCapital()">Record Owner Capital</button></div>';
    tc += '<div style="font-size:0.8rem;color:var(--dim);margin-top:0.35rem">Only record this after real money has actually moved into treasury custody.</div>';
    tc += '<div class="form-row" style="margin-top:0.75rem"><label>Reserve</label><input id="reserve-amount" type="number" step="0.01" value="' + tr.remediation.recommended_reserve_floor_usd.toFixed(2) + '" style="width:120px"> <input id="reserve-note" placeholder="Why policy changed" style="flex:1"></div>';
    tc += '<div class="action-row"><button class="secondary" onclick="updateReserveFloor()">Update Reserve Floor</button></div>';
    tc += '<ul style="margin:0.5rem 0 0 1.25rem;font-size:0.82rem;color:var(--dim)">';
    tr.remediation.next_steps.forEach(function(step) { tc += '<li>' + step + '</li>'; });
    tc += '</ul></div>';
  }
  document.getElementById('treasury-card').innerHTML = tc;

  // Court
  var co = '';
  // Open violations
  co += '<div class="card"><strong>Open Violations</strong> (' + data.court.open_violations.length + ')';
  if (data.court.open_violations.length === 0) {
    co += '<div class="empty">No open violations</div>';
  } else {
    co += '<table><tr><th>ID</th><th>Agent</th><th>Type</th><th>Severity</th><th>Status</th><th>Sanction</th><th>Actions</th></tr>';
    data.court.open_violations.forEach(function(v) {
      co += '<tr><td>' + v.id + '</td><td>' + v.agent_id + '</td>';
      co += '<td>' + v.type + '</td><td>' + v.severity + '</td>';
      co += '<td>' + v.status + '</td><td>' + (v.sanction_applied || '-') + '</td>';
      co += '<td><button class="secondary" onclick="resolveViolation(\'' + v.id + '\')">Resolve</button> ';
      co += '<button class="secondary" onclick="fileAppeal(\'' + v.id + '\',\'' + v.agent_id + '\')">Appeal</button></td></tr>';
    });
    co += '</table>';
  }

  // Pending appeals
  if (data.court.pending_appeals.length > 0) {
    co += '<br><strong>Pending Appeals</strong>';
    co += '<table><tr><th>ID</th><th>Violation</th><th>Agent</th><th>Grounds</th><th>Actions</th></tr>';
    data.court.pending_appeals.forEach(function(a) {
      co += '<tr><td>' + a.id + '</td><td>' + a.violation_id + '</td><td>' + a.agent_id + '</td>';
      co += '<td>' + a.grounds + '</td>';
      co += '<td><button onclick="decideAppealAction(\'' + a.id + '\',\'overturned\')">Overturn</button> ';
      co += '<button class="secondary" onclick="decideAppealAction(\'' + a.id + '\',\'upheld\')">Uphold</button> ';
      co += '<button class="secondary" onclick="decideAppealAction(\'' + a.id + '\',\'dismissed\')">Dismiss</button></td></tr>';
    });
    co += '</table>';
  }

  co += '<div style="margin-top:0.5rem;font-size:0.8rem;color:var(--dim)">Total violations: ' + data.court.total_violations + ' | Total appeals: ' + data.court.total_appeals + '</div>';
  co += '</div>';

  // File violation form
  co += '<div class="card"><strong>File Violation</strong>';
  co += '<div class="form-row"><label>Agent</label><select id="vio-agent">';
  data.agents.forEach(function(a) { co += '<option value="' + a.economy_key + '">' + a.name + ' (' + a.economy_key + ')</option>'; });
  co += '</select></div>';
  co += '<div class="form-row"><label>Type</label><select id="vio-type">';
  ['weak_output','rejected_output','rework','token_waste','false_confidence','critical_failure'].forEach(function(t) {
    co += '<option value="' + t + '">' + t + '</option>';
  });
  co += '</select></div>';
  co += '<div class="form-row"><label>Severity</label><select id="vio-severity">';
  for (var s = 1; s <= 6; s++) {
    var desc = ['','light failure','light failure','probation','lead_ban','zero_authority','remediation_only'];
    co += '<option value="' + s + '">' + s + ' (' + desc[s] + ')</option>';
  }
  co += '</select></div>';
  co += '<div class="form-row"><label>Evidence</label><input id="vio-evidence" placeholder="What happened" style="flex:1"></div>';
  co += '<div class="form-row"><label>Policy Ref</label><input id="vio-policy" placeholder="e.g. CLAUDE.md section 9.2" style="flex:1"></div>';
  co += '<div class="action-row"><button class="danger" onclick="fileViolation()">File Violation</button>';
  co += ' <button class="secondary" onclick="autoReview()">Run Auto-Review</button></div>';
  co += '</div>';

  document.getElementById('court-section').innerHTML = co;

  // CI Vertical
  var ci = data.ci_vertical;
  var cv = '<div style="margin-bottom:0.5rem"><strong>Preflight:</strong> ';
  cv += ci.preflight === 'CLEAR'
    ? '<span class="tag tag-live">CLEAR</span>'
    : '<span class="tag tag-crit">BLOCKED</span>';
  if (ci.blocked_phases.length) cv += ' <span style="color:var(--dim)">(' + ci.blocked_phases.join(', ') + ')</span>';
  cv += '</div>';
  cv += '<table><tr><th>Phase</th><th>Agent</th><th>Action</th><th>Authority</th><th>Risk</th><th>Restrictions</th><th>Lead</th></tr>';
  ci.phases.forEach(function(p) {
    cv += '<tr><td><strong>' + p.phase + '</strong></td>';
    cv += '<td>' + p.agent_name + '</td><td>' + p.action + '</td>';
    var gate = p.clear ? '<span style="color:var(--green)">PASS</span>' : '<span style="color:var(--red)">BLOCKED</span>';
    if (!p.clear && p.blockers.length) gate += '<div style="color:var(--dim);font-size:0.75rem">' + p.blockers.join(' | ') + '</div>';
    cv += '<td>' + gate + '</td>';
    cv += '<td>' + riskTag(p.risk_state) + '</td>';
    cv += '<td>' + (p.restrictions.length ? p.restrictions.join(', ') : '-') + '</td>';
    cv += '<td>' + (p.is_lead ? '<strong>LEAD</strong>' : '-') + '</td></tr>';
  });
  cv += '</table>';
  if (data.remediations.length) {
    cv += '<div style="margin-top:0.75rem"><strong>Remediation Paths</strong></div>';
    data.remediations.forEach(function(r) {
      cv += '<div class="card" style="margin-top:0.5rem">';
      cv += '<strong>' + r.agent_name + '</strong> ' + riskTag(r.risk_state);
      cv += '<div style="margin-top:0.35rem;font-size:0.82rem;color:var(--dim)">Restrictions: ' + (r.restrictions.length ? r.restrictions.join(', ') : '-') + ' | Open violations: ' + r.open_violations + ' | Total violations: ' + r.total_violations + '</div>';
      if (r.actions && r.actions.remediate && r.actions.remediate.allowed) {
        cv += '<div class="action-row" style="margin-top:0.5rem"><button class="secondary" onclick="remediateAgent(\\'' + r.agent_key + '\\', \\'' + r.agent_name + '\\')">Run Court Remediation</button></div>';
      }
      cv += '<ul style="margin:0.5rem 0 0 1.25rem">';
      r.next_steps.forEach(function(step) { cv += '<li>' + step + '</li>'; });
      cv += '</ul></div>';
    });
  }
  cv += '<div style="margin-top:0.5rem;font-size:0.8rem;color:var(--dim)">Pipeline phases execute in order: research -> write -> QA -> execute -> compress -> deliver -> score</div>';
  document.getElementById('ci-card').innerHTML = cv;
}

// ── Action handlers ─────────────────────────────────────────────────────────

function killSwitch(engage) {
  if (!requirePermission('/api/authority/kill-switch')) return;
  var reason = engage ? prompt('Reason for engaging kill switch:') : '';
  if (engage && !reason) return;
  api('POST', '/api/authority/kill-switch', { engage: engage, reason: reason })
    .then(function(r) { toast(r.message); refresh(); });
}

function decideApproval(id, decision) {
  if (!requirePermission('/api/authority/approve')) return;
  var reason = prompt('Reason (' + decision + '):') || '';
  api('POST', '/api/authority/approve', { approval_id: id, decision: decision, reason: reason })
    .then(function(r) { toast(r.message); refresh(); });
}

function requestApproval() {
  if (!requirePermission('/api/authority/request')) return;
  api('POST', '/api/authority/request', {
    agent: document.getElementById('apr-agent').value,
    action: document.getElementById('apr-action').value,
    resource: document.getElementById('apr-resource').value,
    cost: parseFloat(document.getElementById('apr-cost').value) || 0
  }).then(function(r) { toast(r.message); refresh(); });
}

function createDelegation() {
  if (!requirePermission('/api/authority/delegate')) return;
  api('POST', '/api/authority/delegate', {
    from: document.getElementById('dlg-from').value,
    to: document.getElementById('dlg-to').value,
    scopes: document.getElementById('dlg-scopes').value,
    hours: parseInt(document.getElementById('dlg-hours').value) || 24
  }).then(function(r) { toast(r.message); refresh(); });
}

function revokeDelegation(id) {
  if (!requirePermission('/api/authority/revoke')) return;
  if (!confirm('Revoke delegation ' + id + '?')) return;
  api('POST', '/api/authority/revoke', { delegation_id: id })
    .then(function(r) { toast(r.message); refresh(); });
}

function fileViolation() {
  if (!requirePermission('/api/court/file')) return;
  api('POST', '/api/court/file', {
    agent: document.getElementById('vio-agent').value,
    type: document.getElementById('vio-type').value,
    severity: parseInt(document.getElementById('vio-severity').value),
    evidence: document.getElementById('vio-evidence').value,
    policy_ref: document.getElementById('vio-policy').value
  }).then(function(r) { toast(r.message); refresh(); });
}

function resolveViolation(id) {
  if (!requirePermission('/api/court/resolve')) return;
  var note = prompt('Resolution note:');
  if (!note) return;
  api('POST', '/api/court/resolve', { violation_id: id, note: note })
    .then(function(r) { toast(r.message); refresh(); });
}

function fileAppeal(vid, agent) {
  if (!requirePermission('/api/court/appeal')) return;
  var grounds = prompt('Appeal grounds:');
  if (!grounds) return;
  api('POST', '/api/court/appeal', { violation_id: vid, agent: agent, grounds: grounds })
    .then(function(r) { toast(r.message); refresh(); });
}

function decideAppealAction(id, decision) {
  if (!requirePermission('/api/court/decide-appeal')) return;
  api('POST', '/api/court/decide-appeal', { appeal_id: id, decision: decision })
    .then(function(r) { toast(r.message); refresh(); });
}

function autoReview() {
  if (!requirePermission('/api/court/auto-review')) return;
  api('POST', '/api/court/auto-review', {})
    .then(function(r) { toast(r.message); refresh(); });
}

function remediateAgent(agentId, agentName) {
  if (!requirePermission('/api/court/remediate')) return;
  var note = prompt('Remediation note for ' + agentName + ':') || '';
  api('POST', '/api/court/remediate', { agent_id: agentId, note: note })
    .then(function(r) { toast(r.message); refresh(); });
}

function contributeCapital() {
  if (!requirePermission('/api/treasury/contribute')) return;
  var amount = parseFloat(document.getElementById('cap-amount').value) || 0;
  var note = document.getElementById('cap-note').value || 'owner capital contribution';
  if (amount <= 0) return toast('Capital amount must be greater than 0');
  api('POST', '/api/treasury/contribute', { amount: amount, note: note })
    .then(function(r) { toast(r.message || r.error); refresh(); });
}

function updateReserveFloor() {
  if (!requirePermission('/api/treasury/reserve-floor')) return;
  var amount = parseFloat(document.getElementById('reserve-amount').value);
  var note = document.getElementById('reserve-note').value || 'reserve policy change';
  if (isNaN(amount) || amount < 0) return toast('Reserve floor must be 0 or greater');
  if (!confirm('Update reserve floor to $' + amount.toFixed(2) + '?')) return;
  api('POST', '/api/treasury/reserve-floor', { amount: amount, note: note })
    .then(function(r) { toast(r.message || r.error); refresh(); });
}

function setCharter() {
  if (!requirePermission('/api/institution/charter')) return;
  var text = document.getElementById('charter-text').value;
  api('POST', '/api/institution/charter', { text: text })
    .then(function(r) { toast(r.message); refresh(); });
}

function setLifecycle() {
  if (!requirePermission('/api/institution/lifecycle')) return;
  var state = document.getElementById('lifecycle-select').value;
  if (!confirm('Transition institution lifecycle to ' + state + '?')) return;
  api('POST', '/api/institution/lifecycle', { state: state })
    .then(function(r) { toast(r.message || r.error); refresh(); });
}

function refresh() {
  api('GET', '/api/status').then(render).catch(function(e) {
    document.getElementById('status-bar').innerHTML = '<span style="color:var(--red)">Error loading: ' + e + '</span>';
  });
  // Also load audit trail
  api('GET', '/api/audit').then(function(data) {
    if (!data.events || data.events.length === 0) {
      document.getElementById('audit-card').innerHTML = '<div class="empty">No recent audit events</div>';
      return;
    }
    var at = '<table><tr><th>Time</th><th>Action</th><th>Agent</th><th>Resource</th><th>Outcome</th></tr>';
    data.events.slice(0, 20).forEach(function(e) {
      at += '<tr><td style="font-size:0.8rem">' + e.timestamp + '</td>';
      at += '<td>' + e.action + '</td><td>' + (e.agent_id || '-') + '</td>';
      at += '<td>' + (e.resource || '-') + '</td><td>' + e.outcome + '</td></tr>';
    });
    at += '</table>';
    document.getElementById('audit-card').innerHTML = at;
  }).catch(function(){});
}

refresh();
setInterval(refresh, 15000);
</script>
</body>
</html>"""


# ── HTTP Request Handler ─────────────────────────────────────────────────────

class WorkspaceHandler(BaseHTTPRequestHandler):
    _HEAD_JSON_PATHS = {
        '/api/status',
        '/api/context',
        '/api/institution',
        '/api/agents',
        '/api/authority',
        '/api/treasury',
        '/api/treasury/accounts',
        '/api/treasury/funding-sources',
        '/api/treasury/settlement-adapters',
        '/api/subscriptions',
        '/api/subscriptions/delivery-targets',
        '/api/subscriptions/loom-delivery-jobs',
        '/api/subscriptions/loom-delivery-runs',
        '/api/subscriptions/preview-queue',
        '/api/accounting',
        '/api/pilot/intake',
        '/api/pilot/intake/operator',
        '/api/payouts',
        '/api/federation',
        '/api/federation/peers',
        '/api/federation/inbox',
        '/api/federation/execution-jobs',
        '/api/federation/manifest',
        '/api/federation/witness/archive',
        '/api/alerts',
        '/api/runtime-proof',
        '/api/runtime-proof-contract',
        '/api/kernel-proof-bundle',
        '/api/admission',
        '/api/session/validate',
        '/api/court',
        '/api/warrants',
        '/api/commitments',
        '/api/cases',
    }

    def _json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        try:
            self.wfile.write(json.dumps(data).encode())
        except (BrokenPipeError, ConnectionResetError):
            return
        except OSError as exc:
            if getattr(exc, 'errno', None) in {32, 104}:
                return
            raise

    def _headers_only(self, status=200, content_type='text/plain; charset=utf-8', *, www_authenticate=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Access-Control-Allow-Origin', '*')
        if www_authenticate:
            self.send_header('WWW-Authenticate', www_authenticate)
        self.end_headers()

    def _html(self, html):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode())

    def _text(self, text, status=200, content_type='text/plain; charset=utf-8'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(text.encode())

    def _unauthorized(self, is_api=True):
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="Meridian Workspace"')
        if is_api:
            self.send_header('Content-Type', 'application/json')
        else:
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.end_headers()
        if is_api:
            self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode())
        else:
            self.wfile.write(b'Unauthorized')

    def _service_unavailable(self, message, is_api=True):
        self.send_response(503)
        if is_api:
            self.send_header('Content-Type', 'application/json')
        else:
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.end_headers()
        if is_api:
            self.wfile.write(json.dumps({'error': message}).encode())
        else:
            self.wfile.write(message.encode())

    def _is_authorized(self):
        header = self.headers.get('Authorization', '')
        # Bearer (session) auth — always available
        if header.startswith('Bearer '):
            token = header.split(' ', 1)[1].strip()
            return _session_authority.validate(token) is not None
        # Basic auth
        user, password, _credential_org_id, _credential_user_id = _load_workspace_credentials()
        if not user or not password:
            return False
        if not header.startswith('Basic '):
            return False
        try:
            decoded = base64.b64decode(header.split(' ', 1)[1]).decode('utf-8')
        except Exception:
            return False
        if ':' not in decoded:
            return False
        supplied_user, supplied_password = decoded.split(':', 1)
        return hmac.compare_digest(supplied_user, user) and hmac.compare_digest(supplied_password, password)

    def _require_auth(self, path):
        # Session validate is a passive introspection endpoint — the token is the proof.
        protected = is_workspace_protected_path(path)
        if not protected:
            return True
        if self._is_authorized():
            return True
        user, password, _credential_org_id, _credential_user_id = _load_workspace_credentials()
        if not user or not password:
            if WORKSPACE_AUTH_REQUIRED:
                self._service_unavailable('Workspace auth is required but credentials are not configured',
                                          is_api=path.startswith('/api/'))
                return False
            return True
        self._unauthorized(is_api=path.startswith('/api/'))
        return False

    def _session_claims_from_request(self, expected_org_id=None):
        """Extract and validate session claims from a Bearer token."""
        header = self.headers.get('Authorization', '')
        if not header.startswith('Bearer '):
            return None
        token = header.split(' ', 1)[1].strip()
        return _session_authority.validate(token, expected_org_id=expected_org_id)

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def log_message(self, fmt, *args):
        pass  # Suppress default logging

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Meridian-Org-Id')
        self.end_headers()

    def do_HEAD(self):
        parsed = urlparse(self.path)
        path = parsed.path
        is_api = path.startswith('/api/')
        protected = is_workspace_protected_path(path)
        if protected and not self._is_authorized():
            user, password, _credential_org_id, _credential_user_id = _load_workspace_credentials()
            if not user or not password:
                if WORKSPACE_AUTH_REQUIRED:
                    return self._headers_only(503, 'application/json' if is_api else 'text/plain; charset=utf-8')
            else:
                return self._headers_only(
                    401,
                    'application/json' if is_api else 'text/plain; charset=utf-8',
                    www_authenticate='Basic realm="Meridian Workspace"',
                )

        if path == '/' or path == '/workspace':
            try:
                _resolve_workspace_context()
            except RuntimeError:
                return self._headers_only(503, 'text/plain; charset=utf-8')
            return self._headers_only(200, 'text/html; charset=utf-8')

        if path in self._HEAD_JSON_PATHS:
            try:
                inst_ctx = _resolve_workspace_context()
                _enforce_request_context(parsed, self.headers, inst_ctx.org_id)
                session_claims = self._session_claims_from_request(expected_org_id=inst_ctx.org_id)
                if self.headers.get('Authorization', '').startswith('Bearer ') and session_claims is None:
                    return self._headers_only(403, 'application/json')
            except RuntimeError:
                return self._headers_only(503, 'application/json')
            except ValueError:
                return self._headers_only(400, 'application/json')
            return self._headers_only(200, 'application/json')

        return self._headers_only(404, 'application/json' if is_api else 'text/plain; charset=utf-8')

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if not self._require_auth(path):
            return
        try:
            allow_inactive_context = path in (
                '/api/institution/charter',
                '/api/institution/lifecycle',
            )
            inst_ctx = _resolve_workspace_context(
                allow_inactive=allow_inactive_context,
            )
            org_id = inst_ctx.org_id
            org = inst_ctx.org
            context_source = inst_ctx.context_source
            request_context = _enforce_request_context(parsed, self.headers, org_id)
            session_claims = self._session_claims_from_request(expected_org_id=org_id)
            if session_claims:
                auth_context = _resolve_auth_context_from_session(session_claims, org_id)
            elif self.headers.get('Authorization', '').startswith('Bearer '):
                return self._json({
                    'error': 'Session token is not valid for this institution'
                }, 403)
            else:
                auth_context = _resolve_auth_context(org_id)
        except RuntimeError as e:
            return self._service_unavailable(str(e), is_api=path.startswith('/api/'))
        except ValueError as e:
            return self._json({'error': str(e)}, 400)

        if path == '/' or path == '/workspace':
            return self._html(DASHBOARD_HTML)
        elif path == '/api/status':
            return self._json(api_status(institution_context=inst_ctx))
        elif path == '/api/context':
            host_identity, admission_registry = _runtime_host_state(org_id)
            response = {
                **request_context,
                'auth': auth_context,
                'permissions': _permission_snapshot(auth_context),
                'institution': inst_ctx.to_dict(),
                'runtime_core': runtime_core_snapshot(
                    inst_ctx,
                    additional_institutions_allowed=False,
                    second_institution_path=(
                        'Live runtime remains founding-only. Admitting a second '
                        'institution requires a new runtime program; this '
                        'deployment does not expose shared multi-institution routing.'
                    ),
                    host_identity=host_identity,
                    admission_registry=admission_registry,
                    admission_management_mode=_admission_management_state(host_identity)['management_mode'],
                    admission_mutation_enabled=_admission_management_state(host_identity)['mutation_enabled'],
                    admission_mutation_disabled_reason=_admission_management_state(host_identity)['mutation_disabled_reason'],
                ),
            }
            response['runtime_core']['federation'] = _federation_snapshot(
                org_id,
                host_identity=host_identity,
                admission_registry=admission_registry,
            )
            return self._json(response)
        elif path == '/api/institution':
            return self._json(_public_org_record(org))
        elif path == '/api/institution/template':
            return self._json(_institution_template_snapshot(org_id, org=org))
        elif path == '/api/institution/license/catalog':
            return self._json({
                'status': 'deprecated',
                'reason': 'open_source_mode',
                'message': 'The institution license catalog has been deprecated. Meridian is now fully open source.',
                'next_steps': [
                    'Install Loom: curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian-loom/main/scripts/install.sh | bash',
                    'Visit https://github.com/mapleleaflatte03/meridian-loom for source and documentation',
                    'The institution template remains available at /api/institution/template',
                ],
            }, 410)
        elif path == '/api/agents':
            reg = load_registry()
            return self._json([
                normalize_agent_record(a)
                for a in reg['agents'].values()
                if a.get('org_id') in (None, '', org_id)
            ])
        elif path == '/api/authority':
            queue = _load_queue(org_id)
            lead_id, lead_auth = get_sprint_lead(org_id)
            reg = load_registry()
            return self._json({
                'kill_switch': queue['kill_switch'],
                'pending_approvals': get_pending_approvals(org_id=org_id),
                'delegations': [d for d in queue['delegations'].values() if d.get('org_id') in (None, '', org_id)],
                'sprint_lead': _public_sprint_lead(lead_id, lead_auth, reg=reg),
            })
        elif path == '/api/treasury':
            host_identity, _admission_registry = _runtime_host_state(org_id)
            return self._json(
                treasury_snapshot(
                    org_id,
                    host_supported_adapters=getattr(host_identity, 'settlement_adapters', []),
                )
            )
        elif path == '/api/treasury/wallets':
            return self._json(load_wallets(org_id))
        elif path == '/api/treasury/accounts':
            return self._json(load_treasury_accounts(org_id))
        elif path == '/api/treasury/maintainers':
            return self._json(kernel_load_maintainers(org_id))
        elif path == '/api/treasury/contributors':
            return self._json(load_contributors(org_id))
        elif path == '/api/treasury/proposals':
            return self._json(load_payout_proposals(org_id))
        elif path == '/api/treasury/funding-sources':
            return self._json(load_funding_sources(org_id))
        elif path == '/api/treasury/settlement-adapters':
            host_identity, _admission_registry = _runtime_host_state(org_id)
            return self._json({
                'bound_org_id': org_id,
                'summary': settlement_adapter_summary(
                    org_id,
                    host_supported_adapters=getattr(host_identity, 'settlement_adapters', []),
                ),
                'adapters': list_settlement_adapters(org_id),
            })
        elif path == '/api/treasury/settlement-adapters/readiness':
            host_identity, _admission_registry = _runtime_host_state(org_id)
            return self._json(_settlement_adapter_readiness_snapshot(
                org_id,
                host_supported_adapters=getattr(host_identity, 'settlement_adapters', []),
            ))
        elif path == '/api/treasury/payout-plan-preview-queue':
            return self._json(kernel_payout_plan_preview_queue_snapshot(org_id))
        elif path == '/api/treasury/payout-plan-preview-queue/inspect':
            return self._json(kernel_inspect_payout_plan_preview_queue(org_id))
        elif path == '/api/treasury/payout-plan-approval-candidate-queue':
            return self._json(kernel_payout_plan_approval_candidate_queue_snapshot(org_id))
        elif path == '/api/treasury/payout-execution-queue':
            return self._json(kernel_payout_execution_queue_snapshot(org_id))
        elif path == '/api/treasury/payout-plan-approval-candidate-queue/inspect':
            return self._json(kernel_inspect_payout_plan_approval_candidate_queue(org_id))
        elif path == '/api/subscriptions':
            return self._json(service_state.subscription_snapshot(org_id))
        elif path == '/api/subscriptions/delivery-targets':
            external_only = parse_qs(parsed.query).get('external_only', ['0'])[-1].lower() in ('1', 'true', 'yes', 'on')
            return self._json({
                'bound_org_id': org_id,
                'external_only': external_only,
                'targets': subscription_service.active_delivery_targets(
                    org_id,
                    external_only=external_only,
                ),
            })
        elif path == '/api/subscriptions/loom-delivery-jobs':
            limit = parse_qs(parsed.query).get('limit', ['50'])[-1]
            return self._json(subscription_service.loom_delivery_queue_snapshot(org_id, limit=limit))
        elif path == '/api/subscriptions/loom-delivery-runs':
            limit = parse_qs(parsed.query).get('limit', ['50'])[-1]
            return self._json(subscription_service.loom_delivery_run_snapshot(org_id, limit=limit))
        elif path == '/api/subscriptions/preview-queue':
            limit = parse_qs(parsed.query).get('limit', ['50'])[-1]
            return self._json(service_state.subscription_preview_snapshot(org_id, limit=limit))
        elif path == '/api/accounting':
            return self._json(service_state.accounting_snapshot(org_id))
        elif path == '/api/pilot/intake':
            return self._json(pilot_intake.queue_snapshot(org_id))
        elif path == '/api/pilot/intake/operator':
            return self._json(pilot_intake.operator_review_snapshot(org_id))
        elif path == '/api/payouts':
            host_identity, _admission_registry = _runtime_host_state(org_id)
            return self._json(_payout_snapshot(
                org_id,
                host_supported_adapters=getattr(host_identity, 'settlement_adapters', []),
            ))
        elif path == '/api/federation':
            host_identity, admission_registry = _runtime_host_state(org_id)
            return self._json(_federation_snapshot(
                org_id,
                host_identity=host_identity,
                admission_registry=admission_registry,
            ))
        elif path == '/api/federation/peers':
            host_identity, admission_registry = _runtime_host_state(org_id)
            return self._json(_federation_snapshot(
                org_id,
                host_identity=host_identity,
                admission_registry=admission_registry,
            ))
        elif path == '/api/federation/inbox':
            return self._json(_federation_inbox_snapshot(org_id))
        elif path == '/api/federation/handoff-preview-queue':
            return self._json(kernel_handoff_preview_queue_snapshot(org_id))
        elif path == '/api/federation/handoff-dispatch-queue':
            return self._json(kernel_handoff_dispatch_queue_snapshot(org_id))
        elif path == '/api/federation/execution-jobs':
            return self._json(_federation_execution_jobs_snapshot(org_id))
        elif path == '/api/federation/manifest':
            host_identity, admission_registry = _runtime_host_state(org_id)
            return self._json(_federation_manifest(
                inst_ctx,
                host_identity=host_identity,
                admission_registry=admission_registry,
            ))
        elif path == '/api/federation/witness/archive':
            host_identity, _admission_registry = _runtime_host_state(org_id)
            return self._json(_witness_archive_snapshot(
                org_id,
                host_identity=host_identity,
            ))
        elif path == '/api/alerts':
            return self._json(alerting.alert_queue_snapshot(org_id))
        elif path == '/api/runtime-proof':
            proof = loom_runtime_proof.collect_loom_runtime_proof(include_service_probe=True)
            return self._json(
                loom_runtime_proof.public_loom_runtime_receipt(
                    proof,
                    bound_org_id=org_id,
                )
            )
        elif path == '/api/runtime-proof-contract':
            proof = loom_runtime_proof.collect_loom_runtime_proof(include_service_probe=True)
            return self._json(
                loom_runtime_proof.public_loom_surface_contract_receipt(
                    proof,
                    bound_org_id=org_id,
                )
            )
        elif path == '/api/kernel-proof-bundle':
            return self._json(
                _kernel_public_proof_bundle(
                    base_url=_request_public_base_url(self),
                )
            )
        elif path == '/api/admission':
            host_identity, admission_registry = _runtime_host_state(org_id)
            return self._json(_admission_snapshot(
                org_id,
                host_identity=host_identity,
                admission_registry=admission_registry,
            ))
        elif path == '/api/runtimes':
            data = kernel_load_runtimes()
            contracts = kernel_check_all_contracts()
            runtimes = data.get('runtimes', {})
            usage_snapshot = _agent_runtime_usage_snapshot(org_id=org_id)
            result = {}
            for runtime_id, runtime in runtimes.items():
                result[runtime_id] = dict(runtime)
                result[runtime_id]['contract_check'] = contracts.get(runtime_id, {})
                result[runtime_id]['runtime_usage'] = usage_snapshot['runtimes'].get(runtime_id, {
                    'runtime_id': runtime_id,
                    'bound_agent_ids': [],
                    'bound_org_ids': [],
                    'bound_agent_count': 0,
                    'runtime_binding_status': 'declared_unused',
                })
            return self._json({
                'runtimes': result,
                'contract_requirements': data.get('contract_requirements', {}),
                'compliance_thresholds': data.get('compliance_thresholds', {}),
                'runtime_usage': usage_snapshot,
            })
        elif path.startswith('/api/runtimes/'):
            runtime_id = path[len('/api/runtimes/'):]
            runtime = kernel_get_runtime(runtime_id)
            if runtime is None:
                return self._json({'error': f'Runtime {runtime_id!r} not found'}, 404)
            usage_snapshot = _agent_runtime_usage_snapshot(org_id=org_id)
            enriched = dict(runtime)
            enriched['contract_check'] = kernel_check_contract(runtime_id)
            enriched['runtime_usage'] = usage_snapshot['runtimes'].get(runtime_id, {
                'runtime_id': runtime_id,
                'bound_agent_ids': [],
                'bound_org_ids': [],
                'bound_agent_count': 0,
                'runtime_binding_status': 'declared_unused',
            })
            return self._json(enriched)
        elif path == '/api/session/validate':
            qs = parse_qs(parsed.query)
            token = None
            token_list = qs.get('token', [])
            if token_list:
                token = token_list[0]
            else:
                auth_header = self.headers.get('Authorization', '')
                if auth_header.startswith('Bearer '):
                    token = auth_header.split(' ', 1)[1].strip()
            if not token:
                return self._json({'error': 'No token provided — pass ?token= or Authorization: Bearer'}, 400)
            claims = _session_authority.validate(token, expected_org_id=org_id)
            if claims is None:
                return self._json({'valid': False})
            return self._json({'valid': True, 'claims': claims.to_dict()})
        elif path == '/api/court':
            records = _load_records(org_id)
            return self._json({
                'violations': [v for v in records['violations'].values() if v.get('org_id') in (None, '', org_id)],
                'appeals': [a for a in records['appeals'].values() if a.get('org_id') in (None, '', org_id)],
            })
        elif path == '/api/warrants':
            include_expired = parse_qs(parsed.query).get('include_expired', ['0'])[-1].lower() in ('1', 'true', 'yes', 'on')
            include_archived = parse_qs(parsed.query).get('include_archived', ['0'])[-1].lower() in ('1', 'true', 'yes', 'on')
            expired_only = parse_qs(parsed.query).get('expired_only', ['0'])[-1].lower() in ('1', 'true', 'yes', 'on')
            archived_only = parse_qs(parsed.query).get('archived_only', ['0'])[-1].lower() in ('1', 'true', 'yes', 'on')
            return self._json({
                'warrants': _list_warrants_compat(
                    org_id,
                    include_archived=include_archived or include_expired or archived_only or expired_only,
                    archived_only=archived_only,
                    expired_only=expired_only,
                ),
                'summary': _warrant_summary(
                    org_id,
                    include_archived=include_archived or include_expired or archived_only or expired_only,
                    archived_only=archived_only,
                    expired_only=expired_only,
                ),
            })
        elif path == '/api/commitments':
            return self._json(_commitment_snapshot(org_id))
        elif path == '/api/cases':
            return self._json(_case_snapshot(org_id))
        elif path == '/api/ci-vertical':
            reg = load_registry()
            lead_id, _ = get_sprint_lead(org_id)
            return self._json(_ci_vertical_status(reg, lead_id, org_id))
        elif path == '/api/audit':
            events = query_events(org_id=org_id, limit=30)
            events.reverse()
            return self._json({'events': events})
        elif path in ('/metrics', '/api/metrics'):
            metrics_text = status_surface.observability_metrics_text(org_id)
            return self._text(metrics_text)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == '/api/federation/receive':
            try:
                inst_ctx = _resolve_workspace_context()
                body = self._read_body()
                envelope = (body.get('envelope') or '').strip()
                if not envelope:
                    return self._json({'error': 'Federation envelope is required'}, 400)
                peer_registry_override = _control_plane_notice_validation_peer_registry(
                    inst_ctx.org_id,
                    envelope,
                )
                claims, federation_state = _accept_federation_request(
                    inst_ctx.org_id,
                    envelope,
                    payload=body.get('payload'),
                    peer_registry=peer_registry_override,
                )
                receipt = _federation_receipt(
                    inst_ctx.org_id,
                    federation_state.get('host_id', ''),
                    claims,
                )
                inbox_entry = _federation_inbox_entry(
                    inst_ctx.org_id,
                    claims,
                    receipt,
                    payload=body.get('payload'),
                )
                processing = _process_received_federation_message(
                    inst_ctx.org_id,
                    claims,
                    receipt,
                    payload=body.get('payload'),
                )
                if processing.get('inbox_entry'):
                    inbox_entry = processing['inbox_entry']
                log_event(
                    inst_ctx.org_id,
                    claims.actor_id or f'peer:{claims.source_host_id}',
                    'federation_envelope_received',
                    resource=claims.message_type,
                    outcome='accepted',
                    actor_type=claims.actor_type or 'service',
                    details={
                        'envelope_id': claims.envelope_id,
                        'source_host_id': claims.source_host_id,
                        'source_institution_id': claims.source_institution_id,
                        'target_host_id': claims.target_host_id,
                        'target_institution_id': claims.target_institution_id,
                        'nonce': claims.nonce,
                        'boundary_name': claims.boundary_name,
                        'warrant_id': claims.warrant_id,
                        'commitment_id': claims.commitment_id,
                        'receipt_id': receipt['receipt_id'],
                    },
                    session_id=claims.session_id or None,
                )
                return self._json({
                    'message': 'Federation envelope accepted',
                    'claims': claims.to_dict(),
                    'receipt': receipt,
                    'inbox_entry': inbox_entry,
                    'processing': processing,
                    'runtime_core': {
                        'federation': dict(
                            federation_state,
                            inbox_summary=summarize_inbox_entries(inst_ctx.org_id),
                        ),
                    },
                })
            except FederationUnavailable as e:
                return self._json({'error': str(e)}, 503)
            except FederationReplayError as e:
                return self._json({'error': str(e)}, 409)
            except FederationValidationError as e:
                return self._json({'error': str(e)}, 403)
            except RuntimeError as e:
                return self._service_unavailable(str(e), is_api=True)
            except ValueError as e:
                return self._json({'error': str(e)}, 400)

        if path == '/api/pilot/intake':
            try:
                inst_ctx = _resolve_workspace_context()
                body = self._read_body()
                requested_offer = body.get('requested_offer') or 'manual_pilot'
                result = pilot_intake.submit_pilot_request(
                    body.get('name'),
                    body.get('company'),
                    email=body.get('email') or '',
                    telegram_handle=body.get('telegram_handle') or '',
                    requested_cadence=body.get('requested_cadence') or '',
                    competitors=body.get('competitors') or [],
                    topics=body.get('topics') or [],
                    notes=body.get('notes') or '',
                    source_page=body.get('source_page') or 'pilot.html',
                    requested_offer=requested_offer,
                    org_id=inst_ctx.org_id,
                    submitted_by='public:intake',
                )
                preview_result = None
                if bool(body.get('publish_preview')) or requested_offer == subscription_service.PUBLIC_CHECKOUT_PLAN:
                    preview_result = subscription_preview_queue.queue_subscription_preview(
                        result['request'],
                        org_id=inst_ctx.org_id,
                        by='public:checkout-preview',
                        note='Public checkout preview generated from pilot intake',
                    )
                checkout_offer = subscription_service.public_checkout_offer()
                log_event(
                    inst_ctx.org_id,
                    'public:intake',
                    'pilot_intake_requested',
                    resource=result['request']['request_id'],
                    outcome='success',
                    actor_type='external',
                    details={
                        'company': result['request'].get('company', ''),
                        'contact_channel': result['request'].get('contact_channel', ''),
                        'status': result['request'].get('status', ''),
                        'source_page': result['request'].get('source_page', ''),
                        'requested_offer': requested_offer,
                    },
                )
                response = {
                    'message': 'Pilot intake request recorded',
                    'request': result['request'],
                    'summary': result['summary'],
                }
                if preview_result:
                    response['message'] = 'Pilot intake recorded and public checkout preview published'
                    response['subscription_preview'] = preview_result['preview']
                    response['subscription_preview_summary'] = preview_result['summary']
                    response['checkout'] = {
                        'preview_id': preview_result['preview'].get('preview_id', ''),
                        'checkout_capture_path': '/api/subscriptions/checkout-capture',
                        'offer': checkout_offer,
                    }
                return self._json(response, 201)
            except RuntimeError as e:
                return self._service_unavailable(str(e), is_api=True)
            except ValueError as e:
                return self._json({'error': str(e)}, 400)

        if path == '/api/subscriptions/checkout-capture':
            try:
                inst_ctx = _resolve_workspace_context()
                body = self._read_body()
                draft_id = (body.get('draft_id') or '').strip()
                draft = None
                preview_id = (body.get('preview_id') or '').strip()
                if draft_id:
                    payload = subscription_service.load_subscriptions(inst_ctx.org_id)
                    draft = payload.get('draft_subscriptions', {}).get(draft_id)
                    if not draft:
                        raise LookupError(f'Subscription draft not found: {draft_id}')
                    draft_preview_id = (draft.get('preview_id') or '').strip()
                    draft_plan = (draft.get('plan') or '').strip()
                    draft_telegram_id = (draft.get('telegram_id') or '').strip()
                    if preview_id and draft_preview_id and preview_id != draft_preview_id:
                        raise ValueError(f'preview_id mismatch for draft {draft_id}')
                    if body.get('plan') and draft_plan and (body.get('plan') or '').strip() != draft_plan:
                        raise ValueError(f'plan mismatch for draft {draft_id}')
                    if body.get('telegram_id') and draft_telegram_id and (body.get('telegram_id') or '').strip() != draft_telegram_id:
                        raise ValueError(f'telegram_id mismatch for draft {draft_id}')
                    if not preview_id:
                        preview_id = draft_preview_id
                if not preview_id:
                    raise ValueError('preview_id or draft_id is required')
                preview = subscription_preview_queue.get_subscription_preview(preview_id, org_id=inst_ctx.org_id)
                payment_evidence = body.get('payment_evidence') or {}
                payment_ref = (body.get('payment_ref') or '').strip()
                if not payment_ref and isinstance(payment_evidence, dict):
                    payment_ref = (payment_evidence.get('payment_ref') or '').strip()
                payment_method = (body.get('payment_method') or 'captured').strip()
                if isinstance(payment_evidence, dict):
                    tx_hash = str(payment_evidence.get('tx_hash') or '').strip()
                    if tx_hash and not payment_ref:
                        payment_ref = tx_hash
                        payment_evidence['payment_ref'] = payment_ref
                settlement_verification = {}
                plan_name = (body.get('plan') or (draft.get('plan') if draft else '') or '').strip()
                if payment_method == subscription_service.PUBLIC_CHECKOUT_PAYMENT_METHOD:
                    settlement_verification = subscription_service.ensure_base_usdc_customer_payment(
                        preview,
                        plan_name=plan_name or subscription_service._default_plan_from_preview(preview),
                        payment_ref=payment_ref,
                        tx_hash=(payment_evidence.get('tx_hash') if isinstance(payment_evidence, dict) else ''),
                        org_id=inst_ctx.org_id,
                    )
                result = subscription_service.capture_subscription_from_preview(
                    preview,
                    telegram_id=body.get('telegram_id') or (draft.get('telegram_id') if draft else None),
                    plan=plan_name,
                    payment_method=payment_method,
                    payment_ref=payment_ref,
                    payment_evidence=payment_evidence,
                    org_id=inst_ctx.org_id,
                    actor='public:checkout',
                    timeout=int(body.get('timeout') or 120),
                )
                activated = result['subscription']
                run = result.get('delivery_run', {})
                if bool(run.get('delivered')) and result.get('delivery_job', {}).get('preview_id'):
                    preview_result = subscription_preview_queue.mark_preview_delivered(
                        preview_id,
                        run.get('delivery_ref') or result.get('delivery_job', {}).get('delivery_ref') or result['delivery_job']['job_id'],
                        org_id=inst_ctx.org_id,
                        by='public:checkout',
                        delivery_run_id=run.get('run_id', ''),
                    )
                else:
                    preview_result = subscription_preview_queue.mark_preview_activated(
                        preview_id,
                        activated['id'],
                        org_id=inst_ctx.org_id,
                        by='public:checkout',
                        checkout_claimed=bool(activated.get('payment_verified')),
                        payment_capture_claimed=bool(activated.get('payment_verified')),
                    )
                log_event(
                    inst_ctx.org_id,
                    'public:checkout',
                    'subscription_checkout_captured',
                    resource=activated['id'],
                    outcome='success',
                    actor_type='external',
                    details={
                        'preview_id': preview_id,
                        'draft_id': draft_id,
                        'telegram_id': result['telegram_id'],
                        'subscriber_id': result.get('subscriber_id', ''),
                        'plan': activated.get('plan', ''),
                        'payment_ref': activated.get('payment_ref', ''),
                        'payment_verified': bool(activated.get('payment_verified')),
                        'delivery_state': run.get('state', ''),
                        'payment_method': payment_method,
                    },
                )
                return self._json({
                    'message': 'Captured checkout activated from preview or draft record; Loom execution and customer delivery ran automatically when the runtime and delivery channels were healthy',
                    'result': result,
                    'settlement_verification': settlement_verification,
                    'preview': preview_result['preview'],
                    'subscription_preview_summary': preview_result['summary'],
                    'service_state': service_state.subscription_snapshot(inst_ctx.org_id),
                }, 201)
            except RuntimeError as e:
                return self._service_unavailable(str(e), is_api=True)
            except LookupError as e:
                return self._json({'error': str(e)}, 404)
            except ValueError as e:
                return self._json({'error': str(e)}, 400)

        if path == '/api/institution/license/checkout-capture':
            return self._json({
                'status': 'deprecated',
                'reason': 'open_source_mode',
                'message': 'Institution license checkout has been deprecated. Meridian is now fully open source.',
                'next_steps': [
                    'Install Loom: curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian-loom/main/scripts/install.sh | bash',
                    'Visit https://github.com/mapleleaflatte03/meridian-loom for source and documentation',
                    'The institution template remains available at /api/institution/template',
                ],
            }, 410)
        if False:  # Preserved for ledger continuity reference
            try:
                inst_ctx = _resolve_workspace_context()
                body = self._read_body()
                plan_name = str(body.get('plan') or '').strip()
                payment_ref = str(body.get('payment_ref') or '').strip()
                payment_evidence = body.get('payment_evidence') or {}
                tx_hash = ''
                if isinstance(payment_evidence, dict):
                    tx_hash = str(payment_evidence.get('tx_hash') or '').strip()
                    if not payment_ref:
                        payment_ref = str(payment_evidence.get('payment_ref') or tx_hash).strip()
                if not tx_hash:
                    tx_hash = str(body.get('tx_hash') or payment_ref).strip()
                capture = subscription_service.capture_institution_license_checkout(
                    plan_name=plan_name,
                    payment_ref=payment_ref,
                    tx_hash=tx_hash,
                    institution_name=str(body.get('institution_name') or '').strip(),
                    buyer_name=str(body.get('buyer_name') or '').strip(),
                    buyer_contact=str(body.get('buyer_contact') or body.get('email') or '').strip(),
                    org_id=inst_ctx.org_id,
                )
                log_event(
                    inst_ctx.org_id,
                    'public:institution-license',
                    'institution_license_checkout_captured',
                    resource=capture.get('license_id', ''),
                    outcome='success',
                    actor_type='external',
                    details={
                        'plan': capture.get('plan', ''),
                        'payment_ref': capture.get('payment_ref', ''),
                        'tx_hash': capture.get('tx_hash', ''),
                        'revenue_share_pct': capture.get('revenue_share_pct', 0.0),
                        'maintenance_plan': capture.get('maintenance_plan', ''),
                    },
                )
                return self._json({
                    'message': 'Institution license payment captured and ledger-bound evidence recorded.',
                    'capture': capture,
                    'catalog': _institution_license_catalog_snapshot(inst_ctx.org_id),
                }, 201)
            except RuntimeError as e:
                return self._service_unavailable(str(e), is_api=True)
            except ValueError as e:
                return self._json({'error': str(e)}, 400)

        if not self._require_auth(path):
            return
        if path == '/api/federation/execution-jobs/execute':
            return self._json({
                'error': 'Federation execution jobs remain review-only on the live founding-only host',
                'route': path,
                'management_mode': 'founding_locked',
                'mutation_enabled': False,
                'mutation_disabled_reason': 'single_institution_deployment',
                'state_change': False,
            }, 503)
        if path == '/api/federation/witness/archive':
            try:
                inst_ctx = _resolve_workspace_context()
                host_identity, _admission_registry = _runtime_host_state(inst_ctx.org_id)
            except RuntimeError as e:
                return self._service_unavailable(str(e), is_api=True)
            if getattr(host_identity, 'role', '') != 'witness_host':
                return self._json({
                    'error': (
                        f"Witness archive is disabled on host '{host_identity.host_id}' "
                        f"(witness_host_only)"
                    ),
                    'witness_archive': _witness_archive_snapshot(
                        inst_ctx.org_id,
                        host_identity=host_identity,
                    ),
                }, 503)
        try:
            allow_inactive_context = path in (
                '/api/institution/charter',
                '/api/institution/lifecycle',
            )
            inst_ctx = _resolve_workspace_context(
                allow_inactive=allow_inactive_context,
            )
            org_id = inst_ctx.org_id
            _enforce_request_context(parsed, self.headers, org_id)
            session_claims = self._session_claims_from_request(expected_org_id=org_id)
            if session_claims:
                auth_context = _resolve_auth_context_from_session(session_claims, org_id)
            elif self.headers.get('Authorization', '').startswith('Bearer '):
                return self._json({
                    'error': 'Session token is not valid for this institution'
                }, 403)
            else:
                auth_context = _resolve_auth_context(org_id)
            _enforce_mutation_authorization(auth_context, org_id, path)
        except RuntimeError as e:
            return self._service_unavailable(str(e), is_api=path.startswith('/api/'))
        except ValueError as e:
            return self._json({'error': str(e)}, 400)
        except PermissionError as e:
            return self._json({'error': str(e)}, 403)

        try:
            body = self._read_body()
        except Exception:
            return self._json({'error': 'Invalid JSON'}, 400)

        by = auth_context.get('actor_id') or 'owner'  # server-enforced — never trust client-supplied actor identity
        _sid = auth_context.get('session_id')  # session traceability for audit

        try:
            if path == '/api/telegram/history/import':
                export_path = str(body.get('export_path') or '').strip()
                session_key = str(body.get('session_key') or '').strip()
                manager_name = str(body.get('manager_name') or 'Leviathann').strip() or 'Leviathann'
                if not export_path:
                    return self._json({'error': 'export_path is required'}, 400)
                if not session_key:
                    return self._json({'error': 'session_key is required'}, 400)
                result = import_telegram_history(
                    export_path,
                    session_key,
                    manager_name=manager_name,
                    loom_root=body.get('loom_root') or None,
                )
                log_event(
                    org_id,
                    by,
                    'telegram_history_imported',
                    resource=session_key,
                    outcome='success',
                    details={
                        'export_path': export_path,
                        'manager_name': manager_name,
                        'message_count': result.get('message_count', 0),
                        'storage_path': result.get('storage_path', ''),
                    },
                    session_id=_sid,
                )
                return self._json({
                    'message': 'Telegram history imported into Leviathann session continuity',
                    'result': result,
                }, 201)

            if path == '/api/authority/kill-switch':
                if body.get('engage'):
                    engage_kill_switch(by, body.get('reason', ''), org_id=org_id)
                    log_event(org_id, by, 'kill_switch_engaged', outcome='success',
                              details={'by': by, 'reason': body.get('reason')},
                              session_id=_sid)
                    return self._json({'message': 'Kill switch ENGAGED'})
                else:
                    disengage_kill_switch(by, org_id=org_id)
                    log_event(org_id, by, 'kill_switch_disengaged', outcome='success',
                              details={'by': by}, session_id=_sid)
                    return self._json({'message': 'Kill switch disengaged'})

            elif path == '/api/authority/approve':
                decision = body['decision']
                decide_approval(body['approval_id'], decision,
                               by, body.get('reason', ''), org_id=org_id)
                log_event(org_id, by, 'approval_decided', resource=body['approval_id'],
                          outcome='success', details={'decision': decision, 'reason': body.get('reason', '')},
                          session_id=_sid)
                return self._json({'message': f'Approval {body["approval_id"]}: {decision}'})

            elif path == '/api/authority/request':
                aid = request_approval(body['agent'], body['action'],
                                       body['resource'], body.get('cost', 0), org_id=org_id)
                log_event(org_id, body['agent'], 'approval_requested', resource=aid,
                          outcome='success', details=body, session_id=_sid)
                return self._json({'message': f'Approval requested: {aid}', 'approval_id': aid})

            elif path == '/api/authority/delegate':
                scopes = [s.strip() for s in body['scopes'].split(',') if s.strip()]
                did = delegate(body['from'], body['to'], scopes, body.get('hours', 24), org_id=org_id)
                log_event(org_id, body['from'], 'delegation_created', resource=did,
                          outcome='success', details=body, session_id=_sid)
                return self._json({'message': f'Delegation created: {did}', 'delegation_id': did})

            elif path == '/api/authority/revoke':
                revoke_delegation(body['delegation_id'], org_id=org_id)
                log_event(org_id, by, 'delegation_revoked', resource=body['delegation_id'],
                          outcome='success', session_id=_sid)
                return self._json({'message': f'Delegation revoked: {body["delegation_id"]}'})

            elif path == '/api/court/file':
                vid = file_violation(body['agent'], org_id, body['type'],
                                     body['severity'], body['evidence'],
                                     body.get('policy_ref', ''))
                return self._json({'message': f'Violation filed: {vid}', 'violation_id': vid})

            elif path == '/api/court/resolve':
                resolve_violation(body['violation_id'], body['note'], org_id=org_id)
                log_event(org_id, by, 'violation_resolved', resource=body['violation_id'],
                          outcome='success', details={'note': body['note']},
                          session_id=_sid)
                return self._json({'message': f'Violation resolved: {body["violation_id"]}'})

            elif path == '/api/court/appeal':
                aid = file_appeal(body['violation_id'], body['agent'], body['grounds'], org_id=org_id)
                log_event(org_id, body['agent'], 'appeal_filed', resource=aid,
                          outcome='success', session_id=_sid)
                return self._json({'message': f'Appeal filed: {aid}', 'appeal_id': aid})

            elif path == '/api/court/decide-appeal':
                decide_appeal(body['appeal_id'], body['decision'], by, org_id=org_id)
                log_event(org_id, by, 'appeal_decided', resource=body['appeal_id'],
                          outcome='success', details={'decision': body['decision']},
                          session_id=_sid)
                return self._json({'message': f'Appeal {body["appeal_id"]}: {body["decision"]}'})

            elif path == '/api/court/auto-review':
                vids = auto_review(org_id=org_id)
                return self._json({'message': f'Auto-review: {len(vids)} violation(s) created',
                                   'violations': vids})

            elif path == '/api/court/remediate':
                lifted = remediate(body['agent_id'], by,
                                   body.get('note', ''), org_id=org_id)
                log_event(org_id, by, 'court_remediation', resource=body['agent_id'],
                          outcome='success', details={'lifted': lifted, 'note': body.get('note', '')},
                          session_id=_sid)
                return self._json({'message': f'Remediation complete: lifted {lifted}',
                                   'lifted': lifted})

            elif path == '/api/treasury/contribute':
                result = contribute_owner_capital(body['amount'], body.get('note', ''),
                                                  by, org_id=org_id)
                log_event(org_id, by, 'treasury_owner_capital', outcome='success',
                          details=result, session_id=_sid)
                return self._json({
                    'message': f'Owner capital recorded: +${result["amount_usd"]:.2f}',
                    'snapshot': treasury_snapshot(
                        org_id,
                        host_supported_adapters=getattr(_runtime_host_state(org_id)[0], 'settlement_adapters', []),
                    ),
                })

            elif path == '/api/treasury/reserve-floor':
                result = set_reserve_floor_policy(body['amount'], body.get('note', ''),
                                                  by, org_id=org_id)
                log_event(org_id, by, 'treasury_reserve_floor_updated',
                          outcome='success', details=result, session_id=_sid)
                return self._json({
                    'message': 'Reserve floor updated',
                    'snapshot': treasury_snapshot(
                        org_id,
                        host_supported_adapters=getattr(_runtime_host_state(org_id)[0], 'settlement_adapters', []),
                    ),
                })

            elif path == '/api/treasury/settlement-adapters/preflight':
                host_identity, _admission_registry = _runtime_host_state(org_id)
                result = preflight_settlement_adapter(
                    (body.get('adapter_id') or '').strip(),
                    org_id=org_id,
                    currency=body.get('currency') or 'USDC',
                    tx_hash=(body.get('tx_hash') or '').strip(),
                    settlement_proof=body.get('settlement_proof'),
                    host_supported_adapters=getattr(host_identity, 'settlement_adapters', []),
                )
                log_event(
                    org_id,
                    by,
                    'settlement_adapter_preflight_checked',
                    outcome=('success' if result.get('preflight_ok') else 'warning'),
                    details={
                        'requested_adapter_id': result.get('requested_adapter_id', ''),
                        'preflight_ok': result.get('preflight_ok', False),
                        'error_type': result.get('error_type', ''),
                        'error': result.get('error', ''),
                    },
                    session_id=_sid,
                )
                return self._json(result)

            elif path == '/api/treasury/payout-plan-approval-candidate-queue/promote':
                preview_id = (body.get('preview_id') or '').strip()
                if not preview_id:
                    return self._json({'error': 'preview_id is required'}, 400)
                candidate = kernel_promote_payout_plan_preview_to_approval_candidate(
                    preview_id,
                    by,
                    org_id=org_id,
                    promotion_note=body.get('note', ''),
                )
                log_event(
                    org_id,
                    by,
                    'payout_plan_preview_promoted_to_approval_candidate',
                    outcome='success',
                    resource=preview_id,
                    details={
                        'proposal_id': candidate.get('proposal_id', ''),
                        'candidate_id': candidate.get('candidate_id', ''),
                        'promoted_at': candidate.get('promoted_at', ''),
                    },
                    session_id=_sid,
                )
                return self._json({
                    'message': f'Payout-plan approval candidate promoted: {preview_id}',
                    'candidate': candidate,
                    'summary': kernel_payout_plan_approval_candidate_queue_snapshot(org_id).get('summary', {}),
                })

            elif path == '/api/subscriptions/add':
                result = subscription_service.create_subscription(
                    body.get('telegram_id'),
                    plan=body.get('plan') or 'trial',
                    duration_days=body.get('duration_days'),
                    payment_method=body.get('payment_method'),
                    payment_ref=body.get('payment_ref'),
                    confirm_payment=bool(body.get('confirm_payment')),
                    trial=bool(body.get('trial')),
                    email=body.get('email'),
                    org_id=org_id,
                    actor=by,
                )
                subscription = result['subscription']
                log_event(
                    org_id,
                    by,
                    'subscription_created',
                    outcome='success',
                    resource=subscription['id'],
                    details={
                        'telegram_id': result['telegram_id'],
                        'plan': subscription['plan'],
                        'payment_verified': bool(subscription.get('payment_verified')),
                    },
                    session_id=_sid,
                )
                return self._json({
                    'message': f"Subscription created: {subscription['id']}",
                    'result': result,
                    'service_state': service_state.subscription_snapshot(org_id),
                })

            elif path == '/api/subscriptions/draft-from-preview':
                preview_id = (body.get('preview_id') or '').strip()
                preview = subscription_preview_queue.get_subscription_preview(preview_id, org_id=org_id)
                result = subscription_service.create_draft_subscription_from_preview(
                    preview,
                    org_id=org_id,
                    actor=by,
                )
                draft_subscription = result['draft_subscription']
                preview_result = subscription_preview_queue.mark_preview_drafted(
                    preview_id,
                    draft_subscription['draft_id'],
                    org_id=org_id,
                    by=by,
                )
                log_event(
                    org_id,
                    by,
                    'subscription_draft_created',
                    outcome='success',
                    resource=draft_subscription['draft_id'],
                    details={
                        'preview_id': preview_id,
                        'pilot_request_id': draft_subscription.get('pilot_request_id', ''),
                        'draft_status': draft_subscription.get('status', 'draft'),
                    },
                    session_id=_sid,
                )
                return self._json({
                    'message': 'Draft subscription created from preview record; no checkout or payment capture claimed',
                    'result': result,
                    'preview': preview_result['preview'],
                    'subscription_preview_summary': preview_result['summary'],
                    'service_state': service_state.subscription_snapshot(org_id),
                })

            elif path == '/api/subscriptions/activate-from-preview':
                preview_id = (body.get('preview_id') or '').strip()
                preview = subscription_preview_queue.get_subscription_preview(preview_id, org_id=org_id)
                result = subscription_service.activate_subscription_from_preview(
                    preview,
                    telegram_id=body.get('telegram_id'),
                    plan=(body.get('plan') or '').strip(),
                    payment_method=body.get('payment_method') or 'captured',
                    payment_ref=body.get('payment_ref'),
                    org_id=org_id,
                    actor=by,
                    timeout=int(body.get('timeout') or 120),
                )
                activated = result['subscription']
                run = result.get('delivery_run', {})
                if bool(run.get('delivered')) and result.get('delivery_job', {}).get('preview_id'):
                    preview_result = subscription_preview_queue.mark_preview_delivered(
                        preview_id,
                        run.get('delivery_ref') or result.get('delivery_job', {}).get('delivery_ref') or result['delivery_job']['job_id'],
                        org_id=org_id,
                        by=by,
                        delivery_run_id=run.get('run_id', ''),
                    )
                else:
                    preview_result = subscription_preview_queue.mark_preview_activated(
                        preview_id,
                        activated['id'],
                        org_id=org_id,
                        by=by,
                        checkout_claimed=bool(activated.get('payment_verified')),
                        payment_capture_claimed=bool(activated.get('payment_verified')),
                    )
                log_event(
                    org_id,
                    by,
                    'subscription_activated',
                    outcome='success',
                    resource=activated['id'],
                    details={
                        'preview_id': preview_id,
                        'telegram_id': result['telegram_id'],
                        'plan': activated.get('plan', ''),
                        'payment_verified': bool(activated.get('payment_verified')),
                    },
                    session_id=_sid,
                )
                return self._json({
                    'message': 'Captured subscription activated from preview record; Loom execution and customer delivery ran automatically when the runtime and delivery channels were healthy',
                    'result': result,
                    'preview': preview_result['preview'],
                    'subscription_preview_summary': preview_result['summary'],
                    'service_state': service_state.subscription_snapshot(org_id),
                })

            elif path == '/api/subscriptions/loom-delivery-jobs/run':
                job_id = (body.get('job_id') or '').strip()
                if job_id:
                    result = subscription_service.run_loom_delivery_job(
                        job_id,
                        org_id=org_id,
                        actor=by,
                        timeout=int(body.get('timeout') or 120),
                    )
                else:
                    result = subscription_service.run_pending_loom_delivery_jobs(
                        org_id,
                        actor=by,
                        timeout=int(body.get('timeout') or 120),
                        limit=int(body.get('limit') or 1),
                    )
                log_event(
                    org_id,
                    by,
                    'subscription_delivery_run',
                    outcome='success',
                    resource=job_id or 'pending',
                    details={
                        'attempted_count': result.get('attempted_count', 1 if job_id else 0),
                    },
                    session_id=_sid,
                )
                return self._json({
                    'message': 'Loom subscription delivery runner advanced queued jobs',
                    'result': result,
                    'service_state': service_state.subscription_snapshot(org_id),
                })

            elif path == '/api/subscriptions/convert':
                result = subscription_service.convert_trial_subscription(
                    body.get('telegram_id'),
                    body.get('plan'),
                    payment_method=body.get('payment_method'),
                    payment_ref=body.get('payment_ref'),
                    confirm_payment=bool(body.get('confirm_payment')),
                    email=body.get('email'),
                    org_id=org_id,
                    actor=by,
                )
                subscription = result['subscription']
                log_event(
                    org_id,
                    by,
                    'subscription_converted',
                    outcome='success',
                    resource=subscription['id'],
                    details={
                        'telegram_id': result['telegram_id'],
                        'plan': subscription['plan'],
                        'payment_verified': bool(subscription.get('payment_verified')),
                    },
                    session_id=_sid,
                )
                return self._json({
                    'message': f"Trial converted: {subscription['id']}",
                    'result': result,
                    'service_state': service_state.subscription_snapshot(org_id),
                })

            elif path == '/api/subscriptions/verify-payment':
                result = subscription_service.verify_subscription_payment(
                    body.get('telegram_id'),
                    subscription_id=(body.get('subscription_id') or '').strip() or None,
                    payment_ref=body.get('payment_ref'),
                    org_id=org_id,
                    actor=by,
                )
                subscription = result['subscription']
                log_event(
                    org_id,
                    by,
                    'subscription_payment_verified',
                    outcome='success',
                    resource=subscription['id'],
                    details={
                        'telegram_id': result['telegram_id'],
                        'payment_ref': subscription.get('payment_ref', ''),
                    },
                    session_id=_sid,
                )
                return self._json({
                    'message': f"Subscription payment verified: {subscription['id']}",
                    'result': result,
                    'service_state': service_state.subscription_snapshot(org_id),
                })

            elif path == '/api/subscriptions/remove':
                result = subscription_service.cancel_active(
                    body.get('telegram_id'),
                    org_id=org_id,
                    actor=by,
                )
                log_event(
                    org_id,
                    by,
                    'subscription_cancelled',
                    outcome='success',
                    resource=result['telegram_id'],
                    details={'cancelled_count': result['cancelled_count']},
                    session_id=_sid,
                )
                return self._json({
                    'message': f"Subscriptions cancelled for telegram:{result['telegram_id']}",
                    'result': result,
                    'service_state': service_state.subscription_snapshot(org_id),
                })

            elif path == '/api/subscriptions/set-email':
                subscription = subscription_service.set_email(
                    (body.get('telegram_id') or '').strip(),
                    (body.get('email') or '').strip(),
                    org_id=org_id,
                    actor=by,
                )
                log_event(
                    org_id,
                    by,
                    'subscription_email_updated',
                    outcome='success',
                    resource=subscription.get('id', ''),
                    details={'telegram_id': str(body.get('telegram_id') or '').strip()},
                    session_id=_sid,
                )
                return self._json({
                    'message': f"Subscription email updated: {subscription.get('id', '')}",
                    'subscription': subscription,
                    'service_state': service_state.subscription_snapshot(org_id),
                })

            elif path == '/api/subscriptions/record-delivery':
                entry = subscription_service.record_delivery(
                    (body.get('telegram_id') or '').strip(),
                    (body.get('product') or '').strip(),
                    brief_date=(body.get('brief_date') or '').strip(),
                    org_id=org_id,
                    actor=by,
                )
                log_event(
                    org_id,
                    by,
                    'subscription_delivery_recorded',
                    outcome='success',
                    resource=entry['telegram_id'],
                    details={'product': entry['product']},
                    session_id=_sid,
                )
                return self._json({
                    'message': f"Delivery recorded: {entry['telegram_id']}",
                    'entry': entry,
                    'service_state': service_state.subscription_snapshot(org_id),
                })

            elif path == '/api/alerts/dispatch':
                limit = int(body.get('limit') or 20)
                acknowledge_only = body.get('acknowledge_only')
                if acknowledge_only is None:
                    acknowledge_only = True
                result = alerting.dispatch_queued_alerts(
                    org_id,
                    limit=limit,
                    hook_name=(body.get('hook_name') or '').strip(),
                    acknowledge_only=bool(acknowledge_only),
                )
                log_event(
                    org_id,
                    by,
                    'alert_queue_dispatched',
                    outcome='success',
                    resource=str(result.get('dispatched_count', 0)),
                    details={
                        'dispatch_mode': result.get('dispatch_mode', ''),
                        'acknowledged_count': result.get('acknowledged_count', 0),
                        'pending_delivery_count': result.get('pending_delivery_count', 0),
                    },
                    session_id=_sid,
                )
                return self._json({
                    'message': 'Alert queue acknowledged without claiming external delivery',
                    'result': result,
                })

            elif path == '/api/pilot/intake/operator/review':
                request_id = (body.get('request_id') or body.get('requestId') or '').strip()
                result = pilot_intake.acknowledge_pilot_request(
                    request_id,
                    by,
                    org_id=org_id,
                    note=body.get('note') or body.get('review_note') or '',
                )
                preview_result = subscription_preview_queue.queue_subscription_preview(
                    result['request'],
                    org_id=org_id,
                    by=by,
                    note=body.get('note') or body.get('review_note') or '',
                )
                log_event(
                    org_id,
                    by,
                    'pilot_intake_reviewed',
                    outcome='success',
                    resource=result['request'].get('request_id', ''),
                    details={
                        'status': result['request'].get('status', ''),
                        'review_state': result['request'].get('review_state', ''),
                        'reviewed_by': result['request'].get('reviewed_by', ''),
                        'preview_id': preview_result['preview'].get('preview_id', ''),
                    },
                    session_id=_sid,
                )
                return self._json({
                    'message': 'Pilot intake request acknowledged by operator; no fulfillment claimed',
                    'request': result['request'],
                    'summary': result['summary'],
                    'operator_review': pilot_intake.operator_review_snapshot(org_id).get('operator_review', {}),
                    'subscription_preview': preview_result['preview'],
                    'subscription_preview_summary': preview_result['summary'],
                })

            elif path == '/api/payouts/propose':
                proposal = create_payout_proposal(
                    (body.get('contributor_id') or '').strip(),
                    body.get('amount_usd'),
                    (body.get('contribution_type') or '').strip(),
                    proposed_by=by,
                    org_id=org_id,
                    evidence=body.get('evidence'),
                    recipient_wallet_id=(body.get('recipient_wallet_id') or '').strip(),
                    currency=body.get('currency') or 'USDC',
                    settlement_adapter=(body.get('settlement_adapter') or 'internal_ledger').strip(),
                    note=body.get('note', ''),
                    metadata=body.get('metadata'),
                    linked_commitment_id=(body.get('linked_commitment_id') or '').strip(),
                )
                log_event(
                    org_id,
                    by,
                    'payout_proposal_created',
                    outcome='success',
                    resource=proposal['proposal_id'],
                    details={
                        'contributor_id': proposal['contributor_id'],
                        'amount_usd': proposal['amount_usd'],
                        'recipient_wallet_id': proposal['recipient_wallet_id'],
                        'settlement_adapter': proposal['settlement_adapter'],
                        'linked_commitment_id': proposal.get('linked_commitment_id', ''),
                    },
                    session_id=_sid,
                )
                return self._json({
                    'message': f"Payout proposal created: {proposal['proposal_id']}",
                    'proposal': proposal,
                    'summary': payout_proposal_summary(org_id),
                })

            elif path == '/api/accounting/expense':
                result = accounting_service.record_owner_expense(
                    body.get('amount_usd'),
                    note=body.get('note', ''),
                    by=by,
                    org_id=org_id,
                )
                log_event(
                    org_id,
                    by,
                    'owner_expense_recorded',
                    outcome='success',
                    details={'amount_usd': result['amount_usd']},
                    session_id=_sid,
                )
                return self._json({
                    'message': 'Owner expense recorded',
                    'result': result,
                    'service_state': service_state.accounting_snapshot(org_id),
                })

            elif path == '/api/accounting/reimburse':
                result = accounting_service.reimburse_owner(
                    body.get('amount_usd'),
                    note=body.get('note', ''),
                    by=by,
                    org_id=org_id,
                )
                log_event(
                    org_id,
                    by,
                    'owner_reimbursement_recorded',
                    outcome='success',
                    details={'amount_usd': result['amount_usd']},
                    session_id=_sid,
                )
                return self._json({
                    'message': 'Owner reimbursement recorded',
                    'result': result,
                    'service_state': service_state.accounting_snapshot(org_id),
                })

            elif path == '/api/accounting/draw':
                result = accounting_service.take_owner_draw(
                    body.get('amount_usd'),
                    note=body.get('note', ''),
                    by=by,
                    org_id=org_id,
                )
                log_event(
                    org_id,
                    by,
                    'owner_draw_recorded',
                    outcome='success',
                    details={'amount_usd': result['amount_usd']},
                    session_id=_sid,
                )
                return self._json({
                    'message': 'Owner draw recorded',
                    'result': result,
                    'service_state': service_state.accounting_snapshot(org_id),
                })

            elif path == '/api/payouts/submit':
                proposal_id = (body.get('proposal_id') or '').strip()
                if not proposal_id:
                    return self._json({'error': 'proposal_id is required'}, 400)
                proposal = submit_payout_proposal(
                    proposal_id,
                    by,
                    org_id=org_id,
                    note=body.get('note', ''),
                    owner_override=(auth_context.get('role') == 'owner'),
                )
                log_event(
                    org_id,
                    by,
                    'payout_proposal_submitted',
                    outcome='success',
                    resource=proposal_id,
                    details={'status': proposal['status']},
                    session_id=_sid,
                )
                return self._json({
                    'message': f'Payout proposal submitted: {proposal_id}',
                    'proposal': proposal,
                    'summary': payout_proposal_summary(org_id),
                })

            elif path == '/api/payouts/review':
                proposal_id = (body.get('proposal_id') or '').strip()
                if not proposal_id:
                    return self._json({'error': 'proposal_id is required'}, 400)
                proposal = review_payout_proposal(
                    proposal_id,
                    by,
                    org_id=org_id,
                    note=body.get('note', ''),
                )
                log_event(
                    org_id,
                    by,
                    'payout_proposal_under_review',
                    outcome='success',
                    resource=proposal_id,
                    details={'status': proposal['status']},
                    session_id=_sid,
                )
                return self._json({
                    'message': f'Payout proposal under review: {proposal_id}',
                    'proposal': proposal,
                    'summary': payout_proposal_summary(org_id),
                })

            elif path == '/api/payouts/approve':
                proposal_id = (body.get('proposal_id') or '').strip()
                if not proposal_id:
                    return self._json({'error': 'proposal_id is required'}, 400)
                proposal = approve_payout_proposal(
                    proposal_id,
                    by,
                    org_id=org_id,
                    note=body.get('note', ''),
                )
                log_event(
                    org_id,
                    by,
                    'payout_proposal_approved',
                    outcome='success',
                    resource=proposal_id,
                    details={'status': proposal['status']},
                    session_id=_sid,
                )
                return self._json({
                    'message': f'Payout proposal approved: {proposal_id}',
                    'proposal': proposal,
                    'summary': payout_proposal_summary(org_id),
                })

            elif path == '/api/payouts/open-dispute-window':
                proposal_id = (body.get('proposal_id') or '').strip()
                if not proposal_id:
                    return self._json({'error': 'proposal_id is required'}, 400)
                proposal = open_payout_dispute_window(
                    proposal_id,
                    by,
                    org_id=org_id,
                    note=body.get('note', ''),
                    dispute_window_hours=body.get('dispute_window_hours'),
                )
                log_event(
                    org_id,
                    by,
                    'payout_dispute_window_opened',
                    outcome='success',
                    resource=proposal_id,
                    details={
                        'status': proposal['status'],
                        'dispute_window_ends_at': proposal.get('dispute_window_ends_at', ''),
                    },
                    session_id=_sid,
                )
                return self._json({
                    'message': f'Payout dispute window opened: {proposal_id}',
                    'proposal': proposal,
                    'summary': payout_proposal_summary(org_id),
                })

            elif path == '/api/payouts/reject':
                proposal_id = (body.get('proposal_id') or '').strip()
                if not proposal_id:
                    return self._json({'error': 'proposal_id is required'}, 400)
                proposal = reject_payout_proposal(
                    proposal_id,
                    by,
                    org_id=org_id,
                    note=body.get('note', ''),
                )
                log_event(
                    org_id,
                    by,
                    'payout_proposal_rejected',
                    outcome='success',
                    resource=proposal_id,
                    details={'status': proposal['status']},
                    session_id=_sid,
                )
                return self._json({
                    'message': f'Payout proposal rejected: {proposal_id}',
                    'proposal': proposal,
                    'summary': payout_proposal_summary(org_id),
                })

            elif path == '/api/payouts/cancel':
                proposal_id = (body.get('proposal_id') or '').strip()
                if not proposal_id:
                    return self._json({'error': 'proposal_id is required'}, 400)
                proposal = cancel_payout_proposal(
                    proposal_id,
                    by,
                    org_id=org_id,
                    note=body.get('note', ''),
                    owner_override=(auth_context.get('role') == 'owner'),
                )
                log_event(
                    org_id,
                    by,
                    'payout_proposal_cancelled',
                    outcome='success',
                    resource=proposal_id,
                    details={'status': proposal['status']},
                    session_id=_sid,
                )
                return self._json({
                    'message': f'Payout proposal cancelled: {proposal_id}',
                    'proposal': proposal,
                    'summary': payout_proposal_summary(org_id),
                })

            elif path == '/api/payouts/execute':
                proposal_id = (body.get('proposal_id') or '').strip()
                warrant_id = (body.get('warrant_id') or '').strip()
                if not proposal_id:
                    return self._json({'error': 'proposal_id is required'}, 400)
                if not warrant_id:
                    return self._json({'error': 'warrant_id is required'}, 400)
                proposal_record = get_payout_proposal(proposal_id, org_id=org_id)
                linked_commitment_id = (proposal_record or {}).get('linked_commitment_id', '').strip()
                if linked_commitment_id:
                    case_record, settlement_warrant = _maybe_block_commitment_settlement(
                        linked_commitment_id,
                        by,
                        org_id=org_id,
                        session_id=_sid,
                        note=body.get('note', ''),
                    )
                    if case_record:
                        return self._json({
                            'error': (
                                f"Linked commitment '{linked_commitment_id}' cannot settle while case "
                                f"'{case_record.get('case_id', '')}' is {case_record.get('status', '')}"
                            ),
                            'case': case_record,
                            'warrant': settlement_warrant,
                            'linked_commitment_id': linked_commitment_id,
                            'summary': payout_proposal_summary(org_id),
                        }, 409)
                host_identity, _admission_registry = _runtime_host_state(org_id)
                request_payload = {
                    'proposal_id': proposal_id,
                    'settlement_adapter': (body.get('settlement_adapter') or 'internal_ledger').strip(),
                    'tx_hash': (body.get('tx_hash') or '').strip(),
                }
                if linked_commitment_id:
                    request_payload['linked_commitment_id'] = linked_commitment_id
                if 'settlement_proof' in body:
                    request_payload['settlement_proof'] = body.get('settlement_proof')
                validate_warrant_for_execution(
                    warrant_id,
                    org_id=org_id,
                    action_class='payout_execution',
                    boundary_name='payouts',
                    actor_id=by,
                    session_id=_sid or '',
                    request_payload=request_payload,
                )
                proposal = execute_payout_proposal(
                    proposal_id,
                    by,
                    org_id=org_id,
                    warrant_id=warrant_id,
                    settlement_adapter=request_payload['settlement_adapter'],
                    tx_hash=request_payload['tx_hash'],
                    note=body.get('note', ''),
                    allow_early=bool(body.get('allow_early')),
                    settlement_proof=body.get('settlement_proof'),
                    host_supported_adapters=getattr(host_identity, 'settlement_adapters', []),
                )
                warrant = mark_warrant_executed(
                    warrant_id,
                    org_id=org_id,
                    execution_refs={
                        **dict(proposal.get('execution_refs') or {}),
                        'proposal_id': proposal_id,
                    },
                )
                log_event(
                    org_id,
                    by,
                    'payout_executed',
                    outcome='success',
                    resource=proposal_id,
                    details={
                        'amount_usd': proposal['amount_usd'],
                        'recipient_wallet_id': proposal['recipient_wallet_id'],
                        'warrant_id': warrant_id,
                        'tx_ref': (proposal.get('execution_refs') or {}).get('tx_ref', ''),
                        'linked_commitment_id': linked_commitment_id,
                    },
                    session_id=_sid,
                )
                return self._json({
                    'message': f'Payout executed: {proposal_id}',
                    'proposal': proposal,
                    'warrant': warrant,
                    'summary': payout_proposal_summary(org_id),
                })

            elif path == '/api/session/issue':
                user_id = auth_context.get('user_id')
                role = auth_context.get('role')
                if not user_id or not role:
                    return self._json({
                        'error': 'Cannot issue session: actor is not a member of this institution'
                    }, 403)
                ttl = body.get('ttl_seconds')
                token = _session_authority.issue(org_id, user_id, role, ttl_seconds=ttl)
                claims = _session_authority.validate(token)
                log_event(org_id, by, 'session_issued', outcome='success',
                          details={'session_id': claims.session_id,
                                   'user_id': user_id, 'role': role},
                          session_id=_sid)
                return self._json({
                    'token': token,
                    'session_id': claims.session_id,
                    'org_id': org_id,
                    'user_id': user_id,
                    'role': role,
                    'expires_at': claims.expires_at,
                })

            elif path == '/api/session/revoke':
                session_id = body.get('session_id')
                if not session_id:
                    return self._json({'error': 'session_id is required'}, 400)
                _session_authority.revoke(session_id)
                log_event(org_id, by, 'session_revoked', outcome='success',
                          details={'session_id': session_id},
                          session_id=_sid)
                return self._json({'message': f'Session revoked: {session_id}'})

            elif path == '/api/warrants/issue':
                action_class = (body.get('action_class') or '').strip()
                boundary_name = (body.get('boundary_name') or '').strip()
                if not action_class:
                    return self._json({'error': 'action_class is required'}, 400)
                if not boundary_name:
                    return self._json({'error': 'boundary_name is required'}, 400)
                warrant = issue_warrant(
                    org_id,
                    action_class,
                    boundary_name,
                    by,
                    session_id=_sid or '',
                    request_payload=body.get('request_payload'),
                    risk_class=(body.get('risk_class') or 'moderate').strip(),
                    evidence_refs=body.get('evidence_refs'),
                    policy_refs=body.get('policy_refs'),
                    ttl_seconds=body.get('ttl_seconds'),
                    auto_issue=bool(body.get('auto_issue')),
                    note=body.get('note', ''),
                )
                log_event(org_id, by, 'warrant_issued', outcome='success',
                          resource=warrant['warrant_id'],
                          details={
                              'action_class': warrant['action_class'],
                              'boundary_name': warrant['boundary_name'],
                              'court_review_state': warrant['court_review_state'],
                          },
                          session_id=_sid)
                return self._json({
                    'message': f"Warrant issued: {warrant['warrant_id']}",
                    'warrant': warrant,
                })

            elif path in ('/api/warrants/approve', '/api/warrants/stay', '/api/warrants/revoke'):
                warrant_id = (body.get('warrant_id') or '').strip()
                if not warrant_id:
                    return self._json({'error': 'warrant_id is required'}, 400)
                decision = path.rsplit('/', 1)[-1]
                decision_past = {
                    'approve': 'approved',
                    'stay': 'stayed',
                    'revoke': 'revoked',
                }
                warrant = review_warrant(
                    warrant_id,
                    decision,
                    by,
                    org_id=org_id,
                    note=body.get('note', ''),
                )
                execution_job = _sync_execution_job_for_warrant_review(
                    org_id,
                    warrant,
                    decision=decision,
                    note=body.get('note', ''),
                    actor_id=by,
                    session_id=_sid,
                    reason=f'workspace_warrant_{decision}',
                )
                court_notice = None
                if execution_job:
                    try:
                        court_notice = _deliver_execution_job_court_notice(
                            org_id,
                            execution_job,
                            warrant,
                            decision,
                            actor_id=by,
                            session_id=_sid,
                            note=body.get('note', ''),
                        )
                    except (FederationUnavailable, FederationDeliveryError, FederationValidationError, PermissionError, LookupError, RuntimeError, ValueError) as exc:
                        log_event(
                            org_id,
                            by,
                            'federation_court_notice_delivery_failed',
                            outcome='failed',
                            resource=(execution_job or {}).get('job_id', ''),
                            details={
                                'warrant_id': warrant_id,
                                'decision': decision,
                                'error': str(exc),
                            },
                            session_id=_sid,
                        )
                log_event(org_id, by, f'warrant_{decision}', outcome='success',
                          resource=warrant_id,
                          details={
                              'court_review_state': warrant['court_review_state'],
                              'execution_job_id': (execution_job or {}).get('job_id', ''),
                              'execution_job_state': (execution_job or {}).get('state', ''),
                          },
                          session_id=_sid)
                response = {
                    'message': f"Warrant {decision_past[decision]}: {warrant_id}",
                    'warrant': warrant,
                }
                if execution_job:
                    response['execution_job'] = execution_job
                if court_notice:
                    response['court_notice'] = court_notice
                return self._json(response)

            elif path == '/api/commitments/propose':
                target_host_id = (body.get('target_host_id') or '').strip()
                target_org_id = (
                    body.get('target_institution_id')
                    or body.get('target_org_id')
                    or ''
                ).strip()
                summary = (body.get('summary') or '').strip()
                if not target_host_id:
                    return self._json({'error': 'target_host_id is required'}, 400)
                if not target_org_id:
                    return self._json({'error': 'target_institution_id is required'}, 400)
                if not summary:
                    return self._json({'error': 'summary is required'}, 400)
                commitment = commitments.propose_commitment(
                    target_host_id,
                    target_org_id,
                    summary,
                    commitment_id=(body.get('commitment_id') or '').strip(),
                    proposed_by=by,
                    note=body.get('note', ''),
                    org_id=org_id,
                    metadata=body.get('metadata'),
                )
                log_event(org_id, by, 'commitment_proposed', resource=commitment['commitment_id'],
                          outcome='success', details={
                              'target_host_id': target_host_id,
                              'target_institution_id': target_org_id,
                              'summary': summary,
                          }, session_id=_sid)
                return self._json({
                    'message': f"Commitment proposed: {commitment['commitment_id']}",
                    'commitment': commitment,
                    'summary': commitments.commitment_summary(org_id),
                })

            elif path == '/api/commitments/accept':
                commitment_id = (body.get('commitment_id') or '').strip()
                if not commitment_id:
                    return self._json({'error': 'commitment_id is required'}, 400)
                commitment = commitments.accept_commitment(
                    commitment_id,
                    by,
                    org_id=org_id,
                    note=body.get('note', ''),
                )
                log_event(org_id, by, 'commitment_accepted', resource=commitment_id,
                          outcome='success', details={'status': commitment['status']},
                          session_id=_sid)
                return self._json({
                    'message': f"Commitment accepted: {commitment_id}",
                    'commitment': commitment,
                    'summary': commitments.commitment_summary(org_id),
                })

            elif path == '/api/commitments/reject':
                commitment_id = (body.get('commitment_id') or '').strip()
                if not commitment_id:
                    return self._json({'error': 'commitment_id is required'}, 400)
                commitment = commitments.reject_commitment(
                    commitment_id,
                    by,
                    org_id=org_id,
                    note=body.get('note', ''),
                )
                log_event(org_id, by, 'commitment_rejected', resource=commitment_id,
                          outcome='success', details={'status': commitment['status']},
                          session_id=_sid)
                return self._json({
                    'message': f"Commitment rejected: {commitment_id}",
                    'commitment': commitment,
                    'summary': commitments.commitment_summary(org_id),
                })

            elif path == '/api/commitments/breach':
                commitment_id = (body.get('commitment_id') or '').strip()
                if not commitment_id:
                    return self._json({'error': 'commitment_id is required'}, 400)
                commitment = commitments.breach_commitment(
                    commitment_id,
                    by,
                    org_id=org_id,
                    note=body.get('note', ''),
                )
                log_event(org_id, by, 'commitment_breached', resource=commitment_id,
                          outcome='success', details={'status': commitment['status']},
                          session_id=_sid)
                case_record = None
                warrant = None
                if body.get('open_case', True):
                    case_record, created = _maybe_open_case_for_commitment_breach(
                        commitment,
                        by,
                        org_id=org_id,
                        note=body.get('case_note') or body.get('note', ''),
                    )
                    if created:
                        log_event(
                            org_id,
                            by,
                            'case_opened',
                            resource=case_record['case_id'],
                            outcome='success',
                            details={
                                'claim_type': case_record['claim_type'],
                                'linked_commitment_id': commitment_id,
                                'linked_warrant_id': case_record.get('linked_warrant_id', ''),
                            },
                            session_id=_sid,
                        )
                    warrant = _maybe_stay_warrant_for_case(
                        case_record,
                        by,
                        org_id=org_id,
                        session_id=_sid,
                        note=body.get('case_note') or body.get('note', ''),
                    )
                return self._json({
                    'message': f"Commitment breached: {commitment_id}",
                    'commitment': commitment,
                    'summary': commitments.commitment_summary(org_id),
                    'case': case_record,
                    'warrant': warrant,
                })

            elif path == '/api/commitments/settle':
                commitment_id = (body.get('commitment_id') or '').strip()
                if not commitment_id:
                    return self._json({'error': 'commitment_id is required'}, 400)
                proposal_id = (body.get('proposal_id') or '').strip()
                settlement_proposal = None
                settlement_ref = None
                if proposal_id:
                    settlement_proposal = get_payout_proposal(proposal_id, org_id=org_id)
                    if not settlement_proposal:
                        return self._json({'error': f'Payout proposal not found: {proposal_id}'}, 404)
                    if settlement_proposal.get('status') != 'executed':
                        return self._json({
                            'error': (
                                f"Payout proposal '{proposal_id}' must be executed before settling "
                                f"commitment '{commitment_id}'"
                            ),
                            'proposal': settlement_proposal,
                        }, 409)
                    if (settlement_proposal.get('linked_commitment_id') or '').strip() != commitment_id:
                        return self._json({
                            'error': (
                                f"Payout proposal '{proposal_id}' is linked to commitment "
                                f"{settlement_proposal.get('linked_commitment_id', '')!r}, not {commitment_id!r}"
                            ),
                            'proposal': settlement_proposal,
                        }, 409)
                    settlement_ref = {
                        'proposal_id': proposal_id,
                        'tx_ref': (settlement_proposal.get('execution_refs') or {}).get('tx_ref', ''),
                        'settlement_adapter': settlement_proposal.get('settlement_adapter', ''),
                        'tx_hash': settlement_proposal.get('tx_hash', ''),
                        'proof_type': (settlement_proposal.get('execution_refs') or {}).get('proof_type', ''),
                        'verification_state': (settlement_proposal.get('execution_refs') or {}).get('verification_state', ''),
                        'finality_state': (settlement_proposal.get('execution_refs') or {}).get('finality_state', ''),
                        'warrant_id': settlement_proposal.get('warrant_id', ''),
                        'recorded_by': by,
                        'proof': (settlement_proposal.get('execution_refs') or {}).get('proof', {}),
                    }
                case_record, warrant = _maybe_block_commitment_settlement(
                    commitment_id,
                    by,
                    org_id=org_id,
                    session_id=_sid,
                    note=body.get('note', ''),
                )
                if case_record:
                    return self._json({
                        'error': (
                            f"Commitment '{commitment_id}' cannot settle while case "
                            f"'{case_record.get('case_id', '')}' is {case_record.get('status', '')}"
                        ),
                        'case': case_record,
                        'warrant': warrant,
                            'summary': commitments.commitment_summary(org_id),
                        }, 409)
                if settlement_ref:
                    commitments.record_settlement_ref(
                        commitment_id,
                        settlement_ref,
                        org_id=org_id,
                    )
                commitment = commitments.settle_commitment(
                    commitment_id,
                    by,
                    org_id=org_id,
                    note=body.get('note', ''),
                )
                log_event(org_id, by, 'commitment_settled', resource=commitment_id,
                          outcome='success', details={'status': commitment['status']},
                          session_id=_sid)
                return self._json({
                    'message': f"Commitment settled: {commitment_id}",
                    'commitment': commitment,
                    'proposal': settlement_proposal,
                    'summary': commitments.commitment_summary(org_id),
                })

            elif path == '/api/cases/open':
                claim_type = (body.get('claim_type') or '').strip()
                if not claim_type:
                    return self._json({'error': 'claim_type is required'}, 400)
                if body.get('federate'):
                    target_host_id, target_institution_id = _case_notice_delivery_context(
                        {
                            'target_host_id': (body.get('target_host_id') or '').strip(),
                            'target_institution_id': (
                                body.get('target_institution_id')
                                or body.get('target_org_id')
                                or ''
                            ).strip(),
                        },
                        body,
                    )
                    if not target_host_id:
                        return self._json({
                            'error': 'target_host_id is required for federated case_notice dispatch',
                        }, 400)
                    if not target_institution_id:
                        return self._json({
                            'error': 'target_institution_id is required for federated case_notice dispatch',
                        }, 400)
                case_record = cases.open_case(
                    org_id,
                    claim_type,
                    by,
                    target_host_id=(body.get('target_host_id') or '').strip(),
                    target_institution_id=(
                        body.get('target_institution_id')
                        or body.get('target_org_id')
                        or ''
                    ).strip(),
                    linked_commitment_id=(body.get('linked_commitment_id') or '').strip(),
                    linked_warrant_id=(body.get('linked_warrant_id') or '').strip(),
                    evidence_refs=body.get('evidence_refs') or [],
                    note=body.get('note', ''),
                    metadata=body.get('metadata'),
                )
                log_event(org_id, by, 'case_opened', resource=case_record['case_id'],
                          outcome='success', details={
                              'claim_type': claim_type,
                              'linked_commitment_id': case_record.get('linked_commitment_id', ''),
                              'linked_warrant_id': case_record.get('linked_warrant_id', ''),
                          }, session_id=_sid)
                federation_peer = _maybe_suspend_peer_for_case(
                    case_record,
                    by,
                    org_id=org_id,
                    session_id=_sid,
                )
                warrant = _maybe_stay_warrant_for_case(
                    case_record,
                    by,
                    org_id=org_id,
                    session_id=_sid,
                    note=body.get('note', ''),
                )
                delivery = None
                if body.get('federate'):
                    try:
                        case_notice_delivery = _deliver_case_notice(
                            org_id,
                            case_record,
                            'open',
                            actor_id=by,
                            session_id=_sid or '',
                            body=body,
                        )
                    except ValueError as e:
                        return self._json({'error': str(e), 'case': case_record}, 400)
                    except FederationUnavailable as e:
                        return self._json({
                            'error': str(e),
                            'case': case_record,
                            'federation_peer': federation_peer,
                            'warrant': warrant,
                        }, 503)
                    except PermissionError as e:
                        response = {'error': str(e), 'case': case_record}
                        response['federation_peer'] = getattr(e, 'federation_peer', None)
                        response['warrant'] = getattr(e, 'warrant', None)
                        return self._json(response, 403)
                    except FederationDeliveryError as e:
                        response = {
                            'error': str(e),
                            'case': case_record,
                            'peer_host_id': e.peer_host_id,
                            'claims': _federation_claims_dict(e.claims),
                            'federation_peer': getattr(e, 'federation_peer', None),
                            'warrant': getattr(e, 'warrant', None),
                        }
                        return self._json(response, 502)
                    delivery = case_notice_delivery['delivery']
                return self._json({
                    'message': f"Case opened: {case_record['case_id']}",
                    'case': case_record,
                    'summary': _case_snapshot(org_id),
                    'federation_peer': federation_peer,
                    'warrant': warrant,
                    'delivery': delivery,
                    **({'runtime_core': case_notice_delivery['runtime_core']} if body.get('federate') else {}),
                })

            elif path in ('/api/cases/stay', '/api/cases/resolve'):
                case_id = (body.get('case_id') or '').strip()
                if not case_id:
                    return self._json({'error': 'case_id is required'}, 400)
                decision = path.rsplit('/', 1)[-1]
                event_name = {
                    'stay': 'case_stayed',
                    'resolve': 'case_resolved',
                }[decision]
                prior_case = _case_record_by_id(org_id, case_id)
                if body.get('federate'):
                    target_host_id, target_institution_id = _case_notice_delivery_context(
                        prior_case or {},
                        body,
                    )
                    if not target_host_id:
                        return self._json({
                            'error': 'target_host_id is required for federated case_notice dispatch',
                            'case': prior_case,
                        }, 400)
                    if not target_institution_id:
                        return self._json({
                            'error': 'target_institution_id is required for federated case_notice dispatch',
                            'case': prior_case,
                        }, 400)
                case_record = {
                    'stay': cases.stay_case,
                    'resolve': cases.resolve_case,
                }[decision](
                    case_id,
                    by,
                    org_id=org_id,
                    note=body.get('note', ''),
                )
                log_event(org_id, by, event_name, resource=case_id,
                          outcome='success', details={'status': case_record['status']},
                          session_id=_sid)
                federation_peer = None
                warrant = None
                if decision == 'stay':
                    federation_peer = _maybe_suspend_peer_for_case(
                        case_record,
                        by,
                        org_id=org_id,
                        session_id=_sid,
                    )
                    warrant = _maybe_stay_warrant_for_case(
                        case_record,
                        by,
                        org_id=org_id,
                        session_id=_sid,
                        note=body.get('note', ''),
                    )
                else:
                    federation_peer = _maybe_restore_peer_for_case(
                        case_record,
                        by,
                        org_id=org_id,
                        session_id=_sid,
                    )
                delivery = None
                if body.get('federate'):
                    try:
                        case_notice_delivery = _deliver_case_notice(
                            org_id,
                            case_record,
                            decision,
                            actor_id=by,
                            session_id=_sid or '',
                            body=body,
                        )
                    except ValueError as e:
                        return self._json({'error': str(e), 'case': case_record}, 400)
                    except FederationUnavailable as e:
                        return self._json({
                            'error': str(e),
                            'case': case_record,
                            'federation_peer': federation_peer,
                            'warrant': warrant,
                        }, 503)
                    except PermissionError as e:
                        response = {'error': str(e), 'case': case_record}
                        response['federation_peer'] = getattr(e, 'federation_peer', None)
                        response['warrant'] = getattr(e, 'warrant', None)
                        return self._json(response, 403)
                    except FederationDeliveryError as e:
                        response = {
                            'error': str(e),
                            'case': case_record,
                            'peer_host_id': e.peer_host_id,
                            'claims': _federation_claims_dict(e.claims),
                            'federation_peer': getattr(e, 'federation_peer', None),
                            'warrant': getattr(e, 'warrant', None),
                        }
                        return self._json(response, 502)
                    delivery = case_notice_delivery['delivery']
                return self._json({
                    'message': f"Case {case_record['status']}: {case_id}",
                    'case': case_record,
                    'summary': _case_snapshot(org_id),
                    'federation_peer': federation_peer,
                    'warrant': warrant,
                    'delivery': delivery,
                    **({'runtime_core': case_notice_delivery['runtime_core']} if body.get('federate') else {}),
                })

            elif path == '/api/federation/handoff-preview-queue/acknowledge':
                handoff_id = (body.get('handoff_id') or '').strip()
                if not handoff_id:
                    return self._json({'error': 'handoff_id is required'}, 400)
                by_actor = (body.get('by') or by or '').strip()
                if not by_actor:
                    return self._json({'error': 'by is required'}, 400)
                try:
                    promotion = _acknowledge_and_dispatch_remote_handoff_preview(
                        org_id,
                        handoff_id,
                        actor_id=by_actor,
                        note=body.get('note', ''),
                    )
                except LookupError as e:
                    return self._json({'error': str(e)}, 404)
                except PermissionError as e:
                    return self._json({'error': str(e)}, 403)
                except ValueError as e:
                    return self._json({'error': str(e)}, 400)
                response = {
                    'message': 'Federation handoff preview acknowledged',
                    **promotion,
                }
                if promotion.get('dispatch_record_created'):
                    response['message'] = (
                        'Federation handoff preview acknowledged and promoted to dispatch'
                    )
                return self._json(response)

            elif path == '/api/federation/handoff-dispatch-queue/run':
                dispatch_id = (body.get('dispatch_id') or body.get('handoff_id') or '').strip()
                if not dispatch_id:
                    return self._json({'error': 'dispatch_id is required'}, 400)
                by_actor = (body.get('by') or by or '').strip()
                if not by_actor:
                    return self._json({'error': 'by is required'}, 400)
                try:
                    dispatch_runner = _run_federation_dispatch(
                        org_id,
                        dispatch_id,
                        actor_id=by_actor,
                        note=body.get('note', ''),
                        session_id=_sid or '',
                        payload=body.get('payload'),
                        warrant_id=(body.get('warrant_id') or '').strip(),
                        commitment_id=(body.get('commitment_id') or '').strip(),
                        ttl_seconds=body.get('ttl_seconds'),
                    )
                except LookupError as e:
                    return self._json({'error': str(e)}, 404)
                except FederationUnavailable as e:
                    return self._json({'error': str(e)}, 503)
                except PermissionError as e:
                    case_record = getattr(e, 'case_record', None)
                    if case_record:
                        return self._json({
                            'error': str(e),
                            'case': case_record,
                            'federation_peer': getattr(e, 'federation_peer', None),
                            'warrant': getattr(e, 'warrant', None),
                        }, 409)
                    return self._json({'error': str(e)}, 403)
                except FederationDeliveryError as e:
                    return self._json({
                        'error': str(e),
                        'peer_host_id': e.peer_host_id,
                        'claims': _federation_claims_dict(e.claims),
                        'case': getattr(e, 'case_record', None),
                        'federation_peer': getattr(e, 'federation_peer', None),
                        'warrant': getattr(e, 'warrant', None),
                    }, 502)
                except ValueError as e:
                    return self._json({'error': str(e)}, 400)
                response = {
                    'message': 'Federation handoff dispatch executed',
                    **dispatch_runner,
                }
                if dispatch_runner.get('dispatch_runner') == 'remote_http_federation_runner':
                    response['message'] = (
                        'Federation handoff dispatch delivered to remote host '
                        'and receiver-side execution job was persisted'
                    )
                    if dispatch_runner.get('blocking_case'):
                        response['message'] = (
                            'Federation handoff dispatch delivered to remote host '
                            'and receiver-side execution job was blocked by case'
                        )
                    if dispatch_runner.get('already_dispatched'):
                        response['message'] = (
                            'Federation handoff dispatch was already delivered to the remote host'
                        )
                else:
                    response['message'] = (
                        'Federation handoff dispatch promoted to receiver-side execution job'
                    )
                    if dispatch_runner.get('blocking_case'):
                        response['message'] = (
                            'Federation handoff dispatch promoted to blocked '
                            'receiver-side execution job'
                        )
                return self._json(response)

            elif path == '/api/federation/send':
                target_host_id = (body.get('target_host_id') or '').strip()
                target_org_id = (body.get('target_org_id') or '').strip()
                message_type = (body.get('message_type') or '').strip()
                if not target_host_id:
                    return self._json({'error': 'target_host_id is required'}, 400)
                if not target_org_id:
                    return self._json({'error': 'target_org_id is required'}, 400)
                if not message_type:
                    return self._json({'error': 'message_type is required'}, 400)
                try:
                    delivery, federation_state = _deliver_federation_envelope(
                        org_id,
                        target_host_id,
                        target_org_id,
                        message_type,
                        payload=body.get('payload'),
                        actor_type='user',
                        actor_id=by,
                        session_id=_sid or '',
                        warrant_id=(body.get('warrant_id') or '').strip(),
                        commitment_id=(body.get('commitment_id') or '').strip(),
                        ttl_seconds=body.get('ttl_seconds'),
                    )
                except FederationUnavailable as e:
                    return self._json({'error': str(e)}, 503)
                except PermissionError as e:
                    case_record = getattr(e, 'case_record', None)
                    if case_record:
                        return self._json({
                            'error': str(e),
                            'case': case_record,
                            'federation_peer': getattr(e, 'federation_peer', None),
                            'warrant': getattr(e, 'warrant', None),
                        }, 409)
                    return self._json({'error': str(e)}, 403)
                except FederationDeliveryError as e:
                    return self._json({
                        'error': str(e),
                        'peer_host_id': e.peer_host_id,
                        'claims': _federation_claims_dict(e.claims),
                        'case': getattr(e, 'case_record', None),
                        'federation_peer': getattr(e, 'federation_peer', None),
                        'warrant': getattr(e, 'warrant', None),
                    }, 502)
                return self._json({
                    'message': 'Federation envelope delivered',
                    'delivery': delivery,
                    'runtime_core': {
                        'federation': federation_state,
                    },
                })

            elif path == '/api/federation/witness/archive':
                host_identity, _admission_registry = _runtime_host_state(org_id)
                if getattr(host_identity, 'role', '') != 'witness_host':
                    return self._json({
                        'error': (
                            f"Witness archive is disabled on host '{host_identity.host_id}' "
                            f"(witness_host_only)"
                        ),
                        'witness_archive': _witness_archive_snapshot(
                            org_id,
                            host_identity=host_identity,
                        ),
                    }, 503)
                envelope = (body.get('envelope') or '').strip()
                if not envelope:
                    return self._json({'error': 'envelope is required'}, 400)
                receipt = body.get('receipt')
                if not isinstance(receipt, dict) or not receipt:
                    return self._json({'error': 'receipt is required'}, 400)
                payload = body.get('payload')
                authority = _federation_authority(host_identity)
                claims = authority.validate(
                    envelope,
                    payload=payload,
                    expected_boundary_name='federation_gateway',
                )
                source_peer, source_manifest = authority.fetch_peer_manifest(
                    claims.source_host_id,
                )
                authority._validate_peer_manifest(
                    source_peer,
                    source_manifest,
                    target_institution_id=claims.source_institution_id,
                )
                target_peer, target_manifest = authority.fetch_peer_manifest(
                    claims.target_host_id,
                )
                authority._validate_peer_manifest(
                    target_peer,
                    target_manifest,
                    target_institution_id=claims.target_institution_id,
                )
                validated_receipt = authority._validate_delivery_receipt(
                    {'receipt': receipt},
                    peer_host_id=claims.target_host_id,
                    target_institution_id=claims.target_institution_id,
                    claims=claims,
                )
                record, created = archive_witness_observation(
                    WITNESS_ARCHIVE_FILE,
                    host_id=host_identity.host_id,
                    bound_org_id=org_id,
                    actor_id=by,
                    claims=claims.to_dict(),
                    receipt=validated_receipt,
                    payload=payload,
                    source_manifest=source_manifest,
                    target_manifest=target_manifest,
                )
                log_event(
                    org_id,
                    by,
                    'federation_witness_observation_archived',
                    resource=record['archive_id'],
                    outcome='success',
                    details={
                        'created': created,
                        'message_type': record.get('message_type', ''),
                        'source_host_id': record.get('source_host_id', ''),
                        'target_host_id': record.get('target_host_id', ''),
                        'receipt_id': record.get('receipt_id', ''),
                    },
                    session_id=_sid,
                )
                return self._json({
                    'message': (
                        'Witness observation archived'
                        if created else
                        f"Witness observation already archived: {record['archive_id']}"
                    ),
                    'created': created,
                    'archive': record,
                    'witness_archive': _witness_archive_snapshot(
                        org_id,
                        host_identity=host_identity,
                    ),
                })

            elif path == '/api/federation/execution-jobs/execute':
                return self._json(
                    _reject_live_execution_job_completion(org_id),
                    503,
                )

            elif path in (
                '/api/federation/peers/upsert',
                '/api/federation/peers/refresh',
                '/api/federation/peers/suspend',
                '/api/federation/peers/revoke',
            ):
                action = path.rsplit('/', 1)[-1]
                _mutate_federation_peer(org_id, action, body)
                return self._json({'message': f'Federation peer {action} applied'})

            elif path in ('/api/admission/admit', '/api/admission/suspend', '/api/admission/revoke'):
                action = path.rsplit('/', 1)[-1]
                _mutate_admission(org_id, action, body.get('org_id'))
                return self._json({'message': f'Admission {action} applied'})

            elif path == '/api/institution/charter':
                set_charter(org_id, body['text'])
                log_event(org_id, by, 'charter_set', outcome='success',
                          session_id=_sid)
                return self._json({'message': 'Charter saved'})

            elif path == '/api/institution/lifecycle':
                org_transition_lifecycle(org_id, body['state'])
                log_event(org_id, by, 'lifecycle_transitioned', outcome='success',
                          details={'new_state': body['state']}, session_id=_sid)
                return self._json({'message': f'Lifecycle transitioned to {body["state"]}'})

            elif path == '/api/agents/update':
                agent_id = (body.get('agent_id') or '').strip()
                if not agent_id:
                    return self._json({'error': 'agent_id is required'}, 400)
                update_fields = {}
                for key in ('name', 'purpose', 'rollout_state', 'status'):
                    value = body.get(key)
                    if value is not None:
                        update_fields[key] = value
                if 'approval_required' in body:
                    update_fields['approval_required'] = bool(body.get('approval_required'))
                if not update_fields:
                    return self._json({'error': 'No mutable agent fields provided'}, 400)
                update_registry_agent(agent_id, **update_fields)
                agent = get_agent(agent_id)
                if not agent or agent.get('org_id') != org_id:
                    return self._json({'error': 'Agent not found in this institution'}, 404)
                log_event(
                    org_id,
                    by,
                    'agent_updated',
                    resource=agent_id,
                    outcome='success',
                    details=update_fields,
                    session_id=_sid,
                )
                return self._json({'message': f'Agent updated: {agent_id}', 'agent': agent})

            elif path == '/api/agents/budget':
                agent_id = (body.get('agent_id') or '').strip()
                if not agent_id:
                    return self._json({'error': 'agent_id is required'}, 400)
                set_agent_budget(
                    agent_id,
                    max_per_run_usd=body.get('max_per_run_usd'),
                    max_per_day_usd=body.get('max_per_day_usd'),
                    max_per_month_usd=body.get('max_per_month_usd'),
                )
                agent = get_agent(agent_id)
                if not agent or agent.get('org_id') != org_id:
                    return self._json({'error': 'Agent not found in this institution'}, 404)
                log_event(
                    org_id,
                    by,
                    'agent_budget_updated',
                    resource=agent_id,
                    outcome='success',
                    details={'budget': agent.get('budget', {})},
                    session_id=_sid,
                )
                return self._json({'message': f'Agent budget updated: {agent_id}', 'agent': agent})

            elif path == '/api/agents/scopes':
                agent_id = (body.get('agent_id') or '').strip()
                scopes = body.get('scopes')
                if not agent_id:
                    return self._json({'error': 'agent_id is required'}, 400)
                if not isinstance(scopes, list):
                    return self._json({'error': 'scopes must be a JSON array'}, 400)
                set_agent_scopes(agent_id, scopes)
                agent = get_agent(agent_id)
                if not agent or agent.get('org_id') != org_id:
                    return self._json({'error': 'Agent not found in this institution'}, 404)
                log_event(
                    org_id,
                    by,
                    'agent_scopes_updated',
                    resource=agent_id,
                    outcome='success',
                    details={'scopes': agent.get('scopes', [])},
                    session_id=_sid,
                )
                return self._json({'message': f'Agent scopes updated: {agent_id}', 'agent': agent})

            elif path == '/api/agents/risk':
                agent_id = (body.get('agent_id') or '').strip()
                state = (body.get('state') or '').strip()
                if not agent_id:
                    return self._json({'error': 'agent_id is required'}, 400)
                if not state:
                    return self._json({'error': 'state is required'}, 400)
                set_agent_risk_state(agent_id, state)
                agent = get_agent(agent_id)
                if not agent or agent.get('org_id') != org_id:
                    return self._json({'error': 'Agent not found in this institution'}, 404)
                log_event(
                    org_id,
                    by,
                    'agent_risk_state_updated',
                    resource=agent_id,
                    outcome='success',
                    details={'state': state},
                    session_id=_sid,
                )
                return self._json({'message': f'Agent risk state updated: {agent_id}', 'agent': agent})

            elif path == '/api/agents/lifecycle':
                agent_id = (body.get('agent_id') or '').strip()
                state = (body.get('state') or '').strip()
                if not agent_id:
                    return self._json({'error': 'agent_id is required'}, 400)
                if not state:
                    return self._json({'error': 'state is required'}, 400)
                transition_agent_lifecycle(agent_id, state)
                agent = get_agent(agent_id)
                if not agent or agent.get('org_id') != org_id:
                    return self._json({'error': 'Agent not found in this institution'}, 404)
                log_event(
                    org_id,
                    by,
                    'agent_lifecycle_transitioned',
                    resource=agent_id,
                    outcome='success',
                    details={'state': state},
                    session_id=_sid,
                )
                return self._json({'message': f'Agent lifecycle transitioned: {agent_id}', 'agent': agent})

            elif path == '/api/agents/incident':
                agent_id = (body.get('agent_id') or '').strip()
                if not agent_id:
                    return self._json({'error': 'agent_id is required'}, 400)
                incident_count = record_agent_incident(agent_id)
                agent = get_agent(agent_id)
                if not agent or agent.get('org_id') != org_id:
                    return self._json({'error': 'Agent not found in this institution'}, 404)
                log_event(
                    org_id,
                    by,
                    'agent_incident_recorded',
                    resource=agent_id,
                    outcome='success',
                    details={
                        'incident_count': incident_count,
                        'risk_state': agent.get('risk_state'),
                    },
                    session_id=_sid,
                )
                return self._json({
                    'message': f'Agent incident recorded: {agent_id}',
                    'incident_count': incident_count,
                    'agent': agent,
                })

            elif path == '/api/agents/sync-economy':
                sync_from_economy()
                log_event(
                    org_id,
                    by,
                    'agent_sync_from_economy',
                    outcome='success',
                    session_id=_sid,
                )
                reg = load_registry()
                return self._json({
                    'message': 'Agent registry synced from economy ledger',
                    'agents': [
                        normalize_agent_record(a)
                        for a in reg['agents'].values()
                        if a.get('org_id') in (None, '', org_id)
                    ],
                })

            else:
                return self._json({'error': 'Not found'}, 404)

        except PermissionError as e:
            return self._json({'error': str(e)}, 403)
        except Exception as e:
            return self._json({'error': str(e)}, 400)


def main():
    global WORKSPACE_ORG_ID
    parser = argparse.ArgumentParser(description='Governed Workspace server')
    parser.add_argument('--port', type=int, default=18901)
    parser.add_argument('--org-id', default=None,
                        help='Bind this live workspace process to the founding Meridian institution only.')
    args = parser.parse_args()
    if args.org_id:
        WORKSPACE_ORG_ID = args.org_id

    # Boot with an inactive context so lifecycle recovery endpoints remain
    # reachable even if the institution has been suspended.
    inst_ctx = _resolve_workspace_context(allow_inactive=True)
    org_id, org, context_source = inst_ctx.org_id, inst_ctx.org, inst_ctx.context_source

    server_class = ThreadingHTTPServer
    server = server_class(('127.0.0.1', args.port), WorkspaceHandler)
    print(f'Governed Workspace running at http://127.0.0.1:{args.port}')
    print(f'Dashboard: http://127.0.0.1:{args.port}/')
    print(f'API:       http://127.0.0.1:{args.port}/api/status')
    print(f'Bound institution: {org.get("slug", "") if org else ""} ({org_id}) via {context_source}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nShutdown.')
        server.server_close()


if __name__ == '__main__':
    main()
