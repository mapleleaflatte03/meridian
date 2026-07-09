## 2026-07-09 - Fix SQL injection in SQLite PRAGMA journal_mode
**Vulnerability:** SQL injection vulnerability in `observability_store.py` due to using an unvalidated environment variable directly inside a `PRAGMA journal_mode` f-string execution.
**Learning:** SQLite PRAGMA statements do not support parameter binding (`?`), so it's impossible to pass dynamic configurations safely using standard parameterized queries. Instead, when a dynamic value is required for PRAGMA statements, it must be validated against a strict allowlist to prevent SQL injection.
**Prevention:** Always validate dynamic configuration inputs against a strict allowlist before constructing PRAGMA queries using string formatting.
