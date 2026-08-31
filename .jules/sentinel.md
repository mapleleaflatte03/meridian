## 2026-08-31 - SQL Injection in SQLite PRAGMA
**Vulnerability:** SQL injection vulnerability via unvalidated environment variable in SQLite PRAGMA statement.
**Learning:** Python's sqlite3 module does not support parameterized queries for PRAGMA statements. Using f-strings to inject environment variables into PRAGMA queries introduces SQL injection risks if the variable is controlled by an attacker.
**Prevention:** Always validate external inputs against a strict allowlist before using them in PRAGMA statements or other non-parameterizable SQL queries.
