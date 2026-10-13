"""Admin "Tizim xaritasi": xarita ma'lumoti va jonli sinovlar (`admin_osmap.py`, `admin_probe.py`).

Asosiy kafolatlar:
  * hamma yo'l FAQAT ADMIN (oddiy xodimga 403, tokensiz 401);
  * sinov ishlab chiqarish kodini chaqiradi: `tts-text` ning yakuniy matni `/tts/speak`
    TTS serveriga AYNAN yuborgan matn bilan bir xil;
  * miya funksiyasi DRY rejimda prompt chizadi, model, Telegram va jonli ombor
    chaqirilmaydi; yon ta'sirsiz qilib bo'lmaydigan funksiyada `execute` - 409.
Tashqi xizmat chaqirilmaydi.
"""

from __future__ import annotations

import io
import json
import urllib.request

import pytest

from app.core.config import settings
from app.services.stt import Transcript
from app.services.tts import TtsClient

API = "/api/v1/admin"


def _audit(db) -> list[dict]:
    rows = db.rows("SELECT action, target_type, target_id, detail FROM audit_log ORDER BY id")
    for row in rows:
        row["detail"] = json.loads(row["detail"]) if row["detail"] else None
    return rows


def _wav() -> dict:
    return {"file": ("speech.wav", io.BytesIO(b"RIFF" + b"\0" * 4000), "audio/wav")}


# --- huquq --------------------------------------------------------------------------------------

_PROBES = [
    ("get", "/osmap", None),
    ("post", "/probe/tts-text", {"json": {"text": "salom"}}),
    ("post", "/probe/wake", {"json": {"text": "salom barno"}}),
    ("post", "/probe/hold", {"json": {"question": "ta'til qachon?"}}),
    ("post", "/probe/mask", {"json": {"text": "+998 90 123 45 67"}}),
    ("get", "/probe/agent", None),
    ("get", "/probe/health", None),
    ("post", "/probe/brain/group_summary", {"json": {"input": "Ali: salom"}}),
    ("post", "/probe/stt", "audio"),
]


@pytest.mark.parametrize("method,path,kwargs", _PROBES)
def test_faqat_admin(client, user_auth, method, path, kwargs):
    """Oddiy xodimga 403, tokensiz 401 - xaritada ichki promptlar, sinovlar esa pullik
    xizmatlarga chiqadi."""
    extra = {"files": _wav(), "data": {"language": "uz"}} if kwargs == "audio" else (kwargs or {})
    response = getattr(client, method)(f"{API}{path}", headers=user_auth, **extra)
    assert response.status_code == 403, (path, response.text)
    extra = {"files": _wav(), "data": {"language": "uz"}} if kwargs == "audio" else (kwargs or {})
    assert getattr(client, method)(f"{API}{path}", **extra).status_code == 401


# --- xarita -------------------------------------------------------------------------------------


def test_osmap_fayl_yoq_404(client, auth, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "osmap_path", tmp_path / "osmap" / "osmap.json", raising=False)
    response = client.get(f"{API}/osmap", headers=auth)
    assert response.status_code == 404
    assert "OSMAP_PATH" in response.json()["message"]


def test_osmap_fayl_bor_200(client, auth, tmp_path, monkeypatch):
    path = tmp_path / "osmap.json"
    data = {"meta": {"snapshot": "sinov"}, "flows": [{"id": "stt", "title": "STT", "nodes": [], "edges": []}]}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(settings, "osmap_path", path, raising=False)
    response = client.get(f"{API}/osmap", headers=auth)
    assert response.status_code == 200
    assert response.json() == data
    # Ichida ichki promptlar - keshga tushmasin.
    assert response.headers["cache-control"] == "no-store"


def test_osmap_buzuq_503(client, auth, tmp_path, monkeypatch):
    path = tmp_path / "osmap.json"
    path.write_text("{yarim", encoding="utf-8")
    monkeypatch.setattr(settings, "osmap_path", path, raising=False)
    assert client.get(f"{API}/osmap", headers=auth).status_code == 503


# --- TTS matni: route bilan AYNI natija ---------------------------------------------------------


class _FakeTts:
    """`/tts/stream` ni yozib boradi va qisqa PCM qaytaradi (`test_tts.FakeServer` ning qisqasi)."""

    def __init__(self) -> None:
        self.streams: list[dict] = []

    def open(self, request, timeout=None):
        path = "/" + request.full_url.split("://", 1)[1].split("/", 1)[1]
        payload = json.loads(request.data) if request.data else None
        if path == "/api/v1/auth/token":
            return _Resp(json.dumps({"access_token": "tok", "expires_in": 86400}).encode())
        if path == "/api/v1/tts/stream":
            self.streams.append(payload)
            return _Resp(b"\0\0" * 400, {"x-sample-rate": "8000", "x-chunk-count": "1", "x-stream-id": "s1"})
        raise AssertionError(path)


class _Resp:
    def __init__(self, data: bytes, headers: dict | None = None) -> None:
        self._data = data
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            data, self._data = self._data, b""
            return data
        data, self._data = self._data[:size], self._data[size:]
        return data

    def close(self) -> None:
        self._data = b""


@pytest.fixture
def tts_server(monkeypatch):
    import app.api.v1.tts as module

    fake = _FakeTts()

    class Opener:
        def open(self, request, timeout=None):
            return fake.open(request, timeout)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **kw: Opener())
    monkeypatch.setattr(module, "_client", TtsClient(
        "http://tts", "frontend", "s3cret", spoken_names=lambda: {"DVSIB": "Data va sun'iy intellekt bo'limi"}))
    return fake


@pytest.mark.parametrize("text", [
    "“BRB-TECH” MChJ 25.09.2026 kuni soat 09:00-18:00 da ishlaydi, DVSIB loyihasi bo'yicha.",
    "Karta: 8600 1234 5678 9012, summa 2450000 so'm, versiya v1.2.3",
    "  Oddiy javob: ta'til 21 kun.  ",
])
def test_tts_text_route_bilan_bir_xil(client, auth, tts_server, text):
    """Sinovning yakuniy matni va normalizator qarori `/tts/speak` TTS serveriga AYNAN
    yuborgan bilan bir xil - sinov nusxa emas, o'sha zanjir (`prepare_speech`)."""
    spoken = client.post("/api/v1/tts/speak", json={"text": text, "language": "uz"}, headers=auth)
    assert spoken.status_code == 200
    sent = tts_server.streams[-1]

    probe = client.post(f"{API}/probe/tts-text", json={"text": text, "language": "uz"}, headers=auth)
    assert probe.status_code == 200
    body = probe.json()
    assert body["ok"] is True
    assert body["result"]["final"] == sent["text"]
    assert body["result"]["normalizeNumbers"] == sent["normalize_numbers"]
    # Bosqichlar - zanjir tartibida, oxirgisi - yakuniy matn.
    stages = [s["stage"] for s in body["result"]["stages"]]
    assert stages == ["input", "clip", "spoken_names", "legal_forms", "quotes", "dates", "times",
                      "risky_for_normalizer"]
    assert body["result"]["stages"][-1]["text"] == sent["text"]
    # Sinov TTS serveriga hech narsa yubormaydi (sintez - faqat `tts-speak`, brauzerda).
    assert len(tts_server.streams) == 1


def test_tts_text_clip_chegarasi(client, auth, tts_server):
    response = client.post(f"{API}/probe/tts-text", json={"text": "a" * 700, "mode": "clip"}, headers=auth)
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["result"]["status"] == 422


def test_tts_text_tilsiz(client, auth, tts_server):
    body = client.post(f"{API}/probe/tts-text", json={"text": "привет", "language": "ru"}, headers=auth).json()
    assert body["ok"] is False and body["result"]["status"] == 400


# --- uyg'otish ----------------------------------------------------------------------------------


def test_wake_ha(client, auth):
    body = client.post(f"{API}/probe/wake", json={"text": "Salom, Barno!"}, headers=auth).json()
    assert body["ok"] is True
    assert body["result"]["matched"] is True
    assert body["result"]["heard"] == "salom barno"
    words = {w["word"]: w for w in body["result"]["words"]}
    assert words["barno"]["isBarno"] is True and words["barno"]["distanceBarno"] == 0
    assert words["salom"]["greeting"] is True
    assert [s["step"] for s in body["trace"]] == ["normalize_heard", "word_limit", "to_latin", "match"]
    # Oraliq qiymatlar AYNI `is_wake_phrase` dan (`trace`), qayta hisoblanmaydi.
    match = body["trace"][-1]["detail"]
    assert match["barno"] is True and match["greetingIn"] == "latin"


def test_wake_eski_nom_salom_asl_sozlarda(client, auth):
    """Eski nom (Venera) - salom ASL so'zlar ichida qidiriladi (`pool`), jadval ham shunday."""
    body = client.post(f"{API}/probe/wake", json={"text": "Assalom Venera"}, headers=auth).json()
    assert body["result"]["matched"] is True
    assert body["trace"][-1]["detail"]["greetingIn"] == "heard"
    words = {w["word"]: w for w in body["result"]["words"]}
    assert words["assalom"]["greeting"] is True and words["venera"]["isVenera"] is True


def test_wake_kirill_va_uzun(client, auth):
    cyr = client.post(f"{API}/probe/wake", json={"text": "Салом Барно"}, headers=auth).json()["result"]
    assert cyr["latin"] == "salom barno" and cyr["matched"] is True
    long = client.post(f"{API}/probe/wake", json={"text": "barno bugun ob-havo qanday bo'ladi ayting"},
                       headers=auth).json()
    assert long["result"]["matched"] is False
    assert "uzun" in long["result"]["reason"]
    limit = next(s for s in long["trace"] if s["step"] == "word_limit")
    assert limit["detail"]["ok"] is False


# --- niqob --------------------------------------------------------------------------------------


def test_mask(client, auth):
    text = "Aliga qo'ng'iroq: +998 90 123 45 67, pochta ali@brb.uz, parol: qwerty123"
    body = client.post(f"{API}/probe/mask", json={"text": text}, headers=auth).json()
    result = body["result"]
    assert "+998" not in result["masked"] and "ali@brb.uz" not in result["masked"]
    assert "qwerty123" not in result["masked"]
    assert result["fired"] == {"<telefon>": 1, "<email>": 1, "parol": 1}
    # Faqat sirlar: telefon va email QOLADI (guruh CRM so'rovi qoidasi).
    assert "+998 90 123 45 67" in result["secretsOnly"]["masked"]
    assert result["secretsOnly"]["fired"] == {"parol": 1}


def test_mask_ishlab_chiqarish_bilan_bir_xil():
    """`fired` berilmasa ham, berilsa ham natija bir xil - xulq o'zgarmagan."""
    from app.services.tg_groups import mask_secrets, mask_text

    text = "Bearer abc.def-ghi karta 8600123456789012 +7 916 123-45-67 AA1234567"
    assert mask_text(text, {}) == mask_text(text)
    assert mask_secrets(text, {}) == mask_secrets(text)


def test_mask_ozgarmagan_moslik_sanalmaydi(client, auth):
    """`_intl_phone` qisqa sonni (`+12 34 56`) o'z holicha qaytaradi - sinov uni
    "niqoblandi" deb sanamasin (avval moslik soni sanalardi: 2 ta, niqob esa 1 ta)."""
    body = client.post(f"{API}/probe/mask", json={"text": "kod +12 34 56, tel +7 916 123-45-67"},
                       headers=auth).json()
    assert body["result"]["masked"] == "kod +12 34 56, tel <telefon>"
    assert body["result"]["fired"] == {"<telefon>": 1}


# --- kutish ovozi -------------------------------------------------------------------------------


def test_hold_modelsiz(client, auth, monkeypatch):
    """`use_llm=false` - gemma CHAQIRILMAYDI; jadval mavzusi va ovozlar ketma-ketligi."""
    import app.api.v1.chat as chat_module
    from app.services import hold

    def boom(*a, **k):
        raise AssertionError("model chaqirildi")

    monkeypatch.setattr(chat_module._hold_classifier, "classify", boom)
    before = dict(hold._navbat)
    body = client.post(f"{API}/probe/hold", json={"question": "Ertaga ta'tilga chiqsam bo'ladimi?"},
                       headers=auth).json()
    assert body["ok"] is True and body["cost_note"] is None
    result = body["result"]
    assert result["keywordTopic"] == "tatil" and result["source"] == "jadval"
    clips = result["clips"]
    assert clips[0]["stage"] == "ilk" and len(clips) == settings.hold_max
    assert clips[0]["url"] == f"/api/v1/tts/hold/{clips[0]['clip']}.wav"
    # Navbat surilmaydi - sinov foydalanuvchilarning keyingi kutish gapini o'zgartirmaydi.
    assert dict(hold._navbat) == before
    assert "classify" not in [s["step"] for s in body["trace"]]


# --- STT ----------------------------------------------------------------------------------------


def test_stt_router(client, auth, monkeypatch):
    import app.api.v1.stt as module

    sent: list[dict] = []

    def transcribe(audio, *, language, content_type="audio/webm", budget=None):
        sent.append({"bytes": len(audio), "language": language, "content_type": content_type})
        return Transcript(text="salom dunyo", language=language, backend="uz", duration_sec=1.5)

    monkeypatch.setattr(module._router_client, "transcribe", transcribe)
    response = client.post(f"{API}/probe/stt", files=_wav(), data={"language": "uz"}, headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    result = body["result"]
    assert result["text"] == "salom dunyo" and result["provider"] == "router"
    assert result["fallbackUsed"] is False
    assert result["forwarded"] == {"filename": "speech.wav", "contentType": "audio/wav", "bytes": 4004}
    assert sent == [{"bytes": 4004, "language": "uz", "content_type": "audio/wav"}]
    assert [s["step"] for s in body["trace"]] == ["upload", "pick", "stt_router"]
    assert "bepul" in body["cost_note"]


# --- agent, sog'lik -----------------------------------------------------------------------------


def test_agent_sozlanmagan(client, auth, monkeypatch):
    monkeypatch.setattr(settings, "hrm_assistant_client_secret", "", raising=False)
    body = client.get(f"{API}/probe/agent", headers=auth).json()
    assert body["ok"] is False
    assert "sozlanmagan" in body["result"]["error"]


def test_health(client, auth):
    body = client.get(f"{API}/probe/health", headers=auth).json()
    names = [s["name"] for s in body["result"]["services"]]
    assert names[:2] == ["upstream", "assistant"]
    assert body["trace"][-1]["step"] == "diagnostics"
    assert body["result"]["diagnostics"]["status"] == body["result"]["status"]


# --- miya funksiyalari --------------------------------------------------------------------------


@pytest.fixture
def no_side_effects(monkeypatch, tmp_path):
    """Model, Telegram va jonli guruh ombori - chaqirilsa test yiqiladi."""
    import app.bot as bot_module
    from app.services.integrations.ollama import OllamaChat

    def boom(*a, **k):
        raise AssertionError("yon ta'sir: tashqi chaqiruv")

    monkeypatch.setattr(OllamaChat, "complete", boom)
    monkeypatch.setattr(OllamaChat, "complete_meta", boom)
    monkeypatch.setattr(bot_module.api, "send_message", boom, raising=False)
    monkeypatch.setattr(bot_module.api, "send_chat_action", boom, raising=False)
    live = tmp_path / "live" / "groups.db"
    monkeypatch.setattr(settings, "telegram_groups_db", live, raising=False)
    return live


def test_brain_guruh_xulosasi_dry(client, auth, no_side_effects, _isolated_analytics):
    sample = "Ali: Server xotirasi to'ldi, +998 90 123 45 67 ga qo'ng'iroq qiling\nVali: Ertaga tuzataman"
    response = client.post(f"{API}/probe/brain/group_summary", json={"input": sample}, headers=auth)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["mode"] == "dry"
    call = result["calls"][0]
    from app.bot.groups import SYSTEM_PROMPT

    assert call["op"] == "group_summary" and call["system"] == SYSTEM_PROMPT
    assert "Turi: XULOSA" in call["user"] and "Vali: Ertaga tuzataman" in call["user"]
    # Saqlash yo'li (`message_text` -> `mask_text`) - modelga niqoblangan matn boradi.
    assert "<telefon>" in call["user"] and "+998" not in call["user"]
    # Agent holatidagi tana - AYNI `AgentComplete.request`.
    assert result["agentRequest"]["purpose"] == "group_summary"
    assert result["agentRequest"]["instructions"] == SYSTEM_PROMPT
    assert result["agentRequest"]["audience"] == "group"
    assert "telegramWouldSend" not in result
    # Jonli guruh ombori yaratilmadi ham.
    assert not no_side_effects.exists()
    assert _audit(_isolated_analytics)[-1]["target_id"] == "brain:group_summary"


def test_brain_guruh_execute_telegramga_yubormaydi(client, auth, no_side_effects, monkeypatch):
    """`execute` - model chaqiriladi, javob esa Telegram'ga EMAS, natijaga."""
    import app.api.v1.admin_probe as probe

    class Model:
        model = "soxta"

        def complete(self, system, user, **kwargs):
            return "**Asosiy:** server xotirasi.\n- Vali ertaga tuzatadi"

    monkeypatch.setattr(probe, "_live_writer", lambda feature: Model())
    body = client.post(f"{API}/probe/brain/group_ask",
                       json={"input": "Ali: salom\nVali: server tuzaldi", "question": "server?", "execute": True, "confirm_cost": True},
                       headers=auth).json()
    result = body["result"]
    assert result["mode"] == "execute"
    assert result["calls"][0]["output"].startswith("**Asosiy:**")
    assert result["telegramWouldSend"] and "server" in result["telegramWouldSend"][-1]
    assert body["cost_note"]
    assert body["ok"] is True


def test_brain_execute_model_xatosi_ok_emas(client, auth, no_side_effects, monkeypatch):
    """Model yiqilsa ishlab chiqarish kodi xatoni o'zi yutadi ("bajarib bo'lmadi" xabari) -
    sinov buni muvaffaqiyat deb ko'rsatmasin."""
    import app.api.v1.admin_probe as probe
    from app.services.integrations.ollama import OllamaError

    class Down:
        model = "soxta"

        def complete(self, system, user, **kwargs):
            raise OllamaError("model ishlamayapti")

    monkeypatch.setattr(probe, "_live_writer", lambda feature: Down())
    body = client.post(f"{API}/probe/brain/group_summary",
                       json={"input": "Ali: salom\nVali: server tuzaldi", "execute": True, "confirm_cost": True}, headers=auth).json()
    assert body["ok"] is False
    assert "output" not in body["result"]["calls"][0]
    assert body["result"]["telegramWouldSend"]


def test_brain_brif_dry(client, auth, no_side_effects):
    body = client.post(f"{API}/probe/brain/brief_extract",
                       json={"input": "Ali: DVSIB-12 vazifani juma kuni topshiraman", "kind": "support"},
                       headers=auth).json()
    from app.bot.briefs import SUPPORT_PROMPT

    call = body["result"]["calls"][0]
    assert call["op"] == "brief_extract_support" and call["system"] == SUPPORT_PROMPT
    assert "DVSIB-12" in call["user"] and call["format"] == "json"
    assert body["result"]["agentRequest"]["priority"] == "batch"


def test_brain_yigilish_va_tasnif_dry(client, auth, no_side_effects):
    transcript = "\n".join(f"S{1 + n % 2}: bu yig'ilishning {n}-gapi, biz loyiha muddatini muhokama qildik"
                           for n in range(12))
    summary = client.post(f"{API}/probe/brain/meeting_summary", json={"input": transcript}, headers=auth).json()
    calls = summary["result"]["calls"]
    assert len(calls) == 1 and calls[0]["op"].startswith("meeting_")
    assert "TRANSCRIPT" in calls[0]["user"]

    ask = client.post(f"{API}/probe/brain/meeting_ask",
                      json={"input": transcript, "question": "Muddat qachon?"}, headers=auth).json()
    assert ask["result"]["calls"][0]["op"] == "meeting_ask"
    assert "Muddat qachon?" in ask["result"]["calls"][0]["user"]

    hold = client.post(f"{API}/probe/brain/hold_classify", json={"question": "ta'til"}, headers=auth).json()
    messages = hold["result"]["request"]["messages"]
    assert messages[1] == {"role": "user", "content": "ta'til"}


def test_brain_crm_tana_tokensiz(client, auth, no_side_effects):
    body = client.post(f"{API}/probe/brain/group_crm",
                       json={"input": "Ali: mijoz +998 90 123 45 67 ga shartnoma", "question": "vazifa qil"},
                       headers=auth).json()
    request = body["result"]["agentRequest"]
    assert request["tokens"] == {"crm": "<crm-token>"}
    assert "<telefon>" in request["context"][0]["items"][0]["text"]
    # AYNI `GroupActions._v4_body`: oyna yorlig'i, so'ragan odam eslatmasi, `assistant_user_id`.
    block = request["context"][0]
    assert block["window"]["label"].startswith("oxirgi")
    assert block["notes"][0]["kind"] == "people"
    assert request["user_id"].startswith("venera:") and request["chat_id"] == "tgcrm-probe"
    secret = client.post(f"{API}/probe/brain/group_crm",
                         json={"input": "Ali: salom", "question": "vazifa qil, parol: qwerty123"},
                         headers=auth).json()["result"]["agentRequest"]
    assert "qwerty123" not in secret["question"]
    meeting = client.post(f"{API}/probe/brain/meeting_crm", json={"input": "Hisobotni tayyorlash"},
                          headers=auth).json()
    assert meeting["result"]["agentRequest"]["tokens"] == {"crm": "<crm-token>"}
    assert "Hisobotni tayyorlash" in meeting["result"]["question"]


@pytest.mark.parametrize("feature", ["group_crm", "meeting_crm", "brief_crm", "meeting_summary", "meeting_ask"])
def test_brain_execute_yon_tasirli_409(client, auth, no_side_effects, feature):
    response = client.post(f"{API}/probe/brain/{feature}", json={"input": "Ali: salom", "execute": True},
                           headers=auth)
    assert response.status_code == 409


def test_brain_nomalum_422(client, auth):
    assert client.post(f"{API}/probe/brain/nimadir", json={}, headers=auth).status_code == 422


def test_audit_yoziladi_matnsiz(client, auth, _isolated_analytics):
    client.post(f"{API}/probe/mask", json={"text": "maxfiy 8600123456789012"}, headers=auth)
    rows = [r for r in _audit(_isolated_analytics) if r["action"] == "probe.run"]
    assert rows and rows[-1]["target_type"] == "probe" and rows[-1]["target_id"] == "mask"
    assert "8600" not in json.dumps(rows[-1]["detail"])


def test_pullik_sinov_tasdiqsiz_428(client, auth):
    """Sahifadagi tasdiq yetmaydi: API ni to'g'ridan-to'g'ri chaqirgan admin ham pullik
    yo'lni aniq tasdiqlashi kerak - model chaqirilmaydi."""
    r = client.post(f"{API}/probe/brain/group_summary", json={"input": "Ali: salom", "execute": True}, headers=auth)
    assert r.status_code == 428
    r = client.post(f"{API}/probe/hold", json={"question": "kim kech qoldi", "use_llm": True}, headers=auth)
    assert r.status_code == 428
    # Bepul yo'l tasdiqsiz ishlaydi.
    assert client.post(f"{API}/probe/hold", json={"question": "kim kech qoldi"}, headers=auth).status_code == 200


def test_pullik_sinov_soatlik_chek(monkeypatch):
    from fastapi import HTTPException

    from app.api.v1 import admin_probe as probe
    from app.schemas.auth import AuthUser

    monkeypatch.setattr(probe, "PAID_PER_HOUR", 2)
    monkeypatch.setattr(probe, "_paid_runs", {})
    admin = AuthUser(actorId=1, email="admin@test", fullName="Admin", roles=["ADMIN"])
    probe._paid_gate(admin, "stt", True, "")
    probe._paid_gate(admin, "stt", True, "")
    try:
        probe._paid_gate(admin, "stt", True, "")
    except HTTPException as exc:
        assert exc.status_code == 429
    else:  # pragma: no cover
        raise AssertionError("chekdan oshgan sinov o'tib ketdi")
