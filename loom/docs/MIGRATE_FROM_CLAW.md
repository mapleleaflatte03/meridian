# Migrate from Claw-family Runtimes to Loom

This guide is for operators moving from broad assistant runtimes into a
governed local runtime with receipts, authority checks, and treasury gates.

## Scope

What this migration lane does:

- bootstraps a Loom runtime root (`loom quickstart`)
- scaffolds adapter surfaces aligned to your source runtime profile
- enables adapters and emits test/health diagnostics
- writes governed connect scorecard artifacts

What it does not do:

- import external provider secrets automatically
- claim protocol-level compatibility with every third-party plugin
- bypass warrants, court checks, or treasury gates

## One-command migration bootstrap

```bash
./scripts/bootstrap_from_claw_profile.sh \
  --profile openclaw \
  --root "$HOME/.local/share/meridian-loom/runtime/migrate-openclaw" \
  --kernel-path /opt/meridian-kernel \
  --org-id migration_openclaw
```

Supported profiles:

- `openclaw`
- `openfang`
- `zeroclaw`

## Profile mapping

| Profile | Adapter set scaffolded |
| --- | --- |
| `openclaw` | `telegram`, `discord`, `whatsapp`, `slack`, `email`, `webhook`, `browser`, `shell` |
| `openfang` | `grpc`, `a2a`, `mcp`, `http` |
| `zeroclaw` | `telegram`, `discord`, `browser`, `shell`, `webhook`, `ros2` |

## Validate after bootstrap

```bash
loom connect list --root "$LOOM_ROOT" --format human
loom connect validate --root "$LOOM_ROOT" --format human
loom connect scorecard --root "$LOOM_ROOT" --format human
```

Artifacts to inspect:

- `state/connect/registry.json`
- `state/connect/health/<adapter-id>.json`
- `state/connect/tests/<adapter-id>.jsonl`
- `artifacts/connect/latest.json`

## Acceptance lane

Run the full migration lane for all three profiles:

```bash
make acceptance-migration-profile-lane
```

## Rollback

Migration is additive and scoped by runtime root. To rollback:

1. stop the service using that root
2. archive or remove that root directory
3. continue on the previous root without changing kernel governance state
