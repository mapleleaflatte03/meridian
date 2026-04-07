#!/usr/bin/env python3
import unittest
from unittest import mock

from team_topology import SPECIALIST_KEYS, load_team_topology


class TeamTopologyTests(unittest.TestCase):
    def test_load_team_topology_reads_meridian_env_defaults(self):
        topology = load_team_topology()
        self.assertEqual(topology.manager.name, "Leviathann")
        self.assertEqual(topology.manager.profile_name, "manager_primary")
        self.assertIn(topology.manager.provider_kind, {"cli_session", "http_json"})
        self.assertEqual(len(topology.specialists), len(SPECIALIST_KEYS))
        specialist_map = {agent.env_key: agent for agent in topology.specialists}
        for key in SPECIALIST_KEYS:
            self.assertIn(key, specialist_map)
            self.assertTrue(specialist_map[key].base_url)
            self.assertTrue(specialist_map[key].model)
            self.assertEqual(specialist_map[key].provider_kind, "http_json")

    def test_load_team_topology_falls_back_to_manager_registry_record_on_name_drift(self):
        drifted_registry = {
            "agents": {
                "agent_manager": {
                    "id": "agent_manager",
                    "name": "Manager",
                    "role": "manager",
                    "economy_key": "main",
                    "purpose": "manager lane",
                },
                "agent_atlas": {
                    "id": "agent_atlas",
                    "name": "Atlas",
                    "role": "analyst",
                    "economy_key": "atlas",
                    "purpose": "atlas lane",
                },
                "agent_sentinel": {
                    "id": "agent_sentinel",
                    "name": "Sentinel",
                    "role": "verifier",
                    "economy_key": "sentinel",
                    "purpose": "sentinel lane",
                },
                "agent_forge": {
                    "id": "agent_forge",
                    "name": "Forge",
                    "role": "executor",
                    "economy_key": "forge",
                    "purpose": "forge lane",
                },
                "agent_quill": {
                    "id": "agent_quill",
                    "name": "Quill",
                    "role": "writer",
                    "economy_key": "quill",
                    "purpose": "quill lane",
                },
                "agent_aegis": {
                    "id": "agent_aegis",
                    "name": "Aegis",
                    "role": "qa_gate",
                    "economy_key": "aegis",
                    "purpose": "aegis lane",
                },
                "agent_pulse": {
                    "id": "agent_pulse",
                    "name": "Pulse",
                    "role": "compressor",
                    "economy_key": "pulse",
                    "purpose": "pulse lane",
                },
            }
        }
        runtime_env = {
            "MERIDIAN_MANAGER_AGENT_NAME": "Leviathann",
            "MERIDIAN_BRAIN_MANAGER_PROFILE_NAME": "manager_primary",
            "MERIDIAN_BRAIN_MANAGER_TRANSPORT": "http_json",
            "MERIDIAN_BRAIN_MANAGER_ENDPOINT": "https://example.invalid/v1/chat/completions",
            "MERIDIAN_BRAIN_MANAGER_AUTH_ENV": "MANAGER_API_KEY",
            "MERIDIAN_BRAIN_MANAGER_MODEL": "manager-model",
        }
        for key in SPECIALIST_KEYS:
            runtime_env[f"MERIDIAN_AGENT_{key}_NAME"] = key.title()
            runtime_env[f"MERIDIAN_AGENT_{key}_PROVIDER"] = "http_json"
            runtime_env[f"MERIDIAN_AGENT_{key}_BASE_URL"] = f"https://{key.lower()}.example.invalid/v1"
            runtime_env[f"MERIDIAN_AGENT_{key}_MODEL"] = f"{key.lower()}-model"

        with mock.patch("team_topology._load_registry", return_value=drifted_registry):
            with mock.patch("team_topology.load_runtime_env", return_value=runtime_env):
                topology = load_team_topology()

        self.assertEqual(topology.manager.registry_id, "agent_manager")
        self.assertEqual(topology.manager.name, "Leviathann")
        self.assertEqual(topology.manager.role, "manager")


if __name__ == "__main__":
    unittest.main()
