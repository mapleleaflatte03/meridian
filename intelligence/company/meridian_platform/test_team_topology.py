#!/usr/bin/env python3
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from dataclasses import replace

from team_topology import (
    DEFAULT_CODEX_BASE_URL,
    SPECIALIST_KEYS,
    _profile_json_for_agent,
    _resolve_codex_auth_path,
    load_runtime_env,
    load_team_topology,
    sync_loom_team_profiles,
)


class TeamTopologyTests(unittest.TestCase):
    def test_kernel_registry_path_targets_nested_kernel_bundle_registry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            kernel_root = Path(tmpdir) / "kernel"
            nested_kernel = kernel_root / "kernel"
            nested_kernel.mkdir(parents=True, exist_ok=True)
            (nested_kernel / "agent_registry.py").write_text("# stub\n", encoding="utf-8")

            from team_topology import _kernel_registry_path

            resolved = _kernel_registry_path(
                Path("/tmp/runtime-root"),
                {"MERIDIAN_KERNEL_ROOT": str(kernel_root)},
            )

        self.assertEqual(resolved, nested_kernel / "agent_registry.json")

    def test_resolve_codex_auth_path_prefers_dedicated_loom_auth_over_newer_shared_cli_auth(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            loom_auth = Path(tmpdir) / ".meridian" / "auth" / "codex" / "login-home" / ".codex" / "auth.json"
            shared_auth = Path(tmpdir) / ".codex" / "auth.json"
            loom_auth.parent.mkdir(parents=True, exist_ok=True)
            shared_auth.parent.mkdir(parents=True, exist_ok=True)
            loom_auth.write_text('{"tokens":{"access_token":"loom-token"}}', encoding="utf-8")
            shared_auth.write_text('{"tokens":{"access_token":"shared-token"}}', encoding="utf-8")
            os.utime(loom_auth, (1, 1))
            os.utime(shared_auth, (2, 2))
            with mock.patch("team_topology._candidate_codex_auth_paths", return_value=(loom_auth, shared_auth)):
                resolved = _resolve_codex_auth_path({})
        self.assertEqual(resolved, loom_auth)

    def test_profile_json_for_codex_uses_backend_api_default_url(self):
        topology = load_team_topology()
        agent = replace(
            next(item for item in topology.specialists if item.env_key == "SENTINEL"),
            provider_kind="openai_codex",
            base_url="",
            model="gpt-5.4",
        )
        with mock.patch("team_topology._resolve_codex_auth_path", return_value=Path("/tmp/auth.json")):
            payload = _profile_json_for_agent(agent, runtime_env={})
        self.assertEqual(payload["base_url"], DEFAULT_CODEX_BASE_URL)

    def test_resolve_codex_auth_path_ignores_invalid_dedicated_auth_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            loom_auth = Path(tmpdir) / ".meridian" / "auth" / "codex" / "login-home" / ".codex" / "auth.json"
            shared_auth = Path(tmpdir) / ".codex" / "auth.json"
            loom_auth.parent.mkdir(parents=True, exist_ok=True)
            shared_auth.parent.mkdir(parents=True, exist_ok=True)
            loom_auth.write_text("", encoding="utf-8")
            shared_auth.write_text('{"tokens":{"access_token":"shared-token"}}', encoding="utf-8")
            with mock.patch("team_topology._candidate_codex_auth_paths", return_value=(loom_auth, shared_auth)):
                resolved = _resolve_codex_auth_path({})
        self.assertEqual(resolved, shared_auth)

    def test_load_team_topology_reads_meridian_env_defaults(self):
        topology = load_team_topology()
        self.assertEqual(topology.manager.name, "Leviathann")
        self.assertEqual(topology.manager.profile_name, "manager_primary")
        self.assertIn(topology.manager.provider_kind, {"openai_codex", "openai_compatible"})
        self.assertEqual(len(topology.specialists), len(SPECIALIST_KEYS))
        specialist_map = {agent.env_key: agent for agent in topology.specialists}
        for key in SPECIALIST_KEYS:
            self.assertIn(key, specialist_map)
        self.assertEqual(specialist_map["ATLAS"].profile_name, "research_frontier")
        self.assertEqual(specialist_map["SENTINEL"].profile_name, "verifier_frontier")
        self.assertEqual(specialist_map["FORGE"].profile_name, "executor_tooling")

    def test_load_runtime_env_prefers_local_meridian_env_over_repo_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            repo_env = tmp / "repo.env"
            repo_gateway_env = tmp / "repo.env.gateway"
            local_env = tmp / ".meridian.env"
            local_gateway_env = tmp / ".meridian.env.gateway"
            repo_env.write_text("MERIDIAN_AGENT_ATLAS_MODEL=repo-model\n", encoding="utf-8")
            repo_gateway_env.write_text("MERIDIAN_AGENT_ATLAS_MODEL=gateway-model\n", encoding="utf-8")
            local_env.write_text("MERIDIAN_AGENT_ATLAS_MODEL=local-model\n", encoding="utf-8")
            local_gateway_env.write_text("MERIDIAN_LOOM_ROOT=/tmp/local-runtime\n", encoding="utf-8")

            runtime_env = load_runtime_env(
                env_files=(repo_env, repo_gateway_env, local_env, local_gateway_env),
            )

        self.assertEqual(runtime_env["MERIDIAN_AGENT_ATLAS_MODEL"], "local-model")
        self.assertEqual(runtime_env["MERIDIAN_LOOM_ROOT"], "/tmp/local-runtime")

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

    def test_sync_loom_team_profiles_registers_team_agents_in_kernel_registry(self):
        topology = load_team_topology()
        with mock.patch("team_topology.load_runtime_env", return_value={}):
            with mock.patch("team_topology._kernel_registry_path") as kernel_registry_path:
                temp_root = Path(self.id().replace(".", "_"))
                loom_root = Path("/tmp") / temp_root
                kernel_path = loom_root / "kernel" / "agent_registry.json"
                kernel_registry_path.return_value = kernel_path
                result = sync_loom_team_profiles(topology, loom_root=loom_root, org_id="org_runtime")

        self.assertEqual(result["kernel_registry_path"], str(kernel_path))
        payload = __import__("json").loads(kernel_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["agents"]["agent_atlas"]["org_id"], "org_runtime")
        self.assertEqual(payload["agents"]["agent_atlas"]["economy_key"], "atlas")
        self.assertEqual(payload["agents"]["agent_sentinel"]["runtime_binding"]["runtime_id"], "loom_native")

    def test_sync_loom_team_profiles_updates_runtime_loom_config(self):
        topology = load_team_topology()
        with tempfile.TemporaryDirectory() as tmpdir:
            loom_root = Path(tmpdir)
            loom_toml = loom_root / "loom.toml"
            kernel_root = loom_root / "kernel-bundle"
            platform_dir = loom_root / "platform"
            platform_dir.mkdir(parents=True, exist_ok=True)
            (platform_dir / "organizations.json").write_text(
                '{"organizations":{"org_runtime":{"id":"org_runtime","name":"Runtime Org","slug":"runtime-org","owner_id":"user_runtime","members":[],"plan":"enterprise","status":"active","charter":"","policy_defaults":{},"treasury_id":"capsule://org_runtime/treasury","lifecycle_state":"active","settings":{}}}}',
                encoding="utf-8",
            )
            (kernel_root / "kernel").mkdir(parents=True, exist_ok=True)
            (kernel_root / "kernel" / "agent_registry.py").write_text("# stub\n", encoding="utf-8")
            (kernel_root / "kernel" / "capsule.py").write_text(
                "\n".join(
                    [
                        "import json",
                        "import os",
                        "def init_capsule(org_id, ledger_template=None):",
                        "    target = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'capsules', org_id)",
                        "    os.makedirs(target, exist_ok=True)",
                        "    with open(os.path.join(target, 'ledger.json'), 'w', encoding='utf-8') as handle:",
                        "        json.dump(ledger_template or {}, handle)",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (kernel_root / "kernel" / "organizations.json").write_text('{"organizations":{}}', encoding="utf-8")
            (kernel_root / "economy").mkdir(parents=True, exist_ok=True)
            (kernel_root / "economy" / "ledger.json").write_text('{"agents":{}}', encoding="utf-8")
            loom_toml.write_text(
                '\n'.join(
                    [
                        '[runtime]',
                        'mode = "embedded"',
                        'kernel_path = "/stale/kernel"',
                        'org_id = "org_stale"',
                        'state_dir = "state"',
                    ]
                )
                + '\n',
                encoding="utf-8",
            )

            runtime_env = {
                "MERIDIAN_KERNEL_ROOT": str(kernel_root),
                "MERIDIAN_LOOM_ORG_ID": "org_runtime",
            }
            with mock.patch("team_topology.PLATFORM_DIR", platform_dir):
                result = sync_loom_team_profiles(
                    topology,
                    loom_root=loom_root,
                    org_id="org_runtime",
                    runtime_env=runtime_env,
                )

            rendered = loom_toml.read_text(encoding="utf-8")
            kernel_orgs = (kernel_root / "kernel" / "organizations.json").read_text(encoding="utf-8")

        self.assertEqual(result["loom_toml_status"], "updated")
        self.assertIn(f'kernel_path = "{kernel_root}"', rendered)
        self.assertIn('org_id = "org_runtime"', rendered)
        self.assertEqual(result["kernel_org_status"], "updated")
        self.assertIn(result["kernel_capsule_status"], {"initialized", "exists", "unchanged"})
        self.assertIn('"org_runtime"', kernel_orgs)


if __name__ == "__main__":
    unittest.main()
