## 2023-10-27 - Fix Path Traversal in Asset Serving
**Vulnerability:** Path traversal vulnerability in `intelligence/meridian_gateway.py`. The `WebAPIAdapter` class used `str(asset_path).startswith(str(assets_root))` to check if a requested asset file was within the `assets` directory.
**Learning:** `startswith` string matching is insufficient for path boundary validation because a sibling directory named `assets_foo` would start with the same prefix as `assets`, allowing unauthorized access to files outside the intended directory.
**Prevention:** Use Python's `pathlib.Path.is_relative_to()` method instead of string prefix matching to ensure cryptographic boundary validation of paths.
