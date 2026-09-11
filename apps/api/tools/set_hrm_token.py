#!/usr/bin/env python3
"""HRM token'ini `.env` ga yozadi. Qayta ishga tushirish KERAK EMAS.

HRM sessiyasi bir necha daqiqada tugaydi, ya'ni token kuniga o'n marta
almashadi. Shu sababli:

  * API tokenni `.env` dan HAR SO'ROVDA o'qiydi (`core/config.py`,
    `hrm_token_now`) - fayl o'zgargani `stat` bilan aniqlanadi, ya'ni
    diskka odatda borilmaydi ham;
  * demak bu vosita faqat FAYLNI yangilaydi va xizmatga tegmaydi. Restart
    ayni vaqtda oqib turgan javoblarni kesib yuborardi.

Ishlatish (apps/api ichidan):

    venv/bin/python tools/set_hrm_token.py 'eyJhbGciOi...'
    pbpaste | venv/bin/python tools/set_hrm_token.py -      # nusxadan
    venv/bin/python tools/set_hrm_token.py --show           # holatni ko'rish

Token EKRANGA CHIQMAYDI: faqat uzunligi, egasi va muddati ko'rsatiladi.
`.env` ning huquqlari (600) saqlanadi va yozish ATOMIK - yarim yozilgan
fayl tufayli boshqa sirlar yo'qolib qolmaydi.
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
import tempfile

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import _ENV_FILE, hrm_token_now  # noqa: E402
from app.services.integrations.assistant import token_seconds_left  # noqa: E402

KEY = "hrm_token"


def clean(raw: str) -> str:
    """Nusxa-ko'chirishda yopishib keladigan narsalarni oladi.

    `Bearer ` prefiksi, qo'shtirnoq, yangi qator va bo'sh joylar - hammasi
    juda oson yopishadi, va ularning har biri token'ni yaroqsiz qiladi.
    Xato faqat birinchi savolda ko'rinardi, "nega ishlamayapti" degan
    shaklda.
    """
    value = raw.strip().strip('"').strip("'").strip()
    for prefix in ("Bearer ", "bearer ", "Authorization: Bearer "):
        if value.startswith(prefix):
            value = value[len(prefix):].strip()
    return "".join(value.split())


def describe(token: str) -> str:
    if not token:
        return "token yo'q"
    left = token_seconds_left(token)
    parts = [f"{len(token)} belgi"]
    if left is None:
        parts.append("MUDDATI O'QILMADI (JWT emas?)")
    elif left <= 0:
        parts.append(f"MUDDATI TUGAGAN ({-left} s oldin)")
    else:
        parts.append(f"exp bo'yicha {left // 60} daq {left % 60} s qoldi")
    return ", ".join(parts)


def write(path: Path, token: str) -> None:
    """`.env` dagi `hrm_token` qatorini almashtiradi (yoki qo'shadi).

    ATOMIK: yangi mazmun yonidagi vaqtinchalik faylga yozilib, keyin
    `os.replace` bilan o'rniga qo'yiladi. To'g'ridan-to'g'ri yozishda
    xato yarim yozilgan `.env` qoldirardi - ya'ni `SECRET_KEY` va boshqa
    sirlar bilan birga.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        lines, mode = [], 0o600

    out: list[str] = []
    replaced = False
    for line in lines:
        name = line.split("=", 1)[0].strip().lower()
        if "=" in line and not line.lstrip().startswith("#") and name == KEY:
            if not replaced:
                out.append(f"{KEY}={token}")
                replaced = True
            # Takroriy qatorlar TASHLANADI: `.env` da ikki xil qiymat
            # qolsa, oxirgisi ustun bo'lib, tuzatgan odam boshqasini
            # ko'rib turib "nega o'zgarmadi" deb o'ylardi.
            continue
        out.append(line)
    if not replaced:
        if out and out[-1].strip():
            out.append("")
        out.append("# HRM sessiya token'i - `tools/set_hrm_token.py` yozadi.")
        out.append(f"{KEY}={token}")

    directory = path.parent
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=directory, prefix=".env.", suffix=".tmp", delete=False,
    )
    try:
        with handle:
            handle.write("\n".join(out).rstrip("\n") + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        # Huquqlar AVVAL, almashtirishdan oldin: aks holda fayl bir lahza
        # 600 dan kengroq huquq bilan o'z joyida turardi.
        os.chmod(handle.name, mode or 0o600)
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("token", nargs="?",
                        help="HRM JWT. `-` bo'lsa stdin'dan o'qiladi.")
    parser.add_argument("--show", action="store_true",
                        help="Faqat hozirgi holatni ko'rsatadi, yozmaydi.")
    args = parser.parse_args()

    if args.show or not args.token:
        current = hrm_token_now()
        print(f"{_ENV_FILE}\n  hozir: {describe(current)}")
        if not args.show:
            print("\nYozish uchun: venv/bin/python tools/set_hrm_token.py '<JWT>'",
                  file=sys.stderr)
            return 2
        return 0

    raw = sys.stdin.read() if args.token == "-" else args.token
    token = clean(raw)
    if not token:
        print("token bo'sh", file=sys.stderr)
        return 1
    if token.count(".") != 2:
        # To'xtatmaydi, faqat ogohlantiradi: format kutilmaganda o'zgarsa
        # vosita ishlashdan to'xtab qolmasligi kerak.
        print("OGOHLANTIRISH: bu JWT ga o'xshamaydi (uch qism yo'q)", file=sys.stderr)

    write(_ENV_FILE, token)
    print(f"yozildi: {_ENV_FILE}\n  {describe(token)}")
    # `hrm_token_now()` faylni qaytadan o'qiydi - ya'ni bu qator API
    # AYNI SHU qiymatni ko'rayotganini tasdiqlaydi.
    seen = hrm_token_now()
    print("  API ko'rayotgani:", "AYNI SHU token" if seen == token else "BOSHQA (!)")
    print("\nQayta ishga tushirish kerak emas - API .env ni har so'rovda o'qiydi.")
    if token.count(".") == 2 and (token_seconds_left(token) or 0) > 0:
        print("Tekshirish: curl -s http://127.0.0.1:8000/api/health | "
              "python3 -m json.tool | grep -i hrm_token")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
