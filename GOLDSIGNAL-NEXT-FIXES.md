# Goldsignal next fixes

## 1. Reduce entry alert frequency and validate confidence

- The screenshot shows three M5/M1 BUY entries at 21:26, 21:47, and 21:52 MYT. All three were recorded as stopped.
- Aim for one or two qualifying entries per hour, with a maximum of two across M15 and M5/M1 in any rolling 60 minutes. Allow zero when setups fail the quality gate. Count new signals only so TP and SL updates can still reach users.
- The requested confidence threshold is above 80%. Define the outcome before measuring it and validate the score on unseen Valetax bid/ask ticks with realistic alert delays, spread, and costs. A Gemini confirmation and five historical pattern matches do not establish a measured probability. Keep any uncalibrated score labeled as a setup score.
- When the cap or quality gate blocks a candidate, show the reason. Recheck the entry zone, quote, and expiry before publishing any candidate later.

## 2. Replace closed signal lines with a chart box

- While a signal is active, remove the corresponding live target line as TP1 or TP2 is reached. Keep the active stop and remaining target levels visible.
- After all targets are reached or the stop is hit, remove all remaining live signal lines and display a bounded risk/reward box like the second screenshot. Show the reward and risk zones from the recorded fill and levels, and end the box at the recorded exit time. Label the actual outcome and show which targets were hit before exit.
- A stop after a partial take-profit still closes the box. If the price later crosses a target, the recorded result stays stopped. Verify BUY and SELL, target-by-target completion, and a stop after partial profit. Confirm separately how expired and timed-out signals should appear.

## 3. AI Insight and chart zones

- Add an AI Insight panel beside the live chart. Show BUY, SELL, or WAIT, the quote and analysis time, the setup type, and the trend for each timeframe used. Use the reference's three-part explanation structure: market structure, why the zones matter, and what must happen before entry.
- Derive supply, demand, swing, and potential liquidity zones from closed broker candles. Define exactly how the engine detects a break of structure, a change of character (CHoCH), and rejection patterns such as pin bars or engulfing candles. Describe order blocks as zones inferred from price action. Candle data alone cannot establish who placed orders.
- Show the nearest and next relevant zones, their price bounds, distance from the current quote, and the confirmation still needed. Let users toggle the chart zones. Keep watch zones visually distinct from active entry levels and the completed trade boxes in section 2.
- Include the invalidation level and risk/reward for each actionable setup. The reference's 88% SELL, price levels, and 1:3 minimum are examples. The 80% rule requires the validation in section 1, and a 1:3 gate needs its own replay before adoption.
- Compute the analysis inputs in Python. Reuse one short Gemini explanation for all viewers when the underlying setup changes, within the existing shared quota. Keep showing the last analysis time and use the Python scan status when Gemini is paused.

## 4. Live signal, performance, and history

- Add a clear **Waiting for confirmation** state with the current session, the watched direction and zone, and the next condition the scanner needs. Make it clear when there is an active, actionable entry.
- Add Day, Week, Month, and All performance views. Show signal count, completed trades, net simulated pips, and outcome counts. Define the win-rate denominator using completed fills and explain how break-even, partial exits, and expired signals are counted.
- The added performance screenshot shows a win-rate ring with TP Hit, Break-Even, and Stop Loss counts, plus a time chart with a win-rate line and net pips per day bars. Use separate percentage and pip scales, label the date range in MYT, and show summary cards for Total Signals, Win Rate, and Net Pips. Show no data for empty periods and include sample counts with win rates. Use simulated Goldsignal records for the chart and cards.
- Show direction, strategy/timeframe, issue time, outcome, and simulated result in signal history. Open a signal's details to show its original rationale, entry zone, actual simulated fill, SL, TP1–TP3, and recorded exit timeline. Use Goldsignal's recorded results for every metric.

## 5. USD news

- Expand the current USD calendar into a compact panel with event name, local time, impact, and source. Include the FOMC minutes and evaluate the other examples shown: Philly Fed manufacturing, jobless claims, and the University of Michigan sentiment and inflation expectations releases.
- Show which events trigger an entry pause and whether a pause is active. Validate source coverage and timestamps before adding an event to the entry-blocking rules.

## 6. Lot calculator and personal P&L

- The reference shows a standalone calculator using the viewer's capital and chosen risk. Keep this optional since the old Account Fit form was removed. For a selected signal, use its actual entry-to-stop distance and broker symbol specs, include estimated costs, round down to the lot step, and flag when the minimum lot exceeds the chosen risk.
- The monthly P&L calendar is a reference for personal results and goals. Confirm where personal results would come from before building it. Label any simulated data clearly.

## 7. Leaderboard reference

- The screenshots also show a top-profit leaderboard with rank, balance, equity, profit, and return percentage. Confirm whether Goldsignal should have a leaderboard, and whether it should use paper results or opt-in read-only MT5 results. The quiz and competition navigation are reference material pending a separate decision.

## 8. Installed app push notifications

- Reported behavior: after installing Goldsignal, no notification prompt appeared. The user enabled notifications manually, but signals in the app still did not appear as phone notifications.
- Add a visible **Enable notifications** action on first use of the installed app. Ask for permission when the user taps it, then register the device's push subscription with the backend. On iOS and iPadOS, test from the Home Screen app. [WebKit Web Push guidance](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/)
- The dashboard currently checks whether the signed-in identity has a stored subscription. Verify the installed app has its own matching local subscription. Test the same sign-in across browser and installed app contexts, and check whether one device overwrites another device's subscription.
- Add a test notification that uses this device's subscription and works without waiting for a signal. Distinguish OS permission, device subscription, provider acceptance, and actual notification display. Verify delivery with the app closed, then verify that tapping a notification opens the intended signal.
- At the time of the check, the backend had one stored subscription and three entry pushes marked sent. Three shared preview records were also present. Provider acceptance does not establish that the affected device displayed a notification.
