## 2025-02-23 - Memory limit on JsonFileBackend.read_log
**Learning:** For large JSONL files, loading the entire file into a list before slicing `entries[-tail:]` causes O(N) memory consumption, which is particularly bad for unbounded logs like `audit.jsonl`.
**Action:** Use `collections.deque(maxlen=tail)` to naturally limit memory footprint to O(tail) directly during the append phase. This acts as a bounded sliding window without altering processing semantics.
