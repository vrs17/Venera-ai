"""Telegram bot: xabarlarni olish (long polling) va javob berish.

OQIM (bitta savol):

    xabar/ovoz -> [ovoz bo'lsa: fayl -> STT -> "🎙 matn"] -> "⏳" xabari
      -> yuqoridagi xizmat oqimi (bosqich matni "⏳" da ko'rinadi)
      -> "⏳" o'chiriladi, javob YANGI xabar bo'lib keladi (bildirishnoma
         bilan - javob 15-40 s oladi va odam boshqa ishga o'tgan bo'ladi)
      -> manbalar tugmalari, taklif kartasi, ariza fayli

XABAR QANDAY KELADI. Ikki rejim (`settings.telegram_mode`):

  * `polling` - bot o'zi so'raydi (`getUpdates`, chiquvchi ulanish). JONLI
    TIZIMDA SHU. Boshqa nusxa shu tokenni o'qisa (409) - ulanish DARHOL
    qaytarib olinadi (`poll_error`).
  * `webhook` - Telegram xabarni o'zi `/api/v1/telegram/webhook` ga yuboradi
    va boshqa `getUpdates` o'quvchilarni rad etadi. O'LCHANGAN (2026-09-24):
    Telegram'ning serverimizga ulanishi ko'pincha birinchi urinishda
    "Connection timed out" bo'ladi va xabar 20 s - 2 daqiqa kechikadi
    (ovozli savol: yetkazish ~80 s, GAPI 1.6 s, javob 7 s). Tarmoq yo'li
    Venera'dan tashqarida - shuning uchun jonli tizim `polling` da. Webhook
    kodi qoladi: tarmoq tuzatilsa `.env` dagi bitta qator bilan yoqiladi.

NAVBAT. Bitta odamning xabarlari KETMA-KET ishlanadi (tartib saqlanadi:
`/new` dan keyingi savol haqiqatan yangi suhbatga tushadi), turli odamlar
esa parallel - `telegram_workers` ta ipgacha. Tugma bosishlar navbatsiz:
"Tasdiqlash" savol javobini kutib turmasligi kerak.

XATOLAR odamga veb ilovadagi xabarlar bilan aytiladi (`chat._MESSAGES`,
`stt._MESSAGES`, `actions._MESSAGES`) - ichki manzil yoki sir chiqmaydi.

KIRISH FAQAT MATN VA OVOZ (mikrofon). Video (kamera: dumaloq video, video
fayl) QABUL QILINMAYDI: yuklab olinmaydi, ko'rilmaydi va chatdan darhol
o'chiriladi. Kamera tugmasini Telegram ilovasi boshqaradi - bot uni
yashira olmaydi, shaxsiy chatda media cheklovi ham yo'q (`setChatPermissions`
faqat guruhlar uchun). Bot qila oladigani - qabul qilmaslik va o'chirish.

JURNAL: savol, transkript va javob MATNI yozilmaydi (shaxsiy ma'lumot) -
faqat `actorId`, uzunlik va natija.

ADMIN PANEL IZI esa veb chatdagi bilan bir xil (`services/analytics`):
har savol `turns` ga kanal `bot`, tur `bot` bilan yoziladi - kadrlar,
manbalar, vaqtlar va natija. Bu jurnal emas, ADMIN uchun ruxsatli ombor
(saqlash muddati `analytics_retention_days`).

JAVOB KO'RINISHI. Javob matni - qisqa; ostida izohlar ("📚 Manbalar":
faqat iqtibos qilinganlari, LEX.UZ - bosiladigan havola) va tugmalar:
ichki hujjat uchun "📄 Hujjatni ochish" (bosilganda IMZOLANGAN, 10
daqiqalik havola keladi - bank hujjati Telegram serverlariga yuklanmaydi)
va "⚑" - javob haqida xabar berish (veb ilovadagi AYNI shikoyat xizmati,
`services/reports.py`, kanal `bot`, chegara ham o'sha).

HR SAVOLLARI FAQAT SHAXSIY CHATDA. Javoblarda shaxsiy HR ma'lumoti bor:
guruhda bot HR/CRM savoliga javob bermaydi. Oddiy guruhda unga murojaat
qilinsa (buyruq, `@nom`, uning xabariga javob, guruhga qo'shilish) - bitta
qisqa "faqat shaxsiy chatda" izohi (`_GROUP_EVERY` da bir marta), qolgan
hammasi jim. RO'YXATDAGI guruhlarda (`telegram_groups`) esa yozishma
xulosasi va yozishma bo'yicha savol bor - `groups.py`; u HRM/CRM ga
murojaat qilmaydi.

"PRO" BOTDA YO'Q: savol har doim standart rejimda ketadi (`Backend.stream`).

BETA. Yangi mini app `/tg-beta/` da sinovda: `/beta` buyrug'i faqat ADMIN
rolidagilarga va `MINIAPP_BETA_LOGINS` dagilarga uning tugmasini beradi,
qolganlarga "bunday buyruq yo'q" - boshqa buyruqlardan farqi bilinmaydi.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
import urllib.parse

from collections import OrderedDict, deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..core.config import settings
from ..schemas.auth import AuthUser
from ..services import admin_users, analytics
from ..services.analytics import TurnRecorder, bind, redact, set_proposal_status
from ..services.integrations.assistant import AssistantError
from ..services.integrations.telegram import UPDATE_TYPES, TelegramApi, TelegramError
from ..services.stt import SttError, Transcript
from ..services.telegram_links import LinkStore, TelegramLink
from ..services.identities import Directory
from ..services.users import UserStore
from . import render
from .briefs import BTN_GROUPS, BriefService
from .group_actions import ONLY_OWNER, GroupActions
from .group_admin import GROUP_NOT_ENABLED, GROUP_PAUSED, GroupAdmin
from .groups import GroupAssistant
from .render import esc

log = logging.getLogger(__name__)

#: Bitta odamning navbatidagi eng ko'p xabar. Undan ortig'iga "kuting".
_QUEUE_LIMIT = 3
#: Ulanmagan odamga ko'rsatma shundan tez-tez takrorlanmaydi (soniya).
_HINT_EVERY = 60.0
#: "Faqat matn va ovoz" izohi shundan tez takrorlanmaydi: albomdagi o'nta
#: video o'nta izoh bo'lmasin (har biri baribir o'chiriladi).
_NOTE_EVERY = 10.0
#: Webhook holati shu oraliqda tekshiriladi (soniya).
_WEBHOOK_CHECK = 60.0
#: Telegram webhook'ga shuncha KETMA-KET tekshiruv davomida yetib bora
#: olmasa (yangi xato va navbatda xabar bor) - `polling` ga qaytiladi. 5
#: daqiqa: qayta ishga tushish paytidagi bir necha soniyalik uzilish buni
#: qo'zg'atmaydi - Telegram keyingi urinishda baribir yetkazadi.
_WEBHOOK_FAILS = 5
#: Telegram javobni olmay qolsa yangilanishni QAYTA yuboradi - shuncha
#: oxirgi `update_id` eslab qolinadi va takrori tashlanadi.
_SEEN_UPDATES = 2000
#: Bot faqat shu turdagi yangilanishlarni oladi (polling ham shu ro'yxat -
#: `TelegramApi.get_updates`). `edited_message` - faqat ro'yxatdagi guruhlar
#: uchun (`groups.py`); `my_chat_member` - bot guruhga qo'shildi/chiqarildi
#: (`group_admin.py`).
ALLOWED_UPDATES = list(UPDATE_TYPES)
#: Boshqa nusxa bilan to'qnashuvda (409) qayta so'rash oralig'i. Ikkinchi
#: nusxa har to'qnashuvdan keyin ~30 s kutadi, biz esa DARHOL qaytamiz - u
#: ulanishni atigi bir necha yuz millisekund ushlab turadi. Nol emas: u ham
#: darhol qaytsa, ikkalasi tarmoqni bosib qo'ymasin.
_CONFLICT_RETRY = 0.1
#: Bir daqiqada shundan ko'p to'qnashuv - ikkinchi nusxa ham shoshyapti:
#: sekinlashamiz (baribir yutib bo'lmaydi, faqat tarmoq to'ladi).
_CONFLICT_BURST = 30
_CONFLICT_SLOW = 2.0
#: "⏳" xabaridagi bosqich matni shundan tez yangilanmaydi.
_STAGE_EVERY = 1.5
#: "yozmoqda..." holati 5 s yashaydi - shundan oldin yangilanadi.
_TYPING_EVERY = 4.5
_TYPING_LIMIT = 180.0
#: Botdagi savol rejimi - har doim standart ("Pro" yo'q, `Backend.stream`).
BOT_MODE = "standard"
#: Ariza fayli uchun chegara (`assistant._MAX_FILE_BYTES` bilan bir xil):
#: undan katta fayl u yerda JIMGINA kesiladi, kesilgan hujjat yuborilmaydi.
_MAX_FILE = 25 * 1024 * 1024

#: Guruhdagi "faqat shaxsiy chatda" izohi bitta guruhga shundan tez
#: takrorlanmaydi (soniya): guruhda botni chaqiraverish shovqin bo'lmasin.
_GROUP_EVERY = 600.0
#: Javob kaliti -> (egasi, suhbat): "⚑" bosilganda egalikni tekshirish uchun.
#: Asosiy manba - analitika ombori (`turns`); bu xotiradagi nusxa analitika
#: o'chiq bo'lsa ham ishlashi uchun. Qayta ishga tushsa - faqat ombor.
_TURNS_KEPT = 2000

#: Bot menyusidagi buyruqlar (`setMyCommands`). `/beta` ATAYLAB yo'q - u
#: faqat sinovchilarga, menyuda esa hamma ko'radi. `/app`, `/chiqish`,
#: `/yangi` - eski nomlar, ishlayveradi, lekin menyuda yo'q.
COMMANDS = [
    {"command": "start", "description": "Barnoni ochish"},
    {"command": "new", "description": "Yangi suhbat"},
    {"command": "help", "description": "Bot nima qila oladi"},
    {"command": "logout", "description": "Hisobni botdan uzish"},
]
#: Bot profili - Telegram'da ko'rinadigan nom va tavsif (`setMyName`,
#: `setMyShortDescription`, `setMyDescription`). Username (@...) bu yerda
#: o'zgarmaydi. Chegaralar: nom <=64, qisqa tavsif <=120, tavsif <=512.
PROFILE = {
    "name": "Barno AI",
    "short_description": "Barno AI - HRM va CRM bo'yicha kompaniya yordamchisi.",
    "description": ("Salom! Men Barno AI - kompaniyaning HRM va CRM bo'yicha yordamchisiman. "
                    "Savolingizni yozing yoki ovozli xabar yuboring. Boshlash uchun /start ni "
                    "bosing va ish loginingiz bilan bir marta kiring."),
}

_INTRO = (
    "Salom! Men <b>Barno</b> - HRM va CRM bo'yicha yordamchiman.\n\n"
    "Boshlash uchun pastdagi tugma bilan Barnoni oching va ish loginingiz "
    "bilan <b>bir marta</b> kiring. Shundan keyin savollarni shu chatda "
    "yozaverasiz - qayta kirish so'ralmaydi."
)
#: Guruhda: bitta qisqa izoh, boshqa hech narsa.
_GROUP_ONLY = "Barno faqat shaxsiy chatda ishlaydi."
_UNKNOWN = "Bunday buyruq yo'q. Yordam: /help"
_BETA = (
    "🧪 Barno mini app'ining <b>yangi (beta)</b> versiyasi. Kamchilik ko'rsangiz, "
    "javob ostidagi ⚑ yoki ilovadagi «Xabar berish» orqali yozing."
)
_EXPIRED = (
    "Bot {days} kun ishlatilmagani uchun xavfsizlik maqsadida ulanish tugadi. "
    "Barno ilovasini ochib kiring - ulanish yangilanadi va shu yerda davom etasiz."
)
#: Admin panelda bloklangan hisob. Sabab va kim bloklagani AYTILMAYDI -
#: faqat nima qilish kerakligi.
_BLOCKED = "Hisobingiz bloklangan. Administratorga murojaat qiling."
#: 3-4 qator: bot nima qila oladi. Batafsili - ilovada.
_HELP = (
    "<b>Barno</b> - HRM va CRM bo'yicha yordamchi.\n\n"
    "• Savolni yozing yoki 🎙 ovozli xabar yuboring - qisqa javob va manbalari shu yerda.\n"
    "• HRM/CRM da o'zgartirish kerak bo'lsa, avval taklif ko'rsataman - faqat "
    "<b>Tasdiqlash</b> dan keyin bajariladi.\n"
    "• Javob noto'g'ri bo'lsa - ostidagi ⚑ tugmasi bilan xabar bering.\n\n"
    "/new - yangi suhbat · /start - Barnoni ochish · /logout - botdan chiqish"
)


def welcome_text(user: AuthUser, *, again: bool = False) -> str:
    """Ulangandan keyingi birinchi xabar (`again` - `/start` da takror)."""
    head = "Hisobingiz ulangan" if again else "Barno hisobingiz ulandi"
    return (
        f"✅ {head}: <b>{esc(user.fullName or user.email)}</b>\n\n"
        "Endi shu chatda savol yozing yoki 🎙 ovozli xabar yuboring - HRM va CRM "
        "bo'yicha javobni shu yerda beraman.\n\n"
        "/new - yangi suhbat · /help - yordam"
    )


def beta_logins() -> frozenset[str]:
    """`settings.miniapp_beta_logins` - kichik harfda (vergul/bo'shliq bilan)."""
    raw = str(getattr(settings, "miniapp_beta_logins", "") or "")
    return frozenset(part.strip().lower() for part in re.split(r"[,\s;]+", raw) if part.strip())


def beta_allowed(user: AuthUser, login: str | None) -> bool:
    """`/beta` shu odamga ochiqmi: ADMIN roli (samarali, `admin_users.access`
    dan) yoki `MINIAPP_BETA_LOGINS` da.

    `login` - SSO logini; berilsa FAQAT u solishtiriladi (emailni odam
    Keycloak'da o'zi o'zgartira oladi), `None` - `users.yaml` hisobi, u
    yerda email loginning o'zi (`admin_users.is_bootstrap` qoidasi).
    """
    if admin_users.ADMIN in user.roles:
        return True
    value = user.email if login is None else login
    return bool(value) and str(value).strip().lower() in beta_logins()


class Backend:
    """Bot ishlatadigan xizmatlar - API endpointlari ishlatadigan AYNI nusxalar.

    NEGA ALOHIDA NUSXA EMAS. CRM agent sessiyasi va foydalanuvchi
    ulanishlari `refresh_token` ni ROTATSIYA qiladi: ikkinchi nusxa
    birinchisining tokenini bekor qilib qo'yardi (`chat._crm` izohi). Yuqori
    xizmat va STT navbatlari (semaforlar) ham umumiy bo'lishi kerak - bot
    veb ilovaning ulushini ikki baravar qilib yubormasin.

    Testlar shu sinfni soxtasi bilan almashtiradi.
    """

    def stream(self, question: str, user: AuthUser, chat_id: str):
        from ..api.v1 import chat as _chat

        # Web va mini app bilan BITTA yo'l: xodimlar ma'lumotnomasi, keyin yordamchi.
        # Dvigatel - SHU ODAMNING `bot` kanalidagisi (`effective_engine`):
        # admin unga alohida versiya bergan bo'lsa o'sha, bo'lmasa bot
        # kanali siyosati, oxiri `.env`. Botda tanlov tugmasi yo'q - odam
        # o'z default'ida (`engine=None`).
        #
        # "PRO" BOTDA YO'Q - ATAYLAB va ochiq yozilgan (`BOT_MODE`): har Pro
        # savol pulga tushadi va odamning byudjetidan yeydi, botda esa
        # uni tanlash, qolganini ko'rsatish va "Pro javob" belgisi yo'q.
        # Default'ga tayanilmaydi - `open_stream` default'i o'zgarsa ham
        # bot standart rejimda qolsin (`test_bot_ux.py` tekshiradi).
        return _chat.open_stream(question, user, chat_id, channel="bot", mode=BOT_MODE,
                                 engine=None)

    def engine(self, user: AuthUser | None = None) -> str:
        """Bot kanalining dvigateli (shu odam uchun) - savol izi uchun
        (`_collect`). Odamsiz - "hamma uchun" qiymat."""
        from ..api.v1 import chat as _chat

        return _chat.effective_engine(user, "bot")

    def stream_group(self, question: str, user: AuthUser, chat_id: str):
        """Guruhdagi CRM so'rovi (`group_actions.py`): shaxsiy chatdagi AYNI yo'l, lekin
        FAQAT odamning O'Z CRM tokeni bilan - HRM yo'q (javob guruhdagi hammaga
        ko'rinadi), umumiy agent hisobi yo'q (vazifa so'ragan odam nomidan). `audience` -
        v4 da agent o'zi ham guruh deb biladi: shaxsiy xotira va `work_activity` yo'q."""
        from ..api.v1 import chat as _chat

        return _chat.open_stream(question, user, chat_id, channel="bot", mode=BOT_MODE, engine=None,
                                 platforms=("crm",), own_tokens=True, audience="group")

    def own_crm(self, user: AuthUser) -> bool:
        """Odamning O'Z CRM ulanishi bormi (guruhda CRM so'rovi sharti)."""
        from ..api.v1 import chat as _chat

        return _chat.has_own_crm(user)

    def own_crm_token(self, user: AuthUser) -> str | None:
        """Odamning O'Z CRM tokeni (guruh CRM v4 so'rovi uchun) - umumiy hisob emas."""
        from ..api.v1 import chat as _chat

        return _chat._connectors.hub.tokens(str(user.actorId)).get("crm") or None

    def agent_user_id(self, user: AuthUser) -> str:
        """Agentdagi kimlik (`venera:{actorId}`) - guruh CRM suhbati shu kalit bilan
        yoziladi va keyin o'chiriladi (`group_actions.sweep`)."""
        from ..api.v1 import chat as _chat

        return _chat.assistant_user_id(user)

    def forget_chat(self, chat_id: str, user_id: str) -> None:
        """Guruh CRM suhbatini agentda o'chirish (2026-10-10, F0 maxfiylik): ichida
        guruhdagi boshqa odamlarning xabarlari bor - guruh o'chirilganda, saqlash
        muddati yoki suhbat muddati tugaganda. Agent v4 `chat_purge` ni e'lon qilgan bo'lsa -
        HAQIQIY o'chirish (kvitansiya bilan); aks holda avvalgidek yumshoq (W1, 2026-10-11)."""
        from ..api.v1 import chat as _chat
        from ..services.brain import routing as _brain

        if _brain.purge_chat(chat_id, user_id) is not None:
            return
        _chat._assistant.delete_chat(chat_id, user_id=user_id)

    def action(self, verb: str, token: str, user: AuthUser, *, own_tokens: bool = False) -> dict[str, Any]:
        """Taklifni tasdiqlash / rad etish. `own_tokens` - guruhdagi taklif: faqat
        odamning o'z CRM tokeni (u qanday yaratilgan bo'lsa, shunday)."""
        from ..api.v1 import chat as _chat

        call = _chat._assistant.confirm_action if verb == "confirm" else _chat._assistant.cancel_action
        if own_tokens:
            tokens = {k: v for k, v in _chat._connectors.hub.tokens(str(user.actorId)).items() if k == "crm"}
        else:
            tokens = _chat._live_tokens(user)
        return call(token, user_id=_chat.assistant_user_id(user), tokens=tokens)

    def artifact(self, token: str, kind: str):
        from ..api.v1 import chat as _chat

        return _chat._assistant.fetch_artifact(token, kind)

    def doc_link(self, doc_id: str, user: AuthUser, filename: str | None):
        """"Hujjatni ochish": imzolangan, qisqa muddatli havola (`FileLink`,
        nisbiy `url`). Mini app'dagi `POST /chat/doc/{id}/link` bilan BITTA
        imzolovchi (`chat.doc_link`) - kanal `bot`, ochilishi hisobda shunday
        tursin. Hujjat bu yerda olinmaydi. `ValueError` - kalit yaroqsiz."""
        from ..api.v1 import chat as _chat

        return _chat.doc_link(doc_id, user.actorId, filename, channel="bot")

    def history(self, chat_id: str, user: AuthUser) -> Any:
        """Shikoyat surati uchun suhbat tarixi - `POST /reports` dagi AYNI
        chaqiruv: odamning O'Z kaliti bilan (boshqa odamning suhbati 404).
        Telemetriyada savollar bo'lsa umuman chaqirilmaydi."""
        from ..api.v1 import chat as _chat
        from ..services import reports as _reports
        from ..services.integrations.assistant import AssistantError
        from ..services.tg_groups import is_group_agent_chat

        if is_group_agent_chat(chat_id):
            # Guruhdagi CRM suhbati shikoyat suratiga olinmaydi (`api/v1/reports.py` dagi qoida).
            raise AssistantError("Suhbat topilmadi", status=404)
        return _chat._assistant.get_chat(chat_id, user_id=_chat.assistant_user_id(user),
                                         limit=_reports.SNAPSHOT_TURNS * 2)

    def transcribe(self, audio: bytes, content_type: str) -> Transcript:
        from ..api.v1 import stt as _stt

        # Ovozli xabar ham savol: veb ilovadagi `/stt/transcribe` bilan bir
        # xil tanlov va zahira (GAPI -> Router). Til - o'zbek: Telegram
        # interfeysi tili (`language_code`) ko'pincha ruscha yoki inglizcha,
        # gap esa o'zbekcha.
        return _stt._transcribe_with_fallback(
            _stt._pick("uz", settings.stt_provider), audio, "uz", content_type,
            yol="Telegram", budget=settings.stt_deadline,
        )


def _chat_message(status: int) -> str:
    from ..api.v1 import chat as _chat

    return _chat._MESSAGES.get(status, _chat._MESSAGES[502])


def _open_error_code(exc: AssistantError) -> str:
    """Ochilmagan oqim uchun izdagi xato kodi - veb chatdagi qoida."""
    from ..api.v1 import chat as _chat

    return _chat.open_error_code(exc)


def _stt_message(status: int) -> str:
    from ..api.v1 import stt as _stt

    return _stt._MESSAGES.get(status, _stt._MESSAGES[502])


def _action_message(status: int) -> str:
    from ..api.v1 import actions as _actions

    return _actions._MESSAGES.get(status, _actions._MESSAGES[502])


def _expired_statuses() -> tuple[int, ...]:
    from ..api.v1 import actions as _actions

    return _actions.EXPIRED_STATUSES


def _proposal_outcome(verb: str, result: dict[str, Any]) -> str | None:
    """Taklif holati izga - veb ilovadagi AYNI qoida (`actions.proposal_outcome`)."""
    from ..api.v1 import actions as _actions

    return _actions.proposal_outcome(verb, result)


@dataclass
class _Answer:
    parts: list[str] = field(default_factory=list)
    docs: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    failure: str | None = None
    #: Savol izi uchun: oqim ochilmagan yoki o'rtada uzilgan bo'lsa - sababi.
    error: BaseException | None = None


class _Typing:
    """"yozmoqda..." - javob kelguncha har 4.5 soniyada."""

    def __init__(self, api: TelegramApi, chat_id: int, every: float | None) -> None:
        self.api = api
        self.chat_id = chat_id
        self.every = every
        self._stop = threading.Event()

    def start(self) -> "_Typing":
        if self.every:
            threading.Thread(target=self._run, name="tg-typing", daemon=True).start()
        return self

    def _run(self) -> None:
        deadline = time.monotonic() + _TYPING_LIMIT
        while not self._stop.is_set() and time.monotonic() < deadline:
            try:
                self.api.send_chat_action(self.chat_id, "typing")
            except TelegramError:
                pass
            self._stop.wait(self.every)

    def stop(self) -> None:
        self._stop.set()


def _is_group(msg: dict[str, Any]) -> bool:
    return (msg.get("chat") or {}).get("type") in ("group", "supergroup")


def is_video(msg: dict[str, Any]) -> bool:
    """Kamera/video xabari: dumaloq video, video, yoki fayl sifatidagi video."""
    if isinstance(msg.get("video_note"), dict) or isinstance(msg.get("video"), dict):
        return True
    document = msg.get("document")
    return isinstance(document, dict) and str(document.get("mime_type") or "").lower().startswith("video/")


def _origin(url: str) -> str:
    """`https://llm.brb-tech.uz/tg/` -> `https://llm.brb-tech.uz`: imzolangan
    nisbiy havolani to'liq manzilga aylantirish uchun. Faqat `https` -
    Telegram tugmasidagi havola shifrsiz bo'lmasin; aks holda `""`."""
    try:
        parts = urllib.parse.urlsplit(url or "")
        host = parts.hostname
    except ValueError:
        return ""
    if parts.scheme != "https" or not host or parts.username or parts.password:
        return ""
    return f"https://{parts.netloc}"


def _iso(epoch: float | None) -> str | None:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat() if epoch else None


class VeneraBot:
    """Bitta bot nusxasi. `handle_update` - sinxron (testlar shuni chaqiradi),
    `dispatch` - navbat orqali, `start` - so'rov ipi."""

    def __init__(
        self,
        api: TelegramApi,
        links: LinkStore,
        *,
        users: Callable[[], Directory | UserStore],
        backend: Backend | None = None,
        webapp_url: str = "",
        workers: int = 4,
        inline: bool = False,
        typing_every: float | None = _TYPING_EVERY,
        mode: str = "polling",
        webhook_url: str = "",
        webhook_secret: str = "",
        beta_url: str = "",
        sync_commands: bool = False,
        groups: GroupAssistant | None = None,
        briefs: BriefService | None = None,
        admin: GroupAdmin | None = None,
        group_actions: bool = False,
    ) -> None:
        self.api = api
        #: Guruhlarni botda boshqarish (`group_admin.py`). `None` - guruhlar
        #: faqat `.env` dan, bot qo'shilishi/chiqarilishi e'tiborsiz (eski xulq).
        self.admin = admin
        #: Ro'yxatdagi guruhlar yordamchisi. `None` - hamma guruhda eski xulq.
        self.groups = groups
        #: Rahbariyat brifi (`briefs.py`) - shaxsiy chatda, faqat rahbarlarga.
        #: `None` - bot avvalgidek.
        self.briefs = briefs
        #: `/beta` tugmasi manzili (yangi mini app). Bo'sh - `/beta` hech kimga yo'q.
        self.beta_url = beta_url
        #: Buyruqlar menyusini Telegram'ga yozish (`setMyCommands`) - FAQAT
        #: jonli ishga tushishda (`app.bot.start`). Testlar va boshqa
        #: nusxalar menyuga tegmaydi.
        self.sync_commands = sync_commands
        #: Manzil yoki sir bo'lmasa webhook mumkin emas - `polling`.
        self.mode = "webhook" if mode == "webhook" and webhook_url and webhook_secret else "polling"
        self.webhook_url = webhook_url
        self.webhook_secret = webhook_secret
        self.links = links
        self.users = users
        self.backend = backend or Backend()
        #: Guruhda CRM (`group_actions.py`): "@venera crmga kiritib qo'y" - vazifa
        #: taklifi, faqat so'ragan odam tasdiqlaydi. `False` - guruhlar avvalgidek.
        self.group_actions: GroupActions | None = None
        if group_actions and groups is not None:
            self.group_actions = GroupActions(api, groups.store, self.backend, resolve=self._member_of,
                                              username=lambda: self.username)
            groups.actions = self.group_actions
            hooks = getattr(getattr(admin, "registry", None), "removed_hooks", None)
            if isinstance(hooks, list):
                # Guruh ro'yxatdan olib tashlansa - agentdagi CRM suhbatlari darhol o'chirilsin.
                hooks.append(self.group_actions.kick)
        self.webapp_url = webapp_url
        self.typing_every = typing_every
        self.username = ""
        #: `getMe`: botning o'z id si va privacy mode (o'chiq - hamma xabarni ko'radi).
        self.bot_id: int | None = None
        self.can_read_all = False
        self._inline = inline
        self._pool = None if inline else ThreadPoolExecutor(
            max_workers=max(1, workers), thread_name_prefix="tg-bot")
        self._queues: dict[int, deque[Callable[[], None]]] = {}
        self._running: set[int] = set()
        self._qlock = threading.Lock()
        self._hint_at: dict[int, float] = {}
        self._note_at: dict[int, float] = {}
        self._busy: set[str] = set()
        self._busy_lock = threading.Lock()
        #: Ariza kaliti -> sarlavha: "PDF" tugmasi bosilganda faylga nom
        #: berish uchun. Faqat xotirada - qayta ishga tushsa nom umumiy bo'ladi.
        self._titles: OrderedDict[str, str] = OrderedDict()
        self._titles_lock = threading.Lock()
        #: Hujjat kaliti -> nomi: havola xabari va fayl nomi uchun.
        self._doc_titles: OrderedDict[str, str] = OrderedDict()
        #: Javob kaliti -> (actor_id, suhbat) - `_TURNS_KEPT` izohi.
        self._turns: OrderedDict[str, tuple[int, str]] = OrderedDict()
        self._turns_lock = threading.Lock()
        self._group_at: dict[int, float] = {}
        self._offset: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._prepared = False
        self._state: dict[str, Any] = {"error": "", "error_at": None, "ok_at": None, "updates": 0,
                                       "note": ""}
        self._seen: OrderedDict[int, None] = OrderedDict()
        self._seen_lock = threading.Lock()
        self._webhook_set_at = 0.0
        self._webhook_fails = 0
        self._webhook: dict[str, Any] = {}
        #: 409 lar vaqti - boshqa nusxa shu tokenni o'qiyotganining izi.
        self._conflicts: deque[float] = deque(maxlen=2000)
        self._conflict_log_at = 0.0

    # --- so'rov ipi ---------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="tg-bot", daemon=True)
        self._thread.start()
        if self.group_actions is not None:
            # Agentdagi eski guruh CRM suhbatlarini o'chiruvchi (`group_actions.sweep`).
            self.group_actions.start()

    def stop(self) -> None:
        self._stop.set()
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
        if self.group_actions is not None:
            self.group_actions.stop()
        if self.groups is not None:
            self.groups.stop()
        if self.briefs is not None:
            self.briefs.stop()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    def status(self) -> dict[str, Any]:
        """`/api/health/detail` uchun. Token va odamlar ro'yxati YO'Q."""
        return {
            "running": self.running,
            "username": self.username or None,
            "last_ok_at": _iso(self._state["ok_at"]),
            "error": self._state["error"] or None,
            "error_at": _iso(self._state["error_at"]),
            "updates": self._state["updates"],
            "mode": self.mode,
            "note": self._state["note"] or None,
            "webhook": dict(self._webhook) if self._webhook else None,
            #: Oxirgi 10 daqiqada boshqa nusxa bilan to'qnashuvlar (409).
            "conflicts_10min": sum(1 for t in list(self._conflicts) if time.time() - t <= 600),
            #: Guruhdagi CRM suhbatlari (agentda o'chirish navbati) - faqat sonlar.
            "groupCrm": self._group_crm_counts(),
        }

    def _group_crm_counts(self) -> dict[str, int] | None:
        """`tiqilgan` (`stuck`) > 0 - agentda o'chmayotgan guruh suhbatlari bor: health
        ogohlantiradi (ichida guruhdagi boshqa odamlarning xabarlari)."""
        if self.group_actions is None:
            return None
        try:
            return self.group_actions.state.counts()
        except sqlite3.Error:
            return None

    def _run(self) -> None:
        if self.mode == "webhook":
            self._run_webhook()
        if not self._stop.is_set():
            # `polling` rejimi - yoki webhook ishlamay, zaxiraga qaytildi.
            self._run_polling()

    # --- webhook ----------------------------------------------------------------

    def _run_webhook(self) -> None:
        """Webhook'ni o'rnatadi va har daqiqada tekshiradi. Faqat to'xtatilganda
        yoki `polling` ga qaytish kerak bo'lganda chiqadi."""
        while not self._stop.is_set():
            if not self._prepared:
                self._prepare()
            try:
                if not self.check_webhook():
                    return
            except TelegramError as exc:
                self._state["error"] = str(exc)
                self._state["error_at"] = time.time()
                log.warning("Telegram webhook tekshirilmadi: %s", exc)
            except Exception:  # noqa: BLE001 - ip o'lmasligi kerak
                log.exception("Telegram webhook: kutilmagan xato")
            self._stop.wait(_WEBHOOK_CHECK)

    def check_webhook(self, *, now: float | None = None) -> bool:
        """Webhook o'z joyidami va Telegram unga yetib boryaptimi.

        `False` - Telegram uzoq vaqt yetib bora olmadi va webhook O'CHIRILDI:
        chaqiruvchi `polling` ga o'tadi (xabarlar Telegram navbatida kutib
        turgan - yo'qolmaydi).
        """
        now = time.time() if now is None else now
        info = self.api.get_webhook_info()
        url = str(info.get("url") or "")
        pending = int(info.get("pending_update_count") or 0)
        error = str(info.get("last_error_message") or "")
        error_at = float(info.get("last_error_date") or 0)
        if url != self.webhook_url:
            # Birinchi marta - yoki kimdir (boshqa nusxa) manzilni o'zgartirgan.
            self._set_webhook(now, "o'rnatildi" if not self._webhook_set_at
                              else "QAYTA o'rnatildi - manzil o'zgartirilgan edi")
            return True
        allowed = info.get("allowed_updates")
        if isinstance(allowed, list) and sorted(allowed) != sorted(ALLOWED_UPDATES):
            # Yangilanish turlari o'zgargan (masalan `my_chat_member` qo'shildi) -
            # manzil bir xil bo'lsa ham qayta o'rnatiladi. Yo'q bo'lsa - Telegram
            # sukuti: `chat_member` dan boshqa hammasi, ya'ni yetarli.
            self._set_webhook(now, "QAYTA o'rnatildi - yangilanish turlari o'zgardi")
            return True
        failing = bool(pending and error_at and error_at > self._webhook_set_at
                       and now - error_at < 3 * _WEBHOOK_CHECK)
        self._webhook = {"pending": pending, "last_error": error or None,
                         "last_error_at": _iso(error_at) if error_at else None}
        if not failing:
            self._webhook_fails = 0
            self._state["error"] = ""
            self._state["ok_at"] = now
            return True
        self._webhook_fails += 1
        self._state["error"] = f"Telegram webhook'ga yetib bora olmayapti: {error}"
        self._state["error_at"] = now
        if self._webhook_fails == 1 and ("401" in error or "403" in error):
            # Sir mos kelmayapti - boshqa nusxa webhook'ni o'z siri bilan
            # o'rnatgan bo'lishi mumkin. Bir marta qayta o'rnatamiz.
            self._set_webhook(now, "QAYTA o'rnatildi - sir rad etilayotgan edi")
            return True
        if self._webhook_fails >= _WEBHOOK_FAILS:
            log.error("Telegram webhook %d daqiqa ishlamadi (%s) - xabarlar yo'qolmasligi uchun "
                      "polling'ga qaytildi", self._webhook_fails, error)
            self.api.delete_webhook()
            self.mode = "polling"
            self._state["note"] = f"webhook ishlamadi ({error}) - polling'ga qaytildi"
            return False
        log.warning("Telegram webhook'ga yetib bora olmayapti (%d/%d): %s",
                    self._webhook_fails, _WEBHOOK_FAILS, error)
        return True

    def _set_webhook(self, now: float, what: str) -> None:
        self.api.set_webhook(self.webhook_url, secret=self.webhook_secret,
                             allowed_updates=ALLOWED_UPDATES)
        first = not self._webhook_set_at
        self._webhook_set_at = now
        self._webhook_fails = 0
        self._webhook = {"pending": 0, "last_error": None, "last_error_at": None}
        self._state["error"] = ""
        self._state["ok_at"] = now
        (log.info if first else log.warning)("Telegram webhook %s: %s", what, self.webhook_url)

    def accept(self, update: dict[str, Any]) -> None:
        """Webhook orqali kelgan yangilanish. Takrori tashlanadi."""
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            with self._seen_lock:
                if update_id in self._seen:
                    return
                self._seen[update_id] = None
                while len(self._seen) > _SEEN_UPDATES:
                    self._seen.popitem(last=False)
        self._state["updates"] += 1
        self._state["ok_at"] = time.time()
        self.dispatch(update)

    # --- polling ------------------------------------------------------------------

    def _run_polling(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            if not self._prepared:
                self._prepare()
            try:
                self.poll_once()
                backoff = 1.0
            except TelegramError as exc:
                wait, backoff = self.poll_error(exc, backoff)
                self._stop.wait(wait)
            except Exception:  # noqa: BLE001 - ip o'lmasligi kerak
                log.exception("Telegram bot: kutilmagan xato")
                self._stop.wait(5.0)

    def poll_error(self, exc: TelegramError, backoff: float, *,
                   now: float | None = None) -> tuple[float, float]:
        """`getUpdates` xatosidan keyin: (qancha kutish, keyingi backoff).

        409 IKKI XIL, va farqi muhim:

          * "webhook is active" - webhook o'rnatilgan, polling umuman
            ishlamaydi: kutamiz va aytamiz (qo'lda `deleteWebhook`);
          * "terminated by other getUpdates request" - BOSHQA NUSXA shu
            tokenni o'qiyapti (2026-09-24 da dev server). DARHOL qayta
            so'raymiz: Telegram'da faqat oxirgi so'rov tirik qoladi, ya'ni
            shu bilan ulanish bizga qaytadi va u nusxa xabarni ushlashga
            deyarli ulgurmaydi. Butunlay to'xtatish - tokenni yangilash.
        """
        now = time.time() if now is None else now
        text = f"{exc.description} {exc}".lower()
        if exc.code == 409 and "webhook" in text:
            self._state["error"] = str(exc)
            self._state["error_at"] = now
            log.error("Telegram bot: webhook o'rnatilgan - polling ishlamaydi, deleteWebhook kerak (%s)", exc)
            return 30.0, backoff
        if exc.code == 409:
            self._conflicts.append(now)
            if now - self._conflict_log_at >= 600:
                self._conflict_log_at = now
                log.warning("Telegram bot: boshqa nusxa ham shu tokenni o'qiyapti (409) - ulanish darhol "
                            "qaytarib olinadi; butunlay to'xtatish uchun bot tokenini yangilang")
            recent = sum(1 for t in self._conflicts if now - t <= 60)
            return (_CONFLICT_SLOW if recent > _CONFLICT_BURST else _CONFLICT_RETRY), backoff
        self._state["error"] = str(exc)
        self._state["error_at"] = now
        if exc.code in (401, 404):
            log.error("Telegram bot: token rad etildi (%s)", exc)
            return 300.0, backoff
        log.warning("Telegram bot: %s", exc)
        return backoff, min(backoff * 2, 30.0)

    def _prepare(self) -> None:
        """Bot nomi - bir marta (yiqilsa keyin yana); keyin buyruqlar menyusi."""
        try:
            me = self.api.get_me()
        except TelegramError as exc:
            log.warning("Telegram bot tayyorlanmadi: %s", exc)
            return
        self.username = str(me.get("username") or "")
        self.bot_id = me.get("id") if isinstance(me.get("id"), int) else None
        self.can_read_all = bool(me.get("can_read_all_group_messages"))
        if self.admin is not None:
            self.admin.set_me(bot_id=self.bot_id, username=self.username, can_read_all=self.can_read_all)
        self._prepared = True
        log.info("Telegram bot ishga tushdi: @%s", self.username)
        if self.sync_commands:
            self.sync_menu()
            self.sync_profile()

    def sync_profile(self) -> int:
        """Bot nomi va tavsiflari `PROFILE` bilan bir xil bo'lsin. IDEMPOTENT:
        har maydon avval o'qiladi, faqat farq qilsa yoziladi (`setMyName`
        chegarasi qattiq - 429 uzoq kuttiradi, shuning uchun bir marta).

        Har maydon alohida: biri yiqilsa qolganlari baribir yoziladi. Xato
        botni TO'XTATMAYDI. Natija: nechta maydon yozildi.
        """
        written = 0
        for field, value in PROFILE.items():
            try:
                getter = getattr(self.api, f"get_my_{field}")
                setter = getattr(self.api, f"set_my_{field}")
                if getter() == value:
                    continue
                setter(value)
            except TelegramError as exc:
                log.warning("Telegram bot: profil (%s) yangilanmadi: %s", field, exc)
                continue
            except Exception:  # noqa: BLE001 - ip o'lmasligi kerak
                log.exception("Telegram bot: profil (%s) - kutilmagan xato", field)
                continue
            written += 1
            log.info("Telegram bot: profil (%s) yangilandi", field)
        return written

    def sync_menu(self) -> bool:
        """Buyruqlar menyusi `COMMANDS` bilan bir xil bo'lsin. IDEMPOTENT:
        Telegram'dagi ro'yxat allaqachon shu bo'lsa hech narsa yozilmaydi.

        Xato botni TO'XTATMAYDI - menyu qulaylik, savol-javob esa usiz ham
        ishlaydi. Natija: menyu yangilandimi.
        """
        try:
            if self.api.get_my_commands() == COMMANDS:
                return False
            self.api.set_my_commands(COMMANDS)
        except TelegramError as exc:
            log.warning("Telegram bot: buyruqlar menyusi yangilanmadi: %s", exc)
            return False
        except Exception:  # noqa: BLE001 - ip o'lmasligi kerak
            log.exception("Telegram bot: buyruqlar menyusi - kutilmagan xato")
            return False
        log.info("Telegram bot: buyruqlar menyusi yangilandi")
        return True

    def poll_once(self, timeout: int = 25) -> int:
        updates = self.api.get_updates(self._offset, timeout=timeout)
        self._state["ok_at"] = time.time()
        self._state["error"] = ""
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                # Keyingi so'rov shu `offset` bilan ketadi - Telegram buni
                # "qabul qilindi" deb biladi va qayta bermaydi.
                self._offset = max(self._offset or 0, update_id + 1)
            self._state["updates"] += 1
            try:
                self.dispatch(update)
            except Exception:  # noqa: BLE001
                log.exception("Telegram xabari navbatga qo'yilmadi")
        return len(updates)

    # --- navbat ---------------------------------------------------------------

    def dispatch(self, update: dict[str, Any]) -> None:
        if self._inline:
            self.handle_update(update)
            return
        if isinstance(update.get("callback_query"), dict):
            self._submit(lambda: self._on_callback(update["callback_query"]))
            return
        if isinstance(update.get("my_chat_member"), dict):
            self._submit(lambda: self._on_member(update["my_chat_member"]))
            return
        message = update.get("message")
        if self.groups is not None:
            # Guruh xabari shaxsiy navbatga TUSHMAYDI: guruh yozishmasi tez
            # oqadi, navbat to'lsa guruhga "⏳ Oldingi xabarlaringizga..."
            # ketardi. Saqlash tez, javob esa `groups` ning o'z iplarida.
            group_msg = message if isinstance(message, dict) else update.get("edited_message")
            if isinstance(group_msg, dict) and _is_group(group_msg):
                edited = group_msg is not message
                self._submit(lambda: self._on_group(group_msg, edited=edited))
                return
        if not isinstance(message, dict):
            return
        chat_id = (message.get("chat") or {}).get("id")
        if not isinstance(chat_id, int):
            return
        if is_video(message):
            # Navbatsiz: video DARHOL o'chirilsin - oldingi savolning javobini
            # (15-40 s) kutib chatda turmasin.
            self._submit(lambda: self._on_message(message))
            return
        if not self._enqueue(chat_id, lambda: self._on_message(message)):
            self._submit(lambda: self._say(
                chat_id, "⏳ Oldingi xabarlaringizga javob tayyorlanmoqda - biroz kuting."))

    def _submit(self, job: Callable[[], None]) -> None:
        if self._pool is None:
            job()
            return
        try:
            self._pool.submit(self._guarded, job)
        except RuntimeError:
            pass  # to'xtatilmoqda

    @staticmethod
    def _guarded(job: Callable[[], None]) -> None:
        try:
            job()
        except Exception:  # noqa: BLE001
            log.exception("Telegram xabari ishlanmadi")

    def _enqueue(self, chat_id: int, job: Callable[[], None]) -> bool:
        with self._qlock:
            queue = self._queues.setdefault(chat_id, deque())
            if len(queue) >= _QUEUE_LIMIT:
                return False
            queue.append(job)
            if chat_id in self._running:
                return True
            self._running.add(chat_id)
        self._submit(lambda: self._drain(chat_id))
        return True

    def _drain(self, chat_id: int) -> None:
        while True:
            with self._qlock:
                queue = self._queues.get(chat_id)
                if not queue:
                    self._queues.pop(chat_id, None)
                    self._running.discard(chat_id)
                    return
                job = queue.popleft()
            self._guarded(job)

    # --- yangilanishlar ---------------------------------------------------------

    def handle_update(self, update: dict[str, Any]) -> None:
        if isinstance(update.get("callback_query"), dict):
            self._on_callback(update["callback_query"])
        elif isinstance(update.get("my_chat_member"), dict):
            self._on_member(update["my_chat_member"])
        elif isinstance(update.get("message"), dict):
            self._on_message(update["message"])
        elif isinstance(update.get("edited_message"), dict) and _is_group(update["edited_message"]):
            self._on_group(update["edited_message"], edited=True)

    def _on_message(self, msg: dict[str, Any]) -> None:
        chat = msg.get("chat") or {}
        sender = msg.get("from") or {}
        if chat.get("type") != "private":
            if _is_group(msg):
                self._on_group(msg)
            return
        if sender.get("is_bot"):
            return
        chat_id, tg_id = chat.get("id"), sender.get("id")
        if not isinstance(chat_id, int) or not isinstance(tg_id, int):
            return
        if is_video(msg):
            # Ulanganmi-yo'qmi - farqi yo'q: kamera yozuvi hech kimdan olinmaydi.
            self._reject_video(chat_id, msg)
            return
        sent = msg.get("date")
        if isinstance(sent, int) and time.time() - sent >= 5:
            # Yuborilgandan ishlanguncha: yetkazish + navbat. Sekin javobni
            # "GAPI mi, yordamchimi, Telegram mi" deb taxmin qilmaslik uchun.
            log.info("Telegram xabari %d s kechikib ishlandi (%s)", int(time.time() - sent), self.mode)
        text = str(msg.get("text") or "").strip()
        if text.startswith("/") and len(text) > 1 and text[1].isalpha():
            self._command(chat_id, tg_id, text)
            return

        link, state = self.links.lookup(tg_id)
        if link is None:
            self._link_prompt(chat_id, state)
            return
        found = self._account(chat_id, link)
        if found is None:
            return
        user, login = found
        # "⚙️ Guruhlar" tugmasi (`group_admin.py`) - HR yordamchisiga ketmaydi.
        if (self.admin is not None and text == BTN_GROUPS
                and self.admin.on_text(chat_id, text, user, login)):
            return
        # Rahbariyat brifi tugmasi yoki "Boshqa davr" so'roviga javob - HR
        # yordamchisiga ketmaydi. Qolgan matn va ovoz - avvalgidek.
        if (self.briefs is not None and text and not isinstance(msg.get("voice"), dict)
                and self.briefs.on_text(chat_id, msg, text, user, login)):
            return
        # Hisob: shu xabar bo'yicha har tashqi chaqiruv (STT, Assistant,
        # Telegram) shu odam va `bot` kanali bilan yoziladi. Bot HTTP dan
        # kelmaydi - kanalni sarlavha emas, kodning o'zi aytadi.
        with bind(user.actorId, "bot"):
            if isinstance(msg.get("voice"), dict):
                self._voice(chat_id, tg_id, user, msg)
            elif text:
                self._ask(chat_id, tg_id, user, text)
            else:
                # Rasm, fayl, stiker, audio fayl... - ishlanmaydi.
                self._note(chat_id, "Faqat matn va 🎙 ovozli xabar qabul qilinadi.")

    def _addressed(self, msg: dict[str, Any]) -> bool:
        """Guruhdagi xabar SHU botga qaratilganmi: buyruq (`/help` yoki
        `/help@shu_bot`; boshqa botga `@` bilan - yo'q), matnda `@shu_bot`,
        shu botning xabariga javob yoki botning guruhga qo'shilishi.

        Bot nomi (`getMe`) hali noma'lum bo'lsa - faqat `@` siz buyruq.
        """
        name = self.username.lower()
        text = str(msg.get("text") or msg.get("caption") or "")
        if text.startswith("/") and len(text) > 1 and text[1].isalpha():
            _, _, mention = text.split(maxsplit=1)[0].partition("@")
            return not mention or (bool(name) and mention.lower() == name)
        if not name:
            return False
        if re.search(rf"@{re.escape(name)}(?!\w)", text, re.IGNORECASE):
            return True

        def ours(who: Any) -> bool:
            return (isinstance(who, dict) and bool(who.get("is_bot"))
                    and str(who.get("username") or "").lower() == name)

        reply = msg.get("reply_to_message")
        if isinstance(reply, dict) and ours(reply.get("from")):
            return True
        members = msg.get("new_chat_members")
        return isinstance(members, list) and any(ours(m) for m in members)

    def _on_group(self, msg: dict[str, Any], *, edited: bool = False) -> None:
        """Guruh xabari. Ro'yxatdagi guruh - `groups` (saqlash, xulosa).
        Qolganlari - FAQAT shaxsiy chat: HR javoblari guruhga chiqmaydi,
        murojaat qilinsa bitta qisqa izoh, qolgan xabarlar jim (har xabarga
        javob shovqin bo'lardi)."""
        chat_id = (msg.get("chat") or {}).get("id")
        if self.admin is not None and not edited and self.admin.on_migration(msg):
            return          # guruh supergroup'ga aylandi - faqat ro'yxat va tarix ko'chadi
        if self.groups is not None and self.groups.allowed(chat_id):
            if edited:
                self.groups.on_edit(msg)
            else:
                self.groups.on_message(msg, username=self.username)
            return
        note = _GROUP_ONLY
        if self.admin is not None and not edited:
            # Yoqilmagan guruh: bot qo'shildimi (rahbarga "turini tanlang"),
            # to'xtatilganmi yoki rahbar qarorini kutyaptimi. Mazmun SAQLANMAYDI.
            verdict = self.admin.on_inactive(msg, resolve=self._exec_of)
            if verdict == "join":
                return
            note = {"paused": GROUP_PAUSED, "pending": GROUP_NOT_ENABLED}.get(verdict, _GROUP_ONLY)
        # Boshqa botlarga javob yo'q - ikki bot bir-birining xabariga javob
        # berib "suhbatlashib" qolmasin.
        if not edited and not (msg.get("from") or {}).get("is_bot") and self._addressed(msg):
            self._group_note(chat_id, msg.get("message_id"), text=note)

    def _on_member(self, update: dict[str, Any]) -> None:
        """`my_chat_member` - botning guruhdagi holati o'zgardi (`group_admin.py`).
        Shaxsiy chatda bu - odam botni blokladi/ochdi: e'tiborsiz."""
        if self.admin is None:
            return
        if (update.get("chat") or {}).get("type") not in ("group", "supergroup"):
            return
        with bind(None, "bot"):
            self.admin.on_member(update, resolve=self._exec_of)

    def _member_of(self, tg_id: int) -> tuple[AuthUser, str | None] | None:
        """Telegram odami - Venera'ga ulangan, bloklanmagan xodimmi (`_account` ning
        JIM nusxasi: hech kimga yozmaydi, ulanishni uzmaydi)."""
        if not isinstance(tg_id, int):
            return None
        link, _ = self.links.lookup(tg_id)
        if link is None:
            return None
        try:
            stored = self.users().by_actor_id(link.actor_id)
        except Exception:  # noqa: BLE001
            log.exception("Telegram: hisoblar manbasi o'qilmadi")
            return None
        if stored is None:
            return None
        login = getattr(stored, "username", None)
        verdict = admin_users.access(stored.to_public(), login=login)
        if verdict.blocked:
            return None
        return verdict.user, login

    def _exec_of(self, tg_id: int) -> tuple[AuthUser, str | None] | None:
        """Telegram odami - guruhlarni boshqara oladigan rahbarmi."""
        if self.admin is None:
            return None
        found = self._member_of(tg_id)
        if found is None or not self.admin.allowed(*found):
            return None
        return found

    def _group_note(self, chat_id: Any, message_id: Any, *, text: str = _GROUP_ONLY) -> None:
        """"Faqat shaxsiy chatda" (yoki guruh holati) - guruhga `_GROUP_EVERY` da
        bir marta. Tugma shaxsiy chatni ochadi (bot nomi ma'lum bo'lsa)."""
        if not isinstance(chat_id, int):
            return
        now = time.monotonic()
        if now - self._group_at.get(chat_id, -_GROUP_EVERY) < _GROUP_EVERY:
            return
        self._group_at[chat_id] = now
        if len(self._group_at) > 2000:
            self._group_at.clear()
        markup = (render.url_button("Shaxsiy chatni ochish", f"https://t.me/{self.username}")
                  if re.fullmatch(r"\w{3,64}", self.username) else None)
        # Guruh id si - qaysi guruh ekanini topish uchun (nomi yozilmaydi).
        log.info("Telegram: guruhda murojaat - izoh (guruh %s o'qilmaydi)", chat_id)
        self._send(chat_id, esc(text), markup=markup, reply_to=message_id)

    def _reject_video(self, chat_id: int, msg: dict[str, Any]) -> None:
        """Video (kamera) - yuklab olinmaydi va chatdan o'chiriladi."""
        message_id = msg.get("message_id")
        deleted = False
        if isinstance(message_id, int):
            try:
                self.api.delete_message(chat_id, message_id)
                deleted = True
            except TelegramError as exc:
                log.info("Telegram: video o'chirilmadi: %s", exc)
        log.info("Telegram: video rad etildi (%s)", "o'chirildi" if deleted else "o'chirilmadi")
        self._note(chat_id, "📵 Video qabul qilinmaydi" + (" - xabar o'chirildi" if deleted else "")
                   + ". Savolni yozing yoki 🎙 ovozli xabar yuboring.")

    def _note(self, chat_id: int, text: str) -> None:
        """Qisqa izoh - `_NOTE_EVERY` dan tez takrorlanmaydi."""
        now = time.monotonic()
        if now - self._note_at.get(chat_id, -_NOTE_EVERY) < _NOTE_EVERY:
            return
        self._note_at[chat_id] = now
        if len(self._note_at) > 2000:
            self._note_at.clear()
        self._say(chat_id, text)

    def _user_for(self, chat_id: int, link: TelegramLink) -> AuthUser | None:
        found = self._account(chat_id, link)
        return found[0] if found else None

    def _account(self, chat_id: int, link: TelegramLink) -> tuple[AuthUser, str | None] | None:
        """Ulanishdagi hisob HALI BORMI - har xabarda tekshiriladi: hisob
        `users.yaml` dan olib tashlansa bot darhol to'xtashi kerak.

        Admin qarorlari veb ilovadagi bilan AYNI funksiyadan
        (`admin_users.access`): rollar samarali, bloklangan odam esa
        xushmuomala rad oladi. Bloklanganda ulanish UZILMAYDI - blok olib
        tashlansa odam mini app'ni qayta ochmasdan davom etsin.

        Natija: (samarali foydalanuvchi, SSO logini yoki `None` - zahira hisob).
        """
        stored = self.users().by_actor_id(link.actor_id)
        if stored is None:
            self.links.unlink(link.tg_id, actor_id=link.actor_id)
            log.warning("Telegram: ulangan hisob topilmadi (%s) - ulanish uzildi", link.actor_id)
            self._send(chat_id, "Barno hisobingiz topilmadi. Ilovani ochib qaytadan kiring.",
                       markup=render.app_button(self.webapp_url))
            return None
        login = getattr(stored, "username", None)
        verdict = admin_users.access(stored.to_public(), login=login)
        if verdict.blocked:
            log.info("Telegram: hisob bloklangan (%s) - savol qabul qilinmadi", link.actor_id)
            self._note(chat_id, _BLOCKED)
            return None
        return verdict.user, login

    def _link_prompt(self, chat_id: int, state: str, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._hint_at.get(chat_id, -_HINT_EVERY) < _HINT_EVERY:
            return
        self._hint_at[chat_id] = now
        if len(self._hint_at) > 2000:
            self._hint_at.clear()
        text = _EXPIRED.format(days=settings.telegram_link_days) if state == "expired" else _INTRO
        self._send(chat_id, text, markup=render.app_button(self.webapp_url))

    # --- buyruqlar --------------------------------------------------------------

    def _command(self, chat_id: int, tg_id: int, text: str) -> None:
        head = text.split(maxsplit=1)[0][1:]
        name, _, mention = head.partition("@")
        if mention and self.username and mention.lower() != self.username.lower():
            return
        name = name.lower()
        link, state = self.links.lookup(tg_id)
        if name == "start":
            if link is None:
                self._link_prompt(chat_id, state, force=True)
                return
            found = self._account(chat_id, link)
            if found is not None:
                user, login = found
                self._send(chat_id, welcome_text(user, again=True),
                           markup=render.app_button(self.webapp_url))
                # Rahbarga - ikkinchi xabar: brif tugmalari (bitta xabarda
                # faqat bitta `reply_markup` - birinchisida ilova tugmasi).
                if self.briefs is not None and self.briefs.allowed(user, login):
                    self.briefs.show_keyboard(chat_id)
        elif name == "help":
            # Ulanmagan odamga - BITTA xabar: yordam va ilova tugmasi.
            self._send(chat_id, _HELP,
                       markup=render.app_button(self.webapp_url) if link is None else None)
        elif name == "beta":
            self._beta(chat_id, link)
        elif name in ("brif", "brief"):
            self._brief_command(chat_id, link, text)
        elif name in ("guruhlar", "groups"):
            self._groups_command(chat_id, link)
        elif name in ("new", "yangi"):
            if link is None:
                self._link_prompt(chat_id, state, force=True)
            elif self.links.new_chat(tg_id):
                self._send(chat_id, "🆕 Yangi suhbat boshlandi. Savolingizni yozing yoki "
                                    "ovozli xabar yuboring.")
        elif name == "app":
            # Eski nom (menyuda endi `/start`) - ishlayveradi.
            self._send(chat_id, "Barno ilovasi - ovozli suhbat va suhbatlar tarixi:",
                       markup=render.app_button(self.webapp_url))
        elif name in ("logout", "chiqish"):
            if self.links.unlink(tg_id):
                log.info("Telegram: ulanish bot orqali uzildi (%s)", link.actor_id if link else "-")
                self._send(chat_id, "Hisobingiz botdan uzildi. Qayta ulash uchun Barnoni "
                                    "oching.", markup=render.app_button(self.webapp_url))
            else:
                self._send(chat_id, "Hisob ulanmagan.")
        else:
            self._send(chat_id, _UNKNOWN)

    def _brief_command(self, chat_id: int, link: TelegramLink | None, text: str) -> None:
        """`/brif [davr]` - rahbariyat brifi. Ruxsati yo'q odamga - noma'lum
        buyruqdagi AYNAN o'sha javob (`/beta` kabi): brif borligi bilinmasin."""
        found = self._account(chat_id, link) if (link is not None and self.briefs is not None) else None
        if found is None:
            if link is None or self.briefs is None:
                self._send(chat_id, _UNKNOWN)
            return          # bloklangan / hisob yo'q - `_account` o'zi aytdi
        user, login = found
        if not self.briefs.allowed(user, login):
            self._send(chat_id, _UNKNOWN)
            return
        parts = text.split(maxsplit=1)
        log.info("Telegram: /brif (%s)", user.actorId)
        self.briefs.on_command(chat_id, user, parts[1] if len(parts) > 1 else "")

    def _groups_command(self, chat_id: int, link: TelegramLink | None) -> None:
        """`/guruhlar` - guruhlarni boshqarish. Ruxsati yo'q odamga - noma'lum
        buyruqdagi AYNAN o'sha javob (`/brif` kabi)."""
        found = self._account(chat_id, link) if (link is not None and self.admin is not None) else None
        if found is None:
            if link is None or self.admin is None:
                self._send(chat_id, _UNKNOWN)
            return          # bloklangan / hisob yo'q - `_account` o'zi aytdi
        user, login = found
        if not self.admin.allowed(user, login):
            self._send(chat_id, _UNKNOWN)
            return
        log.info("Telegram: /guruhlar (%s)", user.actorId)
        self.admin.on_command(chat_id)

    def _beta(self, chat_id: int, link: TelegramLink | None) -> None:
        """`/beta` - yangi mini app tugmasi, FAQAT sinovchilarga.

        Ulanmagan yoki ruxsati yo'q odamga - noma'lum buyruqdagi AYNAN o'sha
        javob: beta borligi ham bilinmasin. Manzil sozlanmagan bo'lsa ham
        shunday - sinovchiga ochiladigan narsa yo'q. Bloklangan yoki
        o'chirilgan hisobga `_account` o'z izohini aytadi.
        """
        found = self._account(chat_id, link) if link is not None else None
        if found is None:
            if link is None:
                self._send(chat_id, _UNKNOWN)
            return          # bloklangan / hisob yo'q - `_account` o'zi aytdi
        user, login = found
        markup = render.app_button(self.beta_url, "🧪 Beta'ni ochish")
        if markup is None or not beta_allowed(user, login):
            self._send(chat_id, _UNKNOWN)
            return
        log.info("Telegram: /beta (%s)", user.actorId)
        self._send(chat_id, _BETA, markup=markup)

    # --- savol -> javob -----------------------------------------------------------

    def _ask(self, chat_id: int, tg_id: int, user: AuthUser, question: str, *,
             stt: dict[str, Any] | None = None) -> None:
        """`stt` - ovozli xabar bo'lsa: transkripsiya qancha vaqt olgani va
        qaysi variant (izga nuqta bo'lib tushadi, savol undan KEYIN boshlanadi)."""
        limit = settings.hrm_assistant_max_question_chars
        if len(question) > limit:
            self._say(chat_id, f"Savol juda uzun ({len(question)} belgi) - {limit} belgigacha yozing.")
            return
        chat = self.links.chat_for(tg_id, idle_sec=settings.telegram_chat_idle_hours * 3600)
        # SAVOL IZI (admin panel) - veb chatdagi bilan bir xil shakl.
        rec = TurnRecorder(user, "bot", "bot", question, chat_id=chat, locale="uz",
                           input_mode="voice" if stt else "text")
        if stt:
            rec.point("stt", **stt)
        try:
            with rec.bind():
                typing = _Typing(self.api, chat_id, self.typing_every).start()
                holder = self._send(chat_id, "⏳ Javob tayyorlanmoqda…")
                try:
                    answer = self._collect(question, user, chat, chat_id, holder, rec)
                finally:
                    typing.stop()
                # "⚑" bosilganda egalikni tekshirish uchun (analitika o'chiq
                # bo'lsa ham) - javob chiqishidan OLDIN.
                self._remember_turn(rec.turn_id, user.actorId, chat)
                # Javobni Telegram'ga yetkazish ham izda: uzun javob bir
                # necha xabarga bo'linadi va har biri tarmoq so'rovi.
                with rec.span("telegram.deliver"):
                    self._deliver(chat_id, holder, answer, turn_id=rec.turn_id)
        except BaseException as exc:
            rec.finish("error", error=exc)
            raise
        rec.finish(error=answer.error)

    def _collect(self, question: str, user: AuthUser, chat: str, chat_id: int,
                 holder: int | None, rec: TurnRecorder) -> _Answer:
        answer = _Answer()
        log.info("Telegram savol (%s): %d belgi", user.actorId, len(question))
        try:
            with rec.span("assistant.open") as info:
                stream = self.backend.stream(question, user, chat)
                info["requestId"] = stream.request_id
        except AssistantError as exc:
            log.warning("Telegram savol (%s) [%s]: %s", user.actorId,
                        getattr(exc, "reason", None) or "-", exc)
            answer.failure = _chat_message(exc.status)
            # Veb chatdagi AYNI kod: `queue_full` / `upstream_unreachable` /
            # `upstream_busy`, qolgani `open_failed`.
            rec.error_code, answer.error = _open_error_code(exc), exc
            # Ochilmagan savolda ham qaysi dvigatelga borilgani izda tursin -
            # SHU ODAMNIKI (admin unga alohida versiya bergan bo'lishi mumkin).
            engine_of = getattr(self.backend, "engine", None)
            if callable(engine_of):
                rec.update(engine=engine_of(user))
            return answer
        # So'ralgan dvigatel (ma'lumotnoma javobida `None`); `done.engine`
        # kelsa `rec.observe` uni haqiqatda javob bergani bilan almashtiradi.
        rec.update(request_id=stream.request_id, engine=getattr(stream, "engine", None))
        frames = stream.frames
        stage_text, stage_at = "", 0.0
        try:
            for raw in frames:
                try:
                    frame = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if not isinstance(frame, dict):
                    continue
                # Izga - JSON qayta o'qilmaydi, tayyor lug'at beriladi.
                rec.observe(frame)
                kind = frame.get("type")
                if kind == "token":
                    answer.parts.append(str(frame.get("text") or ""))
                elif kind == "stage":
                    text = str(frame.get("text") or "").strip()
                    now = time.monotonic()
                    if holder and text and text != stage_text and now - stage_at >= _STAGE_EVERY:
                        stage_text, stage_at = text, now
                        self._edit(chat_id, holder, f"⏳ {esc(text)}")
                elif kind == "sources":
                    docs = render.doc_sources(frame.get("sources") or frame.get("items"))
                    if docs:
                        answer.docs = docs
                elif kind == "artifact":
                    art = frame.get("artifact") or frame
                    if isinstance(art, dict):
                        answer.artifacts.append(art)
                elif kind == "proposal":
                    proposal = frame.get("proposal") or frame
                    if isinstance(proposal, dict) and proposal.get("token"):
                        answer.proposals.append(proposal)
                elif kind == "error":
                    answer.failure = render.frame_error(frame)
        except AssistantError as exc:
            # Oqim o'rtasida uzildi - kelgan qism baribir ko'rsatiladi.
            log.warning("Telegram javob oqimi (%s): %s", user.actorId, exc)
            answer.failure = _chat_message(exc.status)
            # Veb chatdagi kabi kod (`stream_broken`), ichki sabab esa nuqtada.
            rec.point("assistant.broken", status=exc.status, error=redact(exc))
            rec.error_code, answer.error = "stream_broken", exc
        finally:
            # Oqim OXIRIGACHA o'qilmagan bo'lsa ham yopiladi - yuqoridagi
            # xizmat sloti faqat shunda bo'shaydi. `AnswerStream.close` -
            # boshlanmagan oqimda ham slotni qaytaradi; u bo'lmasa (soxta
            # oqim) - generatorning o'zi.
            close = getattr(stream, "close", None) or getattr(frames, "close", None)
            if callable(close):
                close()
            log.info("Telegram javob (%s): request_id=%s natija=%s", user.actorId,
                     stream.request_id, stream.outcome or "-")
        return answer

    def _deliver(self, chat_id: int, holder: int | None, answer: _Answer, *,
                 turn_id: str | None = None) -> None:
        """Javob: matn bloklari, izohlar ("📚 Manbalar") va OXIRGI xabar
        ostida tugmalar - "📄 Hujjatni ochish" va "⚑". "⚑" faqat haqiqiy
        javob ostida: xato yoki bo'sh javob haqida xabar berishning ma'nosi
        yo'q (u izda xato bo'lib turibdi)."""
        if holder:
            try:
                self.api.delete_message(chat_id, holder)
            except TelegramError:
                self._edit(chat_id, holder, "✓")
        body = "".join(answer.parts).strip()
        blocks = render.to_blocks(body) if body else []
        rows: list[list[dict[str, Any]]] = []
        if blocks and answer.docs:
            shown = render.cited(answer.docs, body)
            blocks.append(render.sources_block(shown))
            rows = render.doc_rows(shown)
            self._remember_titles(shown)
        # Kalit shakli tekshiriladi: tugma ma'lumoti `parse_report` dan o'tmasa,
        # bosilganda baribir "eskirgan" bo'lardi - unday tugma chiqmasin.
        if blocks and turn_id and render.parse_report(turn_id):
            rows.append(render.report_row(turn_id))
        markup = render.keyboard(rows)
        if not blocks:
            if answer.failure:
                blocks = ["⚠️ " + esc(answer.failure)]
            elif not answer.artifacts and not answer.proposals:
                blocks = ["Javob kelmadi. Savolni boshqacha yozib ko'ring."]
        elif answer.failure:
            # Qisman javobdan keyingi xato - izoh, javobning o'rniga emas.
            blocks.append("⚠️ <i>" + esc(answer.failure) + "</i>")
        chunks = render.pack(blocks)
        for index, chunk in enumerate(chunks):
            self._send(chat_id, chunk, markup=markup if index == len(chunks) - 1 else None)
        for proposal in answer.proposals:
            self._send_proposal(chat_id, proposal)
        for artifact in answer.artifacts:
            self._send_artifact(chat_id, artifact)

    # --- ovozli xabar -------------------------------------------------------------

    def _voice(self, chat_id: int, tg_id: int, user: AuthUser, msg: dict[str, Any]) -> None:
        voice = msg["voice"]
        most = settings.telegram_voice_max_sec
        size_limit = int(settings.stt_max_upload_mb * 1024 * 1024)
        duration = int(voice.get("duration") or 0)
        if duration > most or int(voice.get("file_size") or 0) > size_limit:
            self._say(chat_id, f"Ovozli xabar juda uzun - {most // 60} daqiqagacha yuboring.")
            return
        file_id = voice.get("file_id")
        if not isinstance(file_id, str):
            return
        typing = _Typing(self.api, chat_id, self.typing_every).start()
        try:
            try:
                info = self.api.get_file(file_id)
                audio = self.api.download(str(info.get("file_path") or ""), limit=size_limit)
            except TelegramError as exc:
                log.warning("Telegram ovozi olinmadi (%s): %s", user.actorId, exc)
                self._say(chat_id, "Ovozli xabarni olib bo'lmadi - qaytadan yuboring.")
                return
            boshlandi = time.monotonic()
            try:
                result = self.backend.transcribe(audio, str(voice.get("mime_type") or "audio/ogg"))
            except SttError as exc:
                log.warning("Telegram STT (%s): %s", user.actorId, exc)
                self._say(chat_id, _stt_message(exc.status))
                return
            stt_ms = int((time.monotonic() - boshlandi) * 1000)
        finally:
            typing.stop()
        text = (result.text or "").strip()
        log.info("Telegram ovoz (%s): %d s -> %d belgi (%s)", user.actorId, duration,
                 len(text), result.backend or "-")
        if not text:
            self._send(chat_id, "🎙 Ovozdan matn ajratib bo'lmadi - aniqroq gapirib qayta yuboring.",
                       reply_to=msg.get("message_id"))
            return
        note = "\n<i>(yozuv uzun - boshi olindi)</i>" if result.truncated else ""
        self._send(chat_id, f"🎙 <i>{esc(text)}</i>{note}", reply_to=msg.get("message_id"))
        self._ask(chat_id, tg_id, user, text, stt={
            "durMs": stt_ms, "audioSec": duration, "backend": result.backend or None,
            "truncated": bool(result.truncated),
        })

    # --- tugmalar -------------------------------------------------------------------

    def _on_callback(self, cq: dict[str, Any]) -> None:
        cq_id = str(cq.get("id") or "")
        msg = cq.get("message") or {}
        chat = msg.get("chat") or {}
        tg_id = (cq.get("from") or {}).get("id")
        if chat.get("type") not in (None, "private"):
            data = str(cq.get("data") or "")
            if (self.group_actions is not None and data.startswith("a:") and chat.get("type") in ("group", "supergroup")
                    and isinstance(chat.get("id"), int)):
                # Guruhdagi CRM taklifi kartasi (`group_actions.py`).
                self._group_action(cq_id, chat["id"], msg, tg_id, data)
                return
            # Boshqa guruh tugmasi (bot u yerda boshqa tugma yubormaydi - bu
            # nusxa yoki soxta so'rov): hech narsa bajarilmaydi.
            self._answer_cb(cq_id, _GROUP_ONLY)
            return
        if chat.get("type") != "private" or not isinstance(tg_id, int) or not isinstance(chat.get("id"), int):
            self._answer_cb(cq_id)
            return
        chat_id = chat["id"]
        link, state = self.links.lookup(tg_id)
        if link is None:
            self._answer_cb(cq_id, "Avval Barno hisobingizni ulang: /start", alert=True)
            return
        data = str(cq.get("data") or "")
        if self.briefs is not None and data.startswith("b:"):
            found = self._account(chat_id, link)
            if found is None:
                self._answer_cb(cq_id)
                return
            self.briefs.on_callback(cq_id, chat_id, msg, found[0], found[1], data)
            return
        if self.admin is not None and data.startswith("g:"):
            found = self._account(chat_id, link)
            if found is None:
                self._answer_cb(cq_id)
                return
            with bind(found[0].actorId, "bot"):
                self.admin.on_callback(cq_id, chat_id, msg, found[0], found[1], data)
            return
        user = self._user_for(chat_id, link)
        if user is None:
            self._answer_cb(cq_id)
            return
        kind, _, rest = data.partition(":")
        # Hisob: tugma bo'yicha chaqiruvlar (tasdiqlash, fayl) shu odam va
        # `bot` kanali bilan yoziladi.
        with bind(user.actorId, "bot"):
            self._button(cq_id, chat_id, msg, user, kind, rest)

    def _group_action(self, cq_id: str, chat_id: int, msg: dict[str, Any], tg_id: Any, data: str) -> None:
        """Guruhdagi taklif tugmasi: faqat SO'RAGAN odam bosa oladi, faqat yoqilgan
        guruhda; tasdiqlash - shaxsiy chatdagi AYNI `_action`, o'z CRM tokeni bilan."""
        verb, _, token = data[2:].partition(":")
        owner = self.group_actions.owner(token, chat_id) if self.group_actions is not None else None
        if owner is None:
            self._answer_cb(cq_id, "Tugma eskirgan", alert=True)
            return
        if self.groups is None or not self.groups.allowed(chat_id):
            self._answer_cb(cq_id, "Barno bu guruhda yoqilmagan", alert=True)
            return
        found = self._member_of(tg_id) if isinstance(tg_id, int) else None
        if found is None or found[0].actorId != owner.actor_id:
            self._answer_cb(cq_id, ONLY_OWNER.format(name=owner.name), alert=True)
            return
        with bind(found[0].actorId, "bot"):
            self._action(cq_id, chat_id, msg.get("message_id"), found[0], verb, token, own_tokens=True)

    def _button(self, cq_id: str, chat_id: int, msg: dict[str, Any], user: AuthUser,
                kind: str, rest: str) -> None:
        if kind == "a":
            verb, _, token = rest.partition(":")
            self._action(cq_id, chat_id, msg.get("message_id"), user, verb, token)
        elif kind == "f":
            short, _, token = rest.partition(":")
            file_kind = {"d": "docx", "p": "pdf"}.get(short)
            if file_kind is None or not render.SAFE_ARTIFACT.fullmatch(token):
                self._answer_cb(cq_id, "Tugma eskirgan", alert=True)
                return
            self._answer_cb(cq_id, "Fayl tayyorlanmoqda…")
            with self._titles_lock:
                title = self._titles.get(token) or "hujjat"
            self._send_file(chat_id, file_kind, token, title)
        elif kind == "d":
            if not render.SAFE_KEY.fullmatch(rest):
                self._answer_cb(cq_id, "Tugma eskirgan", alert=True)
                return
            self._open_doc(cq_id, chat_id, msg.get("message_id"), user, rest)
        elif kind == "r":
            self._report(cq_id, chat_id, msg, user, rest)
        else:
            self._answer_cb(cq_id, "Tugma eskirgan", alert=True)

    # --- "Hujjatni ochish" ------------------------------------------------------

    def _open_doc(self, cq_id: str, chat_id: int, reply_to: Any, user: AuthUser,
                  doc_id: str) -> None:
        """Imzolangan havola - YANGI xabar, "📄 Hujjatni ochish" URL tugmasi bilan.

        NEGA HAVOLA, fayl emas: PDF chatga yuborilsa bank hujjati Telegram
        serverlarida abadiy qoladi. Havola esa qisqa muddatli
        (`chat.doc_link`) va hujjat Venera'dan ochiladi. NEGA tugma
        bosilganda, javob bilan birga emas: javob ostidagi havola 10
        daqiqada eskirardi - tugma esa har bosilganda yangi havola beradi.
        Hujjatni ko'rish huquqi veb ilovadagi bilan bir xil: har qanday
        ulangan xodim (`GET /chat/doc/{id}` ham faqat sessiya so'raydi).
        """
        with self._titles_lock:
            title = self._doc_titles.get(doc_id) or doc_id
        # Havola to'liq manzil bo'lishi kerak (Telegram tugmasi) - ommaviy
        # manzil mini app manzilidan (`https` bo'lmasa - havola berilmaydi).
        origin = _origin(self.webapp_url)
        link = None
        if origin:
            try:
                link = self.backend.doc_link(doc_id, user, title)
            except ValueError:
                self._answer_cb(cq_id, "Tugma eskirgan", alert=True)
                return
            except Exception:  # noqa: BLE001 - tugma javobsiz qolmasin
                log.exception("Telegram: hujjat havolasi yasalmadi (%s)", user.actorId)
        path = str(getattr(link, "url", "") or "")
        markup = render.url_button("📄 Hujjatni ochish", origin + path if path.startswith("/") else "")
        if markup is None:
            self._answer_cb(cq_id, "Hujjatni hozir ochib bo'lmadi - Barno ilovasida oching.",
                            alert=True)
            return
        self._answer_cb(cq_id)
        minutes = max(1, int(getattr(link, "expiresIn", 600) or 600) // 60)
        log.info("Telegram: hujjat havolasi (%s), %d daq", user.actorId, minutes)
        self._send(chat_id, f"📄 <b>{esc(title)}</b>\n<i>Havola {minutes} daqiqa ishlaydi - "
                            "keyin tugmani javob ostidan qayta bosing.</i>",
                   markup=markup, reply_to=reply_to)

    def _remember_titles(self, docs: list[dict[str, Any]]) -> None:
        with self._titles_lock:
            for doc in docs:
                doc_id, title = doc.get("doc_id"), doc.get("title")
                if isinstance(doc_id, str) and isinstance(title, str) and title.strip():
                    self._doc_titles[doc_id] = title.strip()[:200]
                    self._doc_titles.move_to_end(doc_id)
            while len(self._doc_titles) > 500:
                self._doc_titles.popitem(last=False)

    # --- "⚑" - javob haqida xabar berish -----------------------------------------

    def _remember_turn(self, turn_id: str, actor_id: int, chat: str) -> None:
        with self._turns_lock:
            self._turns[turn_id] = (actor_id, chat)
            while len(self._turns) > _TURNS_KEPT:
                self._turns.popitem(last=False)

    def _turn_owner(self, turn_id: str, actor_id: int) -> tuple[bool, str | None]:
        """Javob SHU ODAMNIKIMI: (ha/yo'q, uning suhbati).

        Tugma ma'lumoti soxta bo'lishi mumkin - kalit HECH QACHON o'z-o'zidan
        ishonchli emas. Avval xotira (shu jarayon bergan javob), keyin
        analitika ombori (`turns`: egasi, kanal `bot`). Ikkalasida ham yo'q -
        yo'q: tasdiqlanmagan kalit bilan shikoyat yaratilmaydi.
        """
        with self._turns_lock:
            known = self._turns.get(turn_id)
        if known is not None:
            return known[0] == actor_id, known[1]
        try:
            analytics.flush(2.0)
            row = analytics.get_db().row(
                "SELECT actor_id, chat_id, channel FROM turns WHERE id = ?", (turn_id,))
        except Exception:  # noqa: BLE001 - ombor nosozligi "yo'q" degani
            log.warning("Telegram: javob egasi tekshirilmadi", exc_info=True)
            return False, None
        if row is None or row.get("actor_id") != actor_id or row.get("channel") != "bot":
            return False, None
        return True, row.get("chat_id")

    def _report(self, cq_id: str, chat_id: int, msg: dict[str, Any], user: AuthUser,
                rest: str) -> None:
        parsed = render.parse_report(rest)
        message_id = msg.get("message_id")
        if parsed is None or not isinstance(message_id, int):
            self._answer_cb(cq_id, "Tugma eskirgan", alert=True)
            return
        turn_id, action = parsed
        if action == render.REPORT_DONE:
            self._answer_cb(cq_id, "Xabar allaqachon yuborilgan")
            return
        owned, chat = self._turn_owner(turn_id, user.actorId)
        if not owned:
            log.warning("Telegram: begona yoki noma'lum javob haqida xabar (%s) - rad etildi",
                        user.actorId)
            self._answer_cb(cq_id, "Bu javob haqida xabar berib bo'lmaydi", alert=True)
            return
        current = msg.get("reply_markup")
        if action == "":
            self._set_buttons(chat_id, message_id, render.swap_report_rows(
                current, render.report_reason_rows(turn_id)))
            self._answer_cb(cq_id, "Nima noto'g'ri?")
            return
        if action == render.REPORT_CANCEL:
            self._set_buttons(chat_id, message_id, render.swap_report_rows(
                current, [render.report_row(turn_id)]))
            self._answer_cb(cq_id)
            return
        key = f"r:{turn_id}"
        with self._busy_lock:
            if key in self._busy:
                self._answer_cb(cq_id, "Yuborilmoqda…")
                return
            self._busy.add(key)
        try:
            self._submit_report(cq_id, chat_id, message_id, current, user, turn_id, chat,
                                render.REPORT_CODES[action])
        finally:
            with self._busy_lock:
                self._busy.discard(key)

    def _submit_report(self, cq_id: str, chat_id: int, message_id: int, current: Any,
                       user: AuthUser, turn_id: str, chat: str | None, reason: str) -> None:
        """Veb ilovadagi AYNI xizmat (`reports.create`): surat telemetriyadan
        (shu odamning shu suhbatdagi savollari), bo'lmasa suhbat tarixidan;
        chegara ham o'sha (soatiga 20 ta, odam bo'yicha - veb va bot birga)."""
        from ..services import reports as _reports

        history = getattr(self.backend, "history", None)
        try:
            _reports.create(
                user, channel="bot", chat_id=chat, turn_id=turn_id, reason=reason,
                upstream=(lambda cid: history(cid, user)) if callable(history) else None,
            )
        except _reports.ReportError as exc:
            log.info("Telegram: xabar qabul qilinmadi (%s): %s", user.actorId, exc.status)
            self._answer_cb(cq_id, str(exc), alert=True)
            return
        self._set_buttons(chat_id, message_id, render.swap_report_rows(
            current, [render.report_done_row(turn_id)]))
        self._answer_cb(cq_id, "Rahmat, yuborildi")

    def _action(self, cq_id: str, chat_id: int, message_id: Any, user: AuthUser,
                verb: str, token: str, *, own_tokens: bool = False) -> None:
        if verb not in ("c", "x") or not render.SAFE_KEY.fullmatch(token):
            self._answer_cb(cq_id, "Tugma eskirgan", alert=True)
            return
        with self._busy_lock:
            if token in self._busy:
                # Ikki marta tez bosish - bitta so'rov.
                self._answer_cb(cq_id, "Bajarilmoqda…")
                return
            self._busy.add(token)
        what = "tasdiqlash" if verb == "c" else "rad etish"
        try:
            try:
                extra = {"own_tokens": True} if own_tokens else {}
                result = self.backend.action("confirm" if verb == "c" else "cancel", token, user, **extra)
            except AssistantError as exc:
                log.warning("Telegram amal %s (%s, %s): %s", what, user.actorId, token, exc)
                self._answer_cb(cq_id, _action_message(exc.status), alert=True)
                if exc.status in _expired_statuses():
                    # Veb ilovadagi kabi: muddati o'tgan taklif (404 yoki 410).
                    set_proposal_status(token, "expired")
                    if isinstance(message_id, int):
                        self._clear_buttons(chat_id, message_id)
                return
            outcome = _proposal_outcome("confirm" if verb == "c" else "cancel", result)
            if outcome:
                set_proposal_status(token, outcome)
            settled, text, toast = render.outcome(result)
            log.info("Telegram amal %s (%s): token=%s holat=%s ok=%s", what, user.actorId, token,
                     result.get("status"), result.get("ok"))
            self._answer_cb(cq_id, toast)
            if settled and isinstance(message_id, int):
                self._clear_buttons(chat_id, message_id)
                self._send(chat_id, text, reply_to=message_id)
        finally:
            with self._busy_lock:
                self._busy.discard(token)

    # --- taklif va fayllar -----------------------------------------------------------

    def _send_proposal(self, chat_id: int, proposal: dict[str, Any]) -> None:
        text = render.proposal_card(proposal)
        markup = render.proposal_buttons(str(proposal.get("token") or ""))
        if markup is None:
            text += "\n\n<i>Bu taklifni Barno ilovasida tasdiqlang.</i>"
        self._send(chat_id, text, markup=markup)

    def _send_artifact(self, chat_id: int, art: dict[str, Any]) -> None:
        title = str(art.get("title") or art.get("filename") or "Hujjat").strip()
        refs: dict[str, str] = {}
        for key in ("docx_url", "pdf_url"):
            value = art.get(key)
            if isinstance(value, str):
                parts = value.split("/")
                # `/api/v1/chat/artifact/{token}/{kind}` - `_rewrite_artifact` shakli.
                if (len(parts) == 7 and parts[1:5] == ["api", "v1", "chat", "artifact"]
                        and parts[6] in ("docx", "pdf") and render.SAFE_ARTIFACT.fullmatch(parts[5])):
                    refs[parts[6]] = parts[5]
        if not refs:
            self._send(chat_id, f"📎 Hujjat tayyorlandi: <b>{esc(title)}</b>. "
                                "Faylni Barno ilovasidan yuklab oling.")
            return
        kind = "docx" if "docx" in refs else "pdf"
        markup = render.file_button("pdf", refs["pdf"]) if kind == "docx" and "pdf" in refs else None
        with self._titles_lock:
            for token in refs.values():
                self._titles[token] = title
                self._titles.move_to_end(token)
            while len(self._titles) > 500:
                self._titles.popitem(last=False)
        self._send_file(chat_id, kind, refs[kind], title,
                        caption=f"📎 <b>{esc(title)}</b>", markup=markup)

    def _send_file(self, chat_id: int, kind: str, token: str, title: str, *,
                   caption: str | None = None, markup: dict[str, Any] | None = None) -> None:
        from ..api.v1.chat import _download_name

        self._upload(chat_id, lambda: self.backend.artifact(token, kind),
                     _download_name(title, kind), caption=caption, markup=markup, what="Hujjat")

    def _upload(self, chat_id: int, open_it: Callable[[], Any], filename: str | None, *,
                caption: str | None = None, markup: dict[str, Any] | None = None,
                what: str = "Hujjat") -> None:
        try:
            content_type, upstream_name, chunks = open_it()
            data = b"".join(chunks)
        except AssistantError as exc:
            log.warning("Telegram: %s olinmadi: %s", what.lower(), exc)
            self._say(chat_id, f"{what}ni olib bo'lmadi: {_chat_message(exc.status)}")
            return
        if not data or len(data) >= _MAX_FILE:
            self._say(chat_id, f"{what}ni yuborib bo'lmadi - fayl bo'sh yoki juda katta.")
            return
        name = filename or upstream_name or "hujjat.pdf"
        try:
            self.api.send_document(chat_id, name, data, content_type or "application/octet-stream",
                                   caption=caption, reply_markup=markup)
        except TelegramError as exc:
            log.warning("Telegram: fayl yuborilmadi: %s", exc)
            self._say(chat_id, f"{what}ni yuborib bo'lmadi - qaytadan urinib ko'ring.")

    # --- yuborish -------------------------------------------------------------------

    def _send(self, chat_id: int, text: str, *, markup: dict[str, Any] | None = None,
              reply_to: Any = None) -> int | None:
        """HTML xabar. Telegram belgilashni rad etsa - teglarsiz qayta.
        Natija: yuborilgan xabar `message_id` si yoki `None`."""
        reply = reply_to if isinstance(reply_to, int) else None
        try:
            sent = self.api.send_message(chat_id, text, reply_markup=markup, reply_to=reply)
        except TelegramError as exc:
            if not exc.bad_markup:
                log.warning("Telegram xabari yuborilmadi: %s", exc)
                return None
            try:
                sent = self.api.send_message(chat_id, render.plain(text), html=False,
                                             reply_markup=markup, reply_to=reply)
            except TelegramError as again:
                log.warning("Telegram xabari yuborilmadi: %s", again)
                return None
        message_id = sent.get("message_id") if isinstance(sent, dict) else None
        return message_id if isinstance(message_id, int) else None

    def _say(self, chat_id: int, text: str) -> None:
        """Oddiy izoh (HTML'siz matn)."""
        self._send(chat_id, esc(text))

    def _edit(self, chat_id: int, message_id: int, text: str) -> None:
        try:
            self.api.edit_message_text(chat_id, message_id, text)
        except TelegramError as exc:
            if not exc.not_modified:
                log.debug("Telegram tahrirlanmadi: %s", exc)

    def _set_buttons(self, chat_id: int, message_id: int, markup: dict[str, Any] | None) -> None:
        """Xabar tugmalarini almashtiradi (`None` - olib tashlaydi)."""
        try:
            self.api.edit_reply_markup(chat_id, message_id, markup)
        except TelegramError as exc:
            if not exc.not_modified:
                log.debug("Telegram tugmalari almashtirilmadi: %s", exc)

    def _clear_buttons(self, chat_id: int, message_id: int) -> None:
        try:
            self.api.edit_reply_markup(chat_id, message_id, None)
        except TelegramError as exc:
            if not exc.not_modified:
                log.debug("Telegram tugmalari olinmadi: %s", exc)

    def _answer_cb(self, cq_id: str, text: str = "", *, alert: bool = False) -> None:
        if not cq_id:
            return
        try:
            self.api.answer_callback(cq_id, text, alert=alert)
        except TelegramError as exc:
            log.debug("Telegram tugma javobi: %s", exc)
