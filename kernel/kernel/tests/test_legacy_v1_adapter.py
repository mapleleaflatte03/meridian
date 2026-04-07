#!/usr/bin/env python3
import os
import sys
import unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, ROOT)

from adapters import legacy_v1_compatible as adapter
import runtime_adapter


class LegacyV1AdapterTests(unittest.TestCase):
    def setUp(self):
        self.orig_check_authority = adapter.check_authority
        self.orig_check_budget = adapter.check_budget
        self.orig_get_restrictions = adapter.get_restrictions
        self.orig_meter_record = adapter.meter_record
        self.orig_log_event = adapter.log_event

    def tearDown(self):
        adapter.check_authority = self.orig_check_authority
        adapter.check_budget = self.orig_check_budget
        adapter.get_restrictions = self.orig_get_restrictions
        adapter.meter_record = self.orig_meter_record
        adapter.log_event = self.orig_log_event

    def test_adapter_proof_reports_reference_library(self):
        proof = adapter.adapter_proof()
        self.assertEqual(proof['type'], 'reference_library')
        self.assertEqual(proof['runtime_id'], 'legacy_v1_compatible')
        self.assertEqual(set(proof['implemented_hooks']), set(adapter.SUPPORTED_HOOKS))

    def test_runtime_registry_reports_reference_adapter(self):
        proof = runtime_adapter.get_adapter_proof('legacy_v1_compatible')
        self.assertEqual(proof['status'], 'available')
        self.assertEqual(proof['module'], 'adapters.legacy_v1_compatible')
        self.assertEqual(proof['assessment_basis'], 'reference_adapter_library')
        self.assertEqual(proof['type'], 'reference_library')

        contract = runtime_adapter.check_contract('legacy_v1_compatible')
        self.assertEqual(contract['status'], 'reference_adapter')
        self.assertEqual(contract['score'], 7)
        self.assertEqual(contract['total'], 7)
        self.assertEqual(
            contract['assessment_basis'],
            'declared_runtime_plus_reference_adapter',
        )
        self.assertEqual(contract['adapter_supplied'], ['agent_identity', 'action_envelope', 'cost_attribution', 'approval_hook', 'audit_emission', 'sanction_controls', 'budget_gate'])
        self.assertIn('route runtime events through that adapter', contract['verdict'])

    def test_build_action_envelope_normalizes_fields(self):
        envelope = adapter.build_action_envelope(
            ' atlas ',
            ' research ',
            ' web_search ',
            0.25,
            run_id='run_1',
            session_id='ses_1',
            details={'query': 'meridian'},
        )
        self.assertEqual(envelope['agent_id'], 'atlas')
        self.assertEqual(envelope['action_type'], 'research')
        self.assertEqual(envelope['resource'], 'web_search')
        self.assertEqual(envelope['estimated_cost_usd'], 0.25)
        self.assertEqual(envelope['run_id'], 'run_1')
        self.assertEqual(envelope['session_id'], 'ses_1')

    def test_validate_action_envelope_rejects_missing_fields(self):
        with self.assertRaises(ValueError):
            adapter.validate_action_envelope({'agent_id': '', 'action_type': 'research', 'resource': 'web'})
        with self.assertRaises(ValueError):
            adapter.validate_action_envelope({'agent_id': 'atlas', 'action_type': '', 'resource': 'web'})
        with self.assertRaises(ValueError):
            adapter.validate_action_envelope({'agent_id': 'atlas', 'action_type': 'research', 'resource': ''})

    def test_pre_session_check_blocks_execute_restriction(self):
        adapter.get_restrictions = lambda agent_id, org_id=None: ['execute']
        result = adapter.pre_session_check('org_demo', 'atlas')
        self.assertFalse(result['allowed'])
        self.assertIn('restricted from execute', result['reason'])

    def test_pre_action_check_blocks_authority_failure(self):
        adapter.get_restrictions = lambda agent_id, org_id=None: []
        adapter.check_authority = lambda agent_id, action, org_id=None: (False, 'kill switch engaged')
        envelope = adapter.build_action_envelope('atlas', 'research', 'web_search', 0.10)
        result = adapter.pre_action_check('org_demo', envelope)
        self.assertFalse(result['allowed'])
        self.assertEqual(result['stage'], 'approval_hook')
        self.assertEqual(result['reason'], 'kill switch engaged')

    def test_pre_action_check_blocks_budget_failure(self):
        adapter.get_restrictions = lambda agent_id, org_id=None: []
        adapter.check_authority = lambda agent_id, action, org_id=None: (True, 'ok')
        adapter.check_budget = lambda agent_id, cost_usd, org_id=None: (False, 'below reserve')
        envelope = adapter.build_action_envelope('atlas', 'research', 'web_search', 0.10)
        result = adapter.pre_action_check('org_demo', envelope)
        self.assertFalse(result['allowed'])
        self.assertEqual(result['stage'], 'budget_gate')
        self.assertEqual(result['reason'], 'below reserve')

    def test_pre_action_check_allows_zero_cost_without_budget_gate(self):
        calls = []
        adapter.get_restrictions = lambda agent_id, org_id=None: []
        adapter.check_authority = lambda agent_id, action, org_id=None: (True, 'ok')

        def _budget(*args, **kwargs):
            calls.append((args, kwargs))
            return True, 'ok'

        adapter.check_budget = _budget
        envelope = adapter.build_action_envelope('atlas', 'research', 'web_search', 0.0)
        result = adapter.pre_action_check('org_demo', envelope)
        self.assertTrue(result['allowed'])
        self.assertEqual(calls, [])

    def test_post_action_record_emits_meter_and_audit(self):
        seen = {}
        adapter.meter_record = lambda org_id, agent_id, metric, quantity=1.0, unit='calls', cost_usd=0.0, run_id='', details=None: (
            seen.setdefault('meter', {
                'org_id': org_id,
                'agent_id': agent_id,
                'metric': metric,
                'quantity': quantity,
                'unit': unit,
                'cost_usd': cost_usd,
                'run_id': run_id,
                'details': details,
            }) or 'meter_1'
        )
        adapter.log_event = lambda org_id, agent_id, action, resource='', outcome='success', actor_type='agent', details=None, policy_ref='', session_id=None: (
            seen.setdefault('audit', {
                'org_id': org_id,
                'agent_id': agent_id,
                'action': action,
                'resource': resource,
                'outcome': outcome,
                'actor_type': actor_type,
                'details': details,
                'session_id': session_id,
            }) or 'evt_1'
        )

        envelope = adapter.build_action_envelope(
            'atlas',
            'research',
            'web_search',
            0.10,
            run_id='run_123',
            session_id='ses_123',
            details={'query': 'meridian'},
        )
        result = adapter.post_action_record('org_demo', envelope, actual_cost_usd=0.15)
        self.assertEqual(result['cost_usd'], 0.15)
        self.assertEqual(seen['meter']['org_id'], 'org_demo')
        self.assertEqual(seen['meter']['cost_usd'], 0.15)
        self.assertEqual(seen['meter']['run_id'], 'run_123')
        self.assertEqual(seen['audit']['session_id'], 'ses_123')
        self.assertEqual(seen['audit']['action'], 'research')


if __name__ == '__main__':
    unittest.main()
