#!/usr/bin/env python3
import importlib.util
import pathlib
import shutil
import unittest
import uuid


ROOT = pathlib.Path(__file__).resolve().parents[2]
JOBS_PATH = ROOT / 'kernel' / 'federated_execution_jobs.py'
CAPSULE_PATH = ROOT / 'kernel' / 'capsule.py'
CAPSULES_DIR = ROOT / 'capsules'


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


jobs = _load_module('kernel_federated_execution_jobs_test', JOBS_PATH)
capsule = _load_module('kernel_capsule_test_for_federated_execution_jobs', CAPSULE_PATH)


class FederatedExecutionJobTests(unittest.TestCase):
    def setUp(self):
        self.org_id = f'org_execution_job_test_{uuid.uuid4().hex[:8]}'
        self.capsule_dir = CAPSULES_DIR / self.org_id
        capsule.init_capsule(self.org_id)

    def tearDown(self):
        shutil.rmtree(self.capsule_dir, ignore_errors=True)

    def _job(self, envelope_id, *, state='pending_local_warrant', message_type='execution_request'):
        return {
            'envelope_id': envelope_id,
            'source_host_id': 'host_alpha',
            'source_institution_id': 'org_alpha',
            'target_host_id': 'host_beta',
            'target_institution_id': 'org_beta',
            'actor_type': 'service',
            'actor_id': 'peer:host_alpha',
            'session_id': 'ses_demo',
            'boundary_name': 'federation_gateway',
            'identity_model': 'signed_host_service',
            'message_type': message_type,
            'sender_warrant_id': 'war_sender',
            'local_warrant_id': '',
            'commitment_id': 'cmt_demo',
            'payload': {'task': envelope_id},
            'payload_hash': '',
            'state': state,
            'received_at': '2026-03-22T00:00:00Z',
            'metadata': {'demo': True},
        }

    def test_capsule_initializes_federated_execution_jobs_file(self):
        path = pathlib.Path(capsule.capsule_path(self.org_id, 'federated_execution_jobs.json'))
        self.assertTrue(path.exists())
        payload = jobs._load_store(self.org_id)
        self.assertEqual(payload['jobs'], {})
        self.assertIn('pending_local_warrant', payload['states'])

    def test_upsert_get_list_and_summary(self):
        created = jobs.upsert_execution_job(self.org_id, self._job('fed_job_1'))
        self.assertEqual(created['envelope_id'], 'fed_job_1')
        self.assertEqual(created['state'], 'pending_local_warrant')
        self.assertTrue(created['job_id'].startswith('fej_'))

        fetched = jobs.get_execution_job('fed_job_1', self.org_id)
        self.assertEqual(fetched['envelope_id'], 'fed_job_1')

        listed = jobs.list_execution_jobs(self.org_id)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]['envelope_id'], 'fed_job_1')

        summary = jobs.execution_job_summary(self.org_id)
        self.assertEqual(summary['total'], 1)
        self.assertEqual(summary['pending_local_warrant'], 1)
        self.assertEqual(summary['message_type_counts'], {'execution_request': 1})

    def test_upsert_persists_request_and_gap_objects(self):
        created = jobs.upsert_execution_job(self.org_id, self._job('fed_job_request'))
        self.assertEqual(created['request']['request_id'], 'fed_job_request')
        self.assertEqual(created['request']['request_type'], 'execution_request')
        self.assertEqual(created['request']['claims']['envelope_id'], 'fed_job_request')
        self.assertEqual(created['request']['claims']['message_type'], 'execution_request')
        self.assertEqual(created['request']['payload'], {'task': 'fed_job_request'})
        self.assertEqual(created['gap']['request_id'], 'fed_job_request')
        self.assertEqual(created['gap']['request_type'], 'execution_request')
        self.assertEqual(created['gap']['status'], 'pending_local_warrant')
        self.assertEqual(created['gap']['metadata'], {'demo': True})
        self.assertEqual(created['gap']['evidence_refs'][0], 'federation_envelope:fed_job_request')
        self.assertTrue(created['gap']['evidence_refs'][1].startswith('payload_hash:'))

        fetched = jobs.get_execution_job('fed_job_request', self.org_id)
        self.assertEqual(fetched['request']['request_id'], 'fed_job_request')
        self.assertEqual(fetched['gap']['status'], 'pending_local_warrant')
        self.assertEqual(fetched['gap']['metadata'], {'demo': True})

    def test_normalize_store_preserves_persisted_request_hash_domain(self):
        request_object = {
            'request_id': 'fed_job_hash',
            'request_type': 'execution_request',
            'claims': {
                'envelope_id': 'fed_job_hash',
                'source_host_id': 'host_alpha',
                'source_institution_id': 'org_alpha',
                'target_host_id': 'host_beta',
                'target_institution_id': 'org_beta',
                'actor_type': 'service',
                'actor_id': 'peer:host_alpha',
                'session_id': 'ses_demo',
                'boundary_name': 'federation_gateway',
                'identity_model': 'signed_host_service',
                'message_type': 'execution_request',
                'sender_warrant_id': 'war_sender',
                'commitment_id': 'cmt_demo',
                'payload_hash': 'hash_demo',
            },
            'receipt': {
                'receipt_id': 'fedrcpt_demo',
                'accepted_at': '2026-03-22T00:00:00Z',
                'receiver_host_id': 'host_beta',
                'receiver_institution_id': 'org_beta',
                'message_type': 'execution_request',
                'boundary_name': 'federation_gateway',
                'identity_model': 'signed_host_service',
            },
            'payload': {'task': 'demo'},
            'payload_hash': 'hash_demo',
            'evidence_refs': [
                'federation_envelope:fed_job_hash',
                'federation_receipt:fedrcpt_demo',
                'payload_hash:hash_demo',
            ],
        }
        created = jobs.upsert_execution_job(
            self.org_id,
            self._job('fed_job_hash'),
            local_warrant_id='war_local_demo',
            request=request_object,
        )
        self.assertEqual(created['request'], request_object)
        fetched = jobs.get_execution_job('fed_job_hash', self.org_id)
        self.assertEqual(fetched['request'], request_object)

    def test_upsert_is_idempotent_by_envelope_id_and_tracks_state(self):
        jobs.upsert_execution_job(self.org_id, self._job('fed_job_2'))
        updated = jobs.upsert_execution_job(
            self.org_id,
            self._job(
                'fed_job_2',
                state='ready',
            ),
        )
        self.assertEqual(updated['envelope_id'], 'fed_job_2')
        self.assertEqual(updated['state'], 'ready')

        updated = jobs.upsert_execution_job(
            self.org_id,
            self._job(
                'fed_job_2',
                state='executed',
            ),
        )
        self.assertEqual(updated['state'], 'executed')
        self.assertTrue(updated['executed_at'])

        listed = jobs.list_execution_jobs(self.org_id)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]['state'], 'executed')
        self.assertEqual(jobs.list_execution_jobs(self.org_id, state='executed')[0]['envelope_id'], 'fed_job_2')

        summary = jobs.execution_job_summary(self.org_id)
        self.assertEqual(summary['executed'], 1)

    def test_sync_execution_job_for_local_warrant_updates_state(self):
        created = jobs.upsert_execution_job(
            self.org_id,
            self._job('fed_job_3', state='pending_local_warrant'),
            local_warrant_id='war_local_demo',
        )
        self.assertEqual(created['state'], 'pending_local_warrant')

        updated = jobs.sync_execution_job_for_local_warrant(
            self.org_id,
            'war_local_demo',
            state='ready',
            note='Local warrant approved',
            metadata={'review_decision': 'approve'},
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated['job_id'], created['job_id'])
        self.assertEqual(updated['state'], 'ready')
        self.assertEqual(updated['metadata']['review_decision'], 'approve')
        self.assertEqual(updated['note'], 'Local warrant approved')


if __name__ == '__main__':
    unittest.main()
