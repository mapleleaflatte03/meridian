## 2025-02-14 - Fix sqlite PRAGMA SQL injection

**Vulnerability:** The environment variable `MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE` was directly injected into a `PRAGMA journal_mode={...}` SQL command after bypassing a blocklist `not in {'', 'DEFAULT', 'OFF'}`. This exposed the application to potential arbitrary SQL injection by manipulating the environment variable.
**Learning:** Using a blocklist for input validation allows malicious strings to slip through. The code assumed any value other than `''`, `DEFAULT`, or `OFF` was a safe SQLite configuration value, rather than explicitly enumerating valid `PRAGMA journal_mode` options.
**Prevention:** Always use strict allowlisting for values injected into `PRAGMA` statements, as parameterized queries (`?`) are not supported for `PRAGMA` in sqlite3.
