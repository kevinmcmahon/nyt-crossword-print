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
echo "[1/4] Installing Python dependencies..."
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    uv venv "$SCRIPT_DIR/.venv"
    echo "  Created venv at $SCRIPT_DIR/.venv"
else
    echo "  Venv already exists, skipping creation."
fi

if ! "$SCRIPT_DIR/.venv/bin/python" -c "import playwright" 2>/dev/null; then
    uv pip install --python "$SCRIPT_DIR/.venv/bin/python" playwright
    echo "  Installed playwright."
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
echo "  ✅ Playwright + Chromium ready (venv: $SCRIPT_DIR/.venv)"
echo ""

# --- 2. Verify pass is available ---
echo "[2/4] Checking for GNU pass..."
if command -v pass &>/dev/null; then
    echo "  ✅ pass is installed."
else
    echo "  ❌ pass is not installed. Install it with: sudo apt install pass"
    echo "     Then initialize with: gpg --gen-key && pass init <your-gpg-id>"
    exit 1
fi

# Check if NYT credentials exist
if pass show nyt/email &>/dev/null 2>&1; then
    echo "  ✅ nyt/email found in pass."
else
    echo "  ⚠️  nyt/email not found. Store it with: pass insert nyt/email"
fi

if pass show nyt/password &>/dev/null 2>&1; then
    echo "  ✅ nyt/password found in pass."
else
    echo "  ⚠️  nyt/password not found. Store it with: pass insert nyt/password"
fi
echo ""

# --- 3. Verify CUPS and printer ---
echo "[3/4] Checking CUPS printer setup..."
if command -v lp &>/dev/null; then
    echo "  ✅ CUPS (lp) is available."
    echo "  Available printers:"
    lpstat -p 2>/dev/null || echo "    (no printers configured)"
    echo ""
    echo "  Set your printer name in: $SCRIPT_DIR/config.json"
else
    echo "  ❌ CUPS is not installed. Install with: sudo apt install cups"
    exit 1
fi
echo ""

# --- 4. Show cron command ---
echo "[4/4] Cron setup"
echo "  Add the nightly job with:"
echo ""
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
