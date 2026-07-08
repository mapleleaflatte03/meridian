## 2026-07-08 - Fix PRAGMA SQL Injection in SQLite Connection Initialization
**Vulnerability:** The `MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE` environment variable was directly interpolated into a `PRAGMA journal_mode={...}` execution statement in `intelligence/company/meridian_platform/observability_store.py` without strict allowlisting, allowing potential SQL injection.
**Learning:** SQLite PRAGMA statements do not support parameter binding (`?`). Any dynamic configuration passed to them must be validated against a strict allowlist.
**Prevention:** Always use strict allowlists (e.g., `{'DELETE', 'TRUNCATE', 'PERSIST', 'MEMORY', 'WAL'}`) for dynamic configuration values in PRAGMA execution statements.
