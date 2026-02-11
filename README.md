# NYT Crossword Print

Automatically downloads and prints the daily New York Times crossword puzzle
every evening. Designed to run as an OpenClaw skill with a nightly cron job.

## How It Works

Every night at **9:05 PM Central**, OpenClaw runs a Playwright-based script that:

1. Checks if printing is paused (skips if so)
2. Loads your saved `NYT-S` session cookie
3. Fetches the puzzle ID and downloads the PDF
4. Lightens the black grid squares if `block_opacity` < 100 (saves toner)
5. Sends it to your printer via CUPS

On failure (including expired cookies), you get a Telegram alert. On success,
it's silent — you just find the crossword on your printer.

## Prerequisites

- **Ubuntu 20.04+** (your OpenClaw instance)
- **[uv](https://docs.astral.sh/uv/)** — Python package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **CUPS** — printing system
- **Active NYT subscription that includes crossword access** (e.g., NYT Games or All Access — a basic News subscription alone does not include the crossword)
- **HP LaserJet** (or any CUPS-compatible printer) on your Tailscale network
- **OpenClaw** running with Telegram configured

Install system dependencies:

```bash
sudo apt install -y cups

# Playwright's headless Chromium needs these system libraries
sudo apt install -y libatk1.0-0t64 libatk-bridge2.0-0t64 libatspi2.0-0t64 \
  libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2t64
```

## What You Need to Customize

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

Sessions typically last several weeks. When the cookie expires, you'll get a
Telegram notification asking you to provide a fresh one.

### 2. Printer Name (required)

Find your CUPS printer name:

```bash
lpstat -p -d
```

Then update `config.json` with the exact printer name:

```json
{
  "printer_name": "YOUR_PRINTER_NAME"
}
```

### 3. Cron Schedule (optional)

The default schedule is **9:05 PM Central** (5 minutes after the puzzle
publishes). Edit `cron-job.json` or the `openclaw cron add` command to change
the time or timezone.

## Quick Setup

```bash
# 1. Clone / copy the skill folder
cp -r nyt-crossword-print ~/.openclaw/skills/nyt-crossword-print

# 2. Run the interactive setup
chmod +x ~/.openclaw/skills/nyt-crossword-print/setup.sh
~/.openclaw/skills/nyt-crossword-print/setup.sh

# 3. Add the cron job to OpenClaw
openclaw cron add \
  --name "NYT Crossword Print" \
  --cron "5 21 * * *" \
  --tz "America/Chicago" \
  --session isolated \
  --message "Run the nyt-crossword-print skill: download and print today's crossword." \
  --deliver \
  --channel telegram

# 4. Restart the OpenClaw gateway
openclaw gateway restart
```

## Authentication

NYT uses DataDome bot detection which blocks automated login attempts.
The script does **not** attempt to log in — it relies entirely on a saved
`NYT-S` session cookie.

Cookie state is stored in `.nyt_cookies.json` (gitignored). When it expires:

1. You'll get a Telegram alert from the failed cron job.
2. Log into nytimes.com in a browser.
3. Copy the `NYT-S` cookie value from DevTools.
4. Update `.nyt_cookies.json` (or tell the agent your new cookie value).

## Telegram Commands

Once the skill is loaded, you can tell your OpenClaw agent:

| Command                        | Effect                                   |
| ------------------------------ | ---------------------------------------- |
| "Pause crossword printing"     | Stops the nightly job                    |
| "Resume crossword printing"    | Re-enables the nightly job               |
| "Print today's crossword"      | Manual print (ignores pause)             |
| "Crossword status"             | Shows active/paused + last run info      |

## Printer Setup (CUPS over Tailscale)

Your printer needs to be configured as a CUPS destination. If it supports IPP
(most modern HP LaserJets do):

```bash
# Add the printer (replace <TAILSCALE_IP> with your printer's IP)
lpadmin -p HPLaserJet -E \
  -v ipp://<TAILSCALE_IP>/ipp/print \
  -m everywhere

# Set as default
lpoptions -d HPLaserJet

# Test
echo "test page" | lp
```

If IPP doesn't work, you may need the full CUPS package and the HP driver:

```bash
sudo apt install cups hplip
# Then configure via http://localhost:631
```

## File Structure

```
nyt-crossword-print/
├── SKILL.md             # OpenClaw skill definition
├── fetch_and_print.py   # Main script (Playwright + CUPS)
├── pause_resume.py      # Pause / resume / status utility
├── config.json          # Printer config + pause flag
├── setup.sh             # One-time setup helper
├── cron-job.json        # OpenClaw cron job config (reference)
├── .nyt_cookies.json    # Saved auth cookies (gitignored, auto-generated)
├── .gitignore           # Excludes cookies, venv, downloads
└── README.md            # This file
```

## Configuration

All state is managed via `config.json` in the skill directory:

| Field          | Purpose                                        |
| -------------- | ---------------------------------------------- |
| `printer_name`  | CUPS printer name — set to your printer         |
| `copies`        | Number of copies to print (default: `1`)        |
| `fit_to_page`   | Scale PDF to fit page (default: `true`)         |
| `block_opacity` | Black square darkness 0-100 (default: `30`)     |
| `paused`        | Pause flag (`true` = skip nightly prints)       |

Downloaded PDFs are saved to `downloads/` temporarily and deleted after printing.

## Troubleshooting

**Cookie expired**
- You'll see "Cookie expired" in the error output (and a Telegram alert).
- Log into nytimes.com in a browser and copy the `NYT-S` cookie value.
- Update `.nyt_cookies.json` or tell the agent your new cookie.

**PDF download failure**
- Puzzle may not be published yet — it drops at 9 PM Central
- The NYT puzzle API may have changed — check the response from
  `https://www.nytimes.com/svc/crosswords/v6/puzzle/daily.json`

**Printer error**
- Check printer status: `lpstat -t`
- Verify Tailscale connectivity: `ping <printer-tailscale-ip>`
- Check CUPS logs: `tail /var/log/cups/error_log`

**Playwright issues**
- Reinstall Chromium: `python3 -m playwright install chromium`
- Check for missing system deps: `python3 -m playwright install-deps`

## How the PDF Download Works

The script fetches today's puzzle dynamically — no hardcoded date math:

1. Hits the NYT puzzle API to get today's puzzle ID:
   ```
   GET https://www.nytimes.com/svc/crosswords/v6/puzzle/daily.json
   ```
2. Downloads the PDF:
   ```
   GET https://www.nytimes.com/svc/crosswords/v2/puzzle/{puzzle_id}.pdf
   ```
3. If `block_opacity` < 100, edits the PDF content stream to lighten the
   black grid squares (the NYT API's `block_opacity` query parameter is
   broken, so this is done client-side with PyMuPDF).

These are undocumented NYT APIs — they could change at any time.
