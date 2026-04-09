#!/usr/bin/env bash
set -euo pipefail

UNIT_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
UNIT_PATH="${UNIT_DIR}/meridian-runtime-supervisor.service"

systemctl --user disable --now meridian-runtime-supervisor.service >/dev/null 2>&1 || true
rm -f "${UNIT_PATH}"
systemctl --user daemon-reload

echo "[supervisor-service] removed ${UNIT_PATH}"
