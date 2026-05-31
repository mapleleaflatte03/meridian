## 2024-05-24 - Removing `list()` wrapper for dictionary fallback iteration
**Learning:** Iterating over `data.get('key') or []` inside `for item in ...` does not need an explicit `list()` wrapper when iterating. The `list()` creates an unnecessary O(N) shallow copy.
**Action:** When a fallback returns a native list `[]` and `data.get('key')` returns an iterable, omit `list()` unless mutation requires a snapshot copy. Also ensure parens are maintained if there are slices.
