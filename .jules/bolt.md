## 2026-06-16 - Python List Slicing Precedence Bug
**Learning:** When removing unnecessary list() copies before slicing in Python (e.g., optimizing `list(data.get('key') or [])[:N]`), omitting parentheses causes the slice to bind exclusively to the `[]` fallback due to operator precedence, creating a subtle functional regression.
**Action:** Always wrap expressions involving boolean fallback in parentheses, like `(data.get('key') or [])[:N]`, before applying slice operators.
