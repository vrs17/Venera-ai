"""Admin panel: "Tizim xaritasi" ma'lumoti. FAQAT ADMIN.

    GET /admin/osmap    `settings.osmap_path` dagi JSON (oqimlar, qadamlar,
                        kod parchalari, promptlar) - o'zgartirilmasdan

NEGA ENDPOINT, statik fayl EMAS. Faylda ICHKI PROMPTLAR so'zma-so'z va kod
parchalari bor (tizim qanday ishlashi, qaysi model, qaysi tekshiruv). `public/`
yoki nginx orqali berilsa, havolani bilgan har kim (kirmagan odam ham) uni
o'qiy olardi. Bu yerda esa router darajasida `require_roles("ADMIN")` -
`admin.py` dagi sabab bilan.

Fayl xarita yig'uvchisidan (`build.py`) qo'lda qo'yiladi. Yo'q yoki buzuq
bo'lsa - 404 / 503 va nima qilish kerakligi aytiladi: sahifa "bo'sh xarita"
ko'rsatib, adashtirmasin.

`async def` EMAS: diskdan o'qiydi (bloklaydi) - threadpool.
"""

from __future__ import annotations

import json
import logging
import threading

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from ...core.config import settings
from ...core.errors import error_status
from ..deps import require_roles

log = logging.getLogger(__name__)

admin_only = require_roles("ADMIN")

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(admin_only)])

#: Oxirgi o'qilgan fayl: (yo'l, mtime_ns, hajm) -> baytlar. Fayl ~1 MB, sahifa
#: har ochilganda qayta tahlil qilish (json.loads) bekor - o'zgarmagan bo'lsa
#: tekshirilgan baytlar qaytadi.
_cache: dict[str, tuple[tuple[str, int, int], bytes]] = {}
_lock = threading.Lock()


def _read_checked() -> bytes:
    path = settings.osmap_path
    try:
        info = path.stat()
    except FileNotFoundError:
        raise error_status(
            404,
            "Tizim xaritasi fayli yo'q. Uni serverda OSMAP_PATH ga (default "
            "apps/api/data/osmap/osmap.json) qo'ying - xarita yig'uvchisi (build.py) chiqargan osmap.json.",
        ) from None
    except OSError as exc:
        log.warning("Tizim xaritasi o'qilmadi: %s", exc)
        raise error_status(503, "Tizim xaritasi fayli o'qilmadi - keyinroq urinib ko'ring") from exc
    mark = (str(path), info.st_mtime_ns, info.st_size)
    with _lock:
        hit = _cache.get("osmap")
        if hit is not None and hit[0] == mark:
            return hit[1]
        try:
            raw = path.read_bytes()
            data = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            log.warning("Tizim xaritasi buzuq (%s): %s", path, type(exc).__name__)
            raise error_status(503, "Tizim xaritasi fayli buzuq (JSON emas) - uni qayta yig'ib qo'ying") from exc
        if not isinstance(data, dict) or not isinstance(data.get("flows"), list):
            raise error_status(503, "Tizim xaritasi faylida `flows` ro'yxati yo'q - uni qayta yig'ib qo'ying")
        _cache["osmap"] = (mark, raw)
        return raw


@router.get("/osmap", responses={200: {"content": {"application/json": {}}},
                                 404: {"description": "Fayl hali qo'yilmagan"}})
def get_osmap() -> Response:
    """Xarita JSON i - fayldagi baytlar o'zgarmasdan (tekshirilgan). Keshlanmaydi:
    ichida ichki promptlar bor, proksi yoki brauzer keshida qolmasin."""
    return Response(content=_read_checked(), media_type="application/json",
                    headers={"Cache-Control": "no-store"})
