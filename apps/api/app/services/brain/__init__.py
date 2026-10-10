"""Miya (LLM ishi) agentga ko'chishi - bizning tomondagi relslar (W0).

Oxirgi holat (egasining qarori, 2026-10-10): serverimiz mulohaza uchun LLM
chaqirmaydi - xulosa, ajratish, tasnif, savol-javob agentda. Bizda kanallar,
media, auth/tokenlar, rozilik, ruxsat tekshiruvi, xom yozuv va UI qoladi.
Ko'chish funksiyama-funksiya, shartnoma bo'yicha (`agent-contract.md`):

    routing.py   flag (`engine_control.brain_choice`) + capability guard -> `Route`
    chat.py      `BrainChat` - `OllamaChat` o'rnidagi o'ram (guruh, brif);
                 `AgentComplete` - agentning `complete` i, `complete_meta` shaklida
    features.py  brif CRM vazifasi, yig'ilish zanjiriga `agent` bo'g'ini, hold
    shadow.py    fondagi taqqoslash: o'z navbati, namuna, `shadow_results`

Default'lar BUGUNGI xulq: hamma funksiya `local`, `AGENT_V4_ENABLED=false`.
"""

from __future__ import annotations

from .chat import AgentComplete, BrainChat, note_fallback
from .features import (
    admin_view,
    brief_crm_ask,
    hold_mode,
    hold_shadow,
    meeting_agent_ok,
    meeting_ask_providers,
    meeting_ask_shadow,
    meeting_summary_providers,
    meeting_summary_shadow,
)
from .routing import Route, route

__all__ = [
    "AgentComplete", "BrainChat", "Route", "admin_view", "brief_crm_ask", "hold_mode", "hold_shadow",
    "meeting_agent_ok", "meeting_ask_providers", "meeting_ask_shadow", "meeting_summary_providers",
    "meeting_summary_shadow",
    "note_fallback", "route",
]
