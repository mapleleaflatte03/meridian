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

### Tranche 5: remaining runtime ergonomics

Next:

- bounded shell presets for common daily tasks
- clearer browser restrictions and host allowlists
- safer destructive-action guardrails in Core mode
- richer scheduling/routine UX
- channel pairing/admin cockpit in Core

## Non-goals

- turning Core into Team
- hiding governance truth
- adding surface area that is not actually backed by runtime behavior
