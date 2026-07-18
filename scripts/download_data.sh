#!/usr/bin/env bash
# scripts/download_data.sh — download 15m Kraken history for the backtest.
# Kraken's candle API only serves ~720 recent candles, so freqtrade must
# rebuild candles from raw trades (--dl-trades). This is SLOW (hours; Kraken
# rate-limits). Run it overnight; it is resumable — rerunning skips finished pairs.
set -euo pipefail
cd "$(dirname "$0")/.."

TIMERANGE="${1:-20260101-20260715}"

docker compose run --rm freqtrade download-data \
  --config /freqtrade/config-paper.json \
  --pairs-file /freqtrade/user_data/pairs_usd.json \
  -t 15m \
  --dl-trades \
  --timerange "$TIMERANGE"
