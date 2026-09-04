"""macOS adapteri - Step 8 da to'ldiriladi.

Reja (interfeys allaqachon tayyor, faqat shu fayl yoziladi):
  launch            -> subprocess ["open", "-a", app]
  open_url          -> ["open", url]
  set_volume        -> osascript "set volume output volume N"
  lock_workstation  -> CGSession -suspend
  screenshot        -> ["screencapture", path]
  is_session_locked -> CGSessionCopyCurrentDictionary
  autostart         -> ~/Library/LaunchAgents/uz.venera.assistant.plist (RunAtLoad, KeepAlive)
  single instance   -> NSDistributedNotificationCenter yoki fayl-lock
Qo'shimcha: .app bundle, Info.plist da NSMicrophoneUsageDescription, imzo va notarizatsiya.
"""

from __future__ import annotations

from .base import NullAdapter


class MacAdapter(NullAdapter):
    name = "macos-stub"
