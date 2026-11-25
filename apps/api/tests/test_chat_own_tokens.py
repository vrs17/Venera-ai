"""Odam nomidan FAQAT uning o'z HRM/CRM ulanishi (2026-11-25, ega qarori; `CHAT_SHARED_TOKENS`).

Holat: Google Play sharhlovchisining demo hisobi (mahalliy kirish, BRB-Tech ID yo'q - o'z
ulanishi yo'q) har savolda `auth_expired` olardi: chat unga `.env` dagi eskirgan umumiy HRM
tokenini yuborardi. Token ishlagan paytda esa begona hisob kompaniyaning HRM/CRM
ma'lumotini ko'rardi. Endi ulanmagan hisobga hech qanday token ketmaydi.
"""

from __future__ import annotations

from app.core.config import settings
from tests.test_assistant_v4 import (  # noqa: F401 - fiksturalar
    DEMO_ID,
    _fresh_cache,
    agent,
    db,
    grant,
    wired,
)


def _ask(client, headers):
    return client.post("/api/v1/chat/stream", headers={**headers, "X-Venera-Client": "mobile"},
                       json={"question": "Ta'tilim qancha qoldi?"})


def test_ulanmagan_hisobga_umumiy_token_ketmaydi(wired, client, user_auth, agent, db, monkeypatch):
    monkeypatch.setattr(wired, "platform_tokens", lambda: {"hrm": "eskirgan-umumiy", "crm": "umumiy"})
    grant(db, DEMO_ID, ["v4"], "v4")
    assert _ask(client, user_auth).status_code == 200
    [sent] = agent.streams()
    assert "tokens" not in sent["body"]                    # agent halol `auth_missing` beradi


def test_kalit_yoqilsa_eski_xulq(wired, client, user_auth, agent, db, monkeypatch):
    monkeypatch.setattr(settings, "chat_shared_tokens", True)
    monkeypatch.setattr(wired, "platform_tokens", lambda: {"hrm": "umumiy"})
    grant(db, DEMO_ID, ["v4"], "v4")
    assert _ask(client, user_auth).status_code == 200
    [sent] = agent.streams()
    assert sent["body"]["tokens"] == {"hrm": "umumiy"}
