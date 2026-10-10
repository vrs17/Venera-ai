/**
 * Jonli suhbat ekrani (`/voice`): dvigatel (`useVoiceSession`) soxta - faqat UI tekshiriladi.
 * Salomlashuv, holat yozuvi, mikrofon/karnay/✕, xato tugmalari, suhbat matni (javob katta
 * matnda, kutish klipi matni), matnga tegib to'xtatish, "baribir yuborish", matnsiz rejim,
 * Pro kaliti, Android "orqaga", tuman obunasi.
 */
import { act, fireEvent, render, screen, within } from '@testing-library/react-native';
import { router } from 'expo-router';
import { BackHandler, Linking } from 'react-native';

import VoiceScreen from '@/app/voice';
import { useAuth } from '@/features/auth/authStore';
import { useChat, type Exchange } from '@/features/chat/chatStore';
import { usePro } from '@/features/chat/proStore';
import { useSettings } from '@/features/settings/settingsStore';
import type { LevelListener, VoiceSnapshot } from '@/features/voice';
import { fogDim } from '@/features/voice/ui/VoiceFog';
import { statusLine } from '@/features/voice/ui/voiceText';
import { useVoiceSettings } from '@/features/voice/voiceSettings';
import { makeT } from '@/i18n';

import { fakeServices, Providers } from './fixtures/fakeServices';

jest.mock('expo-router', () => {
  const React = jest.requireActual<typeof import('react')>('react');
  return {
    router: { push: jest.fn(), replace: jest.fn(), navigate: jest.fn(), back: jest.fn(), canGoBack: jest.fn(() => true) },
    useFocusEffect: (cb: () => void) => React.useEffect(cb, [cb]),
  };
});

const IDLE: VoiceSnapshot = {
  status: 'idle',
  micMuted: false,
  hearing: false,
  suspended: false,
  error: null,
  notice: null,
  turnIds: [],
  pendingText: null,
  holdText: null,
  speakingId: null,
  canSpeak: true,
  earpiece: false,
  textOnly: false,
  preparing: false,
  answersSpoken: 0,
};

/** Soxta sessiya: holat testdan o'zgartiriladi, ekran useSyncExternalStore bilan kuzatadi. */
const mockSession = {
  snap: IDLE,
  listeners: new Set<() => void>(),
  levels: new Set<LevelListener>(),
  actions: {
    toggleMute: jest.fn(),
    setEarpiece: jest.fn(),
    interrupt: jest.fn(),
    retry: jest.fn(),
    sendPending: jest.fn(),
    dismissNotice: jest.fn(),
    end: jest.fn(async () => {}),
  },
  subscribeLevel: (l: LevelListener) => {
    mockSession.levels.add(l);
    return () => {
      mockSession.levels.delete(l);
    };
  },
};

jest.mock('@/features/voice/useVoiceSession', () => {
  const React = jest.requireActual<typeof import('react')>('react');
  return {
    useVoiceSession: () => {
      const snap = React.useSyncExternalStore(
        (l: () => void) => {
          mockSession.listeners.add(l);
          return () => mockSession.listeners.delete(l);
        },
        () => mockSession.snap,
      );
      return { snap, actions: mockSession.actions, subscribeLevel: mockSession.subscribeLevel };
    },
  };
});

async function setSnap(patch: Partial<VoiceSnapshot>) {
  await act(async () => {
    mockSession.snap = { ...mockSession.snap, ...patch };
    mockSession.listeners.forEach((l) => l());
  });
}

function exchange(over: Partial<Exchange> & { id: string }): Exchange {
  return {
    question: 'Bugun kim kechikdi?',
    answer: '',
    status: 'pending',
    stage: null,
    sources: [],
    artifact: null,
    proposal: null,
    error: null,
    errorCode: null,
    warning: null,
    proRequested: false,
    pro: null,
    engine: null,
    askedAt: null,
    answeredAt: null,
    turnId: null,
    input: 'voice',
    holds: [],
    ...over,
  };
}

async function renderVoice() {
  await render(
    <Providers services={fakeServices()}>
      <VoiceScreen />
    </Providers>,
  );
}

const push = router.push as jest.Mock;
const back = router.back as jest.Mock;

beforeEach(() => {
  mockSession.snap = IDLE;
  mockSession.listeners.clear();
  mockSession.levels.clear();
  useChat.getState().newChat();
  usePro.getState().reset();
  useSettings.getState().set({ uiLang: 'uz', proOn: false });
  useVoiceSettings.setState({ showText: true });
  useAuth.getState().setSignedIn({ actorId: 7, actorType: 'EMPLOYEE', email: 'y@x.uz', fullName: 'Yusuf Mamajonov', position: null, department: null, roles: [], passwordChangeRequired: false });
});

describe('VoiceScreen', () => {
  it('empty state: ✦ + "Gaplashamiz, Yusuf"; connecting; mic disabled until the session is ready', async () => {
    await renderVoice();
    expect(screen.getByTestId('voice-screen')).toBeTruthy();
    expect(screen.getByText('Gaplashamiz, Yusuf')).toBeTruthy();
    expect(screen.getByText('✦', { includeHiddenElements: true })).toBeTruthy();
    expect(screen.getByTestId('voice-status').props.children).toBe('Ulanmoqda…');
    expect(screen.getByTestId('voice-mic').props.accessibilityState).toMatchObject({ disabled: true, checked: true });
    expect(screen.queryByTestId('voice-transcript')).toBeNull();
    expect(screen.getByTestId('voice-fog')).toBeTruthy();
  });

  it('greeting without a name', async () => {
    useAuth.getState().setSignedIn({ actorId: 7, actorType: 'EMPLOYEE', email: 'y@x.uz', fullName: '', position: null, department: null, roles: [], passwordChangeRequired: false });
    await renderVoice();
    expect(screen.getByText('Gaplashamiz')).toBeTruthy();
  });

  it('listening -> hearing -> muted: caption follows; mic toggles mute', async () => {
    await renderVoice();
    await setSnap({ status: 'listening' });
    expect(screen.getByTestId('voice-status').props.children).toBe('Tinglayapman');
    await setSnap({ hearing: true });
    expect(screen.getByTestId('voice-status').props.children).toBe('Eshityapman…');
    await act(async () => {
      await fireEvent.press(screen.getByTestId('voice-mic'));
    });
    expect(mockSession.actions.toggleMute).toHaveBeenCalledTimes(1);
    await setSnap({ status: 'muted', micMuted: true, hearing: false });
    expect(screen.getByTestId('voice-status').props.children).toBe("Mikrofon o'chiq");
    expect(screen.getByTestId('voice-mic').props.accessibilityState).toMatchObject({ checked: false, disabled: false });
    expect(screen.getByTestId('icon-MicOff')).toBeTruthy();
  });

  it('a notice wins over the state text; thinking shows the hold clip text', async () => {
    await renderVoice();
    await setSnap({ status: 'listening', notice: 'no_speech' });
    expect(screen.getByTestId('voice-status').props.children).toBe('Eshitilmadi - qaytadan ayting');
    await setSnap({ status: 'thinking', notice: null, holdText: 'Hozir tekshiraman' });
    expect(screen.getByTestId('voice-status').props.children).toBe('Hozir tekshiraman');
    await setSnap({ status: 'speaking', holdText: null });
    expect(screen.getByTestId('voice-status').props.children).toBe("To'xtatish uchun gapiring yoki bosing");
  });

  it('transcript: question bubble, hold text while waiting, then the answer as large clean text', async () => {
    useChat.setState({ exchanges: [exchange({ id: 'e1', status: 'pending', stage: 'HRM tekshirilmoqda' })] });
    await renderVoice();
    await setSnap({ status: 'thinking', turnIds: ['e1'], holdText: 'Bir soniya, qarayapman' });
    expect(screen.getByTestId('voice-transcript')).toBeTruthy();
    expect(screen.getByText('Bugun kim kechikdi?')).toBeTruthy();
    // Kutish matni BITTA joyda (pastdagi yozuvda); javob o'rnida nuqtalar va agent bosqichi.
    expect(screen.getByTestId('voice-status').props.children).toBe('Bir soniya, qarayapman');
    expect(within(screen.getByTestId('voice-turn-e1')).queryByText('Bir soniya, qarayapman')).toBeNull();
    expect(within(screen.getByTestId('voice-turn-e1')).getByText('HRM tekshirilmoqda')).toBeTruthy();
    expect(screen.queryByTestId('voice-greeting')).toBeNull();

    await act(async () => {
      useChat.setState({ exchanges: [exchange({ id: 'e1', status: 'done', answer: '**Uch kishi** kechikdi: Ali, Vali [T1].\n\n[T1] hrm_today_late' })] });
    });
    await setSnap({ status: 'speaking', holdText: null, speakingId: 'e1' });
    const answer = screen.getByTestId('voice-answer-e1');
    expect(answer.props.children).toBe('Uch kishi kechikdi: Ali, Vali.');
  });

  it('tapping the transcript while Barno speaks interrupts; a drag does not', async () => {
    useChat.setState({ exchanges: [exchange({ id: 'e1', status: 'done', answer: 'Javob.' })] });
    await renderVoice();
    await setSnap({ status: 'speaking', turnIds: ['e1'] });
    const tr = screen.getByTestId('voice-transcript');
    await act(async () => {
      await fireEvent(tr, 'touchStart', { nativeEvent: { pageX: 100, pageY: 300 } });
      await fireEvent(tr, 'touchMove', { nativeEvent: { pageX: 100, pageY: 360 } });
      await fireEvent(tr, 'touchEnd', { nativeEvent: { pageX: 100, pageY: 360 } });
    });
    expect(mockSession.actions.interrupt).not.toHaveBeenCalled();
    await act(async () => {
      await fireEvent(tr, 'touchStart', { nativeEvent: { pageX: 100, pageY: 300 } });
      await fireEvent(tr, 'touchEnd', { nativeEvent: { pageX: 102, pageY: 301 } });
    });
    expect(mockSession.actions.interrupt).toHaveBeenCalledTimes(1);
    // Tinglash paytida tegish hech narsani to'xtatmaydi.
    await setSnap({ status: 'listening' });
    await act(async () => {
      await fireEvent(tr, 'touchStart', { nativeEvent: { pageX: 100, pageY: 300 } });
      await fireEvent(tr, 'touchEnd', { nativeEvent: { pageX: 100, pageY: 300 } });
    });
    expect(mockSession.actions.interrupt).toHaveBeenCalledTimes(1);
  });

  it('unsure transcript: faded bubble + "Yuborish" sends it', async () => {
    await renderVoice();
    await setSnap({ status: 'listening', pendingText: "Ta'tilim qancha", notice: 'unsure' });
    expect(screen.getByText("Ta'tilim qancha")).toBeTruthy();
    expect(screen.getByTestId('voice-status').props.children).toBe('Aniq eshitilmadi - yuborishdan oldin tekshiring');
    await act(async () => {
      await fireEvent.press(screen.getByTestId('voice-send-pending'));
    });
    expect(mockSession.actions.sendPending).toHaveBeenCalledTimes(1);
  });

  it('transcribing shows a placeholder user bubble', async () => {
    await renderVoice();
    await setSnap({ status: 'transcribing' });
    expect(screen.getByTestId('voice-transcribing')).toBeTruthy();
    expect(screen.getByTestId('voice-status').props.children).toBe('Tushunyapman…');
  });

  it('error mic_denied: red text, retry and open settings', async () => {
    const open = jest.spyOn(Linking, 'openSettings').mockResolvedValue(undefined);
    await renderVoice();
    await setSnap({ status: 'error', error: 'mic_denied' });
    const status = screen.getByTestId('voice-status');
    expect(status.props.children).toMatch(/Mikrofon/);
    await act(async () => {
      await fireEvent.press(screen.getByTestId('voice-retry'));
    });
    expect(mockSession.actions.retry).toHaveBeenCalledTimes(1);
    await act(async () => {
      await fireEvent.press(screen.getByTestId('voice-open-settings'));
    });
    expect(open).toHaveBeenCalled();
    await setSnap({ error: 'offline' });
    expect(screen.queryByTestId('voice-open-settings')).toBeNull();
    expect(screen.getByTestId('voice-status').props.children).toBe("Internet yo'q - ulanishni tekshiring");
    open.mockRestore();
  });

  it('earpiece switch: one fixed name + on/off state (TalkBack never says the active speaker is "off")', async () => {
    await renderVoice();
    await setSnap({ status: 'listening' });
    const sp = screen.getByTestId('voice-speaker');
    expect(sp.props.accessibilityLabel).toBe('Quloq dinamigi');
    expect(sp.props.accessibilityState).toMatchObject({ checked: false });
    await act(async () => {
      await fireEvent.press(sp);
    });
    expect(mockSession.actions.setEarpiece).toHaveBeenCalledWith(true);
    await setSnap({ earpiece: true });
    expect(screen.getByTestId('voice-speaker').props.accessibilityLabel).toBe('Quloq dinamigi');
    expect(screen.getByTestId('voice-speaker').props.accessibilityState).toMatchObject({ checked: true });
    expect(screen.getByTestId('icon-Ear')).toBeTruthy();
  });

  it('⚙ opens a dark sheet ON this screen (no navigation, the session keeps going); speed applies at once', async () => {
    useVoiceSettings.setState({ speed: 'normal', voice: 'uz_female_calm' });
    await renderVoice();
    await setSnap({ status: 'speaking', turnIds: [] });
    await act(async () => {
      await fireEvent.press(screen.getByTestId('voice-settings'));
    });
    expect(push).not.toHaveBeenCalled();
    expect(screen.getByTestId('voice-sheet')).toBeTruthy();
    await act(async () => {
      await fireEvent.press(screen.getByTestId('voice-sheet-speed-fast'));
      await fireEvent.press(screen.getByTestId('voice-sheet-male'));
    });
    expect(useVoiceSettings.getState()).toMatchObject({ speed: 'fast', voice: 'uz_male_news' });
    expect(screen.getByTestId('voice-sheet-speed-fast').props.accessibilityState).toMatchObject({ checked: true });
    await act(async () => {
      await fireEvent.press(screen.getByTestId('voice-sheet-close'));
    });
    expect(screen.queryByTestId('voice-sheet')).toBeNull();
    expect(mockSession.actions.end).not.toHaveBeenCalled();
  });

  it('✕ ends the session first, then closes the screen (once)', async () => {
    await renderVoice();
    await act(async () => {
      await fireEvent.press(screen.getByTestId('voice-end'));
      await fireEvent.press(screen.getByTestId('voice-end'));
    });
    expect(mockSession.actions.end).toHaveBeenCalledTimes(1);
    expect(back).toHaveBeenCalledTimes(1);
  });

  it('Android back = end', async () => {
    type Handler = Parameters<typeof BackHandler.addEventListener>[1];
    const handlers: Handler[] = [];
    const spy = jest.spyOn(BackHandler, 'addEventListener').mockImplementation((_e, h) => {
      handlers.push(h);
      return { remove: () => {} };
    });
    await renderVoice();
    let handled: boolean | null | undefined = false;
    await act(async () => {
      handled = handlers.at(-1)?.({} as Parameters<Handler>[0]);
    });
    expect(handled).toBe(true);
    expect(mockSession.actions.end).toHaveBeenCalledTimes(1);
    expect(back).toHaveBeenCalledTimes(1);
    spy.mockRestore();
  });

  it('text hidden: an answer that is NOT spoken (TTS failed, ru/en, long) is still shown as text', async () => {
    useVoiceSettings.setState({ showText: false });
    useChat.setState({ exchanges: [exchange({ id: 'e1', status: 'done', answer: 'Javob.' })] });
    await renderVoice();
    await setSnap({ status: 'listening', turnIds: ['e1'], notice: 'tts_failed', textOnly: true });
    expect(screen.getByTestId('voice-transcript')).toBeTruthy();
    expect(screen.getByTestId('voice-answer-e1').props.children).toBe('Javob.');
    // Ishonchsiz matnni tekshirish va yuborish ham matnsiz rejimda ishlaydi.
    await setSnap({ notice: 'unsure', textOnly: false, pendingText: "Ta'tilim qancha" });
    expect(screen.getByTestId('voice-send-pending')).toBeTruthy();
  });

  it('ru/en: says up front that answers come as text; no speaker switch; text always shown', async () => {
    useSettings.getState().set({ uiLang: 'ru' });
    useVoiceSettings.setState({ showText: false });
    useChat.setState({ exchanges: [exchange({ id: 'e1', status: 'done', answer: 'Ответ.' })] });
    await renderVoice();
    await setSnap({ status: 'listening', canSpeak: false });
    expect(screen.getByTestId('voice-text-only-note').props.children).toMatch(/текстом/);
    expect(screen.queryByTestId('voice-speaker')).toBeNull();
    await setSnap({ turnIds: ['e1'] });
    expect(screen.getByTestId('voice-transcript')).toBeTruthy();
    await act(async () => {
      await fireEvent.press(screen.getByTestId('voice-settings'));
    });
    const sw = screen.getByTestId('voice-sheet-show-text');
    expect(sw.props.accessibilityState).toMatchObject({ disabled: true });
    expect(sw.props.on).toBe(true);
  });

  it('earpiece mode: a cheek tap does not end the call or stop Barno - ✕ needs a long press', async () => {
    useChat.setState({ exchanges: [exchange({ id: 'e1', status: 'done', answer: 'Javob.' })] });
    await renderVoice();
    await setSnap({ status: 'speaking', turnIds: ['e1'], earpiece: true });
    await act(async () => {
      await fireEvent.press(screen.getByTestId('voice-end'));
    });
    expect(mockSession.actions.end).not.toHaveBeenCalled();
    const tr = screen.getByTestId('voice-transcript');
    await act(async () => {
      await fireEvent(tr, 'touchStart', { nativeEvent: { pageX: 100, pageY: 300 } });
      await fireEvent(tr, 'touchEnd', { nativeEvent: { pageX: 100, pageY: 300 } });
    });
    expect(mockSession.actions.interrupt).not.toHaveBeenCalled();
    await act(async () => {
      await fireEvent(screen.getByTestId('voice-end'), 'longPress');
    });
    expect(mockSession.actions.end).toHaveBeenCalledTimes(1);
  });

  it('TalkBack can stop Barno through an action on the mic button', async () => {
    await renderVoice();
    await setSnap({ status: 'speaking' });
    const mic = screen.getByTestId('voice-mic');
    expect(mic.props.accessibilityActions).toEqual(expect.arrayContaining([expect.objectContaining({ name: 'interrupt' })]));
    await act(async () => {
      await fireEvent(mic, 'accessibilityAction', { nativeEvent: { actionName: 'interrupt' } });
    });
    expect(mockSession.actions.interrupt).toHaveBeenCalledTimes(1);
    // Holat matni e'lon qilinmaydi (Barno ustidan gapirmasin); xato/eslatma - e'lon qilinadi.
    expect(screen.getByTestId('voice-status').props.accessibilityLiveRegion).toBe('none');
    await setSnap({ notice: 'no_speech' });
    expect(screen.getByTestId('voice-status').props.accessibilityLiveRegion).toBe('polite');
  });

  it('the interrupt hint is shown only for the first answers; muted -> "tap to stop"; preparing', async () => {
    await renderVoice();
    await setSnap({ status: 'thinking', preparing: true });
    expect(screen.getByTestId('voice-status').props.children).toBe('Tayyorlanmoqda…');
    await setSnap({ status: 'speaking', preparing: false, answersSpoken: 3 });
    expect(screen.getByTestId('voice-status').props.children).toBe('Barno gapiryapti');
    await setSnap({ micMuted: true });
    expect(screen.getByTestId('voice-status').props.children).toBe("To'xtatish uchun bosing");
  });

  it('text hidden: no transcript; the title becomes the state, the caption keeps only notices', async () => {
    useVoiceSettings.setState({ showText: false });
    useChat.setState({ exchanges: [exchange({ id: 'e1', status: 'done', answer: 'Javob.' })] });
    await renderVoice();
    await setSnap({ status: 'speaking', turnIds: ['e1'] });
    expect(screen.queryByTestId('voice-transcript')).toBeNull();
    expect(screen.getByTestId('voice-title').props.children).toBe("To'xtatish uchun gapiring yoki bosing");
    expect(screen.getByTestId('voice-status').props.children).toBe(' ');
    // Matnsiz rejimda ham o'rtaga tegish to'xtatadi.
    await act(async () => {
      await fireEvent.press(screen.getByTestId('voice-greeting'));
    });
    expect(mockSession.actions.interrupt).toHaveBeenCalledTimes(1);
    await setSnap({ status: 'listening', notice: 'tts_failed' });
    expect(screen.getByTestId('voice-status').props.children).toBe('Ovoz xizmati javob bermadi - javob ekranda');
  });

  it('Pro pill: hidden without Pro; toggles proOn; spent -> no toggle', async () => {
    await renderVoice();
    expect(screen.queryByTestId('voice-pro')).toBeNull();
    await act(async () => {
      usePro.setState({ available: true, remaining: 2 });
    });
    const pill = await screen.findByTestId('voice-pro');
    expect(screen.getByText('Pro · 2')).toBeTruthy();
    await act(async () => {
      await fireEvent.press(pill);
    });
    expect(useSettings.getState().proOn).toBe(true);
    await act(async () => {
      usePro.setState({ remaining: 0 });
    });
    await act(async () => {
      await fireEvent.press(screen.getByTestId('voice-pro'));
    });
    expect(useSettings.getState().proOn).toBe(true);
  });

  it('fog subscribes to the level stream and survives updates from both voices', async () => {
    await renderVoice();
    // Tuman + mikrofon halqasi.
    expect(mockSession.levels.size).toBe(2);
    await act(async () => {
      mockSession.levels.forEach((l) => l(0.7, 'user'));
      mockSession.levels.forEach((l) => l(0.4, 'barno'));
      mockSession.levels.forEach((l) => l(Number.NaN, 'none'));
    });
    expect(screen.getByTestId('voice-fog-cool')).toBeTruthy();
    expect(screen.getByTestId('voice-fog-warm')).toBeTruthy();
    await screen.unmount();
    expect(mockSession.levels.size).toBe(0);
  });
});

describe('voice status helpers', () => {
  const t = makeT('uz');
  it('first match wins: error, notice, suspended, then state', () => {
    expect(statusLine({ ...IDLE, status: 'error', error: 'mic_failed', notice: 'no_speech' }, t)).toEqual({ text: "Mikrofonni ochib bo'lmadi", kind: 'error' });
    expect(statusLine({ ...IDLE, status: 'listening', notice: 'auto_muted' }, t).kind).toBe('notice');
    expect(statusLine({ ...IDLE, status: 'listening', suspended: true }, t).text).toBe('Pauzada');
    expect(statusLine({ ...IDLE, status: 'thinking' }, t).text).toBe("O'ylayapman…");
    expect(makeT('ru')('nav.voice.uzOnly')).toMatch(/узбекском/);
  });

  it('fog dims for mute, error and connecting', () => {
    expect(fogDim('muted', true)).toBe(0.35);
    expect(fogDim('listening', true)).toBe(0.35);
    expect(fogDim('speaking', true)).toBe(1);
    expect(fogDim('error', false)).toBe(0.2);
    expect(fogDim('idle', false)).toBe(0.5);
    expect(fogDim('listening', false)).toBe(1);
  });
});
