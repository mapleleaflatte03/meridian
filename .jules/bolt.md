## 2026-07-04 - O(N²) Loop in Agent Registry Sync
**Learning:** Found a nested loop `for lk, la in ledger.get('agents', {}).items():` inside a loop iterating over all agents during `sync_from_economy()`. This caused an O(N²) time complexity bottleneck for agent registry syncs when economy keys did not match (fallback to name check).
**Action:** Replace nested loops with a single O(N) precomputation of a hash map (dictionary) before the main loop to achieve O(1) lookups during iteration.
