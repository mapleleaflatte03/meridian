## 2024-06-03 - Performance issue with copy.deepcopy()
**Learning:** Found multiple instances of `copy.deepcopy()` in the codebase. However, a custom `_fast_deepcopy` implementation that bypasses Python's internal aliasing logic introduced critical regressions by improperly un-aliasing shared references and breaking custom object types. We must not reinvent deepcopy for complex data structures because speed without correctness is useless.
**Action:** Avoid micro-optimizations that fundamentally bypass deep, semantic language mechanics. Focus on caching or O(n) improvements.
