#!/usr/bin/env python3
"""
Watch for the printer to come back online, then print a saved PDF.
Usage: python3 print_when_online.py <pdf_path>
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_and_print import check_printer_reachable, print_pdf_raw, load_config

POLL_INTERVAL = 60  # seconds between checks

def main():
    if len(sys.argv) < 2:
        print("Usage: print_when_online.py <pdf_path>", file=sys.stderr)
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        print(f"[error] PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    config = load_config()
    printer_ip = config.get("printer_ip")
    if not printer_ip:
        print("[error] No printer_ip in config.json", file=sys.stderr)
        sys.exit(1)

    print(f"[watcher] Waiting for printer at {printer_ip}:9100 to come online...")
    print(f"[watcher] Will print: {pdf_path.name}")
    print(f"[watcher] Checking every {POLL_INTERVAL}s. Ctrl-C to cancel.")
    sys.stdout.flush()

    while True:
        if check_printer_reachable(printer_ip):
            print(f"[watcher] Printer is online! Sending print job...")
            sys.stdout.flush()
            try:
                print_pdf_raw(pdf_path, printer_ip)
                print("[watcher] Done — crossword sent to printer.")
                sys.exit(0)
            except Exception as e:
                print(f"[watcher] Print failed: {e} — will retry next cycle.", file=sys.stderr)
        else:
            print(f"[watcher] Printer not reachable yet, retrying in {POLL_INTERVAL}s...")
            sys.stdout.flush()
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
