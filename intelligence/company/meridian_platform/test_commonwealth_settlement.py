#!/usr/bin/env python3
"""RED tests for Inter-Institution Treasury & Settlement Protocol (Slice 2).

Tests the commonwealth settlement lifecycle (prepare -> commit -> refund),
ensuring proper cryptographic proof receipt validation and treasury budget
reservation/commit/release loops.

Reference: RFC-0006 (Inter-Institution Settlement)
"""
import os
import sys
import unittest
from unittest import mock

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

from commonwealth import (
    _sha256_hex,
    prepare_settlement,
    commit_settlement,
    refund_settlement,
    get_settlement,
)


class CommonwealthSettlementProtocolTest(unittest.TestCase):
    def setUp(self):
        self.org_id = 'org_test_settlement'
        self.peer_org_id = 'org_peer_remote'
        self.agent_id = 'agent_test_123'

        # Patch the file-based store so tests run purely in memory
        self.store = {'settlements': {}}
        self.load_patcher = mock.patch('commonwealth._load_settlements', return_value=self.store)
        self.save_patcher = mock.patch('commonwealth._save_settlements')
        self.mock_load = self.load_patcher.start()
        self.mock_save = self.save_patcher.start()

        # Helper to simulate _save_settlements updating our in-memory store
        def fake_save(data, org_id):
            self.store.update(data)
        self.mock_save.side_effect = fake_save

    def tearDown(self):
        self.load_patcher.stop()
        self.save_patcher.stop()

    def test_prepare_settlement_calculates_split_and_receipt_hash(self):
        result = prepare_settlement(
            self.org_id,
            peer_org_id=self.peer_org_id,
            agent_id=self.agent_id,
            task_description='Cross-institution task',
            amount_usd=100.0,
            royalty_rate=0.10,
            reservation_id='resv_treasury_1',
        )

        self.assertEqual(result['status'], 'prepared')
        self.assertIn('settlement_id', result)
        self.assertIn('receipt_hash', result)

        split = result['split']
        self.assertEqual(split['total_usd'], 100.0)
        self.assertEqual(split['worker_usd'], 90.0)
        self.assertEqual(split['royalty_usd'], 10.0)

        expected_hash = _sha256_hex(
            result['settlement_id'],
            self.org_id,
            self.peer_org_id,
            self.agent_id,
            '100.0'
        )
        self.assertEqual(result['receipt_hash'], expected_hash)

        record = get_settlement(self.org_id, result['settlement_id'])
        self.assertIsNotNone(record)
        self.assertEqual(record['status'], 'prepared')
        self.assertEqual(record['reservation_id'], 'resv_treasury_1')

    def test_prepare_validates_inputs(self):
        with self.assertRaisesRegex(ValueError, 'amount_usd must be positive'):
            prepare_settlement(self.org_id, peer_org_id='p', agent_id='a', task_description='t', amount_usd=-10.0)

        with self.assertRaisesRegex(ValueError, 'royalty_rate must be in'):
            prepare_settlement(self.org_id, peer_org_id='p', agent_id='a', task_description='t', amount_usd=10.0, royalty_rate=1.5)

    def test_commit_settlement_with_valid_proof_receipt(self):
        # 1. Prepare
        prep = prepare_settlement(
            self.org_id,
            peer_org_id=self.peer_org_id,
            agent_id=self.agent_id,
            task_description='Task',
            amount_usd=50.0,
        )
        sid = prep['settlement_id']
        expected_receipt = prep['receipt_hash']

        # 2. Commit with the EXACT matching receipt
        commit = commit_settlement(
            self.org_id,
            sid,
            proof_receipt=expected_receipt,
            proof_receipt_refs=[expected_receipt],  # The kernel proof tree contains it
        )

        self.assertEqual(commit['status'], 'committed')
        self.assertTrue(commit['proof_receipt_valid'])
        self.assertEqual(commit['proof_receipt'], expected_receipt)

        record = get_settlement(self.org_id, sid)
        self.assertEqual(record['status'], 'committed')
        self.assertIsNotNone(record['committed_at'])

    def test_commit_settlement_rejects_invalid_proof_receipt(self):
        prep = prepare_settlement(
            self.org_id, peer_org_id=self.peer_org_id, agent_id=self.agent_id, task_description='T', amount_usd=50.0
        )
        sid = prep['settlement_id']

        bad_receipt = _sha256_hex('tampered')

        with self.assertRaisesRegex(ValueError, 'does not match settlement receipt hash or any live proof anchor'):
            commit_settlement(
                self.org_id,
                sid,
                proof_receipt=bad_receipt,
                proof_receipt_refs=[prep['receipt_hash']],
            )

        record = get_settlement(self.org_id, sid)
        self.assertEqual(record['status'], 'prepared')  # Unchanged

    def test_refund_settlement_releases_reservation(self):
        prep = prepare_settlement(
            self.org_id, peer_org_id=self.peer_org_id, agent_id=self.agent_id, task_description='T', amount_usd=50.0, reservation_id='resv_2'
        )
        sid = prep['settlement_id']

        refund = refund_settlement(
            self.org_id,
            sid,
            reason='Task cancelled by peer',
            court_decision_ref='case_999'
        )

        self.assertEqual(refund['status'], 'refunded')
        self.assertEqual(refund['refund_reason'], 'Task cancelled by peer')
        self.assertEqual(refund['court_decision_ref'], 'case_999')

        record = get_settlement(self.org_id, sid)
        self.assertEqual(record['status'], 'refunded')
        self.assertEqual(record['refund_reason'], 'Task cancelled by peer')

    def test_commit_idempotency(self):
        prep = prepare_settlement(
            self.org_id, peer_org_id=self.peer_org_id, agent_id=self.agent_id, task_description='T', amount_usd=50.0
        )
        sid = prep['settlement_id']
        receipt = prep['receipt_hash']

        commit1 = commit_settlement(self.org_id, sid, proof_receipt=receipt, proof_receipt_refs=[receipt])
        self.assertFalse(commit1.get('idempotent', False))

        # Second commit with same receipt should succeed and return idempotent=True
        commit2 = commit_settlement(self.org_id, sid, proof_receipt=receipt, proof_receipt_refs=[receipt])
        self.assertTrue(commit2['idempotent'])
        self.assertEqual(commit2['status'], 'committed')

    def test_refund_idempotency(self):
        prep = prepare_settlement(
            self.org_id, peer_org_id=self.peer_org_id, agent_id=self.agent_id, task_description='T', amount_usd=50.0
        )
        sid = prep['settlement_id']

        refund1 = refund_settlement(self.org_id, sid, reason='R1')
        self.assertFalse(refund1.get('idempotent', False))

        refund2 = refund_settlement(self.org_id, sid, reason='R2')
        self.assertTrue(refund2['idempotent'])
        # State remains from first refund
        self.assertEqual(refund2['refund_reason'], 'R1')

if __name__ == '__main__':
    unittest.main()
