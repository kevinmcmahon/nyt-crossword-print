# 🧩 NYT Crossword Print — OpenClaw Skill

Automatically downloads and prints the daily New York Times crossword puzzle
every evening. Designed to run as an OpenClaw skill with a nightly cron job.

## How It Works

Every night at **9:10 PM Central**, OpenClaw runs a Playwright-based script that:

1. Checks if printing is paused (skips if so)
2. Retrieves your NYT credentials from `pass`
3. Logs into nytimes.com via headless Chromium
4. Downloads the crossword PDF for today
5. Sends it to your printer via CUPS

On failure, you get a Telegram alert. On success, it's silent — you just find
the crossword on your printer.

## Prerequisites

- **Ubuntu 20.04+** (your OpenClaw instance)
- **Active NYT subscription that includes crossword access** (e.g., NYT Games or All Access — a basic News subscription alone does not include the crossword)
- **HP LaserJet** (or any CUPS-compatible printer) on your Tailscale network
- **OpenClaw** running with Telegram configured

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
  --cron "10 21 * * *" \
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
└── README.md            # This file
```

## Configuration

All state is managed via `config.json` in the skill directory:

| Field          | Purpose                                        |
| -------------- | ---------------------------------------------- |
| `printer_name` | CUPS printer name (default: `HP_LaserJet`)     |
| `copies`       | Number of copies to print (default: `1`)       |
| `fit_to_page`  | Scale PDF to fit page (default: `true`)        |
| `paused`       | Pause flag (`true` = skip nightly prints)      |

Downloaded PDFs are saved to `downloads/` temporarily and deleted after printing.

## Troubleshooting

**Auth failure**
- Verify credentials: `pass show nyt/email` and `pass show nyt/password`
- NYT may have changed their login flow — check if you can log in manually
- Re-run setup: `pass edit nyt/password`

**PDF download failure**
- Puzzle may not be published yet — it drops at 9 PM Central
- The URL pattern `MonDDYY` may have changed — check the NYT crossword site

**Printer error**
- Check printer status: `lpstat -t`
- Verify Tailscale connectivity: `ping <printer-tailscale-ip>`
- Check CUPS logs: `tail /var/log/cups/error_log`

**Playwright issues**
- Reinstall Chromium: `python3 -m playwright install chromium`
- Check for missing system deps: `python3 -m playwright install-deps`

## NYT URL Pattern

The crossword PDF URL follows this pattern:

```
https://www.nytimes.com/svc/crosswords/v2/puzzle/print/{MonDDYY}.pdf
```

Examples:
- `Feb0726.pdf` → February 7, 2026
- `Sep0224.pdf` → September 2, 2024
- `Dec2525.pdf` → December 25, 2025

This is not an official/documented API — it could change at any time.
