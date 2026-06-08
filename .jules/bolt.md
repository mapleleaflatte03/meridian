## 2024-06-08 - Caching Specialist Restriction Checks in Hot Loops
**Learning:** Checking if a specialist worker is restricted using `court_get_restrictions` happens repeatedly in the gateway's routing loop (`_normalize_worker_selection`), especially for keys like SENTINEL and AEGIS. This causes redundant database/court API calls that degrade latency during team construction.
**Action:** Always wrap deterministic restriction/governance checks with `@functools.lru_cache` in hot routing paths to eliminate redundant queries.
