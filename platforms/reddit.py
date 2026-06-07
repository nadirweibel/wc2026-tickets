"""
Reddit scraper using Reddit's public JSON API.

Reddit serves JSON for any page by appending .json to the URL — no auth,
no app registration needed. Rate limit is ~60 req/min for unauthenticated
access, well within our hourly cadence.

Monitors r/WorldCup2026Tickets plus several other subs, searching for
posts that mention ticket prices for Swiss games or SoFi/LA games.
"""

import re
import time
import requests
from typing import List, Dict

_HEADERS = {
    # Reddit requires a descriptive User-Agent for unauthenticated requests.
    "User-Agent": "wc2026-ticket-checker/1.0 (price monitor; contact via github.com/nadirweibel/wc2026-tickets)",
    "Accept": "application/json",
}

# Subreddits to monitor — checked newest posts + searched
_MONITOR_SUBS = [
    "WorldCup2026Tickets",  # most targeted
    "soccertickets",
    "Tickets",
    "FIFA",
    "worldcup",
    "soccer",
]

# Search terms run against each subreddit
_SEARCHES = [
    "Switzerland FIFA World Cup 2026 ticket",
    "FIFA World Cup 2026 SoFi ticket",
    "FIFA World Cup 2026 Inglewood ticket",
    "FIFA World Cup 2026 Los Angeles ticket",
]

# Dollar amounts between $30 and $8000 are treated as plausible ticket prices
_PRICE_RE = re.compile(
    r'(?:\$\s*|face\s+value\s+\$?\s*)(\d{1,2},\d{3}|\d{2,4})(?:\.\d{2})?',
    re.IGNORECASE,
)
_MIN_P, _MAX_P = 30, 8000


def search(query: str) -> List[Dict]:
    """
    Called once per TARGET_SEARCH query by checker.py.
    On the first query we do the full sweep; subsequent calls are no-ops
    to avoid redundant requests (results are already deduped by post ID).
    """
    # Only do the full sweep on the first query to avoid redundant requests
    if not query.startswith("World Cup Switzerland"):
        return []
    return _sweep()


def _sweep() -> List[Dict]:
    results: List[Dict] = []
    seen_ids: set = set()

    for sub in _MONITOR_SUBS:
        # 1. Newest posts in the sub
        posts = _fetch(f"https://www.reddit.com/r/{sub}/new.json", {"limit": 25})
        _parse_posts(posts, seen_ids, results)
        time.sleep(0.5)   # polite pacing

        # 2. Search within the sub for WC2026 ticket terms
        for q in _SEARCHES:
            posts = _fetch(
                f"https://www.reddit.com/r/{sub}/search.json",
                {"q": q, "sort": "new", "t": "month", "limit": 15, "restrict_sr": 1},
            )
            _parse_posts(posts, seen_ids, results)
            time.sleep(0.5)

    return results


def _fetch(url: str, params: dict) -> list:
    try:
        r = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        if r.status_code == 429:
            print(f"[Reddit] Rate limited on {url}; skipping.")
            return []
        if r.status_code != 200:
            print(f"[Reddit] HTTP {r.status_code} for {url}")
            return []
        data = r.json()
        return data.get("data", {}).get("children", [])
    except Exception as e:
        print(f"[Reddit] Error fetching {url}: {e}")
        return []


def _parse_posts(children: list, seen_ids: set, results: list) -> None:
    for child in children:
        post = child.get("data", {})
        post_id = post.get("id", "")
        if not post_id or post_id in seen_ids:
            continue
        seen_ids.add(post_id)

        title = post.get("title", "")
        body  = post.get("selftext", "")
        text  = f"{title} {body}"

        if not _is_relevant(text):
            continue

        prices = _extract_prices(text)
        if not prices:
            continue

        sub_name = post.get("subreddit", "")
        results.append({
            "platform": f"Reddit r/{sub_name}",
            "event": title[:120],
            "date": "",
            "venue": "",
            "url": f"https://reddit.com{post.get('permalink', '')}",
            "min_price": min(prices),
            "currency": "USD",
            "section": post_id,   # stable unique key in prices.json
        })


def _is_relevant(text: str) -> bool:
    t = text.lower()
    has_wc = "world cup" in t or "fifa" in t or "wc2026" in t or "wc 2026" in t
    has_target = (
        "switzerland" in t or "swiss" in t
        or "sofi" in t or "inglewood" in t
        or "los angeles" in t
    )
    has_ticket = any(w in t for w in ("ticket", "seat", "selling", "wtb", "wts", "for sale", "face value"))
    return has_wc and (has_target or has_ticket)


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
