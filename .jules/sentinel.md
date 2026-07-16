## 2026-07-16 - SQL Injection via SQLite PRAGMA configuration
**Vulnerability:** SQL Injection vulnerability due to unsanitized environment variable (`MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE`) passed directly to a PRAGMA statement (`conn.execute(f'PRAGMA journal_mode={configured_journal_mode}')`).
**Learning:** SQLite PRAGMA statements do not support parameter binding (`?`). Passing user input or dynamic environment variables directly to PRAGMA statements is a critical vulnerability.
**Prevention:** Dynamic configuration values for PRAGMA statements must always be validated against a strict allowlist. Include historically permitted fallback values in the allowlist to prevent logic regressions.
