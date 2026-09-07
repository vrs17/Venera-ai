"""Buyruq oqimini boshqaruvchi.

Bitta asyncio sikli alohida thread'da ishlaydi. Tashqi thread'lar (hotkey, tray,
oyna) faqat `call_soon_threadsafe` orqali xabar yuboradi.

Bitta navbatdagi ish bitta `asyncio.Task` ichida bajariladi, shuning uchun
bekor qilish uchun bitta `.cancel()` yetarli - qaysi bosqichda bo'lishidan qat'i nazar.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime
from typing import Callable

from .. import events as ev
from .. import paths
from ..actions import registry
from ..actions.base import ActionContext, ActionResult
from ..audio import earcons
from ..audio.wav import encode_wav
from ..engines.base import Activator, AudioClip, LlmEngine, SttEngine, TtsEngine
from ..nlu.intents import Intent, IntentName
from .states import State, label

log = logging.getLogger(__name__)

EventSink = Callable[[object], None]


class Orchestrator:
    """Holat mashinasi: IDLE -> ... -> IDLE."""

    def __init__(
        self,
        config,
        adapter,
        stt: SttEngine,
        llm: LlmEngine,
        tts: TtsEngine,
        activator: Activator,
        capture,
        player,
        context: ActionContext,
        on_event: EventSink | None = None,
        listener=None,
    ) -> None:
        self.config = config
        self.adapter = adapter
        self.stt = stt
        self.llm = llm
        self.tts = tts
        self.activator = activator
        self.capture = capture
        self.player = player
        # Ovoz yo'li. Berilgan bo'lsa buyruq MIKROFONDAN olinadi; None bo'lsa
        # matn oynadan keladi (Step 1 xulqi) - mavjud testlar shunga tayanadi.
        self.listener = listener
        self.ctx = context
        self.on_event = on_event or (lambda _e: None)

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._queue: asyncio.Queue | None = None
        self._task: asyncio.Task | None = None
        self._state = State.IDLE
        self._ready = threading.Event()
        self._stopping = threading.Event()
        self._text_waiter: asyncio.Future | None = None
        self._paused_by_lock = False
        self._last_tick = 0.0
        #: `capture_utterance()` BLOKLOVCHI va boshqa thread'da ishlaydi.
        #: `run_in_executor` future'ini bekor qilish o'sha thread'ni TO'XTATMAYDI -
        #: shuning uchun bekor qilish faqat shu Event orqali yetib boradi.
        self._capture_cancel: threading.Event | None = None

    # --- holat ---------------------------------------------------------------

    @property
    def state(self) -> State:
        return self._state

    @property
    def voice_mode(self) -> bool:
        """Buyruq mikrofondan olinadimi: tinglovchi bor va ishlayaptimi."""
        listener = self.listener
        return bool(listener is not None and getattr(listener, "running", False))

    def _set_state(self, state: State, detail: str = "") -> None:
        if state is self._state:
            return
        self._state = state
        log.info("Holat: %s%s", label(state), f" ({detail})" if detail else "")
        self._emit(ev.StateChanged(state=str(state), detail=detail))

    def _emit(self, event: object) -> None:
        try:
            self.on_event(event)
        except Exception:  # noqa: BLE001 - UI xatosi oqimni to'xtatmasin
            log.exception("Event yuborilmadi")

    # --- hayot sikli ---------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run_loop, name="core", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=10.0):
            log.error("Core sikli ishga tushmadi")

    def stop(self) -> None:
        self._stopping.set()
        loop = self._loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(loop.stop)
        except RuntimeError:
            pass
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._queue = asyncio.Queue()
        loop.create_task(self._consume())
        loop.create_task(self._watchdog())
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            # Kutayotgan tasklarni siklni yopishdan OLDIN bekor qilish shart,
            # aks holda "Event loop is closed" xatolari chiqadi.
            try:
                pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True),
                    )
                loop.run_until_complete(self._shutdown())
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:  # noqa: BLE001
                log.debug("To'xtatishda xato", exc_info=True)
            finally:
                loop.close()
            log.info("Core sikli to'xtadi")

    async def _shutdown(self) -> None:
        for engine in (self.stt, self.llm, self.tts):
            try:
                await engine.close()
            except Exception:  # noqa: BLE001
                pass

    # --- tashqi thread'lardan chaqiriladi ------------------------------------

    def post(self, event: object) -> None:
        """Har qanday thread'dan xavfsiz xabar yuborish."""
        loop, queue = self._loop, self._queue
        if loop is None or queue is None:
            log.debug("Core hali tayyor emas, xabar tashlandi: %r", event)
            return
        try:
            loop.call_soon_threadsafe(queue.put_nowait, event)
        except RuntimeError:
            log.debug("Core to'xtagan, xabar tashlandi: %r", event)

    def activate(self, source: str = "hotkey") -> None:
        self.post(ev.ActivationRequested(source=source))

    def submit_text(self, text: str, source: str = "window") -> None:
        self.post(ev.TextSubmitted(text=text, source=source))

    def cancel(self, source: str = "user") -> None:
        self.post(ev.CancelRequested(source=source))

    # --- xabarlarni qayta ishlash --------------------------------------------

    async def _consume(self) -> None:
        assert self._queue is not None
        while True:
            event = await self._queue.get()
            try:
                await self._handle(event)
            except Exception:  # noqa: BLE001 - bitta xabar butun siklni buzmasin
                log.exception("Xabar qayta ishlanmadi: %r", event)

    async def _handle(self, event: object) -> None:
        if isinstance(event, ev.ActivationRequested):
            await self._on_activation(event)
        elif isinstance(event, ev.TextSubmitted):
            await self._on_text(event)
        elif isinstance(event, ev.CancelRequested):
            await self._on_cancel(event)
        elif isinstance(event, ev.SessionLocked):
            await self._on_lock()
        elif isinstance(event, ev.SessionUnlocked):
            await self._on_unlock()
        elif isinstance(event, ev.ShutdownRequested):
            self.stop()
        else:
            log.debug("E'tiborsiz xabar: %r", event)

    async def _on_activation(self, event: ev.ActivationRequested) -> None:
        if self._state is State.PAUSED:
            log.info("To'xtatilgan holatda aktivatsiya e'tiborsiz qoldirildi")
            return
        if self._task is not None and not self._task.done():
            # Ish ketayotganda qayta uyg'otish = bekor qilish (barge-in)
            log.info("Ish ketayotganda aktivatsiya - joriy buyruq bekor qilindi")
            await self._cancel_task()
            return
        self._task = asyncio.create_task(self._turn(event.source))

    async def _on_text(self, event: ev.TextSubmitted) -> None:
        waiter = self._text_waiter
        if waiter is not None and not waiter.done():
            waiter.set_result(event.text)
            return
        # Aktivatsiyasiz to'g'ridan-to'g'ri matn: aktivatsiya + matn
        if self._task is not None and not self._task.done():
            await self._cancel_task()
        self._task = asyncio.create_task(self._turn(event.source, direct_text=event.text))

    async def _on_cancel(self, event: ev.CancelRequested) -> None:  # noqa: ARG002
        await self._cancel_task()
        self.player.stop()
        self._set_state(State.IDLE, "bekor qilindi")

    async def _cancel_task(self) -> None:
        task, self._task = self._task, None
        waiter, self._text_waiter = self._text_waiter, None
        # Ovoz yozuvi executor thread'ida bloklangan - uni faqat shu Event uzadi.
        cancel, self._capture_cancel = self._capture_cancel, None
        if cancel is not None:
            cancel.set()
        if waiter is not None and not waiter.done():
            waiter.cancel()
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def _on_lock(self) -> None:
        if self._state is State.PAUSED:
            return
        log.info("Ekran qulflandi - mikrofon yopilmoqda")
        await self._cancel_task()
        self.player.stop()
        # Tinglovchi capture'ning yagona iste'molchisi - avval U to'xtaydi,
        # keyin oqim yopiladi. Teskari tartibda thread o'lik navbatni o'qirdi.
        if self.listener is not None:
            self.listener.stop()
        self.capture.stop()
        self._paused_by_lock = True
        self._set_state(State.PAUSED, "ekran qulflangan")

    async def _on_unlock(self) -> None:
        if not self._paused_by_lock:
            return
        log.info("Ekran ochildi - ish davom etadi")
        self._paused_by_lock = False
        # `_on_lock` mikrofonni YOPGAN edi. Uni qayta ochmasak, ekran bir marta
        # qulflangach ilova qayta ishga tushmaguncha kar bo'lib qolardi.
        self._restore_audio()
        self._set_state(State.IDLE, "ekran ochildi")

    def _restore_audio(self) -> None:
        """Qulfdan keyin mikrofonni tiklaydi. Xato butun oqimni to'xtatmasin."""
        try:
            started = bool(self.capture.start())
        except Exception:  # noqa: BLE001
            log.exception("Qulfdan keyin mikrofon ochilmadi")
            return
        if not started:
            log.warning("Qulfdan keyin mikrofon ochilmadi")
            self._emit(ev.Notice(self.ctx.phrases.get("mic_error"), level="warning"))
            return
        listener = self.listener
        if listener is None:
            return
        try:
            if not listener.start():
                log.warning("Qulfdan keyin tinglovchi ishga tushmadi: %s",
                            getattr(listener, "error", "") or "noma'lum sabab")
        except Exception:  # noqa: BLE001
            log.exception("Qulfdan keyin tinglovchi ishga tushmadi")

    # --- bitta buyruq oqimi --------------------------------------------------

    async def _turn(self, source: str, direct_text: str | None = None) -> None:
        started = time.monotonic()
        timeouts = self.config.timeouts
        try:
            if direct_text is None:
                self._set_state(State.ACTIVATED, source)
                await self._play(earcons.wake())
                text = await self._capture_text(timeouts.capturing)
                if text is None:
                    self._set_state(State.IDLE, "vaqt tugadi")
                    await self._play(earcons.tick())
                    return
            else:
                text = direct_text

            text = (text or "").strip()
            if not text:
                self._set_state(State.IDLE, "bo'sh matn")
                await self._play(earcons.tick())
                return

            self._set_state(State.TRANSCRIBING)
            text = await self._transcribe(text)

            self._set_state(State.THINKING)
            intent = await asyncio.wait_for(self.llm.understand(text), timeout=timeouts.thinking)

            if intent.name is IntentName.CANCEL:
                self.player.stop()
                result = ActionResult(self.ctx.phrases.get("cancel_ok"))
                await self._speak(result.spoken)
                self._set_state(State.IDLE, "bekor")
                self._emit(ev.TurnFinished(text=text, intent=str(intent.name),
                                           spoken=result.spoken, ok=True,
                                           elapsed_ms=int((time.monotonic() - started) * 1000)))
                return

            deferred = registry.is_deferred(intent)
            if deferred:
                # Ekran qulflanishidan oldin javob aytiladi, aks holda eshitilmaydi
                self._set_state(State.SPEAKING)
                preview = self._preview_reply(intent)
                await self._speak(preview)

            self._set_state(State.ACTING)
            result = await self._act(intent, timeouts.acting)

            if not deferred:
                self._set_state(State.SPEAKING)
                await self._speak(result.spoken)
                await self._play(earcons.done() if result.ok else earcons.error())

            self._set_state(State.IDLE)
            self._emit(ev.TurnFinished(
                text=text, intent=str(intent.name), spoken=result.spoken, ok=result.ok,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            ))

        except asyncio.CancelledError:
            log.info("Buyruq bekor qilindi")
            self._set_state(State.IDLE, "bekor qilindi")
            raise
        except asyncio.TimeoutError:
            log.warning("Buyruq vaqt chegarasidan oshdi")
            await self._speak(self.ctx.phrases.get("timeout"))
            self._set_state(State.IDLE, "vaqt tugadi")
        except Exception:  # noqa: BLE001
            log.exception("Buyruq bajarilmadi")
            await self._speak(self.ctx.phrases.get("action_failed"))
            await self._play(earcons.error())
            self._set_state(State.IDLE, "xato")
        finally:
            self._text_waiter = None

    def _preview_reply(self, intent: Intent) -> str:
        if intent.name is IntentName.LOCK_SCREEN:
            return self.ctx.phrases.get("lock_ok")
        return ""

    async def _capture_text(self, timeout: float) -> str | None:
        """Buyruqni oladi: tinglovchi bo'lsa mikrofondan, aks holda oynadan.

        Ovoz rejimida STT ham SHU YERDA chaqiriladi, ya'ni qaytadigan qiymat
        allaqachon matn. `_transcribe()` esa `submit_text` yo'qligini ko'rib
        uni o'zgarishsiz o'tkazib yuboradi - `_turn()` tegilmaydi.
        """
        self._set_state(State.CAPTURING)
        if self.voice_mode:
            return await self._capture_voice(timeout)
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future = loop.create_future()
        self._text_waiter = waiter

        if self.config.audio.save_debug_wav and self.capture.running:
            self.capture.drain()

        try:
            return await asyncio.wait_for(waiter, timeout=timeout)
        except asyncio.TimeoutError:
            log.info("Buyruq kiritilmadi (%.0f s)", timeout)
            return None
        finally:
            self._text_waiter = None
            self._save_debug_audio()

    async def _capture_voice(self, timeout: float) -> str | None:
        """Mikrofondan bitta nutq segmentini olib STT ga yuboradi."""
        loop = asyncio.get_running_loop()
        cancel = threading.Event()
        self._capture_cancel = cancel
        try:
            wav = await loop.run_in_executor(
                None, self.listener.capture_utterance, timeout, cancel,
            )
        except asyncio.CancelledError:
            # Future bekor bo'ldi, lekin executor thread'i o'z holicha yozishda
            # davom etardi - uni O'ZIMIZ to'xtatamiz.
            cancel.set()
            raise
        finally:
            if self._capture_cancel is cancel:
                self._capture_cancel = None

        if not wav:
            log.info("Nutq eshitilmadi (%.0f s)", timeout)
            return None

        self._save_debug_wav(wav)
        self._set_state(State.TRANSCRIBING)
        try:
            return await asyncio.wait_for(
                self.stt.transcribe(wav), timeout=self.config.timeouts.stt,
            )
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            log.warning("STT %.0f s ichida javob bermadi", self.config.timeouts.stt)
            self._emit(ev.Notice(self.ctx.phrases.get("stt_error"), level="error"))
            return None
        except Exception as exc:  # noqa: BLE001 - server xatosi buyruqni yiqitsin, ilovani emas
            log.warning("STT xatosi: %s", exc)
            self._emit(ev.Notice(self.ctx.phrases.get("stt_error"), level="error"))
            return None

    def _save_debug_wav(self, wav: bytes) -> None:
        """Ovoz rejimida segment allaqachon WAV - qayta kodlash shart emas."""
        if not self.config.audio.save_debug_wav or not wav:
            return
        try:
            directory = paths.debug_audio_dir()
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / f"{datetime.now():%Y%m%d-%H%M%S}.wav"
            target.write_bytes(wav)
            log.info("Nosozlik uchun audio saqlandi: %s", target)
        except Exception as exc:  # noqa: BLE001
            log.debug("Debug audio saqlanmadi: %s", exc)

    def _save_debug_audio(self) -> None:
        if not self.config.audio.save_debug_wav or not self.capture.running:
            return
        try:
            pcm = self.capture.record(0.0, drain_first=False)
            if pcm.size == 0:
                return
            directory = paths.debug_audio_dir()
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / f"{datetime.now():%Y%m%d-%H%M%S}.wav"
            target.write_bytes(encode_wav(pcm, self.config.audio.sample_rate))
            log.info("Nosozlik uchun audio saqlandi: %s", target)
        except Exception as exc:  # noqa: BLE001
            log.debug("Debug audio saqlanmadi: %s", exc)

    async def _transcribe(self, text: str) -> str:
        """Step 1: mock STT matnni shunchaki qaytaradi. Step 2: haqiqiy server."""
        submit = getattr(self.stt, "submit_text", None)
        if submit is not None:
            submit(text)
            return await self.stt.transcribe(b"")
        return text

    async def _act(self, intent: Intent, timeout: float) -> ActionResult:
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, registry.execute, intent, self.ctx),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            log.warning("Harakat %.0f s ichida tugamadi: %s", timeout, intent.describe())
            return ActionResult.failure(self.ctx.phrases.get("timeout"))

    async def _speak(self, text: str) -> None:
        if not text or not self.config.tts.enabled:
            return
        try:
            clip: AudioClip = await asyncio.wait_for(
                self.tts.synthesize(text), timeout=self.config.timeouts.tts_synth,
            )
        except asyncio.TimeoutError:
            log.warning("TTS sintezi vaqtida ulgurmadi")
            return
        except Exception:  # noqa: BLE001
            log.exception("TTS xatosi")
            return
        if clip.empty:
            return
        await self._play(clip.pcm, clip.sample_rate)

    async def _play(self, pcm, sample_rate: int = 16000) -> None:
        loop = asyncio.get_running_loop()
        # AEC yo'q: dinamikdagi ovoz mikrofonga qaytadi va Venera O'Z javobini
        # keyingi buyruq deb yozib olardi. Ijro davomida tinglovchi karlanadi;
        # `resume()` marker qo'yadi, shuning uchun pre-roll ham o'sha ovozni
        # orqaga qarab tortib kelolmaydi.
        listener = self.listener
        if listener is not None:
            try:
                listener.pause()
            except Exception:  # noqa: BLE001
                log.debug("listener.pause xatosi", exc_info=True)
        try:
            await loop.run_in_executor(
                None, self.player.play, pcm, sample_rate, self.config.timeouts.playback,
            )
        except Exception:  # noqa: BLE001
            log.debug("Ijro xatosi", exc_info=True)
        finally:
            if listener is not None:
                try:
                    listener.resume()
                except Exception:  # noqa: BLE001
                    log.debug("listener.resume xatosi", exc_info=True)

    # --- kuzatuvchi ----------------------------------------------------------

    async def _watchdog(self) -> None:
        """Mikrofon tirikligini va ekran qulfini kuzatadi.

        Uyqudan keyin oqim jimgina o'ladi: callback kelmay qo'yadi, lekin
        xato ham chiqmaydi. Shuning uchun vaqt bo'yicha tekshiriladi.
        Soatning katta sakrashi ham uyqudan uyg'onish belgisi.
        """
        self._last_tick = time.monotonic()
        was_locked = False
        interval = 2.0

        while not self._stopping.is_set():
            await asyncio.sleep(interval)
            now = time.monotonic()
            gap = now - self._last_tick
            self._last_tick = now

            resumed = gap > interval * 5
            if resumed:
                log.info("Vaqt sakradi (%.0f s) - kompyuter uyqudan uyg'ongan bo'lishi mumkin", gap)

            try:
                locked = self.adapter.is_session_locked()
            except Exception:  # noqa: BLE001
                locked = False

            if locked and not was_locked:
                self.post(ev.SessionLocked())
            elif not locked and was_locked:
                self.post(ev.SessionUnlocked())
            was_locked = locked

            if locked or self._state is State.PAUSED:
                continue

            if not self.capture.running:
                continue
            # Ovoz rejimida mikrofonni tinglovchi o'zi kuzatadi va qayta ochadi
            # (`AudioListener._check_alive`). Ikkalasi bir vaqtda `reopen()`
            # chaqirsa oqim ketma-ket ikki marta yopilib-ochilardi.
            if self.voice_mode:
                continue
            if resumed or not self.capture.is_alive(tolerance=max(3.0, interval * 2)):
                log.warning("Mikrofon javob bermayapti (%.1f s) - qayta ochilmoqda",
                            self.capture.seconds_since_audio())
                if not self.capture.reopen():
                    self._emit(ev.Notice(self.ctx.phrases.get("mic_error"), level="warning"))
