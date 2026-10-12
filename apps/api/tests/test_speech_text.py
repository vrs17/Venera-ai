"""TTS'ga ketadigan matn: sana, vaqt va qisqartmalar so'z bilan.

Kutilgan shakllar JONLI eshitib tanlangan (2026-09-23): har biri TTS'da
sintez qilinib, STT bilan qayta matnga o'girilgan. Bu yerda ular o'zgarmasligi
qo'riqlanadi - aks holda "tushunarsiz" ovoz sezdirmasdan qaytib kelardi.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from app.services.speech_text import SpokenNames, attach, cardinal, for_speech, ordinal

#: Testlar sanaga BOG'LIQ bo'lmasligi uchun "bugun" qat'iy.
BUGUN = date(2026, 9, 23)


def speak(text: str) -> str:
    return for_speech(text, today=BUGUN)


# --- sonlar ------------------------------------------------------------------


@pytest.mark.parametrize("n, words", [
    (1, "birinchi"), (2, "ikkinchi"), (3, "uchinchi"), (4, "to'rtinchi"),
    (6, "oltinchi"), (7, "yettinchi"), (9, "to'qqizinchi"), (10, "o'ninchi"),
    (11, "o'n birinchi"), (20, "yigirmanchi"), (21, "yigirma birinchi"),
    (30, "o'ttizinchi"), (31, "o'ttiz birinchi"),
    (2000, "ikki minginchi"), (2010, "ikki ming o'ninchi"),
    (2026, "ikki ming yigirma oltinchi"),
    (1990, "bir ming to'qqiz yuz to'qsoninchi"),
])
def test_tartib_son(n, words):
    """Qo'shimcha faqat OXIRGI so'zga: unli bilan tugasa "nchi", aks holda
    "inchi" ("ikki" -> "ikkinchi", "besh" -> "beshinchi")."""
    assert ordinal(n) == words


def test_sanoq_son():
    assert cardinal(0) == "nol"
    assert cardinal(45) == "qirq besh"
    assert cardinal(18) == "o'n sakkiz"


@pytest.mark.parametrize("word, suffix, joined", [
    ("sentabr", "dan", "sentabrdan"),
    ("qirq", "ga", "qirqqa"),             # q dan keyin g -> q
    ("ellik", "gacha", "ellikkacha"),     # k dan keyin g -> k
    ("to'qqiz", "da", "to'qqizda"),
])
def test_qoshimcha_imlosi(word, suffix, joined):
    assert attach(word, suffix) == joined


# --- sanalar -----------------------------------------------------------------


@pytest.mark.parametrize("text, spoken", [
    # Foydalanuvchi keltirgan ikki shakl. Joriy yil AYTILMAYDI.
    ("28.09.2026", "yigirma sakkizinchi sentabr"),
    ("2026-10-21", "yigirma birinchi oktabr"),
    ("Bugun (2026-09-23) 10 kishi", "Bugun (yigirma uchinchi sentabr) 10 kishi"),
    # Boshqa yil - rasmiy tartibda, yil oldin.
    ("12.05.1990", "bir ming to'qqiz yuz to'qsoninchi yil o'n ikkinchi may"),
    # JONLI XATO: yopishgan qo'shimcha serverda 422 berib, javob ovozsiz qolgan.
    ("09.09.2025dan tuzilgan", "ikki ming yigirma beshinchi yil to'qqizinchi sentabrdan tuzilgan"),
    ("25.09.2026gacha topshiring", "yigirma beshinchi sentabrgacha topshiring"),
    ("2026-09-23dan beri", "yigirma uchinchi sentabrdan beri"),
    # Takroriy "yil": so'zlarda yil bor, "... yil yildan" eshitilmasin.
    ("09.09.2025-yildan", "ikki ming yigirma beshinchi yil to'qqizinchi sentabrdan"),
    ("09.09.2025 yildan", "ikki ming yigirma beshinchi yil to'qqizinchi sentabrdan"),
    ("25.06.2026 yil", "yigirma beshinchi iyun"),
    ("Sana: 25.09.2026 y.", "Sana: yigirma beshinchi sentabr."),
    ("25.09.2026 y. imzolangan", "yigirma beshinchi sentabr imzolangan"),
    # Alohida yozilgan qo'shimcha ham so'zga qo'shiladi.
    ("25.09.2026 dan 30.09.2026 gacha", "yigirma beshinchi sentabrdan o'ttizinchi sentabrgacha"),
    ("25.09.2026 kuni", "yigirma beshinchi sentabr kuni"),
    # Oraliq: oy nomi ikkala tomonda (qisqa shakl ikki xil eshitildi).
    ("25.09.2026-30.09.2026 oralig'ida",
     "yigirma beshinchi sentabrdan o'ttizinchi sentabrgacha oralig'ida"),
    ("2026-09-25 — 2026-09-30", "yigirma beshinchi sentabrdan o'ttizinchi sentabrgacha"),
    ("01.10.2025-14.10.2025",
     "ikki ming yigirma beshinchi yil birinchi oktabrdan o'n to'rtinchi oktabrgacha"),
    ("28.12.2026 – 10.01.2027",
     "yigirma sakkizinchi dekabrdan ikki ming yigirma yettinchi yil o'ninchi yanvargacha"),
    # Ro'yxat - "16 xonali karta" emas.
    ("Siz 01.09.2026, 03.09.2026 va 05.09.2026 kunlari",
     "Siz birinchi sentabr, uchinchi sentabr va beshinchi sentabr kunlari"),
    # Qo'shimcha bo'lmagan so'z yopishsa - ajratiladi, "sentabryangi" emas.
    ("25.09.2026yangi", "yigirma beshinchi sentabr yangi"),
])
def test_sana_soz_bilan(text, spoken):
    assert speak(text) == spoken


def test_joriy_yil_bugundan_olinadi():
    """Yil qat'iy yozilmagan: kelasi yil xuddi shu sana yil bilan aytiladi."""
    assert for_speech("28.09.2026", today=date(2027, 1, 5)) == \
        "ikki ming yigirma oltinchi yil yigirma sakkizinchi sentabr"


# --- vaqt --------------------------------------------------------------------


@pytest.mark.parametrize("text, spoken", [
    # Foydalanuvchi keltirgan holat: "to'qqiz nol o'n sakkiz nol" eshitilardi.
    ("Ish vaqti 09:00-18:00", "Ish vaqti soat to'qqizdan o'n sakkizgacha"),
    ("Ish vaqti 09:00–18:00.", "Ish vaqti soat to'qqizdan o'n sakkizgacha."),
    # "soat" bir marta: matnda bo'lsa qo'shilmaydi, davomida ham.
    ("Soat 09:00 dan 17:00 gacha", "Soat to'qqizdan o'n yettigacha"),
    ("soat: 13:30", "soat: o'n uch o'ttiz"),
    ("09:12 da keldingiz", "soat to'qqiz o'n ikkida keldingiz"),
    ("13:05", "soat o'n uch nol besh"),
    # Soniya aytilmaydi.
    ("08:45:12da keldi", "soat sakkiz qirq beshda keldi"),
    ("08:50ga", "soat sakkiz ellikka"),
    ("08:40gacha", "soat sakkiz qirqqacha"),
    # Sana bilan birga.
    ("23.09.2026 08:45", "yigirma uchinchi sentabr soat sakkiz qirq besh"),
    ("2026-09-23T08:45:00", "yigirma uchinchi sentabr soat sakkiz qirq besh"),
])
def test_vaqt_soz_bilan(text, spoken):
    assert speak(text) == spoken


# --- qisqartmalar ------------------------------------------------------------


@pytest.mark.parametrize("text, spoken", [
    # Foydalanuvchi keltirgan holat: "b chepche" eshitilardi.
    ("“BRB-TECH” MCHJ bosh direktori", "BRB-TECH mas'uliyati cheklangan jamiyati bosh direktori"),
    ("“BRB-TECH” MChJ bosh direktori", "BRB-TECH mas'uliyati cheklangan jamiyati bosh direktori"),
    ("“BRB-TECH” M.Ch.J. rahbari", "BRB-TECH mas'uliyati cheklangan jamiyati rahbari"),
    ("BRB-TECH MChJga", "BRB-TECH mas'uliyati cheklangan jamiyatiga"),
    ("“BRB-TECH” MChJ.", "BRB-TECH mas'uliyati cheklangan jamiyati."),
    # Nomsiz - qaratqich qo'shimchasiz: "jamiyat ochish", "jamiyati ochish" emas.
    ("MChJ ochish uchun", "mas'uliyati cheklangan jamiyat ochish uchun"),
    ("yangi MChJ ochildi", "yangi mas'uliyati cheklangan jamiyat ochildi"),
    ("«Anor» XK", "Anor xususiy korxonasi"),
    ("“Ipak Yo'li” ATB", "Ipak Yo'li aksiyadorlik tijorat banki"),
])
def test_qisqartma_soz_bilan(text, spoken):
    assert speak(text) == spoken


def test_qavsdagi_qisqartma_qoshilmaydi():
    """`(qisqartmasi: MChJ)` qo'shilsa, qavs ichidagi "MChJ" yana "mchj"
    bo'lib o'qiladi - jonli eshitilgan."""
    assert "MChJ" not in speak("“BRB-TECH” MCHJ") and "qisqartmasi" not in speak("“BRB-TECH” MCHJ")


# --- tegilmaydi --------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "31.02.2026",                       # yaroqsiz sana
    "2026-13-45 kodli",                 # yaroqsiz ISO - kod
    "12026-09-23",
    "1.5dan oshiq",                     # kasr
    "server 10.10.50.4 da",             # IP
    "versiya v1.2.3",
    "1.10.10.2026da",
    "8600-1234-5678-9012",              # karta
    "2450000 so'm",                     # normalizator to'g'ri o'qiydi
    "24:00", "12:60", "3:2", "2:255 oyat",
    "AJOYIB natija",                    # "AJ" so'z ichida
    "info@mchj.uz, brb.uz/MChJ",        # manzil ichida - qisqartma emas
    "o‘z xohishimga ko‘ra, ta’til",     # apostroflar - harf, qoladi
    "Kechikishlarni tekshirayapman.",   # kutish ovozlari o'zgarmasligi kerak
])
def test_boshqa_matnga_tegilmaydi(text):
    assert speak(text) == text


def test_jonli_xato_bergan_javob():
    """Foydalanuvchi ko'rgan javob shakli (ismsiz): 422 bergan sana, "b
    chepche" bo'lgan kompaniya nomi - ikkalasi bitta javobda."""
    text = ("Ariza “BRB-TECH” MCHJ bosh direktoriga. Men bilan 09.09.2025dan tuzilgan "
            "mehnat shartnomasini bekor qilishingizni so'rayman. Sana: 25.09.2026 Fayl ilova qilindi.")
    assert speak(text) == (
        "Ariza BRB-TECH mas'uliyati cheklangan jamiyati bosh direktoriga. Men bilan ikki ming "
        "yigirma beshinchi yil to'qqizinchi sentabrdan tuzilgan mehnat shartnomasini bekor "
        "qilishingizni so'rayman. Sana: yigirma beshinchi sentabr Fayl ilova qilindi.")


def test_kutish_ovozlariga_tegilmaydi():
    """Kutish gaplari oldindan sintez qilingan (`services/hold.py`). Ularda
    sana, vaqt, qisqartma yo'q - va bu funksiya ularni o'zgartirsa, yangi
    sintez eski kalitdagi ovozdan farq qilib qolardi."""
    from app.services.hold import all_clips

    changed = [text for _, text in all_clips() if speak(text) != text]
    assert not changed, changed


# --- loyiha nomlari (talaffuz lug'ati) -------------------------------------------

#: Haqiqiy nom emas - qoidani tekshirish uchun. "bank" k bilan tugaydi:
#: qo'shimcha imlosi ham ko'rinsin ("bankka").
NOMLAR = {"DVSIB": "Raqamli bank"}


def nomli(text: str) -> str:
    return for_speech(text, today=BUGUN, names=NOMLAR)


@pytest.mark.parametrize("text, spoken", [
    ("DVSIB loyihasida 2 ta vazifa topildi:", "Raqamli bank loyihasida 2 ta vazifa topildi:"),
    ("**DVSIB** loyihasida", "**Raqamli bank** loyihasida"),
    ("Vazifani DVSIBga qo'shing.", "Vazifani Raqamli bankka qo'shing."),
    ("DVSIB-ning sprinti", "Raqamli bankning sprinti"),
    ("Vazifalaringiz odatda DVSIB.", "Vazifalaringiz odatda Raqamli bank."),
    ("DVSIB va HR loyihalari", "Raqamli bank va HR loyihalari"),
    # Nom yonida yozilgan bo'lsa - ikki marta aytilmaydi.
    ("Raqamli bank (DVSIB) loyihasida", "Raqamli bank loyihasida"),
    ("DVSIB (Raqamli bank) loyihasida", "Raqamli bank loyihasida"),
])
def test_loyiha_kodi_nom_bilan_aytiladi(text, spoken):
    assert nomli(text) == spoken


@pytest.mark.parametrize("text", [
    "DVSIB-266 yopildi.",                       # vazifa kaliti - loyiha nomi EMAS
    "- DVSIB-12 - Shartnoma tayyor.",
    "Havola: https://crm.example.uz/DVSIB/board",
    "Pochta: dvsib@example.uz va DVSIB.uz",
    "XDVSIB va DVSIBX va DVSIB_1",               # boshqa so'z ichida
    "Dvsib",                                     # katta-kichik harf aniq
])
def test_loyiha_kodi_ozga_joyda_tegilmaydi(text):
    assert nomli(text) == speak(text)


def test_lugatsiz_hech_narsa_ozgarmaydi():
    assert for_speech("DVSIB loyihasida", today=BUGUN) == "DVSIB loyihasida"
    assert for_speech("DVSIB loyihasida", today=BUGUN, names={}) == "DVSIB loyihasida"


def test_lugat_fayli(tmp_path):
    """Fayl yo'q - bo'sh; yaroqsiz yozuv tashlanadi; fayl o'zgarsa qayta
    o'qiladi; buzilsa oxirgi yaroqli nusxa qoladi (ovoz baribir ishlaydi)."""
    path = tmp_path / "tts_names.json"
    names = SpokenNames(path)
    assert names() == {}

    path.write_text(json.dumps({"DVSIB": "  Raqamli   bank ", "bad key": "x", "HR": "",
                                "N1": 5, "LONG": "y" * 201}), encoding="utf-8")
    assert names() == {"DVSIB": "Raqamli bank"}

    path.write_text(json.dumps({"DVSIB": "Raqamli bank", "HRM": "kadrlar tizimi"}), encoding="utf-8")
    assert names() == {"DVSIB": "Raqamli bank", "HRM": "kadrlar tizimi"}

    path.write_text("{buzuq json", encoding="utf-8")
    assert names() == {"DVSIB": "Raqamli bank", "HRM": "kadrlar tizimi"}

    path.write_text(json.dumps(["ro'yxat", "obyekt emas"]), encoding="utf-8")
    assert names() == {"DVSIB": "Raqamli bank", "HRM": "kadrlar tizimi"}

    path.unlink()
    assert names() == {}
