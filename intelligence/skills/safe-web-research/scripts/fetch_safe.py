#!/usr/bin/env python3
"""Safe web fetch script for extracting content from public URLs."""

import sys
import json
import urllib.request
import urllib.error
import re
import gzip
from pathlib import Path

def fetch_url(url: str, timeout: int = 30) -> dict:
    """Fetch content from a URL safely."""
    try:
        # Validate URL
        if not url.startswith(('http://', 'https://')):
            return {"ok": False, "error": "Invalid URL protocol"}
        
        # Make request
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (compatible; Meridian-SafeFetch/1.0)'
            }
        )
        
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw_content = response.read()
            
            # Handle gzip decompression
            if response.getheader('Content-Encoding') == 'gzip':
                try:
                    content = gzip.decompress(raw_content).decode('utf-8', errors='replace')
                except:
                    content = raw_content.decode('utf-8', errors='replace')
            else:
                content = raw_content.decode('utf-8', errors='replace')
            
            # Basic HTML tag removal for text extraction
            text_content = re.sub(r'<[^>]+>', ' ', content)
            text_content = re.sub(r'\s+', ' ', text_content).strip()
            
            return {
                "ok": True,
                "url": url,
                "status_code": response.status,
                "content": text_content[:5000],  # Limit content size
                "content_length": len(text_content)
            }
            
    except urllib.error.HTTPError as e:
        return {
            "ok": False,
            "error": f"HTTP {e.code}: {e.reason}",
            "status_code": e.code
        }
    except urllib.error.URLError as e:
        return {
            "ok": False,
            "error": f"URL error: {e.reason}"
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"Fetch error: {str(e)}"
        }

def main():
    if len(sys.argv) == 2:
        # Positional argument format
        url = sys.argv[1]
    elif len(sys.argv) == 3 and sys.argv[1] == "--url":
        # --url flag format
        url = sys.argv[2]
    else:
        print(json.dumps({"ok": False, "error": "Usage: fetch_safe.py [--url] <url>"}))
        sys.exit(1)
    
    result = fetch_url(url)
    # Return in the format expected by _run_safe_web_fetch
    if result.get("ok"):
        response = {
            "results": [{
                "url": result["url"],
                "status": "success",
                "content_type": "text/html",
                "normalized_text": result["content"]
            }]
        }
    else:
        response = {
            "error": result.get("error", "Unknown error"),
            "results": []
        }
    print(json.dumps(response, indent=2))

if __name__ == "__main__":
    main()
