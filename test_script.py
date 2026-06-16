import urllib.request
import urllib.error

BASE = "https://app.welliam.codes"

try:
    req = urllib.request.Request(BASE + "/api/status")
    with urllib.request.urlopen(req, timeout=20) as response:
        print(response.status, response.read().decode("utf-8", "ignore"))
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode("utf-8", "ignore"))
