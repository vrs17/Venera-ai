#!/usr/bin/env python3
"""Ilova ikonkasini (.ico) yaratadi - PyInstaller va installer uchun.

    python tools/make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venera.ui import icons  # noqa: E402


def main() -> int:
    target = Path(__file__).resolve().parents[1] / "src" / "venera" / "resources" / "icons"
    target.mkdir(parents=True, exist_ok=True)

    ico = target / "app.ico"
    icons.save_ico(ico)
    print(f"{ico}  ({ico.stat().st_size} bayt)")

    for state in ("idle", "capturing", "thinking", "speaking", "paused"):
        png = target / f"{state}.png"
        icons.build(state).save(png)
        print(f"{png}  ({png.stat().st_size} bayt)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
