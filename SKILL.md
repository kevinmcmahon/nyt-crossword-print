---
name: nyt-crossword-print
description: >
  Automatically downloads the daily NYT crossword puzzle PDF and prints it
  to a network printer. Runs on a nightly schedule via cron. Supports
  pause/resume via Telegram and sends error alerts on failure.
version: 1.0.0
author: user
tags:
  - crossword
  - nyt
  - printing
  - automation
requirements:
  - python3 (3.10+)
  - playwright (pip install playwright && playwright install chromium)
  - pass (GNU password store, for NYT credentials)
  - CUPS (for lp print command)
---

# NYT Crossword Auto-Print

This skill downloads the daily New York Times crossword puzzle PDF and sends it
to your network printer automatically each evening after the puzzle is published.

## Prerequisites

1. **NYT Subscription**: You must have an active NYT Games/Crossword subscription.
2. **`pass` (GNU Password Store)**: NYT credentials stored securely:
   - `pass insert nyt/email`
   - `pass insert nyt/password`
3. **Playwright + Chromium**:
   ```bash
   pip install playwright
   playwright install chromium
   ```
4. **CUPS**: Configured with your target printer. Verify with `lpstat -p`.
5. **Tailscale**: Printer accessible on the Tailscale network.

## Configuration

Edit `config.json` to set your printer name and preferences:

```json
{
  "printer_name": "HP_LaserJet",
  "copies": 1,
  "fit_to_page": true,
  "paused": false
}
```

Get your CUPS printer name by running `lpstat -p -d`.

## Cron Setup

Schedule the skill to run nightly at 9:10 PM Central:

```bash
openclaw cron add \
  --name "NYT Crossword Print" \
  --cron "10 21 * * *" \
  --tz "America/Chicago" \
  --session isolated \
  --message "Run the nyt-crossword-print skill: download and print today's crossword." \
  --deliver \
  --channel telegram
```

## Telegram Commands

- **Pause**: Tell the agent "pause crossword printing"
  - The agent should run: `python3 pause_resume.py pause`
- **Resume**: Tell the agent "resume crossword printing"
  - The agent should run: `python3 pause_resume.py resume`
- **Status**: Tell the agent "crossword printing status"
  - The agent should run: `python3 pause_resume.py status`

## How It Works

1. Checks the pause flag in `config.json` — skips if paused.
2. Retrieves NYT credentials from `pass`.
3. Launches headless Chromium via Playwright.
4. Logs into the NYT account (email → password flow).
5. Downloads the crossword PDF for today's date.
6. Sends the PDF to the configured CUPS printer via `lp`.
7. Reports success or failure. On failure, outputs an error message for
   Telegram delivery.

## Troubleshooting

- **Auth failures**: NYT may change their login flow. Check the login selectors
  in `fetch_and_print.py` and update if needed.
- **Printer offline**: Ensure the printer is reachable via Tailscale
  (`ping <printer-tailscale-ip>`) and registered in CUPS (`lpstat -p`).
- **PDF not available**: The puzzle publishes at 9 PM CT. The script retries
  up to 3 times with 60-second delays if the PDF is not yet available.
