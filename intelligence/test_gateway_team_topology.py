#!/usr/bin/env python3
"""Tests for /api/team/topology gateway route.

Surfaces Team-mode operator state (manager + specialists, roles, models,
dispatch flags) without exposing the api_key_env_var hints. Origin-
protected like the other team-control surfaces.
"""

import unittest
from pathlib import Path
from unittest.mock import patch

import meridian_gateway as gateway


GATEWAY_PY = Path(__file__).resolve().parent / "meridian_gateway.py"


class _StubTeamAgent:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class _StubTeamTopology:
    def __init__(self, org_id, manager, specialists):
        self.org_id = org_id
        self.manager = manager
        self.specialists = tuple(specialists)


class TestBuildTeamTopologyResponse(unittest.TestCase):
    def _stub_topology(self) -> _StubTeamTopology:
        manager = _StubTeamAgent(
            env_key="MANAGER",
            registry_id="agent_manager",
            handle="manager",
            name="Manager",
            role="manager",
            purpose="Manager and orchestrator.",
            profile_name="manager_primary",
            provider_kind="openai_codex",
            model="gpt-5",
            task_kind="manage",
            kernel_role="manager",
            scopes=("loom.session.write",),
            aliases=("Lev", "Leviathann"),
            dispatchable=False,
            manager_visible=True,
            api_key_env_var="MERIDIAN_BRAIN_MANAGER_AUTH_ENV",
        )
        atlas = _StubTeamAgent(
            env_key="ATLAS",
            registry_id="agent_atlas",
            handle="atlas",
            name="Atlas",
            role="research",
            purpose="Architect / research.",
            profile_name="research_frontier",
            provider_kind="openai_compatible",
            model="grok-2",
            task_kind="research",
            kernel_role="specialist",
            scopes=("loom.research",),
            aliases=("Architect",),
            dispatchable=True,
            manager_visible=False,
            api_key_env_var="MERIDIAN_AGENT_ATLAS_API_KEY",
        )
        return _StubTeamTopology(
            org_id="org_local_test",
            manager=manager,
            specialists=[atlas],
        )

    def _patch_loader(self, topology):
        from company.meridian_platform import team_topology as _tt
        return patch.object(_tt, "load_team_topology", return_value=topology)

    def test_response_shapes_manager_and_specialists(self):
        with self._patch_loader(self._stub_topology()), patch.object(
            gateway,
            "_build_memory_taxonomy_operator_status",
            return_value={"status": "success", "tag_count": 2, "tags": ["release", "vietnam"]},
        ):
            result = gateway._build_team_topology_response()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["org_id"], "org_local_test")
        self.assertEqual(result["specialist_count"], 1)
        self.assertEqual(result["memory_taxonomy"]["tag_count"], 2)
        self.assertEqual(result["memory_taxonomy"]["tags"], ["release", "vietnam"])
        self.assertEqual(result["manager"]["name"], "Manager")
        self.assertEqual(result["manager"]["role"], "manager")
        self.assertEqual(result["manager"]["dispatchable"], False)
        self.assertEqual(result["manager"]["manager_visible"], True)
        atlas = result["specialists"][0]
        self.assertEqual(atlas["env_key"], "ATLAS")
        self.assertEqual(atlas["model"], "grok-2")
        self.assertIn("Architect", atlas["aliases"])
        self.assertEqual(atlas["scopes"], ["loom.research"])
        self.assertTrue(atlas["dispatchable"])

    def test_response_does_not_leak_api_key_env_var(self):
        # Owner safety: the response must never include the env var name
        # that points at the secret. Even though it is not the secret
        # itself, leaking the name leaks deployment shape and can guide
        # an attacker.
        with self._patch_loader(self._stub_topology()), patch.object(
            gateway,
            "_build_memory_taxonomy_operator_status",
            return_value={"status": "success", "tag_count": 1, "tags": ["release"]},
        ):
            result = gateway._build_team_topology_response()
        for agent in [result["manager"], *result["specialists"]]:
            self.assertNotIn("api_key_env_var", agent)

    def test_response_handles_load_failure(self):
        from company.meridian_platform import team_topology as _tt

        def boom(*args, **kwargs):
            raise RuntimeError("synthetic_topology_failure")

        with patch.object(_tt, "load_team_topology", side_effect=boom):
            result = gateway._build_team_topology_response()
        self.assertEqual(result["status"], "error")
        self.assertIn("team_topology_load_failed", result["output"])
        self.assertIn("synthetic_topology_failure", result["output"])


class TestTeamTopologyRouteWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = GATEWAY_PY.read_text(encoding="utf-8")

    def test_route_handler_exists(self):
        self.assertIn('"/api/team/topology"', self.source)
        self.assertIn("_build_team_topology_response(", self.source)

    def test_route_is_origin_protected_not_public(self):
        # Defense in depth: never put /api/team/* in the public-read list.
        self.assertFalse(gateway.is_public_read_route("/api/team/topology"))
        self.assertNotIn("/api/team/topology", gateway.PUBLIC_READ_ROUTES_EXACT)


if __name__ == "__main__":
    unittest.main()
