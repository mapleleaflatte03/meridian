## 2024-10-09 - SQL Injection via SQLite PRAGMA Statements
**Vulnerability:** Unsanitized environment variables used directly in `PRAGMA journal_mode` string formatting, allowing SQL injection.
**Learning:** Python's sqlite3 module does not support parameterized queries (`?`) for PRAGMA statements, forcing string interpolation which bypasses normal SQL injection protections if not explicitly validated.
**Prevention:** Always validate external inputs against a strict positive allowlist before interpolating them into PRAGMA or other structural SQL statements.
