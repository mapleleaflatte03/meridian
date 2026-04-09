#!/usr/bin/env python3
import json
import os
import tempfile
import unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import sys
sys.path.insert(0, ROOT)

import witness_archive


class WitnessArchiveTests(unittest.TestCase):
    def test_load_witness_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = os.path.join(tmp, 'nonexistent.json')

            # Test non-existent file
            data = witness_archive.load_witness_archive(archive_path, host_id='host_1')
            self.assertEqual(data.get('host_id'), 'host_1')
            self.assertEqual(data.get('records'), {})
            self.assertIn('updated_at', data)

            # Test existing file
            with open(archive_path, 'w') as f:
                json.dump({'host_id': 'host_1', 'custom_data': 123}, f)

            data = witness_archive.load_witness_archive(archive_path, host_id='host_1')
            self.assertEqual(data.get('host_id'), 'host_1')
            self.assertEqual(data.get('custom_data'), 123)
            self.assertEqual(data.get('records'), {})
            self.assertIn('updated_at', data)

            # Test host_id mismatch
            with self.assertRaises(RuntimeError) as ctx:
                witness_archive.load_witness_archive(archive_path, host_id='host_2')
            self.assertIn("Witness archive host_id 'host_1' does not match runtime host 'host_2'", str(ctx.exception))

            # Test existing file with no host_id but host_id is provided
            with open(archive_path, 'w') as f:
                json.dump({'custom_data': 456}, f)

            data = witness_archive.load_witness_archive(archive_path, host_id='host_3')
            self.assertEqual(data.get('host_id'), 'host_3')
            self.assertEqual(data.get('custom_data'), 456)


    def test_archive_observation_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = os.path.join(tmp, 'witness_archive.json')
            record, created = witness_archive.archive_witness_observation(
                archive_path,
                host_id='host_gamma',
                bound_org_id='org_gamma',
                actor_id='user_gamma',
                claims={
                    'envelope_id': 'fed_demo',
                    'source_host_id': 'host_alpha',
                    'source_institution_id': 'org_alpha',
                    'target_host_id': 'host_beta',
                    'target_institution_id': 'org_beta',
                    'message_type': 'settlement_notice',
                    'payload_hash': 'hash_demo',
                    'warrant_id': 'war_demo',
                    'commitment_id': 'cmt_demo',
                },
                receipt={
                    'receipt_id': 'fedrcpt_demo',
                    'receiver_host_id': 'host_beta',
                    'receiver_institution_id': 'org_beta',
                },
                payload={'tx_ref': 'tx_demo'},
                source_manifest={'host_identity': {'host_id': 'host_alpha'}},
                target_manifest={'host_identity': {'host_id': 'host_beta'}},
            )
            self.assertTrue(created)
            self.assertTrue(record['archive_id'].startswith('witobs_'))
            self.assertEqual(record['observer_host_id'], 'host_gamma')
            self.assertEqual(record['observer_institution_id'], 'org_gamma')
            duplicate, created = witness_archive.archive_witness_observation(
                archive_path,
                host_id='host_gamma',
                bound_org_id='org_gamma',
                actor_id='user_gamma',
                claims={
                    'envelope_id': 'fed_demo',
                    'source_host_id': 'host_alpha',
                    'source_institution_id': 'org_alpha',
                    'target_host_id': 'host_beta',
                    'target_institution_id': 'org_beta',
                    'message_type': 'settlement_notice',
                    'payload_hash': 'hash_demo',
                },
                receipt={
                    'receipt_id': 'fedrcpt_demo',
                    'receiver_host_id': 'host_beta',
                    'receiver_institution_id': 'org_beta',
                },
            )
            self.assertFalse(created)
            self.assertEqual(duplicate['archive_id'], record['archive_id'])

            summary = witness_archive.witness_archive_summary(
                archive_path,
                host_id='host_gamma',
            )
            self.assertEqual(summary['total'], 1)
            self.assertEqual(summary['message_type_counts'], {'settlement_notice': 1})
            self.assertEqual(summary['peer_host_ids'], ['host_alpha', 'host_beta'])

            with open(archive_path) as f:
                store = json.load(f)
            self.assertEqual(len(store['records']), 1)


if __name__ == '__main__':
    unittest.main()
