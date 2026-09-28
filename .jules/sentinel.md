## 2024-09-28 - SQLite PRAGMA SQL Injection
**Vulnerability:** SQL injection via unsanitized environment variable `MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE` interpolated into a PRAGMA statement string in `observability_store.py`. The original code used a negative allowlist that failed to prevent arbitrary payload execution.
**Learning:** SQLite's Python driver doesn't support parameterized queries for PRAGMA statements, making them highly susceptible to injection if user or environment inputs are used directly. A negative allowlist check is insufficient.
**Prevention:** Always use strict positive allowlists for dynamic PRAGMA values.
