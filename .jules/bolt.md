## 2026-07-13 - Replace O(N^2) list lookups with O(N) set lookups
**Learning:** When deduplicating items inside a loop using `if item not in seen:`, initializing `seen` as a list (`seen = []`) causes O(N^2) time complexity because list inclusion checks are O(N).
**Action:** Always initialize a set (`seen = set()`) and use `seen.add(item)` for O(1) lookups and O(N) overall complexity.
