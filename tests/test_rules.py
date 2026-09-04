"""Buyruq -> intent jadvali. Bu testlar Step 3 da LLM qo'shilganda ham amal qiladi."""

import pytest

from venera.nlu.intents import IntentName
from venera.nlu.rules import parse

CASES = [
    ("chrome och", IntentName.OPEN_APP),
    ("chromeni ochib ber", IntentName.OPEN_APP),
    ("xromni ishga tushir", IntentName.OPEN_APP),
    ("och telegram", IntentName.OPEN_APP),
    ("microsoft excel ni ishga tushir", IntentName.OPEN_APP),
    ("ovozni ko'tar", IntentName.VOLUME_UP),
    ("ovozni kuchaytir", IntentName.VOLUME_UP),
    ("tovushni pasaytir", IntentName.VOLUME_DOWN),
    ("ovozni kamaytir", IntentName.VOLUME_DOWN),
    ("ovozni o'chir", IntentName.MUTE),
    ("ovozni yoq", IntentName.UNMUTE),
    ("ovozni qirq besh foiz", IntentName.VOLUME_SET),
    ("ovozni 30 ga qo'y", IntentName.VOLUME_SET),
    ("ekranni qulfla", IntentName.LOCK_SCREEN),
    ("kompyuterni qulfla", IntentName.LOCK_SCREEN),
    ("skrinshot ol", IntentName.SCREENSHOT),
    ("ekranni rasmga ol", IntentName.SCREENSHOT),
    ("soat necha", IntentName.TIME),
    ("hozir soat necha", IntentName.TIME),
    ("bugun qaysi kun", IntentName.DATE),
    ("bugungi sana", IntentName.DATE),
    ("googlda venera bank qidir", IntentName.WEB_SEARCH),
    ("internetdan valyuta kursi izla", IntentName.WEB_SEARCH),
    ("venera.uz saytini och", IntentName.OPEN_URL),
    ("https://google.com ni och", IntentName.OPEN_URL),
    ("to'xta", IntentName.CANCEL),
    ("bekor qil", IntentName.CANCEL),
    ("yana ayt", IntentName.REPEAT),
    ("nima qila olasan", IntentName.HELP),
    ("bugun ob-havo qandayligini bilmoqchiman", IntentName.UNKNOWN),
]


@pytest.mark.parametrize("text,expected", CASES)
def test_intent_aniqlanadi(text, expected):
    assert parse(text).name is expected, f"{text!r} -> {parse(text).describe()}"


def test_qamrov_kamida_90_foiz():
    """Ma'lum buyruqlarning kamida 90 foizi tanilishi kerak."""
    known = [c for c in CASES if c[1] is not IntentName.UNKNOWN]
    ok = sum(1 for text, expected in known if parse(text).name is expected)
    assert ok / len(known) >= 0.9


@pytest.mark.parametrize("text,level", [
    ("ovozni qirq besh foiz", 45),
    ("ovozni 30 ga qo'y", 30),
    ("ovozni 70", 70),
])
def test_ovoz_darajasi(text, level):
    assert parse(text).level == level


def test_daraja_chegaralanadi():
    assert 0 <= parse("ovozni 500 ga qo'y").level <= 100


@pytest.mark.parametrize("text,app", [
    ("chromeni och", "chrome"),
    ("google chrome ni och", "google chrome"),
    ("telegramni ishga tushir", "telegram"),
])
def test_dastur_nomi_tozalanadi(text, app):
    assert parse(text).app == app


def test_bosh_matn():
    assert parse("").name is IntentName.UNKNOWN
    assert parse("   ").name is IntentName.UNKNOWN


@pytest.mark.parametrize("text", ["versiya qanday", "qaysi versiya", "versiyang nechada"])
def test_versiya_intenti(text):
    assert parse(text).name is IntentName.VERSION
