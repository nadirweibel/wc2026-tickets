"""
Ticketmaster — Playwright-based resale price scraper.

Loads each event with quantities 1–4 in parallel (separate browser tabs).
TM's resale page reads the ?qty=N URL param and passes it to its internal
offeradapter.ticketmaster.com `facets?show=totalpricerange` API, so each
quantity can yield a different cheapest-available price.

All prices are all-in (total cost including service fees) per TM's display.

Requires: playwright (`pip install playwright && playwright install chromium`)
"""

import asyncio
from typing import Dict, List, Optional, Tuple

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)

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

_QTYS = ["1", "2", "3", "4"]
_MAX_CONCURRENT = 3    # concurrent events (each spawns 4 qty pages)
_PRICE_TIMEOUT  = 20   # seconds to wait for the TM price API per page


def search(query: str, api_key: str = "") -> List[Dict]:
    if not query.startswith("World Cup Switzerland"):
        return []
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("[Ticketmaster] playwright not installed — returning null-price entries")
        return _null_entries()
    try:
        return asyncio.run(_scrape_all())
    except RuntimeError:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(asyncio.run, _scrape_all()).result()


async def _scrape_all() -> List[Dict]:
    from playwright.async_api import async_playwright

    sem = asyncio.Semaphore(_MAX_CONCURRENT)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-setuid-sandbox"],
        )
        ctx = await browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1280, "height": 900},
        )

        tasks = [_scrape_event(ctx, sem, eid, meta) for eid, meta in _EVENTS.items()]
        results = await asyncio.gather(*tasks)
        await browser.close()

    return [r for r in results if r is not None]


async def _fetch_qty_price(ctx, event_id: str, meta: dict, qty: str) -> Tuple[str, Optional[float], Optional[int]]:
    """Load one TM event page with ?qty=N and intercept the facets price API."""
    page = await ctx.new_page()
    captured_facets: list = []
    price_ready: asyncio.Future = asyncio.get_event_loop().create_future()

    async def on_response(response):
        url = response.url
        if "totalpricerange" in url and (
            "offeradapter.ticketmaster" in url or event_id in url
        ):
            try:
                body = await response.json()
                captured_facets.extend(body.get("facets", []))
                if not price_ready.done():
                    price_ready.set_result(True)
            except Exception:
                pass

    page.on("response", on_response)

    base_url = meta.get("url") or f"https://www.ticketmaster.com/event/{event_id}"
    page_url = f"{base_url}?qty={qty}"
    try:
        await page.goto(page_url, timeout=30_000, wait_until="domcontentloaded")
        try:
            await asyncio.wait_for(asyncio.shield(price_ready), timeout=_PRICE_TIMEOUT)
        except asyncio.TimeoutError:
            pass
    except Exception as e:
        print(f"[Ticketmaster] Error qty={qty} {event_id}: {e}")
    finally:
        await page.close()

    prices = [
        float(pr["min"])
        for f in captured_facets
        for pr in f.get("totalPriceRange", [])
        if pr.get("min") is not None
    ]
    price = min(prices) if prices else None
    listing_count = len(prices) if prices else None
    return qty, price, listing_count


async def _scrape_event(ctx, sem, event_id: str, meta: dict) -> Optional[Dict]:
    async with sem:
        qty_results = await asyncio.gather(
            *[_fetch_qty_price(ctx, event_id, meta, qty) for qty in _QTYS]
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
            print(f"[Ticketmaster] {meta['name'][:45]:45s}  {qty_log}  → best ${best_price:.0f} (qty={best_qty})")
        else:
            print(f"[Ticketmaster] {meta['name'][:45]:45s}  no data")

        url = meta.get("url") or f"https://www.ticketmaster.com/event/{event_id}"
        return {
            "platform":      "Ticketmaster",
            "event":         meta["name"],
            "date":          meta["date"],
            "venue":         meta["venue"],
            "url":           url,
            "min_price":     best_price,
            "price_note":    "all-in" if best_price else None,
            "listing_count": best_listing_count,
            "best_qty":      int(best_qty) if best_qty else None,
            "currency":      "USD",
            "_tm_event_id":  event_id,
        }


def _null_entries() -> List[Dict]:
    return [
        {
            "platform":    "Ticketmaster",
            "event":       meta["name"],
            "date":        meta["date"],
            "venue":       meta["venue"],
            "url":         meta.get("url") or f"https://www.ticketmaster.com/event/{event_id}",
            "min_price":   None,
            "currency":    "USD",
            "_tm_event_id": event_id,
        }
        for event_id, meta in _EVENTS.items()
    ]
