#!/usr/bin/env python3
import importlib.util
import pathlib
import shutil
import unittest
import uuid


ROOT = pathlib.Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / 'kernel' / 'cases.py'
CAPSULE_PATH = ROOT / 'kernel' / 'capsule.py'
CAPSULES_DIR = ROOT / 'capsules'


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cases = _load_module('kernel_cases_test', CASES_PATH)
capsule = _load_module('kernel_capsule_test_for_cases', CAPSULE_PATH)


class CaseCapsuleTests(unittest.TestCase):
    def setUp(self):
        self.org_id = f'org_case_test_{uuid.uuid4().hex[:8]}'
        self.capsule_dir = CAPSULES_DIR / self.org_id
        capsule.init_capsule(self.org_id)

    def tearDown(self):
        shutil.rmtree(self.capsule_dir, ignore_errors=True)

    def test_capsule_initializes_cases_file(self):
        path = pathlib.Path(capsule.capsule_path(self.org_id, 'cases.json'))
        self.assertTrue(path.exists())
        payload = cases._load_store(self.org_id)
        self.assertEqual(payload['cases'], {})
        self.assertIn('breach_of_commitment', payload['claim_types'])

    def test_open_stay_and_resolve_case(self):
        record = cases.open_case(
            self.org_id,
            'misrouted_execution',
            'user_owner',
            target_host_id='host_beta',
            target_institution_id='org_beta',
            note='Receiver reported wrong target',
        )
        self.assertEqual(record['status'], 'open')
        self.assertEqual(record['institution_id'], self.org_id)
        stayed = cases.stay_case(record['case_id'], 'user_owner', org_id=self.org_id, note='Freeze execution')
        self.assertEqual(stayed['status'], 'stayed')
        resolved = cases.resolve_case(record['case_id'], 'user_owner', org_id=self.org_id, note='Resolved after review')
        self.assertEqual(resolved['status'], 'resolved')
        self.assertEqual(resolved['resolution'], 'Resolved after review')
        summary = cases.case_summary(self.org_id)
        self.assertEqual(summary['total'], 1)
        self.assertEqual(summary['resolved'], 1)

    def test_breach_helper_dedupes_open_case(self):
        commitment = {
            'commitment_id': 'cmt_demo',
            'target_host_id': 'host_beta',
            'target_institution_id': 'org_beta',
            'warrant_id': 'war_demo',
        }
        first, created_first = cases.ensure_case_for_commitment_breach(
            commitment,
            'user_owner',
            org_id=self.org_id,
            note='Delivery failed',
        )
        second, created_second = cases.ensure_case_for_commitment_breach(
            commitment,
            'user_owner',
            org_id=self.org_id,
            note='Delivery failed again',
        )
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first['case_id'], second['case_id'])
        self.assertEqual(first['linked_warrant_id'], 'war_demo')
        self.assertTrue(cases.case_targets_peer(first))
        self.assertEqual(cases.blocked_peer_host_ids(self.org_id), ['host_beta'])

    def test_breach_helper_targets_counterparty_for_mirrored_commitment(self):
        mirrored_commitment = {
            'commitment_id': 'cmt_mirror_demo',
            'institution_id': self.org_id,
            'source_host_id': 'host_alpha',
            'source_institution_id': 'org_alpha',
            'target_host_id': 'host_beta',
            'target_institution_id': self.org_id,
            'warrant_id': 'war_demo',
        }
        record, created = cases.ensure_case_for_commitment_breach(
            mirrored_commitment,
            'user_owner',
            org_id=self.org_id,
            note='Remote peer breached mirrored commitment',
        )
        self.assertTrue(created)
        self.assertEqual(record['target_host_id'], 'host_alpha')
        self.assertEqual(record['target_institution_id'], 'org_alpha')
        self.assertTrue(cases.case_targets_peer(record))
        self.assertEqual(cases.blocked_peer_host_ids(self.org_id), ['host_alpha'])

    def test_blocking_helpers_surface_commitments_and_peers(self):
        blocking = cases.open_case(
            self.org_id,
            'misrouted_execution',
            'user_owner',
            target_host_id='host_beta',
            target_institution_id='org_beta',
            linked_commitment_id='cmt_demo',
        )
        cases.open_case(
            self.org_id,
            'non_delivery',
            'user_owner',
            target_host_id='host_gamma',
            target_institution_id='org_gamma',
            linked_commitment_id='cmt_other',
        )

        self.assertEqual(
            cases.blocking_commitment_case('cmt_demo', org_id=self.org_id)['case_id'],
            blocking['case_id'],
        )
        self.assertEqual(
            cases.blocking_peer_case('host_beta', org_id=self.org_id)['case_id'],
            blocking['case_id'],
        )
        self.assertCountEqual(cases.blocking_commitment_ids(self.org_id), ['cmt_demo', 'cmt_other'])
        self.assertEqual(cases.blocked_peer_host_ids(self.org_id), ['host_beta'])

    def test_resolve_clears_blocking_peer_and_commitment_views(self):
        record = cases.open_case(
            self.org_id,
            'misrouted_execution',
            'user_owner',
            target_host_id='host_beta',
            target_institution_id='org_beta',
            linked_commitment_id='cmt_demo',
        )
        self.assertTrue(cases.case_targets_peer(record))
        self.assertEqual(cases.blocked_peer_host_ids(self.org_id), ['host_beta'])
        self.assertEqual(cases.blocking_commitment_ids(self.org_id), ['cmt_demo'])

        cases.resolve_case(
            record['case_id'],
            'user_owner',
            org_id=self.org_id,
            note='Resolved after review',
        )

        self.assertEqual(cases.blocked_peer_host_ids(self.org_id), [])
        self.assertEqual(cases.blocking_commitment_ids(self.org_id), [])

    def test_delivery_failure_helper_dedupes_active_case(self):
        first, created_first = cases.ensure_case_for_delivery_failure(
            'invalid_settlement_notice',
            'user_owner',
            org_id=self.org_id,
            target_host_id='host_beta',
            target_institution_id='org_beta',
            linked_commitment_id='cmt_demo',
            note='Receipt mismatch',
        )
        second, created_second = cases.ensure_case_for_delivery_failure(
            'invalid_settlement_notice',
            'user_owner',
            org_id=self.org_id,
            target_host_id='host_beta',
            target_institution_id='org_beta',
            linked_commitment_id='cmt_demo',
            note='Receipt mismatch again',
        )
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first['case_id'], second['case_id'])


if __name__ == '__main__':
    unittest.main()
