"""Bayonnoma qatorlarini tanlash - ombor qatorlari ustidagi sof funksiyalar (`service` ni IMPORT QILMAYDI).

Dvigatel (`minutes/__init__`), chat modeli ko'radigan holat (`state`) va chat navbati (`service`) BITTA ta'rifdan
foydalanadi:

    HEAD (`ready_row`)         joriy transkript VERSIYASI (`transcript_rev`) bo'yicha tilning eng keyin TAYYOR bo'lgan hujjati
                               (`prompt.READY_VERSIONS`, mazmuni bor) - til tugmasi bosilganda qayta yuboriladigani
    BASE (`base_row`)          tahrir asosi: joriy transkript AVLODI (`transcript_gen`) bo'yicha eng keyin tayyor bo'lgan
                               hujjat. Qator tahriri va spikerlarni birlashtirishdan keyin ham (`transcript_rev` oshgan)
                               - qator id lari o'zgarmagan, hujjatni tahrirlash mumkin; qayta o'girilgandan keyin - yo'q
    joriy til (`current_lang`) eng yangi BASE hujjatning tili (har til ichidan) - "bayonnomani o'zgartir" shu tilga
    qamrov (`snapshot`, `pending`)  hujjat yozilganda qaysi ko'rsatmalar berilgan; berilmagan faollari - kutilayotgan
    tiriklik (`stale_after`, `is_live`)  `running` qator eskirmagan bo'lsa - uni yozayotgan ip tirik

`pick_*` - bitta `store.minutes_rows` ro'yxati ustida (holat bloki bir so'rov bilan hamma tilni ko'radi), qolganlari -
shularning ombor bilan o'ramlari.

NEGA ALOHIDA MODUL. `minutes/__init__` `service` ni import qiladi, `service` esa chat navbatida bayonnoma holatini
o'qiydi: bu yordamchilar `minutes/__init__` da tursa - `service` <-> `minutes` aylanma bog'liqligi. Bu yerda faqat
ombor qatorlari, sozlamalar va prompt versiyalari.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Sequence

from ....core.config import settings
from ..store import jload
from . import prompt

#: Eskirgan `running` qator chegarasi ustiga zaxira (soniya): prompt yig'ish, tekshiruv, ombor, havza navbati.
STALE_MARGIN_SEC = 300


def stale_after() -> float:
    """`running` qator shuncha soniyadan eski bo'lsa - TIRIK EMAS: uni yozayotgan ip jarayon bilan birga
    o'lgan (restart, yiqilish). Aks holda qator abadiy "yozilmoqda" bo'lib, yangi bosishni ham o'ziga
    qo'shib yutib turardi. Chegara - eng yomon model vaqti (`ClaudeChat.complete_meta`): slotni kutish
    (`meetings_claude_timeout` gacha) + har urinish (`meetings_claude_retries` + 1) shu chegaragacha, ustiga
    `STALE_MARGIN_SEC`. Default: 600 x (1 + 3) + 300 = 2700 s (45 daqiqa)."""
    timeout = max(0.0, float(settings.meetings_claude_timeout))
    attempts = max(0, int(settings.meetings_claude_retries)) + 1
    return timeout * (1 + attempts) + STALE_MARGIN_SEC


def is_live(row: Mapping[str, Any], now: float) -> bool:
    """`running` va `stale_after()` dan yosh - uni yozayotgan ip tirik. Ombor O'ZGARMAYDI: eskirganini `failed` /
    `interrupted` deb yozish - dvigatelning `_settle` ishi."""
    return row.get("status") == "running" and now - float(row.get("created_at") or 0) <= stale_after()


def snapshot(row: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Hujjat yozilganda berilgan ko'rsatmalar (`guidance_json.notes`): [{"id", "text"}]; eski qatorda []."""
    data = jload(row.get("guidance_json")) if row else None
    notes = data.get("notes") if isinstance(data, dict) else None
    return [n for n in notes if isinstance(n, dict) and n.get("id")] if isinstance(notes, list) else []


def applied_ids(row: Mapping[str, Any] | None) -> set[str]:
    """Hujjatga berilgan ko'rsatmalar id lari (kesilganlari ham - abadiy "kutilayotgan" bo'lib qolmasin)."""
    return {str(n["id"]) for n in snapshot(row)}


def pending(row: Mapping[str, Any] | None, notes: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Faol ko'rsatmalardan (`store.notes`, eskisi birinchi) shu hujjatda hali yo'qlari."""
    done = applied_ids(row)
    return [n for n in notes if str(n.get("id")) not in done]


def _ready(row: Mapping[str, Any]) -> bool:
    """Tayyor, mazmuni bor va prompt versiyasi `READY_VERSIONS` da (HEAD bilan bir xil ta'rif)."""
    return row.get("status") == "ready" and bool(row.get("content_json")) \
        and row.get("prompt_version") in prompt.READY_VERSIONS


def _done_at(row: Mapping[str, Any]) -> int:
    """Hujjat qachon TAYYOR bo'lgani (`finished_at`; eski qatorda - `created_at`)."""
    return int(row.get("finished_at") or row.get("created_at") or 0)


def newest_ready(rows: Sequence[Mapping[str, Any]],
                 keep: Callable[[Mapping[str, Any]], bool] = lambda row: True) -> dict[str, Any] | None:
    """`keep` dan o'tgan tayyor qatorlardan JORIYI: zanjir UCHI (boshqa tayyor qatorning ota-versiyasi emas), ulardan
    eng keyin tayyor bo'lgani (bir soniyada - keyin yaratilgani).

    NEGA YARATILISH TARTIBI EMAS. Navbatdagi ishlar `_lock` ni istalgan tartibda olishi mumkin (qulf adolatli emas; til
    tugmasi o'z ipida): R1 (oldin so'ralgan) kutib turganda R2 tayyor bo'ladi, R1 esa uning ustiga yoziladi (`_run`
    asosni qulf ichida qayta tanlaydi - R1 ning ota-versiyasi R2). Yaratilish tartibida "joriy" R2 bo'lib qolardi - R1
    ning o'zgarishi joriy hujjatdan, keyingi tahrirlardan va qayta yuborishdan tushib qolardi. Ota-versiya bo'lgan qator
    uch emas; zanjirlar orasida (masalan «Qayta yozish» - yangi asl hujjat) - eng keyin tayyor bo'lgani."""
    found = [(index, row) for index, row in enumerate(rows) if _ready(row) and keep(row)]
    if not found:
        return None
    parents = {row.get("parent_id") for _, row in found if row.get("parent_id")}
    tips = [item for item in found if item[1].get("id") not in parents] or found
    _, best = max(tips, key=lambda item: (_done_at(item[1]), item[0]))
    return dict(best)


def _same_gen(row: Mapping[str, Any], m: Mapping[str, Any]) -> bool:
    """Qator joriy transkript avlodida yozilganmi (NULL - v8 dan oldingi eski versiya bo'yicha: noma'lum, yo'q)."""
    gen = row.get("transcript_gen")
    return gen is not None and int(gen) == int(m.get("transcript_gen") or 0)


def pick_base(rows: Sequence[Mapping[str, Any]], m: Mapping[str, Any],
              lang: str) -> tuple[dict[str, Any] | None, str | None]:
    """BASE (ro'yxatdan; eng keyin tayyor bo'lgani - `newest_ready`) -> (qator, None). Yo'q bo'lsa: shu tilda boshqa
    avlodning tayyor hujjati bor (yozuv qayta o'girilgan) - (None, "minutes_outdated"), aks holda
    (None, "minutes_missing")."""
    found = newest_ready(rows, lambda row: row.get("language") == lang and _same_gen(row, m))
    if found is not None:
        return found, None
    if any(row.get("language") == lang and _ready(row) for row in rows):
        return None, "minutes_outdated"
    return None, "minutes_missing"


def pick_current(rows: Sequence[Mapping[str, Any]], m: Mapping[str, Any]) -> dict[str, Any] | None:
    """Har til ichidan eng keyin tayyor bo'lgan joriy-avlod hujjat (yoki `None`)."""
    return newest_ready(rows, lambda row: _same_gen(row, m))


def ready_row(store: Any, meeting_id: str, lang: str, rev: int) -> dict[str, Any] | None:
    """HEAD: shu tilda joriy transkript versiyasi (`rev`) bo'yicha eng keyin tayyor bo'lgan hujjat - prompt versiyasi
    `READY_VERSIONS` da (minutes-2 hujjati ham qayta ishlatiladi: deploy pullik qayta yozish keltirmaydi)."""
    return newest_ready(store.minutes_rows(meeting_id),
                        lambda row: row["language"] == lang and int(row["transcript_rev"]) == int(rev))


def base_row(store: Any, m: Mapping[str, Any], lang: str) -> tuple[dict[str, Any] | None, str | None]:
    """BASE - tahrir asosi (`pick_base`): (qator, None) yoki (None, "minutes_outdated" | "minutes_missing")."""
    return pick_base(store.minutes_rows(m["id"]), m, lang)


def current_lang(store: Any, m: Mapping[str, Any]) -> str | None:
    """Eng yangi joriy-avlod tayyor hujjatning tili - hujjat yo'q bo'lsa `None`."""
    row = pick_current(store.minutes_rows(m["id"]), m)
    return row["language"] if row else None
