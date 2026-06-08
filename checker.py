#!/usr/bin/env python3
"""
FIFA World Cup 2026 ticket price checker.

Monitors Swiss national team games (any venue) and all games at SoFi Stadium
(Inglewood / Los Angeles). Runs hourly via GitHub Actions; sends email when a
listing hits a new price low AND is below PRICE_CEILING.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from platforms import ticketmaster, seatgeek, stubhub, vividseats, fifa, reddit
from platforms import availability
import notify

PRICE_CEILING = float(os.environ.get("PRICE_CEILING", "500"))
HISTORY_FILE = Path("prices.json")
LOG_FILE = Path("prices_log.csv")

# Search terms drive every platform query.
# Swiss games use the team name; Inglewood games use venue identifiers.
TARGET_SEARCHES = [
    "World Cup Switzerland",        # matches SeatGeek: "Switzerland vs X - World Cup"
    "World Cup SoFi Stadium",       # SoFi games
    "World Cup Inglewood",
    "World Cup Los Angeles 2026",
]


def load_history() -> dict:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return {}


def save_history(history: dict) -> None:
    HISTORY_FILE.write_text(json.dumps(history, indent=2, default=str))


def append_log(listings: list, ts: str) -> None:
    write_header = not LOG_FILE.exists() or LOG_FILE.stat().st_size == 0
    with LOG_FILE.open("a") as f:
        if write_header:
            f.write("timestamp,platform,event,date,venue,min_price,max_price,currency,url\n")
        for l in listings:
            if l.get("min_price") is None:
                continue
            f.write(
                f"{ts},{l['platform']!r},{l['event']!r},{l.get('date','')!r},"
                f"{l.get('venue','')!r},{l['min_price']},{l.get('max_price','')!r},"
                f"{l.get('currency','USD')},{l.get('url','')!r}\n"
            )


def make_key(listing: dict) -> str:
    return f"{listing['platform']}|{listing['event']}|{listing.get('date', '')}|{listing.get('section', '')}"


def dedupe(listings: list) -> list:
    seen: set = set()
    out = []
    for l in listings:
        k = make_key(l)
        if k not in seen:
            seen.add(k)
            out.append(l)
    return out


def check_all() -> list:
    listings = []
    tm_key = os.environ.get("TM_API_KEY", "")
    sg_id = os.environ.get("SG_CLIENT_ID", "")

    for query in TARGET_SEARCHES:
        if tm_key:
            listings.extend(ticketmaster.search(query, tm_key))
        if sg_id:
            listings.extend(seatgeek.search(query, sg_id))
        listings.extend(stubhub.search(query))
        listings.extend(vividseats.search(query))
        listings.extend(fifa.search(query))
        listings.extend(reddit.search(query))

    return dedupe(listings)


def main() -> None:
    now = datetime.now(timezone.utc).isoformat()
    print(f"[{now}] Starting price check | ceiling=${PRICE_CEILING:.0f}")

    history = load_history()
    listings = check_all()
    alerts = []

    print(f"  {len(listings)} unique listings found across all platforms")

    for listing in listings:
        price = listing.get("min_price")
        key = make_key(listing)
        prev = history.get(key, {})

        # Always persist monitored events, even with no price yet.
        # Preserve last_price from previous run — a null return means "scraper
        # couldn't reach the platform this cycle" (e.g. Akamai / Cloudflare
        # blocking GitHub Actions datacenter IPs), NOT "confirmed no listings".
        if price is None:
            # Carry over platform-specific IDs from listing even on null price
            null_extras = {
                k: listing[k]
                for k in ("_tm_event_id", "_vs_id", "_sg_event_id")
                if listing.get(k) is not None
            }
            history[key] = {
                **prev,
                "event": listing["event"],
                "platform": listing["platform"],
                "date": listing.get("date", ""),
                "venue": listing.get("venue", ""),
                "url": listing.get("url", ""),
                "min_seen": prev.get("min_seen"),
                "last_price": prev.get("last_price"),   # keep last known price
                "last_checked": now,
                **null_extras,
            }
            continue

        # Availability check for Reddit posts
        av_status = prev.get("availability", "")
        is_reddit = listing["platform"].lower().startswith("reddit")
        if is_reddit and availability.should_recheck(prev):
            av_status = availability.check(
                listing.get("url", ""),
                listing.get("event", ""),
                listing.get("body", ""),
            )
            label = {"sold": "SOLD", "available": "LIVE", "uncertain": "?"}.get(av_status, "?")
            print(f"  availability [{label}] {listing['event'][:55]}")

        prev_min = prev.get("min_seen")
        is_new_low = prev_min is None or price < prev_min
        below_ceiling = price < PRICE_CEILING

        # Don't alert on sold listings
        if is_new_low and below_ceiling and av_status != "sold":
            alerts.append({**listing, "prev_min": prev_min})
            prev_str = f"${prev_min:.0f}" if prev_min else "first seen"
            print(f"  ALERT  {listing['platform']:15s} | {listing['event'][:60]} | ${price:.0f} (was {prev_str})")

        # Preserve extra platform-specific fields (price_note, url_qty2, counts, etc.)
        extras = {
            k: listing[k]
            for k in ("price_note", "url_qty2", "listing_count", "ticket_count",
                      "base_price", "body", "_tm_event_id", "_vs_id", "_sg_event_id",
                      "best_qty")
            if listing.get(k) is not None
        }
        history[key] = {
            "event": listing["event"],
            "platform": listing["platform"],
            "date": listing.get("date", ""),
            "venue": listing.get("venue", ""),
            "url": listing.get("url", ""),
            "min_seen": min(price, prev_min) if prev_min is not None else price,
            "last_price": price,
            "last_checked": now,
            **({"availability": av_status, "av_checked_at": now} if is_reddit else {}),
            **extras,
        }

    save_history(history)
    append_log(listings, now)

    if alerts:
        notify.send_alerts(alerts, PRICE_CEILING)
        print(f"  Email sent for {len(alerts)} alert(s).")
    else:
        print("  No new lows below ceiling; no email sent.")

    print("Done.")


if __name__ == "__main__":
    main()
