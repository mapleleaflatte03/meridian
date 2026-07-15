## 2026-07-15 - Strict allowlist for PRAGMA statements
**Vulnerability:** SQL injection risk in SQLite PRAGMA journal_mode via unvalidated environment variables.
**Learning:** SQLite PRAGMA statements do not support parameter binding (?). Dynamic configuration values passed to PRAGMA must be validated against a strict allowlist.
**Prevention:** Always use strict allowlists (including historical fallbacks like '' or 'DEFAULT') to sanitize dynamic input before injecting it into PRAGMA statements.
