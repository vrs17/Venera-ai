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

APP_NAME = "Barno AI Assistant"
# Qayta nomlashdan oldingi yorliq nomlari (0.3.0 gacha) - yangilanishda olib tashlanadi.
LEGACY_APP_NAMES = ("Venera AI Assistant",)
EXE_NAME = "Venera.exe"
PROCESS_NAME = "Venera.exe"
PAYLOAD_DIR = "payload"
UPDATE_URL_FILE = "update_url.txt"   # build paytida yopishtiriladi (build_setup.ps1 -UpdateUrl)

CREATE_NO_WINDOW = 0x08000000

# Ranglar packages/design-tokens/tokens.json dagi `desktop` bo'limidan ko'chirilgan.
# Bu yerda ataylab QATTIQ yozilgan: o'rnatuvchi (Setup.exe) o'zi o'rnatayotgan
# ilovaning paketiga bog'liq bo'lmasligi kerak - u alohida .exe sifatida yig'iladi.
# tokens.json o'zgarsa, shu bloknni ham yangilang.
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


def legacy_start_menu_shortcuts() -> list[Path]:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return [Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{name}.lnk"
            for name in LEGACY_APP_NAMES]


def legacy_desktop_shortcuts() -> list[Path]:
    profile = os.environ.get("USERPROFILE") or str(Path.home())
    return [Path(profile) / "Desktop" / f"{name}.lnk" for name in LEGACY_APP_NAMES]


def _remove_quietly(items) -> None:
    for item in items:
        try:
            item.unlink(missing_ok=True)
        except OSError:
            pass


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


def setup_log(message: str) -> None:
    """O'rnatish qadamlarini faylga yozadi.

    Jim rejimda (`/S`) `print()` hech qayerga chiqmaydi - o'rnatuvchini
    yangilanish xizmati konsolsiz ishga tushiradi. Shu sababli muvaffaqiyatsiz
    o'rnatish MUTLAQO ko'rinmas edi: ilova eski versiyada qolar, foydalanuvchi
    esa nima bo'lganini bilmasdi. Endi sabab shu faylda qoladi.
    """
    try:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        folder = Path(base) / "Venera" / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with (folder / "setup.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp}  {message}\n")
    except Exception:  # noqa: BLE001 - log yozilmasligi o'rnatishni to'xtatmaydi
        pass


def app_is_running() -> bool:
    code, output = run_hidden(
        ["tasklist", "/FI", f"IMAGENAME eq {PROCESS_NAME}", "/NH"], timeout=20
    )
    if code != 0:
        return False          # tasklist ishlamasa - to'xtagan deb hisoblaymiz
    return PROCESS_NAME.lower() in output.lower()


def stop_running_app(timeout: float = 30.0) -> bool:
    """Ishlayotgan ilovani to'xtatadi va HAQIQATAN to'xtaganini kutadi.

    Avval `time.sleep(1.0)` bilan cheklanardi. Bu yetarli emas: tray ikonkasi,
    tkinter oynasi va bir nechta thread bilan ishlayotgan jarayon o'ldirilgandan
    keyin ham Windows .exe faylining qulfini bir necha soniya ushlab turadi.
    Natijada keyingi `rmtree` va `copytree` muvaffaqiyatsiz tugardi - lekin xato
    jim rejimda ko'rinmasdi va eski versiya joyida qolardi.

    True - jarayon yo'q; False - qulflab turibdi (o'rnatishni boshlash mumkin emas).
    """
    setup_log("Ishlayotgan nusxa to'xtatilmoqda...")
    if not app_is_running():
        setup_log("Ilova ishlamayapti - to'xtatish shart emas")
        return True

    # `/T` (butun daraxtni o'ldirish) ATAYLAB ISHLATILMAYDI. Yangilanish
    # xizmati o'rnatuvchini Venera.exe ning FARZANDI sifatida ishga tushiradi,
    # ya'ni `/T` ilova bilan birga o'rnatuvchining o'zini ham o'ldiradi -
    # fayllar almashmasdan, jimgina. `/IM` esa faqat nomi mos jarayonlarni
    # oladi, o'rnatuvchining nomi boshqacha (Venera-...-Setup-x.y.z.exe).
    run_hidden(["taskkill", "/IM", PROCESS_NAME, "/F"], timeout=20)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.5)
        if not app_is_running():
            # Jarayon ro'yxatdan yo'qoldi, lekin fayl deskriptorlari bir lahza
            # kechroq bo'shaydi - shuning uchun qisqa nafas.
            time.sleep(1.5)
            setup_log("Ishlayotgan nusxa to'xtatildi")
            return True

    setup_log(f"XATO: {PROCESS_NAME} {timeout:.0f} soniyada to'xtamadi")
    return False


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
                "Publisher": "Barno",
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

    setup_log(f"--- O'rnatish boshlandi -> {target}")

    report(5, "Ishlayotgan nusxa to'xtatilmoqda...")
    if not stop_running_app():
        # MUHIM: shu yerda to'xtaymiz. Pastdagi rmtree ishlayotgan ilovaning
        # papkasini o'chiradi - agar jarayon hali tirik bo'lsa, natija yarim
        # o'chirilgan, ishlamaydigan o'rnatma bo'lardi. Eski versiya butun
        # qolgani buzilganidan yaxshiroq.
        return False, ("Ilova to'xtamadi - o'rnatish bekor qilindi. "
                       "Barnoni qo'lda yoping va qaytadan urinib ko'ring.")

    report(15, "Eski versiya tozalanmoqda...")
    if target.exists():
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                shutil.rmtree(target)
                last_error = None
                break
            except OSError as exc:
                last_error = exc
                time.sleep(1.0 + attempt)
        if last_error is not None:
            # Ilgari bu xato JIMGINA e'tiborsiz qoldirilardi va kod pastga
            # o'tib ketardi. Papka yarim o'chirilgan bo'lishi mumkin, ya'ni
            # keyingi nusxalash ham ishonchsiz - shuning uchun aniq aytamiz.
            setup_log(f"XATO: eski papka o'chmadi: {last_error}")
            return False, f"Eski versiya o'chirilmadi: {last_error}"

    report(25, "Fayllar ko'chirilmoqda...")
    copy_error: Exception | None = None
    for attempt in range(3):
        try:
            target.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target, dirs_exist_ok=True)
            copy_error = None
            break
        except Exception as exc:  # noqa: BLE001
            copy_error = exc
            time.sleep(1.0 + attempt)
    if copy_error is not None:
        setup_log(f"XATO: fayllar ko'chirilmadi: {copy_error}")
        return False, f"Fayllar ko'chirilmadi: {copy_error}"

    if not exe.exists():
        setup_log("XATO: ko'chirishdan keyin Venera.exe topilmadi")
        return False, "Ko'chirishdan keyin dastur fayli topilmadi"
    setup_log("Fayllar ko'chirildi")

    report(60, "Yorliqlar yaratilmoqda...")
    # Nom o'zgardi (Venera -> Barno): eski yorliq dublikat bo'lib qolmasin. Eskisi
    # faqat yangisi HAQIQATAN yaratilgandan keyin o'chiriladi; ish stolida eski
    # yorliq bo'lgan bo'lsa (jim yangilanishda desktop=False), o'rniga yangisi qo'yiladi.
    legacy_desktop = [p for p in legacy_desktop_shortcuts() if p.exists()]
    if make_shortcut(start_menu_shortcut(), exe):
        _remove_quietly(legacy_start_menu_shortcuts())
    if desktop or legacy_desktop:
        if make_shortcut(desktop_shortcut(), exe):
            _remove_quietly(legacy_desktop)

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
    setup_log(f"O'rnatish tugadi: {exe}")
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
    setup_log(f"Jim rejim natijasi: {'OK' if ok else 'XATO'} - {detail}")
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
