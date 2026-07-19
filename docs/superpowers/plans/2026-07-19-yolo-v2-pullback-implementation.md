# YOLO v2 — Pullback-in-uptrend Implementation Plan

> **For the implementing agent (Claude):** TDD the signal module first, then wire the strategy, then run the rolling harness. Do **not** implement tabled families A/B/C. Do **not** retune v1 chase-pump.

**Goal:** Replace MemeMomentum v1’s chase entry with higher-TF BTC regime + 15m pullback entry and fee-aware exits; prove it on the rolling harness with protections on.

**Specs (read in order):**

1. `docs/superpowers/specs/2026-07-19-yolo-v2-pullback-redesign.md` — **authoritative** for signal math, exits, gate, tabled families  
2. `docs/superpowers/specs/2026-07-18-yolo-meme-momentum-bot-design.md` — §6/§8 money & safety always win  
3. `docs/design-critique-2026-07-19.md` — why v1 is dead  
4. `docs/backtests.md` — how to record new runs  

**Architecture (unchanged shell):** Freqtrade Docker + dynamic pairlist + pure-pandas `momentum_signals.py` + `MemeMomentum` IStrategy + `scripts/rolling_backtest.py` with $250k floor and `--enable-protections`.

---

## Global constraints

- `"dry_run": true` in committed configs; no live keys; no `config-live.json` this phase.
- $750 / 3 × $250; protections never weakened.
- Fee model: `--fee 0.004` taker.
- **One primary hypothesis only.** No strategy zoo; tabled families stay docs-only.
- **Do not stop** long-running downloads on this Mac (`user_data/download_mac.log` etc.).
- Commit at natural checkpoints with plain-English messages; push to `origin/main` is fine on Austin’s repo.
- Apr–Jul feathers: OOS for v2 only when complete — do not use them to rescue v1.

---

### Task 1: TDD — rewrite pure-pandas signals for v2

**Files:**

- Edit: `user_data/strategies/momentum_signals.py`
- Edit: `tests/test_momentum_signals.py`

**Target API (keep pure pandas, no freqtrade):**

```python
DEFAULT_PARAMS = {
    # regime (on 1h-equivalent series or separate btc frame)
    "regime_ema_fast": 20,
    "regime_ema_slow": 50,
    # impulse / pullback on 15m
    "impulse_lookback": 12,
    "impulse_min_pct": 0.04,
    "pullback_min_pct": 0.015,
    "pullback_max_pct": 0.05,
    "chase_block_candles": 3,
    "chase_block_pct": 0.02,
    "volume_window": 48,
    "volume_mult": 1.5,
    # optional pair trend
    "pair_ema_period": 50,
    "require_pair_above_ema": True,
}

def add_indicators(df, params) -> DataFrame: ...
def regime_mask_from_btc(btc_1h: DataFrame, params) -> Series: ...  # or equivalent
def entry_mask(df, params, regime_ok: Series | bool) -> Series: ...
```

Exact helper names may vary; tests define the contract.

- [ ] **Step 1:** Write failing tests for:
  1. Regime true when 1h close > EMA50 and EMA20 > EMA50; false in clear downtrend.
  2. Entry false when regime false (even if pullback geometry is perfect).
  3. Entry false on vertical chase (last 3 bars +2%+).
  4. Entry true on synthetic: prior impulse + pullback into band + volume alive + regime true.
  5. Entry false when pullback is a full collapse beyond `pullback_max_pct`.
- [ ] **Step 2:** Implement indicators + masks until tests pass.
- [ ] **Step 3:** ` .venv/bin/pytest tests/test_momentum_signals.py -v ` — all green.
- [ ] **Step 4:** Commit: “Rewrite momentum signals for v2 pullback + regime filter”.

---

### Task 2: Wire `MemeMomentum` strategy to v2 signals

**Files:**

- Edit: `user_data/strategies/MemeMomentum.py`
- Possibly: `config-paper.json` only if timeframe/pairlist needs a note (prefer no config churn)

**Behavior:**

- `timeframe = "15m"` unchanged.
- Merge BTC informative 1h (or resample) for regime; if BTC pair missing in a backtest month, document fallback (fail closed: no entries).
- `populate_entry_trend` uses new `entry_mask`.
- Exits per redesign: ROI `{0: 0.03, 60: 0.02, 180: 0.01}`, `stoploss = -0.04`, trailing positive 0.012 / offset 0.02, stagnation **6** hours.
- Protections block **unchanged** (Cooldown, StoplossGuard, MaxDrawdown).

- [ ] **Step 1:** Update strategy fields and entry wiring.
- [ ] **Step 2:** Smoke: strategy file imports; existing integration tests still pass or update for new signal contract.
- [ ] **Step 3:** ` .venv/bin/pytest tests/ -v ` — all green.
- [ ] **Step 4:** Commit: “Wire MemeMomentum to v2 pullback entries and fee-aware exits”.

---

### Task 3: Rolling backtest — control + v2 in-sample

**Files:**

- Maybe touch: `scripts/rolling_backtest.py` only if needed for BTC data path or reporting regime trade counts (avoid drive-by refactors).
- Append: `docs/backtests.md`

**Runs (fee 0.004, protections on, $250k floor already required):**

1. **Optional control:** confirm harness still runs (v2 code will not reproduce old v1 numbers — if a v1 snapshot is needed, tag/restore is overkill; just note v1 was frozen at prior commits).
2. **v2 primary:**  
   ` .venv/bin/python scripts/rolling_backtest.py 2026-02 2026-03 `

**Interpret:**

- Feb–Mar was a bearish market window historically for the project narrative — **many zero-trade or low-trade weeks can be correct** if regime is off.
- Fail only on: large losses while trading, or code/harness errors.
- Do **not** launch a parameter grid. At most one conceptual tweak if the default is obviously broken (e.g. zero entries even when BTC is clearly up in a synthetic month).

- [ ] **Step 1:** Run Feb–Mar v2; append table + plain-English verdict to `docs/backtests.md`.
- [ ] **Step 2:** Commit results note.
- [ ] **Step 3:** If Apr–Jul data is fully on disk, run OOS `2026-04 2026-07` and record; else leave pending and do not block on downloads.

---

### Task 4: Gate judgment + handoff update

- [ ] Compare results to amended gate (profit + regime-conditional frequency).
- [ ] Update `.handoff/task.md`: pass/fail, next action (dry-run only if viable; else one redesign decision — not tabled zoo).
- [ ] Stop for Austin before dry-run or live.

---

## Out of scope this plan

- Tabled families A (breakout), B (mean-reversion), C (session scalps)
- Sentiment auto-apply, live config, stake increases
- Stopping or restarting Mac/Windows data downloads
- Hyperopt / multi-param grids

## Done definition

- Tests green for v2 signals  
- Strategy wired with fee-aware exits + intact protections  
- At least Feb–Mar v2 rolling results recorded  
- Handoff states whether candidate is dry-run-eligible or needs a single next hypothesis  
