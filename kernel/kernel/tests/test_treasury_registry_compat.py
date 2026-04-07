#!/usr/bin/env python3
"""Compatibility tests for treasury registry lookups."""

import os
import sys
import types
import unittest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
KERNEL_DIR = os.path.dirname(THIS_DIR)
if KERNEL_DIR not in sys.path:
    sys.path.insert(0, KERNEL_DIR)

import treasury


class TreasuryRegistryCompatTests(unittest.TestCase):
    def test_check_budget_supports_legacy_registry_signature_without_org_id(self):
        legacy_registry = types.ModuleType('agent_registry')

        def _legacy_lookup(economy_key):
            if economy_key == 'atlas':
                return {'id': 'agent_atlas'}
            return None

        legacy_registry.get_agent_by_economy_key = _legacy_lookup

        original_module = sys.modules.get('agent_registry')
        original_agent_check_budget = treasury._agent_check_budget
        original_budget_summary = treasury.budget_reservation_summary
        sys.modules['agent_registry'] = legacy_registry
        treasury._agent_check_budget = lambda agent_id, cost: (True, 'ok')
        treasury.budget_reservation_summary = lambda org_id, agent_id=None: {
            'runway_usd': 10.0,
            'available_for_reservation_usd': 10.0,
        }
        try:
            allowed, reason = treasury.check_budget('atlas', 1.0, org_id='org_test')
            self.assertTrue(allowed)
            self.assertEqual(reason, 'ok')
        finally:
            treasury._agent_check_budget = original_agent_check_budget
            treasury.budget_reservation_summary = original_budget_summary
            if original_module is not None:
                sys.modules['agent_registry'] = original_module
            else:
                sys.modules.pop('agent_registry', None)


if __name__ == '__main__':
    unittest.main()
