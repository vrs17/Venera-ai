"""Admin "Agent playground" - agent bosqichlarini ko'rish, tahrirlab qayta ishga tushirish,
modellarni solishtirish va regressiya sinovlarini saqlash. FAQAT ADMIN.

    GET    /admin/playground/status              agent debug yoqilganmi, tanlanadigan modellar
    GET    /admin/playground/turns/{turn_id}     bizdagi savol + agentdagi bosqichlar yozuvi
    POST   /admin/playground/prompt              yangi savol uchun bosqich kirishi (model chaqirilmaydi)
    POST   /admin/playground/run                 bitta bosqich (va ixtiyoriy 2-model) - PULLIK, tasdiq bilan
    GET    /admin/playground/cases               saqlangan regressiya sinovlari
    POST   /admin/playground/cases               sinov saqlash
    DELETE /admin/playground/cases/{case_id}     sinovni arxivlash
    GET    /admin/playground/cases/export        sinovlar `run_inproc` to'plami shaklida

Qoidalar `services/playground.py` izohida: vosita chaqiruvlari bajarilmaydi, bosqich kirishi
saqlanmaydi, agent mijozi o'z uzgichi bilan. Har ko'rish va ishga tushirish admin auditida
(`playground.*`) - kim xom promptni ko'rgani hujjatlanadi; kiritilgan matn auditga YOZILMAYDI.
"""

from __future__ import annotations

import logging
import sqlite3

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path

from ...core.errors import error_status
from ...schemas.auth import AuthUser
from ...schemas.playground import CaseIn, PromptQuery, StageRun
from ...services import admin_users as _admin
from ...services import playground as _pg
from ...services.analytics.db import get_db
from ..deps import require_roles
from .admin_probe import _paid_gate

log = logging.getLogger(__name__)

admin_only = require_roles("ADMIN")

router = APIRouter(prefix="/admin/playground", tags=["admin"], dependencies=[Depends(admin_only)])

#: Savol va sinov id si (uuid hex). `Annotated` - har parametr o'z nusxasini oladi
#: (bitta `Path(...)` obyekti ikki yo'lda ulashilsa FastAPI uni birinchi nomga bog'laydi).
ItemId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


def _audit(admin: AuthUser, action: str, target: str | None, detail: dict[str, Any]) -> None:
    """Audit yozilmasa ham javob beriladi - audit hujjat, amalning sharti emas."""
    try:
        with get_db().transaction() as conn:
            _admin.write_audit(conn, admin, action, "playground", target, detail)
    except (sqlite3.Error, OSError) as exc:
        log.warning("Playground auditi yozilmadi (%s): %s", action, type(exc).__name__)


def _raise(exc: _pg.Unavailable):
    raise error_status(exc.status, exc.message) from None


@router.get("/status")
def playground_status() -> dict[str, Any]:
    return _pg.status()


@router.get("/turns/{turn_id}")
def playground_turn(turn_id: ItemId, admin: AuthUser = Depends(admin_only)) -> dict[str, Any]:
    found = _pg.turn(turn_id)
    if found is None:
        raise error_status(404, "Savol topilmadi")
    _audit(admin, "playground.view", turn_id, {"captured": found["capture"] is not None,
                                               "problem": (found["problem"] or {}).get("code")})
    return found


@router.post("/prompt")
def playground_prompt(body: PromptQuery, admin: AuthUser = Depends(admin_only)) -> dict[str, Any]:
    try:
        out = _pg.prompt(body)
    except _pg.Unavailable as exc:
        _raise(exc)
    _audit(admin, "playground.prompt", body.stage, {"platforms": body.platforms, "lang": body.lang})
    return out


@router.post("/run")
def playground_run(body: StageRun, admin: AuthUser = Depends(admin_only)) -> dict[str, Any]:
    try:
        # Hajm tekshiruvi pullik chekdan OLDIN: rad etiladigan kirish soatlik hisobni yemasin.
        _pg.check_size(body)
    except _pg.Unavailable as exc:
        _raise(exc)
    models = [m for m in (body.model, body.compare_model) if m] or ["default"]
    note = (f"{len(models)} ta model chaqiruvi ({', '.join(models)}): OpenAI pullik, Ollama Cloud kvotasi prod "
            "bilan umumiy.")
    _paid_gate(admin, "playground", body.confirm_cost, note)
    if body.compare_model:
        # Ikkinchi model - ikkinchi pullik chaqiruv: soatlik chek ikkalasini ham sanaydi.
        _paid_gate(admin, "playground", True, note)
    try:
        out = _pg.run(body)
    except _pg.Unavailable as exc:
        _raise(exc)
    _audit(admin, "playground.run", body.stage,
           {"models": models, "ok": [r.get("ok") for r in out["runs"]], "ms": [r.get("ms") for r in out["runs"]]})
    return {**out, "cost_note": note}


@router.get("/cases")
def playground_cases() -> dict[str, Any]:
    return {"items": _pg.list_cases()}


@router.post("/cases", status_code=201)
def playground_case_create(body: CaseIn, admin: AuthUser = Depends(admin_only)) -> dict[str, Any]:
    with get_db().transaction() as conn:
        case = _pg.create_case(conn, body, _admin._by(admin))
        _admin.write_audit(conn, admin, "playground.case_create", "playground_case", case["id"],
                           {"turns": len(body.dialog), "area": body.area})
    return case


@router.delete("/cases/{case_id}")
def playground_case_delete(case_id: ItemId, admin: AuthUser = Depends(admin_only)) -> dict[str, Any]:
    with get_db().transaction() as conn:
        if not _pg.archive_case(conn, case_id):
            raise error_status(404, "Sinov topilmadi")
        _admin.write_audit(conn, admin, "playground.case_delete", "playground_case", case_id, {})
    return {"id": case_id, "archived": True}


@router.get("/cases/export")
def playground_cases_export() -> dict[str, Any]:
    return _pg.export_suite()
