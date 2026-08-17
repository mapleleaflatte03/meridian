## 2024-08-17 - O(N^2) lists in Cases lookup
**Learning:** `blocking_commitment_ids` and `blocked_peer_host_ids` in `cases.py` are iterating with `seen = []` and doing `not in seen` which results in O(N^2) complexity.
**Action:** Replace `seen = []` with `seen = set()` for O(1) containment checks.
