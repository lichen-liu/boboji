#!/usr/bin/env python3
"""Convert Google Maps Timeline JSON into Fog of World GPX; no install needed."""

from pathlib import Path
import sys

if sys.version_info < (3, 11):
    raise SystemExit("timeline_to_fog.py requires Python 3.11 or newer; invoke your installed Python 3.11+ explicitly.")

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from boboji.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
