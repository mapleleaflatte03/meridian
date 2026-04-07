#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import shutil
import sys
import unittest
import uuid


ROOT = pathlib.Path(__file__).resolve().parents[2]
CAPSULE_PATH = ROOT / 'kernel' / 'capsule.py'
PREVIEW_QUEUE_PATH = ROOT / 'kernel' / 'payout_plan_preview_queue.py'
CANDIDATE_QUEUE_PATH = ROOT / 'kernel' / 'payout_plan_approval_candidate_queue.py'
TREASURY_PATH = ROOT / 'kernel' / 'treasury.py'


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PayoutPlanApprovalCandidateQueueTests(unittest.TestCase):
    def setUp(self):
        self.org_id = f'org_candidate_queue_{uuid.uuid4().hex[:8]}'
        self.orig_capsule_module = sys.modules.get('capsule')
        self.capsule = _load_module(f'kernel_capsule_candidate_{uuid.uuid4().hex}', CAPSULE_PATH)
        sys.modules['capsule'] = self.capsule
        self.preview_queue = _load_module(f'kernel_preview_queue_candidate_{uuid.uuid4().hex}', PREVIEW_QUEUE_PATH)
        self.candidate_queue = _load_module(f'kernel_candidate_queue_{uuid.uuid4().hex}', CANDIDATE_QUEUE_PATH)
        self.treasury = _load_module(f'kernel_treasury_candidate_{uuid.uuid4().hex}', TREASURY_PATH)
        self.capsule.init_capsule(self.org_id)
        self.capsule_dir = pathlib.Path(self.capsule.capsule_path(self.org_id, 'ledger.json')).parent

    def tearDown(self):
        shutil.rmtree(self.capsule_dir, ignore_errors=True)
        if self.orig_capsule_module is None:
            sys.modules.pop('capsule', None)
        else:
            sys.modules['capsule'] = self.orig_capsule_module

    def _seed_preview(self, *, acknowledged=True):
        preview = self.preview_queue.upsert_payout_plan_preview(self.org_id, {
            'preview_id': 'ptx_preview_demo',
            'proposal_id': 'pay_demo',
            'status_at_preview': 'dispute_window',
            'settlement_adapter': 'internal_ledger',
            'preview_state': 'previewed',
            'dry_run': True,
            'execution_ready': True,
            'settlement_claimed': False,
            'external_settlement_observed': False,
            'preview_truth_source': 'payout_dry_run_and_adapter_contract_only',
            'execution_plan': {
                'tx_ref': 'ptx_preview_demo',
                'amount_usd': 2.0,
                'cash_before': 120.0,
                'cash_after': 118.0,
                'settlement_adapter': 'internal_ledger',
            },
            'proposal_snapshot': {
                'proposal_id': 'pay_demo',
                'status': 'dispute_window',
                'amount_usd': 2.0,
            },
            'generated_at': '2026-03-22T00:00:00Z',
            'previewed_at': '2026-03-22T00:00:00Z',
            'queued_at': '2026-03-22T00:00:00Z',
        })
        if acknowledged:
            preview = self.preview_queue.acknowledge_payout_plan_preview(
                self.org_id,
                'ptx_preview_demo',
                by='user:owner',
                note='reviewed',
            )
        return preview

    def test_promote_acknowledged_preview_creates_candidate_queue_record(self):
        preview = self._seed_preview()

        candidate = self.treasury.promote_payout_plan_preview_to_approval_candidate(
            'ptx_preview_demo',
            'user:owner',
            org_id=self.org_id,
            promotion_note='ready for approval review',
        )

        self.assertEqual(candidate['candidate_id'], 'ptx_preview_demo')
        self.assertEqual(candidate['source_preview_id'], preview['preview_id'])
        self.assertTrue(candidate['candidate_ready_for_approval'])
        self.assertEqual(candidate['promoted_by'], 'user:owner')
        self.assertEqual(candidate['promotion_note'], 'ready for approval review')
        self.assertEqual(candidate['approval_candidate_truth_source'], 'payout_preview_acknowledgement_and_local_policy_only')
        self.assertFalse(candidate['settlement_claimed'])
        self.assertFalse(candidate['external_settlement_observed'])

        queue_path = pathlib.Path(self.capsule.capsule_path(self.org_id, 'payout_plan_approval_candidate_queue.json'))
        self.assertTrue(queue_path.exists())
        payload = json.loads(queue_path.read_text())
        record = payload['payout_plan_approval_candidates']['ptx_preview_demo']
        self.assertTrue(record['candidate_ready_for_approval'])
        self.assertEqual(record['preview_acknowledged_by'], 'user:owner')
        self.assertEqual(record['preview_snapshot']['preview_id'], 'ptx_preview_demo')

        inspection = self.treasury.inspect_payout_plan_approval_candidate_queue(self.org_id)
        self.assertEqual(inspection['inspection_summary']['total'], 1)
        self.assertEqual(inspection['inspection_summary']['ready_for_approval'], 1)
        self.assertEqual(inspection['payout_plan_approval_candidates'][0]['inspection_state'], 'ready_for_approval')

    def test_promote_rejects_unacknowledged_preview(self):
        self._seed_preview(acknowledged=False)

        with self.assertRaises(PermissionError):
            self.treasury.promote_payout_plan_preview_to_approval_candidate(
                'ptx_preview_demo',
                'user:owner',
                org_id=self.org_id,
            )


if __name__ == '__main__':
    unittest.main()
