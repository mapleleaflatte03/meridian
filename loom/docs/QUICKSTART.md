# Quickstart

This is the fastest end-to-end Loom flow that feels like a product, not a repo rehearsal.

It goes through:

1. install
2. initialize Kernel
3. create a governed personal agent
4. connect a delivery channel
5. run the agent loop
6. inspect delivery, memory, channel health, and proof receipts

## 1. Install Loom

```bash
curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian-loom/main/scripts/install.sh | bash
```

## 2. Initialize Kernel

```bash
cd /opt/meridian-kernel
python3 quickstart.py --init-only
```

This creates the local institution and treasury defaults Loom expects on a fresh machine.

## 3. Create your first governed personal agent

```bash
export LOOM_ROOT="${HOME}/.local/share/meridian-loom/runtime/default"
export MERIDIAN_KERNEL_PATH=/opt/meridian-kernel
export MERIDIAN_ORG_ID="${MERIDIAN_ORG_ID:-local_foundry}"

loom new-agent \
  --name "My Assistant" \
  --root "$LOOM_ROOT" \
  --kernel-path "$MERIDIAN_KERNEL_PATH" \
  --org-id "$MERIDIAN_ORG_ID" \
  --format human
```

This command:

- initializes Loom if needed
- registers the agent in Kernel with `runtime_binding=loom_native`
- writes `~/.config/meridian-loom/agents/my-assistant/agent.toml`
- seeds the agent folder with `README.md`, `MEMORY.md`, and `SOUL.md`

Optional first-run delivery flags:

```bash
loom new-agent \
  --name "My Assistant" \
  --telegram-chat-id "123456789" \
  --webhook-url "https://example.com/loom-hook"
```

## 4. Connect a delivery channel

```bash
loom channel connect telegram \
  --agent my-assistant \
  --chat-id "123456789"
```

Or wire a webhook:

```bash
loom channel connect webhook \
  --agent my-assistant \
  --url "https://example.com/loom-hook"
```

Inspect the configured route:

```bash
loom channel list --root "$LOOM_ROOT" --agent my-assistant
loom channel health --root "$LOOM_ROOT" --agent my-assistant --history-limit 5 --diagnostic-limit 5
```

## 5. Run the personal agent loop

```bash
loom run-agent my-assistant
```

The default mode starts a background loop that:

- keeps the local Loom service healthy
- keeps the supervisor ready
- claims due heartbeats
- writes loop state under `run/personal-agents/`
- dispatches governed runs with receipts
- follows the restart policy declared in `agent.toml`

Inspect it:

```bash
tail -f "${HOME}/.local/share/meridian-loom/runtime/default/run/personal-agents/my-assistant.log"
loom run-agent status my-assistant
loom run-agent inspect my-assistant
loom run-agent diagnose my-assistant
loom run-agent watch my-assistant --once
loom status --root "$LOOM_ROOT"
loom doctor --root "$LOOM_ROOT" --format human
```

If the loop exits and the policy should bring it back:

```bash
loom run-agent reconcile my-assistant
```

The supervisor semantics are intentionally explicit:

- `healthy`: supervisor + worker are both running
- `waiting_backoff`: the worker exited and the supervisor is waiting before restart
- `manual_restart_required`: the worker exited under manual policy and needs operator action
- `stopped_by_policy`: the loop is stopped and no restart is pending

## 6. Inspect memory, channels, and receipts

Search the seeded profile memory:

```bash
AGENT_ID="$(
  loom agent runtime --root "$LOOM_ROOT" --agent-id agent_my-assistant 2>/dev/null >/dev/null \
  && printf 'agent_my-assistant' \
  || true
)"
```

If you do not know the exact `agent_id`, read it from `agent.toml`:

```bash
python3 - <<'PY'
from pathlib import Path
config = Path.home() / ".config/meridian-loom/agents/my-assistant/agent.toml"
for line in config.read_text().splitlines():
    if line.startswith("agent_id = "):
        print(line.split("=", 1)[1].strip().strip('"'))
        break
PY
```

Then inspect the runtime surfaces:

```bash
loom memory search --root "$LOOM_ROOT" --agent-id "$AGENT_ID" --category profile
loom memory receipts --root "$LOOM_ROOT" --agent-id "$AGENT_ID" --limit 10
loom channel list --root "$LOOM_ROOT" --agent my-assistant
loom channel health --root "$LOOM_ROOT" --agent my-assistant --history-limit 5 --diagnostic-limit 5
loom channel deliveries --root "$LOOM_ROOT" --include-archived
loom channel test --agent my-assistant --text "Loom delivery path check"
loom job list --root "$LOOM_ROOT" --format human
```

Memory read/write receipts are stored under:

```text
$LOOM_ROOT/state/memory/receipts.jsonl
```

## One truthful next move

After this quickstart, do one of these:

- connect Telegram or webhook delivery in `agent.toml`
- use `loom channel connect` / `loom channel test` instead of editing config by hand
- use `loom channel health --history-limit 5 --diagnostic-limit 5` to verify both current health and recent test history
- set `[supervision] restart_policy = "always"` in `agent.toml` if you want reconcile-friendly restarts
- use `loom run-agent watch my-assistant` when you want a compact operator dashboard instead of raw JSON
- inspect the generated agent folder under `~/.config/meridian-loom/agents/my-assistant/`
- run the terminal and browser examples from the main README
