# Run Local

Loom is currently designed to run as a local-first service boundary on one
Linux host.

## Recommended runtime root

```bash
export LOOM_ROOT="$HOME/.local/share/meridian-loom/runtime/default"
export MERIDIAN_KERNEL_PATH=/opt/meridian-kernel
export LOOM_SERVICE_TOKEN=loom-local-token
mkdir -p "$LOOM_ROOT"
```

## Initialize

```bash
loom init \
  --mode embedded \
  --root "$LOOM_ROOT" \
  --kernel-path "$MERIDIAN_KERNEL_PATH" \
  --org-id local_foundry
```

## Preflight

```bash
loom doctor --root "$LOOM_ROOT" --format human
loom health --root "$LOOM_ROOT" --format human
```

## Start

Background mode:

```bash
loom start \
  --root "$LOOM_ROOT" \
  --kernel-path "$MERIDIAN_KERNEL_PATH" \
  --http-address 127.0.0.1:18910 \
  --service-token "$LOOM_SERVICE_TOKEN"
```

Foreground mode:

```bash
loom start \
  --foreground \
  --root "$LOOM_ROOT" \
  --kernel-path "$MERIDIAN_KERNEL_PATH" \
  --http-address 127.0.0.1:18910 \
  --service-token "$LOOM_SERVICE_TOKEN"
```

## Inspect

```bash
loom status --root "$LOOM_ROOT"
loom logs --root "$LOOM_ROOT" --lines 50
curl -sS -H "Authorization: Bearer ${LOOM_SERVICE_TOKEN}" http://127.0.0.1:18910/status
curl -sS -H "Authorization: Bearer ${LOOM_SERVICE_TOKEN}" http://127.0.0.1:18910/health
curl -sS -H "Authorization: Bearer ${LOOM_SERVICE_TOKEN}" http://127.0.0.1:18910/metrics
```

The runtime root uses this layout:

- config: `<root>/loom.toml`
- state: `<root>/state`
- run: `<root>/run`
- logs: `<root>/logs`
- artifacts: `<root>/artifacts`
- capabilities: `<root>/capabilities`

## Capability registry

Loom now keeps a local capability registry inside the runtime root. Built-in
capabilities are scaffolded automatically at init time.

Inspect the registry:

```bash
loom capability list --root "$LOOM_ROOT"
loom capability show --root "$LOOM_ROOT" --name loom.echo.v1
```

Scaffold a custom local capability:

```bash
loom capability scaffold \
  --root "$LOOM_ROOT" \
  --name local.custom.echo \
  --description "Custom local echo capability" \
  --action-type respond \
  --resource capability:local.custom.echo \
  --worker-kind python
```

Import a real workspace skill bundle from an legacy-style skills tree:

```bash
loom capability import-workspace-skill \
  --root "$LOOM_ROOT" \
  --skill-root /root/.legacy-runtime/workspace/skills/malware-triage
```

That creates a Loom-native capability wrapper around the imported skill bundle,
so execution still happens through Loom's own queue, job, worker, and artifact
paths.

Forge a Loom-native candidate capability directly inside the runtime:

```bash
loom capability forge \
  --root "$LOOM_ROOT" \
  --gap-class artifact_triage \
  --goal "suspicious artifact triage"

loom capability gap show \
  --root "$LOOM_ROOT" \
  --gap-id <gap_id>
```

Verify and promote that imported capability through Loom's own runtime path:

```bash
loom capability verify \
  --root "$LOOM_ROOT" \
  --kernel-path "$MERIDIAN_KERNEL_PATH" \
  --agent-id agent_tutorial \
  --org-id local_foundry \
  --name clawskill.malware-triage.v0 \
  --payload-json '{"artifact_path":"/tmp/sample.exe","skip_container":true}' \
  --estimated-cost-usd 0.05

loom capability promote \
  --root "$LOOM_ROOT" \
  --name clawskill.malware-triage.v0
```

Verify a forged capability against actual worker-result expectations:

```bash
loom capability verify \
  --root "$LOOM_ROOT" \
  --kernel-path "$MERIDIAN_KERNEL_PATH" \
  --agent-id agent_tutorial \
  --org-id local_foundry \
  --name loomforge.artifact.inspect.v0 \
  --payload-json '{"artifact_path":"/tmp/sample.exe"}' \
  --estimated-cost-usd 0.05 \
  --expect-summary-contains sample.exe \
  --expect-result-field artifact_exists=true \
  --expect-result-field artifact_name=sample.exe

loom capability promote \
  --root "$LOOM_ROOT" \
  --name loomforge.artifact.inspect.v0
```

## Submit

```bash
curl -sS \
  -H "Authorization: Bearer ${LOOM_SERVICE_TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  --data '{
    "request_id":"demo-submit",
    "agent_id":"agent_allow",
    "org_id":"local_foundry",
    "action_type":"research",
    "resource":"web_search",
    "estimated_cost_usd":0.05,
    "kernel_path":"/opt/meridian-kernel"
  }' \
  http://127.0.0.1:18910/submit
```

Then inspect:

```bash
loom job list --root "$LOOM_ROOT" --format human
loom job inspect --root "$LOOM_ROOT" --job-id <job_id> --format human
loom parity report --root "$LOOM_ROOT"
loom shadow report --root "$LOOM_ROOT"
```

Submit through a built-in capability instead of raw action/resource fields:

```bash
loom action execute \
  --root "$LOOM_ROOT" \
  --kernel-path "$MERIDIAN_KERNEL_PATH" \
  --agent-id agent_atlas \
  --org-id org_b7d95bae \
  --capability loom.echo.v1 \
  --payload-json '{"message":"hello from capability"}' \
  --estimated-cost-usd 0.05
```

Run an imported workspace skill through the same runtime path:

```bash
loom action execute \
  --root "$LOOM_ROOT" \
  --kernel-path "$MERIDIAN_KERNEL_PATH" \
  --agent-id agent_tutorial \
  --org-id local_foundry \
  --capability clawskill.malware-triage.v0 \
  --payload-json '{"artifact_path":"/tmp/sample.exe","skip_container":true}' \
  --estimated-cost-usd 0.05
```

Exercise the same capability path through the service boundary:

```bash
./scripts/acceptance_capability_service.sh
./scripts/migration_tools/rehearse_claw_skill_service.sh
./scripts/migration_tools/rehearse_claw_skill_multi_import.sh
./scripts/migration_tools/rehearse_legacy_plugin_import.sh
./scripts/migration_tools/rehearse_server_replacement.sh
./scripts/tests/rehearse_phase2_portability_corpus.sh
```

`scripts/migration_tools/rehearse_server_replacement.sh` is the replacement-proof path for this branch:
it imports `malware-triage`, verifies it, promotes it, submits it through Loom
service, inspects the completed job, restarts Loom, submits the same imported
skill again, then tails logs and stops cleanly. It proves the local server path
is owned by Loom. It does not prove live legacy-runtime cutover.

## Restart and stop

```bash
loom restart --root "$LOOM_ROOT" --kernel-path "$MERIDIAN_KERNEL_PATH" --http-address 127.0.0.1:18910 --service-token "$LOOM_SERVICE_TOKEN"
loom stop --root "$LOOM_ROOT"
```
