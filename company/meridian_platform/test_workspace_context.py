#!/usr/bin/env python3
import importlib.util
import os
import unittest
from unittest import mock
import types
from urllib.parse import urlparse


PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_PY = os.path.join(PLATFORM_DIR, 'workspace.py')


def _load_workspace(name):
    spec = importlib.util.spec_from_file_location(name, WORKSPACE_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class LiveWorkspaceContextTests(unittest.TestCase):
    def setUp(self):
        self.workspace = _load_workspace('live_workspace_context_test')
        self.orig_workspace_org_id = self.workspace.WORKSPACE_ORG_ID
        self.orig_runtime_host_identity_file = self.workspace.RUNTIME_HOST_IDENTITY_FILE
        self.orig_runtime_admission_file = self.workspace.RUNTIME_ADMISSION_FILE
        self.orig_federation_peers_file = self.workspace.FEDERATION_PEERS_FILE
        self.orig_federation_replay_file = self.workspace.FEDERATION_REPLAY_FILE
        self.orig_federation_signing_secret = self.workspace.FEDERATION_SIGNING_SECRET
        self.orig_get_founding_org = self.workspace._get_founding_org
        self.orig_load_orgs = self.workspace.load_orgs
        self.orig_load_workspace_credentials = self.workspace._load_workspace_credentials
        self.orig_load_host_identity = self.workspace.load_host_identity
        self.orig_load_admission_registry = self.workspace.load_admission_registry
        self.orig_runtime_host_state = self.workspace._runtime_host_state
        self.orig_federation_authority = self.workspace._federation_authority
        self.orig_log_event = self.workspace.log_event
        self.orig_list_warrants = self.workspace.list_warrants
        self.orig_get_warrant = self.workspace.get_warrant
        self.orig_issue_warrant = self.workspace.issue_warrant
        self.orig_review_warrant = self.workspace.review_warrant
        self.orig_commitment_summary = self.workspace.commitments.commitment_summary
        self.orig_list_commitments = self.workspace.commitments.list_commitments
        self.orig_validate_commitment_for_settlement = self.workspace.commitments.validate_commitment_for_settlement
        self.orig_record_settlement_ref = self.workspace.commitments.record_settlement_ref
        self.orig_settle_commitment = self.workspace.commitments.settle_commitment
        self.orig_case_summary = self.workspace.cases.case_summary
        self.orig_list_cases = self.workspace.cases.list_cases
        self.orig_blocking_commitment_ids = self.workspace.cases.blocking_commitment_ids
        self.orig_blocked_peer_host_ids = self.workspace.cases.blocked_peer_host_ids
        self.orig_maybe_block_commitment_settlement = self.workspace._maybe_block_commitment_settlement
        self.orig_ensure_case_for_delivery_failure = self.workspace.cases.ensure_case_for_delivery_failure
        self.orig_subscription_snapshot = self.workspace.service_state.subscription_snapshot
        self.orig_accounting_snapshot = self.workspace.service_state.accounting_snapshot
        self.orig_pilot_intake_snapshot = self.workspace.service_state.pilot_intake_snapshot
        self.orig_persistence_snapshot = self.workspace.status_surface.persistence_snapshot
        self.orig_observability_snapshot = self.workspace.status_surface.observability_snapshot
        self.orig_summarize_inbox_entries = self.workspace.summarize_inbox_entries
        self.orig_get_execution_job = self.workspace.get_execution_job
        self.orig_get_execution_job_by_local_warrant = self.workspace.get_execution_job_by_local_warrant
        self.orig_list_execution_jobs = self.workspace.list_execution_jobs
        self.orig_execution_job_summary = self.workspace.execution_job_summary
        self.orig_sync_execution_job_for_local_warrant = self.workspace.sync_execution_job_for_local_warrant
        self.orig_upsert_execution_job = self.workspace.upsert_execution_job
        self.workspace.status_surface.persistence_snapshot = lambda org_id=None: {
            'backend': 'file-backed-json-jsonl',
            'db': {'status': 'absent', 'reason': 'stubbed for unit tests'},
            'seams': [],
        }
        self.workspace.status_surface.observability_snapshot = lambda org_id=None: {
            'backend': 'file-backed-jsonl',
            'metrics': {
                'audit': {'total_events': 0},
                'metering': {'total_cost_usd': 0.0},
            },
            'slo': {'status': 'not_formalized'},
            'alert_queue': {
                'queue_count': 0,
                'pending_delivery_count': 0,
                'delivered_count': 0,
            },
        }

    def tearDown(self):
        self.workspace.WORKSPACE_ORG_ID = self.orig_workspace_org_id
        self.workspace.RUNTIME_HOST_IDENTITY_FILE = self.orig_runtime_host_identity_file
        self.workspace.RUNTIME_ADMISSION_FILE = self.orig_runtime_admission_file
        self.workspace.FEDERATION_PEERS_FILE = self.orig_federation_peers_file
        self.workspace.FEDERATION_REPLAY_FILE = self.orig_federation_replay_file
        self.workspace.FEDERATION_SIGNING_SECRET = self.orig_federation_signing_secret
        self.workspace._get_founding_org = self.orig_get_founding_org
        self.workspace.load_orgs = self.orig_load_orgs
        self.workspace._load_workspace_credentials = self.orig_load_workspace_credentials
        self.workspace.load_host_identity = self.orig_load_host_identity
        self.workspace.load_admission_registry = self.orig_load_admission_registry
        self.workspace._runtime_host_state = self.orig_runtime_host_state
        self.workspace._federation_authority = self.orig_federation_authority
        self.workspace.log_event = self.orig_log_event
        self.workspace.list_warrants = self.orig_list_warrants
        self.workspace.get_warrant = self.orig_get_warrant
        self.workspace.issue_warrant = self.orig_issue_warrant
        self.workspace.review_warrant = self.orig_review_warrant
        self.workspace.commitments.commitment_summary = self.orig_commitment_summary
        self.workspace.commitments.list_commitments = self.orig_list_commitments
        self.workspace.commitments.validate_commitment_for_settlement = self.orig_validate_commitment_for_settlement
        self.workspace.commitments.record_settlement_ref = self.orig_record_settlement_ref
        self.workspace.commitments.settle_commitment = self.orig_settle_commitment
        self.workspace.cases.case_summary = self.orig_case_summary
        self.workspace.cases.list_cases = self.orig_list_cases
        self.workspace.cases.blocking_commitment_ids = self.orig_blocking_commitment_ids
        self.workspace.cases.blocked_peer_host_ids = self.orig_blocked_peer_host_ids
        self.workspace._maybe_block_commitment_settlement = self.orig_maybe_block_commitment_settlement
        self.workspace.cases.ensure_case_for_delivery_failure = self.orig_ensure_case_for_delivery_failure
        self.workspace.service_state.subscription_snapshot = self.orig_subscription_snapshot
        self.workspace.service_state.accounting_snapshot = self.orig_accounting_snapshot
        self.workspace.service_state.pilot_intake_snapshot = self.orig_pilot_intake_snapshot
        self.workspace.status_surface.persistence_snapshot = self.orig_persistence_snapshot
        self.workspace.status_surface.observability_snapshot = self.orig_observability_snapshot
        self.workspace.summarize_inbox_entries = self.orig_summarize_inbox_entries
        self.workspace.get_execution_job = self.orig_get_execution_job
        self.workspace.get_execution_job_by_local_warrant = self.orig_get_execution_job_by_local_warrant
        self.workspace.list_execution_jobs = self.orig_list_execution_jobs
        self.workspace.execution_job_summary = self.orig_execution_job_summary
        self.workspace.sync_execution_job_for_local_warrant = self.orig_sync_execution_job_for_local_warrant
        self.workspace.upsert_execution_job = self.orig_upsert_execution_job

    def test_live_workspace_rejects_non_founding_configured_org(self):
        self.workspace._load_workspace_credentials = lambda: (None, None, None, None)
        self.workspace.WORKSPACE_ORG_ID = 'org_other'
        self.workspace._get_founding_org = lambda: ('org_founding', {'slug': 'meridian', 'name': 'Meridian'})
        with self.assertRaises(RuntimeError):
            self.workspace._resolve_workspace_context()

    def test_live_workspace_rejects_non_founding_credential_scope(self):
        self.workspace._load_workspace_credentials = lambda: ('owner', 'secret', 'org_other', None)
        self.workspace._get_founding_org = lambda: ('org_founding', {'slug': 'meridian', 'name': 'Meridian'})
        with self.assertRaises(RuntimeError):
            self.workspace._resolve_workspace_context()

    def test_request_override_must_match_bound_org(self):
        with self.assertRaises(ValueError):
            self.workspace._enforce_request_context(
                urlparse('/api/status?org_id=org_other'),
                _Headers(),
                'org_founding',
            )

        context = self.workspace._enforce_request_context(
            urlparse('/api/status?org_id=org_founding'),
            _Headers({'X-Meridian-Org-Id': 'org_founding'}),
            'org_founding',
        )
        self.assertEqual(context['requested_org_id'], 'org_founding')
        self.assertEqual(context['bound_org_id'], 'org_founding')

    def test_live_workspace_context_returns_institution_context(self):
        self.workspace._load_workspace_credentials = lambda: (None, None, None, None)
        self.workspace._get_founding_org = lambda: (
            'org_founding',
            {'id': 'org_founding', 'slug': 'meridian', 'name': 'Meridian', 'lifecycle_state': 'founding'},
        )
        ctx = self.workspace._resolve_workspace_context()
        self.assertEqual(ctx.org_id, 'org_founding')
        self.assertEqual(ctx.boundary.name, 'workspace')
        self.assertEqual(ctx.context_source, 'founding_default')

    def test_auth_context_reports_credential_binding(self):
        self.workspace._load_workspace_credentials = lambda: ('owner', 'secret', 'org_founding', None)
        auth = self.workspace._resolve_auth_context('org_founding')
        self.assertEqual(auth['mode'], 'credential_bound')
        self.assertEqual(auth['org_id'], 'org_founding')
        self.assertEqual(auth['actor_id'], 'workspace_user:owner')

    def test_auth_context_prefers_explicit_user_id(self):
        self.workspace._load_workspace_credentials = lambda: ('owner', 'secret', 'org_founding', 'user_meridian_owner')
        self.workspace.load_orgs = lambda: {
            'organizations': {
                'org_founding': {
                    'id': 'org_founding',
                    'slug': 'meridian',
                    'name': 'Meridian',
                    'owner_id': 'user_meridian_owner',
                    'members': [{'user_id': 'user_meridian_owner', 'role': 'owner'}],
                },
            }
        }
        auth = self.workspace._resolve_auth_context('org_founding')
        self.assertEqual(auth['actor_id'], 'user_meridian_owner')
        self.assertEqual(auth['actor_source'], 'credentials')
        self.assertEqual(auth['role'], 'owner')

    def test_auth_context_resolves_owner_alias_role(self):
        self.workspace._load_workspace_credentials = lambda: ('owner', 'secret', 'org_founding', None)
        self.workspace.load_orgs = lambda: {
            'organizations': {
                'org_founding': {
                    'id': 'org_founding',
                    'slug': 'meridian',
                    'name': 'Meridian',
                    'owner_id': 'user_meridian',
                    'members': [{'user_id': 'user_meridian', 'role': 'owner'}],
                },
            }
        }
        auth = self.workspace._resolve_auth_context('org_founding')
        self.assertEqual(auth['user_id'], 'user_meridian')
        self.assertEqual(auth['role'], 'owner')
        self.assertEqual(auth['actor_source'], 'owner_alias')

    def test_public_org_record_canonicalizes_meridian_owner_and_members(self):
        record = self.workspace._public_org_record({
            'id': 'org_founding',
            'name': 'Meridian',
            'owner_id': 'user_son_5322393870',
            'members': [
                {'user_id': 'user_son_5322393870', 'role': 'owner'},
                {'user_id': 'user_meridian_other', 'role': 'admin'},
            ],
        })
        self.assertEqual(record['owner_id'], 'user_meridian_5322393870')
        self.assertEqual(record['members'][0]['user_id'], 'user_meridian_5322393870')
        self.assertEqual(record['members'][1]['user_id'], 'user_meridian_other')

    def test_public_sprint_lead_resolves_agent_identity_fields(self):
        lead = self.workspace._public_sprint_lead(
            'atlas',
            100,
            reg={
                'agents': {
                    'agent_atlas': {
                        'id': 'agent_atlas',
                        'org_id': 'org_founding',
                        'name': 'Atlas',
                        'economy_key': 'atlas',
                        'authority_units': 65,
                        'reputation_units': 80,
                        'runtime_binding': {'runtime_id': 'loom_native'},
                    }
                }
            },
        )
        self.assertEqual(lead['agent_id'], 'agent_atlas')
        self.assertEqual(lead['economy_key'], 'atlas')
        self.assertEqual(lead['agent_name'], 'Atlas')
        self.assertEqual(lead['auth'], 100)
        self.assertEqual(lead['auth_source'], 'economy_sprint_lead')
        self.assertEqual(lead['registry_authority_units'], 65)
        self.assertEqual(lead['registry_reputation_units'], 80)
        self.assertEqual(lead['authority_alignment'], 'divergent')

    def test_mutation_authorization_requires_admin_for_kill_switch(self):
        auth = {'enabled': True, 'role': 'member'}
        with self.assertRaises(PermissionError):
            self.workspace._enforce_mutation_authorization(auth, 'org_founding', '/api/authority/kill-switch')

    def test_mutation_authorization_allows_member_request(self):
        auth = {'enabled': True, 'role': 'member'}
        required = self.workspace._enforce_mutation_authorization(auth, 'org_founding', '/api/authority/request')
        self.assertEqual(required, 'member')

    def test_permission_snapshot_tracks_allowed_paths(self):
        auth = {'enabled': True, 'role': 'admin'}
        permissions = self.workspace._permission_snapshot(auth)['mutation_paths']
        self.assertTrue(permissions['/api/authority/kill-switch']['allowed'])
        self.assertTrue(permissions['/api/institution/charter']['allowed'])
        self.assertFalse(permissions['/api/treasury/contribute']['allowed'])
        self.assertTrue(permissions['/api/warrants/issue']['allowed'])
        self.assertTrue(permissions['/api/warrants/approve']['allowed'])
        self.assertTrue(permissions['/api/payouts/propose']['allowed'])
        self.assertTrue(permissions['/api/payouts/submit']['allowed'])
        self.assertTrue(permissions['/api/payouts/review']['allowed'])
        self.assertFalse(permissions['/api/payouts/approve']['allowed'])
        self.assertTrue(permissions['/api/treasury/settlement-adapters/preflight']['allowed'])
        self.assertTrue(permissions['/api/federation/execution-jobs/execute']['allowed'])
        self.assertEqual(permissions['/api/federation/execution-jobs/execute']['required_role'], 'admin')
        self.assertTrue(permissions['/api/subscriptions/add']['allowed'])
        self.assertTrue(permissions['/api/subscriptions/draft-from-preview']['allowed'])
        self.assertTrue(permissions['/api/subscriptions/activate-from-preview']['allowed'])
        self.assertTrue(permissions['/api/subscriptions/loom-delivery-jobs/run']['allowed'])
        self.assertTrue(permissions['/api/subscriptions/convert']['allowed'])
        self.assertTrue(permissions['/api/subscriptions/verify-payment']['allowed'])
        self.assertTrue(permissions['/api/subscriptions/remove']['allowed'])
        self.assertTrue(permissions['/api/subscriptions/set-email']['allowed'])
        self.assertTrue(permissions['/api/subscriptions/record-delivery']['allowed'])
        self.assertFalse(permissions['/api/accounting/expense']['allowed'])
        self.assertEqual(permissions['/api/accounting/expense']['required_role'], 'owner')
        self.assertFalse(permissions['/api/accounting/reimburse']['allowed'])
        self.assertEqual(permissions['/api/accounting/reimburse']['required_role'], 'owner')
        self.assertFalse(permissions['/api/accounting/draw']['allowed'])
        self.assertEqual(permissions['/api/accounting/draw']['required_role'], 'owner')
        self.assertEqual(
            permissions['/api/treasury/settlement-adapters/preflight']['required_role'],
            'member',
        )
        self.assertEqual(permissions['/api/subscriptions/add']['required_role'], 'admin')
        self.assertEqual(permissions['/api/subscriptions/draft-from-preview']['required_role'], 'admin')
        self.assertEqual(permissions['/api/subscriptions/activate-from-preview']['required_role'], 'admin')
        self.assertEqual(permissions['/api/subscriptions/loom-delivery-jobs/run']['required_role'], 'admin')
        self.assertEqual(permissions['/api/subscriptions/convert']['required_role'], 'admin')
        self.assertEqual(permissions['/api/subscriptions/verify-payment']['required_role'], 'admin')
        self.assertEqual(permissions['/api/subscriptions/remove']['required_role'], 'admin')
        self.assertEqual(permissions['/api/payouts/execute']['required_role'], 'owner')
        self.assertTrue(permissions['/api/cases/open']['allowed'])
        self.assertTrue(permissions['/api/cases/resolve']['allowed'])
        self.assertTrue(permissions['/api/federation/send']['allowed'])
        self.assertFalse(permissions['/api/federation/peers/refresh']['allowed'])
        self.assertEqual(permissions['/api/federation/peers/refresh']['required_role'], 'owner')

    def test_payout_snapshot_surfaces_settlement_adapters(self):
        founding_org_id = self.workspace.WORKSPACE_ORG_ID or self.workspace._get_founding_org()[0]
        self.workspace.payout_proposal_summary = lambda org_id=None: {'total': 0, 'executed': 0}
        self.workspace.list_payout_proposals = lambda org_id=None: []
        self.workspace.load_payout_proposals = lambda org_id=None: {'state_machine': {'states': []}}
        self.workspace.list_settlement_adapters = lambda org_id=None: [
            {'adapter_id': 'internal_ledger', 'payout_execution_enabled': True},
            {'adapter_id': 'base_usdc_x402', 'payout_execution_enabled': False},
        ]
        self.workspace.settlement_adapter_summary = lambda org_id=None, host_supported_adapters=None: {
            'default_payout_adapter': 'internal_ledger',
            'host_supported_adapters': list(host_supported_adapters or []),
        }
        snapshot = self.workspace._payout_snapshot(
            founding_org_id,
            host_supported_adapters=['internal_ledger'],
        )
        self.assertEqual(snapshot['settlement_adapter_summary']['default_payout_adapter'], 'internal_ledger')
        self.assertEqual(snapshot['settlement_adapter_summary']['host_supported_adapters'], ['internal_ledger'])
        self.assertEqual(len(snapshot['settlement_adapters']), 2)

    def test_api_status_exposes_runtime_core(self):
        from runtime_host import default_host_identity
        self.workspace._load_workspace_credentials = lambda: ('owner', 'secret', 'org_founding', 'user_owner')
        self.workspace._get_founding_org = lambda: (
            'org_founding',
            {
                'id': 'org_founding',
                'slug': 'meridian',
                'name': 'Meridian',
                'owner_id': 'user_owner',
                'members': [{'user_id': 'user_owner', 'role': 'owner'}],
                'lifecycle_state': 'founding',
                'policy_defaults': {},
            },
        )
        self.workspace.load_registry = lambda: {
            'agents': {
                'agent_demo': {
                    'id': 'agent_demo',
                    'org_id': 'org_founding',
                    'name': 'Atlas',
                    'role': 'analyst',
                    'purpose': 'Research',
                    'reputation_units': 91,
                    'authority_units': 42,
                    'risk_state': 'nominal',
                    'lifecycle_state': 'active',
                    'economy_key': 'atlas',
                    'incident_count': 0,
                    'created_at': '2026-03-22T00:00:00Z',
                    'last_active_at': '2026-03-22T00:00:00Z',
                },
            },
        }
        self.workspace._load_queue = lambda org_id: {
            'kill_switch': False,
            'pending_approvals': {},
            'delegations': {},
        }
        self.workspace.treasury_snapshot = lambda org_id, **_kwargs: {}
        self.workspace._phase_mod.evaluate = lambda org_id: (0, {'name': 'Founder-Backed Build'})
        self.workspace._load_records = lambda org_id: {'violations': {}, 'appeals': {}}
        self.workspace.list_warrants = lambda org_id=None, **_kwargs: [
            {
                'warrant_id': 'war_live_demo',
                'court_review_state': 'approved',
                'execution_state': 'ready',
            }
        ]
        self.workspace.commitments.commitment_summary = lambda org_id=None: {
            'total': 1,
            'proposed': 0,
            'accepted': 1,
            'rejected': 0,
            'breached': 0,
            'settled': 0,
            'delivery_refs_total': 0,
        }
        self.workspace.commitments.list_commitments = lambda org_id=None: [
            {
                'commitment_id': 'com_live_demo',
                'status': 'accepted',
            }
        ]
        self.workspace.cases.case_summary = lambda org_id=None: {
            'total': 1,
            'open': 1,
            'stayed': 0,
            'resolved': 0,
        }
        self.workspace.cases.list_cases = lambda org_id=None: [
            {
                'case_id': 'case_live_demo',
                'status': 'open',
                'claim_type': 'breach_of_commitment',
            }
        ]
        self.workspace.get_restrictions = lambda agent_id, org_id=None: {'restrictions': []}
        self.workspace.service_state.subscription_snapshot = lambda org_id=None: {
            'bound_org_id': org_id,
            'mutation_enabled': True,
            'identity_model': 'session',
            'summary': {'subscriber_count': 1, 'external_target_count': 0},
        }
        self.workspace.service_state.subscription_preview_snapshot = lambda org_id=None: {
            'bound_org_id': org_id,
            'mutation_enabled': True,
            'identity_model': 'session',
            'summary': {'preview_count': 0, 'open_count': 0},
            'queue': [],
        }
        self.workspace.service_state.accounting_snapshot = lambda org_id=None: {
            'bound_org_id': org_id,
            'mutation_enabled': True,
            'identity_model': 'session',
            'summary': {'capital_contributed_usd': 2.0, 'unreimbursed_expenses_usd': 0.0},
        }
        self.workspace.get_sprint_lead = lambda org_id: ('', 0)
        self.workspace.get_pending_approvals = lambda org_id=None: []
        self.workspace._ci_vertical_status = lambda reg, lead_id, org_id: {}
        self.workspace.get_agent_remediation = lambda economy_key, reg, org_id=None: None
        self.workspace.capsule_dir = lambda org_id: f'/tmp/capsules/{org_id}'
        self.workspace.load_host_identity = lambda *args, **kwargs: default_host_identity(
            host_id='host_live',
            label='Meridian Live Host',
            supported_boundaries=['workspace', 'cli', 'mcp_service'],
        )
        self.workspace.load_admission_registry = lambda *args, **kwargs: {
            'source': 'derived_bound_default',
            'host_id': 'host_live',
            'institutions': {'org_founding': {'status': 'admitted'}},
            'admitted_org_ids': ['org_founding'],
        }
        fake_commitments = types.SimpleNamespace(
            commitment_summary=lambda org_id=None: {
                'total': 1,
                'open': 0,
                'proposed': 0,
                'accepted': 1,
                'rejected': 0,
                'breached': 0,
                'settled': 0,
                'delivery_refs_total': 0,
            },
            list_commitments=lambda org_id=None: [{
                'commitment_id': 'com_live_demo',
                'status': 'accepted',
                'target_host_id': 'host_live',
                'target_institution_id': 'org_founding',
                'summary': 'Demo commitment',
                'delivery_refs': [],
            }],
        )
        fake_cases = types.SimpleNamespace(
            case_summary=lambda org_id=None: {
                'total': 1,
                'open': 1,
                'stayed': 0,
                'resolved': 0,
            },
            blocking_commitment_ids=lambda org_id=None: ['com_live_demo'],
            list_cases=lambda org_id=None: [{
                'case_id': 'case_live_demo',
                'status': 'open',
                'claim_type': 'breach_of_commitment',
                'linked_commitment_id': 'com_live_demo',
            }],
            blocked_peer_host_ids=lambda org_id=None: ['host_peer'],
        )
        ctx = self.workspace._resolve_workspace_context()
        with mock.patch.object(self.workspace, 'commitments', fake_commitments), \
             mock.patch.object(self.workspace, 'cases', fake_cases), \
             mock.patch.object(self.workspace.service_state, 'pilot_intake_snapshot', return_value={
                 'bound_org_id': 'org_founding',
                 'management_mode': 'manual_pilot_intake',
                 'mutation_enabled': True,
                 'identity_model': 'public_submission',
                 'summary': {'total_requests': 0},
                 'request_paths': {
                     'submit': '/api/pilot/intake',
                     'inspect': '/api/pilot/intake',
                     'operator_inspect': '/api/pilot/intake/operator',
                 },
             }):
            status = self.workspace.api_status(institution_context=ctx)
        self.assertEqual(status['runtime_core']['institution_context']['org_id'], 'org_founding')
        self.assertFalse(status['runtime_core']['admission']['additional_institutions_allowed'])
        self.assertEqual(status['runtime_core']['admission']['management_mode'], 'founding_locked')
        self.assertFalse(status['runtime_core']['admission']['mutation_enabled'])
        self.assertTrue(status['runtime_core']['service_registry']['federation_gateway']['supports_institution_routing'])
        self.assertTrue(status['runtime_core']['service_registry']['federation_gateway']['requires_warrant'])
        self.assertEqual(
            status['runtime_core']['service_registry']['federation_gateway']['required_warrant_actions']['execution_request'],
            'federated_execution',
        )
        self.assertEqual(
            status['runtime_core']['service_registry']['federation_gateway']['required_warrant_actions']['commitment_proposal'],
            'cross_institution_commitment',
        )
        self.assertEqual(
            status['runtime_core']['service_registry']['federation_gateway']['required_warrant_actions']['commitment_acceptance'],
            'cross_institution_commitment',
        )
        self.assertEqual(
            status['runtime_core']['service_registry']['federation_gateway']['required_warrant_actions']['commitment_breach_notice'],
            'cross_institution_commitment',
        )
        self.assertNotIn(
            'case_notice',
            status['runtime_core']['service_registry']['federation_gateway']['required_warrant_actions'],
        )
        self.assertFalse(status['runtime_core']['service_registry']['mcp_service']['supports_institution_routing'])
        self.assertTrue(status['runtime_core']['service_registry']['subscriptions']['supports_institution_routing'])
        self.assertEqual(status['runtime_core']['service_registry']['subscriptions']['scope'], 'institution_bound')
        self.assertEqual(status['runtime_core']['service_registry']['subscriptions']['identity_model'], 'session')
        self.assertTrue(status['runtime_core']['service_registry']['accounting']['supports_institution_routing'])
        self.assertEqual(status['runtime_core']['service_registry']['accounting']['scope'], 'institution_bound')
        self.assertEqual(status['runtime_core']['service_registry']['accounting']['identity_model'], 'session')
        self.assertEqual(status['runtime_core']['host_identity']['host_id'], 'host_live')
        self.assertEqual(status['runtime_core']['admission']['admitted_org_ids'], ['org_founding'])
        self.assertEqual(status['runtime_core']['admission']['management_mode'], 'founding_locked')
        self.assertFalse(status['runtime_core']['admission']['mutation_enabled'])
        self.assertEqual(
            status['runtime_core']['admission']['mutation_disabled_reason'],
            'single_institution_deployment',
        )
        self.assertEqual(status['warrants']['total'], 1)
        self.assertEqual(status['warrants']['executable'], 1)
        self.assertIn('commitments', status)
        self.assertEqual(status['commitments']['total'], 1)
        self.assertEqual(status['commitments']['accepted'], 1)
        self.assertEqual(status['commitments']['management_mode'], 'founding_workspace_local')
        self.assertTrue(status['commitments']['mutation_enabled'])
        self.assertEqual(status['cases']['total'], 1)
        self.assertEqual(status['cases']['open'], 1)
        self.assertEqual(status['cases']['management_mode'], 'founding_workspace_local')
        self.assertEqual(status['cases']['blocking_commitment_ids'], ['com_live_demo'])
        self.assertEqual(status['cases']['blocked_peer_host_ids'], ['host_peer'])
        self.assertEqual(status['service_state']['subscriptions']['summary']['subscriber_count'], 1)
        self.assertTrue(status['service_state']['subscriptions']['mutation_enabled'])
        self.assertEqual(status['service_state']['subscriptions']['identity_model'], 'session')
        self.assertEqual(status['service_state']['accounting']['summary']['capital_contributed_usd'], 2.0)
        self.assertTrue(status['service_state']['accounting']['mutation_enabled'])
        self.assertIn('federation', status['runtime_core'])
        self.assertFalse(status['runtime_core']['federation']['enabled'])
        self.assertEqual(status['runtime_proof']['route'], '/api/runtime-proof')
        self.assertEqual(status['runtime_proof']['contract_version'], 'runtime_proof_contract_v1')
        self.assertNotEqual(status['runtime_proof']['runtime_proof_status'], '')
        self.assertNotEqual(status['runtime_proof']['channel_surface_status'], '')
        self.assertNotEqual(status['runtime_proof']['trust_ops_status'], '')
        self.assertNotEqual(status['runtime_proof']['proof_path'], '')
        self.assertEqual(status['runtime_proof']['runtime_id'], 'loom_native')
        self.assertEqual(status['slo']['status'], 'not_formalized')
        self.assertEqual(status['queue_count'], 0)
        self.assertEqual(status['pending_delivery_count'], 0)
        self.assertEqual(status['delivered_count'], 0)
        self.assertEqual(status['constitutional_model']['kernel']['count'], 5)
        self.assertEqual(status['constitutional_model']['platform']['count'], 6)
        self.assertEqual(status['constitutional_model']['runtime']['runtime_id'], 'loom_native')
        self.assertEqual(status['agents'][0]['runtime_binding']['runtime_id'], 'loom_native')
        self.assertEqual(status['agent_runtime_bindings'][0]['agent_id'], status['agents'][0]['id'])
        self.assertEqual(status['agent_runtime_bindings'][0]['agent_name'], status['agents'][0]['name'])
        self.assertEqual(status['agent_runtime_bindings'][0]['runtime_id'], 'loom_native')
        self.assertEqual(status['agent_runtime_bindings'][0]['boundary_name'], 'workspace')
        self.assertEqual(status['agent_runtime_bindings'][0]['boundary_scope'], 'institution_bound')
        self.assertEqual(status['agents'][0]['runtime_binding']['runtime_label'], 'Meridian Loom Runtime')
        self.assertEqual(status['agents'][0]['runtime_binding']['bound_org_id'], 'org_founding')
        self.assertEqual(status['agents'][0]['runtime_binding']['context_source'], 'agent_registry')
        self.assertEqual(status['agents'][0]['runtime_binding']['boundary_name'], 'workspace')
        self.assertEqual(status['agents'][0]['runtime_binding']['identity_model'], 'session')
        self.assertTrue(status['agents'][0]['runtime_binding']['runtime_registered'])
        self.assertEqual(status['agents'][0]['runtime_binding']['registration_status'], 'registered')


    def test_api_status_exposes_pilot_intake_queue(self):
        from runtime_host import default_host_identity
        self.workspace._load_workspace_credentials = lambda: ('owner', 'secret', 'org_founding', 'user_owner')
        self.workspace._get_founding_org = lambda: (
            'org_founding',
            {
                'id': 'org_founding',
                'slug': 'meridian',
                'name': 'Meridian',
                'owner_id': 'user_owner',
                'members': [{'user_id': 'user_owner', 'role': 'owner'}],
                'lifecycle_state': 'founding',
                'policy_defaults': {},
            },
        )
        self.workspace.load_registry = lambda: {'agents': {}}
        self.workspace._load_queue = lambda org_id: {
            'kill_switch': False,
            'pending_approvals': {},
            'delegations': {},
        }
        self.workspace.treasury_snapshot = lambda org_id, **_kwargs: {}
        self.workspace._phase_mod.evaluate = lambda org_id: (0, {'name': 'Founder-Backed Build'})
        self.workspace._load_records = lambda org_id: {'violations': {}, 'appeals': {}}
        self.workspace.list_warrants = lambda org_id=None, **_kwargs: []
        self.workspace.commitments.commitment_summary = lambda org_id=None: {'total': 0, 'proposed': 0, 'accepted': 0, 'rejected': 0, 'breached': 0, 'settled': 0, 'delivery_refs_total': 0}
        self.workspace.commitments.list_commitments = lambda org_id=None: []
        self.workspace.cases.case_summary = lambda org_id=None: {'total': 0, 'open': 0, 'stayed': 0, 'resolved': 0}
        self.workspace.cases.list_cases = lambda org_id=None: []
        self.workspace.service_state.subscription_snapshot = lambda org_id=None: {
            'bound_org_id': org_id,
            'mutation_enabled': True,
            'identity_model': 'session',
            'summary': {'subscriber_count': 0, 'external_target_count': 0},
        }
        self.workspace.service_state.subscription_preview_snapshot = lambda org_id=None: {
            'bound_org_id': org_id,
            'mutation_enabled': True,
            'identity_model': 'operator_review',
            'summary': {'total_previews': 1},
            'queue_paths': {
                'inspect': '/api/subscriptions/preview-queue',
                'source_review': '/api/pilot/intake/operator/review',
            },
        }
        self.workspace.service_state.accounting_snapshot = lambda org_id=None: {
            'bound_org_id': org_id,
            'mutation_enabled': True,
            'identity_model': 'session',
            'summary': {'capital_contributed_usd': 0.0, 'unreimbursed_expenses_usd': 0.0},
        }
        self.workspace.service_state.pilot_intake_snapshot = lambda org_id=None: {
            'bound_org_id': org_id,
            'management_mode': 'manual_pilot_intake',
            'mutation_enabled': True,
            'identity_model': 'public_submission',
            'summary': {'total_requests': 1, 'requested_count': 1},
            'request_paths': {
                'submit': '/api/pilot/intake',
                'inspect': '/api/pilot/intake',
                'operator_inspect': '/api/pilot/intake/operator',
                'operator_review': '/api/pilot/intake/operator/review',
            },
        }
        self.workspace.get_sprint_lead = lambda org_id: ('', 0)
        self.workspace.get_pending_approvals = lambda org_id=None: []
        self.workspace._ci_vertical_status = lambda reg, lead_id, org_id: {}
        self.workspace.get_agent_remediation = lambda economy_key, reg, org_id=None: None
        self.workspace.capsule_dir = lambda org_id: f'/tmp/capsules/{org_id}'
        self.workspace.load_host_identity = lambda *args, **kwargs: default_host_identity(
            host_id='host_live',
            label='Meridian Live Host',
            supported_boundaries=['workspace', 'cli', 'mcp_service'],
        )
        self.workspace.load_admission_registry = lambda *args, **kwargs: {
            'source': 'derived_bound_default',
            'host_id': 'host_live',
            'institutions': {'org_founding': {'status': 'admitted'}},
            'admitted_org_ids': ['org_founding'],
        }
        ctx = self.workspace._resolve_workspace_context()
        status = self.workspace.api_status(institution_context=ctx)
        self.assertIn('pilot_intake', status['service_state'])
        self.assertIn('subscription_preview', status['service_state'])
        self.assertEqual(status['service_state']['pilot_intake']['summary']['total_requests'], 1)
        self.assertEqual(status['service_state']['pilot_intake']['request_paths']['submit'], '/api/pilot/intake')
        self.assertEqual(status['service_state']['pilot_intake']['request_paths']['operator_inspect'], '/api/pilot/intake/operator')
        self.assertEqual(status['service_state']['subscription_preview']['summary']['total_previews'], 1)

    def test_public_pilot_intake_post_records_request_without_auth_gate(self):
        calls = []
        self.workspace._resolve_workspace_context = lambda **_: types.SimpleNamespace(org_id='org_founding', org={}, context_source='configured_org')

        class FakeHandler:
            def __init__(self):
                self.path = '/api/pilot/intake'
                self.headers = _Headers({'Content-Type': 'application/json'})
                self.response = None

            def _require_auth(self, path):
                calls.append(('require_auth', path))
                raise AssertionError('public intake route should not require auth')

            def _read_body(self):
                return {
                    'name': 'Jane Doe',
                    'company': 'Acme',
                    'email': 'jane@example.com',
                    'requested_cadence': 'Daily alert',
                    'competitors': 'OpenAI, Anthropic',
                    'topics': 'pricing, launches',
                    'notes': 'Need watchlist coverage',
                    'source_page': 'pilot.html',
                    'requested_offer': 'manual_pilot',
                }

            def _json(self, data, status=200):
                self.response = {'data': data, 'status': status}
                return self.response

            def _service_unavailable(self, message, is_api=False):
                raise AssertionError(message)

        with mock.patch.object(self.workspace.pilot_intake, 'submit_pilot_request', return_value={
            'request': {
                'request_id': 'pir_demo',
                'company': 'Acme',
                'contact_channel': 'email',
                'status': 'requested',
                'source_page': 'pilot.html',
            },
            'summary': {'total_requests': 1, 'requested_count': 1},
        }), mock.patch.object(self.workspace, 'log_event', return_value='evt_demo'):
            handler = FakeHandler()
            result = self.workspace.WorkspaceHandler.do_POST(handler)

        self.assertEqual(calls, [])
        self.assertEqual(handler.response['status'], 410)
        self.assertEqual(handler.response['data']['reason'], 'open_source_mode')
        self.assertIn('/pilot', handler.response['data']['message'])
        self.assertEqual(result, handler.response)

    def test_subscription_draft_from_preview_route_creates_status_surface(self):
        calls = []
        self.workspace._resolve_workspace_context = lambda **_: types.SimpleNamespace(org_id='org_founding', org={}, context_source='configured_org')

        class PostHandler:
            def __init__(self):
                self.path = '/api/subscriptions/draft-from-preview'
                self.headers = _Headers({'Content-Type': 'application/json'})
                self.response = None

            def _require_auth(self, path):
                calls.append(('require_auth', path))
                return True

            def _json(self, data, status=200):
                self.response = {'data': data, 'status': status}
                return self.response

            def _service_unavailable(self, message, is_api=False):
                raise AssertionError(message)

            def _session_claims_from_request(self, expected_org_id=None):
                return None

            def _read_body(self):
                return {'preview_id': 'quote_pir_demo'}

        with mock.patch.object(self.workspace.subscription_preview_queue, 'get_subscription_preview', return_value={
            'preview_id': 'quote_pir_demo',
            'pilot_request_id': 'pir_demo',
            'state': 'reviewed',
            'requested_offer': 'manual_pilot',
            'preview_truth_source': 'pilot_intake_review_and_published_plan_table_only',
        }), mock.patch.object(self.workspace.subscription_service, 'create_draft_subscription_from_preview', return_value={
            'preview_id': 'quote_pir_demo',
            'draft_subscription': {
                'draft_id': 'draft_quote_pir_demo',
                'preview_id': 'quote_pir_demo',
                'pilot_request_id': 'pir_demo',
                'status': 'draft',
            },
        }), mock.patch.object(self.workspace.subscription_preview_queue, 'mark_preview_drafted', return_value={
            'preview': {
                'preview_id': 'quote_pir_demo',
                'pilot_request_id': 'pir_demo',
                'draft_subscription_id': 'draft_quote_pir_demo',
                'draft_state': 'draft_created',
            },
            'summary': {'total_previews': 1, 'drafted_count': 1},
        }), mock.patch.object(self.workspace.service_state, 'subscription_snapshot', return_value={
            'bound_org_id': 'org_founding',
            'summary': {'subscriber_count': 0, 'draft_subscription_count': 1},
        }), mock.patch.object(self.workspace, 'log_event', return_value='evt_demo'), mock.patch.object(self.workspace, '_resolve_auth_context', return_value={
            'enabled': True,
            'mode': 'credential_bound',
            'org_id': 'org_founding',
            'user_id': 'user_owner',
            'role': 'owner',
            'actor_id': 'user_owner',
            'actor_source': 'test',
            'session_id': 'sid_demo',
        }):
            handler = PostHandler()
            result = self.workspace.WorkspaceHandler.do_POST(handler)
        self.assertEqual(calls, [('require_auth', '/api/subscriptions/draft-from-preview')])
        self.assertEqual(handler.response['status'], 200)
        self.assertEqual(handler.response['data']['result']['draft_subscription']['status'], 'draft')
        self.assertEqual(handler.response['data']['preview']['draft_subscription_id'], 'draft_quote_pir_demo')
        self.assertEqual(handler.response['data']['subscription_preview_summary']['drafted_count'], 1)
        self.assertEqual(result, handler.response)

    def test_subscription_activate_from_preview_route_queues_loom_delivery(self):
        calls = []
        self.workspace._resolve_workspace_context = lambda **_: types.SimpleNamespace(org_id='org_founding', org={}, context_source='configured_org')

        class PostHandler:
            def __init__(self):
                self.path = '/api/subscriptions/activate-from-preview'
                self.headers = _Headers({'Content-Type': 'application/json'})
                self.response = None

            def _require_auth(self, path):
                calls.append(('require_auth', path))
                return True

            def _json(self, data, status=200):
                self.response = {'data': data, 'status': status}
                return self.response

            def _service_unavailable(self, message, is_api=False):
                raise AssertionError(message)

            def _session_claims_from_request(self, expected_org_id=None):
                return None

            def _read_body(self):
                return {
                    'preview_id': 'quote_pir_demo',
                    'telegram_id': '800',
                    'plan': 'premium-brief-weekly',
                    'payment_ref': 'ref-activate',
                }

        with mock.patch.object(self.workspace.subscription_preview_queue, 'get_subscription_preview', return_value={
            'preview_id': 'quote_pir_demo',
            'pilot_request_id': 'pir_demo',
            'state': 'reviewed',
            'requested_offer': 'manual_pilot',
            'preview_truth_source': 'pilot_intake_review_and_published_plan_table_only',
            'telegram_handle': '800',
        }), mock.patch.object(self.workspace.subscription_service, 'activate_subscription_from_preview', return_value={
            'preview_id': 'quote_pir_demo',
            'telegram_id': '800',
            'subscription': {
                'id': 'sub_activated',
                'plan': 'premium-brief-weekly',
                'status': 'active',
                'payment_verified': True,
            },
            'delivery_job': {
                'job_id': 'loom_sub_activated',
                'preview_id': 'quote_pir_demo',
                'delivery_ref': 'loom-job-1',
            },
            'delivery_run': {
                'run_id': 'ldr_sub_activated',
                'job_id': 'loom_sub_activated',
                'state': 'executed',
                'delivery_status': 'delivered',
                'delivered': True,
                'delivery_ref': 'loom-job-1',
            },
            'delivery_execution': {'ok': True, 'job_id': 'loom-job-1'},
        }), mock.patch.object(self.workspace.subscription_preview_queue, 'mark_preview_activated', return_value={
            'preview': {
                'preview_id': 'quote_pir_demo',
                'pilot_request_id': 'pir_demo',
                'activated_subscription_id': 'sub_activated',
                'delivery_ref': 'loom-job-1',
                'delivery_state': 'delivered',
            },
            'summary': {'total_previews': 1, 'activated_count': 1, 'delivered_count': 1},
        }), mock.patch.object(self.workspace.subscription_preview_queue, 'mark_preview_delivered', return_value={
            'preview': {
                'preview_id': 'quote_pir_demo',
                'pilot_request_id': 'pir_demo',
                'activated_subscription_id': 'sub_activated',
                'delivery_ref': 'loom-job-1',
                'delivery_state': 'delivered',
            },
            'summary': {'total_previews': 1, 'activated_count': 1, 'delivered_count': 1},
        }), mock.patch.object(self.workspace.service_state, 'subscription_snapshot', return_value={
            'bound_org_id': 'org_founding',
            'summary': {'subscriber_count': 1, 'active_subscription_count': 1},
            'loom_delivery_queue_summary': {'total_jobs': 1, 'queued_count': 0, 'blocked_count': 0, 'completed_count': 1},
            'loom_delivery_run_summary': {'total_runs': 1, 'delivered_count': 1},
        }), mock.patch.object(self.workspace, 'log_event', return_value='evt_demo'), mock.patch.object(self.workspace, '_resolve_auth_context', return_value={
            'enabled': True,
            'mode': 'credential_bound',
            'org_id': 'org_founding',
            'user_id': 'user_owner',
            'role': 'owner',
            'actor_id': 'user_owner',
            'actor_source': 'test',
            'session_id': 'sid_demo',
        }):
            handler = PostHandler()
            result = self.workspace.WorkspaceHandler.do_POST(handler)
        self.assertEqual(calls, [('require_auth', '/api/subscriptions/activate-from-preview')])
        self.assertEqual(handler.response['status'], 200)
        self.assertEqual(handler.response['data']['result']['subscription']['status'], 'active')
        self.assertEqual(handler.response['data']['preview']['delivery_ref'], 'loom-job-1')
        self.assertEqual(handler.response['data']['subscription_preview_summary']['delivered_count'], 1)
        self.assertEqual(result, handler.response)

    def test_subscription_loom_delivery_run_route_advances_jobs(self):
        calls = []
        self.workspace._resolve_workspace_context = lambda **_: types.SimpleNamespace(org_id='org_founding', org={}, context_source='configured_org')

        class PostHandler:
            def __init__(self):
                self.path = '/api/subscriptions/loom-delivery-jobs/run'
                self.headers = _Headers({'Content-Type': 'application/json'})
                self.response = None

            def _require_auth(self, path):
                calls.append(('require_auth', path))
                return True

            def _json(self, data, status=200):
                self.response = {'data': data, 'status': status}
                return self.response

            def _service_unavailable(self, message, is_api=False):
                raise AssertionError(message)

            def _session_claims_from_request(self, expected_org_id=None):
                return None

            def _read_body(self):
                return {'job_id': 'loom_sub_activated', 'timeout': 5}

        with mock.patch.object(self.workspace.subscription_service, 'run_loom_delivery_job', return_value={
            'job_id': 'loom_sub_activated',
            'delivery_job': {'job_id': 'loom_sub_activated', 'state': 'executed', 'delivery_status': 'delivered'},
            'run': {'run_id': 'ldr_sub_activated', 'job_id': 'loom_sub_activated', 'state': 'executed', 'delivery_status': 'delivered', 'delivered': True},
            'execution': {'ok': True, 'job_id': 'loom-job-1'},
        }), mock.patch.object(self.workspace.service_state, 'subscription_snapshot', return_value={
            'bound_org_id': 'org_founding',
            'summary': {'subscriber_count': 1, 'active_subscription_count': 1},
            'loom_delivery_queue_summary': {'total_jobs': 1, 'queued_count': 0, 'blocked_count': 0, 'completed_count': 1},
            'loom_delivery_run_summary': {'total_runs': 1, 'delivered_count': 1},
        }), mock.patch.object(self.workspace, 'log_event', return_value='evt_demo'), mock.patch.object(self.workspace, '_resolve_auth_context', return_value={
            'enabled': True,
            'mode': 'credential_bound',
            'org_id': 'org_founding',
            'user_id': 'user_owner',
            'role': 'owner',
            'actor_id': 'user_owner',
            'actor_source': 'test',
            'session_id': 'sid_demo',
        }):
            handler = PostHandler()
            result = self.workspace.WorkspaceHandler.do_POST(handler)
        self.assertEqual(calls, [('require_auth', '/api/subscriptions/loom-delivery-jobs/run')])
        self.assertEqual(handler.response['status'], 200)
        self.assertEqual(handler.response['data']['result']['run']['state'], 'executed')
        self.assertEqual(result, handler.response)

    def test_public_subscription_checkout_capture_route_uses_explicit_payment_evidence(self):
        calls = []
        self.workspace._resolve_workspace_context = lambda **_: types.SimpleNamespace(org_id='org_founding', org={}, context_source='configured_org')

        class PostHandler:
            def __init__(self):
                self.path = '/api/subscriptions/checkout-capture'
                self.headers = _Headers({'Content-Type': 'application/json'})
                self.response = None

            def _require_auth(self, path):
                calls.append(('require_auth', path))
                return True

            def _json(self, data, status=200):
                self.response = {'data': data, 'status': status}
                return self.response

            def _service_unavailable(self, message, is_api=False):
                raise AssertionError(message)

            def _session_claims_from_request(self, expected_org_id=None):
                return None

            def _read_body(self):
                return {
                    'draft_id': 'draft_quote_pir_demo'
                    , 'preview_id': 'quote_pir_demo',
                    'telegram_id': '800',
                    'plan': 'premium-brief-weekly',
                    'payment_ref': 'ref-checkout',
                    'payment_evidence': {
                        'order_id': 'ord-checkout',
                        'payment_key': 'ref:ref-checkout',
                        'payment_ref': 'ref-checkout',
                        'tx_hash': '0xcheckout',
                        'amount_usd': 2.99,
                    },
                }

        with mock.patch.object(self.workspace.subscription_service, 'load_subscriptions', return_value={
            'draft_subscriptions': {
                'draft_quote_pir_demo': {
                    'draft_id': 'draft_quote_pir_demo',
                    'preview_id': 'quote_pir_demo',
                    'telegram_id': '800',
                    'plan': 'premium-brief-weekly',
                },
            },
        }), mock.patch.object(self.workspace.subscription_preview_queue, 'get_subscription_preview', return_value={
            'preview_id': 'quote_pir_demo',
            'pilot_request_id': 'pir_demo',
            'state': 'reviewed',
            'requested_offer': 'manual_pilot',
            'preview_truth_source': 'pilot_intake_review_and_published_plan_table_only',
            'telegram_handle': '800',
        }), mock.patch.object(self.workspace.subscription_service, 'capture_subscription_from_preview', return_value={
            'preview_id': 'quote_pir_demo',
            'telegram_id': '800',
            'subscription': {
                'id': 'sub_checkout',
                'plan': 'premium-brief-weekly',
                'status': 'active',
                'payment_verified': True,
                'payment_ref': 'ref-checkout',
            },
            'delivery_job': {
                'job_id': 'loom_sub_checkout',
                'preview_id': 'quote_pir_demo',
                'delivery_ref': 'loom-job-checkout',
            },
            'delivery_run': {
                'run_id': 'ldr_sub_checkout',
                'job_id': 'loom_sub_checkout',
                'state': 'executed',
                'delivery_status': 'delivered',
                'delivered': True,
                'delivery_ref': 'loom-job-checkout',
            },
            'delivery_execution': {'ok': True, 'job_id': 'loom-job-checkout'},
        }), mock.patch.object(self.workspace.subscription_preview_queue, 'mark_preview_delivered', return_value={
            'preview': {
                'preview_id': 'quote_pir_demo',
                'pilot_request_id': 'pir_demo',
                'activated_subscription_id': 'sub_checkout',
                'delivery_ref': 'loom-job-checkout',
                'delivery_state': 'delivered',
            },
            'summary': {'total_previews': 1, 'activated_count': 1, 'delivered_count': 1},
        }), mock.patch.object(self.workspace.subscription_preview_queue, 'mark_preview_activated', return_value={
            'preview': {
                'preview_id': 'quote_pir_demo',
                'pilot_request_id': 'pir_demo',
                'activated_subscription_id': 'sub_checkout',
                'delivery_state': 'captured',
            },
            'summary': {'total_previews': 1, 'activated_count': 1, 'delivered_count': 0},
        }), mock.patch.object(self.workspace.service_state, 'subscription_snapshot', return_value={
            'bound_org_id': 'org_founding',
            'summary': {'subscriber_count': 1, 'active_subscription_count': 1},
            'loom_delivery_queue_summary': {'total_jobs': 1, 'queued_count': 0, 'blocked_count': 0, 'completed_count': 1},
            'loom_delivery_run_summary': {'total_runs': 1, 'delivered_count': 1},
        }), mock.patch.object(self.workspace, 'log_event', return_value='evt_demo'), mock.patch.object(self.workspace, '_resolve_auth_context', return_value={
            'enabled': True,
            'mode': 'credential_bound',
            'org_id': 'org_founding',
            'user_id': 'user_owner',
            'role': 'owner',
            'actor_id': 'user_owner',
            'actor_source': 'test',
            'session_id': 'sid_demo',
        }):
            handler = PostHandler()
            result = self.workspace.WorkspaceHandler.do_POST(handler)
        self.assertEqual(calls, [])
        self.assertEqual(handler.response['status'], 410)
        self.assertEqual(handler.response['data']['reason'], 'open_source_mode')
        self.assertIn('deprecated', handler.response['data']['status'])
        self.assertEqual(result, handler.response)

    def test_public_subscription_checkout_capture_route_only_marks_preview_delivered_after_dispatch(self):
        calls = []
        self.workspace._resolve_workspace_context = lambda **_: types.SimpleNamespace(org_id='org_founding', org={}, context_source='configured_org')

        class PostHandler:
            def __init__(self):
                self.path = '/api/subscriptions/checkout-capture'
                self.headers = _Headers({'Content-Type': 'application/json'})
                self.response = None

            def _require_auth(self, path):
                calls.append(('require_auth', path))
                return True

            def _json(self, data, status=200):
                self.response = {'data': data, 'status': status}
                return self.response

            def _service_unavailable(self, message, is_api=False):
                raise AssertionError(message)

            def _session_claims_from_request(self, expected_org_id=None):
                return None

            def _read_body(self):
                return {
                    'draft_id': 'draft_quote_pir_demo',
                    'preview_id': 'quote_pir_demo',
                    'telegram_id': '800',
                    'plan': 'premium-brief-weekly',
                    'payment_ref': 'ref-checkout',
                    'payment_evidence': {
                        'order_id': 'ord-checkout',
                        'payment_key': 'ref:ref-checkout',
                        'payment_ref': 'ref-checkout',
                        'tx_hash': '0xcheckout',
                        'amount_usd': 2.99,
                    },
                }

        mark_preview_delivered = mock.Mock(return_value={
            'preview': {
                'preview_id': 'quote_pir_demo',
                'pilot_request_id': 'pir_demo',
                'activated_subscription_id': 'sub_checkout',
                'delivery_ref': 'loom-job-checkout',
                'delivery_state': 'delivered',
            },
            'summary': {'total_previews': 1, 'activated_count': 1, 'delivered_count': 1},
        })
        mark_preview_activated = mock.Mock(return_value={
            'preview': {
                'preview_id': 'quote_pir_demo',
                'pilot_request_id': 'pir_demo',
                'activated_subscription_id': 'sub_checkout',
                'delivery_state': 'captured',
            },
            'summary': {'total_previews': 1, 'activated_count': 1, 'delivered_count': 0},
        })

        with mock.patch.object(self.workspace.subscription_service, 'load_subscriptions', return_value={
            'draft_subscriptions': {
                'draft_quote_pir_demo': {
                    'draft_id': 'draft_quote_pir_demo',
                    'preview_id': 'quote_pir_demo',
                    'telegram_id': '800',
                    'plan': 'premium-brief-weekly',
                },
            },
        }), mock.patch.object(self.workspace.subscription_preview_queue, 'get_subscription_preview', return_value={
            'preview_id': 'quote_pir_demo',
            'pilot_request_id': 'pir_demo',
            'state': 'reviewed',
            'requested_offer': 'manual_pilot',
            'preview_truth_source': 'pilot_intake_review_and_published_plan_table_only',
            'telegram_handle': '800',
        }), mock.patch.object(self.workspace.subscription_service, 'capture_subscription_from_preview', return_value={
            'preview_id': 'quote_pir_demo',
            'telegram_id': '800',
            'subscription': {
                'id': 'sub_checkout',
                'plan': 'premium-brief-weekly',
                'status': 'active',
                'payment_verified': True,
                'payment_ref': 'ref-checkout',
            },
            'delivery_job': {
                'job_id': 'loom_sub_checkout',
                'preview_id': 'quote_pir_demo',
                'delivery_ref': 'loom-job-checkout',
            },
            'delivery_run': {
                'run_id': 'ldr_sub_checkout',
                'job_id': 'loom_sub_checkout',
                'state': 'executed',
                'delivery_status': 'artifact_ready',
                'delivered': False,
                'delivery_ref': 'loom-job-checkout',
            },
            'delivery_execution': {'ok': True, 'job_id': 'loom-job-checkout'},
            'delivery_artifact': {'brief_preview': 'brief queued for later retrieval'},
        }), mock.patch.object(self.workspace.subscription_preview_queue, 'mark_preview_delivered', mark_preview_delivered), mock.patch.object(self.workspace.subscription_preview_queue, 'mark_preview_activated', mark_preview_activated), mock.patch.object(self.workspace.service_state, 'subscription_snapshot', return_value={
            'bound_org_id': 'org_founding',
            'summary': {'subscriber_count': 1, 'active_subscription_count': 1},
            'loom_delivery_queue_summary': {'total_jobs': 1, 'queued_count': 0, 'blocked_count': 1, 'completed_count': 0},
            'loom_delivery_run_summary': {'total_runs': 1, 'delivered_count': 0},
        }), mock.patch.object(self.workspace, 'log_event', return_value='evt_demo'), mock.patch.object(self.workspace, '_resolve_auth_context', return_value={
            'enabled': True,
            'mode': 'credential_bound',
            'org_id': 'org_founding',
            'user_id': 'user_owner',
            'role': 'owner',
            'actor_id': 'user_owner',
            'actor_source': 'test',
            'session_id': 'sid_demo',
        }):
            handler = PostHandler()
            result = self.workspace.WorkspaceHandler.do_POST(handler)
        self.assertEqual(calls, [])
        self.assertEqual(handler.response['status'], 410)
        self.assertEqual(handler.response['data']['reason'], 'open_source_mode')
        self.assertFalse(mark_preview_delivered.called)
        self.assertFalse(mark_preview_activated.called)
        self.assertEqual(result, handler.response)

    def test_operator_pilot_intake_routes_expose_review_only_flow(self):
        calls = []
        self.workspace._resolve_workspace_context = lambda **_: types.SimpleNamespace(org_id='org_founding', org={}, context_source='configured_org')

        class GetHandler:
            def __init__(self):
                self.path = '/api/pilot/intake/operator'
                self.headers = _Headers({'Content-Type': 'application/json'})
                self.response = None

            def _require_auth(self, path):
                calls.append(('require_auth', path))
                return True

            def _json(self, data, status=200):
                self.response = {'data': data, 'status': status}
                return self.response

            def _service_unavailable(self, message, is_api=False):
                raise AssertionError(message)

            def _session_claims_from_request(self, expected_org_id=None):
                return None

        with mock.patch.object(self.workspace.pilot_intake, 'operator_review_snapshot', return_value={
            'management_mode': 'manual_operator_review',
            'operator_review': {'review_mode': 'manual_ack_only'},
            'summary': {'total_requests': 1},
        }), mock.patch.object(self.workspace, '_resolve_auth_context', return_value={
            'enabled': True,
            'mode': 'credential_bound',
            'org_id': 'org_founding',
            'user_id': 'user_owner',
            'role': 'owner',
            'actor_id': 'user_owner',
            'actor_source': 'test',
            'session_id': 'sid_demo',
        }):
            handler = GetHandler()
            result = self.workspace.WorkspaceHandler.do_GET(handler)
        self.assertEqual(calls, [('require_auth', '/api/pilot/intake/operator')])
        self.assertEqual(handler.response['status'], 200)
        self.assertEqual(handler.response['data']['management_mode'], 'manual_operator_review')
        self.assertEqual(result, handler.response)

        post_calls = []

        class PostHandler:
            def __init__(self):
                self.path = '/api/pilot/intake/operator/review'
                self.headers = _Headers({'Content-Type': 'application/json'})
                self.response = None

            def _require_auth(self, path):
                post_calls.append(('require_auth', path))
                return True

            def _json(self, data, status=200):
                self.response = {'data': data, 'status': status}
                return self.response

            def _service_unavailable(self, message, is_api=False):
                raise AssertionError(message)

            def _session_claims_from_request(self, expected_org_id=None):
                return None

            def _read_body(self):
                return {'request_id': 'pir_demo', 'note': 'Reviewed'}

        with mock.patch.object(self.workspace.pilot_intake, 'acknowledge_pilot_request', return_value={
            'request': {
                'request_id': 'pir_demo',
                'status': 'reviewed',
                'review_state': 'acknowledged',
                'reviewed_by': 'user_owner',
            },
            'summary': {'total_requests': 1, 'reviewed_count': 1, 'acknowledged_count': 1},
        }), mock.patch.object(self.workspace.subscription_preview_queue, 'queue_subscription_preview', return_value={
            'preview': {
                'preview_id': 'quote_pir_demo',
                'pilot_request_id': 'pir_demo',
                'state': 'reviewed',
            },
            'summary': {'total_previews': 1, 'reviewed_count': 1},
        }), mock.patch.object(self.workspace.pilot_intake, 'operator_review_snapshot', return_value={
            'operator_review': {'review_mode': 'manual_ack_only', 'acknowledged_count': 1},
        }), mock.patch.object(self.workspace, 'log_event', return_value='evt_demo'), mock.patch.object(self.workspace, '_resolve_auth_context', return_value={
            'enabled': True,
            'mode': 'credential_bound',
            'org_id': 'org_founding',
            'user_id': 'user_owner',
            'role': 'owner',
            'actor_id': 'user_owner',
            'actor_source': 'test',
            'session_id': 'sid_demo',
        }):
            handler = PostHandler()
            result = self.workspace.WorkspaceHandler.do_POST(handler)
        self.assertEqual(post_calls, [('require_auth', '/api/pilot/intake/operator/review')])
        self.assertEqual(handler.response['status'], 200)
        self.assertEqual(handler.response['data']['request']['review_state'], 'acknowledged')
        self.assertEqual(handler.response['data']['subscription_preview']['preview_id'], 'quote_pir_demo')
        self.assertEqual(result, handler.response)

    def test_api_status_reports_witness_read_only_host_management(self):
        from runtime_host import default_host_identity

        self.workspace._load_workspace_credentials = lambda: ('owner', 'secret', 'org_founding', 'user_owner')
        self.workspace._get_founding_org = lambda: (
            'org_founding',
            {
                'id': 'org_founding',
                'slug': 'meridian',
                'name': 'Meridian',
                'owner_id': 'user_owner',
                'members': [{'user_id': 'user_owner', 'role': 'owner'}],
                'lifecycle_state': 'founding',
                'policy_defaults': {},
            },
        )
        self.workspace.load_registry = lambda: {'agents': {}}
        self.workspace._load_queue = lambda org_id: {
            'kill_switch': False,
            'pending_approvals': {},
            'delegations': {},
        }
        self.workspace.treasury_snapshot = lambda org_id, **_kwargs: {}
        self.workspace._phase_mod.evaluate = lambda org_id: (0, {'name': 'Founder-Backed Build'})
        self.workspace._load_records = lambda org_id: {'violations': {}, 'appeals': {}}
        self.workspace.list_warrants = lambda org_id=None, **_kwargs: []
        self.workspace.commitments.commitment_summary = lambda org_id=None: {'total': 0, 'proposed': 0, 'accepted': 0, 'rejected': 0, 'breached': 0, 'settled': 0, 'delivery_refs_total': 0}
        self.workspace.commitments.list_commitments = lambda org_id=None: []
        self.workspace.cases.case_summary = lambda org_id=None: {'total': 0, 'open': 0, 'stayed': 0, 'resolved': 0}
        self.workspace.cases.list_cases = lambda org_id=None: []
        self.workspace.service_state.subscription_snapshot = lambda org_id=None: {
            'bound_org_id': org_id,
            'mutation_enabled': True,
            'identity_model': 'session',
            'summary': {'subscriber_count': 0, 'external_target_count': 0},
        }
        self.workspace.service_state.accounting_snapshot = lambda org_id=None: {
            'bound_org_id': org_id,
            'mutation_enabled': True,
            'identity_model': 'session',
            'summary': {'capital_contributed_usd': 0.0, 'unreimbursed_expenses_usd': 0.0},
        }
        self.workspace.get_sprint_lead = lambda org_id: ('', 0)
        self.workspace.get_pending_approvals = lambda org_id=None: []
        self.workspace._ci_vertical_status = lambda reg, lead_id, org_id: {}
        self.workspace.get_agent_remediation = lambda economy_key, reg, org_id=None: None
        self.workspace.capsule_dir = lambda org_id: f'/tmp/capsules/{org_id}'
        self.workspace.load_host_identity = lambda *args, **kwargs: default_host_identity(
            host_id='host_live',
            label='Meridian Live Host',
            role='witness_host',
            federation_enabled=False,
            supported_boundaries=['workspace', 'cli', 'federation_gateway'],
        )
        self.workspace.load_admission_registry = lambda *args, **kwargs: {
            'source': 'derived_bound_default',
            'host_id': 'host_live',
            'institutions': {'org_founding': {'status': 'admitted'}},
            'admitted_org_ids': ['org_founding'],
        }

        ctx = self.workspace._resolve_workspace_context()
        with mock.patch.object(self.workspace.service_state, 'pilot_intake_snapshot', return_value={
            'bound_org_id': 'org_founding',
            'management_mode': 'manual_pilot_intake',
            'mutation_enabled': True,
            'identity_model': 'public_submission',
            'summary': {'total_requests': 0},
            'request_paths': {
                'submit': '/api/pilot/intake',
                'inspect': '/api/pilot/intake',
                'operator_inspect': '/api/pilot/intake/operator',
            },
        }):
            status = self.workspace.api_status(institution_context=ctx)

        self.assertEqual(status['runtime_core']['host_identity']['role'], 'witness_host')
        self.assertEqual(status['runtime_core']['admission']['management_mode'], 'witness_read_only')
        self.assertFalse(status['runtime_core']['admission']['mutation_enabled'])
        self.assertEqual(status['runtime_core']['admission']['mutation_disabled_reason'], 'witness_host_read_only')
        self.assertEqual(status['runtime_core']['federation']['management_mode'], 'witness_read_only')
        self.assertFalse(status['runtime_core']['federation']['mutation_enabled'])
        self.assertEqual(status['runtime_core']['federation']['mutation_disabled_reason'], 'witness_host_read_only')

    def test_admission_snapshot_reports_founding_lock(self):
        from runtime_host import default_host_identity

        snapshot = self.workspace._admission_snapshot(
            'org_founding',
            host_identity=default_host_identity(
                host_id='host_live',
                label='Meridian Live Host',
                role='institution_host',
            ),
            admission_registry={
                'source': 'derived_bound_default',
                'host_id': 'host_live',
                'institutions': {'org_founding': {'status': 'admitted'}},
                'admitted_org_ids': ['org_founding'],
            },
        )
        self.assertEqual(snapshot['management_mode'], 'founding_locked')
        self.assertFalse(snapshot['mutation_enabled'])
        self.assertEqual(snapshot['institutions']['org_founding']['status'], 'admitted')

    def test_admission_snapshot_reports_witness_read_only(self):
        from runtime_host import default_host_identity

        snapshot = self.workspace._admission_snapshot(
            'org_founding',
            host_identity=default_host_identity(
                host_id='host_live',
                label='Meridian Live Host',
                role='witness_host',
                federation_enabled=False,
                supported_boundaries=['workspace', 'cli', 'federation_gateway'],
            ),
            admission_registry={
                'source': 'derived_bound_default',
                'host_id': 'host_live',
                'institutions': {'org_founding': {'status': 'admitted'}},
                'admitted_org_ids': ['org_founding'],
            },
        )
        self.assertEqual(snapshot['management_mode'], 'witness_read_only')
        self.assertFalse(snapshot['mutation_enabled'])
        self.assertEqual(snapshot['mutation_disabled_reason'], 'witness_host_read_only')

    def test_mutate_admission_fails_closed_for_live_runtime(self):
        with self.assertRaises(PermissionError):
            self.workspace._mutate_admission('org_founding', 'admit', 'org_demo_peer')

    def test_federation_snapshot_reports_disabled_live_host(self):
        from runtime_host import default_host_identity
        host = default_host_identity(
            host_id='host_live',
            label='Meridian Live Host',
            federation_enabled=False,
            supported_boundaries=['workspace', 'cli', 'federation_gateway'],
        )
        snap = self.workspace._federation_snapshot(
            'org_founding',
            host_identity=host,
            admission_registry={'admitted_org_ids': ['org_founding']},
        )
        self.assertFalse(snap['enabled'])
        self.assertFalse(snap['send_enabled'])
        self.assertEqual(snap['disabled_reason'], 'host_federation_disabled')
        self.assertEqual(snap['management_mode'], 'founding_locked')
        self.assertFalse(snap['mutation_enabled'])

    def test_federation_snapshot_reports_witness_read_only(self):
        from runtime_host import default_host_identity
        snap = self.workspace._federation_snapshot(
            'org_founding',
            host_identity=default_host_identity(
                host_id='host_live',
                label='Meridian Live Host',
                role='witness_host',
                federation_enabled=False,
                supported_boundaries=['workspace', 'cli', 'federation_gateway'],
            ),
            admission_registry={'admitted_org_ids': ['org_founding']},
        )
        self.assertFalse(snap['enabled'])
        self.assertFalse(snap['send_enabled'])
        self.assertEqual(snap['management_mode'], 'witness_read_only')
        self.assertFalse(snap['mutation_enabled'])
        self.assertEqual(snap['mutation_disabled_reason'], 'witness_host_read_only')
        self.assertIn('witness_archive', snap)
        self.assertTrue(snap['witness_archive']['archive_enabled'])
        self.assertEqual(snap['witness_archive']['management_mode'], 'witness_local_archive')

    def test_federation_snapshot_surfaces_inbox_summary(self):
        from runtime_host import default_host_identity
        self.workspace.summarize_inbox_entries = lambda org_id: {
            'org_id': org_id,
            'total': 1,
            'received': 1,
            'processed': 0,
            'message_type_counts': {'execution_request': 1},
            'state_counts': {'received': 1},
            'updatedAt': '2026-03-22T00:00:00Z',
        }
        host = default_host_identity(
            host_id='host_live',
            label='Meridian Live Host',
            federation_enabled=False,
            supported_boundaries=['workspace', 'cli', 'federation_gateway'],
        )
        snap = self.workspace._federation_snapshot(
            'org_founding',
            host_identity=host,
            admission_registry={'admitted_org_ids': ['org_founding']},
        )
        self.assertEqual(snap['inbox_summary']['total'], 1)
        self.assertEqual(
            snap['inbox_summary']['message_type_counts']['execution_request'],
            1,
        )

    def test_federation_execution_jobs_snapshot_surfaces_local_warrant(self):
        self.workspace.list_execution_jobs = lambda org_id, state=None: [
            {
                'job_id': 'fej_demo',
                'envelope_id': 'fed_exec_demo',
                'receipt_id': 'fedrcpt_demo',
                'state': 'pending_local_warrant',
                'local_warrant_id': 'war_local_demo',
                'message_type': 'execution_request',
                'received_at': '2026-03-22T00:00:00Z',
                'source_host_id': 'host_alpha',
                'source_institution_id': 'org_alpha',
                'target_host_id': 'host_live',
                'target_institution_id': 'org_founding',
                'boundary_name': 'federation_gateway',
                'identity_model': 'signed_host_service',
                'payload': {'task': 'demo'},
                'payload_hash': 'hash_demo',
            }
        ]
        self.workspace.execution_job_summary = lambda org_id: {
            'org_id': org_id,
            'total': 1,
            'pending_local_warrant': 1,
            'ready': 0,
            'executed': 0,
            'blocked': 0,
            'rejected': 0,
            'state_counts': {'pending_local_warrant': 1},
            'message_type_counts': {'execution_request': 1},
            'updatedAt': '2026-03-22T00:00:00Z',
        }
        self.workspace.get_warrant = lambda warrant_id, org_id=None: {
            'warrant_id': warrant_id,
            'court_review_state': 'pending_review',
            'execution_state': 'ready',
            'expires_at': '2026-03-22T01:00:00Z',
        }
        snapshot = self.workspace._federation_execution_jobs_snapshot('org_founding')
        self.assertFalse(snapshot['mutation_enabled'])
        self.assertEqual(snapshot['mutation_disabled_reason'], 'review_via_warrants')
        self.assertEqual(snapshot['summary']['total'], 1)
        self.assertEqual(snapshot['summary']['pending_local_warrant'], 1)
        self.assertEqual(snapshot['jobs'][0]['envelope_id'], 'fed_exec_demo')
        self.assertEqual(snapshot['jobs'][0]['state'], 'pending_local_warrant')
        self.assertEqual(snapshot['jobs'][0]['local_warrant']['warrant_id'], 'war_local_demo')
        self.assertEqual(snapshot['jobs'][0]['local_warrant']['court_review_state'], 'pending_review')
        self.assertEqual(snapshot['jobs'][0]['local_warrant']['execution_state'], 'ready')

    def test_reject_live_execution_job_completion_reports_review_only_boundary(self):
        result = self.workspace._reject_live_execution_job_completion('org_founding')
        self.assertEqual(result['management_mode'], 'founding_locked')
        self.assertFalse(result['mutation_enabled'])
        self.assertFalse(result['state_change'])
        self.assertEqual(result['boundary_name'], 'federation_gateway')
        self.assertEqual(result['identity_model'], 'signed_host_service')
        self.assertEqual(result['mutation_disabled_reason'], 'single_institution_deployment')
        self.assertIn('review-only', result['error'])
        self.assertFalse(result['execution_jobs']['mutation_enabled'])

    def test_federation_execution_jobs_execute_fails_closed_without_state_change(self):
        calls = []

        class FakeHandler:
            def __init__(self):
                self.path = '/api/federation/execution-jobs/execute'
                self.headers = _Headers()
                self.response = None
                self.body_read = False

            def _require_auth(self, path):
                calls.append(('require_auth', path))
                return True

            def _resolve_workspace_context(self):
                raise AssertionError('route should fail closed before resolving workspace context')

            def _enforce_request_context(self, *args, **kwargs):
                raise AssertionError('route should fail closed before request-context enforcement')

            def _resolve_auth_context(self, *args, **kwargs):
                raise AssertionError('route should fail closed before auth-context resolution')

            def _enforce_mutation_authorization(self, *args, **kwargs):
                raise AssertionError('route should fail closed before mutation authorization')

            def _read_body(self):
                self.body_read = True
                raise AssertionError('route should fail closed before body parsing')

            def _json(self, data, status=200):
                self.response = {'data': data, 'status': status}
                return self.response

        handler = FakeHandler()
        result = self.workspace.WorkspaceHandler.do_POST(handler)

        self.assertEqual(calls, [('require_auth', '/api/federation/execution-jobs/execute')])
        self.assertEqual(handler.response['status'], 503)
        self.assertEqual(handler.response['data']['route'], '/api/federation/execution-jobs/execute')
        self.assertEqual(handler.response['data']['management_mode'], 'founding_locked')
        self.assertFalse(handler.response['data']['mutation_enabled'])
        self.assertFalse(handler.response['data']['state_change'])
        self.assertFalse(handler.body_read)
        self.assertEqual(result, handler.response)

    def test_process_received_commitment_proposal_and_acceptance_mirror_records(self):
        from federation import FederationEnvelopeClaims

        mirrored_records = [
            {
                'commitment_id': 'com_fed_demo',
                'status': 'proposed',
                'federation_refs': [{'envelope_id': 'fed_commit_env_1'}],
            },
            {
                'commitment_id': 'com_fed_demo',
                'status': 'accepted',
                'accepted_by': 'peer:host_peer',
                'federation_refs': [
                    {'envelope_id': 'fed_commit_env_1'},
                    {'envelope_id': 'fed_commit_env_2'},
                ],
            },
        ]
        commit_calls = []
        self.workspace.commitments.mirror_federated_commitment = lambda *args, **kwargs: (
            commit_calls.append({'args': args, 'kwargs': kwargs}) or mirrored_records[len(commit_calls) - 1]
        )
        self.workspace._federation_inbox_entry = lambda *args, **kwargs: {
            'envelope_id': kwargs.get('envelope_id', ''),
            'state': kwargs.get('state', 'received'),
        }
        self.workspace.log_event = lambda *args, **kwargs: None

        proposal_claims = FederationEnvelopeClaims(
            envelope_id='fed_commit_env_1',
            source_host_id='host_peer',
            source_institution_id='org_peer',
            target_host_id='host_live',
            target_institution_id='org_founding',
            actor_type='user',
            actor_id='user_peer',
            session_id='ses_peer',
            boundary_name='federation_gateway',
            identity_model='signed_host_service',
            message_type='commitment_proposal',
            payload_hash='hash_proposal',
            warrant_id='war_commit',
            commitment_id='com_fed_demo',
        )
        proposal_processing = self.workspace._process_received_federation_message(
            'org_founding',
            proposal_claims,
            {'receipt_id': 'fedrcpt_commit_env_1', 'accepted_at': '2026-03-22T00:00:00Z'},
            payload={'commitment_type': 'deliver_brief', 'summary': 'Deliver the approved brief'},
        )

        acceptance_claims = FederationEnvelopeClaims(
            envelope_id='fed_commit_env_2',
            source_host_id='host_peer',
            source_institution_id='org_peer',
            target_host_id='host_live',
            target_institution_id='org_founding',
            actor_type='user',
            actor_id='user_peer',
            session_id='ses_peer',
            boundary_name='federation_gateway',
            identity_model='signed_host_service',
            message_type='commitment_acceptance',
            payload_hash='hash_acceptance',
            warrant_id='war_commit',
            commitment_id='com_fed_demo',
        )
        acceptance_processing = self.workspace._process_received_federation_message(
            'org_founding',
            acceptance_claims,
            {'receipt_id': 'fedrcpt_commit_env_2', 'accepted_at': '2026-03-22T00:01:00Z'},
            payload={'commitment_type': 'deliver_brief', 'summary': 'Deliver the approved brief'},
        )

        self.assertTrue(proposal_processing['applied'])
        self.assertEqual(proposal_processing['reason'], 'commitment_proposal_mirrored')
        self.assertEqual(proposal_processing['commitment']['status'], 'proposed')
        self.assertTrue(acceptance_processing['applied'])
        self.assertEqual(acceptance_processing['reason'], 'commitment_acceptance_mirrored')
        self.assertEqual(acceptance_processing['commitment']['status'], 'accepted')
        self.assertEqual(commit_calls[0]['kwargs']['message_type'], 'commitment_proposal')
        self.assertEqual(commit_calls[1]['kwargs']['message_type'], 'commitment_acceptance')
        self.assertEqual(commit_calls[0]['kwargs']['warrant_id'], 'war_commit')
        self.assertEqual(commit_calls[1]['kwargs']['warrant_id'], 'war_commit')

    def test_process_received_commitment_breach_notice_mirrors_breached_record_and_opens_case(self):
        from federation import FederationEnvelopeClaims

        mirrored_records = [{
            'commitment_id': 'com_fed_demo',
            'status': 'breached',
            'breached_by': 'peer:host_peer',
            'federation_refs': [{'envelope_id': 'fed_commit_env_3'}],
            'warrant_id': 'war_commit',
        }]
        commit_calls = []
        case_calls = []
        self.workspace.commitments.mirror_federated_commitment = lambda *args, **kwargs: (
            commit_calls.append({'args': args, 'kwargs': kwargs}) or mirrored_records[len(commit_calls) - 1]
        )
        self.workspace.cases.ensure_case_for_commitment_breach = lambda commitment_record, actor_id, **kwargs: (
            case_calls.append({'commitment_record': commitment_record, 'actor_id': actor_id, 'kwargs': kwargs})
            or ({
                'case_id': 'case_breach_demo',
                'claim_type': 'breach_of_commitment',
                'status': 'open',
                'linked_commitment_id': commitment_record['commitment_id'],
                'linked_warrant_id': commitment_record.get('warrant_id', ''),
            }, True)
        )
        self.workspace._maybe_stay_warrant_for_case = lambda *args, **kwargs: {
            'applied': True,
            'warrant_id': 'war_commit',
            'court_review_state': 'stayed',
        }
        self.workspace._federation_inbox_entry = lambda *args, **kwargs: {
            'envelope_id': kwargs.get('envelope_id', ''),
            'state': kwargs.get('state', 'received'),
        }
        self.workspace.log_event = lambda *args, **kwargs: None

        claims = FederationEnvelopeClaims(
            envelope_id='fed_commit_env_3',
            source_host_id='host_peer',
            source_institution_id='org_peer',
            target_host_id='host_live',
            target_institution_id='org_founding',
            actor_type='user',
            actor_id='user_peer',
            session_id='ses_peer',
            boundary_name='federation_gateway',
            identity_model='signed_host_service',
            message_type='commitment_breach_notice',
            payload_hash='hash_breach',
            warrant_id='war_commit',
            commitment_id='com_fed_demo',
        )
        processing = self.workspace._process_received_federation_message(
            'org_founding',
            claims,
            {'receipt_id': 'fedrcpt_commit_env_3', 'accepted_at': '2026-03-22T00:02:00Z'},
            payload={'commitment_type': 'deliver_brief', 'summary': 'Deliver the approved brief'},
        )

        self.assertTrue(processing['applied'])
        self.assertEqual(processing['reason'], 'commitment_breach_notice_mirrored')
        self.assertEqual(processing['commitment']['status'], 'breached')
        self.assertEqual(processing['case']['case_id'], 'case_breach_demo')
        self.assertEqual(processing['warrant']['court_review_state'], 'stayed')
        self.assertEqual(commit_calls[0]['kwargs']['message_type'], 'commitment_breach_notice')
        self.assertEqual(case_calls[0]['commitment_record']['status'], 'breached')

    def test_process_received_court_notice_reviews_sender_warrant_and_records_delivery_ref(self):
        from federation import FederationEnvelopeClaims

        delivery_refs = [{
            'message_type': 'execution_request',
            'envelope_id': 'fed_exec_demo',
            'target_host_id': 'host_peer',
            'target_institution_id': 'org_peer',
            'warrant_id': 'war_sender',
        }]
        sender_warrant = {
            'warrant_id': 'war_sender',
            'action_class': 'federated_execution',
            'boundary_name': 'federation_gateway',
            'court_review_state': 'approved',
            'execution_state': 'ready',
            'reviewed_by': '',
            'reviewed_at': '',
            'review_note': '',
        }
        self.workspace._federation_inbox_entry = lambda *args, **kwargs: {
            'envelope_id': kwargs.get('envelope_id', ''),
            'state': kwargs.get('state', 'received'),
        }
        self.workspace.get_warrant = lambda warrant_id, org_id=None: (
            dict(sender_warrant) if warrant_id == 'war_sender' else None
        )
        self.workspace.review_warrant = lambda warrant_id, decision, by, **kwargs: {
            **dict(sender_warrant),
            'warrant_id': warrant_id,
            'court_review_state': {'approve': 'approved', 'stay': 'stayed', 'revoke': 'revoked'}[decision],
            'reviewed_by': by,
            'reviewed_at': '2026-03-22T00:00:00Z',
            'review_note': kwargs.get('note', ''),
        }
        self.workspace.commitments.get_commitment = lambda commitment_id, org_id=None: {
            'commitment_id': commitment_id,
            'status': 'accepted',
            'delivery_refs': list(delivery_refs),
        }
        self.workspace.commitments.record_delivery_ref = lambda commitment_id, delivery_ref, **kwargs: {
            'commitment_id': commitment_id,
            'status': 'accepted',
            'delivery_refs': list(delivery_refs) + [dict(delivery_ref)],
        }
        self.workspace.log_event = lambda *args, **kwargs: None

        claims = FederationEnvelopeClaims(
            envelope_id='fed_court_demo',
            source_host_id='host_peer',
            source_institution_id='org_peer',
            target_host_id='host_live',
            target_institution_id='org_founding',
            actor_type='user',
            actor_id='user_peer',
            session_id='ses_peer',
            boundary_name='federation_gateway',
            identity_model='signed_host_service',
            message_type='court_notice',
            payload_hash='hash_court_demo',
            warrant_id='war_sender',
            commitment_id='com_fed_demo',
        )
        processing = self.workspace._process_received_federation_message(
            'org_founding',
            claims,
            {'receipt_id': 'fedrcpt_court_demo', 'accepted_at': '2026-03-22T00:00:00Z'},
            payload={
                'court_decision': 'stay',
                'sender_warrant_id': 'war_sender',
                'local_warrant_id': 'war_local_peer',
                'source_execution_envelope_id': 'fed_exec_demo',
                'source_execution_job_id': 'fej_demo',
                'source_execution_receipt_id': 'fedrcpt_exec_demo',
                'local_court_review_state': 'stayed',
                'local_execution_state': 'ready',
                'target_host_id': 'host_live',
                'target_institution_id': 'org_founding',
                'note': 'Receiver hold',
                'metadata': {'trace': 'court_notice_demo'},
            },
        )

        self.assertTrue(processing['applied'])
        self.assertEqual(processing['reason'], 'court_notice_applied')
        self.assertEqual(processing['warrant']['warrant_id'], 'war_sender')
        self.assertEqual(processing['warrant']['court_review_state'], 'stayed')
        self.assertEqual(processing['warrant']['reviewed_by'], 'user_peer')
        self.assertEqual(processing['delivery_ref']['message_type'], 'court_notice')
        self.assertEqual(processing['delivery_ref']['local_warrant_id'], 'war_local_peer')
        self.assertEqual(processing['outbound_execution_ref']['envelope_id'], 'fed_exec_demo')
        self.assertEqual(processing['inbox_entry']['state'], 'processed')

    def test_process_received_court_notice_blocks_missing_sender_reference(self):
        from federation import FederationEnvelopeClaims

        self.workspace._federation_inbox_entry = lambda *args, **kwargs: {
            'envelope_id': kwargs.get('envelope_id', ''),
            'state': kwargs.get('state', 'received'),
        }
        self.workspace.get_warrant = lambda warrant_id, org_id=None: {
            'warrant_id': 'war_sender',
            'action_class': 'federated_execution',
            'boundary_name': 'federation_gateway',
            'court_review_state': 'approved',
            'execution_state': 'ready',
        }
        self.workspace.commitments.get_commitment = lambda commitment_id, org_id=None: {
            'commitment_id': commitment_id,
            'status': 'accepted',
            'delivery_refs': [],
        }
        self.workspace.log_event = lambda *args, **kwargs: None

        claims = FederationEnvelopeClaims(
            envelope_id='fed_court_bad',
            source_host_id='host_peer',
            source_institution_id='org_peer',
            target_host_id='host_live',
            target_institution_id='org_founding',
            actor_type='user',
            actor_id='user_peer',
            session_id='ses_peer',
            boundary_name='federation_gateway',
            identity_model='signed_host_service',
            message_type='court_notice',
            payload_hash='hash_court_bad',
            warrant_id='war_sender',
            commitment_id='com_fed_demo',
        )
        processing = self.workspace._process_received_federation_message(
            'org_founding',
            claims,
            {'receipt_id': 'fedrcpt_court_bad', 'accepted_at': '2026-03-22T00:00:00Z'},
            payload={
                'court_decision': 'stay',
                'sender_warrant_id': 'war_sender',
                'local_warrant_id': 'war_local_peer',
                'source_execution_envelope_id': 'fed_exec_missing',
                'target_host_id': 'host_live',
                'target_institution_id': 'org_founding',
                'note': 'Receiver hold',
                'metadata': {},
            },
        )

        self.assertFalse(processing['applied'])
        self.assertEqual(processing['reason'], 'invalid_court_notice')
        self.assertIn("No outbound execution_request proof matches", processing['error'])

    def test_process_received_case_notice_mirrors_open_and_resolve(self):
        from federation import FederationEnvelopeClaims

        store = {'cases': {}}
        original_load_store = self.workspace.cases._load_store
        original_save_store = self.workspace.cases._save_store
        original_list_cases = self.workspace.cases.list_cases
        original_open_case = self.workspace.cases.open_case
        suspend_calls = []
        restore_calls = []
        try:
            self.workspace.cases._load_store = lambda org_id=None: {
                'cases': {key: dict(value) for key, value in store['cases'].items()},
            }
            self.workspace.cases._save_store = lambda data, org_id=None: store.__setitem__(
                'cases',
                {key: dict(value) for key, value in (data.get('cases') or {}).items()},
            )
            self.workspace.cases.list_cases = lambda org_id=None: list(store['cases'].values())

            def fake_open_case(org_id, claim_type, actor_id, **kwargs):
                record = {
                    'case_id': 'case_live_mirror',
                    'institution_id': org_id,
                    'source_institution_id': org_id,
                    'claim_type': claim_type,
                    'target_host_id': kwargs.get('target_host_id', ''),
                    'target_institution_id': kwargs.get('target_institution_id', ''),
                    'linked_commitment_id': kwargs.get('linked_commitment_id', ''),
                    'linked_warrant_id': kwargs.get('linked_warrant_id', ''),
                    'status': 'open',
                    'opened_by': actor_id,
                    'reviewed_by': '',
                    'reviewed_at': '',
                    'review_note': '',
                    'resolution': '',
                    'note': kwargs.get('note', ''),
                    'metadata': dict(kwargs.get('metadata') or {}),
                    'updated_at': '2026-03-22T00:00:00Z',
                }
                store['cases'][record['case_id']] = record
                return dict(record)

            self.workspace.cases.open_case = fake_open_case
            self.workspace._maybe_suspend_peer_for_case = lambda case_record, actor_id, **kwargs: (
                suspend_calls.append(case_record['case_id'])
                or {
                    'applied': False,
                    'peer_host_id': case_record.get('target_host_id', ''),
                    'reason': 'single_institution_deployment',
                    'trust_state': '',
                }
            )
            self.workspace._maybe_stay_warrant_for_case = lambda *args, **kwargs: {
                'applied': True,
                'court_review_state': 'stayed',
            }
            self.workspace._maybe_restore_peer_for_case = lambda case_record, actor_id, **kwargs: (
                restore_calls.append(case_record['case_id'])
                or {
                    'applied': False,
                    'peer_host_id': case_record.get('target_host_id', ''),
                    'reason': 'single_institution_deployment',
                    'trust_state': '',
                }
            )
            self.workspace._federation_inbox_entry = lambda *args, **kwargs: {
                'envelope_id': 'fed_case_live_open',
                'state': kwargs.get('state', 'received'),
            }
            self.workspace.log_event = lambda *args, **kwargs: None

            open_claims = FederationEnvelopeClaims(
                envelope_id='fed_case_live_open',
                source_host_id='host_alpha',
                source_institution_id='org_alpha',
                target_host_id='host_live',
                target_institution_id='org_founding',
                actor_type='user',
                actor_id='user_alpha',
                session_id='ses_alpha',
                boundary_name='federation_gateway',
                identity_model='signed_host_service',
                message_type='case_notice',
                payload_hash='hash_case_open',
            )
            open_payload = {
                'case_decision': 'open',
                'source_case_id': 'case_alpha_demo',
                'claim_type': 'misrouted_execution',
                'linked_commitment_id': 'cmt_demo',
                'linked_warrant_id': 'war_demo',
                'target_host_id': 'host_live',
                'target_institution_id': 'org_founding',
                'note': 'Open mirrored case',
            }
            first = self.workspace._process_received_federation_message(
                'org_founding',
                open_claims,
                {'receipt_id': 'fedrcpt_case_open', 'accepted_at': '2026-03-22T00:00:00Z'},
                payload=open_payload,
            )
            resolved = self.workspace._process_received_federation_message(
                'org_founding',
                FederationEnvelopeClaims(
                    envelope_id='fed_case_live_resolve',
                    source_host_id='host_alpha',
                    source_institution_id='org_alpha',
                    target_host_id='host_live',
                    target_institution_id='org_founding',
                    actor_type='user',
                    actor_id='user_alpha',
                    session_id='ses_alpha',
                    boundary_name='federation_gateway',
                    identity_model='signed_host_service',
                    message_type='case_notice',
                    payload_hash='hash_case_resolve',
                ),
                {'receipt_id': 'fedrcpt_case_resolve', 'accepted_at': '2026-03-22T00:01:00Z'},
                payload=dict(open_payload, case_decision='resolve', note='Resolved on source'),
            )
        finally:
            self.workspace.cases._load_store = original_load_store
            self.workspace.cases._save_store = original_save_store
            self.workspace.cases.list_cases = original_list_cases
            self.workspace.cases.open_case = original_open_case

        self.assertTrue(first['applied'])
        self.assertEqual(first['reason'], 'case_notice_applied')
        self.assertTrue(first['case_created'])
        self.assertEqual(first['case']['target_host_id'], 'host_alpha')
        self.assertEqual(first['case']['metadata']['federation_source_case_id'], 'case_alpha_demo')
        self.assertFalse(first['federation_peer']['applied'])
        self.assertEqual(first['federation_peer']['reason'], 'single_institution_deployment')

        self.assertTrue(resolved['applied'])
        self.assertEqual(resolved['case']['status'], 'resolved')
        self.assertFalse(resolved['federation_peer']['applied'])
        self.assertEqual(resolved['federation_peer']['reason'], 'single_institution_deployment')
        self.assertEqual(suspend_calls, ['case_live_mirror'])
        self.assertEqual(restore_calls, ['case_live_mirror'])

    def test_case_open_federate_fails_closed_when_live_federation_disabled(self):
        calls = []

        class FakeHandler:
            def __init__(self):
                self.path = '/api/cases/open'
                self.headers = _Headers()
                self.response = None

            def _require_auth(self, path):
                calls.append(('require_auth', path))
                return True

            def _session_claims_from_request(self, expected_org_id=None):
                calls.append(('session_claims', expected_org_id))
                return None

            def _read_body(self):
                return {
                    'claim_type': 'misrouted_execution',
                    'target_host_id': 'host_peer',
                    'target_institution_id': 'org_peer',
                    'federate': True,
                    'note': 'Mirror this case',
                }

            def _json(self, data, status=200):
                self.response = {'data': data, 'status': status}
                return self.response

        handler = FakeHandler()
        with mock.patch.object(
            self.workspace,
            '_resolve_workspace_context',
            return_value=types.SimpleNamespace(org_id='org_founding'),
        ), mock.patch.object(
            self.workspace,
            '_enforce_request_context',
            return_value={'requested_org_id': '', 'bound_org_id': 'org_founding'},
        ), mock.patch.object(
            self.workspace,
            '_resolve_auth_context',
            return_value={'actor_id': 'user_owner', 'session_id': 'ses_demo'},
        ), mock.patch.object(
            self.workspace,
            '_enforce_mutation_authorization',
            return_value='owner',
        ), mock.patch.object(
            self.workspace.cases,
            'open_case',
            return_value={
                'case_id': 'case_live_demo',
                'claim_type': 'misrouted_execution',
                'target_host_id': 'host_peer',
                'target_institution_id': 'org_peer',
                'linked_commitment_id': '',
                'linked_warrant_id': '',
                'status': 'open',
            },
        ), mock.patch.object(
            self.workspace,
            '_maybe_suspend_peer_for_case',
            return_value={
                'applied': False,
                'peer_host_id': 'host_peer',
                'reason': 'single_institution_deployment',
                'trust_state': '',
            },
        ), mock.patch.object(
            self.workspace,
            '_maybe_stay_warrant_for_case',
            return_value=None,
        ), mock.patch.object(
            self.workspace,
            '_deliver_case_notice',
            side_effect=self.workspace.FederationUnavailable('Federation gateway is disabled on host_live'),
        ), mock.patch.object(
            self.workspace,
            'log_event',
        ):
            result = self.workspace.WorkspaceHandler.do_POST(handler)

        self.assertEqual(calls[0], ('require_auth', '/api/cases/open'))
        self.assertEqual(result['status'], 503)
        self.assertEqual(result['data']['case']['case_id'], 'case_live_demo')
        self.assertIn('disabled', result['data']['error'])

    def test_case_resolve_federate_fails_closed_when_live_federation_disabled(self):
        calls = []

        class FakeHandler:
            def __init__(self):
                self.path = '/api/cases/resolve'
                self.headers = _Headers()
                self.response = None

            def _require_auth(self, path):
                calls.append(('require_auth', path))
                return True

            def _session_claims_from_request(self, expected_org_id=None):
                calls.append(('session_claims', expected_org_id))
                return None

            def _read_body(self):
                return {
                    'case_id': 'case_live_demo',
                    'federate': True,
                    'note': 'Resolve peer sync',
                }

            def _json(self, data, status=200):
                self.response = {'data': data, 'status': status}
                return self.response

        handler = FakeHandler()
        with mock.patch.object(
            self.workspace,
            '_resolve_workspace_context',
            return_value=types.SimpleNamespace(org_id='org_founding'),
        ), mock.patch.object(
            self.workspace,
            '_enforce_request_context',
            return_value={'requested_org_id': '', 'bound_org_id': 'org_founding'},
        ), mock.patch.object(
            self.workspace,
            '_resolve_auth_context',
            return_value={'actor_id': 'user_owner', 'session_id': 'ses_demo'},
        ), mock.patch.object(
            self.workspace,
            '_enforce_mutation_authorization',
            return_value='owner',
        ), mock.patch.object(
            self.workspace,
            '_case_record_by_id',
            return_value={
                'case_id': 'case_live_demo',
                'target_host_id': 'host_peer',
                'target_institution_id': 'org_peer',
            },
        ), mock.patch.object(
            self.workspace.cases,
            'resolve_case',
            return_value={
                'case_id': 'case_live_demo',
                'claim_type': 'misrouted_execution',
                'target_host_id': 'host_peer',
                'target_institution_id': 'org_peer',
                'linked_commitment_id': '',
                'linked_warrant_id': '',
                'status': 'resolved',
            },
        ), mock.patch.object(
            self.workspace,
            '_maybe_restore_peer_for_case',
            return_value={
                'applied': False,
                'peer_host_id': 'host_peer',
                'reason': 'single_institution_deployment',
                'trust_state': '',
            },
        ), mock.patch.object(
            self.workspace,
            '_deliver_case_notice',
            side_effect=self.workspace.FederationUnavailable('Federation gateway is disabled on host_live'),
        ), mock.patch.object(
            self.workspace,
            'log_event',
        ):
            result = self.workspace.WorkspaceHandler.do_POST(handler)

        self.assertEqual(calls[0], ('require_auth', '/api/cases/resolve'))
        self.assertEqual(result['status'], 503)
        self.assertEqual(result['data']['case']['case_id'], 'case_live_demo')
        self.assertEqual(result['data']['federation_peer']['reason'], 'single_institution_deployment')
        self.assertIn('disabled', result['data']['error'])

    def test_federation_send_commitment_breach_notice_fails_closed_when_live_federation_disabled(self):
        calls = []

        class FakeHandler:
            def __init__(self):
                self.path = '/api/federation/send'
                self.headers = _Headers()
                self.response = None

            def _require_auth(self, path):
                calls.append(('require_auth', path))
                return True

            def _session_claims_from_request(self, expected_org_id=None):
                calls.append(('session_claims', expected_org_id))
                return None

            def _read_body(self):
                return {
                    'target_host_id': 'host_peer',
                    'target_org_id': 'org_peer',
                    'message_type': 'commitment_breach_notice',
                    'commitment_id': 'cmt_live_demo',
                    'payload': {'summary': 'mirror breach notice'},
                }

            def _json(self, data, status=200):
                self.response = {'data': data, 'status': status}
                return self.response

        handler = FakeHandler()
        with mock.patch.object(
            self.workspace,
            '_resolve_workspace_context',
            return_value=types.SimpleNamespace(org_id='org_founding'),
        ), mock.patch.object(
            self.workspace,
            '_enforce_request_context',
            return_value={'requested_org_id': '', 'bound_org_id': 'org_founding'},
        ), mock.patch.object(
            self.workspace,
            '_resolve_auth_context',
            return_value={'actor_id': 'user_owner', 'session_id': 'ses_demo'},
        ), mock.patch.object(
            self.workspace,
            '_enforce_mutation_authorization',
            return_value='owner',
        ), mock.patch.object(
            self.workspace,
            '_deliver_federation_envelope',
            side_effect=self.workspace.FederationUnavailable('Federation gateway is disabled on host_live'),
        ), mock.patch.object(
            self.workspace,
            'log_event',
        ):
            result = self.workspace.WorkspaceHandler.do_POST(handler)

        self.assertEqual(calls[0], ('require_auth', '/api/federation/send'))
        self.assertEqual(result['status'], 503)
        self.assertIn('disabled', result['data']['error'])
        self.assertEqual(result, handler.response)

    def test_accounting_expense_route_passes_bound_org_to_writer(self):
        calls = []

        class FakeHandler:
            def __init__(self):
                self.path = '/api/accounting/expense'
                self.headers = _Headers()
                self.response = None

            def _require_auth(self, path):
                calls.append(('require_auth', path))
                return True

            def _session_claims_from_request(self, expected_org_id=None):
                calls.append(('session_claims', expected_org_id))
                return None

            def _read_body(self):
                return {'amount_usd': 1.25, 'note': 'travel'}

            def _json(self, data, status=200):
                self.response = {'data': data, 'status': status}
                return self.response

        recorded = {}
        handler = FakeHandler()
        with mock.patch.object(
            self.workspace,
            '_resolve_workspace_context',
            return_value=types.SimpleNamespace(org_id='org_founding'),
        ), mock.patch.object(
            self.workspace,
            '_enforce_request_context',
            return_value={'requested_org_id': '', 'bound_org_id': 'org_founding'},
        ), mock.patch.object(
            self.workspace,
            '_resolve_auth_context',
            return_value={'actor_id': 'user_owner', 'session_id': 'ses_demo'},
        ), mock.patch.object(
            self.workspace,
            '_enforce_mutation_authorization',
            return_value='owner',
        ), mock.patch.object(
            self.workspace.service_state,
            'accounting_snapshot',
            return_value={'bound_org_id': 'org_founding'},
        ), mock.patch.object(
            self.workspace,
            'log_event',
        ), mock.patch.object(
            self.workspace.accounting_service,
            'record_owner_expense',
            side_effect=lambda amount_usd, note='', by='owner', org_id=None: recorded.update({
                'amount_usd': amount_usd,
                'note': note,
                'actor': by,
                'org_id': org_id,
            }) or {'amount_usd': float(amount_usd), 'unreimbursed_expenses_usd': 1.25},
        ):
            result = self.workspace.WorkspaceHandler.do_POST(handler)

        self.assertEqual(calls[0], ('require_auth', '/api/accounting/expense'))
        self.assertEqual(recorded['org_id'], 'org_founding')
        self.assertEqual(recorded['actor'], 'user_owner')
        self.assertEqual(result['status'], 200)
        self.assertEqual(result['data']['message'], 'Owner expense recorded')
        self.assertEqual(result['data']['service_state']['bound_org_id'], 'org_founding')

    def test_treasury_contribute_route_passes_bound_org_to_treasury_layer(self):
        calls = []

        class FakeHandler:
            def __init__(self):
                self.path = '/api/treasury/contribute'
                self.headers = _Headers()
                self.response = None

            def _require_auth(self, path):
                calls.append(('require_auth', path))
                return True

            def _session_claims_from_request(self, expected_org_id=None):
                calls.append(('session_claims', expected_org_id))
                return None

            def _read_body(self):
                return {'amount': 2.0, 'note': 'seed capital'}

            def _json(self, data, status=200):
                self.response = {'data': data, 'status': status}
                return self.response

        recorded = {}
        handler = FakeHandler()
        with mock.patch.object(
            self.workspace,
            '_resolve_workspace_context',
            return_value=types.SimpleNamespace(org_id='org_founding'),
        ), mock.patch.object(
            self.workspace,
            '_enforce_request_context',
            return_value={'requested_org_id': '', 'bound_org_id': 'org_founding'},
        ), mock.patch.object(
            self.workspace,
            '_resolve_auth_context',
            return_value={'actor_id': 'user_owner', 'session_id': 'ses_demo'},
        ), mock.patch.object(
            self.workspace,
            '_enforce_mutation_authorization',
            return_value='owner',
        ), mock.patch.object(
            self.workspace,
            'contribute_owner_capital',
            side_effect=lambda amount, note='', by='owner', org_id=None: recorded.update({
                'amount': amount,
                'note': note,
                'by': by,
                'org_id': org_id,
            }) or {'amount_usd': float(amount)},
        ), mock.patch.object(
            self.workspace,
            'treasury_snapshot',
            return_value={'bound_org_id': 'org_founding'},
        ), mock.patch.object(
            self.workspace,
            'log_event',
        ):
            result = self.workspace.WorkspaceHandler.do_POST(handler)

        self.assertEqual(calls[0], ('require_auth', '/api/treasury/contribute'))
        self.assertEqual(recorded['org_id'], 'org_founding')
        self.assertEqual(recorded['by'], 'user_owner')
        self.assertEqual(result['status'], 200)
        self.assertIn('Owner capital recorded', result['data']['message'])
        self.assertEqual(result['data']['snapshot']['bound_org_id'], 'org_founding')

    def test_federation_receipt_is_bound_to_receiver_host_and_org(self):
        from federation import FederationEnvelopeClaims

        receipt = self.workspace._federation_receipt(
            'org_founding',
            'host_live',
            FederationEnvelopeClaims(
                envelope_id='fed_demo',
                message_type='execution_request',
                boundary_name='federation_gateway',
            ),
        )
        self.assertEqual(receipt['envelope_id'], 'fed_demo')
        self.assertEqual(receipt['receiver_host_id'], 'host_live')
        self.assertEqual(receipt['receiver_institution_id'], 'org_founding')
        self.assertEqual(receipt['identity_model'], 'signed_host_service')
        self.assertTrue(receipt['receipt_id'].startswith('fedrcpt_'))

    def test_process_received_execution_request_creates_local_warranted_job(self):
        from federation import FederationEnvelopeClaims

        audit_events = []
        self.workspace.get_execution_job = lambda envelope_id, org_id=None: None
        self.workspace.issue_warrant = lambda *args, **kwargs: {
            'warrant_id': 'war_local_demo',
            'court_review_state': 'pending_review',
            'execution_state': 'ready',
            'expires_at': '2026-03-22T01:00:00Z',
        }
        self.workspace.get_warrant = lambda warrant_id, org_id=None: {
            'warrant_id': warrant_id,
            'court_review_state': 'pending_review',
            'execution_state': 'ready',
            'expires_at': '2026-03-22T01:00:00Z',
        }
        self.workspace.upsert_execution_job = lambda org_id, job: dict(job, job_id='fej_demo')
        original_blocking_case = self.workspace._blocking_case_for_delivery
        self.workspace._blocking_case_for_delivery = lambda **kwargs: None
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append({
            'args': args,
            'kwargs': kwargs,
        })
        original_inbox_entry = self.workspace._federation_inbox_entry
        self.workspace._federation_inbox_entry = lambda *args, **kwargs: {
            'envelope_id': 'fed_exec_demo',
            'state': kwargs.get('state', 'received'),
        }
        try:
            claims = FederationEnvelopeClaims(
                envelope_id='fed_exec_demo',
                source_host_id='host_peer',
                source_institution_id='org_peer',
                target_host_id='host_live',
                target_institution_id='org_founding',
                actor_type='service',
                actor_id='peer:host_peer',
                session_id='ses_peer',
                boundary_name='federation_gateway',
                identity_model='signed_host_service',
                message_type='execution_request',
                payload_hash='hash_live',
                warrant_id='war_sender',
                commitment_id='cmt_live',
            )
            processing = self.workspace._process_received_federation_message(
                'org_founding',
                claims,
                {'receipt_id': 'fedrcpt_live', 'accepted_at': '2026-03-22T00:00:00Z'},
                payload={'task': 'demo'},
            )
        finally:
            self.workspace._blocking_case_for_delivery = original_blocking_case
            self.workspace._federation_inbox_entry = original_inbox_entry

        self.assertTrue(processing['applied'])
        self.assertEqual(processing['state'], 'processed')
        self.assertEqual(processing['reason'], 'execution_job_created')
        self.assertEqual(processing['execution_job']['job_id'], 'fej_demo')
        self.assertEqual(processing['execution_job']['state'], 'pending_local_warrant')
        self.assertEqual(processing['receiver_warrant']['warrant_id'], 'war_local_demo')
        self.assertEqual(processing['inbox_entry']['state'], 'processed')
        self.assertEqual(audit_events[-1]['args'][2], 'federation_execution_job_created')

    def test_process_received_execution_request_blocks_on_case(self):
        from federation import FederationEnvelopeClaims

        self.workspace.get_execution_job = lambda envelope_id, org_id=None: None
        self.workspace.issue_warrant = lambda *args, **kwargs: self.fail('blocked execution should not issue warrant')
        original_blocking_case = self.workspace._blocking_case_for_delivery
        self.workspace._blocking_case_for_delivery = lambda **kwargs: {
            'case_id': 'case_live_demo',
            'claim_type': 'non_delivery',
            'status': 'open',
        }
        self.workspace.upsert_execution_job = lambda org_id, job: dict(job, job_id='fej_demo')
        self.workspace.log_event = lambda *args, **kwargs: None
        original_inbox_entry = self.workspace._federation_inbox_entry
        self.workspace._federation_inbox_entry = lambda *args, **kwargs: {
            'envelope_id': 'fed_exec_demo',
            'state': kwargs.get('state', 'received'),
        }
        try:
            claims = FederationEnvelopeClaims(
                envelope_id='fed_exec_demo',
                source_host_id='host_peer',
                source_institution_id='org_peer',
                target_host_id='host_live',
                target_institution_id='org_founding',
                actor_type='service',
                actor_id='peer:host_peer',
                session_id='ses_peer',
                boundary_name='federation_gateway',
                identity_model='signed_host_service',
                message_type='execution_request',
                payload_hash='hash_live',
                warrant_id='war_sender',
                commitment_id='cmt_live',
            )
            processing = self.workspace._process_received_federation_message(
                'org_founding',
                claims,
                {'receipt_id': 'fedrcpt_live', 'accepted_at': '2026-03-22T00:00:00Z'},
                payload={'task': 'demo'},
            )
        finally:
            self.workspace._blocking_case_for_delivery = original_blocking_case
            self.workspace._federation_inbox_entry = original_inbox_entry

        self.assertTrue(processing['applied'])
        self.assertEqual(processing['reason'], 'case_blocked')
        self.assertEqual(processing['execution_job']['state'], 'blocked')
        self.assertEqual(processing['case']['case_id'], 'case_live_demo')
        self.assertIsNone(processing['receiver_warrant'])

    def test_mutate_federation_peer_is_rejected_on_live(self):
        with self.assertRaises(PermissionError):
            self.workspace._mutate_federation_peer('org_founding', 'upsert', {
                'peer_host_id': 'host_beta',
                'shared_secret': 'beta-secret',
            })

    def test_mutate_federation_peer_refresh_is_rejected_on_live(self):
        with self.assertRaises(PermissionError):
            self.workspace._mutate_federation_peer('org_founding', 'refresh', {
                'peer_host_id': 'host_beta',
            })

    def test_maybe_suspend_peer_for_case_reports_founding_lock(self):
        result = self.workspace._maybe_suspend_peer_for_case(
            {
                'case_id': 'case_live_demo',
                'claim_type': 'misrouted_execution',
                'status': 'open',
                'target_host_id': 'host_peer',
            },
            'user_owner',
            org_id='org_founding',
            session_id='ses_demo',
        )
        self.assertFalse(result['applied'])
        self.assertEqual(result['peer_host_id'], 'host_peer')
        self.assertEqual(result['reason'], 'single_institution_deployment')

    def test_maybe_restore_peer_for_case_reports_founding_lock(self):
        result = self.workspace._maybe_restore_peer_for_case(
            {
                'case_id': 'case_live_demo',
                'claim_type': 'misrouted_execution',
                'status': 'resolved',
                'target_host_id': 'host_peer',
            },
            'user_owner',
            org_id='org_founding',
            session_id='ses_demo',
        )
        self.assertFalse(result['applied'])
        self.assertEqual(result['peer_host_id'], 'host_peer')
        self.assertEqual(result['reason'], 'single_institution_deployment')

    def test_maybe_restore_peer_for_case_restores_peer_when_management_allows(self):
        self.workspace._runtime_host_state = lambda _org_id: (
            types.SimpleNamespace(host_id='host_live', role='institution_host'),
            {'admitted_org_ids': ['org_founding']},
        )
        self.workspace._federation_management_state = lambda _host_identity=None: {
            'mutation_enabled': True,
            'mutation_disabled_reason': '',
        }
        self.workspace.cases.peer_can_be_thawed = lambda peer_host_id, org_id=None, claim_types=None: True
        self.workspace.set_peer_trust_state = lambda *args, **kwargs: {
            'peers': {
                'host_peer': {
                    'host_id': 'host_peer',
                    'trust_state': 'trusted',
                    'admitted_org_ids': ['org_peer'],
                    'label': 'Peer',
                },
            }
        }
        logs = []
        self.workspace.log_event = lambda *args, **kwargs: logs.append({'args': args, 'kwargs': kwargs})

        result = self.workspace._maybe_restore_peer_for_case(
            {
                'case_id': 'case_live_demo',
                'claim_type': 'misrouted_execution',
                'status': 'resolved',
                'target_host_id': 'host_peer',
            },
            'user_owner',
            org_id='org_founding',
            session_id='ses_demo',
        )
        self.assertTrue(result['applied'])
        self.assertEqual(result['peer_host_id'], 'host_peer')
        self.assertEqual(result['trust_state'], 'trusted')
        self.assertEqual(result['admitted_org_ids'], ['org_peer'])
        self.assertEqual(logs[-1]['args'][2], 'federation_peer_auto_reinstated')

    def test_maybe_open_case_for_delivery_failure_reports_fail_closed_peer_state(self):
        from federation import FederationDeliveryError

        audit_events = []
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append({
            'args': args,
            'kwargs': kwargs,
        })
        self.workspace.cases.ensure_case_for_delivery_failure = lambda claim_type, actor_id, **kwargs: ({
            'case_id': 'case_live_demo',
            'claim_type': claim_type,
            'status': 'open',
            'linked_commitment_id': kwargs.get('linked_commitment_id', ''),
            'target_host_id': kwargs.get('target_host_id', ''),
        }, True)
        error = FederationDeliveryError(
            "Peer host 'host_peer' returned receipt receiver_institution_id 'org_wrong', not 'org_peer'",
            peer_host_id='host_peer',
        )

        case_record, federation_peer = self.workspace._maybe_open_case_for_delivery_failure(
            error,
            'user_owner',
            org_id='org_founding',
            target_host_id='host_peer',
            target_institution_id='org_peer',
            commitment_id='cmt_demo',
            warrant_id='war_demo',
            session_id='ses_demo',
        )

        self.assertEqual(case_record['claim_type'], 'misrouted_execution')
        self.assertEqual(federation_peer['peer_host_id'], 'host_peer')
        self.assertFalse(federation_peer['applied'])
        self.assertEqual(federation_peer['reason'], 'single_institution_deployment')
        self.assertEqual(audit_events[0]['args'][2], 'case_opened')

    def test_maybe_stay_warrant_for_case_stays_ready_warrant(self):
        audit_events = []
        self.workspace.list_warrants = lambda org_id=None, **_kwargs: [
            {
                'warrant_id': 'war_live_demo',
                'court_review_state': 'approved',
                'execution_state': 'ready',
            }
        ]
        self.workspace.review_warrant = lambda warrant_id, decision, by, **_kwargs: {
            'warrant_id': warrant_id,
            'court_review_state': 'stayed',
            'execution_state': 'ready',
            'reviewed_by': by,
        }
        self.workspace._sync_execution_job_for_warrant_review = lambda *args, **kwargs: {
            'job_id': 'fej_live_demo',
            'state': 'blocked',
        }
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append({
            'args': args,
            'kwargs': kwargs,
        })

        warrant = self.workspace._maybe_stay_warrant_for_case(
            {
                'case_id': 'case_live_demo',
                'claim_type': 'misrouted_execution',
                'linked_warrant_id': 'war_live_demo',
            },
            'user_owner',
            org_id='org_founding',
            session_id='ses_demo',
            note='Receipt contradiction',
        )

        self.assertTrue(warrant['applied'])
        self.assertEqual(warrant['warrant_id'], 'war_live_demo')
        self.assertEqual(warrant['court_review_state'], 'stayed')
        self.assertEqual(warrant['execution_job']['job_id'], 'fej_live_demo')
        self.assertEqual(audit_events[0]['args'][2], 'warrant_stayed_for_case')
        self.assertEqual(audit_events[0]['kwargs']['details']['case_id'], 'case_live_demo')
        self.assertEqual(audit_events[0]['kwargs']['details']['job_state'], 'blocked')

    def test_maybe_block_commitment_settlement_returns_case_and_warrant(self):
        audit_events = []
        self.workspace.cases.blocking_commitment_case = lambda commitment_id, **_kwargs: {
            'case_id': 'case_live_demo',
            'claim_type': 'non_delivery',
            'status': 'open',
            'linked_commitment_id': commitment_id,
            'linked_warrant_id': 'war_live_demo',
        }
        self.workspace.list_warrants = lambda org_id=None, **_kwargs: [
            {
                'warrant_id': 'war_live_demo',
                'court_review_state': 'approved',
                'execution_state': 'ready',
            }
        ]
        self.workspace.review_warrant = lambda warrant_id, decision, by, **_kwargs: {
            'warrant_id': warrant_id,
            'court_review_state': 'stayed',
            'execution_state': 'ready',
            'reviewed_by': by,
        }
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append({
            'args': args,
            'kwargs': kwargs,
        })

        case_record, warrant = self.workspace._maybe_block_commitment_settlement(
            'cmt_demo',
            'user_owner',
            org_id='org_founding',
            session_id='ses_demo',
            note='Do not settle while case is open',
        )

        self.assertEqual(case_record['case_id'], 'case_live_demo')
        self.assertTrue(warrant['applied'])
        self.assertEqual(warrant['warrant_id'], 'war_live_demo')
        self.assertEqual(audit_events[-1]['args'][2], 'commitment_settlement_blocked')
        self.assertEqual(audit_events[-1]['kwargs']['resource'], 'cmt_demo')

    def test_sync_execution_job_for_warrant_review_marks_ready(self):
        calls = {}
        self.workspace.get_execution_job_by_local_warrant = lambda warrant_id, org_id: {
            'job_id': 'fej_live_demo',
            'local_warrant_id': warrant_id,
            'state': 'pending_local_warrant',
            'note': 'Queued',
        }

        def _sync(org_id, warrant_id, **kwargs):
            calls['sync'] = {
                'org_id': org_id,
                'warrant_id': warrant_id,
                **kwargs,
            }
            return {
                'job_id': 'fej_live_demo',
                'local_warrant_id': warrant_id,
                'state': kwargs['state'],
                'note': kwargs['note'],
                'metadata': kwargs['metadata'],
            }

        self.workspace.sync_execution_job_for_local_warrant = _sync
        self.workspace.get_warrant = lambda warrant_id, org_id=None: {
            'warrant_id': warrant_id,
            'court_review_state': 'approved',
            'execution_state': 'ready',
            'expires_at': '2026-03-22T01:00:00Z',
        }

        job = self.workspace._sync_execution_job_for_warrant_review(
            'org_founding',
            {
                'warrant_id': 'war_live_local',
                'action_class': 'federated_execution',
                'boundary_name': 'federation_gateway',
                'court_review_state': 'approved',
                'execution_state': 'ready',
                'reviewed_by': 'user_owner',
                'reviewed_at': '2026-03-22T00:30:00Z',
            },
            decision='approve',
            note='Reviewed locally',
        )

        self.assertEqual(calls['sync']['state'], 'ready')
        self.assertEqual(calls['sync']['metadata']['review_decision'], 'approve')
        self.assertEqual(job['state'], 'ready')
        self.assertEqual(job['local_warrant']['court_review_state'], 'approved')

    def test_sync_execution_job_for_warrant_review_blocks_or_rejects_local_warrant(self):
        cases = (
            ('stayed', 'stay', 'blocked'),
            ('revoked', 'revoke', 'rejected'),
        )

        for court_review_state, decision, expected_state in cases:
            with self.subTest(court_review_state=court_review_state, decision=decision):
                calls = {}
                self.workspace.get_execution_job_by_local_warrant = lambda warrant_id, org_id: {
                    'job_id': 'fej_live_demo',
                    'local_warrant_id': warrant_id,
                    'state': 'pending_local_warrant',
                    'note': 'Queued',
                }

                def _sync(org_id, warrant_id, **kwargs):
                    calls['sync'] = {
                        'org_id': org_id,
                        'warrant_id': warrant_id,
                        **kwargs,
                    }
                    return {
                        'job_id': 'fej_live_demo',
                        'local_warrant_id': warrant_id,
                        'state': kwargs['state'],
                        'note': kwargs['note'],
                        'metadata': kwargs['metadata'],
                    }

                self.workspace.sync_execution_job_for_local_warrant = _sync
                self.workspace.get_warrant = lambda warrant_id, org_id=None, state=court_review_state: {
                    'warrant_id': warrant_id,
                    'court_review_state': state,
                    'execution_state': 'ready',
                    'expires_at': '2026-03-22T01:00:00Z',
                }

                job = self.workspace._sync_execution_job_for_warrant_review(
                    'org_founding',
                    {
                        'warrant_id': 'war_live_local',
                        'action_class': 'federated_execution',
                        'boundary_name': 'federation_gateway',
                        'court_review_state': court_review_state,
                        'execution_state': 'ready',
                        'reviewed_by': 'user_owner',
                        'reviewed_at': '2026-03-22T00:30:00Z',
                    },
                    decision=decision,
                    note='Reviewed locally',
                )

                self.assertEqual(calls['sync']['state'], expected_state)
                self.assertEqual(calls['sync']['metadata']['review_decision'], decision)
                self.assertEqual(job['state'], expected_state)
                self.assertEqual(job['local_warrant']['court_review_state'], court_review_state)

    def test_process_received_settlement_notice_marks_inbox_processed(self):
        from federation import FederationEnvelopeClaims

        audit_events = []
        self.workspace.commitments.validate_commitment_for_settlement = (
            lambda commitment_id, **_kwargs: {'commitment_id': commitment_id, 'state': 'accepted'}
        )
        self.workspace._maybe_block_commitment_settlement = lambda *args, **kwargs: (None, None)
        self.workspace.commitments.record_settlement_ref = lambda *args, **kwargs: None
        self.workspace.get_warrant = lambda warrant_id, org_id=None: {
            'warrant_id': warrant_id,
            'court_review_state': 'approved',
            'execution_state': 'ready',
        }
        self.workspace.commitments.settle_commitment = lambda commitment_id, by, **_kwargs: {
            'commitment_id': commitment_id,
            'state': 'settled',
            'settled_by': by,
            'delivery_refs': [
                {
                    'message_type': 'execution_request',
                    'warrant_id': 'war_sender',
                    'envelope_id': 'fed_exec_sender',
                    'receipt_id': 'fedrcpt_sender',
                    'target_host_id': 'host_live',
                    'target_institution_id': 'org_founding',
                },
            ],
        }
        sender_warrants = []
        self.workspace.mark_warrant_executed = lambda warrant_id, **_kwargs: sender_warrants.append(warrant_id) or {
            'warrant_id': warrant_id,
            'execution_state': 'executed',
        }
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append({
            'args': args,
            'kwargs': kwargs,
        })
        original_inbox_entry = self.workspace._federation_inbox_entry
        self.workspace._federation_inbox_entry = lambda *args, **kwargs: {
            'envelope_id': 'fed_live_settle',
            'state': kwargs.get('state', 'received'),
            'processed_at': '2026-03-22T00:00:00Z' if kwargs.get('state') == 'processed' else '',
        }
        try:
            with mock.patch.object(
                self.workspace,
                '_runtime_host_state',
                return_value=(
                    types.SimpleNamespace(settlement_adapters=['internal_ledger']),
                    {'admitted_org_ids': ['org_founding']},
                ),
            ), mock.patch.object(self.workspace, 'preflight_settlement_adapter') as preflight_mock:
                preflight_mock.return_value = {
                    'default_payout_adapter': 'internal_ledger',
                    'requested_adapter_id': 'internal_ledger',
                    'currency': 'USDC',
                    'host_supported_adapters': ['internal_ledger'],
                    'known': True,
                    'preflight_ok': True,
                    'can_execute_now': True,
                    'execution_enabled': True,
                    'error_type': '',
                    'error': '',
                    'contract': {
                        'adapter_id': 'internal_ledger',
                        'execution_mode': 'host_ledger',
                        'settlement_path': 'journal_append',
                        'proof_type': 'ledger_transaction',
                        'verification_state': 'host_ledger_final',
                        'finality_state': 'host_local_final',
                        'finality_model': 'host_local_final',
                        'dispute_model': 'court_case',
                        'reversal_or_dispute_capability': 'court_case',
                    },
                }
                claims = FederationEnvelopeClaims(
                    envelope_id='fed_live_settle',
                    source_host_id='host_peer',
                    source_institution_id='org_peer',
                    target_host_id='host_live',
                    target_institution_id='org_founding',
                    actor_type='service',
                    actor_id='peer:host_peer',
                    session_id='ses_peer',
                    boundary_name='federation_gateway',
                    identity_model='signed_host_service',
                    message_type='settlement_notice',
                    payload_hash='hash_live',
                    warrant_id='war_live',
                    commitment_id='cmt_live',
                )
                processing = self.workspace._process_received_federation_message(
                    'org_founding',
                    claims,
                    {'receipt_id': 'fedrcpt_live', 'accepted_at': '2026-03-22T00:00:00Z'},
                    payload={
                        'proposal_id': 'ppo_live',
                        'tx_ref': 'tx_live',
                        'tx_hash': '0xdeadbeef',
                        'settlement_adapter': 'internal_ledger',
                        'currency': 'USDC',
                        'proof': {'mode': 'institution_transactions_journal'},
                    },
                )
        finally:
            self.workspace._federation_inbox_entry = original_inbox_entry

        preflight_mock.assert_called_once_with(
            'internal_ledger',
            org_id='org_founding',
            currency='USDC',
            tx_hash='0xdeadbeef',
            settlement_proof={'mode': 'institution_transactions_journal'},
            host_supported_adapters=['internal_ledger'],
        )
        self.assertTrue(processing['applied'])
        self.assertEqual(processing['state'], 'processed')
        self.assertEqual(processing['reason'], 'settlement_notice_applied')
        self.assertEqual(processing['commitment']['state'], 'settled')
        self.assertEqual(processing['settlement_ref']['tx_ref'], 'tx_live')
        self.assertEqual(
            processing['settlement_ref']['settlement_adapter_contract_snapshot']['adapter_id'],
            'internal_ledger',
        )
        self.assertEqual(
            processing['settlement_ref']['settlement_adapter_contract_digest'],
            self.workspace.settlement_adapter_contract_digest(
                processing['settlement_ref']['settlement_adapter_contract_snapshot']
            ),
        )
        self.assertEqual(processing['settlement_adapter_preflight']['preflight_ok'], True)
        self.assertEqual(processing['inbox_entry']['state'], 'processed')
        self.assertEqual(processing['warrant']['warrant_id'], 'war_sender')
        self.assertEqual(sender_warrants, ['war_sender'])
        self.assertEqual(audit_events[-1]['args'][2], 'federation_settlement_notice_applied')

    def test_process_received_settlement_notice_blocks_failed_adapter_preflight(self):
        from federation import FederationEnvelopeClaims

        audit_events = []
        self.workspace.commitments.validate_commitment_for_settlement = (
            lambda commitment_id, **_kwargs: {'commitment_id': commitment_id, 'state': 'accepted'}
        )
        self.workspace._maybe_block_commitment_settlement = lambda *args, **kwargs: (None, None)
        self.workspace.commitments.record_settlement_ref = lambda *args, **kwargs: self.fail(
            'settlement ref should not be recorded'
        )
        self.workspace.commitments.settle_commitment = lambda *args, **kwargs: self.fail(
            'commitment should not settle'
        )
        self.workspace.cases.ensure_case_for_delivery_failure = lambda *args, **kwargs: (
            {
                'case_id': 'case_live_invalid_notice',
                'claim_type': 'invalid_settlement_notice',
                'status': 'open',
                'linked_commitment_id': 'cmt_live',
                'target_host_id': 'host_peer',
            },
            True,
        )
        self.workspace._maybe_suspend_peer_for_case = lambda *args, **kwargs: {
            'applied': True,
            'peer_host_id': 'host_peer',
            'trust_state': 'suspended',
        }
        self.workspace.mark_warrant_executed = lambda *args, **kwargs: self.fail(
            'sender warrant should not finalize when settlement preflight fails'
        )
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append({
            'args': args,
            'kwargs': kwargs,
        })

        with mock.patch.object(
            self.workspace,
            '_runtime_host_state',
            return_value=(
                types.SimpleNamespace(settlement_adapters=['internal_ledger']),
                {'admitted_org_ids': ['org_founding']},
            ),
        ), mock.patch.object(self.workspace, 'preflight_settlement_adapter') as preflight_mock:
            preflight_mock.return_value = {
                'default_payout_adapter': 'internal_ledger',
                'requested_adapter_id': 'base_usdc_x402',
                'currency': 'USDC',
                'host_supported_adapters': ['internal_ledger'],
                'known': True,
                'preflight_ok': False,
                'can_execute_now': False,
                'execution_enabled': False,
                'error_type': 'permission_error',
                'error': "Settlement adapter 'base_usdc_x402' is not enabled for payout execution",
            }

            claims = FederationEnvelopeClaims(
                envelope_id='fed_live_blocked',
                source_host_id='host_peer',
                source_institution_id='org_peer',
                target_host_id='host_live',
                target_institution_id='org_founding',
                actor_type='service',
                actor_id='peer:host_peer',
                session_id='ses_peer',
                boundary_name='federation_gateway',
                identity_model='signed_host_service',
                message_type='settlement_notice',
                payload_hash='hash_live',
                warrant_id='war_live',
                commitment_id='cmt_live',
            )
            processing = self.workspace._process_received_federation_message(
                'org_founding',
                claims,
                {'receipt_id': 'fedrcpt_live', 'accepted_at': '2026-03-22T00:00:00Z'},
                payload={
                    'proposal_id': 'ppo_live',
                    'tx_ref': 'tx_live',
                    'settlement_adapter': 'base_usdc_x402',
                    'currency': 'USDC',
                    'proof': {'reference': 'live-proof'},
                },
            )

        self.assertEqual(preflight_mock.call_count, 2)
        self.assertFalse(processing['applied'])
        self.assertEqual(processing['state'], 'received')
        self.assertEqual(processing['reason'], 'invalid_settlement_notice')
        self.assertIn('not enabled for payout execution', processing['error'])
        self.assertEqual(processing['case']['case_id'], 'case_live_invalid_notice')
        self.assertTrue(processing['case_created'])
        self.assertEqual(processing['federation_peer']['trust_state'], 'suspended')
        self.assertEqual(processing['settlement_adapter_preflight']['requested_adapter_id'], 'base_usdc_x402')
        self.assertEqual(processing['settlement_adapter_preflight']['error_type'], 'permission_error')
        self.assertEqual(audit_events[-1]['args'][2], 'federation_settlement_notice_rejected')

    def test_process_received_settlement_notice_blocks_contract_digest_mismatch(self):
        from federation import FederationEnvelopeClaims

        audit_events = []
        self.workspace.commitments.validate_commitment_for_settlement = (
            lambda commitment_id, **_kwargs: {'commitment_id': commitment_id, 'state': 'accepted'}
        )
        self.workspace._maybe_block_commitment_settlement = lambda *args, **kwargs: (None, None)
        self.workspace.commitments.record_settlement_ref = lambda *args, **kwargs: self.fail(
            'settlement ref should not be recorded'
        )
        self.workspace.commitments.settle_commitment = lambda *args, **kwargs: self.fail(
            'commitment should not settle'
        )
        self.workspace.cases.ensure_case_for_delivery_failure = lambda *args, **kwargs: (
            {
                'case_id': 'case_live_digest_mismatch',
                'claim_type': 'invalid_settlement_notice',
                'status': 'open',
                'linked_commitment_id': 'cmt_live',
                'target_host_id': 'host_peer',
            },
            True,
        )
        self.workspace._maybe_suspend_peer_for_case = lambda *args, **kwargs: {
            'applied': True,
            'peer_host_id': 'host_peer',
            'trust_state': 'suspended',
        }
        self.workspace.mark_warrant_executed = lambda *args, **kwargs: self.fail(
            'sender warrant should not finalize when settlement contract drifts'
        )
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append({
            'args': args,
            'kwargs': kwargs,
        })

        with mock.patch.object(
            self.workspace,
            '_runtime_host_state',
            return_value=(
                types.SimpleNamespace(settlement_adapters=['internal_ledger']),
                {'admitted_org_ids': ['org_founding']},
            ),
        ), mock.patch.object(self.workspace, 'preflight_settlement_adapter') as preflight_mock:
            preflight_mock.return_value = {
                'default_payout_adapter': 'internal_ledger',
                'requested_adapter_id': 'internal_ledger',
                'currency': 'USDC',
                'host_supported_adapters': ['internal_ledger'],
                'known': True,
                'preflight_ok': True,
                'can_execute_now': True,
                'execution_enabled': True,
                'error_type': '',
                'error': '',
                'contract': {
                    'adapter_id': 'internal_ledger',
                    'execution_mode': 'host_ledger',
                    'settlement_path': 'journal_append',
                    'proof_type': 'ledger_transaction',
                    'verification_state': 'host_ledger_final',
                    'finality_state': 'host_local_final',
                    'finality_model': 'host_local_final',
                    'dispute_model': 'court_case',
                    'reversal_or_dispute_capability': 'court_case',
                },
            }

            claims = FederationEnvelopeClaims(
                envelope_id='fed_live_digest_mismatch',
                source_host_id='host_peer',
                source_institution_id='org_peer',
                target_host_id='host_live',
                target_institution_id='org_founding',
                actor_type='service',
                actor_id='peer:host_peer',
                session_id='ses_peer',
                boundary_name='federation_gateway',
                identity_model='signed_host_service',
                message_type='settlement_notice',
                payload_hash='hash_live',
                warrant_id='war_live',
                commitment_id='cmt_live',
            )
            processing = self.workspace._process_received_federation_message(
                'org_founding',
                claims,
                {'receipt_id': 'fedrcpt_live', 'accepted_at': '2026-03-22T00:00:00Z'},
                payload={
                    'proposal_id': 'ppo_live',
                    'tx_ref': 'tx_live',
                    'settlement_adapter': 'internal_ledger',
                    'currency': 'USDC',
                    'proof': {'mode': 'institution_transactions_journal'},
                    'settlement_adapter_contract_snapshot': {
                        'contract_version': 2,
                        'adapter_id': 'internal_ledger',
                        'status': 'active',
                        'payout_execution_enabled': True,
                        'execution_mode': 'host_ledger',
                        'settlement_path': 'tampered_path',
                        'supported_currencies': ['USD', 'USDC'],
                        'requires_tx_hash': False,
                        'requires_settlement_proof': False,
                        'requires_verifier_attestation': False,
                        'verification_mode': 'host_ledger',
                        'verification_ready': True,
                        'accepted_attestation_types': [],
                        'proof_type': 'ledger_transaction',
                        'verification_state': 'host_ledger_final',
                        'finality_state': 'host_local_final',
                        'finality_model': 'host_local_final',
                        'reversal_or_dispute_capability': 'court_case',
                        'dispute_model': 'court_case',
                    },
                    'settlement_adapter_contract_digest': 'bad-digest',
                },
            )

        self.assertFalse(processing['applied'])
        self.assertEqual(processing['state'], 'received')
        self.assertEqual(processing['reason'], 'invalid_settlement_notice')
        self.assertIn('contract drifted', processing['error'])
        self.assertEqual(processing['case']['case_id'], 'case_live_digest_mismatch')
        self.assertEqual(processing['federation_peer']['trust_state'], 'suspended')
        self.assertEqual(processing['settlement_adapter_preflight']['error_type'], 'validation_error')
        self.assertEqual(audit_events[-1]['args'][2], 'federation_settlement_notice_rejected')

    def test_process_received_settlement_notice_respects_case_block(self):
        from federation import FederationEnvelopeClaims

        self.workspace.commitments.validate_commitment_for_settlement = (
            lambda commitment_id, **_kwargs: {'commitment_id': commitment_id, 'state': 'accepted'}
        )
        self.workspace._maybe_block_commitment_settlement = lambda *args, **kwargs: (
            {'case_id': 'case_live_demo', 'status': 'open', 'linked_commitment_id': 'cmt_live'},
            {'applied': True, 'warrant_id': 'war_live', 'court_review_state': 'stayed'},
        )
        self.workspace.commitments.record_settlement_ref = lambda *args, **kwargs: self.fail(
            'settlement ref should not be recorded'
        )
        self.workspace.commitments.settle_commitment = lambda *args, **kwargs: self.fail(
            'commitment should not settle'
        )
        self.workspace.log_event = lambda *args, **kwargs: None

        claims = FederationEnvelopeClaims(
            envelope_id='fed_live_blocked',
            source_host_id='host_peer',
            source_institution_id='org_peer',
            target_host_id='host_live',
            target_institution_id='org_founding',
            actor_type='service',
            actor_id='peer:host_peer',
            session_id='ses_peer',
            boundary_name='federation_gateway',
            identity_model='signed_host_service',
            message_type='settlement_notice',
            payload_hash='hash_live',
            warrant_id='war_live',
            commitment_id='cmt_live',
        )
        processing = self.workspace._process_received_federation_message(
            'org_founding',
            claims,
            {'receipt_id': 'fedrcpt_live', 'accepted_at': '2026-03-22T00:00:00Z'},
            payload={'tx_ref': 'tx_live'},
        )
        self.assertFalse(processing['applied'])
        self.assertEqual(processing['reason'], 'case_blocked')
        self.assertEqual(processing['state'], 'received')
        self.assertEqual(processing['case']['case_id'], 'case_live_demo')

    def test_deliver_federation_envelope_attaches_case_payload_on_preflight_block(self):
        from runtime_host import default_host_identity

        audit_events = []

        class FakeAuthority:
            def ensure_enabled(self):
                return True

        self.workspace._runtime_host_state = lambda _org_id: (
            default_host_identity(host_id='host_live', federation_enabled=True, peer_transport='https'),
            {'admitted_org_ids': ['org_founding']},
        )
        self.workspace._federation_authority = lambda _host: FakeAuthority()
        self.workspace.cases.blocking_peer_case = lambda target_host_id, **_kwargs: {
            'case_id': 'case_live_demo',
            'claim_type': 'misrouted_execution',
            'status': 'open',
            'target_host_id': target_host_id,
        }
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append({
            'args': args,
            'kwargs': kwargs,
        })

        with self.assertRaises(PermissionError) as exc_info:
            self.workspace._deliver_federation_envelope(
                'org_founding',
                'host_peer',
                'org_peer',
                'settlement_notice',
                payload={'tx_ref': '0xabc'},
                actor_type='user',
                actor_id='user_owner',
                session_id='ses_demo',
            )

        self.assertEqual(exc_info.exception.case_record['case_id'], 'case_live_demo')
        self.assertEqual(exc_info.exception.federation_peer['peer_host_id'], 'host_peer')
        self.assertEqual(exc_info.exception.federation_peer['reason'], 'peer_not_registered')
        self.assertEqual(audit_events[0]['args'][2], 'federation_case_blocked')

    def test_deliver_federation_envelope_skips_case_block_for_case_notice(self):
        from runtime_host import default_host_identity

        calls = []

        class FakeAuthority:
            def ensure_enabled(self):
                return True

            def snapshot(self, **kwargs):
                return {'host_id': 'host_live', 'enabled': True}

            def deliver(self, target_host_id, source_org_id, target_org_id, message_type, **kwargs):
                calls.append({
                    'target_host_id': target_host_id,
                    'source_org_id': source_org_id,
                    'target_org_id': target_org_id,
                    'message_type': message_type,
                    'kwargs': kwargs,
                })
                return {
                    'claims': {
                        'envelope_id': 'fed_case_send_1',
                        'target_host_id': target_host_id,
                        'target_institution_id': target_org_id,
                    },
                    'receipt': {
                        'receipt_id': 'fedrcpt_case_send_1',
                    },
                    'peer': {
                        'transport': 'https',
                    },
                }

        self.workspace._runtime_host_state = lambda _org_id: (
            default_host_identity(host_id='host_live', federation_enabled=True, peer_transport='https'),
            {'admitted_org_ids': ['org_founding']},
        )
        self.workspace._federation_authority = lambda _host: FakeAuthority()
        self.workspace.cases.blocking_peer_case = lambda target_host_id, **_kwargs: {
            'case_id': 'case_live_demo',
            'claim_type': 'misrouted_execution',
            'status': 'open',
            'target_host_id': target_host_id,
        }
        self.workspace.log_event = lambda *args, **kwargs: None

        with mock.patch.object(
            self.workspace,
            '_archive_delivery_with_witness_peers',
            return_value={
                'attempted': 1,
                'created': 1,
                'existing': 0,
                'failed': 0,
                'records': [{'peer_host_id': 'host_witness', 'created': True}],
            },
        ) as archive_mock:
            delivery, federation_state = self.workspace._deliver_federation_envelope(
                'org_founding',
                'host_peer',
                'org_peer',
                'case_notice',
                payload={'case_decision': 'resolve', 'source_case_id': 'case_live_demo'},
                actor_type='user',
                actor_id='user_owner',
                session_id='ses_demo',
            )

        self.assertEqual(delivery['claims']['envelope_id'], 'fed_case_send_1')
        self.assertEqual(calls[0]['message_type'], 'case_notice')
        self.assertEqual(federation_state['host_id'], 'host_live')
        self.assertEqual(delivery['witness_archive']['attempted'], 1)
        self.assertEqual(delivery['witness_archive']['created'], 1)
        archive_mock.assert_called_once()

    def test_deliver_federation_envelope_keeps_sender_warrant_pending_for_commitment_linked_execution_request(self):
        from runtime_host import default_host_identity

        calls = []

        class FakeAuthority:
            def ensure_enabled(self):
                return True

            def deliver(self, target_host_id, bound_org_id, target_org_id, message_type, **kwargs):
                return {
                    'claims': {
                        'envelope_id': 'fed_exec_demo',
                        'target_host_id': target_host_id,
                        'target_institution_id': target_org_id,
                    },
                    'receipt': {
                        'receipt_id': 'fedrcpt_demo',
                        'receiver_host_id': target_host_id,
                        'receiver_institution_id': target_org_id,
                    },
                    'peer': {'transport': 'https'},
                }

            def snapshot(self, **kwargs):
                return {
                    'enabled': True,
                    'boundary_name': 'federation_gateway',
                    'host_id': kwargs.get('bound_org_id', 'org_founding'),
                }

        self.workspace._runtime_host_state = lambda _org_id: (
            default_host_identity(
                host_id='host_live',
                federation_enabled=True,
                peer_transport='https',
                supported_boundaries=['workspace', 'federation_gateway'],
            ),
            {'admitted_org_ids': ['org_founding']},
        )
        self.workspace._federation_authority = lambda _host: FakeAuthority()
        self.workspace.commitments.validate_commitment_for_delivery = lambda *args, **kwargs: {
            'commitment_id': 'cmt_live',
            'delivery_refs': [],
        }
        self.workspace.validate_warrant_for_execution = lambda *args, **kwargs: {
            'warrant_id': 'war_sender',
            'execution_state': 'ready',
        }
        self.workspace.commitments.record_delivery_ref = lambda *args, **kwargs: {
            'recorded_at': '2026-03-22T00:00:00Z',
            'message_type': 'execution_request',
        }
        self.workspace.mark_warrant_executed = lambda *args, **kwargs: calls.append(kwargs)
        self.workspace.log_event = lambda *args, **kwargs: None

        delivery, _snapshot = self.workspace._deliver_federation_envelope(
            'org_founding',
            'host_peer',
            'org_peer',
            'execution_request',
            payload={'task': 'demo'},
            actor_type='service',
            actor_id='peer:host_peer',
            session_id='ses_demo',
            warrant_id='war_sender',
            commitment_id='cmt_live',
        )

        self.assertEqual(delivery['receipt']['receipt_id'], 'fedrcpt_demo')
        self.assertEqual(calls, [])

    def test_federation_manifest_reports_founding_locked_runtime(self):
        from runtime_host import default_host_identity

        self.workspace._load_workspace_credentials = lambda: (None, None, None, None)
        self.workspace._get_founding_org = lambda: (
            'org_founding',
            {'id': 'org_founding', 'slug': 'meridian', 'name': 'Meridian', 'lifecycle_state': 'founding'},
        )
        manifest = self.workspace._federation_manifest(
            self.workspace._resolve_workspace_context(),
            host_identity=default_host_identity(
                host_id='host_live',
                label='Meridian Live Host',
                federation_enabled=False,
                supported_boundaries=['workspace', 'cli', 'federation_gateway'],
            ),
            admission_registry={
                'source': 'derived_bound_default',
                'host_id': 'host_live',
                'institutions': {'org_founding': {'status': 'admitted'}},
                'admitted_org_ids': ['org_founding'],
            },
        )
        self.assertEqual(manifest['host_identity']['host_id'], 'host_live')
        self.assertEqual(manifest['admission']['management_mode'], 'founding_locked')
        self.assertFalse(manifest['federation']['enabled'])
        self.assertTrue(manifest['service_registry']['federation_gateway']['requires_warrant'])
        self.assertIn('witness_archive', manifest)
        self.assertFalse(manifest['witness_archive']['archive_enabled'])
        self.assertEqual(manifest['witness_archive']['archive_disabled_reason'], 'witness_host_only')

    def test_federation_snapshot_surfaces_disabled_witness_archive_on_live_host(self):
        from runtime_host import default_host_identity

        snap = self.workspace._federation_snapshot(
            'org_founding',
            host_identity=default_host_identity(
                host_id='host_live',
                label='Meridian Live Host',
                federation_enabled=False,
                supported_boundaries=['workspace', 'cli', 'federation_gateway'],
            ),
            admission_registry={
                'source': 'derived_bound_default',
                'host_id': 'host_live',
                'institutions': {'org_founding': {'status': 'admitted'}},
                'admitted_org_ids': ['org_founding'],
            },
        )
        self.assertIn('witness_archive', snap)
        self.assertFalse(snap['witness_archive']['archive_enabled'])
        self.assertEqual(snap['witness_archive']['management_mode'], 'host_role_unavailable')
        self.assertEqual(snap['witness_archive']['archive_disabled_reason'], 'witness_host_only')

    def test_federation_witness_archive_route_fails_closed_on_non_witness_host(self):
        calls = []

        class FakeHandler:
            def __init__(self):
                self.path = '/api/federation/witness/archive'
                self.headers = _Headers({'Content-Length': '0'})
                self.response = None
                self.body_read = False

            def _require_auth(self, path):
                calls.append(('require_auth', path))
                return True

            def _read_body(self):
                self.body_read = True
                raise AssertionError('route should fail closed before body parsing')

            def _json(self, data, status=200):
                self.response = {'data': data, 'status': status}
                return self.response

            def _service_unavailable(self, *args, **kwargs):
                raise AssertionError('route should fail closed with JSON response')

        handler = FakeHandler()
        with mock.patch.object(
            self.workspace,
            '_resolve_workspace_context',
            return_value=types.SimpleNamespace(org_id='org_founding'),
        ), mock.patch.object(
            self.workspace,
            '_runtime_host_state',
            return_value=(
                __import__('runtime_host').default_host_identity(
                    host_id='host_live',
                    federation_enabled=False,
                    peer_transport='none',
                    supported_boundaries=['workspace', 'cli', 'federation_gateway'],
                ),
                {'admitted_org_ids': ['org_founding']},
            ),
        ):
            result = self.workspace.WorkspaceHandler.do_POST(handler)
        self.assertEqual(calls, [('require_auth', '/api/federation/witness/archive')])
        self.assertEqual(handler.response['status'], 503)
        self.assertFalse(handler.body_read)
        self.assertEqual(handler.response['data']['witness_archive']['archive_disabled_reason'], 'witness_host_only')
        self.assertIn('Witness archive is disabled', handler.response['data']['error'])
        self.assertEqual(result, handler.response)

    def test_alerts_route_returns_alert_queue_snapshot(self):
        calls = []

        class FakeHandler:
            def __init__(self):
                self.path = '/api/alerts'
                self.headers = _Headers({'Content-Length': '0'})
                self.response = None

            def _require_auth(self, path):
                calls.append(('require_auth', path))
                return True

            def _json(self, data, status=200):
                self.response = {'data': data, 'status': status}
                return self.response

            def _service_unavailable(self, *args, **kwargs):
                raise AssertionError('alerts route should return JSON queue snapshot')

            def _session_claims_from_request(self, expected_org_id=None):
                return None

        handler = FakeHandler()
        with mock.patch.object(
            self.workspace,
            '_resolve_workspace_context',
            return_value=types.SimpleNamespace(org_id='org_founding', org={}, context_source='configured_org'),
        ), mock.patch.object(
            self.workspace,
            '_enforce_request_context',
            return_value={'mode': 'process_bound'},
        ), mock.patch.object(
            self.workspace,
            '_resolve_auth_context',
            return_value={'enabled': True, 'role': 'owner'},
        ), mock.patch.object(
            self.workspace.alerting,
            'alert_queue_snapshot',
            return_value={
                'log_path': '/tmp/slo_alert_log.jsonl',
                'org_id': 'org_founding',
                'queue_count': 1,
                'pending_delivery_count': 1,
                'delivered_count': 0,
                'queue': [{'delivery_state': 'dry_run'}],
                'db': {'status': 'present'},
            },
        ):
            result = self.workspace.WorkspaceHandler.do_GET(handler)
        self.assertEqual(calls, [('require_auth', '/api/alerts')])
        self.assertEqual(handler.response['status'], 200)
        self.assertEqual(handler.response['data']['queue_count'], 1)
        self.assertEqual(handler.response['data']['pending_delivery_count'], 1)
        self.assertEqual(result, handler.response)

    def test_alerts_dispatch_route_acknowledges_queue_without_claiming_delivery(self):
        calls = []

        class FakeHandler:
            def __init__(self):
                self.path = '/api/alerts/dispatch'
                self.headers = _Headers({'Content-Length': '0'})
                self.response = None

            def _require_auth(self, path):
                calls.append(('require_auth', path))
                return True

            def _json(self, data, status=200):
                self.response = {'data': data, 'status': status}
                return self.response

            def _service_unavailable(self, *args, **kwargs):
                raise AssertionError('alerts dispatch route should return JSON')

            def _session_claims_from_request(self, expected_org_id=None):
                return None

            def _read_body(self):
                return {}

        handler = FakeHandler()
        with mock.patch.object(
            self.workspace,
            '_resolve_workspace_context',
            return_value=types.SimpleNamespace(org_id='org_founding', org={}, context_source='configured_org'),
        ), mock.patch.object(
            self.workspace,
            '_enforce_request_context',
            return_value={'mode': 'process_bound'},
        ), mock.patch.object(
            self.workspace,
            '_resolve_auth_context',
            return_value={'enabled': True, 'role': 'owner'},
        ), mock.patch.object(
            self.workspace.alerting,
            'dispatch_queued_alerts',
            return_value={
                'log_path': '/tmp/slo_alert_log.jsonl',
                'org_id': 'org_founding',
                'dispatch_mode': 'inspect_only',
                'dispatched_count': 1,
                'acknowledged_count': 1,
                'pending_delivery_count': 1,
                'delivered_count': 0,
                'queue': [{'dispatch_state': 'acknowledged_pending'}],
                'result': 'ignored',
            },
        ):
            result = self.workspace.WorkspaceHandler.do_POST(handler)
        self.assertEqual(calls, [('require_auth', '/api/alerts/dispatch')])
        self.assertEqual(handler.response['status'], 200)
        self.assertEqual(handler.response['data']['result']['dispatch_mode'], 'inspect_only')
        self.assertEqual(handler.response['data']['result']['acknowledged_count'], 1)
        self.assertEqual(result, handler.response)

    def test_runtime_proof_route_returns_live_runtime_snapshot(self):
        calls = []

        class FakeHandler:
            def __init__(self):
                self.path = '/api/runtime-proof'
                self.headers = _Headers({'Content-Length': '0'})
                self.response = None

            def _require_auth(self, path):
                calls.append(('require_auth', path))
                return True

            def _json(self, data, status=200):
                self.response = {'data': data, 'status': status}
                return self.response

            def _service_unavailable(self, *args, **kwargs):
                raise AssertionError('runtime-proof route should return JSON proof snapshot')

            def _session_claims_from_request(self, expected_org_id=None):
                return None

        handler = FakeHandler()
        with mock.patch.object(
            self.workspace,
            '_resolve_workspace_context',
            return_value=types.SimpleNamespace(org_id='org_founding', org={}, context_source='configured_org'),
        ), mock.patch.object(
            self.workspace,
            '_enforce_request_context',
            return_value={'mode': 'process_bound'},
        ), mock.patch.object(
            self.workspace,
            '_resolve_auth_context',
            return_value={'enabled': True, 'role': 'owner'},
        ), mock.patch.object(
            self.workspace,
            'loom_runtime_proof',
            types.SimpleNamespace(
                collect_loom_runtime_proof=lambda include_service_probe=False: {
                    'runtime_id': 'loom_native',
                    'proof_type': 'live_single_host_loom_deployment',
                    'checked_at': '2026-03-22T00:00:00Z',
                    'deployment_truth': {'scope': 'single_host', 'generic_runtime_claim': False},
                    'health': {
                        'health_ok': True,
                        'agent_count': 2,
                        'session_total': 5,
                        'agents': [{'handle': 'main'}, {'handle': 'atlas'}],
                        'heartbeat': {'interval': '30m', 'primary_agent': 'main'},
                        'telegram': {'ok': True},
                    },
                    'service_probe': {'checked': True, 'ok': True, 'output': 'service running', 'status': 'running', 'health': 'healthy', 'transport': 'socket+http'},
                    'governed_agents': [],
                    'handle_overlap': ['main'],
                    'handle_gap': [],
                },
                public_loom_runtime_receipt=lambda proof, bound_org_id=None: {
                    'runtime_id': 'loom_native',
                    'bound_org_id': bound_org_id,
                    'runtime_health': {'health_ok': True, 'service_probe_ok': True},
                    'runtime_inventory': {'runtime_agent_names': ['main', 'atlas'], 'runtime_agent_count': 2},
                    'governed_agent_summary': {'declared_bound_agent_count': 1},
                },
            ),
        ):
            result = self.workspace.WorkspaceHandler.do_GET(handler)
        self.assertEqual(calls, [('require_auth', '/api/runtime-proof')])
        self.assertEqual(handler.response['status'], 200)
        self.assertTrue(handler.response['data']['runtime_health']['health_ok'])
        self.assertEqual(handler.response['data']['bound_org_id'], 'org_founding')
        self.assertEqual(result, handler.response)

    def test_admission_snapshot_reports_founding_lock(self):
        from runtime_host import default_host_identity
        host = default_host_identity(
            host_id='host_live',
            label='Meridian Live Host',
            federation_enabled=False,
            supported_boundaries=['workspace', 'cli', 'federation_gateway'],
        )
        snap = self.workspace._admission_snapshot(
            'org_founding',
            host_identity=host,
            admission_registry={'source': 'derived_bound_default', 'admitted_org_ids': ['org_founding'], 'institutions': {'org_founding': {'status': 'admitted'}}},
        )
        self.assertEqual(snap['management_mode'], 'founding_locked')
        self.assertFalse(snap['mutation_enabled'])
        self.assertEqual(snap['mutation_disabled_reason'], 'single_institution_deployment')

    def test_mutate_admission_is_rejected_on_live(self):
        with self.assertRaises(PermissionError):
            self.workspace._mutate_admission('org_founding', 'admit', 'org_other')

    def test_accept_federation_request_fails_closed_when_disabled(self):
        from federation import FederationAuthority, FederationUnavailable
        from runtime_host import default_host_identity

        self.workspace.FEDERATION_SIGNING_SECRET = 'alpha-secret'
        self.workspace.load_host_identity = lambda *args, **kwargs: default_host_identity(
            host_id='host_live',
            label='Meridian Live Host',
            federation_enabled=False,
            peer_transport='none',
            supported_boundaries=['workspace', 'cli', 'federation_gateway'],
        )
        self.workspace.load_admission_registry = lambda *args, **kwargs: {
            'source': 'derived_bound_default',
            'host_id': 'host_live',
            'institutions': {'org_founding': {'status': 'admitted'}},
            'admitted_org_ids': ['org_founding'],
        }
        sender = FederationAuthority(
            default_host_identity(
                host_id='host_live',
                federation_enabled=True,
                peer_transport='https',
            ),
            signing_secret='alpha-secret',
        )
        envelope = sender.issue(
            'org_founding',
            'host_live',
            'org_founding',
            'execution_request',
            payload={'task': 'demo'},
        )
        with self.assertRaises(FederationUnavailable):
            self.workspace._accept_federation_request(
                'org_founding',
                envelope,
                payload={'task': 'demo'},
            )

    def test_deliver_federation_envelope_fails_closed_when_disabled(self):
        from federation import FederationUnavailable
        from runtime_host import default_host_identity

        self.workspace.load_host_identity = lambda *args, **kwargs: default_host_identity(
            host_id='host_live',
            label='Meridian Live Host',
            federation_enabled=False,
            peer_transport='none',
            supported_boundaries=['workspace', 'cli', 'federation_gateway'],
        )
        self.workspace.load_admission_registry = lambda *args, **kwargs: {
            'source': 'derived_bound_default',
            'host_id': 'host_live',
            'institutions': {'org_founding': {'status': 'admitted'}},
            'admitted_org_ids': ['org_founding'],
        }

        with self.assertRaises(FederationUnavailable):
            self.workspace._deliver_federation_envelope(
                'org_founding',
                'host_peer',
                'org_peer',
                'execution_request',
                payload={'task': 'demo'},
                actor_type='user',
                actor_id='user_owner',
                session_id='ses_demo',
            )


if __name__ == '__main__':
    unittest.main()
