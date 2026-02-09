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
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
DOWNLOAD_DIR = SCRIPT_DIR / "downloads"
COOKIE_PATH = SCRIPT_DIR / ".nyt_cookies.json"


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
# Cookie persistence
# ---------------------------------------------------------------------------
def _save_cookies(cookies: list[dict]):
    """Save browser cookies to disk for reuse across runs."""
    with open(COOKIE_PATH, "w") as f:
        json.dump(cookies, f)


def _load_cookies() -> list[dict] | None:
    """Load previously saved cookies, or return None."""
    if not COOKIE_PATH.exists():
        return None
    try:
        with open(COOKIE_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# NYT login + PDF download via Playwright
# ---------------------------------------------------------------------------
def _make_browser_context(p):
    """Create a stealth-configured browser context."""
    browser = p.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(
        viewport={"width": 1366, "height": 768},
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        accept_downloads=True,
    )
    return browser, context


def _nyt_login(page, email: str, password: str):
    """Perform the NYT email/password login flow."""
    print("[info] Navigating to NYT login page...")
    page.goto(
        "https://myaccount.nytimes.com/auth/enter-email"
        "?response_type=cookie&client_id=lgcl"
        "&redirect_uri=https://www.nytimes.com",
        wait_until="networkidle",
    )

    print("[info] Entering email...")
    email_input = page.wait_for_selector(
        'input[name="email"], input[type="email"]', timeout=15000
    )
    email_input.fill(email)

    submit_btn = page.query_selector(
        'button[type="submit"], button:has-text("Continue")'
    )
    if submit_btn:
        submit_btn.click()
    else:
        email_input.press("Enter")

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

    print("[info] Waiting for login to complete...")
    page.wait_for_load_state("networkidle", timeout=30000)
    time.sleep(2)


def _download_pdf(page, pdf_url: str, pdf_path: Path) -> bool:
    """Try to download the PDF. Returns True on success, False if auth expired."""
    try:
        with page.expect_download(timeout=30000) as download_info:
            page.evaluate("url => { window.location.href = url; }", pdf_url)
        download = download_info.value
        download.save_as(str(pdf_path))
        return True
    except Exception:
        # No download triggered — likely a 401/403 redirect to login
        return False


def _get_puzzle_id(page) -> tuple[int, str]:
    """Fetch today's daily puzzle ID and publication date from the NYT API."""
    resp = page.goto(
        "https://www.nytimes.com/svc/crosswords/v6/puzzle/daily.json",
        wait_until="load",
        timeout=15000,
    )
    if resp.status != 200:
        raise RuntimeError(f"Failed to fetch puzzle info (HTTP {resp.status})")
    data = resp.json()
    return data["id"], data.get("publicationDate", "unknown")


def download_crossword_pdf(email: str, password: str, config: dict) -> Path:
    """
    Download the crossword PDF, reusing saved cookies when possible.
    Falls back to a full login if cookies are missing or expired.
    """
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    block_opacity = config.get("block_opacity", 30)

    saved_cookies = _load_cookies()

    with Stealth().use_sync(sync_playwright()) as p:
        browser, context = _make_browser_context(p)

        # Try saved cookies first (skip login entirely)
        if saved_cookies:
            print("[info] Trying saved cookies...")
            context.add_cookies(saved_cookies)
            page = context.new_page()

            # Fetch puzzle ID from API
            puzzle_id, pub_date = _get_puzzle_id(page)
            pdf_url = f"https://www.nytimes.com/svc/crosswords/v2/puzzle/{puzzle_id}.pdf?block_opacity={block_opacity}"
            pdf_path = DOWNLOAD_DIR / f"crossword_{puzzle_id}.pdf"
            print(f"[info] Puzzle #{puzzle_id} ({pub_date})")
            print(f"[info] PDF URL: {pdf_url}")

            if _download_pdf(page, pdf_url, pdf_path):
                print(f"[info] PDF saved to {pdf_path} ({pdf_path.stat().st_size} bytes)")
                browser.close()
                return pdf_path
            print("[info] Saved cookies expired, logging in...")
            page.close()
            context.close()
            browser.close()
            browser, context = _make_browser_context(p)

        # Full login flow
        page = context.new_page()
        _nyt_login(page, email, password)

        # Save cookies for next time
        _save_cookies(context.cookies())

        # Fetch puzzle ID and download PDF
        puzzle_id, pub_date = _get_puzzle_id(page)
        pdf_url = f"https://www.nytimes.com/svc/crosswords/v2/puzzle/{puzzle_id}.pdf?block_opacity={block_opacity}"
        pdf_path = DOWNLOAD_DIR / f"crossword_{puzzle_id}.pdf"
        print(f"[info] Puzzle #{puzzle_id} ({pub_date})")
        print(f"[info] Downloading: {pdf_url}")

        if not _download_pdf(page, pdf_url, pdf_path):
            browser.close()
            raise RuntimeError(
                "Authentication failed. Login may have failed or "
                "subscription may not cover crosswords."
            )

        print(f"[info] PDF saved to {pdf_path} ({pdf_path.stat().st_size} bytes)")

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
            pdf_path = download_crossword_pdf(nyt_email, nyt_password, config)
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
