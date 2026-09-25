## 2025-01-20 - Prevent SQL Injection via PRAGMA string concatenation
**Vulnerability:** A `PRAGMA journal_mode={configured_journal_mode}` string was being executed where `configured_journal_mode` came directly from an environment variable without strict validation.
**Learning:** Relying on string concatenation for SQL PRAGMAs can be dangerous since PRAGMA values cannot be parametrized securely using standard `?` syntax.
**Prevention:** Always use strict positive allowlists for configuring PRAGMA parameters derived from environment variables.
