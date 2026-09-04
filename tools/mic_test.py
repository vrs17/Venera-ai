#!/usr/bin/env python3
"""Mikrofonni sinaydi: yozib oladi, darajani ko'rsatadi va WAV saqlaydi.

    python tools/mic_test.py            # 3 soniya
    python tools/mic_test.py 5          # 5 soniya
    python tools/mic_test.py 3 "Array"  # nomida "Array" bo'lgan mikrofon

Bu Step 2 dan oldin audio zanjiri ishlayotganini isbotlaydi: saqlangan fayl
16 kHz mono 16-bit - STT serveri aynan shuni kutadi.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venera.audio import wav  # noqa: E402
from venera.audio.capture import AudioCapture, available  # noqa: E402


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
    hint = sys.argv[2] if len(sys.argv) > 2 else None

    if not available():
        print("sounddevice o'rnatilmagan:  pip install sounddevice")
        return 1

    peak_seen = [0.0]

    def on_level(level: float) -> None:
        peak_seen[0] = max(peak_seen[0], level)
        bars = int(level * 60)
        print("\r  [" + "#" * bars + " " * (40 - min(40, bars)) + f"] {level:.3f}", end="")

    capture = AudioCapture(device_hint=hint, on_level=on_level)
    if not capture.start():
        print("Mikrofon ochilmadi. `python tools/list_devices.py` bilan tekshiring.")
        return 1

    device = capture.device
    print(f"Mikrofon: {device.label() if device else '?'}")
    print(f"{seconds:.0f} soniya gapiring...\n")
    time.sleep(0.3)

    pcm = capture.record(seconds)
    capture.stop()
    print()

    if pcm.size == 0:
        print("Hech qanday ma'lumot kelmadi - mikrofon ruxsatini tekshiring")
        print("  Windows: Sozlamalar > Maxfiylik > Mikrofon > Ilovalarga ruxsat")
        return 1

    target = Path.cwd() / "mic_test.wav"
    target.write_bytes(wav.encode_wav(pcm, capture.sample_rate))

    print(f"Namunalar : {pcm.size} ({wav.duration_seconds(pcm, capture.sample_rate):.2f} s)")
    print(f"RMS       : {wav.rms_level(pcm):.4f}")
    print(f"Eng baland: {wav.peak_level(pcm):.4f}")
    print(f"Saqlandi  : {target}")

    if wav.peak_level(pcm) < 0.01:
        print("\nOgohlantirish: signal juda past. Mikrofon o'chirilgan yoki tanlanmagan bo'lishi mumkin.")
        return 1
    print("\nMikrofon ishlayapti.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
