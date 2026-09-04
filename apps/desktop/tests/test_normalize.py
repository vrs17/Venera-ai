import pytest

from venera.nlu.normalize import normalize, strip_suffix, unify_apostrophes


@pytest.mark.parametrize("raw,expected", [
    ("Chromeni ochib ber, iltimos!", "chromeni ochib ber"),
    ("Ekranni qulfla.", "ekranni qulfla"),
    ("soat necha???", "soat necha"),
    ("   ko'p    bo'sh   joy  ", "ko'p bo'sh joy"),
    ("", ""),
])
def test_normalize(raw, expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize("raw", ["o‘chir", "oʻchir", "o’chir", "o`chir", "o'chir"])
def test_apostrof_variantlari_bir_xil_bo_ladi(raw):
    """STT va foydalanuvchi turli apostrof belgilarini ishlatadi - hammasi bir xil bo'lishi shart."""
    assert normalize(raw) == "o'chir"


def test_apostrof_ochirilmaydi():
    """Apostrof harf tarkibiga kiradi: "o'chir" (mute) != "ochir"."""
    assert "'" in normalize("ovozni o'chir")


def test_domen_ichidagi_nuqta_saqlanadi():
    assert normalize("google.com ni och") == "google.com ni och"
    assert normalize("venera.uz saytini och") == "venera.uz saytini och"


def test_unify_apostrophes_faqat_apostrofga_tegadi():
    assert unify_apostrophes("To‘xta") == "To'xta"


@pytest.mark.parametrize("word,expected", [
    ("chromeni", "chrome"),
    ("telegramni", "telegram"),
    ("excel", "excel"),
    ("ni", "ni"),
])
def test_strip_suffix(word, expected):
    assert strip_suffix(word) == expected
