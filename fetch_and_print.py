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


def _run_command(cmd: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    """Run a command with a bounded timeout and convert hangs to useful errors."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Command timed out after {timeout}s: {' '.join(cmd)}"
        ) from exc


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

    Uses PyMuPDF's drawing inspector to locate every black-filled shape and
    paints an opaque gray rectangle on top of each one.  This works
    regardless of whether the PDF uses RGB, grayscale, or CMYK fills, and
    also handles PDFs that encode the black squares as semi-transparent fills
    via ExtGState — Ghostscript's ljet4 PCL driver ignores PDF transparency
    and would render those as solid black without this step.

    opacity: 0 (white) to 100 (solid black).
    """
    if opacity >= 100:
        return

    import fitz

    # opacity=30 → 30% black → RGB gray = 1 - 0.30 = 0.70 (light gray)
    gray_val = 1.0 - opacity / 100.0
    gray_color = (gray_val, gray_val, gray_val)

    doc = fitz.open(str(pdf_path))
    modified = False

    for page in doc:
        drawings = page.get_drawings()
        black_fills = [
            d for d in drawings
            if d.get("fill") == (0.0, 0.0, 0.0) and d.get("rect") is not None
        ]
        if not black_fills:
            continue

        # Paint opaque gray rectangles over every black fill.  Drawing at the
        # end of the content stream means these land on top, covering the
        # original black (whether opaque or semi-transparent).
        shape = page.new_shape()
        for drawing in black_fills:
            shape.draw_rect(drawing["rect"])
        shape.finish(fill=gray_color, color=None, width=0)
        shape.commit()
        modified = True

    if modified:
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


def _download_pdf(context, pdf_url: str, pdf_path: Path) -> None:
    """Download the PDF or raise a specific failure reason."""
    try:
        response = context.request.get(pdf_url, timeout=30000)  # 30s timeout
        if response.status in (401, 403):
            raise RuntimeError(
                f"NYT auth failed while downloading PDF (HTTP {response.status}). "
                "Please provide a fresh NYT-S cookie value."
            )
        if response.status != 200:
            raise RuntimeError(f"Failed to download PDF (HTTP {response.status})")
        content_type = response.headers.get("content-type", "")
        if "pdf" not in content_type:
            raise RuntimeError(f"PDF download returned non-PDF content type: {content_type or 'unknown'}")
        pdf_path.write_bytes(response.body())
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"PDF download failed: {exc}") from exc


def _get_puzzle_id(page, date: str | None = None) -> tuple[int, str]:
    """Fetch puzzle ID and publication date from the NYT API.
    If date is given (YYYY-MM-DD), fetch that date's puzzle; otherwise today's.
    """
    if date:
        url = f"https://www.nytimes.com/svc/crosswords/v6/puzzle/daily/{date}.json"
    else:
        url = "https://www.nytimes.com/svc/crosswords/v6/puzzle/daily.json"
    try:
        resp = page.goto(url, wait_until="load", timeout=15000)
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch puzzle info: {exc}") from exc
    if resp is None:
        raise RuntimeError("Failed to fetch puzzle info: no response from NYT")
    if resp.status != 200:
        raise RuntimeError(f"Failed to fetch puzzle info (HTTP {resp.status})")
    try:
        data = resp.json()
        return data["id"], data.get("publicationDate", "unknown")
    except Exception as exc:
        raise RuntimeError(f"Failed to parse puzzle info response: {exc}") from exc


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
        browser = None
        context = None
        try:
            browser, context = _make_browser_context(p)
            context.add_cookies(cookies)
            page = context.new_page()

            puzzle_id, pub_date = _get_puzzle_id(page, date)
            pdf_url = f"https://www.nytimes.com/svc/crosswords/v2/puzzle/{puzzle_id}.pdf?block_opacity={block_opacity}"
            pdf_path = DOWNLOAD_DIR / f"crossword_{puzzle_id}.pdf"
            print(f"[info] Puzzle #{puzzle_id} ({pub_date})")

            _download_pdf(context, pdf_url, pdf_path)

            print(f"[info] PDF saved to {pdf_path} ({pdf_path.stat().st_size} bytes)")
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Browser download failed: {exc}") from exc
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass

    if block_opacity < 100:
        print(f"[info] Applying block opacity: {block_opacity}%")
        try:
            _apply_block_opacity(pdf_path, block_opacity)
        except Exception as exc:
            raise RuntimeError(f"Failed to apply block opacity: {exc}") from exc

    return pdf_path


# ---------------------------------------------------------------------------
# Printing via CUPS
# ---------------------------------------------------------------------------
def check_printer_reachable(printer_ip: str, port: int = 9100, timeout: int = 5) -> bool:
    """Return True if the printer's JetDirect port is reachable."""
    import socket
    try:
        with socket.create_connection((printer_ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def wake_printer(printer_ip: str, port: int = 9100, timeout: int = 5, wait: int = 15) -> None:
    """Poke the printer's raw port to wake it from sleep, then wait for it to come online."""
    import socket
    try:
        with socket.create_connection((printer_ip, port), timeout=timeout):
            pass
        print(f"[info] Printer at {printer_ip}:{port} responded — waiting {wait}s for it to wake up...")
    except OSError:
        print(f"[info] Printer at {printer_ip}:{port} is in deep sleep — waiting {wait}s for it to wake up...")
    time.sleep(wait)  # Always wait, regardless of initial connection result


def print_pdf_raw(pdf_path: Path, printer_ip: str, port: int = 9100, timeout: int = 60) -> None:
    """Convert PDF to PCL and send directly to printer via raw JetDirect (port 9100).
    Bypasses CUPS/IPP entirely — more reliable over Tailscale routing.

    _apply_block_opacity() replaces black fill values with actual gray fill values
    before this function is called, so Ghostscript's ljet4 sees real gray and
    renders correctly (it ignores PDF opacity/ExtGState entirely).
    """
    import socket
    import tempfile

    temp_file = tempfile.NamedTemporaryFile(suffix=".pcl", delete=False)
    temp_file.close()
    pcl_path = Path(temp_file.name)
    try:
        print(f"[info] Converting PDF to PCL...")
        result = _run_command(
            ["gs", "-dNOPAUSE", "-dBATCH", "-sDEVICE=ljet4",
             f"-sOutputFile={pcl_path}", str(pdf_path)],
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Ghostscript conversion failed: {result.stderr.strip()}")

        pcl_data = pcl_path.read_bytes()
        print(f"[info] Sending {len(pcl_data)} bytes to {printer_ip}:{port}...")

        with socket.create_connection((printer_ip, port), timeout=timeout) as sock:
            sock.sendall(pcl_data)

        print(f"[info] Raw PCL sent successfully.")
    finally:
        if pcl_path.exists():
            pcl_path.unlink()


def print_pdf(pdf_path: Path, printer_name: str, copies: int = 1, fit_to_page: bool = True,
              job_timeout: int = 120) -> None:
    """Send a PDF to a CUPS printer and verify the job completes."""

    cmd = ["lp", "-d", printer_name, "-n", str(copies)]
    if fit_to_page:
        cmd.extend(["-o", "fit-to-page"])
    cmd.append(str(pdf_path))

    print(f"[info] Printing: {' '.join(cmd)}")
    result = _run_command(cmd, timeout=30)

    if result.returncode != 0:
        raise RuntimeError(f"Print failed: {result.stderr.strip()}")

    submitted = result.stdout.strip()
    print(f"[info] Print job submitted: {submitted}")

    # Extract job number and poll until complete or timeout
    import re
    match = re.search(rf"({re.escape(printer_name)}-\d+)", submitted)
    if not match:
        print("[warn] Could not parse job number — skipping completion check.")
        return

    job_id = match.group(1)
    deadline = time.time() + job_timeout
    poll_interval = 5

    print(f"[info] Monitoring job {job_id} (timeout {job_timeout}s)...")
    while time.time() < deadline:
        time.sleep(poll_interval)

        # Check if job shows as completed
        check = _run_command(
            ["lpstat", "-W", "completed", "-l"],
            timeout=15,
        )
        if job_id in check.stdout:
            print(f"[info] Job {job_id} completed.")
            return

        # Check active job status
        active = _run_command(["lpstat", "-l"], timeout=15)
        if job_id in active.stdout:
            if any(s in active.stdout for s in ["aborted", "canceled"]):
                raise RuntimeError(
                    f"Print job {job_id} failed in CUPS. "
                    f"Printer may be offline or out of paper."
                )
            # Job still active (processing/processing-to-stop-point) — keep waiting
            continue

        # Job not in active or completed — check if printer is idle,
        # which means it processed the job even if CUPS lost track of it.
        printer_status = _run_command(["lpstat", "-p", printer_name], timeout=15)
        if "idle" in printer_status.stdout.lower():
            print(f"[info] Job {job_id} left queue and printer is idle — treating as success.")
            return

        print(f"[warn] Job {job_id} disappeared and printer is not idle — waiting...")

    # Timeout — but if the printer is idle, the job likely completed fine
    printer_status = _run_command(["lpstat", "-p", printer_name], timeout=15)
    if "idle" in printer_status.stdout.lower():
        print(f"[info] Monitoring timed out but printer is idle — treating as success.")
        return

    raise RuntimeError(
        f"Print job {job_id} did not complete within {job_timeout}s — printer may be stuck."
    )


def check_printer_status(printer_name: str) -> str:
    """Check CUPS printer status. Returns status string."""
    result = _run_command(
        ["lpstat", "-p", printer_name],
        timeout=15,
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
    # Unbuffered output so logs survive SIGTERM (exec captures line-by-line)
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
    parser = argparse.ArgumentParser(description="Download and print an NYT crossword.")
    parser.add_argument("--date", help="Puzzle date (YYYY-MM-DD). Defaults to today's puzzle.")
    args = parser.parse_args()

    max_retries = 2
    retry_delay_seconds = 10

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

    printer_ip = config.get("printer_ip")
    copies = config.get("copies", 1)
    print_max_retries = 3
    print_retry_delay = 15

    if not printer_ip:
        print("[error] Raw printing requires config.json printer_ip.", file=sys.stderr)
        sys.exit(1)

    # Wake printer from sleep first, then verify it's actually reachable.
    wake_printer(printer_ip)

    # Pre-flight: verify printer is reachable before bothering to download.
    # Retry a few times — printer may need extra time to wake from deep sleep.
    print(f"[info] Checking printer reachability at {printer_ip}:9100...")
    max_reach_attempts = 4
    reach_wait = 15
    reachable = False
    for reach_attempt in range(1, max_reach_attempts + 1):
        if check_printer_reachable(printer_ip):
            reachable = True
            break
        if reach_attempt < max_reach_attempts:
            print(f"[info] Printer not yet reachable (attempt {reach_attempt}/{max_reach_attempts}), waiting {reach_wait}s...")
            time.sleep(reach_wait)
    if not reachable:
        print(f"[error] Printer at {printer_ip}:9100 not reachable after {max_reach_attempts} attempts — may be offline or subnet route down.", file=sys.stderr)
        sys.exit(1)
    print(f"[info] Printer reachable.")

    # Clean up stale PDFs from previous failed runs.
    try:
        stale = [p for p in DOWNLOAD_DIR.glob("*.pdf") if p.stat().st_mtime < (time.time() - 86400)]
        for p in stale:
            p.unlink()
            print(f"[info] Cleaned up stale PDF: {p.name}")
    except OSError:
        pass

    # Download with retries
    pdf_path = None
    for attempt in range(1, max_retries + 1):
        try:
            print(f"[info] Download attempt {attempt}/{max_retries}...")
            pdf_path = download_crossword_pdf(config, args.date)
            break
        except Exception as e:
            err = str(e)
            print(f"[warn] Attempt {attempt} failed: {err}", file=sys.stderr)
            # Don't retry permanent failures (auth, not-found, cookie errors)
            if any(x in err for x in ["auth failed", "HTTP 401", "HTTP 403", "HTTP 404", "cookie"]):
                print(f"[error] Permanent failure, not retrying: {err}", file=sys.stderr)
                sys.exit(1)
            if attempt < max_retries:
                print(f"[info] Retrying in {retry_delay_seconds} seconds...")
                time.sleep(retry_delay_seconds)
            else:
                print(f"[error] All {max_retries} download attempts failed.", file=sys.stderr)
                sys.exit(1)

    # Print directly to JetDirect; this avoids CUPS job-state polling over slow Tailscale paths.
    for copy_number in range(1, copies + 1):
        if copies > 1:
            print(f"[info] Printing copy {copy_number}/{copies}...")
        for attempt in range(1, print_max_retries + 1):
            try:
                print_pdf_raw(pdf_path, printer_ip)
                break
            except Exception as e:
                print(f"[warn] Print attempt {attempt}/{print_max_retries} failed: {e}", file=sys.stderr)
                if attempt < print_max_retries:
                    print(f"[info] Retrying print in {print_retry_delay}s...")
                    time.sleep(print_retry_delay)
                else:
                    print(f"[error] All {print_max_retries} print attempts failed.", file=sys.stderr)
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
