#!/usr/bin/env python3
"""Tests for the /api/memory/* gateway routes.

Covers:
- _build_memory_search_response shapes and filters
- _build_memory_receipts_response summaries and filters
- _build_memory_graph_response shape and validation
- _build_memory_fork_response and _build_memory_replay_response governance wiring
- subprocess invocation arg construction (single-agent and --all-agents)
- Origin-protected route is wired and not in _public_read_allowed
- Content truncation when include_content=True
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import meridian_gateway as gateway


GATEWAY_PY = Path(__file__).resolve().parent / "meridian_gateway.py"


class TestBuildMemorySearchResponse(unittest.TestCase):
    def test_requires_agent_id_or_all_agents(self):
        result = gateway._build_memory_search_response(
            query="anything",
            agent_id=None,
            all_agents=False,
            category=None,
            key_prefix=None,
            tags=None,
            limit=20,
            include_content=False,
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(
            result["output"], "memory_search_requires_agent_id_or_all_agents"
        )
        self.assertEqual(result["matches"], [])

    def test_all_agents_passes_flag_to_loom(self):
        captured = {}

        def fake_run(args):
            captured["args"] = list(args)
            return {"ok": True, "payload": []}

        with patch.object(gateway, "_run_loom_memory_command", side_effect=fake_run):
            result = gateway._build_memory_search_response(
                query="ship",
                agent_id=None,
                all_agents=True,
                category=None,
                key_prefix=None,
                tags=None,
                limit=5,
                include_content=False,
            )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["scope"], "all_agents")
        self.assertIsNone(result["agent_id"])
        self.assertIn("--all-agents", captured["args"])
        self.assertIn("--text", captured["args"])
        self.assertEqual(captured["args"][captured["args"].index("--text") + 1], "ship")
        self.assertIn("--limit", captured["args"])
        self.assertEqual(captured["args"][captured["args"].index("--limit") + 1], "5")
        self.assertNotIn("--agent-id", captured["args"])

    def test_single_agent_passes_agent_id_to_loom(self):
        captured = {}

        def fake_run(args):
            captured["args"] = list(args)
            return {"ok": True, "payload": []}

        with patch.object(gateway, "_run_loom_memory_command", side_effect=fake_run):
            gateway._build_memory_search_response(
                query="hanoi",
                agent_id="atlas",
                all_agents=False,
                category="core",
                key_prefix="morning_",
                tags=None,
                limit=10,
                include_content=False,
            )
        args = captured["args"]
        self.assertIn("--agent-id", args)
        self.assertEqual(args[args.index("--agent-id") + 1], "atlas")
        self.assertNotIn("--all-agents", args)
        self.assertEqual(args[args.index("--category") + 1], "core")
        self.assertEqual(args[args.index("--key-prefix") + 1], "morning_")

    def test_redacts_content_by_default(self):
        sample_entries = [
            {
                "agent_id": "atlas",
                "category": "core",
                "key": "morning_brief",
                "content": "secret-internal-note",
                "updated_at": 1234567890,
                "created_at": 1234567000,
            }
        ]

        def fake_run(args):
            return {"ok": True, "payload": sample_entries}

        with patch.object(gateway, "_run_loom_memory_command", side_effect=fake_run):
            result = gateway._build_memory_search_response(
                query="brief",
                agent_id="atlas",
                all_agents=False,
                category=None,
                key_prefix=None,
                tags=None,
                limit=20,
                include_content=False,
            )
        self.assertEqual(result["match_count"], 1)
        match = result["matches"][0]
        self.assertEqual(match["agent_id"], "atlas")
        self.assertEqual(match["key"], "morning_brief")
        self.assertEqual(match["updated_at"], 1234567890)
        # Content must NOT leak when include_content is false.
        self.assertNotIn("content", match)

    def test_truncates_long_content_when_included(self):
        long_text = "x" * (gateway.MEMORY_SEARCH_API_CONTENT_PREVIEW_CHARS + 50)
        sample_entries = [
            {
                "agent_id": "atlas",
                "category": "core",
                "key": "long_key",
                "content": long_text,
                "updated_at": 1,
                "created_at": 0,
            }
        ]

        def fake_run(args):
            return {"ok": True, "payload": sample_entries}

        with patch.object(gateway, "_run_loom_memory_command", side_effect=fake_run):
            result = gateway._build_memory_search_response(
                query="",
                agent_id="atlas",
                all_agents=False,
                category=None,
                key_prefix=None,
                tags=None,
                limit=1,
                include_content=True,
            )
        match = result["matches"][0]
        self.assertTrue(match["content_truncated"])
        self.assertTrue(match["content"].endswith("…"))
        self.assertEqual(
            len(match["content"]),
            gateway.MEMORY_SEARCH_API_CONTENT_PREVIEW_CHARS + 1,  # +1 for the ellipsis
        )

    def test_loom_failure_propagates_as_error(self):
        def fake_run(args):
            return {"ok": False, "error": "synthetic_failure_message"}

        with patch.object(gateway, "_run_loom_memory_command", side_effect=fake_run):
            result = gateway._build_memory_search_response(
                query="anything",
                agent_id="atlas",
                all_agents=False,
                category=None,
                key_prefix=None,
                tags=None,
                limit=20,
                include_content=False,
            )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["output"], "synthetic_failure_message")
        self.assertEqual(result["matches"], [])

    def test_forwards_repeated_tags_to_loom_and_response(self):
        captured = {}
        sample_entries = [
            {
                "agent_id": "atlas",
                "category": "core",
                "key": "release_note",
                "content": "vn rollout",
                "tags": ["release", "vietnam"],
                "updated_at": 12,
                "created_at": 10,
            }
        ]

        def fake_run(args):
            captured["args"] = list(args)
            return {"ok": True, "payload": sample_entries}

        with patch.object(gateway, "_run_loom_memory_command", side_effect=fake_run):
            result = gateway._build_memory_search_response(
                query="rollout",
                agent_id="atlas",
                all_agents=False,
                category=None,
                key_prefix=None,
                tags=["release", "vietnam"],
                limit=5,
                include_content=False,
            )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["tag_filter"], ["release", "vietnam"])
        self.assertEqual(result["matches"][0]["tags"], ["release", "vietnam"])
        args = captured["args"]
        self.assertEqual(args.count("--tag"), 2)
        self.assertEqual(
            [args[index + 1] for index, value in enumerate(args) if value == "--tag"],
            ["release", "vietnam"],
        )


class TestBuildMemoryOverviewResponse(unittest.TestCase):
    def test_overview_propagates_loom_failure(self):
        def fake_run(args):
            self.assertEqual(args, ["overview"])
            return {"ok": False, "error": "synthetic_overview_failure"}

        with patch.object(gateway, "_run_loom_memory_command", side_effect=fake_run):
            result = gateway._build_memory_overview_response()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["output"], "synthetic_overview_failure")

    def test_overview_shapes_aggregates(self):
        sample = {
            "agent_count": 2,
            "total_entries": 5,
            "total_bytes": 1024,
            "tag_count": 3,
            "tags": ["audit", "release", "vietnam"],
            "policy": {"max_entry_bytes": 4096, "retention_days": 30},
            "agents": [
                {
                    "agent_id": "atlas",
                    "entry_count": 3,
                    "total_bytes": 600,
                    "categories": ["core", "notes"],
                    "tags": ["release", "vietnam"],
                },
                {
                    "agent_id": "quill",
                    "entry_count": 2,
                    "total_bytes": 424,
                    "categories": ["drafts"],
                    "tags": ["audit"],
                },
            ],
        }

        def fake_run(args):
            return {"ok": True, "payload": sample}

        with patch.object(gateway, "_run_loom_memory_command", side_effect=fake_run):
            result = gateway._build_memory_overview_response()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["agent_count"], 2)
        self.assertEqual(result["total_entries"], 5)
        self.assertEqual(result["total_bytes"], 1024)
        self.assertEqual(result["tag_count"], 3)
        self.assertEqual(result["tags"], ["audit", "release", "vietnam"])
        self.assertEqual(result["policy"]["retention_days"], 30)
        self.assertEqual(len(result["agents"]), 2)
        atlas = next(a for a in result["agents"] if a["agent_id"] == "atlas")
        self.assertEqual(atlas["entry_count"], 3)
        self.assertEqual(atlas["category_count"], 2)
        self.assertEqual(atlas["categories"], ["core", "notes"])
        self.assertEqual(atlas["tag_count"], 2)
        self.assertEqual(atlas["tags"], ["release", "vietnam"])

    def test_overview_can_omit_per_agent_breakdown(self):
        sample = {
            "agent_count": 1,
            "total_entries": 1,
            "tag_count": 1,
            "tags": ["release"],
            "agents": [
                {
                    "agent_id": "x",
                    "entry_count": 1,
                    "total_bytes": 10,
                    "categories": [],
                    "tags": ["release"],
                }
            ],
        }

        def fake_run(args):
            return {"ok": True, "payload": sample}

        with patch.object(gateway, "_run_loom_memory_command", side_effect=fake_run):
            result = gateway._build_memory_overview_response(include_agents=False)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["tag_count"], 1)
        self.assertEqual(result["tags"], ["release"])
        self.assertEqual(result["agents"], [])

    def test_overview_handles_unexpected_payload(self):
        def fake_run(args):
            return {"ok": True, "payload": ["not", "a", "dict"]}

        with patch.object(gateway, "_run_loom_memory_command", side_effect=fake_run):
            result = gateway._build_memory_overview_response()
        self.assertEqual(result["status"], "error")
        self.assertEqual(
            result["output"], "memory_overview_unexpected_payload_shape"
        )


class TestBuildMemoryReceiptsResponse(unittest.TestCase):
    def test_receipts_pass_agent_and_limit_to_loom(self):
        captured = {}

        def fake_run(args):
            captured["args"] = list(args)
            return {"ok": True, "payload": []}

        with patch.object(gateway, "_run_loom_memory_command", side_effect=fake_run):
            result = gateway._build_memory_receipts_response(
                agent_id="atlas",
                limit=7,
            )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["agent_id"], "atlas")
        self.assertIn("receipts", captured["args"])
        self.assertEqual(captured["args"][captured["args"].index("--agent-id") + 1], "atlas")
        self.assertEqual(captured["args"][captured["args"].index("--limit") + 1], "7")

    def test_receipts_truncates_large_summaries(self):
        oversized = "x" * (gateway.MEMORY_SEARCH_API_CONTENT_PREVIEW_CHARS + 50)

        def fake_run(args):
            return {
                "ok": True,
                "payload": [
                    {
                        "timestamp_unix_ms": 1,
                        "operation": "write",
                        "agent_id": "atlas",
                        "kind": "memory_receipt",
                        "receipt_hash": "abc123",
                        "input_summary": oversized,
                        "output_summary": oversized,
                        "is_error": False,
                    }
                ],
            }

        with patch.object(gateway, "_run_loom_memory_command", side_effect=fake_run):
            result = gateway._build_memory_receipts_response(agent_id=None, limit=5)
        self.assertEqual(result["status"], "success")
        receipt = result["receipts"][0]
        self.assertTrue(receipt["input_summary_truncated"])
        self.assertTrue(receipt["output_summary_truncated"])
        self.assertTrue(receipt["input_summary"].endswith("…"))
        self.assertTrue(receipt["output_summary"].endswith("…"))

    def test_receipts_propagates_loom_failure(self):
        def fake_run(args):
            return {"ok": False, "error": "synthetic_receipts_failure"}

        with patch.object(gateway, "_run_loom_memory_command", side_effect=fake_run):
            result = gateway._build_memory_receipts_response(agent_id="atlas", limit=2)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["output"], "synthetic_receipts_failure")
        self.assertEqual(result["receipts"], [])


class TestBuildMemoryGraphResponse(unittest.TestCase):
    def test_graph_requires_source_ref(self):
        result = gateway._build_memory_graph_response(
            source_ref="",
            focus_node_id=None,
            direction="both",
            limit=10,
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["output"], "memory_graph_requires_source_ref")

    def test_graph_passes_source_node_direction_and_limit_to_loom(self):
        captured = {}

        def fake_run(args):
            captured["args"] = list(args)
            return {
                "ok": True,
                "payload": {
                    "status": "memory_graph_inspect",
                    "source_ref": "atlas",
                    "total_nodes": 2,
                    "focus_node": {"node_id": "n1"},
                    "ancestor_nodes": [],
                    "descendant_nodes": [],
                    "direction": "ancestors",
                    "limit": 4,
                    "note": "ok",
                },
            }

        with patch.object(gateway, "_run_loom_memory_command", side_effect=fake_run):
            result = gateway._build_memory_graph_response(
                source_ref="atlas",
                focus_node_id="n1",
                direction="ancestors",
                limit=4,
            )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["graph_status"], "memory_graph_inspect")
        self.assertEqual(captured["args"][:3], ["graph", "inspect", "atlas"])
        self.assertEqual(captured["args"][captured["args"].index("--node-id") + 1], "n1")
        self.assertEqual(captured["args"][captured["args"].index("--direction") + 1], "ancestors")
        self.assertEqual(captured["args"][captured["args"].index("--limit") + 1], "4")

    def test_graph_propagates_loom_failure(self):
        def fake_run(args):
            return {"ok": False, "error": "synthetic_graph_failure"}

        with patch.object(gateway, "_run_loom_memory_command", side_effect=fake_run):
            result = gateway._build_memory_graph_response(
                source_ref="atlas",
                focus_node_id=None,
                direction="both",
                limit=10,
            )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["output"], "synthetic_graph_failure")

    def test_graph_rejects_unexpected_payload_shape(self):
        def fake_run(args):
            return {"ok": True, "payload": ["not", "a", "dict"]}

        with patch.object(gateway, "_run_loom_memory_command", side_effect=fake_run):
            result = gateway._build_memory_graph_response(
                source_ref="atlas",
                focus_node_id=None,
                direction="both",
                limit=10,
            )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["output"], "memory_graph_unexpected_payload_shape")


class TestBuildMemoryForkReplayResponse(unittest.TestCase):
    def test_fork_requires_source_and_target(self):
        result = gateway._build_memory_fork_response(
            source_ref="",
            target_agent_id="",
            branch=None,
            focus_node_id=None,
            direction="both",
            limit=10,
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["output"], "memory_fork_requires_source_ref")

        result = gateway._build_memory_fork_response(
            source_ref="atlas",
            target_agent_id="",
            branch=None,
            focus_node_id=None,
            direction="both",
            limit=10,
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["output"], "memory_fork_requires_target_agent_id")

    def test_fork_passes_expected_args(self):
        captured = {}

        def fake_run(args, *, extra_args=None):
            captured["args"] = list(args)
            captured["extra_args"] = list(extra_args or [])
            return {"ok": True, "payload": {"status": "memory_fork_created", "target_agent_id": "quill"}}

        with patch.object(gateway, "_run_loom_memory_json_command", side_effect=fake_run):
            result = gateway._build_memory_fork_response(
                source_ref="atlas",
                target_agent_id="quill",
                branch="warm-start",
                focus_node_id="n1",
                direction="ancestors",
                limit=4,
            )
        self.assertEqual(result["status"], "memory_fork_created")
        self.assertEqual(captured["args"][:4], ["fork", "atlas", "--target-agent-id", "quill"])
        self.assertEqual(captured["args"][captured["args"].index("--branch") + 1], "warm-start")
        self.assertEqual(captured["args"][captured["args"].index("--node-id") + 1], "n1")
        self.assertEqual(captured["args"][captured["args"].index("--direction") + 1], "ancestors")
        self.assertEqual(captured["args"][captured["args"].index("--limit") + 1], "4")
        self.assertEqual(captured["extra_args"], [])

    def test_replay_requires_source_and_target(self):
        result = gateway._build_memory_replay_response(
            source_ref="",
            target_agent_id="",
            org_id="org_test",
            focus_node_id=None,
            direction="both",
            limit=10,
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["output"], "memory_replay_requires_source_ref")

        result = gateway._build_memory_replay_response(
            source_ref="atlas",
            target_agent_id="",
            org_id="org_test",
            focus_node_id=None,
            direction="both",
            limit=10,
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["output"], "memory_replay_requires_target_agent_id")

    def test_replay_passes_kernel_and_org_boundary(self):
        captured = {}

        def fake_run(args, *, extra_args=None):
            captured["args"] = list(args)
            captured["extra_args"] = list(extra_args or [])
            return {"ok": True, "payload": {"status": "memory_replay_applied", "replayed_entries": 2}}

        with patch.object(gateway, "_run_loom_memory_json_command", side_effect=fake_run):
            result = gateway._build_memory_replay_response(
                source_ref="atlas",
                target_agent_id="quill",
                org_id="org_test",
                focus_node_id="n1",
                direction="descendants",
                limit=6,
            )
        self.assertEqual(result["status"], "memory_replay_applied")
        self.assertEqual(captured["args"][:4], ["replay", "atlas", "--target-agent-id", "quill"])
        self.assertEqual(captured["args"][captured["args"].index("--node-id") + 1], "n1")
        self.assertEqual(captured["args"][captured["args"].index("--direction") + 1], "descendants")
        self.assertEqual(captured["args"][captured["args"].index("--limit") + 1], "6")
        self.assertIn("--kernel-path", captured["extra_args"])
        self.assertIn("--org-id", captured["extra_args"])
        self.assertEqual(captured["extra_args"][captured["extra_args"].index("--org-id") + 1], "org_test")

    def test_replay_rejects_unexpected_payload_shape(self):
        def fake_run(args, *, extra_args=None):
            return {"ok": True, "payload": ["not", "a", "dict"]}

        with patch.object(gateway, "_run_loom_memory_json_command", side_effect=fake_run):
            result = gateway._build_memory_replay_response(
                source_ref="atlas",
                target_agent_id="quill",
                org_id="org_test",
                focus_node_id=None,
                direction="both",
                limit=10,
            )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["output"], "memory_replay_unexpected_payload_shape")


class TestBuildMemoryLatestArtifactResponse(unittest.TestCase):
    def test_requires_supported_kind(self):
        result = gateway._build_memory_latest_artifact_response("weird")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["output"], "memory_latest_artifact_requires_supported_kind")

    def test_returns_absent_when_latest_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(gateway, "LOOM_ROOT", tmpdir):
                result = gateway._build_memory_latest_artifact_response("fork")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["kind"], "fork")
        self.assertFalse(result["artifact_present"])
        self.assertIsNone(result["artifact"])

    def test_returns_payload_when_latest_file_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_dir = Path(tmpdir) / "artifacts" / "memory" / "replays"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "latest.json").write_text(
                json.dumps(
                    {
                        "status": "memory_replay_applied",
                        "source_ref": "atlas",
                        "target_agent_id": "quill",
                        "replayed_entries": 2,
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(gateway, "LOOM_ROOT", tmpdir):
                result = gateway._build_memory_latest_artifact_response("replay")
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["artifact_present"])
        self.assertEqual(result["artifact"]["status"], "memory_replay_applied")
        self.assertEqual(result["artifact"]["target_agent_id"], "quill")

    def test_rejects_non_dict_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_dir = Path(tmpdir) / "artifacts" / "memory" / "forks"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "latest.json").write_text(json.dumps(["bad"]), encoding="utf-8")
            with patch.object(gateway, "LOOM_ROOT", tmpdir):
                result = gateway._build_memory_latest_artifact_response("fork")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["output"], "memory_latest_artifact_unexpected_payload_shape")


class TestBuildMemoryArtifactHistoryResponse(unittest.TestCase):
    def test_requires_supported_kind(self):
        result = gateway._build_memory_artifact_history_response("weird", 5)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["output"], "memory_artifact_history_requires_supported_kind")

    def test_returns_empty_history_when_dir_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(gateway, "LOOM_ROOT", tmpdir):
                result = gateway._build_memory_artifact_history_response("fork", 3)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["artifact_count"], 0)


class TestBuildMemoryGovernanceSummaryResponse(unittest.TestCase):
    def test_governance_summary_aggregates_latest_and_history(self):
        with patch.object(
            gateway,
            "_build_memory_latest_artifact_response",
            side_effect=[
                {"status": "success", "artifact_present": True, "artifact": {"status": "memory_fork_created", "target_agent_id": "quill"}},
                {"status": "success", "artifact_present": True, "artifact": {"status": "memory_replay_blocked", "target_agent_id": "quill", "authority_status": "denied"}},
            ],
        ), patch.object(
            gateway,
            "_build_memory_artifact_history_response",
            side_effect=[
                {"status": "success", "artifact_count": 2},
                {"status": "success", "artifact_count": 3},
            ],
        ):
            result = gateway._build_memory_governance_summary_response(7)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["limit"], 7)
        self.assertEqual(result["fork_latest_status"], "memory_fork_created")
        self.assertEqual(result["fork_recent_count"], 2)
        self.assertEqual(result["replay_latest_status"], "memory_replay_blocked")
        self.assertEqual(result["replay_recent_count"], 3)
        self.assertEqual(result["replay_authority_status"], "denied")

    def test_returns_recent_replay_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_dir = Path(tmpdir) / "artifacts" / "memory" / "replays"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "a.json").write_text(
                json.dumps(
                    {
                        "status": "memory_replay_blocked",
                        "source_ref": "atlas",
                        "target_agent_id": "quill",
                        "authority_status": "denied",
                        "replayed_entries": 0,
                    }
                ),
                encoding="utf-8",
            )
            (artifact_dir / "latest.json").write_text("{}", encoding="utf-8")
            with patch.object(gateway, "LOOM_ROOT", tmpdir):
                result = gateway._build_memory_artifact_history_response("replay", 5)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["artifact_count"], 1)
        self.assertEqual(result["artifacts"][0]["status"], "memory_replay_blocked")
        self.assertEqual(result["artifacts"][0]["authority_status"], "denied")
        self.assertGreater(result["artifacts"][0]["timestamp_unix_ms"], 0)

    def test_skips_non_dict_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_dir = Path(tmpdir) / "artifacts" / "memory" / "forks"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "bad.json").write_text(json.dumps(["bad"]), encoding="utf-8")
            with patch.object(gateway, "LOOM_ROOT", tmpdir):
                result = gateway._build_memory_artifact_history_response("fork", 5)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["artifact_count"], 0)


class TestGovernedMemoryOperatorStatus(unittest.TestCase):
    def test_operator_status_projects_compact_summary(self):
        with patch.object(
            gateway,
            "_build_memory_governance_summary_response",
            return_value={
                "status": "success",
                "fork_latest_status": "memory_fork_created",
                "fork_recent_count": 2,
                "fork_target_agent_id": "quill",
                "replay_latest_status": "memory_replay_blocked",
                "replay_recent_count": 1,
                "replay_target_agent_id": "quill",
                "replay_authority_status": "denied",
            },
        ):
            result = gateway._build_governed_memory_operator_status(limit=5)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["fork_latest_status"], "memory_fork_created")
        self.assertEqual(result["fork_recent_count"], 2)
        self.assertEqual(result["replay_latest_status"], "memory_replay_blocked")
        self.assertEqual(result["replay_authority_status"], "denied")

    def test_operator_status_degrades_cleanly(self):
        with patch.object(
            gateway,
            "_build_memory_governance_summary_response",
            return_value={"status": "error", "output": "boom"},
        ):
            result = gateway._build_governed_memory_operator_status(limit=5)
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["output"], "boom")
        self.assertEqual(result["fork_latest_status"], "missing")
        self.assertEqual(result["replay_latest_status"], "missing")

    def test_attach_governed_memory_status_adds_block(self):
        with patch.object(
            gateway,
            "_build_governed_memory_operator_status",
            return_value={"status": "success", "fork_latest_status": "memory_fork_created"},
        ):
            result = gateway._attach_governed_memory_status({"runtime_id": "loom_native"})
        self.assertEqual(result["runtime_id"], "loom_native")
        self.assertEqual(result["governed_memory"]["status"], "success")
        self.assertEqual(result["governed_memory"]["fork_latest_status"], "memory_fork_created")


class TestGovernedMemoryStatusAndOperatorTruth(unittest.TestCase):
    def setUp(self):
        self._cache_snapshot = dict(gateway.WORKSPACE_STATUS_CACHE)
        self._refresh_in_flight = gateway.WORKSPACE_STATUS_REFRESH_IN_FLIGHT

    def tearDown(self):
        gateway.WORKSPACE_STATUS_CACHE.clear()
        gateway.WORKSPACE_STATUS_CACHE.update(self._cache_snapshot)
        gateway.WORKSPACE_STATUS_REFRESH_IN_FLIGHT = self._refresh_in_flight

    def test_workspace_status_snapshot_includes_governed_memory(self):
        gateway.WORKSPACE_STATUS_CACHE["fetched_at_unix_ms"] = 0
        gateway.WORKSPACE_STATUS_CACHE["snapshot"] = None
        gateway.WORKSPACE_STATUS_REFRESH_IN_FLIGHT = False

        def fake_workspace_get(path: str, timeout_seconds: float):  # noqa: ARG001
            if path == "/api/status":
                return {
                    "ok": True,
                    "status_code": 200,
                    "payload": {
                        "runtime_id": "loom_native",
                        "slo": {"status": "healthy", "alert_count": 0},
                        "treasury": {"balance_usd": 1.0, "reserve_floor_usd": 0.5},
                    },
                }
            return {"ok": False, "status_code": 500, "payload": {"status": "error"}}

        with patch.object(
            gateway,
            "_workspace_api_get_json_with_timeout",
            side_effect=fake_workspace_get,
        ), patch.object(
            gateway,
            "_build_governed_memory_operator_status",
            return_value={
                "status": "success",
                "fork_latest_status": "memory_fork_created",
                "replay_latest_status": "memory_replay_blocked",
            },
        ):
            result = gateway._workspace_status_snapshot_cached()

        self.assertTrue(result["ok"])
        self.assertEqual(result["payload"]["governed_memory"]["status"], "success")
        self.assertEqual(
            result["payload"]["governed_memory"]["fork_latest_status"],
            "memory_fork_created",
        )

    def test_operator_truth_packet_carries_governed_memory(self):
        responses = {
            "/api/status": {
                "ok": True,
                "payload": {
                    "runtime_id": "loom_runtime_test",
                    "context": {"bound_org_id": "org_test"},
                    "treasury": {"balance_usd": 3.0, "reserve_floor_usd": 1.0},
                    "governed_memory": {
                        "status": "success",
                        "fork_latest_status": "memory_fork_created",
                        "replay_latest_status": "memory_replay_blocked",
                    },
                },
            },
            "/api/runtime-proof": {"ok": True, "payload": {"runtime_id": "loom_runtime_test"}},
            "/api/payouts": {"ok": True, "payload": {"execution_gate": {"phase_ok": True, "reason": ""}, "phase_machine": {"number": 1, "name": "ok"}}},
        }

        def fake_workspace_get(path: str):
            return responses.get(path, {"ok": False, "payload": {}})

        with patch.object(gateway, "_workspace_api_get_json", side_effect=fake_workspace_get), patch.object(
            gateway,
            "_recent_telegram_delivery_summary",
            return_value={"checked_count": 0, "delivered_count": 0, "failed_count": 0, "pending_count": 0},
        ):
            packet = gateway._build_meridian_operator_truth_packet()

        self.assertEqual(packet["runtime_id"], "loom_runtime_test")
        self.assertEqual(packet["governed_memory"]["status"], "success")
        self.assertEqual(packet["governed_memory"]["replay_latest_status"], "memory_replay_blocked")


class TestMemorySearchRouteWiring(unittest.TestCase):
    """Source-string assertions matching the existing intelligence test style."""

    @classmethod
    def setUpClass(cls):
        cls.source = GATEWAY_PY.read_text(encoding="utf-8")

    def test_route_handler_exists(self):
        self.assertIn('"/api/memory/search"', self.source)
        self.assertIn("_build_memory_search_response(", self.source)

    def test_route_is_origin_protected_not_public(self):
        # /api/memory/search must not be added to _public_read_allowed.
        public_block_start = self.source.index("def _public_read_allowed")
        public_block = self.source[public_block_start : public_block_start + 4000]
        self.assertNotIn("/api/memory/search", public_block)

    def test_max_limit_is_capped(self):
        self.assertIn("MEMORY_SEARCH_API_MAX_LIMIT", self.source)
        self.assertIn(
            "min(limit_val, MEMORY_SEARCH_API_MAX_LIMIT)",
            self.source,
        )

    def test_search_route_supports_repeated_and_csv_tags(self):
        self.assertIn('query_params.get("tag")', self.source)
        self.assertIn('raw_csv = _qp("tags")', self.source)
        self.assertIn('tags=_qp_tags()', self.source)

    def test_overview_route_is_wired(self):
        self.assertIn('"/api/memory/overview"', self.source)
        self.assertIn("_build_memory_overview_response(", self.source)

    def test_overview_route_is_origin_protected_not_public(self):
        public_block_start = self.source.index("def _public_read_allowed")
        public_block = self.source[public_block_start : public_block_start + 4000]
        self.assertNotIn("/api/memory/overview", public_block)

    def test_receipts_route_is_wired(self):
        self.assertIn('"/api/memory/receipts"', self.source)
        self.assertIn("_build_memory_receipts_response(", self.source)

    def test_graph_route_is_wired(self):
        self.assertIn('"/api/memory/graph"', self.source)
        self.assertIn("_build_memory_graph_response(", self.source)

    def test_fork_and_replay_routes_are_wired(self):
        self.assertIn('"/api/memory/fork"', self.source)
        self.assertIn("_build_memory_fork_response(", self.source)
        self.assertIn('"/api/memory/replay"', self.source)
        self.assertIn("_build_memory_replay_response(", self.source)

    def test_latest_artifact_routes_are_wired(self):
        self.assertIn('"/api/memory/fork/latest"', self.source)
        self.assertIn('"/api/memory/replay/latest"', self.source)
        self.assertIn("_build_memory_latest_artifact_response(", self.source)

    def test_history_routes_are_wired(self):
        self.assertIn('"/api/memory/fork/history"', self.source)
        self.assertIn('"/api/memory/replay/history"', self.source)
        self.assertIn("_build_memory_artifact_history_response(", self.source)

    def test_governance_route_is_wired(self):
        self.assertIn('"/api/memory/governance"', self.source)
        self.assertIn("_build_memory_governance_summary_response(", self.source)

    def test_receipts_and_graph_are_origin_protected_not_public(self):
        public_block_start = self.source.index("def _public_read_allowed")
        public_block = self.source[public_block_start : public_block_start + 4000]
        self.assertNotIn("/api/memory/receipts", public_block)
        self.assertNotIn("/api/memory/graph", public_block)
        self.assertNotIn("/api/memory/fork", public_block)
        self.assertNotIn("/api/memory/replay", public_block)
        self.assertNotIn("/api/memory/fork/latest", public_block)
        self.assertNotIn("/api/memory/replay/latest", public_block)
        self.assertNotIn("/api/memory/fork/history", public_block)
        self.assertNotIn("/api/memory/replay/history", public_block)
        self.assertNotIn("/api/memory/governance", public_block)


class TestPublicReadAllowlistRuntime(unittest.TestCase):
    """Runtime tests of is_public_read_route against the actual exported
    function — not a source-string check. These assert the security
    contract for every memory route plus a few sanity routes that MUST
    remain publicly readable."""

    def test_memory_search_is_not_public(self):
        self.assertFalse(gateway.is_public_read_route("/api/memory/search"))

    def test_memory_overview_is_not_public(self):
        self.assertFalse(gateway.is_public_read_route("/api/memory/overview"))

    def test_memory_receipts_is_not_public(self):
        self.assertFalse(gateway.is_public_read_route("/api/memory/receipts"))

    def test_memory_graph_is_not_public(self):
        self.assertFalse(gateway.is_public_read_route("/api/memory/graph"))

    def test_memory_fork_is_not_public(self):
        self.assertFalse(gateway.is_public_read_route("/api/memory/fork"))

    def test_memory_replay_is_not_public(self):
        self.assertFalse(gateway.is_public_read_route("/api/memory/replay"))

    def test_memory_latest_artifact_routes_are_not_public(self):
        self.assertFalse(gateway.is_public_read_route("/api/memory/fork/latest"))
        self.assertFalse(gateway.is_public_read_route("/api/memory/replay/latest"))

    def test_memory_history_routes_are_not_public(self):
        self.assertFalse(gateway.is_public_read_route("/api/memory/fork/history"))
        self.assertFalse(gateway.is_public_read_route("/api/memory/replay/history"))

    def test_memory_governance_route_is_not_public(self):
        self.assertFalse(gateway.is_public_read_route("/api/memory/governance"))

    def test_memory_search_with_query_string_is_not_public(self):
        # Defense in depth: even if a malformed call sneaks a query into
        # the path, the canonical normalization is just the path. The
        # gateway parses the query separately, so the path stays clean.
        self.assertFalse(gateway.is_public_read_route("/api/memory/search "))
        self.assertFalse(gateway.is_public_read_route(""))
        self.assertFalse(gateway.is_public_read_route("/api/memory"))

    def test_arbitrary_unmounted_routes_are_not_public(self):
        # Guard against accidental wildcard.
        self.assertFalse(gateway.is_public_read_route("/api/admin"))
        self.assertFalse(gateway.is_public_read_route("/api/secrets"))
        self.assertFalse(gateway.is_public_read_route("/api/run"))

    def test_known_public_routes_remain_public(self):
        # Sanity: refactor must not have demoted any previously-public
        # route. If this breaks, the gateway will start refusing public
        # traffic that operators rely on.
        for path in (
            "/api/healthz",
            "/api/channels/health",
            "/api/workflows/showcase",
            "/api/status",
            "/api/treasury",
            "/api/payouts",
            "/api/marketplace",
        ):
            with self.subTest(path=path):
                self.assertTrue(gateway.is_public_read_route(path))

    def test_channel_diagnostics_and_proof_paths_are_public(self):
        self.assertTrue(
            gateway.is_public_read_route("/api/channels/telegram/diagnostics")
        )
        self.assertTrue(
            gateway.is_public_read_route("/api/channels/zalo/proof")
        )

    def test_memory_routes_are_excluded_from_constant_set(self):
        for path in (
            "/api/memory/search",
            "/api/memory/overview",
            "/api/memory/diff",
            "/api/memory/snapshot",
            "/api/memory/receipts",
            "/api/memory/graph",
            "/api/memory/fork",
            "/api/memory/replay",
            "/api/memory/fork/latest",
            "/api/memory/replay/latest",
            "/api/memory/fork/history",
            "/api/memory/replay/history",
            "/api/memory/governance",
        ):
            with self.subTest(path=path):
                self.assertNotIn(path, gateway.PUBLIC_READ_ROUTES_EXACT)


if __name__ == "__main__":
    unittest.main()
