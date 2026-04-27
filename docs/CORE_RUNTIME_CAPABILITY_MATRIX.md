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
| Session history search | `core.sh session search QUERY` | shipped | Searches across stored session-history event text with snippets and session references |
| Session context resume | `core.sh session resume SESSION_KEY EVENT_INDEX [--queue|--context]` | shipped | Materializes one historical event into a reusable context note and can push it into file queue or persistent project context |
| Session context reuse | `core.sh session reuse QUERY [--queue|--context]` | shipped | Finds the newest matching historical event and rehydrates it directly into file queue or persistent project context |
| Persistent project context | `core.sh context *` / `ask --no-context` | shipped | Stores default context files that auto-attach to ask/chat unless explicitly bypassed |
| Playbook / runbook surface | `core.sh playbook *` | shipped | Saves recurring workflows as runnable Core playbooks, captures successful outputs, maps playbooks into scheduled routines, runs mapped playbook jobs, and can unschedule them cleanly |
| Last response inspect | `core.sh response *` | shipped | show/meta/path |
| Runtime doctor | `core.sh doctor *` | shipped | Aggregates doctor/health/provider/gateway/queue/memory/agent/channel with receipt/fix/summary surfaces |
| Provider plane inspect | `core.sh provider *` | shipped | status/profiles/auth/route/login |
| Effective config inspect | `core.sh config show` | shipped | Uses Loom config surface |
| Runtime status/logs | `core.sh runtime *` | shipped | status/health/logs |
| Channel cockpit | `core.sh channel *` | shipped | list/health/show/deliveries/send/test/diagnostics |
| Multi-channel health | `core.sh channel diagnostics` | shipped | Overview of all channels; per-channel diagnostics with `channel diagnostics CHANNEL [LIMIT]`; wired into doctor overview; API at `/api/channels/health` and `/api/channels/{id}/diagnostics` |
| Memory cockpit | `core.sh memory *` | shipped | overview/receipts/graph/status |
| Job cockpit | `core.sh job *` | shipped | list/inspect/approve |
| Queue cockpit | `core.sh queue *` | shipped | status/inspect/run-once/run-until-empty |
| Agent operator cockpit | `core.sh agent *` | shipped | inspect/diagnose/status/session/context/memory |
| Capability growth loop | `core.sh cap *` | shipped | delegates to `skill.sh` |
| Artifact-safe rendering | `core.sh ask` / `chat` | shipped | Long outputs auto-truncate with preview; `response page` for full paged view |
| Artifact export/materialization | `core.sh response export DIR` | shipped | Exports latest artifact into a real directory tree when output includes file sections |
| Attachment/file flow | `core.sh ask --file` / `chat /file` | shipped | Pass text files as context; multi-file, size-guarded, binary-rejected |
| Provider/model switching | `core.sh provider list/use` | shipped | `provider list` shows full plane; `provider use PROFILE --model M` switches; `ask --model M` for per-request; chat `/model` for sticky |
| Config editing flow | `core.sh config set/get` | shipped | Allowlisted keys only; backup on write; `config get` shows source |
| Session export | `core.sh session export ID DIR` | shipped | Exports session JSON + Markdown transcript |
| Session archive lifecycle | `core.sh session archive` | shipped | Dry-run default; `--older-than DAYS --execute` for cleanup |
| Gateway model override | `/api/run` `model` field | shipped | Per-request model override via JSON payload; env restored after |
| Channel pairing/admin flow | `core.sh channel connect *` | shipped | scaffold/list/validate/enable/disable/test/health/diagnostics/scorecard surfaced in Core |
| Scheduling daily automation | `core.sh schedule *` / `schedules` | shipped | status/list/show/every/daily/pause/cancel/run/run-due exposed in Core |
| Web/dashboard bridge | `core.sh web *` | shipped | urls/status expose local gateway, workspace, peer workspace, and public web surfaces |
| Live proof coverage | `core.sh proof *` | shipped | local proof runner now acts as a real gate: structured receipt, failed-check detection, isolated provider restore/mutation proof, and summary/path/show surfaces |

## Priority order

### P1

- ~~artifact-safe rendering for long code/app outputs~~ shipped
- ~~attachment/file flow for `ask` and `chat`~~ shipped
- ~~safer higher-level provider/model switching flow~~ shipped

### P2

- ~~config editing helpers with guardrails~~ shipped
- ~~session export/archive~~ shipped
- ~~richer scheduling/routine UX~~ shipped

### P3

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

### Completed: Tranche 4 — provider/model switching, config editing, session lifecycle

- `core.sh provider list` — full provider plane table: active route, fallback chain, registry, effective manager execution
- `core.sh provider use PROFILE --model M` — switch active provider/model via institution policy with auto-backup
- `core.sh ask --model M` — per-request model override passed to gateway
- Gateway `/api/run` accepts optional `model` field for per-request override (env restored after)
- Chat `/model MODEL` — sticky model override for the chat session; `/model` clears
- Chat `/provider` — show status; `/provider use PROFILE` — persistent switch
- `core.sh config set KEY VALUE` — safe config editing with allowlisted keys + backup
- `core.sh config get KEY` — shows value and source (overrides.env vs environment)
- `core.sh session archive` — dry-run by default; `--older-than DAYS --execute` for cleanup
- Session archive preserves current session, moves old event files to archive directory

### Completed: Tranche 5 — scheduling and routine cockpit

- `core.sh schedule status` — schedule runtime overview with total/enabled/due counts
- `core.sh schedule list` / `schedules` — list scheduled jobs with next fire time
- `core.sh schedule show JOB_ID` — show full schedule details
- `core.sh schedule every NAME SECONDS` — create an interval routine
- `core.sh schedule daily NAME HH:MM [TZ]` — create a daily routine in Core-native form
- `core.sh schedule pause JOB_ID` — pause a routine
- `core.sh schedule cancel JOB_ID` — cancel a routine
- `core.sh schedule run JOB_ID` — execute one routine immediately
- `core.sh schedule run-due [LIMIT]` — flush due routines now from Core

### Completed: Tranche 6 — channel pairing and adapter admin cockpit

- `core.sh channel connect list` — list connect adapters from the runtime registry
- `core.sh channel connect scaffold NAME TRANSPORT [ACTION_SCHEMA]` — scaffold a governed adapter manifest from Core
- `core.sh channel connect validate/enable/disable/test/health ADAPTER_ID` — operate one adapter from Core
- `core.sh channel connect diagnostics ADAPTER_ID [LIMIT]` — inspect adapter diagnostics
- `core.sh channel connect scorecard` — view multi-adapter scorecard in Core

### Completed: Tranche 7 — web/operator bridge

- `core.sh web urls` — show local gateway/workspace URLs plus public website/pilot/demo surfaces
- `core.sh web status` — probe gateway/workspace/peer-workspace web health from Core

### Completed: Tranche 8 — bounded shell presets and destructive guardrails

- `core.sh shell list` — show safe daily shell presets
- `core.sh shell run PRESET` — run bounded daily presets (`repo-status`, `repo-diff`, `repo-log`, `runtime-events`, `open-ports`, `schedule-list`)
- `core.sh research "cmd [args]"` — now limited to read-only command families
- git research is restricted to read-only subcommands
- curl research rejects mutating flags (`-X`, `--data`, `--form`, upload flags)

### Completed: Tranche 9 — browser restrictions and host allowlists

- `core.sh browse URL` — now restricted to `http`/`https`
- `MERIDIAN_CORE_BROWSE_ALLOWED_HOSTS` — optional host allowlist for Core browse
- `core.sh web browse-policy` — inspect current browse restrictions from Core

### Completed: Tranche 10 — Core live-proof surface

- `core.sh proof local` — run the local Core live-proof suite from the cockpit itself
- `core.sh proof show|path|summary` — inspect the last proof receipt directly from Core
- proof receipt includes `summary`, `details`, and raw `sections`
- live proof now covers isolated provider mutation and config mutation paths without touching the live runtime roots

### Completed: Tranche 11 — doctor remediation receipts

- `core.sh doctor` now captures a doctor receipt at the Core layer
- `core.sh doctor show|path|summary` expose that receipt directly from Core
- `core.sh doctor fix` applies safe doctor remediations, captures before/after check summaries, and records service remediation attempts

### Completed: Tranche 12 — proof hardening and restore-path coverage

- `core.sh proof local` now writes `failed_checks` and computes `status` from actual summary booleans instead of hardcoded pass
- proof now covers isolated `provider restore` from Meridian-owned `.env/.env.gateway` topology
- `core.sh web status` now degrades honestly under sandbox limits using pid-file signals instead of reporting false `down`

### Next execution target
