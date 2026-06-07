"""
SeatGeek public API.

Uses performer-slug search for Swiss games and a venue search for SoFi,
which is far more targeted than keyword search.
"""

import requests
from typing import Dict, List

_BASE = "https://api.seatgeek.com/2"

# SeatGeek performer slug for Switzerland national team
_SWISS_SLUG = "switzerland-national-football-team"

# SeatGeek venue ID for SoFi Stadium (from their API)
_SOFI_VENUE_ID = "130741"


def search(query: str, client_id: str) -> List[Dict]:
    if not query.startswith("World Cup Switzerland"):
        return []   # run once per cycle

    results: List[Dict] = []

    # Swiss games via performer slug
    results.extend(_fetch(
        f"{_BASE}/events",
        {"performers.slug": _SWISS_SLUG, "per_page": 20, "sort": "datetime_local.asc"},
        client_id,
        "Swiss games",
    ))

    # SoFi games via venue
    results.extend(_fetch(
        f"{_BASE}/events",
        {"venue.id": _SOFI_VENUE_ID, "q": "World Cup", "per_page": 20, "sort": "datetime_local.asc"},
        client_id,
        "SoFi games",
    ))

    # Dedupe by event id
    seen: set = set()
    unique = []
    for r in results:
        eid = r.get("_sg_event_id")
        if eid and eid in seen:
            continue
        if eid:
            seen.add(eid)
        unique.append(r)

    return unique


def _fetch(url: str, extra_params: dict, client_id: str, label: str) -> List[Dict]:
    results: List[Dict] = []
    params = {"client_id": client_id, **extra_params}
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()

        for ev in data.get("events", []):
            if not _is_wc(ev.get("title", "")):
                continue

            stats = ev.get("stats", {})
            venue = ev.get("venue", {})
            min_price = stats.get("lowest_price")

            results.append({
                "platform": "SeatGeek",
                "event": ev.get("title", ""),
                "date": ev.get("datetime_local", ""),
                "venue": venue.get("name", "") if isinstance(venue, dict) else "",
                "url": ev.get("url", ""),
                "min_price": float(min_price) if min_price is not None else None,
                "max_price": stats.get("highest_price"),
                "median_price": stats.get("median_price"),
                "listing_count": stats.get("listing_count"),
                "currency": "USD",
                "_sg_event_id": str(ev.get("id", "")),
            })
    except Exception as e:
        print(f"[SeatGeek] Error ({label}): {e}")
    return results


def _is_wc(title: str) -> bool:
    t = title.lower()
    return "world cup" in t or "fifa" in t
