#!/usr/bin/env python3
import importlib.util
import os
import unittest
from unittest import mock

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
SCRIPT_PATH = os.path.join(ROOT, 'ops_meridian_delivery_engine.py')


def _load_script():
    spec = importlib.util.spec_from_file_location('ops_meridian_delivery_engine_test_module', SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


delivery_engine = _load_script()


class MeridianDeliveryEngineTests(unittest.TestCase):
    def test_run_engine_binds_local_payment_evidence_and_reports_blocked_runtime(self):
        with mock.patch.object(delivery_engine.subscription_service, '_loom_delivery_capability', return_value=''),              mock.patch.object(delivery_engine.subscription_service, '_loom_bin', return_value='/tmp/missing-loom-binary'):
            result = delivery_engine.run_engine(disable_outbound_dispatch=True, timeout=1)

        payment_entry = result['payment_entry']
        capture_result = result['capture_result']
        runtime = result['runtime']

        self.assertEqual(payment_entry['type'], 'customer_payment')
        self.assertIn('real broadcast tx hash', payment_entry['note'])
        self.assertTrue(payment_entry['payment_ref'].startswith('prod-exec-'))
        self.assertTrue(payment_entry['order_id'].startswith('ord_prod_'))
        self.assertTrue(payment_entry['tx_hash'].startswith('prod-exec-tx-'))
        self.assertTrue(capture_result['subscription']['payment_verified'])
        self.assertEqual(capture_result['subscription']['payment_evidence']['payment_ref'], payment_entry['payment_ref'])
        self.assertEqual(capture_result['delivery_run']['state'], 'blocked')
        self.assertFalse(capture_result['delivery_run']['delivered'])
        self.assertEqual(capture_result['delivery_artifact'], {})
        self.assertEqual(runtime['capability_name'], '')
        self.assertFalse(runtime['preflight']['ok'])
        self.assertIn('No Loom delivery capability is configured', runtime['preflight']['errors'])
        blockchain = delivery_engine.delivery_blockchain_artifact(result)
        self.assertEqual(blockchain['artifact'], '')
        self.assertEqual(blockchain['artifact_type'], '')
        self.assertFalse(os.path.exists(result['execution_state_dir']))

    def test_delivery_blockchain_artifact_prefers_runtime_tx_hash_before_raw_hex(self):
        result = {
            'capture_result': {
                'delivery_run': {
                    'execution_refs': {
                        'settlement_adapter': 'base_usdc_x402',
                        'proof_type': 'onchain_receipt',
                        'tx_hash': '0xabc123',
                        'proof': {'signed_raw_hex': '0xfeedbeef'},
                    },
                },
            },
        }

        artifact = delivery_engine.delivery_blockchain_artifact(result)
        self.assertEqual(artifact['artifact_type'], 'tx_hash')
        self.assertEqual(artifact['artifact'], '0xabc123')
        self.assertEqual(artifact['artifact_source'], 'delivery_run.execution_refs')
        self.assertEqual(artifact['settlement_adapter'], 'base_usdc_x402')
        self.assertEqual(artifact['proof_type'], 'onchain_receipt')


if __name__ == '__main__':
    unittest.main()
