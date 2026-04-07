import os
import sys
import unittest

KERNEL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if KERNEL_DIR not in sys.path:
    sys.path.insert(0, KERNEL_DIR)

import admission_policy


class AdmissionPolicyTests(unittest.TestCase):
    def test_loom_native_is_admitted(self):
        result = admission_policy.check_admission('loom_native')
        self.assertTrue(result['admitted'])
        self.assertEqual(result['policy'], 'loom_first')
        self.assertEqual(result['contract_score'], 7)

    def test_legacy_bridge_is_admitted_via_adapter_policy(self):
        result = admission_policy.check_admission('legacy_v1_compatible')
        self.assertTrue(result['admitted'])
        self.assertEqual(result['policy'], 'adapter_bridge')
        self.assertTrue(result['adapter_supplied'])
        self.assertEqual(result['contract_status'], 'reference_adapter')

    def test_planned_runtime_is_never_admitted(self):
        result = admission_policy.check_admission('mcp_generic')
        self.assertFalse(result['admitted'])
        self.assertEqual(result['policy'], 'planned')
        self.assertIn('cannot be admitted', ' '.join(result['violations']))


if __name__ == '__main__':
    unittest.main()
