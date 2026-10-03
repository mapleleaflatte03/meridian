## 2024-05-24 - PRAGMA SQL Injection Pattern
**Vulnerability:** SQL Injection in SQLite PRAGMA statements via environment variables (e.g. `MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE`).
**Learning:** Python's sqlite3 module does not support parameterized queries (`?`) for PRAGMA statements. Using string interpolation without strict allowlist validation allows SQL injection if the input source is externally controllable (like an environment variable).
**Prevention:** Always validate external inputs against an explicit allowlist (e.g. `{'DELETE', 'TRUNCATE', 'PERSIST', 'MEMORY', 'WAL', 'OFF', '', 'DEFAULT'}`) before interpolating them into a PRAGMA SQL statement.
