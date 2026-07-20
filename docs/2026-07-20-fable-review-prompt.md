You are reviewing a quantitative trading research effort and deciding whether it
should be killed or continued. You have write access and I want you to use it.

I'm the owner of this project. A Claude Opus 4.8 session did the work and is
recommending we retire the whole strategy family after 3 of a pre-registered 15
experiments. That recommendation may be right, may be premature, and may rest on
diagnostics that are themselves wrong. Money and months ride on it, so I want an
independent reviewer who can open the code, re-run things, fix what's broken, and
come back with a verdict rather than a list of concerns.

## The project

Repo: `/Users/austinsandler/YOLO`, branch `main`, HEAD `68b2bd6`. Clean tree.

A Freqtrade bot for Kraken USD spot pairs, long only, $750 total cap. Paper
trading only; nothing is live. "Family A" is the current strategy: enter on a
15-minute range-coil breakout while BTC's 1-hour trend is up, with an anti-chase
cap at both signal and fill.

Three earlier families were tested and killed. Family A is the fourth.

## The decision on the table

Family A's dev results are negative on both universe arms:

| `range_lookback` | arm L per trade | arm D per trade |
|---|---|---|
| 32 | −0.61% | −1.33% |
| 48 (frozen default) | −0.90% | −1.28% |
| 96 | −0.84% | −1.16% |

The gate (spec §6) needs positive total profit AND a bootstrap 95% lower bound on
mean per-trade net above zero, plus ≥5 trades per week in up-regime periods.
Frequency passes everywhere. Profit fails every cell.

The Opus session recommends retiring family A in dev, writing a post-mortem, and
opening a family B spec. Retiring means the sealed holdout window
(2025-09 → 2026-01) is never run — only a family that survives dev earns it.

## The crux, and why I want you specifically

Spec §3 pre-registers a **hard budget of 15 dev iterations**. Three are used. The
Opus session argues the remaining space was measured without spending iterations:
the exit grid via a forward-path replay engine, the entry filters via a script
that re-scores the recorded trade population.

That argument has a hole the session already found and disclosed to me. Scoring
off the recorded population only works for *tightening* a filter, because a
tightening keeps a subset of trades that already happened. **Three pre-registered
cells are loosenings and were never tested at all:** `range_max_width` 0.08,
`volume_mult` 1.5, `max_extension` 0.02. Each needs a real backtest run. Twelve
iterations remain in the budget.

Worse for the kill recommendation: every tightening measured *worse* than
baseline. Read straight, that pattern points toward loosening helping — which is
an argument for running those three cells, not for retiring.

A second, smaller gap in the same direction: the stagnation timed cuts
{4h, 8h, 12h} were scored, but outside the replay engine's validated envelope —
the config as run had stagnation off, and `custom_exit` is modelled on the candle
close where Freqtrade may use the open. They read deeply negative, so the
modelling error probably does not flip them, but treat them as weaker evidence
than the rest and say so if you disagree.

So the first question is whether this family is actually dead or whether the
session talked itself into stopping early. I want you to answer that, not survey
it.

## What to review, in priority order

1. **Is retiring at 3/15 defensible?** Weigh the three untested loosening cells.
   If you think they should be run, say which, in what order, and what result
   would change the verdict. If you think retiring is right anyway, give the
   argument that survives the monotone-tightening pattern above.

2. **Do the diagnostics carry the weight put on them?** `replay_family_a.py`
   claims it reconstructs the live backtest engine to a mean absolute error of
   0.083% per trade. Nearly every conclusion in this effort rests on that. Check
   the within-candle exit ordering, the holdout seal guard, the trade-selection
   logic, the fee handling, and the acknowledged omission of slot contention.
   Does any conclusion flip inside that error band?

3. **Statistical power on the negative result.** Roughly 843 (arm L) and 720
   (arm D) dev trades. Is the negative finding itself solid, or is per-trade
   expectancy within noise of zero? Compute the interval rather than eyeballing
   it. A conclusion of "we cannot tell" is a real and useful answer here.

4. **The arm-disagreement argument.** The session treats "arm L's best lookback
   value is arm D's worst" as evidence the knob is noise. Two arms, 19 months,
   overlapping coins. Is that inference sound, or are the arms too correlated
   and the sample too short to support it?

5. **The structural stop.** An earlier sweep claimed to cover the exit grid but
   substituted a flat −5% stop for the spec's *structural* stop (signal-bar range
   low, capped at −5%). `scripts/path_analysis/structural_stop.py` closes that
   hole and finds the structural stop is *looser* than assumed — median depth
   −4.78%. Verify that number and the diagnostic stop-depth sweep beside it.

6. **Anything the whole effort has missed.** Look-ahead, leakage, survivorship,
   fee realism, and specifically the framing claim that a 0.9% (arm L) to 1.2%
   (arm D) round-trip fee against a +2.7% median 24-hour peak is most of why this
   family never had room to work.

7. **Honesty audit.** Check the claims in `docs/backtests.md` and in the commit
   messages against what the code and saved outputs actually show. This session
   has a known record of overstating: it twice claimed a review had run when none
   had, and it told me "no pre-registered knob remains" when three cells were
   untested. Find any other claim that outruns its evidence and correct it in
   place.

## Read these first

1. `docs/superpowers/specs/2026-07-20-yolo-family-a-range-breakout.md` — §3 knob
   discipline and budget, §4 the two arms, §6 the gate. This is the contract.
2. `docs/backtests.md` — the DEV results table and the three diagnostic sections
   at the end.
3. `scripts/path_analysis/replay_family_a.py` — module docstring states the seal
   contract; then `entry_quality.py` and `structural_stop.py`.
4. `docs/diagnostics/2026-07-20-family-a-*.txt` — saved raw outputs.
5. `.handoff/task.md` — the session ledger (gitignored). Treat its completion
   claims as leads, not proof.

## What you may change

Edit freely: anything under `docs/`, `scripts/`, and `tests/`. Write new
diagnostics if you need them. Re-run any script in `scripts/path_analysis/` or
`scripts/verify_*.py`; run `.venv/bin/pytest tests/` (37 tests currently pass).
Commit on `main` as you go.

Edit `user_data/strategies/momentum_signals.py` or `MemeMomentum.py` only to fix
a bug you can demonstrate with a failing test written first, and flag it loudly
in your summary. The values in `DEFAULT_PARAMS` are the frozen config — changing
one permanently is a scope change that needs my approval, though you may change
one temporarily to run a pre-registered iteration if you restore it afterward and
confirm `git diff` is clean.

## Hard limits

These are not preferences. Breaking any of them destroys work that cannot be
rebuilt.

- **Never run the holdout window 2025-09 → 2026-01, or the burned window
  2026-02 → 2026-07.** No backtest whose timerange touches or follows
  2025-09-01. The holdout is sealed by discipline: the candles sit on disk and
  nothing stops you but this instruction. One peek burns it permanently for every
  future strategy family, not just this one.
- Dev window is 2024-02 → 2025-08 only.
- If you run a Freqtrade backtest, log the hypothesis and the falsifier in the
  `docs/backtests.md` DEV table **before** the run, change exactly one knob, and
  count it against the 15-iteration budget. Three are used.
- `dry_run` stays true. No live API keys. Never weaken protections; pass
  `--enable-protections` on every run.
- Read backtest results from Freqtrade's stdout, never from `.last_result.json`
  (it is stale and has misled this project before).
- Never pass `--dl-trades` and do not download candle data. That flag's
  end-of-download conversion overwrites existing OHLCV files with a shorter
  trades-derived history.
- Do not modify or delete `user_data/backtest_baseline_iter1/`. It is the only
  surviving copy of the iteration-1 results; the directory those came from is
  gitignored and later runs overwrote it. Related: `replay_family_a.py` can no
  longer reproduce that baseline from `user_data/backtest_results/` and will
  hard-fail its selection count check. That failure is expected, not a bug to
  chase — re-point it at the snapshot if you need those numbers.
- Do not write to or push the Obsidian vault.
- Do not force-push, reset --hard, rewrite pushed history, or delete branches.

## How to work

When you have enough information to act, act. Do not re-derive facts already
established in the files, re-litigate decisions already made, or narrate options
you will not pursue. Where you are weighing a choice, give a recommendation
rather than an exhaustive survey.

Before reporting progress, audit each claim against a tool result from this
session. Report only what you can point to evidence for. If something is not yet
verified, say so. If a check fails, say so with the output; if you skipped a
step, say that; when something is verified, state it plainly without hedging.
This project's failure mode has been confident summaries that outran the
evidence, so an unverified claim from you costs more here than a gap.

Delegate independent subtasks to subagents and keep working while they run.
Intervene if one goes off track or lacks context.

Pause and ask me only if you hit something genuinely mine to decide: a scope
change, an irreversible action, or a judgment only I hold. Otherwise carry the
work to a conclusion. Before you end your turn, check your last paragraph — if
it is a plan or a promise to do something, do that work now instead.

## What I want back

Open with the verdict in one line: **GO** (retire family A now), **REVIEW**
(specific work must happen before the call), or **NO-GO** (the recommendation is
wrong and here is what to do instead).

Then, in plain English written for someone who did not watch you work:

- The reasoning behind the verdict, and the single strongest argument against it.
- Any conclusion in `docs/backtests.md` you found to be wrong or overstated, with
  what the evidence actually supports. Correct these in the file as you go.
- What you changed, and what you ran to check it.
- The exact next action, whether that is running specific iterations or writing
  the post-mortem.

Write complete sentences and spell out terms. Skip working shorthand, arrow
chains, and labels you coined mid-task.
