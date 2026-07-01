## 2026-07-01 - Secure SQLite PRAGMA Configuration
**Vulnerability:** Unvalidated environment variables were being directly injected into SQLite PRAGMA queries (e.g., `PRAGMA journal_mode={value}`), introducing a potential SQL injection vector.
**Learning:** SQLite PRAGMA statements do not support standard parameter binding (?), meaning dynamic configuration values must be validated against a strict allowlist to be safe.
**Prevention:** Always validate configuration values intended for PRAGMA statements against a known allowlist before string interpolation, while taking care to preserve expected control-flow values like '' or 'DEFAULT'.
