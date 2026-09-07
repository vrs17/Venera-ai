"""i18n HAQIQATAN ulanganmi: kalitlar mavjudmi va til almashsa matn o'zgaradimi.

0.2.9 gacha `i18n/` paketi 905 qator edi va `ui.yaml` da to'liq tarjima turardi,
lekin uni HECH KIM o'qimasdi: oyna, tray va javob iboralari qattiq yozilgan
o'zbekcha matn ishlatardi. Bu fayl aynan shu holatning qaytishini to'sadi.
"""

import re
from pathlib import Path

import pytest

from venera import i18n
from venera.actions import phrases as phrases_module
from venera.core.states import LABELS, State, label

SRC = Path(__file__).resolve().parents[1] / "src" / "venera"

#: `i18n.t("...")` va `i18n.phrase("...")` dagi TO'G'RIDAN-TO'G'RI kalitlar.
#: f-string bilan yasalganlar (masalan `state.{...}`) bu yerga tushmaydi -
#: ular `test_i18n.py` da alohida tekshiriladi.
CALL = re.compile(r'i18n\.(t|phrase)\(\s*"([a-z][a-z0-9_.]*)"', re.IGNORECASE)


def used_keys() -> dict[str, list[str]]:
    """Kod bo'ylab ishlatilgan kalitlar: {"t": [...], "phrase": [...]}."""
    found: dict[str, list[str]] = {"t": [], "phrase": []}
    for path in SRC.rglob("*.py"):
        if path.parts[-2:] == ("venera", "i18n") or "i18n" in path.parts[-2:-1]:
            continue  # paketning O'ZIDAGI docstring namunalari hisobga olinmaydi
        for kind, key in CALL.findall(path.read_text(encoding="utf-8")):
            found[kind].append(key)
    return found


@pytest.fixture(autouse=True)
def uz():
    """Har test o'zbekchadan boshlansin - global `_active` sizib ketmasin."""
    i18n.bind("uz")
    yield
    i18n.bind("uz")


# --- kalitlar mavjudmi ------------------------------------------------------

def test_kodda_ishlatilgan_kalitlar_topildi():
    keys = used_keys()
    assert len(keys["t"]) >= 15, f"i18n.t() deyarli ishlatilmayapti: {keys['t']}"


def test_har_bir_ui_kaliti_paketda_bor():
    """Kalit topilmasa `i18n.t()` KALITNING O'ZINI qaytaradi - ya'ni
    foydalanuvchi ekranda "window.button.submit" degan yozuvni ko'rardi."""
    yetishmagan = [k for k in set(used_keys()["t"]) if i18n.t(k) == k]
    assert not yetishmagan, f"ui.yaml da yo'q kalitlar: {sorted(yetishmagan)}"


def test_har_bir_ibora_kaliti_paketda_bor():
    yetishmagan = [k for k in set(used_keys()["phrase"]) if i18n.phrase(k) == k]
    assert not yetishmagan, f"phrases.yaml da yo'q kalitlar: {sorted(yetishmagan)}"


def test_oyna_va_tray_kalitlarini_ishlatadi():
    """Aniq nazorat: bu ikki modul til paketiga ULANGAN bo'lishi shart."""
    for modul in ("ui/window.py", "ui/tray.py"):
        matn = (SRC / modul).read_text(encoding="utf-8")
        assert "i18n.t(" in matn, f"{modul} hali qattiq yozilgan matnda"


# --- holat nomlari ----------------------------------------------------------

def test_holat_nomi_paketdan_keladi():
    for holat in State:
        assert label(holat) == i18n.t(f"state.{holat.value}")


def test_holat_nomi_zaxira_jadval_bilan_mos():
    """`ui.yaml` va `LABELS` ajralib ketmasin - ikkisi ham foydalanuvchiga
    ko'rinadi (paket yuklanmasa LABELS ishlaydi)."""
    for holat, matn in LABELS.items():
        assert label(holat) == matn


# --- javob iboralari --------------------------------------------------------

def test_phrases_til_paketiga_ulangan():
    p = phrases_module.Phrases.load()
    assert isinstance(p, phrases_module._PackPhrases), \
        "javob iboralari hali eski phrases.uz.yaml dan o'qilyapti"


def test_phrases_paketdan_togri_matn_beradi():
    p = phrases_module.Phrases.load()
    assert p.get("unknown") == i18n.phrase("unknown")
    assert p.get("open_app_ok", app="Chrome") == "Chrome ochilmoqda"


def test_phrases_hafta_va_oy_nomlarini_beradi():
    from datetime import datetime

    p = phrases_module.Phrases.load()
    moment = datetime(2026, 9, 7)          # dushanba
    assert p.weekday(moment) == "Dushanba"
    assert p.month(moment) == "sentabr"
    assert p.format_date(moment) == "Dushanba, 7-sentabr 2026-yil"


def test_eski_fayl_va_paket_ajralib_ketmagan():
    """`Phrases` endi paketdan o'qiydi. Eski `phrases.uz.yaml` hali ham
    zaxira yo'l sifatida turibdi - ikkisi farq qilsa, zaxiraga tushgan
    foydalanuvchi BOSHQACHA javob eshitardi."""
    import yaml

    eski = yaml.safe_load((SRC / "resources" / "phrases.uz.yaml").read_text(encoding="utf-8"))
    yangi = yaml.safe_load(
        (SRC / "resources" / "i18n" / "uz" / "phrases.yaml").read_text(encoding="utf-8"))
    farq = sorted(k for k in set(eski) | set(yangi) if eski.get(k) != yangi.get(k))
    assert not farq, f"ikki manba ajralib ketdi: {farq}"


def test_aniq_fayl_berilsa_eski_yol_saqlanadi(tmp_path):
    """Testlar va zaxira yo'l: aniq YAML berilsa paket chetlab o'tiladi."""
    target = tmp_path / "p.yaml"
    target.write_text('unknown: "boshqacha"\n', encoding="utf-8")
    p = phrases_module.Phrases.load(target)
    assert not isinstance(p, phrases_module._PackPhrases)
    assert p.get("unknown") == "boshqacha"


def test_paket_bosh_bolsa_ilova_gapirishda_davom_etadi():
    """`_PackPhrases` kalitni topolmasa xom kalitni emas, zaxira matnni beradi."""
    p = phrases_module._PackPhrases()
    assert p.get("action_failed") != "action_failed"


# --- til almashishi ---------------------------------------------------------

def test_stt_kodi_serverga_yaroqli():
    from venera.engines.stt_onprem import LANGUAGES

    for kod in i18n.codes():
        i18n.bind(kod)
        assert i18n.stt_code() in LANGUAGES, f"{kod}: server bu kodni rad etadi"


def test_paketi_yoq_til_zaxiraga_tushadi():
    """`ru` paketi hali yozilmagan: interfeys uzbekchada qolishi, ilova esa
    yiqilmasligi kerak."""
    pack = i18n.bind("ru")
    assert pack is not None
    assert i18n.t("window.button.submit") == "Bajarish", "zaxira til ishlamadi"
