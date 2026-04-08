# Meridian Migration Map

**Canonical repository:** https://github.com/mapleleaflatte03/meridian

## Legacy Repositories → Monorepo

Meridian has converged from three separate repositories to a single monorepo.

| Legacy repo | Archived | Canonical module path |
|---|:---:|---|
| `mapleleaflatte03/meridian-loom` | yes | `meridian/loom` |
| `mapleleaflatte03/meridian-kernel` | yes | `meridian/kernel` |
| `mapleleaflatte03/meridian-intelligence` | yes | `meridian/intelligence` |

Legacy repositories are read-only archives. All development happens in the monorepo.

## Contributor Redirect Map

| Legacy location | Redirect to |
|---|---|
| Issues in `meridian-loom` | https://github.com/mapleleaflatte03/meridian/issues/new/choose |
| Issues in `meridian-kernel` | https://github.com/mapleleaflatte03/meridian/issues/new/choose |
| Issues in `meridian-intelligence` | https://github.com/mapleleaflatte03/meridian/issues/new/choose |
| PRs in any mirror | Open against `mapleleaflatte03/meridian` at the corresponding `loom/`, `kernel/`, `intelligence/` path |
| Discussions in any mirror | https://github.com/mapleleaflatte03/meridian/discussions |
| Wiki in any mirror | https://github.com/mapleleaflatte03/meridian (monorepo docs) |

## Canonical Entry Points

- Issues: https://github.com/mapleleaflatte03/meridian/issues/new/choose
- Pull requests: https://github.com/mapleleaflatte03/meridian/pulls
- Discussions: https://github.com/mapleleaflatte03/meridian/discussions
- Security: https://github.com/mapleleaflatte03/meridian/security/policy
- Contributing: https://github.com/mapleleaflatte03/meridian/blob/main/CONTRIBUTING.md
- Roadmap: https://github.com/mapleleaflatte03/meridian/blob/main/ROADMAP.md

## Archive Policy

See [`docs/ARCHIVE_POLICY.md`](ARCHIVE_POLICY.md) for full policy and verification commands.

## Verification

```bash
./scripts/verify_archive_policy.sh
```
