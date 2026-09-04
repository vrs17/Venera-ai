"""Windows SAPI orqali ovoz sintezi (Step 1 zaxira yechimi).

MUHIM: SAPI'da o'zbek ovozi yo'q. Rus yoki ingliz ovozi o'zbekcha matnni
noto'g'ri talaffuz qiladi - bu KUTILGAN holat. Step 4 da on-prem TTS
almashtiradi va ovoz to'g'ri bo'ladi.

Texnik tanlovlar:
  * `Speak` to'g'ridan-to'g'ri dinamikka emas, SpMemoryStream'ga yoziladi.
    Shunda natija AudioClip bo'lib chiqadi va boshqa TTS'lar bilan bir xil
    yo'l bilan (bekor qilinadigan player orqali) ijro etiladi.
  * Barcha COM chaqiruvlari BITTA ajratilgan thread'da bajariladi.
    COM obyektlari thread'ga bog'langan, boshqa thread'dan chaqirish xato beradi.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from ..audio.wav import decode_wav
from .base import AudioClip, HealthStatus, TtsEngine

log = logging.getLogger(__name__)

# SpeechAudioFormatType.SAFT16kHz16BitMono
SAFT_16KHZ_16BIT_MONO = 18
SAMPLE_RATE = 16000


def _com_init() -> None:
    try:
        import comtypes

        comtypes.CoInitialize()
    except Exception as exc:  # noqa: BLE001
        log.debug("TTS thread'da CoInitialize: %s", exc)


class SapiTts(TtsEngine):
    name = "sapi"

    def __init__(self, voice_hint: str | None = None, rate: int = 0, volume: int = 100) -> None:
        self.voice_hint = voice_hint
        self.rate = max(-10, min(10, rate))
        self.volume = max(0, min(100, volume))
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="tts-com", initializer=_com_init,
        )
        self._voice = None
        self._init_error: str | None = None
        self._voices: list[str] = []

    # --- COM thread ichidagi ishlar -------------------------------------------

    def _ensure_voice(self):
        if self._voice is not None or self._init_error is not None:
            return self._voice
        if sys.platform != "win32":
            self._init_error = "SAPI faqat Windows'da mavjud"
            return None
        try:
            import comtypes.client

            voice = comtypes.client.CreateObject("SAPI.SpVoice")
            tokens = voice.GetVoices()
            self._voices = []
            chosen = None
            for index in range(tokens.Count):
                token = tokens.Item(index)
                description = token.GetDescription()
                self._voices.append(description)
                if self.voice_hint and self.voice_hint.lower() in description.lower():
                    chosen = token
            if chosen is not None:
                voice.Voice = chosen
                log.info("SAPI ovozi tanlandi: %s", chosen.GetDescription())
            elif self.voice_hint:
                log.warning("'%s' ovozi topilmadi, default ishlatiladi. Mavjud: %s",
                            self.voice_hint, self._voices)
            voice.Rate = self.rate
            voice.Volume = self.volume
            self._voice = voice
        except Exception as exc:  # noqa: BLE001
            self._init_error = str(exc)
            log.warning("SAPI ishga tushmadi: %s", exc)
        return self._voice

    def _synthesize_blocking(self, text: str) -> AudioClip:
        voice = self._ensure_voice()
        if voice is None or not text.strip():
            return AudioClip.silence()
        try:
            import comtypes.client

            stream = comtypes.client.CreateObject("SAPI.SpMemoryStream")
            audio_format = comtypes.client.CreateObject("SAPI.SpAudioFormat")
            audio_format.Type = SAFT_16KHZ_16BIT_MONO
            stream.Format = audio_format

            previous = voice.AudioOutputStream
            voice.AudioOutputStream = stream
            try:
                voice.Speak(text)
            finally:
                voice.AudioOutputStream = previous

            raw = bytes(bytearray(stream.GetData()))
        except Exception as exc:  # noqa: BLE001
            log.warning("SAPI sintez qilmadi: %s", exc)
            return AudioClip.silence()

        if not raw:
            return AudioClip.silence()
        # SpMemoryStream odatda xom PCM qaytaradi, lekin RIFF ham bo'lishi mumkin
        if raw[:4] == b"RIFF":
            pcm, rate = decode_wav(raw)
            return AudioClip(pcm=pcm, sample_rate=rate)
        pcm = np.frombuffer(raw[: len(raw) - (len(raw) % 2)], dtype="<i2").copy()
        return AudioClip(pcm=pcm, sample_rate=SAMPLE_RATE)

    def _list_voices_blocking(self) -> list[str]:
        self._ensure_voice()
        return list(self._voices)

    # --- ommaviy asinxron interfeys -------------------------------------------

    async def synthesize(self, text: str) -> AudioClip:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._synthesize_blocking, text)

    async def list_voices(self) -> list[str]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._list_voices_blocking)

    async def health(self) -> HealthStatus:
        voices = await self.list_voices()
        if self._init_error:
            return HealthStatus(False, self._init_error)
        return HealthStatus(True, f"{len(voices)} ta ovoz: {', '.join(voices[:3])}")

    async def close(self) -> None:
        self._executor.shutdown(wait=False)


class NullTts(TtsEngine):
    """Ovoz o'chirilganda (engines.tts: none) yoki SAPI yo'q bo'lganda."""

    name = "none"

    async def synthesize(self, text: str) -> AudioClip:  # noqa: ARG002
        return AudioClip.silence()

    async def health(self) -> HealthStatus:
        return HealthStatus(True, "ovoz o'chirilgan")
