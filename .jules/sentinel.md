## 2026-07-05 - [SQL Injection Prevention in SQLite PRAGMA]
**Vulnerability:** Found a potential SQL injection where the `MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE` environment variable was directly interpolated into a `PRAGMA journal_mode={...}` execution statement in `observability_store.py`.
**Learning:** SQLite PRAGMA statements do not support `?` parameterization. Consequently, any dynamic configuration values passed to them are susceptible to injection attacks if not carefully restricted.
**Prevention:** Always validate dynamic PRAGMA values against a strict allowlist of known, safe options before interpolating them into SQL execution strings.
