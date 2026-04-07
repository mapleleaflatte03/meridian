#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import shutil
import unittest
import uuid


ROOT = pathlib.Path(__file__).resolve().parents[2]
ECONOMY_DIR = ROOT / 'economy'
CAPSULES_DIR = ROOT / 'capsules'


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ensure_legacy_economy_state():
    ECONOMY_DIR.mkdir(parents=True, exist_ok=True)
    ledger_path = ECONOMY_DIR / 'ledger.json'
    revenue_path = ECONOMY_DIR / 'revenue.json'
    tx_path = ECONOMY_DIR / 'transactions.jsonl'

    if not ledger_path.exists():
        ledger_path.write_text(json.dumps({
            'updatedAt': '2026-03-21T00:00:00Z',
            'epoch': {'started_at': '2026-03-21T00:00:00Z'},
            'treasury': {
                'cash_usd': 0.0,
                'reserve_floor_usd': 0.0,
                'total_revenue_usd': 0.0,
                'support_received_usd': 0.0,
                'owner_capital_contributed_usd': 0.0,
                'expenses_recorded_usd': 0.0,
                'owner_draws_usd': 0.0,
            },
            'agents': {
                'atlas': {
                    'name': 'Atlas',
                    'role': 'analyst',
                    'reputation_units': 50,
                    'authority_units': 50,
                    'probation': False,
                    'zero_authority': False,
                    'status': 'active',
                },
                'sentinel': {
                    'name': 'Sentinel',
                    'role': 'verifier',
                    'reputation_units': 50,
                    'authority_units': 50,
                    'probation': False,
                    'zero_authority': False,
                    'status': 'active',
                },
                'forge': {
                    'name': 'Forge',
                    'role': 'builder',
                    'reputation_units': 50,
                    'authority_units': 50,
                    'probation': False,
                    'zero_authority': False,
                    'status': 'active',
                },
            },
        }, indent=2))

    if not revenue_path.exists():
        revenue_path.write_text(json.dumps({
            'clients': {},
            'orders': {},
            'receivables_usd': 0.0,
            'updatedAt': '2026-03-21T00:00:00Z',
        }, indent=2))

    if not tx_path.exists():
        tx_path.write_text('')


class ExternalSettlementTests(unittest.TestCase):
    def setUp(self):
        _ensure_legacy_economy_state()
        self.org_id = f'org_settle_{uuid.uuid4().hex[:8]}'
        self.capsule_mod = _load_module(ROOT / 'kernel' / 'capsule.py', 'kernel_capsule_external_settle')
        self.revenue_mod = _load_module(ROOT / 'economy' / 'revenue.py', 'kernel_revenue_external_settle')
        self.capsule_mod.init_capsule(self.org_id)
        self.capsule_dir = CAPSULES_DIR / self.org_id

        self.ledger_path = self.capsule_dir / 'ledger.json'
        self.revenue_path = self.capsule_dir / 'revenue.json'
        self.tx_path = self.capsule_dir / 'transactions.jsonl'

        ledger = json.loads(self.ledger_path.read_text())
        ledger['updatedAt'] = '2026-03-21T00:00:00Z'
        ledger['epoch']['started_at'] = '2026-03-21T00:00:00Z'
        self.ledger_path.write_text(json.dumps(ledger, indent=2))
        self.revenue_path.write_text(json.dumps({
            'clients': {},
            'orders': {},
            'receivables_usd': 0.0,
            'updatedAt': '2026-03-21T00:00:00Z',
        }, indent=2))
        self.tx_path.write_text('')

        self.default_ledger_before = json.loads((ECONOMY_DIR / 'ledger.json').read_text())
        self.default_tx_before = (ECONOMY_DIR / 'transactions.jsonl').read_text()

    def tearDown(self):
        shutil.rmtree(self.capsule_dir, ignore_errors=True)

    def _load_capsule_ledger(self):
        return json.loads(self.ledger_path.read_text())

    def _load_capsule_revenue(self):
        return json.loads(self.revenue_path.read_text())

    def _load_capsule_txs(self):
        return [
            json.loads(line)
            for line in self.tx_path.read_text().splitlines()
            if line.strip()
        ]

    def test_external_customer_payment_is_idempotent_and_capsule_scoped(self):
        result = self.revenue_mod.record_external_customer_payment(
            'capsule-product',
            2.5,
            payment_key='ref:pay_123',
            payment_ref='pay_123',
            client_name='Capsule Customer',
            client_contact='capsule@example.com',
            tx_hash='0xabc',
            payment_source='integration_test',
            org_id=self.org_id,
        )
        self.assertFalse(result['duplicate'])

        second = self.revenue_mod.record_external_customer_payment(
            'capsule-product',
            2.5,
            payment_key='ref:pay_123',
            payment_ref='pay_123',
            client_name='Capsule Customer',
            client_contact='capsule@example.com',
            tx_hash='0xabc',
            payment_source='integration_test',
            org_id=self.org_id,
        )
        self.assertTrue(second['duplicate'])
        self.assertEqual(second['order_id'], result['order_id'])

        ledger = self._load_capsule_ledger()
        revenue = self._load_capsule_revenue()
        txs = self._load_capsule_txs()

        self.assertAlmostEqual(ledger['treasury']['cash_usd'], 2.5, places=2)
        self.assertAlmostEqual(ledger['treasury']['total_revenue_usd'], 2.5, places=2)
        self.assertIn('ref:pay_123', ledger['treasury']['processed_payment_keys'])
        self.assertEqual(revenue['orders'][result['order_id']]['status'], 'paid')

        evidence = self.revenue_mod.find_customer_payment_evidence(
            payment_ref='pay_123',
            min_amount_usd=2.5,
            org_id=self.org_id,
        )
        self.assertIsNotNone(evidence)
        self.assertEqual(evidence['payment_key'], 'ref:pay_123')

        customer_txs = [tx for tx in txs if tx.get('type') == 'customer_payment']
        self.assertEqual(len(customer_txs), 1)
        self.assertEqual((ECONOMY_DIR / 'transactions.jsonl').read_text(), self.default_tx_before)
        self.assertEqual(
            json.loads((ECONOMY_DIR / 'ledger.json').read_text())['treasury']['cash_usd'],
            self.default_ledger_before['treasury']['cash_usd'],
        )

    def test_support_contribution_does_not_create_customer_revenue(self):
        result = self.revenue_mod.record_external_support_contribution(
            1.75,
            payment_key='support:abc',
            payment_ref='support_abc',
            supporter_name='Backer',
            supporter_contact='supporter@example.com',
            payment_source='integration_test',
            org_id=self.org_id,
        )
        self.assertFalse(result['duplicate'])

        second = self.revenue_mod.record_external_support_contribution(
            1.75,
            payment_key='support:abc',
            payment_ref='support_abc',
            supporter_name='Backer',
            supporter_contact='supporter@example.com',
            payment_source='integration_test',
            org_id=self.org_id,
        )
        self.assertTrue(second['duplicate'])

        ledger = self._load_capsule_ledger()
        txs = self._load_capsule_txs()
        self.assertAlmostEqual(ledger['treasury']['cash_usd'], 1.75, places=2)
        self.assertAlmostEqual(ledger['treasury']['support_received_usd'], 1.75, places=2)
        self.assertEqual(ledger['treasury'].get('total_revenue_usd', 0.0), 0.0)
        support_txs = [tx for tx in txs if tx.get('type') == 'support_contribution']
        self.assertEqual(len(support_txs), 1)


if __name__ == '__main__':
    unittest.main()
