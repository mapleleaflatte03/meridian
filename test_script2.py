import urllib.request

req = urllib.request.Request("https://app.welliam.codes/api/status")
# We need to add a user-agent to avoid Cloudflare 403 1010 code maybe?
req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3')
try:
    with urllib.request.urlopen(req, timeout=20) as response:
        print(response.status, response.read().decode("utf-8", "ignore"))
except Exception as e:
    print(e)
