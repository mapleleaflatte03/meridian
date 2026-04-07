# Loom Benchmarks

Loom ships with a tiny benchmark harness for one thing only: answering the
newcomer question, "how fast does the binary start and how much memory does it
use for a cold command on this box?"

This benchmark is intentionally narrow:

- It measures short-lived CLI cold starts and peak RSS.
- It does not claim steady-state daemon memory.
- It does not claim end-to-end workflow superiority.
- It is only fair when every binary runs on the same host with the same shell
  and the same filesystem state.

## Included harness

Use the built-in script:

```bash
python3 scripts/bench_runtime.py \
  --iterations 5 \
  --warmup 1 \
  --case "loom status::./target/release/loom status --root /tmp/loom-bench-root" \
  --case "zeroclaw help::zeroclaw --help" \
  --case "openfang help::openfang --help" \
  --case "ironclaw::ironclaw --help" \
  --format markdown
```

The script reports:

- mean cold start time
- p95 cold start time
- worst observed peak RSS
- exit-code consistency

## Suggested baseline commands

These are the least misleading commands to benchmark first:

- `loom status --root <runtime-root>`
- `zeroclaw --help`
- `openfang --help`
- `ironclaw --help`

If your local install exposes a stronger status or doctor command, swap it in
and keep the comparison honest in your notes.

## Current reference run

Reference host:

- date: `2026-04-05`
- host: Meridian VPS, Ubuntu 22.04, x86_64
- Loom binary: local `target/debug/loom`
- ZeroClaw binary: optional Linux x86_64 release asset when available on host
- OpenFang binary: `v0.5.6` Linux x86_64 release asset
- IronClaw binary: `v0.24.0` Linux x86_64 release asset

Reference commands:

- `loom status --root /home/ubuntu/.local/share/meridian-loom/runtime/default`
- `zeroclaw --help`
- `openfang --help`
- `ironclaw --help`

Reference results:

| Case | Mean cold start (ms) | p95 (ms) | Peak RSS (MiB) |
| --- | ---: | ---: | ---: |
| `loom status` | 29.8 | 33.9 | 4.8 |
| `zeroclaw --help` | n/a (binary not installed on reference host) | n/a | n/a |
| `openfang --help` | 28.5 | 30.8 | 2.8 |
| `ironclaw --help` | 32.6 | 33.9 | 5.1 |

Interpretation:

- Loom is already in the same cold-start band as OpenFang and IronClaw on this host.
- ZeroClaw is included in the harness so the same host can produce a direct row whenever that binary is installed.
- OpenFang wins this narrow help-surface memory/startup check.
- Loom stays ahead of IronClaw on the same narrow check while surfacing a richer governed status command.
- This is still not a workflow benchmark. It only answers the newcomer question: "does the binary feel fast enough to trust on first run?"

## Why this benchmark exists

OpenFang and IronClaw both make speed and operator experience part of their
story. Loom should not dodge that comparison. It should make the same comparison
reproducible on one machine, with one small script, and with a clear proof
boundary around what the numbers do and do not mean.
