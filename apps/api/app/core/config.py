"""Sozlamalar - hammasi muhit o'zgaruvchilaridan.

QOIDA: kodda hech qanday manzil, parol yoki kalit QATTIQ YOZILMAYDI.
Sabab oddiy - dev, test va prod bir xil kod bilan ishlashi kerak, va sir
git'ga tushmasligi kerak.

Qiymatlar tartibi: muhit o'zgaruvchisi -> `.env` fayli -> shu yerdagi default.
Default'lar LOKAL ISHLAB CHIQISH uchun xavfsiz bo'lishi kerak, prod uchun emas.
"""

from __future__ import annotations

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
    #: Matn chegarasi. Uzun matn butun navbatni ushlab turadi, shuning uchun
    #: qisqartiriladi (xato qaytarilmaydi - matn foydalanuvchi aytgan gapi).
    tts_max_chars: int = 600

    # --- CORS ---
    #: Bo'sh bo'lsa CORS o'chirilgan: frontend nginx orqali BIR XIL originda
    #: turadi (`/api` proxy), ya'ni CORS umuman kerak emas. Faqat frontend
    #: boshqa domenda ishlasa to'ldiriladi.
    cors_origins: list[str] = []

    @property
    def secret_is_default(self) -> bool:
        return self.secret_key == "dev-only-insecure-change-me"


settings = Settings()
