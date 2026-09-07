"""Parol xeshini yasaydi - `config/users.yaml` ga qo'yish uchun.

    cd apps/api
    python -m app.tools.hash_password

Parol ekranda KO'RINMAYDI (getpass) va tarixga tushmaydi. Xesh har safar
boshqacha chiqadi (tasodifiy salt) - bu normal.
"""

from __future__ import annotations

import getpass
import sys

from ..core.security import hash_password, verify_password


def main() -> int:
    password = getpass.getpass("Parol: ")
    if not password:
        print("Parol bo'sh - bekor qilindi", file=sys.stderr)
        return 1
    if password != getpass.getpass("Takrorlang: "):
        print("Parollar mos kelmadi", file=sys.stderr)
        return 1

    digest = hash_password(password)
    assert verify_password(password, digest), "xesh o'zini tekshirmadi"

    print("\nconfig/users.yaml ga quyidagini qo'ying:\n")
    print(f"    password_hash: \"{digest}\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
