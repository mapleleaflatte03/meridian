## 2024-07-28 - SQLite PRAGMA Injection via Environment Variables
**Vulnerability:** SQL injection vulnerability found in `intelligence/company/meridian_platform/observability_store.py` where an environment variable (`MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE`) is directly interpolated into a `PRAGMA journal_mode={}` statement.
**Learning:** PRAGMA statements do not support parameterized queries (`?`), leading developers to mistakenly use f-strings or concatenation. If the value comes from an untrusted or unverified source (like an environment variable), it can lead to SQL injection.
**Prevention:** When dynamically setting PRAGMA values, always strictly validate the input against an explicit allowlist of acceptable values before executing the statement.
