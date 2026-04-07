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
QUEUE_PATH = ROOT / 'kernel' / 'payout_plan_preview_queue.py'
TREASURY_PATH = ROOT / 'kernel' / 'treasury.py'


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PayoutPlanPreviewQueueTests(unittest.TestCase):
    def setUp(self):
        self.org_id = f'org_preview_queue_{uuid.uuid4().hex[:8]}'
        self.orig_capsule_module = sys.modules.get('capsule')
        self.capsule = _load_module(f'kernel_capsule_preview_{uuid.uuid4().hex}', CAPSULE_PATH)
        sys.modules['capsule'] = self.capsule
        self.queue = _load_module(f'kernel_payout_preview_queue_{uuid.uuid4().hex}', QUEUE_PATH)
        self.treasury = _load_module(f'kernel_treasury_preview_{uuid.uuid4().hex}', TREASURY_PATH)
        self.capsule.init_capsule(self.org_id)
        self.capsule_dir = pathlib.Path(self.capsule.capsule_path(self.org_id, 'ledger.json')).parent

    def tearDown(self):
        shutil.rmtree(self.capsule_dir, ignore_errors=True)
        if self.orig_capsule_module is None:
            sys.modules.pop('capsule', None)
        else:
            sys.modules['capsule'] = self.orig_capsule_module

    def _seed_preview(self):
        return self.queue.upsert_payout_plan_preview(self.org_id, {
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

    def test_inspect_queue_is_read_only_and_reports_operator_ack_need(self):
        self._seed_preview()
        queue_path = pathlib.Path(self.capsule.capsule_path(self.org_id, 'payout_plan_preview_queue.json'))
        before = queue_path.read_text()

        inspection = self.treasury.inspect_payout_plan_preview_queue(self.org_id)

        after = queue_path.read_text()
        self.assertEqual(before, after)
        self.assertEqual(inspection['inspection_summary']['total'], 1)
        self.assertEqual(inspection['inspection_summary']['ready_for_ack'], 1)
        self.assertEqual(inspection['inspection_summary']['requires_operator_ack'], 1)
        self.assertEqual(inspection['payout_plan_previews'][0]['inspection_state'], 'ready_for_ack')
        self.assertTrue(inspection['payout_plan_previews'][0]['inspection_required'])

    def test_acknowledge_preview_records_operator_ack_without_claiming_settlement(self):
        self._seed_preview()

        acknowledged = self.treasury.acknowledge_payout_plan_preview(
            'ptx_preview_demo',
            'user:owner',
            org_id=self.org_id,
            note='reviewed',
        )

        self.assertTrue(acknowledged['acknowledged'])
        self.assertEqual(acknowledged['acknowledged_by'], 'user:owner')
        self.assertEqual(acknowledged['acknowledged_note'], 'reviewed')
        self.assertFalse(acknowledged['settlement_claimed'])

        summary = self.queue.payout_plan_preview_queue_summary(self.org_id)
        self.assertEqual(summary['acknowledged'], 1)
        self.assertEqual(summary['settlement_claimed'], 0)
        self.assertEqual(summary['acknowledgement_pending'], 0)

        queue_path = pathlib.Path(self.capsule.capsule_path(self.org_id, 'payout_plan_preview_queue.json'))
        payload = json.loads(queue_path.read_text())
        record = payload['payout_plan_previews']['ptx_preview_demo']
        self.assertTrue(record['acknowledged'])
        self.assertEqual(record['acknowledged_by'], 'user:owner')
        self.assertEqual(record['preview_state'], 'previewed')


if __name__ == '__main__':
    unittest.main()
