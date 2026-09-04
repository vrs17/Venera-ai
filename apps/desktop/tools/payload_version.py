#!/usr/bin/env python3
"""PyInstaller onefile o'rnatuvchisi ICHIDAGI ilova versiyasini o'qiydi.

Nega kerak: build "0.2.9" deb yozishi, setup.log "OK" deyishi mumkin - lekin
ikkalasi ham arxiv ichidagi haqiqiy binarni tekshirmaydi. Bir marta shu sababli
0.2.8 deb nomlangan o'rnatuvchi ichida 0.2.5 ilovasi tarqatilgan.

    python3 payload_version.py <setup.exe>
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

MAGIC = b"MEI\014\013\012\013\016"
COOKIE = "!8sIIii64s"
COOKIE_LEN = struct.calcsize(COOKIE)
ENTRY = "!IIIIBc"
ENTRY_LEN = struct.calcsize(ENTRY)


def entries(data: bytes):
    pos = data.rfind(MAGIC)
    if pos < 0:
        raise SystemExit("PyInstaller arxivi topilmadi")
    _magic, pkg_len, toc_off, toc_len, _pyver, _lib = struct.unpack(
        COOKIE, data[pos:pos + COOKIE_LEN])
    # Arxiv boshi: cookie tugagan joydan paket uzunligini ayiramiz.
    base = pos + COOKIE_LEN - pkg_len
    cursor = base + toc_off
    end = cursor + toc_len
    while cursor < end:
        (size, offset, comp_size, uncomp_size, is_comp, type_code) = struct.unpack(
            ENTRY, data[cursor:cursor + ENTRY_LEN])
        name = data[cursor + ENTRY_LEN:cursor + size].rstrip(b"\0").decode("utf-8", "replace")
        yield name, base + offset, comp_size, is_comp, type_code
        cursor += size


def main() -> int:
    data = Path(sys.argv[1]).read_bytes()
    found = {}
    for name, offset, comp_size, is_comp, _type in entries(data):
        flat = name.replace("\\", "/")
        if flat.endswith("resources/VERSION"):
            blob = data[offset:offset + comp_size]
            if is_comp:
                blob = zlib.decompress(blob)
            found[flat] = blob.decode("utf-8", "replace").strip()
    if not found:
        print("resources/VERSION topilmadi", file=sys.stderr)
        return 1
    for name, version in sorted(found.items()):
        print(f"{version}\t{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
