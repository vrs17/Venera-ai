""""Pro" byudjeti.

    GET /pro/quota   odamning qolgan "Pro" savollari

"Pro" - HAR XABAR uchun yoqiladigan rejim: yuqoridagi yordamchi tashqi
(hosted) modeldan maslahat oladi. Bu pulga tushadi, shuning uchun har bir
odamning kunlik / haftalik / oylik byudjeti bor (suriladigan oynalar).

KIMLIK SERVERDAN, `chat.py` dagi bilan AYNAN bir xil
(`assistant_user_id` -> `venera:{actorId}`): brauzer `user_id` yubormaydi
va yubora olmaydi, aks holda birovning byudjetini ko'rish mumkin bo'lardi.

CHEGARALAR QOTIRILMAYDI - ular shu endpointdan o'qiladi (hujjat talabi:
"read them from this endpoint, do not hard-code").
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from ...core.errors import error_status
from ...schemas.auth import AuthUser
from ...schemas.pro import ProQuota
from ...services.integrations.assistant import AssistantError
from . import chat as _chat
from ..deps import current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/pro", tags=["pro"])

#: Foydalanuvchiga ko'rinadigan xabarlar (ichki matnsiz, `chat.py` kabi).
_MESSAGES = {
    400: "So'rov qabul qilinmadi",
    404: "Byudjet topilmadi",
    422: "Byudjetni o'qib bo'lmadi",
    501: "Savol-javob xizmati hali sozlanmagan",
    503: "Savol-javob xizmati band, biroz kutib qayta urinib ko'ring",
    504: "Javob juda uzoq cho'zildi",
    502: "Savol-javob xizmati javob bermadi",
}


@router.get("/quota", response_model=ProQuota)
def quota(user: AuthUser = Depends(current_user)) -> ProQuota:
    """Qolgan "Pro" savollar - kiritish panelidagi hisoblagich uchun.

    `async def` EMAS: klient bloklaydigan `urllib` ishlatadi, FastAPI
    oddiy `def` ni threadpool'da bajaradi (`chat.py` dagi kabi).
    """
    try:
        result = _chat._assistant.pro_quota(user_id=_chat.assistant_user_id(user))
    except AssistantError as exc:
        log.warning("Pro byudjeti (%s): %s", user.email, exc)
        status = exc.status if exc.status in _MESSAGES else 502
        raise error_status(status, _MESSAGES[status]) from exc
    return ProQuota(**{k: v for k, v in result.items() if k in ProQuota.model_fields})
