"""Frontend konteyneri (rootless podman) tarmog'i: `mtu=1500` MAJBURIY.

2026-10-10 o'lchangan: podman default MTU (65520) bilan slirp4netns nginx ->
uvicorn yo'lida ~64 KB dan katta HAR BIR javobni AYNAN 5 s ushlab turadi
(libslirp 32768 baytlik segment + "silly window" himoyasi + 5 s persist
taymeri; tcpdump bilan isbotlangan). Mobil ovozda bu har TTS bo'lagi oldidan
5 s jimlik edi. Flag "keraksiz" deb o'chirib yuborilmasin - shu test turibdi.

Fayl yo'q bo'lsa (API alohida joylangan) - test o'tkazib yuboriladi.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

UNIT = Path(__file__).resolve().parents[2] / "web" / "deploy" / "venera-frontend.user.service"


def _exec_start() -> list[str]:
    if not UNIT.exists():
        pytest.skip(f"{UNIT} yo'q")
    lines = UNIT.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("ExecStart="))
    parts: list[str] = []
    for line in lines[start:]:
        stripped = line.rstrip()
        parts.append(stripped.removesuffix("\\"))
        if not stripped.endswith("\\"):
            break
    return shlex.split(" ".join(parts).removeprefix("ExecStart="))


def _network_options() -> tuple[str, dict[str, str]]:
    args = _exec_start()
    value = args[args.index("--network") + 1]
    mode, _, raw = value.partition(":")
    options = dict(item.split("=", 1) for item in raw.split(",") if item)
    return mode, options


def test_frontend_slirp_mtu_1500():
    mode, options = _network_options()
    assert mode == "slirp4netns"
    assert options.get("mtu") == "1500", (
        "slirp4netns MTU 1500 bo'lmasa ~64 KB dan katta har /api javobi 5 s kechikadi")


def test_frontend_backendga_host_loopback_orqali_chiqadi():
    """`allow_host_loopback` - uvicorn 127.0.0.1:8000 da; usiz login ishlamaydi."""
    _, options = _network_options()
    assert options.get("allow_host_loopback") == "true"
