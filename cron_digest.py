"""
Lightweight cron script for Railway.
Called with: python cron_digest.py <period>
Where period is: daily, weekly, or monthly

Requires env vars:
  CRON_SECRET  — shared secret matching the one in the app
  APP_URL      — base URL of the running app (e.g. https://bmm-pos-production.up.railway.app)
"""
import os
import sys
import urllib.request
import urllib.error
import json

def main():
    period = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if period not in ("daily", "weekly", "monthly"):
        print(f"Invalid period: {period}")
        sys.exit(1)

    app_url = os.environ.get("APP_URL", "").rstrip("/")
    cron_secret = os.environ.get("CRON_SECRET", "")

    if not app_url:
        print("ERROR: APP_URL env var not set")
        sys.exit(1)
    if not cron_secret:
        print("ERROR: CRON_SECRET env var not set")
        sys.exit(1)

    url = f"{app_url}/api/v1/notifications/send-sale-digests?period={period}"
    print(f"Calling {url} ...")

    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "X-Cron-Secret": cron_secret,
            "Content-Type": "application/json",
        },
        data=b"",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
            print(f"OK: {body}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"HTTP {e.code}: {body}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
