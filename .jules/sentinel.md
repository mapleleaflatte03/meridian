## 2024-05-24 - SQL Injection in SQLite PRAGMA
**Vulnerability:** SQL injection vulnerability in `observability_store.py` where an environment variable is directly interpolated into a `PRAGMA journal_mode` statement.
**Learning:** SQLite PRAGMA statements do not support parameterized queries. Therefore, dynamically setting PRAGMA values via f-strings or string concatenation exposes the application to SQL injection, even if the source is an environment variable.
**Prevention:** Always validate external inputs intended for PRAGMA statements against a strict allowlist of permitted values before interpolation. Ensure the validation preserves original control flow values (like `''` or `'DEFAULT'`).
