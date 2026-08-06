## 2024-05-31 - Fix SQL Injection Vulnerability in SQLite PRAGMA journal_mode configuration

**Vulnerability:** A SQL injection vulnerability was found in `intelligence/company/meridian_platform/observability_store.py` where an environment variable (`MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE`) was read and passed directly into a SQLite `PRAGMA journal_mode={...}` query via an f-string without proper validation or parameterization. (Note that SQLite PRAGMA statements do not support standard parameterization, making input validation strictly required).

**Learning:** The vulnerability existed because environment variables were implicitly trusted as configuration inputs, and while standard queries can use parameterized inputs, PRAGMA configuration relies on string interpolation. Since no explicit strict allowlist was in place for the environment variable, a malicious variable could include extra SQL statements (e.g., via semicolons).

**Prevention:** To avoid this in the future, all inputs read from environment variables (or external sources) that are used in statements not supporting standard parameterization (like PRAGMA) must be strictly validated against a hardcoded allowlist of acceptable values before being interpolated.
