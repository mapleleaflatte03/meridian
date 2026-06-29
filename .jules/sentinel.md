## 2026-06-29 - SQLite PRAGMA parameter injection
**Vulnerability:** A PRAGMA statement in `observability_store.py` interpolates a user-controlled environment variable directly into the query, potentially leading to a SQLite PRAGMA injection since parameter binding `?` isn't supported for PRAGMAs.
**Learning:** External or environment-based values must never be directly interpolated into SQL or PRAGMA commands.
**Prevention:** Dynamic configuration values passed to PRAGMA statements must be validated against a strict allowlist rather than parameterized queries, to prevent SQL injection attacks.
