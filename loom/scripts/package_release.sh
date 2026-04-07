#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${OUTPUT_DIR:-${repo_root}/dist}"
kernel_path="${KERNEL_PATH:-/opt/meridian-kernel}"
build_target="${BUILD_TARGET:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      output_dir="$2"
      shift 2
      ;;
    --kernel-path)
      kernel_path="$2"
      shift 2
      ;;
    --version)
      version="$2"
      shift 2
      ;;
    --target)
      build_target="$2"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

version="${version:-$(git -C "$repo_root" describe --tags --always --dirty 2>/dev/null || date -u +%Y%m%d-%H%M%S)}"
arch="$(uname -m)"
os="$(uname -s | tr '[:upper:]' '[:lower:]')"
binary_path="$repo_root/target/release/loom"
if [[ -n "$build_target" ]]; then
  case "$build_target" in
    x86_64-unknown-linux-musl|x86_64-unknown-linux-gnu)
      os="linux"
      arch="x86_64"
      ;;
    aarch64-unknown-linux-musl|aarch64-unknown-linux-gnu)
      os="linux"
      arch="aarch64"
      ;;
    x86_64-apple-darwin)
      os="darwin"
      arch="x86_64"
      ;;
    aarch64-apple-darwin)
      os="darwin"
      arch="aarch64"
      ;;
  esac
  binary_path="$repo_root/target/${build_target}/release/loom"
fi
package_name="meridian-loom-${version}-${os}-${arch}"
staging_dir="${output_dir}/${package_name}"
tarball="${output_dir}/${package_name}.tar.gz"

mkdir -p "$output_dir" "$staging_dir/bin" "$staging_dir/config" "$staging_dir/docs" "$staging_dir/docs/assets" "$staging_dir/scripts" "$staging_dir/deploy/systemd" "$staging_dir/templates"

(
  cd "$repo_root"
  if [[ -n "$build_target" ]]; then
    cargo build --release --workspace --locked --target "$build_target"
  else
    cargo build --release --workspace --locked
  fi
)

install -m 0755 "$binary_path" "$staging_dir/bin/loom"
install -m 0644 "$repo_root/loom.toml.example" "$staging_dir/config/loom.toml.example"

for doc in INSTALL.md QUICKSTART.md RUN_LOCAL.md SERVICE.md CONFIG.md OPERATIONS.md RELEASE.md ARCHITECTURE.md BENCHMARKS.md; do
  install -m 0644 "$repo_root/docs/$doc" "$staging_dir/docs/$doc"
done
cp -a "$repo_root/docs/assets/." "$staging_dir/docs/assets/"
cp -a "$repo_root/templates/." "$staging_dir/templates/"

install -m 0644 "$repo_root/README.md" "$staging_dir/README.md"
install -m 0755 "$repo_root/scripts/install.sh" "$staging_dir/scripts/install.sh"
install -m 0755 "$repo_root/scripts/install_local.sh" "$staging_dir/scripts/install_local.sh"
install -m 0755 "$repo_root/scripts/release_local.sh" "$staging_dir/scripts/release_local.sh"
install -m 0755 "$repo_root/scripts/package_release.sh" "$staging_dir/scripts/package_release.sh"
install -m 0755 "$repo_root/scripts/bench_runtime.py" "$staging_dir/scripts/bench_runtime.py"
install -m 0755 "$repo_root/scripts/acceptance_local_service.sh" "$staging_dir/scripts/acceptance_local_service.sh"
install -m 0755 "$repo_root/scripts/acceptance_container_service.sh" "$staging_dir/scripts/acceptance_container_service.sh"
install -m 0755 "$repo_root/scripts/verify_release_local.sh" "$staging_dir/scripts/verify_release_local.sh"
install -m 0644 "$repo_root/deploy/systemd/loom.service" "$staging_dir/deploy/systemd/loom.service"
install -m 0644 "$repo_root/deploy/systemd/loom-user.service" "$staging_dir/deploy/systemd/loom-user.service"
install -m 0644 "$repo_root/Dockerfile" "$staging_dir/Dockerfile"
install -m 0644 "$repo_root/docker-compose.yml" "$staging_dir/docker-compose.yml"
install -m 0644 "$repo_root/Makefile" "$staging_dir/Makefile"

cat > "$staging_dir/manifest.txt" <<EOF
package=${package_name}
version=${version}
os=${os}
arch=${arch}
kernel_path_hint=${kernel_path}
build_target=${build_target:-native}
truth=official v0.1 local runtime package; hosted replacement not claimed
layout=bin/loom config/loom.toml.example docs/ docs/assets/ templates/ scripts/ deploy/systemd/ Dockerfile docker-compose.yml Makefile
EOF

(
  cd "$output_dir"
  tar -czf "${package_name}.tar.gz" "${package_name}"
)

if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$tarball" > "${tarball}.sha256"
elif command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$tarball" > "${tarball}.sha256"
fi

printf '%s\n' "$tarball"
