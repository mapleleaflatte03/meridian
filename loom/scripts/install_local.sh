#!/usr/bin/env bash
set -euo pipefail

archive="${1:-}"
prefix="${PREFIX:-$HOME/.local/share/meridian-loom}"
bin_dir="${BIN_DIR:-$HOME/.local/bin}"
runtime_root="${RUNTIME_ROOT:-}"

if [[ -z "${archive}" ]]; then
  echo "usage: $0 /path/to/meridian-loom-<version>-<os>-<arch>.tar.gz|/path/to/dist [--prefix PATH]" >&2
  exit 2
fi

shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix)
      prefix="$2"
      shift 2
      ;;
    --bin-dir)
      bin_dir="$2"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -d "$archive" ]]; then
  archive="$(find "$archive" -maxdepth 1 -name 'meridian-loom-*.tar.gz' -type f | sort | tail -n 1)"
fi

if [[ -z "$archive" || ! -f "$archive" ]]; then
  echo "missing archive: $archive" >&2
  exit 1
fi

if [[ -z "${runtime_root}" ]]; then
  runtime_root="$prefix/runtime/default"
fi

mkdir -p "$prefix" "$bin_dir"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
tar -xzf "$archive" -C "$tmpdir"
package_dir="$(find "$tmpdir" -mindepth 1 -maxdepth 1 -type d | head -n 1)"

release_dir="$prefix/current"
rm -rf "$release_dir"
mkdir -p "$prefix/releases"
cp -a "$package_dir" "$prefix/releases/"
package_name="$(basename "$package_dir")"
ln -sfn "$prefix/releases/$package_name" "$release_dir"
ln -sfn "$release_dir/bin/loom" "$bin_dir/loom"

mkdir -p "$runtime_root"
cp -f "$release_dir/config/loom.toml.example" "$runtime_root/loom.toml.example"
if [[ ! -f "$runtime_root/loom.toml" ]]; then
  cp -f "$release_dir/config/loom.toml.example" "$runtime_root/loom.toml"
fi

cat <<EOF
installed: $release_dir
binary:    $bin_dir/loom
runtime:   $runtime_root
config:    $runtime_root/loom.toml
example:   $runtime_root/loom.toml.example
next:      loom init --mode embedded --root "$runtime_root" --kernel-path /path/to/meridian-kernel
EOF
