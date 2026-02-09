# 🧩 NYT Crossword Print — OpenClaw Skill

Automatically downloads and prints the daily New York Times crossword puzzle
every evening. Designed to run as an OpenClaw skill with a nightly cron job.

## How It Works

Every night at **9:05 PM Central**, OpenClaw runs a Playwright-based script that:

1. Checks if printing is paused (skips if so)
2. Retrieves your NYT credentials from `pass`
3. Logs into nytimes.com via headless Chromium
4. Downloads the crossword PDF for today
5. Sends it to your printer via CUPS

On failure, you get a Telegram alert. On success, it's silent — you just find
the crossword on your printer.

## Prerequisites

- **Ubuntu 20.04+** (your OpenClaw instance)
- **[uv](https://docs.astral.sh/uv/)** — Python package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **[pass](https://www.passwordstore.org/)** — GNU password manager, initialized with a GPG key
- **CUPS** — printing system
- **Active NYT subscription that includes crossword access** (e.g., NYT Games or All Access — a basic News subscription alone does not include the crossword)
- **HP LaserJet** (or any CUPS-compatible printer) on your Tailscale network
- **OpenClaw** running with Telegram configured

Install system dependencies:

```bash
sudo apt install -y pass cups

# Playwright's headless Chromium needs these system libraries
sudo apt install -y libatk1.0-0t64 libatk-bridge2.0-0t64 libatspi2.0-0t64 \
  libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2t64
```

Initialize `pass` (one-time, if not already done):

```bash
gpg --gen-key
pass init <your-gpg-id>
```

## What You Need to Customize

Before the skill will work, you need to configure these three things:

### 1. NYT Credentials (required)

Store your NYT email and password in `pass`:

```bash
pass insert nyt/email      # enter your NYT account email
pass insert nyt/password   # enter your NYT account password
```

These are read at runtime by the script — nothing is stored in plaintext.

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

## How Authentication Works

The script uses a two-tier approach to avoid logging in every run:

1. **Saved cookies (fast path)** — On the first successful login, browser
   cookies are saved to `.nyt_cookies.json` (gitignored, never committed).
   On subsequent runs, the script loads these cookies and attempts to download
   the PDF directly — no login page, no bot detection risk.

2. **Full login (fallback)** — If the saved cookies are missing or expired
   (NYT sessions typically last weeks), the script performs a full
   Playwright-based login using your `pass` credentials, then saves the new
   cookies for next time.

The key auth cookie is **`NYT-S`** — this is what grants access to subscriber
content. You never need to manage this manually; the script handles it.

**Bot detection:** The script uses `playwright-stealth` to avoid DataDome
bot detection on NYT. Do not make raw HTTP requests to `myaccount.nytimes.com`
from the same IP — DataDome will block it aggressively (15+ minutes).

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
  --message "Run the nyt-crossword-print skill: execute python3 ~/.openclaw/skills/nyt-crossword-print/fetch_and_print.py and report any errors to me." \
  --deliver \
  --channel telegram

# 4. Restart the OpenClaw gateway
openclaw gateway restart
```

## Credential Management

Credentials are stored with `pass` (GPG-encrypted at rest):

```bash
# View stored email
pass show nyt/email

# Update credentials
pass edit nyt/email
pass edit nyt/password
```

Cookie state is stored in `.nyt_cookies.json` (gitignored). If you run into
persistent auth issues, delete this file to force a fresh login:

```bash
rm .nyt_cookies.json
```

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

**Auth failure**
- Delete `.nyt_cookies.json` to force a fresh login: `rm .nyt_cookies.json`
- Verify credentials: `pass show nyt/email` and `pass show nyt/password`
- NYT may have changed their login flow — check if you can log in manually
- Re-run setup: `pass edit nyt/password`

**Bot detection / IP blocked**
- The script uses `playwright-stealth` to avoid DataDome. If you get blocked,
  wait 15+ minutes before retrying.
- Never make non-stealth requests to `myaccount.nytimes.com` from the same IP.

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
2. Constructs the PDF URL using the puzzle ID and your configured block opacity:
   ```
   https://www.nytimes.com/svc/crosswords/v2/puzzle/{puzzle_id}.pdf?block_opacity=30
   ```
3. Triggers the download via `window.location.href` (the PDF endpoint sends a
   browser download event, not a normal page response).

These are undocumented NYT APIs — they could change at any time.
