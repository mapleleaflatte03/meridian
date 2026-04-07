#!/usr/bin/env python3
"""
Restore a Meridian host from a migration bundle.

Usage:
  python3 company/meridian_platform/migration_restore.py --bundle-dir /path/to/bundle --dry-run
  python3 company/meridian_platform/migration_restore.py --bundle-dir /path/to/bundle --restore
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path


SYSTEM_UNITS = (
    "meridian-workspace.service",
    "meridian-mcp.service",
    "meridian-loom.service",
    "caddy.service",
)
USER_UNITS = ("meridian-gateway.service",)


@dataclass
class RestorePaths:
    bundle_dir: Path
    state_manifest: Path
    state_archive: Path
    readiness_file: Path | None = None
    summary_file: Path | None = None


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_paths(bundle_dir: Path) -> RestorePaths:
    summary_path = bundle_dir / "bundle-summary.json"
    summary = _load_json(summary_path) if summary_path.exists() else {}
    state_manifest = Path(summary.get("state_manifest_file") or bundle_dir / "state-manifest.json")
    state_archive = Path(summary.get("state_archive") or bundle_dir / "state-bundle.tar.gz")
    readiness_file = Path(summary["readiness_file"]) if isinstance(summary, dict) and summary.get("readiness_file") else None
    if not state_manifest.exists():
        raise FileNotFoundError(f"missing state manifest: {state_manifest}")
    if not state_archive.exists():
        raise FileNotFoundError(f"missing state archive: {state_archive}")
    return RestorePaths(
        bundle_dir=bundle_dir,
        state_manifest=state_manifest,
        state_archive=state_archive,
        readiness_file=readiness_file if readiness_file and readiness_file.exists() else None,
        summary_file=summary_path if summary_path.exists() else None,
    )


def _is_safe_member(member_name: str) -> bool:
    path = Path(member_name)
    return not path.is_absolute() and ".." not in path.parts


def _run(cmd: list[str], *, timeout: int = 120) -> dict[str, object]:
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _service_action(action: str, *, dry_run: bool) -> list[dict[str, object]]:
    ops: list[dict[str, object]] = []
    for unit in SYSTEM_UNITS:
        cmd = ["systemctl", action, unit]
        ops.append({"scope": "system", "unit": unit, "cmd": cmd, "result": None if dry_run else _run(cmd)})
    for unit in USER_UNITS:
        cmd = ["systemctl", "--user", action, unit]
        ops.append({"scope": "user", "unit": unit, "cmd": cmd, "result": None if dry_run else _run(cmd)})
    return ops


def _manifest_summary(manifest: list[dict[str, object]]) -> dict[str, object]:
    files = sum(1 for item in manifest if item.get("type") == "file")
    directories = sum(1 for item in manifest if item.get("type") == "directory")
    missing = [item["path"] for item in manifest if not item.get("exists")]
    return {
        "entry_count": len(manifest),
        "files": files,
        "directories": directories,
        "missing_entries": missing,
    }


def verify_manifest(manifest: list[dict[str, object]]) -> dict[str, object]:
    results = []
    ok = True
    for item in manifest:
        path = Path(item["path"])
        exists = path.exists()
        entry = {
            "path": str(path),
            "kind": item.get("kind"),
            "expected_exists": bool(item.get("exists")),
            "actual_exists": exists,
            "status": "ok",
        }
        if bool(item.get("exists")) != exists:
            entry["status"] = "mismatch"
            ok = False
        elif exists and item.get("type") == "file":
            actual_size = path.stat().st_size
            entry["actual_size_bytes"] = actual_size
            if item.get("size_bytes") is not None and actual_size != item["size_bytes"]:
                entry["status"] = "size_mismatch"
                ok = False
        elif exists and item.get("type") == "directory":
            entry["actual_type"] = "directory"
        results.append(entry)
    return {"ok": ok, "results": results}


def extract_archive(state_archive: Path, *, dry_run: bool) -> dict[str, object]:
    with tarfile.open(state_archive, "r:gz") as archive:
        members = archive.getmembers()
        unsafe = [member.name for member in members if not _is_safe_member(member.name)]
        if unsafe:
            raise ValueError(f"unsafe archive members: {unsafe[:5]}")
        if dry_run:
            return {"member_count": len(members), "sample_members": [member.name for member in members[:10]], "restored": False}
        archive.extractall(path="/")
        return {"member_count": len(members), "sample_members": [member.name for member in members[:10]], "restored": True}


def collect(bundle_dir: Path) -> dict[str, object]:
    paths = _resolve_paths(bundle_dir)
    manifest = _load_json(paths.state_manifest)
    if not isinstance(manifest, list):
        raise ValueError(f"invalid manifest format: {paths.state_manifest}")
    return {
        "bundle_dir": str(paths.bundle_dir),
        "summary_file": str(paths.summary_file) if paths.summary_file else None,
        "readiness_file": str(paths.readiness_file) if paths.readiness_file else None,
        "state_manifest": str(paths.state_manifest),
        "state_archive": str(paths.state_archive),
        "manifest_summary": _manifest_summary(manifest),
        "verify": verify_manifest(manifest),
    }


def restore(bundle_dir: Path, *, stop_services: bool, start_services: bool, dry_run: bool) -> dict[str, object]:
    paths = _resolve_paths(bundle_dir)
    manifest = _load_json(paths.state_manifest)
    if not isinstance(manifest, list):
        raise ValueError(f"invalid manifest format: {paths.state_manifest}")
    stop_ops = _service_action("stop", dry_run=dry_run) if stop_services else []
    archive_result = extract_archive(paths.state_archive, dry_run=dry_run)
    verify_result = verify_manifest(manifest) if not dry_run else {"ok": None, "results": []}
    start_ops = _service_action("start", dry_run=dry_run) if start_services else []
    return {
        "bundle_dir": str(paths.bundle_dir),
        "state_manifest": str(paths.state_manifest),
        "state_archive": str(paths.state_archive),
        "stopped_services": stop_ops,
        "archive_restore": archive_result,
        "verify": verify_result,
        "started_services": start_ops,
        "dry_run": dry_run,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore a Meridian host from a migration bundle")
    parser.add_argument("--bundle-dir", required=True, help="Bundle directory created by migration_bundle.py")
    mode = parser.add_mutually_exclusive_group(required=False)
    mode.add_argument("--restore", action="store_true", help="Restore the state archive onto this host")
    mode.add_argument("--verify-only", action="store_true", help="Verify current host paths against the bundle manifest")
    parser.add_argument("--dry-run", action="store_true", help="Print intended restore actions without extracting")
    parser.add_argument("--stop-services", action="store_true", help="Stop Meridian services before restore")
    parser.add_argument("--start-services", action="store_true", help="Start Meridian services after restore")
    args = parser.parse_args(argv)

    bundle_dir = Path(args.bundle_dir).expanduser().resolve()
    try:
        if args.restore:
            payload = restore(
                bundle_dir,
                stop_services=args.stop_services,
                start_services=args.start_services,
                dry_run=args.dry_run,
            )
        else:
            payload = collect(bundle_dir)
    except Exception as exc:  # pragma: no cover - CLI error path
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
