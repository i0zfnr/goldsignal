# Goldsignal: own analysis, workflow and decision logic

Written 2026-11-19 from reading the code, not from the handoff claims.
Scope: live worker (`mt5:XAUUSD.vx`), research replay, evidence UI.

---

## 1. What the system actually is

Three separate lanes that share rules but not outcomes:

| Lane | Code | Purpose | Real money? |
|---|---|---|---|
| Live worker | `worker.py`, `market.py`, `lifecycle.py` | Detect, gate, publish, track paper outcomes | No |
| Research replay | `scalp_grid.py`, `scalp_research.py`, `replay_report.py` | Offline strategy search on archived ticks | No |
| Evidence UI | `api.py`, `src/*.tsx` | Show state, funnel, per-session samples | No |

There is no order execution anywhere. Every "entry" is an alert plus paper tracking.
That is deliberate and should stay until evidence exists.

---

## 2. Live workflow, end to end

```
MT5 tick/M15 read
  -> snapshot (quote, bars, M15/M5/M1 frames, broker spec)
  -> detect candidate A: M15 baseline (strategy.setup)
  -> detect candidate B: M5 setup + M1 trigger (scalp.scalp_candidate)
  -> tag session label
  -> gate: session, expiry, quote age, permission, spread, entry zone, news
  -> review: rules (pass-through) or Gemini (advisory, can only downgrade)
  -> publish only if gate CONFIRM at publish time and <2 per rolling hour
  -> track every tick: fill, stop, TP ladder, timeout
  -> record events/alerts/push
  -> performance + per-session evidence
```

### 2.1 Detection

M15 baseline (`strategy.py:55`):
- Needs closed M15 bars; trends on M15, M30, H1 must all agree and last close beyond mean.
- Last M15 candle must be a rejection: body direction matches trend, wick >= body.
- Swing level must be a confirmed local extreme within 0.8 of the candle.
- Close must be >0.8 beyond the level.
- Levels (`strategy.py:102`): entry `[close-3, close]`, stop `close-6`, TP `+3/+6/+10`.

M5/M1 scalp (`scalp.py:18`):
- M5 breakout close beyond previous 6-bar high/low, aligned with M15 4-bar trend.
- Wait for a closed M1 retest: extreme within 0.2x average range of the boundary.
- Entry `[reference-0.25*risk, reference]`, stop at M1 extreme minus 0.1x range (min 0.10).
- TP at 1R, 1.5R, 2R. Hold 30 min. Expiry = min(trigger+3 min, setup+5 min, session cutoff).
- `max_spread = min(0.5, 0.2*risk)`.

### 2.2 Gate (`strategy.py:118`)

Order matters; first failure wins:
1. expired or session closed -> REJECT
2. quote missing, unavailable, or older than 20s -> WAIT
3. broker permission blocks direction -> REJECT
4. spread > `max_spread` -> WAIT
5. executable price (ask for BUY, bid for SELL) outside entry zone -> WAIT
6. high-impact news within 20 min before / 15 min after -> WAIT
7. else CONFIRM

### 2.3 Review (`worker.py:37`)

- `SIGNAL_REVIEW_MODE=rules` -> no model, gate result stands.
- Gemini/Ollama -> can return CONFIRM/WAIT/REJECT; code only downgrades.
  A model CONFIRM never overrides a failed gate.
- Gemini 429 pauses calls; 5xx/transport retried up to 2 times.

### 2.4 Publish

`worker.py:303`: publish only if `decision == CONFIRM` and re-evaluated at publish time,
and fewer than 2 signals in the last hour. Candidate rows are stored regardless, so
blocked candidates remain visible.

### 2.5 Outcome (`lifecycle.py:7`)

- Fill: executable price inside entry zone while gate passes.
- Stop: executable exit price crosses stop -> STOPPED.
- Timeout: `holding_until` reached -> TIMED_OUT at current price.
- TP ladder: TP1 moves stop to reference, TP2 moves stop to TP1, TP3 completes.
- Costs: `(direction*(exit-fill) - slippage)*contract*conversion - commission`,
  multiplied by each exit fraction. Skipped entirely when `spec` is None.

### 2.6 Reporting

- `/api/performance`: win/loss by net pips `(exit-fill)/0.10`, **before fees**.
- `/api/sessions`: detected, published, closed, win rate, Wilson 95% interval,
  evidence status per session (`sessions.py`).
- Status labels: `No closed trades` -> `Collecting evidence (n/30)` -> `Provisional`
  (<150) -> `Calibrated` -> `High-confidence evidence` (>=150 and interval lower bound >=80).

---

## 3. Research workflow (`scalp_grid.py`)

- 960 attempted configs, 880 unique, from family x lookback x confirmation x stop x reward.
- Frozen criteria: 10 completed development trades, positive mean net, drawdown <=10,
  losing streak <=5, >=0.5 executable entries/session.
- Validation: two windows, 5 completed trades each, across 5 cost/delay scenarios.
- Simulation: $100 equity, 0.01 lot, single exit, 2 alerts/hour, 3% daily loss stop,
  detection/processing/post delays, real spread and slippage.
- Output includes Wilson interval and an explicit "insufficient evidence" note.

This is the most statistically honest part of the repo.

---

## 4. My analysis

### Strengths
1. Execution gates are separate from signal logic and are deterministic.
2. AI cannot override risk gates. Correct design.
3. Research uses real ticks, spread, delays and costs; no future data in features.
4. Labels say "Simulated" and evidence statuses refuse to invent confidence.
5. Every candidate is stored, including blocked ones, so the funnel is auditable.

### Defects, ranked by impact on your goal

**D1. Account-risk gate is inactive in live mode (critical).**
`.env` has no `BROKER_*` keys -> `market.py:196` returns `None` -> `account_fit` always
skips and `result_per_lot` stays null. Live signals currently have no sizing check and
no net P/L. Until fixed you cannot know whether a signal was even tradeable at $100.

**D2. M15 baseline reward/risk is structurally weak.**
Entry zone `[close-3, close]`, stop `close-6`, TP1 `close+3`.
Filled near zone top: risk 6, TP1 3 -> 0.5R. You need >67% at TP1 before costs.
Filled at zone bottom: 2R. So outcome depends on where the tick happens to be.
The scalp lane (1R/1.5R/2R) is the only lane with sane geometry at 0.01 lot.

**D3. Validation sample is too small to select a winner.**
5 completed trades per validation window cannot distinguish 55% from 80%.
Selecting the best of 880 configs on 5 trades is noise mining, even with frozen criteria.

**D4. Win rate is pre-fee.**
`api.py` performance uses price pips only. Partial exits can show a win while net is
negative after spread/commission. Label says "before fees", but users read the big number.

**D5. MT5 IPC errors were hidden.**
`Worker cycle failed.` with no cause. Now fixed with cause text plus one reconnect retry.
Intermittent `-10001` remains possible when the terminal restarts or reconnects.

**D6. Timeout handling depends on ticks.**
Filled signals are skipped when a cycle has no ticks (`worker.py:169`), so a feed gap
delays timeout exits. Minor, but it biases hold time during outages.

**D7. Entry fill ignores adverse slippage.**
Fill price is the quote, slippage is applied only to P/L. Optimistic by design in both
live tracking and research. Same assumption in both, so comparisons stay fair, but
absolute expectancy is overstated.

### What "high confidence" requires (non-negotiable)

Confidence is a property of a measured sample, not of more inputs:

- Outcome must be net-of-cost, single exit policy, timeout counted as a real exit.
- Per session, per strategy, chronological split; no refitting on the final period.
- Claim only what the lower bound supports:
  - ~80% point estimate: show the interval, expect lower bound well below 80 at n<150.
  - "At least 80%": need n in the hundreds per session at that win rate.
- Positive net expectancy and bounded drawdown must hold simultaneously.

More indicators cannot fix D1 or D2. Filters cannot fix D3.

---

## 5. Recommended workflow

### Phase 0 — make the platform truthful (days, not weeks)
1. Run `python -m goldsignal.demo_session audit` and fill `BROKER_*` env values.
2. Restart worker; confirm `spec` is non-null and `result_per_lot` is populated.
3. Add net-of-cost column beside win rate; keep the pre-fee number for continuity.
4. Confirm per-session evidence rows populate as trades close.

Gate to proceed: at least one closed trade with non-null net P/L and a visible
account-risk decision (FIT or SKIP with reason).

### Phase 1 — fix tradeability at $100
5. Compute the stop-distance distribution of all detected candidates.
6. Keep only setups whose 0.01-lot loss <= 1% of equity; show the rest as Blocked.
7. Decide: scalp-only at $100, or raise capital. Do not widen risk silently.

Gate: a printed funnel — detected, gate-pass, risk-pass, published, filled, closed.

### Phase 2 — collect honest forward evidence
8. Freeze the outcome definition (single exit, net, timeout included).
9. Run 20 development sessions with zero threshold changes.
10. Report per session: trades, win rate + interval, net expectancy, drawdown, streak,
    zero-entry days and their first rejection reason.

Gate: >=30 closed trades per session bucket before any model work.

### Phase 3 — one change at a time
11. Test each candidate feature against the unchanged control on the same candidates:
    HTF agreement, retest quality, M1 trigger completion, spread-to-stop ratio, RSI(8).
12. Keep a feature only if it raises net expectancy with non-overlapping intervals.

Gate: feature lift survives both cost scenarios and the slow-phone scenario.

### Phase 4 — calibration, then claims
13. Split calibration data from fitting data; produce reliability by score region.
14. Publish a confidence number only with sample size, window and interval attached.
15. Any "80%" label must be the lower bound, not the point estimate.

### What not to do
- Do not enable thresholds per session before each session has its own sample.
- Do not add a second AI layer that outputs opinions without measurable features.
- Do not count max favorable excursion as a win.
- Do not treat 880 correlated variants as 880 discoveries.

---

## 6. One-paragraph verdict

The engineering is honest and mostly well-layered: deterministic gates, AI fenced off,
real-tick replay with costs, evidence labels that refuse to lie. The product is not yet
a signal service. The account gate is inactive in live mode, the M15 lane has 0.5R
geometry, and the validation sample is too small to justify any edge claim. Fix those
three things in that order and the system becomes capable of earning confidence; it
cannot be given confidence by adding indicators or by scanning more sessions.
