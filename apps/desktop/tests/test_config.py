"""Sozlamalar - noto'g'ri qiymat ilovani yiqitmasligi kerak."""

import textwrap

import pytest

from venera import config as config_module


def _write(tmp_path, body: str):
    path = tmp_path / "config.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_fayl_yoq_bolsa_defaultlar(tmp_path):
    cfg, warnings = config_module.load(tmp_path / "yoq.yaml")
    assert cfg.engines.stt == "mock"
    assert cfg.timeouts.capturing == 15.0
    assert any("topilmadi" in w for w in warnings)


def test_qisman_ustiga_qoyish(tmp_path):
    path = _write(tmp_path, """
        engines:
          tts: none
        timeouts:
          acting: 9.0
    """)
    cfg, warnings = config_module.load(path)
    assert cfg.engines.tts == "none"
    assert cfg.timeouts.acting == 9.0
    assert cfg.engines.stt == "mock"        # tegilmagan kalit default qoladi
    assert cfg.timeouts.capturing == 15.0
    assert warnings == []


def test_notogri_qiymatlar_tuzatiladi(tmp_path):
    path = _write(tmp_path, """
        audio:
          sample_rate: 12345
          channels: 2
          blocksize: 999999
        tts:
          rate: 99
          volume: -5
        timeouts:
          acting: -1
        logging:
          level: NOMALUM
        engines:
          stt: sehrli
    """)
    cfg, warnings = config_module.load(path)
    assert cfg.audio.sample_rate == 16000
    assert cfg.audio.channels == 1
    assert cfg.audio.blocksize == 512
    assert cfg.tts.rate == 0
    assert cfg.tts.volume == 100
    assert cfg.timeouts.acting == 5.0
    assert cfg.logging.level == "INFO"
    assert cfg.engines.stt == "mock"
    assert len(warnings) >= 8


def test_notanish_kalit_ogohlantiradi(tmp_path):
    path = _write(tmp_path, """
        engines:
          allaqanday: qiymat
    """)
    cfg, warnings = config_module.load(path)
    assert any("noma'lum kalit" in w for w in warnings)
    assert cfg.engines.stt == "mock"


def test_buzuq_yaml_yiqitmaydi(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("engines:\n  stt: [buzuq\n", encoding="utf-8")
    cfg, warnings = config_module.load(path)
    assert cfg.engines.stt == "mock"
    assert any("o'qilmadi" in w for w in warnings)


def test_search_url_query_siz_tuzatiladi(tmp_path):
    path = _write(tmp_path, """
        actions:
          search_url: "https://example.com/"
    """)
    cfg, warnings = config_module.load(path)
    assert "{query}" in cfg.actions.search_url
    assert any("search_url" in w for w in warnings)


def test_default_resurs_fayli_oqiladi():
    from venera import paths

    cfg, warnings = config_module.load(paths.resource("config.default.yaml"))
    assert warnings == [], warnings
    assert cfg.engines.stt == "mock"
    assert cfg.audio.sample_rate == 16000


# --- eski config'ni yangilash -------------------------------------------------

def test_upgrade_file_yangi_bolimlarni_qoshadi(tmp_path):
    """Eski kompyuterdagi config'da yangi bo'lim yo'q - u qo'shilishi kerak,
    aks holda yangilangan ilovaning yangi sozlamalari ko'rinmay qoladi."""
    path = _write(tmp_path, """
        engines:
          stt: mock
        logging:
          level: DEBUG
    """)
    added = config_module.upgrade_file(path)
    assert "update" in added

    cfg, warnings = config_module.load(path)
    assert cfg.logging.level == "DEBUG", "foydalanuvchi qiymati saqlanishi kerak"
    assert cfg.engines.stt == "mock"
    assert hasattr(cfg.update, "url")
    assert warnings == [], warnings


def test_upgrade_file_izohlarni_ham_kochiradi(tmp_path):
    path = _write(tmp_path, "engines:\n  stt: mock\n")
    config_module.upgrade_file(path)
    text = path.read_text(encoding="utf-8")
    assert "# Yangilanish manbasi" in text, "yangi bo'lim tushuntirishi bilan kelishi kerak"


def test_upgrade_file_zaxira_yaratadi(tmp_path):
    path = _write(tmp_path, "engines:\n  stt: mock\n")
    original = path.read_text(encoding="utf-8")
    config_module.upgrade_file(path)
    assert path.with_suffix(".yaml.bak").read_text(encoding="utf-8") == original


def test_upgrade_file_ikkinchi_marta_hech_narsa_qilmaydi(tmp_path):
    from venera import paths

    path = tmp_path / "config.yaml"
    path.write_text(paths.resource("config.default.yaml").read_text(encoding="utf-8"),
                    encoding="utf-8")
    assert config_module.upgrade_file(path) == []


def test_upgrade_file_yoq_fayl(tmp_path):
    assert config_module.upgrade_file(tmp_path / "yoq.yaml") == []


def test_upgrade_file_buzuq_yaml_tegmaydi(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("engines:\n  stt: [buzuq\n", encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    assert config_module.upgrade_file(path) == []
    assert path.read_text(encoding="utf-8") == before


# --- apps.yaml birlashtirish ---------------------------------------------------
# actions.apps.load() foydalanuvchi faylini topsa apps.default.yaml ni UMUMAN
# o'qimaydi, install_defaults() esa mavjud faylni o'tkazib yuboradi. Ikkalasi
# birga - yangilanishda qo'shilgan ovozli buyruq hech qachon ishlamasligini
# anglatadi. Quyidagi testlar aynan shu holatni qo'riqlaydi.

def _write_apps(tmp_path, body: str):
    path = tmp_path / "apps.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_upgrade_apps_yangi_dasturni_qoshadi(tmp_path):
    """Eski katalogda Claude yo'q - yangilangandan keyin paydo bo'lishi kerak."""
    path = _write_apps(tmp_path, """
        apps:
          - name: Google Chrome
            aliases: [chrome]
            windows: ["chrome.exe"]
            macos: ["Google Chrome"]
    """)
    added = config_module.upgrade_apps_file(path)
    assert "Claude" in added

    from venera.actions import apps as apps_module
    catalog = apps_module.load(path)
    assert catalog.find("claude")[0] is not None, "yangi buyruq ishlashi kerak"
    assert catalog.find("chrome")[0] is not None, "eski buyruq yo'qolmasligi kerak"


def test_upgrade_apps_foydalanuvchi_tahririga_tegmaydi(tmp_path):
    """Foydalanuvchi standart yozuvni o'zgartirgan bo'lsa, u saqlanishi shart."""
    path = _write_apps(tmp_path, """
        apps:
          - name: Google Chrome
            aliases: [mening brauzerim]
            windows: ["C:\\\\mening\\\\chrome.exe"]
            macos: ["Google Chrome"]
    """)
    config_module.upgrade_apps_file(path)

    from venera.actions import apps as apps_module
    catalog = apps_module.load(path)
    entry, _score = catalog.find("mening brauzerim")
    assert entry is not None and entry.name == "Google Chrome"
    assert path.read_text(encoding="utf-8").count("- name: Google Chrome") == 1


def test_upgrade_apps_zaxira_yaratadi(tmp_path):
    path = _write_apps(tmp_path, "apps:\n  - name: Google Chrome\n    windows: [\"chrome.exe\"]\n")
    original = path.read_text(encoding="utf-8")
    config_module.upgrade_apps_file(path)
    assert path.with_suffix(".yaml.bak").read_text(encoding="utf-8") == original


def test_upgrade_apps_ikkinchi_marta_hech_narsa_qilmaydi(tmp_path):
    path = _write_apps(tmp_path, "apps:\n  - name: Google Chrome\n    windows: [\"chrome.exe\"]\n")
    first = config_module.upgrade_apps_file(path)
    assert first
    assert config_module.upgrade_apps_file(path) == [], "takroriy yozuv qo'shilmasligi kerak"


def test_upgrade_apps_buzuq_fayl_yiqitmaydi(tmp_path):
    path = _write_apps(tmp_path, "apps: bu ro'yxat emas\n")
    assert config_module.upgrade_apps_file(path) == []


def test_upgrade_apps_yoq_fayl(tmp_path):
    assert config_module.upgrade_apps_file(tmp_path / "yoq.yaml") == []


# --- build skripti eski keshni qayta ishlatmasligi kerak -------------------------
# `build\` keshi eski bayt-kodni saqlab qolgani uchun 0.2.8 deb nomlangan
# o'rnatuvchi ichida 0.2.5 ilovasi ketdi. Bu jimgina sodir bo'ldi va faqat
# foydalanuvchi mashinasida bilindi.

def _build_script(name: str) -> str:
    from pathlib import Path
    return (Path(__file__).resolve().parents[1] / "packaging" / "windows" / name
            ).read_text(encoding="utf-8")


def test_build_tozalash_standart():
    text = _build_script("build.ps1")
    assert "$NoClean" in text, "tozalash standart bo'lishi kerak, -Clean bilan emas"
    assert "if (-not $NoClean)" in text


def test_build_yigilgan_exe_versiyasini_tekshiradi():
    """`$version` manbadan o'qiladi - u yig'ilgan fayl haqida hech narsa
    aytmaydi. .exe ning O'ZIDAN so'ralishi shart."""
    text = _build_script("build.ps1")
    assert "--version" in text, "yig'ilgan .exe versiyasi so'ralmayapti"
    assert "VERSIYA MOS KELMADI" in text, "mos kelmasa build to'xtashi kerak"


def test_setup_payload_versiyasini_tekshiradi():
    text = _build_script("build_setup.ps1")
    assert "PAYLOAD VERSIYASI MOS KELMADI" in text
