#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import shutil
import tempfile
import unittest
import uuid


ROOT = pathlib.Path(__file__).resolve().parents[2]
WARRANTS_PATH = ROOT / 'kernel' / 'warrants.py'
CAPSULE_PATH = ROOT / 'kernel' / 'capsule.py'
CAPSULES_DIR = ROOT / 'capsules'


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


warrants = _load_module('kernel_warrants_test', WARRANTS_PATH)
capsule = _load_module('kernel_capsule_test_for_warrants', CAPSULE_PATH)


class WarrantCapsuleTests(unittest.TestCase):
    def setUp(self):
        self.org_id = f'org_warrant_test_{uuid.uuid4().hex[:8]}'
        self.capsule_dir = CAPSULES_DIR / self.org_id
        capsule.init_capsule(self.org_id)

    def tearDown(self):
        shutil.rmtree(self.capsule_dir, ignore_errors=True)

    def test_capsule_initializes_warrants_file(self):
        warrants_path = pathlib.Path(capsule.capsule_path(self.org_id, 'warrants.json'))
        self.assertTrue(warrants_path.exists())
        payload = json.loads(warrants_path.read_text())
        self.assertEqual(payload['warrants'], {})
        self.assertIn('federated_execution', payload['action_classes'])

    def test_issue_approve_validate_and_execute_warrant(self):
        record = warrants.issue_warrant(
            self.org_id,
            'federated_execution',
            'federation_gateway',
            'user_owner',
            session_id='ses_demo',
            request_payload={'task': 'demo'},
            risk_class='moderate',
        )
        self.assertEqual(record['court_review_state'], 'pending_review')
        approved = warrants.review_warrant(
            record['warrant_id'],
            'approve',
            'user_owner',
            org_id=self.org_id,
        )
        self.assertEqual(approved['court_review_state'], 'approved')
        validated = warrants.validate_warrant_for_execution(
            record['warrant_id'],
            org_id=self.org_id,
            action_class='federated_execution',
            boundary_name='federation_gateway',
            actor_id='user_owner',
            session_id='ses_demo',
            request_payload={'task': 'demo'},
        )
        self.assertEqual(validated['warrant_id'], record['warrant_id'])
        executed = warrants.mark_warrant_executed(
            record['warrant_id'],
            org_id=self.org_id,
            execution_refs={'receipt_id': 'fedrcpt_demo'},
        )
        self.assertEqual(executed['execution_state'], 'executed')
        self.assertEqual(executed['execution_refs']['receipt_id'], 'fedrcpt_demo')

    def test_validate_rejects_request_hash_mismatch(self):
        record = warrants.issue_warrant(
            self.org_id,
            'federated_execution',
            'federation_gateway',
            'user_owner',
            request_payload={'task': 'demo'},
        )
        warrants.review_warrant(record['warrant_id'], 'approve', 'user_owner', org_id=self.org_id)
        with self.assertRaises(PermissionError):
            warrants.validate_warrant_for_execution(
                record['warrant_id'],
                org_id=self.org_id,
                action_class='federated_execution',
                boundary_name='federation_gateway',
                actor_id='user_owner',
                request_payload={'task': 'different'},
            )

    def test_validate_rejects_revoked_warrant(self):
        record = warrants.issue_warrant(
            self.org_id,
            'federated_execution',
            'federation_gateway',
            'user_owner',
        )
        warrants.review_warrant(record['warrant_id'], 'revoke', 'user_owner', org_id=self.org_id)
        with self.assertRaises(PermissionError):
            warrants.validate_warrant_for_execution(
                record['warrant_id'],
                org_id=self.org_id,
                action_class='federated_execution',
                boundary_name='federation_gateway',
            )

    def test_validate_rejects_stayed_warrant(self):
        record = warrants.issue_warrant(
            self.org_id,
            'federated_execution',
            'federation_gateway',
            'user_owner',
        )
        warrants.review_warrant(record['warrant_id'], 'stay', 'user_owner', org_id=self.org_id)
        with self.assertRaises(PermissionError):
            warrants.validate_warrant_for_execution(
                record['warrant_id'],
                org_id=self.org_id,
                action_class='federated_execution',
                boundary_name='federation_gateway',
            )

    def test_validate_rejects_expired_warrant(self):
        record = warrants.issue_warrant(
            self.org_id,
            'federated_execution',
            'federation_gateway',
            'user_owner',
            request_payload={'task': 'demo'},
        )
        warrants.review_warrant(record['warrant_id'], 'approve', 'user_owner', org_id=self.org_id)
        store = warrants._load_store(self.org_id)
        store['warrants'][record['warrant_id']]['expires_at'] = '1970-01-01T00:00:00Z'
        warrants._save_store(store, self.org_id)
        with self.assertRaises(PermissionError):
            warrants.validate_warrant_for_execution(
                record['warrant_id'],
                org_id=self.org_id,
                action_class='federated_execution',
                boundary_name='federation_gateway',
                actor_id='user_owner',
                request_payload={'task': 'demo'},
            )

    def test_message_type_mapping_requires_federated_execution(self):
        self.assertEqual(
            warrants.warrant_action_for_message('execution_request'),
            'federated_execution',
        )
        self.assertEqual(
            warrants.warrant_action_for_message('commitment_breach_notice'),
            'cross_institution_commitment',
        )
        self.assertEqual(warrants.warrant_action_for_message('settlement_notice'), '')


if __name__ == '__main__':
    unittest.main()
