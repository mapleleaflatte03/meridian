# Meridian Example Packs

Ready-to-run examples for evaluators and new users. Each example is self-contained and can be run after completing onboarding.

## Prerequisites

```bash
# Install and onboard first
curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian/main/scripts/install-full.sh | bash
cd ~/meridian
./scripts/onboard.sh --mode core   # or --mode team
```

## Core Examples

| Example | File | What it demonstrates |
| --- | --- | --- |
| Daily task loop | `core-daily-loop.sh` | Browse, research, memory, inspect cycle |
| Scheduled monitoring | `core-scheduled-check.sh` | Recurring task scheduling |
| Benchmark comparison | `benchmark-vs-claw.sh` | Cold start and RSS comparison |

## Team Examples

| Example | File | What it demonstrates |
| --- | --- | --- |
| Governed execution | `team-governed-execution.sh` | Full Team execution + inspect + audit export |

## Running Examples

```bash
# From the monorepo root:
bash examples/core-daily-loop.sh
bash examples/core-scheduled-check.sh
bash examples/benchmark-vs-claw.sh

# Team mode only:
bash examples/team-governed-execution.sh
```
