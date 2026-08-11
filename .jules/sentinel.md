## 2023-10-27 - Prevent SQL injection via PRAGMA statements
**Vulnerability:** SQLite `PRAGMA` statements do not support parameterized queries. The application dynamically constructed `PRAGMA journal_mode` using an environment variable without strict validation against an allowlist, posing a risk of SQL injection.
**Learning:** Even internal configuration settings sourced from environment variables can be leveraged for injection attacks if directly concatenated into raw SQL, especially when parameterization isn't supported by the database engine for that specific statement type.
**Prevention:** Always validate dynamic input used in `PRAGMA` statements against a strict allowlist of known-safe values before executing the query.
