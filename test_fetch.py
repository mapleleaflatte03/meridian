import urllib.request
import urllib.error

BASE = "https://app.welliam.codes"

try:
    req = urllib.request.Request(BASE + "/api/status")
    with urllib.request.urlopen(req, timeout=20) as response:
        print(response.status)
        print(response.read().decode("utf-8", "ignore"))
except urllib.error.HTTPError as e:
    print(f"HTTP Error: {e.code}")
    print(e.read().decode("utf-8", "ignore"))
except Exception as e:
    print(f"Error: {e}")
