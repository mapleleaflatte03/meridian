## 2024-05-25 - copy.deepcopy performance overhead
**Learning:** `copy.deepcopy()` is incredibly slow in Python. Replacing it with `json.loads(json.dumps())` or shallow copy with `dict()` initially seemed like a good performance fix but introduced subtle shared-state mutation risks due to differences in semantic behavior (creating shallow vs deep copies) or side effects (like casting keys from integer to string or crashing on non-json-serializable structures).
**Action:** Do not substitute `deepcopy` with shallow copy or JSON conversion techniques unless the objects strictly only require shallow copying or have only json-compatible types without semantic shifts.

## 2024-05-25 - Unnecessary list() wraps in for-loops
**Learning:** The codebase frequently uses `for item in list(data.get('key') or []):`. Wrapping a list, that is already retrieved as a list from a dictionary, inside another `list()` call forces an unnecessary shallow copy, taking O(N) time and memory overhead. Removing the `list()` wrapper when iterating over dictionary lists provides a modest but measurable performance improvement.
**Action:** Remove `list()` wrappers when iterating over list values from a dictionary like `for item in (data.get('key') or []):` unless the underlying list is expected to be mutated during the iteration, to avoid unnecessary O(n) shallow copies.
