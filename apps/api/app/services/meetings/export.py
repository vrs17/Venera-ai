"""Eksport: xulosa (Markdown/TXT), transkript (TXT/SRT) - KOD chizadi, model emas.

`[S1]` tokenlari ismga almashtiriladi (ism bo'lmasa "1-ishtirokchi" /
"Участник 1" / "Speaker 1"), birlashtirilgan spikerlar (`mergedInto`)
qo'llanadi, sarlavhalar `layout` dan, sanalar til bo'yicha.
"""

from __future__ import annotations

import re
import unicodedata

from typing import Any

from . import dates
from .prompts import clock, hms

_TOKEN = re.compile(r"\[(S\d{1,2})\]")

_FALLBACK = {"uz": "{n}-ishtirokchi", "ru": "Участник {n}", "en": "Speaker {n}"}
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
    name = (speakers.get(sid) or {}).get("name")
    if name:
        return name
    number = re.sub(r"\D", "", sid) or "?"
    return _FALLBACK.get(lang, _FALLBACK["uz"]).format(n=number)


def render_tokens(text: Any, speakers: dict[str, dict[str, Any]], lang: str) -> str:
    return _TOKEN.sub(lambda m: speaker_name(m.group(1), speakers, lang), str(text or ""))


def slug(title: str) -> str:
    value = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return value[:60] or "meeting"


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
