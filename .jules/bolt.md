## 2026-06-30 - Replace O(N^2) list lookup with O(1) hash map lookup
**Learning:** Using `if item not in list` inside a loop for deduplicating array items creates an O(N^2) bottleneck, which is particularly detrimental when dealing with database rows (e.g. evaluating blocking cases).
**Action:** Always use a `set` for deduplication lookups to achieve O(1) time complexity, and then convert the result back to a sorted list if deterministic order is required.
