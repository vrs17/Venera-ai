"""Foydalanuvchilar faylini qo'lda tahrirlashdan kelib chiqadigan xatolar.

Bularning hammasi JONLI tizimda bo'lgan yoki bo'lishi mumkin bo'lgan holatlar,
va hammasining umumiy belgisi bitta: ular JIMGINA sodir bo'ladi. Fayl to'g'ri
ko'rinadi, xizmat ko'tariladi, va muammo faqat kimdir kira olmay qolganda yoki
kimdir ortiqcha huquq olganda bilinadi.
"""

from __future__ import annotations

import yaml

from app.services.users import UserStore, example_password_hashes


def _write(tmp_path, users):
    path = tmp_path / "users.yaml"
    path.write_text(yaml.safe_dump({"users": users}), encoding="utf-8")
    return path


BASE = {
    "actor_id": 1,
    "email": "admin@venera.uz",
    "full_name": "Administrator",
    "roles": ["ADMIN"],
    "password_hash": "pbkdf2$600000$abc$def",
}


def test_xato_actor_id_butun_omborni_yiqitmaydi(tmp_path):
    """`actor_id: 1a` -> avval ValueError butun API ni 500 qilardi.

    `from_file` "hech qachon istisno tashlamaydi" deb va'da beradi va
    `/api/health` shunga tayanadi. Bitta xato belgi bu va'dani buzardi.
    """
    path = _write(tmp_path, [{**BASE, "actor_id": "1a"}])
    store = UserStore.from_file(path)          # istisno CHIQMASLIGI kerak
    assert len(store) == 1
    assert store.by_email("admin@venera.uz").actor_id == 1   # o'rniga tartib raqami


def test_bitta_buzuq_yozuv_qolganlarini_yutib_yubormaydi(tmp_path):
    path = _write(tmp_path, [
        {**BASE, "actor_id": "yomon"},
        {**BASE, "actor_id": 2, "email": "demo@venera.uz"},
    ])
    store = UserStore.from_file(path)
    assert len(store) == 2, "buzuq yozuv sog'lomini ham yo'q qildi"


def test_qavssiz_roles_harflarga_bolinmaydi(tmp_path):
    """`roles: ADMIN` (ro'yxat emas) -> ['A','D','M','I','N'] bo'lardi.

    Natijada foydalanuvchi ADMIN bo'lmasdi, lekin xato ham ko'rinmasdi.
    """
    path = _write(tmp_path, [{**BASE, "roles": "ADMIN"}])
    roles = UserStore.from_file(path).by_email("admin@venera.uz").roles
    assert roles == ["ADMIN"], f"rollar buzildi: {roles}"


def test_roles_yoq_bolsa_bosh_royxat(tmp_path):
    path = _write(tmp_path, [{k: v for k, v in BASE.items() if k != "roles"}])
    assert UserStore.from_file(path).by_email("admin@venera.uz").roles == []


def test_takror_email_ogohlantiradi(tmp_path, caplog):
    """Takror email oldingi yozuvni ALMASHTIRADI - hech bo'lmasa log'da ko'rinsin."""
    path = _write(tmp_path, [
        {**BASE, "roles": ["ADMIN", "RAG_ADMIN"]},
        {**BASE, "actor_id": 2, "full_name": "Ikkinchi", "roles": ["USER"]},
    ])
    with caplog.at_level("ERROR"):
        store = UserStore.from_file(path)
    assert len(store) == 1
    assert store.by_email("admin@venera.uz").roles == ["USER"]  # ikkinchisi yutdi
    assert any("takrorlan" in r.message.lower() or "takrorlan" in r.getMessage().lower()
               for r in caplog.records), "takror email haqida ogohlantirish yo'q"


# --- namuna parollarini aniqlash ---

def test_namuna_xeshlari_oqiladi():
    """`users.example.yaml` git'da - undagi xeshlar aniqlanishi kerak."""
    from app.core.config import settings
    hashes = example_password_hashes(settings.users_file.parent / "users.example.yaml")
    assert len(hashes) >= 2, "namuna fayldan xesh o'qilmadi"


def test_namuna_paroli_ishlatilsa_aniqlanadi(tmp_path):
    from app.core.config import settings
    example = settings.users_file.parent / "users.example.yaml"
    hashes = example_password_hashes(example)
    entries = yaml.safe_load(example.read_text(encoding="utf-8"))["users"]

    store = UserStore.from_file(_write(tmp_path, entries))
    flagged = store.emails_using(hashes)
    assert flagged, "namuna parollari ishlatilyapti, lekin aniqlanmadi"


def test_oz_paroli_bolsa_ogohlantirish_yoq(tmp_path):
    from app.core.config import settings
    hashes = example_password_hashes(settings.users_file.parent / "users.example.yaml")
    store = UserStore.from_file(_write(tmp_path, [BASE]))
    assert store.emails_using(hashes) == [], "yolg'on ogohlantirish"


def test_namuna_fayl_yoq_bolsa_yiqilmaydi(tmp_path):
    assert example_password_hashes(tmp_path / "yoq.yaml") == set()


def test_health_namuna_parolini_aytadi(client, auth, monkeypatch, tmp_path):
    """`/api/health` degraded bo'lishi va qaysi hisob ekanini aytishi kerak.

    DIQQAT: `health()` `get_user_store()` ni `Depends` orqali EMAS, to'g'ridan
    chaqiradi - shuning uchun `dependency_overrides` unga ta'sir qilmaydi va
    modul atributini almashtirish kerak. Buni bilmasa test jimgina HAQIQIY
    `config/users.yaml` ni o'qib, tasodifan o'tib ketardi.
    """
    import app.main as main
    from app.core.config import settings

    example = settings.users_file.parent / "users.example.yaml"
    entries = yaml.safe_load(example.read_text(encoding="utf-8"))["users"]
    store = UserStore.from_file(_write(tmp_path, entries))

    monkeypatch.setattr(main, "get_user_store", lambda: store)
    body = client.get("/api/health/detail", headers=auth).json()

    assert body["status"] == "degraded"
    assert any("NAMUNA PAROLLARI" in w for w in body["warnings"])
    assert any("admin@venera.uz" in w for w in body["warnings"])


def test_health_oz_paroli_bilan_toza(client, auth, monkeypatch, tmp_path):
    """Yolg'on ogohlantirish bo'lmasligi kerak - aks holda unga e'tibor berilmay qoladi."""
    import app.main as main
    store = UserStore.from_file(_write(tmp_path, [BASE]))
    monkeypatch.setattr(main, "get_user_store", lambda: store)

    body = client.get("/api/health/detail", headers=auth).json()
    assert not any("NAMUNA PAROLLARI" in w for w in body["warnings"]), body["warnings"]
