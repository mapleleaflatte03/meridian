## 2024-11-01 - Path Traversal Vulnerability in Static File Serving
**Vulnerability:** The static file serving routes in `meridian_gateway.py` use string prefix matching (`str(asset_path).startswith(str(assets_root))`) to restrict access to the `/assets/` directory.
**Learning:** This is vulnerable to Path Traversal because string prefix matching allows access to sibling directories sharing the same prefix (e.g., `/app/company/www_secret/`).
**Prevention:** Use `Path.is_relative_to(target_directory)` instead of `str(path).startswith(...)` to correctly and safely validate directory boundaries.
