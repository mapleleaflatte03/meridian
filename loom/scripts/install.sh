#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
HOME_DIR="${HOME:-$(getent passwd "$(id -u)" | cut -d: -f6)}"
if [[ -z "$HOME_DIR" ]]; then
  echo 'failed to resolve HOME directory for installer prefix' >&2
  exit 1
fi
export HOME="$HOME_DIR"

PREFIX="${LOOM_PREFIX:-${HOME_DIR}/.local/share/meridian-loom}"
CURRENT_DIR="${PREFIX}/current"
BIN_DIR="${LOOM_BIN_DIR:-${HOME_DIR}/.local/bin}"
RUNTIME_ROOT="${LOOM_RUNTIME_ROOT:-${PREFIX}/runtime/default}"
BINARY_PATH="${BIN_DIR}/loom"
KERNEL_PATH="${LOOM_KERNEL_PATH:-}"
RELEASE_REPO="${LOOM_RELEASE_REPO:-mapleleaflatte03/meridian-loom}"
RELEASE_VERSION="${LOOM_RELEASE_VERSION:-latest}"
INSTALL_MODE="${LOOM_INSTALL_MODE:-auto}"
CARGO_HOME="${CARGO_HOME:-${HOME_DIR}/.cargo}"
RUSTUP_HOME="${RUSTUP_HOME:-${HOME_DIR}/.rustup}"
CARGO_ENV="${CARGO_HOME}/env"
RUSTUP_INIT_URL="https://sh.rustup.rs"

SUDO=()
APT_UPDATED=0
RUNTIME_WAS_INITIALIZED=0
ONBOARD_WAS_RUN=0
INSTALL_SOURCE="unknown"

ensure_admin_access() {
  local reason="${1:-administrative action}"
  if [[ $(id -u) -eq 0 ]]; then
    return
  fi
  if [[ ${#SUDO[@]} -gt 0 ]]; then
    return
  fi
  if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    SUDO=(sudo -n)
    return
  fi
  printf 'administrative privileges are required to %s\n' "$reason" >&2
  exit 1
}

ensure_privileges() {
  local target
  local writable_probe
  for target in "$PREFIX" "$BIN_DIR"; do
    writable_probe="$target"
    while [[ ! -e "$writable_probe" && "$writable_probe" != "/" ]]; do
      writable_probe="$(dirname "$writable_probe")"
    done
    if [[ -w "$writable_probe" || -w "$target" ]]; then
      continue
    fi
    ensure_admin_access "write to $target"
  done
}

run_privileged() {
  if [[ $(id -u) -eq 0 ]]; then
    "$@"
  elif [[ ${#SUDO[@]} -gt 0 ]]; then
    "${SUDO[@]}" "$@"
  else
    "$@"
  fi
}

run_admin() {
  if [[ $(id -u) -eq 0 ]]; then
    "$@"
  elif [[ ${#SUDO[@]} -gt 0 ]]; then
    "${SUDO[@]}" "$@"
  else
    printf 'administrative privileges are required to run %s\n' "$1" >&2
    exit 1
  fi
}

file_exists() {
  if [[ ${#SUDO[@]} -gt 0 ]]; then
    "${SUDO[@]}" test -f "$1"
  else
    [[ -f "$1" ]]
  fi
}

ensure_apt_updated() {
  if [[ "$APT_UPDATED" -eq 1 ]]; then
    return
  fi
  if ! command -v apt-get >/dev/null 2>&1; then
    echo 'apt-get is required to install missing dependencies automatically' >&2
    exit 1
  fi
  ensure_admin_access 'install missing system packages'
  printf '==> Refreshing apt metadata\n'
  run_admin env DEBIAN_FRONTEND=noninteractive apt-get -qq update
  APT_UPDATED=1
}

ensure_command_or_package() {
  local command_name="$1"
  local package_name="$2"
  if command -v "$command_name" >/dev/null 2>&1; then
    return
  fi
  ensure_apt_updated
  printf '==> Installing missing package %s for %s\n' "$package_name" "$command_name"
  run_admin env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends "$package_name"
}

repo_has_source_checkout() {
  [[ -f "$REPO_ROOT/Cargo.toml" && -x "$REPO_ROOT/scripts/package_release.sh" ]]
}

normalize_os() {
  case "$(uname -s)" in
    Linux) printf 'linux\n' ;;
    Darwin) printf 'darwin\n' ;;
    *)
      printf 'unsupported operating system: %s\n' "$(uname -s)" >&2
      return 1
      ;;
  esac
}

normalize_arch() {
  case "$(uname -m)" in
    x86_64|amd64) printf 'x86_64\n' ;;
    aarch64|arm64) printf 'aarch64\n' ;;
    *)
      printf 'unsupported architecture: %s\n' "$(uname -m)" >&2
      return 1
      ;;
  esac
}

release_metadata_url() {
  if [[ "$RELEASE_VERSION" == "latest" ]]; then
    printf 'https://api.github.com/repos/%s/releases/latest\n' "$RELEASE_REPO"
  else
    printf 'https://api.github.com/repos/%s/releases/tags/%s\n' "$RELEASE_REPO" "$RELEASE_VERSION"
  fi
}

extract_release_asset_urls() {
  local metadata_path="$1"
  local target_os="$2"
  local target_arch="$3"
  python3 - "$metadata_path" "$target_os" "$target_arch" <<'PY'
import json
import pathlib
import re
import sys

metadata_path = pathlib.Path(sys.argv[1])
target_os = sys.argv[2]
target_arch = sys.argv[3]
payload = json.loads(metadata_path.read_text(encoding="utf-8"))
assets = payload.get("assets", [])
pattern = re.compile(rf"^meridian-loom-.*-{re.escape(target_os)}-{re.escape(target_arch)}\.tar\.gz$")
package = None
checksum = None
for asset in assets:
    name = asset.get("name", "")
    if pattern.match(name):
        package = asset
    elif package and name == package["name"] + ".sha256":
        checksum = asset
if package is None:
    for asset in assets:
        name = asset.get("name", "")
        if pattern.match(name):
            package = asset
            break
if package is not None and checksum is None:
    checksum_name = package["name"] + ".sha256"
    for asset in assets:
        if asset.get("name") == checksum_name:
            checksum = asset
            break
if package is None:
    sys.exit(1)
print(package["name"])
print(package["browser_download_url"])
print(checksum["browser_download_url"] if checksum else "")
PY
}

verify_checksum() {
  local artifact_path="$1"
  local checksum_path="$2"
  python3 - "$artifact_path" "$checksum_path" <<'PY'
import hashlib
import pathlib
import sys

artifact = pathlib.Path(sys.argv[1])
checksum = pathlib.Path(sys.argv[2])
line = checksum.read_text(encoding="utf-8").strip().splitlines()[0]
expected = line.split()[0]
h = hashlib.sha256()
with artifact.open("rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        h.update(chunk)
actual = h.hexdigest()
if actual != expected:
    raise SystemExit(f"checksum mismatch for {artifact.name}: expected {expected}, got {actual}")
PY
}

download_prebuilt_release() {
  local target_os
  local target_arch
  local metadata_path
  local asset_name
  local asset_url
  local checksum_url
  local artifact_dir
  local artifact_path
  local checksum_path

  ensure_command_or_package curl curl
  ensure_command_or_package python3 python3

  target_os="$(normalize_os)" || return 1
  target_arch="$(normalize_arch)" || return 1
  metadata_path="$(mktemp)"
  if ! curl -fsSL -H 'Accept: application/vnd.github+json' "$(release_metadata_url)" -o "$metadata_path" 2>/dev/null; then
    rm -f "$metadata_path"
    return 1
  fi
  if ! readarray -t asset_info < <(extract_release_asset_urls "$metadata_path" "$target_os" "$target_arch"); then
    rm -f "$metadata_path"
    return 1
  fi
  rm -f "$metadata_path"
  asset_name="${asset_info[0]}"
  asset_url="${asset_info[1]}"
  checksum_url="${asset_info[2]}"
  artifact_dir="$(mktemp -d)"
  artifact_path="${artifact_dir}/${asset_name}"
  printf '==> Downloading Meridian Loom release %s\n' "$asset_name" >&2
  curl -fsSL "$asset_url" -o "$artifact_path"
  if [[ -n "$checksum_url" ]]; then
    checksum_path="${artifact_path}.sha256"
    curl -fsSL "$checksum_url" -o "$checksum_path"
    verify_checksum "$artifact_path" "$checksum_path"
  fi
  printf '%s\n' "$artifact_path"
}

seed_builtin_capabilities() {
  local registry_path
  registry_path="$RUNTIME_ROOT/capabilities/registry.json"
  run_privileged python3 - "$registry_path" <<'PY2'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
if path.exists():
    payload = json.loads(path.read_text(encoding="utf-8"))
else:
    payload = {"version": "loom.capabilities.v0", "capabilities": []}

descriptors = [
    {
        "name": "loom.browser.navigate.v1",
        "description": "Run the built-in bounded browser navigation Wasm guest through the local Wasmtime lane.",
        "action_type": "browse",
        "resource": "capability:loom.browser.navigate.v1",
        "worker_kind": "wasm",
        "interpreter": "wasmtime",
        "worker_entry": "",
        "wasm_module": "builtin:browser.navigate",
        "binary_surface": "builtin_wasm_guest",
        "payload_mode": "json",
        "source_kind": "loom_builtin",
        "source_path": "builtin:loom.browser.navigate.v1",
        "source_manifest": "",
        "adapter_kind": "loom_wasm_browser_guest_v0",
        "import_provenance": "loom_builtin_contract_v0",
        "runtime_lane": "wasm",
        "dependency_mode": "builtin",
        "env_contract": "none",
        "isolation_expectation": "pooled_wasmtime_local",
        "verification_status": "builtin",
        "last_verified_at": "",
        "last_verification_job_id": "",
        "last_verification_execution_id": "",
        "verification_note": "built-in bounded web/Wasm capability",
        "promotion_state": "builtin",
        "promoted_at": "",
        "enabled": True,
    },
    {
        "name": "loom.terminal.exec.v1",
        "description": "Run the built-in bounded terminal execution Wasm guest through the local Wasmtime lane.",
        "action_type": "execute",
        "resource": "capability:loom.terminal.exec.v1",
        "worker_kind": "wasm",
        "interpreter": "wasmtime",
        "worker_entry": "",
        "wasm_module": "builtin:terminal.exec",
        "binary_surface": "builtin_wasm_guest",
        "payload_mode": "json",
        "source_kind": "loom_builtin",
        "source_path": "builtin:loom.terminal.exec.v1",
        "source_manifest": "",
        "adapter_kind": "loom_wasm_terminal_guest_v0",
        "import_provenance": "loom_builtin_contract_v0",
        "runtime_lane": "wasm",
        "dependency_mode": "builtin",
        "env_contract": "none",
        "isolation_expectation": "pooled_wasmtime_local",
        "verification_status": "builtin",
        "last_verified_at": "",
        "last_verification_job_id": "",
        "last_verification_execution_id": "",
        "verification_note": "built-in bounded terminal/Wasm capability",
        "promotion_state": "builtin",
        "promoted_at": "",
        "enabled": True,
    },
    {
        "name": "loom.heartbeat.schedule.v1",
        "description": "Run the built-in heartbeat scheduling Wasm guest through the local Wasmtime lane and persist a bounded receipt.",
        "action_type": "schedule",
        "resource": "capability:loom.heartbeat.schedule.v1",
        "worker_kind": "wasm",
        "interpreter": "wasmtime",
        "worker_entry": "",
        "wasm_module": "builtin:heartbeat.schedule",
        "binary_surface": "builtin_wasm_guest",
        "payload_mode": "json",
        "source_kind": "loom_builtin",
        "source_path": "builtin:loom.heartbeat.schedule.v1",
        "source_manifest": "",
        "adapter_kind": "loom_wasm_heartbeat_guest_v0",
        "import_provenance": "loom_builtin_contract_v0",
        "runtime_lane": "wasm",
        "dependency_mode": "builtin",
        "env_contract": "none",
        "isolation_expectation": "pooled_wasmtime_local",
        "verification_status": "builtin",
        "last_verified_at": "",
        "last_verification_job_id": "",
        "last_verification_execution_id": "",
        "verification_note": "built-in heartbeat/Wasm capability with local receipt logging",
        "promotion_state": "builtin",
        "promoted_at": "",
        "enabled": True,
    },
]

capabilities = payload.setdefault("capabilities", [])
by_name = {item.get("name"): index for index, item in enumerate(capabilities)}
for descriptor in descriptors:
    index = by_name.get(descriptor["name"])
    if index is None:
        capabilities.append(descriptor)
    else:
        capabilities[index] = descriptor
capabilities.sort(key=lambda item: item.get("name", ""))
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY2
}

print_banner() {
  local icon
  icon="$(cat <<'BANNER'
             /\             
        /\  /  \  /\        
       /  \/ /\ \/  \       
      / /\  /  \  /\ \      
     /_/ /_/ /\ \_\ \_\     
     \ \ \ \/  \/ / / /     
      \ \/  /\  \/ / /      
       \___/  \___/ /       
BANNER
)"
  if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    printf '[38;5;81m%s[0m
' "$icon"
    printf '[1;97m%s[0m
' 'MERIDIAN'
    printf '[38;5;245m%s[0m
' 'GOVERNED LOCAL RUNTIME'
    printf '[38;5;153m%s[0m

' 'Loom v0.1.16 - official local runtime with bounded proof surfaces.'
  else
    printf '%s
' "$icon"
    printf '%s
' 'MERIDIAN'
    printf '%s
' 'GOVERNED LOCAL RUNTIME'
    printf '%s

' 'Loom v0.1.16 - official local runtime with bounded proof surfaces.'
  fi
}

source_cargo_env() {
  if [[ -f "$CARGO_ENV" ]]; then
    # shellcheck disable=SC1090
    source "$CARGO_ENV"
  fi
}

cargo_is_usable() {
  if [[ -x "${CARGO_HOME}/bin/cargo" ]]; then
    "${CARGO_HOME}/bin/cargo" --version >/dev/null 2>&1
    return $?
  fi
  command -v cargo >/dev/null 2>&1 && cargo --version >/dev/null 2>&1
}

bootstrap_rust_toolchain() {
  ensure_command_or_package curl curl
  ensure_command_or_package cc build-essential
  printf '==> Installing Rust toolchain via rustup\n'
  export CARGO_HOME RUSTUP_HOME HOME
  export RUSTUP_INIT_SKIP_PATH_CHECK=yes
  export RUSTUP_INIT_SKIP_SUDO_CHECK=yes
  curl --proto '=https' --tlsv1.2 -fsSL "$RUSTUP_INIT_URL" | sh -s -- -y --profile minimal --default-toolchain stable --no-modify-path
  export PATH="${CARGO_HOME}/bin:${PATH}"
}

ensure_cargo() {
  source_cargo_env
  export PATH="${CARGO_HOME}/bin:${PATH}"
  if cargo_is_usable; then
    return
  fi
  if [[ -x "${CARGO_HOME}/bin/rustup" ]]; then
    ensure_command_or_package cc build-essential
    printf '==> Activating Rust stable toolchain\n'
    export CARGO_HOME RUSTUP_HOME HOME
    "${CARGO_HOME}/bin/rustup" toolchain install stable --profile minimal
    "${CARGO_HOME}/bin/rustup" default stable
    source_cargo_env
    export PATH="${CARGO_HOME}/bin:${PATH}"
  fi
  if cargo_is_usable; then
    return
  fi
  bootstrap_rust_toolchain
  source_cargo_env
  if ! cargo_is_usable; then
    echo 'cargo not found after rustup bootstrap' >&2
    exit 1
  fi
}

ensure_python3() {
  ensure_command_or_package python3 python3
}

package_source_release() {
  local output_dir
  output_dir="$(mktemp -d)"
  printf '==> Building Meridian Loom release from source checkout\n' >&2
  "$REPO_ROOT/scripts/package_release.sh" --kernel-path "${KERNEL_PATH:-/opt/meridian-kernel}" --output-dir "$output_dir"
}

install_archive() {
  local archive_path="$1"
  local tmpdir
  local package_dir
  local package_name

  if [[ ! -f "$archive_path" ]]; then
    printf 'missing release archive: %s\n' "$archive_path" >&2
    exit 1
  fi

  tmpdir="$(mktemp -d)"
  tar -xzf "$archive_path" -C "$tmpdir"
  package_dir="$(find "$tmpdir" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  if [[ -z "$package_dir" || ! -d "$package_dir" ]]; then
    rm -rf "$tmpdir"
    printf 'failed to unpack release archive: %s\n' "$archive_path" >&2
    exit 1
  fi
  package_name="$(basename "$package_dir")"

  run_privileged mkdir -p "$PREFIX/releases" "$BIN_DIR"
  run_privileged rm -rf "$PREFIX/releases/$package_name"
  run_privileged cp -a "$package_dir" "$PREFIX/releases/"
  run_privileged ln -sfn "$PREFIX/releases/$package_name" "$CURRENT_DIR"
  run_privileged ln -sfn "$CURRENT_DIR/bin/loom" "$BINARY_PATH"
  rm -rf "$tmpdir"
  printf '==> Installed Meridian Loom release %s\n' "$package_name"
}

ensure_runtime_root() {
  local prepared_capabilities=0
  run_privileged mkdir -p "$RUNTIME_ROOT/capabilities"
  if [[ -z "$KERNEL_PATH" && -d /opt/meridian-kernel ]]; then
    KERNEL_PATH=/opt/meridian-kernel
  elif [[ -z "$KERNEL_PATH" && -d /tmp/meridian-kernel ]]; then
    KERNEL_PATH=/tmp/meridian-kernel
  fi

  if ! file_exists "$RUNTIME_ROOT/loom.toml"; then
    printf '==> Initializing runtime root at %s\n' "$RUNTIME_ROOT"
    if [[ -n "$KERNEL_PATH" ]]; then
      run_privileged "$BINARY_PATH" init --mode embedded --root "$RUNTIME_ROOT" --kernel-path "$KERNEL_PATH"
    else
      run_privileged "$BINARY_PATH" init --mode embedded --root "$RUNTIME_ROOT"
    fi
    RUNTIME_WAS_INITIALIZED=1
  else
    printf '==> Reusing existing runtime config at %s\n' "$RUNTIME_ROOT/loom.toml"
  fi

  if ! file_exists "$RUNTIME_ROOT/capabilities/registry.json"; then
    printf '==> Preparing built-in capabilities\n'
    run_privileged "$BINARY_PATH" capability list --root "$RUNTIME_ROOT" --format json >/dev/null
    prepared_capabilities=1
  fi

  ensure_python3
  seed_builtin_capabilities
  if [[ "$prepared_capabilities" -eq 1 ]]; then
    printf '==> Built-in capabilities ready\n'
  fi
}

run_onboard_if_interactive() {
  if [[ "${LOOM_SKIP_ONBOARD:-}" == "1" ]]; then
    return
  fi
  if [[ "$RUNTIME_WAS_INITIALIZED" -ne 1 && "${LOOM_RUN_ONBOARD:-}" != "1" ]]; then
    return
  fi
  if [[ ! -e /dev/tty || ! -r /dev/tty || ! -w /dev/tty ]]; then
    return
  fi
  if [[ ! -t 1 && ! -t 2 ]]; then
    return
  fi
  printf '==> Launching Meridian setup wizard\n'
  local onboard_args=(onboard --root "$RUNTIME_ROOT" --format human)
  if [[ -n "$KERNEL_PATH" ]]; then
    onboard_args+=(--kernel-path "$KERNEL_PATH")
  fi
  "$BINARY_PATH" "${onboard_args[@]}" </dev/tty >/dev/tty 2>/dev/tty
  ONBOARD_WAS_RUN=1
}

print_summary() {
  local doctor_step
  local new_agent_step
  local run_agent_step
  local path_hint
  local quickstart
  doctor_step="$BINARY_PATH doctor --root \"$RUNTIME_ROOT\" --format human"
  new_agent_step="$BINARY_PATH new-agent --name \"My Assistant\" --root \"$RUNTIME_ROOT\""
  run_agent_step="$BINARY_PATH run-agent my-assistant"
  quickstart="Quick start:
  1. Create an agent: $new_agent_step
  2. Run the loop:    $run_agent_step
  3. Inspect health:  $doctor_step"
  path_hint=""
  case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
      path_hint="path:     add $BIN_DIR to PATH to run 'loom' directly"
      ;;
  esac
  cat <<SUMMARY
==> Meridian install ready
source:   $INSTALL_SOURCE
binary:   $BINARY_PATH
runtime:  $RUNTIME_ROOT
message:  ✅ Loom v0.1.16 installed. Run loom new-agent to create your first governed agent.

$quickstart
$path_hint
SUMMARY
}

main() {
  local archive_path=""
  print_banner
  ensure_privileges
  if [[ "$INSTALL_MODE" != "source" ]]; then
    archive_path="$(download_prebuilt_release || true)"
    if [[ -n "$archive_path" ]]; then
      INSTALL_SOURCE="github-release"
      install_archive "$archive_path"
    elif [[ "$INSTALL_MODE" == "release" ]]; then
      printf 'no compatible Meridian Loom release asset was available for %s/%s\n' "$(normalize_os 2>/dev/null || echo unknown)" "$(normalize_arch 2>/dev/null || echo unknown)" >&2
      exit 1
    fi
  fi
  if [[ -z "$archive_path" ]]; then
    if ! repo_has_source_checkout; then
      printf 'no compatible Meridian Loom release asset was found, and this installer is not running inside a source checkout for source fallback\n' >&2
      exit 1
    fi
    if [[ "$INSTALL_MODE" == "auto" ]]; then
      printf '==> No compatible release asset was available; falling back to source build\n' >&2
    fi
    ensure_cargo
    archive_path="$(package_source_release)"
    INSTALL_SOURCE="source-fallback"
    install_archive "$archive_path"
  fi
  ensure_runtime_root
  run_onboard_if_interactive
  print_summary
}

main "$@"
