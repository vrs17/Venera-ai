"""Miya flag'lari (`engine_control`) va yo'naltirish (`services/brain/routing.py`).

Tekshiriladi: default'lar bugungi xulq (`local`); tartib admin -> `.env` -> `local`;
admin API (422, 403, audit); capability guard sabablari; imkoniyatlar keshi so'rovni
kuttirmaydi; jonli `.env` o'qish; sxema v4 migratsiyasi. Tarmoqqa chiqilmaydi.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time

import pytest

from app.core import config as config_module
from app.core.config import agent_v4_enabled_now, brain_engine_now, hold_classifier_now, platforms_now, settings
from app.schemas.auth import AuthUser
from app.services import engine_control as control
from app.services.admin_users import AdminError
from app.services.analytics.db import MIGRATIONS, SCHEMA_VERSION, Database
from app.services.brain import routing
from app.services.brain.routing import CapabilityCache
from tests.agent_fakes import FULL_CAPS, FakeAgent, caps_without, enable_agent

ADMIN = AuthUser(actorId=1, actorType="EMPLOYEE", email="admin@venera.uz", fullName="Administrator",
                 roles=["ADMIN"])


# ================================================================ default va tartib


def test_hamma_funksiya_default_local_va_agent_ochiq(_isolated_analytics):
    assert set(control.BRAIN_FEATURES) == {"group_summary", "group_ask", "brief_extract", "brief_crm",
                                           "meeting_summary", "meeting_ask", "hold_classify", "group_crm",
                                           "meeting_crm"}
    for feature in control.BRAIN_FEATURES:
        route = routing.route(feature)
        assert (route.configured, route.effective, route.reason) == ("local", "local", None)
    # Hold - `keyword` (reja W0.5): ovozli savol tashqariga chiqmaydi; qaytarish `HOLD_CLASSIFIER=llm`.
    assert settings.agent_v4_enabled is False and settings.hold_classifier == "keyword"


def test_14_op_hammasi_bitta_funksiyada():
    ops = {"classify", "group_summary", "group_ask", "brief_extract", "brief_extract_support",
           "brief_project", "brief_headline", "brief_crm", "meeting_classify", "meeting_extract",
           "meeting_map", "meeting_write", "meeting_verify", "meeting_ask"}
    assert set(control.BRAIN_OP_FEATURE) == ops


def test_tartib_admin_env_default(_isolated_analytics, monkeypatch):
    monkeypatch.setattr(settings, "group_ask_engine", "shadow")
    choice = control.brain_choice("group_ask")
    assert (choice.state, choice.source, choice.sample_rate) == ("shadow", "env", 0.2)
    control.put_brain(ADMIN, "group_ask", state="agent", sample_rate=0.5, db=_isolated_analytics)
    choice = control.brain_choice("group_ask")
    assert (choice.state, choice.source, choice.sample_rate) == ("agent", "admin", 0.5)
    # `state: None` - admin qarori olib tashlanadi, yana `.env`.
    control.put_brain(ADMIN, "group_ask", state=None, db=_isolated_analytics)
    assert control.brain_choice("group_ask").source == "env"
    # Noto'g'ri `.env` qiymati (masalan dvigatel nomi) - `local`.
    monkeypatch.setattr(settings, "group_ask_engine", "v3")
    assert (control.brain_choice("group_ask").state, control.brain_choice("group_ask").source) == (
        "local", "default")
    assert control.brain_choice("nomalum").state == "local"


def test_admin_yozuvi_audit_va_takror_audit_yozmaydi(_isolated_analytics):
    db = _isolated_analytics
    control.put_brain(ADMIN, "brief_extract", state="shadow", note="W2 sinov", db=db)
    control.put_brain(ADMIN, "brief_extract", state="shadow", db=db)          # o'zgarish yo'q
    control.put_brain(ADMIN, "brief_extract", sample_rate=1.0, db=db)         # holat saqlanadi
    rows = db.rows("SELECT action, target_type, target_id, detail FROM audit_log ORDER BY id")
    assert [(r["action"], r["target_type"], r["target_id"]) for r in rows] == [
        ("feature.state", "feature", "brief_extract"), ("feature.state", "feature", "brief_extract")]
    assert json.loads(rows[1]["detail"]) == {"from": {"state": "shadow", "sampleRate": None},
                                             "to": {"state": "shadow", "sampleRate": 1.0}}
    [row] = db.rows("SELECT * FROM brain_routing")
    assert (row["state"], row["sample_rate"], row["note"]) == ("shadow", 1.0, "W2 sinov")


@pytest.mark.parametrize("kwargs, code", [
    ({"state": "v3"}, "UNKNOWN_STATE"),
    ({"state": "shadow", "sample_rate": 1.5}, "BAD_SAMPLE_RATE"),
    ({"sample_rate": 0.5}, "STATE_REQUIRED"),
])
def test_admin_tekshiruv(_isolated_analytics, kwargs, code):
    with pytest.raises(AdminError) as info:
        control.put_brain(ADMIN, "group_summary", db=_isolated_analytics, **kwargs)
    assert info.value.status == 422 and info.value.code == code
    assert _isolated_analytics.rows("SELECT * FROM brain_routing") == []
    with pytest.raises(AdminError):
        control.put_brain(ADMIN, "ollama", state="local", db=_isolated_analytics)


def test_buzuq_qator_va_jadval_yoq_bolsa_dvigatel_buzilmaydi(_isolated_analytics):
    db = _isolated_analytics
    db.execute("INSERT INTO brain_routing (feature, state) VALUES ('group_ask', 'ollama')")
    db.execute("INSERT INTO engine_policy (key, value) VALUES ('default', 'v1')")
    data = control.load(db)
    assert dict(data.brain) == {} and dict(data.policy) == {"default": "v1"}
    db.execute("DROP TABLE brain_routing")
    data = control.load(db)
    assert dict(data.policy) == {"default": "v1"} and dict(data.brain) == {}


# ================================================================ capability guard


def test_guard_sabablari(_isolated_analytics, monkeypatch):
    monkeypatch.setattr(settings, "group_summary_engine", "agent")
    assert routing.route("group_summary").reason == "agent_disabled"
    monkeypatch.setattr(settings, "agent_v4_enabled", True)
    monkeypatch.setattr(settings, "hrm_assistant_client_id", "")
    monkeypatch.setattr(settings, "hrm_assistant_client_secret", "")
    routing.reset_for_tests()
    # Kredensial yo'q (testda `HRM_ASSISTANT_CLIENT_ID` bo'sh) - tarmoqqa chiqilmaydi.
    assert routing.route("group_summary").reason == "agent_not_configured"
    fake = FakeAgent()
    routing.reset_for_tests(interactive=fake.client())
    routing.capabilities().prime(None)
    routing.capabilities().background = True
    # Kesh bo'sh: javob DARHOL `local`, yangilash fonda.
    assert routing.route("group_summary").reason == "capabilities_unknown"
    enable_agent(monkeypatch, fake, caps={**FULL_CAPS, "in_network_models_only": False})
    assert routing.route("group_summary").reason == "not_in_network"
    enable_agent(monkeypatch, fake, caps=caps_without("instructions_mode"))
    route = routing.route("group_summary")
    assert (route.configured, route.effective, route.reason) == (
        "agent", "local", "capability_missing:instructions_mode")
    enable_agent(monkeypatch, fake)
    route = routing.route("group_summary")
    assert (route.effective, route.reason, route.agent) == ("agent", None, True)


def test_shadow_uchun_shadow_imkoniyati_kerak(_isolated_analytics, monkeypatch):
    enable_agent(monkeypatch, FakeAgent(), caps=caps_without("shadow"), group_ask="shadow", brief_crm="agent")
    assert routing.route("group_ask").reason == "capability_missing:shadow"
    assert routing.route("brief_crm").effective == "agent"       # agent holatiga `shadow` kerak emas
    enable_agent(monkeypatch, FakeAgent(), caps=caps_without("frames:route"), hold_classify="agent")
    assert routing.route("hold_classify").reason == "capability_missing:frames:route"


def test_bosh_kalit_hammasini_qaytaradi(_isolated_analytics, monkeypatch):
    enable_agent(monkeypatch, FakeAgent(), group_summary="agent", meeting_ask="shadow")
    assert routing.route("group_summary").agent and routing.route("meeting_ask").shadow
    monkeypatch.setattr(settings, "agent_v4_enabled", False)
    assert routing.route("group_summary").local and routing.route("meeting_ask").local


def test_imkoniyatlar_keshi_sorovni_kuttirmaydi():
    started, release = threading.Event(), threading.Event()

    def slow_fetch():
        started.set()
        release.wait(5)
        return FULL_CAPS

    cache = CapabilityCache(slow_fetch, ttl=300)
    began = time.monotonic()
    assert cache.get() is None                                   # darhol, fetch fonda
    assert time.monotonic() - began < 0.5
    assert started.wait(5)
    assert cache.get() is None                                   # ikkinchi fetch boshlanmaydi
    release.set()
    for _ in range(200):
        if cache.get() is not None:
            break
        time.sleep(0.01)
    assert cache.get().has("complete") and cache.get().has("frames:route")


def test_kesh_xatoda_oxirgi_yaxshi_qiymatni_saqlaydi():
    now = [0.0]
    answers = [FULL_CAPS, RuntimeError("agent o'chiq")]

    def fetch():
        item = answers.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    cache = CapabilityCache(fetch, ttl=10, error_ttl=5, clock=lambda: now[0], background=False)
    assert cache.get().has("complete")
    now[0] = 11.0
    assert cache.get().has("complete")                           # xato - lekin oxirgi yaxshisi
    assert cache.state()["error"] == "RuntimeError"


# ================================================================ jonli .env


def test_jonli_env_oqish(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("AGENT_V4_ENABLED=true\nHOLD_CLASSIFIER=keyword\nGROUP_ASK_ENGINE=Shadow\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "_ENV_FILE", env)
    monkeypatch.setattr(config_module, "_token_cache", {})
    assert agent_v4_enabled_now() is True
    assert hold_classifier_now() == "keyword"
    assert brain_engine_now("group_ask") == "shadow"
    assert brain_engine_now("group_summary") == "local"            # kalit yo'q - sozlama obyekti
    # Restartsiz qaytarish; tanilmagan qiymat - `keyword` (egress to'xtatish niyatini buzmaydi).
    time.sleep(0.01)
    env.write_text("AGENT_V4_ENABLED=false\nHOLD_CLASSIFIER=keywords\n", encoding="utf-8")
    assert agent_v4_enabled_now() is False
    assert hold_classifier_now() == "keyword"
    env.write_text("HOLD_CLASSIFIER=llm\n# bo'sh\n", encoding="utf-8")
    assert hold_classifier_now() == "llm"
    time.sleep(0.01)
    env.write_text("# kalit yo'q\n", encoding="utf-8")
    assert hold_classifier_now() == "keyword"                     # koddagi default (reja W0.5)


def test_maxfiylik_qaytarish_kalitlari_jonli(tmp_path, monkeypatch):
    """`MEETINGS_ASK_PLATFORMS` / `BRIEF_CRM_PLATFORMS` - `.env` dan jonli, default faqat `crm`."""
    env = tmp_path / ".env"
    env.write_text("# bo'sh\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "_ENV_FILE", env)
    monkeypatch.setattr(config_module, "_token_cache", {})
    assert platforms_now("meetings_ask_platforms") == frozenset({"crm"})
    assert platforms_now("brief_crm_platforms") == frozenset({"crm"})
    time.sleep(0.01)
    env.write_text("BRIEF_CRM_PLATFORMS= CRM , hrm \n", encoding="utf-8")
    assert platforms_now("brief_crm_platforms") == frozenset({"crm", "hrm"})
    assert platforms_now("meetings_ask_platforms") == frozenset({"crm"})


# ================================================================ sxema v4


def test_v3_ombor_v4_ga_otadi_malumot_joyida(tmp_path):
    assert SCHEMA_VERSION == 4
    path = tmp_path / "prod" / "venera.db"
    path.parent.mkdir()
    old = sqlite3.connect(str(path), isolation_level=None)
    for step in MIGRATIONS[:3]:
        for statement in step:
            old.execute(statement)
    old.execute("PRAGMA user_version = 3")
    old.execute("INSERT INTO engine_policy (key, value) VALUES ('default', 'v3')")
    old.execute("INSERT INTO api_calls (ts, service, op, status, duration_ms) VALUES (1, 'ollama', 'classify', "
                "'ok', 700)")
    old.close()
    database = Database(path)
    try:
        assert database.version() == 4
        assert [r["name"] for r in database.rows("PRAGMA table_info(brain_routing)")] == [
            "feature", "state", "sample_rate", "note", "updated_at", "updated_by"]
        assert "similarity" in {r["name"] for r in database.rows("PRAGMA table_info(shadow_results)")}
        assert dict(control.load(database).policy) == {"default": "v3"}
        assert database.scalar("SELECT COUNT(*) FROM api_calls") == 1
    finally:
        database.close_all()


# ================================================================ admin API


def test_admin_api(client, auth, user_auth, _isolated_analytics):
    body = client.get("/api/v1/admin/engines/brain", headers=auth).json()
    assert body["states"] == ["local", "shadow", "agent"] and body["holdClassifier"] == "keyword"
    assert {f["feature"]: (f["state"], f["effective"]) for f in body["features"]}["group_ask"] == (
        "local", "local")
    assert body["agent"]["enabled"] is False and body["agent"]["reason"] == "agent_disabled"
    assert body["shadow"]["workers"] == 1

    put = client.put("/api/v1/admin/engines/brain/group_ask", headers=auth,
                     json={"state": "agent", "sampleRate": 0.3, "note": "sinov"})
    assert put.status_code == 200, put.text
    row = {f["feature"]: f for f in put.json()["features"]}["group_ask"]
    # Sozlangan `agent`, lekin bosh kalit o'chiq - ish `local` da (sababi bilan).
    assert (row["state"], row["source"], row["effective"], row["reason"], row["sampleRate"]) == (
        "agent", "admin", "local", "agent_disabled", 0.3)
    assert row["updatedBy"] == "admin@venera.uz" and row["note"] == "sinov"

    bad = client.put("/api/v1/admin/engines/brain/group_ask", headers=auth, json={"state": "turbo"})
    assert bad.status_code == 422
    assert client.put("/api/v1/admin/engines/brain/nomalum", headers=auth,
                      json={"state": "local"}).status_code == 422
    assert client.get("/api/v1/admin/engines/brain", headers=user_auth).status_code == 403
    assert client.put("/api/v1/admin/engines/brain/group_ask", headers=user_auth,
                      json={"state": "local"}).status_code == 403
    [audit] = _isolated_analytics.rows("SELECT action, target_id FROM audit_log WHERE action='feature.state'")
    assert audit == {"action": "feature.state", "target_id": "group_ask"}
