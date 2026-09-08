"""Ovoz -> matn javobi.

`apps/web/src/types.ts` dagi `Transcript` bilan MOS bo'lishi shart -
`tests/test_contract.py` shuni qo'riqlaydi.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TranscriptResponse(BaseModel):
    text: str = Field(description="Tanib olingan matn")
    language: str = Field(default="", description="Router ishlatgan til")
    durationSec: float = Field(default=0.0, description="Audio uzunligi (soniya)")
    lowConfidence: bool = Field(
        default=False,
        description="Router matnga ishonchi past. uz backend buni `null` qaytaradi, "
                    "shuning uchun bu yerda doim bool.",
    )
