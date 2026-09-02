## 2024-05-24 - Prevent SQL injection in SQLite PRAGMA journal_mode
**Vulnerability:** SQL injection vulnerability via `os.environ.get('MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE')` passed unsanitized into a `PRAGMA journal_mode={...}` statement.
**Learning:** PRAGMA statements do not support parameterized queries (e.g., using `?`). Dynamic inputs must be explicitly validated against a strict allowlist. Ensure handled edge cases (like `''` or `'DEFAULT'`) are included to avoid breaking subsequent conditional logic.
**Prevention:** Use an allowlist for all dynamic values in PRAGMA statements instead of trusting external input or blindly passing them to the database.
