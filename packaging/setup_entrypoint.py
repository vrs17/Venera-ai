"""Venera AI Assistant - o'rnatuvchi (Setup.exe).

Bitta fayl: ilovaning to'liq nusxasi shu exe ichiga joylashtirilgan.
Foydalanuvchi ikki marta bosadi, "O'rnatish" ni tanlaydi - tamom.
Maqsad kompyuterda Python, .NET yoki boshqa dastur kerak emas.

Administrator huquqi TALAB QILINMAYDI: hamma narsa joriy foydalanuvchi
papkalariga yoziladi (%LOCALAPPDATA%, %APPDATA%, HKCU).

Jim rejim (IT bo'limi uchun ommaviy tarqatishda):
    Venera-AI-Assistant-Setup.exe /S
    Venera-AI-Assistant-Setup.exe /S /NOAUTOSTART /NOLAUNCH
    Venera-AI-Assistant-Setup.exe /S /URL=\\\\fileserver\\venera\\assistant\\version.json

`/URL=` bayrog'i yangilanish manbasini config.yaml ga yozadi, shunda keyingi
versiyalar avtomatik topiladi va foydalanuvchi bir bosishda yangilaydi.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

APP_NAME = "Venera AI Assistant"
EXE_NAME = "Venera.exe"
PROCESS_NAME = "Venera.exe"
PAYLOAD_DIR = "payload"
UPDATE_URL_FILE = "update_url.txt"   # build paytida yopishtiriladi (build_setup.ps1 -UpdateUrl)

CREATE_NO_WINDOW = 0x08000000

BG = "#12151B"
FG = "#E8EAED"
MUTED = "#8A9099"
ACCENT = "#2F6FED"
FIELD = "#1C2029"
OK_COLOR = "#1FAD66"
ERR_COLOR = "#D64545"


# --- yordamchi funksiyalar ----------------------------------------------------

def payload_path() -> Path:
    """Exe ichiga joylashtirilgan ilova papkasi."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / PAYLOAD_DIR


def baked_update_url() -> str:
    """Build paytida yopishtirilgan yangilanish manzili.

    `build_setup.ps1 -UpdateUrl "..."` bilan berilsa, shu o'rnatuvchidan
    o'rnatilgan HAR BIR kompyuter yangilanishni o'zi topadigan bo'ladi -
    foydalanuvchi hech narsa sozlamaydi, IT ham har bir mashinaga bormaydi.
    """
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    try:
        candidate = base / UPDATE_URL_FILE
        if candidate.exists():
            # Har qatorda bitta manzil: birinchisi asosiy, qolganlari zaxira.
            lines = [
                line.strip() for line in candidate.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            return "|".join(lines)
    except OSError:
        pass
    return ""


def payload_version() -> str:
    """Ilova versiyasi payload ichidagi VERSION faylidan o'qiladi.

    Shu tufayli o'rnatuvchida versiya ikkinchi marta yozilmaydi va
    "Ilovalar" ro'yxatida doim to'g'ri raqam ko'rinadi.
    """
    for candidate in (
        payload_path() / "_internal" / "venera" / "resources" / "VERSION",
        payload_path() / "_internal" / "resources" / "VERSION",
    ):
        try:
            if candidate.exists():
                value = candidate.read_text(encoding="utf-8").strip()
                if value:
                    return value
        except OSError:
            continue
    return "0.0.0"


APP_VERSION = None   # birinchi murojaatda payload'dan o'qiladi


def app_version() -> str:
    global APP_VERSION
    if APP_VERSION is None:
        APP_VERSION = payload_version()
    return APP_VERSION


def install_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Programs" / "Venera"


def start_menu_shortcut() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{APP_NAME}.lnk"


def desktop_shortcut() -> Path:
    profile = os.environ.get("USERPROFILE") or str(Path.home())
    return Path(profile) / "Desktop" / f"{APP_NAME}.lnk"


def run_hidden(args: list[str], timeout: float = 60.0) -> tuple[int, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                                creationflags=CREATE_NO_WINDOW)
        return result.returncode, ((result.stdout or "") + (result.stderr or "")).strip()
    except FileNotFoundError:
        return 1, f"topilmadi: {args[0]}"
    except subprocess.TimeoutExpired:
        return 1, "javob bermadi"
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def stop_running_app() -> None:
    run_hidden(["taskkill", "/IM", PROCESS_NAME, "/F"], timeout=20)
    time.sleep(1.0)


def make_shortcut(target: Path, exe: Path) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    script = (
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{target}');"
        f"$s.TargetPath = '{exe}';"
        f"$s.WorkingDirectory = '{exe.parent}';"
        f"$s.IconLocation = '{exe}';"
        f"$s.Description = '{APP_NAME}';"
        f"$s.Save()"
    )
    code, _ = run_hidden(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", script], timeout=45,
    )
    return code == 0


def register_uninstall(exe: Path, size_kb: int) -> bool:
    """Ilova "Parametrlar > Ilovalar" ro'yxatida ko'rinadi va o'sha yerdan o'chiriladi."""
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Venera-AI-Assistant"
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE) as key:
            strings = {
                "DisplayName": APP_NAME,
                "DisplayVersion": app_version(),
                "Publisher": "Venera",
                "InstallLocation": str(exe.parent),
                "DisplayIcon": str(exe),
                "UninstallString": f'"{exe}" --uninstall',
                "QuietUninstallString": f'"{exe}" --uninstall --silent',
            }
            for name, value in strings.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
            winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, int(size_kb))
            winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
        return True
    except Exception:  # noqa: BLE001
        return False


def folder_size_kb(folder: Path) -> int:
    total = 0
    for item in folder.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return max(1, total // 1024)


# --- o'rnatish bosqichlari ----------------------------------------------------

def perform_install(autostart: bool, desktop: bool, launch: bool, report,
                    update_url: str = "") -> tuple[bool, str]:
    """report(foiz, matn) - jarayonni ko'rsatish uchun."""
    source = payload_path()
    if not (source / EXE_NAME).exists():
        return False, f"Ichki fayllar topilmadi: {source}"

    target = install_dir()
    exe = target / EXE_NAME

    report(5, "Ishlayotgan nusxa to'xtatilmoqda...")
    stop_running_app()

    report(15, "Eski versiya tozalanmoqda...")
    if target.exists():
        for attempt in range(3):
            try:
                shutil.rmtree(target)
                break
            except OSError:
                time.sleep(1.0 + attempt)

    report(25, "Fayllar ko'chirilmoqda...")
    try:
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, dirs_exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        return False, f"Fayllar ko'chirilmadi: {exc}"

    if not exe.exists():
        return False, "Ko'chirishdan keyin dastur fayli topilmadi"

    report(60, "Yorliqlar yaratilmoqda...")
    make_shortcut(start_menu_shortcut(), exe)
    if desktop:
        make_shortcut(desktop_shortcut(), exe)

    report(72, "Ro'yxatga qo'shilmoqda...")
    register_uninstall(exe, folder_size_kb(target))

    if not update_url:
        update_url = baked_update_url()

    if update_url:
        report(78, "Yangilanish manzili yozilmoqda...")
        code, output = run_hidden([str(exe), "--set-update-url", update_url], timeout=60)
        if code != 0:
            report(78, f"Yangilanish manzili yozilmadi: {output[:80]}")

    if autostart:
        report(85, "Avtostart yoqilmoqda...")
        code, output = run_hidden([str(exe), "--install-autostart"], timeout=60)
        if code != 0:
            report(85, "Avtostart yoqilmadi - tray menyusidan yoqish mumkin")

    if launch:
        report(95, "Ishga tushirilmoqda...")
        try:
            subprocess.Popen([str(exe)], cwd=str(target), creationflags=0x00000008,
                             close_fds=True)
            time.sleep(2.5)
        except Exception:  # noqa: BLE001
            pass

    report(100, "Tayyor")
    return True, str(exe)


# --- jim rejim ----------------------------------------------------------------

def parse_url_flag(argv: list[str]) -> str:
    """/URL=<manzil> - yangilanish manbasini o'rnatish uchun."""
    for item in argv:
        cleaned = item.lstrip("/-")
        if cleaned.upper().startswith("URL="):
            return cleaned[4:].strip().strip('"')
    return ""


def run_silent(argv: list[str]) -> int:
    flags = {a.upper().lstrip("/-").split("=")[0] for a in argv}
    ok, detail = perform_install(
        autostart="NOAUTOSTART" not in flags,
        desktop="DESKTOP" in flags,
        launch="NOLAUNCH" not in flags,
        report=lambda _p, _t: None,
        update_url=parse_url_flag(argv),
    )
    if sys.stdout is not None:
        print(f"{APP_NAME}: {'o' + chr(39) + 'rnatildi' if ok else 'XATO'} - {detail}")
    return 0 if ok else 1


# --- oynali rejim -------------------------------------------------------------

def run_gui() -> int:
    import queue
    import tkinter as tk
    from tkinter import ttk

    messages: queue.Queue = queue.Queue()
    state = {"done": False, "ok": False, "detail": ""}

    root = tk.Tk()
    root.title(f"{APP_NAME} {app_version()} - o'rnatish")
    root.configure(bg=BG)
    root.geometry("500x340")
    root.resizable(False, False)

    try:
        root.iconbitmap(str(payload_path() / "_internal" / "venera" /
                            "resources" / "icons" / "app.ico"))
    except Exception:  # noqa: BLE001
        pass

    tk.Label(root, text=APP_NAME, bg=BG, fg=FG,
             font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=26, pady=(24, 2))
    tk.Label(root, text=f"Versiya {app_version()}   |   ovozli desktop yordamchi",
             bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=26)

    box = tk.Frame(root, bg=FIELD)
    box.pack(fill="x", padx=26, pady=(16, 10))
    tk.Label(box, text="O'rnatiladigan joy", bg=FIELD, fg=MUTED,
             font=("Segoe UI", 8)).pack(anchor="w", padx=12, pady=(8, 0))
    tk.Label(box, text=str(install_dir()), bg=FIELD, fg=FG,
             font=("Consolas", 8)).pack(anchor="w", padx=12, pady=(1, 9))

    autostart_var = tk.BooleanVar(value=True)
    desktop_var = tk.BooleanVar(value=False)
    options = tk.Frame(root, bg=BG)
    options.pack(fill="x", padx=24)
    for text, var in (("Windows bilan birga ishga tushsin", autostart_var),
                      ("Ish stoliga yorliq qo'yilsin", desktop_var)):
        tk.Checkbutton(options, text=text, variable=var, bg=BG, fg=FG, selectcolor=FIELD,
                       activebackground=BG, activeforeground=FG, font=("Segoe UI", 9),
                       highlightthickness=0, bd=0).pack(anchor="w")

    baked = baked_update_url()
    initial_note = ("Administrator huquqi kerak emas."
                    + ("  Yangilanishlar avtomatik tekshiriladi." if baked else ""))
    status = tk.Label(root, text=initial_note, bg=BG, fg=MUTED,
                      font=("Segoe UI", 9), anchor="w", wraplength=450, justify="left")
    status.pack(fill="x", padx=26, pady=(14, 4))

    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:  # noqa: BLE001
        pass
    style.configure("venera.Horizontal.TProgressbar", troughcolor=FIELD, background=ACCENT,
                    bordercolor=FIELD, lightcolor=ACCENT, darkcolor=ACCENT)
    progress = ttk.Progressbar(root, style="venera.Horizontal.TProgressbar",
                               mode="determinate", maximum=100)
    progress.pack(fill="x", padx=26)

    buttons = tk.Frame(root, bg=BG)
    buttons.pack(fill="x", padx=26, pady=18)

    def close() -> None:
        root.quit()
        root.destroy()

    cancel_button = tk.Button(buttons, text="Bekor qilish", command=close, relief="flat",
                              bg=FIELD, fg=MUTED, font=("Segoe UI", 10), padx=16, pady=6,
                              activebackground="#262B36", activeforeground=FG, cursor="hand2")
    cancel_button.pack(side="right")

    def start() -> None:
        install_button.configure(state="disabled", text="O'rnatilmoqda...")
        for child in options.winfo_children():
            child.configure(state="disabled")

        def worker() -> None:
            ok, detail = perform_install(
                autostart=autostart_var.get(),
                desktop=desktop_var.get(),
                launch=True,
                report=lambda percent, text: messages.put((percent, text)),
                update_url=parse_url_flag(sys.argv[1:]),
            )
            state["done"], state["ok"], state["detail"] = True, ok, detail
            messages.put((100 if ok else 0, None))

        threading.Thread(target=worker, daemon=True).start()

    install_button = tk.Button(buttons, text="O'rnatish", command=start, relief="flat",
                               bg=ACCENT, fg="#FFFFFF", font=("Segoe UI", 10, "bold"),
                               padx=26, pady=6, activebackground="#1E4FBF",
                               activeforeground="#FFFFFF", cursor="hand2")
    install_button.pack(side="right", padx=(0, 10))

    def pump() -> None:
        while True:
            try:
                percent, text = messages.get_nowait()
            except queue.Empty:
                break
            progress["value"] = percent
            if text is not None:
                status.configure(text=text, fg=MUTED)

        if state["done"]:
            if state["ok"]:
                status.configure(
                    text="O'rnatildi. Ilova tray'da (soat yonida) ishlayapti.\n"
                         "Uyg'otish klavishasi tray menyusida ko'rsatilgan.",
                    fg=OK_COLOR,
                )
                install_button.configure(text="Tayyor", state="disabled")
                cancel_button.configure(text="Yopish", fg=FG)
            else:
                status.configure(text=f"Xato: {state['detail']}", fg=ERR_COLOR)
                install_button.configure(text="Qayta urinish", state="normal")
            state["done"] = False
        root.after(80, pump)

    root.after(80, pump)
    root.mainloop()
    return 0


def main() -> int:
    argv = sys.argv[1:]
    silent = any(a.upper().lstrip("/-") in ("S", "SILENT", "QUIET") for a in argv)
    if silent:
        return run_silent(argv)
    try:
        return run_gui()
    except Exception as exc:  # noqa: BLE001 - oyna ochilmasa jim rejimga o'tamiz
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None, f"Oyna ochilmadi ({exc}).\nJim rejimda o'rnatilmoqda.", APP_NAME, 0x30)
        except Exception:  # noqa: BLE001
            pass
        return run_silent(["/S"])


if __name__ == "__main__":
    sys.exit(main())
