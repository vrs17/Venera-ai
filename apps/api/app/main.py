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

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from fastapi import Depends

from .api.deps import current_user, docs_viewer, get_user_store
from .api.v1 import router as v1_router
from .core import errors
from .core.config import crm_token_now, hrm_token_now, settings
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
from .services.users import example_password_hashes

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

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
    description="Venera AI - web ilova uchun backend.",
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
    )

app.include_router(v1_router)


#: Yuqoridagi ovoz xizmatlari holati. Keshlanadi - `/api/health` monitoring
#: tomonidan tez-tez so'raladi.
_upstream = UpstreamHealth(settings.stt_base_url, settings.tts_base_url)


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

    return {
        "status": "degraded" if warnings else "ok",
        "upstream": upstream,
        "version": settings.version,
        "users": len(store),
        "tts_slots": {"busy": tts_busy, "limit": settings.tts_max_concurrent},
        # TOKEN QIYMATI YO'Q - faqat holat va muddat.
        "crm_session": crm,
        # Foydalanuvchi ulanishlari: sozlanganmi va nechta odam ulangan.
        # TOKEN YO'Q.
        "connectors": {
            "hrm": hub.hrm.configured,
            "crm": hub.crm.configured,
            "users": hub.store.user_count(),
        },
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
def health_detail(user: AuthUser = Depends(current_user)) -> dict:
    """To'liq tashxis - SESSIYA TALAB QILADI.

    IT xodimi uchun mo'ljallangan ma'lumot shu yerda qoladi. Kirish
    huquqi tekshiriladi, chunki ro'yxatdagi har bir satr tizim haqida
    biror narsani oshkor qiladi.
    """
    return _diagnostics()
