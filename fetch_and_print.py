#!/usr/bin/env python3
"""
NYT Crossword Print
Downloads the daily crossword PDF using saved NYT cookies and sends
it to a CUPS printer.  Requires a valid NYT-S cookie in .nyt_cookies.json.
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
# Cookie auth
# ---------------------------------------------------------------------------
def _load_cookies() -> list[dict]:
    """Load saved cookies or raise with an actionable message."""
    if not COOKIE_PATH.exists():
        raise RuntimeError(
            "No saved cookies found. Please provide a fresh NYT-S cookie:\n"
            f"  echo '[{{\"name\":\"NYT-S\",\"value\":\"<COOKIE>\",\"domain\":\".nytimes.com\",\"path\":\"/\",\"secure\":true,\"httpOnly\":true,\"sameSite\":\"None\"}}]' > {COOKIE_PATH}"
        )
    try:
        with open(COOKIE_PATH) as f:
            cookies = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Failed to read {COOKIE_PATH}: {exc}") from exc
    if not cookies:
        raise RuntimeError("Cookie file is empty. Please provide a fresh NYT-S cookie.")
    return cookies


# ---------------------------------------------------------------------------
# PDF post-processing
# ---------------------------------------------------------------------------
def _apply_block_opacity(pdf_path: Path, opacity: int) -> None:
    """Lighten the black grid squares in a crossword PDF.

    The NYT API ignores the block_opacity query parameter, so we
    post-process the PDF ourselves by editing the content stream
    directly.  Only the fill color preceding the square grid-cell
    rectangles (21.77 x 21.77 pt) is changed — text and borders
    stay black.

    opacity: 0 (white) to 100 (solid black).
    """
    if opacity >= 100:
        return  # nothing to do
    import re as _re

    import fitz

    gray_val = f"{1.0 - opacity / 100.0:.3f}"  # 30 → "0.700"
    doc = fitz.open(str(pdf_path))
    for page in doc:
        for xref in page.get_contents():
            stream = doc.xref_stream(xref)
            # Pattern: "0.000 g\n<coords> 21.77 -21.77 re B"
            # Replace the fill color only for these grid-cell rectangles.
            new_stream = _re.sub(
                rb"0\.000 g\n([\d.]+ [\d.]+ 21\.77 -21\.77 re B)",
                gray_val.encode() + b" g\n\\1",
                stream,
            )
            if new_stream != stream:
                doc.update_stream(xref, new_stream)
    doc.saveIncr()
    doc.close()


# ---------------------------------------------------------------------------
# NYT PDF download via Playwright
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


def _download_pdf(context, pdf_url: str, pdf_path: Path) -> bool:
    """Try to download the PDF. Returns True on success, False if auth expired."""
    try:
        response = context.request.get(pdf_url)
        if response.status != 200:
            return False
        content_type = response.headers.get("content-type", "")
        if "pdf" not in content_type:
            return False
        pdf_path.write_bytes(response.body())
        return True
    except Exception:
        return False


def _get_puzzle_id(page, date: str | None = None) -> tuple[int, str]:
    """Fetch puzzle ID and publication date from the NYT API.
    If date is given (YYYY-MM-DD), fetch that date's puzzle; otherwise today's.
    """
    if date:
        url = f"https://www.nytimes.com/svc/crosswords/v6/puzzle/daily/{date}.json"
    else:
        url = "https://www.nytimes.com/svc/crosswords/v6/puzzle/daily.json"
    resp = page.goto(url, wait_until="load", timeout=15000)
    if resp.status != 200:
        raise RuntimeError(f"Failed to fetch puzzle info (HTTP {resp.status})")
    data = resp.json()
    return data["id"], data.get("publicationDate", "unknown")


def download_crossword_pdf(config: dict, date: str | None = None) -> Path:
    """Download the crossword PDF using saved cookies.
    If date is given (YYYY-MM-DD), fetch that date's puzzle; otherwise today's.
    """
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    block_opacity = config.get("block_opacity", 100)

    cookies = _load_cookies()

    with Stealth().use_sync(sync_playwright()) as p:
        browser, context = _make_browser_context(p)
        context.add_cookies(cookies)
        page = context.new_page()

        puzzle_id, pub_date = _get_puzzle_id(page, date)
        pdf_url = f"https://www.nytimes.com/svc/crosswords/v2/puzzle/{puzzle_id}.pdf"
        pdf_path = DOWNLOAD_DIR / f"crossword_{puzzle_id}.pdf"
        print(f"[info] Puzzle #{puzzle_id} ({pub_date})")

        if not _download_pdf(context, pdf_url, pdf_path):
            browser.close()
            raise RuntimeError(
                "Cookie expired — could not download the crossword PDF.\n"
                "Please provide a fresh NYT-S cookie value."
            )

        print(f"[info] PDF saved to {pdf_path} ({pdf_path.stat().st_size} bytes)")
        browser.close()

    if block_opacity < 100:
        print(f"[info] Applying block opacity: {block_opacity}%")
        _apply_block_opacity(pdf_path, block_opacity)

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
    import argparse
    parser = argparse.ArgumentParser(description="Download and print an NYT crossword.")
    parser.add_argument("--date", help="Puzzle date (YYYY-MM-DD). Defaults to today's puzzle.")
    args = parser.parse_args()

    max_retries = 3
    retry_delay_seconds = 60

    # Load config
    try:
        config = load_config()
    except Exception as e:
        print(f"[error] Failed to load config: {e}", file=sys.stderr)
        sys.exit(1)

    # Check pause flag (skip for ad-hoc date requests)
    if not args.date and is_paused(config):
        print("[info] Crossword printing is PAUSED. Skipping.")
        sys.exit(0)

    printer_name = config.get("printer_name", "HP_LaserJet")
    copies = config.get("copies", 1)
    fit_to_page = config.get("fit_to_page", True)

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
            pdf_path = download_crossword_pdf(config, args.date)
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
