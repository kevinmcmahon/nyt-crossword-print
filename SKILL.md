---
name: nyt-crossword-print
description: >
  Automatically downloads the daily NYT crossword puzzle PDF and prints it
  to a network printer. Runs on a nightly schedule via cron. Supports
  pause/resume via Telegram and sends error alerts on failure.
version: 1.1.0
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
  - pymupdf (pip install pymupdf) — for block opacity post-processing
  - CUPS (for lp print command)
---

# NYT Crossword Auto-Print

This skill downloads the daily New York Times crossword puzzle PDF and sends it
to your network printer automatically each evening after the puzzle is published.

## Prerequisites

1. **NYT Subscription**: You must have an active NYT Games or All Access subscription
   (a basic News subscription does not include crossword access).
2. **NYT-S Cookie**: A valid `NYT-S` session cookie saved to `.nyt_cookies.json`.
   See [Authentication](#authentication) below.
3. **Playwright + Stealth + Chromium**:
   ```bash
   pip install playwright playwright-stealth
   playwright install chromium
   ```
4. **PyMuPDF** (for block opacity):
   ```bash
   pip install pymupdf
   ```
5. **CUPS**: Configured with your target printer. Verify with `lpstat -p`.
6. **Tailscale**: Printer accessible on the Tailscale network.

## What You Need to Configure

### 1. NYT-S Cookie (required)

The script authenticates using a saved `NYT-S` session cookie — there is no
automated login (NYT's DataDome bot detection blocks it).

To get your cookie: log into nytimes.com in a browser, open DevTools → Application
→ Cookies → `NYT-S`, and copy the value. Then save it:

```bash
cat > .nyt_cookies.json << 'EOF'
[{"name":"NYT-S","value":"YOUR_COOKIE_HERE","domain":".nytimes.com","path":"/","secure":true,"httpOnly":true,"sameSite":"None"}]
EOF
```

Sessions typically last several weeks. When the cookie expires, the script will
fail with a clear error message and you'll get a **Telegram notification** asking
you to provide a fresh cookie.

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

- **Print today's crossword**: "print the crossword"
  - Run: `python3 fetch_and_print.py`
- **Print a specific date**: "print the crossword for Feb 7, 2025"
  - Run: `python3 fetch_and_print.py --date 2025-02-07`
  - Convert whatever date format the user provides into `YYYY-MM-DD`
- **Pause**: "pause crossword printing"
  - Run: `python3 pause_resume.py pause`
- **Resume**: "resume crossword printing"
  - Run: `python3 pause_resume.py resume`
- **Status**: "crossword printing status"
  - Run: `python3 pause_resume.py status`

All commands must be run from the skill directory: `cd /home/openclaw/projects/nyt-crossword-print && .venv/bin/python ...`

## How It Works

1. Checks the pause flag in `config.json` — skips if paused.
2. Loads the saved `NYT-S` cookie from `.nyt_cookies.json`.
3. Launches headless Chromium via Playwright (with stealth mode).
4. Fetches today's puzzle ID from the NYT API.
5. Downloads the PDF using cookie authentication.
6. If `block_opacity` < 100, post-processes the PDF to lighten the black
   grid squares (edits the PDF content stream directly — text stays black).
7. Sends the PDF to the configured CUPS printer via `lp`.
8. Cleans up the downloaded PDF.

If the cookie has expired, the script exits with an error. Because the cron
job uses `--deliver --channel telegram`, you'll get a Telegram message telling
you to provide a fresh cookie.

## Authentication

NYT uses DataDome bot detection which blocks automated login attempts.
The script does **not** attempt to log in — it relies entirely on a saved
`NYT-S` session cookie.

Cookie state is stored in `.nyt_cookies.json` (gitignored). Sessions typically
last several weeks before expiring. When it expires:

1. You'll get a Telegram alert from the failed cron job.
2. Log into nytimes.com in a browser.
3. Copy the `NYT-S` cookie value from DevTools.
4. Update `.nyt_cookies.json` (or tell the agent your new cookie value).

## Troubleshooting

- **Cookie expired**: You'll see "Cookie expired" in the error output.
  Get a fresh `NYT-S` cookie from your browser and update `.nyt_cookies.json`.
- **Printer offline**: Ensure the printer is reachable via Tailscale
  (`ping <printer-tailscale-ip>`) and registered in CUPS (`lpstat -p`).
- **PDF not available**: The puzzle publishes at 9 PM CT. The script retries
  up to 3 times with 60-second delays if the PDF is not yet available.
