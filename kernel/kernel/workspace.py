#!/usr/bin/env python3
"""
Governed Workspace -- Owner-facing surface for the Kernel.

Serves an HTML dashboard + JSON API for all five primitives:
  Institution, Agent, Authority, Treasury, Court.

Endpoints:
  GET  /                          -> Dashboard HTML
  GET  /api/status                -> Full system snapshot (JSON)
  GET  /api/institution           -> Institution state
  GET  /api/agents                -> Agent registry
  GET  /api/authority             -> Authority state (kill switch, approvals, delegations)
  GET  /api/treasury              -> Treasury snapshot
  GET  /api/treasury/wallets      -> Wallet registry
  GET  /api/treasury/accounts     -> Treasury sub-accounts
  GET  /api/treasury/maintainers  -> Maintainer registry
  GET  /api/treasury/contributors -> Contributor registry
  GET  /api/treasury/proposals    -> Payout proposals
  GET  /api/treasury/settlement-adapters -> Settlement adapter registry
  GET  /api/treasury/settlement-adapters/readiness -> Settlement adapter readiness snapshot
  GET  /api/treasury/funding-sources -> Funding source records
  GET  /api/subscriptions         -> Institution-owned subscription service state
  GET  /api/subscriptions/delivery-targets -> Institution delivery-target calculation
  GET  /api/accounting            -> Institution-owned accounting owner-ledger state
  GET  /api/payouts               -> Payout proposals and summary
  GET  /api/admission             -> Host admission state
  GET  /api/federation            -> Federation gateway state
  GET  /api/federation/peers      -> Federation peer registry state
  GET  /api/federation/inbox      -> Institution-scoped federation inbox state
  GET  /api/federation/handoff-preview-queue -> Persisted remote handoff preview queue
  GET  /api/federation/handoff-dispatch-queue -> Persisted federation handoff dispatch queue
  GET  /api/federation/execution-jobs -> Receiver-side federated execution jobs
  GET  /api/treasury/payout-plan-preview-queue -> Persisted payout-plan preview queue
  GET  /api/treasury/payout-plan-preview-queue/inspect -> Read-only payout-plan preview queue inspection pass
  GET  /api/treasury/payout-plan-approval-candidate-queue -> Persisted payout-plan approval-candidate queue
  GET  /api/treasury/payout-plan-approval-candidate-queue/inspect -> Read-only payout-plan approval-candidate queue inspection pass
  GET  /api/federation/manifest   -> Public host federation manifest
  GET  /api/federation/witness/archive -> Witness-host archival evidence state
  GET  /api/runtimes              -> Runtime registry and contract status
  GET  /api/runtimes/<id>         -> Single runtime record
  GET  /api/court                 -> Court records
  GET  /api/warrants              -> Warrant records and summary
  GET  /api/commitments           -> Commitment records and summary
  GET  /api/cases                 -> Inter-institution cases and summary
  POST /api/authority/kill-switch -> Engage/disengage kill switch
  POST /api/authority/approve     -> Decide an approval
  POST /api/authority/request     -> Request approval
  POST /api/authority/delegate    -> Create delegation
  POST /api/authority/revoke      -> Revoke delegation
  POST /api/court/file            -> File a violation
  POST /api/court/resolve         -> Resolve a violation
  POST /api/court/appeal          -> File an appeal
  POST /api/court/decide-appeal   -> Decide an appeal
  POST /api/court/remediate       -> Lift lingering sanctions after review
  POST /api/warrants/issue        -> Issue a warrant record
  POST /api/warrants/approve      -> Approve a warrant for execution
  POST /api/warrants/stay         -> Stay a warrant before execution
  POST /api/warrants/revoke       -> Revoke a warrant before execution
  POST /api/commitments/propose   -> Propose a cross-institution commitment
  POST /api/commitments/accept    -> Accept a commitment
  POST /api/commitments/reject    -> Reject a commitment
  POST /api/commitments/breach    -> Mark a commitment as breached
  POST /api/commitments/settle    -> Mark a commitment as settled
  POST /api/cases/open            -> Open an inter-institution case
  POST /api/cases/stay            -> Stay an inter-institution case
  POST /api/cases/resolve         -> Resolve an inter-institution case
  POST /api/federation/handoff-dispatch-queue/run -> Dispatch a queued handoff locally or to a trusted remote peer
  POST /api/federation/execution-jobs/execute -> Execute a ready receiver-side federated execution job
  POST /api/treasury/contribute   -> Record owner capital contribution
  POST /api/treasury/reserve-floor -> Update reserve floor policy
  POST /api/treasury/settlement-adapters/preflight -> Validate settlement-adapter execution requirements
  POST /api/subscriptions/add     -> Create a subscription record
  POST /api/subscriptions/convert -> Convert a trial into a paid subscription
  POST /api/subscriptions/verify-payment -> Bind payment evidence to a subscription
  POST /api/subscriptions/remove  -> Cancel active subscriptions for a Telegram user
  POST /api/subscriptions/set-email -> Update subscription email metadata
  POST /api/subscriptions/record-delivery -> Append a delivery record
  POST /api/accounting/expense    -> Record an owner-paid expense in the owner ledger
  POST /api/accounting/reimburse  -> Reimburse an owner-paid expense from treasury
  POST /api/accounting/draw       -> Take an owner draw from treasury above reserve floor
  POST /api/payouts/propose       -> Create a payout proposal draft
  POST /api/payouts/submit        -> Submit a payout proposal for review
  POST /api/payouts/review        -> Move a payout proposal into review
  POST /api/payouts/approve       -> Owner-approve a payout proposal
  POST /api/payouts/open-dispute-window -> Start the payout dispute window
  POST /api/payouts/reject        -> Reject a payout proposal
  POST /api/payouts/cancel        -> Cancel a payout proposal
  POST /api/payouts/execute       -> Execute an approved payout
  POST /api/session/issue         -> Issue session token (requires auth)
  GET  /api/session/validate      -> Validate session token
  POST /api/session/revoke        -> Revoke a session
  POST /api/admission/admit       -> Admit an institution on this host
  POST /api/admission/suspend     -> Suspend an admitted institution on this host
  POST /api/admission/revoke      -> Revoke an institution on this host
  POST /api/federation/peers/upsert -> Create or update a federation peer
  POST /api/federation/peers/refresh -> Refresh peer capability snapshot from its public manifest
  POST /api/federation/peers/suspend -> Suspend a federation peer
  POST /api/federation/peers/revoke -> Revoke a federation peer
  POST /api/federation/send       -> Deliver a federation envelope to a trusted peer
  POST /api/federation/receive    -> Validate and consume a federation envelope
  POST /api/federation/handoff-preview-queue/acknowledge -> Acknowledge a remote handoff preview and queue a dispatch record
  POST /api/federation/witness/archive -> Archive independently validated witness evidence
  POST /api/institution/charter   -> Set charter
  POST /api/institution/lifecycle -> Transition lifecycle

Run:
  python3 workspace.py                    # port 18901
  python3 workspace.py --port 18902
  python3 workspace.py --org-id <org>    # bind this process to one institution

When workspace credentials are configured, the dashboard and JSON API are
owner-authenticated with HTTP Basic auth.  Session tokens (Authorization:
Bearer) are also accepted as an alternative auth path.

Institution context:
  The built-in workspace is a founding-institution reference surface.  All
  HTTP endpoints bind to one institution selected at process start.
  The underlying kernel helpers accept org_id, but exposing arbitrary org
  selection over HTTP is intentionally deferred until an org-scoped auth
  model exists.
"""
import argparse
import copy
import base64
import datetime
import hashlib
import hmac
import json
import os
import sys
from types import SimpleNamespace
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse, parse_qs

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(PLATFORM_DIR)
EXAMPLES_INTELLIGENCE_DIR = os.path.join(WORKSPACE, 'examples', 'intelligence')
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
sys.path.insert(0, PLATFORM_DIR)
if os.path.isdir(EXAMPLES_INTELLIGENCE_DIR):
    sys.path.insert(0, EXAMPLES_INTELLIGENCE_DIR)

from organizations import (load_orgs, set_charter, set_policy_defaults,
                           transition_lifecycle as org_transition_lifecycle)
from agent_registry import load_registry, normalize_agent_record, sync_from_economy
from audit import log_event, query_events, tail_events

import importlib.util

# Import authority, treasury, court via their public APIs
from authority import (check_authority, request_approval, decide_approval,
                       delegate, revoke_delegation, engage_kill_switch,
                       disengage_kill_switch, get_pending_approvals,
                       get_sprint_lead, is_kill_switch_engaged, _load_queue)
from treasury import (treasury_snapshot, get_balance, get_runway, check_budget,
                      contribute_owner_capital, set_reserve_floor_policy,
                      load_wallets, load_treasury_accounts, load_maintainers,
                      load_contributors, load_payout_proposals, load_funding_sources,
                      list_settlement_adapters, settlement_adapter_summary,
                      settlement_adapter_readiness_snapshot,
                      preflight_settlement_adapter,
                      settlement_adapter_contract_snapshot, settlement_adapter_contract_digest,
                      get_payout_proposal,
                      list_payout_proposals, payout_proposal_summary,
                      create_payout_proposal, submit_payout_proposal,
                      review_payout_proposal, approve_payout_proposal,
                      open_payout_dispute_window, reject_payout_proposal,
                      cancel_payout_proposal, execute_payout_proposal,
                      promote_payout_plan_preview_to_approval_candidate,
                      inspect_payout_plan_approval_candidate_queue,
                      payout_plan_approval_candidate_queue_snapshot,
                      payout_execution_queue_snapshot)
from subscription_service import (
    add_subscription,
    active_delivery_targets,
    cancel_active,
    convert_trial_subscription,
    load_subscriptions,
    record_delivery,
    set_email,
    subscription_summary,
    verify_subscription_payment,
)
from accounting_service import (
    accounting_snapshot,
    record_owner_expense,
    reimburse_owner,
    take_owner_draw,
)
from runtime_adapter import load_runtimes, get_runtime, check_all_contracts
from court import (file_violation, get_violations, resolve_violation,
                   file_appeal, decide_appeal, get_agent_record, auto_review,
                   get_restrictions, remediate, _load_records, VIOLATION_TYPES)
from session import SessionAuthority
from warrants import (
    list_warrants,
    get_warrant,
    issue_warrant,
    review_warrant,
    validate_warrant_for_execution,
    mark_warrant_executed,
    warrant_action_for_message,
)
from commitments import (
    accept_commitment,
    breach_commitment,
    commitment_summary,
    get_commitment,
    list_commitments,
    sync_federated_commitment_proposal,
    record_delivery_ref,
    record_settlement_ref,
    reject_commitment,
    propose_commitment,
    settle_commitment,
    validate_commitment_for_acceptance_dispatch,
    validate_commitment_for_breach_notice,
    validate_commitment_for_delivery,
    validate_commitment_for_proposal_dispatch,
    validate_commitment_for_settlement,
)
from cases import (
    blocked_peer_host_ids,
    blocking_commitment_ids,
    blocking_commitment_case,
    blocking_peer_case,
    case_requires_peer_block,
    case_targets_peer,
    case_summary,
    get_case,
    ensure_case_for_delivery_failure,
    ensure_case_for_commitment_breach,
    list_cases,
    open_case,
    resolve_case,
    stay_case,
)
import cases as cases_module
from federation import (
    FederationAuthority,
    FederationPeer,
    ReplayStore,
    load_peer_registry,
    upsert_peer_registry_entry,
    refresh_peer_registry_entry,
    set_peer_trust_state,
    FederationUnavailable,
    FederationDeliveryError,
    FederationValidationError,
    FederationReplayError,
)
from federation_inbox import (
    load_inbox_entries,
    summarize_inbox_entries,
    upsert_inbox_entry,
)
from federated_execution_jobs import (
    get_execution_job,
    list_execution_jobs,
    execution_job_summary,
    upsert_execution_job,
)
from federation_handoff_queue import (
    acknowledge_handoff_preview,
    handoff_preview_queue_snapshot as _handoff_preview_queue_snapshot,
    upsert_handoff_preview,
)
from federation_handoff_dispatch_queue import (
    get_handoff_dispatch_record,
    handoff_dispatch_queue_snapshot as _handoff_dispatch_queue_snapshot,
    mark_handoff_dispatch_record_dispatched,
    promote_acknowledged_handoff_preview_to_dispatch_record,
)
from payout_plan_preview_queue import (
    inspect_payout_plan_preview_queue as _payout_plan_preview_queue_inspection,
    payout_plan_preview_queue_snapshot as _payout_plan_preview_queue_snapshot,
    payout_plan_preview_queue_summary,
)
from witness_archive import (
    archive_witness_observation,
    list_witness_observations,
    witness_archive_summary,
)
from institution_context import (
    InstitutionContext,
    WORKSPACE_BOUNDARY,
    runtime_core_snapshot,
)
from runtime_host import (
    load_host_identity,
    load_admission_registry,
    ensure_org_admitted,
    set_admission_state,
)


import court_service
import execution_job_service
import federation_service
import treasury_service

# Process-level session authority (tokens do not survive restarts unless
# MERIDIAN_SESSION_SECRET is set in the environment).
_session_revocation_file = (
    os.environ.get('MERIDIAN_SESSION_REVOCATIONS_FILE', '').strip() or None
)
if not _session_revocation_file and os.environ.get('MERIDIAN_SESSION_SECRET', '').strip():
    # Persistent signing key → revocations must also persist.
    _session_revocation_file = os.path.join(PLATFORM_DIR, '.session_revocations')

_session_authority = SessionAuthority(revocation_file=_session_revocation_file)


def _treasury_service_deps():
    return SimpleNamespace(
        treasury_snapshot=treasury_snapshot,
        load_wallets=load_wallets,
        load_treasury_accounts=load_treasury_accounts,
        load_maintainers=load_maintainers,
        load_contributors=load_contributors,
        load_payout_proposals=load_payout_proposals,
        settlement_adapter_summary=settlement_adapter_summary,
        list_settlement_adapters=list_settlement_adapters,
        _runtime_host_state=_runtime_host_state,
        _settlement_adapter_readiness_snapshot=_settlement_adapter_readiness_snapshot,
        load_funding_sources=load_funding_sources,
        _payout_plan_preview_queue_snapshot=_payout_plan_preview_queue_snapshot,
        _payout_plan_preview_queue_inspection=_payout_plan_preview_queue_inspection,
        payout_plan_approval_candidate_queue_snapshot=payout_plan_approval_candidate_queue_snapshot,
        payout_execution_queue_snapshot=payout_execution_queue_snapshot,
        inspect_payout_plan_approval_candidate_queue=inspect_payout_plan_approval_candidate_queue,
        _payout_snapshot=_payout_snapshot,
        contribute_owner_capital=contribute_owner_capital,
        set_reserve_floor_policy=set_reserve_floor_policy,
        preflight_settlement_adapter=preflight_settlement_adapter,
        log_event=log_event,
        create_payout_proposal=create_payout_proposal,
        payout_proposal_summary=payout_proposal_summary,
        submit_payout_proposal=submit_payout_proposal,
        review_payout_proposal=review_payout_proposal,
        approve_payout_proposal=approve_payout_proposal,
        open_payout_dispute_window=open_payout_dispute_window,
        reject_payout_proposal=reject_payout_proposal,
        cancel_payout_proposal=cancel_payout_proposal,
        promote_payout_plan_preview_to_approval_candidate=promote_payout_plan_preview_to_approval_candidate,
        get_payout_proposal=get_payout_proposal,
        _maybe_block_commitment_settlement=_maybe_block_commitment_settlement,
        validate_warrant_for_execution=validate_warrant_for_execution,
        execute_payout_proposal=execute_payout_proposal,
        mark_warrant_executed=mark_warrant_executed,
    )


def _execution_job_service_deps():
    return SimpleNamespace(
        _federation_execution_jobs_snapshot=_federation_execution_jobs_snapshot,
        get_execution_job=get_execution_job,
        get_execution_job_by_local_warrant=get_execution_job_by_local_warrant,
        _complete_federated_execution_job=_complete_federated_execution_job,
        FederationUnavailable=FederationUnavailable,
        FederationDeliveryError=FederationDeliveryError,
        _federation_claims_dict=_federation_claims_dict,
    )


def _federation_service_deps():
    return SimpleNamespace(
        _runtime_host_state=_runtime_host_state,
        _federation_snapshot=_federation_snapshot,
        _federation_inbox_snapshot=_federation_inbox_snapshot,
        _handoff_preview_queue_snapshot=_handoff_preview_queue_snapshot,
        _handoff_dispatch_queue_snapshot=_handoff_dispatch_queue_snapshot,
        _federation_manifest=_federation_manifest,
        _witness_archive_snapshot=_witness_archive_snapshot,
        _admission_snapshot=_admission_snapshot,
        _control_plane_notice_validation_peer_registry=_control_plane_notice_validation_peer_registry,
        _accept_federation_request=_accept_federation_request,
        _federation_receipt=_federation_receipt,
        _federation_inbox_entry=_federation_inbox_entry,
        _process_received_federation_message=_process_received_federation_message,
        summarize_inbox_entries=summarize_inbox_entries,
        _deliver_federation_envelope=_deliver_federation_envelope,
        _acknowledge_and_dispatch_remote_handoff_preview=_acknowledge_and_dispatch_remote_handoff_preview,
        _run_federation_dispatch=_run_federation_dispatch,
        _mutate_federation_peer=_mutate_federation_peer,
        _mutate_admission=_mutate_admission,
        _federation_authority=_federation_authority,
        _federation_claims_dict=_federation_claims_dict,
        archive_witness_observation=archive_witness_observation,
        WITNESS_ARCHIVE_FILE=WITNESS_ARCHIVE_FILE,
        log_event=log_event,
        FederationUnavailable=FederationUnavailable,
        FederationDeliveryError=FederationDeliveryError,
        FederationValidationError=FederationValidationError,
        FederationReplayError=FederationReplayError,
    )


def _court_service_deps():
    return SimpleNamespace(
        _load_records=_load_records,
        list_warrants=list_warrants,
        _warrant_summary=_warrant_summary,
        _commitment_snapshot=_commitment_snapshot,
        _case_snapshot=_case_snapshot,
        file_violation=file_violation,
        resolve_violation=resolve_violation,
        file_appeal=file_appeal,
        decide_appeal=decide_appeal,
        auto_review=auto_review,
        remediate=remediate,
        issue_warrant=issue_warrant,
        review_warrant=review_warrant,
        _sync_execution_job_for_warrant_review=_sync_execution_job_for_warrant_review,
        _deliver_execution_job_court_notice=_deliver_execution_job_court_notice,
        propose_commitment=propose_commitment,
        _commitment_summary=_commitment_summary,
        _deliver_federation_envelope=_deliver_federation_envelope,
        _federation_claims_dict=_federation_claims_dict,
        get_payout_proposal=get_payout_proposal,
        _maybe_block_commitment_settlement=_maybe_block_commitment_settlement,
        record_settlement_ref=record_settlement_ref,
        accept_commitment=accept_commitment,
        reject_commitment=reject_commitment,
        breach_commitment=breach_commitment,
        settle_commitment=settle_commitment,
        _maybe_open_case_for_commitment_breach=_maybe_open_case_for_commitment_breach,
        _maybe_stay_warrant_for_case=_maybe_stay_warrant_for_case,
        open_case=open_case,
        _case_notice_delivery_context=_case_notice_delivery_context,
        _maybe_suspend_peer_for_case=_maybe_suspend_peer_for_case,
        _deliver_case_notice=_deliver_case_notice,
        get_case=get_case,
        stay_case=stay_case,
        resolve_case=resolve_case,
        _maybe_restore_peer_for_case=_maybe_restore_peer_for_case,
        log_event=log_event,
        FederationUnavailable=FederationUnavailable,
        FederationDeliveryError=FederationDeliveryError,
        FederationValidationError=FederationValidationError,
    )


_WORKSPACE_GET_SERVICES = (
    (treasury_service, _treasury_service_deps),
    (federation_service, _federation_service_deps),
    (court_service, _court_service_deps),
    (execution_job_service, _execution_job_service_deps),
)

_WORKSPACE_INGRESS_POST_SERVICES = (
    (federation_service, _federation_service_deps),
)

_WORKSPACE_POST_SERVICES = (
    (treasury_service, _treasury_service_deps),
    (federation_service, _federation_service_deps),
    (court_service, _court_service_deps),
    (execution_job_service, _execution_job_service_deps),
)


_SERVICE_HANDLED = object()


def _dispatch_workspace_get_service(handler, path, *, org_id, inst_ctx=None, request_context=None, auth_context=None):
    for service_module, deps_factory in _WORKSPACE_GET_SERVICES:
        result = service_module.handle_get(
            handler,
            path,
            org_id=org_id,
            inst_ctx=inst_ctx,
            request_context=request_context,
            auth_context=auth_context,
            deps=deps_factory(),
        )
        if result is not service_module.NOT_HANDLED:
            return _SERVICE_HANDLED if result is None else result
    return None


def _dispatch_workspace_ingress_post_service(handler, path, *, body, inst_ctx):
    for service_module, deps_factory in _WORKSPACE_INGRESS_POST_SERVICES:
        handle = getattr(service_module, 'handle_ingress_post', None)
        if handle is None:
            continue
        result = handle(
            handler,
            path,
            body=body,
            inst_ctx=inst_ctx,
            deps=deps_factory(),
        )
        if result is not service_module.NOT_HANDLED:
            return _SERVICE_HANDLED if result is None else result
    return None


def _dispatch_workspace_post_service(handler, path, *, body, org_id, actor_id, session_id, auth_context, inst_ctx=None):
    for service_module, deps_factory in _WORKSPACE_POST_SERVICES:
        result = service_module.handle_post(
            handler,
            path,
            body=body,
            org_id=org_id,
            actor_id=actor_id,
            session_id=session_id,
            auth_context=auth_context,
            inst_ctx=inst_ctx,
            deps=deps_factory(),
        )
        if result is not service_module.NOT_HANDLED:
            return _SERVICE_HANDLED if result is None else result
    return None

# Optional: CI vertical import from the example vertical if present
_ci_vertical_available = False
try:
    from ci_vertical import PIPELINE_PHASES, _phase_gate_snapshot, get_agent_remediation
    _ci_vertical_available = True
except ImportError:
    pass

# Optional: Phase machine import
_phase_machine_available = False
try:
    from phase_machine import current_phase, PHASES as PHASE_DEFS
    _phase_machine_available = True
except ImportError:
    pass


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


ROLE_RANK = {
    'viewer': 0,
    'member': 1,
    'admin': 2,
    'owner': 3,
}

MUTATION_ROLE_REQUIREMENTS = {
    '/api/authority/kill-switch': 'admin',
    '/api/authority/approve': 'admin',
    '/api/authority/request': 'member',
    '/api/authority/delegate': 'admin',
    '/api/authority/revoke': 'admin',
    '/api/court/file': 'member',
    '/api/court/resolve': 'admin',
    '/api/court/appeal': 'member',
    '/api/court/decide-appeal': 'admin',
    '/api/court/auto-review': 'admin',
    '/api/court/remediate': 'admin',
    '/api/warrants/issue': 'admin',
    '/api/warrants/approve': 'admin',
    '/api/warrants/stay': 'admin',
    '/api/warrants/revoke': 'admin',
    '/api/commitments/propose': 'admin',
    '/api/commitments/accept': 'admin',
    '/api/commitments/reject': 'admin',
    '/api/commitments/breach': 'admin',
    '/api/commitments/settle': 'admin',
    '/api/cases/open': 'admin',
    '/api/cases/stay': 'admin',
    '/api/cases/resolve': 'admin',
    '/api/federation/execution-jobs/execute': 'admin',
    '/api/federation/handoff-preview-queue/acknowledge': 'admin',
    '/api/federation/handoff-dispatch-queue/run': 'admin',
    '/api/treasury/contribute': 'owner',
    '/api/treasury/reserve-floor': 'owner',
    '/api/treasury/settlement-adapters/preflight': 'member',
    '/api/subscriptions/add': 'admin',
    '/api/subscriptions/convert': 'admin',
    '/api/subscriptions/verify-payment': 'admin',
    '/api/subscriptions/remove': 'admin',
    '/api/subscriptions/set-email': 'admin',
    '/api/subscriptions/record-delivery': 'admin',
    '/api/accounting/expense': 'owner',
    '/api/accounting/reimburse': 'owner',
    '/api/accounting/draw': 'owner',
    '/api/payouts/propose': 'member',
    '/api/payouts/submit': 'member',
    '/api/payouts/review': 'admin',
    '/api/payouts/approve': 'owner',
    '/api/payouts/open-dispute-window': 'owner',
    '/api/payouts/reject': 'admin',
    '/api/payouts/cancel': 'member',
    '/api/payouts/execute': 'owner',
    '/api/admission/admit': 'owner',
    '/api/admission/suspend': 'owner',
    '/api/admission/revoke': 'owner',
    '/api/federation/send': 'admin',
    '/api/federation/witness/archive': 'admin',
    '/api/federation/peers/upsert': 'owner',
    '/api/federation/peers/refresh': 'owner',
    '/api/federation/peers/suspend': 'owner',
    '/api/federation/peers/revoke': 'owner',
    '/api/institution/charter': 'admin',
    '/api/institution/lifecycle': 'owner',
    '/api/session/issue': 'member',
    '/api/session/revoke': 'admin',
}


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


def _resolve_workspace_context():
    """Bind this workspace process to exactly one institution.

    Returns an InstitutionContext backed by the WORKSPACE_BOUNDARY declaration.
    Resolution order: explicit --org-id > credential org scope > founding default.
    """
    configured_org_id = WORKSPACE_ORG_ID
    cred_user, cred_password, credential_org_id, _credential_user_id = _load_workspace_credentials()
    credential_scope_active = bool(cred_user and cred_password and credential_org_id)
    if configured_org_id and credential_scope_active and configured_org_id != credential_org_id:
        raise RuntimeError(
            f"Workspace credentials are scoped to institution '{credential_org_id}', "
            f"but process binding requested '{configured_org_id}'"
        )
    if configured_org_id:
        org = load_orgs().get('organizations', {}).get(configured_org_id)
        if not org:
            raise RuntimeError(f'Configured workspace org not found: {configured_org_id}')
        ctx = InstitutionContext.bind(configured_org_id, org, 'configured_org', WORKSPACE_BOUNDARY)
        _runtime_host_state(ctx.org_id)
        return ctx
    if credential_scope_active:
        org = load_orgs().get('organizations', {}).get(credential_org_id)
        if not org:
            raise RuntimeError(f'Credential-scoped workspace org not found: {credential_org_id}')
        ctx = InstitutionContext.bind(credential_org_id, org, 'credentials_org', WORKSPACE_BOUNDARY)
        _runtime_host_state(ctx.org_id)
        return ctx
    ctx = InstitutionContext.resolve(WORKSPACE_BOUNDARY)
    _runtime_host_state(ctx.org_id)
    return ctx


def _runtime_host_state(bound_org_id):
    host_identity = load_host_identity(
        RUNTIME_HOST_IDENTITY_FILE,
        supported_boundaries=[
            'workspace',
            'cli',
            'federation_gateway',
            'mcp_service',
            'payment_monitor',
            'subscriptions',
            'accounting',
        ],
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


def _federation_management_state(host_identity):
    if getattr(host_identity, 'role', '') == 'witness_host':
        return {
            'management_mode': 'witness_read_only',
            'mutation_enabled': False,
            'mutation_disabled_reason': 'witness_host_read_only',
        }
    return {
        'management_mode': 'workspace_api_file_backed',
        'mutation_enabled': True,
        'mutation_disabled_reason': '',
    }


def _federation_snapshot(bound_org_id, host_identity=None, admission_registry=None, peer_registry=None):
    if host_identity is None or admission_registry is None:
        host_identity, admission_registry = _runtime_host_state(bound_org_id)
    if peer_registry is None:
        peer_registry = load_peer_registry(
            FEDERATION_PEERS_FILE,
            host_identity=host_identity,
        )
    snapshot = _federation_authority(host_identity, peer_registry=peer_registry).snapshot(
        bound_org_id=bound_org_id,
        admission_registry=admission_registry,
    )
    snapshot.update(_federation_management_state(host_identity))
    snapshot['inbox_summary'] = summarize_inbox_entries(bound_org_id)
    snapshot['execution_job_summary'] = execution_job_summary(bound_org_id)
    snapshot['handoff_preview'] = _routing_handoff_preview_snapshot(
        bound_org_id,
        host_identity=host_identity,
        admission_registry=admission_registry,
        peer_registry=peer_registry,
        org_registry=load_orgs().get('organizations', {}),
    )
    snapshot['handoff_preview_queue'] = _handoff_preview_queue_snapshot(bound_org_id)
    snapshot['handoff_dispatch_queue'] = _handoff_dispatch_queue_snapshot(bound_org_id)
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
        'federation': {
            key: value
            for key, value in federation.items()
            if key not in ('peers', 'trusted_peers', 'trusted_peer_ids')
        },
        'witness_archive': _witness_archive_snapshot(
            context.org_id,
            host_identity=host_identity,
        ),
    }


def _admission_management_state(host_identity):
    if getattr(host_identity, 'role', '') == 'witness_host':
        return {
            'management_mode': 'witness_read_only',
            'mutation_enabled': False,
            'mutation_disabled_reason': 'witness_host_read_only',
        }
    return {
        'management_mode': 'workspace_api_file_backed',
        'mutation_enabled': True,
        'mutation_disabled_reason': '',
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
    host_identity, _admission_registry = _runtime_host_state(bound_org_id)
    management = _admission_management_state(host_identity)
    if not management['mutation_enabled']:
        raise PermissionError(
            f"Admission mutations are disabled on host '{host_identity.host_id}' "
            f"({management['mutation_disabled_reason']})"
        )
    target_org_id = (target_org_id or '').strip()
    if not target_org_id:
        raise ValueError('org_id is required')
    if target_org_id not in load_orgs().get('organizations', {}):
        raise LookupError(f"Institution '{target_org_id}' is not registered")
    if action in ('suspend', 'revoke') and target_org_id == bound_org_id:
        raise PermissionError(
            'Cannot suspend or revoke the currently bound institution from its own workspace process'
        )
    status_map = {
        'admit': 'admitted',
        'suspend': 'suspended',
        'revoke': 'revoked',
    }
    if action not in status_map:
        raise ValueError(f'Unsupported admission action: {action}')
    updated = set_admission_state(
        RUNTIME_ADMISSION_FILE,
        target_org_id,
        status_map[action],
        bound_org_id=bound_org_id,
        host_identity=host_identity,
        source='workspace_api',
    )
    return _admission_snapshot(
        bound_org_id,
        host_identity=host_identity,
        admission_registry=updated,
    )


def _accept_federation_request(bound_org_id, envelope, payload=None, *, peer_registry=None):
    host_identity, admission_registry = _runtime_host_state(bound_org_id)
    authority = _federation_authority(host_identity)
    if peer_registry is not None:
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
        supported_boundaries=[
            'workspace',
            'cli',
            'federation_gateway',
            'mcp_service',
            'payment_monitor',
            'subscriptions',
            'accounting',
        ],
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
    host_identity, admission_registry = _runtime_host_state(bound_org_id)
    management = _federation_management_state(host_identity)
    if not management['mutation_enabled']:
        raise PermissionError(
            f"Federation peer mutations are disabled on host '{host_identity.host_id}' "
            f"({management['mutation_disabled_reason']})"
        )

    payload = dict(payload or {})
    peer_host_id = (payload.get('peer_host_id') or payload.get('host_id') or '').strip()
    if not peer_host_id:
        raise ValueError('peer_host_id is required')
    if peer_host_id == host_identity.host_id:
        raise PermissionError('Cannot register the current host as its own federation peer')

    if action == 'upsert':
        peer_registry = upsert_peer_registry_entry(
            FEDERATION_PEERS_FILE,
            peer_host_id,
            host_identity=host_identity,
            label=payload.get('label'),
            transport=payload.get('transport'),
            endpoint_url=payload.get('endpoint_url'),
            trust_state=payload.get('trust_state'),
            shared_secret=payload.get('shared_secret'),
            witness_archive_user=payload.get('witness_archive_user'),
            witness_archive_pass=payload.get('witness_archive_pass'),
            admitted_org_ids=payload.get('admitted_org_ids'),
        )
    elif action == 'refresh':
        peer_registry = refresh_peer_registry_entry(
            FEDERATION_PEERS_FILE,
            peer_host_id,
            host_identity=host_identity,
            target_org_id=(payload.get('target_org_id') or '').strip() or None,
        )
    else:
        status_map = {
            'suspend': 'suspended',
            'revoke': 'revoked',
        }
        if action not in status_map:
            raise ValueError(f'Unsupported federation peer action: {action}')
        peer_registry = set_peer_trust_state(
            FEDERATION_PEERS_FILE,
            peer_host_id,
            status_map[action],
            host_identity=host_identity,
        )
    return _federation_snapshot(
        bound_org_id,
        host_identity=host_identity,
        admission_registry=admission_registry,
        peer_registry=peer_registry,
    )


def _federation_claims_dict(claims):
    if not claims:
        return {}
    if isinstance(claims, dict):
        return dict(claims)
    if hasattr(claims, 'to_dict'):
        return claims.to_dict()
    if hasattr(claims, '__dict__'):
        return {
            key: value
            for key, value in vars(claims).items()
            if not key.startswith('_')
        }
    claim_fields = (
        'envelope_id',
        'source_host_id',
        'source_institution_id',
        'target_host_id',
        'target_institution_id',
        'actor_type',
        'actor_id',
        'session_id',
        'boundary_name',
        'identity_model',
        'message_type',
        'warrant_id',
        'commitment_id',
        'payload_hash',
        'nonce',
    )
    extracted = {}
    for field in claim_fields:
        if hasattr(claims, field):
            extracted[field] = getattr(claims, field)
    if extracted:
        return extracted
    return {}


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


def _execution_request_runtime_object(claims, receipt, payload=None):
    claim_data = _federation_claims_dict(claims)
    receipt_data = dict(receipt or {})
    request_payload = payload if isinstance(payload, dict) else {}
    evidence_refs = [f"federation_envelope:{claim_data.get('envelope_id', '')}"]
    receipt_id = (receipt_data.get('receipt_id') or '').strip()
    if receipt_id:
        evidence_refs.append(f'federation_receipt:{receipt_id}')
    payload_hash = (claim_data.get('payload_hash') or '').strip()
    if payload_hash:
        evidence_refs.append(f'payload_hash:{payload_hash}')
    return {
        'request_id': claim_data.get('envelope_id', ''),
        'request_type': claim_data.get('message_type', 'execution_request') or 'execution_request',
        'claims': {
            'envelope_id': claim_data.get('envelope_id', ''),
            'source_host_id': claim_data.get('source_host_id', ''),
            'source_institution_id': claim_data.get('source_institution_id', ''),
            'target_host_id': claim_data.get('target_host_id', ''),
            'target_institution_id': claim_data.get('target_institution_id', ''),
            'actor_type': claim_data.get('actor_type', ''),
            'actor_id': claim_data.get('actor_id', ''),
            'session_id': claim_data.get('session_id', ''),
            'boundary_name': claim_data.get('boundary_name', ''),
            'identity_model': claim_data.get('identity_model', ''),
            'message_type': claim_data.get('message_type', ''),
            'sender_warrant_id': claim_data.get('warrant_id', ''),
            'commitment_id': claim_data.get('commitment_id', ''),
            'payload_hash': claim_data.get('payload_hash', ''),
        },
        'receipt': {
            'receipt_id': receipt_data.get('receipt_id', ''),
            'accepted_at': receipt_data.get('accepted_at', ''),
            'receiver_host_id': receipt_data.get('receiver_host_id', ''),
            'receiver_institution_id': receipt_data.get('receiver_institution_id', ''),
        },
        'payload': request_payload,
        'payload_hash': claim_data.get('payload_hash', ''),
        'evidence_refs': evidence_refs,
    }


def _execution_gap_runtime_object(request, *, status, metadata=None):
    request = dict(request or {})
    return {
        'request_id': (request.get('request_id') or '').strip(),
        'request_type': (request.get('request_type') or '').strip(),
        'status': (status or '').strip(),
        'metadata': dict(metadata or {}),
        'evidence_refs': list(request.get('evidence_refs') or []),
    }


def _receiver_execution_warrant_payload_from_job(job):
    record = dict(job or {})
    request = dict(record.get('request') or {})
    claims = dict(request.get('claims') or {})
    if not claims:
        claims = {
            'source_host_id': (record.get('source_host_id') or '').strip(),
            'source_institution_id': (record.get('source_institution_id') or '').strip(),
            'target_host_id': (record.get('target_host_id') or '').strip(),
            'target_institution_id': (record.get('target_institution_id') or '').strip(),
            'message_type': (record.get('message_type') or '').strip(),
            'boundary_name': (record.get('boundary_name') or '').strip(),
            'identity_model': (record.get('identity_model') or '').strip(),
            'sender_warrant_id': (record.get('sender_warrant_id') or '').strip(),
            'commitment_id': (record.get('commitment_id') or '').strip(),
            'payload_hash': (record.get('payload_hash') or '').strip(),
        }
    payload = request.get('payload') if isinstance(request.get('payload'), dict) else {}
    if not payload:
        payload = record.get('payload') if isinstance(record.get('payload'), dict) else {}
    return {
        'request_id': (request.get('request_id') or record.get('envelope_id') or '').strip(),
        'request_type': (request.get('request_type') or record.get('message_type') or 'execution_request').strip(),
        'source_host_id': (claims.get('source_host_id') or '').strip(),
        'source_institution_id': (claims.get('source_institution_id') or '').strip(),
        'target_host_id': (claims.get('target_host_id') or '').strip(),
        'target_institution_id': (claims.get('target_institution_id') or '').strip(),
        'message_type': (claims.get('message_type') or '').strip(),
        'boundary_name': (claims.get('boundary_name') or '').strip(),
        'identity_model': (claims.get('identity_model') or '').strip(),
        'sender_warrant_id': (claims.get('sender_warrant_id') or record.get('sender_warrant_id') or '').strip(),
        'commitment_id': (claims.get('commitment_id') or '').strip(),
        'payload': payload,
        'evidence_refs': list(request.get('evidence_refs') or []),
    }


def _execution_job_warrant_validation_payload(job):
    record = dict(job or {})
    request = record.get('request')
    if isinstance(request, dict) and request:
        return dict(request)
    return _receiver_execution_warrant_payload_from_job(record)


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
        'mutation_enabled': True,
        'mutation_disabled_reason': '',
        'storage_model': 'capsule_canonical',
        'boundary_name': 'federation_gateway',
        'identity_model': 'signed_host_service',
        'execution_route': '/api/federation/execution-jobs/execute',
        'required_local_warrant_state': 'approved',
        'summary': execution_job_summary(bound_org_id),
        'jobs': jobs,
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
        request_object = _execution_request_runtime_object(claims, receipt, payload)
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
            'request': request_object,
            'gap': _execution_gap_runtime_object(request_object, status='blocked', metadata={
                'case_id': blocking_case.get('case_id', ''),
                'case_status': blocking_case.get('status', ''),
                'claim_type': blocking_case.get('claim_type', ''),
            }),
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

    request_object = _execution_request_runtime_object(claims, receipt, payload)
    receiver_warrant = issue_warrant(
        bound_org_id,
        'federated_execution',
        'federation_gateway',
        actor_id,
        session_id='',
        request_payload=request_object,
        risk_class='high',
        evidence_refs=request_object['evidence_refs'],
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
        'request': request_object,
        'gap': _execution_gap_runtime_object(request_object, status='pending_local_warrant', metadata={
            'source_boundary_name': claims.boundary_name,
        }),
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


def get_execution_job_by_local_warrant(warrant_id, org_id):
    warrant_id = (warrant_id or '').strip()
    if not warrant_id:
        return None
    return next(
        (
            job for job in list_execution_jobs(org_id)
            if (job.get('local_warrant_id') or '').strip() == warrant_id
        ),
        None,
    )


def sync_execution_job_for_local_warrant(org_id, warrant_id, *, state, note='', metadata=None):
    existing = get_execution_job_by_local_warrant(warrant_id, org_id)
    if not existing:
        return None
    merged_metadata = dict(existing.get('metadata') or {})
    merged_metadata.update(metadata or {})
    return upsert_execution_job(
        org_id,
        job_id=existing.get('job_id', ''),
        state=state,
        note=note or existing.get('note', ''),
        metadata=merged_metadata,
    )


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
    job = synced
    job = _execution_job_view(bound_org_id, job)
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


def _execution_job_proof_ref(job):
    job_id = (job.get('job_id') or '').strip()
    if not job_id:
        raise ValueError('job_id is required')
    return f"fexec_{job_id}"


def _execution_job_execution_refs(bound_org_id, job, *, actor_id='', note=''):
    record = dict(job or {})
    executed_at = _now()
    tx_ref = (record.get('execution_refs') or {}).get('tx_ref') or _execution_job_proof_ref(record)
    return {
        'tx_ref': tx_ref,
        'tx_hash': '',
        'settlement_adapter': 'federated_execution_proof',
        'proof_type': 'federated_execution_job',
        'verification_state': 'receiver_local_final',
        'finality_state': 'receiver_local_final',
        'linked_commitment_id': (record.get('commitment_id') or '').strip(),
        'proof': {
            'mode': 'receiver_local_execution_job',
            'job_id': record.get('job_id', ''),
            'envelope_id': record.get('envelope_id', ''),
            'payload_hash': record.get('payload_hash', ''),
            'receipt_id': record.get('receipt_id', ''),
            'local_warrant_id': record.get('local_warrant_id', ''),
            'sender_warrant_id': record.get('sender_warrant_id', ''),
            'source_host_id': record.get('source_host_id', ''),
            'source_institution_id': record.get('source_institution_id', ''),
            'target_host_id': record.get('target_host_id', ''),
            'target_institution_id': record.get('target_institution_id', ''),
            'executed_by': (actor_id or '').strip(),
            'executed_at': executed_at,
            'note': note or '',
            'bound_org_id': (bound_org_id or '').strip(),
        },
    }


def _execution_job_settlement_notice_payload(job, execution_refs):
    refs = dict(execution_refs or {})
    return {
        'tx_ref': refs.get('tx_ref', ''),
        'tx_hash': refs.get('tx_hash', ''),
        'settlement_adapter': refs.get('settlement_adapter', ''),
        'proof_type': refs.get('proof_type', ''),
        'verification_state': refs.get('verification_state', ''),
        'finality_state': refs.get('finality_state', ''),
        'proof': refs.get('proof') or {},
        'execution_refs': refs,
        'job_id': (job.get('job_id') or '').strip(),
        'local_warrant_id': (job.get('local_warrant_id') or '').strip(),
    }


def _execute_federated_execution_job(bound_org_id, job_id, *, actor_id, session_id=None, note=''):
    job_id = (job_id or '').strip()
    if not job_id:
        raise ValueError('job_id is required')
    job = get_execution_job(job_id, org_id=bound_org_id)
    if not job:
        raise LookupError(f'Execution job not found: {job_id}')
    if (job.get('message_type') or '').strip() != 'execution_request':
        raise PermissionError(
            f"Execution job '{job_id}' is not an execution_request "
            f"(message_type={job.get('message_type', '')})"
        )
    if (job.get('boundary_name') or '').strip() != 'federation_gateway':
        raise PermissionError(
            f"Execution job '{job_id}' is not scoped to federation_gateway "
            f"(boundary_name={job.get('boundary_name', '')})"
        )
    return _complete_federated_execution_job(
        bound_org_id,
        job,
        actor_id=actor_id,
        session_id=session_id,
    )


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


def _settlement_notice_currency(payload=None):
    payload = payload if isinstance(payload, dict) else {}
    execution_refs = payload.get('execution_refs') or {}
    if not isinstance(execution_refs, dict):
        execution_refs = {}
    return (
        str(
            payload.get('currency')
            or execution_refs.get('currency')
            or 'USDC'
        ).strip().upper()
        or 'USDC'
    )


def _settlement_notice_preflight(bound_org_id, claims, receipt, *, payload=None):
    settlement_ref = _settlement_notice_ref(claims, receipt, payload)
    adapter_id = (settlement_ref.get('settlement_adapter') or '').strip()
    if not adapter_id:
        return settlement_ref, {
            'preflight_ok': False,
            'requested_adapter_id': '',
            'error_type': 'validation_error',
            'error': 'Settlement notice is missing settlement_adapter',
            'currency': _settlement_notice_currency(payload),
        }
    host_identity, _admission_registry = _runtime_host_state(bound_org_id)
    return settlement_ref, preflight_settlement_adapter(
        adapter_id,
        org_id=bound_org_id,
        currency=_settlement_notice_currency(payload),
        tx_hash=settlement_ref.get('tx_hash', ''),
        settlement_proof=settlement_ref.get('proof') or {},
        host_supported_adapters=getattr(host_identity, 'settlement_adapters', []),
    )


def _validated_settlement_notice_ref(bound_org_id, claims, receipt, *, payload=None):
    settlement_ref, preflight = _settlement_notice_preflight(
        bound_org_id,
        claims,
        receipt,
        payload=payload,
    )
    adapter_id = (settlement_ref.get('settlement_adapter') or '').strip()
    if not preflight.get('preflight_ok'):
        raise ValueError(
            preflight.get('error')
            or f"Settlement notice failed adapter preflight for {adapter_id!r}"
        )
    normalized = dict(preflight.get('normalized_proof') or {})
    contract = dict(preflight.get('contract') or {})
    expected_snapshot = dict(settlement_ref.get('settlement_adapter_contract_snapshot') or {})
    expected_digest = (settlement_ref.get('settlement_adapter_contract_digest') or '').strip()
    current_snapshot = dict(
        contract.get('contract_snapshot')
        or settlement_adapter_contract_snapshot(contract)
    )
    current_digest = (
        contract.get('contract_digest')
        or settlement_adapter_contract_digest(current_snapshot)
    ).strip()
    requires_verifier_attestation = bool(contract.get('requires_verifier_attestation'))
    if requires_verifier_attestation and not expected_snapshot:
        raise ValueError(
            f"Settlement notice for non-internal adapter {adapter_id!r} requires verifier attestation snapshot and digest"
        )
    if expected_snapshot and current_snapshot != expected_snapshot:
        raise ValueError(
            f"Settlement notice adapter contract drifted for {adapter_id!r}"
        )
    if expected_digest and current_digest and not hmac.compare_digest(expected_digest, current_digest):
        raise ValueError(
            f"Settlement notice adapter contract digest mismatch for {adapter_id!r}"
        )
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
    settlement_ref['currency'] = preflight.get('currency', _settlement_notice_currency(payload))
    settlement_ref['reversal_or_dispute_capability'] = normalized.get(
        'reversal_or_dispute_capability',
        '',
    )
    settlement_ref['settlement_adapter_contract'] = contract
    settlement_ref['settlement_adapter_contract_snapshot'] = current_snapshot
    settlement_ref['settlement_adapter_contract_digest'] = current_digest
    return settlement_ref, preflight


def _federated_execution_job_ref(job, *, execution_refs=None, settlement_notice=None, executed_by=''):
    record = dict(job or {})
    refs = dict(record.get('execution_refs') or {})
    for key, value in dict(execution_refs or {}).items():
        if value is not None:
            refs[key] = value
    if executed_by and not refs.get('executed_by'):
        refs['executed_by'] = executed_by
    if not refs.get('execution_channel'):
        refs['execution_channel'] = 'workspace_api'
    if not refs.get('proof_type'):
        refs['proof_type'] = 'local_execution'
    if not refs.get('verification_state'):
        refs['verification_state'] = 'host_local_final'
    if not refs.get('finality_state'):
        refs['finality_state'] = 'host_local_final'
    if not refs.get('proof'):
        refs['proof'] = {
            'job_id': record.get('job_id', ''),
            'envelope_id': record.get('envelope_id', ''),
            'local_warrant_id': record.get('local_warrant_id', ''),
            'payload_hash': record.get('payload_hash', ''),
        }
    refs.setdefault('job_id', record.get('job_id', ''))
    refs.setdefault('envelope_id', record.get('envelope_id', ''))
    refs.setdefault('local_warrant_id', record.get('local_warrant_id', ''))
    refs.setdefault('commitment_id', record.get('commitment_id', ''))
    refs.setdefault('received_at', record.get('received_at', ''))
    refs.setdefault('executed_at', record.get('executed_at', '') or _now())
    refs.setdefault('executed_by', executed_by or record.get('metadata', {}).get('executed_by', ''))
    if settlement_notice:
        claims = dict(settlement_notice.get('claims') or {})
        receipt = dict(settlement_notice.get('receipt') or {})
        refs['settlement_notice_envelope_id'] = (
            claims.get('envelope_id', '') or settlement_notice.get('envelope_id', '')
        )
        refs['settlement_notice_receipt_id'] = (
            receipt.get('receipt_id', '') or settlement_notice.get('receipt_id', '')
        )
        refs['settlement_notice_target_host_id'] = (
            claims.get('target_host_id', '') or settlement_notice.get('target_host_id', '')
        )
        refs['settlement_notice_target_institution_id'] = (
            claims.get('target_institution_id', '') or settlement_notice.get('target_institution_id', '')
        )
        refs['settlement_notice_sent_at'] = (
            receipt.get('accepted_at', '') or settlement_notice.get('sent_at', '') or _now()
        )
        refs['settlement_notice_response'] = dict(settlement_notice.get('response') or {})
    return refs


def _federated_execution_job_settlement_notice_view(execution_refs):
    refs = dict(execution_refs or {})
    envelope_id = (refs.get('settlement_notice_envelope_id') or '').strip()
    receipt_id = (refs.get('settlement_notice_receipt_id') or '').strip()
    if not envelope_id and not receipt_id:
        return None
    return {
        'message_type': 'settlement_notice',
        'envelope_id': envelope_id,
        'receipt_id': receipt_id,
        'target_host_id': (refs.get('settlement_notice_target_host_id') or '').strip(),
        'target_institution_id': (refs.get('settlement_notice_target_institution_id') or '').strip(),
        'sent_at': (refs.get('settlement_notice_sent_at') or '').strip(),
        'response': dict(refs.get('settlement_notice_response') or {}),
    }


def _existing_federated_execution_settlement_notice(job, commitment=None):
    refs = dict((job or {}).get('execution_refs') or {})
    if refs.get('settlement_notice_envelope_id') or refs.get('settlement_notice_receipt_id'):
        return {
            'message_type': 'settlement_notice',
            'envelope_id': refs.get('settlement_notice_envelope_id', ''),
            'receipt_id': refs.get('settlement_notice_receipt_id', ''),
            'target_host_id': refs.get('settlement_notice_target_host_id', ''),
            'target_institution_id': refs.get('settlement_notice_target_institution_id', ''),
            'sent_at': refs.get('settlement_notice_sent_at', ''),
            'response': dict(refs.get('settlement_notice_response') or {}),
        }
    for ref in (commitment or {}).get('delivery_refs', []) or []:
        if (ref or {}).get('message_type') == 'settlement_notice' and (
            (ref or {}).get('target_host_id') == (job or {}).get('source_host_id')
            and (ref or {}).get('target_institution_id') == (job or {}).get('source_institution_id')
        ):
            return {
                'message_type': 'settlement_notice',
                'envelope_id': (ref or {}).get('envelope_id', ''),
                'receipt_id': (ref or {}).get('receipt_id', ''),
                'target_host_id': (ref or {}).get('target_host_id', ''),
                'target_institution_id': (ref or {}).get('target_institution_id', ''),
                'sent_at': (ref or {}).get('recorded_at', ''),
                'claims': {
                    'envelope_id': (ref or {}).get('envelope_id', ''),
                    'target_host_id': (ref or {}).get('target_host_id', ''),
                    'target_institution_id': (ref or {}).get('target_institution_id', ''),
                },
                'receipt': {
                    'receipt_id': (ref or {}).get('receipt_id', ''),
                    'accepted_at': (ref or {}).get('recorded_at', ''),
                },
                'response': {},
            }
    return None


def _linked_payout_proposal_for_commitment(bound_org_id, commitment_id):
    commitment_id = (commitment_id or '').strip()
    if not commitment_id:
        return None
    proposals = [
        proposal
        for proposal in list_payout_proposals(bound_org_id)
        if (proposal.get('linked_commitment_id') or '').strip() == commitment_id
    ]
    if not proposals:
        return None
    proposals.sort(
        key=lambda row: (
            1 if (row.get('status') or '').strip() == 'executed' else 0,
            row.get('executed_at', ''),
            row.get('updated_at', ''),
            row.get('created_at', ''),
            row.get('proposal_id', ''),
        ),
        reverse=True,
    )
    return proposals[0]


def _commitment_settlement_ref(commitment, *, proposal_id=''):
    settlement_refs = list((commitment or {}).get('settlement_refs') or [])
    if not settlement_refs:
        return None
    proposal_id = (proposal_id or '').strip()
    if proposal_id:
        for ref in reversed(settlement_refs):
            if (ref or {}).get('proposal_id', '') == proposal_id:
                return dict(ref or {})
    return dict(settlement_refs[-1] or {})


def _linked_payout_execution_refs(bound_org_id, job):
    record = dict(job or {})
    commitment_id = (record.get('commitment_id') or '').strip()
    if not commitment_id:
        return None, None

    proposal = _linked_payout_proposal_for_commitment(bound_org_id, commitment_id)
    if proposal:
        status = (proposal.get('status') or '').strip()
        if status == 'executed':
            execution_refs = dict(proposal.get('execution_refs') or {})
            if execution_refs:
                execution_refs.setdefault('proposal_id', proposal.get('proposal_id', ''))
                execution_refs.setdefault('linked_commitment_id', commitment_id)
                return proposal, execution_refs

    commitment = get_commitment(commitment_id, org_id=bound_org_id)
    settlement_ref = _commitment_settlement_ref(
        commitment,
        proposal_id=(proposal or {}).get('proposal_id', ''),
    )
    if settlement_ref:
        settlement_ref = dict(settlement_ref)
        settlement_ref.setdefault('proposal_id', (proposal or {}).get('proposal_id', ''))
        settlement_ref.setdefault('linked_commitment_id', commitment_id)
        return proposal, settlement_ref

    if proposal:
        status = (proposal.get('status') or '').strip()
        raise LookupError(
            f"Linked payout proposal '{proposal.get('proposal_id', '')}' for commitment "
            f"'{commitment_id}' does not have persisted execution refs yet (status={status or 'unknown'})"
        )
    raise LookupError(f"No executed payout proposal or settlement ref is linked to commitment '{commitment_id}'")


def _complete_federated_execution_job(bound_org_id, job, *, actor_id='', session_id=None):
    record = dict(job or {})
    job_id = (record.get('job_id') or '').strip()
    if not job_id:
        raise ValueError('job_id is required')
    local_warrant_id = (record.get('local_warrant_id') or '').strip()
    if not local_warrant_id:
        raise ValueError(f"Execution job '{job_id}' is missing local_warrant_id")
    state = (record.get('state') or '').strip()
    if state not in ('ready', 'executed'):
        raise PermissionError(
            f"Execution job '{job_id}' is not executable (state={state or 'unknown'})"
        )

    warrant = get_warrant(local_warrant_id, org_id=bound_org_id)
    if not warrant:
        raise LookupError(f'Local warrant not found: {local_warrant_id}')

    merged_refs = dict(record.get('execution_refs') or {})
    if state != 'executed':
        merged_refs = _federated_execution_job_ref(
            record,
            execution_refs=merged_refs,
            executed_by=actor_id or '',
        )
        validate_warrant_for_execution(
            local_warrant_id,
            org_id=bound_org_id,
            action_class='federated_execution',
            boundary_name='federation_gateway',
            request_payload=_execution_job_warrant_validation_payload(record),
        )
        warrant = mark_warrant_executed(
            local_warrant_id,
            org_id=bound_org_id,
            execution_refs=merged_refs,
        )
        record = upsert_execution_job(
            bound_org_id,
            job_id=job_id,
            state='executed',
            execution_refs=merged_refs,
            note='Receiver-side execution completed',
            metadata={
                **dict(record.get('metadata') or {}),
                'executed_by': actor_id or '',
            },
        )
        log_event(
            bound_org_id,
            actor_id or f'peer:{record.get("source_host_id", "")}',
            'federation_execution_job_executed',
            resource=job_id,
            outcome='success',
            details={
                'local_warrant_id': local_warrant_id,
                'commitment_id': record.get('commitment_id', ''),
                'job_state': 'executed',
            },
            session_id=session_id,
        )
    else:
        if warrant.get('execution_state') != 'executed':
            warrant = mark_warrant_executed(
                local_warrant_id,
                org_id=bound_org_id,
                execution_refs=merged_refs or warrant.get('execution_refs') or {},
            )

    commitment = None
    settlement_notice = None
    commitment_id = (record.get('commitment_id') or '').strip()
    if commitment_id:
        commitment = get_commitment(commitment_id, org_id=bound_org_id)
        settlement_notice = _existing_federated_execution_settlement_notice(record, commitment)
        if settlement_notice:
            if not merged_refs.get('settlement_notice_envelope_id') and not merged_refs.get('settlement_notice_receipt_id'):
                merged_refs = _federated_execution_job_ref(
                    record,
                    execution_refs=merged_refs,
                    settlement_notice=settlement_notice,
                    executed_by=actor_id or '',
                )
                record = upsert_execution_job(
                    bound_org_id,
                    job_id=job_id,
                    state='executed',
                    execution_refs=merged_refs,
                    note=record.get('note', ''),
                    metadata=dict(record.get('metadata') or {}),
                )
            return {
                'execution_job': _execution_job_view(bound_org_id, record),
                'warrant': warrant,
                'settlement_notice': _federated_execution_job_settlement_notice_view(merged_refs),
            }

        proposal, settlement_execution_refs = _linked_payout_execution_refs(bound_org_id, record)
        if not settlement_execution_refs:
            raise LookupError(
                f"No persisted payout execution refs are linked to commitment '{commitment_id}'"
            )
        settlement_execution_refs = dict(settlement_execution_refs)
        if proposal and proposal.get('proposal_id'):
            settlement_execution_refs.setdefault('proposal_id', proposal.get('proposal_id', ''))
        payload = {
            'job_id': job_id,
            'local_warrant_id': local_warrant_id,
            'envelope_id': record.get('envelope_id', ''),
            'commitment_id': commitment_id,
            'execution_refs': dict(settlement_execution_refs),
            'currency': settlement_execution_refs.get('currency', ''),
            'proof': settlement_execution_refs.get('proof') or {},
            'proof_type': settlement_execution_refs.get('proof_type', ''),
            'verification_state': settlement_execution_refs.get('verification_state', ''),
            'finality_state': settlement_execution_refs.get('finality_state', ''),
            'tx_ref': settlement_execution_refs.get('tx_ref', ''),
            'tx_hash': settlement_execution_refs.get('tx_hash', ''),
            'settlement_adapter': settlement_execution_refs.get('settlement_adapter', ''),
        }
        delivery, _federation_state = _deliver_federation_envelope(
            bound_org_id,
            record.get('source_host_id', ''),
            record.get('source_institution_id', ''),
            'settlement_notice',
            payload=payload,
            actor_type='service',
            actor_id=actor_id or f'peer:{record.get("source_host_id", "")}',
            session_id=session_id or '',
            commitment_id=commitment_id,
        )
        settlement_notice = {
            'message_type': 'settlement_notice',
            'envelope_id': (delivery.get('claims') or {}).get('envelope_id', ''),
            'receipt_id': (delivery.get('receipt') or {}).get('receipt_id', ''),
            'target_host_id': (delivery.get('claims') or {}).get('target_host_id', ''),
            'target_institution_id': (delivery.get('claims') or {}).get('target_institution_id', ''),
            'sent_at': (delivery.get('receipt') or {}).get('accepted_at', '') or _now(),
            'response': dict(delivery.get('response') or {}),
        }
        merged_refs = _federated_execution_job_ref(
            record,
            execution_refs=settlement_execution_refs,
            settlement_notice=settlement_notice,
            executed_by=actor_id or '',
        )
        record = upsert_execution_job(
            bound_org_id,
            job_id=job_id,
            state='executed',
            execution_refs=merged_refs,
            note=record.get('note', ''),
            metadata=dict(record.get('metadata') or {}),
        )
        log_event(
            bound_org_id,
            actor_id or f'peer:{record.get("source_host_id", "")}',
            'federation_execution_job_settlement_notice_sent',
            resource=job_id,
            outcome='success',
            details={
                'commitment_id': commitment_id,
                'envelope_id': settlement_notice['envelope_id'],
                'receipt_id': settlement_notice['receipt_id'],
            },
            session_id=session_id,
        )
        return {
            'execution_job': _execution_job_view(bound_org_id, record),
            'warrant': warrant,
            'settlement_notice': settlement_notice,
        }

    return {
        'execution_job': _execution_job_view(bound_org_id, record),
        'warrant': warrant,
        'settlement_notice': None,
    }


def _process_received_commitment_proposal(bound_org_id, claims, receipt, *, payload=None):
    payload = payload if isinstance(payload, dict) else {}
    actor_id = claims.actor_id or f'peer:{claims.source_host_id}'
    summary = (payload.get('summary') or payload.get('commitment_type') or '').strip()
    if not summary:
        return {
            'applied': False,
            'message_type': claims.message_type,
            'state': 'received',
            'reason': 'invalid_commitment_payload',
            'error': 'summary is required',
        }
    metadata = dict(payload.get('metadata') or {})
    metadata.setdefault('federation_source_host_id', claims.source_host_id)
    metadata.setdefault('federation_envelope_id', claims.envelope_id)
    commitment, created = sync_federated_commitment_proposal(
        bound_org_id,
        claims.commitment_id,
        source_host_id=claims.source_host_id,
        source_institution_id=claims.source_institution_id,
        target_host_id=claims.target_host_id,
        target_institution_id=claims.target_institution_id,
        summary=summary,
        actor_id=actor_id,
        terms_payload=payload.get('terms_payload'),
        warrant_id=claims.warrant_id,
        note=payload.get('note', ''),
        metadata=metadata,
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
        'federation_commitment_proposal_recorded',
        resource=claims.commitment_id,
        outcome='success',
        actor_type=claims.actor_type or 'service',
        details=_federation_audit_details(
            claims,
            receipt_id=(receipt or {}).get('receipt_id', ''),
            summary=summary,
            created=created,
        ),
        session_id=claims.session_id or None,
    )
    return {
        'applied': True,
        'message_type': claims.message_type,
        'state': 'processed',
        'reason': 'commitment_proposal_recorded',
        'commitment': commitment,
        'created': created,
        'inbox_entry': inbox_entry,
    }


def _process_received_commitment_acceptance(bound_org_id, claims, receipt, *, payload=None):
    payload = payload if isinstance(payload, dict) else {}
    actor_id = claims.actor_id or f'peer:{claims.source_host_id}'
    commitment = get_commitment(claims.commitment_id, org_id=bound_org_id)
    if not commitment:
        return {
            'applied': False,
            'message_type': claims.message_type,
            'state': 'received',
            'reason': 'commitment_not_found',
            'error': f"Commitment not found: {claims.commitment_id}",
        }
    if (commitment.get('target_host_id') or '').strip() != (claims.source_host_id or '').strip():
        return {
            'applied': False,
            'message_type': claims.message_type,
            'state': 'received',
            'reason': 'commitment_target_mismatch',
            'error': (
                f"Commitment '{claims.commitment_id}' target_host_id "
                f"{commitment.get('target_host_id', '')!r} does not match "
                f"{(claims.source_host_id or '').strip()!r}"
            ),
        }
    if (commitment.get('target_institution_id') or '').strip() != (claims.source_institution_id or '').strip():
        return {
            'applied': False,
            'message_type': claims.message_type,
            'state': 'received',
            'reason': 'commitment_target_mismatch',
            'error': (
                f"Commitment '{claims.commitment_id}' target_institution_id "
                f"{commitment.get('target_institution_id', '')!r} does not match "
                f"{(claims.source_institution_id or '').strip()!r}"
            ),
        }
    created = False
    if (commitment.get('status') or '').strip() != 'accepted':
        commitment = accept_commitment(
            claims.commitment_id,
            actor_id,
            org_id=bound_org_id,
            note=payload.get('note', '') or 'Accepted via received commitment_acceptance envelope',
        )
        created = True
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
        'federation_commitment_acceptance_recorded',
        resource=claims.commitment_id,
        outcome='success',
        actor_type=claims.actor_type or 'service',
        details=_federation_audit_details(
            claims,
            receipt_id=(receipt or {}).get('receipt_id', ''),
            accepted=created,
        ),
        session_id=claims.session_id or None,
    )
    return {
        'applied': True,
        'message_type': claims.message_type,
        'state': 'processed',
        'reason': 'commitment_acceptance_recorded',
        'commitment': commitment,
        'accepted': created,
        'inbox_entry': inbox_entry,
    }


def _process_received_commitment_breach_notice(bound_org_id, claims, receipt, *, payload=None):
    payload = payload if isinstance(payload, dict) else {}
    actor_id = claims.actor_id or f'peer:{claims.source_host_id}'
    commitment = get_commitment(claims.commitment_id, org_id=bound_org_id)
    if not commitment:
        return {
            'applied': False,
            'message_type': claims.message_type,
            'state': 'received',
            'reason': 'commitment_not_found',
            'error': f"Commitment not found: {claims.commitment_id}",
        }
    if (commitment.get('target_host_id') or '').strip() != (claims.source_host_id or '').strip():
        return {
            'applied': False,
            'message_type': claims.message_type,
            'state': 'received',
            'reason': 'commitment_target_mismatch',
            'error': (
                f"Commitment '{claims.commitment_id}' target_host_id "
                f"{commitment.get('target_host_id', '')!r} does not match "
                f"{(claims.source_host_id or '').strip()!r}"
            ),
        }
    if (commitment.get('target_institution_id') or '').strip() != (claims.source_institution_id or '').strip():
        return {
            'applied': False,
            'message_type': claims.message_type,
            'state': 'received',
            'reason': 'commitment_target_mismatch',
            'error': (
                f"Commitment '{claims.commitment_id}' target_institution_id "
                f"{commitment.get('target_institution_id', '')!r} does not match "
                f"{(claims.source_institution_id or '').strip()!r}"
            ),
        }
    breached = False
    if (commitment.get('status') or '').strip() != 'breached':
        commitment = breach_commitment(
            claims.commitment_id,
            actor_id,
            org_id=bound_org_id,
            note=payload.get('note', '') or 'Breached via received commitment_breach_notice envelope',
        )
        breached = True
    case_record, created_case = _maybe_open_case_for_commitment_breach(
        commitment,
        actor_id,
        org_id=bound_org_id,
        note=payload.get('note', '') or 'Opened from received commitment_breach_notice envelope',
    )
    federation_peer = _maybe_suspend_peer_for_case(
        case_record,
        actor_id,
        org_id=bound_org_id,
        session_id=claims.session_id or None,
    )
    if created_case:
        log_event(
            bound_org_id,
            actor_id,
            'case_opened',
            outcome='success',
            resource=case_record['case_id'],
            details={
                'claim_type': case_record['claim_type'],
                'linked_commitment_id': claims.commitment_id,
                'linked_warrant_id': case_record.get('linked_warrant_id', ''),
            },
            session_id=claims.session_id or None,
        )
    warrant = _maybe_stay_warrant_for_case(
        case_record,
        actor_id,
        org_id=bound_org_id,
        session_id=claims.session_id or None,
        note=payload.get('note', '') or 'Stayed after received commitment_breach_notice envelope',
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
        'federation_commitment_breach_notice_recorded',
        resource=claims.commitment_id,
        outcome='success',
        actor_type=claims.actor_type or 'service',
        details=_federation_audit_details(
            claims,
            receipt_id=(receipt or {}).get('receipt_id', ''),
            breached=breached,
            case_id=case_record.get('case_id', ''),
            case_created=created_case,
            federation_peer_state=(federation_peer or {}).get('trust_state', ''),
            warrant_state=(warrant or {}).get('court_review_state', ''),
        ),
        session_id=claims.session_id or None,
    )
    return {
        'applied': True,
        'message_type': claims.message_type,
        'state': 'processed',
        'reason': 'commitment_breach_notice_recorded',
        'commitment': commitment,
        'breached': breached,
        'case': case_record,
        'federation_peer': federation_peer,
        'warrant': warrant,
        'inbox_entry': inbox_entry,
    }


def _case_notice_required_payload_fields():
    return (
        'case_decision',
        'source_case_id',
        'claim_type',
        'linked_commitment_id',
        'linked_warrant_id',
        'target_host_id',
        'target_institution_id',
        'note',
        'metadata',
    )


def _case_notice_payload_dict(payload):
    payload = payload if isinstance(payload, dict) else {}
    notice = {
        'case_decision': (payload.get('case_decision') or '').strip(),
        'source_case_id': (payload.get('source_case_id') or '').strip(),
        'claim_type': (payload.get('claim_type') or '').strip(),
        'linked_commitment_id': (payload.get('linked_commitment_id') or '').strip(),
        'linked_warrant_id': (payload.get('linked_warrant_id') or '').strip(),
        'target_host_id': (payload.get('target_host_id') or '').strip(),
        'target_institution_id': (
            payload.get('target_institution_id')
            or payload.get('target_org_id')
            or ''
        ).strip(),
        'note': payload.get('note', ''),
        'metadata': dict(payload.get('metadata') or {}),
    }
    return notice


def _case_notice_store_case_lookup(bound_org_id, source_host_id, source_institution_id, source_case_id):
    source_host_id = (source_host_id or '').strip()
    source_institution_id = (source_institution_id or '').strip()
    source_case_id = (source_case_id or '').strip()
    if not source_host_id or not source_institution_id or not source_case_id:
        return None
    for case in list_cases(bound_org_id):
        metadata = dict(case.get('metadata') or {})
        if (
            metadata.get('federation_source_host_id') == source_host_id
            and metadata.get('federation_source_institution_id') == source_institution_id
            and metadata.get('federation_source_case_id') == source_case_id
        ):
            return case
    return None


def _case_notice_store_case(bound_org_id, case_record):
    store = cases_module._load_store(bound_org_id)
    store.setdefault('cases', {})[case_record['case_id']] = case_record
    cases_module._save_store(store, bound_org_id)
    return case_record


def _case_notice_case_metadata(claims, receipt, payload, *, target_host_id, target_institution_id):
    payload = payload if isinstance(payload, dict) else {}
    metadata = dict(payload.get('metadata') or {})
    metadata.update({
        'source': 'federation_case_notice',
        'federation_message_type': 'case_notice',
        'federation_case_decision': payload.get('case_decision', ''),
        'federation_source_host_id': claims.source_host_id,
        'federation_source_institution_id': claims.source_institution_id,
        'federation_source_case_id': payload.get('source_case_id', ''),
        'federation_notice_target_host_id': target_host_id,
        'federation_notice_target_institution_id': target_institution_id,
        'federation_envelope_id': claims.envelope_id,
        'federation_receipt_id': (receipt or {}).get('receipt_id', ''),
    })
    return metadata


def _process_received_case_notice(bound_org_id, claims, receipt, *, payload=None):
    payload = _case_notice_payload_dict(payload)
    actor_id = claims.actor_id or f'peer:{claims.source_host_id}'
    decision = payload.get('case_decision', '')
    source_case_id = payload.get('source_case_id', '')
    claim_type = payload.get('claim_type', '')
    linked_commitment_id = payload.get('linked_commitment_id', '')
    linked_warrant_id = payload.get('linked_warrant_id', '')
    target_host_id = payload.get('target_host_id', '')
    target_institution_id = payload.get('target_institution_id', '')
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
        return {
            'applied': False,
            'message_type': claims.message_type,
            'state': 'received',
            'reason': 'invalid_case_notice',
            'error': error,
        }

    mirrored_case = _case_notice_store_case_lookup(
        bound_org_id,
        claims.source_host_id,
        claims.source_institution_id,
        source_case_id,
    )
    created = False
    mirrored_target_host_id = claims.source_host_id
    mirrored_target_institution_id = claims.source_institution_id
    mirror_metadata = _case_notice_case_metadata(
        claims,
        receipt,
        payload,
        target_host_id=target_host_id,
        target_institution_id=target_institution_id,
    )
    if decision == 'open':
        if mirrored_case:
            mirrored_case = dict(mirrored_case)
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
            _case_notice_store_case(bound_org_id, mirrored_case)
        else:
            mirrored_case = open_case(
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
            return {
                'applied': False,
                'message_type': claims.message_type,
                'state': 'received',
                'reason': 'case_not_found',
                'error': error,
            }
        mirrored_case = dict(mirrored_case)
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
        _case_notice_store_case(bound_org_id, mirrored_case)
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
    return {
        'applied': True,
        'message_type': claims.message_type,
        'state': 'processed',
        'reason': 'case_notice_applied',
        'case': mirrored_case,
        'case_created': created,
        'federation_peer': federation_peer,
        'warrant': warrant,
        'inbox_entry': inbox_entry,
    }


def _court_notice_required_payload_fields():
    return (
        'court_decision',
        'sender_warrant_id',
        'local_warrant_id',
        'source_execution_envelope_id',
        'target_host_id',
        'target_institution_id',
        'note',
        'metadata',
    )


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
    host_identity, admission_registry = _runtime_host_state(bound_org_id)
    authority = _federation_authority(host_identity)
    authority.ensure_enabled()
    peer = authority.peer_registry.get('peers', {}).get(target_host_id)
    if not peer:
        raise FederationDeliveryError(f"Peer host '{target_host_id}' is not in peer registry")
    if peer.trust_state == 'revoked':
        raise FederationDeliveryError(
            f"Peer host '{target_host_id}' is not trusted (state={peer.trust_state})"
        )
    if not peer.receive_url:
        raise FederationDeliveryError(
            f"Peer host '{target_host_id}' does not declare endpoint_url"
        )
    if not (peer.manifest_url.lower().startswith('http://') or peer.manifest_url.lower().startswith('https://')):
        raise FederationDeliveryError(f"Invalid URL scheme for manifest in peer '{target_host_id}'")
    try:
        request = urllib_request.Request(peer.manifest_url, method='GET')
        with urllib_request.urlopen(request, timeout=10) as response:
            manifest = json.loads(response.read().decode('utf-8') or '{}')
    except urllib_error.HTTPError as exc:
        body = exc.read().decode('utf-8')
        raise FederationDeliveryError(
            f"Failed fetching federation manifest from '{peer.host_id}': HTTP {exc.code}: {body}",
            peer_host_id=peer.host_id,
        ) from exc
    except Exception as exc:
        raise FederationDeliveryError(
            f"Failed fetching federation manifest from '{peer.host_id}': {exc}",
            peer_host_id=peer.host_id,
        ) from exc
    if not isinstance(manifest, dict):
        raise FederationDeliveryError(
            f"Peer host '{peer.host_id}' returned a non-object federation manifest",
            peer_host_id=peer.host_id,
            response=manifest,
        )
    authority._validate_peer_manifest(
        peer,
        manifest,
        target_institution_id=target_institution_id,
    )
    envelope = authority.issue(
        bound_org_id,
        peer.host_id,
        target_institution_id,
        'court_notice',
        payload=federated_payload,
        actor_type='user',
        actor_id=actor_id,
        session_id=session_id or '',
        warrant_id=sender_warrant_id,
        commitment_id=(record.get('commitment_id') or '').strip(),
    )
    claims = authority.validate(
        envelope,
        payload=federated_payload,
        expected_target_host_id=peer.host_id,
        expected_target_org_id=target_institution_id,
        expected_boundary_name='federation_gateway',
    )
    if not (peer.receive_url.lower().startswith('http://') or peer.receive_url.lower().startswith('https://')):
        raise FederationDeliveryError(f"Invalid URL scheme for receive_url in peer '{target_host_id}'")
    try:
        request = urllib_request.Request(
            peer.receive_url,
            data=json.dumps({
                'envelope': envelope,
                'payload': federated_payload,
            }).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib_request.urlopen(request, timeout=10) as response:
            delivery_response = json.loads(response.read().decode('utf-8') or '{}')
    except urllib_error.HTTPError as exc:
        body = exc.read().decode('utf-8')
        raise FederationDeliveryError(
            f"Peer returned HTTP {exc.code}: {body}",
            peer_host_id=peer.host_id,
            envelope=envelope,
            claims=claims,
        ) from exc
    except Exception as exc:
        raise FederationDeliveryError(
            f"Failed delivering federation envelope to '{peer.host_id}': {exc}",
            peer_host_id=peer.host_id,
            envelope=envelope,
            claims=claims,
        ) from exc
    receipt = authority._validate_delivery_receipt(
        delivery_response,
        peer_host_id=peer.host_id,
        target_institution_id=target_institution_id,
        claims=claims,
    )
    delivery = {
        'peer': peer.to_dict(),
        'peer_manifest': manifest,
        'envelope': envelope,
        'claims': claims.to_dict(),
        'receipt': receipt,
        'response': delivery_response,
    }
    witness_archive = _archive_delivery_with_witness_peers(
        bound_org_id,
        authority,
        delivery,
        federated_payload,
        actor_id=actor_id,
        session_id=session_id,
        host_identity=host_identity,
    )
    delivery['witness_archive'] = witness_archive
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
    federation_state = authority.snapshot(
        bound_org_id=bound_org_id,
        admission_registry=admission_registry,
    )
    log_event(
        bound_org_id,
        actor_id,
        'federation_court_notice_sent',
        resource=record.get('job_id', '') or sender_warrant_id,
        outcome='success',
        actor_type='user',
        details=_federation_audit_details(
            claims,
            peer_transport=peer.transport,
            receipt_id=receipt.get('receipt_id', ''),
            receiver_host_id=receipt.get('receiver_host_id', ''),
            receiver_institution_id=receipt.get('receiver_institution_id', ''),
            local_warrant_id=(record.get('local_warrant_id') or '').strip(),
            sender_warrant_id=sender_warrant_id,
            decision=(decision or '').strip(),
            witness_archive_attempted=witness_archive.get('attempted', 0),
            witness_archive_created=witness_archive.get('created', 0),
            witness_archive_failed=witness_archive.get('failed', 0),
        ),
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


def _sender_execution_delivery_ref_for_court_notice(bound_org_id, sender_warrant_id, claims, payload):
    payload = _court_notice_payload_dict(payload)
    sender_warrant_id = (sender_warrant_id or '').strip()
    execution_envelope_id = payload.get('source_execution_envelope_id', '')
    commitment = None
    if claims.commitment_id:
        commitment = get_commitment(claims.commitment_id, org_id=bound_org_id)
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
        note=note or (
            f"Receiver-side court_notice {decision} from {claims.source_host_id}"
        ),
    )
    delivery_record = None
    if claims.commitment_id and commitment:
        commitment = record_delivery_ref(
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
    if claims.message_type == 'commitment_proposal' and claims.commitment_id:
        return _process_received_commitment_proposal(
            bound_org_id,
            claims,
            receipt,
            payload=payload,
        )

    if claims.message_type == 'commitment_acceptance' and claims.commitment_id:
        return _process_received_commitment_acceptance(
            bound_org_id,
            claims,
            receipt,
            payload=payload,
        )

    if claims.message_type == 'commitment_breach_notice' and claims.commitment_id:
        return _process_received_commitment_breach_notice(
            bound_org_id,
            claims,
            receipt,
            payload=payload,
        )

    if claims.message_type == 'case_notice':
        return _process_received_case_notice(
            bound_org_id,
            claims,
            receipt,
            payload=payload,
        )

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
        validate_commitment_for_settlement(
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
        settlement_ref, settlement_preflight = _validated_settlement_notice_ref(
            bound_org_id,
            claims,
            receipt,
            payload=payload,
        )
    except ValueError as exc:
        error = str(exc)
        raw_settlement_ref = _settlement_notice_ref(claims, receipt, payload)
        case_record, created = ensure_case_for_delivery_failure(
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
        result.update({
            'reason': 'invalid_settlement_notice',
            'error': error,
            'settlement_preflight': None,
            'case': case_record,
            'case_created': created,
            'federation_peer': federation_peer,
        })
        settlement_preflight = _settlement_notice_preflight(
            bound_org_id,
            claims,
            receipt,
            payload=payload,
        )[1]
        if not settlement_preflight.get('error_type'):
            settlement_preflight = dict(settlement_preflight)
            settlement_preflight['preflight_ok'] = False
            settlement_preflight['can_execute_now'] = False
            settlement_preflight['error_type'] = 'validation_error'
            settlement_preflight['error'] = error
        result['settlement_preflight'] = settlement_preflight
        return result
    record_settlement_ref(
        claims.commitment_id,
        settlement_ref,
        org_id=bound_org_id,
    )
    commitment = settle_commitment(
        claims.commitment_id,
        actor_id,
        org_id=bound_org_id,
        note='Applied from received settlement_notice envelope',
    )
    sender_warrant = _finalize_sender_warrant_for_settlement_notice(
        bound_org_id,
        claims,
        receipt,
        commitment,
        settlement_ref,
        payload=payload,
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
        ),
        session_id=claims.session_id or None,
    )
    result.update({
        'applied': True,
        'state': 'processed',
        'reason': 'settlement_notice_applied',
        'commitment': commitment,
        'settlement_ref': settlement_ref,
        'settlement_preflight': settlement_preflight,
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
    archive = manifest.get('witness_archive', {}) or {}
    if archive.get('host_id') and archive.get('host_id') != peer.host_id:
        raise FederationDeliveryError(
            f"Peer host '{peer.host_id}' witness archive host_id "
            f"{archive.get('host_id', '')!r} does not match peer host",
            peer_host_id=peer.host_id,
            response=manifest,
        )
    return manifest


def _local_federation_manifest(bound_org_id, *, host_identity=None, admission_registry=None):
    org = load_orgs().get('organizations', {}).get(bound_org_id)
    if not org:
        raise RuntimeError(f"Local institution '{bound_org_id}' not found for federation manifest")
    context = InstitutionContext.bind(
        bound_org_id,
        org,
        'federation_local_manifest',
        WORKSPACE_BOUNDARY,
    )
    return _federation_manifest(
        context,
        host_identity=host_identity,
        admission_registry=admission_registry,
    )


def _witness_peer_archive_headers(peer):
    headers = {
        'Content-Type': 'application/json',
    }
    if getattr(peer, 'witness_archive_user', '') and getattr(peer, 'witness_archive_pass', ''):
        token = base64.b64encode(
            f'{peer.witness_archive_user}:{peer.witness_archive_pass}'.encode('utf-8')
        ).decode('ascii')
        headers['Authorization'] = f'Basic {token}'
    return headers


def _archive_delivery_with_witness_peers(bound_org_id, authority, delivery, payload, *,
                                         actor_id='', session_id=None,
                                         host_identity=None):
    if not hasattr(authority, 'peer_registry'):
        return {
            'attempted': 0,
            'created': 0,
            'existing': 0,
            'failed': 0,
            'records': [],
        }
    host_identity = host_identity or authority.host_identity
    claims = dict(delivery.get('claims') or {})
    receipt = dict(delivery.get('receipt') or {})
    if not claims or not receipt:
        return {
            'attempted': 0,
            'created': 0,
            'existing': 0,
            'failed': 0,
            'skipped': 0,
            'records': [],
        }
    admission_registry = load_admission_registry(
        RUNTIME_ADMISSION_FILE,
        bound_org_id=bound_org_id,
        host_identity=host_identity,
    )
    source_manifest = _local_federation_manifest(
        bound_org_id,
        host_identity=host_identity,
        admission_registry=admission_registry,
    )
    target_manifest = dict(delivery.get('peer_manifest') or {})

    peer_registry = authority.peer_registry.get('peers', {}) or {}
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
        if not (
            getattr(peer, 'witness_archive_user', '')
            and getattr(peer, 'witness_archive_pass', '')
        ):
            results.append({
                'peer_host_id': peer.host_id,
                'peer_label': peer.label,
                'attempted': False,
                'archived': False,
                'created': False,
                'skipped': True,
                'reason': 'witness_archive_not_configured',
            })
            continue

        try:
            witness_peer, witness_manifest = authority.fetch_peer_manifest(peer.host_id)
            witness_manifest = _validate_witness_peer_manifest(witness_peer, witness_manifest)
            witness_role = (witness_manifest.get('host_identity', {}) or {}).get('role', '')
            archive = witness_manifest.get('witness_archive', {}) or {}
            if witness_role != 'witness_host':
                results.append({
                    'peer_host_id': witness_peer.host_id,
                    'peer_label': witness_peer.label,
                    'attempted': False,
                    'archived': False,
                    'created': False,
                    'skipped': True,
                    'reason': 'peer_not_witness_host',
                })
                continue
            if not archive.get('archive_enabled'):
                raise FederationDeliveryError(
                    f"Peer host '{witness_peer.host_id}' does not advertise enabled witness archive",
                    peer_host_id=witness_peer.host_id,
                    response=witness_manifest,
                )
            if not (witness_peer.endpoint_url.lower().startswith('http://') or witness_peer.endpoint_url.lower().startswith('https://')):
                raise FederationDeliveryError(f"Invalid URL scheme for witness archive in peer '{witness_peer.host_id}'")
            headers = _witness_peer_archive_headers(witness_peer)
            request = urllib_request.Request(
                witness_peer.endpoint_url + '/api/federation/witness/archive',
                data=json.dumps({
                    'envelope': delivery.get('envelope', ''),
                    'payload': payload,
                    'receipt': receipt,
                    'source_manifest': source_manifest,
                    'target_manifest': target_manifest,
                }).encode('utf-8'),
                headers=headers,
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
                'attempted': True,
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
                'attempted': True,
                'archived': False,
                'created': False,
                'error': str(exc),
            }
            log_event(
                bound_org_id,
                actor_id or f'host:{host_identity.host_id}',
                'federation_witness_archive_failed',
                resource=claims.get('message_type', ''),
                outcome='failed',
                actor_type=claims.get('actor_type') or 'service',
                details={
                    'witness_host_id': peer.host_id,
                    'target_host_id': target_host_id,
                    'target_institution_id': claims.get('target_institution_id', ''),
                    'error': str(exc),
                    'receipt_id': receipt.get('receipt_id', ''),
                },
                session_id=session_id or None,
            )
        results.append(result)

    return {
        'attempted': sum(1 for row in results if row.get('attempted')),
        'created': sum(1 for row in results if row.get('archived') and row.get('created')),
        'existing': sum(1 for row in results if row.get('archived') and not row.get('created')),
        'failed': sum(1 for row in results if row.get('attempted') and not row.get('archived')),
        'skipped': sum(1 for row in results if row.get('skipped')),
        'records': results,
    }


def _deliver_federation_envelope(bound_org_id, target_host_id, target_org_id,
                                 message_type, payload=None, *,
                                 actor_type='host_service', actor_id='',
                                 session_id='', warrant_id='',
                                 commitment_id='', claims_commitment_id='',
                                 ttl_seconds=None):
    host_identity, admission_registry = _runtime_host_state(bound_org_id)
    if getattr(host_identity, 'role', '') == 'witness_host':
        message = (
            f"Federation send is disabled on host '{host_identity.host_id}' "
            f"(witness_host_read_only)"
        )
        log_event(
            bound_org_id,
            actor_id or f'host:{host_identity.host_id}',
            'federation_send_blocked',
            resource=message_type,
            outcome='blocked',
            actor_type=actor_type or 'service',
            details={
                'target_host_id': target_host_id,
                'target_institution_id': target_org_id,
                'reason': 'witness_host_read_only',
            },
            session_id=session_id or None,
        )
        raise PermissionError(message)
    authority = _federation_authority(host_identity)
    authority.ensure_enabled()
    execution_warrant = None
    linked_commitment = None
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
    if commitment_id:
        try:
            if message_type == 'commitment_proposal':
                linked_commitment = validate_commitment_for_proposal_dispatch(
                    commitment_id,
                    target_institution_id=target_org_id,
                    org_id=bound_org_id,
                    target_host_id=target_host_id,
                    warrant_id=warrant_id,
                )
            elif message_type == 'commitment_acceptance':
                linked_commitment = validate_commitment_for_acceptance_dispatch(
                    commitment_id,
                    target_institution_id=target_org_id,
                    org_id=bound_org_id,
                    target_host_id=target_host_id,
                    warrant_id=warrant_id,
                )
            elif message_type == 'commitment_breach_notice':
                linked_commitment = validate_commitment_for_breach_notice(
                    commitment_id,
                    target_institution_id=target_org_id,
                    org_id=bound_org_id,
                    target_host_id=target_host_id,
                    warrant_id=warrant_id,
                )
            else:
                linked_commitment = validate_commitment_for_delivery(
                    commitment_id,
                    target_institution_id=target_org_id,
                    org_id=bound_org_id,
                    target_host_id=target_host_id,
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
    delivery_commitment_id = (claims_commitment_id or commitment_id or '').strip()
    if not delivery_commitment_id and message_type == 'execution_request' and isinstance(payload, dict):
        adapter_envelope = payload.get('adapter_envelope')
        adapter_details = (
            dict(adapter_envelope.get('details') or {})
            if isinstance(adapter_envelope, dict)
            else {}
        )
        delivery_commitment_id = (
            payload.get('commitment_id')
            or adapter_details.get('commitment_id')
            or ''
        ).strip()

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
            commitment_id=delivery_commitment_id,
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
    if execution_warrant and not (
        message_type == 'execution_request' and linked_commitment
    ):
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
    commitment_delivery_ref = None
    if not linked_commitment and delivery_commitment_id:
        linked_commitment = get_commitment(delivery_commitment_id, org_id=bound_org_id)
    if linked_commitment:
        commitment_delivery_ref = record_delivery_ref(
            delivery_commitment_id,
            org_id=bound_org_id,
            delivery_ref={
                'recorded_at': _now(),
                'message_type': message_type,
                'envelope_id': (claims or {}).get('envelope_id', ''),
                'target_host_id': target_host_id,
                'target_institution_id': target_org_id,
                'receipt_id': receipt.get('receipt_id', ''),
                'receiver_host_id': receipt.get('receiver_host_id', ''),
                'receiver_institution_id': receipt.get('receiver_institution_id', ''),
                'warrant_id': warrant_id,
                'payload_hash': (claims or {}).get('payload_hash', ''),
                'task': (
                    payload.get('task', '')
                    if isinstance(payload, dict)
                    else ''
                ),
                'adapter_envelope': (
                    dict((payload.get('adapter_envelope') or {}))
                    if isinstance(payload, dict)
                    and isinstance(payload.get('adapter_envelope'), dict)
                    else {}
                ),
            },
        )
        log_event(
            bound_org_id,
            actor_id or f'host:{host_identity.host_id}',
            'commitment_delivery_recorded',
            resource=delivery_commitment_id,
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


def _request_routing_snapshot(parsed_url, headers, bound_org_id):
    requested_org_id = _requested_org_override(parsed_url, headers)
    if not requested_org_id:
        return {
            'mode': 'process_bound',
            'bound_org_id': bound_org_id,
            'effective_org_id': bound_org_id,
            'request_override': 'exact-match-only',
            'requested_org_id': '',
            'route_state': 'bound',
            'route_reason': 'no_request_override',
        }
    if requested_org_id == bound_org_id:
        return {
            'mode': 'process_bound',
            'bound_org_id': bound_org_id,
            'effective_org_id': bound_org_id,
            'request_override': 'exact-match-only',
            'requested_org_id': requested_org_id,
            'route_state': 'matched',
            'route_reason': 'request_org_matches_bound_institution',
        }
    return {
        'mode': 'process_bound',
        'bound_org_id': bound_org_id,
        'effective_org_id': bound_org_id,
        'request_override': 'exact-match-only',
        'requested_org_id': requested_org_id,
        'route_state': 'rejected',
        'route_reason': 'request_override_mismatch',
    }


def _enforce_request_context(parsed_url, headers, bound_org_id):
    request_context = _request_routing_snapshot(parsed_url, headers, bound_org_id)
    if request_context['route_state'] == 'rejected':
        raise ValueError(
            f"Workspace is bound to institution '{bound_org_id}'. "
            f"Request-level override '{request_context['requested_org_id']}' is not allowed."
        )
    return request_context


def _unique_nonempty_org_ids(*groups):
    seen = set()
    ordered = []
    for group in groups:
        for item in group or []:
            org_id = (item or '').strip()
            if org_id and org_id not in seen:
                seen.add(org_id)
                ordered.append(org_id)
    return ordered


def _org_routing_decision(requested_org_id, *, bound_org_id, host_identity=None,
                          admission_registry=None, peer_registry=None, org_registry=None):
    requested_org_id = (requested_org_id or '').strip()
    bound_org_id = (bound_org_id or '').strip()
    admitted_org_ids = _unique_nonempty_org_ids((admission_registry or {}).get('admitted_org_ids', []))
    org_registry = dict(org_registry or {})
    peer_registry = dict(peer_registry or {})
    host_federation_enabled = bool(getattr(host_identity, 'federation_enabled', False))
    host_id = getattr(host_identity, 'host_id', '') if host_identity else ''

    if not requested_org_id:
        return {
            'requested_org_id': '',
            'route_state': 'blocked',
            'route_kind': 'blocked',
            'route_reason': 'missing_requested_org_id',
            'bound_org_id': bound_org_id,
            'target_org_id': '',
            'target_host_id': '',
            'target_endpoint_url': '',
            'peer_host_id': '',
            'peer_trust_state': '',
            'peer_label': '',
            'known_locally': False,
            'known_remotely': False,
            'admitted_locally': False,
            'host_federation_enabled': host_federation_enabled,
            'host_id': host_id,
        }

    if requested_org_id == bound_org_id:
        admitted_locally = requested_org_id in admitted_org_ids
        return {
            'requested_org_id': requested_org_id,
            'route_state': 'local',
            'route_kind': 'local',
            'route_reason': (
                'request_targets_bound_institution'
                if admitted_locally else
                'bound_institution_not_admitted'
            ),
            'bound_org_id': bound_org_id,
            'target_org_id': requested_org_id,
            'target_host_id': host_id,
            'target_endpoint_url': '',
            'peer_host_id': '',
            'peer_trust_state': '',
            'peer_label': '',
            'known_locally': True,
            'known_remotely': False,
            'admitted_locally': admitted_locally,
            'host_federation_enabled': host_federation_enabled,
            'host_id': host_id,
        }

    if requested_org_id in admitted_org_ids:
        return {
            'requested_org_id': requested_org_id,
            'route_state': 'blocked',
            'route_kind': 'blocked',
            'route_reason': 'request_targets_another_local_institution_no_cross_org_dispatch',
            'bound_org_id': bound_org_id,
            'target_org_id': requested_org_id,
            'target_host_id': host_id,
            'target_endpoint_url': '',
            'peer_host_id': '',
            'peer_trust_state': '',
            'peer_label': '',
            'known_locally': True,
            'known_remotely': False,
            'admitted_locally': True,
            'host_federation_enabled': host_federation_enabled,
            'host_id': host_id,
        }

    peer_matches = []
    for peer_host_id, peer in sorted((peer_registry.get('peers') or {}).items()):
        admitted = _unique_nonempty_org_ids(getattr(peer, 'admitted_org_ids', []))
        if requested_org_id in admitted:
            peer_matches.append(peer)

    if not peer_matches:
        return {
            'requested_org_id': requested_org_id,
            'route_state': 'blocked',
            'route_kind': 'blocked',
            'route_reason': (
                'unknown_requested_institution'
                if requested_org_id not in org_registry else
                'no_trusted_peer_can_serve_requested_institution'
            ),
            'bound_org_id': bound_org_id,
            'target_org_id': requested_org_id,
            'target_host_id': '',
            'target_endpoint_url': '',
            'peer_host_id': '',
            'peer_trust_state': '',
            'peer_label': '',
            'known_locally': requested_org_id in org_registry,
            'known_remotely': False,
            'admitted_locally': False,
            'host_federation_enabled': host_federation_enabled,
            'host_id': host_id,
        }

    if not host_federation_enabled:
        peer = peer_matches[0]
        return {
            'requested_org_id': requested_org_id,
            'route_state': 'blocked',
            'route_kind': 'blocked',
            'route_reason': 'federation_disabled_on_host',
            'bound_org_id': bound_org_id,
            'target_org_id': requested_org_id,
            'target_host_id': '',
            'target_endpoint_url': '',
            'peer_host_id': peer.host_id,
            'peer_trust_state': peer.trust_state,
            'peer_label': peer.label,
            'known_locally': requested_org_id in org_registry or requested_org_id in admitted_org_ids,
            'known_remotely': True,
            'admitted_locally': False,
            'host_federation_enabled': host_federation_enabled,
            'host_id': host_id,
        }

    trusted_matches = [peer for peer in peer_matches if getattr(peer, 'trust_state', '') == 'trusted']
    if not trusted_matches:
        peer = peer_matches[0]
        return {
            'requested_org_id': requested_org_id,
            'route_state': 'blocked',
            'route_kind': 'blocked',
            'route_reason': 'matching_peer_not_trusted',
            'bound_org_id': bound_org_id,
            'target_org_id': requested_org_id,
            'target_host_id': '',
            'target_endpoint_url': '',
            'peer_host_id': peer.host_id,
            'peer_trust_state': peer.trust_state,
            'peer_label': peer.label,
            'known_locally': requested_org_id in org_registry or requested_org_id in admitted_org_ids,
            'known_remotely': True,
            'admitted_locally': False,
            'host_federation_enabled': host_federation_enabled,
            'host_id': host_id,
        }

    peer = next((item for item in trusted_matches if getattr(item, 'endpoint_url', '').strip()), None)
    if not peer:
        peer = trusted_matches[0]
        return {
            'requested_org_id': requested_org_id,
            'route_state': 'blocked',
            'route_kind': 'blocked',
            'route_reason': 'matching_peer_missing_endpoint',
            'bound_org_id': bound_org_id,
            'target_org_id': requested_org_id,
            'target_host_id': '',
            'target_endpoint_url': '',
            'peer_host_id': peer.host_id,
            'peer_trust_state': peer.trust_state,
            'peer_label': peer.label,
            'known_locally': requested_org_id in org_registry or requested_org_id in admitted_org_ids,
            'known_remotely': True,
            'admitted_locally': False,
            'host_federation_enabled': host_federation_enabled,
            'host_id': host_id,
        }

    return {
        'requested_org_id': requested_org_id,
        'route_state': 'remote',
        'route_kind': 'remote',
        'route_reason': 'trusted_peer_can_serve_requested_institution',
        'bound_org_id': bound_org_id,
        'target_org_id': requested_org_id,
        'target_host_id': peer.host_id,
        'target_endpoint_url': peer.endpoint_url,
        'peer_host_id': peer.host_id,
        'peer_trust_state': peer.trust_state,
        'peer_label': peer.label,
        'known_locally': requested_org_id in org_registry or requested_org_id in admitted_org_ids,
        'known_remotely': True,
        'admitted_locally': False,
        'host_federation_enabled': host_federation_enabled,
        'host_id': host_id,
    }


def _routing_planner_snapshot(bound_org_id, *, requested_org_ids=None, host_identity=None,
                              admission_registry=None, peer_registry=None, org_registry=None):
    org_registry = dict(org_registry or {})
    peer_registry = dict(peer_registry or {})
    admitted_org_ids = _unique_nonempty_org_ids((admission_registry or {}).get('admitted_org_ids', []))
    peer_admitted_org_ids = []
    for peer in (peer_registry.get('peers') or {}).values():
        peer_admitted_org_ids.extend(_unique_nonempty_org_ids(getattr(peer, 'admitted_org_ids', [])))
    candidates = _unique_nonempty_org_ids(
        requested_org_ids or [],
        [bound_org_id],
        admitted_org_ids,
        peer_admitted_org_ids,
        org_registry.keys(),
    )
    decisions = [
        _org_routing_decision(
            requested_org_id,
            bound_org_id=bound_org_id,
            host_identity=host_identity,
            admission_registry=admission_registry,
            peer_registry=peer_registry,
            org_registry=org_registry,
        )
        for requested_org_id in candidates
    ]
    return {
        'bound_org_id': bound_org_id,
        'host_id': getattr(host_identity, 'host_id', '') if host_identity else '',
        'host_federation_enabled': bool(getattr(host_identity, 'federation_enabled', False)),
        'requested_org_ids': candidates,
        'summary': {
            'total': len(decisions),
            'local': len([item for item in decisions if item['route_kind'] == 'local']),
            'remote': len([item for item in decisions if item['route_kind'] == 'remote']),
            'blocked': len([item for item in decisions if item['route_kind'] == 'blocked']),
        },
        'decisions': decisions,
    }


def _persist_remote_handoff_preview(bound_org_id, preview):
    if (preview or {}).get('route_kind') != 'remote':
        return None
    try:
        return upsert_handoff_preview(bound_org_id, preview)
    except (SystemExit, ValueError, FileNotFoundError, OSError):
        return None


def _acknowledge_and_dispatch_remote_handoff_preview(bound_org_id, handoff_id, *, actor_id, note=''):
    preview = acknowledge_handoff_preview(bound_org_id, handoff_id, by=actor_id, note=note)
    result = {
        'handoff_preview': preview,
        'dispatch_record': None,
        'dispatch_record_created': False,
        'dispatch_record_error': '',
    }
    if not preview.get('dispatch_ready'):
        return result
    try:
        dispatch_record = promote_acknowledged_handoff_preview_to_dispatch_record(
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


def _dispatch_target_profile(bound_org_id, dispatch_record, *, host_identity=None):
    record = dict(dispatch_record or {})
    preview_snapshot, draft = _merged_dispatch_execution_request(record)
    local_host_id = getattr(host_identity, 'host_id', '') if host_identity else ''
    target_institution_id = (
        draft.get('target_institution_id')
        or record.get('requested_org_id')
        or ''
    ).strip()
    target_host_id = (
        draft.get('target_host_id')
        or record.get('target_host_id')
        or ''
    ).strip()

    common_blockers = []
    if not record.get('dispatch_ready'):
        common_blockers.append('dispatch_not_ready')
    if record.get('settlement_claimed') or preview_snapshot.get('settlement_claimed'):
        common_blockers.append('settlement_claimed')
    if record.get('external_settlement_observed') or preview_snapshot.get('external_settlement_observed'):
        common_blockers.append('external_settlement_observed')

    local_blockers = list(common_blockers)
    if target_institution_id != (bound_org_id or '').strip():
        local_blockers.append('target_institution_mismatch')
    if target_host_id and local_host_id and target_host_id != local_host_id:
        local_blockers.append('target_host_mismatch')

    remote_blockers = list(common_blockers)
    if not target_institution_id:
        remote_blockers.append('missing_target_institution_id')
    if not target_host_id:
        remote_blockers.append('missing_target_host_id')
    if target_institution_id == (bound_org_id or '').strip() and (
        not target_host_id or not local_host_id or target_host_id == local_host_id
    ):
        remote_blockers.append('dispatch_already_local')

    if not local_blockers:
        dispatch_mode = 'local'
        blockers = list(local_blockers)
    elif not remote_blockers:
        dispatch_mode = 'remote'
        blockers = list(remote_blockers)
    else:
        dispatch_mode = 'blocked'
        blockers = list(dict.fromkeys(local_blockers + remote_blockers))

    return {
        'dispatch_mode': dispatch_mode,
        'satisfiable': dispatch_mode != 'blocked',
        'blockers': blockers,
        'local_blockers': local_blockers,
        'remote_blockers': remote_blockers,
        'target_institution_id': target_institution_id,
        'target_host_id': target_host_id or local_host_id,
    }


def _local_dispatch_target_satisfiable(bound_org_id, dispatch_record, *, host_identity=None):
    target = _dispatch_target_profile(bound_org_id, dispatch_record, host_identity=host_identity)
    return {
        'satisfiable': target['dispatch_mode'] == 'local',
        'blockers': list(target['local_blockers']),
        'target_institution_id': target['target_institution_id'],
        'target_host_id': target['target_host_id'],
    }


def _run_local_federation_dispatch(bound_org_id, dispatch_id, *, actor_id, note='', session_id=None):
    dispatch_id = (dispatch_id or '').strip()
    actor_id = (actor_id or '').strip()
    if not dispatch_id:
        raise ValueError('dispatch_id is required')
    if not actor_id:
        raise ValueError('actor_id is required')

    dispatch_record = get_handoff_dispatch_record(dispatch_id, bound_org_id)
    if not dispatch_record:
        raise LookupError(f'Federation handoff dispatch record not found: {dispatch_id}')
    host_identity, admission_registry = _runtime_host_state(bound_org_id)
    locality = _local_dispatch_target_satisfiable(bound_org_id, dispatch_record, host_identity=host_identity)
    if not locality['satisfiable']:
        raise PermissionError(
            f"Federation handoff dispatch '{dispatch_id}' is not locally satisfiable: "
            f"{', '.join(locality['blockers'])}"
        )

    preview_snapshot, draft = _merged_dispatch_execution_request(dispatch_record)
    source_host_id = (draft.get('source_host_id') or '').strip()
    source_institution_id = (draft.get('source_institution_id') or '').strip()
    target_host_id = locality['target_host_id'] or getattr(host_identity, 'host_id', '') or ''
    target_institution_id = locality['target_institution_id'] or (bound_org_id or '').strip()
    envelope_id = dispatch_id
    request_payload = dict(draft.get('payload') or {})
    claims = SimpleNamespace(
        envelope_id=envelope_id,
        source_host_id=source_host_id,
        source_institution_id=source_institution_id,
        target_host_id=target_host_id,
        target_institution_id=target_institution_id,
        actor_type='service',
        actor_id=source_host_id and f'peer:{source_host_id}' or actor_id,
        session_id=session_id or '',
        boundary_name=(draft.get('boundary_name') or 'federation_gateway'),
        identity_model=(draft.get('identity_model') or 'signed_host_service'),
        message_type=(draft.get('message_type') or 'execution_request'),
        warrant_id=(draft.get('warrant_id') or ''),
        commitment_id=(draft.get('commitment_id') or ''),
        payload_hash=(draft.get('payload_hash') or ''),
    )
    receipt = {
        'receipt_id': 'fedrcpt_' + hashlib.sha256(
            ':'.join((dispatch_id, target_host_id, target_institution_id)).encode('utf-8')
        ).hexdigest()[:12],
        'envelope_id': envelope_id,
        'accepted_at': _now(),
        'receiver_host_id': target_host_id,
        'receiver_institution_id': target_institution_id,
    }
    execution_job, receiver_warrant, blocking_case = _queue_received_execution_request(
        bound_org_id,
        claims,
        receipt,
        payload=request_payload,
    )
    dispatch_state = 'dispatched'
    dispatch_note = note or (
        'Local dispatch runner promoted dispatch record to receiver-side execution job'
        if not blocking_case else
        'Local dispatch runner materialized a blocked receiver-side execution job'
    )
    updated_dispatch = mark_handoff_dispatch_record_dispatched(
        bound_org_id,
        dispatch_id,
        dispatched_by=actor_id,
        note=dispatch_note,
        dispatch_runner='local_receiver_execution_runner',
        execution_job_id=(execution_job.get('job_id') or '').strip(),
        execution_job_state=(execution_job.get('state') or '').strip(),
        execution_job_snapshot=execution_job,
        dispatch_truth_source='local_receiver_execution_job_materialized',
    )
    return {
        'dispatch_record': updated_dispatch,
        'execution_job': _execution_job_view(bound_org_id, execution_job),
        'receiver_warrant': receiver_warrant,
        'blocking_case': blocking_case,
        'dispatch_runner': 'local_receiver_execution_runner',
        'dispatch_state': dispatch_state,
        'dispatch_blockers': list(locality['blockers']),
        'execution_job_created': True,
    }


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


def _run_remote_federation_dispatch(bound_org_id, dispatch_id, *, actor_id, note='', session_id=None,
                                    payload=None, warrant_id='', commitment_id='', ttl_seconds=None):
    dispatch_id = (dispatch_id or '').strip()
    actor_id = (actor_id or '').strip()
    if not dispatch_id:
        raise ValueError('dispatch_id is required')
    if not actor_id:
        raise ValueError('actor_id is required')

    dispatch_record = get_handoff_dispatch_record(dispatch_id, bound_org_id)
    if not dispatch_record:
        raise LookupError(f'Federation handoff dispatch record not found: {dispatch_id}')

    existing_result = _existing_remote_dispatch_result(dispatch_record)
    if existing_result is not None:
        return existing_result

    host_identity, admission_registry = _runtime_host_state(bound_org_id)
    target = _dispatch_target_profile(bound_org_id, dispatch_record, host_identity=host_identity)
    if target['dispatch_mode'] != 'remote':
        raise PermissionError(
            f"Federation handoff dispatch '{dispatch_id}' is not remotely dispatchable: "
            f"{', '.join(target['remote_blockers'] or target['blockers'])}"
        )

    preview_snapshot, draft = _merged_dispatch_execution_request(dispatch_record)
    request_payload = payload if payload is not None else draft.get('payload')
    if request_payload is None:
        request_payload = {}
    if not isinstance(request_payload, dict):
        raise ValueError('payload must be a JSON object for remote federation dispatch')

    resolved_warrant_id = (warrant_id or draft.get('warrant_id') or '').strip()
    if not resolved_warrant_id:
        raise ValueError('warrant_id is required for remote federation dispatch')
    resolved_commitment_id = (commitment_id or draft.get('commitment_id') or '').strip()

    delivery, federation_state = _deliver_federation_envelope(
        bound_org_id,
        target['target_host_id'],
        target['target_institution_id'],
        (draft.get('message_type') or 'execution_request'),
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
    updated_dispatch = mark_handoff_dispatch_record_dispatched(
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
        'dispatch_blockers': list(target['remote_blockers']),
        'execution_job_created': bool(remote_execution_job),
        'delivery_received': True,
    }


def _run_federation_dispatch(bound_org_id, dispatch_id, *, actor_id, note='', session_id=None,
                             payload=None, warrant_id='', commitment_id='', ttl_seconds=None):
    dispatch_record = get_handoff_dispatch_record(dispatch_id, bound_org_id)
    if not dispatch_record:
        raise LookupError(f'Federation handoff dispatch record not found: {dispatch_id}')
    host_identity, admission_registry = _runtime_host_state(bound_org_id)
    target = _dispatch_target_profile(bound_org_id, dispatch_record, host_identity=host_identity)
    if target['dispatch_mode'] == 'local':
        return _run_local_federation_dispatch(
            bound_org_id,
            dispatch_id,
            actor_id=actor_id,
            note=note,
            session_id=session_id,
        )
    if target['dispatch_mode'] == 'remote':
        return _run_remote_federation_dispatch(
            bound_org_id,
            dispatch_id,
            actor_id=actor_id,
            note=note,
            session_id=session_id,
            payload=payload,
            warrant_id=warrant_id,
            commitment_id=commitment_id,
            ttl_seconds=ttl_seconds,
        )
    raise PermissionError(
        f"Federation handoff dispatch '{dispatch_id}' is not dispatchable: "
        f"{', '.join(target['blockers'])}"
    )


def _routing_handoff_preview_snapshot(bound_org_id, *, requested_org_ids=None,
                                      host_identity=None, admission_registry=None,
                                      peer_registry=None, org_registry=None):
    org_registry = dict(org_registry or {})
    if host_identity is None or admission_registry is None:
        host_identity, admission_registry = _runtime_host_state(bound_org_id)
    if peer_registry is None:
        peer_registry = load_peer_registry(
            FEDERATION_PEERS_FILE,
            host_identity=host_identity,
        )
    peer_registry = dict(peer_registry or {})
    routing_planner = _routing_planner_snapshot(
        bound_org_id,
        requested_org_ids=requested_org_ids,
        host_identity=host_identity,
        admission_registry=admission_registry,
        peer_registry=peer_registry,
        org_registry=org_registry,
    )
    handoff_candidates = []
    generated_at = _now()
    for decision in routing_planner['decisions']:
        requested_org_id = decision.get('requested_org_id', '')
        route_kind = decision.get('route_kind', '')
        route_reason = decision.get('route_reason', '')
        handoff_state = 'blocked'
        dispatch_ready = False
        dispatch_blockers = [route_reason] if route_reason else []
        if route_kind == 'local':
            handoff_state = 'local_bound'
            dispatch_blockers = ['request_targets_bound_institution']
        elif route_kind == 'remote':
            handoff_state = 'previewed'
            dispatch_ready = True
            dispatch_blockers = []
        preview = {
            'requested_org_id': requested_org_id,
            'route_kind': route_kind,
            'route_state': decision.get('route_state', ''),
            'route_reason': route_reason,
            'handoff_state': handoff_state,
            'dispatch_ready': dispatch_ready,
            'dispatch_blockers': dispatch_blockers,
            'preview_truth_source': 'planner_only' if route_kind != 'remote' else 'planner_and_peer_registry_only',
            'dispatch_paths': {
                'send': '/api/federation/send',
                'receive': '/api/federation/receive',
                'receiver_jobs': '/api/federation/execution-jobs',
                'receiver_execute': '/api/federation/execution-jobs/execute',
            },
            'draft_execution_request': {
                'message_type': 'execution_request',
                'boundary_name': 'federation_gateway',
                'identity_model': 'signed_host_service',
                'source_host_id': getattr(host_identity, 'host_id', ''),
                'source_institution_id': bound_org_id,
                'target_host_id': decision.get('target_host_id', ''),
                'target_institution_id': requested_org_id,
                'payload_hash': '',
                'warrant_id': '',
                'commitment_id': '',
            },
            'generated_at': generated_at,
            'previewed_at': generated_at,
            'queued_at': generated_at,
        }
        if route_kind == 'remote':
            preview['handoff_id'] = 'fhdp_' + hashlib.sha256(
                ':'.join((
                    bound_org_id,
                    requested_org_id,
                    decision.get('target_host_id', ''),
                    decision.get('target_endpoint_url', ''),
                    route_reason,
                )).encode('utf-8')
            ).hexdigest()[:12]
            preview['target_host_id'] = decision.get('target_host_id', '')
            preview['target_endpoint_url'] = decision.get('target_endpoint_url', '')
            preview['peer_host_id'] = decision.get('peer_host_id', '')
            preview['peer_label'] = decision.get('peer_label', '')
            preview['peer_trust_state'] = decision.get('peer_trust_state', '')
            preview['remote_execution_claimed'] = False
            persisted_preview = _persist_remote_handoff_preview(bound_org_id, preview)
            if persisted_preview is not None:
                preview['handoff_queue_recorded'] = True
                preview['handoff_queue_state'] = persisted_preview.get('state', '')
            else:
                preview['handoff_queue_recorded'] = False
        else:
            preview['target_host_id'] = decision.get('target_host_id', '')
            preview['target_endpoint_url'] = decision.get('target_endpoint_url', '')
            preview['peer_host_id'] = decision.get('peer_host_id', '')
            preview['peer_label'] = decision.get('peer_label', '')
            preview['peer_trust_state'] = decision.get('peer_trust_state', '')
            preview['remote_execution_claimed'] = False
        handoff_candidates.append(preview)

    return {
        'bound_org_id': bound_org_id,
        'host_id': getattr(host_identity, 'host_id', '') if host_identity else '',
        'generated_at': generated_at,
        'routing_planner': routing_planner,
        'summary': {
            'total': len(handoff_candidates),
            'local': len([item for item in handoff_candidates if item['route_kind'] == 'local']),
            'remote': len([item for item in handoff_candidates if item['route_kind'] == 'remote']),
            'blocked': len([item for item in handoff_candidates if item['route_kind'] == 'blocked']),
            'remote_previewed': len([item for item in handoff_candidates if item['handoff_state'] == 'previewed']),
        },
        'handoff_candidates': handoff_candidates,
    }


def _resolve_auth_context(bound_org_id):
    user, password, credential_org_id, credential_user_id = _load_workspace_credentials()
    auth_enabled = bool(user and password)
    if credential_org_id and auth_enabled and credential_org_id != bound_org_id:
        raise RuntimeError(
            f"Workspace credentials are scoped to institution '{credential_org_id}', "
            f"but process is bound to '{bound_org_id}'"
        )
    resolved_user_id = None
    actor_source = None
    if credential_user_id:
        resolved_user_id = credential_user_id
        actor_source = 'credentials'
    elif user and _member_role(bound_org_id, user):
        resolved_user_id = user
        actor_source = 'basic_user_id'
    elif user == 'owner':
        org = load_orgs().get('organizations', {}).get(bound_org_id)
        owner_id = (org or {}).get('owner_id')
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
    current_role = _member_role(bound_org_id, claims.user_id)
    return {
        'enabled': True,
        'mode': 'session_bound',
        'org_id': bound_org_id,
        'user_id': claims.user_id,
        'role': current_role,
        'actor_id': claims.user_id,
        'actor_source': 'session',
        'session_id': claims.session_id,
    }


def _member_role(org_id, user_id):
    if not org_id or not user_id:
        return None
    org = load_orgs().get('organizations', {}).get(org_id)
    if not org:
        return None
    for member in org.get('members', []):
        if member.get('user_id') == user_id:
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


def _warrant_summary(org_id):
    warrants = list_warrants(org_id)
    pending_review = 0
    executable = 0
    executed = 0
    for record in warrants:
        if record.get('court_review_state') == 'pending_review':
            pending_review += 1
        if record.get('court_review_state') in ('auto_issued', 'approved') and record.get('execution_state') == 'ready':
            executable += 1
        if record.get('execution_state') == 'executed':
            executed += 1
    return {
        'total': len(warrants),
        'pending_review': pending_review,
        'executable': executable,
        'executed': executed,
    }


def _commitment_summary(org_id):
    return commitment_summary(org_id)


def _commitment_management_state():
    return {
        'management_mode': 'workspace_api_file_backed',
        'mutation_enabled': True,
        'mutation_disabled_reason': '',
    }


def _commitment_snapshot(org_id):
    return {
        'bound_org_id': org_id,
        **_commitment_management_state(),
        **_commitment_summary(org_id),
        'commitments': list_commitments(org_id),
    }


def _payout_snapshot(org_id, *, host_supported_adapters=None):
    return {
        'bound_org_id': org_id,
        'management_mode': 'workspace_api_file_backed',
        'mutation_enabled': True,
        'mutation_disabled_reason': '',
        'summary': payout_proposal_summary(org_id),
        'proposals': list_payout_proposals(org_id),
        'policy': load_payout_proposals(org_id).get('state_machine', {}),
        'settlement_adapter_summary': settlement_adapter_summary(
            org_id,
            host_supported_adapters=host_supported_adapters,
        ),
        'settlement_adapters': list_settlement_adapters(org_id),
        'plan_preview_queue_summary': payout_plan_preview_queue_summary(org_id),
    }


def _settlement_adapter_readiness_snapshot(org_id, *, host_supported_adapters=None):
    return settlement_adapter_readiness_snapshot(
        org_id,
        host_supported_adapters=host_supported_adapters,
    )


def _case_management_state():
    return {
        'management_mode': 'workspace_api_file_backed',
        'mutation_enabled': True,
        'mutation_disabled_reason': '',
    }


def _case_snapshot(org_id):
    return {
        'bound_org_id': org_id,
        **_case_management_state(),
        **case_summary(org_id),
        'blocking_commitment_ids': blocking_commitment_ids(org_id),
        'blocked_peer_host_ids': blocked_peer_host_ids(org_id),
        'cases': list_cases(org_id),
    }


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
    host_identity, admission_registry = _runtime_host_state(bound_org_id)
    authority = _federation_authority(host_identity)
    authority.ensure_enabled()
    peer = authority.peer_registry.get('peers', {}).get(target_host_id)
    if not peer:
        raise FederationDeliveryError(f"Peer host '{target_host_id}' is not in peer registry")
    if peer.trust_state == 'revoked':
        raise FederationDeliveryError(
            f"Peer host '{target_host_id}' is not trusted (state={peer.trust_state})"
        )
    if not peer.receive_url:
        raise FederationDeliveryError(
            f"Peer host '{target_host_id}' does not declare endpoint_url"
        )
    if not (peer.manifest_url.lower().startswith('http://') or peer.manifest_url.lower().startswith('https://')):
        raise FederationDeliveryError(f"Invalid URL scheme for manifest in peer '{target_host_id}'")
    try:
        request = urllib_request.Request(peer.manifest_url, method='GET')
        with urllib_request.urlopen(request, timeout=10) as response:
            manifest = json.loads(response.read().decode('utf-8') or '{}')
    except urllib_error.HTTPError as exc:
        body = exc.read().decode('utf-8')
        raise FederationDeliveryError(
            f"Failed fetching federation manifest from '{peer.host_id}': HTTP {exc.code}: {body}",
            peer_host_id=peer.host_id,
        ) from exc
    except Exception as exc:
        raise FederationDeliveryError(
            f"Failed fetching federation manifest from '{peer.host_id}': {exc}",
            peer_host_id=peer.host_id,
        ) from exc
    if not isinstance(manifest, dict):
        raise FederationDeliveryError(
            f"Peer host '{peer.host_id}' returned a non-object federation manifest",
            peer_host_id=peer.host_id,
            response=manifest,
        )
    authority._validate_peer_manifest(
        peer,
        manifest,
        target_institution_id=target_institution_id,
    )
    envelope = authority.issue(
        bound_org_id,
        peer.host_id,
        target_institution_id,
        'case_notice',
        payload=federated_payload,
        actor_type='user',
        actor_id=actor_id,
        session_id=session_id or '',
    )
    claims = authority.validate(
        envelope,
        payload=federated_payload,
        expected_target_host_id=peer.host_id,
        expected_target_org_id=target_institution_id,
        expected_boundary_name='federation_gateway',
    )
    if not (peer.receive_url.lower().startswith('http://') or peer.receive_url.lower().startswith('https://')):
        raise FederationDeliveryError(f"Invalid URL scheme for receive_url in peer '{target_host_id}'")
    try:
        request = urllib_request.Request(
            peer.receive_url,
            data=json.dumps({
                'envelope': envelope,
                'payload': federated_payload,
            }).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib_request.urlopen(request, timeout=10) as response:
            delivery_response = json.loads(response.read().decode('utf-8') or '{}')
    except urllib_error.HTTPError as exc:
        body = exc.read().decode('utf-8')
        raise FederationDeliveryError(
            f"Peer returned HTTP {exc.code}: {body}",
            peer_host_id=peer.host_id,
            envelope=envelope,
            claims=claims,
        ) from exc
    except Exception as exc:
        raise FederationDeliveryError(
            f"Failed delivering federation envelope to '{peer.host_id}': {exc}",
            peer_host_id=peer.host_id,
            envelope=envelope,
            claims=claims,
        ) from exc
    receipt = authority._validate_delivery_receipt(
        delivery_response,
        peer_host_id=peer.host_id,
        target_institution_id=target_institution_id,
        claims=claims,
    )
    delivery = {
        'peer': peer.to_dict(),
        'peer_manifest': manifest,
        'envelope': envelope,
        'claims': claims.to_dict(),
        'receipt': receipt,
        'response': delivery_response,
    }
    witness_archive = _archive_delivery_with_witness_peers(
        bound_org_id,
        authority,
        delivery,
        federated_payload,
        actor_id=actor_id,
        session_id=session_id,
        host_identity=host_identity,
    )
    delivery['witness_archive'] = witness_archive
    federation_state = authority.snapshot(
        bound_org_id=bound_org_id,
        admission_registry=admission_registry,
    )
    log_event(
        bound_org_id,
        actor_id,
        'federation_envelope_sent',
        resource='case_notice',
        outcome='accepted',
        actor_type='user',
        details=_federation_audit_details(
            claims,
            peer_transport=peer.transport,
            receipt_id=receipt.get('receipt_id', ''),
            receiver_host_id=receipt.get('receiver_host_id', ''),
            receiver_institution_id=receipt.get('receiver_institution_id', ''),
            commitment_delivery_recorded=False,
            witness_archive_attempted=witness_archive.get('attempted', 0),
            witness_archive_created=witness_archive.get('created', 0),
            witness_archive_failed=witness_archive.get('failed', 0),
        ),
        session_id=session_id or None,
    )
    return {
        'delivery': delivery,
        'runtime_core': {
            'federation': federation_state,
        },
        'target_host_id': target_host_id,
        'target_institution_id': target_institution_id,
        'payload': federated_payload,
    }


def _subscription_snapshot(org_id):
    payload = load_subscriptions(org_id)
    return {
        'bound_org_id': org_id,
        'management_mode': 'institution_owned_service',
        'mutation_enabled': True,
        'mutation_disabled_reason': '',
        'storage_model': 'capsule_canonical',
        'boundary_name': 'subscriptions',
        'identity_model': 'session',
        'mutation_paths': [
            '/api/subscriptions/add',
            '/api/subscriptions/convert',
            '/api/subscriptions/verify-payment',
            '/api/subscriptions/remove',
            '/api/subscriptions/set-email',
            '/api/subscriptions/record-delivery',
        ],
        'summary': subscription_summary(org_id),
        'meta': payload.get('_meta', {}),
        'state': payload,
        'subscribers': payload.get('subscribers', {}),
        'delivery_log_tail': payload.get('delivery_log', [])[-20:],
        'active_delivery_targets': active_delivery_targets(org_id, external_only=True),
    }


def _maybe_open_case_for_commitment_breach(commitment_record, actor_id, *, org_id, note=''):
    return ensure_case_for_commitment_breach(
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
    case_record = blocking_commitment_case(commitment_id, org_id=org_id)
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
            commitment_case = blocking_commitment_case(commitment_id, org_id=org_id)
            if commitment_case:
                return commitment_case
        return blocking_peer_case(target_host_id, org_id=org_id)
    except (SystemExit, ValueError):
        return None


def _maybe_suspend_peer_for_case(case_record, actor_id, *, org_id, session_id=None):
    if not case_requires_peer_block(case_record):
        return None
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
    try:
        peer_registry = set_peer_trust_state(
            FEDERATION_PEERS_FILE,
            target_host_id,
            'suspended',
            host_identity=host_identity,
        )
    except LookupError:
        return {
            'applied': False,
            'peer_host_id': target_host_id,
            'reason': 'peer_not_registered',
            'trust_state': '',
        }

    snapshot = _federation_snapshot(
        org_id,
        host_identity=host_identity,
        admission_registry=admission_registry,
        peer_registry=peer_registry,
    )
    peer_record = next(
        (peer for peer in snapshot.get('peers', []) if peer.get('host_id') == target_host_id),
        None,
    )
    log_event(
        org_id,
        actor_id,
        'federation_peer_auto_suspended',
        resource=target_host_id,
        outcome='success',
        details={
            'peer_host_id': target_host_id,
            'case_id': case_record.get('case_id', ''),
            'claim_type': case_record.get('claim_type', ''),
            'trust_state': (peer_record or {}).get('trust_state', ''),
        },
        session_id=session_id,
    )
    return {
        'applied': True,
        'peer_host_id': target_host_id,
        'reason': '',
        'trust_state': (peer_record or {}).get('trust_state', ''),
        'federation': snapshot,
    }


def _maybe_restore_peer_for_case(case_record, actor_id, *, org_id, session_id=None):
    if not case_targets_peer(case_record):
        return None
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
    current_peer = _federation_peer_state(target_host_id, host_identity=host_identity)
    if current_peer and current_peer.get('trust_state') == 'revoked':
        return {
            'applied': False,
            'peer_host_id': target_host_id,
            'reason': 'peer_revoked',
            'trust_state': 'revoked',
        }
    remaining_case = blocking_peer_case(target_host_id, org_id=org_id)
    if remaining_case:
        snapshot = _federation_snapshot(
            org_id,
            host_identity=host_identity,
            admission_registry=admission_registry,
        )
        peer_record = next(
            (peer for peer in snapshot.get('peers', []) if peer.get('host_id') == target_host_id),
            None,
        )
        return {
            'applied': False,
            'peer_host_id': target_host_id,
            'reason': 'other_blocking_case_remains',
            'trust_state': (peer_record or {}).get('trust_state', ''),
            'case_id': remaining_case.get('case_id', ''),
            'federation': snapshot,
        }
    if current_peer and current_peer.get('trust_state') == 'trusted':
        return {
            'applied': False,
            'peer_host_id': target_host_id,
            'reason': 'already_trusted',
            'trust_state': 'trusted',
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

    snapshot = _federation_snapshot(
        org_id,
        host_identity=host_identity,
        admission_registry=admission_registry,
        peer_registry=peer_registry,
    )
    peer_record = next(
        (peer for peer in snapshot.get('peers', []) if peer.get('host_id') == target_host_id),
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
            'trust_state': (peer_record or {}).get('trust_state', ''),
        },
        session_id=session_id,
    )
    return {
        'applied': True,
        'peer_host_id': target_host_id,
        'reason': '',
        'trust_state': (peer_record or {}).get('trust_state', ''),
        'federation': snapshot,
    }


def _sender_warrant_delivery_ref_for_settlement_notice(commitment, claims, *, payload=None):
    payload = payload if isinstance(payload, dict) else {}
    execution_envelope_id = (payload.get('envelope_id') or '').strip()
    for ref in reversed(list((commitment or {}).get('delivery_refs') or [])):
        ref = dict(ref or {})
        if (ref.get('message_type') or '').strip() != 'execution_request':
            continue
        if execution_envelope_id and (ref.get('envelope_id') or '').strip() != execution_envelope_id:
            continue
        if (ref.get('target_host_id') or '').strip() != (claims.source_host_id or '').strip():
            continue
        if (ref.get('target_institution_id') or '').strip() != (claims.source_institution_id or '').strip():
            continue
        warrant_id = (ref.get('warrant_id') or '').strip()
        if warrant_id:
            return warrant_id, ref
    return '', None


def _finalize_sender_warrant_for_settlement_notice(bound_org_id, claims, receipt, commitment,
                                                   settlement_ref, *, payload=None):
    warrant_id, delivery_ref = _sender_warrant_delivery_ref_for_settlement_notice(
        commitment,
        claims,
        payload=payload,
    )
    if not warrant_id:
        return None
    warrant = get_warrant(warrant_id, org_id=bound_org_id)
    if not warrant:
        return None
    if warrant.get('execution_state') == 'executed':
        return warrant
    if warrant.get('execution_state') != 'ready':
        return warrant
    execution_refs = {
        'message_type': 'execution_request',
        'envelope_id': (delivery_ref or {}).get('envelope_id', ''),
        'target_host_id': (delivery_ref or {}).get('target_host_id', ''),
        'target_institution_id': (delivery_ref or {}).get('target_institution_id', ''),
        'receipt_id': (delivery_ref or {}).get('receipt_id', ''),
        'receiver_host_id': (delivery_ref or {}).get('receiver_host_id', ''),
        'receiver_institution_id': (delivery_ref or {}).get('receiver_institution_id', ''),
        'commitment_id': claims.commitment_id,
        'completion_message_type': 'settlement_notice',
        'completion_envelope_id': claims.envelope_id,
        'completion_receipt_id': (receipt or {}).get('receipt_id', ''),
        'completion_source_host_id': claims.source_host_id,
        'completion_source_institution_id': claims.source_institution_id,
        'settlement_ref': dict(settlement_ref or {}),
    }
    return mark_warrant_executed(
        warrant_id,
        org_id=bound_org_id,
        execution_refs=execution_refs,
    )


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
        case_record, created = ensure_case_for_delivery_failure(
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


def _scoped_registry(org_id):
    """Filter agent registry to a single institution's agents.

    Currently always called with the founding org from _get_founding_org().
    The org_id filter is real substrate behavior (not inert) — it correctly
    excludes agents that belong to a different org_id.  Multi-org API
    exposure is blocked until an org-scoped auth model exists.
    """
    reg = load_registry()
    if org_id is None:
        return reg
    scoped_agents = {
        agent_id: agent
        for agent_id, agent in reg.get('agents', {}).items()
        if agent.get('org_id') in (None, org_id)
    }
    return {
        **reg,
        'agents': scoped_agents,
    }


# -- API data builders --------------------------------------------------------

def _treasury_snapshot_with_host_adapters(org_id, host_identity):
    host_supported_adapters = getattr(host_identity, 'settlement_adapters', [])
    try:
        return treasury_snapshot(
            org_id,
            host_supported_adapters=host_supported_adapters,
        )
    except TypeError as exc:
        if 'host_supported_adapters' not in str(exc):
            raise
        return treasury_snapshot(org_id)

def api_status(org_id=None, context_source='founding_default', institution_context=None,
               request_routing=None):
    if institution_context is not None:
        inst_ctx = institution_context
    elif org_id is None:
        inst_ctx = _resolve_workspace_context()
    else:
        org = load_orgs().get('organizations', {}).get(org_id)
        inst_ctx = InstitutionContext.bind(org_id, org, context_source, WORKSPACE_BOUNDARY)

    org_id = inst_ctx.org_id
    org = inst_ctx.org
    context_source = inst_ctx.context_source
    host_identity, admission_registry = _runtime_host_state(org_id)

    reg = _scoped_registry(org_id)
    queue = _load_queue(org_id)
    snap = _treasury_snapshot_with_host_adapters(org_id, host_identity)
    records = _load_records(org_id)
    lead_id, lead_auth = get_sprint_lead(org_id)
    auth_context = _resolve_auth_context(org_id)
    try:
        peer_registry = load_peer_registry(FEDERATION_PEERS_FILE, host_identity=host_identity)
    except RuntimeError as exc:
        peer_registry = {
            'source': 'error',
            'host_id': getattr(host_identity, 'host_id', '') or '',
            'peers': {},
            'trusted_peer_ids': [],
            'error': str(exc),
        }
    routing_planner = _routing_planner_snapshot(
        org_id,
        requested_org_ids=[(request_routing or {}).get('requested_org_id', '')],
        host_identity=host_identity,
        admission_registry=admission_registry,
        peer_registry=peer_registry,
        org_registry=load_orgs().get('organizations', {}),
    )
    if peer_registry.get('error'):
        routing_planner['peer_registry_error'] = peer_registry['error']

    agents = []
    remediations = []
    for a in reg['agents'].values():
        a = normalize_agent_record(a)
        restrictions = get_restrictions(a.get('economy_key', a['name'].lower()), org_id=org_id)
        remediation = None
        if _ci_vertical_available:
            remediation = get_agent_remediation(a.get('economy_key', a['name'].lower()), reg)
        if remediation:
            remediations.append(remediation)
        agents.append({
            'id': a['id'], 'name': a['name'], 'role': a['role'],
            'purpose': a['purpose'],
            'rep': a['reputation_units'], 'auth': a['authority_units'],
            'runtime_binding': a.get('runtime_binding'),
            'risk_state': a.get('risk_state', 'nominal'),
            'lifecycle_state': a.get('lifecycle_state', 'active'),
            'economy_key': a.get('economy_key'),
            'incident_count': a.get('incident_count', 0),
            'restrictions': restrictions,
            'is_sprint_lead': a.get('economy_key') == lead_id,
            'remediation': remediation,
        })
    runtime_usage = _agent_runtime_usage_snapshot(org_id=org_id, reg=reg)

    open_violations = [v for v in records['violations'].values()
                       if v['status'] in ('open', 'sanctioned', 'appealed')]
    pending_appeals = [a for a in records['appeals'].values()
                       if a['status'] == 'pending']
    pending_approvals = [a for a in queue['pending_approvals'].values()
                         if a['status'] == 'pending']
    active_delegations = [d for d in queue['delegations'].values()
                          if d.get('expires_at', '') > _now()]

    if request_routing is None:
        request_routing = {
            'mode': 'process_bound',
            'bound_org_id': org_id,
            'effective_org_id': org_id,
            'request_override': 'exact-match-only',
            'requested_org_id': '',
            'route_state': 'bound',
            'route_reason': 'no_request_override',
        }

    result = {
        'context': {
            'mode': 'process_bound',
            'bound_org_id': org_id,
            'source': context_source,
            'request_override': 'exact-match-only',
            'request_routing': request_routing,
            'auth': auth_context,
            'permissions': _permission_snapshot(auth_context),
        },
        'routing_planner': routing_planner,
        'handoff_preview_queue': _handoff_preview_queue_snapshot(org_id),
        'runtime_core': runtime_core_snapshot(
            inst_ctx,
            additional_institutions_allowed=True,
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
            'owner_id': org.get('owner_id', ''),
            'treasury_id': org.get('treasury_id'),
        } if org else None,
        'agents': agents,
        'authority': {
            'kill_switch': queue['kill_switch'],
            'pending_approvals': pending_approvals,
            'active_delegations': active_delegations,
            'sprint_lead': {'agent_id': lead_id, 'auth': lead_auth},
        },
        'treasury': snap,
        'court': {
            'open_violations': open_violations,
            'pending_appeals': pending_appeals,
            'total_violations': len(records['violations']),
            'total_appeals': len(records['appeals']),
        },
        'warrants': _warrant_summary(org_id),
        'commitments': _commitment_snapshot(org_id),
        'cases': _case_snapshot(org_id),
        'service_state': {
            'subscriptions': _subscription_snapshot(org_id),
            'accounting': accounting_snapshot(org_id),
        },
        'remediations': remediations,
        'timestamp': _now(),
    }
    result['runtime_core']['runtime_usage'] = runtime_usage
    result['runtime_core']['federation'] = _federation_snapshot(
        org_id,
        host_identity=host_identity,
        admission_registry=admission_registry,
    )

    if _ci_vertical_available:
        result['ci_vertical'] = _ci_vertical_status(reg, lead_id, org_id=org_id)

    if _phase_machine_available:
        try:
            phase_num, phase_info = current_phase(org_id)
            result['phase_machine'] = {
                'current_phase': phase_num,
                'name': phase_info['name'],
                'description': phase_info['description'],
                'next_phase': phase_info.get('next_phase'),
                'next_unlock': phase_info.get('next_unlock'),
                'checks': phase_info.get('checks', []),
            }
        except Exception:
            result['phase_machine'] = {'error': 'evaluation failed'}

    return result


def _agent_runtime_usage_snapshot(org_id=None, reg=None):
    if reg is None:
        reg = _scoped_registry(org_id)
    usage = {}
    unregistered_bindings = []
    for agent in (reg or {}).get('agents', {}).values():
        normalized = normalize_agent_record(agent)
        binding = dict(normalized.get('runtime_binding') or {})
        runtime_id = (binding.get('runtime_id') or '').strip()
        if not runtime_id:
            continue
        entry = usage.setdefault(runtime_id, {
            'runtime_id': runtime_id,
            'bound_agent_ids': [],
            'bound_org_ids': [],
        })
        entry['bound_agent_ids'].append(normalized.get('id'))
        bound_org_id = normalized.get('org_id')
        if bound_org_id:
            entry['bound_org_ids'].append(bound_org_id)
        if not binding.get('runtime_registered', True):
            unregistered_bindings.append({
                'agent_id': normalized.get('id'),
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


def _ci_vertical_status(reg, lead_id, org_id=None):
    """Build CI vertical constitutional gate status."""
    phases, blocked_phases = _phase_gate_snapshot(reg, org_id=org_id)
    all_clear = all(p['clear'] for p in phases)

    return {
        'preflight': 'CLEAR' if (all_clear and not is_kill_switch_engaged(org_id=org_id)) else 'BLOCKED',
        'blocked_phases': blocked_phases,
        'phases': phases,
    }


# -- HTML Dashboard -----------------------------------------------------------

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Governed Workspace</title>
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

<h1>Governed Workspace</h1>
<p class="subtitle">Constitutional Operating System -- Five Primitives Demo</p>

<div class="status-bar" id="status-bar">Loading...</div>

<!-- PHASE MACHINE -->
<h2>Phase Machine</h2>
<div class="card" id="phase-card">Loading...</div>

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

function riskTag(state) {
  if (state === 'critical') return '<span class="tag tag-crit">CRITICAL</span>';
  if (state === 'elevated') return '<span class="tag tag-warn">ELEVATED</span>';
  if (state === 'suspended') return '<span class="tag tag-crit">SUSPENDED</span>';
  return '<span class="tag tag-live">NOMINAL</span>';
}

function render(data) {
  currentContext = data.context || null;
  var ks = data.authority.kill_switch;
  var sb = '';
  sb += '<span class="item">Kill switch: ' + (ks.engaged
    ? '<span class="tag tag-on">ENGAGED</span>' : '<span class="tag tag-off">OFF</span>') + '</span>';
  sb += '<span class="item">Balance: <strong>$' + data.treasury.balance_usd.toFixed(2) + '</strong></span>';
  sb += '<span class="item">Runway: <strong>$' + data.treasury.runway_usd.toFixed(2) + '</strong></span>';
  sb += '<span class="item">Violations: <strong>' + data.court.open_violations.length + ' open</strong></span>';
  sb += '<span class="item">Approvals: <strong>' + data.authority.pending_approvals.length + ' pending</strong></span>';
  sb += '<span class="item">Lead: <strong>' + (data.authority.sprint_lead.agent_id || 'none') + '</strong></span>';
  if (data.context && data.context.auth && data.context.auth.actor_id) {
    sb += '<span class="item">Actor: <strong>' + data.context.auth.actor_id + '</strong> (' + (data.context.auth.role || 'unbound') + ')</span>';
  }
  document.getElementById('status-bar').innerHTML = sb;

  // Phase Machine
  var pm = data.phase_machine;
  if (pm && !pm.error) {
    var pc = '<div class="form-row"><label>Current Phase</label> <strong>Phase ' + pm.current_phase + ' &mdash; ' + pm.name + '</strong></div>';
    pc += '<div class="form-row"><label>Description</label> ' + pm.description + '</div>';
    if (pm.next_phase !== null && pm.next_phase !== undefined) {
      pc += '<div class="form-row"><label>Next Phase</label> Phase ' + pm.next_phase + '</div>';
      pc += '<div class="form-row"><label>Unlock needs</label> ' + (pm.next_unlock || '?') + '</div>';
    }
    if (pm.checks) {
      pc += '<table><tr><th>#</th><th>Phase</th><th>Status</th><th>Reason</th></tr>';
      pm.checks.forEach(function(c) {
        pc += '<tr><td>' + c.phase + '</td><td>' + c.name + '</td>';
        pc += '<td>' + (c.met ? '<span class="tag tag-live">PASS</span>' : '<span class="tag tag-warn">FAIL</span>') + '</td>';
        pc += '<td>' + c.reason + '</td></tr>';
      });
      pc += '</table>';
    }
    document.getElementById('phase-card').innerHTML = pc;
  } else {
    document.getElementById('phase-card').innerHTML = '<em>Phase machine not available</em>';
  }

  var inst = data.institution;
  if (inst) {
    var ic = '<div class="grid2"><div>';
    ic += '<div class="form-row"><label>Name</label> <strong>' + inst.name + '</strong></div>';
    ic += '<div class="form-row"><label>Lifecycle</label> <span class="tag tag-live">' + inst.lifecycle_state.toUpperCase() + '</span></div>';
    ic += '<div class="form-row"><label>Plan</label> ' + inst.plan + '</div>';
    ic += '</div><div>';
    ic += '<div class="form-row"><label>Charter</label></div>';
    ic += '<textarea id="charter-text" placeholder="Set institution charter...">' + (inst.charter || '') + '</textarea>';
    if (can('/api/institution/charter')) {
      ic += '<div class="action-row"><button onclick="setCharter()">Save Charter</button></div>';
    } else {
      ic += '<div class="form-row"><label></label><span style="color:var(--dim);font-size:0.8rem">Charter updates require ' + requiredRole('/api/institution/charter') + ' role.</span></div>';
    }
    ic += '</div></div>';
    document.getElementById('inst-card').innerHTML = ic;
  }

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

  var au = '<div class="card">';
  au += '<strong>Kill Switch</strong>: ' + (ks.engaged
    ? '<span class="tag tag-on">ENGAGED</span> by ' + ks.engaged_by + ' -- ' + ks.reason
      + (can('/api/authority/kill-switch') ? ' <button onclick="killSwitch(false)">Disengage</button>' : '')
    : '<span class="tag tag-off">OFF</span>' + (can('/api/authority/kill-switch') ? ' <button class="danger" onclick="killSwitch(true)">Engage Kill Switch</button>' : ' <span style="color:var(--dim);font-size:0.8rem">requires ' + requiredRole('/api/authority/kill-switch') + '</span>'));
  au += '</div>';
  au += '<div class="card"><strong>Pending Approvals</strong> (' + data.authority.pending_approvals.length + ')';
  if (data.authority.pending_approvals.length === 0) {
    au += '<div class="empty">No pending approvals</div>';
  }
  au += '</div>';
  document.getElementById('authority-section').innerHTML = au;

  var tr = data.treasury;
  var tc = '<div class="grid3">';
  tc += '<div class="metric"><div class="val">$' + tr.balance_usd.toFixed(2) + '</div><div class="label">Balance</div></div>';
  tc += '<div class="metric"><div class="val">$' + tr.runway_usd.toFixed(2) + '</div><div class="label">Runway</div></div>';
  tc += '<div class="metric"><div class="val">$' + tr.reserve_floor_usd.toFixed(2) + '</div><div class="label">Reserve Floor</div></div>';
  tc += '</div>';
  document.getElementById('treasury-card').innerHTML = tc;

  var co = '<div class="card"><strong>Open Violations</strong> (' + data.court.open_violations.length + ')';
  if (data.court.open_violations.length === 0) {
    co += '<div class="empty">No open violations</div>';
  }
  co += '</div>';
  document.getElementById('court-section').innerHTML = co;
}

function killSwitch(engage) {
  var reason = engage ? prompt('Reason for engaging kill switch:') : '';
  if (engage && !reason) return;
  api('POST', '/api/authority/kill-switch', { engage: engage, reason: reason })
    .then(function(r) { toast(r.message); refresh(); });
}

function setCharter() {
  if (!can('/api/institution/charter')) return toast('This action requires ' + requiredRole('/api/institution/charter') + ' role.');
  var text = document.getElementById('charter-text').value;
  api('POST', '/api/institution/charter', { text: text })
    .then(function(r) { toast(r.message); refresh(); });
}

function refresh() {
  api('GET', '/api/status').then(render).catch(function(e) {
    document.getElementById('status-bar').innerHTML = '<span style="color:var(--red)">Error loading: ' + e + '</span>';
  });
  api('GET', '/api/audit').then(function(data) {
    if (!data.events || data.events.length === 0) {
      document.getElementById('audit-card').innerHTML = '<div class="empty">No recent audit events</div>';
      return;
    }
    var at = '<table><tr><th>Time</th><th>Action</th><th>Agent</th><th>Outcome</th></tr>';
    data.events.slice(0, 20).forEach(function(e) {
      at += '<tr><td style="font-size:0.8rem">' + e.timestamp + '</td>';
      at += '<td>' + e.action + '</td><td>' + (e.agent_id || '-') + '</td>';
      at += '<td>' + e.outcome + '</td></tr>';
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


# -- HTTP Request Handler -----------------------------------------------------

class WorkspaceHandler(BaseHTTPRequestHandler):

    def _send_bytes(self, payload, *, status=200, content_type='application/json'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

    def _json(self, data, status=200):
        self._send_bytes(json.dumps(data).encode('utf-8'), status=status, content_type='application/json')

    def _html(self, html):
        self._send_bytes(html.encode('utf-8'), status=200, content_type='text/html; charset=utf-8')

    def _unauthorized(self, is_api=True):
        payload = (json.dumps({'error': 'Unauthorized'}).encode('utf-8') if is_api else b'Unauthorized')
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="Meridian Workspace"')
        self.send_header('Content-Type', 'application/json' if is_api else 'text/plain; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

    def _service_unavailable(self, message, is_api=True):
        payload = (json.dumps({'error': message}).encode('utf-8') if is_api else message.encode('utf-8'))
        self.send_response(503)
        self.send_header('Content-Type', 'application/json' if is_api else 'text/plain; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

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
        protected = (path == '/' or path.startswith('/workspace') or path.startswith('/api/')) \
            and path not in ('/api/session/validate', '/api/federation/manifest')
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

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if not self._require_auth(path):
            return
        try:
            inst_ctx = _resolve_workspace_context()
            org_id = inst_ctx.org_id
            org = inst_ctx.org
            context_source = inst_ctx.context_source
            request_context = _enforce_request_context(parsed, self.headers, org_id)
            session_claims = self._session_claims_from_request(expected_org_id=org_id)
            if session_claims:
                auth_context = _resolve_auth_context_from_session(session_claims, org_id)
            elif self.headers.get('Authorization', '').startswith('Bearer '):
                # Bearer was provided but invalid for this institution — never
                # fall back to credential auth silently.
                return self._json({
                    'error': 'Session token is not valid for this institution'
                }, 403)
            else:
                auth_context = _resolve_auth_context(org_id)
        except RuntimeError as e:
            return self._json({'error': str(e)}, 503)
        except ValueError as e:
            return self._json({'error': str(e)}, 400)

        service_response = _dispatch_workspace_get_service(
            self,
            path,
            org_id=org_id,
            inst_ctx=inst_ctx,
            request_context=request_context,
            auth_context=auth_context,
        )
        if service_response is not None:
            return service_response

        if path == '/' or path == '/workspace':
            return self._html(DASHBOARD_HTML)
        elif path == '/api/status':
            return self._json(api_status(institution_context=inst_ctx, request_routing=request_context))
        elif path == '/api/context':
            host_identity, admission_registry = _runtime_host_state(org_id)
            response = {
                **request_context,
                'request_routing': request_context,
                'auth': auth_context,
                'permissions': _permission_snapshot(auth_context),
                'institution': inst_ctx.to_dict(),
                'runtime_core': runtime_core_snapshot(
                    inst_ctx,
                    additional_institutions_allowed=True,
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
            return self._json(org or {})
        elif path == '/api/agents':
            reg = _scoped_registry(org_id)
            return self._json([normalize_agent_record(a) for a in reg['agents'].values()])
        elif path == '/api/authority':
            queue = _load_queue(org_id)
            lead_id, lead_auth = get_sprint_lead(org_id)
            return self._json({
                'kill_switch': queue['kill_switch'],
                'pending_approvals': list(queue['pending_approvals'].values()),
                'delegations': list(queue['delegations'].values()),
                'sprint_lead': {'agent_id': lead_id, 'auth': lead_auth},
            })
        elif path == '/api/subscriptions':
            return self._json(_subscription_snapshot(org_id))
        elif path == '/api/subscriptions/delivery-targets':
            return self._json({
                'bound_org_id': org_id,
                'targets': active_delivery_targets(org_id),
                'external_targets': active_delivery_targets(org_id, external_only=True),
            })
        elif path == '/api/accounting':
            return self._json(accounting_snapshot(org_id))
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
            return self._json(load_maintainers(org_id))
        elif path == '/api/treasury/contributors':
            return self._json(load_contributors(org_id))
        elif path == '/api/treasury/proposals':
            return self._json(load_payout_proposals(org_id))
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
        elif path == '/api/treasury/funding-sources':
            return self._json(load_funding_sources(org_id))
        elif path == '/api/treasury/payout-plan-preview-queue':
            return self._json(_payout_plan_preview_queue_snapshot(org_id))
        elif path == '/api/treasury/payout-plan-preview-queue/inspect':
            return self._json(_payout_plan_preview_queue_inspection(org_id))
        elif path == '/api/treasury/payout-plan-approval-candidate-queue':
            return self._json(payout_plan_approval_candidate_queue_snapshot(org_id))
        elif path == '/api/treasury/payout-execution-queue':
            return self._json(payout_execution_queue_snapshot(org_id))
        elif path == '/api/treasury/payout-plan-approval-candidate-queue/inspect':
            return self._json(inspect_payout_plan_approval_candidate_queue(org_id))
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
            return self._json(_handoff_preview_queue_snapshot(org_id))
        elif path == '/api/federation/handoff-dispatch-queue':
            return self._json(_handoff_dispatch_queue_snapshot(org_id))
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
            return self._json(_witness_archive_snapshot(org_id, host_identity=host_identity))
        elif path == '/api/admission':
            host_identity, admission_registry = _runtime_host_state(org_id)
            return self._json(_admission_snapshot(
                org_id,
                host_identity=host_identity,
                admission_registry=admission_registry,
            ))
        elif path == '/api/runtimes':
            data = load_runtimes()
            contracts = check_all_contracts()
            runtimes = data.get('runtimes', {})
            usage_snapshot = _agent_runtime_usage_snapshot(org_id=org_id)
            # Embed contract check result into each runtime entry
            result = {}
            for rid, rt in runtimes.items():
                result[rid] = dict(rt)
                result[rid]['contract_check'] = contracts.get(rid, {})
                result[rid]['runtime_usage'] = usage_snapshot['runtimes'].get(rid, {
                    'runtime_id': rid,
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
            rt = get_runtime(runtime_id)
            if rt is None:
                return self._json({'error': f'Runtime {runtime_id!r} not found'}, 404)
            from runtime_adapter import check_contract
            usage_snapshot = _agent_runtime_usage_snapshot(org_id=org_id)
            enriched = dict(rt)
            enriched['contract_check'] = check_contract(runtime_id)
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
                'violations': list(records['violations'].values()),
                'appeals': list(records['appeals'].values()),
            })
        elif path == '/api/warrants':
            return self._json({
                'warrants': list_warrants(org_id),
                'summary': _warrant_summary(org_id),
            })
        elif path == '/api/commitments':
            return self._json(_commitment_snapshot(org_id))
        elif path == '/api/cases':
            return self._json(_case_snapshot(org_id))
        elif path == '/api/audit':
            events = tail_events(30, org_id=org_id)
            events.reverse()
            return self._json({'events': events})
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
            except RuntimeError as e:
                return self._json({'error': str(e)}, 503)
            except ValueError as e:
                return self._json({'error': str(e)}, 400)
            service_response = _dispatch_workspace_ingress_post_service(
                self,
                path,
                body=body,
                inst_ctx=inst_ctx,
            )
            if service_response is not None:
                return service_response
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
                return self._json({'error': str(e)}, 503)
            except ValueError as e:
                return self._json({'error': str(e)}, 400)

        if path == '/api/federation/witness/archive':
            try:
                inst_ctx = _resolve_workspace_context()
                body = self._read_body()
                host_identity, _admission_registry = _runtime_host_state(inst_ctx.org_id)
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
                envelope = (body.get('envelope') or '').strip()
                if not envelope:
                    return self._json({'error': 'envelope is required'}, 400)
                receipt = body.get('receipt')
                if not isinstance(receipt, dict) or not receipt:
                    return self._json({'error': 'receipt is required'}, 400)
                payload = body.get('payload')
                source_manifest = body.get('source_manifest')
                target_manifest = body.get('target_manifest')
                authority = _federation_authority(host_identity)
                claims = authority.validate(
                    envelope,
                    payload=payload,
                    expected_boundary_name='federation_gateway',
                )
                source_peer = authority.peer_registry.get('peers', {}).get(claims.source_host_id)
                if not source_peer:
                    raise FederationValidationError(
                        f"Source host '{claims.source_host_id}' is not in peer registry"
                    )
                if not isinstance(source_manifest, dict):
                    source_peer, source_manifest = authority.fetch_peer_manifest(claims.source_host_id)
                authority._validate_peer_manifest(
                    source_peer,
                    source_manifest,
                    target_institution_id=claims.source_institution_id,
                )
                target_peer = authority.peer_registry.get('peers', {}).get(claims.target_host_id)
                if not target_peer:
                    raise FederationValidationError(
                        f"Target host '{claims.target_host_id}' is not in peer registry"
                    )
                if not isinstance(target_manifest, dict):
                    target_peer, target_manifest = authority.fetch_peer_manifest(claims.target_host_id)
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
                actor_id = claims.actor_id or f'peer:{claims.source_host_id}'
                record, created = archive_witness_observation(
                    WITNESS_ARCHIVE_FILE,
                    host_id=host_identity.host_id,
                    bound_org_id=inst_ctx.org_id,
                    actor_id=actor_id,
                    claims=claims.to_dict(),
                    receipt=validated_receipt,
                    payload=payload,
                    source_manifest=source_manifest,
                    target_manifest=target_manifest,
                )
                log_event(
                    inst_ctx.org_id,
                    actor_id,
                    'federation_witness_observation_archived',
                    resource=record['archive_id'],
                    outcome='success',
                    actor_type=claims.actor_type or 'service',
                    details={
                        'created': created,
                        'message_type': record.get('message_type', ''),
                        'source_host_id': record.get('source_host_id', ''),
                        'target_host_id': record.get('target_host_id', ''),
                        'receipt_id': record.get('receipt_id', ''),
                    },
                    session_id=claims.session_id or None,
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
                        inst_ctx.org_id,
                        host_identity=host_identity,
                    ),
                })
            except FederationDeliveryError as e:
                return self._json({'error': str(e)}, 502)
            except FederationValidationError as e:
                return self._json({'error': str(e)}, 403)
            except FederationUnavailable as e:
                return self._json({'error': str(e)}, 503)
            except RuntimeError as e:
                return self._json({'error': str(e)}, 503)
            except ValueError as e:
                return self._json({'error': str(e)}, 400)

        if not self._require_auth(path):
            return
        try:
            inst_ctx = _resolve_workspace_context()
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
            return self._json({'error': str(e)}, 503)
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
            service_response = _dispatch_workspace_post_service(
                self,
                path,
                body=body,
                org_id=org_id,
                actor_id=by,
                session_id=_sid,
                auth_context=auth_context,
                inst_ctx=inst_ctx,
            )
        except RuntimeError as e:
            return self._json({'error': str(e)}, 503)
        except LookupError as e:
            return self._json({'error': str(e)}, 404)
        except ValueError as e:
            return self._json({'error': str(e)}, 400)
        except PermissionError as e:
            return self._json({'error': str(e)}, 403)
        if service_response is not None:
            return service_response

        try:
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
                return self._json({'message': f'Approval requested: {aid}', 'approval_id': aid})

            elif path == '/api/authority/delegate':
                scopes = [s.strip() for s in body['scopes'].split(',') if s.strip()]
                did = delegate(body['from'], body['to'], scopes, body.get('hours', 24), org_id=org_id)
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
                log_event(org_id, by, 'violation_filed', resource=vid,
                          outcome='success',
                          details={'agent': body['agent'], 'type': body['type'], 'severity': body['severity']},
                          session_id=_sid)
                return self._json({'message': f'Violation filed: {vid}', 'violation_id': vid})

            elif path == '/api/court/resolve':
                resolve_violation(body['violation_id'], body['note'], org_id=org_id)
                log_event(org_id, by, 'violation_resolved', resource=body['violation_id'],
                          outcome='success', details={'note': body['note']},
                          session_id=_sid)
                return self._json({'message': f'Violation resolved: {body["violation_id"]}'})

            elif path == '/api/court/appeal':
                aid = file_appeal(body['violation_id'], body['agent'], body['grounds'], org_id=org_id)
                return self._json({'message': f'Appeal filed: {aid}', 'appeal_id': aid})

            elif path == '/api/court/decide-appeal':
                decide_appeal(body['appeal_id'], body['decision'], by, org_id=org_id)
                log_event(org_id, by, 'appeal_decided', resource=body['appeal_id'],
                          outcome='success', details={'decision': body['decision']},
                          session_id=_sid)
                return self._json({'message': f'Appeal {body["appeal_id"]}: {body["decision"]}'})

            elif path == '/api/court/auto-review':
                vids = auto_review(org_id=org_id)
                log_event(org_id, by, 'court_auto_review', outcome='success',
                          details={'violations': vids, 'count': len(vids)},
                          session_id=_sid)
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

            elif path == '/api/subscriptions/add':
                result = add_subscription(
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
                    'service_state': _subscription_snapshot(org_id),
                })

            elif path == '/api/subscriptions/convert':
                result = convert_trial_subscription(
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
                    'service_state': _subscription_snapshot(org_id),
                })

            elif path == '/api/subscriptions/verify-payment':
                result = verify_subscription_payment(
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
                    'service_state': _subscription_snapshot(org_id),
                })

            elif path == '/api/subscriptions/remove':
                result = cancel_active(
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
                    'service_state': _subscription_snapshot(org_id),
                })

            elif path == '/api/subscriptions/set-email':
                subscription = set_email(
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
                    'service_state': _subscription_snapshot(org_id),
                })

            elif path == '/api/subscriptions/record-delivery':
                entry = record_delivery(
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
                    'service_state': _subscription_snapshot(org_id),
                })

            elif path == '/api/accounting/expense':
                result = record_owner_expense(
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
                    'service_state': accounting_snapshot(org_id),
                })

            elif path == '/api/accounting/reimburse':
                result = reimburse_owner(
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
                    'service_state': accounting_snapshot(org_id),
                })

            elif path == '/api/accounting/draw':
                result = take_owner_draw(
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
                    'service_state': accounting_snapshot(org_id),
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

            elif path == '/api/treasury/payout-plan-approval-candidate-queue/promote':
                preview_id = (body.get('preview_id') or '').strip()
                if not preview_id:
                    return self._json({'error': 'preview_id is required'}, 400)
                candidate = promote_payout_plan_preview_to_approval_candidate(
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
                    'summary': payout_plan_approval_candidate_queue_snapshot(org_id)['summary'],
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
                warrant = validate_warrant_for_execution(
                    warrant_id,
                    org_id=org_id,
                    action_class='payout_execution',
                    boundary_name='payouts',
                    actor_id=by,
                    session_id=_sid or '',
                    request_payload=request_payload,
                )
                dry_run = bool(body.get('dry_run'))
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
                    dry_run=dry_run,
                )
                if dry_run:
                    log_event(
                        org_id,
                        by,
                        'payout_execution_previewed',
                        outcome='success',
                        resource=proposal_id,
                        details={
                            'amount_usd': proposal['execution_plan']['amount_usd'],
                            'recipient_wallet_id': proposal['execution_plan']['recipient_wallet_id'],
                            'warrant_id': warrant_id,
                            'tx_ref': proposal['execution_plan']['tx_ref'],
                            'linked_commitment_id': linked_commitment_id,
                        },
                        session_id=_sid,
                    )
                    return self._json({
                        'message': f'Payout execution previewed: {proposal_id}',
                        'proposal': proposal,
                        'warrant': warrant,
                        'summary': payout_proposal_summary(org_id),
                    })
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
                summary = (body.get('summary') or body.get('commitment_type') or '').strip()
                if not target_host_id:
                    return self._json({'error': 'target_host_id is required'}, 400)
                if not target_org_id:
                    return self._json({'error': 'target_institution_id is required'}, 400)
                if not summary:
                    return self._json({'error': 'summary is required'}, 400)
                commitment = propose_commitment(
                    org_id,
                    target_host_id,
                    target_org_id,
                    summary,
                    by,
                    terms_payload=body.get('terms_payload'),
                    warrant_id=(body.get('warrant_id') or '').strip(),
                    note=body.get('note', ''),
                    metadata=body.get('metadata'),
                )
                log_event(
                    org_id,
                    by,
                    'commitment_proposed',
                    outcome='success',
                    resource=commitment['commitment_id'],
                    details={
                        'target_host_id': target_host_id,
                        'target_institution_id': target_org_id,
                        'summary': summary,
                        'warrant_id': commitment.get('warrant_id', ''),
                    },
                    session_id=_sid,
                )
                response = {
                    'message': f"Commitment proposed: {commitment['commitment_id']}",
                    'commitment': commitment,
                    'summary': _commitment_summary(org_id),
                }
                if body.get('federate'):
                    federated_payload = {'summary': summary}
                    if 'terms_payload' in body:
                        federated_payload['terms_payload'] = body.get('terms_payload')
                    if body.get('note'):
                        federated_payload['note'] = body.get('note', '')
                    if 'metadata' in body:
                        federated_payload['metadata'] = body.get('metadata')
                    try:
                        delivery, federation_state = _deliver_federation_envelope(
                            org_id,
                            target_host_id,
                            target_org_id,
                            'commitment_proposal',
                            payload=federated_payload,
                            actor_type='user',
                            actor_id=by,
                            session_id=_sid or '',
                            warrant_id=commitment.get('warrant_id', ''),
                            commitment_id=commitment['commitment_id'],
                        )
                    except FederationUnavailable as e:
                        response['error'] = str(e)
                        return self._json(response, 503)
                    except PermissionError as e:
                        response['error'] = str(e)
                        response['case'] = getattr(e, 'case_record', None)
                        response['federation_peer'] = getattr(e, 'federation_peer', None)
                        response['warrant'] = getattr(e, 'warrant', None)
                        if response['case']:
                            return self._json(response, 409)
                        return self._json(response, 403)
                    except FederationDeliveryError as e:
                        response.update({
                            'error': str(e),
                            'peer_host_id': e.peer_host_id,
                            'claims': _federation_claims_dict(e.claims),
                            'case': getattr(e, 'case_record', None),
                            'federation_peer': getattr(e, 'federation_peer', None),
                            'warrant': getattr(e, 'warrant', None),
                        })
                        return self._json(response, 502)
                    response['delivery'] = delivery
                    response['runtime_core'] = {
                        'federation': federation_state,
                    }
                return self._json(response)

            elif path in (
                '/api/commitments/accept',
                '/api/commitments/reject',
                '/api/commitments/breach',
                '/api/commitments/settle',
            ):
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
                decision = path.rsplit('/', 1)[-1]
                if decision == 'settle':
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
                            'summary': _commitment_summary(org_id),
                        }, 409)
                    if settlement_ref:
                        record_settlement_ref(
                            commitment_id,
                            settlement_ref,
                            org_id=org_id,
                        )
                decision_past = {
                    'accept': 'accepted',
                    'reject': 'rejected',
                    'breach': 'breached',
                    'settle': 'settled',
                }
                event_name = {
                    'accept': 'commitment_accepted',
                    'reject': 'commitment_rejected',
                    'breach': 'commitment_breached',
                    'settle': 'commitment_settled',
                }[decision]
                commitment = {
                    'accept': accept_commitment,
                    'reject': reject_commitment,
                    'breach': breach_commitment,
                    'settle': settle_commitment,
                }[decision](
                    commitment_id,
                    by,
                    org_id=org_id,
                    note=body.get('note', ''),
                )
                log_event(
                    org_id,
                    by,
                    event_name,
                    outcome='success',
                    resource=commitment_id,
                    details={'status': commitment['status']},
                    session_id=_sid,
                )
                case_record = None
                warrant = None
                if decision == 'breach' and body.get('open_case', True):
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
                            outcome='success',
                            resource=case_record['case_id'],
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
                response = {
                    'message': f"Commitment {decision_past[decision]}: {commitment_id}",
                    'commitment': commitment,
                    'proposal': settlement_proposal,
                    'summary': _commitment_summary(org_id),
                    'case': case_record,
                    'warrant': warrant,
                }
                if decision == 'accept' and body.get('federate'):
                    target_host_id = (
                        body.get('target_host_id')
                        or commitment.get('source_host_id')
                        or ''
                    ).strip()
                    target_org_id = (
                        body.get('target_institution_id')
                        or body.get('target_org_id')
                        or commitment.get('source_institution_id')
                        or ''
                    ).strip()
                    if not target_host_id:
                        response['error'] = (
                            f"Commitment '{commitment_id}' does not declare source_host_id for "
                            'federated acceptance dispatch'
                        )
                        return self._json(response, 400)
                    if not target_org_id:
                        response['error'] = (
                            f"Commitment '{commitment_id}' does not declare source_institution_id for "
                            'federated acceptance dispatch'
                        )
                        return self._json(response, 400)
                    federated_payload = {}
                    if body.get('note'):
                        federated_payload['note'] = body.get('note', '')
                    try:
                        delivery, federation_state = _deliver_federation_envelope(
                            org_id,
                            target_host_id,
                            target_org_id,
                            'commitment_acceptance',
                            payload=federated_payload,
                            actor_type='user',
                            actor_id=by,
                            session_id=_sid or '',
                            warrant_id=(body.get('warrant_id') or '').strip(),
                            commitment_id=commitment_id,
                        )
                    except FederationUnavailable as e:
                        response['error'] = str(e)
                        return self._json(response, 503)
                    except PermissionError as e:
                        response['error'] = str(e)
                        response['case'] = getattr(e, 'case_record', None)
                        response['federation_peer'] = getattr(e, 'federation_peer', None)
                        response['warrant'] = getattr(e, 'warrant', None)
                        if response['case']:
                            return self._json(response, 409)
                        return self._json(response, 403)
                    except FederationDeliveryError as e:
                        response.update({
                            'error': str(e),
                            'peer_host_id': e.peer_host_id,
                            'claims': _federation_claims_dict(e.claims),
                            'case': getattr(e, 'case_record', None),
                            'federation_peer': getattr(e, 'federation_peer', None),
                            'warrant': getattr(e, 'warrant', None),
                        })
                        return self._json(response, 502)
                    response['delivery'] = delivery
                    response['runtime_core'] = {
                        'federation': federation_state,
                    }
                if decision == 'breach' and body.get('federate'):
                    target_host_id = (
                        body.get('target_host_id')
                        or commitment.get('source_host_id')
                        or ''
                    ).strip()
                    target_org_id = (
                        body.get('target_institution_id')
                        or body.get('target_org_id')
                        or commitment.get('source_institution_id')
                        or ''
                    ).strip()
                    if not target_host_id:
                        response['error'] = (
                            f"Commitment '{commitment_id}' does not declare source_host_id for "
                            'federated breach dispatch'
                        )
                        return self._json(response, 400)
                    if not target_org_id:
                        response['error'] = (
                            f"Commitment '{commitment_id}' does not declare source_institution_id for "
                            'federated breach dispatch'
                        )
                        return self._json(response, 400)
                    federated_payload = {}
                    if body.get('note'):
                        federated_payload['note'] = body.get('note', '')
                    try:
                        delivery, federation_state = _deliver_federation_envelope(
                            org_id,
                            target_host_id,
                            target_org_id,
                            'commitment_breach_notice',
                            payload=federated_payload,
                            actor_type='user',
                            actor_id=by,
                            session_id=_sid or '',
                            warrant_id=(body.get('warrant_id') or '').strip(),
                            commitment_id=commitment_id,
                        )
                    except FederationUnavailable as e:
                        response['error'] = str(e)
                        return self._json(response, 503)
                    except PermissionError as e:
                        response['error'] = str(e)
                        response['case'] = getattr(e, 'case_record', None)
                        response['federation_peer'] = getattr(e, 'federation_peer', None)
                        response['warrant'] = getattr(e, 'warrant', None)
                        if response['case']:
                            return self._json(response, 409)
                        return self._json(response, 403)
                    except FederationDeliveryError as e:
                        response.update({
                            'error': str(e),
                            'peer_host_id': e.peer_host_id,
                            'claims': _federation_claims_dict(e.claims),
                            'case': getattr(e, 'case_record', None),
                            'federation_peer': getattr(e, 'federation_peer', None),
                            'warrant': getattr(e, 'warrant', None),
                        })
                        return self._json(response, 502)
                    response['delivery'] = delivery
                    response['runtime_core'] = {
                        'federation': federation_state,
                    }
                return self._json(response)

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
                case_record = open_case(
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
                    dedupe_existing=True,
                )
                log_event(
                    org_id,
                    by,
                    'case_opened',
                    outcome='success',
                    resource=case_record['case_id'],
                    details={
                        'claim_type': claim_type,
                        'linked_commitment_id': case_record.get('linked_commitment_id', ''),
                        'linked_warrant_id': case_record.get('linked_warrant_id', ''),
                    },
                    session_id=_sid,
                )
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
                        return self._json({'error': str(e), 'case': case_record}, 503)
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
                prior_case = get_case(case_id, org_id=org_id)
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
                    'stay': stay_case,
                    'resolve': resolve_case,
                }[decision](
                    case_id,
                    by,
                    org_id=org_id,
                    note=body.get('note', ''),
                )
                log_event(
                    org_id,
                    by,
                    event_name,
                    outcome='success',
                    resource=case_id,
                    details={'status': case_record['status']},
                    session_id=_sid,
                )
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
                elif decision == 'resolve':
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
                        return self._json({'error': str(e), 'case': case_record}, 503)
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
                    response['message'] = 'Federation handoff preview acknowledged and promoted to dispatch'
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
                        session_id=_sid,
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
                        response['message'] = 'Federation handoff dispatch was already delivered to the remote host'
                else:
                    response['message'] = 'Federation handoff dispatch promoted to receiver-side execution job'
                    if dispatch_runner.get('blocking_case'):
                        response['message'] = 'Federation handoff dispatch promoted to blocked receiver-side execution job'
                return self._json(response)

            elif path == '/api/federation/execution-jobs/execute':
                job_ref = (body.get('job_id') or body.get('envelope_id') or body.get('local_warrant_id') or '').strip()
                if not job_ref:
                    return self._json({'error': 'job_id is required'}, 400)
                if body.get('execution_refs'):
                    return self._json({
                        'error': (
                            'execution_refs are not accepted; the settlement proof is derived '
                            'from the linked payout proposal'
                        )
                    }, 400)
                job = get_execution_job(job_ref, org_id=org_id) or get_execution_job_by_local_warrant(job_ref, org_id)
                if not job:
                    return self._json({'error': f'Execution job not found: {job_ref}'}, 404)
                try:
                    execution = _complete_federated_execution_job(
                        org_id,
                        job,
                        actor_id=by,
                        session_id=_sid,
                    )
                except FederationUnavailable as e:
                    return self._json({'error': str(e)}, 503)
                except FederationDeliveryError as e:
                    return self._json({
                        'error': str(e),
                        'peer_host_id': e.peer_host_id,
                        'claims': _federation_claims_dict(e.claims),
                    }, 502)
                except PermissionError as e:
                    return self._json({'error': str(e)}, 403)
                except LookupError as e:
                    return self._json({'error': str(e)}, 404)
                except ValueError as e:
                    return self._json({'error': str(e)}, 400)
                return self._json({
                    'message': 'Federated execution job executed',
                    **execution,
                })

            elif path in (
                '/api/federation/peers/upsert',
                '/api/federation/peers/refresh',
                '/api/federation/peers/suspend',
                '/api/federation/peers/revoke',
            ):
                action = path.rsplit('/', 1)[-1]
                peer_host_id = (body.get('peer_host_id') or body.get('host_id') or '').strip()
                snapshot = _mutate_federation_peer(org_id, action, body)
                peer_record = next(
                    (
                        peer for peer in snapshot.get('peers', [])
                        if peer.get('host_id') == peer_host_id
                    ),
                    None,
                )
                log_event(
                    org_id,
                    by,
                    f'federation_peer_{action}',
                    resource=peer_host_id,
                    outcome='success',
                    details={
                        'peer_host_id': peer_host_id,
                        'host_id': snapshot['host_id'],
                        'management_mode': snapshot['management_mode'],
                        'trust_state': (peer_record or {}).get('trust_state', ''),
                        'last_refreshed_at': (peer_record or {}).get('last_refreshed_at', ''),
                        'manifest_version': (
                            ((peer_record or {}).get('capability_snapshot') or {}).get('manifest_version')
                        ),
                    },
                    session_id=_sid,
                )
                return self._json({
                    'message': f'Federation peer {action} applied to {peer_host_id}',
                    'federation': snapshot,
                })

            elif path in ('/api/admission/admit', '/api/admission/suspend', '/api/admission/revoke'):
                action = path.rsplit('/', 1)[-1]
                target_org_id = body.get('org_id')
                snapshot = _mutate_admission(org_id, action, target_org_id)
                log_event(
                    org_id,
                    by,
                    f'admission_{action}',
                    resource=target_org_id or '',
                    outcome='success',
                    details={
                        'target_org_id': target_org_id,
                        'host_id': snapshot['host_id'],
                        'host_role': snapshot['host_role'],
                        'status': snapshot['institutions'][target_org_id]['status'],
                    },
                    session_id=_sid,
                )
                return self._json({
                    'message': f'Admission {action} applied to {target_org_id}',
                    'admission': snapshot,
                })

            elif path == '/api/institution/charter':
                set_charter(org_id, body['text'])
                log_event(org_id, by, 'charter_set', outcome='success',
                          session_id=_sid)
                return self._json({'message': 'Charter saved'})

            elif path == '/api/institution/lifecycle':
                org_transition_lifecycle(org_id, body['state'])
                log_event(org_id, by, 'lifecycle_transitioned', outcome='success',
                          details={'state': body['state']}, session_id=_sid)
                return self._json({'message': f'Lifecycle transitioned to {body["state"]}'})

            else:
                return self._json({'error': 'Not found'}, 404)

        except PermissionError as e:
            return self._json({'error': str(e)}, 403)
        except LookupError as e:
            return self._json({'error': str(e)}, 404)
        except Exception as e:
            return self._json({'error': str(e)}, 400)


def main():
    global WORKSPACE_ORG_ID
    parser = argparse.ArgumentParser(description='Governed Workspace server')
    parser.add_argument('--port', type=int, default=18901)
    parser.add_argument('--org-id', default=None,
                        help='Bind this workspace process to one institution. No request-level org routing is exposed.')
    args = parser.parse_args()
    if args.org_id:
        WORKSPACE_ORG_ID = args.org_id

    inst_ctx = _resolve_workspace_context()
    org_id, org, context_source = inst_ctx.org_id, inst_ctx.org, inst_ctx.context_source

    server = HTTPServer(('127.0.0.1', args.port), WorkspaceHandler)
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
