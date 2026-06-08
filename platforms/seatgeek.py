"""
SeatGeek scraper — BrightData Web Unlocker API (primary) with macOS Chrome fallback.

SeatGeek uses DataDome bot protection that blocks all automated requests from
datacenter IPs (GitHub Actions), residential proxies without proper cookies, and
headless browsers.  Two bypass paths are implemented in priority order:

  1. BrightData Web Unlocker REST API (env: BD_API_KEY + BD_ZONE)
       Works from GitHub Actions.  Costs ~$1 / 1 000 requests.
       Set both vars as GitHub Actions secrets to enable.

  2. macOS off-screen Chrome via AppleScript (env: no extra vars, darwin only)
       Drives the user's real Chrome (inheriting its DataDome session cookies).
       Opens an invisible window at (-3000, -3000) so Chrome never steals focus.
       Falls back gracefully when Chrome is not running.

  3. Null entries — checker.py preserves last known prices automatically.
"""

import json
import os
import re
import subprocess
import sys
import time
from typing import Dict, List, Optional

import requests

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

# quantity=2 gives the most listings and best per-ticket price.
# sort=price ensures cheapest seats appear first.
_QTY = "2"

# ── BrightData config ───────────────────────────────────────────────────────────
# Set BD_API_KEY and BD_ZONE as GitHub Actions secrets (and in .env for local runs).
# BD_ZONE is the zone name shown in your BrightData dashboard (e.g. "web_unlocker1").
_BD_API_KEY = os.environ.get("BD_API_KEY", "")
_BD_ZONE    = os.environ.get("BD_ZONE", "")
_BD_URL     = "https://api.brightdata.com/request"

# ── macOS Chrome config ─────────────────────────────────────────────────────────
_PAGE_WAIT = 14           # seconds to wait for React to render
_OFF_X1, _OFF_Y1, _OFF_X2, _OFF_Y2 = -3000, -3000, -2200, -2200

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

    # Priority 1: BrightData (works from GitHub Actions)
    if _BD_API_KEY and _BD_ZONE:
        return [_scrape_brightdata(ev) for ev in _EVENTS]

    # Priority 2: macOS Chrome (local only)
    if _chrome_available():
        try:
            with open(_JS_FILE, "w") as fh:
                fh.write(_JS_EXTRACT)
        except OSError as e:
            print(f"[SeatGeek] Could not write JS temp file: {e}")
            return _null_entries()
        return [_scrape_chrome(ev) for ev in _EVENTS]

    # Priority 3: null — last prices preserved by checker.py
    print("[SeatGeek] No scraper available (set BD_API_KEY+BD_ZONE or run on macOS with Chrome)")
    return _null_entries()


# ── BrightData path ─────────────────────────────────────────────────────────────

def _scrape_brightdata(ev: dict) -> Dict:
    """Fetch one SeatGeek event page via BrightData Web Unlocker REST API."""
    url = f"{ev['url']}?quantity={_QTY}&sort=price"
    try:
        resp = requests.post(
            _BD_URL,
            headers={
                "Authorization": f"Bearer {_BD_API_KEY}",
                "Content-Type":  "application/json",
            },
            json={
                "url":    url,
                "zone":   _BD_ZONE,
                "format": "raw",
            },
            timeout=90,
        )
        if resp.status_code != 200:
            print(f"[SeatGeek/BD] HTTP {resp.status_code} for {ev['name'][:45]}: {resp.text[:120]}")
            return _null_row(ev)

        html = resp.text
        return _parse_html(ev, html)

    except requests.RequestException as exc:
        print(f"[SeatGeek/BD] Request error for {ev['name'][:45]}: {exc}")
        return _null_row(ev)


def _parse_html(ev: dict, html: str) -> Dict:
    """Extract min price and listing count from SeatGeek page HTML."""
    min_price: Optional[float] = None
    listing_count: Optional[int] = None
    all_in = False

    # --- Primary: __NEXT_DATA__ JSON (most reliable, no DOM parsing) ---
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        try:
            nd = json.loads(m.group(1))
            sg_event = nd["props"]["pageProps"]["event"]
            stats = sg_event.get("stats", {})
            lp = stats.get("lowest_price")
            if lp is not None and isinstance(lp, (int, float)) and lp > 0:
                min_price = float(lp)
                listing_count = stats.get("listing_count") or stats.get("visible_listing_count")
                # SeatGeek shows all-in prices when these flags are True
                all_in = bool(
                    sg_event.get("all_in_price_on_event_page") or
                    sg_event.get("all_in_price_before_checkout")
                )
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    # --- Fallback: regex price extraction from rendered HTML ---
    if min_price is None:
        all_prices = [int(x) for x in re.findall(r'\$(\d{2,4})', html) if 50 <= int(x) <= 9999]
        if all_prices:
            min_price = float(min(all_prices))

    # --- Listing count fallback ---
    if listing_count is None:
        cnt = re.search(r'([\d,]+)\s+listings?', html, re.IGNORECASE)
        if cnt:
            try:
                listing_count = int(cnt.group(1).replace(",", ""))
            except ValueError:
                pass

    # --- True DataDome block: no __NEXT_DATA__ AND no prices ---
    if min_price is None and "__NEXT_DATA__" not in html:
        print(f"[SeatGeek/BD] Blocked (no page data) for {ev['name'][:45]}")
        return _null_row(ev)

    if min_price:
        note = "all-in" if all_in else None
        print(f"[SeatGeek/BD] {ev['name'][:50]:50s} ${min_price:.0f} "
              f"({'all-in, ' if all_in else ''}{listing_count} listings)")
    else:
        print(f"[SeatGeek/BD] {ev['name'][:50]:50s} no price found in response")

    return {
        "platform":      "SeatGeek",
        "event":         ev["name"],
        "date":          ev["date"],
        "venue":         ev["venue"],
        "url":           ev["url"],
        "_sg_event_id":  ev.get("_sg_event_id"),
        "min_price":     min_price,
        "price_note":    "all-in" if all_in else None,
        "listing_count": listing_count,
        "currency":      "USD",
    }


# ── macOS Chrome path ────────────────────────────────────────────────────────────

def _chrome_available() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        r = subprocess.run(
            ["osascript", "-e", 'tell application "Google Chrome" to return name'],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0 and "Chrome" in r.stdout
    except Exception:
        return False


def _scrape_chrome(ev: dict) -> Dict:
    """Open one invisible off-screen Chrome window, wait, extract price, close."""
    url = f"{ev['url']}?quantity={_QTY}&sort=price"
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
            print(f"[SeatGeek/Chrome] AppleScript error for {ev['name'][:45]}: "
                  f"{r.stderr.strip()[:80]}")
            return _null_row(ev)

        data = json.loads(r.stdout.strip())
        min_price     = data.get("min")
        raw_count     = data.get("listings")
        listing_count: Optional[int] = None
        if raw_count:
            try:
                listing_count = int(str(raw_count).replace(",", ""))
            except ValueError:
                pass

        if min_price:
            print(f"[SeatGeek/Chrome] {ev['name'][:50]:50s} "
                  f"${min_price:.0f} ({listing_count} listings)")
        else:
            print(f"[SeatGeek/Chrome] {ev['name'][:50]:50s} no data "
                  f"(title: {data.get('title', '')[:40]})")

        return {
            "platform":      "SeatGeek",
            "event":         ev["name"],
            "date":          ev["date"],
            "venue":         ev["venue"],
            "url":           ev["url"],
            "_sg_event_id":  ev.get("_sg_event_id"),
            "min_price":     float(min_price) if min_price else None,
            "price_note":    None,
            "listing_count": listing_count,
            "currency":      "USD",
        }

    except subprocess.TimeoutExpired:
        print(f"[SeatGeek/Chrome] Timeout for {ev['name'][:45]}")
        return _null_row(ev)
    except json.JSONDecodeError as exc:
        print(f"[SeatGeek/Chrome] JSON error for {ev['name'][:45]}: {exc}")
        return _null_row(ev)
    except Exception as exc:
        print(f"[SeatGeek/Chrome] Error for {ev['name'][:45]}: {exc}")
        return _null_row(ev)


# ── Helpers ─────────────────────────────────────────────────────────────────────

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
