""""Hamma tanlay oladi" (`selectable:<versiya>`, 2026-11-25) - ega: "v4 default, v5 ham mavjud".

Default (`engine_policy.default`) O'ZGARMAYDI: savol yuborgan, hech narsa tanlamagan odam
bugungidek v4 da. Faqat chatdagi versiya tanlovida (`GET /chat/engines` -> `selectable`,
`available`) v5 ham chiqadi va odam uni o'zi tanlasa (`/chat/stream` dagi `engine`) - v5.
"""

from __future__ import annotations

import pytest

from app.services import engine_control as control
from tests.test_engine_control import (  # noqa: F401 - fiksturalar
    _fresh_cache,
    api,
    audit,
    db,
    grant,
    person,
    policy,
    put_policy_row,
    upstream,
    wired,
)


def everyone_v4_and_v5(db) -> None:
    policy(db, default="v4", refresh=False)
    put_policy_row(db, "selectable:v5", "v5")
    control.invalidate()


def test_default_qoladi_tanlov_qoshiladi(db):
    everyone_v4_and_v5(db)
    choice = control.resolve(person(7), "web")
    assert (choice.engine, choice.source) == ("v4", "default")
    assert choice.available == ("v4", "v5") and choice.selectable
    # Odam tanlasa - v5; tanlamasa yoki boshqasini so'rasa - v4.
    assert control.resolve(person(7), "web", "v5").engine == "v5"
    assert control.resolve(person(7), "web", "v3").engine == "v4"
    assert control.resolve(person(7), "web", "v3").ignored


def test_tanlovsiz_hamma_bugungidek(db):
    policy(db, default="v4")
    choice = control.resolve(person(7), "web", "v5")
    assert (choice.engine, choice.available, choice.selectable) == ("v4", ("v4",), False)


def test_alohida_ruxsatli_odam_ham_korad_lekin_defaulti_ozi(db):
    everyone_v4_and_v5(db)
    grant(db, 7, ["v3"])
    choice = control.resolve(person(7), "web")
    assert choice.engine == "v3"                      # o'z ro'yxatidan bitta - o'sha
    assert choice.available == ("v3", "v5") and choice.selectable
    assert control.resolve(person(7), "web", "v5").engine == "v5"


def test_kalit_qiymati_mos_bolmasa_etiborsiz(db):
    policy(db, default="v4", refresh=False)
    put_policy_row(db, "selectable:v5", "v3")
    control.invalidate()
    assert control.resolve(person(7), "web").available == ("v4",)


def test_admin_api_tanlov_royxati_va_audit(api, auth, db):
    policy(db, default="v4")
    body = api.put("/api/v1/admin/engines/policy", headers=auth, json={"selectable": ["v5"]}).json()
    assert body["policy"]["selectable"] == ["v5"]
    assert body["policy"]["default"] == "v4"
    assert body["effective"]["web"] == "v4"           # hech kim ko'chmadi
    rows = audit(db)
    assert rows[-1]["detail"]["from"]["selectable"] == [] and rows[-1]["detail"]["to"]["selectable"] == ["v5"]
    # Odam tomonida: tanlov ko'rinadi.
    engines = api.get("/api/v1/chat/engines", headers=auth).json()
    assert engines["current"] == "v4" and engines["selectable"] is True
    assert engines["available"] == ["v4", "v5"]
    # Olib tashlash - `[]`.
    body = api.put("/api/v1/admin/engines/policy", headers=auth, json={"selectable": []}).json()
    assert body["policy"]["selectable"] == []
    assert api.get("/api/v1/chat/engines", headers=auth).json()["selectable"] is False
    # `selectable` yuborilmasa - o'zgarmaydi.
    api.put("/api/v1/admin/engines/policy", headers=auth, json={"selectable": ["v5"]})
    body = api.put("/api/v1/admin/engines/policy", headers=auth, json={"default": "v4"}).json()
    assert body["policy"]["selectable"] == ["v5"]


@pytest.mark.parametrize("value", [["v9"], ["legacy"], [""], "v5"])
def test_admin_api_notogri_tanlov_422(api, auth, db, value):
    response = api.put("/api/v1/admin/engines/policy", headers=auth, json={"selectable": value})
    assert response.status_code == 422, response.text
    assert db.rows("SELECT * FROM engine_policy WHERE key LIKE 'selectable:%'") == []


def test_chat_oqimi_tanlangan_v5_ga_tanlanmagani_v4_ga(api, auth, upstream, db):
    everyone_v4_and_v5(db)
    picked = api.post("/api/v1/chat/stream", headers={**auth, "X-Venera-Client": "web"},
                      json={"question": "savol", "engine": "v5"})
    plain = api.post("/api/v1/chat/stream", headers={**auth, "X-Venera-Client": "web"},
                     json={"question": "savol"})
    assert picked.status_code == plain.status_code == 200
    assert upstream.paths()[-2:] == ["/api/v5/chat/stream", "/api/v4/chat/stream"]
