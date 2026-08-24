## 2024-05-18 - Prevent SQL Injection via SQLite PRAGMA

**Vulnerability:** SQL injection vulnerability in `intelligence/company/meridian_platform/observability_store.py` where an unvalidated environment variable `MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE` was directly interpolated into a `PRAGMA journal_mode={...}` query via an f-string.
**Learning:** PRAGMA statements in Python's `sqlite3` module do not support parameterized queries (e.g., `?`). When dynamically generating PRAGMA queries using externally controlled configuration (such as environment variables), the input can be manipulated to execute arbitrary PRAGMA commands or SQL statements.
**Prevention:** Strictly validate dynamically generated PRAGMA values against an explicit allowlist of acceptable values (e.g., `{'DELETE', 'TRUNCATE', 'PERSIST', 'MEMORY', 'WAL', 'OFF'}`) before executing the query.
