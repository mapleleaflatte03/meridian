## 2024-05-24 - Fix SQL injection in SQLite PRAGMA configuration
**Vulnerability:** SQLite `PRAGMA` statements configured via unvalidated string concatenation (e.g., `conn.execute(f"PRAGMA journal_mode={mode}")`) allow SQL injection because `PRAGMA` queries do not support parameterized placeholders (`?`).
**Learning:** Environment variables or other input sources used directly in PRAGMA queries bypass the normal SQL parameterization protections.
**Prevention:** Strictly allowlist or validate all values dynamically passed into `PRAGMA` commands.
