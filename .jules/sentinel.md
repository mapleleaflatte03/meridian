## 2024-05-24 - SQL Injection in PRAGMA statement
**Vulnerability:** SQL injection vulnerability via environment variable interpolation into PRAGMA journal_mode statement.
**Learning:** In Python's sqlite3 module, PRAGMA statements do not support parameterized queries (e.g., using `?`). Setting PRAGMA values dynamically from external inputs requires explicit validation.
**Prevention:** Explicitly validate the input against a strict allowlist of allowed values before interpolating it into the PRAGMA string.
