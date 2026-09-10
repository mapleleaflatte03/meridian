## 2024-05-18 - Fix SQL Injection in SQLite PRAGMA journal_mode
**Vulnerability:** SQL injection vulnerability via unvalidated environment variable `MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE` interpolated into `conn.execute(f'PRAGMA journal_mode={...}')`.
**Learning:** SQLite `PRAGMA` statements do not support parameterized queries (e.g., using `?`). Therefore, when setting PRAGMA values dynamically from external inputs (like environment variables), you cannot use parameterization.
**Prevention:** You must explicitly validate the input against a strict allowlist (e.g., `'DELETE'`, `'TRUNCATE'`, `'PERSIST'`, `'MEMORY'`, `'WAL'`, `'OFF'`, `''`, `'DEFAULT'`) before formatting it into the SQL string to prevent SQL injection.
