# Operations

This is the compact runbook for a local operator.

## Environment checks

Doctor:

```bash
loom doctor --root "$LOOM_ROOT" --format human
```

Use `doctor` for:

- config existence
- path layout
- worker paths
- kernel binding
- permissions and obvious missing files

Health:

```bash
loom health --root "$LOOM_ROOT" --format human
curl -sS -H "Authorization: Bearer ${LOOM_SERVICE_TOKEN}" http://127.0.0.1:18910/health
```

Use `health` for:

- workspace readiness
- service running/degraded state

Status:

```bash
loom status --root "$LOOM_ROOT"
curl -sS -H "Authorization: Bearer ${LOOM_SERVICE_TOKEN}" http://127.0.0.1:18910/status
curl -sS -H "Authorization: Bearer ${LOOM_SERVICE_TOKEN}" http://127.0.0.1:18910/metrics
```

Use `status` for:

- service process state
- transport in use
- queue depth
- last request and last job
- runtime paths

## Logs

```bash
loom logs --root "$LOOM_ROOT" --lines 100
loom logs --root "$LOOM_ROOT" --follow
```

Primary files:

- `<root>/logs/service.log`
- `<root>/logs/service_events.jsonl`

Retention knobs:

- `log_max_bytes`
- `log_max_files`

Service logs never print the raw HTTP bearer token. Config/status surfaces only
show the token environment variable name.

## Jobs and artifacts

Inspect jobs:

```bash
loom job list --root "$LOOM_ROOT" --format human
loom job inspect --root "$LOOM_ROOT" --job-id <job_id> --format human
curl -sS -H "Authorization: Bearer ${LOOM_SERVICE_TOKEN}" http://127.0.0.1:18910/jobs/<job_id>
```

Inspect proof surfaces:

```bash
loom parity report --root "$LOOM_ROOT"
loom shadow report --root "$LOOM_ROOT"
```

Rehearse the warrant-bound shadow lane and prepare zk settlement artifacts:

```bash
loom shadow run \
  --backend wasmtime \
  --root "$LOOM_ROOT" \
  --kernel-path "$MERIDIAN_KERNEL_PATH" \
  --agent-id agent_atlas \
  --org-id "$MERIDIAN_ORG_ID" \
  --action-type research \
  --resource system_info \
  --module builtin:system.info \
  --warrant-file ./shadow-warrant.json \
  --format human

loom job settle \
  --zk \
  --zk-backend sp1 \
  --root "$LOOM_ROOT" \
  --kernel-path "$MERIDIAN_KERNEL_PATH" \
  --actual-cost-usd 0.05 \
  --format human
```

Run semantic gRPC action transport (same governance/proof contract, different transport):

```bash
loom shadow run \
  --backend grpc_action \
  --root "$LOOM_ROOT" \
  --kernel-path "$MERIDIAN_KERNEL_PATH" \
  --agent-id agent_atlas \
  --org-id "$MERIDIAN_ORG_ID" \
  --action-type shadow_grpc_action \
  --resource external_grpc_action \
  --warrant-file ./shadow-warrant.json \
  --url 127.0.0.1:50051 \
  --grpc-service meridian.runtime.v1.ActionService \
  --grpc-method SubmitAction \
  --grpc-action-kind research.deliver \
  --grpc-action-objective "deliver governed runtime diff" \
  --grpc-context-json '{"lane":"trust_ops"}' \
  --grpc-constraints-json '{"max_latency_ms":12000}' \
  --grpc-memory-json '["mem://pattern/trust-ops-summary-v3"]' \
  --grpc-plaintext \
  --grpc-timeout-seconds 10 \
  --grpc-allow-unknown-fields \
  --format human
```

`grpc_action` notes:

- Requires `grpcurl` in `PATH`, or set `LOOM_SHADOW_GRPCURL_BIN=/path/to/grpcurl`.
- Optional transport flags:
  - `--grpc-authority`
  - repeated `--grpc-import-path`
  - repeated `--grpc-proto`
  - repeated `--grpc-protoset`
  - `--grpc-timeout-seconds` (1..120)
  - `--grpc-allow-unknown-fields`
  - `--grpc-plaintext` / `--grpc-tls`
- RPC formatting is strict: service + method must resolve to exactly one
  `<Service>/<Method>` segment pair.
- `shadow report` now prints typed gRPC diagnostics for the latest
  `grpc_action` run (target/rpc/transport/timeout/proto-protoset counts).
- The same diagnostics are persisted as typed artifacts at
  `artifacts/shadow/grpc_action/latest.json` (+ `stream.jsonl`) under the
  runtime root.
- `parity report` also renders this typed diagnostics block, so operator review
  can stay in one place.
- `loom shadow grpc-diagnostics --root "$LOOM_ROOT" --limit 20` renders the
  typed diagnostics stream/history directly.

Run embodied semantic physical transport (governed physical action schema over gRPC):

```bash
loom shadow run \
  --backend grpc_physical \
  --root "$LOOM_ROOT" \
  --kernel-path "$MERIDIAN_KERNEL_PATH" \
  --agent-id agent_atlas \
  --org-id "$MERIDIAN_ORG_ID" \
  --action-type shadow_grpc_physical \
  --resource external_grpc_physical \
  --warrant-file ./shadow-warrant.json \
  --url 127.0.0.1:50051 \
  --grpc-service meridian.embodied.action.v1.PhysicalActionService \
  --grpc-method Execute \
  --grpc-action-kind physical.move \
  --grpc-action-objective "move robot to staging point" \
  --physical-robot-id unitree.go2 \
  --physical-target warehouse.aisle-7 \
  --physical-command move_to_pose \
  --physical-safety-class restricted \
  --physical-dry-run \
  --grpc-physical-lifecycle stream \
  --grpc-physical-ack-required \
  --grpc-physical-ack-timeout-seconds 5 \
  --grpc-physical-cancel-on-ack-timeout \
  --grpc-plaintext \
  --grpc-timeout-seconds 10 \
  --format human
```

`grpc_physical` notes:

- Required fields:
  `--physical-robot-id`, `--physical-target`, `--physical-command`,
  `--physical-safety-class`.
- Payload schema is validated as `meridian.embodied.action.v1` before dispatch.
- Typed diagnostics include physical fields:
  `grpc_physical_robot_id`, `grpc_physical_target`,
  `grpc_physical_command`, `grpc_physical_safety_class`,
  `grpc_physical_dry_run`.
- Stream lifecycle controls are supported in the same lane:
  `--grpc-physical-lifecycle unary|stream`,
  `--grpc-physical-ack-required`,
  `--grpc-physical-ack-timeout-seconds`,
  `--grpc-physical-cancel-on-ack-timeout`,
  `--grpc-physical-cancel-after-seconds`.
- Typed diagnostics now include lifecycle state for operator audit:
  `grpc_lifecycle_mode`, `grpc_lifecycle_ack_required`,
  `grpc_lifecycle_ack_received`, `grpc_lifecycle_cancelled`,
  `grpc_lifecycle_cancel_reason`.
- Diagnostics are persisted in the same typed artifact stream used by
  `grpc_action` (`artifacts/shadow/grpc_action/latest.json` +
  `stream.jsonl`) so operator tooling can query one stream.

Run embodied A2A physical transport (same embodied governance surface with A2A HTTP transport):

```bash
loom shadow run \
  --backend a2a_physical \
  --root "$LOOM_ROOT" \
  --kernel-path "$MERIDIAN_KERNEL_PATH" \
  --agent-id agent_atlas \
  --org-id "$MERIDIAN_ORG_ID" \
  --action-type shadow_a2a_physical \
  --resource external_a2a_physical \
  --warrant-file ./shadow-warrant.json \
  --url http://127.0.0.1:8088/shadow-a2a-physical \
  --header "x-shadow-test: enabled" \
  --a2a-physical-method message/send \
  --a2a-physical-request-id shadow-a2a-physical-test \
  --a2a-physical-kind physical.move \
  --a2a-physical-objective "dispatch embodied lane" \
  --a2a-physical-skill atlas_motion \
  --physical-robot-id unitree.go2 \
  --physical-target warehouse.aisle-7 \
  --physical-command move_to_pose \
  --physical-safety-class restricted \
  --physical-dry-run \
  --grpc-context-json '{}' \
  --grpc-constraints-json '{}' \
  --grpc-memory-json '[]' \
  --format human
```

Run embodied ROS2 physical transport (same semantic governed payload, ROS2 execution bridge):

```bash
loom shadow run \
  --backend ros2_physical \
  --root "$LOOM_ROOT" \
  --kernel-path "$MERIDIAN_KERNEL_PATH" \
  --agent-id agent_atlas \
  --org-id "$MERIDIAN_ORG_ID" \
  --action-type shadow_ros2_physical \
  --resource external_ros2_physical \
  --warrant-file ./shadow-warrant.json \
  --ros2-service /meridian/physical_action/execute \
  --ros2-type meridian_embodied_msgs/srv/ExecutePhysicalAction \
  --ros2-timeout-seconds 20 \
  --ros2-physical-kind physical.move \
  --ros2-physical-objective "move robot to staging point" \
  --physical-robot-id unitree.go2 \
  --physical-target warehouse.aisle-7 \
  --physical-command move_to_pose \
  --physical-safety-class restricted \
  --physical-dry-run \
  --format human
```

`ros2_physical` notes:

- Requires `ros2` CLI in `PATH`, or set `LOOM_SHADOW_ROS2_BIN`.
- Reads ROS2 bridge controls from:
  - service mode (default): `--ros2-mode service`, `--ros2-service`,
    `--ros2-type`, `--ros2-timeout-seconds`
  - action mode: `--ros2-mode action`, `--ros2-action-name`,
    `--ros2-action-type`, optional `--ros2-action-feedback`,
    optional `--ros2-action-cancel-after-seconds`,
    `--ros2-timeout-seconds`
- Persists typed diagnostics with `transport_kind=ros2` and ROS2
  service/action metadata in the same operator diagnostics stream
  (`artifacts/shadow/grpc_action/`).

ROS2 action mode example:

```bash
loom shadow run \
  --backend ros2_physical \
  --root "$LOOM_ROOT" \
  --kernel-path "$MERIDIAN_KERNEL_PATH" \
  --agent-id agent_atlas \
  --org-id "$MERIDIAN_ORG_ID" \
  --action-type shadow_ros2_physical \
  --resource external_ros2_physical \
  --warrant-file ./shadow-warrant.json \
  --ros2-mode action \
  --ros2-action-name /meridian/physical_action/goal \
  --ros2-action-type meridian_embodied_msgs/action/ExecutePhysicalAction \
  --ros2-action-feedback \
  --ros2-action-cancel-after-seconds 5 \
  --ros2-timeout-seconds 20 \
  --ros2-physical-kind physical.move \
  --ros2-physical-objective "move robot to staging point" \
  --physical-robot-id unitree.go2 \
  --physical-target warehouse.aisle-7 \
  --physical-command move_to_pose \
  --physical-safety-class restricted \
  --physical-dry-run \
  --format human
```

The settlement slice is bounded on purpose:

- `shadow run` requires a verified warrant file
- `job settle --zk` binds to the PoGE witness digest from the latest shadow run
- `job settle --zk --zk-backend ...` currently supports `sp1`
- Court and Treasury are checked before settlement is marked prepared
- chain finality is not claimed until a chain adapter confirms submission

Acceptance lane (one command):

```bash
./scripts/acceptance_shadow_zk.sh
# or
make acceptance-shadow-zk

# full lane (core flow + typed report assertions)
./scripts/acceptance_shadow_zk_lane.sh
# or
make acceptance-shadow-zk-lane

# embodied core lane (ros2_physical -> settle --zk -> reports)
./scripts/acceptance_shadow_embodied_zk.sh
# or
make acceptance-shadow-zk-embodied
```

Core merge gate (Shadow + ZK path):

```bash
./scripts/acceptance_shadow_zk_lane.sh
cargo test -p loom-shadow
cargo test -p meridian-loom --test shadow_zk
```

Swarm acceptance (`acceptance_swarm_lane.sh`) is a separate lane and is
intentionally excluded from this core gate.

## Sovereign evolution lanes

Breed a governed child agent DNA artifact (Court + Authority gated):

```bash
loom breed agent_atlas agent_quill \
  --agent-id agent_atlas \
  --mutation-rate 0.15 \
  --root "$LOOM_ROOT" \
  --kernel-path "$MERIDIAN_KERNEL_PATH" \
  --org-id "$MERIDIAN_ORG_ID" \
  --format human
```

Initialize one sovereign institution stack in the local runtime root:

```bash
loom init-nation \
  --charter "Shadow Era Charter" \
  --org-id "$MERIDIAN_ORG_ID" \
  --root "$LOOM_ROOT" \
  --kernel-path "$MERIDIAN_KERNEL_PATH" \
  --format human

loom connect scaffold \
  --name grpc_action_adapter \
  --transport grpc \
  --action-schema meridian.a2a.action.v1 \
  --root "$LOOM_ROOT" \
  --format human

loom connect list --root "$LOOM_ROOT" --format human
```

## Common failures

- `401 unauthorized`: token mismatch between service start and HTTP client
- `400 bad_request`: malformed HTTP request or invalid JSON body
- `415 unsupported_media_type`: submit/import request was not JSON
- `service log not found`: service has not been started yet
- `runtime service already appears to be running`: stale or active lock/PID detected
- `kernel path is required`: config or command is missing a kernel binding for that path
