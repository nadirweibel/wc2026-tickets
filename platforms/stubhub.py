"""
StubHub — Playwright-based scraper.

Loads each event page with quantities 1–4 in parallel (separate browser tabs).
StubHub's ?quantity=N URL param filters the listing view, so different quantities
can surface different cheapest-available prices (some listings only sell in pairs,
some only in groups of 4, etc.).

Falls back gracefully to null-price entries if Playwright is not installed or if
Akamai blocks the request (checker.py preserves last known prices on null runs).

Requires: playwright (`pip install playwright && playwright install chromium`)
"""

import asyncio
import re
from typing import Dict, List, Optional, Tuple

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)

_EVENTS: Dict[str, dict] = {
    # ── Switzerland group-stage ────────────────────────────────────────────
    "153020611": {
        "name": "Qatar vs Switzerland - World Cup - Group B (Match 8)",
        "date": "2026-06-13",
        "venue": "Levi's Stadium",
        "url": "https://www.stubhub.com/world-cup-santa-clara-tickets-6-13-2026/event/153020611/",
    },
    "153020716": {
        "name": "Switzerland vs Bosnia-Herzegovina - World Cup - Match 26 (Group B)",
        "date": "2026-06-18",
        "venue": "SoFi Stadium",
        "url": "https://www.stubhub.com/world-cup-inglewood-tickets-6-18-2026/event/153020716/",
    },
    "153020467": {
        "name": "Canada vs Switzerland - World Cup - Match 51 (Group B)",
        "date": "2026-06-24",
        "venue": "BC Place Stadium",
        "url": "https://www.stubhub.com/world-cup-vancouver-tickets-6-24-2026/event/153020467/",
    },
    # ── SoFi / Inglewood events ────────────────────────────────────────────
    "153020709": {
        "name": "USA vs Paraguay - World Cup - Match 4 (Group D)",
        "date": "2026-06-12",
        "venue": "SoFi Stadium",
        "url": "https://www.stubhub.com/world-cup-inglewood-tickets-6-12-2026/event/153020709/",
    },
    "153020712": {
        "name": "Iran vs New Zealand - World Cup - Match 15 (Group G)",
        "date": "2026-06-15",
        "venue": "SoFi Stadium",
        "url": "https://www.stubhub.com/world-cup-inglewood-tickets-6-15-2026/event/153020712/",
    },
    "153020717": {
        "name": "Belgium vs Iran - World Cup - Match 39 (Group G)",
        "date": "2026-06-21",
        "venue": "SoFi Stadium",
        "url": "https://www.stubhub.com/world-cup-inglewood-tickets-6-21-2026/event/153020717/",
    },
    "153020718": {
        "name": "USA vs Turkey - World Cup - Match 59 (Group D)",
        "date": "2026-06-25",
        "venue": "SoFi Stadium",
        "url": "https://www.stubhub.com/world-cup-inglewood-tickets-6-25-2026/event/153020718/",
    },
    "153020724": {
        "name": "World Cup Round of 32: 2A vs. 2B (Match 73)",
        "date": "2026-06-28",
        "venue": "SoFi Stadium",
        "url": "https://www.stubhub.com/world-cup-inglewood-tickets-6-28-2026/event/153020724/",
    },
    "153020726": {
        "name": "World Cup Round of 32: 1H vs. 2J (Match 84)",
        "date": "2026-07-02",
        "venue": "SoFi Stadium",
        "url": "https://www.stubhub.com/world-cup-inglewood-tickets-7-2-2026/event/153020726/",
    },
}

_QTYS = ["1", "2", "3", "4"]
_MAX_CONCURRENT = 3   # concurrent events (each spawns 4 qty pages)
_PAGE_SETTLE = 5      # seconds to wait for JS rendering after domcontentloaded


def search(query: str, api_key: str = "") -> List[Dict]:
    if not query.startswith("World Cup Switzerland"):
        return []
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("[StubHub] playwright not installed — returning null-price entries")
        return _null_entries()
    try:
        return asyncio.run(_scrape_all())
    except RuntimeError:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(asyncio.run, _scrape_all()).result()


async def _scrape_all() -> List[Dict]:
    from playwright.async_api import async_playwright
    import os

    sem = asyncio.Semaphore(_MAX_CONCURRENT)

    async with async_playwright() as pw:
        chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        launch_kwargs = dict(
            headless=True,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-setuid-sandbox"],
        )
        if os.path.exists(chrome_path):
            launch_kwargs["executable_path"] = chrome_path

        browser = await pw.chromium.launch(**launch_kwargs)
        ctx = await browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1280, "height": 900},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )

        tasks = [_scrape_event(ctx, sem, eid, meta) for eid, meta in _EVENTS.items()]
        results = await asyncio.gather(*tasks)
        await browser.close()

    return [r for r in results if r is not None]


async def _fetch_qty_page(ctx, meta: dict, qty: str) -> Tuple[str, Optional[float], Optional[int]]:
    """Load one StubHub event page with a specific quantity filter, return (qty, price, listing_count)."""
    from playwright.async_api import TimeoutError as PWTimeout
    page = await ctx.new_page()
    try:
        url = meta["url"].rstrip("/") + f"/?quantity={qty}"
        await page.goto(url, timeout=30_000, wait_until="domcontentloaded")
        await asyncio.sleep(_PAGE_SETTLE)

        data = await page.evaluate(r"""() => {
            const text = document.body.innerText;
            const countMatch = text.match(/([0-9,]+)\s+listings?/i);
            const listingCount = countMatch ? parseInt(countMatch[1].replace(/,/g,'')) : null;
            const priceMatches = text.match(/\$([0-9]{2,4}(?:,[0-9]{3})*(?:\.[0-9]{2})?)/g) || [];
            const prices = priceMatches
                .map(m => parseFloat(m.replace(/[$,]/g, '')))
                .filter(p => p >= 50 && p <= 9999);
            return {listingCount, prices};
        }""")

        prices = data.get("prices", [])
        price = min(prices) if prices else None
        return qty, price, data.get("listingCount")
    except Exception as e:
        print(f"[StubHub] Error qty={qty} {meta['name'][:35]}: {e}")
        return qty, None, None
    finally:
        await page.close()


async def _scrape_event(ctx, sem, event_id: str, meta: dict) -> Optional[Dict]:
    async with sem:
        # Fetch all quantities in parallel
        qty_results = await asyncio.gather(
            *[_fetch_qty_page(ctx, meta, qty) for qty in _QTYS]
        )

        best_qty: Optional[str] = None
        best_price: Optional[float] = None
        best_listing_count: Optional[int] = None
        price_by_qty: Dict[str, Optional[float]] = {}

        for qty, price, listing_count in qty_results:
            price_by_qty[qty] = price
            if price is not None and (best_price is None or price < best_price):
                best_price = price
                best_qty = qty
                best_listing_count = listing_count

        qty_log = "  ".join(
            f"qty{q}=${price_by_qty[q]:.0f}" if price_by_qty.get(q) else f"qty{q}=—"
            for q in _QTYS
        )
        if best_price:
            print(f"[StubHub] {meta['name'][:45]:45s}  {qty_log}  → best ${best_price:.0f} (qty={best_qty})")
        else:
            print(f"[StubHub] {meta['name'][:45]:45s}  no data")

        return {
            "platform":      "StubHub",
            "event":         meta["name"],
            "date":          meta["date"],
            "venue":         meta["venue"],
            "url":           meta["url"],
            "min_price":     best_price,
            "price_note":    "all-in" if best_price else None,
            "listing_count": best_listing_count,
            "best_qty":      int(best_qty) if best_qty else None,
            "currency":      "USD",
        }


def _null_entries() -> List[Dict]:
    return [
        {
            "platform": "StubHub",
            "event":    meta["name"],
            "date":     meta["date"],
            "venue":    meta["venue"],
            "url":      meta["url"],
            "min_price": None,
            "currency": "USD",
        }
        for meta in _EVENTS.values()
    ]
