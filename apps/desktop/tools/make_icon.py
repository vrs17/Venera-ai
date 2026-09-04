#!/usr/bin/env python3
"""Ilova ikonkalarini yaratadi - PyInstaller va installer uchun.

    python tools/make_icon.py

Natija:
    app.ico          Windows (.exe va installer)
    Venera.iconset/  macOS - `iconutil -c icns` uchun PNG'lar to'plami
    <state>.png      tray holatlari (ikkala platformada ham)

`.icns` ning o'zi shu yerda yasalmaydi: uni Mac'dagi `iconutil` yasaydi
(packaging/macos/build_macos.sh). Shunda ikkala platforma ham AYNAN bir xil
manba rasmdan kelib chiqadi.
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

    iconset = target / "Venera.iconset"
    icons.save_iconset(iconset)
    count = len(list(iconset.glob("*.png")))
    print(f"{iconset}  ({count} ta PNG - `iconutil -c icns` uchun)")

    for state in ("idle", "capturing", "thinking", "speaking", "paused"):
        png = target / f"{state}.png"
        icons.build(state).save(png)
        print(f"{png}  ({png.stat().st_size} bayt)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
