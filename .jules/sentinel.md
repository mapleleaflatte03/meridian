## 2024-05-24 - Path Traversal bypass via startswith

**Vulnerability:** Path Traversal bypass in the gateway asset serving route. An attacker could access sibling directories sharing the same prefix name (e.g., `www-secret` instead of `www`) because boundary checks were performed via string prefixes instead of paths.
**Learning:** `str(path).startswith(str(assets_root))` is fundamentally insecure for path constraints. `/app/www-secret/key.txt` starts with `/app/www`, allowing traversal.
**Prevention:** Use `pathlib`'s `is_relative_to(assets_root)` which verifies structural path containment rather than just character prefixes.
