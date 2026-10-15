"""Xulosa ko'rinishi: har fakt BIR marta (ega qarori, 2026-10-15).

MUAMMO: model har bo'limni alohida to'ldiradi va bitta faktni bir nechta bo'limga
yozadi. 8,5 daqiqalik yig'ilishda 31 band bor edi, orqasida 8 ta fakt:
"ChatGPT javoblarini yig'ib Gemini'ni o'qitish" 7 marta (asosiy fikr, vazifa,
g'oya, afzallik, tanlangan, mavzu, kuzatuv). Odam bir narsani qayta-qayta o'qiydi.

YECHIM - modelsiz, aniq qoida: transkriptning BIR joyiga ishora qilgan VA matni
o'xshash bandlar bitta fakt. Fakt eng muhim bo'limda qoladi, boshqa bo'limdagi
nusxasi o'chadi va qolgan bandga belgi (`alsoIn`: "Tanlangan", "Afzallik",
"Xavf") bo'lib qo'shiladi - ma'no yo'qolmaydi, takror yo'qoladi.

Tartib: vazifa > qaror > ochiq savol > asosiy fikr > xavf > keyingi qadam >
shablon bo'limlari > mavzu ichidagi fikr > muhim lahza. NEGA asosiy fikr xavfdan
oldin: "Qisqa xulosa" kartasida vazifa, qaror, savol va asosiy fikr bor - kartadagi
fakt kartada qolsin, yopiq "Batafsil" ga ko'chib ketmasin.

O'CHMAYDI: vazifalar va qarorlar (CRM, holat, belgilash ularga bog'langan; qisqa
blok va jadval ham ulardan), mavzularning o'zi (bob: sarlavha, vaqt oralig'i),
odam belgilagan lahza (`fromMark`), raqamlar va sanalar jadvali.

JAVOB PAYTIDA qo'llanadi (bazadagi xulosa o'zgarmaydi): eski yozuvlarga ham darhol
ishlaydi, xulosani qayta yaratish shart emas; qoida o'zgarsa - hammasi birdan
yangilanadi. Ilova (`GET .../summaries/{id}`) va eksport bir xil ko'rinishni oladi.
"""

from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any

from .templates import SECTION_TITLES

#: Ko'rinish versiyasi - `content.view.compact`. Ilova shuni ko'rsa o'zi takror qidirmaydi.
COMPACT_VERSION = 1

#: Bir xil fakt: transkript qatorlari kichik to'plamning kamida YARMI umumiy VA so'z
#: o'zaklari kichik to'plamning kamida YARMI umumiy (kamida 2 ta o'zak). Qatorsiz band -
#: faqat matn bo'yicha, qattiqroq (Jaccard).
IDS_OVERLAP = 0.5
TEXT_OVERLAP = 0.5
TEXT_MIN_SHARED = 2
TEXT_ONLY_JACCARD = 0.6
#: Muhim lahza - transkriptdan so'zma-so'z iqtibos, gapi boshqacha: qatori mos kelsa
#: kamroq so'z yetadi.
QUOTE_OVERLAP = 0.3

_APOS = str.maketrans({c: "'" for c in "ʻʼ’‘`´"})
_PUNCT = re.compile(r"[^\w\s']", re.UNICODE)

#: Ma'no tashimaydigan so'zlar (o'zak, 5 harf): "qaror qilindi", "aniqlandi" har bandda bor.
_STOP = frozenset({
    "va", "bilan", "uchun", "ham", "bu", "shu", "u", "bir", "esa", "emas", "yoki", "lekin", "ammo",
    "hamda", "orqal", "haqid", "bo'yi", "kerak", "qilis", "qilin", "qildi", "qilad", "bo'li", "bo'ld",
    "etild", "etis", "qaror", "kelis", "aniql", "rejal", "muhok", "taklif", "uning", "ular", "bizni",
    "barch", "har", "eng", "juda", "faqat", "yana", "endi", "keyi",
    "и", "в", "на", "с", "для", "по", "что", "не", "как", "это",
    "the", "and", "of", "to", "for", "with", "in", "on", "is", "be", "will",
})

#: Belgi (chip) matni - BIRLIK shaklda, xulosa tilida. Yo'q kalit - bo'lim sarlavhasi.
_CHIP: dict[str, dict[str, str]] = {
    "decisions": {"uz": "Qaror", "ru": "Решение", "en": "Decision"},
    "openQuestions": {"uz": "Ochiq savol", "ru": "Открытый вопрос", "en": "Open question"},
    "risks": {"uz": "Xavf", "ru": "Риск", "en": "Risk"},
    "nextSteps": {"uz": "Keyingi qadam", "ru": "Следующий шаг", "en": "Next step"},
    "ideas": {"uz": "G'oya", "ru": "Идея", "en": "Idea"},
    "pros": {"uz": "Afzallik", "ru": "Плюс", "en": "Pro"},
    "cons": {"uz": "Kamchilik", "ru": "Минус", "en": "Con"},
    "shortlist": {"uz": "Tanlangan", "ru": "В шорт-листе", "en": "Shortlisted"},
    "blockers": {"uz": "To'siq", "ru": "Блокер", "en": "Blocker"},
    "issues": {"uz": "Muammo", "ru": "Проблема", "en": "Issue"},
    "agreements": {"uz": "Kelishuv", "ru": "Договорённость", "en": "Agreement"},
    "wins": {"uz": "Yutuq", "ru": "Успех", "en": "Win"},
    "objections": {"uz": "E'tiroz", "ru": "Возражение", "en": "Objection"},
    "painPoints": {"uz": "Mijoz muammosi", "ru": "Боль клиента", "en": "Pain point"},
    "clientNeeds": {"uz": "Mijoz ehtiyoji", "ru": "Потребность клиента", "en": "Client need"},
    "concerns": {"uz": "Xavotir", "ru": "Опасение", "en": "Concern"},
    "milestones": {"uz": "Bosqich", "ru": "Этап", "en": "Milestone"},
    "dependencies": {"uz": "Bog'liqlik", "ru": "Зависимость", "en": "Dependency"},
    "scopeChanges": {"uz": "Hajm o'zgarishi", "ru": "Изменение объёма", "en": "Scope change"},
    "ourCommitments": {"uz": "Bizning majburiyat", "ru": "Наше обязательство", "en": "Our commitment"},
    "clientCommitments": {"uz": "Mijoz majburiyati", "ru": "Обязательство клиента", "en": "Client commitment"},
    "concepts": {"uz": "Tushuncha", "ru": "Понятие", "en": "Concept"},
    "homework": {"uz": "Uy vazifasi", "ru": "Домашнее задание", "en": "Homework"},
}

#: Belgisi ko'rsatilmaydigan bo'limlar: "Asosiy fikr", "Mavzu", "Muhim lahza" har faktga
#: tegishli bo'lardi - belgi hech narsa aytmaydi (faqat `view.merged` sanog'iga kiradi).
_SILENT = frozenset({"keyPoints", "topics", "highlights"})

#: Kompaniya va mahsulot nomlari - nutqni aniqlash ularni har xil yozadi ("BRVtek").
#: Iqtiboslarga (`quote`) tegilmaydi: ular transkriptdan so'zma-so'z dalil.
_SPELLING: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<![\w-])(?:BR[VB][\s-]?te(?:k|ch)|Bi[\s-]?Ar[\s-]?Bi[\s-]?te(?:k|ch))(?![\w-])", re.I),
     "BRB-Tech"),
)
_NO_SPELLING = frozenset({"quote", "id", "key", "speaker", "kind", "status", "template", "language",
                          "schemaVersion", "ref", "raw"})


def _stems(text: Any) -> set[str]:
    value = unicodedata.normalize("NFKC", str(text or "")).lower().translate(_APOS)
    words = _PUNCT.sub(" ", value).split()
    return {w[:5] for w in words if len(w) > 1 and w[:5] not in _STOP and w not in _STOP}


def _ids(item: dict[str, Any]) -> set[int]:
    raw = item.get("sourceSegmentIds")
    if raw is None and item.get("segmentId") is not None:
        raw = [item["segmentId"]]
    out = set()
    for x in raw or []:
        try:
            out.add(int(x))
        except (TypeError, ValueError):
            continue
    return out


def _overlap(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


class _Fact:
    """Bir fakt nusxalari - har biri o'z qatorlari va so'zlari bilan (bir nusxaga mos
    kelsa ham yetadi: "ChatGPT javoblari" va "Gemini'ni o'qitish" ikki xil iboralanadi)."""

    def __init__(self, item: dict[str, Any], ids: set[int], stems: set[str]) -> None:
        self.item = item
        self.members: list[tuple[set[int], set[str]]] = [(ids, stems)]
        self.also: list[tuple[str, str | None]] = []

    def same(self, ids: set[int], stems: set[str], quote: bool) -> bool:
        for m_ids, m_stems in self.members:
            if ids and m_ids:
                if _overlap(ids, m_ids) < IDS_OVERLAP:
                    continue
                shared = len(stems & m_stems)
                need = QUOTE_OVERLAP if quote else TEXT_OVERLAP
                if shared >= TEXT_MIN_SHARED and _overlap(stems, m_stems) >= need:
                    return True
            elif not quote and stems and m_stems:
                if len(stems & m_stems) / len(stems | m_stems) >= TEXT_ONLY_JACCARD:
                    return True
        return False


def _text_of(section: str, item: dict[str, Any]) -> str:
    if section == "actionItems":
        return str(item.get("task") or "")
    if section == "highlights":
        return str(item.get("quote") or "")
    return str(item.get("text") or "")


def chip_label(section: str, key: str | None, lang: str) -> str:
    name = key if section == "template" and key else section
    lang = lang if lang in ("uz", "ru", "en") else "uz"
    own = _CHIP.get(name)
    if own:
        return own[lang]
    return SECTION_TITLES.get(name, {}).get(lang) or name


def _spell(value: Any, key: str = "") -> Any:
    if key in _NO_SPELLING:
        return value
    if isinstance(value, str):
        for pattern, word in _SPELLING:
            value = pattern.sub(word, value)
        return value
    if isinstance(value, list):
        return [_spell(v, key) for v in value]
    if isinstance(value, dict):
        return {k: _spell(v, k) for k, v in value.items()}
    return value


def compact(content: dict[str, Any] | None) -> dict[str, Any] | None:
    """Ko'rinish: nomlar to'g'rilangan, takror faktlar birlashtirilgan. Asl lug'at o'zgarmaydi.
    Qayta qo'llansa natija o'zgarmaydi (`view.compact` bor bo'lsa - shundayicha qaytadi)."""
    if not isinstance(content, dict) or not content:
        return content
    if (content.get("view") or {}).get("compact") == COMPACT_VERSION:
        return content
    out: dict[str, Any] = _spell(copy.deepcopy(content))
    lang = str(out.get("language") or "uz")

    facts: list[_Fact] = []
    removed: dict[str, str] = {}  # o'chgan band id si -> qolgan band id si
    merged = 0

    def lists() -> list[tuple[str, str | None, list[dict[str, Any]], bool]]:
        """(bo'lim, shablon kaliti, ro'yxat, o'chirsa bo'ladimi) - muhimlik tartibida (modul izohi)."""
        rows: list[tuple[str, str | None, list[dict[str, Any]], bool]] = [
            ("actionItems", None, out.get("actionItems") or [], False),
            ("decisions", None, out.get("decisions") or [], False),
            ("openQuestions", None, out.get("openQuestions") or [], True),
            ("keyPoints", None, out.get("keyPoints") or [], True),
            ("risks", None, out.get("risks") or [], True),
            ("nextSteps", None, out.get("nextSteps") or [], True),
        ]
        for group in out.get("templateSections") or []:
            if isinstance(group, dict) and isinstance(group.get("items"), list):
                rows.append(("template", str(group.get("key") or ""), group["items"], True))
        for topic in out.get("topics") or []:
            if isinstance(topic, dict) and isinstance(topic.get("keyPoints"), list):
                rows.append(("topics", None, topic["keyPoints"], True))
        rows.append(("highlights", None, out.get("highlights") or [], True))
        return rows

    for section, key, items, removable in lists():
        own: list[_Fact] = []  # shu ro'yxatning o'z bandlari bir-biri bilan solishtirilmaydi
        keep: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                keep.append(item)
                continue
            ids, stems = _ids(item), _stems(_text_of(section, item))
            quote = section == "highlights"
            target = None
            if removable and not (quote and item.get("fromMark")):
                target = next((f for f in facts if f.same(ids, stems, quote)), None)
            if target is None:
                keep.append(item)
                own.append(_Fact(item, ids, stems))
                continue
            merged += 1
            target.members.append((ids, stems))
            if section not in _SILENT:
                target.also.append((section, key))
            if item.get("id") and target.item.get("id"):
                removed[str(item["id"])] = str(target.item["id"])
        items[:] = keep
        facts.extend(own)

    for fact in facts:
        if not fact.also:
            continue
        chips, seen = [], set()
        for section, key in fact.also:
            label = chip_label(section, key, lang)
            if label in seen or label == chip_label(_section_of(fact, out), None, lang):
                continue
            seen.add(label)
            chips.append({"section": section, "key": key, "label": label})
        if chips:
            fact.item["alsoIn"] = chips

    # Mavzu ichidagi fikr kartaga ko'chgan bo'lsa ham mavzu (bob) qoladi; bo'sh shablon bo'limi - yo'q.
    out["templateSections"] = [g for g in out.get("templateSections") or []
                               if not isinstance(g, dict) or g.get("items")]
    # Kuzatuv ro'yxati: vazifa, qaror va ochiq savol "Qisqa xulosa" kartasida o'z holati bilan
    # turibdi ("Mas'ul: belgilanmagan", "taxminiy") - ro'yxatda ikkinchi marta chiqmaydi.
    shown = {str(x.get("id")) for k in ("actionItems", "decisions", "openQuestions")
             for x in out.get(k) or [] if isinstance(x, dict)}
    follow = []
    for f in out.get("followUps") or []:
        if not isinstance(f, dict):
            continue
        ref = f.get("ref")
        ref = removed.get(str(ref), ref) if ref is not None else None
        if ref is not None and str(ref) in shown:
            merged += 1
            continue
        follow.append({**f, "ref": ref})
    out["followUps"] = follow
    for mark in out.get("userMarks") or []:
        if isinstance(mark, dict) and isinstance(mark.get("coveredBy"), list):
            mark["coveredBy"] = list(dict.fromkeys(removed.get(str(x), x) for x in mark["coveredBy"]))
    out["view"] = {"compact": COMPACT_VERSION, "merged": merged}
    return out


def _section_of(fact: _Fact, content: dict[str, Any]) -> str:
    """Qolgan band qaysi bo'limda - o'z bo'limi nomi belgi bo'lib takrorlanmasin
    ("Xavf" bandiga "Xavf" belgisi)."""
    for key in ("decisions", "openQuestions", "risks", "nextSteps"):
        if any(x is fact.item for x in content.get(key) or []):
            return key
    return ""
