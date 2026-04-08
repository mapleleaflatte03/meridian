# Meridian Research Hub

This page collects canonical research artifacts for governance and verifiable local agent execution.

## Core Artifacts (Canonical)

- PoGE protocol: `loom/docs/MERIDIAN_PoGE_PROTOCOL.md`
- Runtime benchmarks: `loom/docs/BENCHMARKS.md`
- Cross-stack architecture: `intelligence/ARCHITECTURE.md`
- Kernel + Loom boundary notes: `kernel/docs/LOOM_SPEC.md`
- Public roadmap: `ROADMAP.md`
- Community routing for RFCs: `docs/COMMUNITY_MAP.md`

## PoGE + Governance RFC Track

Use the `Research RFC` issue template to propose protocol/runtime changes:

- Template: `.github/ISSUE_TEMPLATE/research_rfc.yml`
- Open RFC issue: `https://github.com/mapleleaflatte03/meridian/issues/new/choose`

Every RFC must include:

1. trust-boundary impact,
2. measurable acceptance criteria,
3. rollback strategy.

## Baseline Reproduction Commands

```bash
# Loom benchmark harness
cd loom
python3 scripts/bench_runtime.py --help

# Runtime proof surface checks
curl -fsS http://127.0.0.1:8266/api/runtime-proof
curl -fsS http://127.0.0.1:8266/api/kernel-proof-bundle

# Governance state checks
curl -fsS http://127.0.0.1:8266/api/institution/template
curl -fsS http://127.0.0.1:8266/api/treasury
curl -fsS http://127.0.0.1:8266/api/status
```

## Killer Example (Governed Runtime Loop)

Minimal example to show why Meridian is different from generic local-agent runtimes:

1. bootstrap stack (`./scripts/bootstrap_full.sh`)
2. start services (`./scripts/dev-up.sh`)
3. inspect institution template and court rules
4. inspect treasury reserve discipline
5. inspect runtime proof + kernel proof bundle

Expected evidence:

- institution template schema present (`meridian.institution_template.v1`)
- court rules initialized (>=3)
- treasury snapshot carries balance + reserve floor
- runtime proof route and kernel proof bundle are reachable and coherent

## Suggested Research Outputs

- benchmark notes (`loom/docs/BENCHMARKS.md`)
- proof-route audits (`/api/runtime-proof`, `/api/kernel-proof-bundle`)
- governance case studies (incident -> sanction -> remediation traces)

Keep outputs reproducible: include exact commands, payload snippets, and module/commit context.
