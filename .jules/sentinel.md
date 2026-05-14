## 2025-02-14 - SQL Injection via PRAGMA Statement

**Vulnerability:** A `PRAGMA journal_mode=` SQL statement in `intelligence/company/meridian_platform/observability_store.py` was being constructed via an f-string using an unvalidated environment variable (`MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE`).
**Learning:** `sqlite3.Connection.execute()` does not support parameterized queries (placeholders) for `PRAGMA` statements. While `execute()` does not allow multiple semicolon-separated statements (which limits the injection attack surface compared to `executescript()`), constructing any part of a query with dynamic input inherently bypasses parameterization defenses.
**Prevention:** Always validate values used in `PRAGMA` statements or other unparameterizable SQL contexts against a strict, hardcoded allowlist before interpolation.
