#!/usr/bin/env python3
"""Uncensored forward-path replay for family A's DEV-window entries.

Iteration 1 lost -0.90%/trade (arm L) with a 58% win rate: avg win +1.97% vs
avg loss -4.82%. That asymmetry has two possible causes and the knob you should
spend an iteration on differs completely between them:

  (a) the ENTRIES are worthless   -> no exit ladder can save them; family dies.
  (b) the EXITS cap live moves    -> the ROI tail (+1.5% after 8h, ~+0.6% net)
                                     harvests a fraction of what the move gives.

Trade records cannot tell these apart: `max_rate` is CENSORED at exit time, so
a +1.5% ROI exit hides whatever the coin did for the next two days (the lesson
that invalidated the first v2 exit analysis -- see
docs/exit-path-analysis-2026-07-20.md section 1). This replays each entry
against RAW candles, ignoring the recorded exit, to measure the real forward
path.

Outputs, in the order they should be read:

1. Engine validation. Reconstruct the CONFIG AS RUN (ROI 5/3/1.5, stop -4%,
   trailing 0.012@0.03) inside this engine and compare per-trade net against
   the recorded profit_ratio. If this does not reproduce, nothing below is
   trustworthy and the script exits 1.
2. Uncensored peak distribution at 6/12/24/48h -- the ceiling for ANY exit.
3. Perfect-exit ceiling (sell the exact top, minus fees). Only a NEGATIVE
   ceiling is decisive: it kills the family without spending an iteration.
   A positive ceiling is near-vacuous and proves nothing on its own.
4. Honest counterfactuals across the PRE-REGISTERED exit grid only
   (spec s3: ROI {default, wider, tighter} x trailing {on, off} x stop
   {-4%, -5%}). This orders the remaining iterations; it does not replace one.

HOLDOUT SEAL (hard constraint, spec s5). The dev window ends 2025-08-31. The
holdout 2025-09 -> 2026-01 is sealed by discipline only -- those candles are
physically on disk. An entry late in 2025-08 replayed forward 48h WOULD READ
SEALED CANDLES. Every window is truncated at SEAL_TS and an assertion fails the
run if any candle at/after it is ever touched. Truncated trades are counted and
reported, never silently averaged in.

Diagnostic only: no knob is changed and no config is graded. In-sample on the
dev window by declaration -- any exit shape chosen off the back of this is more
fitted than a blind grid pick, which raises the bar on the sealed holdout.

Usage: .venv/bin/python3 scripts/path_analysis/replay_family_a.py
"""
import json
import sys
import warnings
import zipfile
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)

import pandas as pd  # noqa: E402

BASE = Path("user_data/backtest_results")
DATA = Path("user_data/data/kraken")
# Iteration-1 baseline snapshot: later runs overwrote rolling_summary_{L,D}.json
# and became "latest per month" in BASE, so selecting from BASE alone would
# silently return a NON-baseline population that still passes the count check
# (it matches the overwritten summaries). Selection is therefore pinned to the
# snapshot's zip manifest and cross-checked against the snapshot's summaries.
BASELINE_SNAPSHOT = Path("user_data/backtest_baseline_iter1")

# --- holdout seal -----------------------------------------------------------
SEAL_TS = pd.Timestamp("2025-09-01", tz="UTC")
DEV_START = pd.Timestamp("2024-02-01", tz="UTC")

# --- arm definitions (spec s4) ---------------------------------------------
ARM_FEES = {"L": 0.0045, "D": 0.006}
ARM_MAX_WHITELIST = 30          # arm L is top-30; arm D slices ranks 31..100

# --- config as run, iteration 1 (MemeMomentum.py) ---------------------------
ROI_AS_RUN = {0: 0.05, 240: 0.03, 480: 0.015}
STOP_AS_RUN = -0.04
TRAIL_POS, TRAIL_OFFSET = 0.012, 0.03

# --- pre-registered exit grid (spec s3 candidate values) --------------------
ROI_SHAPES = {
    "default": {0: 0.05, 240: 0.03, 480: 0.015},
    "wider":   {0: 0.07, 360: 0.04, 720: 0.02},
    "tighter": {0: 0.03, 120: 0.02, 360: 0.01},
}
# Recorded holds reach 592h, so a short horizon would cut real exits off the
# end and score them as unresolved. 720h covers every recorded trade; the seal
# still truncates it near the window edge, which is the point of the guard.
HORIZON_H = 720
VALIDATION_TOL = 0.001          # 0.1pp/trade mean abs error

_cache: dict[str, pd.DataFrame] = {}
_seal_breach: list[str] = []


def candles(pair: str) -> pd.DataFrame:
    if pair not in _cache:
        df = pd.read_feather(DATA / f"{pair.replace('/', '_')}-15m.feather")
        df["date"] = pd.to_datetime(df["date"], utc=True)
        _cache[pair] = df.set_index("date").sort_index()
    return _cache[pair]


def window_for(pair: str, entry_ts: pd.Timestamp) -> tuple[pd.DataFrame, bool]:
    """Candles from entry forward, TRUNCATED AT THE HOLDOUT SEAL.

    Returns (window, truncated). `truncated` means the seal cut the horizon
    short, so this trade's 24h/48h numbers are floors, not measurements.
    """
    full_end = entry_ts + pd.Timedelta(hours=HORIZON_H)
    w = candles(pair).loc[entry_ts:min(full_end, SEAL_TS)]
    # .loc slicing is INCLUSIVE of the endpoint, so the bound above still admits
    # the 00:00 candle on seal day — the first holdout bar. Cut it explicitly.
    w = w[w.index < SEAL_TS]
    if len(w) and w.index.max() >= SEAL_TS:
        _seal_breach.append(f"{pair} @ {entry_ts} reached {w.index.max()}")
    return w, full_end > SEAL_TS


# --- freqtrade exit arithmetic ---------------------------------------------
def ratio_for_price(entry: float, rate: float, fee: float) -> float:
    """freqtrade calc_profit_ratio: fees on both sides."""
    return (rate * (1 - fee)) / (entry * (1 + fee)) - 1


def price_for_ratio(entry: float, ratio: float, fee: float) -> float:
    return entry * (1 + fee) * (1 + ratio) / (1 - fee)


def roi_for_minutes(roi: dict, minutes: float) -> float:
    """freqtrade picks the largest threshold key <= trade duration."""
    applicable = [v for k, v in sorted(roi.items()) if k <= minutes]
    return applicable[-1] if applicable else None


def simulate(entry_ts, entry_rate, window, fee, roi, stop_pct, trailing: bool,
             stagnation_h=None, stop_abs=None):
    """Mirror freqtrade's backtest exit stack on 15m candles.

    Within-candle order is freqtrade's, not an intuitive one, and the crosstab
    against 1563 recorded exits is what pinned it down:

    1. The trailing stop ratchets off the candle HIGH before anything is tested
       against the LOW (freqtrade assumes the high comes first inside a candle;
       23 recorded trailing_stop_loss exits scored as plain stops until this
       moved ahead of the stop check).
    2. ROI beats a stop that has already ratcheted, and loses only to a HARD
       stop still sitting at its original level -- freqtrade's
       `roi_reached and stoplossflag.exit_type != STOP_LOSS`. 101 recorded ROI
       exits scored as trailing until this was fixed.

    Gap fills: a stop fills at the open when the candle opened through it, and
    ROI likewise -- hence the min()/max() rather than the trigger price.

    `stop_abs` overrides `stop_pct` with an absolute price, for the spec's
    STRUCTURAL stop (the signal bar's range low, capped at -5%). Same mechanic,
    per-trade level: it stays a hard stop until the trailing stop ratchets past
    it, so it sits inside the validated envelope.
    """
    if not len(window):
        return None
    stop_price = stop_abs if stop_abs is not None else entry_rate * (1 + stop_pct)
    peak_rate = entry_rate
    trail_armed = trailing_active = False

    for ts, row in window.iterrows():
        minutes = (ts - entry_ts).total_seconds() / 60

        # 1) ratchet the trailing stop off the high, before testing the low
        if trailing:
            peak_rate = max(peak_rate, row.high)
            if not trail_armed and \
                    ratio_for_price(entry_rate, peak_rate, fee) >= TRAIL_OFFSET:
                trail_armed = True
            if trail_armed:
                trail_price = peak_rate * (1 - TRAIL_POS)
                if trail_price > stop_price:
                    stop_price, trailing_active = trail_price, True

        stop_hit = row.low <= stop_price
        target = roi_for_minutes(roi, minutes)
        roi_price = (price_for_ratio(entry_rate, target, fee)
                     if target is not None else None)
        roi_hit = roi_price is not None and row.high >= roi_price

        # 2) ROI, unless blocked by a hard (never-ratcheted) stop this candle
        if roi_hit and not (stop_hit and not trailing_active):
            return (ratio_for_price(entry_rate, max(row.open, roi_price), fee),
                    "roi", minutes / 60)

        # 3) stop / trailing stop
        if stop_hit:
            return (ratio_for_price(entry_rate, min(row.open, stop_price), fee),
                    "trailing" if trailing_active else "stop", minutes / 60)

        # 4) stagnation (MemeMomentum.custom_exit; a custom exit ranks below
        #    ROI and stoploss, so it is checked last). Evaluated on the close —
        #    the price you could actually act on for that bar.
        if stagnation_h and minutes / 60 > stagnation_h:
            net = ratio_for_price(entry_rate, row.close, fee)
            if net < 0.01:
                return net, "stagnation", minutes / 60

    last_ts, last = window.index[-1], window.iloc[-1]
    return (ratio_for_price(entry_rate, last.close, fee), "horizon",
            (last_ts - entry_ts).total_seconds() / 3600)


# --- trade loading ----------------------------------------------------------
def zip_meta(zp: Path):
    with zipfile.ZipFile(zp) as z:
        names = z.namelist()
        inner = [n for n in names if n.endswith(".json")
                 and not n.endswith("_config.json")
                 and not n.endswith(".meta.json")][0]
        data = json.loads(z.read(inner))["strategy"]["MemeMomentum"]
        cfg_names = [n for n in names if n.endswith("_config.json")]
        whitelist = 0
        if cfg_names:
            cfg = json.loads(z.read(cfg_names[0]))
            whitelist = len(cfg.get("exchange", {}).get("pair_whitelist", []))
    return data, whitelist


def load_dev_trades() -> pd.DataFrame:
    """Family-A dev-window trades, selected structurally and cross-checked
    against the recorded baseline totals.

    Arm comes from the config whitelist size (L = top 30, D = ranks 31..100),
    never from filename order. Where a month was run more than once (the
    2024-11 smoke preceded the baseline series) the LATEST run wins. The
    per-month trade counts must then match rolling_summary_{L,D}.json exactly,
    which is what proves this is the iteration-1 baseline set and not a mix.
    """
    manifest = {Path(line).name for line in
                (BASELINE_SNAPSHOT / "iter1_zip_manifest.txt")
                .read_text().splitlines() if line.strip()}
    picked: dict[tuple[str, str], tuple[str, list]] = {}
    for zp in sorted(BASE.glob("*.zip")):
        if zp.name not in manifest:
            continue                                    # not in the iter-1 snapshot
        data, whitelist = zip_meta(zp)
        start = pd.Timestamp(data["backtest_start"], tz="UTC")
        end = pd.Timestamp(data["backtest_end"], tz="UTC")
        if start < DEV_START or end > SEAL_TS:
            continue                                    # not the dev window
        arm = "L" if whitelist <= ARM_MAX_WHITELIST else "D"
        key = (arm, f"{start:%Y-%m}")
        if key not in picked or zp.name > picked[key][0]:
            picked[key] = (zp.name, data["trades"])

    rows = []
    for (arm, month), (zname, trades) in picked.items():
        for t in trades:
            rows.append({"arm": arm, "month": month, "zip": zname,
                         "pair": t["pair"],
                         "open_date": pd.Timestamp(t["open_date"]),
                         "open_rate": t["open_rate"],
                         "recorded_profit": t["profit_ratio"],
                         "recorded_exit": t["exit_reason"]})
    df = pd.DataFrame(rows)

    # cross-check against the recorded baseline summaries
    problems = []
    for arm in ("L", "D"):
        summary = json.loads(
            (BASELINE_SNAPSHOT / f"rolling_summary_{arm}.json").read_text())
        expected = {m["month"]: m["trades"] for m in summary["per_month"]}
        got = df[df.arm == arm].groupby("month").size().to_dict()
        if got != expected:
            for m in sorted(set(expected) | set(got)):
                if expected.get(m) != got.get(m):
                    problems.append(
                        f"  arm {arm} {m}: summary={expected.get(m)} selected={got.get(m)}")
    if problems:
        print("SELECTION MISMATCH vs rolling_summary_*.json:")
        print("\n".join(problems))
        sys.exit(1)
    return df


# --- reporting helpers ------------------------------------------------------
def describe(series: pd.Series, label: str, thresholds) -> None:
    s = series.dropna()
    print(f"\n{label} ({len(s)} trades):")
    print("  " + "  ".join(f"p{int(q * 100)}={s.quantile(q):+.1%}"
                           for q in (0.25, 0.5, 0.75, 0.9, 0.95)))
    for x in thresholds:
        print(f"    >= {x:>5.0%}: {(s >= x).sum():4d} ({(s >= x).mean():5.1%})")


def summarise(res: list, label: str) -> dict:
    s = pd.DataFrame([r for r in res if r is not None],
                     columns=["net", "tag", "hold_h"])
    if s.empty:
        return {}
    w = s.net > 0
    tags = s.tag.value_counts()
    return {"label": label, "n": len(s), "sum": s.net.sum(),
            "per_trade": s.net.mean(), "win": w.mean(),
            "avg_win": s.net[w].mean() if w.any() else 0.0,
            "avg_loss": s.net[~w].mean() if (~w).any() else 0.0,
            "med_hold": s.hold_h.median(),
            "exits": f"{tags.get('stop', 0)}/{tags.get('trailing', 0)}/"
                     f"{tags.get('roi', 0)}/{tags.get('stagnation', 0)}/"
                     f"{tags.get('horizon', 0)}"}


def print_table(rows: list) -> None:
    print(f"  {'variant':<34} {'sum%':>8} {'/trade':>8} {'win%':>6} "
          f"{'avgW':>7} {'avgL':>7} {'hold_h':>7}  stop/trail/roi/stag/horizon")
    for r in rows:
        if not r:
            continue
        print(f"  {r['label']:<34} {r['sum']:+8.1%} {r['per_trade']:+8.2%} "
              f"{r['win']:6.0%} {r['avg_win']:+7.2%} {r['avg_loss']:+7.2%} "
              f"{r['med_hold']:7.1f}  {r['exits']}")


def main() -> None:
    trades = load_dev_trades()
    print(f"Family A DEV baseline: {len(trades)} trades "
          f"(L={sum(trades.arm == 'L')}, D={sum(trades.arm == 'D')}) "
          f"across {trades.zip.nunique()} result zips — matches "
          f"rolling_summary_L/D.json exactly.")
    print(f"Holdout seal: windows truncated at {SEAL_TS:%Y-%m-%d}; "
          f"horizon {HORIZON_H}h.")

    # build windows once
    windows, truncated = [], []
    for t in trades.itertuples():
        w, trunc = window_for(t.pair, t.open_date)
        windows.append(w)
        truncated.append(trunc)
    trades["truncated"] = truncated

    if _seal_breach:
        print(f"\nSEAL BREACH — {len(_seal_breach)} windows reached the holdout:")
        print("\n".join("  " + b for b in _seal_breach[:10]))
        sys.exit(1)
    n_trunc = int(trades.truncated.sum())
    print(f"Seal guard OK: no candle at/after {SEAL_TS:%Y-%m-%d} read. "
          f"{n_trunc} trades ({n_trunc / len(trades):.1%}) had their horizon "
          f"cut by the seal — reported separately, never averaged in silently.")
    empty = sum(1 for w in windows if not len(w))
    if empty:
        print(f"NOTE: {empty} trades have no candles in window (excluded).")

    # ---- 1. engine validation ---------------------------------------------
    print("\n" + "=" * 78)
    print("1. ENGINE VALIDATION — reconstruct the config as run vs the record")
    print("=" * 78)
    recon = [simulate(t.open_date, t.open_rate, w, ARM_FEES[t.arm],
                      ROI_AS_RUN, STOP_AS_RUN, trailing=True)
             for t, w in zip(trades.itertuples(), windows)]
    trades["sim_net"] = [r[0] if r else float("nan") for r in recon]
    trades["sim_tag"] = [r[1] if r else "none" for r in recon]

    # Compare only trades that both sides actually resolved. force_exit is a
    # month-boundary artifact of the monthly harness, not an exit rule, and a
    # seal-truncated or unresolved window has no comparable endpoint.
    comparable = (~trades.truncated) & (trades.recorded_exit != "force_exit") \
        & (trades.sim_tag != "horizon") & trades.sim_net.notna()
    dropped = {
        "seal-truncated": int(trades.truncated.sum()),
        "force_exit (month boundary)": int((trades.recorded_exit == "force_exit").sum()),
        "unresolved in horizon": int((trades.sim_tag == "horizon").sum()),
    }
    err = (trades.sim_net - trades.recorded_profit)[comparable]
    rec_mean = trades.loc[comparable, "recorded_profit"].mean()
    sim_mean = trades.loc[comparable, "sim_net"].mean()
    print("  excluded from the comparison: "
          + ", ".join(f"{v} {k}" for k, v in dropped.items()))
    print(f"  trades compared: {len(err)}")
    print(f"  recorded  mean profit/trade: {rec_mean:+.3%}")
    print(f"  simulated mean profit/trade: {sim_mean:+.3%}")
    print(f"  mean error {err.mean():+.4%}   mean|error| {err.abs().mean():.4%}   "
          f"p95|error| {err.abs().quantile(0.95):.4%}")
    if err.abs().mean() > VALIDATION_TOL:
        print(f"\n  FAIL: mean|error| exceeds {VALIDATION_TOL:.2%}. The engine does "
              "not reproduce freqtrade's exits, so the counterfactuals below "
              "would be fiction. Fix the engine before reading further.")
        sys.exit(1)
    print(f"  PASS (tolerance {VALIDATION_TOL:.2%}/trade) — counterfactuals are "
          "trustworthy to about this precision.")

    # ---- 2. uncensored peaks ----------------------------------------------
    print("\n" + "=" * 78)
    print("2. UNCENSORED FORWARD PATH — what the entries actually offered")
    print("=" * 78)
    full = ~trades.truncated
    for h in (6, 12, 24, 48):
        peaks, mae, ttp = [], [], []
        for t, w in zip(trades.itertuples(), windows):
            sub = w.loc[:t.open_date + pd.Timedelta(hours=h)]
            if not len(sub):
                peaks.append(float("nan")); mae.append(float("nan"))
                ttp.append(float("nan")); continue
            peaks.append(sub.high.max() / t.open_rate - 1)
            pk = sub.high.idxmax()
            ttp.append((pk - t.open_date).total_seconds() / 3600)
            mae.append(sub.loc[:pk].low.min() / t.open_rate - 1)
        trades[f"peak{h}"] = peaks
        trades[f"mae{h}"] = mae
        trades[f"ttp{h}"] = ttp
    describe(trades.loc[full, "peak24"], "Gross peak within 24h (untruncated)",
             (0.02, 0.03, 0.05, 0.08, 0.10, 0.15))
    describe(trades.loc[full, "peak48"], "Gross peak within 48h (untruncated)",
             (0.02, 0.03, 0.05, 0.08, 0.10, 0.15))
    print(f"\nMedian time-to-24h-peak: {trades.loc[full, 'ttp24'].median():.1f}h; "
          f"median dip before that peak: {trades.loc[full, 'mae24'].median():+.2%}")
    movers = trades[full & (trades.peak24 >= 0.04)]
    if len(movers):
        print(f"Among the {len(movers)} trades that peaked >= +4% inside 24h: "
              f"median time-to-peak {movers.ttp24.median():.1f}h, "
              f"median dip first {movers.mae24.median():+.2%}, "
              f"{(movers.mae24 <= -0.04).mean():.0%} would have hit the -4% "
              "stop before paying.")

    # ---- 3. perfect-exit ceiling ------------------------------------------
    print("\n" + "=" * 78)
    print("3. PERFECT-EXIT CEILING (sell the exact top; only a NEGATIVE result "
          "is decisive)")
    print("=" * 78)
    for arm in ("L", "D"):
        sub = trades[full & (trades.arm == arm)]
        fee = ARM_FEES[arm]
        for h in (24, 48):
            net = ratio_for_price(1.0, 1.0 + sub[f"peak{h}"], fee)
            print(f"  arm {arm} {h}h: {net.mean():+.2%}/trade  "
                  f"({net.sum():+.1%} summed over {len(sub)} trades)")

    # ---- 4. pre-registered exit grid --------------------------------------
    print("\n" + "=" * 78)
    print("4. HONEST COUNTERFACTUALS — pre-registered exit grid only (spec s3)")
    print("=" * 78)
    print(f"  Baseline recorded: {trades.recorded_profit.mean():+.2%}/trade "
          f"over {len(trades)} trades.\n")
    for arm in ("L", "D"):
        idx = [i for i, t in enumerate(trades.itertuples()) if t.arm == arm]
        sub = trades.iloc[idx]
        subw = [windows[i] for i in idx]
        fee = ARM_FEES[arm]
        print(f"  --- arm {arm} (fee {fee}/side, {len(sub)} trades) ---")
        rows = []
        for shape, roi in ROI_SHAPES.items():
            for trailing in (True, False):
                for stop_pct in (-0.04, -0.05):
                    res = [simulate(t.open_date, t.open_rate, w, fee,
                                    roi, stop_pct, trailing)
                           for t, w in zip(sub.itertuples(), subw)]
                    rows.append(summarise(
                        res, f"roi={shape} trail={'on' if trailing else 'off'} "
                             f"stop={stop_pct:.0%}"))
        rows.sort(key=lambda r: -r["per_trade"])
        print_table(rows)
        print()

    # ---- 4b. stagnation cut -----------------------------------------------
    print("  --- stagnation cut (Austin's gate amendment: off by default, "
          "{4,8,12}h are dev knobs) ---")
    print("  Held at trailing=off, stop=-4%. Median time-to-24h-peak is "
          f"{trades.loc[full, 'ttp24'].median():.1f}h and {movers.ttp24.median():.1f}h "
          "among the >=+4% movers, so a\n  short cut trades dead capital "
          "against killing late winners — which side wins is the question.\n")
    for arm in ("L", "D"):
        idx = [i for i, t in enumerate(trades.itertuples()) if t.arm == arm]
        sub, subw, fee = trades.iloc[idx], [windows[i] for i in idx], ARM_FEES[arm]
        print(f"  --- arm {arm} ---")
        rows = []
        for shape, roi in ROI_SHAPES.items():
            for stag in (None, 4, 8, 12):
                res = [simulate(t.open_date, t.open_rate, w, fee, roi, -0.04,
                                False, stagnation_h=stag)
                       for t, w in zip(sub.itertuples(), subw)]
                rows.append(summarise(
                    res, f"roi={shape} stagnation={stag or 'off'}"))
        rows.sort(key=lambda r: -r["per_trade"])
        print_table(rows)
        print()

    print("Reminder: every number above is IN-SAMPLE on the dev window. Picking "
          "an exit shape from this table is more fitted than a blind grid pick "
          "— log that in docs/backtests.md and hold the holdout to a higher bar.")


if __name__ == "__main__":
    main()
