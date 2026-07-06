## 2026-07-06 - Replace list inclusion checks with set lookups
**Learning:** Checking inclusion with `if item not in seen:` on a list within a loop results in an O(N^2) time complexity, creating a performance bottleneck when processing large datasets like federated cases or queues.
**Action:** Always use an O(1) hash map lookup (e.g. `seen = set()`) when keeping track of unique items during iteration.
