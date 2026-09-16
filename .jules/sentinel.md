## 2024-05-23 - Prevent SQL Injection in PRAGMA Statements
**Vulnerability:** SQL injection vulnerability found in `PRAGMA journal_mode` due to direct string interpolation of an environment variable (`conn.execute(f'PRAGMA journal_mode={configured_journal_mode}')`).
**Learning:** Python's sqlite3 module does not support parameterized queries for `PRAGMA` statements.
**Prevention:** Always interpolate strings explicitly against a strict allowlist of valid options for `PRAGMA` values to prevent SQL injection.
