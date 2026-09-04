"""macOS `say` orqali ovoz sintezi (Step 1 zaxira yechimi, SapiTts ning egizagi).

MUHIM: `say` da o'zbek ovozi yo'q. Rus yoki ingliz ovozi o'zbekcha matnni
noto'g'ri talaffuz qiladi - bu KUTILGAN holat, xuddi Windows'dagi SAPI kabi.
Step 4 da on-prem TTS almashtiradi va ovoz to'g'ri bo'ladi.

Texnik tanlovlar:
  * `say` to'g'ridan-to'g'ri dinamikka emas, vaqtinchalik WAV faylga yozadi.
    Shunda natija AudioClip bo'lib chiqadi va boshqa TTS'lar bilan bir xil
    yo'l bilan (bekor qilinadigan player orqali) ijro etiladi - SapiTts
    SpMemoryStream'ga yozgani bilan aynan bir xil sabab.
  * Thread pool KERAK EMAS: `say` alohida jarayon, shuning uchun asyncio
    subprocess bilan chinakam asinxron chaqiramiz. COM'dagi kabi thread'ga
    bog'lanish muammosi yo'q.
  * Ovoz balandligi `say` da flag sifatida yo'q, shuning uchun PCM ni
    o'zimiz masshtablaymiz - SAPI'ning Volume=0..100 xatti-harakati saqlanadi.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

from ..audio.wav import decode_wav
from .base import AudioClip, HealthStatus, TtsEngine

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
# LEI16@16000 - little-endian int16, 16 kHz, mono. decode_wav aynan shuni kutadi.
DATA_FORMAT = f"LEI16@{SAMPLE_RATE}"
# `say` juda uzun matnda osilib qolmasin.
SAY_TIMEOUT = 60

# SAPI Rate (-10..10) ni `say -r` (so'z/daqiqa) ga o'girish. 175 - macOS default.
BASE_WPM = 175


def _rate_to_wpm(rate: int) -> int:
    """-10 -> ~88 wpm, 0 -> 175, +10 -> ~262. Chegaralar `say` uchun xavfsiz."""
    return max(80, min(300, int(round(BASE_WPM * (1 + rate / 20.0)))))


class SayTts(TtsEngine):
    name = "say"

    def __init__(self, voice_hint: str | None = None, rate: int = 0, volume: int = 100) -> None:
        self.voice_hint = voice_hint
        self.rate = max(-10, min(10, rate))
        self.volume = max(0, min(100, volume))
        self._voices: list[str] = []
        self._voice: str | None = None
        self._init_error: str | None = None
        self._resolved = False

    # --- ovozlar ro'yxati -----------------------------------------------------

    async def _run(self, args: list[str], timeout: int = 15) -> tuple[int, bytes, bytes]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return 127, b"", b"say topilmadi"
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return 124, b"", b"say javob bermadi"
        return proc.returncode or 0, out, err

    async def _resolve_voice(self) -> None:
        """Ovozlar ro'yxatini bir marta o'qiydi va voice_hint'ga mos kelganini tanlaydi."""
        if self._resolved:
            return
        self._resolved = True

        if sys.platform != "darwin":
            self._init_error = "say faqat macOS'da mavjud"
            return
        if shutil.which("say") is None:
            self._init_error = "say buyrug'i topilmadi"
            return

        code, out, err = await self._run(["say", "-v", "?"])
        if code != 0:
            self._init_error = (err or out).decode("utf-8", "replace").strip() or f"kod {code}"
            log.warning("say ovozlar ro'yxatini bermadi: %s", self._init_error)
            return

        # Format: "Milena              ru_RU    # Здравствуйте, меня зовут Milena."
        for line in out.decode("utf-8", "replace").splitlines():
            line = line.strip()
            if not line:
                continue
            name = line.split("#", 1)[0].strip()
            # Oxirgi bo'lak - til kodi (ru_RU), undan oldingisi ovoz nomi.
            parts = name.rsplit(None, 1)
            if len(parts) == 2:
                self._voices.append(f"{parts[0].strip()} ({parts[1]})")
                if self.voice_hint and self.voice_hint.lower() in name.lower():
                    self._voice = parts[0].strip()

        if self._voice:
            log.info("say ovozi tanlandi: %s", self._voice)
        elif self.voice_hint:
            log.warning("'%s' ovozi topilmadi, default ishlatiladi. Mavjud: %s",
                        self.voice_hint, self._voices[:5])

    # --- sintez ---------------------------------------------------------------

    def _apply_volume(self, pcm: np.ndarray) -> np.ndarray:
        """SAPI'dagi Volume=0..100 bilan bir xil natija."""
        if self.volume >= 100:
            return pcm
        scaled = pcm.astype(np.float32) * (self.volume / 100.0)
        return np.clip(scaled, -32768, 32767).astype(np.int16)

    async def synthesize(self, text: str) -> AudioClip:
        if not text.strip():
            return AudioClip.silence()
        await self._resolve_voice()
        if self._init_error:
            return AudioClip.silence()

        # NamedTemporaryFile emas: `say` faylni O'ZI yaratadi, ochiq deskriptor
        # bilan to'qnashmasligi uchun faqat nomni band qilamiz.
        with tempfile.TemporaryDirectory(prefix="venera-tts-") as tmp:
            out_path = Path(tmp) / "speech.wav"
            args = ["say", "-o", str(out_path), "--file-format=WAVE",
                    f"--data-format={DATA_FORMAT}", "-r", str(_rate_to_wpm(self.rate))]
            if self._voice:
                args += ["-v", self._voice]
            # `--` : matn tire bilan boshlansa flag deb o'qilmasin.
            args += ["--", text]

            code, _, err = await self._run(args, timeout=SAY_TIMEOUT)
            if code != 0:
                log.warning("say sintez qilmadi: %s",
                            err.decode("utf-8", "replace").strip() or f"kod {code}")
                return AudioClip.silence()
            if not out_path.exists() or out_path.stat().st_size == 0:
                log.warning("say bo'sh fayl qaytardi")
                return AudioClip.silence()

            try:
                raw = out_path.read_bytes()
                pcm, rate = decode_wav(raw)
            except Exception as exc:  # noqa: BLE001 - buzuq WAV ilovani yiqitmasin
                log.warning("say chiqargan WAV o'qilmadi: %s", exc)
                return AudioClip.silence()

        return AudioClip(pcm=self._apply_volume(pcm), sample_rate=rate)

    async def list_voices(self) -> list[str]:
        await self._resolve_voice()
        return list(self._voices)

    async def health(self) -> HealthStatus:
        voices = await self.list_voices()
        if self._init_error:
            return HealthStatus(False, self._init_error)
        return HealthStatus(True, f"{len(voices)} ta ovoz: {', '.join(voices[:3])}")

    async def close(self) -> None:
        return None
