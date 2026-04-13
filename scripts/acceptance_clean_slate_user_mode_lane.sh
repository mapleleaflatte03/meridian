#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

TMP_DIR="${TMPDIR:-/tmp}/meridian_clean_slate_lane_$$"
trap 'rm -rf "${TMP_DIR}"' EXIT

ISOLATED_ROOT="${TMP_DIR}/root"
ISOLATED_KERNEL="${TMP_DIR}/kernel"
ISOLATED_INTELLIGENCE="${TMP_DIR}/intelligence"
BOOTSTRAP_LOG="${TMP_DIR}/bootstrap.log"
ORG_SNAPSHOT_BEFORE="${TMP_DIR}/organizations.before.json"

mkdir -p "${ISOLATED_ROOT}" "${ISOLATED_KERNEL}" "${ISOLATED_INTELLIGENCE}"
cp -a "${ROOT_DIR}/kernel/." "${ISOLATED_KERNEL}/"
cp -a "${ROOT_DIR}/intelligence/." "${ISOLATED_INTELLIGENCE}/"

ORG_FILE="${ISOLATED_INTELLIGENCE}/company/meridian_platform/organizations.json"
if [ -f "${ORG_FILE}" ]; then
  cp "${ORG_FILE}" "${ORG_SNAPSHOT_BEFORE}"
fi

echo "[clean-slate-lane] running user-mode bootstrap in isolated roots"
if ! MERIDIAN_INSTALL_MODE=user \
  MERIDIAN_AUTO_START_STACK=0 \
  MERIDIAN_SKIP_LOOM_BUILD=1 \
  MERIDIAN_SKIP_SMOKE_CHECK=1 \
  MERIDIAN_ROOT="${ISOLATED_ROOT}" \
  MERIDIAN_LOOM_ROOT="${ROOT_DIR}/loom" \
  MERIDIAN_KERNEL_ROOT="${ISOLATED_KERNEL}" \
  MERIDIAN_INTELLIGENCE_ROOT="${ISOLATED_INTELLIGENCE}" \
  ./scripts/bootstrap_full.sh >"${BOOTSTRAP_LOG}" 2>&1; then
  echo "[clean-slate-lane] bootstrap failed; dumping log" >&2
  cat "${BOOTSTRAP_LOG}" >&2 || true
  exit 1
fi

echo "[clean-slate-lane] validating no seeded institution or credentials"
python3 - <<'PY' "${TMP_DIR}"
import pathlib
import sys

base = pathlib.Path(sys.argv[1])
root_runtime = base / "root" / "runtime"
orgs_after = base / "intelligence" / "company" / "meridian_platform" / "organizations.json"
orgs_before = base / "organizations.before.json"
bootstrap_log = base / "bootstrap.log"

cred_path = root_runtime / "workspace_credentials"
runtime_smoke = root_runtime / "bootstrap_gateway_smoke.json"

if cred_path.exists():
    raise SystemExit(f"clean-slate violation: credentials file exists at {cred_path}")
if runtime_smoke.exists():
    raise SystemExit(f"clean-slate violation: gateway smoke artifact should not exist in user mode: {runtime_smoke}")

log_text = bootstrap_log.read_text(encoding="utf-8")
required_line = "User mode: leaving workspace state clean-slate for onboarding."
if required_line not in log_text:
    raise SystemExit("clean-slate violation: bootstrap log missing explicit clean-slate user-mode marker")
for banned in ("Workspace org id:", "Bootstrapping workspace platform state..."):
    if banned in log_text:
        raise SystemExit(f"clean-slate violation: bootstrap entered seeded workspace flow: {banned}")

if orgs_before.exists():
    if not orgs_after.exists():
        raise SystemExit("clean-slate violation: organizations.json was removed during user-mode bootstrap")
    if orgs_before.read_bytes() != orgs_after.read_bytes():
        raise SystemExit("clean-slate violation: organizations.json mutated during user-mode bootstrap")
else:
    if orgs_after.exists():
        raise SystemExit("clean-slate violation: organizations.json was created during user-mode bootstrap")

print("[clean-slate-lane] PASS")
PY
