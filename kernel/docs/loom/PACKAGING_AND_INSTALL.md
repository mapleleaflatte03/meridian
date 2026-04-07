<p align="center">
  <img src="../assets/meridian_lockup_flat.svg" alt="Meridian" width="720">
</p>

<p align="center">
  Truthful install and distribution story for Loom as a first-party runtime that is already installable before every future claim is mature.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/install-source%20first-0c1117?style=flat-square" alt="Source first">
  <img src="https://img.shields.io/badge/repo-first--party%20runtime-0f766e?style=flat-square" alt="First-party runtime">
  <img src="https://img.shields.io/badge/runtime-bounded%20truth-8b0000?style=flat-square" alt="Bounded runtime truth">
</p>

<p align="center">
  <a href="../LOOM_SPEC.md">Loom Spec</a> ·
  <a href="CLI_AND_MODES.md">CLI and Modes</a> ·
  <a href="SHADOW_PREREQUISITES.md">Shadow Prerequisites</a> ·
  <a href="https://github.com/mapleleaflatte03/meridian-loom">Loom Repo</a>
</p>

# Meridian Loom // Packaging and Installation Strategy

**Status:** Design document plus official first-party runtime packaging story

## Build Requirements

| Component | Toolchain | Notes |
|-----------|-----------|-------|
| Rust supervisor | `cargo build --release` | Minimum Rust edition: 2021 |
| Python workers | Standard CPython 3.10+ | No exotic dependencies planned |
| TypeScript workers | Node 18+ / Bun | Channel adapter code |
| WASM modules | `cargo build --target wasm32-wasi` | Sandboxed capability modules |

## Distribution Formats

### 1. Source build (primary path during early phases)

```bash
git clone https://github.com/mapleleaflatte03/meridian-loom.git
cd meridian-loom
cargo build --release
```

Binary lands at `target/release/loom`. This is the expected path during
Phase 0–2 when the audience is the Meridian team and early contributors.

**Current truth:** a public Loom runtime already exists at
`https://github.com/mapleleaflatte03/meridian-loom` and builds in the founder
workspace. It is installable and testable as a governed local runtime surface,
but broader hosted/runtime claims remain bounded. The current runtime now exposes local surfaces for all
seven contract areas. `loom action execute` materializes a fail-closed runtime
receipt, a runtime-side audit artifact, and a parity stream. Loom can
also capture a live legacy runtime proof snapshot on the founder host. `loom service`
now exposes a local service shell with truthful file-backed ingress fallback,
and it can optionally bind a tokenized local HTTP control plane for
`GET /status`, `POST /submit`, and `POST /stop` when the host permits local
binding. `loom service import-commitments` can import sender-side
`execution_request` delivery refs from a commitments snapshot into the local
queue. These are runtime-local proof surfaces, not proof of every governed hosted
deployment mode. Hosted and broad deployment claims remain intentionally bounded.

### 2. Pre-built binary (Phase 3+)

When the ABI stabilizes, publish platform binaries:

| Platform | Format |
|----------|--------|
| Linux x86_64 | Tarball, `.deb`, `.rpm` |
| macOS arm64 | Tarball, Homebrew tap |
| macOS x86_64 | Tarball |
| Docker | `ghcr.io/<org>/meridian-loom:<tag>` |

No Windows target planned initially. Docker covers cross-platform needs
during early adoption.

### 3. Docker image

```dockerfile
FROM rust:1-slim AS build
WORKDIR /src
COPY . .
RUN cargo build --release

FROM debian:bookworm-slim
COPY --from=build /src/target/release/loom /usr/local/bin/loom
COPY loom.toml /etc/loom/loom.toml
ENTRYPOINT ["loom"]
CMD ["start"]
```

The Docker image bundles only the Rust supervisor binary and default config.
Workers (Python, TypeScript) are mounted or installed as additional layers
depending on the deployment.

### 4. Cargo install (convenience)

```bash
cargo install meridian-loom
```

Published to crates.io once the CLI surface stabilizes (Phase 3+).

## Configuration

All runtime config lives in `loom.toml`:

```toml
[runtime]
mode = "standalone"          # or "shadow", "embedded"
kernel_path = "/path/to/meridian-kernel"

[governance]
contract_bridge = true       # Enable 7-hook bridge to kernel
kernel_url = ""              # For remote kernel mode (future)

[transport]
telegram = false
mcp = false
http = true

[workers]
python_path = "workers/python"
typescript_path = "workers/typescript"
wasm_dir = "workers/wasm"

[scheduler]
cron_enabled = false
```

The config file is the single source of truth for what Loom does at startup.
No implicit behavior — if a transport isn't enabled in config, it isn't loaded.

## Kernel Dependency at Install Time

Loom does **not** bundle the kernel. The kernel is a separate install:

```bash
# Get kernel (pure Python, stdlib-only — no pip install needed)
git clone https://github.com/mapleleaflatte03/meridian-kernel.git

# Install Loom (Rust)
git clone https://github.com/mapleleaflatte03/meridian-loom.git
cd meridian-loom && cargo build --release

# Point Loom at kernel during init
./target/release/loom init --mode embedded --kernel-path /path/to/meridian-kernel --root /tmp/loom-rehearsal
```

In **embedded mode** (see `CLI_AND_MODES.md`), Loom is expected to ship a
vendored copy of the kernel's governance checks as a compiled library. The
current runtime does not implement that bundling yet. The canonical install
path still keeps kernel and Loom separate.

## Versioning

Loom versions independently from the kernel. The seven-hook contract
defined in `kernel/runtimes.json` is the compatibility anchor — it does
not carry its own version number today. Compatibility is expressed as
the count of proven hooks:

```
Loom 0.1.x — first-party runtime packaging, local proof receipts, and bounded runtime claims
Loom 0.2.0 — deeper personal-agent/runtime proof and broader delivery surfaces
```

Loom's version number does not imply kernel version compatibility beyond
the current contract definition and proof surfaces it has actually shipped.

## Maturity Gates

Loom follows a graduated maturity model. Each gate requires proof, not
just elapsed time.

| Gate | Requirement | What it unlocks |
|------|-------------|-----------------|
| **Pre-alpha** (historical) | Spec exists, registry entry at 0/7, public scaffold builds | CLI/setup rehearsal only |
| **Runtime v0.1** (current) | Installable first-party runtime, local proof surfaces, bounded public claims | Loom as the product front door |
| **Alpha** | Personal-agent loop, channels, and memory feel solid under repeated local use | Evaluation by contributors |
| **Beta** | Broader hosted/runtime proof, shadow hardening, and richer delivery surfaces | Opt-in use alongside other runtime paths |
| **GA** | Durable hosted/runtime proof, stable packaging, and repeated clean runs across the declared surface | Production use, broader runtime replacement claims |

Contract compliance is already native 7/7 for `loom_native` in
`runtimes.json`. The remaining gates are about product maturity, hosted/runtime
breadth, and proof of the broader runtime claim surface.
