## 2024-10-27 - Path Traversal Vulnerability in Asset Serving
**Vulnerability:** Path traversal vulnerability due to string prefix matching for path boundaries.
**Learning:** Using `str(path).startswith(str(root))` allows path traversals because it only checks for a string prefix, not a directory boundary. If `root` is `/var/www/assets`, `path` being `/var/www/assets_secret/key.txt` would match.
**Prevention:** Use `pathlib.Path.is_relative_to(root)` to securely validate directory boundaries in Python.
