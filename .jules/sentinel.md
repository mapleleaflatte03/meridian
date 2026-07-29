## 2026-07-29 - SQLite PRAGMA Injection Vulnerability
**Vulnerability:** SQL injection via unparameterized PRAGMA interpolation of environment variables (e.g. `MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE`).
**Learning:** PRAGMA statements do not support parameterized queries in sqlite3. Dynamic values interpolated into these statements must be strictly validated.
**Prevention:** Always validate dynamic inputs intended for PRAGMA statements against a strict allowlist of acceptable values before execution.
