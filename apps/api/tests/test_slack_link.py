"""Slack hisobini Barno hisobiga ulash - «Connect Barno AI account» (`app/slack/link.py`,
`services/slack_links.py`, `api/v1/slack.py`).

Ega qarori (2026-11-12): ulanmagan odamga Barno ishni bajarmaydi - faqat o'ziga ko'rinadigan ulash
tugmasi; tugma Barno kirish sahifasini ochadi (SSO yoki login + parol), ulanish faqat tasdiq sahifasida
tugma bosilganda yoziladi. Ulangach yozuv va savollar odamning O'Z hisobida va ilovadagi suhbati bilan
bitta; ulashdan oldingi yozuvlar umumiy hisobda qoladi va ularning kartalari ishlayveradi. Uzish - Slack
"Home" varag'idan; admin "hamma joydan chiqarish" i ham uzadi.

Hammasi soxta (`slack_fakes.py`, `meetings_fakes.py`): tarmoq ham, pul ham yo'q.
"""

from __future__ import annotations

import time

from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from app.core.config import settings
from app.services import admin_users
from app.services.meetings import llm
from app.services.slack_links import LinkStore
from app.slack import assistant, home, link, meeting, render
from slack_fakes import AUDIO, BOT_USER, FakeSlack, as_parent, card, drive, send_audio, setup
from meetings_fakes import FakeAnthropic

APP = "https://llm.test"


def _linking_on(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "sso_app_url", APP, raising=False)
    monkeypatch.setattr(settings, "slack_link_required", True, raising=False)
    monkeypatch.setattr(settings, "slack_links_file", tmp_path / "slack" / "links.json", raising=False)
    monkeypatch.setattr(link, "_offered", {})
    link.TICKETS.clear()


@pytest.fixture
def linking(users_file, monkeypatch, tmp_path):
    """Shaxsiy hisob majburiy (`SSO_APP_URL` bor). Umumiy hisob (actor 1) - ESKI yozuvlar uchun.
    Qaytaradi: yuklab olingan audio manzillari."""
    calls = setup(monkeypatch, users_file)
    _linking_on(monkeypatch, tmp_path)
    yield calls
    link.TICKETS.clear()


@pytest.fixture
def claude(_isolated_meetings, monkeypatch):
    monkeypatch.setattr(settings, "meetings_ask_chain", "claude", raising=False)
    fake = FakeAnthropic()
    _isolated_meetings.ask_claude = llm.ClaudeChat(lambda: "sk-ant-test-SLACK", "claude-sonnet-5-5", timeout=10,
                                                   client_factory=fake, fallbacks=True)
    return fake


def _url(message: dict) -> str:
    [button] = [e for b in message["blocks"] if b["type"] == "actions" for e in b["elements"]]
    assert button["text"]["text"] == link.BUTTON
    return button["url"]


def _ticket(message: dict) -> str:
    url = _url(message)
    assert url.startswith(f"{APP}/link/slack?t=")
    return url.split("t=", 1)[1]


def _actions(view: dict) -> list[str]:
    return [e["action_id"] for b in view["blocks"] if b["type"] == "actions" for e in b["elements"]]


def _texts(view: dict) -> str:
    return "\n".join(b["text"]["text"] for b in view["blocks"] if b.get("type") == "section")


# --- ulanmagan odam ------------------------------------------------------------------------------


def test_ulanmagan_odam_audio_yuborsa_ish_emas_ulash_tugmasi(linking):
    slack = FakeSlack(files={"F1": AUDIO})
    event = slack.say("D2", files=[AUDIO], user="U2", team="T1")
    meeting.acknowledge(slack, event)

    assert slack.posted == [] and linking == []               # til savoli ham, yuklab olish ham yo'q
    [offer] = slack.ephemeral
    assert (offer["channel"], offer["user"]) == ("D2", "U2")
    assert link.OFFER_HEAD in offer["blocks"][0]["text"]["text"]
    ticket = link.describe(_ticket(offer))
    assert (ticket.team_id, ticket.user_id, ticket.channel) == ("T1", "U2", "D2")
    # Havola - Barno manzili va faqat bir martalik chipta; Slack id'lari havolada YO'Q.
    parsed = urlsplit(_url(offer))
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == f"{APP}/link/slack"
    assert list(parse_qs(parsed.query)) == ["t"]


def test_matn_va_thread_savoli_ham_ulashni_soraydi_takrorsiz(linking):
    slack = FakeSlack()
    # Chatning o'zidagi matn - HR/CRM yordamchisiga (2026-11-13): ulanmagan odamga javob ham emas, faqat ulash.
    assistant.on_text(slack, slack.say("D2", "Salom", user="U2", team="T1"))
    assistant.on_text(slack, slack.say("D2", "Yana", user="U2", team="T1"))
    assert len(slack.ephemeral) == 1 and slack.posted == []

    link._offered.clear()
    question = slack.say("D2", "Kim?", user="U2", team="T1", thread="100.1")
    meeting.on_message(slack, question, bot_user=BOT_USER)
    assert len(slack.ephemeral) == 2 and slack.ephemeral[-1]["thread_ts"] == "100.1"


def test_muddati_otgan_ulanish_va_ochirilgan_hisob(linking):
    slack = FakeSlack()
    links = link.store()
    links.link("T1", "U2", 2, now=time.time() - 31 * 86400)
    assistant.on_text(slack, slack.say("D2", "Salom", user="U2", team="T1"))
    assert link.OFFER_EXPIRED in slack.ephemeral[-1]["blocks"][0]["text"]["text"]

    links.link("T1", "U9", 99)                                # bunday hisob yo'q (o'chirilgan)
    with pytest.raises(link.NotLinked):
        link.person("T1", "U9")
    assert links.lookup("T1", "U9") == (None, "none")         # ulanish ham olib tashlandi


def test_bloklangan_hisobga_sababi_aytiladi(linking, client, auth):
    link.store().link("T1", "U2", 2)
    assert client.patch("/api/v1/admin/users/2", headers=auth, json={"disabled": True}).status_code == 200
    slack = FakeSlack()
    assistant.on_text(slack, slack.say("D2", "Salom", user="U2", team="T1"))
    assert slack.ephemeral[-1]["text"] == render.escape(link.BLOCKED) and slack.posted == []


def test_plaud_buyrugi_tugma_va_birinchi_ochilish_ulashni_soraydi(linking):
    slack = FakeSlack()
    home.on_command(slack, {"command": "/plaud", "channel_id": "D2", "user_id": "U2", "team_id": "T1"})
    assert slack.posted == [] and _ticket(slack.ephemeral[-1])
    # Tugma bosilishi - odamning o'z harakati: takror cheklovi yo'q.
    home.on_plaud(slack, {"user": {"id": "U2", "team_id": "T1"}, "channel": {"id": "D2"},
                          "actions": [{"action_id": home.PLAUD_ACTION}]})
    assert len(slack.ephemeral) == 2

    link._offered.clear()
    home.on_open(slack, {"type": "app_home_opened", "user": "U2", "tab": "messages", "channel": "D2", "team": "T1"})
    assert slack.posted[-1]["text"].startswith("🎙 *Plaud*")   # nima qila olishi - va ulash tugmasi
    assert len(slack.ephemeral) == 3


def test_ephemeral_ketmasa_shaxsiy_xabarga(linking):
    """`/plaud` Barno a'zo bo'lmagan kanalda: ephemeral rad etiladi - havola shaxsiy xabarda (hech qachon
    hammaga ko'rinadigan xabarda emas)."""

    class NoEphemeral(FakeSlack):
        def chat_postEphemeral(self, **kwargs):
            raise RuntimeError("channel_not_found")

    slack = NoEphemeral()
    home.on_command(slack, {"command": "/plaud", "channel_id": "C9", "user_id": "U2", "team_id": "T1"})
    [sent] = slack.posted
    assert sent["channel"] == "U2" and _ticket(sent)


# --- tasdiq sahifasi (API) -----------------------------------------------------------------------


def test_tasdiq_sahifasi_ulaydi_chipta_bir_martalik(linking, client, user_auth):
    ticket = link.new_ticket("T1", "U2", "D2", name="Demo Slack")
    url = f"/api/v1/slack/link/{ticket}"
    assert client.get(url).status_code == 401                 # kirmagan - kirish sahifasiga

    info = client.get(url, headers=user_auth)
    assert info.status_code == 200, info.text
    body = info.json()
    assert (body["slackName"], body["accountName"]) == ("Demo Slack", "Demo Foydalanuvchi")
    assert 0 < body["expiresIn"] <= link.TICKET_TTL
    assert client.get(url, headers=user_auth).status_code == 200    # ko'rish chiptani yoqmaydi

    done = client.post("/api/v1/slack/link", headers=user_auth, json={"ticket": ticket})
    assert done.status_code == 200, done.text
    assert (done.json()["status"], done.json()["days"]) == ("new", 30)
    found, state = link.store().lookup("T1", "U2")
    assert state == "linked" and found.actor_id == 2

    again = client.post("/api/v1/slack/link", headers=user_auth, json={"ticket": ticket})
    assert again.status_code == 404 and client.get(url, headers=user_auth).status_code == 404


def test_boshqa_hisobga_otkazish_va_uzish(linking, client, auth, user_auth):
    link.store().link("T1", "U2", 1)
    ticket = link.new_ticket("T1", "U2", "D2")
    done = client.post("/api/v1/slack/link", headers=user_auth, json={"ticket": ticket})
    assert done.json()["status"] == "switched" and link.store().lookup("T1", "U2")[0].actor_id == 2

    gone = client.post("/api/v1/slack/unlink", headers=user_auth)
    assert gone.status_code == 200 and gone.json() == {"unlinked": 1}
    assert link.store().lookup("T1", "U2") == (None, "none")


def test_yaroqsiz_chipta_va_sozlanmagan_ulash(linking, client, user_auth, monkeypatch):
    assert client.post("/api/v1/slack/link", headers=user_auth, json={"ticket": "x" * 43}).status_code == 404
    assert client.post("/api/v1/slack/link", headers=user_auth, json={"ticket": "../../etc"}).status_code == 422

    monkeypatch.setattr(settings, "sso_app_url", "", raising=False)
    ticket = link.new_ticket("T1", "U2", "D2")
    assert client.post("/api/v1/slack/link", headers=user_auth, json={"ticket": ticket}).status_code == 501
    assert client.get(f"/api/v1/slack/link/{ticket}", headers=user_auth).status_code == 501


def test_chipta_muddati_otadi(linking, monkeypatch):
    ticket = link.new_ticket("T1", "U2", "D2")
    assert link.describe(ticket) is not None
    later = time.time() + link.TICKET_TTL + 1
    monkeypatch.setattr(link.time, "time", lambda: later)
    assert link.describe(ticket) is None
    assert link.confirm(ticket, SimpleNamespace(actorId=2)) is None


def test_ulangach_slackka_xabar_va_home_yangilanadi(linking):
    slack = FakeSlack()
    ticket = link.Ticket(team_id="T1", user_id="U2", channel="D2", name="", created=time.time())
    link.store().link("T1", "U2", 2)
    link.notify_linked(ticket, SimpleNamespace(fullName="Demo Foydalanuvchi", email="demo@x"), client=slack)
    assert slack.posted[-1]["channel"] == "D2" and "Demo Foydalanuvchi" in slack.posted[-1]["text"]
    assert link.UNLINK_ACTION in _actions(slack.published[-1]["view"])


def test_admin_hamma_joydan_chiqarsa_slack_ulanishi_uziladi(linking, client, auth):
    link.store().link("T1", "U2", 2)
    link.store().link("T1", "U3", 1)
    assert client.post("/api/v1/admin/users/2/signout", headers=auth).status_code == 200
    assert link.store().lookup("T1", "U2") == (None, "none")
    assert link.store().lookup("T1", "U3")[1] == "linked"     # boshqa odamniki joyida
    entry = admin_users.audit_entries(target_type="user", target_id=2)[0]
    assert entry["action"] == "user.signout" and entry["detail"]["slackLinks"] == 1


# --- ulangan odam --------------------------------------------------------------------------------


def test_ulangan_odamning_yozuvi_va_savoli_ozida_ilova_bilan_bitta(linking, _isolated_meetings, claude,
                                                                    client, user_auth, monkeypatch):
    link.store().link("T1", "U2", 2)
    rt = _isolated_meetings
    slack = FakeSlack(files={"F1": AUDIO})
    send_audio(slack, slack.say("D2", files=[AUDIO], user="U2", team="T1"), rt, user="U2")
    summary = card(slack)
    mid = render.marked(summary)
    assert rt.store.meeting_any(mid)["actor_id"] == 2          # umumiy hisob (1) emas

    slack.parents[summary["ts"]] = as_parent(summary)
    question = slack.say("D2", "Kim hisobot yuboradi?", user="U2", team="T1", thread=summary["ts"])
    meeting.on_message(slack, question, bot_user=BOT_USER)
    meeting.on_message(slack, slack.say("D2", "Batafsilroq", user="U2", team="T1", thread=summary["ts"]),
                       bot_user=BOT_USER)
    # So'rovchi yo'q - egasining suhbati: Slack'dagi savollar ilovadagi chat bilan bitta.
    assert [t["question"] for t in rt.store.chat_turns(mid)] == ["Kim hisobot yuboradi?", "Batafsilroq"]
    assert rt.store.chat_turns(mid, asker="slack:U2") == []
    assert [m["role"] for m in claude.chats()[-1]["messages"]] == ["user", "assistant", "user"]

    # Ilovadagi Plaud bo'limi hali faqat sinov ro'yxatiga ochiq (`MEETINGS_LOGINS`): ro'yxatdan tashqaridagi
    # odam Slack yozuvini faqat Slack'da ko'radi; ro'yxatdagisi - ilovada ham, o'sha suhbat bilan.
    assert client.get(f"/api/v1/meetings/{mid}/chat", headers=user_auth).status_code == 403
    monkeypatch.setattr(settings, "meetings_logins", "demo@venera.uz", raising=False)
    items = client.get(f"/api/v1/meetings/{mid}/chat", headers=user_auth)
    assert items.status_code == 200, items.text
    assert [t["question"] for t in items.json()["items"]] == ["Kim hisobot yuboradi?", "Batafsilroq"]


def test_ulangan_odam_bayonnoma_korsatmasi_ilovadagi_suhbat_bilan_bitta(linking, _isolated_meetings, monkeypatch):
    """Ulangan odamning O'Z yozuvi: bayonnoma menyusi thread'idagi ko'rsatma egasining suhbatiga (`asker` yo'q -
    ilovadagi chat bilan bitta), til tugmasi ham egasi nomidan - ko'rsatma hujjatga qo'llanadi (umumiy hisobdagi
    `slack:<user id>` bo'lsa ko'rsatma topilmasdi)."""
    link.store().link("T1", "U2", 2)
    rt = _isolated_meetings
    monkeypatch.setattr(settings, "meetings_minutes_chain", "ollama", raising=False)
    slack = FakeSlack(files={"F1": AUDIO})
    send_audio(slack, slack.say("D2", files=[AUDIO], user="U2", team="T1"), rt, user="U2")
    summary = card(slack)
    mid = render.marked(summary)
    body = {"channel": {"id": "D2"}, "user": {"id": "U2"}, "team": {"id": "T1"}}
    meeting.on_action(slack, {**body, "actions": [{"action_id": "barno_minutes", "value": mid}],
                              "message": {"ts": summary["ts"]}}, sleep=drive(rt))
    menu = slack.posted[-1]
    thread = slack.thread_under(menu)
    meeting.on_message(slack, slack.say("D2", "CHAIR=Alisher Karimov", user="U2", team="T1", thread=thread),
                       bot_user=BOT_USER)
    [note] = rt.store.chat_turns(mid)
    assert (note["kind"], note["asker"]) == ("note", None) and rt.store.chat_turns(mid, asker="slack:U2") == []

    meeting.on_action(slack, {**body, "actions": [{"action_id": "barno_minutes_lang_uz-cyrl",
                                                   "value": f"{mid}|uz-cyrl"}],
                              "message": {"ts": menu["ts"]}}, sleep=drive(rt))
    # Tildan keyin format (2026-11-13) - format savoli xabaridagi tugma.
    meeting.on_action(slack, {**body, "actions": [{"action_id": "barno_minutes_fmt_docx", "value": f"{mid}|uz-cyrl"}],
                              "message": {"ts": slack.posted[-1]["ts"]}}, sleep=drive(rt))
    [call] = [c for c in rt.llm.calls if c["op"] == "meeting_minutes"]
    assert "1. CHAIR=Alisher Karimov" in call["user"]
    assert "Ko'rsatmalaringiz hisobga olindi (1 ta)." in slack.updated[-1]["text"]
    assert [row["asker"] for row in rt.store.minutes_rows(mid)] == [None]


def test_eski_yozuv_umumiy_hisobda_qoladi_kartasi_ishlaydi(users_file, monkeypatch, tmp_path, _isolated_meetings,
                                                          claude):
    setup(monkeypatch, users_file)
    rt = _isolated_meetings
    slack = FakeSlack(files={"F1": AUDIO})
    # Ulash yoqilishidan OLDIN: umumiy hisob (actor 1).
    send_audio(slack, slack.say("D1", files=[AUDIO], user="U1", team="T1"), rt, user="U1")
    summary = card(slack)
    mid = render.marked(summary)
    slack.parents[summary["ts"]] = as_parent(summary)
    assert rt.store.meeting_any(mid)["actor_id"] == 1

    _linking_on(monkeypatch, tmp_path)
    link.store().link("T1", "U1", 2)
    question = slack.say("D1", "Kim?", user="U1", team="T1", thread=summary["ts"])
    meeting.on_message(slack, question, bot_user=BOT_USER)
    meeting.on_message(slack, slack.say("D1", "Batafsilroq", user="U1", team="T1", thread=summary["ts"]),
                       bot_user=BOT_USER)
    # Eski yozuv - avvalgidek har odam o'z suhbatida (umumiy hisobda).
    assert [t["question"] for t in rt.store.chat_turns(mid, asker="slack:U1")] == ["Kim?", "Batafsilroq"]
    assert rt.store.meeting_any(mid)["actor_id"] == 1

    meeting.on_action(slack, {"actions": [{"action_id": "barno_transcript", "value": mid}],
                              "channel": {"id": "D1"}, "user": {"id": "U1"}, "team": {"id": "T1"},
                              "message": {"ts": summary["ts"]}}, sleep=drive(rt))
    assert slack.uploaded[-1]["thread_ts"] == summary["ts"]


def test_ulanmagan_odam_eski_kartani_bossa_ham_ulash(linking, _isolated_meetings):
    slack = FakeSlack()
    meeting.on_action(slack, {"actions": [{"action_id": "barno_transcript", "value": "a" * 32}],
                              "channel": {"id": "D2"}, "user": {"id": "U2"}, "team": {"id": "T1"},
                              "message": {"ts": "100.1"}}, sleep=drive(_isolated_meetings))
    assert slack.uploaded == [] and _ticket(slack.ephemeral[-1])


# --- "Home" varag'i ------------------------------------------------------------------------------


def test_home_varagi_ulash_va_uzish(linking):
    slack = FakeSlack()
    opened = {"type": "app_home_opened", "user": "U2", "tab": "home", "team": "T1"}
    home.on_open(slack, opened)
    view = slack.published[-1]["view"]
    assert home.TAGLINE in _texts(view) and _actions(view) == [link.CONNECT_ACTION]

    # Home'da kanal yo'q - ulash havolasi shaxsiy xabarda.
    link.on_action(slack, {"actions": [{"action_id": link.CONNECT_ACTION}], "user": {"id": "U2", "team_id": "T1"},
                           "team": {"id": "T1"}})
    assert slack.posted[-1]["channel"] == "U2" and _ticket(slack.posted[-1])

    link.store().link("T1", "U2", 2)
    home.on_open(slack, opened)
    view = slack.published[-1]["view"]
    assert "Demo Foydalanuvchi" in _texts(view) and _actions(view) == [link.UNLINK_ACTION]

    link.on_action(slack, {"actions": [{"action_id": link.UNLINK_ACTION, "value": "unlink"}],
                           "user": {"id": "U2", "team_id": "T1"}, "team": {"id": "T1"}})
    assert link.store().lookup("T1", "U2") == (None, "none")
    assert "uzildi" in slack.posted[-1]["text"]
    assert _actions(slack.published[-1]["view"]) == [link.CONNECT_ACTION]


def test_ulash_ochiq_bolmasa_home_eskicha(users_file, monkeypatch):
    setup(monkeypatch, users_file)
    assert not link.required()
    assert home.view("T1", "U2") == {"type": "home", "blocks": [
        {"type": "section", "text": {"type": "mrkdwn", "text": home.TAGLINE}}]}


# --- dispetcher va ombor -------------------------------------------------------------------------


def test_dispetcher_ulash_tugmalari_va_ish_maydoni(monkeypatch):
    from app import slack as slack_app

    jobs = []
    monkeypatch.setattr(slack_app, "_pool", SimpleNamespace(submit=lambda fn, *a, **k: jobs.append((fn, a))))
    for action in (link.LINK_ACTION, link.CONNECT_ACTION, link.UNLINK_ACTION):
        slack_app._on_action(lambda: None, {"actions": [{"action_id": action}], "user": {"id": "U2"}}, FakeSlack())
        assert jobs[-1][0] is link.on_action
    event = {"type": "app_home_opened", "user": "U2", "tab": "home"}
    slack_app._on_home(event, FakeSlack(), {"team_id": "T7"})
    assert event["team"] == "T7" and jobs[-1][0] is home.on_open
    message = {"channel_type": "im", "user": "U2", "channel": "D2", "ts": "1.1", "text": "salom"}
    slack_app._on_message(message, FakeSlack(), {"team_id": "T7", "bot_user_id": BOT_USER})
    assert message["team"] == "T7"


def test_ulanishlar_ombori(tmp_path):
    path = tmp_path / "links.json"
    store = LinkStore(path, ttl_days=30)
    assert store.link("T1", "U1", 2, now=1000) == "new"
    assert store.link("T1", "U1", 2, now=2000) == "refreshed"
    assert store.link("T1", "U1", 3, now=3000) == "switched"
    assert store.lookup("T2", "U1", now=3000) == (None, "none")      # boshqa ish maydoni - boshqa odam
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert "U1" in path.read_text() and "token" not in path.read_text()

    # `touch` diskka soatda bir marta yozadi va uzilgan ulanishni TIRILTIRMAYDI.
    assert store.touch("T1", "U1", 3, now=3060) and store.lookup("T1", "U1", now=3060)[0].seen_at == 3000
    assert store.touch("T1", "U1", 3, now=7000) and store.lookup("T1", "U1", now=7000)[0].seen_at == 7000
    assert not store.touch("T1", "U1", 2, now=7000)                   # boshqa hisob
    expired = 7000 + 31 * 86400
    assert store.lookup("T1", "U1", now=expired) == (None, "expired")
    assert not store.touch("T1", "U1", 3, now=expired)
    assert store.link("T1", "U1", 3, now=expired) == "new"

    assert LinkStore(path).lookup("T1", "U1", now=expired)[0].actor_id == 3   # diskdan
    assert store.by_actor(3)[0].user_id == "U1" and store.count(now=expired) == 1
    assert store.unlink("T1", "U1", actor_id=2) is False
    assert store.unlink_actor(3) == 1 and store.lookup("T1", "U1", now=expired) == (None, "none")
    assert not store.touch("T1", "U1", 3, now=expired)
