## 2024-05-15 - Unsafe PRAGMA Interpolation in SQLite Connection Setup
**Vulnerability:** SQL Injection via untrusted environment variable `MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE` interpolated directly into a `PRAGMA journal_mode=` statement.
**Learning:** Python's `sqlite3` driver does not support parameterized queries (e.g., `?`) for `PRAGMA` statements. External configuration injected into these commands must be strictly validated.
**Prevention:** Always validate values intended for `PRAGMA` statements against a hardcoded allowlist of permitted options before formatting them into the query string.
