#!/usr/bin/env python3
"""Statistical weight of family A's negative dev result (review, 2026-07-20).

Three questions the DEV table asserts answers to without intervals:

1. Is per-trade expectancy actually below zero, or within noise of it?
   -> bootstrap 95% CI on mean per-trade net, per arm, per iteration cell.
2. Is the `range_lookback` cell ranking (L: 32>96>48, D: 96>48>32) a real
   ordering or noise? -> pairwise difference CIs within each arm.
3. The structural-stop tightness claims ("looser than -4% on 69%, cap binds
   on 46%") compared a NET-OF-FEES depth against GROSS stop levels. Recompute
   both fractions in price space, where "tighter/looser" actually lives.

Iteration cells are identified by zip timestamp group and cross-checked
against the counts in docs/backtests.md (843/720, 884/728, 689/659).
Reads recorded trades only; no candle at/after 2025-09-01 is touched (the
structural-stop section reads signal-bar rows inside the dev window only).

Usage: .venv/bin/python3 scripts/path_analysis/stats_check.py
"""
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from replay_family_a import (BASE, BASELINE_SNAPSHOT, DEV_START, SEAL_TS,  # noqa: E402
                             load_dev_trades, zip_meta)

RNG = np.random.default_rng(20260720)
N_BOOT = 10_000

# zip-name prefix ranges for the three iteration runs (timestamps from the
# DEV table readouts; verified below by count cross-check)
EXPECTED = {  # (iter, arm) -> (n_trades, sum_monthly_profit_pct)
    (1, "L"): (843, -76.40), (1, "D"): (720, -91.80),
    (2, "L"): (884, -53.97), (2, "D"): (728, -96.87),
    (3, "L"): (689, -58.01), (3, "D"): (659, -76.50),
}


def load_all_dev_zips() -> pd.DataFrame:
    manifest = {Path(line).name for line in
                (BASELINE_SNAPSHOT / "iter1_zip_manifest.txt")
                .read_text().splitlines() if line.strip()}
    rows = []
    for zp in sorted(BASE.glob("*.zip")):
        data, whitelist = zip_meta(zp)
        start = pd.Timestamp(data["backtest_start"], tz="UTC")
        end = pd.Timestamp(data["backtest_end"], tz="UTC")
        if start < DEV_START or end > SEAL_TS:
            continue
        arm = "L" if whitelist <= 30 else "D"
        for t in data["trades"]:
            rows.append({"zip": zp.name, "in_manifest": zp.name in manifest,
                         "arm": arm, "month": f"{start:%Y-%m}",
                         "profit": t["profit_ratio"],
                         "pair": t["pair"], "open_date": t["open_date"],
                         "open_rate": t["open_rate"]})
    return pd.DataFrame(rows)


def assign_iterations(df: pd.DataFrame) -> pd.DataFrame:
    """Iter 1 = the deduplicated baseline selection from load_dev_trades()
    (the manifest also holds the superseded 2024-11 smoke run, so raw manifest
    membership over-counts). Later zips split into runs: a new run starts when
    the (arm, month) pair repeats — one run per iteration per arm in timestamp
    order yields iteration groups 2 and 3."""
    baseline_zips = set(load_dev_trades().zip.unique())
    df = df.copy()
    df["iter"] = 0
    df.loc[df.zip.isin(baseline_zips), "iter"] = 1
    rest = df[~df.in_manifest]
    for arm in ("L", "D"):
        seen: dict[str, int] = {}
        for zp in sorted(rest[rest.arm == arm].zip.unique()):
            month = rest[rest.zip == zp].month.iloc[0]
            seen[month] = seen.get(month, 0) + 1
            df.loc[df.zip == zp, "iter"] = 1 + seen[month]
    return df


def boot_ci(x: np.ndarray, n=N_BOOT) -> tuple[float, float]:
    means = RNG.choice(x, size=(n, len(x)), replace=True).mean(axis=1)
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def main() -> None:
    df = assign_iterations(load_all_dev_zips())

    print("=" * 78)
    print("1. PER-CELL EXPECTANCY — mean per-trade net with bootstrap 95% CI")
    print("=" * 78)
    cells = {}
    for (it, arm), grp in df.groupby(["iter", "arm"]):
        x = grp.profit.values
        exp_n, _ = EXPECTED.get((it, arm), (None, None))
        tag = "OK" if exp_n == len(x) else f"MISMATCH expected {exp_n}"
        lo, hi = boot_ci(x)
        se = x.std(ddof=1) / np.sqrt(len(x))
        cells[(it, arm)] = x
        print(f"  iter {it} arm {arm}: n={len(x):4d} [{tag}]  "
              f"mean {x.mean():+.3%}  sd {x.std(ddof=1):.3%}  se {se:.3%}  "
              f"boot95 [{lo:+.3%}, {hi:+.3%}]  "
              f"{'CI excludes 0' if hi < 0 else 'CI REACHES 0'}")

    print()
    print("=" * 78)
    print("2. RANGE_LOOKBACK CELL DIFFERENCES — is the arm ranking real?")
    print("   (cells share the underlying window and many trades, so these")
    print("   independent-sample CIs UNDERSTATE the evidence needed; if even")
    print("   they include 0, the ordering claim has no support)")
    print("=" * 78)
    LOOKBACK = {1: 48, 2: 32, 3: 96}
    for arm in ("L", "D"):
        for a, b in ((2, 1), (3, 1), (2, 3)):
            xa, xb = cells[(a, arm)], cells[(b, arm)]
            d = xa.mean() - xb.mean()
            boots = (RNG.choice(xa, (2000, len(xa))).mean(axis=1)
                     - RNG.choice(xb, (2000, len(xb))).mean(axis=1))
            lo, hi = np.quantile(boots, [0.025, 0.975])
            print(f"  arm {arm}: lookback {LOOKBACK[a]} vs {LOOKBACK[b]}: "
                  f"diff {d:+.3%}  boot95 [{lo:+.3%}, {hi:+.3%}]  "
                  f"{'sign settled' if lo * hi > 0 else 'sign NOT settled'}")

    print()
    print("=" * 78)
    print("3. STRUCTURAL STOP — tightness recomputed in PRICE space")
    print("=" * 78)
    from structural_stop import structural_stops  # noqa: E402  (heavy import)
    iter1 = df[df.iter == 1].copy()
    iter1["open_date"] = pd.to_datetime(iter1.open_date, utc=True)
    stops = structural_stops(iter1)
    ok = stops.notna()
    entry = iter1.loc[ok, "open_rate"]
    stop_price = stops[ok]
    baseline_price = entry * 0.96          # gross -4% stop, same basis
    cap_price = entry * 0.95               # gross -5% cap
    gross_depth = stop_price / entry - 1
    tighter = (stop_price > baseline_price).mean()
    capped = (stop_price <= cap_price * 1.0000001).mean()
    print(f"  resolved {ok.sum()}/{len(iter1)} trades")
    print("  GROSS depth from entry: "
          + "  ".join(f"p{int(q*100)}={gross_depth.quantile(q):+.2%}"
                      for q in (0.1, 0.25, 0.5, 0.75, 0.9)))
    print(f"  tighter than the -4% baseline stop (price above entry*0.96): "
          f"{tighter:.0%}")
    print(f"  looser than baseline: {1 - tighter:.0%}")
    print(f"  -5% cap binds (range_low <= entry*0.95): {capped:.0%}")
    print("  (docs claimed: looser on 69%, cap binds on 46% — those numbers "
          "compared net-of-fee depth to gross levels)")


if __name__ == "__main__":
    main()
