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
