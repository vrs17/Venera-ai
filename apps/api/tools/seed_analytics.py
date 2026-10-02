#!/usr/bin/env python3
"""Analitika omboriga SINOV ma'lumoti: admin panelni bo'sh omborsiz ishlab
chiqish va ko'rsatish uchun.

NEGA KERAK. Admin panelning deyarli har bir sahifasi (grafiklar, foizlar,
"eng sekin javoblar", xabarlar qutisi) faqat ma'lumot bilan tekshiriladi.
Jonli ombor esa ishlab chiqish mashinasida yo'q (va bo'lmasligi kerak -
unda odamlarning savollari). Bu skript o'sha ko'rinishdagi SOXTA ma'lumot
yasaydi:

  * 30 kun, ~40 xodim, bo'limlar bo'yicha; kanallar web ~55%, mini app ~25%,
    bot ~20%; ish kunlari ko'p, dam olish kunlari kam; Toshkent vaqti bilan
    ish soatlarida cho'qqi;
  * yo'nalishlar (rules / hrm / crm / both / clarify / live), javob vaqti
    log-normal va uzun dumli (o'lchangan: `rules` mediana ~15.7 s, p90 ~39 s),
    ~3% xato, ~2% bekor qilingan;
  * HR hujjatlaridan parchalar (haqiqiydek nomlar, sahifalar, ballar),
    HRM/CRM chaqiruvlari, takliflar (ariza), fayllar;
  * har xizmat uchun `api_calls` (assistant, STT, TTS, Ollama, HRM, CRM,
    Keycloak, Telegram), kirish urinishlari (muvaffaqiyatsizlari ham);
  * ~25 xabar (shikoyat) hamma holatlarda, admin izohlari va audit bilan;
    bitta bloklangan va bitta roli o'zgartirilgan xodim.

Natija TAKRORLANADI: bir xil `--seed` - bir xil ma'lumot (vaqtlar esa
`--end` ga, default - hozirga nisbatan).

XAVFSIZLIK. `/home/ymamajonov/Venera` (prod daraxti) ostidagi HAR QANDAY
yo'l rad etiladi - jonli omborga soxta savol yozish statistikani abadiy
buzardi. `--reset` ombordagi HAMMA analitikani o'chiradi (faqat ishlab
chiqish ombori uchun).

Ishlatish (apps/api ichidan):

    venv/bin/python tools/seed_analytics.py                  # ombor bo'sh bo'lsa to'ldiradi
    venv/bin/python tools/seed_analytics.py --reset          # tozalab, qaytadan
    venv/bin/python tools/seed_analytics.py --db /tmp/a.db --days 14 --scale 0.5
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
import uuid

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.services.analytics.db import Database  # noqa: E402

#: Jonli xizmat shu daraxtdan ishlaydi (systemd). Uning ostiga HECH NARSA yozilmaydi.
PROD_ROOT = Path("/home/ymamajonov/Venera")

#: Toshkent - UTC+5, yozgi vaqt yo'q.
TZ_OFFSET = 5 * 3600

#: Seed xodimlari shu raqamdan boshlanadi - `users.yaml` dagi haqiqiy
#: hisoblar (1, 2, ...) bilan to'qnashmasin.
ACTOR_BASE = 9001

TABLES = ("turn_events", "turn_sources", "turns", "api_calls", "auth_events", "reports",
          "user_admin", "audit_log")

ADMIN = {"actorId": 1, "name": "Administrator", "email": "admin@venera.uz"}

# --- xodimlar ---------------------------------------------------------------------

DEPARTMENTS = [
    ("Kadrlar bo'limi", 5), ("Buxgalteriya", 5), ("IT bo'limi", 6), ("Savdo bo'limi", 8),
    ("Marketing", 4), ("Yuridik bo'lim", 3), ("Logistika", 4), ("Mijozlar bilan ishlash", 5),
]
FIRST_M = ["Aziz", "Bobur", "Jasur", "Sardor", "Otabek", "Sherzod", "Rustam", "Javlon", "Ulug'bek",
           "Farrux", "Akmal", "Doston", "Temur", "Eldor", "Nodir", "Islom", "Shoxrux", "Anvar"]
FIRST_F = ["Aziza", "Dilnoza", "Madina", "Nilufar", "Gulnora", "Kamola", "Shahnoza", "Malika",
           "Zarina", "Feruza", "Sevara", "Nodira", "Mohira", "Laylo", "Durdona", "Munisa"]
LAST = ["Karimov", "Aliyev", "Rahimov", "Toshmatov", "Yusupov", "Ergashev", "Qodirov",
        "Mirzayev", "Abdullayev", "Sobirov", "Xolmatov", "Nazarov", "Saidov", "Umarov",
        "Hasanov", "Ismoilov", "Jo'rayev", "Sultonov", "Fayzullayev", "Olimov"]
POSITIONS = ["Mutaxassis", "Bosh mutaxassis", "Yetakchi mutaxassis", "Bo'lim boshlig'i",
             "Menejer", "Operator", "Tahlilchi"]

# --- hujjatlar ------------------------------------------------------------------------

DOCS: dict[str, tuple[str, int, list[str]]] = {
    "ichki-tartib-2024": ("Ichki mehnat tartibi qoidalari", 34, [
        "Ish vaqti dushanbadan jumagacha 09:00 dan 18:00 gacha, tushlik tanaffusi 13:00-14:00.",
        "Ishga 15 daqiqadan ortiq kechikish intizomiy qoidabuzarlik hisoblanadi va tabelda "
        "qayd etiladi.",
        "Xodim ishda bo'lmaslik sababini shu kunning o'zida bevosita rahbariga ma'lum qiladi.",
    ]),
    "tatil-nizom-2025": ("Mehnat ta'tillari to'g'risidagi nizom", 18, [
        "Yillik asosiy ta'til 21 kalendar kundan kam bo'lmagan muddatga beriladi.",
        "Ta'til jadvali har yili 15-dekabrga qadar tuziladi va xodimlar imzo bilan tanishtiriladi.",
        "Ta'tilni qismlarga bo'lish mumkin, bunda qismlardan biri 12 kundan kam bo'lmasligi kerak.",
        "Qo'shimcha ta'til nogironligi bor xodimlarga va zararli sharoitda ishlovchilarga "
        "beriladi.",
    ]),
    "safar-yoriqnoma": ("Xizmat safarlari to'g'risidagi yo'riqnoma", 12, [
        "Xizmat safari davomida kunlik xarajatlar eng kam ish haqining 10 foizi miqdorida "
        "to'lanadi.",
        "Safardan qaytgach uch ish kuni ichida avans hisoboti va chiptalar buxgalteriyaga "
        "topshiriladi.",
    ]),
    "mukofot-nizom": ("Mukofotlash va rag'batlantirish nizomi", 9, [
        "Choraklik mukofot KPI ko'rsatkichlari 90 foizdan yuqori bajarilganda hisoblanadi.",
        "Intizomiy jazosi bor xodimga jazo muddati davomida mukofot berilmaydi.",
    ]),
    "masofaviy-ish": ("Masofaviy ishlash tartibi", 7, [
        "Masofaviy ish haftasiga ko'pi bilan ikki kun, bo'lim rahbarining yozma roziligi bilan "
        "ruxsat etiladi.",
        "Masofadan ishlagan kuni xodim 09:00 dan 18:00 gacha korporativ messenjerda aloqada "
        "bo'ladi.",
    ]),
    "kasallik-varaqasi": ("Vaqtincha mehnatga layoqatsizlik nafaqasi tartibi", 11, [
        "Nafaqa ish stajiga qarab o'rtacha ish haqining 60 foizidan 80 foizigacha to'lanadi.",
        "Kasallik varaqasi yopilgan kundan boshlab besh kun ichida kadrlar bo'limiga topshiriladi.",
    ]),
    "attestatsiya-nizom": ("Xodimlarni attestatsiyadan o'tkazish nizomi", 14, [
        "Attestatsiya uch yilda bir marta, komissiya tomonidan o'tkaziladi.",
        "Attestatsiyadan o'tmagan xodimga uch oy ichida qayta topshirish imkoniyati beriladi.",
    ]),
    "axborot-xavfsizligi": ("Axborot xavfsizligi siyosati", 22, [
        "Parolni boshqa shaxsga berish yoki ochiq joyda yozib qo'yish taqiqlanadi.",
        "Korporativ ma'lumotlarni shaxsiy bulut xizmatlariga yuklash mumkin emas.",
    ]),
    "moddiy-yordam": ("Moddiy yordam ko'rsatish tartibi", 5, [
        "Moddiy yordam xodimning arizasi asosida, to'y yoki yaqin qarindoshi vafot etganda "
        "beriladi.",
        "Moddiy yordam miqdori bir oylik ish haqidan oshmaydi.",
    ]),
    "ishga-qabul": ("Ishga qabul qilish va moslashuv yo'riqnomasi", 10, [
        "Yangi xodimga birinchi ish kuni murabbiy biriktiriladi va moslashuv rejasi beriladi.",
        "Sinov muddati uch oygacha belgilanadi.",
    ]),
    "shartnoma-bekor": ("Mehnat shartnomasini bekor qilish tartibi", 8, [
        "Xodim o'z xohishi bilan ishdan bo'shaganda ish beruvchini ikki hafta oldin yozma "
        "ogohlantiradi.",
        "Oxirgi ish kuni xodim bilan to'liq hisob-kitob qilinadi.",
    ]),
    "kiyinish-qoidasi": ("Korporativ kiyinish qoidalari", 4, [
        "Mijozlar bilan ishlovchi xodimlar dushanbadan payshanbagacha rasmiy kiyimda bo'ladi.",
        "Juma kuni erkin, lekin ozoda kiyinish ruxsat etiladi.",
    ]),
}

#: (savol, hujjatlar, javob). Javobdagi `[n]` - manba tartibi.
RULES_QA: list[tuple[str, list[str], str]] = [
    ("Yillik ta'til necha kun?", ["tatil-nizom-2025"],
     "Yillik asosiy ta'til kamida 21 kalendar kun [1]. Jadval har yili dekabrda tuziladi [1]."),
    ("Ta'tilni ikkiga bo'lsam bo'ladimi?", ["tatil-nizom-2025"],
     "Ha, ta'tilni qismlarga bo'lish mumkin, lekin bir qismi kamida 12 kun bo'lishi kerak [1]."),
    ("Qo'shimcha ta'til kimga beriladi?", ["tatil-nizom-2025", "ichki-tartib-2024"],
     "Qo'shimcha ta'til nogironligi bor xodimlarga va zararli sharoitda ishlovchilarga "
     "beriladi [1]. Batafsil ichki tartib qoidalarida [2]."),
    ("Ish vaqti soat nechadan nechagacha?", ["ichki-tartib-2024"],
     "Ish vaqti dushanba-juma 09:00-18:00, tushlik 13:00-14:00 [1]."),
    ("Kechiksam nima bo'ladi?", ["ichki-tartib-2024", "mukofot-nizom"],
     "15 daqiqadan ortiq kechikish intizomiy qoidabuzarlik sifatida tabelda qayd etiladi [1]. "
     "Intizomiy jazo muddatida mukofot berilmaydi [2]."),
    ("Xizmat safarida kunlik qancha to'lanadi?", ["safar-yoriqnoma"],
     "Kunlik xarajatlar eng kam ish haqining 10 foizi miqdorida to'lanadi [1]."),
    ("Safardan keyin qanday hujjat topshiraman?", ["safar-yoriqnoma"],
     "Uch ish kuni ichida avans hisoboti va chiptalarni buxgalteriyaga topshirasiz [1]."),
    ("Choraklik mukofot qanday hisoblanadi?", ["mukofot-nizom"],
     "Mukofot KPI 90 foizdan yuqori bajarilganda hisoblanadi [1]."),
    ("Uydan ishlash mumkinmi?", ["masofaviy-ish"],
     "Haftasiga ko'pi bilan ikki kun, rahbarning yozma roziligi bilan mumkin [1]. Shu kuni "
     "09:00-18:00 aloqada bo'lasiz [1]."),
    ("Kasallik varaqasi qanday to'lanadi?", ["kasallik-varaqasi"],
     "Nafaqa stajga qarab o'rtacha ish haqining 60-80 foizi miqdorida to'lanadi [1]. "
     "Varaqani yopilgach besh kun ichida kadrlar bo'limiga topshiring [1]."),
    ("Attestatsiya qachon o'tkaziladi?", ["attestatsiya-nizom"],
     "Attestatsiya uch yilda bir marta komissiya tomonidan o'tkaziladi [1]."),
    ("Parolimni hamkasbimga bersam bo'ladimi?", ["axborot-xavfsizligi"],
     "Yo'q, parolni boshqa shaxsga berish taqiqlanadi [1]."),
    ("To'y uchun moddiy yordam olsa bo'ladimi?", ["moddiy-yordam"],
     "Ha, ariza asosida beriladi, miqdori bir oylik ish haqidan oshmaydi [1]."),
    ("Ishdan bo'shash uchun necha kun oldin ariza beriladi?", ["shartnoma-bekor"],
     "Ikki hafta oldin yozma ogohlantirish kerak [1]."),
    ("Yangi xodimga birinchi kuni nima beriladi?", ["ishga-qabul"],
     "Murabbiy biriktiriladi va moslashuv rejasi beriladi [1]. Sinov muddati uch oygacha [1]."),
    ("Juma kuni jinsi shim kiysa bo'ladimi?", ["kiyinish-qoidasi"],
     "Juma kuni erkin, lekin ozoda kiyinish ruxsat etiladi [1]."),
    ("Как оформить отпуск?", ["tatil-nizom-2025"],
     "Ежегодный отпуск - не менее 21 календарного дня [1]; график составляется в декабре [1]."),
]
#: Ariza (fayl) yasaladigan savollar - `artifact` kadri bilan.
ARTIFACT_QA = [
    ("Ta'til uchun ariza yozib bering", ["tatil-nizom-2025"],
     "Ariza tayyor: 14 kalendar kunlik yillik ta'til [1]. Faylni yuklab olib imzolang."),
    ("Xizmat safari uchun ariza tayyorlab ber", ["safar-yoriqnoma"],
     "Ariza tayyorlandi [1]. Safar maqsadi va sanalarini tekshiring."),
]

#: (savol, platforma chaqiruvi, qisqa natija, javob)
HRM_QA = [
    ("Bugun kechikdimmi?", "hrm_today_late", "kelish 08:54, kechikish yo'q",
     "Yo'q, bugun 08:54 da kelgansiz [T1]."),
    ("Bugun ishga kech qoldimmi?", "hrm_today_late", "kelish 09:23, 23 daqiqa",
     "Ha, bugun 09:23 da kelgansiz - 23 daqiqa kechikish [T1]."),
    ("Bu oy necha kun ishladim?", "hrm_month_attendance", "19 ish kuni, 2 kun ta'til",
     "Shu oy 19 kun ishlagansiz, 2 kun ta'tilda bo'lgansiz [T1]."),
    ("Ta'til qoldig'im qancha?", "hrm_vacation_balance", "qoldiq 12 kun",
     "2026 yil uchun ta'til qoldig'ingiz - 12 kun [T1]."),
    ("Oxirgi oylik varaqamni ko'rsat", "hrm_payslip", "avgust 2026, to'langan",
     "Avgust oyi hisob-kitobi tayyor va to'langan [T1]. Batafsil HRM kabinetida."),
    ("Ertaga smenam bormi?", "hrm_schedule", "30-sentabr 09:00-18:00",
     "Ertaga smenangiz 09:00 dan 18:00 gacha [T1]."),
]
CRM_QA = [
    ("Menga biriktirilgan murojaatlar", "crm_my_issues", "ochiq 4, muddati o'tgan 1",
     "Sizda 4 ta ochiq murojaat bor, bittasining muddati o'tgan [T1]."),
    ("48213-murojaat holati qanday?", "crm_issue_status", "jarayonda, Savdo bo'limi",
     "48213-murojaat jarayonda, mas'ul - Savdo bo'limi [T1]."),
    ("Bugungi uchrashuvlarim", "crm_my_meetings", "2 ta: 11:00, 15:30",
     "Bugun ikkita uchrashuv: 11:00 va 15:30 [T1]."),
]
#: Taklif (yozish amali) - tasdiqlashni kutadi.
CRM_PROPOSAL = ("Mijoz uchun yangi murojaat ochib ber", "crm_create_issue", "loyiha tayyor",
                "Murojaat loyihasi tayyor [T1]. Tasdiqlasangiz CRM da ochiladi.")
BOTH_QA = [
    ("Ta'til qoldig'im bor, ariza qanday yoziladi?", "hrm_vacation_balance", "qoldiq 12 kun",
     ["tatil-nizom-2025"],
     "Qoldig'ingiz 12 kun [T1]. Ariza jadval asosida, kamida 12 kunlik qism bilan beriladi [1]."),
    ("Kechikishlarim mukofotga ta'sir qiladimi?", "hrm_month_attendance", "2 kechikish",
     ["mukofot-nizom", "ichki-tartib-2024"],
     "Shu oy 2 ta kechikish qayd etilgan [T1]. Intizomiy jazo bo'lsa mukofot berilmaydi [1] [2]."),
]
LIVE_QA = [
    ("Bo'limimda nechta xodim bor?", "hrm_employee_search", "14 xodim",
     "Bo'limingizda 14 xodim ishlaydi [T1]."),
    ("Kim bugun ta'tilda?", "hrm_department_leaves", "2 xodim",
     "Bugun bo'limingizdan 2 kishi ta'tilda [T1]."),
]
CLARIFY_Q = ["Ariza", "Qancha?", "Salom", "Yordam kerak", "Hujjat", "Muddat qancha"]
CLARIFY_A = "Aniqlashtirib bering: ta'til, xizmat safari yoki moddiy yordam haqida so'rayapsizmi?"

STAGES = {
    "rules": "Hujjatlar qidirilmoqda", "both": "Hujjatlar va HRM ma'lumotlari tekshirilmoqda",
    "hrm": "HRM ma'lumotlari olinmoqda", "crm": "CRM ma'lumotlari olinmoqda",
    "live": "Ma'lumot olinmoqda", "clarify": "Savol tahlil qilinmoqda",
}
#: (median total ms, sigma, ttft ulushi)
LATENCY = {
    "rules": (15700, 0.70, 0.33), "both": (18000, 0.60, 0.36), "hrm": (3500, 0.35, 0.62),
    "crm": (4200, 0.40, 0.60), "live": (5000, 0.45, 0.55), "clarify": (2000, 0.30, 0.55),
}
ROUTES = [("rules", 46), ("hrm", 24), ("crm", 10), ("both", 8), ("clarify", 8), ("live", 4)]
ERRORS = [
    # (kod, http, matn, ulush)
    ("auth_missing", 200, "Bu savol uchun CRM hisobingizni ulang", 35),
    ("upstream_timeout", 504, "Javob juda uzoq cho'zildi", 25),
    ("AssistantError", 502, "Savol-javob xizmati javob bermadi", 20),
    ("busy", 503, "Savol-javob xizmati band, biroz kutib qayta urinib ko'ring", 12),
    ("rate_limited", 429, "So'rovlar ko'p, bir daqiqadan keyin urinib ko'ring", 8),
]
#: Toshkent vaqti bo'yicha soatlik og'irliklar (0..23).
HOUR_WEIGHTS = [0.1, 0.05, 0.05, 0.05, 0.05, 0.1, 0.3, 1.0, 4.0, 9.0, 10.0, 9.0, 5.0, 4.0,
                8.0, 9.0, 8.0, 5.0, 3.0, 2.0, 1.5, 1.0, 0.6, 0.3]

REPORT_COMMENTS = {
    "wrong": ["Javobda 24 kun deyilgan, nizomda 21 kun.", "Mukofot foizi noto'g'ri ko'rsatilgan",
              "Bu boshqa bo'limga tegishli qoida"],
    "incomplete": ["Qaysi hujjatlar kerakligi aytilmadi", "Javob yarmida uzilib qoldi",
                   "Ariza namunasini ham berish kerak edi"],
    "outdated": ["Bu 2023 yilgi nizom, yangisi bor", "Kiyinish qoidasi o'zgargan"],
    "unsafe": ["Boshqa xodimning ma'lumoti ko'rinib qoldi"],
    "other": ["Javob juda uzun, qisqaroq bo'lsa yaxshi", "Ovozli javob o'qilmadi"],
}
ADMIN_NOTES = {
    "resolved": ["Nizomning yangi versiyasi yuklandi", "Hujjat indeksi yangilandi",
                 "Yuqori xizmat jamoasiga yuborildi, tuzatildi"],
    "dismissed": ["Javob nizomga mos", "Takroriy xabar"],
    "reviewing": ["Kadrlar bo'limidan tasdiq kutilmoqda"],
}
REPORT_PLAN = {"new": 8, "reviewing": 5, "resolved": 8, "dismissed": 4}


# --- yordamchilar ---------------------------------------------------------------------


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds") \
        .replace("+00:00", "Z")


def weighted(rng: random.Random, pairs: list[tuple[Any, float]]) -> Any:
    items, weights = zip(*pairs)
    return rng.choices(items, weights=weights, k=1)[0]


def lognormal_ms(rng: random.Random, median: float, sigma: float) -> int:
    return max(50, int(median * math.exp(rng.gauss(0.0, sigma))))


def seed_engine(turn_id: str, channel: str) -> str:
    """Yordamchi dvigateli (`turns.engine`, sxema v2): web - `v2`, mini app va
    botning taxminan chorak savoli - `v1` (kanal istisnosi sinovda, `core/
    engines.py`). Tasodif `rng` dan OLINMAYDI - kalitdan: aks holda qolgan
    hamma qiymat (va takrorlanuvchanlik testi) siljib ketardi."""
    if channel in ("miniapp", "bot") and int(turn_id[-1], 16) % 4 == 0:
        return "v1"
    return "v2"


def hex_id(rng: random.Random) -> str:
    return uuid.UUID(int=rng.getrandbits(128), version=4).hex


def chat_uuid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def compact(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


@dataclass
class Person:
    actor_id: int
    name: str
    login: str
    department: str
    position: str
    primary: str
    weight: float
    voice: float


@dataclass
class Data:
    turns: list[tuple] = field(default_factory=list)
    events: list[tuple] = field(default_factory=list)
    sources: list[tuple] = field(default_factory=list)
    calls: list[tuple] = field(default_factory=list)
    auth: list[tuple] = field(default_factory=list)
    reports: list[tuple] = field(default_factory=list)
    user_admin: list[tuple] = field(default_factory=list)
    audit: list[tuple] = field(default_factory=list)
    #: Xabar nusxasi uchun: chat_id -> [(ts, savol, javob, turn_id, manbalar)]
    chats: dict[str, list[tuple]] = field(default_factory=dict)
    #: Xabar berish mumkin bo'lgan savollar: (turn_id, ts, person, channel, chat_id, status)
    reportable: list[tuple] = field(default_factory=list)


def people(rng: random.Random, count: int) -> list[Person]:
    out: list[Person] = []
    used: set[str] = set()
    slots = [dept for dept, size in DEPARTMENTS for _ in range(size)]
    rng.shuffle(slots)
    while len(slots) < count:
        slots.append(rng.choice(DEPARTMENTS)[0])
    for index in range(count):
        female = rng.random() < 0.45
        first = rng.choice(FIRST_F if female else FIRST_M)
        last = rng.choice(LAST) + ("a" if female else "")
        login = f"{first[0].lower()}.{last.lower().replace(chr(39), '')}"
        while login in used:
            login += str(rng.randint(1, 9))
        used.add(login)
        primary = weighted(rng, [("web", 55), ("miniapp", 25), ("bot", 20)])
        out.append(Person(
            actor_id=ACTOR_BASE + index, name=f"{first} {last}", login=login,
            department=slots[index],
            position="Bo'lim boshlig'i" if rng.random() < 0.12 else rng.choice(POSITIONS),
            primary=primary,
            # Faollik: ozchilik ko'p so'raydi, ko'pchilik kam - log-normal.
            weight=math.exp(rng.gauss(0.0, 0.8)),
            voice={"web": 0.12, "miniapp": 0.08, "bot": 0.35}[primary],
        ))
    return out


# --- savol --------------------------------------------------------------------------------


class Builder:
    """Bitta savolning qatorlari: `turns`, hodisalar, manbalar, chaqiruvlar -
    `TurnRecorder` va metr yozadigan shaklda."""

    def __init__(self, rng: random.Random, data: Data) -> None:
        self.rng = rng
        self.data = data

    def call(self, ts: float, service: str, op: str, ms: int, *, person: Person | None,
             channel: str | None, turn_id: str | None = None, units: dict | None = None,
             fail: float = 0.02, http_ok: int = 200,
             error: tuple[int, str] | None = None) -> bool:
        rng = self.rng
        failed = error is not None or rng.random() < fail
        if failed and error is None:
            error = rng.choice([(503, "HTTP 503: navbat to'la"), (504, "timeout (35 s)"),
                                (502, "HTTP 502: Bad Gateway")])
        self.data.calls.append((
            ts, service, op, "error" if failed else "ok",
            error[0] if failed else http_ok, max(1, int(ms)),
            person.actor_id if person else None, channel, turn_id,
            compact(units) if units else None, error[1] if failed else None,
        ))
        return not failed

    def turn(self, person: Person, ts: float, channel: str, chat_id: str) -> float:
        """Savolni yozadi; javob tugagan lahzani qaytaradi (keyingi savol undan keyin)."""
        rng = self.rng
        data = self.data
        turn_id = hex_id(rng)
        voice = rng.random() < (person.voice if channel == person.primary
                                else {"web": 0.12, "miniapp": 0.08, "bot": 0.35}[channel])
        kind = "bot" if channel == "bot" else "chat"
        # Bot faqat ichki Router'ni ishlatadi; web/mini app - ~30% GAPI.
        provider = "stt_gapi" if channel != "bot" and rng.random() < 0.3 else "stt_router"
        route = weighted(rng, ROUTES)
        roll = rng.random()
        status = "error" if roll < 0.03 else ("cancelled" if roll < 0.05 else "ok")
        failure = weighted(rng, [(e, e[3]) for e in ERRORS]) if status == "error" else None
        if failure and failure[0] == "auth_missing":
            # "Hisobingizni ulang" - faqat jonli HRM/CRM savolida bo'ladi.
            route = rng.choice(["crm", "hrm"])

        docs: list[str] = []
        tool: tuple[str, str] | None = None
        proposal = artifact = False
        if route == "rules":
            if rng.random() < 0.06:
                question, docs, answer = rng.choice(ARTIFACT_QA)
                artifact = True
            else:
                question, docs, answer = rng.choice(RULES_QA)
        elif route == "hrm":
            question, name, digest, answer = rng.choice(HRM_QA)
            tool = (name, digest)
        elif route == "crm":
            if rng.random() < 0.18:
                question, name, digest, answer = CRM_PROPOSAL
                proposal = True
            else:
                question, name, digest, answer = rng.choice(CRM_QA)
            tool = (name, digest)
        elif route == "both":
            question, name, digest, docs, answer = rng.choice(BOTH_QA)
            tool = (name, digest)
        elif route == "live":
            question, name, digest, answer = rng.choice(LIVE_QA)
            tool = (name, digest)
        else:
            question, answer = rng.choice(CLARIFY_Q), CLARIFY_A
        locale = "ru" if any("а" <= ch.lower() <= "я" for ch in question) else \
            weighted(rng, [("uz", 95), ("en", 5)])

        median, sigma, share = LATENCY[route]
        total = lognormal_ms(rng, median, sigma)
        if rng.random() < 0.04:
            total = int(total * rng.uniform(2.5, 4.0))              # uzun dum
        # O'lchangan eng sekini 72.6 s; undan ancha uzuni - nosozlik, bu yerda emas.
        total = min(total, 110_000)
        ttft = max(250, int(total * min(0.95, share * math.exp(rng.gauss(0.0, 0.25)))))
        error_code = error_text = None
        http_status: int | None = 200
        if failure is not None:
            error_code, http_status, error_text, _ = failure
            if error_code == "auth_missing":
                total, ttft, answer = rng.randint(700, 1600), None, None
            elif error_code == "upstream_timeout":
                total, ttft, answer = 120_000 + rng.randint(0, 900), None, None
            else:
                total, ttft, answer = rng.randint(300, 4000), None, None
            if error_code != "auth_missing":
                route = None
        elif status == "cancelled":
            total = rng.randint(400, max(500, ttft))
            ttft = ttft if rng.random() < 0.3 and ttft < total else None
            http_status, route = None, None
            answer = answer[:rng.randint(0, len(answer) // 2)] if ttft else None

        # Ovoz: savol avval matnga o'giriladi - javob oqimi undan keyin boshlanadi.
        stt_ms = rng.randint(700, 2600) if voice else 0
        request_id = f"req_{hex_id(rng)[:16]}" if status != "cancelled" or ttft else None
        answer_text = answer or ""
        frames = (len(answer_text) // 4 + 6) if answer_text else 2
        started = ts
        ended = ts + (stt_ms + total) / 1000.0
        proposal_token = f"prop_{hex_id(rng)[:20]}" if proposal and status == "ok" else None
        proposal_status = None
        if proposal_token:
            proposal_status = weighted(rng, [("executed", 60), ("cancelled", 20), ("expired", 10),
                                             ("failed", 5), ("pending", 5)])

        # --- manbalar ---
        source_rows: list[tuple] = []
        snapshot_sources: list[dict] = []
        if status == "ok" or (status == "cancelled" and ttft):
            idx = 0
            for position, doc_id in enumerate(docs):
                title, pages, snippets = DOCS[doc_id]
                for chunk in range(rng.choice([1, 1, 2])):
                    item = {"kind": "doc", "doc_id": doc_id, "title": title,
                            "page": rng.randint(1, pages), "citation_index": position + 1,
                            "score": round(rng.uniform(0.62, 0.95) - 0.05 * chunk, 3),
                            "snippet": rng.choice(snippets)}
                    source_rows.append((turn_id, idx, "doc", doc_id, title, item["page"],
                                        item["score"], item["snippet"], None, None,
                                        position + 1, compact(item)))
                    snapshot_sources.append({k: item[k] for k in (
                        "kind", "doc_id", "title", "page", "citation_index")})
                    idx += 1
            if tool:
                ok = rng.random() > 0.03
                item = {"kind": tool[0].split("_", 1)[0], "tool": tool[0], "marker": "[T1]",
                        "status": "200" if ok else "error", "digest": tool[1] if ok else "xato"}
                source_rows.append((turn_id, idx, item["kind"], tool[0], None, None, None, None,
                                    item["status"], item["digest"], 1, compact(item)))
                snapshot_sources.append(item)
        docs_count = sum(1 for r in source_rows if r[2] == "doc")
        tools_count = len(source_rows) - docs_count
        data.sources.extend(source_rows)

        # --- vaqt chizig'i (`recorder.py` yozadigan nomlar) ---
        events: list[tuple] = []

        def event(t_ms: int, etype: str, name: str, payload: Any = None,
                  dur: int | None = None) -> None:
            events.append((turn_id, len(events), max(0, int(t_ms)), dur, etype, name,
                           compact(payload) if payload is not None else None))

        if voice:
            event(0, "span", "stt", {"provider": provider.removeprefix("stt_"),
                                     "audioSec": round(stt_ms / 1000 * 2.4, 1)}, stt_ms)
            event(stt_ms + 20, "span", "hold.classify",
                  {"model": "gemma4:31b", "topic": route or "unknown",
                   "tone": rng.choice(["oddiy", "shoshilinch"])}, rng.randint(500, 1500))
        open_ms = rng.randint(120, 650)
        event(stt_ms, "span", "assistant.open", {"requestId": request_id}, open_ms)
        if status != "error" or error_code == "auth_missing":
            event(stt_ms + open_ms, "note", "first_frame", {"type": "stage"})
            event(stt_ms + open_ms + 1, "frame", "stage", {"text": STAGES.get(route or "", "")})
        if source_rows:
            refs = [r[3] for r in source_rows]
            event(stt_ms + (ttft or total) * 0.7, "frame", "sources",
                  {"count": len(source_rows), "docs": docs_count, "tools": tools_count,
                   "refs": sorted(set(refs), key=refs.index)})
        if ttft is not None:
            event(stt_ms + ttft, "note", "first_token")
        if proposal_token:
            event(stt_ms + total - 40, "frame", "proposal",
                  {"summary": "Yangi murojaat: mijoz so'rovi", "operation": "create_issue",
                   "connector": "crm"})
        if artifact and status == "ok":
            event(stt_ms + total - 30, "frame", "artifact",
                  {"title": "Ariza", "doc_id": f"ariza-{hex_id(rng)[:8]}",
                   "files": ["docx", "pdf", "preview"]})
        if status == "ok":
            event(stt_ms + total, "frame", "done", {"route": route, "request_id": request_id})
        elif status == "error":
            event(stt_ms + total, "frame", "error", {"code": error_code, "text": error_text})
        data.events.extend(events)

        data.turns.append((
            turn_id, started, ended, person.actor_id, person.name, person.login, channel, kind,
            "voice" if voice else "text", locale, chat_id, request_id, question,
            answer if answer else None, route, status, error_code,
            error_text if status == "error" else None,
            http_status if status != "cancelled" else None, ttft,
            stt_ms + total, frames, docs_count, tools_count,
            1 if artifact and status == "ok" else 0, 1 if proposal_token else 0,
            proposal_token, proposal_status, len(answer_text),
            seed_engine(turn_id, channel),
        ))
        data.chats.setdefault(chat_id, []).append(
            (started, question, answer_text, turn_id, snapshot_sources))
        data.reportable.append((turn_id, ended, person, channel, chat_id, status))

        # --- tashqi chaqiruvlar ---
        stream_start = ts + stt_ms / 1000.0
        if voice:
            if channel == "bot":
                self.call(ts, "telegram", "getFile", rng.randint(80, 260), person=person,
                          channel=channel, turn_id=turn_id,
                          units={"bytes": rng.randint(9000, 90000)},
                          fail=0.005)
            self.call(ts, provider, "transcribe", stt_ms, person=person, channel=channel,
                      units={"audioSec": round(stt_ms / 1000 * 2.4, 1)}, fail=0.02)
            self.call(stream_start, "ollama", "classify", rng.randint(450, 1500), person=person,
                      channel=channel, turn_id=turn_id, fail=0.03)
        if route in ("crm", "both") and rng.random() < 0.5:
            self.call(stream_start - 0.3, "crm", "refresh", rng.randint(120, 420), person=person,
                      channel=channel, turn_id=turn_id, fail=0.01)
        stream_error = (http_status, f"HTTP {http_status}: {error_code}") \
            if status == "error" and error_code != "auth_missing" else None
        self.call(stream_start, "assistant", "stream", total, person=person, channel=channel,
                  turn_id=turn_id, units={"frames": frames}, fail=0.0, error=stream_error)
        if status != "ok":
            return ended
        if proposal_status in ("executed", "failed"):
            self.call(ended + rng.uniform(15, 90), "assistant", "action.confirm",
                      rng.randint(400, 2600), person=person, channel=channel, turn_id=turn_id,
                      error=(502, "HTTP 502: CRM rad etdi") if proposal_status == "failed"
                      else None)
        if artifact and rng.random() < 0.8:
            self.call(ended + rng.uniform(5, 60), "assistant", "artifact", rng.randint(150, 900),
                      person=person, channel=channel, turn_id=turn_id,
                      units={"bytes": rng.randint(18_000, 46_000)}, fail=0.01)
        if docs and channel != "bot" and rng.random() < 0.12:
            self.call(ended + rng.uniform(5, 120), "assistant", "doc", rng.randint(200, 1800),
                      person=person, channel=channel, turn_id=turn_id,
                      units={"bytes": rng.randint(180_000, 2_400_000)}, fail=0.01)
        if channel == "bot":
            for _ in range(rng.choice([1, 1, 2])):
                self.call(ended + rng.uniform(0.1, 1.5), "telegram", "sendMessage",
                          rng.randint(90, 320), person=person, channel=channel,
                          turn_id=turn_id, fail=0.005)
        elif voice or rng.random() < 0.06:
            chars = min(len(answer_text), settings.tts_max_chars)
            self.call(ended + 0.2, "tts", "speak", 1300 + chars * rng.uniform(8, 14),
                      person=person, channel=channel, turn_id=turn_id if voice else None,
                      units={"chars": chars}, fail=0.025)
        return ended


# --- yig'ish -----------------------------------------------------------------------------


def generate(rng: random.Random, *, days: int, users: int, scale: float, end: float) -> Data:
    data = Data()
    builder = Builder(rng, data)
    staff = people(rng, users)
    start = end - days * 86400.0

    blocked = min(staff, key=lambda p: p.weight)
    block_at = end - 3 * 86400.0
    promoted = sorted(staff, key=lambda p: -p.weight)[1]
    last_seen: dict[int, tuple[float, str, str]] = {}

    # Toshkent kunlari bo'yicha: kun boshi (UTC) = mahalliy yarim tun - 5 soat.
    first_day = math.floor((start + TZ_OFFSET) / 86400.0) * 86400.0 - TZ_OFFSET
    day = first_day
    while day < end:
        weekday = datetime.fromtimestamp(day + TZ_OFFSET, timezone.utc).weekday()
        volume = (110 if weekday < 5 else (28 if weekday == 5 else 14)) * scale
        count = max(0, int(rng.gauss(volume, volume * 0.12)))
        hours = [(h, w) for h, w in enumerate(HOUR_WEIGHTS)]
        # Avval kunning hamma savollari, keyin VAQT TARTIBIDA: suhbatga
        # qo'shilish "oldingi savoldan 30 daqiqa ichida" degan qoidaga tayanadi.
        # Suhbat - o'rtacha ~1.8 savol (aniqlashtiruvchi savollar bilan), ya'ni
        # kunlik hajmni saqlash uchun boshlanishlar shunchaga kam.
        moments = sorted(
            (day + weighted(rng, hours) * 3600.0 + rng.uniform(0, 3600),
             rng.choices(staff, weights=[p.weight for p in staff], k=1)[0].actor_id)
            for _ in range(int(count / 1.8)))
        by_id = {p.actor_id: p for p in staff}
        logged: set[int] = set()
        for ts, actor_id in moments:
            person = by_id[actor_id]
            if not start <= ts < end:
                continue
            if person is blocked and ts >= block_at:
                continue
            channel = person.primary if rng.random() < 0.75 else \
                weighted(rng, [("web", 55), ("miniapp", 25), ("bot", 20)])
            # Suhbat: 30 daqiqa ichida o'sha kanaldan kelgan savol - o'sha suhbat
            # (bot uchun 6 soat - `telegram_chat_idle_hours`).
            previous = last_seen.get(person.actor_id)
            idle = 6 * 3600.0 if channel == "bot" else 1800.0
            if previous and previous[1] == channel and 0 <= ts - previous[0] < idle \
                    and rng.random() < 0.7:
                chat_id = previous[2]
            else:
                chat_id = f"tg-{person.actor_id}-{int(ts)}" if channel == "bot" \
                    else chat_uuid(rng)
                if channel != "bot" and rng.random() < 0.7:
                    builder.call(ts - rng.uniform(2, 30), "assistant", "chats.list",
                                 rng.randint(60, 320), person=person, channel=channel,
                                 units={"bytes": rng.randint(900, 9000)}, fail=0.01)
            last_seen[person.actor_id] = (ts, channel, chat_id)
            if channel != "bot" and person.actor_id not in logged and rng.random() < 0.35:
                logged.add(person.actor_id)
                login_events(rng, builder, data, person, ts - rng.uniform(20, 600), channel)
            moment = ts
            for _ in range(8):
                ended = builder.turn(person, moment, channel, chat_id)
                last_seen[person.actor_id] = (moment, channel, chat_id)
                # Javobni o'qib, keyingi savol: 20 s - 4 daqiqa.
                moment = ended + rng.uniform(20, 240)
                if rng.random() > 0.45 or moment >= end:
                    break
        day += 86400.0

    stray_logins(rng, data, start, end)
    blocked_story(rng, data, blocked, block_at, end)
    promotion(rng, data, promoted, start + (end - start) * 0.4)
    reports(rng, data, end)
    return data


def login_events(rng: random.Random, builder: Builder, data: Data, person: Person, ts: float,
                 channel: str) -> None:
    """Kirish: ba'zan avval xato parol, SSO bo'lsa Keycloak chaqiruvi va
    HRM ulanishi (HRM tokeni 10 soat yashaydi - odam har kuni qayta ulanadi)."""
    method = "sso" if rng.random() < 0.85 else "local"
    if rng.random() < 0.07:
        data.auth.append((ts - rng.uniform(10, 60), None, person.login, 0, method, channel,
                          "bad_password"))
        if method == "sso":
            builder.call(ts - 30, "keycloak", "authenticate", rng.randint(180, 600), person=None,
                         channel=channel, error=(401, "HTTP 401: invalid_grant"))
    if method == "sso" and rng.random() < 0.01:
        data.auth.append((ts - 5, None, person.login, 0, method, channel, "sso_unavailable"))
        builder.call(ts - 5, "keycloak", "authenticate", 10_000, person=None, channel=channel,
                     error=(504, "timeout (10 s)"))
    data.auth.append((ts, person.actor_id, person.login, 1, method, channel, None))
    if method == "sso":
        builder.call(ts, "keycloak", "authenticate", rng.randint(180, 700), person=person,
                     channel=channel, fail=0.0)
        if rng.random() < 0.4:
            builder.call(ts + 1, "hrm", "authenticate", rng.randint(250, 1200), person=person,
                         channel=channel, fail=0.03)


def stray_logins(rng: random.Random, data: Data, start: float, end: float) -> None:
    """Noma'lum loginlar bilan urinishlar - "kim tizimni sinayapti" ko'rinsin."""
    for _ in range(12):
        ts = rng.uniform(start, end)
        login = rng.choice(["admin", "test", "root", "hr", "manager@brb.uz"])
        data.auth.append((ts, None, login, 0, "local", rng.choice(["web", "miniapp"]),
                          "unknown_user"))


def blocked_story(rng: random.Random, data: Data, person: Person, block_at: float,
                  end: float) -> None:
    """Bitta xodim bloklangan: `user_admin`, audit va keyingi rad etilgan kirishlar."""
    data.user_admin.append((person.actor_id, None, 1, 1, "Ishdan bo'shagan, hisob yopildi",
                            block_at, ADMIN["email"]))
    data.audit.append((block_at, ADMIN["actorId"], ADMIN["name"], "user.block", "user",
                       str(person.actor_id), compact({"tokenVersion": 1})))
    for _ in range(2):
        data.auth.append((rng.uniform(block_at + 3600, end), person.actor_id, person.login, 0,
                          "sso", "web", "blocked"))


def promotion(rng: random.Random, data: Data, person: Person, at: float) -> None:
    """Bitta faol xodimga RAG_ADMIN - hujjatlar va izlarni ko'ra oladi."""
    roles = ["USER", "RAG_ADMIN"]
    data.user_admin.append((person.actor_id, compact(roles), 0, 0, None, at, ADMIN["email"]))
    data.audit.append((at, ADMIN["actorId"], ADMIN["name"], "user.roles", "user",
                       str(person.actor_id),
                       compact({"from": ["USER"], "to": roles, "override": roles})))


def reports(rng: random.Random, data: Data, end: float) -> None:
    """~25 xabar: nusxa - suhbatning shu savolgacha bo'lgan qismi (telemetriyadan)."""
    plan = [status for status, count in REPORT_PLAN.items() for _ in range(count)]
    candidates = [c for c in data.reportable if c[5] in ("ok", "error")]
    if not candidates:
        return
    # Xatolar ko'proq xabar oladi - haqiqatda ham shunday.
    weights = [4.0 if c[5] == "error" else 1.0 for c in candidates]
    picked: set[str] = set()
    for status in plan:
        for _ in range(20):
            turn_id, ended, person, channel, chat_id, _state = \
                rng.choices(candidates, weights=weights, k=1)[0]
            if turn_id not in picked:
                break
        picked.add(turn_id)
        created = min(end - 60, ended + rng.uniform(20, 900))
        reason = weighted(rng, [("wrong", 35), ("incomplete", 25), ("outdated", 15),
                                ("unsafe", 5), ("other", 10), (None, 10)])
        comment = rng.choice(REPORT_COMMENTS[reason]) if reason and rng.random() < 0.75 else None
        messages = []
        for at, question, answer, key, sources in data.chats.get(chat_id, []):
            if at > ended:
                break
            messages.append({"role": "user", "content": question, "createdAt": iso(at),
                             "turnId": key})
            messages.append({"role": "assistant", "content": answer, "createdAt": iso(at + 5),
                             "turnId": key, **({"sources": sources} if sources else {})})
        # Har beshinchi xabar - butun suhbatga (aniq javobsiz).
        target = None if rng.random() < 0.2 else turn_id
        report_id = hex_id(rng)
        note = updated_at = updated_by = None
        if status != "new":
            updated_at = min(end - 30, created + rng.uniform(1800, 3 * 86400))
            updated_by = ADMIN["email"]
            note = rng.choice(ADMIN_NOTES[status]) if rng.random() < 0.8 else None
            data.audit.append((updated_at, ADMIN["actorId"], ADMIN["name"], "report.status",
                               "report", report_id, compact({"from": "new", "to": status})))
            if note:
                data.audit.append((updated_at + 1, ADMIN["actorId"], ADMIN["name"],
                                   "report.note", "report", report_id,
                                   compact({"chars": len(note), "preview": note})))
        data.reports.append((
            report_id, created, person.actor_id, person.name, person.login, channel, chat_id,
            target, reason, comment,
            compact({"source": "telemetry", "messages": messages}),
            status, note, updated_at, updated_by,
        ))


# --- ombor ---------------------------------------------------------------------------------


def guard(path: Path) -> None:
    """Prod daraxti ostidagi yo'l - to'xtash. Symlink orqali ham, nisbiy yo'l
    bilan ham aylanib o'tib bo'lmasin: ikkala ko'rinish tekshiriladi."""
    for candidate in (path.absolute(), path.resolve()):
        if candidate == PROD_ROOT or PROD_ROOT in candidate.parents:
            raise SystemExit(f"RAD ETILDI: {candidate} - prod daraxti ({PROD_ROOT}) ostida. "
                             "Sinov ma'lumoti jonli omborga yozilmaydi.")


def write(db: Database, data: Data, *, reset: bool) -> None:
    with db.transaction() as conn:
        if reset:
            for table in TABLES:
                conn.execute(f"DELETE FROM {table}")
        conn.executemany(
            "INSERT INTO turns (id, started_at, ended_at, actor_id, user_name, user_login, "
            "channel, kind, input_mode, locale, chat_id, request_id, question, answer, route, "
            "status, error_code, error_text, http_status, ttft_ms, total_ms, frames, "
            "sources_count, tool_calls, has_artifact, has_proposal, proposal_token, "
            "proposal_status, answer_chars, engine) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", data.turns)
        conn.executemany(
            "INSERT INTO turn_events (turn_id, seq, t_ms, dur_ms, type, name, payload) "
            "VALUES (?,?,?,?,?,?,?)", data.events)
        conn.executemany(
            "INSERT INTO turn_sources (turn_id, idx, kind, ref, title, page, score, snippet, "
            "status, digest, citation, raw) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", data.sources)
        conn.executemany(
            "INSERT INTO api_calls (ts, service, op, status, http_status, duration_ms, actor_id, "
            "channel, turn_id, units, error) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            sorted(data.calls, key=lambda c: c[0]))
        conn.executemany(
            "INSERT INTO auth_events (ts, actor_id, login, ok, method, channel, reason) "
            "VALUES (?,?,?,?,?,?,?)", sorted(data.auth, key=lambda a: a[0]))
        conn.executemany(
            "INSERT INTO reports (id, created_at, actor_id, user_name, user_login, channel, "
            "chat_id, turn_id, reason, comment, snapshot, status, admin_note, updated_at, "
            "updated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", data.reports)
        conn.executemany(
            "INSERT OR REPLACE INTO user_admin (actor_id, roles, disabled, token_version, note, "
            "updated_at, updated_by) VALUES (?,?,?,?,?,?,?)", data.user_admin)
        conn.executemany(
            "INSERT INTO audit_log (ts, admin_actor_id, admin_name, action, target_type, "
            "target_id, detail) VALUES (?,?,?,?,?,?,?)", sorted(data.audit, key=lambda a: a[0]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analitika omboriga sinov ma'lumoti")
    parser.add_argument("--db", type=Path, default=None,
                        help="Ombor fayli (default: sozlamadagi ANALYTICS_DB_FILE)")
    parser.add_argument("--days", type=int, default=30, help="Necha kunlik (default 30)")
    parser.add_argument("--users", type=int, default=40, help="Xodimlar soni (default 40)")
    parser.add_argument("--scale", type=float, default=1.0,
                        help="Savollar hajmi koeffitsienti (1.0 - ish kuniga ~110 ta)")
    parser.add_argument("--seed", type=int, default=2026, help="Tasodif urug'i")
    parser.add_argument("--end", default=None,
                        help="Oxirgi lahza, ISO-8601 (default: hozir)")
    parser.add_argument("--reset", action="store_true",
                        help="Ombordagi HAMMA analitikani o'chirib, qaytadan to'ldirish")
    args = parser.parse_args(argv)

    path = Path(args.db) if args.db else Path(
        getattr(settings, "analytics_db_file", Path(__file__).resolve().parents[1]
                / "data" / "analytics" / "venera.db"))
    guard(path)
    if args.days < 1 or args.users < 1 or args.scale <= 0:
        parser.error("--days, --users va --scale musbat bo'lishi kerak")
    end = time.time()
    if args.end:
        text = args.end[:-1] + "+00:00" if args.end.endswith("Z") else args.end
        moment = datetime.fromisoformat(text)
        end = (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp()

    db = Database(path)
    try:
        existing = int(db.scalar("SELECT COUNT(*) FROM turns", default=0))
        if existing and not args.reset:
            print(f"Omborda allaqachon {existing} ta savol bor ({path}).\n"
                  "Qaytadan to'ldirish uchun: --reset (HAMMA analitika o'chadi).",
                  file=sys.stderr)
            return 1
        started = time.monotonic()
        data = generate(random.Random(args.seed), days=args.days, users=args.users,
                        scale=args.scale, end=end)
        write(db, data, reset=args.reset)
        took = time.monotonic() - started
        print(f"Ombor: {path}")
        print(f"Oraliq: {iso(end - args.days * 86400)} .. {iso(end)}")
        for name, rows in (("savollar", data.turns), ("hodisalar", data.events),
                           ("manbalar", data.sources), ("chaqiruvlar", data.calls),
                           ("kirishlar", data.auth), ("xabarlar", data.reports),
                           ("audit", data.audit)):
            print(f"  {name:<12} {len(rows):>7}")
        print(f"Tayyor: {took:.1f} s")
    finally:
        db.close_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
