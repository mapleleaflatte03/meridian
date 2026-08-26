## 2024-08-26 - Prevent PRAGMA SQL Injection
**Vulnerability:** SQL injection via unsanitized environment variable in PRAGMA statement.
**Learning:** In Python's sqlite3 module, PRAGMA statements do not support parameterized queries, making them vulnerable if dynamically constructed from environment variables.
**Prevention:** Strictly validate inputs against an explicit allowlist before using them in PRAGMA queries.
