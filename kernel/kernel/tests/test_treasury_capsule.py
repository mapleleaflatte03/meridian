#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import shutil
import tempfile
import unittest
import uuid
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[2]
TREASURY_PATH = ROOT / 'kernel' / 'treasury.py'
CAPSULE_PATH = ROOT / 'kernel' / 'capsule.py'
ECONOMY_DIR = ROOT / 'economy'
CAPSULES_DIR = ROOT / 'capsules'


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_root_ledger_cash_snapshot():
    path = ECONOMY_DIR / 'ledger.json'
    if not path.exists():
        return {'treasury': {'cash_usd': 0.0}}
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return {'treasury': {'cash_usd': 0.0}}
    if not isinstance(payload, dict):
        return {'treasury': {'cash_usd': 0.0}}
    treasury_payload = payload.get('treasury')
    if not isinstance(treasury_payload, dict):
        payload['treasury'] = {'cash_usd': 0.0}
    elif 'cash_usd' not in treasury_payload:
        treasury_payload['cash_usd'] = 0.0
    return payload


treasury = _load_module('kernel_treasury_test', TREASURY_PATH)
capsule = _load_module('kernel_capsule_test_for_treasury', CAPSULE_PATH)


class TreasuryCapsuleTests(unittest.TestCase):
    def setUp(self):
        self.org_id = f'org_treasury_test_{uuid.uuid4().hex[:8]}'
        self.capsule_dir = CAPSULES_DIR / self.org_id
        capsule.init_capsule(self.org_id)

        ledger_path = pathlib.Path(capsule.capsule_path(self.org_id, 'ledger.json'))
        ledger = json.loads(ledger_path.read_text())
        ledger['updatedAt'] = '2026-03-21T00:00:00Z'
        ledger['epoch']['started_at'] = '2026-03-21T00:00:00Z'
        ledger['agents'] = {
            'atlas': {
                'name': 'Atlas',
                'role': 'analyst',
                'reputation_units': 50,
                'authority_units': 50,
                'probation': False,
                'zero_authority': False,
                'status': 'active',
            }
        }
        ledger_path.write_text(json.dumps(ledger, indent=2))
        self.default_ledger_before = _read_root_ledger_cash_snapshot()

    def tearDown(self):
        shutil.rmtree(self.capsule_dir, ignore_errors=True)

    def test_contribute_owner_capital_writes_only_to_capsule(self):
        result = treasury.contribute_owner_capital(
            7.5,
            note='capsule top-up',
            by='owner',
            org_id=self.org_id,
        )

        self.assertEqual(result['amount_usd'], 7.5)
        ledger = json.loads((self.capsule_dir / 'ledger.json').read_text())
        self.assertAlmostEqual(ledger['treasury']['cash_usd'], 7.5, places=2)
        self.assertAlmostEqual(ledger['treasury']['owner_capital_contributed_usd'], 7.5, places=2)

        tx_lines = [json.loads(line) for line in (self.capsule_dir / 'transactions.jsonl').read_text().splitlines() if line.strip()]
        self.assertEqual(len(tx_lines), 1)
        self.assertEqual(tx_lines[0]['type'], 'treasury_deposit')
        self.assertEqual(tx_lines[0]['deposit_type'], 'owner_capital')

        default_ledger = _read_root_ledger_cash_snapshot()
        self.assertEqual(
            (default_ledger.get('treasury') or {}).get('cash_usd', 0.0),
            (self.default_ledger_before.get('treasury') or {}).get('cash_usd', 0.0),
        )

    def test_load_funding_sources_backfills_owner_capital_from_ledger(self):
        ledger_path = self.capsule_dir / 'ledger.json'
        ledger = json.loads(ledger_path.read_text())
        ledger['treasury']['owner_capital_contributed_usd'] = 4.25
        ledger_path.write_text(json.dumps(ledger, indent=2))

        funding = treasury.load_funding_sources(self.org_id)

        self.assertIn('src_derived_owner_capital', funding['sources'])
        derived = funding['sources']['src_derived_owner_capital']
        self.assertEqual(derived['type'], 'owner_capital')
        self.assertEqual(derived['currency'], 'USD')
        self.assertTrue(derived['metadata']['derived_from_ledger'])
        self.assertAlmostEqual(derived['amount_usd'], 4.25, places=2)

    def test_treasury_snapshot_reads_capsule_protocol_state(self):
        revenue_path = self.capsule_dir / 'revenue.json'
        revenue = json.loads(revenue_path.read_text())
        revenue['clients'] = {'client_a': {'name': 'Capsule Client', 'contact': 'capsule@test'}}
        revenue['orders'] = {
            'order_a': {
                'client': 'client_a',
                'product': 'capsule-substrate',
                'amount_usd': 3.5,
                'status': 'paid',
                'history': [],
                'created_at': '2026-03-21T00:00:00Z',
            }
        }
        revenue['receivables_usd'] = 0.0
        revenue_path.write_text(json.dumps(revenue, indent=2))

        ledger_path = self.capsule_dir / 'ledger.json'
        ledger = json.loads(ledger_path.read_text())
        ledger['treasury']['cash_usd'] = 11.0
        ledger['treasury']['total_revenue_usd'] = 3.5
        ledger['treasury']['reserve_floor_usd'] = 5.0
        ledger_path.write_text(json.dumps(ledger, indent=2))

        (self.capsule_dir / 'wallets.json').write_text(json.dumps({
            'wallets': {
                'wallet_capsule': {
                    'id': 'wallet_capsule',
                    'verification_level': 3,
                    'verification_label': 'self_custody_verified',
                    'payout_eligible': True,
                    'status': 'active',
                }
            },
            'verification_levels': {},
        }, indent=2))
        (self.capsule_dir / 'maintainers.json').write_text(json.dumps({
            'maintainers': {'m1': {'name': 'Maintainer'}},
            'roles': {},
        }, indent=2))
        (self.capsule_dir / 'contributors.json').write_text(json.dumps({
            'contributors': {'c1': {'name': 'Contributor'}},
            'contribution_types': [],
            'registration_requirements': {},
        }, indent=2))
        (self.capsule_dir / 'payout_proposals.json').write_text(json.dumps({
            'proposals': {'p1': {'status': 'submitted'}},
            'state_machine': {},
            'proposal_schema': {},
        }, indent=2))
        (self.capsule_dir / 'funding_sources.json').write_text(json.dumps({
            'sources': {'s1': {'type': 'owner_capital'}},
            'source_types': {},
        }, indent=2))

        snapshot = treasury.treasury_snapshot(self.org_id)

        self.assertEqual(snapshot['balance_usd'], 11.0)
        self.assertEqual(snapshot['total_revenue_usd'], 3.5)
        self.assertEqual(snapshot['clients'], 1)
        self.assertEqual(snapshot['paid_orders'], 1)
        self.assertEqual(snapshot['protocol']['wallet_count'], 1)
        self.assertEqual(snapshot['protocol']['payout_eligible_wallets'], 1)
        self.assertEqual(snapshot['protocol']['maintainer_count'], 1)
        self.assertEqual(snapshot['protocol']['contributor_count'], 1)
        self.assertEqual(snapshot['protocol']['pending_proposals'], 1)
        self.assertEqual(snapshot['protocol']['funding_sources'], 1)

    def test_load_wallets_migrates_legacy_registry_for_founding_alias(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = pathlib.Path(tmpdir)
            economy_dir = tmpdir / 'economy'
            economy_dir.mkdir()
            legacy_treasury = tmpdir / 'treasury'
            legacy_treasury.mkdir()
            legacy_wallets = legacy_treasury / 'wallets.json'
            legacy_payload = {
                'wallets': {'legacy_wallet': {'id': 'legacy_wallet', 'status': 'active'}},
                'verification_levels': {},
            }
            legacy_wallets.write_text(json.dumps(legacy_payload, indent=2))

            def fake_capsule_path(org_id, filename):
                return str(economy_dir / filename)

            with mock.patch.object(treasury, 'ECONOMY_DIR', str(economy_dir)), \
                 mock.patch.object(treasury, 'LEGACY_TREASURY_DIR', str(legacy_treasury)), \
                 mock.patch.object(treasury, 'capsule_path', side_effect=fake_capsule_path):
                wallets = treasury.load_wallets('org_b7d95bae')

            migrated_path = economy_dir / 'wallets.json'
            self.assertTrue(migrated_path.exists())
            self.assertIn('legacy_wallet', wallets['wallets'])

    def test_payout_proposal_lifecycle_executes_against_capsule_state(self):
        ledger_path = self.capsule_dir / 'ledger.json'
        ledger = json.loads(ledger_path.read_text())
        ledger['treasury']['cash_usd'] = 120.0
        ledger['treasury']['reserve_floor_usd'] = 50.0
        ledger_path.write_text(json.dumps(ledger, indent=2))

        (self.capsule_dir / 'wallets.json').write_text(json.dumps({
            'wallets': {
                'wallet_exec': {
                    'id': 'wallet_exec',
                    'verification_level': 3,
                    'verification_label': 'self_custody_verified',
                    'payout_eligible': True,
                    'status': 'active',
                }
            },
            'verification_levels': {},
        }, indent=2))
        (self.capsule_dir / 'contributors.json').write_text(json.dumps({
            'contributors': {
                'contrib_exec': {
                    'id': 'contrib_exec',
                    'name': 'Contributor Exec',
                    'payout_wallet_id': 'wallet_exec',
                }
            },
            'contribution_types': ['code'],
            'registration_requirements': {},
        }, indent=2))

        proposal = treasury.create_payout_proposal(
            'contrib_exec',
            12.0,
            'code',
            proposed_by='user:proposer',
            org_id=self.org_id,
            evidence={'pr_urls': ['https://example.test/pr/1']},
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
        proposal = treasury.execute_payout_proposal(
            proposal['proposal_id'],
            'user:owner',
            org_id=self.org_id,
            warrant_id='war_exec_123',
            tx_hash='tx_demo_hash',
        )

        self.assertEqual(proposal['status'], 'executed')
        self.assertEqual(proposal['warrant_id'], 'war_exec_123')
        self.assertEqual(proposal['tx_hash'], 'tx_demo_hash')
        self.assertTrue(proposal['execution_refs']['tx_ref'].startswith('ptx_'))
        self.assertEqual(proposal['execution_refs']['proof_type'], 'ledger_transaction')
        self.assertEqual(proposal['execution_refs']['verification_state'], 'host_ledger_final')
        self.assertEqual(proposal['execution_refs']['finality_state'], 'host_local_final')
        self.assertEqual(proposal['execution_refs']['settlement_adapter_contract']['execution_mode'], 'host_ledger')
        self.assertEqual(proposal['execution_refs']['settlement_adapter_contract']['dispute_model'], 'court_case')
        self.assertEqual(proposal['execution_refs']['settlement_adapter_contract']['finality_model'], 'host_local_final')
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

        summary = treasury.payout_proposal_summary(self.org_id)
        self.assertEqual(summary['executed'], 1)
        self.assertEqual(summary['requested_usd'], 12.0)
        self.assertEqual(summary['executed_usd'], 12.0)

        ledger = json.loads(ledger_path.read_text())
        self.assertAlmostEqual(ledger['treasury']['cash_usd'], 108.0, places=2)
        self.assertAlmostEqual(ledger['treasury']['expenses_recorded_usd'], 12.0, places=2)

        tx_lines = [json.loads(line) for line in (self.capsule_dir / 'transactions.jsonl').read_text().splitlines() if line.strip()]
        self.assertEqual(tx_lines[-1]['type'], 'payout_execution')
        self.assertEqual(tx_lines[-1]['proposal_id'], proposal['proposal_id'])
        self.assertEqual(tx_lines[-1]['warrant_id'], 'war_exec_123')
        self.assertEqual(tx_lines[-1]['verification_state'], 'host_ledger_final')
        self.assertEqual(tx_lines[-1]['settlement_adapter_contract']['execution_mode'], 'host_ledger')
        self.assertEqual(
            tx_lines[-1]['settlement_adapter_contract_snapshot']['adapter_id'],
            'internal_ledger',
        )
        self.assertEqual(
            tx_lines[-1]['settlement_adapter_contract_digest'],
            proposal['execution_refs']['settlement_adapter_contract_digest'],
        )

    def test_create_payout_proposal_blocks_ineligible_wallet(self):
        (self.capsule_dir / 'wallets.json').write_text(json.dumps({
            'wallets': {
                'wallet_blocked': {
                    'id': 'wallet_blocked',
                    'verification_level': 2,
                    'verification_label': 'exchange_linked',
                    'payout_eligible': False,
                    'status': 'active',
                }
            },
            'verification_levels': {},
        }, indent=2))
        (self.capsule_dir / 'contributors.json').write_text(json.dumps({
            'contributors': {
                'contrib_blocked': {
                    'id': 'contrib_blocked',
                    'name': 'Contributor Blocked',
                    'payout_wallet_id': 'wallet_blocked',
                }
            },
            'contribution_types': ['code'],
            'registration_requirements': {},
        }, indent=2))

        with self.assertRaises(PermissionError):
            treasury.create_payout_proposal(
                'contrib_blocked',
                5.0,
                'code',
                proposed_by='user:proposer',
                org_id=self.org_id,
                evidence={'description': 'bad wallet should fail'},
            )

    def test_execute_payout_proposal_rejects_disabled_settlement_adapter(self):
        (self.capsule_dir / 'wallets.json').write_text(json.dumps({
            'wallets': {
                'wallet_exec': {
                    'id': 'wallet_exec',
                    'verification_level': 3,
                    'verification_label': 'self_custody_verified',
                    'payout_eligible': True,
                    'status': 'active',
                }
            },
            'verification_levels': {},
        }, indent=2))
        (self.capsule_dir / 'contributors.json').write_text(json.dumps({
            'contributors': {
                'contrib_exec': {
                    'id': 'contrib_exec',
                    'name': 'Contributor Exec',
                    'payout_wallet_id': 'wallet_exec',
                }
            },
            'contribution_types': ['code'],
            'registration_requirements': {},
        }, indent=2))
        proposal = treasury.create_payout_proposal(
            'contrib_exec',
            2.0,
            'code',
            proposed_by='user:proposer',
            org_id=self.org_id,
            evidence={'description': 'adapter gate'},
            settlement_adapter='base_usdc_x402',
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
        with self.assertRaises(PermissionError):
            treasury.execute_payout_proposal(
                proposal['proposal_id'],
                'user:owner',
                org_id=self.org_id,
                warrant_id='war_disabled_adapter',
                settlement_adapter='base_usdc_x402',
                tx_hash='0xdeadbeef',
                settlement_proof={'reference': 'demo-proof'},
            )

    def test_execute_payout_proposal_disabled_adapter_is_atomic(self):
        (self.capsule_dir / 'wallets.json').write_text(json.dumps({
            'wallets': {
                'wallet_exec': {
                    'id': 'wallet_exec',
                    'verification_level': 3,
                    'verification_label': 'self_custody_verified',
                    'payout_eligible': True,
                    'status': 'active',
                }
            },
            'verification_levels': {},
        }, indent=2))
        (self.capsule_dir / 'contributors.json').write_text(json.dumps({
            'contributors': {
                'contrib_exec': {
                    'id': 'contrib_exec',
                    'name': 'Contributor Exec',
                    'payout_wallet_id': 'wallet_exec',
                }
            },
            'contribution_types': ['code'],
            'registration_requirements': {},
        }, indent=2))
        proposal = treasury.create_payout_proposal(
            'contrib_exec',
            2.0,
            'code',
            proposed_by='user:proposer',
            org_id=self.org_id,
            evidence={'description': 'adapter atomicity gate'},
            settlement_adapter='base_usdc_x402',
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
        ledger_path = self.capsule_dir / 'ledger.json'
        tx_path = self.capsule_dir / 'transactions.jsonl'
        ledger_before = json.loads(ledger_path.read_text())
        tx_lines_before = [line for line in tx_path.read_text().splitlines() if line.strip()]

        with self.assertRaises(PermissionError):
            treasury.execute_payout_proposal(
                proposal['proposal_id'],
                'user:owner',
                org_id=self.org_id,
                warrant_id='war_disabled_adapter_atomic',
                settlement_adapter='base_usdc_x402',
                tx_hash='0xdeadbeef',
                settlement_proof={'reference': 'demo-proof'},
            )

        ledger_after = json.loads(ledger_path.read_text())
        tx_lines_after = [line for line in tx_path.read_text().splitlines() if line.strip()]
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

    def test_execute_payout_proposal_accepts_enabled_base_x402_with_ready_verifier(self):
        ledger_path = self.capsule_dir / 'ledger.json'
        ledger = json.loads(ledger_path.read_text())
        ledger['treasury']['cash_usd'] = 120.0
        ledger['treasury']['reserve_floor_usd'] = 50.0
        ledger['treasury']['expenses_recorded_usd'] = 0.0
        ledger_path.write_text(json.dumps(ledger, indent=2))

        (self.capsule_dir / 'wallets.json').write_text(json.dumps({
            'wallets': {
                'wallet_exec': {
                    'id': 'wallet_exec',
                    'verification_level': 3,
                    'verification_label': 'self_custody_verified',
                    'payout_eligible': True,
                    'status': 'active',
                }
            },
            'verification_levels': {},
        }, indent=2))
        (self.capsule_dir / 'contributors.json').write_text(json.dumps({
            'contributors': {
                'contrib_exec': {
                    'id': 'contrib_exec',
                    'name': 'Contributor Exec',
                    'payout_wallet_id': 'wallet_exec',
                }
            },
            'contribution_types': ['code'],
            'registration_requirements': {},
        }, indent=2))
        settlement_adapters_path = self.capsule_dir / 'settlement_adapters.json'
        settlement_adapters_path.write_text(json.dumps({
            'default_payout_adapter': 'base_usdc_x402',
            'adapters': {
                'base_usdc_x402': {
                    'status': 'active',
                    'payout_execution_enabled': True,
                    'verification_ready': True,
                },
            },
        }, indent=2))

        proposal = treasury.create_payout_proposal(
            'contrib_exec',
            2.0,
            'code',
            proposed_by='user:proposer',
            org_id=self.org_id,
            evidence={'description': 'enabled x402 adapter'},
            settlement_adapter='base_usdc_x402',
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
        with mock.patch.object(
            treasury,
            '_current_phase',
            lambda org_id=None: (5, {'name': 'Contributor Payouts'}),
        ):
            executed = treasury.execute_payout_proposal(
                proposal['proposal_id'],
                'user:owner',
                org_id=self.org_id,
                warrant_id='war_enabled_adapter',
                settlement_adapter='base_usdc_x402',
                tx_hash='0xbaseenabled',
                settlement_proof={
                    'reference': 'base://receipt/enabled',
                    'verification_attestation': {
                        'type': 'x402_settlement_verifier',
                        'reference': 'attest://base/enabled',
                    },
                },
                host_supported_adapters=['base_usdc_x402'],
            )

        self.assertEqual(executed['status'], 'executed')
        self.assertEqual(executed['settlement_adapter'], 'base_usdc_x402')
        self.assertEqual(executed['tx_hash'], '0xbaseenabled')
        self.assertEqual(executed['execution_refs']['proof_type'], 'onchain_receipt')
        self.assertEqual(
            executed['execution_refs']['verification_state'],
            'external_verification_required',
        )
        self.assertEqual(
            executed['execution_refs']['finality_state'],
            'external_chain_finality',
        )
        self.assertEqual(
            executed['execution_refs']['settlement_adapter_contract']['settlement_path'],
            'x402_onchain',
        )
        self.assertEqual(
            executed['execution_refs']['settlement_adapter_contract_snapshot']['adapter_id'],
            'base_usdc_x402',
        )
        self.assertTrue(
            executed['execution_refs']['settlement_adapter_contract_snapshot']['verification_ready']
        )
        self.assertEqual(
            executed['execution_refs']['settlement_adapter_contract_digest'],
            treasury.settlement_adapter_contract_digest(
                executed['execution_refs']['settlement_adapter_contract_snapshot']
            ),
        )
        self.assertEqual(
            executed['execution_refs']['proof']['reference'],
            'base://receipt/enabled',
        )
        self.assertEqual(
            executed['execution_refs']['proof']['verification_attestation']['type'],
            'x402_settlement_verifier',
        )
        self.assertTrue(executed['execution_queue_persisted'])
        self.assertIsNotNone(executed['execution_queue_record'])
        self.assertEqual(executed['execution_queue_record']['state'], 'executed')
        self.assertEqual(executed['execution_queue_record']['execution_id'], executed['execution_refs']['tx_ref'])
        self.assertEqual(
            executed['execution_queue_record']['adapter_contract_digest'],
            executed['execution_refs']['settlement_adapter_contract_digest'],
        )

        ledger = json.loads((self.capsule_dir / 'ledger.json').read_text())
        self.assertAlmostEqual(ledger['treasury']['cash_usd'], 118.0, places=2)
        self.assertAlmostEqual(ledger['treasury']['expenses_recorded_usd'], 2.0, places=2)

        tx_lines = [json.loads(line) for line in (self.capsule_dir / 'transactions.jsonl').read_text().splitlines() if line.strip()]
        self.assertEqual(tx_lines[-1]['type'], 'payout_execution')
        self.assertEqual(tx_lines[-1]['settlement_adapter'], 'base_usdc_x402')
        self.assertEqual(tx_lines[-1]['tx_hash'], '0xbaseenabled')
        self.assertEqual(
            tx_lines[-1]['settlement_adapter_contract']['settlement_path'],
            'x402_onchain',
        )
        self.assertEqual(
            tx_lines[-1]['settlement_adapter_contract_digest'],
            executed['execution_refs']['settlement_adapter_contract_digest'],
        )

    def test_execute_payout_records_linked_commitment_settlement_ref(self):
        ledger_path = self.capsule_dir / 'ledger.json'
        ledger = json.loads(ledger_path.read_text())
        ledger['treasury']['cash_usd'] = 120.0
        ledger['treasury']['reserve_floor_usd'] = 50.0
        ledger_path.write_text(json.dumps(ledger, indent=2))

        (self.capsule_dir / 'wallets.json').write_text(json.dumps({
            'wallets': {
                'wallet_exec': {
                    'id': 'wallet_exec',
                    'verification_level': 3,
                    'verification_label': 'self_custody_verified',
                    'payout_eligible': True,
                    'status': 'active',
                }
            },
            'verification_levels': {},
        }, indent=2))
        (self.capsule_dir / 'contributors.json').write_text(json.dumps({
            'contributors': {
                'contrib_exec': {
                    'id': 'contrib_exec',
                    'name': 'Contributor Exec',
                    'payout_wallet_id': 'wallet_exec',
                }
            },
            'contribution_types': ['code'],
            'registration_requirements': {},
        }, indent=2))

        commitment = treasury.commitments.propose_commitment(
            self.org_id,
            'host_beta',
            'org_beta',
            'Settle the approved brief',
            'user_owner',
            warrant_id='war_exec_123',
        )
        treasury.commitments.accept_commitment(
            commitment['commitment_id'],
            'user_owner',
            org_id=self.org_id,
        )

        proposal = treasury.create_payout_proposal(
            'contrib_exec',
            12.0,
            'code',
            proposed_by='user:proposer',
            org_id=self.org_id,
            evidence={'pr_urls': ['https://example.test/pr/1']},
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
                warrant_id='war_exec_123',
                tx_hash='tx_demo_hash',
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

    def test_settlement_adapter_readiness_snapshot_explains_host_blockers(self):
        settlement_adapters_path = self.capsule_dir / 'settlement_adapters.json'
        settlement_adapters_path.write_text(json.dumps({
            'default_payout_adapter': 'base_usdc_x402',
            'adapters': {
                'internal_ledger': {
                    'status': 'active',
                    'payout_execution_enabled': True,
                },
                'base_usdc_x402': {
                    'status': 'active',
                    'payout_execution_enabled': True,
                    'verification_ready': False,
                },
            },
        }, indent=2))

        snapshot = treasury.settlement_adapter_readiness_snapshot(
            self.org_id,
            host_supported_adapters=['internal_ledger'],
        )

        self.assertEqual(snapshot['default_payout_adapter'], 'base_usdc_x402')
        self.assertEqual(snapshot['host_supported_adapters'], ['internal_ledger'])
        self.assertEqual(snapshot['summary']['default_payout_adapter'], 'base_usdc_x402')
        self.assertEqual(snapshot['ready_adapter_ids'], ['internal_ledger'])
        self.assertIn('base_usdc_x402', snapshot['blocked_adapter_ids'])

        ready = next(item for item in snapshot['adapters'] if item['adapter_id'] == 'internal_ledger')
        blocked = next(item for item in snapshot['adapters'] if item['adapter_id'] == 'base_usdc_x402')
        self.assertTrue(ready['execution_ready'])
        self.assertEqual(ready['execution_blocker_messages'], ['Adapter is ready for execution on this host.'])
        self.assertFalse(blocked['execution_ready'])
        self.assertIn('host_not_supported', blocked['execution_blockers'])
        self.assertIn('verification_not_ready', blocked['execution_blockers'])
        self.assertIn('The current host does not advertise this adapter.', blocked['execution_blocker_messages'])
        self.assertEqual(
            blocked['contract_digest'],
            treasury.settlement_adapter_contract_digest(blocked['contract_snapshot']),
        )

    def test_preflight_settlement_adapter_accepts_internal_ledger(self):
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
        self.assertTrue(result['execution_ready'])
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
        self.assertEqual(result['contract']['dispute_model'], 'court_case')
        self.assertEqual(result['contract']['finality_model'], 'host_local_final')
        self.assertFalse(result['execution_blockers'])
        self.assertEqual(result['requirements']['execution_mode'], 'host_ledger')
        self.assertEqual(result['requirements']['settlement_path'], 'journal_append')
        self.assertEqual(result['requirements']['verification_mode'], 'host_ledger')
        self.assertTrue(result['requirements']['verification_ready'])
        self.assertFalse(result['requirements']['requires_verifier_attestation'])
        self.assertEqual(result['requirements']['accepted_attestation_types'], [])
        self.assertEqual(result['requirements']['dispute_model'], 'court_case')
        self.assertEqual(result['requirements']['finality_model'], 'host_local_final')
        self.assertEqual(result['normalized_proof']['proof']['mode'], 'institution_transactions_journal')
        self.assertEqual(result['normalized_proof']['execution_mode'], 'host_ledger')
        self.assertEqual(result['normalized_proof']['settlement_path'], 'journal_append')

    def test_preflight_settlement_adapter_requires_host_support_for_x402_execution(self):
        result = treasury.preflight_settlement_adapter(
            'base_usdc_x402',
            org_id=self.org_id,
            currency='USDC',
            tx_hash='0xdeadbeef',
            settlement_proof={'reference': 'demo-proof'},
            host_supported_adapters=['internal_ledger'],
        )
        self.assertTrue(result['known'])
        self.assertFalse(result['preflight_ok'])
        self.assertFalse(result['can_execute_now'])
        self.assertEqual(result['error_type'], 'permission_error')
        self.assertIn('not supported on this host', result['error'])
        self.assertFalse(result['execution_ready'])
        self.assertEqual(result['contract']['execution_mode'], 'external_chain')
        self.assertEqual(result['contract']['settlement_path'], 'x402_onchain')
        self.assertEqual(result['contract']['verification_mode'], 'external_attestation')
        self.assertTrue(result['contract']['verification_ready'])
        self.assertTrue(result['contract']['requires_verifier_attestation'])
        self.assertEqual(
            result['contract']['accepted_attestation_types'],
            ['x402_settlement_verifier'],
        )
        self.assertEqual(result['contract']['dispute_model'], 'court_case_plus_chain_review')
        self.assertEqual(result['contract']['finality_model'], 'external_chain_finality')
        self.assertIn('host_not_supported', result['execution_blockers'])
        self.assertEqual(result['requirements']['execution_mode'], 'external_chain')
        self.assertEqual(result['requirements']['settlement_path'], 'x402_onchain')
        self.assertEqual(result['requirements']['verification_mode'], 'external_attestation')
        self.assertTrue(result['requirements']['verification_ready'])
        self.assertTrue(result['requirements']['requires_verifier_attestation'])
        self.assertEqual(
            result['requirements']['accepted_attestation_types'],
            ['x402_settlement_verifier'],
        )
        self.assertEqual(result['requirements']['dispute_model'], 'court_case_plus_chain_review')
        self.assertEqual(result['requirements']['finality_model'], 'external_chain_finality')

    def test_preflight_settlement_adapter_accepts_x402_with_host_support_and_verifier_attestation(self):
        result = treasury.preflight_settlement_adapter(
            'base_usdc_x402',
            org_id=self.org_id,
            currency='USDC',
            tx_hash='0xdeadbeef',
            settlement_proof={
                'reference': 'demo-proof',
                'verification_attestation': {
                    'type': 'x402_settlement_verifier',
                    'reference': 'attest://base/demo',
                },
            },
            host_supported_adapters=['base_usdc_x402'],
        )
        self.assertTrue(result['known'])
        self.assertTrue(result['preflight_ok'])
        self.assertTrue(result['can_execute_now'])
        self.assertTrue(result['execution_enabled'])
        self.assertTrue(result['host_supported'])
        self.assertTrue(result['execution_ready'])
        self.assertEqual(result['contract']['execution_mode'], 'external_chain')
        self.assertEqual(result['contract']['settlement_path'], 'x402_onchain')
        self.assertEqual(result['contract']['verification_mode'], 'external_attestation')
        self.assertTrue(result['contract']['verification_ready'])
        self.assertTrue(result['contract']['requires_verifier_attestation'])
        self.assertEqual(result['contract']['accepted_attestation_types'], ['x402_settlement_verifier'])
        self.assertFalse(result['execution_blockers'])
        self.assertEqual(result['requirements']['verification_ready'], True)
        self.assertEqual(result['normalized_proof']['execution_mode'], 'external_chain')
        self.assertEqual(result['normalized_proof']['settlement_path'], 'x402_onchain')
        self.assertEqual(result['normalized_proof']['verification_attestation_types'], ['x402_settlement_verifier'])

    def test_preflight_settlement_adapter_requires_host_support_for_manual_wire_execution(self):
        result = treasury.preflight_settlement_adapter(
            'manual_bank_wire',
            org_id=self.org_id,
            currency='USD',
            settlement_proof={'reference': 'manual-receipt'},
            host_supported_adapters=['internal_ledger'],
        )
        self.assertTrue(result['known'])
        self.assertFalse(result['preflight_ok'])
        self.assertFalse(result['can_execute_now'])
        self.assertEqual(result['error_type'], 'permission_error')
        self.assertIn('not supported on this host', result['error'])
        self.assertFalse(result['execution_ready'])
        self.assertEqual(result['contract']['execution_mode'], 'manual_offchain')
        self.assertEqual(result['contract']['settlement_path'], 'manual_bank_review')
        self.assertEqual(result['contract']['verification_mode'], 'manual_attestation')
        self.assertTrue(result['contract']['verification_ready'])
        self.assertTrue(result['contract']['requires_verifier_attestation'])
        self.assertEqual(
            result['contract']['accepted_attestation_types'],
            ['manual_wire_verifier'],
        )
        self.assertEqual(result['contract']['dispute_model'], 'manual_reversal_and_court_case')
        self.assertEqual(result['contract']['finality_model'], 'manual_settlement_pending')
        self.assertIn('host_not_supported', result['execution_blockers'])
        self.assertEqual(result['requirements']['execution_mode'], 'manual_offchain')
        self.assertEqual(result['requirements']['settlement_path'], 'manual_bank_review')
        self.assertEqual(result['requirements']['verification_mode'], 'manual_attestation')
        self.assertTrue(result['requirements']['verification_ready'])
        self.assertTrue(result['requirements']['requires_verifier_attestation'])
        self.assertEqual(
            result['requirements']['accepted_attestation_types'],
            ['manual_wire_verifier'],
        )
        self.assertEqual(result['requirements']['dispute_model'], 'manual_reversal_and_court_case')
        self.assertEqual(result['requirements']['finality_model'], 'manual_settlement_pending')

    def test_preflight_settlement_adapter_accepts_manual_wire_with_evidence_and_host_support(self):
        result = treasury.preflight_settlement_adapter(
            'manual_bank_wire',
            org_id=self.org_id,
            currency='USD',
            settlement_proof={
                'reference': 'manual-receipt',
                'verification_attestation': {
                    'type': 'manual_wire_verifier',
                    'reference': 'attest://manual/wire',
                },
            },
            host_supported_adapters=['manual_bank_wire'],
        )
        self.assertTrue(result['known'])
        self.assertTrue(result['preflight_ok'])
        self.assertTrue(result['can_execute_now'])
        self.assertTrue(result['execution_enabled'])
        self.assertTrue(result['host_supported'])
        self.assertTrue(result['execution_ready'])
        self.assertEqual(result['contract']['execution_mode'], 'manual_offchain')
        self.assertEqual(result['contract']['settlement_path'], 'manual_bank_review')
        self.assertEqual(result['contract']['verification_mode'], 'manual_attestation')
        self.assertTrue(result['contract']['verification_ready'])
        self.assertTrue(result['contract']['requires_verifier_attestation'])
        self.assertEqual(result['contract']['accepted_attestation_types'], ['manual_wire_verifier'])
        self.assertFalse(result['execution_blockers'])
        self.assertEqual(result['requirements']['verification_ready'], True)
        self.assertEqual(result['normalized_proof']['execution_mode'], 'manual_offchain')
        self.assertEqual(result['normalized_proof']['settlement_path'], 'manual_bank_review')
        self.assertEqual(result['normalized_proof']['verification_attestation_types'], ['manual_wire_verifier'])

    def test_preflight_settlement_adapter_blocks_enabled_external_adapter_without_verifier_readiness(self):
        settlement_adapters_path = self.capsule_dir / 'settlement_adapters.json'
        settlement_adapters_path.write_text(json.dumps({
            'default_payout_adapter': 'base_usdc_x402',
            'adapters': {
                'base_usdc_x402': {
                    'status': 'active',
                    'payout_execution_enabled': True,
                    'verification_ready': False,
                },
            },
        }, indent=2))

        result = treasury.preflight_settlement_adapter(
            'base_usdc_x402',
            org_id=self.org_id,
            currency='USDC',
            tx_hash='0xdeadbeef',
            settlement_proof={'reference': 'demo-proof'},
            host_supported_adapters=['base_usdc_x402'],
        )
        self.assertTrue(result['known'])
        self.assertFalse(result['preflight_ok'])
        self.assertFalse(result['can_execute_now'])
        self.assertEqual(result['error_type'], 'permission_error')
        self.assertIn('verification path is not ready', result['error'])
        self.assertIn('verification_not_ready', result['execution_blockers'])
        self.assertFalse(result['execution_ready'])

    def test_preflight_settlement_adapter_requires_verifier_attestation_when_ready(self):
        settlement_adapters_path = self.capsule_dir / 'settlement_adapters.json'
        settlement_adapters_path.write_text(json.dumps({
            'default_payout_adapter': 'base_usdc_x402',
            'adapters': {
                'base_usdc_x402': {
                    'status': 'active',
                    'payout_execution_enabled': True,
                    'verification_ready': True,
                },
            },
        }, indent=2))

        result = treasury.preflight_settlement_adapter(
            'base_usdc_x402',
            org_id=self.org_id,
            currency='USDC',
            tx_hash='0xdeadbeef',
            settlement_proof={'reference': 'demo-proof'},
            host_supported_adapters=['base_usdc_x402'],
        )
        self.assertTrue(result['known'])
        self.assertFalse(result['preflight_ok'])
        self.assertFalse(result['can_execute_now'])
        self.assertEqual(result['error_type'], 'validation_error')
        self.assertIn('verifier attestation', result['error'])
        self.assertTrue(result['execution_ready'])

    def test_execute_payout_proposal_dry_run_returns_preview_without_mutating_state(self):
        ledger_path = self.capsule_dir / 'ledger.json'
        ledger = json.loads(ledger_path.read_text())
        ledger['treasury']['cash_usd'] = 120.0
        ledger['treasury']['reserve_floor_usd'] = 50.0
        ledger['treasury']['expenses_recorded_usd'] = 0.0
        ledger_path.write_text(json.dumps(ledger, indent=2))

        (self.capsule_dir / 'wallets.json').write_text(json.dumps({
            'wallets': {
                'wallet_exec': {
                    'id': 'wallet_exec',
                    'verification_level': 3,
                    'verification_label': 'self_custody_verified',
                    'payout_eligible': True,
                    'status': 'active',
                }
            },
            'verification_levels': {},
        }, indent=2))
        (self.capsule_dir / 'contributors.json').write_text(json.dumps({
            'contributors': {
                'contrib_exec': {
                    'id': 'contrib_exec',
                    'name': 'Contributor Exec',
                    'payout_wallet_id': 'wallet_exec',
                }
            },
            'contribution_types': ['code'],
            'registration_requirements': {},
        }, indent=2))
        settlement_adapters_path = self.capsule_dir / 'settlement_adapters.json'
        settlement_adapters_path.write_text(json.dumps({
            'default_payout_adapter': 'base_usdc_x402',
            'adapters': {
                'base_usdc_x402': {
                    'status': 'active',
                    'payout_execution_enabled': True,
                    'verification_ready': True,
                },
            },
        }, indent=2))

        proposal = treasury.create_payout_proposal(
            'contrib_exec',
            2.0,
            'code',
            proposed_by='user:proposer',
            org_id=self.org_id,
            evidence={'description': 'dry run preview'},
            settlement_adapter='base_usdc_x402',
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
        ledger_before = json.loads(ledger_path.read_text())
        tx_path = self.capsule_dir / 'transactions.jsonl'
        tx_lines_before = [line for line in tx_path.read_text().splitlines() if line.strip()]

        with mock.patch.object(
            treasury,
            '_current_phase',
            lambda org_id=None: (5, {'name': 'Contributor Payouts'}),
        ):
            preview = treasury.execute_payout_proposal(
                proposal['proposal_id'],
                'user:owner',
                org_id=self.org_id,
                warrant_id='war_preview_adapter',
                settlement_adapter='base_usdc_x402',
                tx_hash='0xbasepreview',
                settlement_proof={
                    'reference': 'base://receipt/preview',
                    'verification_attestation': {
                        'type': 'x402_settlement_verifier',
                        'reference': 'attest://base/preview',
                    },
                },
                host_supported_adapters=['base_usdc_x402'],
                dry_run=True,
            )

        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['status'], 'dispute_window')
        self.assertEqual(preview['settlement_adapter'], 'base_usdc_x402')
        self.assertEqual(preview['execution_plan']['amount_usd'], 2.0)
        self.assertTrue(preview['execution_plan']['tx_ref'].startswith('ptx_preview_'))
        self.assertEqual(preview['execution_plan']['cash_after'], 118.0)
        self.assertEqual(preview['execution_plan']['settlement_adapter_contract']['execution_mode'], 'external_chain')
        self.assertEqual(preview['execution_plan']['settlement_adapter_contract_digest'], treasury.settlement_adapter_contract_digest(preview['execution_plan']['settlement_adapter_contract_snapshot']))

        ledger_after = json.loads(ledger_path.read_text())
        tx_lines_after = [line for line in tx_path.read_text().splitlines() if line.strip()]
        self.assertEqual(ledger_after['treasury']['cash_usd'], ledger_before['treasury']['cash_usd'])
        self.assertEqual(ledger_after['treasury']['expenses_recorded_usd'], ledger_before['treasury']['expenses_recorded_usd'])
        self.assertEqual(tx_lines_after, tx_lines_before)
        proposal_after = treasury.get_payout_proposal(proposal['proposal_id'], org_id=self.org_id)
        self.assertEqual(proposal_after['status'], 'dispute_window')
        self.assertNotIn('executed_at', preview)
        self.assertTrue(preview['plan_preview_queue_persisted'])
        self.assertIsNotNone(preview['plan_preview_queue_record'])
        self.assertEqual(preview['plan_preview_queue_record']['preview_id'], preview['execution_plan']['tx_ref'])
        self.assertEqual(
            preview['plan_preview_queue_record']['preview_truth_source'],
            'payout_dry_run_and_adapter_contract_only',
        )
        self.assertTrue(preview['execution_queue_persisted'])
        self.assertIsNotNone(preview['execution_queue_record'])
        self.assertEqual(preview['execution_queue_record']['state'], 'previewed')
        self.assertFalse(preview['execution_queue_record']['settlement_claimed'])
        queue_path = self.capsule_dir / 'payout_plan_preview_queue.json'
        self.assertTrue(queue_path.exists())
        queue_payload = json.loads(queue_path.read_text())
        self.assertEqual(len(queue_payload['payout_plan_previews']), 1)
        queue_summary = treasury.payout_plan_preview_queue_summary(self.org_id)
        self.assertEqual(queue_summary['total'], 1)
        self.assertEqual(queue_summary['execution_ready'], 1)

    def test_missing_org_fails_cleanly(self):
        with self.assertRaises(SystemExit) as ctx:
            treasury.load_wallets(f'org_missing_{uuid.uuid4().hex[:8]}')
        self.assertIn('is not initialized', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
