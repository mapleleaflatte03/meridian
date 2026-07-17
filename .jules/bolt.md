## 2026-07-17 - Array Deduplication Bottlenecks in Data Processing Loops

**Learning:** When iterating over potentially large lists of records (like database rows) to extract unique values, deduplicating using `if item not in seen_list:` causes an O(N^2) time complexity because Python must linearly scan the `seen_list` for every item processed.

**Action:** Always initialize `seen` as a `set()` (e.g., `seen = set()`) and use `seen.add()` instead of a list when deduplicating items inside a loop. This reduces the lookup time to O(1) and overall complexity to O(N). Because `sorted(seen)` works on sets and returns a list, the return type remains unchanged.
