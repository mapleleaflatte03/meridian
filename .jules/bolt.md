## 2024-08-13 - O(n^2) list counts inside comprehensions
**Learning:** Checking for duplicates using a list comprehension with `list.count()` inside it (e.g., `[x for x in lst if lst.count(x) > 1]`) creates an unexpected O(n^2) bottleneck that is very noticeable on large lists, even in error paths.
**Action:** Always use sets to track seen items and identify duplicates for an O(n) approach.
