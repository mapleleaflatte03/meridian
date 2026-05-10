# Meridian Core Runtime Parity Plan

Canonical internal plan for turning Meridian Core into the default daily local agent runtime.

Companion matrix: [`docs/CORE_RUNTIME_CAPABILITY_MATRIX.md`](CORE_RUNTIME_CAPABILITY_MATRIX.md)

## Goal

Meridian Core must be able to replace a modern local agent runtime for daily work:

- prompt loop
- browser tasks
- terminal execution
- memory and recall
- channels and delivery
- job/session inspection
- scheduling and recurring work
- capability discovery and extension

Meridian Team remains the governed depth above that baseline.

## Capability pillars

### 1. Daily prompt loop

Core needs one obvious entrypoint for "just do the task now".

Target surface:

- `./scripts/core.sh ask "task"`
- session-aware request/response
- route visibility (`direct` vs deeper execution)
- output that stays readable in the terminal

### 2. Operator cockpit

Core needs live runtime introspection without forcing users into raw runtime commands.

Target surface:

- `./scripts/core.sh agent inspect`
- `./scripts/core.sh agent diagnose`
- `./scripts/core.sh channel health`
- `./scripts/core.sh job list`
- `./scripts/core.sh queue status`

### 3. Memory that can be inspected, not just written

Core memory cannot stop at key-value storage.

Target surface:

- `./scripts/core.sh memory overview`
- `./scripts/core.sh memory receipts`
- `./scripts/core.sh memory graph SOURCE_REF`

### 4. Channel-first runtime

Core should treat channels as first-class daily runtime surfaces.

Target surface:

- Telegram stable on main stack
- external channel ingress/outbound adapters
- delivery dedup
- channel health and diagnostics
- safe fallback when a channel is configured outside the runtime registry

### 5. Capability growth loop

Core needs a clean way to grow new runtime powers without rewriting product surfaces.

Target surface:

- capability discovery via `core.sh cap *`
- scaffold → verify → promote flow
- gap-driven capability forging

## Tranche status

### Tranche 1: surfaced runtime cockpit

Completed:

- added `core.sh ask`
- added `core.sh agent inspect|diagnose|status`
- added `core.sh job list|inspect|approve`
- added `core.sh channel list|health|show|deliveries|send|test`
- added `core.sh queue status|inspect|run-once|run-until-empty`
- added `core.sh memory overview|receipts|graph`
- updated README and migration guide to expose the new Core surface

### Tranche 2: session-native Core

In progress:

- stable session naming and resume flow in `core.sh ask`
- `core.sh session current|new|use|list|show|reset`
- `core.sh response show|meta|path` for inspectable last-result receipts
- `core.sh chat` for a terminal-native daily prompt loop on the active session
- `core.sh doctor` for one-shot runtime/provider/gateway/channel diagnostics
- `core.sh provider *` and `core.sh config show` for provider plane/operator visibility
- optional streaming mode for long responses
- cleaner terminal rendering for code/build artifacts

### Tranche 3: attachment and artifact handling

Completed:

- `core.sh ask --file PATH` and `-f` shorthand for file attachments
- multi-file support with size guards (512 KiB per file, 2 MiB total)
- binary file detection and rejection with clear warnings
- chat mode: `/file PATH` queues, `/files` lists, `/clear-files` resets
- gateway `/api/run` accepts `attachments` array in payload
- file content prepended to goal as `<file name="...">` context blocks
- artifact-safe rendering: auto-truncate long outputs with preview
- `core.sh response page` for paged full-output viewing via `$PAGER`
- configurable thresholds via `MERIDIAN_CORE_LONG_OUTPUT_CHARS` / `_LINES`

### Tranche 4: provider/model switching, config editing, session lifecycle

Completed:

- `core.sh provider list` — full provider plane table (active route, fallback chain, provider + model registries, effective manager execution)
- `core.sh provider use PROFILE --model M` — switch active provider/model via `institution_brain_policy.configure_policy()` with auto-backup of previous policy
- `core.sh ask --model M` — per-request model override passed through to gateway
- Gateway `/api/run` accepts optional `model` field — sets `MERIDIAN_BRAIN_MANAGER_MODEL` for the request, restores after
- Chat `/model MODEL` — sticky per-session model override; `/model` clears back to default
- Chat `/provider` — shows current provider status; `/provider use P` switches persistently
- `core.sh config set KEY VALUE` — safe config editing: allowlisted keys only, backup before write, creates `overrides.env`
- `core.sh config get KEY` — shows effective value and whether it came from overrides.env or environment
- `core.sh session archive` — dry-run by default lists old sessions; `--older-than DAYS --execute` moves event files to archive directory, prunes registry, preserves current session

### Tranche 5: scheduling and routine cockpit

Completed:

- `core.sh schedule status` — schedule runtime overview from Loom schedule plane
- `core.sh schedule list` / `schedules` — list scheduled jobs in a Core-readable table
- `core.sh schedule show JOB_ID` — inspect one routine in detail
- `core.sh schedule every NAME SECONDS` — create interval routines without dropping to raw Loom CLI
- `core.sh schedule daily NAME HH:MM [TZ]` — create daily routines from Core
- `core.sh schedule pause JOB_ID` / `cancel JOB_ID` — control routines from Core
- `core.sh schedule run JOB_ID` / `run-due [LIMIT]` — execute routines immediately from Core

### Tranche 6: channel pairing and adapter admin cockpit

Completed:

- `core.sh channel connect list` — list connect adapters without dropping to raw Loom CLI
- `core.sh channel connect scaffold NAME TRANSPORT [ACTION_SCHEMA]` — scaffold governed channel adapters from Core
- `core.sh channel connect validate|enable|disable|test|health ADAPTER_ID` — operate one adapter from Core
- `core.sh channel connect diagnostics ADAPTER_ID [LIMIT]` — inspect adapter diagnostics
- `core.sh channel connect scorecard` — inspect operator-level adapter scorecard

### Tranche 7: web/operator bridge

Completed:

- `core.sh web urls` — surface local gateway/workspace URLs and public website/pilot/demo surfaces from Core
- `core.sh web status` — probe gateway/workspace/peer-workspace health from Core

### Tranche 8: bounded shell presets and destructive guardrails

Completed:

- `core.sh shell list` — expose safe daily shell presets
- `core.sh shell run PRESET` — bounded daily shell surfaces for repo/runtime inspection
- `core.sh research "cmd [args]"` — restricted to read-only command families
- git research limited to read-only subcommands
- curl research blocks mutating request flags

### Tranche 9: browser restrictions and host allowlists

Completed:

- `core.sh browse URL` — restricted to `http`/`https`
- `MERIDIAN_CORE_BROWSE_ALLOWED_HOSTS` — optional browse host allowlist in Core
- `core.sh web browse-policy` — inspect active browse restrictions and allowlist

### Tranche 10: Core live-proof surface

Completed:

- `core.sh proof local` — expose the local Core live-proof suite as a first-class Core command
- `core.sh proof show|path|summary` — inspect the latest proof receipt from Core itself
- proof receipt now carries `summary` booleans plus operator `details`
- local proof now covers isolated provider/config mutation paths in temp runtime roots, not just read-only cockpit surfaces

### Tranche 11: remaining runtime ergonomics

Completed:

- `core.sh doctor` now writes a Core doctor receipt on each run
- `core.sh doctor show|path|summary` expose that receipt directly from the Core cockpit
- `core.sh doctor fix` performs safe doctor remediations and records before/after summaries plus service restart attempts

### Tranche 12: proof hardening and restore-path coverage

Completed:

- `core.sh proof local` is now a true gate: receipt `status` is derived from real summary booleans and carries `failed_checks`
- proof now covers isolated `provider restore` from Meridian-owned `.env/.env.gateway` topology in addition to generic provider mutation
- `core.sh web status` now reports honest sandbox-visible signals (`ok` or `pid-file`) instead of false `down` when local socket checks are blocked by the environment
- `core.sh session search QUERY` and chat `/search QUERY` expose search across stored session-history text with session references and snippets
- `core.sh session resume SESSION_KEY EVENT_INDEX [--queue]` and chat `/use-resume` bridge historical context back into live file context without manual copy/paste
- `core.sh session reuse QUERY [--queue]` and chat `/reuse QUERY` collapse search + resume + queue into one step for faster daily recovery of old context
- `core.sh context add/list/remove/clear` introduces persistent project context files that auto-attach to `ask`/chat, while `--no-context` gives one-turn escape hatches
- `session resume|reuse ... --context` turns recovered historical context into persistent project context instead of only a one-turn queue
- `core.sh playbook *` introduces saved runnable runbooks; `playbook capture` promotes successful outputs or recovered context into reusable Core workflows; `playbook every|daily|schedules|run-scheduled|unschedule` maps playbooks into Core-owned scheduled routines and cleans them back out safely

### Tranche 13: remaining runtime ergonomics

Next:

- further harden proof/noise quality and expand end-to-end proof depth where runtime-safe

## Non-goals

- turning Core into Team
- hiding governance truth
- adding surface area that is not actually backed by runtime behavior
