## 2024-06-03 - Avoid unnecessary shallow copies during iteration
**Learning:** In Python, wrapping `dict.get('key') or []` with `list()` creates an unnecessary O(n) shallow copy, which can cause a ~4.5% performance degradation on large datasets.
**Action:** When iterating over dictionary values that might be None, directly use `for item in data.get('key') or []:` instead of wrapping the result in `list()`.
