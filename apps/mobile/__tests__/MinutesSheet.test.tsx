/**
 * Bayonnoma varag'i: ochilganda ro'yxat -> tanlangan tilda tayyor hujjat bo'lsa "Ulashish" (Word/PDF
 * `Authorization` bilan keshga -> ulashish oynasi), bo'lmasa "Tayyorlash" -> POST (til DOIM aniq) ->
 * `running` - har 3 s so'rash -> tayyor; 10 daqiqadan keyin "keyinroq qarang". Xatolar sababi bilan:
 * internet, chegara (Retry-After), nutqsiz yozuv, model sozlanmagan, PDF yo'q (Word'da), xato qatori
 * (kod bo'yicha), eski server (404 - qayta urinishsiz), yo'qolgan hujjat (ro'yxat yangilanadi).
 * Chatdagi bayonnoma: hujjat yo'q - «Chatda ko'rsatma berish» (+ ko'rsatmalar soni), tayyor -
 * «O'zgartirish so'rash» (chat rejim chipi bilan); versiya, so'rov, nima o'zgardi, egasi aytgan rais;
 * hali qo'llanmagan ko'rsatmalar («Qo'llash» - `force`siz POST); yangi versiya yozilayotganda oldingisi
 * ulashiladi; yiqilgan tahrir - «Qayta so'rash» (eski so'rov qoralama bo'lib); 2-versiyadan «Qayta yozish»
 * tasdiq so'raydi. Native qatlam (expo-file-system/legacy, expo-sharing) - soxta; tarmoq yo'q.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { Alert, type AlertButton } from 'react-native';

import { ApiClient, ApiError } from '@/api/client';
import { createMeetingsApi, type MeetingsApi } from '@/api/meetings';
import type { MinutesDetail, MinutesView } from '@/api/types';
import { MinutesSheet, resetMinutesMemory, type MinutesSheetProps } from '@/features/meeting/MinutesSheet';
import { MINUTES_POLL_LIMIT_MS, MINUTES_POLL_MS } from '@/features/meeting/minutesModel';
import { useSettings } from '@/features/settings/settingsStore';

import { fakeMeetingsApi, fakeServices, Providers } from './fixtures/fakeServices';
import { minutesChanges, minutesHeader, minutesView, speakers } from './fixtures/server';

jest.mock('expo-file-system/legacy', () => {
  const downloadAsync = jest.fn();
  const cancelAsync = jest.fn(async () => {});
  return {
    cacheDirectory: 'file:///cache/',
    downloadAsync,
    cancelAsync,
    createDownloadResumable: jest.fn((url: string, fileUri: string, opts: unknown, onProgress?: unknown) => ({
      downloadAsync: () => downloadAsync(url, fileUri, opts, onProgress),
      cancelAsync,
    })),
    readAsStringAsync: jest.fn(async () => ''),
    deleteAsync: jest.fn(async () => {}),
    makeDirectoryAsync: jest.fn(async () => {}),
    moveAsync: jest.fn(async () => {}),
  };
});
jest.mock('expo-sharing', () => ({
  isAvailableAsync: jest.fn(async () => true),
  shareAsync: jest.fn(async () => {}),
}));
jest.mock('expo-network', () => ({
  getNetworkStateAsync: jest.fn(async () => ({ isConnected: true, isInternetReachable: true })),
  addNetworkStateListener: jest.fn(() => ({ remove: jest.fn() })),
}));

type Downloaded = { status: number; uri: string; headers: Record<string, string> };
const FS = jest.requireMock('expo-file-system/legacy') as {
  downloadAsync: jest.Mock<Promise<Downloaded>, [string, string, { headers: Record<string, string> }, unknown]>;
  readAsStringAsync: jest.Mock<Promise<string>, [string]>;
  moveAsync: jest.Mock;
};
const Sharing = jest.requireMock('expo-sharing') as { isAvailableAsync: jest.Mock; shareAsync: jest.Mock };

const ID = 'a'.repeat(32);
const DOC = 'f'.repeat(32);
const BASE = `https://x.uz/api/v1/meetings/${ID}`;
const DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
const DOCX_NAME = 'Баённома - Narxlar va hisobot 2026-11-06.docx';
const DOCX_HEADERS = {
  'Content-Type': DOCX_MIME,
  'Cache-Control': 'private, no-store',
  'Content-Disposition': `attachment; filename="bayonnoma.docx"; filename*=UTF-8''${encodeURIComponent(DOCX_NAME)}`,
};

/** Fayl javobi: 2xx - fayl, aks holda server konverti shu faylda. */
function respond(status: number, headers: Record<string, string> = {}, body = '') {
  FS.downloadAsync.mockImplementationOnce(async (_url, fileUri) => {
    if (body) FS.readAsStringAsync.mockResolvedValueOnce(body);
    return { status, uri: fileUri, headers };
  });
}

const running = (over: Partial<MinutesView> = {}) =>
  minutesView({ status: 'running', finishedAt: null, sectionCount: 0, itemCount: 0, notes: [], ...over });
const detail = (v: MinutesView): MinutesDetail => ({ ...v, content: v.status === 'ready' ? { agenda: [] } : null });
const apiErr = (status: number, code: string, retryAfter: number | null = null) => new ApiError(status, code, code, null, retryAfter);

async function open(api: Partial<MeetingsApi> = {}, props: Partial<MinutesSheetProps> = {}) {
  const real = createMeetingsApi(new ApiClient({ baseUrl: 'https://x.uz/' }));
  const meetings = fakeMeetingsApi({ minutesExportUrl: real.minutesExportUrl, ...api });
  const svc = fakeServices({ meetings });
  const onClose = jest.fn();
  const sheet = (visible: boolean) => (
    <Providers services={svc}>
      <MinutesSheet visible={visible} onClose={onClose} meetingId={ID} title="Narxlar va hisobot" meetingLanguage="uz" {...props} />
    </Providers>
  );
  const view = await render(sheet(true));
  // Ro'yxat javobi (mikrotask) - holat chizilsin.
  await act(async () => {});
  return { meetings, onClose, view, sheet };
}

const press = async (testID: string) => {
  await act(async () => {
    await fireEvent.press(screen.getByTestId(testID));
  });
};
const advance = async (ms: number) => {
  await act(async () => {
    await jest.advanceTimersByTimeAsync(ms);
  });
};

beforeEach(() => {
  useSettings.getState().set({ uiLang: 'uz', themePref: 'light' });
  resetMinutesMemory();
  FS.downloadAsync.mockReset();
  FS.readAsStringAsync.mockReset();
  FS.readAsStringAsync.mockResolvedValue('');
  Sharing.isAvailableAsync.mockResolvedValue(true);
});

afterEach(() => {
  jest.useRealTimers();
});

describe('MinutesSheet', () => {
  it('a ready document of the meeting language: draft note, notes, warning count; Word download with auth -> share sheet', async () => {
    const doc = minutesView({ warnings: ['ungrounded_name:Aziz', 'provider_failed:ollama', 'script_mismatch'] });
    const { meetings, onClose } = await open({ minutesList: jest.fn(async () => ({ items: [doc] })) });
    expect(screen.getByTestId('minutes-ready')).toHaveTextContent(/Bayonnoma tayyor: 2 bo'lim, 5 band/);
    // O'zbekcha yig'ilish -> kirill (server qoidasi); format - Word.
    expect(screen.getByTestId('minutes-lang-uz-cyrl')).toBeChecked();
    expect(screen.getByTestId('minutes-lang-uz-latn')).not.toBeChecked();
    expect(screen.getByTestId('minutes-fmt-docx')).toBeChecked();
    expect(screen.getByText('Loyiha')).toBeTruthy();
    expect(screen.getByTestId('minutes-draft')).toHaveTextContent(/^Bu loyiha: «________» joylarini .* kotib yoki hujjat tizimi to'ldiradi\.$/);
    expect(screen.getByTestId('minutes-notes')).toHaveTextContent(/Aniqlashtirish kerak.*Muddat aniq aytilmagan - 2-band/);
    // `provider_failed` - hujjat sifati haqida emas, sanalmaydi.
    expect(screen.getByTestId('minutes-warnings')).toHaveTextContent("Tekshiruvda 2 ta ogohlantirish - hujjatni diqqat bilan ko'zdan kechiring");
    expect(screen.getByTestId('minutes-redo')).toHaveTextContent('Qayta yozish');
    // Asl hujjat (1-versiya): versiya, so'rov, o'zgarishlar va sarlavha qatorlari yo'q; chatsiz - "O'zgartirish" ham.
    for (const id of ['minutes-version', 'minutes-request', 'minutes-changes', 'minutes-header', 'minutes-pending', 'minutes-superseded', 'minutes-edit', 'minutes-guide']) {
      expect([id, screen.queryByTestId(id)]).toEqual([id, null]);
    }

    respond(200, DOCX_HEADERS);
    await press('minutes-share');
    await waitFor(() => expect(Sharing.shareAsync).toHaveBeenCalled());
    const [url, tmp, opts] = FS.downloadAsync.mock.calls[0];
    expect(url).toBe(`${BASE}/minutes/${DOC}/export?format=docx`);
    expect(tmp).toMatch(/^file:\/\/\/cache\/exports\/download-\d+\.part$/);
    expect(opts.headers).toMatchObject({ Authorization: 'Bearer jwt', 'X-Venera-Client': 'mobile', 'Accept-Language': 'uz' });
    const target = `file:///cache/exports/${encodeURIComponent(DOCX_NAME)}`;
    expect(FS.moveAsync).toHaveBeenCalledWith({ from: tmp, to: target });
    expect(Sharing.shareAsync).toHaveBeenCalledWith(target, { mimeType: DOCX_MIME, dialogTitle: 'Narxlar va hisobot' });
    expect(onClose).toHaveBeenCalled();
    expect(meetings.createMinutes).not.toHaveBeenCalled();
  });

  it('PDF can be chosen; 503 pdf_unavailable offers "Word\'da ulashish", which switches format and shares', async () => {
    await open({ minutesList: jest.fn(async () => ({ items: [minutesView()] })) });
    await fireEvent.press(screen.getByTestId('minutes-fmt-pdf'));
    expect(screen.getByTestId('minutes-fmt-pdf')).toBeChecked();
    respond(503, { 'Retry-After': '10' }, JSON.stringify({ code: 'pdf_unavailable', message: 'x' }));
    await press('minutes-share');
    expect(await screen.findByTestId('minutes-problem')).toHaveTextContent(/^PDF hozircha tayyorlab bo'lmaydi/);
    expect(FS.downloadAsync.mock.calls[0][0]).toBe(`${BASE}/minutes/${DOC}/export?format=pdf`);
    respond(200, DOCX_HEADERS);
    await act(async () => {
      await fireEvent.press(screen.getByText("Word'da ulashish"));
    });
    await waitFor(() => expect(Sharing.shareAsync).toHaveBeenCalled());
    expect(FS.downloadAsync.mock.calls[1][0]).toBe(`${BASE}/minutes/${DOC}/export?format=docx`);
    expect(screen.getByTestId('minutes-fmt-docx')).toBeChecked();
  });

  it('export_busy: 429 = my previous file, 503 = server queue; both offer a retry', async () => {
    await open({ minutesList: jest.fn(async () => ({ items: [minutesView()] })) });
    respond(429, { 'Retry-After': '5' }, JSON.stringify({ code: 'export_busy', message: 'x' }));
    await press('minutes-share');
    expect(await screen.findByTestId('minutes-problem')).toHaveTextContent(/^Oldingi fayl hali tayyorlanmoqda/);
    respond(503, {}, JSON.stringify({ code: 'export_busy', message: 'x' }));
    await act(async () => {
      await fireEvent.press(screen.getByText('Qayta urinish'));
    });
    expect(await screen.findByText("Server band - birozdan keyin qayta urinib ko'ring")).toBeTruthy();
    expect(FS.downloadAsync).toHaveBeenCalledTimes(2);
  });

  it('no document yet: "Tayyorlash" POSTs the explicit language -> 202 running -> polls every 3 s -> ready', async () => {
    jest.useFakeTimers();
    const minutes = jest
      .fn<Promise<MinutesDetail>, [string, string]>()
      .mockResolvedValueOnce(detail(running()))
      .mockResolvedValueOnce(detail(minutesView()));
    const { meetings } = await open({ createMinutes: jest.fn(async () => running()), minutes });
    expect(screen.queryByTestId('minutes-ready')).toBeNull();
    await press('minutes-prepare');
    expect(meetings.createMinutes).toHaveBeenCalledWith(ID, { language: 'uz-cyrl', force: false });
    expect(screen.getByTestId('minutes-running')).toHaveTextContent(/Bayonnoma yozilmoqda - odatda 1-3 daqiqa/);
    expect(screen.getByTestId('minutes-running')).toHaveTextContent(/Oynani yopsangiz ham ish davom etadi/);
    expect(screen.getByTestId('minutes-prepare')).toBeDisabled();

    await advance(MINUTES_POLL_MS);
    expect(minutes).toHaveBeenCalledWith(ID, DOC);
    expect(screen.getByTestId('minutes-running')).toBeTruthy();
    await advance(MINUTES_POLL_MS);
    expect(minutes).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId('minutes-ready')).toBeTruthy();
    expect(screen.getByTestId('minutes-share')).not.toBeDisabled();
    // Tayyor - so'rash to'xtadi.
    await advance(30_000);
    expect(minutes).toHaveBeenCalledTimes(2);
  });

  it('a 200 "already running" answer (also with force) is polled exactly like 202; "Qayta yozish" sends force', async () => {
    jest.useFakeTimers();
    const ready = minutesView({ id: 'r'.repeat(32), createdAt: '2026-11-06T05:00:00Z' });
    const createMinutes = jest.fn(async () => running({ createdAt: '2026-11-06T06:10:00Z' }));
    const minutes = jest.fn(async () => detail(running({ createdAt: '2026-11-06T06:10:00Z' })));
    await open({ minutesList: jest.fn(async () => ({ items: [ready] })), createMinutes, minutes });
    await press('minutes-redo');
    expect(createMinutes).toHaveBeenCalledWith(ID, { language: 'uz-cyrl', force: true });
    expect(screen.getByTestId('minutes-running')).toBeTruthy();
    await advance(MINUTES_POLL_MS);
    expect(minutes).toHaveBeenCalledWith(ID, DOC);
  });

  it('still writing after 10 minutes: polling stops with an honest "check later"; "Qayta tekshirish" resumes from the listing', async () => {
    jest.useFakeTimers();
    const minutesList = jest
      .fn<Promise<{ items: MinutesView[] }>, [string]>()
      .mockResolvedValueOnce({ items: [running()] })
      .mockResolvedValueOnce({ items: [minutesView()] });
    const minutes = jest.fn(async () => detail(running()));
    await open({ minutesList, minutes });
    // Ochilganda ro'yxatda yozilayotgan hujjat - so'rash darhol davom etadi.
    expect(screen.getByTestId('minutes-running')).toBeTruthy();
    await advance(MINUTES_POLL_LIMIT_MS + MINUTES_POLL_MS);
    expect(screen.getByTestId('minutes-slow')).toHaveTextContent(/^Bayonnoma odatdagidan uzoq yozilmoqda\. Keyinroq qayta oching/);
    const calls = minutes.mock.calls.length;
    await advance(60_000);
    expect(minutes.mock.calls.length).toBe(calls);
    await press('minutes-recheck');
    expect(minutesList).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId('minutes-ready')).toBeTruthy();
  });

  it('closing does not cancel the server work: reopening resumes polling from the listing', async () => {
    jest.useFakeTimers();
    const minutesList = jest.fn(async () => ({ items: [running()] }));
    const minutes = jest.fn(async () => detail(running()));
    const { view, sheet } = await open({ minutesList, minutes });
    await act(async () => {
      await view.rerender(sheet(false));
    });
    await advance(10 * MINUTES_POLL_MS);
    expect(minutes).not.toHaveBeenCalled();
    await act(async () => {
      await view.rerender(sheet(true));
    });
    await act(async () => {});
    expect(minutesList).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId('minutes-running')).toBeTruthy();
    await advance(MINUTES_POLL_MS);
    expect(minutes).toHaveBeenCalledTimes(1);
  });

  it('a failed row is explained by its code (never the raw message) and "Qayta urinish" prepares again', async () => {
    const bad = minutesView({ status: 'failed', error: { code: 'interrupted', message: 'worker died: KeyError' } });
    const { meetings } = await open({ minutesList: jest.fn(async () => ({ items: [bad] })) });
    expect(screen.getByTestId('minutes-failed')).toHaveTextContent("Bayonnoma yozish uzilib qoldi - qayta urinib ko'ring");
    expect(screen.queryByText(/KeyError/)).toBeNull();
    await press('minutes-retry');
    expect(meetings.createMinutes).toHaveBeenCalledWith(ID, { language: 'uz-cyrl', force: false });
  });

  it('POST errors: offline (retry), rate limit with Retry-After (no retry), speechless recording, model not configured', async () => {
    const createMinutes = jest.fn<Promise<MinutesView>, [string, unknown]>().mockRejectedValueOnce(apiErr(0, 'network'));
    await open({ createMinutes });
    await press('minutes-prepare');
    expect(screen.getByTestId('minutes-problem')).toHaveTextContent(/^Internet yo'q\. Bayonnoma serverda yoziladi/);

    createMinutes.mockRejectedValueOnce(apiErr(429, 'rate_limited', 1200));
    await act(async () => {
      await fireEvent.press(screen.getByText('Qayta urinish'));
    });
    expect(createMinutes).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId('minutes-problem')).toHaveTextContent("Bir soatlik bayonnoma chegarasi tugadi - 20 daqiqadan keyin urinib ko'ring");
    expect(screen.queryByText('Qayta urinish')).toBeNull();

    createMinutes.mockRejectedValueOnce(apiErr(409, 'transcript_empty'));
    await press('minutes-prepare');
    expect(screen.getByTestId('minutes-problem')).toHaveTextContent("Yozuvda nutq topilmadi - bayonnoma uchun gapirilgan yig'ilish yozuvi kerak");

    createMinutes.mockRejectedValueOnce(apiErr(409, 'not_ready'));
    await press('minutes-prepare');
    expect(screen.getByTestId('minutes-problem')).toHaveTextContent(/^Yozuv hali matnga o'girilmagan/);

    createMinutes.mockRejectedValueOnce(apiErr(503, 'llm_not_configured'));
    await press('minutes-prepare');
    expect(screen.getByTestId('minutes-problem')).toHaveTextContent('Bayonnoma xizmati hali sozlanmagan - administratorga murojaat qiling');
    expect(screen.queryByText('Qayta urinish')).toBeNull();
  });

  it('an older backend without minutes routes (404 on the listing): honest "not on the server yet", no retry, nothing to press', async () => {
    const { meetings } = await open({ minutesList: jest.fn(async () => Promise.reject(apiErr(404, 'not_found'))) });
    expect(screen.getByTestId('minutes-problem')).toHaveTextContent('Bayonnoma serverda hali yoqilmagan - server yangilangach ishlaydi');
    expect(screen.queryByText('Qayta urinish')).toBeNull();
    expect(screen.getByTestId('minutes-prepare')).toBeDisabled();
    expect(meetings.createMinutes).not.toHaveBeenCalled();
  });

  it('a 404 on POST also means the server is older; a vanished document while polling refreshes the listing', async () => {
    jest.useFakeTimers();
    const minutesList = jest
      .fn<Promise<{ items: MinutesView[] }>, [string]>()
      .mockResolvedValueOnce({ items: [running()] })
      .mockResolvedValueOnce({ items: [] });
    const minutes = jest.fn(async () => Promise.reject(apiErr(404, 'minutes_not_found')));
    const createMinutes = jest.fn(async () => Promise.reject(apiErr(404, 'not_found')));
    await open({ minutesList, minutes, createMinutes });
    await advance(MINUTES_POLL_MS);
    // Aniq hujjat yo'q: ro'yxat qayta o'qildi, varaq "Tayyorlash" ga qaytdi.
    expect(minutesList).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId('minutes-problem')).toHaveTextContent('Bayonnoma topilmadi - qaytadan tayyorlang');
    expect(screen.queryByTestId('minutes-running')).toBeNull();
    await advance(10 * MINUTES_POLL_MS);
    expect(minutes).toHaveBeenCalledTimes(1);

    await press('minutes-prepare');
    expect(screen.getByTestId('minutes-problem')).toHaveTextContent('Bayonnoma serverda hali yoqilmagan - server yangilangach ishlaydi');
    expect(screen.getByTestId('minutes-prepare')).toBeDisabled();
  });

  it('only a stale document: says the transcript changed and offers "Tayyorlash"', async () => {
    await open({ minutesList: jest.fn(async () => ({ items: [minutesView({ stale: true })] })) });
    expect(screen.getByTestId('minutes-stale')).toHaveTextContent("Matn o'zgargan - avvalgi bayonnoma eskirgan. Yangisini tayyorlang.");
    expect(screen.queryByTestId('minutes-share')).toBeNull();
    expect(screen.getByTestId('minutes-prepare')).not.toBeDisabled();
  });

  it('the default follows the meeting language (en -> English); another language has its own state', async () => {
    await open({ minutesList: jest.fn(async () => ({ items: [minutesView({ language: 'ru' })] })) }, { meetingLanguage: 'en' });
    expect(screen.getByTestId('minutes-lang-en')).toBeChecked();
    expect(screen.queryByTestId('minutes-ready')).toBeNull();
    await fireEvent.press(screen.getByTestId('minutes-lang-ru'));
    expect(screen.getByTestId('minutes-ready')).toBeTruthy();
  });

  it('opened from a chat card («Ochish»): starts in that document language', async () => {
    await open({ minutesList: jest.fn(async () => ({ items: [minutesView({ language: 'ru' })] })) }, { initialLanguage: 'ru' });
    expect(screen.getByTestId('minutes-lang-ru')).toBeChecked();
    expect(screen.getByTestId('minutes-lang-uz-cyrl')).not.toBeChecked();
    expect(screen.getByTestId('minutes-ready')).toBeTruthy();
  });
});

describe('MinutesSheet: directions and edits in chat', () => {
  const REV = 'r'.repeat(32);
  const later = '2026-11-06T06:10:00Z';

  it('no document yet: «Chatda ko\'rsatma berish» with the hint and the count of directions -> opens the chat in direction mode', async () => {
    const onOpenChat = jest.fn();
    await open({ minutesList: jest.fn(async () => ({ items: [], notes: 2 })) }, { onOpenChat });
    expect(screen.getByText("Rais, qatnashchilar, nimaga e'tibor berish - chatga yozing, Barno bayonnomani shunga qarab yozadi")).toBeTruthy();
    expect(screen.getByTestId('minutes-guide-count')).toHaveTextContent("Chatdagi ko'rsatmalar: 2 ta - tayyorlashda hisobga olinadi");
    expect(screen.getByTestId('minutes-guide')).toHaveTextContent("Chatda ko'rsatma berish");
    // "Tayyorlash" o'z joyida - ko'rsatma ixtiyoriy.
    expect(screen.getByTestId('minutes-prepare')).not.toBeDisabled();
    await press('minutes-guide');
    expect(onOpenChat).toHaveBeenCalledWith({ intent: 'note' });
  });

  it('no directions yet (or an older server without the count): the guide without a count', async () => {
    await open({ minutesList: jest.fn(async () => ({ items: [] })) }, { onOpenChat: jest.fn() });
    expect(screen.getByTestId('minutes-guide')).toBeTruthy();
    expect(screen.queryByTestId('minutes-guide-count')).toBeNull();
  });

  it('an older server (404 on the listing) shows no guide', async () => {
    await open({ minutesList: jest.fn(async () => Promise.reject(apiErr(404, 'not_found'))) }, { onOpenChat: jest.fn() });
    expect(screen.queryByTestId('minutes-guide')).toBeNull();
  });

  it('a ready document: no guide; «O\'zgartirish so\'rash» opens the chat in edit mode for the chosen language', async () => {
    const onOpenChat = jest.fn();
    await open({ minutesList: jest.fn(async () => ({ items: [minutesView(), minutesView({ id: REV, language: 'ru' })], notes: 1 })) }, { onOpenChat });
    expect(screen.queryByTestId('minutes-guide')).toBeNull();
    expect(screen.getByTestId('minutes-edit')).toHaveTextContent("O'zgartirish so'rash");
    await press('minutes-edit');
    expect(onOpenChat).toHaveBeenLastCalledWith({ intent: 'revise', language: 'uz-cyrl' });
    await fireEvent.press(screen.getByTestId('minutes-lang-ru'));
    await press('minutes-edit');
    expect(onOpenChat).toHaveBeenLastCalledWith({ intent: 'revise', language: 'ru' });
  });

  it('a revised version: version pill, the request, what changed, the owner-stated chair and attendees ([S#] -> name), "the remaining blanks"', async () => {
    const v2 = minutesView({
      id: REV,
      createdAt: later,
      kind: 'revise',
      version: 2,
      parentId: DOC,
      request: "3-bandda muddat 1-dekabr bo'lsin",
      changes: minutesChanges(),
      header: minutesHeader({ attendees: ['[S1]', "B.Aliyev - bo'lim boshlig'i"] }),
      notesApplied: 1,
    });
    await open({ minutesList: jest.fn(async () => ({ items: [minutesView(), v2] })) }, { onOpenChat: jest.fn(), speakers });
    expect(screen.getByTestId('minutes-version')).toHaveTextContent('2-versiya');
    expect(screen.getByTestId('minutes-request')).toHaveTextContent("So'ralgan o'zgarish: 3-bandda muddat 1-dekabr bo'lsin");
    expect(screen.getByTestId('minutes-changes')).toHaveTextContent("O'zgarishlar: 3-band; qo'shildi: 8; sarlavha qismi");
    expect(screen.getByTestId('minutes-header')).toHaveTextContent("Rais: Boshqaruv raisi A.KarimovQatnashchilar: Aziz, B.Aliyev - bo'lim boshlig'i");
    expect(screen.getByTestId('minutes-draft')).toHaveTextContent("Bu loyiha: qolgan «________» joylarini kotib yoki hujjat tizimi to'ldiradi.");
  });

  it('new directions not in the document yet: «Qo\'llash» sends a plain POST (the server writes a directions revision); meanwhile the old version stays shareable', async () => {
    jest.useFakeTimers();
    const rev = running({ id: REV, createdAt: later, kind: 'revise', version: 2, parentId: DOC });
    const createMinutes = jest.fn(async () => rev);
    const minutes = jest.fn(async () => detail(rev));
    await open({ minutesList: jest.fn(async () => ({ items: [minutesView({ pendingNotes: 2 })], notes: 2 })), createMinutes, minutes }, { onOpenChat: jest.fn() });
    expect(screen.getByTestId('minutes-pending')).toHaveTextContent(/^2 ta yangi ko'rsatma bu bayonnomada hali yo'q/);
    expect(screen.getByTestId('minutes-apply-notes')).toHaveTextContent("Qo'llash");
    await press('minutes-apply-notes');
    expect(createMinutes).toHaveBeenCalledWith(ID, { language: 'uz-cyrl', force: false });
    expect(screen.getByTestId('minutes-running')).toHaveTextContent(/Yangi versiya tayyorlanmoqda - odatda 1-3 daqiqa/);
    // Oldingi versiya: karta, ulashish va yana o'zgartirish so'rash; "Qayta yozish" va «Qo'llash» yo'q.
    expect(screen.getByTestId('minutes-ready')).toBeTruthy();
    expect(screen.getByTestId('minutes-share')).not.toBeDisabled();
    expect(screen.getByTestId('minutes-edit')).not.toBeDisabled();
    expect(screen.queryByTestId('minutes-redo')).toBeNull();
    expect(screen.queryByTestId('minutes-pending')).toBeNull();
    await advance(MINUTES_POLL_MS);
    expect(minutes).toHaveBeenCalledWith(ID, REV);
  });

  it('a revision already running when the sheet opens: the ready card stays, the running card says "a new version"', async () => {
    jest.useFakeTimers();
    const rev = running({ id: REV, createdAt: later, kind: 'revise', version: 2, parentId: DOC });
    await open({ minutesList: jest.fn(async () => ({ items: [minutesView(), rev] })), minutes: jest.fn(async () => detail(rev)) }, { onOpenChat: jest.fn() });
    expect(screen.getByTestId('minutes-running')).toHaveTextContent(/Yangi versiya tayyorlanmoqda/);
    expect(screen.getByTestId('minutes-ready')).toHaveTextContent(/Bayonnoma tayyor: 2 bo'lim, 5 band/);
    expect(screen.getByTestId('minutes-share')).toBeTruthy();
    expect(screen.getByTestId('minutes-edit')).toBeTruthy();
  });

  it('a failed edit says why; «Qayta so\'rash» reopens the chat with the old request as a draft (no full rewrite is offered)', async () => {
    const onOpenChat = jest.fn();
    const bad = minutesView({
      id: 'b'.repeat(32),
      createdAt: later,
      status: 'failed',
      kind: 'revise',
      version: 2,
      parentId: DOC,
      request: '3-bandni olib tashlang',
      error: { code: 'no_change', message: "Bayonnomada o'zgarish bo'lmadi" },
    });
    const { meetings } = await open({ minutesList: jest.fn(async () => ({ items: [minutesView(), bad] })) }, { onOpenChat });
    expect(screen.getByTestId('minutes-failed')).toHaveTextContent("Bayonnomada o'zgarish bo'lmadi - nimani o'zgartirish kerakligini aniqroq yozing");
    expect(screen.getByTestId('minutes-ready')).toBeTruthy();
    expect(screen.queryByTestId('minutes-redo')).toBeNull();
    expect(screen.getByTestId('minutes-resend')).toHaveTextContent("Qayta so'rash");
    await press('minutes-resend');
    expect(onOpenChat).toHaveBeenCalledWith({ intent: 'revise', language: 'uz-cyrl' }, '3-bandni olib tashlang');
    expect(meetings.createMinutes).not.toHaveBeenCalled();
  });

  it('a failed directions revision (no request) retries without force; a failed rewrite of the original still retries with force', async () => {
    const bad = minutesView({ id: 'b'.repeat(32), createdAt: later, status: 'failed', kind: 'revise', version: 2, request: null, error: { code: 'llm_failed', message: 'x' } });
    const { meetings, view } = await open({ minutesList: jest.fn(async () => ({ items: [minutesView({ pendingNotes: 1 }), bad] })) }, { onOpenChat: jest.fn() });
    expect(screen.getByTestId('minutes-failed')).toHaveTextContent("Model bayonnomani tahrirlay olmadi - qayta urinib ko'ring");
    // "Qayta urinish" ko'rsatmalarni o'zi qayta qo'llaydi - alohida «Qo'llash» banneri yo'q.
    expect(screen.queryByTestId('minutes-pending')).toBeNull();
    expect(screen.getByTestId('minutes-redo')).toHaveTextContent('Qayta urinish');
    await press('minutes-redo');
    expect(meetings.createMinutes).toHaveBeenCalledWith(ID, { language: 'uz-cyrl', force: false });
    await view.unmount();

    const failedRewrite = minutesView({ id: 'b'.repeat(32), createdAt: later, status: 'failed', error: { code: 'llm_busy', message: 'x' } });
    const again = await open({ minutesList: jest.fn(async () => ({ items: [minutesView(), failedRewrite] })) }, { onOpenChat: jest.fn() });
    expect(screen.getByTestId('minutes-failed')).toHaveTextContent("Model hozir band - birozdan keyin qayta urinib ko'ring");
    await press('minutes-redo');
    expect(again.meetings.createMinutes).toHaveBeenCalledWith(ID, { language: 'uz-cyrl', force: true });
  });

  it('«Qayta yozish» on version 2+ asks first (chat edits would be lost): cancel does nothing, confirm rewrites with force', async () => {
    const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
    try {
      const v2 = minutesView({ id: REV, createdAt: later, kind: 'revise', version: 2, parentId: DOC });
      const { meetings } = await open({ minutesList: jest.fn(async () => ({ items: [minutesView(), v2] })) });
      await press('minutes-redo');
      expect(alert.mock.calls.at(-1)?.slice(0, 2)).toEqual([
        'Qayta yozish',
        "Qayta yozilsa hujjat yozuvdan yangidan tuziladi: chatda so'ralgan o'zgartirishlar qo'llanmaydi, ko'rsatmalar qo'llanadi. Davom etasizmi?",
      ]);
      let buttons = alert.mock.calls.at(-1)?.[2] as AlertButton[];
      await act(async () => buttons.find((b) => b.text === 'Bekor qilish')?.onPress?.());
      expect(meetings.createMinutes).not.toHaveBeenCalled();
      await press('minutes-redo');
      buttons = alert.mock.calls.at(-1)?.[2] as AlertButton[];
      await act(async () => buttons.find((b) => b.text === 'Qayta yozish')?.onPress?.());
      expect(meetings.createMinutes).toHaveBeenCalledWith(ID, { language: 'uz-cyrl', force: true });
    } finally {
      alert.mockRestore();
    }
  });

  it('written anew after a transcript edit: a banner says earlier edits are not in it; truncated directions get their own line; neither is counted as a check warning', async () => {
    const doc = minutesView({ warnings: ['superseded_revisions:2', 'guidance_truncated:3', 'script_mismatch'] });
    await open({ minutesList: jest.fn(async () => ({ items: [doc] })) });
    expect(screen.getByTestId('minutes-superseded')).toHaveTextContent("Matn tahrirlangani uchun bayonnoma yangidan yozildi - avvalgi o'zgartirishlar kiritilmagan");
    expect(screen.getByTestId('minutes-truncated')).toHaveTextContent("Ko'rsatmalar juda ko'p - eng eskilaridan 3 tasi hisobga olinmadi");
    expect(screen.getByTestId('minutes-warnings')).toHaveTextContent("Tekshiruvda 1 ta ogohlantirish - hujjatni diqqat bilan ko'zdan kechiring");
  });

  it('«Qo\'llash» while earlier edits fill the queue (409 minutes_busy): the reason and a re-check, not "transcript not ready"', async () => {
    const createMinutes = jest.fn(async () => Promise.reject(apiErr(409, 'minutes_busy')));
    await open({ minutesList: jest.fn(async () => ({ items: [minutesView({ pendingNotes: 1 })] })), createMinutes }, { onOpenChat: jest.fn() });
    await press('minutes-apply-notes');
    expect(screen.getByTestId('minutes-problem')).toHaveTextContent(/^Oldingi o'zgartirishlar hali tayyorlanmoqda - tugashini kuting/);
    expect(screen.queryByText(/Yozuv hali matnga o'girilmagan/)).toBeNull();
    expect(screen.getByText('Qayta tekshirish')).toBeTruthy();
  });
});
