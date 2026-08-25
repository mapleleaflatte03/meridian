## 2025-02-21 - SQLite PRAGMA Injection via Environment Variables
**Vulnerability:** SQL injection is possible if user-controlled or external strings are passed into SQLite `PRAGMA` statements via string interpolation (e.g., `f'PRAGMA journal_mode={mode}'`), because parameterization (e.g., `?`) is not supported for pragmas.
**Learning:** Even environment variables used for database configuration (like `MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE`) can act as an injection vector if the application environment can be manipulated or if configurations are dynamically sourced.
**Prevention:** Always validate external strings intended for `PRAGMA` execution against a strict, static allowlist of acceptable values (e.g., `{'WAL', 'MEMORY', 'DELETE', etc.}`) prior to interpolation.
