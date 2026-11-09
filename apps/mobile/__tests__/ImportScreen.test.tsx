/**
 * "Ulashish -> Barno AI" tasdiq ekrani: ulashilgan fayllar (asl nom, suhbatdosh, hajm),
 * qabul qilinmaganlar soni, suhbat tili, "Yuborish" -> fayl recordings/ ga ko'chadi va
 * navbat qatori (source share) yoziladi, "Bekor qilish" -> imports/ tozalanadi.
 * Avtomatik yuborish YO'Q: kalitli havola ham faqat tasdiq ekranini ochadi.
 * "Audio yuklash" yozgan mp3/wav/ogg: native ularni tanimaydi - meta JS'da o'qiladi, tozalash JS'da.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react-native';
import { router } from 'expo-router';
import { Alert, type AlertButton } from 'react-native';

import ImportScreen from '@/app/import';
import { useAuth } from '@/features/auth/authStore';
import { __setCallsStorage, useCalls } from '@/features/calls/callsStore';
import type { ImportMeta } from '@/features/entry/nativeEntry';
import { useSettings } from '@/features/settings/settingsStore';
import { createMemoryQueueStore } from '@/features/upload/queueStore.memory';
import type { Services } from '@/services';

import { fakeServices, Providers } from './fixtures/fakeServices';
import { config, loginResponse } from './fixtures/server';

const mockParams: { value: Record<string, string> } = { value: {} };
jest.mock('expo-router', () => ({
  router: { push: jest.fn(), replace: jest.fn(), dismissTo: jest.fn(), navigate: jest.fn(), back: jest.fn(), canGoBack: jest.fn(() => true) },
  Stack: { Screen: () => null },
  useLocalSearchParams: () => mockParams.value,
  useFocusEffect: () => {},
}));

const mockImports = new Map<string, ImportMeta>();
jest.mock('@/features/entry/nativeEntry', () => ({
  ...jest.requireActual('@/features/entry/nativeEntry'),
  getImportMeta: jest.fn(async (name: string) => mockImports.get(name) ?? null),
  removeImport: jest.fn(() => true),
}));
const native = jest.requireMock<Record<string, jest.Mock>>('@/features/entry/nativeEntry');

// "Audio yuklash" yozgan mp3/wav/ogg uchun JS `imports/` (expo-file-system o'rniga).
const mockJs = new Map<string, { size: number; meta: Record<string, unknown> | null }>();
const mockJsRemoved: string[] = [];
jest.mock('@/features/calls/pickAudio', () => ({
  ...jest.requireActual('@/features/calls/pickAudio'),
  appImportsDir: () => ({
    exists: (name: string) => mockJs.has(name),
    copyIn: async () => 0,
    head: () => new Uint8Array(),
    writeMeta: () => {},
    readMeta: (name: string) => mockJs.get(name)?.meta ?? null,
    stat: (name: string) => (mockJs.has(name) ? { path: `/data/user/0/app/files/imports/${name}`, size: mockJs.get(name)!.size } : null),
    remove: (name: string) => {
      mockJsRemoved.push(name);
      mockJs.delete(name);
    },
    freeBytes: () => null,
    sweep: () => {},
  }),
}));

const mockMoved: [string, string][] = [];
jest.mock('expo-file-system', () => ({
  File: class {
    uri: string;
    constructor(uri: string) {
      this.uri = uri;
    }
    moveSync(target: { uri: string }) {
      mockMoved.push([this.uri, target.uri]);
    }
  },
}));
jest.mock('@/lib/paths', () => ({
  recordingFile: (id: string, ext = '.aac') => ({ uri: `file:///doc/recordings/${id}${ext}` }),
  toFileUri: (p: string) => (/^[a-z]+:\/\//i.test(p) ? p : `file://${p}`),
}));
let mockSeq = 0;
jest.mock('expo-crypto', () => ({
  getRandomBytes: (n: number) => Uint8Array.from({ length: n }, (_, i) => (i === 0 ? ++mockSeq : i)),
}));

const alertSpy = jest.spyOn(Alert, 'alert');
// Plaud stekda bo'lsa o'shanga qaytiladi ("Audio yuklash" dan kelganda ikkinchi nusxa ochilmaydi).
const dismissTo = router.dismissTo as jest.Mock;
const back = router.back as jest.Mock;

const A = 'share_1728560000000_0_Call_recording_Alisher_241010_143012.m4a';
const B = 'share_1728560000000_1_notes.aac';
const C = 'share_1728560000000_2_big.m4a';

function meta(fileName: string, over: Partial<ImportMeta> = {}): ImportMeta {
  return {
    fileName,
    path: `/data/user/0/app/files/imports/${fileName}`,
    displayName: fileName,
    contentType: fileName.endsWith('.aac') ? 'audio/aac' : 'audio/mp4',
    sizeBytes: 1_500_000,
    durationMs: 90_000,
    dateMs: null,
    source: 'share',
    ...over,
  };
}

async function renderImport(params: Record<string, string>) {
  mockParams.value = params;
  const services: Services = { ...fakeServices(), queue: createMemoryQueueStore() };
  await render(
    <Providers services={services}>
      <ImportScreen />
    </Providers>,
  );
  return services;
}

beforeEach(() => {
  __setCallsStorage(null);
  mockImports.clear();
  mockJs.clear();
  mockJsRemoved.length = 0;
  mockMoved.length = 0;
  alertSpy.mockReset();
  useSettings.setState({ uiLang: 'uz', lastLanguage: 'uz' });
  useAuth.setState({ status: 'signedIn', user: loginResponse.user, config });
});

describe('Import confirm screen', () => {
  it('lists the shared files with their original names; skipped files are reported', async () => {
    mockImports.set(A, meta(A, { displayName: 'Call recording Alisher_241010_143012.m4a' }));
    mockImports.set(B, meta(B, { displayName: 'Mijoz bilan uchrashuv.aac', sizeBytes: 300_000 }));
    await renderImport({ files: `${A},${B}`, skipped: '2', n: '5' });
    await waitFor(() => expect(screen.getByTestId('import-screen')).toBeTruthy());
    expect(within(screen.getByTestId(`import-item-${A}`)).getByText('Alisher')).toBeTruthy();
    expect(within(screen.getByTestId(`import-item-${B}`)).getByText('Mijoz bilan uchrashuv')).toBeTruthy();
    expect(screen.getByTestId('import-skipped')).toHaveTextContent("2 ta fayl qo'shilmadi (format yoki hajm)");
    expect(screen.getByText('Yuborish (2)')).toBeTruthy();
    expect(native.getImportMeta).toHaveBeenCalledWith(A);
  });

  it('send: consent once, files move into recordings, share rows are queued, then the recordings list', async () => {
    mockImports.set(A, meta(A, { displayName: 'Call recording Alisher_241010_143012.m4a' }));
    mockImports.set(B, meta(B, { displayName: 'Mijoz bilan uchrashuv.aac' }));
    // Server chegarasidan katta - yuborilmaydi, lekin imports/ dan o'chiriladi.
    mockImports.set(C, meta(C, { sizeBytes: config.maxUploadBytes + 1 }));
    const services = await renderImport({ files: `${A},${B},${C}`, n: '6' });
    await waitFor(() => expect(screen.getByTestId('import-send')).toBeTruthy());
    expect(within(screen.getByTestId(`import-item-${C}`)).getByText('150 MB dan katta')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('import-lang-ru'));

    alertSpy.mockImplementationOnce((_t?: string, _m?: string, buttons?: AlertButton[]) => buttons?.find((b) => b.text === 'Tushundim')?.onPress?.());
    await fireEvent.press(screen.getByTestId('import-send'));
    await waitFor(() => expect(dismissTo).toHaveBeenCalledWith('/meetings'));

    const rows = await services.queue.list();
    expect(rows).toHaveLength(2);
    const call = rows.find((r) => r.title === "Qo'ng'iroq: Alisher");
    const notes = rows.find((r) => r.contentType === 'audio/aac');
    expect(call).toMatchObject({ source: 'share', contentType: 'audio/mp4', language: 'ru', expectedSpeakers: 2, state: 'stopped' });
    // Qo'ng'iroq bo'lmagan fayl nomi sarlavha emas - server AI sarlavhasini qo'yadi.
    expect(notes).toMatchObject({ source: 'share', language: 'ru', expectedSpeakers: null, title: null });
    expect(call?.fileUri).toBe(`file:///doc/recordings/${call?.clientId}.m4a`);
    expect(mockMoved).toEqual(
      expect.arrayContaining([[`file:///data/user/0/app/files/imports/${A}`, `file:///doc/recordings/${call?.clientId}.m4a`]]),
    );
    expect(mockMoved).toHaveLength(2);
    // Hammasi (yuborilmagan katta fayl ham) imports/ dan olib tashlandi.
    for (const n of [A, B, C]) expect(native.removeImport).toHaveBeenCalledWith(n);
    expect(services.uploader.runOnce).toHaveBeenCalled();
    expect(useCalls.getState().consentAt).not.toBeNull();
  });

  it('declined consent sends nothing; cancel discards the shared copies', async () => {
    mockImports.set(A, meta(A));
    const services = await renderImport({ files: A, n: '7' });
    await waitFor(() => expect(screen.getByTestId('import-send')).toBeTruthy());
    // Bitta fayl - oddiy "Yuborish"; rozilik hali ko'rilmagan - eslatma Alert'da, sahifada takrorlanmaydi.
    expect(screen.getByText('Yuborish')).toBeTruthy();
    expect(screen.queryByText("Qo'ng'iroqni faqat suhbatdoshni ogohlantirib yozing.")).toBeNull();
    alertSpy.mockImplementationOnce((_t?: string, _m?: string, buttons?: AlertButton[]) => buttons?.find((b) => b.text === 'Bekor qilish')?.onPress?.());
    await fireEvent.press(screen.getByTestId('import-send'));
    expect(await services.queue.list()).toEqual([]);
    expect(mockMoved).toEqual([]);

    await fireEvent.press(screen.getByTestId('import-cancel'));
    expect(native.removeImport).toHaveBeenCalledWith(A);
    expect(back).toHaveBeenCalled();
  });

  it('nothing usable (missing file): honest empty state that leads to the recordings', async () => {
    await renderImport({ files: A, n: '8' });
    await waitFor(() => expect(screen.getByTestId('import-empty')).toBeTruthy());
    expect(screen.getByText("Yuboriladigan fayl yo'q")).toBeTruthy();
    expect(within(screen.getByTestId(`import-item-${A}`)).getByText('Fayl topilmadi')).toBeTruthy();
    // Bo'lim nomi Slack/Telegram'dagi kabi "Plaud" (marshrut va testID o'zgarmagan).
    expect(screen.getByTestId('import-to-recordings')).toHaveTextContent("Plaud'ga o'tish");
    await fireEvent.press(screen.getByTestId('import-to-recordings'));
    expect(dismissTo).toHaveBeenCalledWith('/meetings');
  });

  it('the empty state names the real cause: all too large / all unsupported', async () => {
    mockImports.set(C, meta(C, { sizeBytes: config.maxUploadBytes + 1 }));
    await renderImport({ files: C, n: '10' });
    await waitFor(() => expect(screen.getByTestId('import-empty')).toBeTruthy());
    expect(screen.getByText('Fayl 150 MB dan katta')).toBeTruthy();
    expect(screen.queryByText("Fayl allaqachon yuborilgan yoki o'chirilgan.")).toBeNull();
  });

  it('after consent was seen, the reminder shows only for call recordings', async () => {
    useCalls.getState().set({ consentAt: 1 });
    mockImports.set(A, meta(A, { displayName: 'Call recording Alisher_241010_143012.m4a' }));
    await renderImport({ files: A, n: '11' });
    await waitFor(() => expect(screen.getByTestId('import-send')).toBeTruthy());
    expect(screen.getByText("Qo'ng'iroqni faqat suhbatdoshni ogohlantirib yozing.")).toBeTruthy();

    mockImports.set(B, meta(B, { displayName: 'Mijoz bilan uchrashuv.aac' }));
    await renderImport({ files: B, n: '12' });
    await waitFor(() => expect(screen.getByTestId(`import-item-${B}`)).toBeTruthy());
    expect(screen.queryByText("Qo'ng'iroqni faqat suhbatdoshni ogohlantirib yozing.")).toBeNull();
  });

  it('invalid names from the link are never read', async () => {
    await renderImport({ files: '../../databases/venera-queue.db,x.flac,y.json', n: '9' });
    await waitFor(() => expect(screen.getByTestId('import-empty')).toBeTruthy());
    expect(native.getImportMeta).not.toHaveBeenCalled();
  });

  const MP3 = 'share_1731130000000_0_Kengash_9-noyabr.mp3';
  const WAV = 'share_1731130000000_1_diktofon.wav';
  const OGG = 'share_1731130000000_2_voice.ogg';
  const jsMeta = (displayName: string, contentType: string) => ({ displayName, contentType, sizeBytes: 1, durationMs: 0, dateMs: null, source: 'share' });

  it('"Audio yuklash" files (mp3, wav, ogg): metadata read in JS, sent with their own type, cleaned up in JS', async () => {
    mockImports.set(A, meta(A, { displayName: 'Call recording Alisher_241010_143012.m4a' }));
    mockJs.set(MP3, { size: 2_000_000, meta: jsMeta('Kengash 9-noyabr.mp3', 'audio/mpeg') });
    mockJs.set(WAV, { size: 9_000_000, meta: jsMeta('Diktofon yozuvi.wav', 'audio/wav') });
    // Meta yo'q (yozilmay qolgan) - nom va tur fayl nomidan (native qoidasi bilan bir xil).
    mockJs.set(OGG, { size: 400_000, meta: null });
    const services = await renderImport({ files: `${A},${MP3},${WAV},${OGG}`, n: '20' });
    await waitFor(() => expect(screen.getByTestId('import-send')).toBeTruthy());
    // Sarlavha - asl nom kengaytmasiz (native fayllar kabi).
    expect(within(screen.getByTestId(`import-item-${MP3}`)).getByText('Kengash 9-noyabr')).toBeTruthy();
    expect(within(screen.getByTestId(`import-item-${WAV}`)).getByText('Diktofon yozuvi')).toBeTruthy();
    // Meta'siz fayl ham yuboriladi (tur nomdan - audio/ogg), "Fayl topilmadi" emas.
    expect(within(screen.getByTestId(`import-item-${OGG}`)).queryByText('Fayl topilmadi')).toBeNull();
    expect(screen.getByText('Yuborish (4)')).toBeTruthy();
    // Native faqat o'zi taniydigan nomni o'qiydi.
    expect(native.getImportMeta.mock.calls).toEqual([[A]]);

    alertSpy.mockImplementationOnce((_t?: string, _m?: string, buttons?: AlertButton[]) => buttons?.find((b) => b.text === 'Tushundim')?.onPress?.());
    await fireEvent.press(screen.getByTestId('import-send'));
    await waitFor(() => expect(dismissTo).toHaveBeenCalledWith('/meetings'));

    const rows = await services.queue.list();
    const byType = Object.fromEntries(rows.map((r) => [r.contentType, r]));
    expect(Object.keys(byType).sort()).toEqual(['audio/mp4', 'audio/mpeg', 'audio/ogg', 'audio/wav']);
    expect(byType['audio/mpeg']).toMatchObject({ source: 'share', fileUri: `file:///doc/recordings/${byType['audio/mpeg'].clientId}.mp3`, totalBytes: 2_000_000 });
    expect(byType['audio/wav'].fileUri).toBe(`file:///doc/recordings/${byType['audio/wav'].clientId}.wav`);
    expect(byType['audio/ogg'].fileUri).toBe(`file:///doc/recordings/${byType['audio/ogg'].clientId}.ogg`);
    expect(mockMoved).toEqual(
      expect.arrayContaining([[`file:///data/user/0/app/files/imports/${MP3}`, `file:///doc/recordings/${byType['audio/mpeg'].clientId}.mp3`]]),
    );
    // mp3/wav/ogg ning `.json` i JS'da o'chiriladi (Kotlin `removeImport` bu nomlarni rad etadi).
    expect(new Set(mockJsRemoved)).toEqual(new Set([MP3, WAV, OGG]));
    expect(native.removeImport.mock.calls.map(([n]) => n)).toEqual([A, A]);
  });

  it('cancel: JS-written files are deleted in JS, native ones natively; a vanished JS file says "Fayl topilmadi"', async () => {
    mockImports.set(B, meta(B));
    mockJs.set(MP3, { size: 2_000_000, meta: jsMeta('Kengash.mp3', 'audio/mpeg') });
    await renderImport({ files: `${B},${MP3},${WAV}`, n: '21' });
    await waitFor(() => expect(screen.getByTestId('import-send')).toBeTruthy());
    expect(within(screen.getByTestId(`import-item-${WAV}`)).getByText('Fayl topilmadi')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('import-cancel'));
    expect(mockJsRemoved).toEqual([MP3, WAV]);
    expect(native.removeImport.mock.calls).toEqual([[B]]);
    expect(back).toHaveBeenCalled();
  });
});
