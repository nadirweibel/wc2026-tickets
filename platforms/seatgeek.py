"""SeatGeek public API — free, sign up at seatgeek.com/account/develop."""

import requests
from typing import List, Dict


def search(query: str, client_id: str) -> List[Dict]:
    results: List[Dict] = []
    base = "https://api.seatgeek.com/2/events"

    params = {
        "client_id": client_id,
        "q": query,
        "per_page": 50,
        "sort": "datetime_local.asc",
    }

    try:
        r = requests.get(base, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()

        for ev in data.get("events", []):
            if not _is_wc(ev.get("title", "")):
                continue

            stats = ev.get("stats", {})
            min_price = stats.get("lowest_price")
            if min_price is None:
                continue

            venue = ev.get("venue", {})
            results.append({
                "platform": "SeatGeek",
                "event": ev.get("title", ""),
                "date": ev.get("datetime_local", ""),
                "venue": venue.get("name", "") if isinstance(venue, dict) else "",
                "url": ev.get("url", ""),
                "min_price": float(min_price),
                "max_price": stats.get("highest_price"),
                "median_price": stats.get("median_price"),
                "listing_count": stats.get("listing_count"),
                "currency": "USD",
            })
    except Exception as e:
        print(f"[SeatGeek] Error for '{query}': {e}")

    return results


def _is_wc(title: str) -> bool:
    t = title.lower()
    return "world cup" in t or "fifa" in t
