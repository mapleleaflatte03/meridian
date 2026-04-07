#!/usr/bin/env python3
"""Tests for treasury predictive risk scoring."""

import os
import sys
import unittest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
KERNEL_DIR = os.path.dirname(THIS_DIR)
if KERNEL_DIR not in sys.path:
    sys.path.insert(0, KERNEL_DIR)

from treasury_risk import (
    RiskInput,
    assess_risk,
    compute_burn_rate,
    predict_runway_days,
    RISK_HEALTHY,
    RISK_WARNING,
    RISK_CRITICAL,
)


class TestBurnRate(unittest.TestCase):
    def test_burn_rate_from_transactions(self):
        txns = [
            {'amount_usd': -10.0, 'timestamp': 1000},
            {'amount_usd': -5.0, 'timestamp': 2000},
            {'amount_usd': 20.0, 'timestamp': 3000},  # deposit, ignored for burn
        ]
        rate = compute_burn_rate(txns, window_days=30)
        self.assertGreater(rate, 0)

    def test_burn_rate_empty_transactions(self):
        rate = compute_burn_rate([], window_days=30)
        self.assertEqual(rate, 0.0)

    def test_burn_rate_ignores_deposits(self):
        txns = [{'amount_usd': 100.0, 'timestamp': 1000}]
        rate = compute_burn_rate(txns, window_days=30)
        self.assertEqual(rate, 0.0)


class TestRunwayPrediction(unittest.TestCase):
    def test_runway_with_known_burn(self):
        days = predict_runway_days(balance_usd=100.0, burn_rate_per_day=10.0)
        self.assertEqual(days, 10)

    def test_runway_zero_burn_is_infinite(self):
        days = predict_runway_days(balance_usd=100.0, burn_rate_per_day=0.0)
        self.assertEqual(days, -1)

    def test_runway_zero_balance(self):
        days = predict_runway_days(balance_usd=0.0, burn_rate_per_day=10.0)
        self.assertEqual(days, 0)


class TestRiskAssessment(unittest.TestCase):
    def test_healthy_treasury(self):
        result = assess_risk(RiskInput(
            balance_usd=100.0,
            reserve_floor_usd=20.0,
            burn_rate_per_day=1.0,
            active_sanctions=0,
            pending_payouts_usd=5.0,
        ))
        self.assertEqual(result.level, RISK_HEALTHY)
        self.assertGreater(result.runway_days, 0)
        self.assertFalse(result.court_warning)

    def test_warning_near_floor(self):
        result = assess_risk(RiskInput(
            balance_usd=25.0,
            reserve_floor_usd=20.0,
            burn_rate_per_day=2.0,
            active_sanctions=0,
            pending_payouts_usd=0.0,
        ))
        self.assertEqual(result.level, RISK_WARNING)

    def test_critical_below_floor(self):
        result = assess_risk(RiskInput(
            balance_usd=15.0,
            reserve_floor_usd=20.0,
            burn_rate_per_day=5.0,
            active_sanctions=0,
            pending_payouts_usd=0.0,
        ))
        self.assertEqual(result.level, RISK_CRITICAL)

    def test_sanctions_trigger_court_warning(self):
        result = assess_risk(RiskInput(
            balance_usd=100.0,
            reserve_floor_usd=20.0,
            burn_rate_per_day=1.0,
            active_sanctions=2,
            pending_payouts_usd=0.0,
        ))
        self.assertTrue(result.court_warning)

    def test_pending_payouts_reduce_effective_balance(self):
        result = assess_risk(RiskInput(
            balance_usd=30.0,
            reserve_floor_usd=20.0,
            burn_rate_per_day=1.0,
            active_sanctions=0,
            pending_payouts_usd=15.0,
        ))
        # effective balance = 30 - 15 = 15, below floor 20
        self.assertEqual(result.level, RISK_CRITICAL)

    def test_risk_output_is_deterministic(self):
        inp = RiskInput(
            balance_usd=50.0,
            reserve_floor_usd=20.0,
            burn_rate_per_day=2.0,
            active_sanctions=0,
            pending_payouts_usd=5.0,
        )
        r1 = assess_risk(inp)
        r2 = assess_risk(inp)
        self.assertEqual(r1.level, r2.level)
        self.assertEqual(r1.runway_days, r2.runway_days)
        self.assertEqual(r1.effective_balance_usd, r2.effective_balance_usd)

    def test_risk_to_dict(self):
        result = assess_risk(RiskInput(
            balance_usd=100.0,
            reserve_floor_usd=20.0,
            burn_rate_per_day=1.0,
            active_sanctions=0,
            pending_payouts_usd=0.0,
        ))
        d = result.to_dict()
        self.assertIn('level', d)
        self.assertIn('runway_days', d)
        self.assertIn('effective_balance_usd', d)
        self.assertIn('court_warning', d)
        self.assertIn('authority_gate', d)


if __name__ == '__main__':
    unittest.main()
