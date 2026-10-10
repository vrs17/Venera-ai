#!/usr/bin/env python3
"""Nom taxallusi: asosiy skript - `tools/meetings_live_check.py` (spetsifikatsiya 8.3 dagi nom).

Ikkala nom ham ishlaydi, chunki topshiriqda `meeting_live_check.py` deb aytilgan:

    venv/bin/python tools/meeting_live_check.py usage
"""

from __future__ import annotations

import runpy
import sys

from pathlib import Path

if __name__ == "__main__":
    sys.argv[0] = str(Path(__file__).with_name("meetings_live_check.py"))
    runpy.run_path(sys.argv[0], run_name="__main__")
