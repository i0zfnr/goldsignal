# USD100 account and Android phone study

Implemented on 19 November 2026. This is an isolated paper-account study using genuine Valetax quotes. No broker order is sent. The completed 880-variant run remains the baseline; no strategy is promoted by this work.

## Running demo

The API listens on loopback port 8012, separate from the existing production API/relay. API, worker and future-session collector run as hidden Windows processes. A temporary Cloudflare HTTPS tunnel provides the Android Chrome/PWA origin. The tunnel address was supplied in the conversation; it is not the production Ryaze hostname. It remains available only while those processes and Windows stay online. A new tunnel origin requires a new phone subscription.

Database: `.research/demo-phone/account.sqlite3`. The dedicated viewer key is in `.research/demo-phone/access-key.txt`, outside Git. Existing authentication, hidden admin entry point and production database are unchanged. Do not copy production subscriptions into this database: Web Push subscriptions belong to the HTTPS origin.

Enable notifications on this demo origin, send a test notification, background Chrome, and tap the notification. Test messages prove only the delivery/instrumentation path. They are excluded from strategy-entry timing calibration. There were no enrolled devices or real paired ENTRY measurements at the initial readiness check. No device events or phone timings have been fabricated.

The next fresh New York window begins **19 November at 9:00 PM Singapore time**, equivalent to 08:00 America/New_York. Daily archive export runs after 18:00 New York, when the requested session and tracking interval have completed. The collector intentionally does not relabel the already inspected November 18 session as fresh.

## Account-specific ENTRY READY

The feature is off unless `GOLDSIGNAL_DEMO_ACCOUNT=1`. Startup requires MT5 mode, rules-only review and a SQLite database under `.research/demo-phone`. The demo worker ignores stored Gemini enablement. Normal shared production alerts and authentication retain their existing behavior when the flag is off. This change has not been deployed to the production Ryaze app.

Before each account-specific ENTRY submission:

1. Require the existing M5/M1 baseline signal and an unexpired entry phase.
2. Check pause status, New York/broker window, fresh executable quote, spread, entry zone and the economic-calendar gate.
3. Read current terminal account and symbol information. Require the pinned USD demo account, USD symbol profit currency and a fully tradable symbol. Check actual volume minimum, step and maximum. Use current BUY/SELL minimum-lot margin calculation for the corresponding side.
4. Calculate planned stop loss from live ask for BUY or bid for SELL through the original natural stop. Add explicit round-trip commission and adverse slippage. Reject any minimum-size entry above 1% of current closed paper equity. Start equity is USD100; free margin is estimated from paper equity with one active opportunity.
5. Require one full 0.01-lot exit, at most two account-specific opportunities per rolling hour and the existing 3% daily loss budget. Do not widen the budget or tighten the stop to obtain a fit.

The submitted title is `DEMO ENTRY READY`, with 0.01 lot, full-exit target and explicit cost assumptions in its body. A failed account gate prevents Web Push submission and saves its first reason in `demo_check`. The device-specific notification list displays `DEMO entry blocked` and that reason. Risk checks are per owner rather than shared across viewers.

Opening the notification repeats the live quote/specification and risk checks. It requires authenticated ownership of the device alert and its recorded submission attempt. The first open snapshot is retained. Repeated page requests cannot rescue a failed first action after a later re-entry. A valid first open creates one paper fill, never an MT5 order.

Paper exits close the entire 0.01 lot at the first executable-side tick crossing the original stop, TP1 or hold timeout. There are no partial exits or trailing-stop changes in this paper ledger. Exit price uses the actual crossing tick, not an idealized stop/target fill. No quote means no manufactured exit; broker closures can delay a timeout exit until a tradable quote exists. Account-specific exit updates use the same Web Push transport. Existing shared strategy tracking stays separate, so dashboard shared performance is not the USD100 paper ledger.

## Broker verification

The configured terminal was accessed directly. Its account mode is demo, account currency USD, company Valetax International Limited, instrument `XAUUSD.vx`.

| Specification | Observed value |
|---|---:|
| Minimum volume | 0.01 lot |
| Volume step | 0.01 lot |
| Maximum volume | 50 lots |
| Contract | 100 ounces per lot |
| Tick size | 0.01 |
| Tick value | USD1 per lot |
| Complete round trips inspected, last 90 days | 541 |
| Recorded commission plus fee per lot round trip | USD0 |

Commission evidence sums the entry and exit deal commission/fee fields for fully matched positions, divided by entry volume. Account identifiers and deal tickets are excluded from artifacts; a private account fingerprint prevents silently switching the study account. This verifies observed charges on the configured demo account. It does not establish a commercial account subtype, future fee guarantee or real-money account tariff. Swap and charges outside those deal fields are not inferred.

Paper alerts explicitly assume USD0 commission/lot round trip and 0.10 adverse price slippage. Bid/ask spread is separate. Margin is recalculated from current terminal information at each critical check. Natural-stop planned risk is not a guarantee against gaps. Daily broker audits preserve observed specifications and fee evidence beside new session exports.

The frozen grid keeps its existing shared cost scenarios: commission USD7/14 and price slippage 0.10/0.20, plus the explicit zero-commission scenario. Actual zero-fee evidence is not used to remove higher-cost stress tests.

## Separate timing observations

Each attempt records:

- Actual local Web Push call start, distinct from alert queue creation.
- Provider completion and acceptance status. Acceptance is not phone receipt.
- Android service-worker `push` handling time.
- `showNotification` completion. This does not prove when Android displayed a banner.
- Notification click time.
- Server entry-open handler start, live action-quote check time and the gate result.

Candidate M1 confirmation, backend detection and first observed eligibility are recorded separately. Attempt IDs correlate retries; stable alert IDs preserve opportunity identity. Client wall time, monotonic time, worker context, clock-offset estimate, uncertainty and calibration time are retained separately from server ingestion time.

The service worker stores unsent measurements in IndexedDB and retries uploads on push, click and page-open messages. An offline upload does not become the receipt timestamp. Tokens are scoped to a recorded alert/attempt, never include subscription endpoints, are omitted from API display data and are excluded from exported events. Duplicate events are idempotent.

For grid calibration, require at least **20 genuine paired ENTRY opens across three New York session dates**. Exclude tests, exit updates, missing stages, rejected submissions, noncausal timestamps, clock uncertainty above one second and calibrations more than 120 seconds from event capture. Unopened alerts remain censored/missing, never assigned zero reaction time.

Only development-session phone opens can calibrate timing. The first adequate fit is saved to `frozen-timing.json` before scoring; later validation/final clicks cannot refit it. The replay independently rejects a timing file containing validation or final-period opens. If the admitted development roster changes after the freeze, the run stops for review rather than silently choosing a different sample.

Once that day's genuine tick archive is complete, reconstruct the earliest eligible broker quote after measured backend detection using the candidate's original levels and the economic-calendar snapshots observed at that time. Measure eligibility-to-submission elapsed from that quote. This includes polling/queue overhead without erasing late eligibility or double-counting its wait. A raw first-observed-eligibility interval is retained for comparison. If reconstruction fails or its completed session archive is absent, the pair cannot fit replay delays.

The prospective replay uses median measured detection, eligibility-to-submission elapsed and submission-to-action-quote delay. P90 post-submission, processing and detection delays are shared stress tests. Detection is a pre-eligibility stage; AI review remains zero in this rules-only study. Transferring these timing distributions from baseline alerts to other grid families is an explicit research assumption, not a measured property of every strategy.

## Fresh data and longer windows

The protocol was written before the first fresh session. It contains the same 880 configuration definitions and baseline selection criteria, with no change to natural stops, the USD100 starting account, 1% planned risk or 0.01-lot single exits.

| Period | Admitted fresh New York sessions | Use |
|---|---:|---|
| Development | First 20 | Replay and rank frozen definitions |
| Validation A | Next 10 | Evaluate the frozen development shortlist |
| Validation B | Next 10 | Check consistency and shared stresses |
| Final reserve | Next 10 | Held separately until finalists are frozen |

Sessions must be from the pinned account/feed, have genuine bid/ask ticks, cover both New York boundaries and have no unexplained gaps above 20 seconds. Failed/partial exports remain available for inspection and are not silently overwritten. Holidays, missing data and duplicates do not count as additional admitted sessions. The broker offset is checked against current quote time; historical clock/schedule changes still require review.

The dataset builder reads prices/candles from the first 40 admitted sessions only. It does not link final-reserve tick files into the development/validation dataset. Calendar snapshots are saved as observed and apply only during their recorded observation intervals, preventing later schedules from being retroactively applied. Snapshot availability, feed completeness and revisions remain audit concerns; they are not claimed perfect.

Collection stops after 50 admitted sessions. Account changes pause paper tracking and invalidate other-account exports; they do not silently replace the pinned feed.

After calibration and all required development/validation inputs exist, `rerun` runs exactly the frozen definitions with shared measured-delay/cost scenarios. It writes a plan and hashes before scoring, then freezes the development shortlist before evaluating either validation window. No final-return selection occurs. If no configuration passes, there are no finalists to evaluate. Final data must never be used to replace settings.

## Commands

```powershell
# Read-only verification against the configured terminal.
.venv\Scripts\python.exe -m goldsignal.demo_session audit
.venv\Scripts\python.exe -m goldsignal.demo_session setup

# Separate processes; these are already running for the current demo.
.venv\Scripts\python.exe -m goldsignal.demo_session serve
.venv\Scripts\python.exe -m goldsignal.demo_session worker
.venv\Scripts\python.exe -m goldsignal.demo_session collect

# Measurement report: no assumed phone times are inserted.
.venv\Scripts\python.exe -m goldsignal.demo_session timing

# Fails with a readiness message until real measurements and fresh sessions exist.
.venv\Scripts\python.exe -m goldsignal.demo_session rerun --output .research/demo-phone/prospective-run
```

The server/worker/collector need Windows and MT5 online. They are not installed as an automatic startup service. The HTTPS tunnel is temporary; its process is separate. Runtime process IDs, logs, viewer key, database, protocol, broker audits, timing reports and archives are under `.research/demo-phone`, ignored by Git. Do not copy the private runtime files into a deployment.

## Validation and current limits

52 tests passed. Production frontend build, Python compilation, service-worker syntax and whitespace checks passed. Tests cover default-off behavior, account risk before submission, fresh risk at open, first-open idempotence, full minimum-lot exit, scoped telemetry, provider/device separation, closed-equity risk and refusal to substitute missing phone measurements. Existing production-path tests pass with the demo flag off.

The demo URL and its clock endpoint returned HTTP200; viewer sign-in succeeded. No real Android subscription or paired ENTRY sample was present at the initial readiness check. Fresh New York data cannot exist before the next session opens. The larger measured-delay grid run is therefore **pending**, not reported as completed. Its readiness gate was exercised and refused to replace missing phone evidence with assumptions.

Existing production deployment was not changed. No paid API, Gemini request or broker order was used. The original 880-variant baseline artifacts remain preserved. Forward-only detection timing and observed-calendar support do not introduce new strategy definitions.
