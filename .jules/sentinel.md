## 2026-07-03 - Fix SQL Injection in PRAGMA Statement

**Vulnerability:** The SQLite PRAGMA journal_mode statement in observability_store.py directly substituted an environment variable (MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE) into the SQL query without strict validation.
**Learning:** SQLite PRAGMA statements do not support standard parameter binding (?). Therefore, any dynamic configuration values passed to PRAGMA statements must be validated against a strict allowlist.
**Prevention:** Always validate configuration values against a strict allowlist before interpolating them into PRAGMA queries. Do not rely solely on parameter binding if it is unsupported by the specific SQL statement.
