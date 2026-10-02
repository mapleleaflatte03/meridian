## 2024-10-02 - PRAGMA SQL Injection in SQLite Connection
**Vulnerability:** SQL injection vulnerability in `conn.execute(f'PRAGMA journal_mode={...}')` because environment variable inputs were inserted without strict validation.
**Learning:** SQLite's PRAGMA statements do not support parameterized queries (e.g., `?`). This forces string formatting, making it vulnerable to injection if the string comes from an untrusted source like an environment variable.
**Prevention:** Always enforce a strict, positive allowlist before substituting dynamic values into PRAGMA statements.
