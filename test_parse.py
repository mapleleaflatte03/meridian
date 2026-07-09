import datetime
ts = "2026-07-09T19:30:35.1528477"
parsed = datetime.datetime.fromisoformat(ts.replace('Z', '+00:00'))
print("tzinfo:", parsed.tzinfo)
