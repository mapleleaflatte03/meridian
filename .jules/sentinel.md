## 2024-05-24 - SQL Injection in PRAGMA Statement
**Vulnerability:** SQL injection vulnerability found in PRAGMA journal_mode configuration due to unparameterized string interpolation of environment variables.
**Learning:** Python's sqlite3 module doesn't support parameterized queries for PRAGMA statements. Using negative validation (not in) instead of an explicit allowlist allows arbitrary strings to be interpolated, posing an injection risk.
**Prevention:** Always use a strict positive allowlist for dynamic PRAGMA statements, preserving previously valid or ignored options like 'DEFAULT' or '' in the validation logic to avoid behavioral regressions.
