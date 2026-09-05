## 2025-02-14 - Fix SQL injection in SQLite journal_mode configuration
**Vulnerability:** The `MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE` environment variable was directly interpolated into a `PRAGMA journal_mode=` statement via an f-string without validation.
**Learning:** SQLite PRAGMA statements do not support standard parameterization (`?`), requiring strict manual validation or allowlisting for dynamic values to prevent SQL injection.
**Prevention:** Always implement a hardcoded allowlist when setting PRAGMA values from external inputs (like environment variables) in SQLite.
