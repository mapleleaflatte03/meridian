## 2026-07-10 - Strict Allowlist for SQLite PRAGMA Statements
**Vulnerability:** Unvalidated environment variables were injected directly into a SQLite PRAGMA statement via f-string (`conn.execute(f'PRAGMA journal_mode={val}')`).
**Learning:** SQLite PRAGMA statements do not support parameter binding (`?`). Dynamic configuration values passed to PRAGMA statements must be validated against a strict allowlist to prevent SQL injection.
**Prevention:** Always use a predefined set of allowed values for dynamic PRAGMA values instead of passing variables directly or trying to parameterize them.
