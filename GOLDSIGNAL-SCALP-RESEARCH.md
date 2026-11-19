> Superseded: timing and executable-price risk conclusions are corrected in [GOLDSIGNAL-SCALP-TIMING-CORRECTION.md](GOLDSIGNAL-SCALP-TIMING-CORRECTION.md). Do not use the original latency comparison for strategy selection.

# Goldsignal scalping research, 19 November 2026

## Verdict

Faster action recovered executable entries. It did not establish a high-confidence profitable strategy. Keep production unchanged. Variant B merits a measured demo phone test; C does not pass the evaluation. No paid API calls, Gemini requests, orders, or push messages were made by this experiment.

This upgrade is an offline research command, not an enabled live strategy. M5 defines the scalp setup, M1 confirms entry, and M15 supplies trend context. The extra hypothesis also uses H1 direction. Targets use the existing 1R, 1.5R, 2R schedule with partial exits and a 30-minute hold limit.

## Data and audit

Actual Valetax MT5 XAUUSD.vx bid/ask history: 2,411,969 normalized ticks across 11 New York sessions, 4–18 November 2026. Development: six sessions before 12 November; evaluation: five sessions from 12 November. No proxy feed was used. Millisecond timestamps retain broker row order within equal timestamps. Every session had zero normalized invalid quotes, exact duplicates, and gaps over 20 seconds. Largest observed gap: 19.330 seconds. These checks do not prove the broker returned every original tick; raw invalid rows removed during normalization cannot be counted retrospectively.

Local inputs: `.research/scalp-20261119/manifest.json`, `candles.json`, and daily `*.ticks.csv.gz`. The terminal was accessed, not inferred from a website. Account mode: demo; account and symbol profit currencies: USD. Account commercial subtype and actual commission were not verified. Current symbol snapshot: minimum 0.01 lot, step 0.01, maximum 50 lots, contract 100 ounces. Current margin rate is an estimate, not historical margin. Assumed commission: USD0 per lot round trip; assumed round-trip adverse slippage: USD0.10 in price. Bid/ask includes spread separately. Double-cost sensitivity doubles that slippage; doubling zero assumed commission does not validate actual broker fees.

Research uses configured America/New_York 08:00–17:00 intersected with broker hours, including the existing cutoff buffer. Current broker-hours configuration: 00:00–17:00 and 18:00–24:00 New York time. Broker clock offset: 7,200 seconds, verified against a fresh quote at export. Historical offset changes were not independently verified. Test sessions are after the November US DST transition. Candle warmup extends seven calendar days before the first session.

Production still supports its configured sessions and both existing signal lanes. This experiment isolates the existing M5/M1 scalp; it is not an M15-baseline replay. The previous session-coverage report counted setups, not executable returns. The two-alert rolling-hour cap is retained. Research additionally permits one pending/active opportunity across directions to prevent overlapping exposure; that stricter rule means this is not an exact production portfolio replay. Consecutive closed-candle rules remain unchanged. No reopening-gap relaxation was tested: the inspected NY scalp diagnostics did not show missing-consecutive-bar rejections. Scheduled closures must not be filled with fabricated candles.

Calendar input is the current local cache, not a point-in-time historical event archive. Existing high-impact pause windows are reused. Retail sales, PPI and FOMC minutes blocked candidates in this sample. Historical completeness and revisions are unverified, so the results cannot establish historical news-filter coverage. Geopolitical headlines and retrospective manual pauses are excluded.

Sources accessed: [MT5 tick history](https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksrange_py), [symbol specifications](https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py), [Valetax metals](https://valetax.com/trading-instruments/metals/), [Valetax standard account description](https://valetax.com/account-types/standard/), [BLS calendar](https://www.bls.gov/schedule/news_release/bls.ics), [BEA schedule](https://www.bea.gov/news/schedule/full), [Federal Reserve calendars](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm). The standard-account page does not identify this terminal account subtype.

## Frozen comparisons

A: existing breakout/retest with assumed 30-second total candidate-to-action delay. B: identical candidates and rules with assumed 5-second delay. A is a timing scenario, not a measured reconstruction of all current phone delivery stages. Both also run paired 5, 15, 30 and 60-second sweeps. C adds one M5 pullback/M1 resumption hypothesis to B, adapted to the user's scalping clarification instead of the brief's initial M15 pullback suggestion.

C requires four consecutive closed M15 and H1 candles with same-sign first-to-last close movement. Latest closed M5 body must oppose that direction. A subsequent closed M1 within the next five minutes must resume direction and close beyond the preceding M1 high/low. Stop extends past the M5/M1 extreme by max(0.10, 10% of M5 range). Entry spans reference to 0.25R favorable; expiry is two minutes or session cutoff, whichever is earlier. Spread cannot exceed min(configured maximum, 0.20R). One candidate per M5 candle/direction; earliest qualifying M1 confirmation wins. No unfinished or future candle is read.

An alert opportunity starts at its first gate-valid quote. Action is the first tick at or after max(confirmation plus assumed delay, first valid quote). It never waits for a later re-entry after that action tick. Recheck zone, spread, freshness, expiry, calendar, and account sizing then. This models an immediate alert when eligible with a minimum total delay; it does not add simulated delivery delay twice. Missing observed review-start/end, push-submission and actual phone-receipt timestamps remain unknown. Provider acceptance is not proof of phone receipt. Existing saved notification-open records are preserved in the archive, but do not identify every delivery stage.

Rows are ordered by first eligible alert time and candidate ID. Suppress during existing exposure or after two alerts in a rolling hour. Reuse production executable price sides, lifecycle stops and partial exits. Positive net after costs defines a win, even when final status is STOPPED after partial profits. Drawdown below uses closed trade equity, not intratrade mark-to-market. An incomplete final fill is counted executable but excluded from completed-return statistics. Small-account runs use fixed equity/free margin, 1% risk, 3% tracked daily loss limit, and three broker-valid partial exits. They do not simulate deposits, changing leverage or equity compounding.

The chronological split is reproducible but not a genuinely untouched holdout: parts of this historical period and four alerts were already inspected before this experiment. No strategy thresholds were tuned against these P&L results. A future prospective interval remains required.

## Evaluation results

Five sessions. Strategy-per-lot results are USD per one-lot exposure, diagnostic only. They bypass account sizing and are not a recommendation to trade one lot.

| Variant | Candidates | Alerts | Executable / session | Executable % | Completed | Win rate (95% Wilson interval) | Mean net | Total net | Closed drawdown |
|---|---:|---:|---:|---:|---:|---|---:|---:|---:|
| A, 30s | 40 | 21 | 1.0 | 23.81 | 5 | 40.0% (11.76–76.93%) | -67.2 | -336.0 | 774.33 |
| B, 5s | 40 | 21 | 2.6 | 61.9 | 13 | 46.15% (23.21–70.86%) | 14.51 | 188.66 | 1410.33 |
| C, 5s | 133 | 55 | 7.6 | 69.09 | 37 | 43.24% (28.67–59.09%) | -19.69 | -728.68 | 3251.0 |

B versus A recovered eight net additional fills (13 versus 5), with the same 40 candidate stream. Its per-lot drawdown increased substantially. C versus B added 93 candidates and 25 executable entries, including one incomplete fill, while net return worsened. More alerts did not improve quality.

### Account-qualified evaluation

| Variant | Account | Published alerts | Executable | Completed | Win rate | Total USD net | Closed USD drawdown | Double-cost total USD net |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| A | USD100_1pct | 16 | 0 | 0 | None | 0 | 0 | 0 |
| A | USD1000_1pct | 20 | 4 | 4 | 50.0 | -2.08 | 12.61 | -2.4 |
| B | USD100_1pct | 8 | 0 | 0 | None | 0 | 0 | 0 |
| B | USD1000_1pct | 17 | 9 | 9 | 44.44 | -7.36 | 27.88 | -6.98 |
| C | USD100_1pct | 29 | 0 | 0 | None | 0 | 0 | 0 |
| C | USD1000_1pct | 42 | 22 | 21 | 28.57 | -81.71 | 89.38 | -85.69 |

All USD100 actionable entries failed minimum-lot risk checks. Alerts in that row can still be missed before reaching a risk check; they do not represent sized entries. Some USD1000 entries failed the three-part broker volume requirement. Double costs can change rounded position size, daily risk stops and the admitted trade set; account returns need not worsen monotonically.

### Delay sensitivity, strategy per lot

| Variant | Total delay | Completed | Mean USD net | Total USD net | Closed USD drawdown |
|---|---:|---:|---:|---:|---:|
| A | 5s | 13 | 14.51 | 188.66 | 1410.33 |
| A | 15s | 5 | 80.67 | 403.33 | 846.0 |
| A | 30s | 5 | -67.2 | -336.0 | 774.33 |
| A | 60s | 2 | -292.5 | -585.0 | 585.0 |
| B | 5s | 13 | 14.51 | 188.66 | 1410.33 |
| B | 15s | 5 | 80.67 | 403.33 | 846.0 |
| B | 30s | 5 | -67.2 | -336.0 | 774.33 |
| B | 60s | 2 | -292.5 | -585.0 | 585.0 |
| C | 5s | 37 | -19.69 | -728.68 | 3251.0 |
| C | 15s | 27 | -21.86 | -590.34 | 3395.33 |
| C | 30s | 21 | -57.54 | -1208.34 | 2861.0 |
| C | 60s | 19 | -71.12 | -1351.34 | 2886.34 |

A and B are identical at the same delay by design. Development results, every candidate outcome, per-setup records, rejection counts, both account scenarios and all sweeps are stored in the JSON artifacts. Main per-lot double-cost totals: A USD-386.0, B USD58.66, C USD-1098.68.

### Main rejection reasons

A: outcomes {'missed': 16, 'blocked': 17, 'filled': 5, 'suppressed': 2}. Reasons: {'Executable quote is outside the entry zone': 16, 'Spread exceeds configured limit': 16, 'STOPPED': 5, 'Calendar pause: Retail sales': 1, 'Two per hour cap or existing exposure': 2}.

B: outcomes {'missed': 8, 'filled': 13, 'blocked': 17, 'suppressed': 2}. Reasons: {'Executable quote is outside the entry zone': 10, 'COMPLETED': 1, 'Spread exceeds configured limit': 14, 'STOPPED': 12, 'Calendar pause: Retail sales': 1, 'Two per hour cap or existing exposure': 2}.

C: outcomes {'filled': 37, 'missed': 17, 'suppressed': 44, 'blocked': 34, 'incomplete': 1}. Reasons: {'STOPPED': 34, 'Executable quote is outside the entry zone': 23, 'Two per hour cap or existing exposure': 44, 'COMPLETED': 2, 'Spread exceeds configured limit': 24, 'Calendar pause: PPI · Producer Price Index': 2, 'TIMED_OUT': 1, 'Calendar pause: Retail sales': 1, 'Tick archive ends before exit': 1, 'Calendar pause: FOMC Minutes': 1}.

## Original four alerts

Reproduced 0/4 inside their zones at the first broker quote at recorded publication plus 30 seconds. Timing starts at persisted publication, not candle close. The following times are MYT, with milliseconds. First interval end means the first subsequent gate failure; later re-entries can occur. It is not a claim of permanent invalidation.

| ID | M1 confirmation | First executable | First interval ceased | Publication | Confirmation to publication |
|---|---|---|---|---|---:|
| s1795008300B | 18 Nov 21:26:00.000 | 18 Nov 21:26:00.641 | 18 Nov 21:26:06.797 | 18 Nov 21:26:02.903 | 2.904s |
| s1795009500B | 18 Nov 21:47:00.000 | 18 Nov 21:47:18.471 | 18 Nov 21:47:18.507 | 18 Nov 21:47:40.723 | 40.723s |
| s1795009800B | 18 Nov 21:52:00.000 | 18 Nov 21:52:24.462 | 18 Nov 21:52:40.867 | 18 Nov 21:52:31.827 | 31.827s |
| s1795017900S | 19 Nov 00:07:00.000 | 19 Nov 00:07:00.098 | 19 Nov 00:07:00.210 | 19 Nov 00:07:51.576 | 51.577s |

Confirmation-to-publication spans are observable aggregate delays, not separate measurements of Python processing, Gemini, push delivery or reaction time. Several first executable intervals are extremely short. Their existence does not establish that a human could trade them. Delayed review and price leaving the zone are meaningful bottlenecks; no zone widening or expiry extension was silently applied.

## Reproduce

Run from the repository with the existing environment and Valetax terminal open for export. Replay itself needs only archive files and the same symbol/session configuration. Existing archive/output paths are exclusive: choose a new path for another export or run.

```powershell
.venv\Scripts\python.exe -m goldsignal.scalp_research export --start 2026-11-04 --until 2026-11-18T18:00 --commission 0 --slippage 0.10 --archive .research/scalp-new
.venv\Scripts\python.exe -m goldsignal.scalp_research run --archive .research/scalp-20261119 --split 2026-11-12 --output .research/scalp-replay-new.json
.venv\Scripts\python.exe -m goldsignal.scalp_research run --archive .research/scalp-20261119 --split 2026-11-12 --cost-multiplier 2 --output .research/scalp-costs-new.json
$env:PYTHON_DOTENV_DISABLED='1'
.venv\Scripts\python.exe -m pytest -q
```

`run` includes A/B/C, all four delays, USD100/USD1000 risk scenarios and the four-alert reproduction. Export reuses the existing MT5 tick collector. The verified gzip CSV reader accepts `time,bid,ask` headers; time is UTC Unix seconds with fractional milliseconds, ascending broker order. Do not substitute candles for ticks. No alternate feed or separate import step was needed because MT5 was accessible.

Completed artifacts: `.research/scalp-20261119-final.json` and `.research/scalp-20261119-final-costs2.json`. Archives are ignored by Git to avoid committing local market/account snapshots. No credentials, account identifiers or push subscription secrets are included by the exporter.

## Remaining evidence

A prospective, unseen demo interval is required. Measure review start/end, push submission, provider response, observed device receipt and notification open separately on the existing phone channel. The current offline ledger records confirmation, first executable quote, simulated action and exit; it cannot observe physical device receipt. No production instrumentation or push behavior was changed. No free Gemini shadow comparison was run because live paired phone measurements were unavailable; the core test stayed deterministic and cost RM0.

Verify actual account commission, account subtype and historical margin/specifications before account-specific conclusions. Obtain a point-in-time historical economic-event archive to validate news filtering. Test a small-account exit policy separately before relaxing the broker-valid thirds requirement. Do not reuse the evaluation period to tune thresholds and call it new validation.

80% remains a research target. None of these results supports that probability claim or guarantees a signal every hour/session.
