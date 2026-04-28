#!/usr/bin/env python3
"""Tests for the /api/memory/search gateway route.

Covers:
- _build_memory_search_response shapes and filters
- subprocess invocation arg construction (single-agent and --all-agents)
- Origin-protected route is wired and not in _public_read_allowed
- Content truncation when include_content=True
"""

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
                limit=20,
                include_content=False,
            )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["output"], "synthetic_failure_message")
        self.assertEqual(result["matches"], [])


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


if __name__ == "__main__":
    unittest.main()
