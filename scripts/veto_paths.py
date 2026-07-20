#!/usr/bin/env python3
"""24h path of vetoed entries (family A spec s3 auditor pin): if the best
movers gap through the anti-chase cap, this family repeats b''s missed-mover
failure from above instead of below — measure it, don't assume.

For each ENTRY-VETO line in the given .log files: what would buying the vetoed
gap-fill have done over the next 24h? Reports per veto the max favorable /
adverse excursion from the vetoed fill price and the 24h close, then a one-line
verdict of what the cap saved or cost in aggregate.

Usage: veto_paths.py run1.log [run2.log ...]
"""
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)

import pandas as pd  # noqa: E402

DATA = Path("user_data/data/kraken")

VETO_RE = re.compile(
    r"ENTRY-VETO pair=(?P<pair>\S+) fill=(?P<fill>\S+) cap=(?P<cap>\S+) "
    r"time=(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\+\d{2}:\d{2})"
)


def parse_veto_lines(log_text: str) -> list[dict]:
    out = []
    for m in VETO_RE.finditer(log_text):
        cap = m.group("cap")
        out.append({
            "pair": m.group("pair"),
            "fill": float(m.group("fill")),
            "cap": None if cap == "none" else float(cap),
            "time": pd.Timestamp(m.group("time")),
        })
    return out


def path_24h(pair: str, t0: pd.Timestamp, fill: float) -> dict | None:
    f = DATA / f"{pair.replace('/', '_')}-15m.feather"
    if not f.exists():
        return None
    df = pd.read_feather(f, columns=["date", "high", "low", "close"])
    df["date"] = pd.to_datetime(df["date"], utc=True)
    win = df[(df["date"] >= t0) & (df["date"] < t0 + pd.Timedelta(hours=24))]
    if win.empty:
        return None
    return {
        "mfe_pct": (win["high"].max() / fill - 1) * 100,
        "mae_pct": (win["low"].min() / fill - 1) * 100,
        "close24_pct": (win["close"].iloc[-1] / fill - 1) * 100,
    }


def main():
    vetoes = []
    for lp in sys.argv[1:]:
        vetoes.extend(parse_veto_lines(Path(lp).read_text()))
    if not vetoes:
        print("No ENTRY-VETO lines in the given logs.")
        return
    rows = []
    for v in vetoes:
        p = path_24h(v["pair"], v["time"], v["fill"])
        if p is None:
            continue
        rows.append({**v, **p})
    d = pd.DataFrame(rows)
    print(d.to_string(index=False,
                      formatters={"mfe_pct": "{:+.2f}".format,
                                  "mae_pct": "{:+.2f}".format,
                                  "close24_pct": "{:+.2f}".format}))
    print(f"\n{len(d)} vetoed fills: median 24h close {d['close24_pct'].median():+.2f}% "
          f"(median MFE {d['mfe_pct'].median():+.2f}%, median MAE "
          f"{d['mae_pct'].median():+.2f}%)")
    print("Positive median close = the cap is costing movers (b' failure from "
          "above); negative = the cap is refusing bad chases, as designed.")


if __name__ == "__main__":
    main()
