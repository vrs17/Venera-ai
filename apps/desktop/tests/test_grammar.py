"""Deklarativ slot-grammatika dvigateli.

Bu yerda TILDAN QAT'I NAZAR ishlashi kerak bo'lgan xatti-harakat tekshiriladi:
tartib, slotlar, makrolar, xatolarga chidamlilik. O'zbekcha buyruqlar jadvali
esa `test_rules.py` da - u regressiya yo'qligining isboti.
"""

import pytest
import yaml

from venera import paths
from venera.nlu import grammar as grammar_module
from venera.nlu import transforms, words
from venera.nlu.grammar import SlotSpec
from venera.nlu.intents import IntentName

UZ_DIR = paths.resource("i18n", "uz")


def _kitob(**qoshimcha):
    """Kichik sinov so'zligi."""
    malumot = {
        "fillers": ["iltimos"],
        "suffixes": ["ni", "ga"],
        "particles": ["ni", "ga"],
        "wake_prefixes": ["venera"],
        "macros": {"num": r"(?:\d+|[a-z'\s]+?)"},
        "numbers": {
            "parser": "decimal_words",
            "units": {"bir": 1, "besh": 5},
            "tens": {"qirq": 40},
            "scales": {"yuz": 100, "ming": 1000},
        },
    }
    malumot.update(qoshimcha)
    kitob, muammolar = words.from_data("tt", malumot)
    assert muammolar == []
    return kitob


def _grammatika(qoidalar, kitob=None, **qoshimcha):
    malumot = {"rules": qoidalar}
    malumot.update(qoshimcha)
    return grammar_module.compile(malumot, kitob or _kitob(), "tt")


# --- asosiy ishlash ---------------------------------------------------------


def test_oddiy_qoida_mos_keladi():
    g = _grammatika([{"intent": "cancel", "patterns": [r"^to'xta\b"]}])
    assert g.match("to'xta").name is IntentName.CANCEL


def test_mos_kelmasa_unknown():
    g = _grammatika([{"intent": "cancel", "patterns": [r"^to'xta\b"]}])
    assert g.match("salom dunyo").name is IntentName.UNKNOWN


def test_bosh_matn_unknown():
    g = _grammatika([{"intent": "cancel", "patterns": ["."]}])
    assert g.match("").name is IntentName.UNKNOWN
    assert g.match("   ").name is IntentName.UNKNOWN


def test_matn_normalizatsiyadan_otadi():
    """Naqshga tozalangan matn keladi: kichik harf, yagona apostrof, filler'siz."""
    g = _grammatika([{"intent": "cancel", "patterns": [r"^to'xta$"]}])
    assert g.match("To‘xta, iltimos!").name is IntentName.CANCEL


def test_raw_text_tozalangan_matn():
    g = _grammatika([{"intent": "cancel", "patterns": ["to'xta"]}])
    assert g.match("  To'xta!  ").raw_text == "to'xta"


def test_source_har_doim_rules():
    g = _grammatika([{"intent": "cancel", "patterns": ["to'xta"]}])
    assert g.match("to'xta").source == "rules"


# --- tartib -----------------------------------------------------------------


def test_birinchi_mos_kelgan_qoida_yutadi():
    g = _grammatika([
        {"name": "aniq", "intent": "mute", "patterns": ["ovozni o'chir"]},
        {"name": "umumiy", "intent": "volume_down", "patterns": ["ovoz"]},
    ])
    assert g.match("ovozni o'chir").name is IntentName.MUTE


def test_teskari_tartibda_umumiy_qoida_yeb_qoyadi():
    """TARTIB MUHIM ekanining isboti - shuning uchun rules.yaml da tartib qat'iy."""
    g = _grammatika([
        {"name": "umumiy", "intent": "volume_down", "patterns": ["ovoz"]},
        {"name": "aniq", "intent": "mute", "patterns": ["ovozni o'chir"]},
    ])
    assert g.match("ovozni o'chir").name is IntentName.VOLUME_DOWN


def test_qoidalar_tartibi_yaml_dagidek_saqlanadi():
    g = _grammatika([
        {"name": "a", "intent": "help", "patterns": ["a"]},
        {"name": "b", "intent": "time", "patterns": ["b"]},
        {"name": "c", "intent": "date", "patterns": ["c"]},
    ])
    assert [r.name for r in g.rules] == ["a", "b", "c"]
    assert [r.order for r in g.rules] == [0, 1, 2]


# --- slotlar ----------------------------------------------------------------


def test_slot_intent_maydoniga_yoziladi():
    g = _grammatika([{
        "intent": "open_app",
        "slots": {"app": {"transform": "strip_affixes"}},
        "patterns": [r"^(?P<app>.+?)\s+och$"],
    }])
    assert g.match("chromeni och").app == "chrome"


def test_qisqa_yozuv_transform_nomi_bilan():
    """`app: strip_affixes` - mapping o'rniga to'g'ridan-to'g'ri nom."""
    g = _grammatika([{
        "intent": "open_app",
        "slots": {"app": "strip_affixes"},
        "patterns": [r"^(?P<app>.+?)\s+och$"],
    }])
    assert g.match("telegramni och").app == "telegram"


def test_number_transform_sozdan_son_ajratadi():
    g = _grammatika([{
        "intent": "volume_set",
        "slots": {"level": {"transform": "number"}},
        "patterns": [r"^ovoz (?P<level>.+)$"],
    }])
    assert g.match("ovoz qirq besh").level == 45


def test_clamp_chegaralaydi():
    g = _grammatika([{
        "intent": "volume_set",
        "slots": {"level": {"transform": "number", "clamp": [0, 100]}},
        "patterns": [r"^ovoz (?P<level>.+)$"],
    }])
    assert g.match("ovoz 500").level == 100
    assert g.match("ovoz bir ming").level == 100


def test_required_slot_chiqmasa_keyingi_qoidaga_otiladi():
    """`_volume_set` ning eski xatti-harakati: son yo'q -> boshqa qoida."""
    g = _grammatika([
        {"name": "set", "intent": "volume_set",
         "slots": {"level": {"transform": "number", "required": True}},
         "patterns": [r"^ovozni (?P<level>.+)$"]},
        {"name": "up", "intent": "volume_up", "patterns": ["ovozni ko'tar"]},
    ])
    assert g.match("ovozni 30").name is IntentName.VOLUME_SET
    assert g.match("ovozni ko'tar").name is IntentName.VOLUME_UP


def test_required_bolmasa_default_qiymat_qoladi():
    g = _grammatika([{
        "intent": "volume_set",
        "slots": {"level": {"transform": "number", "default": 7}},
        "patterns": [r"^ovozni (?P<level>.*)$"],
    }])
    assert g.match("ovozni salom").level == 7


def test_slot_intent_maydoni_bolmasa_otkazib_yuboriladi():
    g = _grammatika([{
        "intent": "open_app",
        "slots": {"bunday_maydon_yoq": {}},
        "patterns": [r"^(?P<bunday_maydon_yoq>.+) och$"],
    }])
    assert any("Intent maydoni emas" in p for p in g.problems)
    assert g.match("chrome och").name is IntentName.OPEN_APP


def test_elon_qilinmagan_guruh_ogohlantiradi():
    g = _grammatika([{
        "intent": "open_app",
        "patterns": [r"^(?P<app>.+) och$"],
    }])
    assert any("e'lon qilinmagan" in p for p in g.problems)


# --- makrolar ---------------------------------------------------------------


def test_makro_almashtiriladi():
    kitob = _kitob()
    assert kitob.expand("(?P<level>{num})") == r"(?P<level>(?:\d+|[a-z'\s]+?))"


def test_kvantifikator_makro_deb_qabul_qilinmaydi():
    """`str.format` ISHLATILMAYDI: `{2,3}` KeyError berardi."""
    kitob = _kitob()
    assert kitob.expand(r"a{2,3}b") == r"a{2,3}b"
    assert kitob.expand(r"\d{4}") == r"\d{4}"


def test_notanish_makro_oz_holicha_qoladi_va_ogohlantiradi():
    g = _grammatika([{"intent": "help", "patterns": ["{bunday_makro_yoq}"]}])
    assert any("noma'lum makro" in p for p in g.problems)


def test_makro_bilan_qoida_ishlaydi():
    g = _grammatika([{
        "intent": "volume_set",
        "slots": {"level": {"transform": "number", "required": True}},
        "patterns": [r"^ovozni (?P<level>{num})\s*foiz$"],
    }])
    assert g.match("ovozni qirq besh foiz").level == 45
    assert g.match("ovozni 20 foiz").level == 20


# --- uyg'otish so'zi --------------------------------------------------------


def test_wake_prefix_kesiladi():
    g = _grammatika([{"intent": "cancel", "patterns": [r"^to'xta$"]}], strip_wake=True)
    assert g.match("venera to'xta").name is IntentName.CANCEL


def test_wake_prefix_ochirilgan_bolsa_kesilmaydi():
    g = _grammatika([{"intent": "cancel", "patterns": [r"^to'xta$"]}], strip_wake=False)
    assert g.match("venera to'xta").name is IntentName.UNKNOWN


def test_yolgiz_qolgan_wake_soz_kesilmaydi():
    """"venerani och" - dastur nomi bo'lishi mumkin, uni yo'q qilib bo'lmaydi."""
    kitob = _kitob()
    assert kitob.strip_wake("venera") == "venera"
    assert kitob.strip_wake("venera to'xta") == "to'xta"


# --- xatolarga chidamlilik --------------------------------------------------


def test_buzuq_regex_faqat_ozini_ochiradi():
    g = _grammatika([
        {"name": "buzuq", "intent": "cancel", "patterns": ["((("]},
        {"name": "sog", "intent": "help", "patterns": ["yordam"]},
    ])
    assert [r.name for r in g.rules] == ["sog"]
    assert any("regex xatosi" in p for p in g.problems)


def test_notanish_intent_qoidani_ochiradi():
    g = _grammatika([{"intent": "bunday_intent_yoq", "patterns": ["a"]}])
    assert g.rules == ()
    assert any("noma'lum" in p for p in g.problems)


def test_unknown_intent_taqiqlanadi():
    g = _grammatika([{"intent": "unknown", "patterns": ["a"]}])
    assert g.rules == ()


def test_notanish_transform_text_ga_qaytadi():
    g = _grammatika([{
        "intent": "open_app",
        "slots": {"app": {"transform": "bunday_transform_yoq"}},
        "patterns": [r"^(?P<app>.+) och$"],
    }])
    assert any("noma'lum" in p for p in g.problems)
    assert g.match("chrome och").app == "chrome"


@pytest.mark.parametrize("yomon", [None, "matn", 42, [], {"rules": "royxat emas"}])
def test_buzuq_malumot_exception_tashlamaydi(yomon):
    g = grammar_module.compile(yomon, _kitob(), "tt")
    assert g.match("nimadir").name is IntentName.UNKNOWN


def test_bosh_grammatika_ishlaydi():
    g = grammar_module.empty("tt")
    assert g.rules == ()
    assert g.match("chrome och").name is IntentName.UNKNOWN


def test_naqshsiz_qoida_otkazib_yuboriladi():
    g = _grammatika([{"intent": "help"}])
    assert g.rules == ()


# --- transformatsiyalar registri --------------------------------------------


def test_asosiy_transformatsiyalar_royxatdan_otgan():
    for nom in ("text", "lower", "number", "strip_affixes", "strip_suffix", "url"):
        assert nom in transforms.TRANSFORMS, nom


def test_transform_royxatdan_otkazish():
    @transforms.register("sinov_teskari")
    def _teskari(raw, book, slot):  # noqa: ARG001
        return raw[::-1]

    try:
        assert transforms.get("sinov_teskari")("abc", _kitob(), None) == "cba"
    finally:
        transforms.TRANSFORMS.pop("sinov_teskari", None)


def test_url_transform_bosh_qiymatda_none():
    assert transforms.get("url")("  ", _kitob(), None) is None


def test_strip_affixes_alohida_yuklamani_tashlaydi():
    kitob = _kitob()
    assert kitob.strip_affixes("google chrome ni") == "google chrome"
    assert kitob.strip_affixes("ni") == "ni"     # yolg'iz qolsa tegilmaydi


def test_slotspec_default_qiymatlari():
    slot = SlotSpec(name="app")
    assert slot.transform == "text"
    assert slot.required is False
    assert slot.clamp is None


# --- haqiqiy uz paketi ------------------------------------------------------


def test_uz_rules_yaml_tartibi_kompilyatsiyada_saqlanadi():
    xom = yaml.safe_load((UZ_DIR / "rules.yaml").read_text(encoding="utf-8"))
    kutilgan = [q.get("name") or q["intent"] for q in xom["rules"]]

    kitob, _ = words.from_data(
        "uz", yaml.safe_load((UZ_DIR / "words.yaml").read_text(encoding="utf-8")))
    g = grammar_module.compile(xom, kitob, "uz")

    assert [r.name for r in g.rules] == kutilgan
    assert g.problems == ()


def test_uz_grammatikasi_barcha_intentlarni_qamraydi():
    """UNKNOWN dan tashqari har bir intent uchun kamida bitta qoida bo'lishi kerak."""
    from venera import i18n

    qamralgan = set(i18n.grammar().intents())
    kutilgan = {i for i in IntentName if i is not IntentName.UNKNOWN}
    assert kutilgan - qamralgan == set()


def test_umumiy_qoidalar_oxirida_turadi():
    """`open_app` eng umumiy qoida - u ro'yxatning oxirida bo'lishi SHART."""
    from venera import i18n

    nomlar = [r.name for r in i18n.grammar().rules]
    assert nomlar[-2:] == ["open_app", "open_app_rev"]
    assert nomlar.index("volume_set") < nomlar.index("volume_up")
    assert nomlar.index("search") < nomlar.index("open_app")
