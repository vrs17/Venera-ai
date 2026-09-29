"""Xodimlar ma'lumotnomasi: yuklash, qidirish, chatda tahrirlash (tasdiq bilan).

Ismlar TO'QIMA - haqiqiy ro'yxat testlarda yo'q.
"""

from __future__ import annotations

import json

import pytest

from app.core.config import settings
from app.schemas.auth import AuthUser
from app.services import contacts, contacts_chat
from app.services.contacts import ContactError, clean_email, clean_phone, clean_telegram
from app.tools.contacts_import import load, read_rows

LIST = """F.I.SH\tTelegram\tNomer\tBRB Tech Email
Qodirov Sanjarbek Olim o'g'li\t@sanjar_q\t+998901112233\ts.qodirov@example.uz
Qodirov Temur Aziz o'g'li\t-\t+998\tt.qodirov@example.uz
Nazarova Dilnoza Karim qizi\t@dilnoza_n\t+998935554433\t-
Xolmatov Ulug‘bek Ergashevich\t-\t+998\t-
Isroilov Botir Olimjonovich\t@botir_isroilov\t+998977778899\tb.isroilov@example.uz
"""

ADMIN = AuthUser(actorId=1, email="admin@venera.uz", fullName="Admin", roles=["ADMIN"])
USER = AuthUser(actorId=2, email="demo@venera.uz", fullName="Demo", roles=["USER"])


@pytest.fixture
def people():
    report = load(read_rows(LIST), actor="import:test")
    assert report == {"added": 5, "updated": 0, "same": 0, "problems": []}
    return contacts.store


def ask(question, user=ADMIN):
    stream = contacts_chat.answer(question, user)
    if stream is None:
        return None
    frames = [json.loads(raw) for raw in stream.frames]
    text = "".join(f.get("text", "") for f in frames if f["type"] == "token")
    proposal = next((f["proposal"] for f in frames if f["type"] == "proposal"), None)
    assert frames[-1] == {"type": "done", "route": "contacts"}
    return text, proposal


# --- tozalash va yuklash ------------------------------------------------------------


def test_qiymatlar_tozalanadi():
    assert clean_phone("+998") is None and clean_phone("-") is None
    assert clean_phone("90 111 22 33") == "+998901112233"
    assert clean_phone("+998 (93) 555-44-33") == "+998935554433"
    assert clean_telegram("-") is None and clean_telegram("t.me/abc_d") == "@abc_d"
    assert clean_email(" A.B@Example.UZ ") == "a.b@example.uz"
    for bad in (lambda: clean_phone("12345"), lambda: clean_telegram("@a"), lambda: clean_email("x@")):
        with pytest.raises(ContactError):
            bad()


def test_yuklash_bosh_kataklar_va_qayta_yuklash(people):
    temur = people.find("Qodirov Temur")[0][0]
    assert temur.phone is None and temur.telegram is None and temur.email == "t.qodirov@example.uz"
    # Qayta yuklash: yangi telefon qo'shiladi, bo'sh katak bor qiymatni o'chirmaydi.
    again = LIST.replace("Qodirov Temur Aziz o'g'li\t-\t+998", "Qodirov Temur Aziz o'g'li\t-\t+998909998877")
    again += "Yangiboyev Aziz Ali o'g'li\t-\t-\t-\n"
    report = load(read_rows(again), actor="import:test")
    assert report["added"] == 1 and report["updated"] == 1 and report["same"] == 4
    assert people.get(temur.id).phone == "+998909998877" and people.get(temur.id).email == "t.qodirov@example.uz"
    assert people.count() == 6


def test_yuklashda_xato_maydon_qolganini_buzmaydi():
    report = load(read_rows("F.I.SH\tTelegram\tNomer\tEmail\nSobirov Ali\t@x\t123\tali@example.uz\n"),
                  actor="import:test")
    assert report["added"] == 1 and {p[1] for p in report["problems"]} == {"telegram", "phone"}
    assert contacts.store.all()[0].email == "ali@example.uz"


# --- qidirish -------------------------------------------------------------------------


@pytest.mark.parametrize("question", [
    "Nazarova Dilnozaning telefon raqami qanday?",
    "Dilnozaning telegrami?",                      # faqat ism, qo'shimcha bilan
    "Назарова Дилнозанинг телефони",               # kirill
    "nazarova dilnoza nomeri",                     # STT kabi, kichik harf
])
def test_kontakt_savoli_royxatdan_javob_oladi(people, question):
    text, proposal = ask(question)
    assert "**Nazarova Dilnoza Karim qizi**" in text and "+998935554433" in text and "@dilnoza_n" in text
    assert "Email: kiritilmagan" in text and proposal is None


def test_imlo_va_qisqa_ism(people):
    assert "Xolmatov Ulug‘bek" in ask("Holmatov Ulugbekning telefoni")[0]      # x/h, apostrof
    assert "Isroilov Botir" in ask("Isroiliv Botirning emaili")[0]              # bitta harf xato
    assert "Qodirov Sanjarbek" in ask("Qodirov Sanjarning telegrami")[0]         # qisqa ism


def test_familiya_bir_xil_bolsa_ikkalasi(people):
    text, _ = ask("Qodirovning telefon raqami")
    assert "Bir nechta xodim" in text and "Sanjarbek" in text and "Temur" in text


@pytest.mark.parametrize("question", [
    "Nazarova Dilnoza bugun ishga keldimi?",       # HRM savoli - kontakt so'zi yo'q
    "Qodirov Sanjarbekning shartnoma raqami",      # "raqam", lekin telefon emas
    "Kimning telefon raqami +998901112233?",       # ism yo'q
    "CRM dagi vazifani o'chir",                    # boshqa tahrir
    "Ta'til arizasini ro'yxatga qo'sh",            # ism ham, qiymat ham yo'q
])
def test_boshqa_savollar_yordamchiga_ketadi(people, question):
    assert ask(question) is None


def test_bosh_malumotnoma_chatga_tegmaydi():
    assert ask("Nazarova Dilnozaning telefoni") is None


# --- tahrirlash -------------------------------------------------------------------------


def confirm(token, user=ADMIN):
    return contacts_chat.act("confirm", token, user)


def test_telefonni_ozgartirish_karta_va_tasdiq(people):
    text, proposal = ask("Nazarova Dilnozaning telefonini +998 90 123 45 67 ga o'zgartir")
    assert proposal["connector"] == "xodimlar" and proposal["target"]["name"].startswith("Nazarova Dilnoza")
    assert proposal["changes"] == [{"field": "Telefon", "from": "+998935554433", "to": "+998901234567"}]
    assert proposal["token"].startswith("ct_")
    # Hali hech narsa o'zgarmagan.
    assert people.find("Nazarova Dilnoza")[0][0].phone == "+998935554433"
    result = confirm(proposal["token"])
    assert result["status"] == "executed" and result["ok"] and result["result"] == {"key": "Nazarova Dilnoza"}
    employee = people.find("Nazarova Dilnoza")[0][0]
    assert employee.phone == "+998901234567"
    change = people.history(employee.id)[0]
    assert (change["actor"], change["action"], change["field"], change["old"], change["new"]) == \
        ("venera:1", "update", "phone", "+998935554433", "+998901234567")
    # Bir martalik.
    with pytest.raises(Exception):
        confirm(proposal["token"])


def test_telegram_email_qiymat_turidan(people):
    _, proposal = ask("Qodirov Temurning ma'lumotini o'zgartir: @temur_q, temur.q@example.uz")
    assert {c["field"]: c["to"] for c in proposal["changes"]} == {"Telegram": "@temur_q", "Email": "temur.q@example.uz"}


def test_maydonni_tozalash(people):
    _, proposal = ask("Isroilov Botirning telegramini o'chir")
    assert proposal["changes"] == [{"field": "Telegram", "from": "@botir_isroilov", "to": None}]
    confirm(proposal["token"])
    assert people.find("Isroilov Botir")[0][0].telegram is None


def test_xodimni_ochirish(people):
    _, proposal = ask("Xolmatov Ulug'bekni ro'yxatdan o'chir")
    assert proposal["operation"] == "delete_employee"
    confirm(proposal["token"])
    assert people.count() == 4 and not people.find("Xolmatov Ulugbek")


def test_yangi_xodim_qoshish(people):
    text, proposal = ask("Yangi xodim qo'sh: Karimov Jasur Anvarovich, +998971234567, @jasur_k")
    assert proposal["operation"] == "create_employee" and proposal["target"]["name"] == "Karimov Jasur Anvarovich"
    assert {c["field"]: c["to"] for c in proposal["changes"]} == {
        "F.I.SH": "Karimov Jasur Anvarovich", "Telefon": "+998971234567", "Telegram": "@jasur_k"}
    assert any("Email" in w for w in proposal["warnings"])
    confirm(proposal["token"])
    assert "@jasur_k" in ask("Karimov Jasurning telegrami")[0]


def test_ism_familiyani_tuzatish(people):
    _, proposal = ask("Isroiliv Botirning ismini Isroilov Botir Olimovich ga o'zgartir")
    assert proposal["changes"] == [{"field": "F.I.SH", "from": "Isroilov Botir Olimjonovich",
                                    "to": "Isroilov Botir Olimovich"}]


def test_takroriy_telefon_rad_etiladi(people):
    _, proposal = ask("Qodirov Temurning telefonini +998901112233 ga o'zgartir")
    result = confirm(proposal["token"])
    assert result["status"] == "failed" and "boshqa xodimda bor" in result["error"]


def test_shu_orada_ozgargan_bolsa_ustidan_yozilmaydi(people):
    _, first = ask("Nazarova Dilnozaning telefonini +998901234567 ga o'zgartir")
    _, second = ask("Nazarova Dilnozaning telefonini +998907654321 ga o'zgartir")
    confirm(first["token"])
    result = confirm(second["token"])
    assert result["status"] == "failed" and "o'zgargan" in result["error"]


def test_oddiy_foydalanuvchi_ozgartira_olmaydi(people):
    text, proposal = ask("Nazarova Dilnozaning telefonini +998901234567 ga o'zgartir", USER)
    assert proposal is None and "faqat administrator" in text
    assert "+998935554433" in ask("Nazarova Dilnozaning telefoni", USER)[0]    # qidirish ochiq


def test_boshqa_odam_taklifini_tasdiqlay_olmaydi(people):
    _, proposal = ask("Nazarova Dilnozaning telefonini +998901234567 ga o'zgartir")
    other = AuthUser(actorId=9, email="x@venera.uz", fullName="X", roles=["ADMIN"])
    with pytest.raises(Exception):
        confirm(proposal["token"], other)
    assert people.find("Nazarova Dilnoza")[0][0].phone == "+998935554433"


def test_rad_etish_va_muddat(people, monkeypatch):
    _, proposal = ask("Nazarova Dilnozaning telefonini +998901234567 ga o'zgartir")
    assert contacts_chat.act("cancel", proposal["token"], ADMIN)["status"] == "cancelled"
    _, proposal = ask("Nazarova Dilnozaning telefonini +998901234567 ga o'zgartir")
    import time as _time
    real = _time.time
    monkeypatch.setattr(contacts_chat.time, "time", lambda: real() + 1000)
    assert contacts_chat.act("confirm", proposal["token"], ADMIN)["status"] == "expired"
    assert people.find("Nazarova Dilnoza")[0][0].phone == "+998935554433"


def test_bir_nechta_mos_kelsa_taklif_yoq(people):
    text, proposal = ask("Qodirovning telefonini +998901234567 ga o'zgartir")
    assert proposal is None and "Bir nechta xodim" in text


# --- HTTP: chat oqimi va tasdiqlash endpointi ---------------------------------------------


def test_chat_stream_va_actions_endpoint(client, auth, people, monkeypatch):
    import app.api.v1.chat as chat_api

    def fail(*args, **kwargs):
        raise AssertionError("kontakt savoli yuqoridagi xizmatga bormasligi kerak")

    monkeypatch.setattr(chat_api._assistant, "stream", fail)
    r = client.post("/api/v1/chat/stream", headers=auth,
                    json={"question": "Nazarova Dilnozaning telefonini +998901234567 ga o'zgartir"})
    frames = [json.loads(line) for line in r.text.splitlines()]
    proposal = next(f["proposal"] for f in frames if f["type"] == "proposal")
    r = client.post(f"/api/v1/actions/{proposal['token']}/confirm", headers=auth)
    assert r.status_code == 200 and r.json()["status"] == "executed" and r.json()["connector"] == "xodimlar"
    r = client.post("/api/v1/chat/stream", headers=auth, json={"question": "Nazarova Dilnozaning telefoni?"})
    assert "+998901234567" in r.text


def test_demo_foydalanuvchi_endpoint_orqali_ham_rad(client, people):
    token = client.post("/api/v1/auth/login", json={"email": "demo@venera.uz", "password": "demo2026"}).json()["token"]
    r = client.post("/api/v1/chat/stream", headers={"Authorization": f"Bearer {token}"},
                    json={"question": "Nazarova Dilnozani ro'yxatdan o'chir"})
    assert "faqat administrator" in r.text and '"proposal"' not in r.text


# --- Telegram bot: o'sha yo'l ---------------------------------------------------------------


def test_botda_qidirish_va_tasdiqlash(people, tmp_path):
    from app.bot.runner import Backend, VeneraBot
    from app.core.security import hash_password
    from app.services.telegram_links import LinkStore
    from app.services.users import StoredUser, UserStore
    from tests.test_telegram_bot import FakeTelegram, callback, text_update, TG_ID

    users = UserStore({"a@b.uz": StoredUser(actor_id=1, email="a@b.uz", full_name="Admin",
                                            password_hash=hash_password("x"), roles=["ADMIN"])})
    tg = FakeTelegram()
    links = LinkStore(tmp_path / "links.json")
    links.link(TG_ID, 1)
    bot = VeneraBot(tg, links, users=lambda: users, backend=Backend(), inline=True, typing_every=None)
    bot.handle_update(text_update("Nazarova Dilnozaning telefoni"))
    assert "+998935554433" in tg.texts()[-1]
    bot.handle_update(text_update("Nazarova Dilnozaning telefonini +998901234567 ga o'zgartir"))
    card = tg.sent()[-1]
    assert "XODIMLAR" in card["text"] and "<s>+998935554433</s> → +998901234567" in card["text"]
    data = card["reply_markup"]["inline_keyboard"][0][1]["callback_data"]
    assert data.startswith("a:c:ct_")
    bot.handle_update(callback(data))
    assert tg.texts()[-1] == "✅ <b>Bajarildi</b>: <code>Nazarova Dilnoza</code>"
    assert people.find("Nazarova Dilnoza")[0][0].phone == "+998901234567"


def test_mavjud_xodimni_toldirish_xodim_sozisiz(people):
    _, proposal = ask("Qodirov Temurga telegram qo'sh: @temur_q")
    assert proposal["operation"] == "update_employee"
    assert proposal["changes"] == [{"field": "Telegram", "from": None, "to": "@temur_q"}]


def test_bitta_ism_boshqa_odamga_tegmaydi(people):
    # "Sanjar" - "Qodirov Sanjarbek" ning ismiga o'xshaydi, lekin familiya boshqa.
    _, proposal = ask("Aliyev Sanjar +998971112233 ni qo'sh")
    assert proposal["operation"] == "create_employee" and proposal["target"]["name"] == "Aliyev Sanjar"


def test_xodim_sozi_bilan_bir_xil_ism_ogohlantirish(people):
    _, proposal = ask("Yangi xodim qo'sh: Nazarova Dilnoza, @dilnoza_2")
    assert proposal["operation"] == "create_employee"
    assert any("o'xshash xodim bor" in w for w in proposal["warnings"])


# --- ro'yxat so'rovlari -------------------------------------------------------------

def test_foydalanuvchi_yozgan_sorov_royxat_chiqaradi(people):
    # Aynan jonli so'rov: "contaktlar" (c bilan), "ro'yhat" (h bilan).
    text, proposal = ask("xodimlarni contaktlar ro'yhatini chiqar")
    assert text.startswith("**Xodimlar kontaktlari — 5 ta**") and proposal is None
    assert "1. Isroilov Botir Olimjonovich — +998977778899 · @botir_isroilov · b.isroilov@example.uz" in text
    assert "Xolmatov Ulug‘bek Ergashevich — kiritilmagan" in text
    assert "Kiritilmagan: telefon — 2 ta, telegram — 2 ta, email — 2 ta" in text


def test_bitta_maydon_royxati(people):
    text, _ = ask("Barcha xodimlarning telefon raqamlarini ko'rsat")
    assert text.startswith("**Xodimlar: telefon — 3 ta**") and "@" not in text.split("\n\n")[1]
    assert "Telefon kiritilmagan: 2 ta xodim" in text


def test_kiritilmaganlar_royxati(people):
    text, _ = ask("Telegrami kiritilmagan xodimlar ro'yxati")
    assert text.startswith("**Telegram kiritilmagan xodimlar — 2 ta**")
    assert "Qodirov Temur" in text and "Xolmatov" in text and "Nazarova" not in text
    assert "To'ldirish:" in text                      # administratorga maslahat
    assert "To'ldirish:" not in ask("Telegrami kiritilmagan xodimlar ro'yxati", USER)[0]


@pytest.mark.parametrize("question", [
    "Bugun kech qolgan xodimlar ro'yxati",          # HRM - kontakt so'zi yo'q
    "Yangi qo'shilgan xodimlar kimlar?",            # majhul shakl - buyruq emas
    "Xodimlar ro'yxatini bo'limlar bo'yicha ber",   # HRM
])
def test_hrm_royxatlari_yordamchiga_ketadi(people, question):
    assert ask(question) is None


def test_ism_aniq_bolsa_royxat_emas_bitta_odam(people):
    text, _ = ask("Nazarova Dilnozaning kontaktlari")
    assert text.startswith("**Nazarova Dilnoza Karim qizi**")


# --- suhbat davomi: "kontaktlarini kiritishimiz kerak" -> qiymatlar -> karta -----------

def test_yangi_odam_kontaktlarini_kiritish_ikki_bosqichda(people):
    # Aynan jonli so'rov shakli (bu odam ro'yxatda yo'q).
    text, proposal = ask("Maxmudov Azizmurod kontaktlarini kiritishimiz kerak")
    assert proposal is None and text.startswith("**Maxmudov Azizmurod** ma'lumotnomada hali yo'q")
    assert "Kontaktlarini yozing" in text
    text, proposal = ask("+998901234567, @azizmurod_m, a.maxmudov@example.uz")
    assert proposal["operation"] == "create_employee" and proposal["target"]["name"] == "Maxmudov Azizmurod"
    assert {c["field"]: c["to"] for c in proposal["changes"]} == {
        "F.I.SH": "Maxmudov Azizmurod", "Telefon": "+998901234567", "Telegram": "@azizmurod_m",
        "Email": "a.maxmudov@example.uz"}
    confirm(proposal["token"])
    assert "@azizmurod_m" in ask("Maxmudov Azizmurodning telegrami")[0]


def test_familiyasi_oxshash_yangi_odam_mos_kelgan_deb_korsatilmaydi(people):
    # "Qodirov Anvar" - ro'yxatda Qodirov Sanjarbek va Qodirov Temur bor, Anvar yo'q.
    text, proposal = ask("Qodirov Anvar kontaktlarini kiritishimiz kerak")
    assert proposal is None and text.startswith("**Qodirov Anvar** ma'lumotnomada hali yo'q")
    _, proposal = ask("+998901234567")
    assert proposal["target"]["name"] == "Qodirov Anvar"


def test_ismi_boshqa_qidiruvda_topilmadi_deyiladi(people):
    text, proposal = ask("Qodirov Anvarning telefoni qanday?")
    assert text.startswith("**Qodirov Anvar** ma'lumotnomada yo'q. Familiyasi o'xshashlar:")
    assert "Qodirov Sanjarbek" in text and "Qo'shish uchun" in text and proposal is None
    assert "Qo'shish uchun" not in ask("Qodirov Anvarning telefoni qanday?", USER)[0]


def test_yoq_odamning_telefonini_ozgartirish_qoshishga_aylanadi(people):
    _, proposal = ask("Qodirov Anvarning telefonini +998901234567 ga o'zgartir")
    assert proposal["operation"] == "create_employee" and proposal["target"]["name"] == "Qodirov Anvar"


def test_mavjud_xodim_kontaktlarini_yangilash_ikki_bosqichda(people):
    text, proposal = ask("Qodirov Temurning kontaktlarini yangilash kerak")
    assert proposal is None and text.startswith("**Qodirov Temur Aziz o'g'li**") and "Yangi qiymatni yozing" in text
    _, proposal = ask("@temur_q")
    assert proposal["operation"] == "update_employee"
    assert proposal["changes"] == [{"field": "Telegram", "from": None, "to": "@temur_q"}]


def test_maydon_aytildi_qiymat_keyin(people):
    text, _ = ask("Nazarova Dilnozaning telefonini o'zgartirish kerak")
    assert "Yangi qiymatni yozing: telefon" in text
    _, proposal = ask("+998 90 123 45 67")
    assert proposal["changes"] == [{"field": "Telefon", "from": "+998935554433", "to": "+998901234567"}]


def test_qoralama_boshqa_gapga_yopishmaydi(people):
    ask("Qodirov Anvar kontaktlarini kiritishimiz kerak")
    assert ask("Ta'til necha kun beriladi?") is None          # boshqa savol - qoralama tushadi
    assert ask("+998901234567") is None                      # endi hech kimga tegishli emas


def test_qoralama_boshqa_odam_ismi_bilan_ishlatilmaydi(people):
    ask("Qodirov Anvar kontaktlarini kiritishimiz kerak")
    text, proposal = ask("Nazarova Dilnozaning telegrami @yangi_tg ga o'zgartir")
    assert proposal["target"]["name"].startswith("Nazarova Dilnoza")


def test_oddiy_foydalanuvchi_kontakt_kirita_olmaydi(people):
    text, proposal = ask("Qodirov Anvar kontaktlarini kiritishimiz kerak", USER)
    assert proposal is None and "faqat administrator" in text


def test_foydalanuvchining_ikkinchi_royxat_sorovi(people):
    text, _ = ask("menga xodimlarni kontaktlari ro'yhatini ber")
    assert text.startswith("**Xodimlar kontaktlari — 5 ta**")
    assert ask("menga xodimlarni kontaktlari ro'yhatini ber")[0] == text     # har safar bir xil


@pytest.mark.parametrize("question", [
    "Sanjarbek Qodirovni kontaklarini ko'rsat",      # jonli so'rov shakli: "kontak" (t siz), ism oldin
    "Qodirov Sanjarbekning kontaktlari",
    "Sanjarbek Qodirov kantakti",
    "Qodirov Sanjarbek contact",
    "Кодиров Санжарбек контактлари",                 # kirill
])
def test_kontakt_sozining_yozilish_variantlari(people, question):
    text, proposal = ask(question)
    assert text.startswith("**Qodirov Sanjarbek Olim o'g'li**") and proposal is None


def test_faqat_ism_yordamchiga_ketadi(people):
    # Yordamchining "Qaysi xodim?" savoliga javob bo'lishi mumkin - tutib olinmaydi.
    assert ask("Sanjarbek Qodirov") is None


def test_kontaklar_royxati(people):
    assert ask("xodimlar kontaklari ro'yxati")[0].startswith("**Xodimlar kontaktlari — 5 ta**")


def test_telgram_xatosi_telefonga_tushmaydi(people):
    _, proposal = ask("Isroilov Botirning telgramini o'chir")
    assert proposal["changes"] == [{"field": "Telegram", "from": "@botir_isroilov", "to": None}]


@pytest.mark.parametrize("question, expected", [
    ("Sanjar akani kontakti", "**Qodirov Sanjarbek"),              # jonli so'rov shakli
    ("Temur akaning telegrami", "**Qodirov Temur"),
    ("Dilnoza opaning telefoni", "**Nazarova Dilnoza"),
    ("Botir akajonni kontaklarini ber", "**Isroilov Botir"),
    ("hurmatli Isroilov Botirning emaili", "**Isroilov Botir"),
])
def test_hurmat_sozlari_ism_emas(people, question, expected):
    text, proposal = ask(question)
    assert text.startswith(expected) and proposal is None


@pytest.mark.parametrize("question", [
    "telefoni yo'q xodimlar ro'yxati",
    "xodimlar kontaktlarini yuboring",
    "barcha kontaktlar",
])
def test_ismsiz_royxat_sorovlari(people, question):
    text, _ = ask(question)
    assert text.startswith("**")  and ("kontaktlari" in text.split("\n")[0] or "kiritilmagan" in text.split("\n")[0])
