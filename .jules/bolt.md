## 2026-07-28 - Handle Missing Directories and Permissions Gracefully in Tests

**Learning:** When tests execute code that probes the environment (e.g. `meridian_gateway.py` looking for `/home/ubuntu/...`), Python's `Path.exists()` may throw a `PermissionError` instead of returning `False`. This halts tests unexpectedly on environments with strict permissions like GitHub Actions runners, masking other legitimate issues.

**Action:** Whenever introducing iterative directory checks via `exists()` or similar commands over a list of hardcoded system paths, always catch `PermissionError` and safely fall back.
