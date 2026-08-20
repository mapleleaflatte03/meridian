## 2024-05-15 - Unsafe PRAGMA Configuration via Environment Variable
**Vulnerability:** SQL Injection in SQLite `PRAGMA journal_mode` via `MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE` environment variable in `observability_store.py`.
**Learning:** PRAGMA statements do not support parameterized queries in Python's sqlite3 module. When generating PRAGMA queries using externally controlled configuration (like environment variables), strict allowlists must be used instead of just excluding values or trusting the input.
**Prevention:** Validate all inputs that are used in dynamic PRAGMA statements against a hardcoded allowlist of acceptable values (e.g., `WAL`, `DELETE`, `TRUNCATE`, `PERSIST`, `MEMORY`, `OFF`).
