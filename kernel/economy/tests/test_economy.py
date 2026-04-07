#!/usr/bin/env python3
"""
Control tests for the Meridian kernel economy.
Tests:
  1. Accepted output raises score
  2. Weak output triggers sanction
  3. Zero-authority agent cannot lead
  4. Paid event increases treasury

Run: python3 -m unittest discover -s economy/tests -p 'test_*.py'
"""
import json, os, shutil, subprocess, tempfile, unittest

WORKSPACE    = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
ECONOMY_DIR  = os.path.join(WORKSPACE, 'economy')
LEDGER_PATH  = os.path.join(ECONOMY_DIR, 'ledger.json')
TX_PATH      = os.path.join(ECONOMY_DIR, 'transactions.jsonl')
REVENUE_PATH = os.path.join(ECONOMY_DIR, 'revenue.json')


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=WORKSPACE)
    return r.stdout.strip(), r.returncode, r.stderr.strip()


def ensure_legacy_economy_state():
    os.makedirs(ECONOMY_DIR, exist_ok=True)
    if not os.path.exists(LEDGER_PATH):
        with open(LEDGER_PATH, 'w') as f:
            json.dump({
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
            }, f, indent=2)
    if not os.path.exists(TX_PATH):
        with open(TX_PATH, 'w') as f:
            f.write('')
    if not os.path.exists(REVENUE_PATH):
        with open(REVENUE_PATH, 'w') as f:
            json.dump({
                'clients': {},
                'orders': {},
                'receivables_usd': 0.0,
                'updatedAt': '2026-03-21T00:00:00Z',
            }, f, indent=2)


def load_ledger():
    with open(LEDGER_PATH) as f:
        return json.load(f)


def load_txs():
    with open(TX_PATH) as f:
        return [json.loads(l) for l in f if l.strip()]


def snap(agent_id):
    d = load_ledger()['agents'][agent_id]
    return d['reputation_units'], d['authority_units']


def restore_score(agent_id, rep, auth):
    current = snap(agent_id)
    rep_d   = rep  - current[0]
    auth_d  = auth - current[1]
    if rep_d != 0 or auth_d != 0:
        run(['python3', 'economy/score.py', 'record',
             '--agent', agent_id, '--event', 'test_restore',
             '--rep', str(rep_d), '--auth', str(auth_d), '--note', 'test cleanup'])


class TestEconomy(unittest.TestCase):
    def setUp(self):
        ensure_legacy_economy_state()
        self._state_backup_dir = tempfile.mkdtemp(prefix='meridian-econ-test-')
        self._state_files = [LEDGER_PATH, TX_PATH, REVENUE_PATH]
        for path in self._state_files:
            shutil.copy2(path, os.path.join(self._state_backup_dir, os.path.basename(path)))

    def tearDown(self):
        for path in self._state_files:
            backup = os.path.join(self._state_backup_dir, os.path.basename(path))
            shutil.copy2(backup, path)
        shutil.rmtree(self._state_backup_dir, ignore_errors=True)

    def test_1_accepted_output_raises_score(self):
        """Accepted output raises REP and AUTH."""
        rep0, auth0 = snap('atlas')
        if rep0 >= 95 or auth0 >= 95:
            run(['python3', 'economy/score.py', 'record',
                 '--agent', 'atlas', '--event', 'test_setup',
                 '--rep', '-20', '--auth', '-20', '--note', 'ctrl-test create headroom'])
            rep0, auth0 = snap('atlas')
        try:
            out, rc, _ = run(['python3', 'economy/score.py', 'record',
                              '--agent', 'atlas', '--event', 'test_accepted',
                              '--rep', '10', '--auth', '8', '--note', 'ctrl-test accepted output'])
            self.assertEqual(rc, 0, f"score.py record should exit 0: {out}")
            rep1, auth1 = snap('atlas')
            self.assertGreater(rep1, rep0, f"REP should increase: {rep0}->{rep1}")
            self.assertGreater(auth1, auth0, f"AUTH should increase: {auth0}->{auth1}")
        finally:
            restore_score('atlas', rep0, auth0)

    def test_2_weak_output_sanction(self):
        """Weak output triggers sanction and records transaction."""
        tx_before = len(load_txs())
        try:
            out, rc, _ = run(['python3', 'economy/sanctions.py', 'apply',
                              '--agent', 'sentinel', '--type', 'lead_ban',
                              '--note', 'ctrl-test weak output'])
            self.assertEqual(rc, 0, f"sanctions.py apply should exit 0: {out}")
            self.assertIn('SANCTION APPLIED', out)

            txs_after = load_txs()
            sanction_txs = [tx for tx in txs_after[tx_before:]
                            if tx.get('type') == 'sanction_applied' and tx.get('agent') == 'sentinel']
            self.assertGreater(len(sanction_txs), 0, "sanction_applied should be in transactions.jsonl")
        finally:
            run(['python3', 'economy/sanctions.py', 'lift',
                 '--agent', 'sentinel', '--type', 'lead_ban', '--note', 'ctrl-test cleanup'])
            d = load_ledger()['agents']['sentinel']
            self.assertFalse(d.get('lead_ban'), "lead_ban should be cleared after lift")

    def test_3_zero_authority_cannot_lead(self):
        """Zero-authority agent is blocked from leading and AUTH gain."""
        rep0, auth0 = snap('forge')
        try:
            run(['python3', 'economy/sanctions.py', 'apply',
                 '--agent', 'forge', '--type', 'zero_authority', '--note', 'ctrl-test zero_auth'])

            out, rc, _ = run(['python3', 'economy/authority.py', 'check',
                              '--agent', 'forge', '--action', 'lead'])
            self.assertEqual(rc, 1, f"authority check should exit 1 (blocked): {out}")
            self.assertIn('BLOCKED', out)

            out_lead, _, _ = run(['python3', 'economy/authority.py', 'sprint-lead'])
            self.assertTrue('forge' not in out_lead.lower() or 'NONE' in out_lead,
                            f"zero_authority forge should not be sprint lead: {out_lead}")

            forge_auth_before = snap('forge')[1]
            run(['python3', 'economy/score.py', 'record',
                 '--agent', 'forge', '--event', 'test_auth_block',
                 '--auth', '10', '--note', 'ctrl-test should be blocked'])
            self.assertEqual(snap('forge')[1], forge_auth_before, "AUTH gain should be blocked under zero_authority")
        finally:
            run(['python3', 'economy/sanctions.py', 'lift',
                 '--agent', 'forge', '--type', 'zero_authority', '--note', 'ctrl-test cleanup'])
            restore_score('forge', rep0, auth0)

    def test_4_paid_event_increases_treasury(self):
        """Paid event via revenue.py increases treasury cash."""
        cash_before = load_ledger()['treasury']['cash_usd']
        tx_before = len(load_txs())
        test_amount = 0.01
        created_client_id = None
        created_order_id = None
        try:
            out, rc, _ = run(['python3', 'economy/revenue.py', 'client', 'add',
                              '--name', 'CtrlTestClient', '--contact', 'test@ctrl'])
            self.assertEqual(rc, 0, f"client add should exit 0: {out}")
            for word in out.split():
                if len(word) == 8 and all(c in '0123456789abcdef' for c in word):
                    created_client_id = word
                    break
            self.assertIsNotNone(created_client_id, f"Should find client ID in output: {out}")

            out, rc, _ = run(['python3', 'economy/revenue.py', 'order', 'create',
                              '--client', created_client_id,
                              '--product', 'ctrl-test-product',
                              '--amount', str(test_amount),
                              '--note', 'control test order'])
            self.assertEqual(rc, 0, f"order create should exit 0: {out}")
            for word in out.split():
                if len(word) == 8 and all(c in '0123456789abcdef' for c in word):
                    created_order_id = word
                    break
            self.assertIsNotNone(created_order_id, f"Should find order ID in output: {out}")

            for state in ['accepted', 'in_progress', 'delivered', 'invoiced', 'paid']:
                out, rc, _ = run(['python3', 'economy/revenue.py', 'order', 'advance',
                                  created_order_id])
                self.assertEqual(rc, 0, f"advance to {state} should exit 0: {out}")

            cash_after = load_ledger()['treasury']['cash_usd']
            self.assertGreater(cash_after, cash_before, f"Treasury cash should increase: ${cash_before}->${cash_after}")
            self.assertAlmostEqual(cash_after - cash_before, test_amount, places=2,
                                   msg=f"Should deposit ${test_amount}: delta=${cash_after - cash_before}")
            txs = load_txs()[tx_before:]
            paid_txs = [
                tx for tx in txs
                if tx.get('type') == 'customer_payment'
                and tx.get('order_id') == created_order_id
                and tx.get('product') == 'ctrl-test-product'
            ]
            self.assertGreater(len(paid_txs), 0, "customer_payment transaction should exist")
        finally:
            if created_order_id:
                run(['python3', 'economy/score.py', 'treasury', 'withdraw',
                     '--amount', str(test_amount), '--type', 'expense',
                     '--note', 'ctrl-test cleanup'])


if __name__ == '__main__':
    unittest.main()
