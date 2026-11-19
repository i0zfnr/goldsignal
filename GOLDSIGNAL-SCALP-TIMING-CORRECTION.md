# Corrected scalp alert timing

This report supersedes the timing conclusions in GOLDSIGNAL-SCALP-RESEARCH.md. Production, Gemini, push delivery and trading rules were not changed. All timings below are assumptions, not phone measurements. No paid APIs were called.

## Stage model

1. M1 closes and confirms the candidate at C. Review starts at C and finishes at C + review latency.
2. Find the first quote eligible under executable side, zone, spread, expiry, New York window and calendar. Eligibility can arrive after review finishes.
3. Local processing starts at the first eligible quote after review. After processing latency, use the first subsequent broker quote and recheck all publication gates. If that attempt fails, wait for another eligible quote, repeat local processing, and recheck. Submit only on the first successful attempt before expiry.
4. Action is submission + post-submission delay. This delay includes transport and human reaction. Five seconds could mean one second delivery plus four seconds reaction; 30 seconds could mean three plus 27. These decompositions are examples, not observations. Use the first bid/ask broker row at or after action. Never wait for a later re-entry after that row.
5. Recheck zone, spread, expiry, freshness, news, and account risk at action. Buy at ask; sell at bid. Opposite price side closes the simulated position.

The original bug used max(C + delay, first eligible quote). When eligibility arrived late, the phone delay disappeared. The regression creates eligibility at 120 after confirmation at 100, then leaves the zone before action at 125. The corrected result is missed even if price later re-enters. Local-processing failure and review-once behavior also have regression tests.

For risk-qualified research paths, the account screen runs before modeled submission and again at action. Stored earliest_valid_submission denotes price/news eligibility before the account screen; timing.submission is null if risk or portfolio rules prevent publication. Counterfactual action quotes are still logged for risk-blocked opportunities. Fixed-lot grid risk uses executable entry through the natural stop plus adverse slippage and commission, not a favorable reference or artificial tightened stop.

## Production trace

`worker.evaluate` checks the market/calendar/review gate; `worker.process` rechecks before persisting the signal. `record_event` queues shared and device ENTRY events. `alerts.send_pending` checks current quote eligibility before calling Web Push. It can expire an invalid queued alert rather than wait for a later re-entry. There is no viewer-specific account_fit check on shared signal publication or push submission. `/api/entry-open` also validates market eligibility, not account risk. Account screens in this research are therefore counterfactual, not claims about production safeguards.

The modeled retry policy and fresh-tick checks describe the replay policy, not a measured replication of worker polling and transport scheduling. The one-active/pending exposure constraint is retained from the preceding research and is stricter than shared signal publication.

## Paired A/B on existing Valetax archive

Identical 40 M5/M1 candidates across five evaluation sessions, 12–18 November. A uses 30 seconds after submission; B uses five. Both use the same processing latency. Existing rules, spread/news gates, partial exits, one-active opportunity and two-per-hour cap remain paired. Values below are USD per one lot diagnostic, without account sizing, commission0 and round-trip price slippage0.10.

| Processing seconds | Post-submission seconds | Published | Completed | Wins | Total net | Closed-trade drawdown |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 5 | 21 | 13 | 5 | -306.67 | 1635.33 |
| 0 | 30 | 21 | 6 | 2 | -565.0 | 994.33 |
| 2 | 5 | 20 | 9 | 4 | 74.0 | 1163.33 |
| 2 | 30 | 20 | 2 | 1 | 149.33 | 275.0 |
| 5 | 5 | 17 | 12 | 5 | -123.67 | 1413.33 |
| 5 | 30 | 17 | 2 | 1 | -191.33 | 289.0 |
| 15 | 5 | 9 | 6 | 2 | -744.0 | 899.33 |
| 15 | 30 | 9 | 2 | 0 | -514.0 | 514.0 |
| 30 | 5 | 7 | 2 | 1 | -205.33 | 288.0 |
| 30 | 30 | 7 | 2 | 0 | -667.0 | 667.0 |

The zero-processing corrected B has 13 fills, but only 12 belong to the original 13. One original fill becomes missed and another candidate becomes filled. Corrected net is USD-306.67 per lot, versus the invalid earlier USD+188.66. With two-second processing, B has nine fills, six from the original set. A has two fills under that same processing assumption. Counts alone do not show profitability or prove a realistic phone-open latency.

### Original 13, individually

Outcome after portfolio cap/exposure rules. Same tick feed and commission0. The full trace CSV records confirmation, first eligible quote, earliest submission, action time/quote and reason.

| Original candidate | Corrected processing0/post5 | Corrected processing2/post5 |
|---|---|---|
| s1794495000S | filled | filled |
| s1794584100S | filled | filled |
| s1794587100B | missed | missed |
| s1794843600S | filled | missed |
| s1794860400S | filled | filled |
| s1794926100B | filled | filled |
| s1794928500S | filled | filled |
| s1794932400S | filled | missed |
| s1795008300B | filled | missed |
| s1795008900B | filled | missed |
| s1795014300S | filled | filled |
| s1795019700S | filled | missed |
| s1795034400B | filled | missed |

## Commission and USD100

Actual configured account commission remains unverified. Explicit scenarios are USD0, USD7 and USD14 per lot round trip. They are not claimed Valetax fee schedules. Costs are charged proportionally across partial exits; a 0.01-lot single exit pays USD0, USD0.07 or USD0.14. The grid also stresses slippage at 0.20 versus 0.10 in price. Spread is included separately through actual bid/ask. Current margin/specification snapshots are not historical guarantees.

At processing2/post5/commission7 the current partial-exit USD100 scenario publishes zero account-qualified alerts. Its 40 candidates split into 22 minimum-lot risk blocks and 18 price/spread/news/submission blocks. Each candidate's first blocking gate and available executable risk/three-exit minimum are in GOLDSIGNAL-USD100-FIRST-GATES.csv. The action quote is explicitly counterfactual for pre-publication risk blocks. Minimum-lot failure precedes the partial-exit check; do not mislabel these as partial-volume failures.

The new fixed-0.01-lot grid separately tests a single broker-valid exit. A 0.01-lot position cannot close three >=0.01-lot partials: that requires at least 0.03 lot. Removing partials solves that volume constraint only; it does not make a stop loss above the 1% cash budget acceptable.

## Separate publication diagnostic

The original four saved alerts remain 0/4 inside their zones at recorded publication + 30 seconds. This diagnostic begins at persisted publication and is not the A/B staged model. It does not separately measure review, provider receipt, transport or reaction. Original fields remain in the corrected JSON under original_publication_plus_30_diagnostic.

## Reproduce

```powershell
.venv\Scripts\python.exe -m goldsignal.scalp_research run --archive .research/scalp-20261119 --split 2026-11-12 --processing 0 2 5 15 30 --post-delays 5 15 30 60 --commissions 0 7 14 --output .research/staged-new.json
.venv\Scripts\python.exe -m goldsignal.scalp_research run --archive .research/scalp-20261119 --split 2026-11-12 --review 30 --processing 2 --post-delays 5 30 --commissions 0 7 14 --output .research/review-new.json
```

Existing artifact paths cannot be overwritten. The completed main artifact is `.research/scalp-staged-v3-executable-risk.json` for processing0/2 and post5/30; the earlier wide latency sweep uses the same corrected per-lot timing model. Its account-sizing figures are superseded by executable-price sizing in v3. Existing setup rules were unchanged; the grid is a separate research experiment.

## Fresh-session demo measurement plan

Use a separate demo instance and consenting test device on the existing Web Push channel. Do not deploy production changes as part of this replay. Freeze candidate rules, shortlist and account policy before collecting the next five complete New York sessions. A session already inspected or used for debugging cannot be the final holdout.

Record a candidate ID and UTC epoch milliseconds for M1 confirmation, backend detection, review start/end, fresh quote capture, queue creation, actual webpush call start/end and provider status. Never store endpoint URLs or push keys in the research ledger. In the demo service worker record push-event handling, showNotification completion and notificationclick separately. A service-worker event proves code execution, not the time an OS displayed the notification. Preserve offline events locally and upload later with both client event time and server ingestion time.

The existing entry-open endpoint records checked_at when the server handles the open and the available bid/ask. That timestamp includes page launch and network time; it is not the actual notification click. Add demo-only event IDs to distinguish background notification clicks from opening the chart directly. Estimate client/server clock offset with multiple round trips; retain uncertainty and monotonic client deltas. Correlate submission, push-event, click and server entry-open once per alert. Provider acceptance alone does not prove device receipt.

Collect every candidate, including blocked, expired, suppressed and unopened notifications. Report eligibility at real click and server open separately, along with processing/transport/reaction distributions and missing-event rates. Replay those measured components on the frozen shortlist. Do not widen zones or retune strategies after viewing the holdout. No observed phone measurements exist in this experiment; that fresh-device collection is still required.
