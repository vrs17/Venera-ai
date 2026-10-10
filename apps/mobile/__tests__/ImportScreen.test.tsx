/**
 * "Ulashish -> Barno AI" tasdiq ekrani: ulashilgan fayllar (asl nom, suhbatdosh, hajm),
 * qabul qilinmaganlar soni, suhbat tili, "Yuborish" -> fayl recordings/ ga ko'chadi va
 * navbat qatori (source share) yoziladi, "Bekor qilish" -> imports/ tozalanadi.
 * Avtomatik yuborish YO'Q: kalitli havola ham faqat tasdiq ekranini ochadi.
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
  router: { push: jest.fn(), replace: jest.fn(), navigate: jest.fn(), back: jest.fn(), canGoBack: jest.fn(() => true) },
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
const replace = router.replace as jest.Mock;
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
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/meetings'));

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
    await fireEvent.press(screen.getByTestId('import-to-recordings'));
    expect(replace).toHaveBeenCalledWith('/meetings');
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
    await renderImport({ files: '../../databases/venera-queue.db,x.mp3', n: '9' });
    await waitFor(() => expect(screen.getByTestId('import-empty')).toBeTruthy());
    expect(native.getImportMeta).not.toHaveBeenCalled();
  });
});
