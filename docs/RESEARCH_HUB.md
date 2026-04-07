# Meridian Research Hub

This page collects canonical research artifacts for governance and verifiable local agent execution.

## Core Artifacts

- PoGE protocol: `loom/docs/MERIDIAN_PoGE_PROTOCOL.md`
- Runtime benchmarks: `loom/docs/BENCHMARKS.md`
- Cross-stack architecture: `intelligence/ARCHITECTURE.md`
- Kernel + Loom boundary notes: `kernel/docs/LOOM_SPEC.md`

## Baseline Reproduction Commands

```bash
# Loom benchmark harness
cd loom
python3 scripts/bench_runtime.py --help

# Runtime proof surface checks
curl -fsS http://127.0.0.1:8266/api/runtime-proof
curl -fsS http://127.0.0.1:8266/api/kernel-proof-bundle
```

## RFC Process

Use GitHub Discussions for research RFC drafts:

- Start with objective and threat model.
- Include measurable acceptance criteria.
- Link any benchmark traces or proof outputs.
