"""Analitika: har savol-javobning izi, tashqi chaqiruvlar hisobi, admin ma'lumoti.

    db.py        SQLite ombori, sxema (`PRAGMA user_version`), o'qish
    writer.py    yagona yozuvchi ip: navbat, to'plam, eski yozuvlarni tozalash
    recorder.py  `TurnRecorder` - bitta savolning kadrlari, vaqtlari, manbalari
    meter.py     `metered(...)` - xizmat chaqiruvlari; `bind` - kim/qayerdan/qaysi savol

QOIDA: so'rov yo'li HECH QACHON diskni kutmaydi va yozib olish xatosi
javobni HECH QACHON buzmaydi. Yozuvlar navbatga tushadi, o'qish esa
to'g'ridan-to'g'ri (`get_db().rows(...)`).
"""

from __future__ import annotations

from pathlib import Path

from . import db as _db_module
from . import writer as _writer_module
from .db import SCHEMA_VERSION, Database, analytics_enabled, get_db, retention_days
from .meter import (
    Attribution,
    Binding,
    Call,
    begin,
    bind,
    carry,
    current,
    current_actor,
    current_channel,
    current_turn,
    http_status_of,
    metered,
    record_auth_event,
    record_call,
    redact,
)
from .recorder import TurnRecorder, new_turn_id, set_proposal_status, valid_turn_id
from .writer import Writer, get_writer, purge, shutdown

__all__ = [
    "SCHEMA_VERSION", "Database", "analytics_enabled", "get_db", "retention_days",
    "Writer", "get_writer", "purge", "shutdown",
    "TurnRecorder", "new_turn_id", "set_proposal_status", "valid_turn_id",
    "Attribution", "Binding", "Call", "begin", "bind", "carry", "current",
    "current_actor", "current_channel", "current_turn", "http_status_of", "metered",
    "record_auth_event", "record_call", "redact",
    "flush", "reset_for_tests",
]


def flush(timeout: float = 5.0) -> bool:
    """Umumiy yozuvchining navbatini diskka tushiradi (testlar, "hozir
    yozilganini o'qish" kerak bo'lgan joylar)."""
    return get_writer().flush(timeout)


def reset_for_tests(path: Path | str, **writer_kwargs) -> Database:
    """Ombor VA yozuvchini `path` dagi yangi faylga o'tkazadi.

    Eski yozuvchi navbatini yozib to'xtaydi, eski ombor ulanishlari
    yopiladi. Har test o'z fayli bilan ishlaydi - jonli ma'lumotga tegmaydi.
    """
    _writer_module.shutdown(2.0)
    database = _db_module.reset_for_tests(path)
    _writer_module.reset_for_tests(database, **writer_kwargs)
    return database
