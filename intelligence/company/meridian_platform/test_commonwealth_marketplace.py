#!/usr/bin/env python3
"""RED tests for On-device Verifiable Agent Marketplace (Slice 4).

Covers Commonwealth marketplace lifecycle in commonwealth mode:
publish -> acquire -> settle

Reference: RFC-0004
"""
import os
import sys
import unittest
from unittest import mock

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

from commonwealth import (
    publish_to_commonwealth,
    acquire_from_commonwealth,
    settle_commonwealth_acquisition,
    get_commonwealth_marketplace,
)


class CommonwealthMarketplaceLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.org_id = 'org_marketplace_test'
        self.acquirer_org_id = 'org_marketplace_buyer'

        self.market_store = {'listings': {}, 'acquisitions': {}, 'settlements': {}}

        self.load_patcher = mock.patch('commonwealth._load_cw_marketplace')
        self.save_patcher = mock.patch('commonwealth._save_cw_marketplace')
        self.mock_load = self.load_patcher.start()
        self.mock_save = self.save_patcher.start()

        self.mock_load.return_value = self.market_store

        def fake_save(data, org_id):
            self.market_store = data

        self.mock_save.side_effect = fake_save

    def tearDown(self):
        self.load_patcher.stop()
        self.save_patcher.stop()

    def test_publish_acquire_settle_happy_path(self):
        publish = publish_to_commonwealth(
            self.org_id,
            agent_id='agent_alpha',
            task_description='Cross-org runtime labor',
            amount_usd=120.0,
            royalty_rate=0.15,
        )
        self.assertEqual(publish['status'], 'open')
        listing_id = publish['listing_id']

        acquire = acquire_from_commonwealth(
            self.org_id,
            listing_id,
            acquirer_org_id=self.acquirer_org_id,
            reservation_note='reserve for constitutional execution',
        )
        self.assertEqual(acquire['status'], 'assigned')
        acquisition_id = acquire['acquisition_id']

        settlement = settle_commonwealth_acquisition(
            self.org_id,
            acquisition_id,
            proof_receipt='proof_receipt_abc123',
            settled_by='court_operator_1',
        )

        self.assertEqual(settlement['status'], 'settled')
        self.assertIn('settlement_id', settlement)
        self.assertIn('settlement_receipt', settlement)

        split = settlement['split']
        self.assertEqual(split['total_usd'], 120.0)
        self.assertEqual(split['worker_usd'] + split['royalty_usd'], 120.0)
        self.assertEqual(split['royalty_usd'], 18.0)
        self.assertEqual(split['worker_usd'], 102.0)

        snapshot = get_commonwealth_marketplace(self.org_id)
        self.assertEqual(snapshot['active_acquisitions'], 0)
        self.assertEqual(snapshot['settled_count'], 1)

    def test_settle_requires_assigned_status(self):
        publish = publish_to_commonwealth(
            self.org_id,
            agent_id='agent_beta',
            task_description='Task',
            amount_usd=50.0,
            royalty_rate=0.10,
        )
        listing_id = publish['listing_id']

        acquire = acquire_from_commonwealth(
            self.org_id,
            listing_id,
            acquirer_org_id=self.acquirer_org_id,
        )

        # First settle succeeds
        settle_commonwealth_acquisition(
            self.org_id,
            acquire['acquisition_id'],
            proof_receipt='proof_x',
            settled_by='operator',
        )

        # Second settle should fail (already settled)
        with self.assertRaisesRegex(ValueError, 'is not assigned'):
            settle_commonwealth_acquisition(
                self.org_id,
                acquire['acquisition_id'],
                proof_receipt='proof_y',
                settled_by='operator',
            )

    def test_settle_validates_inputs(self):
        with self.assertRaisesRegex(ValueError, 'acquisition_id is required'):
            settle_commonwealth_acquisition(
                self.org_id,
                '',
                proof_receipt='proof',
                settled_by='operator',
            )

        # create assigned acquisition first
        publish = publish_to_commonwealth(
            self.org_id,
            agent_id='agent_gamma',
            task_description='Task',
            amount_usd=20.0,
        )
        acquire = acquire_from_commonwealth(
            self.org_id,
            publish['listing_id'],
            acquirer_org_id=self.acquirer_org_id,
        )

        with self.assertRaisesRegex(ValueError, 'proof_receipt is required'):
            settle_commonwealth_acquisition(
                self.org_id,
                acquire['acquisition_id'],
                proof_receipt='',
                settled_by='operator',
            )


if __name__ == '__main__':
    unittest.main()
