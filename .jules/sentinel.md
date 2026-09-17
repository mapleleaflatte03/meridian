## 2024-09-17 - SQL Injection in SQLite PRAGMA Statements
**Vulnerability:** SQL Injection via untrusted environment variables in `PRAGMA journal_mode=...` statement.
**Learning:** SQLite's `sqlite3` module does not support parameterized queries (e.g. `?`) in PRAGMA statements. Using f-strings or string concatenation creates an injection vector if the input is untrusted.
**Prevention:** Always use a strict positive allowlist when dynamically constructing PRAGMA statements from external input.
