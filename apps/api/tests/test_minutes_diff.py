"""Bayonnoma versiyalari orasidagi o'zgarishlar (`minutes/diff.py`): bandlar Word dagi raqamlar bilan
(`compose.numbering`), kun tartibi, sarlavha qismi va boshqa kalitlar; o'zbekcha qisqa bayon (`summary_uz`).

Modelsiz: asos - `meetings_fakes.minutes_reply` (ikki kun tartibi bandi, ikki bo'lim: 1 - ma'lumot uchun qabul,
2 - vazifa, 3 - vazifa; 4 - kod qo'shadigan nazorat bandi), ustida qo'lda o'zgartirishlar.
"""

from __future__ import annotations

import copy

from app.services.meetings.minutes import diff, validate
from meetings_fakes import minutes_reply, parse_lines

USER = "\n".join([
    "Output language: Uzbek (Cyrillic script)",
    "#1 [00:00] S1 (Aziz): Assalomu alaykum, hisobot bo'yicha boshlaymiz.",
    "#2 [00:06] S1 (Aziz): Narxni 15 mln so'm qilib belgilaymiz.",
    "#3 [00:14] S2: Men ikki kun ichida hisobotni tayyorlayman.",
])


def base() -> dict:
    data = minutes_reply(parse_lines(USER), USER)
    data["header"] = {**validate.EMPTY_HEADER, "attendees": []}
    return data


def task(text: str) -> dict:
    return {"kind": "task", "deadline": None, "deadlineDate": None, "responsible": [], "text": text,
            "subpoints": [], "followUp": None, "sourceSegmentIds": [1], "confidence": 0.9}


def test_ozgarishsiz_bosh():
    old = base()
    new = copy.deepcopy(old)
    # Manba qatorlar, ishonch va texnik qo'shimchalar - o'zgarish emas.
    new["sections"][0]["items"][1]["sourceSegmentIds"] = [3]
    new["sections"][0]["items"][1]["confidence"] = 0.4
    new["agenda"][0]["sourceSegmentIds"] = [2]
    new["quality"] = {"warnings": ["x"], "strict": False}
    ch = diff.changes(old, new)
    assert ch == {"items": {"changed": [], "added": [], "removed": []},
                  "agenda": {"changed": [], "added": [], "removed": []}, "header": [], "other": []}
    assert diff.empty(ch) and diff.empty(None) and diff.empty({}) and diff.summary_uz(ch) == ""
    # minutes-2 asosi (`header` yo'q) va bo'sh sarlavhali tahrir - sarlavha o'zgarmagan; izohlar [] = None.
    legacy = {k: v for k, v in old.items() if k != "header"}
    assert diff.empty(diff.changes(legacy, {**old, "notes": None}))


def test_ortaga_qoshilgan_band_keyingilari_ozgarmagan():
    old = base()
    new = copy.deepcopy(old)
    new["sections"][0]["items"].insert(1, task("[S1] га янги вазифа юклатилсин."))
    ch = diff.changes(old, new)
    # Yangi band 2-raqamni oldi; eski 2 va 3 endi 3 va 4 - "o'zgardi" deb ko'rsatilmaydi.
    assert ch["items"] == {"changed": [], "added": [2], "removed": []} and not diff.empty(ch)
    assert diff.summary_uz(ch) == "2-band qo'shildi"
    new["sections"][1]["items"] += [task("Биринчи қўшимча."), task("Иккинчи қўшимча.")]
    assert diff.changes(old, new)["items"]["added"] == [2, 5, 6]
    assert diff.summary_uz(diff.changes(old, new)) == "2, 5, 6-bandlar qo'shildi"


def test_almashtirish_va_olib_tashlash():
    old = base()
    new = copy.deepcopy(old)
    new["sections"][0]["items"][1]["deadline"] = "жорий йил 1 декабрга қадар"
    del new["sections"][1]["items"][0]
    ch = diff.changes(old, new)
    assert ch["items"] == {"changed": [2], "added": [], "removed": [3]}
    assert diff.summary_uz(ch) == "2-band o'zgardi; avvalgi 3-band olib tashlandi"
    new = copy.deepcopy(old)
    new["sections"][0]["items"][0]["text"] += " Бунда, муддат белгилансин."
    new["sections"][1]["items"][0]["responsible"] = ["[S1]"]
    ch = diff.changes(old, new)
    assert ch["items"] == {"changed": [1, 3], "added": [], "removed": []}
    assert diff.summary_uz(ch) == "1, 3-bandlar o'zgardi"
    # Ikki band bitta bandga almashsa: juft - o'zgargan, ortig'i - olib tashlangan (eski raqam).
    new = copy.deepcopy(old)
    new["sections"][0]["items"] = [new["sections"][0]["items"][0], task("Бирлаштирилган вазифа.")]
    del new["sections"][1]["items"][0]
    ch = diff.changes(old, new)
    assert ch["items"] == {"changed": [2], "added": [], "removed": [3]}


def test_kochirilgan_band_ozgargan_masala_siljishi_esa_yoq():
    old = base()
    moved = copy.deepcopy(old)
    moved["sections"][0]["items"].append(moved["sections"][1]["items"].pop(0))
    ch = diff.changes(old, moved)
    # Matn o'sha, raqami ham o'sha (3), lekin boshqa masala bo'limida - o'zgargan.
    assert ch["items"] == {"changed": [3], "added": [], "removed": []}
    # 1-masala (va bo'limi) olib tashlandi: qolgan bo'lim endi 1-masalaga ishora qiladi - band o'zgarmagan.
    cut = copy.deepcopy(old)
    del cut["agenda"][0]
    del cut["sections"][0]
    cut["sections"][0]["agendaIndex"] = 1
    ch = diff.changes(old, cut)
    assert ch["items"] == {"changed": [], "added": [], "removed": [1, 2]}
    assert ch["agenda"] == {"changed": [], "added": [], "removed": [1]}
    assert diff.summary_uz(ch) == "avvalgi 1, 2-bandlar olib tashlandi; kun tartibidan avvalgi 1-masala olib tashlandi"


def test_sarlavha_kun_tartibi_va_boshqa_kalitlar():
    old = base()
    new = copy.deepcopy(old)
    new["header"].update({"chair": "Бошқарув раиси А.Каримов", "attendees": ["[S1]"]})
    new["agenda"][1]["title"] = "Кредит масалалари тўғрисида"
    new["agenda"].append({"title": "Бошқа масала тўғрисида", "speakers": [], "report": "Муҳокама қилинди.",
                          "sourceSegmentIds": [3]})
    new["title"] = "Янги сарлавҳа"
    new["controller"] = None
    ch = diff.changes(old, new)
    assert ch["header"] == ["chair", "attendees"]
    assert ch["agenda"] == {"changed": [2], "added": [3], "removed": []}
    assert ch["other"] == ["title", "controller"] and ch["items"] == {"changed": [], "added": [], "removed": []}
    assert diff.summary_uz(ch) == ("kun tartibining 2-masalasi o'zgardi; kun tartibiga 3-masala qo'shildi; "
                                   "rais, qatnashchilar yangilandi; sarlavha, nazorat bandi o'zgardi")
    assert set(diff.HEADER_NAMES_UZ) == set(validate.HEADER_KEYS)


def test_summary_uz_yozilishi():
    ch = {"items": {"changed": [3, 7], "added": [8], "removed": [4]},
          "agenda": {"changed": [2], "added": [], "removed": []}, "header": ["chair", "attendees"], "other": ["title"]}
    assert diff.summary_uz(ch) == ("3, 7-bandlar o'zgardi; 8-band qo'shildi; avvalgi 4-band olib tashlandi; "
                                   "kun tartibining 2-masalasi o'zgardi; rais, qatnashchilar yangilandi; "
                                   "sarlavha o'zgardi")
    plural = {"items": {"changed": [], "added": [], "removed": [4, 5]},
              "agenda": {"changed": [2, 3], "added": [4, 5], "removed": [1, 6]}, "header": ["city"],
              "other": ["preamble", "notes"]}
    assert diff.summary_uz(plural) == ("avvalgi 4, 5-bandlar olib tashlandi; kun tartibining 2, 3-masalalari "
                                       "o'zgardi; kun tartibiga 4, 5-masalalar qo'shildi; kun tartibidan avvalgi "
                                       "1, 6-masalalar olib tashlandi; shahar yangilandi; kirish gapi, izohlar o'zgardi")
    assert diff.summary_uz({"header": ["organization", "chairedBy"]}) == "tashkilot nomi, kim huzurida yangilandi"
    assert not diff.empty({"other": ["notes"]}) and diff.empty({"items": {}, "agenda": {}, "header": []})
