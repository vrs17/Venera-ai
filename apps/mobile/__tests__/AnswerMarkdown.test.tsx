/**
 * Chat javobini o'qish qulayligi (2026-10-10, egasining skrinshoti - CRM vazifalari javobi):
 *  - `[T2]` (jonli so'rov belgisi) matnda ko'rinmaydi, "Manbalar" tugmasi qoladi;
 *  - `[1]` (hujjat) - kichik yuqori indeks, bosilsa manbalar ochiladi;
 *  - `DVSIB-245` kabi vazifa kalitlari kichik va xira;
 *  - "Oxirgi xabarga" (↓) tugmasi o'rtada emas, o'ng chetda - javob matnini yopmaydi.
 */
import { act, fireEvent, render, screen } from '@testing-library/react-native';
import { StyleSheet } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import type { ChatFrame } from '@/api/chat';
import ChatScreen from '@/app/index';
import { useAuth } from '@/features/auth/authStore';
import { useChat } from '@/features/chat/chatStore';
import { useChats } from '@/features/chat/chatsStore';
import { usePro } from '@/features/chat/proStore';
import { AnswerMarkdown, answerPieces, isTaskKey, stripToolMarks, superscript } from '@/features/chat/ui/AnswerMarkdown';
import { useRecorderStore } from '@/features/recorder/RecorderProvider';
import { initialRecorderState } from '@/features/recorder/recorderMachine';
import { useSettings } from '@/features/settings/settingsStore';
import { lightTheme } from '@/ui/theme';

import { fakeChatApi, fakeServices, Providers } from './fixtures/fakeServices';

jest.mock('expo-router', () => ({ router: { push: jest.fn(), replace: jest.fn(), navigate: jest.fn() } }));

const flat = (el: { props: { style?: unknown } }) => (StyleSheet.flatten(el.props.style as never) ?? {}) as Record<string, unknown>;

beforeEach(() => {
  useSettings.getState().set({ uiLang: 'uz', proOn: false, themePref: 'light' });
});

describe('answer marks (pure)', () => {
  it('drops [Tn] with the space before it, keeps code-free text intact', () => {
    expect(stripToolMarks('Bugun kechikmadingiz [T1]. Topshirildi [T1, T2][T3].')).toBe('Bugun kechikmadingiz. Topshirildi.');
    expect(stripToolMarks('[1] hujjat')).toBe('[1] hujjat');
  });

  it('splits text into plain parts, document citations and task keys', () => {
    expect(answerPieces('Ta\'til 24 kun [1][2] - DVSIB-245 (HR2-17) [T4].')).toEqual([
      { kind: 'text', text: "Ta'til 24 kun" },
      { kind: 'cite', n: '1' },
      { kind: 'cite', n: '2' },
      { kind: 'text', text: ' - ' },
      { kind: 'key', text: 'DVSIB-245' },
      { kind: 'text', text: ' (' },
      { kind: 'key', text: 'HR2-17' },
      { kind: 'text', text: ').' },
    ]);
    // So'z ichida yoki davomi bor bo'lsa - kalit emas.
    for (const s of ['xDVSIB-1', 'DVSIB-245a', 'A-B-12', 'DVSIB-1-2', 'oʻDVSIB-3', 'ёDV-3', 'Dvsib-3']) {
      expect([s, answerPieces(s).some((p) => p.kind === 'key')]).toEqual([s, false]);
    }
    expect(answerPieces('Link [1]', { cites: false })).toEqual([{ kind: 'text', text: 'Link [1]' }]);
    expect(superscript('120')).toBe('¹²⁰');
  });

  it('common non-task codes (COVID-19, UTF-8, ISO-9001, SHA-256, Q3-2026, H1-2026, MRZ-2) are NOT muted', () => {
    for (const s of ['COVID-19', 'UTF-8', 'ISO-9001', 'SHA-256', 'Q3-2026', 'H1-2026', 'MRZ-2']) {
      expect([s, isTaskKey(s), answerPieces(`Standart ${s} bo'yicha`).some((p) => p.kind === 'key')]).toEqual([s, false, false]);
    }
    for (const s of ['DVSIB-245', 'HR2-17', 'Q12-3']) expect([s, isTaskKey(s)]).toEqual([s, true]);
  });
});

describe('AnswerMarkdown', () => {
  it('[Tn] markers are hidden (no grey boxes after bullets)', async () => {
    await render(<AnswerMarkdown text={'- Hisobot topshirildi [T2]\n- Reja tasdiqlandi [T1, T2]'} />);
    expect(screen.getByText('Hisobot topshirildi')).toBeTruthy();
    expect(screen.getByText('Reja tasdiqlandi')).toBeTruthy();
    expect(screen.queryByText(/T\d/)).toBeNull();
  });

  it('[n] is a small superscript glued to the word; tapping it opens the sources', async () => {
    const onCite = jest.fn();
    await render(<AnswerMarkdown text="Ta'til 24 kun [1][2]." onCite={onCite} />);
    const one = screen.getByText('¹');
    // Ketma-ket iqtiboslar "¹²" (o'n ikki) emas - vergul bilan, web va Mini App kabi.
    const two = screen.getByText(',²');
    expect(two.props.accessibilityLabel).toBe('2-manba');
    expect(one.props.accessibilityLabel).toBe('1-manba');
    expect(screen.queryByText(/\[1\]/)).toBeNull();
    expect(flat(one)).toMatchObject({ color: lightTheme.brand, fontWeight: '700' });
    expect(flat(one).backgroundColor).toBeUndefined();
    await fireEvent.press(one);
    expect(onCite).toHaveBeenCalledWith('1');
  });

  it('task keys are small and muted, even inside bold text or inline code; the task name stays primary', async () => {
    await render(<AnswerMarkdown text={'1. **DVSIB-245** Oylik hisobotni topshirish\n2. `DVSIB-12` Reja'} />);
    const key = flat(screen.getByText('DVSIB-245'));
    expect(key).toMatchObject({ fontSize: 13, fontWeight: '400', color: lightTheme.textMuted });
    expect(flat(screen.getByText(' Oylik hisobotni topshirish')).fontSize).toBeUndefined();
    const code = flat(screen.getByText('DVSIB-12'));
    expect(code).toMatchObject({ fontSize: 13, color: lightTheme.textMuted });
    expect(code.backgroundColor).toBeUndefined();
  });

  it('code is never touched: [T1] inside a code block or inline code stays', async () => {
    await render(<AnswerMarkdown text={'`[T1]` va\n\n```\nGET /x [T2]\n```'} />);
    expect(screen.getByText('[T1]')).toBeTruthy();
    expect(screen.getByText('GET /x [T2]')).toBeTruthy();
  });
});

describe('chat jump-to-latest button', () => {
  const metrics = { frame: { x: 0, y: 0, width: 390, height: 844 }, insets: { top: 24, left: 0, right: 0, bottom: 16 } };

  beforeEach(() => {
    useChat.getState().newChat();
    useChats.getState().reset();
    usePro.getState().reset();
    useAuth.getState().setSignedIn({ actorId: 7, actorType: 'EMPLOYEE', email: 'y@x.uz', fullName: 'Yusuf Mamajonov', position: null, department: null, roles: [], passwordChangeRequired: false });
    useAuth.getState().setConfig(null);
    useRecorderStore.setState({ machine: initialRecorderState });
  });

  it('sits at the right edge above the composer, not over the middle of the answer', async () => {
    const frames: ChatFrame[] = [{ type: 'token', text: 'Uzun javob [T1].' }, { type: 'done', engine: 'v3' }];
    const stream = jest.fn(async (_q: string, onFrame: (f: ChatFrame) => void) => {
      for (const f of frames) onFrame(f);
    });
    await render(
      <SafeAreaProvider initialMetrics={metrics}>
        <Providers services={fakeServices({ chat: fakeChatApi({ stream }) })}>
          <ChatScreen />
        </Providers>
      </SafeAreaProvider>,
    );
    await fireEvent.changeText(await screen.findByTestId('composer-input'), 'Vazifalarim');
    await act(async () => {
      await fireEvent.press(screen.getByTestId('composer-send'));
    });
    expect(await screen.findByText('Uzun javob.')).toBeTruthy();
    expect(screen.queryByTestId('chat-jump')).toBeNull();

    await fireEvent.scroll(screen.getByTestId('chat-scroll'), {
      nativeEvent: { contentOffset: { x: 0, y: 0 }, contentSize: { width: 390, height: 3000 }, layoutMeasurement: { width: 390, height: 600 } },
    });
    const jump = await screen.findByTestId('chat-jump');
    expect(jump.props.accessibilityLabel).toBe('Oxirgi xabarga');
    const style = flat(jump);
    expect(style).toMatchObject({ position: 'absolute', right: 12 });
    expect(style.alignSelf).toBeUndefined();
    expect(style.left).toBeUndefined();
  });
});
