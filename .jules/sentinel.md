## 2024-05-18 - Fix Path Traversal in Asset Gateway
**Vulnerability:** Path traversal vulnerability in `meridian_gateway.py` when serving static assets (using `str(path).startswith(str(root))`).
**Learning:** Checking path validity via string prefix matching is insecure because a sibling directory could share the same string prefix. This allows attackers to access files outside the intended root.
**Prevention:** Use `Path.is_relative_to()` to ensure file requests cannot traverse outside the target root directory boundaries.
