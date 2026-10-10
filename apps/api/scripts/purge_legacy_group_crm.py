#!/usr/bin/env python3
"""Eski guruh CRM suhbatlarini agentda o'chirish - BIR MARTALIK, deploy paytida.

NEGA KERAK. Guruhdagi CRM (MR !23, 2026-10-09 dan) agentda har odam uchun suhbat
ochadi va unga guruhdagi BOSHQA odamlarning xabarlarini (2026-10-10 gacha javob
qilingan xabar niqobsiz) yozadi. 2026-10-10 dan yangi suhbatlar `tgcrm-` prefiksli:
shaxsiy tarixda ko'rinmaydi va `group_actions.sweep` ularni agentda o'chiradi. ESKI
suhbatlar esa oddiy uuid4 bilan ochilgan - prefiks yo'q (web va mobil tarixida
ko'rinadi), `groups.db` da yozuvi yo'q (tozalovchi bilmaydi). Bu skript ularni topib
o'chiradi. Agentdagi o'chirish hozircha YUMSHOQ (`DELETE /api/chats`) - haqiqiy
o'chirish agent jamoasining ishi (A4, `agent-contract.md`).

QANDAY TOPILADI. Odamlar: Telegram ulanganlar (`links.json`, muddati o'tganlari ham)
va analytics `turns` da `channel = 'bot'` savoli borlar (ombor FAQAT o'qiladi). Har
odamning agentdagi suhbatlari (`GET /api/chats`), har suhbatning xabarlari: suhbat
ESKI guruh CRM suhbati, agar undagi HAR foydalanuvchi xabari `[Telegram ish guruhi «`
bilan boshlansa (`bot/group_actions._HEAD`, 2026-10-09 dan o'zgarmagan). Shaxsiy
suhbatda odam bu belgini bir marta yozgan bo'lsa ham - boshqa xabarlari belgisiz,
ya'ni tegilmaydi. `tgcrm-` suhbatlar o'tkazib yuboriladi (ular tozalovchiniki).

XAVFSIZLIK. Default - DRY-RUN (faqat sanaydi). `--apply` bilan o'chiradi. Chiqishda
faqat SONLAR: matn, sarlavha, suhbat yoki odam id'lari yo'q. Kalit `.env` dan
(chat bilan bir xil `HRM_ASSISTANT_*`), jurnalga yozilmaydi.

Ishlatish (apps/api ichidan, prod venv bilan):

    venv/bin/python scripts/purge_legacy_group_crm.py             # nechta topiladi
    venv/bin/python scripts/purge_legacy_group_crm.py --apply     # o'chirish
    venv/bin/python scripts/purge_legacy_group_crm.py --json      # sonlar JSON da
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

#: Guruh CRM savolining boshi (`bot/group_actions._HEAD`).
MARKER = "[Telegram ish guruhi «"
#: Yangi (2026-10-10 dan) suhbatlar prefiksi - ular tozalovchiniki (`tg_groups.AGENT_CHAT_PREFIX`).
NEW_PREFIX = "tgcrm-"


def user_id(actor_id: int) -> str:
    """Agentdagi kimlik - `api/v1/chat.assistant_user_id` bilan AYNAN bir xil."""
    return f"venera:{actor_id}"


def actors_from_links(path: Path) -> set[int]:
    """`links.json` dagi HAMMA Venera hisoblari (muddati o'tganlari ham)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    links = data.get("links") if isinstance(data, dict) else None
    out: set[int] = set()
    for raw in (links or {}).values() if isinstance(links, dict) else ():
        actor = raw.get("actor_id") if isinstance(raw, dict) else None
        if isinstance(actor, int) and not isinstance(actor, bool):
            out.add(actor)
    return out


def actors_from_analytics(path: Path) -> set[int]:
    """Botda savol bergan odamlar. Ombor FAQAT o'qiladi (`mode=ro`, `query_only`)."""
    if not path.is_file():
        return set()
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only = ON")
        rows = conn.execute("SELECT DISTINCT actor_id FROM turns WHERE channel = 'bot' AND actor_id IS NOT NULL")
        return {int(r[0]) for r in rows if isinstance(r[0], int)}
    except sqlite3.Error:
        return set()
    finally:
        conn.close()


def is_legacy(detail: Mapping[str, Any]) -> bool:
    """Suhbatdagi HAR foydalanuvchi xabari guruh CRM belgisi bilan boshlanadimi."""
    users = [m for m in detail.get("messages") or [] if isinstance(m, Mapping) and m.get("role") == "user"]
    return bool(users) and all(str(m.get("content") or "").lstrip().startswith(MARKER) for m in users)


def run(assistant: Any, actors: Iterable[int], *, apply: bool, page: int = 100,
        detail_limit: int = 50) -> dict[str, int]:
    """Topadi va (`apply`) o'chiradi. Natija - faqat sonlar."""
    from app.services.integrations.assistant import AssistantError

    counts = {"actors": 0, "chats": 0, "new": 0, "found": 0, "deleted": 0, "errors": 0}
    for actor in sorted(set(actors)):
        uid = user_id(actor)
        counts["actors"] += 1
        chats: list[str] = []
        offset = 0
        while True:
            try:
                listing = assistant.list_chats(user_id=uid, limit=page, offset=offset)
            except AssistantError:
                counts["errors"] += 1
                break
            items = [i for i in listing.get("items") or [] if isinstance(i, Mapping)]
            chats.extend(str(i["chat_id"]) for i in items if isinstance(i.get("chat_id"), str))
            if len(items) < page:
                break
            offset += page
        # Avval ro'yxat to'liq yig'iladi, keyin o'chiriladi: o'chirish sahifalarni surib yubormasin.
        for chat_id in chats:
            counts["chats"] += 1
            if chat_id.startswith(NEW_PREFIX):
                counts["new"] += 1
                continue
            try:
                detail = assistant.get_chat(chat_id, user_id=uid, limit=detail_limit)
            except AssistantError:
                counts["errors"] += 1
                continue
            if not is_legacy(detail):
                continue
            counts["found"] += 1
            if not apply:
                continue
            try:
                assistant.delete_chat(chat_id, user_id=uid)
                counts["deleted"] += 1
            except AssistantError:
                counts["errors"] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.core.config import settings
    from app.services.integrations.assistant import AssistantClient

    parser = argparse.ArgumentParser(description="Eski guruh CRM suhbatlarini agentda o'chirish (bir martalik)")
    parser.add_argument("--apply", action="store_true", help="o'chirish (default - faqat sanash)")
    parser.add_argument("--json", action="store_true", help="sonlar JSON da")
    parser.add_argument("--links", type=Path, default=settings.telegram_links_file)
    parser.add_argument("--analytics", type=Path, default=settings.analytics_db_file)
    args = parser.parse_args(argv)

    assistant = AssistantClient(settings.hrm_assistant_base_url, settings.hrm_assistant_client_id,
                                settings.hrm_assistant_client_secret, timeout=30.0, max_concurrent=1)
    if not assistant.configured:
        print("Agent sozlanmagan (HRM_ASSISTANT_*) - hech narsa qilinmadi", file=sys.stderr)
        return 2
    actors = actors_from_links(args.links) | actors_from_analytics(args.analytics)
    counts = run(assistant, actors, apply=args.apply)
    counts["apply"] = int(bool(args.apply))
    if args.json:
        print(json.dumps(counts, sort_keys=True))
    else:
        mode = "O'CHIRILDI" if args.apply else "DRY-RUN (o'chirish uchun --apply)"
        print(f"{mode}: odamlar {counts['actors']}, suhbatlar {counts['chats']}, yangi (tgcrm-) "
              f"{counts['new']}, eski guruh CRM {counts['found']}, o'chirildi {counts['deleted']}, "
              f"xatolar {counts['errors']}")
    return 1 if counts["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
