## 2025-02-18 - Fix SQL Injection in PRAGMA statement
**Vulnerability:** SQL Injection via untrusted environment variable interpolation in a SQLite PRAGMA query.
**Learning:** SQLite PRAGMA statements cannot use standard parameterized binding (`?`), which led to string formatting of an environment variable (`MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE`), creating an injection risk.
**Prevention:** Always validate configuration variables against a strict, hardcoded allowlist before interpolating them into SQL queries that do not support parameterization.
