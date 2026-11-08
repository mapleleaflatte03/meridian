## 2024-05-15 - Path Traversal via String Prefix Matching
**Vulnerability:** File serving routes used `str(path).startswith()` to check if a requested file was within the allowed `assets` directory.
**Learning:** `startswith()` is insecure for path validation because it only checks string prefixes. A path like `/assets_secret/file` starts with `/assets`, bypassing the check and allowing access to sibling directories.
**Prevention:** Always use `pathlib.Path.is_relative_to()` to validate that a path is strictly within a target directory boundary.
