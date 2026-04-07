#!/usr/bin/env python3
import importlib.util
import pathlib
import shutil
import unittest
import uuid


ROOT = pathlib.Path(__file__).resolve().parents[2]
CAPSULE_PATH = ROOT / 'kernel' / 'capsule.py'
QUEUE_PATH = ROOT / 'kernel' / 'payout_execution_queue.py'
CAPSULES_DIR = ROOT / 'capsules'


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


queue = _load_module('kernel_payout_execution_queue_test', QUEUE_PATH)
capsule = _load_module('kernel_capsule_test_for_payout_execution_queue', CAPSULE_PATH)


class PayoutExecutionQueueTests(unittest.TestCase):
    def setUp(self):
        self.org_id = f'org_execution_queue_test_{uuid.uuid4().hex[:8]}'
        self.capsule_dir = CAPSULES_DIR / self.org_id
        capsule.init_capsule(self.org_id)

    def tearDown(self):
        shutil.rmtree(self.capsule_dir, ignore_errors=True)

    def _record(self, execution_id, *, state='previewed'):
        return {
            'execution_id': execution_id,
            'proposal_id': 'pay_demo',
            'warrant_id': 'war_exec_demo',
            'settlement_adapter': 'internal_ledger',
            'state': state,
            'dispatch_ready': state in ('dispatchable', 'executed'),
            'dispatch_blockers': [] if state in ('dispatchable', 'executed') else ['preview_only'],
            'execution_ready': state in ('dispatchable', 'executed'),
            'settlement_claimed': False,
            'external_settlement_observed': False,
            'proof_type': 'ledger_transaction',
            'tx_hash': '0xfeedbeef',
            'execution_refs': {'tx_ref': execution_id},
            'execution_plan': {'tx_ref': execution_id, 'amount_usd': 2.0},
            'proposal_snapshot': {'proposal_id': 'pay_demo', 'status': 'dispute_window'},
            'adapter_contract_snapshot': {'adapter_id': 'internal_ledger'},
            'adapter_contract_digest': 'digest_demo',
            'generated_at': '2026-03-22T00:00:00Z',
            'queued_at': '2026-03-22T00:00:00Z',
        }

    def test_upsert_persists_execution_record_and_summary(self):
        created = queue.upsert_payout_execution_record(self.org_id, self._record('ptx_exec_1', state='dispatchable'))

        self.assertEqual(created['execution_id'], 'ptx_exec_1')
        self.assertEqual(created['state'], 'dispatchable')
        self.assertTrue(created['dispatch_ready'])
        self.assertEqual(created['execution_digest'], queue._execution_digest(created))

        fetched = queue.get_payout_execution_record('ptx_exec_1', self.org_id)
        self.assertEqual(fetched['proposal_id'], 'pay_demo')
        self.assertEqual(fetched['execution_state'], 'dispatchable')

        listed = queue.list_payout_execution_records(self.org_id)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]['execution_id'], 'ptx_exec_1')

        summary = queue.payout_execution_queue_summary(self.org_id)
        self.assertEqual(summary['total'], 1)
        self.assertEqual(summary['dispatchable'], 1)
        self.assertEqual(summary['adapter_counts'], {'internal_ledger': 1})

    def test_upsert_is_idempotent_and_tracks_execution_transition(self):
        queue.upsert_payout_execution_record(self.org_id, self._record('ptx_exec_2', state='previewed'))
        updated = queue.upsert_payout_execution_record(self.org_id, self._record('ptx_exec_2', state='executed'))

        self.assertEqual(updated['state'], 'executed')
        self.assertEqual(updated['execution_state'], 'executed')
        self.assertEqual(queue.list_payout_execution_records(self.org_id, state='executed')[0]['execution_id'], 'ptx_exec_2')
        self.assertEqual(queue.payout_execution_queue_summary(self.org_id)['executed'], 1)


if __name__ == '__main__':
    unittest.main()
