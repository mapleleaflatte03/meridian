## 2026-07-12 - SQLite PRAGMA SQL Injection
**Vulnerability:** SQL injection vulnerability in PRAGMA statements due to lack of parameterized query support for PRAGMA arguments.
**Learning:** SQLite PRAGMA statements do not support parameter binding (e.g. `?`). Dynamic configuration values passed to PRAGMA statements must be validated against a strict allowlist.
**Prevention:** Always validate dynamic inputs against an allowlist before using them in PRAGMA execution queries.
