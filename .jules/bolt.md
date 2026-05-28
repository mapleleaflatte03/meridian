## 2024-05-28 - Remove unnecessary list() wrapper on get() or []
**Learning:** When iterating over dictionary values that might be None, use `for item in data.get('key') or []:` instead of wrapping the result in `list()`. This avoids an unnecessary O(n) shallow copy and improves performance on large datasets.
**Action:** Avoid wrapping expressions with `list()` in `for` loop iterables when it's just meant to handle default empty lists. Use `data.get('key') or []` natively.
