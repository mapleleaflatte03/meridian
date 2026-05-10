#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

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

    def test_run_capability_falls_back_when_file_ingress_stays_staged(self):
        commands = []
        with tempfile.TemporaryDirectory() as tmpdir:
            receipt_path = os.path.join(tmpdir, "missing-receipt.json")
            responses = [
                subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "status": "service_submit_accepted",
                            "transport": "file_ingress",
                            "job_id": "abc456",
                            "ingress_receipt_path": receipt_path,
                        }
                    ),
                    stderr="",
                ),
                subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=json.dumps({"job_status": "completed"}),
                    stderr="",
                ),
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
                sleeper=lambda _seconds: None,
                result_loader=lambda path, default=None: {"host_response_json": {"output_text": "ok"}},
            )

        self.assertTrue(result["ok"])
        self.assertIn("warnings", result)
        self.assertIn("staged file_ingress", result["warnings"][0])
        self.assertEqual(result["job_id"], "abc456")
        self.assertEqual(result["worker_result"]["host_response_json"]["output_text"], "ok")
        self.assertEqual(len(commands), 2)

    def test_run_capability_accepts_completed_job_record_after_inspect_timeout(self):
        commands = []
        responses = [
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps({"status": "service_submit_accepted", "transport": "http", "job_id": "abc999"}),
                stderr="",
            ),
        ]

        def _runner(*args, **kwargs):
            commands.append(args[0])
            if responses:
                return responses.pop(0)
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="temporary inspect failure")

        context = LoomRuntimeContext(
            loom_bin="/fake/loom",
            loom_root="/fake/root",
            org_id="org_48b05c21",
            agent_id="agent_atlas",
            runtime_env={"MERIDIAN_AGENT_ATLAS_API_KEY": "token"},
        )

        with mock.patch("loom_runtime_client._load_job_record", return_value={"job_status": "completed"}):
            result = run_capability(
                context,
                "loom.llm.inference.v1",
                {"prompt": "hello"},
                1,
                agent_id="agent_atlas",
                action_type="research",
                resource="manual:test",
                runner=_runner,
                sleeper=lambda _seconds: None,
                result_loader=lambda path, default=None: {"host_response_json": {"output_text": "ok-from-job-record"}},
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["job_id"], "abc999")
        self.assertEqual(result["worker_result"]["host_response_json"]["output_text"], "ok-from-job-record")
        self.assertIn("warnings", result)
        self.assertIn("job record completed", result["warnings"][-1])

    def test_run_capability_bypasses_submit_when_runtime_state_is_stale(self):
        commands = []
        direct_output = {
            "job_id": "job::org_48b05c21::agent_forge::execute::abc124",
            "worker_status": "completed",
            "runtime_outcome": "worker_executed",
            "worker_result_path": "/fake/root/state/runtime/jobs/abc124/result.json",
        }

        def _runner(*args, **kwargs):
            commands.append(args[0])
            return subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(direct_output), stderr="")

        with mock.patch(
            "loom_runtime_client._service_state_warning",
            return_value="Loom service runtime state is unhealthy (status=crashed, pid=999, pid_not_running)",
        ):
            with mock.patch("loom_runtime_client._pid_is_running", return_value=False):
                result = run_capability(
                    self._context(),
                    "loom.llm.inference.v1",
                    {"prompt": "hello"},
                    30,
                    agent_id="agent_forge",
                    action_type="execute",
                    resource="manual:build",
                    runner=_runner,
                    result_loader=lambda path, default=None: {"host_response_json": {"output_text": "artifact"}},
                )

        self.assertTrue(result["ok"])
        self.assertEqual(result["execution_mode"], "direct_action_execute")
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][1:3], ["action", "execute"])
        self.assertIn("warnings", result)
        self.assertIn("runtime state is unhealthy", result["warnings"][0])

    def test_run_capability_falls_back_when_file_ingress_is_staged_and_service_dies(self):
        commands = []
        with tempfile.TemporaryDirectory() as tmpdir:
            receipt_path = os.path.join(tmpdir, "missing-receipt.json")
            responses = [
                subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "status": "service_submit_accepted",
                            "transport": "file_ingress",
                            "job_id": "abc457",
                            "ingress_receipt_path": receipt_path,
                        }
                    ),
                    stderr="",
                ),
            ]

            def _runner(*args, **kwargs):
                commands.append(args[0])
                return responses.pop(0)

            with mock.patch("loom_runtime_client._load_job_record", return_value={}):
                with mock.patch(
                    "loom_runtime_client._service_state_warning",
                    side_effect=[
                        "",
                        "Loom service runtime state is unhealthy (status=crashed, pid=999, pid_not_running)",
                    ],
                ):
                    with mock.patch(
                        "loom_runtime_client._direct_execute_capability",
                        return_value={
                            "ok": True,
                            "runtime": "loom",
                            "capability_name": "loom.llm.inference.v1",
                            "execution_mode": "direct_action_execute",
                            "job_id": "job::org_48b05c21::agent_atlas::research::abc457",
                            "worker_result": {"host_response_json": {"output_text": "ok"}},
                        },
                    ) as direct_execute:
                        result = run_capability(
                            self._context(),
                            "loom.llm.inference.v1",
                            {"prompt": "hello"},
                            30,
                            agent_id="agent_atlas",
                            action_type="research",
                            resource="manual:test",
                            runner=_runner,
                            sleeper=lambda _seconds: None,
                            result_loader=lambda path, default=None: {"host_response_json": {"output_text": "ok"}},
                        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["execution_mode"], "direct_action_execute")
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][1:3], ["service", "submit"])
        self.assertEqual(direct_execute.call_count, 1)
        self.assertIn("warnings", result)
        self.assertIn("staged file_ingress", result["warnings"][0])
        self.assertIn("runtime state is unhealthy", result["warnings"][1])

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
