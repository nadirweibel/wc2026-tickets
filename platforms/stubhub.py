"""
StubHub scraper — uses the FIFA WC grouping page JSON-LD.

The grouping page (world-cup-tickets/grouping/45410) returns schema.org
SportsEvent JSON-LD with lowPrice for every event on sale. We paginate
through up to 10 pages and filter for Switzerland or SoFi Stadium events.
Works from a residential IP; blocked on GitHub Actions (Akamai 202).
"""

import json
import time
import requests
from bs4 import BeautifulSoup
from typing import Dict, List

_GROUPING_URL = "https://www.stubhub.com/world-cup-tickets/grouping/45410/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}
_MAX_PAGES = 10


def search(query: str) -> List[Dict]:
    if not query.startswith("World Cup Switzerland"):
        return []   # run once per cycle

    results: List[Dict] = []
    seen: set = set()

    for page in range(1, _MAX_PAGES + 1):
        page_events = _fetch_page(page)
        if not page_events:
            break

        new_on_page = 0
        for ev in page_events:
            name = ev["name"]
            if "parking" in name.lower():
                continue
            if not _is_target(name, ev["venue"]):
                continue
            key = f"{name}|{ev['date'][:10]}"
            if key in seen:
                continue
            seen.add(key)
            new_on_page += 1
            results.append({
                "platform": "StubHub",
                "event": name,
                "date": ev["date"],
                "venue": ev["venue"],
                "url": ev["url"],
                "min_price": ev["price"],
                "currency": "USD",
            })

        time.sleep(0.5)

    return results


def _fetch_page(page: int) -> List[Dict]:
    url = f"{_GROUPING_URL}?page={page}"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=20, allow_redirects=True)
        if r.status_code != 200:
            print(f"[StubHub] HTTP {r.status_code} page {page}")
            return []

        soup = BeautifulSoup(r.text, "lxml")
        events: List[Dict] = []

        for tag in soup.find_all("script", type="application/ld+json"):
            if not tag.string:
                continue
            try:
                ld = json.loads(tag.string)
                items = ld.get("@graph", [ld] if isinstance(ld, dict) else ld)
                for item in items:
                    if item.get("@type") not in ("SportsEvent", "Event"):
                        continue
                    offers = item.get("offers") or {}
                    low = offers.get("lowPrice") or offers.get("price")
                    if low is None:
                        continue
                    loc = item.get("location") or {}
                    venue = loc.get("name", "") if isinstance(loc, dict) else ""
                    events.append({
                        "name": item.get("name", ""),
                        "date": item.get("startDate", ""),
                        "venue": venue,
                        "url": item.get("url", ""),
                        "price": float(low),
                    })
            except Exception as e:
                print(f"[StubHub] JSON-LD parse error page {page}: {e}")

        return events
    except Exception as e:
        print(f"[StubHub] Request error page {page}: {e}")
        return []


def _is_target(name: str, venue: str) -> bool:
    n, v = name.lower(), venue.lower()
    return (
        "switzerland" in n or "swiss" in n or
        "sofi" in v or "sofi" in n or "inglewood" in v
    )
