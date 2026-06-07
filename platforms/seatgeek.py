"""
SeatGeek — AppleScript + Chrome scraper (macOS only).

SeatGeek uses DataDome bot protection that blocks all automated requests
(curl, Playwright+Chromium, Playwright+system Chrome, profile copies, etc.)
even from residential IPs.  The only reliable path is to drive the user's
real Chrome via AppleScript, which inherits the existing DataDome session.

Key design: a NEW off-screen Chrome window is opened for each event
(-3000,-3000 so it is never visible) and closed immediately after scraping.
Chrome never steals focus from whatever app you are using.

Behaviour by environment
  • macOS + Chrome running  → scrapes all events invisibly in the background
  • macOS + Chrome absent   → null-price entries (last prices preserved by checker.py)
  • Linux / GitHub Actions  → null-price entries (last prices preserved by checker.py)

JS extraction is written to /tmp/sg_extract.js to avoid AppleScript
string-escaping issues with embedded quotes in the script literal.
"""

import json
import subprocess
import sys
from typing import Dict, List, Optional

# ── Events ─────────────────────────────────────────────────────────────────────
# Event names MUST match what is already stored in prices.json (they form the
# history key).  Dates use the same ISO format as the original SeatGeek API.
_EVENTS: List[Dict] = [
    {
        "name":  "Switzerland vs Qatar - World Cup - Match 8 (Group B)",
        "date":  "2026-06-13T12:00:00",
        "venue": "Levi's Stadium",
        "url":   "https://seatgeek.com/fifa-world-cup-tickets/international-soccer/2026-06-13-12-pm/17171556",
        "_sg_event_id": "17171556",
    },
    {
        "name":  "Switzerland vs Bosnia & Herzegovina - World Cup - Match 26 (Group B)",
        "date":  "2026-06-18T12:00:00",
        "venue": "SoFi Stadium",
        "url":   "https://seatgeek.com/fifa-world-cup-tickets/international-soccer/2026-06-18-12-pm/17176205",
        "_sg_event_id": "17176205",
    },
    {
        "name":  "Canada vs Switzerland - World Cup - Match 51 (Group B)",
        "date":  "2026-06-24T12:00:00",
        "venue": "BC Place Stadium",
        "url":   "https://seatgeek.com/fifa-world-cup-tickets/international-soccer/2026-06-24-12-pm/17249641",
        "_sg_event_id": "17249641",
    },
]

# quantity=2 gives best per-ticket price and most listings.
# sort=price ensures cheapest seats are on the first page (JS takes Math.min anyway).
_QTY      = "2"
_PAGE_WAIT = 14   # seconds to wait after navigation for React to render prices

# Off-screen position: window is opened here so it is never visible on-screen.
_OFF_X1, _OFF_Y1, _OFF_X2, _OFF_Y2 = -3000, -3000, -2200, -2200

# JS written to a temp file — avoids AppleScript string-escaping nightmares.
_JS_EXTRACT = r"""
(function(){
  var prices = [];
  document.querySelectorAll('[class*="price"],[class*="Price"]').forEach(function(el){
    var m = el.innerText.match(/\$(\d{2,4})/);
    if (m) prices.push(parseInt(m[1]));
  });
  var good = prices.filter(function(p){ return p >= 50 && p <= 9999; });
  var cnt  = document.body.innerText.match(/(\d[\d,]+)\s+listings?/i);
  return JSON.stringify({
    title:    document.title.slice(0, 80),
    min:      good.length ? Math.min.apply(null, good) : null,
    listings: cnt ? cnt[1] : null
  });
})()
"""

_JS_FILE = "/tmp/sg_extract.js"


# ── Public entry point ─────────────────────────────────────────────────────────

def search(query: str, client_id: str = "") -> List[Dict]:
    """Called once per checker cycle; client_id kept for interface compatibility."""
    if not query.startswith("World Cup Switzerland"):
        return []

    if not _chrome_available():
        print("[SeatGeek] Chrome not available — keeping last prices")
        return _null_entries()

    try:
        with open(_JS_FILE, "w") as fh:
            fh.write(_JS_EXTRACT)
    except OSError as e:
        print(f"[SeatGeek] Could not write JS temp file: {e}")
        return _null_entries()

    return [_scrape_event(ev) for ev in _EVENTS]


# ── Internal helpers ───────────────────────────────────────────────────────────

def _chrome_available() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        r = subprocess.run(
            ["osascript", "-e",
             'tell application "Google Chrome" to return name'],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0 and "Chrome" in r.stdout
    except Exception:
        return False


def _scrape_event(ev: dict) -> Dict:
    """Open one invisible off-screen Chrome window, wait, extract price, close."""
    url = f"{ev['url']}?quantity={_QTY}&sort=price"

    # AppleScript:
    #  1. Remember which app is frontmost so we can restore focus afterwards.
    #  2. Open a new Chrome window positioned off-screen (-3000,-3000) — invisible.
    #  3. Navigate, wait for React to render, extract prices via JS.
    #  4. Close the window.
    #  5. Restore focus to the original app so Chrome never steals it.
    script = (
        'set prevApp to name of (info for (path to frontmost application))\n'
        'tell application "Google Chrome"\n'
        f'    set jsCode to do shell script "cat {_JS_FILE}"\n'
        f'    set scrapeWin to make new window\n'
        f'    set bounds of scrapeWin to {{{_OFF_X1}, {_OFF_Y1}, {_OFF_X2}, {_OFF_Y2}}}\n'
        f'    set URL of active tab of scrapeWin to "{url}"\n'
        f'    delay {_PAGE_WAIT}\n'
        '    set pgData to execute (active tab of scrapeWin) javascript jsCode\n'
        '    close scrapeWin\n'
        'end tell\n'
        'activate application prevApp\n'
        'return pgData'
    )
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True,
            timeout=_PAGE_WAIT + 25,
        )
        if r.returncode != 0:
            print(f"[SeatGeek] AppleScript error for {ev['name'][:45]}: "
                  f"{r.stderr.strip()[:80]}")
            return _null_row(ev)

        data = json.loads(r.stdout.strip())
        min_price  = data.get("min")
        raw_count  = data.get("listings")
        listing_count: Optional[int] = None
        if raw_count:
            try:
                listing_count = int(str(raw_count).replace(",", ""))
            except ValueError:
                pass

        if min_price:
            print(f"[SeatGeek] {ev['name'][:50]:50s} "
                  f"${min_price:.0f} ({listing_count} listings)")
        else:
            print(f"[SeatGeek] {ev['name'][:50]:50s} no data "
                  f"(title: {data.get('title', '')[:40]})")

        return {
            "platform":      "SeatGeek",
            "event":         ev["name"],
            "date":          ev["date"],
            "venue":         ev["venue"],
            "url":           ev["url"],
            "_sg_event_id":  ev.get("_sg_event_id"),
            "min_price":     float(min_price) if min_price else None,
            "price_note":    "all-in" if min_price else None,
            "listing_count": listing_count,
            "currency":      "USD",
        }

    except subprocess.TimeoutExpired:
        print(f"[SeatGeek] Timeout for {ev['name'][:45]}")
        return _null_row(ev)
    except json.JSONDecodeError as exc:
        print(f"[SeatGeek] JSON error for {ev['name'][:45]}: {exc}")
        return _null_row(ev)
    except Exception as exc:
        print(f"[SeatGeek] Error for {ev['name'][:45]}: {exc}")
        return _null_row(ev)


def _null_row(ev: dict) -> Dict:
    return {
        "platform":      "SeatGeek",
        "event":         ev["name"],
        "date":          ev["date"],
        "venue":         ev["venue"],
        "url":           ev["url"],
        "_sg_event_id":  ev.get("_sg_event_id"),
        "min_price":     None,
        "currency":      "USD",
    }


def _null_entries() -> List[Dict]:
    return [_null_row(ev) for ev in _EVENTS]
