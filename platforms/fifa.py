"""
FIFA official ticketing — best-effort scraper.

The FIFA ticketing portal (tickets.fifa.com) uses a heavily JS-rendered
SPA. This module makes two attempts:
  1. A JSON API endpoint that the portal's mobile site queries.
  2. Parsing JSON-LD from the HTML response if #1 fails.

Expect this to fail silently more often than not; the other platforms
cover resale prices more reliably.
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
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://tickets.fifa.com",
    "Referer": "https://tickets.fifa.com/",
}

_BASE = "https://tickets.fifa.com"


def search(query: str) -> List[Dict]:
    results: List[Dict] = []

    # Attempt 1 — internal catalog API
    results.extend(_try_api(query))
    if results:
        return results

    # Attempt 2 — HTML + JSON-LD from the matches page
    results.extend(_try_html(query))
    return results


def _try_api(query: str) -> List[Dict]:
    out: List[Dict] = []
    candidates = [
        f"{_BASE}/api/matches",
        f"{_BASE}/api/v1/matches",
        f"{_BASE}/api/events",
    ]
    for url in candidates:
        try:
            r = requests.get(url, headers=_HEADERS, timeout=15)
            if r.status_code != 200:
                continue
            data = r.json()
            matches = data if isinstance(data, list) else data.get("matches", data.get("events", []))
            for m in matches:
                if not _matches_query(m, query):
                    continue
                price = m.get("minPrice") or m.get("lowestPrice") or m.get("priceFrom")
                if price is None:
                    continue
                out.append({
                    "platform": "FIFA Official",
                    "event": m.get("matchName") or m.get("name") or m.get("title") or "FIFA WC26 match",
                    "date": m.get("matchDate") or m.get("date") or m.get("startDate") or "",
                    "venue": _venue_str(m),
                    "url": f"{_BASE}/en/tickets",
                    "min_price": float(price),
                    "currency": m.get("currency", "USD"),
                })
            if out:
                break
        except Exception:
            pass
    return out


def _try_html(query: str) -> List[Dict]:
    out: List[Dict] = []
    try:
        r = requests.get(f"{_BASE}/en/tickets", headers=_HEADERS, timeout=20)
        if r.status_code != 200:
            return out
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.find_all("script", {"type": "application/ld+json"}):
            if not tag.string:
                continue
            try:
                payload = json.loads(tag.string)
                items = payload if isinstance(payload, list) else [payload]
                for item in items:
                    if item.get("@type") != "Event":
                        continue
                    if not _matches_query(item, query):
                        continue
                    offers = item.get("offers") or {}
                    price = offers.get("lowPrice") or offers.get("price")
                    if price is None:
                        continue
                    out.append({
                        "platform": "FIFA Official",
                        "event": item.get("name", "FIFA WC26 match"),
                        "date": item.get("startDate", ""),
                        "venue": (item.get("location") or {}).get("name", "") if isinstance(item.get("location"), dict) else "",
                        "url": item.get("url", f"{_BASE}/en/tickets"),
                        "min_price": float(price),
                        "currency": offers.get("priceCurrency", "USD"),
                    })
            except Exception:
                pass
    except Exception as e:
        print(f"[FIFA Official] HTML error: {e}")
    return out


def _matches_query(obj: dict, query: str) -> bool:
    q_words = [w for w in query.lower().split() if len(w) > 3]
    text = " ".join(str(v) for v in obj.values()).lower()
    return any(w in text for w in q_words)


def _venue_str(m: dict) -> str:
    v = m.get("venue") or m.get("stadium") or {}
    if isinstance(v, dict):
        return v.get("name") or v.get("stadiumName") or ""
    return str(v) if v else ""
