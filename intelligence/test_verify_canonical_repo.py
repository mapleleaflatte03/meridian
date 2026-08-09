#!/usr/bin/env python3
"""Tests for scripts/verify_canonical_repo.sh.

Workspace clarity preflight: ensures any coding agent landing in this
workspace can immediately tell which path is canonical and which are
archived mirrors. Tests both human and JSON output, plus strict-mode
exit semantics.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = MERIDIAN_ROOT / "scripts" / "verify_canonical_repo.sh"


def _git_init(path: Path, dirty: bool, archive_marker: bool) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "-C", str(path), "init", "-q", "-b", "main"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "test"],
        check=True,
    )
    (path / "README.md").write_text("seed", encoding="utf-8")
    if archive_marker:
        (path / "ARCHIVE_POLICY.md").write_text(
            "archive policy", encoding="utf-8"
        )
    subprocess.run(
        ["git", "-C", str(path), "add", "."],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-q", "-m", "seed"],
        check=True,
    )
    if dirty:
        (path / "extra.txt").write_text("uncommitted", encoding="utf-8")


def _run(env_overrides: dict, *args, expect_rc: int | None = None):
    env = os.environ.copy()
    env.update(env_overrides)
    result = subprocess.run(
        [str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
    )
    if expect_rc is not None:
        assert result.returncode == expect_rc, (
            f"expected rc {expect_rc}, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


class TestVerifyCanonicalRepo(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="meridian-vcr-"))
        self.canonical = self.tmp / "canonical"
        self.mirror_clean = self.tmp / "mirror_clean"
        self.mirror_dirty = self.tmp / "mirror_dirty"
        self.missing = self.tmp / "missing_path"
        _git_init(self.canonical, dirty=False, archive_marker=False)
        _git_init(self.mirror_clean, dirty=False, archive_marker=True)
        _git_init(self.mirror_dirty, dirty=True, archive_marker=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _env(self) -> dict:
        return {
            "MERIDIAN_CANONICAL_PATH": str(self.canonical),
            "MERIDIAN_MIRROR_PATHS": ":".join(
                [str(self.mirror_clean), str(self.mirror_dirty), str(self.missing)]
            ),
        }

    def test_json_output_shape(self):
        result = _run(self._env(), "--json", expect_rc=0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["canonical_path"], str(self.canonical))
        self.assertEqual(len(payload["repos"]), 4)
        roles = {r["path"]: r["role"] for r in payload["repos"]}
        self.assertEqual(roles[str(self.canonical)], "canonical")
        self.assertEqual(roles[str(self.mirror_clean)], "mirror_archived")
        self.assertEqual(roles[str(self.mirror_dirty)], "mirror_archived")
        self.assertEqual(roles[str(self.missing)], "mirror_archived")

    def test_json_marks_missing_path(self):
        result = _run(self._env(), "--json")
        payload = json.loads(result.stdout)
        missing = next(r for r in payload["repos"] if r["path"] == str(self.missing))
        self.assertEqual(missing["presence"], "missing")

    def test_json_marks_dirty_mirror(self):
        result = _run(self._env(), "--json")
        payload = json.loads(result.stdout)
        dirty = next(r for r in payload["repos"] if r["path"] == str(self.mirror_dirty))
        self.assertEqual(dirty["presence"], "present")
        self.assertEqual(dirty["git_state"], "dirty")
        self.assertEqual(dirty["archive_marker"], "ARCHIVE_POLICY.md")

    def test_human_output_lists_canonical_and_mirrors(self):
        result = _run(self._env(), expect_rc=0)
        self.assertIn(str(self.canonical), result.stdout)
        self.assertIn("canonical", result.stdout)
        self.assertIn("mirror_archived", result.stdout)
        self.assertIn(str(self.mirror_clean), result.stdout)

    def test_strict_exits_nonzero_when_mirror_is_dirty(self):
        # mirror_dirty has uncommitted changes -> strict should exit 2.
        result = _run(self._env(), "--strict")
        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "WARN: archived mirror has uncommitted divergence",
            result.stderr,
        )
        self.assertIn(str(self.mirror_dirty), result.stderr)

    def test_strict_exits_zero_when_all_mirrors_clean(self):
        env = {
            "MERIDIAN_CANONICAL_PATH": str(self.canonical),
            "MERIDIAN_MIRROR_PATHS": str(self.mirror_clean),
        }
        result = _run(env, "--strict")
        self.assertEqual(result.returncode, 0)

    def test_unknown_arg_rejected(self):
        result = _run(self._env(), "--bogus")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown arg", result.stderr)


class TestCoreWhichRepoWrapper(unittest.TestCase):
    """core.sh which-repo must surface the verifier so operators don't need
    to know about scripts/verify_canonical_repo.sh directly."""

    @classmethod
    def setUpClass(cls):
        core_sh = MERIDIAN_ROOT / "scripts" / "core.sh"
        cls.source = core_sh.read_text(encoding="utf-8")

    def test_which_repo_dispatched_in_main_switch(self):
        self.assertIn(
            'which-repo)  cmd_which_repo "$@" ;;',
            self.source,
        )

    def test_cmd_which_repo_function_exists(self):
        self.assertIn("cmd_which_repo()", self.source)

    def test_cmd_which_repo_delegates_to_verifier(self):
        # Delegates to scripts/verify_canonical_repo.sh; do not
        # reimplement the probe logic in core.sh.
        self.assertIn("verify_canonical_repo.sh", self.source)
        self.assertIn(
            'bash "$verifier" "$@"',
            self.source,
        )

    def test_help_lists_which_repo(self):
        # The cmd_help() heredoc spans more than 8000 chars; assert the
        # which-repo entry directly with its argument signature so we
        # cannot match an incidental prose mention elsewhere.
        self.assertIn(
            "which-repo [--json] [--strict]",
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
