"""O'rnatish va o'chirish amallari (Windows).

Bu modul ham Setup.exe tomonidan, ham ilovaning o'zi tomonidan ishlatiladi:
Setup o'rnatadi, ilova esa `--uninstall` bilan o'zini o'chira oladi. Shu sababli
"Ilovalar va imkoniyatlar" ro'yxatidagi O'chirish tugmasi ishlaydi.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

APP_ID = "Venera-AI-Assistant"
APP_NAME = "Barno AI Assistant"
#: Qayta nomlashdan oldingi yorliq nomlari - o'chirishda ular ham olib tashlanadi.
LEGACY_APP_NAMES = ("Venera AI Assistant",)
PUBLISHER = "Barno"
UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}"
CREATE_NO_WINDOW = 0x08000000


def install_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Programs" / "Venera"


def start_menu_shortcut() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{APP_NAME}.lnk"


def desktop_shortcut() -> Path:
    profile = os.environ.get("USERPROFILE") or str(Path.home())
    return Path(profile) / "Desktop" / f"{APP_NAME}.lnk"


def legacy_shortcuts() -> list[Path]:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    profile = os.environ.get("USERPROFILE") or str(Path.home())
    found: list[Path] = []
    for name in LEGACY_APP_NAMES:
        found.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{name}.lnk")
        found.append(Path(profile) / "Desktop" / f"{name}.lnk")
    return found


def _powershell(script: str, timeout: float = 30.0) -> bool:
    """PowerShell'ni ko'rinmas oynada ishga tushiradi."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", script],
            capture_output=True, text=True, timeout=timeout, creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            log.warning("PowerShell xatosi: %s", (result.stderr or "").strip()[:200])
        return result.returncode == 0
    except Exception as exc:  # noqa: BLE001
        log.warning("PowerShell ishga tushmadi: %s", exc)
        return False


def create_shortcut(target: Path, exe: Path, description: str = "") -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    script = (
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{target}');"
        f"$s.TargetPath = '{exe}';"
        f"$s.WorkingDirectory = '{exe.parent}';"
        f"$s.IconLocation = '{exe}';"
        f"$s.Description = '{description or APP_NAME}';"
        f"$s.Save()"
    )
    return _powershell(script)


def register_uninstall(exe: Path, version: str, size_kb: int) -> bool:
    """"Ilovalar va imkoniyatlar" ro'yxatiga qo'shadi (faqat joriy foydalanuvchi)."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0,
                                winreg.KEY_WRITE) as key:
            values = {
                "DisplayName": APP_NAME,
                "DisplayVersion": version,
                "Publisher": PUBLISHER,
                "InstallLocation": str(exe.parent),
                "DisplayIcon": str(exe),
                "UninstallString": f'"{exe}" --uninstall',
                "QuietUninstallString": f'"{exe}" --uninstall --silent',
            }
            for name, value in values.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
            winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, int(size_kb))
            winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Uninstall yozuvi qo'shilmadi: %s", exc)
        return False


def unregister_uninstall() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
        return True
    except FileNotFoundError:
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Uninstall yozuvi o'chirilmadi: %s", exc)
        return False


def schedule_self_delete(folder: Path, delay_seconds: int = 4, attempts: int = 12) -> None:
    """Ishlab turgan exe o'z papkasini o'chira olmaydi, shuning uchun kechiktiriladi.

    Ikki tuzoq (ikkalasi ham sinovda aniqlangan):
      * `timeout` buyrug'i konsolsiz jarayonda "Input redirection is not
        supported" xatosi bilan darhol tugaydi - kutish umuman bo'lmaydi;
      * DETACHED_PROCESS bayrog'i bilan PowerShell ishga tushadi, lekin ishlamaydi
        (unga host konsoli kerak). Faqat CREATE_NO_WINDOW to'g'ri ishlaydi va
        jarayon ota-jarayon tugagandan keyin ham davom etadi.
    """
    script = (
        f"Start-Sleep -Seconds {delay_seconds}; "
        f"1..{attempts} | ForEach-Object {{ "
        f"if (Test-Path '{folder}') {{ "
        f"Remove-Item -LiteralPath '{folder}' -Recurse -Force -ErrorAction SilentlyContinue; "
        f"Start-Sleep -Seconds 1 }} }}"
    )
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
             "-ExecutionPolicy", "Bypass", "-Command", script],
            creationflags=CREATE_NO_WINDOW,
            close_fds=True,
        )
        log.info("Papka %s soniyadan keyin o'chiriladi: %s", delay_seconds, folder)
    except Exception as exc:  # noqa: BLE001
        log.warning("Papkani o'chirish rejalashtirilmadi: %s", exc)


def uninstall(keep_settings: bool = False) -> list[str]:
    """Avtostart, yorliqlar, registr yozuvi va fayllarni olib tashlaydi."""
    from . import get_adapter

    steps: list[str] = []
    adapter = get_adapter()

    status = adapter.autostart_remove()
    steps.append("Avtostart o'chirildi" if not status.installed else f"Avtostart: {status.detail}")

    for shortcut in (start_menu_shortcut(), desktop_shortcut(), *legacy_shortcuts()):
        try:
            shortcut.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("Yorliq o'chirilmadi %s: %s", shortcut, exc)
    steps.append("Yorliqlar o'chirildi")

    steps.append("Ro'yxatdan olib tashlandi" if unregister_uninstall() else "Registr yozuvi qoldi")

    if not keep_settings:
        from .. import paths

        for folder in (paths.config_dir(), paths.state_dir()):
            try:
                if folder.exists():
                    schedule_self_delete(folder, delay_seconds=6)
            except Exception:  # noqa: BLE001
                pass
        steps.append("Sozlamalar va loglar o'chiriladi")
    else:
        steps.append("Sozlamalar saqlandi")

    target = install_dir()
    if target.exists():
        schedule_self_delete(target)
        steps.append(f"Fayllar o'chiriladi: {target}")

    return steps
