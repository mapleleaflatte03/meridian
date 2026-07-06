## 2026-07-06 - SQL Injection via PRAGMA Statements
**Vulnerability:** SQL injection vulnerability via an environment variable inserted directly into a SQLite PRAGMA journal_mode statement.
**Learning:** SQLite PRAGMA statements do not support parameter binding (?), making direct string formatting vulnerable to SQL injection even if the input comes from environment variables.
**Prevention:** Use a strict allowlist for any dynamic configuration values passed to PRAGMA statements, rather than parameterized queries, to prevent SQL injection attacks.
