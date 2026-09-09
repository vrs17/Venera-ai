#!/usr/bin/env python3
"""Uyg'otish so'zi jurnalini o'qiydi va moslashtirgichni baholaydi.

NEGA KERAK. "Aniq aytmasa uyg'onmaydi" degan shikoyatni faqat haqiqiy
transkriptlarni ko'rib hal qilish mumkin: model qanday yozayotgani ma'lum
bo'lmasa, qoidalarni sozlash taxmin bo'lib qoladi.

Eng foydali qismi - `--replay`: JURNALDAGI matnlarni HOZIRGI qoidalarga
qayta yuritadi va nima o'zgarishini ko'rsatadi. Qoidani o'zgartirib, avval
shu buyruqni ishlatib ko'ring: nechta o'tkazib yuborilgan holat tuzalgani
va nechta yangi noto'g'ri uyg'onish paydo bo'lgani darhol ko'rinadi.

Ishlatish (apps/api ichidan):

    venv/bin/python tools/wake_report.py                # umumiy ko'rinish
    venv/bin/python tools/wake_report.py --misses       # faqat uyg'onmaganlar
    venv/bin/python tools/wake_report.py --replay       # hozirgi qoidalar bilan
    venv/bin/python tools/wake_report.py --play <id>    # audioni eshitish
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.services.wake import is_wake_phrase  # noqa: E402


def rows(directory: Path) -> list[dict]:
    index = directory / "wake.jsonl"
    if not index.exists():
        return []
    out = []
    for line in index.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            # Bitta buzuq qator butun hisobotni to'xtatmasligi kerak.
            continue
    return out


def summary(entries: list[dict]) -> None:
    total = len(entries)
    woke = sum(1 for e in entries if e.get("matched"))
    print(f"Jami urinish : {total}")
    print(f"Uyg'ongan    : {woke}")
    print(f"Uyg'onmagan  : {total - woke}")
    if not total:
        return
    print("\nSabablar:")
    for reason, count in Counter(e.get("reason", "?") for e in entries).most_common():
        print(f"  {count:5d}  {reason}")
    print("\nEng ko'p uchragan transkriptlar:")
    for text, count in Counter(e.get("text", "") for e in entries).most_common(15):
        verdict = "✓" if is_wake_phrase(text)[0] else " "
        print(f"  {verdict} {count:4d}  {text!r}")


def listing(entries: list[dict], only_misses: bool) -> None:
    print(f"{'vaqt':<21} {'uyg':<4} {'sabab':<26} matn")
    print("-" * 100)
    for e in entries:
        if only_misses and e.get("matched"):
            continue
        mark = "HA" if e.get("matched") else "-"
        print(f"{e.get('at','')[:19]:<21} {mark:<4} {e.get('reason','')[:25]:<26} "
              f"{e.get('text','')!r}  [{e.get('id','')}]")


def replay(entries: list[dict]) -> None:
    """Jurnaldagi matnlarni HOZIRGI qoidalar bilan qayta baholaydi."""
    fixed, broken, same = [], [], 0
    for e in entries:
        was = bool(e.get("matched"))
        now, reason = is_wake_phrase(e.get("text", ""))
        if now == was:
            same += 1
        elif now:
            fixed.append((e, reason))
        else:
            broken.append((e, reason))

    print(f"O'zgarmagan            : {same}")
    print(f"Endi UYG'ONADI         : {len(fixed)}   <- tuzalgan holatlar")
    print(f"Endi UYG'ONMAYDI       : {len(broken)}  <- yo'qotilgan holatlar")
    for label, group in (("Endi uyg'onadi", fixed), ("Endi uyg'onmaydi", broken)):
        if not group:
            continue
        print(f"\n{label}:")
        for e, reason in group[:40]:
            print(f"  {e.get('text','')!r}  ({reason})  [{e.get('id','')}]")


def play(directory: Path, entries: list[dict], attempt_id: str) -> int:
    match = next((e for e in entries if e.get("id", "").startswith(attempt_id)), None)
    if not match:
        print(f"topilmadi: {attempt_id}", file=sys.stderr)
        return 1
    path = directory / match["audio"]
    print(f"{path}\n  matn   : {match.get('text','')!r}\n"
          f"  qaror  : {'uyg`ondi' if match.get('matched') else 'uyg`onmadi'} "
          f"({match.get('reason','')})")
    if not path.exists():
        print("  audio o'chirilgan (saqlash chegarasi)", file=sys.stderr)
        return 1
    for player in ("paplay", "aplay", "ffplay", "play"):
        try:
            subprocess.run([player, str(path)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return 0
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    print("  (pleyer topilmadi - faylni yuqoridagi yo'ldan oling)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, default=settings.wake_log_dir)
    parser.add_argument("--misses", action="store_true", help="faqat uyg'onmaganlar")
    parser.add_argument("--list", action="store_true", help="hamma urinishlar")
    parser.add_argument("--replay", action="store_true", help="hozirgi qoidalar bilan qayta baholash")
    parser.add_argument("--play", metavar="ID", help="audioni eshitish")
    args = parser.parse_args()

    entries = rows(args.dir)
    if not entries:
        print(f"jurnal bo'sh: {args.dir / 'wake.jsonl'}")
        return 0

    if args.play:
        return play(args.dir, entries, args.play)
    if args.replay:
        replay(entries)
    elif args.list or args.misses:
        listing(entries, only_misses=args.misses)
    else:
        summary(entries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
