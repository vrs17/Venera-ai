"""i18n yadrosi: kashf qilish, yuklash, fallback va nuqsonlarga chidamlilik.

Eng muhim tekshiruvlar:
  * buzuq YAML ILOVANI YIQITMAYDI (config.load() naqshi);
  * yetishmagan kalit zaxira tildan (uz) olinadi, xom kalit ekranga chiqmaydi;
  * `words.yaml` va `nlu/` dagi moslik nusxalari BIR XIL qoladi.
"""

import textwrap

import pytest
import yaml

from venera import i18n, paths
from venera.config import LANGUAGES
from venera.core.states import LABELS, State
from venera.i18n import locale as locale_module
from venera.i18n import pack as pack_module
from venera.i18n import script
from venera.i18n.registry import LocaleRegistry
from venera.nlu import normalize as normalize_module
from venera.nlu import numbers as numbers_module

UZ_DIR = paths.resource("i18n", "uz")


@pytest.fixture(autouse=True)
def faol_til_tiklanadi():
    """Har bir test tugagach faol til `uz` ga qaytadi - testlar bir-birini buzmasin."""
    oldingi = i18n.code()
    yield
    i18n.bind(oldingi)


# --- kashf qilish -----------------------------------------------------------


def test_uz_paketi_topiladi():
    assert "uz" in i18n.codes()


def test_etalon_til_birinchi_turadi():
    """Ro'yxatda `uz` birinchi - u manba til va fallback etaloni."""
    assert i18n.codes()[0] == "uz"


def test_kashf_qilish_qattiq_royxatga_bogliq_emas(tmp_path):
    """Yangi til = yangi papka. Kodda hech qanday ro'yxat o'zgartirilmaydi."""
    papka = tmp_path / "xx"
    papka.mkdir()
    (papka / "locale.yaml").write_text("code: xx\nname: Test tili\n", encoding="utf-8")

    registry = LocaleRegistry(roots=[tmp_path])
    assert registry.codes() == ("xx",)
    assert registry.spec("xx").display == "Test tili"


def test_locale_yaml_yoq_papka_e_tiborsiz(tmp_path):
    (tmp_path / "hujjatlar").mkdir()
    assert LocaleRegistry(roots=[tmp_path]).codes() == ()


def test_zh_uchun_paket_yoq_va_bu_aniq_koinadi():
    """zh STT shartnomasida bor, lekin til paketi ATAYLAB yozilmagan.

    Sabab: xitoyda so'z chegarasi yo'q, `\\b` va `\\s+` ishlamaydi,
    10^4/10^8 boshqa arifmetika. STT ishlaydi, interfeys zaxira tilga tushadi.
    """
    yoq = i18n.registry().missing(LANGUAGES)
    assert "zh" in yoq
    assert "uz" not in yoq


# --- paket mazmuni ----------------------------------------------------------


def test_uz_paketi_toliq():
    paket = i18n.active()
    assert paket.code == "uz"
    assert paket.ok
    assert paket.spec.complete is True
    assert len(paket.ui) >= 75, "ui.yaml da kutilganidan kam kalit bor"
    assert len(paket.phrases) >= 30
    assert len(paket.grammar.rules) == 20


def test_uz_paketida_muammo_yoq():
    assert i18n.active().problems == ()
    assert i18n.registry().problems == ()


def test_barcha_holat_nomlari_tarjima_qilingan():
    """`core.states.LABELS` dagi har bir holat `ui.yaml` da bo'lishi kerak."""
    for holat in State:
        kalit = f"state.{holat.value}"
        assert i18n.t(kalit) == LABELS[holat], kalit


def test_eski_phrases_fayldagi_hamma_kalit_kochirilgan():
    """`i18n/uz/phrases.yaml` eski `phrases.uz.yaml` ning ustiga qurilgan."""
    eski = yaml.safe_load(paths.resource("phrases.uz.yaml").read_text(encoding="utf-8"))
    yangi = i18n.active().phrases
    yetishmagan = sorted(set(eski) - set(yangi))
    assert yetishmagan == [], f"kalitlar yo'qolgan: {yetishmagan}"
    for kalit, qiymat in eski.items():
        assert yangi[kalit] == qiymat, kalit


# --- matn olish -------------------------------------------------------------


def test_t_matn_qaytaradi():
    assert i18n.t("window.button.submit") == "Bajarish"


def test_t_ichma_ich_kalitni_nuqta_bilan_tekislaydi():
    assert i18n.t("tray.error.unavailable", error="x") == "Tray ikonkasi mavjud emas: x"


def test_t_shablonni_toldiradi():
    assert i18n.t("tray.version", version="0.2.9") == "Versiya 0.2.9"


def test_yetishmagan_argument_ilovani_yiqitmaydi():
    """`{version}` berilmasa shablon xom holida qaytadi, exception yo'q."""
    assig = i18n.t("tray.version")
    assert "{version}" in assig


def test_notanish_kalit_kalitning_ozini_qaytaradi():
    assert i18n.t("bunday.kalit.yoq") == "bunday.kalit.yoq"


def test_notanish_kalit_missing_royxatiga_tushadi():
    i18n.t("yana.bir.yoq.kalit")
    assert "ui.yana.bir.yoq.kalit" in i18n.active().missing


def test_phrase_ishlaydi():
    assert i18n.phrase("open_app_ok", app="Chrome") == "Chrome ochilmoqda"


def test_raw_royxat_qaytaradi():
    kunlar = i18n.raw("phrases", "weekdays")
    assert isinstance(kunlar, list) and len(kunlar) == 7
    assert kunlar[0] == "Dushanba"


# --- fallback ---------------------------------------------------------------


def test_paketi_yoq_tilda_matn_uz_dan_olinadi():
    """Foydalanuvchi ruschani tanladi, lekin paket hali yozilmagan."""
    paket = i18n.bind("ru")
    assert i18n.code() == "ru"
    assert i18n.t("window.button.submit") == "Bajarish"   # uz dan
    assert not paket.ok
    assert any("topilmadi" in p for p in i18n.problems())


def test_paketi_yoq_tilda_stt_kodi_ozgarmaydi():
    """Interfeys uz ga tushsa ham, STT foydalanuvchi tanlagan tilda ishlaydi."""
    i18n.bind("ru")
    assert i18n.stt_code() == "ru"


def test_paketi_yoq_tilda_buyruq_baribir_taniladi():
    """Qoidalar zaxira tildan olinadi - foydalanuvchi buyruqsiz qolmasin."""
    from venera.nlu.intents import IntentName
    from venera.nlu.rules import parse

    i18n.bind("ru")
    assert parse("chrome och").name is IntentName.OPEN_APP


def test_bosh_til_kodi_etalonga_qaytadi():
    i18n.bind("")
    assert i18n.code() == "uz"


def test_uz_ozini_ozicha_zaxira_qilmaydi():
    """Cheksiz halqa bo'lmasligi uchun etalon tilning fallback'i bo'sh."""
    assert i18n.active().fallback is None
    assert i18n.active().spec.fallback == ""


# --- nuqsonlarga chidamlilik ------------------------------------------------


def test_buzuq_yaml_exception_tashlamaydi(tmp_path):
    papka = tmp_path / "yy"
    papka.mkdir()
    (papka / "locale.yaml").write_text("code: yy\nname: Yomon\n", encoding="utf-8")
    (papka / "ui.yaml").write_text("bu: [ochilmagan qavs\n", encoding="utf-8")
    (papka / "rules.yaml").write_text("rules: {bu: royxat emas}\n", encoding="utf-8")

    paket = LocaleRegistry(roots=[tmp_path]).load("yy")
    assert paket.code == "yy"
    assert paket.problems, "muammolar ro'yxati bo'sh bo'lmasligi kerak"
    assert paket.text("nima") == "nima"     # yiqilmadi


def test_buzuq_naqsh_faqat_ozini_ochiradi(tmp_path):
    papka = tmp_path / "zz"
    papka.mkdir()
    (papka / "locale.yaml").write_text("code: zz\n", encoding="utf-8")
    (papka / "rules.yaml").write_text(textwrap.dedent("""
        rules:
          - intent: cancel
            patterns:
              - "((("
          - intent: help
            patterns:
              - "yordam"
    """), encoding="utf-8")

    paket = LocaleRegistry(roots=[tmp_path]).load("zz")
    nomlar = [r.name for r in paket.grammar.rules]
    assert nomlar == ["help"], "buzuq qoida o'chirilib, sog'i qolishi kerak"


def test_yoq_papka_bosh_paket_beradi(tmp_path):
    paket = LocaleRegistry(roots=[tmp_path]).load("qq")
    assert paket.code == "qq"
    assert paket.ui == {}
    assert paket.text("kalit") == "kalit"


def test_locale_parse_hech_qachon_yiqilmaydi():
    for yomon in (None, "matn", 42, [], {"code": 5}, {"script": "yozuv-yo'q"}):
        spec, muammolar = locale_module.parse("tt", yomon)
        assert spec.code == "tt"
        assert isinstance(muammolar, list)


def test_papka_nomi_locale_yaml_dagi_koddan_ustun(tmp_path):
    papka = tmp_path / "aa"
    papka.mkdir()
    (papka / "locale.yaml").write_text("code: bb\n", encoding="utf-8")
    registry = LocaleRegistry(roots=[tmp_path])
    assert registry.codes() == ("aa",)
    assert any("mos emas" in p for p in registry.problems)


def test_foydalanuvchi_papkasi_ustun(tmp_path):
    """`config_dir()/i18n` paket ichidagi tarjimani almashtira oladi."""
    for nom in ("foydalanuvchi", "paket"):
        papka = tmp_path / nom / "cc"
        papka.mkdir(parents=True)
        (papka / "locale.yaml").write_text(f"code: cc\nname: {nom}\n", encoding="utf-8")

    registry = LocaleRegistry(roots=[tmp_path / "foydalanuvchi", tmp_path / "paket"])
    assert registry.spec("cc").name == "foydalanuvchi"


def test_read_yaml_yoq_faylni_kechiradi(tmp_path):
    data, xato = pack_module.read_yaml(tmp_path / "yoq.yaml")
    assert data is None and xato == ""


# --- moslik nusxalari drift qilmasin ---------------------------------------
#
# `normalize.py` va `numbers.py` ichida o'zbekcha ro'yxatlarning nusxasi bor
# (eski `normalize()` / `words_to_int()` funksiyalari uchun). Asosiy manba -
# `uz/words.yaml`. Quyidagi testlar ikkalasi ajralib ketmasligini kafolatlaydi.

def _uz_words():
    return yaml.safe_load((UZ_DIR / "words.yaml").read_text(encoding="utf-8"))


def test_fillers_nusxasi_bir_xil():
    assert tuple(_uz_words()["fillers"]) == normalize_module._FILLERS


def test_suffixes_nusxasi_bir_xil():
    assert tuple(_uz_words()["suffixes"]) == normalize_module._SUFFIXES


@pytest.mark.parametrize("bolim,jadval", [
    ("units", numbers_module.UNITS),
    ("tens", numbers_module.TENS),
    ("scales", numbers_module.SCALES),
])
def test_son_jadvallari_nusxasi_bir_xil(bolim, jadval):
    assert _uz_words()["numbers"][bolim] == jadval


def test_words_book_faol_tildan_keladi():
    kitob = i18n.words()
    assert kitob.code == "uz"
    assert kitob.number("qirq besh") == 45
    assert kitob.strip_affixes("google chrome ni") == "google chrome"
    assert kitob.normalize("Chromeni ochib ber, iltimos!") == "chromeni ochib ber"


# --- transliteratsiya -------------------------------------------------------


@pytest.mark.parametrize("lotin,kirill", [
    ("salom", "салом"),
    ("o'zbek", "ўзбек"),
    ("g'alaba", "ғалаба"),
    ("shahar", "шаҳар"),
    ("chiroq", "чироқ"),
])
def test_lotindan_kirillga(lotin, kirill):
    assert script.to_cyrillic(lotin) == kirill


@pytest.mark.parametrize("kirill,lotin", [
    ("салом", "salom"),
    ("ўзбек", "o'zbek"),
    ("ғалаба", "g'alaba"),
])
def test_kirilldan_lotinga(kirill, lotin):
    assert script.to_latin(kirill) == lotin


def test_bosh_harf_saqlanadi():
    assert script.to_cyrillic("Salom") == "Салом"


def test_yozuv_aniqlanadi():
    assert script.detect("salom") == "latin"
    assert script.detect("салом") == "cyrillic"
    assert script.detect("12345") == "other"
    assert script.detect("") == "other"


def test_to_script_ikki_marta_ogirmaydi():
    kirill = script.to_cyrillic("salom")
    assert script.to_script(kirill, "cyrillic") == kirill


# --- ommaviy API ------------------------------------------------------------


def test_describe_check_uchun_malumot_beradi():
    malumot = i18n.describe()
    for kalit in ("code", "name", "ui_keys", "rules", "problems", "available"):
        assert kalit in malumot


def test_names_uz_nomini_oz_tilida_beradi():
    assert i18n.names()["uz"] == "O'zbekcha"


def test_active_hech_qachon_none_emas():
    assert i18n.active() is not None
    assert i18n.grammar() is not None
    assert i18n.words() is not None
