#!/usr/bin/env python3
"""Tests for constitutional_trace module."""

import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
if PLATFORM_DIR not in sys.path:
    sys.path.insert(0, PLATFORM_DIR)


class ConstitutionalTraceTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.trace_file = os.path.join(self.tmp.name, 'traces.jsonl')

    def tearDown(self):
        self.tmp.cleanup()

    @mock.patch('constitutional_trace.is_kill_switch_engaged', return_value=False)
    @mock.patch('constitutional_trace.get_sprint_lead', return_value=('agent_lead', 42))
    @mock.patch('constitutional_trace.get_pending_approvals', return_value=[])
    @mock.patch('constitutional_trace._load_queue', return_value={'delegations': {}})
    @mock.patch('constitutional_trace._treasury_snapshot', return_value={
        'balance_usd': 200.0,
        'reserve_floor_usd': 50.0,
        'runway_usd': 150.0,
        'above_reserve': True,
    })
    @mock.patch('constitutional_trace.court_get_restrictions', return_value=[])
    def test_build_trace_clean_posture(self, *_mocks):
        from constitutional_trace import build_constitutional_trace
        trace = build_constitutional_trace(
            org_id='org_test',
            session_key='web_api:test',
            agent_id='agent_mgr',
            plan={'mode': 'team', 'workers': ['ATLAS', 'FORGE'], 'skills': [], 'routing_score': {'decision': 'team', 'confidence': 85}},
            steps=[{'ok': True}, {'ok': True}],
            output='Test response output.',
        )
        self.assertEqual(trace['schema_version'], 'constitutional_trace.v1')
        self.assertTrue(trace['trace_id'].startswith('ctrace_'))
        self.assertEqual(trace['institution_id'], 'org_test')
        # Authority
        self.assertFalse(trace['authority']['kill_switch_engaged'])
        self.assertEqual(trace['authority']['sprint_lead_agent_id'], 'agent_lead')
        self.assertEqual(trace['authority']['delegation_count'], 0)
        # Treasury
        self.assertEqual(trace['treasury']['balance_usd'], 200.0)
        self.assertTrue(trace['treasury']['above_reserve'])
        self.assertEqual(trace['treasury']['budget_gate'], 'passed')
        # Court
        self.assertEqual(trace['court']['posture'], 'clean')
        self.assertEqual(trace['court']['active_sanctions'], 0)
        # Route
        self.assertEqual(trace['route']['mode'], 'team')
        self.assertEqual(trace['route']['workers'], ['ATLAS', 'FORGE'])
        # Execution
        self.assertEqual(trace['execution']['steps_total'], 2)
        self.assertEqual(trace['execution']['steps_completed'], 2)
        self.assertTrue(trace['execution']['manager_synthesized'])
        self.assertTrue(trace['execution']['proof_hash'].startswith('sha256:'))

    @mock.patch('constitutional_trace.is_kill_switch_engaged', return_value=True)
    @mock.patch('constitutional_trace.get_sprint_lead', return_value=('', 0))
    @mock.patch('constitutional_trace.get_pending_approvals', return_value=[{'id': 'req_1'}])
    @mock.patch('constitutional_trace._load_queue', return_value={'delegations': {}})
    @mock.patch('constitutional_trace._treasury_snapshot', return_value={
        'balance_usd': 30.0,
        'reserve_floor_usd': 50.0,
        'runway_usd': -20.0,
        'above_reserve': False,
    })
    @mock.patch('constitutional_trace.court_get_restrictions', return_value=[
        {'severity': 4, 'type': 'rework'},
    ])
    def test_build_trace_blocked_posture(self, *_mocks):
        from constitutional_trace import build_constitutional_trace
        trace = build_constitutional_trace(
            org_id='org_test',
            session_key='web_api:test',
            agent_id='agent_bad',
            plan={'mode': 'direct', 'reason': 'greeting'},
            steps=[],
            output='Hi there.',
        )
        self.assertTrue(trace['authority']['kill_switch_engaged'])
        self.assertEqual(trace['authority']['pending_approvals'], 1)
        self.assertFalse(trace['treasury']['above_reserve'])
        self.assertEqual(trace['treasury']['budget_gate'], 'blocked')
        self.assertEqual(trace['court']['posture'], 'blocked')
        self.assertEqual(trace['court']['blocking_violations'], 1)
        self.assertEqual(trace['route']['mode'], 'direct')
        self.assertFalse(trace['execution']['manager_synthesized'])

    def test_persist_and_load_traces(self):
        from constitutional_trace import persist_trace, load_recent_traces, trace_file_path
        with mock.patch.dict(os.environ, {'MERIDIAN_CONSTITUTIONAL_TRACE_FILE': self.trace_file}):
            trace_1 = {
                'schema_version': 'constitutional_trace.v1',
                'trace_id': 'ctrace_001',
                'timestamp': '2026-04-22T09:00:00Z',
                'institution_id': 'org_test',
            }
            trace_2 = {
                'schema_version': 'constitutional_trace.v1',
                'trace_id': 'ctrace_002',
                'timestamp': '2026-04-22T09:01:00Z',
                'institution_id': 'org_test',
            }
            self.assertEqual(trace_file_path(), self.trace_file)
            persist_trace(trace_1)
            persist_trace(trace_2)
            loaded = load_recent_traces(limit=10)
            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded[0]['trace_id'], 'ctrace_002')
            self.assertEqual(loaded[1]['trace_id'], 'ctrace_001')

    def test_load_traces_empty_file(self):
        from constitutional_trace import load_recent_traces
        with mock.patch.dict(os.environ, {'MERIDIAN_CONSTITUTIONAL_TRACE_FILE': self.trace_file}):
            loaded = load_recent_traces(limit=10)
            self.assertEqual(loaded, [])

    def test_load_traces_with_limit(self):
        from constitutional_trace import persist_trace, load_recent_traces
        with mock.patch.dict(os.environ, {'MERIDIAN_CONSTITUTIONAL_TRACE_FILE': self.trace_file}):
            for i in range(5):
                persist_trace({
                    'trace_id': f'ctrace_{i:03d}',
                    'timestamp': f'2026-04-22T09:{i:02d}:00Z',
                })
            loaded = load_recent_traces(limit=2)
            self.assertEqual(len(loaded), 2)

    def test_execution_summary_counts_ok_status_as_completed(self):
        from constitutional_trace import _execution_summary
        summary = _execution_summary(
            [
                {'status': 'ok', 'agent_id': 'agent_forge'},
                {'status': 'success', 'agent_id': 'agent_quill'},
                {'status': 'error', 'agent_id': 'agent_aegis'},
            ],
            'done',
            mode='team',
        )
        self.assertEqual(summary['steps_total'], 3)
        self.assertEqual(summary['steps_completed'], 2)
        self.assertEqual(summary['steps_failed'], 1)
        self.assertTrue(summary['manager_synthesized'])


if __name__ == '__main__':
    unittest.main()
