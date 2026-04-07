#!/usr/bin/env python3
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from company.meridian_platform import agent_registry


class TestAgentRegistry(unittest.TestCase):
    def setUp(self):
        self._state_dir = tempfile.mkdtemp(prefix='meridian-test-agent-registry-')
        self.registry_file = os.path.join(self._state_dir, 'agent_registry.json')

        # Mock REGISTRY_FILE
        self._orig_registry_file = agent_registry.REGISTRY_FILE
        agent_registry.REGISTRY_FILE = self.registry_file

    def tearDown(self):
        # Restore REGISTRY_FILE
        agent_registry.REGISTRY_FILE = self._orig_registry_file
        shutil.rmtree(self._state_dir, ignore_errors=True)

    def test_register_agent_success_default_params(self):
        agent_id = agent_registry.register_agent(
            org_id='org_123',
            name='TestAgent',
            role='analyst',
            purpose='Testing purposes'
        )

        self.assertTrue(agent_id.startswith('agent_testagent_'))

        with open(self.registry_file, 'r') as f:
            data = json.load(f)

        self.assertIn(agent_id, data['agents'])
        agent = data['agents'][agent_id]

        self.assertEqual(agent['org_id'], 'org_123')
        self.assertEqual(agent['name'], 'TestAgent')
        self.assertEqual(agent['role'], 'analyst')
        self.assertEqual(agent['purpose'], 'Testing purposes')

        # Check defaults
        self.assertFalse(agent['approval_required'])
        self.assertEqual(agent['scopes'], [])
        self.assertEqual(agent['model_policy']['max_context_tokens'], 200000)
        self.assertEqual(agent['model_policy']['allowed_models'], [])
        self.assertEqual(agent['budget']['max_per_run_usd'], 0.50)
        self.assertEqual(agent['rollout_state'], 'active')
        self.assertEqual(agent['risk_state'], 'nominal')
        self.assertEqual(agent['lifecycle_state'], 'active')
        self.assertEqual(agent['incident_count'], 0)
        self.assertEqual(agent['status'], 'active')

    def test_register_agent_success_custom_params(self):
        custom_scopes = ['read', 'write']
        custom_model_policy = {'allowed_models': ['gpt-4'], 'max_context_tokens': 1000}
        custom_budget = {'max_per_run_usd': 1.0, 'max_per_day_usd': 10.0, 'max_per_month_usd': 100.0}

        agent_id = agent_registry.register_agent(
            org_id='org_456',
            name='CustomAgent',
            role='executor',
            purpose='Custom testing',
            scopes=custom_scopes,
            model_policy=custom_model_policy,
            budget=custom_budget,
            approval_required=True
        )

        with open(self.registry_file, 'r') as f:
            data = json.load(f)

        agent = data['agents'][agent_id]

        self.assertEqual(agent['scopes'], custom_scopes)
        self.assertEqual(agent['model_policy'], custom_model_policy)
        self.assertEqual(agent['budget'], custom_budget)
        self.assertTrue(agent['approval_required'])

    def test_get_agent_by_economy_key_supports_org_scoping(self):
        agent_a = agent_registry.register_agent(
            org_id='org_a',
            name='AtlasA',
            role='analyst',
            purpose='Org A analyst',
        )
        agent_b = agent_registry.register_agent(
            org_id='org_b',
            name='AtlasB',
            role='analyst',
            purpose='Org B analyst',
        )

        data = agent_registry.load_registry()
        data['agents'][agent_a]['economy_key'] = 'atlas'
        data['agents'][agent_b]['economy_key'] = 'atlas'
        agent_registry.save_registry(data)

        ambiguous = agent_registry.get_agent_by_economy_key('atlas')
        self.assertIsNone(ambiguous)

        scoped = agent_registry.get_agent_by_economy_key('atlas', org_id='org_b')
        self.assertIsNotNone(scoped)
        self.assertEqual(scoped['id'], agent_b)

    def test_resolve_agent_supports_registry_id_and_economy_key(self):
        agent_id = agent_registry.register_agent(
            org_id='org_123',
            name='Resolver',
            role='analyst',
            purpose='Resolve by id and economy key',
        )
        data = agent_registry.load_registry()
        data['agents'][agent_id]['economy_key'] = 'resolver'
        agent_registry.save_registry(data)

        by_id = agent_registry.resolve_agent(agent_id, org_id='org_123')
        self.assertIsNotNone(by_id)
        self.assertEqual(by_id['id'], agent_id)

        by_key = agent_registry.resolve_agent('resolver', org_id='org_123')
        self.assertIsNotNone(by_key)
        self.assertEqual(by_key['id'], agent_id)

if __name__ == '__main__':
    unittest.main()
