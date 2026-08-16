## 2024-08-16 - Prevent SQL Injection in SQLite PRAGMA Statements
**Vulnerability:** SQL injection vulnerability via untrusted environment variables injected directly into `PRAGMA` statement strings in `observability_store.py`.
**Learning:** Python's `sqlite3` driver does not support parameterized queries (e.g., `?`) for `PRAGMA` statements.
**Prevention:** When dynamically generating `PRAGMA` queries using external configuration, always validate the input against an explicit allowlist of acceptable values before executing.
