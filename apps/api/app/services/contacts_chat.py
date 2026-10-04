"""Chatdagi xodimlar ma'lumotnomasi: qidirish va tahrirlash (tasdiq kartasi bilan).

Web, mini app va Telegram bot savolni BITTA joydan o'tkazadi (`chat.open_stream`),
va bu modul yuqoridagi yordamchidan OLDIN qaraydi:

  QIDIRISH  "Azizov Boburning telefoni?" - ism + aloqa so'zi (telefon, Telegram,
            email, kontakt). Javob ro'yxatning o'zidan, darhol. Ism topilmasa -
            savol odatdagidek yordamchiga ketadi.

  TAHRIRLASH  "... telefonini +998... ga o'zgartir", "Yangi xodim qo'sh: ...",
            "... telegramini o'chir", "... ni ro'yxatdan o'chir". Hech narsa
            DARHOL o'zgarmaydi: CRM dagi kabi "Taklif qilingan o'zgarish"
            kartasi chiqadi (`proposal` kadri - klientlar uni allaqachon
            ko'rsatadi) va faqat "Tasdiqlash" bosilganda saqlanadi
            (`/actions/{token}/confirm` -> `act`). Qiymat turi o'zidan
            aniqlanadi: `+998...` telefon, `@...` Telegram, `...@...` email.

  RUXSAT   Qidirish - har qanday kirgan foydalanuvchi. Taklif yaratish va
            TASDIQLASH - faqat `contacts_editor_roles` (ADMIN); rol tasdiq
            paytida QAYTA tekshiriladi.

Tahrir so'zlari ("o'chir", "qo'sh") boshqa savollarda ham uchraydi ("vazifani
o'chir") - shuning uchun buyruq faqat ro'yxatdagi xodim ismi, qiymat yoki
"xodim/ro'yxat" so'zi bilan birga bo'lsagina shu yerda qoladi.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import threading
import time
import uuid

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..core.config import settings
from ..schemas.auth import AuthUser
from . import contacts as _contacts
from .contacts import FIELDS, LABELS, ContactError, Employee, clean_name, fold
from .integrations.assistant import AnswerStream, AssistantError

log = logging.getLogger(__name__)

#: Kartadagi platforma nomi (klientlar katta harf bilan ko'rsatadi).
CONNECTOR = "xodimlar"
#: Bizning taklif kalitlari - yuqoridagi xizmatnikidan shu prefiks bilan ajraladi.
TOKEN_PREFIX = "ct_"
#: Yuqoridagi xizmatdagi kabi 15 daqiqa (kartada ham shu yozilgan).
PROPOSAL_TTL = 900
#: Bir javobda eng ko'pi nechta xodim ko'rsatiladi.
_SHOW_MAX = 5

# --- matndan qiymatlar -------------------------------------------------------------

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_TELEGRAM = re.compile(r"(?:(?<![\w@.])@|\b(?:https?://)?t\.me/)([A-Za-z][A-Za-z0-9_]{3,31})\b")
_PHONE = re.compile(r"(?<![\w+])\+?\d[\d\s\-()]{7,18}\d(?!\d)")


def extract_values(text: str) -> tuple[dict[str, list[str]], str]:
    """(topilgan qiymatlar, qiymatlarsiz matn). Qiymatlar tozalangan shaklda."""
    found: dict[str, list[str]] = {"email": [], "telegram": [], "phone": []}
    rest = text
    for match in _EMAIL.findall(rest):
        found["email"].append(match.lower())
    rest = _EMAIL.sub(" ", rest)
    for match in _TELEGRAM.finditer(rest):
        found["telegram"].append("@" + match.group(1))
    rest = _TELEGRAM.sub(" ", rest)
    for match in _PHONE.findall(rest):
        try:
            phone = _contacts.clean_phone(match)
        except ContactError:
            continue
        if phone:
            found["phone"].append(phone)
            rest = rest.replace(match, " ")
    return found, rest


# --- so'zlar -------------------------------------------------------------------

#: Maydon so'zlari (so'z BOSHI bo'yicha). Tartib muhim: "telegram" "tel" dan oldin.
_FIELD_WORDS = (
    ("telegram", ("telegram", "telgram", "telegarm", "telegramm", "tg", "username", "yuzername")),
    ("email", ("email", "e-mail", "emeil", "emayl", "imeyl", "pochta", "mail", "elektron")),
    ("phone", ("telefon", "tel", "nomer", "raqam", "mobil")),
    ("full_name", ("ismi", "ismini", "isming", "ism", "familiya", "fish", "fio")),
)
#: "raqam"/"nomer" shu so'zlar yonida telefon EMAS ("shartnoma raqami").
_NOT_PHONE = ("shartnoma", "buyruq", "hisob", "pasport", "inn", "jshshir", "ariza", "hujjat",
              "karta", "plastik", "xona", "kabinet", "stir", "vazifa", "task", "zayavka")
#: "kontak" (t siz) ham - odamlar shunday yozadi: "kontaklarini ko'rsat".
_CONTACT_WORDS = ("kontak", "contak", "contac", "kantak", "aloqa", "bog'lan", "boglan")
_DIRECTORY_WORDS = ("xodim", "ro'yxat", "royxat", "ro'yhat", "royhat", "kontak", "contak",
                    "ma'lumotnoma", "bazaga", "bazadan", "bazada")
_VERBS = {
    # `(?!il)` - majhul shakl BUYRUQ EMAS: "telefoni kiritilmagan xodimlar",
    # "yangi qo'shilgan", "o'chirilgan xodimlar" - bular savol.
    "add": (r"(?<![a-z'])qo'?sh(?!imcha|il)", r"(?<![a-z'])kirit(?!il)", r"\badd\b"),
    "update": (r"(?<![a-z'])o'?zgartir(?!il)", r"almashtir(?!il)", r"(?<![a-z'])yangila(?!n)",
               r"(?<![a-z'])tuzat(?!il)", r"(?<![a-z'])o'?rnat(?!il)", r"\bupdate\b"),
    "delete": (r"(?<![a-z'])o'?chir(?!il)", r"olib\s+tashla", r"chiqarib\s+tashla", r"\bdelete\b",
               r"\bremove\b"),
}
#: Ro'yxat so'rovi: "xodimlar kontaktlari ro'yxati", "barcha xodimlarning telefonlari".
#: "ro'yhat" (h bilan) va "contakt" (c bilan) ham - odamlar shunday yozadi.
_COLLECTIVE = ("xodimlar", "barcha", "hamma", "ro'yxat", "royxat", "ro'yhat", "royhat", "list",
               "jadval", "spisok", "kontaktlar", "kontaklar", "contaktlar", "contaklar", "contactlar")
#: "... kiritilmagan xodimlar" - kamchiliklar ro'yxati.
_MISSING = ("kiritilmagan", "yo'q", "yoq", "bo'sh", "to'ldirilmagan", "toldirilmagan", "yozilmagan")


def _fields(tokens: list[str]) -> set[str]:
    found: set[str] = set()
    exclude_raqam = any(t.startswith(x) for t in tokens for x in _NOT_PHONE)
    for token in tokens:
        for field, prefixes in _FIELD_WORDS:
            if field == "full_name":
                hit = token in prefixes or token.startswith(("familiya", "fish"))
            else:
                hit = any(token.startswith(p) for p in prefixes)
                if hit and field == "phone" and exclude_raqam and token.startswith(("raqam", "nomer")):
                    hit = False
            if hit:
                found.add(field)
                break
    return found


def _verb(folded: str) -> str | None:
    # O'chirish avval: "o'chirib qo'y" da ikkala so'z bor, ma'no - o'chirish.
    for kind in ("delete", "update", "add"):
        if any(re.search(p, folded) for p in _VERBS[kind]):
            return kind
    return None


def _editor(user: AuthUser) -> bool:
    return bool(set(user.roles) & set(settings.contacts_editor_roles))


# --- javob kadrlari ------------------------------------------------------------------


def _stream(text: str, *, proposal: dict[str, Any] | None = None) -> AnswerStream:
    frames: list[dict[str, Any]] = [{"type": "token", "text": text}]
    if proposal:
        frames.append({"type": "proposal", "proposal": proposal})
    frames.append({"type": "done", "route": "contacts"})
    raw = [json.dumps(f, ensure_ascii=False).encode("utf-8") + b"\n" for f in frames]
    return AnswerStream(request_id=uuid.uuid4().hex, frames=iter(raw), outcome={"route": "contacts"})


def describe(employee: Employee) -> str:
    lines = [f"**{employee.full_name}**"]
    for field in ("phone", "telegram", "email"):
        lines.append(f"- {LABELS[field]}: {employee.get(field) or 'kiritilmagan'}")
    return "\n".join(lines)


# --- kirish nuqtasi ---------------------------------------------------------------------


@dataclass
class _Ask:
    """Bitta xabarning tahlili."""

    text: str
    #: Qiymatlar (telefon, @username, email) olib tashlangan matn.
    rest: str
    tokens: list[str]
    fields: set[str]
    values: dict[str, list[str]]
    verb: str | None
    #: Ism bo'lishi mumkin bo'lgan so'zlar - asl yozuvida, tartib bilan.
    names: list[str]
    staff: bool          # "xodim"
    contact: bool        # "kontakt", "aloqa"
    directory: bool      # "ro'yxat", "baza", "xodim"
    collective: bool     # "xodimlar", "barcha", "ro'yxat"
    missing: bool        # "kiritilmagan", "yo'q"

    @property
    def has_values(self) -> bool:
        return any(self.values.values())


def _parse(text: str) -> _Ask:
    values, rest = extract_values(text)
    tokens = _contacts.words(rest)

    def has(prefixes) -> bool:
        return any(t.startswith(p) for t in tokens for p in prefixes)

    return _Ask(text=text, rest=rest, tokens=tokens, fields=_fields(tokens), values=values,
                verb=_verb(fold(text)), names=_name_words(rest), staff=has(("xodim",)),
                contact=has(_CONTACT_WORDS), directory=has(_DIRECTORY_WORDS),
                collective=has(_COLLECTIVE), missing=has(_MISSING))


def answer(question: str, user: AuthUser) -> AnswerStream | None:
    """Savol ma'lumotnomaga tegishli bo'lsa - tayyor javob oqimi, aks holda `None`
    (savol yuqoridagi yordamchiga ketadi)."""
    text = (question or "").strip()
    store = _contacts.store
    if not text or len(text) > 600:
        return None
    try:
        if store.count() == 0:
            return None
    except Exception:  # noqa: BLE001 - ma'lumotnoma ishlamasa chat to'xtamasin
        log.exception("Xodimlar ma'lumotnomasi o'qilmadi")
        return None
    ask = _parse(text)

    # Oldingi javob qiymat so'ragan edi ("kontaktlarini yozing") - shu xabar
    # o'sha xodim uchun. Ishlatilmasa ham OLIB TASHLANADI: keyinroq boshqa
    # gapga yopishib qolmasin.
    draft = _drafts.pop(user.actorId)
    if draft is not None and ask.has_values and ask.verb in (None, "add", "update"):
        result = _from_draft(draft, ask, user)
        if result is not None:
            return result

    if ask.verb is not None:
        result = _edit(ask, user)
        if result is not None:
            return result

    if not ((ask.fields - {"full_name"}) or ask.contact):
        return None
    found = store.find(ask.rest)
    # Matnda ro'yxatdagi odamning ISMI bo'lsa - o'sha odam haqida ("Botirning
    # kontaktlari"), bo'lmasa - butun ro'yxat ("xodimlar kontaktlari ro'yxati").
    person = bool(found) and any(
        _word_matches(w, _contacts.name_parts(found[0][0].full_name)) for w in ask.names)
    if ask.collective and not person:
        return _list(ask.fields, ask.missing, user)
    if not found:
        return None
    other = _other_person(found, ask.names)
    if other is not None:
        return _not_found(other, found, user)
    return _lookup(found, ask.fields, user)


def _list(fields: set[str], missing: bool, user: AuthUser) -> AnswerStream:
    """Butun ro'yxat - yoki so'ralgan maydon bo'yicha, yoki kiritilmaganlar."""
    people = _contacts.store.all()
    wanted = [f for f in ("phone", "telegram", "email") if f in fields] or ["phone", "telegram", "email"]
    names = ", ".join(LABELS[f].lower() for f in wanted)
    log.info("Xodimlar ma'lumotnomasi (%s): ro'yxat (%s%s)", user.actorId, ",".join(wanted),
             ", kiritilmaganlar" if missing else "")
    if missing:
        rows = []
        for e in people:
            gaps = [LABELS[f].lower() for f in wanted if not e.get(f)]
            if gaps:
                rows.append(e.full_name + (f" — {', '.join(gaps)} yo'q" if len(wanted) > 1 else ""))
        if not rows:
            return _stream(f"Hamma xodimda {names} kiritilgan.")
        text = f"**{names.capitalize()} kiritilmagan xodimlar — {len(rows)} ta**\n\n" + _numbered(rows)
        if _editor(user):
            text += ("\n\nTo'ldirish: \"Familiya Ismning telefonini +998... ga o'zgartir\" yoki "
                     "\"Familiya Ismga telegram qo'sh: @username\".")
        return _stream(text)
    rows = []
    for e in people:
        values = [e.get(f) for f in wanted if e.get(f)]
        if values:
            rows.append(f"{e.full_name} — " + " · ".join(values))
        elif len(wanted) == 3:
            rows.append(f"{e.full_name} — kiritilmagan")
    if len(wanted) == 3:
        text = f"**Xodimlar kontaktlari — {len(people)} ta**\n\n" + _numbered(rows)
        gaps = [(LABELS[f].lower(), sum(1 for e in people if not e.get(f))) for f in wanted]
        gaps = [f"{label} — {count} ta" for label, count in gaps if count]
        if gaps:
            text += "\n\nKiritilmagan: " + ", ".join(gaps) + ". Ro'yxati: \"telefoni kiritilmagan xodimlar\"."
    else:
        text = f"**Xodimlar: {names} — {len(rows)} ta**\n\n" + _numbered(rows)
        without = len(people) - len(rows)
        if without:
            text += f"\n\n{names.capitalize()} kiritilmagan: {without} ta xodim - \"{names} kiritilmagan xodimlar\"."
    return _stream(text)


def _numbered(rows: list[str]) -> str:
    return "\n".join(f"{i}. {row}" for i, row in enumerate(rows, 1))


def _lookup(found: list[tuple[Employee, float]], fields: set[str], user: AuthUser) -> AnswerStream:
    people = [e for e, _ in found]
    log.info("Xodimlar ma'lumotnomasi (%s): qidiruv, %d ta mos", user.actorId, len(people))
    if len(people) == 1:
        employee = people[0]
        text = describe(employee)
        missing = [f for f in (fields - {"full_name"}) if not employee.get(f)]
        if missing and _editor(user):
            text += (f"\n\n{LABELS[missing[0]]} hali kiritilmagan. Qo'shish uchun yozing: "
                     f"\"{employee.short}ning {LABELS[missing[0]].lower()}ini ... ga o'zgartir\".")
        return _stream(text)
    if len(people) <= _SHOW_MAX:
        return _stream("Bir nechta xodim mos keldi:\n\n" + "\n\n".join(describe(e) for e in people))
    names = "\n".join(f"- {e.full_name}" for e in people[:10])
    return _stream(f"Mos xodimlar ko'p ({len(people)} ta) - familiya va ismni to'liqroq yozing:\n{names}")


def _not_found(name: str, found: list[tuple[Employee, float]], user: AuthUser) -> AnswerStream:
    """Familiyasi o'xshash, ismi boshqa - bu BOSHQA odam, "mos kelgan" emas."""
    similar = ", ".join(e.full_name for e, _ in found[:_SHOW_MAX])
    text = f"**{name}** ma'lumotnomada yo'q."
    if similar:
        text += f" Familiyasi o'xshashlar: {similar}."
    if _editor(user):
        text += (f"\n\nQo'shish uchun yozing: \"{name} kontaktlarini kiritish kerak\" yoki birdaniga "
                 f"\"Yangi xodim qo'sh: {name}, +998..., @username, email\".")
    return _stream(text)


# --- tahrirlash --------------------------------------------------------------------------

#: Familiya VA ism aniq mos kelgan (har biri ~0.8+).
STRONG = 1.6


def _edit(ask: _Ask, user: AuthUser) -> AnswerStream | None:
    store = _contacts.store
    verb = ask.verb
    fields = ask.fields - {"full_name"}
    about_contacts = bool(fields) or ask.contact
    # Bizniki emasligini ERTA aniqlash: "vazifani o'chir", "arizani ro'yxatga qo'sh".
    if verb == "add" and not (ask.staff or ask.has_values or about_contacts):
        return None
    if verb == "update" and not (ask.has_values or ask.fields or ask.contact):
        return None
    if verb == "delete" and not (fields or ask.directory):
        return None

    rename_to = None
    lookup_text = ask.rest
    if verb == "update" and ask.fields == {"full_name"}:
        head, rename_to = _rename_parts(ask.text)
        lookup_text = head or ask.rest
    found = store.find(lookup_text)
    # Familiyasi o'xshash, lekin ismi boshqa - ma'lumotnomada YO'Q odam.
    stranger = _other_person(found, _name_words(lookup_text)) if found else None

    if verb == "add" and (ask.staff or not found or stranger):
        name = stranger or _new_name(ask.names)
        if name is None:
            return _stream(_ADD_EXAMPLE)
        return _guard(user) or _new_person(name, ask, found, user)

    if verb == "update" and stranger:
        # "Maxmudov Azizmurodning telefonini ... ga o'zgartir" - lekin u yo'q:
        # yangi xodim sifatida qo'shishni taklif qilamiz.
        return _guard(user) or _new_person(stranger, ask, found, user)

    if not found:
        if ask.has_values or ask.directory or about_contacts:
            return _stream("Bunday xodim ro'yxatda topilmadi - familiya va ismni tekshiring.")
        return None
    if stranger:
        return _not_found(stranger, found, user)
    if len(found) > 1:
        return _ambiguous([e for e, _ in found])
    employee = found[0][0]
    guard = _guard(user)
    if guard is not None:
        return guard
    if verb == "delete":
        return _clear_proposal(employee, fields, user) if fields else _delete_proposal(employee, user)
    return _update_proposal(employee, ask.values, ask.fields, user, rename_to=rename_to)


def _new_person(name: str, ask: _Ask, found: list[tuple[Employee, float]], user: AuthUser) -> AnswerStream:
    """Yangi xodim: qiymat bo'lsa - karta; kontakt so'ralgan, qiymat yo'q bo'lsa -
    so'raymiz va eslab qolamiz; faqat ism - ism bilan karta."""
    if not ask.has_values and ((ask.fields - {"full_name"}) or ask.contact):
        _drafts.put(user.actorId, {"mode": "add", "name": name})
        return _stream(
            f"**{name}** ma'lumotnomada hali yo'q - yangi xodim sifatida qo'shamiz.\n\n"
            "Kontaktlarini yozing (bittasi yoki hammasi):\n"
            "- telefon: +998 90 123 45 67\n- Telegram: @username\n- email: ism@brb-tech.uz\n\n"
            f"Faqat ism bilan qo'shish: \"Yangi xodim qo'sh: {name}\".")
    similar = next((e for e, s in found if s >= STRONG and _same_person(name, e)), None)
    return _add_proposal(name, ask.values, user, similar=similar)


_ADD_EXAMPLE = ("Yangi xodimning familiyasi va ismini yozing. Masalan:\n"
                "\"Yangi xodim qo'sh: Aliyev Vali Karimovich, +998901234567, @vali_a, v.aliyev@brb-tech.uz\"")


def _ambiguous(people: list[Employee]) -> AnswerStream:
    names = ", ".join(e.full_name for e in people[:_SHOW_MAX])
    return _stream(f"Bir nechta xodim mos keldi: {names}. Familiya va ismni to'liqroq yozing.")


def _guard(user: AuthUser) -> AnswerStream | None:
    if _editor(user):
        return None
    log.info("Xodimlar ma'lumotnomasi (%s): tahrir rad etildi - rol yo'q", user.actorId)
    return _stream("Xodimlar ma'lumotini faqat administrator o'zgartira oladi. "
                   "Qidirish esa hamma uchun ochiq.")


_RENAME = re.compile(
    r"(?P<head>.*?)\b(?:ismi\w*|isming\w*|familiya\w*|f\.?\s?i\.?\s?sh\w*|fio\w*)\s+"
    r"(?P<new>.+?)\s*(?:ga|ka|qa)?\s+(?:o'?zgartir|almashtir|tuzat)\w*\W*$",
    re.IGNORECASE)


def _rename_parts(text: str) -> tuple[str, str | None]:
    unified = _contacts._APOS.sub("'", text)
    match = _RENAME.search(unified)
    if not match:
        return "", None
    new = re.sub(r"\s+(?:ga|ka|qa)$", "", match.group("new").strip(" \"'«»:,"))
    return match.group("head"), new


#: Ism BO'LMAYDIGAN so'zlar: buyruqlar, maydonlar, murojaatlar, qo'shimchalar.
#: Qisqa so'zlar ANIQ ro'yxatda - prefiks bilan olinsa familiyani yeb qo'yardi
#: ("ber" -> "Berdiyev", "baza" -> "Bazarov", "ism" -> "Ismoilov").
_NOT_NAME_EXACT = {
    "yangi", "va", "bilan", "hamda", "uning", "ularning", "iltimos", "uchun", "bu", "shu", "menga",
    "bizga", "ber", "bering", "berish", "qil", "qiling", "qilish", "qilib", "qilamiz", "yoz", "yozing",
    "yozish", "kim", "kimning", "kimlar", "deb", "nomli", "ismli", "ism", "ismi", "ismini", "isming",
    "fish", "fio", "tel", "tg", "baza", "bazaga", "bazada", "bazadan", "add", "please", "update",
    "delete", "remove", "olib", "hurmatli", "janob", "xonim", "aka", "opa", "domla", "ustoz",
    "ni", "ga", "ka", "qa", "ning", "da", "dan", "ham", "endi", "hozir", "qanday", "qanaqa",
    "yo'q", "yoq", "bor", "emas", "mavjud", "bo'sh", "ayt", "ayting", "aytib", "aytchi",
}
_NOT_NAME = re.compile(
    r"^(?:qo'?sh\w*|kirit\w*|o'?zgartir\w*|almashtir\w*|yangila\w*|tuzat\w*|o'?chir\w*|"
    r"o'?rnat\w*|ro'?y[xh]at\w*|kontak\w*|contak\w*|contac\w*|kantak\w*|ma'lumot\w*|telefon\w*|nomer\w*|"
    r"raqam\w*|mobil\w*|tele?gr?am\w*|telegarm\w*|username\w*|e-?mail\w*|emayl\w*|imeyl\w*|"
    r"pochta\w*|xodim\w*|kerak\w*|"
    r"mumkin\w*|chiqar\w*|ko'?rsat\w*|tashla\w*|nima\w*|hamma\w*|barcha\w*|familiya\w*|"
    r"kiritilmagan|to'?ldirilmagan|yozilmagan|aloqa\w*|bog'?lan\w*|yubor\w*|jo'?nat\w*)$")
#: Hurmat so'zlari qo'shimchalari bilan: "Murod akani", "Malika opaning", "ustozga",
#: "akajon", "opamning". Ular ism EMAS - aks holda "Murod akani" ro'yxatda yo'q
#: odam bo'lib chiqardi, holbuki "Murod" Murodbek'ka aniq mos keladi.
_HONORIFIC = re.compile(
    r"^(?:aka|opa|uka|singil|xonim|janob|domla|ustoz|hurmatli|bro)(?:jon)?(?:m|im)?"
    r"(?:ni|ning|niki|ga|dan|da|lar|larni|larga)?$")
#: Egalik/kelishik qo'shimchalari - YANGI ism yozilganda oxirgi so'zdan olinadi.
_NAME_SUFFIX = re.compile(r"(?:ning|ni|ga|ka|qa|dan|da)$", re.IGNORECASE)


def _name_words(rest: str) -> list[str]:
    """Ism bo'lishi mumkin bo'lgan so'zlar (asl yozuvida, tartib bilan)."""
    kept = []
    for raw in re.split(r"[\s,;:!?]+", rest):
        word = raw.strip(".\"'«»()[]")
        if len(word) < 2 or not re.search(r"[^\W\d_]", word) or re.search(r"\d", word):
            continue
        folded = fold(word)
        if folded in _NOT_NAME_EXACT or _NOT_NAME.match(folded) or _HONORIFIC.match(folded):
            continue
        kept.append(word)
    return kept


def _base_name(name: str) -> str:
    """"Maxmudov Azizmurodning" -> "Maxmudov Azizmurod" (faqat oxirgi so'z)."""
    words_ = name.split()
    if words_:
        stripped = _NAME_SUFFIX.sub("", words_[-1])
        if len(stripped) >= 4:
            words_[-1] = stripped
    return " ".join(words_)


def _new_name(names: list[str]) -> str | None:
    """Yangi xodimning F.I.SH i - ism so'zlaridan."""
    if not 2 <= len(names) <= 6:
        return None
    try:
        return clean_name(_base_name(" ".join(names)))
    except ContactError:
        return None


def _word_matches(word: str, parts: list[str]) -> bool:
    return any(_contacts.similar(stem, part) >= 0.8 for stem in _contacts.stems(fold(word)) for part in parts)


def _other_person(found: list[tuple[Employee, float]], names: list[str]) -> str | None:
    """Eng mos xodim faqat BITTA bo'lagi bilan mos kelgan (familiya), yonidagi
    ism esa unga umuman o'xshamaydi - "Maxmudov Azizmurod" "Mahmudov Abdulla"
    EMAS. Shunday bo'lsa - yozilgan ism (ma'lumotnomada yo'q odam)."""
    if not found or len(names) < 2:
        return None
    best, score = found[0]
    if score >= STRONG:
        return None
    parts = _contacts.name_parts(best.full_name)
    hits = [_word_matches(w, parts) for w in names]
    for i, hit in enumerate(hits):
        if not hit:
            continue
        for j in (i - 1, i + 1):
            if 0 <= j < len(names) and not hits[j]:
                a, b = sorted((i, j))
                return _base_name(" ".join(names[a:b + 1]))
    return None


def _same_person(name: str, employee: Employee) -> bool:
    """Yangi yozilgan ism shu xodimniki bo'lishi mumkinmi (qo'shimchalar bilan)."""
    ours = _contacts.name_parts(name)
    theirs = _contacts.name_parts(employee.full_name)
    return len(ours) >= 2 and all(_word_matches(word, theirs) for word in ours[:2])


# --- suhbat davomi: qiymat kutilmoqda ------------------------------------------------------


class _Drafts:
    """"Kontaktlarini yozing" dan keyingi xabar - kim uchun (odam bo'yicha,
    10 daqiqa, xotirada)."""

    TTL = 600

    def __init__(self) -> None:
        self._items: dict[int, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def put(self, actor_id: int, draft: dict[str, Any]) -> None:
        with self._lock:
            self._items[actor_id] = {**draft, "expires": time.time() + self.TTL}

    def pop(self, actor_id: int) -> dict[str, Any] | None:
        with self._lock:
            draft = self._items.pop(actor_id, None)
        if draft is None or draft["expires"] < time.time():
            return None
        return draft


_drafts = _Drafts()


def _from_draft(draft: dict[str, Any], ask: _Ask, user: AuthUser) -> AnswerStream | None:
    """Kutilgan qiymatlar keldi - karta. Xabarda BOSHQA odamning ismi bo'lsa -
    qoralama ishlatilmaydi (u boshqa savol)."""
    if not _editor(user):
        return None
    if draft["mode"] == "add":
        name = draft["name"]
        if ask.names and not any(_word_matches(w, _contacts.name_parts(name)) for w in ask.names):
            return None
        return _add_proposal(name, ask.values, user, similar=None)
    employee = _contacts.store.get(draft["employee_id"])
    if employee is None:
        return _stream("Xodim topilmadi (o'chirilgan bo'lishi mumkin).")
    if ask.names and not any(_word_matches(w, _contacts.name_parts(employee.full_name)) for w in ask.names):
        return None
    return _update_proposal(employee, ask.values, ask.fields, user, rename_to=None)


# --- takliflar ------------------------------------------------------------------------------


class _Pending:
    """Kutayotgan takliflar - xotirada, 15 daqiqa. Qayta ishga tushsa yo'qoladi
    (kartadagi tugma "topilmadi" deydi - xavfsiz tomonga)."""

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def put(self, entry: dict[str, Any]) -> str:
        token = TOKEN_PREFIX + secrets.token_hex(12)
        now = time.time()
        with self._lock:
            for key in [k for k, v in self._items.items() if v["expires"] < now - 3600]:
                del self._items[key]
            self._items[token] = {**entry, "expires": now + PROPOSAL_TTL}
        return token

    def get(self, token: str) -> dict[str, Any] | None:
        with self._lock:
            return self._items.get(token)

    def pop(self, token: str) -> dict[str, Any] | None:
        with self._lock:
            return self._items.pop(token, None)


_pending = _Pending()


def _proposal(user: AuthUser, *, operation: str, summary: str, target: str,
              changes: list[dict[str, Any]], warnings: list[str], entry: dict[str, Any]) -> dict[str, Any]:
    token = _pending.put({**entry, "actor": user.actorId, "operation": operation, "summary": summary,
                          "label": target})
    log.info("Xodimlar ma'lumotnomasi (%s): taklif %s", user.actorId, operation)
    return {
        "token": token, "connector": CONNECTOR, "operation": operation, "summary": summary,
        "target": {"kind": "employee", "name": target},
        "changes": changes, "warnings": warnings,
        "expires_at": datetime.fromtimestamp(time.time() + PROPOSAL_TTL, timezone.utc).isoformat(),
    }


def _update_proposal(employee: Employee, values: dict[str, list[str]], fields: set[str],
                     user: AuthUser, *, rename_to: str | None) -> AnswerStream:
    changes: dict[str, str | None] = {}
    for field in ("phone", "telegram", "email"):
        if len(values.get(field) or []) > 1:
            return _stream(f"Bir nechta {LABELS[field].lower()} yozilgan - bittasini qoldiring.")
        if values.get(field):
            changes[field] = values[field][0]
    if rename_to is not None:
        try:
            changes["full_name"] = clean_name(rename_to)
        except ContactError as exc:
            return _stream(str(exc))
    wanted = fields - {"full_name"} - set(changes)
    if not changes:
        # Qiymat yo'q - so'raymiz, va keyingi xabar shu xodim uchun ekanini eslab qolamiz.
        _drafts.put(user.actorId, {"mode": "update", "employee_id": employee.id})
        asked = ", ".join(_EXAMPLES[f] for f in ("phone", "telegram", "email") if f in wanted) or \
            "telefon (+998 90 123 45 67), Telegram (@username) yoki email - qaysi biri o'zgarsa"
        return _stream(describe(employee) + f"\n\nYangi qiymatni yozing: {asked}.")
    changes = {f: v for f, v in changes.items() if employee.get(f) != v}
    if not changes:
        return _stream("Bu qiymatlar allaqachon kiritilgan - o'zgartiradigan narsa yo'q.\n\n" + describe(employee))
    rows = [{"field": LABELS[f], "from": employee.get(f), "to": v} for f, v in changes.items()]
    proposal = _proposal(
        user, operation="update_employee", target=employee.full_name,
        summary=f"Xodim ma'lumotini o'zgartirish: {employee.full_name}",
        changes=rows, warnings=[],
        entry={"kind": "update", "employee_id": employee.id, "changes": changes,
               "expect": {f: employee.get(f) for f in changes}})
    return _stream("Quyidagi o'zgarishni tasdiqlang:", proposal=proposal)


_EXAMPLES = {"phone": "telefon (+998 90 123 45 67)", "telegram": "Telegram (@username)",
             "email": "email (ism@brb-tech.uz)"}


def _clear_proposal(employee: Employee, clear: set[str], user: AuthUser) -> AnswerStream:
    changes = {f: None for f in clear if employee.get(f)}
    if not changes:
        return _stream("Bu maydon allaqachon bo'sh.\n\n" + describe(employee))
    rows = [{"field": LABELS[f], "from": employee.get(f), "to": None} for f in changes]
    proposal = _proposal(
        user, operation="update_employee", target=employee.full_name,
        summary=f"Xodim ma'lumotini o'chirish: {employee.full_name}",
        changes=rows, warnings=[],
        entry={"kind": "update", "employee_id": employee.id, "changes": changes,
               "expect": {f: employee.get(f) for f in changes}})
    return _stream("Quyidagi ma'lumot o'chiriladi - tasdiqlang:", proposal=proposal)


def _delete_proposal(employee: Employee, user: AuthUser) -> AnswerStream:
    proposal = _proposal(
        user, operation="delete_employee", target=employee.full_name,
        summary=f"Xodimni ro'yxatdan o'chirish: {employee.full_name}",
        changes=[{"field": "Holat", "from": "Ro'yxatda", "to": "O'chirilgan"}],
        warnings=["Xodim qidiruvda chiqmaydi. Yozuvi va tarixi saqlanadi - kerak bo'lsa qaytariladi."],
        entry={"kind": "delete", "employee_id": employee.id})
    return _stream("Xodim ro'yxatdan o'chiriladi - tasdiqlang:", proposal=proposal)


def _add_proposal(name: str, values: dict[str, list[str]], user: AuthUser, *,
                  similar: Employee | None) -> AnswerStream:
    record: dict[str, str | None] = {"full_name": name}
    for field in ("phone", "telegram", "email"):
        items = values.get(field) or []
        if len(items) > 1:
            return _stream(f"Bir nechta {LABELS[field].lower()} yozilgan - bittasini qoldiring.")
        record[field] = items[0] if items else None
    rows = [{"field": LABELS[f], "to": record[f]} for f in FIELDS if record.get(f)]
    warnings = []
    if similar is not None:
        warnings.append(f"Shunga o'xshash xodim bor: {similar.full_name}. Takror emasligini tekshiring.")
    missing = [LABELS[f] for f in ("phone", "telegram", "email") if not record.get(f)]
    if missing:
        warnings.append("Kiritilmagan: " + ", ".join(missing) + " - keyin qo'shish mumkin.")
    proposal = _proposal(
        user, operation="create_employee", target=name,
        summary=f"Yangi xodim qo'shish: {name}", changes=rows, warnings=warnings,
        entry={"kind": "add", "record": record})
    return _stream("Yangi xodim qo'shiladi - tasdiqlang:", proposal=proposal)


# --- tasdiqlash / rad etish (`/actions/{token}/...`) --------------------------------------------


def owns(token: str) -> bool:
    return str(token or "").startswith(TOKEN_PREFIX)


def act(verb: str, token: str, user: AuthUser) -> dict[str, Any]:
    """`confirm` | `cancel` | `status`. Natija - `ActionResult` shakli.

    Topilmagan yoki BOSHQA odamniki - 404 (farqi aytilmaydi), yuqoridagi
    xizmatdagi kabi.
    """
    entry = _pending.get(token)
    if entry is None or entry["actor"] != user.actorId:
        raise AssistantError("taklif topilmadi", status=404)
    base = {"token": token, "connector": CONNECTOR, "operation": entry["operation"],
            "summary": entry["summary"]}
    if time.time() > entry["expires"]:
        _pending.pop(token)
        return {**base, "status": "expired"}
    if verb == "status":
        return {**base, "status": "pending"}
    if verb == "cancel":
        _pending.pop(token)
        log.info("Xodimlar ma'lumotnomasi (%s): taklif rad etildi", user.actorId)
        return {**base, "status": "cancelled"}
    if not _editor(user):
        return {**base, "status": "failed", "ok": False,
                "error": "Xodimlar ma'lumotini faqat administrator o'zgartira oladi"}
    entry = _pending.pop(token)
    if entry is None:                    # ikki marta bosildi - birinchisi oldi
        raise AssistantError("taklif topilmadi", status=404)
    actor = f"venera:{user.actorId}"
    store = _contacts.store
    try:
        if entry["kind"] == "update":
            employee = store.update(entry["employee_id"], entry["changes"], actor=actor,
                                    expect=entry["expect"])
        elif entry["kind"] == "delete":
            employee = store.delete(entry["employee_id"], actor=actor)
        else:
            employee = store.add(entry["record"], actor=actor)
    except ContactError as exc:
        return {**base, "status": "failed", "ok": False, "error": str(exc)}
    return {**base, "status": "executed", "ok": True, "result": {"key": employee.short}}
