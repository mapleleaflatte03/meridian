## 2025-02-12 - Fix SQLite PRAGMA journal_mode Injection
**Vulnerability:** SQL Injection in Python `sqlite3.connect` dynamically setting PRAGMA values based on external inputs (`MERIDIAN_OBSERVABILITY_SQLITE_JOURNAL_MODE`).
**Learning:** Python's sqlite3 API for executing PRAGMA queries does not support parameterized query arguments. Therefore, securely executing a dynamic PRAGMA based on external strings requires a robust allowlist to ensure safe values.
**Prevention:** Avoid executing DDL and PRAGMA queries dynamically based on environment or user inputs. When required, use a strict whitelist and a fallback secure default.
