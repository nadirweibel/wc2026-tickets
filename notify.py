"""Send email alerts via Gmail SMTP (App Password required)."""

import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_alerts(alerts: list, ceiling: float) -> None:
    gmail_user = os.environ.get("GMAIL_USER", "")
    gmail_pass = os.environ.get("GMAIL_APP_PASSWORD", "")
    dest = os.environ.get("ALERT_EMAIL", gmail_user)

    if not gmail_user or not gmail_pass:
        print("[notify] No GMAIL_USER / GMAIL_APP_PASSWORD set; printing to stdout.")
        for a in alerts:
            prev = f"${a['prev_min']:.0f}" if a.get("prev_min") else "first seen"
            print(f"  {a['platform']} | {a['event']} | ${a['min_price']:.0f} (was {prev}) | {a.get('url','')}")
        return

    n = len(alerts)
    subject = f"[WC2026 Tickets] {n} new low{'s' if n > 1 else ''} below ${ceiling:.0f}"

    rows = ""
    for a in alerts:
        prev = f"${a['prev_min']:.0f}" if a.get("prev_min") else "first seen"
        url = a.get("url", "")
        link = f'<a href="{url}">Buy</a>' if url else "—"
        venue = a.get("venue", "")
        rows += (
            f"<tr>"
            f"<td>{a['platform']}</td>"
            f"<td>{a['event']}</td>"
            f"<td>{a.get('date', '')}</td>"
            f"<td>{venue}</td>"
            f"<td><strong>${a['min_price']:.0f}</strong></td>"
            f"<td>{prev}</td>"
            f"<td>{link}</td>"
            f"</tr>\n"
        )

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;color:#222;">
<h2 style="color:#003580;">FIFA World Cup 2026 — New Price Lows</h2>
<p>The following listings dropped below your <strong>${ceiling:.0f}</strong> ceiling
and set a new recorded low as of <em>{ts}</em>.</p>
<table border="1" cellpadding="8" cellspacing="0"
       style="border-collapse:collapse;width:100%;font-size:14px;">
  <tr style="background:#003580;color:#fff;">
    <th>Platform</th><th>Event</th><th>Date</th><th>Venue</th>
    <th>Min Price</th><th>Previous Low</th><th>Link</th>
  </tr>
  {rows}
</table>
<p style="font-size:12px;color:#888;margin-top:20px;">
  Min price = cheapest listed ticket found; all-in fees may be higher.<br>
  Checks run hourly. Price ceiling: ${ceiling:.0f}.<br>
  <a href="https://github.com">View full price log</a> in your repo (prices_log.csv).
</p>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = dest
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
        srv.login(gmail_user, gmail_pass)
        srv.sendmail(gmail_user, dest, msg.as_string())
