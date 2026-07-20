# v2 Out-of-Sample Validation (Apr–Jul) Run Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to run this task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This is an operations/validation plan — most steps run existing, tested code; only Task 0 created new code (already TDD'd).

**Goal:** When the Apr–Jul Kraken download finishes, repair the candle store, run the v2 out-of-sample rolling backtest honestly, and present the combined in-sample + OOS picture to Austin for his direction call.

**Architecture:** The gap-fill download (`--dl-trades`) ends with a conversion phase that **overwrites** each pair's 15m feather with candles built only from stored trades (verified in freqtrade 2026.4 source: `ohlcv_store(data=ohlcv)`, no merge). Most gap-pair trades start 2026-04-01, so conversion wipes Jan–Mar candles. We back up first (done), merge after, verify coverage, then run the existing tested harness.

**Tech Stack:** freqtrade 2026.4 (Docker), pandas via `.venv`, `scripts/rolling_backtest.py` (stdout-parse result selection — do not revert to `.last_result.json`), `scripts/verify_regime_gating.py`, `scripts/merge_15m_backup.py`.

## Global Constraints

- Spec §6/§8 hard rules never weakened: `"dry_run": true`, $750 / 3×$250 cap, protections on, `--enable-protections`, $250k/day volume floor in ranking.
- `--fee 0.004` (Kraken taker) on every backtest.
- **No tuning, no grid search, no param changes before or during the OOS run.** Apr–Jul is reserved OOS; touching params on it burns its OOS status.
- Amended gate: positive total profit AND ≥5 trades/week **in up-regime periods only** (zero-trade bear stretches are compliant). The harness's built-in `gate_pass` uses overall trades/week — apply the amended interpretation in the write-up; do not edit the tested harness for this.
- No deploy, no live keys, no `config-live.json`. Every terminal branch of this plan ends at "STOP and report to Austin."
- Do not kill the running download (wrapper PID ~42820; sequence: 46-pair full-range DONE → 582-pair gap-fill RUNNING).

## Current state (verified 2026-07-20 ~03:00 UTC)

- Download at XLM/USD, index 554/582 (~27 pairs left, ~1–2 h) + conversion phase after (~10–30 min). Sentinel line when fully done: `=== ALL DOWNLOADS COMPLETE ===` in `user_data/download_narrowed.log`.
- Background monitor armed on that log (completion / conversion-start / stall / wrapper-death).
- **Backup taken:** `user_data/data/kraken_15m_backup_20260720/` — 628 feathers, 710 MB, all ending 2026-03-31 23:45 (gap pairs) or full-range (the 46 new pairs).
- Fallback source intact: `~/Downloads/master_q4/` bulk CSVs (12,027 files) + `scripts/convert_kraken_ohlcvt.py`.
- `scripts/merge_15m_backup.py` written and tested (union / restore-missing / live-wins-overlap all pass).
- `.venv/bin/pytest tests/` → 17 passed. Disk: 1.3 TB free.
- In-sample record (do not re-run): v2 Feb–Mar = 36 trades, −8.36%, 5.40% max DD, all 36 entries in up-regime, gate FAIL on profit (`docs/backtests.md`).

---

### Task 0: Pre-completion safeguards — DONE

- [x] Back up all 15m feathers before the conversion phase (628 files → `kraken_15m_backup_20260720/`)
- [x] Write + test `scripts/merge_15m_backup.py` (3 synthetic cases pass)
- [x] Confirm bulk-CSV fallback exists (`~/Downloads/master_q4`, 12,027 CSVs)
- [x] Arm log monitor; confirm test suite green (17 passed)

### Task 1: Confirm the download finished clean

**Files:** read-only: `user_data/download_narrowed.log`

- [ ] **Step 1: Wait for the monitor event** (or check manually):

```bash
grep -c "ALL DOWNLOADS COMPLETE" user_data/download_narrowed.log   # expect 1
grep -c "About to convert pairs" user_data/download_narrowed.log   # expect 2 (46-pair run + gap-fill run)
grep -ciE "error|exception" user_data/download_narrowed.log        # expect small; inspect any hits
```

- [ ] **Step 2: Spot-check that conversion actually rewrote candles** (BTC now extends past Mar 31 but likely lost Jan–Mar):

```bash
.venv/bin/python -W ignore -c "
import pandas as pd
df = pd.read_feather('user_data/data/kraken/BTC_USD-15m.feather')
d = pd.to_datetime(df['date'], utc=True)
print('BTC_USD:', d.min(), '->', d.max(), len(df), 'rows')"
```

Expected: max ≈ 2026-07-14/15. If min ≈ 2026-04-01 → overwrite happened as predicted → Task 2 required. If min ≈ 2026-01-01 → freqtrade merged after all → run Task 2 anyway (it is a no-op union; dedupe keeps it safe) and note the surprise.

### Task 2: Merge the backup back in

**Files:** run: `scripts/merge_15m_backup.py` (modifies `user_data/data/kraken/*-15m.feather`, gitignored data only)

- [ ] **Step 1: Run the merge**

```bash
.venv/bin/python -W ignore scripts/merge_15m_backup.py
```

Expected output: `Merged 628 pairs: ~569 gained history, ...` then probe lines. Every probe (BTC, ETH, SOL, XLM, AAVE) must read `2026-01-01 00:00 -> 2026-07-14/15 ...` with `0 duplicate dates`.

- [ ] **Step 2: If any probe shows duplicates or a gap at the Mar 31/Apr 1 boundary** → Contingency C3.

### Task 3: Data-coverage gate (cheap, before burning the run)

- [ ] **Step 1: Count rankable pairs per OOS month** — ranking month M needs the *prior* month's candles (≥500) above the $250k/day floor:

```bash
.venv/bin/python -W ignore -c "
import sys; sys.path.insert(0, 'scripts')
from rolling_backtest import rank_pairs_for_month, DATA_DIR, TOP_N
import pandas as pd
for m in ['2026-04','2026-05','2026-06','2026-07']:
    pairs = rank_pairs_for_month(DATA_DIR, pd.Timestamp(m, tz='UTC'), TOP_N)
    print(m, '->', len(pairs), 'pairs; top 5:', pairs[:5])"
```

Expected: 30 pairs each month, majors near the top (BTC/ETH/SOL-type names). Any month with 0 pairs → Contingency C3/C5 before running anything.

### Task 4: OOS rolling backtest (the main event)

- [ ] **Step 1: Run it** (Feb–Mar months took ~seconds each; whole run is minutes):

```bash
.venv/bin/python scripts/rolling_backtest.py 2026-04 2026-07
```

The harness prints, per month, the exact result zip + trades + profit (the stale-pointer bug fix — trust only these lines). Summary lands in `user_data/backtest_results/rolling_summary.{json,md}`.

- [ ] **Step 2: Note the July caveat** — data ends ~Jul 14/15, so 2026-07 is a half month. The summary divides by 4×4.345 ≈ 17.4 weeks; the real window is ~15.0 weeks. Report both; use in-regime weeks for the gate anyway.

### Task 5: Regime audit + in-regime frequency

- [ ] **Step 1: Audit every OOS trade against the reconstructed BTC regime** (uses the 4 zip names the harness printed):

```bash
.venv/bin/python -W ignore scripts/verify_regime_gating.py \
  user_data/backtest_results/<apr>.zip user_data/backtest_results/<may>.zip \
  user_data/backtest_results/<jun>.zip user_data/backtest_results/<jul>.zip
```

Expected: `Opened in DOWN-regime: 0`. Any leak → treat the whole run as suspect (Contingency C6 logic in reverse: audit before believing any number, good or bad).

- [ ] **Step 2: Compute the up-regime share of the window** (for the amended frequency gate):

```bash
.venv/bin/python -W ignore -c "
import sys; sys.path.insert(0, 'user_data/strategies')
import pandas as pd
from momentum_signals import DEFAULT_PARAMS, regime_mask_from_btc, resample_1h
btc = pd.read_feather('user_data/data/kraken/BTC_USD-15m.feather')
btc['date'] = pd.to_datetime(btc['date'], utc=True)
w = btc[(btc['date'] >= '2026-04-01') & (btc['date'] < '2026-07-15')]
h = resample_1h(w); up = regime_mask_from_btc(h, DEFAULT_PARAMS)
share = up.mean()
weeks = (w['date'].max() - w['date'].min()).days / 7
print(f'window {weeks:.1f} weeks, up-regime share {share:.1%}, up-weeks {share*weeks:.1f}')"
```

In-regime trades/week = total OOS trades ÷ up-weeks. Gate leg passes at ≥5.

### Task 6: Record honestly, commit, stop for Austin

- [ ] **Step 1:** Append a new section to `docs/backtests.md` in the same format as the Feb–Mar v2 section: per-month table with result filenames, totals, up-regime share, in-regime trades/week, per-trade shape (win rate, avg trade), explicit gate verdict per leg, July-partial caveat, and the merge-repair note (what was overwritten, what was merged).
- [ ] **Step 2:** Update `.handoff/task.md` (results, verdict, exact next action = Austin's decision).
- [ ] **Step 3:** Commit + push:

```bash
git add docs/backtests.md
git commit -m "Record v2 Apr-Jul out-of-sample rolling backtest"
git push
```

- [ ] **Step 4: STOP.** Present to Austin: in-sample (−8.36%, 36 trades, 5.4% DD, all-in-regime) side by side with OOS, and the standing options — (a) judge v2 on the combined picture, (b) one conceptual design change via spec update (exit asymmetry: −4% stop vs +3% capped ROI at ~0.8% round-trip fees is the identified mechanism), (c) table v2, open the next tabled family. **If (b) is chosen, Apr–Jul stops being clean OOS for the modified design — fresh validation needs Aug+ data.** No tuning meanwhile.

---

## Contingency tree

**C1 — Download stalls or the wrapper dies without the sentinel** (monitor fires stall/exit event):
Diagnose with `tail -50 user_data/download_narrowed.log` and `docker ps`. The download is resumable — finished pairs are skipped:
```bash
nohup bash -c 'bash scripts/download_data.sh 20260401-20260715 pairs_usd_gap.json && echo "=== ALL DOWNLOADS COMPLETE ===" ' >> user_data/download_narrowed.log 2>&1 &
```
The resumed run re-triggers conversion at its end; the backup predates all conversion, so Tasks 2–3 are unchanged. Re-arm the monitor.

**C2 — Sentinel present but only 1 "About to convert" line** (gap-fill conversion never ran):
Convert manually, then proceed to Task 2:
```bash
docker compose run --rm freqtrade trades-to-ohlcv --config /freqtrade/config-paper.json \
  --pairs-file /freqtrade/user_data/pairs_usd_gap.json -t 15m
```

**C3 — Merge output wrong** (duplicate dates, missing boundary candles, pair count off):
Restore wholesale and retry: `cp -p user_data/data/kraken_15m_backup_20260720/*-15m.feather user_data/data/kraken/` then re-run Task 2. Last resort: rebuild Jan–Mar from bulk CSVs (`.venv/bin/python scripts/convert_kraken_ohlcvt.py` — it unions with existing data) and re-run C2's manual conversion for Apr–Jul.

**C4 — July month errors or returns no data in the harness:**
Run `rolling_backtest.py 2026-04 2026-06` instead, record July as "excluded (partial data)" in the write-up. Do not hand-edit the harness.

**C5 — Zero or near-zero OOS trades:**
Not automatically a failure — first run Task 5 Step 2. If the window was overwhelmingly down-regime, the strategy sat out by design; verdict is "insufficient in-regime exposure to judge," and the honest options for Austin shift toward waiting for more data. Sanity-check that entries were *possible*: pick one known up-regime day and confirm `momentum_signals` produces candidates on it.

**C6 — OOS strongly positive (guard against believing a bug):**
Before presenting: (1) regime audit clean (Task 5), (2) per-month zip names in the harness log match the zips read, (3) spot-check 3 winning trades against raw candles (entry price within the candle's range, exit consistent with ROI/stop). Only then present — still STOP for Austin; a passing OOS does not authorize deploy (in-sample failed; 2-week paper gate still ahead per README rules).

**C7 — Docker daemon flakes mid-run:**
Restart Docker Desktop, re-run the harness command. Months are independent; a partial run just re-runs (results are selected from each run's own stdout, so stale results cannot leak in).

## Decision points reserved for Austin

1. The (a)/(b)/(c) direction call after OOS lands — this plan ends there.
2. Anything touching deploy, live keys, or spending beyond routine backtest compute.
