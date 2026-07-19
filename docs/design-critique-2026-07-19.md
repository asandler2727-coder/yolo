# Independent design critique — Grok Build, 2026-07-19

Run after the Task 6 sweep failed the gate on Feb–Mar 2026 data (see
`docs/backtests.md`). Read-only critique by grok-4.5-build via the Grok Build
plugin (job `review-mrr53k6n-hx2u69`), focused on whether the MemeMomentum v1
design is salvageable. Verdict: **needs-attention — design rejection, not a
tuning problem.** Findings below are Grok's, with our reconciliation notes.

## Summary (Grok, verbatim)

> Do not ship or dry-run this design. Sweep evidence shows negative per-trade
> expectancy on the core entry rule (chase 15m pumps after the move, pay 0.8%
> round-trip). Param tuning only reduces how often you lose money; it does not
> create edge. Salvage requires a strategy redesign (regime filter / non-chase
> entry / fee-aware edge), not more knobs on MemeMomentum v1.

## Findings

1. **[critical] Entry rule has negative expectancy; tuning cannot fix it**
   (`momentum_signals.py`). Buying after a completed +3%/2h pump and paying
   ~0.8% round-trip means each trade needs a large continuation just to break
   even; the sweep's monotone "stricter entry → smaller losses" pattern is the
   signature of negative per-trade expectancy. Suggested directions: higher-TF
   regime filter + 15m pullback entry; range-breakout-with-volume instead of
   pct-change-from-N-candles-ago; or explicitly fade overextended pumps.
   *Reconciliation: matches our own Task 6 analysis exactly. Accepted.*

2. **[critical] Exit stack assumes a large unfinished pump the entry already
   spent** (`MemeMomentum.py` ROI/trailing/stop). ROI wants +10% after a +3%
   entry signal; when continuation fails the loss is structural. Suggested:
   fee-aware ROI floor, ATR-based stops, shorter time-stop. *Accepted as part
   of any redesign; not worth retuning on v1 (sweep already proved ROI/stop
   dials don't restore profit).*

3. **[high] Long-only 15m momentum is regime-blind** — no market/pair trend
   filter, so it buys relief rallies in down months (Feb: −48.6% vs market
   ~−14%). Suggested: regime filter that disables longs in down regimes, and
   restructure the gate so frequency can't pass while expectancy is negative;
   accept zero-trade bear months if the product stays "meme pumps only."
   *Accepted in principle. Note: gate restructuring is Austin's call (spec §9
   forbids loosening; making it stricter/structural is allowed but is a spec
   change).*

4. **[high] Backtest universe and risk path don't match live**
   (`rolling_backtest.py`): ranking had no $250k/day floor and no
   spread/stability proxies, and the harness didn't pass
   `--enable-protections`, so live halts (StoplossGuard, 15% MaxDrawdown)
   never fired in backtests. *Accepted and FIXED same day: ranking now
   enforces `MIN_DAILY_QUOTE_VOLUME = 250_000` (test-covered) and the harness
   passes `--enable-protections`. This resolves the open methodology question
   in docs/backtests.md. Spread/stability OHLC proxies deliberately skipped
   for now (small effect vs the volume floor; revisit if a redesign passes).
   Consequence: future runs are not directly comparable to the recorded
   Feb–Mar numbers — rerun the baseline as a control before comparing.*

5. **[medium] 15m high-frequency momentum is structurally fee-dominated on
   Kraken** at taker 0.4%: ~20 trades/week of small moves is churn that the
   fee eats. Suggested: longer timeframe / fewer higher-quality trades, or
   maker-first order handling re-gated at realistic maker+slippage.
   *Accepted as a design input: the predecessor bot's zero-trade failure
   over-corrected into fee-burning trade frequency.*

## Grok's recommended next steps (all consistent with spec §9)

- Freeze parameter sweeps on v1; treat the gate FAIL as design rejection.
- Write a short redesign brief first: regime filter + non-chase entry +
  fee-aware risk/reward; pick ONE primary hypothesis, not a multi-knob grid.
- Align the harness with live constraints (done) and rerun the baseline only
  as a control after redesign, with protections enabled.
- Use Apr–Jul data as out-of-sample for the NEW design — "not as a lottery
  ticket for the current chase-pump rule."
- No dry-run or live until a redesigned strategy shows positive total profit
  and realistic drawdown on the rolling harness.

## Status

Harness fixes applied and committed. Strategy redesign direction awaits
Austin's approval (it changes product behavior: e.g. sitting out bear months
conflicts with the current ≥5 trades/week gate leg).
