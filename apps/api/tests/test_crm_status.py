"""Brifdagi vazifalarning CRM holati - Venera AI agenti orqali (`app/bot/crm_status.py`)."""

from __future__ import annotations

import json

from types import SimpleNamespace

import pytest

from app.bot import crm_status
from app.bot.briefs import BriefService, apply_crm, period_for
from app.bot.crm_status import QUESTION_MAX, CrmChecker, map_status
from app.services.integrations.ollama import OllamaError
from tests.test_bot_briefs import G1, G2, NOW, T1, T2, make_world, seed

USER = SimpleNamespace(actorId=7, roles=["ADMIN"], email="a@b.uz")
CRM_SOURCE = [{"kind": "crm", "tool": "crm_issue_search", "status": "ok", "digest": "2 ta vazifa"}]


class Agent:
    """Venera AI agenti o'rnida: savollarni yozib oladi, navbatdagi javobni qaytaradi."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.questions: list[str] = []

    def __call__(self, question, user, timeout):
        self.questions.append(question)
        answer = self.answers.pop(0) if self.answers else {"answer": '{"tasks": []}', "sources": CRM_SOURCE}
        if isinstance(answer, Exception):
            raise answer
        return answer


def tasks(*rows):
    return {"answer": "```json\n" + json.dumps({"tasks": list(rows)}, ensure_ascii=False) + "\n```",
            "sources": CRM_SOURCE, "error": None}


def item(title, *, kind="task", status="open", group=G1, detail="", owner=None, due=None, at=NOW - 3600):
    return {"type": kind, "title": title, "detail": detail, "owner": owner, "requested_by": None,
            "status": status, "due": due, "severity": "medium", "src": [1], "at": at, "first_at": at,
            "group": group}


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


# --- holat so'zlari ---------------------------------------------------------------------------------


@pytest.mark.parametrize("raw, status", [
    ("Bajarildi", "done"), ("Yopilgan", "done"), ("Done", "done"), ("Closed", "done"), ("Выполнено", "done"),
    ("Закрыта", "done"), ("Jarayonda", "in_progress"), ("In Progress", "in_progress"),
    ("Ko'rib chiqishda", "in_progress"), ("В работе", "in_progress"), ("Testing", "in_progress"),
    ("Blocked", "blocked"), ("To'xtatilgan", "blocked"), ("Yangi", "open"), ("Open", "open"),
    ("Новая", "open"), ("Bekor qilingan", "cancelled"), ("Cancelled", "cancelled"),
    ("Bajarilmagan", None), ("Не выполнено", None), ("", None), ("Kutilmoqda", None),
])
def test_crm_holati_bizning_holatlarga(raw, status):
    assert map_status(raw) == status


# --- tekshiruv -------------------------------------------------------------------------------------


def test_crm_da_bajarilgan_vazifa_guruhda_aytilmasa_ham_bajarildi():
    agent = Agent(tasks({"n": 1, "found": True, "key": "DVSIB-120", "title": "Call history fix", "status": "Bajarildi",
                         "assignee": "Kaizen", "due": "2026-10-07", "updated": "2026-10-08"},
                        {"n": 2, "found": True, "key": "DVSIB-121", "title": "Prezentatsiya", "status": "Jarayonda",
                         "assignee": None, "due": None}))
    items = [item("Call history xatosini tuzatish", owner="kaizen", status="in_progress"),
             item("Callmind prezentatsiyasi")]
    report = CrmChecker(agent).check(USER, items, {G1: T1})
    assert (report.checked, report.found, report.note, report.tools) == (2, 2, "", {"crm_issue_search"})
    [question] = agent.questions
    assert len(question) <= QUESTION_MAX
    assert "1) Call history xatosini tuzatish (mas'ul: kaizen; guruh: AI team)" in question
    assert "2) Callmind prezentatsiyasi (guruh: AI team)" in question
    assert "hech narsa yaratma va o'zgartirma" in question
    apply_crm(items)
    assert items[0]["status"] == "done" and items[0]["crm"]["key"] == "DVSIB-120"
    assert items[1]["status"] == "in_progress" and items[1]["crm"]["raw"] == "Jarayonda"


def test_bajarilgan_qaror_uchrashuv_va_sorov_tekshirilmaydi():
    agent = Agent()
    report = CrmChecker(agent).check(USER, [item("Tugagan ish", status="done"), item("Qaror", kind="decision"),
                                            item("Bank bilan uchrashuv", kind="deadline"),
                                            item("DWH ga o'tishni ko'rib chiqish", kind="management_request")])
    assert report.checked == 0 and agent.questions == []


def test_guruh_muhokamasidan_oldin_yopilgan_vazifa_boshqa_vazifa():
    # "Dashboard tekshirish" ~ "DVSIB-6 Dashboard ko'rsatish (Done, 2026-05-02)" - noto'g'ri moslik.
    agent = Agent(tasks({"n": 1, "found": True, "key": "DVSIB-6", "status": "Done", "updated": "2026-05-02"}))
    items = [item("Dashboard ma'lumotlarini tekshirish", status="in_progress")]
    report = CrmChecker(agent).check(USER, items)
    assert (report.found, report.rejected) == (0, 1) and "crm" not in items[0]
    assert "Bitta umumiy so'z" in agent.questions[0] and '"updated"' in agent.questions[0]


def test_yopilgan_sanasi_aytilmasa_faqat_korsatiladi():
    agent = Agent(tasks({"n": 1, "found": True, "key": "DVSIB-8", "status": "Done"}))
    items = [item("Hisobot", status="in_progress")]
    report = CrmChecker(agent).check(USER, items)
    assert report.found == 1 and items[0]["crm"]["status"] is None and items[0]["crm"]["raw"] == "Done"
    apply_crm(items)
    assert items[0]["status"] == "in_progress"                       # "Bajarildi" ga o'tmaydi


def test_agent_crm_ni_oqimasa_javob_ishlatilmaydi():
    answer = tasks({"n": 1, "found": True, "key": "DVSIB-1", "status": "Bajarildi"})
    answer["sources"] = [{"kind": "doc", "status": "ok"}]
    items = [item("Hisobot")]
    checker = CrmChecker(Agent(answer))
    report = checker.check(USER, items)
    assert report.found == 0 and "CRM ni o'qimadi" in report.note and "crm" not in items[0]


def test_crm_ulanmagan_izohi():
    items = [item("Hisobot")]
    report = CrmChecker(Agent({"answer": "", "sources": [], "error": {"code": "auth_missing"}})).check(USER, items)
    assert report.found == 0 and report.note.startswith("CRM ulanmagan")


def test_guruhda_aytilgan_kalit_boshqa_bolsa_rad_etiladi():
    agent = Agent(tasks({"n": 1, "found": True, "key": "DVSIB-999", "status": "Bajarildi"},
                        {"n": 2, "found": False}))
    items = [item("DVSIB-120 hisobotini yuborish"), item("Server yangilash")]
    report = CrmChecker(agent).check(USER, items)
    assert report.found == 0 and all("crm" not in i for i in items)
    assert "kalit: DVSIB-120" in agent.questions[0]


def test_matnli_javob_ollamada_jsonga_ogiriladi():
    class Writer:
        def __init__(self):
            self.calls = []

        def complete(self, system, user, **kwargs):
            self.calls.append((user, kwargs))
            return '{"tasks": [{"n": 1, "found": true, "key": "DVSIB-5", "status": "Yopilgan", "updated": "2026-10-08"}]}'

    writer = Writer()
    prose = {"answer": "DVSIB-5 vazifasi yopilgan.", "sources": CRM_SOURCE, "error": None}
    items = [item("Hisobot")]
    report = CrmChecker(Agent(prose), writer=writer).check(USER, items)
    assert report.found == 1 and items[0]["crm"]["status"] == "done"
    [(prompt, kwargs)] = writer.calls
    assert "DVSIB-5 vazifasi yopilgan." in prompt and kwargs["op"] == "brief_crm"


def test_matnli_javob_ogirilmasa_tekshiruv_bolmadi():
    class Broken:
        def complete(self, *args, **kwargs):
            raise OllamaError("down")

    prose = {"answer": "Topa olmadim", "sources": CRM_SOURCE, "error": None}
    report = CrmChecker(Agent(prose), writer=Broken()).check(USER, [item("Hisobot")])
    assert report.found == 0 and report.note == "CRM tekshiruvi bo'lmadi"


def test_kesh_15_daqiqa_topilmagani_ham():
    clock = Clock()
    agent = Agent(tasks({"n": 1, "found": True, "key": "DVSIB-1", "status": "Jarayonda"}, {"n": 2, "found": False}))
    checker = CrmChecker(agent, clock=clock)
    checker.check(USER, [item("Bir"), item("Ikki")])
    again = [item("Bir"), item("Ikki")]
    report = checker.check(USER, again)
    assert len(agent.questions) == 1 and report.found == 1 and again[0]["crm"]["key"] == "DVSIB-1"
    # Boshqa rahbar - o'z CRM huquqi bilan, alohida so'raladi.
    checker.check(SimpleNamespace(actorId=8, roles=[], email=""), [item("Bir")])
    assert len(agent.questions) == 2
    clock.now += 901
    checker.check(USER, [item("Bir"), item("Ikki")])
    assert len(agent.questions) == 3


def test_kop_vazifa_bolib_soraladi_va_chegara_saqlanadi():
    agent = Agent()
    long = "x" * 300
    items = [item(f"Vazifa {n}", detail=f"{long} {n}") for n in range(25)]
    report = CrmChecker(agent).check(USER, items)
    assert report.checked == 20                                     # bitta brifda eng ko'pi
    assert len(agent.questions) >= 3 and all(len(q) <= QUESTION_MAX for q in agent.questions)
    assert sum(q.count("\n") for q in agent.questions) >= 20


def test_agent_yiqilsa_izoh():
    report = CrmChecker(Agent(RuntimeError("upstream"))).check(USER, [item("Hisobot")])
    assert report.found == 0 and report.note == "CRM tekshiruvi bo'lmadi"


# --- brifda ----------------------------------------------------------------------------------------


def test_brifda_crm_holati_va_bajarildi(tmp_path):
    w = make_world(tmp_path, roles=("ADMIN",))
    seed(w)
    agent = Agent(tasks({"n": 1, "found": True, "key": "OPS-7", "title": "SSH keys", "status": "Done",
                         "updated": "2026-10-08"},
                        {"n": 2, "found": True, "key": "CR-12", "title": "Kredit qoldig'i", "status": "Jarayonda",
                         "assignee": "Yusufxon"}))
    checker = CrmChecker(agent)
    brief = w.engine.brief([(G1, T1), (G2, T2)], period_for("7d", NOW), all_mode=True,
                           crm=lambda items, titles: checker.check(USER, items, titles))
    text = brief.parts[0]
    assert "<i>🗂 CRM: 2/2 vazifa topildi</i>" in text
    # Muddati o'tgan SSH vazifasi CRM da bajarilgan - "Diqqat" dan "Bajarildi" ga.
    done = text.split("🟢 <b>Bajarildi</b>\n")[1].split("\n\n")[0]
    assert "• SSH kalitlarini yangilash · 🗂 OPS-7: Done · <i>Kredit loyihasi</i>" in done
    assert "SSH kalitlarini" not in text.split("🟢 <b>Bajarildi</b>")[0]
    assert "• Kredit qoldig'i hisobi · 📅 10-oktyabr · 🗂 CR-12: Jarayonda · <i>AI team</i>" in text
    assert "guruh: Kredit loyihasi" in agent.questions[0] and "guruh: AI team" in agent.questions[0]


def test_brif_crm_xatosida_ham_chiqadi(tmp_path):
    w = make_world(tmp_path, roles=("ADMIN",))
    seed(w)

    def broken(items, titles):
        raise RuntimeError("boom")

    brief = w.engine.brief([(G1, T1), (G2, T2)], period_for("7d", NOW), all_mode=True, crm=broken)
    assert "<i>🗂 CRM tekshiruvi bo'lmadi</i>" in brief.parts[0]
    assert "🔴 muddat o'tdi (8-oktyabr, 12:00) — bajarilgani haqida xabar yo'q" in brief.parts[0]


def test_xizmat_rahbar_nomidan_tekshiradi(tmp_path):
    w = make_world(tmp_path, roles=("ADMIN",))
    seed(w)
    seen = []

    class Checker:
        def check(self, user, items, titles):
            seen.append((user.actorId, len(items), sorted(titles)))
            return crm_status.CrmReport()

    service = BriefService(w.tg, w.engine, groups=lambda: frozenset(w.allowed), logins=lambda: frozenset(),
                           inline=True, clock=lambda: w.clock[0], crm=Checker())
    user = SimpleNamespace(actorId=1, roles=["ADMIN"], email="a@b.uz")
    service._start_brief(555, user, "all", "7d", cq_id=None, edit_id=None)
    assert seen == [(1, 5, sorted([G1, G2]))]
    holder = [c for c in w.tg.calls if c[0] == "send_message"][0][1]["text"]
    assert "CRM da tekshirilmoqda" in holder


# --- agentga savol -----------------------------------------------------------------------------------


class Stream:
    def __init__(self, frames):
        self.frames = iter(json.dumps(f).encode() + b"\n" for f in frames)
        self.closed = False

    def close(self):
        self.closed = True


def test_agent_savoli_alohida_user_id_va_odam_tokenlari(monkeypatch):
    from app.api.v1 import chat

    calls = []
    stream = Stream([{"type": "stage", "text": "CRM"}, {"type": "sources", "sources": CRM_SOURCE},
                     {"type": "proposal", "token": "t"}, {"type": "token", "text": '{"tasks": '},
                     {"type": "token", "text": "[]}"}, {"type": "done"}])

    class Assistant:
        def stream(self, question, **kwargs):
            calls.append((question, kwargs))
            return stream

    monkeypatch.setattr(chat, "_assistant", Assistant())
    monkeypatch.setattr(chat, "_live_tokens", lambda user: {"crm": "own-token", "hrm": "h"})
    monkeypatch.setattr(chat, "effective_engine", lambda user, channel, requested=None: "v2")
    reply = crm_status.agent_ask("savol", USER, 30)
    assert reply == {"answer": '{"tasks": []}', "sources": CRM_SOURCE, "error": None}
    [(question, kwargs)] = calls
    assert kwargs["user_id"] == "venera-brief:7" and kwargs["tokens"]["crm"] == "own-token"
    assert kwargs["engine"] == "v2" and stream.closed


def test_crm_tokeni_yoq_bolsa_agentga_borilmaydi(monkeypatch):
    from app.api.v1 import chat

    class Assistant:
        def stream(self, *args, **kwargs):
            raise AssertionError("chaqirilmasligi kerak")

    monkeypatch.setattr(chat, "_assistant", Assistant())
    monkeypatch.setattr(chat, "_live_tokens", lambda user: {"hrm": "h"})
    assert crm_status.agent_ask("savol", USER, 30)["error"] == {"code": "auth_missing"}
