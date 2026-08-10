## 2024-05-23 - Prevent SQL Injection in SQLite PRAGMA Statements
**Vulnerability:** SQL injection vulnerability in `observability_store.py` where the `PRAGMA journal_mode` was directly formatted using the `MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE` environment variable.
**Learning:** SQLite `PRAGMA` statements do not support standard parameterized queries (`?`). Therefore, user or environment input cannot be safely passed to them without validation.
**Prevention:** Always strictly validate input against an explicit allowlist of acceptable values (including fallbacks like `''` or `'DEFAULT'`) before formatting it into `PRAGMA` execution statements.
