"""Send email alerts via Gmail SMTP (App Password required)."""

import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def _buy_url(alert: dict) -> str:
    """Return the best buy URL, with qty=2 pre-selected where supported."""
    # Prefer a pre-stored qty=2 URL
    if alert.get("url_qty2"):
        return alert["url_qty2"]
    url = alert.get("url", "")
    if not url:
        return ""
    # Append quantity filter for known platforms
    sep = "&" if "?" in url else "?"
    if "vividseats.com" in url:
        return url + sep + "qty=2"
    if "stubhub.com" in url:
        return url + sep + "quantity=2"
    return url


def send_alerts(alerts: list, ceiling: float) -> None:
    gmail_user = os.environ.get("GMAIL_USER", "")
    gmail_pass = os.environ.get("GMAIL_APP_PASSWORD", "")
    dest = os.environ.get("ALERT_EMAIL", gmail_user)

    if not gmail_user or not gmail_pass:
        print("[notify] No credentials — printing to stdout.")
        for a in alerts:
            prev = f"${a['prev_min']:.0f}" if a.get("prev_min") else "first seen"
            print(f"  {a['platform']} | {a['event']} | ${a['min_price']:.0f} (was {prev}) | {a.get('url','')}")
        return

    n = len(alerts)
    subject = f"[WC2026] {n} new price low{'s' if n > 1 else ''} below ${ceiling:.0f}"

    rows = ""
    for a in alerts:
        prev    = f"${a['prev_min']:.0f}" if a.get("prev_min") else "first seen"
        buy_url = _buy_url(a)
        link    = f'<a href="{buy_url}" style="color:#fff;background:#026cdf;padding:4px 10px;border-radius:4px;text-decoration:none;font-size:12px">Buy →</a>' if buy_url else "—"
        note    = a.get("price_note", "")
        note_td = f'<span style="font-size:11px;color:#888">{note}</span>' if note else ""
        tc = a.get("ticket_count") or a.get("listing_count")
        avail = f'<span style="font-size:11px;color:#555">{tc:,} tkts</span>' if tc else ""
        rows += (
            f"<tr>"
            f"<td style='padding:8px 10px;border-bottom:1px solid #eee'>{a['platform']}</td>"
            f"<td style='padding:8px 10px;border-bottom:1px solid #eee'>{a['event']}</td>"
            f"<td style='padding:8px 10px;border-bottom:1px solid #eee;white-space:nowrap'>{(a.get('date') or '')[:10]}</td>"
            f"<td style='padding:8px 10px;border-bottom:1px solid #eee'>{a.get('venue','')}</td>"
            f"<td style='padding:8px 10px;border-bottom:1px solid #eee'><strong style='font-size:16px'>${a['min_price']:.0f}</strong> {note_td}</td>"
            f"<td style='padding:8px 10px;border-bottom:1px solid #eee'>{avail}</td>"
            f"<td style='padding:8px 10px;border-bottom:1px solid #eee'>{prev}</td>"
            f"<td style='padding:8px 10px;border-bottom:1px solid #eee'>{link}</td>"
            f"</tr>\n"
        )

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;color:#222;max-width:900px;margin:0 auto">
<h2 style="color:#003580;border-bottom:3px solid #ffd700;padding-bottom:8px">
  ⚽ FIFA World Cup 2026 — New Price Lows 🇨🇭
</h2>
<p>New all-time lows below your <strong>${ceiling:.0f}</strong> ceiling as of <em>{ts}</em>.
&nbsp;&nbsp;<a href="https://nadirweibel.github.io/wc2026-tickets/"
   style="color:#fff;background:#003580;padding:5px 12px;border-radius:4px;text-decoration:none;font-size:13px;font-weight:bold">
   📊 Open dashboard →</a></p>
<table width="100%" cellpadding="0" cellspacing="0"
       style="border-collapse:collapse;font-size:14px;border:1px solid #ddd">
  <tr style="background:#003580;color:#fff">
    <th style="padding:10px;text-align:left">Platform</th>
    <th style="padding:10px;text-align:left">Event</th>
    <th style="padding:10px;text-align:left">Date</th>
    <th style="padding:10px;text-align:left">Venue</th>
    <th style="padding:10px;text-align:left">Price</th>
    <th style="padding:10px;text-align:left">Available</th>
    <th style="padding:10px;text-align:left">Prev Low</th>
    <th style="padding:10px;text-align:left">Buy (2 tkts)</th>
  </tr>
  {rows}
</table>
<p style="font-size:11px;color:#999;margin-top:16px">
  VividSeats prices are all-in (fees included). StubHub prices include all fees per their policy.
  TM/SeatGeek prices are base price — final cost may be higher.<br>
  Buy links open pre-filtered to 2 tickets where supported (VividSeats &amp; StubHub).<br>
  Checks run hourly. Ceiling: ${ceiling:.0f}.
</p>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = gmail_user
    msg["To"]      = dest
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
        srv.login(gmail_user, gmail_pass)
        srv.sendmail(gmail_user, dest, msg.as_string())
