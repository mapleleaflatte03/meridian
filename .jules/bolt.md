## 2024-05-30 - Dictionary iteration optimization
**Learning:** In Python, doing `for item in list(data.get('key') or []):` creates an unnecessary O(N) shallow copy.
**Action:** Use `for item in data.get('key') or []:` instead. Note that `list()` should still be preserved when iterating over `.values()`, `.keys()`, or `.items()` if the dictionary might be mutated during iteration.
