"""Venera API - ilova nuqtasi.

Ishga tushirish (ishlab chiqish):
    cd apps/api && uvicorn app.main:app --reload --port 8000

Hujjat: http://localhost:8000/api/docs  (avtomatik, qo'lda yozilmaydi)

TUZILMA:
    app/core/       sozlama, xavfsizlik, xato shakli
    app/api/v1/     HTTP qatlami - router'lar, mantiq YO'Q
    app/schemas/    so'rov/javob modellari (frontend types.ts nusxasi)
    app/services/   MANTIQ shu yerda: foydalanuvchilar, quvur, integratsiyalar

Qoida: router'da mantiq yozilmaydi, `services/` da HTTP haqida bilinmaydi.
Shu tufayli mantiqni test qilish uchun HTTP kerak emas va integratsiya
qo'shganda router'ga tegilmaydi.
"""

from __future__ import annotations

import logging
import threading
import time

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from fastapi import Depends

from .api.deps import current_user, docs_viewer, get_identity_store, get_user_store, require_roles
from .api.metering import ChannelMiddleware
from .api.v1 import router as v1_router
from .core import errors
from .core.config import crm_token_now, hrm_token_now, settings
from .services.oidc import KeycloakOidc
from .schemas.auth import AuthUser
from .services.integrations.assistant import token_warning
from .services.upstream import UpstreamHealth, warnings_for


def tts_client():
    """Ovoz endpointi ishlatayotgan AYNI klient.

    Import shu yerda, funksiya ichida: modul darajasida qilinsa
    `api.v1.tts` -> `main` -> `api.v1.tts` aylanma importi chiqardi.
    """
    from .api.v1.tts import _client

    return _client


def crm_auth():
    """Chat endpointi ishlatayotgan AYNI CRM sessiyasi.

    Alohida nusxa yasalsa u alohida login qilib, `refresh_token` ni
    rotatsiya bilan bekor qilar edi - ya'ni sog'lik tekshiruvining o'zi
    chat sessiyasini buzardi.
    """
    from .api.v1.chat import _crm

    return _crm


def connector_hub():
    """Ulanishlar markazi - `api/v1/connectors.py` dagi AYNI nusxa."""
    from .api.v1.connectors import hub

    return hub


def assistant_state() -> dict:
    """Yordamchi: dvigatel (umumiy va har kanalniki) va navbat - chat
    endpointi ishlatayotgan AYNI klientdan. Sir yo'q - faqat versiya nomlari
    va sonlar."""
    from .api.v1.chat import _assistant
    from .core.engines import config_state
    from .services.engine_control import health_state

    # `engine` - `.env` (boshlang'ich qiymat), `policy` - HOZIR haqiqatda
    # ishlaydigani (admin panel qarori bilan). Ikkalasi kerak: admin siyosat
    # saqlagach `.env` dagi qiymat endi ishlamaydi, va jurnal o'qiydigan
    # odam buni shu yerda ko'rishi kerak.
    return {"engine": config_state(), "policy": health_state(),
            "slots": _assistant.slots_state()}
from .services.users import example_password_hashes

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)
# Anthropic SDK DEBUG da butun so'rov tanasini (tizim prompti + transkript) jurnalga yozadi -
# `DEBUG=true` bo'lsa ham yig'ilish matni logga tushmasin; httpx2 ham so'rov qatorlarini yozmasin.
logging.getLogger("anthropic").setLevel(logging.INFO)
logging.getLogger("httpx2").setLevel(logging.WARNING)

# Hujjat manzillari ATAYLAB `/api/` ostida.
#
# Sabab: nginx (apps/web/deploy/nginx.container.conf) FAQAT `location /api/`
# ni backend'ga uzatadi, qolgan hamma narsa SPA ga ketadi. Default `/docs`
# bilan qoldirsak Swagger tashqaridan OCHILMAYDI va nginx'ga alohida
# location qo'shishga to'g'ri kelardi. Shu bitta qaror bilan deploy
# sozlamasiga umuman tegilmaydi.
#
# Swagger UI ning O'ZI ham muammo, va ikki qatlamda:
#
#   1. FastAPI uni default holda `cdn.jsdelivr.net` dan yuklaydi. Ichki
#      tarmoqda internet yo'q. Shuning uchun fayllar `app/static/` da turadi.
#   2. Frontend nginx butun saytga qattiq CSP qo'yadi - `script-src 'self'`.
#      FastAPI ning `get_swagger_ui_html()` funksiyasi INLINE `<script>` yozadi,
#      CSP esa uni bloklaydi: bundle yuklanadi, ishga tushirilmaydi, sahifa
#      BO'SH ochiladi. curl 200 qaytaradi va muammo ko'rinmaydi.
#
# Shuning uchun sahifa quyida QO'LDA yig'iladi: inline skript YO'Q, ishga
# tushirish kodi `static/swagger-init.js` da. CSP ni bo'shashtirish kerak emas.
app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="Barno AI - web ilova uchun backend.",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

#: Swagger UI fayllari shu papkada turadi. Yuklab olish:
#: docs/deploy-api.md, "Swagger fayllari" bo'limi.
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_SWAGGER_FILES = ("swagger-ui-bundle.js", "swagger-ui.css", "swagger-init.js")
_SWAGGER_MISSING = [f for f in _SWAGGER_FILES if not (_STATIC_DIR / f).exists()]

# Papka bo'lmasa `StaticFiles` ISHGA TUSHISHDA yiqiladi va butun API
# ko'tarilmaydi - hujjat sahifasi tufayli xizmatni yo'qotish mantiqsiz.
_STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/api/static", StaticFiles(directory=_STATIC_DIR), name="static")

#: Sahifada INLINE SKRIPT YO'Q - CSP `script-src 'self'` uni bloklardi.
_DOCS_PAGE = """<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="/api/static/swagger-ui.css">
<link rel="icon" href="data:,">
</head>
<body>
<div id="swagger-ui"></div>
<script src="/api/static/swagger-ui-bundle.js"></script>
<script src="/api/static/swagger-init.js"></script>
</body>
</html>"""


@app.get("/api/openapi.json", include_in_schema=False)
def openapi_schema(_: str = Depends(docs_viewer)) -> dict:
    """OpenAPI sxemasi - hujjat sahifasi bilan BIR XIL himoyada.

    Sahifani qulflab, sxemani ochiq qoldirish ma'nosiz bo'lardi: qimmatli
    ma'lumot aynan shu faylda (endpointlar, modellar, rol nomlari).
    Brauzer Basic ma'lumotlarini shu originga o'zi qayta yuboradi, shuning
    uchun foydalanuvchi ikkinchi marta parol kiritmaydi.
    """
    return app.openapi()


@app.get("/api/docs", include_in_schema=False)
def swagger_ui(_: str = Depends(docs_viewer)) -> HTMLResponse:
    """Swagger UI. Internetsiz ishlaydi va qattiq CSP ostida ham ochiladi."""
    if _SWAGGER_MISSING:
        # ATAYLAB xato sahifasi, BO'SH sahifa emas. CDN ga qaytish MA'NOSIZ:
        # CSP `script-src 'self'` tashqi manbani baribir bloklaydi, natijada
        # foydalanuvchi sababsiz oq ekran ko'rardi.
        log.error("Swagger fayllari yetishmayapti: %s", ", ".join(_SWAGGER_MISSING))
        return HTMLResponse(
            "<h1>Swagger fayllari yo'q</h1>"
            f"<p>Yetishmayapti: <code>{', '.join(_SWAGGER_MISSING)}</code></p>"
            "<p>Yechim: <code>docs/deploy-api.md</code>, "
            "&laquo;Swagger fayllari&raquo; bo'limi.</p>"
            "<p>OpenAPI JSON ishlayapti: <a href=\"/api/openapi.json\">/api/openapi.json</a></p>",
            status_code=503,
        )
    return HTMLResponse(_DOCS_PAGE.format(title=f"{settings.app_name} - hujjat"))

# FastAPI ning default `{"detail": ...}` shakli frontend kutgan shaklga MOS
# KELMAYDI - shuning uchun handler'lar almashtiriladi. Tafsilot: core/errors.py
errors.install(app)

# CORS odatda KERAK EMAS: nginx frontend va `/api` ni BIR XIL originda
# ko'rsatadi. Faqat frontend boshqa domenda ishlasa `cors_origins` to'ldiriladi.
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # Boshqa domendan JS faqat shu ro'yxatdagi sarlavhalarni o'qiy oladi:
        # savol kaliti shikoyat va ovoz so'rovlariga qo'shiladi.
        expose_headers=["X-Venera-Turn", "X-Venera-Request-Id"],
    )

# Hisob kanali (web / miniapp / ...) har so'rov boshida - `api/metering.py`.
app.add_middleware(ChannelMiddleware)

app.include_router(v1_router)


#: Yuqoridagi ovoz xizmatlari holati. Keshlanadi - `/api/health` monitoring
#: tomonidan tez-tez so'raladi.
_upstream = UpstreamHealth(settings.stt_base_url, settings.tts_base_url)


@app.on_event("startup")
def _warm_hold_voices() -> None:
    """Tayyor kutish ovozlarini FON ipida sintez qiladi.

    NEGA ISHGA TUSHGANDA. Kutish gapining butun ma'nosi kechikishning
    nolligida. Sintez esa o'lchangan holda 1-3 sekund oladi - ya'ni uni
    so'rov ichida qilish tuzatayotgan muammoning o'zini yasagan bo'lardi:
    javob kechikardi va TTS ning ikki slotidan biri band bo'lardi.

    NEGA IP. `startup` hodisasi tugamaguncha xizmat so'rov qabul
    qilmaydi. 12 ta ovoz ketma-ket ~20 sekund oladi, ya'ni har qayta ishga
    tushish yigirma sekundlik uzilish bo'lardi - holbuki ovozlar
    BO'LMASA ham hammasi ishlaydi (klient matnni o'zi aytadi).
    """
    if not settings.hold_enabled or not settings.hold_warm:
        return
    if not settings.tts_client_secret:
        log.info("Kutish ovozlari: TTS sozlanmagan, o'tkazib yuborildi")
        return

    def run() -> None:
        from .api.v1.chat import _hold_voices
        from .services.hold import all_clips

        client = tts_client()
        _hold_voices.warm(all_clips(),
                          lambda text: client.synthesize_wav(text, voice=settings.tts_voice))

    threading.Thread(target=run, name="hold-warm", daemon=True).start()


@app.on_event("startup")
def _start_telegram_bot() -> None:
    """Telegram bot - FONDA, ishga tushishni kutdirmaydi (`app/bot/`).

    Token bo'lmasa yoki `TELEGRAM_BOT_ENABLED=false` bo'lsa hech narsa
    qilmaydi - veb ilova va mini app botga bog'liq emas.
    """
    from . import bot

    bot.start()


@app.on_event("shutdown")
def _stop_telegram_bot() -> None:
    from . import bot

    bot.stop()


@app.on_event("startup")
def _start_slack() -> None:
    """Slack ilovasi "Barno AI" - FONDA ulanadi (`app/slack/`).

    Tokenlar bo'lmasa hech narsa qilmaydi - qolgan hamma narsa Slack'ga bog'liq emas.
    """
    from . import slack

    slack.start()


@app.on_event("shutdown")
def _stop_slack() -> None:
    from . import slack

    slack.stop()


@app.on_event("startup")
def _start_meetings_worker() -> None:
    """Yig'ilish yozuvchisining fon ishchisi (`services/meetings/worker.py`).

    `MEETINGS_WORKER=false` bo'lsa ip yo'q. Bo'lim o'chiq va ombor yo'q
    bo'lsa ip faqat kutadi - diskka hech narsa yozmaydi."""
    from .services import meetings

    meetings.start()


@app.on_event("shutdown")
def _stop_meetings_worker() -> None:
    from .services import meetings

    meetings.stop()


def meetings_state() -> dict:
    """Yig'ilishlar holati - `/api/health/detail` uchun: SONLAR va daqiqalar,
    mazmun (matn, xulosa, ism) YO'Q."""
    from .services import meetings

    return meetings.status()


@app.on_event("shutdown")
def _flush_analytics() -> None:
    """Analitika navbatida qolgan yozuvlarni diskka tushiradi.

    Botdan KEYIN (hodisalar ro'yxatdagi tartibda): botning oxirgi savoli
    ham yozilsin. Yozuvchi ip o'zi birinchi yozuvda ishga tushadi - bu
    yerda faqat to'xtatiladi; `atexit` esa ikkinchi to'r.
    """
    from .services import analytics

    analytics.shutdown()


def telegram_state() -> dict:
    """Telegram bot holati - `/api/health/detail` uchun. TOKEN, Telegram id
    va ismlar YO'Q: faqat holat va ulanganlar SONI."""
    from . import bot

    return bot.status()


def stt_variants() -> dict:
    """STT variantlarining holati - `/api/health/detail` uchun.

    Import FUNKSIYA ICHIDA: `api/v1/stt.py` ni modul boshida import qilish
    aylanma bog'liqlik yasaydi (`main` -> `api` -> `main`).
    """
    from .api.v1.stt import _fallbacks, _gapi_client, _gapi_wake_client, _wake_budget
    from .services.meetings import runtime as meetings_runtime

    spend = _gapi_client.spend()
    wake_spend = _gapi_wake_client.spend()
    # Uchinchi klient - yig'ilishlar (alohida slot). Kunlik balans BITTA, shuning
    # uchun sarfi umumiy songa qo'shiladi va alohida ham ko'rsatiladi.
    meeting_client = meetings_runtime().gapi
    meeting_spend = meeting_client.spend() if callable(getattr(meeting_client, "spend", None)) \
        else {"audio_sec": 0.0, "calls": 0, "sent": 0}
    return {
        "provider": settings.stt_provider,
        "wake_provider": settings.stt_wake_provider,
        "gapi_configured": _gapi_client.configured,
        # Bugun shu jarayon GAPI da sarflagan audio - kunlik chegara 480
        # daqiqa (28800 s) va u Toshkent yarim kechasida to'ldiriladi.
        "gapi_spend": {
            "day": spend["day"],
            "audio_sec": round(float(spend["audio_sec"]) + float(wake_spend["audio_sec"])
                               + float(meeting_spend["audio_sec"]), 1),
            "calls": int(spend["calls"]) + int(wake_spend["calls"]) + int(meeting_spend["calls"]),
            # `sent` > `calls` degani: urinish yuborilgan, javob kelmagan -
            # va o'lchangan holda javobsiz urinishning ham puli ketadi.
            "sent": int(spend["sent"]) + int(wake_spend["sent"]) + int(meeting_spend["sent"]),
            "wake_audio_sec": wake_spend["audio_sec"],
            "wake_calls": wake_spend["calls"],
            "meeting_audio_sec": meeting_spend["audio_sec"],
            "meeting_calls": meeting_spend["calls"],
        },
        "wake_budget": _wake_budget.snapshot(),
        # Zahira qachon ishlagani. `last_5min > 0` degani "2-variant
        # tanlangan, lekin AMALDA 1-variant ishlayapti".
        "fallback": _fallbacks.snapshot(),
    }


def hold_state() -> dict:
    """Kutish gapi holati - `/api/health/detail` uchun.

    KALIT QIYMATI YO'Q - faqat sozlangan/sozlanmagan va ovozlar soni.
    """
    from .api.v1.chat import _hold_classifier, _hold_voices, _holds
    from .services.hold import all_clips

    return {
        "enabled": settings.hold_enabled,
        "model": settings.ollama_model if _hold_classifier.configured else "",
        "model_configured": _hold_classifier.configured,
        "first_ms": settings.hold_first_ms,
        "repeat_ms": settings.hold_repeat_ms,
        "max": settings.hold_max,
        "voices": _hold_voices.snapshot(all_clips()),
        # Nechta ovoz aytilgani va yorliq qayerdan kelgani. `jadval` ko'p
        # bo'lsa - model ulgurmayapti yoki ishlamayapti.
        "said": _holds.snapshot(),
    }


def _sso_configured() -> bool:
    """SSO (Keycloak, brauzer orqali) sozlanganmi - `api/v1/auth._oidc` bilan bir manba."""
    return KeycloakOidc(settings.sso_issuer, settings.sso_client_id, settings.sso_client_secret).configured


def _diagnostics() -> dict:
    """To'liq tashxis. FAQAT sessiya bilan ko'rsatiladi (pastga qara).

    `warnings` - ishga tushdi, lekin e'tibor talab qiladigan holatlar.
    Bular server KO'TARILISHINI to'smaydi: buzuq config tufayli xizmat
    umuman ishlamagandan ko'ra, ishlab turib muammoni AYTGANI yaxshiroq.
    """
    store = get_user_store()
    warnings: list[str] = []
    if settings.secret_is_default:
        warnings.append("secret_key default qiymatda - PRODUCTION uchun o'zgartiring")
    if len(store) == 0:
        warnings.append(f"foydalanuvchilar yuklanmadi ({settings.users_file})")

    # `users.example.yaml` git'da, undagi parollar esa README da OCHIQ yozilgan.
    # Uni nusxalab qoldirish eng oson va eng xavfli xato: tizim ishlaydi,
    # hech nima buzilmaydi, va parol allaqachon e'lon qilingan bo'ladi.
    # Buni AYTMASA hech kim sezmaydi - shu tekshiruv yo'qligi tufayli bir
    # marta jonli tizimda aynan shunday bo'lgan.
    demo = store.emails_using(
        example_password_hashes(settings.users_file.parent / "users.example.yaml")
    )
    if demo:
        warnings.append(
            "NAMUNA PAROLLARI ISHLATILMOQDA (" + ", ".join(demo) + ") - "
            "ular git'da ochiq yozilgan, DARHOL almashtiring: "
            "venv/bin/python -m app.tools.hash_password"
        )

    # Yuqoridagi ovoz xizmatlari BIZDAN MUSTAQIL o'chadi, va o'chganda ilova
    # o'zi butunlay sog'lom ko'rinadi - uyg'otish so'zi esa jimgina ishlamay
    # qo'yadi. Aynan shunday bo'ldi: uz backend o'chganini faqat log'dan
    # bilish mumkin edi.
    upstream = _upstream.snapshot()
    warnings.extend(warnings_for(upstream))

    # Savol-javob zanjiri kredensialsiz JIMGINA ishlamaydi: har savol
    # yuqoridagi xizmatdan 401 olardi va foydalanuvchi buni "xizmat
    # javob bermadi" deb ko'rardi. Sozlanmaganini AYTAMIZ.
    if not (settings.hrm_assistant_client_id and settings.hrm_assistant_client_secret):
        warnings.append(
            "hrm_assistant_client_id/secret bo'sh - CHAT ISHLAMAYDI "
            "(.env: HRM_ASSISTANT_CLIENT_ID, HRM_ASSISTANT_CLIENT_SECRET)"
        )

    # Yordamchi: qaysi DVIGATEL (kanal bo'yicha) va NAVBAT holati. Navbat
    # 29-sentabrda jimgina "to'la" bo'lib qolgan: bir soat davomida har savol
    # 503 olgan, yordamchiga esa birorta so'rov bormagan. Endi navbat o'zini
    # davolaydi, lekin to'lgani va qaytarib olingan joylar SHU YERDA ko'rinadi.
    assistant = assistant_state()
    warnings.extend(assistant["engine"]["problems"])
    slots = assistant["slots"]
    if slots["busy"] >= slots["limit"]:
        warnings.append(
            f"Savol-javob navbati to'la ({slots['busy']}/{slots['limit']}, eng eskisi "
            f"{slots['oldestSec']} s) - yangi savollar yordamchiga bormay 503 olyapti"
        )
    if slots["reclaimed"]:
        warnings.append(
            f"Savol-javob navbatidan {slots['reclaimed']} ta oqib ketgan joy qaytarib olingan "
            "(ishga tushgandan beri) - jurnalda 'oqib ketgan joy' ERROR qatoriga qarang"
        )

    # Umumiy HRM token'i - VAQTINCHALIK yechim, uni unutib qo'yish oson, va
    # muddati bir necha daqiqada tugaydi. Ikkalasi ham shu bir qatorda
    # aytiladi: aks holda "nega jonli savol ishlamayapti" degan savolga
    # javob faqat log'da bo'lardi.
    # HAR platforma uchun alohida: HRM tokeni joyida bo'lib, CRM tokeni
    # tugagan bo'lishi mumkin - o'shanda CRM savollari jimgina ishlamay
    # qo'yadi va buni faqat aytib bersa bilish mumkin.
    manual = [("hrm_token", hrm_token_now())]
    # `crm_token` AYTILMAYDI, agar avtomatik sessiya sozlangan bo'lsa:
    # u holda qo'lda yozilgan qiymat umuman ishlatilmaydi, va "muddati
    # tugagan" ogohlantirishi odamni mavjud bo'lmagan muammoga
    # yuborardi. Avtomatik sessiyaning o'z holati pastda.
    if not crm_auth().configured:
        manual.append(("crm_token", crm_token_now()))
    for _key, _token in manual:
        token_note = token_warning(_token, key=_key)
        if token_note:
            warnings.append(token_note)

    # CRM sessiyasi: sozlangan bo'lsa o'zini yangilab turadi, lekin hisob
    # rad etilsa (`USER_NOT_PROVISIONED`) qayta urinish BEFOYDA va buni
    # faqat aytib bersa bilish mumkin.
    crm = crm_auth().status()
    crm_note = crm_auth().warning()
    if crm_note:
        warnings.append(crm_note)

    # Foydalanuvchilarning o'z HRM/CRM ulanishlari. Sozlanmagan bo'lsa "+"
    # menyusidagi tugma "serverda sozlanmagan" deydi - sababi shu yerda.
    hub = connector_hub()
    # Kirish yo'li: SSO (Keycloak, brauzer orqali - `SSO_ISSUER`/`SSO_CLIENT_SECRET`,
    # `services/oidc.py`) yoki zahira (`users.yaml`). Ikkalasi ham yo'q bo'lsa
    # HECH KIM kira olmaydi - va bu `/api/health` da aytilmasa faqat login
    # oynasidagi xatodan bilinardi.
    sso_ready = _sso_configured()
    if not sso_ready and not settings.local_login_enabled:
        warnings.append(
            "kirish yo'li yo'q: SSO (SSO_ISSUER/SSO_CLIENT_ID/SSO_CLIENT_SECRET) "
            "sozlanmagan va LOCAL_LOGIN_ENABLED=false"
        )
    elif not sso_ready:
        warnings.append("SSO_ISSUER / SSO_CLIENT_SECRET bo'sh - Keycloak orqali kirish o'chiq, faqat users.yaml")
    if not hub.hrm.configured:
        warnings.append("hrm_base_url bo'sh - HRM ulanishi (foydalanuvchi hisobi) o'chiq")
    if not hub.crm.configured:
        warnings.append(
            "crm_idp_token_url / crm_client_secret / crm_base_url to'liq emas - "
            "CRM ulanishi (foydalanuvchi hisobi) o'chiq"
        )

    # TTS navbatidagi band joylar. KO'RSATILADI, chunki bu bir marta
    # jimgina to'lib qolgan: ikki joy oqib ketgan va har bir ovoz so'rovi
    # 503 olgan, holbuki xizmatning o'zi mutlaqo sog'lom edi. Buni
    # aniqlash uchun jurnalni qazish kerak bo'lgan - endi shu yerda turadi.
    tts_busy = tts_client().busy()
    if tts_busy >= settings.tts_max_concurrent:
        warnings.append(
            f"TTS navbati to'la ({tts_busy}/{settings.tts_max_concurrent}) - "
            "ovoz javoblari 503 olyapti"
        )

    # QAYSI STT VARIANTI ishlayotgani va PULLIK variantda bugun qancha
    # sarflangani. Bularning ikkisi ham jurnalda bor, lekin hech narsa
    # ularni qo'shmaydi - kvota tugashini esa oldindan bilish kerak, aks
    # holda u foydalanuvchiga XATO ko'rinishida yetib boradi.
    #
    # KALIT QIYMATI YO'Q - faqat sozlangan/sozlanmagan.
    stt_state = stt_variants()
    hold = hold_state()
    if hold["enabled"] and not hold["model_configured"]:
        warnings.append(
            "Kutish ovozi yoqilgan, lekin tasniflovchi model sozlanmagan "
            "(OLLAMA_API_KEY / VENERA_API_URL) - mavzuni faqat kalit so'z jadvali tanlaydi"
        )
    if hold["enabled"] and hold["voices"]["tayyor"] < hold["voices"]["jami"]:
        warnings.append(
            f"Kutish ovozlari to'liq emas ({hold['voices']['tayyor']}/"
            f"{hold['voices']['jami']}) - ovozi yo'q holatlarda kutish ovozi "
            "aytilmaydi (xizmat yangi ishga tushgan bo'lsa ~50 s da to'ladi)"
        )
    for nomi, tanlov in (("STT_PROVIDER", settings.stt_provider),
                         ("STT_WAKE_PROVIDER", settings.stt_wake_provider)):
        if tanlov == "gapi" and not stt_state["gapi_configured"]:
            warnings.append(
                f"{nomi}=gapi, lekin GAPI_API_KEY bo'sh - 1-variant (Router) ishlayapti"
            )
    # ZAHIRA ISHLAYOTGANI - jim degradatsiya. Foydalanuvchi uchun hammasi
    # joyida ko'rinadi, ya'ni buni faqat shu yerda aytish mumkin.
    fb = stt_state["fallback"]
    if fb["last_5min"]:
        warnings.append(
            f"STT zahirasi oxirgi 5 daqiqada {fb['last_5min']} marta ishladi "
            f"(oxirgisi: {fb['last_path']}, kod {fb['last_status']}) - 2-variant "
            "tanlangan, lekin amalda 1-variant (Router) javob berayapti"
        )
    spend = stt_state["gapi_spend"]
    if spend["sent"] > spend["calls"]:
        warnings.append(
            f"GAPI: {spend['sent']} urinish yuborilgan, {spend['calls']} tasi javob bergan - "
            "javobsiz urinishlarning ham puli ketadi"
        )

    # Telegram bot: token bor, lekin o'qiy olmayapti (boshqa nusxa, token
    # bekor qilingan, tarmoq) - bot jim turadi va buni faqat shu yerda
    # ko'rish mumkin.
    telegram = telegram_state()
    if telegram["configured"] and telegram["enabled"]:
        if telegram.get("error"):
            warnings.append(f"Telegram bot xabar ololmayapti: {telegram['error']}")
        elif not telegram.get("running"):
            warnings.append(f"Telegram bot ishlamayapti: {telegram.get('note') or 'sabab jurnalda'}")
        if telegram.get("conflicts_10min"):
            warnings.append(
                f"Telegram bot: boshqa nusxa ham shu tokenni o'qiyapti ({telegram['conflicts_10min']} "
                "marta / 10 daq) - bot ulanishni qaytarib oladi, lekin xabar ba'zan o'sha nusxaga "
                "tushishi mumkin; @BotFather'da tokenni yangilab, faqat jonli .env ga qo'ying"
            )

    # Guruhdagi CRM suhbatlari agentda o'chmayapti (`group_actions.sweep`): ichida guruhdagi
    # boshqa odamlarning xabarlari bor - odam ko'rishi kerak.
    crm = telegram.get("groupCrm") or {}
    if crm.get("stuck"):
        warnings.append(f"Telegram guruh CRM: {crm['stuck']} ta suhbat agentda o'chirilmayapti "
                        "(5+ urinish) - jurnalda 'Telegram guruh CRM' ni qarang")

    # Yig'ilish yozuvchisi: navbat, bugungi daqiqalar, ishchi tirikligi. GAPI
    # kaliti rad etilgan bo'lsa (401/403) - yozuvlar jimgina `failed` bo'lmasin.
    meetings = meetings_state()
    if meetings.get("lastAuthFailureAt") and time.time() - float(meetings["lastAuthFailureAt"]) < 86400:
        keys = "GAPI_API_KEY / GAPI_API_KEY2" if settings.gapi_api_key2 else "GAPI_API_KEY"
        warnings.append(f"Yig'ilishlar: GAPI kaliti rad etildi (401/403) - {keys} ni tekshiring")
    if meetings.get("enabled") and settings.meetings_worker and not meetings.get("worker", {}).get("alive"):
        warnings.append("Yig'ilishlar bo'limi yoqilgan, lekin fon ishchisi ishlamayapti")

    return {
        "status": "degraded" if warnings else "ok",
        "upstream": upstream,
        "version": settings.version,
        "users": len(store),
        "tts_slots": {"busy": tts_busy, "limit": settings.tts_max_concurrent},
        # Yordamchi: dvigatel (umumiy va kanal bo'yicha) va navbat (band /
        # chegara, eng eski joy, qaytarib olinganlar).
        "assistant": assistant,
        "stt": stt_state,
        # Kutish gapi: yoqilganmi, model sozlanganmi, tayyor ovoz nechta.
        "hold": hold,
        # TOKEN QIYMATI YO'Q - faqat holat va muddat.
        "crm_session": crm,
        # Foydalanuvchi ulanishlari: sozlanganmi va nechta odam ulangan.
        # TOKEN YO'Q.
        "connectors": {
            "hrm": hub.hrm.configured,
            "crm": hub.crm.configured,
            "users": hub.store.user_count(),
        },
        # Kirish: SSO sozlanganmi, zahira ochiqmi, SSO bilan nechta odam kirgan.
        "login": {
            "sso": _sso_configured(),
            "local": settings.local_login_enabled,
            "identities": len(get_identity_store()),
        },
        # Telegram bot: ishlayaptimi va nechta odam ulangan. TOKEN YO'Q.
        "telegram": telegram,
        # Yig'ilishlar: holatlar bo'yicha sonlar, bugungi daqiqalar, ishchi. MAZMUN YO'Q.
        "meetings": meetings,
        "warnings": warnings,
    }


@app.get("/api/health", tags=["service"])
@app.get("/health", tags=["service"], include_in_schema=False)
def health() -> dict:
    """OCHIQ holat: faqat tirikligi va versiyasi.

    ATAYLAB MINIMAL. Bu yo'l autentifikatsiyasiz va nginx orqali
    TASHQARIGA ochiq (`llm.brb-tech.uz/api/health`). Ilgari u butun
    tashxisni qaytarardi, ya'ni ismini aytmagan har qanday odam
    quyidagilarni ko'rar edi:

      * `crm_session` - CRM agent hisobi sozlanganmi, necha marta login
        qilgan, va `last_error` da Keycloak ning xom javobi (jonli
        misol: "Account is not fully set up", ya'ni hisob mavjud va
        noto'g'ri sozlangan);
      * `warnings` - qaysi token muddati tugagani, chat sozlanmagani,
        va namuna parollari ishlatilayotgan bo'lsa QAYSI HISOBLAR
        ekani (`main.py` dagi `demo` tekshiruvi emaillarni nomlaydi);
      * `users` - hisoblar soni, `upstream` - ichki xizmatlar holati.

    Bularning hammasi hujum uchun razvedka. `status` esa ochiq qoladi:
    u "e'tibor kerak" deyishga yetadi, nimasi kerakligini aytmaydi -
    monitoring uchun shu kifoya.
    """
    diagnostics = _diagnostics()
    return {"status": diagnostics["status"], "version": diagnostics["version"]}


@app.get("/api/health/detail", tags=["service"])
def health_detail(user: AuthUser = Depends(require_roles("ADMIN"))) -> dict:
    """To'liq tashxis - FAQAT ADMIN.

    IT xodimi uchun mo'ljallangan ma'lumot shu yerda qoladi. Oddiy sessiya
    yetmaydi: ro'yxatdagi har bir satr tizim haqida biror narsani oshkor
    qiladi (ichki xizmatlar holati, sozlanmagan kalitlar, namuna parolli
    hisoblar), va buni har bir xodim ko'rishi shart emas.
    """
    return _diagnostics()
