"""Selection-aware statistics for family B phase 0 (spec s5, audit finding 1).

The gate tests the BEST of ~486 cell/arm/horizon looks, so an unadjusted
per-look confidence bound is near-vacuous. This module implements the
max-statistic (simultaneous / max-t) cluster bootstrap: resample calendar
months, compute every look's resampled mean, take the 95th percentile of the
max studentized deviation across looks, and back the selected look's mean off
by that amount. The resulting lower bound is valid for the data-selected look
because it is valid for ALL looks simultaneously.
"""
import numpy as np


def max_stat_bootstrap(looks, months, min_n=40, n_boot=2000, seed=20260722):
    rng = np.random.default_rng(seed)
    ids = sorted(looks)
    month_arrays = {j: {m: np.asarray(looks[j].get(m, []), dtype=float)
                        for m in months} for j in ids}
    n = {j: sum(len(a) for a in month_arrays[j].values()) for j in ids}
    mean = {j: (np.concatenate(list(month_arrays[j].values())).mean()
                if n[j] else np.nan) for j in ids}

    # bootstrap: resample the month list with replacement, all looks together
    boot = np.full((n_boot, len(ids)), np.nan)
    for b in range(n_boot):
        picks = rng.choice(len(months), size=len(months), replace=True)
        for k, j in enumerate(ids):
            arrs = [month_arrays[j][months[p]] for p in picks]
            flat = np.concatenate(arrs) if arrs else np.array([])
            if len(flat):
                boot[b, k] = flat.mean()

    se = {j: float(np.nanstd(boot[:, k], ddof=1)) for k, j in enumerate(ids)}
    eligible = {j: bool(n[j] >= min_n and se[j] > 0 and np.isfinite(mean[j]))
                for j in ids}
    elig_idx = [k for k, j in enumerate(ids) if eligible[j]]

    out = {"per_look": {j: {"n": n[j], "mean": float(mean[j]), "se": se[j],
                            "eligible": eligible[j]} for j in ids},
           "selected": None, "lb_selected": None,
           "q95_max_t": float("nan"), "naive_p5_of_max": float("nan")}
    if not elig_idx:
        return out

    sub = boot[:, elig_idx]
    centers = np.array([mean[ids[k]] for k in elig_idx])
    ses = np.array([se[ids[k]] for k in elig_idx])
    t_max = np.nanmax((sub - centers) / ses, axis=1)
    q95 = float(np.nanpercentile(t_max, 95))
    sel_k = elig_idx[int(np.nanargmax(centers))]
    sel = ids[sel_k]
    out["selected"] = sel
    out["q95_max_t"] = q95
    out["lb_selected"] = float(mean[sel] - q95 * se[sel])
    out["naive_p5_of_max"] = float(np.nanpercentile(np.nanmax(sub, axis=1), 5))
    return out
