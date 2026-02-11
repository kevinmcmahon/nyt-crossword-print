#!/usr/bin/env bash
#
# setup.sh — One-time setup for the NYT Crossword Print skill.
# Run this on your OpenClaw Ubuntu instance.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "=== NYT Crossword Print — Setup ==="
echo ""

# --- 1. Python dependencies ---
echo "[1/3] Installing Python dependencies..."
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    uv venv "$SCRIPT_DIR/.venv"
    echo "  Created venv at $SCRIPT_DIR/.venv"
else
    echo "  Venv already exists, skipping creation."
fi

if ! "$SCRIPT_DIR/.venv/bin/python" -c "import playwright" 2>/dev/null; then
    uv pip install --python "$SCRIPT_DIR/.venv/bin/python" playwright playwright-stealth pymupdf
    echo "  Installed playwright, playwright-stealth, pymupdf."
else
    echo "  playwright already installed, skipping."
fi

CHROMIUM_DIR=$("$SCRIPT_DIR/.venv/bin/python" -m playwright install --dry-run chromium 2>/dev/null \
    | grep -m1 'Install location:' | awk '{print $NF}')
if [ -z "$CHROMIUM_DIR" ] || [ ! -d "$CHROMIUM_DIR" ]; then
    "$SCRIPT_DIR/.venv/bin/python" -m playwright install chromium
    echo "  Installed Chromium browser."
else
    echo "  Chromium already installed, skipping."
fi
echo "  Playwright + Chromium ready (venv: $SCRIPT_DIR/.venv)"
echo ""

# --- 2. Verify CUPS and printer ---
echo "[2/3] Checking CUPS printer setup..."
if command -v lp &>/dev/null; then
    echo "  CUPS (lp) is available."
    echo "  Available printers:"
    lpstat -p 2>/dev/null || echo "    (no printers configured)"
    echo ""
    echo "  Set your printer name in: $SCRIPT_DIR/config.json"
else
    echo "  CUPS is not installed. Install with: sudo apt install cups"
    exit 1
fi
echo ""

# --- 3. Check for NYT-S cookie ---
echo "[3/3] Checking for NYT-S cookie..."
if [ -f "$SCRIPT_DIR/.nyt_cookies.json" ]; then
    echo "  .nyt_cookies.json found."
else
    echo "  No .nyt_cookies.json found."
    echo "  You'll need to provide your NYT-S cookie. Log into nytimes.com,"
    echo "  open DevTools > Application > Cookies > NYT-S, then run:"
    echo ""
    echo "  cat > $SCRIPT_DIR/.nyt_cookies.json << 'EOF'"
    echo '  [{"name":"NYT-S","value":"YOUR_COOKIE_HERE","domain":".nytimes.com","path":"/","secure":true,"httpOnly":true,"sameSite":"None"}]'
    echo "  EOF"
fi
echo ""

# --- Cron setup ---
echo "Cron setup:"
echo "  openclaw cron add \\"
echo "    --name \"NYT Crossword Print\" \\"
echo "    --cron \"5 21 * * *\" \\"
echo "    --tz \"America/Chicago\" \\"
echo "    --session isolated \\"
echo "    --message \"Run the nyt-crossword-print skill: download and print today's crossword.\" \\"
echo "    --deliver \\"
echo "    --channel telegram"
echo ""

echo "=== Setup complete ==="
echo ""
echo "To test manually, run:"
echo "  cd $SCRIPT_DIR && .venv/bin/python fetch_and_print.py"
