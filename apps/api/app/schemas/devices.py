"""Qurilma sessiyasi sxemalari (mobil ilova, spetsifikatsiya 3.2, 29-31).

`POST /auth/devices/session` javobi - `LoginResponse` ning O'ZI (`schemas/auth.py`):
ilova kirish va sessiyani bitta kod bilan o'qiydi.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DeviceRegisterRequest(BaseModel):
    deviceName: str = Field(min_length=1, max_length=80)
    platform: Literal["android", "ios"]
    appVersion: str = Field(default="", max_length=40)


class DeviceRegistered(BaseModel):
    deviceId: str
    #: 43 belgili base64url (32 tasodifiy bayt). FAQAT shu javobda ko'rinadi.
    deviceToken: str
    expiresAt: str


class DeviceTokenRequest(BaseModel):
    deviceToken: str = Field(min_length=1, max_length=200)


class DeviceRevoked(BaseModel):
    status: Literal["OK"] = "OK"
