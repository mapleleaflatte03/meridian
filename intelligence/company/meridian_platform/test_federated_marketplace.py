#!/usr/bin/env python3
"""Tests for Federated Proof Marketplace."""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PLATFORM_DIR)

from federated_marketplace import (
    publish_offering, federated_catalog, request_rental, rental_settlement,
)


class TestPublishOffering(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_publish_creates_offering(self):
        with patch('federated_marketplace.capsule_path',
                   side_effect=lambda org_id, fn: os.path.join(self.temp_dir, fn)):
            offering = publish_offering(
                org_id='org_a',
                agent_id='agent_researcher',
                capability='deep_research',
                price_usd_per_run=0.50,
                description='Deep web research',
            )
        self.assertTrue(offering['id'].startswith('off_'))
        self.assertEqual(offering['org_id'], 'org_a')
        self.assertEqual(offering['capability'], 'deep_research')
        self.assertEqual(offering['price_usd_per_run'], 0.50)
        self.assertEqual(offering['status'], 'active')


class TestFederatedCatalog(unittest.TestCase):
    def test_aggregates_across_institutions(self):
        with patch('federated_marketplace.list_orgs', return_value=[
            {'id': 'org_a', 'name': 'Alpha', 'slug': 'alpha'},
            {'id': 'org_b', 'name': 'Beta', 'slug': 'beta'},
        ]), patch('federated_marketplace._load_catalog') as mock_load:
            mock_load.side_effect = lambda org_id: {
                'offerings': {
                    f'off_{org_id}': {
                        'id': f'off_{org_id}',
                        'org_id': org_id,
                        'capability': 'research',
                        'price_usd_per_run': 0.30 if org_id == 'org_a' else 0.50,
                        'status': 'active',
                    }
                }
            }
            catalog = federated_catalog()

        self.assertEqual(len(catalog), 2)
        self.assertEqual(catalog[0]['price_usd_per_run'], 0.30)
        self.assertEqual(catalog[0]['institution_name'], 'Alpha')
        self.assertEqual(catalog[1]['institution_name'], 'Beta')


class TestRentalFlow(unittest.TestCase):
    def test_request_rental_validates_offering(self):
        with patch('federated_marketplace._load_catalog', return_value={
            'offerings': {'off_1': {'id': 'off_1', 'status': 'active', 'capability': 'research'}}
        }):
            rental = request_rental('org_b', 'off_1', 'org_a', 'Research task')
        self.assertEqual(rental['status'], 'requested')
        self.assertTrue(rental['rental_id'].startswith('rental_'))
        self.assertIn('request_hash', rental)

    def test_request_rental_rejects_inactive(self):
        with patch('federated_marketplace._load_catalog', return_value={
            'offerings': {'off_1': {'id': 'off_1', 'status': 'cancelled'}}
        }):
            with self.assertRaises(ValueError):
                request_rental('org_b', 'off_1', 'org_a', 'Research task')

    def test_settlement_produces_hash(self):
        rental = {
            'rental_id': 'rental_test123',
            'requester_org_id': 'org_b',
            'provider_org_id': 'org_a',
        }
        settlement = rental_settlement(rental, 'proof_abc', 'Research completed')
        self.assertEqual(settlement['status'], 'settled')
        self.assertIn('settlement_hash', settlement)
        self.assertEqual(settlement['proof_receipt'], 'proof_abc')


if __name__ == '__main__':
    unittest.main()
