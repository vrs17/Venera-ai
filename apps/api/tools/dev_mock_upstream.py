#!/usr/bin/env python3
"""Yuqoridagi xizmatlarning OFLAYN soxtasi - Venera'ni ichki tarmoqsiz ishlatish uchun.

NEGA KERAK. Venera javobni o'zi yozmaydi: savol HR Assistant'ga, ovoz STT
Router'ga, javob ovozi TTS serveriga boradi - uchalasi ham ICHKI tarmoqda
(`10.10.50.4`). Undan uzilgan kompyuterda chat umuman ishlamaydi, va
frontendning katta qismini (iqtiboslar, hujjat ko'ruvchisi, ariza fayli,
taklif kartasi, suhbatlar tarixi, ovoz paneli) ko'rib bo'lmaydi. Bu fayl
o'sha xizmatlarning HAMMASINI bitta portda taqlid qiladi: Venera API o'zining
HAQIQIY kodi bilan ishlaydi, faqat `.env` dagi manzillar shu yerga qaraydi.

SHAKLLAR TAXMIN EMAS. Har bir maydon Venera'da uni O'QIYDIGAN joydan olingan:

  * `app/services/integrations/assistant.py` - NDJSON kadrlari, `X-Request-Id`,
    `/api/chats`, `/api/actions/{token}`, `/api/hr/artifacts/...`, `/doc/...`;
  * `apps/web/src/types.ts`, `views/ChatView.vue`, `AnswerSources.vue`,
    `MarkdownMessage.vue`, `ActionCard.vue` - brauzer o'qiydigan maydonlar;
  * `app/services/stt.py`, `tts.py`, `upstream.py` - STT/TTS javoblari, `/health`;
  * `tests/test_assistant.py`, `test_chats.py`, `test_actions.py`,
    `test_stt.py`, `test_tts.py` - hujjatdagi va JONLI xizmatda o'lchangan shakllar.

  Jonli xizmatdan olingan farqlar ham takrorlanadi: iqtiboslar `items` kaliti
  ostida keladi (`sources` emas), hujjat kaliti `HR_045` ko'rinishida (pastki
  chiziq bilan), HRM chaqiruvi belgisi qavssiz (`T1`), hujjat nomi kichik
  harfda. `score`, `snippet` va `args` - TAXMIN: jonli xizmat ularni bermasligi
  mumkin, lekin analitika (`services/analytics`) ularni o'qiydi, brauzer esa
  e'tiborsiz qoldiradi.

Ishlatish (apps/api ichidan; faqat standart kutubxona, venv shart emas):

    python3 tools/dev_mock_upstream.py                   # 127.0.0.1:8091
    python3 tools/dev_mock_upstream.py --port 8092
    python3 tools/dev_mock_upstream.py --speed 0         # kechikishsiz (avtomatik testlar)
    python3 tools/dev_mock_upstream.py --strict-tokens   # HRM/CRM tokeni yo'q -> auth_missing
    python3 tools/dev_mock_upstream.py --silent-tts      # TTS jim audio beradi

`.env` - FAQAT LOKAL ishlab chiqish uchun (ishlab chiqarishda HECH QACHON):

    HRM_ASSISTANT_BASE_URL=http://127.0.0.1:8091
    HRM_ASSISTANT_CLIENT_ID=dev-mock
    HRM_ASSISTANT_CLIENT_SECRET=dev-mock
    STT_BASE_URL=http://127.0.0.1:8091
    TTS_BASE_URL=http://127.0.0.1:8091
    TTS_CLIENT_ID=dev-mock
    TTS_CLIENT_SECRET=dev-mock
    TELEGRAM_BOT_ENABLED=false
    # ixtiyoriy - 2-variant STT va kutish ovozi tasnifi ham shu yerga:
    #   GAPI_BASE_URL=http://127.0.0.1:8091/v1  GAPI_API_KEY=dev-mock  STT_PROVIDER=gapi
    #   OLLAMA_BASE_URL=http://127.0.0.1:8091   OLLAMA_API_KEY=dev-mock  HOLD_ENABLED=true

SSENARIYLAR - savoldagi kalit so'z bo'yicha (o'zbek, rus, ingliz). Tartib
MUHIM, yuqoridagisi ustun: "ta'til arizasi" - ariza, "ta'tilim qoldimi" - HRM.

    ssenariy   misol kalit so'zlar                           oxirgi kadrlar              route
    error      kechikdimmi, davomatim, xato, опоздал          error(auth_missing), done   null
    proposal   2 soat yoz, worklog, списать время, vazifa yarat  sources, proposal, token.. crm
    artifact   ariza, заявление, application                 sources, artifact, token..  both
    crm        crm, vazifalarim, mijoz, клиент, задачи, task  sources, token..            crm
    hrm        qoldi, maosh, oylik, зарплата, осталось, salary  sources, token..          hrm|both
    rag        ta'til, qoida, safar, ish vaqti, kasal, отпуск  sources, token..           rules
    clarify    hisobot, отчёт, report                        token..                     clarify
    smalltalk  qolgan hamma narsa (salom, rahmat, ...)        token..                     rules

  Har oqim: bir nechta `stage` (200-600 ms oraliq), keyin kadrlar, keyin
  so'zma-so'z `token` (25-40 ms), oxirida `done` (`route` + `request_id`).
  Javoblar o'zbekcha Markdown, `[1]` / `[T1]` belgilari `items` ga mos.

MAJBURLASH. Savol ichida `mock:<nom>` bo'lsa, kalit so'zdan qat'i nazar shu
ssenariy ishlaydi (masalan "mock:cut ta'til necha kun?"). Yuqoridagilardan
tashqari nosozlik holatlari:

    partial   javobning yarmi, keyin `error` - brauzer javobni ogohlantirish bilan saqlaydi
    cut       kadrlar ORASIDA ulanish uziladi (yiqilgan xizmatning odatiy ko'rinishi).
              `http.client` buni oddiy EOF deb o'qiydi; Venera `done` kelmaganini
              sezib `stream_broken` va `done` yozadi (2026-09-29 tuzatildi)
    torn      kadr O'RTASIDA uziladi - Venera `stream_broken` va `done` yozadi
    busy      oqim ochilmasdan 503 ("navbat to'la")
    fail      oqim ochilmasdan 500
    slow      birinchi so'zdan oldin ~9 s jimlik - kutish ovozini (hold) sinash uchun

HOLAT XOTIRADA: suhbatlar `(user_id, chat_id)` bo'yicha, takliflar (15 daqiqa),
ariza fayllari va TTS tokenlari. Qayta ishga tushsa hammasi yo'qoladi - TTS
tokeni ham, va bu ataylab: Venera 401 olib, tokenni o'zi yangilaydi (jonli
server qayta ishga tushgandagi kabi).

NIMA YO'Q: Keycloak (SSO kirish, CRM agent sessiyasi), HRM/CRM ulanishlari
("+" menyusi) va Telegram Bot API taqlid qilinmaydi - lokal `.env` da ular
sozlanmagan, ya'ni Venera ularni chaqirmaydi. TTS audiosi nutq EMAS -
past ovozli "g'o'ng'illash" (yoki `--silent-tts` bilan jimlik); STT esa
namunaviy savollarni qaytaradi.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import random
import re
import signal
import string
import struct
import sys
import threading
import time
import traceback
import uuid
import zipfile

from array import array
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlsplit
from xml.sax.saxutils import escape as xml_escape


# --- sozlamalar ---------------------------------------------------------------


class _Opts:
    """Buyruq satridagi tanlovlar - `main()` to'ldiradi."""

    speed: float = 1.0          # kechikishlar ko'paytuvchisi; 0 - kechikishsiz
    strict_tokens: bool = False  # HRM/CRM tokeni yo'q savol -> auth_missing
    silent_tts: bool = False     # TTS jim audio beradi


OPTS = _Opts()
_rng = random.Random()
_TASHKENT = timezone(timedelta(hours=5))

#: Jonli xizmatlar chegaralari (hujjat va Venera kodidagi izohlar bo'yicha).
_ACTION_TTL = 15 * 60           # taklif 15 daqiqa yashaydi (`api/v1/actions.py`)
_ARTIFACT_TTL = 24 * 3600
_TTS_TOKEN_TTL = 24 * 3600      # "24 soatlik token" (`services/tts.py`)
_TTS_RATE = 8000                # `x-sample-rate`; frontend ham 8000 ni kutadi
_TTS_MAX_AUDIO_SEC = 20.0       # dev qulayligi: uzun javob ham 20 s dan oshmaydi
_STT_MAX_BYTES = 25 * 1024 * 1024
_VOICES = ("uz_female_calm", "uz_male_news")

_MONTHS = ("yanvar", "fevral", "mart", "aprel", "may", "iyun",
           "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr")
_WEEKDAYS = ("dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba")


def _pause(lo: float, hi: float | None = None) -> None:
    """Tabiiy kechikish. `--speed 0` da umuman kutilmaydi."""
    if OPTS.speed <= 0:
        return
    time.sleep((lo if hi is None else _rng.uniform(lo, hi)) * OPTS.speed)


def _iso(ts: float | None = None) -> str:
    """ISO-8601 UTC, `Z` bilan - `schemas/chats.py` shu shaklni kutadi."""
    return datetime.fromtimestamp(ts if ts is not None else time.time(),
                                  timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today() -> date:
    return datetime.now(_TASHKENT).date()


def _day_month(d: date) -> str:
    return f"{d.day}-{_MONTHS[d.month - 1]}"


def _dmy(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def _key(length: int = 32) -> str:
    """Jonli xizmat kalitlariga o'xshash (`bCqctM12doIGngZiBVLO4t1ZydzGNGVL`)."""
    alphabet = string.ascii_letters + string.digits
    return "".join(random.SystemRandom().choice(alphabet) for _ in range(length))


_log_lock = threading.Lock()


def _log(message: str) -> None:
    with _log_lock:
        print(f"{time.strftime('%H:%M:%S')} {message}", flush=True)


# --- PDF (qo'lda, xref bilan) --------------------------------------------------
#
# Hujjat ko'ruvchisi pdf.js bilan chizadi (`DocViewer.vue`), ya'ni fayl HAQIQIY
# PDF bo'lishi shart: to'g'ri `xref`, aniq `/Length`. Shrift - standart 14
# talikdan Helvetica, WinAnsi kodlashda: o'zbek lotin yozuvi (', «», –) sig'adi.


def _pdf_str(text: str) -> bytes:
    text = text.replace("ʻ", "'").replace("ʼ", "'").replace("‘", "'").replace("’", "'")
    raw = text.encode("cp1252", "replace")
    return b"(" + raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def _pdf_info_str(text: str) -> bytes:
    """`Info` lug'ati uchun matn - UTF-16BE, BOM bilan. Bu yerda WinAnsi EMAS:
    hujjat xususiyatlari PDFDocEncoding'da o'qiladi va "—" buzilib chiqardi."""
    return b"<FEFF" + text.encode("utf-16-be").hex().upper().encode() + b">"


class _Canvas:
    """Bitta sahifaning kontent oqimi."""

    def __init__(self) -> None:
        self.ops: list[bytes] = []

    def text(self, x: float, y: float, text: str, font: str = "F1", size: float = 10.5,
             gray: float = 0.0) -> None:
        self.ops.append(f"BT {gray:.2f} g /{font} {size} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ".encode()
                        + _pdf_str(text) + b" Tj ET")

    def rect(self, x: float, y: float, w: float, h: float, rgb: tuple[float, float, float]) -> None:
        r, g, b = rgb
        self.ops.append(f"{r:.3f} {g:.3f} {b:.3f} rg {x:.2f} {y:.2f} {w:.2f} {h:.2f} re f 0 g".encode())

    def hline(self, x1: float, x2: float, y: float, gray: float = 0.8, width: float = 0.6) -> None:
        self.ops.append(f"{gray:.2f} G {width} w {x1:.2f} {y:.2f} m {x2:.2f} {y:.2f} l S 0 G".encode())

    def bytes(self) -> bytes:
        return b"\n".join(self.ops)


def _text_width(text: str, size: float) -> float:
    """Helvetica uchun taxminiy kenglik - markazlash va o'ngga tekislash uchun yetarli."""
    return len(text) * size * 0.5


def _wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    if line:
        lines.append(line)
    return lines


def _pdf(pages: list[bytes], title: str) -> bytes:
    """Kontent oqimlaridan to'liq PDF: katalog, sahifalar, uchta shrift, `Info`, `xref`."""
    objs: dict[int, bytes] = {}
    first_page = 7
    kids = " ".join(f"{first_page + 2 * i} 0 R" for i in range(len(pages)))
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()
    for num, base in ((3, "Helvetica"), (4, "Helvetica-Bold"), (5, "Helvetica-Oblique")):
        objs[num] = (f"<< /Type /Font /Subtype /Type1 /BaseFont /{base} "
                     "/Encoding /WinAnsiEncoding >>").encode()
    stamp = datetime.now(timezone.utc).strftime("D:%Y%m%d%H%M%SZ")
    objs[6] = (b"<< /Title " + _pdf_info_str(title) + b" /Producer (Venera dev mock) /CreationDate "
               + _pdf_str(stamp) + b" >>")
    for i, content in enumerate(pages):
        page_no, content_no = first_page + 2 * i, first_page + 2 * i + 1
        objs[page_no] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                         f"/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> "
                         f"/Contents {content_no} 0 R >>").encode()
        objs[content_no] = (f"<< /Length {len(content)} >>\nstream\n".encode()
                            + content + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    size = max(objs) + 1
    for num in range(1, size):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objs[num] + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {size}\n".encode() + b"0000000000 65535 f \n"
    for num in range(1, size):
        out += f"{offsets[num]:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {size} /Root 1 0 R /Info 6 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n").encode()
    return bytes(out)


# --- hujjatlar katalogi ------------------------------------------------------


@dataclass(frozen=True)
class Passage:
    """Hujjatdagi bitta bo'lim. Iqtibos `snippet` i va PDF'dagi sariq
    belgilangan matn AYNAN shu - ya'ni ko'ruvchi ochgan sahifada odam
    javobdagi da'voni o'z ko'zi bilan ko'radi."""

    doc_id: str
    page: int
    section: str
    heading: str
    text: str


DOCS: dict[str, dict[str, Any]] = {
    "HR_012": {"title": "Mehnat ta'tillari to'g'risidagi nizom", "pages": 8,
               "approved": "Bosh direktorning 2025-yil 14-yanvardagi 7-son buyrug'i bilan tasdiqlangan"},
    "HR_019": {"title": "Vaqtincha mehnatga layoqatsizlik varaqalarini rasmiylashtirish tartibi",
               "pages": 5,
               "approved": "Bosh direktorning 2024-yil 2-sentabrdagi 112-son buyrug'i bilan tasdiqlangan"},
    "HR_027": {"title": "Mehnatga haq to'lash va mukofotlash to'g'risidagi nizom", "pages": 9,
               "approved": "Kuzatuv kengashining 2025-yil 28-fevraldagi qarori bilan tasdiqlangan"},
    "HR_031": {"title": "Xizmat safarlari tartibi to'g'risidagi yo'riqnoma", "pages": 6,
               "approved": "Bosh direktorning 2025-yil 3-martdagi 29-son buyrug'i bilan tasdiqlangan"},
    # 24 sahifa - jonli xizmat bu hujjatdan 22-sahifani iqtibos qilgan
    # (`test_assistant.py: test_jonli_kadr_shakli`), va brauzer keshida
    # qolgan o'sha havola ham ochilishi kerak.
    "HR_045": {"title": "Ichki mehnat tartibi qoidalari", "pages": 24,
               "approved": "Bosh direktorning 2025-yil 12-maydagi 48-son buyrug'i bilan tasdiqlangan"},
    "HR_058": {"title": "Kiyinish madaniyati (dress-kod) standarti", "pages": 4,
               "approved": "Bosh direktorning 2024-yil 20-dekabrdagi 171-son buyrug'i bilan tasdiqlangan"},
}

PASSAGES: dict[str, Passage] = {
    "leave_min": Passage("HR_012", 4, "3.2", "Yillik asosiy ta'til",
                         "Xodimlarga har yili kamida 21 kalendar kunlik asosiy haq to'lanadigan "
                         "mehnat ta'tili beriladi."),
    "leave_split": Passage("HR_012", 6, "4.1", "Ta'tilni qismlarga bo'lish",
                           "Xodimning xohishiga ko'ra ta'til qismlarga bo'linishi mumkin, bunda "
                           "qismlardan biri kamida 14 kalendar kun bo'lishi shart."),
    "leave_apply": Passage("HR_012", 7, "5.2", "Ariza berish tartibi",
                           "Ta'til to'g'risidagi ariza ta'til boshlanishidan kamida uch ish kuni "
                           "oldin bo'lim rahbari bilan kelishilgan holda Kadrlar bo'limiga "
                           "topshiriladi."),
    "hours": Passage("HR_045", 3, "2.1", "Ish vaqti",
                     "Jamiyatda besh kunlik ish haftasi belgilangan: ish kuni soat 09:00 dan "
                     "18:00 gacha, tushlik tanaffusi 13:00 dan 14:00 gacha."),
    "leave_schedule": Passage("HR_045", 5, "7.1", "Ta'tillar jadvali",
                              "Ta'tillar jadvali har yili 15-dekabrgacha tasdiqlanadi va har bir "
                              "xodim imzo qo'ydirilgan holda u bilan tanishtiriladi."),
    "late": Passage("HR_045", 9, "4.3", "Kechikish va davomat",
                    "Ish vaqtining boshlanishiga 15 daqiqadan ortiq kechikish mehnat intizomining "
                    "buzilishi hisoblanadi va bo'lim rahbariga bildiriladi."),
    "final": Passage("HR_045", 22, "70", "Yakuniy qoidalar",
                     "Ushbu qoidalarga o'zgartirishlar kasaba uyushmasi qo'mitasi bilan kelishilgan "
                     "holda Bosh direktor buyrug'i bilan kiritiladi."),
    "trip_order": Passage("HR_031", 2, "2.1", "Safarga yuborish",
                          "Xizmat safariga yuborish bo'lim rahbarining taqdimnomasi asosida Bosh "
                          "direktor buyrug'i bilan rasmiylashtiriladi."),
    "trip_advance": Passage("HR_031", 3, "3.4", "Avans va hisobot",
                            "Safar xarajatlari uchun avans safardan kamida ikki ish kuni oldin "
                            "beriladi; bo'nak hisoboti qaytgandan keyin uch ish kuni ichida "
                            "topshiriladi."),
    "pay_dates": Passage("HR_027", 4, "3.1", "Ish haqi to'lash muddatlari",
                         "Ish haqi oyda ikki marta to'lanadi: avans joriy oyning 25-sanasida, "
                         "qolgan qismi keyingi oyning 10-sanasida."),
    "per_diem": Passage("HR_027", 7, "6.2", "Sutkalik xarajatlar",
                        "Respublika hududidagi xizmat safarlarida sutkalik xarajatlar eng kam "
                        "ish haqining 10 foizi miqdorida qoplanadi."),
    "dress": Passage("HR_058", 2, "1.2", "Umumiy talablar",
                     "Ish kunlari xodimlar ishbilarmonlik uslubidagi kiyimda bo'lishi kerak; "
                     "juma kuni erkin (smart casual) uslubga ruxsat etiladi."),
    "sick_notify": Passage("HR_019", 4, "4.1", "Xabar berish",
                           "Xodim kasallik haqida ish kunining birinchi soatida bevosita "
                           "rahbariga xabar berishi shart."),
    "sick_list": Passage("HR_019", 2, "2.1", "Elektron varaqa",
                         "Kasallik varaqasi tibbiyot muassasasi tomonidan elektron shaklda beriladi "
                         "va xodim ishga chiqqan kuni uning raqamini Kadrlar bo'limiga taqdim etadi."),
    "sick_pay": Passage("HR_019", 3, "3.2", "Nafaqa miqdori",
                        "Vaqtincha mehnatga layoqatsizlik nafaqasi ish stajiga qarab o'rtacha ish "
                        "haqining 60 foizidan 100 foizigacha miqdorda to'lanadi."),
}

_FILLER_HEADINGS = ("Umumiy qoidalar", "Asosiy tushunchalar", "Tomonlarning huquq va majburiyatlari",
                    "Rasmiylashtirish tartibi", "Nazorat va javobgarlik", "Hisobot va hujjatlar",
                    "Alohida holatlar", "Kelishmovchiliklarni hal etish")
_FILLER = (
    "Ushbu bo'lim talablari jamiyatning barcha tarkibiy bo'linmalari uchun majburiydir.",
    "Bo'lim rahbarlari xodimlarni ushbu tartib bilan imzo qo'ydirib tanishtirishga mas'uldir.",
    "Hujjatda nazarda tutilmagan masalalar amaldagi qonunchilikka muvofiq hal etiladi.",
    "Hujjatlar elektron shaklda HRM tizimida yuritiladi va arxivda besh yil saqlanadi.",
    "Xodim o'z huquqlari buzilgan deb hisoblasa, Kadrlar bo'limiga yozma murojaat qilishi mumkin.",
    "Ijro ustidan nazorat Kadrlar bo'limi boshlig'i zimmasiga yuklatiladi.",
    "O'zgartirishlar tasdiqlangan kundan boshlab o'n kun ichida barcha xodimlarga e'lon qilinadi.",
    "Tartib buzilganda intizomiy javobgarlik Mehnat kodeksida belgilangan tartibda qo'llaniladi.",
    "Bo'linmalar o'rtasidagi kelishmovchiliklar Bosh direktor o'rinbosari tomonidan ko'rib chiqiladi.",
    "Murojaatlar kelib tushgan kundan boshlab o'n besh kun ichida ko'rib chiqiladi.",
    "Ushbu talablar sinov muddatidagi xodimlarga ham to'liq tatbiq etiladi.",
)


def _doc_meta(doc_id: str) -> dict[str, Any]:
    """Katalogda yo'q kalit uchun ham hujjat - eski iqtibos havolasi bo'sh qolmasin."""
    return DOCS.get(doc_id) or {"title": f"Ichki hujjat {doc_id}", "pages": 3,
                                "approved": "Ichki hujjat (katalogda yo'q - umumiy namuna)"}


_pdf_cache: dict[str, bytes] = {}


def doc_pdf(doc_id: str) -> bytes:
    """Iqtibos qilingan hujjat: sarlavha, bo'limlar, iqtibos matni sariq fonda."""
    cached = _pdf_cache.get(doc_id)
    if cached:
        return cached
    meta = _doc_meta(doc_id)
    total = int(meta["pages"])
    cited: dict[int, list[Passage]] = {}
    for passage in PASSAGES.values():
        if passage.doc_id == doc_id:
            cited.setdefault(passage.page, []).append(passage)
    pages: list[bytes] = []
    for n in range(1, total + 1):
        rng = random.Random(f"{doc_id}:{n}")
        c = _Canvas()
        c.text(56, 810, f"BRB-TECH  ·  {meta['title']}", "F1", 8, gray=0.45)
        c.text(539 - _text_width(doc_id.replace("_", "-"), 8), 810, doc_id.replace("_", "-"),
               "F1", 8, gray=0.45)
        c.hline(56, 539, 800)
        y = 772.0
        if n == 1:
            for line in _wrap(meta["title"].upper(), 48):
                c.text(56, y, line, "F2", 15)
                y -= 20
            y -= 4
            c.text(56, y, meta["approved"], "F3", 9, gray=0.35)
            y -= 14
            c.hline(56, 539, y, gray=0.85)
            y -= 26
        sections: list[tuple[str, str, str, bool]] = [
            (p.section, p.heading, p.text, True) for p in cited.get(n, [])]
        # Iqtibos bo'limi sahifaning o'rtasiga tushsin: oldida bitta
        # to'ldiruvchi bo'lim, keyin iqtibos, keyin sahifa to'lguncha yana.
        headings = rng.sample(_FILLER_HEADINGS, 6)
        for k, heading in enumerate(headings, start=1):
            filler = (f"{n}.{k}", heading, " ".join(rng.sample(_FILLER, 3)), False)
            sections.insert(0 if k == 1 else len(sections), filler)
            if y - sum(30 + 14.5 * len(_wrap(s[2], 88)) for s in sections) < 150:
                break
        for number, heading, body, highlighted in sections:
            lines = _wrap(body, 88)
            if y - (22 + 14.5 * len(lines)) < 70:
                break
            c.text(56, y, f"{number}. {heading}", "F2", 11.5)
            y -= 18
            if highlighted:
                height = 14.5 * len(lines) + 6
                c.rect(52, y - height + 11, 491, height, (1.0, 0.94, 0.66))
            for line in lines:
                c.text(60, y, line, "F1", 10.5)
                y -= 14.5
            y -= 12
        c.hline(56, 539, 52, gray=0.9)
        c.text(56, 38, "NAMUNA - Venera dev mock, haqiqiy hujjat emas", "F3", 7.5, gray=0.5)
        label = f"{n} / {total}"
        c.text(539 - _text_width(label, 9), 38, label, "F1", 9, gray=0.35)
        pages.append(c.bytes())
    data = _pdf(pages, meta["title"])
    _pdf_cache[doc_id] = data
    return data


# --- ariza fayli (PDF va DOCX) -------------------------------------------------

_PEOPLE = (
    ("Karimova Dilnoza Rustamovna", "Bosh mutaxassis", "Axborot texnologiyalari departamenti"),
    ("Rahimov Aziz Baxtiyorovich", "HR mutaxassisi", "Xodimlar bilan ishlash bo'limi"),
    ("Yusupova Malika Sherzodovna", "Sotuv menejeri", "Korporativ sotuvlar bo'limi"),
    ("Tursunov Jasur Anvarovich", "Yetakchi dasturchi", "Raqamli mahsulotlar departamenti"),
    ("Abdullayeva Nigora Olimovna", "Buxgalter", "Moliya va hisob bo'limi"),
)


def _profile(user_id: str) -> tuple[str, str, str]:
    """Soxta HRM profili - bir odam uchun doim bir xil (kalit xeshi bo'yicha)."""
    digest = hashlib.sha1(user_id.encode("utf-8")).digest()
    return _PEOPLE[digest[0] % len(_PEOPLE)]


_UNITS = ("", "bir", "ikki", "uch", "to'rt", "besh", "olti", "yetti", "sakkiz", "to'qqiz")
_TENS = ("", "o'n", "yigirma", "o'ttiz")


def _words(n: int) -> str:
    tens, units = divmod(n, 10)
    return " ".join(w for w in (_TENS[tens], _UNITS[units]) if w) or "nol"


def _leave_lines(art: dict[str, Any]) -> dict[str, Any]:
    name, position, department = art["profile"]
    start, end, days = art["start"], art["end"], art["days"]
    surname, first = name.split()[0], name.split()[1]
    return {
        "to": ["«BRB-TECH» MChJ", "Bosh direktori", "A. B. Sobirovga", department,
               position, f"{surname} {first[0]}.dan"],
        "title": "ARIZA",
        "body": (f"Menga {_dmy(start)}-yildan {_dmy(end)}-yilgacha {days} ({_words(days)}) "
                 "kalendar kunlik yillik asosiy mehnat ta'tilini berishingizni so'rayman. "
                 "Ta'til davrida joriy vazifalarim bo'lim hamkasbimga topshiriladi."),
        "date": f"Sana: {_dmy(art['created'])}",
        "sign": "Imzo: ______________",
        "agreed": "Kelishildi: bo'lim rahbari ______________",
        "foot": f"Venera tomonidan tayyorlangan  ·  {art['doc_id']}  ·  NAMUNA (dev mock)",
    }


def artifact_pdf(art: dict[str, Any], *, preview: bool = False) -> bytes:
    t = _leave_lines(art)
    c = _Canvas()
    if preview:
        c.rect(0, 812, 595, 30, (0.93, 0.95, 0.99))
        c.text(56, 823, "KO'RIB CHIQISH NUSXASI - imzolashdan oldin tekshiring", "F2", 9, gray=0.3)
    y = 760.0
    for line in t["to"]:
        c.text(330, y, line, "F1", 11)
        y -= 16
    c.text((595 - _text_width(t["title"], 16)) / 2, 600, t["title"], "F2", 16)
    y = 560.0
    for i, line in enumerate(_wrap(t["body"], 80)):
        c.text(92 if i == 0 else 72, y, line, "F1", 11.5)
        y -= 18
    y -= 30
    c.text(72, y, t["date"], "F1", 11)
    c.text(523 - _text_width(t["sign"], 11), y, t["sign"], "F1", 11)
    y -= 40
    c.text(72, y, t["agreed"], "F3", 10.5, gray=0.25)
    c.hline(56, 539, 52, gray=0.9)
    c.text(56, 38, t["foot"], "F3", 7.5, gray=0.5)
    return _pdf([c.bytes()], art["title"])


def artifact_docx(art: dict[str, Any]) -> bytes:
    """Minimal, lekin HAQIQIY DOCX - Word ham, LibreOffice ham ochadi."""
    t = _leave_lines(art)

    def para(text: str, *, align: str | None = None, bold: bool = False, size: int = 24,
             before: int = 0) -> str:
        ppr = "".join([f'<w:jc w:val="{align}"/>' if align else "",
                       f'<w:spacing w:before="{before}"/>' if before else ""])
        rpr = ("<w:b/>" if bold else "") + f'<w:sz w:val="{size}"/>'
        return (f"<w:p><w:pPr>{ppr}</w:pPr><w:r><w:rPr>{rpr}</w:rPr>"
                f'<w:t xml:space="preserve">{xml_escape(text)}</w:t></w:r></w:p>')

    body = "".join(para(line, align="right") for line in t["to"])
    body += para(t["title"], align="center", bold=True, size=32, before=600)
    body += para(t["body"], align="both", before=240)
    body += para(t["date"], before=480) + para(t["sign"], align="right")
    body += para(t["agreed"], before=360) + para(t["foot"], size=16, before=720)
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f"<w:body>{body}<w:sectPr/></w:body></w:document>")
    types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Override PartName="/word/document.xml" ContentType="application/'
             'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document)
    return buffer.getvalue()


# --- audio ---------------------------------------------------------------------


def _pcm_bytes(samples: array) -> bytes:
    """16-bit LITTLE-endian - `audio/L16` va WAV shuni talab qiladi."""
    if sys.byteorder == "big":
        samples = array("h", samples)
        samples.byteswap()
    return samples.tobytes()


def _murmur(seconds: float, rate: int, seed: int) -> bytes:
    """Nutqqa o'xshash past ovozli g'o'ng'illash: bo'g'in ritmi (~4 Hz) va
    ohang egri chizig'i bilan. Sof sinus quloqni charchatadi, bu esa yo'q."""
    n = max(1, int(seconds * rate))
    out = array("h", bytes(2 * n))
    if OPTS.silent_tts:
        return _pcm_bytes(out)
    f0 = 150.0 + 18.0 * (seed % 3)
    fade = max(1, int(0.02 * rate))
    amp = 0.16 * 32767 / 1.47
    two_pi = 2.0 * math.pi
    for i in range(n):
        t = i / rate
        envelope = (0.5 - 0.5 * math.cos(two_pi * 4.3 * t)) * min(1.0, i / fade, (n - 1 - i) / fade)
        phase = two_pi * (f0 * t + 3.0 * math.sin(two_pi * 0.9 * t))
        out[i] = int(amp * envelope * (math.sin(phase) + 0.35 * math.sin(2 * phase)
                                       + 0.12 * math.sin(3 * phase)))
    return _pcm_bytes(out)


def speech_chunks(text: str, rate: int = _TTS_RATE) -> list[bytes]:
    """Matn -> PCM bo'laklari: har gap bo'lagi uchun bittasi, orasida 160 ms pauza.

    Jonli server ham matnni tinish belgilari bo'yicha bo'laklab, har birini
    tayyor bo'lishi bilan yuboradi (`services/tts.py` izohi).
    """
    phrases = [p for p in re.split(r"(?<=[.!?;:,\n])\s+", text.strip()) if p.strip()] or [text]
    gap = bytes(2 * int(0.16 * rate))
    chunks: list[bytes] = []
    total = 0.0
    for i, phrase in enumerate(phrases):
        seconds = min(3.0, max(0.35, 0.055 * len(phrase)))
        seconds = min(seconds, _TTS_MAX_AUDIO_SEC - total)
        if seconds < 0.2:
            break
        chunks.append(_murmur(seconds, rate, i) + gap)
        total += seconds + 0.16
    return chunks


def wav_header(pcm_len: int, rate: int) -> bytes:
    """44 baytlik PCM WAV sarlavhasi, 16-bit mono. Uzunlik ANIQ yoziladi: jonli
    server oqim boshida uni bilmay `0xFFFFFFFF` yozadi, soxta esa hammasini
    oldindan yasaydi - shuning uchun pleyer davomiylikni to'g'ri ko'rsatadi."""
    return (b"RIFF" + struct.pack("<I", 36 + pcm_len) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", pcm_len))


def _wav_info(data: bytes) -> dict[str, Any] | None:
    """RIFF/WAVE bo'laklarini o'qiydi. Oqimli WAV (`0xFFFFFFFF`) ham tushunadi."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    pos, fmt = 12, None
    while pos + 8 <= len(data):
        chunk_id = data[pos:pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        start = pos + 8
        if chunk_id == b"fmt " and size >= 16:
            fmt = struct.unpack_from("<HHIIHH", data, start)
        elif chunk_id == b"data":
            if fmt is None:
                return None
            end = len(data) if size in (0, 0xFFFFFFFF) or start + size > len(data) else start + size
            return {"channels": fmt[1], "rate": fmt[2], "bits": fmt[5], "pcm": data[start:end]}
        pos = start + size + (size & 1)
    return None


def _audio_facts(data: bytes, filename: str) -> tuple[float, bool]:
    """(davomiylik, jimmi). WAV aniq o'lchanadi; siqilgan formatlar - taxminan
    32 kbit/s bo'yicha (Opus ovoz uchun odatiy)."""
    info = _wav_info(data)
    if not info or not info["rate"] or not info["channels"] or not info["bits"]:
        return round(len(data) / 4000.0, 2), False
    frame_bytes = info["channels"] * info["bits"] // 8
    seconds = len(info["pcm"]) / float(info["rate"] * frame_bytes)
    silent = False
    if info["bits"] == 16 and len(info["pcm"]) >= 2:
        samples = array("h")
        samples.frombytes(info["pcm"][: len(info["pcm"]) // 2 * 2])
        if sys.byteorder == "big":
            samples.byteswap()
        silent = max((abs(s) for s in samples[::7]), default=0) < 500
    return round(seconds, 2), silent


_SAMPLE_QUESTIONS = {
    "uz": ("Yillik ta'tilim necha kun qoldi?", "Xizmat safari qanday rasmiylashtiriladi?",
           "Mening CRM dagi vazifalarim qanday?", "Keyingi oylik qachon tushadi?",
           "Ish vaqti soat nechadan nechagacha?"),
    "ru": ("Сколько дней отпуска у меня осталось?", "Какие у меня задачи в CRM?",
           "Когда будет зарплата?"),
    "en": ("How many vacation days do I have left?", "What are my CRM tasks?",
           "When is the next salary payment?"),
    "zh": ("我还剩几天年假？",),
}


def transcript_for(data: bytes, filename: str, language: str) -> tuple[str, float]:
    """Namunaviy matn. Uch holat, uchalasi ham brauzerda sinash uchun kerak:

      * jimlik -> bo'sh matn ("hech narsa eshitilmadi");
      * qisqa (<= 2.7 s) o'zbekcha parcha -> "Salom Venera" - uyg'otish
        so'zi (`/stt/wake` parchasi 0.35-2.6 s bo'ladi);
      * qolgani -> namunaviy savol; bir xil audio doim bir xil savol beradi.
    """
    seconds, silent = _audio_facts(data, filename)
    if silent:
        return "", seconds
    if language == "uz" and seconds <= 2.7:
        return "Salom Venera", seconds
    options = _SAMPLE_QUESTIONS.get(language) or _SAMPLE_QUESTIONS["uz"]
    return options[hashlib.sha1(data).digest()[0] % len(options)], seconds


# --- holat (xotirada) ----------------------------------------------------------


def _chat_title(question: str) -> str:
    """Birinchi savolning boshi - jonli xizmat ham suhbatni shunday nomlaydi."""
    text = re.sub(r"\s+", " ", _DIRECTIVE.sub("", question)).strip() or "Yangi suhbat"
    if len(text) <= 60:
        return text
    cut = text[:60]
    return (cut[: cut.rfind(" ")] if cut.rfind(" ") > 30 else cut).rstrip(" ,.;:") + "…"


class ChatStore:
    """Suhbatlar tarixi - `(user_id, chat_id)` bo'yicha, yumshoq o'chirish bilan."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._chats: dict[tuple[str, str], dict[str, Any]] = {}

    @staticmethod
    def _summary(chat: dict[str, Any]) -> dict[str, Any]:
        return {"chat_id": chat["chat_id"], "title": chat["title"],
                "title_source": chat["title_source"], "created_at": _iso(chat["created"]),
                "updated_at": _iso(chat["updated"]), "messages": len(chat["messages"])}

    def add_turn(self, user_id: str, chat_id: str, question: str, answer: str,
                 asked: float, answered: float) -> None:
        with self._lock:
            chat = self._chats.get((user_id, chat_id))
            if chat is None:
                chat = {"chat_id": chat_id, "title": _chat_title(question), "title_source": "auto",
                        "created": asked, "updated": answered, "deleted": False, "messages": []}
                self._chats[(user_id, chat_id)] = chat
            # O'chirilgan suhbatga yangi savol uni QAYTARADI (`assistant.py`).
            chat["deleted"] = False
            chat["updated"] = answered
            chat["messages"] += [
                {"role": "user", "content": question, "created_at": _iso(asked)},
                {"role": "assistant", "content": answer, "created_at": _iso(answered)},
            ]

    def listing(self, user_id: str, limit: int, offset: int) -> dict[str, Any]:
        with self._lock:
            mine = sorted((c for (uid, _), c in self._chats.items()
                           if uid == user_id and not c["deleted"]),
                          key=lambda c: c["updated"], reverse=True)
            return {"items": [self._summary(c) for c in mine[offset:offset + limit]],
                    "limit": limit, "offset": offset}

    def detail(self, user_id: str, chat_id: str, limit: int) -> dict[str, Any] | None:
        with self._lock:
            chat = self._chats.get((user_id, chat_id))
            if chat is None or chat["deleted"]:
                return None
            out = self._summary(chat)
            out["messages"] = [dict(m) for m in chat["messages"][-limit:]]
            return out

    def rename(self, user_id: str, chat_id: str, title: str) -> dict[str, Any] | None:
        with self._lock:
            chat = self._chats.get((user_id, chat_id))
            if chat is None or chat["deleted"]:
                return None
            chat["title"], chat["title_source"] = title, "user"
            return self._summary(chat)

    def delete(self, user_id: str, chat_id: str) -> bool:
        with self._lock:
            chat = self._chats.get((user_id, chat_id))
            if chat is None:
                return False
            chat["deleted"] = True          # takroriy chaqiruv ham 200
            return True

    def restore(self, user_id: str, chat_id: str) -> dict[str, Any] | None:
        with self._lock:
            chat = self._chats.get((user_id, chat_id))
            if chat is None:
                return None
            chat["deleted"] = False
            return self._summary(chat)

    def count(self) -> int:
        with self._lock:
            return len(self._chats)


class ActionStore:
    """Taklif qilingan yozuv amallari: pending -> executed | cancelled | expired."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, dict[str, Any]] = {}

    def create(self, user_id: str, proposal: dict[str, Any], outcome: dict[str, Any]) -> str:
        token = _key()
        with self._lock:
            self._items[token] = {"token": token, "user_id": user_id, "status": "pending",
                                  "summary": proposal["summary"], "operation": proposal["operation"],
                                  "connector": proposal["connector"], "outcome": outcome,
                                  "expires": time.time() + _ACTION_TTL, "ok": None,
                                  "error": None, "result": None}
        return token

    @staticmethod
    def _view(item: dict[str, Any], request_id: str) -> dict[str, Any]:
        return {k: item[k] for k in ("token", "status", "summary", "operation", "connector",
                                     "ok", "error", "result")} | {"request_id": request_id}

    def _fresh(self, token: str) -> dict[str, Any] | None:
        item = self._items.get(token)
        if item and item["status"] == "pending" and time.time() > item["expires"]:
            item["status"], item["ok"] = "expired", False
            item["error"] = "Taklif muddati tugagan (15 daqiqa)"
        return item

    def get(self, token: str, request_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._fresh(token)
            return self._view(item, request_id) if item else None

    def decide(self, token: str, verb: str, user_id: str, request_id: str) -> tuple[int, dict[str, Any]]:
        with self._lock:
            item = self._fresh(token)
            # Boshqa odamning taklifi ham "yo'q" - kalit ma'lum bo'lsa ham.
            if item is None or item["user_id"] != user_id:
                return 404, {"detail": {"code": "not_found", "message": "No such proposal for this user."}}
            if item["status"] == "expired":
                return 404, {"detail": {"code": "expired", "message": "Proposal expired."}}
            if item["status"] == "pending":
                if verb == "confirm":
                    item["status"], item["ok"] = "executed", True
                    item["result"] = dict(item["outcome"])
                else:
                    item["status"] = "cancelled"
            elif not (verb == "confirm" and item["status"] == "executed"
                      or verb == "cancel" and item["status"] == "cancelled"):
                item_error = ("Taklif allaqachon bajarilgan" if item["status"] == "executed"
                              else "Taklif allaqachon rad etilgan")
                return 200, self._view(item, request_id) | {"error": item_error}
            return 200, self._view(item, request_id)

    def count(self) -> int:
        with self._lock:
            return len(self._items)


class ArtifactStore:
    """Yaratilgan ariza fayllari: kalit -> ma'lumot; baytlar so'ralganda yasaladi."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, dict[str, Any]] = {}

    def create(self, art: dict[str, Any]) -> str:
        token = _key()
        with self._lock:
            self._items[token] = art | {"expires": time.time() + _ARTIFACT_TTL}
        return token

    def get(self, token: str) -> dict[str, Any] | None:
        with self._lock:
            art = self._items.get(token)
            return art if art and time.time() < art["expires"] else None

    def count(self) -> int:
        with self._lock:
            return len(self._items)


class TtsTokens:
    """TTS tokenlari. Qayta ishga tushsa eskilari 401 oladi - Venera yangilaydi."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, float] = {}

    def issue(self) -> str:
        token = f"mock-{uuid.uuid4().hex}"
        with self._lock:
            self._items[token] = time.time() + _TTS_TOKEN_TTL
        return token

    def valid(self, token: str) -> bool:
        with self._lock:
            return self._items.get(token, 0.0) > time.time()

    def count(self) -> int:
        with self._lock:
            return len(self._items)


CHATS = ChatStore()
ACTIONS = ActionStore()
ARTIFACTS = ArtifactStore()
TTS_TOKENS = TtsTokens()


# --- ssenariylar -----------------------------------------------------------


@dataclass
class Ctx:
    """Bitta savol haqida hamma narsa."""

    question: str
    q: str                  # kichik harf, apostroflar bir xil
    user_id: str
    chat_id: str | None
    tokens: dict[str, str]
    base: str               # soxtaning o'z manzili - "ichki" havolalar uchun
    request_id: str


@dataclass
class Plan:
    """Oqim rejasi: qadamlar, tarixga yoziladigan javob va xato holati."""

    scenario: str
    steps: list[tuple] = field(default_factory=list)
    answer: str = ""
    store: bool = True
    http_error: tuple[int, dict[str, Any]] | None = None

    def stage(self, name: str, text: str, lo: float = 0.2, hi: float = 0.6) -> "Plan":
        """Bosqich kadri. Oldingi bosqichdan beri o'tgan kutish HISOBGA olinadi:
        oradagi `sources`/`artifact` kadrlari bilan birga ham oraliq [lo, hi]
        ichida qoladi (brauzer bosqich matnini shu tezlikda almashtiradi)."""
        spent_lo = spent_hi = 0.0
        for step in reversed(self.steps):
            if step[0] == "frame" and step[1].get("type") == "stage":
                break
            if step[0] == "wait":
                spent_lo, spent_hi = spent_lo + step[1], spent_hi + step[2]
        wait_lo = max(0.0, lo - spent_lo)
        wait_hi = max(wait_lo, hi - spent_hi)
        self.steps += [("wait", wait_lo, wait_hi),
                       ("frame", {"type": "stage", "stage": name, "text": text})]
        return self

    def frame(self, frame: dict[str, Any], lo: float = 0.05, hi: float = 0.15) -> "Plan":
        self.steps += [("wait", lo, hi), ("frame", frame)]
        return self

    def sources(self, items: list[dict[str, Any]]) -> "Plan":
        # `items` - JONLI shakl (`sources` hujjatdagi bir martalik javobniki).
        return self.frame({"type": "sources", "items": items})

    def write(self, answer: str) -> "Plan":
        """Javob matni: "yozilmoqda" bosqichi, birinchi so'zgacha pauza, keyin so'zma-so'z."""
        self.answer = answer
        self.stage("generation", "Javob yozilmoqda")
        self.steps += [("wait", 0.3, 0.6), ("tokens", answer)]
        return self

    def done(self, route: str | None) -> "Plan":
        self.steps.append(("done", route))
        return self


def _doc(key: str, n: int, score: float) -> dict[str, Any]:
    p = PASSAGES[key]
    # Nomi KICHIK harfda - jonli xizmat shunday beradi (`test_jonli_kadr_shakli`).
    return {"kind": "doc", "doc_id": p.doc_id, "title": DOCS[p.doc_id]["title"].lower(),
            "section": p.section, "page": p.page, "preview_available": True,
            "citation_index": n, "score": score, "snippet": p.text}


def _call(kind: str, n: int, tool: str, digest: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    # Belgi QAVSSIZ ("T1") - jonli shakl; brauzer qavsni o'zi qo'shadi.
    return {"kind": kind, "marker": f"T{n}", "tool": tool, "status": "ok", "digest": digest,
            "args": args or {}}


def _routing(plan: Plan) -> Plan:
    plan.steps.append(("wait", 0.15, 0.35))
    return plan.stage("routing", "Savol tahlil qilinmoqda", 0.05, 0.15)


def _next_workday_on_or_before(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def plan_rag(ctx: Ctx) -> Plan:
    q = ctx.q
    plan = _routing(Plan("rag")).stage("retrieval", "Hujjatlar qidirilmoqda")
    plan.stage("rerank", "Eng mos bo'limlar saralanmoqda")
    if re.search(r"safar|komandirov|командиров|\btrip|travel|сафар", q):
        plan.sources([_doc("trip_order", 1, 0.93), _doc("trip_advance", 2, 0.88),
                      _doc("per_diem", 3, 0.74)])
        plan.write(
            "Xizmat safari quyidagi tartibda rasmiylashtiriladi:\n\n"
            "1. **Taqdimnoma** — bo'lim rahbari safar maqsadi va muddatini ko'rsatib taqdimnoma "
            "yozadi, safar Bosh direktor buyrug'i bilan rasmiylashtiriladi [1].\n"
            "2. **Avans** — safar xarajatlari uchun avans safardan kamida **ikki ish kuni oldin** "
            "beriladi [2].\n"
            "3. **Sutkalik** — respublika hududida sutkalik xarajatlar eng kam ish haqining "
            "**10 foizi** miqdorida qoplanadi [3].\n"
            "4. **Hisobot** — qaytgach **uch ish kuni** ichida bo'nak hisobotini chipta va "
            "mehmonxona hujjatlari bilan topshirasiz [2].\n\n"
            "> Chipta va mehmonxona cheklarini safar davomidayoq suratga olib qo'ying — "
            "hisobot tezroq yopiladi.")
    elif re.search(r"ish\s*vaqt|soat\s*nech|tushlik|working\s*hours|график|режим|dress|kiyin|"
                   r"дресс|kechikish", q):
        plan.sources([_doc("hours", 1, 0.95), _doc("dress", 2, 0.81), _doc("late", 3, 0.77)])
        plan.write(
            "**Ish tartibi** [1]:\n\n"
            "| Ko'rsatkich | Vaqt |\n|---|---|\n"
            "| Ish kuni | 09:00 – 18:00 |\n| Tushlik | 13:00 – 14:00 |\n"
            "| Ish haftasi | 5 kun, dushanba – juma |\n\n"
            "Ish kunlari ishbilarmonlik uslubidagi kiyim talab qilinadi, **juma kuni** esa erkin "
            "(*smart casual*) uslubga ruxsat bor [2].\n\n"
            "Ish boshlanishiga **15 daqiqadan ortiq** kechikish intizom buzilishi hisoblanadi va "
            "bo'lim rahbariga bildiriladi [3].")
    elif re.search(r"kasal|больнич|\bsick|bolnichn", q):
        plan.sources([_doc("sick_notify", 1, 0.9), _doc("sick_list", 2, 0.87),
                      _doc("sick_pay", 3, 0.83)])
        plan.write(
            "Kasal bo'lib qolsangiz:\n\n"
            "1. Ish kunining **birinchi soatida** bevosita rahbaringizga xabar bering [1].\n"
            "2. Kasallik varaqasi shifoxonada **elektron** shaklda ochiladi — ishga chiqqan "
            "kuningiz uning raqamini Kadrlar bo'limiga bering [2].\n"
            "3. Nafaqa ish stajingizga qarab o'rtacha ish haqining **60–100 foizi** miqdorida "
            "to'lanadi [3].")
    else:
        plan.sources([_doc("leave_min", 1, 0.94), _doc("leave_schedule", 2, 0.86),
                      _doc("leave_split", 3, 0.82), _doc("leave_apply", 4, 0.71)])
        plan.write(
            "Yillik asosiy mehnat ta'tili — kamida **21 kalendar kun**, u to'liq haq "
            "to'lanadigan ta'til hisoblanadi [1].\n\n"
            "**Asosiy qoidalar:**\n\n"
            "1. Ta'til **jadval asosida** beriladi — jadval har yili 15-dekabrgacha "
            "tasdiqlanadi [2].\n"
            "2. Ta'tilni qismlarga bo'lish mumkin, lekin bir qismi kamida **14 kalendar kun** "
            "bo'lishi shart [3].\n"
            "3. Ariza ta'til boshlanishidan kamida **uch ish kuni oldin** bo'lim rahbari bilan "
            "kelishib topshiriladi [4].\n\n"
            "Shaxsiy qoldig'ingizni bilish uchun *«Ta'tilim necha kun qoldi?»* deb so'rang.")
    return plan.done("rules")


def plan_hrm(ctx: Ctx, *, slow: bool = False) -> Plan:
    plan = _routing(Plan("slow" if slow else "hrm"))
    if slow:
        # Birinchi so'zgacha uzoq jimlik - `hold` kadrlari aynan shu paytda keladi.
        plan.steps.append(("wait", 8.5, 9.5))
    plan.stage("hrm", "HRM ma'lumotlari olinmoqda", 0.35, 0.6)
    today = _today()
    year = today.year
    if slow or re.search(r"maosh|oylik|ish\s*haq|salary|pay\s*day|payslip|зарплат|avans|аванс|"
                         r"маош|ойлик", ctx.q):
        advance = date(year, today.month, 25)
        if advance < today:
            advance = (advance.replace(day=1) + timedelta(days=32)).replace(day=25)
        salary = date(year, today.month, 10)
        if salary < today:
            salary = (salary.replace(day=1) + timedelta(days=32)).replace(day=10)
        last_month = (today.replace(day=1) - timedelta(days=1))

        def when(d: date) -> str:
            moved = _next_workday_on_or_before(d)
            text = f"**{_day_month(moved)}**, {_WEEKDAYS[moved.weekday()]}"
            if moved != d:
                text += f" ({_day_month(d)} {_WEEKDAYS[d.weekday()]}ga to'g'ri keladi)"
            return text

        plan.sources([
            _call("hrm", 1, "hrm_payroll_schedule",
                  "Avans: har oyning 25-sanasi; oylik: keyingi oyning 10-sanasi",
                  {"employee": "me"}),
            _call("hrm", 2, "hrm_payslip_last",
                  f"{_MONTHS[last_month.month - 1].capitalize()} {last_month.year}: hisoblangan "
                  "9 200 000, ushlangan 1 104 000, to'langan 8 096 000 so'm",
                  {"period": last_month.strftime("%Y-%m")}),
        ])
        first, second = sorted([("Avans", advance), ("Oylik maosh", salary)], key=lambda x: x[1])
        plan.write(
            "Keyingi to'lovlaringiz [T1]:\n\n"
            f"- **{first[0]}** — {when(first[1])}\n"
            f"- **{second[0]}** — {when(second[1])}\n\n"
            f"Oxirgi hisob-varaqangiz ({_MONTHS[last_month.month - 1]}) [T2]:\n\n"
            "| Modda | So'm |\n|---|---:|\n| Hisoblangan | 9 200 000 |\n"
            "| Ushlanmalar | 1 104 000 |\n| **Qo'lga** | **8 096 000** |\n\n"
            "To'lov kuni dam olish kuniga to'g'ri kelsa, pul undan oldingi ish kunida o'tkaziladi.")
        return plan.done("hrm")
    plan.stage("retrieval", "Ta'til qoidalari tekshirilmoqda")
    plan.sources([
        _call("hrm", 1, "hrm_vacation_balance",
              f"{year}-yil: me'yor 21 kun, ishlatilgan 7, qolgan 14", {"year": year}),
        _call("hrm", 2, "hrm_leave_history",
              f"Oxirgi ta'til: 14.07.{year} – 20.07.{year} (7 kun)", {"limit": 3}),
        _doc("leave_split", 1, 0.79),
    ])
    plan.write(
        f"Sizda **14 kalendar kun** yillik ta'til qoldi [T1].\n\n"
        "| Ko'rsatkich | Kun |\n|---|---|\n| Yillik me'yor | 21 |\n| Ishlatilgan | 7 |\n"
        "| **Qolgan** | **14** |\n\n"
        f"Oxirgi ta'tilingiz: 14.07.{year} – 20.07.{year}, 7 kun [T2].\n\n"
        "Ta'til bo'lib olinganda bir qismi kamida 14 kun bo'lishi kerak [1] — ya'ni qolgan "
        "14 kunni **bir yo'la** olsangiz, qoida bajariladi. Ariza kerak bo'lsa: "
        "*«14 kunlik ta'til arizasi yoz»*.")
    return plan.done("both")


def _crm_issues(today: date) -> list[tuple[str, str, date, str]]:
    return [
        ("DVSIB-231", "Kredit skoring hisobotini yangilash", today - timedelta(days=3), "Jarayonda"),
        ("DVSIB-228", "Mijozlar bazasini CRM ga ko'chirish", today - timedelta(days=1), "Jarayonda"),
        ("DVSIB-240", "Oylik KPI dashboardini tayyorlash", today + timedelta(days=2), "Yangi"),
        ("DVSIB-236", "Hamkor bank bilan API integratsiyasi", today + timedelta(days=5),
         "Ko'rib chiqishda"),
        ("DVSIB-244", "Xavfsizlik auditi natijalarini tahlil qilish", today + timedelta(days=9),
         "Yangi"),
    ]


def plan_crm(ctx: Ctx) -> Plan:
    plan = _routing(Plan("crm")).stage("crm", "CRM tekshirilmoqda", 0.35, 0.6)
    today = _today()
    if re.search(r"mijoz|klient|client|customer|клиент|мижоз|bitim|\bdeal|сделк", ctx.q):
        quoted = re.search(r"[«\"“]([^»\"”]{2,60})[»\"”]", ctx.question)
        name = quoted.group(1).strip() if quoted else "Anor Savdo"
        contact = today - timedelta(days=5)
        plan.sources([
            _call("crm", 1, "crm_customer", f"«{name}» MChJ · STIR 305 112 948 · menejer: "
                  "Yusupova M.", {"query": name}),
            _call("crm", 2, "crm_customer_deals", "3 ta bitim: 1 ochiq, 2 yopilgan",
                  {"customer": name}),
        ])
        plan.write(
            f"**«{name}» MChJ** — mijoz kartasi [T1]:\n\n"
            "- **STIR:** 305 112 948\n- **Segment:** o'rta biznes, ulgurji savdo\n"
            "- **Mas'ul menejer:** Yusupova Malika\n"
            f"- **Oxirgi aloqa:** {_day_month(contact)}, qo'ng'iroq\n\n"
            "Bitimlar [T2]:\n\n"
            "1. Aylanma mablag'lar krediti — **1,2 mlrd so'm**, *muzokarada*\n"
            "2. Korporativ karta xizmati — yopilgan, muvaffaqiyatli\n"
            "3. Eskrou hisob — yopilgan, rad etilgan\n\n"
            "Keyingi qadam: ochiq kredit bitimi bo'yicha garov hujjatlarini so'rash.")
        return plan.done("crm")
    issues = _crm_issues(today)
    overdue = sum(1 for _, _, due, _ in issues if due < today)
    plan.sources([_call("crm", 1, "crm_my_issues",
                        f"{len(issues)} ta aktiv vazifa, {overdue} tasining muddati o'tgan",
                        {"assignee": "me", "status": "open"})])
    late_label = "**muddati o'tgan**"
    rows = "".join(
        f"| **{key}** | {title} | {_day_month(due)} | {late_label if due < today else status} |\n"
        for key, title, due, status in issues)
    plan.write(
        f"Sizda **{len(issues)} ta aktiv vazifa** bor, ulardan **{overdue} tasining muddati "
        "o'tgan** [T1]:\n\n| Vazifa | Nomi | Muddat | Holat |\n|---|---|---|---|\n"
        f"{rows}\n"
        "Birinchi navbatda **DVSIB-231** ni yopishni tavsiya qilaman — u eng uzoq kechikkan. "
        "Vaqt yozish uchun: *«DVSIB-231 ga 2 soat yoz»*.")
    return plan.done("crm")


def plan_artifact(ctx: Ctx) -> Plan:
    plan = _routing(Plan("artifact")).stage("hrm", "Xodim ma'lumotlari olinmoqda", 0.35, 0.6)
    plan.stage("retrieval", "Ariza shabloni va qoidalar tekshirilmoqda")
    plan.stage("drafting", "Ariza tayyorlanmoqda", 0.4, 0.6)
    today = _today()
    found = re.search(r"(\d{1,2})\s*(?:-?\s*kun|дн|day)", ctx.q)
    days = min(28, max(1, int(found.group(1)))) if found else 14
    start = today + timedelta(days=7 + (7 - today.weekday()) % 7)
    end = start + timedelta(days=days - 1)
    profile = _profile(ctx.user_id)
    doc_id = f"ARZ-{today.strftime('%y%m%d')}-{_key(4).upper()}"
    art = {"title": f"Ta'til arizasi — {_dmy(start)}", "doc_id": doc_id, "profile": profile,
           "start": start, "end": end, "days": days, "created": today}
    token = ARTIFACTS.create(art)
    left = 14 - days
    plan.sources([
        _doc("leave_apply", 1, 0.9),
        _call("hrm", 1, "hrm_employee_profile", " · ".join(profile), {"employee": "me"}),
        _call("hrm", 2, "hrm_vacation_balance", "qolgan: 14 kun", {"year": today.year}),
    ])
    # Havolalar - soxtaning "ICHKI" manzili: Venera ularni o'z yo'liga
    # o'giradi (`_rewrite_artifact`), ya'ni o'sha kod ham ishlaydi.
    base = f"{ctx.base}/api/hr/artifacts/{token}"
    plan.frame({"type": "artifact", "title": art["title"], "doc_id": doc_id,
                "docx_url": f"{base}/docx", "pdf_url": f"{base}/pdf", "preview_url": f"{base}/preview",
                "expires_at": _iso(time.time() + _ARTIFACT_TTL)})
    balance = (f"ariza tasdiqlangach **{left} kun** qoladi [T2]" if left >= 0 else
               f"qoldiq yetmaydi — {-left} kun uchun haq to'lanmaydigan ta'til arizasi kerak [T2]")
    plan.write(
        "Ariza tayyor — tekshirib, imzolang [T1]:\n\n"
        "- **Turi:** yillik asosiy mehnat ta'tili\n"
        f"- **Muddat:** {_dmy(start)} – {_dmy(end)} (**{days} kalendar kun**)\n"
        f"- **Qoldiq:** {balance}\n\n"
        "Arizani ta'til boshlanishidan kamida **uch ish kuni oldin** bo'lim rahbari bilan "
        "kelishib, Kadrlar bo'limiga topshiring [1]. DOCX va PDF nusxalari pastda.")
    return plan.done("both")


def plan_proposal(ctx: Ctx) -> Plan:
    plan = _routing(Plan("proposal")).stage("crm", "CRM dan vazifa olinmoqda", 0.35, 0.6)
    plan.stage("planning", "O'zgarish rejasi tuzilmoqda")
    today = _today()
    if re.search(r"yarat|create|созда|ярат", ctx.q):
        quoted = re.search(r"[«\"“]([^»\"”]{2,80})[»\"”]", ctx.question)
        title = quoted.group(1).strip() if quoted else "Hisobot shablonini yangilash"
        due = today + timedelta(days=3)
        proposal = {"summary": f"DVSIB loyihasida yangi vazifa: «{title}»",
                    "operation": "create_issue", "connector": "crm",
                    "target": {"key": "DVSIB", "title": "Raqamli bank xizmatlari"},
                    "changes": [{"field": "Sarlavha", "from": None, "to": title},
                                {"field": "Ijrochi", "from": None, "to": "Siz"},
                                {"field": "Muddat", "from": None, "to": _dmy(due)},
                                {"field": "Muhimlik", "from": None, "to": "O'rta"}],
                    "warnings": []}
        outcome = {"key": f"DVSIB-{245 + _rng.randint(0, 20)}"}
        plan.sources([_call("crm", 1, "crm_project_get",
                            "DVSIB · Raqamli bank xizmatlari · 42 ta ochiq vazifa",
                            {"project": "DVSIB"})])
        answer = ("Yangi vazifa yaratishni taklif qilaman — **hali hech narsa yaratilmadi** [T1]:\n\n"
                  f"- **Loyiha:** DVSIB\n- **Sarlavha:** {title}\n- **Ijrochi:** siz\n"
                  f"- **Muddat:** {_dmy(due)}\n\n"
                  "Tasdiqlasangiz, CRM da yarataman. Pastdagi kartadan **Tasdiqlash** yoki "
                  "**Rad etish** ni tanlang.")
    else:
        key_match = re.search(r"\b([A-Z]{2,10}-\d{1,6})\b", ctx.question)
        issue = key_match.group(1) if key_match else "DVSIB-231"
        hours_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:soat|час|hour|h\b)", ctx.q)
        hours = float(hours_match.group(1).replace(",", ".")) if hours_match else 2.0
        hours_text = f"{hours:g} soat"
        before_min = 210
        after_min = before_min + int(hours * 60)
        spent = lambda m: f"{m // 60} s {m % 60:02d} daq"  # noqa: E731
        proposal = {"summary": f"{issue} vazifasiga {hours_text} vaqt yozish",
                    "operation": "worklog", "connector": "crm",
                    "target": {"key": issue, "title": "Kredit skoring hisobotini yangilash"},
                    "changes": [{"field": "Sarflangan vaqt", "from": spent(before_min),
                                 "to": spent(after_min)},
                                {"field": "Sana", "from": None, "to": _dmy(today)},
                                {"field": "Izoh", "from": None, "to": "Hisobot shablonini yangilash"}],
                    "warnings": (["Bugungi jami vaqtingiz 8 soatdan oshadi"] if hours > 6 else [])}
        outcome = {"key": issue, "worklog_id": str(10480 + _rng.randint(0, 99)),
                   "logged": hours_text}
        plan.sources([_call("crm", 1, "crm_issue_get",
                            f"{issue} · Kredit skoring hisobotini yangilash · sarflangan: "
                            f"{spent(before_min)}", {"key": issue})])
        answer = ("O'zgarishni tayyorladim — **hali hech narsa yozilmadi** [T1]:\n\n"
                  f"- **Vazifa:** {issue} — Kredit skoring hisobotini yangilash\n"
                  f"- **Qo'shiladigan vaqt:** {hours_text} "
                  f"(jami {spent(before_min)} → {spent(after_min)})\n"
                  f"- **Sana:** bugun, {_day_month(today)}\n\n"
                  "Tasdiqlasangiz, CRM ga yozaman. Pastdagi kartadan **Tasdiqlash** yoki "
                  "**Rad etish** ni tanlang.")
    token = ACTIONS.create(ctx.user_id, proposal, outcome)
    # `confirm_url` / `cancel_url` - ICHKI manzil: Venera ularni olib tashlaydi
    # (`_strip_proposal_urls`), brauzerga yetib bormaydi.
    plan.frame({"type": "proposal", "proposal": proposal | {
        "token": token, "expires_at": _iso(time.time() + _ACTION_TTL),
        "confirm_url": f"{ctx.base}/api/actions/{token}/confirm",
        "cancel_url": f"{ctx.base}/api/actions/{token}/cancel"}})
    plan.write(answer)
    return plan.done("crm")


_AUTH_TEXT = {
    "hrm": ("Bu savolga javob berish uchun HRM tizimiga kirishingiz kerak. «+» menyusidan HRM "
            "hisobingizni ulang va qayta so'rang."),
    "crm": ("Bu savolga javob berish uchun CRM tizimiga kirishingiz kerak. «+» menyusidan CRM "
            "hisobingizni ulang va qayta so'rang."),
}


def plan_error(ctx: Ctx, platform: str = "hrm") -> Plan:
    """Xato kadri tokenlar O'RNIGA keladi, keyin `done` (route yo'q)."""
    plan = _routing(Plan("error", store=False))
    plan.stage(platform, f"{platform.upper()} ma'lumotlari so'ralmoqda", 0.3, 0.6)
    plan.frame({"type": "error", "code": "auth_missing", "text": _AUTH_TEXT[platform]}, 0.2, 0.4)
    return plan.done(None)


def plan_clarify(ctx: Ctx) -> Plan:
    plan = _routing(Plan("clarify"))
    plan.write(
        "Qaysi hisobot kerakligini aniqlashtirib bering:\n\n"
        "1. **Ta'til hisoboti** — qoldiq va olingan kunlar (HRM);\n"
        "2. **Vazifalar hisoboti** — CRM dagi ochiq va yopilgan vazifalar;\n"
        "3. **Hisob-varaq** — oxirgi oy bo'yicha hisoblangan va to'langan summa.\n\n"
        "Raqamini yoki nomini yozing.")
    return plan.done("clarify")


def plan_smalltalk(ctx: Ctx) -> Plan:
    plan = _routing(Plan("smalltalk"))
    if re.search(r"rahmat|raxmat|спасибо|thank|рахмат|tashakkur", ctx.q):
        plan.write("Arzimaydi! Yana savol tug'ilsa, bemalol yozing.")
    elif re.search(r"salom|assalom|привет|здравств|hello|\bhi\b|\bhey\b|салом|ассалом", ctx.q):
        plan.write(
            "Salom! Men **Venera** — HR yordamchingizman.\n\n"
            "Qoidalar, ta'til va maosh, CRM vazifalari yoki ariza tayyorlash bo'yicha "
            "so'rashingiz mumkin. Nimadan boshlaymiz?")
    else:
        plan.write(
            "Men quyidagilarda yordam bera olaman:\n\n"
            "- **Qoidalar** — ta'til, ish vaqti, xizmat safari, kasallik varaqasi;\n"
            "- **HRM** — ta'til qoldig'i, maosh sanalari;\n"
            "- **CRM** — vazifalar, mijozlar, vaqt yozish;\n"
            "- **Arizalar** — ta'til arizasini tayyorlash.\n\n"
            "Savolingizni shu yo'nalishlardan birida bering.")
    return plan.done("rules")


def plan_partial(ctx: Ctx) -> Plan:
    """Javobning yarmi, keyin xato - brauzer yarim javobni ogohlantirish bilan saqlaydi."""
    full = plan_rag(ctx)
    plan = Plan("partial", store=False)
    for step in full.steps:
        if step[0] == "tokens":
            plan.steps.append(("tokens", step[1][: len(step[1]) // 2]))
            break
        plan.steps.append(step)
    plan.frame({"type": "error", "code": "generation_failed",
                "text": "Javob yozish o'rtasida to'xtab qoldi. Qayta urinib ko'ring."}, 0.3, 0.5)
    return plan.done("rules")


def plan_cut(ctx: Ctx, *, mid_frame: bool = False) -> Plan:
    """Javob o'rtasida ulanish UZILADI - `done` yo'q, nol chunk ham yo'q.

    Ikki xil uzilish, chunki Venera ularni HAR XIL ko'radi:
      * `cut`  - kadrlar ORASIDA (yiqilgan xizmatning odatiy ko'rinishi).
        `http.client` chunk chegarasidagi uzilishni oddiy EOF deb o'qiydi -
        `pump()` `done` kelmaganini ko'rib buni uzilish deb biladi;
      * `torn` - kadr O'RTASIDA (chunk e'lon qilgan baytlar kelmaydi) -
        `IncompleteRead`, Venera `stream_broken` va `done` yozadi.
    """
    full = plan_rag(ctx)
    plan = Plan("torn" if mid_frame else "cut", store=False)
    for step in full.steps:
        if step[0] == "tokens":
            plan.steps += [("tokens", step[1][: len(step[1]) // 3]), ("cut", mid_frame)]
            break
        plan.steps.append(step)
    return plan


_DIRECTIVE = re.compile(r"\bmock:([a-z]+)\b", re.IGNORECASE)

#: (ssenariy, naqsh) - TARTIB bilan, birinchi mos kelgani tanlanadi.
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("error", re.compile(r"kechikdim|kechikkanmi|davomatim|\bxato\b|\berror\b|ошибк|опоздал|"
                         r"\bam i late|\bwas i late|auth_missing")),
    ("proposal", re.compile(r"vaqt\w*\s+yoz|soat\s+yoz|worklog|log\s+(my\s+)?time|списа|"
                            r"запиши\s+врем|vazifa\s+yarat|task\s+yarat|create\s+(a\s+)?task|"
                            r"созда\w*\s+задач|вазифа\s+ярат|вақт\s+ёз")),
    ("artifact", re.compile(r"ariza|заявлен|ариза|application|\bblank")),
    ("crm", re.compile(r"\bcrm\b|mijoz|klient|client|customer|клиент|мижоз|bitim|\bdeal|сделк|"
                       r"vazifa|\btask|задач|\bissue|вазифа|dvsib")),
    ("hrm", re.compile(r"qoldi|qoldig|balans|balance|остал|остат|maosh|oylik(?!\s+hisobot)|ish\s*haq|"
                       r"salary|pay\s*day|payslip|зарплат|avans|аванс|маош|ойлик|қолди|\bleft\b|"
                       r"remaining")),
    ("rag", re.compile(r"ta'?til|отпуск|vacation|\bleave\b|qoida|nizom|tartib|policy|\brule|"
                       r"правил|положени|kodeks|mehnat|safar|komandirov|командиров|\btrip|"
                       r"travel|ish\s*vaqt|soat\s*nech|tushlik|working\s*hours|график|режим|"
                       r"dress|kiyin|дресс|kasal|больнич|\bsick|dekret|kechikish|таътил|қоида|"
                       r"низом|сафар")),
    ("clarify", re.compile(r"hisobot|отч[её]т|\breport|statistik|ҳисобот")),
)

_BUILDERS: dict[str, Callable[[Ctx], Plan]] = {
    "rag": plan_rag, "hrm": plan_hrm, "crm": plan_crm, "artifact": plan_artifact,
    "proposal": plan_proposal, "error": plan_error, "smalltalk": plan_smalltalk,
    "clarify": plan_clarify, "partial": plan_partial, "cut": plan_cut,
    "torn": lambda ctx: plan_cut(ctx, mid_frame=True),
    "slow": lambda ctx: plan_hrm(ctx, slow=True),
}

#: Qaysi ssenariy qaysi platforma tokenini talab qiladi (`--strict-tokens`).
_NEEDS = {"hrm": "hrm", "slow": "hrm", "artifact": "hrm", "crm": "crm", "proposal": "crm"}


def choose(question: str) -> tuple[str, str]:
    """(ssenariy, normallashtirilgan savol)."""
    q = re.sub(r"[‘’ʻʼ`´]", "'", question.lower())
    forced = _DIRECTIVE.search(q)
    if forced:
        return forced.group(1), q
    for name, pattern in _RULES:
        if pattern.search(q):
            return name, q
    return "smalltalk", q


def build_plan(ctx: Ctx, scenario: str) -> Plan:
    if scenario == "busy":
        return Plan("busy", store=False,
                    http_error=(503, {"detail": "LLM navbati to'la, keyinroq urinib ko'ring"}))
    if scenario == "fail":
        return Plan("fail", store=False, http_error=(500, {"detail": "Internal Server Error"}))
    need = _NEEDS.get(scenario)
    if OPTS.strict_tokens and need and not ctx.tokens.get(need):
        # Jonli xizmat xulqi: token yo'q platforma haqidagi savol `auth_missing`.
        plan = plan_error(ctx, need)
        plan.scenario = f"{scenario}->auth_missing"
        return plan
    builder = _BUILDERS.get(scenario, plan_smalltalk)
    return builder(ctx)


# --- Ollama (kutish ovozi tasnifi) --------------------------------------------

_TOPICS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("kechikish", re.compile(r"kech(ik|\s*qol)|davomat|kelmadi|опозд|\blate\b")),
    ("tatil", re.compile(r"ta'?til|dam\s*ol|dekret|otpusk|отпуск|kasallik|vacation")),
    ("hujjat", re.compile(r"qoida|hujjat|nizom|tartib|reglament|qonun|buyruq|ariza")),
    ("vazifa", re.compile(r"vazifa|topshiriq|task|muddat|задач")),
    ("mijoz", re.compile(r"mijoz|klient|bitim|savdo|shartnoma|crm|клиент")),
    ("xodim", re.compile(r"xodim|ishda\s*yo'?q|kim\s*ishda|bo'?lim|lavozim")),
    ("hisobot", re.compile(r"hisobot|statistik|yig'?ma|ko'rsatkich|отч")),
)


def classify(question: str) -> str:
    q = re.sub(r"[‘’ʻʼ`´]", "'", question.lower())
    topic = next((name for name, pattern in _TOPICS if pattern.search(q)), "umumiy")
    tone = "shoshilinch" if re.search(r"\btez\b|darhol|zudlik|срочно|urgent|!\s*$", q) else "oddiy"
    return f"{topic}|{tone}"


# --- multipart -----------------------------------------------------------------


def parse_multipart(body: bytes, content_type: str) -> dict[str, tuple[dict[str, str], bytes]]:
    """`multipart/form-data` -> {nom: (sarlavhalar, baytlar)}. `cgi` 3.13 da yo'q."""
    found = re.search(r'boundary="?([^";]+)"?', content_type or "")
    if not found:
        return {}
    parts: dict[str, tuple[dict[str, str], bytes]] = {}
    for chunk in body.split(b"--" + found.group(1).encode("latin-1"))[1:]:
        if chunk.startswith(b"--"):
            break
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        head, _, data = chunk.partition(b"\r\n\r\n")
        if data.endswith(b"\r\n"):
            data = data[:-2]
        headers: dict[str, str] = {}
        for line in head.split(b"\r\n"):
            name, _, value = line.decode("latin-1").partition(":")
            headers[name.strip().lower()] = value.strip()
        field_name = re.search(r'\bname="([^"]*)"', headers.get("content-disposition", ""))
        if field_name:
            parts[field_name.group(1)] = (headers, data)
    return parts


def _filename_of(headers: dict[str, str]) -> str:
    found = re.search(r'filename="([^"]*)"', headers.get("content-disposition", ""))
    return found.group(1) if found else ""


# --- HTTP ----------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    """Bitta portda uchta (ixtiyoriy beshta) xizmat - yo'l bo'yicha ajratiladi."""

    protocol_version = "HTTP/1.1"
    server_version = "venera-dev-mock/1.0"
    sys_version = ""

    # --- umumiy -----------------------------------------------------------

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Standart jurnal o'chiq - har so'rov `_dispatch` da bitta qatorda yoziladi."""

    def send_response(self, code: int, message: str | None = None) -> None:
        self._status = code
        super().send_response(code, message)

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PATCH(self) -> None:
        self._dispatch("PATCH")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        started = time.monotonic()
        self._status, self._note, self._headers_sent = 0, "", False
        self._rid = (self.headers.get("X-Request-Id") or "").strip()[:128] or uuid.uuid4().hex
        url = urlsplit(self.path)
        self._query = parse_qs(url.query)
        try:
            for verb, pattern, handler in ROUTES:
                match = pattern.fullmatch(url.path)
                if match and verb == method:
                    handler(self, *[unquote(g) for g in match.groups()])
                    break
            else:
                known = any(p.fullmatch(url.path) for _, p, _ in ROUTES)
                self._json(405 if known else 404,
                           {"detail": "Method Not Allowed" if known else "Not Found"})
        except (BrokenPipeError, ConnectionResetError):
            self._note += "  [klient uzildi]"
            self.close_connection = True
        except Exception:  # noqa: BLE001 - soxta server yiqilmasligi kerak
            traceback.print_exc()
            self._note += "  [ICHKI XATO]"
            if not self._headers_sent:
                self._json(500, {"detail": "mock internal error"})
            self.close_connection = True
        finally:
            took = (time.monotonic() - started) * 1000
            _log(f"{method:<6} {self.path} -> {self._status or '-'} {took:.0f}ms{self._note}")

    def _q(self, name: str) -> str | None:
        values = self._query.get(name)
        return values[0] if values else None

    def _read(self, limit: int = 1024 * 1024) -> bytes | None:
        length = int(self.headers.get("Content-Length") or 0)
        if length > limit:
            self.close_connection = True
            self._json(413, {"detail": f"so'rov juda katta ({length} bayt)"})
            return None
        return self.rfile.read(length) if length else b""

    def _json_body(self) -> dict[str, Any] | None:
        raw = self._read()
        if raw is None:
            return None
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            self._json(422, {"detail": [{"type": "json_invalid", "loc": ["body"],
                                         "msg": "JSON decode error"}]})
            return None
        if not isinstance(data, dict):
            self._json(422, {"detail": [{"type": "dict_type", "loc": ["body"],
                                         "msg": "Input should be a valid dictionary"}]})
            return None
        return data

    def _headers_out(self, status: int, content_type: str, extra: dict[str, str] | None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        # Audit kaliti: klient yuborganini qaytaramiz (jonli xizmat o'zinikini).
        self.send_header("X-Request-Id", self._rid)
        for name, value in (extra or {}).items():
            self.send_header(name, value)

    def _bytes(self, status: int, body: bytes, content_type: str,
               extra: dict[str, str] | None = None) -> None:
        self._headers_out(status, content_type, extra)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self._headers_sent = True
        self.wfile.write(body)

    def _json(self, status: int, payload: Any, extra: dict[str, str] | None = None) -> None:
        self._bytes(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    "application/json", extra)

    def _open_stream(self, status: int, content_type: str, extra: dict[str, str] | None = None) -> None:
        self._headers_out(status, content_type, extra)
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self._headers_sent = True

    def _chunk(self, data: bytes) -> None:
        if data:
            self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))

    def _close_stream(self) -> None:
        self.wfile.write(b"0\r\n\r\n")

    def _client_ok(self) -> bool:
        """Ilova kredensiallari. Qiymati tekshirilmaydi - faqat BORLIGI (usiz 401)."""
        if (self.headers.get("X-Client-Id") or "").strip() and \
                (self.headers.get("X-Client-Secret") or "").strip():
            return True
        self._json(401, {"detail": "X-Client-Id / X-Client-Secret yo'q yoki noto'g'ri"})
        return False

    def _user_id(self) -> str | None:
        user_id = self._q("user_id")
        if not user_id:
            self._json(422, {"detail": [{"type": "missing", "loc": ["query", "user_id"],
                                         "msg": "Field required"}]})
        return user_id

    def _int_q(self, name: str, default: int, low: int, high: int) -> int | None:
        raw = self._q(name)
        try:
            value = default if raw is None else int(raw)
        except ValueError:
            value = -1
        if not low <= value <= high:
            self._json(422, {"detail": [{"type": "int_range", "loc": ["query", name],
                                         "msg": f"must be {low}..{high}"}]})
            return None
        return value

    # --- holat ---------------------------------------------------------------

    def health(self) -> None:
        """`services/upstream.py` ikki xizmatni BIR manzilda so'raydi: STT
        `status` va `backends` ni, TTS `model_loaded` ni o'qiydi."""
        self._json(200, {"status": "ok",
                         "backends": {"uzbek_stt": {"status": "ok"}, "multilang": {"status": "ok"}},
                         "model_loaded": True, "voice_profiles": list(_VOICES), "device": "mock"})

    def assistant_health(self) -> None:
        self._json(200, {"status": "ok", "service": "hr-assistant (dev mock)"})

    def mock_state(self) -> None:
        self._json(200, {"chats": CHATS.count(), "actions": ACTIONS.count(),
                         "artifacts": ARTIFACTS.count(), "tts_tokens": TTS_TOKENS.count(),
                         "scenarios": [name for name, _ in _RULES] + ["smalltalk"],
                         "directives": sorted(_BUILDERS) + ["busy", "fail"],
                         "options": {"speed": OPTS.speed, "strict_tokens": OPTS.strict_tokens,
                                     "silent_tts": OPTS.silent_tts}})

    # --- HR Assistant: savol -> oqim -----------------------------------------------

    def chat_stream(self) -> None:
        if not self._client_ok():
            return
        body = self._json_body()
        if body is None:
            return
        question, user_id = body.get("question"), body.get("user_id")
        missing = [{"type": "missing", "loc": ["body", name], "msg": "Field required"}
                   for name, value in (("question", question), ("user_id", user_id))
                   if not isinstance(value, str) or not value.strip()]
        if missing:
            self._json(422, {"detail": missing})
            return
        if len(question) > 4000:
            self._json(422, {"detail": "question is too long"})
            return
        chat_id = body.get("chat_id") if isinstance(body.get("chat_id"), str) else None
        tokens = body.get("tokens") if isinstance(body.get("tokens"), dict) else {}
        scenario, q = choose(question)
        ctx = Ctx(question=question, q=q, user_id=user_id, chat_id=chat_id or None,
                  tokens={k: str(v) for k, v in tokens.items() if v},
                  base=f"http://{self.headers.get('Host') or '127.0.0.1'}", request_id=self._rid)
        plan = build_plan(ctx, scenario)
        self._note = f"  [{plan.scenario}]"
        if plan.http_error:
            _pause(0.2, 0.5)
            self._json(*plan.http_error)
            return
        asked = time.time()
        _pause(0.1, 0.4)        # ulanish va sarlavhalar - jonli xizmatda 0-2 s
        self._open_stream(200, "application/x-ndjson")
        frames = 0

        def send(frame: dict[str, Any]) -> None:
            nonlocal frames
            self._chunk(json.dumps(frame, ensure_ascii=False).encode("utf-8") + b"\n")
            frames += 1

        for step in plan.steps:
            kind = step[0]
            if kind == "wait":
                _pause(step[1], step[2])
            elif kind == "frame":
                send(step[1])
            elif kind == "tokens":
                for piece in re.findall(r"\s*\S+\s*", step[1]):
                    send({"type": "token", "text": piece})
                    _pause(0.025, 0.04)
            elif kind == "done":
                send({"type": "done", "route": step[1], "request_id": self._rid})
            elif kind == "cut":
                if step[1]:
                    # Kadr O'RTASIDA: chunk sarlavhasi to'liq uzunlikni aytadi,
                    # baytlarning yarmi keladi - klient `IncompleteRead` oladi.
                    line = json.dumps({"type": "token", "text": "uzilgan kadr "},
                                      ensure_ascii=False).encode("utf-8") + b"\n"
                    self.wfile.write(b"%x\r\n" % len(line) + line[: len(line) // 2])
                # Nol chunk YO'Q - ulanish shunchaki yopiladi.
                self._note += f" {frames} kadr, UZILDI{' (kadr ichida)' if step[1] else ''}"
                self.close_connection = True
                return
        self._close_stream()
        self._note += f" {frames} kadr"
        # Tarix: faqat javob bo'lgan va suhbat kaliti berilgan turn yoziladi -
        # kalitsiz savol jonli xizmatda ham xotirasiz bajariladi.
        if plan.store and plan.answer and ctx.chat_id:
            CHATS.add_turn(user_id, ctx.chat_id, question, plan.answer, asked, time.time())

    # --- HR Assistant: suhbatlar tarixi ------------------------------------------

    _NOT_FOUND = {"detail": {"code": "not_found", "message": "No such chat for this user."}}

    def chats_list(self) -> None:
        if not self._client_ok():
            return
        user_id = self._user_id()
        limit = self._int_q("limit", 50, 1, 1000) if user_id else None
        offset = self._int_q("offset", 0, 0, 1_000_000) if limit is not None else None
        if offset is not None:
            self._json(200, CHATS.listing(user_id, limit, offset))

    def chat_get(self, chat_id: str) -> None:
        if not self._client_ok():
            return
        user_id = self._user_id()
        limit = self._int_q("limit", 200, 1, 1000) if user_id else None
        if limit is None:
            return
        found = CHATS.detail(user_id, chat_id, limit)
        self._json(200 if found else 404, found or self._NOT_FOUND)

    def chat_patch(self, chat_id: str) -> None:
        if not self._client_ok():
            return
        user_id = self._user_id()
        body = self._json_body() if user_id else None
        if body is None:
            return
        title = re.sub(r"\s+", " ", str(body.get("title") or "")).strip()
        if not 1 <= len(title) <= 80:
            self._json(422, {"detail": {"code": "invalid_title",
                                        "message": "Title must be 1-80 characters."}})
            return
        found = CHATS.rename(user_id, chat_id, title)
        self._json(200 if found else 404, found or self._NOT_FOUND)

    def chat_delete(self, chat_id: str) -> None:
        if not self._client_ok():
            return
        user_id = self._user_id()
        if not user_id:
            return
        if CHATS.delete(user_id, chat_id):
            self._json(200, {"chat_id": chat_id, "status": "deleted"})
        else:
            self._json(404, self._NOT_FOUND)

    def chat_restore(self, chat_id: str) -> None:
        if not self._client_ok():
            return
        user_id = self._user_id()
        if not user_id:
            return
        found = CHATS.restore(user_id, chat_id)
        self._json(200 if found else 404, found or self._NOT_FOUND)

    # --- HR Assistant: yozuv amallari ----------------------------------------------

    def action_get(self, token: str) -> None:
        if not self._client_ok():
            return
        found = ACTIONS.get(token, self._rid)
        if found:
            self._note = f"  [{found['status']}]"
            self._json(200, found)
        else:
            self._json(404, {"detail": {"code": "not_found", "message": "No such proposal."}})

    def action_decide(self, token: str, verb: str) -> None:
        if not self._client_ok():
            return
        body = self._json_body()
        if body is None:
            return
        user_id = body.get("user_id")
        if not isinstance(user_id, str) or not user_id:
            self._json(422, {"detail": [{"type": "missing", "loc": ["body", "user_id"],
                                         "msg": "Field required"}]})
            return
        _pause(0.4, 0.9)        # platformaga yozish vaqti
        status, payload = ACTIONS.decide(token, verb, user_id, self._rid)
        self._note = f"  [{verb} -> {payload.get('status', status)}]"
        self._json(status, payload)

    # --- HR Assistant: fayllar -----------------------------------------------------

    def artifact(self, token: str, kind: str) -> None:
        if not self._client_ok():
            return
        art = ARTIFACTS.get(token)
        if art is None or kind not in ("preview", "docx", "pdf"):
            self._json(404, {"detail": "Artifact not found or expired"})
            return
        _pause(0.1, 0.3)
        stem = f"tatil-arizasi-{art['start'].strftime('%Y-%m-%d')}"
        if kind == "docx":
            self._bytes(200, artifact_docx(art),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        {"Content-Disposition": f'attachment; filename="{stem}.docx"'})
        else:
            disposition = "inline" if kind == "preview" else "attachment"
            self._bytes(200, artifact_pdf(art, preview=kind == "preview"), "application/pdf",
                        {"Content-Disposition": f'{disposition}; filename="{stem}.pdf"'})

    def doc(self, doc_id: str) -> None:
        if not self._client_ok():
            return
        # `HR_404` - xato yo'lini sinash uchun ataylab yo'q hujjat.
        if not re.fullmatch(r"[\w.~:-]{1,128}", doc_id) or doc_id == "HR_404":
            self._json(404, {"detail": "Document not found"})
            return
        _pause(0.1, 0.3)
        self._bytes(200, doc_pdf(doc_id), "application/pdf",
                    {"Content-Disposition": f'inline; filename="{doc_id}.pdf"'})

    # --- STT Router ----------------------------------------------------------------

    def stt_transcribe(self) -> None:
        raw = self._read(_STT_MAX_BYTES + 64 * 1024)
        if raw is None:
            return
        parts = parse_multipart(raw, self.headers.get("Content-Type") or "")
        language = parts["language"][1].decode("utf-8", "replace").strip() if "language" in parts else ""
        if not language:
            # Router'da avtomatik aniqlash YO'Q - til majburiy (`services/stt.py`).
            self._json(422, {"detail": "language maydoni majburiy: uz | en | ru | zh"})
            return
        if language not in ("uz", "en", "ru", "zh"):
            self._json(400, {"detail": f"unsupported language: {language}"})
            return
        if "file" not in parts or not parts["file"][1]:
            self._json(400, {"detail": "audio fayl bo'sh"})
            return
        headers, audio = parts["file"]
        filename = _filename_of(headers)
        if len(audio) > _STT_MAX_BYTES:
            self._json(413, {"detail": "audio 25 MB dan katta"})
            return
        if language == "uz" and filename.lower().endswith(".webm"):
            # Jonli xulq: o'zbek backend WebM ni ocha olmaydi (`web/src/api/wav.ts`).
            self._json(415, {"detail": "uzbek_stt: .webm qo'llab-quvvatlanmaydi (wav/ogg/opus/mp3/flac)"})
            return
        text, seconds = transcript_for(audio, filename, language)
        elapsed = 0.12 + min(2.0, seconds * 0.03)
        _pause(elapsed)
        uz = language == "uz"
        limit = 300.0 if uz else 600.0
        self._note = f"  [{language}, {seconds:.1f}s, {len(text)} belgi]"
        self._json(200, {
            "text": text, "language": language,
            "backend": "uzbek_stt" if uz else "multilang",
            "model": "uzbek_stt_v1" if uz else "large-v3-turbo-ct2",
            "duration_sec": min(seconds, limit), "truncated": seconds > limit,
            # Sifat bayroqlari FAQAT multilang da; uz backend `null` beradi.
            "avg_logprob": None if uz else -0.18, "segments": None if uz else 1,
            "low_confidence": None if uz else False,
            "language_mismatch": None if uz else False, "detected_language": None,
            "elapsed_sec": round(elapsed, 3),
        })

    # --- TTS -----------------------------------------------------------------------

    def tts_token(self) -> None:
        body = self._json_body()
        if body is None:
            return
        if not str(body.get("client_id") or "").strip() or not str(body.get("client_secret") or "").strip():
            self._json(401, {"detail": "client_id yoki client_secret noto'g'ri"})
            return
        self._json(200, {"access_token": TTS_TOKENS.issue(), "token_type": "bearer",
                         "expires_in": _TTS_TOKEN_TTL})

    def tts_stream(self) -> None:
        token = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        if not TTS_TOKENS.valid(token):
            self._json(401, {"detail": "Token yaroqsiz yoki muddati tugagan"})
            return
        body = self._json_body()
        if body is None:
            return
        text = str(body.get("text") or "").strip()
        fmt = str(body.get("format") or "wav").lower()
        voice = body.get("voice_profile") or "uz_female_calm"
        if not text or len(text) > 5000:
            self._json(422, {"detail": "text bo'sh yoki 5000 belgidan uzun"})
            return
        if voice not in _VOICES:
            self._json(422, {"detail": f"noma'lum voice_profile: {voice}"})
            return
        if fmt not in ("l16", "wav"):
            self._json(422, {"detail": f"noma'lum format: {fmt}"})
            return
        if body.get("normalize_numbers", True) and (
                re.search(r"\d{1,2}\.\d{1,2}\.\d{4}[^\W\d_]", text)
                or any(len(re.sub(r"\D", "", m.group())) >= 16
                       for m in re.finditer(r"\d[\d\s.,-]{10,}\d", text))
                or any(not re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{4}", m.group())
                       for m in re.finditer(r"\d+(?:\.\d+){2,}", text))):
            # Jonli normalizator shu naqshlarda yiqiladi (`services/tts.py`
            # izohidagi jadval) - Venera normalizatsiyasiz qayta yuboradi.
            self._json(422, {"detail": "invalid literal for int() with base 10: '09.2025'"})
            return
        chunks = speech_chunks(text)
        stream_id = uuid.uuid4().hex[:12]
        pcm_total = sum(len(c) for c in chunks)
        _pause(0.3, 0.8)        # birinchi bo'lak sintezi - sarlavhalar undan keyin
        content_type = (f"audio/L16; rate={_TTS_RATE}; channels=1" if fmt == "l16" else "audio/wav")
        self._open_stream(200, content_type, {"x-sample-rate": str(_TTS_RATE),
                                              "x-chunk-count": str(len(chunks)),
                                              "x-stream-id": stream_id})
        if fmt == "wav":
            self._chunk(wav_header(pcm_total, _TTS_RATE))
        for i, chunk in enumerate(chunks):
            if i:
                # Sintez real vaqtdan ~7 barobar tez: bo'lak ovozining 15% i.
                _pause(len(chunk) / (2 * _TTS_RATE) * 0.15)
            self._chunk(chunk)
        self._close_stream()
        seconds = pcm_total / (2 * _TTS_RATE)
        self._note = f"  [{fmt}, {len(chunks)} bo'lak, {seconds:.1f}s, {voice}]"

    # --- ixtiyoriy: GAPI (2-variant STT) va Ollama (tasnif) ------------------------

    def gapi_transcribe(self) -> None:
        if not (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip():
            self._json(401, {"error": "unauthorized", "hint": "API kaliti yo'q"})
            return
        raw = self._read(_STT_MAX_BYTES + 64 * 1024)
        if raw is None:
            return
        parts = parse_multipart(raw, self.headers.get("Content-Type") or "")
        if "file" not in parts or not parts["file"][1]:
            self._json(400, {"error": "empty_file", "hint": "file maydoni bo'sh"})
            return
        headers, audio = parts["file"]
        text, seconds = transcript_for(audio, _filename_of(headers), "uz")
        _pause(0.3 + min(2.0, seconds * 0.04))
        job = uuid.uuid4().hex[:16]
        self._note = f"  [gapi, {seconds:.1f}s, {len(text)} belgi]"
        self._json(200, {"id": job, "text": text, "audio_seconds": seconds, "language": "uz"},
                   {"X-Job-Id": job})

    def ollama_chat(self) -> None:
        if not (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip():
            self._json(401, {"error": "unauthorized"})
            return
        body = self._json_body()
        if body is None:
            return
        messages = body.get("messages") if isinstance(body.get("messages"), list) else []
        question = next((str(m.get("content") or "") for m in reversed(messages)
                         if isinstance(m, dict) and m.get("role") == "user"), "")
        label = classify(question)
        _pause(0.3, 0.9)
        self._note = f"  [{label}]"
        self._json(200, {"model": body.get("model") or "mock", "created_at": _iso(),
                         "message": {"role": "assistant", "content": label},
                         "done": True, "done_reason": "stop"})


ROUTES: list[tuple[str, re.Pattern[str], Callable[..., None]]] = [
    (verb, re.compile(path), handler) for verb, path, handler in (
        ("GET", r"/health", Handler.health),
        ("GET", r"/api/health", Handler.assistant_health),
        ("GET", r"/_mock", Handler.mock_state),
        # HR Assistant
        ("POST", r"/api/chat/stream", Handler.chat_stream),
        ("GET", r"/api/chats", Handler.chats_list),
        ("GET", r"/api/chats/([^/]+)", Handler.chat_get),
        ("PATCH", r"/api/chats/([^/]+)", Handler.chat_patch),
        ("DELETE", r"/api/chats/([^/]+)", Handler.chat_delete),
        ("POST", r"/api/chats/([^/]+)/restore", Handler.chat_restore),
        ("GET", r"/api/actions/([^/]+)", Handler.action_get),
        ("POST", r"/api/actions/([^/]+)/(confirm|cancel)", Handler.action_decide),
        ("GET", r"/api/hr/artifacts/([\w.~-]{1,256})/(\w+)", Handler.artifact),
        ("GET", r"/doc/([^/]+)", Handler.doc),
        # STT Router
        ("POST", r"/transcribe", Handler.stt_transcribe),
        # TTS
        ("POST", r"/api/v1/auth/token", Handler.tts_token),
        ("POST", r"/api/v1/tts/stream", Handler.tts_stream),
        # ixtiyoriy
        ("POST", r"/v1/transcribe", Handler.gapi_transcribe),
        ("POST", r"/api/chat", Handler.ollama_chat),
    )
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Venera yuqori xizmatlarining oflayn soxtasi")
    parser.add_argument("--host", default="127.0.0.1", help="tinglanadigan manzil (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8091, help="port (default 8091)")
    parser.add_argument("--speed", type=float, default=1.0,
                        help="kechikishlar ko'paytuvchisi: 1 - tabiiy, 0 - kechikishsiz")
    parser.add_argument("--strict-tokens", action="store_true",
                        help="HRM/CRM tokeni yuborilmagan savolga auth_missing (jonli xulq)")
    parser.add_argument("--silent-tts", action="store_true", help="TTS jim audio beradi")
    parser.add_argument("--seed", type=int, default=None, help="tasodifiy kechikishlar urug'i")
    args = parser.parse_args()
    # Jurnal faylga yo'naltirilganda ham o'zbekcha/ruscha belgilar yiqitmasin.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OPTS.speed, OPTS.strict_tokens, OPTS.silent_tts = max(0.0, args.speed), args.strict_tokens, args.silent_tts
    if args.seed is not None:
        _rng.seed(args.seed)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    print(f"Venera dev mock: http://{args.host}:{args.port}  (speed={OPTS.speed}, "
          f"strict_tokens={OPTS.strict_tokens})\n"
          "  HR Assistant  POST /api/chat/stream · /api/chats · /api/actions · /api/hr/artifacts · /doc\n"
          "  STT Router    POST /transcribe            TTS  POST /api/v1/auth/token · /api/v1/tts/stream\n"
          "  GAPI STT      POST /v1/transcribe         Ollama  POST /api/chat        holat  GET /health\n"
          "  ssenariylar: " + " ".join(name for name, _ in _RULES) + " smalltalk"
          "   (majburlash: savolda mock:<nom>)", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("Venera dev mock to'xtadi.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
