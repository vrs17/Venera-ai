"""Xodimlar ma'lumotnomasi: qiymatlarni tozalash, ro'yxatni yuklash, qidirish.

Chatdagi kontakt javoblari va tahrirlari (`contacts_chat`) 2026-10-07 olib
tashlandi - kontakt savollari endi yordamchiga ketadi. Ro'yxatning o'zi va
yuklash vositasi (`tools/contacts_import.py`) qoldi.

Ismlar TO'QIMA - haqiqiy ro'yxat testlarda yo'q.
"""

from __future__ import annotations

import pytest

from app.services import contacts
from app.services.contacts import ContactError, clean_email, clean_phone, clean_telegram
from app.tools.contacts_import import load, read_rows

LIST = """F.I.SH\tTelegram\tNomer\tBRB Tech Email
Qodirov Sanjarbek Olim o'g'li\t@sanjar_q\t+998901112233\ts.qodirov@example.uz
Qodirov Temur Aziz o'g'li\t-\t+998\tt.qodirov@example.uz
Nazarova Dilnoza Karim qizi\t@dilnoza_n\t+998935554433\t-
Xolmatov Ulug‘bek Ergashevich\t-\t+998\t-
Isroilov Botir Olimjonovich\t@botir_isroilov\t+998977778899\tb.isroilov@example.uz
"""


@pytest.fixture
def people():
    report = load(read_rows(LIST), actor="import:test")
    assert report == {"added": 5, "updated": 0, "same": 0, "problems": []}
    return contacts.store


# --- tozalash va yuklash ------------------------------------------------------------


def test_qiymatlar_tozalanadi():
    assert clean_phone("+998") is None and clean_phone("-") is None
    assert clean_phone("90 111 22 33") == "+998901112233"
    assert clean_phone("+998 (93) 555-44-33") == "+998935554433"
    assert clean_telegram("-") is None and clean_telegram("t.me/abc_d") == "@abc_d"
    assert clean_email(" A.B@Example.UZ ") == "a.b@example.uz"
    for bad in (lambda: clean_phone("12345"), lambda: clean_telegram("@a"), lambda: clean_email("x@")):
        with pytest.raises(ContactError):
            bad()


def test_yuklash_bosh_kataklar_va_qayta_yuklash(people):
    temur = people.find("Qodirov Temur")[0][0]
    assert temur.phone is None and temur.telegram is None and temur.email == "t.qodirov@example.uz"
    # Qayta yuklash: yangi telefon qo'shiladi, bo'sh katak bor qiymatni o'chirmaydi.
    again = LIST.replace("Qodirov Temur Aziz o'g'li\t-\t+998", "Qodirov Temur Aziz o'g'li\t-\t+998909998877")
    again += "Yangiboyev Aziz Ali o'g'li\t-\t-\t-\n"
    report = load(read_rows(again), actor="import:test")
    assert report["added"] == 1 and report["updated"] == 1 and report["same"] == 4
    assert people.get(temur.id).phone == "+998909998877" and people.get(temur.id).email == "t.qodirov@example.uz"
    assert people.count() == 6


def test_yuklashda_xato_maydon_qolganini_buzmaydi():
    report = load(read_rows("F.I.SH\tTelegram\tNomer\tEmail\nSobirov Ali\t@x\t123\tali@example.uz\n"),
                  actor="import:test")
    assert report["added"] == 1 and {p[1] for p in report["problems"]} == {"telegram", "phone"}
    assert contacts.store.all()[0].email == "ali@example.uz"


# --- qidirish (imlo farqlariga chidamli) -----------------------------------------------


@pytest.mark.parametrize("name", [
    "Nazarova Dilnoza",
    "Nazarova Dilnozaning",        # qo'shimcha bilan
    "Назарова Дилноза",            # kirill
    "nazarova dilnoza",            # kichik harf
])
def test_qidirish_imlo_va_yozuvga_chidamli(people, name):
    assert people.find(name)[0][0].full_name == "Nazarova Dilnoza Karim qizi"
