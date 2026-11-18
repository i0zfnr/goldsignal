# Goldsignal

Goldsignal monitors XAUUSD M15, reviews closed-candle setups and tracks simulated execution. The local replay uses synthetic candles, ordered bid/ask ticks and a mock USD calendar. The default rules path and replay use zero paid API calls and require no provider credentials.

## Run the Windows demo

From PowerShell with Python 3.11+ and Node 20+:

```powershell
Set-Location C:\laragon\www\goldsignal
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd ci
npm.cmd run build
.\.venv\Scripts\python.exe -m goldsignal.store
```

Run these commands in two PowerShell windows from the same project directory:

```powershell
# Window 1
.\.venv\Scripts\python.exe -m goldsignal.worker

# Window 2
.\.venv\Scripts\python.exe -m uvicorn goldsignal.api:app --host 127.0.0.1 --port 8000
```

Open [the dashboard](http://127.0.0.1:8000). The first replay cycle publishes the SELL at 3793.42 and reaches TP3 on the ninth quote, about 40 seconds after startup. The clock advances three simulated minutes per worker cycle. Each repetition advances to another synthetic Monday. Every third cycle pauses entries for the mock release and tracks the same candidate in the no-news comparison. The worker continues while the page is closed. Restart either process against the same database to resume. Point both processes to a new SQLite filename to replay from the start.


```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd run build
```

## Laragon MySQL

Start MySQL in Laragon. Run the following in its MySQL console using a local administrator. Choose a unique password for the service account.

```sql
CREATE DATABASE goldsignal CHARACTER SET utf8mb4;
CREATE USER 'goldsignal'@'127.0.0.1' IDENTIFIED BY 'replace-this-password';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, INDEX, ALTER
  ON goldsignal.* TO 'goldsignal'@'127.0.0.1';
```

```powershell
Copy-Item .env.example .env
notepad.exe .env
```

Set `DATABASE_URL=mysql+pymysql://goldsignal:YOUR_URL_ENCODED_PASSWORD@127.0.0.1:3306/goldsignal?charset=utf8mb4`. Match Laragon's configured port. Run `python -m goldsignal.store` with the project venv before starting the worker or web process. Migration v1 creates the schema version, records and candle tables. Both runtimes use the same database. For local development, SQLite is the default so the replay can run without starting Laragon.

## Rules and simulated execution

- The worker checks the configured entry sessions before strategy evaluation and again before publication. Default weekday windows use local time in each city: Sydney 08:00–17:00, Tokyo 09:00–18:00, London 08:00–17:00, and New York 08:00–17:00. Overlaps form a continuous entry window when the broker is open. Set `ENTRY_SESSIONS` to a comma-separated subset of `sydney,tokyo,london,new_york` to narrow coverage. All stored stamps are UTC epochs, chart candles use open time in seconds, and the dashboard displays session times in MYT.
- A swing high or low strictly exceeds the neighboring highs or lows on both sides. The default is two bars per side. It becomes available when the second right-hand candle closes. The scanner uses the newest qualifying swing within its recent 48-candle lookback. The rejection bar must come after confirmation, touch within 0.80 of the swing, close past the zone on the rejection side, have a directional body and have a wick on the rejection side at least as long as that body.
- Each of M15, M30 and H1 must have four contiguous closed bars by default. M30 and H1 aggregate complete UTC-aligned M15 bars. For BUY, the latest close must sit above both the oldest close and the mean of the window in each timeframe. SELL reverses both comparisons. **Aligned** is a rule grade.
- `E` is the rejection close. BUY entry is `E − 3` to `E`, SL is `E − 6`, and targets are `E + 3/6/10`. SELL mirrors those distances. One displayed pip is 0.10 in price.
- Execution confirmation requires a fresh quote, spread within the limit, executable bid or ask inside the zone, no calendar pause and an open window. The pending signal expires at the earlier of 30 minutes after the rejection close and the session cutoff. It fills at the first subsequent eligible tick in the zone, using ask for BUY and bid for SELL. Filled trades keep tracking beyond the entry window. Tracking uses opposite-side quotes for targets and stops, the actual tick price for gaps, and the first executable tick at or after the three-hour timeout.
- TP1 moves SL to `E`. TP2 moves SL to TP1. Simulation uses thirds of a lot-equivalent. Demo estimates use 100 oz per lot, 0.01 lot minimum and step, 1% notional margin, USD 7 per lot round trip and 0.10 price-unit adverse slippage. Side-specific prices already account for spread. Costs are charged proportionally at exits.
- The candidate record retains setup features, first and latest review evidence, and calendar gate reasons. The same quote and rule gates drive a separate simulated branch with the calendar gate omitted. Compare fill rate, fills that reached TP1 before a stop, and results per lot after costs. Results with unknown cost inputs show as unavailable.

## Calendar and review

The live worker refreshes public calendars and RSS in a background thread. BLS supplies CPI, PPI and Employment Situation. BEA supplies Personal Income and Outlays dates. The Fed supplies scheduled FOMC meeting dates, modeled at 14:00 New York on the decision day. Verify exceptional FOMC release times before using the calendar operationally. A required schedule older than six hours blocks new entries. The default news pause is 20 minutes before through 15 minutes after each release. Official schedules typically supply dates and times. Missing actual, forecast and previous values are kept blank. The calendar source contract in `goldsignal/news.py` can also accept those fields from a future read-only MQL5 bridge.

Fed RSS and URLs in `HEADLINE_RSS_URLS` are context. Feed entries retain the headline, link, publication and first-seen timestamps in the cached feed. Headlines cannot initiate or improve a setup. Rules mode caches computed setup features and source evidence in the database and makes zero model calls. Optional `SIGNAL_REVIEW_MODE=ollama` uses a loopback model with validated CONFIRM, WAIT or REJECT output. The worker refreshes the quote and reruns execution rules after live model review. Gemini is disabled by default and can be enabled by the admin. 9Router and paid news providers have no configured integrations.

[BLS iCalendar](https://www.bls.gov/help/hlpical.htm) · [BEA release schedule](https://www.bea.gov/news/schedule/full) · [Federal Reserve FOMC calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) · [Federal Reserve RSS](https://www.federalreserve.gov/feeds/feeds.htm)

## Connect your MT5 terminal

1. On the always-on Windows collector host, open the 64-bit MT5 terminal, sign in to the intended broker and enable the exact gold symbol in Market Watch. Use read-only investor credentials if supported by the broker. Leave the terminal running in the Windows user session that runs the worker.
2. In the project venv install the official connector with `.\.venv\Scripts\python.exe -m pip install MetaTrader5`. Set `MARKET_SOURCE=mt5`, `MT5_TERMINAL_PATH=C:/path/to/terminal64.exe` and `BROKER_SYMBOL` to the actual Market Watch symbol in `.env`.
   If the terminal returns broker-local timestamps, set `MT5_SERVER_OFFSET_MINUTES` to the measured offset from UTC. The connected Valetax terminal returned UTC+02:00 on November 18, 2026. This setting is fixed and applies to the imported history. Recheck it at broker clock changes and restart with a fresh live store if previously imported candles crossed the offset change.
3. Enter the broker's regular New York hours in `BROKER_HOURS` as comma-separated `HH:MM-HH:MM` intervals. Use `24:00` as an interval end and split intervals that cross midnight. Set the Friday close, Sunday open and broker holiday dates. Use `BROKER_DATE_HOURS` for exceptional dates. For example, `{"2026-11-26":"00:00-13:00"}` specifies one early close. The connector checks the supplied schedule against symbol permissions and current quotes. Use the broker's notices to maintain exceptions.
4. To enable estimated simulation costs, set verified `BROKER_ACCOUNT_CURRENCY`, `BROKER_UNITS_PER_CURRENCY` (1 or 100), `BROKER_CONVERSION`, `BROKER_MARGIN_RATE` (fraction), round-trip `BROKER_COMMISSION` per lot in account currency, and `BROKER_SLIPPAGE` in price units. Set `BROKER_COSTS_AS_OF` to a UTC ISO timestamp such as the output of `(Get-Date).ToUniversalTime().ToString('o')`. Refresh the cost timestamp and values together. The worker takes lot minimum, maximum, step and contract size from MT5. The estimates use verified linear XAUUSD contract economics.
5. Run the worker and web process. Confirm LIVE during broker hours, fresh bid/ask, official calendar source timestamps and the expected next entry opening in MYT. Verify a broker symbol and its specifications before testing a live alert. All trade tracking stays simulated. The adapter does not submit orders.

For restart recovery, configure Task Scheduler in the same Windows user account. Launch the terminal at user logon, then start `.venv\Scripts\python.exe` with `-m goldsignal.worker` from the repository directory, with restart on failure and one running instance. Keep MySQL running as a service. Start the web process as a separate task or service. On reconnect the worker resumes from the persisted market cursor, re-reads missing candles and catches up on ordered quotes. A closed browser has no effect on monitoring. A stopped or disconnected worker shows STALE once the heartbeat or quote expires.

[Official MT5 Python connector](https://www.mql5.com/en/docs/python_metatrader5)

## Ryaze hostname and phone alert test

Use one always-on Windows host for the simplest live deployment. Run the web app on loopback, the MT5 terminal and worker in the same user session, and MySQL on a local or private connection. Keep one worker per database and symbol. If the API and Windows collector run on different hosts, configure both with the same private MySQL database and matching source, symbol and session settings.

1. Ask the owner of the existing Ryaze hostname for access to its authoritative DNS record. Point the exact hostname to the host's public IPv4 with an A record or to the hosting provider's assigned target with a CNAME. Use AAAA only for a working public IPv6 path. If Ryaze controls the hostname, its owner needs to apply the record or provide a configurable hostname. The record value depends on the chosen host.
2. Build and migrate the app on the host. Set `SECURE_COOKIE=1` and run FastAPI on `127.0.0.1:8000`. Put the actual hostname in the Caddyfile below and run `caddy run --config Caddyfile` as a supervised service. Route public ports 80 and 443 to Caddy and confirm that the URL loads with a trusted certificate.

```caddyfile
your-existing-ryaze-hostname.example {
    reverse_proxy 127.0.0.1:8000
}
```

3. Generate a dedicated VAPID pair with `.\.venv\Scripts\python.exe -m goldsignal.vapid C:/secure/goldsignal-vapid.pem`. Set the printed `VAPID_PUBLIC_KEY`, that absolute `VAPID_PRIVATE_KEY_FILE` path, and `VAPID_SUBJECT=mailto:operator@example.com`. Put the private key in a directory readable only by the service account. Restart the API and worker.
4. For a predictable test, use `MARKET_SOURCE=demo` and a separate database. Open the HTTPS URL on the Pixel 7 in Chrome. Tap **Enable phone alerts**, allow notifications, and background Chrome. Wait for the next eligible replay cycle, within about two minutes at the default replay rate. Expect a **DEMO** entry and later tracking notifications. Tap one to open the matching saved signal. Check delivery in **Alert preview**, then use **Disable phone alerts** if desired.

Web Push sends shared alerts to opted-in viewers. A queued entry is delivered only while its executable price, spread, calendar, session and expiry checks still pass. Delivery retries transient failures up to four attempts while valid. The saved lifecycle event and its alert share one database transaction and carry a stable deduplication key. The device uses the same key as its notification tag because an interrupted provider acknowledgement can be ambiguous. HTTPS and hosting costs are separate from paid API fees.

[Caddy HTTPS setup](https://caddyserver.com/docs/automatic-https) · [Web Push subscription requirements](https://developer.mozilla.org/en-US/docs/Web/API/PushManager/subscribe)

### Ryaze managed Node deployment

When Ryaze runs the public Node app and the Windows PC runs FastAPI and MT5, deploy this repository as a managed Node app with entry file `server.js`. That app builds the static dashboard and relays the four dashboard API routes. Generate the relay identity on Windows:

```powershell
.\.venv\Scripts\python.exe -m goldsignal.relay ryaze-relay.pem
```

Set `RELAY_PUBLIC_KEY` on Ryaze to the printed value. Keep the PEM on Windows. With the worker and FastAPI already running, start the outbound relay:

```powershell
.\.venv\Scripts\python.exe -m goldsignal.relay ryaze-relay.pem --url https://goldsignal.ryaze.my.id
```

Use the deployed hostname if it differs. Schedule the relay beside the Windows API and worker if it should reconnect after login or restart. Ryaze serves the dashboard while Windows is offline. Live API calls recover when the relay reconnects. Windows FastAPI listens on loopback and needs no inbound port.

### Admin access and Gemini

Run `.\.venv\Scripts\python.exe -m goldsignal.access` once on Windows to configure the admin email, password hash and credential encryption key in `.env`. Restart the API and worker, and restart the relay after changing which API routes it serves. Live mode requires sign-in. The default local demo stays open until you configure admin access.

Sign in at `/admin`. Create a separate access key for each viewer and share it privately. Viewers enter their key at `/`. Revoke a key to end its sessions and remove its push subscription. The same key can sign in again until revoked.

Paste a Google AI Studio key into Gemini review and enable it. The Windows backend encrypts the key and uses it for the shared worker. The worker sends a compact price and trend summary to `GEMINI_MODEL` only after the Python setup gates pass. No account fields are sent to Google. It caps requests at six per UTC day, caps output at 96 tokens with minimal thinking on the default Flash-Lite model, and caches a review per candidate. An unavailable, ambiguous or invalid review stays on WAIT. Disabling Gemini restores the configured rules or Ollama mode. An AI Studio key from a free-tier project is needed to avoid paid usage. To switch chat and signal review to Gemini 3.1 Pro Preview, use a paid API project, set `GEMINI_MODEL=gemini-3.1-pro-preview` in the Windows `.env`, and restart the API and worker. Pro reviews use low thinking with a 512-token response cap. The six-request daily cap remains shared across automated reviews. [Google’s Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)

Choose M1, M5, M15, M30, H1, or H4 on the chart. Live views use candles and bid/ask from MT5 and update roughly once a second. The strategy stays on M15 and checks M30 and H1 trends. RSI(8) uses Wilder smoothing. The pattern comparison scans up to 1,000 past closed M15 bars and summarizes the next-four-candle moves of five nearest historical matches based on RSI, recent return and candle shape. Those moves are historical evidence. The worker sends shared entry alerts to opted-in viewers and sends subsequent simulated TP/SL alerts as quotes reach the tracked levels.
