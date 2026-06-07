"""
Vivid Seats scraper.

Same technique as StubHub: parse the Next.js __NEXT_DATA__ blob and
JSON-LD Event markup embedded in the search-result HTML.
"""

import json
import requests
from bs4 import BeautifulSoup
from typing import List, Dict

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_SEARCH_URL = "https://www.vividseats.com/search"


def search(query: str) -> List[Dict]:
    results: List[Dict] = []
    try:
        r = requests.get(
            _SEARCH_URL,
            params={"searchTerm": query},
            headers=_HEADERS,
            timeout=20,
            allow_redirects=True,
        )
        if r.status_code != 200:
            print(f"[VividSeats] HTTP {r.status_code} for '{query}'")
            return results

        soup = BeautifulSoup(r.text, "lxml")

        nd = soup.find("script", {"id": "__NEXT_DATA__"})
        if nd and nd.string:
            try:
                results.extend(_from_next(json.loads(nd.string)))
            except Exception as e:
                print(f"[VividSeats] __NEXT_DATA__ parse error: {e}")

        for tag in soup.find_all("script", {"type": "application/ld+json"}):
            if not tag.string:
                continue
            try:
                payload = json.loads(tag.string)
                items = payload if isinstance(payload, list) else [payload]
                for item in items:
                    ev = _from_ld(item)
                    if ev:
                        results.append(ev)
            except Exception:
                pass

    except Exception as e:
        print(f"[VividSeats] Request error for '{query}': {e}")

    return results


def _from_next(data: dict) -> List[Dict]:
    out: List[Dict] = []
    props = data.get("props", {}).get("pageProps", {})
    for key in ("productions", "events", "searchResults", "results"):
        for item in props.get(key, []):
            name = (
                item.get("name")
                or item.get("productionName")
                or item.get("title")
                or ""
            )
            if not name or not _is_wc(name):
                continue
            price = item.get("minPrice") or item.get("lowestPrice") or item.get("minTicketPrice")
            if price is None:
                continue
            web_path = item.get("webPath") or item.get("url") or ""
            out.append({
                "platform": "VividSeats",
                "event": name,
                "date": item.get("localDate") or item.get("eventDate") or item.get("date") or "",
                "venue": item.get("venueName") or item.get("venue") or "",
                "url": f"https://www.vividseats.com{web_path}" if web_path.startswith("/") else web_path,
                "min_price": float(price),
                "currency": "USD",
            })
    return out


def _from_ld(ld: dict) -> Dict | None:
    if ld.get("@type") != "Event":
        return None
    name = ld.get("name", "")
    if not _is_wc(name):
        return None
    offers = ld.get("offers") or {}
    price = offers.get("lowPrice") or offers.get("price")
    if price is None:
        return None
    return {
        "platform": "VividSeats",
        "event": name,
        "date": ld.get("startDate", ""),
        "venue": (ld.get("location") or {}).get("name", "") if isinstance(ld.get("location"), dict) else "",
        "url": ld.get("url", ""),
        "min_price": float(price),
        "currency": offers.get("priceCurrency", "USD"),
    }


def _is_wc(name: str) -> bool:
    n = name.lower()
    return "world cup" in n or "fifa" in n
