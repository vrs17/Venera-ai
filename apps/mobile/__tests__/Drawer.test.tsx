/**
 * Chap panel (drawer): asosiy bo'limlar va ularning ko'rinish qoidasi (yig'ilishlar
 * yoqilmagan / oflayn lokal yozuv / yozuv ketmoqda), yo'nalishlar (avval yopiladi,
 * keyin o'tadi), suhbatlar ro'yxati holatlari, qidiruv, bosib turib nomlash/o'chirish,
 * yopilish yo'llari (fon, orqaga tugmasi, surish qoidasi).
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react-native';
import { router } from 'expo-router';
import { Alert, type AlertButton } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import type { ChatApi, ChatSummary } from '@/api/chat';
import { useAuth } from '@/features/auth/authStore';
import { useChat } from '@/features/chat/chatStore';
import { useChats } from '@/features/chat/chatsStore';
import { AppDrawer, drawerWidth, firstName, shouldClaimSwipe, shouldCloseOnRelease } from '@/features/nav/AppDrawer';
import { filterChats } from '@/features/nav/ChatList';
import { useRecorderStore } from '@/features/recorder/RecorderProvider';
import { initialRecorderState } from '@/features/recorder/recorderMachine';
import { useSettings } from '@/features/settings/settingsStore';
import { newQueueRow, type QueueRow } from '@/features/upload/queueStore';

import { fakeChatApi, fakeServices, Providers } from './fixtures/fakeServices';
import { config } from './fixtures/server';

jest.mock('expo-router', () => ({ router: { push: jest.fn(), replace: jest.fn(), navigate: jest.fn() } }));

const metrics = { frame: { x: 0, y: 0, width: 390, height: 844 }, insets: { top: 24, left: 0, right: 0, bottom: 16 } };

const DAY = 86_400_000;
const CHATS: ChatSummary[] = [
  { chat_id: 'old-1', title: "Ta'til qoldig'i", created_at: null, updated_at: new Date().toISOString() },
  { chat_id: 'old-2', title: 'Ish jadvalim', created_at: null, updated_at: new Date(Date.now() - 30 * DAY).toISOString() },
];

function chatApi(over: Partial<ChatApi> = {}): ChatApi {
  return fakeChatApi({ list: jest.fn(async () => ({ items: CHATS, limit: 50, offset: 0 })), ...over });
}

function localRow(over: Partial<QueueRow> = {}): QueueRow {
  return newQueueRow({
    clientId: 'c-1',
    fileUri: 'file:///doc/rec-1.aac',
    language: 'uz',
    template: 'auto',
    expectedSpeakers: null,
    source: 'app',
    startedAt: '2026-10-10T09:05:00Z',
    state: 'stopped',
    ...over,
  });
}

async function renderDrawer(opts: { chat?: ChatApi; rows?: QueueRow[] } = {}) {
  const chat = opts.chat ?? chatApi();
  const services = fakeServices({ chat });
  for (const r of opts.rows ?? []) await services.queue.insert(r);
  const onClose = jest.fn();
  const tree = (open: boolean) => (
    <SafeAreaProvider initialMetrics={metrics}>
      <Providers services={services}>
        <AppDrawer open={open} onClose={onClose} />
      </Providers>
    </SafeAreaProvider>
  );
  const view = await render(tree(true));
  await screen.findByTestId('drawer');
  return { chat, services, onClose, rerender: (open: boolean) => view.rerender(tree(open)) };
}

async function press(testID: string) {
  await act(async () => {
    await fireEvent.press(screen.getByTestId(testID));
  });
}

/** `Alert.alert` ning tugmalari - bosib turish menyusini qo'lda "bosish" uchun. */
function alertButtons(call = 0): AlertButton[] {
  return (jest.mocked(Alert.alert).mock.calls[call]?.[2] ?? []) as AlertButton[];
}

function button(buttons: AlertButton[], text: string): AlertButton {
  const b = buttons.find((x) => x.text === text);
  if (!b) throw new Error(`no alert button "${text}"`);
  return b;
}

let alertSpy: jest.SpyInstance;

beforeEach(() => {
  alertSpy = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
  useChat.getState().newChat();
  useChats.getState().reset();
  useSettings.getState().set({ uiLang: 'uz', themePref: 'light' });
  useAuth.getState().setSignedIn({ actorId: 7, actorType: 'EMPLOYEE', email: 'y@x.uz', fullName: 'Yusuf Mamajonov', position: null, department: null, roles: [], passwordChangeRequired: false });
  useAuth.getState().setConfig(null);
  useRecorderStore.setState({ machine: initialRecorderState });
});

// Faqat o'z josusimizni tiklaymiz (boshqa modul mocklariga tegmaymiz).
afterEach(() => {
  alertSpy.mockRestore();
});

describe('AppDrawer', () => {
  it('brand, new chat, grouped chats and the profile footer; meeting entries hidden while meetings are off', async () => {
    const { chat } = await renderDrawer();
    expect(screen.getByText('Barno')).toBeTruthy();
    expect(screen.getByTestId('drawer-new')).toBeTruthy();
    expect(screen.getByText('Suhbatlar')).toBeTruthy();
    expect(await screen.findByTestId('history-old-1')).toBeTruthy();
    expect(screen.getByText('Bugun')).toBeTruthy();
    expect(screen.getByText('Oldinroq')).toBeTruthy();
    // Profil: bosh harflar + ism (familiyasiz), sozlamalarga olib boradi.
    expect(screen.getByText('YM')).toBeTruthy();
    expect(screen.getByText('Yusuf')).toBeTruthy();
    expect(screen.getByTestId('drawer-settings').props.accessibilityLabel).toBe('Profil va sozlamalar');
    // Ism ostida ko'rinadigan "Sozlamalar" - avatarni bosish kerakligini taxmin qilish shart emas.
    expect(within(screen.getByTestId('drawer-settings')).getByText('Sozlamalar')).toBeTruthy();
    // Yig'ilishlar yoqilmagan, lokal yozuv ham yo'q - yozuv kirishlari yo'q.
    expect(screen.queryByTestId('drawer-recordings')).toBeNull();
    expect(screen.queryByTestId('drawer-tasks')).toBeNull();
    expect(screen.queryByTestId('drawer-record')).toBeNull();
    // Ochilganda ro'yxat jim yangilanadi.
    expect(chat.list).toHaveBeenCalled();
  });

  it('"Yangi suhbat" starts a new chat and closes the drawer', async () => {
    const { onClose } = await renderDrawer();
    // Jest'da UUID mock'i id bermaydi - yangi suhbatni `epoch` oshganidan bilamiz.
    const before = useChat.getState().epoch;
    await press('drawer-new');
    expect(useChat.getState().epoch).toBe(before + 1);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(router.push).not.toHaveBeenCalled();
  });

  it('with meetings on: Plaud, Vazifalarim, profile and the red pill close first, then navigate', async () => {
    useAuth.getState().setConfig(config);
    const { onClose } = await renderDrawer();
    expect(screen.getByText('Yozish')).toBeTruthy();
    const cases: [string, string][] = [
      ['drawer-recordings', '/meetings'],
      ['drawer-tasks', '/action-items'],
      ['drawer-settings', '/settings'],
      ['drawer-record', '/record?src=app'],
    ];
    for (const [id, path] of cases) {
      jest.mocked(router.push).mockClear();
      onClose.mockClear();
      await press(id);
      expect([id, jest.mocked(router.push).mock.calls]).toEqual([id, [[path]]]);
      expect(onClose).toHaveBeenCalledTimes(1);
      expect(onClose.mock.invocationCallOrder[0]).toBeLessThan(jest.mocked(router.push).mock.invocationCallOrder[0]);
    }
  });

  it('offline with a local recording: Plaud stays reachable and shows the not-uploaded count', async () => {
    await renderDrawer({ rows: [localRow(), localRow({ clientId: 'c-2', state: 'failed' }), localRow({ clientId: 'c-3', state: 'done' })] });
    const row = await screen.findByTestId('drawer-recordings');
    // Plaud belgisi - yig'ilish (`MeetingsIcon`), jonli suhbatning to'lqini emas.
    expect(within(row).getByTestId('icon-Meetings')).toBeTruthy();
    // `done` sanalmaydi.
    expect(screen.getByText('2')).toBeTruthy();
    expect(row.props.accessibilityLabel).toBe('Plaud, 2 ta yozuv yuklanmagan');
    expect(screen.getByTestId('drawer-record')).toBeTruthy();
    // Vazifalar - serverdagi yig'ilishlardan; konfig yo'q - ko'rsatilmaydi.
    expect(screen.queryByTestId('drawer-tasks')).toBeNull();
  });

  it('while recording: live pill on Plaud and the red pill shows the clock; paused shows "Pauzada"', async () => {
    const at = Date.now() - 65_000;
    useRecorderStore.setState({ machine: { ...initialRecorderState, status: 'recording', startedAt: at, segmentStartedAt: at } });
    await renderDrawer({ rows: [localRow({ state: 'recording' })] });
    const row = await screen.findByTestId('drawer-recordings');
    expect(row.props.accessibilityLabel).toBe('Plaud, Yozilmoqda');
    expect(screen.getByText('Yozilmoqda')).toBeTruthy();
    expect(screen.getByText(/^Yozilmoqda 01:0\d$/)).toBeTruthy();
    await act(async () => {
      useRecorderStore.setState({ machine: { ...initialRecorderState, status: 'paused', startedAt: at, accumulatedMs: 125_000, segmentStartedAt: null } });
    });
    expect(await screen.findByText('Pauzada 02:05')).toBeTruthy();
    expect(screen.getByTestId('drawer-record').props.accessibilityLabel).toBe('Pauzada 02:05');
  });

  it('search filters chats by title (case-insensitive), hides captions and primary rows, says when nothing matches', async () => {
    await renderDrawer();
    await screen.findByTestId('history-old-1');
    await press('drawer-search');
    const input = screen.getByTestId('drawer-search-input');
    expect(input.props.placeholder).toBe('Suhbatlardan qidirish');
    expect(screen.queryByText('Barno')).toBeNull();
    expect(screen.queryByTestId('drawer-new')).toBeNull();

    await act(async () => {
      await fireEvent.changeText(input, 'JADVAL');
    });
    expect(screen.getByTestId('history-old-2')).toBeTruthy();
    expect(screen.queryByTestId('history-old-1')).toBeNull();
    expect(screen.queryByText('Oldinroq')).toBeNull();

    await act(async () => {
      await fireEvent.changeText(input, 'zzz');
    });
    expect(screen.getByText('Hech narsa topilmadi')).toBeTruthy();

    await press('drawer-search-close');
    expect(screen.getByText('Barno')).toBeTruthy();
    expect(screen.getByTestId('history-old-1')).toBeTruthy();
    expect(screen.getByTestId('history-old-2')).toBeTruthy();
  });

  it('long-press -> rename through PromptModal', async () => {
    const { chat } = await renderDrawer();
    await act(async () => {
      await fireEvent(await screen.findByTestId('history-old-1'), 'longPress');
    });
    expect(jest.mocked(Alert.alert).mock.calls[0][0]).toBe("Ta'til qoldig'i");
    await act(async () => {
      button(alertButtons(), "Nomini o'zgartirish").onPress?.();
    });
    const field = await screen.findByTestId('prompt-input');
    expect(field.props.value).toBe("Ta'til qoldig'i");
    await act(async () => {
      await fireEvent.changeText(field, "Ta'til 2026");
    });
    await press('prompt-save');
    expect(chat.rename).toHaveBeenCalledWith('old-1', "Ta'til 2026");
    expect(await screen.findByText("Ta'til 2026")).toBeTruthy();
  });

  it('long-press -> delete the open chat removes it and starts a new chat', async () => {
    const { chat } = await renderDrawer();
    await act(async () => {
      useChat.setState({ chatId: 'old-1' });
    });
    const epoch = useChat.getState().epoch;
    await act(async () => {
      await fireEvent(await screen.findByTestId('history-old-1'), 'longPress');
    });
    await act(async () => {
      button(alertButtons(0), "O'chirish").onPress?.();
    });
    expect(jest.mocked(Alert.alert).mock.calls[1][0]).toBe("«Ta'til qoldig'i» suhbati o'chirilsinmi?");
    await act(async () => {
      button(alertButtons(1), "O'chirish").onPress?.();
    });
    await waitFor(() => expect(chat.remove).toHaveBeenCalledWith('old-1'));
    await waitFor(() => expect(useChat.getState().epoch).toBe(epoch + 1));
    expect(useChat.getState().chatId).not.toBe('old-1');
    expect(screen.queryByTestId('history-old-1')).toBeNull();
  });

  it('list states: load error with retry, then empty', async () => {
    const list = jest.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ items: [], limit: 50, offset: 0 });
    await renderDrawer({ chat: fakeChatApi({ list }) });
    expect(await screen.findByText("Suhbatlar ro'yxatini olib bo'lmadi")).toBeTruthy();
    await act(async () => {
      await fireEvent.press(screen.getByText('Qayta urinish'));
    });
    expect(await screen.findByText("Hali suhbat yo'q")).toBeTruthy();
    expect(list).toHaveBeenCalledTimes(2);
  });

  it('hardware back leaves search first, then closes the drawer', async () => {
    const { onClose } = await renderDrawer();
    await screen.findByTestId('history-old-1');
    await press('drawer-search');
    expect(screen.getByTestId('drawer-search-input')).toBeTruthy();
    await act(async () => {
      await fireEvent(screen.getByTestId('drawer-modal'), 'requestClose');
    });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.queryByTestId('drawer-search-input')).toBeNull();
    expect(screen.getByText('Barno')).toBeTruthy();
    await act(async () => {
      await fireEvent(screen.getByTestId('drawer-modal'), 'requestClose');
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('closes on scrim tap and hardware back; unmounts after the close animation', async () => {
    const { onClose, rerender } = await renderDrawer();
    await press('drawer-scrim');
    expect(onClose).toHaveBeenCalledTimes(1);
    await act(async () => {
      await fireEvent(screen.getByTestId('drawer-modal'), 'requestClose');
    });
    expect(onClose).toHaveBeenCalledTimes(2);
    await act(async () => {
      await rerender(false);
    });
    await waitFor(() => expect(screen.queryByTestId('drawer')).toBeNull());
  });
});

describe('drawer helpers', () => {
  it('panel width: 85% of the screen, at most 320', () => {
    expect(drawerWidth(360)).toBe(306);
    expect(drawerWidth(390)).toBe(320);
    expect(drawerWidth(800)).toBe(320);
  });

  it('swipe: claims only a clear leftward horizontal drag; closes past 30% or on a fast flick', () => {
    expect(shouldClaimSwipe(-20, 5)).toBe(true);
    expect(shouldClaimSwipe(-6, 0)).toBe(false);
    expect(shouldClaimSwipe(-20, 30)).toBe(false);
    expect(shouldClaimSwipe(20, 0)).toBe(false);
    expect(shouldCloseOnRelease(-100, 0, 300)).toBe(true);
    expect(shouldCloseOnRelease(-50, -0.6, 300)).toBe(true);
    expect(shouldCloseOnRelease(-50, -0.2, 300)).toBe(false);
  });

  it('filterChats / firstName', () => {
    expect(filterChats(CHATS, '  ', 'Yangi suhbat')).toBe(CHATS);
    expect(filterChats(CHATS, "ta'TIL", 'Yangi suhbat').map((c) => c.chat_id)).toEqual(['old-1']);
    expect(filterChats([{ chat_id: 'x', title: '', created_at: null, updated_at: null }], 'yangi', 'Yangi suhbat')).toHaveLength(1);
    expect(firstName('  Yusuf Mamajonov ')).toBe('Yusuf');
    expect(firstName(null)).toBe('');
  });
});
