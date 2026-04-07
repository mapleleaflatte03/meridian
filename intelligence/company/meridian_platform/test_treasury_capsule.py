#!/usr/bin/env python3
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

COMPANY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, COMPANY_DIR)

import accounting
import agent_registry
import authority
import capsule
import court
import payment_monitor
import subscriptions
import treasury

REVENUE_PY = os.path.join(os.path.dirname(COMPANY_DIR), 'economy', 'revenue.py')
_revenue_spec = importlib.util.spec_from_file_location('treasury_capsule_test_revenue', REVENUE_PY)
revenue = importlib.util.module_from_spec(_revenue_spec)
_revenue_spec.loader.exec_module(revenue)


class TreasuryCapsuleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix='treasury-capsule-')
        self._capsules_dir = os.path.join(self._tmp, 'capsules')
        self._legacy_ledger = os.path.join(self._tmp, 'ledger.json')
        self._legacy_revenue = os.path.join(self._tmp, 'revenue.json')
        self._legacy_transactions = os.path.join(self._tmp, 'transactions.jsonl')
        self._legacy_subscriptions = os.path.join(self._tmp, 'subscriptions.json')
        self._legacy_subscriptions_backup = os.path.join(self._tmp, 'subscriptions.json.bak')
        self._legacy_subscriptions_lock = os.path.join(self._tmp, '.subscriptions.lock')
        self._legacy_owner_ledger = os.path.join(self._tmp, 'owner_ledger.json')
        self._legacy_payment_monitor_state = os.path.join(self._tmp, 'payment_monitor_state.json')
        self._legacy_payment_events = os.path.join(self._tmp, 'payment_events.log')
        self._legacy_payment_integrity_lock = os.path.join(self._tmp, '.payment_integrity.lock')
        self.org_id = 'org_live'

        with open(self._legacy_ledger, 'w') as f:
            json.dump({
                'epoch': {'number': 8, 'auth_decay_per_epoch': 5},
                'agents': {
                    'atlas': {
                        'name': 'Atlas',
                        'status': 'active',
                        'reputation_units': 91,
                        'authority_units': 42,
                        'last_scored_at': '2026-03-21T00:00:00Z',
                        'probation': False,
                        'zero_authority': False,
                        'lead_ban': False,
                        'remediation_only': False,
                    },
                    'sentinel': {
                        'name': 'Sentinel',
                        'status': 'active',
                        'reputation_units': 50,
                        'authority_units': 25,
                        'last_scored_at': '2026-03-21T00:00:00Z',
                        'probation': False,
                        'zero_authority': False,
                        'lead_ban': False,
                        'remediation_only': False,
                    },
                },
                'treasury': {
                    'cash_usd': 7.5,
                    'reserve_floor_usd': 5.0,
                    'total_revenue_usd': 3.0,
                    'support_received_usd': 1.25,
                    'owner_capital_contributed_usd': 2.0,
                    'owner_draws_usd': 0.0,
                }
            }, f, indent=2)
        with open(self._legacy_revenue, 'w') as f:
            json.dump({
                'clients': {'cli_a': {'id': 'cli_a', 'name': 'Client A'}},
                'orders': {
                    'ord_a': {
                        'id': 'ord_a',
                        'client': 'cli_a',
                        'status': 'paid',
                        'product': 'brief',
                    }
                },
                'receivables_usd': 0.0,
            }, f, indent=2)
        with open(self._legacy_transactions, 'w') as f:
            f.write('')
        subscriptions_payload = {
            'subscribers': {},
            'delivery_log': [],
            'updatedAt': '2026-03-21T00:00:00Z',
            '_meta': {'service_scope': 'institution_owned_subscription_service'},
        }
        with open(self._legacy_subscriptions, 'w') as f:
            json.dump(subscriptions_payload, f, indent=2)
        with open(self._legacy_subscriptions_backup, 'w') as f:
            json.dump(subscriptions_payload, f, indent=2)
        with open(self._legacy_subscriptions_lock, 'w') as f:
            f.write('')
        with open(self._legacy_owner_ledger, 'w') as f:
            json.dump({}, f)
        with open(self._legacy_payment_monitor_state, 'w') as f:
            json.dump({'last_block': 7}, f, indent=2)
        with open(self._legacy_payment_events, 'w') as f:
            f.write('2026-03-21T00:00:00Z boot\n')
        with open(self._legacy_payment_integrity_lock, 'w') as f:
            f.write('')

        self._orig_capsules_dir = capsule.CAPSULES_DIR
        self._orig_legacy_ledger = capsule.LEGACY_LEDGER_FILE
        self._orig_legacy_revenue = capsule.LEGACY_REVENUE_FILE
        self._orig_legacy_transactions = capsule.LEGACY_TRANSACTIONS_FILE
        self._orig_legacy_subscriptions = capsule.LEGACY_SUBSCRIPTIONS_FILE
        self._orig_legacy_subscriptions_backup = capsule.LEGACY_SUBSCRIPTIONS_BACKUP_FILE
        self._orig_legacy_subscriptions_lock = capsule.LEGACY_SUBSCRIPTIONS_LOCK_FILE
        self._orig_legacy_owner_ledger = capsule.LEGACY_OWNER_LEDGER_FILE
        self._orig_legacy_payment_monitor_state = capsule.LEGACY_PAYMENT_MONITOR_STATE_FILE
        self._orig_legacy_payment_events = capsule.LEGACY_PAYMENT_EVENTS_LOG_FILE
        self._orig_legacy_payment_integrity_lock = capsule.LEGACY_PAYMENT_INTEGRITY_LOCK_FILE
        self._orig_default_org = capsule.default_org_id

        capsule.CAPSULES_DIR = self._capsules_dir
        capsule.LEGACY_LEDGER_FILE = self._legacy_ledger
        capsule.LEGACY_REVENUE_FILE = self._legacy_revenue
        capsule.LEGACY_TRANSACTIONS_FILE = self._legacy_transactions
        capsule.LEGACY_SUBSCRIPTIONS_FILE = self._legacy_subscriptions
        capsule.LEGACY_SUBSCRIPTIONS_BACKUP_FILE = self._legacy_subscriptions_backup
        capsule.LEGACY_SUBSCRIPTIONS_LOCK_FILE = self._legacy_subscriptions_lock
        capsule.LEGACY_OWNER_LEDGER_FILE = self._legacy_owner_ledger
        capsule.LEGACY_PAYMENT_MONITOR_STATE_FILE = self._legacy_payment_monitor_state
        capsule.LEGACY_PAYMENT_EVENTS_LOG_FILE = self._legacy_payment_events
        capsule.LEGACY_PAYMENT_INTEGRITY_LOCK_FILE = self._legacy_payment_integrity_lock
        capsule.default_org_id = lambda: self.org_id

        self._orig_treasury_default = treasury._default_org_id
        self._orig_treasury_ensure = treasury.ensure_treasury_aliases
        self._orig_treasury_ledger_path = treasury.capsule_ledger_path
        self._orig_treasury_revenue_path = treasury.capsule_revenue_path
        self._orig_accounting_ensure = accounting.ensure_treasury_aliases
        self._orig_accounting_ledger_path = accounting.capsule_ledger_path
        self._orig_accounting_tx_path = accounting.capsule_transactions_path
        self._orig_accounting_owner = accounting.OWNER_LEDGER
        self._orig_payment_monitor_state = payment_monitor.STATE_FILE
        self._orig_payment_monitor_event = payment_monitor.EVENT_LOG
        self._orig_revenue_payment_lock = revenue.PAYMENT_LOCK
        self._orig_registry_ensure = agent_registry.ensure_treasury_aliases
        self._orig_registry_ledger_path = agent_registry.capsule_ledger_path
        self._orig_registry_file = agent_registry.REGISTRY_FILE
        self._orig_authority_default = authority._default_org_id
        self._orig_authority_ensure = authority.ensure_treasury_aliases
        self._orig_authority_ledger_path = authority.capsule_ledger_path
        self._orig_court_default = court._default_org_id
        self._orig_court_ensure = court.ensure_treasury_aliases
        self._orig_court_ledger_path = court.capsule_ledger_path

        treasury._default_org_id = lambda: self.org_id
        treasury.ensure_treasury_aliases = capsule.ensure_treasury_aliases
        treasury.capsule_ledger_path = capsule.ledger_path
        treasury.capsule_revenue_path = capsule.revenue_path

        accounting.ensure_treasury_aliases = capsule.ensure_treasury_aliases
        accounting.capsule_ledger_path = capsule.ledger_path
        accounting.capsule_transactions_path = capsule.transactions_path
        accounting.OWNER_LEDGER = accounting.DEFAULT_OWNER_LEDGER

        payment_monitor.STATE_FILE = payment_monitor.DEFAULT_STATE_FILE
        payment_monitor.EVENT_LOG = payment_monitor.DEFAULT_EVENT_LOG
        revenue.PAYMENT_LOCK = revenue.DEFAULT_PAYMENT_LOCK

        agent_registry.ensure_treasury_aliases = capsule.ensure_treasury_aliases
        agent_registry.capsule_ledger_path = capsule.ledger_path
        agent_registry.REGISTRY_FILE = os.path.join(self._tmp, 'agent_registry.json')
        with open(agent_registry.REGISTRY_FILE, 'w') as f:
            json.dump({
                'agents': {
                    'agent_atlas_123456': {
                        'id': 'agent_atlas_123456',
                        'org_id': self.org_id,
                        'name': 'Atlas',
                        'role': 'analyst',
                        'purpose': 'Research',
                        'model_policy': {},
                        'scopes': ['research'],
                        'budget': {'max_per_run_usd': 1.0, 'max_per_day_usd': 5.0, 'max_per_month_usd': 100.0},
                        'approval_required': False,
                        'rollout_state': 'active',
                        'sla': {},
                        'reputation_units': 1,
                        'authority_units': 1,
                        'sponsor_id': None,
                        'risk_state': 'nominal',
                        'lifecycle_state': 'active',
                        'economy_key': 'atlas',
                        'incident_count': 0,
                        'escalation_path': [],
                        'status': 'active',
                        'created_at': '2026-03-21T00:00:00Z',
                        'last_active_at': '2026-03-21T00:00:00Z',
                    }
                },
                'updatedAt': '2026-03-21T00:00:00Z',
            }, f, indent=2)

        authority._default_org_id = lambda: self.org_id
        authority.ensure_treasury_aliases = capsule.ensure_treasury_aliases
        authority.capsule_ledger_path = capsule.ledger_path

        court._default_org_id = lambda: self.org_id
        court.ensure_treasury_aliases = capsule.ensure_treasury_aliases
        court.capsule_ledger_path = capsule.ledger_path

    def tearDown(self):
        capsule.CAPSULES_DIR = self._orig_capsules_dir
        capsule.LEGACY_LEDGER_FILE = self._orig_legacy_ledger
        capsule.LEGACY_REVENUE_FILE = self._orig_legacy_revenue
        capsule.LEGACY_TRANSACTIONS_FILE = self._orig_legacy_transactions
        capsule.LEGACY_SUBSCRIPTIONS_FILE = self._orig_legacy_subscriptions
        capsule.LEGACY_SUBSCRIPTIONS_BACKUP_FILE = self._orig_legacy_subscriptions_backup
        capsule.LEGACY_SUBSCRIPTIONS_LOCK_FILE = self._orig_legacy_subscriptions_lock
        capsule.LEGACY_OWNER_LEDGER_FILE = self._orig_legacy_owner_ledger
        capsule.LEGACY_PAYMENT_MONITOR_STATE_FILE = self._orig_legacy_payment_monitor_state
        capsule.LEGACY_PAYMENT_EVENTS_LOG_FILE = self._orig_legacy_payment_events
        capsule.LEGACY_PAYMENT_INTEGRITY_LOCK_FILE = self._orig_legacy_payment_integrity_lock
        capsule.default_org_id = self._orig_default_org

        treasury._default_org_id = self._orig_treasury_default
        treasury.ensure_treasury_aliases = self._orig_treasury_ensure
        treasury.capsule_ledger_path = self._orig_treasury_ledger_path
        treasury.capsule_revenue_path = self._orig_treasury_revenue_path

        accounting.ensure_treasury_aliases = self._orig_accounting_ensure
        accounting.capsule_ledger_path = self._orig_accounting_ledger_path
        accounting.capsule_transactions_path = self._orig_accounting_tx_path
        accounting.OWNER_LEDGER = self._orig_accounting_owner

        payment_monitor.STATE_FILE = self._orig_payment_monitor_state
        payment_monitor.EVENT_LOG = self._orig_payment_monitor_event
        revenue.PAYMENT_LOCK = self._orig_revenue_payment_lock

        agent_registry.ensure_treasury_aliases = self._orig_registry_ensure
        agent_registry.capsule_ledger_path = self._orig_registry_ledger_path
        agent_registry.REGISTRY_FILE = self._orig_registry_file

        authority._default_org_id = self._orig_authority_default
        authority.ensure_treasury_aliases = self._orig_authority_ensure
        authority.capsule_ledger_path = self._orig_authority_ledger_path

        court._default_org_id = self._orig_court_default
        court.ensure_treasury_aliases = self._orig_court_ensure
        court.capsule_ledger_path = self._orig_court_ledger_path

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_aliases_are_symlinks_to_legacy_state(self):
        aliases = capsule.ensure_treasury_aliases(self.org_id)
        self.assertTrue(os.path.islink(aliases['ledger']))
        self.assertTrue(os.path.islink(aliases['revenue']))
        self.assertTrue(os.path.islink(aliases['transactions']))
        self.assertEqual(os.path.realpath(aliases['ledger']), self._legacy_ledger)
        self.assertEqual(os.path.realpath(aliases['revenue']), self._legacy_revenue)
        self.assertEqual(os.path.realpath(aliases['transactions']), self._legacy_transactions)
        sub_aliases = capsule.ensure_subscription_aliases(self.org_id)
        self.assertFalse(os.path.islink(sub_aliases['subscriptions']))
        self.assertFalse(os.path.islink(sub_aliases['subscriptions_backup']))
        self.assertFalse(os.path.islink(sub_aliases['subscriptions_lock']))
        self.assertTrue(os.path.islink(self._legacy_subscriptions))
        self.assertTrue(os.path.islink(self._legacy_subscriptions_backup))
        self.assertTrue(os.path.islink(self._legacy_subscriptions_lock))
        self.assertEqual(os.path.realpath(self._legacy_subscriptions), sub_aliases['subscriptions'])
        self.assertEqual(
            os.path.realpath(self._legacy_subscriptions_backup),
            sub_aliases['subscriptions_backup'],
        )
        self.assertEqual(
            os.path.realpath(self._legacy_subscriptions_lock),
            sub_aliases['subscriptions_lock'],
        )
        self.assertEqual(sub_aliases['canonical_source'], 'capsule_file')
        self.assertEqual(
            sub_aliases['canonical_service_module'],
            'company.meridian_platform.subscription_service',
        )
        self.assertEqual(sub_aliases['compatibility_module'], 'company.subscriptions')
        self.assertEqual(sub_aliases['compatibility_mode'], 'compatibility_alias')
        accounting_aliases = capsule.ensure_accounting_aliases(self.org_id)
        self.assertFalse(os.path.islink(accounting_aliases['owner_ledger']))
        self.assertTrue(os.path.islink(self._legacy_owner_ledger))
        self.assertEqual(
            os.path.realpath(self._legacy_owner_ledger),
            accounting_aliases['owner_ledger'],
        )
        self.assertEqual(accounting_aliases['canonical_source'], 'capsule_file')
        self.assertEqual(
            accounting_aliases['canonical_service_module'],
            'company.meridian_platform.accounting_service',
        )
        self.assertEqual(accounting_aliases['compatibility_module'], 'company.accounting')
        self.assertEqual(accounting_aliases['compatibility_mode'], 'compatibility_alias')
        monitor_aliases = capsule.ensure_payment_monitor_aliases(self.org_id)
        self.assertTrue(os.path.islink(monitor_aliases['payment_monitor_state']))
        self.assertTrue(os.path.islink(monitor_aliases['payment_events_log']))
        self.assertEqual(
            os.path.realpath(monitor_aliases['payment_monitor_state']),
            self._legacy_payment_monitor_state,
        )
        self.assertEqual(
            os.path.realpath(monitor_aliases['payment_events_log']),
            self._legacy_payment_events,
        )
        revenue_aliases = capsule.ensure_revenue_integrity_aliases(self.org_id)
        self.assertTrue(os.path.islink(revenue_aliases['payment_integrity_lock']))
        self.assertEqual(
            os.path.realpath(revenue_aliases['payment_integrity_lock']),
            self._legacy_payment_integrity_lock,
        )

    def test_matching_regular_file_is_replaced_with_symlink(self):
        org_dir = os.path.join(self._capsules_dir, self.org_id)
        os.makedirs(org_dir, exist_ok=True)
        ledger_alias = os.path.join(org_dir, 'ledger.json')
        with open(self._legacy_ledger) as src, open(ledger_alias, 'w') as dst:
            dst.write(src.read())
        capsule.ensure_treasury_aliases(self.org_id)
        self.assertTrue(os.path.islink(ledger_alias))
        self.assertEqual(os.path.realpath(ledger_alias), self._legacy_ledger)

    def test_revenue_collision_is_merged_and_relinked(self):
        org_dir = os.path.join(self._capsules_dir, self.org_id)
        os.makedirs(org_dir, exist_ok=True)
        revenue_alias = os.path.join(org_dir, 'revenue.json')
        with open(revenue_alias, 'w') as f:
            json.dump({
                'clients': {
                    'cli_b': {'id': 'cli_b', 'name': 'Client B'},
                },
                'orders': {},
                'receivables_usd': 0.0,
                'updatedAt': '2026-03-22T00:00:00Z',
            }, f, indent=2)
        capsule.ensure_treasury_aliases(self.org_id)
        self.assertTrue(os.path.islink(revenue_alias))
        self.assertEqual(os.path.realpath(revenue_alias), self._legacy_revenue)
        with open(self._legacy_revenue) as f:
            merged = json.load(f)
        self.assertIn('cli_a', merged['clients'])
        self.assertIn('cli_b', merged['clients'])
        self.assertEqual(merged['updatedAt'], '2026-03-22T00:00:00Z')

    def test_treasury_reads_through_capsule_aliases(self):
        capsule.ensure_treasury_aliases(self.org_id)
        self.assertEqual(treasury.get_balance(self.org_id), 7.5)
        snap = treasury.treasury_snapshot(self.org_id)
        self.assertEqual(snap['support_received_usd'], 1.25)
        self.assertEqual(snap['owner_capital_usd'], 2.0)
        self.assertEqual(snap['clients'], 1)
        self.assertEqual(snap['paid_orders'], 1)

    def test_treasury_snapshot_is_read_only(self):
        capsule.ensure_treasury_aliases(self.org_id)
        with mock.patch.object(treasury, "ensure_treasury_aliases", side_effect=AssertionError("snapshot should not sync aliases")), \
             mock.patch.object(treasury, "load_treasury_accounts", side_effect=AssertionError("snapshot should not sync accounts")), \
             mock.patch.object(treasury, "load_funding_sources", side_effect=AssertionError("snapshot should not sync funding sources")), \
             mock.patch.object(treasury, "_save_account_store", side_effect=AssertionError("snapshot should not save accounts")), \
             mock.patch.object(treasury, "_save_funding_source_store", side_effect=AssertionError("snapshot should not save funding sources")):
            snap = treasury.treasury_snapshot(self.org_id)

        self.assertEqual(snap["balance_usd"], 7.5)
        self.assertIn("protocol", snap)
        self.assertIn("settlement_adapter_summary", snap)

    def test_accounting_writes_through_capsule_alias(self):
        capsule.ensure_treasury_aliases(self.org_id)
        result = accounting.contribute_capital(1.0, 'test deposit', actor='owner', org_id=self.org_id)
        self.assertEqual(result['cash_after_usd'], 8.5)
        owner_alias = capsule.owner_ledger_path(self.org_id)
        self.assertFalse(os.path.islink(owner_alias))
        self.assertTrue(os.path.islink(self._legacy_owner_ledger))
        self.assertEqual(os.path.realpath(self._legacy_owner_ledger), owner_alias)
        with open(owner_alias) as f:
            owner = json.load(f)
        self.assertEqual(owner['capital_contributed_usd'], 1.0)
        self.assertEqual(owner['_meta']['service_scope'], 'institution_owned_service')
        self.assertEqual(owner['_meta']['bound_org_id'], self.org_id)
        with open(self._legacy_ledger) as f:
            ledger = json.load(f)
        self.assertEqual(ledger['treasury']['cash_usd'], 8.5)
        self.assertEqual(ledger['treasury']['owner_capital_contributed_usd'], 3.0)
        with open(self._legacy_transactions) as f:
            entries = [json.loads(line) for line in f if line.strip()]
        self.assertTrue(any(entry.get('deposit_type') == 'owner_capital' for entry in entries))
        with open(capsule.transactions_path(self.org_id)) as f:
            capsule_entries = [json.loads(line) for line in f if line.strip()]
        self.assertTrue(any(entry.get('deposit_type') == 'owner_capital' for entry in capsule_entries))
        self.assertEqual(accounting.load_owner(self.org_id)['_meta']['bound_org_id'], self.org_id)
        self.assertEqual(accounting.load_ledger(self.org_id)['treasury']['cash_usd'], 8.5)

    def test_accounting_rejects_non_founding_org_binding(self):
        capsule.ensure_treasury_aliases(self.org_id)
        with self.assertRaisesRegex(ValueError, 'Live capsule only supports founding org'):
            accounting.contribute_capital(1.0, 'wrong org', actor='owner', org_id='org_other')

    def test_treasury_protocol_sync_tracks_owner_capital(self):
        capsule.ensure_treasury_aliases(self.org_id)
        result = treasury.contribute_owner_capital(
            3.0,
            note='owner sync test',
            by='owner',
            org_id=self.org_id,
        )

        self.assertTrue(result['funding_source_id'].startswith('src_'))

        accounts = treasury.load_treasury_accounts(self.org_id)
        self.assertAlmostEqual(accounts['accounts']['operating_cash']['balance_usd'], 10.5, places=2)
        self.assertAlmostEqual(accounts['accounts']['owner_capital']['balance_usd'], 5.0, places=2)
        self.assertAlmostEqual(accounts['accounts']['reserve_floor']['balance_usd'], 5.0, places=2)
        self.assertEqual(accounts['accounts']['pending_payouts']['balance_usd'], 0.0)
        self.assertEqual(accounts['accounts']['executed_payouts']['balance_usd'], 0.0)

        funding = treasury.load_funding_sources(self.org_id)
        self.assertEqual(len(funding['sources']), 2)
        explicit = [item for item in funding['sources'].values() if item.get('source_id') == result['funding_source_id']][0]
        derived = funding['sources']['src_derived_owner_capital']
        self.assertEqual(explicit['type'], 'owner_capital')
        self.assertEqual(explicit['currency'], 'USD')
        self.assertEqual(explicit['actor_id'], 'owner')
        self.assertAlmostEqual(explicit['amount_usd'], 3.0, places=2)
        self.assertTrue(derived['metadata']['derived_from_ledger'])
        self.assertAlmostEqual(derived['amount_usd'], 2.0, places=2)

    def test_payment_monitor_uses_capsule_aliases(self):
        capsule.ensure_treasury_aliases(self.org_id)
        state = payment_monitor.load_state()
        self.assertEqual(state['last_block'], 7)
        payment_monitor.save_state({'last_block': 12})
        with open(self._legacy_payment_monitor_state) as f:
            persisted = json.load(f)
        self.assertEqual(persisted['last_block'], 12)
        payment_monitor.log_event('probe')
        with open(self._legacy_payment_events) as f:
            content = f.read()
        self.assertIn('probe', content)

    def test_revenue_payment_lock_uses_capsule_alias(self):
        with revenue.payment_lock():
            revenue.append_tx({'type': 'lock_probe'})
        lock_path = capsule.payment_integrity_lock_path(self.org_id)
        self.assertTrue(os.path.islink(lock_path))
        self.assertEqual(os.path.realpath(lock_path), self._legacy_payment_integrity_lock)

    def test_agent_registry_sync_reads_capsule_alias(self):
        capsule.ensure_treasury_aliases(self.org_id)
        agent_registry.sync_from_economy()
        with open(agent_registry.REGISTRY_FILE) as f:
            registry = json.load(f)
        atlas = registry['agents']['agent_atlas_123456']
        self.assertEqual(atlas['reputation_units'], 91)
        self.assertEqual(atlas['authority_units'], 42)

    def test_agent_registry_lookup_surfaces_runtime_binding(self):
        agent = agent_registry.get_agent('agent_atlas_123456')
        self.assertIsNotNone(agent)
        self.assertEqual(agent['runtime_binding']['runtime_id'], 'loom_native')
        self.assertEqual(agent['runtime_binding']['runtime_label'], 'Meridian Loom Runtime')
        self.assertEqual(agent['runtime_binding']['bound_org_id'], self.org_id)
        self.assertEqual(agent['runtime_binding']['context_source'], 'agent_registry')
        self.assertEqual(agent['runtime_binding']['boundary_name'], 'workspace')
        self.assertEqual(agent['runtime_binding']['identity_model'], 'session')
        self.assertTrue(agent['runtime_binding']['runtime_registered'])
        self.assertEqual(agent['runtime_binding']['registration_status'], 'registered')

        agents = agent_registry.list_agents(self.org_id)
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0]['runtime_binding']['runtime_id'], 'loom_native')
        self.assertEqual(agents[0]['runtime_binding']['bound_org_id'], self.org_id)

    def test_authority_and_court_use_capsule_ledger_alias(self):
        capsule.ensure_treasury_aliases(self.org_id)
        lead_id, lead_auth = authority.get_sprint_lead(self.org_id)
        self.assertEqual(lead_id, 'atlas')
        self.assertEqual(lead_auth, 42)

        violation_id = court.file_violation(
            agent_id='atlas',
            org_id=self.org_id,
            violation_type='false_confidence',
            severity=5,
            evidence='test evidence',
        )
        self.assertTrue(violation_id.startswith('vio_'))
        with open(self._legacy_ledger) as f:
            ledger = json.load(f)
        self.assertTrue(ledger['agents']['atlas']['zero_authority'])

    def test_live_payout_proposal_lifecycle_executes_against_founding_alias(self):
        capsule.ensure_treasury_aliases(self.org_id)
        org_dir = os.path.join(self._capsules_dir, self.org_id)
        os.makedirs(org_dir, exist_ok=True)

        with open(os.path.join(org_dir, 'wallets.json'), 'w') as f:
            json.dump({
                'wallets': {
                    'wallet_live': {
                        'id': 'wallet_live',
                        'verification_level': 3,
                        'verification_label': 'self_custody_verified',
                        'payout_eligible': True,
                        'status': 'active',
                    }
                },
                'verification_levels': {},
            }, f, indent=2)
        with open(os.path.join(org_dir, 'contributors.json'), 'w') as f:
            json.dump({
                'contributors': {
                    'contrib_live': {
                        'id': 'contrib_live',
                        'name': 'Contributor Live',
                        'payout_wallet_id': 'wallet_live',
                    }
                },
                'contribution_types': ['code'],
                'registration_requirements': {},
            }, f, indent=2)

        proposal = treasury.create_payout_proposal(
            'contrib_live',
            1.5,
            'code',
            proposed_by='user:proposer',
            org_id=self.org_id,
            evidence={'description': 'live capsule proof'},
        )
        proposal = treasury.submit_payout_proposal(
            proposal['proposal_id'],
            'user:proposer',
            org_id=self.org_id,
        )
        proposal = treasury.review_payout_proposal(
            proposal['proposal_id'],
            'user:reviewer',
            org_id=self.org_id,
        )
        proposal = treasury.approve_payout_proposal(
            proposal['proposal_id'],
            'user:owner',
            org_id=self.org_id,
        )
        proposal = treasury.open_payout_dispute_window(
            proposal['proposal_id'],
            'user:owner',
            org_id=self.org_id,
            dispute_window_hours=0,
        )
        with mock.patch.object(treasury, '_payout_phase_gate', return_value=(True, 'phase 5 test override')):
            proposal = treasury.execute_payout_proposal(
                proposal['proposal_id'],
                'user:owner',
                org_id=self.org_id,
                warrant_id='war_live_exec',
                tx_hash='tx_live_demo',
            )

        self.assertEqual(proposal['status'], 'executed')
        self.assertEqual(proposal['warrant_id'], 'war_live_exec')
        self.assertEqual(proposal['tx_hash'], 'tx_live_demo')
        self.assertTrue(proposal['execution_refs']['tx_ref'].startswith('ptx_'))
        self.assertEqual(proposal['execution_refs']['proof_type'], 'ledger_transaction')
        self.assertEqual(proposal['execution_refs']['verification_state'], 'host_ledger_final')
        self.assertEqual(proposal['execution_refs']['finality_state'], 'host_local_final')
        self.assertEqual(
            proposal['execution_refs']['settlement_adapter_contract_snapshot']['adapter_id'],
            'internal_ledger',
        )
        self.assertEqual(
            proposal['execution_refs']['settlement_adapter_contract_digest'],
            treasury.settlement_adapter_contract_digest(
                proposal['execution_refs']['settlement_adapter_contract_snapshot']
            ),
        )
        self.assertEqual(proposal['execution_refs']['proof']['mode'], 'institution_transactions_journal')

        with open(self._legacy_ledger) as f:
            ledger = json.load(f)
        self.assertAlmostEqual(ledger['treasury']['cash_usd'], 6.0, places=2)
        self.assertAlmostEqual(ledger['treasury']['expenses_recorded_usd'], 1.5, places=2)

        with open(self._legacy_transactions) as f:
            entries = [json.loads(line) for line in f if line.strip()]
        self.assertEqual(entries[-1]['type'], 'payout_execution')
        self.assertEqual(entries[-1]['proposal_id'], proposal['proposal_id'])
        self.assertEqual(entries[-1]['warrant_id'], 'war_live_exec')
        self.assertEqual(entries[-1]['verification_state'], 'host_ledger_final')
        self.assertEqual(
            entries[-1]['settlement_adapter_contract_snapshot']['adapter_id'],
            'internal_ledger',
        )
        self.assertEqual(
            entries[-1]['settlement_adapter_contract_digest'],
            proposal['execution_refs']['settlement_adapter_contract_digest'],
        )

        accounts = treasury.load_treasury_accounts(self.org_id)
        self.assertAlmostEqual(accounts['accounts']['operating_cash']['balance_usd'], 6.0, places=2)
        self.assertAlmostEqual(accounts['accounts']['expenses_recorded']['balance_usd'], 1.5, places=2)
        self.assertAlmostEqual(accounts['accounts']['executed_payouts']['balance_usd'], 1.5, places=2)
        self.assertAlmostEqual(accounts['accounts']['pending_payouts']['balance_usd'], 0.0, places=2)

    def test_live_execute_payout_records_linked_commitment_settlement_ref(self):
        capsule.ensure_treasury_aliases(self.org_id)
        org_dir = os.path.join(self._capsules_dir, self.org_id)
        os.makedirs(org_dir, exist_ok=True)

        with open(os.path.join(org_dir, 'wallets.json'), 'w') as f:
            json.dump({
                'wallets': {
                    'wallet_live': {
                        'id': 'wallet_live',
                        'verification_level': 3,
                        'verification_label': 'self_custody_verified',
                        'payout_eligible': True,
                        'status': 'active',
                    }
                },
                'verification_levels': {},
            }, f, indent=2)
        with open(os.path.join(org_dir, 'contributors.json'), 'w') as f:
            json.dump({
                'contributors': {
                    'contrib_live': {
                        'id': 'contrib_live',
                        'name': 'Contributor Live',
                        'payout_wallet_id': 'wallet_live',
                    }
                },
                'contribution_types': ['code'],
                'registration_requirements': {},
            }, f, indent=2)

        commitment = treasury.commitments.propose_commitment(
            'host_peer',
            'org_peer',
            'Settle the approved brief',
            commitment_id='com_live_settle',
            proposed_by='user_owner',
            warrant_id='war_live_exec',
            org_id=self.org_id,
        )
        treasury.commitments.accept_commitment(
            commitment['commitment_id'],
            'user_owner',
            org_id=self.org_id,
        )

        proposal = treasury.create_payout_proposal(
            'contrib_live',
            1.5,
            'code',
            proposed_by='user:proposer',
            org_id=self.org_id,
            evidence={'description': 'live capsule proof'},
            linked_commitment_id=commitment['commitment_id'],
        )
        proposal = treasury.submit_payout_proposal(
            proposal['proposal_id'],
            'user:proposer',
            org_id=self.org_id,
        )
        proposal = treasury.review_payout_proposal(
            proposal['proposal_id'],
            'user:reviewer',
            org_id=self.org_id,
        )
        proposal = treasury.approve_payout_proposal(
            proposal['proposal_id'],
            'user:owner',
            org_id=self.org_id,
        )
        proposal = treasury.open_payout_dispute_window(
            proposal['proposal_id'],
            'user:owner',
            org_id=self.org_id,
            dispute_window_hours=0,
        )
        with mock.patch.object(treasury, '_payout_phase_gate', return_value=(True, 'phase 5 test override')):
            proposal = treasury.execute_payout_proposal(
                proposal['proposal_id'],
                'user:owner',
                org_id=self.org_id,
                warrant_id='war_live_exec',
                tx_hash='tx_live_demo_commitment',
            )

        self.assertEqual(proposal['linked_commitment_id'], commitment['commitment_id'])
        self.assertEqual(
            proposal['execution_refs']['linked_commitment_id'],
            commitment['commitment_id'],
        )
        self.assertEqual(proposal['linked_commitment']['commitment_id'], commitment['commitment_id'])
        self.assertEqual(
            proposal['linked_commitment']['settlement_refs'][0]['proposal_id'],
            proposal['proposal_id'],
        )
        self.assertEqual(
            proposal['linked_commitment']['settlement_refs'][0]['tx_ref'],
            proposal['execution_refs']['tx_ref'],
        )
        self.assertEqual(
            proposal['linked_commitment']['settlement_refs'][0]['settlement_adapter_contract_snapshot']['adapter_id'],
            'internal_ledger',
        )
        self.assertEqual(
            proposal['linked_commitment']['settlement_refs'][0]['settlement_adapter_contract_digest'],
            proposal['execution_refs']['settlement_adapter_contract_digest'],
        )
        self.assertEqual(
            treasury.commitments.commitment_summary(self.org_id)['settlement_refs_total'],
            1,
        )

    def test_live_payout_creation_blocks_unverified_wallet(self):
        capsule.ensure_treasury_aliases(self.org_id)
        org_dir = os.path.join(self._capsules_dir, self.org_id)
        os.makedirs(org_dir, exist_ok=True)

        with open(os.path.join(org_dir, 'wallets.json'), 'w') as f:
            json.dump({
                'wallets': {
                    'wallet_blocked': {
                        'id': 'wallet_blocked',
                        'verification_level': 1,
                        'verification_label': 'linked',
                        'payout_eligible': False,
                        'status': 'active',
                    }
                },
                'verification_levels': {},
            }, f, indent=2)
        with open(os.path.join(org_dir, 'contributors.json'), 'w') as f:
            json.dump({
                'contributors': {
                    'contrib_blocked': {
                        'id': 'contrib_blocked',
                        'name': 'Contributor Blocked',
                        'payout_wallet_id': 'wallet_blocked',
                    }
                },
                'contribution_types': ['code'],
                'registration_requirements': {},
            }, f, indent=2)

        with self.assertRaises(PermissionError):
            treasury.create_payout_proposal(
                'contrib_blocked',
                1.0,
                'code',
                proposed_by='user:proposer',
                org_id=self.org_id,
                evidence={'description': 'blocked wallet'},
            )

    def test_live_payout_execution_rejects_disabled_settlement_adapter(self):
        capsule.ensure_treasury_aliases(self.org_id)
        org_dir = os.path.join(self._capsules_dir, self.org_id)
        os.makedirs(org_dir, exist_ok=True)

        with open(os.path.join(org_dir, 'wallets.json'), 'w') as f:
            json.dump({
                'wallets': {
                    'wallet_live': {
                        'id': 'wallet_live',
                        'verification_level': 3,
                        'verification_label': 'self_custody_verified',
                        'payout_eligible': True,
                        'status': 'active',
                    }
                },
                'verification_levels': {},
            }, f, indent=2)
        with open(os.path.join(org_dir, 'contributors.json'), 'w') as f:
            json.dump({
                'contributors': {
                    'contrib_live': {
                        'id': 'contrib_live',
                        'name': 'Contributor Live',
                        'payout_wallet_id': 'wallet_live',
                    }
                },
                'contribution_types': ['code'],
                'registration_requirements': {},
            }, f, indent=2)

        proposal = treasury.create_payout_proposal(
            'contrib_live',
            1.0,
            'code',
            proposed_by='user:proposer',
            org_id=self.org_id,
            evidence={'description': 'live adapter gate'},
            settlement_adapter='base_usdc_x402',
        )
        proposal = treasury.submit_payout_proposal(proposal['proposal_id'], 'user:proposer', org_id=self.org_id)
        proposal = treasury.review_payout_proposal(proposal['proposal_id'], 'user:reviewer', org_id=self.org_id)
        proposal = treasury.approve_payout_proposal(proposal['proposal_id'], 'user:owner', org_id=self.org_id)
        proposal = treasury.open_payout_dispute_window(
            proposal['proposal_id'],
            'user:owner',
            org_id=self.org_id,
            dispute_window_hours=0,
        )
        with mock.patch.object(treasury, '_payout_phase_gate', return_value=(True, 'phase 5 test override')):
            with self.assertRaises(PermissionError):
                treasury.execute_payout_proposal(
                    proposal['proposal_id'],
                    'user:owner',
                    org_id=self.org_id,
                    warrant_id='war_live_disabled',
                    settlement_adapter='base_usdc_x402',
                    tx_hash='0xdeadbeef',
                    settlement_proof={'reference': 'live-proof'},
                )

    def test_live_payout_execution_disabled_adapter_is_atomic(self):
        capsule.ensure_treasury_aliases(self.org_id)
        org_dir = os.path.join(self._capsules_dir, self.org_id)
        os.makedirs(org_dir, exist_ok=True)

        with open(os.path.join(org_dir, 'wallets.json'), 'w') as f:
            json.dump({
                'wallets': {
                    'wallet_live': {
                        'id': 'wallet_live',
                        'verification_level': 3,
                        'verification_label': 'self_custody_verified',
                        'payout_eligible': True,
                        'status': 'active',
                    }
                },
                'verification_levels': {},
            }, f, indent=2)
        with open(os.path.join(org_dir, 'contributors.json'), 'w') as f:
            json.dump({
                'contributors': {
                    'contrib_live': {
                        'id': 'contrib_live',
                        'name': 'Contributor Live',
                        'payout_wallet_id': 'wallet_live',
                    }
                },
                'contribution_types': ['code'],
                'registration_requirements': {},
            }, f, indent=2)

        proposal = treasury.create_payout_proposal(
            'contrib_live',
            1.0,
            'code',
            proposed_by='user:proposer',
            org_id=self.org_id,
            evidence={'description': 'live adapter atomicity gate'},
            settlement_adapter='base_usdc_x402',
        )
        proposal = treasury.submit_payout_proposal(proposal['proposal_id'], 'user:proposer', org_id=self.org_id)
        proposal = treasury.review_payout_proposal(proposal['proposal_id'], 'user:reviewer', org_id=self.org_id)
        proposal = treasury.approve_payout_proposal(proposal['proposal_id'], 'user:owner', org_id=self.org_id)
        proposal = treasury.open_payout_dispute_window(
            proposal['proposal_id'],
            'user:owner',
            org_id=self.org_id,
            dispute_window_hours=0,
        )
        ledger_path = os.path.join(org_dir, 'ledger.json')
        tx_path = os.path.join(org_dir, 'transactions.jsonl')
        with open(ledger_path) as f:
            ledger_before = json.load(f)
        with open(tx_path) as f:
            tx_lines_before = [line for line in f.read().splitlines() if line.strip()]

        with mock.patch.object(treasury, '_payout_phase_gate', return_value=(True, 'phase 5 test override')):
            with self.assertRaises(PermissionError):
                treasury.execute_payout_proposal(
                    proposal['proposal_id'],
                    'user:owner',
                    org_id=self.org_id,
                    warrant_id='war_live_disabled_atomic',
                    settlement_adapter='base_usdc_x402',
                    tx_hash='0xdeadbeef',
                    settlement_proof={'reference': 'live-proof'},
                )

        with open(ledger_path) as f:
            ledger_after = json.load(f)
        with open(tx_path) as f:
            tx_lines_after = [line for line in f.read().splitlines() if line.strip()]
        self.assertEqual(
            ledger_after['treasury']['cash_usd'],
            ledger_before['treasury']['cash_usd'],
        )
        self.assertEqual(
            ledger_after['treasury'].get('expenses_recorded_usd', 0.0),
            ledger_before['treasury'].get('expenses_recorded_usd', 0.0),
        )
        self.assertEqual(tx_lines_after, tx_lines_before)
        proposal_after = treasury.get_payout_proposal(proposal['proposal_id'], org_id=self.org_id)
        self.assertEqual(proposal_after['status'], 'dispute_window')

    def test_live_preflight_settlement_adapter_accepts_internal_ledger(self):
        result = treasury.preflight_settlement_adapter(
            'internal_ledger',
            org_id=self.org_id,
            host_supported_adapters=['internal_ledger'],
        )
        self.assertTrue(result['known'])
        self.assertTrue(result['preflight_ok'])
        self.assertTrue(result['can_execute_now'])
        self.assertTrue(result['execution_enabled'])
        self.assertTrue(result['host_supported'])
        self.assertEqual(result['contract']['execution_mode'], 'host_ledger')
        self.assertEqual(result['contract']['settlement_path'], 'journal_append')
        self.assertEqual(result['contract']['verification_mode'], 'host_ledger')
        self.assertTrue(result['contract']['verification_ready'])
        self.assertFalse(result['contract']['requires_verifier_attestation'])
        self.assertEqual(result['contract']['accepted_attestation_types'], [])
        self.assertEqual(
            result['contract']['contract_digest'],
            treasury.settlement_adapter_contract_digest(result['contract']['contract_snapshot']),
        )
        self.assertEqual(result['requirements']['verification_mode'], 'host_ledger')
        self.assertTrue(result['requirements']['verification_ready'])
        self.assertFalse(result['requirements']['requires_verifier_attestation'])
        self.assertEqual(result['requirements']['accepted_attestation_types'], [])
        self.assertEqual(result['normalized_proof']['proof']['mode'], 'institution_transactions_journal')

    def test_live_preflight_settlement_adapter_reports_disabled_adapter(self):
        result = treasury.preflight_settlement_adapter(
            'base_usdc_x402',
            org_id=self.org_id,
            currency='USDC',
            tx_hash='0xdeadbeef',
            settlement_proof={'reference': 'live-proof'},
            host_supported_adapters=['internal_ledger'],
        )
        self.assertTrue(result['known'])
        self.assertFalse(result['preflight_ok'])
        self.assertFalse(result['can_execute_now'])
        self.assertEqual(result['error_type'], 'permission_error')
        self.assertIn('not enabled', result['error'])
        self.assertEqual(result['contract']['verification_mode'], 'external_attestation')
        self.assertFalse(result['contract']['verification_ready'])
        self.assertTrue(result['contract']['requires_verifier_attestation'])
        self.assertEqual(
            result['contract']['accepted_attestation_types'],
            ['x402_settlement_verifier'],
        )
        self.assertIn('verification_not_ready', result['execution_blockers'])
        self.assertEqual(result['requirements']['verification_mode'], 'external_attestation')
        self.assertFalse(result['requirements']['verification_ready'])
        self.assertTrue(result['requirements']['requires_verifier_attestation'])
        self.assertEqual(
            result['requirements']['accepted_attestation_types'],
            ['x402_settlement_verifier'],
        )

    def test_live_preflight_settlement_adapter_blocks_enabled_external_adapter_without_verifier_readiness(self):
        capsule.ensure_treasury_aliases(self.org_id)
        org_dir = os.path.join(self._capsules_dir, self.org_id)
        os.makedirs(org_dir, exist_ok=True)
        settlement_adapters_path = os.path.join(org_dir, 'settlement_adapters.json')
        with open(settlement_adapters_path, 'w') as f:
            json.dump({
            'default_payout_adapter': 'base_usdc_x402',
            'adapters': {
                'base_usdc_x402': {
                    'status': 'active',
                    'payout_execution_enabled': True,
                },
            },
        }, f, indent=2)

        result = treasury.preflight_settlement_adapter(
            'base_usdc_x402',
            org_id=self.org_id,
            currency='USDC',
            tx_hash='0xdeadbeef',
            settlement_proof={'reference': 'live-proof'},
            host_supported_adapters=['base_usdc_x402'],
        )
        self.assertTrue(result['known'])
        self.assertFalse(result['preflight_ok'])
        self.assertFalse(result['can_execute_now'])
        self.assertEqual(result['error_type'], 'permission_error')
        self.assertIn('verification path is not ready', result['error'])
        self.assertIn('verification_not_ready', result['execution_blockers'])

    def test_subscription_helpers_manage_capsule_state(self):
        created = subscriptions.create_subscription(
            '100',
            plan='trial',
            email='trial@example.com',
            org_id=self.org_id,
        )
        self.assertEqual(created['telegram_id'], '100')
        self.assertEqual(created['subscription']['plan'], 'trial')
        self.assertEqual(created['subscription']['email'], 'trial@example.com')
        self.assertEqual(subscriptions.active_delivery_targets(org_id=self.org_id), ['100'])

        updated = subscriptions.set_subscription_email(
            '100',
            'owner@example.com',
            org_id=self.org_id,
        )
        self.assertEqual(updated['subscription']['email'], 'owner@example.com')

        delivery = subscriptions.record_delivery(
            '100',
            'daily-brief',
            brief_date='2026-03-22',
            org_id=self.org_id,
        )
        self.assertEqual(delivery['entry']['brief_date'], '2026-03-22')
        self.assertEqual(delivery['entry']['product'], 'daily-brief')

        cancelled = subscriptions.cancel_active_subscriptions('100', org_id=self.org_id)
        self.assertEqual(cancelled['telegram_id'], '100')
        self.assertEqual(len(cancelled['cancelled_ids']), 1)
        self.assertEqual(subscriptions.active_delivery_targets(org_id=self.org_id), [])

        stored = subscriptions.load_subs(self.org_id)
        self.assertEqual(stored['subscribers']['100'][-1]['status'], 'cancelled')
        self.assertEqual(stored['delivery_log'][-1]['product'], 'daily-brief')

    def test_subscription_helper_convert_trial_to_paid(self):
        subscriptions.create_subscription('200', plan='trial', org_id=self.org_id)
        with mock.patch.object(subscriptions, '_require_payment_evidence', return_value={
            'order_id': 'ord_demo',
            'payment_key': 'pay_demo',
            'payment_ref': 'ref_demo',
            'tx_hash': '0xfeed',
            'amount': 2.99,
        }):
            converted = subscriptions.convert_trial_subscription(
                '200',
                'premium-brief-weekly',
                payment_ref='ref_demo',
                confirm_payment=True,
                email='paid@example.com',
                org_id=self.org_id,
            )
        self.assertEqual(converted['subscription']['plan'], 'premium-brief-weekly')
        self.assertTrue(converted['subscription']['payment_verified'])
        self.assertEqual(converted['subscription']['payment_evidence']['tx_hash'], '0xfeed')

        stored = subscriptions.load_subs(self.org_id)
        self.assertEqual(stored['subscribers']['200'][0]['status'], 'converted')
        self.assertEqual(stored['subscribers']['200'][1]['plan'], 'premium-brief-weekly')

    def test_subscription_helper_verify_payment_binds_evidence(self):
        created = subscriptions.create_subscription(
            '300',
            plan='premium-brief-weekly',
            payment_ref='ref_initial',
            org_id=self.org_id,
        )
        with mock.patch.object(subscriptions, '_require_payment_evidence', return_value={
            'order_id': 'ord_verify',
            'payment_key': 'pay_verify',
            'payment_ref': 'ref_verified',
            'tx_hash': '0x1234',
            'amount': 2.99,
        }):
            verified = subscriptions.verify_subscription_payment(
                '300',
                subscription_id=created['subscription']['id'],
                payment_ref='ref_verified',
                org_id=self.org_id,
            )
        self.assertTrue(verified['subscription']['payment_verified'])
        self.assertEqual(verified['subscription']['payment_ref'], 'ref_verified')
        self.assertEqual(verified['subscription']['payment_evidence']['order_id'], 'ord_verify')

    def test_accounting_helpers_record_expense_reimburse_and_draw(self):
        result = accounting.record_owner_expense(1.25, note='travel', actor='user:owner', org_id=self.org_id)
        self.assertEqual(result['amount_usd'], 1.25)
        self.assertAlmostEqual(result['unreimbursed_expenses_usd'], 1.25, places=2)

        owner = accounting.load_owner(self.org_id)
        ledger = accounting.load_ledger(self.org_id)
        self.assertAlmostEqual(owner['expenses_paid_usd'], 1.25, places=2)
        self.assertAlmostEqual(ledger['treasury']['cash_usd'], 7.5, places=2)

        result = accounting.reimburse_owner(1.0, note='travel repay', actor='user:owner', org_id=self.org_id)
        self.assertEqual(result['amount_usd'], 1.0)
        self.assertAlmostEqual(result['cash_after_usd'], 6.5, places=2)
        self.assertAlmostEqual(result['unreimbursed_expenses_usd'], 0.25, places=2)

        result = accounting.take_owner_draw(1.0, note='profit', actor='user:owner', org_id=self.org_id)
        self.assertEqual(result['amount_usd'], 1.0)
        self.assertAlmostEqual(result['cash_after_usd'], 5.5, places=2)
        self.assertAlmostEqual(result['available_for_draw_usd'], 0.5, places=2)

        owner = accounting.load_owner(self.org_id)
        ledger = accounting.load_ledger(self.org_id)
        self.assertAlmostEqual(owner['reimbursements_received_usd'], 1.0, places=2)
        self.assertAlmostEqual(owner['draws_taken_usd'], 1.0, places=2)
        self.assertAlmostEqual(ledger['treasury']['cash_usd'], 5.5, places=2)


if __name__ == '__main__':
    unittest.main()
