#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest
import uuid


ROOT = pathlib.Path(__file__).resolve().parents[2]
ECONOMY_DIR = ROOT / 'economy'
CAPSULES_DIR = ROOT / 'capsules'


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    return result.stdout.strip(), result.returncode, result.stderr.strip()


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


class CapsuleScopingTests(unittest.TestCase):
    def setUp(self):
        _ensure_legacy_economy_state()
        self.org_id = f'org_capsule_test_{uuid.uuid4().hex[:8]}'
        self.capsule_dir = CAPSULES_DIR / self.org_id
        self.spec = importlib.util.spec_from_file_location('kernel_capsule_test', ROOT / 'kernel' / 'capsule.py')
        self.capsule = importlib.util.module_from_spec(self.spec)
        self.spec.loader.exec_module(self.capsule)
        self.capsule.init_capsule(self.org_id)

        ledger_path = pathlib.Path(self.capsule.capsule_path(self.org_id, 'ledger.json'))
        revenue_path = pathlib.Path(self.capsule.capsule_path(self.org_id, 'revenue.json'))
        tx_path = pathlib.Path(self.capsule.capsule_path(self.org_id, 'transactions.jsonl'))

        ledger = json.loads(ledger_path.read_text())
        ledger['updatedAt'] = '2026-03-21T00:00:00Z'
        ledger['epoch']['started_at'] = '2026-03-21T00:00:00Z'
        ledger['agents'] = {
            'atlas': {'name': 'Atlas', 'role': 'analyst', 'reputation_units': 50, 'authority_units': 50, 'probation': False, 'zero_authority': False, 'status': 'active'},
            'sentinel': {'name': 'Sentinel', 'role': 'verifier', 'reputation_units': 50, 'authority_units': 50, 'probation': False, 'zero_authority': False, 'status': 'active'},
        }
        ledger_path.write_text(json.dumps(ledger, indent=2))
        revenue_path.write_text(json.dumps({'clients': {}, 'orders': {}, 'receivables_usd': 0.0, 'updatedAt': '2026-03-21T00:00:00Z'}, indent=2))
        tx_path.write_text('')

        self.default_ledger_before = json.loads((ECONOMY_DIR / 'ledger.json').read_text())
        self.default_tx_before = (ECONOMY_DIR / 'transactions.jsonl').read_text()

    def tearDown(self):
        shutil.rmtree(self.capsule_dir, ignore_errors=True)

    def test_sanctions_apply_writes_only_to_capsule(self):
        out, rc, err = run([
            'python3', 'economy/sanctions.py', 'apply',
            '--org_id', self.org_id,
            '--agent', 'sentinel',
            '--type', 'probation',
            '--note', 'capsule test',
        ])
        self.assertEqual(rc, 0, err or out)
        ledger = json.loads((self.capsule_dir / 'ledger.json').read_text())
        self.assertTrue(ledger['agents']['sentinel']['probation'])
        default_ledger = json.loads((ECONOMY_DIR / 'ledger.json').read_text())
        self.assertFalse(default_ledger['agents']['sentinel'].get('probation', False))

    def test_revenue_paid_event_credits_only_capsule_treasury(self):
        out, rc, err = run([
            'python3', 'economy/revenue.py', 'client', 'add',
            '--org_id', self.org_id,
            '--name', 'Capsule Client',
            '--contact', 'capsule@test',
        ])
        self.assertEqual(rc, 0, err or out)
        client_id = out.split()[2]

        out, rc, err = run([
            'python3', 'economy/revenue.py', 'order', 'create',
            '--org_id', self.org_id,
            '--client', client_id,
            '--product', 'capsule-product',
            '--amount', '1.25',
        ])
        self.assertEqual(rc, 0, err or out)
        order_id = out.split()[2]

        for _ in range(5):
            out, rc, err = run([
                'python3', 'economy/revenue.py', 'order', 'advance',
                '--org_id', self.org_id,
                order_id,
            ])
            self.assertEqual(rc, 0, err or out)

        ledger = json.loads((self.capsule_dir / 'ledger.json').read_text())
        self.assertAlmostEqual(ledger['treasury']['cash_usd'], 1.25, places=2)
        default_ledger = json.loads((ECONOMY_DIR / 'ledger.json').read_text())
        self.assertEqual(default_ledger['treasury']['cash_usd'], self.default_ledger_before['treasury']['cash_usd'])
        self.assertEqual((ECONOMY_DIR / 'transactions.jsonl').read_text(), self.default_tx_before)

        tx_lines = [json.loads(line) for line in (self.capsule_dir / 'transactions.jsonl').read_text().splitlines() if line.strip()]
        order_created = [entry for entry in tx_lines if entry.get('type') == 'order_created']
        customer_payments = [entry for entry in tx_lines if entry.get('type') == 'customer_payment']
        self.assertEqual(len(order_created), 1)
        self.assertEqual(len(customer_payments), 1)

    def test_authority_check_reads_capsule_ledger(self):
        ledger_path = self.capsule_dir / 'ledger.json'
        ledger = json.loads(ledger_path.read_text())
        ledger['agents']['atlas']['authority_units'] = 10
        ledger_path.write_text(json.dumps(ledger, indent=2))

        out, rc, _ = run([
            'python3', 'economy/authority.py', 'check',
            '--org_id', self.org_id,
            '--agent', 'atlas',
            '--action', 'lead',
        ])
        self.assertEqual(rc, 1, out)
        self.assertIn('below lead threshold', out)

    def test_explicit_founding_org_alias_resolves_to_legacy_economy(self):
        founding_org = 'org_b7d95bae'
        self.capsule.register_capsule_alias(founding_org, str(ECONOMY_DIR))
        self.assertEqual(
            pathlib.Path(self.capsule.capsule_path(founding_org, 'ledger.json')),
            ECONOMY_DIR / 'ledger.json',
        )

    def test_uninitialized_org_fails_cleanly(self):
        missing_org = f'org_missing_{uuid.uuid4().hex[:8]}'
        cases = [
            ['python3', 'economy/authority.py', 'show', '--org_id', missing_org],
            ['python3', 'economy/revenue.py', 'summary', '--org_id', missing_org],
            ['python3', 'economy/sanctions.py', 'show', '--org_id', missing_org],
        ]
        for cmd in cases:
            out, rc, err = run(cmd)
            message = out or err
            self.assertNotEqual(rc, 0, cmd)
            self.assertIn('is not initialized', message)


if __name__ == '__main__':
    unittest.main()
