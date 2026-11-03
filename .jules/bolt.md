## 2025-02-12 - Optimized O(N^2) Nested Loop in sync_from_economy
**Learning:** Found a classic performance anti-pattern (O(n²) nested loop) inside `kernel/kernel/agent_registry.py` where `sync_from_economy` iterated over all agents and, for each agent, scanned the entire ledger list to match by name. This causes an explosion in execution time as the number of agents and ledger entries grows.
**Action:** Replace nested loops performing lookups with pre-computed hash maps (dictionaries) for O(1) lookups, achieving O(N) complexity instead.
