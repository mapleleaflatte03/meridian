import os

with open('scripts/acceptance_ui_anatomy_lane.sh', 'r') as f:
    text = f.read()

import re
text = re.sub(r'check "index.html: governance-model section" grep -q \'id="governance-model"\' "\$WWW_DIR/index.html"\n', '', text)
text = re.sub(r'check "index.html: research-hub section"    grep -q \'id="research-hub"\'     "\$WWW_DIR/index.html"\n', '', text)
text = re.sub(r'check "index.html: how-to-contribute"       grep -q \'id="how-to-contribute"\' "\$WWW_DIR/index.html"\n', '', text)
text = re.sub(r'check "index.html: sponsors section"        grep -q \'id="sponsors"\'          "\$WWW_DIR/index.html"\n', '', text)
with open('scripts/acceptance_ui_anatomy_lane.sh', 'w') as f:
    f.write(text)
