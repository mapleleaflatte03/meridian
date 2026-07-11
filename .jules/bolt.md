## 2026-07-11 - O(1) Set Lookups for Deduplication
**Learning:** Deduplicating lists of ids using `if item not in list` inside a loop leads to O(N^2) time complexity, which becomes a silent bottleneck as data grows. Python sets provide O(1) membership checks.
**Action:** Always initialize a `set()` instead of `[]` when tracking seen items during iteration.
