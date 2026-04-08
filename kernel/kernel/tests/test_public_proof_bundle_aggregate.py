#!/usr/bin/env python3
"""Regression tests for public proof bundle aggregation behavior."""

import importlib.util
import pathlib
import unittest


THIS_DIR = pathlib.Path(__file__).resolve().parent
ROOT_DIR = THIS_DIR.parent.parent
BUNDLE_PATH = ROOT_DIR / 'examples' / 'generate_public_proof_bundle.py'


def _load_bundle_module():
    spec = importlib.util.spec_from_file_location('kernel_public_bundle', str(BUNDLE_PATH))
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Unable to load bundle module at {BUNDLE_PATH}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublicProofBundleAggregateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = _load_bundle_module()

    def test_supplemental_live_receipt_populates_member_list(self):
        live_hash = 'f' * 64
        aggregate = self.bundle._build_aggregate_section(
            [],
            supplemental_members=[
                {
                    'label': 'live_runtime_receipt',
                    'item': {'included': True, 'body_sha256': live_hash},
                }
            ],
        )

        self.assertEqual(aggregate['topology'], 'hypercube')
        self.assertEqual(aggregate['member_count'], 1)
        self.assertEqual(aggregate['member_receipts'], [live_hash])
        self.assertTrue(aggregate['inclusion_verified'])
        self.assertEqual(len(aggregate['integrity_hash']), 64)

    def test_supplemental_receipt_dedupes_against_reference_members(self):
        member_hash = 'a' * 64
        aggregate = self.bundle._build_aggregate_section(
            [
                {
                    'passed': True,
                    'summary': {'merkle_root': member_hash},
                }
            ],
            supplemental_members=[
                {
                    'label': 'live_host_receipt',
                    'item': {'included': True, 'body_sha256': member_hash},
                }
            ],
        )

        self.assertEqual(aggregate['member_count'], 1)
        self.assertEqual(aggregate['member_receipts'], [member_hash])
        self.assertTrue(aggregate['inclusion_verified'])

    def test_supplemental_member_hash_falls_back_to_structured_payload_hash(self):
        aggregate = self.bundle._build_aggregate_section(
            [],
            supplemental_members=[
                {
                    'label': 'live_host_receipt',
                    'item': {
                        'included': True,
                        'manifest': {'host_identity': {'host_id': 'host_123'}},
                    },
                }
            ],
        )

        self.assertEqual(aggregate['member_count'], 1)
        self.assertEqual(len(aggregate['member_receipts'][0]), 64)
        self.assertTrue(all(ch in '0123456789abcdef' for ch in aggregate['member_receipts'][0]))


if __name__ == '__main__':
    unittest.main()
