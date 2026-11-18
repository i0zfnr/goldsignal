# Goldsignal strategy review

Goldsignal watches Valetax `XAUUSD.vx` in MT5, publishes qualified signals and tracks their simulated outcomes. Viewers use the Ryaze website and can opt in to phone alerts. They place trades manually.

## What runs where

| Component | Role |
| --- | --- |
| MT5 on Windows | Supplies broker bid, ask and candles. The collector uses read-only access. |
| Python worker on Windows | Runs the entry rules, simulated lifecycle, calendar refresh and notification queue. |
| FastAPI and SQLite on Windows | Store signal history, account access, shared reviews and notification subscriptions. |
| Outbound HTTPS relay and Ryaze | Deliver the dashboard and its API responses to browsers. Windows must stay online for live data. |
| Gemini Flash-Lite | Reviews qualified setups, and answers private admin chat prompts through a separate endpoint. |

The admin signs in directly at `/admin`. Viewers sign in at `/` with a revocable access key. The admin stores the Gemini key once, encrypted on Windows. The chart pulls the same broker data for everyone. M1, M5, M15, M30, H1 and H4 are viewing options. The signal strategy always starts with a closed M15 candle.

## Entry decision

1. **Open session.** The worker checks regional weekday windows against broker hours. The default local windows are Sydney 08:00–17:00, Tokyo 09:00–18:00, London 08:00–17:00 and New York 08:00–17:00. Local time zones handle daylight saving. Overlapping windows stay open when the broker is open. The dashboard shows session names and MYT.
2. **Aligned trend.** Read the four latest consecutive, fully closed candles on M15, M30 and H1. For BUY, the latest close must be above both the oldest and the average on all three timeframes. SELL reverses the comparisons. Missing bars, flat trends or disagreements block the setup.
3. **Confirmed swing.** Find a strict swing low for BUY or high for SELL. The default swing requires two bars on each side and a recent 48-bar search window. A swing becomes known only once its right-side bars close.
4. **Rejection candle.** The last closed M15 candle must have the correct body direction. The rejection wick must be at least as long as the body. The low or high must touch within **0.80 price units** of the swing, and the close must finish past that band in the rejection direction.
5. **Historical context.** Wilder RSI(8), the four-bar return and normalized candle body are compared with up to **1,000 previous closed M15 candles**. The worker takes the five closest historical matches and summarizes their signed next-four-bar return. It excludes matches that need future data at evaluation time. This summarizes historical context without estimating the probability of profit.
6. **Execution checks.** Require a fresh executable quote, a broker-permitted direction, spread at or below **0.50 price units**, and an executable price inside the entry zone. Quotes older than **20 seconds** block entries. Calendar pauses are **20 minutes before** to **15 minutes after** covered releases. An official schedule older than **six hours** blocks entries.
7. **Gemini review.** When enabled, the worker sends a compact set of already-calculated levels and evidence. Gemini can return `CONFIRM`, `WAIT` or `REJECT`. Python keeps the original direction and levels. The worker reloads live quotes and rechecks the gates before publishing. Invalid output, a failed request or exhausted review quota holds the candidate. Rules mode can run without Gemini.

Automated Gemini review uses up to **six requests per UTC day** across all sessions, with at most **96 output tokens** per request and one cached result per candidate. Chart refreshes use zero model tokens. Manual admin chat uses the same Google project and does not count toward Goldsignal’s six-review counter. Its usage still counts against Google's project quota. Chat does not publish a signal.

## Entry and exit levels

Let `E` be the closed rejection candle’s close. All offsets below are XAUUSD price units.

| Direction | Entry zone | Initial stop | TP1 | TP2 | TP3 |
| --- | --- | --- | --- | --- | --- |
| BUY | E − 3 to E | E − 6 | E + 3 | E + 6 | E + 10 |
| SELL | E to E + 3 | E + 6 | E − 3 | E − 6 | E − 10 |

- **Pending.** The candidate expires at the earlier of 30 minutes after the M15 close or the end of the continuous entry window. BUY can fill on ask, SELL on bid, at the first eligible subsequent tick.
- **Filled.** Targets and stops use the opposite quote side. The simulated stop moves to `E` at TP1 and to TP1 at TP2. `E` is the signal reference and may differ from the simulated fill price. Each target represents one third of the simulated position.
- **Closed.** Three targets complete the simulation. A stop or the three-hour holding timeout exits the remainder. Tracking can continue after the entry window. Gaps may produce a simulated exit price beyond the target or stop.
- **Alerts.** Confirmed entries and lifecycle changes are queued for viewers who opt in. Entries are rechecked before delivery and expired if the setup is no longer executable. The queue retries temporary failures and uses stable notification IDs to limit duplicate display. The dashboard shows shared alert history. Viewers choose their own risk and position size.

## Why a live chart can show no signal

`LIVE` confirms that quotes are arriving. The scanner still needs a closed M15 setup that passes trend, swing, rejection and execution checks. The new scan line shows the latest closed candle and the blocking setup rule. If a setup does reach the candidate stage, **Last candidate** shows the decision and reason.

During the 18 November 2026 investigation, the worker was fresh and Gemini was enabled. Rechecking the last roughly 24 hours of stored M15 candles yielded no qualifying setup, and no Gemini signal review had been used. The worker later showed SELL trend agreement with no qualifying rejection candle. Google returned HTTP 200 for model access with the saved key. This verified access to the model, while real generated chat and live trade-signal delivery remain separate checks.

## Validation plan

| Stage | Evidence to collect |
| --- | --- |
| Gate audit | Count bars scanned, trend agreement, rejection candles, swing matches, valid quotes, calendar pauses, Gemini decisions and published signals. Break counts down by trading session. |
| Broker replay | Use historical bid/ask ticks and candles from the broker. Replay in timestamp order with the historical calendar, session schedule, spread, and slippage assumptions. Check for future-data leakage in both swing confirmation and pattern features. |
| Strategy comparison | Compare the current rules-only baseline with Gemini review on the same candidate stream. Change only one parameter per experiment. Reserve a later out-of-sample period to see whether any improvement carries forward. |
| Execution review | Track entries filled before expiry, TP1 reached before stop, full lifecycle, net return in units of initial risk, drawdown, and alert latency. Mark costs and tick gaps explicitly. Include how often the Gemini quota holds candidates. |
| Alert check | Test entry, TP1, TP2, TP3, stop and expiry in demo. On a real phone, opt in over HTTPS, background the browser, and confirm that opening each alert works. Verify unsubscribe and key revocation. |
| Operations | Verify reconnect after Windows restart, broker holidays and DST, admin access, key rotation, and failure behavior when the broker, calendar or Gemini is unavailable. |

Collect the gate counts before loosening entry rules. If the rejection test is the main bottleneck, compare a wider swing tolerance or a different wick-to-body requirement in replay. Keep the original live rules until the comparison can be inspected.

## Session coverage experiment

I replayed the setup filters against the stored Valetax M15 sample spanning 4–18 November 2026 MYT. There were 980 closes in an open entry window. The experiment benchmarked candidate detection without historical execution, spreads, news blocks, model decisions or returns.

| Setup variant | Candidates | MYT dates with candidates |
| --- | ---: | ---: |
| Current rules | 3 | 2 |
| Minimum rejection wick equal to half the body | 4 | 2 |
| Swing tolerance increased from 0.80 to 1.60 | 4 | 4 |
| Both changes | 6 | 4 |

The combined variant found one candidate in the Sydney/Tokyo overlap and five in London or the London/New York overlap. This sample falls short of daily coverage and provides no estimate of profitability.

For broader coverage, test two complementary setups in shadow mode. Keep the current rejection rule as the baseline. Test a session opening-range breakout followed by a retest, and test a trend pullback with a wider volatility-adjusted swing zone. An opening-range breakout study on crude-oil futures supplies a testable structure. Any edge on Valetax gold remains unverified. [Opening-range breakout study](https://www.econ.umu.se/ueslpnr/ues845.pdf)

Log a session status such as `No setup`, `Watchlist` or `Confirmed` for each open session. Send entry alerts only for confirmed setups. Track the percentage of sessions with at least one qualified candidate alongside fill rate, net results after costs, drawdown and false breakouts. Predefine the comparisons and evaluate an untouched later period before enabling a variant. [Research on backtest overfitting](https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID2423465_code434076.pdf?abstractid=2308659&mirid=1)

## Source map

- `goldsignal/config.py` sets trading windows, thresholds and expiry.
- `goldsignal/market.py` connects to MT5 and normalizes bars and quotes.
- `goldsignal/strategy.py` defines setup detection, pattern matching and entry gates.
- `goldsignal/worker.py` runs the scanner, Gemini review and publishing.
- `goldsignal/lifecycle.py` tracks simulated fills and exits.
- `goldsignal/alerts.py` queues and delivers shared pushes.
- `goldsignal/access.py` and `goldsignal/chat.py` handle administration and manual chat.
- `ryaze-server.mjs` and `goldsignal/relay.py` connect the public site to the Windows backend.
