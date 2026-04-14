#!/usr/bin/env python3
"""
Tests for institution onboarding flow.

Covers:
- Institution creation with isolated bootstrap
- Treasury/court/memory context provisioning
- Org admission lifecycle
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PLATFORM_DIR)

from organizations import create_org, get_org, load_orgs
from institution_context import InstitutionContext, WORKSPACE_BOUNDARY
from onboarding import provision_institution


class TestInstitutionOnboarding(unittest.TestCase):
    """Test institution creation and bootstrap isolation."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orgs_file = os.path.join(self.temp_dir, 'organizations.json')

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_create_institution_generates_unique_id_and_slug(self):
        """RED: Institution creation should generate unique org_id and slug."""
        with patch('organizations.ORGS_FILE', self.orgs_file), \
             patch('organizations_store.db_path_for_file', return_value=os.path.join(self.temp_dir, 'orgs.db')):
            # Create first institution
            org_id_1 = create_org('Test Institution', 'user_test_001', 'free')
            org_1 = get_org(org_id_1)

            self.assertIsNotNone(org_1)
            self.assertEqual(org_1['name'], 'Test Institution')
            self.assertEqual(org_1['slug'], 'test-institution')
            self.assertEqual(org_1['owner_id'], 'user_test_001')
            self.assertEqual(org_1['plan'], 'free')
            self.assertEqual(org_1['status'], 'active')
            self.assertEqual(org_1['lifecycle_state'], 'active')

            # Create second institution with same name
            org_id_2 = create_org('Test Institution', 'user_test_002', 'pro')
            org_2 = get_org(org_id_2)

            # Should have different IDs and slugs
            self.assertNotEqual(org_id_1, org_id_2)
            self.assertNotEqual(org_1['slug'], org_2['slug'])
            self.assertTrue(org_2['slug'].startswith('test-institution-'))

    def test_institution_has_isolated_treasury_pointer(self):
        """RED: Each institution should have isolated treasury pointer."""
        with patch('organizations.ORGS_FILE', self.orgs_file), \
             patch('organizations_store.db_path_for_file', return_value=os.path.join(self.temp_dir, 'orgs.db')):
            org_id = create_org('Acme Corp', 'user_acme_001', 'enterprise')
            org = get_org(org_id)

            # Treasury pointer should be None initially (set during bootstrap)
            self.assertIsNone(org.get('treasury_id'))

            # After bootstrap, should point to capsule-scoped treasury
            # This will be tested in integration test with actual bootstrap

    def test_institution_has_policy_defaults(self):
        """RED: New institution should have policy defaults."""
        with patch('organizations.ORGS_FILE', self.orgs_file), \
             patch('organizations_store.db_path_for_file', return_value=os.path.join(self.temp_dir, 'orgs.db')):
            org_id = create_org('Policy Test Org', 'user_policy_001', 'free')
            org = get_org(org_id)

            policy = org.get('policy_defaults', {})
            self.assertIn('max_budget_per_agent_usd', policy)
            self.assertIn('require_approval_above_usd', policy)
            self.assertIn('auto_sanctions_enabled', policy)
            self.assertIn('auth_decay_per_epoch', policy)

            # Defaults should match expected values
            self.assertEqual(policy['max_budget_per_agent_usd'], 10.0)
            self.assertEqual(policy['require_approval_above_usd'], 5.0)
            self.assertTrue(policy['auto_sanctions_enabled'])
            self.assertEqual(policy['auth_decay_per_epoch'], 5)

    def test_institution_context_resolves_for_new_org(self):
        """RED: InstitutionContext should resolve for newly created org."""
        with patch('organizations.ORGS_FILE', self.orgs_file), \
             patch('organizations_store.db_path_for_file', return_value=os.path.join(self.temp_dir, 'orgs.db')):
            org_id = create_org('Context Test Org', 'user_ctx_001', 'starter')

            # Should be able to bind context to new org
            ctx = InstitutionContext.resolve(WORKSPACE_BOUNDARY, configured_org_id=org_id)

            self.assertEqual(ctx.org_id, org_id)
            self.assertTrue(ctx.is_admitted)
            self.assertEqual(ctx.identity_model, 'session')
            self.assertEqual(ctx.scope, 'institution_bound')

    def test_multiple_institutions_can_coexist(self):
        """RED: Multiple institutions should coexist without interference."""
        with patch('organizations.ORGS_FILE', self.orgs_file), \
             patch('organizations_store.db_path_for_file', return_value=os.path.join(self.temp_dir, 'orgs.db')):
            org_id_a = create_org('Institution A', 'user_a', 'free')
            org_id_b = create_org('Institution B', 'user_b', 'pro')
            org_id_c = create_org('Institution C', 'user_c', 'enterprise')

            orgs_data = load_orgs()
            all_orgs = orgs_data['organizations']

            self.assertEqual(len(all_orgs), 3)
            self.assertIn(org_id_a, all_orgs)
            self.assertIn(org_id_b, all_orgs)
            self.assertIn(org_id_c, all_orgs)

            # Each should have unique slug
            slugs = {org['slug'] for org in all_orgs.values()}
            self.assertEqual(len(slugs), 3)


class TestInstitutionBootstrap(unittest.TestCase):
    """Test institution bootstrap provisioning (integration-level)."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orgs_file = os.path.join(self.temp_dir, 'organizations.json')
        self.capsule_dir = os.path.join(self.temp_dir, 'capsules')
        os.makedirs(self.capsule_dir, exist_ok=True)

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_bootstrap_creates_isolated_capsule(self):
        """RED: Bootstrap should create isolated capsule for new institution."""
        with patch('organizations.ORGS_FILE', self.orgs_file), \
             patch('organizations_store.db_path_for_file', return_value=os.path.join(self.temp_dir, 'orgs.db')), \
             patch('capsule.ORGS_FILE', self.orgs_file), \
             patch('capsule.CAPSULES_DIR', self.capsule_dir):

            from capsule import ensure_capsule, capsule_path

            org_id = create_org('Bootstrap Test Org', 'user_bootstrap_001', 'free')

            # Ensure capsule for this org
            ensure_capsule(org_id)

            # Capsule directory should exist
            cap_path = capsule_path(org_id, 'test.txt')
            cap_dir = os.path.dirname(cap_path)
            self.assertTrue(os.path.exists(cap_dir))

            # Should have expected structure
            self.assertTrue(os.path.isdir(cap_dir))

    def test_bootstrap_creates_isolated_treasury(self):
        """RED: Bootstrap should create isolated treasury for new institution."""
        with patch('organizations.ORGS_FILE', self.orgs_file), \
             patch('organizations_store.db_path_for_file', return_value=os.path.join(self.temp_dir, 'orgs.db')), \
             patch('capsule.ORGS_FILE', self.orgs_file), \
             patch('capsule.CAPSULES_DIR', self.capsule_dir), \
             patch('capsule.LEGACY_LEDGER_FILE', os.path.join(self.temp_dir, 'ledger.json')), \
             patch('capsule.LEGACY_REVENUE_FILE', os.path.join(self.temp_dir, 'revenue.json')), \
             patch('capsule.LEGACY_TRANSACTIONS_FILE', os.path.join(self.temp_dir, 'transactions.jsonl')):

            from capsule import ensure_capsule, ensure_treasury_aliases

            # Create legacy files for founding org compatibility
            with open(os.path.join(self.temp_dir, 'ledger.json'), 'w') as f:
                json.dump({}, f)
            with open(os.path.join(self.temp_dir, 'revenue.json'), 'w') as f:
                json.dump({}, f)
            open(os.path.join(self.temp_dir, 'transactions.jsonl'), 'a').close()

            org_id = create_org('Treasury Test Org', 'user_treasury_001', 'pro')
            ensure_capsule(org_id)

            # Create treasury aliases
            aliases = ensure_treasury_aliases(org_id)

            # Should have ledger, revenue, transactions paths
            self.assertIn('ledger', aliases)
            self.assertIn('revenue', aliases)
            self.assertIn('transactions', aliases)

            # Files should exist
            self.assertTrue(os.path.exists(aliases['ledger']))
            self.assertTrue(os.path.exists(aliases['revenue']))
            self.assertTrue(os.path.exists(aliases['transactions']))

            with open(aliases['ledger']) as f:
                ledger = json.load(f)
            self.assertEqual(ledger['schema'], 'meridian-kernel-economy-v1')
            self.assertEqual(ledger['treasury']['cash_usd'], 0.0)
            self.assertEqual(ledger['treasury']['reserve_floor_usd'], 50.0)


if __name__ == '__main__':
    unittest.main()
