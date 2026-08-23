## 2025-02-27 - PRAGMA Statements and SQL Injection
**Vulnerability:** SQL Injection via untrusted environment variable input in `PRAGMA` statement construction (`intelligence/company/meridian_platform/observability_store.py`).
**Learning:** `PRAGMA` statements in SQLite do not support parameterized queries (e.g., `?`). When configurations (like journal modes) are read from the environment and interpolated into `PRAGMA` queries, they bypass standard parameterization defenses.
**Prevention:** Always enforce a strict, exhaustive allowlist when constructing `PRAGMA` queries or any dynamic SQL where parameterization is unsupported. Ensure the allowlist explicitly permits historically valid bypass values (like empty strings or `'DEFAULT'`).
