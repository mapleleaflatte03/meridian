## 2024-05-18 - Fix Path Traversal via String Prefix Checking
**Vulnerability:** Path boundary validation used `str(asset_path).startswith(str(assets_root))` which is insecure and allows directory traversal if a sibling directory shares the same prefix.
**Learning:** Python's `str.startswith()` does not validate structural path boundaries. An attacker can access files in a directory like `/assets_hidden` if the intended boundary is `/assets`.
**Prevention:** Always use `pathlib.Path.is_relative_to()` to validate that a path properly exists within a target directory structure.
