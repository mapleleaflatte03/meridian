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

    def test_provision_institution_persists_institution_brain_policy(self):
        with patch('organizations.ORGS_FILE', self.orgs_file), \
             patch('organizations_store.db_path_for_file', return_value=os.path.join(self.temp_dir, 'orgs.db')), \
             patch('capsule.ORGS_FILE', self.orgs_file), \
             patch('capsule.CAPSULES_DIR', self.capsule_dir):
            result = provision_institution(
                name='Policy Boot Org',
                owner_id='user_policy_boot_001',
                plan='starter',
                brain_route_type='cli_session',
                brain_provider_profile='claude_local',
                brain_model='',
                brain_auth_profile='claude_local',
                brain_cli_bin='claude',
            )
            policy = result.get('institution_brain_policy') or {}
            self.assertEqual(policy.get('schema'), 'meridian.institution_brain_policy.v1')
            self.assertEqual(policy.get('institution_id'), result['org_id'])
            self.assertEqual(policy.get('primary_route_id'), 'route_primary')
            routes = policy.get('routes') or []
            self.assertEqual(len(routes), 1)
            self.assertEqual(routes[0].get('route_type'), 'cli_session')
            self.assertEqual(routes[0].get('provider_profile'), 'claude_local')

    def test_provision_institution_requires_explicit_route_configuration(self):
        with patch('organizations.ORGS_FILE', self.orgs_file), \
             patch('organizations_store.db_path_for_file', return_value=os.path.join(self.temp_dir, 'orgs.db')), \
             patch('capsule.ORGS_FILE', self.orgs_file), \
             patch('capsule.CAPSULES_DIR', self.capsule_dir):
            with self.assertRaises(ValueError) as exc:
                provision_institution(
                    name='Policy Missing Route',
                    owner_id='user_policy_missing_001',
                    plan='starter',
                    brain_route_type='',
                    brain_provider_profile='',
                    brain_model='',
                    brain_auth_profile='',
                    brain_cli_bin='',
                )
            self.assertEqual(str(exc.exception), 'brain_route_type is required')

    def test_provision_institution_requires_cli_bin_for_cli_route(self):
        with patch('organizations.ORGS_FILE', self.orgs_file), \
             patch('organizations_store.db_path_for_file', return_value=os.path.join(self.temp_dir, 'orgs.db')), \
             patch('capsule.ORGS_FILE', self.orgs_file), \
             patch('capsule.CAPSULES_DIR', self.capsule_dir):
            with self.assertRaises(ValueError) as exc:
                provision_institution(
                    name='Policy Missing CLI Bin',
                    owner_id='user_policy_missing_cli_001',
                    plan='starter',
                    brain_route_type='cli_session',
                    brain_provider_profile='codex_local',
                    brain_model='',
                    brain_auth_profile='codex_local',
                    brain_cli_bin='',
                )
            self.assertEqual(str(exc.exception), 'brain_cli_bin is required for cli_session')

    def test_provision_institution_requires_http_auth_for_http_route(self):
        with patch('organizations.ORGS_FILE', self.orgs_file), \
             patch('organizations_store.db_path_for_file', return_value=os.path.join(self.temp_dir, 'orgs.db')), \
             patch('capsule.ORGS_FILE', self.orgs_file), \
             patch('capsule.CAPSULES_DIR', self.capsule_dir):
            with self.assertRaises(ValueError) as exc:
                provision_institution(
                    name='Policy Missing HTTP Auth',
                    owner_id='user_policy_missing_http_auth_001',
                    plan='starter',
                    brain_route_type='http_json',
                    brain_provider_profile='http_provider',
                    brain_model='http-model',
                    brain_auth_profile='http_profile',
                    brain_cli_bin='',
                    brain_endpoint='https://router.example/v1/chat/completions',
                    brain_auth_env='',
                    brain_key_env_pool=[],
                )
            self.assertEqual(str(exc.exception), 'brain_auth_env or brain_key_env_pool is required for http_json')

    def test_policy_file_persists_and_reloads_without_env_injection(self):
        import institution_brain_policy
        with patch('organizations.ORGS_FILE', self.orgs_file), \
             patch('organizations_store.db_path_for_file', return_value=os.path.join(self.temp_dir, 'orgs.db')), \
             patch('capsule.ORGS_FILE', self.orgs_file), \
             patch('capsule.CAPSULES_DIR', self.capsule_dir):
            result = provision_institution(
                name='Policy Persist Org',
                owner_id='user_policy_persist_001',
                plan='starter',
                brain_route_type='cli_session',
                brain_provider_profile='codex_local',
                brain_model='codex-mini-latest',
                brain_auth_profile='codex_local',
                brain_cli_bin='codex',
                brain_cli_home='/tmp/codex-home',
            )
            org_id = result['org_id']
            policy_path = institution_brain_policy.policy_path(org_id)
            self.assertTrue(os.path.exists(policy_path))

            reloaded = institution_brain_policy.load_policy(org_id)
            active_route = institution_brain_policy.active_route(reloaded)
            self.assertEqual(reloaded.get('primary_route_id'), 'route_primary')
            self.assertEqual(active_route.get('provider_profile'), 'codex_local')
            self.assertEqual(active_route.get('route_type'), 'cli_session')
            self.assertEqual(active_route.get('cli_bin'), 'codex')
            self.assertEqual(active_route.get('model'), 'codex-mini-latest')
            self.assertEqual(reloaded.get('updated_by'), 'onboarding:user_policy_persist_001')

            with patch.dict(os.environ, {}, clear=True):
                status = institution_brain_policy.policy_status(org_id)
            self.assertTrue(status.get('configured'))
            self.assertEqual(status.get('source'), 'institution_policy')
            self.assertEqual(status.get('active_route', {}).get('provider_profile'), 'codex_local')
            self.assertEqual(status.get('active_route', {}).get('route_type'), 'cli_session')
            self.assertEqual(status.get('active_route', {}).get('model'), 'codex-mini-latest')
            self.assertEqual(status.get('fallback_chain'), [])
            self.assertEqual(status.get('active_route', {}).get('disable_reason', ''), '')
            self.assertEqual(status.get('active_route', {}).get('approved_by_authority'), True)
            self.assertEqual(status.get('active_route', {}).get('allowed_by_treasury'), True)
            self.assertEqual(status.get('active_route', {}).get('last_failover'), {})
            self.assertIn('codex_local', status.get('auth_profiles', {}))
            self.assertEqual(status.get('auth_profiles', {}).get('codex_local', {}).get('auth_mode'), 'session_home')
            self.assertTrue(status.get('failover_policy', {}).get('allow_route_chain_fallback'))
            self.assertEqual(status.get('failover_policy', {}).get('within_route_retry_limit'), 1)
            self.assertIn('billing', status.get('failover_policy', {}).get('error_classes', []))
            self.assertIn('auth', status.get('failover_policy', {}).get('error_classes', []))
            self.assertIn('rate_limit', status.get('failover_policy', {}).get('error_classes', []))
            self.assertIn('transport', status.get('failover_policy', {}).get('error_classes', []))
            self.assertIn('provider_unavailable', status.get('failover_policy', {}).get('error_classes', []))
            self.assertEqual(status.get('status'), 'unknown')
            self.assertEqual(status.get('reason'), '')
            self.assertEqual(status.get('active_route', {}).get('auth_profile_order'), ['codex_local'])
            self.assertEqual(status.get('active_route', {}).get('fallback_route_ids'), [])
            self.assertEqual(status.get('active_route', {}).get('budget_band'), 'standard')
            self.assertEqual(status.get('active_route', {}).get('disabled'), False)
            self.assertEqual(status.get('active_route', {}).get('cooldown_until'), '')
            self.assertEqual(status.get('active_route', {}).get('last_health'), 'unknown')
            self.assertEqual(status.get('active_route', {}).get('last_health_reason'), '')
            self.assertEqual(status.get('active_route', {}).get('route_id'), 'route_primary')
            self.assertEqual(status.get('active_route', {}).get('cli_home'), '/tmp/codex-home')
            self.assertEqual(status.get('active_route', {}).get('endpoint'), '')
            self.assertEqual(status.get('active_route', {}).get('auth_env'), '')
            self.assertEqual(status.get('active_route', {}).get('key_env_pool'), [])
            self.assertIn('billing', status.get('active_route', {}).get('failover_error_classes', []))
            self.assertIn('auth', status.get('active_route', {}).get('failover_error_classes', []))
            self.assertIn('rate_limit', status.get('active_route', {}).get('failover_error_classes', []))
            self.assertIn('transport', status.get('active_route', {}).get('failover_error_classes', []))
            self.assertIn('provider_unavailable', status.get('active_route', {}).get('failover_error_classes', []))
            self.assertEqual(status.get('active_route', {}).get('route_type'), 'cli_session')
            self.assertEqual(status.get('active_route', {}).get('provider_profile'), 'codex_local')
            self.assertEqual(status.get('active_route', {}).get('model'), 'codex-mini-latest')
            self.assertEqual(status.get('auth_profiles', {}).get('codex_local', {}).get('cli_bin'), 'codex')
            self.assertEqual(status.get('auth_profiles', {}).get('codex_local', {}).get('cli_home'), '/tmp/codex-home')
            self.assertEqual(status.get('auth_profiles', {}).get('codex_local', {}).get('auth_env'), '')
            self.assertEqual(status.get('auth_profiles', {}).get('codex_local', {}).get('key_env_pool'), [])
            self.assertEqual(status.get('auth_profiles', {}).get('codex_local', {}).get('profile_name'), 'codex_local')
            self.assertEqual(status.get('active_route', {}).get('approved_by_authority'), True)
            self.assertEqual(status.get('active_route', {}).get('allowed_by_treasury'), True)
            self.assertEqual(status.get('active_route', {}).get('disable_reason'), '')
            self.assertEqual(status.get('active_route', {}).get('last_failover'), {})
            self.assertEqual(status.get('active_route', {}).get('route_id'), 'route_primary')
            self.assertEqual(status.get('source'), 'institution_policy')
            self.assertTrue(status.get('configured'))
            self.assertEqual(status.get('active_route', {}).get('provider_profile'), 'codex_local')
            self.assertEqual(status.get('active_route', {}).get('route_type'), 'cli_session')
            self.assertEqual(status.get('active_route', {}).get('model'), 'codex-mini-latest')
            self.assertEqual(status.get('active_route', {}).get('auth_profile_order'), ['codex_local'])
            self.assertEqual(status.get('active_route', {}).get('disable_reason', ''), '')
            self.assertEqual(status.get('active_route', {}).get('last_failover'), {})
            self.assertEqual(status.get('active_route', {}).get('approved_by_authority'), True)
            self.assertEqual(status.get('active_route', {}).get('allowed_by_treasury'), True)
            self.assertEqual(status.get('fallback_chain'), [])
            self.assertIn('codex_local', status.get('auth_profiles', {}))
            self.assertEqual(status.get('status'), 'unknown')
            self.assertEqual(status.get('reason'), '')
            self.assertIn('error_classes', status.get('failover_policy', {}))
            self.assertTrue(status.get('failover_policy', {}).get('allow_route_chain_fallback'))
            self.assertEqual(status.get('failover_policy', {}).get('within_route_retry_limit'), 1)
            self.assertEqual(reloaded.get('primary_route_id'), 'route_primary')
            self.assertEqual(reloaded.get('schema'), 'meridian.institution_brain_policy.v1')
            self.assertEqual(reloaded.get('institution_id'), org_id)
            self.assertEqual(reloaded.get('updated_by'), 'onboarding:user_policy_persist_001')
            self.assertEqual(reloaded.get('routes', [])[0].get('provider_profile'), 'codex_local')
            self.assertEqual(reloaded.get('routes', [])[0].get('route_type'), 'cli_session')
            self.assertEqual(reloaded.get('routes', [])[0].get('cli_bin'), 'codex')
            self.assertEqual(reloaded.get('routes', [])[0].get('model'), 'codex-mini-latest')
            self.assertEqual(reloaded.get('routes', [])[0].get('auth_profile_order'), ['codex_local'])
            self.assertEqual(reloaded.get('routes', [])[0].get('approved_by_authority'), True)
            self.assertEqual(reloaded.get('routes', [])[0].get('allowed_by_treasury'), True)
            self.assertEqual(reloaded.get('routes', [])[0].get('disable_reason'), '')
            self.assertEqual(reloaded.get('routes', [])[0].get('last_failover'), {})
            self.assertEqual(reloaded.get('routes', [])[0].get('fallback_route_ids'), [])
            self.assertEqual(reloaded.get('routes', [])[0].get('budget_band'), 'standard')
            self.assertEqual(reloaded.get('routes', [])[0].get('disabled'), False)
            self.assertEqual(reloaded.get('routes', [])[0].get('cooldown_until'), '')
            self.assertEqual(reloaded.get('routes', [])[0].get('last_health'), 'unknown')
            self.assertEqual(reloaded.get('routes', [])[0].get('last_health_reason'), '')
            self.assertEqual(reloaded.get('routes', [])[0].get('route_id'), 'route_primary')
            self.assertEqual(reloaded.get('routes', [])[0].get('cli_home'), '/tmp/codex-home')
            self.assertEqual(reloaded.get('routes', [])[0].get('endpoint'), '')
            self.assertEqual(reloaded.get('routes', [])[0].get('auth_env'), '')
            self.assertEqual(reloaded.get('routes', [])[0].get('key_env_pool'), [])
            self.assertIn('billing', reloaded.get('routes', [])[0].get('failover_error_classes', []))
            self.assertIn('auth', reloaded.get('routes', [])[0].get('failover_error_classes', []))
            self.assertIn('rate_limit', reloaded.get('routes', [])[0].get('failover_error_classes', []))
            self.assertIn('transport', reloaded.get('routes', [])[0].get('failover_error_classes', []))
            self.assertIn('provider_unavailable', reloaded.get('routes', [])[0].get('failover_error_classes', []))
            self.assertIn('codex_local', reloaded.get('auth_profiles', {}))
            self.assertEqual(reloaded.get('auth_profiles', {}).get('codex_local', {}).get('auth_mode'), 'session_home')
            self.assertEqual(reloaded.get('auth_profiles', {}).get('codex_local', {}).get('cli_bin'), 'codex')
            self.assertEqual(reloaded.get('auth_profiles', {}).get('codex_local', {}).get('cli_home'), '/tmp/codex-home')
            self.assertEqual(reloaded.get('auth_profiles', {}).get('codex_local', {}).get('auth_env'), '')
            self.assertEqual(reloaded.get('auth_profiles', {}).get('codex_local', {}).get('key_env_pool'), [])
            self.assertEqual(reloaded.get('auth_profiles', {}).get('codex_local', {}).get('profile_name'), 'codex_local')
            self.assertTrue(reloaded.get('failover_policy', {}).get('allow_route_chain_fallback'))
            self.assertEqual(reloaded.get('failover_policy', {}).get('within_route_retry_limit'), 1)
            self.assertIn('billing', reloaded.get('failover_policy', {}).get('error_classes', []))
            self.assertIn('auth', reloaded.get('failover_policy', {}).get('error_classes', []))
            self.assertIn('rate_limit', reloaded.get('failover_policy', {}).get('error_classes', []))
            self.assertIn('transport', reloaded.get('failover_policy', {}).get('error_classes', []))
            self.assertIn('provider_unavailable', reloaded.get('failover_policy', {}).get('error_classes', []))
            self.assertTrue(os.path.exists(policy_path))
            with open(policy_path, 'r', encoding='utf-8') as fh:
                raw_policy = json.load(fh)
            self.assertEqual(raw_policy.get('primary_route_id'), 'route_primary')
            self.assertEqual(raw_policy.get('routes', [])[0].get('provider_profile'), 'codex_local')
            self.assertEqual(raw_policy.get('routes', [])[0].get('route_type'), 'cli_session')
            self.assertEqual(raw_policy.get('routes', [])[0].get('cli_bin'), 'codex')
            self.assertEqual(raw_policy.get('routes', [])[0].get('model'), 'codex-mini-latest')
            self.assertEqual(raw_policy.get('routes', [])[0].get('auth_profile_order'), ['codex_local'])
            self.assertEqual(raw_policy.get('routes', [])[0].get('approved_by_authority'), True)
            self.assertEqual(raw_policy.get('routes', [])[0].get('allowed_by_treasury'), True)
            self.assertEqual(raw_policy.get('routes', [])[0].get('disable_reason'), '')
            self.assertEqual(raw_policy.get('routes', [])[0].get('last_failover'), {})
            self.assertEqual(raw_policy.get('routes', [])[0].get('fallback_route_ids'), [])
            self.assertEqual(raw_policy.get('routes', [])[0].get('budget_band'), 'standard')
            self.assertEqual(raw_policy.get('routes', [])[0].get('disabled'), False)
            self.assertEqual(raw_policy.get('routes', [])[0].get('cooldown_until'), '')
            self.assertEqual(raw_policy.get('routes', [])[0].get('last_health'), 'unknown')
            self.assertEqual(raw_policy.get('routes', [])[0].get('last_health_reason'), '')
            self.assertEqual(raw_policy.get('routes', [])[0].get('route_id'), 'route_primary')
            self.assertEqual(raw_policy.get('routes', [])[0].get('cli_home'), '/tmp/codex-home')
            self.assertEqual(raw_policy.get('routes', [])[0].get('endpoint'), '')
            self.assertEqual(raw_policy.get('routes', [])[0].get('auth_env'), '')
            self.assertEqual(raw_policy.get('routes', [])[0].get('key_env_pool'), [])
            self.assertIn('billing', raw_policy.get('routes', [])[0].get('failover_error_classes', []))
            self.assertIn('auth', raw_policy.get('routes', [])[0].get('failover_error_classes', []))
            self.assertIn('rate_limit', raw_policy.get('routes', [])[0].get('failover_error_classes', []))
            self.assertIn('transport', raw_policy.get('routes', [])[0].get('failover_error_classes', []))
            self.assertIn('provider_unavailable', raw_policy.get('routes', [])[0].get('failover_error_classes', []))


if __name__ == '__main__':
    unittest.main()
