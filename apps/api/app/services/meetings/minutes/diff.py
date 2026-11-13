"""Bayonnoma versiyalari orasidagi o'zgarishlar (`changes`) va ularning o'zbekcha qisqa bayoni (`summary_uz`).

Tahrirdan keyin odamga "3, 7-bandlar o'zgardi; 8-band qo'shildi; rais yangilandi" ko'rsatiladi (Slack, Telegram,
ilova). Bo'sh o'zgarish (`empty`) - o'zgartirish so'rovi hujjatga ta'sir qilmadi: yangi versiya saqlanmaydi, odamga
aniqroq yozish aytiladi.

    changes(old, new) -> {"items": {"changed": [yangi raqamlar], "added": [yangi raqamlar],
                                    "removed": [eski raqamlar]},
                          "agenda": {"changed": [...], "added": [...], "removed": [...]},
                          "header": [farq qilgan `HEADER_KEYS`],
                          "other": ["title" | "preamble" | "controller" | "notes"]}

BANDLAR Word dagi raqamlar bilan (`compose.numbering`, kod qo'shadigan nazorat bandisiz) solishtiriladi. Imzo - tur,
muddat, mas'ullar, matn, kichik bandlar va "Bunda" davomi; manba qatorlar va ishonch E'TIBORGA OLINMAYDI (model ularni
qayta tanlashi - odam uchun o'zgarish emas). `difflib.SequenceMatcher` ketma-ketlikni tekislaydi: o'rtaga band
qo'shilsa, keyingilarining raqami siljiydi, lekin ular "o'zgardi" deb ko'rsatilmaydi. `replace` bo'lagida juftlar
(kamroq tomon soni) - o'zgargan, ortig'i - qo'shilgan yoki olib tashlangan.

KO'CHIRILGAN BAND. Matni o'zgarmagan, lekin boshqa kun tartibi masalasining bo'limiga o'tkazilgan band ham "o'zgardi"
(aks holda "3-bandni II bo'limga o'tkazing" so'rovi bajarilsa ham "o'zgarish yo'q" deyilardi). Masala raqami emas -
kun tartibi tekislashidagi mos masala solishtiriladi: masala olib tashlanib, keyingilarining `agendaIndex` i siljisa,
bandlar o'zgarmagan hisoblanadi.
"""

from __future__ import annotations

import difflib
import json

from typing import Any, NamedTuple, Sequence

from . import compose, validate

#: Sarlavha qismi kalitlari - odamga ko'rinadigan nomlar (`summary_uz`, Slack/Telegram xabari).
HEADER_NAMES_UZ = {"organization": "tashkilot nomi", "chairedBy": "kim huzurida", "city": "shahar",
                   "chair": "rais", "attendees": "qatnashchilar"}
#: Bandlar va kun tartibidan tashqari solishtiriladigan kalitlar (shu tartibda) va ularning nomlari.
OTHER_KEYS = ("title", "preamble", "controller", "notes")
OTHER_NAMES_UZ = {"title": "sarlavha", "preamble": "kirish gapi", "controller": "nazorat bandi", "notes": "izohlar"}


class _Item(NamedTuple):
    number: int            # Word dagi raqami
    agenda: int | None     # bo'limining kun tartibi raqami (1-based; yaroqsiz - None)
    signature: str


def _signature(values: Sequence[Any]) -> str:
    return json.dumps(list(values), ensure_ascii=False)


def _items(content: dict[str, Any]) -> list[_Item]:
    agenda_count = len([a for a in (content.get("agenda") or []) if isinstance(a, dict)])
    sections = compose.sections_of(content)
    out: list[_Item] = []
    for n in compose.numbering(content):
        if n.control:
            continue
        section = sections[n.section - 1]
        item = compose.items_of(section)[n.index]
        index = section.get("agendaIndex")
        valid = isinstance(index, int) and not isinstance(index, bool) and 1 <= index <= agenda_count
        out.append(_Item(n.number, index if valid else None, _signature(
            [item.get(k) for k in ("kind", "deadline", "deadlineDate", "responsible", "text", "subpoints",
                                   "followUp")])))
    return out


def _agenda(content: dict[str, Any]) -> list[str]:
    return [_signature([a.get("title"), a.get("report"), a.get("speakers")])
            for a in (content.get("agenda") or []) if isinstance(a, dict)]


def _compare(old: Sequence[str], new: Sequence[str], old_nos: Sequence[int], new_nos: Sequence[int]
             ) -> tuple[dict[str, list[int]], list[tuple[int, int]], list[tuple[int, int]]]:
    """Ikki imzo ketma-ketligi -> ({"changed", "added", "removed"} raqamlari, o'zgarmagan juftlar, o'zgargan juftlar);
    juftlar - (eski indeks, yangi indeks)."""
    out: dict[str, list[int]] = {"changed": [], "added": [], "removed": []}
    same: list[tuple[int, int]] = []
    paired: list[tuple[int, int]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, list(old), list(new), autojunk=False).get_opcodes():
        if tag == "equal":
            same += list(zip(range(i1, i2), range(j1, j2)))
            continue
        k = min(i2 - i1, j2 - j1)                      # insert / delete - 0, replace - juftlar soni
        out["changed"] += list(new_nos[j1:j1 + k])
        paired += list(zip(range(i1, i1 + k), range(j1, j1 + k)))
        out["removed"] += list(old_nos[i1 + k:i2])
        out["added"] += list(new_nos[j1 + k:j2])
    return out, same, paired


def _header(content: dict[str, Any]) -> dict[str, Any]:
    raw = content.get("header") if isinstance(content.get("header"), dict) else {}
    out: dict[str, Any] = {}
    for key in validate.HEADER_KEYS:
        value = raw.get(key)
        if key == "attendees":
            out[key] = [str(a) for a in value] if isinstance(value, list) else []
        else:
            out[key] = value if isinstance(value, str) and value.strip() else None
    return out


def _plain(value: Any) -> Any:
    """`other` kalitlarini solishtirish: bo'sh qiymatlar (None, "", []) bir xil."""
    return value or None


def changes(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Eski va yangi mazmun orasidagi o'zgarishlar (modul hujjatidagi shakl); raqamlar o'sish tartibida."""
    old, new = old or {}, new or {}
    old_agenda, new_agenda = _agenda(old), _agenda(new)
    agenda, same, paired = _compare(old_agenda, new_agenda, range(1, len(old_agenda) + 1),
                                    range(1, len(new_agenda) + 1))
    moved_to = {i + 1: j + 1 for i, j in same + paired}            # eski masala raqami -> yangisi
    old_items, new_items = _items(old), _items(new)
    items, same_items, _ = _compare([x.signature for x in old_items], [x.signature for x in new_items],
                                    [x.number for x in old_items], [x.number for x in new_items])
    for i, j in same_items:
        before, after = old_items[i].agenda, new_items[j].agenda
        if (moved_to.get(before) if before is not None else None) != after:
            items["changed"].append(new_items[j].number)           # matn o'sha, bo'lim boshqa - ko'chirilgan
    old_header, new_header = _header(old), _header(new)
    return {"items": {key: sorted(set(value)) for key, value in items.items()},
            "agenda": {key: sorted(set(value)) for key, value in agenda.items()},
            "header": [key for key in validate.HEADER_KEYS if old_header[key] != new_header[key]],
            "other": [key for key in OTHER_KEYS if _plain(old.get(key)) != _plain(new.get(key))]}


def empty(ch: dict[str, Any] | None) -> bool:
    """Hech narsa o'zgarmaganmi (`None` - ham bo'sh)."""
    if not ch:
        return True
    groups = (ch.get("items") or {}, ch.get("agenda") or {})
    return not any(any(group.get(key) for key in ("changed", "added", "removed")) for group in groups) \
        and not ch.get("header") and not ch.get("other")


def _numbers(values: Sequence[int], one: str, many: str) -> str:
    """[3] -> "3-band"; [3, 7] -> "3, 7-bandlar"."""
    return f"{', '.join(str(v) for v in values)}-{one if len(values) == 1 else many}"


def summary_uz(ch: dict[str, Any] | None) -> str:
    """O'zgarishlarning o'zbekcha qisqa bayoni (qismlar "; " bilan, oxirida nuqtasiz), masalan: "3, 7-bandlar
    o'zgardi; 8-band qo'shildi; avvalgi 4-band olib tashlandi; kun tartibining 2-masalasi o'zgardi; rais,
    qatnashchilar yangilandi; sarlavha o'zgardi". Bo'sh o'zgarish - ""."""
    if empty(ch):
        return ""
    ch = ch or {}
    items, agenda = ch.get("items") or {}, ch.get("agenda") or {}
    parts: list[str] = []
    if items.get("changed"):
        parts.append(f"{_numbers(items['changed'], 'band', 'bandlar')} o'zgardi")
    if items.get("added"):
        parts.append(f"{_numbers(items['added'], 'band', 'bandlar')} qo'shildi")
    if items.get("removed"):
        parts.append(f"avvalgi {_numbers(items['removed'], 'band', 'bandlar')} olib tashlandi")
    if agenda.get("changed"):
        parts.append(f"kun tartibining {_numbers(agenda['changed'], 'masalasi', 'masalalari')} o'zgardi")
    if agenda.get("added"):
        parts.append(f"kun tartibiga {_numbers(agenda['added'], 'masala', 'masalalar')} qo'shildi")
    if agenda.get("removed"):
        parts.append(f"kun tartibidan avvalgi {_numbers(agenda['removed'], 'masala', 'masalalar')} olib tashlandi")
    if ch.get("header"):
        parts.append(f"{', '.join(HEADER_NAMES_UZ.get(k, k) for k in ch['header'])} yangilandi")
    if ch.get("other"):
        parts.append(f"{', '.join(OTHER_NAMES_UZ.get(k, k) for k in ch['other'])} o'zgardi")
    return "; ".join(parts)
