#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from loom_runtime_client import (
    LoomRuntimeContext,
    capability_preflight,
    estimate_capability_cost_usd,
    run_capability,
)


class LoomRuntimeClientFallbackTests(unittest.TestCase):
    def _context(self):
        return LoomRuntimeContext(
            loom_bin="/fake/loom",
            loom_root="/fake/root",
            org_id="org_48b05c21",
            agent_id="agent_atlas",
            runtime_env={"MERIDIAN_AGENT_ATLAS_API_KEY": "token"},
        )

    def test_capability_preflight_accepts_direct_execute_when_service_crashed(self):
        responses = [
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(
                    {
                        "running": False,
                        "service_status": "crashed",
                        "health": "crashed",
                        "transport": "file_ingress",
                    }
                ),
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(
                    {
                        "enabled": True,
                        "verification_status": "builtin",
                        "promotion_state": "builtin",
                    }
                ),
                stderr="",
            ),
        ]

        def _runner(*args, **kwargs):
            return responses.pop(0)

        preflight = capability_preflight(
            self._context(),
            "loom.llm.inference.v1",
            route="test_route",
            runner=_runner,
            transport_allowlist=("http", "socket+http"),
        )

        self.assertTrue(preflight["ok"])
        self.assertEqual(preflight["execution_mode"], "direct_action_execute")
        self.assertFalse(preflight["errors"])
        self.assertTrue(preflight["warnings"])

    def test_run_capability_falls_back_to_direct_execute_when_service_submit_fails(self):
        commands = []
        direct_output = {
            "job_id": "job::org_48b05c21::agent_atlas::research::abc123",
            "worker_status": "completed",
            "runtime_outcome": "worker_executed",
            "worker_result_path": "/fake/root/state/runtime/jobs/abc123/result.json",
        }
        responses = [
            subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="service down"),
            subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(direct_output), stderr=""),
        ]

        def _runner(*args, **kwargs):
            commands.append(args[0])
            return responses.pop(0)

        result = run_capability(
            self._context(),
            "loom.llm.inference.v1",
            {"prompt": "hello"},
            30,
            agent_id="agent_atlas",
            action_type="research",
            resource="manual:test",
            runner=_runner,
            result_loader=lambda path, default=None: {"host_response_json": {"output_text": "ok"}},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["execution_mode"], "direct_action_execute")
        self.assertEqual(result["worker_result"]["host_response_json"]["output_text"], "ok")
        self.assertIn("warnings", result)
        self.assertEqual(result["estimated_cost_usd"], 0.05)
        self.assertIn("--estimated-cost-usd", commands[0])
        self.assertIn("0.05", commands[0])
        self.assertIn("--estimated-cost-usd", commands[1])
        self.assertIn("0.05", commands[1])

    def test_estimate_capability_cost_prefers_payload_override(self):
        cost = estimate_capability_cost_usd(
            "loom.browser.navigate.v1",
            {"url": "https://example.com", "estimated_cost_usd": 0.19},
            action_type="research",
            resource="https://example.com",
        )
        self.assertEqual(cost, 0.19)


if __name__ == "__main__":
    unittest.main()
