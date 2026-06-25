# WC2026 Ticket Price Checker — Claude Code Working Notes

Last updated: 2026-06-24.

## Project at a glance

Hourly price monitor for **Switzerland national team games** and **all SoFi Stadium (Inglewood)
games** at the 2026 FIFA World Cup. Checks multiple resale platforms, emails when a new price low
is found under a configurable ceiling, and shows everything on a live GitHub Pages dashboard.

**GitHub repo:** https://github.com/nadirweibel/wc2026-tickets  
**Dashboard:** https://nadirweibel.github.io/wc2026-tickets/  
**Local source:** `/Users/weibel2/Projects/wc2026-tickets/`

---

## File layout

```
checker.py              — main runner; called hourly by cron/Actions
notify.py               — Gmail SMTP alert builder
prices.json             — current price state (one entry per platform+event+section)
prices_log.csv          — append-only hourly log (full history)
index.html              — single-file dashboard (no build step; served by GitHub Pages)
run_local.sh            — launches checker.py from Mac + commits + pushes
install_local.sh        — one-time setup: writes .env, installs launchd agent
requirements.txt        — pip deps
.github/workflows/check.yml  — GitHub Actions hourly cron

platforms/
  availability.py       — Reddit post alive/dead checker (RSS-based)
  reddit.py             — Reddit search scraper
  ticketmaster.py       — Ticketmaster Discovery API
  seatgeek.py           — SeatGeek public API
  stubhub.py            — HTML scraper
  vividseats.py         — HTML scraper
  fifa.py               — FIFA official (best-effort, often JS-blocked)
```

---

## Key data structures

### `prices.json`

One JSON object where each key = `make_key(listing)`:

```
"{platform}|{event}|{date}|{section}"
```

For Reddit, `section` = the post_id (e.g. `1tzz2nw`).  
For ticketed platforms, `section` = section string (e.g. "Section 201").

Each value is a dict with:
- `platform`, `event`, `date`, `venue`, `url`
- `min_seen` — lowest price ever recorded for this listing
- `last_price` — price from the most recent run
- `last_checked` — ISO timestamp of last run
- `availability` — (Reddit only) `"sold"`, `"available"`, or `"uncertain"`
- `av_checked_at` — (Reddit only) ISO timestamp of last availability check
- `body` — (Reddit only) first 600 chars of post body
- `best_qty`, `listing_count`, `ticket_count`, `base_price`, `price_note` — optional extras

### Alert logic

Email sent only when:
1. `price < prev_min` (new all-time low for that listing)
2. `price < PRICE_CEILING` (env var, default 500)
3. `availability != "sold"` (suppresses alerts on dead Reddit posts)

---

## Platform notes

### Reddit (`platforms/reddit.py`)

Searches `r/WorldCup2026Tickets` and 7 other subs via Reddit's search RSS
(`/r/{sub}/search/.rss?q=...&restrict_sr=1&sort=new&t=month`).

Only runs on the `"World Cup Switzerland"` search query (the first in `TARGET_SEARCHES`)
to avoid duplicating work across all queries.

**RSS header quirks (learned the hard way):**
- URL must be `/comments/{post_id}/.rss` — adding the slug after the id causes 403.
- `Accept-Language` header triggers Reddit's bot block even with a valid UA.
- Working headers (in `_HEADERS`): UA + `Accept: application/rss+xml, application/xml, */*` only.
- `.json` API endpoint → always 403 from GitHub Actions IPs.

### Availability checker (`platforms/availability.py`)

Called for each Reddit post to determine if it's still live.

**How it works:**
1. Regex on title+body: obvious "sold"/"available" keywords → early return.
2. Fetch the individual post's RSS: `https://www.reddit.com/r/.../comments/{post_id}/.rss`
3. Parse Atom XML, extract first entry (post body), strip HTML tags via BeautifulSoup.
4. If body starts with `[deleted]` or `[removed]` → mark `"sold"`.
5. If any comment contains sold keywords → mark `"sold"`.
6. If `ANTHROPIC_API_KEY` set → ask Claude Haiku for a final verdict.
7. Fallback → `"uncertain"`.

**Recheck intervals** (`should_recheck`):
- `available` / `uncertain` → every 4 hours
- `sold` → every 24 hours (to catch cases where a deleted post re-listed)

**Known issue:** if `_fetch_post` returns `(None, [])` (network failure or Reddit rate-limit)
and no `ANTHROPIC_API_KEY` is set (local env), the function returns `"uncertain"` even for
previously-confirmed-deleted posts. This can cause local runs to flip `"sold"` → `"uncertain"`.
Fix: when fetch fails and existing status is `"sold"`, preserve it rather than re-evaluating.
Not yet implemented; low priority since GitHub Actions has the API key and pushes the canonical
`prices.json`.

---

## Dashboard (`index.html`)

Single HTML file, no build step. Fetches `prices.json` from the same GitHub Pages origin.

Key JS functions:
- `load()` — `fetch('prices.json?_='+Date.now())` (cache-busting), builds `allRows`
- `renderReddit(rows)` — filters: `r.platform.includes('reddit') && r.availability !== 'sold'`
- `renderGameCard(game, allRows)` — per-game card; passes `rows` (pre-sold-filtered for Reddit
  section via `renderReddit`) but an unfiltered `redditRows` into `renderPlatRow` for the
  platform-row section (this is intentional — Reddit posts don't appear in the platform table)
- `avBadge(row)` — renders `SOLD` / `LIVE` / `?` badge
- `dismiss(key)` — LocalStorage-based dismissal per listing

GitHub Pages serves this with `cache-control: max-age=600`. Hard refresh (Cmd+Shift+R) clears
the browser cache when the page doesn't reflect a recent push.

---

## Email alerts (`notify.py`)

Uses Gmail SMTP with an App Password. Sends HTML table with:
- Platform, event, date, venue, best price, ticket count, previous low, buy link
- Dashboard button in the header
- VividSeats / StubHub pre-fill qty=2 in buy URLs

---

## Local cron vs GitHub Actions

Two parallel runners update `prices.json`:

| | GitHub Actions | Local Mac (launchd) |
|---|---|---|
| Trigger | Hourly cron (`0 * * * *`) | Every 3600s via launchd |
| IP | GitHub datacenter | Residential (avoids Akamai/CloudFlare blocks) |
| Env vars | GitHub Secrets | `.env` file in project root |
| Commit msg | `"prices: {timestamp}"` | `"prices (local): {timestamp}"` |
| ANTHROPIC_API_KEY | Set → LLM availability check | Not set → falls back to "uncertain" |

StubHub, VividSeats, and Reddit all block GitHub Actions datacenter IPs, so the local runner
is the primary source for those platforms. GitHub Actions reliably gets Ticketmaster + SeatGeek.

**Merge conflict pattern:** Both runners commit to `prices.json` and `prices_log.csv` on
overlapping schedules. Conflicts are data-only; always resolve with `git checkout --theirs`
(take origin's version) when pulling from the local side, since Actions has fresher data for
TM/SG and may have more recent availability checks.

**As of 2026-06-24:** Local branch is 138 commits ahead of `origin/main`. Before migrating
to a new account/machine, push with:
```bash
cd /Users/weibel2/Projects/wc2026-tickets
git push
```
If there are conflicts, resolve them:
```bash
git fetch origin
git merge origin/main -m "Merge remote price updates"
# For data-file conflicts: git checkout --theirs prices.json prices_log.csv
git push
```

---

## GitHub Secrets (required)

| Secret | Purpose |
|---|---|
| `TM_API_KEY` | Ticketmaster Discovery API key |
| `SG_CLIENT_ID` | SeatGeek client ID |
| `GMAIL_USER` | Gmail sender address |
| `GMAIL_APP_PASSWORD` | Gmail App Password (16-char) |
| `ALERT_EMAIL` | Recipient address for price alerts |
| `PRICE_CEILING` | Max alert price (e.g. `300`) |
| `ANTHROPIC_API_KEY` | Claude Haiku for availability LLM fallback |

Repo settings → Actions → General → Workflow permissions → "Read and write permissions" required
so Actions can commit `prices.json` back.

---

## Known bugs fixed (history)

1. **`best_qty=None` bug** — `checker.py` wasn't persisting the `best_qty` field to `prices.json`
   because it wasn't in the `extras` whitelist tuple. Fixed: added `"best_qty"` to the tuple
   (checker.py ~line 159).

2. **Reddit deleted-post detection** — RSS fetch was failing due to:
   - URL slug before `/.rss` causing 403 (fixed: regex to strip slug)
   - `Accept-Language` header triggering Reddit bot block (fixed: removed it)
   - `_DELETED_RE` anchored with `$` failing to match because of `[link] [comments]` footer
     (fixed: removed the `$` anchor)

3. **Sold posts appearing on dashboard** — `renderReddit()` wasn't filtering `availability===sold`.
   Fixed in `index.html` line 662.

4. **Stale deleted posts** — deleted posts drop from Reddit search results so the main checker
   loop never re-evaluates them. Fixed: added a second pass in `checker.py` after the main loop
   that rechecks any Reddit entries not seen in current search results if `should_recheck` is true.

---

## Running locally

```bash
# One-time setup (installs launchd agent that runs every hour):
bash install_local.sh

# Run once manually:
bash run_local.sh

# Or just the Python:
source .env && python3 checker.py
```

Logs go to `local_run.log`.

---

## GitHub Pages setup

- Serves directly from `main` branch root (no `docs/` subfolder, no Actions deploy step).
- `index.html` + `prices.json` are in the repo root → served at `nadirweibel.github.io/wc2026-tickets/`.
- Enable in repo Settings → Pages → Source: "Deploy from a branch" → branch: `main` → folder: `/(root)`.
