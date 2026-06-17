## 2024-05-04 - Caching OS Page Memory Instead of Deepcopy
**Learning:** Python `copy.deepcopy()` on parsed JSON dicts is often slower than storing the raw JSON string and calling `json.loads()` on demand when retrieving from the cache, because json string parsing via the C-extension is heavily optimized.
**Action:** When caching JSON-serializable payloads in memory to avoid mutation bugs, save the object as a JSON string with `json.dumps()` in the cache, and retrieve it using `json.loads()` instead of relying on `copy.deepcopy()`.
