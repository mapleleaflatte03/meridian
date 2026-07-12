## 2026-07-12 - O(N^2) List Lookups Avoidance
**Learning:** Found O(N^2) list containment checks `item not in seen` within loops where `seen` is an array. This becomes a performance bottleneck for large inputs. Using `set()` brings lookups to O(1) and overall complexity down to O(N).
**Action:** Always initialize deduplication collections as sets (`seen = set()`) and use `.add()` instead of arrays and `.append()`. `sorted(seen)` will correctly output a list.
