# Goldsignal session setup coverage

Valetax XAUUSD.vx M1, M5 and M15 candle replay, 4–17 November 2026 New York dates. Session dates below use each session’s local time. Window edges can produce partial sessions. Sydney and Tokyo overlap, and qualifying setups are counted in every session open at confirmation.

This is an upper-bound setup scan. It does not replay bid/ask gates, calendar availability, Gemini review, or alert delivery. A setup can be counted in this report and still fail to produce an alert.

| Session | Observed sessions | With an M15 setup | With an M5/M1 setup | With either |
| --- | ---: | ---: | ---: | ---: |
| Sydney | 11 | 0 | 10 | 10 |
| Tokyo | 11 | 1 | 11 | 11 |
| London | 10 | 3 | 10 | 10 |
| New York | 10 | 1 | 10 | 10 |

| Session | Local date | Closed M1 observations | M15 setups | Unique M5/M1 setups |
| --- | --- | ---: | ---: | ---: |
| London | 2026-11-04 | 540 | 0 | 7 |
| London | 2026-11-05 | 540 | 0 | 10 |
| London | 2026-11-06 | 540 | 0 | 8 |
| London | 2026-11-09 | 540 | 0 | 8 |
| London | 2026-11-10 | 540 | 0 | 10 |
| London | 2026-11-11 | 540 | 1 | 9 |
| London | 2026-11-12 | 540 | 0 | 14 |
| London | 2026-11-13 | 540 | 0 | 5 |
| London | 2026-11-16 | 540 | 1 | 10 |
| London | 2026-11-17 | 540 | 1 | 7 |
| New York | 2026-11-04 | 536 | 0 | 9 |
| New York | 2026-11-05 | 536 | 0 | 9 |
| New York | 2026-11-06 | 536 | 0 | 8 |
| New York | 2026-11-09 | 536 | 0 | 4 |
| New York | 2026-11-10 | 536 | 0 | 5 |
| New York | 2026-11-11 | 536 | 0 | 8 |
| New York | 2026-11-12 | 536 | 0 | 5 |
| New York | 2026-11-13 | 536 | 0 | 8 |
| New York | 2026-11-16 | 536 | 1 | 10 |
| New York | 2026-11-17 | 536 | 0 | 8 |
| Sydney | 2026-11-04 | 60 | 0 | 0 |
| Sydney | 2026-11-05 | 475 | 0 | 6 |
| Sydney | 2026-11-06 | 475 | 0 | 9 |
| Sydney | 2026-11-09 | 419 | 0 | 5 |
| Sydney | 2026-11-10 | 475 | 0 | 5 |
| Sydney | 2026-11-11 | 475 | 0 | 12 |
| Sydney | 2026-11-12 | 475 | 0 | 6 |
| Sydney | 2026-11-13 | 475 | 0 | 5 |
| Sydney | 2026-11-16 | 419 | 0 | 4 |
| Sydney | 2026-11-17 | 475 | 0 | 10 |
| Sydney | 2026-11-18 | 415 | 0 | 9 |
| Tokyo | 2026-11-04 | 240 | 0 | 2 |
| Tokyo | 2026-11-05 | 540 | 0 | 9 |
| Tokyo | 2026-11-06 | 540 | 0 | 12 |
| Tokyo | 2026-11-09 | 540 | 0 | 16 |
| Tokyo | 2026-11-10 | 540 | 0 | 8 |
| Tokyo | 2026-11-11 | 540 | 0 | 15 |
| Tokyo | 2026-11-12 | 540 | 0 | 13 |
| Tokyo | 2026-11-13 | 540 | 0 | 4 |
| Tokyo | 2026-11-16 | 540 | 0 | 5 |
| Tokyo | 2026-11-17 | 540 | 1 | 7 |
| Tokyo | 2026-11-18 | 300 | 0 | 9 |

## Bid/ask eligibility replay

For each unique setup, I replayed broker ticks up to expiry with the saved scheduled-event calendar. The 30-second result uses the first quote at or after a simulated 30-second alert and reaction delay, within a further 20-second quote-availability window. Historical calendar freshness, manual pauses, Gemini, and real push delivery were unavailable or outside this replay.

Unique candidates checked: **214**. Candidate windows with zero returned ticks: **34**.

| Session | Observed | With an executable candidate | Still executable after 30 s |
| --- | ---: | ---: | ---: |
| Sydney | 11 | 9 | 5 |
| Tokyo | 11 | 9 | 8 |
| London | 10 | 8 | 6 |
| New York | 10 | 8 | 3 |

| Session | Local date | Executable candidates | Still executable after 30 s |
| --- | --- | ---: | ---: |
| London | 2026-11-04 | 0 | 0 |
| London | 2026-11-05 | 0 | 0 |
| London | 2026-11-06 | 6 | 2 |
| London | 2026-11-09 | 3 | 0 |
| London | 2026-11-10 | 6 | 2 |
| London | 2026-11-11 | 7 | 2 |
| London | 2026-11-12 | 9 | 2 |
| London | 2026-11-13 | 3 | 0 |
| London | 2026-11-16 | 7 | 3 |
| London | 2026-11-17 | 7 | 2 |
| New York | 2026-11-04 | 0 | 0 |
| New York | 2026-11-05 | 0 | 0 |
| New York | 2026-11-06 | 4 | 0 |
| New York | 2026-11-09 | 1 | 0 |
| New York | 2026-11-10 | 3 | 0 |
| New York | 2026-11-11 | 7 | 2 |
| New York | 2026-11-12 | 4 | 0 |
| New York | 2026-11-13 | 2 | 0 |
| New York | 2026-11-16 | 5 | 2 |
| New York | 2026-11-17 | 6 | 3 |
| Sydney | 2026-11-04 | 0 | 0 |
| Sydney | 2026-11-05 | 0 | 0 |
| Sydney | 2026-11-06 | 6 | 2 |
| Sydney | 2026-11-09 | 4 | 0 |
| Sydney | 2026-11-10 | 4 | 1 |
| Sydney | 2026-11-11 | 4 | 1 |
| Sydney | 2026-11-12 | 3 | 0 |
| Sydney | 2026-11-13 | 3 | 2 |
| Sydney | 2026-11-16 | 3 | 0 |
| Sydney | 2026-11-17 | 4 | 0 |
| Sydney | 2026-11-18 | 8 | 3 |
| Tokyo | 2026-11-04 | 0 | 0 |
| Tokyo | 2026-11-05 | 0 | 0 |
| Tokyo | 2026-11-06 | 8 | 2 |
| Tokyo | 2026-11-09 | 9 | 2 |
| Tokyo | 2026-11-10 | 6 | 2 |
| Tokyo | 2026-11-11 | 5 | 1 |
| Tokyo | 2026-11-12 | 10 | 1 |
| Tokyo | 2026-11-13 | 3 | 2 |
| Tokyo | 2026-11-16 | 4 | 1 |
| Tokyo | 2026-11-17 | 6 | 0 |
| Tokyo | 2026-11-18 | 8 | 3 |
