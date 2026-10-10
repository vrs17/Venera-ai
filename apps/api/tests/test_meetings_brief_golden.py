""""Qisqa xulosa" - server va mobil ilova AYNAN bir xil matn bersin (2026-10-10 sharhi).

Namuna `packages/fixtures/meeting-brief.json` da; mobil tomonda xuddi shu fayl
`apps/mobile/__tests__/briefGolden.test.ts` da tekshiriladi. NEGA umumiy fayl: ilovadagi
"Nusxa olish"/"Ulashish" matni va yuklab olingan fayl ikki xil kodda yig'iladi - biri
o'zgarib, ikkinchisi qolib ketsa, shu test ikkala tomonda ham yiqiladi.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.services.meetings import export

GOLDEN = Path(__file__).resolve().parents[3] / "packages" / "fixtures" / "meeting-brief.json"
CASES = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]


def _speakers(case: dict) -> dict[str, dict]:
    return {s["id"]: {"id": s["id"], "name": s["name"], "merged_into": s["mergedInto"]} for s in case["speakers"]}


def _rows(live: list[dict]) -> list[dict]:
    """Mobil `ActionItem` -> ombordagi `action_items` qatori (`actions_from_rows` kirishi)."""
    return [{"task": a["task"], "owner_name": a["owner"]["name"], "owner_speaker": a["owner"]["speaker"],
             "owner_kind": a["owner"]["kind"], "due_date": a["due"]["date"], "due_time": a["due"]["time"],
             "due_raw": a["due"]["raw"], "status": a["status"], "needs_confirmation": a["needsConfirmation"]}
            for a in live]


def _document(case: dict) -> export.Document:
    content = case["content"]
    meeting = case["meeting"]
    speakers = _speakers(case)
    live = case.get("liveActions")
    brief_actions = export.actions_from_rows(_rows(live), speakers, content["language"]) if live else None
    recorded_at = datetime.fromisoformat(meeting["recordedAt"].replace("Z", "+00:00")).timestamp()
    # Ilova tili ataylab BOSHQA: blok baribir xulosa tilida bo'lishi kerak.
    app_lang = "ru" if content["language"] != "ru" else "en"
    return export.build_document(title=meeting["title"], recorded_at=recorded_at, duration_sec=meeting["durationSec"],
                                 speakers=speakers, lang=app_lang, now=0, parts=["brief"], template="general",
                                 content=content, brief_actions=brief_actions,
                                 user_title=meeting["titleSource"] == "user")


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_qisqa_xulosa_umumiy_namuna(case):
    doc = _document(case)
    assert export.render_text(doc) == case["expectedText"]
    if "expectedMarkdown" in case:
        assert export.render_markdown(doc) == case["expectedMarkdown"]
