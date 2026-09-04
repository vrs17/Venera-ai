"""Windows adapteri.

Muhim tanlovlar:
  * Dastur ochish - ShellExecuteW. `os.startfile`dan farqli o'laroq u App Paths
    registrini o'qiydi, shuning uchun "chrome.exe" to'liq yo'lsiz ham ochiladi.
  * Ekran qulflanganini aniqlash - OpenInputDesktop. Yashirin oyna va WTS
    obunasi kerak emas, oddiy poll yetarli.
  * Bitta nusxa - nomlangan mutex, "Local\\" prefiksi bilan: RDP'dagi har bir
    foydalanuvchi o'z nusxasiga ega bo'ladi.
  * Avtostart - Task Scheduler, logon trigger. ExecutionTimeLimit=PT0S bo'lishi
    SHART: default 72 soat, aks holda ilova uch kundan keyin o'ldiriladi.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path, PureWindowsPath
from xml.sax.saxutils import escape

from .. import APP_DISPLAY_NAME, paths
from .base import AutostartStatus, OSAdapter

log = logging.getLogger(__name__)

TASK_NAME = r"Venera\AI Assistant"
MUTEX_NAME = "Local\\VeneraAIAssistant"

SW_SHOWNORMAL = 1
ERROR_ALREADY_EXISTS = 183
DESKTOP_SWITCHDESKTOP = 0x0100

# CREATE_NO_WINDOW - schtasks chaqirganda konsol oynasi chaqnamasligi uchun
CREATE_NO_WINDOW = 0x08000000


def enable_dpi_awareness() -> None:
    """Toast va dialoglar blur bo'lmasligi uchun. Xato bo'lsa e'tiborsiz."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001 - Win8.1'dan eski tizimlarda shcore yo'q
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


def prepare_comtypes() -> None:
    """comtypes frozen holatda yozib bo'lmaydigan papkaga generatsiya qilmasin."""
    try:
        import comtypes.client

        gen_dir = paths.comtypes_gen_dir()
        gen_dir.mkdir(parents=True, exist_ok=True)
        comtypes.client.gen_dir = str(gen_dir)
    except Exception as exc:  # noqa: BLE001
        log.debug("comtypes gen_dir sozlanmadi: %s", exc)


def _co_initialize() -> None:
    """COM'ni joriy thread uchun ishga tushiradi.

    Executor thread'lari qayta ishlatiladi, shuning uchun CoUninitialize
    chaqirilmaydi - thread umri davomida COM ochiq qolgani to'g'ri.
    """
    try:
        import comtypes

        comtypes.CoInitialize()
    except Exception as exc:  # noqa: BLE001
        log.debug("CoInitialize: %s", exc)


class WindowsAdapter(OSAdapter):
    name = "windows"

    def __init__(self) -> None:
        self._mutex_handle: int | None = None
        self._volume_iface = None
        self._notifier = None

    # --- dasturlar -----------------------------------------------------------

    def _shell_execute(self, target: str, params: str | None = None) -> bool:
        try:
            result = ctypes.windll.shell32.ShellExecuteW(
                None, "open", target, params, None, SW_SHOWNORMAL,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("ShellExecuteW xatosi (%s): %s", target, exc)
            return False
        # ShellExecute 32 dan katta qiymat qaytarsa muvaffaqiyatli
        if result > 32:
            log.info("Ochildi: %s", target)
            return True
        log.info("Ochilmadi: %s (ShellExecute kodi %s)", target, result)
        return False

    def launch(self, targets: list[str]) -> bool:
        for target in targets:
            if not target:
                continue
            if self._shell_execute(target):
                return True
        return False

    def open_url(self, url: str) -> bool:
        if not url:
            return False
        if not url.startswith(("http://", "https://", "ms-settings:", "mailto:")):
            url = "https://" + url
        return self._shell_execute(url)

    # --- ovoz ----------------------------------------------------------------

    def _endpoint_volume(self):
        if self._volume_iface is not None:
            return self._volume_iface
        _co_initialize()
        try:
            from pycaw.pycaw import AudioUtilities

            speakers = AudioUtilities.GetSpeakers()
            # pycaw 2025+ da GetSpeakers() AudioDevice qaytaradi va interfeys
            # tayyor holda `.EndpointVolume` da turadi. Eski versiyalarda esa
            # xom IMMDevice keladi va uni Activate qilish kerak.
            endpoint = getattr(speakers, "EndpointVolume", None)
            if endpoint is not None:
                self._volume_iface = endpoint
            else:
                from ctypes import POINTER, cast

                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import IAudioEndpointVolume

                interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                self._volume_iface = cast(interface, POINTER(IAudioEndpointVolume))
        except Exception as exc:  # noqa: BLE001
            log.warning("Ovoz interfeysi olinmadi: %s", exc)
            self._volume_iface = None
        return self._volume_iface

    def get_volume(self) -> int | None:
        iface = self._endpoint_volume()
        if iface is None:
            return None
        try:
            return int(round(iface.GetMasterVolumeLevelScalar() * 100))
        except Exception as exc:  # noqa: BLE001
            log.warning("Ovoz darajasi o'qilmadi: %s", exc)
            self._volume_iface = None
            return None

    def set_volume(self, percent: int) -> bool:
        iface = self._endpoint_volume()
        if iface is None:
            return False
        value = max(0, min(100, int(percent))) / 100.0
        try:
            iface.SetMasterVolumeLevelScalar(value, None)
            if value > 0:
                iface.SetMute(0, None)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("Ovoz o'rnatilmadi: %s", exc)
            self._volume_iface = None
            return False

    def set_mute(self, muted: bool) -> bool:
        iface = self._endpoint_volume()
        if iface is None:
            return False
        try:
            iface.SetMute(1 if muted else 0, None)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("Ovoz o'chirilmadi/yoqilmadi: %s", exc)
            self._volume_iface = None
            return False

    # --- ekran ---------------------------------------------------------------

    def lock_workstation(self) -> bool:
        try:
            return bool(ctypes.windll.user32.LockWorkStation())
        except Exception as exc:  # noqa: BLE001
            log.warning("Ekran qulflanmadi: %s", exc)
            return False

    def screenshot(self, destination: Path) -> Path | None:
        try:
            from PIL import ImageGrab

            destination.parent.mkdir(parents=True, exist_ok=True)
            image = ImageGrab.grab(all_screens=True)
            image.save(destination, "PNG")
            log.info("Skrinshot saqlandi: %s", destination)
            return destination
        except Exception as exc:  # noqa: BLE001
            log.warning("Skrinshot olinmadi: %s", exc)
            return None

    def is_session_locked(self) -> bool:
        """Kirish deskotpini ocholmasak - ekran qulflangan yoki boshqa desktopdamiz."""
        try:
            user32 = ctypes.windll.user32
            handle = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
            if not handle:
                return True
            user32.CloseDesktop(handle)
            return False
        except Exception:  # noqa: BLE001 - aniqlab bo'lmasa "qulflanmagan" deb hisoblaymiz
            return False

    # --- bitta nusxa ---------------------------------------------------------

    def acquire_single_instance(self, key: str = MUTEX_NAME) -> bool:
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            handle = kernel32.CreateMutexW(None, False, key)
            last_error = kernel32.GetLastError()
            if not handle:
                log.warning("Mutex yaratilmadi (kod %s) - nusxa nazorati o'chirildi", last_error)
                return True
            if last_error == ERROR_ALREADY_EXISTS:
                log.warning("Ilova allaqachon ishlayapti")
                kernel32.CloseHandle(handle)
                return False
            self._mutex_handle = handle  # handle ilova umri davomida ochiq turishi shart
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("Bitta nusxa tekshiruvi ishlamadi: %s", exc)
            return True

    # --- avtostart -----------------------------------------------------------

    @staticmethod
    def _run_schtasks(args: list[str]) -> tuple[int, str]:
        try:
            proc = subprocess.run(
                ["schtasks", *args],
                capture_output=True, text=True, timeout=20,
                creationflags=CREATE_NO_WINDOW,
            )
            output = (proc.stdout or "") + (proc.stderr or "")
            return proc.returncode, output.strip()
        except FileNotFoundError:
            return 1, "schtasks topilmadi"
        except subprocess.TimeoutExpired:
            return 1, "schtasks javob bermadi"
        except Exception as exc:  # noqa: BLE001
            return 1, str(exc)

    def autostart_status(self) -> AutostartStatus:
        code, output = self._run_schtasks(["/Query", "/TN", TASK_NAME])
        if code == 0:
            return AutostartStatus(True, "Task Scheduler'da ro'yxatdan o'tgan")
        return AutostartStatus(False, output.splitlines()[0] if output else "topilmadi")

    def _build_task_xml(self, command: str) -> str:
        user = os.environ.get("USERNAME", "")
        domain = os.environ.get("USERDOMAIN", "")
        user_id = f"{domain}\\{user}" if domain and user else user
        executable = command
        arguments = ""
        if command.startswith('"'):
            end = command.find('"', 1)
            if end > 0:
                executable = command[1:end]
                arguments = command[end + 1 :].strip()
        # PureWindowsPath - Linux'da yozilgan testlar ham to'g'ri natija bersin
        working_dir = str(PureWindowsPath(executable).parent)

        return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{escape(APP_DISPLAY_NAME)} - ovozli yordamchi, tizimga kirganda ishga tushadi</Description>
    <URI>\\{escape(TASK_NAME)}</URI>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(user_id)}</UserId>
      <Delay>PT10S</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user_id)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <DisallowStartOnRemoteAppSession>false</DisallowStartOnRemoteAppSession>
    <UseUnifiedSchedulingEngine>true</UseUnifiedSchedulingEngine>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(executable)}</Command>
      {f"<Arguments>{escape(arguments)}</Arguments>" if arguments else ""}
      <WorkingDirectory>{escape(working_dir)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""

    def autostart_install(self, command: str) -> AutostartStatus:
        xml = self._build_task_xml(command)
        tmp_path = None
        try:
            # schtasks /XML faylni Unicode (UTF-16LE + BOM) sifatida kutadi
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".xml", delete=False, encoding="utf-16",
            ) as handle:
                handle.write(xml)
                tmp_path = handle.name
            code, output = self._run_schtasks(["/Create", "/TN", TASK_NAME, "/XML", tmp_path, "/F"])
            if code == 0:
                log.info("Avtostart yoqildi: %s", command)
                return AutostartStatus(True, "yoqildi")
            log.warning("Avtostart yoqilmadi: %s", output)
            return AutostartStatus(False, output)
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def autostart_remove(self) -> AutostartStatus:
        code, output = self._run_schtasks(["/Delete", "/TN", TASK_NAME, "/F"])
        if code == 0:
            log.info("Avtostart o'chirildi")
            return AutostartStatus(False, "o'chirildi")
        return AutostartStatus(self.autostart_status().installed, output)

    # --- diagnostika ---------------------------------------------------------

    def describe(self) -> dict[str, str]:
        status = self.autostart_status()
        return {
            "adapter": self.name,
            "autostart": "yoqilgan" if status.installed else f"yo'q ({status.detail})",
            "session_locked": str(self.is_session_locked()),
            "volume": str(self.get_volume()),
            "executable": sys.executable,
        }
