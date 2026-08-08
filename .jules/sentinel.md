## 2024-08-08 - Fix SQL injection in SQLite PRAGMA
**Vulnerability:** A SQL injection vulnerability existed in `intelligence/company/meridian_platform/observability_store.py` where an unvalidated environment variable was directly injected into a `PRAGMA journal_mode=` statement using an f-string.
**Learning:** `PRAGMA` statements in sqlite3 do not support parameterized queries (`?`), meaning dynamic variables passed to them must be strictly validated.
**Prevention:** Strictly validate any dynamic input for `PRAGMA` statements against an explicit allowlist of acceptable values (including historical bypass values) before execution to prevent SQL injection.
