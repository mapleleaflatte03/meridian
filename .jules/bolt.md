## 2026-07-18 - Replacing O(N) list inclusion with O(1) set inclusion in loops
**Learning:** When deduplicating items or checking for inclusion inside a loop (`if item not in seen:`), using a list for `seen` results in O(N^2) time complexity.
**Action:** Always initialize a set (`seen = set()`) and use `seen.add(item)` to achieve O(1) lookups and O(N) overall complexity.
