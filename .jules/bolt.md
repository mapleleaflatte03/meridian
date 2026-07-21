## 2026-07-21 - Fix O(N^2) complexity in loop deduplication
**Learning:** Deduplicating items inside a loop by checking inclusion against a list (e.g., `if item not in seen:`) causes O(N^2) time complexity.
**Action:** Always initialize a set (`seen = set()`) and use `seen.add(item)` to achieve O(1) lookups and O(N) overall complexity.
