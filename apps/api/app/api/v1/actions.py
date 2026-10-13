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
from ...services.analytics import set_proposal_status
from ...services.analytics.recorder import PROPOSAL_STATUSES
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
    410: "Taklif muddati tugagan - savolni qayta bering va 15 daqiqa ichida tasdiqlang",
    422: "Taklifni bajarib bo'lmadi",
    501: "Savol-javob xizmati hali sozlanmagan",
    503: "Savol-javob xizmati band, biroz kutib qayta urinib ko'ring",
    504: "Javob juda uzoq cho'zildi",
    502: "Savol-javob xizmati javob bermadi",
}

#: Yuqoridagi xizmat taklifni "muddati o'tgan" deb javob beradigan holatlar: eskisi
#: 404 (taklifni tanimadi), 2026-10 dan esa aniq `410 {"code": "expired"}`. 410
#: ro'yxatda yo'qligida "Savol-javob xizmati javob bermadi" (502) chiqib, odam
#: xizmat buzilgan deb o'ylardi. Web va bot (`bot/runner.py`) shu bitta qoidadan.
EXPIRED_STATUSES = (404, 410)

_TOKEN = Path(max_length=128, description="Yordamchi bergan taklif kaliti")


def _run(call, user: AuthUser, token: str, what: str, verb: str | None = None) -> ActionResult:
    try:
        result = call()
    except AssistantError as exc:
        log.warning("Amal %s (%s, %s): %s", what, user.email, token, exc)
        if verb and exc.upstream_status == 409:
            settled = _settled(token, user)
            if settled is not None:
                return settled
        if verb and exc.status in EXPIRED_STATUSES:
            # Taklifning muddati o'tgan (15 daqiqa) - izda ham shunday.
            set_proposal_status(token, "expired")
            _meeting_item(user, token, "expired")
        status = exc.status if exc.status in _MESSAGES else 502
        raise error_status(status, _MESSAGES[status]) from exc
    log.info("Amal %s (%s): token=%s holat=%s ok=%s", what, user.email, token,
             result.get("status"), result.get("ok"))
    if verb:
        outcome = proposal_outcome(verb, result)
        if outcome:
            set_proposal_status(token, outcome)
            _meeting_item(user, token, outcome, result.get("result"))
    return ActionResult(**{k: v for k, v in result.items() if k in ActionResult.model_fields})


def _settled(token: str, user: AuthUser) -> ActionResult | None:
    """Tasdiq/rad etish 409 oldi: taklif ALLAQACHON yakunlangan (`already_executed` yoki
    `cancelled`) - haqiqiy holat qaytariladi, xato emas.

    NEGA. v4 ovozli suhbatda odam "ha" deb AYTADI va agent taklifni o'zi bajaradi
    (`assistant._V4_VOICE`), suhbatdagi karta esa tugmalari bilan qoladi. Keyin bosilgan
    "Tasdiqlash" 409 olib, foydalanuvchiga "Savol-javob xizmati javob bermadi" (502)
    ko'rinardi - vazifa esa CRMda ochilgan. Ikki qurilmadan bosilganda ham shu. Endi
    karta "Bajarildi" / "Rad etilgan" deydi. Ikkinchi yozuv BO'LMAYDI - agent 409 ni
    egalikni tekshirgandan keyin beradi va amalni qaytarmaydi.

    Holatni o'qib bo'lmasa (yoki u hali `pending`) - `None`: chaqiruvchi avvalgi xato yo'li."""
    try:
        view = _chat._assistant.get_action(token)
    except AssistantError as exc:
        log.warning("Amal holati o'qilmadi (%s, %s): %s", user.email, token, exc)
        return None
    status = view.get("status") if isinstance(view, dict) else None
    if status not in PROPOSAL_STATUSES or status == "pending":
        return None
    log.info("Amal allaqachon yakunlangan (%s): token=%s holat=%s", user.email, token, status)
    set_proposal_status(token, status)
    _meeting_item(user, token, status, view.get("result"))
    return ActionResult(**{k: v for k, v in view.items() if k in ActionResult.model_fields})


def _meeting_item(user: AuthUser, token: str, outcome: str, result: object = None) -> None:
    """Taklif yig'ilish vazifasidan kelgan bo'lsa (`POST /meetings/.../crm`) - vazifaning CRM
    holati ham yangilanadi. Bo'lim hech qachon yoqilmagan bo'lsa ombor yaratilmaydi, xato
    esa tasdiq javobiga ta'sir qilmaydi (`note_crm_outcome` o'zi ushlaydi)."""
    try:
        from ...services.meetings import service as _meetings

        _meetings.note_crm_outcome(user.actorId, token, outcome, result)
    except Exception:                                              # noqa: BLE001
        log.warning("Yig'ilish vazifasi CRM holati yangilanmadi", exc_info=True)


def proposal_outcome(verb: str, result: dict) -> str | None:
    """Tasdiqlash/rad etish natijasi -> savol izidagi taklif holati
    (`turns.proposal_status`): admin panel "taklif nima bo'ldi" deb ko'radi.

    Xizmat holatni o'zi aytsa - o'sha (`executed`, `failed`, ...); aytmasa
    `ok` bo'yicha. Bot ham shu funksiyani ishlatadi - ikki kanalda bir xil.
    """
    status = result.get("status")
    if isinstance(status, str) and status in PROPOSAL_STATUSES and status != "pending":
        return status
    if verb == "cancel":
        return "cancelled"
    if verb == "confirm":
        ok = result.get("ok")
        return "executed" if ok is True else ("failed" if ok is False else None)
    return None


def _user_id(user: AuthUser) -> str:
    # `chat.py` dagi bilan AYNAN bir xil: taklif shu id uchun qilingan va
    # xizmat faqat o'sha id dan tasdiq qabul qiladi.
    return _chat.assistant_user_id(user)


@router.post("/{token}/confirm", response_model=ActionResult)
def confirm(token: str = _TOKEN, user: AuthUser = Depends(current_user)) -> ActionResult:
    """Taklifni BAJARISH. Faqat odam bosgandan keyin, faqat o'sha odam,
    bir marta, 15 daqiqa ichida - qolganini xizmat tekshiradi."""
    return _run(
        lambda: _chat._assistant.confirm_action(
            token, user_id=_user_id(user), tokens=_chat._live_tokens(user)),
        user, token, "tasdiqlash", "confirm",
    )


@router.post("/{token}/cancel", response_model=ActionResult)
def cancel(token: str = _TOKEN, user: AuthUser = Depends(current_user)) -> ActionResult:
    """Taklifni RAD ETISH - endi tasdiqlab bo'lmaydi."""
    return _run(
        lambda: _chat._assistant.cancel_action(
            token, user_id=_user_id(user), tokens=_chat._live_tokens(user)),
        user, token, "rad etish", "cancel",
    )


@router.get("/{token}", response_model=ActionResult)
def status(token: str = _TOKEN, user: AuthUser = Depends(current_user)) -> ActionResult:
    """Taklifning holati."""
    return _run(lambda: _chat._assistant.get_action(token), user, token, "holati")
