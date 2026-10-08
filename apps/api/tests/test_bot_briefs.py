"""Rahbariyat brifi: hodisalarni ajratish, kesh, brif, menyu va tugmalar.

Telegram ham, model ham SOXTA - tarmoqqa chiqilmaydi.
"""

from __future__ import annotations

import itertools
import json
import re
import sqlite3

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.bot import briefs as briefs_mod
from app.bot.briefs import (BTN_ALL, BTN_ONE, REMOVE_KEYBOARD, REPLY_KEYBOARD, BriefEngine, BriefService,
                            _CLOSED, _NOT_PERIOD, code_for, merge, parse_events, period_for, render_brief,
                            validate_events, GroupStats)
from app.bot.groups import TZ, Period, parse_period
from app.bot.runner import _UNKNOWN, VeneraBot
from app.services.integrations.ollama import OllamaError
from app.services.telegram_links import LinkStore
from app.services.tg_groups import GroupStore, Row
from tests.test_bot_ux import BOT_NAME, WEBAPP, Directory, _stored, press
from tests.test_telegram_bot import TG_ID, FakeBackend, FakeTelegram, text_update

G1, G2 = -1001111111111, -1002222222222
T1, T2 = "AI team", "Kredit loyihasi"
NOW = datetime(2026, 10, 8, 15, 0, tzinfo=TZ).timestamp()          # payshanba
_ids = itertools.count(100)


class BriefTelegram(FakeTelegram):
    """`FakeTelegram` + tahrirdagi tugmalar ham yoziladi."""

    def edit_message_text(self, chat_id, message_id, text, *, html=True, reply_markup=None):
        self._rec("edit_message_text", chat_id=chat_id, message_id=message_id, text=text,
                  reply_markup=reply_markup)


class ScriptWriter:
    """Model o'rnida: (guruh nomi, kun) -> JSON yoki xato; sarlavha - qisqa ro'yxat."""

    def __init__(self) -> None:
        self.days: dict[tuple[str, str], object] = {}
        self.calls: list[tuple[str, str, dict]] = []
        self.headline: object = "- Asosiy: API xatosi hal bo'lmagan\n- Qaror qabul qilindi"

    def complete(self, system, user, *, num_predict=1200, temperature=0.2, op="group", format=None):
        self.calls.append((op, user, {"temperature": temperature, "format": format}))
        if op == "brief_headline":
            if isinstance(self.headline, Exception):
                raise self.headline
            return self.headline
        group = re.search(r"Guruh: (.*)", user).group(1)
        day = re.search(r"Kun: (\d{4}-\d{2}-\d{2})", user).group(1)
        answer = self.days.get((group, day), '{"events": []}')
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, list):              # navbatdagi javoblar (qayta urinish uchun)
            return answer.pop(0)
        return answer

    def extracts(self):
        return [c for c in self.calls if c[0] == "brief_extract"]


def msg(chat, text, ago, *, who="Sardor", title=None, reply=None):
    message = {"message_id": next(_ids), "date": int(NOW - ago),
               "chat": {"id": chat, "type": "supergroup", "title": title or {G1: T1, G2: T2}[chat]},
               "from": {"id": abs(hash(who)) % 10 ** 6, "is_bot": False, "first_name": who}, "text": text}
    if reply:
        message["reply_to_message"] = {"message_id": reply}
    return message


def day_of(ago):
    return datetime.fromtimestamp(NOW - ago, TZ).strftime("%Y-%m-%d")


def events_json(*events):
    return "```json\n" + json.dumps({"events": list(events)}, ensure_ascii=False) + "\n```"


def ev(kind, title, src, **extra):
    return {"type": kind, "title": title, "detail": extra.pop("detail", ""), "owner": None,
            "requested_by": None, "status": None, "due": None, "severity": "medium", "src": src, **extra}


@pytest.fixture
def world(tmp_path):
    return make_world(tmp_path)


def make_world(tmp_path, *, roles=("USER",), logins=("a@b.uz",), groups=(G1, G2)):
    tg = BriefTelegram()
    store = GroupStore(tmp_path / "telegram" / "groups.db")
    writer = ScriptWriter()
    clock = [NOW]
    allowed = set(groups)
    names = set(logins)
    engine = BriefEngine(store, writer, groups=lambda: frozenset(allowed), clock=lambda: clock[0])
    service = BriefService(tg, engine, groups=lambda: frozenset(allowed), logins=lambda: frozenset(names),
                           inline=True, clock=lambda: clock[0])
    backend = FakeBackend()
    directory = Directory(_stored(roles=roles))
    links = LinkStore(tmp_path / "links.json")
    bot = VeneraBot(tg, links, users=lambda: directory, backend=backend, webapp_url=WEBAPP, inline=True,
                    typing_every=None, briefs=service)
    bot.username = BOT_NAME
    links.link(TG_ID, 1)
    return SimpleNamespace(tg=tg, store=store, writer=writer, clock=clock, engine=engine, service=service,
                           backend=backend, bot=bot, allowed=allowed, logins=names)


def seed(w):
    """2 guruh, 3 kun: muammo, vazifa, qaror, o'tgan muddat, hal bo'lgan muammo."""
    a1 = msg(G1, "LLM serverda xotira 92%, logsni tozalash kerak", 2 * 86400, who="Alisher")
    a2 = msg(G1, "Yusufxon, kredit qoldig'i hisobini 10.10 gacha tuzating", 2 * 86400 - 600, who="Bunyod")
    a3 = msg(G1, "Logs tozalandi, xotira 40%", 86400, who="Alisher")
    b1 = msg(G2, "Mijoz API dan 500 xato, integratsiya to'xtadi", 3 * 3600, who="Sardor")
    b2 = msg(G2, "Kamola, SSH kalitlarni bugun soat 12:00 gacha yangilang", 5 * 3600, who="Sardor")
    b3 = msg(G2, "Sentyabr ma'lumotlarini o'chiramiz. Kelishdik", 4 * 3600, who="Sardor")
    for m in (a1, a2, a3, b1, b2, b3):
        w.store.add(m)
    w.writer.days[(T1, day_of(2 * 86400))] = events_json(
        ev("problem", "LLM server xotirasi", [a1["message_id"]], status="open", severity="high"),
        ev("task", "Kredit qoldig'i hisobi", [a2["message_id"]], owner="Yusufxon", requested_by="Bunyod",
           status="in_progress", due="2026-10-10"))
    w.writer.days[(T1, day_of(86400))] = events_json(
        ev("status_change", "LLM server xotirasi", [a3["message_id"]], status="done", owner="Alisher"))
    w.writer.days[(T2, day_of(3 * 3600))] = events_json(
        ev("problem", "Mijoz API xatosi", [b1["message_id"]], status="open", severity="high"),
        ev("task", "SSH kalitlarini yangilash", [b2["message_id"]], owner="Kamola", status="open",
           due="2026-10-08 12:00"),
        ev("decision", "Sentyabr ma'lumotlarini o'chirish", [b3["message_id"]], requested_by="Sardor"))
    return SimpleNamespace(a1=a1, a2=a2, a3=a3, b1=b1, b2=b2, b3=b3)


def last_text(w):
    return w.tg.sent()[-1]["text"]


def buttons(markup):
    return [b for row in (markup or {}).get("inline_keyboard", []) for b in row]


# --- javobni o'qish va tekshirish -----------------------------------------------------------------


def test_json_chegara_bilan_va_kesilgan():
    assert parse_events('```json\n{"events": [{"type": "task"}]}\n```') == [{"type": "task"}]
    assert parse_events('{"events": []}') == []
    cut = '{"events": [{"type": "task", "title": "A"}, {"type": "problem", "title": "B"}, {"type": "ri'
    assert [e["title"] for e in parse_events(cut)] == ["A", "B"]
    assert parse_events("Kechirasiz, bugun hodisa yo'q") is None
    assert parse_events('{"events": [{"type": "ta') is None


def _rows(*items):
    return {i: Row(message_id=i, thread_id=None, date=int(NOW) - 100 + i, from_id=1, from_name=name,
                   username=None, text=text, reply_to=None) for i, name, text in items}


def test_tekshiruv_manba_ism_soat_va_qiymatlar():
    rows = _rows((1, "Bunyod", "Yusufxon, hisobni juma gacha tuzating, demo soat 11:00 da"),
                 (2, "Dilnoza", "telefonim +998 90 123 45 67"))
    blob = " ".join(f"{r.from_name} {r.text}" for r in rows.values()).lower()
    raw = [
        {"type": "task", "title": "Hisob", "owner": "Yusufxon", "requested_by": "Toshmat", "src": [1, 99],
         "due": "2026-10-10 23:59", "status": "doing", "severity": "urgent"},
        {"type": "deadline", "title": "Demo", "src": ["#1"], "due": "2026-10-09 11:00"},
        {"type": "gossip", "title": "X", "src": [1]},
        {"type": "risk", "title": "Y", "src": [42]},
        {"type": "problem", "title": "Aloqa", "detail": "telefon +998 90 123 45 67", "src": [2], "due": "ertaga"},
    ]
    out = validate_events(raw, rows, blob)
    assert [e["title"] for e in out] == ["Hisob", "Demo", "Aloqa"]       # tur yoki manba yo'q - tashlandi
    task, demo, problem = out
    assert task["src"] == [1] and task["owner"] == "Yusufxon"
    assert task["requested_by"] is None                                  # yozishmada yo'q ism
    assert task["due"] == "2026-10-10"                                   # 23:59 aytilmagan - soat yo'q
    assert task["status"] is None and task["severity"] == "medium"
    assert demo["due"] == "2026-10-09 11:00"                             # soat xabarda bor
    assert problem["due"] is None and "<telefon>" in problem["detail"]
    assert task["at"] == rows[1].date


# --- davr ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("code, label", [("24h", "oxirgi 24 soat"), ("7d", "oxirgi 7 kun"), ("td", "bugun"),
                                         ("90d", "oxirgi 90 kun"), ("c60d", "oxirgi 60 kun"),
                                         ("yd", "kecha"), ("tw", "bu hafta"), ("tm", "bu oy"),
                                         ("c3d", "oxirgi 3 kun"), ("c12h", "oxirgi 12 soat")])
def test_davr_kodlari(code, label):
    assert period_for(code, NOW).label == label


@pytest.mark.parametrize("code", ["c91d", "c0d", "c9999h", "xx", "c3w"])
def test_davr_kodi_notogri(code):
    assert period_for(code, NOW) is None


def test_ozi_yozgan_davr_kodga():
    for text, code in (("3 kun", "c3d"), ("2 hafta", "c14d"), ("bu oy", "tm"), ("12 soat", "c12h"),
                       ("kecha", "yd")):
        period = parse_period(text, "summary", NOW, max_days=31, strict=True)
        assert code_for(period) == code and period_for(code, NOW) is not None
    assert parse_period("ta'tilim qancha?", "summary", NOW, strict=True) is None
    assert parse_period("ta'tilim qancha?", "summary", NOW).label == "oxirgi 24 soat"   # eski xulq


# --- ombor ----------------------------------------------------------------------------------------------


def test_ombor_nomlar_belgilar_va_tozalash(world):
    w = world
    first = msg(G1, "salom", 3600)
    w.store.add(first)
    w.store.add({**msg(G1, "", 60, title="AI team (yangi)"), "sticker": {}})   # matnsiz - nom baribir
    assert w.store.titles([G1, G2]) == {G1: "AI team (yangi)"}
    day = day_of(3600)
    before = w.store.day_markers(G1, NOW - 86400 * 2, NOW)
    w.store.edit({**first, "text": "salom!", "edit_date": int(NOW)})
    after = w.store.day_markers(G1, NOW - 86400 * 2, NOW)
    assert before[day] != after[day] and before[day].startswith("1:")
    assert w.store.count_between(G1, NOW - 7200, NOW) == 1
    w.store.put_events(G1, "2020-01-01", marker="1:1:0", version="x", status="ok", events=[])
    w.store.purge()
    assert w.store.get_events(G1, ["2020-01-01"]) == {}


def test_eski_v1_ombor_yangilanadi(tmp_path):
    path = tmp_path / "groups.db"
    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE messages (chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,"
                       " thread_id INTEGER, date INTEGER NOT NULL, from_id INTEGER, from_name TEXT NOT NULL"
                       " DEFAULT '', username TEXT, text TEXT NOT NULL, reply_to INTEGER, edited_at INTEGER,"
                       " PRIMARY KEY (chat_id, message_id)); PRAGMA user_version = 1;")
    conn.execute("INSERT INTO messages (chat_id, message_id, date, text) VALUES (?, 1, ?, 'eski')", (G1, int(NOW)))
    conn.commit()
    conn.close()
    store = GroupStore(path)
    assert store.count() == 1 and store.titles([G1]) == {}
    store.put_events(G1, "2026-10-08", marker="1:1:0", version="v", status="ok", events=[{"a": 1}])
    assert store.get_events(G1, ["2026-10-08"])["2026-10-08"]["events"] == [{"a": 1}]


# --- dvigatel: kesh, xato, fon -----------------------------------------------------------------------------


def test_kesh_takror_brif_modelga_bormaydi(world):
    w = world
    seed(w)
    period = period_for("7d", NOW)
    first = w.engine.brief([(G1, T1), (G2, T2)], period, all_mode=True)
    calls = len(w.writer.extracts())
    assert calls == 3 and first.items == 5
    w.engine.brief([(G1, T1), (G2, T2)], period, all_mode=True)
    assert len(w.writer.extracts()) == calls
    # Ajratish JSON so'raydi (Ollama `format`).
    assert all(c[2]["format"] == "json" for c in w.writer.extracts())


def test_bugun_yangi_xabar_va_otgan_kun_tahriri(world):
    w = world
    s = seed(w)
    period = period_for("7d", NOW)
    w.engine.brief([(G1, T1), (G2, T2)], period, all_mode=True)
    base = len(w.writer.extracts())
    w.store.add(msg(G2, "yangi gap", 60))                    # bugun, lekin kesh hali yangi
    w.engine.brief([(G1, T1), (G2, T2)], period, all_mode=True)
    assert len(w.writer.extracts()) == base
    w.clock[0] += briefs_mod.TODAY_FRESH + 1                 # 10 daqiqadan keyin - faqat bugun
    w.engine.brief([(G1, T1), (G2, T2)], period_for("7d", w.clock[0]), all_mode=True)
    days = [re.search(r"Kun: (\S+)", c[1]).group(1) for c in w.writer.extracts()[base:]]
    assert days == [day_of(0)]
    w.store.edit({**s.a1, "text": "LLM serverda xotira 95%", "edit_date": int(NOW)})   # o'tgan kun tahriri
    w.engine.brief([(G1, T1), (G2, T2)], period_for("7d", w.clock[0]), all_mode=True)
    days = [re.search(r"Kun: (\S+)", c[1]).group(1) for c in w.writer.extracts()[base + 1:]]
    assert days == [day_of(2 * 86400)]


def test_yiqilgan_kun_qayta_urinish_va_kutish(world):
    w = world
    s = seed(w)
    day = day_of(3 * 3600)
    w.writer.days[(T2, day)] = ["afsuski bugun javob yo'q", "yana yo'q"]   # 2 marta JSON emas
    period = period_for("24h", NOW)
    brief = w.engine.brief([(G2, T2)], period, all_mode=False)
    assert "1 ta kun hali tahlil qilinmagan" in brief.parts[0]
    temps = [c[2]["temperature"] for c in w.writer.extracts()]
    assert temps == [0.2, 0.0]                                            # bir marta qayta, 0 haroratda
    w.engine.brief([(G2, T2)], period, all_mode=False)
    assert len(w.writer.extracts()) == 2                                  # 30 daqiqa kutiladi
    w.clock[0] += briefs_mod.FAIL_BACKOFF + 1
    w.writer.days[(T2, day)] = events_json(ev("problem", "Mijoz API xatosi", [s.b1["message_id"]]))
    brief = w.engine.brief([(G2, T2)], period_for("24h", w.clock[0]), all_mode=False)
    assert "tahlil qilinmagan" not in brief.parts[0] and "Mijoz API xatosi" in brief.parts[0]


def test_fon_tayyorlash_ozgarmagan_kunni_otkazadi_va_429_da_toxtaydi(world):
    w = world
    seed(w)
    assert w.engine.prewarm_once() == 3
    assert w.engine.prewarm_once() == 0
    w.store.add(msg(G1, "yangi", 60))
    w.store.add(msg(G2, "yana yangi", 30))
    w.clock[0] += briefs_mod.PREWARM_FRESH + 1
    # Guruhlar id tartibida: G2 (-1002...) birinchi. 429 - aylanish to'xtaydi, G1 ga o'tilmaydi.
    w.writer.days[(T2, day_of(0))] = OllamaError("Ollama HTTP 429")
    assert w.engine.prewarm_once() == 0
    assert [re.search(r"Guruh: (.*)", c[1]).group(1) for c in w.writer.extracts()[3:]] == [T2]


def test_chegara_eng_yangi_kunlar(world):
    w = world
    for back in range(5):
        w.store.add(msg(G1, f"kun {back}", back * 86400 + 60))
    _, missing, calls = w.engine.ensure(G1, T1, period_for("7d", NOW), budget=2)
    days = [re.search(r"Kun: (\S+)", c[1]).group(1) for c in w.writer.extracts()]
    assert calls == 2 and missing == 3 and days == [day_of(86400 + 60), day_of(60)]   # eskidan yangiga


def test_keyingi_kun_oldingi_ochiq_ishlarni_koradi_va_birlashadi(world):
    w = world
    seed(w)
    brief = w.engine.brief([(G1, T1)], period_for("7d", NOW), all_mode=False)
    second = [c[1] for c in w.writer.extracts() if f"Kun: {day_of(86400)}" in c[1]][0]
    assert "OCHIQ ishlar" in second and "- LLM server xotirasi (problem, open)" in second
    text = brief.parts[0]
    assert "🟢 <b>Bajarildi</b>\n• LLM server xotirasi" in text and "Diqqat" not in text


# --- brif ko'rinishi ----------------------------------------------------------------------------------------


def test_barcha_guruhlar_brifi(world):
    w = world
    seed(w)
    brief = w.engine.brief([(G1, T1), (G2, T2)], period_for("7d", NOW), all_mode=True)
    text = brief.parts[0]
    assert text.startswith("📊 <b>Rahbariyat brifi — Barcha guruhlar</b> · oxirgi 7 kun\n"
                           "<i>2 ta guruh · 6 ta xabar · 5 ta hodisa</i>")
    assert "⚡ <b>Asosiy</b>\n• Asosiy: API xatosi hal bo'lmagan\n• Qaror qabul qilindi" in text
    attention = text.split("🔴 <b>Diqqat talab qiladi</b>\n")[1].split("\n\n")[0]
    assert "• Mijoz API xatosi · <i>Kredit loyihasi</i>" in attention
    # Muddati o'tgan vazifa (12:00, hozir 15:00) - faktga tayangan ibora.
    assert "SSH kalitlarini yangilash\n  🔴 muddat o'tdi (08.10 12:00) — bajarilgani haqida xabar yo'q" in attention
    assert "✅ <b>Qarorlar</b>\n• Sentyabr ma'lumotlarini o'chirish · <i>Kredit loyihasi</i>" in text
    assert "📋 <b>Vazifalar</b>\n\n👤 <b>Yusufxon</b>\n• Kredit qoldig'i hisobi · 📅 10.10 · 🟡 jarayonda" in text
    assert f"🟢 <b>Bajarildi</b>\n• LLM server xotirasi · {day_of(86400)[8:]}.{day_of(86400)[5:7]} · <i>AI team</i>" in text
    assert "📁 <b>Guruhlar</b>\n• Kredit loyihasi — 3 xabar · 🔴 2\n• AI team — 3 xabar · 🟡 1 · 🟢 1" in text
    assert [t for _, t in brief.drill] == [T2, T1]
    assert all(len(p) <= 4000 for p in brief.parts)


def test_bitta_guruh_teglarsiz_va_sarlavha_ixtiyoriy(world):
    w = world
    seed(w)
    w.writer.headline = OllamaError("Ollama HTTP 500")
    brief = w.engine.brief([(G2, T2)], period_for("24h", NOW), all_mode=False)
    text = brief.parts[0]
    assert text.startswith("📊 <b>Rahbariyat brifi — Kredit loyihasi</b> · oxirgi 24 soat\n"
                           "<i>3 ta xabar · 3 ta hodisa</i>")
    assert "<i>Kredit loyihasi</i>" not in text and "📁" not in text and "⚡" not in text
    assert brief.drill == []


def test_render_mas_ul_yoq_ortiqcha_va_html():
    period = Period(NOW - 86400, NOW, "oxirgi 24 soat")
    items = [{"type": "task", "title": f"Ish <b>{i}</b>", "detail": "", "owner": None, "requested_by": None,
              "status": "open", "due": None, "severity": "low", "src": [1], "at": NOW - i, "group": G1}
             for i in range(8)]
    blocks = render_brief(items, [GroupStats(G1, T1, 8)], period=period, now=NOW, all_mode=False,
                          scope_title=T1, headline=[], missing=0)
    tasks = [b for b in blocks if b.startswith("📋")][0]
    assert "👤 <b>Mas'ul belgilanmagan</b>" in tasks and "Ish &lt;b&gt;0&lt;/b&gt;" in tasks
    assert tasks.endswith("<i>… yana 2 ta</i>")
    empty = render_brief([], [GroupStats(G1, T1, 4)], period=period, now=NOW, all_mode=False, scope_title=T1,
                         headline=[], missing=0)
    assert "Bu davrda muhim hodisa topilmadi." in empty


def test_birlashtirish_holat_va_muddat():
    first = {"type": "task", "title": "Kredit qoldig'i hisobi", "detail": "boshlandi", "owner": "Yusufxon",
             "requested_by": None, "status": "in_progress", "due": "2026-10-10", "severity": "medium",
             "src": [1], "at": 1, "group": G1}
    later = {**first, "type": "status_change", "title": "Kredit qoldig‘i  hisobi!", "status": "done",
             "due": None, "detail": "tugadi", "at": 5}
    other = {**first, "group": G2}
    merged = merge([later, first, other])
    assert len(merged) == 2
    one = [m for m in merged if m["group"] == G1][0]
    assert (one["type"], one["status"], one["due"], one["detail"], one["first_at"]) == \
        ("task", "done", "2026-10-10", "tugadi", 1)


# --- bot: kirish, menyu, tugmalar ---------------------------------------------------------------------------


def test_ruxsatsiz_odam_hech_narsa_ko_rmaydi(tmp_path):
    w = make_world(tmp_path, logins=())
    w.bot.handle_update(text_update("/brif"))
    assert last_text(w) == _UNKNOWN
    w.bot.handle_update(text_update("/start"))
    assert all(kw["reply_markup"] != REPLY_KEYBOARD for kw in w.tg.sent())
    w.bot.handle_update(text_update(BTN_ALL))                 # eskirgan klaviatura
    assert last_text(w) == _CLOSED and w.tg.sent()[-1]["reply_markup"] == REMOVE_KEYBOARD
    w.bot.handle_update(press("b:p:all:7d"))
    assert w.tg.sent("answer_callback")[-1]["text"] == _CLOSED and w.writer.calls == []
    w.bot.handle_update(text_update("ta'tilim necha kun?"))
    assert w.backend.questions and w.backend.questions[-1][0] == "ta'tilim necha kun?"


def test_admin_va_login_ruxsati(tmp_path):
    admin = make_world(tmp_path / "a", roles=("ADMIN",), logins=())
    admin.bot.handle_update(text_update("/start"))
    assert admin.tg.sent()[-1]["reply_markup"] == REPLY_KEYBOARD          # welcome dan keyin - ikkinchi xabar
    other = make_world(tmp_path / "b", logins=("boshqa@b.uz",))
    other.bot.handle_update(text_update("/brif"))
    assert last_text(other) == _UNKNOWN


def test_tugma_menyu_ochadi_hr_ga_ketmaydi(world):
    w = world
    w.store.add(msg(G1, "salom", 60))
    w.bot.handle_update(text_update(BTN_ALL))
    sent = w.tg.sent()[-1]
    assert "Barcha guruhlar" in sent["text"] and "davrni tanlang" in sent["text"]
    assert [b["text"] for b in buttons(sent["reply_markup"])][:7] == ["24 soat", "7 kun", "30 kun", "90 kun",
                                                                         "Bugun", "Kecha", "Bu hafta"]
    w.bot.handle_update(text_update(BTN_ONE))
    groups = buttons(w.tg.sent()[-1]["reply_markup"])
    assert [b["text"] for b in groups][:2] == [T1, f"Guruh …{str(G2)[-4:]}"]   # nomi hali noma'lum
    assert w.backend.questions == []
    w.bot.handle_update(text_update("kecha nima bo'ldi?"))          # oddiy savol - HR yordamchisiga
    assert w.backend.questions[-1][0] == "kecha nima bo'ldi?"


def test_davr_tugmasi_brif_yuboradi(world):
    w = world
    seed(w)
    w.bot.handle_update(press("b:p:all:7d", message_id=500))
    order = [n for n, _ in w.tg.calls]
    assert order[0] == "answer_callback"                              # tugmaga darhol javob
    holder = [kw for n, kw in w.tg.calls if n == "edit_message_text"][0]
    assert holder["message_id"] == 500 and "tayyorlanmoqda" in holder["text"]
    assert ("delete_message", {"chat_id": TG_ID, "message_id": 500}) in w.tg.calls
    brief = w.tg.sent()[-1]
    assert brief["text"].startswith("📊 <b>Rahbariyat brifi — Barcha guruhlar</b>")
    data = [b["callback_data"] for b in buttons(brief["reply_markup"])]
    assert data == [f"b:p:{G2}:7d:n", f"b:p:{G1}:7d:n", "b:s:all:n", "b:m:n"]
    # Brif ostidagi tugma brifni o'zgartirmaydi - yangi xabar.
    w.bot.handle_update(press(f"b:p:{G1}:7d:n", message_id=777))
    assert all(kw["message_id"] != 777 for n, kw in w.tg.calls if n == "edit_message_text")
    assert w.tg.sent()[-1]["text"].startswith("📊 <b>Rahbariyat brifi — AI team</b>")


def test_soxta_tugma_va_uzunlik(world):
    w = world
    seed(w)
    w.bot.handle_update(press("b:p:-100999:7d"))                   # ro'yxatda yo'q guruh
    w.bot.handle_update(press("b:p:all:c99d"))                      # juda uzun davr
    w.bot.handle_update(press("b:z"))
    toasts = [kw["text"] for kw in w.tg.sent("answer_callback")]
    assert toasts == ["Tugma eskirgan"] * 3 and w.writer.calls == []
    for label in (BTN_ALL, BTN_ONE):
        w.bot.handle_update(text_update(label))
    w.bot.handle_update(press("b:p:all:30d"))
    for kw in w.tg.sent() + [kw for n, kw in w.tg.calls if n == "edit_message_text"]:
        for b in buttons(kw.get("reply_markup")):
            assert len(b["callback_data"].encode()) <= 64


def test_boshqa_davr_faqat_javob_bilan(world):
    w = world
    seed(w)
    w.bot.handle_update(press("b:c:all"))
    prompt = w.tg.sent()[-1]
    assert prompt["reply_markup"]["force_reply"] is True
    w.bot.handle_update(text_update("3 kunlik ta'tilim qancha?", message_id=11))   # javob emas - HR
    assert w.backend.questions[-1][0] == "3 kunlik ta'tilim qancha?"
    reply = text_update("bilmadim", message_id=12)
    reply["message"]["reply_to_message"] = {"message_id": prompt["message_id"]}
    w.bot.handle_update(reply)
    assert last_text(w).startswith(_NOT_PERIOD)
    again = w.tg.sent()[-1]["message_id"]
    good = text_update("3 kun", message_id=13)
    good["message"]["reply_to_message"] = {"message_id": again}
    w.bot.handle_update(good)
    assert "· oxirgi 3 kun" in w.tg.sent()[-1]["text"]
    assert w.tg.sent()[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"].endswith(":c3d:n")
    assert len(w.backend.questions) == 1


def test_boshqa_davr_muddati_tugaydi(world):
    w = world
    w.bot.handle_update(press("b:c:all"))
    prompt = w.tg.sent()[-1]["message_id"]
    w.clock[0] += briefs_mod.PROMPT_TTL + 1
    late = text_update("3 kun", message_id=14)
    late["message"]["reply_to_message"] = {"message_id": prompt}
    w.bot.handle_update(late)
    assert w.backend.questions[-1][0] == "3 kun"


def test_brif_buyrugi_davr_bilan(world):
    w = world
    seed(w)
    w.bot.handle_update(text_update("/brif 7 kun"))
    assert w.tg.sent()[-1]["text"].startswith("📊 <b>Rahbariyat brifi — Barcha guruhlar</b> · oxirgi 7 kun")
    w.bot.handle_update(text_update("/brif"))
    assert w.tg.sent()[-2]["reply_markup"] == REPLY_KEYBOARD and "Qaysi guruhlar" in last_text(w)


def test_band_va_chegara(world):
    w = world
    seed(w)
    w.service._inflight.add(1)
    w.bot.handle_update(press("b:p:all:7d"))
    assert w.tg.sent("answer_callback")[-1]["text"] == briefs_mod._BUSY
    w.service._inflight.clear()
    for _ in range(briefs_mod.USER_LIMIT[0]):
        w.bot.handle_update(press("b:p:all:7d"))
    w.bot.handle_update(press("b:p:all:7d"))
    last = w.tg.sent("answer_callback")[-1]
    assert last["text"] == briefs_mod._TOO_MANY and last["alert"] is True


def test_guruhlar_sahifalari(tmp_path):
    ids = [-1000000000000 - i for i in range(10)]
    w = make_world(tmp_path, groups=ids)
    for i, gid in enumerate(ids):
        w.store.add(msg(gid, "salom", 60, title=f"Guruh {i:02d}"))
    w.bot.handle_update(text_update(BTN_ONE))
    first = buttons(w.tg.sent()[-1]["reply_markup"])
    assert [b["text"] for b in first][:8] == [f"Guruh {i:02d}" for i in range(8)]
    assert [b["text"] for b in first][8:11] == ["‹", "1/2", "›"]
    w.bot.handle_update(press("b:g:1", message_id=600))
    page = [kw for n, kw in w.tg.calls if n == "edit_message_text"][-1]
    assert [b["text"] for b in buttons(page["reply_markup"])][:2] == ["Guruh 08", "Guruh 09"]


def test_mavjud_xususiyatlar_ozgarmadi(world):
    """Oddiy savol, /start, /help, boshqa tugmalar - brifsiz botdagidek."""
    w = world
    w.bot.handle_update(text_update("salom"))
    assert w.backend.questions[-1][0] == "salom"
    w.bot.handle_update(press("r:" + "a" * 32))
    assert w.writer.calls == []


# --- forward qilingan tarix: ASL sanasi bilan ---------------------------------------------------------


def fwd(chat, text, ago, original, *, who="Sardor", author="Yusufxon"):
    message = msg(chat, text, ago, who=who)
    message["forward_origin"] = {"type": "user", "date": int(original), "sender_user": {"id": 7, "first_name": author}}
    return message


def test_forward_asl_vaqti_saqlanadi_va_sanaladi(world):
    w = world
    july = datetime(2026, 7, 15, 10, 0, tzinfo=TZ).timestamp()
    w.store.add(fwd(G1, "Dashboard ishlamayapti", 600, july))
    w.store.add(msg(G1, "bugungi gap", 300))
    [old, new] = w.store.window(G1, NOW - 3600, NOW)
    assert old.orig_date == int(july) and old.when == int(july) and new.orig_date is None
    assert w.store.count_between(G1, NOW - 7 * 86400, NOW) == 1          # forward - iyulda
    assert w.store.count_between(G1, NOW - 90 * 86400, NOW) == 2


def test_eski_ombor_forward_sanasi_belgidan_tiklanadi(tmp_path):
    path = tmp_path / "groups.db"
    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE messages (chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,"
                       " thread_id INTEGER, date INTEGER NOT NULL, from_id INTEGER, from_name TEXT NOT NULL"
                       " DEFAULT '', username TEXT, text TEXT NOT NULL, reply_to INTEGER, edited_at INTEGER,"
                       " PRIMARY KEY (chat_id, message_id)); PRAGMA user_version = 2;")
    posted = int(datetime(2026, 10, 7, 12, 0, tzinfo=TZ).timestamp())
    january = int(datetime(2027, 1, 5, 9, 0, tzinfo=TZ).timestamp())
    for mid, date, text in ((1, posted, "[forward: Yusufxon Mamadjanov, 15.07 10:00] Dashboard xatosi"),
                            (2, january, "[forward: Ali, 20.12 09:30] yil oxiri"),
                            (3, posted, "[forward qilingan xabar]"),
                            (4, posted, "oddiy xabar")):
        conn.execute("INSERT INTO messages (chat_id, message_id, date, text) VALUES (?, ?, ?, ?)",
                     (G1, mid, date, text))
    conn.commit()
    conn.close()
    store = GroupStore(path)
    rows = {r.message_id: r for r in store.window(G1, 0, january + 1)}
    assert rows[1].orig_date == int(datetime(2026, 7, 15, 10, 0, tzinfo=TZ).timestamp())
    assert rows[2].orig_date == int(datetime(2026, 12, 20, 9, 30, tzinfo=TZ).timestamp())   # o'tgan yil
    assert rows[3].orig_date is None and rows[4].orig_date is None
    check = sqlite3.connect(path)
    assert check.execute("PRAGMA user_version").fetchone()[0] == 3
    check.close()


def test_forward_tarix_asl_sanasida_korinadi(world):
    w = world
    july = datetime(2026, 7, 15, 10, 0, tzinfo=TZ).timestamp()
    old = fwd(G2, "Dashboard ishlamayapti, ertaga tuzatamiz", 600, july)
    w.store.add(old)
    w.writer.days[(T2, day_of(600))] = events_json(
        ev("problem", "Dashboard ishlamasligi", [old["message_id"]], status="open", severity="high"))
    week = w.engine.brief([(G2, T2)], period_for("7d", NOW), all_mode=False)
    assert "Bu davrda muhim hodisa topilmadi." in week.parts[0] and "<i>0 ta xabar" in week.parts[0]
    prompt = w.writer.extracts()[0][1]
    assert "[15.07 10:00] Sardor: [forward: Yusufxon, 15.07 10:00] Dashboard" in prompt
    season = w.engine.brief([(G2, T2)], period_for("90d", NOW), all_mode=False)
    assert "Dashboard ishlamasligi" in season.parts[0] and "<i>1 ta xabar · 1 ta hodisa</i>" in season.parts[0]
    assert len(w.writer.extracts()) == 1                                  # o'sha kun - keshdan
