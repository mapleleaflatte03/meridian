## 2024-05-24 - Optimized directory traversal
**Learning:** `os.listdir()` followed by `os.path.isdir()` creates an O(N) performance bottleneck for large directories because it incurs an extra `stat` system call for every single file.
**Action:** Always prefer `os.scandir()` within a `with` context block when filtering directory contents by file type (like `is_file()` or `is_dir()`), as it caches file attributes retrieved during the underlying directory iteration, drastically reducing system call overhead.
