"""Sozlamalar - hammasi muhit o'zgaruvchilaridan.

QOIDA: kodda hech qanday manzil, parol yoki kalit QATTIQ YOZILMAYDI.
Sabab oddiy - dev, test va prod bir xil kod bilan ishlashi kerak, va sir
git'ga tushmasligi kerak.

Qiymatlar tartibi: muhit o'zgaruvchisi -> `.env` fayli -> shu yerdagi default.
Default'lar LOKAL ISHLAB CHIQISH uchun xavfsiz bo'lishi kerak, prod uchun emas.
"""

from __future__ import annotations

import threading

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

#: apps/api/ papkasi - config fayllari shunga nisbatan qidiriladi.
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Venera API"
    #: Frontend `package.json` versiyasi bilan bog'liq emas - bu API versiyasi.
    version: str = "0.1.0"
    debug: bool = False

    # --- xavfsizlik ---
    #: Token imzolash kaliti. PRODUCTION'DA ALBATTA O'ZGARTIRILADI.
    #: Bu default qiymat ataylab "xavfsiz emas" deb ko'rinadi - unutib
    #: qo'yilsa `/health` uni ogohlantirish sifatida ko'rsatadi.
    secret_key: str = "dev-only-insecure-change-me"
    token_ttl_hours: int = 12

    #: Demo foydalanuvchilar fayli. Keyinchalik bu joyni DB egallaydi -
    #: `services/users.py` interfeysi o'zgarmaydi.
    users_file: Path = BASE_DIR / "config" / "users.yaml"

    # --- STT (ovozni matnga o'girish) ---
    #: STT Router manzili. Ichki tarmoqda, VPN ortida.
    stt_base_url: str = "http://10.10.50.4:8006"
    #: BIR urinish uchun timeout. Byudjet zanjiri: brauzer nginx orqali 120 s
    #: kutadi (API_READ_TIMEOUT). Undan uzoq kutish ma'nosiz - javob endi hech
    #: kimga yetib bormaydi, lekin slot va Router ishchisi band turadi.
    stt_timeout: float = 35.0
    #: 503 (navbat to'la) uchun urinishlar. 502/504 QAYTA URINILMAYDI.
    stt_attempts: int = 3
    #: Butun `transcribe()` uchun devor-soat chegarasi - nginx 120 s dan KAM.
    stt_deadline: float = 100.0
    #: BUTUN park uchun Router chegarasi ~10 parallel (o'lchangan: 25 da 503 lar
    #: boshlanadi). Web ilova shuning bir qismini oladi - desktop park va boshqa
    #: klientlarga joy qolsin. Oshsa - kutmasdan 503 "band" qaytaramiz.
    stt_max_concurrent: int = 4
    #: Yuklash chegarasi. Router o'zi ham 25 MB da to'xtatadi, lekin biz
    #: undan OLDIN to'xtatamiz: aks holda katta fayl butun tarmoqni bosib
    #: o'tib, faqat oxirida rad etilardi.
    stt_max_upload_mb: float = 10.0

    # --- STT VARIANTI: qaysi xizmat ishlatiladi ---
    #: `router` - 1-variant, ichki STT Router (yuqorida). `gapi` -
    #: 2-variant, `console.gapi.uz`.
    #:
    #: IKKALASI HAM QOLADI. Qaytarish uchun kod o'zgartirilmaydi: `.env`
    #: dagi `STT_PROVIDER` qatorini o'chirib, xizmatni qayta ishga
    #: tushirish yetadi. Shu sababli KODDAGI default `router` - isbotlangan
    #: yo'l, va sinov `.env` orqali yoqiladi.
    #:
    #: GAPI faqat O'ZBEK tilini biladi va matnni faqat LOTIN yozuvida
    #: qaytaradi. `ru`/`en` uchun unda model yo'q, shuning uchun tanlovchi
    #: (`api/v1/stt.py`) bu tillarni baribir Router'ga yuboradi - ya'ni
    #: GAPI ga o'tish rus yoki ingliz interfeysini buzmaydi.
    stt_provider: str = "router"
    #: UYG'OTISH SO'ZI uchun ALOHIDA tanlov, va default ATAYLAB `router`.
    #:
    #: Sababi o'lchangan. Tinglagich `COOLDOWN_MS = 2500` bilan ishlaydi,
    #: ya'ni tinglab turgan har bir varaq daqiqasiga 24 TAGACHA so'rov
    #: yuborishi mumkin (jim xonada - nol, chunki sukunat brauzerdan
    #: chiqmaydi). GAPI da esa yuklash chegarasi daqiqasiga 60 ta va har
    #: bo'lak PULLIK - holbuki bu bo'laklarning deyarli hammasi "bu
    #: uyg'otish so'zi emas" degan javob beradi. Ichki Router shu ishni
    #: 0.1 sekundda va bepul qiladi.
    #:
    #: Ya'ni bu "tejamkorlik" emas, vazifaning boshqaligi: uyg'otish so'zi
    #: - kalit so'z qidirish, transkripsiya emas.
    stt_wake_provider: str = "router"

    # --- GAPI STT (2-variant) ---
    gapi_base_url: str = "https://console.gapi.uz/v1"
    #: Loyihaga bog'langan token. Bo'sh bo'lsa 2-variant O'CHIQ.
    gapi_api_key: str = ""
    #: O'lchangan tezlik: mediana 1.2 s, yuklama ostida 3.6 s; 35 s yozuv
    #: 1-3 sekundda.
    #:
    #: 60 EMAS, 20 - va sababi zahira. GAPI yiqilganda so'rov Router'ga
    #: tushadi, ya'ni BITTA so'rov ikki klientning vaqtini ketma-ket yeydi.
    #: 60 s bo'lganda jami 121 s ga chiqardi, nginx esa 120 s da ulanishni
    #: uzadi - Router'ning javobi o'lgan socketga yozilardi. 20 s esa
    #: o'lchangan eng yomon holatdan (3.6 s) besh barobar katta, ya'ni
    #: sog'lom GAPI bunga bemalol sig'adi; sig'masa - Router tezroq
    #: javob beradi.
    gapi_timeout: float = 20.0
    #: Yuklash chegarasi daqiqasiga 60 ta (token uchun) - bu bizning ulush.
    gapi_max_concurrent: int = 2

    # --- UYG'OTISH SO'ZI uchun GAPI byudjeti ---
    #
    # NEGA BU KERAK. Uyg'otish so'zi tinglagichi FONDA ishlaydi va har bir
    # chat varag'ida default YOQIQ. Brauzerdagi `COOLDOWN_MS = 2500` esa
    # bizning YAGONA chegaramiz edi - ya'ni pullik xizmatning tormozi
    # MIJOZDA turgan. O'zgartirilgan sahifa, ochiq qolgan eski varaq yoki
    # bir odamning uchta varag'i hisobni yeb qo'yishi mumkin edi.
    #
    # O'LCHANGAN SONLAR (jonli GAPI, shu loyiha tokeni):
    #   * bitta parcha = 0.03 g, ya'ni 1 g = 1 audio-daqiqa, kunlik 480 g;
    #   * bitta varaq daqiqasiga 24 tagacha parcha yuboradi (2.5 s oraliq);
    #   * tokenning yuklash chegarasi 60/daqiqa - va o'sha tokendan
    #     foydalanuvchining SAVOLI ham o'tadi, ya'ni uch varaq 72 ta qilib
    #     chegaradan oshadi va 429 aynan SAVOLGA tegadi;
    #   * jonli uyg'otish jurnalida parchalarning ~71 foizi uyg'otish
    #     so'zi EMAS - ya'ni pulning katta qismi "bu u emas" javobiga
    #     ketadi.
    #
    # Chegaradan oshganda so'rov RAD ETILMAYDI - 1-variantga (bepul, ichki
    # Router) tushadi. Uyg'otish - kalit so'z qidirish, Router buni
    # baribir 0.1 sekundda bajaradi. Ya'ni bu chegara xizmatni emas,
    # HISOBNI cheklaydi.
    #: Bitta foydalanuvchi uchun daqiqada nechta parcha GAPI ga ketadi.
    #: 30 - bitta halol varaq (24/daqiqa) erkin o'tadi, ikkinchi varaqdan
    #: boshlab esa ortiqchasi Router'ga tushadi.
    wake_gapi_per_actor_min: int = 30
    #: HAMMA foydalanuvchilar uchun jami. 45 - tokenning 60/daqiqa
    #: chegarasidan past, ya'ni foydalanuvchining SAVOLI uchun joy qoladi.
    wake_gapi_total_min: int = 45

    # --- TTS (matnni ovozga o'girish) ---
    #: TTS serveri. Ichki tarmoqda, VPN ortida - STT bilan bir xil hostda,
    #: boshqa portda.
    tts_base_url: str = "http://10.10.50.4:8200"
    #: Klient sirlari TTS serverining `AUTH_CLIENTS` ro'yxatidan keladi.
    #: `tts_client_secret` BO'SH bo'lsa ovoz sintezi o'chiq: endpoint 503
    #: qaytaradi, qolgan hamma narsa ishlaydi. Sir FAQAT `.env` da.
    tts_client_id: str = "frontend"
    tts_client_secret: str = ""
    #: BO'LAKLAR ORASIDAGI kutish - oqim uzunligi EMAS. Bo'laklar odatda
    #: 1-2 s oralab keladi, ya'ni bu chegara faqat server butunlay jim
    #: qolganda ishlaydi. Sintez GPU navbatida turishi mumkin, shuning
    #: uchun birinchi bo'lak uchun ham shu qiymat.
    tts_timeout: float = 60.0
    #: Server 429 qaytarmaydi - navbat cheksiz o'sadi. Chegarani o'zimiz
    #: qo'yamiz: oshsa darhol 503 "band".
    tts_max_concurrent: int = 2
    #: Ovoz profili: `uz_female_calm` (ayol) yoki `uz_male_news` (erkak).
    tts_voice: str = "uz_female_calm"
    #: `null` -> server 0.95 ni oladi. Rasmiy matn uchun 0.90, yangiliklar 1.0.
    tts_speed: float | None = None
    #: Bo'lakning maqsadli davomiyligi (soniya). Hujjat jonli qo'ng'iroq
    #: uchun 1.0-2.0 ni tavsiya qiladi: 3.0 da birinchi bo'lak butun
    #: jumlani qamrab, TTFB ~5x sekinlashadi; 10.0 da streaming umuman
    #: yo'qoladi. Server 0.5-10 dan tashqarisiga 422 beradi.
    tts_chunk_sec: float = 1.5
    #: Matn chegarasi - ZAXIRA to'siq. Asosiy qisqartirish frontendda, GAP
    #: chegarasida bo'ladi (`VoicePanel.vue`, `SPEAK_LIMIT`); bu yerda esa
    #: so'z chegarasida kesiladi va xato qaytarilmaydi.
    #:
    #: 600 EDI va bu O'QILADIGAN JAVOBNI YARMIDA KESARDI: o'sha qiymat matn
    #: foydalanuvchining bitta AYTGAN GAPI bo'lgan davrdan qolgan edi, javob
    #: esa tabiatan uzunroq (jonli misol: mehnat ta'tili bo'yicha 6 bandli
    #: javob 1016 belgi).
    #:
    #: 3000 jonli o'lchovga asoslangan: server 5000 belgini ham qabul qiladi,
    #: va birinchi bayt UZUNLIKDAN QAT'I NAZAR ~1.37 s da keladi, ya'ni uzun
    #: matn kechikish qo'shmaydi. Narxi boshqa joyda: 3000 belgi ~198 s ovoz
    #: bo'lib, oqim ~41 s davom etadi va shu vaqt ichida `tts_max_concurrent`
    #: slotlaridan bittasini ushlab turadi.
    tts_max_chars: int = 3000

    # --- Uyg'otish so'zi jurnali ---
    #: "Salom Venera" urinishlari yozib boriladi: audio + transkript + qaror.
    #: Muammoni TAXMIN bilan emas, dalil bilan tuzatish uchun - qaysi
    #: aytilish qanday transkribe qilingani ko'rinmasa, moslashtirgichni
    #: sozlash ko'r-ko'rona bo'ladi.
    #:
    #: OVOZ YOZUVLARI SHAXSIY MA'LUMOT. Papka `.gitignore` da. Kerak
    #: bo'lmaganda `WAKE_LOG_ENABLED=false` bilan butunlay o'chiriladi.
    wake_log_enabled: bool = True
    wake_log_dir: Path = BASE_DIR / "data" / "wake"
    #: Shuncha audiodan ortig'i o'chiriladi (eng eskisidan). JSONL qatorlari
    #: qoladi - ular kichkina va statistika uchun kerak.
    wake_log_max_files: int = 500

    # --- HR Assistant (savolga javob beradigan yuqori xizmat) ---
    #: BRB-TECH HR Assistant API: hujjatlar bo'yicha RAG + HRM connector,
    #: bitta `/api/chat/stream` endpointi ortida. Venera uchun BU YAGONA
    #: kirish nuqtasi - HRM ga to'g'ridan-to'g'ri borilmaydi.
    hrm_assistant_base_url: str = "http://10.10.50.4:8080"
    #: ILOVANING kredensiallari (`X-Client-Id` / `X-Client-Secret`). Usiz
    #: xizmat 401 qaytaradi, shuning uchun savol umuman yuborilmaydi -
    #: `/api/health` esa buni ogohlantirish sifatida ko'rsatadi.
    #:
    #: SIR BRAUZERGA HECH QACHON BERILMAYDI: frontend faqat Venera'ning
    #: o'z `/api/v1/chat/stream` yo'liga boradi.
    hrm_assistant_client_id: str = ""
    hrm_assistant_client_secret: str = ""
    #: Kadrlar ORASIDAGI eng uzun tanaffus, butun javob vaqti emas: LLM
    #: javobi bir daqiqadan oshishi normal, bir daqiqa JIMLIK - nosozlik.
    hrm_assistant_timeout: int = 120
    #: Yuqorida bitta LLM turadi. Bu bizning ulushimiz - oshsa xizmatga
    #: bormasdan 503 qaytariladi.
    hrm_assistant_max_concurrent: int = 4
    #: Undan uzun savol yuborilmaydi. Chegara xizmatda ham bor, lekin
    #: 100 KB matnni tarmoqqa chiqarib, keyin rad javobini olish ma'nosiz.
    hrm_assistant_max_question_chars: int = 2000

    #: HRM sessiya token'i (JWT) - JONLI HRM ma'lumoti uchun.
    #:
    #: VAQTINCHALIK YECHIM VA BITTA MUHIM OQIBATI BOR. Xizmat bu token'ni
    #: "so'rayotgan odamning O'Z sessiyasi" deb qabul qiladi va hujjatda
    #: aytilganidek, token bilan "men / I" degani TOKEN EGASI hisoblanadi.
    #: Ya'ni bu yerda bitta umumiy token turgan paytda Venera'ning HAR
    #: QANDAY foydalanuvchisi "men bugun kechikdimmi?" deb so'rasa, javob
    #: token EGASI haqida bo'ladi. Shuning uchun `/api/health` bu token
    #: qo'yilganini ogohlantirish sifatida ko'rsatadi.
    #:
    #: Bo'sh bo'lsa jonli HRM savollari `auth_missing` bilan qaytadi, va bu
    #: TO'G'RI xatti-harakat: boshqa odamning huquqi bilan javob berishdan
    #: ko'ra javob bermaslik yaxshi. Hujjatlar bo'yicha savollar ishlaydi.
    #:
    #: Muddati tugagach xizmat yana `auth_missing` qaytaradi - token'ni
    #: `.env` da yangilash kerak. Doimiy yechim: foydalanuvchi o'z HRM
    #: hisobi bilan kirsin va token sessiyadan olinsin.
    #:
    #: BU QIYMAT ISHGA TUSHGANDAGISI. Kod uni TO'G'RIDAN-TO'G'RI
    #: ISHLATMAYDI - `hrm_token_now()` ga qara: token bir necha daqiqada
    #: muddati tugaydi, ya'ni har almashtirishda xizmatni qayta ishga
    #: tushirish ayni vaqtdagi javob oqimlarini kesib yuborardi.
    hrm_token: str = ""
    #: CRM sessiya token'i - HRM tokeni bilan AYNI MANTIQDA.
    #:
    #: Yuqoridagi yordamchi 2026-09-14 dan boshlab CRM ni ham biladi va
    #: `tokens` xaritasida qaysi platforma kerak bo'lsa o'shanisini
    #: ishlatadi. Ikkisi MUSTAQIL: CRM tokenisiz CRM savollari
    #: `auth_missing` qaytaradi ("CRM tizimiga kiring"), HRM savollari
    #: esa ishlab turadi - va teskarisi.
    crm_token: str = ""

    # --- CRM sessiyasi (avtomatik) ---
    #: CRM ning asosiy manzili. BO'SH bo'lsa avtomatik sessiya O'CHIQ va
    #: yuqoridagi qo'lda yozilgan `crm_token` ishlatiladi.
    crm_base_url: str = ""
    #: AGENTNING O'Z CRM hisobi - odamning hisobi EMAS.
    #:
    #: Hujjat talabi, va sababi ikkita: hisobning roli agent nimani
    #: o'qib-o'zgartira olishini belgilaydi (ya'ni zarar doirasi kichik
    #: qoladi), va audit jurnali halol bo'ladi - aks holda agentning har
    #: bir harakati kimning parolini olgan bo'lsa o'sha odamga yozilardi.
    crm_username: str = ""
    #: Parol FAQAT birinchi login uchun. Undan keyin `refresh_token`
    #: ishlatiladi va parolga qaytilmaydi.
    crm_password: str = ""
    crm_timeout: float = 10.0
    #: `refresh_token` shu faylda turadi. `data/` gitignore'da, fayl 600
    #: huquq bilan atomik yoziladi.
    #:
    #: BU DOIMIY KREDENSIAL: `exp` i yo'q, 30 kun ishlatilmasa bekor
    #: bo'ladi. Uni qo'lga kiritgan odam cheksiz muddat agent nomidan
    #: token yasay oladi - paroldan farqi yo'q.
    crm_refresh_file: Path = BASE_DIR / "data" / "crm" / "refresh_token"

    # --- Ulanishlar: foydalanuvchining O'Z HRM / CRM hisobi ---
    #: Yuqoridagi agent sessiyasidan FARQI: u yerda bitta umumiy hisob, bu
    #: yerda har bir odam "+" menyusidan o'z logini va paroli bilan kiradi
    #: va chatga uning O'Z tokeni beriladi. Mantiq:
    #: `services/integrations/connectors.py`.
    #:
    #: HRM API manzili (`POST /api/authenticate`). BO'SH bo'lsa HRM ulanishi
    #: o'chiq - menyuda "serverda sozlanmagan" ko'rinadi.
    hrm_base_url: str = ""
    hrm_timeout: float = 10.0
    #: HRM tokeni 10 SOAT yashaydi va refresh'i yo'q. Muddati shundan KAM
    #: qolganda u yuqoridagi xizmatga BERILMAYDI va odam qayta kiradi:
    #: savol-javob bir necha daqiqa cho'zilishi mumkin, token esa javob
    #: OXIRIGACHA yaroqli turishi kerak.
    hrm_token_margin: float = 300.0
    #: CRM uchun Keycloak token manzili - parol bilan kirish shu yerda
    #: (`grant_type=password`, `offline_access`). BO'SH bo'lsa CRM
    #: ulanishi o'chiq. `crm_base_url` (yuqorida) esa yangilash uchun
    #: kerak: `POST /api/auth/refresh` CRM ning o'zida.
    crm_idp_token_url: str = ""
    crm_client_id: str = "crm-client"
    #: Ilova siri - FAQAT `.env` da, brauzerga hech qachon bermaydi.
    crm_client_secret: str = ""
    #: CRM `access_token` 300 SEKUND yashaydi. Muddati shundan kam qolgan
    #: bo'lsa savol oldidan `refresh_token` bilan yangilanadi - ya'ni token
    #: olinganidan keyin ko'pi bilan 120 s qayta ishlatiladi, undan keyin
    #: har savolga yangisi. Savol-javob 2-3 daqiqa cho'zilishi mumkin,
    #: shuning uchun 90 s emas (agent sessiyasidagi kabi) - 180 s.
    crm_token_margin: float = 180.0
    #: Foydalanuvchilar tokenlari (HRM token, CRM refresh_token) shu faylda.
    #: `data/` gitignore'da, fayl 600 huquq bilan atomik yoziladi. PAROL BU
    #: YERDA YO'Q - u faqat login so'roviga ketadi.
    connectors_file: Path = BASE_DIR / "data" / "connectors" / "tokens.json"

    # --- CORS ---
    #: Bo'sh bo'lsa CORS o'chirilgan: frontend nginx orqali BIR XIL originda
    #: turadi (`/api` proxy), ya'ni CORS umuman kerak emas. Faqat frontend
    #: boshqa domenda ishlasa to'ldiriladi.
    cors_origins: list[str] = []

    @property
    def secret_is_default(self) -> bool:
        return self.secret_key == "dev-only-insecure-change-me"


settings = Settings()


#: `.env` fayli - `hrm_token_now()` shundan o'qiydi.
_ENV_FILE = BASE_DIR / ".env"

#: Oxirgi o'qish, kalit bo'yicha: {kalit: (fayl belgisi, qiymat)}.
#: Belgi - `mtime_ns` va hajm.
_token_cache: dict[str, tuple[object, str]] = {}
_token_lock = threading.Lock()


def _env_token(key: str, fallback: str = "") -> str:
    """`.env` dan bitta token - HAR SAFAR yangi qiymat bilan.

    NEGA SOZLAMA OBYEKTIDAN EMAS. HRM sessiyasi bir necha daqiqada muddati
    tugaydi, ya'ni token tez-tez almashtiriladi. `Settings` esa faylni
    FAQAT import paytida o'qiydi - yangi qiymatni ko'rish uchun xizmatni
    qayta ishga tushirish kerak bo'lardi, va har necha daqiqada restart
    ayni vaqtda oqib turgan javoblarni kesib yuborardi.

    Diskka odatda BORILMAYDI: fayl o'zgargani `stat` bilan aniqlanadi
    (`mtime_ns` + hajm), o'zgarmagan bo'lsa keshdagi qiymat qaytadi.

    Fayl o'qilmasa - eng oxirgi MA'LUM qiymat qaytadi, bo'sh satr emas:
    tahrirlash o'rtasida qolgan fayl tufayli ishlab turgan chat to'xtab
    qolmasligi kerak. Kalitning O'ZI yo'q bo'lsa esa bo'sh satr qaytadi,
    chunki bu "token olib tashlandi" degani bo'lishi mumkin.
    """
    cached = _token_cache.get(key)
    try:
        info = _ENV_FILE.stat()
        mark: object = (info.st_mtime_ns, info.st_size)
    except OSError:
        return cached[1] if cached else fallback
    if cached is not None and mark == cached[0]:
        return cached[1]
    with _token_lock:
        # Ikkinchi tekshiruv: qulf kutilayotganda boshqa ip allaqachon
        # o'qib bo'lgan bo'lishi mumkin.
        cached = _token_cache.get(key)
        if cached is not None and mark == cached[0]:
            return cached[1]
        value = _read_env_value(_ENV_FILE, key)
        resolved = value if value is not None else ""
        _token_cache[key] = (mark, resolved)
        return resolved


def hrm_token_now() -> str:
    """HRM sessiya token'i."""
    return _env_token("hrm_token", settings.hrm_token)


def crm_token_now() -> str:
    """CRM sessiya token'i."""
    return _env_token("crm_token", settings.crm_token)


#: `tokens` xaritasidagi nomlar -> `.env` kalitlari. Yuqoridagi xizmat
#: tanimagan nomni E'TIBORSIZ qoldiradi, ya'ni yangi platforma qo'shilsa
#: shu yerga bitta qator yetadi.
_PLATFORMS = (("hrm", "hrm_token"), ("crm", "crm_token"))


def platform_tokens() -> dict[str, str]:
    """Odamning BARCHA platforma token'lari - `tokens` xaritasi uchun.

    Hujjat talabi: "Send every token the user has. The assistant decides
    per question which platform it needs." Ya'ni tanlashga urinmaymiz -
    savol HRM haqidami yoki CRM haqidami, buni yuqoridagi xizmat o'zi
    hal qiladi.

    BO'SH token YUBORILMAYDI. Bo'sh satr yuborilsa xizmat uni "sessiya
    bor, lekin yaroqsiz" deb qabul qilishi mumkin edi; yo'qligi esa
    aniq `auth_missing` beradi va foydalanuvchi tushunarli xabar oladi
    ("CRM tizimiga kiring").
    """
    return {name: token for name, key in _PLATFORMS if (token := _env_token(key))}


def _read_env_value(path: Path, key: str) -> str | None:
    """`.env` dan bitta kalitni o'qiydi. Butun faylni qayta tahlil
    QILMAYDI: bizga faqat shu kalit kerak, qolganini o'zgartirish esa
    ishlab turgan sozlamani kutilmaganda almashtirib qo'yardi.

    `pydantic-settings` kabi harf registriga qaramaydi, va qiymat
    atrofidagi qo'shtirnoqni oladi.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    wanted = key.lower()
    found: str | None = None
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip().lower() != wanted:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        # Oxirgi mos qator ustun - `.env` da takroriy kalit bo'lsa muhit
        # o'zgaruvchilari ham shunday ishlaydi.
        found = value
    return found
