#!/usr/bin/env python3
import importlib.util
import json
import os
import tempfile
import unittest


PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
WARRANTS_PY = os.path.join(PLATFORM_DIR, 'warrants.py')


def _load_module(name):
    spec = importlib.util.spec_from_file_location(name, WARRANTS_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LiveWarrantTests(unittest.TestCase):
    def setUp(self):
        self.warrants = _load_module('live_warrants_test')
        self.tmpdir = tempfile.TemporaryDirectory()
        self.orig_capsule_path = self.warrants.capsule_path
        self.warrants.capsule_path = lambda org_id, filename: os.path.join(
            self.tmpdir.name,
            org_id or 'org_live',
            filename,
        )

    def tearDown(self):
        self.warrants.capsule_path = self.orig_capsule_path
        self.tmpdir.cleanup()

    def test_issue_review_and_execute_live_warrant(self):
        record = self.warrants.issue_warrant(
            'org_live',
            'federated_execution',
            'federation_gateway',
            'user_owner',
            session_id='ses_live',
            request_payload={'task': 'demo'},
        )
        self.assertEqual(record['court_review_state'], 'pending_review')
        approved = self.warrants.review_warrant(
            record['warrant_id'],
            'approve',
            'user_owner',
            org_id='org_live',
        )
        self.assertEqual(approved['court_review_state'], 'approved')
        validated = self.warrants.validate_warrant_for_execution(
            record['warrant_id'],
            org_id='org_live',
            action_class='federated_execution',
            boundary_name='federation_gateway',
            actor_id='user_owner',
            session_id='ses_live',
            request_payload={'task': 'demo'},
        )
        self.assertEqual(validated['warrant_id'], record['warrant_id'])
        executed = self.warrants.mark_warrant_executed(
            record['warrant_id'],
            org_id='org_live',
            execution_refs={'receipt_id': 'fedrcpt_live'},
        )
        self.assertEqual(executed['execution_state'], 'executed')
        warrant_path = self.warrants.capsule_path('org_live', 'warrants.json')
        with open(warrant_path) as f:
            payload = json.load(f)
        self.assertIn(record['warrant_id'], payload['warrants'])

    def test_validate_rejects_missing_or_mismatched_live_warrant(self):
        with self.assertRaises(PermissionError):
            self.warrants.validate_warrant_for_execution(
                'war_missing',
                org_id='org_live',
                action_class='federated_execution',
                boundary_name='federation_gateway',
            )

        record = self.warrants.issue_warrant(
            'org_live',
            'federated_execution',
            'federation_gateway',
            'user_owner',
            request_payload={'task': 'demo'},
        )
        self.warrants.review_warrant(record['warrant_id'], 'approve', 'user_owner', org_id='org_live')
        with self.assertRaises(PermissionError):
            self.warrants.validate_warrant_for_execution(
                record['warrant_id'],
                org_id='org_live',
                action_class='federated_execution',
                boundary_name='federation_gateway',
                request_payload={'task': 'other'},
            )

    def test_validate_rejects_stayed_or_expired_live_warrant(self):
        record = self.warrants.issue_warrant(
            'org_live',
            'federated_execution',
            'federation_gateway',
            'user_owner',
            request_payload={'task': 'demo'},
        )
        self.warrants.review_warrant(record['warrant_id'], 'stay', 'user_owner', org_id='org_live')
        with self.assertRaises(PermissionError):
            self.warrants.validate_warrant_for_execution(
                record['warrant_id'],
                org_id='org_live',
                action_class='federated_execution',
                boundary_name='federation_gateway',
            )

        record = self.warrants.issue_warrant(
            'org_live',
            'federated_execution',
            'federation_gateway',
            'user_owner',
            request_payload={'task': 'demo'},
        )
        self.warrants.review_warrant(record['warrant_id'], 'approve', 'user_owner', org_id='org_live')
        store = self.warrants._load_store('org_live')
        store['warrants'][record['warrant_id']]['expires_at'] = '1970-01-01T00:00:00Z'
        self.warrants._save_store(store, 'org_live')
        with self.assertRaises(PermissionError):
            self.warrants.validate_warrant_for_execution(
                record['warrant_id'],
                org_id='org_live',
                action_class='federated_execution',
                boundary_name='federation_gateway',
                actor_id='user_owner',
                request_payload={'task': 'demo'},
            )


if __name__ == '__main__':
    unittest.main()
