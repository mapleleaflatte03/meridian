## 2026-07-14 - Deduplication performance bottleneck
**Learning:** The deduplication logic in `cases.py` functions like `blocking_commitment_ids` and `blocked_peer_host_ids` used a list `seen = []` for tracking seen elements, causing O(N^2) complexity with `if item not in seen`.
**Action:** Always initialize a set (`seen = set()`) and use `seen.add(item)` for O(1) lookups to ensure O(N) overall complexity when deduplicating items inside loops.
