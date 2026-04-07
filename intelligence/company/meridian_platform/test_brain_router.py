#!/usr/bin/env python3
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

PLATFORM_DIR = Path(__file__).resolve().parent
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

import brain_router


class BrainRouterTests(unittest.TestCase):
    def test_resolve_manager_plan_prefers_agnostic_env_schema(self):
        env = {
            "MERIDIAN_BRAIN_MANAGER_TRANSPORT": "http_json",
            "MERIDIAN_BRAIN_MANAGER_PROFILE_NAME": "manager_primary",
            "MERIDIAN_BRAIN_MANAGER_ENDPOINT": "https://router.example/v1/chat/completions",
            "MERIDIAN_BRAIN_MANAGER_MODEL": "reasoner-small",
            "MERIDIAN_BRAIN_MANAGER_KEY_POOL": "key-a,key-b",
            "MERIDIAN_BRAIN_MANAGER_FAILOVER_STATUS_CODES": "429,503",
        }
        plan = brain_router.resolve_manager_plan(runtime_env=env, model_hint="")
        self.assertEqual(plan["profile_name"], "manager_primary")
        self.assertEqual(plan["transport_kind"], "http_json")
        self.assertEqual(plan["model"], "reasoner-small")
        self.assertEqual(plan["endpoint"], "https://router.example/v1/chat/completions")
        self.assertEqual(plan["key_pool"], ["key-a", "key-b"])
        self.assertEqual(plan["failover_status_codes"], {429, 503})

    def test_resolve_manager_plan_migrates_legacy_env_keys(self):
        env = {
            "MERIDIAN_MANAGER_PROVIDER": "xai_pool",
            "MERIDIAN_MANAGER_MODEL": "legacy-model",
            "MERIDIAN_MANAGER_XAI_BASE_URL": "https://legacy.example/v1/chat/completions",
            "MERIDIAN_MANAGER_XAI_API_KEY_1": "legacy-key-1",
            "MERIDIAN_MANAGER_XAI_API_KEY_2": "legacy-key-2",
            "MERIDIAN_MANAGER_XAI_FAILOVER_STATUS_CODES": "401,429,503",
        }
        plan = brain_router.resolve_manager_plan(runtime_env=env, model_hint="")
        self.assertEqual(plan["transport_kind"], "http_json")
        self.assertEqual(plan["model"], "legacy-model")
        self.assertEqual(plan["endpoint"], "https://legacy.example/v1/chat/completions")
        self.assertEqual(plan["key_pool"], ["legacy-key-1", "legacy-key-2"])
        self.assertEqual(plan["failover_status_codes"], {401, 429, 503})
        self.assertIn("legacy", str(plan.get("migration_note", "")).lower())

    def test_execute_manager_http_failover_uses_next_key(self):
        env = {
            "MERIDIAN_BRAIN_MANAGER_TRANSPORT": "http_json",
            "MERIDIAN_BRAIN_MANAGER_PROFILE_NAME": "manager_http_pool",
            "MERIDIAN_BRAIN_MANAGER_ENDPOINT": "https://router.example/v1/chat/completions",
            "MERIDIAN_BRAIN_MANAGER_MODEL": "fast-reasoner",
            "MERIDIAN_BRAIN_MANAGER_KEY_POOL": "key-a,key-b",
            "MERIDIAN_BRAIN_MANAGER_FAILOVER_STATUS_CODES": "429,503",
            "MERIDIAN_BRAIN_MANAGER_MAX_TOKENS": "64",
        }

        calls = []

        def fake_http_post(*, endpoint, headers, payload, timeout):
            calls.append({"endpoint": endpoint, "headers": headers, "payload": payload, "timeout": timeout})
            if len(calls) == 1:
                raise urllib.error.HTTPError(
                    url=endpoint,
                    code=429,
                    msg="rate limit",
                    hdrs=None,
                    fp=io.BytesIO(b'{"error":"rate limit"}'),
                )
            return json.dumps(
                {
                    "model": "fast-reasoner",
                    "choices": [{"message": {"content": "fallback success"}}],
                }
            )

        result = brain_router.execute_manager(
            runtime_env=env,
            system_prompt="system",
            user_prompt="user",
            model="",
            timeout=5,
            http_post=fake_http_post,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["key_slot"], 2)
        self.assertEqual(result["transport_kind"], "http_json")
        self.assertIn("fallback", result["output_text"])
        self.assertEqual(len(calls), 2)
        self.assertTrue(result.get("warnings"))

    def test_execute_manager_http_failover_trace_is_deterministic(self):
        env = {
            "MERIDIAN_BRAIN_MANAGER_TRANSPORT": "http_json",
            "MERIDIAN_BRAIN_MANAGER_PROFILE_NAME": "manager_http_pool",
            "MERIDIAN_BRAIN_MANAGER_ENDPOINT": "https://router.example/v1/chat/completions",
            "MERIDIAN_BRAIN_MANAGER_MODEL": "fast-reasoner",
            "MERIDIAN_BRAIN_MANAGER_KEY_POOL": "key-a,key-b,key-c",
            "MERIDIAN_BRAIN_MANAGER_FAILOVER_STATUS_CODES": "429,503",
            "MERIDIAN_BRAIN_MANAGER_MAX_TOKENS": "64",
        }

        def run_once() -> dict[str, object]:
            calls = {"count": 0}

            def fake_http_post(*, endpoint, headers, payload, timeout):
                calls["count"] += 1
                if calls["count"] == 1:
                    raise urllib.error.HTTPError(
                        url=endpoint,
                        code=429,
                        msg="rate limit",
                        hdrs=None,
                        fp=io.BytesIO(b'{"error":"rate limit"}'),
                    )
                if calls["count"] == 2:
                    return json.dumps({"error": "quota exhausted"})
                return json.dumps(
                    {
                        "model": "fast-reasoner",
                        "choices": [{"message": {"content": "fallback success"}}],
                    }
                )

            return brain_router.execute_manager(
                runtime_env=env,
                system_prompt="system",
                user_prompt="user",
                model="",
                timeout=5,
                http_post=fake_http_post,
            )

        first = run_once()
        second = run_once()
        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertEqual(first["key_slot"], 3)
        self.assertEqual(second["key_slot"], 3)
        self.assertEqual(first.get("failover_trace"), second.get("failover_trace"))
        self.assertEqual(
            [item.get("outcome") for item in first.get("failover_trace", [])],
            ["http_error", "empty_payload", "success"],
        )
        self.assertEqual(
            [item.get("key_slot") for item in first.get("failover_trace", [])],
            [1, 2, 3],
        )

    def test_execute_manager_cli_session(self):
        env = {
            "MERIDIAN_BRAIN_MANAGER_TRANSPORT": "cli_session",
            "MERIDIAN_BRAIN_MANAGER_PROFILE_NAME": "manager_cli",
            "MERIDIAN_BRAIN_MANAGER_MODEL": "local-brain",
            "MERIDIAN_BRAIN_MANAGER_CLI_BIN": "brain-cli",
            "MERIDIAN_BRAIN_MANAGER_CLI_HOME": "/tmp/brain-home",
        }

        def fake_run_cli(*, command, env_vars, timeout):
            return {
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "output_text": "cli success",
                "model": "local-brain",
            }

        result = brain_router.execute_manager(
            runtime_env=env,
            system_prompt="system",
            user_prompt="hello",
            model="local-brain",
            timeout=5,
            run_cli=fake_run_cli,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["output_text"], "cli success")
        self.assertEqual(result["transport_kind"], "cli_session")
        self.assertEqual(result["provider_profile"], "manager_cli")

    def test_manager_exec_metadata_from_plan(self):
        env = {
            "MERIDIAN_BRAIN_MANAGER_TRANSPORT": "http_json",
            "MERIDIAN_BRAIN_MANAGER_PROFILE_NAME": "manager_primary",
            "MERIDIAN_BRAIN_MANAGER_ENDPOINT": "https://router.example/v1/chat/completions",
            "MERIDIAN_BRAIN_MANAGER_MODEL": "reasoner-small",
        }
        meta = brain_router.manager_exec_metadata(runtime_env=env, model_hint="")
        self.assertEqual(meta["provider_profile"], "manager_primary")
        self.assertEqual(meta["transport_kind"], "http_json")
        self.assertEqual(meta["auth_mode"], "bearer_pool")
        self.assertEqual(meta["model"], "reasoner-small")


if __name__ == "__main__":
    unittest.main()
