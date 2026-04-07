#!/usr/bin/env python3
import importlib.util
import os
import unittest
from unittest import mock
from urllib.parse import urlparse


ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
WORKSPACE_PY = os.path.join(ROOT, 'workspace.py')


def _load_workspace(name):
    spec = importlib.util.spec_from_file_location(name, WORKSPACE_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class WorkspaceContextTests(unittest.TestCase):
    def setUp(self):
        self.workspace = _load_workspace('kernel_workspace_context_test')
        self.orig_workspace_org_id = self.workspace.WORKSPACE_ORG_ID
        self.orig_runtime_host_identity_file = self.workspace.RUNTIME_HOST_IDENTITY_FILE
        self.orig_runtime_admission_file = self.workspace.RUNTIME_ADMISSION_FILE
        self.orig_federation_peers_file = self.workspace.FEDERATION_PEERS_FILE
        self.orig_federation_replay_file = self.workspace.FEDERATION_REPLAY_FILE
        self.orig_federation_signing_secret = self.workspace.FEDERATION_SIGNING_SECRET
        self.orig_load_orgs = self.workspace.load_orgs
        self.orig_load_workspace_credentials = self.workspace._load_workspace_credentials
        self.orig_load_host_identity = self.workspace.load_host_identity
        self.orig_load_admission_registry = self.workspace.load_admission_registry
        self.orig_runtime_host_state = self.workspace._runtime_host_state
        self.orig_federation_authority = self.workspace._federation_authority
        self.orig_refresh_peer_registry_entry = self.workspace.refresh_peer_registry_entry
        self.orig_load_peer_registry = self.workspace.load_peer_registry
        self.orig_log_event = self.workspace.log_event
        self.orig_list_warrants = self.workspace.list_warrants
        self.orig_get_warrant = self.workspace.get_warrant
        self.orig_issue_warrant = self.workspace.issue_warrant
        self.orig_review_warrant = self.workspace.review_warrant
        self.orig_commitment_summary = self.workspace.commitment_summary
        self.orig_list_commitments = self.workspace.list_commitments
        self.orig_validate_commitment_for_delivery = self.workspace.validate_commitment_for_delivery
        self.orig_validate_commitment_for_settlement = self.workspace.validate_commitment_for_settlement
        self.orig_record_delivery_ref = self.workspace.record_delivery_ref
        self.orig_record_settlement_ref = self.workspace.record_settlement_ref
        self.orig_settle_commitment = self.workspace.settle_commitment
        self.orig_case_summary = self.workspace.case_summary
        self.orig_list_cases = self.workspace.list_cases
        self.orig_blocking_commitment_ids = self.workspace.blocking_commitment_ids
        self.orig_blocked_peer_host_ids = self.workspace.blocked_peer_host_ids
        self.orig_blocking_commitment_case = self.workspace.blocking_commitment_case
        self.orig_blocking_peer_case = self.workspace.blocking_peer_case
        self.orig_maybe_block_commitment_settlement = self.workspace._maybe_block_commitment_settlement
        self.orig_set_peer_trust_state = self.workspace.set_peer_trust_state
        self.orig_ensure_case_for_delivery_failure = self.workspace.ensure_case_for_delivery_failure
        self.orig_summarize_inbox_entries = self.workspace.summarize_inbox_entries
        self.orig_get_execution_job = self.workspace.get_execution_job
        self.orig_get_execution_job_by_local_warrant = self.workspace.get_execution_job_by_local_warrant
        self.orig_list_execution_jobs = self.workspace.list_execution_jobs
        self.orig_execution_job_summary = self.workspace.execution_job_summary
        self.orig_sync_execution_job_for_local_warrant = self.workspace.sync_execution_job_for_local_warrant
        self.orig_upsert_execution_job = self.workspace.upsert_execution_job
        self.orig_list_witness_observations = self.workspace.list_witness_observations
        self.orig_witness_archive_summary = self.workspace.witness_archive_summary
        self.orig_settlement_adapter_readiness_snapshot = self.workspace.settlement_adapter_readiness_snapshot
        self.orig_payout_plan_preview_queue_snapshot = self.workspace._payout_plan_preview_queue_snapshot

    def tearDown(self):
        self.workspace.WORKSPACE_ORG_ID = self.orig_workspace_org_id
        self.workspace.RUNTIME_HOST_IDENTITY_FILE = self.orig_runtime_host_identity_file
        self.workspace.RUNTIME_ADMISSION_FILE = self.orig_runtime_admission_file
        self.workspace.FEDERATION_PEERS_FILE = self.orig_federation_peers_file
        self.workspace.FEDERATION_REPLAY_FILE = self.orig_federation_replay_file
        self.workspace.FEDERATION_SIGNING_SECRET = self.orig_federation_signing_secret
        self.workspace.load_orgs = self.orig_load_orgs
        self.workspace._load_workspace_credentials = self.orig_load_workspace_credentials
        self.workspace.load_host_identity = self.orig_load_host_identity
        self.workspace.load_admission_registry = self.orig_load_admission_registry
        self.workspace._runtime_host_state = self.orig_runtime_host_state
        self.workspace._federation_authority = self.orig_federation_authority
        self.workspace.refresh_peer_registry_entry = self.orig_refresh_peer_registry_entry
        self.workspace.load_peer_registry = self.orig_load_peer_registry
        self.workspace.log_event = self.orig_log_event
        self.workspace.list_warrants = self.orig_list_warrants
        self.workspace.get_warrant = self.orig_get_warrant
        self.workspace.issue_warrant = self.orig_issue_warrant
        self.workspace.review_warrant = self.orig_review_warrant
        self.workspace.commitment_summary = self.orig_commitment_summary
        self.workspace.list_commitments = self.orig_list_commitments
        self.workspace.validate_commitment_for_delivery = self.orig_validate_commitment_for_delivery
        self.workspace.validate_commitment_for_settlement = self.orig_validate_commitment_for_settlement
        self.workspace.record_delivery_ref = self.orig_record_delivery_ref
        self.workspace.record_settlement_ref = self.orig_record_settlement_ref
        self.workspace.settle_commitment = self.orig_settle_commitment
        self.workspace.case_summary = self.orig_case_summary
        self.workspace.list_cases = self.orig_list_cases
        self.workspace.blocking_commitment_ids = self.orig_blocking_commitment_ids
        self.workspace.blocked_peer_host_ids = self.orig_blocked_peer_host_ids
        self.workspace.blocking_commitment_case = self.orig_blocking_commitment_case
        self.workspace.blocking_peer_case = self.orig_blocking_peer_case
        self.workspace._maybe_block_commitment_settlement = self.orig_maybe_block_commitment_settlement
        self.workspace.set_peer_trust_state = self.orig_set_peer_trust_state
        self.workspace.ensure_case_for_delivery_failure = self.orig_ensure_case_for_delivery_failure
        self.workspace.summarize_inbox_entries = self.orig_summarize_inbox_entries
        self.workspace.get_execution_job = self.orig_get_execution_job
        self.workspace.get_execution_job_by_local_warrant = self.orig_get_execution_job_by_local_warrant
        self.workspace.list_execution_jobs = self.orig_list_execution_jobs
        self.workspace.execution_job_summary = self.orig_execution_job_summary
        self.workspace.sync_execution_job_for_local_warrant = self.orig_sync_execution_job_for_local_warrant
        self.workspace.upsert_execution_job = self.orig_upsert_execution_job
        self.workspace.list_witness_observations = self.orig_list_witness_observations
        self.workspace.witness_archive_summary = self.orig_witness_archive_summary
        self.workspace.settlement_adapter_readiness_snapshot = self.orig_settlement_adapter_readiness_snapshot
        self.workspace._payout_plan_preview_queue_snapshot = self.orig_payout_plan_preview_queue_snapshot

    def test_configured_org_binds_process_context(self):
        self.workspace._load_workspace_credentials = lambda: (None, None, None, None)
        self.workspace.WORKSPACE_ORG_ID = 'org_b'
        self.workspace.load_orgs = lambda: {
            'organizations': {
                'org_a': {'id': 'org_a', 'slug': 'a', 'name': 'A'},
                'org_b': {'id': 'org_b', 'slug': 'b', 'name': 'B'},
            }
        }
        ctx = self.workspace._resolve_workspace_context()
        self.assertEqual(ctx.org_id, 'org_b')
        self.assertEqual(ctx.org.get('slug'), 'b')
        self.assertEqual(ctx.context_source, 'configured_org')
        self.assertEqual(ctx.boundary.name, 'workspace')

    def test_credential_scoped_org_binds_process_context(self):
        self.workspace._load_workspace_credentials = lambda: ('owner', 'secret', 'org_b', None)
        self.workspace.load_orgs = lambda: {
            'organizations': {
                'org_a': {'id': 'org_a', 'slug': 'a', 'name': 'A'},
                'org_b': {'id': 'org_b', 'slug': 'b', 'name': 'B'},
            }
        }
        ctx = self.workspace._resolve_workspace_context()
        self.assertEqual(ctx.org_id, 'org_b')
        self.assertEqual(ctx.org.get('slug'), 'b')
        self.assertEqual(ctx.context_source, 'credentials_org')
        self.assertEqual(ctx.boundary.identity_model, 'session')

    def test_credential_scope_conflict_is_rejected(self):
        self.workspace._load_workspace_credentials = lambda: ('owner', 'secret', 'org_a', None)
        self.workspace.WORKSPACE_ORG_ID = 'org_b'
        with self.assertRaises(RuntimeError):
            self.workspace._resolve_workspace_context()

    def test_request_override_must_match_bound_org(self):
        with self.assertRaises(ValueError):
            self.workspace._enforce_request_context(
                urlparse('/api/status?org_id=org_other'),
                _Headers(),
                'org_a',
            )

        context = self.workspace._enforce_request_context(
            urlparse('/api/status?org_id=org_a'),
            _Headers({'X-Meridian-Org-Id': 'org_a'}),
            'org_a',
        )
        self.assertEqual(context['requested_org_id'], 'org_a')
        self.assertEqual(context['bound_org_id'], 'org_a')
        self.assertEqual(context['effective_org_id'], 'org_a')
        self.assertEqual(context['route_state'], 'matched')
        self.assertEqual(context['route_reason'], 'request_org_matches_bound_institution')

    def test_auth_context_reports_credential_binding(self):
        self.workspace._load_workspace_credentials = lambda: ('owner', 'secret', 'org_a', None)
        auth = self.workspace._resolve_auth_context('org_a')
        self.assertEqual(auth['mode'], 'credential_bound')
        self.assertEqual(auth['org_id'], 'org_a')
        self.assertEqual(auth['actor_id'], 'workspace_user:owner')

    def test_routing_planner_classifies_local_remote_and_blocked_orgs(self):
        host = self.workspace.load_host_identity('missing')
        host.federation_enabled = True
        peer_registry = {
            'peers': {
                'host_beta': self.workspace.FederationPeer(
                    host_id='host_beta',
                    label='Beta Host',
                    trust_state='trusted',
                    endpoint_url='http://127.0.0.1:19001',
                    admitted_org_ids=['org_remote'],
                ),
                'host_gamma': self.workspace.FederationPeer(
                    host_id='host_gamma',
                    label='Gamma Host',
                    trust_state='suspended',
                    endpoint_url='http://127.0.0.1:19002',
                    admitted_org_ids=['org_suspended'],
                ),
            },
        }
        snapshot = self.workspace._routing_planner_snapshot(
            'org_local',
            requested_org_ids=['org_local', 'org_remote', 'org_suspended', 'org_unknown'],
            host_identity=host,
            admission_registry={'admitted_org_ids': ['org_local']},
            peer_registry=peer_registry,
            org_registry={'org_local': {}, 'org_remote': {}, 'org_suspended': {}},
        )
        decisions = {item['requested_org_id']: item for item in snapshot['decisions']}
        self.assertEqual(snapshot['summary'], {'total': 4, 'local': 1, 'remote': 1, 'blocked': 2})
        self.assertEqual(decisions['org_local']['route_kind'], 'local')
        self.assertEqual(decisions['org_local']['route_reason'], 'request_targets_bound_institution')
        self.assertEqual(decisions['org_remote']['route_kind'], 'remote')
        self.assertEqual(decisions['org_remote']['target_host_id'], 'host_beta')
        self.assertEqual(decisions['org_remote']['target_endpoint_url'], 'http://127.0.0.1:19001')
        self.assertEqual(decisions['org_suspended']['route_kind'], 'blocked')
        self.assertEqual(decisions['org_suspended']['route_reason'], 'matching_peer_not_trusted')
        self.assertEqual(decisions['org_unknown']['route_kind'], 'blocked')
        self.assertEqual(decisions['org_unknown']['route_reason'], 'unknown_requested_institution')

    def test_routing_handoff_preview_bridges_remote_planner_entries(self):
        host = self.workspace.load_host_identity('missing')
        host.federation_enabled = True
        planner = {
            'bound_org_id': 'org_local',
            'host_id': host.host_id,
            'host_federation_enabled': True,
            'requested_org_ids': ['org_local', 'org_remote', 'org_blocked'],
            'summary': {'total': 3, 'local': 1, 'remote': 1, 'blocked': 1},
            'decisions': [
                {
                    'requested_org_id': 'org_local',
                    'route_state': 'local',
                    'route_kind': 'local',
                    'route_reason': 'request_targets_bound_institution',
                    'target_host_id': '',
                    'target_endpoint_url': '',
                    'peer_host_id': '',
                    'peer_label': '',
                    'peer_trust_state': '',
                },
                {
                    'requested_org_id': 'org_remote',
                    'route_state': 'remote',
                    'route_kind': 'remote',
                    'route_reason': 'trusted_peer_can_serve_requested_institution',
                    'target_host_id': 'host_beta',
                    'target_endpoint_url': 'http://127.0.0.1:19001',
                    'peer_host_id': 'host_beta',
                    'peer_label': 'Beta Host',
                    'peer_trust_state': 'trusted',
                },
                {
                    'requested_org_id': 'org_blocked',
                    'route_state': 'blocked',
                    'route_kind': 'blocked',
                    'route_reason': 'unknown_requested_institution',
                    'target_host_id': '',
                    'target_endpoint_url': '',
                    'peer_host_id': '',
                    'peer_label': '',
                    'peer_trust_state': '',
                },
            ],
        }
        self.workspace._routing_planner_snapshot = lambda *args, **kwargs: planner

        with mock.patch.object(self.workspace, 'upsert_handoff_preview', return_value={'state': 'previewed'}) as upsert:
            preview = self.workspace._routing_handoff_preview_snapshot(
                'org_local',
                host_identity=host,
                admission_registry={'admitted_org_ids': ['org_local']},
                peer_registry={'peers': {}},
                org_registry={'org_local': {}, 'org_remote': {}, 'org_blocked': {}},
            )

        self.assertEqual(preview['summary'], {'total': 3, 'local': 1, 'remote': 1, 'blocked': 1, 'remote_previewed': 1})
        remote = next(item for item in preview['handoff_candidates'] if item['requested_org_id'] == 'org_remote')
        self.assertEqual(remote['handoff_state'], 'previewed')
        self.assertTrue(remote['dispatch_ready'])
        self.assertTrue(remote['handoff_queue_recorded'])
        self.assertEqual(remote['handoff_queue_state'], 'previewed')
        self.assertFalse(remote['remote_execution_claimed'])
        self.assertEqual(remote['dispatch_paths']['send'], '/api/federation/send')
        self.assertEqual(remote['draft_execution_request']['target_host_id'], 'host_beta')
        self.assertEqual(remote['draft_execution_request']['target_institution_id'], 'org_remote')
        self.assertTrue(remote['handoff_id'].startswith('fhdp_'))
        blocked = next(item for item in preview['handoff_candidates'] if item['requested_org_id'] == 'org_blocked')
        self.assertEqual(blocked['handoff_state'], 'blocked')
        self.assertFalse(blocked['dispatch_ready'])
        upsert.assert_called_once()
        called_org_id, called_preview = upsert.call_args.args
        self.assertEqual(called_org_id, 'org_local')
        self.assertEqual(called_preview['handoff_id'], remote['handoff_id'])
        self.assertEqual(called_preview['requested_org_id'], 'org_remote')
        self.assertEqual(called_preview['draft_execution_request']['target_host_id'], 'host_beta')

    def test_federation_snapshot_includes_handoff_dispatch_queue(self):
        host = self.workspace.load_host_identity('missing')
        host.federation_enabled = True

        class _AuthorityStub:
            def snapshot(self, **kwargs):
                return {'host_id': host.host_id, 'peers': [], 'admitted_org_ids': ['org_local']}

        with mock.patch.object(self.workspace, '_federation_authority', return_value=_AuthorityStub()), \
             mock.patch.object(self.workspace, '_routing_handoff_preview_snapshot', return_value={'summary': {'total': 0}, 'handoff_candidates': []}), \
             mock.patch.object(self.workspace, '_handoff_dispatch_queue_snapshot', return_value={'summary': {'total': 1}, 'handoff_dispatch_records': [{'dispatch_id': 'fhdp_demo'}]}), \
             mock.patch.object(self.workspace, '_witness_archive_snapshot', return_value={'summary': {'total': 0}, 'witness_observations': []}):
            snapshot = self.workspace._federation_snapshot(
                'org_local',
                host_identity=host,
                admission_registry={'admitted_org_ids': ['org_local']},
                peer_registry={'peers': {}},
            )

        self.assertIn('handoff_dispatch_queue', snapshot)
        self.assertEqual(snapshot['handoff_dispatch_queue']['summary']['total'], 1)
        self.assertEqual(snapshot['handoff_dispatch_queue']['handoff_dispatch_records'][0]['dispatch_id'], 'fhdp_demo')

    def test_auth_context_prefers_explicit_user_id(self):
        self.workspace._load_workspace_credentials = lambda: ('owner', 'secret', 'org_a', 'user_meridian_owner')
        self.workspace.load_orgs = lambda: {
            'organizations': {
                'org_a': {
                    'id': 'org_a',
                    'slug': 'a',
                    'name': 'A',
                    'owner_id': 'user_meridian_owner',
                    'members': [{'user_id': 'user_meridian_owner', 'role': 'owner'}],
                },
            }
        }
        auth = self.workspace._resolve_auth_context('org_a')
        self.assertEqual(auth['actor_id'], 'user_meridian_owner')
        self.assertEqual(auth['actor_source'], 'credentials')
        self.assertEqual(auth['role'], 'owner')

    def test_auth_context_resolves_owner_alias_role(self):
        self.workspace._load_workspace_credentials = lambda: ('owner', 'secret', 'org_a', None)
        self.workspace.load_orgs = lambda: {
            'organizations': {
                'org_a': {
                    'id': 'org_a',
                    'slug': 'a',
                    'name': 'A',
                    'owner_id': 'user_owner',
                    'members': [{'user_id': 'user_owner', 'role': 'owner'}],
                },
            }
        }
        auth = self.workspace._resolve_auth_context('org_a')
        self.assertEqual(auth['user_id'], 'user_owner')
        self.assertEqual(auth['role'], 'owner')
        self.assertEqual(auth['actor_source'], 'owner_alias')

    def test_mutation_authorization_requires_admin_for_kill_switch(self):
        auth = {'enabled': True, 'role': 'member'}
        with self.assertRaises(PermissionError):
            self.workspace._enforce_mutation_authorization(auth, 'org_a', '/api/authority/kill-switch')

    def test_mutation_authorization_allows_member_request(self):
        auth = {'enabled': True, 'role': 'member'}
        required = self.workspace._enforce_mutation_authorization(auth, 'org_a', '/api/authority/request')
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
        self.assertTrue(permissions['/api/subscriptions/add']['allowed'])
        self.assertTrue(permissions['/api/subscriptions/record-delivery']['allowed'])
        self.assertFalse(permissions['/api/accounting/draw']['allowed'])
        self.assertEqual(permissions['/api/accounting/draw']['required_role'], 'owner')
        self.assertEqual(
            permissions['/api/treasury/settlement-adapters/preflight']['required_role'],
            'member',
        )
        self.assertEqual(permissions['/api/payouts/execute']['required_role'], 'owner')
        self.assertTrue(permissions['/api/commitments/propose']['allowed'])
        self.assertTrue(permissions['/api/commitments/accept']['allowed'])
        self.assertTrue(permissions['/api/cases/open']['allowed'])
        self.assertTrue(permissions['/api/cases/resolve']['allowed'])
        self.assertTrue(permissions['/api/federation/send']['allowed'])
        self.assertTrue(permissions['/api/federation/execution-jobs/execute']['allowed'])
        self.assertEqual(permissions['/api/federation/execution-jobs/execute']['required_role'], 'admin')
        self.assertTrue(permissions['/api/federation/handoff-preview-queue/acknowledge']['allowed'])
        self.assertEqual(permissions['/api/federation/handoff-preview-queue/acknowledge']['required_role'], 'admin')
        self.assertTrue(permissions['/api/federation/handoff-dispatch-queue/run']['allowed'])
        self.assertEqual(permissions['/api/federation/handoff-dispatch-queue/run']['required_role'], 'admin')
        self.assertFalse(permissions['/api/federation/peers/refresh']['allowed'])
        self.assertEqual(permissions['/api/federation/peers/refresh']['required_role'], 'owner')

    def test_payout_snapshot_surfaces_settlement_adapters(self):
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
            'org_a',
            host_supported_adapters=['internal_ledger'],
        )
        self.assertEqual(snapshot['settlement_adapter_summary']['default_payout_adapter'], 'internal_ledger')
        self.assertEqual(snapshot['settlement_adapter_summary']['host_supported_adapters'], ['internal_ledger'])
        self.assertEqual(len(snapshot['settlement_adapters']), 2)

    def test_settlement_adapter_readiness_snapshot_delegates_host_support(self):
        self.workspace.settlement_adapter_readiness_snapshot = lambda org_id=None, host_supported_adapters=None: {
            'bound_org_id': org_id,
            'host_supported_adapters': list(host_supported_adapters or []),
            'summary': {'ready': 1},
            'ready_adapter_ids': ['internal_ledger'],
            'blocked_adapter_ids': ['base_usdc_x402'],
            'adapters': [{'adapter_id': 'internal_ledger'}],
        }
        snapshot = self.workspace._settlement_adapter_readiness_snapshot(
            'org_a',
            host_supported_adapters=['internal_ledger'],
        )
        self.assertEqual(snapshot['bound_org_id'], 'org_a')
        self.assertEqual(snapshot['host_supported_adapters'], ['internal_ledger'])
        self.assertEqual(snapshot['ready_adapter_ids'], ['internal_ledger'])
        self.assertEqual(snapshot['blocked_adapter_ids'], ['base_usdc_x402'])
        self.assertEqual(snapshot['summary'], {'ready': 1})

    def test_api_status_exposes_runtime_core(self):
        from runtime_host import default_host_identity
        self.workspace._load_workspace_credentials = lambda: ('owner', 'secret', 'org_a', 'user_owner')
        self.workspace.load_orgs = lambda: {
            'organizations': {
                'org_a': {
                    'id': 'org_a',
                    'slug': 'a',
                    'name': 'A',
                    'owner_id': 'user_owner',
                    'members': [{'user_id': 'user_owner', 'role': 'owner'}],
                    'lifecycle_state': 'active',
                    'policy_defaults': {},
                },
                'org_b': {
                    'id': 'org_b',
                    'slug': 'b',
                    'name': 'B',
                    'owner_id': 'user_owner',
                    'members': [{'user_id': 'user_owner', 'role': 'owner'}],
                    'lifecycle_state': 'active',
                    'policy_defaults': {},
                },
                'org_c': {
                    'id': 'org_c',
                    'slug': 'c',
                    'name': 'C',
                    'owner_id': 'user_owner',
                    'members': [{'user_id': 'user_owner', 'role': 'owner'}],
                    'lifecycle_state': 'active',
                    'policy_defaults': {},
                },
            }
        }
        self.workspace.load_registry = lambda: {
            'agents': {
                'agent_atlas_a': {
                    'id': 'agent_atlas_a',
                    'org_id': 'org_a',
                    'name': 'Atlas',
                    'role': 'analyst',
                    'purpose': 'Research',
                    'economy_key': 'atlas',
                    'runtime_binding': {
                        'runtime_id': 'local_kernel',
                        'runtime_label': 'Local Kernel Runtime',
                    },
                    'rollout_state': 'active',
                    'reputation_units': 100,
                    'authority_units': 100,
                    'last_active_at': '2026-03-21T00:00:00Z',
                    'risk_state': 'nominal',
                    'lifecycle_state': 'active',
                    'budget': {'max_per_run_usd': 1.0},
                    'scopes': ['execute'],
                },
            }
        }
        self.workspace._load_queue = lambda org_id: {
            'kill_switch': False,
            'pending_approvals': {},
            'delegations': {},
        }
        self.workspace.treasury_snapshot = lambda org_id: {}
        self.workspace._load_records = lambda org_id: {'violations': {}, 'appeals': {}}
        self.workspace.list_warrants = lambda org_id=None, **_kwargs: [
            {
                'warrant_id': 'war_demo',
                'court_review_state': 'approved',
                'execution_state': 'ready',
            }
        ]
        self.workspace.list_commitments = lambda org_id=None, **_kwargs: [
            {
                'commitment_id': 'cmt_demo',
                'status': 'accepted',
            }
        ]
        self.workspace.commitment_summary = lambda org_id=None: {
            'total': 1,
            'proposed': 0,
            'accepted': 1,
            'rejected': 0,
            'breached': 0,
            'settled': 0,
            'delivery_refs_total': 0,
        }
        self.workspace.list_cases = lambda org_id=None, **_kwargs: [
            {
                'case_id': 'case_demo',
                'status': 'open',
                'claim_type': 'breach_of_commitment',
            }
        ]
        self.workspace.case_summary = lambda org_id=None: {
            'total': 1,
            'open': 1,
            'stayed': 0,
            'resolved': 0,
        }
        self.workspace.blocking_commitment_ids = lambda org_id=None: ['cmt_demo']
        self.workspace.blocked_peer_host_ids = lambda org_id=None: ['host_beta']
        self.workspace.get_sprint_lead = lambda org_id: ('', 0)
        self.workspace.get_pending_approvals = lambda org_id=None: []
        self.workspace.get_restrictions = lambda *args, **kwargs: {}
        self.workspace._ci_vertical_status = lambda reg, lead_id, org_id=None: {}
        self.workspace.get_agent_remediation = lambda economy_key, reg: None
        self.workspace.load_host_identity = lambda *args, **kwargs: default_host_identity(
            host_id='host_alpha',
            federation_enabled=True,
            supported_boundaries=['workspace', 'cli'],
        )
        self.workspace.load_admission_registry = lambda *args, **kwargs: {
            'source': 'file',
            'host_id': 'host_alpha',
            'institutions': {
                'org_a': {'status': 'admitted'},
                'org_b': {'status': 'admitted'},
            },
            'admitted_org_ids': ['org_a', 'org_b'],
        }
        self.workspace.load_peer_registry = lambda *args, **kwargs: {
            'source': 'file',
            'host_id': 'host_alpha',
            'peers': {
                'host_beta': self.workspace.FederationPeer(
                    host_id='host_beta',
                    label='Beta Host',
                    trust_state='trusted',
                    endpoint_url='http://127.0.0.1:19014',
                    admitted_org_ids=['org_c'],
                ),
            },
            'trusted_peer_ids': ['host_beta'],
        }
        self.workspace.load_subscriptions = lambda org_id=None: {
            'subscribers': {'111': []},
            'delivery_log': [],
            '_meta': {'storage_model': 'capsule_canonical'},
        }
        self.workspace.subscription_summary = lambda org_id=None: {'subscriber_count': 1}
        self.workspace.active_delivery_targets = lambda org_id=None, external_only=False: ['111']
        self.workspace.accounting_snapshot = lambda org_id=None: {
            'bound_org_id': org_id,
            'summary': {'entry_count': 0},
            'mutation_enabled': True,
        }
        ctx = self.workspace._resolve_workspace_context()
        status = self.workspace.api_status(institution_context=ctx)
        self.assertEqual(status['runtime_core']['institution_context']['org_id'], 'org_a')
        self.assertEqual(status['context']['request_routing']['effective_org_id'], 'org_a')
        self.assertEqual(status['context']['request_routing']['route_state'], 'bound')
        self.assertTrue(status['runtime_core']['service_registry']['workspace']['supports_institution_routing'])
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
        self.assertTrue(status['runtime_core']['admission']['additional_institutions_allowed'])
        self.assertEqual(status['runtime_core']['admission']['management_mode'], 'workspace_api_file_backed')
        self.assertTrue(status['runtime_core']['admission']['mutation_enabled'])
        self.assertEqual(status['runtime_core']['host_identity']['host_id'], 'host_alpha')
        self.assertEqual(status['runtime_core']['admission']['admitted_org_ids'], ['org_a', 'org_b'])
        self.assertEqual(status['warrants']['total'], 1)
        self.assertEqual(status['warrants']['executable'], 1)
        self.assertEqual(status['commitments']['total'], 1)
        self.assertEqual(status['commitments']['accepted'], 1)
        self.assertEqual(status['commitments']['management_mode'], 'workspace_api_file_backed')
        self.assertTrue(status['commitments']['mutation_enabled'])
        self.assertEqual(status['cases']['total'], 1)
        self.assertEqual(status['cases']['open'], 1)
        self.assertEqual(status['cases']['management_mode'], 'workspace_api_file_backed')
        self.assertEqual(status['cases']['blocking_commitment_ids'], ['cmt_demo'])
        self.assertEqual(status['cases']['blocked_peer_host_ids'], ['host_beta'])
        self.assertIn('federation', status['runtime_core'])
        self.assertTrue(status['runtime_core']['service_registry']['subscriptions']['supports_institution_routing'])
        self.assertTrue(status['runtime_core']['service_registry']['accounting']['supports_institution_routing'])
        self.assertEqual(status['routing_planner']['summary'], {'total': 3, 'local': 1, 'remote': 1, 'blocked': 1})
        decisions = {item['requested_org_id']: item for item in status['routing_planner']['decisions']}
        self.assertEqual(decisions['org_a']['route_kind'], 'local')
        self.assertEqual(decisions['org_b']['route_kind'], 'blocked')
        self.assertEqual(decisions['org_c']['route_kind'], 'remote')
        self.assertEqual(decisions['org_c']['target_host_id'], 'host_beta')
        self.assertEqual(status['agents'][0]['runtime_binding']['runtime_id'], 'local_kernel')
        self.assertEqual(status['agents'][0]['runtime_binding']['bound_org_id'], 'org_a')
        self.assertEqual(status['agents'][0]['runtime_binding']['context_source'], 'agent_registry')
        self.assertEqual(status['agents'][0]['runtime_binding']['boundary_name'], 'workspace')
        self.assertTrue(status['agents'][0]['runtime_binding']['runtime_registered'])
        self.assertEqual(status['runtime_core']['runtime_usage']['runtimes']['local_kernel']['bound_agent_count'], 1)
        self.assertEqual(
            status['runtime_core']['runtime_usage']['runtimes']['local_kernel']['bound_agent_ids'],
            ['agent_atlas_a'],
        )
        self.assertEqual(status['runtime_core']['runtime_usage']['unregistered_bindings'], [])
        self.assertEqual(status['service_state']['subscriptions']['summary']['subscriber_count'], 1)
        self.assertEqual(status['service_state']['accounting']['summary']['entry_count'], 0)

    def test_workspace_get_surfaces_subscriptions_and_accounting(self):
        class FakeContext:
            def __init__(self, org_id='org_a'):
                self.org_id = org_id
                self.org = {'id': org_id, 'name': 'Org A'}
                self.context_source = 'configured_org'

            def to_dict(self):
                return {
                    'org_id': self.org_id,
                    'org_name': self.org.get('name', ''),
                    'boundary_name': 'workspace',
                    'identity_model': 'session',
                    'routing_scope': 'institution_bound',
                    'host_id': 'host_gamma',
                    'host_role': 'witness_host',
                    'admission_id': '',
                    'federation_mode': 'federated_runtime_core',
                    'context_source': self.context_source,
                    'founded_at': '',
                }

            def to_dict(self):
                return {
                    'org_id': self.org_id,
                    'org_name': self.org.get('name', ''),
                    'boundary_name': 'workspace',
                    'identity_model': 'session',
                    'routing_scope': 'institution_bound',
                    'host_id': 'host_gamma',
                    'host_role': 'witness_host',
                    'admission_id': '',
                    'federation_mode': 'federated_runtime_core',
                    'context_source': self.context_source,
                    'founded_at': '',
                }

            def to_dict(self):
                return {
                    'org_id': self.org_id,
                    'org_name': self.org.get('name', ''),
                    'boundary_name': 'workspace',
                    'identity_model': 'session',
                    'routing_scope': 'institution_bound',
                    'host_id': 'host_gamma',
                    'host_role': 'witness_host',
                    'admission_id': '',
                    'federation_mode': 'federated_runtime_core',
                    'context_source': self.context_source,
                    'founded_at': '',
                }

        captured = {}
        handler = object.__new__(self.workspace.WorkspaceHandler)
        handler.path = '/api/subscriptions'
        handler.headers = _Headers()
        handler._require_auth = lambda _path: True
        handler._session_claims_from_request = lambda expected_org_id=None: None
        handler._json = lambda data, status=200: captured.update({'status': status, 'data': data})
        handler._html = lambda html: captured.update({'status': 200, 'html': html})

        with mock.patch.object(self.workspace, '_resolve_workspace_context', return_value=FakeContext()), \
             mock.patch.object(self.workspace, '_enforce_request_context', return_value={'mode': 'process_bound'}), \
             mock.patch.object(self.workspace, '_resolve_auth_context', return_value={'enabled': True, 'role': 'owner'}), \
             mock.patch.object(self.workspace, 'load_registry', return_value={
                 'agents': {
                     'agent_atlas_a': {
                         'id': 'agent_atlas_a',
                         'org_id': 'org_a',
                         'name': 'Atlas',
                         'role': 'analyst',
                         'purpose': 'Research',
                         'economy_key': 'atlas',
                         'runtime_binding': {'runtime_id': 'mcp_generic'},
                         'rollout_state': 'active',
                         'reputation_units': 100,
                         'authority_units': 100,
                         'last_active_at': '2026-03-21T00:00:00Z',
                         'risk_state': 'nominal',
                         'lifecycle_state': 'active',
                         'budget': {'max_per_run_usd': 1.0},
                         'scopes': ['execute'],
                     },
                 }
             }), \
             mock.patch.object(self.workspace, 'load_subscriptions', return_value={'subscribers': {'111': []}, 'delivery_log': [], '_meta': {'storage_model': 'capsule_canonical'}}), \
             mock.patch.object(self.workspace, 'subscription_summary', return_value={'subscriber_count': 1}), \
             mock.patch.object(self.workspace, 'active_delivery_targets', return_value=['111']), \
             mock.patch.object(self.workspace, 'accounting_snapshot', return_value={'bound_org_id': 'org_a', 'summary': {'entry_count': 0}}):
            handler.do_GET()
            self.assertEqual(captured['status'], 200)
            self.assertEqual(captured['data']['bound_org_id'], 'org_a')
            self.assertEqual(captured['data']['management_mode'], 'institution_owned_service')
            self.assertEqual(captured['data']['summary']['subscriber_count'], 1)
            self.assertEqual(captured['data']['state']['subscribers'], {'111': []})

            handler.path = '/api/subscriptions/delivery-targets'
            captured.clear()
            handler.do_GET()
            self.assertEqual(captured['status'], 200)
            self.assertEqual(captured['data']['targets'], ['111'])
            self.assertEqual(captured['data']['external_targets'], ['111'])

            handler.path = '/api/accounting'
            captured.clear()
            handler.do_GET()
            self.assertEqual(captured['status'], 200)
            self.assertEqual(captured['data']['bound_org_id'], 'org_a')
            self.assertEqual(captured['data']['summary']['entry_count'], 0)

            handler.path = '/api/agents'
            captured.clear()
            handler.do_GET()
            self.assertEqual(captured['status'], 200)
            self.assertEqual(captured['data'][0]['runtime_binding']['runtime_id'], 'mcp_generic')
            self.assertEqual(captured['data'][0]['runtime_binding']['bound_org_id'], 'org_a')
            self.assertTrue(captured['data'][0]['runtime_binding']['runtime_registered'])

            handler.path = '/api/runtimes'
            captured.clear()
            handler.do_GET()
            self.assertEqual(captured['status'], 200)
            self.assertEqual(captured['data']['runtimes']['mcp_generic']['runtime_usage']['bound_agent_count'], 1)
            self.assertEqual(
                captured['data']['runtimes']['mcp_generic']['runtime_usage']['bound_agent_ids'],
                ['agent_atlas_a'],
            )
            self.assertEqual(captured['data']['runtime_usage']['unregistered_bindings'], [])


    def test_payout_execute_dry_run_skips_warrant_finalization(self):
        class FakeContext:
            def __init__(self):
                self.org_id = 'org_a'
                self.org = {'id': 'org_a', 'name': 'Org A'}
                self.context_source = 'configured_org'

            def to_dict(self):
                return {
                    'org_id': self.org_id,
                    'org_name': self.org.get('name', ''),
                    'boundary_name': 'workspace',
                    'identity_model': 'session',
                    'routing_scope': 'institution_bound',
                    'host_id': 'host_alpha',
                    'host_role': 'institution_host',
                    'admission_id': '',
                    'federation_mode': 'federated_runtime_core',
                    'context_source': self.context_source,
                    'founded_at': '',
                }

        captured = {}
        handler = object.__new__(self.workspace.WorkspaceHandler)
        handler.path = '/api/payouts/execute'
        handler.headers = _Headers()
        handler._require_auth = lambda _path: True
        handler._session_claims_from_request = lambda expected_org_id=None: None
        handler._read_body = lambda: {
            'proposal_id': 'pay_demo',
            'warrant_id': 'war_preview_1',
            'dry_run': True,
            'settlement_adapter': 'internal_ledger',
            'tx_hash': '0xpreview',
        }
        handler._json = lambda data, status=200: captured.update({'status': status, 'data': data})
        handler._html = lambda html: captured.update({'status': 200, 'html': html})

        preview = {
            'dry_run': True,
            'status': 'dispute_window',
            'proposal_id': 'pay_demo',
            'settlement_adapter': 'internal_ledger',
            'execution_plan': {
                'amount_usd': 2.0,
                'recipient_wallet_id': 'wallet_exec',
                'tx_ref': 'ptx_preview_demo',
            },
        }
        warrant = {'warrant_id': 'war_preview_1', 'execution_state': 'ready'}

        with mock.patch.object(self.workspace, '_resolve_workspace_context', return_value=FakeContext()),              mock.patch.object(self.workspace, '_resolve_auth_context', return_value={'enabled': True, 'role': 'owner', 'actor_id': 'user_owner'}),              mock.patch.object(self.workspace, '_enforce_mutation_authorization', return_value='owner'),              mock.patch.object(self.workspace, '_runtime_host_state', return_value=(self.workspace.load_host_identity('missing'), {'source': 'file', 'institutions': {}, 'admitted_org_ids': []})),              mock.patch.object(self.workspace, 'get_payout_proposal', return_value={'proposal_id': 'pay_demo', 'status': 'dispute_window', 'linked_commitment_id': ''}),              mock.patch.object(self.workspace, 'validate_warrant_for_execution', return_value=warrant),              mock.patch.object(self.workspace, 'execute_payout_proposal', return_value=preview),              mock.patch.object(self.workspace, 'mark_warrant_executed', side_effect=self.fail),              mock.patch.object(self.workspace, 'payout_proposal_summary', return_value={'total': 1}),              mock.patch.object(self.workspace, 'log_event'):
            handler.do_POST()

        self.assertEqual(captured['status'], 200)
        self.assertEqual(captured['data']['message'], 'Payout execution previewed: pay_demo')
        self.assertTrue(captured['data']['proposal']['dry_run'])
        self.assertEqual(captured['data']['proposal']['execution_plan']['tx_ref'], 'ptx_preview_demo')
        self.assertEqual(captured['data']['warrant'], warrant)
        self.assertEqual(captured['data']['summary']['total'], 1)

    def test_treasury_payout_plan_preview_queue_endpoint_returns_snapshot(self):
        class FakeContext:
            def __init__(self):
                self.org_id = 'org_a'
                self.org = {'id': 'org_a', 'name': 'Org A'}
                self.context_source = 'configured_org'

            def to_dict(self):
                return {
                    'org_id': self.org_id,
                    'org_name': self.org.get('name', ''),
                    'boundary_name': 'workspace',
                    'identity_model': 'session',
                    'routing_scope': 'institution_bound',
                    'host_id': 'host_alpha',
                    'host_role': 'institution_host',
                    'admission_id': '',
                    'federation_mode': 'federated_runtime_core',
                    'context_source': self.context_source,
                    'founded_at': '',
                }

        captured = {}
        handler = object.__new__(self.workspace.WorkspaceHandler)
        handler.path = '/api/treasury/payout-plan-preview-queue'
        handler.headers = _Headers()
        handler._require_auth = lambda _path: True
        handler._session_claims_from_request = lambda expected_org_id=None: None
        handler._json = lambda data, status=200: captured.update({'status': status, 'data': data})
        handler._html = lambda html: captured.update({'status': 200, 'html': html})

        snapshot = {
            'summary': {'total': 1, 'execution_ready': 1},
            'payout_plan_previews': [
                {'preview_id': 'ptx_preview_demo', 'proposal_id': 'pay_demo'}
            ],
        }

        with mock.patch.object(self.workspace, '_resolve_workspace_context', return_value=FakeContext()),              mock.patch.object(self.workspace, '_resolve_auth_context', return_value={'enabled': True, 'role': 'owner'}),              mock.patch.object(self.workspace, '_payout_plan_preview_queue_snapshot', return_value=snapshot):
            handler.do_GET()

        self.assertEqual(captured['status'], 200)
        self.assertEqual(captured['data']['summary']['total'], 1)
        self.assertEqual(captured['data']['payout_plan_previews'][0]['preview_id'], 'ptx_preview_demo')

    def test_treasury_payout_plan_preview_queue_inspection_endpoint_returns_inspection(self):
        class FakeContext:
            def __init__(self):
                self.org_id = 'org_a'
                self.org = {'id': 'org_a', 'name': 'Org A'}
                self.context_source = 'configured_org'

            def to_dict(self):
                return {
                    'org_id': self.org_id,
                    'org_name': self.org.get('name', ''),
                    'boundary_name': 'workspace',
                    'identity_model': 'session',
                    'routing_scope': 'institution_bound',
                    'host_id': 'host_alpha',
                    'host_role': 'institution_host',
                    'admission_id': '',
                    'federation_mode': 'federated_runtime_core',
                    'context_source': self.context_source,
                    'founded_at': '',
                }

        captured = {}
        handler = object.__new__(self.workspace.WorkspaceHandler)
        handler.path = '/api/treasury/payout-plan-preview-queue/inspect'
        handler.headers = _Headers()
        handler._require_auth = lambda _path: True
        handler._session_claims_from_request = lambda expected_org_id=None: None
        handler._json = lambda data, status=200: captured.update({'status': status, 'data': data})
        handler._html = lambda html: captured.update({'status': 200, 'html': html})

        inspection = {
            'summary': {'total': 1, 'execution_ready': 1},
            'inspection_summary': {'total': 1, 'ready_for_ack': 1, 'requires_operator_ack': 1},
            'payout_plan_previews': [
                {
                    'preview_id': 'ptx_preview_demo',
                    'proposal_id': 'pay_demo',
                    'inspection_state': 'ready_for_ack',
                }
            ],
        }

        with mock.patch.object(self.workspace, '_resolve_workspace_context', return_value=FakeContext()), \
             mock.patch.object(self.workspace, '_resolve_auth_context', return_value={'enabled': True, 'role': 'owner'}), \
             mock.patch.object(self.workspace, '_payout_plan_preview_queue_inspection', return_value=inspection):
            handler.do_GET()

        self.assertEqual(captured['status'], 200)
        self.assertEqual(captured['data']['inspection_summary']['total'], 1)
        self.assertEqual(captured['data']['payout_plan_previews'][0]['inspection_state'], 'ready_for_ack')

    def test_treasury_payout_plan_approval_candidate_queue_endpoint_returns_snapshot(self):
        class FakeContext:
            def __init__(self):
                self.org_id = 'org_a'
                self.org = {'id': 'org_a', 'name': 'Org A'}
                self.context_source = 'configured_org'

            def to_dict(self):
                return {
                    'org_id': self.org_id,
                    'org_name': self.org.get('name', ''),
                    'boundary_name': 'workspace',
                    'identity_model': 'session',
                    'routing_scope': 'institution_bound',
                    'host_id': 'host_alpha',
                    'host_role': 'institution_host',
                    'admission_id': '',
                    'federation_mode': 'federated_runtime_core',
                    'context_source': self.context_source,
                    'founded_at': '',
                }

        captured = {}
        handler = object.__new__(self.workspace.WorkspaceHandler)
        handler.path = '/api/treasury/payout-plan-approval-candidate-queue'
        handler.headers = _Headers()
        handler._require_auth = lambda _path: True
        handler._session_claims_from_request = lambda expected_org_id=None: None
        handler._json = lambda data, status=200: captured.update({'status': status, 'data': data})
        handler._html = lambda html: captured.update({'status': 200, 'html': html})

        snapshot = {
            'summary': {'total': 1, 'ready_for_approval': 1},
            'payout_plan_approval_candidates': [
                {'candidate_id': 'ptx_preview_demo', 'source_preview_id': 'ptx_preview_demo'}
            ],
        }

        with mock.patch.object(self.workspace, '_resolve_workspace_context', return_value=FakeContext()), \
             mock.patch.object(self.workspace, '_resolve_auth_context', return_value={'enabled': True, 'role': 'owner'}), \
             mock.patch.object(self.workspace, 'payout_plan_approval_candidate_queue_snapshot', return_value=snapshot):
            handler.do_GET()

        self.assertEqual(captured['status'], 200)
        self.assertEqual(captured['data']['summary']['total'], 1)
        self.assertEqual(captured['data']['payout_plan_approval_candidates'][0]['candidate_id'], 'ptx_preview_demo')

    def test_treasury_payout_execution_queue_endpoint_returns_snapshot(self):
        class FakeContext:
            def __init__(self):
                self.org_id = 'org_a'
                self.org = {'id': 'org_a', 'name': 'Org A'}
                self.context_source = 'configured_org'

            def to_dict(self):
                return {
                    'org_id': self.org_id,
                    'org_name': self.org.get('name', ''),
                    'boundary_name': 'workspace',
                    'identity_model': 'session',
                    'routing_scope': 'institution_bound',
                    'host_id': 'host_alpha',
                    'host_role': 'institution_host',
                    'admission_id': '',
                    'federation_mode': 'federated_runtime_core',
                    'context_source': self.context_source,
                    'founded_at': '',
                }

        captured = {}
        handler = object.__new__(self.workspace.WorkspaceHandler)
        handler.path = '/api/treasury/payout-execution-queue'
        handler.headers = _Headers()
        handler._require_auth = lambda _path: True
        handler._session_claims_from_request = lambda expected_org_id=None: None
        handler._json = lambda data, status=200: captured.update({'status': status, 'data': data})
        handler._html = lambda html: captured.update({'status': 200, 'html': html})

        snapshot = {
            'summary': {'total': 1, 'dispatchable': 1},
            'payout_execution_records': [
                {'execution_id': 'ptx_exec_demo', 'proposal_id': 'pay_demo', 'state': 'dispatchable'}
            ],
        }

        with mock.patch.object(self.workspace, '_resolve_workspace_context', return_value=FakeContext()),              mock.patch.object(self.workspace, '_resolve_auth_context', return_value={'enabled': True, 'role': 'owner'}),              mock.patch.object(self.workspace, 'payout_execution_queue_snapshot', return_value=snapshot):
            handler.do_GET()

        self.assertEqual(captured['status'], 200)
        self.assertEqual(captured['data']['summary']['total'], 1)
        self.assertEqual(captured['data']['payout_execution_records'][0]['execution_id'], 'ptx_exec_demo')

    def test_treasury_payout_plan_approval_candidate_queue_promote_endpoint_returns_candidate(self):
        class FakeContext:
            def __init__(self):
                self.org_id = 'org_a'
                self.org = {'id': 'org_a', 'name': 'Org A'}
                self.context_source = 'configured_org'

            def to_dict(self):
                return {
                    'org_id': self.org_id,
                    'org_name': self.org.get('name', ''),
                    'boundary_name': 'workspace',
                    'identity_model': 'session',
                    'routing_scope': 'institution_bound',
                    'host_id': 'host_alpha',
                    'host_role': 'institution_host',
                    'admission_id': '',
                    'federation_mode': 'federated_runtime_core',
                    'context_source': self.context_source,
                    'founded_at': '',
                }

        captured = {}
        handler = object.__new__(self.workspace.WorkspaceHandler)
        handler.path = '/api/treasury/payout-plan-approval-candidate-queue/promote'
        handler.headers = _Headers()
        handler._require_auth = lambda _path: True
        handler._session_claims_from_request = lambda expected_org_id=None: None
        handler._read_body = lambda: {'preview_id': 'ptx_preview_demo', 'note': 'ready for approval review'}
        handler._json = lambda data, status=200: captured.update({'status': status, 'data': data})
        handler._html = lambda html: captured.update({'status': 200, 'html': html})

        candidate = {'candidate_id': 'ptx_preview_demo', 'proposal_id': 'pay_demo', 'promoted_at': '2026-03-22T00:00:00Z'}
        snapshot = {'summary': {'total': 1, 'ready_for_approval': 1}}

        with mock.patch.object(self.workspace, '_resolve_workspace_context', return_value=FakeContext()), \
             mock.patch.object(self.workspace, '_resolve_auth_context', return_value={'enabled': True, 'role': 'owner', 'actor_id': 'user_owner'}), \
             mock.patch.object(self.workspace, '_enforce_mutation_authorization', return_value='owner'), \
             mock.patch.object(self.workspace, 'promote_payout_plan_preview_to_approval_candidate', return_value=candidate), \
             mock.patch.object(self.workspace, 'payout_plan_approval_candidate_queue_snapshot', return_value=snapshot), \
             mock.patch.object(self.workspace, 'log_event'):
            handler.do_POST()

        self.assertEqual(captured['status'], 200)
        self.assertEqual(captured['data']['message'], 'Payout-plan approval candidate promoted: ptx_preview_demo')
        self.assertEqual(captured['data']['candidate']['candidate_id'], 'ptx_preview_demo')
        self.assertEqual(captured['data']['summary']['total'], 1)

    def test_federation_snapshot_surfaces_trusted_peers(self):
        from runtime_host import default_host_identity
        import tempfile
        import json

        with tempfile.TemporaryDirectory() as tmp:
            peers_path = os.path.join(tmp, 'federation_peers.json')
            replay_path = os.path.join(tmp, 'federation_replay.log')
            with open(peers_path, 'w') as f:
                json.dump({
                    'host_id': 'host_alpha',
                    'peers': {
                        'host_beta': {
                            'label': 'Beta Host',
                            'transport': 'https',
                            'endpoint_url': 'http://127.0.0.1:19014',
                            'trust_state': 'trusted',
                            'shared_secret': 'beta-secret',
                            'admitted_org_ids': ['org_b'],
                        }
                    },
                }, f)
            self.workspace.FEDERATION_PEERS_FILE = peers_path
            self.workspace.FEDERATION_REPLAY_FILE = replay_path
            self.workspace.FEDERATION_SIGNING_SECRET = 'alpha-secret'
            host = default_host_identity(
                host_id='host_alpha',
                federation_enabled=True,
                peer_transport='https',
            )
            snap = self.workspace._federation_snapshot(
                'org_a',
                host_identity=host,
                admission_registry={'admitted_org_ids': ['org_a', 'org_b']},
            )
            self.assertTrue(snap['enabled'])
            self.assertIn('handoff_preview', snap)
            self.assertIn('routing_planner', snap['handoff_preview'])
            self.assertIn('handoff_candidates', snap['handoff_preview'])
            self.assertTrue(snap['send_enabled'])
            self.assertEqual(snap['peer_count'], 1)
            self.assertEqual(snap['all_peer_count'], 1)
            self.assertEqual(snap['trusted_peer_ids'], ['host_beta'])
            self.assertEqual(snap['admitted_org_ids'], ['org_a', 'org_b'])
            self.assertEqual(snap['management_mode'], 'workspace_api_file_backed')
            self.assertTrue(snap['mutation_enabled'])
            self.assertIn('handoff_preview_queue', snap)
            self.assertIn('summary', snap['handoff_preview_queue'])

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
                'target_host_id': 'host_beta',
                'target_institution_id': 'org_a',
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
        snapshot = self.workspace._federation_execution_jobs_snapshot('org_a')
        self.assertEqual(snapshot['summary']['total'], 1)
        self.assertEqual(snapshot['summary']['pending_local_warrant'], 1)
        self.assertEqual(snapshot['summary']['message_type_counts'], {'execution_request': 1})
        self.assertEqual(snapshot['jobs'][0]['envelope_id'], 'fed_exec_demo')
        self.assertEqual(snapshot['jobs'][0]['state'], 'pending_local_warrant')
        self.assertEqual(snapshot['jobs'][0]['local_warrant']['warrant_id'], 'war_local_demo')
        self.assertEqual(snapshot['jobs'][0]['local_warrant']['court_review_state'], 'pending_review')
        self.assertEqual(snapshot['jobs'][0]['local_warrant']['execution_state'], 'ready')

    def test_receiver_execution_warrant_payload_prefers_persisted_request_object(self):
        payload = self.workspace._receiver_execution_warrant_payload_from_job({
            'envelope_id': 'fed_exec_demo',
            'source_host_id': 'host_stale',
            'source_institution_id': 'org_stale',
            'target_host_id': 'host_other',
            'target_institution_id': 'org_other',
            'message_type': 'execution_request',
            'boundary_name': 'federation_gateway',
            'identity_model': 'signed_host_service',
            'sender_warrant_id': 'war_stale',
            'commitment_id': 'cmt_stale',
            'payload': {'task': 'stale'},
            'request': {
                'request_id': 'fed_exec_demo',
                'request_type': 'execution_request',
                'claims': {
                    'source_host_id': 'host_alpha',
                    'source_institution_id': 'org_alpha',
                    'target_host_id': 'host_beta',
                    'target_institution_id': 'org_a',
                    'message_type': 'execution_request',
                    'boundary_name': 'federation_gateway',
                    'identity_model': 'signed_host_service',
                    'sender_warrant_id': 'war_sender_demo',
                    'commitment_id': 'cmt_demo',
                },
                'receipt': {
                    'receipt_id': 'fedrcpt_demo',
                    'accepted_at': '2026-03-22T00:00:00Z',
                },
                'payload': {'task': 'demo'},
                'evidence_refs': [
                    'federation_envelope:fed_exec_demo',
                    'federation_receipt:fedrcpt_demo',
                ],
            },
        })
        self.assertEqual(payload['request_id'], 'fed_exec_demo')
        self.assertEqual(payload['request_type'], 'execution_request')
        self.assertEqual(payload['source_host_id'], 'host_alpha')
        self.assertEqual(payload['source_institution_id'], 'org_alpha')
        self.assertEqual(payload['sender_warrant_id'], 'war_sender_demo')
        self.assertEqual(payload['payload'], {'task': 'demo'})
        self.assertEqual(payload['evidence_refs'], ['federation_envelope:fed_exec_demo', 'federation_receipt:fedrcpt_demo'])

    def test_execution_job_warrant_validation_payload_uses_persisted_request_object(self):
        request_object = {
            'request_id': 'fed_exec_demo',
            'request_type': 'execution_request',
            'claims': {
                'source_host_id': 'host_alpha',
                'source_institution_id': 'org_alpha',
                'target_host_id': 'host_beta',
                'target_institution_id': 'org_beta',
                'message_type': 'execution_request',
                'boundary_name': 'federation_gateway',
                'identity_model': 'signed_host_service',
                'sender_warrant_id': 'war_sender_demo',
                'commitment_id': 'cmt_demo',
                'payload_hash': 'hash_demo',
            },
            'receipt': {
                'receipt_id': 'fedrcpt_demo',
                'accepted_at': '2026-03-22T00:00:00Z',
            },
            'payload': {'task': 'demo'},
            'payload_hash': 'hash_demo',
            'evidence_refs': [
                'federation_envelope:fed_exec_demo',
                'federation_receipt:fedrcpt_demo',
            ],
        }
        payload = self.workspace._execution_job_warrant_validation_payload({
            'request': request_object,
            'payload': {'task': 'stale'},
        })
        self.assertEqual(payload, request_object)

    def test_execute_federated_execution_job_records_settlement_notice_once(self):
        job = {
            'job_id': 'fej_demo',
            'envelope_id': 'fed_demo',
            'source_host_id': 'host_alpha',
            'source_institution_id': 'org_alpha',
            'target_host_id': 'host_beta',
            'target_institution_id': 'org_beta',
            'actor_type': 'service',
            'actor_id': 'peer:host_alpha',
            'session_id': 'ses_demo',
            'boundary_name': 'federation_gateway',
            'identity_model': 'signed_host_service',
            'message_type': 'execution_request',
            'receipt_id': 'fedrcpt_demo',
            'sender_warrant_id': 'war_sender',
            'local_warrant_id': 'war_local_demo',
            'commitment_id': 'cmt_demo',
            'payload': {'task': 'demo'},
            'payload_hash': 'hash_demo',
            'state': 'ready',
            'received_at': '2026-03-22T00:00:00Z',
            'note': 'Receiver-side execution request queued for local warrant review',
            'metadata': {},
            'execution_refs': {},
        }
        warrant = {
            'warrant_id': 'war_local_demo',
            'court_review_state': 'approved',
            'execution_state': 'ready',
            'execution_refs': {},
        }
        commitment = {
            'commitment_id': 'cmt_demo',
            'state': 'accepted',
            'status': 'accepted',
            'target_host_id': 'host_alpha',
            'target_institution_id': 'org_alpha',
            'delivery_refs': [],
            'settlement_refs': [],
        }
        proposal = {
            'proposal_id': 'pay_demo',
            'linked_commitment_id': 'cmt_demo',
            'status': 'executed',
            'execution_refs': {
                'tx_ref': 'ptx_demo',
                'settlement_adapter': 'internal_ledger',
                'proof_type': 'ledger_transaction',
                'verification_state': 'host_ledger_final',
                'finality_state': 'host_local_final',
                'proof': {'mode': 'institution_transactions_journal'},
            },
        }
        stored_job = dict(job)
        stored_warrant = dict(warrant)
        delivered_payloads = []
        delivery = {
            'claims': {
                'envelope_id': 'fed_notice_1',
                'target_host_id': 'host_alpha',
                'target_institution_id': 'org_alpha',
            },
            'receipt': {
                'receipt_id': 'fedrcpt_notice_1',
                'accepted_at': '2026-03-22T00:00:01Z',
            },
            'response': {'processing': {'applied': True}},
        }

        def fake_upsert(_org_id, **fields):
            stored_job.update(fields)
            if 'execution_refs' in fields:
                stored_job['execution_refs'] = dict(fields['execution_refs'] or {})
            if 'metadata' in fields:
                stored_job['metadata'] = dict(fields['metadata'] or {})
            return dict(stored_job)

        def fake_mark_warrant_executed(_warrant_id, *, org_id=None, execution_refs=None):
            stored_warrant['execution_state'] = 'executed'
            stored_warrant['executed_at'] = '2026-03-22T00:00:01Z'
            stored_warrant['execution_refs'] = dict(execution_refs or {})
            return dict(stored_warrant)

        def fake_deliver(*args, **kwargs):
            delivered_payloads.append(dict(kwargs.get('payload') or {}))
            return delivery, {'host_id': 'host_beta'}

        with mock.patch.object(self.workspace, 'get_warrant', return_value=stored_warrant), \
             mock.patch.object(self.workspace, 'validate_warrant_for_execution') as validate, \
             mock.patch.object(self.workspace, 'mark_warrant_executed', side_effect=fake_mark_warrant_executed), \
             mock.patch.object(self.workspace, 'get_commitment', return_value=commitment), \
             mock.patch.object(self.workspace, 'list_payout_proposals', return_value=[proposal]), \
             mock.patch.object(self.workspace, 'get_payout_proposal', return_value=proposal), \
             mock.patch.object(self.workspace, 'upsert_execution_job', side_effect=fake_upsert), \
             mock.patch.object(self.workspace, '_deliver_federation_envelope', side_effect=fake_deliver) as deliver, \
             mock.patch.object(self.workspace, 'log_event'):
            executed = self.workspace._complete_federated_execution_job(
                'org_a',
                job,
                actor_id='user_owner',
                session_id='ses_demo',
            )

            self.assertEqual(executed['execution_job']['state'], 'executed')
            self.assertEqual(executed['warrant']['execution_state'], 'executed')
            self.assertEqual(executed['settlement_notice']['message_type'], 'settlement_notice')
            self.assertEqual(executed['settlement_notice']['envelope_id'], 'fed_notice_1')
            self.assertEqual(deliver.call_count, 1)
            validate.assert_called_once()
            self.assertEqual(delivered_payloads[0]['execution_refs']['proposal_id'], 'pay_demo')
            self.assertEqual(delivered_payloads[0]['execution_refs']['tx_ref'], 'ptx_demo')

            commitment['delivery_refs'] = [
                {
                    'message_type': 'settlement_notice',
                    'envelope_id': 'fed_notice_1',
                    'receipt_id': 'fedrcpt_notice_1',
                    'target_host_id': 'host_alpha',
                    'target_institution_id': 'org_alpha',
                    'recorded_at': '2026-03-22T00:00:01Z',
                },
            ]
            stored_job['execution_refs'] = {}

            replay = self.workspace._complete_federated_execution_job(
                'org_a',
                dict(stored_job, state='executed'),
                actor_id='user_owner',
                session_id='ses_demo',
            )

            self.assertEqual(replay['settlement_notice']['envelope_id'], 'fed_notice_1')
            self.assertEqual(deliver.call_count, 1)

    def test_federation_manifest_surfaces_host_admission_and_service_registry(self):
        from runtime_host import default_host_identity

        self.workspace._load_workspace_credentials = lambda: (None, None, None, None)
        self.workspace.WORKSPACE_ORG_ID = 'org_a'
        self.workspace.load_orgs = lambda: {
            'organizations': {
                'org_a': {'id': 'org_a', 'slug': 'a', 'name': 'A', 'lifecycle_state': 'active'},
            }
        }
        ctx = self.workspace._resolve_workspace_context()
        host = default_host_identity(
            host_id='host_alpha',
            role='control_host',
            federation_enabled=True,
            peer_transport='https',
            supported_boundaries=['workspace', 'cli', 'federation_gateway'],
        )
        manifest = self.workspace._federation_manifest(
            ctx,
            host_identity=host,
            admission_registry={
                'source': 'file',
                'host_id': 'host_alpha',
                'institutions': {'org_a': {'status': 'admitted'}},
                'admitted_org_ids': ['org_a'],
            },
        )
        self.assertEqual(manifest['host_identity']['host_id'], 'host_alpha')
        self.assertEqual(manifest['admission']['bound_org_id'], ctx.org_id)
        self.assertIn('federation_gateway', manifest['service_registry'])
        self.assertEqual(manifest['federation']['boundary_name'], 'federation_gateway')
        self.assertTrue(manifest['service_registry']['federation_gateway']['requires_warrant'])
        self.assertEqual(manifest['federation']['routing_summary']['target_institution_id'], ctx.org_id)
        self.assertEqual(manifest['federation']['routing_summary']['delivery_ready_count'], 0)

    def test_federation_receipt_is_bound_to_receiver_host_and_org(self):
        from federation import FederationEnvelopeClaims

        receipt = self.workspace._federation_receipt(
            'org_a',
            'host_alpha',
            FederationEnvelopeClaims(
                envelope_id='fed_demo',
                message_type='execution_request',
                boundary_name='federation_gateway',
            ),
        )
        self.assertEqual(receipt['envelope_id'], 'fed_demo')
        self.assertEqual(receipt['receiver_host_id'], 'host_alpha')
        self.assertEqual(receipt['receiver_institution_id'], 'org_a')
        self.assertEqual(receipt['identity_model'], 'signed_host_service')
        self.assertTrue(receipt['receipt_id'].startswith('fedrcpt_'))

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
        snapshot = self.workspace._federation_snapshot(
            'org_a',
            host_identity=default_host_identity(
                host_id='host_alpha',
                role='control_host',
                federation_enabled=True,
                peer_transport='https',
                supported_boundaries=['workspace', 'cli', 'federation_gateway'],
            ),
            admission_registry={
                'source': 'file',
                'host_id': 'host_alpha',
                'institutions': {'org_a': {'status': 'admitted'}},
                'admitted_org_ids': ['org_a'],
            },
            peer_registry={
                'host_id': 'host_alpha',
                'peers': {},
                'trusted_peer_ids': [],
            },
        )
        self.assertEqual(snapshot['inbox_summary']['total'], 1)
        self.assertEqual(
            snapshot['inbox_summary']['message_type_counts']['execution_request'],
            1,
        )

    def test_witness_host_surfaces_read_only_runtime_truth(self):
        from runtime_host import default_host_identity

        host = default_host_identity(
            host_id='host_gamma',
            role='witness_host',
            federation_enabled=True,
            peer_transport='https',
            supported_boundaries=['workspace', 'cli', 'federation_gateway'],
        )
        admission_registry = {
            'source': 'file',
            'host_id': 'host_gamma',
            'institutions': {
                'org_a': {'status': 'admitted'},
                'org_b': {'status': 'admitted'},
            },
            'admitted_org_ids': ['org_a', 'org_b'],
        }
        self.workspace.summarize_inbox_entries = lambda org_id: {
            'org_id': org_id,
            'total': 2,
            'received': 2,
            'processed': 0,
            'message_type_counts': {'execution_request': 1, 'settlement_notice': 1},
            'state_counts': {'received': 2},
            'updatedAt': '2026-03-22T00:00:00Z',
        }

        admission = self.workspace._admission_snapshot('org_a', host_identity=host, admission_registry=admission_registry)
        federation = self.workspace._federation_snapshot(
            'org_a',
            host_identity=host,
            admission_registry=admission_registry,
            peer_registry={
                'host_id': 'host_gamma',
                'peers': {},
                'trusted_peer_ids': [],
            },
        )
        ctx = self.workspace.InstitutionContext.bind(
            'org_a',
            {
                'id': 'org_a',
                'name': 'Org A',
                'slug': 'org-a',
                'status': 'active',
                'lifecycle_state': 'active',
            },
            'configured_org',
            self.workspace.WORKSPACE_BOUNDARY,
        )
        manifest = self.workspace._federation_manifest(
            ctx,
            host_identity=host,
            admission_registry=admission_registry,
        )

        self.assertEqual(admission['host_role'], 'witness_host')
        self.assertEqual(admission['management_mode'], 'witness_read_only')
        self.assertFalse(admission['mutation_enabled'])
        self.assertEqual(admission['mutation_disabled_reason'], 'witness_host_read_only')
        self.assertEqual(admission['admitted_org_ids'], ['org_a', 'org_b'])
        self.assertEqual(federation['management_mode'], 'witness_read_only')
        self.assertFalse(federation['mutation_enabled'])
        self.assertEqual(federation['mutation_disabled_reason'], 'witness_host_read_only')
        self.assertEqual(federation['inbox_summary']['total'], 2)
        self.assertIn('witness_archive', federation)
        self.assertTrue(federation['witness_archive']['archive_enabled'])
        self.assertEqual(federation['witness_archive']['management_mode'], 'witness_local_archive')
        self.assertEqual(manifest['admission']['management_mode'], 'witness_read_only')
        self.assertFalse(manifest['admission']['mutation_enabled'])
        self.assertEqual(manifest['federation']['management_mode'], 'witness_read_only')
        self.assertFalse(manifest['federation']['mutation_enabled'])
        self.assertEqual(manifest['host_identity']['role'], 'witness_host')

    def test_witness_archive_snapshot_reports_host_local_evidence_state(self):
        from runtime_host import default_host_identity

        host = default_host_identity(
            host_id='host_gamma',
            role='witness_host',
            federation_enabled=True,
            peer_transport='https',
            supported_boundaries=['workspace', 'cli', 'federation_gateway'],
        )
        self.workspace.list_witness_observations = lambda file_path, host_id='': [
            {
                'archive_id': 'witobs_demo',
                'message_type': 'settlement_notice',
                'source_host_id': 'host_alpha',
                'target_host_id': 'host_beta',
            }
        ]
        self.workspace.witness_archive_summary = lambda file_path, host_id='': {
            'total': 1,
            'message_type_counts': {'settlement_notice': 1},
            'peer_host_ids': ['host_alpha', 'host_beta'],
            'latest_observed_at': '2026-03-22T00:00:00Z',
        }

        snapshot = self.workspace._witness_archive_snapshot(
            'org_a',
            host_identity=host,
        )
        self.assertEqual(snapshot['host_role'], 'witness_host')
        self.assertEqual(snapshot['management_mode'], 'witness_local_archive')
        self.assertTrue(snapshot['archive_enabled'])
        self.assertEqual(snapshot['summary']['total'], 1)
        self.assertEqual(snapshot['records'][0]['archive_id'], 'witobs_demo')

    def test_witness_archive_snapshot_is_disabled_on_non_witness_host(self):
        from runtime_host import default_host_identity

        snapshot = self.workspace._witness_archive_snapshot(
            'org_a',
            host_identity=default_host_identity(
                host_id='host_alpha',
                role='institution_host',
                federation_enabled=True,
                peer_transport='https',
            ),
        )
        self.assertFalse(snapshot['archive_enabled'])
        self.assertEqual(snapshot['archive_disabled_reason'], 'witness_host_only')
        self.assertEqual(snapshot['records'], [])

    def test_process_received_settlement_notice_marks_inbox_processed(self):
        from federation import FederationEnvelopeClaims
        from runtime_host import default_host_identity

        calls = {}
        sender_warrant = {
            'warrant_id': 'war_sender',
            'execution_state': 'ready',
        }
        self.workspace.get_commitment = lambda commitment_id, org_id=None: {
            'commitment_id': commitment_id,
            'delivery_refs': [
                {
                    'message_type': 'execution_request',
                    'envelope_id': 'fed_exec',
                    'target_host_id': 'host_alpha',
                    'target_institution_id': 'org_alpha',
                    'receipt_id': 'fedrcpt_exec',
                    'receiver_host_id': 'host_alpha',
                    'receiver_institution_id': 'org_alpha',
                    'warrant_id': 'war_sender',
                }
            ],
        }
        self.workspace.get_warrant = lambda warrant_id, org_id=None: (
            dict(sender_warrant) if warrant_id == 'war_sender' else None
        )
        self.workspace.mark_warrant_executed = lambda warrant_id, *, org_id=None, execution_refs=None: {
            'warrant_id': warrant_id,
            'execution_state': 'executed',
            'execution_refs': dict(execution_refs or {}),
        }
        self.workspace.validate_commitment_for_settlement = (
            lambda commitment_id, **kwargs: {'commitment_id': commitment_id, 'state': 'accepted'}
        )
        self.workspace._maybe_block_commitment_settlement = lambda *args, **kwargs: (None, None)
        self.workspace.record_settlement_ref = (
            lambda commitment_id, settlement_ref, org_id=None: calls.setdefault(
                'settlement_ref',
                (commitment_id, settlement_ref, org_id),
            )
        )
        self.workspace.settle_commitment = (
            lambda commitment_id, by, org_id=None, note='': {
                'commitment_id': commitment_id,
                'state': 'settled',
                'settled_by': by,
                'delivery_refs': [
                    {
                        'message_type': 'execution_request',
                        'envelope_id': 'fed_exec',
                        'target_host_id': 'host_alpha',
                        'target_institution_id': 'org_alpha',
                        'receipt_id': 'fedrcpt_exec',
                        'receiver_host_id': 'host_alpha',
                        'receiver_institution_id': 'org_alpha',
                        'warrant_id': 'war_sender',
                    }
                ],
            }
        )
        self.workspace.log_event = lambda *args, **kwargs: calls.setdefault('audit', []).append((args, kwargs))

        original_inbox_entry = self.workspace._federation_inbox_entry
        self.workspace._federation_inbox_entry = lambda *args, **kwargs: {
            'envelope_id': 'fed_settle',
            'state': kwargs.get('state', 'received'),
            'processed_at': '2026-03-22T00:00:00Z' if kwargs.get('state') == 'processed' else '',
        }
        self.workspace.preflight_settlement_adapter = lambda adapter_id, **kwargs: {
            'preflight_ok': True,
            'requested_adapter_id': adapter_id,
            'currency': 'USDC',
            'normalized_proof': {
                'proof_type': 'ledger_transaction',
                'verification_state': 'host_ledger_final',
                'finality_state': 'host_local_final',
                'reversal_or_dispute_capability': 'court_case',
                'proof': {'mode': 'institution_transactions_journal'},
            },
            'contract': {
                'adapter_id': adapter_id,
                'execution_mode': 'host_ledger',
            },
        }
        try:
            claims = FederationEnvelopeClaims(
                envelope_id='fed_settle',
                source_host_id='host_alpha',
                source_institution_id='org_alpha',
                target_host_id='host_beta',
                target_institution_id='org_a',
                actor_type='user',
                actor_id='user_alpha',
                session_id='ses_alpha',
                boundary_name='federation_gateway',
                identity_model='signed_host_service',
                message_type='settlement_notice',
                payload_hash='hash_demo',
                warrant_id='war_demo',
                commitment_id='cmt_demo',
            )
            receipt = {
                'receipt_id': 'fedrcpt_demo',
                'accepted_at': '2026-03-22T00:00:00Z',
            }
            processing = self.workspace._process_received_federation_message(
                'org_a',
                claims,
                receipt,
                payload={
                    'proposal_id': 'pay_demo',
                    'tx_ref': 'tx_demo',
                    'settlement_adapter': 'internal_ledger',
                    'envelope_id': 'fed_exec',
                },
            )
        finally:
            self.workspace._federation_inbox_entry = original_inbox_entry

        self.assertTrue(processing['applied'])
        self.assertEqual(processing['reason'], 'settlement_notice_applied')
        self.assertEqual(processing['state'], 'processed')
        self.assertEqual(processing['commitment']['state'], 'settled')
        self.assertEqual(processing['settlement_ref']['tx_ref'], 'tx_demo')
        self.assertEqual(processing['settlement_ref']['proposal_id'], 'pay_demo')
        self.assertEqual(processing['settlement_ref']['proof_type'], 'ledger_transaction')
        self.assertEqual(processing['settlement_ref']['verification_state'], 'host_ledger_final')
        self.assertEqual(processing['settlement_ref']['finality_state'], 'host_local_final')
        self.assertEqual(
            processing['settlement_ref']['settlement_adapter_contract']['adapter_id'],
            'internal_ledger',
        )
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
        self.assertEqual(processing['warrant']['warrant_id'], 'war_sender')
        self.assertEqual(processing['warrant']['execution_state'], 'executed')
        self.assertEqual(processing['warrant']['execution_refs']['envelope_id'], 'fed_exec')
        self.assertEqual(processing['warrant']['execution_refs']['completion_envelope_id'], 'fed_settle')
        self.assertTrue(processing['settlement_preflight']['preflight_ok'])
        self.assertEqual(processing['inbox_entry']['state'], 'processed')
        self.assertEqual(calls['settlement_ref'][0], 'cmt_demo')
        self.assertEqual(calls['settlement_ref'][2], 'org_a')

    def test_process_received_settlement_notice_opens_case_when_adapter_invalid(self):
        from federation import FederationEnvelopeClaims
        from runtime_host import default_host_identity

        audit_events = []
        self.workspace.validate_commitment_for_settlement = (
            lambda commitment_id, **kwargs: {'commitment_id': commitment_id, 'state': 'accepted'}
        )
        self.workspace._maybe_block_commitment_settlement = lambda *args, **kwargs: (None, None)
        self.workspace.preflight_settlement_adapter = lambda adapter_id, **kwargs: {
            'preflight_ok': False,
            'requested_adapter_id': adapter_id,
            'error_type': 'unknown_adapter',
            'error': f'Unknown settlement_adapter {adapter_id!r}',
        }
        self.workspace.ensure_case_for_delivery_failure = lambda *args, **kwargs: (
            {
                'case_id': 'case_invalid_notice',
                'claim_type': 'invalid_settlement_notice',
                'status': 'open',
                'linked_commitment_id': 'cmt_demo',
                'target_host_id': 'host_alpha',
            },
            True,
        )
        self.workspace._maybe_suspend_peer_for_case = lambda *args, **kwargs: {
            'applied': True,
            'peer_host_id': 'host_alpha',
            'trust_state': 'suspended',
        }
        self.workspace.mark_warrant_executed = lambda *args, **kwargs: self.fail('sender warrant should not finalize')
        self.workspace.record_settlement_ref = lambda *args, **kwargs: self.fail('settlement ref should not be recorded')
        self.workspace.settle_commitment = lambda *args, **kwargs: self.fail('commitment should not settle')
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append((args, kwargs))

        claims = FederationEnvelopeClaims(
            envelope_id='fed_invalid_settle',
            source_host_id='host_alpha',
            source_institution_id='org_alpha',
            target_host_id='host_beta',
            target_institution_id='org_a',
            actor_type='service',
            actor_id='peer:host_alpha',
            session_id='ses_alpha',
            boundary_name='federation_gateway',
            identity_model='signed_host_service',
            message_type='settlement_notice',
            payload_hash='hash_invalid',
            warrant_id='war_demo',
            commitment_id='cmt_demo',
        )
        processing = self.workspace._process_received_federation_message(
            'org_a',
            claims,
            {'receipt_id': 'fedrcpt_invalid', 'accepted_at': '2026-03-22T00:00:00Z'},
            payload={
                'proposal_id': 'pay_demo',
                'tx_ref': 'tx_demo',
                'settlement_adapter': 'imaginary_chain',
            },
        )
        self.assertFalse(processing['applied'])
        self.assertEqual(processing['reason'], 'invalid_settlement_notice')
        self.assertEqual(processing['case']['case_id'], 'case_invalid_notice')
        self.assertTrue(processing['case_created'])
        self.assertEqual(processing['federation_peer']['trust_state'], 'suspended')
        self.assertIsNone(processing.get('warrant'))
        self.assertFalse(processing['settlement_preflight']['preflight_ok'])
        self.assertEqual(processing['settlement_preflight']['error_type'], 'unknown_adapter')
        self.assertEqual(audit_events[-1][0][2], 'federation_settlement_notice_rejected')

    def test_process_received_settlement_notice_rejects_missing_verifier_attestation_for_external_adapter(self):
        from federation import FederationEnvelopeClaims

        audit_events = []
        self.workspace.validate_commitment_for_settlement = (
            lambda commitment_id, **kwargs: {'commitment_id': commitment_id, 'state': 'accepted'}
        )
        self.workspace._maybe_block_commitment_settlement = lambda *args, **kwargs: (None, None)
        self.workspace.ensure_case_for_delivery_failure = lambda *args, **kwargs: (
            {
                'case_id': 'case_missing_attestation',
                'claim_type': 'invalid_settlement_notice',
                'status': 'open',
                'linked_commitment_id': 'cmt_demo',
                'target_host_id': 'host_alpha',
            },
            True,
        )
        self.workspace._maybe_suspend_peer_for_case = lambda *args, **kwargs: {
            'applied': True,
            'peer_host_id': 'host_alpha',
            'trust_state': 'suspended',
        }
        self.workspace.mark_warrant_executed = lambda *args, **kwargs: self.fail('sender warrant should not finalize')
        self.workspace.record_settlement_ref = lambda *args, **kwargs: self.fail('settlement ref should not be recorded')
        self.workspace.settle_commitment = lambda *args, **kwargs: self.fail('commitment should not settle')
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append((args, kwargs))
        self.workspace.preflight_settlement_adapter = lambda adapter_id, **kwargs: {
            'preflight_ok': True,
            'requested_adapter_id': adapter_id,
            'currency': 'USDC',
            'normalized_proof': {
                'proof_type': 'onchain_receipt',
                'verification_state': 'external_verification_required',
                'finality_state': 'external_chain_finality',
                'reversal_or_dispute_capability': 'court_case_plus_chain_review',
                'proof': {'reference': 'base://receipt/demo'},
            },
            'contract': {
                'adapter_id': adapter_id,
                'execution_mode': 'external_chain',
                'settlement_path': 'x402_onchain',
                'requires_verifier_attestation': True,
            },
        }

        claims = FederationEnvelopeClaims(
            envelope_id='fed_missing_attestation',
            source_host_id='host_alpha',
            source_institution_id='org_alpha',
            target_host_id='host_beta',
            target_institution_id='org_a',
            actor_type='service',
            actor_id='peer:host_alpha',
            session_id='ses_alpha',
            boundary_name='federation_gateway',
            identity_model='signed_host_service',
            message_type='settlement_notice',
            payload_hash='hash_missing_attestation',
            warrant_id='war_demo',
            commitment_id='cmt_demo',
        )
        processing = self.workspace._process_received_federation_message(
            'org_a',
            claims,
            {'receipt_id': 'fedrcpt_missing_attestation', 'accepted_at': '2026-03-22T00:00:00Z'},
            payload={
                'proposal_id': 'pay_demo',
                'tx_ref': 'tx_demo',
                'settlement_adapter': 'base_usdc_x402',
                'tx_hash': '0xbase123',
                'proof': {
                    'reference': 'base://receipt/demo',
                    'payer_wallet': '0xabc123',
                },
            },
        )
        self.assertFalse(processing['applied'])
        self.assertEqual(processing['reason'], 'invalid_settlement_notice')
        self.assertEqual(processing['case']['case_id'], 'case_missing_attestation')
        self.assertTrue(processing['case_created'])
        self.assertEqual(processing['federation_peer']['trust_state'], 'suspended')
        self.assertFalse(processing['settlement_preflight']['preflight_ok'])
        self.assertEqual(processing['settlement_preflight']['error_type'], 'validation_error')
        self.assertIn('verifier attestation', processing['error'])
        self.assertEqual(audit_events[-1][0][2], 'federation_settlement_notice_rejected')

    def test_process_received_settlement_notice_rejects_contract_digest_mismatch(self):
        from federation import FederationEnvelopeClaims

        audit_events = []
        self.workspace.validate_commitment_for_settlement = (
            lambda commitment_id, **kwargs: {'commitment_id': commitment_id, 'state': 'accepted'}
        )
        self.workspace._maybe_block_commitment_settlement = lambda *args, **kwargs: (None, None)
        self.workspace.ensure_case_for_delivery_failure = lambda *args, **kwargs: (
            {
                'case_id': 'case_digest_mismatch',
                'claim_type': 'invalid_settlement_notice',
                'status': 'open',
                'linked_commitment_id': 'cmt_demo',
                'target_host_id': 'host_alpha',
            },
            True,
        )
        self.workspace._maybe_suspend_peer_for_case = lambda *args, **kwargs: {
            'applied': True,
            'peer_host_id': 'host_alpha',
            'trust_state': 'suspended',
        }
        self.workspace.mark_warrant_executed = lambda *args, **kwargs: self.fail('sender warrant should not finalize')
        self.workspace.record_settlement_ref = lambda *args, **kwargs: self.fail('settlement ref should not be recorded')
        self.workspace.settle_commitment = lambda *args, **kwargs: self.fail('commitment should not settle')
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append((args, kwargs))
        self.workspace.preflight_settlement_adapter = lambda adapter_id, **kwargs: {
            'preflight_ok': True,
            'requested_adapter_id': adapter_id,
            'currency': 'USDC',
            'normalized_proof': {
                'proof_type': 'ledger_transaction',
                'verification_state': 'host_ledger_final',
                'finality_state': 'host_local_final',
                'reversal_or_dispute_capability': 'court_case',
                'proof': {'mode': 'institution_transactions_journal'},
            },
            'contract': {
                'adapter_id': adapter_id,
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
            envelope_id='fed_invalid_digest',
            source_host_id='host_alpha',
            source_institution_id='org_alpha',
            target_host_id='host_beta',
            target_institution_id='org_a',
            actor_type='service',
            actor_id='peer:host_alpha',
            session_id='ses_alpha',
            boundary_name='federation_gateway',
            identity_model='signed_host_service',
            message_type='settlement_notice',
            payload_hash='hash_invalid',
            warrant_id='war_demo',
            commitment_id='cmt_demo',
        )
        processing = self.workspace._process_received_federation_message(
            'org_a',
            claims,
            {'receipt_id': 'fedrcpt_invalid', 'accepted_at': '2026-03-22T00:00:00Z'},
            payload={
                'proposal_id': 'pay_demo',
                'tx_ref': 'tx_demo',
                'settlement_adapter': 'internal_ledger',
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
        self.assertEqual(processing['reason'], 'invalid_settlement_notice')
        self.assertEqual(processing['case']['case_id'], 'case_digest_mismatch')
        self.assertEqual(processing['federation_peer']['trust_state'], 'suspended')
        self.assertEqual(processing['settlement_preflight']['error_type'], 'validation_error')
        self.assertIn('contract drifted', processing['error'])
        self.assertEqual(audit_events[-1][0][2], 'federation_settlement_notice_rejected')

    def test_process_received_settlement_notice_respects_case_block(self):
        from federation import FederationEnvelopeClaims

        self.workspace.validate_commitment_for_settlement = (
            lambda commitment_id, **kwargs: {'commitment_id': commitment_id, 'state': 'accepted'}
        )
        self.workspace._maybe_block_commitment_settlement = lambda *args, **kwargs: (
            {'case_id': 'case_demo', 'status': 'open', 'linked_commitment_id': 'cmt_demo'},
            {'applied': True, 'warrant_id': 'war_demo', 'court_review_state': 'stayed'},
        )
        self.workspace.record_settlement_ref = lambda *args, **kwargs: self.fail('settlement ref should not be recorded')
        self.workspace.settle_commitment = lambda *args, **kwargs: self.fail('commitment should not settle')
        self.workspace.log_event = lambda *args, **kwargs: None

        claims = FederationEnvelopeClaims(
            envelope_id='fed_settle_blocked',
            source_host_id='host_alpha',
            source_institution_id='org_alpha',
            target_host_id='host_beta',
            target_institution_id='org_a',
            actor_type='service',
            actor_id='peer:host_alpha',
            session_id='',
            boundary_name='federation_gateway',
            identity_model='signed_host_service',
            message_type='settlement_notice',
            payload_hash='hash_demo',
            warrant_id='war_demo',
            commitment_id='cmt_demo',
        )
        processing = self.workspace._process_received_federation_message(
            'org_a',
            claims,
            {'receipt_id': 'fedrcpt_demo', 'accepted_at': '2026-03-22T00:00:00Z'},
            payload={'tx_ref': 'tx_demo'},
        )
        self.assertFalse(processing['applied'])
        self.assertEqual(processing['reason'], 'case_blocked')
        self.assertEqual(processing['state'], 'received')
        self.assertEqual(processing['case']['case_id'], 'case_demo')

    def test_process_received_case_notice_open_is_idempotent_and_resolve_thaws_peer(self):
        from federation import FederationEnvelopeClaims

        store = {}
        audit_actions = []
        calls = {
            'open_case': 0,
            'suspend_peer': 0,
            'stay_warrant': 0,
            'restore_peer': 0,
        }

        original_inbox_entry = self.workspace._federation_inbox_entry
        original_lookup = self.workspace._case_notice_store_case_lookup
        original_store = self.workspace._case_notice_store_case
        original_open_case = self.workspace.open_case
        original_suspend_peer = self.workspace._maybe_suspend_peer_for_case
        original_stay_warrant = self.workspace._maybe_stay_warrant_for_case
        original_restore_peer = self.workspace._maybe_restore_peer_for_case
        original_log_event = self.workspace.log_event

        def _lookup(bound_org_id, source_host_id, source_institution_id, source_case_id):
            return store.get((source_host_id, source_institution_id, source_case_id))

        def _persist(bound_org_id, case_record):
            key = (
                (case_record.get('metadata') or {}).get('federation_source_host_id'),
                (case_record.get('metadata') or {}).get('federation_source_institution_id'),
                (case_record.get('metadata') or {}).get('federation_source_case_id'),
            )
            store[key] = dict(case_record)
            return case_record

        def _open_case(
            org_id,
            claim_type,
            actor_id,
            *,
            target_host_id='',
            target_institution_id='',
            linked_commitment_id='',
            linked_warrant_id='',
            evidence_refs=None,
            note='',
            metadata=None,
        ):
            calls['open_case'] += 1
            record = {
                'case_id': f'case_mirror_{calls["open_case"]}',
                'institution_id': org_id,
                'source_institution_id': org_id,
                'target_host_id': target_host_id,
                'target_institution_id': target_institution_id,
                'claim_type': claim_type,
                'linked_commitment_id': linked_commitment_id,
                'linked_warrant_id': linked_warrant_id,
                'evidence_refs': list(evidence_refs or []),
                'status': 'open',
                'opened_by': actor_id,
                'opened_at': '2026-03-22T00:00:00Z',
                'updated_at': '2026-03-22T00:00:00Z',
                'reviewed_by': '',
                'reviewed_at': '',
                'review_note': '',
                'resolution': '',
                'note': note or '',
                'metadata': dict(metadata or {}),
            }
            _persist(org_id, record)
            return record

        def _suspend_peer(case_record, actor_id, **kwargs):
            calls['suspend_peer'] += 1
            return {
                'applied': True,
                'peer_host_id': case_record.get('target_host_id', ''),
                'trust_state': 'suspended',
            }

        def _stay_warrant(case_record, actor_id, **kwargs):
            calls['stay_warrant'] += 1
            return {
                'applied': True,
                'warrant_id': case_record.get('linked_warrant_id', ''),
                'court_review_state': 'stayed',
            }

        def _restore_peer(case_record, actor_id, **kwargs):
            calls['restore_peer'] += 1
            return {
                'applied': True,
                'peer_host_id': case_record.get('target_host_id', ''),
                'trust_state': 'trusted',
            }

        self.workspace._federation_inbox_entry = lambda *args, **kwargs: {
            'envelope_id': 'fed_case_notice_demo',
            'state': kwargs.get('state', 'received'),
        }
        self.workspace._case_notice_store_case_lookup = _lookup
        self.workspace._case_notice_store_case = _persist
        self.workspace.open_case = _open_case
        self.workspace._maybe_suspend_peer_for_case = _suspend_peer
        self.workspace._maybe_stay_warrant_for_case = _stay_warrant
        self.workspace._maybe_restore_peer_for_case = _restore_peer
        self.workspace.log_event = lambda *args, **kwargs: audit_actions.append((args, kwargs))

        claims = FederationEnvelopeClaims(
            envelope_id='fed_case_notice_demo',
            source_host_id='host_alpha',
            source_institution_id='org_alpha',
            target_host_id='host_beta',
            target_institution_id='org_beta',
            actor_type='service',
            actor_id='peer:host_alpha',
            session_id='ses_case_notice',
            boundary_name='federation_gateway',
            identity_model='signed_host_service',
            message_type='case_notice',
            payload_hash='hash_case_notice',
            warrant_id='war_case_notice',
            commitment_id='cmt_case_notice',
        )
        payload_open = {
            'case_decision': 'open',
            'source_case_id': 'case_source_1',
            'claim_type': 'misrouted_execution',
            'linked_commitment_id': 'cmt_case_notice',
            'linked_warrant_id': 'war_case_notice',
            'target_host_id': 'host_beta',
            'target_institution_id': 'org_beta',
            'note': 'Mirror open',
            'metadata': {'trace': 'case_notice_demo'},
        }
        payload_resolve = dict(payload_open, case_decision='resolve', note='Mirror resolve')

        try:
            first = self.workspace._process_received_federation_message(
                'org_beta',
                claims,
                {'receipt_id': 'fedrcpt_case_notice', 'accepted_at': '2026-03-22T00:00:00Z'},
                payload=payload_open,
            )
            second = self.workspace._process_received_federation_message(
                'org_beta',
                claims,
                {'receipt_id': 'fedrcpt_case_notice_repeat', 'accepted_at': '2026-03-22T00:01:00Z'},
                payload=payload_open,
            )
            resolved = self.workspace._process_received_federation_message(
                'org_beta',
                claims,
                {'receipt_id': 'fedrcpt_case_notice_resolve', 'accepted_at': '2026-03-22T00:02:00Z'},
                payload=payload_resolve,
            )
        finally:
            self.workspace._federation_inbox_entry = original_inbox_entry
            self.workspace._case_notice_store_case_lookup = original_lookup
            self.workspace._case_notice_store_case = original_store
            self.workspace.open_case = original_open_case
            self.workspace._maybe_suspend_peer_for_case = original_suspend_peer
            self.workspace._maybe_stay_warrant_for_case = original_stay_warrant
            self.workspace._maybe_restore_peer_for_case = original_restore_peer
            self.workspace.log_event = original_log_event

        self.assertTrue(first['applied'])
        self.assertTrue(first['case_created'])
        self.assertEqual(first['case']['status'], 'open')
        self.assertEqual(first['case']['target_host_id'], 'host_alpha')
        self.assertEqual(first['case']['target_institution_id'], 'org_alpha')
        self.assertEqual(first['case']['metadata']['federation_source_case_id'], 'case_source_1')
        self.assertEqual(first['federation_peer']['trust_state'], 'suspended')
        self.assertEqual(first['warrant']['court_review_state'], 'stayed')

        self.assertTrue(second['applied'])
        self.assertFalse(second['case_created'])
        self.assertEqual(second['case']['case_id'], first['case']['case_id'])
        self.assertEqual(len(store), 1)
        self.assertEqual(calls['open_case'], 1)
        self.assertEqual(calls['suspend_peer'], 2)
        self.assertEqual(calls['stay_warrant'], 2)

        self.assertTrue(resolved['applied'])
        self.assertEqual(resolved['case']['status'], 'resolved')
        self.assertEqual(resolved['case']['case_id'], first['case']['case_id'])
        self.assertEqual(resolved['federation_peer']['trust_state'], 'trusted')
        self.assertEqual(calls['restore_peer'], 1)
        self.assertEqual(
            [event[0][2] for event in audit_actions if event[0][2].startswith('federation_case_notice_')],
            ['federation_case_notice_applied', 'federation_case_notice_applied', 'federation_case_notice_applied'],
        )

    def test_process_received_case_notice_blocks_invalid_payload_and_missing_mirror(self):
        from federation import FederationEnvelopeClaims

        audit_actions = []
        original_inbox_entry = self.workspace._federation_inbox_entry
        original_lookup = self.workspace._case_notice_store_case_lookup
        original_store = self.workspace._case_notice_store_case
        original_open_case = self.workspace.open_case
        original_log_event = self.workspace.log_event

        self.workspace._federation_inbox_entry = lambda *args, **kwargs: {
            'envelope_id': 'fed_case_notice_bad',
            'state': kwargs.get('state', 'received'),
        }
        self.workspace._case_notice_store_case_lookup = lambda *args, **kwargs: None
        self.workspace._case_notice_store_case = lambda *args, **kwargs: self.fail('should not persist invalid or missing-mirror case_notice')
        self.workspace.open_case = lambda *args, **kwargs: self.fail('should not open a mirrored case for invalid or missing-mirror case_notice')
        self.workspace.log_event = lambda *args, **kwargs: audit_actions.append((args, kwargs))

        claims = FederationEnvelopeClaims(
            envelope_id='fed_case_notice_bad',
            source_host_id='host_alpha',
            source_institution_id='org_alpha',
            target_host_id='host_beta',
            target_institution_id='org_beta',
            actor_type='service',
            actor_id='peer:host_alpha',
            session_id='ses_case_notice',
            boundary_name='federation_gateway',
            identity_model='signed_host_service',
            message_type='case_notice',
            payload_hash='hash_case_notice_bad',
            warrant_id='war_case_notice',
            commitment_id='cmt_case_notice',
        )

        try:
            invalid = self.workspace._process_received_federation_message(
                'org_beta',
                claims,
                {'receipt_id': 'fedrcpt_case_notice_bad', 'accepted_at': '2026-03-22T00:00:00Z'},
                payload={
                    'case_decision': 'open',
                    'source_case_id': 'case_source_1',
                    'claim_type': 'misrouted_execution',
                    'linked_commitment_id': 'cmt_case_notice',
                    'linked_warrant_id': 'war_case_notice',
                    'target_institution_id': 'org_beta',
                    'note': 'Missing target host should block',
                    'metadata': {},
                },
            )
            missing = self.workspace._process_received_federation_message(
                'org_beta',
                claims,
                {'receipt_id': 'fedrcpt_case_notice_missing', 'accepted_at': '2026-03-22T00:01:00Z'},
                payload={
                    'case_decision': 'resolve',
                    'source_case_id': 'case_source_missing',
                    'claim_type': 'misrouted_execution',
                    'linked_commitment_id': 'cmt_case_notice',
                    'linked_warrant_id': 'war_case_notice',
                    'target_host_id': 'host_beta',
                    'target_institution_id': 'org_beta',
                    'note': 'No mirrored case should block',
                    'metadata': {},
                },
            )
        finally:
            self.workspace._federation_inbox_entry = original_inbox_entry
            self.workspace._case_notice_store_case_lookup = original_lookup
            self.workspace._case_notice_store_case = original_store
            self.workspace.open_case = original_open_case
            self.workspace.log_event = original_log_event

        self.assertFalse(invalid['applied'])
        self.assertEqual(invalid['reason'], 'invalid_case_notice')
        self.assertIn('target_host_id is required', invalid['error'])
        self.assertEqual(audit_actions[-1][0][2], 'federation_case_notice_blocked')

        self.assertFalse(missing['applied'])
        self.assertEqual(missing['reason'], 'case_not_found')
        self.assertIn('Mirrored case not found', missing['error'])
        self.assertEqual(audit_actions[-1][0][2], 'federation_case_notice_blocked')

    def test_process_received_commitment_proposal_records_mirrored_commitment(self):
        from federation import FederationEnvelopeClaims

        audit_events = []
        original_inbox_entry = self.workspace._federation_inbox_entry
        self.workspace._federation_inbox_entry = lambda *args, **kwargs: {
            'envelope_id': 'fed_commit_prop_demo',
            'state': kwargs.get('state', 'received'),
        }
        self.workspace.sync_federated_commitment_proposal = lambda *args, **kwargs: ({
            'commitment_id': 'cmt_demo',
            'source_host_id': 'host_alpha',
            'source_institution_id': 'org_alpha',
            'target_host_id': 'host_beta',
            'target_institution_id': 'org_a',
            'status': 'proposed',
            'metadata': {
                'federation_source_host_id': 'host_alpha',
                'federation_envelope_id': 'fed_commit_prop_demo',
            },
        }, True)
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append((args, kwargs))
        try:
            claims = FederationEnvelopeClaims(
                envelope_id='fed_commit_prop_demo',
                source_host_id='host_alpha',
                source_institution_id='org_alpha',
                target_host_id='host_beta',
                target_institution_id='org_a',
                actor_type='user',
                actor_id='user_owner_alpha',
                session_id='ses_alpha',
                boundary_name='federation_gateway',
                identity_model='signed_host_service',
                message_type='commitment_proposal',
                payload_hash='hash_demo',
                warrant_id='war_commit_demo',
                commitment_id='cmt_demo',
            )
            processing = self.workspace._process_received_federation_message(
                'org_a',
                claims,
                {'receipt_id': 'fedrcpt_commit_prop', 'accepted_at': '2026-03-22T00:00:00Z'},
                payload={
                    'summary': 'Deliver shared brief',
                    'terms_payload': {'scope': 'shared-brief'},
                    'metadata': {'channel': 'federation'},
                },
            )
        finally:
            self.workspace._federation_inbox_entry = original_inbox_entry

        self.assertTrue(processing['applied'])
        self.assertEqual(processing['reason'], 'commitment_proposal_recorded')
        self.assertTrue(processing['created'])
        self.assertEqual(processing['commitment']['commitment_id'], 'cmt_demo')
        self.assertEqual(processing['commitment']['source_host_id'], 'host_alpha')
        self.assertEqual(processing['inbox_entry']['state'], 'processed')
        self.assertEqual(audit_events[-1][0][2], 'federation_commitment_proposal_recorded')

    def test_process_received_commitment_acceptance_marks_commitment_accepted(self):
        from federation import FederationEnvelopeClaims

        audit_events = []
        original_inbox_entry = self.workspace._federation_inbox_entry
        self.workspace._federation_inbox_entry = lambda *args, **kwargs: {
            'envelope_id': 'fed_commit_accept_demo',
            'state': kwargs.get('state', 'received'),
        }
        self.workspace.get_commitment = lambda commitment_id, org_id=None: {
            'commitment_id': commitment_id,
            'status': 'proposed',
            'target_host_id': 'host_beta',
            'target_institution_id': 'org_beta',
        }
        self.workspace.accept_commitment = lambda commitment_id, by, **kwargs: {
            'commitment_id': commitment_id,
            'status': 'accepted',
            'accepted_by': by,
            'review_note': kwargs.get('note', ''),
        }
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append((args, kwargs))
        try:
            claims = FederationEnvelopeClaims(
                envelope_id='fed_commit_accept_demo',
                source_host_id='host_beta',
                source_institution_id='org_beta',
                target_host_id='host_alpha',
                target_institution_id='org_a',
                actor_type='user',
                actor_id='user_owner_beta',
                session_id='ses_beta',
                boundary_name='federation_gateway',
                identity_model='signed_host_service',
                message_type='commitment_acceptance',
                payload_hash='hash_demo',
                warrant_id='war_accept_demo',
                commitment_id='cmt_demo',
            )
            processing = self.workspace._process_received_federation_message(
                'org_a',
                claims,
                {'receipt_id': 'fedrcpt_commit_accept', 'accepted_at': '2026-03-22T00:00:00Z'},
                payload={'note': 'Accepted on beta'},
            )
        finally:
            self.workspace._federation_inbox_entry = original_inbox_entry

        self.assertTrue(processing['applied'])
        self.assertEqual(processing['reason'], 'commitment_acceptance_recorded')
        self.assertTrue(processing['accepted'])
        self.assertEqual(processing['commitment']['accepted_by'], 'user_owner_beta')
        self.assertEqual(processing['inbox_entry']['state'], 'processed')
        self.assertEqual(audit_events[-1][0][2], 'federation_commitment_acceptance_recorded')

    def test_process_received_commitment_breach_notice_marks_commitment_breached_and_opens_case(self):
        from federation import FederationEnvelopeClaims

        audit_events = []
        original_inbox_entry = self.workspace._federation_inbox_entry
        self.workspace._federation_inbox_entry = lambda *args, **kwargs: {
            'envelope_id': 'fed_commit_breach_demo',
            'state': kwargs.get('state', 'received'),
        }
        self.workspace.get_commitment = lambda commitment_id, org_id=None: {
            'commitment_id': commitment_id,
            'status': 'accepted',
            'target_host_id': 'host_beta',
            'target_institution_id': 'org_beta',
            'warrant_id': 'war_commit_demo',
        }
        self.workspace.breach_commitment = lambda commitment_id, by, **kwargs: {
            'commitment_id': commitment_id,
            'status': 'breached',
            'target_host_id': 'host_beta',
            'target_institution_id': 'org_beta',
            'warrant_id': 'war_commit_demo',
            'breached_by': by,
            'review_note': kwargs.get('note', ''),
        }
        self.workspace._maybe_open_case_for_commitment_breach = lambda commitment, actor_id, **kwargs: ({
            'case_id': 'case_breach_demo',
            'claim_type': 'breach_of_commitment',
            'status': 'open',
            'linked_commitment_id': commitment['commitment_id'],
            'linked_warrant_id': commitment['warrant_id'],
        }, True)
        self.workspace._maybe_suspend_peer_for_case = lambda case_record, actor_id, **kwargs: {
            'applied': True,
            'peer_host_id': case_record.get('target_host_id', ''),
            'trust_state': 'suspended',
        }
        self.workspace._maybe_stay_warrant_for_case = lambda *args, **kwargs: {
            'applied': True,
            'warrant_id': 'war_commit_demo',
            'court_review_state': 'stayed',
        }
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append((args, kwargs))
        try:
            claims = FederationEnvelopeClaims(
                envelope_id='fed_commit_breach_demo',
                source_host_id='host_beta',
                source_institution_id='org_beta',
                target_host_id='host_alpha',
                target_institution_id='org_a',
                actor_type='user',
                actor_id='user_owner_beta',
                session_id='ses_beta',
                boundary_name='federation_gateway',
                identity_model='signed_host_service',
                message_type='commitment_breach_notice',
                payload_hash='hash_demo',
                warrant_id='war_breach_demo',
                commitment_id='cmt_demo',
            )
            processing = self.workspace._process_received_federation_message(
                'org_a',
                claims,
                {'receipt_id': 'fedrcpt_commit_breach', 'accepted_at': '2026-03-22T00:00:00Z'},
                payload={'note': 'Breach recorded on beta'},
            )
        finally:
            self.workspace._federation_inbox_entry = original_inbox_entry

        self.assertTrue(processing['applied'])
        self.assertEqual(processing['reason'], 'commitment_breach_notice_recorded')
        self.assertTrue(processing['breached'])
        self.assertEqual(processing['commitment']['breached_by'], 'user_owner_beta')
        self.assertEqual(processing['case']['case_id'], 'case_breach_demo')
        self.assertEqual(processing['federation_peer']['trust_state'], 'suspended')
        self.assertEqual(processing['warrant']['court_review_state'], 'stayed')
        self.assertEqual(processing['inbox_entry']['state'], 'processed')
        self.assertEqual(audit_events[-1][0][2], 'federation_commitment_breach_notice_recorded')

    def test_process_received_court_notice_reviews_sender_warrant_and_records_delivery_ref(self):
        from federation import FederationEnvelopeClaims

        audit_events = []
        original_inbox_entry = self.workspace._federation_inbox_entry
        original_get_warrant = self.workspace.get_warrant
        original_review_warrant = self.workspace.review_warrant
        original_get_commitment = self.workspace.get_commitment
        original_record_delivery_ref = self.workspace.record_delivery_ref
        original_query_events = self.workspace.query_events
        original_log_event = self.workspace.log_event

        commitment = {
            'commitment_id': 'cmt_demo',
            'status': 'accepted',
            'delivery_refs': [
                {
                    'message_type': 'execution_request',
                    'envelope_id': 'fed_exec_demo',
                    'target_host_id': 'host_beta',
                    'target_institution_id': 'org_beta',
                    'warrant_id': 'war_sender',
                }
            ],
        }
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
            'envelope_id': 'fed_court_demo',
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
        self.workspace.get_commitment = lambda commitment_id, org_id=None: (
            dict(commitment) if commitment_id == 'cmt_demo' else None
        )
        self.workspace.record_delivery_ref = lambda commitment_id, delivery_ref, **kwargs: {
            **dict(commitment),
            'delivery_refs': list(commitment['delivery_refs']) + [dict(delivery_ref)],
        }
        self.workspace.query_events = lambda **kwargs: []
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append((args, kwargs))
        try:
            claims = FederationEnvelopeClaims(
                envelope_id='fed_court_demo',
                source_host_id='host_beta',
                source_institution_id='org_beta',
                target_host_id='host_alpha',
                target_institution_id='org_a',
                actor_type='user',
                actor_id='user_owner_beta',
                session_id='ses_beta',
                boundary_name='federation_gateway',
                identity_model='signed_host_service',
                message_type='court_notice',
                payload_hash='hash_court_demo',
                warrant_id='war_sender',
                commitment_id='cmt_demo',
            )
            processing = self.workspace._process_received_federation_message(
                'org_a',
                claims,
                {'receipt_id': 'fedrcpt_court_demo', 'accepted_at': '2026-03-22T00:00:00Z'},
                payload={
                    'court_decision': 'stay',
                    'sender_warrant_id': 'war_sender',
                    'local_warrant_id': 'war_local_beta',
                    'source_execution_envelope_id': 'fed_exec_demo',
                    'source_execution_job_id': 'fej_demo',
                    'source_execution_receipt_id': 'fedrcpt_exec_demo',
                    'local_court_review_state': 'stayed',
                    'local_execution_state': 'ready',
                    'target_host_id': 'host_alpha',
                    'target_institution_id': 'org_a',
                    'note': 'Receiver hold',
                    'metadata': {'trace': 'court_notice_demo'},
                },
            )
        finally:
            self.workspace._federation_inbox_entry = original_inbox_entry
            self.workspace.get_warrant = original_get_warrant
            self.workspace.review_warrant = original_review_warrant
            self.workspace.get_commitment = original_get_commitment
            self.workspace.record_delivery_ref = original_record_delivery_ref
            self.workspace.query_events = original_query_events
            self.workspace.log_event = original_log_event

        self.assertTrue(processing['applied'])
        self.assertEqual(processing['reason'], 'court_notice_applied')
        self.assertEqual(processing['warrant']['warrant_id'], 'war_sender')
        self.assertEqual(processing['warrant']['court_review_state'], 'stayed')
        self.assertEqual(processing['warrant']['reviewed_by'], 'user_owner_beta')
        self.assertEqual(processing['delivery_ref']['message_type'], 'court_notice')
        self.assertEqual(processing['delivery_ref']['local_warrant_id'], 'war_local_beta')
        self.assertEqual(processing['outbound_execution_ref']['envelope_id'], 'fed_exec_demo')
        self.assertEqual(processing['inbox_entry']['state'], 'processed')
        self.assertEqual(audit_events[-1][0][2], 'federation_court_notice_applied')

    def test_process_received_court_notice_blocks_missing_sender_reference(self):
        from federation import FederationEnvelopeClaims

        audit_events = []
        original_inbox_entry = self.workspace._federation_inbox_entry
        original_get_warrant = self.workspace.get_warrant
        original_get_commitment = self.workspace.get_commitment
        original_query_events = self.workspace.query_events
        original_log_event = self.workspace.log_event

        self.workspace._federation_inbox_entry = lambda *args, **kwargs: {
            'envelope_id': 'fed_court_bad',
            'state': kwargs.get('state', 'received'),
        }
        self.workspace.get_warrant = lambda warrant_id, org_id=None: {
            'warrant_id': 'war_sender',
            'action_class': 'federated_execution',
            'boundary_name': 'federation_gateway',
            'court_review_state': 'approved',
            'execution_state': 'ready',
        }
        self.workspace.get_commitment = lambda commitment_id, org_id=None: {
            'commitment_id': commitment_id,
            'status': 'accepted',
            'delivery_refs': [],
        }
        self.workspace.query_events = lambda **kwargs: []
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append((args, kwargs))
        try:
            claims = FederationEnvelopeClaims(
                envelope_id='fed_court_bad',
                source_host_id='host_beta',
                source_institution_id='org_beta',
                target_host_id='host_alpha',
                target_institution_id='org_a',
                actor_type='user',
                actor_id='user_owner_beta',
                session_id='ses_beta',
                boundary_name='federation_gateway',
                identity_model='signed_host_service',
                message_type='court_notice',
                payload_hash='hash_court_bad',
                warrant_id='war_sender',
                commitment_id='cmt_demo',
            )
            processing = self.workspace._process_received_federation_message(
                'org_a',
                claims,
                {'receipt_id': 'fedrcpt_court_bad', 'accepted_at': '2026-03-22T00:00:00Z'},
                payload={
                    'court_decision': 'stay',
                    'sender_warrant_id': 'war_sender',
                    'local_warrant_id': 'war_local_beta',
                    'source_execution_envelope_id': 'fed_exec_missing',
                    'target_host_id': 'host_alpha',
                    'target_institution_id': 'org_a',
                    'note': 'Receiver hold',
                    'metadata': {},
                },
            )
        finally:
            self.workspace._federation_inbox_entry = original_inbox_entry
            self.workspace.get_warrant = original_get_warrant
            self.workspace.get_commitment = original_get_commitment
            self.workspace.query_events = original_query_events
            self.workspace.log_event = original_log_event

        self.assertFalse(processing['applied'])
        self.assertEqual(processing['reason'], 'invalid_court_notice')
        self.assertIn("No outbound execution_request proof matches", processing['error'])
        self.assertEqual(audit_events[-1][0][2], 'federation_court_notice_blocked')

    def test_process_received_case_notice_opens_idempotently_and_resolves_same_mirror(self):
        from federation import FederationEnvelopeClaims

        store = {'cases': {}}
        original_load_store = self.workspace.cases_module._load_store
        original_save_store = self.workspace.cases_module._save_store
        suspend_calls = []
        restore_calls = []
        try:
            self.workspace.cases_module._load_store = lambda org_id=None: {
                'cases': {key: dict(value) for key, value in store['cases'].items()},
            }
            self.workspace.cases_module._save_store = lambda data, org_id=None: store.__setitem__(
                'cases',
                {key: dict(value) for key, value in (data.get('cases') or {}).items()},
            )
            self.workspace.list_cases = lambda org_id=None: list(store['cases'].values())

            def fake_open_case(org_id, claim_type, actor_id, **kwargs):
                record = {
                    'case_id': 'case_mirror_demo',
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

            self.workspace.open_case = fake_open_case
            self.workspace._maybe_suspend_peer_for_case = lambda case_record, actor_id, **kwargs: (
                suspend_calls.append(case_record['case_id'])
                or {
                    'applied': True,
                    'peer_host_id': case_record.get('target_host_id', ''),
                    'trust_state': 'suspended',
                }
            )
            self.workspace._maybe_stay_warrant_for_case = lambda *args, **kwargs: {
                'applied': True,
                'court_review_state': 'stayed',
            }
            self.workspace._maybe_restore_peer_for_case = lambda case_record, actor_id, **kwargs: (
                restore_calls.append(case_record['case_id'])
                or {
                    'applied': True,
                    'peer_host_id': case_record.get('target_host_id', ''),
                    'trust_state': 'trusted',
                }
            )
            self.workspace._federation_inbox_entry = lambda *args, **kwargs: {
                'envelope_id': 'fed_case_open',
                'state': kwargs.get('state', 'received'),
            }
            self.workspace.log_event = lambda *args, **kwargs: None

            open_claims = FederationEnvelopeClaims(
                envelope_id='fed_case_open',
                source_host_id='host_alpha',
                source_institution_id='org_alpha',
                target_host_id='host_beta',
                target_institution_id='org_beta',
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
                'target_host_id': 'host_beta',
                'target_institution_id': 'org_beta',
                'note': 'Open mirrored case',
            }
            first = self.workspace._process_received_federation_message(
                'org_beta',
                open_claims,
                {'receipt_id': 'fedrcpt_case_open', 'accepted_at': '2026-03-22T00:00:00Z'},
                payload=open_payload,
            )
            second = self.workspace._process_received_federation_message(
                'org_beta',
                open_claims,
                {'receipt_id': 'fedrcpt_case_open_2', 'accepted_at': '2026-03-22T00:01:00Z'},
                payload=dict(open_payload, note='Open mirrored case again'),
            )
            resolve_claims = FederationEnvelopeClaims(
                envelope_id='fed_case_resolve',
                source_host_id='host_alpha',
                source_institution_id='org_alpha',
                target_host_id='host_beta',
                target_institution_id='org_beta',
                actor_type='user',
                actor_id='user_alpha',
                session_id='ses_alpha',
                boundary_name='federation_gateway',
                identity_model='signed_host_service',
                message_type='case_notice',
                payload_hash='hash_case_resolve',
            )
            resolved = self.workspace._process_received_federation_message(
                'org_beta',
                resolve_claims,
                {'receipt_id': 'fedrcpt_case_resolve', 'accepted_at': '2026-03-22T00:02:00Z'},
                payload=dict(open_payload, case_decision='resolve', note='Resolved on source'),
            )
        finally:
            self.workspace.cases_module._load_store = original_load_store
            self.workspace.cases_module._save_store = original_save_store

        self.assertTrue(first['applied'])
        self.assertEqual(first['reason'], 'case_notice_applied')
        self.assertTrue(first['case_created'])
        self.assertEqual(first['case']['case_id'], 'case_mirror_demo')
        self.assertEqual(first['case']['target_host_id'], 'host_alpha')
        self.assertEqual(first['case']['target_institution_id'], 'org_alpha')
        self.assertEqual(first['case']['metadata']['federation_source_case_id'], 'case_alpha_demo')
        self.assertEqual(first['federation_peer']['trust_state'], 'suspended')

        self.assertTrue(second['applied'])
        self.assertFalse(second['case_created'])
        self.assertEqual(second['case']['case_id'], 'case_mirror_demo')
        self.assertEqual(len(store['cases']), 1)

        self.assertTrue(resolved['applied'])
        self.assertEqual(resolved['reason'], 'case_notice_applied')
        self.assertEqual(resolved['case']['case_id'], 'case_mirror_demo')
        self.assertEqual(resolved['case']['status'], 'resolved')
        self.assertEqual(resolved['federation_peer']['trust_state'], 'trusted')
        self.assertEqual(suspend_calls, ['case_mirror_demo', 'case_mirror_demo'])
        self.assertEqual(restore_calls, ['case_mirror_demo'])

    def test_process_received_case_notice_rejects_invalid_target_payload(self):
        from federation import FederationEnvelopeClaims

        audit_events = []
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append((args, kwargs))

        claims = FederationEnvelopeClaims(
            envelope_id='fed_case_invalid',
            source_host_id='host_alpha',
            source_institution_id='org_alpha',
            target_host_id='host_beta',
            target_institution_id='org_beta',
            actor_type='user',
            actor_id='user_alpha',
            session_id='ses_alpha',
            boundary_name='federation_gateway',
            identity_model='signed_host_service',
            message_type='case_notice',
            payload_hash='hash_case_invalid',
        )
        processing = self.workspace._process_received_federation_message(
            'org_beta',
            claims,
            {'receipt_id': 'fedrcpt_case_invalid', 'accepted_at': '2026-03-22T00:00:00Z'},
            payload={
                'case_decision': 'open',
                'source_case_id': 'case_alpha_demo',
                'claim_type': 'misrouted_execution',
                'linked_commitment_id': '',
                'linked_warrant_id': '',
                'target_host_id': 'host_gamma',
                'target_institution_id': 'org_beta',
            },
        )

        self.assertFalse(processing['applied'])
        self.assertEqual(processing['reason'], 'invalid_case_notice')
        self.assertIn('target_host_id', processing['error'])
        self.assertEqual(audit_events[-1][0][2], 'federation_case_notice_blocked')

    def test_process_received_case_notice_resolve_requires_existing_mirror(self):
        from federation import FederationEnvelopeClaims

        self.workspace.log_event = lambda *args, **kwargs: None
        self.workspace.list_cases = lambda org_id=None: []

        claims = FederationEnvelopeClaims(
            envelope_id='fed_case_missing',
            source_host_id='host_alpha',
            source_institution_id='org_alpha',
            target_host_id='host_beta',
            target_institution_id='org_beta',
            actor_type='user',
            actor_id='user_alpha',
            session_id='ses_alpha',
            boundary_name='federation_gateway',
            identity_model='signed_host_service',
            message_type='case_notice',
            payload_hash='hash_case_missing',
        )
        processing = self.workspace._process_received_federation_message(
            'org_beta',
            claims,
            {'receipt_id': 'fedrcpt_case_missing', 'accepted_at': '2026-03-22T00:00:00Z'},
            payload={
                'case_decision': 'resolve',
                'source_case_id': 'case_alpha_demo',
                'claim_type': 'misrouted_execution',
                'linked_commitment_id': '',
                'linked_warrant_id': '',
                'target_host_id': 'host_beta',
                'target_institution_id': 'org_beta',
            },
        )

        self.assertFalse(processing['applied'])
        self.assertEqual(processing['reason'], 'case_not_found')
        self.assertIn('Mirrored case not found', processing['error'])

    def test_process_received_execution_request_creates_local_warranted_job(self):
        from federation import FederationEnvelopeClaims

        calls = {}
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
        self.workspace.upsert_execution_job = lambda org_id, job: calls.setdefault(
            'job',
            dict(job, job_id='fej_demo'),
        )
        self.workspace.log_event = lambda *args, **kwargs: calls.setdefault('audit', []).append((args, kwargs))
        original_inbox_entry = self.workspace._federation_inbox_entry
        self.workspace._federation_inbox_entry = lambda *args, **kwargs: {
            'envelope_id': 'fed_exec_demo',
            'state': kwargs.get('state', 'received'),
        }
        try:
            claims = FederationEnvelopeClaims(
                envelope_id='fed_exec_demo',
                source_host_id='host_alpha',
                source_institution_id='org_alpha',
                target_host_id='host_beta',
                target_institution_id='org_a',
                actor_type='user',
                actor_id='user_alpha',
                session_id='ses_alpha',
                boundary_name='federation_gateway',
                identity_model='signed_host_service',
                message_type='execution_request',
                payload_hash='hash_demo',
                warrant_id='war_sender_demo',
                commitment_id='cmt_demo',
            )
            processing = self.workspace._process_received_federation_message(
                'org_a',
                claims,
                {'receipt_id': 'fedrcpt_demo', 'accepted_at': '2026-03-22T00:00:00Z'},
                payload={'task': 'demo'},
            )
        finally:
            self.workspace._federation_inbox_entry = original_inbox_entry

        self.assertTrue(processing['applied'])
        self.assertEqual(processing['reason'], 'execution_job_created')
        self.assertEqual(processing['state'], 'processed')
        self.assertEqual(processing['execution_job']['job_id'], 'fej_demo')
        self.assertEqual(processing['execution_job']['state'], 'pending_local_warrant')
        self.assertEqual(processing['receiver_warrant']['warrant_id'], 'war_local_demo')
        self.assertEqual(processing['inbox_entry']['state'], 'processed')
        self.assertEqual(calls['job']['local_warrant_id'], 'war_local_demo')
        self.assertEqual(calls['job']['sender_warrant_id'], 'war_sender_demo')
        self.assertEqual(calls['audit'][-1][0][2], 'federation_execution_job_created')

    def test_process_received_execution_request_reuses_existing_job(self):
        from federation import FederationEnvelopeClaims

        existing_job = {
            'job_id': 'fej_demo',
            'envelope_id': 'fed_exec_demo',
            'local_warrant_id': 'war_local_demo',
            'state': 'pending_local_warrant',
        }
        self.workspace.get_execution_job = lambda envelope_id, org_id=None: existing_job
        self.workspace.get_warrant = lambda warrant_id, org_id=None: {
            'warrant_id': warrant_id,
            'court_review_state': 'pending_review',
            'execution_state': 'ready',
            'expires_at': '2026-03-22T01:00:00Z',
        }
        self.workspace.issue_warrant = lambda *args, **kwargs: self.fail('should not issue duplicate warrant')
        self.workspace.upsert_execution_job = lambda *args, **kwargs: self.fail('should not upsert duplicate job')
        self.workspace.log_event = lambda *args, **kwargs: None
        original_inbox_entry = self.workspace._federation_inbox_entry
        self.workspace._federation_inbox_entry = lambda *args, **kwargs: {
            'envelope_id': 'fed_exec_demo',
            'state': kwargs.get('state', 'received'),
        }
        try:
            claims = FederationEnvelopeClaims(
                envelope_id='fed_exec_demo',
                source_host_id='host_alpha',
                source_institution_id='org_alpha',
                target_host_id='host_beta',
                target_institution_id='org_a',
                actor_type='user',
                actor_id='user_alpha',
                session_id='ses_alpha',
                boundary_name='federation_gateway',
                identity_model='signed_host_service',
                message_type='execution_request',
                payload_hash='hash_demo',
                warrant_id='war_sender_demo',
                commitment_id='cmt_demo',
            )
            processing = self.workspace._process_received_federation_message(
                'org_a',
                claims,
                {'receipt_id': 'fedrcpt_demo', 'accepted_at': '2026-03-22T00:00:00Z'},
                payload={'task': 'demo'},
            )
        finally:
            self.workspace._federation_inbox_entry = original_inbox_entry

        self.assertTrue(processing['applied'])
        self.assertEqual(processing['execution_job']['job_id'], 'fej_demo')
        self.assertEqual(processing['receiver_warrant']['warrant_id'], 'war_local_demo')

    def test_process_received_execution_request_blocks_on_case(self):
        from federation import FederationEnvelopeClaims

        self.workspace.get_execution_job = lambda envelope_id, org_id=None: None
        self.workspace.issue_warrant = lambda *args, **kwargs: self.fail('blocked execution should not issue warrant')
        original_blocking_case = self.workspace._blocking_case_for_delivery
        self.workspace._blocking_case_for_delivery = lambda **kwargs: {
            'case_id': 'case_demo',
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
                source_host_id='host_alpha',
                source_institution_id='org_alpha',
                target_host_id='host_beta',
                target_institution_id='org_a',
                actor_type='user',
                actor_id='user_alpha',
                session_id='ses_alpha',
                boundary_name='federation_gateway',
                identity_model='signed_host_service',
                message_type='execution_request',
                payload_hash='hash_demo',
                warrant_id='war_sender_demo',
                commitment_id='cmt_demo',
            )
            processing = self.workspace._process_received_federation_message(
                'org_a',
                claims,
                {'receipt_id': 'fedrcpt_demo', 'accepted_at': '2026-03-22T00:00:00Z'},
                payload={'task': 'demo'},
            )
        finally:
            self.workspace._blocking_case_for_delivery = original_blocking_case
            self.workspace._federation_inbox_entry = original_inbox_entry

        self.assertTrue(processing['applied'])
        self.assertEqual(processing['reason'], 'case_blocked')
        self.assertEqual(processing['execution_job']['state'], 'blocked')
        self.assertEqual(processing['case']['case_id'], 'case_demo')
        self.assertIsNone(processing['receiver_warrant'])

    def test_sync_execution_job_for_warrant_review_marks_ready(self):
        calls = {}
        self.workspace.get_execution_job_by_local_warrant = lambda warrant_id, org_id: {
            'job_id': 'fej_demo',
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
                'job_id': 'fej_demo',
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
            'org_a',
            {
                'warrant_id': 'war_local_demo',
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

    def test_sync_execution_job_for_warrant_review_rejects_non_federated_warrant(self):
        self.workspace.get_execution_job_by_local_warrant = lambda warrant_id, org_id: self.fail('should not query job')
        self.workspace.sync_execution_job_for_local_warrant = lambda *args, **kwargs: self.fail('should not sync job')

        job = self.workspace._sync_execution_job_for_warrant_review(
            'org_a',
            {
                'warrant_id': 'war_demo',
                'action_class': 'payout_execution',
                'boundary_name': 'payouts',
                'court_review_state': 'approved',
                'execution_state': 'ready',
            },
            decision='approve',
        )

        self.assertIsNone(job)

    def test_sync_execution_job_for_warrant_review_blocks_or_rejects_local_warrant(self):
        cases = (
            ('stayed', 'stay', 'blocked'),
            ('revoked', 'revoke', 'rejected'),
        )

        for court_review_state, decision, expected_state in cases:
            with self.subTest(court_review_state=court_review_state, decision=decision):
                calls = {}
                self.workspace.get_execution_job_by_local_warrant = lambda warrant_id, org_id: {
                    'job_id': 'fej_demo',
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
                        'job_id': 'fej_demo',
                        'local_warrant_id': warrant_id,
                        'state': kwargs['state'],
                        'note': kwargs['note'],
                        'metadata': kwargs['metadata'],
                    }

                self.workspace.sync_execution_job_for_local_warrant = _sync
                self.workspace.get_warrant = lambda warrant_id, org_id=None, state=court_review_state: {
                    'warrant_id': warrant_id,
                    'action_class': 'federated_execution',
                    'boundary_name': 'federation_gateway',
                    'court_review_state': state,
                    'execution_state': 'ready',
                    'reviewed_by': 'user_owner',
                    'reviewed_at': '2026-03-22T00:30:00Z',
                }

                job = self.workspace._sync_execution_job_for_warrant_review(
                    'org_a',
                    {
                        'warrant_id': 'war_local_demo',
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

    def test_mutate_federation_peer_upserts_registry(self):
        from runtime_host import default_host_identity
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            self.workspace.FEDERATION_PEERS_FILE = os.path.join(tmp, 'federation_peers.json')
            self.workspace.load_host_identity = lambda *args, **kwargs: default_host_identity(
                host_id='host_alpha',
                role='control_host',
                federation_enabled=True,
                peer_transport='https',
                supported_boundaries=['workspace', 'cli', 'federation_gateway'],
            )
            self.workspace.load_admission_registry = lambda *args, **kwargs: {
                'source': 'file',
                'host_id': 'host_alpha',
                'institutions': {'org_a': {'status': 'admitted'}},
                'admitted_org_ids': ['org_a'],
            }
            snapshot = self.workspace._mutate_federation_peer('org_a', 'upsert', {
                'peer_host_id': 'host_beta',
                'label': 'Beta Host',
                'endpoint_url': 'http://127.0.0.1:19016',
                'shared_secret': 'beta-secret',
                'witness_archive_user': 'gamma-user',
                'witness_archive_pass': 'gamma-pass',
                'admitted_org_ids': ['org_b'],
            })
            self.assertEqual(snapshot['management_mode'], 'workspace_api_file_backed')
            self.assertEqual(snapshot['peer_count'], 1)
            self.assertEqual(snapshot['trusted_peer_ids'], ['host_beta'])
            peer = next(peer for peer in snapshot['peers'] if peer['host_id'] == 'host_beta')
            self.assertTrue(peer['witness_archive_configured'])
            self.assertTrue(any(peer['host_id'] == 'host_beta' for peer in snapshot['peers']))

    def test_mutate_federation_peer_refreshes_capability_snapshot(self):
        from federation import FederationPeer, upsert_peer_registry_entry
        from runtime_host import default_host_identity
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            self.workspace.FEDERATION_PEERS_FILE = os.path.join(tmp, 'federation_peers.json')
            host = default_host_identity(
                host_id='host_alpha',
                role='control_host',
                federation_enabled=True,
                peer_transport='https',
                supported_boundaries=['workspace', 'cli', 'federation_gateway'],
            )
            self.workspace.load_host_identity = lambda *args, **kwargs: host
            self.workspace.load_admission_registry = lambda *args, **kwargs: {
                'source': 'file',
                'host_id': 'host_alpha',
                'institutions': {'org_a': {'status': 'admitted'}},
                'admitted_org_ids': ['org_a'],
            }
            upsert_peer_registry_entry(
                self.workspace.FEDERATION_PEERS_FILE,
                'host_beta',
                host_identity=host,
                label='Beta Host',
                endpoint_url='http://127.0.0.1:19017',
                shared_secret='beta-secret',
                admitted_org_ids=['org_b'],
            )
            self.workspace.refresh_peer_registry_entry = lambda *args, **kwargs: {
                'source': 'file',
                'host_id': 'host_alpha',
                'trusted_peer_ids': ['host_beta'],
                'peers': {
                    'host_beta': FederationPeer(
                        'host_beta',
                        label='Beta Host',
                        endpoint_url='http://127.0.0.1:19017',
                        trust_state='trusted',
                        shared_secret='beta-secret',
                        admitted_org_ids=['org_b'],
                        capability_snapshot={
                            'manifest_version': 1,
                            'federation': {
                                'boundary_name': 'federation_gateway',
                            },
                        },
                        last_refreshed_at='2026-03-22T00:00:00Z',
                    ),
                },
            }
            snapshot = self.workspace._mutate_federation_peer('org_a', 'refresh', {
                'peer_host_id': 'host_beta',
                'target_org_id': 'org_b',
            })
            peer = next(peer for peer in snapshot['peers'] if peer['host_id'] == 'host_beta')
            self.assertTrue(peer['last_refreshed_at'])
            self.assertEqual(peer['capability_snapshot']['manifest_version'], 1)
            self.assertEqual(
                peer['capability_snapshot']['federation']['boundary_name'],
                'federation_gateway',
            )

    def test_mutate_federation_peer_rejects_self_host(self):
        from runtime_host import default_host_identity

        self.workspace.load_host_identity = lambda *args, **kwargs: default_host_identity(
            host_id='host_alpha',
            role='control_host',
            federation_enabled=True,
            peer_transport='https',
            supported_boundaries=['workspace', 'cli', 'federation_gateway'],
        )
        self.workspace.load_admission_registry = lambda *args, **kwargs: {
            'source': 'file',
            'host_id': 'host_alpha',
            'institutions': {'org_a': {'status': 'admitted'}},
            'admitted_org_ids': ['org_a'],
        }
        with self.assertRaises(PermissionError):
            self.workspace._mutate_federation_peer('org_a', 'upsert', {
                'peer_host_id': 'host_alpha',
                'shared_secret': 'alpha-secret',
            })

    def test_mutate_admission_adds_second_institution(self):
        from runtime_host import default_host_identity
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            self.workspace.RUNTIME_ADMISSION_FILE = os.path.join(tmp, 'institution_admissions.json')
            self.workspace.load_host_identity = lambda *args, **kwargs: default_host_identity(
                host_id='host_alpha',
                role='control_host',
                federation_enabled=True,
                peer_transport='https',
                supported_boundaries=['workspace', 'cli', 'federation_gateway'],
            )
            self.workspace.load_orgs = lambda: {
                'organizations': {
                    'org_a': {'id': 'org_a', 'name': 'A'},
                    'org_b': {'id': 'org_b', 'name': 'B'},
                }
            }
            snapshot = self.workspace._mutate_admission('org_a', 'admit', 'org_b')
            self.assertEqual(snapshot['management_mode'], 'workspace_api_file_backed')
            self.assertEqual(snapshot['admitted_org_ids'], ['org_a', 'org_b'])
            self.assertEqual(snapshot['institutions']['org_b']['status'], 'admitted')

    def test_mutate_admission_rejects_revoking_bound_org(self):
        from runtime_host import default_host_identity
        self.workspace.load_host_identity = lambda *args, **kwargs: default_host_identity(
            host_id='host_alpha',
            role='control_host',
            federation_enabled=True,
            peer_transport='https',
            supported_boundaries=['workspace', 'cli', 'federation_gateway'],
        )
        self.workspace.load_orgs = lambda: {
            'organizations': {
                'org_a': {'id': 'org_a', 'name': 'A'},
            }
        }
        with self.assertRaises(PermissionError):
            self.workspace._mutate_admission('org_a', 'revoke', 'org_a')

    def test_accept_federation_request_consumes_envelope(self):
        from federation import FederationAuthority
        from runtime_host import default_host_identity
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            replay_path = os.path.join(tmp, 'federation_replay.log')
            self.workspace.FEDERATION_REPLAY_FILE = replay_path
            self.workspace.FEDERATION_SIGNING_SECRET = 'alpha-secret'
            self.workspace.load_host_identity = lambda *args, **kwargs: default_host_identity(
                host_id='host_alpha',
                federation_enabled=True,
                peer_transport='https',
                supported_boundaries=['workspace', 'cli', 'federation_gateway'],
            )
            self.workspace.load_admission_registry = lambda *args, **kwargs: {
                'source': 'file',
                'host_id': 'host_alpha',
                'institutions': {'org_a': {'status': 'admitted'}},
                'admitted_org_ids': ['org_a'],
            }
            sender = FederationAuthority(
                default_host_identity(
                    host_id='host_alpha',
                    federation_enabled=True,
                    peer_transport='https',
                ),
                signing_secret='alpha-secret',
            )
            envelope = sender.issue(
                'org_a',
                'host_alpha',
                'org_a',
                'execution_request',
                payload={'task': 'demo'},
            )
            claims, snapshot = self.workspace._accept_federation_request(
                'org_a',
                envelope,
                payload={'task': 'demo'},
            )
            self.assertEqual(claims.source_host_id, 'host_alpha')
            self.assertTrue(snapshot['enabled'])
            self.assertEqual(snapshot['replay_protection']['entries'], 1)

    def test_deliver_federation_envelope_logs_sender_audit(self):
        from runtime_host import default_host_identity

        audit_events = []

        class FakeAuthority:
            def ensure_enabled(self):
                return True

            def deliver(self, *args, **kwargs):
                return {
                    'peer': {'host_id': 'host_beta', 'transport': 'https'},
                    'envelope': 'signed-envelope',
                    'claims': {
                        'envelope_id': 'fed_demo',
                        'source_host_id': 'host_alpha',
                        'source_institution_id': 'org_a',
                        'target_host_id': 'host_beta',
                        'target_institution_id': 'org_b',
                        'nonce': 'nonce_demo',
                        'boundary_name': 'federation_gateway',
                        'message_type': 'settlement_notice',
                    },
                    'receipt': {
                        'receipt_id': 'fedrcpt_demo',
                        'receiver_host_id': 'host_beta',
                        'receiver_institution_id': 'org_b',
                    },
                    'response': {
                        'accepted': True,
                        'receipt': {
                            'receipt_id': 'fedrcpt_demo',
                            'receiver_host_id': 'host_beta',
                            'receiver_institution_id': 'org_b',
                        },
                    },
                }

            def snapshot(self, *, bound_org_id='', admission_registry=None):
                return {
                    'enabled': True,
                    'bound_org_id': bound_org_id,
                    'admitted_org_ids': list((admission_registry or {}).get('admitted_org_ids', [])),
                }

        self.workspace._runtime_host_state = lambda _org_id: (
            default_host_identity(host_id='host_alpha', federation_enabled=True),
            {'admitted_org_ids': ['org_a', 'org_b']},
        )
        self.workspace._federation_authority = lambda _host: FakeAuthority()
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append({
            'args': args,
            'kwargs': kwargs,
        })

        delivery, snapshot = self.workspace._deliver_federation_envelope(
            'org_a',
            'host_beta',
            'org_b',
            'settlement_notice',
            payload={'task': 'demo'},
            actor_type='user',
            actor_id='user_owner',
            session_id='ses_demo',
        )

        self.assertEqual(delivery['claims']['envelope_id'], 'fed_demo')
        self.assertEqual(delivery['receipt']['receipt_id'], 'fedrcpt_demo')
        self.assertEqual(snapshot['bound_org_id'], 'org_a')
        self.assertEqual(len(audit_events), 1)
        event = audit_events[0]
        self.assertEqual(event['args'][1], 'user_owner')
        self.assertEqual(event['args'][2], 'federation_envelope_sent')
        self.assertEqual(event['kwargs']['actor_type'], 'user')
        self.assertEqual(event['kwargs']['session_id'], 'ses_demo')
        self.assertEqual(event['kwargs']['details']['envelope_id'], 'fed_demo')
        self.assertEqual(event['kwargs']['details']['target_host_id'], 'host_beta')
        self.assertEqual(event['kwargs']['details']['receipt_id'], 'fedrcpt_demo')
        self.assertEqual(event['kwargs']['details']['receiver_host_id'], 'host_beta')

    def test_deliver_federation_envelope_logs_delivery_failure(self):
        from federation import FederationDeliveryError, FederationEnvelopeClaims
        from runtime_host import default_host_identity

        audit_events = []

        class FakeAuthority:
            def ensure_enabled(self):
                return True

            def deliver(self, *args, **kwargs):
                raise FederationDeliveryError(
                    'Peer returned HTTP 503',
                    peer_host_id='host_beta',
                    envelope='signed-envelope',
                    claims=FederationEnvelopeClaims(
                        envelope_id='fed_demo',
                        source_host_id='host_alpha',
                        source_institution_id='org_a',
                        target_host_id='host_beta',
                        target_institution_id='org_b',
                        boundary_name='federation_gateway',
                        message_type='settlement_notice',
                        nonce='nonce_demo',
                    ),
                )

        self.workspace._runtime_host_state = lambda _org_id: (
            default_host_identity(host_id='host_alpha', federation_enabled=True),
            {'admitted_org_ids': ['org_a', 'org_b']},
        )
        self.workspace._federation_authority = lambda _host: FakeAuthority()
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append({
            'args': args,
            'kwargs': kwargs,
        })

        with self.assertRaises(FederationDeliveryError):
            self.workspace._deliver_federation_envelope(
                'org_a',
                'host_beta',
                'org_b',
                'settlement_notice',
                payload={'task': 'demo'},
                actor_type='user',
                actor_id='user_owner',
                session_id='ses_demo',
            )

        self.assertEqual(len(audit_events), 1)
        event = audit_events[0]
        self.assertEqual(event['args'][2], 'federation_envelope_delivery_failed')
        self.assertEqual(event['kwargs']['details']['envelope_id'], 'fed_demo')
        self.assertEqual(event['kwargs']['details']['error'], 'Peer returned HTTP 503')

    def test_deliver_federation_envelope_blocks_execution_without_warrant(self):
        from runtime_host import default_host_identity

        audit_events = []

        class FakeAuthority:
            def ensure_enabled(self):
                return True

        self.workspace._runtime_host_state = lambda _org_id: (
            default_host_identity(host_id='host_alpha', federation_enabled=True),
            {'admitted_org_ids': ['org_a', 'org_b']},
        )
        self.workspace._federation_authority = lambda _host: FakeAuthority()
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append({
            'args': args,
            'kwargs': kwargs,
        })

        with self.assertRaises(PermissionError) as exc_info:
            self.workspace._deliver_federation_envelope(
                'org_a',
                'host_beta',
                'org_b',
                'execution_request',
                payload={'task': 'demo'},
                actor_type='user',
                actor_id='user_owner',
                session_id='ses_demo',
            )

        self.assertEqual(len(audit_events), 1)
        event = audit_events[0]
        self.assertEqual(event['args'][2], 'federation_warrant_blocked')
        self.assertEqual(event['kwargs']['details']['required_action_class'], 'federated_execution')
        self.assertEqual(event['kwargs']['details']['target_host_id'], 'host_beta')

    def test_deliver_federation_envelope_validates_and_marks_commitment(self):
        from runtime_host import default_host_identity

        audit_events = []
        marked = []

        class FakeAuthority:
            def ensure_enabled(self):
                return True

            def deliver(self, *args, **kwargs):
                return {
                    'peer': {'host_id': 'host_beta', 'transport': 'https'},
                    'claims': {
                        'envelope_id': 'fed_demo',
                        'source_host_id': 'host_alpha',
                        'source_institution_id': 'org_a',
                        'target_host_id': 'host_beta',
                        'target_institution_id': 'org_b',
                        'nonce': 'nonce_demo',
                        'boundary_name': 'federation_gateway',
                        'message_type': 'settlement_notice',
                        'commitment_id': 'cmt_demo',
                    },
                    'receipt': {
                        'receipt_id': 'fedrcpt_demo',
                        'receiver_host_id': 'host_beta',
                        'receiver_institution_id': 'org_b',
                    },
                    'response': {'accepted': True},
                }

            def snapshot(self, *, bound_org_id='', admission_registry=None):
                return {
                    'enabled': True,
                    'bound_org_id': bound_org_id,
                    'admitted_org_ids': list((admission_registry or {}).get('admitted_org_ids', [])),
                }

        self.workspace._runtime_host_state = lambda _org_id: (
            default_host_identity(host_id='host_alpha', federation_enabled=True),
            {'admitted_org_ids': ['org_a', 'org_b']},
        )
        self.workspace._federation_authority = lambda _host: FakeAuthority()
        self.workspace.validate_commitment_for_delivery = lambda commitment_id, **_kwargs: {
            'commitment_id': commitment_id,
            'status': 'accepted',
        }
        self.workspace.record_delivery_ref = lambda commitment_id, **kwargs: marked.append({
            'commitment_id': commitment_id,
            'kwargs': kwargs,
        })
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append({
            'args': args,
            'kwargs': kwargs,
        })

        delivery, snapshot = self.workspace._deliver_federation_envelope(
            'org_a',
            'host_beta',
            'org_b',
            'settlement_notice',
            payload={'task': 'demo'},
            actor_type='user',
            actor_id='user_owner',
            session_id='ses_demo',
            commitment_id='cmt_demo',
        )

        self.assertEqual(delivery['claims']['commitment_id'], 'cmt_demo')
        self.assertEqual(snapshot['bound_org_id'], 'org_a')
        self.assertEqual(len(marked), 1)
        self.assertEqual(marked[0]['commitment_id'], 'cmt_demo')
        self.assertEqual(marked[0]['kwargs']['delivery_ref']['receipt_id'], 'fedrcpt_demo')
        self.assertEqual(audit_events[-1]['kwargs']['details']['commitment_id'], 'cmt_demo')

    def test_deliver_federation_commitment_proposal_uses_proposal_validator(self):
        from runtime_host import default_host_identity

        validated = []
        recorded = []
        marked = []

        class FakeAuthority:
            def ensure_enabled(self):
                return True

            def deliver(self, *args, **kwargs):
                return {
                    'peer': {'host_id': 'host_beta', 'transport': 'https'},
                    'claims': {
                        'envelope_id': 'fed_commit_prop_demo',
                        'source_host_id': 'host_alpha',
                        'source_institution_id': 'org_a',
                        'target_host_id': 'host_beta',
                        'target_institution_id': 'org_b',
                        'nonce': 'nonce_demo',
                        'boundary_name': 'federation_gateway',
                        'message_type': 'commitment_proposal',
                        'warrant_id': 'war_commit_demo',
                        'commitment_id': 'cmt_demo',
                    },
                    'receipt': {
                        'receipt_id': 'fedrcpt_commit_prop_demo',
                        'receiver_host_id': 'host_beta',
                        'receiver_institution_id': 'org_b',
                    },
                    'response': {'accepted': True},
                }

            def snapshot(self, *, bound_org_id='', admission_registry=None):
                return {
                    'enabled': True,
                    'bound_org_id': bound_org_id,
                    'admitted_org_ids': list((admission_registry or {}).get('admitted_org_ids', [])),
                }

        self.workspace._runtime_host_state = lambda _org_id: (
            default_host_identity(host_id='host_alpha', federation_enabled=True),
            {'admitted_org_ids': ['org_a', 'org_b']},
        )
        self.workspace._federation_authority = lambda _host: FakeAuthority()
        self.workspace.validate_warrant_for_execution = lambda *args, **kwargs: {
            'warrant_id': 'war_commit_demo',
            'execution_state': 'ready',
        }
        self.workspace.validate_commitment_for_proposal_dispatch = lambda commitment_id, **kwargs: (
            validated.append({'commitment_id': commitment_id, 'kwargs': kwargs}) or {
                'commitment_id': commitment_id,
                'status': 'proposed',
            }
        )
        self.workspace.validate_commitment_for_acceptance_dispatch = (
            lambda *args, **kwargs: self.fail('acceptance validator should not run')
        )
        self.workspace.record_delivery_ref = lambda commitment_id, **kwargs: recorded.append({
            'commitment_id': commitment_id,
            'kwargs': kwargs,
        })
        self.workspace.mark_warrant_executed = lambda *args, **kwargs: marked.append((args, kwargs))
        self.workspace.log_event = lambda *args, **kwargs: None

        delivery, snapshot = self.workspace._deliver_federation_envelope(
            'org_a',
            'host_beta',
            'org_b',
            'commitment_proposal',
            payload={'summary': 'Deliver shared brief'},
            actor_type='user',
            actor_id='user_owner',
            session_id='ses_demo',
            warrant_id='war_commit_demo',
            commitment_id='cmt_demo',
        )

        self.assertEqual(snapshot['bound_org_id'], 'org_a')
        self.assertEqual(delivery['claims']['message_type'], 'commitment_proposal')
        self.assertEqual(len(validated), 1)
        self.assertEqual(validated[0]['commitment_id'], 'cmt_demo')
        self.assertEqual(validated[0]['kwargs']['target_host_id'], 'host_beta')
        self.assertEqual(validated[0]['kwargs']['target_institution_id'], 'org_b')
        self.assertEqual(validated[0]['kwargs']['warrant_id'], 'war_commit_demo')
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]['kwargs']['delivery_ref']['receipt_id'], 'fedrcpt_commit_prop_demo')
        self.assertEqual(len(marked), 1)
        self.assertEqual(marked[0][0][0], 'war_commit_demo')

    def test_deliver_federation_commitment_acceptance_uses_acceptance_validator(self):
        from runtime_host import default_host_identity

        validated = []
        recorded = []
        marked = []

        class FakeAuthority:
            def ensure_enabled(self):
                return True

            def deliver(self, *args, **kwargs):
                return {
                    'peer': {'host_id': 'host_alpha', 'transport': 'https'},
                    'claims': {
                        'envelope_id': 'fed_commit_accept_demo',
                        'source_host_id': 'host_beta',
                        'source_institution_id': 'org_b',
                        'target_host_id': 'host_alpha',
                        'target_institution_id': 'org_a',
                        'nonce': 'nonce_demo',
                        'boundary_name': 'federation_gateway',
                        'message_type': 'commitment_acceptance',
                        'warrant_id': 'war_accept_demo',
                        'commitment_id': 'cmt_demo',
                    },
                    'receipt': {
                        'receipt_id': 'fedrcpt_commit_accept_demo',
                        'receiver_host_id': 'host_alpha',
                        'receiver_institution_id': 'org_a',
                    },
                    'response': {'accepted': True},
                }

            def snapshot(self, *, bound_org_id='', admission_registry=None):
                return {
                    'enabled': True,
                    'bound_org_id': bound_org_id,
                    'admitted_org_ids': list((admission_registry or {}).get('admitted_org_ids', [])),
                }

        self.workspace._runtime_host_state = lambda _org_id: (
            default_host_identity(host_id='host_beta', federation_enabled=True),
            {'admitted_org_ids': ['org_a', 'org_b']},
        )
        self.workspace._federation_authority = lambda _host: FakeAuthority()
        self.workspace.validate_warrant_for_execution = lambda *args, **kwargs: {
            'warrant_id': 'war_accept_demo',
            'execution_state': 'ready',
        }
        self.workspace.validate_commitment_for_proposal_dispatch = (
            lambda *args, **kwargs: self.fail('proposal validator should not run')
        )
        self.workspace.validate_commitment_for_acceptance_dispatch = lambda commitment_id, **kwargs: (
            validated.append({'commitment_id': commitment_id, 'kwargs': kwargs}) or {
                'commitment_id': commitment_id,
                'status': 'accepted',
            }
        )
        self.workspace.record_delivery_ref = lambda commitment_id, **kwargs: recorded.append({
            'commitment_id': commitment_id,
            'kwargs': kwargs,
        })
        self.workspace.mark_warrant_executed = lambda *args, **kwargs: marked.append((args, kwargs))
        self.workspace.log_event = lambda *args, **kwargs: None

        delivery, snapshot = self.workspace._deliver_federation_envelope(
            'org_b',
            'host_alpha',
            'org_a',
            'commitment_acceptance',
            payload={'note': 'Accepted on beta'},
            actor_type='user',
            actor_id='user_owner_beta',
            session_id='ses_beta',
            warrant_id='war_accept_demo',
            commitment_id='cmt_demo',
        )

        self.assertEqual(snapshot['bound_org_id'], 'org_b')
        self.assertEqual(delivery['claims']['message_type'], 'commitment_acceptance')
        self.assertEqual(len(validated), 1)
        self.assertEqual(validated[0]['commitment_id'], 'cmt_demo')
        self.assertEqual(validated[0]['kwargs']['target_host_id'], 'host_alpha')
        self.assertEqual(validated[0]['kwargs']['target_institution_id'], 'org_a')
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]['kwargs']['delivery_ref']['receipt_id'], 'fedrcpt_commit_accept_demo')
        self.assertEqual(len(marked), 1)
        self.assertEqual(marked[0][0][0], 'war_accept_demo')

    def test_deliver_federation_commitment_breach_notice_uses_breach_validator(self):
        from runtime_host import default_host_identity

        validated = []
        recorded = []
        marked = []

        class FakeAuthority:
            def ensure_enabled(self):
                return True

            def deliver(self, *args, **kwargs):
                return {
                    'peer': {'host_id': 'host_alpha', 'transport': 'https'},
                    'claims': {
                        'envelope_id': 'fed_commit_breach_demo',
                        'source_host_id': 'host_beta',
                        'source_institution_id': 'org_b',
                        'target_host_id': 'host_alpha',
                        'target_institution_id': 'org_a',
                        'nonce': 'nonce_demo',
                        'boundary_name': 'federation_gateway',
                        'message_type': 'commitment_breach_notice',
                        'warrant_id': 'war_breach_demo',
                        'commitment_id': 'cmt_demo',
                    },
                    'receipt': {
                        'receipt_id': 'fedrcpt_commit_breach_demo',
                        'receiver_host_id': 'host_alpha',
                        'receiver_institution_id': 'org_a',
                    },
                    'response': {'accepted': True},
                }

            def snapshot(self, *, bound_org_id='', admission_registry=None):
                return {
                    'enabled': True,
                    'bound_org_id': bound_org_id,
                    'admitted_org_ids': list((admission_registry or {}).get('admitted_org_ids', [])),
                }

        self.workspace._runtime_host_state = lambda _org_id: (
            default_host_identity(host_id='host_beta', federation_enabled=True),
            {'admitted_org_ids': ['org_a', 'org_b']},
        )
        self.workspace._federation_authority = lambda _host: FakeAuthority()
        self.workspace.validate_warrant_for_execution = lambda *args, **kwargs: {
            'warrant_id': 'war_breach_demo',
            'execution_state': 'ready',
        }
        self.workspace.validate_commitment_for_proposal_dispatch = (
            lambda *args, **kwargs: self.fail('proposal validator should not run')
        )
        self.workspace.validate_commitment_for_acceptance_dispatch = (
            lambda *args, **kwargs: self.fail('acceptance validator should not run')
        )
        self.workspace.validate_commitment_for_breach_notice = lambda commitment_id, **kwargs: (
            validated.append({'commitment_id': commitment_id, 'kwargs': kwargs}) or {
                'commitment_id': commitment_id,
                'status': 'breached',
            }
        )
        self.workspace.record_delivery_ref = lambda commitment_id, **kwargs: recorded.append({
            'commitment_id': commitment_id,
            'kwargs': kwargs,
        })
        self.workspace.mark_warrant_executed = lambda *args, **kwargs: marked.append((args, kwargs))
        self.workspace.log_event = lambda *args, **kwargs: None

        delivery, snapshot = self.workspace._deliver_federation_envelope(
            'org_b',
            'host_alpha',
            'org_a',
            'commitment_breach_notice',
            payload={'note': 'Breach recorded on beta'},
            actor_type='user',
            actor_id='user_owner_beta',
            session_id='ses_beta',
            warrant_id='war_breach_demo',
            commitment_id='cmt_demo',
        )

        self.assertEqual(snapshot['bound_org_id'], 'org_b')
        self.assertEqual(delivery['claims']['message_type'], 'commitment_breach_notice')
        self.assertEqual(len(validated), 1)
        self.assertEqual(validated[0]['commitment_id'], 'cmt_demo')
        self.assertEqual(validated[0]['kwargs']['target_host_id'], 'host_alpha')
        self.assertEqual(validated[0]['kwargs']['target_institution_id'], 'org_a')
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]['kwargs']['delivery_ref']['receipt_id'], 'fedrcpt_commit_breach_demo')
        self.assertEqual(len(marked), 1)
        self.assertEqual(marked[0][0][0], 'war_breach_demo')

    def test_deliver_federation_execution_request_defers_commitment_warrant_execution(self):
        from runtime_host import default_host_identity

        recorded = []
        marked = []

        class FakeAuthority:
            def ensure_enabled(self):
                return True

            def deliver(self, *args, **kwargs):
                return {
                    'peer': {'host_id': 'host_beta', 'transport': 'https'},
                    'claims': {
                        'envelope_id': 'fed_exec_demo',
                        'source_host_id': 'host_alpha',
                        'source_institution_id': 'org_a',
                        'target_host_id': 'host_beta',
                        'target_institution_id': 'org_b',
                        'nonce': 'nonce_demo',
                        'boundary_name': 'federation_gateway',
                        'message_type': 'execution_request',
                        'commitment_id': 'cmt_demo',
                    },
                    'receipt': {
                        'receipt_id': 'fedrcpt_exec_demo',
                        'receiver_host_id': 'host_beta',
                        'receiver_institution_id': 'org_b',
                    },
                    'response': {'accepted': True},
                }

            def snapshot(self, *, bound_org_id='', admission_registry=None):
                return {
                    'enabled': True,
                    'bound_org_id': bound_org_id,
                    'admitted_org_ids': list((admission_registry or {}).get('admitted_org_ids', [])),
                }

        self.workspace._runtime_host_state = lambda _org_id: (
            default_host_identity(host_id='host_alpha', federation_enabled=True),
            {'admitted_org_ids': ['org_a', 'org_b']},
        )
        self.workspace._federation_authority = lambda _host: FakeAuthority()
        self.workspace.validate_warrant_for_execution = lambda *args, **kwargs: {
            'warrant_id': 'war_demo',
            'execution_state': 'ready',
        }
        self.workspace.validate_commitment_for_delivery = lambda commitment_id, **_kwargs: {
            'commitment_id': commitment_id,
            'status': 'accepted',
        }
        self.workspace.record_delivery_ref = lambda commitment_id, **kwargs: recorded.append({
            'commitment_id': commitment_id,
            'kwargs': kwargs,
        })
        self.workspace.mark_warrant_executed = lambda *args, **kwargs: marked.append((args, kwargs))
        self.workspace.log_event = lambda *args, **kwargs: None

        delivery, _snapshot = self.workspace._deliver_federation_envelope(
            'org_a',
            'host_beta',
            'org_b',
            'execution_request',
            payload={'task': 'demo'},
            actor_type='user',
            actor_id='user_owner',
            session_id='ses_demo',
            warrant_id='war_demo',
            commitment_id='cmt_demo',
        )

        self.assertEqual(delivery['claims']['message_type'], 'execution_request')
        self.assertEqual(marked, [])
        self.assertEqual(recorded[0]['commitment_id'], 'cmt_demo')
        self.assertEqual(recorded[0]['kwargs']['delivery_ref']['warrant_id'], 'war_demo')

    def test_deliver_federation_envelope_blocks_invalid_commitment(self):
        from runtime_host import default_host_identity

        audit_events = []

        class FakeAuthority:
            def ensure_enabled(self):
                return True

        self.workspace._runtime_host_state = lambda _org_id: (
            default_host_identity(host_id='host_alpha', federation_enabled=True),
            {'admitted_org_ids': ['org_a', 'org_b']},
        )
        self.workspace._federation_authority = lambda _host: FakeAuthority()
        self.workspace.validate_commitment_for_delivery = lambda _commitment_id, **_kwargs: (_ for _ in ()).throw(
            ValueError("Commitment 'cmt_demo' is not active for federation (state=rejected)")
        )
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append({
            'args': args,
            'kwargs': kwargs,
        })

        with self.assertRaises(ValueError):
            self.workspace._deliver_federation_envelope(
                'org_a',
                'host_beta',
                'org_b',
                'settlement_notice',
                payload={'task': 'demo'},
                actor_type='user',
                actor_id='user_owner',
                session_id='ses_demo',
                commitment_id='cmt_demo',
            )

        self.assertEqual(len(audit_events), 1)
        event = audit_events[0]
        self.assertEqual(event['args'][2], 'federation_commitment_blocked')
        self.assertEqual(event['kwargs']['details']['commitment_id'], 'cmt_demo')

    def test_deliver_federation_envelope_blocks_open_case(self):
        from runtime_host import default_host_identity

        audit_events = []

        class FakeAuthority:
            def ensure_enabled(self):
                return True

        self.workspace._runtime_host_state = lambda _org_id: (
            default_host_identity(host_id='host_alpha', federation_enabled=True),
            {'admitted_org_ids': ['org_a', 'org_b']},
        )
        self.workspace._federation_authority = lambda _host: FakeAuthority()
        self.workspace.validate_commitment_for_delivery = lambda commitment_id, **_kwargs: {
            'commitment_id': commitment_id,
            'status': 'accepted',
        }
        self.workspace.blocking_commitment_case = lambda commitment_id, **_kwargs: {
            'case_id': 'case_demo',
            'claim_type': 'breach_of_commitment',
            'status': 'open',
            'linked_commitment_id': commitment_id,
        }
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append({
            'args': args,
            'kwargs': kwargs,
        })

        with self.assertRaises(PermissionError) as exc_info:
            self.workspace._deliver_federation_envelope(
                'org_a',
                'host_beta',
                'org_b',
                'settlement_notice',
                payload={'task': 'demo'},
                actor_type='user',
                actor_id='user_owner',
                session_id='ses_demo',
                commitment_id='cmt_demo',
            )

        self.assertEqual(exc_info.exception.case_record['case_id'], 'case_demo')
        self.assertEqual(exc_info.exception.federation_peer['peer_host_id'], 'host_beta')
        self.assertEqual(exc_info.exception.federation_peer['reason'], 'peer_not_registered')
        self.assertEqual(len(audit_events), 1)
        event = audit_events[0]
        self.assertEqual(event['args'][2], 'federation_case_blocked')
        self.assertEqual(event['kwargs']['details']['case_id'], 'case_demo')
        self.assertEqual(event['kwargs']['details']['commitment_id'], 'cmt_demo')

    def test_maybe_suspend_peer_for_case_updates_trust(self):
        from runtime_host import default_host_identity

        audit_events = []
        self.workspace._runtime_host_state = lambda _org_id: (
            default_host_identity(host_id='host_alpha', federation_enabled=True, peer_transport='https'),
            {'admitted_org_ids': ['org_a', 'org_b']},
        )
        self.workspace.ensure_case_for_delivery_failure = lambda claim_type, actor_id, **kwargs: ({
            'case_id': 'case_demo',
            'claim_type': claim_type,
            'status': 'open',
            'linked_commitment_id': kwargs.get('linked_commitment_id', ''),
            'target_host_id': kwargs.get('target_host_id', ''),
        }, True)
        self.workspace.set_peer_trust_state = lambda *_args, **_kwargs: {
            'source': 'file',
            'host_id': 'host_alpha',
            'trusted_peer_ids': [],
            'peers': {
                'host_beta': {
                    'host_id': 'host_beta',
                    'trust_state': 'suspended',
                },
            },
        }
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append({
            'args': args,
            'kwargs': kwargs,
        })

        result = self.workspace._maybe_suspend_peer_for_case(
            {
                'case_id': 'case_demo',
                'claim_type': 'misrouted_execution',
                'status': 'open',
                'target_host_id': 'host_beta',
            },
            'user_owner',
            org_id='org_a',
            session_id='ses_demo',
        )

        self.assertTrue(result['applied'])
        self.assertEqual(result['peer_host_id'], 'host_beta')
        self.assertEqual(result['trust_state'], 'suspended')
        self.assertEqual(audit_events[0]['args'][2], 'federation_peer_auto_suspended')

    def test_maybe_restore_peer_for_case_updates_trust(self):
        from runtime_host import default_host_identity

        audit_events = []
        self.workspace._runtime_host_state = lambda _org_id: (
            default_host_identity(host_id='host_alpha', federation_enabled=True, peer_transport='https'),
            {'admitted_org_ids': ['org_a', 'org_b']},
        )
        self.workspace.blocking_peer_case = lambda peer_host_id, **_kwargs: None
        self.workspace.set_peer_trust_state = lambda *_args, **_kwargs: {
            'source': 'file',
            'host_id': 'host_alpha',
            'trusted_peer_ids': ['host_beta'],
            'peers': {
                'host_beta': {
                    'host_id': 'host_beta',
                    'trust_state': 'trusted',
                },
            },
        }
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append({
            'args': args,
            'kwargs': kwargs,
        })

        result = self.workspace._maybe_restore_peer_for_case(
            {
                'case_id': 'case_demo',
                'claim_type': 'misrouted_execution',
                'status': 'resolved',
                'target_host_id': 'host_beta',
            },
            'user_owner',
            org_id='org_a',
            session_id='ses_demo',
        )

        self.assertTrue(result['applied'])
        self.assertEqual(result['peer_host_id'], 'host_beta')
        self.assertEqual(result['trust_state'], 'trusted')
        self.assertEqual(audit_events[0]['args'][2], 'federation_peer_auto_reinstated')

    def test_maybe_restore_peer_for_case_preserves_revoked_peer(self):
        from runtime_host import default_host_identity

        self.workspace._runtime_host_state = lambda _org_id: (
            default_host_identity(host_id='host_alpha', federation_enabled=True, peer_transport='https'),
            {'admitted_org_ids': ['org_a', 'org_b']},
        )
        self.workspace._federation_peer_state = lambda peer_host_id, **_kwargs: {
            'applied': False,
            'peer_host_id': peer_host_id,
            'reason': 'case_blocked',
            'trust_state': 'revoked',
        }
        self.workspace.blocking_peer_case = lambda peer_host_id, **_kwargs: None
        self.workspace.set_peer_trust_state = lambda *_args, **_kwargs: self.fail('revoked peer should not be auto-restored')
        self.workspace.log_event = lambda *args, **kwargs: self.fail('revoked peer should not emit restore audit')

        result = self.workspace._maybe_restore_peer_for_case(
            {
                'case_id': 'case_demo',
                'claim_type': 'misrouted_execution',
                'status': 'resolved',
                'target_host_id': 'host_beta',
            },
            'user_owner',
            org_id='org_a',
            session_id='ses_demo',
        )

        self.assertFalse(result['applied'])
        self.assertEqual(result['reason'], 'peer_revoked')
        self.assertEqual(result['trust_state'], 'revoked')

    def test_maybe_stay_warrant_for_case_stays_ready_warrant(self):
        audit_events = []
        self.workspace.list_warrants = lambda org_id=None, **_kwargs: [
            {
                'warrant_id': 'war_demo',
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

        warrant = self.workspace._maybe_stay_warrant_for_case(
            {
                'case_id': 'case_demo',
                'claim_type': 'misrouted_execution',
                'linked_warrant_id': 'war_demo',
            },
            'user_owner',
            org_id='org_a',
            session_id='ses_demo',
            note='Receipt contradiction',
        )

        self.assertTrue(warrant['applied'])
        self.assertEqual(warrant['warrant_id'], 'war_demo')
        self.assertEqual(warrant['court_review_state'], 'stayed')
        self.assertEqual(audit_events[0]['args'][2], 'warrant_stayed_for_case')
        self.assertEqual(audit_events[0]['kwargs']['details']['case_id'], 'case_demo')

    def test_maybe_block_commitment_settlement_returns_case_and_warrant(self):
        audit_events = []
        self.workspace.blocking_commitment_case = lambda commitment_id, **_kwargs: {
            'case_id': 'case_demo',
            'claim_type': 'non_delivery',
            'status': 'open',
            'linked_commitment_id': commitment_id,
            'linked_warrant_id': 'war_demo',
        }
        self.workspace.list_warrants = lambda org_id=None, **_kwargs: [
            {
                'warrant_id': 'war_demo',
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
            org_id='org_a',
            session_id='ses_demo',
            note='Do not settle while case is open',
        )

        self.assertEqual(case_record['case_id'], 'case_demo')
        self.assertTrue(warrant['applied'])
        self.assertEqual(warrant['warrant_id'], 'war_demo')
        self.assertEqual(audit_events[-1]['args'][2], 'commitment_settlement_blocked')
        self.assertEqual(audit_events[-1]['kwargs']['resource'], 'cmt_demo')

    def test_maybe_open_case_for_delivery_failure_creates_case_and_suspends_peer(self):
        from federation import FederationDeliveryError, FederationEnvelopeClaims
        from runtime_host import default_host_identity

        audit_events = []
        self.workspace._runtime_host_state = lambda _org_id: (
            default_host_identity(host_id='host_alpha', federation_enabled=True, peer_transport='https'),
            {'admitted_org_ids': ['org_a', 'org_b']},
        )
        self.workspace.ensure_case_for_delivery_failure = lambda claim_type, actor_id, **kwargs: ({
            'case_id': 'case_demo',
            'claim_type': claim_type,
            'status': 'open',
            'linked_commitment_id': kwargs.get('linked_commitment_id', ''),
            'target_host_id': kwargs.get('target_host_id', ''),
        }, True)
        self.workspace.set_peer_trust_state = lambda *_args, **_kwargs: {
            'source': 'file',
            'host_id': 'host_alpha',
            'trusted_peer_ids': [],
            'peers': {
                'host_beta': {
                    'host_id': 'host_beta',
                    'trust_state': 'suspended',
                },
            },
        }
        self.workspace.log_event = lambda *args, **kwargs: audit_events.append({
            'args': args,
            'kwargs': kwargs,
        })
        error = FederationDeliveryError(
            "Peer host 'host_beta' returned receipt receiver_host_id 'host_wrong'",
            peer_host_id='host_beta',
            claims=FederationEnvelopeClaims(
                envelope_id='fed_demo',
                source_host_id='host_alpha',
                source_institution_id='org_a',
                target_host_id='host_beta',
                target_institution_id='org_b',
                message_type='execution_request',
            ),
        )

        case_record, federation_peer = self.workspace._maybe_open_case_for_delivery_failure(
            error,
            'user_owner',
            org_id='org_a',
            target_host_id='host_beta',
            target_institution_id='org_b',
            commitment_id='cmt_demo',
            warrant_id='war_demo',
            session_id='ses_demo',
        )

        self.assertEqual(case_record['claim_type'], 'misrouted_execution')
        self.assertEqual(case_record['linked_commitment_id'], 'cmt_demo')
        self.assertTrue(federation_peer['applied'])
        self.assertEqual(federation_peer['trust_state'], 'suspended')
        self.assertEqual(audit_events[0]['args'][2], 'case_opened')
        self.assertEqual(audit_events[1]['args'][2], 'federation_peer_auto_suspended')


    def test_workspace_do_get_delegates_federation_service(self):
        class FakeContext:
            def __init__(self):
                self.org_id = 'org_a'
                self.org = {'id': 'org_a', 'name': 'Org A'}
                self.context_source = 'configured_org'

            def to_dict(self):
                return {
                    'org_id': self.org_id,
                    'org_name': self.org.get('name', ''),
                    'boundary_name': 'workspace',
                    'identity_model': 'session',
                    'routing_scope': 'institution_bound',
                    'host_id': 'host_alpha',
                    'host_role': 'institution_host',
                    'admission_id': '',
                    'federation_mode': 'federated_runtime_core',
                    'context_source': self.context_source,
                    'founded_at': '',
                }

        captured = {}
        handler = object.__new__(self.workspace.WorkspaceHandler)
        handler.path = '/api/federation'
        handler.headers = _Headers()
        handler._require_auth = lambda _path: True
        handler._session_claims_from_request = lambda expected_org_id=None: None
        handler._json = lambda data, status=200: captured.update({'status': status, 'data': data})
        handler._html = lambda html: captured.update({'status': 200, 'html': html})
        delegated = {}

        def fake_handle_get(_handler, _path, **kwargs):
            delegated['org_id'] = kwargs['org_id']
            _handler._json({'delegated': 'federation_service', 'org_id': kwargs['org_id']})
            return {'delegated': True}

        with mock.patch.object(self.workspace, '_resolve_workspace_context', return_value=FakeContext()),              mock.patch.object(self.workspace, '_resolve_auth_context', return_value={'enabled': True, 'role': 'owner'}),              mock.patch.object(self.workspace.federation_service, 'handle_get', side_effect=fake_handle_get),              mock.patch.object(self.workspace, '_federation_snapshot', side_effect=self.fail):
            handler.do_GET()

        self.assertEqual(captured['status'], 200)
        self.assertEqual(captured['data']['delegated'], 'federation_service')
        self.assertEqual(delegated['org_id'], 'org_a')

    def test_workspace_do_get_delegates_execution_job_service(self):
        class FakeContext:
            def __init__(self):
                self.org_id = 'org_a'
                self.org = {'id': 'org_a', 'name': 'Org A'}
                self.context_source = 'configured_org'

            def to_dict(self):
                return {
                    'org_id': self.org_id,
                    'org_name': self.org.get('name', ''),
                    'boundary_name': 'workspace',
                    'identity_model': 'session',
                    'routing_scope': 'institution_bound',
                    'host_id': 'host_alpha',
                    'host_role': 'institution_host',
                    'admission_id': '',
                    'federation_mode': 'federated_runtime_core',
                    'context_source': self.context_source,
                    'founded_at': '',
                }

        captured = {}
        handler = object.__new__(self.workspace.WorkspaceHandler)
        handler.path = '/api/federation/execution-jobs'
        handler.headers = _Headers()
        handler._require_auth = lambda _path: True
        handler._session_claims_from_request = lambda expected_org_id=None: None
        handler._json = lambda data, status=200: captured.update({'status': status, 'data': data})
        handler._html = lambda html: captured.update({'status': 200, 'html': html})

        def fake_handle_get(_handler, _path, **kwargs):
            _handler._json({'delegated': 'execution_job_service', 'org_id': kwargs['org_id']})
            return {'delegated': True}

        with mock.patch.object(self.workspace, '_resolve_workspace_context', return_value=FakeContext()),              mock.patch.object(self.workspace, '_resolve_auth_context', return_value={'enabled': True, 'role': 'owner'}),              mock.patch.object(self.workspace.execution_job_service, 'handle_get', side_effect=fake_handle_get),              mock.patch.object(self.workspace, '_federation_execution_jobs_snapshot', side_effect=self.fail):
            handler.do_GET()

        self.assertEqual(captured['status'], 200)
        self.assertEqual(captured['data']['delegated'], 'execution_job_service')

    def test_workspace_do_post_delegates_treasury_service(self):
        class FakeContext:
            def __init__(self):
                self.org_id = 'org_a'
                self.org = {'id': 'org_a', 'name': 'Org A'}
                self.context_source = 'configured_org'

            def to_dict(self):
                return {
                    'org_id': self.org_id,
                    'org_name': self.org.get('name', ''),
                    'boundary_name': 'workspace',
                    'identity_model': 'session',
                    'routing_scope': 'institution_bound',
                    'host_id': 'host_alpha',
                    'host_role': 'institution_host',
                    'admission_id': '',
                    'federation_mode': 'federated_runtime_core',
                    'context_source': self.context_source,
                    'founded_at': '',
                }

        captured = {}
        handler = object.__new__(self.workspace.WorkspaceHandler)
        handler.path = '/api/payouts/execute'
        handler.headers = _Headers()
        handler._require_auth = lambda _path: True
        handler._session_claims_from_request = lambda expected_org_id=None: None
        handler._read_body = lambda: {'proposal_id': 'pay_demo', 'warrant_id': 'war_demo'}
        handler._json = lambda data, status=200: captured.update({'status': status, 'data': data})
        handler._html = lambda html: captured.update({'status': 200, 'html': html})

        def fake_handle_post(_handler, _path, **kwargs):
            _handler._json({'delegated': 'treasury_service', 'actor_id': kwargs['actor_id']})
            return {'delegated': True}

        with mock.patch.object(self.workspace, '_resolve_workspace_context', return_value=FakeContext()),              mock.patch.object(self.workspace, '_resolve_auth_context', return_value={'enabled': True, 'role': 'owner', 'actor_id': 'user_owner'}),              mock.patch.object(self.workspace, '_enforce_mutation_authorization', return_value='owner'),              mock.patch.object(self.workspace.treasury_service, 'handle_post', side_effect=fake_handle_post),              mock.patch.object(self.workspace, 'execute_payout_proposal', side_effect=self.fail):
            handler.do_POST()

        self.assertEqual(captured['status'], 200)
        self.assertEqual(captured['data']['delegated'], 'treasury_service')
        self.assertEqual(captured['data']['actor_id'], 'user_owner')

    def test_workspace_do_post_delegates_court_service(self):
        class FakeContext:
            def __init__(self):
                self.org_id = 'org_a'
                self.org = {'id': 'org_a', 'name': 'Org A'}
                self.context_source = 'configured_org'

            def to_dict(self):
                return {
                    'org_id': self.org_id,
                    'org_name': self.org.get('name', ''),
                    'boundary_name': 'workspace',
                    'identity_model': 'session',
                    'routing_scope': 'institution_bound',
                    'host_id': 'host_alpha',
                    'host_role': 'institution_host',
                    'admission_id': '',
                    'federation_mode': 'federated_runtime_core',
                    'context_source': self.context_source,
                    'founded_at': '',
                }

        captured = {}
        handler = object.__new__(self.workspace.WorkspaceHandler)
        handler.path = '/api/court/file'
        handler.headers = _Headers()
        handler._require_auth = lambda _path: True
        handler._session_claims_from_request = lambda expected_org_id=None: None
        handler._read_body = lambda: {
            'agent': 'agent_atlas_a',
            'type': 'policy_violation',
            'severity': 'moderate',
            'evidence': 'demo',
        }
        handler._json = lambda data, status=200: captured.update({'status': status, 'data': data})
        handler._html = lambda html: captured.update({'status': 200, 'html': html})

        def fake_handle_post(_handler, _path, **kwargs):
            _handler._json({'delegated': 'court_service', 'org_id': kwargs['org_id']})
            return {'delegated': True}

        with mock.patch.object(self.workspace, '_resolve_workspace_context', return_value=FakeContext()),              mock.patch.object(self.workspace, '_resolve_auth_context', return_value={'enabled': True, 'role': 'admin', 'actor_id': 'user_admin'}),              mock.patch.object(self.workspace, '_enforce_mutation_authorization', return_value='admin'),              mock.patch.object(self.workspace.court_service, 'handle_post', side_effect=fake_handle_post),              mock.patch.object(self.workspace, 'file_violation', side_effect=self.fail):
            handler.do_POST()

        self.assertEqual(captured['status'], 200)
        self.assertEqual(captured['data']['delegated'], 'court_service')


if __name__ == '__main__':
    unittest.main()
