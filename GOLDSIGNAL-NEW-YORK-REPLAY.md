# New York M15 baseline replay

**Scope** · Valetax `XAUUSD.vx`, 4–17 November 2026 New York dates, existing M15 rules, rules-only replay. The live service still monitors the configured regional sessions. This benchmark used New York entries only.

## Results

- **360** closed M15 candles fell inside the configured New York and broker window. **One** met the setup rules and passed the historical entry checks.
- The **16 November, 11:15 New York** SELL had an entry zone of **3858.66–3861.66**, initial stop **3864.66**, and targets **3855.66 / 3852.66 / 3848.66**.
- The candidate's audit window held **118,182** normalized broker bid/ask ticks. The maximum gap between returned ticks was **3.986 seconds**.

| Combined alert and reaction delay | Executable bid | Outcome |
| ---: | ---: | --- |
| 0 s | 3858.67 | Simulated fill, stopped, **−$610 per lot** after assumed costs |
| 5 s | 3858.59 | Missed. Bid had left the entry zone. |
| 15 s | 3858.13 | Missed. Bid had left the entry zone. |
| 30 s | 3857.78 | Missed. Bid had left the entry zone. |
| 60 s | 3858.58 | Missed. Bid had left the entry zone. |

At the 30-second baseline delay, there were **zero fills** and consequently no completed-trade return. For the illustrative **$100 USD account at 1% risk**, **0 of 1** setups could be sized. MT5 reported a **0.01 lot minimum and step**, with a **100 oz contract**. At the least favorable entry in the zone, the minimum lot would lose **$6.10** at the initial stop under the stated cost assumptions, against **$1.00** budget. The zero-delay loss is a per-lot strategy result. This small account would have skipped it.

## How the replay works

- Reuse the live closed-candle setup, entry gate, sizing and simulated lifecycle. Keep all live setup thresholds. Evaluate each candidate against historical bid/ask from the close. Once the first eligible quote appears, apply the chosen delay and check the first available executable quote. A missed price ends the attempt.
- For a size that fits, round to the broker lot grid and allocate across three broker-valid exits. The remaining position follows the baseline stop and timeout rules. The sizing benchmark estimates margin from the connected account's current MT5 calculator. It uses **$0 assumed round-trip commission and 0.10 price units of adverse slippage**. Historical account costs, leverage and push latency were not measured. [MT5 profit calculator](https://www.mql5.com/en/docs/python_metatrader5/mt5ordercalcprofit_py)
- Replay with the recorded BLS, BEA and Fed calendar cache. This period's snapshot included BLS PPI, CPI and Employment Situation. Historical calendar freshness, changes in release times, and retrospective manual pauses are unavailable. Today's BEA parser also supports GDP alongside PCE. [BLS release schedule](https://www.bls.gov/schedule/news_release/) · [BEA release schedule](https://www.bea.gov/news/schedule) · [Fed FOMC calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)
- Validate the configured two-hour broker clock offset against a fresh terminal quote. The scored interval follows the November clock change. Warm-up history uses the same configured offset. This extractor validates candidate windows without collecting a tick archive for all 360 bars. [MT5 tick history](https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksrange_py)

Run from the configured Windows checkout:

```powershell
.\.venv\Scripts\python.exe -m goldsignal.replay_report --start 2026-11-04 --until 2026-11-18 --delay 30 --commission 0 --slippage 0.10 --output another-replay.json
```

The [machine-readable 30-second report](goldsignal-new-york-replay.json) includes the quote, entry levels, outcome and sizing for every candidate. This sample is too small to estimate win rate, drawdown or session-level performance. The 256 New York configurations, future all-session comparison, Gemini shadow comparison and physical phone test remain pending.
