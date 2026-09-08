## 2024-09-08 - PRAGMA SQL Injection via Environment Variable
**Vulnerability:** A SQLite PRAGMA statement in `observability_store.py` dynamically interpolated an unvalidated environment variable (`MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE`), allowing for potential SQL injection.
**Learning:** In Python's `sqlite3` module, `PRAGMA` statements do not support parameterized queries (e.g., `?`). Therefore, when setting them dynamically from external inputs, they are highly susceptible to injection if not strictly validated.
**Prevention:** Always validate external inputs intended for `PRAGMA` statements against a strict, explicit allowlist (including edge cases like `''` or `'DEFAULT'`) before string interpolation.
