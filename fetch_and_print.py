#!/usr/bin/env python3
"""
NYT Crossword Print
Logs into NYT via Playwright, downloads the daily crossword PDF,
and sends it to a CUPS printer.
"""

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
DOWNLOAD_DIR = SCRIPT_DIR / "downloads"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def is_paused(config: dict) -> bool:
    return config.get("paused", False)


# ---------------------------------------------------------------------------
# Credentials from `pass`
# ---------------------------------------------------------------------------
def get_secret(key: str) -> str:
    """Retrieve a secret from the `pass` password store."""
    result = subprocess.run(
        ["pass", "show", key],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to retrieve secret '{key}' from pass: {result.stderr.strip()}")
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# NYT login + PDF download via Playwright
# ---------------------------------------------------------------------------
def download_crossword_pdf(email: str, password: str, target_date: datetime) -> Path:
    """
    Launch headless Chromium, log into NYT, and download the crossword PDF.
    Returns the path to the downloaded PDF file.
    """
    # Import here so the module can be loaded without playwright installed
    # (e.g., for pause/resume commands).
    from playwright.sync_api import sync_playwright

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # Date format for the PDF URL: e.g. "Feb0726" for Feb 07, 2026
    date_str = target_date.strftime("%b%d%y")
    pdf_url = f"https://www.nytimes.com/svc/crosswords/v2/puzzle/print/{date_str}.pdf"
    pdf_path = DOWNLOAD_DIR / f"crossword_{date_str}.pdf"

    print(f"[info] Target date: {target_date.strftime('%Y-%m-%d')}")
    print(f"[info] PDF URL: {pdf_url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        # ----- Step 1: Navigate to NYT login -----
        print("[info] Navigating to NYT login page...")
        page.goto(
            "https://myaccount.nytimes.com/auth/enter-email"
            "?response_type=cookie&client_id=lgcl"
            "&redirect_uri=https://www.nytimes.com",
            wait_until="networkidle",
        )

        # ----- Step 2: Enter email -----
        print("[info] Entering email...")
        email_input = page.wait_for_selector(
            'input[name="email"], input[type="email"]', timeout=15000
        )
        email_input.fill(email)

        # Click continue / submit
        submit_btn = page.query_selector(
            'button[type="submit"], button:has-text("Continue")'
        )
        if submit_btn:
            submit_btn.click()
        else:
            email_input.press("Enter")

        # ----- Step 3: Enter password -----
        print("[info] Entering password...")
        password_input = page.wait_for_selector(
            'input[name="password"], input[type="password"]', timeout=15000
        )
        password_input.fill(password)

        login_btn = page.query_selector(
            'button[type="submit"], button:has-text("Log In"), button:has-text("Sign In")'
        )
        if login_btn:
            login_btn.click()
        else:
            password_input.press("Enter")

        # Wait for login to complete
        print("[info] Waiting for login to complete...")
        page.wait_for_load_state("networkidle", timeout=30000)

        # Brief pause to ensure cookies are fully set
        time.sleep(2)

        # ----- Step 4: Download the PDF -----
        print(f"[info] Downloading crossword PDF...")

        # Use the page context (which has auth cookies) to download
        response = page.goto(pdf_url, wait_until="load", timeout=30000)

        if response is None:
            browser.close()
            raise RuntimeError(f"No response received for {pdf_url}")

        if response.status == 403 or response.status == 401:
            browser.close()
            raise RuntimeError(
                f"Authentication failed (HTTP {response.status}). "
                "Login may have failed or subscription may not cover crosswords."
            )

        if response.status == 404:
            browser.close()
            raise RuntimeError(
                f"Crossword PDF not found (HTTP 404). "
                f"The puzzle for {date_str} may not be published yet."
            )

        if response.status != 200:
            browser.close()
            raise RuntimeError(
                f"Unexpected HTTP status {response.status} when downloading PDF."
            )

        # Verify we actually got a PDF (not an HTML error page)
        content_type = response.headers.get("content-type", "")
        if "pdf" not in content_type.lower():
            browser.close()
            raise RuntimeError(
                f"Expected a PDF but received content-type: {content_type}. "
                "The download URL may have changed or login failed silently."
            )

        body = response.body()
        pdf_path.write_bytes(body)
        print(f"[info] PDF saved to {pdf_path} ({len(body)} bytes)")

        browser.close()

    return pdf_path


# ---------------------------------------------------------------------------
# Printing via CUPS
# ---------------------------------------------------------------------------
def print_pdf(pdf_path: Path, printer_name: str, copies: int = 1, fit_to_page: bool = True):
    """Send a PDF to a CUPS printer using the `lp` command."""

    cmd = ["lp", "-d", printer_name, "-n", str(copies)]
    if fit_to_page:
        cmd.extend(["-o", "fit-to-page"])
    cmd.append(str(pdf_path))

    print(f"[info] Printing: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"Print failed: {result.stderr.strip()}")

    print(f"[info] Print job submitted: {result.stdout.strip()}")


def check_printer_status(printer_name: str) -> str:
    """Check CUPS printer status. Returns status string."""
    result = subprocess.run(
        ["lpstat", "-p", printer_name],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not query printer '{printer_name}': {result.stderr.strip()}"
        )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    max_retries = 3
    retry_delay_seconds = 60

    # Load config
    try:
        config = load_config()
    except Exception as e:
        print(f"[error] Failed to load config: {e}", file=sys.stderr)
        sys.exit(1)

    # Check pause flag
    if is_paused(config):
        print("[info] Crossword printing is PAUSED. Skipping.")
        sys.exit(0)

    printer_name = config.get("printer_name", "HP_LaserJet")
    copies = config.get("copies", 1)
    fit_to_page = config.get("fit_to_page", True)

    # Get credentials
    try:
        nyt_email = get_secret("nyt/email")
        nyt_password = get_secret("nyt/password")
    except RuntimeError as e:
        print(f"[error] {e}", file=sys.stderr)
        sys.exit(1)

    # Determine today's date in Central Time
    # NYT publishes at 9 PM CT — if we're running after 9 PM CT,
    # we want tomorrow's date (the puzzle that just dropped).
    ct = ZoneInfo("America/Chicago")
    now_ct = datetime.now(ct)

    # The puzzle published at 9 PM CT is for the *next* calendar day.
    # e.g., the puzzle published Mon 9 PM is Tuesday's puzzle.
    # So if running at 9:10 PM Monday, we want Tuesday's date.
    if now_ct.hour >= 21:
        target_date = now_ct + timedelta(days=1)
    else:
        target_date = now_ct

    # Check printer is reachable
    try:
        status = check_printer_status(printer_name)
        print(f"[info] Printer status: {status}")
        if "disabled" in status.lower() or "not available" in status.lower():
            print(f"[error] Printer '{printer_name}' appears unavailable: {status}", file=sys.stderr)
            sys.exit(1)
    except RuntimeError as e:
        print(f"[error] {e}", file=sys.stderr)
        sys.exit(1)

    # Download with retries
    pdf_path = None
    for attempt in range(1, max_retries + 1):
        try:
            print(f"[info] Download attempt {attempt}/{max_retries}...")
            pdf_path = download_crossword_pdf(nyt_email, nyt_password, target_date)
            break
        except RuntimeError as e:
            print(f"[warn] Attempt {attempt} failed: {e}", file=sys.stderr)
            if attempt < max_retries:
                print(f"[info] Retrying in {retry_delay_seconds} seconds...")
                time.sleep(retry_delay_seconds)
            else:
                print(f"[error] All {max_retries} download attempts failed.", file=sys.stderr)
                sys.exit(1)

    # Print
    try:
        print_pdf(pdf_path, printer_name, copies, fit_to_page)
    except RuntimeError as e:
        print(f"[error] {e}", file=sys.stderr)
        sys.exit(1)

    # Cleanup: remove the downloaded PDF after printing
    try:
        pdf_path.unlink()
        print("[info] Cleaned up downloaded PDF.")
    except OSError:
        pass  # Not critical

    print("[success] Crossword downloaded and sent to printer.")


if __name__ == "__main__":
    main()
