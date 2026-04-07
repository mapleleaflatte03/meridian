#!/usr/bin/env python3
"""Compatibility tests for CI vertical budget checks."""

from __future__ import annotations

import unittest
from unittest import mock

import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

# Ensure local capsule module is used by authority.py absolute import.
for _module in (
    "capsule",
    "authority",
    "court",
    "treasury",
    "organizations",
    "audit",
    "agent_registry",
):
    sys.modules.pop(_module, None)

import ci_vertical


class CiVerticalBudgetCompatibilityTests(unittest.TestCase):
    def test_phase_gate_snapshot_supports_legacy_check_budget_signature(self):
        phase = {
            "phase": "research",
            "agent": "atlas",
            "action": "execute",
            "description": "legacy signature compatibility",
        }
        agent_record = {
            "id": "agent_atlas",
            "name": "Atlas",
            "budget": {"max_per_run_usd": 0.5},
            "risk_state": "nominal",
        }

        with mock.patch.object(ci_vertical, "PIPELINE_PHASES", [phase]), mock.patch.object(
            ci_vertical,
            "_get_registry_agent",
            return_value=agent_record,
        ), mock.patch.object(
            ci_vertical,
            "check_authority",
            return_value=(True, "ok"),
        ), mock.patch.object(
            ci_vertical,
            "check_budget",
            side_effect=lambda agent_id, budget_required: (True, "ok"),  # legacy signature
        ), mock.patch.object(
            ci_vertical,
            "get_restrictions",
            return_value=[],
        ), mock.patch.object(
            ci_vertical,
            "get_sprint_lead",
            return_value=("atlas", 42),
        ):
            phases, blocked = ci_vertical._phase_gate_snapshot(reg={"agents": {}}, org_id="org_test")

        self.assertEqual(len(phases), 1)
        self.assertEqual(blocked, [])
        self.assertTrue(phases[0]["budget_allowed"])


if __name__ == "__main__":
    unittest.main()
