## 2026-07-16 - O(N^2) Loop Optimization in ID Deduplication
**Learning:** Checking inclusion against a list (`if item not in seen:`) inside a loop causes O(N^2) time complexity. This was found in `blocking_commitment_ids` and `blocked_peer_host_ids` in `cases.py`.
**Action:** Always initialize a set (`seen = set()`) and use `seen.add(item)` to achieve O(1) lookups and O(N) overall complexity when deduplicating items inside loops.
