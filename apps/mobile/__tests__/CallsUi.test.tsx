/**
 * Qo'ng'iroq yozuvlari ekranlari: "Qo'ng'iroqlar" bo'limi (`CallsPanel` - 2026-11-12 dan Plaud ekranida
 * YO'Q, ega qarori; komponent o'zi sinaladi), rozilik eslatmasi + ruxsat, ro'yxat (suhbatdosh, davomiylik,
 * hajm), "Yuborish" -> navbat qatori, holat pill'lari, avtomatik yuborish kaliti; Sozlamalar ->
 * Qo'ng'iroq yozuvlari sahifasi.
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react-native';
import { router } from 'expo-router';
import type { ReactNode } from 'react';
import { Alert, Linking, PermissionsAndroid, type AlertButton } from 'react-native';

import MeetingsScreen from '@/app/meetings';
import CallsSettingsScreen from '@/app/settings/calls';
import { useAuth } from '@/features/auth/authStore';
import { __resetCallAutoSend, kickCallAutoSend } from '@/features/calls/CallAutoSend';
import { CallsPanel } from '@/features/calls/CallsPanel';
import { __setCallsStorage, useCalls } from '@/features/calls/callsStore';
import { callClientId, callKey } from '@/features/calls/send';
import type { CallRecording } from '@/features/entry/nativeEntry';
import { useRecorderStore } from '@/features/recorder/RecorderProvider';
import { initialRecorderState } from '@/features/recorder/recorderMachine';
import { useSettings } from '@/features/settings/settingsStore';
import { createMemoryQueueStore } from '@/features/upload/queueStore.memory';
import type { Services } from '@/services';

import { fakeServices, Providers } from './fixtures/fakeServices';
import { config, loginResponse } from './fixtures/server';

const mockSearch: { value: Record<string, string> } = { value: {} };
jest.mock('expo-router', () => {
  const React = jest.requireActual<typeof import('react')>('react');
  return {
    router: { push: jest.fn(), replace: jest.fn(), navigate: jest.fn(), back: jest.fn(), canGoBack: jest.fn(() => true) },
    Stack: { Screen: ({ options }: { options?: { headerRight?: () => ReactNode } }) => (options?.headerRight ? options.headerRight() : null) },
    useFocusEffect: (cb: () => void) => React.useEffect(cb, [cb]),
    useLocalSearchParams: () => mockSearch.value,
  };
});

// Native modul holati testdan boshqariladi (qolgan funksiyalar - haqiqiy no-op'lar).
const mockNative = { available: true, permitted: false, recs: [] as CallRecording[] };
jest.mock('@/features/entry/nativeEntry', () => ({
  ...jest.requireActual('@/features/entry/nativeEntry'),
  isCallImportAvailable: jest.fn(() => mockNative.available),
  hasAudioReadPermission: jest.fn(() => mockNative.permitted),
  audioReadPermission: jest.fn(() => 'android.permission.READ_MEDIA_AUDIO'),
  listCallRecordings: jest.fn(async () => (mockNative.permitted ? mockNative.recs : [])),
  copyToAppStorage: jest.fn(async (_uri: string, name: string) => `/data/user/0/app/files/recordings/${name}`),
}));
const native = jest.requireMock<Record<string, jest.Mock>>('@/features/entry/nativeEntry');

const push = router.push as jest.Mock;
const alertSpy = jest.spyOn(Alert, 'alert');
const requestSpy = jest.spyOn(PermissionsAndroid, 'request');

/** Keyingi Alert'da shu matnli tugmani bosadi. */
function answerAlert(text: string) {
  alertSpy.mockImplementationOnce((_title?: string, _msg?: string, buttons?: AlertButton[]) => {
    buttons?.find((b) => b.text === text)?.onPress?.();
  });
}

const NOW = Date.now();
const call = (over: Partial<CallRecording> = {}): CallRecording => ({
  uri: 'content://media/external/audio/media/41',
  displayName: 'Call recording Alisher_241010_143012.m4a',
  relativePath: 'Recordings/Call/',
  sizeBytes: 2_400_000,
  durationMs: 185_000,
  dateMs: NOW - 3 * 60 * 60 * 1000,
  mimeType: 'audio/mp4',
  contentType: 'audio/mp4',
  ...over,
});

async function renderMeetings() {
  const services: Services = { ...fakeServices(), queue: createMemoryQueueStore() };
  await render(
    <Providers services={services}>
      <MeetingsScreen />
    </Providers>,
  );
  return services;
}

/** "Qo'ng'iroqlar" bo'limi o'zi (Plaud ekranida endi yo'q); `onFind` - suhbatdosh bo'yicha qidirish so'rovi. */
async function renderPanel() {
  const services: Services = { ...fakeServices(), queue: createMemoryQueueStore() };
  const onFind = jest.fn();
  await render(
    <Providers services={services}>
      <CallsPanel onFind={onFind} />
    </Providers>,
  );
  return { services, onFind };
}

beforeEach(() => {
  __setCallsStorage(null);
  __resetCallAutoSend();
  mockNative.available = true;
  mockNative.permitted = false;
  mockNative.recs = [];
  mockSearch.value = {};
  alertSpy.mockReset();
  requestSpy.mockReset();
  useSettings.setState({ uiLang: 'uz', lastLanguage: 'uz' });
  useRecorderStore.setState({ machine: initialRecorderState });
  useAuth.setState({ status: 'signedIn', user: loginResponse.user, config, expired: false });
});

describe('Plaud screen', () => {
  it('opens straight on the recordings: no "Yozuvlar | Qo\'ng\'iroqlar" switcher even on a native APK (owner, 2026-11-12)', async () => {
    for (const available of [true, false]) {
      mockNative.available = available;
      await renderMeetings();
      await waitFor(() => expect(screen.getByTestId('meetings-list')).toBeTruthy());
      expect(screen.queryByTestId('meetings-tab-calls')).toBeNull();
      expect(screen.queryByTestId('meetings-tab-recordings')).toBeNull();
      expect(screen.queryByTestId('calls-intro')).toBeNull();
      expect(screen.queryByTestId('calls-settings')).toBeNull();
      await screen.unmount();
    }
  });
});

describe('Calls section (CallsPanel)', () => {
  it('intro -> consent once -> permission -> the list of calls', async () => {
    mockNative.recs = [call(), call({ uri: 'content://m/2', displayName: '+998901234567_241010_101010.m4a', sizeBytes: 300_000, durationMs: 0 })];
    await renderPanel();
    expect(screen.getByTestId('calls-intro')).toBeTruthy();
    expect(screen.getByText("Qo'ng'iroqlarni Barno'ga yuboring")).toBeTruthy();

    answerAlert('Tushundim');
    requestSpy.mockImplementationOnce(async () => {
      mockNative.permitted = true;
      return 'granted';
    });
    await fireEvent.press(screen.getByTestId('calls-enable'));
    await waitFor(() => expect(screen.getByTestId('call-Call recording Alisher_241010_143012.m4a')).toBeTruthy());
    // Rozilik matni aynan kompaniya qoidasini aytadi; ruxsat tizim oynasi tushuntirish bilan.
    expect(alertSpy).toHaveBeenCalledWith('Suhbatdoshni ogohlantiring', expect.stringMatching(/suhbatdoshga ayting - bu kompaniya qoidasi/), expect.any(Array), expect.any(Object));
    expect(requestSpy).toHaveBeenCalledWith('android.permission.READ_MEDIA_AUDIO', expect.objectContaining({ title: 'Audio fayllarga ruxsat' }));
    expect(useCalls.getState()).toMatchObject({ enabled: true, owner: '7' });
    expect(useCalls.getState().consentAt).not.toBeNull();

    const first = screen.getByTestId('call-Call recording Alisher_241010_143012.m4a');
    expect(within(first).getByText('Alisher')).toBeTruthy();
    expect(within(first).getByText(/03:05 · 2,3 MB$/)).toBeTruthy();
    const second = screen.getByTestId('call-+998901234567_241010_101010.m4a');
    expect(within(second).getByText('+998901234567')).toBeTruthy();
    expect(within(second).getByText(/293 KB$/)).toBeTruthy();
    // Avtomatik yuborish standart holatda o'chiq.
    expect(screen.getByText('Faqat siz tanlaganlar')).toBeTruthy();
  });

  it('"Send" copies the file and queues a call row; the card then shows the upload state', async () => {
    useCalls.getState().set({ enabled: true, consentAt: 1, owner: '7' });
    mockNative.permitted = true;
    mockNative.recs = [call()];
    const { services } = await renderPanel();
    const sendBtn = await waitFor(() => screen.getByTestId('call-send-Call recording Alisher_241010_143012.m4a'));
    await fireEvent.press(sendBtn);

    const clientId = callClientId('7', callKey(call()));
    await waitFor(() => expect(screen.getByTestId('call-status-Call recording Alisher_241010_143012.m4a')).toBeTruthy());
    expect(native.copyToAppStorage).toHaveBeenCalledWith(call().uri, `${clientId}.m4a`);
    expect(await services.queue.get(clientId)).toMatchObject({
      source: 'call',
      contentType: 'audio/mp4',
      title: "Qo'ng'iroq: Alisher",
      expectedSpeakers: 2,
      state: 'stopped',
    });
    expect(useCalls.getState().sent[callKey(call())]).toMatchObject({ c: clientId });
    expect(services.uploader.runOnce).toHaveBeenCalled();
    // Navbatdagi qo'ng'iroq bosilsa - telefondagi yozuv sahifasi.
    await fireEvent.press(screen.getByTestId('call-Call recording Alisher_241010_143012.m4a'));
    expect(push).toHaveBeenLastCalledWith(`/meeting/${clientId}?local=1`);
  });

  it('status pills: sent earlier, unsupported format, over the server limit', async () => {
    const sentRec = call({ uri: 'content://m/s', displayName: 'Sent_241010_090000.m4a' });
    useCalls.getState().set({ enabled: true, consentAt: 1, owner: '7' });
    useCalls.getState().markSent(callKey(sentRec), 'cid-1');
    mockNative.permitted = true;
    mockNative.recs = [
      sentRec,
      call({ uri: 'content://m/a', displayName: 'Amr_241010_090000.amr', contentType: null }),
      call({ uri: 'content://m/b', displayName: 'Big_241010_090000.m4a', sizeBytes: config.maxUploadBytes + 1 }),
    ];
    await renderPanel();
    await waitFor(() => expect(screen.getByTestId('call-status-Sent_241010_090000.m4a')).toHaveTextContent('Yuborildi'));
    expect(screen.getByTestId('call-status-Amr_241010_090000.amr')).toHaveTextContent('Format mos emas');
    // Chegara aytiladi - foydalanuvchi nima mumkinligini bilsin.
    expect(screen.getByTestId('call-status-Big_241010_090000.m4a')).toHaveTextContent('150 MB dan katta');
    expect(screen.queryByTestId('call-send-Sent_241010_090000.m4a')).toBeNull();
  });

  it('auto-send switch: warns every time it is turned on (personal calls too), records the moment, off stops it', async () => {
    useCalls.getState().set({ enabled: true, consentAt: 1, owner: '7' });
    mockNative.permitted = true;
    mockNative.recs = [call()];
    await renderPanel();
    await waitFor(() => expect(screen.getByTestId('calls-auto')).toBeTruthy());

    // Ogohlantirish bekor qilinsa - o'chiq qoladi.
    answerAlert('Bekor qilish');
    await fireEvent.press(screen.getByTestId('calls-auto'));
    expect(alertSpy).toHaveBeenLastCalledWith(
      'Avtomatik yuborilsinmi?',
      expect.stringMatching(/shaxsiylari ham - Barno ochilganda/),
      expect.any(Array),
      expect.any(Object),
    );
    expect(useCalls.getState().autoSend).toBe(false);

    const before = Date.now();
    answerAlert('Yoqish');
    await fireEvent.press(screen.getByTestId('calls-auto'));
    await waitFor(() => expect(useCalls.getState().autoSend).toBe(true));
    expect(useCalls.getState().autoSendSince).toBeGreaterThanOrEqual(before);
    // Halol: fon ishi yo'q - Barno ochilganda yuboriladi.
    expect(screen.getByText('Barno ochilganda yuboriladi')).toBeTruthy();
    // Eski qo'ng'iroq (yoqilishdan oldin) avtomatik ketmaydi.
    await act(async () => {});
    expect(native.copyToAppStorage).not.toHaveBeenCalled();
    await fireEvent.press(screen.getByTestId('calls-auto'));
    expect(useCalls.getState().autoSend).toBe(false);
  });

  it('a call still being written cannot be sent yet; calls are grouped by day with only the time on the card', async () => {
    useCalls.getState().set({ enabled: true, consentAt: 1, owner: '7' });
    mockNative.permitted = true;
    const fresh = call({ uri: 'content://m/fresh', displayName: 'Yangi.m4a', durationMs: 0, dateMs: Date.now() - 10_000 });
    mockNative.recs = [fresh];
    await renderPanel();
    await waitFor(() => expect(screen.getByTestId('call-status-Yangi.m4a')).toHaveTextContent('Yozilmoqda'));
    expect(screen.queryByTestId('call-send-Yangi.m4a')).toBeNull();
    expect(screen.getByText('Bugun')).toBeTruthy();
    // Kartada sana yo'q - faqat soat (kun bo'lim sarlavhasida).
    expect(within(screen.getByTestId('call-Yangi.m4a')).getByText(/^\d{2}:\d{2} · 2,3 MB$/)).toBeTruthy();
  });

  it('a sent call opens its summary when the server id is known, otherwise asks to search by the counterpart', async () => {
    const known = call({ uri: 'content://m/k', displayName: 'Known_241010_090000.m4a' });
    const lost = call({ uri: 'content://m/l', displayName: 'Call recording Alisher_241009_090000.m4a' });
    useCalls.getState().set({ enabled: true, consentAt: 1, owner: '7' });
    useCalls.getState().markSent(callKey(known), 'cid-k');
    useCalls.getState().markSent(callKey(lost), 'cid-l');
    useCalls.getState().linkServerIds(new Map([['cid-k', 'srv-42']]));
    mockNative.permitted = true;
    mockNative.recs = [known, lost];
    const { onFind } = await renderPanel();
    await waitFor(() => expect(screen.getByTestId('call-Known_241010_090000.m4a')).toBeTruthy());
    await fireEvent.press(screen.getByTestId('call-Known_241010_090000.m4a'));
    expect(push).toHaveBeenLastCalledWith('/meeting/srv-42');

    await fireEvent.press(screen.getByTestId('call-Call recording Alisher_241009_090000.m4a'));
    expect(onFind).toHaveBeenCalledWith('Alisher');
  });

  it('permission blocked: explains and opens the app settings; no calls -> how to turn on recording', async () => {
    useCalls.getState().set({ enabled: true, consentAt: 1, owner: '7' });
    await renderPanel();
    expect(screen.getByTestId('calls-permission')).toBeTruthy();
    // Android 13+: tizimdagi nom "Musiqa va audio".
    expect(screen.getByText(/"Musiqa va audio" ruxsatini bering/)).toBeTruthy();
    requestSpy.mockResolvedValueOnce('never_ask_again');
    answerAlert('Sozlamalarni ochish');
    await fireEvent.press(screen.getByTestId('calls-grant'));
    await waitFor(() => expect(Linking.openSettings).toHaveBeenCalled());
    expect(alertSpy).toHaveBeenLastCalledWith('Ruxsat kerak', 'Ruxsatlar -> "Musiqa va audio" -> Ruxsat berish', expect.any(Array));
    // "Bekor qilish" tugmasi yo'q: RN baribir tizim oynasini ochadi.
    expect(requestSpy).toHaveBeenLastCalledWith('android.permission.READ_MEDIA_AUDIO', expect.not.objectContaining({ buttonNegative: expect.anything() }));

    mockNative.permitted = true;
    requestSpy.mockResolvedValueOnce('granted');
    await fireEvent.press(screen.getByTestId('calls-grant'));
    await waitFor(() => expect(screen.getByTestId('calls-empty')).toBeTruthy());
    expect(screen.getByText("Qo'ng'iroq yozuvlari yo'q")).toBeTruthy();
    // "Qo'ng'iroqni qanday yozish" - Samsung qadamlari ochiq holda.
    await fireEvent.press(screen.getByTestId('calls-howto'));
    expect(push).toHaveBeenLastCalledWith('/settings/calls?howto=1');
    expect(screen.getByText("Qo'ng'iroqni qanday yozish")).toBeTruthy();
  });

  it('Android 10-12 names the permission the way the system shows it ("Fayllar va media")', async () => {
    native.audioReadPermission.mockReturnValue('android.permission.READ_EXTERNAL_STORAGE');
    try {
      useCalls.getState().set({ enabled: true, consentAt: 1, owner: '7' });
      await renderPanel();
      expect(screen.getByText(/"Fayllar va media" ruxsatini bering/)).toBeTruthy();
    } finally {
      native.audioReadPermission.mockReturnValue('android.permission.READ_MEDIA_AUDIO');
    }
  });

  it('consent declined: nothing is enabled and no permission is asked', async () => {
    await renderPanel();
    answerAlert('Bekor qilish');
    await fireEvent.press(screen.getByTestId('calls-enable'));
    await act(async () => {});
    expect(useCalls.getState().enabled).toBe(false);
    expect(useCalls.getState().consentAt).toBeNull();
    expect(requestSpy).not.toHaveBeenCalled();
  });
});

describe('Settings -> Call recordings', () => {
  async function renderSettings() {
    await render(
      <Providers services={fakeServices()}>
        <CallsSettingsScreen />
      </Providers>,
    );
  }

  it('old APK: says an update is needed', async () => {
    mockNative.available = false;
    await renderSettings();
    expect(screen.getByTestId('calls-update')).toBeTruthy();
    expect(screen.getByText('Yangi versiya kerak')).toBeTruthy();
  });

  it('detection toggle asks consent + permission; auto-send is locked until detection is on and warns before it turns on', async () => {
    await renderSettings();
    expect(screen.getByTestId('calls-auto')).toBeDisabled();
    expect(within(screen.getByTestId('calls-permission-row')).getByText('Berilmagan')).toBeTruthy();

    answerAlert('Tushundim');
    requestSpy.mockImplementationOnce(async () => {
      mockNative.permitted = true;
      return 'granted';
    });
    await fireEvent.press(screen.getByTestId('calls-detect'));
    await waitFor(() => expect(within(screen.getByTestId('calls-permission-row')).getByText('Berilgan')).toBeTruthy());
    expect(useCalls.getState().enabled).toBe(true);
    expect(screen.getByTestId('calls-auto')).not.toBeDisabled();

    answerAlert('Yoqish');
    await fireEvent.press(screen.getByTestId('calls-auto'));
    await waitFor(() => expect(useCalls.getState().autoSend).toBe(true));
    expect(alertSpy).toHaveBeenLastCalledWith('Avtomatik yuborilsinmi?', expect.any(String), expect.any(Array), expect.any(Object));
    // Aniqlash o'chsa avtomatik yuborish ham o'chadi.
    await fireEvent.press(screen.getByTestId('calls-detect'));
    expect(useCalls.getState()).toMatchObject({ enabled: false, autoSend: false });
  });

  it('call language, Samsung steps and the privacy note', async () => {
    useSettings.setState({ lastLanguage: 'uz' });
    await renderSettings();
    expect(screen.getByTestId('calls-lang-uz')).toBeChecked();
    await fireEvent.press(screen.getByTestId('calls-lang-ru'));
    expect(useCalls.getState().language).toBe('ru');
    expect(screen.getByTestId('calls-lang-ru')).toBeChecked();
    expect(screen.queryByTestId('calls-samsung-howto-content')).toBeNull();
    await fireEvent.press(screen.getByTestId('calls-samsung-howto'));
    // Har qo'ng'iroq oldidan ogohlantirish va qo'lda yozish - "hammasini avtomatik yozish" emas.
    expect(screen.getByText('Suhbatdoshga yozayotganingizni ayting')).toBeTruthy();
    expect(screen.getByText("Qo'ng'iroq paytida: uch nuqta -> Qo'ng'iroqni yozish")).toBeTruthy();
    expect(screen.getByText('Avtomatik yozish - faqat tanlangan raqamlar uchun')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('calls-privacy'));
    expect(screen.getByText(/faqat suhbatdoshni ogohlantirib yozing - kompaniya qoidasi/)).toBeTruthy();
    // Avtomatik yuborish nimani yuborishi va qachon ishlashi ochiq aytiladi.
    expect(screen.getByText("Avtomatik: yoqilgandan keyingi barcha qo'ng'iroqlar, shaxsiylari ham")).toBeTruthy();
    expect(screen.getByText('Avtomatik yuborish Barno ochilganda ishlaydi')).toBeTruthy();
  });

  it('"?howto=1" opens the Samsung steps right away; rows follow the setup order', async () => {
    mockSearch.value = { howto: '1' };
    await renderSettings();
    expect(screen.getByTestId('calls-samsung-howto-content')).toBeTruthy();
    const ids = screen.getAllByTestId(/^calls-(detect|permission-row|auto)$/).map((n) => n.props.testID);
    expect(ids).toEqual(['calls-detect', 'calls-permission-row', 'calls-auto']);
    expect(screen.getByText("Qo'ng'iroqlarni ko'rsatish")).toBeTruthy();
    expect(screen.getByText('Audio ruxsati')).toBeTruthy();
  });
});

describe('auto-send runner (app start / foreground)', () => {
  it('sends only calls made after it was turned on, once the file is quiet; never twice', async () => {
    const services: Services = { ...fakeServices(), queue: createMemoryQueueStore() };
    const since = Date.now() - 10 * 60_000;
    useCalls.getState().set({ owner: '7', enabled: true, consentAt: 1, autoSend: true, autoSendSince: since });
    mockNative.permitted = true;
    const fresh = call({ uri: 'content://m/new', displayName: 'Yangi_241010_150000.m4a', dateMs: Date.now() - 2 * 60_000 });
    mockNative.recs = [fresh];
    // 1-skan: hajm hali bir marta ko'rilgan - kutadi (Samsung hali yozayotgan bo'lishi mumkin).
    expect(await kickCallAutoSend(services)).toEqual({ sent: 0, recheck: true });
    expect(native.listCallRecordings).toHaveBeenCalledWith(since, expect.any(Number));
    // 2-skan: hajm o'zgarmagan va 60 s dan oshgan - yuboriladi.
    expect(await kickCallAutoSend(services)).toEqual({ sent: 1, recheck: false });
    const clientId = callClientId('7', callKey(fresh));
    expect(await services.queue.get(clientId)).toMatchObject({ source: 'call', title: "Qo'ng'iroq: Yangi" });
    expect(await kickCallAutoSend(services)).toEqual({ sent: 0, recheck: false });
    expect(native.copyToAppStorage).toHaveBeenCalledTimes(1);
  });

  it('does nothing while signed out, without a known user, without permission or when off', async () => {
    const services: Services = { ...fakeServices(), queue: createMemoryQueueStore() };
    useCalls.getState().set({ owner: '7', enabled: true, consentAt: 1, autoSend: true, autoSendSince: 0 });
    mockNative.recs = [call({ dateMs: Date.now() - 5 * 60_000 })];
    mockNative.permitted = false;
    expect(await kickCallAutoSend(services)).toEqual({ sent: 0, recheck: false });
    mockNative.permitted = true;
    useAuth.setState({ user: null });
    expect(await kickCallAutoSend(services)).toEqual({ sent: 0, recheck: false });
    useAuth.setState({ status: 'signedOut', user: loginResponse.user });
    expect(await kickCallAutoSend(services)).toEqual({ sent: 0, recheck: false });
    // Boshqa odam kirdi: oldingi odamning avtomatik yuborishi unga o'tmaydi.
    useAuth.setState({ status: 'signedIn', user: { ...loginResponse.user, actorId: 99 } });
    expect(await kickCallAutoSend(services)).toEqual({ sent: 0, recheck: false });
    expect(useCalls.getState()).toMatchObject({ owner: '99', enabled: false, autoSend: false });
    expect(native.listCallRecordings).not.toHaveBeenCalled();
  });
});
