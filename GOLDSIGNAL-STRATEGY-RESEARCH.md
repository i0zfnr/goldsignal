# Strategy and worker research plan

Purpose: a controlled way to add strategies without turning the project into
880 correlated guesses. One lane = one frozen hypothesis.

---

## 1. Rules for every new strategy

1. Write the trigger, regime, entry, stop, targets, hold time and invalidation **before** looking at results.
2. Define the outcome first: single exit, net of spread/slippage/commission, timeout counts.
3. Test on the existing archives, development split only.
4. Control = current B lane on the same candidate stream and costs.
5. Pass to shadow mode (detected, no alerts) before any live alert.
6. One change at a time. No threshold tuning after seeing the final period.
7. Keep the lane labelled `research` in the UI until it passes.

---

## 2. Candidate strategies

Ordered by expected value for this codebase, not by excitement.

### A — M15 rejection continuation (existing)
- Hypothesis: trend alignment + rejection at a confirmed swing continues.
- Regime: trending.
- Geometry: entry zone 3.0 wide, stop 6.0, TP 3/6/10 → 0.5R near zone top.
- Status: implemented, weak at $100 (stop 6.0 = 6% risk at 0.01 lot). Not primary.
- Research action: fix geometry (ATR-normalized stop) or leave disabled at $100.

### B — M5 breakout + M1 retest (existing, primary)
- Hypothesis: momentum breakout with a closed M1 retest continues.
- Regime: trending / expansion.
- Geometry: stop 0.1–1.0, targets 1R/1.5R/2R.
- Status: implemented, unproven (no variant reached 10 development trades).
- Research action: collect forward sample; measure net expectancy, MAE, fill delay.

### C — Failed breakout / range fade (proposed)
- Hypothesis: a breakout that closes back inside the range reverses toward the range mid.
- Regime: range / low volatility.
- Trigger: M5 closes back inside after breaking the prior 6-bar extreme, or session high/low sweep + closed M1 reversal.
- Entry: M1 confirmation close; stop beyond the sweep; targets 0.75R/1R/1.5R; hold 20 min.
- Risk: gets run over in trends; needs a range filter (e.g. ADX or range width vs ATR).
- Expected win rate: 40–55%; needs 1.5R average to profit.
- Status: reserved. Next to implement in shadow mode.

### D — London open continuation (proposed)
- Hypothesis: the first expansion after the London open continues in its direction.
- Regime: session open, rising volatility.
- Trigger: 5-min opening range, breakout with M1 confirmation, only 07:00–10:00 London.
- Geometry: stop at opening-range edge, targets 1R/1.5R, hold 45 min.
- Why: different session, different behaviour; current evidence is New York only.
- Status: research only; needs London tick archives.

### E — Volatility compression breakout (proposed)
- Hypothesis: a squeeze (narrow range vs ATR) resolves with a directional move.
- Regime: pre-expansion.
- Trigger: 6+ M5 bars inside a narrow band, then M5 close outside + M1 retest.
- Geometry: stop at band edge, targets 1.5R/2R.
- Risk: low frequency; correlated with B.
- Status: research only.

### F — Trend pullback to value (proposed)
- Hypothesis: in an aligned trend, a pullback to M15 structure/EMA gives better RR than breakout chasing.
- Regime: trending.
- Trigger: M15 trend aligned, price pulls back to prior structure, M1 reversal confirmation.
- Geometry: stop below structure, targets 1.5R/2R/3R.
- Why: directly addresses A's bad RR and B's late entries.
- Status: research only.

### G — Post-news stabilization (not recommended yet)
- Hypothesis: after a high-impact release, the first M1 structure in the release direction continues.
- Risk: spread spikes, slippage, no historical tick coverage for every release.
- Status: do not implement until news-window ticks are archived and audited.

### H — Sizing/geometry variant (not a strategy)
- Rename A's stop to ATR-based and re-test. This is a fix, not a new lane.

---

## 3. Worker planning

Keep one process. Lanes are logical, not separate processes, because MT5 IPC
fails with concurrent attach.

| Component | Role | Shared? |
|---|---|---|
| Kuro | feed, orchestration, health | yes |
| Kaze | detection per lane | per lane |
| Mizu | gate + risk + economics | per lane |
| Nanao | AI confirmation (advisory) | per lane |
| Hikari | publication + delivery | per lane |

Lane states:
- `reserved` — no detector (C, D, E, F until built).
- `shadow` — detector runs, candidates recorded, no alerts.
- `live` — alerts allowed, requires passed evidence.

Capacity rules:
- Max one open exposure at a time across lanes.
- Keep the 2 alerts per rolling hour cap global.
- Never let two lanes publish the same M5 candle.
- One lane failing must not stop the others; isolate exceptions per lane.

UI requirements:
- Show lane state (reserved/shadow/live), not just "waiting".
- Show per-lane evidence: detected, shadow fills, live fills, win rate + interval.
- Label unproven lanes clearly. No confidence badge without sample.

---

## 4. Research workflow per lane

1. Data qualification: ticks complete, spreads present, clock offset known, session coverage counted.
2. Freeze the hypothesis and thresholds in a JSON file next to the code.
3. Development replay: candidates → gates → fills → net outcomes.
4. Control comparison: B on the same days and costs.
5. Shadow forward: 20 sessions, no alerts, record detection and hypothetical fills.
6. Validation: two windows, ≥30 completed each, both must pass.
7. Final reserve: untouched until the shortlist is frozen.
8. Report: net expectancy, win rate + Wilson interval, drawdown, losing streak, zero-entry days.

---

## 5. Acceptance gate (all must hold)

- ≥30 completed trades per validation window.
- Positive net expectancy after costs.
- Closed-trade drawdown ≤ 10 (on $100 paper equity).
- Worst losing streak ≤ 5.
- Wilson 95% lower bound reported, never hidden.
- Lift over control (B) on the same period, not just absolute profit.
- Survives the slow-phone and high-cost scenarios.

Anything less is reported as "insufficient evidence", not as a win.

---

## 6. Implementation order

1. B evidence collection and MAE tracking (in progress).
2. C shadow detector + replay comparison (next).
3. F pullback detector (shares trend filter with A).
4. D London lane, only with London tick archives.
5. E squeeze lane, only if C/F show the regime filters work.
6. G news lane last, or never.

---

## 7. What this plan refuses to do

- Add indicators without a control comparison.
- Enable a lane because it "looks good" on a chart.
- Promise a daily signal or a fixed win rate.
- Count max favorable excursion as a win.
- Treat correlated lanes as independent discoveries.
