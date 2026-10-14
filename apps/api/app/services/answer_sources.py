"""Javob ostidagi manbalar: odamga FAQAT hujjatlar ko'rsatiladi.

EGA QARORI (2026-10-14). Manba javobni hujjat bilan TEKSHIRISH uchun kerak:
"ichki qoidada rostdan shunday yozilganmi". HRM/CRM/DWH/Biznes 24/7/Superapp
so'rovlari (jonli ma'lumot) manba ro'yxatida ko'rinmaydi - ular hujjat emas,
odamga "T1" yoki "CRM · Vazifalar" qatori hech narsa bermaydi va har javob
ostida manba bloki chiqib turardi.

Hujjat deb hisoblanadi: ichki hujjat (`doc`), qonun moddasi (`law`, LEX.UZ) va
`[n]` raqami bilan iqtibos qilingan qo'llanma maqolasi (`biznes247_kb` va
`biznes247_help`). Qolgani - jonli so'rov.

Qoida veb (`chat/platforms.ts` `isLookupSource`) bilan BIR XIL; filtr SERVERDA,
mijozga ketishdan oldin turadi - veb, Mini App, Android va bot bitta joydan
tuzaladi, eski Android ilovasi ham yangilanmasdan to'g'ri ko'rsatadi. Admin izi
(`TurnRecorder`) filtrdan OLDIN yoziladi - u yerda hamma so'rov ko'rinaveradi.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Iterator
from typing import Any

log = logging.getLogger(__name__)

#: Jonli platformalar - doim so'rov (hujjat emas).
LIVE_PLATFORMS = frozenset({"hrm", "crm", "dwh", "biznes247", "superapp"})
#: Bilim platformalari - `[n]` raqami bilan kelsa qo'llanma maqolasi (hujjat),
#: raqamsiz kelsa so'rov.
KNOWLEDGE_PLATFORMS = frozenset({"biznes247_kb", "biznes247_help"})


def is_lookup(source: Any) -> bool:
    """Manba jonli so'rovmi (odamga ko'rsatilmaydi). Lug'at bo'lmasa - `True`
    (tanilmagan narsani ko'rsatgandan ko'ra yashirgan yaxshi)."""
    if not isinstance(source, dict):
        return True
    kind = str(source.get("kind") or "").lower()
    if kind in LIVE_PLATFORMS:
        return True
    if kind in KNOWLEDGE_PLATFORMS:
        return source.get("citation_index") is None
    # Turi yo'q, lekin vosita belgisi bor (`tool`, `T1`) va hujjat raqami yo'q - so'rov.
    if (source.get("tool") or source.get("marker")) and source.get("citation_index") is None:
        return True
    return False


def documents(items: Any) -> list[dict[str, Any]]:
    """Faqat hujjat manbalari (tartib saqlanadi)."""
    if not isinstance(items, list):
        return []
    return [item for item in items if not is_lookup(item)]


def _filter_line(line: bytes) -> bytes | None:
    """Bitta NDJSON qatori. `sources` kadri bo'lmasa - o'zgarmaydi. Hujjat
    qolmasa - kadr umuman yuborilmaydi (`None`)."""
    try:
        frame = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        return line
    if not isinstance(frame, dict) or frame.get("type") != "sources":
        return line
    changed = False
    for key in ("sources", "items"):
        if isinstance(frame.get(key), list):
            kept = documents(frame[key])
            changed = changed or len(kept) != len(frame[key])
            frame[key] = kept
    if not changed:
        return line
    if not any(frame.get(key) for key in ("sources", "items")):
        return None
    ending = b"\n" if line.endswith(b"\n") else b""
    return json.dumps(frame, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + ending


def only_documents(chunk: bytes) -> bytes:
    """Oqim bo'lagi (bir yoki bir necha NDJSON qatori) - `sources` kadrlaridan
    jonli so'rovlar olib tashlanadi. Boshqa kadrlar BAYTMA-BAYT o'zgarmaydi."""
    if b'"sources"' not in chunk:
        return chunk
    out: list[bytes] = []
    for line in chunk.splitlines(keepends=True):
        if b'"sources"' not in line or not line.strip():
            out.append(line)
            continue
        kept = _filter_line(line)
        if kept is not None:
            out.append(kept)
    return b"".join(out)


def client_view(chunks: Iterable[bytes]) -> Iterator[bytes]:
    """Mijozga ketadigan oqim: hujjat bo'lmagan manbalar olib tashlanadi.

    Ichki oqim (`TurnRecorder.wrap`) YOPILISHI SHART: klient uzilsa u
    `cancelled` deb yakunlaydi va yuqoridagi xizmat slotini qaytaradi. Shuning
    uchun `finally` da aniq `close()` - axlat yig'uvchiga ishonib o'tirmaymiz.
    """
    iterator = iter(chunks)
    try:
        for chunk in iterator:
            if not isinstance(chunk, (bytes, bytearray)):
                yield chunk
                continue
            filtered = only_documents(bytes(chunk))
            if filtered:
                yield filtered
    finally:
        close = getattr(iterator, "close", None)
        if callable(close):
            close()
