"""Venera dizayn tokenlari (desktop).

GENERATSIYA QILINGAN FAYL - QO'LDA TAHRIRLAMANG.
Manba: packages/design-tokens/tokens.json | Qayta yig'ish: python3 packages/design-tokens/build.py
"""

from __future__ import annotations

# Brend belgisi - tray ikonkasi va installer sarlavhasida chiziladi.
MARK = 'V'

# --- Holat ranglari (core.states.State qiymatlari bilan mos) ---
STATE_COLORS: dict[str, str] = {
    'idle': '#2F6FED',  # ko'k - tayyor
    'activated': '#1FAD66',  # yashil - uyg'ondi
    'capturing': '#1FAD66',  # yashil - yozib olmoqda
    'transcribing': '#E0A32E',  # sariq - matnga o'girmoqda
    'thinking': '#E0A32E',  # sariq - o'ylamoqda
    'acting': '#E0A32E',  # sariq - bajarmoqda
    'speaking': '#7B5CD6',  # binafsha - gapirmoqda
    'paused': '#8A9099',  # kulrang - to'xtatilgan
}

# --- Natija ranglari ---
OK = '#1FAD66'
WARN = '#E0A32E'
ERROR = '#D64545'

# --- Desktop palitrasi (tkinter oynasi + tray) ---
BG = '#12151B'
FG = '#E8EAED'
MUTED = '#8A9099'
ACCENT = '#2F6FED'
ACCENT_ACTIVE = '#1E4FBF'
ON_ACCENT = '#FFFFFF'
FIELD_BG = '#1C2029'
HOVER = '#262B36'
UPDATE_BG = '#1B2A4A'
UPDATE_FG = '#CFE0FF'
UPDATE_TRACK = '#0E1830'
NIGHT = '#191F33'
VENUS_GOLD = '#E89C44'
VENUS_GOLD_ACTIVE = '#C97F2E'
PEARL = '#F4E6C6'
ON_GOLD = '#0E1220'
