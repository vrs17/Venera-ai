"""`scripts/purge_legacy_group_crm.py`: eski (prefiksisiz) guruh CRM suhbatlarini topadi va
faqat `--apply` da o'chiradi; shaxsiy suhbatlarga tegmaydi; chiqishda faqat sonlar.
Agent soxta - tarmoqqa chiqilmaydi."""

from __future__ import annotations

import importlib.util
import json

from pathlib import Path

from app.api.v1 import chat as chat_api
from app.services.analytics.db import Database
from app.services.integrations.assistant import AssistantError
from app.services.telegram_links import LinkStore

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "purge_legacy_group_crm.py"
HEAD = "[Telegram ish guruhi «AI team». Javobingiz guruhdagi HAMMAGA ko'rinadi ...]\nSo'rov: crmga kiritib qo'y"


def _module():
    spec = importlib.util.spec_from_file_location("purge_legacy_group_crm", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeAssistant:
    def __init__(self, chats: dict[str, dict[str, list[dict]]]) -> None:
        self.chats = chats                     # user_id -> chat_id -> messages
        self.deleted: list[tuple[str, str]] = []
        self.broken: set[str] = set()

    def list_chats(self, *, user_id, limit=50, offset=0):
        ids = list(self.chats.get(user_id, {}))
        return {"items": [{"chat_id": c, "title": "t"} for c in ids[offset:offset + limit]], "limit": limit,
                "offset": offset}

    def get_chat(self, chat_id, *, user_id, limit=200):
        if chat_id in self.broken:
            raise AssistantError("yo'q", status=404)
        return {"chat_id": chat_id, "messages": self.chats[user_id][chat_id][-limit:]}

    def delete_chat(self, chat_id, *, user_id):
        self.deleted.append((chat_id, user_id))
        return {"chat_id": chat_id, "status": "deleted"}


def _msgs(*user_texts: str) -> list[dict]:
    out = []
    for text in user_texts:
        out += [{"role": "user", "content": text}, {"role": "assistant", "content": "javob"}]
    return out


def _world() -> FakeAssistant:
    return FakeAssistant({
        "venera:1": {
            "old-group": _msgs(HEAD, HEAD + " davomi"),
            "personal": _msgs("Ta'tilim qancha qoldi?"),
            "mixed": _msgs("Salom", HEAD),                      # odam belgini bir marta yozgan - tegilmaydi
            "tgcrm-new": _msgs(HEAD),                           # yangi - tozalovchiniki
        },
        "venera:2": {"old-2": _msgs(HEAD)},
    })


def test_dry_run_sanaydi_ochirmaydi():
    module, fake = _module(), _world()
    counts = module.run(fake, {1, 2}, apply=False, page=2)
    assert counts == {"actors": 2, "chats": 5, "new": 1, "found": 2, "deleted": 0, "errors": 0}
    assert fake.deleted == []


def test_apply_faqat_eski_guruh_suhbatlarini_ochiradi():
    module, fake = _module(), _world()
    fake.broken.add("personal")
    counts = module.run(fake, [2, 1, 1], apply=True, page=2)
    assert sorted(fake.deleted) == [("old-2", "venera:2"), ("old-group", "venera:1")]
    assert counts["deleted"] == 2 and counts["errors"] == 1


def test_kimlik_chat_bilan_bir_xil():
    from types import SimpleNamespace

    assert _module().user_id(42) == chat_api.assistant_user_id(SimpleNamespace(actorId=42))


def test_odamlar_ulanishlar_va_analyticsdan(tmp_path):
    module = _module()
    links = LinkStore(tmp_path / "links.json")
    links.link(111, 1)
    links.link(222, 3)
    db_path = tmp_path / "venera.db"
    db = Database(db_path)
    with db.transaction() as conn:
        for actor, channel in ((3, "bot"), (4, "bot"), (5, "web")):
            conn.execute("INSERT INTO turns (id, actor_id, channel, kind, started_at, status, question)"
                         " VALUES (?,?,?,?,?,?,?)", (f"t{actor}", actor, channel, "chat", 1.0, "ok", "q"))
    before = db_path.read_bytes()
    assert module.actors_from_links(tmp_path / "links.json") == {1, 3}
    assert module.actors_from_analytics(db_path) == {3, 4}
    assert db_path.read_bytes() == before                             # ombor faqat o'qildi
    assert module.actors_from_links(tmp_path / "yoq.json") == set()
    assert module.actors_from_analytics(tmp_path / "yoq.db") == set()


def test_main_sozlanmagan_agent_bilan_hech_narsa_qilmaydi(tmp_path, capsys, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "hrm_assistant_client_id", "", raising=False)
    assert _module().main(["--links", str(tmp_path / "l.json"), "--analytics", str(tmp_path / "a.db")]) == 2
    assert "sozlanmagan" in capsys.readouterr().err


def test_main_chiqishda_faqat_sonlar(tmp_path, capsys, monkeypatch):
    from app.core.config import settings
    from app.services.integrations import assistant as assistant_module

    fake = _world()
    module = _module()
    monkeypatch.setattr(assistant_module, "AssistantClient", lambda *a, **k: fake)
    fake.configured = True
    monkeypatch.setattr(settings, "hrm_assistant_client_id", "id", raising=False)
    (tmp_path / "l.json").write_text(json.dumps({"links": {"111": {"actor_id": 1}, "222": {"actor_id": 2}}}),
                                     encoding="utf-8")
    assert module.main(["--json", "--links", str(tmp_path / "l.json"), "--analytics", str(tmp_path / "a.db")]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"actors": 2, "chats": 5, "new": 1, "found": 2, "deleted": 0, "errors": 0, "apply": 0}
    assert fake.deleted == []
