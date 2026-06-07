"""
Reddit monitor.

Searches relevant subreddits for new posts mentioning WC2026 tickets.
Extracts dollar amounts from post titles and bodies; alerts on new posts
that mention prices below the ceiling (not yet seen in prices.json).

Requires a Reddit "script" app — free, no approval needed.
Create one at reddit.com/prefs/apps → "script" type.
Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in GitHub Secrets.
"""

import os
import re
from typing import List, Dict

try:
    import praw
    _HAS_PRAW = True
except ImportError:
    _HAS_PRAW = False

# Subreddits most likely to have WC2026 ticket posts or price tips
_SUBS = [
    "WorldCup2026Tickets",   # most targeted — dedicated WC2026 ticket sub
    "soccertickets",
    "Tickets",
    "FIFA",
    "worldcup",
    "soccer",
    "LosAngeles",
]

# Matches: $200, $1,500, $350.00, "200 each", "face value 250"
_PRICE_RE = re.compile(
    r'(?:\$\s*|face\s+value\s+\$?\s*)(\d{1,2},\d{3}|\d{2,4})(?:\.\d{2})?(?:\s*/?\s*each)?',
    re.IGNORECASE,
)

# Only treat amounts in this range as plausible ticket prices
_MIN_PLAUSIBLE = 30
_MAX_PLAUSIBLE = 8000


def search(query: str) -> List[Dict]:
    if not _HAS_PRAW:
        print("[Reddit] praw not installed; skipping.")
        return []

    client_id = os.environ.get("REDDIT_CLIENT_ID", "")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return []

    results: List[Dict] = []
    seen_ids: set = set()

    try:
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent="wc2026-ticket-checker/1.0 (by u/wc2026bot)",
            ratelimit_seconds=60,
        )

        combined = "+".join(_SUBS)
        sub = reddit.subreddit(combined)

        try:
            posts = list(sub.search(query, sort="new", time_filter="month", limit=25))
        except Exception as e:
            print(f"[Reddit] Search error for '{query}': {e}")
            return []

        for post in posts:
            if post.id in seen_ids:
                continue
            seen_ids.add(post.id)

            text = f"{post.title} {post.selftext}"
            prices = _extract_prices(text)
            if not prices:
                continue

            min_p = min(prices)
            results.append({
                "platform": f"Reddit r/{post.subreddit.display_name}",
                "event": post.title[:120],
                "date": "",
                "venue": "",
                "url": f"https://reddit.com{post.permalink}",
                "min_price": min_p,
                "currency": "USD",
                "section": post.id,     # reuse section field as a stable unique key
                "reddit_score": post.score,
                "reddit_flair": post.link_flair_text or "",
            })

    except Exception as e:
        print(f"[Reddit] Connection error: {e}")

    return results


def _extract_prices(text: str) -> List[float]:
    candidates = []
    for raw in _PRICE_RE.findall(text):
        try:
            val = float(raw.replace(",", ""))
            if _MIN_PLAUSIBLE <= val <= _MAX_PLAUSIBLE:
                candidates.append(val)
        except ValueError:
            pass
    return candidates
