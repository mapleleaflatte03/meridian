## 2026-07-09 - Performance deduplication cases

**Learning:** Replacing `seen = []` with `if item not in seen:` loops using `seen = set()` and `seen.add()` reduces time complexity from O(N^2) to O(N) because set lookups are O(1) compared to list lookups which are O(N).
**Action:** Use sets instead of lists when checking for item existence in a loop to ensure optimal algorithmic performance.
