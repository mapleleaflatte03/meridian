# Meridian Repository Migration Map

This is the canonical redirect map after Meridian converged to a single monorepo.

## Canonical Repository

- https://github.com/mapleleaflatte03/meridian

All new development, docs updates, issues, PRs, and discussions must happen here.

## Archived Mirrors (Read-Only)

- https://github.com/mapleleaflatte03/meridian-loom
- https://github.com/mapleleaflatte03/meridian-kernel
- https://github.com/mapleleaflatte03/meridian-intelligence

These repositories are archived and retained only for historical reference and permalink stability.

## Module Path Mapping

- `meridian-loom` -> `meridian/loom`
- `meridian-kernel` -> `meridian/kernel`
- `meridian-intelligence` -> `meridian/intelligence`

## Canonical Entry Points (Use These Only)

- Issues: https://github.com/mapleleaflatte03/meridian/issues/new/choose
- Pull requests: https://github.com/mapleleaflatte03/meridian/pulls
- Discussions: https://github.com/mapleleaflatte03/meridian/discussions
- Security policy: https://github.com/mapleleaflatte03/meridian/security/policy
- Wiki/docs root: https://github.com/mapleleaflatte03/meridian

## Mirror Redirect Rules

1. Do not open new feature work in any mirror.
2. Any issue or PR opened in a mirror must be redirected to monorepo and closed.
3. Any mirror README, issue template, and PR template must point to the monorepo.
4. Mirror metadata must stay explicit: read-only, canonical source is monorepo.

## Operational Gate (Migration Complete)

- Mirrors archived on GitHub.
- Mirror About/homepage points to monorepo.
- Mirror issue templates disable blank issues and redirect to monorepo.
- Mirror PR templates redirect to module path in monorepo.
- Monorepo README links to this migration map.

If any item above drifts, treat migration as broken and restore before feature work.
