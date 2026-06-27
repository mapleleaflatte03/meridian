## 2026-06-27 - SQLite PRAGMA Injection Vulnerability via Environment Variable
**Vulnerability:** SQLite PRAGMA journal_mode configuration was vulnerable to SQL injection because it accepted unvalidated input from the MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE environment variable directly into an f-string executed against the database.
**Learning:** SQLite PRAGMA statements do not support parameter binding (?). Any dynamic configuration values passed to PRAGMA statements must be explicitly validated against a strict allowlist to prevent SQL injection attacks.
**Prevention:** Always validate external inputs meant for PRAGMA or schema modification commands against a strict allowlist before execution, while ensuring special control values used by application logic are preserved.
