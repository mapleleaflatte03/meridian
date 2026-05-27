## 2024-05-24 - SQL Injection in PRAGMA Statements
**Vulnerability:** SQL injection via environment variable injected into a SQLite PRAGMA statement using f-strings in `observability_store.py`.
**Learning:** SQLite PRAGMA statements do not support parameterized queries (`?`), so dynamic values must be strictly validated against an allowlist, even if they come from configuration or environment variables.
**Prevention:** Always use strict allowlists to validate dynamic inputs to PRAGMA commands before formatting them into SQL strings.
