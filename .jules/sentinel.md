## 2024-05-18 - Prevent SQL Injection via dynamic PRAGMA in SQLite
**Vulnerability:** SQL injection vulnerability via the `MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE` environment variable in `observability_store.py`.
**Learning:** In `sqlite3`, `PRAGMA` statements do not support parameterized queries (`?`). Dynamically setting `PRAGMA` values by string concatenation or interpolation from environment variables or user input allows SQL injection.
**Prevention:** Strictly validate dynamically generated PRAGMA input against an explicit allowlist of acceptable values before execution to prevent SQL injection.
