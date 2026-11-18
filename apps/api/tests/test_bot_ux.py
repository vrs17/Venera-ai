"""Telegram bot UX: "⚑" (xabar berish), izohlar va "Hujjatni ochish",
ulanmagan odam, buyruqlar (`/beta` bilan), faqat shaxsiy chat, "Pro" yo'q.

Telegram ham, yuqoridagi xizmat ham SOXTA (`test_telegram_bot.py` dagilar) -
tarmoqqa chiqilmaydi. Savollar izi va shikoyatlar esa HAQIQIY xizmatdan
(`TurnRecorder`, `services/reports.py`) vaqtinchalik analitika omboriga
yoziladi (`conftest._isolated_analytics`) - veb chatdagi AYNI yo'l.
"""

from __future__ import annotations

import json
import re

import jwt
import pytest

from app.bot import render
from app.bot.runner import _BLOCKED, _GROUP_ONLY, _UNKNOWN, BOT_MODE, COMMANDS, Backend, VeneraBot
from app.core.config import settings
from app.core.security import hash_password
from app.schemas.auth import AuthUser
from app.schemas.reports import REASONS
from app.services import analytics, reports
from app.services.analytics import TurnRecorder, get_db
from app.services.identities import Identity
from app.services.integrations.telegram import TelegramError
from app.services.telegram_links import LinkStore
from app.services.users import StoredUser, UserStore
from tests.test_telegram_bot import TG_ID, FakeBackend, FakeTelegram, _frames, text_update

WEBAPP = "https://llm.brb-tech.uz/tg/"
BETA = "https://llm.brb-tech.uz/tg-beta/"
LEX = "https://lex.uz/docs/6257288#6260710"
BOT_NAME = "venera_test_bot"


class Directory:
    """`get_directory` o'rnida: `users.yaml` hisoblari va SSO hisoblari."""

    def __init__(self, *accounts) -> None:
        self.accounts = {a.actor_id: a for a in accounts}

    def by_actor_id(self, actor_id):
        return self.accounts.get(actor_id)


def _stored(actor_id=1, email="a@b.uz", roles=("USER",)):
    return StoredUser(actor_id=actor_id, email=email, full_name="Ali Valiyev",
                      password_hash=hash_password("x"), roles=list(roles))


@pytest.fixture(autouse=True)
def _fresh_limiter():
    reports.limiter.reset()
    yield
    reports.limiter.reset()


@pytest.fixture(autouse=True)
def _beta_defaults(monkeypatch):
    # `.env` dagi qiymat test natijasini o'zgartirmasin.
    monkeypatch.setattr(settings, "miniapp_beta_logins", "")


def make_bot(tmp_path, directory=None, **kw):
    tg = FakeTelegram()
    links = LinkStore(tmp_path / "links.json")
    backend = FakeBackend()
    directory = directory or Directory(_stored())
    bot = VeneraBot(tg, links, users=lambda: directory, backend=backend, webapp_url=WEBAPP,
                    inline=True, typing_every=None, beta_url=kw.pop("beta_url", BETA), **kw)
    bot.username = BOT_NAME
    return bot, tg, links, backend


@pytest.fixture
def world(tmp_path):
    return make_bot(tmp_path)


def press(data, *, markup=None, message_id=500, tg_id=TG_ID, chat_type="private", cq_id="cb1"):
    message = {"message_id": message_id, "chat": {"id": tg_id, "type": chat_type}}
    if markup is not None:
        message["reply_markup"] = markup
    return {"update_id": 7, "callback_query": {"id": cq_id, "from": {"id": tg_id}, "data": data,
                                               "message": message}}


def toasts(tg):
    return [(kw["text"], kw["alert"]) for name, kw in tg.calls if name == "answer_callback"]


def all_buttons(markup):
    return [b for row in (markup or {}).get("inline_keyboard", []) for b in row]


def ask(bot, tg, backend, frames, question="ta'til necha kun?", message_id=10):
    backend.frames = _frames(*frames)
    bot.handle_update(text_update(question, message_id=message_id))
    return tg.sent()[-1]


SOURCES = {"type": "sources", "items": [
    {"kind": "doc", "doc_id": "HR_045", "title": "Ichki mehnat tartibi", "page": 22, "citation_index": 1},
    {"kind": "law", "citation_index": 2, "title": "Mehnat kodeksi, 160-modda", "url": LEX},
    {"kind": "hrm", "tool": "hrm_today_late", "digest": "count=9"},
]}
ANSWER = [SOURCES, {"type": "token", "text": "Asosiy ta'til **21 kun** [1], qonunda ham [2]."},
          {"type": "done", "route": "rules"}]


def _reports_rows():
    return get_db().rows("SELECT * FROM reports ORDER BY created_at")


# --- "⚑" - javob haqida xabar berish -------------------------------------------------


def test_javob_ostida_hujjat_va_xabar_tugmasi(world):
    bot, tg, links, backend = world
    links.link(TG_ID, 1)
    answer = ask(bot, tg, backend, ANSWER)
    rows = answer["reply_markup"]["inline_keyboard"]
    assert rows[0] == [{"text": "📄 Hujjatni ochish", "callback_data": "d:HR_045"}]
    [flag] = rows[-1]
    assert flag["text"] == "⚑" and re.fullmatch(r"r:[0-9a-f]{32}", flag["callback_data"])
    analytics.flush(2.0)
    turn = get_db().row("SELECT actor_id, channel, kind FROM turns WHERE id = ?", (flag["callback_data"][2:],))
    assert turn == {"actor_id": 1, "channel": "bot", "kind": "bot"}


def test_xabar_berish_sabab_bilan_va_rahmat(world):
    bot, tg, links, backend = world
    links.link(TG_ID, 1)
    answer = ask(bot, tg, backend, ANSWER)
    flag = answer["reply_markup"]["inline_keyboard"][-1][0]["callback_data"]
    turn_id = flag[2:]

    # 1) "⚑" - sabablar ochiladi, hujjat tugmasi joyida qoladi.
    bot.handle_update(press(flag, markup=answer["reply_markup"], message_id=answer["message_id"]))
    edit = tg.sent("edit_reply_markup")[-1]
    assert edit["message_id"] == answer["message_id"]
    board = edit["reply_markup"]["inline_keyboard"]
    assert board[0] == [{"text": "📄 Hujjatni ochish", "callback_data": "d:HR_045"}]
    labels = [b["text"] for row in board[1:] for b in row]
    assert labels == ["Notoʻgʻri", "Toʻliq emas", "Eskirgan", "Xavfli", "Boshqa", "Bekor"]
    assert _reports_rows() == [], "sabab tanlanmaguncha hech narsa yuborilmaydi"

    # 2) "Toʻliq emas" - veb ilovadagi AYNI xizmat, kanal `bot`.
    pick = next(b for b in all_buttons(edit["reply_markup"]) if b["text"] == "Toʻliq emas")
    bot.handle_update(press(pick["callback_data"], markup=edit["reply_markup"],
                            message_id=answer["message_id"], cq_id="cb2"))
    assert toasts(tg)[-1] == ("Rahmat, yuborildi", False)
    [row] = _reports_rows()
    chat = links.lookup(TG_ID)[0].chat_id
    assert (row["actor_id"], row["channel"], row["reason"], row["turn_id"], row["chat_id"]) == \
        (1, "bot", "incomplete", turn_id, chat)
    snapshot = json.loads(row["snapshot"])
    assert snapshot["source"] == "telemetry"
    assert [m["content"] for m in snapshot["messages"]][0] == "ta'til necha kun?"
    assert backend.histories == [], "telemetriyada bor - suhbat tarixi so'ralmaydi"

    # 3) Tugma "✓ Yuborildi" ga aylanadi; qayta bosish yangi shikoyat yaratmaydi.
    done = tg.sent("edit_reply_markup")[-1]["reply_markup"]
    assert done["inline_keyboard"][0][0]["callback_data"] == "d:HR_045"
    [again] = done["inline_keyboard"][-1]
    assert again["text"] == "✓ Yuborildi"
    bot.handle_update(press(again["callback_data"], markup=done, message_id=answer["message_id"]))
    assert toasts(tg)[-1] == ("Xabar allaqachon yuborilgan", False)
    assert len(_reports_rows()) == 1


def test_bekor_qilish_tugmani_qaytaradi(world):
    bot, tg, links, backend = world
    links.link(TG_ID, 1)
    answer = ask(bot, tg, backend, [{"type": "token", "text": "Javob."}, {"type": "done"}])
    flag = answer["reply_markup"]["inline_keyboard"][-1][0]["callback_data"]
    bot.handle_update(press(flag, markup=answer["reply_markup"]))
    opened = tg.sent("edit_reply_markup")[-1]["reply_markup"]
    cancel = next(b for b in all_buttons(opened) if b["text"] == "Bekor")
    bot.handle_update(press(cancel["callback_data"], markup=opened))
    assert tg.sent("edit_reply_markup")[-1]["reply_markup"] == answer["reply_markup"]
    assert _reports_rows() == []


def test_sabablar_backend_bilan_bir_xil():
    assert [reason for _, reason, _ in render.REPORT_REASONS] == list(REASONS)


def test_xatoli_yoki_bosh_javob_ostida_xabar_tugmasi_yoq(world):
    bot, tg, links, backend = world
    links.link(TG_ID, 1)
    reply = ask(bot, tg, backend, [{"type": "error", "text": "CRM tizimiga kiring"}, {"type": "done"}])
    assert reply["text"] == "⚠️ CRM tizimiga kiring" and reply["reply_markup"] is None


def _foreign_turn(actor_id=2, channel="bot"):
    user = AuthUser(actorId=actor_id, email="b@b.uz", fullName="Boshqa")
    rec = TurnRecorder(user, channel, "bot", "begona savol", chat_id="begona-suhbat")
    rec.observe({"type": "token", "text": "begona javob"})
    rec.finish()
    analytics.flush(2.0)
    return rec.turn_id


def test_begona_javob_haqida_xabar_berib_bolmaydi(world):
    """Tugma ma'lumoti soxta bo'lishi mumkin: kalit boshqa odamniki - rad."""
    bot, tg, links, backend = world
    links.link(TG_ID, 1)
    foreign = _foreign_turn()
    for data in (f"r:{foreign}", f"r:{foreign}:w"):
        bot.handle_update(press(data))
        assert toasts(tg)[-1] == ("Bu javob haqida xabar berib bo'lmaydi", True)
    # O'z savoli, lekin bot javobi emas (veb kanal) ham - yo'q.
    web_turn = _foreign_turn(actor_id=1, channel="web")
    bot.handle_update(press(f"r:{web_turn}:w"))
    assert toasts(tg)[-1] == ("Bu javob haqida xabar berib bo'lmaydi", True)
    # Umuman yo'q kalit.
    bot.handle_update(press("r:" + "0" * 32 + ":w"))
    assert toasts(tg)[-1] == ("Bu javob haqida xabar berib bo'lmaydi", True)
    assert _reports_rows() == [] and not tg.sent("edit_reply_markup")


@pytest.mark.parametrize("data", [
    "r:", "r:xyz", "r:" + "A" * 32, "r:" + "a" * 31, "r:" + "a" * 33,
    "r:" + "a" * 32 + ":zz", "r:" + "a" * 32 + ":w:x", "r:" + "a" * 32 + ":",
    "r:" + "a" * 32 + ":" + "w" * 40,
])
def test_buzuq_tugma_malumoti_eskirgan(world, data):
    bot, tg, links, backend = world
    links.link(TG_ID, 1)
    bot.handle_update(press(data))
    assert toasts(tg)[-1] == ("Tugma eskirgan", True)
    assert _reports_rows() == []


def test_qayta_ishga_tushgandan_keyin_ombordan_tekshiriladi(tmp_path):
    """Xotira bo'sh (yangi jarayon) - egalik analitika omboridan."""
    bot, tg, links, backend = make_bot(tmp_path)
    links.link(TG_ID, 1)
    answer = ask(bot, tg, backend, ANSWER)
    flag = answer["reply_markup"]["inline_keyboard"][-1][0]["callback_data"]
    fresh, tg2, _, _ = make_bot(tmp_path)              # o'sha ulanishlar fayli
    fresh.handle_update(press(flag + ":w", markup=answer["reply_markup"]))
    assert toasts(tg2)[-1] == ("Rahmat, yuborildi", False)
    assert _reports_rows()[0]["turn_id"] == flag[2:]


def test_analitika_ochiq_bolmasa_ham_xotiradan(world, monkeypatch):
    """Savol izi yozilmaydi - egalik shu jarayon bergan javoblardan, surat
    esa suhbat tarixidan (odamning O'Z kaliti bilan)."""
    bot, tg, links, backend = world
    links.link(TG_ID, 1)
    monkeypatch.setattr(settings, "analytics_enabled", False)
    answer = ask(bot, tg, backend, [{"type": "token", "text": "Javob."}, {"type": "done"}])
    flag = answer["reply_markup"]["inline_keyboard"][-1][0]["callback_data"]
    bot.handle_update(press(flag + ":o", markup=answer["reply_markup"]))
    assert toasts(tg)[-1] == ("Rahmat, yuborildi", False)
    chat = links.lookup(TG_ID)[0].chat_id
    assert backend.histories == [(chat, 1)]
    assert _reports_rows()[0]["reason"] == "outdated"


def test_chegara_veb_bilan_umumiy(world, monkeypatch):
    bot, tg, links, backend = world
    links.link(TG_ID, 1)
    monkeypatch.setattr(reports.limiter, "limit", 1)
    flags = []
    for i in range(2):
        answer = ask(bot, tg, backend, [{"type": "token", "text": f"Javob {i}."}, {"type": "done"}],
                     message_id=20 + i)
        flags.append(answer["reply_markup"]["inline_keyboard"][-1][0]["callback_data"])
    bot.handle_update(press(flags[0] + ":w"))
    bot.handle_update(press(flags[1] + ":w"))
    text, alert = toasts(tg)[-1]
    assert alert and "Juda ko'p" in text and len(_reports_rows()) == 1
    # AYNI chegara: veb (`POST /reports`) ham shu odam uchun to'lgan.
    assert reports.limiter.take(1) is not None


def test_hamma_tugmalar_64_baytga_sigadi(world):
    bot, tg, links, backend = world
    links.link(TG_ID, 1)
    long_id = "D" * 128                                 # SAFE_KEY ga mos, lekin 64 baytdan uzun
    answer = ask(bot, tg, backend, [
        {"type": "sources", "items": [
            {"kind": "doc", "doc_id": long_id, "title": "Uzun kalitli", "citation_index": 1},
            {"kind": "doc", "doc_id": "HR_" + "9" * 58, "title": "Chegarada", "citation_index": 2}]},
        {"type": "token", "text": "Javob [1] [2]."}, {"type": "done"}])
    buttons = all_buttons(answer["reply_markup"])
    flag = buttons[-1]["callback_data"]
    bot.handle_update(press(flag, markup=answer["reply_markup"]))
    buttons += all_buttons(tg.sent("edit_reply_markup")[-1]["reply_markup"])
    buttons += render.report_done_row(flag[2:])
    assert all(len(b["callback_data"].encode()) <= render.CALLBACK_MAX for b in buttons)
    assert not any(long_id in b["callback_data"] for b in buttons), "sig'maydigan tugma tashlanadi"
    assert any(b["callback_data"] == "d:HR_" + "9" * 58 for b in buttons)


# --- izohlar va "Hujjatni ochish" -------------------------------------------------------


def test_izohlar_faqat_iqtibos_qilinganlari_raqami_saqlanadi(world):
    bot, tg, links, backend = world
    links.link(TG_ID, 1)
    answer = ask(bot, tg, backend, [
        {"type": "sources", "items": [
            {"kind": "doc", "doc_id": "A_1", "title": "Birinchi"},          # raqamsiz -> [1]
            {"kind": "doc", "doc_id": "B_2", "title": "Ikkinchi"},          # [2] - iqtibos yo'q
            {"kind": "doc", "doc_id": "C_3", "title": "Uchinchi", "page": 7}]},
        {"type": "token", "text": "Birinchisi [1], uchinchisi [3]."}, {"type": "done"}])
    text = answer["text"]
    assert text.endswith("📚 <b>Manbalar</b>\n[1] Birinchi\n[3] Uchinchi, 7-bet")
    assert "Ikkinchi" not in text
    docs = [b for b in all_buttons(answer["reply_markup"]) if b["callback_data"].startswith("d:")]
    assert docs == [{"text": "📄 [1] Hujjatni ochish", "callback_data": "d:A_1"},
                    {"text": "📄 [3] Hujjatni ochish", "callback_data": "d:C_3"}]


def test_iqtibos_bolmasa_hammasi_va_chegara(world):
    bot, tg, links, backend = world
    links.link(TG_ID, 1)
    items = [{"kind": "doc", "doc_id": f"D_{i}", "title": f"Hujjat {i}", "citation_index": i}
             for i in range(1, 9)]
    items[0]["title"] = "Juda uzun nom " * 20
    answer = ask(bot, tg, backend, [{"type": "sources", "items": items},
                                    {"type": "token", "text": "Iqtibossiz javob."}, {"type": "done"}])
    lines = answer["text"].split("📚 <b>Manbalar</b>\n")[1].split("\n")
    assert len(lines) == render.FOOTNOTES_MAX + 1
    assert lines[-1] == "<i>… yana 2 ta manba - Barno ilovasida</i>"
    assert lines[0].endswith("…") and len(lines[0]) < 100
    docs = [b for b in all_buttons(answer["reply_markup"]) if b["callback_data"].startswith("d:")]
    assert [b["text"] for b in docs] == [f"📄 [{i}]" for i in range(1, 7)]
    rows = answer["reply_markup"]["inline_keyboard"]
    assert [len(r) for r in rows] == [3, 3, 1], "ko'p hujjat - 3 tadan qisqa tugma, oxirida ⚑"


def test_lex_uz_havola_faqat_https(world):
    bot, tg, links, backend = world
    links.link(TG_ID, 1)
    answer = ask(bot, tg, backend, ANSWER)
    assert f'[2] LEX.UZ · qonunchilik: <a href="{LEX}">Mehnat kodeksi, 160-modda</a>' in answer["text"]
    bad = ask(bot, tg, backend, [
        {"type": "sources", "items": [{"kind": "law", "citation_index": 1, "title": "Modda",
                                       "url": "javascript:alert(1)"}]},
        {"type": "token", "text": "Javob [1]."}, {"type": "done"}], message_id=11)
    assert "<a " not in bad["text"] and "[1] LEX.UZ · qonunchilik: Modda" in bad["text"]
    assert not [b for b in all_buttons(bad["reply_markup"]) if b["callback_data"].startswith("d:")]


def test_hujjatni_ochish_imzolangan_havola_yuboradi(world):
    bot, tg, links, backend = world
    links.link(TG_ID, 1)
    answer = ask(bot, tg, backend, ANSWER)
    bot.handle_update(press("d:HR_045", markup=answer["reply_markup"], message_id=answer["message_id"]))
    assert backend.links == [("HR_045", 1, "Ichki mehnat tartibi")]
    sent = tg.sent()[-1]
    assert sent["reply_to"] == answer["message_id"]
    assert sent["text"].startswith("📄 <b>Ichki mehnat tartibi</b>") and "10 daqiqa" in sent["text"]
    assert sent["reply_markup"] == {"inline_keyboard": [[{
        "text": "📄 Hujjatni ochish", "url": "https://llm.brb-tech.uz/api/v1/chat/file/SIGNED-HR_045"}]]}
    # Bank hujjati Telegram'ga YUKLANMAYDI.
    assert not tg.sent("send_document") and backend.files == []


def test_hujjat_havolasi_yasalmasa_tushunarli_xabar(world):
    bot, tg, links, backend = world
    links.link(TG_ID, 1)
    backend.link_error = RuntimeError("buzildi")
    count = len(tg.sent())
    bot.handle_update(press("d:HR_045"))
    assert toasts(tg)[-1] == ("Hujjatni hozir ochib bo'lmadi - Barno ilovasida oching.", True)
    assert len(tg.sent()) == count


def test_haqiqiy_imzo_bot_kanali_bilan(monkeypatch):
    """`Backend.doc_link` - mini app'dagi AYNI imzolovchi (`chat.doc_link`), kanal `bot`."""
    user = AuthUser(actorId=7, email="a@b.uz", fullName="Ali")
    link = Backend().doc_link("HR_045", user, "Ichki tartib")
    assert link.url.startswith("/api/v1/chat/file/") and link.expiresIn == 600
    claims = jwt.decode(link.url.rsplit("/", 1)[1], settings.secret_key, algorithms=["HS256"],
                        audience="venera:file")
    assert (claims["kind"], claims["doc"], claims["uid"], claims["ch"]) == ("doc", "HR_045", 7, "bot")
    with pytest.raises(ValueError):
        Backend().doc_link("../etc", user, None)


# --- ulanmagan odam ---------------------------------------------------------------------


def test_token_yoq_xatosi_crm_ni_ulashga_yubormaydi():
    """`auth_missing` zaxira matni: HRM qo'lda ulanadi, CRM esa vebga BRB-Tech ID bilan
    kirganda o'zi ulanadi - "CRM ga kiring / ulang" degan yo'l endi yo'q. Xizmatning
    o'z matni kelsa - o'sha yutadi."""
    for code in ("auth_missing", "auth_expired"):
        text = render.frame_error({"type": "error", "code": code})
        assert "BRB-Tech ID" in text and "HRM" in text and "CRM" in text
        assert "CRM ga kiring" not in text and "CRM hisobingizga" not in text
    assert render.frame_error({"code": "auth_missing", "text": "Xizmat matni"}) == "Xizmat matni"
    assert render.frame_error({"code": "boshqa"}) == "Javob berilmadi"


def test_ulanmagan_odamga_bitta_xabar_va_ilova_tugmasi(world):
    bot, tg, links, backend = world
    bot.handle_update(text_update("salom"))
    bot.handle_update(text_update("yana", message_id=11))
    [only] = tg.sent()
    assert "bir marta" in only["text"]
    assert only["reply_markup"] == {"inline_keyboard": [[{"text": "Barnoni ochish",
                                                          "web_app": {"url": WEBAPP}}]]}
    # `/help` ham bitta xabar: yordam + o'sha tugma.
    bot.handle_update(text_update("/help", message_id=12))
    assert len(tg.sent()) == 2 and tg.sent()[-1]["reply_markup"] == only["reply_markup"]


def test_bloklangan_odamga_xushmuomala_rad(tmp_path, monkeypatch):
    from app.services import admin_users

    bot, tg, links, backend = make_bot(tmp_path)
    links.link(TG_ID, 1)
    monkeypatch.setattr(admin_users, "access", lambda user, login=None: admin_users.Access(
        user=user, blocked=True, token_version=0, bootstrap=False))
    bot.handle_update(text_update("savol"))
    assert tg.texts() == [_BLOCKED] and backend.questions == []


# --- buyruqlar ------------------------------------------------------------------------


def test_start_salom_va_ochish_tugmasi(world):
    bot, tg, links, backend = world
    links.link(TG_ID, 1)
    bot.handle_update(text_update("/start"))
    sent = tg.sent()[-1]
    assert "Hisobingiz ulangan" in sent["text"]
    assert sent["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"] == WEBAPP


def test_help_qisqa(world):
    bot, tg, links, backend = world
    links.link(TG_ID, 1)
    bot.handle_update(text_update("/help"))
    text = tg.sent()[-1]["text"]
    assert text.count("•") <= 4 and len(text.splitlines()) <= 8
    assert "/new" in text and "⚑" in text and "/plaud" in text
    assert tg.sent()[-1]["reply_markup"] is None, "ulangan odamga ortiqcha tugma yo'q"


def test_logout_va_chiqish(world):
    bot, tg, links, backend = world
    links.link(TG_ID, 1)
    bot.handle_update(text_update("/logout"))
    assert links.lookup(TG_ID) == (None, "none") and "uzildi" in tg.texts()[-1]
    links.link(TG_ID, 1)
    bot.handle_update(text_update("/chiqish", message_id=11))
    assert links.lookup(TG_ID) == (None, "none")


def test_menyu_buyruqlari():
    assert [c["command"] for c in COMMANDS] == ["start", "plaud", "ovoz", "new", "help", "logout"]
    assert all(len(c["description"]) <= 256 for c in COMMANDS)


def test_menyu_faqat_farq_qilsa_va_xato_botni_toxtatmaydi(tmp_path):
    bot, tg, links, backend = make_bot(tmp_path, sync_commands=True)
    bot._prepare()
    assert tg.commands == COMMANDS and len(tg.sent("set_my_commands")) == 1
    assert bot.sync_menu() is False and len(tg.sent("set_my_commands")) == 1, "idempotent"

    def broken():
        raise TelegramError("getMyCommands: tarmoq xatosi")

    tg.get_my_commands = broken
    assert bot.sync_menu() is False and bot._prepared


def test_menyu_test_nusxasida_yozilmaydi(world):
    bot, tg, links, backend = world
    links.link(TG_ID, 1)
    bot._prepare()
    for text in ("/start", "/help", "/new", "savol", "/beta"):
        bot.handle_update(text_update(text))
    assert not tg.sent("set_my_commands") and tg.commands == []


def _beta_reply(bot, tg):
    bot.handle_update(text_update("/beta"))
    return tg.sent()[-1]


def test_beta_admin_rolida(tmp_path):
    bot, tg, links, _ = make_bot(tmp_path, Directory(_stored(roles=["ADMIN"])))
    links.link(TG_ID, 1)
    reply = _beta_reply(bot, tg)
    assert "beta" in reply["text"]
    assert reply["reply_markup"] == {"inline_keyboard": [[{"text": "🧪 Beta'ni ochish",
                                                           "web_app": {"url": BETA}}]]}


def test_beta_royxatdagi_login(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "miniapp_beta_logins", "x.boshqa, A@B.uz")
    bot, tg, links, _ = make_bot(tmp_path)
    links.link(TG_ID, 1)
    assert _beta_reply(bot, tg)["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"] == BETA


def test_beta_sso_hisobi_faqat_login_bilan(tmp_path, monkeypatch):
    """SSO emailini odam Keycloak'da o'zi o'zgartira oladi - faqat login."""
    sso = Identity(subject="s-1", actor_id=1, username="y.mamajonov", email="a@b.uz",
                   full_name="Ali", roles=["employee"])
    bot, tg, links, _ = make_bot(tmp_path, Directory(sso))
    links.link(TG_ID, 1)
    monkeypatch.setattr(settings, "miniapp_beta_logins", "a@b.uz")
    assert _beta_reply(bot, tg)["text"] == _UNKNOWN
    monkeypatch.setattr(settings, "miniapp_beta_logins", "Y.Mamajonov")
    assert _beta_reply(bot, tg)["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"] == BETA


def test_beta_boshqalarga_noma_lum_buyruq(tmp_path):
    bot, tg, links, _ = make_bot(tmp_path)
    bot.handle_update(text_update("/beta"))                       # ulanmagan
    links.link(TG_ID, 1)
    bot.handle_update(text_update("/beta", message_id=11))        # ruxsatsiz
    bot.handle_update(text_update("/yoq_buyruq", message_id=12))
    assert tg.texts() == [_UNKNOWN, _UNKNOWN, _UNKNOWN]
    assert all(s["reply_markup"] is None for s in tg.sent())


def test_beta_manzil_sozlanmagan_bolsa_admin_ham_kormaydi(tmp_path):
    bot, tg, links, _ = make_bot(tmp_path, Directory(_stored(roles=["ADMIN"])), beta_url="")
    links.link(TG_ID, 1)
    assert _beta_reply(bot, tg)["text"] == _UNKNOWN


# --- faqat shaxsiy chat ------------------------------------------------------------------


def group_update(text=None, *, chat_type="group", chat_id=-100500, message_id=40, **extra):
    message = {"message_id": message_id, "from": {"id": TG_ID, "is_bot": False},
               "chat": {"id": chat_id, "type": chat_type}, **extra}
    if text is not None:
        message["text"] = text
    return {"update_id": 9, "message": message}


def test_guruhda_murojaatsiz_xabar_jim(world):
    bot, tg, links, backend = world
    links.link(TG_ID, 1)
    for text in ("ta'tilim necha kun?", "/help@boshqa_bot", f"@{BOT_NAME}x salom"):
        bot.handle_update(group_update(text))
    bot.handle_update(group_update("salom", chat_type="channel"))
    from_bot = group_update(f"/help@{BOT_NAME}")
    from_bot["message"]["from"] = {"id": 77, "is_bot": True, "username": "boshqa_bot"}
    bot.handle_update(from_bot)
    assert tg.calls == [] and backend.questions == []


@pytest.mark.parametrize("update", [
    group_update("/help"),
    group_update(f"/start@{BOT_NAME}"),
    group_update(f"@{BOT_NAME} ish haqim qancha?", chat_type="supergroup"),
    group_update("menga ayting", reply_to_message={"message_id": 3, "from": {
        "id": 1, "is_bot": True, "username": BOT_NAME}}),
    group_update(new_chat_members=[{"id": 1, "is_bot": True, "username": BOT_NAME}]),
])
def test_guruhda_murojaatga_bitta_qisqa_javob(world, update):
    bot, tg, links, backend = world
    links.link(TG_ID, 1)                     # ulangan odam ham guruhda HR javob olmaydi
    bot.handle_update(update)
    bot.handle_update(update)                # takror - jim (10 daqiqa)
    [reply] = tg.sent()
    assert reply["text"] == _GROUP_ONLY and reply["chat_id"] == -100500
    assert reply["reply_markup"] == {"inline_keyboard": [[{"text": "Shaxsiy chatni ochish",
                                                           "url": f"https://t.me/{BOT_NAME}"}]]}
    assert backend.questions == [] and [n for n, _ in tg.calls] == ["send_message"]


def test_guruhdagi_tugma_bajarilmaydi(world):
    bot, tg, links, backend = world
    links.link(TG_ID, 1)
    bot.handle_update(press("a:c:" + "a" * 32, chat_type="group"))
    bot.handle_update(press("d:HR_045", chat_type="supergroup"))
    assert backend.actions == [] and backend.links == []
    assert toasts(tg) == [(_GROUP_ONLY, False), (_GROUP_ONLY, False)]


# --- "Pro" botda yo'q ------------------------------------------------------------------


def test_bot_har_doim_standart_rejimda(monkeypatch):
    from app.api.v1 import chat as chat_api

    seen = {}

    def fake_open(question, user, chat_id, **kwargs):
        seen.update(kwargs)
        return "oqim"

    monkeypatch.setattr(chat_api, "open_stream", fake_open)
    user = AuthUser(actorId=1, email="a@b.uz", fullName="Ali")
    assert Backend().stream("savol", user, "suhbat") == "oqim"
    assert BOT_MODE == "standard"
    assert seen == {"channel": "bot", "mode": "standard", "engine": None}


def test_pro_bloki_va_buyrugi_yoq(world):
    bot, tg, links, backend = world
    links.link(TG_ID, 1)
    answer = ask(bot, tg, backend, [
        {"type": "token", "text": "Javob."},
        {"type": "done", "engine": "v2", "pro": {"used": True, "remaining": 3}}])
    assert answer["text"] == "Javob." and "Pro" not in answer["text"]
    bot.handle_update(text_update("/pro", message_id=11))
    assert tg.texts()[-1] == _UNKNOWN
