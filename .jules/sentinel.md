## 2026-07-20 - Fix PRAGMA SQL injection vulnerability
**Vulnerability:** Unsanitized environment variable (`MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE`) was interpolated directly into a `PRAGMA journal_mode=` SQL statement in `observability_store.py`.
**Learning:** Even though `sqlite3`'s `execute` method restricts to single statements, unvalidated string interpolation into SQL queries creates a risk if the API usage ever changes (e.g., switching to `executescript`) or behavior updates.
**Prevention:** Always use strict allowlists to validate user or environment inputs that must be directly embedded in SQL (since `PRAGMA` values cannot typically be parameterized). Include fallback bypass values like `''` or `'DEFAULT'` in the allowlist to maintain historical logical parity.
