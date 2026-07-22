# Family B sealed-rerun comparison — 2026-07-22

- Original report SHA-256: `c8815aa387fbeed7f5870808b432f302c81b66fecb76d9e3513a529f9c28798a`
- Original CSV SHA-256: `3512eaa8ac19c995d9048d790e73d48fb036dca49667912425571d734590304e`
- Sealed rerun report SHA-256: `95d799e6d187697706f55653ceff58324f76abc1d6616babc0f299f4121357aa`
- Sealed rerun CSV SHA-256: `3512eaa8ac19c995d9048d790e73d48fb036dca49667912425571d734590304e`

The CSV artifacts are byte-for-byte identical (`cmp` exit 0). The reports have
one textual difference: the final `CSV written:` line names the sealed-rerun
CSV. All calculated values and the FAIL verdict are identical.

Physical dev-dataset validation: 628 manifest-pinned Feather files,
18,420,166 rows, and zero timestamps at or after `2025-09-01T00:00:00Z`.
Neither Docker nor Freqtrade was started for this replay.
