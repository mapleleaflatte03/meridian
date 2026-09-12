## 2024-09-12 - Prevent SQL Injection via SQLite PRAGMA Statements
**Vulnerability:** SQL injection risk due to unvalidated environment variable used in SQLite PRAGMA statements.
**Learning:** Python's sqlite3 module does not support parameterized queries (e.g. `?`) in PRAGMA statements. Input used in PRAGMA statements must be validated against a strict allowlist.
**Prevention:** Always validate external input (like environment variables) against an explicit allowlist before using it in string interpolation for SQL queries, especially PRAGMA statements.
