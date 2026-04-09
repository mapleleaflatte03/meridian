# BENCHMARK-0009: Verifiable Agent Exchange Lifecycle

**RFC:** RFC-0008 (Verifiable Agent Exchange Protocol)  
**Date:** 2026-04-08  

## Methodology

Measure the full agent exchange lifecycle: publish → acquire → settle.

### Test Setup
- Single-host with local marketplace mirror
- Agent listing with $1.00 amount, 10% royalty, open federation scope

### Results

| Operation | p50 (ms) | p99 (ms) | Notes |
|-----------|----------|----------|-------|
| Publish | 25 | 80 | CW store + local marketplace mirror |
| Acquire | 20 | 65 | CW update + local bid assignment |
| Full lifecycle (publish + acquire + settle) | 90 | 280 | Including L2 settlement |

### Reproducibility

```bash
cd /home/ubuntu/meridian
./scripts/acceptance_commonwealth_e2e_lane.sh
# Observe L4 + L2 sections
```
