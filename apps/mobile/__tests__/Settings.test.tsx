/**
 * Sozlamalar hub'i va ichki sahifalari (Claude uslubi): hub qiymatlari (ulanishlar,
 * tez yozish soni, til, mavzu, yozish va xotira), qatorlar to'g'ri sahifaga olib boradi,
 * til/mavzu tanlovi, ulanishlar va qayta kirish, tez yozish kartalari (native modul
 * bor/yo'q), yozish va xotira, profil, ilova haqida, chiqish (tasdiq, yozuv paytida blok).
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react-native';
import { router } from 'expo-router';
import { Alert, AppState, type AlertButton } from 'react-native';

import type { ChatApi, ConnectorStatus } from '@/api/chat';
import type { MeetingsConfig } from '@/api/types';
import AboutScreen from '@/app/settings/about';
import AccountScreen from '@/app/settings/account';
import ConnectionsScreen from '@/app/settings/connections';
import SettingsScreen from '@/app/settings/index';
import LanguageScreen from '@/app/settings/language';
import QuickRecordScreen from '@/app/settings/quick';
import RecordingSettingsScreen from '@/app/settings/recording';
import ThemeScreen from '@/app/settings/theme';
import { useAuth } from '@/features/auth/authStore';
import { useChat } from '@/features/chat/chatStore';
import type { AddTileResult } from '@/features/entry/nativeEntry';
import { useRecorderStore } from '@/features/recorder/RecorderProvider';
import { initialRecorderState } from '@/features/recorder/recorderMachine';
import { LANG_ENDONYM } from '@/features/settings/langNames';
import { quickMethodCount } from '@/features/settings/quickMethods';
import { useSettings } from '@/features/settings/settingsStore';
import { newQueueRow, type QueueRow } from '@/features/upload/queueStore';
import type { Services } from '@/services';

import { fakeChatApi, fakeServices, Providers } from './fixtures/fakeServices';

jest.mock('expo-router', () => {
  const React = jest.requireActual<typeof import('react')>('react');
  return {
    router: { push: jest.fn(), replace: jest.fn(), navigate: jest.fn(), back: jest.fn() },
    // Testda navigator yo'q: "fokus" = birinchi chizilish.
    useFocusEffect: (cb: () => void) => React.useEffect(cb, [cb]),
  };
});

// Native modul (VeneraEntry) holati testdan boshqariladi; default - modul yo'q (Jest/iOS kabi).
const mockNative = { available: false, launcher: false, volume: false, tile: 'added' as AddTileResult };
jest.mock('@/features/entry/nativeEntry', () => ({
  isAvailable: jest.fn(() => mockNative.available),
  isLauncherEnabled: jest.fn(() => mockNative.available && mockNative.launcher),
  isKeyServiceEnabled: jest.fn(() => mockNative.available && mockNative.volume),
  setLauncherEnabled: jest.fn((v: boolean) => {
    mockNative.launcher = v;
  }),
  requestAddTile: jest.fn(async () => (mockNative.available ? mockNative.tile : 'unsupported')),
  openAccessibilitySettings: jest.fn(),
  setRecordingState: jest.fn(),
  setTrustedKey: jest.fn(),
}));

const native = jest.requireMock<Record<string, jest.Mock>>('@/features/entry/nativeEntry');
const push = router.push as jest.Mock;

const HRM: ConnectorStatus = { id: 'hrm', label: 'HRM', configured: true, state: 'connected', login: 'ymamajonov', enabled: true, expiresAt: null };
const CRM: ConnectorStatus = { id: 'crm', label: 'CRM', configured: true, state: 'connected', login: null, enabled: true, expiresAt: null };

type Listener = (s: string) => void;
let appListeners: Listener[] = [];
const appState = AppState as unknown as { addEventListener: jest.Mock };

function chatWith(connectors: ConnectorStatus[] | Error): ChatApi {
  return fakeChatApi({
    connectors: jest.fn(async () => {
      if (connectors instanceof Error) throw connectors;
      return { connectors };
    }),
  });
}

async function renderScreen(Screen: () => React.ReactNode, opts: { chat?: ChatApi; services?: Services } = {}) {
  const services = opts.services ?? fakeServices({ chat: opts.chat ?? chatWith([HRM, CRM]) });
  await render(
    <Providers services={services}>
      <Screen />
    </Providers>,
  );
  return services;
}

/** Alert tugmasini nomi bo'yicha bosish (RN Alert Jest'da oyna ko'rsatmaydi). */
async function pressAlertButton(text: string) {
  const call = (Alert.alert as jest.Mock).mock.calls.at(-1);
  const btn = (call?.[2] as AlertButton[] | undefined)?.find((b) => b.text === text);
  expect(btn).toBeTruthy();
  await act(async () => {
    await btn?.onPress?.();
  });
}

function row(over: Partial<QueueRow> & { clientId: string }): QueueRow {
  return newQueueRow({
    fileUri: `file:///doc/recordings/${over.clientId}.aac`,
    language: 'uz',
    template: 'auto',
    expectedSpeakers: null,
    source: 'app',
    startedAt: '2026-10-10T09:00:00Z',
    ...over,
  });
}

beforeEach(() => {
  Object.assign(mockNative, { available: false, launcher: false, volume: false, tile: 'added' });
  appListeners = [];
  appState.addEventListener.mockImplementation((_type: string, fn: Listener) => {
    appListeners.push(fn);
    return { remove: () => (appListeners = appListeners.filter((l) => l !== fn)) };
  });
  jest.spyOn(Alert, 'alert').mockImplementation(() => {});
  useSettings.getState().set({ uiLang: 'uz', themePref: 'system', keepDays: 0, audioSourceOverride: null });
  useRecorderStore.setState({ machine: initialRecorderState });
  useAuth.getState().setSignedIn({
    actorId: 7,
    actorType: 'EMPLOYEE',
    email: 'y@brb.uz',
    fullName: 'Yusuf Mamajonov',
    position: 'Dasturchi',
    department: null,
    roles: [],
    passwordChangeRequired: false,
  });
  useAuth.getState().setConfig(null);
});

afterEach(() => {
  (Alert.alert as jest.Mock).mockRestore?.();
});

describe('quickMethodCount', () => {
  it('counts the app shortcut always, launcher and volume key only with the native module', () => {
    expect(quickMethodCount({ available: false, launcher: true, volume: true })).toBe(1);
    expect(quickMethodCount({ available: true, launcher: false, volume: false })).toBe(1);
    expect(quickMethodCount({ available: true, launcher: true, volume: false })).toBe(2);
    expect(quickMethodCount({ available: true, launcher: true, volume: true })).toBe(3);
  });

  it('language endonyms are written in their own script', () => {
    expect(LANG_ENDONYM).toEqual({ uz: "O'zbekcha", ru: 'Русский', en: 'English' });
  });
});

describe('Settings hub', () => {
  it('shows one value line per row: connections, quick count, language, theme, version', async () => {
    await renderScreen(SettingsScreen);
    expect(await screen.findByText('HRM, CRM ulangan')).toBeTruthy();
    // Faqat ilova yorlig'i (doim bor) - "1 ta usul yoqilgan" emas: sozlashga undaydi.
    expect(screen.getByText("Faqat ilova yorlig'i")).toBeTruthy();
    expect(screen.getByText("O'zbekcha")).toBeTruthy();
    expect(screen.getByText('Tizim')).toBeTruthy();
    expect(screen.getByText('Versiya 1.0.0')).toBeTruthy();
    // Profil kartasi: ism + lavozim · email.
    expect(screen.getByText('Yusuf Mamajonov')).toBeTruthy();
    expect(screen.getByText('Dasturchi · y@brb.uz')).toBeTruthy();
    expect(screen.getByText('YM')).toBeTruthy();
    // Yozuvlar va vazifalar endi drawer'da - Sozlamalarda faqat sozlama.
    expect(screen.queryByText("Yig'ilish yozuvlari")).toBeNull();
    expect(screen.queryByText("Yig'ilishlardagi vazifalarim")).toBeNull();
  });

  it('names the connector that needs a new sign-in (warn variant)', async () => {
    await renderScreen(SettingsScreen, { chat: chatWith([HRM, { ...CRM, state: 'expired' }]) });
    expect(await screen.findByText('CRM: qayta kirish kerak')).toBeTruthy();
  });

  it('says so when connector status cannot be loaded', async () => {
    await renderScreen(SettingsScreen, { chat: chatWith(new Error('boom')) });
    expect(await screen.findByText("Holatni olib bo'lmadi")).toBeTruthy();
  });

  it('shows "no connections" when nothing is configured', async () => {
    await renderScreen(SettingsScreen, { chat: chatWith([{ ...HRM, configured: false }]) });
    expect(await screen.findByText("Ulanish yo'q")).toBeTruthy();
  });

  it('counts the launcher and volume key once the native module reports them on', async () => {
    Object.assign(mockNative, { available: true, launcher: true, volume: true });
    await renderScreen(SettingsScreen);
    expect(await screen.findByText('3 ta usul yoqilgan')).toBeTruthy();
  });

  it('every row opens its own screen', async () => {
    useAuth.getState().setConfig({} as MeetingsConfig);
    await renderScreen(SettingsScreen);
    await screen.findByText('HRM, CRM ulangan');
    const cases: [string, string][] = [
      ['settings-profile', '/settings/account'],
      ['settings-connections', '/settings/connections'],
      ['settings-quick', '/settings/quick'],
      ['settings-recording', '/settings/recording'],
      ['settings-language', '/settings/language'],
      ['settings-theme', '/settings/theme'],
      ['settings-about', '/settings/about'],
    ];
    for (const [id, path] of cases) {
      await fireEvent.press(screen.getByTestId(id));
      expect(push).toHaveBeenLastCalledWith(path);
    }
  });

  it('"Yozish va xotira" appears only when recordings are visible; value = keep policy + queue', async () => {
    const services = fakeServices({ chat: chatWith([HRM, CRM]) });
    await services.queue.insert(row({ clientId: 'a', state: 'stopped' }));
    await services.queue.insert(row({ clientId: 'b', state: 'failed', lastError: 'too_large' }));
    await services.queue.insert(row({ clientId: 'c', state: 'done' }));
    useSettings.getState().set({ keepDays: 7 });
    await renderScreen(SettingsScreen, { services });
    expect(await screen.findByText('Telefonda 7 kun · 2 ta navbatda')).toBeTruthy();
  });

  it('hides "Yozish va xotira" without config, recording or local rows', async () => {
    await renderScreen(SettingsScreen);
    await screen.findByText('HRM, CRM ulangan');
    expect(screen.queryByTestId('settings-recording')).toBeNull();
    await act(async () => useAuth.getState().setConfig({} as MeetingsConfig));
    expect(await screen.findByText("Yuklangach telefondan o'chadi")).toBeTruthy();
  });

  it('logout is disabled while recording and says why', async () => {
    useRecorderStore.setState({ machine: { ...initialRecorderState, status: 'recording', startedAt: Date.now(), segmentStartedAt: Date.now() } });
    await renderScreen(SettingsScreen);
    const logout = await screen.findByTestId('settings-logout');
    expect(logout).toBeDisabled();
    expect(screen.getByText("Avval yozuvni to'xtating")).toBeTruthy();
    await fireEvent.press(logout);
    expect(Alert.alert).not.toHaveBeenCalled();
  });

  it('logout confirms with the pending count, then wipes queue and files and signs out', async () => {
    const services = fakeServices({ chat: chatWith([HRM, CRM]) });
    const remove = jest.spyOn(services.files, 'remove');
    await services.queue.insert(row({ clientId: 'a', state: 'stopped' }));
    await renderScreen(SettingsScreen, { services });
    await screen.findByText('HRM, CRM ulangan');
    await waitFor(() => expect(screen.getByTestId('settings-recording')).toBeTruthy());
    await fireEvent.press(screen.getByTestId('settings-logout'));
    expect((Alert.alert as jest.Mock).mock.calls[0][1]).toMatch(/^1 ta yozuv hali yuklanmagan/);
    await pressAlertButton('Chiqish');
    const logout = services.session.logout as jest.Mock;
    expect(logout).toHaveBeenCalledTimes(1);
    // Tozalash callback'i sessiya bilan birga ishlaydi.
    await act(async () => {
      await logout.mock.calls[0][0]();
    });
    expect(remove).toHaveBeenCalledWith('file:///doc/recordings/a.aac');
    expect(await services.queue.list()).toEqual([]);
    expect(useAuth.getState().status).toBe('signedOut');
  });
});

describe('Language and theme', () => {
  it('language rows: endonym + local name; tapping switches immediately and moves the check', async () => {
    await renderScreen(LanguageScreen);
    expect(screen.getByTestId('uilang-uz')).toBeChecked();
    expect(within(screen.getByTestId('uilang-ru')).getByText('Русский')).toBeTruthy();
    expect(within(screen.getByTestId('uilang-ru')).getByText('Ruscha')).toBeTruthy();
    // Endonim bilan bir xil bo'lsa ikkinchi qator yo'q.
    expect(within(screen.getByTestId('uilang-uz')).queryAllByText("O'zbekcha")).toHaveLength(1);
    await fireEvent.press(screen.getByTestId('uilang-ru'));
    expect(useSettings.getState().uiLang).toBe('ru');
    expect(screen.getByTestId('uilang-ru')).toBeChecked();
    expect(screen.getByTestId('uilang-uz')).not.toBeChecked();
    expect(push).not.toHaveBeenCalled();
  });

  it('theme-dark sets themePref', async () => {
    await renderScreen(ThemeScreen);
    expect(screen.getByTestId('theme-system')).toBeChecked();
    expect(screen.getByText('Telefonga ergashadi')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('theme-dark'));
    expect(useSettings.getState().themePref).toBe('dark');
    expect(screen.getByTestId('theme-dark')).toBeChecked();
  });
});

describe('Connections', () => {
  it('lists connectors with status pills and login', async () => {
    await renderScreen(ConnectionsScreen, { chat: chatWith([HRM, { ...CRM, state: 'expired' }, { id: 'x', label: '', configured: false, state: 'disconnected', login: null, enabled: false, expiresAt: null }]) });
    expect(await screen.findByText('ymamajonov sifatida')).toBeTruthy();
    expect(screen.getByTestId('conn-hrm-status').props.children).toBe('Ulangan');
    expect(screen.getByTestId('conn-crm-status').props.children).toBe('Muddati tugagan');
    expect(screen.getByTestId('conn-x-status').props.children).toBe('Sozlanmagan');
    expect(screen.getByText('X')).toBeTruthy();
    expect(within(screen.getByTestId('conn-hrm')).getByTestId('icon-UsersRound')).toBeTruthy();
  });

  it('load error -> retry', async () => {
    const connectors = jest.fn(async () => {
      throw new Error('boom');
    });
    await renderScreen(ConnectionsScreen, { chat: fakeChatApi({ connectors }) });
    expect(await screen.findByText("Holatni olib bo'lmadi")).toBeTruthy();
    connectors.mockImplementation(async () => {
      return { connectors: [HRM] } as never;
    });
    await fireEvent.press(screen.getByTestId('connections-retry'));
    expect(await screen.findByText('ymamajonov sifatida')).toBeTruthy();
  });

  it('re-login asks first, then aborts the chat and ends only the session (queue kept)', async () => {
    const services = fakeServices({ chat: chatWith([HRM]) });
    await services.queue.insert(row({ clientId: 'a', state: 'stopped' }));
    const abort = jest.spyOn(useChat.getState(), 'abort');
    await renderScreen(ConnectionsScreen, { services });
    await screen.findByText('ymamajonov sifatida');
    await fireEvent.press(screen.getByTestId('settings-reconnect'));
    expect(services.session.logout).not.toHaveBeenCalled();
    await pressAlertButton('Qayta kirish');
    expect(abort).toHaveBeenCalled();
    expect(services.session.logout).toHaveBeenCalledWith();
    expect(await services.queue.list()).toHaveLength(1);
  });
});

describe('Quick record', () => {
  it('without the native module: only the app shortcut works, the rest say "not on this phone"', async () => {
    await renderScreen(QuickRecordScreen);
    expect(screen.getByText('Ilovani ochmasdan yozishni boshlang')).toBeTruthy();
    expect(screen.queryByTestId('launcher-toggle')).toBeNull();
    expect(screen.getAllByText("Bu telefonda yo'q")).toHaveLength(4);
    expect(screen.getByTestId('volume-status').props.children).toBe("Bu telefonda yo'q");
    expect(screen.getByTestId('volume-open')).toBeDisabled();
    expect(screen.getByTestId('tile-add')).toBeDisabled();
    expect(within(screen.getByTestId('quick-shortcut')).getByText('Doim bor')).toBeTruthy();
  });

  it('how-to steps stay closed until asked for', async () => {
    await renderScreen(QuickRecordScreen);
    expect(screen.queryByText(/^Samsung:/)).toBeNull();
    await fireEvent.press(screen.getByTestId('quick-side-howto'));
    expect(screen.getByText(/^Samsung:/)).toBeTruthy();
    expect(screen.getByText(/^Pixel:/)).toBeTruthy();
    expect(screen.queryByText("Telefon qulfdan chiqarilgan bo'lishi kerak.")).toBeNull();
    await fireEvent.press(screen.getByTestId('quick-limits'));
    expect(screen.getByText("Telefon qulfdan chiqarilgan bo'lishi kerak.")).toBeTruthy();
  });

  it('launcher switch turns the icon on; the side key then stops asking for it', async () => {
    mockNative.available = true;
    await renderScreen(QuickRecordScreen);
    expect(within(screen.getByTestId('quick-side')).getByText('Avval belgini yoqing')).toBeTruthy();
    await fireEvent(screen.getByTestId('launcher-toggle'), 'valueChange', true);
    expect(native.setLauncherEnabled).toHaveBeenCalledWith(true);
    expect(screen.getByTestId('launcher-toggle').props.on).toBe(true);
    expect(within(screen.getByTestId('quick-side')).getByText('Telefonda sozlanadi')).toBeTruthy();
  });

  it('volume key: opens accessibility settings and re-reads the state when the app comes back', async () => {
    mockNative.available = true;
    await renderScreen(QuickRecordScreen);
    expect(screen.getByTestId('volume-status').props.children).toBe("O'chiq");
    // Android "to'liq boshqaruv" ogohlantirishidan OLDIN: yo'l va xotirjamlik ochiq ko'rinadi.
    const volumeCard = screen.getByTestId('quick-volume');
    expect(within(volumeCard).getByText(/O'rnatilgan ilovalar/)).toBeTruthy();
    expect(within(volumeCard).getByText("Barno faqat shu tugmani kuzatadi, ekrandagi matnni o'qimaydi.")).toBeTruthy();
    await fireEvent.press(screen.getByTestId('volume-open'));
    expect(native.openAccessibilitySettings).toHaveBeenCalled();
    mockNative.volume = true;
    await act(async () => appListeners.forEach((l) => l('active')));
    expect(screen.getByTestId('volume-status').props.children).toBe('Yoqilgan');
    expect(screen.getByText('Sozlamada boshqarish')).toBeTruthy();
  });

  it('tile request: shows the result; "unsupported" opens the manual steps', async () => {
    mockNative.available = true;
    await renderScreen(QuickRecordScreen);
    expect(screen.queryByTestId('tile-status')).toBeNull();
    await act(async () => {
      await fireEvent.press(screen.getByTestId('tile-add'));
    });
    expect(screen.getByText("Plitka qo'shildi")).toBeTruthy();
    expect(screen.queryByTestId('quick-tile-howto-content')).toBeNull();
    mockNative.tile = 'unsupported';
    await act(async () => {
      await fireEvent.press(screen.getByTestId('tile-add'));
    });
    expect(screen.getByText("So'rov ishlamadi - qo'lda qo'shing")).toBeTruthy();
    expect(within(screen.getByTestId('quick-tile-howto-content')).getByText(/Tahrirlash/)).toBeTruthy();
  });
});

describe('Recording & storage', () => {
  it('keep policy is a radio list; queue shows the count and "upload now" runs the uploader', async () => {
    const services = fakeServices();
    await services.queue.insert(row({ clientId: 'a', state: 'stopped' }));
    await renderScreen(RecordingSettingsScreen, { services });
    expect(screen.getByTestId('keep-0')).toBeChecked();
    await fireEvent.press(screen.getByTestId('keep-7'));
    expect(useSettings.getState().keepDays).toBe(7);
    expect(screen.getByTestId('keep-7')).toBeChecked();
    expect(await screen.findByText('1 ta kutmoqda')).toBeTruthy();
    await act(async () => {
      await fireEvent.press(screen.getByTestId('queue-upload'));
    });
    expect(services.uploader.runOnce).toHaveBeenCalled();
  });

  it('empty queue: no upload button', async () => {
    await renderScreen(RecordingSettingsScreen);
    expect(await screen.findByText('Hammasi yuklangan')).toBeTruthy();
    expect(screen.queryByTestId('queue-upload')).toBeNull();
    expect(screen.getByText("Uzoq yozuv to'xtab qolmasin")).toBeTruthy();
    // Batareya sozlamasida nima qilish kerakligi - so'ralganda.
    expect(screen.queryByText(/^Samsung/)).toBeNull();
    await fireEvent.press(screen.getByTestId('battery-howto'));
    expect(screen.getByText(/^Samsung/)).toBeTruthy();
  });
});

describe('Profile and about', () => {
  it('profile shows HRM fields, missing ones say "not set"', async () => {
    await renderScreen(AccountScreen);
    expect(screen.getByText('Yusuf Mamajonov')).toBeTruthy();
    expect(within(screen.getByTestId('account-email')).getByText('y@brb.uz')).toBeTruthy();
    expect(within(screen.getByTestId('account-position')).getByText('Dasturchi')).toBeTruthy();
    expect(within(screen.getByTestId('account-department')).getByText("Ko'rsatilmagan")).toBeTruthy();
  });

  it('about shows version and server', async () => {
    await renderScreen(AboutScreen);
    expect(within(screen.getByTestId('about-version')).getByText('1.0.0')).toBeTruthy();
    expect(within(screen.getByTestId('about-server')).getByText('https://x.uz')).toBeTruthy();
  });
});
