"""Rahbariyat brifi - guruh turiga qarab karta (`app/bot/brief_cards.py`) va
support / loyiha ajratish (`app/bot/briefs.py`)."""

from __future__ import annotations

import json
import re

from datetime import datetime

import pytest

from app.bot import brief_cards as cards
from app.bot.briefs import (PROMPT_VERSION, SUPPORT_VERSION, BriefEngine, merge, period_for, validate_events)
from app.bot.groups import TZ, uz_date
from app.services.integrations.ollama import OllamaError
from app.services.tg_groups import Row
from tests.test_bot_briefs import (G1, G2, NOW, T1, T2, ScriptWriter, day_of, ev, events_json, make_world, msg,
                                   seed)
from tests.test_bot_ux import all_buttons, press


def at(hour, minute=0, day=8):
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ).timestamp()


def row(mid, when, text="x", who="Aziz"):
    return Row(message_id=mid, thread_id=None, date=int(when), from_id=1, from_name=who, username=None, text=text,
               reply_to=None)


def support_world(tmp_path, gid=G2):
    w = make_world(tmp_path)
    kinds = {gid: "support"}
    w.kinds = kinds
    w.engine._kind_of = lambda chat_id: kinds.get(chat_id)
    return w


def seed_support(w, gid=G2, title=T2):
    """Bugun (8-oktyabr): bug ko'tarildi 10:00, tuzatildi 12:15; savol 12:00 - javob 12:25; taklif ochiq."""
    a = msg(gid, "Pul o'tkazish ishlamayapti", NOW - at(10), who="Aziz")
    b = msg(gid, "Tuzatildi, tekshirib ko'ring", NOW - at(12, 15), who="Dilshod")
    c = msg(gid, "Limitni qanday oshirsa bo'ladi?", NOW - at(12), who="Kamola")
    d = msg(gid, "Sozlamalar - Limit bo'limidan", NOW - at(12, 25), who="Sardor")
    e = msg(gid, "Tungi rejim qo'shilsa yaxshi bo'lardi", NOW - at(14), who="Bekzod")
    for m in (a, b, c, d, e):
        w.store.add(m)
    w.writer.days[(title, day_of(NOW - at(10)))] = events_json(
        ev("problem", "Pul o'tkazish xatosi", [a["message_id"]], category="bug", requested_by="Aziz",
           status="open", severity="high"),
        ev("status_change", "Pul o'tkazish xatosi", [b["message_id"]], category="bug", owner="Dilshod",
           status="done"),
        ev("problem", "Limitni oshirish", [c["message_id"], d["message_id"]], category="question",
           requested_by="Kamola", owner="Sardor", status="done"),
        ev("problem", "Tungi rejim", [e["message_id"]], category="feature", requested_by="Bekzod", status="open",
           severity="low"))
    return a, b, c, d, e


# --- ma'lumot: boshlanish vaqti, kategoriya, birlashtirish ---------------------------------------


def test_hodisa_boshlanishi_va_kategoriyasi():
    rows = {1: row(1, at(10)), 2: row(2, at(12, 15), who="Dilshod")}
    raw = [{"type": "problem", "title": "Xato", "category": "bug", "src": [1, 2], "requested_by": "Aziz"},
           {"type": "problem", "title": "Boshqa", "category": "spam", "src": [1]}]
    [first, second] = validate_events(raw, rows, "aziz dilshod x")
    assert first["start"] == int(at(10)) and first["at"] == int(at(12, 15)) and first["category"] == "bug"
    assert second["category"] is None


def test_birlashtirish_hal_vaqti_va_kotargan():
    events = [
        {**ev("problem", "Xato", [1], category="bug", requested_by="Aziz", status="open"), "start": at(10), "at": at(10)},
        {**ev("status_change", "Xato", [2], owner="Dilshod", status="done"), "start": at(12), "at": at(12, 15)},
    ]
    [item] = merge(events)
    assert item["start_at"] == at(10) and item["done_at"] == at(12, 15) and item["raised_by"] == "Aziz"
    assert item["category"] == "bug" and item["status"] == "done" and item["owner"] == "Dilshod"
    assert cards.resolution(item) == 2 * 3600 + 15 * 60
    # Qayta ochildi - yangi davra; hal bo'lgani o'chadi.
    reopened = merge(events + [{**ev("problem", "Xato", [3], requested_by="Bekzod", status="open"),
                                "start": at(15), "at": at(15)}])[0]
    assert reopened["start_at"] == at(15) and reopened["done_at"] is None and reopened["raised_by"] == "Bekzod"


def test_birlashtirish_eski_kesh_hodisalari():
    old = {**ev("task", "Hisobot", [1], status="open"), "at": at(9)}          # "start" yo'q
    [item] = merge([old])
    assert item["start_at"] == at(9) and item["first_at"] == at(9) and item.get("category") is None


def test_davomiylik_matni():
    assert cards.duration_text(30) == ""
    assert cards.duration_text(45 * 60) == "45 daqiqa"
    assert cards.duration_text(3 * 3600 + 20 * 60) == "3 soat 20 daqiqa"
    assert cards.duration_text(2 * 86400 + 4 * 3600) == "2 kun 4 soat"
    assert cards.duration_text(-5) == "" and cards.duration_text(None) == ""


# --- support ajratish: alohida yo'riqnoma va kesh versiyasi ---------------------------------------


def test_support_alohida_yoriqnoma_va_versiya(tmp_path):
    w = support_world(tmp_path)
    seed(w)
    w.engine.brief([(G1, T1), (G2, T2)], period_for("7d", NOW), all_mode=True)
    ops = {(re.search(r"Guruh: (.*)", user).group(1), op) for op, user, _ in w.writer.calls if op.startswith("brief_extract")}
    assert (T2, "brief_extract_support") in ops and (T1, "brief_extract") in ops
    assert (T2, "brief_extract") not in ops
    versions = {chat_id: {hit["version"] for hit in w.store.get_events(chat_id, [day_of(n * 86400) for n in range(4)]).values()}
                for chat_id in (G1, G2)}
    assert versions[G1] == {PROMPT_VERSION} and versions[G2] == {SUPPORT_VERSION}


def test_guruh_turi_ozgarsa_qayta_ajratiladi(tmp_path):
    w = support_world(tmp_path)
    seed(w)
    period = period_for("7d", NOW)
    w.engine.brief([(G2, T2)], period, all_mode=False)
    support_calls = len(w.writer.extracts()) + sum(1 for c in w.writer.calls if c[0] == "brief_extract_support")
    w.kinds[G2] = "project"
    w.engine.brief([(G2, T2)], period, all_mode=False)
    assert any(c[0] == "brief_extract" for c in w.writer.calls)
    before = len(w.writer.calls)
    w.engine.brief([(G2, T2)], period, all_mode=False)                      # endi keshdan
    assert [c for c in w.writer.calls[before:] if c[0].startswith("brief_extract")] == []
    assert support_calls >= 1


def test_loyiha_keshi_saqlanadi(tmp_path):
    w = make_world(tmp_path)
    seed(w)
    w.engine.brief([(G1, T1), (G2, T2)], period_for("7d", NOW), all_mode=True)
    before = len(w.writer.extracts())
    w.engine._kind_of = lambda chat_id: None                                  # registr bor, tur tanlanmagan
    w.engine.brief([(G1, T1), (G2, T2)], period_for("7d", NOW), all_mode=True)
    assert len(w.writer.extracts()) == before


def test_support_konteksti_kategoriya_bilan(tmp_path):
    w = support_world(tmp_path)
    seed_support(w)
    w.engine.brief([(G2, T2)], period_for("24h", NOW), all_mode=False)
    later = msg(G2, "Yana bitta savol", -86400 + 600, who="Kamola")          # ertasi kuni
    w.store.add(later)
    w.clock[0] = NOW + 86400
    w.engine.brief([(G2, T2)], period_for("24h", NOW + 86400), all_mode=False)
    prompt = [user for op, user, _ in w.writer.calls if op == "brief_extract_support"][-1]
    assert "HAL BO'LMAGAN murojaatlar" in prompt and "- Tungi rejim (feature" in prompt


# --- support kartasi ---------------------------------------------------------------------------


def test_support_karta_sonlar_va_vaqt(tmp_path):
    w = support_world(tmp_path)
    seed_support(w)
    brief = w.engine.brief([(G2, T2)], period_for("24h", NOW), all_mode=False, view="card")
    text = brief.parts[0]
    assert "🛠 Support" in text
    assert "1. Muammolar: <b>3</b>\n2. Yechildi: <b>2</b>\n3. Jarayonda: <b>1</b>" in text
    assert "🔴 Bug 1 · 🟡 Taklif 1 · ⚪ Savol 1" in text
    assert "1. 🟡 <b>Taklif</b> · Tungi rejim · 8-oktyabrdan beri" in text
    assert "Pul o'tkazish xatosi — Aziz xabar qildi · Dilshod hal qildi · 2 soat 15 daqiqa" in text
    assert "Limitni oshirish — Kamola so'radi · Sardor javob berdi · 25 daqiqa" in text
    assert [c for c in w.writer.calls if c[0] in ("brief_project", "brief_headline")] == []


def test_support_karta_nomalum_qiymatlar():
    now = at(15)
    items = [
        {**ev("status_change", "Faqat hal bo'ldi", [1], category="bug", status="done"), "at": at(11),
         "first_at": at(11), "start_at": None, "raised_by": None, "done_at": at(11), "group": G2},
        {**ev("problem", "Bir zumda", [2, 3], category="question", requested_by="Ali", status="done"), "at": at(12),
         "first_at": at(12), "start_at": at(12) - 20, "raised_by": "Ali", "done_at": at(12), "group": G2},
    ]
    view = cards.support_view(items)
    text = "\n".join(cards.render_support(view, head="H", now=now))
    assert "Faqat hal bo'ldi — hal qilindi 8-oktyabr" in text
    assert "Bir zumda — Ali so'radi · javob berildi 8-oktyabr" in text


def test_support_oldingi_kundan_davomiylik(tmp_path):
    w = support_world(tmp_path)
    old = msg(G2, "Login ishlamayapti", 3 * 86400, who="Aziz")
    fixed = msg(G2, "Login tuzatildi", 3600, who="Dilshod")
    w.store.add(old)
    w.store.add(fixed)
    w.writer.days[(T2, day_of(3 * 86400))] = events_json(
        ev("problem", "Login xatosi", [old["message_id"]], category="bug", requested_by="Aziz", status="open"))
    w.writer.days[(T2, day_of(3600))] = events_json(
        ev("status_change", "Login xatosi", [fixed["message_id"]], category="bug", owner="Dilshod", status="done"))
    w.engine.brief([(G2, T2)], period_for("7d", NOW), all_mode=False)          # kunlar keshlanadi
    calls = len(w.writer.calls)
    card = w.engine.brief([(G2, T2)], period_for("24h", NOW), all_mode=False, view="card").parts[0]
    assert "Login xatosi — Aziz xabar qildi · Dilshod hal qildi · 2 kun 23 soat" in card
    assert len(w.writer.calls) == calls


def test_support_guruhiga_crm_bormaydi(tmp_path):
    w = support_world(tmp_path)
    seed(w)
    seen = []

    def crm(items, titles):
        seen.extend(i["group"] for i in items)
        from app.bot.crm_status import CrmReport
        return CrmReport()

    w.engine.brief([(G2, T2)], period_for("7d", NOW), all_mode=False, crm=crm, view="card")
    assert seen == []
    w.engine.brief([(G1, T1), (G2, T2)], period_for("7d", NOW), all_mode=True, crm=crm, view="card")
    assert seen and set(seen) == {G1}


# --- loyiha kartasi ------------------------------------------------------------------------------


@pytest.mark.parametrize("events, status", [
    ([], "none"),
    ([ev("task", "Hisobot", [1], status="in_progress")], "green"),
    ([ev("task", "Hisobot", [1], status="in_progress", due="2026-10-07")], "orange"),
    ([ev("task", "Hisobot", [1], status="blocked")], "red"),
    ([ev("problem", "Server", [1], status="open", severity="high")], "red"),
    ([ev("risk", "Kechikish", [1], status="open")], "orange"),
])
def test_loyiha_holati(events, status):
    items = [{**e, "at": at(10), "first_at": at(10), "group": G1} for e in events]
    assert cards.project_view(items, at(15)).status == status


def test_loyiha_matni_qabul_qilinadi(tmp_path):
    w = make_world(tmp_path)
    seed(w)
    w.writer.project = json.dumps({"summary": "AI team loyihasi barqaror ketmoqda.",
                                   "done": "Tabriklayman! LLM server xotirasi muammosi hal qilindi.",
                                   "progress": "Yusufxon kredit qoldig'i hisobi ustida ishlamoqda.",
                                   "blockers": ""})
    card = w.engine.brief([(G1, T1)], period_for("7d", NOW), all_mode=False, view="card").parts[0]
    assert "<b>AI team loyihasi barqaror ketmoqda.</b>" in card
    assert "1. ✅ <b>Bajarildi</b>\nTabriklayman! LLM server xotirasi muammosi hal qilindi." in card
    assert "Yusufxon kredit qoldig'i hisobi ustida ishlamoqda.\n👤 Mas'ullar: Yusufxon" in card
    assert "3. 🟢 <b>Holati: Barqaror</b>\nBu loyiha uchun to'siqlar yo'q." in card
    [(op, user, opts)] = [c for c in w.writer.calls if c[0] == "brief_project"]
    assert "BAJARILDI (1):" in user and "JARAYONDA (1):" in user and "FAKTLAR-" in user and opts["format"] == "json"
    assert [c for c in w.writer.calls if c[0] == "brief_headline"] == []


def test_loyiha_matni_toqilgan_ism_va_raqam(tmp_path):
    w = make_world(tmp_path)
    seed(w)
    w.writer.project = json.dumps({"summary": "Jasur loyihani 5 haftada tugatadi.",
                                   "done": "LLM server xotirasi muammosi hal qilindi.",
                                   "progress": "Kredit qoldig'i hisobi 10-oktyabrgacha tayyor bo'ladi.",
                                   "blockers": "Yo'q"})
    card = w.engine.brief([(G1, T1)], period_for("7d", NOW), all_mode=False, view="card").parts[0]
    assert "Jasur" not in card and "5 haftada" not in card
    assert "<b>1 ta ish bajarildi, 1 tasi jarayonda; to'siq yo'q.</b>" in card       # zaxira gap
    assert "LLM server xotirasi muammosi hal qilindi." in card                         # qabul qilingan maydon
    assert "10-oktyabrgacha tayyor" in card


def test_loyiha_matni_yiqilsa_zaxira(tmp_path):
    w = make_world(tmp_path)
    seed(w)
    w.writer.project = OllamaError("down")
    card = w.engine.brief([(G2, T2)], period_for("7d", NOW), all_mode=False, view="card").parts[0]
    assert "3. 🔴 <b>Holati: To'siq bor</b>" in card
    assert "• Mijoz API xatosi" in card and "• SSH kalitlarini yangilash" in card
    assert "2 ta masala e'tibor talab qiladi." in card


def test_loyiha_toqiq_yoq_desa_qabul_qilinmaydi(tmp_path):
    w = make_world(tmp_path)
    seed(w)
    w.writer.project = json.dumps({"summary": "Loyiha barqaror, to'siq yo'q.", "done": "", "progress": "",
                                   "blockers": "To'siqlar yo'q."})
    card = w.engine.brief([(G2, T2)], period_for("7d", NOW), all_mode=False, view="card").parts[0]
    assert "barqaror, to'siq yo'q" not in card and "Holati: To'siq bor" in card


def test_loyiha_crm_dan_keyin(tmp_path):
    w = make_world(tmp_path)
    seed(w)
    from app.bot.crm_status import CrmChecker
    from tests.test_crm_status import USER, Agent, tasks

    agent = Agent(tasks({"n": 1, "found": True, "key": "OPS-7", "status": "Done", "updated": "2026-10-08"}))
    checker = CrmChecker(agent)
    card = w.engine.brief([(G2, T2)], period_for("7d", NOW), all_mode=False, view="card",
                          crm=lambda items, titles: checker.check(USER, items, titles)).parts[0]
    assert "🗂 CRM: 1/1 vazifa topildi" in card
    [user] = [u for op, u, _ in w.writer.calls if op == "brief_project"] or [""]
    assert "BAJARILDI (1):" in user and "SSH kalitlarini yangilash" in user.split("BAJARILDI")[1]


# --- barcha guruhlar --------------------------------------------------------------------------


def test_barcha_guruhlar_turlar_boyicha(tmp_path):
    w = support_world(tmp_path)
    seed(w)
    seed_support(w)
    brief = w.engine.brief([(G1, T1), (G2, T2)], period_for("7d", NOW), all_mode=True, view="card")
    text = "\n".join(brief.parts)
    assert text.startswith("📊 <b>Rahbariyat brifi — Barcha guruhlar</b>")
    assert "🛠 <b>Qo'llab-quvvatlash</b> · 1 ta guruh" in text
    assert "📁 <b>Loyihalar</b> · 1 ta" in text and "🟢 AI team — ✅ 1 · 🔄 1" in text
    assert "Muammolar: <b>3</b> · Yechildi: <b>2</b> · Jarayonda: <b>1</b>" in text
    assert "• Kredit loyihasi — 3 murojaat · ✅ 2 · 🔄 1" in text and "Ochiq buglar:" not in text
    assert [c for c in w.writer.calls if c[0] == "brief_project"] == []
    assert sum(1 for c in w.writer.calls if c[0] == "brief_headline") == 1
    assert brief.kinds == {G1: "project", G2: "support"}


def test_barcha_guruhlar_100_ta(tmp_path):
    lines = [cards.GroupLine(chat_id=-100 - n, title=f"Loyiha {n:03d} " + "x" * 30, kind="project", messages=n,
                             project=cards.project_view([], at(15))) for n in range(100)]
    lines += [cards.GroupLine(chat_id=-1000 - n, title=f"Support {n}", kind="support", messages=5,
                              support=cards.support_view([])) for n in range(20)]
    from app.bot import render
    parts = render.pack(cards.render_overview(lines, head="H", headline=[], now=at(15)))
    assert len(parts) <= 3 and all(len(p) <= 4000 for p in parts)
    assert "… yana 70 ta" in "\n".join(parts) and "… yana 5 ta guruh" in "\n".join(parts)
    assert len(cards.drill_order(lines, 8)) == 8


# --- tugmalar ----------------------------------------------------------------------------------


def test_karta_tugmalari_va_batafsil(tmp_path):
    w = make_world(tmp_path, roles=("ADMIN",))
    seed(w)
    w.bot.handle_update(press("b:p:all:7d", message_id=500))
    card = w.tg.sent()[-1]
    data = [b["callback_data"] for b in all_buttons(card["reply_markup"])]
    assert data == [f"b:p:{G2}:7d:n", f"b:p:{G1}:7d:n", "b:d:all:7d:n", "b:s:all:n", "b:m:n"]
    w.bot.handle_update(press("b:d:all:7d:n", message_id=900))
    detail = w.tg.sent()[-1]
    expected = w.engine.brief([(G1, T1), (G2, T2)], period_for("7d", NOW), all_mode=True)
    assert detail["text"] == expected.parts[-1]
    data = [b["callback_data"] for b in all_buttons(detail["reply_markup"])]
    assert data == [f"b:d:{G2}:7d:n", f"b:d:{G1}:7d:n", "b:s:all:n", "b:m:n"]


def test_soxta_batafsil_tugmasi(tmp_path):
    w = make_world(tmp_path, roles=("ADMIN",))
    seed(w)
    for data in ("b:d:-100999:7d", "b:d:all:c99d", "b:d:all"):
        w.bot.handle_update(press(data))
    toasts = [kw["text"] for kw in w.tg.sent("answer_callback")]
    assert toasts == ["Tugma eskirgan"] * 3


def test_support_holatida_crm_yozilmaydi(tmp_path):
    w = support_world(tmp_path)
    seed_support(w)
    w.service.crm = object()
    w.allowed.discard(G1)
    w.service._start_brief(555, type("U", (), {"actorId": 1})(), str(G2), "7d", cq_id=None, edit_id=None)
    holder = [kw for kw in w.tg.sent() if kw["chat_id"] == 555][0]["text"]
    assert "CRM" not in holder


def test_bitta_guruh_royxatida_tur_belgisi(tmp_path):
    from app.bot.briefs import BTN_ONE
    from tests.test_telegram_bot import text_update

    w = support_world(tmp_path)
    seed(w)
    w.bot.handle_update(text_update(BTN_ONE))
    names = [b["text"] for b in all_buttons(w.tg.sent()[-1]["reply_markup"]) if b["callback_data"].startswith("b:s:")]
    assert names == ["AI team", "🛠 Kredit loyihasi"]                       # tur tanlanmagan - belgisiz


def test_barcha_guruhlar_ochiq_bug_va_tugma_belgisi(tmp_path):
    w = support_world(tmp_path)
    seed(w)
    a = msg(G2, "Kartadan pul yechilmayapti", 3600, who="Aziz")
    w.store.add(a)
    w.writer.days[(T2, day_of(3600))] = events_json(
        ev("problem", "Karta xatosi", [a["message_id"]], category="bug", requested_by="Aziz", status="open",
           severity="high"))
    brief = w.engine.brief([(G1, T1), (G2, T2)], period_for("7d", NOW), all_mode=True, view="card")
    text = "\n".join(brief.parts)
    assert "Ochiq buglar:\n1. Karta xatosi · <i>Kredit loyihasi</i> · 8-oktyabrdan beri" in text
    assert brief.drill[0] == (G2, T2)                                        # ochiq high bug - birinchi


def test_barcha_guruhlar_bitta_chaqiruv_chegarasi(tmp_path, monkeypatch):
    from app.bot import briefs

    monkeypatch.setattr(briefs, "ON_DEMAND_CALLS", 2)
    w = make_world(tmp_path)
    seed(w)                                                                   # 3 kun: G1 - 2, G2 - 1
    brief = w.engine.brief([(G1, T1), (G2, T2)], period_for("7d", NOW), all_mode=True)
    assert len(w.writer.extracts()) == 2
    assert "1 ta kun hali tahlil qilinmagan" in brief.parts[0]

