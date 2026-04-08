# Mirror Archive Status

This file records the current archive/redirect state of legacy Meridian repositories.

## Canonical Source

- `mapleleaflatte03/meridian` (monorepo)

## Legacy Mirrors

| Mirror repo | Archived | Canonical module path | Redirect state |
|---|---:|---|---|
| `mapleleaflatte03/meridian-loom` | yes | `meridian/loom` | issue + PR templates redirect |
| `mapleleaflatte03/meridian-kernel` | yes | `meridian/kernel` | issue + PR templates redirect |
| `mapleleaflatte03/meridian-intelligence` | yes | `meridian/intelligence` | issue + PR templates redirect |

## Redirect Policy

1. Mirrors are read-only and sync-only.
2. New issues/PRs/discussions must be opened in monorepo.
3. Security reports follow monorepo security policy.

Canonical links:

- Issues: https://github.com/mapleleaflatte03/meridian/issues/new/choose
- PRs: https://github.com/mapleleaflatte03/meridian/pulls
- Discussions: https://github.com/mapleleaflatte03/meridian/discussions
- Security: https://github.com/mapleleaflatte03/meridian/security/policy

## Verification Command

```bash
./scripts/check_mirror_archive_policy.sh
```
