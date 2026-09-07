## 2024-05-24 - SQL Injection in PRAGMA Statements
**Vulnerability:** Arbitrary execution of PRAGMA statements via `MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE` environment variable because SQLite `PRAGMA` statements do not support parameterization.
**Learning:** `PRAGMA` commands in `sqlite3` must be explicitly verified against an allowlist if their values depend on external input because standard parameterization (`?`) does not work for PRAGMAs.
**Prevention:** Always validate external configuration inputs intended for `PRAGMA` setup against a strict allowlist of known safe values (e.g., `WAL`, `DELETE`, `OFF`) before string interpolation.
