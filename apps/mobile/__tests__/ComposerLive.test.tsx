/**
 * Chat: "Jonli" kirish tugmasi (bo'sh maydonda ↑ o'rnida), yig'ilish yozilayotganda
 * ogohlantirish, "Tinglash" 🔊 tugmasi va kichik pleer, ovozli savol belgisi.
 *
 * expo-router faqat `{ router }` bilan mock qilinadi (chat ekrani testi kabi): Composer,
 * ExchangeView, ReadAloudBar va ListenButton router hook'larini ishlatmasligi shart.
 */
import { act, fireEvent, render, screen } from '@testing-library/react-native';
import { router } from 'expo-router';

import { useChat, type Exchange } from '@/features/chat/chatStore';
import { Composer } from '@/features/chat/ui/Composer';
import { ExchangeView } from '@/features/chat/ui/ExchangeView';
import { useRecorderStore } from '@/features/recorder/RecorderProvider';
import { initialRecorderState } from '@/features/recorder/recorderMachine';
import { useSettings } from '@/features/settings/settingsStore';
import * as readAloud from '@/features/voice/readAloud';
import { showToast } from '@/ui/errors';

import { fakeActionsApi, fakeChatApi, fakeServices, Providers } from './fixtures/fakeServices';

jest.mock('expo-router', () => ({ router: { push: jest.fn(), replace: jest.fn(), navigate: jest.fn() } }));
jest.mock('@/ui/errors', () => ({ ...jest.requireActual('@/ui/errors'), showToast: jest.fn() }));

const push = router.push as jest.Mock;
const controls = { toggle: jest.fn(), pause: jest.fn(), resume: jest.fn(), stop: jest.fn(), preview: jest.fn() };

beforeEach(() => {
  jest.spyOn(readAloud, 'useReadAloudControls').mockReturnValue(controls);
  readAloud.useReadAloud.setState({ key: null, phase: 'idle', index: 0, total: null });
  useSettings.getState().set({ uiLang: 'uz', proOn: false, themePref: 'light' });
  useRecorderStore.setState({ machine: initialRecorderState });
  useChat.getState().newChat();
});

afterEach(() => {
  jest.restoreAllMocks();
});

async function renderComposer() {
  const onSend = jest.fn(() => true);
  await render(
    <Providers services={fakeServices()}>
      <Composer api={fakeChatApi()} busy={false} onSend={onSend} onStop={jest.fn()} />
    </Providers>,
  );
  return { onSend };
}

describe('Composer "Jonli"', () => {
  it('empty field: the primary button opens live voice; typing turns it into send', async () => {
    await renderComposer();
    const live = screen.getByTestId('composer-live');
    expect(live.props.accessibilityLabel).toBe('Jonli suhbat');
    expect(screen.queryByTestId('composer-send')).toBeNull();
    // Mikrofon diktovka bo'lib qoladi.
    expect(screen.getByTestId('composer-mic')).toBeTruthy();
    await act(async () => {
      await fireEvent.press(live);
    });
    expect(push).toHaveBeenCalledWith('/voice');

    await fireEvent.changeText(screen.getByTestId('composer-input'), 'Salom');
    expect(screen.getByTestId('composer-send')).toBeTruthy();
    expect(screen.queryByTestId('composer-live')).toBeNull();
    await fireEvent.changeText(screen.getByTestId('composer-input'), '   ');
    expect(screen.getByTestId('composer-live')).toBeTruthy();
  });

  it('a meeting recording in progress: toast, no navigation', async () => {
    useRecorderStore.setState({ machine: { ...initialRecorderState, status: 'recording' } as typeof initialRecorderState });
    await renderComposer();
    await act(async () => {
      await fireEvent.press(screen.getByTestId('composer-live'));
    });
    expect(push).not.toHaveBeenCalled();
    expect(showToast).toHaveBeenCalledWith(expect.stringMatching(/yozilmoqda|Yig'ilish/i));
  });

  it('read-aloud mini player sits above the card: label, pause/resume, stop', async () => {
    await renderComposer();
    expect(screen.queryByTestId('readaloud-bar')).toBeNull();
    await act(async () => {
      readAloud.useReadAloud.setState({ key: 'ex-1', phase: 'loading', index: 0, total: null });
    });
    expect(screen.getByTestId('readaloud-label').props.children).toBe('Ovoz tayyorlanmoqda…');
    await act(async () => {
      readAloud.useReadAloud.setState({ phase: 'playing', index: 2, total: null });
    });
    // Bo'lak hisobi ko'rsatilmaydi (ichki narsa) - faqat holat.
    expect(screen.getByTestId('readaloud-label').props.children).toBe("O'qilmoqda");
    await act(async () => {
      await fireEvent.press(screen.getByTestId('readaloud-pause'));
    });
    expect(controls.pause).toHaveBeenCalledTimes(1);
    await act(async () => {
      readAloud.useReadAloud.setState({ phase: 'paused', total: 4 });
    });
    expect(screen.getByTestId('readaloud-label').props.children).toBe("O'qilmoqda");
    expect(screen.getByTestId('readaloud-pause').props.accessibilityLabel).toBe('Davom etish');
    await act(async () => {
      await fireEvent.press(screen.getByTestId('readaloud-pause'));
    });
    expect(controls.resume).toHaveBeenCalledTimes(1);
    await act(async () => {
      await fireEvent.press(screen.getByTestId('readaloud-stop'));
    });
    expect(controls.stop).toHaveBeenCalledTimes(1);
    // Sozlamalardagi namuna chat pleerida ko'rinmaydi.
    await act(async () => {
      readAloud.useReadAloud.setState({ key: readAloud.PREVIEW_KEY, phase: 'playing', index: 1 });
    });
    expect(screen.queryByTestId('readaloud-bar')).toBeNull();
  });

  it('starting dictation stops read-aloud first (its audio would be recorded)', async () => {
    const stop = jest.spyOn(readAloud, 'stopReadAloud');
    await renderComposer();
    await act(async () => {
      await fireEvent.press(screen.getByTestId('composer-mic'));
    });
    expect(stop).toHaveBeenCalled();
  });
});

function done(over: Partial<Exchange> = {}): Exchange {
  return {
    id: 'ex-1',
    question: 'Bugun kim kechikdi?',
    answer: "Bugun uch kishi kechikdi. Ali, Vali va Sardor o'z vaqtida kelmadi.",
    status: 'done',
    stage: null,
    sources: [],
    artifact: null,
    proposal: null,
    error: null,
    errorCode: null,
    warning: null,
    proRequested: false,
    pro: null,
    engine: 'v3',
    askedAt: null,
    answeredAt: null,
    turnId: 'a'.repeat(32),
    input: 'text',
    holds: [],
    ...over,
  };
}

async function renderExchange(ex: Exchange) {
  await render(
    <Providers services={fakeServices()}>
      <ExchangeView ex={ex} api={fakeChatApi()} actions={fakeActionsApi()} live onRetry={jest.fn()} onReconnect={jest.fn()} onSources={jest.fn()} />
    </Providers>,
  );
}

describe('ExchangeView "Tinglash"', () => {
  it('a finished Uzbek answer has 🔊 before copy; pressing toggles read-aloud for this answer', async () => {
    await renderExchange(done());
    const btn = screen.getByTestId('answer-listen');
    expect(btn.props.accessibilityLabel).toBe('Tinglash');
    await act(async () => {
      await fireEvent.press(btn);
    });
    expect(controls.toggle).toHaveBeenCalledWith('ex-1', done().answer, 'a'.repeat(32));
    await act(async () => {
      readAloud.useReadAloud.setState({ key: 'ex-1', phase: 'loading' });
    });
    expect(screen.getByTestId('answer-listen').props.accessibilityState).toMatchObject({ busy: true });
    await act(async () => {
      readAloud.useReadAloud.setState({ phase: 'playing', index: 1 });
    });
    expect(screen.getByTestId('answer-listen').props.accessibilityLabel).toBe("To'xtatish");
    // Boshqa javob o'qilsa bu tugma oddiy holatga qaytadi.
    await act(async () => {
      readAloud.useReadAloud.setState({ key: 'ex-2' });
    });
    expect(screen.getByTestId('answer-listen').props.accessibilityLabel).toBe('Tinglash');
  });

  it('hidden for other UI languages, Cyrillic answers and unfinished answers', async () => {
    useSettings.getState().set({ uiLang: 'ru' });
    await renderExchange(done());
    expect(screen.queryByTestId('answer-listen')).toBeNull();
    await screen.unmount();

    useSettings.getState().set({ uiLang: 'uz' });
    await renderExchange(done({ answer: 'Сегодня опоздали трое сотрудников.' }));
    expect(screen.queryByTestId('answer-listen')).toBeNull();
    await screen.unmount();

    await renderExchange(done({ status: 'streaming' }));
    expect(screen.queryByTestId('answer-listen')).toBeNull();
  });

  it('a voice question carries a small mic mark and a spoken label', async () => {
    await renderExchange(done({ input: 'voice' }));
    const q = screen.getByTestId('question-voice');
    expect(q.props.accessibilityLabel).toBe('Ovozli savol: Bugun kim kechikdi?');
    expect(screen.getByTestId('icon-Mic')).toBeTruthy();
    await screen.unmount();
    await renderExchange(done());
    expect(screen.queryByTestId('question-voice')).toBeNull();
  });
});
