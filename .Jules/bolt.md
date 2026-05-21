## 2024-05-30 - Slicing Precedence on Default Arrays
**Learning:** When removing `list()` wrappers from expressions that include slicing (e.g., `list(data.get('key') or [])[:N]`), Python's operator precedence dictates that the slice `[:N]` evaluates before `or`. Thus, `data.get('key') or [][:N]` slices the empty list fallback, NOT the data list, causing unexpected behavior and bounding failures.
**Action:** When removing `list()` casts, always wrap the resulting `or` expression in parentheses before slicing: `(data.get('key') or [])[:N]`.
