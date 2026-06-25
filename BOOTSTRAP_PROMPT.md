# Bootstrap Prompt — WC2026 Ticket Checker

Paste this into a new Claude Code session opened in the project folder.

---

## Prompt to paste:

```
I have a FIFA World Cup 2026 ticket price monitoring tool. Please read CLAUDE.md 
in this directory to get up to speed on the project, then let me know what you 
found and ask what I'd like to work on.

Quick context:
- GitHub repo: https://github.com/nadirweibel/wc2026-tickets
- Dashboard: https://nadirweibel.github.io/wc2026-tickets/
- Checks Ticketmaster, SeatGeek, StubHub, VividSeats, Reddit for Switzerland 
  national team games + all SoFi Stadium (LA) games
- Hourly cron via GitHub Actions; also runs locally on my Mac via launchd
- Emails price alerts via Gmail when a new low is found under my ceiling
- prices.json is the live data file (committed back to repo each run)
- Local Mac runs are ahead of GitHub — may need to push/sync before changes

The CLAUDE.md has full architecture, known bugs, and working notes.
```

---

## Where the project lives

| Location | Path |
|---|---|
| Local source | `/Users/weibel2/Projects/wc2026-tickets/` |
| GitHub repo | `https://github.com/nadirweibel/wc2026-tickets` |
| Live dashboard | `https://nadirweibel.github.io/wc2026-tickets/` |
| Local secrets | `/Users/weibel2/Projects/wc2026-tickets/.env` |
| launchd plist | `~/Library/LaunchAgents/com.wc2026.tickets.plist` |

## Before migrating to a new account

1. **Push the 138 local commits** so GitHub has the full price history:
   ```bash
   cd /Users/weibel2/Projects/wc2026-tickets
   git push
   # If rejected: git pull --rebase, resolve data-file conflicts with --theirs, then push
   ```

2. **GitHub Secrets** are stored in the repo settings — they transfer with the repo if you
   transfer or fork it. If starting fresh, re-enter them (see the "GitHub Secrets" table in
   CLAUDE.md).

3. The `.env` file on disk contains your API keys for local runs. It is gitignored — copy it
   manually to the new machine if needed.

4. The **launchd agent** (`com.wc2026.tickets`) runs `run_local.sh` every hour. It was
   installed by `install_local.sh`. To reinstall on a new machine: run `bash install_local.sh`.
