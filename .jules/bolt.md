## 2024-05-24 - [Avoid len([item for item in ...]) when computing lengths]
**Learning:** I found a code pattern where the result of a list comprehension was being passed to len() simply to count the matching items (e.g., len([item for item in handoff_candidates if item['route_kind'] == 'local'])). This creates an intermediate list in memory just to discard it, which is inefficient.
**Action:** Replace len([item for item in ... if ...]) with sum(1 for item in ... if ...) to use a memory-efficient generator expression instead.
