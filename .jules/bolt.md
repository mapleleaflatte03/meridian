## 2026-08-11 - Optimize O(N^2) seen list lookups
**Learning:** Found O(N^2) list containment checks in  (both in intelligence and kernel) for deduplicating cases. Since cases can grow large, using lists for deduplication leads to performance bottlenecks on hot paths.
**Action:** Replace `seen = []` and `if X not in seen: seen.append(X)` with `seen = set()` and `seen.add(X)` followed by `sorted(seen)` to reduce time complexity from O(N^2) to O(N). Avoid converting sets to lists before sorting.
