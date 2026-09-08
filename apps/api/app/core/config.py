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
    stt_timeout: float = 30.0
    stt_attempts: int = 3
    #: Yuklash chegarasi. Router o'zi ham 25 MB da to'xtatadi, lekin biz
    #: undan OLDIN to'xtatamiz: aks holda katta fayl butun tarmoqni bosib
    #: o'tib, faqat oxirida rad etilardi.
    stt_max_upload_mb: float = 10.0

    # --- CORS ---
    #: Bo'sh bo'lsa CORS o'chirilgan: frontend nginx orqali BIR XIL originda
    #: turadi (`/api` proxy), ya'ni CORS umuman kerak emas. Faqat frontend
    #: boshqa domenda ishlasa to'ldiriladi.
    cors_origins: list[str] = []

    @property
    def secret_is_default(self) -> bool:
        return self.secret_key == "dev-only-insecure-change-me"


settings = Settings()
