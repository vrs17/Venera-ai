"""Yig'ilish yozuvchisi - JONLI tekshiruv (faqat qo'lda, CI da HECH QACHON). Spetsifikatsiya 8.3.

Kalitlar (`GAPI_API_KEY`, `OLLAMA_API_KEY`) sozlamalardan olinadi va HECH QACHON
chop etilmaydi; xato matnlari `_safe` / `redact` dan o'tadi. Pul yechadigan
rejimlar `--yes-spend` siz ishlamaydi.

    cd apps/api
    venv/bin/python tools/meetings_live_check.py                 # usage (bepul): GAPI balansi
    venv/bin/python tools/meetings_live_check.py gapi --file sample.aac --yes-spend [--speakers 2] [--show-text]
    venv/bin/python tools/meetings_live_check.py ollama --yes-spend [--transcript t.json] [--chars 45000]
                                                         [--num-ctx 32768] [--think false]
    venv/bin/python tools/meetings_live_check.py e2e --file sample.aac --yes-spend [--language uz] [--template auto]

`gapi`: 1-3 daqiqalik, 2+ odamli yozuvni BIR MARTA ADTS (.aac), bir marta .m4a
bilan yuboring - davomiylik, spikerlar, `diarization_error`, til, qo'llangan
`options` (loyiha defaultlari ko'rinadi), segment maydonlari va balans farqi
(diarizatsiya narxi) chiqadi. Matn faqat `--show-text` bilan. Oxirida `GET /jobs`
ro'yxatidagi maydon NOMLARI (uzilgan yuborishni tiklash `created_at` va
`estimated_seconds` ga tayanadi - ular borligini shu tasdiqlaydi).

`ollama`: sintetik o'zbek/rus transkript (`--chars`, default 30K) bilan bitta map
va bitta bir-o'tish chaqiruvi - devor vaqti, `tokensIn/out`, sekundiga token,
`done_reason`, "o'ylash" matni keldimi (`thinkingChars`), coverage, JSON
o'qildimi, tekshiruv statistikasi va TAVSIYA: `MEETINGS_EXTRACT_NUM_PREDICT`,
`MEETINGS_LLM_TIMEOUT`, `MEETINGS_LLM_THINK`. Realistik o'lchov uchun
`--chars 45000` (45 daqiqalik yig'ilish) bilan ham ishga tushiring.

`e2e`: to'liq quvur vaqtinchalik omborda - xulosa JSON va Markdown eksport
(Plaud bilan qo'lda solishtirish uchun). Vaqtinchalik papka oxirida o'chiriladi.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time

from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import ollama_key_now, settings  # noqa: E402
from app.services.analytics import redact  # noqa: E402
from app.services.integrations.gapi_stt import _safe, meeting_settings, parse_meeting_result  # noqa: E402
from app.services.meetings import Runtime, _gapi_meeting_client, _llm, _router_client, audio, export, prompts  # noqa: E402
from app.services.meetings import templates as templates_mod  # noqa: E402
from app.services.meetings.store import MeetingStore, new_id  # noqa: E402
from app.services.meetings.summarize import Validator, call_llm, parse_json  # noqa: E402
from app.services.meetings.transcribe import Transcriber, normalize  # noqa: E402
from app.services.meetings.worker import run_summaries  # noqa: E402
from app.services.stt import SttError  # noqa: E402


def _say(text: str) -> None:
    print(redact(text, limit=0) if text else text)


def _need_spend(args: argparse.Namespace) -> None:
    if not args.yes_spend:
        sys.exit("Bu rejim PULLIK - ishonchingiz komil bo'lsa --yes-spend qo'shing.")


def _content_type(path: Path) -> str:
    return "audio/mp4" if path.suffix.lower() in (".m4a", ".mp4") else "audio/aac"


# --- usage -----------------------------------------------------------------------------


def cmd_usage(_: argparse.Namespace) -> None:
    client = _gapi_meeting_client()
    if not client.configured:
        sys.exit("GAPI_API_KEY sozlanmagan (.env)")
    try:
        usage = client.usage()
    except SttError as exc:
        sys.exit(f"GAPI usage xatosi: {_safe(str(exc), settings.gapi_api_key)}")
    _say(f"available_g: {usage.get('available_g')}  topup_target_g: {usage.get('topup_target_g')}")
    _say(f"usage kalitlari: {sorted(usage.keys())}")


# --- gapi ------------------------------------------------------------------------------


def cmd_gapi(args: argparse.Namespace) -> None:
    _need_spend(args)
    path = Path(args.file)
    client = _gapi_meeting_client()
    if not client.configured:
        sys.exit("GAPI_API_KEY sozlanmagan (.env)")
    ctype = _content_type(path)
    measured = audio.measure(path, ctype)
    _say(f"fayl: {path.name} ({ctype}), {path.stat().st_size} bayt, o'lchangan davomiylik: {measured} s")
    before = client.usage().get("available_g")
    sent = meeting_settings(args.speakers)
    _say(f"yuborilgan sozlamalar: {json.dumps(sent)}")
    started = time.time()
    try:
        job = client.submit_job(path, ctype, sent)
        _say(f"[{time.time() - started:6.1f}s] vazifa {job['id']}: {job['state']}, taxmin {job['estimatedSeconds']} s")
        while True:
            state = client.get_job(job["id"])
            _say(f"[{time.time() - started:6.1f}s] holat: {state.get('state')} "
                 f"progress_seconds={state.get('progress_seconds')} audio_seconds={state.get('audio_seconds')}")
            if state.get("state") in ("done", "failed", "cancelled"):
                break
            time.sleep(3 if time.time() - started < 60 else 10)
        if state.get("state") != "done":
            sys.exit(f"vazifa tugamadi: {state.get('state')}")
        payload = client.get_result(job["id"], job.get("resultUrl"))
    except SttError as exc:
        sys.exit(f"GAPI xatosi: {_safe(str(exc), settings.gapi_api_key)} "
                 f"(status={getattr(exc, 'gapi_status', None)}, code={getattr(exc, 'gapi_code', '')})")
    raw = parse_meeting_result(payload)
    _say(f"natija kalitlari: {raw.keys}")
    _say(f"audio_seconds={raw.audio_seconds} speakers={raw.speakers} diarization_error={raw.diarization_error}")
    _say(f"language: {json.dumps(raw.language, ensure_ascii=False)}")
    _say(f"qo'llangan options: {json.dumps(raw.options, ensure_ascii=False)}")
    if raw.segments:
        _say(f"segment maydonlari: {sorted(raw.segments[0].keys())}")
    norm = normalize(raw)
    _say(f"normallashtirilgan: {len(norm['segments'])} segment, spikerlar: "
         f"{[(s['id'], s['talkSec']) for s in norm['speakers']]}, ogohlantirish: {norm['languageWarning']}")
    for seg in norm["segments"][:5]:
        text = f" {seg['text']}" if args.show_text else ""
        _say(f"  #{seg['id']} {seg['speaker']} {seg['start']}-{seg['end']}{text}")
    try:
        jobs = client.list_jobs(limit=5)
        mine = next((j for j in jobs if str(j.get("id")) == job["id"]), None)
        _say(f"GET /jobs: {len(jobs)} ta; maydonlar: {sorted((jobs[0] if jobs else {}).keys())}; "
             f"bizniki ro'yxatda: {'ha' if mine else 'YOQ'}; created_at={'bor' if (mine or {}).get('created_at') else 'YOQ'}, "
             f"estimated_seconds={(mine or {}).get('estimated_seconds')}")
    except SttError as exc:
        _say(f"GET /jobs xatosi: {_safe(str(exc), settings.gapi_api_key)}")
    after = client.usage().get("available_g")
    _say(f"balans: {before} -> {after} (farq: {None if before is None or after is None else round(before - after, 3)} g)")


# --- ollama ----------------------------------------------------------------------------

_UZ = ["Men ertaga hisobotni tayyorlab yuboraman.", "Narxni 15 mln so'm qilib belgilashga kelishdik.",
       "Juma kuni mijoz bilan gaplashaman.", "Dizaynni chorshanbagacha tekshirib chiqing, iltimos.",
       "Byudjet masalasi hali ochiq, buxgalteriya javob bermadi.", "Xo'p, men olaman bu vazifani."]
_RU_LATIN = ["Ladno, ya prishlyu otchet do pyatnitsy.", "Dogovorilis, zavtra sozvon v 15:00.",
             "Nado proverit' integratsiyu s CRM.", "Horosho, beru na sebya."]


def _synthetic(target_chars: int = 25000) -> list[dict]:
    segments, t, i = [], 0.0, 0
    while sum(len(s["text"]) + 20 for s in segments) < target_chars:
        pool = _UZ if i % 3 else _RU_LATIN
        text = f"{pool[i % len(pool)]} ({i})"
        segments.append({"id": i + 1, "start": t, "end": t + 6.0, "speaker": f"S{i % 3 + 1}", "text": text})
        t += 6.5
        i += 1
    return segments


def _one(llm, name: str, system: str, user: str, last_id: int, segments: list[dict], *, num_predict: int,
         op: str, num_ctx: int, think: bool | None = None) -> dict:
    started = time.time()
    text, meta = call_llm(llm, system, user, num_predict=num_predict, temperature=0.1, op=op, num_ctx=num_ctx,
                          think=think)
    elapsed = time.time() - started
    data, salvaged = parse_json(text)
    checker = Validator(segments=segments, speakers={"S1", "S2", "S3"}, names=[], meeting_day=date.today())
    items = checker.items(data) if data else {}
    cov = checker.coverage_last(data) if data else None
    estimated = int((len(system) + len(user)) / 2.2)
    out_tokens = meta.get("tokensOut") or 0
    _say(f"{name}: {elapsed:.1f} s, tokensIn={meta.get('tokensIn')} (taxmin {estimated}), "
         f"tokensOut={meta.get('tokensOut')} (num_predict {num_predict}), "
         f"{(out_tokens / elapsed) if elapsed else 0:.1f} tok/s, done_reason={meta.get('doneReason')}, "
         f"thinkingChars={meta.get('thinkingChars')}, javob {len(text)} belgi, "
         f"json={'qutqarilgan' if salvaged else ('ha' if data else 'YOQ')}, coverage.lastId={cov} "
         f"(kutilgan {last_id}, {'mos' if cov == last_id else 'MOS EMAS'})")
    _say(f"   tekshiruv: jami={checker.total} yaroqsiz={checker.invalid} tashlangan={checker.dropped} "
         f"vazifalar={len(items.get('actionItems') or [])} qarorlar={len(items.get('decisions') or [])}")
    return {"elapsed": elapsed, "tokensOut": out_tokens, "doneReason": meta.get("doneReason"),
            "thinkingChars": meta.get("thinkingChars") or 0}


def cmd_ollama(args: argparse.Namespace) -> None:
    _need_spend(args)
    llm = _llm(1, settings.meetings_llm_timeout)
    if not llm.configured:
        sys.exit("OLLAMA_API_KEY sozlanmagan (.env)")
    if args.transcript:
        segments = json.loads(Path(args.transcript).read_text(encoding="utf-8"))
    else:
        segments = _synthetic(args.chars)
    lines = [prompts.transcript_line(s, {}) for s in segments]
    _say(f"model: {llm.model}, {len(segments)} qator, {sum(len(x) + 1 for x in lines)} belgi, "
         f"timeout {settings.meetings_llm_timeout:.0f} s")
    meta = prompts.meta_line(date.today(), "Friday", segments[-1]["end"],
                             [{"id": "S1"}, {"id": "S2"}, {"id": "S3"}], True)
    think = {"false": False, "true": True}.get(args.think)
    runs: list[dict] = []
    for num_ctx in ([0, args.num_ctx] if args.num_ctx else [0]):
        suffix = f" num_ctx={num_ctx}" if num_ctx else ""
        user_map = prompts.user_message(meta=meta, language="uz", template_id="general", marks="", running="",
                                        lines=lines)
        try:
            runs.append(_one(llm, "map" + suffix, prompts.map_system(), user_map, segments[-1]["id"], segments,
                             num_predict=settings.meetings_map_num_predict, op="meeting_map", num_ctx=num_ctx,
                             think=think))
            runs.append(_one(llm, "bir-o'tish" + suffix, prompts.extract_system("general"), user_map,
                             segments[-1]["id"], segments, num_predict=settings.meetings_extract_num_predict,
                             op="meeting_extract", num_ctx=num_ctx, think=think))
        except Exception as exc:                                       # noqa: BLE001
            _say(f"xato: {_safe(str(exc), ollama_key_now())}")
    if runs:
        most = max(r["tokensOut"] for r in runs)
        slowest = max(r["elapsed"] for r in runs)
        cut = any(r["doneReason"] == "length" for r in runs)
        _say("TAVSIYA (.env, o'lchovdan):")
        _say(f"  MEETINGS_EXTRACT_NUM_PREDICT >= {int(most * 1.5) or settings.meetings_extract_num_predict}"
             f"{'  (javob KESILDI - num_predict yoki MEETINGS_SINGLE_PASS_CHARS ni o`zgartiring)' if cut else ''}")
        _say(f"  MEETINGS_LLM_TIMEOUT >= {int(slowest * 1.5) + 30}")
        if any(r["thinkingChars"] for r in runs):
            _say("  model 'o'ylash' matni qaytardi - MEETINGS_LLM_THINK=false bilan qayta o'lchang (--think false)")


# --- e2e -------------------------------------------------------------------------------


#: e2e: ijara egasi - quvur har model chaqiruvidan keyin ijarani SHU nom bilan yangilaydi.
E2E_OWNER = "e2e"
#: Transkripsiya qadamlari (3 s / 10 s so'rov, 1 soatlik muddat) va xulosa urinishlari chegarasi.
E2E_MAX_STEPS = 600
E2E_SUMMARY_ROUNDS = 6
#: Model shundan uzoq kutishni so'rasa (429) - pul yoqmasdan to'xtaymiz.
E2E_MAX_WAIT = 900


def insert_e2e_meeting(store: MeetingStore, *, audio_path: Path, ctype: str, duration: float, language: str,
                       template: str, size: int) -> str:
    """Vaqtinchalik omborga yig'ilish - IJARA bilan (`lease_owner='e2e'`): aks holda quvurning
    `renew` chaqiruvi hech narsaga mos kelmay, har model chaqiruvidan keyin to'xtardi."""
    now = int(time.time())
    mid = new_id()
    store.insert_meeting({"id": mid, "actor_id": 0, "client_id": new_id(), "title": "e2e", "language": language,
                          "template": template, "status": "uploaded", "summary_status": "none",
                          "recorded_at": now, "created_at": now, "updated_at": now, "content_type": ctype,
                          "duration_sec": duration, "audio_path": str(audio_path), "completed_at": now,
                          "total_bytes": size, "channel": "api", "lease_owner": E2E_OWNER,
                          "lease_until": now + 10 * 365 * 86400})
    return mid


def run_e2e(rt: Runtime, mid: str, *, sleep=time.sleep, clock=time.time, say=_say,
            max_steps: int = E2E_MAX_STEPS, summary_rounds: int = E2E_SUMMARY_ROUNDS) -> dict:
    """Transkripsiya + xulosa. CHEKLANGAN: qadamlar soni, xulosa urinishlari, uzoq kutish
    (429) va "oldinga siljimadi" - har biri xato bilan to'xtaydi (pullik chaqiruvlar cheksiz takrorlanmaydi)."""
    store = rt.store
    transcriber = Transcriber(rt)
    started = clock()
    for _ in range(max_steps):
        m = store.meeting_any(mid)
        if m["status"] in ("summarizing", "ready", "failed", "waiting_quota"):
            break
        transcriber.step(m, clock(), E2E_OWNER)
        m = store.meeting_any(mid)
        say(f"[{clock() - started:6.1f}s] {m['status']} progress={m.get('progress')} xato={m.get('error_code')}")
        wait = max(0.0, float(m.get("next_attempt_at") or 0) - clock())
        if m["status"] in ("transcribing", "uploaded"):
            sleep(min(10.0, wait))
    else:
        raise SystemExit(f"transkripsiya {max_steps} qadamda tugamadi")
    m = store.meeting_any(mid)
    if m["status"] in ("failed", "waiting_quota"):
        raise SystemExit(f"transkripsiya tugamadi: {m['status']} {m.get('error_code')}")

    def state() -> tuple:
        s = store.summary(mid, m["primary_summary_id"]) if m.get("primary_summary_id") else None
        return (m["status"], (s or {}).get("status"), (s or {}).get("attempts"), m.get("retries"),
                m.get("next_attempt_at"))

    for _ in range(summary_rounds):
        m = store.meeting_any(mid)
        if m["status"] != "summarizing":
            break
        before = state()
        run_summaries(rt, m, clock(), owner=E2E_OWNER)
        m = store.meeting_any(mid)
        if m["status"] != "summarizing":
            break
        if state() == before:
            raise SystemExit("xulosa oldinga siljimadi (ijara yoki navbat) - to'xtatildi")
        wait = float(m.get("next_attempt_at") or 0) - clock()
        if wait > E2E_MAX_WAIT:
            raise SystemExit(f"model {wait:.0f} s kutishni so'radi (429?) - keyinroq qayta ishga tushiring")
        say(f"[{clock() - started:6.1f}s] xulosa qayta urinadi, {max(1.0, wait):.0f} s dan keyin")
        sleep(max(1.0, wait))
    else:
        raise SystemExit(f"xulosa {summary_rounds} urinishda tugamadi")
    return store.meeting_any(mid)


def cmd_e2e(args: argparse.Namespace) -> None:
    _need_spend(args)
    path = Path(args.file)
    ctype = _content_type(path)
    duration = audio.measure(path, ctype)
    if not duration:
        sys.exit("audio o'qilmadi (ADTS .aac yoki .m4a kerak)")
    tmp = Path(tempfile.mkdtemp(prefix="venera-meet-e2e-"))
    try:
        store = MeetingStore(tmp / "meetings")
        rt = Runtime(store=store, gapi=_gapi_meeting_client(), router=_router_client(),
                     llm=_llm(1, settings.meetings_llm_timeout), ask_llm=_llm(1, 120.0))
        audio_path = store.audio_dir(0) / f"e2e{path.suffix.lower()}"
        shutil.copyfile(path, audio_path)
        now = int(time.time())
        started = time.time()
        mid = insert_e2e_meeting(store, audio_path=audio_path, ctype=ctype, duration=duration,
                                 language=args.language, template=args.template, size=path.stat().st_size)
        m = run_e2e(rt, mid)
        summary = store.summary(mid, m["primary_summary_id"])
        _say(f"xulosa: {summary['status']} ({summary.get('error_code')}), shablon {summary['template']}, "
             f"{time.time() - started:.1f} s")
        if summary["status"] != "ready":
            return
        content = json.loads(summary["content_json"])
        print(json.dumps(content, ensure_ascii=False, indent=2))
        speakers = {sp["id"]: sp for sp in store.speakers(mid)}
        print("\n" + "=" * 70 + "\n")
        print(export.summary_document(content, templates_mod.layout(summary["template"], summary["language"]),
                                      speakers, summary["language"], now, markdown=True))
        store.close_all()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Venera Yozuv - jonli tekshiruv (kalitlar chop etilmaydi)")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("usage", help="GAPI balansi (bepul)")
    g = sub.add_parser("gapi", help="bitta yozuvni diarizatsiya bilan o'girish (PULLIK)")
    g.add_argument("--file", required=True)
    g.add_argument("--speakers", type=int, default=None)
    g.add_argument("--show-text", action="store_true")
    g.add_argument("--yes-spend", action="store_true")
    o = sub.add_parser("ollama", help="map + bir-o'tish chaqiruvi (PULLIK)")
    o.add_argument("--transcript", default=None, help="[{id,start,end,speaker,text}] JSON fayl")
    o.add_argument("--chars", type=int, default=30000, help="sintetik transkript hajmi (belgi)")
    o.add_argument("--num-ctx", type=int, default=0)
    o.add_argument("--think", default=None, choices=("false", "true"), help="Ollama think (default: yuborilmaydi)")
    o.add_argument("--yes-spend", action="store_true")
    e = sub.add_parser("e2e", help="to'liq quvur vaqtinchalik omborda (PULLIK)")
    e.add_argument("--file", required=True)
    e.add_argument("--language", default="uz", choices=("uz", "ru", "en"))
    e.add_argument("--template", default="auto", choices=templates_mod.TEMPLATE_IDS[:-1])
    e.add_argument("--yes-spend", action="store_true")
    args = parser.parse_args(argv)
    {"gapi": cmd_gapi, "ollama": cmd_ollama, "e2e": cmd_e2e}.get(args.cmd or "usage", cmd_usage)(args)


if __name__ == "__main__":
    main()
