## 2024-10-06 - Optimized large directory scanning
**Learning:** Checking for directory types using `os.listdir()` followed by `os.path.isdir()` incurs additional overhead on larger filesystems due to extra internal `stat()` system calls for every element.
**Action:** Use `os.scandir()` as a context manager where `entry.is_dir()` and `entry.is_file()` cache the file attributes resulting in fewer system calls, yielding measurable performance improvements when iterating large collections of directories or log files.
