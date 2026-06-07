#!/bin/bash
# One-time setup: creates .env with your secrets and installs a launchd
# agent that runs the price checker every hour from your Mac.

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Creating $DIR/.env with your API secrets..."
cat > "$DIR/.env" << 'ENVEOF'
TM_API_KEY=8Sr8hk1zFHJAKQQShhl2Ws4G91IIBmjH
SG_CLIENT_ID=Mjc1NjMyMjl8MTc4MDc5ODQxMi4wMjQ2NTU4
GMAIL_USER=nad@nadnet.ch
GMAIL_APP_PASSWORD=ztnmrnyibmakhjrp
ALERT_EMAIL=nad@nadnet.ch
PRICE_CEILING=300
ENVEOF

chmod 600 "$DIR/.env"   # readable only by you

chmod +x "$DIR/run_local.sh"

PLIST="$HOME/Library/LaunchAgents/com.wc2026.tickets.plist"
echo "Installing launchd agent at $PLIST..."
cat > "$PLIST" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.wc2026.tickets</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$DIR/run_local.sh</string>
  </array>
  <key>StartInterval</key>
  <integer>3600</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$DIR/local_run.log</string>
  <key>StandardErrorPath</key>
  <string>$DIR/local_run.log</string>
</dict>
</plist>
PLISTEOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo ""
echo "Done! The checker will now run every hour while your Mac is on."
echo "Logs: $DIR/local_run.log"
echo "To stop it: launchctl unload $PLIST"
