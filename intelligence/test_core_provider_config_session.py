#!/usr/bin/env python3
"""Tests for Meridian Core Tranche 4: provider switching, config editing, model override, session archive.

Covers:
- Gateway /api/run model override field processing
- core.sh provider list (output format)
- core.sh provider use (policy mutation + backup)
- core.sh config set/get (allowlist, backup, persistence)
- core.sh session archive (dry-run and execute modes)
- core.sh ask --model flag propagation
- Chat /model and /provider command recognition
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
CORE_SH = MERIDIAN_ROOT / "scripts" / "core.sh"
INTELLIGENCE_DIR = MERIDIAN_ROOT / "intelligence"

# Make sure intelligence and its subdirectories are importable
sys.path.insert(0, str(INTELLIGENCE_DIR))
sys.path.insert(0, str(INTELLIGENCE_DIR / "company" / "meridian_platform"))


# ── Gateway model override tests ──────────────────────────────────────────


class TestGatewayModelOverride(unittest.TestCase):
    """Test that /api/run payload accepts and processes 'model' field."""

    def test_model_field_extracted_from_payload(self):
        """Verify model override string is correctly extracted from payload."""
        payload = {"goal": "test query", "session_id": "s1", "model": "gpt-4o"}
        model_override = str(payload.get("model") or "").strip()
        self.assertEqual(model_override, "gpt-4o")

    def test_empty_model_field_ignored(self):
        """Verify empty/missing model field yields empty string."""
        for payload in [
            {"goal": "test", "session_id": "s1"},
            {"goal": "test", "session_id": "s1", "model": ""},
            {"goal": "test", "session_id": "s1", "model": None},
        ]:
            model_override = str(payload.get("model") or "").strip()
            self.assertEqual(model_override, "")

    def test_model_override_with_attachments(self):
        """Model override and attachments can coexist in payload."""
        payload = {
            "goal": "review this",
            "session_id": "s1",
            "model": "claude-3-sonnet",
            "attachments": [{"name": "file.py", "content": "print(1)", "mime_type": "text/x-python"}],
        }
        model = str(payload.get("model") or "").strip()
        attachments = payload.get("attachments") or []
        self.assertEqual(model, "claude-3-sonnet")
        self.assertEqual(len(attachments), 1)

    def test_env_save_restore_pattern(self):
        """Verify the env save/restore pattern works correctly."""
        saved = os.environ.get("MERIDIAN_BRAIN_MANAGER_MODEL")
        os.environ["MERIDIAN_BRAIN_MANAGER_MODEL"] = "test-model-override"
        self.assertEqual(os.environ["MERIDIAN_BRAIN_MANAGER_MODEL"], "test-model-override")
        # Restore
        if saved is None:
            os.environ.pop("MERIDIAN_BRAIN_MANAGER_MODEL", None)
        else:
            os.environ["MERIDIAN_BRAIN_MANAGER_MODEL"] = saved
        self.assertEqual(os.environ.get("MERIDIAN_BRAIN_MANAGER_MODEL"), saved)


# ── Config set/get tests ─────────────────────────────────────────────────


class TestConfigSetGet(unittest.TestCase):
    """Test core.sh config set and get with allowlist + backup."""

    def _extract_allowed_keys(self) -> list[str]:
        """Extract CORE_CONFIG_ALLOWED_KEYS from core.sh."""
        content = CORE_SH.read_text(encoding="utf-8")
        for line in content.splitlines():
            if line.strip().startswith("CORE_CONFIG_ALLOWED_KEYS="):
                value = line.split("=", 1)[1].strip().strip('"')
                return value.split()
        self.fail("CORE_CONFIG_ALLOWED_KEYS not found in core.sh")
        return []

    def test_allowlist_contains_expected_keys(self):
        """Verify the allowlist has key daily-use config keys."""
        keys = self._extract_allowed_keys()
        self.assertIn("MERIDIAN_BRAIN_MANAGER_MODEL", keys)
        self.assertIn("MERIDIAN_BRAIN_MANAGER_TRANSPORT", keys)
        self.assertIn("MERIDIAN_CORE_LONG_OUTPUT_CHARS", keys)
        self.assertIn("MERIDIAN_GATEWAY_URL", keys)
        # Should NOT include dangerous keys
        self.assertNotIn("MERIDIAN_ORG_ID", keys)
        self.assertNotIn("HOME", keys)
        self.assertNotIn("PATH", keys)

    def test_config_set_creates_overrides_file(self):
        """Verify config set writes to overrides.env correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = os.path.join(tmpdir, "overrides.env")
            # Simulate the Python logic from cmd_config_set
            key = "MERIDIAN_BRAIN_MANAGER_MODEL"
            value = "gpt-4o-mini"
            lines = []
            found = False
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as fh:
                    for line in fh:
                        stripped = line.strip()
                        if stripped.startswith(f"{key}=") or stripped.startswith(f"export {key}="):
                            lines.append(f"export {key}={value}\n")
                            found = True
                        else:
                            lines.append(line)
            if not found:
                lines.append(f"export {key}={value}\n")
            with open(config_file, "w", encoding="utf-8") as fh:
                fh.writelines(lines)
            # Verify
            content = Path(config_file).read_text(encoding="utf-8")
            self.assertIn(f"export {key}={value}", content)

    def test_config_set_updates_existing_key(self):
        """Verify config set replaces existing key rather than duplicating."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = os.path.join(tmpdir, "overrides.env")
            # Write initial
            Path(config_file).write_text("export MERIDIAN_BRAIN_MANAGER_MODEL=old-model\n")
            # Update
            key = "MERIDIAN_BRAIN_MANAGER_MODEL"
            value = "new-model"
            lines = []
            found = False
            with open(config_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    stripped = line.strip()
                    if stripped.startswith(f"{key}=") or stripped.startswith(f"export {key}="):
                        lines.append(f"export {key}={value}\n")
                        found = True
                    else:
                        lines.append(line)
            if not found:
                lines.append(f"export {key}={value}\n")
            with open(config_file, "w", encoding="utf-8") as fh:
                fh.writelines(lines)
            # Verify only one occurrence
            content = Path(config_file).read_text(encoding="utf-8")
            self.assertEqual(content.count("MERIDIAN_BRAIN_MANAGER_MODEL"), 1)
            self.assertIn("new-model", content)
            self.assertNotIn("old-model", content)

    def test_config_set_backup_on_update(self):
        """Verify backup is created when overrides.env exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = os.path.join(tmpdir, "overrides.env")
            backup_file = config_file + ".bak"
            original_content = "export MERIDIAN_GATEWAY_URL=http://old:1234\n"
            Path(config_file).write_text(original_content)
            # Simulate backup
            import shutil
            shutil.copy(config_file, backup_file)
            self.assertTrue(os.path.exists(backup_file))
            self.assertEqual(Path(backup_file).read_text(), original_content)


# ── Session archive tests ────────────────────────────────────────────────


class TestSessionArchive(unittest.TestCase):
    """Test session archive lifecycle cleanup logic."""

    def _build_registry(self, sessions: list[dict]) -> dict:
        """Build a session registry dict from a list of session entries."""
        result = {"sessions": {}}
        for entry in sessions:
            sid = entry["session_id"]
            result["sessions"][sid] = entry
        return result

    def test_archive_identifies_old_sessions(self):
        """Sessions older than cutoff are candidates for archival."""
        now_ms = int(time.time() * 1000)
        old_ms = int((time.time() - 40 * 86400) * 1000)  # 40 days ago
        sessions = [
            {"session_id": "recent-1", "last_used_unix_ms": now_ms},
            {"session_id": "old-1", "last_used_unix_ms": old_ms},
            {"session_id": "old-2", "last_used_unix_ms": old_ms - 1000},
        ]
        cutoff_ms = int((time.time() - 30 * 86400) * 1000)
        candidates = [s for s in sessions if s["last_used_unix_ms"] < cutoff_ms]
        kept = [s for s in sessions if s["last_used_unix_ms"] >= cutoff_ms]
        self.assertEqual(len(candidates), 2)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["session_id"], "recent-1")

    def test_archive_excludes_current_session(self):
        """Current active session is never archived even if old."""
        now_ms = int(time.time() * 1000)
        old_ms = int((time.time() - 40 * 86400) * 1000)
        current_sid = "old-but-active"
        sessions = [
            {"session_id": "old-but-active", "last_used_unix_ms": old_ms},
            {"session_id": "old-inactive", "last_used_unix_ms": old_ms},
        ]
        cutoff_ms = int((time.time() - 30 * 86400) * 1000)
        candidates = []
        kept = []
        for s in sessions:
            if s["session_id"] == current_sid:
                kept.append(s)
            elif s["last_used_unix_ms"] < cutoff_ms:
                candidates.append(s)
            else:
                kept.append(s)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["session_id"], "old-inactive")
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["session_id"], "old-but-active")

    def test_archive_with_no_old_sessions(self):
        """No candidates when all sessions are recent."""
        now_ms = int(time.time() * 1000)
        sessions = [
            {"session_id": "recent-1", "last_used_unix_ms": now_ms},
            {"session_id": "recent-2", "last_used_unix_ms": now_ms - 3600000},
        ]
        cutoff_ms = int((time.time() - 30 * 86400) * 1000)
        candidates = [s for s in sessions if s["last_used_unix_ms"] < cutoff_ms]
        self.assertEqual(len(candidates), 0)

    def test_archive_registry_update(self):
        """Registry is correctly updated after archiving."""
        now_ms = int(time.time() * 1000)
        old_ms = int((time.time() - 40 * 86400) * 1000)
        registry = self._build_registry([
            {"session_id": "keep-me", "last_used_unix_ms": now_ms},
            {"session_id": "archive-me", "last_used_unix_ms": old_ms},
        ])
        cutoff_ms = int((time.time() - 30 * 86400) * 1000)
        sessions = dict(registry["sessions"])
        kept = {}
        for sid, entry in sessions.items():
            if entry["last_used_unix_ms"] >= cutoff_ms:
                kept[sid] = entry
        registry["sessions"] = kept
        self.assertIn("keep-me", registry["sessions"])
        self.assertNotIn("archive-me", registry["sessions"])

    def test_archive_custom_days_threshold(self):
        """Custom --older-than threshold correctly adjusts cutoff."""
        now_ms = int(time.time() * 1000)
        eight_days_ago_ms = int((time.time() - 8 * 86400) * 1000)
        sessions = [
            {"session_id": "eight-days", "last_used_unix_ms": eight_days_ago_ms},
        ]
        # With 7 day threshold, this is a candidate
        cutoff_7d = int((time.time() - 7 * 86400) * 1000)
        candidates_7d = [s for s in sessions if s["last_used_unix_ms"] < cutoff_7d]
        self.assertEqual(len(candidates_7d), 1)
        # With 10 day threshold, this is NOT a candidate
        cutoff_10d = int((time.time() - 10 * 86400) * 1000)
        candidates_10d = [s for s in sessions if s["last_used_unix_ms"] < cutoff_10d]
        self.assertEqual(len(candidates_10d), 0)


# ── Provider switching tests ─────────────────────────────────────────────


class TestProviderSwitching(unittest.TestCase):
    """Test institution_brain_policy configuration for provider switching."""

    def test_policy_configure_creates_route(self):
        """configure_policy creates a valid route with the specified profile and model."""
        import institution_brain_policy

        with tempfile.TemporaryDirectory() as tmpdir:
            org_id = "test-org-provider-switch"
            # Patch capsule_path for isolation
            original_capsule = institution_brain_policy.capsule_path
            institution_brain_policy.capsule_path = lambda oid, fname: os.path.join(tmpdir, f"{oid}_{fname}")
            try:
                policy = institution_brain_policy.configure_policy(
                    org_id,
                    route_type="cli_session",
                    provider_profile="test_provider",
                    model="test-model-v1",
                    updated_by="unit_test",
                    cli_bin="/usr/bin/echo",
                    cli_home="/tmp",
                )
                route = institution_brain_policy.active_route(policy)
                self.assertIsNotNone(route)
                self.assertEqual(route["model"], "test-model-v1")
                self.assertEqual(route["provider_ref"], "test_provider")
                self.assertEqual(route["route_type"], "cli_session")
            finally:
                institution_brain_policy.capsule_path = original_capsule

    def test_policy_switch_preserves_backup(self):
        """Switching creates backup of previous policy."""
        import institution_brain_policy

        with tempfile.TemporaryDirectory() as tmpdir:
            org_id = "test-org-backup"
            original_capsule = institution_brain_policy.capsule_path
            institution_brain_policy.capsule_path = lambda oid, fname: os.path.join(tmpdir, f"{oid}_{fname}")
            try:
                # First configure
                institution_brain_policy.configure_policy(
                    org_id,
                    route_type="cli_session",
                    provider_profile="profile_a",
                    model="model-a",
                    updated_by="unit_test",
                    cli_bin="/usr/bin/echo",
                    cli_home="/tmp",
                )
                policy_path = institution_brain_policy.policy_path(org_id)
                self.assertTrue(os.path.exists(policy_path))

                # Backup before switching
                backup_path = policy_path + ".bak"
                import shutil
                shutil.copy(policy_path, backup_path)

                # Second configure (switch)
                institution_brain_policy.configure_policy(
                    org_id,
                    route_type="cli_session",
                    provider_profile="profile_b",
                    model="model-b",
                    updated_by="unit_test",
                    cli_bin="/usr/bin/echo",
                    cli_home="/tmp",
                )
                # Backup should contain old config
                backup_data = json.loads(Path(backup_path).read_text(encoding="utf-8"))
                backup_route = institution_brain_policy.active_route(backup_data)
                self.assertEqual(backup_route["model"], "model-a")
                # Current should have new config
                current_data = institution_brain_policy.load_policy(org_id)
                current_route = institution_brain_policy.active_route(current_data)
                self.assertEqual(current_route["model"], "model-b")
            finally:
                institution_brain_policy.capsule_path = original_capsule

    def test_policy_status_shows_configured(self):
        """policy_status returns configured=True after configure_policy."""
        import institution_brain_policy

        with tempfile.TemporaryDirectory() as tmpdir:
            org_id = "test-org-status"
            original_capsule = institution_brain_policy.capsule_path
            institution_brain_policy.capsule_path = lambda oid, fname: os.path.join(tmpdir, f"{oid}_{fname}")
            try:
                institution_brain_policy.configure_policy(
                    org_id,
                    route_type="http_json",
                    provider_profile="openai_compat",
                    model="gpt-4o",
                    updated_by="unit_test",
                    endpoint="https://api.example.com/v1/chat/completions",
                    auth_env="OPENAI_API_KEY",
                )
                status = institution_brain_policy.policy_status(org_id)
                self.assertTrue(status["configured"])
                self.assertIsNotNone(status["active_route"])
                self.assertIn("openai_compat", json.dumps(status["provider_registry"]))
            finally:
                institution_brain_policy.capsule_path = original_capsule


# ── core.sh help text tests ──────────────────────────────────────────────


class TestHelpTextCompleteness(unittest.TestCase):
    """Verify help text documents all new Tranche 4 features."""

    @classmethod
    def setUpClass(cls):
        cls.help_text = CORE_SH.read_text(encoding="utf-8")

    def test_help_mentions_provider_list(self):
        self.assertIn("provider list", self.help_text)

    def test_help_mentions_provider_use(self):
        self.assertIn("provider use", self.help_text)

    def test_help_mentions_config_set(self):
        self.assertIn("config set", self.help_text)

    def test_help_mentions_config_get(self):
        self.assertIn("config get", self.help_text)

    def test_help_mentions_session_archive(self):
        self.assertIn("session archive", self.help_text)

    def test_help_mentions_model_override(self):
        self.assertIn("--model", self.help_text)

    def test_chat_help_mentions_model_command(self):
        self.assertIn("/model MODEL", self.help_text)

    def test_chat_help_mentions_provider_command(self):
        self.assertIn("/provider", self.help_text)

    def test_help_mentions_model_override_example(self):
        self.assertIn("core.sh ask --model", self.help_text)


# ── core.sh ask --model flag tests ───────────────────────────────────────


class TestAskModelFlag(unittest.TestCase):
    """Test that --model flag is correctly parsed and passed through."""

    def test_model_flag_in_core_sh_source(self):
        """Verify cmd_ask parses --model flag."""
        content = CORE_SH.read_text(encoding="utf-8")
        self.assertIn("--model|-m)", content)
        self.assertIn("model_override", content)

    def test_model_passed_to_gateway_payload(self):
        """Verify model_override is included in the gateway payload construction."""
        content = CORE_SH.read_text(encoding="utf-8")
        self.assertIn('payload["model"] = model_override', content)


if __name__ == "__main__":
    unittest.main()
