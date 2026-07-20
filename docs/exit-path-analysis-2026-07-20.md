# Exit-path analysis: can any exit design rescue the v2 entries? (2026-07-20)

**Question.** Austin approved direction (b): fix v2's exit asymmetry (capped +3% winners
vs −4% stops plus ~0.8% fees) via a spec update. Before writing that spec, this analysis
checks the premise against the recorded trade paths. **Answer: the premise is wrong.
No exit design tested — including perfect ones — turns these entries profitable.
The loss mechanism is entry timing relative to the post-entry shakeout, not the exit cap.**

**Data.** The 119 trades from the six recorded v2 rolling-backtest zips (Feb–Jul 2026,
in-sample + OOS), replayed against the repaired 15m candle feathers. Everything below is
**in-sample by declaration**: any design informed by it must be validated on Aug+ data.
Scripts: `scripts/path_analysis/` (four files, run from repo root).

## 1. The censored view (trade records) was misleading

From the trade records alone (`max_rate` per trade), the picture looks like "no tail
exists": median trade peak +2.1%, only 10/119 trades above +4%, total profit surrendered
above the 3% ROI cap just +0.34%/trade. But `max_rate` is **censored at exit time** — a
trade cut at +3% after 3h stops being observed, hiding whatever the coin did next.
A conclusion drawn from that table (either way) is invalid. (`mfe_censored.py`)

## 2. Uncensored: the entries genuinely precede moves

Replaying each trade's candles for 24/48h past entry, ignoring the old exits
(`replay_uncensored.py`):

| Peak within 24h of entry | share of 119 trades |
|---|---|
| ≥ +3% | 62% |
| ≥ +4% | 54% |
| ≥ +6% | 36% |
| ≥ +8% | 27% |
| ≥ +10% | 16% |

Median 24h peak **+4.3%**, p75 +8.2%, p90 +12.7%. A perfect exit (sell the exact 24h top,
minus 0.8% fees) would have made **+4.86%/trade** (+6.24% at 48h). The entry signal has
real selection power; v2's exits were not harvesting it — but see §4 for why "uncap the
exits" still fails.

## 3. The shakeout and the clock (`shakeout.py`)

Between entry and the 24h peak:

- Median adverse dip before the peak: **−1.37%** (all trades) / **−1.80%** (the 64 trades
  that peaked ≥+4%); p25 among movers −3.30%. Only 9.2% hit the −4% stop before their peak.
- Median time to peak **6.2h**; among the ≥+4% movers, **73% peak after the 6h stagnation
  horizon** (median ≈ 14h). v2's stagnation timeout fires at hour 6 on trades that are
  flat — i.e. exactly the slow starters whose move arrives at hour 8–20.

So the path shape is: enter on the pullback → chop 1.5–3.3% below entry → move arrives
half a day later. The 0.8% round-trip fee sits on top of every attempt.

## 4. Exit-mechanism sweep: every mechanical family negative

*(Corrected per the independent audit, §8. The first draft used an "optimistic bound"
built from `mfe_censored.py`'s censored max_rate — invalid by §1's own argument; the
audit replaced it with uncensored variants and extended the sweep to two further
families. That script's simulation block is retained only as a record of the error.)*

The audited evidence, all on uncensored candle replays validated against freqtrade's own
accounting (the replay engine reproduces v2's recorded result to within 0.02pp/trade):

- **Conservative close-based trailing replay** (`replay_uncensored.py`, `final_replay.py`):
  stop checked before trail inside each candle, ratchet on closes, fees included.
  9 variants (arm 1.5–3%, trail 2–4%, stagnation 6h / 24h / none, caps 48–72h):
  **−0.97 to −1.48%/trade** vs v2's actual −0.81%/trade. Fixing the time dimension
  (stagnation 24h or removed, per §3) makes it *worse*: longer exposure raises
  stop-outs from 28 to 45–48 of 119.
- **Optimistic intrabar-high trailing replay** (audit): same 9 variants with trail
  tracking intrabar highs — still **−0.80 to −1.48%/trade**.
- **Partial scale-out** (audit): sell half at +3%, trail the rest — **−0.96%/trade**.
- **Flat ROI, no ladder / lock / stagnation** (audit): best of all mechanical exits at
  **−0.57%/trade**, bootstrap 95% CI [−1.18%, +0.03%], one-sided P(mean>0)=0.034 —
  statistically negative, upper bound at breakeven, no deployable edge.

The mechanism: to survive the pre- and post-arm chop a trail needs ≥3–4%; that plus fees
consumes nearly the entire median +4–5% move, while the −4% stop keeps collecting full
losses. Win rate falls to 25–35% and the tail (27% of trades ≥+8%) is too thin at these
fee levels to pay for the rest. The gap between the +4.86% oracle ceiling and every
realizable mechanism is path noise + fees, not a parameter choice.

**Scope:** this refutes *mechanical* exit rules (ladders, stops, trails, scale-outs,
timeouts). A predictive exit (a separate top-detection signal) is untested — but that is
a new signal design, not the approved exit-parameter fix. **Not tested and deliberately
so:** more variants of the same levers. ~20 uniform negatives across four families on the
same 119 trades is a refutation, not an unlucky sample; further in-sample knob-turning
would only manufacture a selection-biased green cell with no OOS data left to expose it.

## 5. Verdict on direction (b)

**Refuted — do not implement.** No tested mechanical exit clears a deployable zero
in-sample: the best (flat ROI) is −0.57%/trade with its 95% upper bound at breakeven, and
every trailing/scale-out variant loses more than the current exits. The upside the oracle
sees (+4.86%/trade) is destroyed not by fees on the exit but by the give-back any
realizable rule must pay to survive the chop. Note the exits still deserved *some* blame:
the audit's flat-ROI test (−0.57%) beats v2's ladder+lock+stagnation (−0.81%), so v2's
extra exit machinery mildly hurt — but removing it still leaves a negative strategy.

Corrected diagnosis: the edge is lost **between entry and the move** — the entry buys
before the shakeout completes (median −1.4%, movers' p25 −3.3%), pays the fee spread, and
either stops out, times out before the ~14h move, or arms a trail that the chop shakes out.

## 6. What the data does support (b′ — proposal only, NOT started)

The one lever with a data-backed mechanism is **entry timing/price**: enter *after* the
shakeout instead of before it — e.g. a limit order deeper in the pullback band (the
measured −1.5 to −3% dip zone) and/or a resumption-confirmation gate (enter on the first
higher close after the pullback low), keeping v2's regime/impulse filters. The audit's
fill-test quantifies the lever: entering ~2% lower shifts per-trade expectancy by **~+2pp**
(flat ROI −0.57 → +1.23%/trade; trailing −0.96 → +1.03%) — in-sample positive. (An
earlier draft claimed "~4% round trip" by counting the cheaper entry and the reduced
give-back separately; they are the same 2%, counted once.)

Honest caveats, stated up front:
- The **entire +2pp is an upper bound**, eroded by two forces the replay cannot price:
  adverse selection (limit fills skew toward trades that keep falling) and missed fills
  (a limit 2% down skips the trades that run straight up — plausibly the best movers).
  Real b′ sits below +2pp and possibly below zero. Only a real freqtrade backtest with
  limit-order semantics can price it.
- This mechanism is **fitted to the same 119 in-sample paths**. A freqtrade backtest of
  it on Feb–Jul is still in-sample; the only clean validation is Aug+ data (or forward
  paper trading). Aug+ data must be reserved for a b′ that already survives in-sample.
- If b′ cannot clear a clean zero in-sample, the pullback family is exhausted
  (option (c) territory) — learned without burning any Aug+ data.

## 7. Status

- v2 exit parameters remain frozen as recorded; no spec change written (the approved (b)
  spec update is withdrawn by this evidence — decision returned to Austin).
- No strategy code touched; no freqtrade backtests run; nothing tuned.
- Data notes: candle feathers are the repaired (backup-merged) set, verified seam-exact;
  July trades' replay windows never truncate (all 11 opened by Jul 5, data ends Jul 15);
  the DOGE/USD hole is Apr–May 2026 only (earlier candles exist from the bulk export) and
  affects 0 of the 119 trades.
- Independent methodology review: research-auditor verdict recorded in §8.

## 8. Independent review (research-auditor, Opus, 2026-07-20)

**Verdict: REVIEW → refutation endorsed; three writeup flaws found and fixed above.**

- Engine validation: reconstructing v2's actual exit ladder inside the replay engine gives
  −0.791%/trade vs the recorded −0.807% (±0.016pp) — the counterfactual replays are
  trustworthy.
- The audit *extended* the sweep beyond this doc's trailing variants: optimistic
  intrabar-high trailing (9 variants, −0.80 to −1.48%/trade), partial scale-out (−0.96%),
  flat ROI (best mechanical exit, −0.57%/trade, 95% CI [−1.18%, +0.03%], one-sided
  P(mean>0)=0.034). Every mechanical family negative; the refutation of (b) is, in the
  auditor's words, "correct and, if anything, under-proven."
- Flaws corrected in this revision: (1) the draft's "optimistic bound" was computed on
  censored max_rate and was invalid (§4 rewritten on audited uncensored evidence);
  (2) a §5 sentence contradicted §2's oracle arithmetic (median perfect exit is +3.5%
  net, not "barely clears fees"); (3) §6's "~4% round trip" double-counted the entry
  improvement (correct figure ~+2pp, audited by fill-test).
- Statistical caveats adopted: the refutation claim is scoped to *mechanical* exits;
  the strongest counterfactual is ~1.9 SE below zero, so the operative wording is "no
  tested mechanical exit clears a deployable zero in-sample."
- Auditor's independent next-step read: run b′ as a real freqtrade backtest with
  limit-entry semantics on Feb–Jul (still in-sample); reserve Aug+ strictly for
  validating a b′ that already survives in-sample.
- All headline numbers in §§2–4 were independently recomputed and reproduce exactly;
  July truncation and the DOGE hole affect 0 trades.
