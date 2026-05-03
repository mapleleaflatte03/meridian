#!/usr/bin/env python3
"""Tests for `core.sh team topology` cockpit command.

Operator-facing window into the Meridian Team plane: manager + specialist
roster, models, scopes, dispatch flags. Pure read; falls back from
gateway to local loader when offline.
"""

import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
CORE_SH = MERIDIAN_ROOT / "scripts" / "core.sh"


class TestTeamCommandWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_team_command_dispatch_exists(self):
        self.assertIn('team)        cmd_team "$@"', self.source)

    def test_cmd_team_function_defined(self):
        self.assertIn("cmd_team() {", self.source)

    def test_cmd_team_topology_function_defined(self):
        self.assertIn("cmd_team_topology() {", self.source)

    def test_topology_calls_gateway_route(self):
        # Auto/remote source must hit the Origin-protected gateway endpoint.
        self.assertIn("/api/team/topology", self.source)
        self.assertIn('Origin: ${gateway_url}', self.source)

    def test_topology_local_fallback_uses_build_team_topology_response(self):
        # Offline path uses the same in-process function the gateway exposes.
        self.assertIn("_build_team_topology_response", self.source)

    def test_topology_supports_json_remote_local_flags(self):
        self.assertIn("--json) mode=", self.source)
        self.assertIn("--remote) source=", self.source)
        self.assertIn("--local) source=", self.source)

    def test_topology_renders_dispatchable_and_manager_visible(self):
        self.assertIn("dispatchable=", self.source)
        self.assertIn("manager_visible=", self.source)

    def test_topology_does_not_print_api_key_env_var(self):
        # The whole point of the gateway shaping is to never leak the env
        # var name. Make sure the Core renderer doesn't reach for it
        # either (defense in depth in case the JSON ever changes shape).
        # Find the team_topology rendering block specifically.
        start = self.source.find("cmd_team_topology() {")
        end = self.source.find("# ── Command: cap", start)
        self.assertGreater(end, start, "could not locate cmd_team_topology block")
        block = self.source[start:end]
        # Filter out the literal mention inside the --help string (which
        # documents the safety property itself). Only flag *active*
        # references that would dereference the field.
        active = block.replace("Never prints\napi_key_env_var hints", "")
        self.assertNotIn("api_key_env_var", active)


if __name__ == "__main__":
    unittest.main()
