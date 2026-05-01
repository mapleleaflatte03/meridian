import time
import copy
import json

cache = {str(i): {'id': i, 'val': i*i, 'nested': {'a': i}} for i in range(100)}

t0 = time.time()
for _ in range(10000):
    _ = copy.deepcopy(cache)
t1 = time.time()

def _fast_copy(obj):
    if isinstance(obj, dict):
        return {k: _fast_copy(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_fast_copy(v) for v in obj]
    elif isinstance(obj, tuple):
        return tuple(_fast_copy(v) for v in obj)
    return obj

t2 = time.time()
for _ in range(10000):
    _ = _fast_copy(cache)
t3 = time.time()

print("copy.deepcopy:", t1 - t0)
print("_fast_copy:", t3 - t2)
