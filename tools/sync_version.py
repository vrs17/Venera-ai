#!/usr/bin/env python3
"""Versiyani bitta manbadan tarqatadi.

Yagona manba: `src/venera/__init__.py` dagi `__version__`.
Shu yerdan `resources/VERSION` fayliga yoziladi, chunki:
  * o'rnatuvchi (Setup.exe) ilova versiyasini shu fayldan biladi;
  * nashr skripti (publish.ps1) version.json ni shu qiymat bilan to'ldiradi.

    python tools/sync_version.py            # yozadi va chiqaradi
    python tools/sync_version.py 0.2.0      # avval __init__.py ni yangilaydi
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "src" / "venera" / "__init__.py"
VERSION_FILE = ROOT / "src" / "venera" / "resources" / "VERSION"
PYPROJECT = ROOT / "pyproject.toml"
PATTERN = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def read_version() -> str:
    match = PATTERN.search(INIT.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"__version__ topilmadi: {INIT}")
    return match.group(1)


def write_version(new_version: str) -> None:
    if not SEMVER.match(new_version):
        raise SystemExit(f"Versiya X.Y.Z ko'rinishida bo'lishi kerak: {new_version!r}")
    text = INIT.read_text(encoding="utf-8")
    INIT.write_text(PATTERN.sub(f'__version__ = "{new_version}"', text, count=1), encoding="utf-8")


def main() -> int:
    if len(sys.argv) > 1:
        write_version(sys.argv[1].strip().lstrip("v"))

    version = read_version()
    VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" - Windows'da ham LF yozilsin, aks holda WSL nusxasi bilan
    # farq qiladi va har build'dan keyin "o'zgargan fayl" bo'lib ko'rinadi.
    VERSION_FILE.write_text(version + "\n", encoding="utf-8", newline="\n")

    # pyproject.toml ham shu yerdan yangilanadi, aks holda paket metama'lumoti
    # __version__ dan orqada qolib ketadi va buni hech kim sezmaydi.
    if PYPROJECT.exists():
        text = PYPROJECT.read_text(encoding="utf-8")
        patched = re.sub(r'^version = "[^"]*"', f'version = "{version}"',
                         text, count=1, flags=re.MULTILINE)
        if patched != text:
            PYPROJECT.write_text(patched, encoding="utf-8")
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
