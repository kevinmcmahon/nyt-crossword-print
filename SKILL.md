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
  - playwright-stealth (pip install playwright-stealth) — required for NYT bot detection
  - pass (GNU password store, for NYT credentials)
  - CUPS (for lp print command)
---

# NYT Crossword Auto-Print

This skill downloads the daily New York Times crossword puzzle PDF and sends it
to your network printer automatically each evening after the puzzle is published.

## Prerequisites

1. **NYT Subscription**: You must have an active NYT Games or All Access subscription
   (a basic News subscription does not include crossword access).
2. **`pass` (GNU Password Store)**: NYT credentials stored securely:
   - `pass insert nyt/email`
   - `pass insert nyt/password`
3. **Playwright + Stealth + Chromium**:
   ```bash
   pip install playwright playwright-stealth
   playwright install chromium
   ```
   `playwright-stealth` is required to bypass NYT's DataDome bot detection.
4. **CUPS**: Configured with your target printer. Verify with `lpstat -p`.
5. **Tailscale**: Printer accessible on the Tailscale network.

## What You Need to Configure

### 1. NYT Credentials

```bash
pass insert nyt/email      # your NYT account email
pass insert nyt/password   # your NYT account password
```

### 2. Printer + Settings

Edit `config.json` — at minimum, set `printer_name` to match your CUPS printer:

```json
{
  "printer_name": "YOUR_PRINTER_NAME",
  "copies": 1,
  "fit_to_page": true,
  "block_opacity": 30,
  "paused": false
}
```

Find your CUPS printer name with `lpstat -p -d`.

| Field           | Purpose                                          |
| --------------- | ------------------------------------------------ |
| `printer_name`  | CUPS printer name — **you must set this**        |
| `copies`        | Number of copies to print                        |
| `fit_to_page`   | Scale PDF to fit the page                        |
| `block_opacity` | Black square darkness, 0 (white) to 100 (black)  |
| `paused`        | `true` to skip nightly prints                    |

## Cron Setup

Schedule the skill to run nightly at 9:05 PM Central:

```bash
openclaw cron add \
  --name "NYT Crossword Print" \
  --cron "5 21 * * *" \
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
3. Launches headless Chromium via Playwright (with stealth mode).
4. **Tries saved cookies first** — loads `.nyt_cookies.json` and attempts to
   download the PDF without logging in. This is faster and avoids bot detection.
5. **Falls back to full login** if cookies are missing or expired — performs the
   email/password flow, then saves the new cookies for next time.
6. Fetches today's puzzle ID from the NYT API and downloads the PDF.
7. Sends the PDF to the configured CUPS printer via `lp`.
8. Cleans up the downloaded PDF.

Cookie state is stored in `.nyt_cookies.json` (gitignored). The key auth cookie
is `NYT-S`. Sessions typically last several weeks before expiring.

## Troubleshooting

- **Auth failures**: Delete `.nyt_cookies.json` to force a fresh login.
  If that doesn't help, verify credentials with `pass show nyt/email` and
  `pass show nyt/password`. NYT may have changed their login flow — check
  if you can log in manually.
- **Bot detection / IP blocked**: The script uses `playwright-stealth` to avoid
  DataDome. Do **not** make non-stealth requests to `myaccount.nytimes.com`
  from the same IP — DataDome blocks aggressively (15+ minutes).
- **Printer offline**: Ensure the printer is reachable via Tailscale
  (`ping <printer-tailscale-ip>`) and registered in CUPS (`lpstat -p`).
- **PDF not available**: The puzzle publishes at 9 PM CT. The script retries
  up to 3 times with 60-second delays if the PDF is not yet available.
