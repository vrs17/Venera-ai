"""Yozuv amallari: yordamchi TAKLIF qiladi, odam tasdiqlaydi.

    POST /actions/{token}/confirm   bajarish
    POST /actions/{token}/cancel    rad etish
    GET  /actions/{token}           holat (keyinroq ochilgan ekran uchun)

Chat turi hech narsani o'zgartirmaydi: javob oqimida `proposal` kadri
keladi (kalit, nima o'zgaradi), va faqat odam "Tasdiqlash"ni bosganda shu
yo'l yuqoridagi xizmatga boradi. KIMLIK VA TOKEN SERVER TOMONIDAN:
`user_id` taklif qilinganda yuborilgan bilan bir xil (`venera:{actorId}`),
platforma tokeni esa `chat._live_tokens` dan - odamning o'zi ulagan
hisob. Brauzer ikkisini ham yubormaydi va yubora olmaydi.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Path

from ...core.errors import error_status
from ...schemas.actions import ActionResult
from ...schemas.auth import AuthUser
from ...services.integrations.assistant import AssistantError
from . import chat as _chat
from ..deps import current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/actions", tags=["actions"])

#: Foydalanuvchiga ko'rinadigan xabarlar. Chat'dagi ro'yxatdan farqi
#: 404 da: bu yerda u "hujjat" emas, "taklif" - 15 daqiqada muddati
#: tugaydi, va odam buni bilishi kerak.
_MESSAGES = {
    400: "Taklifni bajarib bo'lmadi",
    404: "Taklif topilmadi yoki muddati tugagan",
    422: "Taklifni bajarib bo'lmadi",
    501: "Savol-javob xizmati hali sozlanmagan",
    503: "Savol-javob xizmati band, biroz kutib qayta urinib ko'ring",
    504: "Javob juda uzoq cho'zildi",
    502: "Savol-javob xizmati javob bermadi",
}

_TOKEN = Path(max_length=128, description="Yordamchi bergan taklif kaliti")


def _run(call, user: AuthUser, token: str, what: str) -> ActionResult:
    try:
        result = call()
    except AssistantError as exc:
        log.warning("Amal %s (%s, %s): %s", what, user.email, token, exc)
        status = exc.status if exc.status in _MESSAGES else 502
        raise error_status(status, _MESSAGES[status]) from exc
    log.info("Amal %s (%s): token=%s holat=%s ok=%s", what, user.email, token,
             result.get("status"), result.get("ok"))
    return ActionResult(**{k: v for k, v in result.items() if k in ActionResult.model_fields})


def _user_id(user: AuthUser) -> str:
    # `chat.py` dagi bilan AYNAN bir xil: taklif shu id uchun qilingan va
    # xizmat faqat o'sha id dan tasdiq qabul qiladi.
    return f"venera:{user.actorId}"


@router.post("/{token}/confirm", response_model=ActionResult)
def confirm(token: str = _TOKEN, user: AuthUser = Depends(current_user)) -> ActionResult:
    """Taklifni BAJARISH. Faqat odam bosgandan keyin, faqat o'sha odam,
    bir marta, 15 daqiqa ichida - qolganini xizmat tekshiradi."""
    return _run(
        lambda: _chat._assistant.confirm_action(
            token, user_id=_user_id(user), tokens=_chat._live_tokens(user)),
        user, token, "tasdiqlash",
    )


@router.post("/{token}/cancel", response_model=ActionResult)
def cancel(token: str = _TOKEN, user: AuthUser = Depends(current_user)) -> ActionResult:
    """Taklifni RAD ETISH - endi tasdiqlab bo'lmaydi."""
    return _run(
        lambda: _chat._assistant.cancel_action(
            token, user_id=_user_id(user), tokens=_chat._live_tokens(user)),
        user, token, "rad etish",
    )


@router.get("/{token}", response_model=ActionResult)
def status(token: str = _TOKEN, user: AuthUser = Depends(current_user)) -> ActionResult:
    """Taklifning holati."""
    return _run(lambda: _chat._assistant.get_action(token), user, token, "holati")
