"""Guruhdagi CRM so'rovi - agent v4 shakli (migratsiya W1, shartnoma 6.1 / agent javobi §6).

NIMA O'ZGARADI (bugungi v3 yo'li bilan solishtirganda):
  * guruh yozishmasi SAVOL MATNI ichida emas, KONTEKST bloki sifatida (id lar bilan,
    niqoblangan) ketadi - agent uni ma'lumot deb o'qiydi, ichidagi buyruqlarga amal qilmaydi;
  * suhbat `chat_visibility: surface` - so'ragan odamning shaxsiy tarixida ko'rinmaydi,
    `audience: group` - HRM ham, shaxsiy xotira ham ishlatilmaydi, hech narsa "o'rganilmaydi";
  * `retention_days` - agent o'zi o'chiradi; bizning tozalovchi ham `purge` qiladi;
  * faqat `crm.read` va `crm.propose`, faqat so'ragan odamning O'Z CRM tokeni.

Taklifni tasdiqlash/rad etish o'zgarmaydi (`/api/actions/{token}` - agentning umumiy yo'li).
Bu modul faqat so'rov tanasini quradi va javobni bugungi `_ask` shakliga keltiradi; qaysi yo'l
ishlashini `routing.route("group_crm")` hal qiladi (default `local` - bugungi yo'l).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from ...core import config as _config

#: Agentning chat cheklovi 60 000 belgi / 2 000 band (`/api/v4/limits`); biz ancha past
#: turamiz - guruh CRM so'rovi uchun oxirgi yozishma yetadi, ortig'i agentga keraksiz.
CONTEXT_CHARS = 20_000
CONTEXT_ITEMS = 200
#: Guruh CRM suhbati agentda shuncha kun saqlanadi (egasi o'zgartirmaguncha; reja D-qarori).
RETENTION_DAYS = 7
QUESTION_CHARS = 2_000


def surface_id(chat_id: int) -> str:
    return f"tg:{chat_id}"


def _iso(ts: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def context_block(chat_id: int, title: str, items: Iterable[Mapping[str, Any]], *,
                  notes: Iterable[Mapping[str, Any]] = (), window_label: str = "") -> dict[str, Any]:
    """Bitta guruh bloki. `items` - eng ESKIsidan yangisiga; chegaradan oshsa ESKIlari tushadi
    (`truncated.omitted_items`). Matnlar chaqiruvchida NIQOBLANGAN bo'lishi shart."""
    rows = [dict(it) for it in items if str(it.get("text") or "").strip()]
    kept: list[dict[str, Any]] = []
    used = 0
    for it in reversed(rows):
        size = len(str(it.get("text") or ""))
        if len(kept) >= CONTEXT_ITEMS or used + size > CONTEXT_CHARS:
            break
        kept.append(it)
        used += size
    kept.reverse()
    block: dict[str, Any] = {
        "surface_id": surface_id(chat_id),
        "kind": "tg_group",
        "title": title,
        # Egasining qarori (2026-10-11): GPU kelguncha Ollama Cloud; agent `false` ni rad etadi.
        # Shaxsiy xotira va "o'rganish" - guruh matnidan HECH QACHON.
        "policy": {"external_llm": _config.agent_v4_external_models_now(), "personal_memory": False,
                   "learn": False, "retention_days": RETENTION_DAYS},
        "items": kept,
    }
    if window_label:
        block["window"] = {"label": window_label}
    if len(kept) < len(rows):
        block["truncated"] = {"omitted_items": len(rows) - len(kept)}
    extra = [dict(n) for n in notes if str(n.get("text") or "").strip()]
    if extra:
        block["notes"] = extra
    return block


def item(message_id: Any, ts: Any, author: str, text: str, *, reply_to: Any = None) -> dict[str, Any]:
    out: dict[str, Any] = {"id": str(message_id), "author": {"label": author or "guruh a'zosi"},
                           "text": text}
    when = _iso(ts)
    if when:
        out["ts"] = when
    if reply_to is not None:
        out["reply_to"] = str(reply_to)
    return out


def request(*, question: str, user_id: str, chat_id: str, crm_token: str, block: Mapping[str, Any],
            reply_to: Any = None, shadow: bool = False) -> dict[str, Any]:
    """`POST /api/v4/chat` tanasi. `chat_id` - bizning `tgcrm-` suhbatimiz (guruhga bog'langan)."""
    body: dict[str, Any] = {
        "purpose": "group_crm",
        "question": question[:QUESTION_CHARS],
        "user_id": user_id,
        "chat_id": chat_id,
        "tokens": {"crm": crm_token},
        "store": True,
        "chat_visibility": "surface",
        "retention_days": RETENTION_DAYS,
        "audience": "group",
        "tools": ["crm.read", "crm.propose"],
        "memory_scopes": [],
        "context": [dict(block)],
        "client": {"channel": "bot"},
    }
    ids = {str(it.get("id")) for it in block.get("items") or []}
    if reply_to is not None and str(reply_to) in ids:
        body["reply_to_ref"] = f"{block.get('surface_id')}#{reply_to}"
    if shadow:
        # Shadow: agent taklif bermaydi va hech narsa saqlamaydi (agent javobi §6).
        body["shadow"] = True
        body["store"] = False
    return body


def parse(payload: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]], str | None]:
    """Agent javobi -> (matn, takliflar, xato kodi). Bugungi `_ask` natijasi bilan bir xil shakl."""
    text = str(payload.get("answer") or "")
    proposals = [p for p in payload.get("proposals") or [] if isinstance(p, dict) and p.get("token")]
    meta = payload.get("meta") if isinstance(payload.get("meta"), Mapping) else {}
    code = meta.get("error_code") if isinstance(meta, Mapping) else None
    return text, proposals, (str(code) if code else None)
