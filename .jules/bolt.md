## 2024-05-14 - os.scandir for directory traversal
**Learning:** Using `os.listdir()` creates a list of all files in memory, which is inefficient. Furthermore, checking `isdir()` requires constructing the full path via `os.path.join()`.
**Action:** Use `os.scandir()` which returns an iterator of `os.DirEntry` objects. This avoids full list creation, and the `DirEntry` objects cache file attributes, so checking properties like `is_dir()` and getting `name` or `path` is much faster. Remember to use a `with` statement to ensure the directory file descriptor is closed properly.
