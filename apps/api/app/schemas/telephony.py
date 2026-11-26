"""Telefoniya (`/api/v1/telephony`, `api/v1/telephony.py`) - so'rov va javob shakllari."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PlaceCallRequest(BaseModel):
    """Admin sinov qo'ng'irog'i. Raqam: `901234567`, `998901234567` yoki `+998 90 123 45 67`."""

    phone: str = Field(min_length=9, max_length=24)
    #: Adminning o'z izohi (masalan «1-sinov»). FreePBX'ga yuborilmaydi.
    note: str = Field(default="", max_length=200)


class TelephonyStatus(BaseModel):
    enabled: bool = Field(description="Qo'ng'iroq boshlash yoqilganmi (TELEPHONY_ENABLED)")
    configured: bool = Field(description="FreePBX manzili, tokeni va sertifikat barmoq izi berilganmi")
    dailyCap: int
    used24h: int


class CallView(BaseModel):
    callId: str
    phone: str
    status: str = Field(description="placing | queued | rejected | failed | completed | unknown")
    outcome: str = Field(default="", description="no_answer | busy | congestion | rejected | failed | talked | gateway_failed")
    detail: str = Field(default="", description="FreePBX javobidagi sabab (disabled, barno_max, trunk...) yoki xato turi")
    httpStatus: int | None = None
    note: str = ""
    createdAt: int
    placedAt: int | None = None
    resultAt: int | None = None
    answerTime: int | None = None
    endTime: int | None = None
    talkSec: int | None = None
    gatewayStatus: str | None = None
    hangupCause: str | None = None
    events: list[dict[str, Any]] | None = None
    bridge: dict[str, Any] | None = None

    @classmethod
    def of(cls, call: dict[str, Any]) -> "CallView":
        return cls(callId=call["call_id"], phone=call["phone"], status=call["status"], outcome=call["outcome"] or "",
                   detail=call["detail"] or "", httpStatus=call["http_status"], note=call["note"] or "",
                   createdAt=call["created_at"], placedAt=call["placed_at"], resultAt=call["result_at"],
                   answerTime=call["answer_time"], endTime=call["end_time"], talkSec=call["talk_sec"],
                   gatewayStatus=call["gateway_status"], hangupCause=call["hangup_cause"],
                   events=call.get("events"), bridge=call.get("bridge"))
