#!/usr/bin/env python3
"""
Pause / Resume / Status utility for the NYT Crossword Auto-Print skill.
Usage:
    python3 pause_resume.py pause
    python3 pause_resume.py resume
    python3 pause_resume.py status
"""

import json
import sys
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_config(config: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("pause", "resume", "status"):
        print("Usage: pause_resume.py [pause|resume|status]")
        sys.exit(1)

    action = sys.argv[1]
    config = load_config()

    if action == "pause":
        config["paused"] = True
        save_config(config)
        print("✅ Crossword printing is now PAUSED. No puzzles will print until you resume.")

    elif action == "resume":
        config["paused"] = False
        save_config(config)
        print("✅ Crossword printing is now RESUMED. The next puzzle will print on schedule.")

    elif action == "status":
        paused = config.get("paused", False)
        printer = config.get("printer_name", "unknown")
        if paused:
            print(f"⏸️ Crossword printing is currently PAUSED. Printer: {printer}")
        else:
            print(f"▶️ Crossword printing is ACTIVE. Printer: {printer}")


if __name__ == "__main__":
    main()
