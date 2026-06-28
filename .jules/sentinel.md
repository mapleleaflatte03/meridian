## 2026-06-28 - SQL Injection via SQLite PRAGMA configuration
**Vulnerability:** SQL injection vulnerability in observability_store.py via the MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE environment variable, which was directly formatted into a `PRAGMA journal_mode={}` query.
**Learning:** SQLite PRAGMA statements do not support standard parameter binding (`?`). Dynamic configuration values passed to PRAGMA statements must be validated against a strict allowlist.
**Prevention:** Always use a strict allowlist for PRAGMA statements and ensure validation logic correctly handles bypassing/control values like 'DEFAULT' without overwriting them.
