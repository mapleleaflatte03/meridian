#!/usr/bin/env python3
import importlib.util
import os
import sqlite3
import tempfile
import unittest


PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
CASES_PY = os.path.join(PLATFORM_DIR, 'cases.py')


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


import cases_store


class CaseModuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cases = _load_module(CASES_PY, 'cases_test_module')
        self.org_id = 'org_founding'
        self.orig_capsule_path = self.cases.capsule_path
        self.cases.capsule_path = lambda org_id, filename: os.path.join(self.tmp.name, filename)

    def tearDown(self):
        self.cases.capsule_path = self.orig_capsule_path
        self.tmp.cleanup()

    def test_open_stay_and_resolve_case(self):
        record = self.cases.open_case(
            self.org_id,
            'misrouted_execution',
            'user_owner',
            target_host_id='host_peer',
            target_institution_id='org_peer',
            note='Wrong target received',
        )
        self.assertEqual(record['status'], 'open')
        self.assertEqual(record['institution_id'], self.org_id)
        stayed = self.cases.stay_case(record['case_id'], 'user_owner', org_id=self.org_id, note='Freeze')
        self.assertEqual(stayed['status'], 'stayed')
        resolved = self.cases.resolve_case(record['case_id'], 'user_owner', org_id=self.org_id, note='Closed')
        self.assertEqual(resolved['status'], 'resolved')
        self.assertEqual(self.cases.case_summary(self.org_id)['resolved'], 1)

    def test_breach_helper_dedupes_case(self):
        commitment = {
            'commitment_id': 'com_demo',
            'target_host_id': 'host_peer',
            'target_institution_id': 'org_peer',
            'warrant_id': 'war_live_demo',
        }
        first, created_first = self.cases.ensure_case_for_commitment_breach(
            commitment,
            'user_owner',
            org_id=self.org_id,
        )
        second, created_second = self.cases.ensure_case_for_commitment_breach(
            commitment,
            'user_owner',
            org_id=self.org_id,
        )
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first['case_id'], second['case_id'])
        self.assertEqual(first['linked_warrant_id'], 'war_live_demo')

    def test_breach_helper_targets_counterparty_for_mirrored_commitment(self):
        commitment = {
            'commitment_id': 'com_mirror_demo',
            'institution_id': self.org_id,
            'source_host_id': 'host_alpha',
            'source_institution_id': 'org_alpha',
            'target_host_id': 'host_live',
            'target_institution_id': self.org_id,
            'warrant_id': 'war_live_demo',
        }
        record, created = self.cases.ensure_case_for_commitment_breach(
            commitment,
            'user_owner',
            org_id=self.org_id,
        )
        self.assertTrue(created)
        self.assertEqual(record['target_host_id'], 'host_alpha')
        self.assertEqual(record['target_institution_id'], 'org_alpha')

    def test_blocking_helpers_surface_commitments_and_peers(self):
        blocking = self.cases.open_case(
            self.org_id,
            'misrouted_execution',
            'user_owner',
            target_host_id='host_peer',
            target_institution_id='org_peer',
            linked_commitment_id='cmt_demo',
        )
        self.cases.open_case(
            self.org_id,
            'non_delivery',
            'user_owner',
            target_host_id='host_other',
            target_institution_id='org_other',
            linked_commitment_id='cmt_other',
        )
        self.assertEqual(
            self.cases.blocking_commitment_case('cmt_demo', org_id=self.org_id)['case_id'],
            blocking['case_id'],
        )
        self.assertEqual(
            self.cases.blocking_peer_case('host_peer', org_id=self.org_id)['case_id'],
            blocking['case_id'],
        )
        self.assertCountEqual(self.cases.blocking_commitment_ids(self.org_id), ['cmt_demo', 'cmt_other'])
        self.assertEqual(self.cases.blocked_peer_host_ids(self.org_id), ['host_peer'])

    def test_peer_can_be_thawed_only_after_peer_blocking_case_resolves(self):
        record = self.cases.open_case(
            self.org_id,
            'misrouted_execution',
            'user_owner',
            target_host_id='host_peer',
            target_institution_id='org_peer',
            linked_commitment_id='cmt_demo',
        )
        self.assertFalse(self.cases.peer_can_be_thawed('host_peer', org_id=self.org_id))
        self.cases.resolve_case(record['case_id'], 'user_owner', org_id=self.org_id, note='Recovered')
        self.assertTrue(self.cases.peer_can_be_thawed('host_peer', org_id=self.org_id))

    def test_delivery_failure_helper_dedupes_active_case(self):
        first, created_first = self.cases.ensure_case_for_delivery_failure(
            'invalid_settlement_notice',
            'user_owner',
            org_id=self.org_id,
            target_host_id='host_peer',
            target_institution_id='org_peer',
            linked_commitment_id='cmt_demo',
            note='Receipt mismatch',
        )
        second, created_second = self.cases.ensure_case_for_delivery_failure(
            'invalid_settlement_notice',
            'user_owner',
            org_id=self.org_id,
            target_host_id='host_peer',
            target_institution_id='org_peer',
            linked_commitment_id='cmt_demo',
            note='Receipt mismatch again',
        )
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first['case_id'], second['case_id'])


    def test_sqlite_mirror_recovers_when_cases_json_is_missing(self):
        record = self.cases.open_case(
            self.org_id,
            'misrouted_execution',
            'user_owner',
            target_host_id='host_peer',
            target_institution_id='org_peer',
            note='Wrong target received',
        )
        cases_path = self.cases._store_path(self.org_id)
        db_path = cases_store.db_path_for_cases_file(cases_path)
        self.assertTrue(os.path.exists(db_path))

        os.remove(cases_path)
        reloaded = self.cases._load_store(self.org_id)

        with sqlite3.connect(db_path) as conn:
            case_rows = conn.execute('SELECT COUNT(*) FROM cases').fetchone()[0]

        self.assertEqual(case_rows, 1)
        self.assertIn(record['case_id'], reloaded['cases'])
        self.assertEqual(reloaded['cases'][record['case_id']]['status'], 'open')
        self.assertEqual(cases_store.db_status_for_cases_file(cases_path, self.org_id)['status'], 'present')


if __name__ == '__main__':
    unittest.main()
