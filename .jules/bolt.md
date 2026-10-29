## 2024-05-24 - Deferring parsing in log files
**Learning:** When retrieving only the tail end of large log files, running `json.loads` on all lines before slicing them causes significant and unnecessary performance and memory overhead.
**Action:** Use `collections.deque(maxlen=tail)` to accumulate valid unparsed lines, and only parse the resulting small subset.
