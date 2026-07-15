## 2026-07-15 - O(N^2) Deduplication in List Inclusion Checks
**Learning:** Checking inclusion against a list (e.g., `if item not in seen:`) inside a loop results in O(N^2) time complexity, causing potential performance bottlenecks when processing large lists of items.
**Action:** Always initialize a set (`seen = set()`) and use `seen.add(item)` to achieve O(1) lookups and O(N) overall complexity when deduplicating items inside a loop.
