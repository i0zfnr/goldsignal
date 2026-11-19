# Next-agent handoff: evidence-based high-confidence scalp entries

## User objective and scope

The user wants Goldsignal to find useful short-term XAUUSD entries every trading day, aiming for approximately 80% confidence. This document replaces the previous screenshot-focused handoff as the next-work instruction.

Build evidence for selective, executable entries. Do not promise an 80% win rate every day. Daily monitoring, estimated entry probability, observed win rate and profitable expectancy are different things. With one trade in a day, that day's realized win rate is either 0% or 100%; it does not validate the probability forecast.

An honest result can be: “No qualifying entry today,” “Not yet calibrated,” or “The current USD100/minimum-lot constraints prevent a safe entry.” Never force a trade to satisfy a daily quota. This request authorizes a handoff document, not an immediate change to live trading rules.

## Starting state: reuse completed work

- Repository: `C:/laragon/www/goldsignal`, branch `main`, origin `https://github.com/i0zfnr/goldsignal.git`.
- Latest deployed commit: **d298009**, notification service-worker cache fix. Previous commit **4ff3128** contains the research and isolated demo implementation.
- Ryaze main app: `https://goldsignal.ryaze.my.id/`. The user explicitly deferred relay configuration. Leave it unchanged unless they authorize that work later.
- The existing 880-variant study is the baseline. **None passed development.** There were 368 configurations with completed fills, but a maximum of eight completed trades versus the frozen ten-trade minimum. Those results do not establish an 80% edge.
- The largest rejection constraint was minimum-lot stop risk, accounting for 71.6% of blocked candidate/configuration pairs. Those pairs are correlated and must not be counted as independent market opportunities.
- Preserve USD100 initial paper equity, 1% planned risk of current closed equity, natural stops, fixed 0.01-lot single exits, the two-alert rolling-hour cap and no paid API calls. Do not silently change risk, leverage assumptions, account type or broker volume limits.
- Last verification: 52 tests passed and frontend build passed. Do not assume the runtime, tunnel or phone enrollment is still unchanged; inspect current state.

Read `GOLDSIGNAL-DEMO-ACCOUNT-STUDY.md`, `GOLDSIGNAL-SCALP-TIMING-CORRECTION.md` and `GOLDSIGNAL-SCALP-GRID.md` before editing. Preserve the old result artifacts instead of replacing failed results with a new success narrative.

## Priority 1: define what “80%” predicts

Freeze the outcome definition before fitting or choosing thresholds:

1. A candidate must become eligible for an account-specific alert and remain executable at the modeled or actual user action.
2. A filled trade wins only if its full single-exit net P&L is positive after bid/ask spread, commission and adverse slippage. Count the actual exit policy, including timeout exits.
3. Report TP-before-stop separately if it is measured. Do not substitute that event for net profitability without changing the displayed label.
4. Blocked, expired, suppressed and missed alerts are not wins or completed trades. Report them separately, including the percentage executable at phone open.
5. Keep actual fill price, natural stop, target, holding limit and cost assumptions with each label. Do not label a move profitable because price reached a target after the simulated stop had already closed the trade.

Desired probability label: “Estimated probability of a positive net result under this stated exit and execution policy.” A rules score, Gemini CONFIRM, RSI reading, nearest-pattern match or strong-looking chart is not that probability.

## Priority 2: prove the feed and entry pipeline work

Before adding filters or another strategy, trace current opportunities through:

`M1 confirmation -> detection -> first eligible broker quote -> local processing/review -> publication recheck -> submission -> phone handling -> click -> server action quote -> account gate -> fill/exit`.

The existing timing bug was corrected: late eligibility must not erase post-submission delivery/reaction delay. Keep the regression where the quote becomes eligible late but leaves the zone before the user can act. Use the first executable-side broker quote at or after modeled action; no waiting for a later re-entry to rescue the first action.

Audit stale data, broker clock offsets, completed M1/M5 candles, known daily closures versus genuinely missing history, spread, expiry, scheduled-news availability, alert caps and queued-message expiry. Keep M15-baseline and M5/M1-lane reasons separate. The previously shown M5 SELL setup was waiting for a closed M1 retest; an old WAIT/outside-zone candidate and an H1-gap message were not proof that the current M5 lane had failed.

Do not invent missing candles or bypass a quote gate to improve alert counts. Show the current candidate ID, candle close, expiry and first numerical rejection reason. Label old candidates as historical, not as the reason every new setup is waiting.

## Priority 3: establish USD100 tradeability before probability modeling

Use the pinned Valetax `XAUUSD.vx` account/feed and current symbol specifications. Calculate planned cash loss from executable ask for BUY or bid for SELL through the strategy's natural stop, with explicit costs. Reject it if the broker-supported minimum size exceeds the 1% budget. Recheck before submitting ENTRY READY and at the first alert open.

Current observed specifications were minimum/step 0.01 lot, maximum 50 lots and a 100-ounce contract. The configured terminal was a USD demo account. A 90-day query found 541 fully matched round trips with zero recorded commission/fees. This is observed demo-account history, not a real-account tariff or a future guarantee. Verify again using the read-only audit command.

Three broker-valid partial exits cannot be made from a 0.01-lot position when each exit requires 0.01 lot. The demo uses one full exit. Removing partials does not solve a stop that is too expensive for USD100.

Deliver an opportunity funnel: all detected candidates, market-gate passes, account-risk passes, valid submissions, executable opens, fills and completed outcomes. If natural-stop risk eliminates almost everything, state that constraint first. More indicators or a larger AI model cannot make the same minimum lot fit the unchanged cash budget.

## Priority 4: collect genuine execution evidence

The existing isolated demo uses port 8012 and `.research/demo-phone/account.sqlite3`. Runtime files, viewer key, process IDs and protocol are under `.research/demo-phone`, ignored by Git. Never copy keys, subscription endpoints, account identifiers or private runtime files into a handoff or commit.

The user chose Android Chrome / installed PWA. At the last checked state there were no enrolled devices or genuine paired ENTRY opens. Verify current enrollment and events instead of claiming that phone timing has already been measured.

Keep submission, provider acceptance, service-worker push handling, notification click and server entry-open separate. Provider acceptance is not physical receipt. Test notifications can verify transport, but must not become strategy-entry samples. Preserve missing/unopened events rather than giving them zero delay.

Use the existing quality rules: at least 20 genuine paired ENTRY opens across three development-session dates, clock uncertainty at most one second, sufficiently recent calibration, and a completed broker archive to reconstruct eligibility. Freeze timing from development only. Do not refit it using validation/final clicks. Record whether the model transfers timing observations from the baseline lane to other strategies.

## Priority 5: build a small, testable quality model

Do not begin by adding another thousand unbounded strategies. Diagnose the completed grid first. Keep only a few clearly defined, versioned hypotheses supported by failure data. Examples to investigate, not automatically enable:

- Higher-timeframe direction and market regime agree with the M5 setup.
- Entry is near a defined structure/retest rather than chasing an extended candle.
- A completed M1 trigger confirms entry before expiry.
- Spread, cost-to-stop distance and realistic price-to-target leave usable net economics.
- RSI(8) and volatility add incremental evidence beyond the existing trend/price rules.
- Scheduled-news and liquidity conditions match the cohort that was evaluated.

Define every feature with prices and information available at decision time. Use no unfinished/future candles, hindsight swing points, future nearest-pattern outcomes or unsupported claims about institutional orders inferred from OHLC alone. Test a change against its unchanged control on the same candidate stream and costs. Keep New York as the existing validated-study scope; other sessions need their own evidence before claiming the same confidence there.

Start with an interpretable deterministic score or simple local model. Only introduce a probability calibrator if there are enough genuinely labeled observations. Calibration data must be separate from the data used to fit the underlying predictor. Official guidance distinguishes well-calibrated probabilities from raw classifier output and describes reliability diagrams; Brier score alone also reflects discrimination and uncertainty, so it is not a standalone calibration certificate. [scikit-learn probability calibration](https://scikit-learn.org/stable/modules/calibration)

## Priority 6: pre-register the evidence needed for an 80% claim

Choose and write the sample-size, stopping, calibration-tolerance and uncertainty requirements before inspecting new final results. A point estimate of 80% is not proof that the underlying success probability is at least 80%. Report a binomial confidence interval for the observed win proportion. [NIST confidence intervals for proportions](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm)

Proposed acceptance policy for the next agent to formalize before a new prospective experiment:

- Show completed trade count and uncertainty, not just a percentage. Use sample-size planning for the required precision; do not treat ten trades, five nearest matches or an arbitrary minimum count as proof.
- For a label specifically claiming evidence of **at least 80% realized success**, require the predeclared lower confidence bound to support that claim. If only an approximately 80% point estimate is supported, label it accordingly and show its interval.
- For an **estimated 80% entry probability**, require acceptable held-out calibration in that probability region, with enough observations and uncertainty displayed. Overall win rate cannot certify each setup's probability.
- Require positive net expectancy after costs and acceptable drawdown/losing streak under the existing frozen policy. Do not manufacture high win rate with tiny targets and disproportionately large losses.
- Check slower phone opens, higher costs and consistency across chronological windows. A zero-fill strategy is ineligible; a tiny positive sample remains insufficient evidence.
- Account for overlapping signals and dependence by day/session. Binomial intervals alone do not remove that dependence. Report clustered uncertainty and the effect of testing many variants; do not treat 880 correlated attempts as 880 independent discoveries.
- Freeze the shortlist and all scoring/calibration thresholds before final evaluation. If several finalists are reported, predeclare how multiple comparisons and portfolio overlap will be handled. Never pick a new winner using the final period.

Do not extend a failed final test until its percentage looks good. If the registered sample is underpowered or the target fails, report that result and define a new prospective study with genuinely unseen data.

## Priority 7: respect the existing forward split

The current forward protocol is 20 admitted development sessions, two separate 10-session validation windows and 10 final-reserve sessions. These are session counts, not guaranteed trade counts. They may be insufficient for a defensible 80% claim.

Do not silently rewrite that already frozen protocol. If sample-size planning calls for a different experiment, document a new forward protocol before using new outcomes. Preserve the baseline and old protocol results, and keep the final reserve untouched. Calibration, classification thresholds, exit choices and cost assumptions are settings too; none may be selected using final-period returns.

## Priority 8: daily operation without false confidence

The system should monitor every eligible trading day and explain its state:

- **Monitoring:** feed and scanner healthy, no eligible setup yet.
- **Conditional setup:** market condition detected, but an entry trigger or quote is still missing. It is not ENTRY READY.
- **Blocked:** show the first failed market/account gate.
- **ENTRY READY:** all execution/account gates pass and the separately validated quality gate passes.
- **Missed/expired/closed:** never present it as a fresh entry.

Until calibration passes, display “Uncalibrated setup score” or “Not yet validated,” not a fabricated 80% confidence badge. If a probability model is later approved, display the outcome definition, evidence window, sample size and uncertainty alongside its estimate. AI may summarize measured facts; it may not invent a probability or override the Python gates.

Report daily coverage separately: days monitored, days with any qualified entry, zero-entry days and their reasons. A promise of one signal every day conflicts with withholding weak setups when no valid opportunity exists. Do not solve that conflict by lowering the threshold without telling the user.

After a successful forward evaluation, use a separate small demo rollout and monitor data drift, calibration, realized net expectancy, risk failures and delivery latency. Predeclare pause/revalidation rules. Do not automatically promote or retrain from a short losing/winning streak.

## Required next-agent deliverables

1. A current-state audit identifying actual feed, account-risk, timing and strategy-quality blockers.
2. An explicit outcome definition and an achievable evidence plan for the 80% research target.
3. Reproducible, no-paid-API commands, input provenance and a candidate-by-candidate gate/label ledger.
4. Chronological control-versus-change results: fills, executability, net win rate with uncertainty, expectancy, drawdown, losing streak and session/day coverage.
5. Calibration results where justified, including reliability by score region and counts. Otherwise an explicit “insufficient evidence” conclusion.
6. A frozen prospective shortlist and a separate final test, or an explanation that no variant qualifies.
7. A plain user verdict: what improved, what remains unproven, whether entries became rarer, and whether approximately 80% is supported. No guaranteed daily win rate.

Start with diagnosis and data qualification. Keep this work in replay/demo until evidence and the user's authorization support promotion. Preserve authentication, hidden admin access, existing features, required attribution and the deferred-relay decision. No trading-logic change, commit or deployment is requested by this handoff-writing turn.
