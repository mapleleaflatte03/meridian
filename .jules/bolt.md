## 2024-08-03 - Avoid O(n^2) list comprehensions for unique items
**Learning:** Found and fixed an O(n^2) performance bottleneck when collecting unique IDs into lists using `if item not in seen_list`. This is a classic anti-pattern that slows down as the list grows.
**Action:** When filtering or accumulating unique items, always use sets (`seen = set()`) and then convert back to a list (`sorted(seen)` or `list(seen)`) if order/formatting requires it.
