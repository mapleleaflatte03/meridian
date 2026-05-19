## 2024-05-15 - Fast Dictionary Iteration
**Learning:** Found multiple places in the backend where Python dictionaries were iterated like `for x in list(data.get('key') or []):`. Wrapping in `list()` creates an unnecessary O(n) shallow copy, which affects performance on large datasets.
**Action:** Replace `for x in list(data.get('key') or []):` with `for x in data.get('key') or []`.
