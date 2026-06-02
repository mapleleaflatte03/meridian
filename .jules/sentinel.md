## YYYY-MM-DD - SQL Injection in SQLite PRAGMA Statements
**Vulnerability:** Environment variables were interpolated directly into `PRAGMA` SQL statements without validation in `observability_store.py`, risking SQL injection since SQLite `PRAGMA` commands don't support parameterized queries.
**Learning:** Dynamic values passed to `PRAGMA` commands must be manually validated against strict allowlists because standard query parametrization (`?`) cannot be used.
**Prevention:** Always validate external inputs strictly against an allowlist of valid string values when constructing SQL PRAGMA statements.
