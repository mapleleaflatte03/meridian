## 2026-07-10 - O(N²) Performance Bug with List `not in` lookups
**Learning:** Checking for item existence in a Python list inside a loop (`if item not in seen: seen.append(item)`) results in O(N²) time complexity. Using a Python `set()` changes the lookup from O(N) to O(1) resulting in an O(N) algorithm overall.
**Action:** Always use a `set()` for membership testing inside a loop where duplicates need to be filtered out or tracked.
