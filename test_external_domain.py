import urllib.request
BASE = "https://app.welliam.codes"
try:
    req = urllib.request.Request(BASE + "/api/status")
    with urllib.request.urlopen(req, timeout=10) as response:
        print("Status:", response.status)
except Exception as e:
    print("Error:", e)
