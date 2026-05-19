## 2024-05-19 - PRAGMA SQL Injection Risk
**Vulnerability:** SQL injection vulnerability via unvalidated environment variable used in `PRAGMA journal_mode` string formatting.
**Learning:** `PRAGMA` commands in SQLite do not support parameterized queries (`?`), so dynamic values must use string formatting, which introduces injection risks if not strictly allowlisted.
**Prevention:** Always validate dynamic values for `PRAGMA` statements against a strict allowlist before formatting them into the query.
