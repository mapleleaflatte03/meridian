#!/usr/bin/env python3
"""Unit tests for the gateway's small TTL proxy cache.

These tests exercise ``_workspace_proxied_get_cached`` without spinning up a
real workspace, by stubbing ``_workspace_api_get_json``. The goal is to lock in
the behavior we rely on for the hot read-only GET routes (treasury, institution
template): fresh hits, TTL'd cache reuse, stale-with-fallback on upstream
error, and no cache poisoning via ``normalize``.
"""
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

_THIS_DIR = Path(__file__).resolve().parent
_INSTALLED_WORKSPACE = Path('/home/ubuntu/.meridian/workspace')
WORKSPACE = _THIS_DIR if (_THIS_DIR / 'meridian_gateway.py').exists() else _INSTALLED_WORKSPACE
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

spec = importlib.util.spec_from_file_location('meridian_gateway_proxy_cache_test', WORKSPACE / 'meridian_gateway.py')
meridian_gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(meridian_gateway)


class GatewayProxyCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        with meridian_gateway.PROXY_CACHE_LOCK:
            meridian_gateway.PROXY_CACHE.clear()

    def test_fresh_hit_populates_cache_and_marks_fresh(self) -> None:
        call_count = {"n": 0}

        def _fake(path, timeout_seconds=20.0):
            call_count["n"] += 1
            return {"ok": True, "status_code": 200, "payload": {"balance_usd": 0, "call": call_count["n"]}}

        with mock.patch.object(meridian_gateway, "_workspace_api_get_json", side_effect=_fake):
            r1 = meridian_gateway._workspace_proxied_get_cached("/api/treasury", ttl_seconds=2.0)
            r2 = meridian_gateway._workspace_proxied_get_cached("/api/treasury", ttl_seconds=2.0)

        self.assertEqual(call_count["n"], 1, "second call within TTL must be served from cache")
        self.assertEqual(r1["status_code"], 200)
        self.assertEqual(r2["status_code"], 200)
        self.assertEqual(r1["payload"]["call"], 1)
        self.assertEqual(r2["payload"]["call"], 1)
        self.assertEqual(r1["payload"]["gateway_cache"]["state"], "fresh")
        self.assertEqual(r2["payload"]["gateway_cache"]["state"], "fresh")
        self.assertEqual(r2["payload"]["gateway_cache"]["path"], "/api/treasury")

    def test_zero_ttl_always_refetches(self) -> None:
        call_count = {"n": 0}

        def _fake(path, timeout_seconds=20.0):
            call_count["n"] += 1
            return {"ok": True, "status_code": 200, "payload": {"n": call_count["n"]}}

        with mock.patch.object(meridian_gateway, "_workspace_api_get_json", side_effect=_fake):
            meridian_gateway._workspace_proxied_get_cached("/api/treasury", ttl_seconds=0.0)
            meridian_gateway._workspace_proxied_get_cached("/api/treasury", ttl_seconds=0.0)

        self.assertEqual(call_count["n"], 2, "ttl=0 must not reuse cached entries")

    def test_upstream_error_falls_back_to_stale(self) -> None:
        calls = [
            {"ok": True, "status_code": 200, "payload": {"balance_usd": 10}},
            {"ok": False, "status_code": 502, "payload": {"output": "workspace_unreachable"}},
        ]

        def _fake(path, timeout_seconds=20.0):
            return calls.pop(0)

        with mock.patch.object(meridian_gateway, "_workspace_api_get_json", side_effect=_fake):
            first = meridian_gateway._workspace_proxied_get_cached("/api/treasury", ttl_seconds=0.0)
            self.assertEqual(first["payload"]["gateway_cache"]["state"], "fresh")
            second = meridian_gateway._workspace_proxied_get_cached("/api/treasury", ttl_seconds=0.0)

        self.assertTrue(second["ok"])
        self.assertEqual(second["payload"]["gateway_cache"]["state"], "stale_fallback")
        self.assertEqual(second["payload"]["gateway_cache"]["upstream_status_code"], 502)
        self.assertEqual(second["payload"]["balance_usd"], 10)

    def test_normalize_is_applied_per_read_without_cache_poisoning(self) -> None:
        def _fake(path, timeout_seconds=20.0):
            return {"ok": True, "status_code": 200, "payload": {"balance_usd": 5}}

        def _normalize(payload):
            payload = dict(payload)
            payload["balance_usd"] = payload.get("balance_usd", 0) * 2
            return payload

        with mock.patch.object(meridian_gateway, "_workspace_api_get_json", side_effect=_fake):
            r1 = meridian_gateway._workspace_proxied_get_cached(
                "/api/treasury", ttl_seconds=5.0, normalize=_normalize
            )
            r2 = meridian_gateway._workspace_proxied_get_cached(
                "/api/treasury", ttl_seconds=5.0, normalize=_normalize
            )

        self.assertEqual(r1["payload"]["balance_usd"], 10)
        # If the cache were mutated by normalize, r2 would be 20 (double-doubled).
        self.assertEqual(r2["payload"]["balance_usd"], 10)


if __name__ == "__main__":
    unittest.main()
