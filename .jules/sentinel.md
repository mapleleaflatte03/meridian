## 2026-06-24 - PRAGMA SQL Injection Risk
**Vulnerability:** Dynamic configuration values were passed directly into a SQLite PRAGMA statement, creating a potential SQL injection risk.
**Learning:** SQLite PRAGMA statements do not support parameter binding (?), meaning dynamic inputs must be validated manually.
**Prevention:** Always use a strict allowlist to validate dynamic inputs for PRAGMA statements, ensuring special control values (e.g., '', 'DEFAULT') are preserved to prevent logical regressions.
