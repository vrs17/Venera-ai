#!/usr/bin/env python3
"""version.json ni o'rnatuvchi faylдан yasaydi (Linux/macOS/Windows).

`packaging/publish.ps1` PowerShell'ga bog'liq va Windows'da ishlaydi: u
o'rnatuvchini YIG'ADI va manifestni yozadi. Linux serverda yig'ish mumkin
emas, lekin manifest yozish - mumkin. Shuning uchun ish taqsimoti:

    Windows   ->  .exe yig'adi          (packaging/build_setup.ps1)
    Linux     ->  version.json yozadi   (shu skript) va fayllarni tarqatadi

Ishlatish:

    python3 tools/make_manifest.py ../../release/Venera-AI-Assistant-Setup-0.2.3.exe
    python3 tools/make_manifest.py ../../release/...exe --notes "Nima o'zgardi"

Versiya fayl nomidan olinadi (Setup-X.Y.Z.exe). Nom boshqacha bo'lsa
--version bilan ko'rsating.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path

VERSION_IN_NAME = re.compile(r"(\d+\.\d+\.\d+)")
CHUNK = 1024 * 1024


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="version.json yasaydi")
    parser.add_argument("setup", type=Path, help="o'rnatuvchi .exe fayli")
    parser.add_argument("--version", default="", help="versiya (default: fayl nomidan)")
    parser.add_argument("--notes", default="", help="o'zgarishlar izohi")
    parser.add_argument("--mandatory", action="store_true", help="majburiy yangilanish")
    parser.add_argument("--min-version", default="", help="shundan eski versiyalar avval oraliqqa yangilansin")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="manifest yo'li (default: .exe yonidagi version.json)")
    args = parser.parse_args()

    setup: Path = args.setup
    if not setup.is_file():
        print(f"Xato: fayl topilmadi: {setup}", file=sys.stderr)
        return 1

    version = args.version.strip()
    if not version:
        match = VERSION_IN_NAME.search(setup.name)
        if not match:
            print("Xato: versiyani fayl nomidan aniqlab bo'lmadi, --version bering",
                  file=sys.stderr)
            return 1
        version = match.group(1)

    size = setup.stat().st_size
    print(f"  {setup.name}  ({size / 1048576:.1f} MB)")
    print("  sha256 hisoblanmoqda...")
    checksum = sha256_of(setup)

    manifest = {
        "version": version,
        "released": datetime.date.today().isoformat(),
        "notes": args.notes,
        "mandatory": bool(args.mandatory),
        "min_version": args.min_version,
        "setup": {"file": setup.name, "sha256": checksum, "size": size},
    }

    output = args.output or setup.parent / "version.json"
    # BOM'siz, LF bilan - nginx ham, mijoz ham shu ko'rinishni kutadi.
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8", newline="\n")

    print(f"\n  yozildi: {output}")
    print(f"    versiya : {version}")
    print(f"    sha256  : {checksum}")
    print(f"    hajm    : {size}")
    print("\n  Tarqatish tartibi MUHIM - avval .exe, keyin version.json:")
    print(f"    cp {setup.name} /var/www/venera/assistant/")
    print(f"    cp version.json  /var/www/venera/assistant/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
