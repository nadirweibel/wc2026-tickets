"""
Ticketmaster Discovery API.

Uses hardcoded event IDs for all Swiss games and SoFi WC matches —
much more reliable than keyword search, and will catch prices the
moment resale listings appear on TM.
"""

import time
import requests
from typing import Dict, List

_BASE = "https://app.ticketmaster.com/discovery/v2"

# All Switzerland group-stage games
_SWISS_IDS = [
    "Z7r9jZ1A7433K",   # Match 8  — Qatar vs Switzerland       Jun 13 (Levi's)
    "Z7r9jZ1A743f3",   # Match 26 — Switzerland vs Bosnia       Jun 18 (SoFi)
    "Z7r9jZ1A743fg",   # Match 51 — Switzerland vs Canada       Jun 24
]

# SoFi Stadium WC matches (venue ID KovZ917ACh0), all known games
_SOFI_IDS = [
    "Z7r9jZ1A74333",   # Match 4  — USA vs Paraguay             Jun 12
    "Z7r9jZ1A743fe",   # Match 15 — Iran vs New Zealand         Jun 15
    "Z7r9jZ1A743f3",   # Match 26 — Switzerland vs Bosnia       Jun 18  (also Swiss)
    "Z7r9jZ1A743fN",   # Match 39 — Belgium vs Iran             Jun 21
    "Z7r9jZ1A7434Z",   # Match 59 — USA vs Turkey               Jun 25
    "Z7r9jZ1A7434f",   # Match 73 — Round of 32                 Jun 28
    "Z7r9jZ1A7434N",   # Match 84 — Round of 32                 Jul 2
    "Z7r9jZ1A7434U",   # Quarterfinal                           Jul 10
]

_ALL_IDS = list(dict.fromkeys(_SWISS_IDS + _SOFI_IDS))   # deduped, order preserved


def search(query: str, api_key: str) -> List[Dict]:
    # query arg ignored — we poll specific event IDs directly
    if not query.startswith("World Cup Switzerland"):
        return []   # only run once per checker cycle

    results: List[Dict] = []
    for event_id in _ALL_IDS:
        results.extend(_fetch_event(event_id, api_key))
        time.sleep(0.35)   # stay under TM free-tier rate limit
    return results


def _fetch_event(event_id: str, api_key: str) -> List[Dict]:
    try:
        r = requests.get(
            f"{_BASE}/events/{event_id}.json",
            params={"apikey": api_key},
            timeout=15,
        )
        r.raise_for_status()
        ev = r.json()

        name = ev.get("name", "")
        url  = ev.get("url", "")
        date = ev.get("dates", {}).get("start", {}).get("localDate", "")
        venue_list = ev.get("_embedded", {}).get("venues", [{}])
        venue = venue_list[0].get("name", "") if venue_list else ""

        price_ranges = ev.get("priceRanges", [])
        if not price_ranges:
            # Event exists but no listings yet — record it with null price
            # so the dashboard shows it's being monitored
            return [{
                "platform": "Ticketmaster",
                "event": name,
                "date": date,
                "venue": venue,
                "url": url,
                "min_price": None,
                "max_price": None,
                "currency": "USD",
            }]

        return [{
            "platform": "Ticketmaster",
            "event": name,
            "date": date,
            "venue": venue,
            "url": url,
            "min_price": pr.get("min"),
            "max_price": pr.get("max"),
            "currency": pr.get("currency", "USD"),
        } for pr in price_ranges]

    except Exception as e:
        print(f"[Ticketmaster] Error fetching {event_id}: {e}")
        return []
