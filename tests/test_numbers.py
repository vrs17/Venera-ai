import pytest

from venera.nlu.numbers import contains_number, words_to_int


@pytest.mark.parametrize("text,expected", [
    ("nol", 0),
    ("besh", 5),
    ("o'n", 10),
    ("o'n besh", 15),
    ("yigirma", 20),
    ("qirq besh", 45),
    ("ellik", 50),
    ("to'qson to'qqiz", 99),
    ("yuz", 100),
    ("ikki yuz ellik", 250),
    ("ming", 1000),
    ("sakkiz yuz o'n olti ming", 816000),
    ("bir million", 1_000_000),
])
def test_sozlardan_son(text, expected):
    assert words_to_int(text) == expected


@pytest.mark.parametrize("text,expected", [("45", 45), ("ovozni 30 foiz", 30), ("100", 100)])
def test_raqamlar_ustun(text, expected):
    assert words_to_int(text) == expected


@pytest.mark.parametrize("text", ["salom", "", "chromeni och", None])
def test_son_yoq(text):
    assert words_to_int(text) is None
    assert not contains_number(text or "")
