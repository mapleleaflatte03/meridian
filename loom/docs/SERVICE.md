# Service

`loom service` is the local control plane underneath the top-level
`loom start|stop|restart|logs` wrappers.

## Lifecycle commands

Top-level wrappers:

- `loom start`
- `loom stop`
- `loom restart`
- `loom logs`
- `loom status`

Direct service commands:

- `loom service start`
- `loom service status`
- `loom service submit`
- `loom service import-commitments`
- `loom service stop`

## Process model

Loom currently supports:

- foreground service mode
- background single-node local service mode
- PID-backed runtime state
- service lock file
- idempotent stop
- graceful shutdown by stop request

It is still a local-first service, not a hosted multi-node scheduler.

## HTTP control plane

When `--http-address` is set, Loom exposes:

- `GET /status`
- `GET /health`
- `GET /metrics`
- `GET /config`
- `GET /jobs/<id>`
- `POST /submit`
- `POST /import-commitments`
- `POST /stop`

If `--service-token` is set, token auth is required on that surface.

## Queue seam

The local queue surface is separate from the HTTP service surface, but it is now real and operator-visible:

- `loom queue inspect` reads pending queue records without mutating them
- `loom queue consume` runs the local supervisor over pending queue records and writes filesystem ack receipts
- `loom queue run-once` performs one bounded consume pass and records a progress artifact
- `loom queue run-until-empty` repeats bounded passes until the queue drains or the pass cap is reached, then writes a journal and summary artifact
- `loom queue status` reports policy-class queue depth without mutating queue state
- `loom queue ack` records a terminal acknowledgement for an already completed, failed, denied, or cancelled job

Queue artifacts live under `<root>/state/runtime/queue/`:

- pending records: `<root>/state/runtime/queue/pending/<policy_class>/`
- ack receipts: `<root>/state/runtime/queue/acks/`
- run artifacts: `<root>/state/runtime/queue/runs/`

This queue seam is local-only. It does not imply hosted queue orchestration, cross-node delivery, or live transport cutover.

Container/runtime contract:

- image entrypoint: `loom`
- default command: `help`
- expected writable mount: `/var/lib/loom`
- expected kernel mount: `/kernel` (read-only)
- expected runtime audit path in container mode: `/var/lib/loom/runtime/default/artifacts/audit/loom_runtime_events.jsonl`
- common env vars:
  - `LOOM_ROOT`
  - `LOOM_SERVICE_TOKEN`
  - `LOOM_ORG_ID`
  - `MERIDIAN_RUNTIME_AUDIT_FILE`
- bind-mounted runtime roots must be writable by the container user

Auth/parser guarantees in the local HTTP surface:

- missing or malformed `Authorization` -> `401`
- malformed request line or invalid `Content-Length` -> `400`
- `POST /submit` and `POST /import-commitments` without `Content-Type: application/json` -> `415`
- invalid JSON body -> `400`
- `GET /health` returns `503` when the service is degraded or stale

## Ingress transport

Current ingress order:

1. Unix socket when bindable
2. tokenized local HTTP when enabled
3. file-backed ingress fallback when socket ingress is unavailable

`loom service status` reports the actual active transport. Submit receipts also
report the transport and target used.

## Runtime paths

Inside a runtime root:

- config: `<root>/loom.toml`
- service state: `<root>/run/service/runtime_state.json`
- service lock: `<root>/run/service/service.lock`
- metrics: `<root>/run/service/metrics.json`
- stop request: `<root>/run/service/stop.requested`
- ingress stream: `<root>/run/ingress/stream.jsonl`
- ingress requests: `<root>/run/ingress/requests/`
- ingress receipts: `<root>/run/ingress/receipts/`
- service log: `<root>/logs/service.log`
- service events: `<root>/logs/service_events.jsonl`
- capability registry: `<root>/capabilities/registry.json`
- custom capability manifests: `<root>/capabilities/custom/`
- imported clawfamily skill wrappers: `<root>/workers/python/imported-*.py`
- capability verification/promotion state: persisted in each custom manifest under `<root>/capabilities/custom/`
- job ledger: `<root>/state/runtime/jobs/`
- scheduler state: `<root>/state/runtime/scheduler/`
- audit artifacts: `<root>/artifacts/audit/`
- parity artifacts: `<root>/artifacts/parity/`
- shadow artifacts: `<root>/artifacts/shadow/`

Logging retention is controlled by `log_max_bytes` and `log_max_files` in
`loom.toml`.

## Operator examples

```bash
loom start --root "$LOOM_ROOT" --kernel-path "$MERIDIAN_KERNEL_PATH" --http-address 127.0.0.1:18910 --service-token "$LOOM_SERVICE_TOKEN"
loom status --root "$LOOM_ROOT"
loom logs --root "$LOOM_ROOT" --lines 100
loom stop --root "$LOOM_ROOT"
```

Capability-backed submit:

```bash
loom service submit \
  --root "$LOOM_ROOT" \
  --kernel-path "$MERIDIAN_KERNEL_PATH" \
  --http-url http://127.0.0.1:18910 \
  --service-token "$LOOM_SERVICE_TOKEN" \
  --agent-id agent_atlas \
  --org-id org_b7d95bae \
  --capability loom.echo.v1 \
  --payload-json '{"message":"hello from service capability"}'
```

Imported workspace-skill submit:

```bash
loom capability import-workspace-skill \
  --root "$LOOM_ROOT" \
  --skill-root /root/.legacy-runtime/workspace/skills/malware-triage

loom service submit \
  --root "$LOOM_ROOT" \
  --kernel-path "$MERIDIAN_KERNEL_PATH" \
  --http-url http://127.0.0.1:18910 \
  --service-token "$LOOM_SERVICE_TOKEN" \
  --agent-id agent_tutorial \
  --org-id local_foundry \
  --capability clawskill.malware-triage.v0 \
  --payload-json '{"artifact_path":"/tmp/sample.exe","skip_container":true}'
```

The same capability runtime also supports Loom-forged candidates:

```bash
loom capability forge \
  --root "$LOOM_ROOT" \
  --gap-class artifact_triage \
  --goal "suspicious artifact triage"

loom capability gap show \
  --root "$LOOM_ROOT" \
  --gap-id <gap_id>
```

Use `loom capability verify` with `--expect-summary-contains` and
`--expect-result-field PATH=VALUE` when you want Loom to treat runtime success
as insufficient and verify the worker result shape before promotion.

Operator-facing rehearsals for this service boundary:

```bash
./scripts/acceptance_capability_service.sh
./scripts/migration_tools/rehearse_claw_skill_service.sh
./scripts/migration_tools/rehearse_claw_skill_multi_import.sh
./scripts/migration_tools/rehearse_legacy_plugin_import.sh
./scripts/migration_tools/rehearse_server_replacement.sh
```

The replacement rehearsal now uses an imported clawfamily skill, not
`loom.echo.v1`. The script proves:
- import into Loom capability contract
- verify and promote through Loom runtime
- service submit through Loom-owned ingress
- job inspect, result inspection, logs
- restart and resubmit through the same imported skill

It does not prove live cutover or legacy-runtime retirement.
