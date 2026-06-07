"""Ticketmaster Discovery API — free tier, sign up at developer.ticketmaster.com."""

import requests
from typing import List, Dict


def search(query: str, api_key: str) -> List[Dict]:
    results: List[Dict] = []
    base = "https://app.ticketmaster.com/discovery/v2/events.json"

    params = {
        "apikey": api_key,
        "keyword": query,
        "size": 50,
        "sort": "date,asc",
        "countryCode": "US",
    }

    try:
        r = requests.get(base, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        events = data.get("_embedded", {}).get("events", [])

        for ev in events:
            if not _is_wc(ev.get("name", "")):
                continue
            url = ev.get("url", "")
            date = ev.get("dates", {}).get("start", {}).get("localDate", "")
            venue_list = ev.get("_embedded", {}).get("venues", [{}])
            venue = venue_list[0].get("name", "") if venue_list else ""

            for pr in ev.get("priceRanges", []):
                results.append({
                    "platform": "Ticketmaster",
                    "event": ev["name"],
                    "date": date,
                    "venue": venue,
                    "url": url,
                    "min_price": pr.get("min"),
                    "max_price": pr.get("max"),
                    "currency": pr.get("currency", "USD"),
                })
    except Exception as e:
        print(f"[Ticketmaster] Error for '{query}': {e}")

    return results


def _is_wc(name: str) -> bool:
    n = name.lower()
    return "world cup" in n or "fifa" in n
