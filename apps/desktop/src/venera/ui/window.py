"""Holat oynasi (tkinter).

Threading qoidasi: butun Tk faqat O'Z thread'ida yashaydi. Tashqi thread'lar
`queue` ga xabar qo'yadi, oyna esa `after(...)` bilan uni o'qiydi. Tk thread-safe
emas, boshqa yo'l bilan chaqirish ilovani tasodifiy yiqitadi.

Step 1 da kiritish maydoni STT o'rnini bosadi: buyruqni yozib Enter bosasiz.
Step 2 da mikrofon ishlaganda maydon qoladi - u nosozlikni tekshirish uchun qulay.
"""

from __future__ import annotations

import logging
import queue
import threading
from datetime import datetime
from typing import Callable

from .. import APP_DISPLAY_NAME, __version__
from .. import i18n
from ..core.states import State, label
from .scene import VoiceScene

# Ranglar packages/design-tokens/tokens.json dan generatsiya qilinadi - shu yerda
# qattiq yozilmaydi, aks holda web bilan bir kuni farq qilib qoladi.
from .tokens import (  # noqa: F401 - BG/FG/... shu modul orqali ham ishlatiladi
    ACCENT,
    ACCENT_ACTIVE,
    BG,
    ERROR,
    FG,
    FIELD_BG,
    HOVER,
    MUTED,
    OK,
    ON_ACCENT,
    UPDATE_BG,
    UPDATE_FG,
    UPDATE_TRACK,
)

log = logging.getLogger(__name__)


class StatusWindow:
    """Alohida thread'da yashaydigan holat oynasi."""

    def __init__(
        self,
        on_submit: Callable[[str], None],
        on_activate: Callable[[], None],
        on_cancel: Callable[[], None],
        hotkey_label: str = "",
        topmost: bool = False,
        on_update: Callable[[], None] | None = None,
    ) -> None:
        self.on_submit = on_submit
        self.on_activate = on_activate
        self.on_cancel = on_cancel
        self.on_update = on_update or (lambda: None)
        self.hotkey_label = hotkey_label
        self.topmost = topmost

        self._commands: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._alive = False
        self._root = None
        self._widgets: dict[str, object] = {}
        self._error: str | None = None

    # --- tashqi interfeys (istalgan thread'dan) -------------------------------

    def start(self, visible: bool = False) -> bool:
        if self._thread is not None:
            return self._alive
        self._thread = threading.Thread(target=self._run, name="ui-window", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=10.0)
        if self._alive and visible:
            self.show()
        return self._alive

    @property
    def alive(self) -> bool:
        return self._alive

    @property
    def error(self) -> str | None:
        return self._error

    def show(self) -> None:
        self._commands.put(("show", None))

    def hide(self) -> None:
        self._commands.put(("hide", None))

    def toggle(self) -> None:
        self._commands.put(("toggle", None))

    def set_state(self, state: str, detail: str = "") -> None:
        self._commands.put(("state", (state, detail)))

    def set_level(self, level: float) -> None:
        self._commands.put(("level", level))

    def log_line(self, text: str, kind: str = "info") -> None:
        self._commands.put(("log", (text, kind)))

    def set_status_note(self, text: str) -> None:
        self._commands.put(("note", text))

    def show_update(self, text: str, button_text: str = "",
                    raise_window: bool = False) -> None:
        """Yuqorida yangilanish paneli chiqaradi.

        `raise_window` ATAYLAB default False: fon tekshiruvi har 6 soatda
        ishlaydi va oynani o'zi ochib, foydalanuvchi ishlayotgan dastur ustiga
        chiqarishi kerak emas. Bunday holatda tray bildirishnomasi va tray
        menyusidagi "Yangi versiya ... - yangilash" yozuvi yetarli, panel esa
        foydalanuvchi oynani o'zi ochganda joyida kutib turadi.

        True faqat foydalanuvchi "Yangilanishni tekshirish" ni BOSGANDA
        beriladi - o'shanda u javob kutayotgan bo'ladi.
        """
        self._commands.put(("update_show", (text, button_text, raise_window)))

    def hide_update(self) -> None:
        self._commands.put(("update_hide", None))

    def set_update_progress(self, done: int, total: int) -> None:
        self._commands.put(("update_progress", (done, total)))

    def stop(self) -> None:
        self._commands.put(("quit", None))
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)

    # --- Tk thread'i ---------------------------------------------------------

    def _run(self) -> None:
        try:
            import tkinter as tk
        except Exception as exc:  # noqa: BLE001
            self._error = f"tkinter mavjud emas: {exc}"
            log.warning("%s", self._error)
            self._ready.set()
            return

        try:
            root = tk.Tk()
        except Exception as exc:  # noqa: BLE001 - displey yo'q (WSL, xizmat)
            self._error = f"oyna ochilmadi: {exc}"
            log.warning("%s", self._error)
            self._ready.set()
            return

        self._root = root
        self._alive = True
        root.title(APP_DISPLAY_NAME)
        root.configure(bg=BG)
        # Sahna 270 px egallaydi - oyna balandligi shunga qarab oshirildi,
        # aks holda `log_frame` (expand=True) siqilib butunlay yo'qolardi.
        root.geometry("520x620")
        root.minsize(460, 540)
        if self.topmost:
            root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build(tk, root)
        root.withdraw()
        self._ready.set()

        root.after(50, self._pump)
        try:
            root.mainloop()
        except Exception:  # noqa: BLE001
            log.exception("Oyna sikli xatosi")
        finally:
            self._alive = False
            scene = self._widgets.get("scene")
            if scene is not None:
                scene.stop()
            log.info("Holat oynasi yopildi")

    def _build(self, tk, root) -> None:
        header = tk.Frame(root, bg=BG)
        header.pack(fill="x", padx=16, pady=(14, 8))

        # Holat nuqtasi YO'Q: sahnadagi orbning o'zi holatni bildiradi va
        # ikkita ko'rsatkich bir-birini takrorlardi.
        state_label = tk.Label(header, text=label(State.IDLE), bg=BG, fg=FG,
                               font=("Segoe UI", 13, "bold"))
        state_label.pack(side="left")

        version_label = tk.Label(header, text=i18n.t("window.version", version=__version__),
                                 bg=BG, fg=MUTED,
                                 font=("Segoe UI", 9))
        version_label.pack(side="right")

        # Yangilanish paneli - odatda yashirin, yangi versiya topilganda ko'rinadi
        update_frame = tk.Frame(root, bg=UPDATE_BG)
        update_row = tk.Frame(update_frame, bg=UPDATE_BG)
        update_row.pack(fill="x", padx=12, pady=9)
        update_label = tk.Label(update_row, text="", bg=UPDATE_BG, fg=UPDATE_FG,
                                font=("Segoe UI", 9), anchor="w", justify="left",
                                wraplength=330)
        update_label.pack(side="left", fill="x", expand=True)
        update_button = tk.Button(update_row, text=i18n.t("window.button.update"),
                                  command=self._on_update,
                                  relief="flat", bg=ACCENT, fg=ON_ACCENT,
                                  font=("Segoe UI", 9, "bold"), padx=14, pady=3,
                                  activebackground=ACCENT_ACTIVE, activeforeground=ON_ACCENT,
                                  cursor="hand2")
        update_button.pack(side="right", padx=(10, 0))
        update_bar = tk.Canvas(update_frame, height=4, bg=UPDATE_TRACK, highlightthickness=0)
        update_progress = update_bar.create_rectangle(0, 0, 0, 4, fill=ACCENT, outline="")

        note = tk.Label(root, text=self._default_note(), bg=BG, fg=MUTED,
                        font=("Segoe UI", 9), anchor="w", justify="left", wraplength=480)
        note.pack(fill="x", padx=16)

        # Ovoz sahnasi: orb holatni, to'lqin esa mikrofon darajasini
        # ko'rsatadi - ikkalasi ham eski 10 px chizig'idan ko'ra o'qiladi.
        scene = VoiceScene(tk, root)
        scene.canvas.pack(fill="x", padx=16, pady=(10, 2))

        entry_frame = tk.Frame(root, bg=BG)
        entry_frame.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(entry_frame, text=i18n.t("window.command"), bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w")
        entry = tk.Entry(entry_frame, bg=FIELD_BG, fg=FG, insertbackground=FG,
                         relief="flat", font=("Segoe UI", 11))
        entry.pack(fill="x", ipady=7, pady=(4, 0))
        entry.bind("<Return>", self._on_submit)
        entry.bind("<Escape>", lambda _e: self.on_cancel())

        buttons = tk.Frame(root, bg=BG)
        buttons.pack(fill="x", padx=16, pady=(8, 6))
        tk.Button(buttons, text=i18n.t("window.button.submit"),
                  command=self._on_submit, relief="flat",
                  bg=ACCENT, fg=ON_ACCENT, font=("Segoe UI", 10, "bold"),
                  activebackground=ACCENT_ACTIVE, activeforeground=ON_ACCENT,
                  padx=16, pady=5, cursor="hand2").pack(side="left")
        tk.Button(buttons, text=i18n.t("window.button.cancel"),
                  command=self.on_cancel, relief="flat",
                  bg=FIELD_BG, fg=FG, font=("Segoe UI", 10),
                  activebackground=HOVER, activeforeground=FG,
                  padx=14, pady=5, cursor="hand2").pack(side="left", padx=(8, 0))
        tk.Button(buttons, text=i18n.t("window.button.hide"),
                  command=self.hide, relief="flat",
                  bg=FIELD_BG, fg=MUTED, font=("Segoe UI", 10),
                  activebackground=HOVER, activeforeground=FG,
                  padx=14, pady=5, cursor="hand2").pack(side="right")

        log_frame = tk.Frame(root, bg=BG)
        log_frame.pack(fill="both", expand=True, padx=16, pady=(6, 14))
        text = tk.Text(log_frame, bg=FIELD_BG, fg=FG, relief="flat", height=8,
                       font=("Consolas", 9), wrap="word", state="disabled",
                       insertbackground=FG)
        scroll = tk.Scrollbar(log_frame, command=text.yview, relief="flat",
                              bg=FIELD_BG, troughcolor=BG, activebackground=HOVER,
                              highlightthickness=0, bd=0)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        text.tag_configure("time", foreground=MUTED)
        text.tag_configure("ok", foreground=OK)
        text.tag_configure("error", foreground=ERROR)
        text.tag_configure("info", foreground=FG)

        self._widgets = {
            "state": state_label, "note": note,
            "scene": scene, "entry": entry, "text": text,
            "update_frame": update_frame, "update_label": update_label,
            "update_button": update_button, "update_bar": update_bar,
            "update_progress": update_progress, "header": header,
        }

    def _default_note(self) -> str:
        hint = i18n.t("window.hint_hotkey", hotkey=self.hotkey_label) if self.hotkey_label else ""
        return f"{hint}{i18n.t('window.hint')}"

    # --- hodisalar -----------------------------------------------------------

    def _on_submit(self, _event=None) -> None:
        entry = self._widgets.get("entry")
        if entry is None:
            return
        text = entry.get().strip()
        if not text:
            return
        entry.delete(0, "end")
        self.log_line(f"> {text}", "info")
        try:
            self.on_submit(text)
        except Exception:  # noqa: BLE001
            log.exception("Buyruq yuborilmadi")

    def _on_update(self) -> None:
        button = self._widgets.get("update_button")
        if button is not None:
            button.configure(state="disabled", text=i18n.t("window.button.downloading"))
        try:
            self.on_update()
        except Exception:  # noqa: BLE001
            log.exception("Yangilanish boshlanmadi")

    def _on_close(self) -> None:
        # Yopish tugmasi ilovani tugatmaydi - faqat yashiradi (tray'da qoladi)
        self.hide()

    def _pump(self) -> None:
        root = self._root
        if root is None:
            return
        try:
            while True:
                try:
                    command, payload = self._commands.get_nowait()
                except queue.Empty:
                    break
                self._apply(command, payload)
        except Exception:  # noqa: BLE001
            log.exception("Oyna buyrug'i bajarilmadi")
        if self._alive and root is not None:
            root.after(50, self._pump)

    def _apply(self, command: str, payload) -> None:
        root = self._root
        if root is None:
            return

        if command == "show":
            root.deiconify()
            root.lift()
            root.focus_force()
            entry = self._widgets.get("entry")
            if entry is not None:
                entry.focus_set()
        elif command == "hide":
            root.withdraw()
        elif command == "toggle":
            self._apply("hide" if root.state() == "normal" else "show", None)
        elif command == "state":
            state, detail = payload
            widget = self._widgets.get("state")
            if widget is not None:
                try:
                    text = label(State(state))
                except ValueError:
                    text = state
                widget.configure(text=text + (f" - {detail}" if detail else ""))
            scene = self._widgets.get("scene")
            if scene is not None:
                scene.set_state(state)
        elif command == "level":
            # Mikrofon darajasining YAGONA yo'li. O'lchagich o'chirilganda bu
            # tarmoq ham ko'chirilishi shart edi, aks holda to'lqin abadiy
            # nolda qolardi (`.get()` tufayli xato ham chiqmasdi).
            scene = self._widgets.get("scene")
            if scene is not None:
                scene.set_level(min(1.0, max(0.0, float(payload) * 4.0)))
        elif command == "note":
            widget = self._widgets.get("note")
            if widget is not None:
                widget.configure(text=str(payload))
        elif command == "log":
            text_widget = self._widgets.get("text")
            if text_widget is not None:
                message, kind = payload
                text_widget.configure(state="normal")
                text_widget.insert("end", f"{datetime.now():%H:%M:%S}  ", "time")
                text_widget.insert("end", f"{message}\n", kind)
                text_widget.see("end")
                # Jurnal cheksiz o'smasin
                if int(text_widget.index("end-1c").split(".")[0]) > 300:
                    text_widget.delete("1.0", "100.0")
                text_widget.configure(state="disabled")
        elif command == "update_show":
            text, button_text, raise_window = payload
            frame = self._widgets.get("update_frame")
            label_widget = self._widgets.get("update_label")
            button = self._widgets.get("update_button")
            bar = self._widgets.get("update_bar")
            if label_widget is not None:
                label_widget.configure(text=text)
            if button is not None:
                # Chaqiruvchi matn bermasa - faol tildagi standart yozuv.
                button.configure(text=button_text or i18n.t("window.button.update"),
                                 state="normal")
            if frame is not None:
                frame.pack(fill="x", padx=16, pady=(4, 8),
                           after=self._widgets.get("header"))
            if bar is not None:
                bar.pack_forget()
            # Fokusni FAQAT foydalanuvchi so'ragan bo'lsa olamiz.
            if raise_window:
                root.deiconify()
                root.lift()
        elif command == "update_hide":
            frame = self._widgets.get("update_frame")
            if frame is not None:
                frame.pack_forget()
        elif command == "update_progress":
            done, total = payload
            bar = self._widgets.get("update_bar")
            item = self._widgets.get("update_progress")
            label_widget = self._widgets.get("update_label")
            if bar is not None and item is not None:
                if not bar.winfo_ismapped():
                    bar.pack(fill="x", padx=12, pady=(0, 8))
                ratio = (done / total) if total else 0.0
                bar.coords(item, 0, 0, max(0.0, min(1.0, ratio)) * bar.winfo_width(), 4)
            if label_widget is not None and total:
                label_widget.configure(text=i18n.t(
                    "window.update.progress",
                    done=done // 1048576, total=total // 1048576))
        elif command == "quit":
            self._alive = False
            try:
                root.quit()
                root.destroy()
            except Exception:  # noqa: BLE001
                pass
