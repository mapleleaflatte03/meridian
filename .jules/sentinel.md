## 2025-02-14 - Fix SQL injection risk in SQLite PRAGMA journal_mode
**Vulnerability:** SQLite `PRAGMA` statements do not support prepared parameters (`?`), and `journal_mode` was being set via an f-string interpolating an environment variable without strict validation. This allowed potential arbitrary SQL execution.
**Learning:** Even though environment variables are typically trusted, passing them unsanitized into an f-string within `conn.execute()` for a `PRAGMA` statement bypasses the protection usually afforded by parameterized queries.
**Prevention:** Always use strict allowlisting for values injected into `PRAGMA` commands, validating against expected constants (e.g., `WAL`, `DELETE`) before passing them to the database.
