## 2024-05-24 - Fix SQL Injection in PRAGMA statement
**Vulnerability:** SQL injection vulnerability in `observability_store.py` where an environment variable (`MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE`) is used directly in a `PRAGMA` execution without being validated against an allowlist.
**Learning:** `PRAGMA` statements in sqlite3 do not support parameterized queries (e.g. `?`). Therefore, when dynamically generating `PRAGMA` queries using externally controlled configuration, you must validate against an explicit allowlist.
**Prevention:** Always validate configuration variables against a strict allowlist before interpolating them into a `PRAGMA` statement.
