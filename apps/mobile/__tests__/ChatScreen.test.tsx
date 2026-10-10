/**
 * Native chat ekrani: salomlashuv -> tayyor savol -> oqimli javob (manbalar bilan),
 * HRM/CRM ulanmagan xatosi -> "Qayta ulash", to'xtatish, drawer'dan tarixni ochish,
 * Pro kaliti, diktovka (to'xtatib tahrirlash va darhol yuborish), tepa panel
 * (☰ / ≋ Yozuvlar / qizil yozuv chizig'i).
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { router } from 'expo-router';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import type { ChatFrame } from '@/api/chat';
import ChatScreen from '@/app/index';
import { useAuth } from '@/features/auth/authStore';
import { useChat } from '@/features/chat/chatStore';
import { useChats } from '@/features/chat/chatsStore';
import { usePro } from '@/features/chat/proStore';
import { useRecorderStore } from '@/features/recorder/RecorderProvider';
import { initialRecorderState } from '@/features/recorder/recorderMachine';
import { useSettings } from '@/features/settings/settingsStore';

import { fakeChatApi, fakeServices, Providers } from './fixtures/fakeServices';
import { config } from './fixtures/server';

jest.mock('expo-router', () => ({ router: { push: jest.fn(), replace: jest.fn(), navigate: jest.fn() } }));

const metrics = { frame: { x: 0, y: 0, width: 390, height: 844 }, insets: { top: 24, left: 0, right: 0, bottom: 16 } };

async function renderChat(chat = fakeChatApi()) {
  const services = fakeServices({ chat });
  await render(
    <SafeAreaProvider initialMetrics={metrics}>
      <Providers services={services}>
        <ChatScreen />
      </Providers>
    </SafeAreaProvider>,
  );
  return { services, chat };
}

/** ☰ - drawer ochiladi. */
async function renderChatMenu() {
  await act(async () => {
    await fireEvent.press(await screen.findByTestId('chat-menu'));
  });
  await screen.findByTestId('drawer');
}

/** Kadrlarni ketma-ket beradigan soxta oqim. */
function streamOf(frames: ChatFrame[]) {
  return jest.fn(async (_q: string, onFrame: (f: ChatFrame) => void) => {
    for (const f of frames) onFrame(f);
  });
}

beforeEach(() => {
  useChat.getState().newChat();
  useChats.getState().reset();
  usePro.getState().reset();
  useSettings.getState().set({ uiLang: 'uz', proOn: false, themePref: 'light' });
  useAuth.getState().setSignedIn({ actorId: 7, actorType: 'EMPLOYEE', email: 'y@x.uz', fullName: 'Yusuf Mamajonov', position: null, department: null, roles: [], passwordChangeRequired: false });
  useAuth.getState().setConfig(null);
  useRecorderStore.setState({ machine: initialRecorderState });
});

describe('ChatScreen', () => {
  it('welcome -> suggested question -> streamed answer with sources', async () => {
    const stream = streamOf([
      { type: 'stage', text: 'HRM tekshirilmoqda' },
      { type: 'sources', items: [{ kind: 'hrm', tool: 'hrm_today_late', marker: 'T1', digest: '09:02 da keldingiz' }, { kind: 'doc', doc_id: 'd1', title: 'Ichki tartib', citation_index: 1 }] },
      { type: 'token', text: '**Yo\'q**, bugun ' },
      { type: 'token', text: 'kechikmadingiz [T1].' },
      { type: 'done', engine: 'v3' },
    ]);
    const { chat } = await renderChat(fakeChatApi({ stream }));
    expect(await screen.findByText('Salom, Yusuf')).toBeTruthy();
    await act(async () => {
      await fireEvent.press(screen.getByText('Bugun kechikdimmi?'));
    });
    expect(stream).toHaveBeenCalledWith('Bugun kechikdimmi?', expect.any(Function), expect.objectContaining({ mode: 'standard', locale: 'uz' }));
    expect(await screen.findByText('2 manba')).toBeTruthy();
    expect(screen.getByText("Yo'q")).toBeTruthy();
    // Javobdan keyin tarix ro'yxatida suhbat paydo bo'ladi (vaqtinchalik nom).
    expect(useChats.getState().items[0]?.title).toBe('Bugun kechikdimmi?');
    expect(chat.list).toHaveBeenCalled();
  });

  it('auth_missing error frame without tokens -> "Qayta ulash" instead of retry', async () => {
    const stream = streamOf([{ type: 'error', code: 'auth_missing', text: 'CRM tokeni yo\'q' }, { type: 'done' }]);
    await renderChat(fakeChatApi({ stream }));
    await fireEvent.changeText(await screen.findByTestId('composer-input'), 'Vazifalarim');
    await act(async () => {
      await fireEvent.press(screen.getByTestId('composer-send'));
    });
    expect(await screen.findByText(/CRM ulanmagan yoki muddati tugagan/)).toBeTruthy();
    expect(screen.getByText('Qayta ulash')).toBeTruthy();
    expect(screen.queryByText('Qayta urinish')).toBeNull();
  });

  it('send is disabled while empty; stop cancels an answer in flight', async () => {
    let release: (() => void) | null = null;
    const stream = jest.fn(
      (_q: string, _f: (f: ChatFrame) => void, opts?: { signal?: AbortSignal }) =>
        new Promise<void>((resolve, reject) => {
          release = resolve;
          opts?.signal?.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
        }),
    );
    await renderChat(fakeChatApi({ stream }));
    expect(await screen.findByTestId('composer-live')).toBeTruthy();
    expect(screen.queryByTestId('composer-send')).toBeNull();
    await fireEvent.changeText(screen.getByTestId('composer-input'), 'Ish jadvalim');
    await act(async () => {
      await fireEvent.press(screen.getByTestId('composer-send'));
    });
    expect(await screen.findByTestId('composer-stop')).toBeTruthy();
    await act(async () => {
      await fireEvent.press(screen.getByTestId('composer-stop'));
    });
    expect(useChat.getState().phase).toBe('idle');
    expect(useChat.getState().exchanges[0].status).toBe('cancelled');
    expect(release).not.toBeNull();
  });

  it('opens a chat from history (☰ -> drawer -> chat row)', async () => {
    const chat = fakeChatApi({
      list: jest.fn(async () => ({ items: [{ chat_id: 'old-1', title: "Ta'til qoldig'i", created_at: null, updated_at: new Date().toISOString() }], limit: 50, offset: 0 })),
      get: jest.fn(async (id: string) => ({
        chat_id: id,
        title: "Ta'til qoldig'i",
        created_at: null,
        updated_at: null,
        messages: [
          { role: 'user', content: "Ta'tilim qancha qoldi?", created_at: null },
          { role: 'assistant', content: '12 kun qoldi.', created_at: null },
        ],
      })),
    });
    await renderChat(chat);
    await renderChatMenu();
    await act(async () => {
      await fireEvent.press(await screen.findByTestId('history-old-1'));
    });
    expect(chat.get).toHaveBeenCalledWith('old-1');
    expect(await screen.findByText('12 kun qoldi.')).toBeTruthy();
    expect(screen.getByText("Ta'tilim qancha qoldi?")).toBeTruthy();
    // Tanlangandan keyin drawer yopiladi (yopilish animatsiyasidan so'ng Modal yo'qoladi).
    await waitFor(() => expect(screen.queryByTestId('drawer')).toBeNull());
    // Ochilgan suhbat nomi tepada.
    expect(screen.getByText("Ta'til qoldig'i")).toBeTruthy();
  });

  it('top bar: ☰ opens the drawer; profile moved from the top bar to the drawer footer', async () => {
    await renderChat();
    expect(screen.queryByTestId('chat-settings')).toBeNull();
    expect(screen.queryByTestId('chat-history')).toBeNull();
    expect(screen.queryByTestId('drawer')).toBeNull();
    expect(screen.getByTestId('chat-menu').props.accessibilityLabel).toBe('Menyu');
    await renderChatMenu();
    expect(screen.getByTestId('drawer')).toBeTruthy();
    await act(async () => {
      await fireEvent.press(screen.getByTestId('drawer-settings'));
    });
    expect(router.push).toHaveBeenCalledWith('/settings');
  });

  it('top bar: ≋ Yozuvlar is hidden without meetings and opens /meetings in one tap when enabled', async () => {
    await renderChat();
    expect(screen.queryByTestId('chat-meetings')).toBeNull();
    await act(async () => {
      useAuth.getState().setConfig(config);
    });
    const btn = await screen.findByTestId('chat-meetings');
    expect(btn.props.accessibilityLabel).toBe('Yozuvlar');
    await act(async () => {
      await fireEvent.press(btn);
    });
    expect(router.push).toHaveBeenCalledWith('/meetings');
  });

  it('red recording strip shows the live clock and opens the recorder', async () => {
    await renderChat();
    expect(screen.queryByTestId('chat-recording')).toBeNull();
    const at = Date.now() - 65_000;
    await act(async () => {
      useRecorderStore.setState({ machine: { ...initialRecorderState, status: 'recording', startedAt: at, segmentStartedAt: at } });
    });
    // Soat har soniya yuradi - aniq soniyaga emas, formatga qaraymiz.
    expect(await screen.findByText(/^Yozilmoqda 01:0\d$/)).toBeTruthy();
    // Yozuv paytida ≋ ham ko'rinadi (konfig bo'lmasa ham - yozuv topiladigan bo'lsin).
    expect(screen.getByTestId('chat-meetings')).toBeTruthy();
    await act(async () => {
      await fireEvent.press(screen.getByTestId('chat-recording'));
    });
    expect(router.push).toHaveBeenCalledWith('/record?src=app');

    await act(async () => {
      useRecorderStore.setState({ machine: { ...initialRecorderState, status: 'paused', startedAt: at, accumulatedMs: 125_000, segmentStartedAt: null } });
    });
    expect(await screen.findByText('Pauzada 02:05')).toBeTruthy();
  });

  it('Pro pill shows when the engine allows it and the next question goes as pro', async () => {
    const stream = streamOf([{ type: 'token', text: 'ok' }, { type: 'done', pro: { requested: true, used: true, calls: 1, remaining: { day: 4, week: 9, month: 9 } } }]);
    const chat = fakeChatApi({
      stream,
      proQuota: jest.fn(async () => ({ remaining: { day: 5, week: 9, month: 9 }, limits: { day: 5, week: 9, month: 9 }, used: { day: 0, week: 0, month: 0 }, engine: 'v3', available: true })),
    });
    await renderChat(chat);
    const pill = await screen.findByTestId('composer-pro');
    await act(async () => {
      await fireEvent.press(pill);
    });
    expect(useSettings.getState().proOn).toBe(true);
    await fireEvent.changeText(screen.getByTestId('composer-input'), 'Murakkab savol');
    await act(async () => {
      await fireEvent.press(screen.getByTestId('composer-send'));
    });
    expect(stream).toHaveBeenCalledWith('Murakkab savol', expect.any(Function), expect.objectContaining({ mode: 'pro' }));
    await waitFor(() => expect(usePro.getState().remaining).toBe(4));
  });

  it('dictation: ↑ sends the transcribed text right away, ■ only puts it in the field', async () => {
    const stream = streamOf([{ type: 'token', text: 'ok' }, { type: 'done' }]);
    const transcribe = jest.fn(async () => ({ text: 'Bugungi vazifalarim qanday', truncated: false }));
    await renderChat(fakeChatApi({ stream, transcribe }));
    const t0 = Date.now();
    const now = jest.spyOn(Date, 'now');

    // ■ - matn maydonga tushadi, yuborilmaydi.
    now.mockReturnValue(t0);
    await act(async () => {
      await fireEvent.press(await screen.findByTestId('composer-mic'));
    });
    await screen.findByTestId('dict-stop');
    // To'lqin taymeri ovoz darajasini o'qib ulgursin (gap bor-yo'qligi shundan).
    await act(async () => {
      await new Promise((r) => setTimeout(r, 250));
    });
    now.mockReturnValue(t0 + 3000);
    await act(async () => {
      await fireEvent.press(screen.getByTestId('dict-stop'));
    });
    await waitFor(() => expect(screen.getByTestId('composer-input').props.value).toBe('Bugungi vazifalarim qanday'));
    expect(stream).not.toHaveBeenCalled();
    expect(transcribe).toHaveBeenCalledWith(expect.stringMatching(/^file:/), 'audio/aac', 'uz', expect.anything());

    // ↑ - darhol yuboriladi.
    now.mockReturnValue(t0 + 10_000);
    await act(async () => {
      await fireEvent.press(screen.getByTestId('composer-mic'));
    });
    await screen.findByTestId('dict-send');
    await act(async () => {
      await new Promise((r) => setTimeout(r, 250));
    });
    now.mockReturnValue(t0 + 14_000);
    await act(async () => {
      await fireEvent.press(screen.getByTestId('dict-send'));
    });
    await waitFor(() => expect(stream).toHaveBeenCalledWith('Bugungi vazifalarim qanday', expect.any(Function), expect.anything()));
    now.mockRestore();
  });
});
