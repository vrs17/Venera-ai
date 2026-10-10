"""Rahbariyat brifi - guruh TURIGA qarab karta (2026-10-08, rahbariyat maketi).

🛠 SUPPORT guruhi - murojaatlar: nechta tushdi, nechtasi yechildi, nechtasi
jarayonda; ochiq masalalar (🔴 Bug / 🟡 Taklif / ⚪ Savol) va yechilganlar -
kim ko'tardi, kim yechdi, qancha vaqtda. CRM YO'Q.

📁 LOYIHA guruhi - bir gapli xulosa; 1) nima bajarildi, 2) nima jarayonda
(mas'ullar bilan), 3) to'siqlar va holat. Vazifa holati CRM dan
(`crm_status.py`, so'ragan rahbar nomidan).

SONLAR va HOLAT - Python'da, to'qilmaydi. Loyiha matnini model yozadi -
FAQAT tekshirilgan faktlardan; har maydon alohida tekshiriladi
(`check_narrative`): faktlarda yo'q raqam yoki ism bo'lsa o'sha maydon
Python matni bilan almashadi. Barcha guruhlar ko'rinishi 100 ta guruhgacha
sig'adi - guruhga bitta qator, model chaqirilmaydi (⚡ sarlavhadan tashqari).

Avvalgi batafsil ko'rinish (`briefs.render_brief`) o'zgarmagan - har kartadagi
"📋 Batafsil" tugmasida.
"""

from __future__ import annotations

import json
import re
import statistics

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .briefs import CATEGORIES, SEVERITIES, _FENCE, _due_text, _grounded, _line, section_of, short_title
from .groups import uz_date
from .render import esc

CATEGORY_LABEL = {"bug": "Bug", "feature": "Taklif", "question": "Savol"}
CATEGORY_ICON = {"bug": "🔴", "feature": "🟡", "question": "⚪"}
_CATEGORY_RANK = {"bug": 0, "feature": 1, "question": 2}
#: Kim ko'tardi / kim yechdi - murojaat turiga mos fe'l.
_RAISED = {"bug": "xabar qildi", "feature": "taklif qildi", "question": "so'radi"}
_SOLVED = {"bug": "hal qildi", "feature": "bajardi", "question": "javob berdi"}
_SOLVED_PASSIVE = {"bug": "hal qilindi", "feature": "bajarildi", "question": "javob berildi"}
_RAISED_ANY = "ko'tardi"

STATUS_LABEL = {"red": ("🔴", "To'siq bor"), "orange": ("🟠", "Xavf ostida"), "green": ("🟢", "Barqaror"),
                "none": ("⚪", "Ma'lumot yo'q")}
KIND_ICON = {"support": "🛠", "project": "📁"}

LIST_MAX = 8                 # kartadagi ro'yxat - shuncha, qolgani "… yana N ta"
FACTS_MAX = 12               # model uchun har guruhdan shuncha fakt
OWNERS_MAX = 5
OVERVIEW_BUGS = 5
OVERVIEW_SUPPORT = 15        # barcha guruhlar: support guruhlari qatori
OVERVIEW_PROJECTS = 30       # barcha guruhlar: loyiha guruhlari qatori
MIN_DURATION = 60.0          # bundan qisqa "yechilish vaqti" ko'rsatilmaydi (bir zumda forward)


def duration_text(seconds: float | None) -> str:
    """`2 soat 15 daqiqa`, `3 kun 4 soat`, `25 daqiqa`; 60 s dan kam - bo'sh."""
    if seconds is None or seconds < MIN_DURATION:
        return ""
    minutes = int(seconds // 60)
    days, rest = divmod(minutes, 1440)
    hours, mins = divmod(rest, 60)
    if days:
        return f"{days} kun" + (f" {hours} soat" if hours else "")
    if hours:
        return f"{hours} soat" + (f" {mins} daqiqa" if mins else "")
    return f"{mins} daqiqa"


def resolution(item: dict[str, Any]) -> float | None:
    """Yechilish vaqti: murojaat ko'tarilgandan yechilgangacha (ikkalasi ham ko'rilgan bo'lsa)."""
    start, done = item.get("start_at"), item.get("done_at")
    if item.get("status") != "done" or not isinstance(start, (int, float)) or not isinstance(done, (int, float)):
        return None
    value = done - start
    return value if value >= MIN_DURATION else None


# --- support ------------------------------------------------------------------------------


@dataclass
class SupportView:
    issues: list[dict[str, Any]]
    open: list[dict[str, Any]]
    solved: list[dict[str, Any]]
    categories: Counter = field(default_factory=Counter)
    typical: float | None = None


def support_view(items: list[dict[str, Any]]) -> SupportView:
    """Murojaatlar: qaror emas - hammasi (support yo'riqnomasida har murojaat bitta hodisa)."""
    issues = [i for i in items if i.get("type") != "decision"]
    solved = [i for i in issues if i.get("status") == "done"]
    opened = [i for i in issues if i.get("status") != "done"]
    opened.sort(key=lambda i: (_CATEGORY_RANK.get(i.get("category"), 3), SEVERITIES.index(i.get("severity", "medium")),
                               i.get("start_at") or i.get("first_at") or i["at"]))
    solved.sort(key=lambda i: -(i.get("done_at") or i["at"]))
    durations = [d for d in (resolution(i) for i in solved) if d is not None]
    return SupportView(issues=issues, open=opened, solved=solved,
                       categories=Counter(i["category"] for i in issues if i.get("category") in CATEGORIES),
                       typical=statistics.median(durations) if len(durations) >= 3 else None)


def _categories_line(categories: Counter, typical: float | None = None) -> str:
    parts = [f"{CATEGORY_ICON[c]} {CATEGORY_LABEL[c]} {categories[c]}" for c in CATEGORIES if categories.get(c)]
    if typical is not None:
        parts.append(f"⏱ odatda {duration_text(typical)}")
    return f"<i>{' · '.join(parts)}</i>" if parts else ""


def _since(item: dict[str, Any], now: float) -> str:
    since = item.get("start_at") or item.get("first_at")
    return f" · {uz_date(since, now=now)}dan beri" if isinstance(since, (int, float)) else ""


def _open_line(n: int, item: dict[str, Any], now: float) -> str:
    category = item.get("category")
    head = f"{CATEGORY_ICON[category]} <b>{CATEGORY_LABEL[category]}</b> · " if category in CATEGORIES else ""
    line = f"{n}. {head}{esc(item['title'])}{_since(item, now)}"
    if item.get("owner"):
        line += f" · 👤 {esc(item['owner'])}"
    return line


def _solved_line(n: int, item: dict[str, Any], now: float) -> str:
    category = item.get("category")
    icon = f"{CATEGORY_ICON[category]} " if category in CATEGORIES else ""
    parts: list[str] = []
    if item.get("raised_by"):
        parts.append(f"{esc(item['raised_by'])} {_RAISED.get(category, _RAISED_ANY)}")
    took = duration_text(resolution(item))
    done = item.get("done_at") or item["at"]
    if item.get("owner"):
        parts.append(f"{esc(item['owner'])} {_SOLVED.get(category, 'hal qildi')}")
        parts.append(took or uz_date(done, now=now))
    else:
        passive = _SOLVED_PASSIVE.get(category, "hal qilindi")
        parts.append(f"{passive} · {took}" if took else f"{passive} {uz_date(done, now=now)}")
    return f"{n}. {icon}{esc(item['title'])} — " + " · ".join(parts)


def render_support(view: SupportView, *, head: str, now: float) -> list[str]:
    """Bitta support guruhi kartasi (maket bo'yicha)."""
    counts = (f"1. Muammolar: <b>{len(view.issues)}</b>\n2. Yechildi: <b>{len(view.solved)}</b>\n"
              f"3. Jarayonda: <b>{len(view.open)}</b>")
    extra = _categories_line(view.categories, view.typical)
    blocks = [head, counts + (f"\n{extra}" if extra else "")]
    if not view.issues:
        blocks.append("Bu davrda murojaat qayd etilmagan.")
        return blocks
    if view.open:
        lines = [_open_line(n, item, now) for n, item in enumerate(view.open[:LIST_MAX], 1)]
        if len(view.open) > LIST_MAX:
            lines.append(f"<i>… yana {len(view.open) - LIST_MAX} ta</i>")
        blocks.append("📂 <b>Ochiq masalalar</b>\n" + "\n".join(lines))
    if view.solved:
        lines = [_solved_line(n, item, now) for n, item in enumerate(view.solved[:LIST_MAX], 1)]
        if len(view.solved) > LIST_MAX:
            lines.append(f"<i>… yana {len(view.solved) - LIST_MAX} ta</i>")
        blocks.append("✅ <b>Yechildi</b>\n" + "\n".join(lines))
    return blocks


# --- loyiha -------------------------------------------------------------------------------


@dataclass
class ProjectView:
    done: list[dict[str, Any]]
    active: list[dict[str, Any]]
    deadlines: list[dict[str, Any]]
    blockers: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    status: str
    owners: list[str]
    more_owners: int = 0

    @property
    def empty(self) -> bool:
        return not (self.done or self.active or self.deadlines or self.blockers or self.decisions)


def project_view(items: list[dict[str, Any]], now: float) -> ProjectView:
    """Bo'limlar - batafsil ko'rinishdagi AYNI qoida (`section_of`): sonlar mos keladi."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        buckets.setdefault(section_of(item, now), []).append(item)
    blockers = sorted(buckets.get("attention", []), key=lambda i: (SEVERITIES.index(i["severity"]), -i["at"]))
    active = buckets.get("tasks", []) + buckets.get("requests", [])
    if not items:
        status = "none"
    elif any(i.get("status") == "blocked" or (i["type"] == "problem" and i["severity"] == "high") for i in blockers):
        status = "red"
    elif blockers:
        status = "orange"
    else:
        status = "green"
    counts = Counter(i["owner"] for i in active + blockers if i.get("owner"))
    owners = [name for name, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))]
    return ProjectView(done=sorted(buckets.get("done", []), key=lambda i: -i["at"]), active=active,
                       deadlines=buckets.get("deadlines", []), blockers=blockers,
                       decisions=buckets.get("decisions", []), status=status, owners=owners[:OWNERS_MAX],
                       more_owners=max(0, len(owners) - OWNERS_MAX))


PROJECT_PROMPT = """Sen Barno - rahbariyat yordamchisisan. Quyida BITTA loyiha guruhining shu davrdagi tekshirilgan faktlari bor (CRM holati qo'shilgan). Rahbar uchun loyiha holatini yoz.
Javob - FAQAT JSON: {"summary": "...", "done": "...", "progress": "...", "blockers": "..."}
- summary - BITTA gap: loyihaning hozirgi holati.
- done - 1-3 gap: nima bajarildi. Muhim natija bo'lsa "Tabriklayman!" bilan boshlash mumkin. Bajarilgan ish bo'lmasa - "".
- progress - 1-3 gap: hozir nima ustida ishlanmoqda; muddat yoki baho faktlarda bo'lsa - ayt. Bo'lmasa - "".
- blockers - 1-2 gap: to'siq va xavflar. Yo'q bo'lsa - "".
QOIDALAR: faqat berilgan faktlar - yangi ism, sana, raqam yoki loyiha nomi QO'SHMA. Mas'ullar ro'yxatini yozma (u alohida ko'rsatiladi). Sana - "7-oktyabr" ko'rinishida. Oddiy gaplar, markdown yo'q, o'zbekcha lotin yozuvida."""

_LIMITS = {"summary": 220, "done": 500, "progress": 500, "blockers": 350}
_NUMBER = re.compile(r"\d+(?:[.,:-]\d+)*")
_NAME = re.compile(r"(?<![\w'ʻʼ‘’])([A-ZА-ЯЁЎҚҒҲ][a-zа-яёўқғҳ'ʻʼ‘’]{2,})")
_CALM = re.compile(r"barqaror|to'siq\w*\s+(?:yo'q|mavjud emas)|muammo\w*\s+yo'q", re.IGNORECASE)


def project_facts(view: ProjectView, *, title: str, now: float) -> list[str]:
    """Model uchun fakt qatorlari (keyin `_clean` va chegara belgisi bilan o'raladi)."""
    icon, label = STATUS_LABEL[view.status]

    def fact(item: dict[str, Any]) -> str:
        line = f"- {item['title']}"
        if item.get("detail"):
            line += f" — {item['detail']}"
        extra = [f"mas'ul {item['owner']}" if item.get("owner") else "",
                 f"muddat {_due_text(item['due'], now)}" if item.get("due") else ""]
        crm = item.get("crm") or {}
        if crm:
            extra.append(f"CRM: {crm.get('key') or ''} {crm.get('raw') or ''}".strip())
        extra = [x for x in extra if x]
        return line + (f" ({'; '.join(extra)})" if extra else "")

    lines = [f"Loyiha: {title}", f"Holat: {label}"]
    for heading, bucket in (("BAJARILDI", view.done), ("JARAYONDA", view.active), ("MUDDATLAR", view.deadlines),
                            ("TO'SIQ VA XAVFLAR", view.blockers), ("QARORLAR", view.decisions)):
        if bucket:
            lines.append(f"{heading} ({len(bucket)}):")
            lines.extend(fact(item) for item in bucket[:FACTS_MAX])
    return lines


def parse_object(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    fence = _FENCE.search(text)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _cap(text: str, limit: int) -> str:
    """Gap chegarasida qisqartirish."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    stop = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[:stop + 1] if stop > limit // 3 else cut[:limit - 1].rstrip() + "…"


#: Gap boshida bosh harf bilan keladigan oddiy so'zlar - ism emas.
_STARTERS = frozenset({
    "bu", "shu", "ushbu", "hozir", "hozirda", "hali", "loyiha", "loyihada", "loyihaning", "loyihadagi",
    "tabriklayman", "barcha", "asosiy", "muhim", "yangi", "keyingi", "ammo", "lekin", "biroq", "shuningdek",
    "hech", "ish", "ishlar", "jarayonda", "bajarildi", "holat", "holati", "davr", "davrda", "muddat",
    "jamoa", "jamoada", "mijoz", "mijozlar", "ular", "biz", "endi", "shuning", "natijada", "afsuski",
})


def ungrounded(text: str, blob: str) -> list[str]:
    """Faktlarda yo'q raqam va ismlar. Raqam - BUTUN bo'lak bo'yicha ("5" faktdagi
    "15:00" ichida bo'lgani uchun o'tib ketmasin); bosh harfli so'z - har joyda,
    gap boshidagi oddiy so'zlardan (`_STARTERS`) tashqari."""
    numbers = set(_NUMBER.findall(blob))
    bad = [n for n in _NUMBER.findall(text) if n not in numbers]
    lowered = blob.lower()
    for match in _NAME.finditer(text):
        word = match.group(1)
        if word.lower() in _STARTERS:
            continue
        if not _grounded(word, lowered):
            bad.append(word)
    return bad


def check_narrative(raw: str, view: ProjectView, blob: str) -> dict[str, str]:
    """Model javobi -> qabul qilingan maydonlar (qolgani Python matni bilan)."""
    data = parse_object(raw) or {}
    out: dict[str, str] = {}
    for key, limit in _LIMITS.items():
        value = data.get(key)
        if not isinstance(value, str):
            continue
        text = " ".join(re.sub(r"\*\*|__|`", "", value).split())
        if not text:
            continue
        text = _cap(text, limit)
        if ungrounded(text, blob):
            continue
        if key == "done" and not view.done:
            continue
        if key == "progress" and not (view.active or view.deadlines):
            continue
        if key == "blockers" and view.status in ("green", "none"):
            continue
        if key in ("summary", "blockers") and view.status in ("red", "orange") and _CALM.search(text):
            continue
        out[key] = text
    return out


def _fallback_summary(view: ProjectView) -> str:
    if view.empty:
        return "Bu davrda loyiha bo'yicha muhim hodisa qayd etilmagan."
    tail = (f"{len(view.blockers)} ta masala e'tibor talab qiladi." if view.blockers else "to'siq yo'q.")
    return f"{len(view.done)} ta ish bajarildi, {len(view.active)} tasi jarayonda; {tail}"


def _bullets(items: list[dict[str, Any]], now: float, empty: str) -> str:
    if not items:
        return empty
    lines = [_line(item, now, "") for item in items[:LIST_MAX]]
    if len(items) > LIST_MAX:
        lines.append(f"<i>… yana {len(items) - LIST_MAX} ta</i>")
    return "\n".join(lines)


def render_project(view: ProjectView, narrative: dict[str, str], *, head: str, now: float) -> list[str]:
    """Bitta loyiha guruhi kartasi (maket bo'yicha)."""
    icon, label = STATUS_LABEL[view.status]
    summary = narrative.get("summary") or _fallback_summary(view)
    done = esc(narrative["done"]) if "done" in narrative else _bullets(
        view.done, now, "Bu davrda bajarilgan ish qayd etilmagan.")
    progress = esc(narrative["progress"]) if "progress" in narrative else _bullets(
        view.active + view.deadlines, now, "Jarayondagi ish qayd etilmagan.")
    if view.owners:
        more = f" va yana {view.more_owners} kishi" if view.more_owners else ""
        progress += f"\n👤 Mas'ullar: {esc(', '.join(view.owners))}{more}"
    if "blockers" in narrative:
        blockers = esc(narrative["blockers"])
    elif view.status in ("green", "none"):
        blockers = "Bu loyiha uchun to'siqlar yo'q."
    else:
        blockers = _bullets(view.blockers, now, "")
    footer = (f"<i>✅ {len(view.done)} bajarildi · 🔄 {len(view.active)} jarayonda · "
              f"🚧 {len(view.blockers)} to'siq</i>")
    return [head, f"<b>{esc(summary)}</b>", f"1. ✅ <b>Bajarildi</b>\n{done}",
            f"2. 🔄 <b>Jarayonda</b>\n{progress}", f"3. {icon} <b>Holati: {label}</b>\n{blockers}", footer]


# --- barcha guruhlar --------------------------------------------------------------------------


@dataclass
class GroupLine:
    """Barcha guruhlar ko'rinishidagi bitta guruh (Python hisoblaydi)."""

    chat_id: int
    title: str
    kind: str
    messages: int
    support: SupportView | None = None
    project: ProjectView | None = None
    crm_found: int = 0

    @property
    def rank(self) -> int:
        """Tugmalar tartibi: eng yomoni birinchi."""
        if self.support is not None:
            if any(i.get("category") == "bug" and i.get("severity") == "high" for i in self.support.open):
                return 0
            return 1 if self.support.open else 2
        status = self.project.status if self.project is not None else "none"
        return {"red": 0, "orange": 1, "green": 2, "none": 3}[status]


def render_overview(lines: list[GroupLine], *, head: str, headline: list[str], now: float) -> list[str]:
    blocks = [head]
    if headline:
        blocks.append("⚡ <b>Asosiy</b>\n" + "\n".join(f"• {esc(line)}" for line in headline))
    support = [g for g in lines if g.support is not None]
    if support:
        issues = sum(len(g.support.issues) for g in support)
        solved = sum(len(g.support.solved) for g in support)
        opened = sum(len(g.support.open) for g in support)
        categories: Counter = Counter()
        for g in support:
            categories.update(g.support.categories)
        text = [f"🛠 <b>Qo'llab-quvvatlash</b> · {len(support)} ta guruh",
                f"Muammolar: <b>{issues}</b> · Yechildi: <b>{solved}</b> · Jarayonda: <b>{opened}</b>"]
        extra = _categories_line(categories)
        if extra:
            text.append(extra)
        bugs = sorted(((i, g) for g in support for i in g.support.open if i.get("category") == "bug"),
                      key=lambda pair: (SEVERITIES.index(pair[0].get("severity", "medium")),
                                        pair[0].get("start_at") or pair[0]["at"]))
        if bugs:
            text.append("Ochiq buglar:")
            text.extend(f"{n}. {esc(item['title'])} · <i>{esc(short_title(g.title))}</i>{_since(item, now)}"
                        for n, (item, g) in enumerate(bugs[:OVERVIEW_BUGS], 1))
            if len(bugs) > OVERVIEW_BUGS:
                text.append(f"<i>… yana {len(bugs) - OVERVIEW_BUGS} ta</i>")
        for g in sorted(support, key=lambda g: (g.rank, -len(g.support.open), g.title.lower()))[:OVERVIEW_SUPPORT]:
            parts = [f"{len(g.support.issues)} murojaat"]
            if g.support.solved:
                parts.append(f"✅ {len(g.support.solved)}")
            if g.support.open:
                parts.append(f"🔄 {len(g.support.open)}")
            bug_count = sum(1 for i in g.support.open if i.get("category") == "bug")
            if bug_count:
                parts.append(f"🔴 {bug_count} bug")
            text.append(f"• {esc(g.title)} — " + " · ".join(parts))
        if len(support) > OVERVIEW_SUPPORT:
            text.append(f"<i>… yana {len(support) - OVERVIEW_SUPPORT} ta guruh</i>")
        blocks.append("\n".join(text))
    projects = [g for g in lines if g.support is None]
    if projects:
        text = [f"📁 <b>Loyihalar</b> · {len(projects)} ta"]
        ordered = sorted(projects, key=lambda g: (g.rank, -(len(g.project.blockers) if g.project else 0),
                                                  -g.messages, g.title.lower()))
        for g in ordered[:OVERVIEW_PROJECTS]:
            view = g.project
            icon = STATUS_LABEL[view.status if view else "none"][0]
            parts = []
            if view is not None:
                for mark, count in (("✅", len(view.done)), ("🔄", len(view.active)), ("🚧", len(view.blockers)),
                                    ("🗂", g.crm_found)):
                    if count:
                        parts.append(f"{mark} {count}")
            text.append(f"{icon} {esc(g.title)} — " + (" · ".join(parts) if parts else "hodisa yo'q"))
        if len(ordered) > OVERVIEW_PROJECTS:
            rest = Counter(STATUS_LABEL[g.project.status if g.project else "none"][0] for g in ordered[OVERVIEW_PROJECTS:])
            text.append(f"<i>… yana {len(ordered) - OVERVIEW_PROJECTS} ta: "
                        + " · ".join(f"{icon} {n}" for icon, n in rest.items()) + "</i>")
        blocks.append("\n".join(text))
    return blocks


def drill_order(lines: list[GroupLine], limit: int) -> list[GroupLine]:
    return sorted(lines, key=lambda g: (g.rank, -g.messages, g.title.lower()))[:limit]
