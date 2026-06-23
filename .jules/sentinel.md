## 2024-06-23 - PRAGMA statement injection via environment variables
**Vulnerability:** A PRAGMA journal_mode statement in `observability_store.py` took an unvalidated environment variable directly into the SQL query string `f'PRAGMA journal_mode={configured_journal_mode}'`, creating a potential SQL injection vector.
**Learning:** Even internal configuration or environment variables must be validated against an allowlist before being injected into raw SQL, especially PRAGMA statements which are evaluated directly by SQLite.
**Prevention:** Use allowlists for any variables that dictate SQL configuration or keywords, as parameterized queries (`?`) cannot be used for PRAGMA values.
