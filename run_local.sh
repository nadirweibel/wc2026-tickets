#!/bin/bash
# Local hourly runner for wc2026-tickets.
# Runs from your Mac (residential IP) so StubHub, VividSeats, and Reddit
# aren't blocked. Commits updated prices.json to GitHub automatically.

set -e
cd "$(dirname "$0")"

# Load secrets from .env if present (created by install_local.sh)
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

echo "=== WC2026 ticket check $(date) ==="
python3 checker.py

# Push updated prices.json so the dashboard reflects local results too
git add prices.json prices_log.csv 2>/dev/null || true
git diff --staged --quiet || \
  git commit -m "prices (local): $(date -u +%Y-%m-%dT%H:%MZ)" && \
  git push
