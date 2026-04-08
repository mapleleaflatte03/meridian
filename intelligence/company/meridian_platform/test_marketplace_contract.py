#!/usr/bin/env python3
import pathlib
import tempfile
import unittest
from unittest import mock

from marketplace import (
    assign_bid,
    get_disputes,
    marketplace_snapshot,
    open_dispute,
    post_bid,
    resolve_dispute,
    settle_bid,
)


class MarketplaceContractTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(prefix='marketplace-contract-')
        self._patch_path = mock.patch(
            'marketplace._marketplace_path',
            side_effect=lambda org_id=None: str(
                pathlib.Path(self._tmpdir.name) / f'{org_id or "default"}_marketplace.json'
            ),
        )
        self._patch_path.start()

    def tearDown(self):
        self._patch_path.stop()
        self._tmpdir.cleanup()

    def test_settlement_split_is_deterministic_and_conserves_total(self):
        bid_id, _receipt = post_bid(
            agent_id='agent_atlas',
            task_description='compile benchmark notes',
            amount_usd=10.0,
            org_id='org_test',
        )
        assign_bid(bid_id, assigned_by='owner', org_id='org_test', reservation_id='resv_123')
        settlement_id, settlement_receipt, split = settle_bid(
            bid_id=bid_id,
            proof_receipt='proof_hash_abc',
            settled_by='owner',
            org_id='org_test',
            royalty_share=0.10,
            reservation_id='resv_123',
        )

        self.assertRegex(settlement_id, r'^stl_[0-9a-f]{8}$')
        self.assertRegex(settlement_receipt, r'^[0-9a-f]{64}$')
        self.assertAlmostEqual(split['worker_usd'] + split['royalty_usd'], split['total_usd'], places=4)
        self.assertAlmostEqual(split['total_usd'], 10.0, places=4)

    def test_dispute_open_and_resolve_preserves_auditable_lifecycle(self):
        bid_id, _receipt = post_bid(
            agent_id='agent_quill',
            task_description='draft policy update',
            amount_usd=7.5,
            org_id='org_test',
        )
        assign_bid(bid_id, assigned_by='owner', org_id='org_test')
        dispute_id = open_dispute(
            bid_id=bid_id,
            opened_by='owner',
            reason='warrant mismatch',
            org_id='org_test',
            action_ids=['act_1'],
        )
        stayed = resolve_dispute(
            dispute_id=dispute_id,
            decision='stay',
            resolved_by='court',
            org_id='org_test',
            court_decision_ref='court_decision_1',
            note='manual review required',
        )

        # 'stay' halts proceedings — dispute remains open for future resolution
        self.assertEqual(stayed['status'], 'open')
        self.assertEqual(stayed['decision'], 'stay')
        self.assertEqual(stayed['court_decision_ref'], 'court_decision_1')

        disputes = get_disputes(org_id='org_test')
        self.assertEqual(len(disputes), 1)
        self.assertEqual(disputes[0]['id'], dispute_id)
        snapshot = marketplace_snapshot(org_id='org_test')
        self.assertEqual(snapshot['status']['open_disputes'], 1)
        self.assertEqual(snapshot['bids'][0]['status'], 'disputed')

        # Now actually resolve the dispute with a final decision
        resolved = resolve_dispute(
            dispute_id=dispute_id,
            decision='release',
            resolved_by='court',
            org_id='org_test',
            note='approved after review',
        )
        self.assertEqual(resolved['status'], 'resolved')
        self.assertEqual(resolved['decision'], 'release')

        snapshot = marketplace_snapshot(org_id='org_test')
        self.assertEqual(snapshot['status']['open_disputes'], 0)
        self.assertEqual(snapshot['bids'][0]['status'], 'settled')

    def test_dispute_can_refund_after_intermediate_stay(self):
        bid_id, _receipt = post_bid(
            agent_id='agent_forge',
            task_description='verify dispute ladder',
            amount_usd=3.25,
            org_id='org_test',
        )
        assign_bid(bid_id, assigned_by='owner', org_id='org_test')
        settle_bid(
            bid_id=bid_id,
            proof_receipt='proof_hash_xyz',
            settled_by='owner',
            org_id='org_test',
            royalty_share=0.10,
        )
        dispute_id = open_dispute(
            bid_id=bid_id,
            opened_by='owner',
            reason='manual quality hold',
            org_id='org_test',
            action_ids=['act_2'],
        )

        stayed = resolve_dispute(
            dispute_id=dispute_id,
            decision='stay',
            resolved_by='court',
            org_id='org_test',
            court_decision_ref='court_decision_hold',
            note='pending additional review',
        )
        self.assertEqual(stayed['status'], 'open')
        self.assertEqual(stayed['decision'], 'stay')

        refunded = resolve_dispute(
            dispute_id=dispute_id,
            decision='refund',
            resolved_by='court',
            org_id='org_test',
            court_decision_ref='court_decision_refund',
            note='refund approved',
        )
        self.assertEqual(refunded['status'], 'resolved')
        self.assertEqual(refunded['decision'], 'refund')

        snapshot = marketplace_snapshot(org_id='org_test')
        self.assertEqual(snapshot['status']['open_disputes'], 0)
        bids = {row['id']: row for row in snapshot['bids']}
        settlements = [row for row in snapshot['settlements'] if row['bid_id'] == bid_id]
        self.assertEqual(bids[bid_id]['status'], 'cancelled')
        self.assertTrue(settlements)
        self.assertEqual(settlements[-1]['status'], 'refunded')


if __name__ == '__main__':
    unittest.main()
