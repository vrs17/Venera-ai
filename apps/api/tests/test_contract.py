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
TRANSCRIPT_FIELDS = {"text", "language", "durationSec", "lowConfidence", "truncated", "backend"}

# types.ts: ProQuota / ProWindows. `engine` va `available` - Venera'niki:
# so'rovchi kanalining dvigateli va "Pro" shu kanalda bormi (faqat v2).
PRO_QUOTA_FIELDS = {"remaining", "limits", "used", "engine", "available"}
PRO_WINDOW_FIELDS = {"day", "week", "month"}

# types.ts: ChatSummary / ChatDetail / ChatMessage / ChatList / ChatDeleted
CHAT_SUMMARY_FIELDS = {"chat_id", "title", "title_source", "created_at", "updated_at", "messages"}
CHAT_MESSAGE_FIELDS = {"role", "content", "created_at"}
CHAT_LIST_FIELDS = {"items", "limit", "offset"}
CHAT_DELETED_FIELDS = {"chat_id", "status"}


def test_login_javobi_types_ts_ga_mos(client):
    body = client.post("/api/v1/auth/login", json=ADMIN).json()
    assert set(body) == LOGIN_FIELDS, "LoginResponse maydonlari mos kelmadi"
    assert set(body["user"]) == AUTH_USER_FIELDS, "AuthUser maydonlari mos kelmadi"


def test_login_sorovi_types_ts_ga_mos():
    """types.ts: LoginRequest - `username` + `password` (`email` eski nom, zahira)."""
    from app.schemas.auth import LoginRequest
    assert {"username", "password"} <= set(LoginRequest.model_fields)


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


def test_suhbatlar_tarixi_types_ts_ga_mos():
    """`schemas/chats.py` <-> `types.ts` dagi `ChatSummary`, `ChatDetail`,
    `ChatMessage`, `ChatList`, `ChatDeleted`.

    Sxemadan o'qiladi: suhbatlar yuqoridagi xizmatda turadi va testda
    chaqirilmaydi (HTTP yo'li `tests/test_chats.py` da soxta xizmat bilan).
    """
    from app.schemas.chats import ChatDeleted, ChatDetail, ChatList, ChatMessage, ChatSummary
    assert set(ChatSummary.model_fields) == CHAT_SUMMARY_FIELDS
    # ChatDetail = ChatSummary, faqat `messages` son emas, ro'yxat.
    assert set(ChatDetail.model_fields) == CHAT_SUMMARY_FIELDS
    assert set(ChatMessage.model_fields) == CHAT_MESSAGE_FIELDS
    assert set(ChatList.model_fields) == CHAT_LIST_FIELDS
    assert set(ChatDeleted.model_fields) == CHAT_DELETED_FIELDS


def test_pro_byudjeti_types_ts_ga_mos():
    """`schemas/pro.py` <-> `types.ts` dagi `ProQuota` va `ProWindows`.

    Sxemadan o'qiladi: byudjet yuqoridagi xizmatda hisoblanadi va testda
    chaqirilmaydi (HTTP yo'li `tests/test_pro.py` da soxta xizmat bilan).
    """
    from app.schemas.pro import ProQuota, ProWindows
    assert set(ProQuota.model_fields) == PRO_QUOTA_FIELDS
    assert set(ProWindows.model_fields) == PRO_WINDOW_FIELDS


def test_stream_sorovida_mode_bor():
    """`mode` KLIENTDAN keladi va faqat ikki qiymat qabul qilinadi."""
    import pytest
    from pydantic import ValidationError
    from app.schemas.chat import StreamRequest

    assert StreamRequest(question="a").mode == "standard", "default standard"
    assert StreamRequest(question="a", mode="pro").mode == "pro"
    with pytest.raises(ValidationError):
        StreamRequest(question="a", mode="turbo")
