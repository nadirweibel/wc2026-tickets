"""
Ticketmaster — Playwright-based resale price scraper.

The Discovery API returns null priceRanges for all WC events (resale not
exposed on the free tier). This module loads TM event pages in a headless
Chromium browser and intercepts the offeradapter.ticketmaster.com
`facets?show=totalpricerange` API response that TM's own frontend calls.

All prices are all-in (total cost including service fees) per TM's pricing
display convention.

Requires: playwright (`pip install playwright && playwright install chromium`)
Falls back gracefully to null-price monitoring entries if not installed.
"""

import asyncio
from typing import Dict, List, Optional

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)

# All Switzerland group-stage + SoFi WC matches (deduped)
_EVENTS: Dict[str, dict] = {
    "Z7r9jZ1A7433K": {
        "name": "Qatar vs Switzerland - World Cup - Match 8 (Group B)",
        "date": "2026-06-13",
        "venue": "Levi's Stadium",
    },
    "Z7r9jZ1A743f3": {
        "name": "Switzerland vs Bosnia-Herzegovina - World Cup - Match 26 (Group B)",
        "date": "2026-06-18",
        "venue": "SoFi Stadium",
    },
    "Z7r9jZ1A743fg": {
        "name": "Canada vs Switzerland - World Cup - Match 51 (Group B)",
        "date": "2026-06-24",
        "venue": "BC Place Stadium",
        "url": "https://www.ticketmaster.ca/event/Z7r9jZ1A743fg",
    },
    "Z7r9jZ1A74333": {
        "name": "USA vs Paraguay - World Cup - Match 4 (Group D)",
        "date": "2026-06-12",
        "venue": "SoFi Stadium",
    },
    "Z7r9jZ1A743fe": {
        "name": "Iran vs New Zealand - World Cup - Match 15 (Group G)",
        "date": "2026-06-15",
        "venue": "SoFi Stadium",
    },
    "Z7r9jZ1A743fN": {
        "name": "Belgium vs Iran - World Cup - Match 39 (Group G)",
        "date": "2026-06-21",
        "venue": "SoFi Stadium",
    },
    "Z7r9jZ1A7434Z": {
        "name": "USA vs Turkey - World Cup - Match 59 (Group D)",
        "date": "2026-06-25",
        "venue": "SoFi Stadium",
    },
    "Z7r9jZ1A7434f": {
        "name": "World Cup Round of 32: 2A vs. 2B (Match 73)",
        "date": "2026-06-28",
        "venue": "SoFi Stadium",
    },
    "Z7r9jZ1A7434N": {
        "name": "World Cup Round of 32: 1H vs. 2J (Match 84)",
        "date": "2026-07-02",
        "venue": "SoFi Stadium",
    },
    "Z7r9jZ1A7434U": {
        "name": "World Cup Quarterfinals: W93 vs. W94 (Match 98)",
        "date": "2026-07-10",
        "venue": "SoFi Stadium",
    },
}

_MAX_CONCURRENT = 3   # browser tabs in parallel (balance throughput vs resource use)
_PRICE_TIMEOUT = 20  # max seconds to wait for the price API to respond per event


def search(query: str, api_key: str = "") -> List[Dict]:
    """Run once per checker cycle; api_key kept for interface compatibility."""
    if not query.startswith("World Cup Switzerland"):
        return []

    try:
        import playwright  # noqa: F401 — just check availability
    except ImportError:
        print("[Ticketmaster] playwright not installed — returning null-price entries")
        return _null_entries()

    try:
        return asyncio.run(_scrape_all())
    except RuntimeError:
        # Already inside an event loop (e.g., Jupyter) — run in thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(asyncio.run, _scrape_all())
            return fut.result()


# ── async scraper ─────────────────────────────────────────────────────────────

async def _scrape_all() -> List[Dict]:
    from playwright.async_api import async_playwright

    results: List[Optional[Dict]] = []
    sem = asyncio.Semaphore(_MAX_CONCURRENT)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ],
        )
        ctx = await browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1280, "height": 900},
        )

        tasks = [
            _scrape_event(ctx, sem, event_id, meta)
            for event_id, meta in _EVENTS.items()
        ]
        results = await asyncio.gather(*tasks)
        await browser.close()

    return [r for r in results if r is not None]


async def _scrape_event(ctx, sem, event_id: str, meta: dict) -> Optional[Dict]:
    async with sem:
        page = await ctx.new_page()
        captured_facets: list = []
        price_ready: asyncio.Future = asyncio.get_event_loop().create_future()

        async def on_response(response):
            url = response.url
            # Match offeradapter on any TM domain (.com or .ca)
            if "totalpricerange" in url and ("offeradapter.ticketmaster" in url or event_id in url):
                try:
                    body = await response.json()
                    captured_facets.extend(body.get("facets", []))
                    if not price_ready.done():
                        price_ready.set_result(True)
                except Exception:
                    pass

        page.on("response", on_response)

        event_url = meta.get("url") or f"https://www.ticketmaster.com/event/{event_id}"
        try:
            await page.goto(
                event_url,
                timeout=30_000,
                wait_until="domcontentloaded",
            )
            # Wait until the price API responds (or timeout)
            try:
                await asyncio.wait_for(asyncio.shield(price_ready), timeout=_PRICE_TIMEOUT)
            except asyncio.TimeoutError:
                pass  # proceed with whatever was captured
        except Exception as e:
            print(f"[Ticketmaster] Error loading {event_id}: {e}")
        finally:
            await page.close()

        prices = [
            float(pr["min"])
            for f in captured_facets
            for pr in f.get("totalPriceRange", [])
            if pr.get("min") is not None
        ]
        min_price = min(prices) if prices else None
        listing_count = len(prices) if prices else None

        if min_price:
            print(f"[Ticketmaster] {meta['name'][:55]:55s} ${min_price:.0f} all-in ({listing_count} listings)")
        else:
            print(f"[Ticketmaster] {meta['name'][:55]:55s} no data")

        url = meta.get("url") or f"https://www.ticketmaster.com/event/{event_id}"
        return {
            "platform": "Ticketmaster",
            "event": meta["name"],
            "date": meta["date"],
            "venue": meta["venue"],
            "url": url,
            "min_price": min_price,
            "price_note": "all-in" if min_price else None,
            "listing_count": listing_count,
            "currency": "USD",
            "_tm_event_id": event_id,
        }


# ── fallback ──────────────────────────────────────────────────────────────────

def _null_entries() -> List[Dict]:
    return [
        {
            "platform": "Ticketmaster",
            "event": meta["name"],
            "date": meta["date"],
            "venue": meta["venue"],
            "url": meta.get("url") or f"https://www.ticketmaster.com/event/{event_id}",
            "min_price": None,
            "currency": "USD",
            "_tm_event_id": event_id,
        }
        for event_id, meta in _EVENTS.items()
    ]

