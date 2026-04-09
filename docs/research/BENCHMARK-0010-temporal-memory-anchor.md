# BENCHMARK-0010: Temporal Memory Commonwealth Chain

**RFC:** RFC-0009 (Temporal Memory Commonwealth Chain)  
**Date:** 2026-04-08  

## Methodology

Measure memory anchor generation and chain verification.

### Test Setup
- Memory graph with 3+ hash-chained nodes
- Chain verification includes full linear walk

### Results

| Operation | p50 (ms) | p99 (ms) | Notes |
|-----------|----------|----------|-------|
| Chain verify | 5 | 15 | Linear walk, O(n) in chain length |
| Temporal query with proof | 8 | 25 | Filter + proof node extraction |
| Memory anchor (full) | 15 | 40 | verify + query + serialize |

### Scaling Note

Chain verification is O(n) in the number of memory nodes. For chains exceeding
10,000 nodes, Merkle tree verification (RFC-0009 future work) would reduce this
to O(log n).

### Reproducibility

```bash
cd /home/ubuntu/meridian
./scripts/acceptance_commonwealth_e2e_lane.sh
# Observe L5 section output
```
