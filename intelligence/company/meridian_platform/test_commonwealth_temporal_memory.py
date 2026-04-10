#!/usr/bin/env python3
"""RED tests for Temporal Memory Commonwealth Chain (Slice 5).

Covers L5 cross-institution temporal proof verification:
- verify_commonwealth_temporal_proof function
- POST /api/commonwealth/memory/verify route

Reference: RFC-0009
"""
import os
import sys
import unittest
from unittest import mock

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

from commonwealth import verify_commonwealth_temporal_proof


class CommonwealthTemporalMemoryTest(unittest.TestCase):
    def setUp(self):
        self.org_id = 'org_temporal_test'
        self.peer_org_id = 'org_temporal_peer'

    def test_verify_valid_proof_from_peer(self):
        """Valid temporal proof from peer org should verify successfully."""
        proof = {
            'chain_valid': True,
            'head_hash': '0' * 64,
            'index_version': 0,
            'selected_count': 0,
            'proof_nodes': [],
        }

        with mock.patch('commonwealth._load_memory_graph') as mock_load_mg:
            mock_mg = mock.Mock()
            mock_load_mg.return_value = mock_mg
            mock_mg.verify_temporal_proof.return_value = (True, None)
            result = verify_commonwealth_temporal_proof(
                self.org_id,
                peer_org_id=self.peer_org_id,
                proof=proof,
            )

        self.assertEqual(result['status'], 'verified')
        self.assertTrue(result['valid'])
        self.assertEqual(result['peer_org_id'], self.peer_org_id)

    def test_verify_invalid_proof_returns_error(self):
        """Invalid temporal proof should return verification failure."""
        proof = {
            'chain_valid': True,
            'head_hash': 'wrong_hash',
            'index_version': 999,
            'selected_count': 0,
            'proof_nodes': [],
        }

        with mock.patch('commonwealth._load_memory_graph') as mock_load_mg:
            mock_mg = mock.Mock()
            mock_load_mg.return_value = mock_mg
            mock_mg.verify_temporal_proof.return_value = (
                False,
                {'reason': 'head_hash_mismatch'},
            )
            result = verify_commonwealth_temporal_proof(
                self.org_id,
                peer_org_id=self.peer_org_id,
                proof=proof,
            )

        self.assertEqual(result['status'], 'verification_failed')
        self.assertFalse(result['valid'])
        self.assertIn('error_detail', result)
        self.assertEqual(result['error_detail']['reason'], 'head_hash_mismatch')

    def test_verify_requires_peer_org_id(self):
        """peer_org_id is required for cross-institution verification."""
        proof = {'chain_valid': True, 'head_hash': '0' * 64}

        with self.assertRaisesRegex(ValueError, 'peer_org_id is required'):
            verify_commonwealth_temporal_proof(
                self.org_id,
                peer_org_id='',
                proof=proof,
            )

    def test_verify_requires_proof_payload(self):
        """proof payload is required."""
        with self.assertRaisesRegex(ValueError, 'proof is required'):
            verify_commonwealth_temporal_proof(
                self.org_id,
                peer_org_id=self.peer_org_id,
                proof=None,
            )

    def test_verify_proof_with_nodes(self):
        """Proof with proof_nodes should verify each node."""
        proof = {
            'chain_valid': True,
            'head_hash': 'abc123' + '0' * 58,
            'index_version': 2,
            'selected_count': 2,
            'proof_nodes': [
                {
                    'hash': 'node1' + '0' * 59,
                    'prev_hash': '0' * 64,
                    'depth': 0,
                    'timestamp': '2026-04-10T18:00:00Z',
                },
                {
                    'hash': 'node2' + '0' * 59,
                    'prev_hash': 'node1' + '0' * 59,
                    'depth': 1,
                    'timestamp': '2026-04-10T18:01:00Z',
                },
            ],
        }

        with mock.patch('commonwealth._load_memory_graph') as mock_load_mg:
            mock_mg = mock.Mock()
            mock_load_mg.return_value = mock_mg
            mock_mg.verify_temporal_proof.return_value = (True, None)
            result = verify_commonwealth_temporal_proof(
                self.org_id,
                peer_org_id=self.peer_org_id,
                proof=proof,
            )

        self.assertEqual(result['status'], 'verified')
        self.assertTrue(result['valid'])
        self.assertEqual(result['verified_node_count'], 2)


if __name__ == '__main__':
    unittest.main()
