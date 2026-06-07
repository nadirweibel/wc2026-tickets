"""
Vivid Seats — internal hermes productions API.

Returns minAipPrice (all-in, fees included), listingCount, ticketCount, and
the webPath for proper event URLs. Uses a session warmup to pass Akamai.
"""

import time
import requests
from typing import Dict, List

_BASE = "https://www.vividseats.com/hermes/api/v1/productions"

_SESSION_HEADERS = {
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
    "Cache-Control": "max-age=0",
}

_QUERIES = [
    "switzerland world cup",
    "sofi stadium world cup",
    "los angeles world cup 2026",
]


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_SESSION_HEADERS)
    try:
        s.get("https://www.vividseats.com", timeout=15, allow_redirects=True)
        time.sleep(1.0)
    except Exception:
        pass
    s.headers.update({
        "Accept": "application/json",
        "Referer": "https://www.vividseats.com/",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    })
    return s


def search(query: str) -> List[Dict]:
    if not query.startswith("World Cup Switzerland"):
        return []

    results: List[Dict] = []
    seen: set = set()
    session = _make_session()

    for q in _QUERIES:
        try:
            r = session.get(_BASE, params={"query": q}, timeout=15)
            if "text/html" in r.headers.get("content-type", ""):
                print(f"[VividSeats] Bot challenge on '{q}' — skipping")
                continue
            r.raise_for_status()
            for item in r.json().get("items", []):
                name = item.get("name", "")
                if not name or "parking" in name.lower():
                    continue
                venue_obj = item.get("venue") or {}
                venue = venue_obj.get("name", "") if isinstance(venue_obj, dict) else ""
                if not _is_target(name, venue):
                    continue

                vid = str(item.get("id", ""))
                if vid in seen:
                    continue
                seen.add(vid)

                # Prefer all-in price (includes service fees); fall back to base price
                aip = item.get("minAipPrice")
                base = item.get("minPrice")
                min_price = aip if aip is not None else base

                web_path = item.get("webPath") or item.get("organicUrl") or ""
                url = (
                    f"https://www.vividseats.com{web_path}"
                    if web_path.startswith("/")
                    else f"https://www.vividseats.com/tickets/production/{vid}"
                )
                # Deep-link with qty=2 so the page opens pre-filtered to pairs
                url_2 = url + ("&" if "?" in url else "?") + "qty=2"

                results.append({
                    "platform": "VividSeats",
                    "event": name,
                    "date": (item.get("localDate") or "")[:19],
                    "venue": venue,
                    "url": url,
                    "url_qty2": url_2,
                    "min_price": float(min_price) if min_price is not None else None,
                    "base_price": float(base) if base is not None else None,
                    "max_price": item.get("maxPrice"),
                    "currency": "USD",
                    "listing_count": item.get("listingCount"),
                    "ticket_count": item.get("ticketCount"),
                    "price_note": "all-in" if aip is not None else "excl. fees",
                    "_vs_id": vid,
                })
        except Exception as e:
            print(f"[VividSeats] Error ({q}): {e}")
        time.sleep(0.5)

    return results


def _is_target(name: str, venue: str) -> bool:
    n, v = name.lower(), venue.lower()
    return (
        "switzerland" in n or "swiss" in n or
        "sofi" in v or "sofi" in n or "inglewood" in v
    )
