#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${MERIDIAN_ROOT:-$ROOT_DIR}/runtime"
PID_DIR="${RUNTIME_DIR}/pids"

stop_from_pid_file() {
  local name="$1"
  local pid_file="${PID_DIR}/${name}.pid"
  if [[ ! -f "$pid_file" ]]; then
    echo "[dev-down] ${name}: no pid file"
    return
  fi

  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -z "$pid" ]]; then
    rm -f "$pid_file"
    echo "[dev-down] ${name}: empty pid file removed"
    return
  fi

  if kill -0 "$pid" >/dev/null 2>&1; then
    kill "$pid" >/dev/null 2>&1 || true
    sleep 0.4
    kill -9 "$pid" >/dev/null 2>&1 || true
    echo "[dev-down] ${name}: stopped pid ${pid}"
  else
    echo "[dev-down] ${name}: pid ${pid} not running"
  fi
  rm -f "$pid_file"
}

stop_from_pid_file "gateway"
stop_from_pid_file "workspace"

echo "[dev-down] done"
