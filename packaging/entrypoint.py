"""PyInstaller uchun kirish nuqtasi.

Nima uchun alohida fayl kerak: PyInstaller `__main__.py` ni to'g'ridan-to'g'ri
`__main__` moduli sifatida ishga tushiradi, natijada paket ichidagi nisbiy
importlar ("from . import ...") ishlamay qoladi:

    ImportError: attempted relative import with no known parent package

Bu fayl esa paketni oddiy import qiladi, shuning uchun nisbiy importlar joyida
qoladi. `python -m venera` bilan ishga tushirish ham o'zgarmaydi.
"""

from __future__ import annotations

import multiprocessing
import sys


def main() -> int:
    # PyInstaller bilan yig'ilgan ilovada bu qator bo'lmasa, subprocess
    # yaratilganda ilova o'zini qayta-qayta ishga tushirib yuboradi.
    multiprocessing.freeze_support()

    from venera.__main__ import main as run

    return run()


if __name__ == "__main__":
    sys.exit(main())
