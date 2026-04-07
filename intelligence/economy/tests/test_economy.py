#!/usr/bin/env python3
"""
Control tests for the Meridian enforced economy.
Tests:
  1. Accepted output raises score
  2. Weak output triggers sanction
  3. Zero-authority agent cannot lead
  4. Paid event increases treasury
  5. Owner draw respects reserve floor

Run: python3 -m unittest discover -s economy/tests -p 'test_*.py'
"""
import json, os, shutil, subprocess, tempfile, unittest

WORKSPACE    = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
ECONOMY_DIR  = os.path.join(WORKSPACE, 'economy')
COMPANY_DIR  = os.path.join(WORKSPACE, 'company')
LEDGER_PATH  = os.path.join(ECONOMY_DIR, 'ledger.json')
TX_PATH      = os.path.join(ECONOMY_DIR, 'transactions.jsonl')
REVENUE_PATH = os.path.join(ECONOMY_DIR, 'revenue.json')


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=WORKSPACE)
    return r.stdout.strip(), r.returncode, r.stderr.strip()


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
        # If agent is already at cap (100), lower first to leave room for increase
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
        test_amount = 0.01  # minimal test amount
        created_client_id = None
        created_order_id = None
        try:
            # Create test client
            out, rc, _ = run(['python3', 'economy/revenue.py', 'client', 'add',
                              '--name', 'CtrlTestClient', '--contact', 'test@ctrl'])
            self.assertEqual(rc, 0, f"client add should exit 0: {out}")
            # Parse client ID from output
            for word in out.split():
                if len(word) == 8 and all(c in '0123456789abcdef' for c in word):
                    created_client_id = word
                    break
            self.assertIsNotNone(created_client_id, f"Should find client ID in output: {out}")

            # Create test order
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

            # Advance order through all states to 'paid'
            for state in ['accepted', 'in_progress', 'delivered', 'invoiced', 'paid']:
                out, rc, _ = run(['python3', 'economy/revenue.py', 'order', 'advance',
                                  created_order_id])
                self.assertEqual(rc, 0, f"advance to {state} should exit 0: {out}")

            cash_after = load_ledger()['treasury']['cash_usd']
            self.assertGreater(cash_after, cash_before, f"Treasury cash should increase: ${cash_before}->${cash_after}")
            self.assertAlmostEqual(cash_after - cash_before, test_amount, places=2,
                                   msg=f"Should deposit ${test_amount}: delta=${cash_after - cash_before}")

            # Verify paid event in transactions
            txs = load_txs()[tx_before:]
            paid_txs = [
                tx for tx in txs
                if tx.get('type') == 'customer_payment'
                and tx.get('order_id') == created_order_id
                and tx.get('product') == 'ctrl-test-product'
            ]
            self.assertGreater(len(paid_txs), 0, "customer_payment transaction should exist")
        finally:
            # Cleanup: withdraw the test amount
            if created_order_id:
                run(['python3', 'economy/score.py', 'treasury', 'withdraw',
                     '--amount', str(test_amount), '--type', 'expense',
                     '--note', 'ctrl-test cleanup'])

    def test_5_owner_draw_respects_floor(self):
        """Owner draw that would breach reserve floor is rejected."""
        ledger = load_ledger()
        cash   = ledger['treasury']['cash_usd']

        # Draw that would breach floor
        oversized = cash + 9999
        out, rc, _ = run(['python3', 'company/accounting.py', 'draw',
                          '--amount', str(oversized), '--note', 'ctrl-test breach'])
        self.assertNotEqual(rc, 0, f"Oversized draw should exit non-zero: {out}")
        self.assertTrue('floor' in out or 'available' in out or 'ERROR' in out,
                        f"Should mention reserve floor: {out}")
        self.assertEqual(load_ledger()['treasury']['cash_usd'], cash,
                         "Cash should be unchanged after rejected draw")


if __name__ == '__main__':
    unittest.main()
