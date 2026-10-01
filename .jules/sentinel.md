## 2024-10-01 - PRAGMA SQL injection via environment variables
**Vulnerability:** A SQL injection vulnerability was found in `observability_store.py` where the environment variable `MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE` was interpolated directly into a PRAGMA SQL statement.
**Learning:** Python's sqlite3 module does not support parameterized queries for PRAGMA statements. Using f-strings to construct PRAGMA statements from external configuration (even environment variables) can lead to SQL injection.
**Prevention:** Any external input used in PRAGMA statements must be strictly validated against an explicit allowlist before interpolation to prevent SQL injection.
