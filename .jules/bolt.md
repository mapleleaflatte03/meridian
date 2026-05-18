## 2025-01-20 - Unnecessary Copy Optimization
**Learning:** Python creates unnecessary O(n) shallow copies when using `list()` on iterables or lists just to prevent iteration over `None`. The memory specifically instructs to use `for item in data.get('key') or []:` instead of `for item in list(data.get('key') or []):`, giving a measured ~4.5% improvement on large datasets in this architecture.
**Action:** Replace `for item in list(data.get('key') or []):` with `for item in data.get('key') or []:` across the backend.
