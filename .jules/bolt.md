## 2024-06-25 - Python Performance Optimizations with os.scandir
**Learning:** Replacing `os.listdir()` with `os.scandir()` is an effective performance improvement for directory traversal. It returns an iterator of `os.DirEntry` objects, which caches file attributes like `is_dir()` and avoids memory overhead for large directories.
**Action:** Always wrap `os.scandir()` in a `with` context manager to avoid ResourceWarnings. Ensure proper re-indentation of subsequent block logic when introducing the context manager via string replacement to avoid IndentationError.
