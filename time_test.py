import time
import os
from intelligence.company.meridian_platform.scheduler_truth import RECURRING_RUNS_DIR

def test_listdir():
    if not os.path.isdir(RECURRING_RUNS_DIR):
        print(f"Skipping, no dir {RECURRING_RUNS_DIR}")
        return
    start = time.time()
    for name in os.listdir(RECURRING_RUNS_DIR):
        pass
    print("os.listdir:", time.time() - start)

def test_scandir():
    if not os.path.isdir(RECURRING_RUNS_DIR):
        return
    start = time.time()
    with os.scandir(RECURRING_RUNS_DIR) as it:
        for entry in it:
            pass
    print("os.scandir:", time.time() - start)

if __name__ == '__main__':
    test_listdir()
    test_scandir()
