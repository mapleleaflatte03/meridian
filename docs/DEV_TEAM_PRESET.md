# Dev Team Preset

Meridian now ships with a default 7-agent software-delivery team preset for Team mode.

## Default Dev Team

| Default handle | Default role | Internal task kind | Kernel role | Dispatchable |
| --- | --- | --- | --- | --- |
| Manager | `manager_tech_lead` | `manage` | `manager` | no |
| Architect | `architect` | `research` | `analyst` | yes |
| Backend | `backend_engineer` | `execute` | `executor` | yes |
| Frontend | `frontend_engineer` | `execute` | `executor` | yes |
| Platform | `platform_engineer` | `execute` | `executor` | yes |
| QA | `qa_reliability_engineer` | `qa_gate` | `qa_gate` | yes |
| Security | `security_reviewer` | `verify` | `verifier` | yes |

These are public-safe default handles, not the user's required identity. End users are expected to rename the team locally during onboarding or through `~/.meridian/.env`.

The internal task kind and kernel role remain stable runtime primitives. The user-facing team semantics now describe a real software-delivery team.

## Supported End-User Role Customization

Use `~/.meridian/team.json` for role, purpose, task-kind, scope, and budget overrides.

Example:

```json
{
  "preset": "dev_team",
  "specialists": {
    "FORGE": {
      "role": "platform_engineer",
      "purpose": "Owns release automation and platform rollout.",
      "task_kind": "execute",
      "kernel_role": "executor",
      "scopes": ["execute", "deploy", "observe"],
      "budget": {
        "max_per_run_usd": 0.9,
        "max_per_day_usd": 9.0,
        "max_per_month_usd": 90.0
      },
      "aliases": ["release engineer"]
    }
  }
}
```

Then restart through the supported runtime path:

```bash
./scripts/dev-up.sh
```

The runtime sync layer regenerates derived files from the user-local config. Do not edit generated runtime files directly.

## Backward Compatibility

- Existing installs can keep legacy generic semantics with `MERIDIAN_TEAM_PRESET=generic_team`.
- Existing name/provider/model overrides in `~/.meridian/.env` and `~/.meridian/.env.gateway` still work.
- `~/.meridian/team.json` overrides preset semantics without replacing provider/model config.
