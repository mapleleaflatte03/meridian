#!/usr/bin/env python3
import importlib.util
import json
import os
import shutil
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCOUNTING_SERVICE_PY = os.path.join(ROOT, 'accounting_service.py')


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AccountingServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.capsules_dir = os.path.join(self.root, 'capsules')
        self.legacy_dir = os.path.join(self.root, 'economy')
        os.makedirs(self.capsules_dir, exist_ok=True)
        os.makedirs(self.legacy_dir, exist_ok=True)

        self._orig_cwd = os.getcwd()
        os.chdir(self.root)
        self.service = _load_module(ACCOUNTING_SERVICE_PY, 'accounting_service_test_module')
        self._orig_capsule_path = self.service.capsule_path
        self.service.capsule_path = self._capsule_path

    def tearDown(self):
        self.service.capsule_path = self._orig_capsule_path
        os.chdir(self._orig_cwd)
        self.tmp.cleanup()

    def _capsule_path(self, org_id, filename):
        base = self.legacy_dir if org_id is None else os.path.join(self.capsules_dir, org_id)
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, filename)

    def _write_ledger(self, org_id, payload):
        path = self._capsule_path(org_id, 'ledger.json')
        with open(path, 'w') as f:
            json.dump(payload, f, indent=2)

    def _read_json(self, org_id, filename):
        with open(self._capsule_path(org_id, filename)) as f:
            return json.load(f)

    def test_snapshot_backfills_owner_capital_from_treasury(self):
        org_id = 'org_alpha'
        self._write_ledger(org_id, {
            'treasury': {
                'cash_usd': 10.0,
                'reserve_floor_usd': 5.0,
                'owner_capital_contributed_usd': 2.0,
                'owner_draws_usd': 0.0,
            }
        })
        with open(self._capsule_path(org_id, 'owner_ledger.json'), 'w') as f:
            json.dump({
                'capital_contributed_usd': 0.0,
                'expenses_paid_usd': 0.0,
                'reimbursements_received_usd': 0.0,
                'draws_taken_usd': 0.0,
                'entries': [],
                '_meta': {'bound_org_id': org_id},
            }, f, indent=2)

        snap = self.service.accounting_snapshot(org_id)
        self.assertEqual(snap['bound_org_id'], org_id)
        self.assertEqual(snap['summary']['capital_contributed_usd'], 2.0)
        self.assertTrue(snap['meta']['capital_sync_backfilled'])
        self.assertEqual(snap['meta']['capital_sync_source'], 'treasury_ledger')

        saved = self._read_json(org_id, 'owner_ledger.json')
        self.assertEqual(saved['capital_contributed_usd'], 2.0)
        self.assertEqual(saved['entries'][-1]['type'], 'capital_contribution_backfill')
        self.assertEqual(saved['entries'][-1]['metadata']['target_owner_capital_usd'], 2.0)

    def test_org_isolation_keeps_ledgers_separate(self):
        org_a = 'org_a'
        org_b = 'org_b'
        self._write_ledger(org_a, {'treasury': {'cash_usd': 0.0, 'reserve_floor_usd': 5.0, 'owner_capital_contributed_usd': 0.0, 'owner_draws_usd': 0.0}})
        self._write_ledger(org_b, {'treasury': {'cash_usd': 0.0, 'reserve_floor_usd': 5.0, 'owner_capital_contributed_usd': 0.0, 'owner_draws_usd': 0.0}})

        a = self.service.contribute_capital(4.0, note='top up A', by='owner', org_id=org_a)
        b = self.service.record_owner_expense(1.5, note='expense B', by='owner', org_id=org_b)

        self.assertEqual(a['cash_after_usd'], 4.0)
        self.assertEqual(b['unreimbursed_expenses_usd'], 1.5)

        ledger_a = self._read_json(org_a, 'ledger.json')
        ledger_b = self._read_json(org_b, 'ledger.json')
        owner_a = self._read_json(org_a, 'owner_ledger.json')
        owner_b = self._read_json(org_b, 'owner_ledger.json')

        self.assertEqual(ledger_a['treasury']['cash_usd'], 4.0)
        self.assertEqual(ledger_b['treasury']['cash_usd'], 0.0)
        self.assertEqual(owner_a['capital_contributed_usd'], 4.0)
        self.assertEqual(owner_b['expenses_paid_usd'], 1.5)
        self.assertNotEqual(owner_a['entries'], owner_b['entries'])

    def test_accounting_snapshot_structure_and_computations(self):
        org_id = 'org_snapshot_test'

        self._write_ledger(org_id, {
            'treasury': {
                'cash_usd': 50.0,
                'reserve_floor_usd': 10.0,
                'owner_capital_contributed_usd': 20.0,
                'owner_draws_usd': 5.0,
            }
        })

        entries = [{'type': f'dummy_{i}'} for i in range(25)]
        with open(self._capsule_path(org_id, 'owner_ledger.json'), 'w') as f:
            json.dump({
                'capital_contributed_usd': 20.0,
                'expenses_paid_usd': 15.0,
                'reimbursements_received_usd': 5.0,
                'draws_taken_usd': 5.0,
                'entries': entries,
                'owner': 'Test Owner',
                '_meta': {'bound_org_id': org_id, 'custom_meta': 'value'},
            }, f, indent=2)

        snap = self.service.accounting_snapshot(org_id)

        self.assertEqual(snap['bound_org_id'], org_id)
        self.assertEqual(snap['management_mode'], 'capsule_owned_service')
        self.assertTrue(snap['mutation_enabled'])
        self.assertEqual(snap['storage_model'], 'capsule_owned_owner_ledger')
        self.assertEqual(snap['boundary_name'], 'accounting')
        self.assertEqual(snap['identity_model'], 'session')

        self.assertTrue(snap['canonical_path'].endswith('owner_ledger.json'))
        self.assertTrue(snap['treasury_path'].endswith('ledger.json'))

        self.assertIn('/api/accounting/expense', snap['mutation_paths'])
        self.assertIn('/api/accounting/reimburse', snap['mutation_paths'])
        self.assertIn('/api/accounting/draw', snap['mutation_paths'])

        self.assertEqual(snap['summary']['capital_contributed_usd'], 20.0)
        self.assertEqual(snap['summary']['expenses_paid_usd'], 15.0)
        self.assertEqual(snap['summary']['reimbursements_received_usd'], 5.0)
        self.assertEqual(snap['summary']['draws_taken_usd'], 5.0)
        self.assertEqual(snap['summary']['unreimbursed_expenses_usd'], 10.0)
        self.assertEqual(snap['summary']['entry_count'], 25)

        self.assertEqual(snap['owner'], 'Test Owner')
        self.assertEqual(snap['meta']['custom_meta'], 'value')

        self.assertEqual(len(snap['entries_tail']), 20)
        self.assertEqual(snap['entries_tail'][0]['type'], 'dummy_5')
        self.assertEqual(snap['entries_tail'][-1]['type'], 'dummy_24')

    def test_journal_behavior_records_all_flows(self):
        org_id = 'org_journal'
        self._write_ledger(org_id, {
            'treasury': {
                'cash_usd': 12.0,
                'reserve_floor_usd': 5.0,
                'owner_capital_contributed_usd': 0.0,
                'owner_draws_usd': 0.0,
            }
        })

        self.service.contribute_capital(3.0, note='seed capital', by='owner', org_id=org_id)
        self.service.record_owner_expense(1.0, note='paperwork', by='owner', org_id=org_id)
        self.service.reimburse_owner(0.5, note='paperwork reimbursement', by='owner', org_id=org_id)
        self.service.take_owner_draw(2.0, note='distribution', by='owner', org_id=org_id)

        owner = self._read_json(org_id, 'owner_ledger.json')
        tx_path = self._capsule_path(org_id, 'transactions.jsonl')
        with open(tx_path) as f:
            tx_lines = [json.loads(line) for line in f if line.strip()]

        self.assertEqual(
            [entry['type'] for entry in owner['entries'][:4]],
            ['capital_contribution', 'owner_expense', 'reimbursement', 'owner_draw'],
        )
        self.assertEqual(
            [entry['type'] for entry in tx_lines[:4]],
            ['treasury_deposit', 'owner_expense_recorded', 'treasury_withdraw', 'treasury_withdraw'],
        )
        self.assertEqual(owner['capital_contributed_usd'], 3.0)
        self.assertEqual(owner['expenses_paid_usd'], 1.0)
        self.assertEqual(owner['reimbursements_received_usd'], 0.5)
        self.assertEqual(owner['draws_taken_usd'], 2.0)

        ledger = self._read_json(org_id, 'ledger.json')
        self.assertAlmostEqual(ledger['treasury']['cash_usd'], 12.5, places=2)
        self.assertAlmostEqual(ledger['treasury']['owner_capital_contributed_usd'], 3.0, places=2)
        self.assertAlmostEqual(ledger['treasury']['owner_draws_usd'], 2.5, places=2)

    def test_contribute_capital(self):
        org_id = 'org_contribute'
        self._write_ledger(org_id, {
            'treasury': {
                'cash_usd': 5.0,
                'reserve_floor_usd': 10.0,
                'owner_capital_contributed_usd': 0.0,
            }
        })

        # We start with default empty owner ledger.

        result = self.service.contribute_capital(15.0, note='initial capital', by='owner_user', org_id=org_id)

        self.assertEqual(result['amount_usd'], 15.0)
        self.assertEqual(result['cash_after_usd'], 20.0)
        self.assertEqual(result['reserve_floor_usd'], 10.0)
        self.assertEqual(result['entry_count'], 1)

        owner = self._read_json(org_id, 'owner_ledger.json')
        self.assertEqual(owner['capital_contributed_usd'], 15.0)
        self.assertEqual(len(owner['entries']), 1)
        self.assertEqual(owner['entries'][0]['type'], 'capital_contribution')
        self.assertEqual(owner['entries'][0]['amount_usd'], 15.0)
        self.assertEqual(owner['entries'][0]['note'], 'initial capital')
        self.assertEqual(owner['entries'][0]['by'], 'owner_user')

        ledger = self._read_json(org_id, 'ledger.json')
        self.assertEqual(ledger['treasury']['cash_usd'], 20.0)
        self.assertEqual(ledger['treasury']['owner_capital_contributed_usd'], 15.0)
        self.assertIn('updatedAt', ledger)

        tx_path = self._capsule_path(org_id, 'transactions.jsonl')
        with open(tx_path) as f:
            tx_lines = [json.loads(line) for line in f if line.strip()]

        self.assertEqual(len(tx_lines), 1)
        self.assertEqual(tx_lines[0]['type'], 'treasury_deposit')
        self.assertEqual(tx_lines[0]['deposit_type'], 'owner_capital')
        self.assertEqual(tx_lines[0]['amount_usd'], 15.0)
        self.assertEqual(tx_lines[0]['cash_after'], 20.0)
        self.assertEqual(tx_lines[0]['note'], 'initial capital')
        self.assertEqual(tx_lines[0]['by'], 'owner_user')

    def test_contribute_capital_invalid_amount(self):
        org_id = 'org_invalid_contribute'
        with self.assertRaisesRegex(ValueError, 'Capital contribution must be greater than 0'):
            self.service.contribute_capital(0.0, org_id=org_id)

        with self.assertRaisesRegex(ValueError, 'Capital contribution must be greater than 0'):
            self.service.contribute_capital(-5.0, org_id=org_id)


if __name__ == '__main__':
    unittest.main()
