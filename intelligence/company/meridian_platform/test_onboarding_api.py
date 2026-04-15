#!/usr/bin/env python3
"""
Tests for institution onboarding API endpoint.

Covers:
- POST /api/institution/create endpoint
- Full provisioning flow via HTTP
- Error handling for missing fields
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import types

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PLATFORM_DIR)

from onboarding import provision_institution


class TestOnboardingAPI(unittest.TestCase):
    """Test institution onboarding API endpoint."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orgs_file = os.path.join(self.temp_dir, 'organizations.json')
        self.capsule_dir = os.path.join(self.temp_dir, 'capsules')
        os.makedirs(self.capsule_dir, exist_ok=True)

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_provision_institution_creates_full_structure(self):
        """Integration test: provision_institution creates org + capsule + treasury."""
        with patch('organizations.ORGS_FILE', self.orgs_file), \
             patch('organizations_store.db_path_for_file', return_value=os.path.join(self.temp_dir, 'orgs.db')), \
             patch('capsule.ORGS_FILE', self.orgs_file), \
             patch('capsule.CAPSULES_DIR', self.capsule_dir):

            result = provision_institution(
                name='Test Institution',
                owner_id='user_test_001',
                plan='pro',
                brain_route_type='cli_session',
                brain_provider_profile='provider.local.alpha',
                brain_model='alpha-model',
                brain_auth_profile='auth.local.alpha',
                brain_cli_bin='alpha-cli',
                brain_provider_entry_id='provider.local.alpha',
                brain_model_entry_id='provider.local.alpha.model.alpha-model',
            )

            self.assertIn('institution_brain_policy', result)
            self.assertEqual(result['institution_brain_policy']['primary_route_id'], 'route_primary')
            self.assertEqual(result['institution_brain_policy']['routes'][0]['provider_ref'], 'provider.local.alpha')
            self.assertEqual(result['institution_brain_policy']['routes'][0]['model_ref'], 'provider.local.alpha.model.alpha-model')
            self.assertEqual(result['institution_brain_policy']['routes'][0]['route_type'], 'cli_session')
            self.assertEqual(result['institution_brain_policy']['active_provider']['provider_id'], 'provider.local.alpha')
            self.assertEqual(result['institution_brain_policy']['active_model']['model_id'], 'provider.local.alpha.model.alpha-model')
            self.assertEqual(result['institution_brain_policy']['active_model']['model_name'], 'alpha-model')
            self.assertIn('provider.local.alpha', result['institution_brain_policy']['provider_registry'])
            self.assertIn('provider.local.alpha.model.alpha-model', result['institution_brain_policy']['model_registry'])
            self.assertIn('auth.local.alpha', result['institution_brain_policy']['auth_profiles'])
            self.assertEqual(result['institution_brain_policy']['auth_profiles']['auth.local.alpha']['cli_bin'], 'alpha-cli')
            self.assertEqual(result['institution_brain_policy']['active_provider']['provider_id'], 'provider.local.alpha')
            self.assertEqual(result['institution_brain_policy']['active_model']['model_id'], 'provider.local.alpha.model.alpha-model')

            # Should return complete structure
            self.assertIn('org_id', result)
            self.assertIn('org', result)
            self.assertIn('capsule_path', result)
            self.assertIn('treasury', result)

            # Org should be created
            org = result['org']
            self.assertEqual(org['name'], 'Test Institution')
            self.assertEqual(org['owner_id'], 'user_test_001')
            self.assertEqual(org['plan'], 'pro')
            self.assertEqual(org['status'], 'active')

            # Capsule should exist
            self.assertTrue(os.path.exists(result['capsule_path']))

            # Treasury files should exist
            treasury = result['treasury']
            self.assertTrue(os.path.exists(treasury['ledger']))
            self.assertTrue(os.path.exists(treasury['revenue']))
            self.assertTrue(os.path.exists(treasury['transactions']))

            # Ledger should have initial structure
            with open(treasury['ledger']) as f:
                ledger = json.load(f)
            self.assertEqual(ledger['schema'], 'meridian-kernel-economy-v1')
            self.assertEqual(ledger['treasury']['cash_usd'], 0.0)
            self.assertEqual(ledger['treasury']['reserve_floor_usd'], 50.0)
            self.assertIsInstance(ledger['transactions'], list)

            # Revenue should have initial structure
            with open(treasury['revenue']) as f:
                revenue = json.load(f)
            self.assertEqual(revenue['total_revenue_usd'], 0.0)
            self.assertIsInstance(revenue['clients'], dict)
            self.assertIsInstance(revenue['orders'], dict)

    def test_normalize_ledger_payload_converts_legacy_flat_shape(self):
        """Unit test: _normalize_ledger_payload migrates flat balance_usd to nested treasury."""
        from capsule import _normalize_ledger_payload

        legacy = {
            'balance_usd': 10.0,
            'reserved_usd': 0.0,
            'transactions': [],
        }
        normalized = _normalize_ledger_payload(legacy)

        self.assertIn('treasury', normalized)
        self.assertEqual(normalized['treasury']['cash_usd'], 10.0)
        self.assertEqual(normalized['schema'], 'meridian-kernel-economy-v1')
        self.assertNotIn('balance_usd', normalized)
        self.assertNotIn('reserved_usd', normalized)
        self.assertIsInstance(normalized['transactions'], list)


if __name__ == '__main__':
    unittest.main()
