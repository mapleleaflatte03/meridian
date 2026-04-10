#!/usr/bin/env python3
"""RED tests for federated proof bundle (Slice 1).

Tests the extension of PoGE to multi-Institution verifiable proof
via a federated proof bundle. The federated bundle includes:
  - Cross-institution Merkle roots from the 3-host federation story
  - Per-institution proof metadata (org_id, host_id, role)
  - Federation context (peer_count, enabled, protocol_version)
  - Federated integrity hash using FEDERATED_INTEGRITY_v1 tag
  - Verifiable inclusion proofs for each institution's contribution

Reference: RFC-0001 (recursive PoGE), RFC-0002 (hypercube), RFC-0005 (commonwealth)
"""
import hashlib
import json
import math
import os
import sys
import unittest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
EXAMPLES_DIR = os.path.normpath(os.path.join(THIS_DIR, '..', '..', 'examples'))
sys.path.insert(0, EXAMPLES_DIR)
sys.path.insert(0, THIS_DIR)


class FederatedProofBundleStructureTest(unittest.TestCase):
    """Test the structure and integrity of a federated proof bundle
    built from synthetic multi-institution proof receipts."""

    @classmethod
    def setUpClass(cls):
        """Import and build a federated proof bundle from synthetic data."""
        from generate_public_proof_bundle import build_federated_bundle

        cls.institution_receipts = [
            {
                'org_id': 'org_alpha',
                'host_id': 'host_alpha',
                'role': 'sender',
                'receipt_hash': hashlib.sha256(b'alpha-proof-data').hexdigest(),
                'witness_archives': 3,
            },
            {
                'org_id': 'org_beta',
                'host_id': 'host_beta',
                'role': 'receiver',
                'receipt_hash': hashlib.sha256(b'beta-proof-data').hexdigest(),
                'witness_archives': 2,
            },
            {
                'org_id': 'org_gamma',
                'host_id': 'host_gamma',
                'role': 'witness',
                'receipt_hash': hashlib.sha256(b'gamma-proof-data').hexdigest(),
                'witness_archives': 5,
            },
        ]
        cls.federation_context = {
            'enabled': True,
            'peer_count': 3,
            'protocol_version': '1.0',
        }
        cls.bundle = build_federated_bundle(
            institution_receipts=cls.institution_receipts,
            federation_context=cls.federation_context,
        )

    def test_bundle_version_is_5(self):
        """Federated bundles use version 5 to distinguish from single-institution v4."""
        self.assertEqual(self.bundle['federated_proof_bundle_version'], 5)

    def test_bundle_has_generated_at(self):
        """Bundle includes an ISO-8601 generation timestamp."""
        self.assertIn('generated_at', self.bundle)
        self.assertIsInstance(self.bundle['generated_at'], str)
        self.assertTrue(len(self.bundle['generated_at']) > 0)

    def test_federation_context_present(self):
        """Bundle includes the federation context metadata."""
        ctx = self.bundle.get('federation_context')
        self.assertIsNotNone(ctx)
        self.assertTrue(ctx['enabled'])
        self.assertEqual(ctx['peer_count'], 3)
        self.assertEqual(ctx['protocol_version'], '1.0')

    def test_institution_proofs_section(self):
        """Bundle includes per-institution proof entries."""
        proofs = self.bundle.get('institution_proofs')
        self.assertIsNotNone(proofs)
        self.assertEqual(len(proofs), 3)
        org_ids = [p['org_id'] for p in proofs]
        self.assertIn('org_alpha', org_ids)
        self.assertIn('org_beta', org_ids)
        self.assertIn('org_gamma', org_ids)

    def test_institution_proof_fields(self):
        """Each institution proof entry contains required metadata."""
        for proof in self.bundle['institution_proofs']:
            self.assertIn('org_id', proof)
            self.assertIn('host_id', proof)
            self.assertIn('role', proof)
            self.assertIn('receipt_hash', proof)
            # receipt_hash must be a valid 64-char hex string
            self.assertEqual(len(proof['receipt_hash']), 64)
            self.assertTrue(
                all(c in '0123456789abcdef' for c in proof['receipt_hash']),
                f"Invalid hex in receipt_hash: {proof['receipt_hash']}",
            )

    def test_federated_aggregate_present(self):
        """Bundle includes the federated aggregate section."""
        agg = self.bundle.get('federated_aggregate')
        self.assertIsNotNone(agg)

    def test_federated_aggregate_topology(self):
        """Federated aggregate uses hypercube topology."""
        agg = self.bundle['federated_aggregate']
        self.assertEqual(agg['topology'], 'hypercube')

    def test_federated_aggregate_has_bundle_id(self):
        """Federated aggregate has a unique bundle_id."""
        agg = self.bundle['federated_aggregate']
        self.assertIn('bundle_id', agg)
        self.assertTrue(agg['bundle_id'].startswith('fhc_'))

    def test_federated_aggregate_member_count(self):
        """Aggregate contains exactly one member per institution."""
        agg = self.bundle['federated_aggregate']
        self.assertEqual(agg['member_count'], 3)

    def test_federated_aggregate_member_receipts(self):
        """Aggregate member_receipts match the institution receipt hashes."""
        agg = self.bundle['federated_aggregate']
        expected_hashes = [r['receipt_hash'] for r in self.institution_receipts]
        self.assertEqual(agg['member_receipts'], expected_hashes)

    def test_federated_aggregate_dimension(self):
        """Dimension is log2 of padded leaf count (3 leaves → pad to 4 → dim 2)."""
        agg = self.bundle['federated_aggregate']
        # 3 institutions, padded to 4 = 2^2
        self.assertEqual(agg['dimension'], 2)

    def test_federated_aggregate_root_is_valid_hash(self):
        """Aggregate root is a 64-char hex string."""
        agg = self.bundle['federated_aggregate']
        root = agg['aggregate_root']
        self.assertEqual(len(root), 64)
        self.assertTrue(all(c in '0123456789abcdef' for c in root))

    def test_federated_aggregate_inclusion_proofs(self):
        """Each member has an inclusion proof with sibling path."""
        agg = self.bundle['federated_aggregate']
        proofs = agg['inclusion_proofs']
        self.assertEqual(len(proofs), 3)
        for i, proof in enumerate(proofs):
            self.assertEqual(proof['index'], i)
            self.assertIn('receipt_hash', proof)
            self.assertIn('sibling_path', proof)
            self.assertIsInstance(proof['sibling_path'], list)

    def test_federated_aggregate_inclusion_verified(self):
        """All inclusion proofs verify against the aggregate root."""
        agg = self.bundle['federated_aggregate']
        self.assertTrue(agg['inclusion_verified'])

    def test_federated_integrity_hash_present(self):
        """Federated integrity hash uses FEDERATED_INTEGRITY_v1 tag."""
        agg = self.bundle['federated_aggregate']
        self.assertIn('integrity_hash', agg)
        integrity = agg['integrity_hash']
        self.assertEqual(len(integrity), 64)
        self.assertTrue(all(c in '0123456789abcdef' for c in integrity))

    def test_federated_integrity_hash_deterministic(self):
        """Recomputing the integrity hash from bundle data matches stored value."""
        agg = self.bundle['federated_aggregate']
        tag = b'FEDERATED_INTEGRITY_v1\x00'
        h = hashlib.sha256()
        h.update(tag)
        h.update(agg['bundle_id'].encode())
        h.update(bytes.fromhex(agg['aggregate_root']))
        for mh in agg['member_receipts']:
            h.update(bytes.fromhex(mh))
        expected = h.hexdigest()
        self.assertEqual(agg['integrity_hash'], expected)

    def test_federated_aggregate_root_recomputable(self):
        """Recompute Merkle root from member hashes and verify it matches."""
        agg = self.bundle['federated_aggregate']
        member_hashes = agg['member_receipts']

        leaves = [bytes.fromhex(h) for h in member_hashes]
        padded_len = max(1, len(leaves))
        while padded_len & (padded_len - 1):
            padded_len += 1
        padded = leaves + [b'\x00' * 32] * (padded_len - len(leaves))

        level = padded
        while len(level) > 1:
            next_level = []
            for i in range(0, len(level), 2):
                next_level.append(hashlib.sha256(level[i] + level[i + 1]).digest())
            level = next_level

        computed_root = level[0].hex()
        self.assertEqual(computed_root, agg['aggregate_root'])

    def test_inclusion_proof_verification(self):
        """Manually verify each inclusion proof against the aggregate root."""
        agg = self.bundle['federated_aggregate']
        root = agg['aggregate_root']

        for proof in agg['inclusion_proofs']:
            current = bytes.fromhex(proof['receipt_hash'])
            position = proof['index']
            for sibling_hex in proof['sibling_path']:
                sibling = bytes.fromhex(sibling_hex)
                if position % 2 == 0:
                    current = hashlib.sha256(current + sibling).digest()
                else:
                    current = hashlib.sha256(sibling + current).digest()
                position //= 2
            self.assertEqual(
                current.hex(),
                root,
                f"Inclusion proof failed for index {proof['index']}",
            )


class FederatedProofBundleEdgeCasesTest(unittest.TestCase):
    """Test edge cases for the federated proof bundle builder."""

    def _build(self, receipts, context=None):
        from generate_public_proof_bundle import build_federated_bundle
        return build_federated_bundle(
            institution_receipts=receipts,
            federation_context=context or {'enabled': True, 'peer_count': len(receipts), 'protocol_version': '1.0'},
        )

    def test_single_institution_bundle(self):
        """A federated bundle with only one institution still works."""
        bundle = self._build([
            {
                'org_id': 'org_solo',
                'host_id': 'host_solo',
                'role': 'sender',
                'receipt_hash': hashlib.sha256(b'solo-proof').hexdigest(),
            },
        ])
        self.assertEqual(bundle['federated_proof_bundle_version'], 5)
        agg = bundle['federated_aggregate']
        self.assertEqual(agg['member_count'], 1)
        # 1 leaf padded to 1 → dimension 0
        self.assertEqual(agg['dimension'], 0)
        self.assertTrue(agg['inclusion_verified'])

    def test_power_of_two_institutions(self):
        """Four institutions require no padding (2^2)."""
        receipts = [
            {
                'org_id': f'org_{i}',
                'host_id': f'host_{i}',
                'role': 'peer',
                'receipt_hash': hashlib.sha256(f'proof-{i}'.encode()).hexdigest(),
            }
            for i in range(4)
        ]
        bundle = self._build(receipts)
        agg = bundle['federated_aggregate']
        self.assertEqual(agg['member_count'], 4)
        self.assertEqual(agg['dimension'], 2)
        self.assertTrue(agg['inclusion_verified'])

    def test_large_federation(self):
        """Federated bundle with 7 institutions (pads to 8 = 2^3)."""
        receipts = [
            {
                'org_id': f'org_{i}',
                'host_id': f'host_{i}',
                'role': 'peer',
                'receipt_hash': hashlib.sha256(f'proof-{i}'.encode()).hexdigest(),
            }
            for i in range(7)
        ]
        bundle = self._build(receipts)
        agg = bundle['federated_aggregate']
        self.assertEqual(agg['member_count'], 7)
        self.assertEqual(agg['dimension'], 3)
        self.assertTrue(agg['inclusion_verified'])

    def test_empty_federation_raises(self):
        """Building with zero institutions raises ValueError."""
        from generate_public_proof_bundle import build_federated_bundle
        with self.assertRaises(ValueError):
            build_federated_bundle(
                institution_receipts=[],
                federation_context={'enabled': True, 'peer_count': 0, 'protocol_version': '1.0'},
            )

    def test_federation_disabled_context(self):
        """Bundle can be built with federation disabled — still valid but flagged."""
        bundle = self._build(
            [
                {
                    'org_id': 'org_a',
                    'host_id': 'host_a',
                    'role': 'sender',
                    'receipt_hash': hashlib.sha256(b'a-proof').hexdigest(),
                },
            ],
            context={'enabled': False, 'peer_count': 1, 'protocol_version': '1.0'},
        )
        self.assertFalse(bundle['federation_context']['enabled'])
        self.assertEqual(bundle['federated_proof_bundle_version'], 5)

    def test_duplicate_org_ids_raises(self):
        """Two receipts with the same org_id should raise ValueError."""
        from generate_public_proof_bundle import build_federated_bundle
        with self.assertRaises(ValueError):
            build_federated_bundle(
                institution_receipts=[
                    {
                        'org_id': 'org_dup',
                        'host_id': 'host_a',
                        'role': 'sender',
                        'receipt_hash': hashlib.sha256(b'dup-a').hexdigest(),
                    },
                    {
                        'org_id': 'org_dup',
                        'host_id': 'host_b',
                        'role': 'receiver',
                        'receipt_hash': hashlib.sha256(b'dup-b').hexdigest(),
                    },
                ],
                federation_context={'enabled': True, 'peer_count': 2, 'protocol_version': '1.0'},
            )


class FederatedProofBundleIntegrityTest(unittest.TestCase):
    """Test that federated integrity hash is tamper-evident."""

    def _build_default(self):
        from generate_public_proof_bundle import build_federated_bundle
        return build_federated_bundle(
            institution_receipts=[
                {
                    'org_id': 'org_alpha',
                    'host_id': 'host_alpha',
                    'role': 'sender',
                    'receipt_hash': hashlib.sha256(b'alpha-data').hexdigest(),
                },
                {
                    'org_id': 'org_beta',
                    'host_id': 'host_beta',
                    'role': 'receiver',
                    'receipt_hash': hashlib.sha256(b'beta-data').hexdigest(),
                },
            ],
            federation_context={'enabled': True, 'peer_count': 2, 'protocol_version': '1.0'},
        )

    def test_different_receipts_produce_different_roots(self):
        """Changing one receipt_hash changes the aggregate root."""
        from generate_public_proof_bundle import build_federated_bundle

        bundle_a = build_federated_bundle(
            institution_receipts=[
                {
                    'org_id': 'org_a',
                    'host_id': 'host_a',
                    'role': 'sender',
                    'receipt_hash': hashlib.sha256(b'data-a').hexdigest(),
                },
                {
                    'org_id': 'org_b',
                    'host_id': 'host_b',
                    'role': 'receiver',
                    'receipt_hash': hashlib.sha256(b'data-b').hexdigest(),
                },
            ],
            federation_context={'enabled': True, 'peer_count': 2, 'protocol_version': '1.0'},
        )
        bundle_b = build_federated_bundle(
            institution_receipts=[
                {
                    'org_id': 'org_a',
                    'host_id': 'host_a',
                    'role': 'sender',
                    'receipt_hash': hashlib.sha256(b'data-a').hexdigest(),
                },
                {
                    'org_id': 'org_b',
                    'host_id': 'host_b',
                    'role': 'receiver',
                    'receipt_hash': hashlib.sha256(b'TAMPERED-data-b').hexdigest(),
                },
            ],
            federation_context={'enabled': True, 'peer_count': 2, 'protocol_version': '1.0'},
        )
        self.assertNotEqual(
            bundle_a['federated_aggregate']['aggregate_root'],
            bundle_b['federated_aggregate']['aggregate_root'],
        )
        self.assertNotEqual(
            bundle_a['federated_aggregate']['integrity_hash'],
            bundle_b['federated_aggregate']['integrity_hash'],
        )

    def test_integrity_hash_changes_with_bundle_id(self):
        """Integrity hash includes bundle_id, so same data at different times differs."""
        bundle = self._build_default()
        agg = bundle['federated_aggregate']

        # Recompute with a different bundle_id
        tag = b'FEDERATED_INTEGRITY_v1\x00'
        h = hashlib.sha256()
        h.update(tag)
        h.update(b'fhc_FAKE_BUNDLE_ID')
        h.update(bytes.fromhex(agg['aggregate_root']))
        for mh in agg['member_receipts']:
            h.update(bytes.fromhex(mh))
        fake_integrity = h.hexdigest()

        self.assertNotEqual(fake_integrity, agg['integrity_hash'])


if __name__ == '__main__':
    unittest.main()
