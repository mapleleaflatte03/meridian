#!/usr/bin/env python3
import os
import sys
import unittest
from unittest import mock

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

import workspace


class _Headers:
    def get(self, k, default=None):
        return default


class _FakePostHandler:
    def __init__(self, path, body):
        self.path = path
        self.headers = _Headers()
        self._body = body

    def _require_auth(self, path):
        return True

    def _session_claims_from_request(self, *args, **kwargs):
        return {}

    def _read_body(self):
        return dict(self._body)

    def _json(self, data, status=200):
        self.response = {'data': data, 'status': status}
        return self.response


class _FakeGetHandler:
    def __init__(self, path):
        self.path = path
        self.headers = _Headers()

    def _require_auth(self, path):
        return True

    def _session_claims_from_request(self, *args, **kwargs):
        return {}

    def _json(self, data, status=200):
        self.response = {'data': data, 'status': status}
        return self.response

    def _html(self, data, status=200):
        self.response = {'data': data, 'status': status}
        return self.response

    def _text(self, data, status=200):
        self.response = {'data': data, 'status': status}
        return self.response


class WorkspaceSideHustleRouteTest(unittest.TestCase):
    def test_side_hustle_api_route_calls_run_side_hustle(self):
        handler = _FakePostHandler(
            '/api/agent/hustle',
            {
                'agent_id': 'agent_123',
                'task_description': 'Create ad copy',
                'amount_usd': 50.0,
                'proof_receipt': 'proof_ad',
                'assigned_by': 'ad_network',
                'settled_by': 'ad_network',
                'estimated_cost_usd': 0.10,
            },
        )

        with mock.patch('workspace._resolve_workspace_context') as mock_ctx, \
             mock.patch('workspace._enforce_request_context'), \
             mock.patch('workspace._resolve_auth_context') as mock_auth, \
             mock.patch('workspace._enforce_mutation_authorization'), \
             mock.patch('workspace.side_hustle') as mock_sh, \
             mock.patch('workspace.log_event'):
            mock_ctx.return_value = type('Ctx', (), {'org_id': 'meridian'})()
            mock_auth.return_value = {'actor_id': 'test_user', 'session_id': 'test_session'}
            mock_sh.run_side_hustle.return_value = {'status': 'settled', 'split': {}}

            workspace.WorkspaceHandler.do_POST(handler)

            mock_sh.run_side_hustle.assert_called_once_with(
                agent_id='agent_123',
                org_id='meridian',
                task_description='Create ad copy',
                amount_usd=50.0,
                proof_receipt='proof_ad',
                assigned_by='ad_network',
                settled_by='ad_network',
                estimated_cost_usd=0.10,
            )
            self.assertEqual(handler.response['data']['status'], 'settled')

    def test_team_governed_execution_route_calls_team_wrapper(self):
        handler = _FakePostHandler(
            '/api/team/governed-execution',
            {
                'agent_id': 'agent_team',
                'task_description': 'Prepare governed memo',
                'amount_usd': 25.0,
                'proof_receipt': 'proof_team',
                'assigned_by': 'ops_lead',
                'settled_by': 'ops_lead',
                'estimated_cost_usd': 0.15,
            },
        )

        with mock.patch('workspace._resolve_workspace_context') as mock_ctx, \
             mock.patch('workspace._enforce_request_context'), \
             mock.patch('workspace._resolve_auth_context') as mock_auth, \
             mock.patch('workspace._enforce_mutation_authorization'), \
             mock.patch('workspace.team_governed_execution') as mock_team, \
             mock.patch('workspace.log_event'):
            mock_ctx.return_value = type('Ctx', (), {'org_id': 'meridian'})()
            mock_auth.return_value = {'actor_id': 'test_user', 'session_id': 'test_session'}
            mock_team.run_team_governed_execution.return_value = {'status': 'settled', 'team_mode': 'team'}

            workspace.WorkspaceHandler.do_POST(handler)

            mock_team.run_team_governed_execution.assert_called_once_with(
                org_id='meridian',
                actor_id='test_user',
                request_payload={
                    'agent_id': 'agent_team',
                    'task_description': 'Prepare governed memo',
                    'amount_usd': 25.0,
                    'proof_receipt': 'proof_team',
                    'assigned_by': 'ops_lead',
                    'settled_by': 'ops_lead',
                    'estimated_cost_usd': 0.15,
                },
                meridian_root=(
                    os.environ.get('MERIDIAN_ROOT', '')
                    or os.path.abspath(os.path.join(workspace.WORKSPACE, '..'))
                ),
            )
            self.assertEqual(handler.response['data']['team_mode'], 'team')

    def test_team_governed_execution_inspect_route_returns_governance_views(self):
        handler = _FakeGetHandler('/api/team/governed-execution/inspect?agent_id=agent_team')

        with mock.patch('workspace._resolve_workspace_context') as mock_ctx, \
             mock.patch('workspace._enforce_request_context', return_value={}), \
             mock.patch('workspace._resolve_auth_context', return_value={'actor_id': 'owner_1'}), \
             mock.patch('workspace.load_orgs', return_value={'organizations': {'meridian': {'id': 'meridian', 'slug': 'meridian'}}}), \
             mock.patch('workspace.get_org', return_value={'id': 'meridian', 'slug': 'meridian'}), \
             mock.patch('workspace._load_workspace_credentials', return_value=(None, None, None, None)), \
             mock.patch('workspace._runtime_host_state', return_value=(type('HostIdentity', (), {'settlement_adapters': []})(), {})), \
             mock.patch('workspace._load_queue', return_value={'kill_switch': {'engaged': False}, 'delegations': {}}), \
             mock.patch('workspace.get_pending_approvals', return_value=[{'id': 'apr_1'}]), \
             mock.patch('workspace.get_sprint_lead', return_value=('lead_agent', 11)), \
             mock.patch('workspace.load_registry', return_value={'agents': {}}), \
             mock.patch('workspace.treasury_snapshot', return_value={'balance_usd': 150.0, 'reserve_floor_usd': 50.0}), \
             mock.patch('workspace.get_agent_record', return_value={'agent_id': 'agent_team', 'open_violations': 0, 'active_restrictions': []}), \
             mock.patch('workspace.query_events', return_value=[{'id': 'evt_1'}]), \
             mock.patch('workspace.audit_stats', return_value={'total_events': 1}):
            mock_ctx.return_value = type('Ctx', (), {'org_id': 'meridian', 'org': {'id': 'meridian', 'slug': 'meridian'}, 'context_source': 'test', 'to_dict': lambda self: {'org_id': 'meridian'}})()

            workspace.WorkspaceHandler.do_GET(handler)

            self.assertEqual(handler.response['status'], 200)
            self.assertEqual(handler.response['data']['treasury']['balance_usd'], 150.0)
            self.assertEqual(handler.response['data']['court']['agent_id'], 'agent_team')
            self.assertEqual(handler.response['data']['audit']['summary']['total_events'], 1)

    def test_team_governed_execution_audit_export_route_requires_agent_id(self):
        handler = _FakeGetHandler('/api/team/governed-execution/audit-export')

        with mock.patch('workspace._resolve_workspace_context') as mock_ctx, \
             mock.patch('workspace._enforce_request_context', return_value={}), \
             mock.patch('workspace._resolve_auth_context', return_value={'actor_id': 'owner_1'}), \
             mock.patch('workspace.load_orgs', return_value={'organizations': {'meridian': {'id': 'meridian', 'slug': 'meridian'}}}), \
             mock.patch('workspace.get_org', return_value={'id': 'meridian', 'slug': 'meridian'}), \
             mock.patch('workspace._load_workspace_credentials', return_value=(None, None, None, None)), \
             mock.patch('workspace._runtime_host_state', return_value=(type('HostIdentity', (), {'settlement_adapters': []})(), {})):
            mock_ctx.return_value = type('Ctx', (), {'org_id': 'meridian', 'org': {'id': 'meridian', 'slug': 'meridian'}, 'context_source': 'test', 'to_dict': lambda self: {'org_id': 'meridian'}})()

            workspace.WorkspaceHandler.do_GET(handler)

            self.assertEqual(handler.response['status'], 400)
            self.assertEqual(handler.response['data']['error'], 'agent_id is required')


if __name__ == '__main__':
    unittest.main()
