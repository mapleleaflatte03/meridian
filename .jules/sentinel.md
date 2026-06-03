## 2026-06-03 - Prevent SQL Injection in SQLite PRAGMA Commands
**Vulnerability:** SQL injection vulnerability via unvalidated environment variable `MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE` passed directly into a `PRAGMA journal_mode=` statement via f-string.
**Learning:** SQLite `PRAGMA` statements do not support parameterized queries (`?`), making any dynamic values concatenated into them susceptible to injection attacks.
**Prevention:** Always strictly validate dynamic values against an allowlist before formatting them into `PRAGMA` statements, ensuring special control flow values (like `''` or `'DEFAULT'`) are preserved.
