## 2024-06-25 - Redundant `list()` wrapper when slicing
**Learning:** In Python, applying `[:N]` slicing to an expression like `list(data.get('key') or [])[:N]` creates an unnecessary full list copy before truncating it. This is highly inefficient.
**Action:** When truncating a list returned by a dictionary fallback (e.g. `.get()`), omit the redundant `list()` cast and properly parenthesize the slice target: `(data.get('key') or [])[:N]`. Always ensure parentheses wrap the entire `or` expression so the slice applies correctly to the list fallback instead of just `[]`.
