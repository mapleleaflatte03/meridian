# {{NAME}}

This folder was created by `loom new-agent`.

It is the operator-facing home for one governed personal agent on Loom:

- `agent.toml` stores the runtime and channel configuration
- `SOUL.md` stores the behavioral contract for the agent
- `MEMORY.md` stores durable operator facts and preferences

## Start the agent

```bash
loom run-agent {{SLUG}}
```

If you want operator-driven restarts after exits, set the supervision policy in
`agent.toml` and reconcile the loop when needed:

```bash
loom run-agent reconcile {{SLUG}}
```

## Inspect proof and runtime state

```bash
loom run-agent inspect {{SLUG}}
loom run-agent diagnose {{SLUG}}
loom run-agent watch {{SLUG}} --once
loom status --root "{{LOOM_ROOT}}"
loom agent runtime --root "{{LOOM_ROOT}}" --agent-id "{{AGENT_ID}}"
loom channel health --root "{{LOOM_ROOT}}" --agent {{SLUG}} --history-limit 5 --diagnostic-limit 5
loom channel deliveries --root "{{LOOM_ROOT}}" --include-archived
loom memory receipts --root "{{LOOM_ROOT}}" --agent-id "{{AGENT_ID}}" --limit 10
loom memory search --root "{{LOOM_ROOT}}" --agent-id "{{AGENT_ID}}" --category profile
```

## What Loom already wired for you

- Kernel agent registration under `{{ORG_ID}}`
- local runtime profile under `{{LOOM_ROOT}}`
- heartbeat schedule for governed recurring execution
- memory receipts for profile and recall activity
- optional Telegram/webhook delivery targets from your creation flags
- a supervision policy block for manual or always-restart operation

Useful operator signals:

- `healthy`: supervisor and worker are both running
- `waiting_backoff`: Loom is waiting before a restart
- `manual_restart_required`: the loop exited and needs `loom run-agent reconcile {{SLUG}}`
- `channel health` includes recent transitions and recent test diagnostics for the agent's channels

Edit `SOUL.md`, `MEMORY.md`, and `agent.toml`, then restart the agent loop if you change runtime behavior.
