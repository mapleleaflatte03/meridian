#!/usr/bin/env python3
"""
Build a migration-grade bundle for the current Meridian host.

Contents:
- readiness snapshot
- repo sync/status metadata
- tracked git diff patches for local repos
- tarball of untracked repo files
- tarball of critical host state/config paths
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import readiness


BACKUP_ROOT = Path("/home/ubuntu/.meridian/backups")


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _run(cmd: list[str], *, cwd: str | None = None, timeout: int = 120) -> dict[str, object]:
    try:
        completed = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": 124,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or f"timeout after {timeout}s",
        }
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_manifest_entry(path: Path) -> dict[str, object]:
    entry: dict[str, object] = {
        "path": str(path),
        "exists": path.exists(),
    }
    if not path.exists():
        return entry
    if path.is_dir():
        files = 0
        total_bytes = 0
        for item in path.rglob("*"):
            if item.is_file():
                files += 1
                try:
                    total_bytes += item.stat().st_size
                except OSError:
                    pass
        entry.update({
            "type": "directory",
            "file_count": files,
            "total_bytes": total_bytes,
        })
        return entry
    entry.update({
        "type": "file",
        "size_bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    })
    return entry


def _bundle_repo(label: str, repo_path: str, dest_dir: Path) -> dict[str, object]:
    repo_dir = dest_dir / label
    repo_dir.mkdir(parents=True, exist_ok=True)
    snapshot = readiness._repo_sync_snapshot(label, repo_path)
    _write_json(repo_dir / "repo-sync.json", snapshot)

    status = _run(["git", "status", "--short"], cwd=repo_path, timeout=30)
    (repo_dir / "git-status.txt").write_text((status.get("stdout") or "") + (status.get("stderr") or ""), encoding="utf-8")

    diff = _run(["git", "diff", "--binary"], cwd=repo_path, timeout=300)
    (repo_dir / "tracked.patch").write_text((diff.get("stdout") or "") + (diff.get("stderr") or ""), encoding="utf-8")

    untracked = list(snapshot.get("untracked") or [])
    (repo_dir / "untracked.txt").write_text("\n".join(untracked) + ("\n" if untracked else ""), encoding="utf-8")
    if untracked:
        archive_path = repo_dir / "untracked.tar.gz"
        with tarfile.open(archive_path, "w:gz") as tar:
            for relative in untracked:
                source = Path(repo_path) / relative
                if source.exists():
                    tar.add(source, arcname=relative)

    head_log = _run(["git", "log", "-1", "--oneline", "--decorate", "HEAD"], cwd=repo_path, timeout=20)
    origin_log = _run(["git", "log", "-1", "--oneline", "--decorate", "origin/main"], cwd=repo_path, timeout=20)
    (repo_dir / "head.txt").write_text((head_log.get("stdout") or "") + (head_log.get("stderr") or ""), encoding="utf-8")
    (repo_dir / "origin-main.txt").write_text((origin_log.get("stdout") or "") + (origin_log.get("stderr") or ""), encoding="utf-8")
    return snapshot


def _bundle_state(paths: list[tuple[str, str]], output_dir: Path) -> list[dict[str, object]]:
    archive_path = output_dir / "state-bundle.tar.gz"
    manifest: list[dict[str, object]] = []
    archive_members: list[str] = []
    for raw_path, kind in paths:
        target = Path(raw_path)
        entry = _path_manifest_entry(target)
        entry["kind"] = kind
        manifest.append(entry)
        if target.exists():
            archive_members.append(str(target).lstrip("/"))
    if archive_members:
        cmd = [
            "tar",
            "--warning=no-file-changed",
            "--ignore-failed-read",
            "-czf",
            str(archive_path),
            "-C",
            "/",
            *archive_members,
        ]
        result = _run(cmd, cwd="/", timeout=600)
        if not result["ok"]:
            raise SystemExit(f"state archive failed: {(result.get('stderr') or result.get('stdout') or '').strip()}")
    _write_json(output_dir / "state-manifest.json", manifest)
    return manifest


def build_bundle(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    readiness_report = readiness.collect()
    _write_json(output_dir / "readiness.json", readiness_report)

    repos_dir = output_dir / "repos"
    repo_snapshots = {}
    for label, repo_path in readiness.MIGRATION_REPOS:
        repo_snapshots[label] = _bundle_repo(label, repo_path, repos_dir)

    state_manifest = _bundle_state(list(readiness.MIGRATION_CRITICAL_PATHS), output_dir)
    summary = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "output_dir": str(output_dir),
        "readiness_file": str(output_dir / "readiness.json"),
        "state_archive": str(output_dir / "state-bundle.tar.gz"),
        "state_manifest_file": str(output_dir / "state-manifest.json"),
        "repos": repo_snapshots,
        "state_manifest": state_manifest,
    }
    _write_json(output_dir / "bundle-summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Meridian migration bundle from the current host")
    parser.add_argument(
        "--output-dir",
        default=str(BACKUP_ROOT / f"migration-bundle-{_now_stamp()}"),
        help="Destination directory for the generated bundle",
    )
    args = parser.parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    summary = build_bundle(output_dir)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
