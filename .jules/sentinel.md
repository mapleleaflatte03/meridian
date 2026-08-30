## 2024-05-24 - [Fix PRAGMA SQL injection in observability_store]
**Vulnerability:** SQL injection vulnerability in `observability_store.py` where `MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE` environment variable was directly injected into a `PRAGMA journal_mode=` statement without checking against a strict allowlist.
**Learning:** PRAGMA statements do not support parameterized queries (e.g., using `?`). When setting PRAGMA values dynamically from external inputs (like environment variables), you must explicitly validate the input against a strict allowlist to prevent SQL injection.
**Prevention:** Always use a strict allowlist of valid string values for PRAGMA options when they derive from external inputs, instead of trusting `.upper()` or similar weak sanitization.
