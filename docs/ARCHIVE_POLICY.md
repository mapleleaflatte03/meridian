# Meridian Archive Policy

**Canonical repository:** https://github.com/mapleleaflatte03/meridian

## Purpose

This document defines the archive policy for Meridian's legacy repositories after monorepo convergence.

## Archived Repositories

The following repositories are permanently archived (read-only) and exist only for historical reference and permalink stability:

| Repository | Status | Canonical path |
|---|:---:|---|
| `mapleleaflatte03/meridian-loom` | archived | `meridian/loom` |
| `mapleleaflatte03/meridian-kernel` | archived | `meridian/kernel` |
| `mapleleaflatte03/meridian-intelligence` | archived | `meridian/intelligence` |

## Policy Rules

1. **No new development in mirrors.** All code, docs, issues, and PRs go to the monorepo.
2. **No issues or PRs in mirrors.** Any issue/PR opened in a mirror must be redirected and closed.
3. **Redirect rule.** Mirror README, issue templates, and PR templates point to the monorepo.
4. **Archive is permanent.** Mirrors will not be unarchived.
5. **Homepage redirect.** Mirror `homepageUrl` on GitHub must point to the canonical monorepo URL.

## Compliance Check

Run the archive policy verification script:

```bash
./scripts/verify_archive_policy.sh
```

Expected output: 3 mirrors confirmed archived, homepage redirects verified.

## Archive Drift Protocol

If a mirror is found to be unarchived or its homepage is wrong:

1. Re-archive the mirror via GitHub repository settings.
2. Set the repository homepage URL to `https://github.com/mapleleaflatte03/meridian`.
3. Rerun `./scripts/verify_archive_policy.sh` to confirm compliance.
4. Document the incident in a commit message.

## Historical Reference

Full migration module map: [`docs/MIGRATION_MAP.md`](MIGRATION_MAP.md)
Legacy module source map: [`docs/REPO_MIGRATION_MAP.md`](REPO_MIGRATION_MAP.md)
Mirror archive status: [`docs/MIRROR_ARCHIVE_STATUS.md`](MIRROR_ARCHIVE_STATUS.md)
