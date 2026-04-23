# Core Runtime Capability Matrix

Canonical internal matrix for turning Meridian Core into the default daily local agent runtime.

This document tracks practical end-user runtime surfaces that must feel complete in Core mode.

## Baseline rule

Core must feel like one coherent product surface:

- daily prompt loop
- session continuity
- last-response inspectability
- runtime doctor and health visibility
- provider/config visibility
- channel and memory cockpit

Core should not require users to memorize low-level Loom subcommands for common daily work.

## Capability matrix

| Capability | Core surface | Current state | Notes |
| --- | --- | --- | --- |
| Daily ask entrypoint | `core.sh ask` | shipped | Uses live gateway `/api/run` |
| Interactive terminal loop | `core.sh chat` | shipped | Reuses the same active session |
| Session continuity | `core.sh session *` | shipped | new/use/current/list/show/reset |
| Last response inspect | `core.sh response *` | shipped | show/meta/path |
| Runtime doctor | `core.sh doctor` | shipped | Aggregates doctor/health/provider/gateway/queue/memory/agent/channel |
| Provider plane inspect | `core.sh provider *` | shipped | status/profiles/auth/route/login |
| Effective config inspect | `core.sh config show` | shipped | Uses Loom config surface |
| Runtime status/logs | `core.sh runtime *` | shipped | status/health/logs |
| Channel cockpit | `core.sh channel *` | shipped | list/health/show/deliveries/send/test |
| Memory cockpit | `core.sh memory *` | shipped | overview/receipts/graph/status |
| Job cockpit | `core.sh job *` | shipped | list/inspect/approve |
| Queue cockpit | `core.sh queue *` | shipped | status/inspect/run-once/run-until-empty |
| Agent operator cockpit | `core.sh agent *` | shipped | inspect/diagnose/status/session/context/memory |
| Capability growth loop | `core.sh cap *` | shipped | delegates to `skill.sh` |
| Artifact-safe rendering | `core.sh ask` / `chat` | shipped | Long outputs auto-truncate with preview; `response page` for full paged view |
| Artifact export/materialization | `core.sh response export DIR` | shipped | Exports latest artifact into a real directory tree when output includes file sections |
| Attachment/file flow | `core.sh ask --file` / `chat /file` | shipped | Pass text files as context; multi-file, size-guarded, binary-rejected |
| Provider/model switching | `core.sh provider *` | partial | inspect/login exists; higher-level switching UX still rough |
| Config editing flow | `core.sh config *` | gap | inspect exists; safe edit/set workflow still missing |
| Session export | `core.sh session export ID DIR` | shipped | Exports session JSON + Markdown transcript |
| Session archive lifecycle | `core.sh session *` | gap | export exists; archive/cleanup workflow not exposed |
| Channel pairing/admin flow | `core.sh channel *` | gap | delivery health exposed; pairing/admin UX not surfaced in Core |
| Scheduling daily automation | `core.sh schedule` / `schedules` | partial | simple recurring tasks exist; richer cron/routine UX still thin |
| Web/dashboard bridge | Core-facing | partial | live stack exists; Core docs could expose when to jump to web UI |

## Priority order

### P1

- ~~artifact-safe rendering for long code/app outputs~~ shipped
- ~~attachment/file flow for `ask` and `chat`~~ shipped
- safer higher-level provider/model switching flow

### P2

- config editing helpers with guardrails
- session export/archive
- richer scheduling/routine UX

### P3

- channel pairing/admin cockpit in Core
- stronger bridge between terminal Core and web operator surfaces

## Current tranche status

### Completed in this branch

- session-native ask flow
- interactive chat loop
- last-response receipt/output cockpit
- runtime doctor aggregation
- provider/config/runtime inspect surfaces

### Completed: Tranche 3 — attachment and artifact handling

- `core.sh ask --file PATH` passes file content as attachment context
- `core.sh ask -f a.py -f b.py "compare"` supports multi-file attach
- chat mode: `/file PATH` queues files, `/files` lists, `/clear-files` resets
- gateway `/api/run` accepts `attachments` array in payload
- artifact-safe rendering: long outputs auto-truncate with preview + file pointer
- `core.sh response page` pages through full long output via `$PAGER`
- binary/oversized files rejected with clear warnings
- per-file 512 KiB / total 2 MiB attachment limits

### Next execution target

- safer higher-level provider/model switching flow
- config editing helpers with guardrails
- session archive/cleanup lifecycle
