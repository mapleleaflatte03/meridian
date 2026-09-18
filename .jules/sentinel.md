## 2024-11-20 - Unparameterized PRAGMA Statements
**Vulnerability:** SQL Injection in SQLite PRAGMA configuration due to injecting environment variables directly into a formatted SQL string.
**Learning:** Python's sqlite3 driver does not support parameterized queries (e.g., `?`) for PRAGMA statements, which makes developers resort to string interpolation, increasing SQL injection risks.
**Prevention:** Whenever dynamic values are needed in PRAGMA statements, strictly validate the input against a hardcoded positive allowlist of acceptable values before interpolating them into the SQL string.
