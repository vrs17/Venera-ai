"""macOS adapteri.

Muhim tanlovlar:
  * Dastur ochish - `open -a`. LaunchServices'ga murojaat qiladi, shuning uchun
    to'liq yo'l kerak emas: "Safari" ham, "/Applications/Safari.app" ham ishlaydi.
  * Ovoz - AppleScript (`set volume`). CoreAudio'ga to'g'ridan-to'g'ri ulanish
    pyobjc talab qiladi; osascript esa tizimda doim bor va qo'shimcha ruxsat
    so'ramaydi.
  * Ekran qulflash - avval CGSession -suspend (ruxsatsiz ishlaydi), u topilmasa
    System Events orqali Ctrl+Cmd+Q. Ikkinchisi Accessibility ruxsatini talab
    qiladi, shuning uchun u ZAXIRA, birinchi tanlov emas.
  * Qulflanganini aniqlash - Quartz.CGSessionCopyCurrentDictionary(). pyobjc
    bo'lmasa "qulflanmagan" deb hisoblanadi (Windows adapteridagi kabi: aniqlab
    bo'lmasa mikrofon yopilmaydi).
  * Bitta nusxa - fayl ustida fcntl.flock. Windows'dagi nomlangan mutexning
    Unix'dagi ekvivalenti: jarayon o'lsa qulf yadro tomonidan bo'shatiladi,
    ya'ni "eskirgan lock fayli" muammosi yo'q.
  * Avtostart - ~/Library/LaunchAgents/uz.venera.assistant.plist. `launchctl
    bootstrap` (macOS 10.11+) ishlatiladi, eski `load` esa zaxira.

Ruxsatlar (birinchi ishga tushganda tizim so'raydi, .app Info.plist'da izohi bor):
  * Mikrofon        - NSMicrophoneUsageDescription
  * Ekran yozib olish - screencapture uchun, macOS 10.15+
  * Accessibility   - faqat zaxira qulflash yo'li uchun
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .. import APP_DISPLAY_NAME, paths
from .base import AutostartStatus, OSAdapter

log = logging.getLogger(__name__)

BUNDLE_ID = "uz.venera.assistant"
LAUNCH_AGENT_LABEL = BUNDLE_ID
LOCK_NAME = "venera.lock"

# CGSession - Apple'ning "Fast User Switching" yordamchisi. Yo'li o'zgarmagan
# (10.6 dan 15 gacha), lekin mavjudligini har safar tekshiramiz.
CGSESSION = (
    "/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/CGSession"
)

_TIMEOUT = 15


def _run(args: list[str], timeout: int = _TIMEOUT) -> tuple[int, str]:
    """Buyruqni ishga tushiradi. (kod, chiqish) qaytaradi, hech qachon otmaydi."""
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return proc.returncode, output
    except FileNotFoundError:
        return 127, f"{args[0]} topilmadi"
    except subprocess.TimeoutExpired:
        return 124, f"{args[0]} javob bermadi"
    except Exception as exc:  # noqa: BLE001 - adapter hech qachon ilovani yiqitmasin
        return 1, str(exc)


def _osascript(script: str) -> tuple[int, str]:
    return _run(["osascript", "-e", script])


class MacAdapter(OSAdapter):
    name = "macos"

    def __init__(self) -> None:
        self._lock_handle = None
        self._notifier = None

    # --- dasturlar -----------------------------------------------------------

    def launch(self, targets: list[str]) -> bool:
        """`open -a` bilan sinaydi; maqsad yo'lga o'xshasa to'g'ridan-to'g'ri `open`."""
        for target in targets:
            if not target:
                continue
            # Yo'l ko'rinishidagi maqsad (/Applications/X.app, ~/bin/y) - `-a` siz.
            looks_like_path = target.startswith(("/", "~", ".")) or target.endswith(".app")
            expanded = os.path.expanduser(target)
            args = ["open", expanded] if looks_like_path else ["open", "-a", target]
            code, output = _run(args)
            if code == 0:
                log.info("Ochildi: %s", target)
                return True
            log.info("Ochilmadi: %s (%s)", target, output or f"kod {code}")
        return False

    def open_url(self, url: str) -> bool:
        if not url:
            return False
        # Windows adapteri bilan bir xil qoida: sxemasi yo'q bo'lsa https qo'shamiz.
        if not url.startswith(("http://", "https://", "mailto:", "x-apple.systempreferences:")):
            url = "https://" + url
        code, output = _run(["open", url])
        if code == 0:
            return True
        log.warning("URL ochilmadi (%s): %s", url, output)
        return False

    # --- ovoz ----------------------------------------------------------------

    def get_volume(self) -> int | None:
        code, output = _osascript("output volume of (get volume settings)")
        if code != 0:
            log.warning("Ovoz darajasi o'qilmadi: %s", output)
            return None
        # Chiqish qurilmasi bo'lmasa AppleScript "missing value" qaytaradi.
        try:
            return max(0, min(100, int(output.strip())))
        except ValueError:
            log.warning("Ovoz darajasi tanilmadi: %r", output)
            return None

    def set_volume(self, percent: int) -> bool:
        value = max(0, min(100, int(percent)))
        code, output = _osascript(f"set volume output volume {value}")
        if code != 0:
            log.warning("Ovoz o'rnatilmadi: %s", output)
            return False
        # Windows adapteri bilan bir xil xatti-harakat: 0 dan katta qiymat
        # qo'yilganda ovoz o'chirilgan bo'lsa, uni yoqamiz - aks holda
        # "ovozni 50 qil" buyrug'i jimlikda qoladi.
        if value > 0:
            _osascript("set volume output muted false")
        return True

    def set_mute(self, muted: bool) -> bool:
        code, output = _osascript(f"set volume output muted {'true' if muted else 'false'}")
        if code != 0:
            log.warning("Ovoz o'chirilmadi/yoqilmadi: %s", output)
            return False
        return True

    # --- ekran ---------------------------------------------------------------

    def lock_workstation(self) -> bool:
        if Path(CGSESSION).exists():
            code, output = _run([CGSESSION, "-suspend"])
            if code == 0:
                return True
            log.info("CGSession ishlamadi (%s), System Events sinaladi", output or code)
        # Zaxira: Ctrl+Cmd+Q. Accessibility ruxsati bo'lmasa osascript -1743 beradi.
        code, output = _osascript(
            'tell application "System Events" to keystroke "q" using {control down, command down}'
        )
        if code == 0:
            return True
        if "-1743" in output or "not allowed" in output.lower():
            log.warning(
                "Ekran qulflanmadi: Accessibility ruxsati yo'q. "
                "System Settings > Privacy & Security > Accessibility da %s ga ruxsat bering",
                APP_DISPLAY_NAME,
            )
        else:
            log.warning("Ekran qulflanmadi: %s", output)
        return False

    def screenshot(self, destination: Path) -> Path | None:
        """`screencapture -x` - jimgina (chertish tovushisiz), butun ekran.

        macOS 10.15+ da Screen Recording ruxsati kerak. Ruxsat bo'lmasa buyruq
        0 qaytaradi, lekin fayl bo'sh yoki faqat oboy bo'ladi - shuning uchun
        natijani hajmi bilan ham tekshiramiz.
        """
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("Skrinshot papkasi yaratilmadi: %s", exc)
            return None

        code, output = _run(["screencapture", "-x", str(destination)])
        if code != 0:
            log.warning("Skrinshot olinmadi: %s", output or f"kod {code}")
            return None
        if not destination.exists() or destination.stat().st_size == 0:
            log.warning(
                "Skrinshot bo'sh chiqdi - Screen Recording ruxsati berilmagan bo'lishi mumkin "
                "(System Settings > Privacy & Security > Screen Recording)"
            )
            return None
        log.info("Skrinshot saqlandi: %s", destination)
        return destination

    def is_session_locked(self) -> bool:
        """Quartz orqali. pyobjc bo'lmasa - "qulflanmagan" deb hisoblaymiz.

        Windows adapteridagi bilan bir xil ehtiyotkorlik: aniqlab bo'lmasa
        mikrofonni yopmaymiz, chunki noto'g'ri "qulflangan" javobi ilovani
        butunlay kar qilib qo'yadi.
        """
        try:
            from Quartz import CGSessionCopyCurrentDictionary  # type: ignore[import-not-found]

            session = CGSessionCopyCurrentDictionary()
            if not session:
                return False
            return bool(session.get("CGSSessionScreenIsLocked", False))
        except Exception:  # noqa: BLE001 - pyobjc yo'q yoki API o'zgargan
            return False

    # --- bitta nusxa ---------------------------------------------------------

    def acquire_single_instance(self, key: str = LOCK_NAME) -> bool:
        """Fayl ustidagi eksklyuziv flock.

        Handle ATAYLAB obyektda saqlanadi: fayl yopilsa qulf ham yo'qoladi.
        Jarayon qanday tugasa ham (crash, kill -9) yadro qulfni bo'shatadi,
        shuning uchun qotib qolgan lock fayli muammosi yo'q.
        """
        try:
            import fcntl

            lock_dir = paths.state_dir()
            lock_dir.mkdir(parents=True, exist_ok=True)
            handle = open(lock_dir / key, "w")  # noqa: SIM115 - umr bo'yi ochiq turishi shart
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                handle.close()
                log.warning("Ilova allaqachon ishlayapti")
                return False
            handle.write(str(os.getpid()))
            handle.flush()
            self._lock_handle = handle
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("Bitta nusxa tekshiruvi ishlamadi: %s", exc)
            return True

    # --- avtostart -----------------------------------------------------------

    @staticmethod
    def _agent_path() -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"

    @staticmethod
    def _split_command(command: str) -> list[str]:
        """`"/path/Venera" -m venera` -> ["/path/Venera", "-m", "venera"].

        app.autostart_command() yo'lni qo'shtirnoq ichida beradi (Windows uchun
        shart). shlex bu qo'shtirnoqlarni to'g'ri yechadi.
        """
        import shlex

        try:
            parts = shlex.split(command)
        except ValueError:
            parts = [command]
        return [p for p in parts if p]

    def _build_plist(self, command: str) -> str:
        from xml.sax.saxutils import escape

        args = self._split_command(command)
        program_args = "\n".join(f"    <string>{escape(a)}</string>" for a in args)
        # Loglar LaunchAgent'ning o'z chiqishini yozadi (Python traceback'lari
        # ilova logiga tushmasdan yo'qolmasligi uchun).
        err_log = paths.log_dir() / "launchagent.log"

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{escape(LAUNCH_AGENT_LABEL)}</string>
  <key>ProgramArguments</key>
  <array>
{program_args}
  </array>
  <key>RunAtLoad</key>
  <true/>
  <!-- KeepAlive.SuccessfulExit=false: foydalanuvchi menyudan chiqsa qayta
       ochilmasin, lekin crash bo'lsa ko'tarilsin. Windows'dagi
       RestartOnFailure bilan bir xil maqsad. -->
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>ProcessType</key>
  <string>Interactive</string>
  <key>StandardErrorPath</key>
  <string>{escape(str(err_log))}</string>
  <key>StandardOutPath</key>
  <string>{escape(str(err_log))}</string>
</dict>
</plist>
"""

    @staticmethod
    def _launchctl(args: list[str]) -> tuple[int, str]:
        return _run(["launchctl", *args])

    def _domain(self) -> str:
        return f"gui/{os.getuid()}"

    def autostart_status(self) -> AutostartStatus:
        agent = self._agent_path()
        if not agent.is_file():
            return AutostartStatus(False, "LaunchAgent topilmadi")
        code, _ = self._launchctl(["print", f"{self._domain()}/{LAUNCH_AGENT_LABEL}"])
        if code == 0:
            return AutostartStatus(True, "launchd'ga yuklangan")
        # Plist bor, lekin yuklanmagan: keyingi kirishda baribir ishga tushadi.
        return AutostartStatus(True, "plist mavjud, joriy sessiyada yuklanmagan")

    def autostart_install(self, command: str) -> AutostartStatus:
        agent = self._agent_path()
        try:
            agent.parent.mkdir(parents=True, exist_ok=True)
            paths.log_dir().mkdir(parents=True, exist_ok=True)
            agent.write_text(self._build_plist(command), encoding="utf-8")
        except OSError as exc:
            log.warning("LaunchAgent yozilmadi: %s", exc)
            return AutostartStatus(False, str(exc))

        # Qayta o'rnatishda avval eskisini chiqaramiz, aks holda bootstrap
        # "Load failed: 5: Input/output error" beradi.
        self._launchctl(["bootout", f"{self._domain()}/{LAUNCH_AGENT_LABEL}"])
        code, output = self._launchctl(["bootstrap", self._domain(), str(agent)])
        if code != 0:
            # macOS 10.10 va undan eski tizimlar uchun zaxira.
            code, output = self._launchctl(["load", "-w", str(agent)])
        if code == 0:
            log.info("Avtostart yoqildi: %s", command)
            return AutostartStatus(True, "yoqildi")
        # Plist joyida - keyingi kirishda launchd uni baribir o'qiydi.
        log.warning("LaunchAgent yozildi, lekin yuklanmadi: %s", output)
        return AutostartStatus(True, f"plist yozildi, yuklanmadi: {output}")

    def autostart_remove(self) -> AutostartStatus:
        agent = self._agent_path()
        self._launchctl(["bootout", f"{self._domain()}/{LAUNCH_AGENT_LABEL}"])
        self._launchctl(["unload", "-w", str(agent)])
        try:
            agent.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("LaunchAgent o'chirilmadi: %s", exc)
            return AutostartStatus(True, str(exc))
        log.info("Avtostart o'chirildi")
        return AutostartStatus(False, "o'chirildi")

    # --- xabarlar ------------------------------------------------------------

    def notify(self, title: str, message: str) -> None:
        """Tray notifier bo'lsa - o'sha, bo'lmasa macOS Notification Center.

        Tray hali qurilmagan paytdagi xabarlar (masalan ishga tushish xatosi)
        Windows'da yo'qoladi; macOS'da esa osascript doim tayyor, shuning uchun
        ularni ko'rsatib qo'yamiz.
        """
        if getattr(self, "_notifier", None) is not None:
            super().notify(title, message)
            return
        safe_title = title.replace('"', "'")
        safe_message = message.replace('"', "'")
        _osascript(f'display notification "{safe_message}" with title "{safe_title}"')

    # --- diagnostika ---------------------------------------------------------

    def describe(self) -> dict[str, str]:
        status = self.autostart_status()
        return {
            "adapter": self.name,
            "autostart": "yoqilgan" if status.installed else f"yo'q ({status.detail})",
            "session_locked": str(self.is_session_locked()),
            "volume": str(self.get_volume()),
            "executable": sys.executable,
            "launch_agent": str(self._agent_path()),
            "screencapture": "bor" if shutil.which("screencapture") else "yo'q",
        }


def describe_permissions() -> str:
    """`--check` uchun: qaysi ruxsatlar kerakligini bir qatorda tushuntiradi."""
    return json.dumps(
        {
            "microphone": "ovozni eshitish uchun (majburiy)",
            "screen_recording": "skrinshot uchun",
            "accessibility": "faqat zaxira ekran qulflash yo'li uchun",
        },
        ensure_ascii=False,
    )
