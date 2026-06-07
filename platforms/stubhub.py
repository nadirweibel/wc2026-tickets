"""
StubHub scraper.

StubHub's public API requires a partner agreement; no free tier exists.
We scrape the search-result HTML, which is Next.js-rendered. The page
embeds its initial state as JSON inside a <script id="__NEXT_DATA__"> tag
and also emits standard JSON-LD Event markup — we try both.

Will return [] if StubHub blocks the request (Cloudflare challenge, etc.).
"""

import json
import re
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
    "Sec-Fetch-Mode": "navigate",
}

_SEARCH_URL = "https://www.stubhub.com/secure/search"


def search(query: str) -> List[Dict]:
    results: List[Dict] = []
    try:
        r = requests.get(
            _SEARCH_URL,
            params={"q": query},
            headers=_HEADERS,
            timeout=20,
            allow_redirects=True,
        )
        if r.status_code != 200:
            print(f"[StubHub] HTTP {r.status_code} for '{query}'")
            return results

        soup = BeautifulSoup(r.text, "lxml")

        # Path 1: Next.js state blob
        nd = soup.find("script", {"id": "__NEXT_DATA__"})
        if nd and nd.string:
            try:
                results.extend(_from_next(json.loads(nd.string)))
            except Exception as e:
                print(f"[StubHub] __NEXT_DATA__ parse error: {e}")

        # Path 2: JSON-LD Event markup
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
        print(f"[StubHub] Request error for '{query}': {e}")

    return results


def _from_next(data: dict) -> List[Dict]:
    out: List[Dict] = []
    props = data.get("props", {}).get("pageProps", {})
    # StubHub uses several different keys depending on search vs category page
    for key in ("events", "searchResults", "results", "items"):
        for item in props.get(key, []):
            name = item.get("name") or item.get("title") or ""
            if not name or not _is_wc(name):
                continue
            price = (
                item.get("minTicketPrice")
                or item.get("minPrice")
                or (item.get("ticketInfo") or {}).get("minListPrice")
            )
            if price is None:
                continue
            out.append({
                "platform": "StubHub",
                "event": name,
                "date": item.get("eventDateLocal") or item.get("date") or "",
                "venue": item.get("venue") or item.get("venueName") or "",
                "url": "https://www.stubhub.com" + (item.get("url") or item.get("eventUrl") or ""),
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
        "platform": "StubHub",
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
