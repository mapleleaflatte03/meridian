## 2024-08-17 - Prevent SQL Injection in PRAGMA configuration
**Vulnerability:** SQL injection possible through unvalidated environment variable `MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE` when generating PRAGMA statements dynamically.
**Learning:** Python's sqlite3 module doesn't allow parameterized bindings (e.g. `?`) in PRAGMA statements, so values dynamically inserted via format strings must be strictly allowlisted when they are derived from external inputs.
**Prevention:** Always validate external configuration used in PRAGMA or schema manipulation statements against a hardcoded allowlist.
