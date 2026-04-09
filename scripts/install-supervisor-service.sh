#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
UNIT_PATH="${UNIT_DIR}/meridian-runtime-supervisor.service"

mkdir -p "${UNIT_DIR}"

cat >"${UNIT_PATH}" <<EOF
[Unit]
Description=Meridian Runtime Supervisor (workspace/peer/gateway auto-restart)
After=network.target

[Service]
Type=simple
WorkingDirectory=${ROOT_DIR}
Environment=MERIDIAN_ROOT=${ROOT_DIR}
Environment=MERIDIAN_KERNEL_ROOT=${ROOT_DIR}/kernel
Environment=MERIDIAN_INTELLIGENCE_ROOT=${ROOT_DIR}/intelligence
Environment=MERIDIAN_WORKSPACE_PORT=18901
Environment=MERIDIAN_WORKSPACE_PEER_PORT=19001
Environment=MERIDIAN_GATEWAY_PORT=8266
Environment=MERIDIAN_HEARTBEAT_ENABLED=0
Environment=MERIDIAN_SUPERVISOR_INTERVAL_SECONDS=5
ExecStart=${ROOT_DIR}/scripts/dev-supervisor.sh run
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
EOF

if systemctl --user list-unit-files 2>/dev/null | grep -q '^meridian-gateway.service'; then
  systemctl --user disable --now meridian-gateway.service >/dev/null 2>&1 || true
fi

systemctl --user daemon-reload
systemctl --user enable --now meridian-runtime-supervisor.service
systemctl --user status meridian-runtime-supervisor.service --no-pager
