## 2024-05-23 - Dynamic PRAGMA Statement SQL Injection
**Vulnerability:** SQL injection vulnerability via dynamically constructed PRAGMA statements with unvalidated environment variables.
**Learning:** SQLite PRAGMA commands in Python do not support parameterized queries (like `?`), making them susceptible to injection if interpolated using f-strings.
**Prevention:** Always validate values dynamically included in PRAGMA statements against a strict allowlist before executing them.
