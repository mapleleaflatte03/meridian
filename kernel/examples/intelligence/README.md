# Example: Competitive Intelligence Vertical

This example shows how to map a multi-agent workflow onto the five
constitutional primitives.

## The Workflow

A competitive intelligence pipeline with eight phases, each assigned
to a specific agent:

| Phase | Agent | Action | Description |
|-------|-------|--------|-------------|
| Research | Atlas | execute | Fetch sources, extract findings |
| Write | Quill | execute | Write cited intelligence brief |
| QA (Sentinel) | Sentinel | review | Verify sources, check contradictions |
| QA (Aegis) | Aegis | review | PASS/FAIL acceptance gate |
| Execute | Forge | execute | Bounded improvement task |
| Compress | Pulse | execute | Compress context for delivery |
| Deliver | Leviathann | execute | Deliver brief to subscribers |
| Score | Leviathann | execute | Auto-score agents, advance epoch |

## How It Uses the Kernel

### Preflight

Before the pipeline runs, `ci_vertical.py preflight` checks every
constitutional gate:

1. **Institution** — is the institution in `active` lifecycle?
2. **Authority** — is the kill switch off? Does each agent have rights for their action?
3. **Treasury** — is the runway above critical threshold?
4. **Court** — is any pipeline agent suspended?

If any gate fails, the pipeline blocks.

### Post-Mortem

After the pipeline runs, `ci_vertical.py post-mortem` analyzes the
output and files court violations for failures:

- Sentinel QA failure → severity 2 violation
- Aegis rejection → severity 3 violation (auto-sanctions Quill)
- Delivery failure → severity 2 violation

### Status View

`ci_vertical.py status` shows the full constitutional map:
all five primitives applied to the pipeline.

## Running It

```bash
# From the repo root, after running quickstart.py:

# Check all gates
python3 examples/intelligence/ci_vertical.py preflight

# View full constitutional status
python3 examples/intelligence/ci_vertical.py status

# Analyze a sample or deployment run
python3 examples/intelligence/ci_vertical.py post-mortem
```

By default, the example reads artifacts from `examples/intelligence/sample-data/`.
For a real deployment, point it at your own runtime output with
`MERIDIAN_ARTIFACT_DIR=/path/to/artifacts`.

## Building Your Own Vertical

To create a new governed workflow:

1. Define your phases and agent assignments
2. Map each phase to an action type (`execute`, `review`, `lead`)
3. Use `check_authority(agent, action)` before each phase
4. Use `check_budget(agent, cost)` for expensive operations
5. Use `file_violation()` when phases fail
6. Wire preflight checks before the workflow starts

The kernel doesn't care what your agents do — it governs *how* they
are allowed to do it.
