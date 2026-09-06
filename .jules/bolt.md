## 2024-09-06 - Replacing os.listdir with os.scandir
**Learning:** Using os.scandir with context manager and variable replacement must ensure variable name does not collide with inner loop variables. Here `entry` collided with json payload `entry = json.load(f)`. While safe in python, it reduces readability.
**Action:** Always check the full scope of a loop when introducing new iterator variable names. Use specific names like `dir_entry` instead of generic `entry`.
