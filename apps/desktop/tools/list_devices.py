#!/usr/bin/env python3
"""Audio qurilmalarini ko'rsatadi.

    python tools/list_devices.py

Chiqqan nomning bir qismini config.yaml -> audio.input_device ga yozing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venera.audio import capture  # noqa: E402


def main() -> int:
    if not capture.available():
        print(f"sounddevice mavjud emas: {capture.SOUNDDEVICE_ERROR}")
        print("O'rnatish:  pip install sounddevice")
        return 1

    devices = capture.list_input_devices()
    if not devices:
        print("Kirish qurilmalari topilmadi.")
        return 1

    print(f"Kirish qurilmalari ({len(devices)} ta):\n")
    for device in devices:
        print(" ", device.label())

    chosen = capture.pick_device(None)
    label = chosen.label() if chosen else "topilmadi"
    print(f"\nTanlanadigan qurilma: {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
