## 2024-09-16 - Optimize directory listing
**Learning:** In Python, `os.listdir()` followed by `os.path.isdir()` on each item generates extra `stat()` system calls. Using `os.scandir()` provides `DirEntry` objects which cache file type information, significantly improving performance when filtering for directories.
**Action:** Use `os.scandir()` instead of `os.listdir()` when iterating over directory contents if you need file type or attributes.
