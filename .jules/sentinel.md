## 2024-05-24 - Fix PRAGMA SQL injection vulnerability
**Vulnerability:** SQL injection vulnerability in SQLite PRAGMA journal_mode due to unsanitized external input (environment variables).
**Learning:** In Python's sqlite3 module, PRAGMA statements do not support parameterized queries (e.g., using ?).
**Prevention:** When setting PRAGMA values dynamically from external inputs, explicitly validate the input against a strict allowlist. Ensure the allowlist includes explicitly handled edge cases to avoid breaking existing functionality.
