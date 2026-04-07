#!/usr/bin/env python3
import importlib.util
import json
import os
import shutil
import sqlite3
import tempfile
import unittest


PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
ACCOUNTING_SERVICE_PY = os.path.join(PLATFORM_DIR, 'accounting_service.py')


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
        os.makedirs(self.capsules_dir, exist_ok=True)

        self._orig_cwd = os.getcwd()
        os.chdir(self.root)
        self.service = _load_module(ACCOUNTING_SERVICE_PY, 'live_accounting_service_test_module')
        self._orig_capsule_path = self.service.capsule_path
        self.service.capsule_path = self._capsule_path

    def tearDown(self):
        self.service.capsule_path = self._orig_capsule_path
        os.chdir(self._orig_cwd)
        self.tmp.cleanup()

    def _capsule_path(self, org_id, filename):
        base = self.capsules_dir if org_id is None else os.path.join(self.capsules_dir, org_id)
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

    def test_sqlite_mirror_recovers_when_owner_ledger_json_is_missing(self):
        org_id = 'org_sqlite'
        self._write_ledger(org_id, {
            'treasury': {
                'cash_usd': 10.0,
                'reserve_floor_usd': 5.0,
                'owner_capital_contributed_usd': 0.0,
                'owner_draws_usd': 0.0,
            }
        })

        self.service.contribute_capital(5.0, note='sqlite seed', by='owner', org_id=org_id)

        owner_path = self._capsule_path(org_id, 'owner_ledger.json')
        db_path = self.service.accounting_store.db_path_for_owner_ledger(owner_path)
        self.assertTrue(os.path.exists(db_path))

        os.remove(owner_path)
        snap = self.service.accounting_snapshot(org_id)

        with sqlite3.connect(db_path) as conn:
            owner_rows = conn.execute('SELECT COUNT(*) FROM owner_ledger').fetchone()[0]
            tx_rows = conn.execute('SELECT COUNT(*) FROM accounting_transactions').fetchone()[0]

        self.assertEqual(owner_rows, 1)
        self.assertGreaterEqual(tx_rows, 1)
        self.assertEqual(snap['db']['status'], 'present')
        self.assertEqual(snap['summary']['capital_contributed_usd'], 5.0)
        self.assertEqual(snap['entries_tail'][-1]['type'], 'capital_contribution')

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


if __name__ == '__main__':
    unittest.main()
