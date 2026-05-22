## 2024-05-22 - SQL Injection Risk in SQLite PRAGMA Commands
**Vulnerability:** SQL injection vulnerability via environment variable `MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE` due to f-string concatenation in `PRAGMA journal_mode` execution.
**Learning:** SQLite `PRAGMA` commands in Python's `sqlite3` module do not support parameterized queries (`?`), leading to string concatenation which introduces injection risks.
**Prevention:** Always validate values intended for SQLite `PRAGMA` commands against a strict allowlist before dynamically incorporating them into SQL strings.
