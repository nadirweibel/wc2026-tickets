# WC2026 Ticket Price Checker

**Repo:** https://github.com/nadirweibel/wc2026-tickets  
**Dashboard:** https://nadirweibel.github.io/wc2026-tickets/


Monitors ticket prices every hour for:
- **Switzerland national team** games (any venue)
- **All games at SoFi Stadium** (Inglewood / Los Angeles)

Checks Ticketmaster, SeatGeek, StubHub, Vivid Seats, and FIFA Official.
Emails you when a listing hits a new price low *and* is under your price ceiling.

---

## Setup (one-time, ~15 minutes)

### 1. Create a private GitHub repo

```
gh repo create wc2026-tickets --private --source . --push
```

Or create it on github.com and `git push`.

### 2. Get free API keys

| Platform | Where to sign up | What to get |
|---|---|---|
| **Ticketmaster** | developer.ticketmaster.com → "Get Your API Key" | `API Key` (Consumer Key) |
| **SeatGeek** | seatgeek.com/account/develop | `Client ID` |
| **Reddit** | reddit.com/prefs/apps → "create another app" → type **script** | `client_id` (under app name) + `client_secret` |

StubHub, Vivid Seats, and FIFA Official are scraped (no key needed).
Reddit credentials are free — no approval process; "script" app type is for personal use.

### 3. Create a Gmail App Password

You need a Gmail account with 2-Step Verification enabled.

1. Go to **myaccount.google.com → Security → App passwords**
2. Create a new app password (name it "WC2026 checker")
3. Copy the 16-character password

### 4. Add GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**. Add these:

| Secret name | Value |
|---|---|
| `TM_API_KEY` | Ticketmaster API key |
| `SG_CLIENT_ID` | SeatGeek client ID |
| `GMAIL_USER` | Your Gmail address (e.g. `you@gmail.com`) |
| `GMAIL_APP_PASSWORD` | The 16-character App Password from step 3 |
| `ALERT_EMAIL` | Where to send alerts (can be same as Gmail or different) |
| `PRICE_CEILING` | Max price to alert on, e.g. `400` (default: 500) |
| `REDDIT_CLIENT_ID` | From reddit.com/prefs/apps (under the app name) |
| `REDDIT_CLIENT_SECRET` | "secret" field on the same app page |

### 5. Enable write permissions for Actions

Repo → **Settings → Actions → General → Workflow permissions** → select **"Read and write permissions"**.

### 6. Run it manually first

Go to **Actions → WC2026 Ticket Price Check → Run workflow**.
Check the logs. If Ticketmaster or SeatGeek keys are set, you should see listings.
After the run, `prices.json` and `prices_log.csv` will be committed automatically.

---

## How it works

```
checker.py   ← runs every hour via GitHub Actions cron
│
├── platforms/ticketmaster.py  ← Discovery API (most reliable)
├── platforms/seatgeek.py      ← SeatGeek public API
├── platforms/stubhub.py       ← HTML scraper (best effort)
├── platforms/vividseats.py    ← HTML scraper (best effort)
└── platforms/fifa.py          ← FIFA official (best effort; often JS-blocked)

notify.py    ← Gmail SMTP alert
prices.json  ← running "price low" record, committed after each check
prices_log.csv ← full hourly history (open in Excel/Sheets)
```

**Alert logic:** email sent only when *both* conditions are true:
1. Price is lower than any previously seen price for that event+platform
2. Price is below your `PRICE_CEILING`

---

## Adjusting search targets

Edit `TARGET_SEARCHES` in `checker.py` to add or remove queries:

```python
TARGET_SEARCHES = [
    "Switzerland FIFA World Cup 2026",       # Swiss team games, any venue
    "FIFA World Cup 2026 SoFi Stadium",      # All Inglewood games
    "FIFA World Cup 2026 Inglewood",
    "FIFA World Cup 2026 Los Angeles",
    # Add more, e.g.:
    # "FIFA World Cup 2026 Final",
]
```

## Caveats

- **StubHub / Vivid Seats** may return no data if they update their anti-bot measures. The script fails gracefully and logs the error.
- **FIFA Official** prices are ballot/waitlist-based and rarely show up via scraping; the resale platforms are more useful for price discovery.
- **Ticketmaster + SeatGeek** are the two most reliable sources.
- Prices shown are the *lowest listed* ticket, before all-in fees (which add 20–40%).
- GitHub Actions cron has ~1–5 min jitter; not exactly on the hour.
