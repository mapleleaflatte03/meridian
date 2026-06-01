## 2025-02-24 - SQL Injection in SQLite PRAGMA Statements
**Vulnerability:** SQL injection vulnerability via an unvalidated environment variable used in a SQLite PRAGMA statement (`conn.execute(f'PRAGMA journal_mode={...}')`).
**Learning:** PRAGMA commands do not support parameterized queries (`?`), so any dynamic values injected into them must be strictly validated against an allowlist, but validation must preserve special control values (like `''` or `'DEFAULT'`) used for bypass logic.
**Prevention:** Always validate dynamic values in PRAGMA statements against a strict allowlist before execution.
