# USD100 Valetax scalp grid

This is offline research and demo work. It does not enable a live strategy or change production. Read `GOLDSIGNAL-SCALP-TIMING-CORRECTION.md` first: the original timing results were invalid for late eligibility.

## Frozen experiment

The raw grid contains 960 combinations: three setup families × five lookbacks × four confirmations × four natural stops × four single-exit reward policies. Family-aware normalization removes 80 equivalent pullback confirmations, leaving 880 canonical configurations. Sorted canonical configuration JSON removes duplicate definitions; IDs are content hashes. The five shared timing/cost scenarios are stress tests, not extra strategies or tunable axes. Zero-fill configurations cannot pass.

All variants start each development/validation window with USD100. Planned risk is 1% of current closed equity, with fixed 0.01 lot. Free margin is approximated by closed equity because one pending/active opportunity is allowed. There are at most two submissions per rolling hour and a 3% daily realized loss stop. Stop risk is computed from executable ask for buys or bid for sells to the strategy's natural stop, plus commission and adverse slippage. Stops are never tightened to fit the budget. Actual gap losses can exceed planned risk.

Every candidate receives a first-blocker record. The ledger also preserves hypothetical user-action eligibility for candidates blocked before publication. A price-valid opportunity can fail cash risk, margin or broker volume. A subsequent price leaving the zone is not mislabeled as its first failure if risk already blocked submission. Gate failures before any eligible quote use the first available quote's failing gate, not the most frequent failure later in the window.

The current three-target partial policy is compared separately at the same 0.01-lot entry. Three broker-valid partials need at least 0.03 lot. A single 0.01-lot exit is volume-valid, but still must pass stop-risk and margin checks. The partial counterfactual does not enter trades with unsupported fractional lots.

## Exact setup definitions

All signals use completed candles only, with consecutive M1, M5 and M15 history. A fresh in-session M5 setup can seek an M1 confirmation during its next five minutes. One opportunity per M5 setup and direction is retained, at the earliest confirming M1 close. Entry spans the M1 close to 0.25R in the favorable direction. Expiry is the earliest of confirmation plus two minutes, M5 setup close plus five minutes, and the existing New York cutoff. Holding limit is 30 minutes.

Lookbacks are 3, 6, 9, 12 or 18 preceding M5 bars:

- **Breakout/retest:** last M5 body breaks the preceding range in the M15 direction. M1 tests the boundary within 20% of the preceding average M5 range and closes on the breakout side. M15 direction is last minus first close of four completed candles.
- **Trend pullback:** M15 direction and preceding M5 net movement agree. Latest M5 body opposes them. The confirming M1 resumes direction and closes beyond the preceding M1 high/low.
- **Range reversal:** absolute M15 close change is at most 25% of the preceding M5 range. Latest M5 sweeps the range edge and closes back inside it. M1 confirms reversal direction.

Confirmations all require a body in trade direction, plus one of:

- `body`: no additional candle condition.
- `engulf`: current real body contains the previous M1 real body.
- `close_break`: close exceeds previous M1 high/low in trade direction.
- `wick`: rejection tail is at least body size, and close is in the favorable outer third of the candle.

Natural stops use the adverse extreme of the triggering M1, setup M5, last two M1 candles, or last three M5 candles. Buffer is max(0.10, 10% of those candles' average range). Exit is one complete 0.01-lot close at 0.5R, 1R, 1.5R or 2R from the signal reference, or natural stop/timeout. Realized reward depends on actual executable fill and exit quotes. The existing partial policy retains its original stops and target progression in the separate baseline timing replay.

The grid uses configured global MAX_SPREAD, held constant across variants. It does not silently inherit the existing scalp's strategy-specific 0.20R spread ceiling. That difference is explicit: these are complete research strategies, not claims that only delivery changed.

## Shared timing and cost scenarios

Review latency is zero in the deterministic grid. Local processing starts after eligibility and lasts two seconds, followed by a fresh publication recheck. Failed rechecks wait for another eligible quote and repeat processing before a first valid submission. User action is the first executable-side tick after submission plus the post-submission delay. No later re-entry rescues a failed action quote. All durations are assumptions.

| Scenario | Processing | Submission to action | Commission, USD/lot round trip | Adverse slippage, price |
|---|---:|---:|---:|---:|
| Base | 2s | 5s | 7 | 0.10 |
| Slow | 2s | 30s | 7 | 0.10 |
| Cost | 2s | 5s | 14 | 0.20 |
| Slow and cost | 2s | 30s | 14 | 0.20 |
| Zero commission | 2s | 5s | 0 | 0.10 |

Actual configured account commission is unverified. These are explicit scenarios, not broker fee claims. Actual bid/ask includes spread separately. Margin and contract specifications are current snapshots. USD100 at 1% means a USD1 initial risk budget. At 0.01 lot and the archived 100-ounce contract, the base assumptions leave approximately USD0.83 of price distance to the natural stop before planned cash risk exceeds USD1.

## Data admission before the search

The original November 4–18 archive supplied 11 sessions. Additional genuine Valetax exports were accessed before the full grid:

- November 3: 201,207 ticks, maximum gap 12.156 seconds; admitted.
- November 2: 219,030 ticks, two gaps above 20 seconds, maximum 107.936 seconds; excluded.
- October 30: 235,065 ticks, maximum gap 6.581 seconds; quarantined because historical broker offset before the US DST transition is unverified.

Five-minute samples on October 29, October 1, September 1, August 3, July 1 and January 5 returned no ticks during the probe. Some candles were available. This does not prove all older broker history is absent. No proxy quotes or candle-synthesized ticks were used. Coverage counts were inspected; no older strategy returns were used to choose settings.

The admitted archive has 2,613,176 ticks across 12 sessions. Symbol is Valetax `XAUUSD.vx`; terminal account mode was demo, account/profit currencies USD, contract 100 ounces, minimum and step 0.01 lot. New York sessions use existing session configuration intersected with broker hours and cutoff buffer. Bid/ask, millisecond row order and gaps were checked. The economic calendar is the current cached schedule, not a verified point-in-time archive. Headline/geopolitical filters are omitted. These limitations prevent a claim of historically complete news protection.

## Chronological selection

Development: seven admitted sessions, November 3–11. Validation window 1: November 12–13, two sessions. Validation window 2: November 16–18, three sessions. Existing November history was previously inspected for debugging and baseline research; it is not a fresh final holdout.

Before full search, the plan freezes these requirements:

- Development: at least 10 completed trades, positive mean net after costs, at least 0.5 executable entries/session, closed-equity drawdown at most USD10, and worst losing streak at most five.
- Rank eligible development configurations by entries/session, then mean net, lower drawdown and shorter losing streak. Freeze at most 20 before validation.
- Each validation window: at least five completed trades and the same quality thresholds. Both windows must pass; aggregate profitability cannot hide a losing window.
- Slower opens, higher costs and their combination must also pass both validation windows. All development configurations receive the same five scenarios; validation is reserved for the frozen development shortlist.
- Freeze successful finalists before any genuinely fresh, future completed New York session data is collected. Never retune or replace them using final results. An empty shortlist has nothing to evaluate on the final period.

The plan, code hash, configuration list and criteria are written before the grid executes. Minimum counts are screening rules, not proof of profitability. Wilson win-rate intervals are descriptive and unadjusted for 960 comparisons. Closed-trade drawdown omits intratrade mark-to-market. Low counts and multiple testing remain material uncertainty.

## Commands and artifacts

NumPy is already present with the Windows MT5 environment; no paid API or new backend dependency was added. Run from this repository with the existing symbol/session configuration. Output paths must be new.

```powershell
.venv\Scripts\python.exe -m goldsignal.scalp_grid --archive .research/scalp-grid-verified --output .research/scalp-grid-new --limit 960
$env:PYTHON_DOTENV_DISABLED='1'
.venv\Scripts\python.exe -m pytest -q
```

The verified archive combines the original export with admitted November 3 data. Excluded November 2 and October 30 remain separate for auditing. Use the existing `scalp_research export` command to acquire additional genuine broker history; do not remove missing intervals or rewrite timestamps to make it pass coverage checks.

Completed run directory: `.research/scalp-grid-960-v1/`. `plan.json` freezes definitions and assumptions. `candidate-ledger.jsonl.gz` logs every strategy/candidate/scenario and its first failure, price-side risk, partial-volume counterfactual and timing. `results.json` contains metrics and ranking. `development-shortlist.json` freezes the next stage. `frozen-finalists.json` prevents final-period setting selection. All market archives stay outside Git.

See the appended measured results for the stage counts and conclusion. The fresh-session instrumentation plan is in `GOLDSIGNAL-SCALP-TIMING-CORRECTION.md`.

## Measured results

The original Cartesian grid generated 960 combinations. A logical alias was identified: the pullback trigger already requires a close-break, so its `body` and `close_break` confirmations are identical by definition. Removing those 80 aliases leaves **880 rule-distinct configurations**. No thresholds or setups were changed after inspecting returns. The audited run reuses identical already-tested executions, filters out alias IDs, and recounts actual publications from the ledger. It does not run a new search on evaluation data.

The 880 definitions produced 317 distinct observed development-ledger behavior groups. Some genuinely different rules happen to behave identically on this short sample. These groups do not establish future equivalence. The CSV labels them; repeated behavior is not independent evidence. The displayed ranking below shows one representative per observed group.

| Stage | Count |
|---|---:|
| Raw generated combinations | 960 |
| Canonical rule-distinct configurations | 880 |
| Nonzero completed development fills | 368 |
| Zero completed fills, ineligible | 512 |
| Passed frozen development screen | 0 |
| Entered validation windows | 0 |
| Passed validation / slower opens / higher costs | 0 |
| Entered fresh final evaluation | 0 |

All 368 nonzero base configurations had fewer than ten completed development trades. The most active had eight across seven sessions. Thirty-seven showed positive development mean net, but none had enough completed trades to pass. That is insufficient evidence, not proof that every rule is intrinsically unprofitable. Validation consistency remains unmeasured because no configuration earned access to that stage. The known validation windows were not opened for grid strategy selection. There are no finalists to test on a fresh final period.

### Shared stress scenarios

Counts are configurations, not independent trading records. Positive mean alone is not a pass.

| Scenario | Nonzero configurations | Positive mean net | Maximum completed trades/configuration | Passed frozen development screen |
|---|---:|---:|---:|---:|
| base | 368 | 37 | 8 | 0 |
| slow | 224 | 19 | 2 | 0 |
| cost | 240 | 10 | 4 | 0 |
| slow_cost | 68 | 0 | 1 | 0 |
| zero_commission | 420 | 57 | 9 | 0 |

### Development ranking, descriptive only

Ranking prioritizes entries/session, then mean net, lower closed-equity drawdown and shorter losing streak. These are failed-screen diagnostics, not recommended strategies. All amounts are USD on the simulated USD100 account.

| Configuration | Family / lookback / confirmation / stop / exit R | Completed | Entries/session | Mean net | Total net | Drawdown | Worst losing streak | Win rate, 95% Wilson interval |
|---|---|---:|---:|---:|---:|---:|---:|---|
| b580ef0ac8c4 | trend_pullback / 6 / body / trigger / 1.5 | 8 | 1.143 | -0.09 | -0.72 | 2.08 | 2 | 37.5%, [13.68, 69.43] |
| 8c3ad20ddf4b | trend_pullback / 6 / body / trigger / 1 | 8 | 1.143 | -0.22 | -1.76 | 2.64 | 2 | 37.5%, [13.68, 69.43] |
| 15f6b9c458a7 | trend_pullback / 6 / body / trigger / 2 | 8 | 1.143 | -0.24 | -1.89 | 4.01 | 5 | 25.0%, [7.15, 59.07] |
| b4fa24794da3 | trend_pullback / 6 / body / trigger / 0.5 | 8 | 1.143 | -0.36 | -2.87 | 3.34 | 2 | 37.5%, [13.68, 69.43] |
| 66d1c262ded3 | trend_pullback / 9 / body / setup / 2 | 7 | 1.0 | -0.22 | -1.51 | 2.55 | 3 | 28.57%, [8.22, 64.11] |
| bba47a4d5966 | trend_pullback / 12 / body / setup / 2 | 7 | 1.0 | -0.22 | -1.51 | 2.55 | 3 | 28.57%, [8.22, 64.11] |
| 9e489247a6b2 | trend_pullback / 9 / body / trigger / 1.5 | 7 | 1.0 | -0.25 | -1.77 | 3.04 | 3 | 28.57%, [8.22, 64.11] |
| 85403230b9b0 | trend_pullback / 9 / body / trigger / 0.5 | 7 | 1.0 | -0.31 | -2.14 | 2.61 | 2 | 42.86%, [15.82, 74.95] |
| 29132d9864d2 | trend_pullback / 9 / body / setup / 1.5 | 7 | 1.0 | -0.31 | -2.18 | 2.71 | 3 | 28.57%, [8.22, 64.11] |
| fbe0967e814e | trend_pullback / 12 / body / setup / 1.5 | 7 | 1.0 | -0.31 | -2.18 | 2.71 | 3 | 28.57%, [8.22, 64.11] |

### First blocking constraints

These counts sum candidate/configuration pairs in the base development scenario. Related variants often examine the same underlying move; do not interpret the totals as unique market opportunities.

| First blocker | Count |
|---|---:|
| Minimum lot exceeds your risk limit | 23211 |
| Executable quote is outside the entry zone | 5450 |
| No valid submission before expiry | 3168 |
| Calendar pause | 360 |
| Two per hour cap or existing exposure | 215 |
| Entry session or candidate expired | 20 |

Minimum-lot stop risk accounts for 71.6% of blocked candidate/configuration pairs. Margin did not appear as a first blocking gate under the archived current margin assumptions. The ledger retains the price-side budget calculation for each risk-tested candidate.


The partial-exit counterfactual recorded 1,960 pairs whose first failure was unsupported three-way volume; its own earlier risk failures remain separate. No three-way exit can be executed from 0.01 lot with a 0.01-lot broker minimum. Single exits recovered some volume-valid entries, but did not produce a qualifying strategy. A zero-fill partial policy has no win rate or expectancy to compare; do not report it as a zero-risk success.

Partial first-blocker counts are matched to the single-exit branch's equity and opportunity stream. They are not an independent partial-portfolio equity simulation; an unsupported partial portfolio would take no fills and remain at USD100.

## Conclusion and next evidence

**No variant passes.** Minimum-lot natural-stop risk is the largest opportunity constraint. Sparse completed trades prevent a defensible quality conclusion; slower opens and higher costs reduce activity further. Under combined slow/high-cost stress, no configuration has positive mean net in this sample.

Do not lower the ten-trade screen, tighten stops to force USD1 risk, pick the best tiny-sample return, or treat the same historical period as a fresh holdout. More genuine, timestamp-verified Valetax ticks across several market regimes could establish whether any candidate can meet the frozen count and expectancy requirements. Additional data cannot itself remove the minimum-lot risk constraint. Verify historical broker UTC offsets, real account commission and historical symbol/margin conditions. A point-in-time economic-event archive is also missing.

The next demo sample should record actual push submission, service-worker push handling, notification click and server entry-open times, as specified in the timing correction report. Use the existing phone channel on a separate demo instance. If a future development/validation sample yields finalists, freeze their definitions first, then collect a genuinely uninspected final session period. This run's finalist list is empty; no final-data returns were manufactured or inspected.

## Audited deliverables

Use `.research/scalp-grid-880-audited/results.json` and its `candidate-ledger.jsonl.gz`: 166,320 retained strategy/candidate/scenario rows. `plan.json` links the original pre-search plan hash and records the canonicalization and replay-engine hash. `development-shortlist.json` and `frozen-finalists.json` are empty. The original raw 960 run remains preserved for audit.

`GOLDSIGNAL-SCALP-GRID-RANKING.csv` contains every nonzero canonical base configuration and observed behavior group. Zero-fill configurations remain in results.json with rejection diagnostics. `GOLDSIGNAL-USD100-FIRST-GATES.csv` audits the original baseline candidates separately. `GOLDSIGNAL-SCALP-TIMING-TRACES.csv` identifies which original 13 fills survive corrected timing.

To reproduce the deterministic alias/publication audit without rerunning identical tick executions:

```powershell
.venv\Scripts\python.exe -m goldsignal.scalp_grid --audit-previous .research/scalp-grid-960-v1 --output .research/scalp-grid-audit-new
```

For a clean replay, use the earlier grid command; the updated generator produces 880 canonical definitions from the raw 960 combinations. Output paths refuse overwrite. These are local artifacts, not a committed or deployed live upgrade.

Validation: 40 tests passed, including late eligibility followed by a missed phone entry, failed publication recheck after processing, executable-side risk, single-versus-partial volume, margin, action-time risk recheck, zero-fill exclusion and canonical alias removal. Python compilation and Git whitespace checks passed. Existing FastAPI test-client dependency emits one deprecation warning. Frontend was not changed, so no UI build was required.

Files added/updated for research: `.gitignore`, `goldsignal/scalp_research.py`, `goldsignal/scalp_timing_replay.py`, `goldsignal/scalp_grid.py`, focused tests, this report, the timing correction report and CSV audits. Existing worker, API, alerts, strategy, lifecycle, authentication, deployment and frontend files remain unchanged. Core research used no paid APIs and no Gemini requests.
