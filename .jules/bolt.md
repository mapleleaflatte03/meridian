## 2024-03-24 - Optimizing directory listing with os.scandir
**Learning:** In the kernel platform code (e.g., `capsule.py`) there is a potential performance optimization. Specifically, in `list_capsules`, using `os.listdir` requires extra `os.path.isdir` stat() calls, which can be optimized with `os.scandir`.
**Action:** Replace `os.listdir` with `os.scandir` in `kernel/kernel/capsule.py` to avoid extra stat() calls when returning directory lists.
