# Dev Team Preset

Meridian now ships with a default 7-agent software-delivery team preset for Team mode.

## Default Dev Team

| Agent | Default role | Internal task kind | Kernel role | Dispatchable |
| --- | --- | --- | --- | --- |
| Leviathann | `manager_tech_lead` | `manage` | `manager` | no |
| Atlas | `architect` | `research` | `analyst` | yes |
| Forge | `backend_engineer` | `execute` | `executor` | yes |
| Quill | `frontend_engineer` | `execute` | `executor` | yes |
| Pulse | `platform_engineer` | `execute` | `executor` | yes |
| Aegis | `qa_reliability_engineer` | `qa_gate` | `qa_gate` | yes |
| Sentinel | `security_reviewer` | `verify` | `verifier` | yes |

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
