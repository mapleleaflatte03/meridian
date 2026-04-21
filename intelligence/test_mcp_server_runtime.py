#!/usr/bin/env python3
import importlib.util
import pathlib
import sys
import types
import unittest
from unittest import mock


HERE = pathlib.Path(__file__).resolve().parent
MCP_SERVER_PATH = HERE / "company" / "mcp_server.py"


class _DummyFastMCP:
    def __init__(self, *_args, **_kwargs):
        pass

    def tool(self, *_args, **_kwargs):
        def _decorator(fn):
            return fn
        return _decorator

    def resource(self, *_args, **_kwargs):
        def _decorator(fn):
            return fn
        return _decorator


def _load_module():
    mcp_pkg = types.ModuleType("mcp")
    server_pkg = types.ModuleType("mcp.server")
    fastmcp_mod = types.ModuleType("mcp.server.fastmcp")
    fastmcp_mod.FastMCP = _DummyFastMCP
    team_topology_mod = types.ModuleType("team_topology")
    team_topology_mod.load_runtime_env = mock.Mock(return_value={})
    team_topology_mod.load_team_topology = mock.Mock(return_value=types.SimpleNamespace(org_id=None))
    team_topology_mod.sync_loom_team_profiles = mock.Mock(return_value=None)
    with mock.patch.dict(
        sys.modules,
        {
            "mcp": mcp_pkg,
            "mcp.server": server_pkg,
            "mcp.server.fastmcp": fastmcp_mod,
            "team_topology": team_topology_mod,
        },
        clear=False,
    ):
        sys.path.insert(0, str(MCP_SERVER_PATH.parent))
        sys.path.insert(0, str(MCP_SERVER_PATH.parent / "meridian_platform"))
        try:
            spec = importlib.util.spec_from_file_location("mcp_server_runtime_test_module", MCP_SERVER_PATH)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            return module
        finally:
            sys.path = [entry for entry in sys.path if entry not in {str(MCP_SERVER_PATH.parent), str(MCP_SERVER_PATH.parent / "meridian_platform")}]


class MpcServerRuntimeTests(unittest.TestCase):
    def test_loom_execution_org_prefers_runtime_org_over_founding_org(self):
        module = _load_module()
        with mock.patch.object(module, "TEAM_RUNTIME_ENV", {}, create=False), mock.patch.object(
            module,
            "_shared_runtime_value",
            return_value="org_runtime_truth",
        ):
            module.DEFAULT_ORG_ID = "org_founding_default"
            module.MCP_ORG_ID = None
            module.TEAM_TOPOLOGY = types.SimpleNamespace(org_id="org_team_topology")
            self.assertEqual(module._loom_org_id(), "org_runtime_truth")


if __name__ == "__main__":
    unittest.main()
