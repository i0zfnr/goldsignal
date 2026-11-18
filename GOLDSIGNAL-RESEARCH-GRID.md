# Goldsignal strategy research grid

The 1,000 candles in Goldsignal provide historical context for a single live M15 setup. This plan defines **1,024 strategy configurations** for separate research. None of the configurations in this grid has a verified profit record.

## Strategy families

| Family | Market condition | Candidate trigger |
| --- | --- | --- |
| Trend pullback | M15 and H1 agree on direction | Closed M5 pullback that rejects a confirmed swing and closes back in the trend direction |
| Opening-range break and retest | Price breaks the early range of an open session | Closed M5 breakout, followed by a closed retest that holds the broken boundary |
| Range rejection | M15 and H1 lack a directional trend and the local range is intact | Closed M5 rejection at a range edge, with RSI(8) turning back toward the middle |
| Volatility breakout | Range compression precedes expansion | Closed M5 break of the prior range, followed by a qualifying executable quote while the spread remains within budget |

Tag every eligible candle using only information available at its close. Record trend direction, range state and current volatility separately from the strategy decision. Use completed M15 and H1 bars for trend and completed M5 bars for triggers and volatility. Apply closed-bar confirmation to swing and retest detection.

## Experiment dimensions

| Dimension | Four values |
| --- | --- |
| Setup family | Trend pullback, opening-range break and retest, range rejection, volatility breakout |
| Session | Sydney, Tokyo, London, New York |
| Setup lookback | 3, 6, 9 or 12 closed M5 bars. For opening-range setups this means the first 15, 30, 45 or 60 minutes of that session. For the other setups it governs the M5 setup search. |
| Stop buffer beyond the structure that invalidates the setup | 0.10, 0.20, 0.30 or 0.40 times M5 ATR(14) |
| Target from the simulated fill | 0.75R, 1.00R, 1.25R or 1.50R, where 1R is the initial fill-to-stop distance |

Test the Cartesian product. Four values across five dimensions produce 1,024 configurations. Compare them with the current Goldsignal M15 rules as a separate baseline. Treat session overlap as shared market exposure when measuring combined results. The thresholds above are experimental inputs.

The first benchmark fixes the session to New York. That leaves 256 configurations and the original M15 baseline. The [baseline replay](GOLDSIGNAL-NEW-YORK-REPLAY.md) is complete for its stated sample. Expand the broker tick archive and freeze the strategy definitions and ranking rules before the grid. Evaluate Sydney, Tokyo and London separately for the all-session coverage goal.

## Evidence needed before live alerts

1. **Collect executable history.** Request Valetax `XAUUSD.vx` bid/ask tick history through MT5 and audit the available date range, platform clock offset, gaps and broker sessions. At inspection on 18 November 2026 the local database held 1,018 M15 and 273 M5 candles. Those bars alone cannot establish scalp fill order or real spread at entry. [MT5 historical bid/ask ticks](https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksrange_py)
2. **Replay in order.** Use the quote side the trader could execute, include spread, commission and adverse slippage, and model alert and human-entry delay. Record unfilled setups and expirations. Check that every feature, including ATR, swing and range boundaries, uses information available when the alert would fire.
3. **Separate research from evaluation.** Use earlier periods for development and rolling forward windows for selection. Reserve a later period that remains untouched until decisions are frozen. Log all 1,024 trials. The odds of finding an impressive result by chance rise with the number of configurations tested. [Research on multiple testing and backtest overfitting](https://doi.org/10.2139/ssrn.2460551)
4. **Rank after costs.** Compare net expectancy per trade, maximum drawdown, trade count, consistency across separate months, session coverage, and how results change with worse spreads or slower fills. Report no-setup and no-trade sessions. Require enough observations to distinguish performance from noise.
5. **Run finalists in shadow mode.** Freeze rules, compare live simulated fills with backtest assumptions, and confirm alert timing. Only enable a setup for live alerts after reviewing that evidence. Gemini can summarize qualified candidates without running 1,024 model calls or assigning a probability that has no calibration.
