"""Eksport: xulosa (Markdown/TXT), transkript (TXT/SRT) - KOD chizadi, model emas.

`[S1]` tokenlari ismga almashtiriladi (ism bo'lmasa "1-ishtirokchi" /
"Участник 1" / "Speaker 1"), birlashtirilgan spikerlar (`mergedInto`)
qo'llanadi, sarlavhalar `layout` dan, sanalar til bo'yicha.

TO'LIQ HUJJAT (2026-10-10, `GET /meetings/{id}/export`): Plaud'dagidek bitta fayl -
sarlavha, sana, davomiylik, ishtirokchilar, xulosa bo'limlari (shablon tartibida),
vazifalar JADVALI (CRM kaliti bilan), aqliy xarita (ierarxiya ko'rinishida) va
to'liq transkript. Avval `build_document` bitta neytral `Document` yasaydi, keyin
uni to'rt format chizadi (MD/TXT - shu yerda, DOCX/PDF - `export_render.py`): to'rt
fayl MAZMUNI bir xil bo'lsin, biri ikkinchisidan "orqada qolmasin".

"QISQA XULOSA" (2026-10-10, `brief` qismi): foydalanuvchi sevgan ixcham ko'rinish - sarlavha,
sana/davomiylik/ishtirokchilar qatori, Maqsad, Qisqacha (1-2 gap), Asosiy fikrlar, Qarorlar,
Vazifalar (mas'ul va muddat bilan), Ochiq savollar. Har eksport shu blok bilan BOSHLANADI;
`parts=brief` yolg'iz so'ralsa fayl aynan shu blokning o'zi (ulashish uchun). Blok - XULOSA
tilida (mobil ilovadagi "Ulashish" bilan so'zma-so'z bir xil); hujjat sarlavhalari - ilova tilida.
"""

from __future__ import annotations

import math
import re
import unicodedata

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote

from . import dates
from .prompts import clock, hms
from .templates import SECTION_TITLES
from .templates import get as get_template
from .templates import layout as template_layout

_TOKEN = re.compile(r"\[(S\d{1,2})\]")

_FALLBACK = {"uz": "{n}-ishtirokchi", "ru": "Участник {n}", "en": "Speaker {n}"}
#: Ovozi tanilgan, ismi yo'q spiker (`voice.UNKNOWN` bilan bir xil).
_UNKNOWN = {"uz": "Noma'lum #{n}", "ru": "Неизвестный #{n}", "en": "Unknown #{n}"}
_CHECK = {"uz": "tekshiring", "ru": "проверьте", "en": "check"}
_DUE = {"uz": "muddat", "ru": "срок", "en": "due"}
#: `followUps[].reasons` - nima uchun kuzatish kerak (kod chizadi, model emas).
_REASONS = {
    "uz": {"no_answer": "javob berilmagan", "no_owner": "mas'ul belgilanmagan", "deferred": "keyinga qoldirilgan",
           "tentative": "taxminiy qaror", "conditional": "shartga bog'liq", "no_due": "muddat belgilanmagan",
           "no_mitigation": "yechim aytilmagan"},
    "ru": {"no_answer": "нет ответа", "no_owner": "нет ответственного", "deferred": "отложено",
           "tentative": "предварительное решение", "conditional": "зависит от условия", "no_due": "нет срока",
           "no_mitigation": "решение не названо"},
    "en": {"no_answer": "no answer", "no_owner": "no owner", "deferred": "deferred", "tentative": "tentative decision",
           "conditional": "conditional", "no_due": "no due date", "no_mitigation": "no mitigation stated"},
}
_CONDITION = {"uz": "shart", "ru": "условие", "en": "if"}

_STATUS = {
    "uz": {"final": "yakuniy", "tentative": "taxminiy", "conditional": "shartli", "reversed": "bekor qilingan"},
    "ru": {"final": "окончательно", "tentative": "предварительно", "conditional": "условно",
           "reversed": "отменено"},
    "en": {"final": "final", "tentative": "tentative", "conditional": "conditional", "reversed": "reversed"},
}


def resolve_speaker(sid: str | None, speakers: dict[str, dict[str, Any]]) -> str | None:
    seen = 0
    while sid and sid in speakers and speakers[sid].get("merged_into") and seen < 8:
        sid = speakers[sid]["merged_into"]
        seen += 1
    return sid


def speaker_name(sid: str | None, speakers: dict[str, dict[str, Any]], lang: str) -> str:
    sid = resolve_speaker(sid, speakers)
    if not sid:
        return "?"
    # NEGA `one_line`: `rename_speaker` faqat bo'shliqlarni yig'adi - eski yozuvlarda boshqaruv
    # belgili ism (`Aziz\x01`) qolgan bo'lishi mumkin, u DOCX XML ni buzib 500 berardi.
    sp = speakers.get(sid) or {}
    name = one_line(sp.get("name"))
    if name:
        return name
    # Ismsiz, lekin ovozi tanilgan (mehmon yoki namuna yozmagan xodim) - doimiy raqami (`voice.py`).
    person = sp.get("person_id") or sp.get("personId")
    if person:
        return _UNKNOWN.get(lang, _UNKNOWN["uz"]).format(n=person)
    number = re.sub(r"\D", "", sid) or "?"
    return _FALLBACK.get(lang, _FALLBACK["uz"]).format(n=number)


def render_tokens(text: Any, speakers: dict[str, dict[str, Any]], lang: str) -> str:
    return _TOKEN.sub(lambda m: speaker_name(m.group(1), speakers, lang), str(text or ""))


#: O'zbekcha tutuq belgilari (`o'`, `oʻ`, `g'`, `gʻ`): slug'da so'zni BO'LMASIN - aks holda bir xil
#: sarlavha `bo-yicha` va `boyicha` bo'lib ikki xil nom olardi.
_APOSTROPHES = re.compile(r"['`´ʹʻʼʽ‘’]")
#: Kirill -> lotin (faqat ASCII fayl nomi uchun; haqiqiy nom `filename*` da o'zgarmaydi):
#: aks holda ruscha sarlavhali hamma fayl `meeting-<sana>` bo'lib, bir-biridan ajralmasdi.
_CYRILLIC = dict(zip("абвгдезийклмнопрстуфыэіқғҳґ", "abvgdeziyklmnoprstufyeiqghg"))
_CYRILLIC.update({"ё": "yo", "ж": "zh", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ь": "",
                  "ю": "yu", "я": "ya", "є": "ye", "ї": "yi", "ў": "o"})


def slug(title: str) -> str:
    value = _APOSTROPHES.sub("", (title or "").lower())
    value = "".join(_CYRILLIC.get(ch, ch) for ch in value)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:60].strip("-") or "meeting"


def _ts(start: Any) -> str:
    return f" ({clock(start)})" if isinstance(start, (int, float)) else ""


def summary_document(content: dict[str, Any], layout: list[dict[str, str]], speakers: dict[str, dict[str, Any]],
                     lang: str, recorded_at: float, *, markdown: bool) -> str:
    """Xulosa matni. `markdown=False` - oddiy matn (TXT)."""
    def t(value: Any) -> str:
        return render_tokens(value, speakers, lang)

    def who(sid: Any) -> str:
        return speaker_name(sid, speakers, lang) if sid else ""

    h1 = "# " if markdown else ""
    h2 = "## " if markdown else ""
    out: list[str] = [f"{h1}{t(content.get('title') or '')}".rstrip(),
                      f"{dates.format_day_time(recorded_at, lang)} · {hms((content.get('meeting') or {}).get('durationSec') or 0)}",
                      ""]
    sections = {g["key"]: g["items"] for g in content.get("templateSections") or []}
    for entry in layout:
        key, title = entry["key"], entry["title"]
        lines: list[str] = []
        if key == "overview":
            if content.get("overview"):
                lines.append(t(content["overview"]))
            if content.get("purpose"):
                lines.append(t(content["purpose"]))
        elif key == "actionItems":
            for a in content.get("actionItems") or []:
                owner = a.get("owner") or {}
                person = who(owner.get("speaker")) or owner.get("name") or ""
                due = a.get("due") or {}
                when = dates.format_date(due.get("date"), lang) if due.get("date") else (due.get("raw") or "")
                if due.get("time"):
                    when = f"{when} {due['time']}".strip()
                box = ("[x] " if a.get("status") == "done_in_meeting" else "[ ] ") if markdown else ""
                cond = f"{_CONDITION.get(lang, 'shart')}: {t(a['condition'])}" if a.get("condition") else ""
                extra = " — ".join(x for x in (person, f"{_DUE.get(lang, 'muddat')}: {when}" if when else "", cond)
                                   if x)
                flag = f" ⚠ {_CHECK.get(lang, 'tekshiring')}" if a.get("needsConfirmation") else ""
                lines.append(f"- {box}{t(a['task'])}{' — ' + extra if extra else ''}{flag}{_ts(a.get('start'))}")
        elif key == "decisions":
            for d in content.get("decisions") or []:
                status = _STATUS.get(lang, _STATUS["uz"]).get(d.get("status") or "final", "")
                cond = f" ({t(d['condition'])})" if d.get("condition") else ""
                flag = f" ⚠ {_CHECK.get(lang, 'tekshiring')}" if d.get("needsConfirmation") else ""
                lines.append(f"- {t(d['text'])}{cond} [{status}]{flag}{_ts(d.get('start'))}")
        elif key == "followUps":
            labels = _REASONS.get(lang, _REASONS["uz"])
            for f in content.get("followUps") or []:
                why = ", ".join(labels.get(r, r) for r in f.get("reasons") or [])
                lines.append(f"- {t(f['text'])}{' — ' + why if why else ''}{_ts(f.get('start'))}")
        elif key == "topics":
            for topic in content.get("topics") or []:
                lines.append(f"{'### ' if markdown else ''}{t(topic['title'])}{_ts(topic.get('start'))}")
                if topic.get("summary"):
                    lines.append(t(topic["summary"]))
                for kp in topic.get("keyPoints") or []:
                    lines.append(f"- {t(kp['text'])}")
                lines.append("")
        elif key in ("keyPoints", "openQuestions", "nextSteps"):
            for item in content.get(key) or []:
                lines.append(f"- {t(item['text'])}{_ts(item.get('start'))}")
        elif key == "risks":
            for r in content.get("risks") or []:
                mitigation = f" → {t(r['mitigation'])}" if r.get("mitigation") else ""
                lines.append(f"- {t(r['text'])}{mitigation}{_ts(r.get('start'))}")
        elif key == "numbers":
            for n in content.get("numbers") or []:
                unit = f" {n['unit']}" if n.get("unit") else ""
                lines.append(f"- {n['value']}{unit} — {t(n.get('what') or '')}")
        elif key == "dates":
            for d in content.get("dates") or []:
                when = dates.format_date(d.get("date"), lang) if d.get("date") else d.get("raw")
                if d.get("time"):
                    when = f"{when} {d['time']}"
                lines.append(f"- {when} — {t(d.get('what') or '')}")
        elif key == "nextMeeting":
            nm = content.get("nextMeeting")
            if nm:
                when = dates.format_date(nm.get("date"), lang) if nm.get("date") else (nm.get("raw") or "")
                if nm.get("time"):
                    when = f"{when} {nm['time']}"
                lines.append(when.strip())
                lines += [f"- {t(a)}" for a in nm.get("agenda") or [] if a]
        elif key == "highlights":
            for h in content.get("highlights") or []:
                prefix = "> " if markdown else ""
                lines.append(f"{prefix}«{h['quote']}» — {who(h.get('speaker')) or '?'}{_ts(h.get('start'))}")
        elif key == "participants":
            for p in content.get("participants") or []:
                share = round(float(p.get("talkShare") or 0) * 100)
                note = f": {t(p['contribution'])}" if p.get("contribution") else ""
                lines.append(f"- {who(p['speaker'])} — {share}%{note}")
        elif key == "keywords":
            if content.get("keywords"):
                lines.append(", ".join(content["keywords"]))
        elif key == "sentiment":
            s = content.get("sentiment")
            if s:
                lines.append(f"{s.get('overall')}{': ' + t(s['note']) if s.get('note') else ''}")
        elif key == "followUpMessage":
            fu = content.get("followUpMessage")
            if fu:
                if fu.get("subject"):
                    lines.append(t(fu["subject"]))
                lines.append(t(fu.get("body") or ""))
        else:
            for item in sections.get(key) or []:
                person = f"{who(item.get('speaker'))}: " if item.get("speaker") else ""
                lines.append(f"- {person}{t(item['text'])}")
        if lines and any(line.strip() for line in lines):
            out.append(f"{h2}{title}")
            out.extend(lines)
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def transcript_txt(segments: list[dict[str, Any]], speakers: dict[str, dict[str, Any]], lang: str, *,
                   with_speakers: bool = True, with_timestamps: bool = True) -> str:
    lines = []
    for seg in segments:
        parts = []
        if with_timestamps:
            parts.append(f"[{hms(seg['start'])}]")
        if with_speakers and seg.get("speaker"):
            parts.append(f"{speaker_name(seg['speaker'], speakers, lang)}:")
        parts.append(seg["text"])
        lines.append(" ".join(parts))
    return "\n".join(lines) + ("\n" if lines else "")


def _srt_time(seconds: float) -> str:
    total_ms = int(round(max(0.0, float(seconds)) * 1000))
    h, rest = divmod(total_ms, 3600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def transcript_srt(segments: list[dict[str, Any]], speakers: dict[str, dict[str, Any]], lang: str, *,
                   with_speakers: bool = True) -> str:
    cues = []
    for number, seg in enumerate(segments, start=1):
        end = max(float(seg["end"]), float(seg["start"]) + 0.5)
        text = seg["text"]
        if with_speakers and seg.get("speaker"):
            text = f"{speaker_name(seg['speaker'], speakers, lang)}: {text}"
        cues.append(f"{number}\n{_srt_time(seg['start'])} --> {_srt_time(end)}\n{text}\n")
    return "\n".join(cues)


# --- to'liq hujjat: DOCX / PDF / MD / TXT (2026-10-10) ----------------------------------------
#
# Mazmun TILI o'zgarmaydi (xulosa qaysi tilda yozilgan bo'lsa - o'shanda), lekin kod
# chizadigan hamma narsa - bo'lim sarlavhalari, jadval ustunlari, sanalar, "1-ishtirokchi" -
# ilova tilida (`Accept-Language`): odam o'z tilidagi ilovadan bosgan faylda sarlavhalar
# ham o'z tilida bo'lsin.

#: Hujjat qismlari - `?parts=` qiymatlari, hujjatdagi tartibda. `brief` ("Qisqa xulosa") - BIRINCHI:
#: faylni ochgan rahbar avval ixcham xulosani ko'rsin, tafsilotlar keyin.
PARTS = ("brief", "summary", "actions", "mindmap", "transcript")
#: Tayyor xulosa kerak bo'lgan qismlar (transkript xulosasiz ham eksport qilinadi).
SUMMARY_PARTS = ("brief", "summary", "actions", "mindmap")

#: Format -> (Content-Type, kengaytma).
FORMATS: dict[str, tuple[str, str]] = {
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    "pdf": ("application/pdf", "pdf"),
    "md": ("text/markdown; charset=utf-8", "md"),
    "txt": ("text/plain; charset=utf-8", "txt"),
}

#: Pastki yozuvdagi mahsulot nomi (texnik id lar `venera` bo'lib qoladi).
BRAND = "Barno AI"

#: Jadval katagi va aqliy xarita tuguni - shundan uzun matn qisqartiriladi: PDF da bitta
#: qator sahifadan baland bo'lsa reportlab chiza olmaydi, xaritada esa uzun gap "shoxni" yo'qotadi.
CELL_CHARS = 600
NODE_CHARS = 160
#: Hujjat sarlavhasi. NEGA chegara shu yerda: DOCX `core_properties.title` 255 belgidan oshsa
#: python-docx ValueError beradi va xato matni (yig'ilish nomi) logga tushardi. Yig'ilish nomi
#: API da 120 bilan cheklangan, lekin `build_document` boshqa joydan ham chaqirilishi mumkin.
TITLE_CHARS = 200
#: Transkript: bitta spikerning ketma-ket bo'laklari (oralig'i shundan kam) - BITTA paragraf.
#: ASR gapni mayda bo'laklarga bo'ladi; har biri alohida qator bo'lsa hujjat "uzuq-yuluq"
#: o'qiladi (Plaud ham qo'shadi). Paragraf juda cho'zilib ketmasin - belgilar chegarasi.
MERGE_GAP_SEC = 3.0
MERGE_CHARS = 1200


def _t(uz: str, ru: str, en: str) -> dict[str, str]:
    return {"uz": uz, "ru": ru, "en": en}


_LABELS: dict[str, dict[str, str]] = {
    "date": _t("Sana", "Дата", "Date"),
    "duration": _t("Davomiyligi", "Длительность", "Duration"),
    "participants": _t("Ishtirokchilar", "Участники", "Participants"),
    "type": _t("Xulosa turi", "Шаблон", "Summary type"),
    "mindmap": _t("Aqliy xarita", "Интеллект-карта", "Mind map"),
    "transcript": _t("Transkript", "Расшифровка", "Transcript"),
    "no": _t("№", "№", "#"),
    "task": _t("Vazifa", "Задача", "Task"),
    "owner": _t("Mas'ul", "Ответственный", "Owner"),
    "due": _t("Muddat", "Срок", "Due"),
    "status": _t("Holat", "Статус", "Status"),
    "crm": _t("CRM", "CRM", "CRM"),
    "open": _t("ochiq", "открыта", "open"),
    "done": _t("bajarildi", "выполнена", "done"),
    "crm_created": _t("yaratildi", "создана", "created"),
    # NEGA buyruq emas ("tekshiring"): vazifa matniga yopishib "sahifani yangilash (tekshiring)"
    # vazifaning bir qismidek o'qilardi. Bu - Barno ishonchi komil emasligi haqidagi OGOHLANTIRISH.
    "check": _t("⚠ aniqlashtirish kerak", "⚠ требует уточнения", "⚠ needs confirmation"),
    "talk_share": _t("nutq ulushi", "доля речи", "talk share"),
    "agenda": _t("Kun tartibi", "Повестка", "Agenda"),
    "generated": _t("Yaratildi", "Создано", "Generated"),
    # Fayl boshqa shaharda ham ochiladi - vaqt qaysi mintaqada ekani ko'rinsin.
    "tz": _t("Toshkent vaqti", "время Ташкента", "Tashkent time"),
    "stale": _t("Transkript bu xulosadan keyin o'zgartirilgan - xulosa eski matn bo'yicha.",
                "Расшифровка изменена после этого резюме - резюме по старому тексту.",
                "The transcript was edited after this summary was written."),
    "no_speakers": _t("Spikerlar ajratilmagan", "Спикеры не разделены", "Speakers not separated"),
    "brief": _t("Qisqa xulosa", "Краткий итог", "Short summary"),
}

#: Faqat eksportdagi bo'lim nomlari (`SECTION_TITLES` ilova bilan umumiy - unga tegmaymiz).
#: NEGA: hujjatda "Asosiy fikrlar" va "Muhim lahzalar" yonma-yon sinonimdek o'qiladi (ikkinchisi
#: aslida iqtiboslar), "Ishtirokchilar" esa sarlavha qatorida ham bor.
_EXPORT_TITLES: dict[str, dict[str, str]] = {
    "highlights": _t("Iqtiboslar", "Цитаты", "Quotes"),
    "participants": _t("Ishtirokchilar faolligi", "Активность участников", "Participation"),
}

#: "Qisqa xulosa" yorliqlari: (birlik, ko'plik) - bitta vazifa "Vazifa:", bir nechtasi "Vazifalar:".
#: Matnlar mobil ilovadagi `recs.brief.*` bilan BIR XIL: ilovadan "Ulashish" va eksport fayli
#: so'zma-so'z bir xil blok bersin (umumiy namuna: `packages/fixtures/meeting-brief.json`, uni
#: pytest ham, jest ham tekshiradi).
_BRIEF_LABELS: dict[str, dict[str, tuple[str, str]]] = {
    "uz": {"purpose": ("Maqsad", "Maqsad"), "overview": ("Qisqacha", "Qisqacha"),
           "keyPoints": ("Asosiy fikr", "Asosiy fikrlar"), "decisions": ("Qaror", "Qarorlar"),
           "actions": ("Vazifa", "Vazifalar"), "questions": ("Ochiq savol", "Ochiq savollar")},
    "ru": {"purpose": ("Цель", "Цель"), "overview": ("Кратко", "Кратко"),
           "keyPoints": ("Ключевой момент", "Ключевые моменты"), "decisions": ("Решение", "Решения"),
           "actions": ("Задача", "Задачи"), "questions": ("Открытый вопрос", "Открытые вопросы")},
    "en": {"purpose": ("Purpose", "Purpose"), "overview": ("In short", "In short"),
           "keyPoints": ("Key point", "Key points"), "decisions": ("Decision", "Decisions"),
           "actions": ("Action item", "Action items"), "questions": ("Open question", "Open questions")},
}
#: Vazifa qatori: "Skriptni yuborish. Mas'ul: 2-ishtirokchi. Muddat belgilanmagan."
_BRIEF_OWNER = {"uz": ("Mas'ul: {x}.", "Mas'ul belgilanmagan."),
                "ru": ("Ответственный: {x}.", "Ответственный не назначен."),
                "en": ("Owner: {x}.", "No owner set.")}
_BRIEF_DUE = {"uz": ("Muddat: {x}.", "Muddat belgilanmagan."),
              "ru": ("Срок: {x}.", "Срок не указан."),
              "en": ("Due: {x}.", "No due date.")}
#: Egasi "biz" (`kind: team`) - ism yo'q, lekin "belgilanmagan" ham emas.
_BRIEF_TEAM = {"uz": "Jamoa", "ru": "Команда", "en": "Team"}
#: Tasdiqlanmagan band belgisi. NEGA buyruq ("tekshiring") emas, holat: blok rahbarga yuboriladi -
#: "tekshiring" unga berilgan ko'rsatmadek o'qilardi (jadvaldagi `_LABELS["check"]` bilan bir xil so'z).
_BRIEF_CHECK = {"uz": "aniqlashtirish kerak", "ru": "требует уточнения", "en": "needs confirmation"}
#: Qisqa davomiylik ("1 daq 53 s"): bir qatorli sarlavha ostida "1 daqiqa 53 soniya" cho'zilib ketadi.
_BRIEF_DURATION = {"uz": ("soat", "daq", "s"), "ru": ("ч", "мин", "с"), "en": ("h", "min", "s")}
#: "Qisqacha" - BITTA gap (ega qarori 2026-10-15, "30 soniyada" kartasi: maqsad va natija bir jumla).
BRIEF_SENTENCES = 1
#: "Asosiy fikrlar" kartada - yig'ilish uzunligiga qarab (ega qarori 2026-10-15): 15 daqiqagacha 3 ta,
#: 45 daqiqagacha 4 ta, undan uzunida 5 ta. Qolgani "Batafsil" da. Mobil `briefPointCount` bilan bir xil.
BRIEF_POINTS_BY_MINUTES = ((15, 3), (45, 4))
BRIEF_POINTS_LONG = 5


def brief_points(duration_sec: Any) -> int:
    """Kartadagi asosiy fikrlar soni. Davomiylik noma'lum - eng qisqasi (3)."""
    try:
        minutes = float(duration_sec or 0) / 60
    except (TypeError, ValueError):
        minutes = 0.0
    if minutes <= 0:
        return BRIEF_POINTS_BY_MINUTES[0][1]
    for limit, count in BRIEF_POINTS_BY_MINUTES:
        if minutes <= limit:
            return count
    return BRIEF_POINTS_LONG


#: Qisqa yig'ilishda (shundan qisqa, daqiqa) "Mavzular" oxirga: 8 daqiqalik suhbatning boblari kerak emas.
SHORT_MEETING_MIN = 15
#: "Batafsil" o'rniga bitta xira qator bo'ladigan bo'limlar (alohida karta/bo'lim emas).
META_SECTIONS = ("participants", "keywords", "sentiment")

_OUTCOME = {
    "uz": {"decided": "qaror qabul qilindi", "open": "ochiq", "info": "ma'lumot"},
    "ru": {"decided": "решено", "open": "открыто", "info": "информация"},
    "en": {"decided": "decided", "open": "open", "info": "info"},
}
_SEVERITY = {
    "uz": {"high": "yuqori", "medium": "o'rta", "low": "past"},
    "ru": {"high": "высокий", "medium": "средний", "low": "низкий"},
    "en": {"high": "high", "medium": "medium", "low": "low"},
}
_SENTIMENT = {
    "uz": {"positive": "ijobiy", "neutral": "neytral", "mixed": "aralash", "negative": "salbiy", "tense": "keskin"},
    "ru": {"positive": "позитивное", "neutral": "нейтральное", "mixed": "смешанное", "negative": "негативное",
           "tense": "напряжённое"},
    "en": {"positive": "positive", "neutral": "neutral", "mixed": "mixed", "negative": "negative", "tense": "tense"},
}
_DURATION = {"uz": ("soat", "daqiqa", "soniya"), "ru": ("ч", "мин", "с"), "en": ("h", "min", "s")}

#: Mazmun tili -> Word/PDF til kodi. NEGA: python-docx shabloni `en-US` - Word o'zbekcha matnning
#: deyarli HAR so'zini qizil chiziq bilan belgilardi. `uz-Latn-UZ` uchun lug'at odatda o'rnatilmagan
#: - Word u holda tekshirmaydi; ruscha matn esa ruscha lug'at bilan to'g'ri tekshiriladi.
WORD_LANGS = {"uz": "uz-Latn-UZ", "ru": "ru-RU", "en": "en-US"}


def label(key: str, lang: str) -> str:
    return _LABELS[key].get(lang) or _LABELS[key]["uz"]


def section_title(key: str, lang: str) -> str:
    titles = _EXPORT_TITLES.get(key) or SECTION_TITLES.get(key) or {}
    return titles.get(lang) or titles.get("uz") or key


class RenderUnavailable(Exception):
    """DOCX/PDF chizib bo'lmaydi (kutubxona yoki shrift yo'q, yoki PDF navbati to'la) - endpoint
    503 qaytaradi. `code` - mobil ilova ko'radigan kod (`pdf_unavailable` | `docx_unavailable` |
    `export_busy`)."""

    def __init__(self, code: str, reason: str = "") -> None:
        super().__init__(f"{code}: {reason}" if reason else code)
        self.code = code
        self.reason = reason


@dataclass
class Document:
    """Formatdan mustaqil hujjat. `blocks` - ketma-ket bloklar (`kind` bo'yicha):

    * `h2` {text} - bo'lim sarlavhasi; `h3` {text, sub} - mavzu (sub - vaqt/natija);
    * `p` {text} - paragraf (qator ichida `\\n` bo'lishi mumkin); `muted` {text} - izoh;
    * `ul` {items: [(daraja 0..2, matn)]}; `quote` {text, who};
    * `table` {head, rows, widths, muted} - `widths` nisbiy kengliklar, katakda `\\n` - yangi
      qator, `muted` - kulrang chiziladigan qatorlar (bajarilgan vazifalar, 0 dan);
    * `tree` {root: {text, children}} - aqliy xarita;
    * `transcript` {lines: [(vaqt, kim, matn)]}.

    * `brief` {title, meta, items: [{label, text} | {label, list}]} - "Qisqa xulosa": `title`/`meta`
      faqat hujjat sarlavhasiz bo'lsa (`head=False`), aks holda ular hujjat boshida bor.

    `lang` - ilova tili (sarlavhalar), `text_lang` - mazmun tili (imlo tekshiruvi, PDF `/Lang`).
    `head=False` - faqat "Qisqa xulosa" (`parts=brief`): hujjat sarlavhasi, meta qatorlari va
    MD/TXT pastki yozuvi chizilmaydi - fayl/matn aynan xulosa ko'rinishida ulashiladi.
    """

    lang: str
    title: str
    meta: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    blocks: list[dict[str, Any]] = field(default_factory=list)
    footer: str = ""
    text_lang: str = ""
    head: bool = True


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f￾￿]")
_SPACES = re.compile(r"\s+")


def xml_safe(value: Any) -> str:
    """XML ga (DOCX) yozib bo'ladigan matn: boshqaruv belgilari va juft bo'lmagan surrogatlar
    olib tashlanadi, bo'shliqlarga TEGILMAYDI (`"Ism: "` oxiridagi bo'shliq kerak). DOCX
    chizuvchisi HAR matnni shundan o'tkazadi - yig'uvchi biror joyda `clean` ni unutsa ham
    fayl 500 bilan yiqilmasin."""
    text = "" if value is None else str(value)
    return _CONTROL.sub("", text.encode("utf-8", "replace").decode("utf-8"))


def clean(value: Any) -> str:
    """Faylga yoziladigan matn: boshqaruv belgilari (DOCX XML ni buzadi, PDF da "quti")
    va juft bo'lmagan surrogatlar (UTF-8 ga yozilmaydi) olib tashlanadi."""
    return xml_safe(value).replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ").strip()


def one_line(value: Any, limit: int = 0) -> str:
    text = _SPACES.sub(" ", clean(value)).strip()
    if limit and len(text) > limit:
        text = text[:limit - 1].rstrip() + "…"
    return text


def flat(cell: Any) -> str:
    """Ko'p qatorli jadval katagi -> bir qator (MD/TXT): `ochiq\\n⚠ ...` -> `ochiq · ⚠ ...`."""
    return " · ".join(x for x in (one_line(part) for part in str(cell or "").split("\n")) if x)


def parse_parts(raw: str | None) -> list[str] | None:
    """`?parts=summary,transcript` -> hujjat tartibidagi ro'yxat; bo'sh - `None` (default:
    hammasi, nima tayyor bo'lsa). Noma'lum qism - `ValueError` (400)."""
    names = [p.strip().lower() for p in (raw or "").split(",") if p.strip()]
    if not names:
        return None
    unknown = [p for p in names if p not in PARTS]
    if unknown:
        raise ValueError(", ".join(unknown[:5]))
    return [p for p in PARTS if p in names]


def format_moment(epoch: float, lang: str) -> str:
    """Yil bilan: `2026-yil 10-oktabr, 16:00` / `10 октября 2026, 16:00` / `October 10, 2026, 16:00`
    (fayl yillar o'tib ham ochiladi - ilovadagi yilsiz sana yetmaydi)."""
    moment = dates.tashkent(epoch)
    hhmm = moment.strftime("%H:%M")
    month = dates.MONTHS.get(lang, dates.MONTHS["uz"])[moment.month - 1]
    if lang == "ru":
        return f"{moment.day} {month} {moment.year}, {hhmm}"
    if lang == "en":
        return f"{month} {moment.day}, {moment.year}, {hhmm}"
    return f"{moment.year}-yil {moment.day}-{month}, {hhmm}"


#: Shundan qisqa yozuvda davomiylik soniyasi bilan: 113 s "1 daqiqa" emas, "1 daqiqa 53 soniya" -
#: aks holda hujjat boshidagi qator "Qisqa xulosa"dagi "1 daq 53 s" bilan zid ko'rinardi.
SHORT_DURATION_SEC = 600


def format_duration(seconds: Any, lang: str) -> str:
    h_word, m_word, s_word = _DURATION.get(lang, _DURATION["uz"])
    total = max(0, int(math.floor(float(seconds or 0) + 0.5)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} {h_word} {minutes} {m_word}" if minutes else f"{hours} {h_word}"
    if minutes:
        return f"{minutes} {m_word} {secs} {s_word}" if secs and total < SHORT_DURATION_SEC else f"{minutes} {m_word}"
    return f"{secs} {s_word}"


def _when(day: Any, hhmm: Any, raw: Any, lang: str) -> str:
    text = dates.format_date(day, lang) if day else (raw or "")
    if hhmm:
        # Vergul bilan: "17-oktabr, 10:00" - "17-oktabr 10:00" da sana va vaqt qo'shilib o'qiladi.
        text = f"{text}, {hhmm}" if str(text).strip() else str(hhmm)
    return one_line(text)


def _crm_key(row: dict[str, Any], lang: str) -> str:
    """CRM da YARATILGAN vazifaning kaliti (`DVSIB-231`); taklif kutilayotgan yoki rad
    etilgan bo'lsa - bo'sh (hujjatda "CRM da bor" degan yolg'on chiqmasin)."""
    if row.get("crm_status") != "executed":
        return ""
    result = row.get("crm_result")
    if isinstance(result, dict):
        for key in ("key", "id", "number"):
            if result.get(key) not in (None, ""):
                return one_line(result[key], 40)
    return label("crm_created", lang)


def actions_from_rows(rows: Sequence[dict[str, Any]], speakers: dict[str, dict[str, Any]],
                      lang: str) -> list[dict[str, Any]]:
    """Jonli vazifalar (`action_items`: odam tahrirlagani, qo'shgani, CRM kaliti) - jadval
    qatorlari. `crm_result` - JSON matn emas, allaqachon o'qilgan qiymat (`jload`)."""
    out = []
    for row in rows:
        if row.get("status") == "dismissed":
            continue
        owner = row.get("owner_name") or (speaker_name(row["owner_speaker"], speakers, lang)
                                          if row.get("owner_speaker") else "")
        # NEGA `render_tokens`: vazifa xulosadan ko'chirilganda matnida `[S2]` qolishi mumkin - jadvalda
        # va "Qisqa xulosa"da u ism bo'lib chiqsin (mobil ilova ham shunday chizadi).
        out.append({"task": one_line(render_tokens(row.get("task"), speakers, lang)), "owner": one_line(owner),
                    "due": _when(row.get("due_date"), row.get("due_time"), row.get("due_raw"), lang),
                    "done": row.get("status") == "done", "check": bool(row.get("needs_confirmation")),
                    "crm": _crm_key(row, lang), "team": row.get("owner_kind") == "team"})
    return out


def actions_from_content(content: dict[str, Any], speakers: dict[str, dict[str, Any]],
                         lang: str) -> list[dict[str, Any]]:
    """Asosiy bo'lmagan xulosa: vazifalar xulosaning o'zidan (CRM kaliti yo'q)."""
    out = []
    for item in content.get("actionItems") or []:
        owner = item.get("owner") or {}
        person = (speaker_name(owner["speaker"], speakers, lang) if owner.get("speaker") else "") \
            or owner.get("name") or ""
        due = item.get("due") or {}
        task = render_tokens(item.get("task"), speakers, lang)
        if item.get("condition"):
            task = f"{task} ({_CONDITION.get(lang, 'shart')}: {render_tokens(item['condition'], speakers, lang)})"
        out.append({"task": one_line(task), "owner": one_line(person),
                    "due": _when(due.get("date"), due.get("time"), due.get("raw"), lang),
                    "done": item.get("status") == "done_in_meeting",
                    # Tekshiruvchi tasdiqlamagan (`verified: false`) vazifa ham ishonchsiz - mobil ilova kabi.
                    "check": bool(item.get("needsConfirmation")) or item.get("verified") is False,
                    "crm": "", "team": owner.get("kind") == "team"})
    return out


def _actions_table(actions: list[dict[str, Any]], lang: str) -> dict[str, Any]:
    rows, muted = [], []
    for number, a in enumerate(actions, start=1):
        # Ogohlantirish vazifa matnida EMAS, holat ustunida (alohida qatorda).
        status = f"✓ {label('done', lang)}" if a.get("done") else label("open", lang)
        if a.get("check"):
            status += "\n" + label("check", lang)
        if a.get("done"):
            muted.append(number - 1)
        rows.append([str(number), one_line(a["task"], CELL_CHARS), one_line(a["owner"], 120), one_line(a["due"], 80),
                     status, a.get("crm") or ""])
    head = [label(k, lang) for k in ("no", "task", "owner", "due", "status", "crm")]
    # Kengliklar DejaVu 8.8 pt da o'lchangan (uz/ru/en): "Ответственный", "16 октября, 18:00",
    # "✓ выполнена", "aniqlashtirish" va `DVSIB-231` so'z o'rtasidan bo'linmasin; qolgani - vazifaga.
    return {"kind": "table", "head": head, "rows": rows, "widths": [5, 31, 18, 19, 15, 12], "muted": muted}


def _participants(content: dict[str, Any], speakers: dict[str, dict[str, Any]], lang: str) -> list[str]:
    """Xulosadagi ishtirokchilar - birlashtirilgan spikerlar BITTA qator (ulushlar qo'shiladi)."""
    merged: dict[str, dict[str, Any]] = {}
    for p in content.get("participants") or []:
        sid = resolve_speaker(p.get("speaker"), speakers) or p.get("speaker") or "?"
        slot = merged.setdefault(sid, {"share": 0.0, "note": ""})
        slot["share"] += float(p.get("talkShare") or 0)
        if p.get("contribution") and not slot["note"]:
            slot["note"] = render_tokens(p["contribution"], speakers, lang)
    out = []
    share_word = label("talk_share", lang)
    for sid, slot in merged.items():
        note = f": {slot['note']}" if slot["note"] else ""
        out.append(one_line(f"{speaker_name(sid, speakers, lang)} — {share_word} {round(slot['share'] * 100)}%{note}"))
    return out


def _norm(value: Any) -> str:
    return one_line(value).casefold()


def _without_repeated_questions(content: dict[str, Any]) -> dict[str, Any]:
    """"Hal qilinmagan masalalar" (`followUps`) har ochiq savolni SABABI bilan allaqachon
    beradi: "Ochiq savollar" bo'limida o'sha matn yana chiqsa hujjat "to'ldirilgan"dek o'qiladi.
    Faqat hujjat bo'limlari uchun (aqliy xarita to'liq mazmundan chiziladi); ilovaga tegmaydi."""
    follow_ups = content.get("followUps") or []
    questions = content.get("openQuestions") or []
    if not follow_ups or not questions:
        return content
    refs = {f.get("ref") for f in follow_ups if f.get("ref") and f.get("kind") in (None, "openQuestion")}
    texts = {_norm(f.get("text")) for f in follow_ups}
    kept = [q for q in questions if q.get("id") not in refs and _norm(q.get("text")) not in texts]
    return {**content, "openQuestions": kept}


def _section(key: str, content: dict[str, Any], speakers: dict[str, dict[str, Any]], lang: str,
             actions: list[dict[str, Any]] | None, stamp: Any = clock) -> list[dict[str, Any]]:
    """Bitta xulosa bo'limining bloklari (sarlavhasiz). Bo'sh bo'lim - bo'sh ro'yxat.
    `stamp` - vaqt formati (transkript bilan BIR XIL: `build_document` tanlaydi)."""
    def t(value: Any) -> str:
        return one_line(render_tokens(value, speakers, lang))

    def who(sid: Any) -> str:
        return one_line(speaker_name(sid, speakers, lang)) if sid else ""

    def ts(start: Any) -> str:
        return f" ({stamp(start)})" if isinstance(start, (int, float)) else ""

    def bullets(lines: list[str]) -> list[dict[str, Any]]:
        items = [(0, line) for line in lines if line]
        return [{"kind": "ul", "items": items}] if items else []

    check = label("check", lang)
    if key == "overview":
        out = []
        if content.get("overview"):
            out.append({"kind": "p", "text": clean(render_tokens(content["overview"], speakers, lang))})
        if content.get("purpose"):
            title = SECTION_TITLES["purpose"].get(lang, "Maqsad")
            out.append({"kind": "p", "text": f"{title}: {t(content['purpose'])}"})
        return out
    if key == "actionItems":
        return [_actions_table(actions, lang)] if actions else []
    if key == "decisions":
        lines = []
        for d in content.get("decisions") or []:
            status = _STATUS.get(lang, _STATUS["uz"]).get(d.get("status") or "final", "")
            cond = f" ({t(d['condition'])})" if d.get("condition") else ""
            # Holat va ogohlantirish BITTA qavsda: "[taxminiy · ⚠ aniqlashtirish kerak]".
            tags = " · ".join(x for x in (status, check if d.get("needsConfirmation") else "") if x)
            lines.append(f"{t(d.get('text'))}{cond}{' [' + tags + ']' if tags else ''}{ts(d.get('start'))}")
        return bullets(lines)
    if key == "followUps":
        reasons = _REASONS.get(lang, _REASONS["uz"])
        lines = []
        for f in content.get("followUps") or []:
            why = ", ".join(reasons.get(r, r) for r in f.get("reasons") or [])
            lines.append(f"{t(f.get('text'))}{' — ' + why if why else ''}{ts(f.get('start'))}")
        return bullets(lines)
    if key == "topics":
        out = []
        outcomes = _OUTCOME.get(lang, _OUTCOME["uz"])
        for topic in content.get("topics") or []:
            span = ""
            if isinstance(topic.get("start"), (int, float)):
                span = stamp(topic["start"])
                if isinstance(topic.get("end"), (int, float)) and topic["end"] > topic["start"]:
                    span += f"–{stamp(topic['end'])}"
            sub = " · ".join(x for x in (span, outcomes.get(topic.get("outcome") or "", "")) if x)
            out.append({"kind": "h3", "text": t(topic.get("title")), "sub": sub})
            if topic.get("summary"):
                out.append({"kind": "p", "text": clean(render_tokens(topic["summary"], speakers, lang))})
            out += bullets([t(kp.get("text")) for kp in topic.get("keyPoints") or []])
        return out
    if key in ("keyPoints", "openQuestions", "nextSteps"):
        return bullets([f"{t(item.get('text'))}{ts(item.get('start'))}" for item in content.get(key) or []])
    if key == "risks":
        lines = []
        levels = _SEVERITY.get(lang, _SEVERITY["uz"])
        for r in content.get("risks") or []:
            level = f" [{levels[r['severity']]}]" if r.get("severity") in levels else ""
            mitigation = f" → {t(r['mitigation'])}" if r.get("mitigation") else ""
            lines.append(f"{t(r.get('text'))}{level}{mitigation}{ts(r.get('start'))}")
        return bullets(lines)
    if key == "numbers":
        lines = []
        for n in content.get("numbers") or []:
            unit = f" {n['unit']}" if n.get("unit") else ""
            what = t(n.get("what"))
            value = n.get("value") if n.get("value") is not None else ""
            lines.append(one_line(f"{value}{unit}{' — ' + what if what else ''}"))
        return bullets(lines)
    if key == "dates":
        lines = []
        for d in content.get("dates") or []:
            what = t(d.get("what"))
            lines.append(one_line(f"{_when(d.get('date'), d.get('time'), d.get('raw'), lang)}"
                                  f"{' — ' + what if what else ''}"))
        return bullets(lines)
    if key == "nextMeeting":
        nm = content.get("nextMeeting")
        if not nm:
            return []
        out = []
        when = _when(nm.get("date"), nm.get("time"), nm.get("raw"), lang)
        if when:
            out.append({"kind": "p", "text": when})
        agenda = [t(a) for a in nm.get("agenda") or [] if a]
        if agenda:
            out.append({"kind": "p", "text": f"{label('agenda', lang)}:"})
            out += bullets(agenda)
        return out
    if key == "highlights":
        return [{"kind": "quote", "text": one_line(h.get("quote")),
                 "who": f"{who(h.get('speaker')) or '?'}{ts(h.get('start'))}"}
                for h in content.get("highlights") or [] if h.get("quote")]
    if key == "participants":
        return bullets(_participants(content, speakers, lang))
    if key == "keywords":
        words = [one_line(w) for w in content.get("keywords") or [] if w]
        return [{"kind": "p", "text": ", ".join(words)}] if words else []
    if key == "sentiment":
        s = content.get("sentiment")
        if not s:
            return []
        mood = _SENTIMENT.get(lang, _SENTIMENT["uz"]).get(s.get("overall") or "", s.get("overall") or "")
        note = f": {t(s['note'])}" if s.get("note") else ""
        return [{"kind": "p", "text": f"{one_line(mood)}{note}"}] if mood else []
    if key == "followUpMessage":
        fu = content.get("followUpMessage")
        if not fu:
            return []
        out = []
        if fu.get("subject"):
            out.append({"kind": "p", "text": t(fu["subject"])})
        if fu.get("body"):
            out.append({"kind": "p", "text": clean(render_tokens(fu["body"], speakers, lang))})
        return out
    sections = {g.get("key"): g.get("items") or [] for g in content.get("templateSections") or []}
    lines = []
    for item in sections.get(key) or []:
        person = f"{who(item.get('speaker'))}: " if item.get("speaker") else ""
        lines.append(f"{person}{t(item.get('text'))}")
    return bullets(lines)


def mindmap_tree(title: str, content: dict[str, Any], speakers: dict[str, dict[str, Any]], lang: str,
                 actions: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Aqliy xarita: ildiz - sarlavha, shoxlar - mavzular (asosiy fikrlari bilan), keyin
    qarorlar, vazifalar va ochiq savollar. Telefon xaritani xulosa mazmunidan O'ZI chizadi
    (qo'shimcha model chaqiruvi yo'q); hujjatda esa u ierarxiya ro'yxati.

    Holat tushib qolmaydi: faqat xaritani o'qigan odam taxminiy qarorni yakuniy, bajarilgan
    vazifani ochiq deb tushunmasin - qarorga holati, vazifaga mas'ul, muddat va "✓"."""
    def t(value: Any) -> str:
        return one_line(render_tokens(value, speakers, lang), NODE_CHARS)

    def node(text: str, children: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {"text": text, "children": children or []}

    branches = []
    outcomes = _OUTCOME.get(lang, _OUTCOME["uz"])
    for topic in content.get("topics") or []:
        leaves = [node(t(kp.get("text"))) for kp in topic.get("keyPoints") or [] if kp.get("text")]
        if not leaves and topic.get("summary"):
            leaves = [node(t(topic["summary"]))]
        outcome = outcomes.get(topic.get("outcome") or "", "")
        branches.append(node(f"{t(topic.get('title'))}{' (' + outcome + ')' if outcome else ''}", leaves))
    if not branches and content.get("keyPoints"):
        branches.append(node(section_title("keyPoints", lang),
                             [node(t(k.get("text"))) for k in content["keyPoints"] if k.get("text")]))
    statuses = _STATUS.get(lang, _STATUS["uz"])
    decisions = []
    for d in content.get("decisions") or []:
        if not d.get("text"):
            continue
        status = d.get("status") or "final"
        tag = f" ({statuses.get(status, status)})" if status != "final" else ""
        decisions.append(node(one_line(f"{t(d['text'])}{tag}", NODE_CHARS + 30)))
    if decisions:
        branches.append(node(section_title("decisions", lang), decisions))
    if actions:
        tasks = []
        for a in actions:
            text = a["task"] + "".join(f"{sep}{a[k]}" for sep, k in ((" — ", "owner"), (" · ", "due")) if a.get(k))
            if a.get("done"):
                text = f"✓ {text} ({label('done', lang)})"
            tasks.append(node(one_line(text, NODE_CHARS + 60)))
        branches.append(node(section_title("actionItems", lang), tasks))
    questions = [node(t(q.get("text"))) for q in content.get("openQuestions") or [] if q.get("text")]
    if questions:
        branches.append(node(section_title("openQuestions", lang), questions))
    return node(one_line(title, NODE_CHARS), branches)


#: Gap chegarasi: nuqta/so'roq/undov (yoki "…") va bo'shliqdan keyin BOSH harf, raqam, `[S1]` yoki
#: qo'shtirnoq. NEGA bosh harf sharti: "15 mln. so'm" yoki "1.2 versiya" gapni bo'lmasin.
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=[\[«\"„“'(0-9A-ZА-ЯЁЎҚҒҲ])")


def first_sentences(text: Any, limit: int = BRIEF_SENTENCES) -> str:
    """Matnning birinchi `limit` gapi (eski xulosalarda umumiy xulosa 3-5 gap - "Qisqacha" 1-2 gap)."""
    value = one_line(text)
    if not value:
        return ""
    return " ".join(_SENTENCE_END.split(value)[:limit])


def brief_duration(seconds: Any, lang: str) -> str:
    """`1 daq 53 s` / `1 мин 53 с` / `1 min 53 s`; soatdan uzunida soniyasiz (`1 soat 5 daq`).
    Yaxlitlash mobil `Math.round` bilan bir xil (yarim - yuqoriga; Python `round` 112.5 -> 112 berardi)."""
    h_word, m_word, s_word = _BRIEF_DURATION.get(lang, _BRIEF_DURATION["uz"])
    total = max(1, int(math.floor(float(seconds or 0) + 0.5)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} {h_word} {minutes} {m_word}" if minutes else f"{hours} {h_word}"
    if minutes:
        return f"{minutes} {m_word} {secs} {s_word}" if secs else f"{minutes} {m_word}"
    return f"{secs} {s_word}"


def brief_moment(epoch: float, lang: str) -> str:
    """Hafta kuni bilan: `10-oktabr 2026 (shanba), 12:37` / `10 октября 2026 (суббота), 12:37` /
    `October 10, 2026 (Saturday), 12:37`."""
    moment = dates.tashkent(epoch)
    hhmm = moment.strftime("%H:%M")
    month = dates.MONTHS.get(lang, dates.MONTHS["uz"])[moment.month - 1]
    weekday = dates.WEEKDAYS.get(lang, dates.WEEKDAYS["uz"])[moment.weekday()]
    if lang == "ru":
        return f"{moment.day} {month} {moment.year} ({weekday}), {hhmm}"
    if lang == "en":
        return f"{month} {moment.day}, {moment.year} ({weekday}), {hhmm}"
    return f"{moment.day}-{month} {moment.year} ({weekday}), {hhmm}"


def people_count(count: int, lang: str) -> str:
    """`2 ishtirokchi` / `2 участника` / `2 participants` (ruscha ko'plik shakllari bilan)."""
    if lang == "ru":
        tail = count % 100
        if count % 10 == 1 and tail != 11:
            word = "участник"
        elif 2 <= count % 10 <= 4 and not 12 <= tail <= 14:
            word = "участника"
        else:
            word = "участников"
        return f"{count} {word}"
    if lang == "en":
        return f"{count} participant{'' if count == 1 else 's'}"
    return f"{count} ishtirokchi"


#: Gap oxiridagi bo'shliq va `;:,` (`_sentence`), qarorga holat qo'shishda - tinish belgisi ham (`_TRAIL`).
_TAIL = re.compile(r"[\s;:,]+$")
_TRAIL = re.compile(r"[\s.;:,!?…]+$")


def _sentence(text: str, end: str = ".") -> str:
    """Band gap bo'lib tugasin: "Skriptni yuborish" -> "Skriptni yuborish." (savol - "?");
    oxiridagi `;:,` olib tashlanadi, tayyor tinish belgisiga tegilmaydi."""
    text = _TAIL.sub("", text)
    return text if not text or text[-1] in ".!?…" else f"{text}{end}"


def brief_block(content: dict[str, Any], speakers: dict[str, dict[str, Any]], lang: str,
                actions: list[dict[str, Any]] | None, *, title: str = "", meta: str = "",
                duration_sec: Any = None) -> dict[str, Any]:
    """"Qisqa xulosa" bloki. `lang` - XULOSA tili (yorliqlar ham, "Mas'ul/Muddat" ham, "2-ishtirokchi"
    ham): blok bitta tilda o'qilsin va ulashilsin ("Maqsad: Обсудить..." aralashmasi chiqmasin).
    Bo'sh band tushib qoladi. `actions` - jadval bilan BIR XIL vazifalar (asosiy xulosada jonli: odam
    tahrirlagani, bajarilgani "✓"), shu tilda yig'ilgan. Tasdiqlanmagan qaror va vazifa
    "(aniqlashtirish kerak)" belgisisiz ketmaydi - qisqa blok ham ishonchsiz bandni aniq deb ko'rsatmasin.

    Mobil `brief.ts` (`buildBrief` + `briefToText`) aynan shu matnni beradi - umumiy namuna
    `packages/fixtures/meeting-brief.json` ikkala tomonda tekshiriladi."""
    labels = _BRIEF_LABELS.get(lang, _BRIEF_LABELS["uz"])
    check_word = _BRIEF_CHECK.get(lang, _BRIEF_CHECK["uz"])
    check = f" ({check_word})"

    def t(value: Any) -> str:
        return one_line(render_tokens(value, speakers, lang))

    def name(key: str, count: int) -> str:
        return labels[key][0 if count == 1 else 1]

    items: list[dict[str, Any]] = []
    purpose = _sentence(t(content.get("purpose")))
    if purpose:
        items.append({"label": name("purpose", 1), "text": purpose})
    overview = _sentence(first_sentences(render_tokens(content.get("overview"), speakers, lang)))
    if overview:
        items.append({"label": name("overview", 1), "text": overview})
    points = [t(k.get("text")) for k in content.get("keyPoints") or [] if k.get("text")]
    if not points:
        # Eski qisqa qo'ng'iroq (fikrlarsiz) yoki uzun yig'ilish - mavzular ichidagi fikrlar,
        # ular ham bo'lmasa mavzularning o'zi (xulosasi yoki nomi).
        points = [t(k.get("text")) for topic in content.get("topics") or [] for k in topic.get("keyPoints") or []
                  if k.get("text")]
    if not points:
        points = [t(topic.get("summary")) or t(topic.get("title")) for topic in content.get("topics") or []]
    points = [_sentence(p) for p in points if p][:brief_points(_duration(content, duration_sec))]
    if points:
        items.append({"label": name("keyPoints", len(points)), "list": points})
    statuses = _STATUS.get(lang, _STATUS["uz"])
    decisions = []
    for d in content.get("decisions") or []:
        status = d.get("status") or "final"
        text = t(d.get("text"))
        if not text or status == "reversed":
            continue
        # Taxminiy/shartli yoki tasdiqlanmagan qaror yakuniydek o'qilmasin: belgilar BITTA qavsda,
        # gap ICHIDA, nuqtadan oldin - "Narx 15 mln so'm (taxminiy, aniqlashtirish kerak)."
        # Shart matni ham kartada (vazifadagidek): "Batafsil" da qarorlar endi yo'q - shart yo'qolmasin.
        # Shart matni bor bo'lsa "shartli" so'zi ortiqcha ("shartli, shart: ...").
        cond = t(d.get("condition"))
        word = statuses.get(status, status) if status != "final" and not (status == "conditional" and cond) else ""
        tags = [word, f"{_CONDITION.get(lang, 'shart')}: {cond}" if cond else "",
                check_word if d.get("needsConfirmation") or d.get("verified") is False else ""]
        tags = [x for x in tags if x]
        decisions.append(f"{_TRAIL.sub('', text)} ({', '.join(tags)})." if tags else _sentence(text))
    if decisions:
        items.append({"label": name("decisions", len(decisions)), "list": decisions})
    owner_set, owner_none = _BRIEF_OWNER.get(lang, _BRIEF_OWNER["uz"])
    due_set, due_none = _BRIEF_DUE.get(lang, _BRIEF_DUE["uz"])
    tasks = []
    for a in actions or []:
        task = one_line(a.get("task"))
        if not task:
            continue
        owner = one_line(a.get("owner")) or (_BRIEF_TEAM.get(lang, _BRIEF_TEAM["uz"]) if a.get("team") else "")
        due = one_line(a.get("due"))
        line = " ".join((_sentence(task), owner_set.format(x=owner) if owner else owner_none,
                         due_set.format(x=due) if due else due_none))
        line += check if a.get("check") else ""
        tasks.append(f"✓ {line}" if a.get("done") else line)
    if tasks:
        items.append({"label": name("actions", len(tasks)), "list": tasks})
    questions = [_sentence(t(q.get("text")), "?") for q in content.get("openQuestions") or [] if q.get("text")]
    questions = [q for q in questions if q]
    if questions:
        items.append({"label": name("questions", len(questions)), "list": questions})
    return {"kind": "brief", "title": one_line(title, TITLE_CHARS), "meta": meta, "items": items}


def _duration(content: dict[str, Any], duration_sec: Any = None) -> float:
    """Yig'ilish davomiyligi (soniya): berilgani, bo'lmasa xulosadagi `meeting.durationSec`."""
    for value in (duration_sec, (content.get("meeting") or {}).get("durationSec")):
        try:
            if value and float(value) > 0:
                return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def brief_covers(content: dict[str, Any], speakers: dict[str, dict[str, Any]], lang: str) -> set[str]:
    """To'liq hujjatdagi qaysi bo'limlarni "Qisqa xulosa" kartasi TO'LIQ beradi - ular "Batafsil" da
    qayta chiqmaydi (ega qarori 2026-10-15, "har fakt bir marta"):

    - umumiy xulosa (bitta gapdan iborat bo'lsa) va maqsad - kartada;
    - qarorlar, ochiq savollar - kartada hammasi (bekor qilingan qaror - `details_content` da qoladi);
    - "Hal qilinmagan masalalar" - `compact` vazifa/qaror/savolga tegishlisini olib tashlagan,
      kartadagi band o'z holati bilan ("Mas'ul: belgilanmagan", "taxminiy") turibdi.

    Asosiy fikrlar bu ro'yxatda YO'Q: kartaga sig'maganlari (`brief_points` dan keyingilari)
    "Batafsil" da qoladi - `details_content`. Mobil `briefCovers` aynan shu qoida."""
    covered: set[str] = {"openQuestions", "followUps"}
    if not any(d.get("status") == "reversed" for d in content.get("decisions") or []):
        covered.add("decisions")
    overview = one_line(render_tokens(content.get("overview"), speakers, lang))
    if not overview or first_sentences(overview) == overview:
        covered.add("overview")
    return covered


def details_content(content: dict[str, Any], duration_sec: Any = None) -> dict[str, Any]:
    """"Batafsil" uchun mazmun: kartadagi asosiy fikrlar olib tashlangan, bekor qilingan qarorlar
    qoladi (kartada ular yo'q - "Narx 15 mln edi, bekor qilindi" yo'qolmasin)."""
    points = [k for k in content.get("keyPoints") or [] if k.get("text")]
    shown = brief_points(_duration(content, duration_sec)) if points else 0
    reversed_ = [d for d in content.get("decisions") or [] if d.get("status") == "reversed"]
    # Maqsad kartada - "Qisqacha" bo'limida (to'liq umumiy xulosa) qayta yozilmaydi.
    return {**content, "keyPoints": points[shown:], "decisions": reversed_, "purpose": None}


def details_order(keys: list[str], duration_sec: Any) -> list[str]:
    """Qisqa yig'ilishda "Mavzular" oxirga (8 daqiqalik suhbatning boblari kam foyda beradi)."""
    minutes = float(duration_sec or 0) / 60
    if "topics" in keys and 0 < minutes <= SHORT_MEETING_MIN:
        keys = [k for k in keys if k != "topics"] + ["topics"]
    return keys


def meta_line(content: dict[str, Any], speakers: dict[str, dict[str, Any]], lang: str) -> str:
    """Kayfiyat, kalit so'zlar va faollik - BITTA xira qator (alohida bo'lim emas)."""
    parts = []
    s = content.get("sentiment") or {}
    mood = _SENTIMENT.get(lang, _SENTIMENT["uz"]).get(s.get("overall") or "", s.get("overall") or "")
    if mood:
        parts.append(f"{SECTION_TITLES['sentiment'].get(lang, 'Kayfiyat')}: {one_line(mood).lower()}")
    words = [one_line(w) for w in content.get("keywords") or [] if w]
    if words:
        parts.append(f"{SECTION_TITLES['keywords'].get(lang, 'Kalit so`zlar')}: {', '.join(words)}")
    # Birlashtirilgan spiker (`_map_merged`: S3 -> S1) ulushi o'zinikiga qo'shiladi - "Aziz 45%, Aziz 15%" emas.
    talk: dict[str, float] = {}
    for p in content.get("participants") or []:
        if p.get("speaker") and p.get("talkShare"):
            talk[p["speaker"]] = talk.get(p["speaker"], 0.0) + float(p["talkShare"])
    shares = [f"{one_line(speaker_name(sid, speakers, lang))} {round(share * 100)}%" for sid, share in talk.items()]
    if len(shares) > 1:
        parts.append(f"{_ACTIVITY.get(lang, _ACTIVITY['uz'])}: {', '.join(shares)}")
    return " · ".join(parts)


_ACTIVITY = {"uz": "Faollik", "ru": "Активность", "en": "Talk share"}


def brief_meta(recorded_at: float, duration_sec: float, people: int, lang: str) -> str:
    """`10-oktabr 2026 (shanba), 12:37 · 1 daq 53 s · 2 ishtirokchi` (bo'sh qism tushib qoladi)."""
    parts = [brief_moment(recorded_at, lang) if recorded_at else "",
             brief_duration(duration_sec, lang) if duration_sec else "",
             people_count(people, lang) if people else ""]
    return " · ".join(p for p in parts if p)


def transcript_lines(segments: Sequence[dict[str, Any]], speakers: dict[str, dict[str, Any]], lang: str,
                     stamp: Any = hms) -> list[tuple[str, str, str]]:
    """Transkript qatorlari (vaqt, kim, matn): bitta spikerning ketma-ket, oralig'i
    `MERGE_GAP_SEC` dan kam bo'laklari bitta paragrafga qo'shiladi (vaqti - birinchisiniki)."""
    merged: list[dict[str, Any]] = []
    last_end: float | None = None
    for seg in segments:
        text = clean(seg.get("text"))
        if not text:
            continue
        who = one_line(speaker_name(seg["speaker"], speakers, lang)) if seg.get("speaker") else ""
        start = float(seg.get("start") or 0)
        prev = merged[-1] if merged else None
        if (prev and prev["who"] == who and last_end is not None and start - last_end <= MERGE_GAP_SEC
                and len(prev["text"]) + len(text) < MERGE_CHARS):
            prev["text"] += " " + text
        else:
            merged.append({"start": start, "who": who, "text": text})
        last_end = float(seg.get("end") or start)
    return [(stamp(x["start"]), x["who"], x["text"]) for x in merged]


def build_document(*, title: str, recorded_at: float, duration_sec: float, speakers: dict[str, dict[str, Any]],
                   lang: str, now: float, parts: Sequence[str], template: str | None = None,
                   content: dict[str, Any] | None = None, actions: list[dict[str, Any]] | None = None,
                   segments: list[dict[str, Any]] | None = None, stale: bool = False,
                   text_lang: str | None = None, brief_actions: list[dict[str, Any]] | None = None,
                   user_title: bool = False) -> Document:
    """To'liq hujjat. `content` - `_map_merged` qilingan xulosa (yoki `None`), `actions` -
    `actions_from_rows`/`actions_from_content` natijasi, `segments` - transkript qatorlari,
    `text_lang` - yig'ilish tili (xulosa bo'lmasa mazmun tili shundan). `brief_actions` - o'sha
    vazifalar XULOSA tilida ("Qisqa xulosa" uchun); berilmasa - xulosaning o'zidan. `user_title` -
    `title` ni odam qo'ygan: "Qisqa xulosa" sarlavhasi ham shu, aks holda - SHU xulosaning sarlavhasi
    (mobil `summaryTitle` bilan bir xil: boshqa shablon xulosasi asosiy xulosa nomini olmasin)."""
    lang = lang if lang in _FALLBACK else "uz"
    content = content or {}
    doc = Document(lang=lang, title=one_line(title, TITLE_CHARS) or BRAND)
    body_lang = content.get("language") or text_lang or lang
    doc.text_lang = body_lang if body_lang in WORD_LANGS else lang
    # Vaqt formati hujjat bo'ylab BIR XIL (xulosadagi "(00:14)" transkriptdagi "[00:14]" ga mos
    # kelsin): soatdan uzun yig'ilishda hammasi `hh:mm:ss`, qisqasida `mm:ss`.
    longest = max(float(duration_sec or 0),
                  max((float(s.get("end") or s.get("start") or 0) for s in segments or []), default=0.0))
    stamp = hms if longest >= 3600 else clock
    if recorded_at:
        doc.meta.append((label("date", lang), format_moment(recorded_at, lang)))
    if duration_sec:
        doc.meta.append((label("duration", lang), format_duration(duration_sec, lang)))
    people = [speaker_name(sid, speakers, lang) for sid, sp in speakers.items() if not sp.get("merged_into")]
    if people:
        doc.meta.append((label("participants", lang), ", ".join(one_line(p) for p in people)))
    has_summary = bool(content) and any(p in SUMMARY_PARTS for p in parts)
    if has_summary and template:
        doc.meta.append((label("type", lang), get_template(template).title.get(lang, template)))
    if has_summary and stale:
        doc.notes.append(label("stale", lang))

    if "brief" in parts and content:
        brief_lang = content.get("language") if content.get("language") in _FALLBACK else lang
        if brief_actions is None:
            brief_actions = actions if actions is not None and brief_lang == lang else \
                actions_from_content(content, speakers, brief_lang)
        if list(parts) == ["brief"]:
            # Faqat "Qisqa xulosa": fayl/matn aynan shu ko'rinishda (sarlavha + bir qatorli meta),
            # hujjat sarlavhasi va "Sana: ..." qatorlari takrorlanmaydi. Spikerlar ajratilmagan
            # bo'lsa (`speakersAvailable: false`) ishtirokchilar soni yolg'on bo'lardi - yozilmaydi.
            count = len(people) or int((content.get("meeting") or {}).get("speakerCount") or 0)
            if (content.get("quality") or {}).get("speakersAvailable") is False:
                count = 0
            doc.head = False
            own = doc.title if user_title else ""
            brief_title = own or one_line(render_tokens(content.get("title"), speakers, brief_lang), TITLE_CHARS) \
                or doc.title
            doc.blocks.append(brief_block(content, speakers, brief_lang, brief_actions, title=brief_title,
                                          meta=brief_meta(recorded_at, duration_sec, count, brief_lang),
                                          duration_sec=duration_sec))
        else:
            # To'liq hujjatda sarlavha va sana/davomiylik/ishtirokchilar - hujjat boshida bor.
            doc.blocks.append({"kind": "h2", "text": label("brief", lang)})
            doc.blocks.append(brief_block(content, speakers, brief_lang, brief_actions, duration_sec=duration_sec))

    table_done = False
    if "summary" in parts and content:
        keys = [entry["key"] for entry in template_layout(template or "general", lang)]
        sections = _without_repeated_questions(content) if "followUps" in keys else content
        repeated: set[str] = set()
        if "brief" in parts:
            # "Batafsil": faqat kartada YO'Q narsa (har fakt bir marta) - ilova bilan bir xil.
            repeated = brief_covers(content, speakers, lang)
            sections = details_content(sections, duration_sec)
            keys = details_order(keys, duration_sec)
        for key in keys:
            if key == "actionItems" and "actions" not in parts:
                continue
            if key in repeated or key in META_SECTIONS:
                continue
            blocks = _section(key, sections, speakers, lang, actions, stamp)
            if blocks:
                doc.blocks.append({"kind": "h2", "text": section_title(key, lang)})
                doc.blocks += blocks
                table_done = table_done or key == "actionItems"
        # Kayfiyat, kalit so'zlar, faollik - alohida bo'lim emas, xulosa oxirida bitta xira qator.
        line = meta_line(content, speakers, lang)
        if line:
            doc.blocks.append({"kind": "muted", "text": line})
    if "actions" in parts and not table_done and actions:
        # Shablonda vazifalar bo'limi yo'q (yoki faqat `actions` so'ralgan) - jadval alohida bo'lim.
        doc.blocks.append({"kind": "h2", "text": section_title("actionItems", lang)})
        doc.blocks.append(_actions_table(actions, lang))
    if "mindmap" in parts and content:
        root = mindmap_tree(doc.title, content, speakers, lang, actions)
        if root["children"]:
            doc.blocks.append({"kind": "h2", "text": label("mindmap", lang)})
            doc.blocks.append({"kind": "tree", "root": root})
    if "transcript" in parts and segments is not None:
        doc.blocks.append({"kind": "h2", "text": label("transcript", lang)})
        if not speakers:
            doc.blocks.append({"kind": "muted", "text": label("no_speakers", lang)})
        doc.blocks.append({"kind": "transcript", "lines": transcript_lines(segments, speakers, lang, stamp)})
    doc.footer = f"{BRAND} · {label('generated', lang)}: {format_moment(now, lang)} ({label('tz', lang)})"
    return doc


# --- MD va TXT ----------------------------------------------------------------------------------


def _md_cell(value: str) -> str:
    return flat(value).replace("\\", "\\\\").replace("|", "\\|") or " "


def _brief_lines(block: dict[str, Any], *, markdown: bool) -> list[str]:
    """"Qisqa xulosa" - MD va TXT uchun BIR XIL qatorlar (MD da yorliqlar qalin)."""
    # NEGA model matni qochirilmaydi (`\_`): bu matn Telegram'ga ham ko'chiriladi, u yerda teskari
    # chiziqlar ko'rinib qolardi; hujjatning qolgan MD bo'limlari ham qochirmaydi.
    def bold(text: str) -> str:
        return f"**{text}**" if markdown else text

    out: list[str] = []
    if block.get("title"):
        # MD: sarlavha va meta - bitta paragrafda, majburiy qator uzilishi bilan (`  `).
        out.append(bold(block["title"]) + ("  " if markdown and block.get("meta") else ""))
    if block.get("meta"):
        out.append(block["meta"])
    if out:
        out.append("")
    for item in block["items"]:
        if "list" in item:
            out.append(bold(f"{item['label']}:"))
            out += [f"- {x}" for x in item["list"]]
        else:
            out.append(f"{bold(item['label'] + ':')} {item['text']}")
        out.append("")
    return out


def render_markdown(doc: Document) -> str:
    out: list[str] = []
    if doc.head:
        out += [f"# {doc.title}", ""]
        for name, value in doc.meta:
            out.append(f"**{name}:** {value}  ")
        if doc.meta:
            out.append("")
        for note in doc.notes:
            out += [f"> {note}", ""]
    for block in doc.blocks:
        kind = block["kind"]
        if kind == "brief":
            out += _brief_lines(block, markdown=True)
        elif kind == "h2":
            out += [f"## {block['text']}", ""]
        elif kind == "h3":
            out.append(f"### {block['text']}")
            if block.get("sub"):
                out.append(f"_{block['sub']}_")
            out.append("")
        elif kind == "p":
            out += ["  \n".join(block["text"].split("\n")), ""]
        elif kind == "muted":
            out += [f"_{block['text']}_", ""]
        elif kind == "ul":
            out += [f"{'  ' * level}- {text}" for level, text in block["items"]] + [""]
        elif kind == "quote":
            out += [f"> «{block['text']}» — {block['who']}", ""]
        elif kind == "table":
            out.append("| " + " | ".join(_md_cell(h) for h in block["head"]) + " |")
            out.append("|" + "|".join("---" for _ in block["head"]) + "|")
            out += ["| " + " | ".join(_md_cell(c) for c in row) + " |" for row in block["rows"]]
            out.append("")
        elif kind == "tree":
            def walk(node: dict[str, Any], depth: int) -> None:
                text = f"**{node['text']}**" if depth < 2 else node["text"]
                out.append(f"{'  ' * depth}- {text}")
                for child in node["children"]:
                    walk(child, depth + 1)
            walk(block["root"], 0)
            out.append("")
        elif kind == "transcript":
            for stamp, who, text in block["lines"]:
                head = f"**[{stamp}] {who}:**" if who else f"**[{stamp}]**"
                out += [f"{head} {text}", ""]
    if doc.head:
        out += ["---", f"_{doc.footer}_"]
    return "\n".join(out).rstrip() + "\n"


def render_text(doc: Document) -> str:
    out: list[str] = []
    if doc.head:
        out = [doc.title, "=" * max(3, len(doc.title))]
        out += [f"{name}: {value}" for name, value in doc.meta]
        out += [f"! {note}" for note in doc.notes]
        out.append("")
    for block in doc.blocks:
        kind = block["kind"]
        if kind == "brief":
            out += _brief_lines(block, markdown=False)
        elif kind == "h2":
            out += ["", block["text"], "-" * max(3, len(block["text"]))]
        elif kind == "h3":
            out += ["", block["text"] + (f" [{block['sub']}]" if block.get("sub") else "")]
        elif kind in ("p", "muted"):
            out += [block["text"], ""]
        elif kind == "ul":
            out += [f"{'  ' * level}- {text}" for level, text in block["items"]] + [""]
        elif kind == "quote":
            out += [f"«{block['text']}» — {block['who']}", ""]
        elif kind == "table":
            head = block["head"]
            for row in block["rows"]:
                out.append(f"{row[0]}. {flat(row[1])}")
                extra = [f"{head[i]}: {flat(row[i])}" for i in range(2, len(row)) if row[i]]
                if extra:
                    out.append("   " + " · ".join(extra))
            out.append("")
        elif kind == "tree":
            def walk(node: dict[str, Any], depth: int) -> None:
                out.append(f"{'  ' * depth}{'- ' if depth else ''}{node['text']}")
                for child in node["children"]:
                    walk(child, depth + 1)
            walk(block["root"], 0)
            out.append("")
        elif kind == "transcript":
            out += [f"[{stamp}] {who + ': ' if who else ''}{text}" for stamp, who, text in block["lines"]]
            out.append("")
    if doc.head:
        out += ["", "---", doc.footer]
    return "\n".join(out).strip() + "\n"


def render(doc: Document, fmt: str, *, font_dir: Path | str | None = None) -> bytes:
    """Hujjat -> fayl baytlari. DOCX/PDF kutubxonalari faqat shu yerda (kerak bo'lganda)
    yuklanadi: ular o'rnatilmagan serverda butun ilova emas, faqat shu format 503 bo'ladi."""
    if fmt == "md":
        return render_markdown(doc).encode("utf-8")
    if fmt == "txt":
        return render_text(doc).encode("utf-8")
    from . import export_render

    if fmt == "docx":
        return export_render.docx_bytes(doc)
    if fmt == "pdf":
        return export_render.pdf_bytes(doc, Path(font_dir) if font_dir else None)
    raise ValueError(fmt)


# --- fayl nomi ----------------------------------------------------------------------------------

_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]+')


def file_names(title: str, recorded_at: float, ext: str) -> tuple[str, str]:
    """(ASCII nom, haqiqiy nom): `haftalik-reja-2026-10-10.pdf` va `Haftalik reja 2026-10-10.pdf`.
    ASCII - eski klientlar uchun (`filename=`), haqiqiy - kirill/o'zbek sarlavha (`filename*=`)."""
    day = dates.tashkent(recorded_at).date().isoformat() if recorded_at else ""
    ascii_name = "-".join(x for x in (slug(title), day) if x)
    real = one_line(_UNSAFE_NAME.sub(" ", clean(title)), 100) or "Barno AI"
    return f"{ascii_name}.{ext}", f"{real}{' ' + day if day else ''}.{ext}"


def content_disposition(ascii_name: str, real_name: str) -> str:
    """RFC 6266: `filename` (ASCII) + `filename*` (UTF-8, foiz bilan kodlangan) - sarlavha
    latin-1 dan tashqariga chiqmaydi, telefon esa haqiqiy nomni ko'rsatadi."""
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(real_name, safe='')}"
