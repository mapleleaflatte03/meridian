## 2024-10-25 - SQL Injection via SQLite PRAGMA statement in Python
**Vulnerability:** SQL injection vulnerability in SQLite PRAGMA statement using string interpolation (`conn.execute(f'PRAGMA journal_mode={configured_journal_mode}')`).
**Learning:** SQLite's python `sqlite3` driver does not support parameterized execution (e.g. `?`) in PRAGMA statements. Using string interpolation without validation for these statements allows for SQL injection.
**Prevention:** Any external input mapped to a PRAGMA parameter must be explicitly validated against an allowlist before string interpolation.
