"""Savolni tasniflaydigan model (Ollama Cloud, `gemma4:31b`).

VAZIFASI - FAQAT TANLASH. Model savolni o'qiydi va ikkita yorliq qaytaradi:
mavzu (`kechikish`, `tatil`, `hujjat`...) va ohang (`shoshilinch`, `oddiy`).
Shu yorliqlar bo'yicha OLDINDAN yozilgan va sintez qilingan kutish ovozi
tanlanadi (`services/hold.py`).

NEGA GAP YOZMAYDI. Avvalgi versiyada model kutish gapini o'zi yozardi, va
eng katta xavf to'qima edi: "foydalanuvchini ushlab tur" deb so'ralgan model
javobning o'zini to'qib qo'yishga moyil ("Mahmud uch marta kechikkan"), odam
esa buni HRM ma'lumoti deb qabul qiladi. Yorliq tanlaganda bu imkonsiz:
ro'yxatdan tashqari javob tuzilma bilan rad etiladi, gap esa hech qachon
model qo'lidan chiqmaydi.

O'LCHANGAN (2026-09-22, jonli, 9 ta o'zbekcha savol): mediana 0.77 s, mavzu
8/9, ohang 9/9. Yagona xato xavfsiz tomonga ketdi - noma'lum mavzu (`DVSIB`)
`umumiy` ga tushdi.

XATO HECH QACHON KO'TARILMAYDI. Model yiqilsa, sekinlashsa yoki g'alati javob
bersa - `None`, va chaqiruvchi kalit so'z jadvalini ishlatadi. Kutish ovozi
qulaylik: uning yo'qligi javobni buzmasligi kerak.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import urllib.error
import urllib.request

from ..analytics.meter import begin
from ..hold import MAVZULAR, OHANGLAR

log = logging.getLogger(__name__)

#: Kalitni jurnaldan va xato matnidan olib tashlash uchun.
_KEY_LIKE = re.compile(r"\b[0-9a-f]{32}\.[A-Za-z0-9_-]{16,}\b")

_PROMPT = """Sen foydalanuvchi savolini TASNIFLAYSAN. Savolga JAVOB BERMAYSAN.

MAVZU yorliqlari:
{mavzular}

OHANG yorliqlari:
- shoshilinch: buyruq ohangi, shoshayotgan odam ("tezda", "darhol", undov)
- oddiy: odatiy savol

Ishonchsiz bo'lsang: mavzu uchun "umumiy", ohang uchun "oddiy".
FAQAT shu shaklda javob ber, boshqa hech narsa yozma: mavzu|ohang"""


def _safe(text: str, key: str = "") -> str:
    """Kalitni matndan olib tashlaydi."""
    if not text:
        return ""
    if key:
        text = text.replace(key, "<key>")
    return _KEY_LIKE.sub("<key>", text)


def parse_label(raw: str) -> tuple[str, str] | None:
    """Model chiqishidan (mavzu, ohang). Yaroqsiz bo'lsa `None`.

    QAT'IY: faqat ma'lum yorliqlar. Model "kechikish|oddiy" o'rniga gap
    yozib yuborsa yoki yangi yorliq o'ylab topsa - rad etiladi va zahira
    ishlaydi. Ohang yaroqsiz, mavzu to'g'ri bo'lsa - ohang "oddiy": shoshilmagan
    odamga qo'pol gapirish xushmuomala gapirishdan yomonroq.
    """
    text = (raw or "").strip().lower()
    # Model ba'zan qo'shtirnoq yoki nuqta qo'shadi.
    text = text.strip("\"'`.").replace(" ", "")
    if "\n" in text or not text:
        return None
    qismlar = text.split("|")
    mavzu = qismlar[0]
    if mavzu not in MAVZULAR:
        return None
    ohang = qismlar[1] if len(qismlar) > 1 else ""
    if ohang not in OHANGLAR:
        ohang = "oddiy"
    return mavzu, ohang


class HoldClassifier:
    """`gemma4:31b` bilan savolni mavzu va ohang bo'yicha tasniflaydi."""

    def __init__(self, base_url: str, api_key: str, model: str, *,
                 timeout: float = 2.5, max_concurrent: int = 4) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self._api_key = api_key or ""
        self.model = model
        self.timeout = timeout
        # Har ovozli savol uchun bitta chaqiruv. Navbat KUTILMAYDI (pastda):
        # kechikkan tasnif ma'nosiz, zahira esa bir zumda ishlaydi.
        self._slots = threading.BoundedSemaphore(max(1, max_concurrent))

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self._api_key and self.model)

    def classify(self, question: str) -> tuple[str, str] | None:
        """(mavzu, ohang) yoki `None`. HECH QACHON xato ko'tarmaydi."""
        if not self.configured or not (question or "").strip():
            return None
        if not self._slots.acquire(blocking=False):
            log.debug("Tasnif: navbat to'la, zahira ishlatiladi")
            return None
        try:
            return self._ask(question)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            log.info("Tasnif bo'lmadi (%s) - zahira ishlatiladi",
                     _safe(str(exc), self._api_key))
            return None
        finally:
            self._slots.release()

    def _ask(self, question: str) -> tuple[str, str] | None:
        mavzular = "\n".join(f"- {nom}: {tavsif}" for nom, tavsif in MAVZULAR.items())
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": _PROMPT.format(mavzular=mavzular)},
                # Savol QISQARTIRILADI: uzun savol modelni chalg'itadi va
                # vaqtni yeydi, mavzu esa birinchi jumlalarda aniq bo'ladi.
                {"role": "user", "content": question.strip()[:400]},
            ],
            "stream": False,
            "options": {
                # Tasnif - ijod emas: bir xil savolga har safar bir xil yorliq.
                "temperature": 0.0,
                # "kechikish|shoshilinch" ~6 token. Qat'iy chegara: model gap
                # yozishga kirishsa ham tez to'xtaydi va rad etiladi.
                "num_predict": 12,
            },
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/chat", data=body, method="POST",
            headers={"Authorization": f"Bearer {self._api_key}",
                     "Content-Type": "application/json"},
        )
        # Hisob: PULLIK tashqi xizmat - har chaqiruv, xatosi bilan. Kalit
        # xato matniga tushmaydi (`_safe`, keyin `redact` ham).
        call = begin("ollama", "classify", units={"chars": len(question.strip()[:400])})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # 401/402/429 - sozlama yoki hisob. Jim: zahira ishlaydi, holat
            # `/api/health/detail` da ko'rinadi.
            log.info("Tasnif: Ollama %s - zahira ishlatiladi", exc.code)
            call.end("error", http_status=exc.code, error=f"Ollama HTTP {exc.code}")
            return None
        except BaseException as exc:
            call.end("error", error=f"{type(exc).__name__}: {_safe(str(exc), self._api_key)}")
            raise
        call.end("ok", http_status=200)
        raw = ((payload.get("message") or {}).get("content")) or ""
        label = parse_label(raw)
        if label is None and raw.strip():
            # Model ko'rsatmani buzdi. Ko'p bo'lsa - prompt qayta yozilishi
            # kerak degan signal.
            log.info("Tasnif rad etildi (ro'yxatda yo'q, %d belgi)", len(raw))
        return label
