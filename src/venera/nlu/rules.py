"""Qoidaga asoslangan intent aniqlash (Step 1 - LLM'siz).

Tartib muhim: birinchi mos kelgan qoida yutadi. Umumiy qoidalar ("... och")
eng oxirida turadi, aks holda ular aniqroq qoidalarni ("... saytini och") yeb qo'yadi.

Step 3 da LLM qo'shilganda bu modul o'chirilmaydi - u "fastpath" bo'lib qoladi:
eng ko'p ishlatiladigan buyruqlar serverga bormasdan, ~0 ms da bajariladi.
"""

from __future__ import annotations

import re
from typing import Callable, NamedTuple

from .intents import Intent, IntentName
from .normalize import normalize, strip_suffix
from .numbers import words_to_int

_NUM = r"(?:\d+|[a-z'\s]+?)"


class Rule(NamedTuple):
    name: str
    pattern: re.Pattern[str]
    build: Callable[[re.Match[str], str], Intent]


def _simple(intent_name: IntentName) -> Callable[[re.Match[str], str], Intent]:
    def build(match: re.Match[str], text: str) -> Intent:  # noqa: ARG001
        return Intent(name=intent_name, raw_text=text, source="rules")
    return build


def _volume_set(match: re.Match[str], text: str) -> Intent:
    level = words_to_int(match.group("level") or "")
    if level is None:
        return Intent(name=IntentName.UNKNOWN, raw_text=text, source="rules")
    return Intent(
        name=IntentName.VOLUME_SET,
        level=max(0, min(100, level)),
        raw_text=text,
        source="rules",
    )


def _open_app(match: re.Match[str], text: str) -> Intent:
    raw = match.group("app").strip()
    # Oxirgi so'zdagi kelishik qo'shimchasi olib tashlanadi: "chromeni" -> "chrome"
    words = raw.split()
    # Alohida turgan yuklama tashlanadi: "google chrome ni och" -> "google chrome"
    while len(words) > 1 and words[-1] in ("ni", "ga", "da", "dan", "ning"):
        words.pop()
    if words:
        words[-1] = strip_suffix(words[-1])
    return Intent(name=IntentName.OPEN_APP, app=" ".join(words), raw_text=text, source="rules")


def _open_url(match: re.Match[str], text: str) -> Intent:
    return Intent(name=IntentName.OPEN_URL, url=match.group("url").strip(), raw_text=text, source="rules")


def _web_search(match: re.Match[str], text: str) -> Intent:
    return Intent(name=IntentName.WEB_SEARCH, query=match.group("query").strip(), raw_text=text, source="rules")


# Tartib bo'yicha qoidalar
RULES: list[Rule] = [
    Rule("cancel", re.compile(r"^(to'xta|to'xtat|bekor|bas|stop|jim bo'l)\b"), _simple(IntentName.CANCEL)),
    Rule("repeat", re.compile(r"\b(yana ayt|qaytar|takrorla|nima deding)\b"), _simple(IntentName.REPEAT)),
    Rule("help", re.compile(r"\b(nima qila olasan|yordam|imkoniyat|buyruqlar)\b"), _simple(IntentName.HELP)),
    Rule("version", re.compile(r"\b(versiya|qaysi versiya|versiyang)\b"), _simple(IntentName.VERSION)),

    Rule("time", re.compile(r"\b(soat necha|necha soat bo'ldi|hozir soat|vaqt qancha)\b"), _simple(IntentName.TIME)),
    Rule("date", re.compile(r"\b(bugun (qaysi kun|nechanchi|qanaqa kun)|bugungi sana|sana necha)\b"),
         _simple(IntentName.DATE)),

    Rule("lock", re.compile(r"\b(ekran(ni)?|kompyuter(ni)?|noutbuk(ni)?)\s+(qulfla|blokla|qulfa|lock)\b"),
         _simple(IntentName.LOCK_SCREEN)),
    Rule("lock2", re.compile(r"^(qulfla|blokla)\b"), _simple(IntentName.LOCK_SCREEN)),
    Rule("screenshot", re.compile(r"\b(skrinshot|screenshot|ekran(ni)?\s+(rasm|surat|suratga|rasmga))\b"),
         _simple(IntentName.SCREENSHOT)),

    # Ovoz: aniq daraja - baland/past qoidalaridan OLDIN turishi shart
    Rule("volume_set",
         re.compile(rf"\b(ovoz|tovush)(ni)?\s+(?P<level>{_NUM})\s*(foiz|protsent|ga|gacha)?\s*(qo'y|qil|o'rnat)?\s*$"),
         _volume_set),
    Rule("mute", re.compile(r"\b(ovoz|tovush)(ni)?\s+(o'chir|jim)|^jim qil\b"), _simple(IntentName.MUTE)),
    Rule("unmute", re.compile(r"\b(ovoz|tovush)(ni)?\s+(yoq|qaytar|tikla)\b"), _simple(IntentName.UNMUTE)),
    Rule("volume_up", re.compile(r"\b(ovoz|tovush)(ni)?\s+.*?(baland|ko'tar|oshir|kattalash|kuchaytir)"),
         _simple(IntentName.VOLUME_UP)),
    Rule("volume_down", re.compile(r"\b(ovoz|tovush)(ni)?\s+.*?(pasay|past|kamaytir|tushir|sekinlash|kichiklash)"),
         _simple(IntentName.VOLUME_DOWN)),

    # Qidiruv - "och" qoidalaridan oldin
    Rule("search", re.compile(r"^(?:(?:googl(?:e)?|gugl|internet|yandex|brauzer)(?:dan|da)?\s+)?"
                              r"(?P<query>.+?)\s+(?:ni\s+)?(?:qidir|izla|top)(?:ib ber)?\s*$"),
         _web_search),

    # URL / sayt
    Rule("url_explicit", re.compile(r"(?P<url>(?:https?://|www\.)\S+)"), _open_url),
    Rule("url_domain", re.compile(r"(?P<url>\b[\w-]+\.(?:uz|com|org|net|ru|io|dev)\b)\s*(?:ni\s+)?(?:sayt(?:ini)?\s+)?(?:och|ochib ber)"),
         _open_url),
    Rule("url_site", re.compile(r"(?P<url>.+?)\s+sayt(?:i|ini|ga)?\s+(?:och|ochib ber|kir)"), _open_url),

    # Dastur ochish - eng umumiy, oxirida
    Rule("open_app", re.compile(r"^(?P<app>.+?)\s+(?:och|ochib ber|ochgin|ishga tushir|yur)\s*$"), _open_app),
    Rule("open_app_rev", re.compile(r"^(?:och|ishga tushir)\s+(?P<app>.+?)\s*$"), _open_app),
]


def parse(text: str) -> Intent:
    """Xom matndan Intent. Hech qanday qoida mos kelmasa UNKNOWN."""
    clean = normalize(text)
    if not clean:
        return Intent(name=IntentName.UNKNOWN, raw_text="", source="rules")

    for rule in RULES:
        match = rule.pattern.search(clean)
        if match is None:
            continue
        intent = rule.build(match, clean)
        if intent.is_known:
            return intent

    return Intent(name=IntentName.UNKNOWN, raw_text=clean, source="rules")
