## 2025-02-27 - SQL Injection in SQLite PRAGMA Configuration
**Vulnerability:** SQL Injection in SQLite PRAGMA journal_mode configuration in observability_store.py via unvalidated environment variable.
**Learning:** Python's sqlite3 module does not support parameterized queries (e.g., using ?) for PRAGMA statements. Using f-strings to inject environment variables directly into PRAGMA statements creates an SQL injection vector.
**Prevention:** When setting PRAGMA values dynamically from external inputs like environment variables, explicitly validate the input against a strict allowlist to prevent SQL injection.
