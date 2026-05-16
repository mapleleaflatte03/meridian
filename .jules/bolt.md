## 2025-02-12 - copy.deepcopy() is slower than json.loads()
**Learning:** When caching file reads in Python to avoid mutation bugs, `copy.deepcopy()` on parsed dicts is often slower than reading from the OS cache, defeating the point of caching. Caching the raw JSON string and parsing it with `json.loads(cached_str)` is significantly faster.
**Action:** Use string caching and `json.loads` instead of `copy.deepcopy` when caching JSON read operations in Python.
