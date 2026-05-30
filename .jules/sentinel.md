## 2025-05-30 - Fix SQLite PRAGMA Injection
**Vulnerability:** SQLite `PRAGMA` commands were constructed using f-strings with unsanitized environment variables (e.g., `os.environ.get('MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE')`).
**Learning:** SQLite's `PRAGMA` statement does not support parameterized queries (placeholders like `?`). This forces developers to use string formatting, which introduces SQL injection risks if the dynamic values are not strictly validated.
**Prevention:** Always validate dynamic values intended for `PRAGMA` commands against a strict allowlist before formatting them into the SQL string.
