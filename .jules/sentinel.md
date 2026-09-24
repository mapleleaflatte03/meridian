## 2025-01-20 - Unsanitized Environment Variables in SQLite PRAGMA

**Vulnerability:** SQL injection vulnerability in `observability_store.py` where an unsanitized environment variable (`MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE`) was interpolated directly into a SQLite PRAGMA execution statement (`PRAGMA journal_mode={...}`).
**Learning:** Python's `sqlite3` driver does not support parameterized queries (`?`) for PRAGMA statements. Any external inputs (even environment variables) used in PRAGMAs must be handled as strings, creating a silent injection risk if not strictly validated.
**Prevention:** Always validate external inputs destined for PRAGMA statements against a strict positive allowlist of acceptable values (e.g., `{'WAL', 'DELETE', ...}`) before executing the string interpolation.
