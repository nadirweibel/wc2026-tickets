"""
Reddit monitor via RSS feeds.

Reddit's JSON API blocks automated requests (Cloudflare 403), but RSS
feeds remain accessible. Content is Atom XML with HTML-encoded post bodies.

Strategy:
- r/WorldCup2026Tickets: accept all posts (the whole sub is WC tickets);
  just extract prices from the HTML body.
- Other subs: require the post to mention Switzerland or SoFi/LA + a ticket keyword.
"""

import re
import time
import xml.etree.ElementTree as ET
from html import unescape
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, */*",
}

_ATOM = "http://www.w3.org/2005/Atom"

# r/WorldCup2026Tickets is the primary target — all posts are WC tickets.
# Others need stricter filtering.
_PRIMARY_SUB = "WorldCup2026Tickets"
_OTHER_SUBS = [
    "soccertickets",
    "SoccerTickets",
    "Tickets",
    "worldcup",
    "soccer",
    "TicketMarket",
    "SportsTickets",
]

_PRICE_RE = re.compile(
    r'(?:\$\s*|face\s+value\s+\$?\s*)(\d{1,2},\d{3}|\d{2,4})(?:\.\d{2})?',
    re.IGNORECASE,
)
_MIN_P, _MAX_P = 50, 8000


def search(query: str) -> List[Dict]:
    if not query.startswith("World Cup Switzerland"):
        return []
    return _sweep()


_SEARCH_QUERIES = [
    "switzerland world cup tickets",
    "swiss world cup tickets",
    "sofi stadium world cup tickets",
    "inglewood world cup tickets",
]

def _sweep() -> List[Dict]:
    results: List[Dict] = []
    seen: set = set()

    # For every sub (primary + others), run targeted search queries instead of
    # reading the raw /new feed.  Reddit's search pre-filters to relevant posts;
    # _is_relevant then double-checks the body.
    all_subs = [_PRIMARY_SUB] + [s for s in _OTHER_SUBS if s != "FIFAWorldCup"]
    for sub in all_subs:
        for q in _SEARCH_QUERIES:
            _fetch(_f(sub, "search"),
                   {"q": q, "sort": "new", "restrict_sr": "1", "t": "month"},
                   sub, seen, results, strict=True)
            time.sleep(0.3)

    return results


def _f(sub: str, listing: str) -> str:
    return f"https://www.reddit.com/r/{sub}/{listing}/.rss"


def _fetch(url: str, params: dict, sub: str, seen: set, out: list, strict: bool) -> None:
    try:
        r = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        if r.status_code != 200:
            print(f"[Reddit] HTTP {r.status_code} for {url}")
            return
        _parse(r.text, sub, seen, out, strict)
    except Exception as e:
        print(f"[Reddit] Error {url}: {e}")


def _parse(xml_text: str, sub: str, seen: set, out: list, strict: bool) -> None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"[Reddit] XML error: {e}")
        return

    for entry in root.findall(f"{{{_ATOM}}}entry"):
        # Stable ID
        id_el = entry.find(f"{{{_ATOM}}}id")
        post_id = (id_el.text or "").split("_")[-1] if id_el is not None else ""
        if not post_id or post_id in seen:
            continue
        seen.add(post_id)

        # Title
        title_el = entry.find(f"{{{_ATOM}}}title")
        title = unescape(title_el.text or "") if title_el is not None else ""

        # Body — HTML-encoded, strip tags
        content_el = entry.find(f"{{{_ATOM}}}content") or entry.find(f"{{{_ATOM}}}summary")
        raw_html = unescape(content_el.text or "") if content_el is not None else ""
        body = BeautifulSoup(raw_html, "lxml").get_text(" ", strip=True) if raw_html else ""

        # Link
        link_el = entry.find(f"{{{_ATOM}}}link")
        url = link_el.get("href", "") if link_el is not None else ""

        full_text = f"{title} {body}"

        # Relevance gate
        if strict and not _is_relevant(full_text):
            continue

        # Must mention a price
        prices = _extract_prices(full_text)
        if not prices:
            continue

        out.append({
            "platform": f"Reddit r/{sub}",
            "event": title[:120],
            "body": body[:600],     # kept for availability checker
            "date": "",
            "venue": "",
            "url": url,
            "min_price": min(prices),
            "currency": "USD",
            "section": post_id,
        })


def _is_relevant(text: str) -> bool:
    t = text.lower()
    has_target = (
        "switzerland" in t or "swiss" in t or
        "sofi" in t or "inglewood" in t or
        ("los angeles" in t and ("world cup" in t or "wc2026" in t or "fifa" in t))
    )
    has_ticket = any(w in t for w in (
        "ticket", "seat", "wts", "wtb", "for sale", "face value", "fs:", "selling", "$"
    ))
    return has_target and has_ticket


def _extract_prices(text: str) -> List[float]:
    out = []
    for raw in _PRICE_RE.findall(text):
        try:
            val = float(raw.replace(",", ""))
            if _MIN_P <= val <= _MAX_P:
                out.append(val)
        except ValueError:
            pass
    return out
