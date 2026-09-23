"""Yuqoridagi xizmatlar holati - STT Router va TTS.

NEGA KERAK. Ovoz zanjiri ikkita tashqi xizmatga tayanadi va ular bizdan
mustaqil o'chadi. Bunday holatda ilova o'zi butunlay sog'lom ko'rinadi:
`/api/health` "ok" deydi, uyg'otish so'zi esa jimgina ishlamay qo'yadi.
Aynan shunday bo'ldi - o'zbek STT backend'i (`127.0.0.1:8002`) o'chib qoldi
va buni faqat log'ni ochib ko'rgandagina bilish mumkin edi.

Tekshiruv KESHLANADI: `/api/health` monitoring tomonidan tez-tez
so'raladi, har safar ikkita tashqi so'rov yuborish esa ularni ortiqcha
bezovta qilardi.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

#: Tekshiruv shuncha soniya "yangi" hisoblanadi.
CACHE_SECONDS = 30.0
#: Qisqa: bu monitoring so'rovi, uni kutib turish mumkin emas.
PROBE_TIMEOUT = 2.5


class UpstreamHealth:
    def __init__(self, stt_url: str, tts_url: str) -> None:
        self.stt_url = stt_url.rstrip("/")
        self.tts_url = tts_url.rstrip("/")
        self._lock = threading.Lock()
        self._at = 0.0
        self._cached: dict = {}

    def snapshot(self) -> dict:
        with self._lock:
            if self._cached and time.monotonic() - self._at < CACHE_SECONDS:
                return self._cached
            self._cached = self._probe()
            self._at = time.monotonic()
            return self._cached

    def _probe(self) -> dict:
        stt = self._stt()
        tts = self._get(f"{self.tts_url}/health")
        return {
            "stt": stt,
            "tts": {"status": "ok" if tts and tts.get("model_loaded") else "unreachable"},
        }

    def _stt(self) -> dict:
        payload = self._get(f"{self.stt_url}/health")
        if not payload:
            return {"status": "unreachable"}
        # Router "degraded" deganda QAYSI backend yiqilganini aytish shart:
        # `uz` o'chsa o'zbekcha ovoz butunlay ishlamaydi, `multilang` o'chsa
        # esa faqat ru/en. Ikkalasi bir xil "degraded" bo'lib ko'rinardi.
        broken = [
            name for name, backend in (payload.get("backends") or {}).items()
            if isinstance(backend, dict) and backend.get("status") != "ok"
        ]
        return {
            "status": str(payload.get("status") or "?"),
            "broken": broken,
        }

    def _get(self, url: str) -> dict | None:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(url, timeout=PROBE_TIMEOUT) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else None
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
            log.info("Yuqoridagi xizmat javob bermadi (%s): %s", url, exc)
            return None


def warnings_for(snapshot: dict) -> list[str]:
    """Holatni `/api/health` ogohlantirishlariga aylantiradi.

    Xabar NIMA ISHLAMASLIGINI aytadi, "degraded" demaydi: navbatchi xodim
    "uz backend o'chgan" dan ko'ra "o'zbekcha ovoz ishlamaydi" ni tezroq
    tushunadi va nima qilishni biladi.
    """
    out: list[str] = []
    stt = snapshot.get("stt") or {}
    if stt.get("status") == "unreachable":
        out.append("STT Router javob bermayapti - ovozdan matnga o'girish ishlamaydi")
    elif "uzbek_stt" in (stt.get("broken") or []):
        # Bu xabar 2-variant (GAPI) paydo bo'lgandan keyin YOLG'ON aytishi
        # mumkin: o'zbek yo'llari GAPI ga o'tgan bo'lsa, Router'ning o'zbek
        # backend'i o'chgani ularga TEGMAYDI. Eski matn esa odamni butunlay
        # boshqa joyni tuzatishga yuborardi - ogohlantirishning eng yomon
        # turi shu: aniq, lekin noto'g'ri.
        from ..core.config import settings

        routerda = [
            nomi for nomi, tanlov in (
                ("o'zbekcha ovoz", settings.stt_provider),
                ('"Salom Venera"', settings.stt_wake_provider),
            ) if tanlov != "gapi"
        ]
        if routerda:
            out.append(
                "STT: o'zbek backend'i o'chgan (10.10.50.4 dagi 8002) - "
                f"{' va '.join(routerda)} ISHLAMAYDI, ru/en ishlaydi"
            )
        else:
            out.append(
                "STT: Router'ning o'zbek backend'i o'chgan (10.10.50.4 dagi "
                "8002). O'zbek yo'llari 2-variantda (GAPI), ya'ni hozir "
                "ishlaydi - lekin ZAHIRA yo'q: GAPI yiqilsa uyg'otish ham "
                "to'xtaydi"
            )
    elif stt.get("broken"):
        out.append(f"STT: backend o'chgan ({', '.join(stt['broken'])})")

    if (snapshot.get("tts") or {}).get("status") != "ok":
        out.append("TTS javob bermayapti - ovozli javob ishlamaydi")
    return out
