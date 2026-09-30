#!/bin/bash
sed -i 's/BASE = "https:\/\/app.welliam.codes"/import os\nBASE = f"http:\/\/127.0.0.1:{os.environ.get('"'"'MERIDIAN_MOCK_PORT'"'"')}"/' intelligence/scripts/acceptance_publish_live_lane.sh
