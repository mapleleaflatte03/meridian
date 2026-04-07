#!/usr/bin/env python3
import datetime
import os
import sys
import unittest
from unittest import mock


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

import slo_policy


class SloPolicyTests(unittest.TestCase):
    def test_evaluate_observability_returns_healthy_for_fresh_metrics(self):
        metrics = {
            'audit': {'latest_at': '2026-03-25T00:15:00Z'},
            'metering': {'latest_at': '2026-03-25T00:20:00Z', 'total_cost_usd': 1.25},
            'governance': {'proof_settle_latest_at': '2026-03-25T00:10:00Z', 'active_sanctions': 0},
        }
        with mock.patch.object(slo_policy, '_now', return_value=datetime.datetime(2026, 3, 25, 0, 30, 0)):
            evaluation = slo_policy.evaluate_observability(metrics)

        self.assertEqual(evaluation['policy_name'], 'meridian_observability_slo_v1')
        self.assertEqual(evaluation['status'], 'healthy')
        self.assertEqual(evaluation['alert_count'], 0)
        self.assertEqual(evaluation['healthy_objective_count'], 5)

    def test_evaluate_observability_reports_warning_and_breach_thresholds(self):
        metrics = {
            'audit': {'latest_at': '2026-03-24T22:00:00Z'},
            'metering': {'latest_at': '2026-03-24T22:00:00Z', 'total_cost_usd': 120.0},
            'governance': {'proof_settle_latest_at': '2026-03-24T22:00:00Z', 'active_sanctions': 0},
        }
        with mock.patch.object(slo_policy, '_now', return_value=datetime.datetime(2026, 3, 25, 0, 30, 0)):
            evaluation = slo_policy.evaluate_observability(metrics)

        self.assertEqual(evaluation['status'], 'breached')
        self.assertGreaterEqual(evaluation['alert_count'], 1)
        objective_names = {item['name'] for item in evaluation['objectives']}
        self.assertIn('monthly_metering_cost', objective_names)
        self.assertIn('monthly_metering_cost', {item['objective'] for item in evaluation['alerts']})

    def test_proof_settle_freshness_healthy_when_recent(self):
        metrics = {
            'audit': {'latest_at': '2026-03-25T00:15:00Z'},
            'metering': {'latest_at': '2026-03-25T00:20:00Z', 'total_cost_usd': 1.0},
            'governance': {'proof_settle_latest_at': '2026-03-25T00:10:00Z', 'active_sanctions': 0},
        }
        with mock.patch.object(slo_policy, '_now', return_value=datetime.datetime(2026, 3, 25, 0, 30, 0)):
            evaluation = slo_policy.evaluate_observability(metrics)
        obj = next(o for o in evaluation['objectives'] if o['name'] == 'proof_settle_freshness')
        self.assertEqual(obj['status'], 'healthy')

    def test_proof_settle_freshness_warning_when_stale(self):
        metrics = {
            'audit': {'latest_at': '2026-03-25T00:15:00Z'},
            'metering': {'latest_at': '2026-03-25T00:20:00Z', 'total_cost_usd': 1.0},
            'governance': {'proof_settle_latest_at': '2026-03-24T21:00:00Z', 'active_sanctions': 0},
        }
        with mock.patch.object(slo_policy, '_now', return_value=datetime.datetime(2026, 3, 25, 0, 30, 0)):
            evaluation = slo_policy.evaluate_observability(metrics)
        obj = next(o for o in evaluation['objectives'] if o['name'] == 'proof_settle_freshness')
        self.assertEqual(obj['status'], 'warning')

    def test_governance_sanction_breaches_when_active(self):
        metrics = {
            'audit': {'latest_at': '2026-03-25T00:15:00Z'},
            'metering': {'latest_at': '2026-03-25T00:20:00Z', 'total_cost_usd': 1.0},
            'governance': {'proof_settle_latest_at': '2026-03-25T00:10:00Z', 'active_sanctions': 2},
        }
        with mock.patch.object(slo_policy, '_now', return_value=datetime.datetime(2026, 3, 25, 0, 30, 0)):
            evaluation = slo_policy.evaluate_observability(metrics)
        obj = next(o for o in evaluation['objectives'] if o['name'] == 'governance_sanction_clean')
        self.assertEqual(obj['status'], 'breached')
        self.assertEqual(obj['active_sanctions'], 2)
        self.assertEqual(evaluation['status'], 'breached')

    def test_governance_sanction_healthy_when_clean(self):
        metrics = {
            'audit': {'latest_at': '2026-03-25T00:15:00Z'},
            'metering': {'latest_at': '2026-03-25T00:20:00Z', 'total_cost_usd': 1.0},
            'governance': {'proof_settle_latest_at': '2026-03-25T00:10:00Z', 'active_sanctions': 0},
        }
        with mock.patch.object(slo_policy, '_now', return_value=datetime.datetime(2026, 3, 25, 0, 30, 0)):
            evaluation = slo_policy.evaluate_observability(metrics)
        obj = next(o for o in evaluation['objectives'] if o['name'] == 'governance_sanction_clean')
        self.assertEqual(obj['status'], 'healthy')

    def test_all_five_objectives_present(self):
        metrics = {
            'audit': {'latest_at': '2026-03-25T00:15:00Z'},
            'metering': {'latest_at': '2026-03-25T00:20:00Z', 'total_cost_usd': 1.0},
            'governance': {'proof_settle_latest_at': '2026-03-25T00:10:00Z', 'active_sanctions': 0},
        }
        with mock.patch.object(slo_policy, '_now', return_value=datetime.datetime(2026, 3, 25, 0, 30, 0)):
            evaluation = slo_policy.evaluate_observability(metrics)
        names = {o['name'] for o in evaluation['objectives']}
        self.assertEqual(names, {
            'audit_freshness', 'metering_freshness', 'monthly_metering_cost',
            'proof_settle_freshness', 'governance_sanction_clean',
        })
        self.assertEqual(evaluation['objective_count'], 5)


if __name__ == '__main__':
    unittest.main()
