"""`/api/v1/meetings/{id}/minutes` - bayonnoma REST shartnomasi (mobil ilova).

Fonda boshlash (202 `running`), tayyori va yozilayotgani (200, ikkinchi bosish qo'shiladi), holatni
so'rash, Word/PDF/MD eksporti, tez tekshiruv xatolari (400/404/409/429/503), eskirgan `running` qator
(`interrupted`), izolyatsiya va fon ishidagi xatolar.

Model - `FakeLLM` (`MEETINGS_MINUTES_CHAIN=ollama`, `meetings_fakes.minutes_reply`); yig'ilish mobil yo'l
bilan tayyorlanadi (yaratish, yuklash, ishchi). Fon ishi `minutes.runner` orqali: default - shu ipda,
`jobs` fiksturasi bilan - navbatga, test o'zi ishga tushiradi (deterministik). Tarmoqqa chiqilmaydi.
"""

from __future__ import annotations

import threading
import time

from urllib.parse import quote

import pytest

from app.core.config import settings
from app.schemas.auth import AuthUser
from app.services.meetings import export, minutes
from app.services.meetings.store import new_id
from meetings_fakes import create_meeting, enable, recorded, run_all

BASE = "/api/v1/meetings"
VIEW_FIELDS = {"id", "meetingId", "language", "status", "createdAt", "finishedAt", "provider", "model",
               "transcriptRev", "stale", "agendaCount", "sectionCount", "itemCount", "notes", "warnings", "error",
               "kind", "version", "parentId", "request", "notesApplied", "pendingNotes", "header", "changes"}
#: `conftest.ADMIN` (actor 1) - Slack/Telegram yo'lini (`minutes.generate`) to'g'ridan-to'g'ri chaqirish uchun.
ADMIN_USER = AuthUser(actorId=1, email="admin@venera.uz", fullName="Administrator", roles=["ADMIN"])


@pytest.fixture(autouse=True)
def _inline_runner(monkeypatch):
    """Fon ishi HAR TESTDA shu ipda - haqiqiy ip havzasi testda ishga tushmaydi."""
    monkeypatch.setattr(minutes, "runner", lambda job: job())


@pytest.fixture
def jobs(monkeypatch):
    """Fon ishlari navbati: `minutes.start` ishni shu ro'yxatga qo'yadi, test `drain` bilan ishga tushiradi."""
    queue: list = []
    monkeypatch.setattr(minutes, "runner", queue.append)
    return queue


def drain(queue: list) -> None:
    while queue:
        queue.pop(0)()


@pytest.fixture
def ready(client, auth, monkeypatch, _isolated_meetings):
    """(yig'ilish id, runtime) - transkripti tayyor yig'ilish (admin), bayonnoma zanjiri FakeLLM."""
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    run_all(_isolated_meetings)
    monkeypatch.setattr(settings, "meetings_minutes_chain", "ollama", raising=False)
    return meeting["id"], _isolated_meetings


def _calls(rt) -> int:
    return len([c for c in rt.llm.calls if c["op"] == "meeting_minutes"])


def _post(client, auth, mid: str, **body):
    return client.post(f"{BASE}/{mid}/minutes", json=body, headers=auth)


def _detail(client, auth, mid: str, minutes_id: str) -> dict:
    response = client.get(f"{BASE}/{mid}/minutes/{minutes_id}", headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


def _note(rt, mid: str, text: str) -> str:
    """Hisob egasining bayonnoma ko'rsatmasi (`kind='note'` chat navbati) - to'g'ridan-to'g'ri omborga (chat orqali
    yuborish - `test_meetings_chat`)."""
    qid = new_id()
    rt.store.add_question({"id": qid, "meeting_id": mid, "question": text, "answer": "Ko'rsatmangiz eslab qolindi.",
                           "citations": "[]", "follow_ups": "[]", "kind": "note", "channel": "mobile",
                           "minutes_json": '{"action":"note","language":null,"instruction":null}',
                           "created_at": int(time.time())})
    return qid


# --- asosiy yo'l ------------------------------------------------------------------------------------


def test_fonda_boshlash_holat_va_eksport(client, auth, ready, jobs):
    mid, rt = ready
    response = _post(client, auth, mid, language="uz-cyrl")
    assert response.status_code == 202, response.text
    started = response.json()
    assert set(started) == VIEW_FIELDS
    assert (started["status"], started["language"], started["meetingId"]) == ("running", "uz-cyrl", mid)
    assert started["error"] is None and started["finishedAt"] is None and started["provider"] is None
    assert started["transcriptRev"] == int(rt.store.meeting_any(mid)["transcript_rev"]) and started["stale"] is False
    # Asl hujjat: 1-versiya, ota-versiya, so'rov, ko'rsatma va o'zgarishlar yo'q.
    assert (started["kind"], started["version"], started["parentId"], started["request"]) == ("generate", 1, None, None)
    assert (started["notesApplied"], started["pendingNotes"]) == (0, 0)
    assert started["header"] is None and started["changes"] is None
    # Model so'rov ipida chaqirilmadi - ish fon navbatida.
    assert len(jobs) == 1 and _calls(rt) == 0
    assert client.get(f"{BASE}/{mid}/minutes", headers=auth).json() == {"items": [started], "notes": 0}
    running = _detail(client, auth, mid, started["id"])
    assert running["status"] == "running" and running["content"] is None
    early = client.get(f"{BASE}/{mid}/minutes/{started['id']}/export", headers=auth)
    assert early.status_code == 409 and early.json()["code"] == "not_ready"

    drain(jobs)
    body = _detail(client, auth, mid, started["id"])
    assert set(body) == VIEW_FIELDS | {"content"}
    assert (body["status"], body["provider"], body["model"]) == ("ready", "ollama", "gemma4:31b")
    assert (body["agendaCount"], body["sectionCount"], body["itemCount"]) == (2, 2, 3)
    assert body["finishedAt"] and body["error"] is None and isinstance(body["notes"], list) and _calls(rt) == 1
    assert body["content"]["language"] == "uz-cyrl"
    assert body["content"]["version"] == minutes.prompt.MINUTES_VERSION

    url = f"{BASE}/{mid}/minutes/{started['id']}/export"
    docx = client.get(url, headers=auth)                                  # format default - Word
    assert docx.status_code == 200 and docx.content[:2] == b"PK"
    assert docx.headers["content-type"] == minutes.FORMATS["docx"][0]
    disposition = docx.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="') and disposition.endswith(".docx")
    assert "%D0%91%D0%B0%D1%91%D0%BD%D0%BD%D0%BE%D0%BC%D0%B0" in disposition      # "Баённома" (UTF-8 foiz bilan)
    assert docx.headers["cache-control"] == "private, no-store"
    pdf = client.get(f"{url}?format=pdf", headers=auth)
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    assert pdf.headers["content-type"] == "application/pdf" and pdf.headers["content-disposition"].endswith(".pdf")
    md = client.get(f"{url}?format=md", headers=auth)
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert "ҚАРОР ҚИЛАДИ:" in md.content.decode("utf-8") and md.headers["content-disposition"].endswith(".md")
    assert client.get(f"{url}?format=txt", headers=auth).status_code == 422


def test_tayyori_200_va_force_yangisi(client, auth, ready):
    mid, rt = ready
    first = _post(client, auth, mid, language="uz-cyrl")
    # Javob - qator yozilgan paytdagi holat; fon ishi (bu testda shu ipda) allaqachon tugagan.
    assert first.status_code == 202 and first.json()["status"] == "running"
    again = _post(client, auth, mid, language="UZ_CYRL")
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
    assert again.json()["status"] == "ready" and _calls(rt) == 1
    forced = _post(client, auth, mid, language="uz-cyrl", force=True)
    assert forced.status_code == 202 and forced.json()["id"] != first.json()["id"] and _calls(rt) == 2
    items = client.get(f"{BASE}/{mid}/minutes", headers=auth).json()["items"]
    assert [(i["id"], i["status"]) for i in items] == [(first.json()["id"], "ready"), (forced.json()["id"], "ready")]


def test_haqiqiy_ip_havzasi_va_hisob_konteksti(client, auth, ready, monkeypatch):
    """Ishlab chiqarish yo'li (`runner` yo'q): ish `WORKERS` li havza ipida, hisob konteksti (kim so'radi)
    `carry` bilan o'sha ipga o'tgan - Claude chaqiruvi odamniki bo'lib yoziladi."""
    from app.services.analytics.meter import current_actor

    mid, rt = ready
    seen: list[tuple[str, int | None]] = []
    original = rt.llm.reply

    def reply(op, system, user):
        seen.append((threading.current_thread().name, current_actor.get()))
        return original(op, system, user)

    monkeypatch.setattr(rt.llm, "reply", reply)
    monkeypatch.setattr(minutes, "runner", None)
    try:
        started = _post(client, auth, mid, language="en")
        assert started.status_code == 202
        body = _detail(client, auth, mid, started.json()["id"])
        deadline = time.monotonic() + 30
        while body["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.05)
            body = _detail(client, auth, mid, started.json()["id"])
    finally:
        # Havza ipi tugaguncha kutiladi: fikstura omborni yopgandan keyin ip unga tegmasin.
        pool = minutes._pool
        minutes.stop()
        if pool is not None:
            pool.shutdown(wait=True)
    assert body["status"] == "ready" and _calls(rt) == 1
    [(thread, actor)] = seen
    assert thread.startswith("minutes") and actor == 1


def test_til_berilmasa_yigilish_tilidan(client, auth, ready):
    mid, _ = ready
    response = client.post(f"{BASE}/{mid}/minutes", headers=auth)          # tanasiz
    assert response.status_code == 202 and response.json()["language"] == "uz-cyrl"   # uz -> kirill (bank hujjati)
    same = client.post(f"{BASE}/{mid}/minutes", json={}, headers=auth)
    assert same.status_code == 200 and same.json()["id"] == response.json()["id"]


def test_ikki_bosish_bitta_model_bitta_chegara(client, auth, ready, jobs, monkeypatch):
    mid, rt = ready
    monkeypatch.setattr(settings, "meetings_minutes_per_hour", 2, raising=False)
    first = _post(client, auth, mid, language="ru")
    assert first.status_code == 202
    second = _post(client, auth, mid, language="ru")
    forced = _post(client, auth, mid, language="ru", force=True)       # yozilayotgani baribir yangi
    for joined in (second, forced):
        assert joined.status_code == 200 and joined.json()["id"] == first.json()["id"]
        assert joined.json()["status"] == "running"
    assert len(jobs) == 1 and len(rt.store.minutes_rows(mid)) == 1
    drain(jobs)
    assert _calls(rt) == 1 and _detail(client, auth, mid, first.json()["id"])["status"] == "ready"
    # Qo'shilgan bosishlar soatlik chegarani yemagan: ikkinchi joy bo'sh, uchinchisi - 429.
    assert _post(client, auth, mid, language="en").status_code == 202
    limited = _post(client, auth, mid, language="uz-latn")
    assert limited.status_code == 429 and limited.json()["code"] == "rate_limited"
    assert int(limited.headers["retry-after"]) > 0


def test_navbatdagi_ishga_bot_qoshiladi(client, auth, ready, jobs):
    """REST ishi navbatda turganda Slack/Telegram (`generate`) xuddi shu hujjatni so'radi: yangi qator ham, ikkinchi
    model chaqiruvi ham yo'q - `generate` navbatdagi ishga qo'shiladi va uning natijasini kutadi (`wait`; bu yerda
    "kutish" navbatni yuritadi). Tayyor mazmunni ko'chirish yo'li -
    `test_minutes_service.test_nusxa_yoli_provenance`."""
    mid, rt = ready
    queued = _post(client, auth, mid, language="uz-cyrl").json()
    sync = minutes.generate(ADMIN_USER, mid, "uz-cyrl", sleep=lambda _sec: drain(jobs))
    assert sync["id"] == queued["id"] and sync["status"] == "ready" and _calls(rt) == 1
    assert len(rt.store.minutes_rows(mid)) == 1
    body = _detail(client, auth, mid, queued["id"])
    assert body["status"] == "ready" and body["provider"] == "ollama"


def test_post_kutilayotgan_korsatma_202_revise(client, auth, ready):
    """Tayyor hujjat bor, chatda yangi ko'rsatma berildi: til tugmasi hujjatni QAYTADAN yozmaydi - joriy hujjatning
    tahriri (202, `kind` revise, 2-versiya, ko'rsatma qo'llangan); keyingi bosish bepul (200, o'sha versiya)."""
    mid, rt = ready
    head = _post(client, auth, mid, language="uz-cyrl").json()
    assert client.get(f"{BASE}/{mid}/minutes", headers=auth).json()["notes"] == 0
    _note(rt, mid, "CHAIR=Alisher Karimov")
    listed = client.get(f"{BASE}/{mid}/minutes", headers=auth).json()
    assert listed["notes"] == 1 and listed["items"][0]["pendingNotes"] == 1     # hujjatda hali yo'q
    started = _post(client, auth, mid, language="uz-cyrl")
    assert started.status_code == 202, started.text
    body = started.json()
    assert set(body) == VIEW_FIELDS and body["status"] == "running"
    assert (body["kind"], body["version"], body["parentId"], body["request"]) == ("revise", 2, head["id"], None)
    done = _detail(client, auth, mid, body["id"])
    assert done["status"] == "ready" and (done["notesApplied"], done["pendingNotes"]) == (1, 0)
    assert done["header"] == {"organization": None, "chairedBy": None, "city": None, "chair": "Alisher Karimov",
                              "attendees": [], "date": None}
    assert done["changes"] == {"items": {"changed": [], "added": [], "removed": []},
                               "agenda": {"changed": [], "added": [], "removed": []}, "header": ["chair"], "other": []}
    assert [c["op"] for c in rt.llm.calls if c["op"].startswith("meeting_minutes")] == \
        ["meeting_minutes", "meeting_minutes_revise"]
    again = _post(client, auth, mid, language="uz-cyrl")
    assert again.status_code == 200 and again.json()["id"] == body["id"] and _calls(rt) == 1
    listed = client.get(f"{BASE}/{mid}/minutes", headers=auth).json()
    assert [(i["version"], i["pendingNotes"]) for i in listed["items"]] == [(1, 1), (2, 0)]
    md = client.get(f"{BASE}/{mid}/minutes/{body['id']}/export?format=md", headers=auth).content.decode("utf-8")
    assert "Alisher Karimov" in md and "2-таҳрир." in md


def test_post_navbat_toliq_409(client, auth, ready, jobs):
    """Shu tilda 3 ta tahrir navbatda (tirik): to'rtinchisi 409 `minutes_busy` - qator ham, chegara ham yo'q; navbat
    bo'shagach o'tadi, tahrirlar bir-birining ustiga yozilgan (ota-versiyalar zanjiri)."""
    mid, rt = ready
    head = _post(client, auth, mid, language="ru").json()
    drain(jobs)
    queued = []
    for n in range(minutes.MAX_LIVE):
        _note(rt, mid, f"Ko'rsatma {n + 1}")
        response = _post(client, auth, mid, language="ru")
        assert response.status_code == 202 and response.json()["kind"] == "revise", response.text
        queued.append(response.json()["id"])
    _note(rt, mid, "To'rtinchi ko'rsatma")
    busy = _post(client, auth, mid, language="ru")
    assert busy.status_code == 409 and busy.json()["code"] == "minutes_busy"
    assert busy.json()["message"] == minutes.FAILURES["minutes_busy"][1] and len(rt.store.minutes_rows(mid)) == 4
    drain(jobs)
    chain = [rt.store.minutes_row(mid, i) for i in queued]
    assert [r["status"] for r in chain] == ["ready"] * 3
    assert [(r["parent_id"], r["revision"]) for r in chain] == [(head["id"], 1), (queued[0], 2), (queued[1], 3)]
    later = _post(client, auth, mid, language="ru")
    assert later.status_code == 202 and later.json()["parentId"] == queued[-1] and later.json()["version"] == 5


def test_navbatda_yigilish_ochirilsa_model_chaqirilmaydi(client, auth, ready, jobs):
    mid, rt = ready
    assert _post(client, auth, mid, language="ru").status_code == 202
    assert client.delete(f"{BASE}/{mid}", headers=auth).status_code == 200
    drain(jobs)
    assert _calls(rt) == 0 and rt.store.minutes_rows(mid) == []


def test_eski_versiya_qayta_ishlatiladi_va_tahrir_fayl_nomi(client, auth, ready):
    """minutes-2 hujjati (deploydan oldingi) joriy - qayta bosish modelni chaqirmaydi (`READY_VERSIONS`), minutes-1
    esa qayta yoziladi. Yangi qator transkript avlodini yozadi (tahrir asosi - BASE). Tahrir qatori (`revision` 1)
    eksportida fayl nomida ham, loyiha qatorida ham versiya belgisi."""
    mid, rt = ready
    first = _post(client, auth, mid, language="uz-cyrl").json()
    row = rt.store.minutes_row(mid, first["id"])
    assert row["transcript_gen"] == rt.store.meeting_any(mid)["transcript_gen"] and row["revision"] == 0
    rt.store.update_minutes(first["id"], prompt_version="minutes-2")
    again = _post(client, auth, mid, language="uz-cyrl")
    assert again.status_code == 200 and again.json()["id"] == first["id"] and _calls(rt) == 1
    rt.store.update_minutes(first["id"], revision=1)
    url = f"{BASE}/{mid}/minutes/{first['id']}/export"
    md = client.get(f"{url}?format=md", headers=auth)
    assert md.status_code == 200 and "2-таҳрир." in md.content.decode("utf-8")
    assert quote("Баённома", safe="") in md.headers["content-disposition"]
    assert quote("(2-таҳрир)", safe="") in md.headers["content-disposition"]
    rt.store.update_minutes(first["id"], prompt_version="minutes-1")
    fresh = _post(client, auth, mid, language="uz-cyrl")
    assert fresh.status_code == 202 and fresh.json()["id"] != first["id"] and _calls(rt) == 2


def test_transkript_tahriridan_keyin_eskirgan_va_yangi_versiya(client, auth, ready):
    mid, rt = ready
    first = _post(client, auth, mid, language="ru").json()
    segment = client.get(f"{BASE}/{mid}/transcript", headers=auth).json()["segments"][0]
    edited = client.patch(f"{BASE}/{mid}/segments/{segment['id']}", json={"text": "Hisobot ertaga yuboriladi"},
                          headers=auth)
    assert edited.status_code == 200, edited.text
    assert client.get(f"{BASE}/{mid}/minutes", headers=auth).json()["items"][0]["stale"] is True
    again = _post(client, auth, mid, language="ru")
    assert again.status_code == 202 and again.json()["id"] != first["id"]
    assert again.json()["transcriptRev"] == first["transcriptRev"] + 1 and again.json()["stale"] is False


# --- xatolar --------------------------------------------------------------------------------------


def test_tez_tekshiruv_xatolari(client, auth, ready, monkeypatch):
    mid, rt = ready
    bad = _post(client, auth, mid, language="de")
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_language"
    assert _post(client, auth, "0" * 32, language="de").status_code == 400      # til - birinchi (`generate` kabi)
    missing = _post(client, auth, "0" * 32, language="ru")
    assert missing.status_code == 404 and missing.json()["code"] == "not_found"
    assert client.post(f"{BASE}/{'0' * 32}/minutes", headers=auth).status_code == 404
    unknown = client.get(f"{BASE}/{mid}/minutes/{'0' * 32}", headers=auth)
    assert unknown.status_code == 404 and unknown.json()["code"] == "minutes_not_found"
    gone = client.get(f"{BASE}/{mid}/minutes/{'0' * 32}/export", headers=auth)
    assert gone.status_code == 404 and gone.json()["code"] == "minutes_not_found"
    # Model sozlanmagan (Claude zanjiri, kalit yo'q): 503, qator ham, chegara ham yo'q.
    monkeypatch.setattr(settings, "meetings_minutes_chain", "claude", raising=False)
    off = _post(client, auth, mid, language="ru")
    assert off.status_code == 503 and off.json()["code"] == "llm_not_configured"
    assert rt.store.minutes_rows(mid) == [] and _calls(rt) == 0
    # Chegara: 1 ta - ikkinchi til 429 + Retry-After.
    monkeypatch.setattr(settings, "meetings_minutes_chain", "ollama", raising=False)
    monkeypatch.setattr(settings, "meetings_minutes_per_hour", 1, raising=False)
    assert _post(client, auth, mid, language="ru").status_code == 202
    limited = _post(client, auth, mid, language="en")
    assert limited.status_code == 429 and limited.json()["code"] == "rate_limited"
    assert int(limited.headers["retry-after"]) > 0 and len(rt.store.minutes_rows(mid)) == 1


def test_transkript_yoq_va_nutqsiz_409(client, auth, ready):
    mid, rt = ready
    fresh = create_meeting(client, auth)                                  # yuklanmagan - transkript yo'q
    early = _post(client, auth, fresh["id"], language="ru")
    assert early.status_code == 409 and early.json()["code"] == "not_ready"
    rt.store.execute("UPDATE segments SET text='  ' WHERE meeting_id=?", (mid,))
    empty = _post(client, auth, mid, language="ru")
    assert empty.status_code == 409 and empty.json()["code"] == "transcript_empty"
    assert "nutq topilmadi" in empty.json()["message"]
    assert rt.store.minutes_rows(mid) == [] and _calls(rt) == 0


def test_eksport_chizilmasa_503(client, auth, ready, monkeypatch):
    mid, _ = ready
    done = _post(client, auth, mid, language="en").json()
    url = f"{BASE}/{mid}/minutes/{done['id']}/export?format=pdf"

    def unavailable(code: str):
        def render(*args, **kwargs):
            raise export.RenderUnavailable(code)
        return render

    monkeypatch.setattr(minutes.render, "render", unavailable("pdf_unavailable"))
    broken = client.get(url, headers=auth)
    assert broken.status_code == 503 and broken.json()["code"] == "pdf_unavailable"
    monkeypatch.setattr(minutes.render, "render", unavailable("export_busy"))
    busy = client.get(url, headers=auth)
    assert busy.status_code == 503 and busy.json()["code"] == "export_busy" and busy.headers["retry-after"] == "10"


def test_begona_yigilish_404(client, auth, user_auth, ready):
    mid, rt = ready
    own = _post(client, auth, mid, language="ru").json()
    paths = (("post", f"{BASE}/{mid}/minutes", {"json": {"language": "ru"}}), ("get", f"{BASE}/{mid}/minutes", {}),
             ("get", f"{BASE}/{mid}/minutes/{own['id']}", {}),
             ("get", f"{BASE}/{mid}/minutes/{own['id']}/export", {}))
    # Bo'lim har xodimga ochiq (2026-11-16), lekin begona yig'ilish "yo'q" (404).
    for method, path, kwargs in paths:
        response = getattr(client, method)(path, headers=user_auth, **kwargs)
        assert response.status_code == 404 and response.json()["code"] == "not_found", path
    assert len(rt.store.minutes_rows(mid)) == 1 and _calls(rt) == 1


# --- eskirgan `running` qator --------------------------------------------------------------------------


def test_eskirish_chegarasi_sozlamadan(monkeypatch):
    monkeypatch.setattr(settings, "meetings_claude_timeout", 600.0, raising=False)
    monkeypatch.setattr(settings, "meetings_claude_retries", 2, raising=False)
    assert minutes.stale_after() == 600 * (1 + 3) + minutes.STALE_MARGIN_SEC == 2700   # slot + 3 urinish + zaxira
    monkeypatch.setattr(settings, "meetings_claude_timeout", 100.0, raising=False)
    monkeypatch.setattr(settings, "meetings_claude_retries", 0, raising=False)
    assert minutes.stale_after() == 100 * 2 + minutes.STALE_MARGIN_SEC


def test_eskirgan_running_interrupted_va_yangi_yozuv(client, auth, ready, jobs, monkeypatch):
    mid, rt = ready
    monkeypatch.setattr(settings, "meetings_claude_timeout", 600.0, raising=False)
    monkeypatch.setattr(settings, "meetings_claude_retries", 2, raising=False)
    rev = int(rt.store.meeting_any(mid)["transcript_rev"])
    now = time.time()

    def running(lang: str, age: float) -> str:
        """Yiqilgan / qayta ishga tushgan jarayondan qolgan qator (uni yozadigan ip yo'q)."""
        row_id = new_id()
        rt.store.insert_minutes({"id": row_id, "meeting_id": mid, "language": lang, "transcript_rev": rev,
                                 "prompt_version": minutes.prompt.MINUTES_VERSION, "status": "running",
                                 "created_at": int(now - age)})
        return row_id

    # Chegaradan yosh qator - tirik hisoblanadi: bosish unga qo'shiladi.
    alive = running("ru", minutes.stale_after() - 60)
    joined = _post(client, auth, mid, language="ru")
    assert joined.status_code == 200 and joined.json()["id"] == alive and joined.json()["status"] == "running"
    assert jobs == []
    # Chegaradan eski - holatda `failed` / `interrupted`, omborga ham yozilgan.
    dead = running("uz-cyrl", minutes.stale_after() + 60)
    body = _detail(client, auth, mid, dead)
    assert body["status"] == "failed" and body["content"] is None and body["finishedAt"]
    assert body["error"] == {"code": "interrupted", "message": minutes.INTERRUPTED}
    row = rt.store.minutes_row(mid, dead)
    assert (row["status"], row["error_code"], row["error"]) == ("failed", "interrupted", minutes.INTERRUPTED)
    # Yangi bosish uzilganiga qo'shilmaydi - yangi yozuv; ro'yxatda ham `interrupted`.
    fresh = _post(client, auth, mid, language="uz-cyrl")
    assert fresh.status_code == 202 and fresh.json()["id"] != dead and len(jobs) == 1
    drain(jobs)
    assert _detail(client, auth, mid, fresh.json()["id"])["status"] == "ready"
    # Ro'yxat ham eskirganini o'zi aniqlaydi (holat so'ralmagan bo'lsa ham).
    other = running("en", minutes.stale_after() + 5)
    items = {i["id"]: i for i in client.get(f"{BASE}/{mid}/minutes", headers=auth).json()["items"]}
    assert items[other]["status"] == "failed" and items[other]["error"]["code"] == "interrupted"
    assert items[alive]["status"] == "running" and items[dead]["error"]["code"] == "interrupted"


def test_restartdan_keyin_running_darhol_interrupted(client, auth, ready, jobs):
    """Deploy (restart) dan keyin oldingi jarayonning `running` qatori 45 daqiqa kutmaydi: ishga tushishda
    (`meetings.start` -> `minutes.recover`) darhol `interrupted`, keyingi bosish yangisini boshlaydi."""
    mid, rt = ready
    started = _post(client, auth, mid, language="uz-cyrl")
    assert started.status_code == 202 and len(jobs) == 1          # yozilmoqda - jarayon shu yerda "o'ldi"
    jobs.clear()
    young = _post(client, auth, mid, language="uz-cyrl")
    assert young.status_code == 200 and young.json()["id"] == started.json()["id"]   # hali tirik deb qo'shiladi
    assert minutes.recover(rt.store) == 1 and minutes.recover(rt.store) == 0
    body = _detail(client, auth, mid, started.json()["id"])
    assert body["status"] == "failed" and body["error"] == {"code": "interrupted", "message": minutes.INTERRUPTED}
    fresh = _post(client, auth, mid, language="uz-cyrl", force=True)
    assert fresh.status_code == 202 and fresh.json()["id"] != started.json()["id"] and len(jobs) == 1
    drain(jobs)
    assert _detail(client, auth, mid, fresh.json()["id"])["status"] == "ready"


# --- fon ishidagi xatolar ------------------------------------------------------------------------------


def test_fon_ishidagi_xatolar_qatorda_qoladi(client, auth, ready, monkeypatch):
    mid, rt = ready
    # Model yaroqsiz javob berdi - `llm_failed` (sinxron yo'lda 502 edi).
    rt.llm.script["meeting_minutes"] = ["bu JSON emas"]
    bad = _post(client, auth, mid, language="en")
    assert bad.status_code == 202
    failed = _detail(client, auth, mid, bad.json()["id"])
    assert failed["status"] == "failed" and failed["error"]["code"] == "llm_failed" and failed["content"] is None
    # Yiqilgani dedupe'ni to'smaydi: qayta bosish - yangi yozuv (model endi to'g'ri javob beradi).
    retry = _post(client, auth, mid, language="en")
    assert retry.status_code == 202 and retry.json()["id"] != bad.json()["id"]
    assert _detail(client, auth, mid, retry.json()["id"])["status"] == "ready"
    # Prompt yig'ishda kutilmagan xato (`_fill` ichida) - `internal`.
    monkeypatch.setattr(minutes.prompt, "build", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    boom = _post(client, auth, mid, language="ru")
    assert boom.status_code == 202
    assert _detail(client, auth, mid, boom.json()["id"])["error"] == {"code": "internal", "message": "RuntimeError"}
    # `_fill` dan tashqaridagi kutilmagan xato ham qatorni `running` da qoldirmaydi.
    monkeypatch.setattr(minutes, "_fill", lambda *a, **k: (_ for _ in ()).throw(KeyError("x")))
    lost = _post(client, auth, mid, language="uz-latn")
    assert lost.status_code == 202
    row = rt.store.minutes_row(mid, lost.json()["id"])
    assert (row["status"], row["error_code"], row["error"]) == ("failed", "internal", "KeyError")
    assert all(r["status"] != "running" for r in rt.store.minutes_rows(mid))
