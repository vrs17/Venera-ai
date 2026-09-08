"""Frontend shartnomasi.

Bu fayl ENG MUHIM: u backend javobi `apps/web/src/types.ts` dagi
interfeyslarga mos kelishini tekshiradi.

Nima uchun kerak: TypeScript serverdan kelgan JSON ni ishga tushish
paytida TEKSHIRMAYDI. Backend maydon nomini o'zgartirsa yoki tashlab
ketsa, frontend kompilyatsiya bo'laveradi va faqat foydalanuvchi ekranida
`undefined` ko'rinadi. Bu testlar shu jimgina buzilishni to'sadi.

QOIDA: `types.ts` o'zgarsa shu fayl ham o'zgaradi va aksincha.
"""

from __future__ import annotations

from tests.conftest import ADMIN

# types.ts: AuthUser
AUTH_USER_FIELDS = {
    "actorId", "actorType", "email", "fullName",
    "position", "department", "roles", "passwordChangeRequired",
}

# types.ts: LoginResponse
LOGIN_FIELDS = {"token", "tokenType", "expiresAt", "passwordChangeRequired", "user"}

# types.ts: ApiErrorResponse
ERROR_FIELDS = {"timestamp", "status", "error", "message", "path"}

# types.ts: PipelineResponse
PIPELINE_FIELDS = {
    "finalStatus", "domain", "domainReason",
    "guard", "intent", "orchestrator", "access", "retrieval", "answer",
}

# types.ts: BaseStage - har bosqichda bo'lishi shart
BASE_STAGE_FIELDS = {"rawAnswer", "model", "adapter", "seconds"}

# types.ts: Transcript
TRANSCRIPT_FIELDS = {"text", "language", "durationSec", "lowConfidence"}


def test_login_javobi_types_ts_ga_mos(client):
    body = client.post("/api/v1/auth/login", json=ADMIN).json()
    assert set(body) == LOGIN_FIELDS, "LoginResponse maydonlari mos kelmadi"
    assert set(body["user"]) == AUTH_USER_FIELDS, "AuthUser maydonlari mos kelmadi"


def test_me_javobi_types_ts_ga_mos(client, auth):
    body = client.get("/api/v1/auth/me", headers=auth).json()
    assert set(body) == AUTH_USER_FIELDS


def test_xato_shakli_types_ts_ga_mos(client):
    """FastAPI default `{"detail": ...}` qaytaradi - bu MOS KELMAYDI.

    Frontend `http.ts` aynan `message` ni o'qiydi:
        body?.message || `Request failed (${status})`
    `detail` qaytarsak foydalanuvchi doim umumiy xabarni ko'radi.
    """
    body = client.post(
        "/api/v1/auth/login", json={**ADMIN, "password": "xato"}).json()
    assert set(body) == ERROR_FIELDS, f"xato shakli noto'g'ri: {body}"
    assert "detail" not in body
    assert body["status"] == 401
    assert body["path"] == "/api/v1/auth/login"
    assert body["message"], "message bo'sh - foydalanuvchi sababni ko'rmaydi"


def test_validatsiya_xatosi_ham_ayni_shaklda(client):
    """422 ham `ApiErrorResponse` bo'lishi kerak - FastAPI buni ham
    `{"detail": [...]}` qilib qaytaradi."""
    body = client.post("/api/v1/auth/login", json={"email": "a@b.uz"}).json()
    assert set(body) == ERROR_FIELDS
    assert body["status"] == 422


def test_405_va_404_ham_ayni_shaklda(client):
    """Router topilmagan yo'llar ham bir xil shaklda javob berishi kerak."""
    for response in (client.get("/api/v1/yoq"), client.get("/api/v1/auth/login")):
        assert set(response.json()) == ERROR_FIELDS


def test_pipeline_javobi_types_ts_ga_mos(client, auth):
    body = client.post(
        "/api/v1/chat/ask", json={"question": "salom"}, headers=auth).json()
    assert set(body) == PIPELINE_FIELDS, "PipelineResponse maydonlari mos kelmadi"


def test_har_bosqichda_base_stage_maydonlari_bor(client, auth):
    body = client.post(
        "/api/v1/chat/ask", json={"question": "salom"}, headers=auth).json()
    for name in ("guard", "intent", "orchestrator", "access"):
        stage = body[name]
        assert stage is not None, f"{name} bosqichi yo'q"
        assert BASE_STAGE_FIELDS <= set(stage), f"{name}: BaseStage maydonlari yetishmayapti"


def test_transcript_javobi_types_ts_ga_mos():
    """`TranscriptResponse` <-> `types.ts` dagi `Transcript`.

    Sxemadan o'qiladi, HTTP orqali emas: STT serveri ichki tarmoqda va
    testda chaqirilmaydi. Maydon nomlari baribir shu yerda qotiriladi.
    """
    from app.schemas.stt import TranscriptResponse
    assert set(TranscriptResponse.model_fields) == TRANSCRIPT_FIELDS
