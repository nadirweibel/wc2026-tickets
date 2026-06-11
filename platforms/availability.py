"""
Reddit post availability checker.

Fetches the Reddit post page (old.reddit.com renders server-side so no JS needed),
extracts title + body + top comments, then asks Claude Haiku whether the ticket
is still for sale.

Fast regex signals are checked first to avoid API calls for obvious cases.
Only runs when ANTHROPIC_API_KEY is set; falls back to "uncertain" otherwise.
"""

import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from html import unescape
from typing import Optional

import requests
from bs4 import BeautifulSoup

_ATOM = "http://www.w3.org/2005/Atom"

try:
    import anthropic as _anthropic
    _HAS_ANTHROPIC = True
except ImportError:
    _HAS_ANTHROPIC = False

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, */*",
}

_SOLD_RE = re.compile(
    r'\b(sold|no longer available|not available|deal closed|found a buyer|'
    r'taken|nevermind|never mind|pulled the listing|off the market)\b',
    re.IGNORECASE,
)
_DELETED_RE = re.compile(r'^\s*\[(deleted|removed)\]', re.IGNORECASE)
_AVAILABLE_RE = re.compile(
    r'\b(still available|still have|dm me|pm me|send offer|message me|lmk|'
    r'reach out|willing to negotiate|open to offers)\b',
    re.IGNORECASE,
)

RECHECK_INTERVAL = timedelta(hours=4)   # re-check "available/uncertain" posts
SOLD_TTL = timedelta(hours=24)          # re-check "sold" posts once/day (post may delete)


def should_recheck(prev: dict) -> bool:
    """True if we should call check() again for this listing."""
    last = prev.get("av_checked_at")
    if not last:
        return True
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(last)
    except Exception:
        return True
    status = prev.get("availability", "")
    if status == "sold":
        return age > SOLD_TTL
    return age > RECHECK_INTERVAL


def check(url: str, title: str, body: str = "") -> str:
    """
    Returns 'available', 'sold', or 'uncertain'.
    Tries regex first; calls Claude Haiku when inconclusive.
    """
    quick = f"{title} {body}"

    if _SOLD_RE.search(quick):
        return "sold"
    if _AVAILABLE_RE.search(title):   # title only — body can be empty for new posts
        return "available"

    post_body, comments = _fetch_post(url)

    # Post was deleted/removed by author or mods — listing is dead.
    if post_body is not None and _DELETED_RE.match(post_body):
        return "sold"

    page_text = " | ".join(filter(None, [post_body, *comments]))
    if page_text and _SOLD_RE.search(page_text):
        return "sold"

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or not _HAS_ANTHROPIC:
        return "uncertain"

    return _llm_check(api_key, title, body, page_text)


def _fetch_post(url: str) -> tuple[Optional[str], list[str]]:
    """Fetch the post body and top comments via the comments-page RSS feed.

    Returns (post_body, [comment_texts]). post_body is None on fetch failure.
    """
    if not url or "reddit.com" not in url:
        return None, []
    try:
        # Reddit 403s on /.rss when the URL slug is present — strip it down
        # to /comments/<post_id>/.rss
        m = re.search(r'/comments/([a-z0-9]+)', url)
        if not m:
            return None, []
        rss_url = re.sub(r'(/comments/[a-z0-9]+).*', r'\1/.rss', url)
        r = requests.get(rss_url, headers=_HEADERS, timeout=15)
        if r.status_code != 200:
            return None, []

        root = ET.fromstring(r.text)
        entries = root.findall(f"{{{_ATOM}}}entry")
        if not entries:
            return None, []

        texts = []
        for entry in entries:
            content_el = entry.find(f"{{{_ATOM}}}content")
            raw = unescape(content_el.text) if content_el is not None and content_el.text else ""
            text = BeautifulSoup(raw, "lxml").get_text(" ", strip=True) if raw else ""
            texts.append(text)

        return texts[0], texts[1:11]
    except Exception as e:
        print(f"[availability] Fetch error {url}: {e}")
        return None, []


def _llm_check(api_key: str, title: str, body: str, page: str) -> str:
    try:
        client = _anthropic.Anthropic(api_key=api_key)
        snippet = (
            f"Title: {title}\n"
            f"Post body: {body[:400]}\n"
            f"Comments/page: {page[:800]}"
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=5,
            system=(
                "You check if a ticket listing on Reddit is still for sale. "
                "Reply with exactly one word: available, sold, or uncertain."
            ),
            messages=[{"role": "user", "content": snippet}],
        )
        answer = msg.content[0].text.strip().lower()
        if any(w in answer for w in ("sold", "gone", "unavailable", "taken", "no")):
            return "sold"
        if "available" in answer or "yes" in answer:
            return "available"
        return "uncertain"
    except Exception as e:
        print(f"[availability] LLM error: {e}")
        return "uncertain"
