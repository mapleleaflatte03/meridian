#!/bin/bash
# Pass MERIDIAN_MOCK_PORT to the python script block.
sed -i 's/python3 - <<'"'"'PY'"'"'/MERIDIAN_MOCK_PORT="${MOCK_PORT}" python3 - <<'"'"'PY'"'"'/' intelligence/scripts/acceptance_publish_live_lane.sh
