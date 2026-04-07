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
PREVIEW_QUEUE_PATH = ROOT / 'kernel' / 'federation_handoff_queue.py'
DISPATCH_QUEUE_PATH = ROOT / 'kernel' / 'federation_handoff_dispatch_queue.py'


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FederationHandoffDispatchQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(prefix='meridian-federation-handoff-dispatch-queue-test-')
        self.root = pathlib.Path(self.tmpdir.name)
        self.economy_dir = self.root / 'economy'
        self.capsules_dir = self.root / 'capsules'
        self.kernel_dir = self.root / 'kernel'
        self.economy_dir.mkdir()
        self.capsules_dir.mkdir()
        self.kernel_dir.mkdir()

        self.orig_capsule_module = sys.modules.get('capsule')
        self.orig_preview_queue_module = sys.modules.get('federation_handoff_queue')
        self.orig_capsule_path = None
        self.orig_capsules_dir = None
        self.orig_economy_dir = None
        self.orig_orgs_file = None
        self.orig_aliases = None

        self.capsule = _load_module(f'kernel_capsule_dispatch_{uuid.uuid4().hex}', CAPSULE_PATH)
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

        self.preview_queue = _load_module(f'kernel_federation_handoff_queue_dispatch_{uuid.uuid4().hex}', PREVIEW_QUEUE_PATH)
        sys.modules['federation_handoff_queue'] = self.preview_queue
        self.dispatch_queue = _load_module(f'kernel_federation_handoff_dispatch_queue_{uuid.uuid4().hex}', DISPATCH_QUEUE_PATH)

        self.org_a = f'org_handoff_dispatch_a_{uuid.uuid4().hex[:8]}'
        self.org_b = f'org_handoff_dispatch_b_{uuid.uuid4().hex[:8]}'
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
        if self.orig_preview_queue_module is None:
            sys.modules.pop('federation_handoff_queue', None)
        else:
            sys.modules['federation_handoff_queue'] = self.orig_preview_queue_module
        self.tmpdir.cleanup()

    def _preview(self, handoff_id):
        return {
            'handoff_id': handoff_id,
            'requested_org_id': self.org_b,
            'route_kind': 'remote',
            'route_state': 'remote',
            'route_reason': 'trusted_peer_can_serve_requested_institution',
            'handoff_state': 'previewed',
            'dispatch_ready': True,
            'dispatch_blockers': [],
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

    def test_promote_acknowledged_preview_creates_dispatch_record(self):
        self.preview_queue.upsert_handoff_preview(self.org_a, self._preview('fhdp_dispatch_1'))
        self.preview_queue.acknowledge_handoff_preview(self.org_a, 'fhdp_dispatch_1', by='user:owner', note='reviewed')

        dispatch = self.dispatch_queue.promote_acknowledged_handoff_preview_to_dispatch_record(
            self.org_a,
            'fhdp_dispatch_1',
            promoted_by='user:owner',
            promotion_note='queued for dispatch',
        )

        self.assertEqual(dispatch['dispatch_id'], 'fhdp_dispatch_1')
        self.assertEqual(dispatch['state'], 'dispatchable')
        self.assertTrue(dispatch['dispatch_ready'])
        self.assertEqual(dispatch['acknowledged_by'], 'user:owner')
        self.assertEqual(dispatch['acknowledged_note'], 'reviewed')
        self.assertEqual(dispatch['dispatch_truth_source'], 'acknowledged_handoff_preview_and_local_policy_only')
        self.assertEqual(dispatch['preview_snapshot']['acknowledged_by'], 'user:owner')
        self.assertEqual(dispatch['preview_snapshot']['handoff_id'], 'fhdp_dispatch_1')

        summary = self.dispatch_queue.handoff_dispatch_queue_summary(self.org_a)
        self.assertEqual(summary['total'], 1)
        self.assertEqual(summary['dispatchable'], 1)
        self.assertEqual(summary['dispatched'], 0)
        self.assertEqual(summary['route_kind_counts'], {'remote': 1})

        snapshot = self.dispatch_queue.handoff_dispatch_queue_snapshot(self.org_a)
        self.assertEqual(snapshot['handoff_dispatch_records'][0]['dispatch_id'], 'fhdp_dispatch_1')

    def test_rejects_unacknowledged_preview(self):
        self.preview_queue.upsert_handoff_preview(self.org_a, self._preview('fhdp_dispatch_blocked'))

        with self.assertRaises(PermissionError):
            self.dispatch_queue.promote_acknowledged_handoff_preview_to_dispatch_record(
                self.org_a,
                'fhdp_dispatch_blocked',
                promoted_by='user:owner',
            )


if __name__ == '__main__':
    unittest.main()
