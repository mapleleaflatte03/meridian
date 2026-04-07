# Install

Meridian Loom should be installed as a real local runtime package, not as an
ad-hoc repo script pile.

Preferred install order:

1. release installer
2. Docker
3. prebuilt tarball
4. source build

## Release installer

```bash
curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian-loom/main/scripts/install.sh | bash
```

The installer prefers a matching GitHub release asset for the current host and only falls back to a source build when no compatible asset exists and the installer is running inside a source checkout.

## Docker

```bash
docker build -t meridian-loom:local .
export MERIDIAN_KERNEL_PATH=/opt/meridian-kernel
export LOOM_SERVICE_TOKEN=loom-local-token
mkdir -p "$PWD/runtime"
docker run --rm \
  -p 127.0.0.1:18910:18910 \
  -e LOOM_ROOT=/var/lib/loom/runtime/default \
  -e LOOM_SERVICE_TOKEN="$LOOM_SERVICE_TOKEN" \
  -e LOOM_ORG_ID=local_foundry \
  -e MERIDIAN_RUNTIME_AUDIT_FILE=/var/lib/loom/runtime/default/artifacts/audit/loom_runtime_events.jsonl \
  -v "$PWD/runtime:/var/lib/loom" \
  -v "$MERIDIAN_KERNEL_PATH:/kernel:ro" \
  --entrypoint /bin/sh \
  meridian-loom:local \
  -lc 'loom init --mode embedded --root "$LOOM_ROOT" --kernel-path /kernel --org-id "$LOOM_ORG_ID" && exec loom start --foreground --root "$LOOM_ROOT" --kernel-path /kernel --http-address 0.0.0.0:18910 --service-token "$LOOM_SERVICE_TOKEN"'
```

This starts Loom with:

- runtime root at `/var/lib/loom/runtime/default`
- kernel mounted read-only at `/kernel`
- runtime audit redirected to `/var/lib/loom/runtime/default/artifacts/audit/loom_runtime_events.jsonl`
- HTTP control plane bound on `0.0.0.0:18910`
- image entrypoint `loom` and explicit shell wrapper for `init && start`
- supported environment variables:
  - `LOOM_ROOT`
  - `LOOM_SERVICE_TOKEN`
  - `LOOM_ORG_ID`
  - `MERIDIAN_RUNTIME_AUDIT_FILE`
- the mounted runtime directory must be writable by the container user

If your host has a compose plugin, `docker compose up --build` still works with
the checked-in [docker-compose.yml](/root/meridian-loom/docker-compose.yml). It
is optional, not required.

For automated verification without compose:

```bash
./scripts/acceptance_container_service.sh --kernel-path /opt/meridian-kernel
```

That script reuses `meridian-loom:acceptance` if it already exists and only
builds the image when missing. Use `--build-image always` if you need a fresh
image build. If host networking for containers is restricted, it falls back to
an in-container socket-based verification path and reports that transport
explicitly.

## Prebuilt tarball

Build a release archive locally:

```bash
./scripts/package_release.sh --kernel-path /opt/meridian-kernel
```

Install it:

```bash
./scripts/install_local.sh dist/meridian-loom-*.tar.gz
```

That creates:

- binary symlink at `~/.local/bin/loom`
- release payload under `~/.local/share/meridian-loom/releases/...`
- active release symlink at `~/.local/share/meridian-loom/current`
- runtime root at `~/.local/share/meridian-loom/runtime/default`
- config template at `~/.local/share/meridian-loom/runtime/default/loom.toml.example`
- active config at `~/.local/share/meridian-loom/runtime/default/loom.toml` if one was not present already

## Source build

```bash
cargo build --release --workspace --locked
```

Use the resulting binary:

```bash
./target/release/loom version
```

## First personal-agent flow

```bash
export LOOM_ROOT="$HOME/.local/share/meridian-loom/runtime/default"
export MERIDIAN_KERNEL_PATH=/opt/meridian-kernel
export MERIDIAN_ORG_ID="${MERIDIAN_ORG_ID:-local_foundry}"

cd /opt/meridian-kernel
python3 quickstart.py --init-only

loom new-agent \
  --name "My Assistant" \
  --root "$LOOM_ROOT" \
  --kernel-path "$MERIDIAN_KERNEL_PATH" \
  --org-id "$MERIDIAN_ORG_ID"

loom channel connect telegram \
  --agent my-assistant \
  --chat-id "123456789"

loom run-agent my-assistant
loom doctor --root "$LOOM_ROOT" --format human
loom run-agent inspect my-assistant
loom run-agent watch my-assistant --once
loom channel health --root "$LOOM_ROOT" --agent my-assistant --history-limit 5 --diagnostic-limit 5
loom memory receipts --root "$LOOM_ROOT" --limit 10
loom channel deliveries --root "$LOOM_ROOT" --include-archived
```

That is the official first-run loop for Loom v0.1.16.

If you want the loop to come back under operator control after an exit:

```bash
loom run-agent my-assistant --restart-policy always --restart-backoff-seconds 30
loom run-agent reconcile my-assistant
```

Operator semantics:

- `loom run-agent inspect` shows supervisor state, crash semantics, channel health history, recent diagnostics, deliveries, and memory receipts in one payload
- `loom run-agent diagnose` turns crash, backoff, missing-channel, and degraded-channel states into concrete remediation commands
- `loom run-agent watch` renders the same surface as a compact terminal dashboard
- `loom channel health` now shows recent transitions and recent channel-test diagnostics instead of only the current state

For the full end-to-end walkthrough, including memory and receipt inspection:

- [docs/QUICKSTART.md](QUICKSTART.md)

For maintainers validating a release from end to end:

```bash
./scripts/verify_release_local.sh --kernel-path /opt/meridian-kernel
```
