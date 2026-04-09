#!/usr/bin/env python3
import importlib.util
import pathlib
import shutil
import sys
import tempfile
import unittest
import uuid


ROOT = pathlib.Path(__file__).resolve().parents[2]
CAPSULE_PATH = ROOT / 'kernel' / 'capsule.py'
QUEUE_PATH = ROOT / 'kernel' / 'federation_handoff_queue.py'


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FederationHandoffQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(prefix='meridian-federation-handoff-queue-test-')
        self.root = pathlib.Path(self.tmpdir.name)
        self.economy_dir = self.root / 'economy'
        self.capsules_dir = self.root / 'capsules'
        self.kernel_dir = self.root / 'kernel'
        self.economy_dir.mkdir()
        self.capsules_dir.mkdir()
        self.kernel_dir.mkdir()

        self.orig_capsule_module = sys.modules.get('capsule')
        self.orig_capsule_path = None
        self.orig_capsules_dir = None
        self.orig_economy_dir = None
        self.orig_orgs_file = None
        self.orig_aliases = None

        self.capsule = _load_module(f'kernel_capsule_{uuid.uuid4().hex}', CAPSULE_PATH)
        self.orig_capsule_path = self.capsule.capsule_path
        self.orig_capsules_dir = self.capsule.CAPSULES_DIR
        self.orig_economy_dir = self.capsule.ECONOMY_DIR
        self.orig_orgs_file = self.capsule.ORGS_FILE
        self.orig_aliases = dict(self.capsule._CAPSULE_ALIASES)

        sys.modules['capsule'] = self.capsule
        self.capsule.ECONOMY_DIR = str(self.economy_dir)
        self.capsule.CAPSULES_DIR = str(self.capsules_dir)
        self.capsule.ORGS_FILE = str(self.kernel_dir / 'organizations.json')
        self.capsule._CAPSULE_ALIASES.clear()

        self.queue = _load_module(f'kernel_federation_handoff_queue_{uuid.uuid4().hex}', QUEUE_PATH)

        self.org_a = f'org_handoff_queue_a_{uuid.uuid4().hex[:8]}'
        self.org_b = f'org_handoff_queue_b_{uuid.uuid4().hex[:8]}'
        self.capsule.init_capsule(self.org_a)
        self.capsule.init_capsule(self.org_b)

    def tearDown(self):
        self.capsule.ECONOMY_DIR = self.orig_economy_dir
        self.capsule.CAPSULES_DIR = self.orig_capsules_dir
        self.capsule.ORGS_FILE = self.orig_orgs_file
        self.capsule._CAPSULE_ALIASES.clear()
        self.capsule._CAPSULE_ALIASES.update(self.orig_aliases)
        if self.orig_capsule_module is None:
            sys.modules.pop('capsule', None)
        else:
            sys.modules['capsule'] = self.orig_capsule_module
        self.tmpdir.cleanup()

    def _preview(self, handoff_id, *, state='previewed', dispatch_ready=True):
        return {
            'handoff_id': handoff_id,
            'requested_org_id': self.org_b,
            'route_kind': 'remote',
            'route_state': 'remote',
            'route_reason': 'trusted_peer_can_serve_requested_institution',
            'handoff_state': state,
            'dispatch_ready': dispatch_ready,
            'dispatch_blockers': [] if dispatch_ready else ['manual_review_required'],
            'preview_truth_source': 'planner_and_peer_registry_only',
            'dispatch_paths': {
                'send': '/api/federation/send',
                'receive': '/api/federation/receive',
                'receiver_jobs': '/api/federation/execution-jobs',
                'receiver_execute': '/api/federation/execution-jobs/execute',
            },
            'draft_execution_request': {
                'message_type': 'execution_request',
                'boundary_name': 'federation_gateway',
                'identity_model': 'signed_host_service',
                'source_host_id': 'host_alpha',
                'source_institution_id': self.org_a,
                'target_host_id': 'host_beta',
                'target_institution_id': self.org_b,
                'payload_hash': '',
                'warrant_id': '',
                'commitment_id': '',
            },
            'generated_at': '2026-03-22T00:00:00Z',
            'previewed_at': '2026-03-22T00:00:00Z',
            'queued_at': '2026-03-22T00:00:00Z',
            'target_host_id': 'host_beta',
            'target_endpoint_url': 'http://127.0.0.1:19001',
            'peer_host_id': 'host_beta',
            'peer_label': 'Beta Host',
            'peer_trust_state': 'trusted',
            'remote_execution_claimed': False,
            'settlement_claimed': False,
            'external_settlement_observed': False,
        }

    def test_capsule_initializes_handoff_queue_file(self):
        path = pathlib.Path(self.capsule.capsule_path(self.org_a, 'federation_handoff_queue.json'))
        self.assertTrue(path.exists())
        payload = self.queue._load_store(self.org_a)
        self.assertEqual(payload['handoff_previews'], {})
        self.assertIn('previewed', payload['states'])

    def test_upsert_persists_and_reloads_preview(self):
        created = self.queue.upsert_handoff_preview(self.org_a, self._preview('fhdp_demo_1'))
        self.assertEqual(created['handoff_id'], 'fhdp_demo_1')
        self.assertEqual(created['state'], 'previewed')
        self.assertTrue(created['preview_digest'])

        fetched = self.queue.get_handoff_preview('fhdp_demo_1', self.org_a)
        self.assertEqual(fetched['requested_org_id'], self.org_b)
        self.assertEqual(fetched['draft_execution_request']['target_host_id'], 'host_beta')

        listed = self.queue.list_handoff_previews(self.org_a)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]['handoff_id'], 'fhdp_demo_1')

        summary = self.queue.handoff_preview_queue_summary(self.org_a)
        self.assertEqual(summary['total'], 1)
        self.assertEqual(summary['previewed'], 1)
        self.assertEqual(summary['dispatch_ready'], 1)
        self.assertEqual(summary['route_kind_counts'], {'remote': 1})

    def test_acknowledge_preview_records_operator_ack_without_claiming_delivery(self):
        self.queue.upsert_handoff_preview(self.org_a, self._preview('fhdp_demo_ack'))

        acknowledged = self.queue.acknowledge_handoff_preview(
            self.org_a,
            'fhdp_demo_ack',
            by='user:owner',
            note='reviewed',
        )

        self.assertTrue(acknowledged['acknowledged'])
        self.assertEqual(acknowledged['acknowledged_by'], 'user:owner')
        self.assertEqual(acknowledged['acknowledged_note'], 'reviewed')
        self.assertFalse(acknowledged['settlement_claimed'])
        self.assertFalse(acknowledged['external_settlement_observed'])

        summary = self.queue.handoff_preview_queue_summary(self.org_a)
        self.assertEqual(summary['acknowledged'], 1)
        self.assertEqual(summary['acknowledgement_pending'], 0)
        self.assertEqual(summary['remote_execution_claimed'], 0)

        fetched = self.queue.get_handoff_preview('fhdp_demo_ack', self.org_a)
        self.assertTrue(fetched['acknowledged'])
        self.assertEqual(fetched['acknowledged_by'], 'user:owner')

    def test_snapshot_filters_and_sorts_records(self):
        self.queue.upsert_handoff_preview(self.org_a, self._preview('fhdp_demo_2'))
        self.queue.upsert_handoff_preview(
            self.org_a,
            self._preview('fhdp_demo_3', state='blocked', dispatch_ready=False),
        )

        snapshot = self.queue.handoff_preview_queue_snapshot(self.org_a, state='previewed')
        self.assertEqual(snapshot['summary']['total'], 2)
        self.assertEqual(len(snapshot['handoff_previews']), 1)
        self.assertEqual(snapshot['handoff_previews'][0]['handoff_id'], 'fhdp_demo_2')

    def test_list_handoff_previews(self):
        self.queue.upsert_handoff_preview(self.org_a, self._preview('fhdp_demo_4', state='previewed'))
        self.queue.upsert_handoff_preview(self.org_a, self._preview('fhdp_demo_5', state='blocked', dispatch_ready=False))
        self.queue.upsert_handoff_preview(self.org_a, self._preview('fhdp_demo_6', state='previewed'))

        # Without state filter
        all_previews = self.queue.list_handoff_previews(self.org_a)
        self.assertEqual(len(all_previews), 3)
        self.assertEqual(set(p['handoff_id'] for p in all_previews), {'fhdp_demo_4', 'fhdp_demo_5', 'fhdp_demo_6'})

        # Filter by 'previewed' state
        previewed_previews = self.queue.list_handoff_previews(self.org_a, state='previewed')
        self.assertEqual(len(previewed_previews), 2)
        self.assertEqual(set(p['handoff_id'] for p in previewed_previews), {'fhdp_demo_4', 'fhdp_demo_6'})

        # Filter by 'blocked' state
        blocked_previews = self.queue.list_handoff_previews(self.org_a, state='blocked')
        self.assertEqual(len(blocked_previews), 1)
        self.assertEqual(blocked_previews[0]['handoff_id'], 'fhdp_demo_5')

        # Filter by non-existent state
        empty_previews = self.queue.list_handoff_previews(self.org_a, state='non_existent_state')
        self.assertEqual(len(empty_previews), 0)


if __name__ == '__main__':
    unittest.main()
