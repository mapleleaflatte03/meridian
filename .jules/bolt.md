## 2026-07-08 - Use Sets for Deduplication in Loops
**Learning:** Using `item not in seen` where `seen` is a list causes O(N²) time complexity when deduplicating items inside a loop. This is an anti-pattern.
**Action:** Always initialize a set (`seen = set()`) and use `seen.add(item)` to achieve O(1) lookups and O(N) overall complexity.
