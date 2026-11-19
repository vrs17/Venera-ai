"""Jonli ovozli suhbat - `/api/v1/live` (llm.brb-tech.uz/barno sahifasi, `apps/web/src/views/LiveView.vue`).

`POST /live/session`: Speko'da («Barno AI» agenti) yangi sessiya ochadi va brauzerga uning bir martalik
transport tokeni va manzilini qaytaradi (`services/integrations/speko.py`). Brauzer shu bilan agentga
to'g'ridan-to'g'ri ulanadi (WebRTC) - ovoz bizning server orqali o'tmaydi.

HIMOYA. Har sessiya - Speko hisobidagi pullik daqiqalar, shuning uchun:
  * faqat tizimga KIRGAN odam (`current_user`) - begona odam bizning hisobimizdan daqiqa sarflay olmaydi;
  * odam boshiga chegara: daqiqasiga `LIVE_SESSIONS_PER_MIN`, soatiga `LIVE_SESSIONS_PER_HOUR` (oshsa 429 va
    `Retry-After`);
  * platforma kaliti brauzerga ham, xato matniga ham chiqmaydi.

`POST /live/feedback`: suhbatdan keyingi baho (1-5, sabablar, izoh) - `services/live_feedback.py`.

XATOLAR. 503 - sozlanmagan (`SPEKO_AGENT_KEY` yo'q) yoki Speko vaqtincha javob bermadi; 502 - Speko bizning
so'rovni rad etdi (kalit yoki agent raqami noto'g'ri - logda sababi). Brauzerga har ikkisida bir xil, sirsiz matn.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Response

from ...core.config import settings
from ...core.errors import error_status
from ...schemas.auth import AuthUser
from ...schemas.live import LiveFeedbackRequest, LiveFeedbackResponse, LiveSessionRequest, LiveSessionResponse
from ...services import live_feedback
from ...services.analytics import metered
from ...services.integrations.speko import SpekoClient, SpekoError
from ...services.reports import RateLimiter
from ..deps import current_user

log = logging.getLogger(__name__)

router = APIRouter(prefix="/live", tags=["live"])

#: Odam boshiga sessiya chegaralari (qiymat har so'rovda sozlamadan - jonli).
_per_minute = RateLimiter(limit=1, window=60.0)
_per_hour = RateLimiter(limit=1, window=3600.0)
#: Baho: suhbat boshiga bitta kutiladi - chegara faqat suiiste'moldan.
_feedback = RateLimiter(limit=10, window=60.0)

UNAVAILABLE = "Ovozli suhbat hozir ishlamayapti - birozdan keyin qayta urinib ko'ring"


def _client() -> SpekoClient:
    return SpekoClient(settings.speko_api_url, settings.speko_agent_key, timeout=settings.speko_timeout)


def _agent_of(persona: str) -> str:
    """Suhbatdosh -> Speko agenti. Hozircha bitta: Barno -> «Barno AI» (`settings.speko_agent_id`)."""
    return {"barno": settings.speko_agent_id}[persona]


def reset_limits() -> None:
    """Testlar uchun."""
    _per_minute.reset()
    _per_hour.reset()
    _feedback.reset()


def _take(user: AuthUser) -> int | None:
    """Chegarada joy bo'lsa band qiladi (`None`), bo'lmasa - necha soniyadan keyin bo'shashi."""
    _per_minute.limit = max(1, int(settings.live_sessions_per_min))
    _per_hour.limit = max(1, int(settings.live_sessions_per_hour))
    wait = _per_minute.take(user.actorId)
    if wait is not None:
        return wait
    wait = _per_hour.take(user.actorId)
    if wait is not None:
        _per_minute.give_back(user.actorId)
    return wait


@router.post("/session", response_model=LiveSessionResponse)
def create_session(body: LiveSessionRequest, response: Response,
                   user: AuthUser = Depends(current_user)) -> LiveSessionResponse:
    client = _client()
    if not client.configured:
        raise error_status(503, UNAVAILABLE)
    wait = _take(user)
    if wait is not None:
        problem = error_status(429, "Juda ko'p urinish - birozdan keyin qayta qo'ng'iroq qiling")
        problem.headers = {"Retry-After": str(wait)}
        raise problem
    try:
        with metered("speko", "session", units={"persona": body.persona}):
            session = client.create_session(_agent_of(body.persona))
    except SpekoError as exc:
        # Ochilmagan sessiya chegaradan joy yemaydi: odam darhol qayta urina olsin.
        _per_minute.give_back(user.actorId)
        _per_hour.give_back(user.actorId)
        log.warning("Jonli suhbat: Speko sessiyasi ochilmadi (%s): %s", user.actorId, exc)
        raise error_status(exc.status if exc.status in (502, 503) else 502, UNAVAILABLE) from None
    log.info("Jonli suhbat: sessiya %s (%s, %s)", session.session_id[:8], user.actorId, body.persona)
    # Token javobi hech qayerda keshlanmasin (brauzer, oraliq proksi).
    response.headers["Cache-Control"] = "no-store"
    return LiveSessionResponse(sessionId=session.session_id, transport=session.transport,
                               transportToken=session.transport_token, transportUrl=session.transport_url,
                               expiresAt=session.expires_at)


@router.post("/feedback", response_model=LiveFeedbackResponse)
def post_feedback(body: LiveFeedbackRequest, user: AuthUser = Depends(current_user)) -> LiveFeedbackResponse:
    wait = _feedback.take(user.actorId)
    if wait is not None:
        problem = error_status(429, "Juda ko'p so'rov - birozdan keyin qayta urinib ko'ring")
        problem.headers = {"Retry-After": str(wait)}
        raise problem
    saved = live_feedback.save(user, body)
    log.info("Jonli suhbat: baho %s/5 (%s, sessiya %s)", saved["rating"], user.actorId, saved["sessionId"][:8])
    return LiveFeedbackResponse()
