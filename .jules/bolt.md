## 2024-10-27 - Optimize JSON File Log Reading
**Learning:** `JsonFileBackend.read_log` reads the entire JSONL file into memory, even when `tail` is specified. For large log files, this could lead to huge memory spikes. Using `collections.deque(maxlen=tail)` prevents the unbounded memory accumulation and allows returning just the last few items in O(1) memory.
**Action:** Use `collections.deque(maxlen=N)` for limiting arrays when iterating over streams or lines of text to prevent loading unneeded objects into memory. Ensure we accumulate *parsed and filtered* data into the deque.
