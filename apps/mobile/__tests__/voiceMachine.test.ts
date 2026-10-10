/**
 * Holat mashinasi - spec 4.2 jadvalining har qatori (raqamlar izohda).
 */
import { initialState, joinText, reduce, type Effect, type MachineEvent, type MachineState } from '@/features/voice/machine';

function st(over: Partial<MachineState> = {}): MachineState {
  return { ...initialState({ canSpeak: true, ttsOff: false, earpiece: false }), ...over };
}

function step(s: MachineState, e: MachineEvent) {
  return reduce(s, e);
}

const types = (effects: Effect[]) => effects.map((e) => e.type);
const vad = (event: Extract<MachineEvent, { type: 'VAD' }>['event']): MachineEvent => ({ type: 'VAD', event });
const cue = { text: "Bir daqiqa, tekshiryapman", clip: 'kutish-ilk-1', at: 1, topic: 'hrm' };

describe('start and permissions (1-6, 40)', () => {
  it('1: a running meeting recording -> error mic_busy', () => {
    const t = step(st(), { type: 'START', meetingActive: true });
    expect(t.state.status).toBe('error');
    expect(t.state.error).toBe('mic_busy');
    expect(t.effects).toEqual([]);
  });

  it('2: START asks permission and stops read-aloud (keep-awake is derived by the session)', () => {
    const t = step(st(), { type: 'START', meetingActive: false });
    expect(t.state.status).toBe('idle');
    expect(t.effects).toEqual([{ type: 'perm.request' }, { type: 'readAloud.stop' }]);
  });

  it('3/4: denied -> error; granted -> audio mode then mic', () => {
    expect(step(st(), { type: 'PERMISSION', granted: false }).state.error).toBe('mic_denied');
    const t = step(st({ earpiece: true }), { type: 'PERMISSION', granted: true });
    expect(t.effects).toEqual([{ type: 'audio.enter', earpiece: true }, { type: 'mic.start' }]);
  });

  it('5: MIC_READY -> listening (no-op later)', () => {
    expect(step(st(), { type: 'MIC_READY' }).state.status).toBe('listening');
    expect(step(st({ status: 'thinking' }), { type: 'MIC_READY' }).state.status).toBe('thinking');
  });

  it('6: MIC_FAILED from any active state -> error mic_failed and the mic is released', () => {
    for (const status of ['listening', 'thinking', 'speaking', 'transcribing'] as const) {
      const t = step(st({ status }), { type: 'MIC_FAILED' });
      expect(t.state.error).toBe('mic_failed');
      expect(types(t.effects)).toContain('mic.release');
    }
  });

  it('40: RETRY from error restarts the START flow', () => {
    const t = step(st({ status: 'error', error: 'mic_failed', micMuted: true }), { type: 'RETRY', meetingActive: false });
    expect(t.state.status).toBe('idle');
    expect(t.state.error).toBeNull();
    expect(t.state.micMuted).toBe(false);
    expect(types(t.effects)).toEqual(['perm.request', 'readAloud.stop']);
    expect(step(st({ status: 'listening' }), { type: 'RETRY', meetingActive: false }).effects).toEqual([]);
  });
});

describe('listening and VAD (7-10)', () => {
  const L = st({ status: 'listening' });

  it('7: speech_start -> hearing, clears the notice', () => {
    const t = step({ ...L, notice: 'no_speech' }, vad({ type: 'speech_start', atMs: 100 }));
    expect(t.state.hearing).toBe(true);
    expect(t.state.notice).toBeNull();
  });

  it('8: speech_end / max_reached -> transcribing and the utterance is cut', () => {
    const t = step({ ...L, hearing: true }, vad({ type: 'speech_end', fromMs: 1000, toMs: 2400, voicedMs: 900, levelDb: -20 }));
    expect(t.state.status).toBe('transcribing');
    expect(t.state.hearing).toBe(false);
    expect(t.effects).toEqual([{ type: 'mic.cut', fromMs: 1000, toMs: 2400, preroll: true }]);
    expect(step(L, vad({ type: 'max_reached', fromMs: 0, toMs: 60_000, voicedMs: 59_000, levelDb: -20 })).state.status).toBe('transcribing');
    // Bo'lib gapirishda gapdan oldingi qism - faqat Barno aks-sadosi: pre-roll yo'q.
    const b = step({ ...L, hearing: true, bargeUtterance: true }, vad({ type: 'speech_end', fromMs: 1000, toMs: 2400, voicedMs: 900, levelDb: -20 }));
    expect(b.effects).toEqual([{ type: 'mic.cut', fromMs: 1000, toMs: 2400, preroll: false }]);
  });

  it('9: speech_discard -> keep listening; a pending prefix is sent alone', () => {
    expect(step({ ...L, hearing: true }, vad({ type: 'speech_discard' })).state).toMatchObject({ status: 'listening', hearing: false });
    const t = step({ ...L, hearing: true, prefix: 'Bugun kim' }, vad({ type: 'speech_discard' }));
    expect(t.state.status).toBe('thinking');
    expect(t.effects).toEqual([{ type: 'chat.send', text: 'Bugun kim' }]);
  });

  it('9: a discarded barge-in utterance is reported to the VAD (self-interrupt fallback)', () => {
    const t = step({ ...L, hearing: true, bargeUtterance: true }, vad({ type: 'speech_discard' }));
    expect(types(t.effects)).toEqual(['vad.bargeDiscard']);
  });

  it('10: 45 s without speech -> auto mute', () => {
    const t = step(L, { type: 'IDLE_TIMEOUT' });
    expect(t.state).toMatchObject({ status: 'muted', micMuted: true, notice: 'auto_muted' });
    expect(t.effects).toEqual([{ type: 'mic.release' }]);
    expect(step({ ...L, hearing: true }, { type: 'IDLE_TIMEOUT' }).state.status).toBe('listening');
  });

  it('barge_in is ignored while listening; VAD is ignored while muted or suspended', () => {
    expect(step(L, vad({ type: 'barge_in', atMs: 1 })).state).toBe(L);
    const m = st({ status: 'muted', micMuted: true });
    expect(step(m, vad({ type: 'speech_start', atMs: 1 })).state).toBe(m);
  });
});

describe('transcribing (11-19)', () => {
  const T = st({ status: 'transcribing' });

  it('11: speech during STT -> continuation', () => {
    expect(step(T, vad({ type: 'speech_start', atMs: 1 })).state).toMatchObject({ status: 'transcribing', continuation: true, hearing: true });
  });

  it('12: STT_OK -> thinking and the joined question is sent', () => {
    const t = step({ ...T, prefix: 'Bugun' }, { type: 'STT_OK', text: '  kim  kechikdi? ', lowConfidence: false });
    expect(t.state).toMatchObject({ status: 'thinking', prefix: null });
    expect(t.effects).toEqual([{ type: 'chat.send', text: 'Bugun kim kechikdi?' }]);
  });

  it('13: STT_OK while the user still speaks -> listening with the prefix kept', () => {
    const t = step({ ...T, continuation: true, hearing: true }, { type: 'STT_OK', text: 'Bugun', lowConfidence: false });
    expect(t.state).toMatchObject({ status: 'listening', prefix: 'Bugun', hearing: true, continuation: false });
    expect(t.effects).toEqual([]);
  });

  it('13b: a continuation that already ended is queued and transcribed next, then both are sent', () => {
    const a = step({ ...T, continuation: true, hearing: true }, vad({ type: 'speech_end', fromMs: 5000, toMs: 6000, voicedMs: 800, levelDb: -20 }));
    expect(a.state).toMatchObject({ status: 'transcribing', sttQueued: 1, continuation: false });
    expect(a.effects).toEqual([{ type: 'mic.cut', fromMs: 5000, toMs: 6000, preroll: true }]);
    const b = step(a.state, { type: 'STT_OK', text: 'Bugun', lowConfidence: false });
    expect(b.state).toMatchObject({ status: 'transcribing', sttQueued: 0, prefix: 'Bugun' });
    expect(b.effects).toEqual([{ type: 'stt.next' }]);
    const c = step(b.state, { type: 'STT_OK', text: 'kim kechikdi', lowConfidence: false });
    expect(c.effects).toEqual([{ type: 'chat.send', text: 'Bugun kim kechikdi' }]);
  });

  it('14: a low-confidence transcript is never sent automatically', () => {
    const t = step({ ...T, prefix: 'Bugun' }, { type: 'STT_OK', text: 'kim kechikdi', lowConfidence: true });
    expect(t.state).toMatchObject({ status: 'listening', pendingText: 'Bugun kim kechikdi', pendingAuto: false, notice: 'unsure', prefix: null });
    expect(t.effects).toEqual([]);
  });

  it('15/16: empty STT sends the prefix alone, or says it heard nothing', () => {
    expect(step({ ...T, prefix: 'Bugun kim' }, { type: 'STT_EMPTY' }).effects).toEqual([{ type: 'chat.send', text: 'Bugun kim' }]);
    const t = step(T, { type: 'STT_EMPTY' });
    expect(t.state).toMatchObject({ status: 'listening', notice: 'no_speech' });
    // Bo'lib gapirish bo'sh chiqdi: "qaytadan ayting" DEYILMAYDI (odam hech narsa demagan).
    const b = step({ ...T, bargeUtterance: true }, { type: 'STT_EMPTY' });
    expect(b.effects).toEqual([{ type: 'vad.bargeDiscard' }]);
    expect(b.state).toMatchObject({ status: 'listening', notice: null, bargeUtterance: false });
  });

  it('17: a network failure -> error offline and the mic is released', () => {
    const t = step(T, { type: 'STT_FAILED', network: true });
    expect(t.state).toMatchObject({ status: 'error', error: 'offline' });
    expect(types(t.effects)).toContain('mic.release');
  });

  it('18/19: other failures retry by listening; the third in a row is an error', () => {
    const a = step(T, { type: 'STT_FAILED', network: false });
    expect(a.state).toMatchObject({ status: 'listening', notice: 'stt_retry', sttFailures: 1 });
    const b = step({ ...a.state, status: 'transcribing' }, { type: 'STT_TIMEOUT' });
    expect(b.state.sttFailures).toBe(2);
    const c = step({ ...b.state, status: 'transcribing' }, { type: 'STT_FAILED', network: false });
    expect(c.state).toMatchObject({ status: 'error', error: 'stt_failed' });
  });

  it('a failed second part keeps the recognized first part as pending text', () => {
    const t = step({ ...T, prefix: 'Bugun kim' }, { type: 'STT_FAILED', network: false });
    expect(t.state).toMatchObject({ pendingText: 'Bugun kim', prefix: null, status: 'listening' });
  });

  it('STT results outside transcribing are ignored', () => {
    const L = st({ status: 'listening' });
    expect(step(L, { type: 'STT_OK', text: 'x y', lowConfidence: false }).state).toBe(L);
  });
});

describe('thinking (20-28)', () => {
  const Th = st({ status: 'thinking' });
  const Tc = st({ status: 'thinking', currentId: 'ex1', turnIds: ['ex1'] });

  it('20: SENT records the exchange of this session', () => {
    const t = step({ ...Th, sttFailures: 2 }, { type: 'SENT', id: 'ex1' });
    expect(t.state).toMatchObject({ currentId: 'ex1', turnIds: ['ex1'], sttFailures: 0 });
  });

  it('21: SEND_BUSY keeps the text and sends it when the chat is free', () => {
    const t = step(Th, { type: 'SEND_BUSY', text: 'Savol' });
    expect(t.state).toMatchObject({ status: 'listening', pendingText: 'Savol', pendingAuto: true, notice: 'chat_busy' });
  });

  it('22: HOLD plays a clip only for the current turn and only when speech is possible', () => {
    expect(step(Tc, { type: 'HOLD', id: 'ex1', cue }).effects).toEqual([{ type: 'speaker.hold', id: 'ex1', cue }]);
    expect(step(Tc, { type: 'HOLD', id: 'other', cue }).effects).toEqual([]);
    expect(step({ ...Tc, canSpeak: false }, { type: 'HOLD', id: 'ex1', cue }).effects).toEqual([]);
    expect(step(Tc, { type: 'HOLD', id: 'ex1', cue: { ...cue, clip: null } }).effects).toEqual([]);
    expect(step({ ...Tc, suspended: true }, { type: 'HOLD', id: 'ex1', cue }).effects).toEqual([]);
  });

  it('23: the first speakable text opens the speech queue; later text is pushed', () => {
    const a = step(Tc, { type: 'ANSWER', id: 'ex1', text: 'Bugun uch kishi', done: false, proposal: false });
    expect(a.effects).toEqual([
      { type: 'speaker.speak', id: 'ex1' },
      { type: 'speaker.push', id: 'ex1', text: 'Bugun uch kishi', done: false },
    ]);
    expect(a.state.answerStarted).toBe(true);
    const b = step(a.state, { type: 'ANSWER', id: 'ex1', text: 'Bugun uch kishi kechikdi.', done: true, proposal: false });
    expect(b.effects).toEqual([{ type: 'speaker.push', id: 'ex1', text: 'Bugun uch kishi kechikdi.', done: true }]);
  });

  it('24: the first audio -> speaking; the hold caption is cleared', () => {
    const t = step({ ...Tc, answerStarted: true, holdText: 'Bir daqiqa' }, { type: 'SPEAKER', event: { type: 'speech_start', key: 'ex1' } });
    expect(t.state).toMatchObject({ status: 'speaking', speakingId: 'ex1', holdText: null });
  });

  it('25: ru/en - no speech, the uz_only note once per session', () => {
    const ru = st({ status: 'thinking', currentId: 'ex1', canSpeak: false });
    const partial = step(ru, { type: 'ANSWER', id: 'ex1', text: 'Ответ', done: false, proposal: false });
    expect(partial.state).toMatchObject({ status: 'thinking', answerSeen: true });
    expect(partial.effects).toEqual([]);
    const a = step(ru, { type: 'ANSWER', id: 'ex1', text: 'Ответ.', done: true, proposal: false });
    expect(a.state).toMatchObject({ status: 'listening', notice: 'uz_only', uzOnlyShown: true, currentId: null });
    expect(a.effects).toEqual([]);
    const b = step({ ...a.state, status: 'thinking', currentId: 'ex2', notice: null }, { type: 'ANSWER', id: 'ex2', text: 'Ещё.', done: true, proposal: false });
    expect(b.state.notice).toBeNull();
  });

  it('25: a Cyrillic answer in the uz UI is not read; a proposal-only answer points to the screen', () => {
    const a = step(Tc, { type: 'ANSWER', id: 'ex1', text: 'Сегодня опоздали трое.', done: true, proposal: false });
    expect(a.state).toMatchObject({ status: 'listening', notice: 'not_uzbek' });
    const b = step(Tc, { type: 'ANSWER', id: 'ex1', text: '', done: true, proposal: true });
    expect(b.state.notice).toBe('see_screen');
    // muted bo'lsa - muted ga qaytadi
    expect(step({ ...Tc, micMuted: true }, { type: 'ANSWER', id: 'ex1', text: '', done: true, proposal: true }).state.status).toBe('muted');
  });

  it('26: a failed or cancelled answer returns to listening and stops speech', () => {
    const t = step({ ...Tc, answerStarted: true }, { type: 'ANSWER_FAILED', id: 'ex1' });
    expect(t.state).toMatchObject({ status: 'listening', currentId: null, answerStarted: false });
    expect(t.effects).toEqual([{ type: 'speaker.stop' }]);
  });

  it('27: barge-in while thinking stops the hold clip and listens, but does NOT cancel the request yet', () => {
    const t = step({ ...Tc, holdText: 'Bir daqiqa', answerStarted: true }, vad({ type: 'barge_in', atMs: 500 }));
    expect(t.state).toMatchObject({ status: 'listening', hearing: true, currentId: 'ex1', parked: 'thinking', bargeUtterance: true, holdText: null, answerStarted: false });
    expect(t.effects).toEqual([{ type: 'speaker.stop' }]);
    expect(types(t.effects)).not.toContain('chat.stop');
  });

  it('28: a tap during a hold clip stops only the clip', () => {
    expect(step({ ...Tc, holdText: 'Bir daqiqa' }, { type: 'TAP_INTERRUPT' }).effects).toEqual([{ type: 'speaker.stopHold' }]);
    expect(step(Tc, { type: 'TAP_INTERRUPT' }).effects).toEqual([]);
  });

  it('hold captions follow the speaker', () => {
    const a = step(Tc, { type: 'SPEAKER', event: { type: 'hold_start', text: 'Bir daqiqa' } });
    expect(a.state.holdText).toBe('Bir daqiqa');
    expect(step(a.state, { type: 'SPEAKER', event: { type: 'hold_end' } }).state.holdText).toBeNull();
  });
});

describe('speaking (29-33)', () => {
  const S = st({ status: 'speaking', currentId: 'ex1', speakingId: 'ex1', answerStarted: true, turnIds: ['ex1'] });

  it('29: speech_end -> listening (or muted), echo guard, shortened note', () => {
    const a = step(S, { type: 'SPEAKER', event: { type: 'speech_end', key: 'ex1', shortened: false, played: 3 } });
    expect(a.state).toMatchObject({ status: 'listening', speakingId: null, currentId: null, notice: null });
    expect(a.effects).toEqual([{ type: 'vad.guard' }]);
    expect(step({ ...S, micMuted: true }, { type: 'SPEAKER', event: { type: 'speech_end', key: 'ex1', shortened: true, played: 9 } }).state).toMatchObject({
      status: 'muted',
      notice: 'shortened',
    });
  });

  it('30: barge-in PAUSES the audio (the answer can resume if it was only noise)', () => {
    const t = step(S, vad({ type: 'barge_in', atMs: 100 }));
    expect(t.state).toMatchObject({ status: 'listening', hearing: true, speakingId: 'ex1', currentId: 'ex1', parked: 'speaking', bargeUtterance: true });
    expect(t.effects).toEqual([{ type: 'speaker.pause' }]);
  });

  it('31: a tap interrupts', () => {
    const t = step(S, { type: 'TAP_INTERRUPT' });
    expect(t.state.status).toBe('listening');
    expect(t.effects).toEqual([{ type: 'speaker.stop' }, { type: 'vad.guard' }]);
  });

  it('32: TTS busy/failed -> note; nothing played -> listening when the speaker drains', () => {
    const Tq = st({ status: 'thinking', currentId: 'ex1', answerStarted: true });
    const a = step(Tq, { type: 'SPEAKER', event: { type: 'error', key: 'ex1', code: 'busy' } });
    expect(a.state.notice).toBe('tts_failed');
    const b = step(a.state, { type: 'SPEAKER', event: { type: 'speech_end', key: 'ex1', shortened: false, played: 0 } });
    expect(b.state).toMatchObject({ status: 'listening', notice: 'tts_failed' });
  });

  it('32b: an answer with nothing speakable points to the screen', () => {
    const Tq = st({ status: 'thinking', currentId: 'ex1', answerStarted: true });
    expect(step(Tq, { type: 'SPEAKER', event: { type: 'speech_end', key: 'ex1', shortened: false, played: 0 } }).state.notice).toBe('see_screen');
  });

  it('33: 501 turns speech off for the session', () => {
    const t = step(S, { type: 'SPEAKER', event: { type: 'error', key: 'ex1', code: 'off' } });
    expect(t.state).toMatchObject({ ttsOff: true, canSpeak: false, notice: 'tts_off' });
  });

  it('speech_end of another key is ignored', () => {
    expect(step(S, { type: 'SPEAKER', event: { type: 'speech_end', key: 'zzz', shortened: false, played: 1 } }).state).toBe(S);
  });
});

describe('mute (34-37)', () => {
  it('34: listening -> muted releases the mic; a waiting prefix becomes pending text', () => {
    const t = step(st({ status: 'listening', prefix: 'Bugun' }), { type: 'MUTE' });
    expect(t.state).toMatchObject({ status: 'muted', micMuted: true, pendingText: 'Bugun', prefix: null });
    expect(t.effects).toEqual([{ type: 'mic.release' }]);
  });

  it('35: muting while thinking/speaking/transcribing keeps the pipeline', () => {
    for (const status of ['thinking', 'speaking', 'transcribing'] as const) {
      const t = step(st({ status }), { type: 'MUTE' });
      expect(t.state).toMatchObject({ status, micMuted: true });
      expect(t.effects).toEqual([{ type: 'mic.release' }]);
    }
  });

  it('36/37: unmute restarts the mic', () => {
    expect(step(st({ status: 'muted', micMuted: true }), { type: 'UNMUTE' })).toEqual({
      state: expect.objectContaining({ status: 'listening', micMuted: false }),
      effects: [{ type: 'mic.start' }],
    });
    const t = step(st({ status: 'speaking', micMuted: true }), { type: 'UNMUTE' });
    expect(t.state).toMatchObject({ status: 'speaking', micMuted: false });
    expect(t.effects).toEqual([{ type: 'mic.start' }]);
  });

  it('mute/unmute are ignored in idle and error', () => {
    expect(step(st(), { type: 'MUTE' }).effects).toEqual([]);
    expect(step(st({ status: 'error', error: 'offline' }), { type: 'UNMUTE' }).effects).toEqual([]);
  });
});

describe('suspend / resume (38-39)', () => {
  it('38: suspend releases the mic, stops speech and aborts STT', () => {
    const t = step(st({ status: 'transcribing', prefix: 'x', sttQueued: 1 }), { type: 'SUSPEND' });
    expect(t.state).toMatchObject({ suspended: true, prefix: null, sttQueued: 0 });
    expect(t.effects).toEqual([{ type: 'mic.release' }, { type: 'speaker.stop', keep: true }, { type: 'stt.abort' }]);
    expect(step(st(), { type: 'SUSPEND' }).effects).toEqual([]);
  });

  it('39: resume listens again; a still-pending answer keeps thinking; muted stays muted', () => {
    const tr = step(st({ status: 'transcribing', suspended: true }), { type: 'RESUME', pending: false });
    expect(tr.state).toMatchObject({ status: 'listening', suspended: false });
    // Audio rejim qayta qo'yiladi (qo'ng'iroq yoki boshqa ilova uni o'zgartirgan bo'lishi mumkin).
    expect(tr.effects).toEqual([{ type: 'audio.enter', earpiece: false }, { type: 'mic.start' }]);
    const th = step(st({ status: 'speaking', suspended: true, currentId: 'ex1', speakingId: 'ex1', answerStarted: true }), { type: 'RESUME', pending: true });
    expect(th.state).toMatchObject({ status: 'thinking', speakingId: null, answerStarted: false, currentId: 'ex1' });
    const done = step(st({ status: 'thinking', suspended: true, currentId: 'ex1' }), { type: 'RESUME', pending: false });
    expect(done.state).toMatchObject({ status: 'listening', currentId: null });
    const muted = step(st({ status: 'listening', suspended: true, micMuted: true }), { type: 'RESUME', pending: false });
    expect(muted.state.status).toBe('muted');
    expect(muted.effects).toEqual([{ type: 'audio.enter', earpiece: false }]);
  });

  it('answers that arrive while suspended are not spoken', () => {
    const s = st({ status: 'thinking', currentId: 'ex1', suspended: true });
    expect(step(s, { type: 'ANSWER', id: 'ex1', text: 'Javob.', done: true, proposal: false }).effects).toEqual([]);
  });
});

describe('pending text, end, notices (41-42)', () => {
  it('42: SEND_PENDING sends; busy -> note and auto-send later; auto only when armed', () => {
    const L = st({ status: 'listening', pendingText: 'Savol' });
    expect(step(L, { type: 'SEND_PENDING', busy: false }).effects).toEqual([{ type: 'chat.send', text: 'Savol' }]);
    const busy = step(L, { type: 'SEND_PENDING', busy: true });
    expect(busy.state).toMatchObject({ notice: 'chat_busy', pendingAuto: true });
    expect(step(L, { type: 'SEND_PENDING', busy: false, auto: true }).effects).toEqual([]);
    expect(step(busy.state, { type: 'SEND_PENDING', busy: false, auto: true }).effects).toEqual([{ type: 'chat.send', text: 'Savol' }]);
  });

  it('41: END stops everything except the chat request; later events are ignored', () => {
    const t = step(st({ status: 'thinking', currentId: 'ex1' }), { type: 'END' });
    expect(t.state.ended).toBe(true);
    expect(types(t.effects)).toEqual(['mic.release', 'speaker.stop', 'stt.abort', 'audio.restore', 'files.clear']);
    expect(types(t.effects)).not.toContain('chat.stop');
    expect(step(t.state, { type: 'START', meetingActive: false })).toEqual({ state: t.state, effects: [] });
  });

  it('notices expire by sequence; dismiss clears; earpiece switches the audio route', () => {
    const a = step(st({ status: 'transcribing' }), { type: 'STT_EMPTY' });
    expect(step(a.state, { type: 'NOTICE_EXPIRED', seq: a.state.noticeSeq - 1 }).state.notice).toBe('no_speech');
    expect(step(a.state, { type: 'NOTICE_EXPIRED', seq: a.state.noticeSeq }).state.notice).toBeNull();
    expect(step(a.state, { type: 'DISMISS_NOTICE' }).state.notice).toBeNull();
    expect(step(st({ status: 'listening' }), { type: 'SET_EARPIECE', on: true })).toEqual({
      state: expect.objectContaining({ earpiece: true }),
      effects: [{ type: 'audio.earpiece', on: true }],
    });
  });

  it('joinText normalizes whitespace and skips empty parts', () => {
    expect(joinText(' Bugun ', '  kim\n kechikdi ')).toBe('Bugun kim kechikdi');
    expect(joinText(null, 'ha')).toBe('ha');
  });
});

describe('barge-in check (parked): nothing is lost until the interruption is a real question', () => {
  const Tc = st({ status: 'thinking', currentId: 'ex1', turnIds: ['ex1'], sentText: 'Bugun kim' });
  const parkedThinking = () => step(Tc, vad({ type: 'barge_in', atMs: 500 })).state;
  const S = st({ status: 'speaking', currentId: 'ex1', speakingId: 'ex1', answerStarted: true, turnIds: ['ex1'], answerSeen: true });
  const parkedSpeaking = () => step(S, vad({ type: 'barge_in', atMs: 500 })).state;
  const cut = (s: MachineState) => step(s, vad({ type: 'speech_end', fromMs: 500, toMs: 1500, voicedMs: 900, levelDb: -20 })).state;

  it('thinking: a discarded utterance (noise) goes back to waiting for the SAME request', () => {
    const t = step(parkedThinking(), vad({ type: 'speech_discard' }));
    expect(t.state).toMatchObject({ status: 'thinking', currentId: 'ex1', parked: null, bargeUtterance: false, notice: null });
    expect(t.effects).toEqual([{ type: 'vad.bargeDiscard' }]);
  });

  it('thinking: empty, low-confidence or echo transcripts also go back to waiting (no "repeat" notice)', () => {
    for (const ev of [{ type: 'STT_EMPTY' }, { type: 'STT_OK', text: 'gap-gap', lowConfidence: true }, { type: 'STT_ECHO' }] as MachineEvent[]) {
      const t = step(cut(parkedThinking()), ev);
      expect(t.state).toMatchObject({ status: 'thinking', currentId: 'ex1', parked: null, notice: null, pendingText: null });
      expect(types(t.effects)).toEqual(['vad.bargeDiscard']);
    }
  });

  it('thinking: a real question cancels the request; before the first token both halves are sent as ONE question', () => {
    const t = step(cut(parkedThinking()), { type: 'STT_OK', text: 'kechikdi?', lowConfidence: false });
    expect(t.effects).toEqual([{ type: 'chat.stop' }, { type: 'chat.send', text: 'Bugun kim kechikdi?' }]);
    expect(t.state).toMatchObject({ status: 'thinking', currentId: null, parked: null, sentText: 'Bugun kim kechikdi?' });
    // Javob allaqachon kela boshlagan bo'lsa - yangi savol alohida.
    const seen = step({ ...cut(parkedThinking()), answerSeen: true }, { type: 'STT_OK', text: 'Ertaga-chi?', lowConfidence: false });
    expect(seen.effects).toEqual([{ type: 'chat.stop' }, { type: 'chat.send', text: 'Ertaga-chi?' }]);
  });

  it('thinking: answer frames that arrive during the check are remembered, not spoken', () => {
    const p = parkedThinking();
    const t = step(p, { type: 'ANSWER', id: 'ex1', text: 'Javob.', done: true, proposal: false });
    expect(t.effects).toEqual([]);
    expect(t.state.answerSeen).toBe(true);
  });

  it('thinking: "to\'xta" cancels the request without sending it as a question', () => {
    const t = step(cut(parkedThinking()), { type: 'STT_STOP' });
    expect(types(t.effects)).toEqual(['chat.stop', 'vad.guard']);
    expect(t.state).toMatchObject({ status: 'listening', currentId: null, parked: null });
  });

  it('speaking: noise or echo resumes Barno from where she paused; nothing is said to the user', () => {
    const a = step(parkedSpeaking(), vad({ type: 'speech_discard' }));
    expect(a.state).toMatchObject({ status: 'speaking', speakingId: 'ex1', parked: null, notice: null });
    expect(a.effects).toEqual([{ type: 'vad.bargeDiscard' }, { type: 'speaker.resume' }]);
    const b = step(cut(parkedSpeaking()), { type: 'STT_ECHO' });
    expect(b.state.status).toBe('speaking');
    expect(b.effects).toEqual([{ type: 'vad.bargeDiscard' }, { type: 'speaker.resume' }]);
  });

  it('speaking: a real question stops the paused audio and is sent; "to\'xta" only stops', () => {
    const a = step(cut(parkedSpeaking()), { type: 'STT_OK', text: 'Ertaga-chi?', lowConfidence: false });
    expect(a.effects).toEqual([{ type: 'speaker.stop' }, { type: 'chat.send', text: 'Ertaga-chi?' }]);
    const b = step(cut(parkedSpeaking()), { type: 'STT_STOP' });
    expect(types(b.effects)).toEqual(['speaker.stop', 'vad.guard']);
    expect(b.state).toMatchObject({ status: 'listening', speakingId: null, currentId: null });
  });

  it('speaking: later answer text still reaches the paused queue', () => {
    const t = step(parkedSpeaking(), { type: 'ANSWER', id: 'ex1', text: 'A. B.', done: true, proposal: false });
    expect(t.effects).toEqual([{ type: 'speaker.push', id: 'ex1', text: 'A. B.', done: true }]);
  });

  it('a paused answer that ends anyway leaves a plain utterance (no stuck "speaking")', () => {
    const t = step(parkedSpeaking(), { type: 'SPEAKER', event: { type: 'speech_end', key: 'ex1', shortened: false, played: 2 } });
    expect(t.state).toMatchObject({ status: 'listening', parked: null, currentId: null, bargeUtterance: true });
    const d = step(t.state, vad({ type: 'speech_discard' }));
    expect(d.state.status).toBe('listening');
  });

  it('mute, suspend and a failed request end the check cleanly', () => {
    const m = step(parkedSpeaking(), { type: 'MUTE' });
    expect(m.state).toMatchObject({ status: 'speaking', micMuted: true, parked: null });
    expect(types(m.effects)).toEqual(['mic.release', 'speaker.resume']);
    const s = step(parkedThinking(), { type: 'SUSPEND' });
    expect(s.state).toMatchObject({ status: 'thinking', suspended: true, parked: null });
    const f = step(parkedThinking(), { type: 'ANSWER_FAILED', id: 'ex1' });
    expect(f.state).toMatchObject({ status: 'listening', parked: null, currentId: null, bargeUtterance: true });
    // Tekshiruv paytida eslatma vaqti o'tsa ham mikrofon o'zi o'chmaydi, kutilgan matn yuborilmaydi.
    expect(step({ ...parkedThinking(), hearing: false }, { type: 'IDLE_TIMEOUT' }).effects).toEqual([]);
    expect(step({ ...parkedThinking(), pendingText: 'x' }, { type: 'SEND_PENDING', busy: false }).effects).toEqual([]);
  });

  it('a failed STT during the check goes back to the answer with a short note', () => {
    const t = step(cut(parkedSpeaking()), { type: 'STT_FAILED', network: false });
    expect(t.state).toMatchObject({ status: 'speaking', notice: 'stt_retry', parked: null });
    expect(types(t.effects)).toEqual(['speaker.resume']);
  });
});

describe('resume, meeting guard and text-only answers', () => {
  it('RESUME with a ready, partly spoken answer continues it; a meeting recording blocks the mic', () => {
    const s = st({ status: 'speaking', suspended: true, currentId: 'ex1', speakingId: 'ex1', answerStarted: true });
    const t = step(s, { type: 'RESUME', pending: false, resumable: true });
    expect(t.state).toMatchObject({ status: 'thinking', currentId: 'ex1', answerStarted: false });
    const m = step(s, { type: 'RESUME', pending: false, meetingActive: true });
    expect(m.state).toMatchObject({ status: 'error', error: 'mic_busy' });
    expect(types(m.effects)).not.toContain('mic.start');
    expect(types(m.effects)).not.toContain('audio.enter');
  });

  it('UNMUTE during a meeting recording is refused (no second recorder)', () => {
    const t = step(st({ status: 'muted', micMuted: true }), { type: 'UNMUTE', meetingActive: true });
    expect(t.state).toMatchObject({ status: 'error', error: 'mic_busy' });
    expect(types(t.effects)).not.toContain('mic.start');
  });

  it('answers that are not (fully) spoken are flagged text-only; a new question clears it', () => {
    const ru = st({ status: 'thinking', currentId: 'ex1', canSpeak: false });
    expect(step(ru, { type: 'ANSWER', id: 'ex1', text: 'Ответ.', done: true, proposal: false }).state.textOnly).toBe(true);
    const tc = st({ status: 'thinking', currentId: 'ex1' });
    expect(step(tc, { type: 'ANSWER', id: 'ex1', text: 'Сегодня трое.', done: true, proposal: false }).state.textOnly).toBe(true);
    expect(step(tc, { type: 'SPEAKER', event: { type: 'error', key: 'ex1', code: 'failed' } }).state.textOnly).toBe(true);
    const sp = st({ status: 'speaking', currentId: 'ex1', speakingId: 'ex1', answerStarted: true });
    expect(step(sp, { type: 'SPEAKER', event: { type: 'speech_end', key: 'ex1', shortened: true, played: 9 } }).state.textOnly).toBe(true);
    expect(step(sp, { type: 'SPEAKER', event: { type: 'speech_end', key: 'ex1', shortened: false, played: 3 } }).state.textOnly).toBe(false);
    const again = step({ ...st({ status: 'transcribing' }), textOnly: true }, { type: 'STT_OK', text: 'Yana savol', lowConfidence: false });
    expect(again.state.textOnly).toBe(false);
  });

  it('counts spoken answers (the interrupt hint is only shown for the first ones)', () => {
    const t = step(st({ status: 'thinking', currentId: 'ex1', answerStarted: true }), { type: 'SPEAKER', event: { type: 'speech_start', key: 'ex1' } });
    expect(t.state.answersSpoken).toBe(1);
  });
});
