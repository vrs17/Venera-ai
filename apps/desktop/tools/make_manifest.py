#!/usr/bin/env python3
"""version.json ni o'rnatuvchi fayllardan yasaydi (Linux/macOS/Windows).

Ish taqsimoti - har bir platforma O'Z mashinasida yig'iladi:

    Windows   ->  .exe   (packaging/windows/build_setup.ps1)
    macOS     ->  .dmg   (packaging/macos/build_macos.sh)
    Linux     ->  manifestni yozadi va fayllarni tarqatadi (shu skript)

Shuning uchun skript BIRLASHTIRIB ishlaydi: mavjud version.json o'qiladi va
faqat berilgan platformalar yangilanadi, qolganlari joyida qoladi. Aks holda
macOS build'i Windows yozuvini o'chirib yuborardi.

Ishlatish:

    # ikkala platforma birga
    python3 tools/make_manifest.py --windows ...Setup-0.2.4.exe --macos ...-0.2.4-universal.dmg

    # faqat macOS - mavjud windows yozuvi saqlanadi
    python3 tools/make_manifest.py --macos ...-0.2.4-universal.dmg -o release/version.json

    # eski uslub (pozitsion argument = --windows) hamon ishlaydi
    python3 tools/make_manifest.py release/Venera-AI-Assistant-Setup-0.2.4.exe

Versiya fayl nomidan olinadi (X.Y.Z). Nom boshqacha bo'lsa --version bering.
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
# ...-0.2.4-universal.dmg / ...-0.2.4-arm64.dmg -> arxitektura
ARCH_IN_NAME = re.compile(r"-(universal|arm64|x86_64)\.dmg$", re.IGNORECASE)
CHUNK = 1024 * 1024

# macOS uchun eng past OS - venera_macos.spec dagi LSMinimumSystemVersion bilan
# BIR XIL bo'lishi shart, aks holda sayt "11.0+" deb yozadi-yu ilova 12.0 talab qiladi.
MACOS_MIN_OS = "11.0"

# Fayllar qo'yiladigan papka. nginx konteyneri shuni read-only mount qiladi
# (apps/web/deploy/venera-frontend.user.service). Faqat chiqariladigan matn uchun -
# skript hech narsani ko'chirmaydi.
PUBLISH_DIR = "~/.local/share/venera/downloads"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def version_from_name(path: Path) -> str:
    match = VERSION_IN_NAME.search(path.name)
    return match.group(1) if match else ""


def describe_asset(path: Path) -> dict:
    size = path.stat().st_size
    print(f"  {path.name}  ({size / 1048576:.1f} MB)")
    print("    sha256 hisoblanmoqda...")
    return {"file": path.name, "sha256": sha256_of(path), "size": size}


def main() -> int:
    parser = argparse.ArgumentParser(description="version.json yasaydi (ko'p platformali)")
    parser.add_argument("setup", type=Path, nargs="?", default=None,
                        help="eski uslub: Windows o'rnatuvchisi (= --windows)")
    parser.add_argument("--windows", type=Path, default=None, help="Windows .exe")
    parser.add_argument("--macos", type=Path, default=None, help="macOS .dmg")
    parser.add_argument("--version", default="", help="versiya (default: fayl nomidan)")
    parser.add_argument("--notes", default="", help="o'zgarishlar izohi")
    parser.add_argument("--mandatory", action="store_true", help="majburiy yangilanish")
    parser.add_argument("--min-version", default="",
                        help="shundan eski versiyalar avval oraliqqa yangilansin")
    parser.add_argument("--drop-stale", action="store_true",
                        help="versiyasi mos kelmaydigan eski platforma yozuvlarini olib tashlash")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="manifest yo'li (default: birinchi fayl yonidagi version.json)")
    args = parser.parse_args()

    windows: Path | None = args.windows or args.setup
    macos: Path | None = args.macos
    if windows is None and macos is None:
        parser.error("kamida bittasi kerak: --windows yoki --macos")

    for label, path in (("--windows", windows), ("--macos", macos)):
        if path is not None and not path.is_file():
            print(f"Xato: fayl topilmadi ({label}): {path}", file=sys.stderr)
            return 1

    # --- versiya --------------------------------------------------------------
    version = args.version.strip()
    if not version:
        for path in (windows, macos):
            if path is not None:
                version = version_from_name(path)
                if version:
                    break
    if not version:
        print("Xato: versiyani fayl nomidan aniqlab bo'lmadi, --version bering",
              file=sys.stderr)
        return 1

    anchor = windows or macos
    assert anchor is not None
    output: Path = args.output or anchor.parent / "version.json"

    # --- mavjud manifestni o'qib, ustiga yozamiz ------------------------------
    existing: dict = {}
    if output.is_file():
        try:
            existing = json.loads(output.read_text(encoding="utf-8-sig"))
            if not isinstance(existing, dict):
                existing = {}
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Ogohlantirish: mavjud {output} o'qilmadi ({exc}) - noldan yoziladi",
                  file=sys.stderr)
            existing = {}

    platforms: dict = dict(existing.get("platforms") or {})

    if windows is not None:
        platforms["windows"] = describe_asset(windows)
    if macos is not None:
        entry = describe_asset(macos)
        arch = ARCH_IN_NAME.search(macos.name)
        entry["arch"] = arch.group(1).lower() if arch else "universal"
        entry["min_os"] = MACOS_MIN_OS
        platforms["macos"] = entry

    # --- versiya nomuvofiqligini tekshirish -----------------------------------
    # Bu eng oson qilinadigan xato: macOS 0.2.4 ni chiqarib, Windows 0.2.3 da
    # qolib ketish. Manifestdagi `version` HAMMA mijozga tegishli, ya'ni
    # Windows 0.2.3 "yangi versiya bor" deb o'sha 0.2.3 faylni qayta yuklaydi.
    stale = []
    for key, entry in list(platforms.items()):
        entry_version = version_from_name(Path(entry.get("file", "")))
        if entry_version and entry_version != version:
            stale.append((key, entry_version, entry.get("file", "")))
            if args.drop_stale:
                platforms.pop(key)

    manifest = {
        "version": version,
        "released": datetime.date.today().isoformat(),
        "notes": args.notes or existing.get("notes", ""),
        "mandatory": bool(args.mandatory),
        "min_version": args.min_version or existing.get("min_version", ""),
        "platforms": platforms,
    }

    # `setup` - eski mijozlar (0.2.3 va oldingilar) UCHUN. Ular `platforms` ni
    # bilmaydi va `setup` bo'lmasa umuman yangilana olmaydi. Shuning uchun u
    # Windows yozuvining nusxasi bo'lib qoladi. Windows yozuvi yo'q bo'lsa -
    # eskisi saqlanadi (o'chirilsa eski mijozlar yangilanishni yo'qotadi).
    if "windows" in platforms:
        manifest["setup"] = dict(platforms["windows"])
    elif existing.get("setup"):
        manifest["setup"] = existing["setup"]

    # BOM'siz, LF bilan - nginx ham, mijoz ham shu ko'rinishni kutadi.
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8", newline="\n")

    print(f"\n  yozildi: {output}")
    print(f"    versiya    : {version}")
    for key in sorted(platforms):
        entry = platforms[key]
        extra = f" [{entry['arch']}]" if entry.get("arch") else ""
        print(f"    {key:<10} : {entry['file']}{extra}  ({entry['size']} bayt)")
    if "setup" not in manifest:
        print("    setup      : YO'Q - eski Windows mijozlar yangilana olmaydi!")

    # `notes` foydalanuvchi yangilanish panelida KO'RADIGAN matn. --notes berilmasa
    # eskisi ko'chib o'tadi, ya'ni 0.2.3 ning izohi 0.2.4 uchun ko'rsatiladi.
    if not args.notes and existing.get("notes") and existing.get("version") != version:
        print(f"\n  ⚠️  --notes berilmadi: {existing.get('version')} ning izohi {version} ga"
              f" ko'chirildi", file=sys.stderr)
        print(f'       "{existing["notes"]}"', file=sys.stderr)
        print("       Bu matn foydalanuvchiga 'nima o'zgardi' deb ko'rsatiladi.",
              file=sys.stderr)

    if stale:
        print("\n  ⚠️  VERSIYA NOMUVOFIQLIGI:", file=sys.stderr)
        for key, entry_version, name in stale:
            state = "olib tashlandi" if args.drop_stale else "QOLDIRILDI"
            print(f"       {key}: {name} ({entry_version}) != manifest {version}  -> {state}",
                  file=sys.stderr)
        if not args.drop_stale:
            print("       Bu platformadagi mijozlar 'yangi versiya bor' deb ESKI faylni",
                  file=sys.stderr)
            print("       qayta yuklaydi. O'sha platformani ham qayta yig'ing yoki",
                  file=sys.stderr)
            print("       --drop-stale bilan yozuvni olib tashlang.", file=sys.stderr)

    print("\n  Tarqatish tartibi MUHIM - avval fayllar, keyin version.json:")
    for path in (windows, macos):
        if path is not None:
            print(f"    cp {path.name}  {PUBLISH_DIR}/")
    print(f"    cp version.json  {PUBLISH_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
