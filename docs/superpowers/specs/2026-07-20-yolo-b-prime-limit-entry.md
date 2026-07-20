# YOLO b′ — limit-entry amendment to the v2 pullback design

**Date:** 2026-07-20
**Status:** Draft — awaiting Austin's approval before implementation
**Repo:** https://github.com/asandler2727-coder/yolo
**Amends:** `2026-07-19-yolo-v2-pullback-redesign.md` §2 (entry pricing only)
**Does not touch:** signals/regime/exits (frozen as implemented), §6 risk, §8 security,
universe, harness, protections, fees
**Evidence base:** `docs/exit-path-analysis-2026-07-20.md` (audited; §8 records the
independent review)

---

## 1. Why this amendment

v2 failed in-sample and out-of-sample (Feb–Jul: 119 trades, −0.81%/trade) with all
entries correctly regime-gated. The audited path analysis established:

- The entry *signal* selects real moves (median 24h peak +4.3%; oracle +4.86%/trade).
- No mechanical exit family clears zero on these entries (~20 variants, four families,
  best −0.57%/trade) — the approved exit-fix direction (b) was withdrawn on this evidence.
- The loss mechanism is entry *price/timing*: after the signal fires, price typically
  dips a further −1.5% (median) to −3.3% (movers' p25) before the move, which arrives
  ~14h later. v2 buys before that dip and pays for it in stops, timeouts, and shaken-out
  trails.
- Fill-test (auditor): entering ~2% lower shifts per-trade expectancy by ~+2pp
  (flat-ROI exits −0.57 → +1.23%/trade; ratchet trailing −0.96 → +1.03). This is an
  **upper bound**: it assumes every trade still happens, at a better price.

**One-sentence edge claim:** placing the entry as a resting limit order ~2% below the
signal price buys the measured shakeout instead of suffering it, at the cost of missing
the signals that run without dipping.

## 2. The change (the only one)

On a 15m candle where the unchanged v2 `entry_mask` fires, instead of entering at the
next candle's market price, place a **limit buy** below it:

| Parameter | Value | Basis (a priori, single configuration — no sweep) |
|---|---|---|
| `entry_limit_depth` | **0.02** (limit = proposed entry rate × 0.98) | The audited fill-test lever (~+2pp), sitting inside the measured dip zone (median −1.37%, movers' p25 −3.30%) |
| Unfilled-entry timeout | **4h** (240 min; 16 × 15m candles) | Dips cluster early (median time-to-peak 6.2h; the dip precedes the peak). A limit resting longer waits increasingly for breakdown-only fills — adverse selection grows with time |

Mechanics (freqtrade): `custom_entry_price` returns `proposed_rate × (1 − 0.02)`;
`unfilledtimeout: {entry: 240, unit: "minutes"}` cancels stale orders. The signal
itself, all exit layers (−4% stop, 3/2/1% ROI ladder, trailing lock, 6h stagnation),
protections, pairlist, and the rolling harness stay byte-identical to v2.

Rationale for changing entries alone: single-variable attribution. The audit showed the
exit ladder mildly hurts (flat ROI −0.57 vs v2's −0.81 on old entries), but exits stay
frozen so the b′ backtest measures the entry effect and nothing else. Exit
simplification remains a separately-testable follow-up with its evidence already on
record.

## 3. What the backtest must price (why this needs freqtrade, not replay)

The +2pp fill-test could not price two erosion forces, and this backtest exists to:

1. **Missed fills:** signals whose price never dips 2% don't fill — plausibly the best
   movers. Lost winners reduce both profit and frequency.
2. **Adverse selection:** fills skew toward signals that keep falling.

Freqtrade backtesting fills a resting limit when a candle's low crosses it and honors
the timeout, so both forces are priced at 15m resolution.

## 4. Gate (unchanged) and b′-specific reporting

The amended gate from the v2 brief applies verbatim: positive total profit at
`--fee 0.004` with `--enable-protections`; ≥5 trades/week averaged over up-regime
periods (zero-trade bears fine); report max DD, flag >~25%/month. **No leg is loosened
for b′.** Fill rate will cut frequency — if profit passes and frequency fails, record
both honestly and return direction to Austin rather than widening anything.

Additionally record: signals vs. placed orders vs. fills (fill rate), per-month table,
win rate, avg trade, exit-reason mix, and the in-regime trades/week divisor as before.

**Statistical status, stated up front:** Feb–Jul is in-sample for b′ (the depth sits in
the middle of a distribution measured on these very trades). Clearing the gate here is
*necessary, not sufficient*: validation requires Aug+ data or the 2-week dry-run per
master spec §9. Failing the profit leg in-sample = the pullback family is exhausted
(option (c) per the v2 brief §3 rules).

## 5. Fees stay conservative

Harness stays at `--fee 0.004` both sides (taker), although a resting limit entry would
usually pay Kraken's maker rate. Modeling maker fees now would flatter the result and
re-open the "maker-fee fantasy without re-gating fills" non-goal (v2 brief §6). If b′
passes and reaches dry-run, real fills price it there. Unmodeled upside, deliberately.

## 6. Implementation traps (must-handle, verify against installed freqtrade 2026.4)

1. **Silent price clamp:** freqtrade caps how far `custom_entry_price` may sit from the
   market via `custom_price_max_distance_ratio` — **default 0.02, exactly our depth**.
   Left at default, boundary rounding can silently clamp the limit and turn b′ into a
   near-no-op. Set it explicitly to `0.05` in the backtest config and assert the
   achieved entry discount in the result (mean fill price vs signal close ≈ −2%).
2. **Fill semantics:** backtest fills the limit iff a candle's `low` ≤ limit while the
   order rests; same-candle open-below-limit fills at the open (better price) — fine,
   report it.
3. **Timeout units:** `unfilledtimeout` uses minutes here; confirm the backtester
   honors it (it does in 2026.x; assert via order/fill counts in the result).
4. **TDD:** unit-test the entry-price function (pure math), then one tiny known-data
   smoke backtest asserting (a) fewer fills than signals, (b) fills ~2% below signal
   close, before the full Feb–Jul run.
5. **Result integrity:** parse the result zip from freqtrade stdout as fixed on
   2026-07-19 (never `.last_result.json`).

## 7. Non-goals for b′

No resumption-confirmation entry gate (tabled second lever — do not combine with depth
in one experiment). No exit changes. No depth/timeout sweep — one pre-registered
configuration, one run. No maker-fee modeling. No new indicators. No changes to
protections, stakes, or the $750 cap. If the single configuration fails, the answer is
recorded, not retuned.

## 8. Definition of done

1. Spec approved by Austin (this gate).
2. Implementation per §6 with tests green.
3. One rolling Feb–Jul backtest (six months, same harness), results + fill diagnostics
   recorded in `docs/backtests.md`, committed.
4. STOP: results to Austin — pass → Aug+/dry-run validation decision; fail → option (c)
   decision. Nothing auto-proceeds.
