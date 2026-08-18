## 2024-05-18 - Fix PRAGMA SQL injection vulnerability
**Vulnerability:** SQL injection vulnerability in `observability_store.py` via `PRAGMA journal_mode={configured_journal_mode}` where `configured_journal_mode` is taken from an environment variable without strict validation.
**Learning:** PRAGMA statements in Python's sqlite3 do not support parameterized queries (e.g. `?`), making them susceptible to injection if user or external inputs are concatenated directly.
**Prevention:** Strictly validate dynamically generated PRAGMA values against an explicit allowlist of acceptable values before execution to prevent SQL injection.
