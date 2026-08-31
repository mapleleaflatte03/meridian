import time
import os

CAPSULES_DIR = "kernel"

def test_listdir():
    if not os.path.isdir(CAPSULES_DIR):
        print(f"Skipping, no dir {CAPSULES_DIR}")
        return
    start = time.time()
    dirs = [
        d for d in os.listdir(CAPSULES_DIR)
        if os.path.isdir(os.path.join(CAPSULES_DIR, d))
    ]
    print("os.listdir:", time.time() - start)

def test_scandir():
    if not os.path.isdir(CAPSULES_DIR):
        return
    start = time.time()
    dirs = []
    with os.scandir(CAPSULES_DIR) as it:
        for entry in it:
            if entry.is_dir():
                dirs.append(entry.name)
    print("os.scandir:", time.time() - start)

if __name__ == '__main__':
    test_listdir()
    test_scandir()
