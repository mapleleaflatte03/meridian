## 2026-06-26 - PRAGMA SQL Injection
**Vulnerability:** SQL injection via unsanitized environment variable interpolated into SQLite PRAGMA journal_mode statement.
**Learning:** SQLite PRAGMA statements do not support parameter binding (`?`), making them vulnerable if dynamic inputs are used.
**Prevention:** Always validate dynamic configuration values passed to PRAGMA statements against a strict allowlist.
