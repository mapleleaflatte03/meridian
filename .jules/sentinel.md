## 2026-06-30 - Fix SQL injection in SQLite PRAGMA journal_mode configuration
**Vulnerability:** The SQLite PRAGMA statement in `observability_store.py` was being directly formatted with the unvalidated environment variable `MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE`, leading to potential SQL injection.
**Learning:** SQLite PRAGMA statements do not support parameter binding (`?`). Dynamic configuration values passed to PRAGMA statements must be validated against a strict allowlist.
**Prevention:** Always validate configuration variables against a strict allowlist before interpolating them into PRAGMA statements or SQL queries. Preserve the application's control flow logic (e.g. empty strings or DEFAULT) when implementing the allowlist validation.
