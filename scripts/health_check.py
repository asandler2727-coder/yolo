#!/usr/bin/env python3
"""Daily dry-run health check (spec §5: zero trades in 48h = fault).
Usage: FT_PASS=... python3 scripts/health_check.py
Requires: pip install freqtrade-client"""
import os
import sys
from datetime import datetime, timedelta, timezone

from freqtrade_client import FtRestClient

client = FtRestClient("http://127.0.0.1:8080", "yolo", os.environ["FT_PASS"])
state = client.show_config()
print(f"Bot state: {state['state']}, dry_run: {state['dry_run']}")
whitelist = client.whitelist()
print(f"Watching {whitelist['length']} pairs: {', '.join(whitelist['whitelist'][:10])}...")

trades = client.trades(limit=100)
cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
recent = [t for t in trades.get("trades", [])
          if datetime.fromisoformat(t["open_date"].replace("Z", "+00:00")) > cutoff]
open_count = client.count().get("current", 0)
print(f"Open trades: {open_count}; trades opened in last 48h: {len(recent)}")

if not recent and not open_count:
    print("FAULT: zero trades in 48h — investigate today (spec §5). "
          "Check whitelist churn, threshold too strict, or bot stalled.")
    sys.exit(1)
print("OK")
