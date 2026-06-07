#!/usr/bin/env bash
# Refresh SeatGeek prices using your real Chrome session (macOS only).
# Opens 3 tabs briefly, closes them, then commits + pushes the updated prices.json.
# Run this whenever you want fresh SeatGeek prices in the dashboard.
#
# Usage:  ./update_seatgeek.sh

set -euo pipefail
cd "$(dirname "$0")"

set -a && source .env && set +a

echo "Fetching SeatGeek prices via Chrome…"
SG_CHROME=1 python3.9 checker.py

echo ""
echo "Committing prices.json…"
git add prices.json
git commit -m "Update SeatGeek prices (manual run $(date -u +%Y-%m-%dT%H:%MZ))" || echo "(no changes to commit)"
git push
echo "Done — dashboard will refresh within 5 minutes."
