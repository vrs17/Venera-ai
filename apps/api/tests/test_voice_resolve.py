"""NUSXA OVOZLARNI TUZATISH (2026-11-18, jonli muammo: xodim namuna yozgan, lekin yig'ilishda «Noma'lum»).

GAPI bitta odamga ikki ovoz ochib qo'ysa (namunasi alohida, yig'ilishdagi ovozi alohida) - ikkalasi orasida
tanlamaydi va odamni har safar "yangi ovoz" deb yozadi. `voice.resolve_meeting` (yig'ilishdan keyin) va `voice.sweep`
(yangi namunadan keyin) spikerning nutq parchasini "faqat xodimlar" maydonida qayta solishtiradi, nusxa ovozni
o'chiradi va O'TGAN yig'ilishlarga ham ism qo'yadi. GAPI soxta - tarmoqqa chiqilmaydi.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.meetings import audio, voice
from meetings_fakes import adts_bytes, enable, gapi_error, recorded, run_all
from test_voice_samples import AUDIO, FakeVoiceGapi, _Inline, person_of, post, result

TENANT = "barno-staff"


class FakeStaffGapi(FakeVoiceGapi):
    """Loyiha ovozlari + "faqat xodimlar" maydoni (`tenant`). `probes` - `enroll: off` solishtirish javoblari."""

    def __init__(self, accounts=(1,)) -> None:
        super().__init__(accounts)
        self.staff: dict[int, dict[str, str]] = {a: {} for a in self.accounts}       # hisob -> {ovoz: nom}
        self.staff_results: dict[int, list] = {a: [] for a in self.accounts}
        self.probes: list = []
        self.prints: dict[str, int] = {}
        self.clips: dict[str, bytes] = {}

    def transcribe_sample(self, audio, content_type, *, account=1, tenant=None, enroll=None):
        if not tenant:
            return super().transcribe_sample(audio, content_type, account=account)
        assert tenant == TENANT
        if enroll == "off":
            self.calls.append(("probe", account, content_type, len(audio)))
            item = self.probes.pop(0) if self.probes else probe()
            if isinstance(item, Exception):
                raise item
            return item, f"probe-{len(self.calls)}"
        self.calls.append(("staff", account, content_type))
        queue = self.staff_results[account]
        if queue:
            item = queue.pop(0)
        else:                                               # odatiy: maydonda yangi ovoz ochiladi
            key = f"st-{account}-{len(self.staff[account]) + 1}"
            item = result("new", 100 + len(self.staff[account]), key)
        if isinstance(item, Exception):
            raise item
        key = item["speaker_info"][0]["identity"].get("speaker_id")
        if key and item["speaker_info"][0]["identity"].get("status") == "new":
            self.staff[account].setdefault(key, "")
        return item, f"staffjob-{account}-{len(self.calls)}"

    def speakers(self, *, account=1, tenant=None):
        if tenant:
            return [{"id": key, "name": name, "number": 100 + n} for n, (key, name) in enumerate(self.staff[account].items())]
        self.calls.append(("list", account))
        return [{"id": key, "voiceprints": count} for key, count in self.prints.items()]

    def create_speaker(self, name, *, account=1, tenant=None):
        if tenant:
            key = f"st-{account}-new{len(self.staff[account]) + 1}"
            self.staff[account][key] = name
            self.calls.append(("staff-create", account, name))
            return {"id": key, "number": 150, "name": name}
        return super().create_speaker(name, account=account)

    def rename_speaker(self, speaker_id, name, *, account=1):
        if speaker_id in self.staff[account]:
            self.staff[account][speaker_id] = name
        return super().rename_speaker(speaker_id, name, account=account)

    def delete_speaker(self, speaker_id, *, account=1):
        self.staff[account].pop(speaker_id, None)
        return super().delete_speaker(speaker_id, account=account)

    def speaker_clip(self, speaker_id, *, account=1):
        self.calls.append(("clip", account, speaker_id))
        if speaker_id not in self.clips:
            raise gapi_error(404, "no_sample")
        return self.clips[speaker_id]


def probe(person: int | None = None, score: float = 0.3):
    """Solishtirish javobi: `person` - maydonda mos kelgan xodim (`barno-<id>`), bo'lmasa notanish."""
    identity = ({"status": "matched", "name": f"barno-{person}", "voice_id": 100, "speaker_id": "st-x", "score": score}
                if person is not None else {"status": "unknown", "score": score})
    return {"segments": [], "speech_seconds": 20.0,
            "speaker_info": [{"index": 0, "speech_seconds": 20.0, "identity": identity}]}


@pytest.fixture
def fake(monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    monkeypatch.setattr(settings, "voice_resolve_enabled", True, raising=False)
    monkeypatch.setattr(settings, "voice_staff_tenant", TENANT, raising=False)
    voice._staff_forget()
    gapi = FakeStaffGapi()
    _isolated_meetings.voice_gapi = gapi
    monkeypatch.setattr(voice, "_pool", _Inline())
    yield gapi
    voice._staff_forget()


def info(*identities):
    return [{"index": n, "speech_seconds": 25.0, "identity": dict(i)} for n, i in enumerate(identities)]


def meeting(client, auth, rt, speaker_info):
    rt.gapi.states = ["processing", "done"]
    rt.gapi.result["speaker_info"] = speaker_info
    item, _ = recorded(client, auth)
    run_all(rt)
    return item["id"]


def speakers(client, auth, meeting_id):
    body = client.get(f"/api/v1/meetings/{meeting_id}/transcript", headers=auth).json()
    return {sp["id"]: sp for sp in body["speakers"]}


def enroll(client, auth, fake, key="sp-own", **identity):
    """Xodim (Administrator) namuna yozadi: loyihada `key` ovozi, maydonda `barno-<id>`."""
    payload = result("new", 100, key)
    payload["speaker_info"][0]["identity"].update(identity or {"score": 0.2})
    fake.results[1].append(payload)
    body = post(client, auth).json()
    assert body["status"] == "ok", body
    return body


# --- "faqat xodimlar" maydoni ---------------------------------------------------------------


def test_namuna_xodimlar_maydoniga_ham_yoziladi(client, auth, fake, _isolated_meetings):
    enroll(client, auth, fake)
    pid = person_of(_isolated_meetings)["id"]
    assert fake.staff[1] == {"st-1-1": f"barno-{pid}"}
    assert ("staff", 1, "audio/ogg") in fake.calls and fake.ops("probe") == []      # o'xshash ovoz yo'q - tekshiruv yo'q
    assert _isolated_meetings.store.row("SELECT result_json FROM voice_samples")["result_json"].count('"staff":"created"') == 1


def test_ikkinchi_namuna_maydondagi_oz_ovoziga_qoshiladi_nomsizi_tozalanadi(client, auth, fake, _isolated_meetings):
    enroll(client, auth, fake)
    pid = person_of(_isolated_meetings)["id"]
    # Ikkinchi namuna maydonda o'z ovoziga mos kelmay yangi ovoz ochdi (boshqa mikrofon) - izi o'z ovoziga, yangisi o'chadi.
    fake.staff_results[1].append(result("new", 101, "st-stray"))
    fake.results[1].append(result("matched", 100, "sp-own"))
    assert post(client, auth).json()["status"] == "ok"
    assert fake.staff[1] == {"st-1-1": f"barno-{pid}"}
    assert any(c[0] == "enroll" and c[2] == "st-1-1" for c in fake.calls)
    assert ("delete", 1, "st-stray") in fake.calls


def test_maydonda_boshqa_xodimga_mos_kelsa_qoshilmaydi(client, auth, fake, _isolated_meetings):
    fake.staff[1]["st-other"] = "barno-99"
    payload = result("matched", 100, "st-other")
    payload["speaker_info"][0]["identity"]["name"] = "barno-99"
    fake.staff_results[1].append(payload)
    enroll(client, auth, fake)
    assert fake.staff[1] == {"st-other": "barno-99"}                               # maydon o'zgarmadi
    assert '"staff":"conflict"' in _isolated_meetings.store.row("SELECT result_json FROM voice_samples")["result_json"]


def test_ochirishda_maydondagi_ovoz_ham_ochadi(client, auth, fake, _isolated_meetings):
    enroll(client, auth, fake)
    assert client.delete("/api/v1/voice-sample", headers=auth).status_code == 200
    assert fake.staff[1] == {} and ("delete", 1, "st-1-1") in fake.calls


def test_maydon_xatosi_namunani_buzmaydi(client, auth, fake, _isolated_meetings):
    fake.staff_results[1].append(gapi_error(503, "busy", retryable=True))
    fake.results[1].append(result("new", 100, "sp-own"))
    assert post(client, auth).json()["status"] == "ok"
    assert [r["speaker_key"] for r in _isolated_meetings.store.rows("SELECT speaker_key FROM voice_links")] == ["sp-own"]


# --- yig'ilishdan keyin ---------------------------------------------------------------------


def test_yangi_lekin_oxshash_ovoz_xodimga_birlashadi(client, auth, fake, _isolated_meetings):
    """Jonli holat: xodim namuna yozgan, lekin GAPI yig'ilishda uni "yangi ovoz" dedi (o'xshashlik 0.74 - boshqa
    nusxa ovoz bilan teng). Nutq parchasi xodimlar maydonida mos keladi -> ism qo'yiladi, nusxa ovoz o'chadi,
    yig'ilishdagi nutq xodimning ovoziga iz bo'ladi."""
    rt = _isolated_meetings
    enroll(client, auth, fake)
    pid = person_of(rt)["id"]
    fake.probes = [probe(pid, 0.87)]
    mid = meeting(client, auth, rt, info(
        {"status": "new", "voice_id": 109, "speaker_id": "sp-dup", "score": 0.742, "runner_up": 0.718},
        {"status": "new", "voice_id": 110, "speaker_id": "sp-guest", "score": 0.21}))
    got = speakers(client, auth, mid)
    assert got["S1"]["name"] == "Administrator" and got["S1"]["nameSource"] == "voice" and got["S1"]["personId"] == pid
    assert got["S1"]["voiceScore"] == 0.87
    assert got["S2"]["name"] is None and got["S2"]["personId"] not in (None, pid)   # chin mehmon - raqami bilan
    probes = fake.ops("probe")
    assert len(probes) == 1 and probes[0][2] == "audio/aac" and probes[0][3] > 4000  # faqat o'xshashi, audio parchasi
    assert ("enroll", 1, "sp-own", "job-1", 0) in fake.calls                          # yig'ilishdagi nutq - xodim ovoziga
    assert ("staff", 1, "audio/aac") not in fake.calls                                # 0.87 - maydon bu sharoitni biladi
    assert ("delete", 1, "sp-dup") in fake.calls and ("delete", 1, "sp-guest") not in fake.calls
    keys = [r["speaker_key"] for r in rt.store.rows("SELECT speaker_key FROM voice_links ORDER BY speaker_key")]
    assert keys == ["sp-guest", "sp-own"]
    assert rt.store.scalar("SELECT COUNT(*) FROM voice_persons WHERE kind='guest'", (), 0) == 1


def test_mos_kelmagan_mehmon_qoladi_va_qayta_tekshirilmaydi(client, auth, fake, _isolated_meetings):
    rt = _isolated_meetings
    enroll(client, auth, fake)
    fake.probes = [probe(None, 0.31)]
    first = meeting(client, auth, rt, info({"status": "new", "voice_id": 109, "speaker_id": "sp-g", "score": 0.6}))
    guest = speakers(client, auth, first)["S1"]["personId"]
    assert speakers(client, auth, first)["S1"]["name"] is None and len(fake.ops("probe")) == 1
    assert rt.store.row("SELECT checked_at FROM voice_persons WHERE id=?", (guest,))["checked_at"]
    # Shu mehmon yana keldi (GAPI: tanish ovoz) - yangi namuna bo'lmagan, qayta solishtirilmaydi (pul tejaladi).
    second = meeting(client, auth, rt, info({"status": "matched", "voice_id": 109, "speaker_id": "sp-g", "score": 0.9}))
    assert speakers(client, auth, second)["S1"]["personId"] == guest and len(fake.ops("probe")) == 1


def test_oxshamagan_yangi_ovoz_va_xodimsiz_holat_tekshirilmaydi(client, auth, fake, _isolated_meetings):
    rt = _isolated_meetings
    meeting(client, auth, rt, info({"status": "new", "voice_id": 109, "speaker_id": "sp-a", "score": 0.9}))
    assert fake.ops("probe") == [] and fake.ops("staff") == []                      # namuna yozgan xodim yo'q
    enroll(client, auth, fake)
    meeting(client, auth, rt, info({"status": "new", "voice_id": 110, "speaker_id": "sp-b", "score": 0.25}))
    assert fake.ops("probe") == []                                                  # hech kimga o'xshamaydi - chin yangi odam


def test_eski_mehmon_ovozi_xodim_bolib_chiqsa_otgan_yigilishlari_ham(client, auth, fake, _isolated_meetings):
    """Xodimning nutqi eski NOMSIZ ovozga tushgan (jonli: #101, diktovkadan qolgan): shu ovoz bilan o'tgan
    yig'ilishlar ham xodimniki - mehmon shaxs qo'shiladi, eski ovoz o'chadi."""
    rt = _isolated_meetings
    old = meeting(client, auth, rt, info({"status": "new", "voice_id": 101, "speaker_id": "sp-old", "score": 0.1}))
    guest = speakers(client, auth, old)["S1"]["personId"]
    enroll(client, auth, fake)
    pid = person_of(rt)["id"]
    fake.probes = [probe(pid, 0.83)]
    new = meeting(client, auth, rt, info({"status": "matched", "voice_id": 101, "speaker_id": "sp-old", "score": 0.739}))
    assert speakers(client, auth, new)["S1"]["name"] == "Administrator"
    assert speakers(client, auth, old)["S1"]["name"] == "Administrator"             # o'tgan yig'ilish ham
    assert rt.store.row("SELECT id FROM voice_persons WHERE id=?", (guest,)) is None
    assert ("delete", 1, "sp-old") in fake.calls and ("enroll", 1, "sp-own", "job-2", 0) in fake.calls
    # Chegaraga yaqin moslik (0.83 < 0.85): yig'ilishdagi nutq MAYDONDAGI ovozga ham iz bo'ladi (keyingi safar aniqroq).
    assert ("staff", 1, "audio/aac") in fake.calls and any(c[0] == "enroll" and c[2] == "st-1-1" for c in fake.calls)
    assert fake.staff[1] == {"st-1-1": f"barno-{pid}"}                              # maydonda yana bitta ovoz - yo'q


def test_audio_bolmasa_gapi_dagi_parcha(client, auth, fake, _isolated_meetings, monkeypatch):
    rt = _isolated_meetings
    enroll(client, auth, fake)
    pid = person_of(rt)["id"]
    monkeypatch.setattr(voice, "_meeting_clip", lambda *a, **k: None)
    fake.clips["sp-dup"] = b"RIFF" + b"\x00" * 6000
    fake.probes = [probe(pid, 0.8)]
    mid = meeting(client, auth, rt, info({"status": "new", "voice_id": 109, "speaker_id": "sp-dup", "score": 0.7}))
    assert speakers(client, auth, mid)["S1"]["name"] == "Administrator"
    assert ("clip", 1, "sp-dup") in fake.calls and fake.ops("probe")[0][2] == "audio/wav"


def test_solishtirish_xatosi_transkriptni_buzmaydi(client, auth, fake, _isolated_meetings):
    rt = _isolated_meetings
    enroll(client, auth, fake)
    fake.probes = [gapi_error(503, "busy", retryable=True)]
    mid = meeting(client, auth, rt, info({"status": "new", "voice_id": 109, "speaker_id": "sp-dup", "score": 0.7}))
    got = speakers(client, auth, mid)["S1"]
    assert got["name"] is None and got["personId"] is not None
    assert client.get(f"/api/v1/meetings/{mid}", headers=auth).json()["status"] == "ready"


def test_gapi_tanigan_xodim_nutqi_ovoziga_iz_boladi(client, auth, fake, _isolated_meetings):
    rt = _isolated_meetings
    enroll(client, auth, fake)
    fake.prints = {"sp-own": 1}
    matched = {"status": "matched", "voice_id": 100, "speaker_id": "sp-own", "score": 0.75, "runner_up": 0.3}
    meeting(client, auth, rt, info(matched))
    assert ("enroll", 1, "sp-own", "job-1", 0) in fake.calls
    # Ikkinchi iz yaqin bo'lsa ham qo'shiladi: u shu ovozning o'z izi bo'lishi mumkin (jonli: 0.913 / 0.875).
    meeting(client, auth, rt, info({**matched, "runner_up": 0.72}))
    assert ("enroll", 1, "sp-own", "job-2", 0) in fake.calls
    # Ovoz bu sharoitni yaxshi biladi (0.93) yoki izlar chegarada - qo'shilmaydi.
    before = len(fake.ops("enroll"))
    meeting(client, auth, rt, info({**matched, "score": 0.93}))
    fake.prints = {"sp-own": settings.voice_prints_max}
    meeting(client, auth, rt, info(matched))
    assert len(fake.ops("enroll")) == before


# --- yangi namunadan keyin: O'TGAN yig'ilishlar ----------------------------------------------


def test_namunadan_keyin_otgan_yigilishdagi_nomalum_ismlanadi(client, auth, fake, _isolated_meetings):
    """Ega talabi (2026-11-18): yig'ilishda namunasi yo'q spiker «Noma'lum #N» bo'ldi; u KEYIN namuna yozsa -
    o'sha yig'ilishda ham ismi chiqsin. GAPI namunani mehmon ovoziga o'zi bog'lay olmagan holat (ikki nusxa)."""
    rt = _isolated_meetings
    mid = meeting(client, auth, rt, info(
        {"status": "new", "voice_id": 105, "speaker_id": "sp-g", "score": 0.1},
        {"status": "new", "voice_id": 106, "speaker_id": "sp-h", "score": 0.2}))
    before = speakers(client, auth, mid)
    assert before["S1"]["name"] is None and before["S2"]["name"] is None and fake.ops("probe") == []
    pid_holder = {}

    def answer():                                           # birinchi mehmon - shu xodim, ikkinchisi - notanish
        return probe(pid_holder["id"], 0.85)

    class Lazy(list):
        def pop(self, index=0):
            return answer() if not self.served else probe(None, 0.3)

        def __bool__(self):
            return True

    lazy = Lazy()
    lazy.served = 0
    original = FakeStaffGapi.transcribe_sample

    def spy(self, data, content_type, *, account=1, tenant=None, enroll=None):
        if tenant and enroll == "off":
            pid_holder["id"] = person_of(rt)["id"]
            out = original(self, data, content_type, account=account, tenant=tenant, enroll=enroll)
            lazy.served += 1
            return out
        return original(self, data, content_type, account=account, tenant=tenant, enroll=enroll)

    fake.probes = lazy
    FakeStaffGapi.transcribe_sample = spy
    try:
        body = enroll(client, auth, fake, score=0.74)        # mavjud ovozga o'xshash, lekin GAPI bog'lamadi
    finally:
        FakeStaffGapi.transcribe_sample = original
    pid = person_of(rt)["id"]
    assert body["message"] == voice.OK_TEXT + voice.RETRO_TEXT.format(n=1)
    after = speakers(client, auth, mid)
    named = [sp for sp in after.values() if sp["name"] == "Administrator"]
    assert len(named) == 1 and named[0]["personId"] == pid and named[0]["nameSource"] == "voice"
    assert len(fake.ops("probe")) == 2                                              # ikkala mehmon tekshirildi
    assert sum(1 for c in fake.calls if c[0] == "delete" and c[2] in ("sp-g", "sp-h")) == 1   # faqat nusxasi o'chdi
    assert any(c[0] == "enroll" and c[2] == "sp-own" and c[3] == "job-1" for c in fake.calls)
    assert rt.store.scalar("SELECT COUNT(*) FROM voice_persons WHERE kind='guest'", (), 0) == 1
    # Holatda ham ko'rinadi (mobil ilova, Telegram va Slack shu matnni ko'rsatadi).
    assert client.get("/api/v1/voice-sample", headers=auth).json()["latest"]["message"].endswith(
        voice.RETRO_TEXT.format(n=1))
    # Notanish mehmon shu namunaga nisbatan tekshirilgan - keyingi yig'ilishda qayta solishtirilmaydi.
    left = rt.store.row("SELECT l.speaker_key, l.voice_no FROM voice_links l JOIN voice_persons p ON p.id=l.person_id "
                        "WHERE p.kind='guest'")
    meeting(client, auth, rt, info({"status": "matched", "voice_id": left["voice_no"], "speaker_id": left["speaker_key"],
                                    "score": 0.9}))
    assert len(fake.ops("probe")) == 2


def test_namuna_hech_kimga_oxshamasa_otgan_yigilishlar_tekshirilmaydi(client, auth, fake, _isolated_meetings):
    rt = _isolated_meetings
    meeting(client, auth, rt, info({"status": "new", "voice_id": 105, "speaker_id": "sp-g", "score": 0.1}))
    body = enroll(client, auth, fake, score=0.22)
    assert body["message"] == voice.OK_TEXT and fake.ops("probe") == []


def test_qayta_namunada_ikkinchi_iz_baland_bolsa_ham_tekshirilmaydi(client, auth, fake, _isolated_meetings):
    """Ikki izli ovozda `runner_up` doim baland (o'z ikkinchi izi) - qayta namuna bekorga (pullik) tekshiruv boshlamaydi.
    Birinchi namunada esa baland ikkinchi iz - yana bir nusxa ovoz bor degani: mehmonlar tekshiriladi."""
    rt = _isolated_meetings
    meeting(client, auth, rt, info({"status": "new", "voice_id": 105, "speaker_id": "sp-g", "score": 0.1},
                                   {"status": "new", "voice_id": 106, "speaker_id": "sp-h", "score": 0.1}))
    payload = result("matched", 105, "sp-g")
    payload["speaker_info"][0]["identity"]["runner_up"] = 0.8
    fake.results[1].append(payload)
    assert post(client, auth).json()["status"] == "ok"
    assert len(fake.ops("probe")) == 1                        # birinchi namuna: qolgan mehmon (sp-h) tekshirildi
    again = result("matched", 105, "sp-g")
    again["speaker_info"][0]["identity"]["runner_up"] = 0.88
    fake.results[1].append(again)
    assert post(client, auth).json()["status"] == "ok"
    assert len(fake.ops("probe")) == 1                        # qayta namuna: tekshiruv yo'q


def test_namuna_mehmonga_ozi_mos_kelsa_otgan_yigilish_soni_aytiladi(client, auth, fake, _isolated_meetings):
    rt = _isolated_meetings
    mid = meeting(client, auth, rt, info({"status": "new", "voice_id": 105, "speaker_id": "sp-g", "score": 0.1}))
    fake.results[1].append(result("matched", 105, "sp-g"))
    body = post(client, auth).json()
    assert body["message"] == voice.OK_TEXT + voice.RETRO_TEXT.format(n=1)
    assert speakers(client, auth, mid)["S1"]["name"] == "Administrator" and fake.ops("probe") == []


def test_qayta_tekshirish_faqat_admin(client, auth, user_auth, fake, _isolated_meetings):
    rt = _isolated_meetings
    mid = meeting(client, auth, rt, info({"status": "new", "voice_id": 105, "speaker_id": "sp-g", "score": 0.1}))
    enroll(client, auth, fake)                                # o'xshashlik past - o'zi tekshirmadi
    pid = person_of(rt)["id"]
    assert client.post("/api/v1/voice-sample/recheck", headers=user_auth).status_code == 403
    fake.probes = [probe(pid, 0.8)]
    body = client.post("/api/v1/voice-sample/recheck", headers=auth).json()
    assert body == {"checked": 1, "adopted": 1, "busy": 0}
    assert speakers(client, auth, mid)["S1"]["name"] == "Administrator"


def test_tuzatish_ochiq_bolsa_hech_narsa_qilinmaydi(client, auth, fake, _isolated_meetings, monkeypatch):
    monkeypatch.setattr(settings, "voice_resolve_enabled", False, raising=False)
    rt = _isolated_meetings
    enroll(client, auth, fake, score=0.9)
    meeting(client, auth, rt, info({"status": "new", "voice_id": 109, "speaker_id": "sp-dup", "score": 0.74}))
    assert fake.ops("staff") == [] and fake.ops("probe") == [] and voice.sweep() == {"checked": 0, "adopted": 0}


# --- audio parchasi -------------------------------------------------------------------------


def test_adts_dan_vaqt_oraliqlari_kesiladi(tmp_path):
    path = tmp_path / "a.aac"
    path.write_bytes(adts_bytes(30.0))
    clip = audio.cut_adts(path, [(20.0, 25.0), (2.0, 4.0), (3.0, 5.0)])           # tartibsiz va ustma-ust
    out = tmp_path / "clip.aac"
    out.write_bytes(clip)
    got = audio.adts_info(out)
    assert got is not None and abs(got.durationSec - 8.0) < 0.2 and got.sampleRate == 16000
    assert audio.cut_adts(path, []) == b"" and audio.cut_adts(path, [(40.0, 50.0)]) == b""


def test_spiker_parchasi_eng_uzun_gaplardan(monkeypatch):
    monkeypatch.setattr(settings, "voice_clip_sec", 20.0, raising=False)
    monkeypatch.setattr(settings, "voice_clip_min_sec", 12.0, raising=False)
    segments = [{"speaker": "S1", "start": 0.0, "end": 9.0}, {"speaker": "S2", "start": 9.0, "end": 30.0},
                {"speaker": "S1", "start": 30.0, "end": 45.0}, {"speaker": "S1", "start": 45.0, "end": 45.5}]
    ranges = voice._ranges(segments, "S1")
    assert [round(x, 2) for x in ranges[0]] == [30.1, 44.9]                         # eng uzun gap - birinchi
    assert round(sum(b - a for a, b in ranges), 1) == 20.0
    assert voice._ranges(segments[:1], "S1") == []                                # 12 s dan kam - kesilmaydi
