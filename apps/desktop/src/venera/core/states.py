"""Holatlar va ruxsat etilgan o'tishlar.

Step 2 da TRANSCRIBING haqiqiy ma'noga ega bo'ladi (hozir mock bir zumda o'tadi),
Step 5 da esa IDLE holatida wake word tinglanadi. Holatlar ro'yxati o'zgarmaydi.
"""

from __future__ import annotations

from enum import Enum


class State(str, Enum):
    IDLE = "idle"                  # tinch turibdi, aktivatsiyani kutmoqda
    ACTIVATED = "activated"        # uyg'ondi, signal berilmoqda
    CAPTURING = "capturing"        # buyruqni kutmoqda (Step 1: matn, Step 2: ovoz)
    TRANSCRIBING = "transcribing"  # ovoz -> matn
    THINKING = "thinking"          # matn -> intent
    ACTING = "acting"              # harakat bajarilmoqda
    SPEAKING = "speaking"          # javob aytilmoqda
    PAUSED = "paused"              # ekran qulflangan yoki foydalanuvchi to'xtatgan

    def __str__(self) -> str:
        return self.value


#: Zaxira nomlar. Faol til paketi (`ui.yaml` dagi `state.*`) BIRINCHI
#: o'qiladi; bu jadval paket yuklanmagan holat uchun qoladi. Ikkisi bir xil
#: bo'lishini `tests/test_i18n.py` tekshiradi.
LABELS: dict[State, str] = {
    State.IDLE: "Tayyor",
    State.ACTIVATED: "Uyg'ondi",
    State.CAPTURING: "Tinglayapman",
    State.TRANSCRIBING: "Matnga o'girilmoqda",
    State.THINKING: "O'ylayapman",
    State.ACTING: "Bajarilmoqda",
    State.SPEAKING: "Javob berilmoqda",
    State.PAUSED: "To'xtatilgan",
}

#: Yangi buyruq qabul qilinadigan holatlar
ACCEPTS_ACTIVATION = {State.IDLE}

#: Ish ketayotgan holatlar - bekor qilish mumkin
BUSY = {State.ACTIVATED, State.CAPTURING, State.TRANSCRIBING,
        State.THINKING, State.ACTING, State.SPEAKING}


def label(state: State) -> str:
    """Holatning foydalanuvchiga ko'rinadigan nomi - FAOL tilda.

    Import halqasi bo'lmasligi uchun i18n kech import qilinadi:
    `i18n` -> `nlu.grammar` zanjiri bu modulga qaytib kelmasligi kerak.
    """
    from .. import i18n

    text = i18n.t(f"state.{state.value}")
    if text != f"state.{state.value}":
        return text
    return LABELS.get(state, str(state))
