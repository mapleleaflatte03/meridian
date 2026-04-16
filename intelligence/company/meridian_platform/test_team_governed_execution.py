#!/usr/bin/env python3
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

import team_governed_execution


class TeamGovernedExecutionTest(unittest.TestCase):
    def test_require_team_mode_blocks_core_mode(self):
        self.assertEqual(
            team_governed_execution.require_team_mode({'mode': 'core'}),
            (False, 'Team governed execution requires Meridian Team mode.'),
        )

    def test_require_team_mode_allows_team_mode(self):
        self.assertEqual(
            team_governed_execution.require_team_mode({'mode': 'team'}),
            (True, 'ok'),
        )

    def test_load_onboard_state_reads_runtime_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = os.path.join(tmp, 'runtime')
            os.makedirs(runtime_dir, exist_ok=True)
            state_path = os.path.join(runtime_dir, 'onboard_state.json')
            with open(state_path, 'w', encoding='utf-8') as fh:
                json.dump({'mode': 'team', 'org_id': 'org_team'}, fh)

            loaded = team_governed_execution.load_onboard_state(meridian_root=tmp)
            self.assertEqual(loaded['mode'], 'team')
            self.assertEqual(loaded['org_id'], 'org_team')

    def test_build_audit_export_aggregates_real_governance_views(self):
        execution_result = {
            'status': 'settled',
            'bid_id': 'bid_123',
            'assignment_id': 'asgn_123',
            'settlement_id': 'stl_123',
            'settlement_receipt': 'settle_receipt',
            'proof_chain': {
                'proof_receipt': 'proof_123',
                'memory_hash': 'memory_hash_123',
                'settlement_receipt': 'settle_receipt',
            },
            'governance_checks': {
                'budget': {'allowed': True, 'reason': 'ok'},
                'court': {'allowed': True, 'reason': 'ok', 'blocking_violations': []},
            },
        }
        authority_snapshot = {
            'kill_switch': {'engaged': False},
            'pending_approvals': [{'id': 'apr_1'}],
            'delegations': [],
            'sprint_lead': {'agent_id': 'agent_lead'},
        }
        treasury_snapshot = {
            'balance_usd': 150.0,
            'reserve_floor_usd': 50.0,
        }
        court_record = {
            'agent_id': 'agent_123',
            'active_restrictions': [],
            'open_violations': 0,
        }
        audit_events = [
            {'id': 'evt_1', 'action': 'side_hustle_executed', 'outcome': 'success'},
            {'id': 'evt_2', 'action': 'team_governed_execution_exported', 'outcome': 'success'},
        ]
        audit_summary = {'total_events': 2, 'actions': {'side_hustle_executed': 1}}

        artifact = team_governed_execution.build_audit_export(
            org_id='org_team',
            actor_id='owner_1',
            team_mode='team',
            request_payload={'agent_id': 'agent_123', 'task_description': 'Write governed memo'},
            execution_result=execution_result,
            authority_snapshot=authority_snapshot,
            treasury_snapshot=treasury_snapshot,
            court_record=court_record,
            audit_events=audit_events,
            audit_summary=audit_summary,
        )

        self.assertEqual(artifact['org_id'], 'org_team')
        self.assertEqual(artifact['team_mode'], 'team')
        self.assertEqual(artifact['execution']['status'], 'settled')
        self.assertEqual(artifact['authority']['pending_approval_count'], 1)
        self.assertEqual(artifact['treasury']['balance_usd'], 150.0)
        self.assertEqual(artifact['court']['open_violations'], 0)
        self.assertEqual(artifact['audit']['event_count'], 2)
        self.assertEqual(artifact['proof_chain']['memory_hash'], 'memory_hash_123')

    def test_run_team_governed_execution_blocks_non_team_mode(self):
        with mock.patch('team_governed_execution.load_onboard_state', return_value={'mode': 'core'}):
            result = team_governed_execution.run_team_governed_execution(
                org_id='org_core',
                actor_id='owner_1',
                request_payload={
                    'agent_id': 'agent_123',
                    'task_description': 'Governed task',
                    'amount_usd': 10.0,
                    'proof_receipt': 'proof_1',
                    'assigned_by': 'operator',
                    'settled_by': 'operator',
                },
            )

        self.assertEqual(result['status'], 'blocked')
        self.assertIn('Team mode', result['reason'])

    def test_run_team_governed_execution_reuses_existing_surfaces(self):
        request_payload = {
            'agent_id': 'agent_123',
            'task_description': 'Write governed memo',
            'amount_usd': 15.0,
            'proof_receipt': 'proof_123',
            'assigned_by': 'operator',
            'settled_by': 'operator',
            'estimated_cost_usd': 0.25,
        }
        with mock.patch('team_governed_execution.load_onboard_state', return_value={'mode': 'team'}), \
             mock.patch('team_governed_execution.side_hustle.run_side_hustle') as mock_run, \
             mock.patch('team_governed_execution._governance_checks') as mock_checks, \
             mock.patch('team_governed_execution._authority_snapshot') as mock_authority, \
             mock.patch('team_governed_execution.treasury_snapshot') as mock_treasury, \
             mock.patch('team_governed_execution.get_agent_record') as mock_court, \
             mock.patch('team_governed_execution.query_events') as mock_audit_events, \
             mock.patch('team_governed_execution.stats') as mock_audit_stats, \
             mock.patch('team_governed_execution.log_event') as mock_log:
            mock_run.return_value = {
                'status': 'settled',
                'settlement_receipt': 'settle_receipt',
                'proof_chain': {
                    'proof_receipt': 'proof_123',
                    'memory_hash': 'memory_hash_123',
                    'settlement_receipt': 'settle_receipt',
                },
                'governance_checks': {
                    'budget': {'allowed': True, 'reason': 'ok'},
                    'court': {'allowed': True, 'reason': 'ok', 'blocking_violations': []},
                },
            }
            mock_checks.return_value = {
                'budget': {'allowed': True, 'reason': 'ok', 'estimated_cost_usd': 0.25},
                'court': {'allowed': True, 'reason': 'ok', 'blocking_violations': []},
            }
            mock_authority.return_value = {
                'kill_switch': {'engaged': False},
                'pending_approvals': [],
                'delegations': [],
                'sprint_lead': {'agent_id': 'agent_lead'},
            }
            mock_treasury.return_value = {'balance_usd': 120.0, 'reserve_floor_usd': 50.0}
            mock_court.return_value = {'agent_id': 'agent_123', 'active_restrictions': [], 'open_violations': 0}
            mock_audit_events.return_value = [{'id': 'evt_1', 'action': 'side_hustle_executed'}]
            mock_audit_stats.return_value = {'total_events': 1}

            result = team_governed_execution.run_team_governed_execution(
                org_id='org_team',
                actor_id='owner_1',
                request_payload=request_payload,
            )

        mock_run.assert_called_once_with(
            agent_id='agent_123',
            org_id='org_team',
            task_description='Write governed memo',
            amount_usd=15.0,
            proof_receipt='proof_123',
            assigned_by='operator',
            settled_by='operator',
            estimated_cost_usd=0.25,
        )
        self.assertEqual(result['status'], 'settled')
        self.assertEqual(result['team_mode'], 'team')
        self.assertIn('audit_export', result)
        self.assertEqual(result['audit_export']['audit']['event_count'], 1)
        mock_log.assert_called_once()


if __name__ == '__main__':
    unittest.main()
