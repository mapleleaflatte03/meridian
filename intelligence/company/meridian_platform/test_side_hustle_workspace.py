#!/usr/bin/env python3
import os
import sys
import unittest
from unittest import mock

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

import workspace

class _Headers:
    def get(self, k, default=None): return default

class WorkspaceSideHustleRouteTest(unittest.TestCase):
    def test_side_hustle_api_route_calls_run_side_hustle(self):
        class FakeHandler:
            def __init__(self):
                self.path = '/api/agent/hustle'
                self.headers = _Headers()
            def _require_auth(self, path):
                return True
            def _session_claims_from_request(self, *args, **kwargs):
                return {}
            def _read_body(self):
                return {
                    'agent_id': 'agent_123',
                    'task_description': 'Create ad copy',
                    'amount_usd': 50.0,
                    'proof_receipt': 'proof_ad',
                    'assigned_by': 'ad_network',
                    'settled_by': 'ad_network',
                    'estimated_cost_usd': 0.10
                }
            def _json(self, data, status=200):
                self.response = {'data': data, 'status': status}
                return self.response

        handler = FakeHandler()

        # Patch route dependencies so execution reaches the hustle branch.
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
                estimated_cost_usd=0.10
            )
            self.assertEqual(handler.response['data']['status'], 'settled')

if __name__ == '__main__':
    unittest.main()
