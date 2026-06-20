#!/usr/bin/env python3
"""Tests for mirror lock markers (Tranche 29).

scripts/install_mirror_locks.sh must:
- exist, be executable, and contain the documented flags (--dry-run, --help)
- install three artifacts into each mirror: MIRROR_LOCK.md,
  MIRROR_LOCK.json, and a .git/hooks/pre-commit script that refuses
  commits unless MERIDIAN_MIRROR_ALLOW_COMMIT=1

scripts/verify_canonical_repo.sh --strict must flag mirrors that are
missing any of those artifacts.
"""

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = MERIDIAN_ROOT / "scripts" / "install_mirror_locks.sh"
VERIFY_SH = MERIDIAN_ROOT / "scripts" / "verify_canonical_repo.sh"


def _init_fake_mirror(base: Path) -> Path:
    """Create a tiny empty git repo that looks like an archived mirror."""
    base.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=base, check=True)
    subprocess.run(
        ["git", "-C", str(base), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(base), "config", "user.name", "test"],
        check=True,
    )
    # Create an initial commit so `git log` has something to report.
    (base / "README.md").write_text("# fake mirror\n")
    subprocess.run(["git", "-C", str(base), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(base), "commit", "-q", "-m", "init"],
        check=True,
    )
    return base


class TestInstallMirrorLocksScript(unittest.TestCase):
    def test_script_exists_and_is_executable(self):
        self.assertTrue(INSTALL_SH.is_file())
        mode = INSTALL_SH.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR, "install script should be executable")

    def test_script_help_documents_flags(self):
        out = subprocess.check_output(
            ["bash", str(INSTALL_SH), "--help"], text=True
        )
        self.assertIn("--dry-run", out)
        self.assertIn("install_mirror_locks", out)

    def test_dry_run_installs_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            mirror = _init_fake_mirror(tdp / "fake-mirror")
            env = os.environ.copy()
            env["MERIDIAN_MIRROR_PATHS"] = str(mirror)
            subprocess.run(
                ["bash", str(INSTALL_SH), "--dry-run"],
                env=env, check=True, capture_output=True,
            )
            self.assertFalse((mirror / "MIRROR_LOCK.md").exists())
            self.assertFalse((mirror / "MIRROR_LOCK.json").exists())
            self.assertFalse((mirror / ".git" / "hooks" / "pre-commit").exists())

    def test_install_writes_all_three_markers(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            mirror = _init_fake_mirror(tdp / "fake-mirror")
            env = os.environ.copy()
            env["MERIDIAN_MIRROR_PATHS"] = str(mirror)
            subprocess.run(
                ["bash", str(INSTALL_SH)],
                env=env, check=True, capture_output=True,
            )
            self.assertTrue((mirror / "MIRROR_LOCK.md").is_file())
            lock_json = mirror / "MIRROR_LOCK.json"
            self.assertTrue(lock_json.is_file())
            parsed = json.loads(lock_json.read_text())
            self.assertEqual(parsed.get("kind"), "meridian_mirror_lock")
            self.assertIn("canonical_path", parsed)
            hook = mirror / ".git" / "hooks" / "pre-commit"
            self.assertTrue(hook.is_file())
            self.assertTrue(hook.stat().st_mode & stat.S_IXUSR)

    def test_installed_hook_blocks_commits_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            mirror = _init_fake_mirror(tdp / "fake-mirror")
            env = os.environ.copy()
            env["MERIDIAN_MIRROR_PATHS"] = str(mirror)
            subprocess.run(
                ["bash", str(INSTALL_SH)],
                env=env, check=True, capture_output=True,
            )
            # An empty commit should be refused by the hook.
            # Make sure we use an explicitly set hook path config in case global config bypasses it
            subprocess.run(["git", "-C", str(mirror), "config", "core.hooksPath", ".git/hooks"], check=True)
            proc = subprocess.run(
                ["git", "-C", str(mirror), "commit",
                 "--allow-empty", "-m", "should be blocked"],
                capture_output=True, text=True,
            )
            self.assertNotEqual(proc.returncode, 0,
                                "hook must refuse commits by default")
            self.assertIn("archived mirror", (proc.stderr or proc.stdout).lower())

    def test_installed_hook_allows_override_env(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            mirror = _init_fake_mirror(tdp / "fake-mirror")
            env = os.environ.copy()
            env["MERIDIAN_MIRROR_PATHS"] = str(mirror)
            subprocess.run(
                ["bash", str(INSTALL_SH)],
                env=env, check=True, capture_output=True,
            )
            # With the override set, the commit must succeed.
            subprocess.run(["git", "-C", str(mirror), "config", "core.hooksPath", ".git/hooks"], check=True)
            env2 = os.environ.copy()
            env2["MERIDIAN_MIRROR_ALLOW_COMMIT"] = "1"
            env2["GIT_AUTHOR_NAME"] = "test"
            env2["GIT_AUTHOR_EMAIL"] = "t@e.com"
            env2["GIT_COMMITTER_NAME"] = "test"
            env2["GIT_COMMITTER_EMAIL"] = "t@e.com"
            proc = subprocess.run(
                ["git", "-C", str(mirror), "commit",
                 "--allow-empty", "-m", "legit mirror sync"],
                env=env2, capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0,
                             f"override should allow commit; stderr={proc.stderr}")


class TestVerifyReportsLockState(unittest.TestCase):
    def test_verify_json_reports_lock_column(self):
        # Point verify at two fake mirrors — one locked, one unlocked.
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            locked = _init_fake_mirror(tdp / "locked-mirror")
            unlocked = _init_fake_mirror(tdp / "unlocked-mirror")
            env = os.environ.copy()
            env["MERIDIAN_MIRROR_PATHS"] = f"{locked}:{unlocked}"
            # Install lock only on the first.
            subprocess.run(
                ["bash", str(INSTALL_SH)],
                env={**env, "MERIDIAN_MIRROR_PATHS": str(locked)},
                check=True, capture_output=True,
            )
            out = subprocess.check_output(
                ["bash", str(VERIFY_SH), "--json"],
                env=env, text=True,
            )
            payload = json.loads(out)
            mirrors = {r["path"]: r for r in payload["repos"] if r["role"] == "mirror_archived"}
            self.assertEqual(mirrors[str(locked)]["lock_state"], "locked")
            self.assertEqual(mirrors[str(unlocked)]["lock_state"], "unlocked")

    def test_verify_strict_flags_unlocked_mirror(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            unlocked = _init_fake_mirror(tdp / "unlocked-mirror")
            env = os.environ.copy()
            env["MERIDIAN_MIRROR_PATHS"] = str(unlocked)
            proc = subprocess.run(
                ["bash", str(VERIFY_SH), "--strict"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 2,
                             "strict mode should exit 2 when a mirror is unlocked")
            self.assertIn("not fully locked", proc.stderr)


if __name__ == "__main__":
    unittest.main()
