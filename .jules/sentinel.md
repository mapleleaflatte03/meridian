## 2024-05-24 - SQL Injection in PRAGMA statement via Environment Variable
**Vulnerability:** A SQLite SQL injection vulnerability was found in `observability_store.py` where an environment variable (`MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE`) was directly concatenated into a `PRAGMA journal_mode` SQL query.
**Learning:** SQLite `PRAGMA` statements do not support parameterized query placeholders (e.g., `?`), making them uniquely susceptible to SQL injection if user or environment inputs are directly concatenated.
**Prevention:** Always validate values intended for `PRAGMA` statements against a strict allowlist of known safe values before execution.
