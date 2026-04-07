#!/usr/bin/env python3
import os
import shlex
import subprocess
import sys
from pathlib import Path

LOOM_REPO = Path('/home/ubuntu/meridian-loom')
IMAGE = 'ubuntu:22.04'
EXPECTED_MARKERS = [
    'MERIDIAN LOOM',
    'Constitutional Runtime v0.1.0.',
    '==> Building Meridian Loom release',
    '==> Installed loom binary to',
    '==> Installation complete',
]


def run() -> int:
    if not LOOM_REPO.exists():
        print(f'loom repo missing: {LOOM_REPO}')
        return 1

    container_script = r'''
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get -qq update
apt-get install -y -qq --no-install-recommends curl build-essential
cp -a /src /tmp/meridian-loom
cd /tmp/meridian-loom
bash scripts/install.sh
INSTALL_ROOT="$HOME/.local/share/meridian-loom"
test -x "$INSTALL_ROOT/current/bin/loom"
test -f "$INSTALL_ROOT/runtime/default/loom.toml"
test -f "$INSTALL_ROOT/runtime/default/capabilities/registry.json"
printf 'artifact_check: binary=%s config=%s registry=%s\n' \
  "$INSTALL_ROOT/current/bin/loom" \
  "$INSTALL_ROOT/runtime/default/loom.toml" \
  "$INSTALL_ROOT/runtime/default/capabilities/registry.json"
'''.strip()

    docker_cmd = [
        'docker', 'run', '--rm',
        '-v', f'{LOOM_REPO}:/src:ro',
        IMAGE,
        'bash', '-lc', container_script,
    ]
    print('$ ' + ' '.join(shlex.quote(part) for part in docker_cmd))
    try:
        completed = subprocess.run(
            docker_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        print(f'docker unavailable: {exc}')
        return 1
    except Exception as exc:  # pragma: no cover - exact failure reporting path
        print(f'docker invocation failed: {exc}')
        return 1

    output = completed.stdout or ''
    if output:
        print(output, end='' if output.endswith('\n') else '\n')

    missing = [marker for marker in EXPECTED_MARKERS if marker not in output]
    if completed.returncode != 0:
        print(f'docker sandbox failed with exit code {completed.returncode}')
        return completed.returncode or 1
    if missing:
        print('missing expected installer markers: ' + ', '.join(missing))
        return 1
    print('sandbox_assertions: ok')
    return 0


if __name__ == '__main__':
    raise SystemExit(run())
