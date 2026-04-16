# Meridian Capability Contributor Guide

Capabilities are the extension units of Meridian Core. Each capability is a
self-contained worker that can be scaffolded, registered, inspected, and run
through a public documented flow — no maintainer intervention required.

---

## The contributor flow

```
scaffold → implement → verify → promote → list → inspect → run
```

All steps happen through `./scripts/skill.sh`. No hidden steps, no manual
file surgery in undocumented directories.

---

## Step 1 — Scaffold a capability

```bash
./scripts/skill.sh scaffold my.cap.name.v1 \
  --kind python \
  --action execute \
  --description "What this capability does"
```

This creates two files:

| File | Purpose |
|------|---------|
| `runtime/default/capabilities/custom/my-cap-name-v1.json` | Loom manifest (auto-managed) |
| `runtime/default/workers/python/my-cap-name-v1.py` | Python worker (you edit this) |
| `runtime/default/capabilities/custom/skill.yaml` | Contributor metadata (you edit this) |

The manifest is in `promotion_state: candidate` until you verify and promote it.

---

## Step 2 — Implement the worker

Edit `runtime/default/workers/python/my-cap-name-v1.py`.

The scaffold generates a working template. Your job is to replace the body of
`main()` with real logic.

### Worker contract

The runtime calls your worker with:

```
python3 worker.py --input /path/to/request.json --output /path/to/result.json
```

**Input** (`--input`): JSON envelope with this shape:

```json
{
  "capability": { "name": "my.cap.name.v1", "worker_kind": "python", ... },
  "envelope": {
    "agent_id": "...",
    "org_id": "...",
    "action_type": "execute",
    "resource": "capability:my.cap.name.v1",
    "payload_json": "{\"my_field\": \"value\"}"
  }
}
```

Read your payload from `envelope["payload_json"]` (JSON string, parse it):

```python
# Standard pattern used in all Meridian workers
capability = payload_envelope.get("capability", {})
envelope = payload_envelope.get("envelope", {})
raw_payload = (
    payload_envelope.get("payload_json", "")
    or envelope.get("payload_json", "")
)
parsed = json.loads(raw_payload) if raw_payload else {}
```

**Output** (`--output`): Write a JSON result and also `print()` it to stdout:

```python
result = {
    "status": "completed",          # required: "completed" | "error"
    "capability_name": "my.cap.v1", # required
    "summary": "Brief result text", # required: shown in inspect/run output
    # ... your custom fields
}
with open(args.output, "w") as fh:
    json.dump(result, fh, indent=2)
    fh.write("\n")
print(json.dumps(result))
```

### Required metadata shape (skill.yaml)

Update `runtime/default/capabilities/custom/skill.yaml` with:

```yaml
id: "my.cap.name.v1"
name: "my.cap.name.v1"
version: "0.1.0"
description: "One sentence: what the capability does."

runtime:
  kind: "python"
  entrypoint: "workers/python/my-cap-name-v1.py"
  action_type: "execute"

inputs:
  - name: my_field
    type: string
    description: "The primary input"
    required: true

outputs:
  - name: summary
    type: string
    description: "Primary result text"
  - name: status
    type: string
    description: "completed | error"

permissions:
  # What host capabilities this uses:
  # network, filesystem, terminal, kv_memory, llm_inference
  - kv_memory

example_invocation:
  command: "./scripts/skill.sh run my.cap.name.v1 --payload '{\"my_field\": \"hello\"}'"
  expected_output: "status: completed, summary: ..."
```

---

## Step 3 — Verify

```bash
./scripts/skill.sh verify my.cap.name.v1 \
  --payload '{"my_field": "test_value"}'
```

This runs your capability once through the full Meridian runtime (including
PoGE proof receipts and parity checks). If it completes without crashing, it
is marked `verified`.

Verify does **not** check the semantic correctness of your output — that is
your responsibility. It confirms the worker process executes cleanly.

---

## Step 4 — Promote

```bash
./scripts/skill.sh promote my.cap.name.v1
```

Promotion registers the capability in the runtime registry. After this, it
appears in `skill.sh list` and can be run by anyone with access to the local
runtime root.

Promotion requires prior verification. A capability that is only scaffolded
(not verified) cannot be promoted.

---

## Discover, inspect, and run

```bash
# List all capabilities
./scripts/skill.sh list

# Inspect full metadata
./scripts/skill.sh inspect my.cap.name.v1

# Run with a payload
./scripts/skill.sh run my.cap.name.v1 --payload '{"my_field": "value"}'

# Also available from core.sh:
./scripts/core.sh cap list
./scripts/core.sh cap inspect my.cap.name.v1
./scripts/core.sh cap run my.cap.name.v1 --payload '{"my_field": "value"}'
```

---

## Example capability: core.url.fetch.v1

The `core.url.fetch.v1` capability was created using this exact flow. You can
inspect it as a reference:

```bash
./scripts/skill.sh inspect core.url.fetch.v1
./scripts/skill.sh run core.url.fetch.v1 \
  --payload '{"url": "https://example.com", "max_chars": 300}'
```

Source worker: `runtime/default/workers/python/core-url-fetch-v1.py`

---

## Capability metadata reference

| Field | Where | Required |
|-------|-------|----------|
| `id` / `name` | skill.yaml, manifest | Yes |
| `version` | skill.yaml | Yes |
| `description` | skill.yaml, scaffold `--description` | Yes |
| `runtime.kind` | manifest `worker_kind` | Yes |
| `runtime.entrypoint` | manifest `worker_entry` | Yes |
| `runtime.action_type` | manifest `action_type` | Yes |
| `inputs` | skill.yaml | Recommended |
| `outputs` | skill.yaml | Recommended |
| `permissions` | skill.yaml | Recommended |
| `example_invocation` | skill.yaml | Recommended |

---

## Capability kinds

| Kind | When to use |
|------|-------------|
| `python` | Any general-purpose capability; uses Python stdlib only unless you add deps |
| `wasm` | Sandboxed compute that must run inside Wasmtime (advanced) |

For Phase 1 contributors, `python` is the right choice.

---

## Where files live

```
meridian/
├── scripts/
│   ├── skill.sh              — Capability management CLI
│   └── core.sh               — Daily task runner (cap subcommand)
└── runtime/
    └── default/
        ├── capabilities/
        │   ├── custom/        — Scaffolded and promoted custom capabilities
        │   └── registry.json  — Auto-managed registry (do not edit manually)
        └── workers/
            └── python/        — Python worker scripts (you edit these)
```

---

## Contributing a capability to the repo

If you want to share a capability with other Meridian users:

1. Complete the scaffold → verify → promote flow locally.
2. Copy your worker file to `loom/capabilities/contrib/<your-cap-name>/worker.py`.
3. Copy your `skill.yaml` alongside it.
4. Open a pull request with a brief description of what the capability does.

The contrib directory is read by `loom capability import-workspace-skill`
(see `loom capability --help`).

---

*This guide covers Phase 2 capability creation. For runtime architecture details, see `intelligence/ARCHITECTURE.md`.*
