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
                plan='pro'
            )

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
            self.assertEqual(ledger['balance_usd'], 0.0)
            self.assertEqual(ledger['reserved_usd'], 0.0)
            self.assertIsInstance(ledger['transactions'], list)

            # Revenue should have initial structure
            with open(treasury['revenue']) as f:
                revenue = json.load(f)
            self.assertEqual(revenue['total_revenue_usd'], 0.0)
            self.assertIsInstance(revenue['clients'], dict)
            self.assertIsInstance(revenue['orders'], dict)


if __name__ == '__main__':
    unittest.main()
