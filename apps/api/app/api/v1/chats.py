"""Suhbatlar tarixi: ro'yxat, ochish, nomini o'zgartirish, o'chirish, tiklash.

    GET    /chats                    ro'yxat - oxirgi faollik bo'yicha, yangisi birinchi
    GET    /chats/{chat_id}          ochish - xabarlari bilan
    PATCH  /chats/{chat_id}          nomini o'zgartirish   {"title": "..."}
    DELETE /chats/{chat_id}          yumshoq o'chirish
    POST   /chats/{chat_id}/restore  o'chirishni bekor qilish

SUHBATLAR BU YERDA SAQLANMAYDI. Har suhbat yuqoridagi xizmatda turadi -
`POST /chat/stream` ga yuborilgan `chatId` bo'yicha (xotira ham shu kalit
bilan). Suhbatni yaratadigan endpoint yo'q: yangi `chatId` bilan birinchi
savol uni yaratadi. Bu fayl faqat proksi: brauzer -> Venera -> xizmat.

KIMLIK SERVERDAN, `chat.py` dagi bilan AYNAN bir xil (`assistant_user_id`,
ya'ni `venera:{actorId}`). Xizmat suhbatni `(ilova, user_id)` bo'yicha
ajratadi: boshqa odamning suhbat kalitini bilgan odam ham uni ocholmaydi,
404 oladi. Brauzer `user_id` ni yubormaydi va yubora olmaydi.

Mantiq `services/integrations/assistant.py` da, bu yerda faqat HTTP.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Path, Query

from ...core.errors import error_status
from ...schemas.auth import AuthUser
from ...schemas.chats import ChatDeleted, ChatDetail, ChatList, ChatRename, ChatSummary
from ...services.integrations.assistant import AssistantError
from . import chat as _chat
from ..deps import current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/chats", tags=["chats"])

#: Foydalanuvchiga ko'rinadigan xabarlar - status bo'yicha, ichki matnsiz
#: (`chat.py` dagi kabi: ichki host va sir bu yerga tushmaydi). 404 bu
#: yerda "suhbat": o'chirilgan, boshqa odamniki yoki umuman bo'lmagan -
#: uchalasi ham brauzer uchun bir xil, va shunday bo'lishi kerak.
_MESSAGES = {
    400: "So'rov qabul qilinmadi",
    404: "Suhbat topilmadi",
    422: "Suhbat nomi bo'sh yoki 80 belgidan uzun",
    501: "Savol-javob xizmati hali sozlanmagan",
    503: "Savol-javob xizmati band, biroz kutib qayta urinib ko'ring",
    504: "Javob juda uzoq cho'zildi",
    502: "Savol-javob xizmati javob bermadi",
}

_CHAT_ID = Path(max_length=128, description="Brauzer yaratgan suhbat kaliti (`chatId`)")


def _run(call, user: AuthUser, what: str, chat_id: str = ""):
    """Xizmatga boradi; xatoni jurnalga yozib, foydalanuvchi xabariga o'giradi."""
    try:
        return call()
    except AssistantError as exc:
        log.warning("Suhbat %s (%s%s): %s", what, user.email,
                    f", {chat_id}" if chat_id else "", exc)
        status = exc.status if exc.status in _MESSAGES else 502
        raise error_status(status, _MESSAGES[status]) from exc


@router.get("", response_model=ChatList)
def list_chats(
    limit: int = Query(50, ge=1, le=200, description="Sahifa hajmi"),
    offset: int = Query(0, ge=0, description="Sahifalash uchun siljish"),
    user: AuthUser = Depends(current_user),
) -> ChatList:
    """Odamning suhbatlari - yon panel uchun. O'chirilganlar ko'rinmaydi;
    bu imkoniyatdan OLDINGI suhbatlar ham chiqadi (birinchi xabaridan nom
    bilan).

    `async def` EMAS: klient bloklaydigan `urllib` ishlatadi, FastAPI oddiy
    `def` ni threadpool'da bajaradi (`chat.py` dagi kabi).
    """
    result = _run(
        lambda: _chat._assistant.list_chats(
            user_id=_chat.assistant_user_id(user), limit=limit, offset=offset),
        user, "ro'yxati",
    )
    return ChatList(
        items=result.get("items") or [],
        limit=result.get("limit", limit),
        offset=result.get("offset", offset),
    )


@router.get("/{chat_id}", response_model=ChatDetail)
def open_chat(
    chat_id: str = _CHAT_ID,
    limit: int = Query(200, ge=1, le=1000, description="Oxirgi nechta xabar"),
    user: AuthUser = Depends(current_user),
) -> ChatDetail:
    """Suhbatni ochish: nom va xabarlar (eskisi birinchi). Davom ettirish
    uchun o'sha `chatId` bilan `POST /chat/stream` - xotira xizmatda."""
    result = _run(
        lambda: _chat._assistant.get_chat(
            chat_id, user_id=_chat.assistant_user_id(user), limit=limit),
        user, "ochish", chat_id,
    )
    return ChatDetail(**result)


@router.patch("/{chat_id}", response_model=ChatSummary)
def rename_chat(
    body: ChatRename,
    chat_id: str = _CHAT_ID,
    user: AuthUser = Depends(current_user),
) -> ChatSummary:
    """Nomini o'zgartirish. Shundan keyin model nomni qayta yozmaydi."""
    result = _run(
        lambda: _chat._assistant.rename_chat(
            chat_id, user_id=_chat.assistant_user_id(user), title=body.title),
        user, "nomini o'zgartirish", chat_id,
    )
    log.info("Suhbat nomi (%s): %s", user.email, chat_id)
    return ChatSummary(**result)


@router.delete("/{chat_id}", response_model=ChatDeleted)
def delete_chat(chat_id: str = _CHAT_ID, user: AuthUser = Depends(current_user)) -> ChatDeleted:
    """YUMSHOQ o'chirish: ro'yxatdan chiqadi, ochilmaydi, lekin hech narsa
    yo'qolmaydi - `restore` yoki o'sha `chatId` bilan yangi savol qaytaradi.
    Takroriy chaqiruv ham 200."""
    result = _run(
        lambda: _chat._assistant.delete_chat(chat_id, user_id=_chat.assistant_user_id(user)),
        user, "o'chirish", chat_id,
    )
    log.info("Suhbat o'chirildi (%s): %s", user.email, chat_id)
    return ChatDeleted(**result)


@router.post("/{chat_id}/restore", response_model=ChatSummary)
def restore_chat(chat_id: str = _CHAT_ID, user: AuthUser = Depends(current_user)) -> ChatSummary:
    """O'chirishni bekor qilish - "Bekor qilish" tugmasi. 404: suhbat hech
    qachon bo'lmagan (yoki boshqa odamniki)."""
    result = _run(
        lambda: _chat._assistant.restore_chat(chat_id, user_id=_chat.assistant_user_id(user)),
        user, "tiklash", chat_id,
    )
    log.info("Suhbat tiklandi (%s): %s", user.email, chat_id)
    return ChatSummary(**result)
