## 2026-07-17 - Fix SQL Injection in PRAGMA Statement
**Vulnerability:** The SQLite `PRAGMA journal_mode` value was being loaded from an environment variable and interpolated directly into an SQL statement without sufficient validation, creating an SQL injection risk.
**Learning:** SQLite `PRAGMA` statements do not support parameter binding (`?`), which means dynamic configurations for PRAGMA must be carefully validated against a strict allowlist.
**Prevention:** Always use a strict allowlist to validate dynamic configurations for `PRAGMA` statements.
