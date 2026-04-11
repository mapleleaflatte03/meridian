#!/usr/bin/env python3
"""Tests for Hands (ready-to-use agent templates)."""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PLATFORM_DIR)

from hands import list_hand_templates, provision_hand, provision_all_hands, HAND_TEMPLATES


class TestHandTemplates(unittest.TestCase):
    def test_list_returns_all_five_templates(self):
        templates = list_hand_templates()
        self.assertEqual(len(templates), 5)
        keys = {t['key'] for t in templates}
        self.assertEqual(keys, {'researcher', 'twitter_manager', 'daily_brief', 'treasury_auditor', 'code_reviewer'})

    def test_each_template_has_required_fields(self):
        for tpl in list_hand_templates():
            self.assertIn('name', tpl)
            self.assertIn('role', tpl)
            self.assertIn('purpose', tpl)
            self.assertIn('scopes', tpl)
            self.assertIn('budget', tpl)
            self.assertIsInstance(tpl['scopes'], list)
            self.assertGreater(len(tpl['scopes']), 0)


class TestHandProvisioning(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.registry_file = os.path.join(self.temp_dir, 'agent_registry.json')
        self.orgs_file = os.path.join(self.temp_dir, 'organizations.json')

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_provision_hand_creates_agent(self):
        call_count = [0]
        def mock_load_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return {'agents': {}}
            return {'agents': {'agent_researcher_abc123': {
                'id': 'agent_researcher_abc123',
                'name': 'Researcher',
                'org_id': 'org_test',
            }}}
        with patch('hands.load_registry', side_effect=mock_load_side_effect), \
             patch('hands.register_agent', return_value='agent_researcher_abc123') as mock_reg:
            result = provision_hand('org_test', 'researcher')
            mock_reg.assert_called_once()
            self.assertEqual(result['name'], 'Researcher')

    def test_provision_unknown_hand_raises(self):
        with self.assertRaises(ValueError) as ctx:
            provision_hand('org_test', 'nonexistent_hand')
        self.assertIn('nonexistent_hand', str(ctx.exception))

    def test_provision_all_hands_creates_five(self):
        created = []
        with patch('hands.load_registry') as mock_load, \
             patch('hands.register_agent') as mock_reg:
            mock_load.return_value = {'agents': {}}
            mock_reg.side_effect = lambda **kw: f'agent_{kw["name"].lower()}_test'
            results = provision_all_hands('org_test')
        self.assertEqual(len(results), 5)

    def test_provision_idempotent_skips_existing(self):
        with patch('hands.load_registry') as mock_load, \
             patch('hands.register_agent') as mock_reg:
            mock_load.return_value = {'agents': {
                'agent_researcher_existing': {
                    'id': 'agent_researcher_existing',
                    'org_id': 'org_test',
                    'name': 'Researcher',
                }
            }}
            result = provision_hand('org_test', 'researcher')
            mock_reg.assert_not_called()
            self.assertEqual(result['id'], 'agent_researcher_existing')


if __name__ == '__main__':
    unittest.main()
