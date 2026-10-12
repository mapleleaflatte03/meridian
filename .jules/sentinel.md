## 2026-10-12 - Fix tarfile path traversal vulnerability
**Vulnerability:** tarfile.extractall used without filter (CWE-22) in migration_restore.py
**Learning:** Python's tarfile.extractall is vulnerable to path traversal and arbitrary file overwrite by default. While _is_safe_member attempted validation, adding filter="data" provides a robust, standard-library mitigation to ensure safe extraction.
**Prevention:** Always use filter="data" (introduced in PEP 706) when calling tarfile.extractall in modern Python environments to mitigate path traversal risks automatically.
