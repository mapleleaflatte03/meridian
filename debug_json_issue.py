path = "intelligence/scripts/acceptance_publish_live_lane.sh"
with open(path, "r") as f:
    content = f.read()

import re
matches = re.finditer(r"python3 - <<'PY'(.*?)PY\n", content, re.DOTALL)
for i, match in enumerate(matches):
    print(f"--- Block {i+1} ---")
    lines = match.group(1).strip().split('\n')
    for j, line in enumerate(lines):
        if "json.loads" in line:
            print(f"Line {j+1}: {line}")
