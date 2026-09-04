"""Yangilanish manbasidan fayl olish.

Ikki xil manba qo'llab-quvvatlanadi, ikkalasi ham bir xil interfeys orqali:

    http://10.10.50.9:8000/updates/version.json     - ichki HTTP server
    \\\\fileserver\\venera\\assistant\\version.json     - tarmoq papkasi (SMB)
    C:\\updates\\venera\\version.json                     - lokal papka (sinov uchun)

Tarmoq papkasi bankda ko'pincha eng oson yo'l: yangi server ko'tarish shart emas,
kirish huquqi Active Directory orqali boshqariladi.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PureWindowsPath
from typing import Callable

log = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int], None]   # (yuklangan bayt, jami bayt)

USER_AGENT = "Venera-AI-Assistant-Updater"
CHUNK = 256 * 1024


class UpdateSourceError(Exception):
    """Manbadan o'qib bo'lmadi."""


def is_http(location: str) -> bool:
    return str(location).lower().startswith(("http://", "https://"))


def _is_absolute_target(name: str) -> bool:
    """URL, UNC yo'l (\\\\server\\share) yoki disk harfi (C:\\...)."""
    return (
        is_http(name)
        or name.startswith("\\\\")
        or (len(name) > 2 and name[1] == ":" and name[2] in "\\/")
    )


def join_location(base: str, name: str) -> str:
    """Manifest yonidagi faylning to'liq manzili.

    `name` allaqachon to'liq manzil bo'lsa (URL yoki mutlaq yo'l) - o'zgarmaydi.

    Windows yo'llari uchun PureWindowsPath ishlatiladi: oddiy Path Linux'da
    teskari chiziqni papka ajratuvchisi deb hisoblamaydi va UNC yo'lni
    bitta fayl nomi sifatida ko'radi (WSL'dagi testlar shuni ko'rsatdi).
    """
    name = str(name).strip()
    base = str(base).strip()
    if _is_absolute_target(name):
        return name
    if is_http(base):
        return urllib.parse.urljoin(base, name)
    if "\\" in base or (len(base) > 2 and base[1] == ":"):
        return str(PureWindowsPath(base).parent / name)
    return str(Path(base).parent / name)


def _build_opener(no_proxy: bool) -> urllib.request.OpenerDirector:
    """Ichki serverlar uchun korporativ proksini chetlab o'tish kerak bo'ladi."""
    handlers: list = []
    if no_proxy:
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers)


def read_bytes(location: str, timeout: float = 20.0, no_proxy: bool = True,
               max_size: int = 8 * 1024 * 1024) -> bytes:
    """Kichik faylni (manifest) to'liq o'qiydi."""
    try:
        if is_http(location):
            opener = _build_opener(no_proxy)
            request = urllib.request.Request(location, headers={"User-Agent": USER_AGENT})
            with opener.open(request, timeout=timeout) as response:
                return response.read(max_size + 1)[:max_size]
        path = Path(location)
        if not path.exists():
            raise UpdateSourceError(f"topilmadi: {location}")
        return path.read_bytes()[:max_size]
    except UpdateSourceError:
        raise
    except urllib.error.HTTPError as exc:
        raise UpdateSourceError(f"server javobi {exc.code}: {location}") from exc
    except urllib.error.URLError as exc:
        raise UpdateSourceError(f"ulanmadi ({exc.reason}): {location}") from exc
    except OSError as exc:
        raise UpdateSourceError(f"o'qilmadi ({exc}): {location}") from exc


def download(location: str, destination: Path, expected_sha256: str = "",
             expected_size: int = 0, timeout: float = 60.0, no_proxy: bool = True,
             progress: ProgressCallback | None = None,
             cancelled: Callable[[], bool] | None = None) -> Path:
    """Katta faylni yuklab oladi va nazorat yig'indisini tekshiradi."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    digest = hashlib.sha256()
    written = 0

    def emit(total: int) -> None:
        if progress is not None:
            try:
                progress(written, total)
            except Exception:  # noqa: BLE001 - UI xatosi yuklashni to'xtatmasin
                pass

    try:
        if is_http(location):
            opener = _build_opener(no_proxy)
            request = urllib.request.Request(location, headers={"User-Agent": USER_AGENT})
            with opener.open(request, timeout=timeout) as response:
                # Yuqoridagi sabab: SPA .exe so'ralganda ham 200 + HTML beradi.
                # sha256 baribir ushlaydi, lekin 45 MB kutib o'tirmasdan darrov
                # aniq sabab bilan to'xtaymiz.
                ctype = (response.headers.get("Content-Type") or "").lower()
                if ctype.startswith("text/html"):
                    raise UpdateSourceError(
                        "server o'rnatuvchi o'rniga HTML sahifa qaytardi - "
                        "fayl serverda yo'q yoki yo'l sozlanmagan"
                    )
                total = int(response.headers.get("Content-Length") or expected_size or 0)
                with temporary.open("wb") as handle:
                    while True:
                        if cancelled is not None and cancelled():
                            raise UpdateSourceError("bekor qilindi")
                        chunk = response.read(CHUNK)
                        if not chunk:
                            break
                        handle.write(chunk)
                        digest.update(chunk)
                        written += len(chunk)
                        emit(total)
        else:
            source = Path(location)
            if not source.exists():
                raise UpdateSourceError(f"topilmadi: {location}")
            total = source.stat().st_size
            with source.open("rb") as reader, temporary.open("wb") as handle:
                while True:
                    if cancelled is not None and cancelled():
                        raise UpdateSourceError("bekor qilindi")
                    chunk = reader.read(CHUNK)
                    if not chunk:
                        break
                    handle.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                    emit(total)
    except UpdateSourceError:
        temporary.unlink(missing_ok=True)
        raise
    except urllib.error.HTTPError as exc:
        temporary.unlink(missing_ok=True)
        raise UpdateSourceError(f"server javobi {exc.code}") from exc
    except urllib.error.URLError as exc:
        temporary.unlink(missing_ok=True)
        raise UpdateSourceError(f"ulanmadi: {exc.reason}") from exc
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise UpdateSourceError(f"yuklanmadi: {exc}") from exc

    if expected_size and written != expected_size:
        temporary.unlink(missing_ok=True)
        raise UpdateSourceError(f"hajm mos kelmadi: {written} != {expected_size}")

    actual = digest.hexdigest()
    if expected_sha256 and actual != expected_sha256.lower():
        temporary.unlink(missing_ok=True)
        raise UpdateSourceError("nazorat yig'indisi mos kelmadi - fayl buzilgan yoki almashtirilgan")
    if not expected_sha256:
        log.warning("Manifestda sha256 yo'q - fayl haqiqiyligi tekshirilmadi")

    destination.unlink(missing_ok=True)
    shutil.move(str(temporary), str(destination))
    log.info("Yuklandi: %s (%d bayt, sha256 %s)", destination, written, actual[:12])
    return destination


def strip_mark_of_the_web(path: Path) -> None:
    """Tarmoq papkasidan olingan faylda SmartScreen belgisi qolmasin."""
    if os.name != "nt":
        return
    try:
        zone = Path(f"{path}:Zone.Identifier")
        if zone.exists():
            zone.unlink()
            log.debug("Zone.Identifier olib tashlandi: %s", path)
    except OSError as exc:
        log.debug("Zone.Identifier o'chirilmadi: %s", exc)
