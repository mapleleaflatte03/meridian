
## 2024-05-18 - Optimize directory traversal

**Learning:** When trying to find files or subdirectories in a directory, `os.scandir` combined with `entry.is_dir()` or `entry.is_file()` is significantly faster than using `os.listdir` and `os.path.isdir(os.path.join(path, name))`. This is because `os.scandir` yields `os.DirEntry` objects which have file type attributes cached, meaning an extra `stat` call doesn't need to be performed. This speeds up traversing large capsule directories.
**Action:** When working in Python code that iterates over directory items and needs to know file types, always refactor `os.listdir` + `os.path.isdir`/`isfile` to use `os.scandir`.
